"""Answer-free replay view and separate evaluation-only labels for a frozen campaign."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal['product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence']
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
CaseId = Annotated[str, Field(pattern=r'^c-[0-9a-f]{20}$')]
CATEGORIES = ('product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Input(Strict):
    path: str
    sha256: Digest
    bytes: Annotated[int, Field(gt=0, le=1024*1024)]
    source_format: Literal['junit-xml', 'failurelens-bundle-v2'] = 'junit-xml'
    expected_inputs: Annotated[int, Field(ge=1, le=16)] = 1

    @field_validator('path')
    @classmethod
    def safe(cls, value):
        p = PurePosixPath(value)
        if p.is_absolute() or len(p.parts) != 2 or '..' in p.parts or '\\' in value or str(p) != value or p.suffix not in {'.xml', '.zip'}:
            raise ValueError('unsafe campaign artifact path')
        return value


class Review(Strict):
    category: Literal['known_flake']
    reason: Annotated[str, Field(min_length=20, max_length=2000)]
    recorded_at: str
    provenance: Literal['synthetic_agent_reviewed_fixture']


class HistoricalInput(Strict):
    artifact: Input
    observed_at: str
    review: Review | None = None


class PublicCase(Strict):
    case_id: CaseId
    repository: Annotated[str, Field(pattern=r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    source_revision: Annotated[str, Field(min_length=1, max_length=160)]
    observed_at: str
    observation: Input
    control: Input | None = None
    history: Annotated[list[HistoricalInput], Field(max_length=10)] = Field(default_factory=list)


class PublicManifest(Strict):
    schema_version: Literal['campaign-input-v1']
    cases: Annotated[list[PublicCase], Field(min_length=1, max_length=1000)]


class CaseLabel(Strict):
    schema_version: Literal['campaign-case-v1']
    case_id: CaseId
    source_kind: Literal['ledgerguard_executed', 'synthetic', 'other_executed']
    source_revision: str
    scenario_family_id: str
    incident_id: str
    artifacts: list[str]
    history_manifest: str | None
    expected_category: Category
    root_cause: str | None
    required_evidence: list[str]
    forbidden_claims: list[str]
    severity: Literal['critical', 'high', 'medium', 'low']
    observability_rationale: str
    oracle: str
    adversarial_tags: list[str]
    label_provenance: str
    label_review_status: Literal['agent-reviewed', 'human-reviewed', 'automated']
    split: Literal['development', 'calibration', 'test']
    variant: Annotated[int, Field(ge=0, le=20)]
    family_group: str
    reused_development: bool
    claim_rubric: Literal['bounded-classification-v1', 'bounded-contract-v1']


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('campaign timestamps require a timezone')
    return result


def bounded_read(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError('expected a regular campaign data file')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('campaign data exceeds resource limit')
    return data


def read_input(root: Path, item: Input) -> bytes:
    path = root / item.path
    if any(p.is_symlink() for p in (root, path.parent, path)) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('campaign artifact escapes public input view')
    data = bounded_read(path, 1024*1024)
    if len(data) != item.bytes or digest(data) != item.sha256:
        raise ValueError('campaign artifact digest or length changed')
    return data


def load_public(root: Path) -> PublicManifest:
    manifest = PublicManifest.model_validate_json(bounded_read(root/'manifest.json', 2*1024*1024))
    ids, paths = set(), set()
    for case in manifest.cases:
        if case.case_id in ids:
            raise ValueError('duplicate campaign case')
        ids.add(case.case_id)
        timestamp(case.observed_at)
        references = [case.observation] + ([case.control] if case.control else [])
        for event in case.history:
            stamp = timestamp(event.observed_at)
            if event.review:
                if timestamp(event.review.recorded_at) <= stamp:
                    raise ValueError('review predates its observation')
            references.append(event.artifact)
        for ref in references:
            if ref.path in paths or PurePosixPath(ref.path).parts[0] != case.case_id:
                raise ValueError('duplicate or cross-case campaign artifact')
            paths.add(ref.path)
            if (ref.source_format == 'junit-xml') != ref.path.endswith('.xml'):
                raise ValueError('artifact format and extension differ')
            read_input(root, ref)
    return manifest


def audit(root: Path, *, enforce_minimums: bool = True) -> tuple[dict, list[CaseLabel], PublicManifest]:
    """Separate evaluator: validate labels and frozen groups without altering them."""
    frozen = json.loads(bounded_read(root/'freeze.json', 2*1024*1024))
    if frozen.get('version') != 'campaign-freeze-v1':
        raise ValueError('invalid frozen campaign version')
    for name in ['inputs/manifest.json', 'labels.json', 'policy.json', 'families.json']:
        if digest(bounded_read(root/name, 4*1024*1024)) != frozen['files'][name]:
            raise ValueError('frozen campaign metadata changed: ' + name)
    public = load_public(root/'inputs')
    labels = [CaseLabel.model_validate(v) for v in json.loads(bounded_read(root/'labels.json', 4*1024*1024))]
    by_id = {row.case_id: row for row in labels}
    if len(by_id) != len(labels) or set(by_id) != {c.case_id for c in public.cases}:
        raise ValueError('missing, duplicate or unexpected campaign labels')
    groups, mechanism_groups = defaultdict(set), defaultdict(set)
    byte_groups = defaultdict(set)
    for case in public.cases:
        label = by_id[case.case_id]
        if label.source_revision != case.source_revision or label.artifacts != [case.observation.path]:
            raise ValueError('label/source input identity differs')
        expected_history = digest(canonical([h.model_dump() for h in case.history])) if case.history else None
        if label.history_manifest != expected_history:
            raise ValueError('history manifest digest differs from labelled context')
        if label.source_kind == 'ledgerguard_executed' and (label.split != 'development' or not label.reused_development or case.control is None):
            raise ValueError('retained inspected executions are development-only paired evidence')
        if label.reused_development and label.split != 'development':
            raise ValueError('inspected development cases cannot be held out')
        if label.expected_category == 'known_flake':
            prior = [h for h in case.history if timestamp(h.observed_at) < timestamp(case.observed_at)]
            if len(prior) < 5 or not any(h.review and timestamp(h.review.recorded_at) < timestamp(case.observed_at) for h in prior):
                raise ValueError('known-flake labels require prior reviewed observations')
        groups[label.family_group].add(label.split)
        mechanism_groups[label.scenario_family_id].add(label.family_group)
        # Only a duplicate/normalization tripwire, not automatic conceptual
        # adjudication. Broader family review remains explicitly agent-authored.
        data = read_input(root/'inputs', case.observation)
        if case.observation.source_format == 'junit-xml':
            text = re.sub(r'c-[0-9a-f]{20}|[0-9a-f]{32,64}|\d+', '#', data.decode())
            byte_groups[digest(text.encode())].add(label.split)
    if any(len(v) > 1 for v in groups.values()) or any(len(v) > 1 for v in mechanism_groups.values()):
        raise ValueError('family or mechanism crosses frozen split boundary')
    if any(len(v) > 1 for v in byte_groups.values()):
        raise ValueError('normalized observation duplicate crosses splits')
    families = json.loads(bounded_read(root/'families.json', 4*1024*1024))
    catalog = {f['family_group']: f for f in families}
    if len(catalog) != len(families) or set(catalog) != set(groups):
        raise ValueError('family catalogue is duplicated or incomplete')
    for group, entries in groups.items():
        expected_cases = {l.case_id for l in labels if l.family_group == group}
        record = catalog[group]
        if (record['split'] not in entries or set(record['cases']) != expected_cases
                or len(record['cases']) != len(expected_cases)
                or record.get('review_status') != 'agent-reviewed'
                or record.get('independent_expert_adjudication') is not False):
            raise ValueError('family catalogue does not match labelled cases/review provenance')
    counts = Counter(l.expected_category for l in labels)
    test = [l for l in labels if l.split == 'test']
    test_products = [l for l in test if l.expected_category == 'product_defect']
    executed = [l for l in labels if l.source_kind == 'ledgerguard_executed']
    gates = dict(cases_at_least_200=len(labels) >= 200, families_at_least_80=len(groups) >= 80,
        category_minimums=counts['product_defect'] >= 80 and all(counts[c] >= 30 for c in CATEGORIES[1:]),
        test_cases_at_least_100=len(test) >= 100, test_products_at_least_40=len(test_products) >= 40,
        test_product_families_at_least_20=len({l.family_group for l in test_products}) >= 20,
        retained_executed_cases_at_least_60=len(executed) >= 60,
        retained_executed_families_at_least_15=len({l.family_group for l in executed}) >= 15)
    if enforce_minimums and not all(gates.values()):
        raise ValueError('campaign minimums failed: ' + str(gates))
    summary = dict(case_count=len(labels), family_count=len(groups), category_counts=dict(counts), minimums=gates,
        split_counts=dict(Counter(l.split for l in labels)), source_counts=dict(Counter(l.source_kind for l in labels)),
        by_split={s: dict(Counter(l.expected_category for l in labels if l.split == s)) for s in ['development', 'calibration', 'test']},
        public_manifest_sha256=frozen['files']['inputs/manifest.json'], freeze_sha256=digest(bounded_read(root/'freeze.json', 2*1024*1024)),
        family_review='agent-reviewed catalogue; structural leakage checks are not independent expert adjudication')
    return summary, labels, public
