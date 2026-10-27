# Quest teleoperation client

A static WebXR controller-input page for Meta Quest Browser. It connects directly
to a compatible WebSocket receiver on your workstation. GitHub Pages serves only
the HTML and JavaScript; it does not receive controller samples or simulation video.

## Connect

1. Start your workstation's compatible receiver with HTTPS enabled.
2. Open https://lakshyajain06.github.io/quest-teleop/ in each Quest Browser.
3. Enter the workstation address, including `https://` and its port.
4. Open **Accept workstation certificate**, accept the local certificate warning,
   and return to the controller page. Allow local network access if prompted.
5. Enter the operator ID and the receiver's session token.
6. Select **Connect and enter XR** and release controller grips once before moving.

The receiver must explicitly allow the origin `https://lakshyajain06.github.io`.
Certificate exceptions, local-network permission, and immersive AR support depend
on the headset browser; physical Quest testing is still required.

No session token or workstation address is baked into this page. Optional launch
parameters can be supplied in the URL fragment, for example
`#server=https%3A%2F%2F192.168.1.100%3A8443&operator=a&token=YOUR_SESSION_TOKEN`.
Fragments are not sent to GitHub's HTTP server. Do not share a token-bearing URL.

## Publish

Publish the `main` branch, root directory, using GitHub Pages. This repository
contains only the browser client, with no simulator code, assets, or datasets.
