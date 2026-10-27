"""Per-operator WebRTC output. Encoding runs off the simulation thread."""
import asyncio
from concurrent.futures import CancelledError
from fractions import Fraction
import threading
import time

import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame


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
        frame = VideoFrame.from_ndarray(image, format='rgb24')
        frame.pts = int((time.monotonic() - self.started) * 90000)
        frame.time_base = Fraction(1, 90000)
        return frame


class VideoReturn:
    """One bounded latest-frame slot and WebRTC peer per operator.

    publish() accepts RGB uint8 frames from any source. Camera placement and
    head-joint actions remain application concerns. ICE is LAN-only by default.
    """
    def __init__(self, fps=20):
        if not 1 <= fps <= 60:
            raise ValueError('Video fps must be between 1 and 60')
        self.fps = fps
        self.lock = threading.Lock()
        self.frames = {}
        self.formats = {}
        self.published_at = {}
        self.peers = {}
        self.loop = None
        self.closing = False

    def start(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def publish(self, operator, image, *, layout='mono', projections=None):
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
            return self.frames.get(operator)

    async def _remove(self, operator):
        peer = self.peers.pop(operator, None)
        if peer:
            await peer.close()
        with self.lock:
            self.frames.pop(operator, None)
            self.formats.pop(operator, None)
            self.published_at.pop(operator, None)

    async def _answer(self, operator, sdp):
        # Keep the most recent camera frame across renegotiation.
        previous = self.peers.pop(operator, None)
        if previous:
            await previous.close()
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers[operator] = peer
        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type='offer'))
            peer.addTrack(_LatestVideoTrack(lambda: self._frame(operator), self.fps))
            await peer.setLocalDescription(await peer.createAnswer())
            return {'type': 'video_answer', 'sdp': peer.localDescription.sdp}
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
