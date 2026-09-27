import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, type Ingestion, type RunInput } from './api';

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
