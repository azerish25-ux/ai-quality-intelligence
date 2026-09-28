"""Execute a loopback-only lost-response / key-corruption fault-proxy experiment.

Uses unmodified, pinned LedgerGuard API + PostgreSQL. A key-corrupting retry
boundary is intentionally faulty; this does NOT assert a defect in LedgerGuard.
Only synthetic fixture money is used. The complete experiment is development
regression data, not a fresh held-out or five-category benchmark.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import http.cookiejar
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fullstack_oracle import verify_pair_observation

PIN = json.loads((Path(__file__).parent / 'source.json').read_text())
SOURCE = '10000000-0000-0000-0000-000000000001'
DEST = '20000000-0000-0000-0000-000000000001'
RECIPIENT = 'LG-20000000000000000000000000000001'
IDENTITY = 'transport::response'


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


class RetryProxy(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, upstream_port: int, corrupt_retry: bool):
        super().__init__(('127.0.0.1', 0), ProxyHandler)
        self.upstream_port, self.corrupt_retry = upstream_port, corrupt_retry
        self.events: list[dict] = []
        self.errors: list[str] = []
        self.request_lock = threading.Lock()


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_):
        pass  # Never log cookies, CSRF values or complete request headers.

    def do_POST(self):
        self.connection.settimeout(25)
        if self.path != '/api/v1/transfers':
            self.send_error(404); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400); return
        if not 1 <= length <= 8192 or self.headers.get('Transfer-Encoding'):
            self.send_error(413); return
        body = self.rfile.read(length)
        key = self.headers.get('Idempotency-Key', '')
        if not key or len(body) != length:
            self.send_error(400); return
        with self.server.request_lock:
            ordinal = len(self.server.events) + 1
            if ordinal > 2:
                self.send_error(429); return
            forwarded_key = str(uuid.uuid4()) if self.server.corrupt_retry and ordinal == 2 else key
            headers = {name: value for name, value in self.headers.items()
                       if name.lower() in {'cookie','x-xsrf-token','x-csrf-token','content-type'}}
            headers['Idempotency-Key'] = forwarded_key
            upstream = http.client.HTTPConnection('127.0.0.1', self.server.upstream_port, timeout=20)
            try:
                upstream.request('POST', '/api/v1/transfers', body=body, headers=headers)
                response = upstream.getresponse()
                data = response.read(65537)
                if len(data) > 65536:
                    raise ValueError('Upstream response exceeds bound')
                receipt = json.loads(data)
                if response.status != 201 or not isinstance(receipt, dict) or not receipt.get('id'):
                    raise ValueError('The real API did not return a settled transfer receipt')
                self.server.events.append(dict(sequence=ordinal, logical_key_digest=digest(key.encode()),
                    intent_digest=digest(body), forwarded_key_digest=digest(forwarded_key.encode()),
                    upstream_status=response.status, upstream_receipt_id=receipt['id'],
                    idempotency_replayed=response.getheader('Idempotency-Replayed')))
                if ordinal == 1:
                    # Read the actual committed response, then close WITHOUT sending headers.
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Connection', 'close')
                    self.end_headers(); self.wfile.write(data)
            except Exception as exc:
                self.server.errors.append(type(exc).__name__)
                self.close_connection = True
                try:
                    self.send_error(502)
                except OSError:
                    pass
            finally:
                upstream.close()


@contextmanager
def retry_proxy(upstream_port: int, corrupt_retry: bool):
    server = RetryProxy(upstream_port, corrupt_retry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError('Fault proxy failed to stop')


def request_json(opener, base, path, body=None, headers=None):
    request = urllib.request.Request(base+path, data=encoded(body) if body is not None else None,
                                    headers={'Content-Type':'application/json', **(headers or {})})
    with opener.open(request, timeout=20) as response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('HTTP response exceeds bound')
        return response.status, json.loads(raw)


def run_command(command: list[str], cwd: Path, records: list, *, text=None, timeout=600) -> str:
    started=time.monotonic()
    result=subprocess.run(command,cwd=cwd,input=text,text=True,capture_output=True,timeout=timeout)
    records.append({'command': command, 'exit_code': result.returncode, 'seconds':time.monotonic()-started})
    if result.returncode:
        # Compose/JVM output may contain private configuration. Do not export it.
        raise RuntimeError(f'Command failed with exit {result.returncode}: {command[0:3]}')
    return result.stdout


def checkout_digest(source: Path) -> str:
    files=subprocess.check_output(['git','ls-files','-z'],cwd=source).split(b'\0')
    h=hashlib.sha256()
    for name in sorted(n for n in files if n):
        path=source/os.fsdecode(name)
        if path.is_symlink():
            raise ValueError('Pinned source unexpectedly contains a symlink')
        h.update(name+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def snapshot(compose, source: Path, records: list) -> dict:
    # A single repeatable-read SELECT sees balances, transfer IDs and their
    # independent double-entry rows at one committed snapshot.
    sql=f"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH effects AS (
 SELECT id,source_id,destination_id,amount_minor,currency,journal_id FROM ledger.transfers
 WHERE source_id='{SOURCE}' AND destination_id='{DEST}'
), balances AS (
 SELECT account_id,posted_minor FROM ledger.account_balances WHERE account_id IN ('{SOURCE}','{DEST}')
), entries AS (
 SELECT journal_id,account_id,side,amount_minor FROM ledger.journal_entries
 WHERE journal_id IN (SELECT journal_id FROM effects)
)
SELECT jsonb_build_object(
 'balances',coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY account_id) FROM balances b),'[]'::jsonb),
 'effects',coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM effects t),'[]'::jsonb),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY journal_id,side) FROM entries e),'[]'::jsonb));
COMMIT;
"""
    output=run_command([*compose,'exec','-T','postgres','psql','-XAtq','-v','ON_ERROR_STOP=1',
                        '-U','ledger_owner','-d','ledgerguard'],source,records,text=sql,timeout=30)
    return json.loads(output)


