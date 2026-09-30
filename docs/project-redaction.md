# Project-keyed text correlation (redaction-v3)

This policy replaces newly generated global, truncated SHA-256 sensitive-value
pseudonyms. It does **not** rewrite historical artifacts, evaluation files,
reports, citations or already approved derivatives. This is bounded declared-field
redaction, not universal anonymization or PII detection.

## Policy and analytical scope

Recognized email, phone, session and explicitly named `transaction_id`/`tx_id`
values receive project-scoped HMAC-SHA256 pseudonyms with 128-bit output. A separate
project key is derived from the installation/operator key, key reference, policy
domain and project ID. Identical values/classes in the same project and key epoch
correlate across runs, API/worker processes and restarts. Different projects, keys
or key references produce different pseudonyms. Credential/private-key/cookie
classes are suppressed because their correlation is unnecessary.

No unkeyed digest of a sensitive value is generated as a privacy mechanism.
Source, content and immutable derivative digests remain ordinary integrity checks;
those checks do not provide secrecy. Pseudonyms reveal equality/frequency within a
project and are not an anonymity guarantee. A party with the secret key can test
guesses; protect key access independently from evidence access.

Named transaction tokens remain distinct. Recognized analytical numeric amount,
balance and status fields remain numerical evidence rather than generic phone
redactions. Existing strict transaction/domain/contract schemas preserve their
UUIDs, producer digests, exact amounts and status codes so diagnosis and independent
semantic recomputation do not change shape. **Those typed identifiers and
application-specific producer digests are not automatically anonymized here.**
A future schema-aware identity policy needs separate compatibility/quality review.
Unknown identifiers, names, arbitrary text, pixels and trace resources remain the
previously documented gaps.

Parser execution starts inside the authenticated project's context. The same
context covers JUnit/Playwright/pytest and other adapters, structured details,
normalized ingestion, typed observations and trace-event/index persistence.
Contexts are request-local and reset on success or exceptions. Direct parser or
logging calls without a project context suppress recognized sensitive values;
they never fabricate a global stable hash. Such standalone output explicitly has
no correlation scope and cannot later be upgraded without original inputs.

Only exact known legacy hash, v3 hash and suppression marker shapes pass through
byte-for-byte. Malformed, arbitrary-tail or truncated marker-shaped text is
suppressed, including secret/email canaries wrapped to resemble a prior token.
Legacy/unscoped and preexisting markers are flagged in provenance rather than silently hashed again
or represented as newly derived project identities. A copied v3 marker cannot
establish its origin or cross-project correlation. Correlation guarantees apply
to replacements made from original values by this policy.

## Default offline key lifecycle

No provider, network call, external credential or paid service is involved. The
first server ingestion initializes a random 256-bit installation correlation key
under `FAILURELENS_ARTIFACT_ROOT/.redaction/installation-key-v1.json`. Its random,
nonsecret `local-v1-...` reference is recorded separately in `initialized-v1`.
These are private operational state, never upload or derivative artifacts.

The key directory must be owned by the application user and private (0700); key
and marker files must be private (0600), regular, singly linked and bounded in
size. The artifact root must be application-owned and not group/world writable.
The loader uses no-follow directory/file descriptors, a one-second deadline for
nonblocking acquisition of an exclusive local filesystem lock, fsynced temporary
files and atomic no-overwrite publication.
Malformed keys, symlinks, unsafe permissions and inconsistent markers fail closed.
A busy lock returns a fixed error after the bounded wait. A crash between atomic
key hard-link publication and temporary unlink leaves two links: the next load
fails closed rather than weakening the singly-linked-file check or regenerating
a key. Restore a verified complete private-key backup with correct permissions;
there is no automatic orphan cleanup or recovery claim for this interrupted state.
The implementation requires a POSIX filesystem supporting advisory locks and
atomic hard links. All API and worker instances must share the same private
artifact volume and operating-system user, as the provided Compose services do.

Generic source/derivative storage resolution rejects the private `.redaction`
namespace, including a symlink alias into it. Even a corrupt evidence storage row
cannot use the ordinary content-serving reader to fetch key material.

