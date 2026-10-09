import React, { useState, useEffect, useRef } from 'react';
import { Download, Trash2 } from 'lucide-react';
import BlurText from '../components/BlurText';
import { getLogs, getProjectLogs, listRuns } from '../api';
import { friendlyError, friendlyErrorParts } from '../utils/friendlyError';
import { exportLogsPdf } from '../utils/exportLogsPdf';

// Map backend event `type` (system|chaos|recovery) + tag straight through --
// the shapes already line up with what this page expects.
const backendEventToLog = (e) => {
  const type = String(e.type || 'SYSTEM').toLowerCase();
  const tag = type.includes('chaos') || type.includes('inject') ? 'CHAOS'
    : type.includes('recover') ? 'RECOV'
    : type.includes('application_error') ? 'ERROR'
    : type.includes('safety') ? 'WARN' : 'INFO';
  const raw = String(e.message || '').trim();
  const friendly = raw.replace(/^starting run for experiment /i, 'Starting test: ')
    .replace(/^Injecting /i, 'Applying test condition: ')
    .replace(/^Test finished: COMPLETED/i, 'Test finished: completed')
    .replace(/^Test finished: FAILED/i, 'Test finished: failed')
    .replace(/^Test finished: BLOCKED/i, 'Test blocked by the safety/environment rules');
  // The backend already returns captured stdout/stderr under data.output for
  // APPLICATION / APPLICATION_ERROR events (see orchestrator.py::run_experiment);
  // it was just never rendered here, so a real "Cannot find module 'express'"
  // (or any other startup error) was invisible even though it was in the payload.
  const output = e.data && typeof e.data.output === 'string' && e.data.output.trim() ? e.data.output : null;
  // Plain-language explanation for error/warning lines and for errors printed by the tested project.
  const isProblem = tag === 'ERROR' || tag === 'WARN';
  const plainFromMsg = isProblem ? friendlyErrorParts(friendly) : { message: friendly, detail: '' };
  const plainFromOutput = output ? friendlyErrorParts(output) : { message: '', detail: '' };
  const hint = plainFromOutput.detail ? plainFromOutput.message : '';
  return { time: e.ts ? new Date(e.ts * 1000).toLocaleTimeString() : '—', tag, msg: plainFromMsg.message || 'System event recorded.', hint, type: tag === 'CHAOS' ? 'chaos' : tag === 'RECOV' ? 'recovery' : 'system', id: e.id, output };
};

const allLogs = [];

