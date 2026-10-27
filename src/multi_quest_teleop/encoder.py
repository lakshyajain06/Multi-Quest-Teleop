"""Per-sender hardware/CPU encoders for the pinned aiortc release.

aiortc 1.15.0 has no public encoder/bitrate setter. Keep this compatibility hook
isolated, guarded, and covered by encode/decode tests; never patch codec globals.
"""
import aiortc
from aiortc.codecs.vpx import Vp8Encoder


class StreamVp8Encoder(Vp8Encoder):
    def __init__(self, max_bitrate):
        if not 250_000 <= max_bitrate <= 100_000_000:
            raise ValueError('Video bitrate must be between 250 kbps and 100 Mbps')
        self.max_bitrate = int(max_bitrate)
        super().__init__()
        self.target_bitrate = self.max_bitrate

    @property
    def target_bitrate(self):
        return self._Vp8Encoder__target_bitrate

    @target_bitrate.setter
    def target_bitrate(self, bitrate):
        # Preserve receiver-estimated bandwidth adaptation, with a configurable
        # ceiling instead of the stock codec's global 1.5 Mbps ceiling.
        self._Vp8Encoder__target_bitrate = max(250_000, min(int(bitrate), self.max_bitrate))


def configure_sender(sender, max_bitrate, codec='vp8', fps=30, on_frame=None):
    if aiortc.__version__ != '1.15.0' or any(not hasattr(sender,name) for name in
                                           ('_RTCRtpSender__encoder','_RTCRtpSender__rtp_timestamp')):
        raise RuntimeError('Configured video encoder requires aiortc==1.15.0')
    encoder = NvencH264Encoder(max_bitrate,fps) if codec == 'nvenc' else StreamVp8Encoder(max_bitrate)
    sender._RTCRtpSender__encoder = _TimedEncoder(encoder,sender,on_frame)


class NvencH264Encoder:
    """H.264 packetization from aiortc, with zero-reorder hardware encoding."""
    def __init__(self, max_bitrate, fps=30):
        from aiortc.codecs.h264 import H264Encoder
        self.packetizer = H264Encoder()
        self.max_bitrate = int(max_bitrate)
        self.target_bitrate = self.max_bitrate
        self.fps = fps
        self.codec = None

    @property
    def target_bitrate(self):
        return self._bitrate

    @target_bitrate.setter
    def target_bitrate(self, bitrate):
        self._bitrate = max(250_000, min(int(bitrate), self.max_bitrate))

    def encode(self, frame, force_keyframe=False):
        import av
        from fractions import Fraction
        from aiortc.mediastreams import VIDEO_TIME_BASE, convert_timebase
        if self.codec and (self.codec.width != frame.width or self.codec.height != frame.height or
                           abs(self._bitrate-self.configured_bitrate)/self.configured_bitrate > .2):
            self.codec = None
        if self.codec is None:
            codec = av.CodecContext.create('h264_nvenc','w')
            codec.width, codec.height = frame.width, frame.height
            codec.pix_fmt = 'yuv420p'
            codec.bit_rate = self._bitrate
            self.configured_bitrate = self._bitrate
            codec.time_base, codec.framerate = Fraction(1,90000), Fraction(self.fps,1)
            codec.max_b_frames = 0
            codec.gop_size = self.fps * 2
            codec.options = {'preset':'p3','tune':'ull','rc':'vbr','cq':'18','zerolatency':'1',
                             'rc-lookahead':'0','delay':'0','profile':'baseline',
                             'maxrate':str(self._bitrate),'bufsize':str(max(1,self._bitrate//self.fps)), 'forced-idr':'1'}
            self.codec = codec
        frame.pict_type = av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE
        data = b''.join(bytes(packet) for packet in self.codec.encode(frame))
        timestamp = convert_timebase(frame.pts,frame.time_base,VIDEO_TIME_BASE)
        return self.packetizer._packetize(self.packetizer._split_bitstream(data)), timestamp

    def pack(self, packet):
        return self.packetizer.pack(packet)


def choose_codec(requested='auto'):
    """Probe actual NVENC initialization, not just FFmpeg's codec listing."""
    if requested not in ('auto','nvenc','vp8'):
        raise ValueError('Video codec must be auto, nvenc, or vp8')
    if requested == 'vp8':
        return 'vp8'
    try:
        import av
        from fractions import Fraction
        frame = av.VideoFrame(256,256,'yuv420p')
        frame.pts,frame.time_base = 0,Fraction(1,90000)
        encoder = NvencH264Encoder(2_000_000)
        packets,_ = encoder.encode(frame,True)
        if not packets:
            raise RuntimeError('NVENC buffered its first frame')
        return 'nvenc'
    except Exception as error:
        if requested == 'nvenc':
            raise RuntimeError(f'NVENC unavailable: {error}') from error
        return 'vp8'


class _TimedEncoder:
    def __init__(self, encoder, sender, on_frame):
        self.encoder,self.sender,self.on_frame = encoder,sender,on_frame
        self.previous_pts = None

    @property
    def target_bitrate(self):
        return self.encoder.target_bitrate

    @target_bitrate.setter
    def target_bitrate(self,value):
        self.encoder.target_bitrate = value

    def encode(self,frame,force_keyframe=False):
        import time
        started = time.monotonic()
        metadata = frame.opaque
        previous_rtp = self.sender._RTCRtpSender__rtp_timestamp
        packets,pts = self.encoder.encode(frame,force_keyframe)
        if packets:
            # RTP sends each completed frame before invoking this encoder again.
            # Infer its random timestamp origin from the previous completed frame.
            timestamp = None if self.previous_pts is None else (previous_rtp-self.previous_pts+pts) & 0xffffffff
            if self.on_frame:
                self.on_frame(timestamp,metadata,(time.monotonic()-started)*1000,self.target_bitrate)
            self.previous_pts = pts
        return packets,pts

    def pack(self,packet):
        return self.encoder.pack(packet)
