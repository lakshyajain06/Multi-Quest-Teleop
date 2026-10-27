"""Per-sender VP8 bitrate configuration for the pinned aiortc release.

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


def configure_sender(sender, max_bitrate):
    if aiortc.__version__ != '1.15.0' or not hasattr(sender, '_RTCRtpSender__encoder'):
        raise RuntimeError('Configured VP8 encoder requires aiortc==1.15.0')
    sender._RTCRtpSender__encoder = StreamVp8Encoder(max_bitrate)
