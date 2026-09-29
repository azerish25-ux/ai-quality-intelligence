# Explainable failure clustering

## Purpose and safety boundary

Loose Thread clusters failures that are useful to investigate together. A cluster is not proof of one root cause, a causal graph, or permission to dismiss product risk. Current-run validated evidence and contradiction policy remain authoritative for classification.

The implementation is deterministic and CPU-only. Every persisted cluster identifies the exact feature and algorithm versions that produced it:

- feature view: `cluster-features-v1:fingerprint-v1`;
- algorithm: `explainable-complete-link-v1`.

## Feature extraction

The strict fingerprint remains the high-precision identity for nearly identical failures. Clustering uses a separate readable feature view containing:

- normalized message tokens;
- exception type and exception family;
- canonical API route, HTTP method and status;
- failed selector;
- assertion text plus direction/negation signature;
- normalized stack-frame paths;
- test source path and logical identity; and
- browser dimension.

UUIDs, timestamps, random ports, source line numbers and route identifiers are normalized when they are nuisance values. Important distinctions such as HTTP `401` versus `500`, selector identity, endpoint ownership, assertion operator and assertion negation remain intact.

## Two-stage algorithm

### 1. Bounded candidate generation

Stable blocks create a small candidate set from strict fingerprint, exception family, canonical route, selector, assertion, leading stack frame and selected normalized message tokens. Every block is capped at 200 members before pair expansion. Oversized exact-fingerprint cohorts retain a linear representative star and exact-key complete-link inference; other oversized blocks are skipped until a more selective shared signal exists.

### 2. Explainable multi-signal scoring

Every candidate pair records individual score components plus matching and conflicting signals. Positive components include exact fingerprint, normalized-message overlap, compatible exception, route/method/status, selector, assertion, stack frames, source path, logical identity and corroborated cross-browser reproduction.

Hard conflicts prevent grouping even when generic text looks similar:

- authorization status (`401`/`403`) versus server failure (`5xx`);
- generic selector timeouts with different selectors; and
- incompatible assertion direction or negation.

A new member must meet the representative assignment threshold (`0.62`) and the complete-link floor (`0.50`) against every existing member. Therefore A resembling B and B resembling C is not enough when A and C conflict or lack sufficient common evidence.

## Persistence and revisions

The relational model contains:

- `failure_clusters`: stable identity and current state;
- `cluster_revisions`: immutable revision metadata and uncertainty;
- `cluster_memberships`: revision-scoped members, scores and explanations; and
- `cluster_membership_decisions`: reviewed confirm/split/merge history.

Reprocessing unchanged project failures is idempotent. Algorithm or membership changes append a revision. Old memberships remain queryable. Superseded clusters retain their identity and may point to one replacement cluster when the transition is unambiguous.

Human-reviewed clusters are protected from automatic rewrites. A reviewed split creates a new locked cluster for the selected proper subset; a merge appends the union to the target and supersedes the source. Optimistic revision checks reject stale corrections.

## Uncertainty

The current revision exposes explicit flags:

- `singleton_outlier`;
- `conservative_boundary`;
- `conflicting_signals_retained`;
- `mixed_exception_types`; and
- `human_reviewed_membership`.

Outliers remain visible as singleton clusters. Downstream-looking failures are still counted independently. No upstream/downstream relationship is created from timing alone.

## Evaluation

`evaluation/generate_clustering_corpus.py` creates 24 synthetic observations with 13 evaluation-only incident labels. The labels and oracle rationales are never passed into feature extraction or clustering. The fixture includes:

- dynamic IDs, timestamps and line numbers;
- cross-browser positives;
- `401` versus `503` collisions;
- generic timeout/different-selector negatives;
- assertion direction and negation negatives;
- an A–B–C bridge case; and
- singleton outliers.

`evaluation/clustering_harness.py` reports pairwise precision/recall, false merges, false splits and adjusted Rand index. The committed controlled result is perfect on this intentionally compact fixture. It is an agent-authored regression benchmark, not an independent or production-representative performance claim.

## API and dashboard

The project/run cluster lists, cluster detail, revision history and review operation are documented in `docs/api-and-cli.md`. The dashboard’s **Failure clusters** workspace exposes the same persisted data: representative, scores, matching/conflicting signals, uncertainty, revisions and reviewed correction controls.
