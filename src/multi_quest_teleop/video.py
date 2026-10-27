"""Per-operator WebRTC output. Encoding runs off the simulation thread."""
import asyncio
from concurrent.futures import CancelledError
from fractions import Fraction
import threading
import time

import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, RTCRtpSender, VideoStreamTrack
from av import VideoFrame

from .encoder import configure_sender, choose_codec


class _LatestVideoTrack(VideoStreamTrack):
    def __init__(self, frame_getter, fps):
        super().__init__()
        self.frame_getter, self.fps = frame_getter, fps
        self.started = None
        self.deadline = None

    async def recv(self):
        while (image := self.frame_getter()) is None:
            await asyncio.sleep(.01)
        now = time.monotonic()
        if self.started is None:
            self.started = now
            self.deadline = now
        await asyncio.sleep(max(0, self.deadline - now))
        self.deadline = max(self.deadline + 1 / self.fps, time.monotonic())
        # Read the newest frame after pacing, rather than encoding one selected
        # before the sleep. The slot is bounded even if rendering outruns encoding.
        record = self.frame_getter()
        if record is not None:
            image, metadata = record
        else:
            image, metadata = image
        frame = VideoFrame.from_ndarray(image, format='rgb24')
        frame.opaque = metadata
        frame.pts = int((time.monotonic() - self.started) * 90000)
        frame.time_base = Fraction(1, 90000)
        return frame


class VideoReturn:
    """One bounded latest-frame slot and WebRTC peer per operator.

    publish() accepts RGB uint8 frames from any source. Camera placement and
    head-joint actions remain application concerns. ICE is LAN-only by default.
    """
    def __init__(self, fps=30, bitrate=24_000_000, codec='auto'):
        if not 1 <= fps <= 60:
            raise ValueError('Video fps must be between 1 and 60')
        if not 250_000 <= bitrate <= 100_000_000:
            raise ValueError('Video bitrate must be between 250 kbps and 100 Mbps')
        self.codec = choose_codec(codec)
        self.bitrate = int(bitrate)
        self.fps = fps
        self.lock = threading.Lock()
        self.frames = {}
        self.formats = {}
        self.channels = {}
        self.encoder_stats = {}
        self.published_at = {}
        self.peers = {}
        self.loop = None
        self.closing = False

    def start(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def publish(self, operator, image, *, layout='mono', projections=None, orientations=None):
        image = np.asarray(image)
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError('Video frames must be H x W x 3 uint8 RGB')
        if min(image.shape[:2]) < 2:
            raise ValueError('Video frames must be at least 2 x 2')
        if layout not in ('mono', 'stereo-sbs'):
            raise ValueError('Video layout must be mono or stereo-sbs')
        metadata = {'layout': layout}
        if layout == 'stereo-sbs':
            if image.shape[1] % 2 or not projections or set(projections) != {'left','right'}:
                raise ValueError('Stereo requires two equal-width eye images and source projections')
            matrices = {}
            for eye, projection in projections.items():
                matrix = np.asarray(projection, dtype=float)
                if matrix.shape != (16,) or not np.isfinite(matrix).all():
                    raise ValueError('Invalid source projection')
                matrices[eye] = matrix.tolist()
            metadata['projections'] = matrices
        if orientations is not None:
            from scipy.spatial.transform import Rotation
            # Convert Z-up tracking quaternions back to native WebXR tracking.
            basis = Rotation.from_euler('x',-90,degrees=True)
            metadata['orientations'] = {
                eye: (basis * Rotation.from_quat(value)).as_quat().tolist()
                for eye,value in orientations.items()
            }
        with self.lock:
            self.formats[operator] = metadata
            self.frames[operator] = np.ascontiguousarray(image).copy()
            self.published_at[operator] = time.monotonic()

    def format(self, operator):
        with self.lock:
            return self.formats.get(operator)

    def _frame(self, operator):
        with self.lock:
            if time.monotonic() - self.published_at.get(operator, 0) > 2.0:
                return None
            image = self.frames.get(operator)
            if image is None:
                return None
            return image, {'video': self.formats[operator], 'published_at': self.published_at[operator]}

    async def _remove(self, operator):
        peer = self.peers.pop(operator, None)
        if peer:
            await peer.close()
        with self.lock:
            self.frames.pop(operator, None)
            self.formats.pop(operator, None)
            self.channels.pop(operator, None)
            self.encoder_stats.pop(operator, None)
            self.published_at.pop(operator, None)

    async def _answer(self, operator, sdp):
        # Keep the most recent camera frame across renegotiation.
        previous = self.peers.pop(operator, None)
        if previous:
            await previous.close()
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers[operator] = peer
        @peer.on('datachannel')
        def on_channel(channel):
            if channel.label == 'frame-meta':
                self.channels[operator] = channel
        def encoded(timestamp, metadata, elapsed_ms, bitrate):
            with self.lock:
                self.encoder_stats[operator] = {'codec':self.codec, 'encode_ms':elapsed_ms, 'bitrate':bitrate}
            if timestamp is not None and metadata and metadata.get('video',{}).get('orientations'):
                def deliver():
                    import json
                    channel = self.channels.get(operator)
                    if channel and channel.readyState == 'open' and channel.bufferedAmount < 65536:
                        channel.send(json.dumps({'rtpTimestamp':timestamp,'video':metadata['video']}))
                self.loop.call_soon_threadsafe(deliver)
        try:
            sender = peer.addTrack(_LatestVideoTrack(lambda: self._frame(operator), self.fps))
            transceiver = next(item for item in peer.getTransceivers() if item.sender is sender)
            transceiver.setCodecPreferences([
                codec for codec in RTCRtpSender.getCapabilities('video').codecs
                if codec.mimeType.lower() in (('video/h264', 'video/rtx') if self.codec == 'nvenc' else ('video/vp8', 'video/rtx'))
            ])
            configure_sender(sender, self.bitrate, self.codec, self.fps, encoded)
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type='offer'))
            await peer.setLocalDescription(await peer.createAnswer())
            return {'type': 'video_answer', 'sdp': peer.localDescription.sdp, 'codec':self.codec}
        except BaseException:
            await self._remove(operator)
            raise

    def answer_async(self, operator, sdp):
        return asyncio.run_coroutine_threadsafe(self._answer(operator, sdp), self.loop)

    def remove(self, operator):
        if self.loop and self.loop.is_running() and not self.closing:
            try:
                asyncio.run_coroutine_threadsafe(self._remove(operator), self.loop).result(timeout=5)
            except CancelledError:
                if not self.closing:
                    raise

    def close(self):
        self.closing = True
        async def shutdown():
            for operator in list(self.peers):
                await self._remove(operator)
            # aiortc may still have ICE tasks scheduled after a peer closes
            # during negotiation. This loop belongs solely to the video service.
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        if self.loop:
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=10)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            self.loop.close()
            self.loop = None
