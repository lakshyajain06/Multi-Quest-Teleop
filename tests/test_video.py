"""Actual WebRTC encode/decode over local sockets, with separate operators."""
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
import unittest

import numpy as np
from multi_quest_teleop import WebXRServer


@unittest.skipUnless(importlib.util.find_spec('aiortc'), 'Install the video extra')
class VideoReturnTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_operators_receive_their_own_frames_and_send_heads(self):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
        from websockets.asyncio.client import connect
        with WebXRServer(['a:right','b:right'],host='127.0.0.1',port=0,video=True,video_codec='vp8') as server:
            peers=[]; receivers=[]
            try:
                async with AsyncExitStack() as stack:
                    for operator,color in [('a',[220,20,10]),('b',[10,20,220])]:
                        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]));peers.append(peer)
                        track_ready=asyncio.get_running_loop().create_future()
                        peer.on('track',lambda track, future=track_ready: future.set_result(track))
                        peer.addTransceiver('video',direction='recvonly')
                        await peer.setLocalDescription(await peer.createOffer())
                        socket=await stack.enter_async_context(connect(
                            f'ws://127.0.0.1:{server.port}/input?operator={operator}&token={server.token}'))
                        rows=np.zeros((2,15)).tolist()
                        await socket.send(json.dumps(dict(version=1,seq=0,controllers=rows,head=[0,1.6,0,0,0,0,1,1])))
                        self.assertEqual(json.loads(await socket.recv()),{'ack':0})
                        head,_=server.head_pose(operator)
                        np.testing.assert_allclose(head[:3],[0,0,1.6],atol=1e-6)
                        await socket.send(json.dumps(dict(type='video_offer',sdp=peer.localDescription.sdp)))
                        answer=json.loads(await socket.recv());self.assertEqual(answer['type'],'video_answer')
                        await peer.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']))
                        image=np.empty((48,64,3),np.uint8);image[:]=color
                        server.publish_video(operator,image)
                        receivers.append((await asyncio.wait_for(track_ready,5), color))
                    self.assertEqual(len(server.clients),2)
                    async def check(track,color):
                        decoded=await asyncio.wait_for(track.recv(),10)
                        rgb=decoded.to_ndarray(format='rgb24')
                        self.assertEqual(rgb.shape,(48,64,3))
                        np.testing.assert_allclose(rgb.mean(axis=(0,1)),color,atol=12)
                    await asyncio.gather(*(check(track,color) for track,color in receivers))
                    await asyncio.sleep(.3)
                    self.assertIsNone(server.head_pose('a')[0])
                for _ in range(100):
                    if not server.video.frames: break
                    await asyncio.sleep(.01)
                self.assertEqual(set(server.video.frames),set())
            finally:
                await asyncio.gather(*(peer.close() for peer in peers))

    async def test_video_negotiation_does_not_block_controller_acknowledgements(self):
        from aiortc import RTCPeerConnection, RTCConfiguration
        from websockets.asyncio.client import connect
        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        try:
            peer.addTransceiver('video',direction='recvonly')
            await peer.setLocalDescription(await peer.createOffer())
            with WebXRServer(['a:right'],host='127.0.0.1',port=0,video=True,video_codec='vp8') as server:
                original=server.video._answer
                async def slow_answer(operator,sdp):
                    await asyncio.sleep(1)
                    return await original(operator,sdp)
                server.video._answer=slow_answer
                async with connect(f'ws://127.0.0.1:{server.port}/input?operator=a&token={server.token}') as socket:
                    await socket.send(json.dumps(dict(type='video_offer',sdp=peer.localDescription.sdp)))
                    await socket.send(json.dumps(dict(version=1,seq=0,controllers=np.zeros((2,15)).tolist())))
                    reply=json.loads(await asyncio.wait_for(socket.recv(),.75))
                    self.assertEqual(reply,{'ack':0})
                    answer=json.loads(await asyncio.wait_for(socket.recv(),5))
                    self.assertEqual(answer['type'],'video_answer')
                    from aiortc import RTCSessionDescription
                    await peer.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']))
                    for _ in range(100):
                        if peer.connectionState in ('connected','failed'): break
                        await asyncio.sleep(.01)
        finally:
            await peer.close()

    async def test_stereo_video_keeps_left_and_right_images_separate(self):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
        from websockets.asyncio.client import connect
        from multi_quest_teleop.stereo import fit_eye_projection
        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        ready=asyncio.get_running_loop().create_future()
        peer.on('track',lambda track:ready.set_result(track))
        try:
            peer.addTransceiver('video',direction='recvonly')
            await peer.setLocalDescription(await peer.createOffer())
            with WebXRServer(['a:right'],host='127.0.0.1',port=0,video=True,video_codec='vp8') as server:
                async with connect(f'ws://127.0.0.1:{server.port}/input?operator=a') as socket:
                    await socket.send(json.dumps(dict(type='video_offer',sdp=peer.localDescription.sdp)))
                    answer=json.loads(await socket.recv())
                    await peer.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']))
                    image=np.empty((48,128,3),np.uint8)
                    image[:,:64]=[220,20,10];image[:,64:]=[10,20,220]
                    source,_=fit_eye_projection([1,0,0,0,0,1,0,0,0,0,-1.001,-1,0,0,-.10005,0],64,48)
                    server.publish_video('a',image,layout='stereo-sbs',projections={'left':source,'right':source})
                    await socket.send(json.dumps(dict(version=1,seq=0,controllers=np.zeros((2,15)).tolist())))
                    ack=json.loads(await socket.recv())
                    self.assertEqual(ack['video']['layout'],'stereo-sbs')
                    track=await asyncio.wait_for(ready,5)
                    decoded=await asyncio.wait_for(track.recv(),10)
                    rgb=decoded.to_ndarray(format='rgb24')
                    np.testing.assert_allclose(rgb[:,2:62].mean(axis=(0,1)),[220,20,10],atol=12)
                    np.testing.assert_allclose(rgb[:,66:126].mean(axis=(0,1)),[10,20,220],atol=12)
        finally:
            await peer.close()

    async def test_high_resolution_stream_preserves_full_frame_dimensions(self):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
        from websockets.asyncio.client import connect
        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        ready=asyncio.get_running_loop().create_future()
        peer.on('track',lambda track:ready.set_result(track))
        try:
            peer.addTransceiver('video',direction='recvonly')
            await peer.setLocalDescription(await peer.createOffer())
            with WebXRServer(['a:right'],host='127.0.0.1',port=0,video=True,video_bitrate=24_000_000) as server:
                async with connect(f'ws://127.0.0.1:{server.port}/input?operator=a') as socket:
                    await socket.send(json.dumps(dict(type='video_offer',sdp=peer.localDescription.sdp)))
                    answer=json.loads(await socket.recv())
                    self.assertIn('H264' if server.video.codec=='nvenc' else 'VP8',answer['sdp'])
                    if server.video.codec=='nvenc': self.assertNotIn('VP8',answer['sdp'])
                    await peer.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']))
                    image=np.empty((1280,2560,3),np.uint8);image[:,:1280]=[220,20,10];image[:,1280:]=[10,20,220]
                    server.publish_video('a',image)
                    track=await asyncio.wait_for(ready,5)
                    frame=await asyncio.wait_for(track.recv(),10)
                    self.assertEqual((frame.width,frame.height),(2560,1280))
        finally:
            await peer.close()

    async def test_rotation_metadata_matches_decoded_rtp_timestamps(self):
        await self.check_rotation_metadata('vp8')

    async def test_nvenc_rotation_metadata_matches_decoded_frames(self):
        from multi_quest_teleop.encoder import choose_codec
        if choose_codec() != 'nvenc':
            self.skipTest('NVENC not available on this host')
        await self.check_rotation_metadata('nvenc')

    async def check_rotation_metadata(self, codec):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
        from websockets.asyncio.client import connect
        from multi_quest_teleop.stereo import fit_eye_projection
        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        ready=asyncio.get_running_loop().create_future();metadata={}
        peer.on('track',lambda track:ready.set_result(track))
        channel=peer.createDataChannel('frame-meta',ordered=False,maxRetransmits=0)
        channel.on('message',lambda raw:metadata.update({json.loads(raw)['rtpTimestamp']:json.loads(raw)}))
        try:
            peer.addTransceiver('video',direction='recvonly')
            await peer.setLocalDescription(await peer.createOffer())
            with WebXRServer(['a:right'],host='127.0.0.1',port=0,video=True,video_codec=codec) as server:
                async with connect(f'ws://127.0.0.1:{server.port}/input?operator=a') as socket:
                    await socket.send(json.dumps(dict(type='video_offer',sdp=peer.localDescription.sdp)))
                    answer=json.loads(await socket.recv())
                    await peer.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']))
                    image=np.full((256,512,3),120,np.uint8)
                    source,_=fit_eye_projection([1,0,0,0,0,1,0,0,0,0,-1.001,-1,0,0,-.10005,0],256,256)
                    server.publish_video('a',image,layout='stereo-sbs',projections={'left':source,'right':source},
                                         orientations={'left':[.70710678,0,0,.70710678],'right':[.70710678,0,0,.70710678]})
                    track=await asyncio.wait_for(ready,5);matches=0
                    for _ in range(5):
                        frame=await asyncio.wait_for(track.recv(),5)
                        origin=peer.getTransceivers()[0].receiver._RTCRtpReceiver__timestamp_mapper._origin
                        timestamp=(origin+frame.pts)&0xffffffff
                        for _ in range(10):
                            if timestamp in metadata: break
                            await asyncio.sleep(.01)
                        if timestamp in metadata:
                            np.testing.assert_allclose(metadata[timestamp]['video']['orientations']['left'],[0,0,0,1],atol=1e-6)
                            matches+=1
                    self.assertGreaterEqual(matches,2)
        finally:
            await peer.close()

    async def test_invalid_frames_are_rejected(self):
        from multi_quest_teleop.video import VideoReturn
        output=VideoReturn()
        for frame in [np.zeros((2,2)), np.zeros((2,2,3),dtype=float)]:
            with self.assertRaises(ValueError): output.publish('a',frame)
