import { friendlyError, friendlyLogLine } from '../utils/friendlyError';
import React, { useState, useEffect, useRef } from 'react';
import { Wifi, WifiOff, Cpu, Power, Target, Zap, CheckCircle2, StopCircle, FileWarning, Gauge, Ban, Database, FileX2, ShieldAlert, Radio, Folder, RefreshCw, BrainCircuit, ShieldCheck } from 'lucide-react';
import BlurText from '../components/BlurText';
import Tooltip from '../components/Tooltip';
import SpotlightCard from '../components/SpotlightCard';
import { setPreset, getLogs, getRun, cancelExperimentRun, isBackendReachable, getPresetAvailability, listProjects } from '../api';

// Outcomes where the project did NOT handle the injected error correctly -> the AI Tutor is needed.
const PROBLEM_OUTCOMES = ['APPLICATION_FAILURE', 'CRASHED', 'WEAK_HANDLING', 'ANOMALY'];
const HANDLED_OUTCOMES = ['PASSED', 'RECOVERED'];

const faultTypes = [
  { id: 'network-delay', preset: 'high_latency', label: 'Slow Response', desc: 'Calls the project’s endpoints with a short timeout to check timeout handling', icon: Wifi, color: '#f59e0b' },
  { id: 'malformed-request', preset: 'malformed_request', label: 'Invalid Request', desc: 'Sends malformed data to test validation and error handling', icon: FileWarning, color: '#ef4444' },
  { id: 'empty-input', preset: 'empty_input', label: 'Empty Input', desc: 'Checks how the application handles a request with no data', icon: FileX2, color: '#f97316' },
  { id: 'large-input', preset: 'oversized_payload', label: 'Large Input', desc: 'Tests safe rejection of a bounded oversized request', icon: Gauge, color: '#f97316' },
  { id: 'unexpected-input', preset: 'boundary_input', label: 'Unexpected Input', desc: 'Tests unusual values and types at the input boundary', icon: ShieldAlert, color: '#f59e0b' },
  { id: 'wrong-format', preset: 'invalid_content_type', label: 'Wrong Data Format', desc: 'Tests handling of an unexpected request content type', icon: FileWarning, color: '#ef4444' },
  { id: 'traffic-burst', preset: 'request_burst', label: 'Traffic Burst', desc: 'Sends bounded concurrent traffic to test backpressure', icon: Gauge, color: '#f97316' },
  { id: 'service-unavailable', preset: 'connection_refused', label: 'Service Unavailable', desc: 'Tests handling when a downstream service cannot be reached', icon: Ban, color: '#ef4444' },
  { id: 'service-stop', preset: 'server_crash_503', label: 'Unexpected Service Stop', desc: 'Stops only the isolated test service and observes the response', icon: Power, color: '#ef4444' },
  { id: 'recovery-after-stop', preset: 'process_kill_recovery', label: 'Recovery After Stop', desc: 'Checks whether the isolated service can recover after termination', icon: Radio, color: '#10b981' },
  { id: 'missing-config', preset: 'missing_env_var', label: 'Missing Configuration', desc: 'Checks whether missing configuration is handled clearly', icon: FileWarning, color: '#f59e0b' },
  { id: 'missing-file', preset: 'missing_file', label: 'Missing File', desc: 'Checks handling when a required file is unavailable', icon: FileX2, color: '#f97316' },
  { id: 'file-access', preset: 'permission_denied', label: 'File Access Denied', desc: 'Tests handling of a permission failure inside the test copy', icon: ShieldAlert, color: '#ef4444' },
  { id: 'wrong-method', preset: 'wrong_http_method', label: 'Wrong Request Method', desc: 'Uses a request method the page does not support', icon: Ban, color: '#f97316' },
  { id: 'null-body', preset: 'null_json_body', label: 'Empty JSON Value', desc: 'Sends a JSON body that is just null instead of an object', icon: FileX2, color: '#f97316' },
  { id: 'special-chars', preset: 'special_characters', label: 'Special Characters', desc: 'Sends quotes, emoji and HTML/SQL-like text to check safe handling', icon: ShieldAlert, color: '#f59e0b' },
  { id: 'long-url', preset: 'long_url', label: 'Very Long URL', desc: 'Requests an address that is thousands of characters long', icon: Gauge, color: '#f97316' },
  { id: 'unknown-page', preset: 'unknown_route', label: 'Page Not Found', desc: 'Asks for a page that does not exist and expects a clean 404', icon: FileWarning, color: '#f59e0b' },
  { id: 'nested-data', preset: 'deeply_nested_json', label: 'Deeply Nested Data', desc: 'Sends JSON nested thousands of levels deep to check limits', icon: FileWarning, color: '#ef4444' },
  { id: 'database-unavailable', preset: 'db_connection_refused', label: 'Database Unavailable', desc: 'Checks handling of an unavailable database dependency', icon: Database, color: '#ef4444' },
];

