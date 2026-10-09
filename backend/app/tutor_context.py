from __future__ import annotations
"""
Tutor code context.

For one experiment run this module answers three questions the AI Tutor needs:

  1. WHICH project / file was tested and WHAT error was injected?
  2. WHERE in the user's own source code does that error land (file + lines)?
  3. WHAT would a resilient version of exactly those lines look like?

Everything is derived from the real imported project files and the real run
record. The fix is produced by a deterministic, rule-based patcher that rewrites
the located lines (wrap in try/except, add a size guard, fail fast on a missing
env var, ...). If AI diagnosis is enabled the LLM may refine the fix, but the
rule-based result is always available and is what runs when no LLM is set up.

Nothing here executes project code and nothing writes to the project: the fix is
only ever *shown* to the learner.
"""
import json
import os
import pathlib
import re
import sys

from app import db, llm_providers

# Outcomes where the project did NOT handle the injected error correctly.
PROBLEM_OUTCOMES = {"APPLICATION_FAILURE", "CRASHED", "WEAK_HANDLING", "ANOMALY"}

_IGNORED_DIRS = {"node_modules", "__pycache__", ".venv", "venv", ".git", "dist", "build",
                 ".next", "coverage", "site-packages"}
_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".java": "java", ".go": "go", ".php": "php", ".rb": "ruby",
    ".rs": "rust", ".kt": "kotlin", ".c": "c", ".cpp": "cpp",
}
_MAX_FILES = 400
_MAX_FILE_BYTES = 300 * 1024

FAULT_LABEL = {
    "malformed_request": "Invalid request body",
    "empty_input": "Empty request body",
    "oversized_payload": "Oversized request body",
    "boundary_input": "Unexpected / boundary values",
    "invalid_content_type": "Wrong Content-Type header",
    "wrong_http_method": "Wrong request method",
    "null_json_body": "Empty JSON value (null) as body",
    "special_characters": "Special characters and emoji in input",
    "long_url": "Very long URL",
    "unknown_route": "Page that does not exist",
    "deeply_nested_json": "Deeply nested JSON body",
    "request_burst": "Burst of concurrent requests",
    "connection_refused": "Downstream connection refused",
    "slow_response": "Slow response / added latency",
    "process_kill": "Service killed without warning",
    "process_kill_recovery": "Service killed, then restarted",
    "missing_env_var": "Required environment variable removed",
    "missing_file": "Required file removed",
    "permission_denied": "File permission denied",
    "db_connection_refused": "Database connection refused",
}


def _injected_description(fault: str, params: dict) -> str:
    paths = ", ".join((params or {}).get("candidate_paths") or []) or "the service's endpoints"
    var = (params or {}).get("env_var") or "a required variable"
    rel = (params or {}).get("relative_path") or "a required file"
    return {
        "malformed_request": f"A request whose body is not valid JSON was sent to {paths}.",
        "empty_input": f"A request with an empty body was sent to {paths}.",
        "oversized_payload": f"A request with a very large body (bounded, safe size) was sent to {paths}.",
        "boundary_input": f"A request with unusual values and wrong data types was sent to {paths}.",
        "invalid_content_type": f"A request with a mismatched Content-Type header was sent to {paths}.",
        "wrong_http_method": f"A request using an unsupported method (PUT) was sent to {paths}.",
        "null_json_body": f"A request whose body is the JSON value null (not an object) was sent to {paths}.",
        "special_characters": f"A request full of quotes, emoji, unicode and HTML/SQL-looking text was sent to {paths}.",
        "long_url": f"A request with a very long URL (about 8 KB) was sent to {paths}.",
        "unknown_route": "A request for a page that does not exist was sent to the service.",
        "deeply_nested_json": f"A request with extremely deeply nested JSON was sent to {paths}.",
        "request_burst": f"Many concurrent requests were sent to {paths} at once.",
        "connection_refused": "A dependency the service calls was made unreachable (connection refused).",
        "slow_response": f"Extra latency was applied while calling {paths}, to see whether callers time out cleanly.",
        "process_kill": "The service process was terminated abruptly (SIGKILL) in the isolated copy.",
        "process_kill_recovery": "The service process was terminated, then a restart supervisor was used to see if it recovers.",
        "missing_env_var": f"The environment variable {var} was removed before the service started.",
        "missing_file": f"The file {rel} was deleted from the isolated copy before the service started.",
        "permission_denied": f"Read permission on {rel} was removed in the isolated copy.",
        "db_connection_refused": "The database endpoint was made unreachable (connection refused).",
    }.get(fault, "A controlled fault was injected into the isolated project copy.")


