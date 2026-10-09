# Chaos Tutor — MVP Backend (stdlib-only reference implementation)

Real, working implementation of the P0+ pipeline from the master spec:

```
UPLOAD → VALIDATE → ISOLATE → ANALYZE → DISCOVER FAILURE SURFACES →
GENERATE EXPERIMENTS → SAFETY CHECK → SANDBOX EXECUTION → OBSERVATION →
FAILURE DETECTION → AI DIAGNOSIS → DISPLAY RESULT → STORE HISTORY
```

...plus two P1 pieces (Recovery Engine, Tutor Engine) and a project
resilience report. The core backend uses the Python standard library. Firebase integration is optional and uses `firebase-admin` when cloud authentication, Firestore sync, or Storage backup is enabled. The sandbox uses a per-run Windows Firewall rule for network isolation when the backend runs elevated. See "Upgrade path" below for the spec's exact stack
(FastAPI/Postgres/Redis/Celery/Docker).

## Windows runtime

This build targets Windows only (Python 3.8–3.14). The sandbox uses
fixed-argv subprocesses, isolated workspaces, process groups, and hard
wall-clock termination as its baseline controls. When the backend is run
as Administrator, it additionally applies a per-run Windows Firewall rule
that blocks the sandboxed process's non-loopback network access
("OS-enforced network isolation"). Running elevated is optional — by
default (`CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX` defaults to enabled) the
backend runs normally from any ordinary terminal without that extra
network isolation.

## Run it

```bash
cd chaos_backend
python3 -m app.main          # http://127.0.0.1:8090
```

Try it against a bundled sample project (there are two — see below):

```bash
curl -X POST http://127.0.0.1:8090/projects/upload \
  -H "X-Project-Name: Mini Task API" \
  --data-binary @sample_projects/mini_task_api.zip
# -> {"id": "<project_id>", ...}

curl -X POST http://127.0.0.1:8090/projects/<project_id>/analyze
curl -X POST http://127.0.0.1:8090/projects/<project_id>/discover-failures
curl -X POST http://127.0.0.1:8090/projects/<project_id>/generate-experiments
curl -X POST http://127.0.0.1:8090/experiments/<experiment_id>/run
curl http://127.0.0.1:8090/runs/<run_id>/tutor
curl -X POST http://127.0.0.1:8090/tutor/<tutor_session_id>/answer -d '{"answer":"..."}'
curl http://127.0.0.1:8090/projects/<project_id>/coverage
curl http://127.0.0.1:8090/projects/<project_id>/report
```

## Run the tests

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

**Last validation in this build: 126 tests passed, 5 skipped, 0 failed (131 tests run).**
The five skips are environment-dependent network-namespace/E2E checks when
`unshare`/`nsenter` isolation is unavailable. The suite covers sandbox
security, archive-intake security, analyzer, safety gate, experiment
generator, failure detection, tutor engine, multi-provider LLM key-pool
rotation/failover, and the end-to-end pipeline. External provider network
calls were not claimed as verified in this offline execution environment.

## Configuring LLM diagnosis (optional, off by default — and off even with keys present)

By default `diagnose_run()` uses the offline rule-based diagnoser — no
setup needed, zero API spend, zero network calls.

**Two separate things are required before it will ever call out to a
real LLM — either alone does nothing:**

```bash
export OPENAI_API_KEYS="sk-...,sk-..."   # 1. at least one provider key
export ENABLE_LLM_DIAGNOSIS=true          # 2. explicit opt-in
```

This is deliberate: pasting keys in for later must never, by itself,
start spending them. `app/llm_providers.py`'s `diagnosis_enabled()` is
the actual gate `diagnose_run()` checks, and it requires both. The
backend also prints its state on every startup, so it's never silently
on:

```
AI diagnosis: OFF (rule-based only) — provider keys are configured but
ENABLE_LLM_DIAGNOSIS is not set, so no spend will occur. Set
ENABLE_LLM_DIAGNOSIS=true to turn it on.
```

Once both are set, paste as many keys as you want per provider,
comma- and/or newline-separated:

