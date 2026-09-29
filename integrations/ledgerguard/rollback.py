"""Collect real HTTP/PostgreSQL rejection/commit-consistency development evidence.

The original pinned companion is never changed. Both roles use disposable copies:
control rejects after SQL execution but BEFORE commit; intervention deliberately
commits first and then rejects. This tests an injected JDBC transaction-boundary
fault, NOT a defect in unmodified LedgerGuard and NOT a PostgreSQL atomicity bug.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from evaluation.campaign_contract import canonical, digest
from integrations.ledgerguard.diagnostics import add_case, freeze
from integrations.ledgerguard.fullstack import (
    PIN, SOURCE, DEST, RECIPIENT, checkout_digest, request_json, run_command, snapshot,
)
from integrations.ledgerguard.rollback_oracle import verify_observation

COMMAND_FILE = Path('backend/src/main/java/lab/ledgerguard/db/FinancialCommands.java')
COMMAND_BLOB = 'cc5a65192cc940cc48dfaca341b69c943440b507'
HOOK = b'                commitStarted = true;\n'
FAMILY = 'early-commit-before-terminal-rejection'
AMOUNTS = (7, 11, 13, 17)
# Explicit source-versioned interpretation of the isolated API's business
# rejection. Neither a generic HTTP error nor a producer verdict grants it.
SEMANTICS = {
    'version': 'ledgerguard-transfer-rejection-v1', 'source_revision': PIN['revision'],
    'operation': 'TRANSFER', 'status': 422, 'code': 'TRANSFER_REJECTED',
    'policy': 'terminal_rejection_has_no_effects',
}


def mutate_command(raw: bytes, *, early_commit: bool) -> bytes:
    """Accept only the inspected pinned method; mutate a private copy, never main."""
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if actual != COMMAND_BLOB or raw.count(HOOK) != 1:
        raise ValueError('Pinned JDBC transaction boundary differs')
    injected = b'                if ("TRANSFER".equals(operation)) {\n'
    if early_commit:
        injected += b'                    c.commit();\n'
    injected += (b'                    throw new SQLException("Controlled post-command rejection", "P4220");\n'
                 b'                }\n')
    return raw.replace(HOOK, injected + HOOK)


def copy_source(source: Path, destination: Path) -> None:
    """Copy only tracked regular files into a new, private disposable tree."""
    if destination.exists() or destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('A new disjoint disposable source directory is required')
    destination.mkdir(parents=True)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=source).split(b'\0')
    for name in (os.fsdecode(n) for n in names if n):
        src = source / name
        if src.is_symlink() or not src.is_file() or not src.resolve().is_relative_to(source.resolve()):
            raise ValueError('Companion source is not a regular tracked tree')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def observation(before: dict, after: dict, *, amount: int, request_id: str,
                response: dict, semantics_digest: str) -> dict:
    """Translate measured values, not the fault configuration or oracle verdict.

    The independent execution oracle verifies raw SQL structure separately.
    All mutations, credentials and expected labels stay outside public inputs.
    """
    previous_ids = {r['id'] for r in before['effects']}
    added = [r for r in after['effects'] if r['id'] not in previous_ids]
    old_entries = Counter((r['journal_id'], r['account_id'], r['side'], r['amount_minor']) for r in before['entries'])
    current_entries = Counter((r['journal_id'], r['account_id'], r['side'], r['amount_minor']) for r in after['entries'])
    entries = current_entries - old_entries
    b = {r['account_id']: r['posted_minor'] for r in before['balances']}
    a = {r['account_id']: r['posted_minor'] for r in after['balances']}
    measurement = dict(
        kind='transaction_finality', finality_policy='terminal_rejection_has_no_effects',
        observation_scope='isolated_logical_request', snapshot_basis='committed_primary_database',
        request_digest=request_id, receipt_request_digest=request_id,
        source_account_digest=digest(SOURCE.encode()), destination_account_digest=digest(DEST.encode()),
        currency='CAD', amount_minor=amount, contract_digest=semantics_digest, served_contract_digest=semantics_digest,
        response_basis='terminal_business_rejection', rejection_status=422, rejection_code='TRANSFER_REJECTED',
        response_status=response['status'], response_code=response['code'], concurrent_writers=0,
        before_source_minor=b[SOURCE], before_destination_minor=b[DEST], after_source_minor=a[SOURCE], after_destination_minor=a[DEST],
        new_transfer_count=len(added), new_journal_entry_count=sum(entries.values()),
        new_debit_minor=sum(key[3] * count for key, count in entries.items() if key[2] == 'DEBIT'),
        new_credit_minor=sum(key[3] * count for key, count in entries.items() if key[2] == 'CREDIT'),
    )
    return dict(schema_version='contract-observations-v1', test_identity='measurement::result',
                attempt=0, browser=None, measurement=measurement)


def synthetic_observation(variant: int = 0, *, effects: bool = True) -> dict:
    """Explicitly synthetic development fixture; never labeled executed."""
    amount = AMOUNTS[variant % len(AMOUNTS)]
    before = dict(balances=[dict(account_id=SOURCE, posted_minor=100), dict(account_id=DEST, posted_minor=50)], effects=[], entries=[])
    after = deepcopy(before)
    if effects:
        journal = str(uuid.UUID(int=200 + variant))
        after['balances'][0]['posted_minor'] -= amount
        after['balances'][1]['posted_minor'] += amount
        after['effects'] = [dict(id=str(uuid.UUID(int=100 + variant)), source_id=SOURCE, destination_id=DEST,
                                 journal_id=journal, amount_minor=amount, currency='CAD')]
        after['entries'] = [dict(journal_id=journal, account_id=SOURCE, side='DEBIT', amount_minor=amount),
                            dict(journal_id=journal, account_id=DEST, side='CREDIT', amount_minor=amount)]
    return observation(before, after, amount=amount, request_id=digest(f'synthetic-finality-{variant}'.encode()),
                       response={'status': 422, 'code': 'TRANSFER_REJECTED'}, semantics_digest=digest(canonical(SEMANTICS)))


def write_corpus(output: Path, pairs: list[dict], provenance: dict, *, executed: bool) -> dict:
    """Freeze this development slice, preserving old benchmark/report bytes."""
    if len(pairs) != len(AMOUNTS) or any(set(pair) != {'observation', 'control'} for pair in pairs):
        raise ValueError('Four complete paired observations are required')
    if type(executed) is not bool:
        raise ValueError('Explicit executed/synthetic scope is required')
    if output.exists():
        raise ValueError('Refusing to overwrite a corpus')
    output.mkdir(parents=True)
    public, labels, families = [], [], {}
    revision = PIN['revision'] if executed else provenance['failurelens_revision']
    for i, pair in enumerate(pairs):
        add_case(output, public, labels, families, record=pair['observation'], control=pair['control'],
                 family=FAMILY, variant=i, source_kind='ledgerguard_executed' if executed else 'synthetic',
                 revision=revision, category='product_defect', severity='critical',
                 oracle='Separately inspected HTTP rejection, primary-database transfers, journal rows and balance deltas.' if executed
                 else 'Hand-authored synthetic relational fixture; not actual HTTP/PostgreSQL execution.')
    # Missing/ambiguous evidence remains a separate explicitly synthetic case.
    for i, (basis, field) in enumerate([
        ('terminal_business_rejection', 'after_destination_minor'),
        ('terminal_business_rejection', 'new_journal_entry_count'),
        ('transport_only', None), ('unresolved', None),
    ]):
        value = deepcopy(pairs[i % len(pairs)]['observation'])
        value['measurement']['response_basis'] = basis
        if field:
            value['measurement'][field] = None
        if basis != 'terminal_business_rejection':
            value['measurement'].update(response_status=503, response_code='OUTCOME_UNKNOWN')
        add_case(output, public, labels, families, record=value, control=None, family=FAMILY,
                 variant=len(pairs) + i, source_kind='synthetic', revision=revision, category='insufficient_evidence', severity='high',
                 oracle='Explicitly altered missing/ambiguous observations cannot establish terminal no-effects rejection.')
    (output/'response-semantics.json').write_bytes(canonical(SEMANTICS))
    result = freeze(output, public, labels, families, provenance)
    frozen = json.loads((output/'freeze.json').read_bytes())
    frozen['files']['response-semantics.json'] = digest((output/'response-semantics.json').read_bytes())
    frozen['harness_files'].update({str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in [Path(__file__), HERE/'rollback_oracle.py', HERE/'fullstack.py']})
    frozen['limitations'] += ['One early-commit mechanism, not independent families per amount.',
                              'Transport failure does not imply rollback; source mutations are disposable only.']
    (output/'freeze.json').write_bytes(canonical(frozen))
    return result


def build_synthetic(output: Path) -> dict:
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    pairs = [dict(observation=synthetic_observation(i), control=synthetic_observation(i, effects=False)) for i in range(4)]
    return write_corpus(output, pairs, dict(failurelens_revision=revision, executed_pairs=0,
        executed_families=0, synthetic_cases=8, scope='synthetic_regression_only', oracle_receipts=[]), executed=False)


@contextmanager
def disposable_stack(source: Path, private: Path, commands: list):
    project = 'failurelens-finality-' + secrets.token_hex(6)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    values = dict(COMPOSE_PROJECT_NAME=project, POSTGRES_DB='ledgerguard', LEDGER_HTTP_PORT=str(port),
                  LEDGER_AUTH_KEY=base64.b64encode(secrets.token_bytes(64)).decode(),
                  RABBITMQ_DEFAULT_USER='ledgerguard', RABBITMQ_DEFAULT_VHOST='/ledgerguard')
    for key in ('POSTGRES_SUPERUSER_PASSWORD', 'LEDGER_OWNER_PASSWORD', 'LEDGER_RUNTIME_PASSWORD', 'RABBITMQ_DEFAULT_PASS', 'LEDGER_DEMO_PASSWORD'):
        values[key] = secrets.token_hex(32)
    env = private / 'runtime.env'
    env.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    env.chmod(0o600)
    compose = ['docker', 'compose', '--project-name', project, '--env-file', str(env), '-f', str(source/'compose.yaml')]
    try:
        run_command([*compose, 'up', '-d', '--build', '--wait', 'postgres', 'api'], source, commands, timeout=900)
        run_command([*compose, 'run', '--rm', 'seed'], source, commands, timeout=120)
        yield compose, port, values['LEDGER_DEMO_PASSWORD']
    finally:
        # This exact random project only; never prune Docker or touch other stacks.
        run_command([*compose, 'down', '--volumes', '--remove-orphans'], source, commands, timeout=120)


def run(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('A new output directory disjoint from the companion is required')
    if not shutil.which('docker'):
        raise RuntimeError('Real Docker/Compose and PostgreSQL execution is required; no synthetic fallback')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if revision != PIN['revision'] or subprocess.check_output(['git', 'status', '--porcelain'], cwd=source).strip():
        raise ValueError('Companion must be the clean pinned revision')
    source_digest = checkout_digest(source)
    raw = (source/COMMAND_FILE).read_bytes()
    # Check before starting any stack or writing any mutation.
    mutate_command(raw, early_commit=False)
    source_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    provenance = dict(failurelens_revision=source_sha, ledgerguard_revision=revision,
        source_worktree_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT).strip()),
        generated_at=datetime.now(timezone.utc).isoformat(), replay_time_is_synthetic=True,
        companion_tree_sha256=source_digest, executed_pairs=4, executed_families=1, synthetic_cases=4,
        scope='HTTP/PostgreSQL controlled JDBC early-commit mutation; not unmodified companion defect',
        commands=[], oracle_receipts=[], mutations={})
    pairs = [dict() for _ in AMOUNTS]
    try:
        with tempfile.TemporaryDirectory(prefix='failurelens-finality-private-') as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            for role in ('control', 'observation'):
                role_dir = private/role
                role_dir.mkdir()
                working = role_dir/'source'
                copy_source(source, working)
                changed = mutate_command(raw, early_commit=role == 'observation')
                (working/COMMAND_FILE).write_bytes(changed)
                provenance['mutations'][role] = dict(path=str(COMMAND_FILE), original_git_blob=COMMAND_BLOB, sha256=digest(changed))
                with disposable_stack(working, role_dir, provenance['commands']) as (compose, port, password):
                    base = f'http://127.0.0.1:{port}'
                    jar = http.cookiejar.CookieJar()
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
                    _, csrf = request_json(opener, base, '/api/v1/auth/csrf')
                    request_json(opener, base, '/api/v1/auth/login', {'email': 'alice@example.test', 'password': password}, {csrf['headerName']: csrf['token']})
                    _, csrf = request_json(opener, base, '/api/v1/auth/csrf')
                    cookie = '; '.join(f'{item.name}={item.value}' for item in jar)
                    for i, amount in enumerate(AMOUNTS):
                        before = snapshot(compose, working, provenance['commands'])
                        key = str(uuid.uuid4())
                        body = canonical(dict(sourceId=SOURCE, recipientRef=RECIPIENT, amountMinor=str(amount), currency='CAD'))
                        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=25)
                        try:
                            connection.request('POST', '/api/v1/transfers', body=body, headers={
                                'Content-Type': 'application/json', 'Cookie': cookie,
                                csrf['headerName']: csrf['token'], 'Idempotency-Key': key})
                            response = connection.getresponse()
                            data = response.read(65537)
                            if len(data) > 65536:
                                raise ValueError('HTTP receipt exceeds bound')
                            parsed = json.loads(data)
                            if not isinstance(parsed, dict) or parsed.get('status') != response.status:
                                raise ValueError('HTTP status and structured receipt differ')
                            receipt = dict(status=response.status, code=parsed.get('code'))
                        finally:
                            connection.close()
                        after = snapshot(compose, working, provenance['commands'])
                        command = dict(source_id=SOURCE, destination_id=DEST, amount_minor=amount, currency='CAD')
                        oracle = verify_observation(before, after, command=command, response=receipt, expected_effects=int(role == 'observation'))
                        request_id = digest(key.encode() + b'\0' + body)
                        record = observation(before, after, amount=amount, request_id=request_id,
                                             response=receipt, semantics_digest=digest(canonical(SEMANTICS)))
                        pairs[i][role] = record
                        # Fake fixture identities only; no cookies, passwords or headers.
                        provenance['oracle_receipts'].append(dict(role=role, variant=i, request_digest=request_id,
                            command=command, response=receipt, before=before, after=after, oracle=oracle))
                        reconciliation = run_command([*compose, 'exec', '-T', 'postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                            '-U', 'ledger_owner', '-d', 'ledgerguard'], working, provenance['commands'],
                            text=(working/'tests/database/reconcile.sql').read_text(), timeout=30)
                        if 'RECONCILIATION_PASS discrepancies=0' not in reconciliation:
                            raise ValueError('Accounting reconciliation failed; this is not the intended finality-only intervention')
            for record in provenance['commands']:
                record['command'] = [part.replace(str(private), '<private>') for part in record['command']]
    finally:
        if checkout_digest(source) != source_digest or subprocess.check_output(['git', 'status', '--porcelain'], cwd=source).strip():
            raise RuntimeError('Original read-only companion changed')
    inventory = write_corpus(output, pairs, provenance, executed=True)
    return {'inventory': inventory, 'provenance': provenance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledgerguard-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confirm-disposable-stack', action='store_true', required=True)
    args = parser.parse_args()
    result = run(args.ledgerguard_source, args.output)
    print(json.dumps(result['inventory'], indent=2))


if __name__ == '__main__':
    main()