const FAULT_CATEGORY = {
  malformed_request: 'Input validation', empty_input: 'Input validation', oversized_payload: 'Input validation', boundary_input: 'Input validation',
  invalid_content_type: 'Input validation', wrong_http_method: 'Input validation', null_json_body: 'Input validation', special_characters: 'Input validation',
  long_url: 'Input validation', unknown_route: 'Input validation', deeply_nested_json: 'Input validation',
  high_latency: 'Traffic and network', request_burst: 'Traffic and network', connection_refused: 'Traffic and network',
  server_crash_503: 'Service recovery', process_kill_recovery: 'Service recovery',
  missing_env_var: 'Configuration and files', missing_file: 'Configuration and files', permission_denied: 'Configuration and files',
  db_connection_refused: 'Database',
};
const FAULT_GROUPS = Object.entries(faultTypes.reduce((acc, f) => { const c = FAULT_CATEGORY[f.preset] || 'Other'; (acc[c] = acc[c] || []).push(f); return acc; }, {}));

const initialTerminalLog = [];

export default function ChaosLabPage({ setCurrentView, selectedProjectId, setSelectedProjectId }) {
  const [selectedFault, setSelectedFault] = useState('network-delay');
  const [terminalLog, setTerminalLog] = useState(initialTerminalLog);
  const [isInjecting, setIsInjecting] = useState(false);
  const abortRef = useRef(null);
  const [flowStep, setFlowStep] = useState(0);
  const [backendUp, setBackendUp] = useState(null); // null = checking, true/false after check
  const [availability, setAvailability] = useState({}); // preset -> {available, reason}
  const [elapsed, setElapsed] = useState(0);
  const [activeStatus, setActiveStatus] = useState('IDLE');
  const activeRunRef = useRef(null);
  const terminalRef = useRef(null);
  const hydratedRef = useRef(false);
  const labStorageKey = `chaosTutorLabState:${selectedProjectId || 'none'}`;
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState('');
  const [lastResult, setLastResult] = useState(null); // { runId, outcome, status }
  const [autoOpenTutor, setAutoOpenTutor] = useState(() => localStorage.getItem('chaosTutorAutoOpen') !== 'off');
  const mountedRef = useRef(true);
  const skipPersistRef = useRef(false);
  const autoOpenRef = useRef(autoOpenTutor);
  const selectedProject = projects.find(p => p.id === selectedProjectId) || null;
  const selectedProjectRef = useRef(null);
  selectedProjectRef.current = selectedProject;
  useEffect(() => { autoOpenRef.current = autoOpenTutor; localStorage.setItem('chaosTutorAutoOpen', autoOpenTutor ? 'on' : 'off'); }, [autoOpenTutor]);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const loadProjects = async () => {
    setProjectsLoading(true);
    try { setProjects((await listProjects()).projects || []); setProjectsError(''); }
    catch (e) { setProjectsError(friendlyError(e) || 'Could not load projects.'); }
    finally { setProjectsLoading(false); }
  };
  useEffect(() => { loadProjects(); }, []);

  // Pick which imported project the chaos test will run against.
  const chooseProject = (p) => {
    if (isInjecting || p.id === selectedProjectId) return;
    localStorage.setItem('chaosTutorProjectId', p.id);
    localStorage.removeItem('chaosTutorRunId');
    setSelectedProjectId?.(p.id);
    setLastResult(null);
    window.dispatchEvent(new Event('chaosTutorRunChanged'));
  };

  const monitorRun = async (runId, opts = {}) => {
    activeRunRef.current = runId;
    setIsInjecting(true);
    setActiveStatus('RUNNING');
    let finished = false;
    for (let i = 0; i < 240; i++) {
      try {
        const current = await getRun(runId);
        const started = current.started_at ? Number(current.started_at) : null;
        const finishedAt = current.finished_at ? Number(current.finished_at) : null;
        const now = Date.now() / 1000;
        const seconds = started ? Math.max(0, Math.round((finishedAt || now) - started)) : i;
        setElapsed(seconds);
        setActiveStatus(current.status || 'RUNNING');
        if (['COMPLETED','FAILED','BLOCKED','CANCELLED'].includes(current.status)) {
          finished = true;
          setFlowStep(4);
          const outcomeText = current.outcome === 'PASSED' ? 'Handled correctly' : current.outcome === 'RECOVERED' ? 'Recovered successfully' : current.outcome === 'APPLICATION_FAILURE' ? 'Application failed under the test condition' : current.outcome === 'CRASHED' ? 'Application crashed under the test condition' : current.outcome === 'WEAK_HANDLING' ? 'Application did not handle the condition safely' : current.outcome === 'TARGET_UNREACHABLE' ? 'Test target could not be reached' : current.outcome === 'ANOMALY' ? 'Unexpected response — review the logs' : (current.outcome || (current.error ? `Could not run: ${current.error}` : 'No outcome recorded'));
          // Tag/color reflect the actual outcome, not just "the run finished" — a failed or
          // crashed test must not show the same green "RECOV" tag as a genuine RECOVERED outcome.
          const isSuccessOutcome = current.status === 'COMPLETED' && (current.outcome === 'PASSED' || current.outcome === 'RECOVERED');
          const isFailureOutcome = current.status === 'COMPLETED' && ['APPLICATION_FAILURE', 'CRASHED', 'WEAK_HANDLING'].includes(current.outcome);
          const finishTag = current.outcome === 'RECOVERED' ? 'RECOV' : isSuccessOutcome ? 'PASS' : isFailureOutcome ? 'FAIL' : 'WARN';
          const finishColor = isSuccessOutcome ? '#34d399' : isFailureOutcome ? '#ef4444' : '#f59e0b';
          appendLog(finishTag, `Test finished: ${outcomeText}`, finishColor);
          setLastResult({ runId, outcome: current.outcome || null, status: current.status });
          window.dispatchEvent(new Event('chaosTutorRunChanged'));
          if (opts.autoOpen && autoOpenRef.current && current.status === 'COMPLETED' && PROBLEM_OUTCOMES.includes(current.outcome)) {
            appendLog('TUTOR', 'The project did not handle this error correctly — opening AI Tutor with the code and a fix…', '#a5b4fc');
            setTimeout(() => { if (mountedRef.current) setCurrentView?.('tutor'); }, 2200);
          }
          // Keep the completed run id so AI Tutor, Reports, and Evidence can open the same run.
          localStorage.setItem('chaosTutorRunId', runId);
          activeRunRef.current = null;
          try { const savedState = JSON.parse(localStorage.getItem(labStorageKey) || '{}'); savedState.runId = null; savedState.activeStatus = current.status; savedState.lastResult = { runId, outcome: current.outcome || null, status: current.status }; localStorage.setItem(labStorageKey, JSON.stringify(savedState)); } catch {}
          break;
        }
      } catch (e) {
        appendLog('WARN', `Could not update the test status. ${friendlyError(e)}`, '#f59e0b');
      }
      await new Promise(r => setTimeout(r, 1000));
    }
    if (!finished) {
      setActiveStatus('MONITORING_TIMEOUT');
      appendLog('WARN', 'Browser monitoring window ended. The backend run remains authoritative.', '#f59e0b');
    }
    setIsInjecting(false);
  };

  // Restore this project's own Chaos Lab state whenever the selected project changes.
  useEffect(() => {
    hydratedRef.current = false;
    skipPersistRef.current = true;
    activeRunRef.current = null;
    setTerminalLog(initialTerminalLog);
    setFlowStep(0);
    setElapsed(0);
    setActiveStatus('IDLE');
    setLastResult(null);
    try {
      const saved = JSON.parse(localStorage.getItem(labStorageKey) || '{}');
      if (saved.selectedFault) setSelectedFault(saved.selectedFault);
      if (Array.isArray(saved.terminalLog) && saved.terminalLog.length) setTerminalLog(saved.terminalLog.slice(-100));
      if (saved.lastResult) setLastResult(saved.lastResult);
      if (saved.runId) {
        setFlowStep(3);
        monitorRun(saved.runId).catch(() => {});
      }
    } catch {}
    hydratedRef.current = true;
    isBackendReachable().then(setBackendUp);
  }, [labStorageKey]);

  // Grey out tests this project can't run (e.g. no database detected) instead of
  // letting the user click and get an error afterwards.
  useEffect(() => {
    if (!selectedProjectId) { setAvailability({}); return; }
    let cancelled = false;
    getPresetAvailability(selectedProjectId).then(a => { if (!cancelled) setAvailability(a); }).catch(() => {});
    return () => { cancelled = true; };
  }, [selectedProjectId]);

  useEffect(() => {
    const current = faultTypes.find(f => f.id === selectedFault);
    if (current && availability[current.preset] && !availability[current.preset].available) {
      const firstOk = faultTypes.find(f => availability[f.preset]?.available);
      if (firstOk) setSelectedFault(firstOk.id);
    }
  }, [availability]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    if (skipPersistRef.current) { skipPersistRef.current = false; return; }
    localStorage.setItem(labStorageKey, JSON.stringify({ selectedFault, terminalLog: terminalLog.slice(-100), runId: activeRunRef.current, elapsed, activeStatus, projectId: selectedProjectId, lastResult }));
  }, [selectedFault, terminalLog, elapsed, activeStatus, lastResult, labStorageKey]);

  const nowTime = () => new Date().toTimeString().slice(0, 8);

  const appendLog = (tag, msg, color) => {
    setTerminalLog(prev => [...prev, { time: nowTime(), tag, msg, color }]);
    requestAnimationFrame(() => {
      if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    });
  };

  // Real flow: drives the actual backend chaos engine + test subject.
  const runRealInjection = async () => {
    const faultLabel = faultTypes.find(f => f.id === selectedFault)?.label;
    const preset = faultTypes.find(f => f.id === selectedFault)?.preset;
    const projectLabel = selectedProjectRef.current?.name || 'selected project';
    setLastResult(null);
    appendLog('CHAOS', `Running “${faultLabel}” on project “${projectLabel}”`, '#f87171');
    try {
      abortRef.current = new AbortController();
      const result = await setPreset(preset, abortRef.current.signal, selectedProjectId);
      activeRunRef.current = result.run_id;
      localStorage.setItem('chaosTutorRunId', result.run_id);
      setFlowStep(2);
      localStorage.setItem(labStorageKey, JSON.stringify({ selectedFault, terminalLog, runId: result.run_id, elapsed: 0, activeStatus: 'RUNNING', projectId: selectedProjectId, lastResult: null }));
      appendLog('INFO', `Test started. Run ID ${result.run_id.slice(0, 10)}… The backend is now checking the isolated project copy.`, '#60a5fa');
      setFlowStep(3);

      await monitorRun(result.run_id, { autoOpen: true });
      try {
        const { events = [] } = await getLogs(result.run_id);
        events.slice(-8).forEach(e => appendLog(e.type || 'INFO', friendlyLogLine(e.message || ''), tagColor(String(e.type || 'INFO').toUpperCase())));
      } catch (_) {}
      appendLog('SYSTEM', 'Result saved. Open Experiments for the evidence, Logs for the event timeline, or AI Tutor for the explanation.', '#94a3b8');
    } catch (err) {
      if (err?.name === 'AbortError') appendLog('WARN', 'Client-side request cancelled.', '#f59e0b');
      else appendLog('ERROR', `The test could not run. ${friendlyError(err)}`, '#ef4444');
    }
  };

  // No simulated chaos is permitted. If the backend is unavailable, fail closed.
  const runScriptedFallback = () => {
    appendLog('BLOCKED', 'Backend unavailable. No simulated experiment will be run.', '#ef4444');
    appendLog('SYSTEM', 'Start the FastAPI backend and retry. No fake result was generated.', '#94a3b8');
    setFlowStep(0);
    return Promise.resolve();
  };

  const handleCancelInjection = async () => {
    if (abortRef.current) abortRef.current.abort();
    if (activeRunRef.current) {
      try { await cancelExperimentRun(activeRunRef.current); appendLog('WARN', 'Stop requested. CD-SET is stopping the isolated test and cleaning up resources.', '#f59e0b'); }
      catch (e) { appendLog('ERROR', `Could not stop the test. ${friendlyError(e)}`, '#ef4444'); }
    } else {
      appendLog('WARN', 'Injection cancellation requested.', '#f59e0b');
    }
    setIsInjecting(false);
    setFlowStep(0);
  };

  const handleInject = async () => {
    if (isInjecting) return;
    setIsInjecting(true);
    setFlowStep(1);

    const up = backendUp ?? await isBackendReachable();
    setBackendUp(up);

    if (up) {
      await runRealInjection();
    } else {
      await runScriptedFallback();
    }

    // Don't blanket-reset the step tracker here: monitorRun sets flowStep to 4
    // (all steps done, colored by the real PASS/FAIL/RECOV outcome) right when
    // a real run finishes, and resetting it to 0 immediately afterward wiped
    // that completed state out before the user could see it. The backend-down
    // fallback path already resets flowStep to 0 itself.
    setIsInjecting(false);
  };

  const flowSteps = [
    { label: 'Check baseline', sub: 'Confirm the isolated copy can start' },
    { label: 'Apply test condition', sub: faultTypes.find(f=>f.id===selectedFault)?.label || 'Selected fault' },
    { label: 'Observe behavior', sub: 'Record the real response and logs' },
    { label: 'Verify & clean up', sub: 'Check outcome and remove the test copy' },
  ];

  const tagColor = (tag) => {
    if (tag === 'CHAOS') return '#ef4444';
    if (tag === 'WARN') return '#f59e0b';
    if (tag === 'ERROR') return '#ef4444';
    if (tag === 'RECOV') return '#10b981';
    if (tag === 'PASS') return '#34d399';
    if (tag === 'FAIL') return '#ef4444';
    if (tag === 'INFO') return '#60a5fa';
    if (tag === 'TUTOR') return '#a5b4fc';
    return '#64748b';
  };

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
        <div>
          <BlurText as="h1" text="Chaos Lab" animateBy="letters" delay={20} style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '4px' }} />
          <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>Pick one problem to test. CD-SET runs it against a temporary copy, watches what happens, and records the result.</p>
        </div>
        <Tooltip position="bottom" title="Backend Connectivity" text={backendUp ? "Connected to the FastAPI backend -- experiment runs use real project data." : "Backend unreachable. Chaos execution is blocked until the backend is available."}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: backendUp ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', border: `1px solid ${backendUp ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`, padding: '8px 14px', borderRadius: '8px', fontSize: '12px', color: backendUp ? '#10b981' : '#ef4444' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: backendUp ? '#10b981' : '#ef4444', boxShadow: `0 0 8px ${backendUp ? '#10b981' : '#ef4444'}` }}></span>
            {backendUp === null ? 'Checking backend...' : backendUp ? 'Backend: connected' : 'Backend: offline (blocked)'}
          </div>
        </Tooltip>
      </div>

      {/* Project picker: which imported project will the chaos test run on? */}
      <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.18)" style={{ padding: '20px 24px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0', margin: '0 0 4px' }}>Choose the project to test</h3>
            <p style={{ fontSize: 11, color: '#64748b', margin: 0, lineHeight: 1.5 }}>Every imported project is listed here. Press <strong style={{ color: '#c7d2fe' }}>Test this project</strong> on the one you want; all chaos tests below run against that project only.</p>
          </div>
          <button className="btn-secondary" onClick={loadProjects} disabled={projectsLoading || isInjecting} style={{ padding: '6px 12px', fontSize: 12 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
        {projectsError && <div style={{ color: '#fca5a5', fontSize: 12, marginBottom: 8 }}>{projectsError}</div>}
        <div role="listbox" aria-label="Imported projects" style={{ maxHeight: 208, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8, paddingRight: 6 }}>
          {projectsLoading && !projects.length && <div style={{ color: '#64748b', fontSize: 12, padding: 8 }}>Loading projects…</div>}
          {!projectsLoading && !projects.length && !projectsError && (
            <div style={{ color: '#94a3b8', fontSize: 12, padding: 12, textAlign: 'center' }}>
              No projects imported yet. <button className="btn-primary" style={{ marginLeft: 8, padding: '5px 12px', fontSize: 12 }} onClick={() => setCurrentView?.('import')}>Import a project</button>
            </div>
          )}
          {projects.map(p => {
            const active = p.id === selectedProjectId;
            return (
              <div key={p.id} role="option" aria-selected={active} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', borderRadius: 10,
                background: active ? 'rgba(99,102,241,.14)' : 'rgba(255,255,255,.025)',
                border: active ? '1px solid #6366f1' : '1px solid rgba(255,255,255,.08)'
              }}>
                <div style={{ width: 34, height: 34, borderRadius: 8, background: 'rgba(99,102,241,.14)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Folder size={17} color={active ? '#c7d2fe' : '#818cf8'} />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: active ? '#c7d2fe' : '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</div>
                  <div style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    File: {p.original_filename || p.name} · {p.status}
                  </div>
                </div>
                {active ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 700, color: '#34d399', flexShrink: 0 }}><CheckCircle2 size={14} /> Testing this project</span>
                ) : (
                  <button className="btn-primary" disabled={isInjecting} onClick={() => chooseProject(p)} style={{ padding: '6px 12px', fontSize: 12, flexShrink: 0, opacity: isInjecting ? 0.5 : 1 }}>
                    <Zap size={13} /> Test this project
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </SpotlightCard>

      {/* 3-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr 1fr', gap: '24px', marginBottom: '24px' }}>
        {/* Column 1: Failure Types */}
        <SpotlightCard spotlightColor="rgba(239, 68, 68, 0.2)" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', marginBottom: '6px', color: '#e2e8f0' }}>Choose one test</h3><p style={{fontSize:11,color:'#64748b',margin:'0 0 16px',lineHeight:1.5}}>Choose the behavior you want to challenge. The test runs against an isolated copy of your imported project.</p>
          <div role="radiogroup" aria-label="Chaos tests" style={{ maxHeight: '560px', overflowY: 'auto', paddingRight: '4px' }}>
            {FAULT_GROUPS.map(([category, items]) => (
              <div key={category} className="tc-group">
                <div className="tc-group-title">{category}</div>
                <div className="tc-list">
                  {items.map(fault => {
                    const Icon = fault.icon;
                    const isSelected = selectedFault === fault.id;
                    const avail = availability[fault.preset];
                    const unavailable = !!avail && !avail.available;
                    return (
                      <label key={fault.id} title={unavailable ? (avail.reason || 'Not applicable to this project') : fault.desc}
                        className={`tc-item${isSelected ? ' is-selected' : ''}${unavailable ? ' is-disabled' : ''}`}>
                        <input type="radio" name="chaos-test" value={fault.id} checked={isSelected} disabled={unavailable} onChange={() => setSelectedFault(fault.id)} />
                        <span className="tc-icon"><Icon size={15} color={fault.color} /></span>
                        <span style={{ minWidth: 0 }}>
                          <div className="tc-name">{fault.label}</div>
                          <div className="tc-desc">{unavailable ? 'Not applicable to this project' : fault.desc}</div>
                        </span>
                        {unavailable ? <span className="pill pill-mute">N/A</span> : isSelected ? <CheckCircle2 size={16} color="#818cf8" /> : <span style={{ width: 16 }} />}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </SpotlightCard>

        {/* Column 2: Configuration */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '600', marginBottom: '6px', color: '#e2e8f0' }}>How this test runs</h3><p style={{fontSize:11,color:'#64748b',margin:'0 0 20px',lineHeight:1.5}}>These settings are fixed by CD-SET so every run is repeatable. The original project is never changed.</p>

            <div className="tc-evidence-grid" style={{ marginBottom: 20 }}>
              <div className="tc-evidence-cell"><div className="k">Target</div><div className="v">Detected automatically from the project</div></div>
              <div className="tc-evidence-cell"><div className="k">Where it runs</div><div className="v">Isolated temporary copy</div></div>
              <div className="tc-evidence-cell"><div className="k">Request timeout</div><div className="v">3 seconds (fixed)</div></div>
              <div className="tc-evidence-cell"><div className="k">Service start timeout</div><div className="v">8 seconds (fixed)</div></div>
            </div>

            {/* Inject Button */}
            <div style={{ background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '10px', padding: '20px', textAlign: 'center' }}>
              <div style={{ margin: '0 auto 14px', padding: '8px 12px', borderRadius: 8, display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12,
                background: selectedProject ? 'rgba(99,102,241,.12)' : 'rgba(245,158,11,.10)', border: `1px solid ${selectedProject ? 'rgba(99,102,241,.35)' : 'rgba(245,158,11,.35)'}`, color: selectedProject ? '#c7d2fe' : '#fbbf24', maxWidth: '100%' }}>
                <Folder size={14} />
                {selectedProject
                  ? <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Chaos will run on: <strong>{selectedProject.name}</strong> <span style={{ opacity: .7, fontFamily: 'monospace' }}>({selectedProject.original_filename || selectedProject.name})</span></span>
                  : <span>No project selected — press “Test this project” above first.</span>}
              </div>
              <div style={{ fontSize: '24px', marginBottom: '8px' }}>⚠</div>
              <h4 style={{ fontSize: '16px', fontWeight: '700', color: '#e2e8f0', marginBottom: '6px', textAlign: 'center' }}>{isInjecting ? 'Test running' : 'Ready to test'}</h4>
              <p style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '16px', lineHeight: '1.5' }}>
                CD-SET will run the selected fault against an isolated copy, record the baseline and observed response, then clean up the test copy. No production system is targeted by this screen.
              </p>
              {isInjecting && <div style={{marginBottom:14,padding:'10px 12px',borderRadius:8,background:'rgba(99,102,241,.08)',border:'1px solid rgba(99,102,241,.22)',color:'#c7d2fe',fontSize:12}}>Elapsed: <strong>{elapsed}s</strong> · Status: <strong>{activeStatus}</strong></div>}
              <Tooltip position="top" title="Run selected test" text={`Run the selected controlled fault against the isolated project copy`}>
                {isInjecting ? (
                <div style={{display:'flex',justifyContent:'center',gap:8}}>
                  <button className="btn-danger" onClick={handleCancelInjection} style={{margin:'0 auto'}}>
                    <StopCircle size={16} /> Cancel Injection
                  </button>
                </div>
              ) : (
                <button className="btn-danger" onClick={handleInject} disabled={backendUp === false || !selectedProjectId || (availability[faultTypes.find(f => f.id === selectedFault)?.preset] && !availability[faultTypes.find(f => f.id === selectedFault)?.preset].available)} style={{ margin: '0 auto' }}>
                  <Zap size={16} /> Run Selected Test
                </button>
              )}
              </Tooltip>
            </div>
            {/* What happened, and whether the AI Tutor is needed */}
            {lastResult && !isInjecting && (() => {
              const needs = lastResult.status === 'COMPLETED' && PROBLEM_OUTCOMES.includes(lastResult.outcome);
              const ok = lastResult.status === 'COMPLETED' && HANDLED_OUTCOMES.includes(lastResult.outcome);
              const color = needs ? '#f87171' : ok ? '#34d399' : '#fbbf24';
              const bg = needs ? 'rgba(239,68,68,.08)' : ok ? 'rgba(16,185,129,.08)' : 'rgba(245,158,11,.08)';
              return (
                <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 10, background: bg, border: `1px solid ${color}55`, textAlign: 'left' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 700, color }}>
                    {needs ? <BrainCircuit size={16} /> : ok ? <ShieldCheck size={16} /> : <ShieldAlert size={16} />}
                    {needs ? 'This project did not handle the injected error correctly' : ok ? 'Handled correctly — AI Tutor is not needed' : 'No verdict for this test'}
                  </div>
                  <p style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.6, margin: '6px 0 10px' }}>
                    {needs ? 'The AI Tutor has your project’s code, the error that was injected and a suggested fix ready.'
                      : ok ? 'The project responded to the injected error the way a resilient service should. Try another test to look for weak spots.'
                      : `The test ended as ${lastResult.status}${lastResult.outcome ? ` (${lastResult.outcome})` : ''}, so there is nothing for the Tutor to fix.`}
                  </p>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {needs && <button className="btn-primary" onClick={() => setCurrentView?.('tutor')} style={{ padding: '7px 14px', fontSize: 12 }}><BrainCircuit size={14} /> Open AI Tutor</button>}
                    {ok && <button className="btn-secondary" onClick={() => setCurrentView?.('tutor')} style={{ padding: '7px 14px', fontSize: 12 }}>Ask the Tutor anyway</button>}
                  </div>
                </div>
              );
            })()}
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, fontSize: 11, color: '#94a3b8', cursor: 'pointer' }}>
              <input type="checkbox" checked={autoOpenTutor} onChange={e => setAutoOpenTutor(e.target.checked)} style={{ accentColor: '#6366f1' }} />
              Open AI Tutor automatically when the project fails a test
            </label>
          </SpotlightCard>
        </div>

        {/* Column 3: Experiment Flow */}
        <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0' }}>How the test works</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {flowSteps.map((step, idx) => {
              const isDone = idx < flowStep;
              const isActive = idx === flowStep - 1;
              return (
                <div key={idx} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <div style={{
                    width: '18px', height: '18px', borderRadius: '50%', border: `2px solid ${isActive ? '#6366f1' : isDone ? '#10b981' : 'rgba(255,255,255,0.2)'}`,
                    background: isDone ? '#10b981' : isActive ? 'rgba(99,102,241,0.3)' : 'transparent',
                    boxShadow: isActive ? '0 0 12px #6366f1' : 'none',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginTop: '2px'
                  }}>
                    {isDone && <CheckCircle2 size={10} color="#fff" />}
                  </div>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: isActive ? '#818cf8' : '#e2e8f0' }}>{step.label}</div>
                    <div style={{ fontSize: '11px', color: '#64748b' }}>{step.sub}</div>
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)', borderRadius: '8px', padding: '16px', marginTop: 'auto' }}>
            <div style={{ fontSize: '10px', fontWeight: '700', color: '#10b981', letterSpacing: '0.5px', marginBottom: '8px' }}>WHAT PROVES THE TEST?</div>
            <p style={{ fontSize: '11px', color: '#94a3b8', lineHeight: '1.5' }}>
              A test is considered real only when the backend records a run ID, baseline observation, injected condition, observed response, final outcome, and cleanup. Results are shown in Experiments, Logs, and AI Tutor. This validates the isolated test environment; it does not claim production equivalence.
            </p>
          </div>
        </SpotlightCard>
      </div>

      {/* Terminal Log */}
      <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.15)" style={{ padding: '0' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          {['Terminal Log', 'Response Headers'].map(tab => (
            <button key={tab} style={{ background: tab === 'Terminal Log' ? 'rgba(99,102,241,0.1)' : 'none', border: 'none', borderBottom: tab === 'Terminal Log' ? '2px solid #6366f1' : '2px solid transparent', padding: '12px 20px', color: tab === 'Terminal Log' ? '#e2e8f0' : '#64748b', fontSize: '13px', cursor: 'pointer', fontWeight: '500' }}>
              {tab}
            </button>
          ))}
        </div>
        <div ref={terminalRef} style={{ padding: '16px', fontFamily: 'monospace', fontSize: '12px', height: '180px', overflowY: 'auto', background: 'rgba(4, 6, 12, 0.5)' }}>
          {terminalLog.length ? terminalLog.map((line, idx) => (
            <div key={idx} style={{ lineHeight: '1.8', display: 'flex', gap: '12px' }}>
              <span style={{ color: '#4b5563', minWidth: '90px', flexShrink: 0 }}>{line.time}</span>
              <span style={{ color: tagColor(line.tag), fontWeight: '700', minWidth: '55px', flexShrink: 0 }}>[{line.tag}]</span>
              <span style={{ color: line.color, flex: 1, minWidth: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{line.msg}</span>
            </div>
          )) : <div style={{color:'#64748b',lineHeight:1.7}}>No test activity yet. Choose a test, click <strong style={{color:'#c7d2fe'}}>Run Selected Test</strong>, and this panel will show each step in plain language.</div>}
        </div>
      </SpotlightCard>
    </div>
  );
}
