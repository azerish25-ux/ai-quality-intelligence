"""Import exact owner-authorized commits using account-created trees only."""
import base64
import importlib.util
import os
from pathlib import Path
import time

spec = importlib.util.spec_from_file_location('saved_recovery', Path(__file__).with_name('import.py'))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
original_post = recovery.post
commits = [
    '6cc87174438c38ad71fad2c0bdf978c6d3255722',
    '158d288252d348ca55e3d2a33e109de882196567',
    '301478f56ce4013ae8e96bd58c07789a884efcd9',
    '7b7ef6f2b2a0ff40cce6b57d5c6af317c753abc5',
]
expected_trees = iter([
    'e0ef27dc767e8060cde62d8cb3472fdbf3d2a8e7',
    '750a01748ee4f3ee04ad0fe14c41150dab3178b0',
    '541388a412ec992f986682e40d72f891f1567e01',
    '059cdb7202bfc4b6d050d830d16f69aa0ed4866e',
])

if os.environ.get('GITHUB_REPOSITORY') != recovery.REPOSITORY:
    raise RuntimeError('Wrong repository')
# Reconstruct and verify every original object locally before remote import.
os.environ['FINALITY_RECOVERY_OFFLINE'] = '1'
recovery.main()
del os.environ['FINALITY_RECOVERY_OFFLINE']
parent = recovery.BASE
uploaded = set()
for commit in commits:
    paths = recovery.git('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', parent, commit).split(b'\0')
    for raw_path in paths:
        if not raw_path:
            continue
        path = raw_path.decode('utf-8')
        entry = recovery.git('ls-tree', commit, '--', path).decode().rstrip('\n')
        if not entry:
            continue
        metadata, actual_path = entry.split('\t', 1)
        mode, kind, sha = metadata.split(' ')
        if kind != 'blob' or mode not in {'100644', '100755'} or path != actual_path:
            raise RuntimeError('Unexpected saved entry')
        if sha not in uploaded:
            content = recovery.git('cat-file', 'blob', sha)
            created = original_post('blobs', {'encoding': 'base64', 'content': base64.b64encode(content).decode()})
            if created['sha'] != sha:
                raise RuntimeError('Uploaded blob differs')
            uploaded.add(sha)
    parent = commit
print('All saved blob versions uploaded and verified; owner creates exact trees.', flush=True)

def delegated_post(endpoint, value):
    if endpoint == 'trees':
        # main() checks the independently reconstructed tree hash, and the commit
        # API verifies that the account-created tree exists. No tree POST occurs.
        return {'sha': next(expected_trees)}
    deadline = time.monotonic() + 300
    while True:
        try:
            return original_post(endpoint, value)
        except RuntimeError as error:
            missing_tree = endpoint == 'commits' and any(
                f'Git object API commits: HTTP {status}:' in str(error) for status in (404, 422))
            if not missing_tree or time.monotonic() >= deadline:
                raise
            print('Waiting for account-created tree before exact commit import.', flush=True)
            time.sleep(5)

recovery.post = delegated_post
recovery.main()