def build_bundle(value: dict, events: list[dict]) -> bytes:
    # Both roles really experienced a failed transport observation; the healthy
    # control PASSES the independent single-effect contract, not the transport test.
    files={'report.xml': b'<testsuite name="http-observation" tests="1" failures="1"><testcase classname="transport" name="response"><failure message="Transport stream ended before a usable response" type="ResponseUnavailable"/></testcase></testsuite>',
           'measurements.json':encoded(value),
           'events.jsonl':b''.join(encoded({'event':'upstream_response_received',
               'sequence':e['sequence'],'status':e['upstream_status'], 'receipt_id':e['upstream_receipt_id']}) for e in events)}
    entries=[dict(id='report',path='report.xml',kind='junit-xml',required=True,role='primary'),
             dict(id='measurements',path='measurements.json',kind='transaction-observations-json',required=True,correlates_to=['report']),
             dict(id='events',path='events.jsonl',kind='console-jsonl',required=True)]
    for entry in entries:
        entry['sha256']=digest(files[entry['path']])
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
        for name, data in {'manifest.json':encoded({'schema_version':'2.0','inputs':entries}),**files}.items():
            archive.writestr(zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0)),data)
    return stream.getvalue()


def run(source: Path, output: Path) -> dict:
    source,output=source.resolve(),output.resolve()
    if source==output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Output and read-only companion checkout must be disjoint')
    if output.exists():
        raise ValueError('Refusing to overwrite an execution directory')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if revision!=PIN['revision'] or subprocess.check_output(['git','status','--porcelain'],cwd=source).strip():
        raise ValueError('Companion checkout is not the clean pinned revision')
    before_digest=checkout_digest(source)
    output.mkdir(parents=True)
    records,labels,cases=[],[],[]
    source_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT).strip())
    with tempfile.TemporaryDirectory(prefix='failurelens-m62-private-') as private_dir:
        private=Path(private_dir); os.chmod(private,0o700)
        port=18080
        # A random project gets its own database/network/volumes. Never connect to
        # or delete an existing developer stack, and never reuse its credentials.
        project='failurelens-m62-'+secrets.token_hex(6)
        values={'COMPOSE_PROJECT_NAME':project,'POSTGRES_DB':'ledgerguard','LEDGER_HTTP_PORT':str(port),
                'LEDGER_AUTH_KEY':base64.b64encode(secrets.token_bytes(64)).decode(),
                'RABBITMQ_DEFAULT_USER':'ledgerguard','RABBITMQ_DEFAULT_VHOST':'/ledgerguard'}
        for name in ('POSTGRES_SUPERUSER_PASSWORD','LEDGER_OWNER_PASSWORD','LEDGER_RUNTIME_PASSWORD',
                     'RABBITMQ_DEFAULT_PASS','LEDGER_DEMO_PASSWORD'):
            values[name]=secrets.token_hex(32)
        env=private/'runtime.env'; env.write_text(''.join(f'{key}={value}\n' for key,value in values.items()));env.chmod(0o600)
        compose=['docker','compose','--project-name',project,'--env-file',str(env),'-f',str(source/'compose.yaml')]
        try:
            run_command([*compose,'up','-d','--build','--wait','postgres','api'],source,records,timeout=900)
            run_command([*compose,'run','--rm','seed'],source,records,timeout=120)
            base=f'http://127.0.0.1:{port}'
            jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            _,csrf=request_json(opener,base,'/api/v1/auth/csrf')
            request_json(opener,base,'/api/v1/auth/login',{'email':'alice@example.test','password':values['LEDGER_DEMO_PASSWORD']},
                         {csrf['headerName']:csrf['token']})
            _,csrf=request_json(opener,base,'/api/v1/auth/csrf')
            cookie='; '.join(f'{item.name}={item.value}' for item in jar)
            for index,amount in enumerate((7,11,13,17)):
                case_id='c-'+digest(f'fullstack-retry-v1-{index}'.encode())[:20]
                refs=[]; pair=[]
                for role in ('control','observation'):
                    fault=role=='observation'; before=snapshot(compose,source,records)
                    key=str(uuid.uuid4()); body=encoded({'sourceId':SOURCE,'recipientRef':RECIPIENT,'amountMinor':str(amount),'currency':'CAD'})
                    requests=[]
                    with retry_proxy(port,fault) as proxy:
                        for sequence in (1,2):
                            connection=http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=25)
                            try:
                                connection.request('POST','/api/v1/transfers',body=body,
                                    headers={'Content-Type':'application/json','Cookie':cookie,csrf['headerName']:csrf['token'],'Idempotency-Key':key})
                                response=connection.getresponse();raw=response.read(65537)
                                if sequence==1 or response.status!=201 or len(raw)>65536:
                                    raise RuntimeError('Unexpected retry transport outcome')
                                receipt=json.loads(raw); status=response.status; receipt_id=receipt['id']
                            except http.client.RemoteDisconnected:
                                if sequence!=1:
                                    raise
                                status,receipt_id=None,None
                            finally:
                                connection.close()
                            requests.append(dict(sequence=sequence,logical_key_digest=digest(key.encode()),intent_digest=digest(body),
                                                 response_status=status,receipt_id=receipt_id))
                        if proxy.errors or len(proxy.events)!=2:
                            raise RuntimeError('The fault proxy failed to execute both real upstream requests')
                        wire=list(proxy.events)
                    after=snapshot(compose,source,records)
                    value=dict(schema_version='transaction-observations-v1',test_identity=IDENTITY,attempt=0,browser=None,
                        command=dict(source_id=SOURCE,destination_id=DEST,amount_minor=amount,currency='CAD'),
                        requests=requests,before=before,after=after)
                    oracle=verify_pair_observation(value,wire,expected_effects=2 if fault else 1)
                    reconciliation=run_command([*compose,'exec','-T','postgres','psql','-X','-v','ON_ERROR_STOP=1',
                        '-U','ledger_owner','-d','ledgerguard'],source,records,text=(source/'tests/database/reconcile.sql').read_text(),timeout=30)
                    if 'RECONCILIATION_PASS discrepancies=0' not in reconciliation:
                        raise RuntimeError('Global accounting reconciliation did not pass')
                    content=build_bundle(value,wire)
                    # Opaque filenames avoid leaking the control/fault name to the parser.
                    filename=digest((case_id+role).encode())[:12]+'.zip'
                    path=output/'inputs'/case_id/filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
                    refs.append(dict(role=role,path=str(path.relative_to(output/'inputs')),sha256=digest(content),bytes=len(content),
                                     source_format='failurelens-bundle-v2',expected_inputs=3))
                    pair.append(dict(role=role,expected_category='product_defect' if fault else 'insufficient_evidence',
                        oracle=oracle,wire_requests=wire,global_reconciliation='PASS',
                        intervention='retry-boundary replaces forwarded key' if fault else 'stable forwarded key',
                        input_digest=digest(content)))
                cases.append(dict(case_id=case_id,repository='azerish25-ux/transaction-reliability-lab',source_revision=revision,inputs=refs))
                labels.append(dict(case_id=case_id,scenario_family_id='lost-response-retry-key-corruption',source_kind='ledgerguard_executed',
                                   execution_scope='http_postgresql_fault_proxy',split='development',label_review_status='agent-reviewed',roles=pair))
        finally:
            run_command([*compose,'down','--volumes','--remove-orphans'],source,records,timeout=120)
            if checkout_digest(source)!=before_digest:
                raise RuntimeError('Read-only companion source changed')
    (output/'inputs/manifest.json').write_bytes(encoded(dict(schema_version='artifact-replay-v2',cases=cases)))
    (output/'ground-truth.json').write_bytes(encoded(labels))
    provenance=dict(schema_version='ledgerguard-fullstack-v1',source_revision=source_sha,source_dirty=dirty,
        ledgerguard_revision=revision,companion_tree_sha256=before_digest,commands=records,
        implementation_sha256={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in
                               (Path(__file__),Path(__file__).with_name('fullstack_oracle.py'))},
        scope='Unmodified LedgerGuard HTTP API and PostgreSQL; deliberate retry-boundary fault proxy; no UI or async-worker coverage',
        family_count=1,paired_scenarios=4,case_count=8,
        limitations=['Development-only, agent-authored scenarios; four amounts are one mechanism, not four independent families.',
                     'The faulty retry boundary is outside LedgerGuard. Different forwarded keys are correctly treated as different requests by the unmodified service.',
                     'A passing global balance reconciliation does not prove one economic effect per logical request.',
                     'The control passes the economic oracle but retains a real failed transport observation; cautious abstention is expected.'])
    (output/'provenance.json').write_bytes(encoded(provenance))
    return provenance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledgerguard-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--confirm-disposable-stack',action='store_true',required=True)
    args=parser.parse_args()
    result=run(args.ledgerguard_source,args.output)
    print(json.dumps({key:result[key] for key in ('source_revision','ledgerguard_revision','family_count','paired_scenarios','case_count')}))


if __name__=='__main__':
    main()
