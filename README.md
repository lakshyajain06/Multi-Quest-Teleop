# Multi-Quest Teleop

An installable **Isaac Lab input device** for multiple Meta Quest browsers.
The library owns browser transport, HTTPS, operator identity, tracking validity,
input timeouts, coordinate conversion, and button callbacks. Your application
owns the mapping from inputs to robot actions, physics, episode decisions, and
recording. It does not require CloudXR, ROS, or a headset APK.

## Install and integrate

With Isaac Lab already installed:

```bash
pip install -e ".[video]"
```

Or add this repository as a submodule and install it:

```bash
git submodule add https://github.com/lakshyajain06/Multi-Quest-Teleop.git third_party/multi_quest_teleop
pip install -e "third_party/multi_quest_teleop[video]"
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
    video=True, video_fps=30, video_bitrate=24_000_000, video_codec="auto",
) as teleop:
    # Pairing is disabled by default. Enable require_pairing=True if desired.
    if teleop.token:
        print("Pairing code:", teleop.token)
    while simulation_app.is_running():
        controllers = teleop.advance()
        actions = map_inputs_to_actions(controllers, observations)  # your task
        observations, *_ = env.step(actions)
        # Supply one uint8 RGB frame per operator, from your chosen camera.
        teleop.publish_video("a", render_camera_a())
        teleop.publish_video("b", render_camera_b())
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
4. Enter the assigned operator ID. Leave the optional pairing code blank by default.
5. Select **Connect and enter XR**, then release controller grips before moving.

GitHub Pages serves only the page. Controller input travels directly to the
workstation over the LAN. The video option opens immersive VR. World views should supply separate eye
images and source projections as described below. Mono camera feeds remain
supported for robot-mounted cameras. Input-only mode uses passthrough. Certificates are generated locally using OpenSSL; no domain purchase
or external certificate authority is needed. Physical Quest testing is still
required for browser permissions and certificate exceptions.

Optional launch parameters belong in the URL fragment, e.g.
`#server=https%3A%2F%2F192.168.1.100%3A8443&operator=a&token=YOUR_SESSION_TOKEN`.
Fragments are not sent to GitHub. Do not publish token-bearing URLs or keys.

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/browser_trials.cjs
node tests/browser_video_trials.cjs
```

Server tests require only the package dependencies. WebRTC tests require the
`video` extra and exercise two simultaneous video streams with actual VP8
encoding/decoding. Device adapter tests also
require Isaac Lab. `WebXRServer` is available from `multi_quest_teleop` for
consumers that do not use Isaac Lab. `examples/mock_headsets.py` sends synthetic
controller input to a local receiver; use it only with simulation.

## GitHub Pages

Publish the `main` branch, root directory. The root page forwards to the packaged
client, preserving launch fragments. The public repository contains only this
library and browser client; robot assets, datasets, and task code stay in the
application repository. No Isaac Lab source is vendored here.


## Camera modes and future robot head control

Camera sources and head motion are separate APIs. `teleop.head_pose(operator)`
returns `(pose, continuity_id)`, with a fresh Z-up XYZW pose or `None` if tracking
is lost/stale. Reconnecting or a tracking gap changes the continuity ID. Arm
controller packets and their existing shape are unchanged.

For a virtual spectator camera, use the source-independent helper:

```python
from multi_quest_teleop.view import WorldCameraRig