# ------------------------------------------------------------------ locating code

_SERVER_START = [r"ThreadingHTTPServer\(", r"HTTPServer\(", r"app\.run\(", r"uvicorn\.run\(",
                 r"\.listen\(", r"serve_forever\("]
_OUTBOUND_CALL = [r"requests\.(?:get|post|put|delete|request)\(", r"urlopen\(", r"http\.client\.",
                  r"\bfetch\(", r"axios\.", r"http\.request\(", r"https\.request\(",
                  r"create_connection\(", r"socket\.connect"]
_BODY_PARSE = [r"json\.loads\(", r"\.get_json\(", r"JSON\.parse\(", r"json\.NewDecoder",
               r"json_decode\(", r"request\.json\b"]

_PATTERNS = {
    "malformed_request": _BODY_PARSE,
    "empty_input": _BODY_PARSE + [r"rfile\.read\("],
    "oversized_payload": [r"headers(?:\.get\(|\[)\s*['\"][Cc]ontent-[Ll]ength", r"content_length",
                          r"rfile\.read\(", r"get_data\(", r"request\.data\b",
                          r"req\.on\(\s*['\"]data['\"]", r"express\.json\("],
    "boundary_input": _BODY_PARSE + [r"\bint\(", r"\bfloat\(", r"parseInt\(", r"req\.body\b"],
    "invalid_content_type": _BODY_PARSE + [r"Content-Type", r"content-type", r"express\.json\("],
    "wrong_http_method": [r"def do_(?:GET|POST)", r"methods\s*=", r"app\.(?:get|post)\(", r"@app\.route"],
    "null_json_body": _BODY_PARSE,
    "special_characters": _BODY_PARSE + [r"execute\(", r"\.format\(", r"f['\"]"],
    "long_url": _SERVER_START,
    "unknown_route": [r"def do_GET", r"@app\.route", r"app\.get\(", r"\.route\("],
    "deeply_nested_json": _BODY_PARSE,
    "request_burst": _SERVER_START,
    "connection_refused": _OUTBOUND_CALL,
    "slow_response": _OUTBOUND_CALL + [r"time\.sleep\(", r"setTimeout\("],
    "process_kill": _SERVER_START,
    "process_kill_recovery": _SERVER_START,
    "missing_env_var": [r"os\.environ", r"os\.getenv\(", r"process\.env\."],
    "missing_file": [r"\bopen\(", r"readFileSync\(", r"fs\.readFile\(", r"read_text\(", r"\.load\("],
    "permission_denied": [r"\bopen\(", r"readFileSync\(", r"fs\.readFile\(", r"read_text\("],
    "db_connection_refused": [r"sqlite3\.connect\(", r"psycopg2?\.connect\(", r"pymysql\.connect\(",
                              r"mysql\.connector\.connect\(", r"MongoClient\(", r"create_engine\(",
                              r"createConnection\(", r"createPool\(", r"new Pool\(",
                              r"redis\.(?:Redis|from_url)\(", r"createClient\("],
}

_PREFERRED_NAMES = ("app", "main", "server", "index", "api", "run")


def _project_files(base: pathlib.Path):
    out = []
    for p in sorted(base.rglob("*")):
        if len(out) >= _MAX_FILES:
            break
        if not p.is_file() or p.suffix.lower() not in _LANG_BY_EXT:
            continue
        rel_parts = p.relative_to(base).parts
        if any(part in _IGNORED_DIRS or part.startswith(".chaos_") for part in rel_parts):
            continue
        low = p.name.lower()
        if low.startswith("test_") or low.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts")):
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out.append((p.relative_to(base).as_posix(), _LANG_BY_EXT[p.suffix.lower()], text))
    return out


def _entry_file(project_id: str):
    try:
        rows = db.get_many("project_analysis", "project_id = ?", (project_id,))
        if rows:
            ep = db.loads(rows[0].get("entrypoint_json"))
            if isinstance(ep, dict):
                return ep.get("file") or ep.get("path") or ep.get("entry")
            if isinstance(ep, str):
                return ep
    except Exception:
        pass
    return None


