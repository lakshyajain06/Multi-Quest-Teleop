import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from multi_quest_teleop.view import WorldCameraRig

class WorldViewTests(unittest.TestCase):
    def test_relative_translation_and_rotation(self):
        rig=WorldCameraRig([1,2,3,0,0,0,1])
        pose=np.array([0,0,1.6,0,0,0,1.])
        np.testing.assert_allclose(rig.update(pose,session=1),rig.anchor)
        moved=pose.copy();moved[0]=.2
        np.testing.assert_allclose(rig.update(moved,session=1)[:3],[1.2,2,3])
        moved[3:]=Rotation.from_euler('y',30,degrees=True).as_quat()
        np.testing.assert_allclose(rig.update(moved,session=1)[3:],moved[3:])

    def test_tracking_gap_and_new_session_hold_camera_pose(self):
        rig=WorldCameraRig([1,2,3,0,0,0,1]);head=np.array([0,0,0,0,0,0,1.])
        rig.update(head,session=1);head[0]=1;held=rig.update(head,session=1)
        np.testing.assert_allclose(rig.update(None),held)
        head[0]=10;np.testing.assert_allclose(rig.update(head,session=1),held)
        head[0]=20;np.testing.assert_allclose(rig.update(head,session=2),held)
