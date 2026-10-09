// UI tests for the Git features: `npm run test:ui`
//  - ui.test.jsx      renders GitImportForm / GitReposPage / ProjectDetailPage in a
//                     simulated DOM (jsdom) against a mocked API and clicks through them
//  - api.real.test.js exercises the real src/api.js against a mocked fetch
// They bundle with esbuild (already installed with Vite); nothing is written outside tests-ui/.out
import esbuild from 'esbuild';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, '.out');
const stub = path.join(here, 'stub_api.js');
const banner = { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" };

await esbuild.build({
  entryPoints: [path.join(here, 'ui.test.jsx')], outfile: path.join(out, 'ui.test.js'),
  bundle: true, platform: 'node', format: 'esm', external: ['jsdom'], jsx: 'automatic',
  loader: { '.js': 'jsx', '.css': 'empty' }, logLevel: 'error', banner,
  plugins: [{ name: 'stub-api', setup(b) {
    b.onResolve({ filter: /(^|\/)api$/ }, () => ({ path: stub }));
    b.onResolve({ filter: /\.\/firebase$/ }, () => ({ path: stub }));
  } }],
});
await esbuild.build({
  entryPoints: [path.join(here, 'api.real.test.js')], outfile: path.join(out, 'api.real.test.js'),
  bundle: true, platform: 'node', format: 'esm', logLevel: 'error', define: { 'import.meta.env': '{}' },
  plugins: [{ name: 'no-firebase', setup(b) {
    b.onResolve({ filter: /\/firebase$/ }, () => ({ path: 'fb', namespace: 'fb' }));
    b.onLoad({ filter: /.*/, namespace: 'fb' }, () => ({ contents: 'export const auth=null;' }));
  } }],
});

let failed = false;
for (const f of ['friendlyError.test.mjs', 'languageErrors.test.mjs']) {
  const r = spawnSync(process.execPath, [path.join(here, f)], { stdio: 'inherit' });
  failed ||= r.status !== 0;
}
for (const f of ['gitUrl.test.mjs']) {
  const r = spawnSync(process.execPath, [path.join(here, '..', 'src', 'utils', f)], { stdio: 'inherit' });
  failed ||= r.status !== 0;
}
for (const f of ['ui.test.js', 'api.real.test.js']) {
  console.log(`\n== ${f} ==`);
  const r = spawnSync(process.execPath, [path.join(out, f)], { stdio: 'inherit' });
  failed ||= r.status !== 0;
}
process.exit(failed ? 1 : 0);
