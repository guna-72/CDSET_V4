import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useMemo, useState, useRef } from 'react';
import { Plus, Play, StopCircle, RefreshCw, Loader2, ShieldCheck, HelpCircle, ChevronDown, ChevronUp } from 'lucide-react';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';
import { getExperiments, getExperimentRuns, runExperiment, cancelExperimentRun, getRun } from '../api';

const TYPE_INFO = {
  malformed_request: { label: 'Invalid Request', short: 'Sends intentionally invalid input to check validation.', category: 'Input validation' },
  empty_input: { label: 'Empty Input', short: 'Checks how the app handles a request with no data.', category: 'Input validation' },
  oversized_payload: { label: 'Large Input', short: 'Sends a bounded large request to check safe rejection.', category: 'Input validation' },
  boundary_input: { label: 'Unexpected Input', short: 'Uses unusual values and types to test validation.', category: 'Input validation' },
  invalid_content_type: { label: 'Wrong Data Format', short: 'Sends valid-looking data with the wrong format header.', category: 'Input validation' },
  request_burst: { label: 'Traffic Burst', short: 'Sends a bounded group of requests to test backpressure.', category: 'Traffic' },
  connection_refused: { label: 'Service Unavailable', short: 'Checks whether downstream connection failures are handled cleanly.', category: 'Network' },
  slow_response: { label: 'Slow Response', short: 'Calls the project’s endpoints with a short timeout to check timeout handling.', category: 'Network' },
  process_kill: { label: 'Unexpected Service Stop', short: 'Stops only the isolated test copy and checks failure handling.', category: 'Service recovery' },
  process_kill_recovery: { label: 'Service Recovery', short: 'Stops the isolated copy and checks whether recovery is possible.', category: 'Service recovery' },
  missing_env_var: { label: 'Missing Configuration', short: 'Removes one non-secret configuration value from the test copy.', category: 'Configuration' },
  missing_file: { label: 'Missing File', short: 'Temporarily removes a file from the isolated test copy.', category: 'Files' },
  permission_denied: { label: 'File Access Denied', short: 'Restricts access to a file inside the isolated test copy.', category: 'Files' },
  wrong_http_method: { label: 'Wrong Request Method', short: 'Uses a request method the page does not support (for example PUT).', category: 'Input validation' },
  null_json_body: { label: 'Empty JSON Value', short: 'Sends a JSON body that is just null instead of an object.', category: 'Input validation' },
  special_characters: { label: 'Special Characters', short: 'Sends quotes, emoji and HTML/SQL-like text to check safe handling.', category: 'Input validation' },
  long_url: { label: 'Very Long URL', short: 'Requests an address that is thousands of characters long.', category: 'Input validation' },
  unknown_route: { label: 'Page Not Found', short: 'Asks for a page that does not exist and expects a clean 404.', category: 'Input validation' },
  deeply_nested_json: { label: 'Deeply Nested Data', short: 'Sends JSON nested thousands of levels deep to check limits.', category: 'Input validation' },
  db_connection_refused: { label: 'Database Unavailable', short: 'Checks how the app handles an unavailable database connection.', category: 'Database' },
};

const STATUS_LABEL = {
  READY: 'Ready to test',
  RUNNING: 'Testing now',
  COMPLETED: 'Test finished',
  FAILED: 'Test error',
  BLOCKED: 'Blocked by safety',
  CANCEL_REQUESTED: 'Stopping test',
  CANCELLED: 'Test cancelled'
};

const OUTCOME_LABEL = {
  PASSED: 'Handled correctly',
  RECOVERED: 'Recovered successfully',
  APPLICATION_FAILURE: 'Application failed under fault',
  CRASHED: 'Application crashed',
  WEAK_HANDLING: 'Fault was not handled safely',
  TARGET_UNREACHABLE: 'Test target could not be reached',
  ANOMALY: 'Unexpected/unclassified response'
};

const statusTone = st => st === 'COMPLETED' ? 'pill-good' : st === 'FAILED' || st === 'BLOCKED' ? 'pill-bad' : st === 'RUNNING' || st === 'CANCEL_REQUESTED' ? 'pill-info' : st === 'READY' ? 'pill-mute' : 'pill-warn';
const outcomeTone = o => o === 'PASSED' || o === 'RECOVERED' ? 'pill-good' : o === 'APPLICATION_FAILURE' || o === 'CRASHED' ? 'pill-bad' : o === 'TARGET_UNREACHABLE' ? 'pill-mute' : 'pill-warn';

