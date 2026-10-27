# Multi-Quest Teleop

An installable **Isaac Lab input device** for multiple Meta Quest browsers.
The library owns browser transport, HTTPS, operator identity, tracking validity,
input timeouts, coordinate conversion, and button callbacks. Your application
owns the mapping from inputs to robot actions, physics, episode decisions, and
recording. It does not require CloudXR, ROS, or a headset APK.

## Install and integrate

With Isaac Lab already installed:

```bash
pip install -e .
```

Or add this repository as a submodule and install it:

```bash
git submodule add https://github.com/lakshyajain06/Multi-Quest-Teleop.git third_party/multi_quest_teleop
pip install -e third_party/multi_quest_teleop
```

Import the device after your normal Isaac Lab application startup. It implements
Isaac Lab's `DeviceBase`: `advance()`, `reset()`, and `add_callback()`.

```python
from multi_quest_teleop import create_local_certificate
from multi_quest_teleop.isaaclab import MultiQuestDevice

cert, key = create_local_certificate("192.168.1.100")  # workstation LAN IP
with MultiQuestDevice(
    bindings=["a:right", "b:right"],
    cert=cert, key=key,
    allowed_origins=["https://lakshyajain06.github.io"],
    yaw_degrees=[0, 180],
) as teleop:
    # Print teleop.token locally so operators can enter it in the browser page.
    print("Session token:", teleop.token)
    while simulation_app.is_running():
        controllers = teleop.advance()
        actions = map_inputs_to_actions(controllers, observations)  # your task
        observations, *_ = env.step(actions)
        # Continue using your existing recorder and episode controls here.
```

`simulation_app`, `env`, `observations`, and `map_inputs_to_actions` are provided
by your application. Alternatively pass `action_mapper=your_function` to receive
mapped actions directly from `advance()`, or supply Isaac Lab `retargeters`.
Choose one mapping path. No robot-specific IK or dataset dependency is included.

## Input contract

`advance()` returns an `N x 15` float32 NumPy array, one row per configured
`operator:hand` binding, in the same order as `bindings`. Any number of distinct
bindings is supported; one operator connection supplies both hands.

| Columns | Meaning |
| --- | --- |
| 0–2 | Controller grip position, metres |
| 3–6 | Orientation quaternion, XYZW |
| 7 | Trigger, 0–1 |
| 8 | Grip/squeeze, 0–1 |
| 9 | Tracking valid, 0 or 1 |
| 10–12 | Primary, secondary, stick click |
| 13–14 | Thumbstick X, Y |

WebXR X-right/Y-up/Z-back coordinates are rotated +90 degrees about X into
X-right/Y-forward/Z-up, followed by the configured per-binding world yaw.
Local tracking origins remain independent. Robot alignment, clutching, workspace
limits, gripper behavior, and IK belong in your action mapping.

Missing or stale samples become zero rows. The first read after connection,
tracking loss, or `reset()` also invalidates the affected binding so a consumer
can disarm it. **Your mapper must honor validity and require grip release after
tracking loss.** The library cannot hold robot targets without knowing your action
semantics. Default timeout: 0.25 seconds. Simulation reads never wait for clients.

Callbacks run on the simulation thread, once per observed button press:

```python
teleop.add_callback(("a:right", "primary"), save_episode)
```

Buttons that press and release entirely between simulation reads can be missed;
use an application event protocol if every short button pulse must be retained.

## Connect Quests

1. Open https://lakshyajain06.github.io/Multi-Quest-Teleop/ in each Quest Browser.
2. Enter the workstation address, e.g. `https://192.168.1.100:8443`.
3. Open **Accept workstation certificate**, accept the local certificate warning,
   and return to the controller page. Allow local network access if prompted.
4. Enter the assigned operator ID and the receiver's session token.
5. Select **Connect and enter XR**, then release controller grips before moving.

GitHub Pages serves only the page. Controller input travels directly to the
workstation over the LAN. The page shows passthrough; simulation video is not
included. Certificates are generated locally using OpenSSL; no domain purchase
or external certificate authority is needed. Physical Quest testing is still
required for browser permissions and certificate exceptions.

Optional launch parameters belong in the URL fragment, e.g.
`#server=https%3A%2F%2F192.168.1.100%3A8443&operator=a&token=YOUR_SESSION_TOKEN`.
Fragments are not sent to GitHub. Do not publish token-bearing URLs or keys.

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/browser_trials.cjs
```

Server tests require only the package dependencies. Device adapter tests also
require Isaac Lab. `WebXRServer` is available from `multi_quest_teleop` for
consumers that do not use Isaac Lab. `examples/mock_headsets.py` sends synthetic
controller input to a local receiver; use it only with simulation.

## GitHub Pages

Publish the `main` branch, root directory. The root page forwards to the packaged
client, preserving launch fragments. The public repository contains only this
library and browser client; robot assets, datasets, and task code stay in the
application repository. No Isaac Lab source is vendored here.
