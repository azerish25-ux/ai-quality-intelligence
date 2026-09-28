# Security and trust boundaries

## M2.1 current binary-evidence boundary

See [safe-binary-evidence.md](safe-binary-evidence.md). This checkpoint supplies
immutable reviewed pixel masks, conservative compatible-image comparison,
version-pinned safe trace event extraction, controlled local inspection, and
approved derivative preview/download with authorization, integrity and lifecycle
checks. The default does not retain binary originals after successful processing.
Raw queue/staging failure recovery still uses existing restricted-source policy;
this is not a claim of universal encryption or instantaneous crash erasure.
Trace text is sanitized before bounded clipping. Unknown trace type names are
counted without publishing their raw values; malformed network URLs are withheld.
See the trace-text upgrade guidance in the binary-evidence contract: this code
change does not rewrite or automatically revoke earlier immutable derivatives.


## Untrusted inputs

Every artifact field is untrusted: filenames, manifests, XML/JSON/JSONL, test names, logs, URLs, request/response evidence, commit metadata, screenshots, trace snapshots, report prose, and model output. A string that looks like an instruction has no authority.

## Identity, authorization, and credentials

FailureLens has three authenticated principal types:

- a human user with project-scoped `viewer`, `reviewer`, or `administrator` membership;
- a project-bound ingestion credential with only the `ingestion:create` scope; and
- a clearly labeled synthetic administrator used only when local demo mode is enabled.

Human passwords are salted with Python's maintained `scrypt` primitive. Session and ingestion secrets are generated from cryptographic randomness and only SHA-256 digests are stored. Session cookies are `HttpOnly` and `SameSite=Lax`; production configuration must also enable `Secure`. Project ingestion secrets are returned exactly once when created. Their stored record exposes only a short prefix, scope, creator, timestamps, expiry, and revocation state.

Every project or resource identifier is resolved to its owning project before access is granted. A user without membership receives the same not-found response for a guessed cross-project identifier as for a missing resource. A member with insufficient privileges receives a forbidden response. Ingestion credentials cannot list projects, read evidence, inspect runs, create reviews, change settings, or act outside their assigned project.

Human review, cluster correction, and impact override APIs derive the actor from the authenticated principal. Client request bodies cannot name or impersonate an actor. Security-sensitive settings and human decisions append application audit events containing the verified actor, action, project, resource, reason, result, and safe metadata. These rows are append-only through the application; they are not claimed to be cryptographically immutable against a database administrator.

### Demo and production modes

The provided Compose stack uses demo mode and binds the API and dashboard to loopback. Demo mode permits a synthetic local administrator and labels that identity in the dashboard. It must not be exposed as a production service.

Production mode (`FAILURELENS_DEMO_MODE=false`) fails startup unless all of the following are true:

- `FAILURELENS_BOOTSTRAP_ADMIN_USERNAME` is set;
- `FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD` is at least 14 characters and is not a known placeholder; and
- `FAILURELENS_SESSION_COOKIE_SECURE=true`.

The old global `FAILURELENS_INGESTION_TOKEN` is rejected in production. Administrators must create project-scoped ingestion credentials through the authenticated settings API or dashboard.

## Implemented artifact and analysis controls

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
- Separate artifact-declared comparison trust from transport-bound effective trust; uploaded changed-file bytes cannot mark themselves as an authenticated or trusted workflow comparison.
- Persist infrastructure events outside test artifacts with stable producer identities and canonical digests; only operator-authorized `authenticated_lookup`, `trusted_workflow`, or `verified_monitor` records may enter correlation cohorts.
- Exclude infrastructure events recorded at/after the analysis cutoff and reject cross-project, repository/environment/worker/workflow/runner/region-incompatible context; correlations remain association-only and cannot independently authorize a classification.
- Require matching project, run, base/head values and immutable mapping versions before impact selection; incomplete, truncated, untrusted, unmapped or critical changes fail closed to full-suite execution.
- Keep impact recommendations advisory and incapable of executing/skipping tests; preserve mandatory critical tests and reject their exclusion through reviewer overrides.
- Render GitHub Markdown with fixed advisory language and no release approval.
- Serve the frontend with a restrictive CSP and `nosniff`; never execute artifact HTML, SVG scripts or trace viewer content on the authenticated origin.

## Safe derivative and binary evidence state

Text and structured observations produce immutable approved JSON derivatives separate from restricted source storage. Screenshot review burns opaque masks into newly encoded, metadata-stripped PNG derivatives; trace extraction creates bounded event derivatives with exact source locators. Original screenshot and trace artifacts remain restricted. Approving a derivative does not turn a restricted required input into a complete run.

Approved content endpoints enforce project membership, approval and revocation state, source/derivative digests and retention, with bounded preview/download and single-range access. The evidence metadata endpoint never returns storage paths. The local trace workflow prints checked, pinned inspection instructions; it does not execute a viewer or host trace HTML on the authenticated origin.

The implemented binary policy discards successfully processed originals through the deletion outbox rather than retaining them under an unconfigured encryption scheme. Encrypted retained-original storage/key management is not implemented. Interrupted/failed raw staging, backups and existing downloads need operator lifecycle controls; revocation cannot retract exported files.

## Known gaps

Automatic redaction remains incomplete for unknown free-text identifiers, names, arbitrary binary formats, DOM snapshots, and pixels. The semantic validator covers deterministic classification predicates, not arbitrary future free-form claims. MFA/SSO integration, request-rate limiting, backup/restore acceptance, independently exercised cross-project cache isolation, authenticated GitHub comparison lookup and broader producer/dialect and sensitive-field coverage remain incomplete. Account recovery and retention have scoped M5.3 implementations; they do not establish universal account security or data erasure. No universal PII detection or arbitrary trace-resource sanitization is claimed.

## No overclaim

The adversarial tests cover declared text secret classes, terminal controls, URL query handling, unsafe XML/ZIP structures, malformed manifests, digest mismatch, binary limits, incomplete-input behavior, cross-failure evidence isolation, derivative tampering, invalid safe-artifact access, irrelevant citations, session/token expiry and revocation, project-role enforcement, actor spoofing, and guessed cross-project identifiers. They do not establish universal PII detection, prompt-injection immunity, or that restricted screenshots/traces are safe to publish. No real credentials or customer data are included.

## M5.3 lifecycle and retention boundary

See [Operational lifecycle](operations-lifecycle.md). The retention worker is an
explicit system audit actor; it is not an HTTP credential type. Startup cannot
reactivate or promote users. Account mutation reauthentication is repeated under
ordered user/session locks, and normal request-validation errors omit raw inputs.
Project evidence expiry clears the covered evidence bodies and creates tombstones;
recorded outcomes/identities/decisions, metadata and independently retained history
remain. Retention is therefore not a claim of universal personal-data erasure or
cryptographic immutability. Global security-audit data, backups and exported files
require a separate operator retention process.
