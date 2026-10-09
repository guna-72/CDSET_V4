import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { Download, RefreshCw, Wrench } from 'lucide-react';
import BlurText from '../components/BlurText';
import CountUp from '../components/CountUp';
import SpotlightCard from '../components/SpotlightCard';
import { getReport } from '../api';

const OUTCOME_COLORS = {
  PASSED: '#10b981',
  RECOVERED: '#34d399',
  WEAK_HANDLING: '#f59e0b',
  APPLICATION_FAILURE: '#ef4444',
  CRASHED: '#b91c1c',
  TARGET_UNREACHABLE: '#64748b',
  ANOMALY: '#a855f7',
};
const outcomeColor = (k) => OUTCOME_COLORS[k] || '#818cf8';
const OUTCOME_LABEL = {
  PASSED: 'Handled correctly', RECOVERED: 'Recovered successfully', APPLICATION_FAILURE: 'Application failed under fault',
  CRASHED: 'Application crashed', WEAK_HANDLING: 'Fault not handled safely', TARGET_UNREACHABLE: 'Target unreachable', ANOMALY: 'Unexpected response',
};
const outcomeText = (k) => OUTCOME_LABEL[k] || (k ? String(k).replace(/_/g, ' ').toLowerCase().replace(/^./, c => c.toUpperCase()) : 'Not run yet');
const outcomeTone = (k) => (k === 'PASSED' || k === 'RECOVERED') ? 'pill-good' : (k === 'APPLICATION_FAILURE' || k === 'CRASHED') ? 'pill-bad' : k === 'TARGET_UNREACHABLE' ? 'pill-mute' : 'pill-warn';
const humanize = (v) => v ? String(v).replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()) : '—';

