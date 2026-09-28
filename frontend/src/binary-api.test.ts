import { afterEach, describe, expect, it, vi } from 'vitest';
import { binaryApi, BinaryError, verifyLocalImage, type BinaryEvidence } from './binary-api';

const item = { input_id: 'input/one', version: 3, source_bytes: 3, source_digest: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' } as BinaryEvidence;
afterEach(() => vi.unstubAllGlobals());

describe('safe binary evidence client', () => {
  it('uses a body-bound review contract without putting reasons or bytes in URLs', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(item)));
    vi.stubGlobal('fetch', fetch);
    await binaryApi.review(item, new File(['abc'], 'original.png'), 'Reviewed private pixels', [{ x: 1, y: 2, width: 3, height: 4 }]);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/binary-evidence/input%2Fone/screenshot-reviews');
    expect(init.credentials).toBe('include');
    expect(init.headers).toEqual({ 'Content-Type': 'application/vnd.failurelens.image-review' });
    const body = await (init.body as Blob).text();
    const [header, bytes] = body.split('\n');
    expect(JSON.parse(header)).toEqual({ expected_version: 3, reason: 'Reviewed private pixels', confirm_safe: true, masks: [{ x: 1, y: 2, width: 3, height: 4 }] });
    expect(bytes).toBe('abc');
  });
  it('passes cancellation through paged reads', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"items":[],"total":0,"offset":25,"limit":25}'));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    await binaryApi.list('run/1', 25, controller.signal);
    expect(fetch).toHaveBeenCalledWith('/api/v1/runs/run%2F1/binary-evidence?offset=25&limit=25', expect.objectContaining({ signal: controller.signal, credentials: 'include' }));
  });
  it('distinguishes expired evidence without returning a proxy error body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<script>unsafe error</script>', { status: 410 })));
    await expect(binaryApi.get('gone')).rejects.toEqual(new BinaryError(410, 'Evidence request failed (410).'));
  });
  it('surfaces a safe version-conflict message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":{"code":"version_conflict","message":"Reload this review"}}', { status: 409 })));
    await expect(binaryApi.decide(item, 'revoke', 'Revocation explanation')).rejects.toThrow('Reload this review');
  });
  it('verifies local bytes before allowing the review preview', async () => {
    await expect(verifyLocalImage(new File(['abc'], 'image.png'), item)).resolves.toBeUndefined();
    await expect(verifyLocalImage(new File(['xyz'], 'image.png'), item)).rejects.toThrow('does not match the source digest');
    await expect(verifyLocalImage(new File(['longer'], 'image.png'), item)).rejects.toThrow('recorded size');
  });
  it('keeps approved downloads on the authenticated same origin', () => {
    expect(binaryApi.content('../forged', '?download=true')).toBe('/api/v1/artifact-derivatives/..%2Fforged/content?download=true');
  });
});
