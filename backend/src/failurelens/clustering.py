from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from .fingerprint import NORMALIZATION_VERSION, normalize_message
from .models import (
    ClusterMembership,
    ClusterMembershipDecision,
    ClusterRevision,
    Failure,
    FailureCluster,
)

FEATURE_VERSION = f"cluster-features-v1:{NORMALIZATION_VERSION}"
ALGORITHM_VERSION = "explainable-complete-link-v1"
ASSIGNMENT_THRESHOLD = 0.62
COMPLETE_LINK_FLOOR = 0.50
MAX_CANDIDATE_BLOCK = 200

_TOKEN = re.compile(r"[a-z0-9_./:-]{3,}")
_UUID_SEGMENT = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)
_ROUTE_ID = re.compile(r"(?<=/)(?:\d{2,}|[0-9a-f]{16,})(?=/|$)", re.I)
_STACK_PATH = re.compile(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)(?::\d+)?")

_STOPWORDS = {
    "after",
    "before",
    "because",
    "could",
    "error",
    "failed",
    "failure",
    "from",
    "into",
    "operation",
    "should",
    "test",
    "that",
    "this",
    "timeout",
    "waiting",
    "with",
}

_AUTH_STATUSES = {401, 403}
_SERVER_STATUSES = {500, 501, 502, 503, 504}


@dataclass(frozen=True)
class FailureFeature:
    failure_id: str
    project_id: str
    run_id: str
    stable_order: tuple[str, ...]
    strict_fingerprint: str
    normalized_message: str
    message_tokens: frozenset[str]
    exception_type: str
    exception_family: str
    route: str | None
    method: str | None
    http_status: int | None
    selector: str | None
    assertion: str | None
    assertion_signature: tuple[str, bool]
    stack_frames: tuple[str, ...]
    source_path: str | None
    browser: str | None
    test_identity: str


@dataclass(frozen=True)
class PairScore:
    total: float
    components: dict[str, float]
    matching_signals: tuple[str, ...]
    conflicting_signals: tuple[str, ...]
    candidate_reasons: tuple[str, ...]
    hard_conflict: bool


@dataclass(frozen=True)
class ProposedMember:
    feature: FailureFeature
    score: PairScore
    role: str


@dataclass(frozen=True)
class ProposedCluster:
    cluster_key: str
    representative: FailureFeature
    members: tuple[ProposedMember, ...]
    uncertainty_flags: tuple[str, ...]
    score_summary: dict[str, Any]

    @property
    def failure_ids(self) -> tuple[str, ...]:
        return tuple(member.feature.failure_id for member in self.members)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _canonical_route(value: Any) -> str | None:
    route = _text(value)
    if route is None:
        return None
    route = route.casefold().split("?", 1)[0]
    route = _UUID_SEGMENT.sub("<uuid>", route)
    route = _ROUTE_ID.sub("<id>", route)
    return route


def _canonical_selector(value: Any) -> str | None:
    selector = _text(value)
    if selector is None:
        return None
    return re.sub(r"\s+", " ", selector.casefold())[:1000]


def _canonical_assertion(value: Any) -> str | None:
    assertion = _text(value)
    if assertion is None:
        return None
    return re.sub(r"\s+", " ", assertion.casefold())[:2000]


def _assertion_signature(value: str | None) -> tuple[str, bool]:
    if value is None:
        return ("none", False)
    negated = bool(re.search(r"\bnot\b|!=|not\.|\.not\b|false\b", value))
    if ">=" in value:
        operator = ">="
    elif "<=" in value:
        operator = "<="
    elif "!=" in value:
        operator = "!="
    elif "==" in value or "equal" in value or "expected" in value:
        operator = "=="
    elif ">" in value:
        operator = ">"
    elif "<" in value:
        operator = "<"
    else:
        operator = "other"
    return operator, negated


def _exception_family(value: str) -> str:
    leaf = value.rsplit(".", 1)[-1].casefold()
    return re.sub(r"(?:error|exception|failure)$", "", leaf) or leaf or "unknown"


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _TOKEN.findall(value.casefold())
        if token not in _STOPWORDS
        and token not in {"uuid", "timestamp", "line", "hex", "port"}
    )


