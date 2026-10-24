import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useMemo, useState } from 'react';
import { Save, Play, TestTube2, FileText, Folder, ChevronDown, ChevronRight, Loader2, RefreshCw, Search } from 'lucide-react';
import { getProjectFiles, getProjectFile, saveProjectFile, ideTest, ideRun, getProject } from '../api';
import { runAnalysisPipeline, describeAnalysis, STAGE_LABELS } from '../utils/gitActions';

function iconFor(path) {
  if (path.endsWith('/')) return <Folder size={14} />;
  return <FileText size={14} />;
}

function syntaxHighlight(line) {
  if (/^\s*(from |import )/.test(line)) return <span style={{color:'#c084fc'}}>{line}</span>;
  if (line.includes('def ') || line.includes('async def ')) return <span style={{color:'#818cf8'}}>{line}</span>;
  if (line.trim().startsWith('#')) return <span style={{color:'#6b7280',fontStyle:'italic'}}>{line}</span>;
  if (line.includes('return ')) return <span style={{color:'#60a5fa'}}>{line}</span>;
  return <span style={{color:'#e2e8f0'}}>{line}</span>;
}

// Turns a backend run/test result into the final terminal line. Handles the
// cases the raw exit code alone explains badly: wall-clock timeouts (e.g. a web
// server that never exits), processes killed by the CPU/memory limit, and
// compile failures.
function finishLine(r, label) {
  const secs = (r.duration_seconds || 0);
  if (r.ok) return { text: `✓ ${label} finished successfully in ${secs.toFixed(2)}s`, color: '#10b981' };
  if (r.timed_out) return { text: `⏱ ${label} was stopped after the ${Math.round(secs)}s time limit. Long-running programs such as web servers cannot run in the IDE — use Chaos Lab to test services.`, color: '#fbbf24' };
  if (r.exit_code === -9 || r.exit_code === -24 || r.exit_code === 137 || r.exit_code === 152) {
    return { text: `✗ ${label} was killed after ${Math.round(secs)}s (time or memory limit exceeded, exit ${r.exit_code}). Check for an infinite loop.`, color: '#f87171' };
  }
  if (r.mode === 'compile') return { text: `✗ Compile failed (exit ${r.exit_code ?? 'unknown'})`, color: '#f87171' };
  if (/EOFError|NoSuchElementException|InputMismatchException/.test(r.stderr || '')) {
    return { text: `✗ ${label} tried to read input but none was provided. Type the values (one per line) in the "Program input" box below the terminal, then run again.`, color: '#fbbf24' };
  }
  return { text: `✗ ${label} stopped with exit ${r.exit_code ?? 'unknown'}`, color: '#f87171' };
}