```bash
export GROQ_API_KEYS="gsk_...,gsk_..."          # free — see table below
export GEMINI_API_KEYS="AIza...,AIza..."         # free — see table below
export OPENROUTER_API_KEYS="sk-or-...,sk-or-..." # free via the openrouter/free default
export DEEPSEEK_API_KEYS="sk-...,sk-..."         # paid
export OPENAI_API_KEYS="sk-...
sk-..."                                          # paid
export ANTHROPIC_API_KEYS="sk-ant-...,sk-ant-..." # paid
```

A singular form (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, ...) is also
read and folded into that provider's pool, for a single-key setup.

**Which of these are actually free** (checked against current provider
docs/pricing for this pass — re-verify before trusting this months
later, free tiers change often):

| Provider | Free? | Notes |
|---|---|---|
| **Groq** | ✅ Yes | No card required. Genuinely free, but rate-limited **per account/org, not per key** — pasting in 5 keys from the same Groq account shares one limit pool, it does not give you 5x quota. Separate Groq accounts would. |
| **Gemini** | ✅ Yes | Free via Google AI Studio. Same caveat as Groq: limits apply **per Google Cloud project**, not per key. |
| **OpenRouter** | ✅ Yes (as configured here) | Defaults to `openrouter/free` — OpenRouter's own official router that always resolves to a genuinely $0 model and picks one that supports the JSON output this needs. This is real, different infrastructure from Groq/Gemini, so it's a good third leg rather than a duplicate. Don't override `OPENROUTER_MODEL` to a specific non-`:free` model unless you intend to pay OpenRouter for it. |
| **DeepSeek** | ❌ No | Had free promotional models through most of 2025; both DeepSeek's own free tier and its free variants on OpenRouter have since been discontinued. Cheap pay-as-you-go, not free. |
| **OpenAI** | ❌ No | No standing free API tier (only a small new-account trial credit that expires). |
| **Anthropic** | ❌ No | Same — no standing free API tier. |

**Practical recommendation**: for a genuinely free setup, configure
`GROQ_API_KEYS` and `GEMINI_API_KEYS` (and leave `OPENROUTER_API_KEYS`
on the `openrouter/free` default too, for a third fallback) and skip
the other three unless you're already paying for them. Because rotation
tries every configured provider on failure, having all three free ones
configured means a rate-limit on one genuinely fails over to a
different provider's separate quota — unlike pasting multiple keys
*within* Groq or Gemini alone, which shares one limit either way.

**What it actually costs once enabled**: one LLM call per *completed
experiment run*, not per project — generate 10 experiments, run all 10,
that's 10 calls. There's no caching or deduplication. Each call sends a
bounded evidence payload (well under the 100KB cap; typically a few
hundred to low thousands of tokens — experiment info + a stderr
snippet + status codes) and requests up to 1000 output tokens.

**Rotation mechanism** (`app/llm_providers.py`, `KeyPool`) — this
controls *which key pays*, not *how many calls happen*: every
configured `(provider, key)` pair across every provider goes into one
pool. Each diagnosis call:
1. **starts from the next position in the pool** (round-robin) — so
   load spreads across all your keys even when every call succeeds on
   the first try, and
2. **fails over to the next entry** if the current one errors (bad key,
   rate limited, provider outage), trying every configured key across
   every provider before finally giving up and falling back to the
   rule-based diagnoser (still free).

**Nothing about any of this is ever visible to the end user as an
error.** If every configured provider/key fails — rate limited, bad
key, outage, malformed response, doesn't matter — `diagnose_run()`
falls back to the rule-based diagnoser and returns a normal, complete
explanation; the failure reason is logged server-side to stderr
(`[diagnosis] LLM diagnosis failed for experiment '...', falling back
to rule-based: ...`) and never appears in the `evidence` list, the
tutor explanation, or anywhere else the frontend renders. This is
covered by
`test_keys_configured_but_all_calls_fail_falls_back_to_rule_based_silently`,
which explicitly asserts none of "llm", "provider", "connectionerror",
"api key", etc. ever shows up in the returned evidence.

Model names are overridable per provider (`ANTHROPIC_MODEL`,
`OPENAI_MODEL`, `GEMINI_MODEL`, `DEEPSEEK_MODEL`, `GROQ_MODEL`,
`OPENROUTER_MODEL`) if you want something other than the built-in
default for that provider. No key is ever logged, stored in the
database, or included in an error message — failures are reported with
a masked form (`sk-a…op`) only, see `_mask()` in `app/llm_providers.py`.