def _flatten_stack(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        for match in _STACK_PATH.findall(value):
            yield match.replace("\\", "/").casefold()
    elif isinstance(value, dict):
        for key in ("file", "path", "function", "frame", "location"):
            if key in value:
                yield from _flatten_stack(value[key])
        for key, item in value.items():
            if key not in {"file", "path", "function", "frame", "location"}:
                yield from _flatten_stack(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_stack(item)


def feature_from_observation(
    *,
    failure_id: str,
    project_id: str,
    run_id: str,
    repository: str | None,
    external_id: str,
    run_attempt: int,
    strict_fingerprint: str,
    message: str,
    exception_type: str | None,
    details: dict[str, Any] | None,
    loose_features: dict[str, Any] | None,
    source_path: str | None,
    browser: str | None,
    test_identity: str,
) -> FailureFeature:
    """Build the exact versioned clustering view from observable failure values.

    Keeping this adapter independent of SQLAlchemy lets the frozen clustering
    evaluation exercise the production feature pipeline without constructing a
    database or consuming oracle labels at runtime.
    """
    details = details if isinstance(details, dict) else {}
    loose = loose_features if isinstance(loose_features, dict) else {}
    normalized = _text(loose.get("message")) or normalize_message(message)
    exception_type = (
        _text(exception_type)
        or _text(loose.get("exception_type"))
        or "unknown"
    ).casefold()
    route = _canonical_route(details.get("route") or loose.get("route"))
    method = _text(details.get("method") or details.get("http_method"))
    method = method.casefold() if method else None
    status = _integer(details.get("http_status") or loose.get("http_status"))
    selector = _canonical_selector(details.get("selector") or loose.get("selector"))
    assertion = _canonical_assertion(details.get("assertion") or loose.get("assertion"))
    stack_source = (
        details.get("stack_frames")
        or details.get("stack")
        or details.get("traceback")
        or details.get("error_stack")
        or []
    )
    stack_frames = tuple(dict.fromkeys(_flatten_stack(stack_source)))[:40]
    normalized_identity = test_identity.casefold()
    stable_order = (
        (repository or "").casefold(),
        external_id.casefold(),
        f"{run_attempt:08d}",
        normalized_identity,
        strict_fingerprint,
        normalized,
        failure_id,
    )
    return FailureFeature(
        failure_id=failure_id,
        project_id=project_id,
        run_id=run_id,
        stable_order=stable_order,
        strict_fingerprint=strict_fingerprint,
        normalized_message=normalized,
        message_tokens=_tokens(normalized),
        exception_type=exception_type,
        exception_family=_exception_family(exception_type),
        route=route,
        method=method,
        http_status=status,
        selector=selector,
        assertion=assertion,
        assertion_signature=_assertion_signature(assertion),
        stack_frames=stack_frames,
        source_path=(source_path.casefold() if source_path else None),
        browser=(browser.casefold() if browser else None),
        test_identity=normalized_identity,
    )


def feature_from_failure(failure: Failure) -> FailureFeature:
    execution = failure.execution
    run = failure.run
    return feature_from_observation(
        failure_id=failure.id,
        project_id=failure.project_id,
        run_id=failure.run_id,
        repository=run.repository,
        external_id=run.external_id,
        run_attempt=run.attempt,
        strict_fingerprint=failure.strict_fingerprint,
        message=failure.message,
        exception_type=failure.exception_type,
        details=execution.details if isinstance(execution.details, dict) else {},
        loose_features=(
            failure.loose_features
            if isinstance(failure.loose_features, dict)
            else {}
        ),
        source_path=execution.source_path,
        browser=execution.browser,
        test_identity=execution.test_identity,
    )


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def _status_class(status: int | None) -> int | None:
    return status // 100 if status is not None else None


def candidate_keys(feature: FailureFeature) -> tuple[str, ...]:
    keys = {
        f"strict:{feature.strict_fingerprint}",
        f"exception:{feature.exception_family}",
    }
    if feature.route:
        keys.add(f"route:{feature.method or '*'}:{feature.route}")
    if feature.selector:
        keys.add(f"selector:{feature.selector}")
    if feature.assertion:
        keys.add(f"assertion:{feature.assertion}")
    if feature.stack_frames:
        keys.add(f"frame:{feature.stack_frames[0]}")
    for token in sorted(feature.message_tokens)[:8]:
        keys.add(f"token:{token}")
    return tuple(sorted(keys))


def generate_candidate_pairs(
    features: Sequence[FailureFeature],
) -> dict[tuple[str, str], tuple[str, ...]]:
    blocks: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        for key in candidate_keys(feature):
            blocks[key].append(feature.failure_id)

    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, ids in blocks.items():
        unique_ids = sorted(set(ids))
        if len(unique_ids) > MAX_CANDIDATE_BLOCK:
            # A high-cardinality block must not expand into quadratic pair
            # storage. Exact fingerprints retain one representative edge per
            # member; get_score can safely infer the same exact-key reason for
            # complete-link checks inside that cohort. Other broad blocks are
            # skipped and require a second, more selective shared signal.
            if key.startswith("strict:"):
                representative = unique_ids[0]
                for member in unique_ids[1:]:
                    reasons[(representative, member)].add(key)
            continue
        for left, right in combinations(unique_ids, 2):
            reasons[(left, right)].add(key)
    return {pair: tuple(sorted(values)) for pair, values in reasons.items()}


def score_features(
    left: FailureFeature,
    right: FailureFeature,
    *,
    candidate_reasons: Sequence[str] = (),
) -> PairScore:
    components: dict[str, float] = {}
    matches: list[str] = []
    conflicts: list[str] = []
    hard_conflict = False

    if left.strict_fingerprint == right.strict_fingerprint:
        components["strict_fingerprint"] = 0.50
        matches.append("strict fingerprint matches")

    message_similarity = _jaccard(left.message_tokens, right.message_tokens)
    if message_similarity:
        components["message_tokens"] = round(0.28 * message_similarity, 6)
        if message_similarity >= 0.6:
            matches.append(f"normalized message tokens overlap ({message_similarity:.2f})")

    if left.exception_type == right.exception_type and left.exception_type != "unknown":
        components["exception_type"] = 0.10
        matches.append("exception type matches")
    elif left.exception_family == right.exception_family and left.exception_family != "unknown":
        components["exception_family"] = 0.05
        matches.append("exception family matches")
    elif left.exception_type != "unknown" and right.exception_type != "unknown":
        components["exception_conflict"] = -0.08
        conflicts.append("exception types differ")

    if left.route and right.route:
        if left.route == right.route:
            components["route"] = 0.10
            matches.append("API route matches")
        else:
            components["route_conflict"] = -0.08
            conflicts.append("API routes differ")

    if left.method and right.method:
        if left.method == right.method:
            components["http_method"] = 0.04
            matches.append("HTTP method matches")
        else:
            components["http_method_conflict"] = -0.06
            conflicts.append("HTTP methods differ")

    if left.http_status is not None and right.http_status is not None:
        if left.http_status == right.http_status:
            components["http_status"] = 0.08
            matches.append(f"HTTP status {left.http_status} matches")
        elif (
            left.http_status in _AUTH_STATUSES
            and right.http_status in _SERVER_STATUSES
        ) or (
            right.http_status in _AUTH_STATUSES
            and left.http_status in _SERVER_STATUSES
        ):
            components["http_status_conflict"] = -0.28
            conflicts.append(
                f"authorization status {min(left.http_status, right.http_status)} conflicts with server failure status {max(left.http_status, right.http_status)}"
            )
            hard_conflict = True
        elif _status_class(left.http_status) != _status_class(right.http_status):
            components["http_status_class_conflict"] = -0.15
            conflicts.append("HTTP status classes differ")
        else:
            components["http_status_difference"] = -0.05
            conflicts.append("HTTP statuses differ")

    if left.selector and right.selector:
        if left.selector == right.selector:
            components["selector"] = 0.10
            matches.append("failed selector matches")
        else:
            components["selector_conflict"] = -0.22
            conflicts.append("failed selectors differ")
            generic_timeout = (
                "timeout" in left.normalized_message
                and "timeout" in right.normalized_message
            )
            if generic_timeout:
                hard_conflict = True
                conflicts.append("generic timeout cannot bridge different selectors")

    if left.assertion and right.assertion:
        if left.assertion == right.assertion:
            components["assertion"] = 0.10
            matches.append("assertion structure matches")
        else:
            left_operator, left_negated = left.assertion_signature
            right_operator, right_negated = right.assertion_signature
            contradictory = (
                left_negated != right_negated
                or (
                    left_operator != right_operator
                    and {left_operator, right_operator}
                    & {">", "<", ">=", "<=", "==", "!="}
                )
            )
            if contradictory:
                components["assertion_direction_conflict"] = -0.28
                conflicts.append("assertion direction or negation conflicts")
                hard_conflict = True
            else:
                components["assertion_difference"] = -0.12
                conflicts.append("assertions differ")

    stack_similarity = _jaccard(left.stack_frames, right.stack_frames)
    if stack_similarity:
        components["stack_frames"] = round(0.14 * stack_similarity, 6)
        if stack_similarity >= 0.5:
            matches.append(f"normalized stack frames overlap ({stack_similarity:.2f})")

    if left.source_path and right.source_path:
        if left.source_path == right.source_path:
            components["source_path"] = 0.05
            matches.append("test source path matches")
        elif left.test_identity == right.test_identity:
            components["source_path_conflict"] = -0.04
            conflicts.append("same test identity reports different source paths")

    identity_similarity = _jaccard(_tokens(left.test_identity), _tokens(right.test_identity))
    if identity_similarity:
        components["test_identity"] = round(0.04 * identity_similarity, 6)

    subtotal = sum(components.values())
    if left.browser and right.browser:
        if left.browser == right.browser:
            components["browser_context"] = 0.01
        elif subtotal >= 0.45:
            components["cross_browser_corroboration"] = 0.02
            matches.append("similar failure reproduced across browsers")

    total = max(0.0, min(1.0, sum(components.values())))
    return PairScore(
        total=round(total, 6),
        components={key: round(value, 6) for key, value in sorted(components.items())},
        matching_signals=tuple(sorted(set(matches))),
        conflicting_signals=tuple(sorted(set(conflicts))),
        candidate_reasons=tuple(sorted(set(candidate_reasons))),
        hard_conflict=hard_conflict,
    )


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))  # type: ignore[return-value]


