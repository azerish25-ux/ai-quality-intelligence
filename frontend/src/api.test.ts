import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, type ClusterDetail, type ClusterSummary, type ImpactMappingSnapshot, type ImpactRecommendation, type Ingestion, type InfrastructureCorrelation, type InfrastructureEvent, type PerformanceComparison, type PerformanceObservation, type PerformancePolicy, type RunInput, type TestHistory } from './api';

const ingestion: Ingestion = {
  id: 'ing-1',
  project_id: 'project-1',
  external_id: 'workflow-1',
  attempt: 1,
  repository: null,
  commit_sha: null,
  base_sha: null,
  branch: null,
  source_format: 'auto',
  source_metadata: {},
  original_name: 'report.json',
  media_type: 'application/json',
  source_digest: 'a'.repeat(64),
  source_size_bytes: 2,
  expected_inputs: 1,
  received_inputs: 0,
  state: 'queued',
  run_id: null,
  job_id: 'job-1',
  parser_version: null,
  policy_version: 'artifact-policy-v1',
  diagnostics: [],
  error_code: null,
  error_message: null,
  retry_count: 0,
  started_at: null,
  completed_at: null,
  created_at: '2026-09-26T00:00:00Z',
  updated_at: '2026-09-26T00:00:00Z'
};

const runInput: RunInput = {
  id: 'input-row-1',
  project_id: 'project-1',
  run_id: 'run-1',
  input_id: 'report',
  kind: 'junit-xml',
  path: 'report.xml',
  required: true,
  status: 'accepted',
  digest: 'b'.repeat(64),
  size_bytes: 128,
  media_type: 'application/xml',
  parser_version: 'junit-v3',
  warnings: [],
  metadata_json: {},
  created_at: '2026-09-26T00:00:00Z'
};


const performancePolicy: PerformancePolicy = {
  id: 'performance-policy-1',
  project_id: 'project-1',
  version: 'performance-policy-v1',
  relative_tolerance: 0.1,
  absolute_tolerance: 0,
  min_baseline_runs: 3,
  max_baseline_age_days: 30,
  require_trusted: true,
  required_dimensions: ['repository', 'workload', 'environment'],
  direction_overrides: {},
  created_at: '2026-09-27T00:00:00Z'
};

const performanceObservation: PerformanceObservation = {
  id: 'performance-observation-1',
  project_id: 'project-1',
  run_id: 'run-1',
  run_input_id: 'input-row-1',
  execution_id: null,
  evidence_id: 'evidence-current',
  metric_key: '1'.repeat(64),
  metric_name: 'http_req_duration',
  metric_scope: 'k6_summary',
  statistic: 'p95',
  direction: 'lower_is_better',
  original_value: 130,
  original_unit: 'ms',
  canonical_value: 130,
  canonical_unit: 'ms',
  sample_count: 600,
  producer: 'k6-handleSummary',
  producer_version: '0.54.0',
  workload: 'checkout-steady',
  dimension_signature: '2'.repeat(64),
  dimensions: { repository: 'owner/repo', environment: 'ci-linux' },
  threshold_status: 'passed',
  threshold_details: {},
  source_digest: '3'.repeat(64),
  source_locator: { pointer: '/metrics/http_req_duration/values/p(95)' },
  observed_at: '2026-09-27T00:00:00Z',
  created_at: '2026-09-27T00:00:00Z'
};

const performanceComparison: PerformanceComparison = {
  id: 'performance-comparison-1',
  project_id: 'project-1',
  current_run_id: 'run-1',
  current_observation_id: performanceObservation.id,
  baseline_snapshot_id: 'performance-baseline-1',
  policy_id: performancePolicy.id,
  engine_version: 'performance-engine-v1',
  input_digest: '4'.repeat(64),
  status: 'REGRESSION',
  metric_name: performanceObservation.metric_name,
  metric_scope: performanceObservation.metric_scope,
  statistic: performanceObservation.statistic,
  direction: performanceObservation.direction,
  workload: performanceObservation.workload,
  canonical_unit: 'ms',
  current_value: 130,
  baseline_value: 100,
  absolute_change: 30,
  relative_change: 0.3,
  allowed_absolute_change: 10,
  allowed_relative_change: 0.1,
  current_sample_count: 600,
  baseline_run_count: 3,
  baseline_sample_count: 1800,
  threshold_status: 'passed',
  effect_size: null,
  uncertainty: { significance_claimed: false },
  compatibility: { rejected_reason_counts: {} },
  confounders: ['no_statistical_significance_claim_from_single_current_summary'],
  current_evidence_id: 'evidence-current',
  baseline_evidence_ids: ['evidence-b1', 'evidence-b2', 'evidence-b3'],
  next_measurement: 'Repeat the identical workload.',
  summary: 'Compatible prior baseline indicates a regression.',
  baseline: {
    id: 'performance-baseline-1',
    project_id: 'project-1',
    current_run_id: 'run-1',
    current_observation_id: performanceObservation.id,
    policy_id: performancePolicy.id,
    input_digest: '5'.repeat(64),
    status: 'AVAILABLE',
    cutoff_at: '2026-09-27T00:00:00Z',
    cohort_dimensions: { environment: 'ci-linux' },
    compatibility: { accepted_count: 3 },
    rejected_candidates: [],
    run_count: 3,
    sample_count: 1800,
    baseline_value: 100,
    baseline_min: 95,
    baseline_max: 105,
    baseline_mad: 5,
    baseline_age_seconds: 86400,
    aggregation: 'median_of_run_level_observations',
    members: [],
    created_at: '2026-09-27T00:00:00Z'
  },
  created_at: '2026-09-27T00:00:00Z'
};

