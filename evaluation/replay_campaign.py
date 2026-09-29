"""Replay an answer-free campaign through API, durable jobs and publication validation.

Synthetic history is rehydrated with fixture clocks in an EMPTY disposable DB.
No production backdating endpoint is added. The scorer and labels run separately.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import resource
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'backend/src'))
from evaluation.campaign_contract import canonical, digest, load_public, read_input, timestamp
from evaluation.replay import install_label_read_guard

SUBSTANTIVE = ('category','severity','confidence','summary','claims','policy_flags','abstention_reason','supporting_evidence_ids','contradictory_evidence_ids')


def source_state() -> dict:
    def git(*args):
        result = subprocess.run(['git','-C',str(ROOT),*args], text=True, capture_output=True, check=True)
        return result.stdout.strip()
    changes = git('status','--porcelain','--untracked-files=normal','--',
                  'backend/src','evaluation','frontend','.github','integrations').splitlines()
    return dict(source_revision=git('rev-parse','HEAD'), source_tree=git('rev-parse','HEAD^{tree}'),
                source_worktree_dirty=bool(changes), source_worktree_changes=changes)


def install_runtime_guards(inputs: Path) -> dict:
    install_label_read_guard(inputs)
    denied = {'network_attempts': 0, 'subprocess_attempts': 0}
    def network(*args, **kwargs):
        denied['network_attempts'] += 1
        raise PermissionError('External network is disabled during controlled replay')
    def process(*args, **kwargs):
        denied['subprocess_attempts'] += 1
        raise PermissionError('Subprocess execution is disabled during controlled replay')
    socket.socket.connect = network
    socket.create_connection = network
    socket.getaddrinfo = network
    subprocess.Popen = process
    def no_generator(event, args):
        if event == 'open' and isinstance(args[0], (str,bytes,os.PathLike)):
            p = Path(os.fsdecode(args[0]))
            if (p.name.startswith(('scenario_catalog.', 'generate_campaign.'))
                    or p.resolve().is_relative_to(ROOT/'integrations'/'ledgerguard')):
                raise PermissionError('Inference cannot read scenario generators')
    sys.addaudithook(no_generator)
    return denied


@contextmanager
def fixture_clock(models, observed_at):
    from sqlalchemy import event
    stamp = timestamp(observed_at)
    def apply(mapper, connection, target):
        target.created_at = stamp
        if hasattr(target, 'started_at'):
            target.started_at = stamp
            target.ended_at = stamp + timedelta(seconds=1)
    for model in models:
        event.listen(model, 'before_insert', apply)
    try:
        yield
    finally:
        for model in models:
            event.remove(model, 'before_insert', apply)


def replay(inputs: Path, output: Path, repeats: int = 5) -> dict:
    if repeats != 5:
        raise ValueError('The frozen campaign requires exactly five repetitions')
    inputs, output = inputs.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(inputs.parent):
        raise ValueError('Predictions need a new directory outside the corpus')
    manifest = load_public(inputs)
    source = source_state()
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from failurelens import models as m
    from failurelens.api import app
    from failurelens.config import get_settings
    from failurelens.db import SessionLocal, initialize_database, engine
    from failurelens.jobs import process_next
    from failurelens.analysis import analyze_failure
    from failurelens.evidence_validation import validate_evidence_records, validated_evidence_views
    from failurelens.history import history_context_for_failure
    from failurelens.service import select_failure_evidence
    from failurelens.github_report import render_markdown

    settings = get_settings()
    if not settings.demo_mode:
        raise ValueError('Synthetic fixture replay is restricted to explicit demo mode')
    initialize_database()
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(m.Project)):
            raise ValueError('Existing projects must never be overwritten; use an empty disposable database')
    guards = install_runtime_guards(inputs)
    output.mkdir(parents=True)
    predictions = []
    start = time.perf_counter()
    with TestClient(app) as client:
        def request(method, url, status=200, **kwargs):
            response = client.request(method, url, **kwargs)
            if response.status_code != status:
                raise RuntimeError(f'{method} {url}: expected {status}, got {response.status_code}: {response.text[:500]}')
            return response
        for case in manifest.cases:
            started = time.perf_counter()
            project = request('POST','/api/v1/projects',201,json={'slug':'campaign-'+case.case_id,'name':'Controlled campaign replay'}).json()
            ingestion_records, history_records = [], []
            def ingest(ref, external, observed_at):
                content = read_input(inputs, ref)
                params = dict(external_id=external,filename='bundle.zip' if ref.source_format=='failurelens-bundle-v2' else 'report.xml',
                    repository=case.repository,branch='evaluation',run_scope='full_suite',environment='controlled-campaign',
                    timezone='UTC',worker_count=1,shard_count=1,expected_inputs=ref.expected_inputs,source_format=ref.source_format)
                if re.fullmatch(r'[0-9a-f]{40}',case.source_revision):
                    params['commit_sha']=case.source_revision
                headers={'content-type':'application/zip' if ref.source_format=='failurelens-bundle-v2' else 'application/xml'}
                url=f"/api/v1/projects/{project['id']}/ingestions"
                queued=request('POST',url,202,params=params,content=content,headers=headers).json()
                # Clock injection is confined to this offline fixture loader.
                # It happens BEFORE the automatic first analysis, so future
                # seeded records cannot enter even the initial decision.
                with fixture_clock([m.Run,m.Analysis],observed_at), SessionLocal() as worker:
                    if not process_next(worker,'campaign-replay',settings=settings):
                        raise RuntimeError('Durable job was not claimed')
                state=request('GET','/api/v1/ingestions/'+queued['id']).json()
                if state['state']!='succeeded':
                    raise RuntimeError('Campaign ingestion did not succeed: '+state['state'])
                duplicate=request('POST',url,202,params=params,content=content,headers=headers).json()
                if duplicate['id']!=queued['id']:
                    raise RuntimeError('Identical input was not idempotent')
                failures=request('GET',f"/api/v1/runs/{state['run_id']}/failures").json()
                ingestion_records.append(dict(path=ref.path,sha256=ref.sha256,run_id=state['run_id'],
                    observed_at=observed_at,state=state['state'],failure_count=len(failures),idempotent=True))
                return state['run_id'],failures
            for index,event in enumerate(case.history):
                run_id, failures=ingest(event.artifact,case.case_id+f'-history-{index}',event.observed_at)
                record=dict(run_id=run_id,path=event.artifact.path,sha256=event.artifact.sha256,observed_at=event.observed_at,review=None)
                if event.review:
                    if len(failures)!=1:
                        raise RuntimeError('A prior review needs exactly one observed failure')
                    with fixture_clock([m.ReviewEvent],event.review.recorded_at):
                        review=request('POST',f"/api/v1/analyses/{failures[0]['latest_analysis']['analysis_id']}/reviews",201,
                            json=dict(decision='category_correction',proposed_category='known_flake',reason=event.review.reason,expected_version=0)).json()
                    record['review']=dict(id=review['id'],recorded_at=event.review.recorded_at,provenance=event.review.provenance)
                history_records.append(record)
            if case.control:
                _,control_failures=ingest(case.control,case.case_id+'-control',case.observed_at)
                if control_failures:
                    raise RuntimeError('Retained executed control no longer passes parsing')
            run_id,failures=ingest(case.observation,case.case_id+'-current',case.observed_at)
            if len(failures)!=1:
                raise RuntimeError('Campaign requires one failure per observation')
            failure=failures[0]
            published=request('GET','/api/v1/analyses/'+failure['latest_analysis']['analysis_id']).json()
            substantive={k:published[k] for k in SUBSTANTIVE}
            repeat_digests=[digest(canonical(substantive))]
            for _ in range(repeats-1):
                with fixture_clock([m.Analysis],case.observed_at):
                    again=request('POST',f"/api/v1/failures/{failure['id']}/analyses",201).json()
                if {k:again[k] for k in SUBSTANTIVE}!=substantive:
                    raise RuntimeError('Substantive deterministic output changed')
                repeat_digests.append(digest(canonical({k:again[k] for k in SUBSTANTIVE})))
            exported=[]
            with SessionLocal() as session:
                row=session.get(m.Failure,failure['id'])
                rows=select_failure_evidence(session,row)
                checks=validate_evidence_records(row,rows,settings=settings)
                views=validated_evidence_views(rows,checks)
                history=history_context_for_failure(session,row)
                details={**row.execution.details,'retry_recovered':row.execution.retry_recovered,'incomplete_run':row.run.completeness!='complete'}
                modes={'constant_product_baseline':'product_defect','full_deterministic':published['category']}
                for mode,context in [('rules_only',{}),('rules_with_history',history)]:
                    decision=analyze_failure(message=row.message,exception_type=row.exception_type,details=details,evidence=views,historical=context)
                    modes[mode]=decision.category.value
                for item in rows:
                    if item.id not in checks.accepted_ids:
                        continue
                    safe=request('GET','/api/v1/evidence/'+item.id).json()
                    data=request('GET','/api/v1/artifact-derivatives/'+item.derivative_id+'/content').content
                    if digest(data)!=item.content_digest:
                        raise RuntimeError('Authorized derivative digest differs')
                    name='safe-evidence/'+case.case_id+'/'+item.id+'.json'
                    path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    exported.append(dict(id=item.id,path=name,sha256=item.content_digest,excerpt=safe['excerpt'],
                                         locator=safe['locator'],execution_id=item.execution_id,run_id=item.run_id,
                                         source_input_sha256=session.get(m.RunInput,item.run_input_id).digest))
                report=render_markdown(row.run,[session.get(m.Analysis,published['analysis_id'])])
                report_name='reports/'+case.case_id+'.md'
                path=output/report_name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(report)
                validation=checks.as_dict()
            predictions.append(dict(case_id=case.case_id,run_id=run_id,execution_id=failure['execution_id'] if 'execution_id' in failure else published['provenance']['evidence_scope']['execution_id'],
                analysis=published,modes=modes,repeat_digests=repeat_digests,history=history,seeded_history=history_records,
                inputs=ingestion_records,evidence=exported,evidence_validation=validation,report=report_name,
                advisory_hold='HOLD_FOR_REVIEW' in report,seconds=time.perf_counter()-started))
    value=dict(schema_version='campaign-replay-v1',**source,database_dialect=engine.dialect.name,
        input_manifest_sha256=digest((inputs/'manifest.json').read_bytes()),case_count=len(predictions),repeats=repeats,cases=predictions,
        wall_seconds=time.perf_counter()-start,peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        runtime_guards=guards,clock_scope='Synthetic fixture chronology, not real historical production observations',
        isolation_scope='Process-local file-open tripwire and network/subprocess denial; not an OS sandbox',
        external_model_requests=0,compute_cost=None)
    (output/'predictions.json').write_bytes(canonical(value))
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm-disposable-database',action='store_true',required=True)
    args=p.parse_args();result=replay(args.inputs,args.output)
    print(json.dumps({k:result[k] for k in ['source_revision','source_worktree_dirty','case_count','database_dialect','wall_seconds','runtime_guards']},indent=2))

if __name__=='__main__':main()