def _cluster_key(representative: FailureFeature) -> str:
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "feature_version": FEATURE_VERSION,
        "strict_fingerprint": representative.strict_fingerprint,
        "exception_family": representative.exception_family,
        "route": representative.route,
        "selector": representative.selector,
        "assertion": representative.assertion,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _representative_score() -> PairScore:
    return PairScore(
        total=1.0,
        components={"representative": 1.0},
        matching_signals=("cluster representative",),
        conflicting_signals=(),
        candidate_reasons=("deterministic representative",),
        hard_conflict=False,
    )


def _proposal_from_group(
    group: Sequence[FailureFeature],
    candidate_map: dict[tuple[str, str], tuple[str, ...]],
    score_cache: dict[tuple[str, str], PairScore],
    *,
    forced: bool = False,
) -> ProposedCluster:
    ordered = sorted(group, key=lambda item: item.stable_order)
    representative = ordered[0]
    members: list[ProposedMember] = [
        ProposedMember(representative, _representative_score(), "representative")
    ]
    scores: list[float] = []
    conflicts: set[str] = set()
    for feature in ordered[1:]:
        key = _pair_key(representative.failure_id, feature.failure_id)
        score = score_cache.get(key)
        if score is None:
            score = score_features(
                representative,
                feature,
                candidate_reasons=candidate_map.get(key, ("human review override",) if forced else ()),
            )
            score_cache[key] = score
        members.append(ProposedMember(feature, score, "member"))
        scores.append(score.total)
        conflicts.update(score.conflicting_signals)

    flags: list[str] = []
    if len(ordered) == 1:
        flags.append("singleton_outlier")
    if scores and min(scores) < 0.72:
        flags.append("conservative_boundary")
    if conflicts:
        flags.append("conflicting_signals_retained")
    if len({item.exception_type for item in ordered}) > 1:
        flags.append("mixed_exception_types")
    if forced:
        flags.append("human_reviewed_membership")
    summary = {
        "assignment_threshold": ASSIGNMENT_THRESHOLD,
        "complete_link_floor": COMPLETE_LINK_FLOOR,
        "member_scores": len(scores),
        "minimum_similarity": round(min(scores), 6) if scores else 1.0,
        "average_similarity": round(sum(scores) / len(scores), 6) if scores else 1.0,
        "maximum_similarity": round(max(scores), 6) if scores else 1.0,
        "conflict_count": len(conflicts),
        "forced_by_review": forced,
    }
    return ProposedCluster(
        cluster_key=_cluster_key(representative),
        representative=representative,
        members=tuple(members),
        uncertainty_flags=tuple(sorted(set(flags))),
        score_summary=summary,
    )


