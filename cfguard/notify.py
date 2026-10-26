"""Bounded generic HTTPS webhook delivery. Destination is a protected external file."""
import json
import os
import ssl
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _destination(path):
    from pathlib import Path
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('unsafe notification file')
    info = path.stat()
    if not path.is_file() or info.st_size > 8192:
        raise ValueError('invalid notification file')
    if os.name == 'posix' and (info.st_mode & 0o007 or info.st_mode & 0o022):
        raise ValueError('notification file must be protected')
    url = path.read_text(encoding='utf-8').strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('HTTPS notification destination required')
    return url


def _post(url, body):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json'}, method='POST')
    with opener.open(req, timeout=5) as response:
        return response.status


def deliver(store, configuration, now, *, transport=None):
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
    return {'delivered': delivered, 'failed': failed, 'pending': store.pending_count()}