rig = WorldCameraRig(initial_camera_world_pose_xyzw)
head, continuity = teleop.head_pose("a")
set_camera_world_pose(rig.update(head, session=continuity))
teleop.publish_video("a", render_camera_a())
```

The first head pose establishes the reference at the chosen world camera anchor.
Subsequent headset translation and rotation move that camera; after tracking
loss the view holds and resumes without a discontinuous jump. The application
chooses the world anchors and performs camera rendering.

For a robot-mounted head camera, publish that camera's frames directly. Do not
also move a spectator camera from the same head pose. A task-specific head mapper
can later turn relative headset motion into bounded robot head-joint targets.
The video presentation remains fixed to the returned camera image, avoiding a
second application of head rotation. This library does not command robot head
joints or add them silently to an existing action/recording schema.

The return path supports separate stereo eye views with frame-matched local
rotational reprojection. Positional/depth reprojection and prediction are not
implemented. Moving scene objects and headset translations still depend on fresh
simulation frames, so native XR timing is not guaranteed. The automatic codec uses NVIDIA H.264 hardware encoding when runtime probing
succeeds, with CPU VP8 as a fallback. Scaling to more headsets requires measuring
render, encode, network, and decode costs.

WebRTC signaling shares the control WebSocket; media uses direct
LAN UDP ICE endpoints (dynamic UDP ports must be reachable). There are no STUN
or TURN services in the default LAN configuration. Each operator has a separate
peer and a latest-frame slot; encoding never blocks the simulation thread.
A missing frame source stops producing fresh media after two seconds, and the
browser disconnects after three seconds of stalled playback. Failed video also
disconnects input; uncheck video when intentionally using an input-only server.

Synthetic end-to-end test (with the application receiver already starting):

```bash
python examples/mock_video_headsets.py --startup-log /tmp/simulation.log --output /tmp/decoded-quest-views
```

This script moves both mock controllers and headsets. Use only with simulation.

## Single-headset operation

Both bindings may belong to the same operator. For example,
`bindings=["a:left", "a:right"]` supplies both hands from one Quest connection.
The application defines the row-to-robot mapping, so it can reverse this order
when a side view places the robots on opposite screen sides.

When a world camera is anchored at a rotated viewpoint, use
`rig.map_tracking_pose(controller_pose)` to put each controller into the same
world frame as that camera before applying robot-specific clutch/IK mapping.
It returns `None` without a current head reference; disarm movement during that
interval and require a fresh grip release when tracking resumes.

Button callbacks can preserve a single-headset control scheme, e.g. left
primary/secondary for save/discard and right secondary for pause. Specific robot
presets and recording commands belong in the consuming application's guide.


## Optional pairing code

Pairing codes are **off by default**. Enter the workstation address and operator
ID and connect; leave the pairing-code field blank. Origin checks and exclusive
operator ownership still apply.

For an optional random four-digit code, construct the device or receiver with
`require_pairing=True`. It prints `Pairing code: 1234` (example) when starting.
The code changes on each startup. An explicit `token=` value also enables the
check for applications that need to supply their own code.


## Stereo world rendering (0.3)

Displaying one flat image twice does not reproduce an XR world. For world views,
the client now sends each `XRView`'s pose and full projection matrix. The
application renders a camera at each actual eye pose, preserving eye separation
and orientation, and packs left/right RGB images side by side into one video.
The client samples only the corresponding half for each eye, fills its viewport,
and maps the source frustum back to the Quest's eye projection. There is no
letterboxed plane in stereo mode. Scissor rectangles isolate the eye viewports.

```python
from multi_quest_teleop.stereo import fit_eye_projection

head, continuity = teleop.head_pose("a")
rig.update(head, session=continuity)
eyes = teleop.eye_views("a")
if head is not None and eyes:
    projections = {}
    for eye in ("left", "right"):
        pose = rig.map_tracking_pose(eyes[eye]["pose"])
        projection, intrinsic = fit_eye_projection(eyes[eye]["projection"], width, height)
        configure_eye_camera(eye, pose, intrinsic)  # application rendering adapter
        projections[eye] = projection
    left, right = render_eye_camera("left"), render_eye_camera("right")
    teleop.publish_video("a", np.concatenate((left, right), axis=1),
                        layout="stereo-sbs", projections=projections,
                        orientations={eye: eyes[eye]["pose"][3:7] for eye in ("left", "right")})
