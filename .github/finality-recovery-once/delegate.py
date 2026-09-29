"""Use owner-created, verified trees; the workflow token does not create trees."""
import importlib.util
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location('saved_recovery', Path(__file__).with_name('import.py'))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
original_post = recovery.post
expected_trees = iter([
    'e0ef27dc767e8060cde62d8cb3472fdbf3d2a8e7',
    '750a01748ee4f3ee04ad0fe14c41150dab3178b0',
    '541388a412ec992f986682e40d72f891f1567e01',
    '059cdb7202bfc4b6d050d830d16f69aa0ed4866e',
])

def delegated_post(endpoint, value):
    if endpoint != 'trees':
        return original_post(endpoint, value)
    sha = next(expected_trees)
    print('Awaiting owner-created exact tree ' + sha, flush=True)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f'https://api.github.com/repos/{recovery.REPOSITORY}/git/trees/{sha}?recovery_probe={time.time_ns()}',
            headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                     'Accept': 'application/vnd.github+json', 'Cache-Control': 'no-cache',
                     'User-Agent': 'failurelens-saved-commit-recovery'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
            if result['sha'] != sha:
                raise RuntimeError('Owner-created tree identity differs')
            return result
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise RuntimeError(f'Tree verification: HTTP {error.code}') from None
        time.sleep(5)
    raise RuntimeError('Owner-created tree was not available; no ref changed')

recovery.post = delegated_post
recovery.main()