const impactMapping: ImpactMappingSnapshot = {
  id: 'mapping-1',
  project_id: 'project-1',
  version: 'mapping-v1',
  policy_version: 'impact-policy-v1',
  source_digest: 'e'.repeat(64),
  trusted: true,
  coverage_complete: true,
  source_metadata: { trusted_revision: 'abcdef0' },
  test_count: 3,
  edge_count: 1,
  created_at: '2026-09-27T00:00:00Z'
};

const impactRecommendation: ImpactRecommendation = {
  id: 'impact-1',
  project_id: 'project-1',
  run_id: 'run-1',
  changed_input_id: 'changes-1',
  mapping_snapshot_id: 'mapping-1',
  base_sha: '1'.repeat(40),
  head_sha: '2'.repeat(40),
  input_digest: 'f'.repeat(64),
  changed_files_digest: 'a'.repeat(64),
  engine_version: 'impact-engine-v1',
  policy_version: 'impact-policy-v1',
  status: 'FOCUSED_SUBSET',
  current_revision: 0,
  comparison_trusted: true,
  mapping_complete: true,
  full_suite_required: false,
  summary: 'Selected 2 of 3 tests.',
  changed_files: [{ status: 'modified', path: 'src/checkout.py' }],
  safety_reasons: [],
  metrics: { test_catalog_count: 3, effective_selected_test_count: 2 },
  selected_tests: [],
  excluded_tests: [],
  overrides: [],
  created_at: '2026-09-27T00:00:00Z',
  updated_at: '2026-09-27T00:00:00Z'
};

const clusterSummary: ClusterSummary = {
  id: 'cluster-1',
  project_id: 'project-1',
  cluster_key: 'c'.repeat(64),
  algorithm_version: 'explainable-complete-link-v1',
  feature_version: 'cluster-features-v1:fingerprint-v1',
  current_revision: 2,
  representative_failure_id: 'failure-1',
  representative_test_identity: 'payments::duplicate',
  member_count: 2,
  uncertainty: 'low',
  status: 'active',
  superseded_by_cluster_id: null,
  created_at: '2026-09-26T00:00:00Z',
  updated_at: '2026-09-26T00:00:00Z'
};


const infrastructureEvent: InfrastructureEvent = {
  id: 'infrastructure-event-1',
  project_id: 'project-1',
  repository: 'owner/repo',
  environment: 'ci-linux',
  producer: 'status-monitor',
  producer_event_id: 'monitor-event-1',
  event_kind: 'service_outage',
  severity: 'error',
  status: 'resolved',
  started_at: '2026-09-26T10:00:00Z',
  ended_at: '2026-09-26T10:10:00Z',
  recorded_at: '2026-09-26T10:11:00Z',
  workflow_name: 'ci',
  workflow_run_id: '1234',
  workflow_attempt: 1,
  runner_identity: 'runner-1',
  runner_group: 'hosted',
  region: 'ca-east',
  worker_count: 4,
  shard_identity: null,
  source_trust: 'verified_monitor',
  trusted_for_correlation: true,
  source_digest: '6'.repeat(64),
  evidence_id: null,
  metadata: { monitor: 'checkout-gateway' },
  created_at: '2026-09-26T10:11:00Z'
};

