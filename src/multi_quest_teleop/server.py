"""Browser controller transport; no Isaac Sim or CloudXR imports."""

import json
import hashlib
import ipaddress
import subprocess
import tempfile
import secrets
import ssl
import threading
import time
from pathlib import Path
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

import numpy as np
from scipy.spatial.transform import Rotation
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve


def create_local_certificate(host, directory=None):
    """Generate a reusable local-only certificate without a domain or external CA."""
    if not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in host):
        raise ValueError('Certificate host must be a plain IP address or hostname')
    try:
        ipaddress.ip_address(host)
        san = f'IP:{host}'
    except ValueError:
        san = f'DNS:{host}'
    root = Path(directory or Path.home() / '.local/state/multi-quest-teleop')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = root / hashlib.sha256(host.encode()).hexdigest()[:16]
    folder.mkdir(mode=0o700, exist_ok=True)
    cert, key = folder / 'cert.pem', folder / 'key.pem'
    if cert.exists() and key.exists():
        result = subprocess.run(['openssl', 'x509', '-checkend', '86400', '-noout', '-in', str(cert)],
                                capture_output=True)
        if result.returncode == 0:
            return cert, key
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        fresh_cert, fresh_key = Path(temporary) / 'cert.pem', Path(temporary) / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(fresh_key), '-out', str(fresh_cert), '-days', '365',
                        '-subj', '/CN=Local Quest Teleoperation', '-addext', f'subjectAltName={san}'],
                       check=True, capture_output=True)
        fresh_key.chmod(0o600)
        fresh_cert.replace(cert)
        fresh_key.replace(key)
    return cert, key


