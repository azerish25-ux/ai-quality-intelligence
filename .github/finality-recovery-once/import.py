"""Restore owner-authorized saved commits as exact Git objects; never move refs."""
from __future__ import annotations
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zlib

REPOSITORY = 'azerish25-ux/ai-quality-intelligence'
BASE = '304d0c8875e8a751f9b5f7b807356da2d2c90ea4'
FINAL = '7b7ef6f2b2a0ff40cce6b57d5c6af317c753abc5'
TREE = '059cdb7202bfc4b6d050d830d16f69aa0ed4866e'
PAYLOAD_DIGEST = '1e008e1fbf1cf7b0d349a42fb988c138d046ce5a0f0ec8acc3eed60f286b7954'

def git(*args: str, data: bytes | None = None, env=None) -> bytes:
    return subprocess.check_output(['git', *args], input=data, env=env)

def decode(item: dict) -> bytes:
    if 't' in item:
        return item['t'].encode('utf-8')
    if 'b' in item:
        return base64.b64decode(item['b'], validate=True)
    if 'z' in item:
        return b''.join(decode(part) for part in item['z'])
    compressor = zlib.compressobj(item['l'], zlib.DEFLATED, -15)
    result = compressor.compress(decode(item['d'])) + compressor.flush()
    if hashlib.sha256(result).hexdigest() != item['h']:
        raise RuntimeError('ZIP compression stream differs; refusing altered snapshot')
    return result

def identity(value: str) -> dict:
    match = re.fullmatch(r'(.*) <([^<>]+)> ([0-9]+) ([+-])([0-9]{2})([0-9]{2})', value)
    if not match:
        raise ValueError('Unsupported original Git identity')
    name, email, timestamp, sign, hours, minutes = match.groups()
    offset = timedelta(hours=int(hours), minutes=int(minutes))
    if sign == '-':
        offset = -offset
    return {'name': name, 'email': email,
            'date': datetime.fromtimestamp(int(timestamp), timezone(offset)).isoformat()}

def post(endpoint: str, value: dict) -> dict:
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/git/{endpoint}',
        data=json.dumps(value).encode('utf-8'), method='POST',
        headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'failurelens-saved-commit-recovery'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Git object API {endpoint}: HTTP {error.code}: '
                           + error.read(2000).decode('utf-8', errors='replace')) from None

def main() -> None:
    offline = os.environ.get('FINALITY_RECOVERY_OFFLINE') == '1'
    if not offline and os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('Wrong repository')
    location = Path(os.environ.get('FINALITY_PAYLOAD_DIR', '.github/finality-recovery-once'))
    encoded = ''.join((location / f'payload-{number}.txt').read_text() for number in range(4))
    compressed = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(compressed).hexdigest() != PAYLOAD_DIGEST:
        raise RuntimeError('Payload digest mismatch')
    payload = json.loads(lzma.decompress(compressed, memlimit=128 * 1024 * 1024))
    if payload['base'] != BASE or payload['final'] != FINAL:
        raise RuntimeError('Wrong source range')
    snapshot = decode(payload['zip'])
    snapshot_sha = git('hash-object', '-w', '--stdin', data=snapshot).decode().strip()
    if snapshot_sha != payload['zip_sha']:
        raise RuntimeError('Snapshot blob differs')
    uploaded = set()
    expected_parent = BASE
    for entry in payload['commits']:
        raw_commit = entry['commit'].encode('utf-8')
        headers, message = entry['commit'].split('\n\n', 1)
        fields = dict(line.split(' ', 1) for line in headers.splitlines())
        if set(fields) != {'tree', 'parent', 'author', 'committer'} or fields['parent'] != expected_parent:
            raise RuntimeError('Unexpected saved commit ancestry or headers')
        with tempfile.TemporaryDirectory(prefix='finality-index-') as temp:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'))
            git('read-tree', expected_parent, env=env)
            git('apply', '--cached', '--whitespace=nowarn', '-', data=entry['patch'].encode(), env=env)
            if entry['has_zip']:
                git('update-index', '--add', '--cacheinfo',
                    '100644,' + snapshot_sha + ',' + payload['zip_path'], env=env)
            actual_tree = git('write-tree', env=env).decode().strip()
        if actual_tree != fields['tree']:
            raise RuntimeError('Reconstructed tree differs for ' + entry['sha'])
        actual_commit = git('hash-object', '-t', 'commit', '-w', '--stdin', data=raw_commit).decode().strip()
        if actual_commit != entry['sha']:
            raise RuntimeError('Original commit differs')
        if not offline:
            entries = []
            changed = git('diff-tree', '--no-commit-id', '--name-status', '-r', '-z', expected_parent, actual_commit).decode().split('\0')
            for index in range(0, len(changed) - 1, 2):
                status, path = changed[index:index + 2]
                if status == 'D':
                    entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
                    continue
                if status not in {'A', 'M'}:
                    raise RuntimeError('Unexpected path change type')
                metadata, actual_path = git('ls-tree', actual_commit, '--', path).decode().rstrip('\n').split('\t', 1)
                mode, kind, sha = metadata.split(' ')
                if kind != 'blob' or mode not in {'100644', '100755'} or actual_path != path:
                    raise RuntimeError('Unexpected tree entry')
                if sha not in uploaded:
                    content = git('cat-file', 'blob', sha)
                    created = post('blobs', {'encoding': 'base64', 'content': base64.b64encode(content).decode()})
                    if created['sha'] != sha:
                        raise RuntimeError('Uploaded blob differs')
                    uploaded.add(sha)
                entries.append({'path': path, 'mode': mode, 'type': kind, 'sha': sha})
            parent_tree = git('rev-parse', expected_parent + '^{tree}').decode().strip()
            created = post('trees', {'base_tree': parent_tree, 'tree': entries})
            if created['sha'] != actual_tree:
                raise RuntimeError('Uploaded tree differs')
            created = post('commits', {'message': message, 'tree': actual_tree, 'parents': [expected_parent],
                                       'author': identity(fields['author']), 'committer': identity(fields['committer'])})
            if created['sha'] != actual_commit:
                raise RuntimeError('Uploaded commit differs: expected ' + actual_commit + ', got ' + created['sha'])
        print(('VERIFIED' if offline else 'IMPORTED') + ' ' + actual_commit + ' tree=' + actual_tree, flush=True)
        expected_parent = actual_commit
    if expected_parent != FINAL or git('rev-parse', FINAL + '^{tree}').decode().strip() != TREE:
        raise RuntimeError('Final identity mismatch')
    print('All four original commits verified. No branch or tag ref was changed.', flush=True)

if __name__ == '__main__':
    main()