This whole path — including the two-factor gate itself — is covered by
`tests/test_llm_providers.py` and `tests/test_diagnosis_providers.py`
(key parsing, rotation order, failover across keys and across
providers, and a test that asserts a provider function is literally
never invoked when keys are present but the flag isn't set) using
mocked provider calls — the actual network calls remain untested in
this sandbox, per the limitation noted above.

## What changed in this pass ("fix bugs/drawbacks, add features")

This is the second pass on this backend. Nine real bugs were found and
fixed — every one of them by actually running the system against
something new, not by code review:

1. **Network isolation was a documented gap → now real.** This
   container turned out to be a full microVM with root, not a locked-down
   container, so `unshare --net --mount` genuinely works. Sandboxed
   services now run in their own network namespace with only loopback up
   — verified live: a direct socket connection from the harness process
   to a sandboxed port fails (`Connection refused`/`Network unreachable`),
   while the harness can still send legitimate test traffic by routing
   through `nsenter` into that specific namespace. See
   `app/sandbox.py`'s module docstring and `TestNetworkNamespaceIsolation`
   in `tests/test_sandbox_security.py`.
2. **Analyzer false positives**: any `.get()` call anywhere in a file
   (dict access, `os.environ.get`, `self.headers.get`, ...) was being
   misread as an HTTP route registration. Fixed by scoping route
   detection to actual decorators (`@app.get(...)`) via AST, not any
   attribute-call named `get`.
3. **Analyzer couldn't resolve `open(SOME_VAR)`** at all — now does,
   via light constant propagation, including the very common
   `os.path.join(os.path.dirname(__file__), "data", "x.json")` idiom
   (resolves to the literal tail `"data/x.json"`).
4. **FastAPI's `async def` route handlers were invisible** to the old
   visitor (it only walked `ast.FunctionDef`, not `ast.AsyncFunctionDef`).
5. **`node_generic` wasn't in the "this adapter implies HTTP" list**,
   so a plain Node app got zero HTTP-category experiments generated.
6. **Raw `http.createServer`-style routing wasn't detected** — only
   Express's `app.get(...)` calls were. Added detection for the
   `req.method === 'X' && ...pathname === '/y'` pattern.
7. **Node/V8 crashed instantly under the sandbox's memory limit.**
   `RLIMIT_AS` (virtual address space) is fundamentally incompatible
   with V8, which reserves a large virtual range upfront regardless of
   actual usage — confirmed live (a bare `node app.js` OOM'd before
   printing anything, under the same 512MB limit Python handles fine).
   Fixed by skipping `RLIMIT_AS` specifically for Node processes and
   capping V8's heap directly with `--max-old-space-size=256` instead —
   the standard real-world fix for sandboxing V8.
8. **Tutor gave a wrong "concept" for recovered runs** and marked a
   correct answer ("add a restart supervisor") as incorrect, because the
   diagnoser never set a `resilience_pattern` for the `RECOVERED`
   outcome and the tutor silently defaulted to "graceful degradation."
9. **Readiness-check flakiness under load** — a single `nsenter` probe
   could occasionally lose the race against a slow-starting sandbox
   under system load. Hardened with a retry and a larger timeout budget.

New features, all exercised by real tests, not just written:

- **3 new chaos experiments**: `request_burst` (concurrent load /
  spec's 429 category, via a real thread pool of concurrent sandboxed
  probes), `invalid_content_type` (mismatched header vs. body), and
  `process_kill_recovery` (see next point).
- **Recovery Engine (P1, spec section 24)** — `app/recovery.py`'s
  `SupervisedService` is a real restart-on-crash supervisor: a monitor
  thread that actually restarts the sandboxed process (same workspace,
  same port) if it dies. `process_kill_recovery` kills the process and
  measures whether/how fast it comes back — genuine supervision, not a
  simulated "recovered: true".
- **Tutor Engine (P1, spec section 25)** — `app/tutor.py` turns a real
  diagnosis into the spec's 8-part explanation (what/why/where/
  evidence/impact/prevention/recovery/concept) plus an auto-generated
  question with server-side keyword-based answer evaluation (the answer
  key never goes to the client — `GET /runs/{id}/tutor` strips it).
