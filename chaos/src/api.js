// Chaos Tutor backend client. Firebase ID tokens are attached automatically.
import { auth } from './firebase';
import { friendlyError } from './utils/friendlyError';

const API_BASE=(() => {
  let envUrl = (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '');
  if (envUrl && !envUrl.startsWith('http://') && !envUrl.startsWith('https://')) {
    envUrl = `https://${envUrl}`;
  }
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    const host = window.location.hostname;
    // When accessed over the network (e.g. from mobile phone or other PC via LAN IP),
    // route API requests to that same host on backend port 8090, unless an explicit external domain is configured.
    if (host !== 'localhost' && host !== '127.0.0.1') {
      if (!envUrl || envUrl.includes('localhost') || envUrl.includes('127.0.0.1')) {
        return `${window.location.protocol}//${host}:8090`;
      }
    }
  }
  return envUrl || 'http://127.0.0.1:8090';
})();
const API_TOKEN=import.meta.env.VITE_API_TOKEN||'';

async function request(path, options={}) {
  const headers=new Headers(options.headers||{});
  // Wait for Firebase to restore the saved session, otherwise the first request after a
  if (auth?.authStateReady) { try { await auth.authStateReady(); } catch {} }
  const user=auth?.currentUser;
  if (API_TOKEN && !user) {
    headers.set('Authorization',`Bearer ${API_TOKEN}`);
  } else if (user) {
    const token=await user.getIdToken();
    if (token) headers.set('Authorization',`Bearer ${token}`);
  }
  // Attach user-configured Settings API keys if present (takes precedence over .env)
  try {
    const rawKeys = localStorage.getItem('chaosTutorApiKeys');
    if (rawKeys) {
      const k = JSON.parse(rawKeys);
      if (k.gemini) headers.set('X-Gemini-Key', k.gemini);
      if (k.groq) headers.set('X-Groq-Key', k.groq);
      if (k.openai) headers.set('X-Openai-Key', k.openai);
      if (k.anthropic) headers.set('X-Anthropic-Key', k.anthropic);
      if (k.openrouter) headers.set('X-Openrouter-Key', k.openrouter);
    }
  } catch {}
  // Requests get a timeout so a stalled backend shows a clear error
  // instead of an endless "Loading..." spinner.
  const isGet=!options.method||String(options.method).toUpperCase()==='GET';
  const isUpload=path==='/projects/upload';
  const isGit=path==='/projects/import-git'||path.endsWith('/git/refresh');
  const isRun=path.includes('/run');
  let controller=null, timer=null;
  if (!options.signal) {
    controller=new AbortController();
    const timeoutMs=(isUpload||isGit) ? 150000 : (isRun ? 180000 : (isGet ? 45000 : 60000));
    timer=setTimeout(()=>controller.abort(),timeoutMs);
    options={...options,signal:controller.signal};
  }
  let res, text;
  try {
    res=await fetch(`${API_BASE}${path}`,{...options,headers});
    text=await res.text();
  } catch (err) {
    if (controller && err?.name==='AbortError') throw new Error('The backend request timed out. Check that the backend server is running on ' + API_BASE + ', then retry.');
    if (err?.name==='AbortError') throw err;   // user-cancelled request: callers check err.name
    // Browser network failures ("Failed to fetch") -> plain language
    const friendly=new Error(friendlyError(err)); friendly.raw=err?.message; throw friendly;
  } finally { if (timer) clearTimeout(timer); }
  let body={};
  try{body=text?JSON.parse(text):{}}catch{body={raw:text}}
  if(!res.ok){
    const raw=body.message||body.error||body.detail||res.statusText||'Request failed';
    const byStatus={400:'The request was not accepted. Check what you entered and try again.',409:'This action conflicts with the current state. Refresh the page and try again.',415:'This file type is not supported here.',422:'Some of the information sent is not valid. Check it and try again.',429:'Too many requests. Wait a minute and try again.',504:'The backend took too long to answer. Try again in a moment.',401:'You are signed out or your session expired. Sign in again and retry.',403:'You do not have permission to do this.',404:'That item was not found. It may have been deleted. Refresh the page or pick another project.',413:'This file is too large to import. Remove node_modules, build folders and large data files, then try again.',500:'Something went wrong inside the backend. Check the backend window for details and try again.',502:'The backend is not responding. Make sure it is running, then try again.',503:'The backend is busy or not ready. Wait a moment and try again.'};
    const text=typeof raw==='string'?raw:JSON.stringify(raw);
    const friendly=friendlyError(text);
    // Bare HTTP statuses (backend sent no real message) get a plain sentence by status code; anything else uses the translated text
    const bare=!text||text===res.statusText||text==='Request failed';
    const e=new Error(bare?(byStatus[res.status]||friendly):friendly);
    e.status=res.status;e.body=body;e.raw=text;throw e}
  return body;
}
const json=(method,body={})=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const API_URL=API_BASE;
export const health=()=>request('/health');
export const listProjects=()=>request('/projects');
export const getProject=id=>request(`/projects/${id}`);
export const deleteProject=id=>request(`/projects/${id}`,{method:'DELETE'});
export const uploadProject=(file,name)=>request('/projects/upload',{method:'POST',headers:{'Content-Type':'application/zip','X-Project-Name':encodeURIComponent(name||file?.name?.replace(/\.zip$/i,'')||'My Project')},body:file});
export const getGitStatus=()=>request('/git/status');
export const importGitProject=(url,branch,name)=>request('/projects/import-git',json('POST',{url,...(branch?{branch}:{}),...(name?{name}:{})}));
// Resolves {conflict:true, modified_files:[...]} instead of throwing when the
// refresh would overwrite the user's IDE edits (HTTP 409), so the UI can ask.
export const refreshGitProject=async(id,discardLocalChanges=false)=>{
  try{return await request(`/projects/${id}/git/refresh`,json('POST',{discard_local_changes:!!discardLocalChanges}))}
  catch(e){if(e.status===409&&e.body?.error==='local_changes')return {conflict:true,message:e.body.message,modified_files:e.body.modified_files||[]};throw e}
};
export const analyzeProject=id=>request(`/projects/${id}/analyze`,json('POST'));
export const getAnalysis=id=>request(`/projects/${id}/analysis`);
export const discoverFailures=id=>request(`/projects/${id}/discover-failures`,json('POST'));
export const getFailurePoints=id=>request(`/projects/${id}/failure-points`);
export const generateExperiments=id=>request(`/projects/${id}/generate-experiments`,json('POST'));
export const getExperiments=id=>request(`/projects/${id}/experiments`);
export const getExperiment=id=>request(`/experiments/${id}`);
export const runExperiment=(id,signal)=>request(`/experiments/${id}/run`,{...json('POST'),signal});
export const getExperimentRuns=id=>request(`/experiments/${id}/runs`);
export const listRuns=(limit=100)=>request(`/runs?limit=${limit}`);
export const getRun=id=>request(`/runs/${id}`);
export const getRunLogs=id=>request(`/runs/${id}/logs`);
export const getProjectLogs=(id,runId='',limit=500)=>request(`/projects/${id}/logs?limit=${limit}${runId?`&run_id=${encodeURIComponent(runId)}`:''}`);
export const getRunDiagnosis=id=>request(`/runs/${id}/diagnosis`);
export const getTutor=id=>request(`/runs/${id}/tutor`);
export const getTutorContext=id=>request(`/runs/${id}/tutor-context`);
export const getProjectLatestRun=id=>request(`/projects/${id}/latest-run`);
export const answerTutor=(id,answer)=>request(`/tutor/${id}/answer`,json('POST',{answer}));
export const askTutor=(id,question,history=[])=>request(`/tutor/${id}/ask`,json('POST',{question,history}));
export const getCapabilities=()=>request('/capabilities');
export const getCoverage=id=>request(`/projects/${id}/coverage`);
export const getReport=id=>request(`/projects/${id}/report`);
export const getProjectFiles=id=>request(`/projects/${id}/files`);
export const getProjectFile=(id,path)=>request(`/projects/${id}/files/content?path=${encodeURIComponent(path)}`);
export const saveProjectFile=(id,path,content)=>request(`/projects/${id}/files/content`,json('PUT',{path,content}));
export const ideTest=id=>request(`/projects/${id}/ide/test`,json('POST'));
export const ideRun=(id,path,stdin='')=>request(`/projects/${id}/ide/run`,json('POST',{path,stdin}));
export const cancelExperimentRun=id=>request(`/runs/${id}/cancel`,json('POST'));
export const checkApiKey=(provider,key,endpoint='')=>request('/keys/check',json('POST',{provider,key,endpoint: endpoint || undefined}));
export const getApiKeyStatus=()=>request('/keys/status');
export const getBackendSettingsKeys=()=>request('/settings/keys');
export const saveBackendSettingsKeys=(keys)=>request('/settings/keys',json('POST',{keys}));