const infrastructureCorrelation: InfrastructureCorrelation = {
  snapshot_id: 'infrastructure-snapshot-1',
  project_id: 'project-1',
  selected_run_id: 'run-1',
  selected_execution_id: 'execution-1',
  policy_version: 'infrastructure-correlation-policy-v1',
  engine_version: 'infrastructure-correlation-v1',
  history_input_digest: 'd'.repeat(64),
  input_digest: '7'.repeat(64),
  status: 'AVAILABLE',
  cutoff_at: '2026-09-27T00:00:00Z',
  after_at: null,
  window_seconds: 900,
  event_kind: null,
  minimum_support: 3,
  accepted_event_ids: [infrastructureEvent.id],
  accepted_events: [infrastructureEvent],
  rejected_events: [],
  sample_sizes: {
    independent_runs: 6,
    exposed_runs: 3,
    unexposed_runs: 3,
    exposed_pass_fail_denominator: 3,
    unexposed_pass_fail_denominator: 3,
    accepted_events: 1,
    rejected_events: 0
  },
  exposed_outcomes: { passed: 0, failed: 3, skipped: 0, cancelled: 0, unknown: 0 },
  unexposed_outcomes: { passed: 3, failed: 0, skipped: 0, cancelled: 0, unknown: 0 },
  rates: {
    exposed_failure_rate: { numerator: 3, denominator: 3, value: 1, interval_95: [0.4385, 1], status: 'available', minimum_support: 3, definition: 'Failure rate.' },
    unexposed_failure_rate: { numerator: 0, denominator: 3, value: 0, interval_95: [0, 0.5615], status: 'available', minimum_support: 3, definition: 'Failure rate.' },
    absolute_failure_rate_difference: 1,
    relative_risk: null
  },
  associations: [],
  confounders: [],
  safety: {
    association_only: true,
    causality_claimed: false,
    can_support_infrastructure_association: true,
    can_independently_authorize_infrastructure_classification: false,
    trusted_sources_only: true,
    prior_only: true,
    current_run_excluded: true,
    truncated: false,
    notes: []
  },
  members: [],
  created_at: '2026-09-27T00:00:00Z'
};

const testHistory: TestHistory = {
  policy_version: 'history-v1',
  history_input_digest: 'd'.repeat(64),
  status: 'available',
  logical_test: { test_identity: 'payments::duplicate' },
  window: { before: '2026-09-26T12:00:00Z', prior_only: true },
  filters: { browser: 'chromium', run_scope: 'full_suite' },
  sample_sizes: { independent_runs: 5, runs_without_matching_test_observation: 1 },
  outcomes: {
    first_attempt: { passed: 2, failed: 3, skipped: 0, cancelled: 0, unknown: 0 },
    final: { passed: 4, failed: 1, skipped: 0, cancelled: 0, unknown: 0 }
  },
  rates: {
    observed_pass_rate: { numerator: 4, denominator: 5, value: 0.8, interval_95: [0.38, 0.96], status: 'available', minimum_support: 3, definition: 'Observed pass rate.' },
    first_attempt_failure_rate: { numerator: 3, denominator: 5, value: 0.6, interval_95: [0.23, 0.88], status: 'available', minimum_support: 3, definition: 'First-attempt failure rate.' },
    final_failure_rate: { numerator: 1, denominator: 5, value: 0.2, interval_95: [0.04, 0.62], status: 'available', minimum_support: 3, definition: 'Final failure rate.' },
    retry_recovery_rate: { numerator: 2, denominator: 3, value: 0.666667, interval_95: [0.21, 0.94], status: 'available', minimum_support: 3, definition: 'Retry recovery rate.' }
  },
  breakdowns: { browser: [], branch: [], environment: [], run_scope: [], worker_count: [], shard_count: [], time_bucket: [] },
  sequences: {},
  review: { reviewed_known_flake: true, events: [] },
  safety: { history_eligible_for_reassurance: true, insufficient_data_reasons: [], selection_bias_present: false, truncated: false, notes: [] },
  pagination: { offset: 0, limit: 100, returned: 0, total: 0 },
  observations: [],
  infrastructure_correlations: null
};

const clusterDetail: ClusterDetail = {
  ...clusterSummary,
  current: {
    id: 'revision-2',
    cluster_id: 'cluster-1',
    revision: 2,
    reason: 'human_confirm',
    algorithm_version: clusterSummary.algorithm_version,
    feature_version: clusterSummary.feature_version,
    representative_failure_id: 'failure-1',
    member_count: 2,
    score_summary: { average_similarity: 0.91 },
    uncertainty_flags: [],
    created_at: '2026-09-26T00:00:00Z',
    memberships: []
  },
  decisions: []
};

afterEach(() => vi.unstubAllGlobals());

