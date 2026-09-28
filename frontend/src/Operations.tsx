import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, operations, type Principal, type UserRecord, type SessionRecord,
  type RetentionPolicy, type RetentionChange, type RetentionPreview, type RetentionJob, type Tombstone } from './api';

const time = (value: string | null): string => value ? new Date(value).toLocaleString() : 'Not recorded';
const terminal = new Set(['succeeded', 'partial', 'cancelled', 'failed', 'dead_lettered']);

export function RecoveryForm() {
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      await operations.redeemRecovery(token, password);
      setMessage('Recovery completed. Sign in with your new password. All older sessions were revoked.');
    } catch (reason) { setError(String(reason)); }
    finally { setToken(''); setPassword(''); setBusy(false); }
  };
  return <details className="auth-card recovery-card"><summary>Recover an account</summary>
    <p>A system administrator must verify your identity and issue a one-time token. Tokens expire after 15 minutes.</p>
    <form onSubmit={submit} className="operations-form">
      <label>Recovery token<input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} required /></label>
      <label>New recovery password<input type="password" autoComplete="new-password" minLength={14} maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} required /></label>
      <button disabled={busy} type="submit">{busy ? 'Recovering…' : 'Set new password'}</button>
    </form>{error && <p role="alert" className="alert">{error}</p>}<p role="status">{message}</p>
  </details>;
}

