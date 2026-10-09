import './setup.js';   // must be first: installs the fake DOM before React loads
import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import assert from 'node:assert/strict';
import GitImportForm from '../src/components/GitImportForm';
import GitReposPage from '../src/pages/GitReposPage';
import ProjectDetailPage from '../src/pages/ProjectDetailPage';
import IdePage from '../src/pages/IdePage';
import { runAnalysisPipeline, describeAnalysis } from '../src/utils/gitActions';
import { calls, mock } from './stub_api.js';

let pass = 0, fail = 0;
const tick = (ms = 20) => act(async () => { await new Promise(r => setTimeout(r, ms)); });
async function mount(el) {
  const host = document.createElement('div'); document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(el); });
  await tick();
  return { host, unmount: () => act(async () => root.unmount()) };
}
function setInput(input, value) {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  set.call(input, value); input.dispatchEvent(new window.Event('input', { bubbles: true }));
}
const type = (host, id, v) => act(async () => { setInput(host.querySelector('#' + id), v); });
const submit = async (host) => { await act(async () => { host.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })); }); await tick(60); };
const click = async (btn) => { await act(async () => { btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); }); await tick(60); };
const btn = (host, text) => [...host.querySelectorAll('button')].find(b => b.textContent.includes(text));
const reset = () => { mock.profile = null; mock.generated = []; calls.length = 0; mock.gitOk = true; mock.projects = []; mock.importImpl = null; mock.refreshQueue = []; mock.failAnalyze = false; localStorage.clear(); };
async function t(name, fn) { reset(); try { await fn(); pass++; console.log('  ok  ', name); } catch (e) { fail++; console.log('  FAIL', name, '\n      ', e.message); } }
const names = () => calls.map(c => c[0]);

console.log('GitImportForm');
await t('rejects ssh:// client-side, never calls the backend', async () => {
  const { host, unmount } = await mount(<GitImportForm />);
  await type(host, 'git-url', 'ssh://git@github.com/o/r.git'); await submit(host);
  assert.match(host.textContent, /Only public https/); assert.deepEqual(names(), []); await unmount();
});
await t('rejects embedded credentials', async () => {
  const { host, unmount } = await mount(<GitImportForm />);
  await type(host, 'git-url', 'https://me:tok@github.com/o/r'); await submit(host);
  assert.match(host.textContent, /embedded credentials/); assert.deepEqual(names(), []); await unmount();
});
await t('disables the button until a URL is typed', async () => {
  const { host, unmount } = await mount(<GitImportForm />);
  assert.equal(btn(host, 'Clone & analyze').disabled, true);
  await type(host, 'git-url', 'github.com/o/r'); assert.equal(btn(host, 'Clone & analyze').disabled, false); await unmount();
});
await t('bare "github.com/o/r" is normalized, cloned, then analyzed in order', async () => {
  const done = []; const imported = [];
  const { host, unmount } = await mount(<GitImportForm onImported={p => imported.push(p.id)} onPipelineDone={(p, ok) => done.push(ok)} />);
  await type(host, 'git-url', 'github.com/octocat/Hello-World'); await submit(host);
  assert.deepEqual(calls[0], ['import', 'https://github.com/octocat/Hello-World', '', '']);
  assert.deepEqual(names(), ['import', 'analyze', 'discover', 'generate']);
  assert.match(host.textContent, /Cloned\s*Hello-World/); assert.match(host.textContent, /7fd1a60/); assert.match(host.textContent, /Analysis complete/);
  assert.deepEqual(imported, ['p1']); assert.deepEqual(done, [true]);
  assert.equal(localStorage.getItem('chaosTutorProjectId'), 'p1'); await unmount();
});
await t('pasted browser URL /tree/dev fills in the branch field', async () => {
  const { host, unmount } = await mount(<GitImportForm />);
  await type(host, 'git-url', 'https://github.com/o/r/tree/dev'); await submit(host);
  assert.deepEqual(calls[0], ['import', 'https://github.com/o/r', 'dev', '']);
  assert.equal(host.querySelector('#git-branch').value, 'dev'); await unmount();
});
await t('passes optional branch + custom name through', async () => {
  const { host, unmount } = await mount(<GitImportForm />);
  await type(host, 'git-url', 'https://github.com/o/r'); await type(host, 'git-branch', 'release'); await type(host, 'git-name', 'My App'); await submit(host);
  assert.deepEqual(calls[0], ['import', 'https://github.com/o/r', 'release', 'My App']); await unmount();
});
await t('backend rejection is shown and the pipeline is NOT started', async () => {
  mock.importImpl = async () => { throw new Error('git import rejected: repository not found, or it is private'); };
  const { host, unmount } = await mount(<GitImportForm />);
  await type(host, 'git-url', 'https://github.com/o/nope'); await submit(host);
  assert.match(host.textContent, /Git repository was not found/); assert.deepEqual(names(), ['import']);
  assert.equal(btn(host, 'Clone & analyze').disabled, false, 'form must be usable again'); await unmount();
});
await t('analysis failure after a good clone keeps the project and warns', async () => {
  mock.failAnalyze = true; const done = [];
  const { host, unmount } = await mount(<GitImportForm onPipelineDone={(p, ok) => done.push(ok)} />);
  await type(host, 'git-url', 'https://github.com/o/r'); await submit(host);
  assert.match(host.textContent, /Repository cloned, but automatic analysis stopped: boom/); assert.match(host.textContent, /Cloned/);
  assert.deepEqual(done, [false]); await unmount();
});
await t('warns when git is not installed', async () => {
  mock.gitOk = false; const { host, unmount } = await mount(<GitImportForm />);
  assert.match(host.textContent, /Git was not found[\s\S]*Git for Windows/); await unmount();
});

