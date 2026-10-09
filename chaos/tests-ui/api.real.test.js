import assert from 'node:assert/strict';
import { refreshGitProject, importGitProject } from '../src/api.js';

let pass = 0, fail = 0, reqs = [];
const respond = (status, body) => async (url, opts) => { reqs.push({ url, method: opts.method, body: opts.body && JSON.parse(opts.body) });
  return { ok: status < 400, status, statusText: 'x', text: async () => JSON.stringify(body) }; };
async function t(name, fn) { reqs = []; try { await fn(); pass++; console.log('  ok  ', name); } catch (e) { fail++; console.log('  FAIL', name, '\n      ', e.message); } }

await t('409 local_changes resolves {conflict:true, modified_files} instead of throwing', async () => {
  global.fetch = respond(409, { error: 'local_changes', message: 'You have edited files', modified_files: ['README'] });
  const r = await refreshGitProject('p1', false);
  assert.deepEqual(r, { conflict: true, message: 'You have edited files', modified_files: ['README'] });
  assert.match(reqs[0].url, /\/projects\/p1\/git\/refresh$/); assert.deepEqual(reqs[0].body, { discard_local_changes: false });
});
await t('discard flag is sent on the retry', async () => {
  global.fetch = respond(200, { id: 'p1', refresh: { changed: false } });
  await refreshGitProject('p1', true); assert.deepEqual(reqs[0].body, { discard_local_changes: true });
});
await t('other errors (400) still throw with the backend message + body', async () => {
  global.fetch = respond(400, { error: 'git refresh failed: network down' });
  await assert.rejects(() => refreshGitProject('p1'), e => e.message === 'git refresh failed: network down' && e.status === 400 && e.body.error === 'git refresh failed: network down');
});
await t('a 409 that is NOT local_changes is not swallowed', async () => {
  global.fetch = respond(409, { error: 'something else' });
  await assert.rejects(() => refreshGitProject('p1'), e => e.status === 409);
});
await t('importGitProject sends only the fields that were provided', async () => {
  global.fetch = respond(201, { id: 'p9' });
  await importGitProject('https://github.com/o/r', '', ''); assert.deepEqual(reqs[0].body, { url: 'https://github.com/o/r' });
  await importGitProject('https://github.com/o/r', 'dev', 'Mine'); assert.deepEqual(reqs[1].body, { url: 'https://github.com/o/r', branch: 'dev', name: 'Mine' });
  assert.match(reqs[0].url, /\/projects\/import-git$/); assert.equal(reqs[0].method, 'POST');
});
console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
