import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import {
  api,
  type ClusterDetail,
  type ClusterRevision,
  type ClusterSummary,
  type Failure,
  type Ingestion,
  type Overview,
  type Project,
  type Run,
  type RunInput
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

const newExternalId = (): string => `manual-${new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)}`;

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
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [externalId, setExternalId] = useState(newExternalId);
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
      setSelectedClusterId('');
      setSelectedCluster(null);
      setRunId('');
      return;
    }
    const [nextRuns, nextIngestions, nextClusters] = await Promise.all([
      api.runs(nextProjectId),
      api.ingestions(nextProjectId),
      api.clusters(nextProjectId)
    ]);
    setRuns(nextRuns);
    setIngestions(nextIngestions);
    setClusters(nextClusters);
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
        expectedInputs: expected
      });
      setIngestions((current) => [queued, ...current.filter((item) => item.id !== queued.id)]);
      setWatchedIngestionId(queued.id);
      setSelectedFile(null);
      setExternalId(newExternalId());
      setExpectedInputs('');
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
          <a href="#clusters">Clusters</a>
          <a href="#workspace">Failure workspace</a>
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
          <div className="scope"><span>Scope</span><strong>{selectedRun ? `${selectedRun.received_inputs}/${selectedRun.expected_inputs ?? 'unspecified'}` : '—'}</strong><small>{selectedRun?.completeness ?? 'no run selected'}</small></div>
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