def _find_line(fault: str, params: dict, files, entry):
    """Return (rel, language, text, line_index) of the best match, or None."""
    params = params or {}
    var = params.get("env_var")
    rel_path = params.get("relative_path")
    candidates = []  # (score, rel, lang, text, idx)

    def add(score, rel, lang, text, idx):
        name = pathlib.PurePosixPath(rel).stem.lower()
        if entry and rel == entry:
            score -= 0.5
        elif name in _PREFERRED_NAMES:
            score -= 0.25
        candidates.append((score, rel, lang, text, idx))

    for rel, lang, text in files:
        lines = _mask_non_code(lang, text)
        if fault == "missing_env_var" and var:
            for i, line in enumerate(lines):
                if var in line and re.search(r"environ|getenv|process\.env", line):
                    add(0, rel, lang, text, i)
        elif fault in ("missing_file", "permission_denied") and rel_path:
            base = os.path.basename(rel_path)
            for i, line in enumerate(lines):
                if base not in line:
                    continue
                m = re.match(r"\s*(?:const|let|var)?\s*([A-Za-z_]\w*)\s*=", line)
                if m:  # a constant holding the path: find where it is actually opened
                    name = m.group(1)
                    for j, l2 in enumerate(lines):
                        if j != i and re.search(rf"\b{re.escape(name)}\b", l2) and \
                                any(re.search(p, l2) for p in _PATTERNS["missing_file"]):
                            add(0, rel, lang, text, j)
                if any(re.search(p, line) for p in _PATTERNS["missing_file"]):
                    add(0.1, rel, lang, text, i)
                else:
                    add(1, rel, lang, text, i)
        if not candidates or fault not in ("missing_env_var", "missing_file", "permission_denied"):
            for prio, pat in enumerate(_PATTERNS.get(fault, [])):
                rx = re.compile(pat)
                for i, line in enumerate(lines):
                    if not line.strip():
                        continue
                    if rx.search(line):
                        add(2 + prio, rel, lang, text, i)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[4]))
    _, rel, lang, text, idx = candidates[0]
    return rel, lang, text, idx


def _mask_non_code(lang: str, text: str):
    """Return the file's lines with comments and docstrings/block comments blanked out, so a
    word like `json.loads()` inside a docstring is never mistaken for a real call."""
    lines = text.splitlines()
    masked = list(lines)
    if lang == "python":
        import io
        import tokenize
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                (sr, sc), (er, ec) = tok.start, tok.end
                if tok.type == tokenize.COMMENT:
                    masked[sr - 1] = masked[sr - 1][:sc]
                elif tok.type == tokenize.STRING and (er > sr or tok.string[:3] in ('"""', "'''")
                                                      or lines[sr - 1].strip() == tok.string):
                    for r in range(sr, er + 1):
                        masked[r - 1] = ""
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return masked
    in_block = False
    for i, line in enumerate(lines):
        out, j, n = [], 0, len(line)
        quote = None
        while j < n:
            two = line[j:j + 2]
            if in_block:
                if two == "*/":
                    in_block, j = False, j + 2
                else:
                    j += 1
                continue
            ch = line[j]
            if quote:
                out.append(ch)
                if ch == "\\":
                    out.append(line[j + 1:j + 2])
                    j += 2
                    continue
                if ch == quote:
                    quote = None
                j += 1
                continue
            if two == "/*":
                in_block, j = True, j + 2
                continue
            if two == "//":
                break
            if ch in "\"'`":
                quote = ch
            out.append(ch)
            j += 1
        masked[i] = "".join(out)
    return masked


def _balance(s: str) -> int:
    return sum(s.count(c) for c in "([{") - sum(s.count(c) for c in ")]}")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _statement_end(lines, idx, lang) -> int:
    """Index of the last line of the statement starting at idx (inclusive)."""
    end, bal = idx, _balance(lines[idx])
    while bal > 0 and end + 1 < len(lines):
        end += 1
        bal += _balance(lines[end])
    if lang == "python" and lines[end].rstrip().endswith(":"):
        base = _indent(lines[idx])
        while end + 1 < len(lines) and (not lines[end + 1].strip() or _indent(lines[end + 1]) > base):
            end += 1
        while end > idx and not lines[end].strip():
            end -= 1
    return end


# ------------------------------------------------------------------ building the fix

def _style(lang: str, text: str) -> str:
    low = text.lower()
    if lang == "python":
        if "from flask" in low or "import flask" in low:
            return "flask"
        if "fastapi" in low:
            return "fastapi"
        if "basehttprequesthandler" in low:
            return "py-http-send-json" if "def _send_json" in text else "py-http"
        return "python"
    if lang in ("javascript", "typescript"):
        return "express" if re.search(r"require\(['\"]express['\"]\)|from ['\"]express['\"]", text) else "node-http"
    return lang


