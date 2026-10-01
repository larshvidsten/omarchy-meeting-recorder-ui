#!/usr/bin/env python3
"""Validate cached drafts and delivery receipts without a model read-back."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
sys.dont_write_bytecode = True
from importlib.machinery import SourceFileLoader
helpers = SourceFileLoader('speaker_helpers', str(Path(__file__).with_name('speaker-transcript.py'))).load_module()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def uri_ok(uri):
    parsed = urlparse(uri)
    return (parsed.scheme == 'tana' and bool(parsed.netloc or parsed.path)) or (
        parsed.scheme == 'https' and parsed.hostname is not None
        and (parsed.hostname == 'tana.inc' or parsed.hostname.endswith('.tana.inc')))


def validate(phase, data):
    required = {'context': ['event_context', 'destination_context', 'type_definition'],
                'draft': ['note_title', 'fields_json', 'destination_context'],
                'publish': ['note_title', 'session_uri', 'message', 'status']}[phase]
    if not isinstance(data, dict) or any(not isinstance(data.get(key), str) for key in required):
        raise ValueError(f'Invalid {phase} result')
    if any(not data[key].strip() for key in required if key not in ('event_context', 'fields_json')):
        raise ValueError(f'Empty {phase} result')
    if phase == 'draft':
        blocks = data.get('blocks')
        if not isinstance(blocks, list) or not blocks or any(not isinstance(b, str) or not b.strip() for b in blocks):
            raise ValueError('Draft must contain the complete note blocks')
        if data['fields_json']:
            json.loads(data['fields_json'])
    if phase == 'publish' and not uri_ok(data['session_uri']):
        raise ValueError('Missing or invalid Tana node link')
    if phase == 'publish' and data['status'] not in ('created', 'already_exists'):
        raise ValueError('Invalid publication status')
    return data


def main():
    action, *args = sys.argv[1:]
    if action == 'key':
        print(hashlib.sha256('\n'.join(digest(p) for p in args).encode()).hexdigest())
    elif action == 'cached':
        path, key, phase = args
        data = helpers.read(path)
        if data.get('cache_key') != key:
            raise ValueError('Stale cache')
        validate(phase, data['result'])
    elif action == 'save':
        raw, path, key, phase = args
        helpers.dump(path, dict(schema_version=1, cache_key=key, result=validate(phase, helpers.read(raw))))
    elif action == 'prepare-draft':
        path, fingerprint, basename = args
        cached = helpers.read(path)
        draft = validate('draft', cached['result'])
        draft['blocks'] = [b for b in draft['blocks'] if not b.startswith(('Source recording:', 'Source recording SHA256:'))]
        draft['blocks'] += ['Source recording: ' + basename, 'Source recording SHA256: ' + fingerprint]
        helpers.dump(path, cached)
    elif action == 'complete':
        draft_path, receipt_path, output, fingerprint = args
        cached_receipt = helpers.read(receipt_path)
        receipt = validate('publish', cached_receipt['result'])
        source = cached_receipt.get('source_sha256')
        if source is None:
            # Older receipts predate explicit source identity; recover it from the saved draft.
            draft = helpers.read(draft_path)['result']
            if 'Source recording SHA256: ' + fingerprint not in draft.get('blocks', []):
                raise ValueError('Receipt belongs to a different recording')
        elif source != fingerprint:
            raise ValueError('Receipt belongs to a different recording')
        helpers.dump(output, dict(receipt, delivery_confirmed=True, source_sha256=fingerprint))

    else:
        raise ValueError('Unknown operation')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Tana workflow: {error}', file=sys.stderr)
        sys.exit(1)
