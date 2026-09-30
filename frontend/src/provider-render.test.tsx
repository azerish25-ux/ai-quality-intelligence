import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ProviderInvocationView } from './OptionalProvider';
import { providerTestJob as job } from './provider-fixtures';

describe('provider proposal rendering boundary', () => {
  it('renders model markup as text and creates only scoped evidence links', () => {
    const html = renderToStaticMarkup(<ProviderInvocationView job={{ ...job, invocation_state: 'proposed', proposal: { category: 'test_defect', hypotheses: [{ text: '<img src=x onerror="alert(1)"><script>fetch("https://evil.invalid")</script>', evidence_ids: ['evidence/one?secret'] }], contradictory_evidence_ids: [], missing_evidence: ['<a href="https://evil.invalid">read this</a>'] } }} category="insufficient_evidence" canCancel={false} busy={false} cancel={() => {}} />);
    expect(html).not.toContain('<script>'); expect(html).not.toContain('<img '); expect(html).not.toContain('href="https://evil.invalid"');
    expect(html).toContain('&lt;img'); expect(html).toContain('href="/api/v1/evidence/evidence%2Fone%3Fsecret"');
    expect(html).toContain('Unverified model hypotheses'); expect(html).toContain('Disagrees with the selected deterministic analysis');
    expect(html).toContain('Unknown cost'); expect(html).not.toContain('$0');
  });
  it('distinguishes recorded cancellation from completed transport accounting', () => {
    const html = renderToStaticMarkup(<ProviderInvocationView job={{ ...job, invocation_state: 'cancelled', recovery_required: true, cancel_requested_at: '2026-09-30T12:01:00Z' }} category="product_defect" canCancel={true} busy={false} cancel={() => {}} />);
    expect(html).toContain('Cancellation recorded · accounting pending'); expect(html).toContain('Transport termination and accounting are still pending');
    expect(html).not.toContain('Request cancellation</button>'); expect(html).toContain('accounting incomplete');
  });
});