const tagStyle = (tag) => {
  const styles = {
    CHAOS: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
    WARN: { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
    ERROR: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
    RECOV: { color: '#10b981', bg: 'rgba(16,185,129,0.1)' },
    INFO: { color: '#60a5fa', bg: 'transparent' },
    '....': { color: '#64748b', bg: 'transparent' },
  };
  return styles[tag] || { color: '#94a3b8', bg: 'transparent' };
};


export default function LogsPage({ setCurrentView, selectedProjectId }) {
  const [filter, setFilter] = useState('All');
  const [isLive, setIsLive] = useState(() => localStorage.getItem('chaosTutorLogsLive') !== 'false');
  const [logs, setLogs] = useState(() => {
    try {
      const projectId = localStorage.getItem('chaosTutorProjectId') || '';
      const storedProjectId = localStorage.getItem('chaosTutorLogsProjectId') || '';
      return projectId && projectId === storedProjectId ? JSON.parse(localStorage.getItem('chaosTutorVisibleLogs') || '[]') : [];
    } catch { return []; }
  });
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState(() => {
    const projectId = localStorage.getItem('chaosTutorProjectId') || '';
    const storedProjectId = localStorage.getItem('chaosTutorLogsProjectId') || '';
    return projectId && projectId === storedProjectId ? (localStorage.getItem('chaosTutorRunId') || '') : '';
  });
  const [backendError, setBackendError] = useState('');
  const seenIdsRef = useRef(new Set());
  const logRef = useRef(null);

  // Resolve the latest run when the Logs page is opened directly. This fixes
  // the old "No run selected" state after navigation or a browser refresh.
  useEffect(() => {
    let cancelled = false;
    const resolveRun = async () => {
      if (!selectedProjectId) return;
      const stored = localStorage.getItem('chaosTutorRunId') || '';
      try {
        const { runs = [] } = await listRuns(100);
        // The backend returns runs newest-first (see db.get_many's ORDER BY
        // ... DESC), so the most recent run for this project is index 0, not
        // the last element — picking the last element here previously
        // surfaced the OLDEST run in the batch as the "latest" one.
        const projectRuns = runs.filter(r => r.project_id === selectedProjectId);
        const storedRun = projectRuns.find(r => r.id === stored);
        const projectRun = storedRun || projectRuns[0];
        if (!cancelled) {
          if (projectRun?.id) {
            setSelectedRunId(projectRun.id);
            localStorage.setItem('chaosTutorRunId', projectRun.id);
          } else {
            setSelectedRunId('');
            localStorage.removeItem('chaosTutorRunId');
          }
        }
      } catch (_) {}
    };
    resolveRun();
    return () => { cancelled = true; };
  }, [selectedProjectId]);

  // A run change starts a fresh evidence view. We never mix events from two
  // runs into one stream, while the backend remains the authoritative source.
  useEffect(() => {
    setLogs([]);
    seenIdsRef.current.clear();
    localStorage.setItem('chaosTutorLogsProjectId', selectedProjectId || '');
    localStorage.removeItem('chaosTutorVisibleLogs');
    const refreshRun = () => {
      const id = localStorage.getItem('chaosTutorRunId') || '';
      const projectId = localStorage.getItem('chaosTutorProjectId') || '';
      setSelectedRunId(projectId === selectedProjectId ? id : '');
      localStorage.setItem('chaosTutorLogsProjectId', selectedProjectId || '');
      setLogs([]);
      seenIdsRef.current.clear();
    };
    window.addEventListener('chaosTutorRunChanged', refreshRun);
    return () => window.removeEventListener('chaosTutorRunChanged', refreshRun);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!isLive || !selectedProjectId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const result = selectedRunId
          ? await getLogs(selectedRunId)
          : await getProjectLogs(selectedProjectId, '', 500);
        if (cancelled) return;
        const events = Array.isArray(result.events) ? result.events : [];
        setBackendError('');
        setLastUpdated(new Date());
        const fresh = events.filter(e => e.id && !seenIdsRef.current.has(e.id));
        fresh.forEach(e => seenIdsRef.current.add(e.id));
        if (!fresh.length) return;
        setLogs(prev => [...prev, ...fresh.map(backendEventToLog)].slice(-500));
        requestAnimationFrame(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; });
      } catch (e) {
        if (!cancelled) setBackendError(friendlyError(e) || 'Logs are unavailable right now. Check that the backend is running.');
      }
    };
    poll();
    const interval = setInterval(poll, 1200);
    return () => { cancelled = true; clearInterval(interval); };
  }, [isLive, selectedProjectId, selectedRunId]);

  useEffect(() => {
    localStorage.setItem('chaosTutorLogsLive', String(isLive));
    localStorage.setItem('chaosTutorLogsProjectId', selectedProjectId || '');
    localStorage.setItem('chaosTutorVisibleLogs', JSON.stringify(logs.slice(-500)));
  }, [isLive, logs, selectedProjectId]);

  const filtered = filter === 'All' ? logs
    : filter === 'Chaos' ? logs.filter(l => l.type === 'chaos')
    : filter === 'Recovery' ? logs.filter(l => l.type === 'recovery')
    : logs.filter(l => l.type === 'system');

  const filters = ['All', 'Chaos', 'Recovery', 'System'];
  const filterColors = { All: '#94a3b8', Chaos: '#ef4444', Recovery: '#10b981', System: '#64748b' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', padding: '24px 32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      {/* Header + Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <BlurText as="h1" text="Live Application Logs" animateBy="letters" delay={20} style={{ fontSize: '24px', fontWeight: '700', letterSpacing: '-0.5px' }} />
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', fontSize: '12px' }}>
          {lastUpdated && <span style={{color:'#64748b'}}>Updated {lastUpdated.toLocaleTimeString()}</span>}
          <a href="#docs" onClick={e => { e.preventDefault(); setCurrentView('overview'); }} style={{ color: '#94a3b8', textDecoration: 'none' }}>Docs</a>
          <a href="#support" onClick={e => { e.preventDefault(); setCurrentView('settings'); }} style={{ color: '#94a3b8', textDecoration: 'none', marginRight: '8px' }}>Support</a>
          <button className="btn-primary" onClick={() => setCurrentView('chaos-lab')}>
            Deploy Experiment
          </button>
        </div>
      </div>

      {/* Run context */}
      <div className="glass-card" style={{padding:'10px 14px',marginBottom:10,display:'flex',alignItems:'center',justifyContent:'space-between',gap:10}}>
        <div><div style={{fontSize:10,color:'#64748b',textTransform:'uppercase',fontWeight:700}}>Evidence source</div><div style={{fontSize:11,color:'#94a3b8',marginTop:3}}>{selectedRunId ? `Showing events for run ${selectedRunId.slice(0,12)}…` : selectedProjectId ? 'Showing project events; a running test will appear here automatically.' : 'No project selected — import a project first.'}</div>{backendError&&<div style={{fontSize:10,color:'#f59e0b',marginTop:4}}>{backendError}</div>}</div>
        {selectedRunId && <button className="btn-secondary" onClick={()=>{setLogs([]);seenIdsRef.current.clear();setSelectedRunId('');localStorage.removeItem('chaosTutorRunId');}} style={{padding:'6px 10px'}}>All project events</button>}
      </div>

      {/* Filter Bar */}
      <div className="glass-card" style={{ padding: '12px 16px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            {filters.map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  background: filter === f ? 'rgba(255,255,255,0.08)' : 'transparent',
                  border: filter === f ? '1px solid rgba(255,255,255,0.15)' : '1px solid transparent',
                  borderRadius: '20px',
                  padding: '6px 14px',
                  color: filter === f ? filterColors[f] : '#64748b',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                {f !== 'All' && <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: filterColors[f] }} />}
                {f}
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={() => setIsLive(true)}
              style={{
                background: isLive ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${isLive ? 'rgba(239,68,68,0.4)' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '6px',
                padding: '6px 14px',
                color: isLive ? '#ef4444' : '#94a3b8',
                fontSize: '12px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              {isLive && <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#ef4444', boxShadow: '0 0 8px #ef4444', animation: 'pulse 1.5s infinite' }} />}
              Live
            </button>
            <button
              onClick={() => setIsLive(false)}
              style={{
                background: !isLive ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '6px',
                padding: '6px 14px',
                color: !isLive ? '#e2e8f0' : '#94a3b8',
                fontSize: '12px',
                fontWeight: '500',
                cursor: 'pointer'
              }}
            >
              Paused
            </button>
            <button
              onClick={() => exportLogsPdf({ logs: filtered, selectedRunId, selectedProjectId, filter })}
              title="Download visible logs as PDF report"
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '6px',
                padding: '6px 10px',
                color: '#94a3b8',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <Download size={15} />
            </button>
            <button onClick={() => { setLogs([]); seenIdsRef.current.clear(); }} title="Clear visible log entries" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', padding: '6px 10px', color: '#94a3b8', cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
              <Trash2 size={15} />
            </button>
          </div>
        </div>
      </div>

      {/* Log Stream */}
      <div
        ref={logRef}
        className="glass-card"
        style={{ flex: 1, overflowY: 'auto', padding: '16px', fontFamily: 'JetBrains Mono, monospace', fontSize: '12.5px' }}
      >
        {filtered.length === 0 ? (
          <div style={{height:'100%',minHeight:260,display:'flex',alignItems:'center',justifyContent:'center',textAlign:'center',color:'#64748b'}}>
            <div><div style={{fontSize:14,color:'#94a3b8',fontWeight:650,marginBottom:6}}>No recorded application events</div><div style={{fontSize:11,maxWidth:420,lineHeight:1.6}}>Run a resilience test to create real events. CD-SET does not display simulated or demo log entries.</div></div>
          </div>
        ) : filtered.map((log, idx) => {
          const ts = tagStyle(log.tag);
          const isHighlight = log.type === 'chaos' || log.type === 'recovery';
          return (
            <div
              key={idx}
              className="log-stream-row"
              style={{
                display: 'flex',
                gap: '16px',
                alignItems: 'flex-start',
                padding: '5px 8px',
                borderRadius: '4px',
                background: isHighlight ? ts.bg : 'transparent',
                marginBottom: '2px',
                borderLeft: isHighlight ? `3px solid ${ts.color}` : '3px solid transparent'
              }}
            >
              <span style={{ color: '#4b5563', minWidth: '110px', flexShrink: 0 }}>{log.time}</span>
              <span style={{
                color: ts.color,
                fontWeight: '700',
                minWidth: '60px',
                flexShrink: 0
              }}>
                [{log.tag}]
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
                <span style={{ color: log.type === 'recovery' ? '#10b981' : log.type === 'chaos' ? '#fca5a5' : '#94a3b8', lineHeight: '1.5', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                  {log.msg}
                </span>
                {log.hint && (
                  <span style={{ color: '#fbbf24', fontSize: 12, marginTop: 3, lineHeight: 1.5, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>What this means: {log.hint}</span>
                )}
                {log.output && (
                  <details style={{ marginTop: 4, maxWidth: '100%' }}>
                    <summary style={{ cursor: 'pointer', color: '#64748b', fontSize: 11 }}>Show captured output</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere', color: '#f87171', background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)', padding: '8px 10px', borderRadius: 6, marginTop: 6, fontSize: 11.5, maxHeight: 260, overflowY: 'auto', maxWidth: '100%' }}>{log.output}</pre>
                  </details>
                )}
              </div>
            </div>
          );
        })}
        {isLive && (
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center', padding: '5px 8px', color: '#64748b', fontFamily: 'monospace', fontSize: '12px' }}>
            <span style={{ minWidth: '110px' }}>{'  '}</span>
            <span style={{ animation: 'blink 1s step-end infinite' }}>▌</span>
          </div>
        )}
      </div>

      <style>{`
        @keyframes blink { 0%, 100% { opacity: 1 } 50% { opacity: 0 } }
        @keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.4 } }
      `}</style>
    </div>
  );
}
