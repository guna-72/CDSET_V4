import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { Code2, Folder, FileText, RefreshCw, Trash2 } from 'lucide-react';
import BlurText from '../components/BlurText';
import SpotlightCard from '../components/SpotlightCard';
import { getProject, getAnalysis, getCoverage, getProjectFiles, deleteProject } from '../api';

export default function OverviewPage({ setCurrentView, selectedProjectId, setSelectedProjectId }) {
  const [project,setProject]=useState(null);
  const [analysis,setAnalysis]=useState(null);
  const [coverage,setCoverage]=useState(null);
  const [projectFiles,setProjectFiles]=useState([]);
  const [error,setError]=useState('');
  const load=async()=>{
    if(!selectedProjectId){setProject(null);return;}
    try{
      const p=await getProject(selectedProjectId); setProject(p);
      const [a,c,f]=await Promise.allSettled([getAnalysis(selectedProjectId),getCoverage(selectedProjectId),getProjectFiles(selectedProjectId)]);
      if(a.status==='fulfilled') setAnalysis(a.value);
      if(c.status==='fulfilled') setCoverage(c.value);
      if(f.status==='fulfilled') setProjectFiles(f.value.files || []);
      setError('');
    }catch(e){setError(friendlyError(e) || 'Could not load project.');}
  };
  useEffect(()=>{load();},[selectedProjectId]);

  const remove=async()=>{
    if(!project || !window.confirm(`Delete project "${project.name}"? This removes its stored experiments and history.`)) return;
    try{
      await deleteProject(project.id);
      localStorage.removeItem('chaosTutorProjectId');
      localStorage.removeItem('chaosTutorRunId');
      setSelectedProjectId?.('');
      setCurrentView('projects');
    }catch(e){setError(friendlyError(e) || 'Delete failed.');}
  };

  if(!selectedProjectId || !project) return (
    <div style={{padding:32,color:'#fff',position:'relative',zIndex:2}}>
      <div className="glass-card" style={{padding:40,textAlign:'center'}}>
        <h2 style={{marginTop:0}}>No project selected</h2>
        <p style={{color:'#94a3b8'}}>Import a project to populate this page with its real data.</p>
        <button className="btn-primary" onClick={()=>setCurrentView('import')}>Import Project</button>
      </div>
    </div>
  );

  // The backend may return languages as an array, object, or null depending on
  // the analyzer result. Normalize it before rendering so importing a project
  // can never crash the Overview page with `langs.join is not a function`.
  const rawLanguages = analysis?.languages;
  const langs = Array.isArray(rawLanguages)
    ? rawLanguages
    : rawLanguages && typeof rawLanguages === 'object'
      ? Object.entries(rawLanguages).map(([name, value]) =>
          typeof value === 'number' ? `${name} (${value})` : name
        )
      : typeof rawLanguages === 'string'
        ? [rawLanguages]
        : [];

  const structure=analysis?.structure || [];
  const files=projectFiles.length ? projectFiles.map(f=>f.path) : (Array.isArray(structure) ? structure : Object.keys(structure||{}));
  const treeLines = [];
  const seenDirs = new Set();
  files.forEach(path => {
    const parts = String(path).split('/');
    parts.forEach((part, idx) => {
      const dir = parts.slice(0, idx).join('/');
      const key = parts.slice(0, idx + 1).join('/');
      if (idx < parts.length - 1 && !seenDirs.has(key)) { seenDirs.add(key); treeLines.push({text: part + '/', depth: idx, dir: true, key}); }
    });
    treeLines.push({text: parts[parts.length-1], depth: parts.length-1, dir:false, key:path});
  });
  return (
    <div style={{padding:32,color:'#fff',position:'relative',zIndex:2}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:24}}>
        <div>
          <BlurText as="h1" text={project.name} animateBy="letters" delay={20} style={{fontSize:28,fontWeight:700,marginBottom:5}}/>
          <div style={{fontSize:12,color:'#94a3b8'}}>Project ID <span style={{fontFamily:'monospace',color:'#818cf8'}}>{project.id}</span> · {project.status}</div>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="btn-secondary" onClick={load}><RefreshCw size={15}/> Refresh</button>
          <button className="btn-secondary" onClick={remove}><Trash2 size={15}/> Delete Project</button>
          <button className="btn-primary" onClick={()=>setCurrentView('ide')}><Code2 size={15}/> Open in Editor</button>
        </div>
      </div>
      {error && <div style={{marginBottom:16,padding:11,borderRadius:8,color:'#fca5a5',background:'rgba(239,68,68,.08)',border:'1px solid rgba(239,68,68,.25)'}}>{error}</div>}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>
        <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
          <h3 style={h3}>Project Info</h3>
          <Info label="Language" value={langs.join(', ')||'Not detected'}/>
          <Info label="Framework" value={analysis?.framework||'Not detected'}/>
          <Info label="Execution" value={analysis?.execution_status||'Not analyzed'}/>
          <Info label="Experiments" value={`${coverage?.total_experiments_generated||0} generated · ${coverage?.experiments_ready||0} ready`}/>
        </SpotlightCard>
        <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
          <h3 style={h3}>Project Structure</h3>
          <div style={{background:'#0a0d16',padding:15,borderRadius:8,maxHeight:270,overflow:'auto',fontFamily:'monospace',fontSize:12}}>
            {treeLines.length ? treeLines.slice(0,160).map((item,i)=><div key={item.key + i} style={{padding:'4px 0',paddingLeft:item.depth*14,color:item.dir?'#a5b4fc':'#cbd5e1'}}>{item.dir ? <Folder size={13} style={{verticalAlign:'middle',marginRight:7,color:'#818cf8'}}/> : <FileText size={13} style={{verticalAlign:'middle',marginRight:7,color:'#64748b'}}/>}{item.text}</div>) : <span style={{color:'#64748b'}}>No structure data.</span>}
          </div>
        </SpotlightCard>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20,marginTop:20}}>
        <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
          <h3 style={h3}>Coverage</h3>
          <Info label="Failure points" value={coverage?.total_failure_points??0}/>
          <Info label="Ready experiments" value={coverage?.experiments_ready??0}/>
          <Info label="Blocked experiments" value={coverage?.experiments_blocked??0}/>
        </SpotlightCard>
        <SpotlightCard spotlightColor="rgba(99,102,241,.2)" style={{padding:24}}>
          <h3 style={h3}>Next steps</h3>
          <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
            <button className="btn-secondary" onClick={()=>setCurrentView('experiments')}>Experiments</button>
            <button className="btn-secondary" onClick={()=>setCurrentView('chaos-lab')}>Chaos Lab</button>
            <button className="btn-secondary" onClick={()=>setCurrentView('tutor')}>AI Tutor</button>
          </div>
        </SpotlightCard>
      </div>
    </div>
  );
}
function Info({label,value}){return <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',gap:16,padding:'10px 0',borderBottom:'1px solid rgba(255,255,255,.05)',fontSize:13,minWidth:0}}><span style={{color:'#94a3b8',flexShrink:0}}>{label}</span><span style={{color:'#e2e8f0',fontWeight:600,textAlign:'right',overflowWrap:'anywhere',wordBreak:'break-word',minWidth:0}}>{String(value)}</span></div>}
const h3={fontSize:15,fontWeight:600,color:'#e2e8f0',margin:'0 0 15px'};
