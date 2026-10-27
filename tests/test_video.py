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
        with WebXRServer(['a:right','b:right'],host='127.0.0.1',port=0,video=True) as server:
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

    async def test_invalid_frames_are_rejected(self):
        from multi_quest_teleop.video import VideoReturn
        output=VideoReturn()
        for frame in [np.zeros((2,2)), np.zeros((2,2,3),dtype=float)]:
            with self.assertRaises(ValueError): output.publish('a',frame)
