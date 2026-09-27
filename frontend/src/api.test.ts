import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, type ClusterDetail, type ClusterSummary, type Ingestion, type RunInput } from './api';

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
      commitSha: 'abcdef0'
    });

    expect(result.state).toBe('queued');
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/projects/project-1/ingestions?');
    expect(url).toContain('filename=report.json');
    expect(url).toContain('external_id=workflow-1');
    expect(url).toContain('expected_inputs=1');
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
