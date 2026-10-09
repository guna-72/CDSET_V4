import React, { useRef, useState } from 'react';
import { UploadCloud, GitBranch, FileArchive, File, FolderOpen, CheckCircle2, ArrowRight, Loader2, AlertTriangle } from 'lucide-react';
import BlurText from '../components/BlurText';
import { uploadProject, analyzeProject, discoverFailures, generateExperiments } from '../api';
import { zipFiles } from '../utils/zipFiles';
import GitImportForm from '../components/GitImportForm';
import GitReposPage from './GitReposPage';
import { friendlyError } from '../utils/friendlyError';

const TABS = [
  { id: 'zip', label: 'ZIP Archive', icon: FileArchive },
  { id: 'file', label: 'Single File', icon: File },
  { id: 'folder', label: 'Project Folder', icon: FolderOpen },
  { id: 'git', label: 'Git', icon: GitBranch },
];

export default function ImportPage({ setCurrentView, setSelectedProjectId, selectedProjectId, initialTab = 'zip' }) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [gitReload, setGitReload] = useState(0);
  const [isImporting, setIsImporting] = useState(false);
  const [stage, setStage] = useState('idle');
  const [statusDetail, setStatusDetail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(null);
  const inputRef = useRef(null);

  const openPicker = () => inputRef.current?.click();

  const importFiles = async (files) => {
    const selected = Array.from(files || []);
    if (!selected.length) return;
    setError('');
    setSuccess(null);
    setIsImporting(true);
    setStage('preparing');
    setStatusDetail('Scanning source files…');

    try {
      const first = selected[0];
      const isZip = activeTab === 'zip' || /\.zip$/i.test(first.name);
      const payload = isZip ? first : await zipFiles(selected, (curr, total) => {
        setStatusDetail(`Packaging source files (${curr}/${total})…`);
      });

      // Prefer the user's actual project/folder name. For a ZIP, use the first
      // meaningful top-level directory when the archive filename is generic.
      const cleanName = (value) => String(value || '')
        .replace(/\.zip$/i, '')
        .replace(/\.(tar|gz|rar|7z)$/i, '')
        .replace(/[_-]+/g, ' ')
        .trim();
      let projectName = activeTab === 'folder'
        ? cleanName(first.webkitRelativePath?.split('/')[0] || first.name)
        : cleanName(first.name);
      if (!projectName || /^(imported project|uploaded project|project)$/i.test(projectName)) {
        projectName = cleanName(first.webkitRelativePath?.split('/')[0] || first.name) || 'My Project';
      }

      setStage('uploading');
      setStatusDetail('Uploading project archive to backend…');
      const project = await uploadProject(payload, projectName || 'imported-project');
      setSelectedProjectId?.(project.id);
      localStorage.setItem('chaosTutorProjectId', project.id);
      localStorage.removeItem('chaosTutorRunId');
      setSuccess({ project, message: `Imported ${project.name || projectName} successfully.`, summary: project.import_summary || null });

      // Import is successful even if analysis later fails. Keep the project available.
      try {
        setStage('analyzing');
        setStatusDetail('Analyzing languages, framework, and entrypoint…');
        await analyzeProject(project.id);
        setStage('discovering');
        setStatusDetail('Discovering failure surfaces and endpoints…');
        await discoverFailures(project.id);
        setStage('generating');
        setStatusDetail('Generating safety-gated chaos experiments…');
        await generateExperiments(project.id);
        setStage('ready');
        setStatusDetail('Project ready!');
        setCurrentView('overview');
      } catch (pipelineError) {
        setStage('imported');
        setError(`Project imported, but automatic analysis stopped. ${friendlyError(pipelineError) || 'Analysis failed.'} You can open Projects and run the analysis again.`);
      } finally {
        // The imported project is still a real backend project even if one
        // analysis stage fails. Always open its Overview so the user can
        // inspect the actual imported workspace instead of returning to a
        // previous/demo project.
        setCurrentView('overview');
      }
    } catch (e) {
      setStage('idle');
      setStatusDetail('');
      setError(friendlyError(e) || 'Project import failed. Please try again.');
    } finally {
      setIsImporting(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleInput = (event) => importFiles(event.target.files);
  const handleDrop = (event) => {
    event.preventDefault();
    importFiles(event.dataTransfer.files);
  };

  const stageLabel = {
    preparing: 'Preparing project…', uploading: 'Importing project…', analyzing: 'Analyzing project…',
    discovering: 'Discovering failure points…', generating: 'Generating experiments…', ready: 'Ready', imported: 'Imported'
  }[stage] || 'Choose a project';

  const accept = activeTab === 'zip' ? '.zip,application/zip' : '*/*';

  return (
    <div style={{ padding: '32px', color: '#fff', zIndex: 1, position: 'relative' }}>
      <div style={{ marginBottom: '28px' }}>
        <BlurText as="h1" text="Import Project" animateBy="letters" delay={20} style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '-0.5px', marginBottom: '6px' }} />
        <p style={{ color: '#94a3b8', fontSize: '13px', margin: 0 }}>Import a ZIP archive, a single source file, a local project folder, or a public Git repository.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(280px, 1fr)', gap: '24px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="glass-card" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', padding: '5px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)', marginBottom: '22px' }}>
              {TABS.map(({ id, label, icon: Icon }) => (
                <button key={id} onClick={() => { setActiveTab(id); setError(''); setSuccess(null); }} style={{
                  flex: '1 1 130px', border: '1px solid transparent', borderRadius: '9px', padding: '10px 12px',
                  background: activeTab === id ? 'rgba(99,102,241,0.16)' : 'transparent', color: activeTab === id ? '#c7d2fe' : '#94a3b8',
                  cursor: 'pointer', fontSize: '12px', fontWeight: 700, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '7px'
                }}><Icon size={15} />{label}</button>
              ))}
            </div>

            {activeTab === 'git' ? (
              <div style={{ padding: '10px 4px' }}>
                <GitImportForm
                  onImported={(p) => { setSelectedProjectId?.(p.id); setGitReload((n) => n + 1); }}
                  onPipelineDone={(_p, ok) => { setGitReload((n) => n + 1); if (ok) setCurrentView('overview'); }}
                />
                <GitReposPage
                  setCurrentView={setCurrentView}
                  setSelectedProjectId={setSelectedProjectId}
                  selectedProjectId={selectedProjectId}
                  reloadKey={gitReload}
                />
              </div>
            ) : (
              <>
                <input
                  ref={inputRef}
                  type="file"
                  accept={accept}
                  style={{ display: 'none' }}
                  onChange={handleInput}
                  {...(activeTab === 'folder' ? { webkitdirectory: '', directory: '', multiple: true } : {})}
                />
                <div onClick={!isImporting ? openPicker : undefined} onDragOver={(e) => e.preventDefault()} onDrop={handleDrop} className="upload-dropzone" style={{ borderRadius: '14px', padding: '58px 24px', textAlign: 'center', cursor: isImporting ? 'wait' : 'pointer', border: '1px dashed rgba(129,140,248,0.35)', background: 'rgba(99,102,241,0.035)' }}>
                  <div style={{ width: '64px', height: '64px', borderRadius: '18px', background: 'rgba(99,102,241,0.13)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                    {isImporting ? <Loader2 size={30} color="#818cf8" className="spin" /> : <UploadCloud size={30} color="#818cf8" />}
                  </div>
                  <h3 style={{ fontSize: '18px', fontWeight: 700, margin: '0 0 8px' }}>{isImporting ? stageLabel : activeTab === 'zip' ? 'Drop a ZIP archive here' : activeTab === 'file' ? 'Choose a source file' : 'Choose a project folder'}</h3>
                  <p style={{ color: '#94a3b8', fontSize: '13px', maxWidth: '520px', margin: '0 auto 20px', lineHeight: 1.6 }}>
                    {isImporting
                      ? (statusDetail || 'Processing project…')
                      : activeTab === 'folder'
                        ? 'All files in the selected folder are packaged with their relative paths and imported as one project (dependencies like node_modules are automatically skipped).'
                        : activeTab === 'file'
                          ? 'The selected file is packaged as a small project so the analyzer can inspect it.'
                          : 'ZIP archives are validated for path traversal, symlinks, size limits, and archive bombs before extraction.'}
                  </p>
                  <button className="btn-secondary" disabled={isImporting} onClick={(e) => { e.stopPropagation(); openPicker(); }}><UploadCloud size={15} /> Browse</button>
                  <div style={{ marginTop: '14px', fontSize: '11px', color: '#64748b' }}>Maximum import size: 500 MB ZIP / 2 GB extracted project / 50,000 archive entries</div>
                </div>
              </>
            )}

            {success && <div style={{ marginTop: '16px', padding: '12px 14px', borderRadius: '10px', border: '1px solid rgba(16,185,129,0.25)', background: 'rgba(16,185,129,0.08)', color: '#a7f3d0', fontSize: '12px' }}><div style={{display:'flex',alignItems:'center',gap:'8px'}}><CheckCircle2 size={16} /> {success.message} <span style={{ color: '#64748b' }}>Project ID: {success.project.id}</span></div>{success.summary?.ignored_generated_files ? <div style={{marginTop:6,color:'#94a3b8'}}>Skipped {success.summary.ignored_generated_files.toLocaleString()} generated dependency/build entries; source files were kept.</div> : null}</div>}
            {error && <div style={{ marginTop: '16px', padding: '12px 14px', borderRadius: '10px', border: '1px solid rgba(239,68,68,0.25)', background: 'rgba(239,68,68,0.08)', color: '#fca5a5', fontSize: '12px', lineHeight: 1.55, display:'flex', gap:8, alignItems:'flex-start' }}><AlertTriangle size={16} style={{flexShrink:0}} /> <span>{error}</span></div>}
          </div>

          <div className="glass-card" style={{ padding: '22px 24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}><h3 style={{ fontSize: '15px', margin: 0 }}>Import pipeline</h3><span className="badge badge-purple">{statusDetail || stageLabel}</span></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: '8px' }}>
              {['Upload','Analyze','Discover','Generate','Ready'].map((label, i) => <div key={label} style={{ textAlign: 'center' }}><div style={{ width: '26px', height: '26px', borderRadius: '50%', margin: '0 auto 7px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 800, background: (stage !== 'idle' && i <= ({uploading:0,preparing:0,analyzing:1,discovering:2,generating:3,ready:4,imported:0}[stage] ?? -1)) ? '#4f46e5' : 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)' }}>{i + 1}</div><div style={{ fontSize: '10px', color: '#94a3b8' }}>{label}</div></div>)}
            </div>
          </div>
        </div>

        <div className="glass-card" style={{ padding: '24px', alignSelf: 'start' }}>
          <h3 style={{ fontSize: '15px', margin: '0 0 18px' }}>What happens after import?</h3>
          {[
            ['1', 'Secure intake', 'The archive is validated before extraction.'],
            ['2', 'Project creation', 'A real project record and workspace are created.'],
            ['3', 'Code analysis', 'Languages, framework, structure, and entrypoint are detected.'],
            ['4', 'Failure discovery', 'Potential resilience surfaces are identified.'],
            ['5', 'Experiments', 'Safety-gated chaos experiments are generated.'],
          ].map(([n, title, desc]) => <div key={n} style={{ display: 'flex', gap: '12px', marginBottom: '17px' }}><div style={{ width: '25px', height: '25px', borderRadius: '8px', background: 'rgba(99,102,241,0.13)', color: '#a5b4fc', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: '10px', fontWeight: 800 }}>{n}</div><div><div style={{ fontSize: '12px', fontWeight: 700, color: '#e2e8f0' }}>{title}</div><div style={{ fontSize: '11px', color: '#64748b', lineHeight: 1.5, marginTop: '2px' }}>{desc}</div></div></div>)}
          <button className="btn-secondary" style={{ width: '100%', justifyContent: 'center', marginTop: '4px' }} onClick={() => setCurrentView('projects')}>View Projects <ArrowRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}
