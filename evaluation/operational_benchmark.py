#!/usr/bin/env python3
"""Reproducible synthetic API-read load, not a root-cause evaluation corpus."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import socket
import subprocess
import sys
import time
import uuid

import httpx
from sqlalchemy import func, insert, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))
from failurelens.config import get_settings
from failurelens.db import SessionLocal, initialize_database
from failurelens.models import Project, Run, RunStatus, TestExecution as Execution, Outcome
from failurelens.service import create_project


def percentile(values, quantile):
    if not values:
        raise ValueError('no measurements')
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def seed_workload(session, *, runs=1000, tests_per_run=50):
    if session.scalar(select(func.count()).select_from(Project)):
        raise ValueError('benchmark requires an empty disposable database')
    project = create_project(session, 'operational-benchmark', 'Synthetic API read benchmark; not evaluation ground truth')
    start = datetime(2026, 1, 1, tzinfo=UTC)
    run_rows, execution_rows = [], []
    for number in range(runs):
        run_id = str(uuid.UUID(int=number + 1))
        run_rows.append(dict(id=run_id, project_id=project.id, external_id=f'synthetic-load-{number}',
            attempt=1, repository='synthetic/operational-benchmark', commit_sha=f'{number:040x}',
            branch='main', framework='synthetic', run_scope='full_suite', environment='benchmark',
            timezone='UTC', worker_count=1, shard_count=1, status=RunStatus.complete,
            completeness='complete', expected_inputs=1, received_inputs=1,
            manifest_digest=hashlib.sha256(f'load-{number}'.encode()).hexdigest(),
            started_at=start + timedelta(minutes=number), created_at=start + timedelta(minutes=number),
            source_metadata={'synthetic': True, 'benchmark_only': True}))
        for test in range(tests_per_run):
            execution_rows.append(dict(id=str(uuid.UUID(int=1_000_000 + number * tests_per_run + test)),
                run_id=run_id, test_identity=f'load::test-{test}', source_path=f'tests/load-{test}.py',
                browser=('chromium', 'firefox', 'webkit')[number % 3], attempt=0,
                outcome=Outcome.passed, duration_ms=10, retry_recovered=False, details={}))
    session.execute(insert(Run), run_rows)
    for offset in range(0, len(execution_rows), 1000):
        session.execute(insert(Execution), execution_rows[offset:offset + 1000])
    session.commit()
    return project.id, run_rows[-1]['id'], execution_rows[-1]['id']


def measure(base, routes, *, concurrency, samples):
    def one(number):
        route = routes[number % len(routes)]
        started = time.perf_counter()
        try:
            response = httpx.get(base + route, timeout=15, trust_env=False)
            ok = response.status_code == 200 and bool(response.json())
        except (httpx.HTTPError, ValueError):
            ok = False
        return {'route': route.split('?')[0].rsplit('/', 1)[-1],
                'elapsed_ms': (time.perf_counter() - started) * 1000, 'ok': ok}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(one, range(samples)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-disposable-database', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.demo_mode or not settings.database_url.startswith('postgresql'):
        raise SystemExit('This acceptance workload requires explicit demo mode and real PostgreSQL')
    if args.output.exists():
        raise SystemExit('Output must be a fresh directory')
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if status.strip():
        raise SystemExit('Commit source before measuring the benchmark')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    initialize_database()
    seed_started = time.perf_counter()
    with SessionLocal() as session:
        project, run, execution = seed_workload(session)
        db_version = session.scalar(text('SHOW server_version'))
    seed_seconds = time.perf_counter() - seed_started
    args.output.mkdir(parents=True)
    routes = [f'/api/v1/projects/{project}/runs?limit=50', f'/api/v1/runs/{run}',
              f'/api/v1/tests/{execution}/history?limit=50', '/api/v1/overview']
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    base = f'http://127.0.0.1:{port}'
    with (args.output / 'api.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'failurelens.api:app', '--host', '127.0.0.1', '--port', str(port)], stdout=log, stderr=subprocess.STDOUT)
        try:
            ready = False
            for _ in range(120):
                if proc.poll() is not None:
                    raise RuntimeError('API process exited before readiness')
                try:
                    ready = httpx.get(base + '/health/ready', timeout=1, trust_env=False).status_code == 200
                except httpx.HTTPError:
                    pass
                if ready:
                    break
                time.sleep(.25)
            if not ready:
                raise RuntimeError('API readiness timed out')
            cold = measure(base, routes, concurrency=1, samples=4)
            warm = measure(base, routes, concurrency=10, samples=200)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
    successful = [r['elapsed_ms'] for r in warm if r['ok']]
    failures = sum(not r['ok'] for r in warm)
    p95 = percentile(successful, .95) if successful else None
    metrics = {'schema_version': 'operational-benchmark-v1', 'source_revision': sha,
        'scope': 'synthetic_indexed_api_reads', 'database': 'postgresql', 'database_version': db_version,
        'workload': {'runs': 1000, 'logical_executions': 50_000, 'concurrency': 10, 'warm_samples': 200},
        'hardware': {'platform': platform.platform(), 'logical_cpus': os.cpu_count(),
                     'python': platform.python_version(), 'reference_hardware_normalized': False},
        'seed_seconds': seed_seconds, 'cold_reads': cold, 'warm_p95_ms': p95,
        'warm_p50_ms': percentile(successful, .5) if successful else None,
        'failed_requests': failures, 'client_max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'api_child_max_rss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        'database_memory_measured': False, 'whole_stack_memory_measured': False,
        'targets': {'zero_failed_requests': failures == 0, 'api_read_p95_under_500ms': p95 is not None and p95 < 500},
        'limitations': ['Synthetic read workload, not classification evaluation or ingestion throughput',
                         'Actual CI hardware is reported, not normalized to the 2-vCPU reference',
                         'Client timings include HTTP connection overhead; DB and whole-stack memory are not measured']}
    (args.output / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    (args.output / 'requests.json').write_text(json.dumps(warm, indent=2) + '\n')
    print(json.dumps(metrics, indent=2))
    raise SystemExit(0 if all(metrics['targets'].values()) else 2)


if __name__ == '__main__':
    main()