describe('artifact upload client', () => {
  it('sends the report as a raw bounded upload with explicit metadata', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(ingestion), {
        status: 202,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['{}'], 'report.json', { type: 'application/json' });

    const result = await api.upload('project-1', file, {
      externalId: 'workflow-1',
      expectedInputs: 1,
      commitSha: 'abcdef0',
      runScope: 'full_suite',
      comparisonTrust: 'trusted_workflow',
      environment: 'ci-linux',
      timezone: 'America/Halifax',
      workerCount: 4,
      shardCount: 2
    });

    expect(result.state).toBe('queued');
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/projects/project-1/ingestions?');
    expect(url).toContain('filename=report.json');
    expect(url).toContain('external_id=workflow-1');
    expect(url).toContain('expected_inputs=1');
    expect(url).toContain('run_scope=full_suite');
    expect(url).toContain('comparison_trust=trusted_workflow');
    expect(url).toContain('environment=ci-linux');
    expect(url).toContain('timezone=America%2FHalifax');
    expect(url).toContain('worker_count=4');
    expect(url).toContain('shard_count=2');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(file);
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
  });
});


describe('run input diagnostics client', () => {
  it('loads persisted per-input completeness evidence', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([runInput]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.runInputs('run-1');

    expect(result).toEqual([runInput]);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/runs/run-1/inputs', {
      headers: { 'Content-Type': 'application/json' }
    });
  });
});

describe('explainable clustering client', () => {
  it('loads project and run cluster scopes', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([clusterSummary]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify([clusterSummary]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      }));
    vi.stubGlobal('fetch', fetchMock);

    expect(await api.clusters('project-1')).toEqual([clusterSummary]);
    expect(await api.runClusters('run-1')).toEqual([clusterSummary]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/projects/project-1/clusters', {
      headers: { 'Content-Type': 'application/json' }
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/runs/run-1/clusters', {
      headers: { 'Content-Type': 'application/json' }
    });
  });

  it('serializes an append-only reviewed split with the expected revision', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(clusterDetail), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.reviewCluster('cluster-1', {
      actor: 'reviewer@example.test',
      decision: 'split',
      reason: 'The selector and endpoint evidence identify a separate incident.',
      expectedRevision: 1,
      failureIds: ['failure-2']
    });

    expect(result.current_revision).toBe(2);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/clusters/cluster-1/reviews');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      actor: 'reviewer@example.test',
      decision: 'split',
      reason: 'The selector and endpoint evidence identify a separate incident.',
      expected_revision: 1,
      failure_ids: ['failure-2'],
      target_cluster_id: null
    });
  });
});


describe('prior-only history client', () => {
  it('serializes cohort filters and loads traceable history statistics', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(testHistory), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.testHistory('execution-1', {
      browser: 'chromium',
      branch: 'main',
      environment: 'ci-linux',
      runScope: 'full_suite',
      timezone: 'America/Halifax',
      workerCount: 4,
      shardCount: 2,
      limit: 50,
      offset: 10
    });

    expect(result.history_input_digest).toBe('d'.repeat(64));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/tests/execution-1/history?browser=chromium&branch=main&environment=ci-linux&run_scope=full_suite&timezone=America%2FHalifax&worker_count=4&shard_count=2&limit=50&offset=10',
      { headers: { 'Content-Type': 'application/json' } }
    );
  });
});



describe('infrastructure event correlation client', () => {
  it('lists independently recorded events and creates an immutable correlation snapshot', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([infrastructureEvent]), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(infrastructureCorrelation), {
        status: 201, headers: { 'Content-Type': 'application/json' }
      }));
    vi.stubGlobal('fetch', fetchMock);

    expect(await api.infrastructureEvents('project-1')).toEqual([infrastructureEvent]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/projects/project-1/infrastructure-events', {
      headers: { 'Content-Type': 'application/json' }
    });

    const snapshot = await api.createInfrastructureCorrelation('execution-1', {
      environment: 'ci-linux',
      run_scope: 'full_suite',
      timezone: 'America/Halifax',
      worker_count: 4,
      shard_count: 2,
      event_kind: 'service_outage',
      window_seconds: 900,
      minimum_support: 3
    });
    expect(snapshot.safety.association_only).toBe(true);
    expect(snapshot.safety.can_independently_authorize_infrastructure_classification).toBe(false);
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe('/api/v1/tests/execution-1/infrastructure-correlations');
    expect(JSON.parse(String(init.body))).toEqual({
      environment: 'ci-linux',
      run_scope: 'full_suite',
      timezone: 'America/Halifax',
      worker_count: 4,
      shard_count: 2,
      event_kind: 'service_outage',
      window_seconds: 900,
      minimum_support: 3
    });
  });

  it('serializes a trusted event without generated server fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(infrastructureEvent), {
        status: 201, headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { id: _id, project_id: _projectId, trusted_for_correlation: _trusted, source_digest: _digest, created_at: _created, ...input } = infrastructureEvent;
    const created = await api.createInfrastructureEvent('project-1', input);
    expect(created.source_digest).toBe('6'.repeat(64));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/projects/project-1/infrastructure-events');
    expect(JSON.parse(String(init.body))).not.toHaveProperty('trusted_for_correlation');
    expect(JSON.parse(String(init.body))).toMatchObject({
      producer_event_id: 'monitor-event-1',
      source_trust: 'verified_monitor',
      event_kind: 'service_outage'
    });
  });
});

