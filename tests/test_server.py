"""Hardware-free trials of real sockets and the production clutch mapper."""
import json
import time
import ssl
import subprocess
import tempfile
import threading
from pathlib import Path
import unittest
import urllib.error
import urllib.request

import numpy as np
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from multi_quest_teleop import WebXRServer, create_local_certificate


class WebXRTrials(unittest.TestCase):
    def setUp(self):
        self.server = WebXRServer(['a:right', 'b:left'], host='127.0.0.1', port=0, timeout=.1)
        self.server.__enter__()
        self.port = self.server.server.socket.getsockname()[1]
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.__exit__(None, None, None)

    def client(self, operator='a', token=None, **kwargs):
        client = connect(f'ws://127.0.0.1:{self.port}/input?operator={operator}&token={token or self.server.token}', **kwargs)
        self.clients.append(client)
        return client

    def rows(self, grip=0):
        rows = np.zeros((2, 15))
        rows[:, 6] = 1
        rows[:, 9] = 1
        rows[:, 8] = grip
        return rows

    def send(self, client, rows, seq=0):
        client.send(json.dumps({'version': 1, 'seq': seq, 'controllers': rows.tolist()}))
        self.assertEqual(json.loads(client.recv()), {'ack': seq})

    def test_http_and_authentication(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/') as response:
            self.assertIn(b'Quest teleoperation', response.read())
            self.assertIn('text/html', response.headers['Content-Type'])
        for kwargs in ({'token':'wrong'}, {'operator':'unknown'}, {'origin':'https://evil.example'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidStatus):
                self.client(**kwargs)

    def test_duplicate_operator_does_not_evict_owner(self):
        owner = self.client()
        duplicate = self.client()
        with self.assertRaises(ConnectionClosed):
            duplicate.recv()
        self.send(owner, self.rows())
        self.server.snapshot()
        self.assertEqual(self.server.snapshot()[0,9], 1)

    def test_two_clients_mapping_and_latest_sample(self):
        a, b = self.client(), self.client('b')
        rows = self.rows(); rows[0,1] = 2; rows[1,1] = 3
        self.send(a, rows); self.send(b, rows)
        self.assertFalse(self.server.snapshot().any())
        np.testing.assert_allclose(self.server.snapshot()[:,2], [3,2])
        for seq in range(1,101):
            rows[1,0] = seq / 100
            self.send(a, rows, seq)
        self.assertAlmostEqual(self.server.snapshot()[0,0], 1)

    def test_timeout_is_independent(self):
        a, b = self.client(), self.client('b')
        self.send(a,self.rows()); self.send(b,self.rows())
        self.server.snapshot()
        time.sleep(.12)
        self.send(b,self.rows(),1)
        self.server.snapshot()  # gap forces one invalid tick
        packet = self.server.snapshot()
        self.assertEqual(packet[0,9],0)
        self.assertEqual(packet[1,9],1)

    def test_reconnection_disarms_even_between_simulation_ticks(self):
        a = self.client(); self.send(a,self.rows()); self.server.snapshot()
        self.assertEqual(self.server.snapshot()[0,9],1)
        a.close()
        deadline = time.monotonic()+1
        while 'a' in self.server.clients and time.monotonic()<deadline:
            time.sleep(.005)
        a = self.client(); self.send(a,self.rows(grip=1))
        self.assertFalse(self.server.snapshot()[0].any())
        self.assertEqual(self.server.snapshot()[0,9],1)

    def test_malformed_packets_close_and_clear_input(self):
        malformed = [None, [], {}, {'version':1,'seq':True,'controllers':[]},
                     {'version':1,'seq':0,'controllers':[[float('nan')]*15]*2},
                     {'version':1,'seq':0,'controllers':[[0]*15]*3}]
        for message in malformed:
            with self.subTest(message=message):
                client = self.client('b')
                client.send(json.dumps(message))
                with self.assertRaises(ConnectionClosed): client.recv()
                deadline = time.monotonic()+1
                while 'b' in self.server.clients and time.monotonic()<deadline: time.sleep(.005)
                self.assertNotIn('b',self.server.samples)

    def test_bad_quaternion_and_buttons(self):
        for column, value in [(6,0),(7,2),(13,2)]:
            with self.subTest(column=column):
                client = self.client('b'); rows=self.rows(); rows[:,column]=value
                client.send(json.dumps({'version':1,'seq':0,'controllers':rows.tolist()}))
                with self.assertRaises(ConnectionClosed): client.recv()
                deadline=time.monotonic()+1
                while 'b' in self.server.clients and time.monotonic()<deadline: time.sleep(.005)

    def test_repeated_sequence_is_rejected(self):
        client=self.client(); self.send(client,self.rows())
        client.send(json.dumps({'version':1,'seq':0,'controllers':self.rows().tolist()}))
        with self.assertRaises(ConnectionClosed): client.recv()

    def test_tracking_loss_between_simulation_ticks_disarms_only_affected_hand(self):
        client=self.client(); rows=self.rows(); self.send(client,rows)
        self.server.snapshot(); self.assertEqual(self.server.snapshot()[0,9],1)
        rows[1,9]=0; self.send(client,rows,1)
        rows[1,9]=1; self.send(client,rows,2)
        self.assertEqual(self.server.snapshot()[0,9],0)
        self.assertEqual(self.server.snapshot()[0,9],1)

    def test_generated_certificate_and_hosted_page_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            cert,key=create_local_certificate('localhost',folder)
            original=cert.read_bytes()
            self.assertEqual(create_local_certificate('localhost',folder),(cert,key))
            self.assertEqual(cert.read_bytes(),original)
            self.assertEqual(key.stat().st_mode & 0o777,0o600)
            trusted=ssl.create_default_context(cafile=str(cert))
            with WebXRServer(['a:right','b:left'],host='127.0.0.1',port=0,cert=cert,key=key,
                             allowed_origins=['https://lakshyajain06.github.io']) as secure:
                with urllib.request.urlopen(f'https://localhost:{secure.port}/certificate',context=trusted) as response:
                    self.assertIn(b'Certificate accepted',response.read())
                with connect(f'wss://localhost:{secure.port}/input?operator=a&token={secure.token}',
                             ssl=trusted,origin='https://lakshyajain06.github.io') as client:
                    self.send(client,self.rows())
                with self.assertRaises(InvalidStatus):
                    connect(f'wss://localhost:{secure.port}/input?operator=a&token={secure.token}',
                            ssl=trusted,origin='https://untrusted.example')

    def test_tls_page_and_wss(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory)/'cert.pem', Path(directory)/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                            '-keyout',str(key),'-out',str(cert),'-days','1',
                            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],
                           check=True, capture_output=True)
            trusted = ssl.create_default_context(cafile=str(cert))
            with WebXRServer(['a:right','b:left'], host='127.0.0.1', port=0,
                             cert=cert,key=key) as secure:
                port=secure.port
                with urllib.request.urlopen(f'https://localhost:{port}/',context=trusted) as response:
                    self.assertEqual(response.status,200)
                with connect(f'wss://localhost:{port}/input?operator=a&token={secure.token}',ssl=trusted) as client:
                    self.send(client,self.rows())
                    secure.snapshot()
                    self.assertEqual(secure.snapshot()[0,9],1)

    def test_concurrent_streaming_with_nonblocking_simulation_reads(self):
        a,b=self.client(),self.client('b')
        failures=[]
        def producer(client):
            try:
                for seq in range(120):
                    self.send(client,self.rows(grip=seq>5),seq)
                    time.sleep(.005)
            except Exception as error: failures.append(error)
        threads=[threading.Thread(target=producer,args=(client,)) for client in [a,b]]
        for thread in threads: thread.start()
        durations=[]; simultaneous=0
        while any(thread.is_alive() for thread in threads):
            started=time.perf_counter(); packet=self.server.snapshot()
            durations.append(time.perf_counter()-started)
            simultaneous += int(packet[:,9].all())
            time.sleep(.002)
        for thread in threads: thread.join()
        self.assertEqual(failures,[])
        self.assertGreater(simultaneous,50)
        self.assertLess(np.percentile(durations,99),.05)



if __name__ == '__main__':
    unittest.main()
