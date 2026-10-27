"""Two synthetic Quests: send HMD/controller poses and decode return video.

Use only with simulation. Streams drive small arm and spectator-camera motions.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time

import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from websockets.asyncio.client import connect


async def operator_trial(operator, index, token, args):
    peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    track_future=asyncio.get_running_loop().create_future()
    peer.on('track',lambda track:track_future.set_result(track))
    try:
        peer.addTransceiver('video',direction='recvonly')
        await peer.setLocalDescription(await peer.createOffer())
        async with connect(f'ws://127.0.0.1:{args.port}/input?operator={operator}&token={token}') as socket:
            await socket.send(json.dumps({'type':'video_offer','sdp':peer.localDescription.sdp}))
            answer=json.loads(await socket.recv())
            if answer['type'] != 'video_answer': raise RuntimeError(answer)
            await peer.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type='answer'))
            async def inputs():
                for seq in range(args.samples):
                    distance=min(max(seq-15,0),50)*.0003*(1 if index == 0 else -1)
                    rows=np.zeros((2,15));rows[:,6]=1;rows[:,9]=1
                    rows[1,0]=distance;rows[1,8]=float(seq>=10)
                    if args.hands == 'both':
                        rows[0,0]=-distance;rows[0,8]=float(seq>=10)
                    yaw=min(seq,50)*.002
                    head=[distance*4,1.6,0,0,float(np.sin(yaw/2)),0,float(np.cos(yaw/2)),1]
                    await socket.send(json.dumps(dict(version=1,seq=seq,controllers=rows.tolist(),head=head)))
                    if json.loads(await socket.recv()) != {'ack':seq}: raise RuntimeError('Invalid ACK')
                    await asyncio.sleep(.04)
            async def video():
                track=await asyncio.wait_for(track_future,10)
                frames=[]
                for _ in range(8):
                    frame=await asyncio.wait_for(track.recv(),30)
                    rgb=frame.to_ndarray(format='rgb24');frames.append(rgb)
                if not all(image.dtype == np.uint8 and np.ptp(image) > 10 for image in frames):
                    raise RuntimeError('Blank or invalid decoded simulation frames')
                if args.output:
                    args.output.mkdir(parents=True,exist_ok=True)
                    frame.to_image().save(args.output/f'{operator}.png')
                print(f'{operator}: decoded {len(frames)} nonblank frames {frames[-1].shape}',flush=True)
            await asyncio.gather(inputs(),video())
    finally:
        await peer.close()


async def run(args):
    for _ in range(240):
        text=args.startup_log.read_text(errors='replace') if args.startup_log.exists() else ''
        match=re.search(rf'{args.port}/(?:\?token=([\w-]+))?',text)
        if match: break
        await asyncio.sleep(.5)
    else: raise RuntimeError('Simulation server did not start')
    await asyncio.gather(*(operator_trial(operator,index,match[1] or '',args) for index,operator in enumerate(args.operators)))
    print(f'PASS: {len(args.operators)} HMD uplink(s) and decoded simulation video return streams',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-log',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18443)
    parser.add_argument('--samples',type=int,default=240)
    parser.add_argument('--operators',nargs='+',default=['a','b'])
    parser.add_argument('--hands',choices=['right','both'],default='right')
    parser.add_argument('--output',type=Path)
    asyncio.run(run(parser.parse_args()))