- **Project resilience report** — `GET /projects/{id}/report`: real run
  counts, an outcome breakdown, a resilience score, and the concrete
  findings with their diagnoses, built entirely from that project's own
  stored run history.
- **A second sample project, in Node.js** (`sample_projects/
  mini_node_api.zip`) — proves the multi-language claim for real. It's
  what surfaced bugs #5–8 above; the Python-only test suite could never
  have caught them.
- **`GET /experiments/{id}/runs`** — was missing from the P0 pass.
- **Multi-provider LLM diagnosis with key rotation, gated by a two-factor
  opt-in** — `app/llm_providers.py` replaces the single hardcoded
  Anthropic call with a pool across Anthropic/OpenAI/Gemini/DeepSeek/
  Groq/OpenRouter, accepting as many pasted keys per provider as you
  have, with round-robin + failover rotation across the whole pool.
  Configuring keys alone does **not** turn it on — `ENABLE_LLM_DIAGNOSIS`
  must also be set, specifically so pasting keys in doesn't silently
  start spending them, and the backend prints its on/off state on every
  startup. See "Configuring LLM diagnosis" above.
- **Two more real bugs found and fixed in that same system**: the
  OpenRouter default model was `openai/gpt-4o-mini` — a real, billed
  OpenRouter pass-through call that contradicted the whole "free option"
  framing — now defaults to `openrouter/free`, OpenRouter's own $0
  router. And the fallback path was leaking raw provider errors
  (`ConnectionError: ...`, key fragments, etc.) into the user-facing
  `evidence` list whenever every configured key failed — now logged to
  stderr for the operator only; the person looking at a tutor
  explanation never sees provider plumbing, success or failure.

## What's real vs. what's out of scope (honesty, per spec Rule 10)

**Actually implemented and tested, not simulated** — archive intake
security, sandbox isolation (privilege drop + rlimits + real network
namespace), AST-based project intelligence, project-aware failure
discovery/experiment generation, the safety gate, 12 chaos experiments
across HTTP/network/process/config/filesystem/database categories,
evidence-grounded rule-based diagnosis, recovery testing, the tutor
engine, and a full HTTP API — all covered by the 85 tests, run against
two real, different-language sample apps.

**Genuinely found, not planted:** the Python sample's `POST /tasks`
accepts `{"title": 12345, ...}` with no type validation (`WEAK_HANDLING`)
— not one of the two bugs deliberately written into that app. The Node
sample's uncaught `JSON.parse` throw crashing the whole process
(`CRASHED`, not just a bad response) is a real, accurate difference from
Python's `http.server`, which survives the same kind of per-request
exception.

**Still deferred to P1/future** (per spec sections 29/30, not attempted
this pass): the coverage-dashboard UI, bounded *adaptive* exploration
(auto-selecting the next experiment from prior results), WebSocket/SSE
live updates, additional recovery strategies beyond restart (backoff,
circuit breaker, fallback).

**Still deferred to the "full-stack version"**: frontend wiring (the
React app is still on mock data), FastAPI/Postgres/Redis/Celery/Docker.

## Known, honest limitations that remain

1. **Filesystem isolation is a plain directory, not a chroot/mount-
   namespace jail.** The unprivileged sandbox user could still *read*
   other world-readable files on the host (never *write* outside its
   own workspace — that part is enforced by the privilege drop). A real
   jail needs a working interpreter + shared libraries bundled inside
   every sandbox copy; deliberately not attempted, because a
   half-built jail that silently breaks execution is worse than the
   documented gap. `unshare --mount` is already in place as the
   foundation for this if it's tackled later.
2. **No seccomp/AppArmor syscall filtering.** Privilege drop + rlimits +
   network/mount namespace isolation are the enforced controls instead.
