"""Send two synthetic headsets to a local WebXR simulation for a mock trial.

Use only with a simulation: this script deliberately engages both robot arms.
"""
import argparse
import json
import re
import time
from pathlib import Path

from websockets.sync.client import connect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--startup-log', type=Path, required=True,
                    help='Log for a freshly launched simulation; reads its generated token')
parser.add_argument('--port', type=int, default=18443)
parser.add_argument('--samples', type=int, default=180)
args = parser.parse_args()
for _ in range(120):
    text = args.startup_log.read_text(errors='replace') if args.startup_log.exists() else ''
    match = re.search(rf'{args.port}/(?:\?token=([\w-]+))?', text)
    if match:
        break
    time.sleep(.5)
else:
    raise RuntimeError('Simulation server did not start within 60 seconds')
session_token = match[1] or ""
clients = []
try:
    for operator in ('a', 'b'):
        clients.append(connect(f'ws://127.0.0.1:{args.port}/input?operator={operator}&token={session_token}'))
    for seq in range(args.samples):
        for index, client in enumerate(clients):
            rows = [[0,0,0,0,0,0,1,0,0,1,0,0,0,0,0] for _ in range(2)]
            rows[1][0] = min(max(seq-15, 0), 50) * .0003 * (1 if index == 0 else -1)
            rows[1][8] = int(seq >= 10)
            client.send(json.dumps(dict(version=1, seq=seq, controllers=rows)))
            if json.loads(client.recv()) != {'ack':seq}:
                raise RuntimeError('Unexpected acknowledgement')
        time.sleep(.04)
finally:
    for client in clients:
        client.close()
print(f'PASS: {args.samples} acknowledged samples per synthetic headset')
