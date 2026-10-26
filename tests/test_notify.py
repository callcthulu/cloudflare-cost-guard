import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import json
import urllib.request
from cfguard.notify import deliver
from cfguard.state import Store


class NotifyTests(unittest.TestCase):
    def test_local_receiver_records_incident_and_acknowledges(self):
        received = []
        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1',0),Receiver)
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                url_file = root/'destination'
                url_file.write_text('https://alerts.example.invalid/approved')
                url_file.chmod(0o600)
                def local_transport(url,body):
                    # Test-only transport: production still strictly requires HTTPS.
                    with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/',data=body,timeout=2) as reply:
                        return reply.status
                with Store(root/'state') as store:
                    now = datetime.now(timezone.utc)
                    store.enqueue('incident-1',{'incident_id':'incident-1'},now)
                    result = deliver(store,{'url_file':url_file},now,transport=local_transport)
                    self.assertEqual(result['delivered'],1)
                    self.assertEqual(received,[{'incident_id':'incident-1'}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_fake_endpoint_receipt_and_failed_retry(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            url_file = path / 'endpoint'
            url_file.write_text('https://alerts.example.invalid/secret')
            url_file.chmod(0o600)
            with Store(path / 'state') as store:
                store.enqueue('event', {'incident_id': 'event', 'reason_code': 'stale'}, now)
                config = {'url_file': url_file, 'max_attempts': 2}
                calls = []
                def failed(url, body):
                    calls.append(body)
                    raise OSError('private endpoint and secret error')
                result = deliver(store, config, now, transport=failed)
                self.assertEqual(result, {'delivered': 0, 'failed': 1, 'pending': 1})
                self.assertNotIn('secret', str(result))
                store.db.execute("UPDATE outbox SET next_at='2000-01-01'")
                result = deliver(store, config, now, transport=lambda url, body: 204)
                self.assertEqual(result['delivered'], 1)
                self.assertEqual(store.pending_count(), 0)
                self.assertEqual(len(calls), 1)

    def test_no_destination_means_pending_not_delivered(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)) as store:
            store.enqueue('e', {'reason_code': 'unknown'}, now)
            self.assertEqual(deliver(store, None, now)['pending'], 1)


if __name__ == '__main__':
    unittest.main()
