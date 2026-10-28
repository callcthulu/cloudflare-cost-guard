"""Bounded, private notification transports using only the standard library."""
import hashlib
import http.client
import json
import os
import re
import smtplib
import ssl
import stat
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.headerregistry import Address
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _destination(path):
    return _https_url(_protected_text(path))


def _protected_text(path):
    """Open once, refusing link/nonregular files and metadata changes during read."""
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('unsafe notification file')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 8192:
        raise ValueError('invalid notification file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 8192 or
                (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('invalid notification file')
        if os.name == 'posix' and info.st_mode & 0o027:
            raise ValueError('notification file must be protected')
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            data = handle.read(8193)
        after = os.fstat(fd)
        current = path.stat()
        if (len(data) > 8192 or
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or
                path.is_symlink() or any(parent.is_symlink() for parent in path.parents)):
            raise ValueError('notification file changed')
        return data.decode('utf-8').strip()
    finally:
        os.close(fd)


def _https_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
            parsed.fragment or any(char.isspace() or ord(char) < 32 for char in url)):
        raise ValueError('HTTPS notification destination required')
    parsed.port  # Reject malformed ports before attempting a network operation.
    return url


def _post(url, body):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json'}, method='POST')
    with opener.open(req, timeout=5) as response:
        return response.status


def _http_post(url, body):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json'}, method='POST')
    with opener.open(req, timeout=5) as response:
        data = response.read(65537)
        if len(data) > 65536:
            raise ValueError('notification response too large')
        return response.status, data


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()


def _target_specs(configuration):
    if not configuration:
        return ()
    if 'targets' not in configuration:
        return ({'id': 'legacy-webhook', 'type': 'webhook',
                 'url_file': configuration['url_file']},)
    return tuple(configuration['targets'])


def _email_settings(path):
    settings = json.loads(_protected_text(path))
    fields = {'host', 'port', 'tls', 'username', 'password', 'from', 'to'}
    if not isinstance(settings, dict) or set(settings) != fields:
        raise ValueError('invalid email settings')
    for name in fields - {'port'}:
        value = settings[name]
        if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(c) < 32 for c in value):
            raise ValueError('invalid email settings')
    if (not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', settings['host']) or
            type(settings['port']) is not int or not 1 <= settings['port'] <= 65535 or
            settings['tls'] not in ('ssl', 'starttls')):
        raise ValueError('invalid email settings')
    for name in ('from', 'to'):
        value = settings[name]
        if (not value.isascii() or len(value) > 254 or
                not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)):
            raise ValueError('invalid email envelope')
        Address(addr_spec=value)
    return settings


def _resolve_one(spec):
    kind = spec['type']
    config = {key: str(value) for key, value in spec.items()}
    result = {'id': spec['id'], 'type': kind, 'config_digest': _digest(config),
              'destination_digest': None, 'credentials': None}
    try:
        if kind in ('webhook', 'slack', 'discord'):
            url = _destination(spec['url_file'])
            parsed = urllib.parse.urlsplit(url)
            if kind == 'slack' and (parsed.netloc not in ('hooks.slack.com', 'hooks.slack-gov.com') or
                    not re.fullmatch(r'/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', parsed.path) or parsed.query):
                raise ValueError('invalid Slack destination')
            if kind == 'discord' and (parsed.netloc != 'discord.com' or
                    not re.fullmatch(r'/api/(?:v10/)?webhooks/[0-9]+/[A-Za-z0-9._-]+', parsed.path) or parsed.query):
                raise ValueError('invalid Discord destination')
            credentials, identity = {'url': url}, url
        elif kind == 'telegram':
            token = _protected_text(spec['token_file'])
            chat_id = _protected_text(spec['chat_id_file'])
            if (not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token) or
                    not re.fullmatch(r'-?[0-9]{1,19}', chat_id) or
                    not -(1 << 63) <= int(chat_id) < (1 << 63) or int(chat_id) == 0):
                raise ValueError('invalid Telegram destination')
            credentials, identity = {'token': token, 'chat_id': chat_id}, [token.split(':', 1)[0], chat_id]
        elif kind == 'email':
            credentials = _email_settings(spec['settings_file'])
            identity = {key: value for key, value in credentials.items() if key != 'password'}
        else:
            raise ValueError('invalid notification type')
        result.update(credentials=credentials, destination_digest=_digest(identity))
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        pass  # Do not return exceptions, credentials, URLs or provider response bodies.
    return result