def propose_clusters_from_features(
    features: Sequence[FailureFeature],
) -> tuple[ProposedCluster, ...]:
    ordered = sorted(features, key=lambda item: item.stable_order)
    if not ordered:
        return tuple()
    candidate_map = generate_candidate_pairs(ordered)
    by_id = {feature.failure_id: feature for feature in ordered}
    score_cache: dict[tuple[str, str], PairScore] = {}

    def get_score(left: FailureFeature, right: FailureFeature) -> PairScore | None:
        key = _pair_key(left.failure_id, right.failure_id)
        reasons = candidate_map.get(key)
        if reasons is None and left.strict_fingerprint == right.strict_fingerprint:
            reasons = (f"strict:{left.strict_fingerprint}",)
        if reasons is None:
            return None
        if key not in score_cache:
            score_cache[key] = score_features(left, right, candidate_reasons=reasons)
        return score_cache[key]

    groups: list[list[FailureFeature]] = []
    for feature in ordered:
        eligible: list[tuple[float, float, tuple[str, ...], int]] = []
        for index, group in enumerate(groups):
            representative = group[0]
            representative_score = get_score(feature, representative)
            if (
                representative_score is None
                or representative_score.hard_conflict
                or representative_score.total < ASSIGNMENT_THRESHOLD
            ):
                continue
            all_scores: list[float] = []
            coherent = True
            for member in group:
                member_score = get_score(feature, member)
                if (
                    member_score is None
                    or member_score.hard_conflict
                    or member_score.total < COMPLETE_LINK_FLOOR
                ):
                    coherent = False
                    break
                all_scores.append(member_score.total)
            if coherent:
                eligible.append(
                    (
                        min(all_scores),
                        sum(all_scores) / len(all_scores),
                        representative.stable_order,
                        index,
                    )
                )
        if not eligible:
            groups.append([feature])
            continue
        # Highest complete-link floor, then average similarity, then the stable
        # representative order. Negating is avoided to keep tuple semantics clear.
        eligible.sort(key=lambda item: (-item[0], -item[1], item[2]))
        groups[eligible[0][3]].append(feature)

    proposals = [
        _proposal_from_group(group, candidate_map, score_cache) for group in groups
    ]
    return tuple(sorted(proposals, key=lambda item: item.representative.stable_order))