// Compatibility adapters for the original Chaos Lab UI. They preserve its visual
// controls while routing actions to the real project/experiment backend.
export const isBackendReachable = async () => { try { await health(); return true; } catch { return false; } };
const PRESET_FAULT = {
    high_latency: 'slow_response',
    malformed_request: 'malformed_request',
    request_burst: 'request_burst',
    server_crash_503: 'process_kill',
    empty_input: 'empty_input',
    oversized_payload: 'oversized_payload',
    boundary_input: 'boundary_input',
    invalid_content_type: 'invalid_content_type',
    connection_refused: 'connection_refused',
    process_kill_recovery: 'process_kill_recovery',
    missing_env_var: 'missing_env_var',
    missing_file: 'missing_file',
    permission_denied: 'permission_denied',
    db_connection_refused: 'db_connection_refused',
    wrong_http_method: 'wrong_http_method',
    null_json_body: 'null_json_body',
    special_characters: 'special_characters',
    long_url: 'long_url',
    unknown_route: 'unknown_route',
    deeply_nested_json: 'deeply_nested_json',
};
const findExperimentForPreset = (experiments, preset) => {
  const presetFault = PRESET_FAULT[preset] || preset;
  // Exact fault_type match only. A fuzzy name match could run a different test
  // (e.g. "process kill" also matches "process kill recovery").
  const exp = experiments.find(e => String(e.fault_type || '').toLowerCase() === String(presetFault).toLowerCase());
  return { exp, presetFault };
};