// Simple SVG donut chart driven entirely by real outcome_counts.
function DonutChart({ counts, total }) {
  const entries = Object.entries(counts).filter(([, v]) => v > 0);
  const cx = 80, cy = 80, r = 60, strokeWidth = 18;
  const circumference = 2 * Math.PI * r;
  let cumulative = 0;

  if (!entries.length) {
    return (
      <div style={{ padding: '20px 0', color: '#64748b', fontSize: '12px' }}>
        No completed runs yet — outcomes will appear here once an experiment finishes.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
      <svg width="160" height="160" viewBox="0 0 160 160">
        {entries.map(([key, value]) => {
          const dashLength = (value / total) * circumference;
          const gapLength = circumference - dashLength;
          const rotation = (cumulative / total) * 360 - 90;
          cumulative += value;
          return (
            <circle
              key={key}
              cx={cx} cy={cy} r={r}
              fill="none"
              stroke={outcomeColor(key)}
              strokeWidth={strokeWidth}
              strokeDasharray={`${dashLength} ${gapLength}`}
              transform={`rotate(${rotation} ${cx} ${cy})`}
              strokeLinecap="butt"
              style={{ transition: 'all 0.5s ease' }}
            />
          );
        })}
        <text x={cx} y={cy - 6} textAnchor="middle" fill="#f3f4f6" fontSize="22" fontWeight="800" fontFamily="Inter, sans-serif">{total}</text>
        <text x={cx} y={cy + 14} textAnchor="middle" fill="#64748b" fontSize="11" fontFamily="Inter, sans-serif">Runs</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {entries.map(([key, value]) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: outcomeColor(key), flexShrink: 0 }} />
            <span style={{ fontSize: '12px', color: '#94a3b8', flex: 1 }}>{outcomeText(key)}</span>
            <span style={{ fontSize: '12px', color: '#e2e8f0', fontWeight: '600' }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ReportsPage({ setCurrentView, selectedProjectId }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    if (!selectedProjectId) { setReport(null); setLoading(false); return; }
    setLoading(true);
    try { setReport(await getReport(selectedProjectId)); setError(''); }
    catch (e) { setError(friendlyError(e) || 'Could not load report.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [selectedProjectId]);

  const exportReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.project?.name || 'project'}-resilience-report.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  if (!selectedProjectId) {
    return (
      <div style={{ padding: 32, color: '#fff', position: 'relative', zIndex: 2 }}>
        <div className="glass-card" style={{ padding: 40, textAlign: 'center' }}>
          <h2 style={{ marginTop: 0 }}>No project selected</h2>
          <p style={{ color: '#94a3b8' }}>Import and test a project before viewing its analytics.</p>
          <button className="btn-primary" onClick={() => setCurrentView('import')}>Import Project</button>
        </div>
      </div>
    );
  }

  const total = report?.total_runs || 0;
  const counts = report?.outcome_counts || {};
  const coverage = report?.coverage || {};
  const testedPoints = coverage.by_coverage_status?.TESTED || 0;
  const totalPoints = coverage.total_failure_points || 0;
  const findings = report?.findings || [];
  const testCases = report?.test_cases || [];

  // Real per-target aggregation from the findings this project's runs actually produced.
  const byTarget = {};
  findings.forEach(f => {
    const key = f.target || 'unknown target';
    byTarget[key] = (byTarget[key] || 0) + 1;
  });
  const targetRows = Object.entries(byTarget).sort((a, b) => b[1] - a[1]);
  const maxTargetCount = targetRows.length ? targetRows[0][1] : 1;

  // Unique recommended fixes actually returned by the diagnosis pipeline.
  const seenFixes = new Set();
  const fixes = findings.filter(f => {
    if (!f.recommended_fix || seenFixes.has(f.recommended_fix)) return false;
    seenFixes.add(f.recommended_fix);
    return true;
  });

  const stats = [
    { label: 'TOTAL RUNS', num: total, sub: report?.project?.name, subColor: '#94a3b8' },
    { label: 'RESILIENCE SCORE', num: report?.resilience_score_pct ?? 0, unit: '%', sub: total ? 'of tested faults handled — not a production guarantee' : 'Run an experiment first', subColor: '#64748b' },
    { label: 'FAILURE POINTS TESTED', num: testedPoints, sub: `of ${totalPoints} discovered`, subColor: '#94a3b8' },
    { label: 'RECOMMENDED FIXES', num: fixes.length, sub: 'from real diagnoses', subColor: '#94a3b8' },
  ];

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
        <div>
          <BlurText as="h1" text="Analytics & Reports" animateBy="letters" delay={20} style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '4px' }} />
          <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>Built entirely from this project's own recorded run history — nothing here is simulated.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn-secondary" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button>
          <button className="btn-secondary" onClick={exportReport} disabled={!report}><Download size={16} />Export Report</button>
        </div>
      </div>

      {error && <div style={{ marginBottom: 16, padding: 12, borderRadius: 8, color: '#fca5a5', background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)' }}>{error}</div>}

      {/* 4 KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px', marginBottom: '28px' }}>
        {stats.map((s, idx) => (
          <SpotlightCard key={idx} spotlightColor={idx === 1 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(99, 102, 241, 0.2)'} style={{ padding: '20px' }}>
            <div style={{ fontSize: '10px', fontWeight: '700', color: '#64748b', letterSpacing: '0.5px', textTransform: 'uppercase', marginBottom: '12px' }}>{s.label}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
              <span style={{ fontSize: '30px', fontWeight: '800', letterSpacing: '-1px', color: '#f3f4f6' }}>
                <CountUp to={s.num} duration={1.2} />
              </span>
              {s.unit && <span style={{ fontSize: '14px', color: '#94a3b8' }}>{s.unit}</span>}
            </div>
            {s.sub && <span style={{ fontSize: '11px', color: s.subColor, display: 'block', marginTop: '4px' }}>{s.sub}</span>}
          </SpotlightCard>
        ))}
      </div>

      {/* Charts Row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '28px' }}>
        <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.2)" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0', marginBottom: '20px' }}>Outcome Breakdown</h3>
          <DonutChart counts={counts} total={total} />
        </SpotlightCard>

        <SpotlightCard spotlightColor="rgba(239, 68, 68, 0.15)" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0', marginBottom: '4px' }}>Most-Affected Targets</h3>
          <p style={{ fontSize: '12px', color: '#64748b', marginBottom: '18px' }}>Endpoints or components with the most recorded failure outcomes.</p>
          {targetRows.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {targetRows.map(([target, count]) => (
                <div key={target}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', color: '#e2e8f0', fontFamily: 'monospace' }}>{target}</span>
                    <span style={{ fontSize: '12px', fontWeight: '700', color: '#f87171' }}>{count}</span>
                  </div>
                  <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{ width: `${(count / maxTargetCount) * 100}%`, height: '100%', background: '#ef4444', borderRadius: '3px' }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: '20px 0', color: '#64748b', fontSize: '12px' }}>No failure outcomes recorded yet.</div>
          )}
        </SpotlightCard>
      </div>

      {/* Test case results: one tidy row per test case */}
      <SpotlightCard spotlightColor="rgba(99, 102, 241, 0.15)" style={{ padding: 0, overflow: 'hidden', marginBottom: '28px' }}>
        <div style={{ padding: '20px 24px 14px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0', margin: '0 0 4px' }}>Test case results</h3>
          <p style={{ fontSize: '12px', color: '#64748b', margin: 0 }}>Latest result for each test case run against this project.</p>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="tc-table" style={{ minWidth: 640 }}>
            <colgroup><col style={{ width: '30%' }} /><col style={{ width: '20%' }} /><col style={{ width: '26%' }} /><col style={{ width: '24%' }} /></colgroup>
            <thead><tr><th>Test case</th><th>Category</th><th>Target</th><th>Result</th></tr></thead>
            <tbody>
              {testCases.length ? testCases.map((c, i) => (
                <tr key={i} className="tc-row">
                  <td><div className="tc-title">{c.experiment || humanize(c.fault_type)}</div></td>
                  <td>{humanize(c.category)}</td>
                  <td><span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.target || ''}>{c.target || '—'}</span></td>
                  <td><span className={`pill ${outcomeTone(c.outcome)}`}>{outcomeText(c.outcome)}</span></td>
                </tr>
              )) : (
                <tr><td colSpan="4" style={{ padding: 28, textAlign: 'center', color: '#64748b' }}>{total ? 'Refresh to load test case results.' : 'No test cases have been run yet.'}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </SpotlightCard>

      {/* Recommended Fixes — real diagnosis output, not decorative */}
      <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.15)" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '9px', marginBottom: '4px' }}>
          <Wrench size={16} color="#34d399" />
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#e2e8f0', margin: 0 }}>Recommended Fixes</h3>
        </div>
        <p style={{ fontSize: '12px', color: '#64748b', marginBottom: '18px' }}>Generated by the diagnosis pipeline from actual observed failures — not generic advice.</p>
        {fixes.length ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {fixes.map((f, i) => (
              <div key={i} className="interactive-item" style={{ padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.04)', minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '12px', fontWeight: '650', color: '#e2e8f0', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{f.experiment}</span>
                  <span className={`pill ${outcomeTone(f.outcome)}`} style={{ flexShrink: 0 }}>{outcomeText(f.outcome)}</span>
                </div>
                <div style={{ fontSize: '12px', color: '#cbd5e1', lineHeight: 1.5, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{f.recommended_fix}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '20px 0', color: '#64748b', fontSize: '12px' }}>{total ? 'No fixes recommended — every completed run passed.' : 'Run an experiment to populate this section.'}</div>
        )}
      </SpotlightCard>
    </div>
  );
}