The server stamps a policy/key reference into durable ingestion metadata before
worker parsing, overriding client/manifest attempts to supply the policy. New
queue records are `artifact-policy-v2`; older queued records acquire a server pin
before parsing rather than trusting an old client-supplied policy field. A worker
retry must resolve that exact key. It cannot silently select the currently active
key or regenerate a missing one.

Missing key material with an initialization marker fails. If the entire private
directory or artifact volume is lost, persisted v3 artifact/derivative versions
or server ingestion pins prevent treating a DB-only restore as a new installation.
The retained version columns survive evidence-body retention. Restore the matching
key and artifact backup; do not delete markers or database provenance to silence
the failure. This check protects a retained database, not a simultaneous loss of
all database and filesystem history.

## Operator keyring and rotation

Optional `FAILURELENS_REDACTION_KEYRING` is a private JSON object mapping versioned
references to base64-encoded, cryptographically random keys of 32–256 bytes.
`FAILURELENS_REDACTION_ACTIVE_KEY_REF` must name an entry. References are restricted
ASCII identifiers of at most 96 characters; `local-v1-` is reserved. Provision
values through the deployment's secret mechanism, never an uploaded artifact,
request body, command-line argument, committed `.env`, issue or log. This project
does not supply an external secret-manager integration or publish example keys.

Settings representation/export hides the keyring; errors contain fixed codes,
never key bodies. The active reference, policy version, HMAC algorithm and project
scope are public provenance. Keep each reference permanently bound to one key;
changing material behind the same reference is an operator error the application
cannot infer. Rotation means adding a new reference and changing the active
reference on every API/worker process, while retaining old keyring entries needed
by pending jobs. Existing local-key pins can still resolve their retained local
file while a configured operator key is active. Retiring/removing an entry blocks
fresh derivation for work pinned to it. No automatic bulk reprocessing occurs.

A rotation deliberately starts a new correlation epoch. It does not promise that
pseudonyms from different epochs join, and it can fragment identity-based history.
Choose the rotation boundary explicitly and preserve the previous epoch's records.
No public endpoint generates, displays, downloads, rotates or deletes these keys.

## Evidence provenance and verification

New immutable safe JSON bytes and their derivative metadata record policy version,
algorithm, project ID, nonsecret key reference/source, marker caveats and redacted
classes. Trace indices also record the same project-key provenance. No root or
project key material is included in evidence, source maps, job payloads, API
schemas, telemetry or report exports.

The publication validator compares v3 policy/scope metadata with the digest-bound
payload in addition to existing digest, scope, locator and semantic checks. It
**does not load a secret key to verify an existing derivative**. Old approved
citations therefore remain verifiable after key rotation/retirement, provided
their bytes, approval and retention state still pass the existing checks.
Historical v1/v2 derivatives retain their original validation/provenance contract;
this change does not certify their old pseudonyms as keyed or revoke exports.

## Backups and recovery

The existing whole-artifact-root backup includes the private key directory, while
the existing database backup retains public key references. The resulting archive
is sensitive operational backup material: keep it permission-restricted, encrypted
and access-controlled separately from normal evidence exports. Restore database,
artifacts, key files/markers and correct ownership/permissions together. Securely
back up operator-managed keys using the deployment's secret-management process.
Copying only safe derivatives is sufficient to verify those retained citations,
but is insufficient to resume the same ingestion correlation epoch.

Key deletion cannot retract downloaded evidence, exported pseudonyms or backups.
This is not encrypted retained-original storage, universal erasure or a substitute
for the source/evidence retention policy.

## Regression evidence

`backend/tests/test_project_redaction.py` covers project/key/reference isolation,
determinism, child-process restart, concurrent atomic initialization, context
isolation/reset, no-key direct parsing, marker preservation, transaction/amount/
status distinctions, file permissions/symlinks/size/corruption, reserved-namespace
reads, normalized and durable parser/trace integration, forged client provenance,
key loss/DB-only restore, queued rotation/retirement and key-free citation checks.
Existing transaction, domain, contract, trace and evidence validation suites remain
separate compatibility gates. These are synthetic privacy regressions, not renewed
held-out classifier acceptance or a universal redaction claim.
