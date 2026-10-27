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

    def test_controller_alignment_uses_the_same_reference_as_the_camera(self):
        anchor=np.array([1,2,3,*Rotation.from_euler('z',90,degrees=True).as_quat()])
        rig=WorldCameraRig(anchor)
        self.assertIsNone(rig.map_tracking_pose([0,0,0,0,0,0,1]))
        head=np.array([0,0,1.6,0,0,0,1.])
        rig.update(head,session=1)
        hand=head.copy();hand[0]=.2
        mapped=rig.map_tracking_pose(hand)
        np.testing.assert_allclose(mapped[:3],[1,2.2,3],atol=1e-6)
        np.testing.assert_allclose(mapped[3:],anchor[3:])
        rig.update(None)
        self.assertIsNone(rig.map_tracking_pose(hand))