```

`np`, `width`, `height`, and camera adapter functions above come from the
application. Do not publish the frame until both eye cameras have been configured
and rendered. `eye_views()` returns `None` when stale. Poses use the same Z-up
tracking basis as `head_pose()`. Projection matrices remain WebXR column-major
OpenGL matrices and must not be rotated with the pose basis conversion.

Isaac Lab's basic USD camera path assumes centered optics and square pixels.
`fit_eye_projection()` chooses a symmetric covering frustum it can render without
losing the headset's asymmetric eye rays. The returned intrinsic matrix configures
the simulation camera; the returned source projection travels with the video
format in control acknowledgements. The client uses source × inverse(XR eye
projection) to sample the correct pixels, rather than approximating eye alignment
with an aspect-ratio fit. Source projections should be cached while unchanged.

Refresh the hosted page after updating; it displays **Client 0.5**. Old mono
clients do not send the eye views needed for world stereo. Stereo doubles the
pixel count at a given per-eye resolution. Actual Quest binocular fusion and
motion comfort still require a physical headset check.


## Image quality (0.4)

The current library defaults to a 24 Mbps ceiling for each operator's combined
stereo stream (12 Mbps in version 0.4). Set `video_bitrate=...` (bits/second) on `MultiQuestDevice` or
`WebXRServer` to change it. The sender starts at that budget and can reduce it
in response to receiver bandwidth estimates. This is a ceiling, not a guaranteed
measured throughput. The page displays received pixel dimensions per eye.

Version 0.4 of the consuming Ultra application used 1024x1024 per eye; the current
low-latency profile uses 1280x1280 per eye, packed as 2560x1280. Its recorded robot-camera resolutions remain
independent. Larger frame sizes require more render/encode time and bandwidth;
benchmark frame rate alongside visual detail. CPU VP8 encoding is still used.

aiortc's stock VP8 encoder caps its bitrate at 1.5 Mbps, which severely limits
stereo detail. The library installs a separately configured encoder on each
sender and prefers VP8 explicitly. No process-wide codec globals are changed.
Since aiortc has no public per-sender encoder setter, this compatibility adapter
is isolated in `encoder.py` and guarded to **aiortc==1.15.0**. Updates to aiortc
require checking this adapter and rerunning the real encode/decode tests.

The quality regression uses a repeatable detailed moving image and compares
actual decoded pixels against the source. It measured about 22 dB PSNR with the
stock starting budget and 43 dB with the new budget in the local test setup.
That synthetic result demonstrates reduced compression loss; it does not
measure headset optics, motion latency, or subjective VR quality.


## Lower head-motion latency (0.5)

`video_codec="auto"` probes NVIDIA H.264 encoding and uses it when available;
`"nvenc"` requires it, and `"vp8"` selects the CPU fallback explicitly. H.264 uses
ultra-low-latency tuning, no B frames, no lookahead, and a small rate-control
buffer. Variable bitrate avoids sending filler data for static scenes. Codec
preferences are applied before remote SDP negotiation, and the encoder adapter
is guarded to aiortc 1.15.0. The server prints the encoder actually selected.
The default video ceiling is now 24 Mbps, with a 30 fps output cap.

For world stereo, supply `orientations={"left": ..., "right": ...}` alongside
source projections in `publish_video()`. These must be the Z-up **tracking**
quaternions returned by `eye_views()`, corresponding to the camera poses used to
render that exact frame. Do not supply transformed simulation-world quaternions.
The source slot captures image and metadata together; pacing selects the latest
slot after sleeping, so stale queued images do not accumulate.

The client opens an unordered, non-retransmitted `frame-meta` data channel. The
encoder maps frame metadata to the actual RTP timestamp. The browser captures
the video texture in `requestVideoFrameCallback` and uses its `rtpTimestamp` to
look up matching render orientations. Each XR frame applies rendered-eye inverse
rotation × current-eye rotation when sampling that image. Metadata from another
frame is never applied. When matching metadata or the browser callback field is
unavailable, stereo presentation continues without the local rotation correction.
The first encoded frame also uses this fallback while the RTP origin is learned.

This reduces rotational waiting without synthesizing positional motion or moving
objects. The symmetric source frustum includes a 15% overscan margin. Fast turns
can still reveal missing image edges. Mono robot-camera feeds are not rotated
again, preserving the future head-joint-control camera contract.

Client 0.5 shows received resolution, frame rate when available, **GPU** for NVENC,
and **local head rotation** when a matching frame is being reprojected. The Ultra
application defaults to 1280x1280 per eye and renders once per control step while
retaining both physics substeps. Its terminal also prints render/physics and
encode timings. Keep recording-camera resolution and task action mappings in the
application.

Local codec benchmark on this workstation, using a repeatable detailed
2560x1280 moving image: warm median encode time was about 7 ms with NVENC and
10 ms with CPU VP8. These are encoder timings, not end-to-end headset latency.
The bigger latency changes are avoiding redundant renders and applying head
rotation locally. Physical Quest measurements remain necessary.
