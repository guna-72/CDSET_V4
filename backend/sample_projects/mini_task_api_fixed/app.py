"""
Mini Task API — FIXED version, used to prove Chaos Tutor is actually
observing real runtime behavior (not fabricating results). Both bugs
present in the original mini_task_api sample are patched here:
  1. Startup: missing seed.json is now handled with a clear error
     instead of an unhandled crash.
  2. POST /tasks: malformed/empty JSON body now returns a handled
     400 instead of crashing the request thread.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8765"))
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seed.json")

# FIX #1: handle a missing/invalid seed file with a clear, controlled exit
# instead of an unhandled exception.
try:
    with open(SEED_PATH) as f:
        TASKS = {t["id"]: t for t in json.load(f)}
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"FATAL: could not load seed data from {SEED_PATH}: {e}", file=sys.stderr, flush=True)
    sys.exit(1)

_next_id = max(TASKS.keys(), default=0) + 1


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send_json(200, {"status": "ok"})

        if parsed.path == "/tasks":
            return self._send_json(200, {"tasks": list(TASKS.values())})

        if parsed.path.startswith("/tasks/"):
            try:
                task_id = int(parsed.path.rsplit("/", 1)[-1])
            except ValueError:
                return self._send_json(400, {"error": "task id must be an integer"})
            task = TASKS.get(task_id)
            if not task:
                return self._send_json(404, {"error": "task not found"})
            return self._send_json(200, task)

        if parsed.path == "/slow":
            qs = parse_qs(parsed.query)
            delay = float(qs.get("delay", ["1"])[0])
            delay = min(delay, 30)
            time.sleep(delay)
            return self._send_json(200, {"slept": delay})

        return self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/tasks":
            return self._send_json(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        # FIX #2: malformed/empty JSON body (or a missing "title" field)
        # is now caught and returns a clean 400 instead of crashing.
        try:
            data = json.loads(raw)
            title = data["title"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._send_json(400, {"error": "request body must be JSON with a 'title' field"})

        global _next_id
        task = {"id": _next_id, "title": title, "done": False}
        TASKS[_next_id] = task
        _next_id += 1
        return self._send_json(201, task)


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"mini-task-api (fixed) listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
