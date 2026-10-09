import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { Folder, Code2, Trash2, RefreshCw, UploadCloud, GitBranch, GitCommit, Loader2 } from 'lucide-react';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';
import { listProjects, deleteProject } from '../api';
import { refreshWithPrompt, shortCommit, STAGE_LABELS } from '../utils/gitActions';

export default function ProjectDetailPage({ setCurrentView, setSelectedProjectId, selectedProjectId }) {
  const [projects,setProjects]=useState([]);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState({});
  const [notes,setNotes]=useState({});
  const fmt=t=>t?new Date(Number(t)*1000).toLocaleString():'';
  const pull=async(p)=>{
    setBusy(b=>({...b,[p.id]:'refreshing'}));setNotes(n=>({...n,[p.id]:''}));
    try{const r=await refreshWithPrompt(p,st=>setBusy(b=>({...b,[p.id]:st})));setNotes(n=>({...n,[p.id]:r.message}))}
    catch(e){setNotes(n=>({...n,[p.id]:`Refresh failed: ${friendlyError(e)}`}))}
    finally{setBusy(b=>{const {[p.id]:_x,...rest}=b;return rest});load()}
  };
  const load=async()=>{try{setProjects((await listProjects()).projects||[]);setError('')}catch(e){setError(friendlyError(e) || 'Could not load projects.')}};
  useEffect(()=>{load()},[]);
  const select=p=>{setSelectedProjectId?.(p.id);localStorage.setItem('chaosTutorProjectId',p.id);setCurrentView('overview')};
  const remove=async(p)=>{
    if(!window.confirm(`Delete "${p.name}" and its experiment history?`))return;
    try{await deleteProject(p.id);if(selectedProjectId===p.id){localStorage.removeItem('chaosTutorProjectId');localStorage.removeItem('chaosTutorRunId');setSelectedProjectId?.('')}await load()}catch(e){setError(friendlyError(e) || 'Delete failed.')}
  };
  return <div style={{padding:32,color:'#fff',position:'relative',zIndex:2}}>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:24}}>
      <div><BlurText as="h1" text="Projects" animateBy="letters" delay={20} style={{fontSize:28,fontWeight:700,marginBottom:5}}/><p style={{color:'#94a3b8',fontSize:13,margin:0}}>Only projects actually stored in the backend are shown.</p></div>
      <div style={{display:'flex',gap:8}}><button className="btn-secondary" onClick={load}><RefreshCw size={15}/> Refresh</button><button className="btn-primary" onClick={()=>setCurrentView('import')}><UploadCloud size={15}/> Import Project</button></div>
    </div>
    {error&&<div style={{marginBottom:16,color:'#fca5a5',fontSize:12}}>{error}</div>}
    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))',gap:16}}>
      {projects.length?projects.map(p=><SpotlightCard key={p.id} spotlightColor="rgba(99,102,241,.2)" style={{padding:20}}>
        <div style={{display:'flex',gap:12,alignItems:'center'}}><div style={{width:40,height:40,borderRadius:10,background:'rgba(99,102,241,.15)',display:'flex',alignItems:'center',justifyContent:'center'}}><Folder size={20} color="#a5b4fc"/></div><div style={{minWidth:0}}><div style={{fontWeight:700,color:'#e2e8f0',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{p.name}</div><div style={{fontSize:10,color:'#64748b'}}>{p.status} · {fmt(p.created_at)}</div></div></div>
        {p.source_type==='git'&&<div style={{display:'flex',gap:6,flexWrap:'wrap',marginTop:12}}><span className="badge badge-purple" style={{display:'inline-flex',alignItems:'center',gap:5}}><GitBranch size={11}/> {p.git_branch||'default'}</span><span className="badge" style={{display:'inline-flex',alignItems:'center',gap:5,fontFamily:'monospace'}}><GitCommit size={11}/> {shortCommit(p.git_commit)||'unknown'}</span></div>}
        <div style={{fontSize:11,color:'#64748b',fontFamily:'monospace',margin:'14px 0',wordBreak:'break-all',overflowWrap:'anywhere'}}>ID: {p.id}</div>
        <div style={{display:'flex',gap:8}}><button className="btn-primary" onClick={()=>select(p)}><Code2 size={14}/> Open</button><button className="btn-secondary" disabled={!!busy[p.id]} onClick={()=>remove(p)}><Trash2 size={14}/> Delete</button>{p.source_type==='git'&&<button className="btn-secondary" disabled={!!busy[p.id]} onClick={()=>pull(p)}>{busy[p.id]?<Loader2 size={14} className="spin"/>:<RefreshCw size={14}/>} {busy[p.id]?(STAGE_LABELS[busy[p.id]]||'Working…'):'Pull latest'}</button>}</div>
        {notes[p.id]&&<div style={{marginTop:10,fontSize:11,lineHeight:1.5,color:notes[p.id].startsWith('Refresh failed')?'#fca5a5':'#a7f3d0'}}>{notes[p.id]}</div>}
      </SpotlightCard>):<div className="glass-card" style={{padding:40,textAlign:'center',gridColumn:'1/-1'}}><h3>No projects</h3><p style={{color:'#64748b'}}>Import a ZIP, file, folder, or Git repository to create your first project.</p><button className="btn-primary" onClick={()=>setCurrentView('import')}>Import Project</button></div>}
    </div>
  </div>
}
