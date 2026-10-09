import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { Download, RefreshCw, ShieldCheck } from 'lucide-react';
import BlurText from '../components/BlurText';
import CountUp from '../components/CountUp';
import SpotlightCard from '../components/SpotlightCard';
import { getReport } from '../api';

// Circular SVG gauge
function CircularGauge({ score, max = 100, color = '#818cf8' }) {
  const radius = 80;
  const strokeWidth = 12;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / max) * circumference * 0.75; // 75% arc
  const dashOffset = circumference * 0.75 - progress;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width="200" height="200" viewBox="0 0 200 200">
        {/* Background arc */}
        <circle
          cx="100" cy="100" r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
          strokeDasharray={`${circumference * 0.75} ${circumference}`}
          strokeLinecap="round"
          transform="rotate(135 100 100)"
        />
        {/* Progress arc */}
        <circle
          cx="100" cy="100" r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${progress} ${circumference}`}
          strokeDashoffset={0}
          strokeLinecap="round"
          transform="rotate(135 100 100)"
          style={{ filter: `drop-shadow(0 0 8px ${color}80)`, transition: 'stroke-dasharray 1s ease' }}
        />
        {/* Center text */}
        <text x="100" y="95" textAnchor="middle" fill="#f3f4f6" fontSize="40" fontWeight="800" fontFamily="Inter, sans-serif">{score}</text>
        <text x="100" y="118" textAnchor="middle" fill="#64748b" fontSize="14" fontFamily="Inter, sans-serif">/{max}</text>
      </svg>
    </div>
  );
}

export default function ResiliencePage({ setCurrentView, selectedProjectId }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    if (!selectedProjectId) { setReport(null); setLoading(false); return; }
    setLoading(true);
    try { setReport(await getReport(selectedProjectId)); setError(''); }
    catch (e) { setError(friendlyError(e) || 'Could not load resilience report.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [selectedProjectId]);

  const total = report?.total_runs || 0;
  const counts = report?.outcome_counts || {};
  const score = report?.resilience_score_pct;
  const safeScore = typeof score === 'number' ? score : 0;
  const passed = (counts.PASSED || 0) + (counts.RECOVERED || 0);
  const failed = (counts.APPLICATION_FAILURE || 0) + (counts.CRASHED || 0) + (counts.WEAK_HANDLING || 0);
  const availability = total ? Math.round(((total - failed) / total) * 1000) / 10 : 0;
  const reliability = total ? Math.round((passed / total) * 1000) / 10 : 0;
  const recovery = counts.RECOVERED ? Math.round((counts.RECOVERED / total) * 1000) / 10 : 0;

  const dynamicPillars = [
    { label: 'Handled outcomes', value: availability, color: '#10b981' },
    { label: 'Reliability', value: reliability, color: '#818cf8' },
    { label: 'Recovery outcomes', value: recovery, color: '#f59e0b' },
  ];

  if (!selectedProjectId) return <div style={{padding:32,color:'#fff',position:'relative',zIndex:2}}><div className="glass-card" style={{padding:40,textAlign:'center'}}><h2>No project selected</h2><p style={{color:'#94a3b8'}}>Import a project before viewing its resilience scorecard.</p><button className="btn-primary" onClick={()=>setCurrentView('import')}>Import Project</button></div></div>;

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <div><span style={{ background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.3)', color: '#10b981', padding: '4px 12px', borderRadius: '6px', fontSize: '11px', fontWeight: '700' }}>PROJECT RESILIENCE</span></div>
        <button className="btn-secondary" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/> Refresh</button>
      </div>
      <BlurText as="h1" text="Resilience Scorecard" animateBy="letters" delay={20} style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '6px' }} />
      <p style={{ color: '#94a3b8', fontSize: '13px', maxWidth: 700, marginBottom: 28 }}>Calculated from this project's actual experiment history. No historical/demo score is used.</p>
      {error && <div style={{marginBottom:16,padding:12,borderRadius:8,color:'#fca5a5',background:'rgba(239,68,68,.08)',border:'1px solid rgba(239,68,68,.25)'}}>{error}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr 1fr', gap: '24px', marginBottom: '28px' }}>
        <SpotlightCard spotlightColor="rgba(129, 140, 248, 0.2)" style={{ padding: '24px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{display:'flex',justifyContent:'space-between',width:'100%'}}><h3 style={{fontSize:15}}>Overall Score</h3><span style={{fontSize:12,color:'#64748b'}}>{total} runs</span></div>
          <CircularGauge score={safeScore} color="#818cf8" />
          <span style={{fontSize:12,color:'#94a3b8'}}>{total ? `${passed} handled/recovered · ${failed} failure outcomes` : 'Run an experiment to calculate'}</span><div style={{fontSize:10,color:'#64748b',textAlign:'center',marginTop:8,lineHeight:1.5}}>Score = handled or recovered test runs ÷ completed test runs. It is not a production uptime SLA.</div>
        </SpotlightCard>
        <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)" style={{ padding: '24px' }}>
          <h3 style={{fontSize:15,marginBottom:24}}>Resilience Pillars</h3>
          <div style={{display:'flex',flexDirection:'column',gap:20}}>
            {dynamicPillars.map((p,idx)=><div key={p.label}><div style={{display:'flex',justifyContent:'space-between',marginBottom:8}}><span style={{fontSize:13,color:'#e2e8f0'}}>{p.label}</span><span style={{fontSize:13,fontWeight:700,color:p.color}}>{p.value}%</span></div><div style={{height:8,background:'rgba(255,255,255,.06)',borderRadius:4,overflow:'hidden'}}><div style={{width:`${Math.max(0,Math.min(100,p.value))}%`,height:'100%',background:p.color,borderRadius:4}}/></div></div>)}
          </div>
        </SpotlightCard>
        <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
          <h3 style={{fontSize:15,marginBottom:20}}>Run Outcomes</h3>
          {Object.keys(counts).length ? Object.entries(counts).map(([k,v])=><div key={k} style={{display:'flex',justifyContent:'space-between',padding:'9px 0',borderBottom:'1px solid rgba(255,255,255,.05)',fontSize:12}}><span style={{color:'#94a3b8'}}>{k}</span><strong>{v}</strong></div>) : <span style={{color:'#64748b',fontSize:12}}>No runs yet.</span>}
        </SpotlightCard>
      </div>
      <SpotlightCard spotlightColor="rgba(16,185,129,.18)" style={{padding:24,marginBottom:20}}>
        <div style={{display:'flex',alignItems:'center',gap:9,marginBottom:8}}><ShieldCheck size={17} color="#34d399"/><h3 style={{fontSize:15,margin:0}}>Test Evidence & Scope</h3></div>
        <p style={{fontSize:12,color:'#94a3b8',lineHeight:1.6,margin:'0 0 14px'}}>These checks are evidence about the imported project in CD-SET's isolated test environment. They are not a claim that production is identical.</p>
        <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:10}}>
          <Evidence label="Recorded runs" value={`${report?.verification?.runs_with_recorded_evidence || 0} / ${report?.verification?.total_completed_runs || 0}`}/>
          <Evidence label="Original project" value={report?.verification?.original_project_modified ? 'Modified — investigate' : 'Not modified by tests'}/>
          <Evidence label="Test environment" value={report?.verification?.test_environment || 'Isolated sandbox copy'}/>
        </div>
      </SpotlightCard>
      <SpotlightCard spotlightColor="rgba(129,140,248,.18)" style={{padding:24,marginBottom:20}}>
        <h3 style={{fontSize:15,margin:'0 0 6px'}}>Verification checklist</h3>
        <p style={{fontSize:12,color:'#64748b',margin:'0 0 14px'}}>Use this checklist to understand exactly what CD-SET has demonstrated for this project.</p>
        <div style={{display:'grid',gridTemplateColumns:'repeat(2,1fr)',gap:10}}>
          <CheckItem label="Project copy tested" ok={total>0}/>
          <CheckItem label="Run evidence recorded" ok={(report?.verification?.runs_with_recorded_evidence||0)>0}/>
          <CheckItem label="Original project preserved" ok={report?.verification?.original_project_modified===false}/>
          <CheckItem label="Outcome classified" ok={total>0 && Object.keys(counts).length>0}/>
        </div>
      </SpotlightCard>
      <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
        <h3 style={{fontSize:15,marginBottom:6}}>Findings</h3><p style={{fontSize:12,color:'#64748b'}}>Concrete findings recorded by the experiment diagnosis pipeline.</p>
        {report?.findings?.length ? report.findings.map((f,i)=><div key={i} style={{padding:'13px 0',borderBottom:'1px solid rgba(255,255,255,.06)'}}><div style={{fontSize:13,fontWeight:650}}>{f.experiment}</div><div style={{fontSize:11,color:'#f87171',marginTop:4}}>{f.outcome} · {f.target}</div><div style={{fontSize:11,color:'#94a3b8',marginTop:5}}>{f.diagnosis || 'No diagnosis text recorded.'}</div></div>) : <div style={{padding:'20px 0',color:'#64748b',fontSize:12}}>{total ? 'No failure findings recorded.' : 'Run an experiment to populate this section.'}</div>}
      </SpotlightCard>
    </div>
  );
}

function CheckItem({label,ok}){return <div style={{padding:'10px 12px',borderRadius:8,background:ok?'rgba(16,185,129,.06)':'rgba(245,158,11,.05)',border:`1px solid ${ok?'rgba(16,185,129,.18)':'rgba(245,158,11,.18)'}`,display:'flex',alignItems:'center',gap:8}}><span style={{fontSize:13,color:ok?'#34d399':'#fbbf24'}}>{ok?'✓':'○'}</span><span style={{fontSize:11,color:'#cbd5e1'}}>{label}</span></div>}
function Evidence({label,value}){return <div style={{padding:'10px 12px',borderRadius:8,background:'rgba(255,255,255,.03)',border:'1px solid rgba(255,255,255,.06)'}}><div style={{fontSize:9,color:'#64748b',textTransform:'uppercase'}}>{label}</div><div style={{fontSize:11,color:'#e2e8f0',marginTop:4}}>{String(value)}</div></div>}
