"""
Mini Task API — a deliberately small, deliberately imperfect example
service used as the "at least one real supported project" for Chaos
Tutor's MVP (spec section 4/50). Pure Python standard library — no pip
install required, so it runs unmodified in a network-isolated sandbox.

Endpoints:
  GET  /health              -> {"status": "ok"}
  GET  /tasks                -> list all tasks
  POST /tasks                -> create a task, body: {"title": "..."}
  GET  /tasks/<id>            -> fetch one task, 404 if missing
  GET  /slow?delay=<seconds>  -> intentionally slow, for timeout experiments

Two realistic, UNFIXED bugs are left in on purpose so the chaos engine has
real failures to discover — this is not a strawman:
  1. Startup reads data/seed.json with a bare open() and no error
     handling -> the process crashes with an unhandled FileNotFoundError
     if that file is missing (a classic "works on my machine" bug).
  2. POST /tasks parses the request body with json.loads() and no
     try/except -> a malformed body crashes the request handler thread
     with an unhandled exception instead of returning 400.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8765"))
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seed.json")

# BUG #1 (intentional): no try/except around this. Missing file = crash.
with open(SEED_PATH) as f:
    TASKS = {t["id"]: t for t in json.load(f)}

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

        # BUG #2 (intentional): no try/except. Malformed/empty JSON body
        # raises inside the handler thread -> connection reset, no clean
        # 400 response, no client-visible explanation.
        data = json.loads(raw)
        title = data["title"]

        global _next_id
        task = {"id": _next_id, "title": title, "done": False}
        TASKS[_next_id] = task
        _next_id += 1
        return self._send_json(201, task)


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"mini-task-api listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
