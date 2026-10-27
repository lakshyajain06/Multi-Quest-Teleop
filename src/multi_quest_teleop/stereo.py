"""Projection helpers for streaming native eye views through symmetric cameras."""
import numpy as np


def fit_eye_projection(projection, width, height, near=.05, far=100.):
    """Return (symmetric source projection, K) covering the XR eye frustum.

    WebXR matrices are column-major. Isaac Lab's basic USD camera path cannot
    express asymmetric principal points. Render a covering symmetric frustum,
    then let the client sample it using the original per-eye XR projection.
    This preserves asymmetric eye optics without averaging/canceling offsets.
    """
    matrix = np.asarray(projection, dtype=float).reshape((4, 4), order='F')
    inverse = np.linalg.inv(matrix)
    rays = np.array([inverse @ [x, y, -1., 1.] for x in (-1., 1.) for y in (-1., 1.)])
    if np.any(rays[:, 2] >= -1e-8) or width < 2 or height < 2:
        raise ValueError('Invalid eye projection or render dimensions')
    slopes = rays[:, :2] / -rays[:, 2:3]
    limits = np.max(np.abs(slopes), axis=0)
    focal = min(width / (2 * limits[0]), height / (2 * limits[1]))
    intrinsic = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]], dtype=np.float32)
    source = np.array([[2*focal/width,0,0,0], [0,2*focal/height,0,0],
                       [0,0,-(far+near)/(far-near),-2*far*near/(far-near)], [0,0,-1,0]], dtype=float)
    return source.ravel(order='F').tolist(), intrinsic