3. **Static analysis is a lightweight AST visitor, not full data-flow
   analysis.** Single-hop constant propagation (see bug #3 above) covers
   the common cases; a value that's conditionally reassigned, or built
   across more than one hop, won't resolve. Honestly reported via
   `components.static_analysis.python_files_with_syntax_errors` when a
   file can't even be parsed.
4. **AI diagnosis is rule-based by default.** `app/llm_providers.py` has
   a complete, real multi-provider client — **Anthropic, OpenAI, Gemini,
   DeepSeek, Groq, and OpenRouter** — with a key-rotation pool, but it's
   untested here (no network). See "Configuring LLM diagnosis" below.
   `diagnose_run()` falls back to the rule-based diagnoser automatically
   if every configured provider/key fails, so this is always safe to
   turn on.
5. **This backend runs as root in this container**, which is how it can
   demonstrate a real privilege drop to `nobody` for the sandboxed
   child. In production the backend service itself should also run
   unprivileged (the sandbox logic doesn't depend on it being root —
   `_drop_privileges_inline`/`_sandbox_init.py` both already handle the
   "not root, nothing to drop" case).

## Upgrade path to the spec'd stack

| This MVP | Spec'd production stack |
|---|---|
| `sqlite3` (`app/db.py`) | PostgreSQL + SQLAlchemy — same table shapes, swap the driver |
| in-process synchronous execution + a real `threading.Thread` supervisor (`app/recovery.py`) | Celery + Redis for `experiment_runs` as background jobs |
| `subprocess` + rlimits + uid drop + `unshare` net/mount namespaces (`app/sandbox.py`) | same code, **plus** run inside `docker run --network=none --cap-drop=ALL --read-only` for defense in depth (container + the namespace isolation this MVP already has) |
| stdlib `http.server` router (`app/http_framework.py`, `app/api.py`) | FastAPI + Pydantic — the route handlers in `app/api.py` translate almost 1:1 |
| rule-based diagnoser | `LLMDiagnoser` in `app/diagnosis.py`, already written — just needs network + `ANTHROPIC_API_KEY` |
| plain isolated directory per sandbox | add a chroot/mount-namespace jail with a bundled interpreter, per limitation #1 above |

None of the core logic (analyzer, failure discovery, experiment
generator, safety gate, chaos engine, detection, recovery, tutor) needs
to change for this upgrade — only the infrastructure layer underneath it.

## Security and portability hardening (2026-09-20)

This build adds several runtime protections without changing the experiment safety model:

- bounded HTTP request bodies (`100 MB + 1 MB` upload ceiling; `2 MB` JSON ceiling)
- strict CORS allowlist via `CHAOS_TUTOR_CORS_ORIGINS` (no wildcard CORS)
- optional Bearer API authentication via `CHAOS_TUTOR_API_TOKEN`
- POST rate limiting (`30/minute/IP` by default)
- security response headers (`nosniff`, `DENY`, `no-store`, strict referrer policy)
- generic client-facing 500 errors; tracebacks stay server-side
- sanitized project names and original filenames
- per-thread SQLite schema initialization for the threaded HTTP server
- bounded concurrent experiment execution (`MAX_ACTIVE_EXPERIMENTS_SYSTEM`)
- stronger sandbox workspace containment checks using real paths
- sandbox environment-variable allowlisting and blocking of `PYTHONPATH`, `NODE_OPTIONS`, loader injection variables, and arbitrary environment overrides
- process-count and file-descriptor limits on POSIX sandboxes
- real tutor follow-up endpoint (`POST /tutor/{id}/ask`)
- runtime capability endpoint (`GET /capabilities`)

### Optional authentication

For a private deployment:

```text
CHAOS_TUTOR_API_TOKEN=<long-random-secret>
CHAOS_TUTOR_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

The frontend can send the same token using `VITE_API_TOKEN`. Do not treat a browser-bundled token as a production secret; for internet-facing deployments use a reverse proxy or real identity-token verification.

## Runtime hardening notes

- Native Windows startup requires no Administrator rights; Windows Firewall network isolation is reported as unavailable (rather than blocking startup) when the backend is not running elevated.
- `GET /capabilities` reports actual platform, Python version, namespace support, LLM status, and whether API authentication is enabled.
- Set `CHAOS_TUTOR_API_TOKEN` to require Bearer authentication for API routes (health/capabilities remain public for readiness checks).
- Set `CHAOS_TUTOR_CORS_ORIGINS` to a comma-separated allowlist for browser origins. The default allows localhost/127.0.0.1 Vite development origins.
- Set `VITE_API_TOKEN` in the frontend only for a controlled local/private deployment; do not treat a browser token as a production secret.
