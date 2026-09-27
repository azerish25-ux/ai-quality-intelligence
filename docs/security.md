# Security and trust boundaries

## Untrusted inputs

Every artifact field is untrusted: filenames, manifests, XML/JSON/JSONL, test names, logs, URLs, request/response evidence, commit metadata, screenshots, trace snapshots, report prose, and model output. A string that looks like an instruction has no authority.

## Implemented controls

- Reject JUnit DTD/entity declarations and malformed required structures.
- Reject traversal, absolute, drive-prefixed and dot-segment archive names; symlinks, encrypted entries, case-folded path collisions, undeclared nested archives and excessive expansion/compression ratios.
- Treat only a manifest-declared Playwright trace as an eligible nested ZIP and inspect it through the bounded trace adapter.
- Revalidate stored byte count and SHA-256 before worker parsing.
- Remove terminal control sequences from display evidence and record that transformation.
- Redact authorization headers, cookies, token/API-key/password fields, private-key blocks, emails, phone numbers and session identifiers.
- Sanitize URL query values without fetching any URL found in evidence.
- Bound decoded images by pixel count and keep screenshot originals restricted.
- Keep trace originals restricted; retain only a bounded, non-executable metadata/event index.
- Persist required/optional input scope and missing/rejected/restricted/unsupported states so absent or unsafe evidence cannot masquerade as a complete run.
- Store evidence/input digests and versioned parser/redaction provenance.
- Keep the deterministic analyzer incapable of shell, network, GitHub-write, test-deletion, quarantine, merge or release actions.
- Prevent non-product classifications from overriding conflicting product-risk evidence without abstention.
- Render GitHub Markdown with fixed advisory language and no release approval.
- Serve the frontend with a restrictive CSP and `nosniff`; never execute artifact HTML, SVG scripts or trace viewer content on the authenticated origin.

## Binary evidence state

Screenshot and Playwright-trace adapters currently produce bounded metadata/index records while marking the original artifact `restricted`. This is safer than treating an accepted upload as display-safe, but it is not the complete safe-derivative requirement.

Still required:

- immutable reviewed/masked screenshot derivatives and source maps;
- perceptual comparison only across compatible approved images;
- richer safe trace extraction and a controlled local viewing workflow;
- explicit encrypted-original retention/key policy and cleanup audit;
- authorized artifact preview/download endpoints with range and expiry controls.

## Known gaps

Automatic redaction remains incomplete for unknown free-text identifiers, names, arbitrary binary formats, DOM snapshots and pixels. Project-scoped viewer/reviewer/admin authorization, ingestion rate limiting, cross-project cache/isolation tests, retention/backup policy, and publication-grade semantic claim validation remain incomplete.

The current demo mode permits unauthenticated local writes when no ingestion token is configured. Production deployment must disable demo mode and supply a strong token; full project-scoped identity and roles remain pending.

## No overclaim

The adversarial tests cover declared text secret classes, terminal controls, URL query handling, unsafe XML/ZIP structures, malformed manifests, digest mismatch, binary limits and incomplete-input behavior. They do not establish universal PII detection, prompt-injection immunity, or that restricted screenshots/traces are safe to publish. No real credentials or customer data are included.
