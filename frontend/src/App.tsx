import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type Failure, type Overview, type Project, type Run } from './api';

const categoryLabel: Record<string, string> = {
  product_defect: 'Probable product defect',
  test_defect: 'Probable test defect',
  infrastructure_failure: 'Infrastructure / environment',
  known_flake: 'Known flaky behavior',
  insufficient_evidence: 'Insufficient evidence'
};

const statusClass = (value: string): string => value.replaceAll('_', '-');

function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState('');
  const [failures, setFailures] = useState<Failure[]>([]);
  const [selectedFailure, setSelectedFailure] = useState<Failure | null>(null);
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRoot = useCallback(async () => {
    const [nextOverview, nextProjects, evaluationResponse] = await Promise.all([
      api.overview(), api.projects(), api.evaluation()
    ]);
    setOverview(nextOverview);
    setProjects(nextProjects);
    setEvaluation(evaluationResponse.metrics ?? null);
    setProjectId((current) => current || nextProjects[0]?.id || '');
  }, []);

  useEffect(() => {
    refreshRoot().catch((reason: unknown) => setError(String(reason)));
  }, [refreshRoot]);

  useEffect(() => {
    if (!projectId) {
      setRuns([]);
      return;
    }
    api.runs(projectId)
      .then((next) => {
        setRuns(next);
        setRunId((current) => current && next.some((run) => run.id === current) ? current : next[0]?.id ?? '');
      })
      .catch((reason: unknown) => setError(String(reason)));
  }, [projectId]);

  useEffect(() => {
    if (!runId) {
      setFailures([]);
      setSelectedFailure(null);
      return;
    }
    api.failures(runId)
      .then((next) => {
        setFailures(next);
        setSelectedFailure(next[0] ?? null);
      })
      .catch((reason: unknown) => setError(String(reason)));
  }, [runId]);

  const selectedRun = useMemo(() => runs.find((run) => run.id === runId) ?? null, [runs, runId]);

  const seedDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      const seeded = await api.seedDemo();
      await refreshRoot();
      setProjectId(seeded.project_id);
      setRunId(seeded.run_id);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const analyze = async (failure: Failure) => {
    setBusy(true);
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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">FL</span><div><strong>FailureLens</strong><small>Evidence-grounded triage</small></div></div>
        <nav aria-label="Primary navigation">
          <a href="#overview">Overview</a>
          <a href="#runs">Runs</a>
          <a href="#workspace">Failure workspace</a>
          <a href="#evaluation">Evaluation</a>
        </nav>
        <div className="sidebar-note">Deterministic mode<br/><span>No model API required</span></div>
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
            ['Runs', overview?.runs ?? '—'],
            ['Failures', overview?.failures ?? '—'],
            ['Analyses', overview?.analyses ?? '—']
          ].map(([label, value]) => <article className="metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}
        </section>

        <section className="category-strip" aria-label="Classification totals">
          {Object.entries(overview?.categories ?? {}).map(([category, count]) => (
            <div key={category}><i className={`dot ${statusClass(category)}`} aria-hidden="true"/><span>{categoryLabel[category]}</span><strong>{count}</strong></div>
          ))}
        </section>

        <section id="runs" className="panel filters">
          <label>Project<select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <label>Run<select value={runId} onChange={(event) => setRunId(event.target.value)}>{runs.map((run) => <option key={run.id} value={run.id}>{run.external_id} · {run.status}</option>)}</select></label>
          <div className="scope"><span>Scope</span><strong>{selectedRun ? `${selectedRun.received_inputs}/${selectedRun.expected_inputs ?? 'unspecified'}` : '—'}</strong><small>{selectedRun?.completeness ?? 'no run selected'}</small></div>
          <div className="scope"><span>Revision</span><strong className="mono">{selectedRun?.commit_sha?.slice(0, 10) ?? 'unknown'}</strong><small>{selectedRun?.branch ?? 'branch unknown'}</small></div>
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
                  <div className="empty action-empty"><p>No deterministic analysis has been persisted.</p><button className="primary" onClick={() => analyze(selectedFailure)} disabled={busy}>Analyze failure</button></div>
                ) : (
                  <div className="analysis-grid">
                    <div className="analysis-summary">
                      <span className={`pill ${statusClass(selectedFailure.latest_analysis.category)}`}>{categoryLabel[selectedFailure.latest_analysis.category]}</span>
                      <h3>{selectedFailure.latest_analysis.summary}</h3>
                      <p>{selectedFailure.latest_analysis.confidence.explanation}</p>
                      <dl><div><dt>Score kind</dt><dd>{selectedFailure.latest_analysis.confidence.kind}</dd></div><div><dt>Score</dt><dd>{selectedFailure.latest_analysis.confidence.value ?? 'unavailable'}</dd></div><div><dt>Evidence completeness</dt><dd>{selectedFailure.latest_analysis.evidence_completeness}</dd></div></dl>
                    </div>
                    <div className="evidence-card"><h3>Evidence state</h3><p><strong>{selectedFailure.latest_analysis.supporting_evidence_ids.length}</strong> supporting citations</p><p><strong>{selectedFailure.latest_analysis.contradictory_evidence_ids.length}</strong> contradictory citations</p><p><strong>{selectedFailure.latest_analysis.missing_evidence.length}</strong> missing inputs</p></div>
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
