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
- Convert normalized text/structured observations into immutable content-addressed safe derivatives with source maps and versioned parser/extractor/redaction provenance.
- Bind each evidence record to its exact execution and manifest input; ambiguous legacy rows remain unscoped and are rejected from new analysis.
- Before publication, re-read derivative bytes and independently verify project/run/execution scope, source and derivative digests, locator bounds, exact excerpt, typed observation equality, derivative approval/retention state and semantic support.
- Withhold invalid claims and safely degrade unsupported non-abstaining classifications to `insufficient_evidence`.
- Keep the deterministic analyzer incapable of shell, network, GitHub-write, test-deletion, quarantine, merge or release actions.
- Prevent non-product classifications from overriding conflicting product-risk evidence without abstention.
- Render GitHub Markdown with fixed advisory language and no release approval.
- Serve the frontend with a restrictive CSP and `nosniff`; never execute artifact HTML, SVG scripts or trace viewer content on the authenticated origin.

## Safe derivative and binary evidence state

Text and structured observations now produce immutable approved JSON derivatives separate from restricted source storage. The public evidence metadata endpoint returns the safe derivative identity and provenance but never its storage path. Screenshot and Playwright-trace adapters still produce bounded metadata/index records while marking the original artifact `restricted`; they do not yet satisfy the complete binary safe-derivative requirement.

Still required:

- immutable reviewed/masked screenshot derivatives and source maps;
- perceptual comparison only across compatible approved images;
- richer safe trace extraction and a controlled local viewing workflow;
- explicit encrypted-original retention/key policy and cleanup audit;
- authorized artifact preview/download endpoints with range and expiry controls.

## Known gaps

Automatic redaction remains incomplete for unknown free-text identifiers, names, arbitrary binary formats, DOM snapshots and pixels. The implemented semantic validator covers deterministic classification predicates, not arbitrary future free-form claims. Project-scoped viewer/reviewer/admin authorization, ingestion rate limiting, cross-project cache/isolation tests, retention/backup policy, masked screenshots and richer trace derivatives remain incomplete.

The current demo mode permits unauthenticated local writes when no ingestion token is configured. Production deployment must disable demo mode and supply a strong token; full project-scoped identity and roles remain pending.

## No overclaim

The adversarial tests cover declared text secret classes, terminal controls, URL query handling, unsafe XML/ZIP structures, malformed manifests, digest mismatch, binary limits, incomplete-input behavior, cross-failure evidence isolation, derivative tampering, invalid safe-artifact access and irrelevant citations. They do not establish universal PII detection, prompt-injection immunity, or that restricted screenshots/traces are safe to publish. No real credentials or customer data are included.