def _respond(style: str, status: int, msg: str, ind: str):
    m = msg.replace('"', "'")
    if style == "flask":
        return [f'{ind}return jsonify({{"error": "{m}"}}), {status}']
    if style == "fastapi":
        return [f'{ind}raise HTTPException(status_code={status}, detail="{m}")']
    if style == "py-http-send-json":
        return [f'{ind}return self._send_json({status}, {{"error": "{m}"}})']
    if style == "py-http":
        return [f"{ind}self.send_response({status})",
                f'{ind}self.send_header("Content-Type", "application/json")',
                f"{ind}self.end_headers()",
                f'{ind}self.wfile.write(b\'{{"error": "{m}"}}\')',
                f"{ind}return"]
    if style == "express":
        return [f'{ind}return res.status({status}).json({{ error: "{m}" }});']
    if style == "node-http":
        return [f"{ind}res.writeHead({status}, {{ 'Content-Type': 'application/json' }});",
                f'{ind}res.end(JSON.stringify({{ error: "{m}" }}));',
                f"{ind}return;"]
    return [f"{ind}# respond with HTTP {status}: {m}"]


def _fail_fast(lang: str, msg: str, ind: str):
    m = msg.replace('"', "'")
    if lang == "python":
        return [f'{ind}sys.stderr.write("Startup error: {m}\\n")', f"{ind}sys.exit(1)"]
    return [f'{ind}console.error("Startup error: {m}");', f"{ind}process.exit(1);"]


def _wrap_try(lang, lines, start, end, exc, handler_lines, warn_import=None):
    """Return replacement lines wrapping lines[start..end] in try/except (or try/catch)."""
    base = lines[start][: _indent(lines[start])]
    body = lines[start:end + 1]
    if lang == "python":
        out = [f"{base}try:"] + [("    " + l if l.strip() else l) for l in body]
        out += [f"{base}except {exc} as exc:"] + handler_lines
        return out
    # JavaScript: keep `const x = ...` visible after the try block
    m = re.match(r"^(\s*)(const|let|var)\s+(\w+)\s*=\s*(.*)$", body[0])
    out = []
    if m:
        out.append(f"{base}let {m.group(3)};")
        body = [f"{base}{m.group(3)} = {m.group(4)}"] + body[1:]
    out += [f"{base}try {{"] + [("  " + l if l.strip() else l) for l in body]
    out += [f"{base}}} catch (err) {{"] + handler_lines + [f"{base}}}"]
    return out


def _arg_of(call: str, line: str):
    m = re.search(rf"{call}\(\s*([A-Za-z_][\w.]*)\s*[,)]", line)
    return m.group(1) if m else None