def resolve_targets(configuration):
    """Resolve declared targets once; invalid credentials remain unresolved routes."""
    return tuple(_resolve_one(spec) for spec in _target_specs(configuration))


def prepare_notifications(store, configuration, now):
    if configuration and 'targets' in configuration:
        targets = resolve_targets(configuration)
        routes = [{key: target[key] for key in ('id', 'config_digest', 'destination_digest')}
                  for target in targets]
        cancelled = store.configure_notification_targets(routes, now)
    else:
        targets = ()
        cancelled = store.disable_notification_targets(now) if hasattr(store, 'disable_notification_targets') else 0
    store._resolved_notification_targets = targets
    store._notification_cancelled = cancelled
    return cancelled


def _title(payload):
    if payload.get('notification_test') is True:
        return 'TEST notification'
    if payload.get('reason_code') == 'budget_warning':
        return 'Budget warning'
    if payload.get('reason_code') == 'cutoff_result':
        return {'worker_deleted': 'Worker deleted',
                'endpoints_disabled': 'workers.dev/preview endpoints disabled',
                'uncertain': 'Cutoff outcome uncertain',
                'not_applied': 'Cutoff not applied'}.get(payload.get('status'), 'Cutoff result')
    return 'Monitoring alert'


def _safe_text(payload):
    lines = ['Cloudflare Cost Guard: ' + _title(payload)]
    if payload.get('notification_test') is True:
        lines.append('TEST - synthetic notification; no Cloudflare action')
    fields = ('reason_code', 'status', 'action', 'scope', 'currency', 'resource_ref',
              'incident_id', 'value', 'hard_limit_usd', 'threshold_usd', 'quality',
              'source', 'period_start', 'period_end', 'metric', 'reason', 'limit',
              'threshold', 'period', 'action_reason')
    for field in fields:
        value = payload.get(field)
        if type(value) not in (str, int):
            continue
        text = str(value)
        if len(text) > 160 or not re.fullmatch(r'[A-Za-z0-9_.:/% +\-]{1,160}', text):
            continue
        line = field + ': ' + text
        if len('\n'.join(lines + [line])) > 1850:
            lines.append('[remaining context omitted]')
            break
        lines.append(line)
    return '\n'.join(lines)


def _smtp_factory(mode, host, port, *, timeout, context):
    if mode == 'ssl':
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    return smtplib.SMTP(host, port, timeout=timeout)


