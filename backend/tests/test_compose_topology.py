from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_only_fixed_route_gateway_can_reach_edge_network():
    config = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    assert config['networks']['failurelens']['internal'] is True
    for service in ('db', 'api', 'worker'):
        assert config['services'][service]['networks'] == ['failurelens']
        assert not config['services'][service].get('ports')
    gateway = config['services']['dashboard']
    assert set(gateway['networks']) == {'failurelens', 'edge'}
    assert set(gateway['ports']) == {'127.0.0.1:8080:8080', '127.0.0.1:8000:8000'}
    nginx = (ROOT / 'frontend/nginx.conf').read_text()
    assert 'listen 8000;' in nginx and 'listen 8080;' in nginx
    assert 'proxy_pass http://api:8000;' in nginx
    assert 'proxy_pass $' not in nginx


def test_recovery_gate_keeps_real_failure_assertions_and_disposable_scope():
    script = (ROOT / 'scripts/compose_recovery_smoke.sh').read_text()
    assert '--confirm-disposable-stack' in script
    assert 'docker compose -p "$PROJECT"' in script
    assert "Runtime external-network isolation failed" in script
    assert 'pg_restore' in script and '--single-transaction --exit-on-error' in script
    assert 'report_snapshot(session,runs[0])' in script


def test_restore_extracts_before_application_import_initializes_storage():
    script = (ROOT / 'scripts/compose_recovery_smoke.sh').read_text()
    restore = script.split('--entrypoint python api -c', 1)[1]
    assert restore.index('root.mkdir()') < restore.index('archive.extractall(')
    assert restore.index('archive.extractall(') < restore.index('from failurelens.')
    # Existing destinations must still be rejected, never overwritten silently.
    assert 'root.mkdir(exist_ok=True)' not in restore