def _build_fix(fault, params, lang, text, lines, idx):
    """Return dict(kind, title, explanation[], code_lines, start, end, extras[]) — never raises."""
    style = _style(lang, text)
    end = _statement_end(lines, idx, lang)
    line = lines[idx]
    ind = line[: _indent(line)]
    inner = ind + ("    " if lang == "python" else "  ")
    in_func = _indent(line) > 0
    py = lang == "python"
    js = lang in ("javascript", "typescript")
    extras, notes = [], []

    def respond(status, msg, level=None):
        return _respond(style, status, msg, level if level is not None else inner)

    def guard_before(cond_py, cond_js, status, msg):
        c = cond_py if py else cond_js
        head = f"{ind}if {c}:" if py else f"{ind}if ({c}) {{"
        block = [head] + _respond(style, status, msg, inner) + ([] if py else [f"{ind}}}"])
        return block

    replacement = None
    title = "Add explicit handling"

    if not (py or js):
        return None  # other languages: locator only, no auto-patch

    if fault in ("malformed_request", "boundary_input", "empty_input", "invalid_content_type",
                 "null_json_body", "deeply_nested_json", "special_characters"):
        exc_py = "(ValueError, TypeError)"
        handler = respond(400, "Request body must be valid JSON") if in_func else _fail_fast(lang, "invalid input", inner)
        assign = re.match(r"\s*(?:const|let|var)?\s*(\w+)\s*=", line)
        var = assign.group(1) if assign else None
        is_parse = any(re.search(p, line) for p in _BODY_PARSE)
        pre, post = [], []
        if fault == "empty_input":
            arg = _arg_of(r"json\.loads", line) or _arg_of(r"JSON\.parse", line)
            if arg:
                pre = guard_before(f"not {arg} or not {arg}.strip()", f"!{arg} || !String({arg}).trim()",
                                   400, "Request body must not be empty")
                title = "Reject an empty body with a 400"
            else:
                pre = guard_before("not request.get_data()", "!req.body", 400, "Request body must not be empty")
        if fault == "invalid_content_type":
            ct_py = 'self.headers.get("Content-Type", "")' if style.startswith("py-http") else 'request.headers.get("Content-Type", "")'
            ct_js = "String(req.headers['content-type'] || '')"
            pre = guard_before(f'"application/json" not in {ct_py}', f"!{ct_js}.includes('application/json')",
                               415, "Content-Type must be application/json")
            title = "Enforce the expected Content-Type (415)"
        if var and is_parse:
            post = guard_before(f"not isinstance({var}, dict)", f"{var} === null || typeof {var} !== 'object' || Array.isArray({var})",
                                400, "JSON body must be an object")
            for field, required in _used_fields(var, lines[end + 1:end + 26], lang):
                post += _field_guard(lang, var, field, required, guard_before)
        if is_parse:
            core = _wrap_try(lang, lines, idx, end, exc_py, handler)
            replacement = pre + core + post
            if fault in ("malformed_request", "boundary_input"):
                title = "Catch the parse error and return 400"
            notes += ["The parse call is wrapped so bad input becomes a clean 4xx instead of an unhandled exception.",
                      "The parsed value is checked to be an object, and each field the code reads is type-checked "
                      "(adjust the expected types to your real schema)."]
        else:
            replacement = pre + lines[idx:end + 1]
            notes += ["A guard rejects the bad request before the risky line runs."]
    elif fault == "oversized_payload":
        title = "Reject oversized bodies before reading them"
        extras.append("MAX_BODY_BYTES = 1_000_000  # 1 MB — add near the top of the file" if py
                      else "const MAX_BODY_BYTES = 1_000_000; // 1 MB — add near the top of the file")
        if re.search(r"headers(?:\.get\(|\[)\s*['\"][Cc]ontent-[Ll]ength", line) and (style.startswith("py-http")):
            v = re.match(r"\s*(\w+)\s*=", line)
            name = v.group(1) if v else "length"
            drain = [f"{inner}remaining = min({name}, 10 * MAX_BODY_BYTES)",
                     f"{inner}while remaining > 0:  # drain the upload so the client can actually read our 413 reply",
                     f"{inner}    chunk = self.rfile.read(min(remaining, 65536))",
                     f"{inner}    if not chunk:",
                     f"{inner}        break",
                     f"{inner}    remaining -= len(chunk)",
                     f"{inner}self.close_connection = True"]
            replacement = lines[idx:end + 1] + [f"{ind}if {name} > MAX_BODY_BYTES:"] + drain + \
                _respond(style, 413, "Request body too large", inner)
            notes += ["The declared Content-Length is checked before the body is read into memory.",
                      "The oversized upload is discarded in small chunks (bounded), so the client receives a clean 413 instead of a broken connection."]
        elif js and re.search(r"req\.on\(\s*['\"]data['\"]", line) and re.search(r"body\s*\+=", "\n".join(lines[idx:end + 1])):
            replacement = [f"{ind}let received = 0;",
                           f"{ind}req.on('data', (chunk) => {{",
                           f"{inner}received += chunk.length;",
                           f"{inner}if (received > MAX_BODY_BYTES) {{",
                           f"{inner}  res.writeHead(413, {{ 'Content-Type': 'application/json' }});",
                           f"{inner}  res.end(JSON.stringify({{ error: 'Request body too large' }}));",
                           f"{inner}  req.destroy();",
                           f"{inner}  return;",
                           f"{inner}}}",
                           f"{inner}body += chunk;",
                           f"{ind}}});"]
            notes += ["The stream is counted and cut off with a 413 once it goes past the size limit."]
        elif style == "flask":
            replacement = lines[idx:end + 1]
            extras.append('app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # Flask answers 413 automatically')
            notes += ["Flask enforces MAX_CONTENT_LENGTH and returns 413 for larger bodies."]
        else:
            replacement = lines[idx:end + 1]
            notes += ["Check the declared Content-Length against MAX_BODY_BYTES before reading the body, and return 413."]
    elif fault == "missing_env_var":
        var = (params or {}).get("env_var") or "REQUIRED_VAR"
        title = "Fail fast with a clear message when the variable is missing"
        m = re.match(r"^(\s*)(\w+)\s*=\s*.*$", line) if py else re.match(r"^(\s*)(?:const|let|var)\s+(\w+)\s*=\s*.*$", line)
        msg = f"required environment variable {var} is not set"
        if py:
            name = m.group(2) if m else var.lower()
            replacement = [f'{ind}{name} = os.environ.get("{var}")', f"{ind}if not {name}:"] + \
                          _fail_fast("python", msg, inner)
        else:
            name = m.group(2) if m else "value"
            replacement = [f"{ind}const {name} = process.env.{var};", f"{ind}if (!{name}) {{"] + \
                          _fail_fast("javascript", msg, inner) + [f"{ind}}}"]
        notes += ["The service refuses to start with one readable line instead of a stack trace or a half-configured state.",
                  "Alternative: define a documented default value if the variable is optional."]
    elif fault in ("missing_file", "permission_denied"):
        rel = (params or {}).get("relative_path") or "the required file"
        title = "Handle the file error and fail with an actionable message"
        msg = f"cannot read {rel} — check that it exists and is readable"
        handler = (_fail_fast(lang, msg, inner) if not in_func else respond(503, msg))
        exc = "(FileNotFoundError, PermissionError, OSError)"
        replacement = _wrap_try(lang, lines, idx, end, exc, handler)
        notes += ["The file access is wrapped, so a missing or unreadable file gives one clear message.",
                  "Alternative: fall back to built-in default data if the file is optional."]
    elif fault in ("db_connection_refused", "connection_refused", "slow_response"):
        title = "Add a timeout and handle the connection failure"
        new_line = line
        if py:
            if re.search(r"requests\.\w+\(", line) and "timeout" not in line:
                new_line = re.sub(r"\)(\s*)$", r", timeout=3)\1", line.rstrip(), count=1)
            elif re.search(r"urlopen\(", line) and "timeout" not in line:
                new_line = re.sub(r"\)(\s*)$", r", timeout=3)\1", line.rstrip(), count=1)
            elif re.search(r"connect\(", line) and "timeout" not in line and "sqlite3" not in line:
                new_line = re.sub(r"\)(\s*)$", r", connect_timeout=3)\1", line.rstrip(), count=1)
        else:
            if re.search(r"\bfetch\(", line) and "signal" not in line:
                new_line = re.sub(r"\)(\s*)([;,]?)\s*$", r", { signal: AbortSignal.timeout(3000) })\1\2", line.rstrip(), count=1)
        tmp = list(lines)
        tmp[idx] = new_line
        exc = "Exception" if fault == "db_connection_refused" else "OSError"
        handler = respond(503, "Dependency unavailable, please retry shortly") if in_func \
            else _fail_fast(lang, "dependency unavailable", inner)
        replacement = _wrap_try(lang, tmp, idx, end, exc, handler)
        notes += ["A short timeout stops the caller hanging.",
                  "The failure is caught and turned into a clear 503 (or a clean startup error) instead of a crash.",
                  "For flaky dependencies also add a few retries with exponential backoff."]
    elif fault == "request_burst":
        title = "Serve requests concurrently and bound the load"
        if "HTTPServer(" in line and "Threading" not in line:
            replacement = [line.replace("HTTPServer(", "ThreadingHTTPServer(", 1)] + lines[idx + 1:end + 1]
            extras.append("from http.server import ThreadingHTTPServer  # replaces HTTPServer in the import")
            notes += ["ThreadingHTTPServer handles each request in its own thread so a burst does not queue behind one slow request."]
        else:
            replacement = lines[idx:end + 1]
            notes += ["Put a concurrency limit or rate limiter in front of this entry point and return 429 when it is exceeded."]
    elif fault in ("process_kill", "process_kill_recovery"):
        title = "Run the service under a restart supervisor"
        replacement = lines[idx:end + 1]
        extras.append("# docker-compose.yml\nservices:\n  app:\n    build: .\n    restart: unless-stopped\n"
                      "    healthcheck:\n      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/health\"]\n      interval: 10s\n      retries: 3")
        notes += ["The code itself cannot survive SIGKILL — the fix is outside it: let Docker, systemd or a process manager restart the service.",
                  "Add a /health endpoint so the supervisor can tell when the service is really back."]
    else:
        return None

    return {
        "title": title, "notes": notes, "extras": extras,
        "start": idx, "end": end, "replacement": replacement, "style": style,
    }


