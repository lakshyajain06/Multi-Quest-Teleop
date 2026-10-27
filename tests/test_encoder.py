import importlib.util
from fractions import Fraction
import unittest
import numpy as np


@unittest.skipUnless(importlib.util.find_spec('aiortc'), 'Install the video extra')
class EncoderQualityTests(unittest.TestCase):
    def test_bitrate_budget_is_per_sender_and_adapts_down(self):
        from multi_quest_teleop.encoder import StreamVp8Encoder
        first,second=StreamVp8Encoder(12_000_000),StreamVp8Encoder(3_000_000)
        self.assertEqual(first.target_bitrate,12_000_000)
        self.assertEqual(second.target_bitrate,3_000_000)
        first.target_bitrate=2_000_000
        self.assertEqual(first.target_bitrate,2_000_000)
        first.target_bitrate=30_000_000
        self.assertEqual(first.target_bitrate,12_000_000)
        self.assertEqual(second.target_bitrate,3_000_000)

    def test_detail_survives_real_encoding_better_than_the_stock_budget(self):
        from av import VideoFrame
        from aiortc.codecs.vpx import Vp8Encoder,Vp8Decoder,VpxPayloadDescriptor
        from aiortc.jitterbuffer import JitterFrame
        from multi_quest_teleop.encoder import StreamVp8Encoder
        grey=np.random.default_rng(7).integers(0,256,(256,512),dtype=np.uint8)
        grey=np.repeat(np.repeat(grey,2,axis=0),2,axis=1)
        scores=[]
        for encoder in (Vp8Encoder(),StreamVp8Encoder(12_000_000)):
            decoder=Vp8Decoder();errors=[]
            for index in range(6):
                image=np.repeat(np.roll(grey,index,axis=1)[...,None],3,axis=2)
                frame=VideoFrame.from_ndarray(image,format='rgb24')
                frame.pts=index*4500;frame.time_base=Fraction(1,90000)
                packets,timestamp=encoder.encode(frame,index==0)
                payload=b''.join(VpxPayloadDescriptor.parse(packet)[1] for packet in packets)
                decoded=decoder.decode(JitterFrame(payload,timestamp))[0].to_ndarray(format='rgb24')
                errors.append(np.mean((image.astype(float)-decoded)**2))
            scores.append(10*np.log10(255**2/np.mean(errors)))
        self.assertGreater(scores[1],scores[0]+6)
