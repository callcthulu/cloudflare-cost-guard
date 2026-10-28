"""Native transports tested only with synthetic protected files and fake networks."""
import json
import http.client
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cfguard import notify
from cfguard.state import Store


class ChannelTests(unittest.TestCase):
    def test_alert_titles_distinguish_warning_confirmed_endpoint_scope_and_uncertainty(self):
        cases=[({'reason_code':'budget_warning','status':'warning'},'Budget warning'),
               ({'reason_code':'cutoff_result','status':'worker_deleted'},'Worker deleted'),
               ({'reason_code':'cutoff_result','status':'endpoints_disabled'},'workers.dev/preview endpoints disabled'),
               ({'reason_code':'cutoff_result','status':'uncertain'},'Cutoff outcome uncertain'),
               ({'reason_code':'cutoff_result','status':'not_applied'},'Cutoff not applied')]
        for payload,title in cases:
            with self.subTest(title=title):
                self.assertIn(title,notify._safe_text(payload).splitlines()[0])

    def test_leaving_multi_target_mode_reports_cancellations_even_without_receiver(self):
        target=self.target('slack','https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        now=datetime.now(timezone.utc)
        with Store(self.root/'state') as store:
            notify.prepare_notifications(store,{'targets':[target]},now)
            store.enqueue('critical',{'reason_code':'cutoff_result'},now,priority=100)
            self.assertEqual(notify.prepare_notifications(store,None,now),1)
            report=notify.deliver(store,None,now)
            self.assertEqual(report['cancelled'],1)
            self.assertEqual(report['pending'],0)
            notify.prepare_notifications(store,None,now)
            self.assertEqual(notify.deliver(store,None,now),{'delivered':0,'failed':0,'pending':0})

    def test_telegram_requires_immutable_nonzero_numeric_chat_identity(self):
        token=self.secret('token','123456:synthetic_TOKEN')
        chat=self.secret('chat','@reassignable_channel')
        target={'id':'tg','type':'telegram','token_file':token,'chat_id_file':chat}
        for value in ('@reassignable_channel','0',str(1<<63),str(-(1<<63)-1)):
            with self.subTest(value=value):
                chat.write_text(value)
                self.assertIsNone(notify.resolve_targets({'targets':[target]})[0]['credentials'])
                result,calls=self.send(target,(200,b'{"ok":true,"result":{"message_id":7}}'))
                self.assertFalse(result['accepted'])
                self.assertEqual(calls,[])

    def test_native_message_is_bounded_and_preserves_scope_currency_and_outcome(self):
        target=self.target('discord','https://discord.com/api/webhooks/123456/synthetic_TOKEN')
        resolved=notify.resolve_targets({'targets':[target]})[0]
        fields=('reason_code','reason','resource_ref','value','limit','threshold','period','quality',
                'incident_id','hard_limit_usd','threshold_usd','period_start','period_end','action_reason','metric')
        payload={field:'x'*160 for field in fields}
        payload.update(status='endpoints_disabled',scope='workers.dev_and_preview_only',currency='USD',
                       source='workers_usage_estimate',action='disable_worker_endpoints')
        observed=[]
        def transport(url,body):
            observed.append(json.loads(body)['content'])
            return 200,b'{"id":"987654"}'
        self.assertTrue(notify.send_target(resolved,payload,transport=transport))
        self.assertLessEqual(len(observed[0]),2000)
        self.assertIn('endpoints_disabled',observed[0])
        self.assertIn('scope: workers.dev_and_preview_only',observed[0])
        self.assertIn('currency: USD',observed[0])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def secret(self, name, value):
        path = self.root / name
        path.write_text(value, encoding='utf-8')
        path.chmod(0o600)
        return path

    def target(self, kind, url):
        return {'id': kind, 'type': kind, 'url_file': self.secret(kind, url)}

    def send(self, target, response, payload=None):
        calls = []
        def transport(url, body):
            calls.append((url, json.loads(body)))
            return response
        result = notify.test_notification({'targets': [target]}, target['id'], send=True,
                                          transport=transport)
        return result, calls

    def test_preview_does_not_read_credentials_or_open_network(self):
        target = {'id': 'slack', 'type': 'slack', 'url_file': self.root/'missing'}
        with patch.object(Path, 'open', side_effect=AssertionError('secret read')):
            result = notify.test_notification({'targets': [target]}, 'slack')
        self.assertTrue(result['preview'])
        self.assertFalse(result['human_receipt_verified'])
        self.assertNotIn('accepted', result)

    def test_resolution_keeps_missing_targets_declared_and_hashes_identity(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        first = notify.resolve_targets({'targets': [target]})[0]
        self.assertEqual(len(first['destination_digest']), 64)
        target['url_file'].unlink()
        missing = notify.resolve_targets({'targets': [target]})[0]
        self.assertEqual(first['config_digest'], missing['config_digest'])
        self.assertIsNone(missing['destination_digest'])
        self.assertIsNone(missing['credentials'])

    def test_slack_requires_application_acknowledgement_and_strict_host(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        result, calls = self.send(target, (200, b'ok'))
        self.assertTrue(result['accepted'])
        self.assertIn('TEST', calls[0][1]['text'])
        self.assertFalse(calls[0][1]['mrkdwn'])
        for response in ((200, b'invalid_payload'), (204, b'ok'), (302, b'ok')):
            self.assertFalse(self.send(target, response)[0]['accepted'])
        target['url_file'].write_text('https://hooks.slack.com.evil.invalid/services/a/b/c')
        self.assertEqual(self.send(target, (200, b'ok'))[1], [])

    def test_discord_disables_mentions_and_requests_message_ack(self):
        target = self.target('discord', 'https://discord.com/api/v10/webhooks/123456/synthetic_TOKEN')
        result, calls = self.send(target, (200, b'{"id":"987654"}'))
        self.assertTrue(result['accepted'])
        self.assertTrue(calls[0][0].endswith('?wait=true'))
        self.assertEqual(calls[0][1]['allowed_mentions'], {'parse': []})
        self.assertFalse(self.send(target, (204, b''))[0]['accepted'])

    def test_telegram_is_plaintext_and_same_bot_rotation_preserves_recipient(self):
        token = self.secret('token', '123456:synthetic_TOKEN')
        chat = self.secret('chat', '-123456')
        target = {'id': 'tg', 'type': 'telegram', 'token_file': token, 'chat_id_file': chat}
        before = notify.resolve_targets({'targets': [target]})[0]
        token.write_text('123456:rotated_TOKEN')
        after = notify.resolve_targets({'targets': [target]})[0]
        self.assertEqual(before['destination_digest'], after['destination_digest'])
        result, calls = self.send(target, (200, b'{"ok":true,"result":{"message_id":7}}'))
        self.assertTrue(result['accepted'])
        self.assertEqual(calls[0][1]['chat_id'], '-123456')
        self.assertNotIn('parse_mode', calls[0][1])
        self.assertNotIn('allow_paid_broadcast', calls[0][1])
        self.assertFalse(self.send(target, (200, b'{"ok":false}'))[0]['accepted'])
        self.assertFalse(self.send(target, (200, b'{"ok":true,"result":{"message_id":true}}'))[0]['accepted'])

    def test_email_uses_tls_and_validated_single_ascii_envelopes(self):
        settings = {'host': 'smtp.example.invalid', 'port': 587, 'tls': 'starttls',
                    'username': 'synthetic', 'password': 'synthetic-secret',
                    'from': 'guard@example.invalid', 'to': 'owner@example.invalid'}
        target = {'id': 'mail', 'type': 'email',
                  'settings_file': self.secret('email', json.dumps(settings))}
        events = []
        class SMTP:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def starttls(self, *, context): events.append('tls')
            def ehlo(self): events.append('ehlo')
            def login(self, user, password): events.append('login')
            def send_message(self, message, *, from_addr, to_addrs):
                events.append((from_addr, to_addrs, message.get_content()))
                return {}
        def factory(mode, host, port, *, timeout, context):
            self.assertEqual((mode, host, port, timeout), ('starttls', 'smtp.example.invalid', 587, 5))
            return SMTP()
        result = notify.test_notification({'targets': [target]}, 'mail', send=True, smtp_factory=factory)
        self.assertTrue(result['accepted'])
        self.assertLess(events.index('tls'), events.index('login'))
        self.assertIn('TEST', events[-1][2])
        before = notify.resolve_targets({'targets': [target]})[0]
        settings['password'] = 'rotated'
        target['settings_file'].write_text(json.dumps(settings))
        after = notify.resolve_targets({'targets': [target]})[0]
        self.assertEqual(before['destination_digest'], after['destination_digest'])
        for field, value in (('tls', 'none'), ('to', 'a@example.invalid,b@example.invalid'),
                             ('from', 'guard@example.invalid\r\nBcc: victim@example.invalid')):
            invalid = dict(settings, **{field: value})
            target['settings_file'].write_text(json.dumps(invalid))
            self.assertIsNone(notify.resolve_targets({'targets': [target]})[0]['credentials'])

    def test_protected_files_reject_oversize_symlinks_and_posix_permissions(self):
        target = self.target('webhook', 'https://alerts.example.invalid/receiver')
        target['url_file'].write_text('x' * 65537)
        self.assertIsNone(notify.resolve_targets({'targets': [target]})[0]['credentials'])
        target['url_file'].write_text('https://alerts.example.invalid/receiver')
        if os.name == 'posix':
            target['url_file'].chmod(0o666)
            self.assertIsNone(notify.resolve_targets({'targets': [target]})[0]['credentials'])
        try:
            link = self.root / 'link'
            link.symlink_to(target['url_file'])
        except OSError:
            return
        target['url_file'] = link
        self.assertIsNone(notify.resolve_targets({'targets': [target]})[0]['credentials'])

    def test_responses_are_bounded_and_failures_do_not_echo_secrets(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        result, _ = self.send(target, (200, b'ok' + b' ' * 65536))
        self.assertFalse(result['accepted'])
        self.assertNotIn('synthetic', str(result))
        with self.assertRaisesRegex(ValueError, '^unknown notification target$'):
            notify.test_notification({'targets': [target]}, 'private-value')

    def test_prepared_delivery_keeps_private_handles_and_independent_results(self):
        first = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        second = self.target('discord', 'https://discord.com/api/webhooks/123456/synthetic_TOKEN')
        config = {'targets': [first, second], 'max_attempts': 10}
        now = datetime.now(timezone.utc)
        calls = []
        with Store(self.root/'state') as store:
            notify.prepare_notifications(store, config, now)
            store.enqueue('incident-safe', {'reason_code': 'budget_warning', 'status': 'warning',
                'resource_ref': 'resource-a1', 'value': '2.50', 'hard_limit_usd': '5.00',
                'threshold_usd': '2.00', 'description': 'secret provider string @everyone',
                'reason': '<@123> secret', 'period_start': '2026-10-01T00:00:00+00:00'}, now)
            first['url_file'].write_text('https://hooks.slack.com/services/TOTHER/BOTHER/changed')
            def transport(url, body):
                calls.append((url, json.loads(body)))
                return (200, b'ok') if 'slack' in url else (200, b'{"error":"invalid"}')
            result = notify.deliver(store, config, now, transport=transport)
            self.assertEqual((result['delivered'], result['failed'], result['pending']), (1, 1, 1))
            slack = next(call for call in calls if 'slack' in call[0])
            self.assertIn('/TTEST/BTEST/', slack[0])
            self.assertIn('5.00', slack[1]['text'])
            self.assertIn('2.00', slack[1]['text'])
            self.assertNotIn('secret', str(calls))
            self.assertNotIn('@', str(calls))
            self.assertNotIn('synthetic', str(result))

    def test_prepare_legacy_preserves_legacy_enqueue_and_counters(self):
        now = datetime.now(timezone.utc)
        target = self.target('webhook', 'https://alerts.example.invalid/receiver')
        with Store(self.root/'state') as store:
            notify.prepare_notifications(store, {'url_file': target['url_file']}, now)
            store.enqueue('legacy-event', {'reason_code': 'warning'}, now)
            self.assertEqual(notify.deliver(store, {'url_file': target['url_file']}, now,
                             transport=lambda url, body: 204),
                             {'delivered': 1, 'failed': 0, 'pending': 0})

    def test_invalid_nested_json_and_email_dot_atoms_fail_safely(self):
        target = self.target('discord', 'https://discord.com/api/webhooks/123456/synthetic_TOKEN')
        self.assertFalse(self.send(target, (200, b'[' * 2000 + b']' * 2000))[0]['accepted'])
        settings = {'host': 'smtp.example.invalid', 'port': 465, 'tls': 'ssl',
                    'username': 'synthetic', 'password': 'synthetic',
                    'from': '..guard@example.invalid', 'to': 'owner@example.invalid'}
        target = {'id': 'mail', 'type': 'email', 'settings_file': self.secret('settings', json.dumps(settings))}
        self.assertIsNone(notify.resolve_targets({'targets': [target]})[0]['credentials'])

    def test_multi_attempt_budget_is_global_and_success_is_not_resent(self):
        config = {'targets': [dict(self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic'),
                                  id='slack-' + str(index)) for index in range(16)], 'max_attempts': 99}
        now = datetime.now(timezone.utc)
        calls = []
        def transport(url, body):
            calls.append(body)
            return 200, b'ok'
        with Store(self.root/'state') as store:
            notify.prepare_notifications(store, config, now)
            store.enqueue('one-event', {'reason_code': 'budget_warning'}, now)
            first = notify.deliver(store, config, now, transport=transport)
            self.assertEqual((first['delivered'], first['pending'], len(calls)), (10, 6, 10))
            second = notify.deliver(store, config, now, transport=transport)
            self.assertEqual((second['delivered'], second['pending'], len(calls)), (6, 0, 16))

    def test_native_http_reads_bounded_response_without_proxy_or_redirects(self):
        class Reply:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                self.size = size
                return b'x' * size
        reply = Reply()
        observed = {}
        class Opener:
            def open(self, request, *, timeout):
                observed['timeout'] = timeout
                return reply
        def build(*handlers):
            observed['handlers'] = handlers
            return Opener()
        with patch.object(notify.urllib.request, 'build_opener', side_effect=build):
            with self.assertRaisesRegex(ValueError, 'response too large'):
                notify._http_post('https://alerts.example.invalid/receiver', b'{}')
        self.assertEqual(reply.size, 65537)
        self.assertEqual(observed['timeout'], 5)
        self.assertTrue(any(isinstance(handler, notify.NoRedirect) for handler in observed['handlers']))
        proxies = [handler for handler in observed['handlers'] if isinstance(handler, notify.urllib.request.ProxyHandler)]
        self.assertEqual(proxies[0].proxies, {})
        self.assertIsNone(notify.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))

    def test_replacing_secret_between_stat_and_open_is_rejected(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        replacement = self.secret('replacement', 'https://hooks.slack.com/services/TOTHER/BOTHER/changed')
        original_open = os.open
        def raced_open(path, flags):
            os.replace(replacement, path)
            return original_open(path, flags)
        with patch.object(os, 'open', side_effect=raced_open):
            resolved = notify.resolve_targets({'targets': [target]})[0]
        self.assertIsNone(resolved['credentials'])

    def test_native_malformed_http_response_is_sanitized(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        def transport(url, body):
            raise http.client.BadStatusLine('private response')
        result = notify.test_notification({'targets': [target]}, 'slack', send=True, transport=transport)
        self.assertFalse(result['accepted'])
        self.assertNotIn('private', str(result))

    def test_email_ssl_never_falls_back_to_plaintext_and_checks_refusal(self):
        settings = {'host': 'smtp.example.invalid', 'port': 465, 'tls': 'ssl',
                    'username': 'synthetic', 'password': 'synthetic-secret',
                    'from': 'guard@example.invalid', 'to': 'owner@example.invalid'}
        target = {'id': 'mail', 'type': 'email', 'settings_file': self.secret('mail', json.dumps(settings))}
        modes = []
        class SMTP:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def login(self, *args): pass
            def send_message(self, *args, **kwargs): return {'owner@example.invalid': (550, b'refused')}
        def factory(mode, host, port, *, timeout, context):
            modes.append(mode)
            self.assertTrue(context.check_hostname)
            return SMTP()
        result = notify.test_notification({'targets': [target]}, 'mail', send=True, smtp_factory=factory)
        self.assertFalse(result['accepted'])
        self.assertEqual(modes, ['ssl'])

    def test_selected_test_target_does_not_resolve_other_credentials(self):
        selected = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        other = {'id': 'other', 'type': 'slack', 'url_file': self.root/'never-read'}
        original = notify._protected_text
        def read(path):
            self.assertNotEqual(path, other['url_file'])
            return original(path)
        with patch.object(notify, '_protected_text', side_effect=read):
            result = notify.test_notification({'targets': [selected, other]}, 'slack', send=True,
                                              transport=lambda url, body: (200, b'ok'))
        self.assertTrue(result['accepted'])

    def test_cli_send_and_queued_delivery_share_public_transport_boundary(self):
        target = self.target('slack', 'https://hooks.slack.com/services/TTEST/BTEST/synthetic')
        config = {'targets': [target]}
        now = datetime.now(timezone.utc)
        with patch.object(notify, 'send_target', return_value=True), \
                patch.object(notify, '_http_post', side_effect=AssertionError('unmocked network')):
            result = notify.test_notification(config, 'slack', send=True)
            self.assertTrue(result['accepted'])
            with Store(self.root/'state') as store:
                notify.prepare_notifications(store, config, now)
                store.enqueue('queued-event', {'reason_code': 'warning'}, now)
                self.assertEqual(notify.deliver(store, config, now)['delivered'], 1)


if __name__ == '__main__':
    unittest.main()