_NUM_HINT = re.compile(r"(^|_)(id|count|age|price|qty|quantity|amount|limit|page|size|total|score|rating|year)$|Id$|Count$", re.I)
_BOOL_HINT = re.compile(r"^(is_?\w+|done|active|enabled|completed|verified|deleted|flag)$", re.I)
_JS_SKIP = {"hasOwnProperty", "toString", "length", "constructor", "valueOf"}


def _used_fields(var: str, following: list, lang: str):
    """(field, required) pairs read from the parsed body in the lines right after the parse."""
    seen, out = set(), []
    code = "\n".join(following)
    if lang == "python":
        for m in re.finditer(rf"\b{re.escape(var)}\[\s*['\"](\w+)['\"]\s*\]", code):
            if m.group(1) not in seen:
                seen.add(m.group(1)); out.append((m.group(1), True))
        for m in re.finditer(rf"\b{re.escape(var)}\.get\(\s*['\"](\w+)['\"]", code):
            if m.group(1) not in seen:
                seen.add(m.group(1)); out.append((m.group(1), False))
    else:
        for m in re.finditer(rf"\b{re.escape(var)}\.(\w+)", code):
            f = m.group(1)
            if f not in seen and f not in _JS_SKIP:
                seen.add(f); out.append((f, True))
        for m in re.finditer(rf"\b{re.escape(var)}\[\s*['\"](\w+)['\"]\s*\]", code):
            if m.group(1) not in seen:
                seen.add(m.group(1)); out.append((m.group(1), True))
    return out[:6]


