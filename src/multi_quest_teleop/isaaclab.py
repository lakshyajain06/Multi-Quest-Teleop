"""Isaac Lab DeviceBase adapter. Import after launching your SimulationApp.

Task-specific IK, robot actions, episode decisions, and recording belong to the
application. The default advance() result is an N x 15 NumPy controller packet.
"""
from collections.abc import Callable

import numpy as np
from isaaclab.devices.device_base import DeviceBase

from .server import WebXRServer


class MultiQuestDevice(DeviceBase):
    """Network input with Isaac Lab's advance/reset/add_callback lifecycle.

    Supply action_mapper(packet) for custom env actions, or Isaac Lab retargeters
    for the standard DeviceBase retargeting path. Without either, advance()
    returns native controller rows in the configured binding order.
    """

    BUTTON_COLUMNS = {"primary": 10, "secondary": 11, "stick_click": 12}

    def __init__(self, bindings, *, action_mapper: Callable | None = None,
                 retargeters=None, **server_options):
        if action_mapper is not None and retargeters:
            raise ValueError('Choose an action_mapper or retargeters')
        super().__init__(retargeters=retargeters)
        self.receiver = WebXRServer(bindings, **server_options)
        self.action_mapper = action_mapper
        self.bindings = tuple(bindings)
        self.callbacks = {}
        self.previous_buttons = np.zeros((len(bindings), 3), dtype=bool)
        self.last_input = np.zeros((len(bindings), 15), dtype=np.float32)
        self.started = False

    @property
    def token(self):
        return self.receiver.token

    def __enter__(self):
        self.receiver.__enter__()
        self.started = True
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.started:
            self.receiver.__exit__(None, None, None)
            self.started = False

    def head_pose(self, operator):
        """Return (Z-up XYZW pose or None, continuity ID), separate from arm input."""
        return self.receiver.head_pose(operator)

    def eye_views(self, operator):
        return self.receiver.eye_views(operator)

    def publish_video(self, operator, rgb, *, layout='mono', projections=None, orientations=None):
        """Send this operator an RGB frame from the application's selected camera."""
        self.receiver.publish_video(operator, rgb, layout=layout, projections=projections, orientations=orientations)

    def reset(self):
        """Disarm all bindings; consumers must release grip before moving again."""
        with self.receiver.lock:
            for generations in self.receiver.generations.values():
                generations += 1
        self.previous_buttons.fill(False)
        self.last_input.fill(0)

    def add_callback(self, key, func):
        """Bind (operator:hand, button_name) to a rising-edge callback.

        Example: add_callback(('a:left', 'primary'), save_episode).
        Callbacks run in advance(), on the simulation thread.
        """
        binding, button = key
        if binding not in self.bindings or button not in self.BUTTON_COLUMNS:
            raise ValueError('Expected (configured binding, primary/secondary/stick_click)')
        if not callable(func):
            raise TypeError('Callback must be callable')
        self.callbacks[key] = func

    def _get_raw_data(self):
        if not self.started:
            raise RuntimeError('Start MultiQuestDevice with a context manager before advance()')
        packet = self.receiver.snapshot()
        self.last_input = packet.copy()
        buttons = (packet[:, 10:13] > .5) & (packet[:, 9:10] == 1)
        rising = buttons & ~self.previous_buttons
        self.previous_buttons = buttons
        for (binding, button), callback in list(self.callbacks.items()):
            if rising[self.bindings.index(binding), self.BUTTON_COLUMNS[button] - 10]:
                callback()
        return self.action_mapper(packet) if self.action_mapper is not None else packet
