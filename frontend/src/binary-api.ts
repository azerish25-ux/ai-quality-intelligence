export interface ArtifactDerivativeSummary {
  id: string; kind: string; digest: string; media_type: string; size_bytes: number;
  redaction_version: string; approved: boolean; restricted: boolean;
  approval_state: string; retention_state: string;
}

export interface PixelMask { x: number; y: number; width: number; height: number }
export interface BinaryDecision {
  id: string; version: number; decision: string; derivative_id: string | null;
  actor_display: string; reason: string; masks: PixelMask[]; created_at: string;
}
export interface BinaryEvidence {
  input_id: string; manifest_input_id: string; project_id: string; run_id: string;
  kind: string; path: string | null; source_digest: string | null; source_bytes: number | null;
  source_status: string; state: string; version: number; execution_id: string | null;
  correlation: string; relationship: string | null; width: number | null; height: number | null;
  coordinate_system: string | null; comparison_context: Record<string, unknown>;
  derivative: ArtifactDerivativeSummary | null; warnings: string[];
  decisions: BinaryDecision[]; decisions_total: number; original_policy: string;
}
export interface BinaryPage { items: BinaryEvidence[]; total: number; offset: number; limit: number }
export interface TraceEvent {
  event: Record<string, unknown>; source_locator: { entry: string; entry_index: number; line: number; entry_digest: string; source_digest: string };
  text: string; evidence_id: string; evidence_derivative_id: string; evidence_digest: string; index: number; pointer: string;
}
export interface TracePage {
  derivative_id: string; digest: string; summary: Record<string, unknown>;
  events: TraceEvent[]; total: number; offset: number; limit: number;
}
export interface ImageComparison {
  status: 'COMPARABLE' | 'INCOMPATIBLE' | 'INSUFFICIENT_CONTEXT'; reasons: string[];
  similarity: number | null; hamming_distance: number | null; algorithm: string; advisory: string;
}
export class BinaryError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${url}`, { ...init, credentials: 'include' });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('failurelens:session-expired'));
    let message = `Evidence request failed (${response.status}).`;
    try {
      const value: unknown = await response.json();
      if (value && typeof value === 'object' && 'detail' in value) {
        const detail = value.detail;
        if (typeof detail === 'string') message = detail;
        else if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') message = detail.message;
      }
    } catch { /* Never render a proxy HTML error page as evidence. */ }
    throw new BinaryError(response.status, message);
  }
  return response.json() as Promise<T>;
}
const jsonPost = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const binaryApi = {
  list: (runId: string, offset = 0, signal?: AbortSignal) => read<BinaryPage>(`/runs/${encodeURIComponent(runId)}/binary-evidence?offset=${offset}&limit=25`, { signal }),
  get: (inputId: string, decisionOffset = 0, signal?: AbortSignal) => read<BinaryEvidence>(`/binary-evidence/${encodeURIComponent(inputId)}?decision_offset=${decisionOffset}`, { signal }),
  trace: (inputId: string, offset = 0, signal?: AbortSignal) => read<TracePage>(`/binary-evidence/${encodeURIComponent(inputId)}/trace-events?offset=${offset}&limit=10`, { signal }),
  review: (item: BinaryEvidence, file: File, reason: string, masks: PixelMask[], signal?: AbortSignal) => read<BinaryEvidence>(`/binary-evidence/${encodeURIComponent(item.input_id)}/screenshot-reviews`, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/vnd.failurelens.image-review' },
    body: new Blob([JSON.stringify({ expected_version: item.version, reason, confirm_safe: true, masks }), '\n', file])
  }),
  decide: (item: BinaryEvidence, decision: 'reject' | 'revoke', reason: string) => read<BinaryEvidence>(`/binary-evidence/${encodeURIComponent(item.input_id)}/decisions`, jsonPost({ expected_version: item.version, decision, reason })),
  compare: (expected: string, actual: string) => read<ImageComparison>('/image-comparisons', jsonPost({ expected_derivative_id: expected, actual_derivative_id: actual })),
  content: (id: string, query = '') => `/api/v1/artifact-derivatives/${encodeURIComponent(id)}/content${query}`
};

export async function verifyLocalImage(file: File, item: BinaryEvidence): Promise<void> {
  if (!item.source_digest || file.size !== item.source_bytes || file.size > 50 * 1024 * 1024) throw new Error('Select the exact original image with the recorded size.');
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), b => b.toString(16).padStart(2, '0')).join('');
  if (digest !== item.source_digest) throw new Error('This file does not match the source digest. No image was submitted.');
}