def send_target(target, payload, *, transport=None, smtp_factory=None):
    """Send using a resolved private handle, without re-reading credential files."""
    credentials, kind = target['credentials'], target['type']
    if credentials is None:
        return False
    try:
        text = _safe_text(payload)
        if kind == 'email':
            message = EmailMessage()
            message['Subject'] = 'Cloudflare Cost Guard: ' + _title(payload)
            message['From'], message['To'] = credentials['from'], credentials['to']
            message.set_content(text)
            context = ssl.create_default_context()
            with (smtp_factory or _smtp_factory)(credentials['tls'], credentials['host'], credentials['port'],
                                                 timeout=5, context=context) as client:
                if credentials['tls'] == 'starttls':
                    client.ehlo()
                    client.starttls(context=context)
                    client.ehlo()
                client.login(credentials['username'], credentials['password'])
                refused = client.send_message(message, from_addr=credentials['from'], to_addrs=[credentials['to']])
                return refused == {}
        if kind == 'telegram':
            url = 'https://api.telegram.org/bot' + credentials['token'] + '/sendMessage'
            body = {'chat_id': credentials['chat_id'], 'text': text}
        else:
            url = credentials['url']
            if kind == 'webhook':
                body = payload
            elif kind == 'slack':
                body = {'text': text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                        'mrkdwn': False, 'link_names': False, 'unfurl_links': False, 'unfurl_media': False}
            else:
                url += '?wait=true'
                body = {'content': text, 'allowed_mentions': {'parse': []}}
        status, response = (transport or _http_post)(url, json.dumps(body, sort_keys=True, allow_nan=False).encode())
        if type(status) is not int or not 200 <= status < 300 or not isinstance(response, bytes) or len(response) > 65536:
            return False
        if kind == 'webhook':
            return True
        if kind == 'slack':
            return status == 200 and response == b'ok'
        decoded = json.loads(response)
        if not isinstance(decoded, dict):
            return False
        if kind == 'discord':
            return isinstance(decoded.get('id'), str) and bool(re.fullmatch(r'[0-9]+', decoded['id']))
        return (decoded.get('ok') is True and isinstance(decoded.get('result'), dict) and
                type(decoded['result'].get('message_id')) is int)
    except (OSError, ValueError, TypeError, KeyError, smtplib.SMTPException,
            http.client.HTTPException, OverflowError, RecursionError):
        return False


def test_notification(configuration, target_id, *, send=False, transport=None, smtp_factory=None):
    """Preview without secret reads; explicit send isolates one synthetic delivery."""
    spec = next((spec for spec in _target_specs(configuration) if spec['id'] == target_id), None)
    if spec is None:
        raise ValueError('unknown notification target')
    result = {'target_ref': hashlib.sha256(target_id.encode()).hexdigest()[:16],
              'type': spec['type'], 'preview': not send, 'human_receipt_verified': False}
    if send:
        target = _resolve_one(spec)
        result['accepted'] = send_target(target, {'notification_test': True, 'reason_code': 'synthetic_test'},
                                           transport=transport, smtp_factory=smtp_factory)
    return result


def deliver(store, configuration, now, *, transport=None, smtp_factory=None):
    if configuration and 'targets' in configuration:
        if not hasattr(store, '_resolved_notification_targets'):
            prepare_notifications(store, configuration, now)
        targets = {target['id']: target for target in store._resolved_notification_targets}
        delivered = failed = 0
        for event in store.pending_deliveries(now, min(int(configuration.get('max_attempts', 3)), 10)):
            target = targets.get(event['target_id'])
            # Never reroute a queued delivery using a newly resolved identity.
            matches = (target is not None and target['config_digest'] == event['config_digest'] and
                       target['destination_digest'] == event['destination_digest'])
            success = matches and send_target(target, event['payload'], transport=transport, smtp_factory=smtp_factory)
            store.notification_delivery_result(event['id'], event['target_id'], bool(success), now)
            delivered += int(success)
            failed += int(not success)
        return {'delivered': delivered, 'failed': failed, 'pending': store.pending_count(),
                'cancelled': store._notification_cancelled, 'targets': store.delivery_summary()['targets']}
    delivered = failed = 0
    if configuration:
        events = store.pending_notifications(now, min(int(configuration.get('max_attempts', 3)), 10))
        for event in events:
            success = False
            try:
                destination = _destination(configuration['url_file'])
                body = json.dumps(event['payload'], sort_keys=True, allow_nan=False).encode()
                status = (transport or _post)(destination, body)
                success = isinstance(status, int) and 200 <= status < 300
            except (OSError, ValueError, KeyError, TypeError):
                # Never log exceptions: network libraries may include secret URLs.
                success = False
            store.notification_result(event['id'], success, now)
            delivered += int(success)
            failed += int(not success)
    report = {'delivered': delivered, 'failed': failed, 'pending': store.pending_count()}
    if getattr(store, '_notification_cancelled', 0):
        report['cancelled'] = store._notification_cancelled
    return report
