"""Real Git/build regressions: packaging noise must not bypass source integrity."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

from evaluation import replay_campaign

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / 'scripts/install_committed_backend.sh'
MEASURED = ('backend/src', 'evaluation', 'frontend', '.github', 'integrations')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def source(tmp_path):
    # This is a tiny disposable Git fixture, not another FailureLens checkout.
    root = tmp_path / 'source with spaces'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Source integrity test')
    git(root, 'config', 'user.email', 'source-test@example.invalid')
    for directory in MEASURED:
        path = root / directory / 'probe.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('VALUE = 1\n')
    (root / 'backend/pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
[project]
name = "failurelens-clean-source-probe"
version = "0.0.0"
[project.optional-dependencies]
dev = []
[tool.setuptools]
package-dir = {"" = "src"}
py-modules = ["probe"]
''')
    (root / 'scripts').mkdir()
    shutil.copyfile(INSTALLER, root / 'scripts/install_committed_backend.sh')
    git(root, 'add', 'backend', 'evaluation', 'frontend', '.github', 'integrations', 'scripts')
    git(root, 'commit', '-m', 'Controlled build fixture')
    return root


def state(source, monkeypatch):
    monkeypatch.setattr(replay_campaign, 'ROOT', source)
    return replay_campaign.source_state()


def install(source, target):
    env = {**os.environ, 'PYTHON': sys.executable, 'PIP_NO_INDEX': '1',
           'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_CONFIG_FILE': os.devnull}
    return subprocess.run(['bash', str(source / 'scripts/install_committed_backend.sh'),
                           '--no-deps', '--no-build-isolation', '--target', str(target)],
                          env=env, text=True, capture_output=True, timeout=60)


def test_real_archived_build_installs_committed_bytes_and_leaves_source_clean(source, tmp_path, monkeypatch):
    before = state(source, monkeypatch)
    assert before['source_worktree_dirty'] is False
    result = install(source, tmp_path / 'installed')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'installed/probe.py').read_text() == 'VALUE = 1\n'
    assert state(source, monkeypatch) == before
    assert not list((source / 'backend/src').glob('*.egg-info'))
    assert 'source remains clean: ' + before['source_revision'] in result.stdout


@pytest.mark.parametrize('directory', MEASURED)
@pytest.mark.parametrize('mutation', ('modified', 'staged', 'deleted', 'untracked'))
def test_source_gate_still_detects_every_measured_boundary(source, monkeypatch, directory, mutation):
    path = source / directory / 'probe.py'
    if mutation == 'deleted':
        path.unlink()
    elif mutation == 'untracked':
        (source / directory / 'uncommitted.py').write_text('UNCOMMITTED = True\n')
    else:
        path.write_text('VALUE = 2\n')
        if mutation == 'staged':
            git(source, 'add', str(path.relative_to(source)))
    result = state(source, monkeypatch)
    assert result['source_worktree_dirty'] is True
    assert any(directory in change for change in result['source_worktree_changes'])


def test_installer_rejects_dirty_source_without_erasing_or_installing_it(source, tmp_path):
    path = source / 'backend/src/probe.py'
    path.write_text('VALUE = 2\n')
    result = install(source, tmp_path / 'installed')
    assert result.returncode != 0
    assert 'Refusing an uncommitted source measurement' in result.stderr
    assert 'backend/src/probe.py' in result.stderr
    assert path.read_text() == 'VALUE = 2\n'
    assert not (tmp_path / 'installed').exists()


def test_packaging_metadata_is_reported_not_silently_ignored(source, tmp_path, monkeypatch):
    # Exercise the old in-place build rather than simulating an egg-info directory.
    result = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                             '--no-index', '--wheel-dir', str(tmp_path / 'wheels'), str(source / 'backend')],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert list((source / 'backend/src').glob('*.egg-info'))
    result = state(source, monkeypatch)
    assert result['source_worktree_dirty'] is True
    assert any('.egg-info' in change for change in result['source_worktree_changes'])


def test_installer_propagates_build_failure_and_cleans_temporary_source(source, tmp_path):
    # Deliberately broken committed packaging is not a successful installation.
    path = source / 'backend/pyproject.toml'
    path.write_text('not valid TOML [')
    git(source, 'add', 'backend/pyproject.toml')
    git(source, 'commit', '-m', 'Deliberately invalid package')
    result = install(source, tmp_path / 'installed')
    assert result.returncode != 0
    assert not (tmp_path / 'installed').exists()
    assert git(source, 'status', '--porcelain') == ''
    assert 'source remains clean:' not in result.stdout


def test_backend_ci_keeps_real_postgresql_coverage_and_clean_build():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    backend = workflow.split('\n  backend:\n', 1)[1].split('\n  evaluation:', 1)[0]
    assert 'bash scripts/install_committed_backend.sh' in backend
    assert 'postgres:17-alpine' in backend
    assert '--cov-branch --cov-report=term-missing --cov-fail-under=75' in backend
    assert 'continue-on-error' not in backend