export default function ExperimentsPage({ setCurrentView, selectedProjectId }) {
  const [rows, setRows] = useState([]);
  const [filterType, setFilterType] = useState('All Types');
  const [filterStatus, setFilterStatus] = useState('All Status');
  const [busy, setBusy] = useState({});
  const [activeExpId, setActiveExpId] = useState(null);
  const [message, setMessage] = useState('');
  const [expanded, setExpanded] = useState({});

  const activeRunIdRef = useRef(null);
  const activeAbortRef = useRef(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (activeAbortRef.current) activeAbortRef.current.abort();
    };
  }, []);

  const load = async () => {
    if (!selectedProjectId) { setRows([]); return; }
    try {
      const { experiments = [] } = await getExperiments(selectedProjectId);
      const enriched = await Promise.all(experiments.map(async e => {
        let runs = [];
        try { runs = (await getExperimentRuns(e.id)).runs || []; } catch {}
        const latest = runs[0];
        const info = TYPE_INFO[e.fault_type] || {
          label: e.name || 'Resilience test',
          short: 'A project-specific resilience check.',
          category: e.category || 'Other'
        };
        return {
          ...e,
          typeLabel: info.label,
          typeInfo: info,
          intensity: e.risk_level <= 1 ? 'Low' : e.risk_level === 2 ? 'Medium' : 'Higher',
          result: latest?.status || e.status,
          latestRun: latest
        };
      }));

      if (!isMountedRef.current) return;
      setRows(enriched);

      const running = enriched.find(item => (item.latestRun?.status === 'RUNNING' || item.status === 'RUNNING') && busy[item.id] !== 'cancel');
      if (running) {
        setActiveExpId(running.id);
        activeRunIdRef.current = running.latestRun?.id || null;
      } else if (!activeRunIdRef.current) {
        setActiveExpId(null);
      }
    } catch (e) {
      if (isMountedRef.current) setMessage(friendlyError(e) || 'Could not load experiments.');
    }
  };

  useEffect(() => {
    load();
  }, [selectedProjectId]);

  // Periodic poll while an experiment is actively executing
  useEffect(() => {
    if (!activeExpId) return;
    const interval = setInterval(() => {
      load();
    }, 2500);
    return () => clearInterval(interval);
  }, [activeExpId, selectedProjectId]);

  const run = async (e) => {
    if (busy[e.id] || activeExpId) return;
    setMessage('');
    setActiveExpId(e.id);
    setBusy(b => ({ ...b, [e.id]: 'run' }));

    const abortCtrl = new AbortController();
    activeAbortRef.current = abortCtrl;

    // Optimistically update status to RUNNING in table
    setRows(prev => prev.map(item => item.id === e.id ? {
      ...item,
      result: 'RUNNING',
      latestRun: {
        ...(item.latestRun || {}),
        status: 'RUNNING',
        started_at: Date.now() / 1000
      }
    } : item));

    try {
      const r = await runExperiment(e.id, abortCtrl.signal);
      const runId = r.run_id;
      activeRunIdRef.current = runId;
      localStorage.setItem('chaosTutorRunId', runId);
      localStorage.setItem('chaosTutorProjectId', selectedProjectId);
      window.dispatchEvent(new Event('chaosTutorRunChanged'));

      setRows(prev => prev.map(item => item.id === e.id ? {
        ...item,
        result: 'RUNNING',
        latestRun: {
          id: runId,
          status: 'RUNNING',
          experiment_id: e.id,
          started_at: Date.now() / 1000
        }
      } : item));

      setMessage(`Testing “${e.typeLabel}”. The experiment is running against the isolated project copy.`);

      for (let i = 0; i < 180; i++) {
        if (abortCtrl.signal.aborted) break;
        await new Promise(x => setTimeout(x, 1000));
        if (abortCtrl.signal.aborted) break;

        try {
          const current = await getRun(runId);
          if (['COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED'].includes(current.status)) {
            setMessage(`${e.typeLabel}: ${STATUS_LABEL[current.status] || current.status}${current.outcome ? ` — ${OUTCOME_LABEL[current.outcome] || current.outcome}` : ''}`);
            break;
          }
        } catch {
          if (abortCtrl.signal.aborted) break;
        }
      }
      await load();
    } catch (err) {
      if (err?.name === 'AbortError') {
        setMessage(`Experiment “${e.typeLabel}” was stopped.`);
      } else {
        setMessage(friendlyError(err) || 'Experiment could not run.');
      }
    } finally {
      if (isMountedRef.current) {
        activeRunIdRef.current = null;
        activeAbortRef.current = null;
        setActiveExpId(null);
        setBusy(b => ({ ...b, [e.id]: null }));
        await load();
      }
    }
  };

  const cancel = async (e) => {
    const runId = activeRunIdRef.current || e.latestRun?.id || localStorage.getItem('chaosTutorRunId');
    if (activeAbortRef.current) {
      activeAbortRef.current.abort();
    }
    setActiveExpId(null);
    activeRunIdRef.current = null;
    localStorage.removeItem('chaosTutorRunId');

    setBusy(b => ({ ...b, [e.id]: 'cancel' }));
    setMessage(`Cancelled “${e.typeLabel}”. Test stopped.`);

    // Immediately mark as CANCELLED in UI for instantaneous feedback
    setRows(prev => prev.map(item => item.id === e.id ? {
      ...item,
      result: 'CANCELLED',
      latestRun: {
        ...(item.latestRun || {}),
        status: 'CANCELLED'
      }
    } : item));

    try {
      if (runId) {
        const r = await cancelExperimentRun(runId);
        setMessage(r.message || `Cancelled “${e.typeLabel}”. Test stopped.`);
      }
    } catch (err) {
      setMessage(friendlyError(err) || 'Could not stop the test.');
    } finally {
      if (isMountedRef.current) {
        setBusy(b => ({ ...b, [e.id]: null }));
        await load();
      }
    }
  };

  const filtered = useMemo(() => rows.filter(e =>
    (filterType === 'All Types' || e.typeLabel === filterType) &&
    (filterStatus === 'All Status' || e.result === filterStatus)
  ), [rows, filterType, filterStatus]);

  const activeRunningItem = useMemo(() => {
    return rows.find(item =>
      (item.id === activeExpId || item.latestRun?.status === 'RUNNING' || item.status === 'RUNNING') &&
      busy[item.id] !== 'cancel' &&
      item.latestRun?.status !== 'CANCELLED' &&
      item.status !== 'CANCELLED'
    );
  }, [rows, activeExpId, busy]);

  if (!selectedProjectId) {
    return (
      <div style={{ padding: 32, color: '#fff' }}>
        <div className="glass-card" style={{ padding: 40, textAlign: 'center' }}>
          <h2>No project selected</h2>
          <p style={{ color: '#94a3b8' }}>Import a project before running resilience tests.</p>
          <button className="btn-primary" onClick={() => setCurrentView('import')}>Import Project</button>
        </div>
      </div>
    );
  }

  const types = ['All Types', ...new Set(rows.map(e => e.typeLabel))];

  return (
    <div style={{ padding: 32, color: '#fff', position: 'relative', zIndex: 2 }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <BlurText as="h1" text="Experiments" animateBy="letters" delay={20} style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }} />
          <p style={{ color: '#94a3b8', fontSize: 13, margin: 0 }}>Simple tests that check how your project behaves when something goes wrong.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={filterType} onChange={e => setFilterType(e.target.value)} style={selectStyle}>
            {types.map(x => <option key={x} value={x}>{x}</option>)}
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={selectStyle}>
            {['All Status', 'READY', 'RUNNING', 'COMPLETED', 'FAILED', 'BLOCKED', 'CANCEL_REQUESTED', 'CANCELLED'].map(x => (
              <option key={x} value={x}>{x === 'All Status' ? 'All Status' : STATUS_LABEL[x] || x}</option>
            ))}
          </select>
          <button className="btn-secondary" onClick={load} title="Refresh test cases">
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      <div style={{ marginBottom: 14, padding: '10px 13px', borderRadius: 9, background: 'rgba(99,102,241,.06)', border: '1px solid rgba(99,102,241,.16)', color: '#cbd5e1', fontSize: 11, lineHeight: 1.5 }}>
        Choose a test, click <strong>Test</strong>, and CD-SET will run it against a temporary copy of your project. The original project files are not changed.
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
        <TrustBadge icon={<ShieldCheck size={15} />} title="Real project copy" text="Tests run against an isolated copy, not the original files." />
        <TrustBadge icon={<HelpCircle size={15} />} title="Evidence is recorded" text="Baseline, fault response, status, outcome, isolation, and cleanup are stored with each run." />
      </div>

      <div style={{ marginBottom: 16, padding: '10px 13px', borderRadius: 9, background: 'rgba(16,185,129,.06)', border: '1px solid rgba(16,185,129,.16)', color: '#a7f3d0', fontSize: 11, lineHeight: 1.55 }}>
        Evidence scope: tests run against a temporary copy of the imported project. A completed test proves the recorded behavior in this controlled environment; it does not prove identical production infrastructure.
      </div>

      {/* Active Running Experiment Notification Banner with Stop/Cancel Button */}
      {activeRunningItem && (
        <div style={{
          marginBottom: 16,
          padding: '12px 18px',
          borderRadius: 10,
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.28)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: '1 1 auto' }}>
            <Loader2 size={16} className="spin" color="#f87171" style={{ flexShrink: 0 }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#fca5a5' }}>
                Experiment in progress: <span style={{ color: '#fff' }}>{activeRunningItem.typeLabel}</span>
              </div>
              <div style={{ fontSize: 11, color: '#94a3b8' }}>
                Testing against isolated copy. Click Cancel to stop and clean up safely.
              </div>
            </div>
          </div>
          <button
            className="btn-danger"
            onClick={() => cancel(activeRunningItem)}
            disabled={busy[activeRunningItem.id] === 'cancel'}
            style={{
              padding: '7px 16px',
              fontSize: 12,
              fontWeight: 600,
              flexShrink: 0,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6
            }}
          >
            {busy[activeRunningItem.id] === 'cancel' ? (
              <>
                <Loader2 size={14} className="spin" />
                <span>Stopping experiment…</span>
              </>
            ) : (
              <>
                <StopCircle size={14} />
                <span>Cancel Experiment</span>
              </>
            )}
          </button>
        </div>
      )}

      {message && (
        <div style={{ marginBottom: 16, padding: '11px 13px', borderRadius: 9, background: 'rgba(99,102,241,.1)', border: '1px solid rgba(99,102,241,.25)', color: '#c7d2fe', fontSize: 12 }}>
          {message}
        </div>
      )}

      {/* Main Experiments Table Card */}
      <SpotlightCard spotlightColor="rgba(167,139,250,.2)" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto', width: '100%' }}>
          <table className="tc-table" style={{ minWidth: 1040, width: '100%', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '21%' }} />
              <col style={{ width: '25%' }} />
              <col style={{ width: '8%' }} />
              <col style={{ width: '13%' }} />
              <col style={{ width: '19%' }} />
              <col style={{ width: '14%' }} />
            </colgroup>
            <thead>
              <tr>
                <th>Test case</th>
                <th>What it checks</th>
                <th>Risk</th>
                <th>Status</th>
                <th>Latest result</th>
                <th style={{ textAlign: 'right', paddingRight: 16 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length ? filtered.map(e => {
                const latest = e.latestRun;
                const status = latest?.status || e.status;
                const isRunning = (activeExpId === e.id || status === 'RUNNING') && busy[e.id] !== 'cancel' && status !== 'CANCELLED';
                const isCanceling = busy[e.id] === 'cancel';
                const isStarting = busy[e.id] === 'run';
                const open = expanded[e.id];

                return (
                  <React.Fragment key={e.id}>
                    <tr className="tc-row">
                      {/* Test Case */}
                      <td style={{ overflow: 'hidden' }}>
                        <div className="tc-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.typeLabel}>
                          {e.typeLabel}
                        </div>
                        <div className="tc-sub" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.typeInfo.category}>
                          {e.typeInfo.category}
                        </div>
                      </td>

                      {/* What it checks */}
                      <td>
                        <div className="tc-clamp" title={e.typeInfo.short}>
                          {e.typeInfo.short}
                        </div>
                      </td>

                      {/* Risk */}
                      <td>
                        <span className={`pill ${e.intensity === 'Low' ? 'pill-good' : e.intensity === 'Medium' ? 'pill-warn' : 'pill-bad'}`}>
                          {e.intensity}
                        </span>
                      </td>

                      {/* Status */}
                      <td style={{ overflow: 'hidden' }}>
                        <span
                          className={`pill ${statusTone(status)}`}
                          title={STATUS_LABEL[status] || status}
                          style={{ maxWidth: '100%', boxSizing: 'border-box' }}
                        >
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {STATUS_LABEL[status] || status}
                          </span>
                        </span>
                      </td>

                      {/* Latest Result - completely contained so it never spills into Actions */}
                      <td style={{ overflow: 'hidden' }}>
                        {latest?.outcome ? (
                          <span
                            className={`pill ${outcomeTone(latest.outcome)}`}
                            title={OUTCOME_LABEL[latest.outcome] || latest.outcome}
                            style={{
                              maxWidth: '100%',
                              boxSizing: 'border-box',
                              display: 'inline-flex',
                              alignItems: 'center'
                            }}
                          >
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }}>
                              {OUTCOME_LABEL[latest.outcome] || latest.outcome}
                            </span>
                          </span>
                        ) : (
                          <span style={{ color: '#64748b' }}>Not run yet</span>
                        )}
                      </td>

                      {/* Actions: Test, Cancel, and Expand Evidence */}
                      <td style={{ textAlign: 'right', paddingRight: 16 }}>
                        <div className="tc-actions" style={{ display: 'inline-flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center', whiteSpace: 'nowrap', flexWrap: 'nowrap' }}>
                          {isRunning ? (
                            <button
                              className="btn-danger"
                              onClick={() => cancel(e)}
                              disabled={isCanceling}
                              title="Cancel and stop this experiment"
                              style={{
                                padding: '6px 12px',
                                fontSize: 12,
                                fontWeight: 600,
                                whiteSpace: 'nowrap',
                                flexShrink: 0
                              }}
                            >
                              {isCanceling ? (
                                <>
                                  <Loader2 size={13} className="spin" />
                                  <span>Stopping…</span>
                                </>
                              ) : (
                                <>
                                  <StopCircle size={13} />
                                  <span>Cancel</span>
                                </>
                              )}
                            </button>
                          ) : (
                            <button
                              className="btn-primary"
                              onClick={() => run(e)}
                              disabled={!!activeExpId || !!busy[e.id] || (e.status !== 'READY' && !latest)}
                              title={activeExpId ? 'Another experiment is currently running' : 'Run this resilience test'}
                              style={{
                                padding: '6px 14px',
                                fontSize: 12,
                                whiteSpace: 'nowrap',
                                flexShrink: 0
                              }}
                            >
                              {isStarting ? (
                                <>
                                  <Loader2 size={13} className="spin" />
                                  <span>Testing…</span>
                                </>
                              ) : (
                                <>
                                  <Play size={13} />
                                  <span>Test</span>
                                </>
                              )}
                            </button>
                          )}
                          {latest && (
                            <button
                              className="btn-secondary"
                              aria-label={open ? 'Hide evidence' : 'Show evidence'}
                              title={open ? 'Hide evidence' : 'View test evidence'}
                              onClick={() => setExpanded(x => ({ ...x, [e.id]: !x[e.id] }))}
                              style={{ padding: '6px 9px', flexShrink: 0 }}
                            >
                              {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {open && latest && (
                      <tr>
                        <td colSpan="6" style={{ padding: '6px 20px 20px' }}>
                          <EvidencePanel run={latest} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              }) : (
                <tr>
                  <td colSpan="6" style={{ padding: 35, textAlign: 'center', color: '#64748b' }}>
                    No test cases match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SpotlightCard>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
        <button className="btn-secondary" onClick={() => setCurrentView('chaos-lab')}>
          <Plus size={15} /> Create a test
        </button>
      </div>
    </div>
  );
}

function TrustBadge({ icon, title, text }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 11px', border: '1px solid rgba(255,255,255,.08)', borderRadius: 9, background: 'rgba(255,255,255,.025)' }}>
      <span style={{ color: '#34d399', flexShrink: 0 }}>{icon}</span>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#e2e8f0' }}>{title}</div>
        <div style={{ fontSize: 10, color: '#64748b' }}>{text}</div>
      </div>
    </div>
  );
}

function EvidencePanel({ run }) {
  const baseline = run.baseline || {};
  const chaos = run.chaos || {};
  const ok = run.outcome === 'PASSED' || run.outcome === 'RECOVERED';
  return (
    <div className="tc-evidence">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <strong style={{ fontSize: 13 }}>Test evidence</strong>
        <span className={`pill ${ok ? 'pill-good' : 'pill-warn'}`}>
          {ok ? 'Expected resilience behavior observed' : 'Review observed behavior'}
        </span>
      </div>
      <div className="tc-evidence-grid">
        <Evidence label="Run status" value={STATUS_LABEL[run.status] || run.status} />
        <Evidence label="Observed result" value={OUTCOME_LABEL[run.outcome] || run.outcome || 'Not recorded'} />
        <Evidence label="Baseline" value={baseline?.ok === true ? 'Healthy before fault' : 'Recorded / unavailable'} />
        <Evidence label="After fault" value={chaos?.ok === true ? 'Application stayed responsive' : 'Fault response was observed'} />
      </div>
      <p style={{ fontSize: 11, color: '#64748b', margin: '12px 0 0', lineHeight: 1.5 }}>
        This proves what happened in CD-SET's isolated test environment. It does not prove that production is identical; use the same runtime, dependencies, configuration, and deployment settings when validating in your real environment.
      </p>
    </div>
  );
}

function Evidence({ label, value }) {
  return (
    <div className="tc-evidence-cell">
      <div className="k">{label}</div>
      <div className="v" style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{String(value)}</div>
    </div>
  );
}

const selectStyle = {
  background: '#111522',
  color: '#e2e8f0',
  border: '1px solid rgba(255,255,255,.1)',
  borderRadius: 8,
  padding: '8px 10px',
  outline: 'none'
};
