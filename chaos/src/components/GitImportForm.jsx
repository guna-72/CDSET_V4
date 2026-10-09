import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { GitBranch, Loader2, AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { getGitStatus, importGitProject } from '../api';
import { normalizeGitInput, validateGitUrl, runAnalysisPipeline, STAGE_LABELS } from '../utils/gitActions';

const inputStyle = {
  width: '100%', boxSizing: 'border-box', padding: '11px 13px', borderRadius: 10, fontSize: 13,
  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', outline: 'none',
};
const labelStyle = { display: 'block', fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 6, letterSpacing: '.03em' };

// Clone a public https git repository, then run the same analyze -> discover
// -> generate pipeline as a ZIP import. `onImported(project)` fires as soon
// as the clone succeeds (the project exists even if analysis later fails).
export default function GitImportForm({ onImported, onPipelineDone, compact = false }) {
  const [url, setUrl] = useState('');
  const [branch, setBranch] = useState('');
  const [name, setName] = useState('');
  const [stage, setStage] = useState('idle');
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [success, setSuccess] = useState(null);
  const [gitOk, setGitOk] = useState(true);
  const busy = stage !== 'idle' && stage !== 'ready' && stage !== 'imported';

  useEffect(() => {
    getGitStatus().then((s) => setGitOk(s?.git_available !== false)).catch(() => {});
  }, []);

  const submit = async (e) => {
    e?.preventDefault();
    if (busy) return;
    setError(''); setWarning(''); setSuccess(null);
    const norm = normalizeGitInput(url, branch);
    const problem = validateGitUrl(norm.url);
    if (problem) { setError(problem); return; }
    if (norm.url !== url.trim()) setUrl(norm.url);
    if (norm.branch !== branch.trim()) setBranch(norm.branch);

    let project;
    try {
      setStage('cloning');
      project = await importGitProject(norm.url, norm.branch, name.trim());
    } catch (err) {
      setStage('idle');
      setError(friendlyError(err) || 'Git import failed.');
      return;
    }
    setSuccess(project);
    localStorage.setItem('chaosTutorProjectId', project.id);
    localStorage.removeItem('chaosTutorRunId');
    onImported?.(project);
    try {
      await runAnalysisPipeline(project.id, setStage);
      setStage('ready');
      onPipelineDone?.(project, true);
    } catch (err) {
      setStage('imported');
      setWarning(`Repository cloned, but automatic analysis stopped: ${friendlyError(err)}. You can still open and edit it.`);
      onPipelineDone?.(project, false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {!compact && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#818cf8' }}>
          <GitBranch size={20} /><strong>Import from a Git repository</strong>
        </div>
      )}
      {!gitOk && (
        <div style={{ display: 'flex', gap: 8, padding: '10px 12px', borderRadius: 10, fontSize: 12, lineHeight: 1.5, color: '#fbbf24', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)' }}>
          <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>Git was not found on this computer. Install <strong>Git for Windows</strong> from git-scm.com/download/win, then restart Chaos Tutor.</span>
        </div>
      )}
      <div>
        <label style={labelStyle} htmlFor="git-url">REPOSITORY URL</label>
        <input id="git-url" style={inputStyle} value={url} disabled={busy} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo" autoComplete="off" spellCheck={false} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12 }}>
        <div>
          <label style={labelStyle} htmlFor="git-branch">BRANCH (OPTIONAL)</label>
          <input id="git-branch" style={inputStyle} value={branch} disabled={busy} onChange={(e) => setBranch(e.target.value)}
            placeholder="default branch" autoComplete="off" spellCheck={false} />
        </div>
        <div>
          <label style={labelStyle} htmlFor="git-name">PROJECT NAME (OPTIONAL)</label>
          <input id="git-name" style={inputStyle} value={name} disabled={busy} onChange={(e) => setName(e.target.value)}
            placeholder="repository name" autoComplete="off" />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>
        <Info size={14} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>Public repositories only (https). Only the latest commit of one branch is downloaded. For a private repository, download it as a ZIP and use the ZIP tab.</span>
      </div>
      <div>
        <button type="submit" className="btn-primary" disabled={busy || !url.trim()} style={{ opacity: busy || !url.trim() ? 0.6 : 1 }}>
          {busy ? <Loader2 size={15} className="spin" /> : <GitBranch size={15} />}
          {busy ? (STAGE_LABELS[stage] || 'Working…') : 'Clone & analyze'}
        </button>
      </div>
      {success && !error && (
        <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid rgba(16,185,129,0.25)', background: 'rgba(16,185,129,0.08)', color: '#a7f3d0', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <CheckCircle2 size={16} />
          <span>Cloned <strong>{success.name}</strong>{success.git_branch ? ` (${success.git_branch}` : ''}{success.git_commit ? ` @ ${success.git_commit.slice(0, 7)})` : success.git_branch ? ')' : ''}.</span>
          {stage === 'ready' && <span style={{ color: '#6ee7b7' }}>Analysis complete.</span>}
        </div>
      )}
      {warning && <div style={{ padding: '10px 12px', borderRadius: 10, fontSize: 12, lineHeight: 1.5, color: '#fbbf24', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)' }}>{warning}</div>}
      {error && (
        <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid rgba(239,68,68,0.25)', background: 'rgba(239,68,68,0.08)', color: '#fca5a5', fontSize: 12, lineHeight: 1.55, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <AlertTriangle size={16} style={{ flexShrink: 0 }} /><span>{error}</span>
        </div>
      )}
    </form>
  );
}
