import { friendlyError } from '../utils/friendlyError';
import React, { useEffect, useState } from 'react';
import { GitBranch, GitCommit, Code2, FlaskConical, RefreshCw, Trash2, Loader2, Folder } from 'lucide-react';
import SpotlightCard from '../components/SpotlightCard';
import { listProjects, deleteProject } from '../api';
import { refreshWithPrompt, shortCommit, STAGE_LABELS } from '../utils/gitActions';

const fmtDate = (t) => (t ? new Date(Number(t) * 1000).toLocaleString() : '');

// Embedded inside Import Project -> Git tab: lists cloned repositories with
// Edit / Run tests / Pull latest / Delete. `reloadKey` re-fetches after a clone.
export default function GitReposPage({ setCurrentView, setSelectedProjectId, selectedProjectId, reloadKey = 0 }) {
  const [repos, setRepos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState({});          // projectId -> stage label key
  const [notes, setNotes] = useState({});        // projectId -> last result message

  const load = async () => {
    try {
      const all = (await listProjects()).projects || [];
      setRepos(all.filter((p) => p.source_type === 'git'));
      setError('');
    } catch (e) {
      setError(friendlyError(e) || 'Could not load repositories.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [reloadKey]);

  const select = (p, view) => {
    setSelectedProjectId?.(p.id);
    localStorage.setItem('chaosTutorProjectId', p.id);
    setCurrentView(view);
  };

  const refresh = async (p) => {
    setBusy((b) => ({ ...b, [p.id]: 'refreshing' }));
    setNotes((n) => ({ ...n, [p.id]: '' }));
    try {
      const r = await refreshWithPrompt(p, (stage) => setBusy((b) => ({ ...b, [p.id]: stage })));
      setNotes((n) => ({ ...n, [p.id]: r.message }));
    } catch (e) {
      setNotes((n) => ({ ...n, [p.id]: `Refresh failed: ${friendlyError(e)}` }));
    } finally {
      setBusy((b) => { const { [p.id]: _drop, ...rest } = b; return rest; });
      load();
    }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete "${p.name}", its local clone, edits, and experiment history?`)) return;
    try {
      await deleteProject(p.id);
      if (selectedProjectId === p.id) {
        localStorage.removeItem('chaosTutorProjectId');
        localStorage.removeItem('chaosTutorRunId');
        setSelectedProjectId?.('');
      }
      await load();
    } catch (e) {
      setError(friendlyError(e) || 'Delete failed.');
    }
  };

  return (
    <div style={{ marginTop: 26, color: '#fff', position: 'relative', zIndex: 2 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h3 style={{ fontSize: 15, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}><GitBranch size={16} color="#818cf8" /> Your repositories ({repos.length})</h3>
        <button className="btn-secondary" onClick={load}><RefreshCw size={14} /> Reload</button>
      </div>
      {error && <div style={{ marginBottom: 14, color: '#fca5a5', fontSize: 12 }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(340px,1fr))', gap: 16 }}>
        {repos.map((p) => {
          const working = busy[p.id];
          const active = selectedProjectId === p.id;
          return (
            <SpotlightCard key={p.id} spotlightColor="rgba(99,102,241,.2)" style={{ padding: 20 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: 'rgba(99,102,241,.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><Folder size={20} color="#a5b4fc" /></div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.name}{active && <span style={{ marginLeft: 8, fontSize: 10, color: '#34d399' }}>● selected</span>}
                  </div>
                  <div style={{ fontSize: 10, color: '#64748b' }}>{p.status} · imported {fmtDate(p.created_at)}</div>
                </div>
              </div>
              <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', margin: '14px 0 6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.git_url}>{p.git_url}</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                <span className="badge badge-purple" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><GitBranch size={11} /> {p.git_branch || 'default'}</span>
                <span className="badge" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: 'monospace' }}><GitCommit size={11} /> {shortCommit(p.git_commit) || 'unknown'}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn-primary" disabled={!!working} onClick={() => select(p, 'ide')}><Code2 size={14} /> Edit code</button>
                <button className="btn-primary" disabled={!!working} onClick={() => select(p, 'chaos-lab')}><FlaskConical size={14} /> Run tests</button>
                <button className="btn-secondary" disabled={!!working} onClick={() => refresh(p)}>
                  {working ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} {working ? (STAGE_LABELS[working] || 'Working…') : 'Pull latest'}
                </button>
                <button className="btn-secondary" disabled={!!working} onClick={() => remove(p)}><Trash2 size={14} /> Delete</button>
              </div>
              {notes[p.id] && <div style={{ marginTop: 12, fontSize: 11, lineHeight: 1.5, color: notes[p.id].startsWith('Refresh failed') ? '#fca5a5' : '#a7f3d0' }}>{notes[p.id]}</div>}
            </SpotlightCard>
          );
        })}
        {!repos.length && !loading && (
          <div className="glass-card" style={{ padding: 36, textAlign: 'center', gridColumn: '1/-1' }}>
            <h3 style={{ marginTop: 0 }}>No repositories yet</h3>
            <p style={{ color: '#64748b', margin: 0 }}>Paste a public GitHub (or GitLab) URL above and click Clone & analyze.</p>
          </div>
        )}
      </div>
    </div>
  );
}