export function AccountPanel({ principal, onSessionChanged }: { principal: Principal; onSessionChanged: (signedOut?: boolean) => Promise<void> }) {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [sessionPage, setSessionPage] = useState(0);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [selectedUser, setSelectedUser] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [reason, setReason] = useState('');
  const [operation, setOperation] = useState<'deactivate' | 'activate' | 'recovery' | 'revoke'>('revoke');
  const [confirmed, setConfirmed] = useState(false);
  const [recovery, setRecovery] = useState<{token: string; expires_at: string} | null>(null);
  const [managedSessions, setManagedSessions] = useState<SessionRecord[]>([]);
  const [managedPage, setManagedPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    if (principal.kind === 'user') operations.sessions(sessionPage * 10).then(rows => { if (active) setSessions(rows); })
      .catch(error => { if (active) setError(String(error)); });
    if (principal.system_admin) api.users().then(rows => {
      if (active) { setUsers(rows); setSelectedUser(id => rows.some(user => user.id === id) ? id : rows[0]?.id ?? ''); }
    }).catch(error => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, [principal.kind, principal.system_admin, principal.user_id, sessionPage, reload]);
  useEffect(() => {
    let active = true;
    setManagedSessions([]);
    if (principal.system_admin && selectedUser) operations.userSessions(selectedUser, managedPage * 10)
      .then(rows => { if (active) setManagedSessions(rows); }).catch(error => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, [selectedUser, principal.system_admin, managedPage, reload]);
  const changePassword = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try { await operations.changePassword(currentPassword, newPassword); await onSessionChanged();
      setReload(n => n + 1); setMessage('Password changed. This session was rotated; all previous sessions were revoked.');
    } catch (reason) { setError(String(reason)); }
    finally { setCurrentPassword(''); setNewPassword(''); setBusy(false); }
  };
  const revoke = async (row: SessionRecord) => {
    setBusy(true); setError('');
    try { await operations.revokeSession(row.id); if (row.current) await onSessionChanged(true);
      setReload(n => n + 1); setMessage('Session revoked.');
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  };
  const administer = async (event: FormEvent) => {
    event.preventDefault(); const user = users.find(row => row.id === selectedUser);
    if (!user || !confirmed) return;
    setBusy(true); setError(''); setMessage(''); setRecovery(null);
    try {
      if (operation === 'recovery') {
        const issued = await operations.issueRecovery(user, adminPassword, reason);
        setRecovery(issued); setMessage('One-time recovery issued. The old password and sessions no longer work.');
      } else if (operation === 'revoke') {
        await operations.revokeUserSessions(user.id, adminPassword, reason); setMessage('All sessions revoked.');
      } else {
        await operations.changeAccount(user, operation === 'activate', adminPassword, reason);
        setMessage(`Account ${operation === 'activate' ? 'activated' : 'deactivated'}. Historical reviewer attribution is preserved.`);
      }
      // A self-recovery token must remain visible until explicitly dismissed.
      if (user.id === principal.user_id && operation !== 'recovery') await onSessionChanged(true);
      else if (user.id !== principal.user_id) setReload(n => n + 1);
    } catch (reason) { setError(String(reason)); setReload(n => n + 1); }
    finally { setAdminPassword(''); setConfirmed(false); setBusy(false); }
  };
  return <section id="account" className="panel operations-panel" aria-labelledby="account-heading">
    <div className="panel-heading"><div><p className="eyebrow">IDENTITY AND SESSIONS</p><h2 id="account-heading">Account security</h2></div></div>
    {error && <div className="alert" role="alert">{error}</div>}<p role="status">{message}</p>
    <div className="settings-grid">
      {principal.kind === 'user' ? <>
        <section className="settings-block"><h3>Change password</h3><form className="operations-form" onSubmit={changePassword}>
          <label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required /></label>
          <label>New password<input type="password" autoComplete="new-password" minLength={14} maxLength={1024} value={newPassword} onChange={event => setNewPassword(event.target.value)} required /></label>
          <button type="submit" disabled={busy}>Change password and revoke older sessions</button>
        </form></section>
        <section className="settings-block"><h3>Your sessions</h3><p>Only session metadata is displayed; credentials are never returned.</p>
          <ul className="operations-records">{sessions.map(row => <li key={row.id}><div><strong>{row.current ? 'This session' : 'Other session'} — {row.state}</strong>
            <small>Created {time(row.created_at)} · Last used {time(row.last_used_at)} · Expires {time(row.expires_at)}</small></div>
            <button type="button" disabled={busy || row.state !== 'active'} onClick={() => revoke(row)}>{row.current ? 'Revoke this session' : 'Revoke session'}</button></li>)}</ul>
          <nav className="pagination" aria-label="Session pages"><button disabled={sessionPage === 0 || busy} onClick={() => setSessionPage(p => p - 1)}>Previous</button>
            <span>Page {sessionPage + 1}</span><button disabled={sessions.length < 10 || busy} onClick={() => setSessionPage(p => p + 1)}>Next</button></nav>
        </section>
      </> : <p className="limitation">The synthetic demo identity has no password or sessions. Sign in with a provisioned human account to use these controls.</p>}
      {principal.system_admin && <section className="settings-block system-status-block"><h3>System account administration</h3>
        <p>Deactivation, recovery, and revocation require a reason and explicit confirmation. Recovery invalidates the old password immediately; keep the issued token private.</p>
        <form className="operations-form" onSubmit={administer}>
          <label>Managed account<select value={selectedUser} onChange={event => { setSelectedUser(event.target.value); setManagedPage(0); setConfirmed(false); setRecovery(null); }}>
            {users.map(user => <option key={user.id} value={user.id}>{user.username} — {user.is_active ? 'active' : 'inactive'} · revision {user.lifecycle_version}</option>)}</select></label>
          <label>Account operation<select value={operation} onChange={event => { setOperation(event.target.value as typeof operation); setConfirmed(false); }}>
            <option value="revoke">Revoke all sessions</option><option value="deactivate">Deactivate account</option><option value="activate">Activate account</option><option value="recovery">Issue one-time recovery</option>
          </select></label>
          {principal.kind === 'user' && <label>Administrator current password<input type="password" autoComplete="current-password" value={adminPassword} onChange={event => setAdminPassword(event.target.value)} required /></label>}
          <label>Account operation reason<input value={reason} onChange={event => setReason(event.target.value)} required maxLength={2000} /></label>
          <label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I confirm this operation for the selected account.</label>
          <button type="submit" disabled={busy || !selectedUser || !confirmed || !reason.trim()}>Apply account operation</button>
        </form>
        {recovery && <div className="one-time-secret"><label>One-time recovery token<textarea readOnly value={recovery.token} spellCheck={false} /></label>
          <p>Expires {time(recovery.expires_at)}. This token is not stored in the browser or displayed again.</p>
          <button onClick={() => { setRecovery(null); void onSessionChanged(selectedUser === principal.user_id); setReload(n => n + 1); }}>Dismiss recovery token</button></div>}
        <h4>Managed account sessions</h4><ul className="operations-records">{managedSessions.map(row => <li key={row.id}><span>{row.current ? 'This session' : 'Session'} — {row.state}</span><small>Created {time(row.created_at)} · Expires {time(row.expires_at)}</small></li>)}</ul>
        <nav className="pagination" aria-label="Managed session pages"><button disabled={managedPage === 0} onClick={() => setManagedPage(p => p - 1)}>Previous</button><span>Page {managedPage + 1}</span><button disabled={managedSessions.length < 10} onClick={() => setManagedPage(p => p + 1)}>Next</button></nav>
      </section>}
    </div>
  </section>;
}

export function RetentionPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [policy, setPolicy] = useState<RetentionPolicy | null>(null);
  const [draft, setDraft] = useState<RetentionChange | null>(null);
  const [proposed, setProposed] = useState<RetentionPreview | null>(null);
  const [cleanup, setCleanup] = useState<RetentionPreview | null>(null);
  const [jobs, setJobs] = useState<RetentionJob[]>([]);
  const [tombstones, setTombstones] = useState<Tombstone[]>([]);
  const [tombstonePage, setTombstonePage] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const reload = useCallback(async () => {
    const [next, history, tombs] = await Promise.all([operations.retention(projectId), operations.retentionJobs(projectId), operations.tombstones(projectId, tombstonePage * 10)]);
    setPolicy(next); setJobs(history); setTombstones(tombs);
    setDraft(current => current ?? { expected_version: next.version, source_days: next.source_days,
      evidence_days: next.evidence_days, audit_days: next.audit_days, export_enabled: next.export_enabled,
      export_max_rows: next.export_max_rows, reason: '' });
  }, [projectId, tombstonePage]);
  useEffect(() => { let active = true;
    reload().catch(error => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    if (!jobs.some(job => !terminal.has(job.state))) return;
    const timer = window.setInterval(() => {
      operations.retentionJobs(projectId).then(next => {
        setJobs(next);
        if (next.every(job => terminal.has(job.state))) {
          setMessage('Cleanup finished. Review the recorded status and any blocked deletions below.');
          void reload(); onChanged();
        }
      }).catch(reason => setError(String(reason)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [jobs, projectId, reload, onChanged]);
  const update = (patch: Partial<RetentionChange>) => {
    setDraft(current => current ? { ...current, ...patch } : current); setProposed(null); setConfirmed(false);
  };
  const previewChange = async (event: FormEvent) => {
    event.preventDefault(); if (!draft) return; setBusy(true); setError('');
    try { setProposed(await operations.previewPolicy(projectId, draft)); setConfirmed(false); }
    catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!draft || !confirmed || !proposed) return; setBusy(true); setError('');
    try { const saved = await operations.saveRetention(projectId, draft); setPolicy(saved);
      setDraft({ ...draft, expected_version: saved.version, reason: '' }); setProposed(null); setCleanup(null); setConfirmed(false);
      setMessage(`Retention policy revision ${saved.version} saved. The worker enforces this policy automatically.`); onChanged();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  };
  const previewCurrent = async () => {
    setBusy(true); setError('');
    try { setCleanup(await operations.previewCleanup(projectId)); } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const enqueue = async () => {
    if (!cleanup) return; setBusy(true); setError('');
    try { const job = await operations.queueCleanup(projectId, cleanup); setJobs(previous => [job, ...previous.filter(row => row.job_id !== job.job_id)]);
      setCleanup(null); setMessage('Cleanup queued. Logical expiry is committed before any file is removed.'); onChanged();
    } catch (reason) { setError(String(reason)); setCleanup(null); } finally { setBusy(false); }
  };
  const summary = (proof: RetentionPreview) => <div className="retention-preview">
    <p>Preview at {time(proof.as_of)} · Policy revision {proof.policy_version}</p>
    <p><strong>{proof.source_ingestions}</strong> uploaded source records; <strong>{proof.source_runs}</strong> run sources; <strong>{proof.evidence_runs}</strong> run evidence bodies; <strong>{proof.audit_events}</strong> audit events eligible.</p>
    <p>Source cutoff {time(proof.cutoff_source)} · Evidence cutoff {time(proof.cutoff_evidence)} · Audit cutoff {time(proof.cutoff_audit)}</p>
    {proof.blocked_by_ingestion && <p role="status">An active ingestion currently defers cleanup.</p>}
  </div>;
  return <section className="settings-block system-status-block" aria-labelledby="retention-heading"><h3 id="retention-heading">Retention and evidence expiry</h3>
    <p>Expiry removes evidence bodies, copied excerpts, and eligible files. Outcomes, historical decision attribution, and minimal tombstones remain. Backups and previously downloaded exports must follow your separate disposal process.</p>
    {error && <div role="alert" className="alert">{error}</div>}<p role="status">{message}</p>
    {!policy || !draft ? <p role="status">Loading retention policy…</p> : <>
      <p>Saved policy revision {policy.version} · Updated {time(policy.updated_at)}</p>
      <form className="operations-form retention-fields" onSubmit={previewChange}>
        <label>Restricted source retention (days)<input type="number" min={1} max={3650} value={draft.source_days} onChange={event => update({ source_days: Number(event.target.value) })} required /></label>
        <label>Safe evidence retention (days)<input type="number" min={1} max={3650} value={draft.evidence_days} onChange={event => update({ evidence_days: Number(event.target.value) })} required /></label>
        <label>Project audit retention (days)<input type="number" min={1} max={3650} value={draft.audit_days} onChange={event => update({ audit_days: Number(event.target.value) })} required /></label>
        <label>Maximum audit export rows<input type="number" min={1} max={10000} value={draft.export_max_rows} onChange={event => update({ export_max_rows: Number(event.target.value) })} required /></label>
        <label className="checkbox-label"><input type="checkbox" checked={draft.export_enabled} onChange={event => update({ export_enabled: event.target.checked })} />Allow administrator audit exports</label>
        <label>Retention change reason<input maxLength={2000} value={draft.reason} onChange={event => update({ reason: event.target.value })} required /></label>
        <button type="submit" disabled={busy || !draft.reason.trim()}>Preview policy change</button>
      </form>
      {proposed && <>{summary(proposed)}<label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I understand the worker will enforce this policy and expiry cannot be undone.</label><button disabled={busy || !confirmed} onClick={save}>Save retention policy</button></>}
      <div className="status-actions"><button type="button" disabled={busy} onClick={previewCurrent}>Preview cleanup under saved policy</button>
        <button type="button" disabled={busy} onClick={() => { setDraft(null); setProposed(null); setCleanup(null); void reload().catch(reason => setError(String(reason))); }}>Reload saved policy</button></div>
      {cleanup && <>{summary(cleanup)}<button className="danger-button" disabled={busy} onClick={enqueue}>Confirm and queue cleanup</button></>}
      <h4>Cleanup jobs</h4>{jobs.length === 0 ? <p>No cleanup job has run yet.</p> : <ul className="operations-records">{jobs.map(job => <li key={job.job_id}>
        <div><strong>{job.state} · policy {job.policy_version}</strong><small>{job.job_id}</small><small>{Object.entries(job.progress).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join(' · ')}</small></div>
        {job.error_code && <span className="state failed">{job.error_code}</span>}</li>)}</ul>}
      <h4>Expiry tombstones</h4><ul className="operations-records">{tombstones.map(row => <li key={row.id}><span>{row.resource_type.replaceAll('_', ' ')} · {row.resource_id}</span><small>Expired {time(row.expired_at)} · policy {row.policy_version}</small></li>)}</ul>
      {tombstones.length === 0 && <p>No tombstones on this page.</p>}
      <nav className="pagination" aria-label="Tombstone pages"><button disabled={tombstonePage === 0} onClick={() => setTombstonePage(p => p - 1)}>Previous</button><span>Page {tombstonePage + 1}</span><button disabled={tombstones.length < 10} onClick={() => setTombstonePage(p => p + 1)}>Next</button></nav>
    </>}
  </section>;
}