def propose_clusters(failures: Sequence[Failure]) -> tuple[ProposedCluster, ...]:
    return propose_clusters_from_features([feature_from_failure(item) for item in failures])


def _current_revision(session: Session, cluster: FailureCluster) -> ClusterRevision | None:
    return session.scalar(
        select(ClusterRevision).where(
            ClusterRevision.cluster_id == cluster.id,
            ClusterRevision.revision == cluster.current_revision,
        )
    )


def current_memberships(
    session: Session, cluster: FailureCluster
) -> list[ClusterMembership]:
    revision = _current_revision(session, cluster)
    if revision is None:
        return []
    return list(
        session.scalars(
            select(ClusterMembership)
            .where(ClusterMembership.revision_id == revision.id)
            .options(
                selectinload(ClusterMembership.failure).selectinload(Failure.execution),
                selectinload(ClusterMembership.failure).selectinload(Failure.run),
            )
            .order_by(ClusterMembership.role.desc(), ClusterMembership.failure_id)
        ).all()
    )


def _uncertainty_value(flags: Sequence[str]) -> str:
    if "singleton_outlier" in flags:
        return "singleton"
    if "conflicting_signals_retained" in flags or "mixed_exception_types" in flags:
        return "mixed"
    if "conservative_boundary" in flags:
        return "boundary"
    return "low"


