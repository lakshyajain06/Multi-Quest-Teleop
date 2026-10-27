"""Use the installed Isaac Lab DeviceBase, without starting the simulator."""
import json
import unittest

import numpy as np
from websockets.sync.client import connect

from multi_quest_teleop.isaaclab import MultiQuestDevice


class IsaacLabDeviceTests(unittest.TestCase):
    def test_custom_actions_and_reset(self):
        with MultiQuestDevice(['a:right'], host='127.0.0.1', port=0,
                              action_mapper=lambda packet: packet[:, :3] * 2) as device:
            receiver=device.receiver
            with connect(f'ws://127.0.0.1:{receiver.port}/input?operator=a&token={device.token}') as client:
                rows=np.zeros((2,15)); rows[:,6]=1; rows[:,9]=1; rows[1,0]=.25
                client.send(json.dumps(dict(version=1,seq=0,controllers=rows.tolist())))
                client.recv()
                np.testing.assert_array_equal(device.advance(),np.zeros((1,3)))
                np.testing.assert_allclose(device.advance(),[[.5,0,0]])
                device.reset()
                np.testing.assert_array_equal(device.advance(),np.zeros((1,3)))
                device.close(); device.close()

    def test_callbacks_run_once_per_press(self):
        events=[]
        with MultiQuestDevice(['a:right'], host='127.0.0.1',port=0) as device:
            device.add_callback(('a:right','primary'),lambda:events.append('pressed'))
            receiver=device.receiver
            with connect(f'ws://127.0.0.1:{receiver.port}/input?operator=a&token={device.token}') as client:
                rows=np.zeros((2,15)); rows[:,6]=1;rows[:,9]=1
                client.send(json.dumps(dict(version=1,seq=0,controllers=rows.tolist())));client.recv()
                device.advance();device.advance()
                rows[1,10]=1
                client.send(json.dumps(dict(version=1,seq=1,controllers=rows.tolist())));client.recv()
                device.advance();device.advance()
                self.assertEqual(events,['pressed'])

    def test_invalid_lifecycle_and_callback(self):
        device=MultiQuestDevice(['a:right'])
        with self.assertRaises(RuntimeError): device.advance()
        with self.assertRaises(ValueError): device.add_callback(('b:left','primary'),lambda:None)
        with self.assertRaises(ValueError): MultiQuestDevice(['a:right'],action_mapper=lambda x:x,retargeters=[object()])

    def test_standard_devicebase_retargeting(self):
        import torch
        class Retargeter:
            def get_requirements(self): return set()
            def retarget(self,packet): return torch.tensor([packet.shape[0]],dtype=torch.float32)
        with MultiQuestDevice(['a:right','b:left','c:right'],host='127.0.0.1',port=0,
                              retargeters=[Retargeter(),Retargeter()]) as device:
            torch.testing.assert_close(device.advance(),torch.tensor([3.,3.]))
