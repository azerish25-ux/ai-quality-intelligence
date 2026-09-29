import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type MouseEvent } from 'react';
import {
  api,
  operations,
  type AuditEvent,
  type Category,
  type ClusterDetail,
  type ClusterRevision,
  type ClusterSummary,
  type Failure,
  type HealthStatus,
  type Ingestion,
  type ImpactMappingInput,
  type ImpactMappingSnapshot,
  type ImpactRecommendation,
  type ImpactRecommendationItem,
  type InfrastructureCorrelation,
  type IngestionTokenRecord,
  type Overview,
  type PerformanceComparison,
  type PerformanceObservation,
  type PerformancePolicy,
  type Principal,
  type Project,
  type ProjectMembership,
  type ProjectRole,
  type ReviewEvent,
  type ReviewQueueItem,
  type Run,
  type RunInput,
  type TestHistory
} from './api';
import { AccountPanel, RecoveryForm, RetentionPanel } from './Operations';
import { BinaryEvidencePanel } from './BinaryEvidence';
import { EvaluationPanel } from './EvaluationPanel';

const categoryLabel: Record<string, string> = {
  product_defect: 'Probable product defect',
  test_defect: 'Probable test defect',
  infrastructure_failure: 'Infrastructure / environment',
  known_flake: 'Known flaky behavior',
  insufficient_evidence: 'Insufficient evidence'
};

const ingestionLabel: Record<string, string> = {
  queued: 'Queued',
  running: 'Processing',
  succeeded: 'Succeeded',
  partial: 'Partial',
  failed: 'Failed',
  cancelled: 'Cancelled',
  dead_lettered: 'Dead-lettered'
};

const roleRank: Record<ProjectRole, number> = {
  viewer: 1,
  reviewer: 2,
  administrator: 3
};

const statusClass = (value: string): string => value.replaceAll('_', '-');
const terminalIngestionStates = new Set(['succeeded', 'partial', 'failed', 'cancelled', 'dead_lettered']);

const formatRate = (rate: TestHistory['rates'][string] | undefined): string => {
  if (!rate || rate.value === null) return `Unavailable (${rate?.numerator ?? 0}/${rate?.denominator ?? 0})`;
  return `${(rate.value * 100).toFixed(1)}% (${rate.numerator}/${rate.denominator})`;
};

const readableValue = (value: string): string => value.replaceAll('_', ' ');
const performanceStatusClass = (value: string): string => statusClass(value.toLowerCase());
const formatPerformanceValue = (value: number | null, unit: string): string => {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  return `${new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value)} ${unit}`;
};
const formatPerformanceDelta = (value: number | null): string => {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
};