def _write_revision(
    session: Session,
    cluster: FailureCluster,
    proposal: ProposedCluster | None,
    *,
    reason: str,
    assignment_kind: str,
) -> ClusterRevision:
    revision_number = cluster.current_revision + 1 if cluster.current_revision else 1
    members = proposal.members if proposal is not None else tuple()
    representative_id = proposal.representative.failure_id if proposal else None
    flags = proposal.uncertainty_flags if proposal else ("superseded",)
    summary = proposal.score_summary if proposal else {"member_scores": 0}
    revision = ClusterRevision(
        cluster_id=cluster.id,
        revision=revision_number,
        reason=reason,
        algorithm_version=ALGORITHM_VERSION,
        feature_version=FEATURE_VERSION,
        representative_failure_id=representative_id,
        member_count=len(members),
        score_summary=summary,
        uncertainty_flags=list(flags),
    )
    session.add(revision)
    session.flush()
    for member in members:
        session.add(
            ClusterMembership(
                cluster_id=cluster.id,
                revision_id=revision.id,
                failure_id=member.feature.failure_id,
                role=member.role,
                similarity_score=member.score.total,
                score_components=member.score.components,
                matching_signals=list(member.score.matching_signals),
                conflicting_signals=list(member.score.conflicting_signals),
                candidate_reasons=list(member.score.candidate_reasons),
                assignment_kind=assignment_kind,
            )
        )
    cluster.current_revision = revision_number
    cluster.representative_failure_id = representative_id
    cluster.member_count = len(members)
    cluster.uncertainty = _uncertainty_value(flags)
    cluster.algorithm_version = ALGORITHM_VERSION
    cluster.feature_version = FEATURE_VERSION
    return revision


def _create_cluster(
    session: Session,
    project_id: str,
    proposal: ProposedCluster,
    *,
    reason: str,
    assignment_kind: str,
    cluster_key: str | None = None,
) -> FailureCluster:
    base_key = cluster_key or proposal.cluster_key
    key = base_key
    salt = "|".join(proposal.failure_ids)
    collision_index = 0
    while session.scalar(
        select(FailureCluster.id).where(
            FailureCluster.project_id == project_id,
            FailureCluster.cluster_key == key,
        )
    ):
        collision_index += 1
        key = hashlib.sha256(
            f"{base_key}|{salt}|{collision_index}".encode("utf-8")
        ).hexdigest()
    cluster = FailureCluster(
        project_id=project_id,
        cluster_key=key,
        algorithm_version=ALGORITHM_VERSION,
        feature_version=FEATURE_VERSION,
        current_revision=0,
        representative_failure_id=None,
        member_count=0,
        uncertainty="none",
        status="active",
    )
    session.add(cluster)
    session.flush()
    _write_revision(
        session,
        cluster,
        proposal,
        reason=reason,
        assignment_kind=assignment_kind,
    )
    return cluster


def _member_set(session: Session, cluster: FailureCluster) -> set[str]:
    return {item.failure_id for item in current_memberships(session, cluster)}


