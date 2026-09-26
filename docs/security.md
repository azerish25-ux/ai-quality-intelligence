# Security and trust boundaries

## Untrusted inputs

Every artifact field is untrusted: filenames, XML/JSON, test names, logs, stack traces, commit metadata, evidence text, report prose, and model output. A string that looks like an instruction has no authority.

## Implemented controls

- Reject JUnit DTD/entity declarations.
- Reject traversal, absolute, drive-prefixed, and dot-segment archive names.
- Remove terminal control sequences before display.
- Redact authorization headers, cookies, common token/password fields, private-key blocks, emails, phone numbers, and session identifiers.
- Preserve amounts, status codes, assertion direction, selectors, and endpoints unless they match an explicit sensitive rule.
- Store evidence digests and versioned parser/redaction provenance.
- Keep the deterministic analyzer incapable of shell, network, GitHub-write, test-deletion, quarantine, merge, or release actions.
- Prevent a non-product classification from overriding conflicting product-risk evidence without abstention.
- Render GitHub Markdown with fixed advisory language and no release approval.
- Serve the frontend with a restrictive CSP and no remote scripts/images.

## Known gaps

Automatic redaction is incomplete for unknown free-text identifiers, screenshots, DOM snapshots, and arbitrary binary formats. Pixel masking, restricted encrypted originals, short raw-retention workflows, ingestion rate limiting, project-scoped authentication/authorization, cross-project cache/isolation tests, SSRF-specific adapter tests, and hardened trace storage are not complete.

The current demo mode permits unauthenticated local writes when no ingestion token is configured. Production deployment must disable demo mode and supply a strong token; full viewer/reviewer/admin authorization is still pending.

## No overclaim

The current adversarial corpus covers text prompt injection and synthetic secret canaries. It does not establish prompt-injection immunity or universal PII detection. No real credentials or customer data are included.