def _field_guard(lang, var, field, required, guard_before):
    """One validation block for a body field. Type is inferred from the field name (string by default)."""
    if _BOOL_HINT.match(field):
        kind, label = "bool", "true or false"
    elif _NUM_HINT.search(field):
        kind, label = "num", "a number"
    else:
        kind, label = "str", "a non-empty string"
    msg = f"'{field}' must be {label}"
    if lang == "python":
        val = f'{var}.get("{field}")'
        ok = {"bool": f"isinstance({val}, bool)",
              "num": f"isinstance({val}, (int, float)) and not isinstance({val}, bool)",
              "str": f"isinstance({val}, str) and {val}.strip() != \"\""}[kind]
        cond = f"not ({ok})" if required else f'"{field}" in {var} and not ({ok})'
        return guard_before(cond, cond, 400, msg)
    val = f"{var}.{field}"
    ok = {"bool": f"typeof {val} === 'boolean'",
          "num": f"typeof {val} === 'number' && Number.isFinite({val})",
          "str": f"typeof {val} === 'string' && {val}.trim() !== ''"}[kind]
    cond = f"!({ok})" if required else f"{val} !== undefined && !({ok})"
    return guard_before(cond, cond, 400, msg)


def _number(lines, first_no):
    return "\n".join(f"{first_no + i:>4} | {l}" for i, l in enumerate(lines))


def _imports_needed(fault, lang, text, replacement) -> list:
    if lang != "python" or not replacement:
        return []
    joined = "\n".join(replacement)
    need = []
    if "sys." in joined and not re.search(r"^\s*import sys\b", text, re.M):
        need.append("import sys")
    if "jsonify(" in joined and "jsonify" not in text.split("def ")[0]:
        need.append("from flask import jsonify")
    if "HTTPException" in joined and "HTTPException" not in text:
        need.append("from fastapi import HTTPException")
    return need


# ------------------------------------------------------------------ public API

