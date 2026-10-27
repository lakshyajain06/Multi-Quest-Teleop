import json
import unittest
import numpy as np
from websockets.sync.client import connect
from multi_quest_teleop import WebXRServer
from multi_quest_teleop.stereo import fit_eye_projection


def projection(offset=.15):
    return [1.1,0,0,0,0,1.2,0,0,offset,.05,-1.001,-1,0,0,-.10005,0]


class StereoProjectionTests(unittest.TestCase):
    def test_covering_frustum_preserves_asymmetric_eye_rays(self):
        for offset in (-.2,.2):
            target=np.array(projection(offset)).reshape(4,4,order='F')
            source,k=fit_eye_projection(target.ravel(order='F'),640,480)
            source=np.array(source).reshape(4,4,order='F')
            self.assertEqual(k[0,0],k[1,1])
            np.testing.assert_array_equal(k[:2,2],[320,240])
            for x in (-1.,0.,1.):
                for y in (-1.,0.,1.):
                    target_clip=np.array([x,y,-1,1])
                    ray=np.linalg.inv(target)@target_clip
                    rendered=source@ray
                    self.assertTrue(np.all(np.abs(rendered[:2]/rendered[3])<=1.000001))
                    reconstructed=target@np.linalg.inv(source)@rendered
                    np.testing.assert_allclose(reconstructed[:2]/reconstructed[3],[x,y],atol=1e-6)

    def test_eye_pose_and_projection_transport(self):
        with WebXRServer(['a:right'],host='127.0.0.1',port=0) as server:
            with connect(f'ws://127.0.0.1:{server.port}/input?operator=a') as client:
                views=[dict(eye=eye,pose=[x,1.6,0,0,0,0,1],projection=projection(offset))
                       for eye,x,offset in [('left',-.032,.15),('right',.032,-.15)]]
                client.send(json.dumps(dict(version=1,seq=0,controllers=np.zeros((2,15)).tolist(),
                                            head=[0,1.6,0,0,0,0,1,1],views=views)))
                self.assertEqual(json.loads(client.recv()),{'ack':0})
                eyes=server.eye_views('a')
                np.testing.assert_allclose(eyes['left']['pose'][:3],[-.032,0,1.6],atol=1e-6)
                np.testing.assert_allclose(eyes['right']['pose'][:3],[.032,0,1.6],atol=1e-6)
                np.testing.assert_allclose(eyes['left']['projection'],projection(.15))