console.log('GitReposPage');
const GIT = { id: 'g1', name: 'Hello-World', source_type: 'git', git_url: 'https://github.com/octocat/Hello-World', git_branch: 'master', git_commit: '7fd1a60b01f91b314f', status: 'ANALYZED', created_at: 1790509245.44 };
const ZIP = { id: 'z1', name: 'zipped-thing', source_type: 'upload', status: 'UPLOADED', created_at: 1790509245.44 };
const props = () => ({ setCurrentView: v => (props.view = v), setSelectedProjectId: id => (props.sel = id), selectedProjectId: '' });
await t('lists only git projects with branch + short commit; hides zip uploads', async () => {
  mock.projects = [ZIP, GIT];
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  assert.match(host.textContent, /Your repositories \(1\)/); assert.match(host.textContent, /Hello-World/); assert.match(host.textContent, /7fd1a60/);
  assert.doesNotMatch(host.textContent, /zipped-thing/); await unmount();
});
await t('shows an empty state with no repos', async () => {
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  assert.match(host.textContent, /No repositories yet/); await unmount();
});
await t('"Edit code" selects the project and opens the IDE; "Run tests" opens Chaos Lab', async () => {
  mock.projects = [GIT]; const p = props();
  const { host, unmount } = await mount(<GitReposPage {...p} />);
  await click(btn(host, 'Edit code')); assert.equal(props.view, 'ide'); assert.equal(props.sel, 'g1'); assert.equal(localStorage.getItem('chaosTutorProjectId'), 'g1');
  await click(btn(host, 'Run tests')); assert.equal(props.view, 'chaos-lab'); await unmount();
});
await t('Pull latest: up to date -> plain message, no re-analysis', async () => {
  mock.projects = [GIT]; mock.refreshQueue = [{ ...GIT, refresh: { changed: false, discarded_files: [], analysis_invalidated: false } }];
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Pull latest')); assert.match(host.textContent, /Already up to date \(7fd1a60\)/);
  assert.deepEqual(names(), ['refresh']); await unmount();
});
await t('Pull latest: new commit -> message + automatic re-analysis', async () => {
  mock.projects = [GIT]; mock.refreshQueue = [{ ...GIT, git_commit: 'abcdef1234', refresh: { changed: true, previous_commit: '7fd1a60b0', commit: 'abcdef1234', discarded_files: [], analysis_invalidated: true } }];
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Pull latest')); assert.match(host.textContent, /Updated 7fd1a60 → abcdef1/); assert.match(host.textContent, /Re-analyzed/);
  assert.deepEqual(names(), ['refresh', 'analyze', 'discover', 'generate']); await unmount();
});
await t('Pull latest: IDE edits + user says NO -> nothing discarded', async () => {
  mock.projects = [GIT]; mock.refreshQueue = [{ conflict: true, modified_files: ['app.py', 'README'] }];
  let asked = ''; window.confirm = m => { asked = m; return false; };
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Pull latest'));
  assert.match(asked, /app\.py/); assert.match(host.textContent, /Refresh cancelled\. Your edits were kept/);
  assert.deepEqual(calls.filter(c => c[0] === 'refresh'), [['refresh', 'g1', false]]); await unmount();
});
await t('Pull latest: IDE edits + user says YES -> retried with discard=true', async () => {
  mock.projects = [GIT];
  mock.refreshQueue = [{ conflict: true, modified_files: ['app.py'] }, { ...GIT, refresh: { changed: false, discarded_files: ['app.py'], analysis_invalidated: true } }];
  window.confirm = () => true;
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Pull latest'));
  assert.deepEqual(calls.filter(c => c[0] === 'refresh'), [['refresh', 'g1', false], ['refresh', 'g1', true]]);
  assert.match(host.textContent, /Discarded 1 local edit/); assert.ok(names().includes('analyze')); await unmount();
});
await t('Pull latest: backend error is shown, button recovers', async () => {
  mock.projects = [GIT]; mock.refreshQueue = [new Error('git refresh failed: network down')];
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Pull latest'));
  assert.match(host.textContent, /Refresh failed/); assert.equal(btn(host, 'Pull latest').disabled, false); await unmount();
});
await t('Delete asks first; cancelling deletes nothing', async () => {
  mock.projects = [GIT]; window.confirm = () => false;
  const { host, unmount } = await mount(<GitReposPage {...props()} />);
  await click(btn(host, 'Delete')); assert.deepEqual(names(), []); await unmount();
});