export default function IdePage({ selectedProjectId, setCurrentView }) {
  const [files, setFiles] = useState([]);
  const [activePath, setActivePath] = useState('');
  const [content, setContent] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [loadingFile, setLoadingFile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [projectRunning, setProjectRunning] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [programInput, setProgramInput] = useState('');
  const [terminalLines, setTerminalLines] = useState([]);
  const [expanded, setExpanded] = useState({});
  const [filesError, setFilesError] = useState('');
  const [projectName, setProjectName] = useState('Selected project');
  const [cursorPos, setCursorPos] = useState({ line: 1, col: 1 });
  const textareaRef = React.useRef(null);
  const gutterRef = React.useRef(null);

  const handleScroll = e => {
    if (gutterRef.current) {
      gutterRef.current.scrollTop = e.target.scrollTop;
    }
  };

  const updateCursorPos = e => {
    const text = e?.target?.value ?? content ?? '';
    const selStart = e?.target?.selectionStart ?? 0;
    const linesUpToCursor = text.substring(0, selStart).split('\n');
    const currentLine = linesUpToCursor.length;
    const currentCol = linesUpToCursor[linesUpToCursor.length - 1].length + 1;
    setCursorPos({ line: currentLine, col: currentCol });
  };

  const handleKeyDown = e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = e.target.selectionStart;
      const end = e.target.selectionEnd;
      const newContent = content.substring(0, start) + '    ' + content.substring(end);
      setContent(newContent);
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.selectionStart = textareaRef.current.selectionEnd = start + 4;
          updateCursorPos({ target: textareaRef.current });
        }
      }, 0);
    }
  };

  const loadFiles = async () => {
    if (!selectedProjectId) return;
    setFilesError('');
    try {
      const result = await getProjectFiles(selectedProjectId);
      const list = result.files || [];
      setFiles(list);
      if (!list.length) setFilesError('The backend returned no editable project files. Click Refresh after the import finishes.');
      if (!activePath && list.length) setActivePath(list.find(f => /\.(py|js|jsx|ts|tsx|json|md|toml|yml|yaml|txt|html|css)$/i.test(f.path))?.path || list[0].path);
    } catch (e) {
      setFilesError(friendlyError(e) || 'Could not load project files.');
      setMessage(friendlyError(e) || 'Could not load project files.');
    }
  };

  useEffect(() => { loadFiles(); if (selectedProjectId) getProject(selectedProjectId).then(p => setProjectName(p?.name || 'Selected project')).catch(() => {}); }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId || !activePath) return;
    let cancelled = false;
    setLoadingFile(true);
    getProjectFile(selectedProjectId, activePath)
      .then(r => { if (!cancelled) { setContent(r.content || ''); setSavedContent(r.content || ''); } })
      .catch(e => { if (!cancelled) setMessage(friendlyError(e) || 'Could not open file.'); })
      .finally(() => { if (!cancelled) setLoadingFile(false); });
    return () => { cancelled = true; };
  }, [selectedProjectId, activePath]);

  const dirty = !!activePath && !loadingFile && content !== savedContent;

  // Writes the open file if it has unsaved edits. Returns false if saving failed,
  // so callers (switch file / Run / Test) don't continue with stale code.
  const saveIfDirty = async () => {
    if (!selectedProjectId || !activePath || content === savedContent) return true;
    try {
      await saveProjectFile(selectedProjectId, activePath, content);
      setSavedContent(content);
      return true;
    } catch (e) {
      setMessage(`Save failed: ${friendlyError(e)}`);
      return false;
    }
  };

  const selectFile = async path => {
    if (path === activePath) return;
    if (!(await saveIfDirty())) return;
    setMessage('');
    setActivePath(path);
  };

  const tree = useMemo(() => {
    const root = { type: 'dir', name: 'project', children: {} };
    for (const f of files) {
      const parts = f.path.split('/').filter(Boolean);
      let node = root;
      parts.forEach((part, idx) => {
        const last = idx === parts.length - 1;
        if (!node.children[part]) node.children[part] = { type: last ? 'file' : 'dir', name: part, path: parts.slice(0, idx + 1).join('/'), children: {} };
        node = node.children[part];
      });
    }
    return root;
  }, [files]);

  const renderTree = (node, depth = 0) => Object.values(node.children).sort((a,b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name)).map(child => {
    const isDir = child.type === 'dir';
    const open = expanded[child.path] !== false;
    return <React.Fragment key={child.path}>
      <button onClick={() => isDir ? setExpanded(x => ({...x, [child.path]: !open})) : selectFile(child.path)} style={{width:'100%',textAlign:'left',display:'flex',alignItems:'center',gap:5,padding:`6px 6px 6px ${8 + depth*14}px`,border:0,borderRadius:6,background:activePath===child.path?'rgba(99,102,241,.15)':'transparent',color:activePath===child.path?'#c7d2fe':isDir?'#cbd5e1':'#94a3b8',cursor:'pointer',fontSize:12,fontFamily:'inherit'}}>
        {isDir ? (open ? <ChevronDown size={13}/> : <ChevronRight size={13}/>) : <FileText size={13}/>}
        <span style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{child.name}</span>
      </button>
      {isDir && open && renderTree(child, depth+1)}
    </React.Fragment>;
  });

  const save = async () => {
    if (!selectedProjectId || !activePath || saving) return;
    setSaving(true); setMessage('');
    try {
      await saveProjectFile(selectedProjectId, activePath, content);
      setSavedContent(content);
      setMessage(`Saved ${activePath}`);
    } catch (e) { setMessage(`Save failed: ${friendlyError(e)}`); }
    finally { setSaving(false); }
  };

  // After editing (or installing dependencies), the analysis the chaos tests
  // were generated from is stale. Re-run it and say plainly whether tests can run.
  const [reanalyzing, setReanalyzing] = useState('');
  const reanalyze = async () => {
    if (!selectedProjectId || reanalyzing) return;
    setMessage('');
    try {
      if (!(await saveIfDirty())) return;
      const r = await runAnalysisPipeline(selectedProjectId, setReanalyzing);
      const text = describeAnalysis(r);
      setTerminalLines([{text: '> Re-analyze project', color:'#94a3b8'}, {text, color: r.status === 'SUPPORTED' ? '#34d399' : '#fbbf24'}]);
      setMessage(text);
    } catch (e) {
      setTerminalLines([{text: `Re-analyze failed: ${friendlyError(e)}`, color:'#f87171'}]);
      setMessage(`Re-analyze failed: ${friendlyError(e)}`);
    } finally { setReanalyzing(''); }
  };

  const test = async () => {
    if (!selectedProjectId || testing) return;
    setTesting(true); setMessage('');
    try {
      if (!(await saveIfDirty())) return;
      const r = await ideTest(selectedProjectId);
      setTerminalLines([
        {text: `> Test project`, color:'#94a3b8'},
        {text: r.stdout || '', color:'#e2e8f0'},
        {text: r.stderr || '', color:r.ok ? '#94a3b8' : '#f87171'},
        r.exit_code === 5 ? {text: '⚠ No tests were found in this project.', color:'#fbbf24'} : finishLine(r, 'Tests')
      ]);
      setMessage(r.ok ? 'Tests completed successfully.' : 'Tests did not pass or were blocked by the sandbox policy.');
    } catch (e) {
      setTerminalLines([{text: friendlyError(e) || 'Test failed.', color:'#f87171'}]);
      setMessage(`Test: ${friendlyError(e)}`);
    } finally { setTesting(false); }
  };

  const runProject = async () => {
    if (!selectedProjectId || projectRunning) return;
    setProjectRunning(true); setMessage('');
    try {
      if (!(await saveIfDirty())) return;
      const r = await ideRun(selectedProjectId, '', programInput);
      setTerminalLines([
        {text: '> Run project', color:'#94a3b8'},
        ...(r.stdout ? [{text:r.stdout, color:'#e2e8f0'}] : []),
        ...(r.stderr ? [{text:r.stderr, color:r.ok ? '#94a3b8' : '#f87171'}] : []),
        finishLine(r, 'Project')
      ]);
      setMessage(r.ok ? 'Project run completed.' : r.timed_out ? 'Project run stopped at the time limit.' : 'Project run failed. Read the terminal output for details.');
    } catch (e) {
      setTerminalLines([{text: `✗ Project run failed: ${friendlyError(e)}`, color:'#f87171'}]);
      setMessage(`Project run: ${friendlyError(e)}`);
    } finally { setProjectRunning(false); }
  };

  const run = async () => {
    if (!selectedProjectId || running) return;
    setRunning(true); setMessage('');
    try {
      if (!(await saveIfDirty())) return;
      const r = await ideRun(selectedProjectId, activePath, programInput);
      setTerminalLines([
        {text: `> Run ${activePath}`, color:'#94a3b8'},
        ...(r.stdout ? [{text:r.stdout, color:'#e2e8f0'}] : []),
        ...(r.stderr ? [{text:r.stderr, color:r.ok ? '#94a3b8' : '#f87171'}] : []),
        finishLine(r, 'Program')
      ]);
      setMessage(r.ok ? `Ran ${activePath}` : r.timed_out ? `${activePath} stopped at the time limit.` : `Run failed for ${activePath}`);
    } catch (e) {
      setTerminalLines([{text:friendlyError(e) || 'Run failed.', color:'#f87171'}]);
      setMessage(`Run: ${friendlyError(e)}`);
    } finally { setRunning(false); }
  };

  useEffect(() => {
    const onKey = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault(); save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedProjectId, activePath, content, saving]);

  const lines = useMemo(() => content.split('\n'), [content]);

  if (!selectedProjectId) {
    return <div style={{padding:'48px',color:'#fff',position:'relative',zIndex:2}}>
      <div className="glass-card" style={{padding:'40px',textAlign:'center'}}>
        <h2 style={{marginTop:0}}>No project selected</h2>
        <p style={{color:'#94a3b8'}}>Import a project before opening Cloud IDE.</p>
        <button className="btn-primary" onClick={() => setCurrentView('import')}>Import Project</button>
      </div>
    </div>;
  }

  return (
    <div style={{display:'flex',flexDirection:'column',height:'calc(100vh - 64px)',color:'#fff',position:'relative',zIndex:2}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',background:'rgba(11,14,22,.9)',padding:'8px 14px',position:'relative',zIndex:40}}>
        <div style={{minWidth:0,overflow:'hidden'}}><div style={{fontSize:'12px',fontWeight:700,color:'#e2e8f0',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{projectName}</div><div style={{fontSize:'10px',color:'#64748b',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{activePath || 'No file selected'}</div></div>
        <div style={{display:'flex',gap:8}}>
          <button title="Refresh files" className="btn-secondary" onClick={loadFiles} style={{padding:'7px 10px'}}><RefreshCw size={14}/></button>
          <button title="Save file (Ctrl+S)" className="btn-secondary" onClick={save} disabled={!activePath || saving} style={{padding:'7px 12px'}}>{saving?<Loader2 size={14} className="spin"/>:<Save size={14}/>} Save{dirty ? ' •' : ''}</button>
          <button title="Run the detected project entry point" className="btn-primary" onClick={runProject} disabled={projectRunning || !files.length} style={{padding:'7px 12px'}}>{projectRunning?<Loader2 size={14} className="spin"/>:<Play size={14}/>} Run Project</button>
          <button title="Run the selected file" className="btn-secondary" onClick={run} disabled={running || !activePath} style={{padding:'7px 12px'}}>{running?<Loader2 size={14} className="spin"/>:<Play size={14}/>} Run File</button>
          <button title="Re-run analysis so chaos tests reflect your latest code" className="btn-secondary" onClick={reanalyze} disabled={!!reanalyzing || !files.length} style={{padding:'7px 12px'}}>{reanalyzing?<Loader2 size={14} className="spin"/>:<Search size={14}/>} {reanalyzing ? (STAGE_LABELS[reanalyzing] || 'Working…') : 'Re-analyze'}</button>
          <button title="Run tests" className="btn-secondary" onClick={test} disabled={testing} style={{padding:'7px 12px'}}>{testing?<Loader2 size={14} className="spin"/>:<TestTube2 size={14}/>} Test</button>
        </div>
      </div>

      <div style={{display:'flex',flex:1,minHeight:0}}>
        <aside style={{width:270,borderRight:'1px solid rgba(255,255,255,.07)',background:'rgba(11,14,22,.88)',overflowY:'auto',padding:'12px'}}>
          <div style={{fontSize:10,fontWeight:800,color:'#64748b',letterSpacing:'.7px',marginBottom:10}}>PROJECT FILES</div>
          {files.length ? renderTree(tree) : <div style={{color:'#64748b',fontSize:11,padding:8}}>{filesError || 'No files found.'}<button onClick={loadFiles} style={{display:'block',marginTop:10,border:0,background:'rgba(99,102,241,.12)',color:'#a5b4fc',padding:'6px 9px',borderRadius:6,cursor:'pointer'}}>Refresh project files</button></div>}
        </aside>

        <section style={{flex:1,display:'flex',flexDirection:'column',minWidth:0,minHeight:0}}>
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'8px 16px',borderBottom:'1px solid rgba(255,255,255,.06)',fontSize:11,background:'rgba(8,11,18,.85)'}}>
            <div style={{minWidth:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
              <span style={{color:'#818cf8',fontWeight:600}}>{activePath || 'Select a file'}</span>
              {dirty && <span style={{marginLeft:8,color:'#fbbf24'}} title="Unsaved changes">● unsaved</span>}
              {message && <span style={{marginLeft:16,color:message.includes('failed')||message.includes('Failed')||message.includes('blocked')?'#f87171':'#34d399'}}>{message}</span>}
            </div>
            {activePath && (
              <div style={{display:'flex',alignItems:'center',gap:10,fontFamily:'JetBrains Mono,monospace',fontSize:11,color:'#64748b',flexShrink:0}}>
                <span style={{background:'rgba(255,255,255,.06)',padding:'2px 8px',borderRadius:4}}>
                  <strong style={{color:'#c7d2fe'}}>{lines.length}</strong> lines
                </span>
                <span style={{background:'rgba(99,102,241,.12)',color:'#a5b4fc',padding:'2px 8px',borderRadius:4}}>
                  Ln {cursorPos.line}, Col {cursorPos.col}
                </span>
              </div>
            )}
          </div>
          <div style={{flex:1,display:'flex',overflow:'hidden',background:'rgba(8,11,18,.75)',fontFamily:'JetBrains Mono,monospace',fontSize:13,position:'relative'}}>
            {loadingFile ? <div style={{padding:24,color:'#64748b'}}>Loading file…</div> :
              <>
                {/* Number count / Line numbers gutter */}
                <div
                  ref={gutterRef}
                  style={{
                    width: Math.max(48, String(lines.length).length * 9 + 24),
                    flexShrink: 0,
                    overflow: 'hidden',
                    userSelect: 'none',
                    borderRight: '1px solid rgba(255,255,255,.08)',
                    background: 'rgba(5,7,12,.9)',
                    padding: '16px 8px 16px 0',
                    textAlign: 'right',
                    font: '13px/22px JetBrains Mono,monospace',
                    color: '#475569',
                    boxSizing: 'border-box',
                  }}
                >
                  {lines.map((_, i) => {
                    const lineNum = i + 1;
                    const isCurrent = lineNum === cursorPos.line;
                    return (
                      <div
                        key={lineNum}
                        style={{
                          height: '22px',
                          lineHeight: '22px',
                          color: isCurrent ? '#a5b4fc' : '#475569',
                          fontWeight: isCurrent ? 700 : 400,
                          background: isCurrent ? 'rgba(99,102,241,.18)' : 'transparent',
                          paddingRight: 6,
                          borderRadius: 2,
                        }}
                      >
                        {lineNum}
                      </div>
                    );
                  })}
                </div>

                {/* Code textarea with synchronized scrolling */}
                <textarea
                  ref={textareaRef}
                  value={content}
                  onChange={e => { setContent(e.target.value); updateCursorPos(e); }}
                  onScroll={handleScroll}
                  onKeyUp={updateCursorPos}
                  onClick={updateCursorPos}
                  onKeyDown={handleKeyDown}
                  spellCheck={false}
                  style={{
                    flex: 1,
                    height: '100%',
                    minHeight: 240,
                    resize: 'none',
                    border: 0,
                    outline: 0,
                    padding: '16px 16px',
                    boxSizing: 'border-box',
                    background: 'transparent',
                    color: '#e2e8f0',
                    font: '13px/22px JetBrains Mono,monospace',
                    whiteSpace: 'pre',
                    overflowWrap: 'normal',
                    overflowX: 'auto',
                    overflowY: 'auto',
                    tabSize: 4,
                  }}
                />
              </>
            }
          </div>
          <div style={{height:150,flexShrink:0,borderTop:'1px solid rgba(255,255,255,.08)',background:'rgba(4,6,12,.95)',overflow:'auto',padding:'12px 16px',font:'12px/1.6 JetBrains Mono,monospace'}}>
            {terminalLines.length ? terminalLines.map((l,i)=><div key={i} style={{color:l.color||'#e2e8f0',whiteSpace:'pre-wrap'}}>{l.text}</div>) : <span style={{color:'#475569'}}>Terminal output will appear here.</span>}
          </div>
          <div style={{flexShrink:0,borderTop:'1px solid rgba(255,255,255,.08)',background:'rgba(8,11,18,.95)',padding:'8px 16px',display:'flex',gap:10,alignItems:'flex-start'}}>
            <label htmlFor="program-input" style={{fontSize:10,fontWeight:800,color:'#64748b',letterSpacing:'.7px',paddingTop:8,whiteSpace:'nowrap'}}>PROGRAM INPUT</label>
            <textarea id="program-input" value={programInput} onChange={e=>setProgramInput(e.target.value)}
              placeholder={'For programs that ask for input, type one value per line, e.g.\n10\n20'}
              spellCheck={false} rows={2}
              style={{flex:1,resize:'vertical',maxHeight:120,border:'1px solid rgba(255,255,255,.1)',borderRadius:6,outline:0,padding:'6px 10px',background:'rgba(4,6,12,.9)',color:'#e2e8f0',font:'12px/1.5 JetBrains Mono,monospace'}} />
          </div>
        </section>
      </div>
    </div>
  );
}