def cluster_project_failures(
    session: Session,
    project_id: str,
    *,
    commit: bool = True,
) -> list[FailureCluster]:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        # Clustering rewrites one project's active identity set as a unit. A
        # transaction-scoped advisory lock prevents concurrent workers from
        # racing to create the same deterministic cluster key or revision.
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(CAST(:project_id AS text), 0))"
            ),
            {"project_id": project_id},
        )

    failures = list(
        session.scalars(
            select(Failure)
            .where(Failure.project_id == project_id)
            .options(selectinload(Failure.execution), selectinload(Failure.run))
        ).all()
    )
    active_clusters = list(
        session.scalars(
            select(FailureCluster)
            .where(
                FailureCluster.project_id == project_id,
                FailureCluster.status == "active",
            )
            .order_by(FailureCluster.created_at, FailureCluster.id)
        ).all()
    )

    locked_clusters: list[FailureCluster] = []
    automatic_clusters: list[FailureCluster] = []
    locked_failure_ids: set[str] = set()
    existing_sets: dict[str, set[str]] = {}
    for cluster in active_clusters:
        revision = _current_revision(session, cluster)
        members = _member_set(session, cluster)
        existing_sets[cluster.id] = members
        if revision is not None and revision.reason.startswith("human_"):
            locked_clusters.append(cluster)
            locked_failure_ids.update(members)
        else:
            automatic_clusters.append(cluster)

    eligible_failures = [
        failure for failure in failures if failure.id not in locked_failure_ids
    ]
    proposals = list(propose_clusters(eligible_failures))

    # Match proposed groups to existing automatic clusters by maximum overlap.
    # One-to-one matching preserves cluster identity while permitting merges and
    # splits to become append-only revisions.
    used_existing: set[str] = set()
    matches: dict[int, FailureCluster] = {}
    ranked_proposals = sorted(
        enumerate(proposals),
        key=lambda item: (-len(item[1].failure_ids), item[1].cluster_key),
    )
    for proposal_index, proposal in ranked_proposals:
        proposal_ids = set(proposal.failure_ids)
        candidates: list[tuple[int, float, str, FailureCluster]] = []
        for cluster in automatic_clusters:
            if cluster.id in used_existing:
                continue
            current_ids = existing_sets.get(cluster.id, set())
            overlap = len(proposal_ids & current_ids)
            if overlap == 0:
                continue
            union = len(proposal_ids | current_ids)
            candidates.append((overlap, overlap / union, cluster.id, cluster))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
            selected = candidates[0][3]
            used_existing.add(selected.id)
            matches[proposal_index] = selected

    resulting: list[FailureCluster] = [*locked_clusters]
    proposal_cluster_ids: dict[str, str] = {}
    for index, proposal in enumerate(proposals):
        cluster = matches.get(index)
        proposal_ids = set(proposal.failure_ids)
        if cluster is None:
            cluster = _create_cluster(
                session,
                project_id,
                proposal,
                reason="automatic_recluster",
                assignment_kind="automatic",
            )
        else:
            current_ids = existing_sets.get(cluster.id, set())
            unchanged = (
                current_ids == proposal_ids
                and cluster.representative_failure_id
                == proposal.representative.failure_id
                and cluster.algorithm_version == ALGORITHM_VERSION
                and cluster.feature_version == FEATURE_VERSION
            )
            if not unchanged:
                _write_revision(
                    session,
                    cluster,
                    proposal,
                    reason="automatic_recluster",
                    assignment_kind="automatic",
                )
            cluster.status = "active"
            cluster.superseded_by_cluster_id = None
        resulting.append(cluster)
        for failure_id in proposal.failure_ids:
            proposal_cluster_ids[failure_id] = cluster.id

    for cluster in automatic_clusters:
        if cluster.id in used_existing:
            continue
        old_ids = existing_sets.get(cluster.id, set())
        destinations = {
            proposal_cluster_ids[failure_id]
            for failure_id in old_ids
            if failure_id in proposal_cluster_ids
        }
        cluster.status = "superseded"
        cluster.superseded_by_cluster_id = (
            next(iter(destinations)) if len(destinations) == 1 else None
        )
        _write_revision(
            session,
            cluster,
            None,
            reason="automatic_superseded",
            assignment_kind="automatic",
        )

    if commit:
        session.commit()
        for cluster in resulting:
            session.refresh(cluster)
    else:
        session.flush()
    return sorted(resulting, key=lambda item: (item.status != "active", item.cluster_key))


def _forced_proposal(failures: Sequence[Failure]) -> ProposedCluster:
    features = sorted(
        (feature_from_failure(failure) for failure in failures),
        key=lambda item: item.stable_order,
    )
    if not features:
        raise ValueError("cluster revision must contain at least one failure")
    candidate_map = generate_candidate_pairs(features)
    return _proposal_from_group(features, candidate_map, {}, forced=True)


