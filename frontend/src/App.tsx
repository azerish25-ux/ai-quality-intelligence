import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import {
  api,
  type ClusterDetail,
  type ClusterRevision,
  type ClusterSummary,
  type Failure,
  type Ingestion,
  type ImpactMappingInput,
  type ImpactMappingSnapshot,
  type ImpactRecommendation,
  type ImpactRecommendationItem,
  type Overview,
  type Project,
  type Run,
  type RunInput,
  type TestHistory
} from './api';

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

const statusClass = (value: string): string => value.replaceAll('_', '-');
const terminalIngestionStates = new Set(['succeeded', 'partial', 'failed', 'cancelled', 'dead_lettered']);

const formatRate = (rate: TestHistory['rates'][string] | undefined): string => {
  if (!rate || rate.value === null) return `Unavailable (${rate?.numerator ?? 0}/${rate?.denominator ?? 0})`;
  return `${(rate.value * 100).toFixed(1)}% (${rate.numerator}/${rate.denominator})`;
};

const readableValue = (value: string): string => value.replaceAll('_', ' ');

const newExternalId = (): string => `manual-${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;

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
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState('');
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [watchedIngestionId, setWatchedIngestionId] = useState<string | null>(null);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [runInputs, setRunInputs] = useState<RunInput[]>([]);
  const [impactMappings, setImpactMappings] = useState<ImpactMappingSnapshot[]>([]);
  const [impactMappingId, setImpactMappingId] = useState('');
  const [impactRecommendations, setImpactRecommendations] = useState<ImpactRecommendation[]>([]);
  const [selectedImpactId, setSelectedImpactId] = useState('');
  const [selectedImpact, setSelectedImpact] = useState<ImpactRecommendation | null>(null);
  const [impactMappingJson, setImpactMappingJson] = useState(defaultImpactMapping);
  const [impactReviewActor, setImpactReviewActor] = useState('reviewer@example.test');
  const [impactReviewReason, setImpactReviewReason] = useState('');
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [runClusters, setRunClusters] = useState<ClusterSummary[]>([]);
  const [selectedClusterId, setSelectedClusterId] = useState('');
  const [selectedCluster, setSelectedCluster] = useState<ClusterDetail | null>(null);
  const [clusterRevisions, setClusterRevisions] = useState<ClusterRevision[]>([]);
  const [selectedClusterMembers, setSelectedClusterMembers] = useState<string[]>([]);
  const [clusterReviewActor, setClusterReviewActor] = useState('reviewer@example.test');
  const [clusterReviewReason, setClusterReviewReason] = useState('');
  const [mergeTargetId, setMergeTargetId] = useState('');
  const [selectedFailure, setSelectedFailure] = useState<Failure | null>(null);
  const [testHistory, setTestHistory] = useState<TestHistory | null>(null);
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
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState(newExternalId);
  const [uploadRunScope, setUploadRunScope] = useState<'full_suite' | 'impact_selected' | 'unknown'>('unknown');
  const [uploadEnvironment, setUploadEnvironment] = useState('');
  const [expectedInputs, setExpectedInputs] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRoot = useCallback(async () => {
    const [nextOverview, nextProjects, evaluationResponse] = await Promise.all([
      api.overview(),
      api.projects(),
      api.evaluation()
    ]);
    setOverview(nextOverview);
    setProjects(nextProjects);
    setEvaluation(evaluationResponse.metrics ?? null);
    setProjectId((current) => current || nextProjects[0]?.id || '');
  }, []);

  const refreshProject = useCallback(async (nextProjectId: string, preferredRunId?: string | null) => {
    if (!nextProjectId) {
      setRuns([]);
      setIngestions([]);
      setClusters([]);
      setRunClusters([]);
      setImpactMappings([]);
      setImpactRecommendations([]);
      setImpactMappingId('');
      setSelectedImpactId('');
      setSelectedImpact(null);
      setSelectedClusterId('');
      setSelectedCluster(null);
      setRunId('');
      return;
    }
    const [nextRuns, nextIngestions, nextClusters, nextMappings, nextImpactRecommendations] = await Promise.all([
      api.runs(nextProjectId),
      api.ingestions(nextProjectId),
      api.clusters(nextProjectId),
      api.impactMappings(nextProjectId),
      api.impactRecommendations(nextProjectId)
    ]);
    setRuns(nextRuns);
    setIngestions(nextIngestions);
    setClusters(nextClusters);
    setImpactMappings(nextMappings);
    setImpactRecommendations(nextImpactRecommendations);
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
    setRunId((current) => {
      if (preferredRunId && nextRuns.some((run) => run.id === preferredRunId)) return preferredRunId;
      if (current && nextRuns.some((run) => run.id === current)) return current;
      return nextRuns[0]?.id ?? '';
    });
  }, []);

  useEffect(() => {
    refreshRoot().catch((reason: unknown) => setError(String(reason)));
  }, [refreshRoot]);

  useEffect(() => {
    refreshProject(projectId).catch((reason: unknown) => setError(String(reason)));
  }, [projectId, refreshProject]);

  useEffect(() => {
    if (!runId) {
      setFailures([]);
      setRunInputs([]);
      setRunClusters([]);
      setSelectedFailure(null);
      return;
    }
    Promise.all([api.failures(runId), api.runInputs(runId), api.runClusters(runId)])
      .then(([nextFailures, nextInputs, nextRunClusters]) => {
        setFailures(nextFailures);
        setRunInputs(nextInputs);
        setRunClusters(nextRunClusters);
        setSelectedClusterId((current) => {
          if (current && nextRunClusters.some((cluster) => cluster.id === current)) return current;
          return nextRunClusters[0]?.id ?? current;
        });
        setSelectedFailure((current) => {
          if (current) return nextFailures.find((item) => item.id === current.id) ?? nextFailures[0] ?? null;
          return nextFailures[0] ?? null;
        });
      })
      .catch((reason: unknown) => setError(String(reason)));
  }, [runId]);

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

  useEffect(() => {
    const url = new URL(window.location.href);
    const values: Record<string, string> = {
      history_scope: historyRunScope,
      history_browser: historyBrowser,
      history_branch: historyBranch,
      history_environment: historyEnvironment,
      history_workers: historyWorkerCount,
      history_shards: historyShardCount
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
    historyBranch,
    historyBrowser,
    historyEnvironment,
    historyRunScope,
    historyShardCount,
    historyWorkerCount
  ]);

  useEffect(() => {
    if (!selectedFailure) {
      setTestHistory(null);
      setHistoryLoading(false);
      return;
    }
    let cancelled = false;
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
    selectedFailure
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
  }, [selectedImpactId]);

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
  }, [selectedClusterId]);

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
      await refreshRoot();
      setProjectId(seeded.project_id);
      await refreshProject(seeded.project_id, seeded.run_id);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const uploadArtifact = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const retryIngestion = async (ingestion: Ingestion) => {
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
    setBusy(true);
    setError(null);
    try {
      const analysis = await api.analyze(failure.id);
      const next = failures.map((item) => item.id === failure.id ? { ...item, latest_analysis: analysis } : item);
      setFailures(next);
      setSelectedFailure(next.find((item) => item.id === failure.id) ?? null);
      await refreshRoot();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const registerImpactMapping = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const generateImpactRecommendation = async () => {
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
    const actor = impactReviewActor.trim();
    const reason = impactReviewReason.trim();
    if (!actor || !reason) {
      setError('Impact overrides require an attributed actor and a concrete engineering reason.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const recommendation = await api.overrideImpactRecommendation(selectedImpact.id, {
        actor,
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
    const actor = clusterReviewActor.trim();
    if (!actor || !reason) {
      setError('Cluster reviews require an actor and a concrete engineering reason.');
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
        actor,
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
    } catch (reasonValue) {
      setError(String(reasonValue));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">FL</span><div><strong>FailureLens</strong><small>Evidence-grounded triage</small></div></div>
        <nav aria-label="Primary navigation">
          <a href="#overview">Overview</a>
          <a href="#ingestion">Ingestion</a>
          <a href="#runs">Runs</a>
          <a href="#impact">Change impact</a>
          <a href="#clusters">Clusters</a>
          <a href="#workspace">Failure workspace</a>
          <a href="#history">Test history</a>
          <a href="#evaluation">Evaluation</a>
        </nav>
        <div className="sidebar-note">Durable deterministic mode<br/><span>No model API required</span></div>
      </aside>

      <main>
        <header className="topbar">
          <div><p className="eyebrow">QUALITY INTELLIGENCE</p><h1>Failure investigation console</h1></div>
          <button className="primary" onClick={seedDemo} disabled={busy}>{busy ? 'Working…' : 'Load synthetic demo'}</button>
        </header>

        {error && <div className="alert" role="alert">{error}</div>}

        <section id="overview" className="metric-grid" aria-label="Overview metrics">
          {[
            ['Projects', overview?.projects ?? '—'],
            ['Ingestions', overview?.ingestions ?? '—'],
            ['Active jobs', overview?.active_ingestions ?? '—'],
            ['Runs', overview?.runs ?? '—'],
            ['Failures', overview?.failures ?? '—'],
            ['Clusters', overview?.clusters ?? '—'],
            ['Impact plans', overview?.impact_recommendations ?? '—'],
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
            <label>Project<select value={projectId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setProjectId(event.target.value)} required><option value="">Select project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label>External run ID<input value={externalId} onChange={(event: ChangeEvent<HTMLInputElement>) => setExternalId(event.target.value)} minLength={1} maxLength={240} required/></label>
            <label>Run scope<select value={uploadRunScope} onChange={(event: ChangeEvent<HTMLSelectElement>) => setUploadRunScope(event.target.value as 'full_suite' | 'impact_selected' | 'unknown')}><option value="unknown">Unknown</option><option value="full_suite">Full suite</option><option value="impact_selected">Impact selected</option></select></label>
            <label>Environment<input placeholder="Optional, e.g. CI Linux" value={uploadEnvironment} onChange={(event: ChangeEvent<HTMLInputElement>) => setUploadEnvironment(event.target.value)}/></label>
            <label>Expected required inputs<input inputMode="numeric" min="0" step="1" placeholder="Optional" value={expectedInputs} onChange={(event: ChangeEvent<HTMLInputElement>) => setExpectedInputs(event.target.value)}/></label>
            <label className="file-field">Report file<input key={fileInputKey} type="file" accept=".xml,.json,.jsonl,.har,.log,.txt,.zip,.png,.jpg,.jpeg,application/xml,application/json,application/zip,text/plain,image/png,image/jpeg" onChange={(event: ChangeEvent<HTMLInputElement>) => setSelectedFile(event.target.files?.[0] ?? null)} required/><small>{selectedFile ? `${selectedFile.name} · ${Math.ceil(selectedFile.size / 1024)} KiB` : 'Supported report, evidence file, or manifest v2 ZIP'}</small></label>
            <button className="primary" type="submit" disabled={busy || !projectId || !selectedFile}>{busy ? 'Working…' : 'Queue ingestion'}</button>
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
                    {ingestion.run_id && <button type="button" onClick={() => setRunId(ingestion.run_id ?? '')}>Open run</button>}
                    {!terminalIngestionStates.has(ingestion.state) && <button type="button" onClick={() => cancelIngestion(ingestion)} disabled={busy}>Cancel</button>}
                    {['failed', 'dead_lettered', 'cancelled'].includes(ingestion.state) && <button type="button" onClick={() => retryIngestion(ingestion)} disabled={busy}>Retry</button>}
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section id="runs" className="panel filters">
          <label>Project<select value={projectId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setProjectId(event.target.value)}><option value="">Select project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <label>Run<select value={runId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setRunId(event.target.value)}><option value="">Select run</option>{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.status}</option>)}</select></label>
          <div className="scope"><span>Input scope</span><strong>{selectedRun ? `${selectedRun.received_inputs}/${selectedRun.expected_inputs ?? 'unspecified'}` : '—'}</strong><small>{selectedRun?.completeness ?? 'no run selected'}</small></div>
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

        <section id="impact" className="panel impact-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">EXPLAINABLE CHANGE IMPACT</p><h2>Focused test recommendation</h2></div>
            <span className={`state ${selectedImpact?.full_suite_required ? 'partial' : selectedImpact ? 'succeeded' : 'unknown'}`}>
              {selectedImpact?.full_suite_required ? 'Full suite required' : selectedImpact ? 'Focused subset' : 'No recommendation'}
            </span>
          </div>
          <p className="impact-advisory">Recommendations are deterministic and advisory. They never skip tests automatically; incomplete, untrusted, critical, or unmapped changes force broad execution.</p>

          <div className="impact-controls">
            <label>Impact run<select value={runId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setRunId(event.target.value)}><option value="">Select a run</option>{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.commit_sha?.slice(0, 10) ?? 'head unknown'}</option>)}</select></label>
            <label>Impact mapping<select value={impactMappingId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setImpactMappingId(event.target.value)}><option value="">Select mapping snapshot</option>{impactMappings.map((mapping) => <option key={mapping.id} value={mapping.id}>{mapping.version} · {mapping.test_count} tests · {mapping.trusted && mapping.coverage_complete ? 'trusted' : 'fallback only'}</option>)}</select></label>
            <button className="primary" type="button" onClick={generateImpactRecommendation} disabled={busy || !runId || !impactMappingId}>Generate recommendation</button>
            <label>Saved recommendation<select value={selectedImpactId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setSelectedImpactId(event.target.value)}><option value="">Select recommendation</option>{impactRecommendations.map((recommendation) => <option key={recommendation.id} value={recommendation.id}>{recommendation.head_sha?.slice(0, 10) ?? 'unknown head'} · {readableValue(recommendation.status)}</option>)}</select></label>
          </div>

          <details className="impact-mapping-editor">
            <summary>Register an immutable mapping snapshot</summary>
            <form onSubmit={registerImpactMapping}>
              <label>Impact mapping manifest<textarea rows={16} spellCheck={false} value={impactMappingJson} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setImpactMappingJson(event.target.value)} /></label>
              <button type="submit" disabled={busy || !projectId}>Register mapping snapshot</button>
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
                <label>Impact reviewer<input value={impactReviewActor} onChange={(event: ChangeEvent<HTMLInputElement>) => setImpactReviewActor(event.target.value)} /></label>
                <label>Impact override reason<input value={impactReviewReason} onChange={(event: ChangeEvent<HTMLInputElement>) => setImpactReviewReason(event.target.value)} placeholder="Required before including or excluding a test" /></label>
              </div>

              <div className="impact-test-grid">
                <section aria-label="Selected impact tests">
                  <div className="history-section-heading"><h3>Selected tests</h3><span>{selectedImpact.selected_tests.length}</span></div>
                  {selectedImpact.selected_tests.map((item) => (
                    <article className="impact-test-row" key={item.test_key}>
                      <div><strong>{item.test_identity}</strong><small>{item.mandatory ? 'Mandatory · ' : ''}{item.confidence} confidence · {item.selection_source}</small><div className="impact-reasons">{item.reason_codes.map((reason) => <code key={reason}>{readableValue(reason)}</code>)}</div></div>
                      <span className={`impact-criticality ${item.criticality}`}>{item.criticality}</span>
                      <button type="button" onClick={() => applyImpactOverride(item, 'exclude')} disabled={busy || selectedImpact.full_suite_required || item.mandatory || item.criticality === 'critical'}>Exclude</button>
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
                      <button type="button" onClick={() => applyImpactOverride(item, 'include')} disabled={busy}>Include</button>
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
                    <label>Actor<input value={clusterReviewActor} onChange={(event: ChangeEvent<HTMLInputElement>) => setClusterReviewActor(event.target.value)} /></label>
                    <label>Engineering reason<textarea rows={3} value={clusterReviewReason} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setClusterReviewReason(event.target.value)} placeholder="State the evidence supporting this correction." /></label>
                    <label>Merge target<select value={mergeTargetId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setMergeTargetId(event.target.value)}><option value="">Select another active cluster</option>{clusters.filter((cluster) => cluster.status === 'active' && cluster.id !== selectedCluster.id).map((cluster) => <option key={cluster.id} value={cluster.id}>{cluster.representative_test_identity ?? cluster.cluster_key.slice(0, 10)} · {cluster.member_count} members</option>)}</select></label>
                    <p>{selectedClusterMembers.length} member{selectedClusterMembers.length === 1 ? '' : 's'} selected for split.</p>
                    <div className="cluster-review-actions">
                      <button type="button" onClick={() => submitClusterReview('confirm')} disabled={busy || selectedCluster.status !== 'active'}>Confirm grouping</button>
                      <button type="button" onClick={() => submitClusterReview('split')} disabled={busy || selectedCluster.status !== 'active' || selectedClusterMembers.length === 0}>Split selected</button>
                      <button type="button" onClick={() => submitClusterReview('merge')} disabled={busy || selectedCluster.status !== 'active' || !mergeTargetId}>Merge into target</button>
                    </div>
                  </section>
                </div>
              </>
            )}
          </article>
        </section>

        <section id="workspace" className="workspace">
          <article className="panel failure-list">
            <div className="panel-heading"><div><p className="eyebrow">CURRENT RUN</p><h2>Failures</h2></div><span className="count">{failures.length}</span></div>
            {failures.length === 0 && <div className="empty">No failures are available for the selected run.</div>}
            {failures.map((failure) => (
              <button className={`failure-row ${selectedFailure?.id === failure.id ? 'active' : ''}`} key={failure.id} onClick={() => setSelectedFailure(failure)}>
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
                  <div className="empty action-empty"><p>Automatic analysis was not persisted. A manual re-analysis remains available.</p><button className="primary" onClick={() => analyze(selectedFailure)} disabled={busy}>Analyze failure</button></div>
                ) : (
                  <div className="analysis-grid">
                    <div className="analysis-summary">
                      <span className={`pill ${statusClass(selectedFailure.latest_analysis.category)}`}>{categoryLabel[selectedFailure.latest_analysis.category]}</span>
                      <h3>{selectedFailure.latest_analysis.summary}</h3>
                      <p>{selectedFailure.latest_analysis.confidence.explanation}</p>
                      <dl><div><dt>Score kind</dt><dd>{selectedFailure.latest_analysis.confidence.kind}</dd></div><div><dt>Score</dt><dd>{selectedFailure.latest_analysis.confidence.value ?? 'unavailable'}</dd></div><div><dt>Evidence completeness</dt><dd>{selectedFailure.latest_analysis.evidence_completeness}</dd></div></dl>
                    </div>
                    <div className="evidence-card">
                      <h3>Evidence state</h3>
                      <p><strong>{selectedFailure.latest_analysis.supporting_evidence_ids.length}</strong> supporting citations</p>
                      <p><strong>{selectedFailure.latest_analysis.contradictory_evidence_ids.length}</strong> contradictory citations</p>
                      <p><strong>{selectedFailure.latest_analysis.missing_evidence.length}</strong> missing inputs</p>
                      <p><strong>{selectedFailure.latest_analysis.validation_results?.accepted_evidence_ids.length ?? 0}</strong> integrity-verified records</p>
                      <p><strong>{selectedFailure.latest_analysis.validation_results?.rejected_evidence_ids.length ?? 0}</strong> rejected records</p>
                      <p><strong>{selectedFailure.latest_analysis.validation_results?.status ?? 'not validated'}</strong> publication validation</p>
                    </div>
                    <div className="next-step"><h3>Next investigation</h3>{selectedFailure.latest_analysis.next_investigation.map((step) => <div key={step.action}><strong>{step.action}</strong><p>{step.rationale}</p></div>)}</div>
                    {selectedFailure.latest_analysis.policy_flags.length > 0 && <div className="flags"><h3>Policy flags</h3>{selectedFailure.latest_analysis.policy_flags.map((flag) => <code key={flag}>{flag}</code>)}</div>}
                  </div>
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

                  <div className="history-grid">
                    <section className="history-timeline" aria-label="Historical observations">
                      <div className="history-section-heading"><h3>Traceable observations</h3><span>{testHistory.pagination.total} prior observation{testHistory.pagination.total === 1 ? '' : 's'}</span></div>
                      {testHistory.observations.length === 0 && <div className="empty">No prior matching observations satisfy the selected cohort.</div>}
                      {testHistory.observations.slice().reverse().map((observation) => (
                        <article className="history-row" key={`${observation.run_id}-${observation.browser ?? 'default'}`}>
                          <span className={`history-outcome ${statusClass(observation.final_outcome)}`}>{observation.final_outcome}</span>
                          <div><strong>{observation.external_id}</strong><small>{new Date(observation.observed_at).toLocaleString()} · {observation.browser ?? 'browser unknown'} · {readableValue(observation.run_scope)}</small><small>First {observation.first_outcome} → final {observation.final_outcome} · {observation.attempt_count} attempt{observation.attempt_count === 1 ? '' : 's'}{observation.retry_recovered ? ' · recovered on retry' : ''}</small></div>
                          <button type="button" onClick={() => { setRunId(observation.run_id); document.getElementById('runs')?.scrollIntoView({ behavior: 'smooth' }); }}>Open run</button>
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

        <section id="evaluation" className="panel evaluation">
          <div className="panel-heading"><div><p className="eyebrow">FROZEN CONTROLLED CORPUS</p><h2>Deterministic evaluation</h2></div><span className="pill insufficient-evidence">Synthetic evidence only</span></div>
          {!evaluation ? <div className="empty">Executed evaluation metrics are not mounted in this runtime.</div> : (
            <div className="eval-grid">
              <div><span>Cases</span><strong>{String(evaluation.case_count)}</strong></div>
              <div><span>Macro F1</span><strong>{Number(evaluation.macro_f1).toFixed(3)}</strong></div>
              <div><span>Product recall</span><strong>{Number(evaluation.product_defect_recall).toFixed(3)}</strong></div>
              <div><span>Dangerous dismissals</span><strong>{String((evaluation.dangerous_dismissal as { numerator: number }).numerator)}</strong></div>
            </div>
          )}
          <p className="limitation">The committed benchmark is agent-authored and synthetic. It does not include the prompt-required actual LedgerGuard executions and must not be presented as deployment performance.</p>
        </section>
      </main>
    </div>
  );
}

export default App;