def build_context(run: dict, use_llm: bool = True) -> dict:
    project = db.get_one("projects", run["project_id"]) or {}
    exp = db.get_one("experiments", run["experiment_id"]) or {}
    params = db.loads(exp.get("parameters_json")) or {}
    fault = exp.get("fault_type") or ""
    outcome = run.get("outcome")
    status = run.get("status")
    diag_rows = db.get_many("diagnoses", "run_id = ?", (run["id"],))
    diag = diag_rows[0] if diag_rows else {}

    ctx = {
        "run_id": run["id"],
        "status": status,
        "outcome": outcome,
        "project": {"id": project.get("id"), "name": project.get("name"),
                    "original_filename": project.get("original_filename")},
        "experiment": {"id": exp.get("id"), "name": exp.get("name"), "fault_type": fault,
                       "category": exp.get("category"), "target": exp.get("target"),
                       "parameters": params},
        "injected": {"label": FAULT_LABEL.get(fault, exp.get("name") or fault),
                     "description": _injected_description(fault, params)},
        "tutor_needed": bool(status == "COMPLETED" and outcome in PROBLEM_OUTCOMES),
        "handled_correctly": bool(status == "COMPLETED" and outcome in ("PASSED", "RECOVERED")),
        "diagnosis": {"failure": diag.get("failure"), "root_cause": diag.get("root_cause"),
                      "impact": diag.get("impact"), "recommended_fix": diag.get("recommended_fix"),
                      "resilience_pattern": diag.get("resilience_pattern"),
                      "evidence": db.loads(diag.get("evidence_json")) if diag else None},
        "code": None,
        "fix": None,
    }
    if not ctx["tutor_needed"] and not ctx["handled_correctly"]:
        return ctx

    storage = project.get("storage_path")
    if not storage or not os.path.isdir(storage):
        return ctx
    try:
        base = pathlib.Path(storage).resolve()
        files = _project_files(base)
        found = _find_line(fault, params, files, _entry_file(project.get("id")))
    except Exception as e:  # never let code lookup break the tutor
        print(f"[tutor_context] code lookup failed: {e}", file=sys.stderr)
        return ctx
    if not found:
        return ctx

    rel, lang, text, idx = found
    lines = text.splitlines()
    end = _statement_end(lines, idx, lang)
    win_start = max(0, idx - 4)
    win_end = min(len(lines) - 1, end + 4)
    ctx["code"] = {
        "file": rel, "language": lang,
        "line": idx + 1, "start_line": win_start + 1, "end_line": win_end + 1,
        "snippet": _number(lines[win_start:win_end + 1], win_start + 1),
        "raw_snippet": "\n".join(lines[win_start:win_end + 1]),
    }

    if not ctx["tutor_needed"]:
        return ctx

    try:
        fix = _build_fix(fault, params, lang, text, lines, idx)
    except Exception as e:
        print(f"[tutor_context] fix generation failed: {e}", file=sys.stderr)
        fix = None
    if fix and fix.get("replacement"):
        new_window = lines[win_start:fix["start"]] + fix["replacement"] + lines[fix["end"] + 1:win_end + 1]
        ctx["fix"] = {
            "title": fix["title"], "notes": fix["notes"], "extras": fix["extras"],
            "imports": _imports_needed(fault, lang, text, fix["replacement"]),
            "file": rel, "language": lang,
            "code": "\n".join(new_window), "method": "rule_based",
        }
    elif fix:
        ctx["fix"] = {"title": fix["title"], "notes": fix["notes"], "extras": fix["extras"],
                      "imports": [], "file": rel, "language": lang, "code": None, "method": "rule_based"}
    if use_llm and ctx["fix"] is not None and llm_providers.diagnosis_enabled():
        try:
            _refine_with_llm(ctx)
        except Exception as e:  # silent fallback, same policy as diagnosis.py
            print(f"[tutor_context] LLM refinement failed, keeping rule-based fix: {e}", file=sys.stderr)
    return ctx


def _refine_with_llm(ctx: dict) -> None:
    payload = json.dumps({
        "injected_fault": ctx["injected"], "outcome": ctx["outcome"], "file": ctx["code"]["file"],
        "language": ctx["code"]["language"], "code": ctx["code"]["raw_snippet"],
        "diagnosis": ctx["diagnosis"], "rule_based_fix": ctx["fix"].get("code"),
    }, default=str)[:60 * 1024]
    system_prompt = (
        "You are the AI Tutor of a chaos-engineering learning tool. Given the learner's own code "
        "snippet, the fault that was injected and what went wrong, return ONLY a JSON object with "
        "keys \"explanation\" (2-4 sentences tying the failure to specific lines of THEIR code) and "
        "\"fixed_code\" (the same snippet rewritten so it handles the fault; keep the same language, "
        "names and style; no markdown fences). Do not invent files or functions that are not in the snippet."
    )
    parsed = llm_providers.diagnose_with_llm(system_prompt, payload)
    code = parsed.get("fixed_code")
    if isinstance(code, str) and code.strip():
        ctx["fix"]["code"] = code.strip("\n")
        ctx["fix"]["method"] = "llm"
    if isinstance(parsed.get("explanation"), str) and parsed["explanation"].strip():
        ctx["fix"]["llm_explanation"] = parsed["explanation"].strip()


def summarize_for_prompt(ctx: dict | None) -> dict:
    """Compact, safe subset of the context used to ground /tutor/{id}/ask answers."""
    if not ctx:
        return {}
    out = {
        "project": (ctx.get("project") or {}).get("name"),
        "injected_fault": (ctx.get("injected") or {}).get("description"),
        "fault_label": (ctx.get("injected") or {}).get("label"),
        "outcome": ctx.get("outcome"),
        "handled_correctly": ctx.get("handled_correctly"),
    }
    code = ctx.get("code")
    if code:
        out["source_file"] = code["file"]
        out["source_line"] = code["line"]
        out["source_snippet"] = code["raw_snippet"]
    fix = ctx.get("fix")
    if fix:
        out["suggested_fix_title"] = fix["title"]
        out["suggested_fix_code"] = fix.get("code")
        out["suggested_fix_notes"] = fix.get("notes")
    return out
