import { afterEach, describe, expect, it, vi } from 'vitest';
import { operations, type RetentionPreview, type UserRecord } from './api';

afterEach(() => vi.unstubAllGlobals());
const mockFetch = (response = new Response('{}', { status: 200 })) => {
  const fetcher = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
};

describe('M5.3 operations client', () => {
  it('sends full-dataset filtering, stable pagination and abort signals to the server', async () => {
    const fetcher = mockFetch();
    const controller = new AbortController();
    await operations.reviewPage('project-1', { status: 'pending', search: 'old%_test', offset: 500, limit: 25, sort: 'oldest' }, controller.signal);
    const [url, init] = fetcher.mock.calls[0];
    const query = new URL(url, 'http://localhost').searchParams;
    expect(query.get('search')).toBe('old%_test');
    expect(query.get('offset')).toBe('500');
    expect(init.signal).toBe(controller.signal);
    expect(init.credentials).toBe('include');
  });

  it('keeps recovery credentials out of the URL and uses a POST body', async () => {
    const fetcher = mockFetch(new Response(null, { status: 204 }));
    await operations.redeemRecovery('flr_synthetic_canary', 'new-synthetic-password');
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/auth/recovery');
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ token: 'flr_synthetic_canary', new_password: 'new-synthetic-password' });
  });

  it('includes the actual optimistic account revision and reauthentication', async () => {
    const fetcher = mockFetch();
    const user = { id: 'user-1', lifecycle_version: 9 } as UserRecord;
    await operations.changeAccount(user, false, 'synthetic-current-password', 'Confirmed disable');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      expected_version: 9, current_password: 'synthetic-current-password', reason: 'Confirmed disable', is_active: false
    });
  });

  it('submits the exact confirmed cleanup preview rather than a new cutoff', async () => {
    const fetcher = mockFetch();
    const preview = { policy_version: 4, as_of: '2026-09-28T12:00:00Z', confirmation_digest: 'a'.repeat(64) } as RetentionPreview;
    await operations.queueCleanup('project-1', preview);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      expected_version: 4, as_of: preview.as_of, confirmation_digest: preview.confirmation_digest
    });
  });

  it('exports server-filtered rows, not just the visible page', async () => {
    const fetcher = mockFetch(new Response('id,action\n1,review\n'));
    expect(await operations.exportAudit('project-1', { action: 'review', search: 'actor', limit: 10, offset: 20 })).toContain('1,review');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ action: 'review', search: 'actor' });
    expect(fetcher.mock.calls[0][1].method).toBe('POST');
  });

  it('does not treat a denied or oversized export as CSV', async () => {
    mockFetch(new Response('export exceeds configured row limit', { status: 413 }));
    await expect(operations.exportAudit('project-1', {})).rejects.toThrow('413');
  });
});

describe('run-detail wire contract', () => {
  const run = {
    id: 'old-run', project_id: 'project-1', external_id: 'outside-recent-window',
    evidence_expired_at: '2026-09-28T15:00:00Z', source_expired_at: null
  };

  it('unwraps the real API envelope and preserves lifecycle metadata', async () => {
    const fetcher = mockFetch(new Response(JSON.stringify({ run, failure_types: { AssertionError: 1 }, failure_count: 1 })));
    expect(await operations.run(run.id)).toEqual(run);
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/runs/old-run');
    expect(fetcher.mock.calls[0][1].credentials).toBe('include');
  });

  it.each([null, {}, { id: 'old-run', project_id: 'project-1' }, { run: { id: 'other-run', project_id: 'project-1' } }, { run: { id: 'old-run' } }])(
    'rejects an invalid or mismatched run envelope: %j', async body => {
      mockFetch(new Response(JSON.stringify(body)));
      await expect(operations.run('old-run')).rejects.toThrow('Invalid run-detail response');
    }
  );

  it('propagates unavailable runs instead of substituting another run', async () => {
    mockFetch(new Response('run not found', { status: 404 }));
    await expect(operations.run('missing')).rejects.toThrow('404');
  });
});