const newExternalId = (): string => `manual-${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;
const tablePageSize = 10;

const searchParam = (key: string): string => new URLSearchParams(window.location.search).get(key) ?? '';
const searchPage = (key: string): number => {
  const value = Number(searchParam(key));
  return Number.isInteger(value) && value > 0 ? value : 1;
};
const searchChoice = <T extends string>(key: string, values: readonly T[], fallback: T): T => {
  const value = searchParam(key) as T;
  return values.includes(value) ? value : fallback;
};
const downloadText = (filename: string, value: string, mediaType: string): void => {
  const url = URL.createObjectURL(new Blob([value], { type: mediaType }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
};

const defaultImpactMapping = JSON.stringify({
  version: 'mapping-v1',
  policy_version: 'impact-policy-v1',
  trusted: true,
  coverage_complete: true,
  source_metadata: {
    generator: 'reviewed repository mapping',
    note: 'Replace this example with trusted coverage, ownership, or dependency data.'
  },
  tests: [
    {
      test_key: 'critical-smoke',
      test_identity: 'tests/smoke.spec.ts::critical smoke',
      source_path: 'tests/smoke.spec.ts',
      criticality: 'critical',
      mandatory: true,
      tags: ['smoke', 'security'],
      estimated_duration_ms: 500
    },
    {
      test_key: 'checkout',
      test_identity: 'tests/checkout.spec.ts::submits payment',
      source_path: 'tests/checkout.spec.ts',
      criticality: 'high',
      mandatory: false,
      tags: ['checkout'],
      estimated_duration_ms: 1200
    },
    {
      test_key: 'profile',
      test_identity: 'tests/profile.spec.ts::updates avatar',
      source_path: 'tests/profile.spec.ts',
      criticality: 'normal',
      mandatory: false,
      tags: ['profile'],
      estimated_duration_ms: 1800
    }
  ],
  edges: [
    {
      source_path: 'src/checkout.py',
      target_type: 'test',
      target_value: 'checkout',
      kind: 'coverage',
      confidence: 0.95,
      mapping_source: 'reviewed coverage export',
      mapping_version: 'coverage-v1'
    }
  ]
}, null, 2);

function App() {
  const authGeneration = useRef(0);
  const rootRequest = useRef(0);
  const projectRequest = useRef(0);
  const selectionIntent = useRef({ projectId: searchParam('project'), runId: searchParam('run') });
  const [navigationRevision, setNavigationRevision] = useState(0);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(() => searchParam('project'));
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState(() => searchParam('run'));
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [watchedIngestionId, setWatchedIngestionId] = useState<string | null>(null);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [runInputs, setRunInputs] = useState<RunInput[]>([]);
  const [performancePolicies, setPerformancePolicies] = useState<PerformancePolicy[]>([]);
  const [performancePolicyId, setPerformancePolicyId] = useState('');
  const [performanceObservations, setPerformanceObservations] = useState<PerformanceObservation[]>([]);
  const [performanceComparisons, setPerformanceComparisons] = useState<PerformanceComparison[]>([]);
  const [performanceLoading, setPerformanceLoading] = useState(false);
  const [impactMappings, setImpactMappings] = useState<ImpactMappingSnapshot[]>([]);
  const [impactMappingId, setImpactMappingId] = useState('');
  const [impactRecommendations, setImpactRecommendations] = useState<ImpactRecommendation[]>([]);
  const [selectedImpactId, setSelectedImpactId] = useState(() => searchParam('impact'));
  const [selectedImpact, setSelectedImpact] = useState<ImpactRecommendation | null>(null);
  const [impactMappingJson, setImpactMappingJson] = useState(defaultImpactMapping);
  const [impactReviewReason, setImpactReviewReason] = useState('');
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [runClusters, setRunClusters] = useState<ClusterSummary[]>([]);
  const [selectedClusterId, setSelectedClusterId] = useState(() => searchParam('cluster'));
  const [selectedCluster, setSelectedCluster] = useState<ClusterDetail | null>(null);
  const [clusterRevisions, setClusterRevisions] = useState<ClusterRevision[]>([]);
  const [selectedClusterMembers, setSelectedClusterMembers] = useState<string[]>([]);
  const [clusterReviewReason, setClusterReviewReason] = useState('');
  const [mergeTargetId, setMergeTargetId] = useState('');
  const [selectedFailureId, setSelectedFailureId] = useState(() => searchParam('failure'));
  const [testHistory, setTestHistory] = useState<TestHistory | null>(null);
  const [infrastructureSnapshot, setInfrastructureSnapshot] = useState<InfrastructureCorrelation | null>(null);
  const [infrastructureLoading, setInfrastructureLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyRunScope, setHistoryRunScope] = useState(
    () => new URLSearchParams(window.location.search).get('history_scope') ?? ''
  );
  const [historyBrowser, setHistoryBrowser] = useState(
    () => new URLSearchParams(window.location.search).get('history_browser') ?? ''
  );
  const [historyBranch, setHistoryBranch] = useState(
    () => new URLSearchParams(window.location.search).get('history_branch') ?? ''
  );
  const [historyEnvironment, setHistoryEnvironment] = useState(
    () => new URLSearchParams(window.location.search).get('history_environment') ?? ''
  );
  const [historyWorkerCount, setHistoryWorkerCount] = useState(
    () => new URLSearchParams(window.location.search).get('history_workers') ?? ''
  );
  const [historyShardCount, setHistoryShardCount] = useState(
    () => new URLSearchParams(window.location.search).get('history_shards') ?? ''
  );
  const [campaignEvaluation, setCampaignEvaluation] = useState<Record<string, unknown> | null>(null);
  const [fullstackEvaluation, setFullstackEvaluation] = useState<Record<string, unknown> | null>(null);
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [reviewTotal, setReviewTotal] = useState<number | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [governanceRevision, setGovernanceRevision] = useState(0);
  const [reviewStatusFilter, setReviewStatusFilter] = useState<'all' | 'pending' | 'reviewed'>(
    () => searchChoice('review_status', ['all', 'pending', 'reviewed'] as const, 'pending')
  );
  const [reviewCategoryFilter, setReviewCategoryFilter] = useState<'all' | Category>(
    () => searchChoice(
      'review_category',
      ['all', 'product_defect', 'test_defect', 'infrastructure_failure', 'known_flake', 'insufficient_evidence'] as const,
      'all'
    )
  );
  const [reviewSearch, setReviewSearch] = useState(() => searchParam('review_search'));
  const [reviewSort, setReviewSort] = useState<'newest' | 'oldest' | 'severity' | 'test'>(
    () => searchChoice('review_sort', ['newest', 'oldest', 'severity', 'test'] as const, 'newest')
  );
  const [reviewPage, setReviewPage] = useState(() => searchPage('review_page'));
  const [analysisReviews, setAnalysisReviews] = useState<ReviewEvent[]>([]);
  const [reviewDecision, setReviewDecision] = useState<'accept' | 'reject' | 'needs_more_evidence' | 'category_correction'>('needs_more_evidence');
  const [reviewCategory, setReviewCategory] = useState<Category>('insufficient_evidence');
  const [reviewReason, setReviewReason] = useState('');
  const [reviewOutcome, setReviewOutcome] = useState('');
  const [reviewReleaseAdvice, setReviewReleaseAdvice] = useState<'HOLD_FOR_REVIEW' | 'INVESTIGATE' | 'NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE'>('INVESTIGATE');
  const [members, setMembers] = useState<ProjectMembership[]>([]);
  const [ingestionTokens, setIngestionTokens] = useState<IngestionTokenRecord[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState<number | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditActions, setAuditActions] = useState<string[]>([]);
  const [auditOutcomes, setAuditOutcomes] = useState<string[]>([]);
  const [auditExportEnabled, setAuditExportEnabled] = useState(false);
  const [auditSearch, setAuditSearch] = useState(() => searchParam('audit_search'));
  const [auditActionFilter, setAuditActionFilter] = useState(() => searchParam('audit_action'));
  const [auditOutcomeFilter, setAuditOutcomeFilter] = useState(() => searchParam('audit_outcome'));
  const [auditSort, setAuditSort] = useState<'newest' | 'oldest'>(
    () => searchChoice('audit_sort', ['newest', 'oldest'] as const, 'newest')
  );
  const [auditPage, setAuditPage] = useState(() => searchPage('audit_page'));
  const [systemHealth, setSystemHealth] = useState<{
    live: HealthStatus | null;
    ready: HealthStatus | null;
    checkedAt: string | null;
    error: string | null;
  }>({ live: null, ready: null, checkedAt: null, error: null });
  const [healthLoading, setHealthLoading] = useState(false);
  const [memberUsername, setMemberUsername] = useState('');
  const [memberRole, setMemberRole] = useState<ProjectRole>('viewer');
  const [tokenName, setTokenName] = useState('');
  const [newTokenSecret, setNewTokenSecret] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState(newExternalId);
  const [uploadRunScope, setUploadRunScope] = useState<'full_suite' | 'impact_selected' | 'unknown'>('unknown');
  const [uploadEnvironment, setUploadEnvironment] = useState('');
  const [expectedInputs, setExpectedInputs] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState('');

  const changeProject = useCallback((id: string, requestedRunId = '', requestedFailureId = '') => {
    projectRequest.current += 1;
    selectionIntent.current = { projectId: id, runId: requestedRunId };
    setProjectId(id); setRunId(requestedRunId); setRuns([]); setIngestions([]);
    setFailures([]); setRunInputs([]); setRunClusters([]); setClusters([]);
    setSelectedFailureId(requestedFailureId); setSelectedClusterId(''); setSelectedCluster(null);
    setSelectedImpactId(''); setSelectedImpact(null); setImpactMappings([]); setImpactRecommendations([]);
    setPerformancePolicies([]); setPerformanceObservations([]); setPerformanceComparisons([]);
    setTestHistory(null); setInfrastructureSnapshot(null); setAnalysisReviews([]);
    setMembers([]); setIngestionTokens([]); setNewTokenSecret(null); setWatchedIngestionId(null);
    setReviewQueue([]); setReviewTotal(null); setAuditEvents([]); setAuditTotal(null);
    setRunError(null); setError(null);
    setNavigationRevision(value => value + 1);
  }, []);

  const changeRun = (id: string) => {
    selectionIntent.current = { projectId, runId: id };
    setRunId(id); setSelectedFailureId(''); setSelectedClusterId('');
    setFailures([]); setRunInputs([]); setRunClusters([]); setTestHistory(null);
    setPerformanceObservations([]); setPerformanceComparisons([]); setRunError(null);
    // Reopening an already selected run must reload the panels we just cleared.
    setNavigationRevision(value => value + 1);
  };

  const navigateSection = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = document.getElementById(event.currentTarget.hash.slice(1));
    if (!target) return;
    event.preventDefault();
    event.currentTarget.closest('details')?.removeAttribute('open');
    const url = new URL(window.location.href);
    url.hash = event.currentTarget.hash;
    // An in-page anchor is not a project/run navigation. Native hash history
    // would invoke popstate while asynchronous panels are still settling.
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: 'instant', block: 'start' });
  };

  const currentRole = useMemo<ProjectRole | null>(() => {
    if (!principal) return null;
    if (principal.system_admin || principal.kind === 'demo') return 'administrator';
    return principal.memberships.find((membership) => membership.project_id === projectId)?.role ?? null;
  }, [principal, projectId]);
  const canReview = currentRole !== null && roleRank[currentRole] >= roleRank.reviewer;
  const canAdminister = currentRole === 'administrator';
  const selectedFailure = useMemo(
    () => failures.find((failure) => failure.id === selectedFailureId) ?? null,
    [failures, selectedFailureId]
  );
  const navigationItems = useMemo(() => [
    { href: '#overview', label: 'Overview' },
    { href: '#ingestion', label: 'Ingestion' },
    { href: '#runs', label: 'Runs' },
    { href: '#impact', label: 'Change impact' },
    { href: '#performance', label: 'Performance' },
    { href: '#clusters', label: 'Clusters' },
    { href: '#workspace', label: 'Failure workspace' },
    { href: '#history', label: 'Test history' },
    ...(canReview ? [{ href: '#reviews', label: 'Review queue' }] : []),
    { href: '#account', label: 'Account security' },
    ...(canAdminister ? [{ href: '#settings', label: 'Settings' }] : []),
    ...(canReview ? [{ href: '#audit', label: 'Audit' }] : []),
    { href: '#evaluation', label: 'Evaluation' }
  ], [canAdminister, canReview]);

  const reviewPageCount = Math.max(1, Math.ceil((reviewTotal ?? 0) / tablePageSize));
  const pagedReviewQueue = reviewQueue;
  const auditPageCount = Math.max(1, Math.ceil((auditTotal ?? 0) / tablePageSize));
  const pagedAuditEvents = auditEvents;
  const governanceChanged = useCallback(() => setGovernanceRevision(value => value + 1), []);

  useEffect(() => {
    if (!principal || !projectId || !canReview) {
      setReviewQueue([]); setReviewTotal(null); return;
    }
    const controller = new AbortController();
    setReviewLoading(true);
    operations.reviewPage(projectId, {
      status: reviewStatusFilter, category: reviewCategoryFilter === 'all' ? undefined : reviewCategoryFilter,
      search: reviewSearch, sort: reviewSort, limit: tablePageSize, offset: (reviewPage - 1) * tablePageSize
    }, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setReviewQueue(page.items); setReviewTotal(page.total);
    }).catch(reason => { if (!controller.signal.aborted) { setError(String(reason)); setReviewQueue([]); } })
      .finally(() => { if (!controller.signal.aborted) setReviewLoading(false); });
    return () => controller.abort();
  }, [principal, projectId, canReview, reviewStatusFilter, reviewCategoryFilter, reviewSearch, reviewSort, reviewPage, governanceRevision]);

  useEffect(() => {
    if (!principal || !projectId || !canReview) {
      setAuditEvents([]); setAuditTotal(null); setAuditExportEnabled(false); return;
    }
    const controller = new AbortController();
    setAuditLoading(true);
    operations.auditPage(projectId, {
      action: auditActionFilter, outcome: auditOutcomeFilter, search: auditSearch, sort: auditSort,
      limit: tablePageSize, offset: (auditPage - 1) * tablePageSize
    }, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setAuditEvents(page.items); setAuditTotal(page.total); setAuditActions(page.actions);
      setAuditOutcomes(page.outcomes); setAuditExportEnabled(page.export_enabled);
    }).catch(reason => { if (!controller.signal.aborted) { setError(String(reason)); setAuditEvents([]); } })
      .finally(() => { if (!controller.signal.aborted) setAuditLoading(false); });
    return () => controller.abort();
  }, [principal, projectId, canReview, auditActionFilter, auditOutcomeFilter, auditSearch, auditSort, auditPage, governanceRevision]);

  const refreshSystemHealth = useCallback(async () => {
    setHealthLoading(true);
    const [live, ready] = await Promise.allSettled([api.healthLive(), api.healthReady()]);
    const errors = [live, ready]
      .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
      .map((result) => String(result.reason));
    setSystemHealth({
      live: live.status === 'fulfilled' ? live.value : null,
      ready: ready.status === 'fulfilled' ? ready.value : null,
      checkedAt: new Date().toISOString(),
      error: errors.length > 0 ? errors.join(' · ') : null
    });
    setStatusMessage(errors.length > 0 ? 'System health check completed with errors.' : 'System health check completed.');
    setHealthLoading(false);
  }, []);

  const refreshRoot = useCallback(async () => {
    const generation = authGeneration.current;
    const request = ++rootRequest.current;
    const [nextOverview, nextProjects, evaluationResponse, fullstackResponse, campaignResponse] = await Promise.all([
      api.overview(),
      api.projects(),
      api.evaluation(),
      api.fullstackEvaluation(),
      api.campaignEvaluation()
    ]);
    if (generation !== authGeneration.current || request !== rootRequest.current) return;
    setOverview(nextOverview);
    setProjects(nextProjects);
    setEvaluation(evaluationResponse.metrics ?? null);
    setFullstackEvaluation(fullstackResponse.metrics ?? null);
    setCampaignEvaluation(campaignResponse.metrics ?? null);
    const intendedProject = selectionIntent.current.projectId;
    if (intendedProject && !nextProjects.some(project => project.id === intendedProject)) {
      setError('Requested project is unavailable or you do not have access. Select an available project.');
    }
    setProjectId(current => intendedProject || current || nextProjects[0]?.id || '');
  }, []);

  const refreshProject = useCallback(async (nextProjectId: string, preferredRunId?: string | null) => {
    const generation = authGeneration.current;
    const request = ++projectRequest.current;
    if (preferredRunId !== undefined) {
      if (selectionIntent.current.runId !== preferredRunId) setSelectedFailureId('');
      selectionIntent.current = { projectId: nextProjectId, runId: preferredRunId ?? '' };
    }
    // Capture intent before awaiting requests. The URL can change during a
    // seed, reload or Back/Forward transition and is not an async data store.
    const requestedRunId = preferredRunId ?? (
      selectionIntent.current.projectId === nextProjectId ? selectionIntent.current.runId : ''
    );
    if (!nextProjectId) {
      setRuns([]);
      setIngestions([]);
      setClusters([]);
      setRunClusters([]);
      setImpactMappings([]);
      setImpactRecommendations([]);
      setPerformancePolicies([]);
      setPerformancePolicyId('');
      setPerformanceObservations([]);
      setPerformanceComparisons([]);
      setImpactMappingId('');
      setSelectedImpactId('');
      setSelectedImpact(null);
      setSelectedClusterId('');
      setSelectedCluster(null);
      setSelectedFailureId('');
      setRunId('');
      return;
    }
    const [nextRuns, nextIngestions, nextClusters, nextMappings, nextImpactRecommendations, nextPerformancePolicies] = await Promise.all([
      api.runs(nextProjectId),
      api.ingestions(nextProjectId),
      api.clusters(nextProjectId),
      api.impactMappings(nextProjectId),
      api.impactRecommendations(nextProjectId),
      api.performancePolicies(nextProjectId)
    ]);
    if (requestedRunId && !nextRuns.some(run => run.id === requestedRunId)) {
      try {
        const olderRun = await operations.run(requestedRunId);
        if (olderRun.project_id === nextProjectId) nextRuns.push(olderRun);
      } catch { /* An unavailable or unauthorized URL cannot add a run to this project. */ }
    }
    if (generation !== authGeneration.current || request !== projectRequest.current) return;
    setRuns(nextRuns);
    setIngestions(nextIngestions);
    setClusters(nextClusters);
    setImpactMappings(nextMappings);
    setImpactRecommendations(nextImpactRecommendations);
    setPerformancePolicies(nextPerformancePolicies);
    setPerformancePolicyId((current) => {
      if (current && nextPerformancePolicies.some((policy) => policy.id === current)) return current;
      return nextPerformancePolicies[0]?.id ?? '';
    });
    setImpactMappingId((current) => {
      if (current && nextMappings.some((mapping) => mapping.id === current)) return current;
      return nextMappings[0]?.id ?? '';
    });
    setSelectedImpactId((current) => {
      if (current && nextImpactRecommendations.some((item) => item.id === current)) return current;
      return nextImpactRecommendations[0]?.id ?? '';
    });
    setSelectedClusterId((current) => {
      if (current && nextClusters.some((cluster) => cluster.id === current)) return current;
      return nextClusters[0]?.id ?? '';
    });
    const currentIntent = selectionIntent.current;
    const nextRunId = currentIntent.projectId === nextProjectId && currentIntent.runId
      ? currentIntent.runId
      : requestedRunId || nextRuns[0]?.id || '';
    selectionIntent.current = { projectId: nextProjectId, runId: nextRunId };
    // Keep a requested ID even when unavailable; the run resolver will show an
    // explicit error rather than quietly opening an unrelated investigation.
    setRunId(nextRunId);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setAuthLoading(true);
    api.me()
      .then(async (nextPrincipal) => {
        if (cancelled) return;
        await refreshRoot();
        if (!cancelled) setPrincipal(nextPrincipal);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        const message = String(reason);
        if (!message.startsWith('401 ')) setError(message);
        setPrincipal(null);
      })
      .finally(() => {
        if (!cancelled) setAuthLoading(false);
      });
    return () => { cancelled = true; };
  }, [refreshRoot]);

  useEffect(() => {
    if (!principal || !projects.some(project => project.id === projectId)) return;
    refreshProject(projectId).catch((reason: unknown) => setError(String(reason)));
  }, [principal, projectId, projects, refreshProject, governanceRevision, navigationRevision]);

  useEffect(() => {
    if (!principal || !projectId) {
      setReviewQueue([]);
      setMembers([]);
      setIngestionTokens([]);
      setAuditEvents([]);
      return;
    }
    let cancelled = false;
    const tasks: Promise<void>[] = [];
    if (canAdminister) {
      tasks.push(
        Promise.all([api.projectMembers(projectId), api.ingestionTokens(projectId)]).then(
          ([nextMembers, nextTokens]) => {
            if (!cancelled) {
              setMembers(nextMembers);
              setIngestionTokens(nextTokens);
            }
          }
        )
      );
    } else {
      setMembers([]);
      setIngestionTokens([]);
    }
    Promise.all(tasks).catch((reason: unknown) => {
      if (!cancelled) setError(String(reason));
    });
    return () => { cancelled = true; };
  }, [canAdminister, canReview, principal, projectId]);

  useEffect(() => {
    if (!principal) return;
    void refreshSystemHealth();
  }, [principal, refreshSystemHealth]);

  useEffect(() => {
    const analysisId = selectedFailure?.latest_analysis?.analysis_id;
    if (!principal || !analysisId) {
      setAnalysisReviews([]);
      return;
    }
    let cancelled = false;
    api.analysisReviews(analysisId)
      .then((events) => {
        if (!cancelled) setAnalysisReviews(events);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(String(reason));
      });
    return () => { cancelled = true; };
  }, [principal, selectedFailure?.latest_analysis?.analysis_id, governanceRevision]);

  useEffect(() => {
    if (!principal || !projectId || !runId) {
      setFailures([]); setRunInputs([]); setRunClusters([]);
      setPerformanceObservations([]); setPerformanceComparisons([]);
      setPerformanceLoading(false); setRunLoading(false);
      return;
    }
    let cancelled = false;
    const generation = authGeneration.current;
    const isCurrent = () => !cancelled && generation === authGeneration.current &&
      selectionIntent.current.projectId === projectId && selectionIntent.current.runId === runId;
    setRunLoading(true); setRunError(null); setPerformanceLoading(true);
    operations.run(runId).then(async openedRun => {
      if (!isCurrent()) return;
      if (openedRun.project_id !== projectId) throw new Error('Run does not belong to the selected project.');
      const [nextFailures, nextInputs, nextRunClusters, nextPerformanceObservations, nextPerformanceComparisons] = await Promise.all([
        api.failures(runId), api.runInputs(runId), api.runClusters(runId),
        api.performanceObservations(runId), api.performanceComparisons(runId)
      ]);
      if (!isCurrent()) return;
      setRuns(current => [...current.filter(run => run.project_id === projectId && run.id !== runId), openedRun]);
      setFailures(nextFailures); setRunInputs(nextInputs); setRunClusters(nextRunClusters);
      setPerformanceObservations(nextPerformanceObservations); setPerformanceComparisons(nextPerformanceComparisons);
      setSelectedClusterId(current => current && nextRunClusters.some(cluster => cluster.id === current)
        ? current : nextRunClusters[0]?.id ?? '');
      setSelectedFailureId(current => current || nextFailures[0]?.id || '');
    }).catch((reason: unknown) => {
      if (!isCurrent()) return;
      setFailures([]); setRunInputs([]); setRunClusters([]);
      setPerformanceObservations([]); setPerformanceComparisons([]);
      setRuns(current => current.filter(run => run.id !== runId));
      setRunError(`Requested investigation is unavailable in this project. ${String(reason)}`);
    }).finally(() => {
      if (isCurrent()) { setPerformanceLoading(false); setRunLoading(false); }
    });
    return () => { cancelled = true; };
  }, [principal, projectId, runId, governanceRevision, navigationRevision]);

  const hasActiveIngestion = useMemo(
    () => ingestions.some((ingestion) => !terminalIngestionStates.has(ingestion.state)),
    [ingestions]
  );

  useEffect(() => {
    if (!projectId || !hasActiveIngestion) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const nextIngestions = await api.ingestions(projectId);
        if (cancelled) return;
        setIngestions(nextIngestions);
        const watched = watchedIngestionId
          ? nextIngestions.find((item) => item.id === watchedIngestionId)
          : undefined;
        if (watched && terminalIngestionStates.has(watched.state)) {
          await Promise.all([
            refreshRoot(),
            refreshProject(projectId, watched.run_id)
          ]);
          if (!cancelled) setWatchedIngestionId(null);
        }
      } catch (reason) {
        if (!cancelled) setError(String(reason));
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [hasActiveIngestion, projectId, refreshProject, refreshRoot, watchedIngestionId]);

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === runId) ?? null,
    [runs, runId]
  );

  const infrastructureCorrelation = infrastructureSnapshot ?? testHistory?.infrastructure_correlations ?? null;

  useEffect(() => {
    const clearSession = () => {
      authGeneration.current += 1;
      selectionIntent.current = { projectId: '', runId: '' };
      rootRequest.current += 1;
      projectRequest.current += 1;
      setProjects([]); setProjectId(''); setRunId(''); setSelectedFailureId(''); setRunError(null);
      setSelectedImpactId(''); setSelectedClusterId(''); setOverview(null); setEvaluation(null); setFullstackEvaluation(null);
      setMembers([]); setIngestionTokens([]); setNewTokenSecret(null);
      setPrincipal(null); setFailures([]); setReviewQueue([]); setAuditEvents([]);
      setSelectedCluster(null); setTestHistory(null); setRuns([]); setIngestions([]);
      setAnalysisReviews([]); setPerformanceComparisons([]); setImpactRecommendations([]);
    };
    window.addEventListener('failurelens:session-expired', clearSession);
    return () => window.removeEventListener('failurelens:session-expired', clearSession);
  }, []);

  useEffect(() => {
    if (!principal || !runId || selectedRun?.evidence_expired_at) return;
    let active = true;
    const timer = window.setInterval(() => {
      operations.run(runId).then(run => {
        if (active && run.evidence_expired_at) governanceChanged();
      }).catch(() => { /* Normal API error handling reports unavailable sessions. */ });
    }, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [principal, runId, selectedRun?.evidence_expired_at, governanceChanged]);


  useEffect(() => {
    if (authLoading || !principal) return;
    const url = new URL(window.location.href);
    const values: Record<string, string> = {
      project: projectId,
      run: runId,
      failure: selectedFailureId,
      cluster: selectedClusterId,
      impact: selectedImpactId,
      history_scope: historyRunScope,
      history_browser: historyBrowser,
      history_branch: historyBranch,
      history_environment: historyEnvironment,
      history_workers: historyWorkerCount,
      history_shards: historyShardCount,
      review_status: reviewStatusFilter === 'pending' ? '' : reviewStatusFilter,
      review_category: reviewCategoryFilter === 'all' ? '' : reviewCategoryFilter,
      review_search: reviewSearch,
      review_sort: reviewSort === 'newest' ? '' : reviewSort,
      review_page: reviewPage > 1 ? String(reviewPage) : '',
      audit_search: auditSearch,
      audit_action: auditActionFilter,
      audit_outcome: auditOutcomeFilter,
      audit_sort: auditSort === 'newest' ? '' : auditSort,
      audit_page: auditPage > 1 ? String(auditPage) : ''
    };
    Object.entries(values).forEach(([key, value]) => {
      if (value.trim()) url.searchParams.set(key, value.trim());
      else url.searchParams.delete(key);
    });
    window.history.replaceState(
      null,
      '',
      `${url.pathname}${url.search}${url.hash}`
    );
  }, [
    authLoading,
    principal,
    auditActionFilter,
    auditOutcomeFilter,
    auditPage,
    auditSearch,
    auditSort,
    historyBranch,
    historyBrowser,
    historyEnvironment,
    historyRunScope,
    historyShardCount,
    historyWorkerCount,
    projectId,
    reviewCategoryFilter,
    reviewPage,
    reviewSearch,
    reviewSort,
    reviewStatusFilter,
    runId,
    selectedClusterId,
    selectedFailureId,
    selectedImpactId
  ]);

  useEffect(() => {
    const applyUrlState = () => {
      const params = new URLSearchParams(window.location.search);
      const projectFromUrl = params.get('project') ?? '';
      const runFromUrl = params.get('run') ?? '';
      const failureFromUrl = params.get('failure') ?? '';
      const clusterFromUrl = params.get('cluster') ?? '';
      const impactFromUrl = params.get('impact') ?? '';
      changeProject(projectFromUrl, runFromUrl, failureFromUrl);
      setSelectedClusterId(clusterFromUrl);
      setSelectedImpactId(impactFromUrl);
      setHistoryRunScope(params.get('history_scope') ?? '');
      setHistoryBrowser(params.get('history_browser') ?? '');
      setHistoryBranch(params.get('history_branch') ?? '');
      setHistoryEnvironment(params.get('history_environment') ?? '');
      setHistoryWorkerCount(params.get('history_workers') ?? '');
      setHistoryShardCount(params.get('history_shards') ?? '');
      const reviewStatus = params.get('review_status');
      setReviewStatusFilter(reviewStatus === 'all' || reviewStatus === 'reviewed' ? reviewStatus : 'pending');
      const reviewCategory = params.get('review_category');
      setReviewCategoryFilter(
        reviewCategory && Object.prototype.hasOwnProperty.call(categoryLabel, reviewCategory)
          ? reviewCategory as Category
          : 'all'
      );
      setReviewSearch(params.get('review_search') ?? '');
      const nextReviewSort = params.get('review_sort');
      setReviewSort(
        nextReviewSort === 'oldest' || nextReviewSort === 'severity' || nextReviewSort === 'test'
          ? nextReviewSort
          : 'newest'
      );
      const nextReviewPage = Number(params.get('review_page'));
      setReviewPage(Number.isInteger(nextReviewPage) && nextReviewPage > 0 ? nextReviewPage : 1);
      setAuditSearch(params.get('audit_search') ?? '');
      setAuditActionFilter(params.get('audit_action') ?? '');
      setAuditOutcomeFilter(params.get('audit_outcome') ?? '');
      setAuditSort(params.get('audit_sort') === 'oldest' ? 'oldest' : 'newest');
      const nextAuditPage = Number(params.get('audit_page'));
      setAuditPage(Number.isInteger(nextAuditPage) && nextAuditPage > 0 ? nextAuditPage : 1);
    };
    window.addEventListener('popstate', applyUrlState);
    return () => window.removeEventListener('popstate', applyUrlState);
  }, [changeProject]);

  useEffect(() => {
    if (reviewTotal !== null && !reviewLoading) setReviewPage((current) => Math.min(Math.max(current, 1), reviewPageCount));
  }, [reviewPageCount, reviewTotal, reviewLoading]);

  useEffect(() => {
    if (auditTotal !== null && !auditLoading) setAuditPage((current) => Math.min(Math.max(current, 1), auditPageCount));
  }, [auditPageCount, auditTotal, auditLoading]);

  useEffect(() => {
    if (!selectedFailure) {
      setTestHistory(null);
      setInfrastructureSnapshot(null);
      setHistoryLoading(false);
      return;
    }
    let cancelled = false;
    setInfrastructureSnapshot(null);
    setHistoryLoading(true);
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const workerCount = historyWorkerCount.trim()
      ? Number(historyWorkerCount)
      : undefined;
    const shardCount = historyShardCount.trim()
      ? Number(historyShardCount)
      : undefined;
    api.testHistory(selectedFailure.execution_id, {
      browser: historyBrowser.trim() || undefined,
      branch: historyBranch.trim() || undefined,
      environment: historyEnvironment.trim() || undefined,
      runScope: historyRunScope === ''
        ? undefined
        : historyRunScope as 'full_suite' | 'impact_selected' | 'unknown',
      workerCount: workerCount && workerCount > 0 ? workerCount : undefined,
      shardCount: shardCount && shardCount > 0 ? shardCount : undefined,
      timezone,
      limit: 100
    })
      .then((history) => {
        if (!cancelled) setTestHistory(history);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setTestHistory(null);
          setError(String(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    historyBranch,
    historyBrowser,
    historyEnvironment,
    historyRunScope,
    historyShardCount,
    historyWorkerCount,
    selectedFailure,
    governanceRevision
  ]);

  useEffect(() => {
    if (!selectedImpactId) {
      setSelectedImpact(null);
      return;
    }
    let cancelled = false;
    api.impactRecommendation(selectedImpactId)
      .then((recommendation) => {
        if (!cancelled) setSelectedImpact(recommendation);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedImpactId, governanceRevision]);

  const visibleClusters = useMemo(
    () => runId ? runClusters : clusters,
    [clusters, runClusters, runId]
  );

  useEffect(() => {
    if (!selectedClusterId) {
      setSelectedCluster(null);
      setClusterRevisions([]);
      setSelectedClusterMembers([]);
      return;
    }
    let cancelled = false;
    Promise.all([api.cluster(selectedClusterId), api.clusterRevisions(selectedClusterId)])
      .then(([detail, revisions]) => {
        if (cancelled) return;
        setSelectedCluster(detail);
        setClusterRevisions(revisions);
        const currentIds = new Set(detail.current?.memberships.map((member) => member.failure_id) ?? []);
        setSelectedClusterMembers((selected) => selected.filter((failureId) => currentIds.has(failureId)));
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedClusterId, governanceRevision]);

  useEffect(() => {
    const validTargets = clusters.filter(
      (cluster) => cluster.status === 'active' && cluster.id !== selectedClusterId
    );
    setMergeTargetId((current) => {
      if (current && validTargets.some((cluster) => cluster.id === current)) return current;
      return validTargets[0]?.id ?? '';
    });
  }, [clusters, selectedClusterId]);

  const seedDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      const seeded = await api.seedDemo();
      changeProject(seeded.project_id, seeded.run_id);
      await refreshRoot();
      await refreshProject(seeded.project_id, seeded.run_id);
      setStatusMessage('Synthetic demo data loaded.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const uploadArtifact = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canAdminister) {
      setError('Administrator project access is required to upload artifacts.');
      return;
    }
    if (!projectId) {
      setError('Select a project before uploading an artifact.');
      return;
    }
    if (!selectedFile) {
      setError('Choose a supported report or FailureLens manifest v2 ZIP bundle.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const expected = expectedInputs.trim() === '' ? undefined : Number(expectedInputs);
      if (expected !== undefined && (!Number.isInteger(expected) || expected < 0)) {
        throw new Error('Expected inputs must be a non-negative whole number.');
      }
      const queued = await api.upload(projectId, selectedFile, {
        externalId: externalId.trim(),
        expectedInputs: expected,
        runScope: uploadRunScope,
        environment: uploadEnvironment.trim() || undefined,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      });
      setIngestions((current) => [queued, ...current.filter((item) => item.id !== queued.id)]);
      setWatchedIngestionId(queued.id);
      setSelectedFile(null);
      setExternalId(newExternalId());
      setExpectedInputs('');
      setUploadRunScope('unknown');
      setUploadEnvironment('');
      setFileInputKey((value) => value + 1);
      await refreshRoot();
      setStatusMessage(`Ingestion ${queued.external_id} queued.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const retryIngestion = async (ingestion: Ingestion) => {
    if (!canAdminister) {
      setError('Administrator project access is required to retry an ingestion.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const queued = await api.retryIngestion(ingestion.id);
      setIngestions((current) => current.map((item) => item.id === queued.id ? queued : item));
      setWatchedIngestionId(queued.id);
      await refreshRoot();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const cancelIngestion = async (ingestion: Ingestion) => {
    if (!canAdminister) {
      setError('Administrator project access is required to cancel an ingestion.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cancelled = await api.cancelIngestion(ingestion.id);
      setIngestions((current) => current.map((item) => item.id === cancelled.id ? cancelled : item));
      if (watchedIngestionId === cancelled.id) setWatchedIngestionId(null);
      await refreshRoot();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const analyze = async (failure: Failure) => {
    if (!canReview) {
      setError('Reviewer project access is required to create an analysis revision.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const analysis = await api.analyze(failure.id);
      const next = failures.map((item) => item.id === failure.id ? { ...item, latest_analysis: analysis } : item);
      setFailures(next);
      setSelectedFailureId(failure.id);
      await refreshRoot();
      setStatusMessage(`Analysis revision created for ${failure.test_identity}.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const persistInfrastructureCorrelation = async () => {
    if (!canReview) {
      setError('Reviewer project access is required to persist an infrastructure snapshot.');
      return;
    }
    if (!selectedFailure) {
      setError('Select a failure before creating an infrastructure-correlation snapshot.');
      return;
    }
    setBusy(true);
    setInfrastructureLoading(true);
    setError(null);
    try {
      const workerCount = historyWorkerCount.trim() ? Number(historyWorkerCount) : undefined;
      const shardCount = historyShardCount.trim() ? Number(historyShardCount) : undefined;
      const snapshot = await api.createInfrastructureCorrelation(
        selectedFailure.execution_id,
        {
          browser: historyBrowser.trim() || undefined,
          branch: historyBranch.trim() || undefined,
          environment: historyEnvironment.trim() || undefined,
          run_scope: historyRunScope === ''
            ? undefined
            : historyRunScope as 'full_suite' | 'impact_selected' | 'unknown',
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
          worker_count: workerCount && workerCount > 0 ? workerCount : undefined,
          shard_count: shardCount && shardCount > 0 ? shardCount : undefined,
          window_seconds: 900,
          minimum_support: 3
        }
      );
      setInfrastructureSnapshot(snapshot);
      await refreshRoot();
      setStatusMessage('Immutable infrastructure-correlation snapshot persisted.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
      setInfrastructureLoading(false);
    }
  };

  const registerDefaultPerformancePolicy = async () => {
    if (!canAdminister) {
      setError('Administrator project access is required to register a performance policy.');
      return;
    }
    if (!projectId) {
      setError('Select a project before registering a performance policy.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const policy = await api.createPerformancePolicy(projectId, {
        version: 'performance-policy-v1',
        relative_tolerance: 0.10,
        absolute_tolerance: 0,
        min_baseline_runs: 3,
        max_baseline_age_days: 30,
        require_trusted: true
      });
      setPerformancePolicies((current) => [policy, ...current.filter((item) => item.id !== policy.id)]);
      setPerformancePolicyId(policy.id);
      setStatusMessage(`Performance policy ${policy.version} registered.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const generatePerformanceComparisons = async () => {
    if (!canReview) {
      setError('Reviewer project access is required to persist performance comparisons.');
      return;
    }
    if (!runId) {
      setError('Select a run before comparing performance observations.');
      return;
    }
    if (performanceObservations.length === 0) {
      setError('The selected run has no normalized duration or k6 performance observations.');
      return;
    }
    setBusy(true);
    setPerformanceLoading(true);
    setError(null);
    try {
      const comparisons = await api.createPerformanceComparisons(
        runId,
        performancePolicyId || undefined
      );
      setPerformanceComparisons(comparisons);
      if (projectId) {
        const policies = await api.performancePolicies(projectId);
        setPerformancePolicies(policies);
        setPerformancePolicyId((current) => current || policies[0]?.id || '');
      }
      await refreshRoot();
      setStatusMessage(`${comparisons.length} performance comparison${comparisons.length === 1 ? '' : 's'} persisted.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
      setPerformanceLoading(false);
    }
  };

  const registerImpactMapping = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canAdminister) {
      setError('Administrator project access is required to register an impact mapping.');
      return;
    }
    if (!projectId) {
      setError('Select a project before registering an impact mapping snapshot.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(impactMappingJson) as ImpactMappingInput;
      const snapshot = await api.createImpactMapping(projectId, parsed);
      setImpactMappings((current) => [snapshot, ...current.filter((item) => item.id !== snapshot.id)]);
      setImpactMappingId(snapshot.id);
      setStatusMessage(`Impact mapping ${snapshot.version} registered.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const generateImpactRecommendation = async () => {
    if (!canReview) {
      setError('Reviewer project access is required to create an impact recommendation.');
      return;
    }
    if (!projectId || !runId || !impactMappingId) {
      setError('Select a project, run, and immutable mapping snapshot before generating a recommendation.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const recommendation = await api.createImpactRecommendation(
        projectId,
        runId,
        impactMappingId,
        undefined,
        selectedRun?.base_sha ?? undefined,
        selectedRun?.commit_sha ?? undefined
      );
      setImpactRecommendations((current) => [
        recommendation,
        ...current.filter((item) => item.id !== recommendation.id)
      ]);
      setSelectedImpact(recommendation);
      setSelectedImpactId(recommendation.id);
      await refreshRoot();
      setStatusMessage('Impact recommendation generated.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const applyImpactOverride = async (
    item: ImpactRecommendationItem,
    action: 'include' | 'exclude'
  ) => {
    if (!selectedImpact) return;
    const reason = impactReviewReason.trim();
    if (!canReview) {
      setError('Reviewer project access is required for an impact override.');
      return;
    }
    if (!reason) {
      setError('Impact overrides require a concrete engineering reason.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const recommendation = await api.overrideImpactRecommendation(selectedImpact.id, {
        action,
        testKey: item.test_key,
        reason,
        expectedRevision: selectedImpact.current_revision
      });
      setSelectedImpact(recommendation);
      setImpactRecommendations((current) => current.map((entry) => (
        entry.id === recommendation.id ? recommendation : entry
      )));
      setImpactReviewReason('');
      setStatusMessage(`${action === 'include' ? 'Included' : 'Excluded'} ${item.test_identity} with an audited override.`);
    } catch (reasonValue) {
      setError(String(reasonValue));
    } finally {
      setBusy(false);
    }
  };

  const toggleClusterMember = (failureId: string) => {
    setSelectedClusterMembers((current) => (
      current.includes(failureId)
        ? current.filter((item) => item !== failureId)
        : [...current, failureId]
    ));
  };

  const submitClusterReview = async (decision: 'confirm' | 'split' | 'merge') => {
    if (!selectedCluster) return;
    const reason = clusterReviewReason.trim();
    if (!canReview) {
      setError('Reviewer project access is required for a cluster correction.');
      return;
    }
    if (!reason) {
      setError('Cluster reviews require a concrete engineering reason.');
      return;
    }
    if (decision === 'split' && selectedClusterMembers.length === 0) {
      setError('Select at least one member to move into the reviewed split cluster.');
      return;
    }
    if (decision === 'merge' && !mergeTargetId) {
      setError('Select an active target cluster before recording a merge.');
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const detail = await api.reviewCluster(selectedCluster.id, {
        decision,
        reason,
        expectedRevision: selectedCluster.current_revision,
        failureIds: decision === 'split' ? selectedClusterMembers : undefined,
        targetClusterId: decision === 'merge' ? mergeTargetId : undefined
      });
      const nextClusterId = decision === 'merge' ? mergeTargetId : detail.id;
      const nextCluster = nextClusterId === detail.id
        ? detail
        : await api.cluster(nextClusterId);
      setSelectedCluster(nextCluster);
      setSelectedClusterId(nextCluster.id);
      setClusterRevisions(await api.clusterRevisions(nextCluster.id));
      setSelectedClusterMembers([]);
      setClusterReviewReason('');
      await Promise.all([refreshRoot(), refreshProject(projectId, runId)]);
      if (runId) setRunClusters(await api.runClusters(runId));
      setStatusMessage(`Cluster review recorded: ${decision}.`);
    } catch (reasonValue) {
      setError(String(reasonValue));
    } finally {
      setBusy(false);
    }
  };

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.login(loginUsername.trim(), loginPassword);
      setLoginPassword('');
      await refreshRoot();
      setPrincipal(response.principal);
      setStatusMessage('Signed in successfully.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.logout();
      window.dispatchEvent(new Event('failurelens:session-expired'));
      setPrincipal(null);
      setProjects([]);
      setProjectId('');
      setRuns([]);
      setRunId('');
      setStatusMessage('Signed out.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const refreshGovernance = async () => {
    if (!projectId || !principal) return;
    const tasks: Promise<unknown>[] = [];
    if (canReview) {
      governanceChanged();
    }
    if (canAdminister) {
      tasks.push(api.projectMembers(projectId).then(setMembers));
      tasks.push(api.ingestionTokens(projectId).then(setIngestionTokens));
    }
    await Promise.all(tasks);
  };

  const openReviewQueueItem = async (item: ReviewQueueItem) => {
    setError(null);
    try {
      const [openedRun, nextFailures] = await Promise.all([operations.run(item.run_id), api.failures(item.run_id)]);
      if (openedRun.project_id !== projectId) throw new Error('Run does not belong to the selected project');
      setRuns(current => current.some(run => run.id === openedRun.id) ? current.map(run => run.id === openedRun.id ? openedRun : run) : [...current, openedRun]);
      changeRun(item.run_id);
      setFailures(nextFailures);
      setSelectedFailureId(
        nextFailures.find((failure) => failure.id === item.failure_id)?.id ?? nextFailures[0]?.id ?? ''
      );
      window.requestAnimationFrame(() => {
        const workspace = document.getElementById('workspace');
        workspace?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        workspace?.focus({ preventScroll: true });
      });
      setStatusMessage(`Opened ${item.test_identity} from the review queue.`);
    } catch (reason) {
      setError(String(reason));
    }
  };

  const submitAnalysisReview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const analysis = selectedFailure?.latest_analysis;
    if (!analysis || !canReview) {
      setError('Select an analyzed failure with reviewer project access.');
      return;
    }
    const reason = reviewReason.trim();
    if (!reason) {
      setError('A concrete review reason is required.');
      return;
    }
    const expectedVersion = analysisReviews.reduce(
      (highest, review) => Math.max(highest, review.version),
      0
    );
    setBusy(true);
    setError(null);
    try {
      const created = await api.reviewAnalysis(analysis.analysis_id, {
        decision: reviewDecision,
        proposedCategory: reviewDecision === 'category_correction' ? reviewCategory : undefined,
        reason,
        expectedVersion,
        investigationOutcome: reviewOutcome.trim() || undefined,
        releaseAdvice: reviewReleaseAdvice
      });
      setAnalysisReviews((current) => [...current, created]);
      setReviewReason('');
      setReviewOutcome('');
      await refreshGovernance();
      setStatusMessage(`Review decision ${readableValue(created.decision)} recorded as version ${created.version}.`);
    } catch (reasonValue) {
      setError(String(reasonValue));
    } finally {
      setBusy(false);
    }
  };

  const addProjectMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !canAdminister) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.addProjectMember(projectId, memberUsername.trim(), memberRole);
      setMembers((current) => [...current, created].sort((left, right) => left.username.localeCompare(right.username)));
      setMemberUsername('');
      governanceChanged();
      setStatusMessage(`${created.display_name} added as ${readableValue(created.role)}.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const changeProjectMemberRole = async (membershipId: string, role: ProjectRole) => {
    if (!projectId || !canAdminister) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateProjectMember(projectId, membershipId, role);
      setMembers((current) => current.map((member) => member.id === updated.id ? updated : member));
      governanceChanged();
      setStatusMessage(`${updated.display_name}'s role changed to ${readableValue(updated.role)}.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const removeProjectMember = async (membershipId: string) => {
    if (!projectId || !canAdminister) return;
    setBusy(true);
    setError(null);
    try {
      await api.removeProjectMember(projectId, membershipId);
      setMembers((current) => current.filter((member) => member.id !== membershipId));
      governanceChanged();
      setStatusMessage('Project membership removed.');
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const createIngestionCredential = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !canAdminister) return;
    const name = tokenName.trim();
    if (!name) {
      setError('A token name is required.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.createIngestionToken(projectId, name);
      setNewTokenSecret(created.token ?? null);
      setIngestionTokens((current) => [created, ...current.filter((token) => token.id !== created.id)]);
      setTokenName('');
      governanceChanged();
      setStatusMessage(`Ingestion credential ${created.name} created. Copy the secret now.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const revokeIngestionCredential = async (tokenId: string) => {
    if (!projectId || !canAdminister) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.revokeIngestionToken(projectId, tokenId);
      setIngestionTokens((current) => current.map((token) => token.id === updated.id ? updated : token));
      governanceChanged();
      setStatusMessage(`Ingestion credential ${updated.name} revoked.`);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const exportAuditCsv = async () => {
    setBusy(true); setError(null);
    try {
      const csv = await operations.exportAudit(projectId, { action: auditActionFilter, outcome: auditOutcomeFilter,
        search: auditSearch, sort: auditSort });
      downloadText(`failurelens-audit-${projectId}.csv`, csv, 'text/csv;charset=utf-8');
      setStatusMessage('Filtered audit export completed under the server policy. The export was audited.');
      governanceChanged();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  };

  const sessionChanged = async (signedOut = false) => {
    if (signedOut) {
      window.dispatchEvent(new Event('failurelens:session-expired'));
      return;
    }
    try { setPrincipal(await api.me()); }
    catch { window.dispatchEvent(new Event('failurelens:session-expired')); }
  };

  if (authLoading) {
    return <div className="auth-shell"><div className="auth-card" role="status"><p className="eyebrow">FAILURELENS</p><h1>Verifying session</h1><p>Loading the authenticated project scope…</p></div></div>;
  }

  if (!principal) {
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={submitLogin}>
          <p className="eyebrow">FAILURELENS</p>
          <h1>Sign in</h1>
          <p>Use a self-hosted FailureLens account. Project permissions are applied after authentication.</p>
          {error && <div className="alert" role="alert">{error}</div>}
        {runError && <div className="alert" role="alert">{runError}</div>}
          <label>Username<input autoComplete="username" value={loginUsername} onChange={(event: ChangeEvent<HTMLInputElement>) => setLoginUsername(event.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={loginPassword} onChange={(event: ChangeEvent<HTMLInputElement>) => setLoginPassword(event.target.value)} required /></label>
          <button className="primary" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>
        <RecoveryForm />
      </div>
    );
  }

  return (
    <>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          const mainContent = document.getElementById('main-content');
          if (!mainContent) return;
          const url = new URL(window.location.href);
          url.hash = 'main-content';
          window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
          mainContent.focus({ preventScroll: true });
          mainContent.scrollIntoView({ block: 'start' });
        }}
      >
        Skip to main content
      </a>
      <div className="app-shell">
      <aside className="sidebar" aria-label="Application sidebar">
        <div className="brand"><span className="brand-mark">FL</span><div><strong>FailureLens</strong><small>Evidence-grounded triage</small></div></div>
        <nav aria-label="Primary navigation">
          {navigationItems.map((item) => <a href={item.href} key={item.href} onClick={navigateSection}>{item.label}</a>)}
        </nav>
        <div className="sidebar-note">Durable deterministic mode<br/><span>No model API required</span></div>
      </aside>

      <main id="main-content" tabIndex={-1}>
        <header className="topbar">
          <div>
            <p className="eyebrow">QUALITY INTELLIGENCE</p><h1>Failure investigation console</h1>
            <details className="mobile-navigation">
              <summary>Navigate</summary>
              <nav aria-label="Compact navigation">
                {navigationItems.map((item) => <a href={item.href} key={item.href} onClick={navigateSection}>{item.label}</a>)}
              </nav>
            </details>
          </div>
          <div>
            {principal.demo_mode && canAdminister && <button className="primary" onClick={seedDemo} disabled={busy}>{busy ? 'Working…' : 'Load synthetic demo'}</button>}
            <div className="identity-bar" aria-label="Authenticated identity">
              <span><strong>{principal.display_name}</strong> · {readableValue(currentRole ?? 'no project role')}</span>
              {principal.kind === 'user' && <button className="ghost-button" type="button" onClick={logout} disabled={busy}>Sign out</button>}
            </div>
          </div>
        </header>

        {principal.demo_mode && <div className="demo-banner" role="status"><strong>Synthetic demo identity.</strong> This loopback-oriented mode bypasses normal login for a visibly labeled administrator and must not be exposed as production authentication.</div>}

        {error && <div className="alert" role="alert">{error}</div>}
        {runError && <div className="alert" role="alert">{runError}</div>}
        <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{statusMessage}</div>

        <section id="overview" className="metric-grid" aria-label="Overview metrics">
          {[
            ['Projects', overview?.projects ?? '—'],
            ['Ingestions', overview?.ingestions ?? '—'],
            ['Active jobs', overview?.active_ingestions ?? '—'],
            ['Runs', overview?.runs ?? '—'],
            ['Failures', overview?.failures ?? '—'],
            ['Clusters', overview?.clusters ?? '—'],
            ['Impact plans', overview?.impact_recommendations ?? '—'],
            ['Performance findings', overview?.performance_comparisons ?? '—'],
            ['Infrastructure events', overview?.infrastructure_events ?? '—'],
            ['Correlation snapshots', overview?.infrastructure_correlations ?? '—'],
            ['Analyses', overview?.analyses ?? '—']
          ].map(([label, value]) => <article className="metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}
        </section>

        <section className="category-strip" aria-label="Classification totals">
          {Object.entries(overview?.categories ?? {}).map(([category, count]) => (
            <div key={category}><i className={`dot ${statusClass(category)}`} aria-hidden="true"/><span>{categoryLabel[category]}</span><strong>{count}</strong></div>
          ))}
        </section>

        <section id="ingestion" className="panel ingestion-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">DURABLE PIPELINE</p><h2>Upload an actual test report</h2></div>
            <span className="pill insufficient-evidence">PostgreSQL-backed worker</span>
          </div>
          <form className="upload-form" onSubmit={uploadArtifact}>
            <label>Project<select value={projectId} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeProject(event.target.value)} required><option value="">Select project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label>External run ID<input value={externalId} onChange={(event: ChangeEvent<HTMLInputElement>) => setExternalId(event.target.value)} minLength={1} maxLength={240} required/></label>
            <label>Run scope<select value={uploadRunScope} onChange={(event: ChangeEvent<HTMLSelectElement>) => setUploadRunScope(event.target.value as 'full_suite' | 'impact_selected' | 'unknown')}><option value="unknown">Unknown</option><option value="full_suite">Full suite</option><option value="impact_selected">Impact selected</option></select></label>
            <label>Environment<input placeholder="Optional, e.g. CI Linux" value={uploadEnvironment} onChange={(event: ChangeEvent<HTMLInputElement>) => setUploadEnvironment(event.target.value)}/></label>
            <label>Expected required inputs<input inputMode="numeric" min="0" step="1" placeholder="Optional" value={expectedInputs} onChange={(event: ChangeEvent<HTMLInputElement>) => setExpectedInputs(event.target.value)}/></label>
            <label className="file-field">Report file<input key={fileInputKey} type="file" accept=".xml,.json,.jsonl,.har,.log,.txt,.zip,.png,.jpg,.jpeg,application/xml,application/json,application/zip,text/plain,image/png,image/jpeg" onChange={(event: ChangeEvent<HTMLInputElement>) => setSelectedFile(event.target.files?.[0] ?? null)} required/><small>{selectedFile ? `${selectedFile.name} · ${Math.ceil(selectedFile.size / 1024)} KiB` : 'Supported report, evidence file, or manifest v2 ZIP'}</small></label>
            <button className="primary" type="submit" disabled={busy || !canAdminister || !projectId || !selectedFile}>{busy ? 'Working…' : 'Queue ingestion'}</button>
          </form>

          <div className="ingestion-list" aria-live="polite">
            {ingestions.length === 0 && <div className="empty">No durable ingestions exist for this project.</div>}
            {ingestions.slice(0, 8).map((ingestion) => {
              const lastDiagnostic = ingestion.diagnostics.at(-1);
              return (
                <article className="ingestion-row" key={ingestion.id}>
                  <div>
                    <div className="ingestion-title"><strong>{ingestion.external_id}</strong><span className={`state ${statusClass(ingestion.state)}`}>{ingestionLabel[ingestion.state] ?? ingestion.state}</span></div>
                    <small>{ingestion.original_name} · {ingestion.source_format} · attempt {ingestion.attempt}</small>
                    {ingestion.error_message && <p className="ingestion-error">{ingestion.error_code}: {ingestion.error_message}</p>}
                    {!ingestion.error_message && lastDiagnostic && <p className="diagnostic mono">{String(lastDiagnostic.phase ?? 'pipeline')} · {String(lastDiagnostic.status ?? 'updated')}</p>}
                  </div>
                  <div className="ingestion-stats"><span>{ingestion.received_inputs}/{ingestion.expected_inputs ?? '—'} inputs</span><code>{ingestion.source_digest.slice(0, 10)}</code></div>
                  <div className="ingestion-actions">
                    {ingestion.run_id && <button type="button" onClick={() => changeRun(ingestion.run_id ?? '')}>Open run</button>}
                    {!terminalIngestionStates.has(ingestion.state) && <button type="button" onClick={() => cancelIngestion(ingestion)} disabled={busy || !canAdminister}>Cancel</button>}
                    {['failed', 'dead_lettered', 'cancelled'].includes(ingestion.state) && <button type="button" onClick={() => retryIngestion(ingestion)} disabled={busy || !canAdminister || Boolean(ingestion.source_expired_at)}>Retry</button>}
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section id="runs" className="panel filters">
          <label>Project<select value={projectId} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeProject(event.target.value)}><option value="">Select project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <label>Run<select value={runId} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeRun(event.target.value)}><option value="">Select run</option>{runId && !runs.some(run => run.id === runId) && <option value={runId}>{runLoading ? 'Loading requested run…' : 'Requested run unavailable'}</option>}{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.status}</option>)}</select></label>
          <div className="scope"><span>Input scope</span><strong>{selectedRun ? `${selectedRun.received_inputs}/${selectedRun.expected_inputs ?? 'unspecified'}` : '—'}</strong><small>{selectedRun?.evidence_expired_at ? 'evidence expired' : selectedRun?.completeness ?? 'no run selected'}</small></div>
          <div className="scope"><span>Execution cohort</span><strong>{selectedRun ? readableValue(selectedRun.run_scope) : '—'}</strong><small>{selectedRun?.environment ?? 'environment unknown'}</small></div>
          <div className="scope"><span>Revision</span><strong className="mono">{selectedRun?.commit_sha?.slice(0, 10) ?? 'unknown'}</strong><small>{selectedRun?.branch ?? 'branch unknown'}</small></div>
        </section>

        <section id="inputs" className="panel input-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">EVIDENCE SCOPE</p><h2>Run inputs and completeness</h2></div>
            <span className={`state ${statusClass(selectedRun?.completeness ?? 'unknown')}`}>{selectedRun?.completeness ?? 'No run'}</span>
          </div>
          {!selectedRun ? <div className="empty">Select a run to inspect its declared and received inputs.</div> : (
            <>
              <div className="input-summary">
                <span>Received inputs<strong>{selectedRun.received_inputs}</strong></span>
                <span>Expected required<strong>{selectedRun.expected_inputs ?? 'Unspecified'}</strong></span>
                <span>Parsed observations<strong>{String(selectedRun.source_metadata.observation_count ?? 'Unknown')}</strong></span>
                <span>Manifest version<strong>{String(selectedRun.source_metadata.manifest_version ?? 'Legacy / direct')}</strong></span>
              </div>
              <div className="input-table" aria-live="polite">
                {runInputs.length === 0 && <div className="empty">No persisted per-input diagnostics exist for this run.</div>}
                {runInputs.map((input) => (
                  <article className="input-row" key={input.id}>
                    <div><strong>{input.input_id}</strong><small>{input.path ?? 'No artifact path'}</small></div>
                    <div><span>{input.kind}</span><small>{input.parser_version ?? 'No parser executed'}</small></div>
                    <div><span className={`state ${statusClass(input.status)}`}>{input.status}</span><small>{input.required ? 'Required' : 'Optional'}</small></div>
                    <div><span>{input.size_bytes === null ? 'No bytes received' : `${Math.ceil(input.size_bytes / 1024)} KiB`}</span><small>{input.warnings.length > 0 ? input.warnings.join(' · ') : input.digest?.slice(0, 16) ?? 'No digest'}</small></div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>

        {selectedRun && <BinaryEvidencePanel key={`${selectedRun.id}:${selectedRun.evidence_expired_at ?? 'active'}`} runId={selectedRun.id} canReview={canReview} />}

        <section id="impact" className="panel impact-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">EXPLAINABLE CHANGE IMPACT</p><h2>Focused test recommendation</h2></div>
            <span className={`state ${selectedImpact?.full_suite_required ? 'partial' : selectedImpact ? 'succeeded' : 'unknown'}`}>
              {selectedImpact?.full_suite_required ? 'Full suite required' : selectedImpact ? 'Focused subset' : 'No recommendation'}
            </span>
          </div>
          <p className="impact-advisory">Recommendations are deterministic and advisory. They never skip tests automatically; incomplete, untrusted, critical, or unmapped changes force broad execution.</p>

          <div className="impact-controls">
            <label>Impact run<select value={runId} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeRun(event.target.value)}><option value="">Select a run</option>{runId && !runs.some(run => run.id === runId) && <option value={runId}>{runLoading ? 'Loading requested run…' : 'Requested run unavailable'}</option>}{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.commit_sha?.slice(0, 10) ?? 'head unknown'}</option>)}</select></label>
            <label>Impact mapping<select value={impactMappingId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setImpactMappingId(event.target.value)}><option value="">Select mapping snapshot</option>{impactMappings.map((mapping) => <option key={mapping.id} value={mapping.id}>{mapping.version} · {mapping.test_count} tests · {mapping.trusted && mapping.coverage_complete ? 'trusted' : 'fallback only'}</option>)}</select></label>
            <button className="primary" type="button" onClick={generateImpactRecommendation} disabled={busy || !canReview || !runId || !impactMappingId}>Generate recommendation</button>
            <label>Saved recommendation<select value={selectedImpactId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setSelectedImpactId(event.target.value)}><option value="">Select recommendation</option>{impactRecommendations.map((recommendation) => <option key={recommendation.id} value={recommendation.id}>{recommendation.head_sha?.slice(0, 10) ?? 'unknown head'} · {readableValue(recommendation.status)}</option>)}</select></label>
          </div>

          <details className="impact-mapping-editor">
            <summary>Register an immutable mapping snapshot</summary>
            <form onSubmit={registerImpactMapping}>
              <label>Impact mapping manifest<textarea rows={16} spellCheck={false} value={impactMappingJson} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setImpactMappingJson(event.target.value)} /></label>
              <button type="submit" disabled={busy || !canAdminister || !projectId}>Register mapping snapshot</button>
            </form>
            <p>Use explicit file-to-test, coverage, ownership, historical-failure, or reverse-dependency edges. A reused version name must have identical content.</p>
          </details>

          {!selectedImpact ? <div className="empty">Choose a run containing a changed-files input and a reviewed mapping snapshot.</div> : (
            <>
              <div className="impact-summary">
                <div><span>Status</span><strong>{readableValue(selectedImpact.status)}</strong><small>{selectedImpact.summary}</small></div>
                <div><span>Comparison</span><strong>{selectedImpact.comparison_trusted ? 'Trusted' : 'Fallback'}</strong><small>{selectedImpact.base_sha?.slice(0, 10) ?? 'unknown base'} → {selectedImpact.head_sha?.slice(0, 10) ?? 'unknown head'}</small></div>
                <div><span>Selected</span><strong>{String(selectedImpact.metrics.effective_selected_test_count ?? selectedImpact.selected_tests.length)}</strong><small>of {String(selectedImpact.metrics.test_catalog_count ?? '—')} catalogued tests</small></div>
                <div><span>Revision</span><strong>{selectedImpact.current_revision}</strong><small>{selectedImpact.overrides.length} audited override{selectedImpact.overrides.length === 1 ? '' : 's'}</small></div>
              </div>

              {selectedImpact.safety_reasons.length > 0 && <div className="impact-warning" role="status"><strong>Why focused execution is blocked</strong><div>{selectedImpact.safety_reasons.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div></div>}

              <div className="impact-changes"><h3>Validated change set</h3>{selectedImpact.changed_files.map((change, index) => <span key={`${String(change.path)}-${index}`}><strong>{String(change.status)}</strong> {String(change.old_path ? `${change.old_path} → ` : '')}{String(change.path)}</span>)}</div>

              <div className="impact-review-controls">
                <p className="identity-note">Verified reviewer: <strong>{principal.display_name}</strong>. The server records this authenticated identity.</p>
                <label>Impact override reason<input value={impactReviewReason} onChange={(event: ChangeEvent<HTMLInputElement>) => setImpactReviewReason(event.target.value)} placeholder="Required before including or excluding a test" disabled={!canReview} /></label>
              </div>

              <div className="impact-test-grid">
                <section aria-label="Selected impact tests">
                  <div className="history-section-heading"><h3>Selected tests</h3><span>{selectedImpact.selected_tests.length}</span></div>
                  {selectedImpact.selected_tests.map((item) => (
                    <article className="impact-test-row" key={item.test_key}>
                      <div><strong>{item.test_identity}</strong><small>{item.mandatory ? 'Mandatory · ' : ''}{item.confidence} confidence · {item.selection_source}</small><div className="impact-reasons">{item.reason_codes.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div></div>
                      <span className={`impact-criticality ${item.criticality}`}>{item.criticality}</span>
                      <button type="button" onClick={() => applyImpactOverride(item, 'exclude')} disabled={busy || !canReview || selectedImpact.full_suite_required || item.mandatory || item.criticality === 'critical'}>Exclude</button>
                    </article>
                  ))}
                </section>
                <section aria-label="Excluded impact tests">
                  <div className="history-section-heading"><h3>Excluded tests</h3><span>{selectedImpact.excluded_tests.length}</span></div>
                  {selectedImpact.excluded_tests.length === 0 && <div className="empty">No tests are excluded from the effective recommendation.</div>}
                  {selectedImpact.excluded_tests.map((item) => (
                    <article className="impact-test-row" key={item.test_key}>
                      <div><strong>{item.test_identity}</strong><small>{item.exclusion_reason}</small></div>
                      <span className={`impact-criticality ${item.criticality}`}>{item.criticality}</span>
                      <button type="button" onClick={() => applyImpactOverride(item, 'include')} disabled={busy || !canReview}>Include</button>
                    </article>
                  ))}
                </section>
              </div>

              <section className="impact-audit" aria-label="Impact override audit">
                <div className="history-section-heading"><h3>Override audit</h3><span>append-only</span></div>
                {selectedImpact.overrides.length === 0 && <div className="empty">No reviewer has changed the deterministic recommendation.</div>}
                {selectedImpact.overrides.map((override) => <article key={override.id}><strong>{override.action} {override.test_key}</strong><span>{override.actor} · revision {override.revision_before} → {override.revision_after}</span><p>{override.reason}</p></article>)}
              </section>
              <p className="history-provenance mono">Engine {selectedImpact.engine_version} · policy {selectedImpact.policy_version} · input {selectedImpact.input_digest.slice(0, 16)} · mapping {selectedImpact.mapping_snapshot_id.slice(0, 8)}.</p>
            </>
          )}
        </section>

        <section id="performance" className="panel performance-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">COMPATIBLE PRIOR-ONLY BASELINES</p><h2>Performance regression analysis</h2></div>
            <span className={`state ${performanceComparisons[0] ? performanceStatusClass(performanceComparisons[0].status) : performanceObservations.length ? 'partial' : 'unknown'}`}>
              {performanceLoading ? 'Calculating' : performanceComparisons.length ? `${performanceComparisons.length} finding${performanceComparisons.length === 1 ? '' : 's'}` : performanceObservations.length ? 'Ready to compare' : 'No observations'}
            </span>
          </div>
          <p className="performance-advisory">Only prior observations with compatible workload, environment, producer, units, run scope, trust, and completeness may form a baseline. Missing or incompatible history is never presented as “no regression.”</p>
          <div className="performance-controls">
            <label>Performance run<select value={runId} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeRun(event.target.value)}><option value="">Select a run</option>{runId && !runs.some(run => run.id === runId) && <option value={runId}>{runLoading ? 'Loading requested run…' : 'Requested run unavailable'}</option>}{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.commit_sha?.slice(0, 10) ?? 'head unknown'}</option>)}</select></label>
            <label>Immutable policy<select value={performancePolicyId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setPerformancePolicyId(event.target.value)}><option value="">Default strict policy</option>{performancePolicies.map((policy) => <option key={policy.id} value={policy.id}>{policy.version} · {Math.round(policy.relative_tolerance * 100)}% · {policy.min_baseline_runs} runs</option>)}</select></label>
            {performancePolicies.length === 0 && <button type="button" onClick={registerDefaultPerformancePolicy} disabled={busy || !canAdminister || !projectId}>Register strict policy</button>}
            <button className="primary" type="button" onClick={generatePerformanceComparisons} disabled={busy || !canReview || performanceLoading || !runId || performanceObservations.length === 0}>Compare compatible baselines</button>
          </div>

          <div className="performance-observations" aria-label="Normalized performance observations">
            <div className="history-section-heading"><h3>Normalized current observations</h3><span>{performanceObservations.length} duration or metric value{performanceObservations.length === 1 ? '' : 's'}</span></div>
            {performanceObservations.length === 0 && <div className="empty">The selected run contains no normalized test-duration or k6 metric observations.</div>}
            {performanceObservations.slice(0, 24).map((observation) => (
              <article className="performance-observation-row" key={observation.id}>
                <div><strong>{observation.metric_name}</strong><small>{readableValue(observation.metric_scope)} · {readableValue(observation.statistic)} · {observation.workload}</small></div>
                <span>{formatPerformanceValue(observation.canonical_value, observation.canonical_unit)}</span>
                <span className={`state ${performanceStatusClass(observation.threshold_status)}`}>{readableValue(observation.threshold_status)}</span>
                <a href={`/api/v1/evidence/${observation.evidence_id}`} target="_blank" rel="noreferrer">Evidence</a>
              </article>
            ))}
          </div>

          <div className="performance-results" aria-label="Performance comparison results">
            <div className="history-section-heading"><h3>Evidence-grounded findings</h3><span>Median of compatible run-level observations; never an aggregate percentile</span></div>
            {performanceLoading && <div className="empty">Selecting prior-only compatible cohorts and calculating deterministic changes…</div>}
            {!performanceLoading && performanceComparisons.length === 0 && <div className="empty">Run the comparison to create immutable baseline snapshots and findings.</div>}
            {performanceComparisons.map((comparison) => {
              const rejectedReasons = (comparison.compatibility.rejected_reason_counts ?? {}) as Record<string, number>;
              const currentBlockers = (comparison.compatibility.current_blockers ?? []) as string[];
              return (
                <article className="performance-comparison-card" key={comparison.id}>
                  <div className="performance-comparison-heading">
                    <div><strong>{comparison.metric_name}</strong><small>{readableValue(comparison.statistic)} · {comparison.workload} · {readableValue(comparison.direction)}</small></div>
                    <span className={`performance-status ${performanceStatusClass(comparison.status)}`}>{readableValue(comparison.status)}</span>
                  </div>
                  <p>{comparison.summary}</p>
                  <div className="performance-summary">
                    <div><span>Current</span><strong>{formatPerformanceValue(comparison.current_value, comparison.canonical_unit)}</strong><small>{comparison.current_sample_count ?? 'unknown'} sample{comparison.current_sample_count === 1 ? '' : 's'}</small></div>
                    <div><span>Compatible baseline</span><strong>{formatPerformanceValue(comparison.baseline_value, comparison.canonical_unit)}</strong><small>{comparison.baseline_run_count} prior run{comparison.baseline_run_count === 1 ? '' : 's'} · {comparison.baseline_sample_count} samples</small></div>
                    <div><span>Absolute change</span><strong>{formatPerformanceValue(comparison.absolute_change, comparison.canonical_unit)}</strong><small>Allowed {formatPerformanceValue(comparison.allowed_absolute_change, comparison.canonical_unit)}</small></div>
                    <div><span>Relative change</span><strong>{formatPerformanceDelta(comparison.relative_change)}</strong><small>Policy tolerance {(comparison.allowed_relative_change * 100).toFixed(1)}%</small></div>
                  </div>
                  {currentBlockers.length > 0 && <div className="performance-reasons"><strong>Current observation blockers</strong>{currentBlockers.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div>}
                  {Object.keys(rejectedReasons).length > 0 && <div className="performance-reasons"><strong>Rejected baseline candidates</strong>{Object.entries(rejectedReasons).map(([reason, count]) => <code key={reason}>{readableValue(reason)} · {count}</code>)}</div>}
                  {comparison.confounders.length > 0 && <div className="performance-reasons"><strong>Confounders and limitations</strong>{comparison.confounders.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div>}
                  <div className="performance-evidence">
                    <strong>Evidence provenance</strong>
                    <a href={`/api/v1/evidence/${comparison.current_evidence_id}`} target="_blank" rel="noreferrer">Current metric evidence</a>
                    {comparison.baseline_evidence_ids.map((evidenceId, index) => <a key={evidenceId} href={`/api/v1/evidence/${evidenceId}`} target="_blank" rel="noreferrer">Baseline evidence {index + 1}</a>)}
                  </div>
                  <div className="performance-next"><strong>Next measurement</strong><p>{comparison.next_measurement}</p></div>
                  <p className="history-provenance mono">Engine {comparison.engine_version} · policy {comparison.policy_id.slice(0, 8)} · baseline {comparison.baseline.status} · aggregation {comparison.baseline.aggregation} · input {comparison.input_digest.slice(0, 16)}.</p>
                </article>
              );
            })}
          </div>
        </section>

        <section id="clusters" className="cluster-workspace">
          <article className="panel cluster-list">
            <div className="panel-heading">
              <div><p className="eyebrow">EXPLAINABLE GROUPING</p><h2>Failure clusters</h2></div>
              <span className="count">{visibleClusters.length}</span>
            </div>
            <p className="cluster-safety-note">Similarity groups investigation signals; it does not prove a shared root cause.</p>
            {visibleClusters.length === 0 && <div className="empty">No persisted clusters are available for the selected scope.</div>}
            {visibleClusters.map((cluster) => (
              <button
                type="button"
                className={`cluster-row ${selectedClusterId === cluster.id ? 'active' : ''}`}
                key={cluster.id}
                onClick={() => setSelectedClusterId(cluster.id)}
              >
                <span>
                  <strong>{cluster.representative_test_identity ?? 'Unresolved representative'}</strong>
                  <small>{cluster.member_count} member{cluster.member_count === 1 ? '' : 's'} · revision {cluster.current_revision}</small>
                </span>
                <span className={`cluster-uncertainty ${statusClass(cluster.uncertainty)}`}>{cluster.uncertainty}</span>
                <code>{cluster.cluster_key.slice(0, 10)}</code>
              </button>
            ))}
          </article>

          <article className="panel cluster-detail">
            {!selectedCluster || !selectedCluster.current ? <div className="empty">Select a cluster to inspect its explainable membership.</div> : (
              <>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">CLUSTER REVISION {selectedCluster.current_revision}</p>
                    <h2>{selectedCluster.representative_test_identity ?? 'Failure cluster'}</h2>
                  </div>
                  <span className={`state ${statusClass(selectedCluster.status)}`}>{selectedCluster.status}</span>
                </div>
                <div className="cluster-meta">
                  <span>Algorithm<strong>{selectedCluster.algorithm_version}</strong></span>
                  <span>Features<strong>{selectedCluster.feature_version}</strong></span>
                  <span>Uncertainty<strong>{selectedCluster.uncertainty}</strong></span>
                  <span>Members<strong>{selectedCluster.current.member_count}</strong></span>
                </div>

                <div className="cluster-members" aria-label="Current cluster memberships">
                  {selectedCluster.current.memberships.map((member) => (
                    <article className="cluster-member" key={member.failure_id}>
                      <label className="member-select">
                        <input
                          type="checkbox"
                          checked={selectedClusterMembers.includes(member.failure_id)}
                          onChange={() => toggleClusterMember(member.failure_id)}
                          disabled={selectedCluster.status !== 'active'}
                        />
                        <span className="sr-only">Select {member.test_identity} for a reviewed split</span>
                      </label>
                      <div className="member-main">
                        <div className="member-heading">
                          <strong>{member.test_identity}</strong>
                          <span>{member.role}</span>
                          <em>{member.similarity_score === null ? 'representative' : member.similarity_score.toFixed(3)}</em>
                        </div>
                        <p>{member.message}</p>
                        <div className="signal-group">
                          {member.matching_signals.map((signal) => <code className="match" key={`${member.failure_id}-match-${signal}`}>{signal}</code>)}
                          {member.conflicting_signals.map((signal) => <code className="conflict" key={`${member.failure_id}-conflict-${signal}`}>{signal}</code>)}
                          {member.matching_signals.length === 0 && member.conflicting_signals.length === 0 && <small>Representative membership establishes the comparison anchor.</small>}
                        </div>
                        {member.candidate_reasons.length > 0 && (
                          <details className="candidate-reasons">
                            <summary>Candidate-generation reasons</summary>
                            <div>{member.candidate_reasons.map((candidate) => <code key={`${member.failure_id}-candidate-${candidate}`}>{candidate}</code>)}</div>
                          </details>
                        )}
                        {Object.keys(member.score_components).length > 0 && (
                          <dl className="score-components">
                            {Object.entries(member.score_components).map(([component, value]) => (
                              <div key={`${member.failure_id}-${component}`}><dt>{component}</dt><dd>{value.toFixed(3)}</dd></div>
                            ))}
                          </dl>
                        )}
                      </div>
                    </article>
                  ))}
                </div>

                <div className="cluster-lower-grid">
                  <section className="cluster-history" aria-label="Cluster revision history">
                    <h3>Revision history</h3>
                    {clusterRevisions.map((revision) => (
                      <article key={revision.id}>
                        <strong>Revision {revision.revision}</strong>
                        <span>{revision.reason.replaceAll('_', ' ')}</span>
                        <small>{revision.member_count} members · {revision.uncertainty_flags.length > 0 ? revision.uncertainty_flags.join(' · ') : 'low uncertainty'}</small>
                      </article>
                    ))}
                    {selectedCluster.decisions.length > 0 && <h3 className="decision-heading">Reviewed decisions</h3>}
                    {selectedCluster.decisions.map((decision) => (
                      <article className="cluster-decision" key={decision.id}>
                        <strong>{decision.decision.replaceAll('_', ' ')}</strong>
                        <span>{decision.reason}</span>
                        <small>{decision.actor} · revision {decision.revision_before} → {decision.revision_after}{decision.cluster_id !== selectedCluster.id ? ' · incoming merge' : ''}</small>
                      </article>
                    ))}
                  </section>

                  <section className="cluster-review" aria-label="Human cluster correction">
                    <h3>Record a reviewed correction</h3>
                    <p className="identity-note">Verified reviewer: <strong>{principal.display_name}</strong>. Actor text is not accepted from the browser.</p>
                    <label>Engineering reason<textarea rows={3} value={clusterReviewReason} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setClusterReviewReason(event.target.value)} placeholder="State the evidence supporting this correction." disabled={!canReview} /></label>
                    <label>Merge target<select value={mergeTargetId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setMergeTargetId(event.target.value)} disabled={!canReview}><option value="">Select another active cluster</option>{clusters.filter((cluster) => cluster.status === 'active' && cluster.id !== selectedCluster.id).map((cluster) => <option key={cluster.id} value={cluster.id}>{cluster.representative_test_identity ?? cluster.cluster_key.slice(0, 10)} · {cluster.member_count} members</option>)}</select></label>
                    <p>{selectedClusterMembers.length} member{selectedClusterMembers.length === 1 ? '' : 's'} selected for split.</p>
                    <div className="cluster-review-actions">
                      <button type="button" onClick={() => submitClusterReview('confirm')} disabled={busy || !canReview || selectedCluster.status !== 'active'}>Confirm grouping</button>
                      <button type="button" onClick={() => submitClusterReview('split')} disabled={busy || !canReview || selectedCluster.status !== 'active' || selectedClusterMembers.length === 0}>Split selected</button>
                      <button type="button" onClick={() => submitClusterReview('merge')} disabled={busy || !canReview || selectedCluster.status !== 'active' || !mergeTargetId}>Merge into target</button>
                    </div>
                  </section>
                </div>
              </>
            )}
          </article>
        </section>

        <section id="workspace" className="workspace" tabIndex={-1}>
          <article className="panel failure-list">
            <div className="panel-heading"><div><p className="eyebrow">CURRENT RUN</p><h2>Failures</h2></div><span className="count">{failures.length}</span></div>
            {failures.length === 0 && <div className="empty">No failures are available for the selected run.</div>}
            {failures.map((failure) => (
              <button className={`failure-row ${selectedFailure?.id === failure.id ? 'active' : ''}`} key={failure.id} onClick={() => setSelectedFailureId(failure.id)}>
                <span className={`severity ${failure.latest_analysis?.severity ?? 'unknown'}`}/>
                <span><strong>{failure.test_identity}</strong><small>{failure.message.slice(0, 110)}</small></span>
                <em>{failure.latest_analysis ? categoryLabel[failure.latest_analysis.category] : 'Not analyzed'}</em>
              </button>
            ))}
          </article>

          <article className="panel detail">
            {!selectedFailure ? <div className="empty">Select a failure to inspect evidence and analysis.</div> : (
              <>
                <div className="panel-heading"><div><p className="eyebrow">FAILURE WORKSPACE</p><h2>{selectedFailure.test_identity}</h2></div><span className="mono fingerprint">{selectedFailure.fingerprint.slice(0, 12)}</span></div>
                <div className="message-block"><span>Observed failure</span><p>{selectedFailure.message}</p></div>
                {!selectedFailure.latest_analysis ? (
                  <div className="empty action-empty"><p>Automatic analysis was not persisted. A manual re-analysis remains available to project reviewers.</p><button className="primary" onClick={() => analyze(selectedFailure)} disabled={busy || !canReview}>Analyze failure</button></div>
                ) : (
                  <>
                    <div className="analysis-grid">
                      <div className="analysis-summary">
                        <span className={`pill ${statusClass(selectedFailure.latest_analysis.category)}`}>{categoryLabel[selectedFailure.latest_analysis.category]}</span>
                        {selectedFailure.latest_analysis.evidence_state === 'expired' && <p className="alert" role="status">Evidence expired. Recorded category: {readableValue(selectedFailure.latest_analysis.recorded_category ?? 'unknown')}. This historical decision is no longer evidence-verified.</p>}
                        <h3>{selectedFailure.latest_analysis.summary}</h3>
                        <p>{selectedFailure.latest_analysis.confidence.explanation}</p>
                        <dl><div><dt>Score kind</dt><dd>{selectedFailure.latest_analysis.confidence.kind}</dd></div><div><dt>Score</dt><dd>{selectedFailure.latest_analysis.confidence.value ?? 'unavailable'}</dd></div><div><dt>Evidence completeness</dt><dd>{selectedFailure.latest_analysis.evidence_completeness}</dd></div></dl>
                      </div>
                      <div className="evidence-card">
                        <h3>Evidence state</h3>
                        <p><strong>{selectedFailure.latest_analysis.supporting_evidence_ids.length}</strong> supporting citations</p>
                        <p><strong>{selectedFailure.latest_analysis.contradictory_evidence_ids.length}</strong> contradictory citations</p>
                        <p><strong>{selectedFailure.latest_analysis.missing_evidence.length}</strong> missing inputs</p>
                        <p><strong>{selectedFailure.latest_analysis.validation_results?.accepted_evidence_ids?.length ?? 0}</strong> integrity-verified records</p>
                        <p><strong>{selectedFailure.latest_analysis.validation_results?.rejected_evidence_ids?.length ?? 0}</strong> rejected records</p>
                        <p><strong>{selectedFailure.latest_analysis.validation_results?.status ?? 'not validated'}</strong> publication validation</p>
                      </div>
                      <div className="next-step"><h3>Next investigation</h3>{selectedFailure.latest_analysis.next_investigation.map((step) => <div key={step.action}><strong>{step.action}</strong><p>{step.rationale}</p></div>)}</div>
                      {selectedFailure.latest_analysis.policy_flags.length > 0 && <div className="flags"><h3>Policy flags</h3>{selectedFailure.latest_analysis.policy_flags.map((flag) => <code key={flag}>{flag}</code>)}</div>}
                    </div>

                    <section className="review-panel" aria-label="Human analysis review">
                      <div className="panel-heading compact-title-row"><div><p className="eyebrow">HUMAN DECISION</p><h3>Review history</h3></div><span className="count">{analysisReviews.length}</span></div>
                      {analysisReviews.length === 0 ? <div className="empty">No human decision has been recorded for this analysis.</div> : (
                        <ol className="review-history">
                          {analysisReviews.map((review) => (
                            <li key={review.id}>
                              <strong>{readableValue(review.decision)}</strong>
                              {review.proposed_category && <span> · {categoryLabel[review.proposed_category as Category] ?? readableValue(review.proposed_category)}</span>}
                              <p>{review.reason}</p>
                              {review.investigation_outcome && <p><strong>Outcome:</strong> {review.investigation_outcome}</p>}
                              <small>{review.actor} · version {review.version} · {new Date(review.created_at).toLocaleString()}{review.release_advice ? ` · ${readableValue(review.release_advice)}` : ''}</small>
                            </li>
                          ))}
                        </ol>
                      )}
                      {canReview ? (
                        <form className="review-form" onSubmit={submitAnalysisReview}>
                          <p className="identity-note">Verified reviewer: <strong>{principal.display_name}</strong>. Recorded categories and review attribution are preserved; retention can expire evidence and quoted free text.</p>
                          <div className="review-form-grid">
                            <label>Decision<select value={reviewDecision} onChange={(event: ChangeEvent<HTMLSelectElement>) => setReviewDecision(event.target.value as typeof reviewDecision)}><option value="accept">Accept analysis</option><option value="reject">Reject analysis</option><option value="needs_more_evidence">Needs more evidence</option><option value="category_correction">Correct category</option></select></label>
                            <label>Proposed category<select value={reviewCategory} onChange={(event: ChangeEvent<HTMLSelectElement>) => setReviewCategory(event.target.value as Category)} disabled={reviewDecision !== 'category_correction'}>{Object.keys(categoryLabel).map((category) => <option key={category} value={category}>{categoryLabel[category]}</option>)}</select></label>
                            <label>Advisory state<select value={reviewReleaseAdvice} onChange={(event: ChangeEvent<HTMLSelectElement>) => setReviewReleaseAdvice(event.target.value as typeof reviewReleaseAdvice)}><option value="HOLD_FOR_REVIEW">Hold for review</option><option value="INVESTIGATE">Investigate</option><option value="NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE">No blocker identified in observed scope</option></select></label>
                          </div>
                          <label>Engineering reason<textarea value={reviewReason} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setReviewReason(event.target.value)} placeholder="State the evidence and reasoning for this decision." required /></label>
                          <label>Investigation outcome<textarea value={reviewOutcome} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setReviewOutcome(event.target.value)} placeholder="Optional follow-up, owner, or unresolved question." /></label>
                          <button className="primary" type="submit" disabled={busy}>Record append-only decision</button>
                        </form>
                      ) : <p className="identity-note">Viewer access is read-only. A reviewer or administrator must record a decision.</p>}
                    </section>
                  </>
                )}
              </>
            )}
          </article>
        </section>

        <section id="history" className="panel history-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">PRIOR-ONLY OUTCOME INTELLIGENCE</p><h2>Historical test intelligence</h2></div>
            <span className={`state ${testHistory?.safety.history_eligible_for_reassurance ? 'succeeded' : 'partial'}`}>
              {historyLoading ? 'Loading' : testHistory?.safety.history_eligible_for_reassurance ? 'History eligible' : 'Not reassurance-safe'}
            </span>
          </div>
          {!selectedFailure ? <div className="empty">Select a failure to inspect its prior-only test history.</div> : (
            <>
              <div className="history-context">
                <div className="history-context-summary"><strong>{selectedFailure.test_identity}</strong><small>Current run is excluded. Future runs and later reviews cannot enter this calculation. Filters remain in the page URL.</small></div>
                <label>Run scope<select value={historyRunScope} onChange={(event: ChangeEvent<HTMLSelectElement>) => setHistoryRunScope(event.target.value)}><option value="">All scopes</option><option value="full_suite">Full suite</option><option value="impact_selected">Impact selected</option><option value="unknown">Unknown</option></select></label>
                <label>Browser<input value={historyBrowser} onChange={(event: ChangeEvent<HTMLInputElement>) => setHistoryBrowser(event.target.value)} placeholder="All browsers" /></label>
                <label>Branch<input value={historyBranch} onChange={(event: ChangeEvent<HTMLInputElement>) => setHistoryBranch(event.target.value)} placeholder="All branches" /></label>
                <label>Environment<input value={historyEnvironment} onChange={(event: ChangeEvent<HTMLInputElement>) => setHistoryEnvironment(event.target.value)} placeholder="All environments" /></label>
                <label>Workers<input type="number" min="1" value={historyWorkerCount} onChange={(event: ChangeEvent<HTMLInputElement>) => setHistoryWorkerCount(event.target.value)} placeholder="Any" /></label>
                <label>Shards<input type="number" min="1" value={historyShardCount} onChange={(event: ChangeEvent<HTMLInputElement>) => setHistoryShardCount(event.target.value)} placeholder="Any" /></label>
              </div>
              {historyLoading ? <div className="empty">Calculating traceable historical rates…</div> : !testHistory ? <div className="empty">Historical data could not be loaded.</div> : (
                <>
                  <div className="history-metrics" aria-label="Historical rate metrics">
                    <article><span>Independent runs</span><strong>{testHistory.sample_sizes.independent_runs ?? 0}</strong><small>{testHistory.sample_sizes.runs_without_matching_test_observation ?? 0} comparable runs had no matching observation and were not counted as passes.</small></article>
                    <article><span>Observed pass rate</span><strong>{formatRate(testHistory.rates.observed_pass_rate)}</strong><small>{testHistory.rates.observed_pass_rate?.status.replaceAll('_', ' ')}</small></article>
                    <article><span>First-attempt failure</span><strong>{formatRate(testHistory.rates.first_attempt_failure_rate)}</strong><small>Browsers and retries collapse to one conservative run outcome.</small></article>
                    <article><span>Final failure</span><strong>{formatRate(testHistory.rates.final_failure_rate)}</strong><small>Skipped, cancelled and unknown remain visible outside the denominator.</small></article>
                    <article><span>Retry recovery</span><strong>{formatRate(testHistory.rates.retry_recovery_rate)}</strong><small>{testHistory.sample_sizes.retry_eligible_first_failures ?? 0} first-attempt failures were eligible.</small></article>
                    <article><span>Reviewed known flake</span><strong>{testHistory.review.reviewed_known_flake ? 'Yes' : 'No'}</strong><small>{testHistory.review.events.length} qualifying prior review event{testHistory.review.events.length === 1 ? '' : 's'} before cutoff.</small></article>
                  </div>

                  {testHistory.safety.insufficient_data_reasons.length > 0 && (
                    <div className="history-warning" role="status">
                      <strong>Why this history cannot support reassurance</strong>
                      <div>{testHistory.safety.insufficient_data_reasons.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div>
                    </div>
                  )}

                  <section className="infrastructure-context" aria-label="Infrastructure event correlations">
                    <div className="history-section-heading">
                      <div><h3>Infrastructure context</h3><small>Independently recorded events aligned to prior test executions.</small></div>
                      <span className={`state ${performanceStatusClass(infrastructureCorrelation?.status ?? 'NO_MATCHING_EVENTS')}`}>
                        {infrastructureLoading ? 'Persisting' : readableValue(infrastructureCorrelation?.status ?? 'NO_MATCHING_EVENTS')}
                      </span>
                    </div>
                    <div className="infrastructure-advisory" role="note">
                      Temporal overlap and rate differences are associations, not proof of cause. This result cannot independently label a failure as infrastructural or remove product-risk evidence.
                    </div>
                    {!infrastructureCorrelation ? (
                      <div className="empty">No infrastructure-correlation result is available for this cohort.</div>
                    ) : (
                      <>
                        <div className="infrastructure-metrics">
                          <article><span>Trusted events</span><strong>{infrastructureCorrelation.sample_sizes.accepted_events ?? 0}</strong><small>{infrastructureCorrelation.sample_sizes.rejected_events ?? 0} rejected by trust, cutoff, time, or context.</small></article>
                          <article><span>Exposed runs</span><strong>{infrastructureCorrelation.sample_sizes.exposed_runs ?? 0}</strong><small>{infrastructureCorrelation.sample_sizes.exposed_pass_fail_denominator ?? 0} pass/fail denominator.</small></article>
                          <article><span>Unexposed runs</span><strong>{infrastructureCorrelation.sample_sizes.unexposed_runs ?? 0}</strong><small>{infrastructureCorrelation.sample_sizes.unexposed_pass_fail_denominator ?? 0} pass/fail denominator.</small></article>
                          <article><span>Exposed failure rate</span><strong>{formatRate(infrastructureCorrelation.rates.exposed_failure_rate)}</strong><small>One conservative outcome per independent run.</small></article>
                          <article><span>Unexposed failure rate</span><strong>{formatRate(infrastructureCorrelation.rates.unexposed_failure_rate)}</strong><small>Missing tests are never counted as passes.</small></article>
                          <article><span>Rate difference</span><strong>{infrastructureCorrelation.rates.absolute_failure_rate_difference == null ? 'Unavailable' : `${(infrastructureCorrelation.rates.absolute_failure_rate_difference * 100).toFixed(1)} pp`}</strong><small>Exploratory association only.</small></article>
                        </div>
                        <div className="infrastructure-columns">
                          <div>
                            <div className="history-section-heading"><h4>Accepted event evidence</h4><span>{infrastructureCorrelation.accepted_events.length}</span></div>
                            {infrastructureCorrelation.accepted_events.length === 0 && <div className="empty">No trusted compatible event overlaps a prior run.</div>}
                            {infrastructureCorrelation.accepted_events.map((event) => (
                              <article className="infrastructure-event-row" key={event.id}>
                                <span className={`state ${event.trusted_for_correlation ? 'succeeded' : 'partial'}`}>{readableValue(event.source_trust)}</span>
                                <div><strong>{readableValue(event.event_kind)}</strong><small>{new Date(event.started_at).toLocaleString()} · {event.producer}</small><small>{event.repository ?? 'repository unknown'} · {event.environment ?? 'environment unknown'}{event.evidence_id ? ` · evidence ${event.evidence_id.slice(0, 8)}` : ''}</small></div>
                              </article>
                            ))}
                          </div>
                          <div>
                            <div className="history-section-heading"><h4>Exposed versus unexposed</h4><span>{infrastructureCorrelation.associations.length} event kind{infrastructureCorrelation.associations.length === 1 ? '' : 's'}</span></div>
                            {infrastructureCorrelation.associations.length === 0 && <div className="empty">No event kind has a compatible exposed cohort.</div>}
                            {infrastructureCorrelation.associations.map((association) => (
                              <article className="infrastructure-association" key={association.event_kind}>
                                <div><strong>{readableValue(association.event_kind)}</strong><span className={`state ${performanceStatusClass(association.status)}`}>{readableValue(association.status)}</span></div>
                                <p>Exposed {formatRate(association.exposed_failure_rate)} · unexposed {formatRate(association.unexposed_failure_rate)}</p>
                                <small>{association.exposed_run_count} exposed / {association.unexposed_run_count} unexposed runs · {association.confounded_run_count} confounded.</small>
                              </article>
                            ))}
                          </div>
                        </div>
                        {(infrastructureCorrelation.confounders.length > 0 || infrastructureCorrelation.rejected_events.length > 0) && (
                          <div className="infrastructure-rejections">
                            <strong>Limitations and rejected context</strong>
                            <div>{infrastructureCorrelation.confounders.map((reason) => <code key={`confounder-${reason}`}>{readableValue(reason)}</code>)}</div>
                            <div>{infrastructureCorrelation.rejected_events.slice(0, 12).flatMap((event) => event.reasons.map((reason) => <code key={`${event.event_id}-${reason}`}>{readableValue(event.event_kind)} · {readableValue(reason)}</code>))}</div>
                          </div>
                        )}
                        <p className="history-provenance mono">Infrastructure policy {infrastructureCorrelation.policy_version} · engine {infrastructureCorrelation.engine_version} · window ±{infrastructureCorrelation.window_seconds}s · input {infrastructureCorrelation.input_digest.slice(0, 16)}.</p>
                      </>
                    )}
                    <button className="secondary" type="button" onClick={persistInfrastructureCorrelation} disabled={busy || !canReview || infrastructureLoading || !selectedFailure}>
                      {infrastructureSnapshot?.snapshot_id ? 'Snapshot persisted' : 'Persist immutable correlation snapshot'}
                    </button>
                  </section>

                  <div className="history-grid">
                    <section className="history-timeline" aria-label="Historical observations">
                      <div className="history-section-heading"><h3>Traceable observations</h3><span>{testHistory.pagination.total} prior observation{testHistory.pagination.total === 1 ? '' : 's'}</span></div>
                      {testHistory.observations.length === 0 && <div className="empty">No prior matching observations satisfy the selected cohort.</div>}
                      {testHistory.observations.slice().reverse().map((observation) => (
                        <article className="history-row" key={`${observation.run_id}-${observation.browser ?? 'default'}`}>
                          <span className={`history-outcome ${statusClass(observation.final_outcome)}`}>{observation.final_outcome}</span>
                          <div><strong>{observation.external_id}</strong><small>{new Date(observation.observed_at).toLocaleString()} · {observation.browser ?? 'browser unknown'} · {readableValue(observation.run_scope)}</small><small>First {observation.first_outcome} → final {observation.final_outcome} · {observation.attempt_count} attempt{observation.attempt_count === 1 ? '' : 's'}{observation.retry_recovered ? ' · recovered on retry' : ''}</small></div>
                          <button type="button" onClick={() => { changeRun(observation.run_id); document.getElementById('runs')?.scrollIntoView({ behavior: 'smooth' }); }}>Open run</button>
                        </article>
                      ))}
                    </section>

                    <section className="history-breakdowns" aria-label="Historical cohort breakdowns">
                      <div className="history-section-heading"><h3>Cohort comparisons</h3><span>Associations, not causal claims</span></div>
                      {(['browser', 'branch', 'environment', 'run_scope', 'worker_count', 'shard_count', 'time_bucket'] as const).map((field) => (
                        <div className="breakdown-group" key={field}>
                          <h4>{readableValue(field)}</h4>
                          {(testHistory.breakdowns[field] ?? []).map((row) => (
                            <div key={`${field}-${row.value}`}><span>{readableValue(row.value)}</span><strong>{formatRate(row.final_failure_rate)}</strong><small>{row.sample_size} sample{row.sample_size === 1 ? '' : 's'}</small></div>
                          ))}
                          {(testHistory.breakdowns[field] ?? []).length === 0 && <small>No data</small>}
                        </div>
                      ))}
                    </section>
                  </div>
                  <p className="history-provenance mono">Policy {testHistory.policy_version} · cutoff {String(testHistory.window.before)} · input digest {testHistory.history_input_digest.slice(0, 16)} · exact records remain available through the API.</p>
                </>
              )}
            </>
          )}
        </section>

        {canReview && (
          <section id="reviews" className="panel review-queue-panel">
            <div className="panel-heading"><div><p className="eyebrow">VERIFIED HUMAN WORKFLOW</p><h2>Review queue</h2></div><span className="count">{reviewTotal ?? '…'} matching</span></div>
            <p className="limitation">Filters and pagination query the full authorized latest-analysis dataset. Older unresolved investigations remain accessible.</p>
            <div className="table-toolbar" aria-label="Review queue filters">
              <label>Search<input type="search" value={reviewSearch} onChange={(event: ChangeEvent<HTMLInputElement>) => { setReviewSearch(event.target.value); setReviewPage(1); }} placeholder="Test, summary, category, or decision" /></label>
              <label>Status<select value={reviewStatusFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setReviewStatusFilter(event.target.value as 'all' | 'pending' | 'reviewed'); setReviewPage(1); }}><option value="pending">Pending action</option><option value="reviewed">Terminally reviewed</option><option value="all">All analyses</option></select></label>
              <label>Category<select value={reviewCategoryFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setReviewCategoryFilter(event.target.value as 'all' | Category); setReviewPage(1); }}><option value="all">All categories</option>{Object.entries(categoryLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>Sort<select value={reviewSort} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setReviewSort(event.target.value as 'newest' | 'oldest' | 'severity' | 'test'); setReviewPage(1); }}><option value="newest">Newest analysis</option><option value="oldest">Oldest analysis</option><option value="severity">Highest severity</option><option value="test">Test identity</option></select></label>
            </div>
            <p className="result-summary" aria-live="polite">{reviewLoading ? 'Loading matching analyses…' : `Showing ${pagedReviewQueue.length} of ${reviewTotal ?? 0} matching analyses.`}</p>
            {!reviewLoading && reviewQueue.length === 0 ? <div className="empty">No analyses match the current review filters.</div> : (
              <>
                <div className="table-wrap">
                  <table>
                    <caption className="sr-only">Filtered review queue</caption>
                    <thead><tr><th scope="col">Test</th><th scope="col">Machine category</th><th scope="col">Evidence</th><th scope="col">Latest decision</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
                    <tbody>{pagedReviewQueue.map((item) => (
                      <tr key={item.analysis_id}>
                        <td><strong>{item.test_identity}</strong><small>{item.summary}</small></td>
                        <td><span className={`pill ${statusClass(item.category)}`}>{categoryLabel[item.category]}</span><small>{item.severity} severity</small></td>
                        <td>{readableValue(item.evidence_completeness)}<small>{item.policy_flags.length > 0 ? item.policy_flags.join(' · ') : 'No active policy flags'}</small></td>
                        <td>{item.latest_review_decision ? readableValue(item.latest_review_decision) : 'Unreviewed'}<small>version {item.latest_review_version}</small></td>
                        <td><button type="button" onClick={() => openReviewQueueItem(item)} aria-label={`Open failure ${item.test_identity}`}>Open failure</button></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <nav className="pagination" aria-label="Review queue pages" aria-busy={reviewLoading}>
                  <button type="button" onClick={() => setReviewPage((page) => Math.max(1, page - 1))} disabled={reviewLoading || reviewPage <= 1}>Previous</button>
                  <span>Page {reviewPage} of {reviewPageCount}</span>
                  <button type="button" onClick={() => setReviewPage((page) => Math.min(reviewPageCount, page + 1))} disabled={reviewLoading || reviewPage >= reviewPageCount}>Next</button>
                </nav>
              </>
            )}
          </section>
        )}

        <AccountPanel key={principal.user_id ?? principal.kind} principal={principal} onSessionChanged={sessionChanged} />

        {canAdminister && (
          <section id="settings" className="panel settings-panel">
            <div className="panel-heading"><div><p className="eyebrow">PROJECT ADMINISTRATION</p><h2>Roles and ingestion credentials</h2></div><span className="state succeeded">Administrator</span></div>
            <div className="settings-grid">
              <section className="settings-block" aria-label="Project memberships">
                <div><h3>Project members</h3><p>Users must already exist. A system administrator can provision users through the typed user API.</p></div>
                <form className="inline-form" onSubmit={addProjectMember}>
                  <label>Username<input value={memberUsername} onChange={(event: ChangeEvent<HTMLInputElement>) => setMemberUsername(event.target.value)} placeholder="reviewer@example.test" required /></label>
                  <label>Role<select value={memberRole} onChange={(event: ChangeEvent<HTMLSelectElement>) => setMemberRole(event.target.value as ProjectRole)}><option value="viewer">Viewer</option><option value="reviewer">Reviewer</option><option value="administrator">Administrator</option></select></label>
                  <button type="submit" disabled={busy || !memberUsername.trim()}>Add member</button>
                </form>
                {members.length === 0 ? <div className="empty">No explicit memberships exist. System administrators retain bootstrap access.</div> : (
                  <div className="table-wrap"><table><caption className="sr-only">Project members and roles</caption><thead><tr><th scope="col">User</th><th scope="col">Role</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead><tbody>{members.map((member) => (
                    <tr key={member.id}>
                      <td><strong>{member.display_name}</strong><small>{member.username}</small></td>
                      <td><select aria-label={`Role for ${member.username}`} value={member.role} onChange={(event: ChangeEvent<HTMLSelectElement>) => changeProjectMemberRole(member.id, event.target.value as ProjectRole)} disabled={busy}><option value="viewer">Viewer</option><option value="reviewer">Reviewer</option><option value="administrator">Administrator</option></select></td>
                      <td><button className="danger-button" type="button" onClick={() => removeProjectMember(member.id)} disabled={busy}>Remove</button></td>
                    </tr>
                  ))}</tbody></table></div>
                )}
              </section>

              <section className="settings-block" aria-label="Project ingestion credentials">
                <div><h3>Ingestion credentials</h3><p>Each secret is bound to this project and can only create artifact ingestions. It cannot read evidence or perform reviews.</p></div>
                <form className="inline-form" onSubmit={createIngestionCredential}>
                  <label>Credential name<input value={tokenName} onChange={(event: ChangeEvent<HTMLInputElement>) => setTokenName(event.target.value)} placeholder="GitHub Actions" required /></label>
                  <span/>
                  <button type="submit" disabled={busy || !tokenName.trim()}>Create token</button>
                </form>
                {newTokenSecret && <div className="secret-once" role="status"><strong>Copy this secret now. It will not be shown again.</strong><code>{newTokenSecret}</code><button type="button" onClick={() => navigator.clipboard?.writeText(newTokenSecret)}>Copy token</button></div>}
                <ul className="token-list">
                  {ingestionTokens.map((token) => (
                    <li key={token.id}>
                      <div><strong>{token.name}</strong><small>{token.token_prefix}… · {token.scopes.join(', ')} · created {new Date(token.created_at).toLocaleDateString()}{token.last_used_at ? ` · last used ${new Date(token.last_used_at).toLocaleString()}` : ''}</small></div>
                      {token.revoked_at ? <span className="state failed">Revoked</span> : <button className="danger-button" type="button" onClick={() => revokeIngestionCredential(token.id)} disabled={busy}>Revoke</button>}
                    </li>
                  ))}
                </ul>
                {ingestionTokens.length === 0 && <div className="empty">No project ingestion credentials exist.</div>}
              </section>

              {projectId && <RetentionPanel key={projectId} projectId={projectId} onChanged={governanceChanged} />}

              <section className="settings-block system-status-block" aria-labelledby="system-status-heading">
                <div><h3 id="system-status-heading">System status and policy versions</h3><p>Health checks are read-only and expose no credentials. Unknown states remain explicit instead of being shown as healthy.</p></div>
                <div className="status-grid" aria-live="polite" aria-busy={healthLoading}>
                  <article><span>API liveness</span><strong className={`state ${systemHealth.live?.status === 'live' ? 'succeeded' : systemHealth.live ? 'failed' : 'unknown'}`}>{systemHealth.live?.status ?? 'Unknown'}</strong></article>
                  <article><span>Database readiness</span><strong className={`state ${systemHealth.ready?.status === 'ready' ? 'succeeded' : systemHealth.ready ? 'failed' : 'unknown'}`}>{systemHealth.ready?.status ?? 'Unknown'}</strong></article>
                  <article><span>Analysis mode</span><strong>Deterministic</strong><small>No model API required</small></article>
                  <article><span>Project role</span><strong>{readableValue(currentRole ?? 'none')}</strong></article>
                  <article><span>Clustering engine</span><strong>{selectedCluster?.algorithm_version ?? runClusters[0]?.algorithm_version ?? 'Not yet persisted'}</strong></article>
                  <article><span>Impact policy</span><strong>{selectedImpact?.policy_version ?? 'Not yet persisted'}</strong></article>
                  <article><span>Performance policy</span><strong>{performancePolicies[0]?.version ?? 'Default strict policy'}</strong></article>
                  <article><span>Evidence inputs</span><strong>{runInputs.length}</strong><small>for selected run</small></article>
                </div>
                {systemHealth.error && <div className="alert compact-alert" role="alert">{systemHealth.error}</div>}
                <div className="status-actions"><button type="button" onClick={refreshSystemHealth} disabled={healthLoading}>{healthLoading ? 'Checking…' : 'Refresh health'}</button>{systemHealth.checkedAt && <small>Checked {new Date(systemHealth.checkedAt).toLocaleString()}</small>}</div>
              </section>
            </div>
          </section>
        )}

        {canReview && (
          <section id="audit" className="panel audit-panel">
            <div className="panel-heading"><div><p className="eyebrow">APPEND-ONLY APPLICATION HISTORY</p><h2>Project audit events</h2></div><span className="count">{auditTotal ?? '…'} matching</span></div>
            <p className="limitation">These events preserve verified application actors and reasons. They are not represented as cryptographically immutable against a database administrator.</p>
            <div className="table-toolbar audit-toolbar" aria-label="Audit event filters">
              <label>Search<input type="search" value={auditSearch} onChange={(event: ChangeEvent<HTMLInputElement>) => { setAuditSearch(event.target.value); setAuditPage(1); }} placeholder="Actor, action, resource, or reason" /></label>
              <label>Action<select value={auditActionFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setAuditActionFilter(event.target.value); setAuditPage(1); }}><option value="">All actions</option>{auditActions.map((action) => <option value={action} key={action}>{readableValue(action)}</option>)}</select></label>
              <label>Outcome<select value={auditOutcomeFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setAuditOutcomeFilter(event.target.value); setAuditPage(1); }}><option value="">All outcomes</option>{auditOutcomes.map((outcome) => <option value={outcome} key={outcome}>{readableValue(outcome)}</option>)}</select></label>
              <label>Sort<select value={auditSort} onChange={(event: ChangeEvent<HTMLSelectElement>) => { setAuditSort(event.target.value as 'newest' | 'oldest'); setAuditPage(1); }}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
              <button type="button" onClick={exportAuditCsv} disabled={busy || auditLoading || !canAdminister || !auditExportEnabled || !auditTotal}>Export filtered CSV</button>
            </div>
            <p className="result-summary" aria-live="polite">{auditLoading ? 'Loading matching audit events…' : `Showing ${pagedAuditEvents.length} of ${auditTotal ?? 0} matching audit events.`}</p>
            {!auditLoading && auditEvents.length === 0 ? <div className="empty">No project audit events match the current filters.</div> : (
              <>
                <div className="table-wrap"><table><caption className="sr-only">Filtered project audit events</caption><thead><tr><th scope="col">Time</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Resource</th><th scope="col">Reason</th></tr></thead><tbody>{pagedAuditEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{new Date(event.created_at).toLocaleString()}</td>
                    <td><strong>{event.actor_display}</strong><small>{readableValue(event.actor_kind)}</small></td>
                    <td>{readableValue(event.action)}<small>{readableValue(event.outcome)}</small></td>
                    <td>{readableValue(event.resource_type)}<small>{event.resource_id ?? 'No resource identifier'}</small></td>
                    <td>{event.reason ?? 'No free-text reason'} </td>
                  </tr>
                ))}</tbody></table></div>
                <nav className="pagination" aria-label="Audit event pages">
                  <button type="button" onClick={() => setAuditPage((page) => Math.max(1, page - 1))} disabled={auditLoading || auditPage <= 1}>Previous</button>
                  <span>Page {auditPage} of {auditPageCount}</span>
                  <button type="button" onClick={() => setAuditPage((page) => Math.min(auditPageCount, page + 1))} disabled={auditLoading || auditPage >= auditPageCount}>Next</button>
                </nav>
              </>
            )}
          </section>
        )}

        <EvaluationPanel metrics={evaluation} />
        {campaignEvaluation && <EvaluationPanel metrics={campaignEvaluation} id="campaign-evaluation" title="Frozen five-category evaluation" />}
        {fullstackEvaluation && <EvaluationPanel metrics={fullstackEvaluation} id="fullstack-evaluation" title="HTTP and database retry evaluation" />}
      </main>
      </div>
    </>
  );
}

export default App;