// Which Chaos Lab buttons can actually run for this project, and why not.
export const getPresetAvailability = async (projectId) => {
  const { experiments = [] } = await getExperiments(projectId);
  const out = {};
  for (const preset of Object.keys(PRESET_FAULT)) {
    const { exp } = findExperimentForPreset(experiments, preset);
    if (!exp) out[preset] = { available: false, reason: 'Not applicable: this project has no matching failure point for this test.' };
    else if (exp.status && exp.status !== 'READY') out[preset] = { available: false, reason: exp.block_reason || `Not runnable (${exp.status}).` };
    else out[preset] = { available: true };
  }
  return out;
};

export const setPreset = async (preset, signal, explicitProjectId) => {
  // The project is passed in explicitly by Chaos Lab so the test always runs on the project the
  // user picked on screen, never on whatever happened to be left in localStorage.
  const projectId = explicitProjectId || localStorage.getItem('chaosTutorProjectId');
  if (!projectId) throw new Error('Import a project first.');
  const { experiments = [] } = await getExperiments(projectId);
  if (!experiments.length) {
    // Say WHY there are none instead of a vague message (e.g. Django/React
    // projects are analyzed but cannot be executed by the chaos engine yet).
    let why = '';
    try {
      const a = await getAnalysis(projectId);
      const fw = a?.framework || a?.profile?.framework;
      const reason = a?.entrypoint?.reason || a?.execution_status_reason || a?.reason;
      const st = a?.execution_status || a?.profile?.execution_status;
      if (st && st !== 'SUPPORTED') why = `${fw ? fw + ' project: ' : ''}${reason || st}`;
    } catch (_) { /* fall through to generic text */ }
    throw new Error(why
      ? `Chaos tests cannot run on this project yet. ${why}. Use a Flask, FastAPI, Express, or plain Python/Node project (Import Project → ZIP or Git).`
      : 'No experiments were generated for this project. Open Import Project and re-run analysis, or try another project.');
  }
  const { exp, presetFault } = findExperimentForPreset(experiments, preset);
  // Never silently substitute a different, unrelated experiment — that would
  // run one fault while the UI claims another was injected. Fail honestly
  // instead, same as the "no experiments at all" case above.
  if (!exp) {
    throw new Error(`This project has no "${String(presetFault).replace(/_/g, ' ')}" scenario available — that failure point wasn't detected for it.`);
  }
  if (exp.status && exp.status !== 'READY') {
    throw new Error(`"${exp.name}" isn't runnable for this project (${exp.block_reason || exp.status}).`);
  }
  const result = await runExperiment(exp.id, signal);
  localStorage.setItem('chaosTutorRunId', result.run_id);
  localStorage.setItem('chaosTutorProjectId', projectId);
  window.dispatchEvent(new Event('chaosTutorRunChanged'));
  return result;
};
export const getLogs = async (runId = localStorage.getItem('chaosTutorRunId')) => {
  if (!runId) return { events: [] };
  return getRunLogs(runId);
};
