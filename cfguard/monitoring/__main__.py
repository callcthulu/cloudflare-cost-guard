"""Explicit commands; default watcher mode is a credential-free preview."""
import argparse
import json
import sqlite3
import sys

from .runtime import Busy, load_config, sample, watch


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only monitoring; never a Cloudflare spending cap.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('validate', 'sample', 'watch'):
        command = sub.add_parser(name)
        command.add_argument('--config', required=True)
        if name == 'sample': command.add_argument('--output', required=True)
        if name == 'watch':
            command.add_argument('--apply', action='store_true', help='Persist monitoring incidents locally.')
            command.add_argument('--send', action='store_true', help='Also deliver to the configured SMTP recipient; requires --apply.')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == 'validate': report, code = {'valid': True}, 0
        elif args.command == 'sample':
            if 'guard_database' not in config or not config.get('accounts'): raise ValueError('sampler_configuration_missing')
            report, code = sample(config, args.output), 0
        else:
            if not ('observation_file' in config or 'ssh_profile' in config): raise ValueError('watch_source_missing')
            if not config.get('expected_account_refs'): raise ValueError('account_baseline_missing')
            report = watch(config, apply=args.apply, send=args.send)
            code = 5 if report.get('failed') or report.get('pending') else 4 if report['issues'] or report.get('active_incidents') else 0
    except Busy: report, code = {'error': 'overlapping_watch'}, 3
    except (ValueError, TypeError, KeyError): report, code = {'error': 'invalid_configuration_or_evidence'}, 2
    except (OSError, sqlite3.Error): report, code = {'error': 'monitor_unavailable'}, 3
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return code


if __name__ == '__main__': sys.exit(main())