console.log('ProjectDetailPage');
await t('shows a readable date (not a raw epoch) and git badge only on git projects', async () => {
  mock.projects = [ZIP, GIT];
  const { host, unmount } = await mount(<ProjectDetailPage {...props()} />);
  assert.doesNotMatch(host.textContent, /1790509245/, 'raw epoch leaked into the UI');
  assert.match(host.textContent, /20\d\d/);
  assert.equal([...host.querySelectorAll('button')].filter(b => b.textContent.includes('Pull latest')).length, 1);
  assert.match(host.textContent, /7fd1a60/); await unmount();
});

console.log('Re-analyze (pipeline summary + IDE button)');
await t('summary reports SUPPORTED with ready/blocked counts', async () => {
  mock.profile = { execution_status: 'SUPPORTED' };
  mock.generated = [{ status: 'READY' }, { status: 'READY' }, { status: 'BLOCKED' }];
  const r = await runAnalysisPipeline('p1');
  assert.deepEqual(r, { status: 'SUPPORTED', reason: '', ready: 2, blocked: 1 });
  assert.match(describeAnalysis(r), /Ready: 2 chaos test\(s\) can run, 1 are blocked/);
});
await t('summary explains why an unrunnable project is blocked', async () => {
  mock.profile = { execution_status: 'PARTIALLY_SUPPORTED', execution_status_reason: 'node_modules is not present' };
  mock.generated = [{ status: 'BLOCKED' }, { status: 'BLOCKED' }];
  const text = describeAnalysis(await runAnalysisPipeline('p1'));
  assert.match(text, /can't run on this project yet \(PARTIALLY_SUPPORTED\): node_modules is not present/);
});
await t('summary tolerates missing fields', async () => {
  const r = await runAnalysisPipeline('p1');
  assert.equal(r.status, 'SUPPORTED'); assert.equal(r.ready, 0);
  assert.equal(describeAnalysis(null), '');
});
await t('IDE Re-analyze runs analyze -> discover -> generate and shows the verdict', async () => {
  mock.profile = { execution_status: 'PARTIALLY_SUPPORTED', execution_status_reason: 'no PORT env var read' };
  mock.generated = [{ status: 'BLOCKED' }];
  const { host, unmount } = await mount(<IdePage selectedProjectId="p1" setCurrentView={() => {}} />);
  await click(btn(host, 'Re-analyze'));
  assert.deepEqual(names().filter(n => n !== 'save'), ['analyze', 'discover', 'generate']);
  assert.match(host.textContent, /can't run on this project yet \(PARTIALLY_SUPPORTED\): no PORT env var read/);
  assert.equal(btn(host, 'Re-analyze').disabled, false, 'button must recover'); await unmount();
});
await t('IDE Re-analyze reports success when the project is runnable', async () => {
  mock.profile = { execution_status: 'SUPPORTED' }; mock.generated = [{ status: 'READY' }];
  const { host, unmount } = await mount(<IdePage selectedProjectId="p1" setCurrentView={() => {}} />);
  await click(btn(host, 'Re-analyze')); assert.match(host.textContent, /Ready: 1 chaos test\(s\) can run/); await unmount();
});
await t('IDE Re-analyze shows an error and recovers when analysis fails', async () => {
  mock.failAnalyze = true;
  const { host, unmount } = await mount(<IdePage selectedProjectId="p1" setCurrentView={() => {}} />);
  await click(btn(host, 'Re-analyze')); assert.match(host.textContent, /Re-analyze failed: boom/);
  assert.equal(btn(host, 'Re-analyze').disabled, false); await unmount();
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
