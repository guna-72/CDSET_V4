import { analyzeProject, discoverFailures, generateExperiments, refreshGitProject } from '../api';

import { shortCommit } from './gitUrl';
export { shortCommit, normalizeGitInput, validateGitUrl } from './gitUrl';

// Runs analyze -> discover -> generate and returns a summary the caller can
// show: { status, reason, ready, blocked }. status is the analyzer's
// execution_status ("SUPPORTED" means chaos tests can run).
export async function runAnalysisPipeline(projectId, onStage = () => {}) {
  onStage('analyzing');
  const analysis = await analyzeProject(projectId);
  const profile = analysis?.profile || analysis || {};
  onStage('discovering');
  await discoverFailures(projectId);
  onStage('generating');
  const gen = await generateExperiments(projectId);
  const exps = gen?.experiments || [];
  onStage('ready');
  return {
    status: profile.execution_status || 'SUPPORTED',
    reason: profile.execution_status_reason || profile.entrypoint?.reason || '',
    ready: exps.filter((e) => e.status === 'READY').length,
    blocked: exps.filter((e) => e.status === 'BLOCKED').length,
  };
}

// One plain sentence for the outcome of runAnalysisPipeline.
export function describeAnalysis(r) {
  if (!r) return '';
  if (r.status === 'SUPPORTED') {
    return r.blocked
      ? `Ready: ${r.ready} chaos test(s) can run, ${r.blocked} are blocked (see Experiments for why).`
      : `Ready: ${r.ready} chaos test(s) can run.`;
  }
  return `Chaos tests can't run on this project yet (${r.status})${r.reason ? `: ${r.reason}` : '.'}`;
}

export const STAGE_LABELS = {
  cloning: 'Cloning repository…',
  refreshing: 'Fetching latest commit…',
  analyzing: 'Analyzing project…',
  discovering: 'Discovering failure points…',
  generating: 'Generating experiments…',
  ready: 'Ready',
};

// Refresh a git project. If the user has edited tracked files in the Cloud
// IDE, the backend refuses (HTTP 409) instead of silently overwriting them;
// ask before discarding. After a real change the previous analysis is stale
// (the backend clears it), so re-run the pipeline automatically.
export async function refreshWithPrompt(project, onStage = () => {}) {
  onStage('refreshing');
  let res = await refreshGitProject(project.id, false);
  if (res.conflict) {
    const files = res.modified_files || [];
    const shown = files.slice(0, 8).join('\n  ');
    const more = files.length > 8 ? `\n  …and ${files.length - 8} more` : '';
    const ok = window.confirm(
      `You edited ${files.length} file(s) in the Cloud IDE that a refresh would overwrite:\n\n  ${shown}${more}\n\n` +
      'Discard those edits and pull the latest version from Git?'
    );
    if (!ok) return { cancelled: true, message: 'Refresh cancelled. Your edits were kept.' };
    onStage('refreshing');
    res = await refreshGitProject(project.id, true);
  }
  const r = res.refresh || {};
  const discarded = (r.discarded_files || []).length;
  if (!r.changed && !discarded) {
    return { project: res, message: `Already up to date (${shortCommit(res.git_commit)}).` };
  }
  let message = r.changed
    ? `Updated ${shortCommit(r.previous_commit)} → ${shortCommit(r.commit)}.`
    : `Discarded ${discarded} local edit(s).`;
  if (r.analysis_invalidated) {
    try {
      const summary = await runAnalysisPipeline(project.id, onStage);
      message += ` Re-analyzed. ${describeAnalysis(summary)}`;
    } catch (e) {
      message += ` Automatic re-analysis stopped: ${e.message || 'analysis failed'}. Open the project to retry.`;
    }
  }
  return { project: res, message };
}