class WebXRServer:
    """One latest-value slot per operator; simulation reads never block on a client.

    Bindings are in application-defined order, e.g. ('a:right', 'b:right'). Poses arrive in
    WebXR local-floor coordinates and are rotated to Z-up application axes.
    """

    def __init__(self, bindings, host='0.0.0.0', port=8443, cert=None, key=None,
                 timeout=0.25, yaw_degrees=None, token=None, allowed_origins=(), video=False, video_fps=20):
        if not bindings or timeout <= 0 or not np.isfinite(timeout):
            raise ValueError('At least one binding and a positive finite timeout are required')
        if yaw_degrees is None:
            yaw_degrees = (0.0,) * len(bindings)
        self.bindings = [binding.split(':') for binding in bindings]
        if any(len(b) != 2 or not b[0] or b[1] not in ('left', 'right') for b in self.bindings):
            raise ValueError('Bindings must be operator:left or operator:right')
        if len({tuple(b) for b in self.bindings}) != len(bindings):
            raise ValueError('Each binding must select a distinct input')
        if len(yaw_degrees) != len(bindings) or not np.isfinite(yaw_degrees).all():
            raise ValueError('One finite yaw angle per binding is required')
        self.rotations = [Rotation.from_euler('z', yaw, degrees=True) *
                          Rotation.from_euler('x', 90, degrees=True) for yaw in yaw_degrees]
        self.host, self.port, self.timeout = host, port, timeout
        self.token = token or secrets.token_urlsafe(24)
        self.allowed_origins = set(allowed_origins)
        self.lock = threading.Lock()
        self.clients, self.samples = {}, {}
        self.generations, self.observed = {}, {}
        self.head_samples = {}
        self.head_generations = {}
        self.video = None
        if video:
            from .video import VideoReturn
            self.video = VideoReturn(fps=video_fps)
        self.context = None
        if bool(cert) != bool(key):
            raise ValueError('Supply both TLS certificate and key')
        if cert:
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            # https://github.com/python-websockets/websockets/issues/1779
            # Avoid TLS 1.3 post-handshake tickets racing with the threaded
            # client's first HTTP write on affected Python/OpenSSL versions.
            self.context.num_tickets = 0
            self.context.load_cert_chain(cert, key)

    def _request(self, connection, request):
        url = urlsplit(request.path)
        if url.path == '/certificate' and request.headers.get('Upgrade', '').lower() != 'websocket':
            return connection.respond(200, 'Certificate accepted. Return to the Quest controller page and connect.\n')
        if url.path == '/' and request.headers.get('Upgrade', '').lower() != 'websocket':
            response = connection.respond(200, files('multi_quest_teleop').joinpath('webxr.html').read_text())
            del response.headers['Content-Type']
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
            response.headers['Cache-Control'] = 'no-store'
            return response
        query = parse_qs(url.query)
        operator = query.get('operator', [''])[0]
        supplied = query.get('token', [''])[0]
        if url.path != '/input' or not secrets.compare_digest(supplied, self.token):
            return connection.respond(403, 'Invalid input URL or token\n')
        if operator not in {b[0] for b in self.bindings}:
            return connection.respond(403, 'Operator is not assigned\n')
        origin = request.headers.get('Origin')
        if origin and origin not in self.allowed_origins and origin not in {
            f"http://{request.headers.get('Host')}", f"https://{request.headers.get('Host')}",
        }:
            return connection.respond(403, 'Origin must match this server\n')
        return None

    def _handle(self, connection):
        operator = parse_qs(urlsplit(connection.request.path).query)['operator'][0]
        with self.lock:
            occupied = operator in self.clients
            if not occupied:
                self.clients[operator] = connection
                self.generations[operator] = self.generations.get(operator, np.zeros(2, dtype=int)) + 1
        if occupied:
            connection.close(1008, 'Operator already connected')
            return
        previous = -1
        try:
            for raw in connection:
                message = json.loads(raw)
                if isinstance(message, dict) and message.get('type') == 'video_offer':
                    if not self.video:
                        connection.send(json.dumps({'type': 'video_error', 'message': 'Video is disabled on this receiver'}))
                        continue
                    sdp = message.get('sdp')
                    if not isinstance(sdp, str) or len(sdp) > 60000:
                        raise ValueError('Invalid video offer')
                    try:
                        connection.send(json.dumps(self.video.answer(operator, sdp)))
                    except Exception:
                        connection.send(json.dumps({'type': 'video_error', 'message': 'Video negotiation failed'}))
                    continue
                seq = message['seq']
                if message['version'] != 1 or type(seq) is not int or seq <= previous:
                    raise ValueError('Invalid protocol version or sequence')
                rows = np.asarray(message['controllers'], dtype=np.float32)
                if rows.shape != (2, 15) or not np.isfinite(rows).all():
                    raise ValueError('Expected two finite controller rows')
                if np.any((rows[:, 7:13] < 0) | (rows[:, 7:13] > 1)):
                    raise ValueError('Invalid button values')
                if np.any((rows[:, 9:13] != 0) & (rows[:, 9:13] != 1)):
                    raise ValueError('Tracking and click fields must be binary')
                if np.any(np.abs(rows[:, 13:]) > 1):
                    raise ValueError('Invalid stick axes')
                for row in rows:
                    if row[9] and not 0.9 < np.linalg.norm(row[3:7]) < 1.1:
                        raise ValueError('Invalid quaternion')
                head = message.get('head')
                if head is not None:
                    head = np.asarray(head, dtype=np.float32)
                    if head.shape != (8,) or not np.isfinite(head).all() or head[7] not in (0, 1):
                        raise ValueError('Expected finite head pose and validity')
                    if head[7] and not .9 < np.linalg.norm(head[3:7]) < 1.1:
                        raise ValueError('Invalid head quaternion')
                previous = seq
                with self.lock:
                    now = time.monotonic()
                    last = self.samples.get(operator)
                    if last is not None and now - last[0] > self.timeout:
                        self.generations[operator] += 1
                    if last is not None:
                        lost = (last[1][:, 9] == 1) & (rows[:, 9] == 0)
                        self.generations[operator] += lost.astype(int)
                    old_head = self.head_samples.get(operator)
                    if head is None or not head[7]:
                        self.head_samples.pop(operator, None)
                        self.head_generations[operator] = self.head_generations.get(operator, 0) + 1
                    else:
                        if old_head is None or now - old_head[0] > self.timeout:
                            self.head_generations[operator] = self.head_generations.get(operator, 0) + 1
                        self.head_samples[operator] = (now, head[:7].copy())
                    self.samples[operator] = (now, rows.copy())
                # Acknowledgement limits the browser to one outstanding sample.
                connection.send(json.dumps({'ack': seq}))
        except (ValueError, TypeError, KeyError, ConnectionClosed):
            connection.close(1008, 'Invalid input or disconnected')
        finally:
            with self.lock:
                self.clients.pop(operator, None)
                self.samples.pop(operator, None)
                self.head_samples.pop(operator, None)
                self.head_generations[operator] = self.head_generations.get(operator, 0) + 1
            if self.video:
                self.video.remove(operator)

    def head_pose(self, operator):
        """Latest Z-up XYZW head pose and continuity ID; (None, ID) if stale."""
        with self.lock:
            sample = self.head_samples.get(operator)
            generation = self.head_generations.get(operator, 0)
            if sample is None or time.monotonic() - sample[0] > self.timeout:
                return None, generation
            pose = sample[1].copy()
        basis = Rotation.from_euler('x', 90, degrees=True)
        pose[:3] = basis.apply(pose[:3])
        pose[3:] = (basis * Rotation.from_quat(pose[3:])).as_quat()
        return pose, generation

    def publish_video(self, operator, rgb):
        if not self.video:
            raise RuntimeError('Enable video when constructing this receiver')
        if operator not in {binding[0] for binding in self.bindings}:
            raise ValueError('Operator is not configured')
        self.video.publish(operator, rgb)

    def snapshot(self):
        packet = np.zeros((len(self.bindings), 15), dtype=np.float32)
        now = time.monotonic()
        with self.lock:
            for index, (operator, hand) in enumerate(self.bindings):
                sample = self.samples.get(operator)
                if sample is None or now - sample[0] > self.timeout:
                    continue
                generation = int(self.generations[operator][int(hand == 'right')])
                if self.observed.get(index) != generation:
                    self.observed[index] = generation
                    continue  # Force the mapper to disarm after every connection/gap.
                packet[index] = sample[1][int(hand == 'right')]
        for row, rotation in zip(packet, self.rotations):
            if row[9]:
                row[:3] = rotation.apply(row[:3])
                row[3:7] = (rotation * Rotation.from_quat(row[3:7])).as_quat()
        return packet

    def __enter__(self):
        self.server = serve(self._handle, self.host, self.port, ssl=self.context,
                            process_request=self._request, max_size=65536, max_queue=1,
                            compression=None, close_timeout=1)
        if self.video:
            self.video.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.socket.getsockname()[1]
        scheme = 'https' if self.context else 'http'
        print(f'WebXR: {scheme}://<workstation-host>:{self.port}/?token={self.token}', flush=True)
        return self

    def __exit__(self, *exc):
        with self.lock:
            clients = list(self.clients.values())
        for connection in clients:
            connection.close(1001, 'Simulation stopped')
        self.server.shutdown()
        self.thread.join(timeout=3)
        if self.video:
            self.video.close()