def review_cluster(
    session: Session,
    cluster: FailureCluster,
    *,
    actor: str,
    decision: str,
    reason: str,
    expected_revision: int,
    failure_ids: Sequence[str] = (),
    target_cluster_id: str | None = None,
) -> ClusterMembershipDecision:
    if cluster.status != "active":
        raise ValueError("only active clusters can be reviewed")
    if cluster.current_revision != expected_revision:
        raise ValueError(
            f"cluster revision conflict: expected {expected_revision}, current {cluster.current_revision}"
        )
    current = current_memberships(session, cluster)
    current_failures = {item.failure_id: item.failure for item in current}
    revision_before = cluster.current_revision

    if decision == "confirm":
        affected_failure_ids = set(current_failures)
        proposal = _forced_proposal(list(current_failures.values()))
        revision = _write_revision(
            session,
            cluster,
            proposal,
            reason="human_confirm",
            assignment_kind="reviewed",
        )
        target: FailureCluster | None = None
    elif decision == "split":
        selected_ids = set(failure_ids)
        if not selected_ids or not selected_ids < set(current_failures):
            raise ValueError(
                "split requires a non-empty proper subset of current cluster failure IDs"
            )
        if not selected_ids.issubset(current_failures):
            raise ValueError("split contains a failure outside the current cluster")
        remaining = [
            failure
            for failure_id, failure in current_failures.items()
            if failure_id not in selected_ids
        ]
        selected = [current_failures[failure_id] for failure_id in selected_ids]
        affected_failure_ids = selected_ids
        source_proposal = _forced_proposal(remaining)
        revision = _write_revision(
            session,
            cluster,
            source_proposal,
            reason="human_split",
            assignment_kind="reviewed",
        )
        split_proposal = _forced_proposal(selected)
        split_key = hashlib.sha256(
            (
                f"human-split|{cluster.id}|{revision_before}|"
                + "|".join(sorted(selected_ids))
            ).encode("utf-8")
        ).hexdigest()
        target = _create_cluster(
            session,
            cluster.project_id,
            split_proposal,
            reason="human_split",
            assignment_kind="reviewed",
            cluster_key=split_key,
        )
    elif decision == "merge":
        if not target_cluster_id or target_cluster_id == cluster.id:
            raise ValueError("merge requires a distinct target cluster")
        target = session.get(FailureCluster, target_cluster_id)
        if (
            target is None
            or target.project_id != cluster.project_id
            or target.status != "active"
        ):
            raise ValueError("merge target must be an active cluster in the same project")
        target_members = current_memberships(session, target)
        affected_failure_ids = set(current_failures)
        union: dict[str, Failure] = {
            item.failure_id: item.failure for item in [*current, *target_members]
        }
        target_proposal = _forced_proposal(list(union.values()))
        _write_revision(
            session,
            target,
            target_proposal,
            reason="human_merge",
            assignment_kind="reviewed",
        )
        cluster.status = "superseded"
        cluster.superseded_by_cluster_id = target.id
        revision = _write_revision(
            session,
            cluster,
            None,
            reason="human_merge_superseded",
            assignment_kind="reviewed",
        )
    else:
        raise ValueError(f"unsupported cluster review decision: {decision}")

    event = ClusterMembershipDecision(
        cluster_id=cluster.id,
        target_cluster_id=target.id if target is not None else None,
        actor=actor,
        decision=decision,
        reason=reason,
        failure_ids=sorted(affected_failure_ids),
        revision_before=revision_before,
        revision_after=revision.revision,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def pairwise_cluster_metrics(
    predicted: dict[str, str], truth: dict[str, str]
) -> dict[str, float | int]:
    ids = sorted(truth)
    missing_predictions = sorted(set(truth) - set(predicted))
    unexpected_predictions = sorted(set(predicted) - set(truth))

    def predicted_label(item_id: str) -> str:
        # A missing output behaves as its own singleton, so omitted members
        # cannot disappear from recall or ARI calculations.
        return predicted.get(item_id, f"__missing__:{item_id}")

    true_positive = false_positive = false_negative = true_negative = 0
    for left, right in combinations(ids, 2):
        predicted_same = predicted_label(left) == predicted_label(right)
        truth_same = truth[left] == truth[right]
        if predicted_same and truth_same:
            true_positive += 1
        elif predicted_same and not truth_same:
            false_positive += 1
        elif not predicted_same and truth_same:
            false_negative += 1
        else:
            true_negative += 1
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )

    # Adjusted Rand index from the pair-count form.
    total_pairs = math.comb(len(ids), 2) if len(ids) >= 2 else 0
    predicted_positive = true_positive + false_positive
    truth_positive = true_positive + false_negative
    expected_index = (
        predicted_positive * truth_positive / total_pairs if total_pairs else 0.0
    )
    max_index = (predicted_positive + truth_positive) / 2
    denominator = max_index - expected_index
    adjusted_rand = (
        (true_positive - expected_index) / denominator
        if denominator
        else 1.0
    )
    return {
        "case_count": len(ids),
        "pairwise_precision": round(precision, 6),
        "pairwise_recall": round(recall, 6),
        "false_merges": false_positive,
        "false_splits": false_negative,
        "true_negative_pairs": true_negative,
        "adjusted_rand_index": round(adjusted_rand, 6),
        "missing_predictions": len(missing_predictions),
        "unexpected_predictions": len(unexpected_predictions),
    }