describe('change-impact client', () => {
  it('registers an immutable mapping and creates an explainable recommendation', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(impactMapping), {
        status: 201,
        headers: { 'Content-Type': 'application/json' }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(impactRecommendation), {
        status: 201,
        headers: { 'Content-Type': 'application/json' }
      }));
    vi.stubGlobal('fetch', fetchMock);

    const createdMapping = await api.createImpactMapping('project-1', {
      version: 'mapping-v1',
      trusted: true,
      coverage_complete: true,
      tests: [{ test_key: 'checkout', test_identity: 'checkout' }],
      edges: []
    });
    expect(createdMapping.source_digest).toBe('e'.repeat(64));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/projects/project-1/impact-mappings');
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toMatchObject({
      version: 'mapping-v1',
      trusted: true,
      coverage_complete: true
    });

    const recommendation = await api.createImpactRecommendation(
      'project-1', 'run-1', 'mapping-1', 'changes-1', 'a'.repeat(40), 'b'.repeat(40)
    );
    expect(recommendation.status).toBe('FOCUSED_SUBSET');
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({
      run_id: 'run-1',
      mapping_snapshot_id: 'mapping-1',
      changed_input_id: 'changes-1',
      base_sha: 'a'.repeat(40),
      head_sha: 'b'.repeat(40)
    });
  });

  it('serializes an attributed optimistic override', async () => {
    const revised = {
      ...impactRecommendation,
      current_revision: 1,
      overrides: [{
        id: 'override-1',
        actor: 'reviewer@example.test',
        action: 'include',
        test_key: 'profile',
        reason: 'Reviewed release-risk coupling.',
        revision_before: 0,
        revision_after: 1,
        created_at: '2026-09-27T00:01:00Z'
      }]
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(revised), {
        status: 201,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.overrideImpactRecommendation('impact-1', {
      actor: 'reviewer@example.test',
      action: 'include',
      testKey: 'profile',
      reason: 'Reviewed release-risk coupling.',
      expectedRevision: 0
    });

    expect(result.current_revision).toBe(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/impact-recommendations/impact-1/overrides');
    expect(JSON.parse(String(init.body))).toEqual({
      actor: 'reviewer@example.test',
      action: 'include',
      test_key: 'profile',
      reason: 'Reviewed release-risk coupling.',
      expected_revision: 0
    });
  });
});


describe('compatible performance intelligence client', () => {
  it('loads policies and normalized observations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([performancePolicy]), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify([performanceObservation]), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      }));
    vi.stubGlobal('fetch', fetchMock);

    expect(await api.performancePolicies('project-1')).toEqual([performancePolicy]);
    expect(await api.performanceObservations('run-1')).toEqual([performanceObservation]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/projects/project-1/performance-policies', {
      headers: { 'Content-Type': 'application/json' }
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/runs/run-1/performance-observations', {
      headers: { 'Content-Type': 'application/json' }
    });
  });

  it('registers an immutable policy and creates prior-only comparisons', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(performancePolicy), {
        status: 201, headers: { 'Content-Type': 'application/json' }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify([performanceComparison]), {
        status: 201, headers: { 'Content-Type': 'application/json' }
      }));
    vi.stubGlobal('fetch', fetchMock);

    const policy = await api.createPerformancePolicy('project-1', {
      version: 'performance-policy-v1',
      min_baseline_runs: 3,
      require_trusted: true
    });
    expect(policy.version).toBe('performance-policy-v1');
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      version: 'performance-policy-v1',
      min_baseline_runs: 3,
      require_trusted: true
    });

    const findings = await api.createPerformanceComparisons(
      'run-1', performancePolicy.id, [performanceObservation.id]
    );
    expect(findings[0].status).toBe('REGRESSION');
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({
      policy_id: performancePolicy.id,
      observation_ids: [performanceObservation.id]
    });
  });
});
