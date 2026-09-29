"""Independently score frozen, mixed-source published decisions after replay exits.

This controlled rubric is not a universal semantic judge or deployment study.
Quality targets remain separate from integrity and mandatory safety gates.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import io
import json
import re
from pathlib import Path
import sys
import zipfile
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.campaign_contract import CATEGORIES, audit, bounded_read, canonical, digest, read_input, timestamp
from evaluation.executed_harness import classification_metrics, family_recall_interval, fraction

FIELDS=('category','severity','confidence','summary','claims','policy_flags','abstention_reason','supporting_evidence_ids','contradictory_evidence_ids')
WORDS={'product_defect':'probable product defect','test_defect':'probable test defect',
       'infrastructure_failure':'probable infrastructure or environment failure','known_flake':'known flaky behavior'}
CONTRACT_TEXT={
    'operation_isolation':'Reported identical actor and payload inputs have different operations but equal fingerprints; this violates the declared operation-isolation contract without establishing the responsible implementation.',
    'projection_ordering':'Reported projection snapshots show a lower-version event replacing newer state despite an ignore-stale policy; this supports a product-defect investigation without establishing the responsible implementation.',
    'weekly_recurrence':'Reported local schedule dates do not preserve a seven-calendar-day weekly recurrence in the declared timezone; this supports a product-defect investigation without establishing the responsible implementation.',
}

# Independently maintained evaluator wording/categories: do not import runtime
# predicates, enums, schemas or claim strings into this scorer.
CONTRACT_TEXT.update({
    'transaction_finality':'Reported committed database observations contain financial effects for an isolated request whose matching versioned response contract declares terminal rejection with no effects; this supports a commit-consistency investigation without establishing the responsible component or general rollback behavior.',
    'atomic_transfer':'Reported isolated two-account snapshots do not match the declared all-or-nothing transfer outcome; this supports a product-defect investigation without establishing the responsible component.',
    'tenant_isolation':'Reported resource content belongs to a different tenant from the authenticated member despite a same-tenant access policy; this supports an access-isolation investigation without establishing the responsible component.',
    'status_expectation':'Reported failing status assertion expects a status excluded by the matching versioned API contract, while the observed response status is permitted; this supports a test-expectation investigation and does not establish that other product behavior is correct.',
    'runner_memory_limit':'Reported runner-scoped memory measurements and an increased OOM-kill counter corroborate termination of the same test-runner process; this supports an infrastructure-interruption investigation without establishing the trigger or clearing product behavior.',
})
CONTRACT_CATEGORY = {k:'product_defect' for k in CONTRACT_TEXT} | {
    'status_expectation':'test_defect', 'runner_memory_limit':'infrastructure_failure',
}


def independent_diagnostic(m: dict) -> bool:
    """Fail-closed relational rubric over reported observations, not verdict tags."""
    def integer(v, lo=0, hi=2**53-1):
        return type(v) is int and lo <= v <= hi
    def sha(v):
        return isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) is not None
    kind=m.get('kind')
    if kind=='transaction_finality':
        fields = {
            'kind','finality_policy','observation_scope','snapshot_basis','request_digest','receipt_request_digest',
            'source_account_digest','destination_account_digest','currency','amount_minor','contract_digest',
            'served_contract_digest','response_basis','rejection_status','rejection_code','response_status','response_code',
            'concurrent_writers','before_source_minor','before_destination_minor','after_source_minor','after_destination_minor',
            'new_transfer_count','new_journal_entry_count','new_debit_minor','new_credit_minor',
        }
        ids = ['request_digest','receipt_request_digest','source_account_digest','destination_account_digest',
               'contract_digest','served_contract_digest']
        balances = [m.get(k) for k in ['before_source_minor','before_destination_minor','after_source_minor','after_destination_minor']]
        if not (set(m)==fields and all(sha(m.get(k)) for k in ids)
                and m.get('finality_policy')=='terminal_rejection_has_no_effects'
                and m.get('observation_scope')=='isolated_logical_request'
                and m.get('snapshot_basis')=='committed_primary_database'
                and m['request_digest']==m['receipt_request_digest']
                and m['source_account_digest']!=m['destination_account_digest']
                and m['contract_digest']==m['served_contract_digest']
                and m.get('response_basis')=='terminal_business_rejection'
                and integer(m.get('rejection_status'),400,499) and integer(m.get('response_status'),400,499)
                and m['rejection_status']==m['response_status']
                and isinstance(m.get('rejection_code'),str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',m['rejection_code'])
                and m.get('response_code')==m['rejection_code']
                and integer(m.get('concurrent_writers'),0,0) and integer(m.get('amount_minor'),1,10**12)
                and isinstance(m.get('currency'),str) and re.fullmatch(r'[A-Z]{3}',m['currency'])
                and all(integer(v,-(2**53-1)) for v in balances)
                and integer(m.get('new_transfer_count'),0,256) and integer(m.get('new_journal_entry_count'),0,512)
                and integer(m.get('new_debit_minor')) and integer(m.get('new_credit_minor'))):
            return False
        delta_source = balances[2]-balances[0]
        delta_destination = balances[3]-balances[1]
        return (delta_source != 0 or delta_destination != 0 or m['new_transfer_count'] > 0
                or m['new_journal_entry_count'] > 0 or m['new_debit_minor'] > 0 or m['new_credit_minor'] > 0)
    if kind=='atomic_transfer':
        ids=['request_digest','receipt_request_digest','source_account_digest','destination_account_digest']
        vals=[m.get(k) for k in ['before_source_minor','before_destination_minor','after_source_minor','after_destination_minor']]
        if not (all(sha(m.get(k)) for k in ids) and all(integer(v,-(2**53-1)) for v in vals)
                and m.get('atomicity_policy')=='both_effects_or_neither' and m.get('observation_scope')=='isolated_logical_request'
                and m['request_digest']==m['receipt_request_digest'] and m['source_account_digest']!=m['destination_account_digest']
                and integer(m.get('concurrent_writers'),0,0) and integer(m.get('amount_minor'),1,10**12)
                and isinstance(m.get('currency'),str) and re.fullmatch(r'[A-Z]{3}',m['currency'])
                and m.get('receipt_outcome') in {'committed','rolled_back'}):return False
        debit=vals[0]-vals[2];credit=vals[3]-vals[1]
        expected=m['amount_minor'] if m['receipt_outcome']=='committed' else 0
        return (debit,credit)!=(expected,expected)
    if kind=='tenant_isolation':
        keys=['actor_tenant_digest','resource_tenant_digest','requested_resource_digest','returned_resource_digest']
        return (all(sha(m.get(k)) for k in keys) and m.get('access_policy')=='same_tenant_resource_access'
                and m.get('principal_scope')=='tenant_member' and integer(m.get('response_status'),100,599)
                and m['actor_tenant_digest']!=m['resource_tenant_digest']
                and m['requested_resource_digest']==m['returned_resource_digest'])
    if kind=='status_expectation':
        allowed=m.get('allowed_statuses')
        return (m.get('assertion_scope')=='response_status_equality' and m.get('contract_source')=='versioned_api_contract'
                and sha(m.get('contract_digest')) and m['contract_digest']==m.get('served_contract_digest')
                and isinstance(allowed,list) and 1<=len(allowed)<=8 and all(integer(v,100,599) for v in allowed)
                and len(set(allowed))==len(allowed) and integer(m.get('observed_status'),100,599)
                and integer(m.get('asserted_status'),100,599) and m['observed_status'] in allowed and m['asserted_status'] not in allowed)
    if kind=='runner_memory_limit':
        return (m.get('process_role')=='test_runner' and m.get('counter_scope')=='isolated_runner_cgroup'
                and sha(m.get('runner_process_digest')) and m['runner_process_digest']==m.get('killed_process_digest')
                and integer(m.get('memory_limit_bytes'),1) and integer(m.get('peak_memory_bytes'))
                and m['peak_memory_bytes']>=m['memory_limit_bytes'] and integer(m.get('oom_kills_before'),0,1000000)
                and integer(m.get('oom_kills_after'),0,1000000) and m['oom_kills_after']>m['oom_kills_before']
                and integer(m.get('termination_signal'),9,9))
    return False


def independent_contract(value: dict) -> str | None:
    """Independent arithmetic/calendar rubric; never call the production inspector."""
    m=value['measurement'];kind=m['kind']
    if kind in {'transaction_finality','atomic_transfer','tenant_isolation','status_expectation','runner_memory_limit'}:
        return kind if independent_diagnostic(m) else None
    if kind=='operation_isolation':
        a,b=m['first'],m['second']
        valid=(m.get('fingerprint_scope')=='operation_actor_payload' and a['operation']!=b['operation'] and a['actor_digest']==b['actor_digest']
               and a['payload_digest']==b['payload_digest'] and a['fingerprint'] is not None and a['fingerprint']==b['fingerprint'])
    elif kind=='projection_ordering':
        a,b,c=m['before'],m['incoming'],m['after']
        valid=(a is not None and c is not None and m['stale_event_policy']=='ignore'
               and a['entity_digest']==b['entity_digest']==c['entity_digest']
               and all(type(v['version']) is int for v in (a,b,c)) and b['version']<a['version'] and c==b)
    elif kind=='weekly_recurrence':
        if m['next_local'] is None:return None
        a,b=datetime.fromisoformat(m['previous_local']),datetime.fromisoformat(m['next_local'])
        zone=ZoneInfo(m['timezone']);expected=a+timedelta(days=7)
        for value in (a,b,expected):
            offsets={v.utcoffset() for v in [value.replace(tzinfo=zone,fold=fold) for fold in (0,1)]
                     if datetime.fromtimestamp(v.timestamp(),zone).replace(tzinfo=None)==value}
            if len(offsets)!=1:return None
        valid=(b.date()-a.date()).days!=7 or b.time()!=a.time()
    else:return None
    return kind if valid else None


def safe_file(root: Path, name: str, bound=1024*1024) -> bytes:
    path=root/name
    if not path.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in [path,*path.parents] if p.is_relative_to(root)):
        raise ValueError('Saved evidence escapes replay directory')
    return bounded_read(path,bound)


def stable_result(analysis: dict) -> dict:
    # IDs and byte offsets are not semantic results. This is explicitly a
    # nuisance comparison, distinct from exact same-input repetition hashes.
    return dict(category=analysis['category'],severity=analysis['severity'],summary=analysis['summary'],
                confidence=analysis['confidence'],claims=[{k:c.get(k) for k in ['kind','text','predicate']} for c in analysis['claims']])


def evaluate(corpus: Path, replay_dir: Path, *, enforce_minimums: bool = True, score_split: str = 'test') -> tuple[dict,list[dict]]:
    if score_split not in {'development','calibration','test'}:
        raise ValueError('Unknown scoring split')
    inventory,labels,public=audit(corpus, enforce_minimums=enforce_minimums)
    replay=json.loads(bounded_read(replay_dir/'predictions.json',64*1024*1024))
    if replay.get('schema_version')!='campaign-replay-v1' or replay.get('input_manifest_sha256')!=inventory['public_manifest_sha256']:
        raise ValueError('Replay does not match the frozen public campaign')
    if replay.get('repeats')!=5 or replay.get('case_count')!=len(labels):
        raise ValueError('Campaign repetitions/count differ')
    if (not isinstance(replay.get('source_revision'), str) or len(replay['source_revision']) != 40
            or not isinstance(replay.get('source_tree'), str) or len(replay['source_tree']) != 40):
        raise ValueError('Replay lacks exact source provenance')
    predictions={r['case_id']:r for r in replay['cases']}
    if len(predictions)!=len(replay['cases']) or set(predictions)!={l.case_id for l in labels}:
        raise ValueError('Duplicate, absent or unexpected predictions')
    inputs={c.case_id:c for c in public.cases}
    policy=json.loads((corpus/'policy.json').read_bytes())
    for key,value in dict(product_recall_minimum=0.90,macro_f1_minimum=0.80,coverage_minimum=0.75,
                          dangerous_dismissal_maximum=0.05,high_critical_dismissals_maximum=0,
                          published_citation_validity_minimum=1.0,critical_unsupported_reassurance_maximum=0,
                          sensitive_canary_leaks_maximum=0,repetitions=5).items():
        if policy.get(key)!=value:raise ValueError('Acceptance policy was changed: '+key)
    rows=[];citations=Counter();claims=Counter();history_checks=0;canaries=0;forbidden=0
    nuisance=defaultdict(list)
    for label in labels:
        p=predictions[label.case_id];case=inputs[label.case_id];a=p['analysis'];category=a['category']
        scope=a['provenance']['evidence_scope']
        if a['run_id']!=p['run_id'] or scope['run_id']!=p['run_id'] or scope['execution_id']!=p['execution_id']:
            raise ValueError('Published analysis scope differs from current execution')
        if category not in CATEGORIES or set(p['modes'])!={'constant_product_baseline','rules_only','rules_with_history','full_deterministic'}:
            raise ValueError('Incomplete or invalid classifier comparison')
        if any(v not in CATEGORIES for v in p['modes'].values()) or p['modes']['full_deterministic']!=category:
            raise ValueError('Published/comparison category mismatch')
        expected_hash=digest(canonical({k:a[k] for k in FIELDS}))
        if p['repeat_digests']!=[expected_hash]*5:
            raise ValueError('Repeated substantive records were altered')
        nuisance[(label.family_group,label.source_kind,label.claim_rubric)].append(stable_result(a))
        supplied=[case.observation]+([case.control] if case.control else [])+[h.artifact for h in case.history]
        receipts={r['path']:r for r in p['inputs']}
        if len(receipts)!=len(p['inputs']) or set(receipts)!={r.path for r in supplied}:
            raise ValueError('Missing or duplicate input receipts')
        for ref in supplied:
            receipt=receipts[ref.path]
            if receipt['sha256']!=ref.sha256 or receipt['state']!='succeeded' or receipt['idempotent'] is not True:
                raise ValueError('Input receipt digest/state/idempotency differs')
        if receipts[case.observation.path]['failure_count']!=1 or receipts[case.observation.path]['run_id']!=p['run_id']:
            raise ValueError('Wrong current failure/run binding')
        if case.control and receipts[case.control.path]['failure_count']!=0:
            raise ValueError('Retained control failed')
        if timestamp(p['history']['history_cutoff'])!=timestamp(case.observed_at):
            raise ValueError('Replay used a different temporal cutoff')
        if len(p['seeded_history'])!=len(case.history):
            raise ValueError('Missing chronological context receipts')
        if case.history:
            prior=[h for h in case.history if timestamp(h.observed_at)<timestamp(case.observed_at)]
            expected_reviews=[]
            seeded={h['path']:h for h in p['seeded_history']}
            if len(seeded)!=len(case.history):raise ValueError('Duplicate history receipt')
            for h in case.history:
                record=seeded[h.artifact.path]
                if record['sha256']!=h.artifact.sha256 or timestamp(record['observed_at'])!=timestamp(h.observed_at):
                    raise ValueError('History receipt differs from frozen input')
                if h.review:
                    if not record['review'] or record['review']['recorded_at']!=h.review.recorded_at:
                        raise ValueError('Prior review provenance differs')
                    if timestamp(h.review.recorded_at)<timestamp(case.observed_at):expected_reviews.append(record['review']['id'])
            if p['history']['independent_runs']!=len(prior) or set(p['history']['review_event_ids'])!=set(expected_reviews):
                raise ValueError('Future or unscoped history entered inference')
            if label.expected_category=='known_flake' and p['history']['history_eligible_for_reassurance'] is not True:
                raise ValueError('Known-flake fixture lacks qualifying persisted history')
            history_checks+=1
        exported={e['id']:e for e in p['evidence']}
        if len(exported)!=len(p['evidence']):raise ValueError('Duplicated exported evidence')
        evidence_payloads={}
        source = read_input(corpus/'inputs', case.observation)
        if case.observation.source_format == 'junit-xml':
            producer_digests = {digest(source)}
        else:
            with zipfile.ZipFile(io.BytesIO(source)) as bundle:
                producer_digests = {digest(bundle.read(name)) for name in bundle.namelist() if name != 'manifest.json'}
        for ident,item in exported.items():
            data=safe_file(replay_dir,item['path'])
            payload=json.loads(data)
            if digest(data)!=item['sha256'] or payload['excerpt']!=item['excerpt']:
                raise ValueError('Saved derivative or quotation changed')
            if item['run_id']!=p['run_id'] or item['execution_id']!=p['execution_id']:
                raise ValueError('Evidence belongs to another execution')
            if item.get('source_input_sha256') not in producer_digests:
                raise ValueError('Derivative source is not a current producer artifact')
            evidence_payloads[ident]=payload
            canaries+=int(b'synthetic-campaign-canary-41729' in data)
        used=set(a['supporting_evidence_ids']+a['contradictory_evidence_ids'])
        used.update(i for claim in a['claims'] for i in claim.get('evidence_ids',[]))
        if not used.issubset(exported):raise ValueError('Published reference lacks a saved derivative')
        checks={v['evidence_id']:v for v in p['evidence_validation']['evidence']}
        for ident in used:
            c=checks.get(ident,{})
            citations['total']+=1
            citations['resolved']+=1
            citations['authorized_and_bounded']+=int(all(c.get(k) is True for k in ['reference_valid','authorized','digest_valid','locator_valid','policy_safe']))
            citations['quotation_exact']+=int(c.get('quotation_valid') is True)
        supported=0
        for claim in a['claims']:
            claims['published']+=1
            ids=claim.get('evidence_ids',[])
            valid=bool(ids) and len(ids)==len(set(ids)) and set(ids).issubset(evidence_payloads) and claim.get('kind')=='inference'
            pred=claim.get('predicate',{})
            if pred.get('kind')=='contract_violation':
                raw=read_input(corpus/'inputs',case.observation)
                if case.observation.source_format!='failurelens-bundle-v2':valid=False
                else:
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:measurement=json.loads(z.read('measurement.json'))
                    kind=independent_contract(measurement)
                    valid &= (kind is not None and pred=={'kind':'contract_violation','contract':kind}
                              and category==CONTRACT_CATEGORY.get(kind) and label.expected_category==CONTRACT_CATEGORY.get(kind)
                              and claim.get('text')==CONTRACT_TEXT.get(kind))
                    valid &= all(evidence_payloads[i]['observation'].get('contract_observation')==measurement for i in ids)
                    valid &= all(evidence_payloads[i]['source_locator']['sha256']==digest(canonical(measurement)) for i in ids)
            else:
                valid &= (category==label.expected_category and category in WORDS
                          and pred=={'kind':'classification_signal','category':category,'minimum_score':3}
                          and claim.get('text')==f"Observed signals support a {WORDS.get(category)} classification.")
                if category=='known_flake':valid &= p['history']['history_eligible_for_reassurance'] is True
            supported+=int(valid)
        claims['supported']+=supported
        claims['rejected_prepublication']+=sum(c.get('status')=='rejected' for c in a['validation_results'].get('claims',[]))
        if category!='insufficient_evidence' and not a['claims']:
            raise ValueError('Non-abstained output lacks a published claim')
        published=canonical({k:a.get(k) for k in ['summary','claims','hypotheses','next_investigation']})
        canaries+=int(b'synthetic-campaign-canary-41729' in published)
        forbidden+=sum(phrase.encode() in published.lower() for phrase in label.forbidden_claims)
        report=safe_file(replay_dir,p['report']).decode()
        expected_hold = category in {'product_defect','insufficient_evidence'}
        if (p['advisory_hold'] != expected_hold
                or ('HOLD_FOR_REVIEW' if expected_hold else 'NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE') not in report
                or 'This report is advisory. It does not approve a release' not in report):
            raise ValueError('Failure lost its scoped advisory status')
        rows.append(dict(case_id=label.case_id,scenario_family_id=label.family_group,source_kind=label.source_kind,
            severity=label.severity,expected_category=label.expected_category,predicted=category,modes=p['modes'],split=label.split,
            abstention_reason=a['abstention_reason'],claim_count=len(a['claims']),supported_claim_count=supported,
            adversarial_tags=label.adversarial_tags,seconds=p['seconds'],run_id=p['run_id'],analysis_id=a['analysis_id']))
    test=[r for r in rows if r['split']==score_split]
    if not test:
        raise ValueError('The declared scoring split is empty')
    metrics=classification_metrics(test,'full_deterministic')
    metrics.update(dict(evaluation_version='campaign-v1',evaluation_scope='frozen_mixed_source_campaign',split=score_split,
        source_revision=replay['source_revision'],source_tree=replay['source_tree'],source_worktree_dirty=replay['source_worktree_dirty'],
        database_dialect=replay['database_dialect'],dataset_case_count=inventory['case_count'],dataset_family_count=inventory['family_count'],
        family_count=len({r['scenario_family_id'] for r in test}),dataset_source_counts=inventory['source_counts'],
        source_counts={s:sum(r['source_kind']==s for r in test) for s in ['ledgerguard_executed','synthetic','other_executed']},
        split_counts=inventory['split_counts'],corpus_audit=inventory,input_manifest_sha256=inventory['public_manifest_sha256'],
        policy_sha256=digest((corpus/'policy.json').read_bytes()),replay_sha256=digest((replay_dir/'predictions.json').read_bytes()),
        by_split={s:classification_metrics([r for r in rows if r['split']==s],'full_deterministic') for s in ['development','calibration','test']},
        by_family={f:classification_metrics([r for r in test if r['scenario_family_id']==f],'full_deterministic') for f in sorted({r['scenario_family_id'] for r in test})},
        comparisons={m:classification_metrics(test,m) for m in ['constant_product_baseline','rules_only','rules_with_history','full_deterministic']},
        family_recall_uncertainty=family_recall_interval(test),
        citation_checks={k:fraction(citations[k],citations['total']) for k in ['resolved','authorized_and_bounded','quotation_exact']},
        claim_checks=dict(scope='all_replayed_cases',published=claims['published'],supported=claims['supported'],unsupported_rate=fraction(claims['published']-claims['supported'],claims['published']),
                          rejected_prepublication=claims['rejected_prepublication'],rubric='Independent bounded wording/category rubric and numeric contract recomputation; not a universal semantic judge'),
        adversarial=dict(cases=sum(bool(r['adversarial_tags']) for r in rows),tags=sorted({t for r in rows for t in r['adversarial_tags']}),
                         sensitive_canary_leaks=canaries,forbidden_claim_occurrences=forbidden,mandatory_attack_class_coverage_complete=False),
        temporal_history_checks=history_checks,unknown_family_test_cases=len(test),
        nuisance_groups=len(nuisance),nuisance_agreement=all(all(v==values[0] for v in values) for values in nuisance.values()),
        repeated_analysis_count=5,wall_seconds=replay['wall_seconds'],peak_process_rss_kib=replay['peak_process_rss_kib'],
        runtime_guards=replay['runtime_guards'],external_model_requests=0,compute_cost=None,
        errors=[r for r in test if r['predicted']!=r['expected_category']],
        generalization_claim_allowed=False,full_m6_complete=False,
        limitations=[
            'The 160-case test split is synthetic and public/agent-authored, not independently blinded or expert-adjudicated.',
            'The 60 actual companion component cases are retained executed artifacts in development; this campaign replays them, not fresh Java execution.',
            'Twelve additional typed-observation development cases are synthetic supplements to three existing families, not new independent families.',
            'The 87 catalogue groups have explicit mechanisms and structural split checks; these are not an automated proof of conceptual independence.',
            'Known-flake history and reviewer events are explicitly synthetic fixtures; future records are seeded to test exclusion.',
            'Family-disjoint test scenarios are an unknown-family challenge relative to development/calibration, not a production temporal backtest.',
            'Claim scoring checks controlled wording, category rubrics and three numeric contracts; broader semantic adjudication remains incomplete.',
            'Eight textual adversarial classes are exercised; complete master-prompt attack-class coverage is not established.',
            'Five repeated analyses are not five independent full-stack performance trials; compute cost and deployment performance remain unknown.',
            'Existing component/full-stack reports remain separate and unchanged. Quality target failures do not become passes because integrity CI is green.',
        ]))
    metrics['integrity_acceptance']=dict(frozen_corpus_and_group_separation=True,all_input_receipts_idempotent=True,
        five_exact_repetitions=True,all_published_citations_resolve=citations['resolved']==citations['total'] and citations['total']>0,
        all_citations_authorized_and_bounded=citations['authorized_and_bounded']==citations['total'],
        committed_clean_source=replay['source_worktree_dirty'] is False,no_future_history=True,no_external_network_or_subprocess=all(v==0 for v in replay['runtime_guards'].values()),
        zero_sensitive_canary_leaks=canaries==0,zero_forbidden_claims=forbidden==0,
        zero_critical_high_dangerous_dismissals=metrics['critical_high_dangerous_dismissal']['numerator']==0,
        all_published_claims_supported=claims['supported']==claims['published'],
        no_unsupported_critical_reassurance=not any(r['expected_category']=='product_defect' and r['predicted'] in {'known_flake','infrastructure_failure'} and r['supported_claim_count']<r['claim_count'] for r in rows))
    metrics['quality_targets']=dict(product_recall_at_least_90_percent=metrics['product_defect_recall'] is not None and metrics['product_defect_recall']>=policy['product_recall_minimum'],
        macro_f1_at_least_0_80=metrics['macro_f1'] is not None and metrics['macro_f1']>=policy['macro_f1_minimum'],
        non_abstained_coverage_at_least_75_percent=metrics['non_abstained_coverage'] is not None and metrics['non_abstained_coverage']>=policy['coverage_minimum'],
        dangerous_dismissal_at_most_5_percent=metrics['dangerous_dismissal']['rate'] is not None and metrics['dangerous_dismissal']['rate']<=policy['dangerous_dismissal_maximum'],
        identical_nuisance_results=metrics['nuisance_agreement'])
    if score_split != 'test':
        metrics.update(evaluation_scope='development_contract_measurement',
                       unknown_family_test_cases=0, held_out_acceptance=False)
        metrics['limitations']=[
            'This is development/regression measurement, not a held-out test or full M6 acceptance.',
            'Case variants share mechanisms and are not independent population observations.',
            'Source kinds describe the actual producer; replay alone is not a fresh companion execution.',
            'Labels and scope are agent-reviewed, not independently blinded or expert-adjudicated.',
            'All original corpus minimums and numerical targets remain unchanged and visible.',
            'A missing category makes broad five-category acceptance unsupported regardless of displayed macro F1.',
            'Future independent families, a complete temporal backtest and the full adversarial suite remain required.',
        ]
    return metrics,rows


def render(m):
    def number(v):return 'undefined' if v is None else f'{v:.3f}'
    development=m['evaluation_scope']=='development_contract_measurement'
    title='Development diagnostic measurement' if development else 'Frozen mixed-source campaign'
    lines=[f'# {title}','',f"Tested source: `{m['source_revision']}`; database: `{m['database_dialect']}`.",
        f"Full dataset: {m['dataset_case_count']} cases / {m['dataset_family_count']} catalogued families. Scored {m['split']}: {m['case_count']} cases / {m['family_count']} families.",
        'Development/regression only; no held-out acceptance or completed M6 is claimed.' if development else
        'The test split is synthetic; retained companion executions remain in development. Full M6 remains PARTIAL.',
        f"Product recall: {number(m['product_defect_recall'])}; macro F1: {number(m['macro_f1'])}; non-abstained coverage: {number(m['non_abstained_coverage'])}.",
        f"Dangerous dismissals: {m['dangerous_dismissal']['numerator']}/{m['dangerous_dismissal']['denominator']}; product abstentions: {m['product_abstentions']}.",
        '', '## Unchanged numerical targets (not full acceptance)', *[f"- {'PASS' if v else 'FAIL'} — {k}" for k,v in m['quality_targets'].items()],
        '', '## Original corpus minimums', *[f"- {'PASS' if v else 'FAIL'} — {k}" for k,v in m['corpus_audit']['minimums'].items()],
        '', '## Integrity and safety', *[f"- {'PASS' if v else 'FAIL'} — {k}" for k,v in m['integrity_acceptance'].items()],
        '', '## Measured baselines', '| Mode | Product recall | Macro F1 | Coverage |', '|---|---:|---:|---:|',
        *[f"| {mode} | {number(v['product_defect_recall'])} | {number(v['macro_f1'])} | {number(v['non_abstained_coverage'])} |" for mode,v in m['comparisons'].items()],
        '', '## Cases requiring review', *[f"- `{r['case_id']}` — {r['scenario_family_id']}: expected `{r['expected_category']}`, published `{r['predicted']}`." for r in m['errors']],
        '', '## Limitations', *['- '+s for s in m['limitations']], '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--enforce-quality',action='store_true')
    p.add_argument('--development-only',action='store_true',help='Score an exclusively development corpus without claiming held-out minimums')
    args=p.parse_args()
    if args.output.exists():raise ValueError('Never overwrite historical benchmark results')
    if args.development_only:
        _, labels, _ = audit(args.corpus.resolve(), enforce_minimums=False)
        if any(label.split != 'development' for label in labels):
            raise ValueError('Development-only mode cannot score calibration or test cases')
    metrics,rows=evaluate(args.corpus.resolve(),args.replay.resolve(), enforce_minimums=not args.development_only,
                          score_split='development' if args.development_only else 'test')
    args.output.mkdir(parents=True)
    (args.output/'metrics.json').write_bytes(canonical(metrics));(args.output/'predictions.jsonl').write_bytes(b''.join(canonical(r) for r in rows))
    (args.output/'report.md').write_text(render(metrics));print(render(metrics))
    if not all(metrics['integrity_acceptance'].values()):raise SystemExit(1)
    if args.enforce_quality and not all(metrics['quality_targets'].values()):raise SystemExit(2)

if __name__=='__main__':main()
