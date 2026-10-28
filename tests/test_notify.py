import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import json
import http.client
import urllib.request
from datetime import timedelta
from unittest.mock import patch
from cfguard.notify import deliver
from cfguard.state import Store


class NotifyTests(unittest.TestCase):
    def test_malformed_legacy_http_is_sanitized_and_retried_with_backoff(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            destination=root/'notification.url'
            destination.write_text('https://alerts.example.invalid/synthetic')
            destination.chmod(0o600)
            with Store(root/'state') as store:
                store.enqueue('critical',{'reason_code':'cutoff_result'},now,priority=100)
                configuration={'url_file':destination,'max_attempts':1}
                with patch('cfguard.notify.urllib.request.build_opener') as opener:
                    opener.return_value.open.side_effect=http.client.BadStatusLine('SYNTHETIC_PRIVATE_RESPONSE')
                    result=deliver(store,configuration,now)
                    self.assertEqual(result,{'delivered':0,'failed':1,'pending':1})
                    self.assertNotIn('SYNTHETIC_PRIVATE_RESPONSE',str(result))
                    self.assertEqual(deliver(store,configuration,now),{'delivered':0,'failed':0,'pending':1})
                    self.assertEqual(opener.return_value.open.call_count,1)
                event=store.db.execute('SELECT attempts,next_at FROM outbox WHERE id=?',('critical',)).fetchone()
                self.assertEqual(event['attempts'],1)
                self.assertGreater(datetime.fromisoformat(event['next_at']),now)
                retried=deliver(store,configuration,now+timedelta(seconds=120),transport=lambda url,body:204)
                self.assertEqual(retried,{'delivered':1,'failed':0,'pending':0})

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
