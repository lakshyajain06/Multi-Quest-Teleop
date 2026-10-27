"""Camera placement independent of robot actions and video transport."""
import numpy as np
from scipy.spatial.transform import Rotation


class WorldCameraRig:
    """Place an HMD-driven spectator camera at an application-defined world pose.

    All poses are XYZW, camera/OpenGL convention. The first valid headset pose
    is the local reference. Tracking loss or reconnection clears that reference
    and resumes from the held world camera pose without a jump.
    """
    def __init__(self, anchor_pose):
        self.pose = np.asarray(anchor_pose, dtype=float).copy()
        if self.pose.shape != (7,) or not np.isfinite(self.pose).all():
            raise ValueError('Camera anchor must be a finite XYZW pose')
        Rotation.from_quat(self.pose[3:])
        self.reference = None
        self.anchor = self.pose.copy()
        self.session = None

    def update(self, head_pose, session=None):
        if head_pose is None:
            self.reference = None
            return self.pose.copy()
        head_pose = np.asarray(head_pose)
        if head_pose.shape != (7,) or not np.isfinite(head_pose).all():
            raise ValueError('Head pose must be a finite XYZW pose')
        if self.reference is None or session != self.session:
            self.reference = head_pose.copy()
            self.anchor = self.pose.copy()
            self.session = session
        origin = Rotation.from_quat(self.reference[3:])
        anchor = Rotation.from_quat(self.anchor[3:])
        self.pose[:3] = self.anchor[:3] + anchor.apply(origin.inv().apply(head_pose[:3] - self.reference[:3]))
        self.pose[3:] = (anchor * origin.inv() * Rotation.from_quat(head_pose[3:])).as_quat()
        return self.pose.copy()

    def map_tracking_pose(self, pose):
        """Map another tracked pose (e.g. a controller) into this camera's world.

        Use the same Z-up tracking basis as update(). Returns None until a
        fresh head reference is available. This keeps hands aligned with the
        displayed world even when the spectator anchor faces a different yaw.
        """
        if self.reference is None:
            return None
        pose = np.asarray(pose, dtype=float)
        if pose.shape != (7,) or not np.isfinite(pose).all():
            raise ValueError('Tracked pose must be a finite XYZW pose')
        origin = Rotation.from_quat(self.reference[3:])
        anchor = Rotation.from_quat(self.anchor[3:])
        result = pose.copy()
        result[:3] = self.anchor[:3] + anchor.apply(origin.inv().apply(pose[:3] - self.reference[:3]))
        result[3:] = (anchor * origin.inv() * Rotation.from_quat(pose[3:])).as_quat()
        return result
