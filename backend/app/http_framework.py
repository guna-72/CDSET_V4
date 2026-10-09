from __future__ import annotations
"""
A minimal routing layer over http.server — stands in for FastAPI, which
can't be installed in this network-isolated sandbox. Supports path
params ("/projects/{id}"), JSON request/response bodies, and per-request
error handling that never leaks a raw traceback to the client.
"""
import json
import re
import traceback
import os
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from app.config import (MAX_HTTP_REQUEST_BYTES, MAX_JSON_BODY_BYTES, CORS_ALLOWED_ORIGINS,
                        API_AUTH_TOKEN, RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX_POSTS)


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class _Headers(dict):
    """Case-insensitive header mapping. HTTP header names are case-insensitive,
    but ``dict(handler.headers)`` keeps whatever casing the client sent, so a
    lookup such as ``headers.get("Authorization")`` silently missed clients that
    send ``authorization`` (HTTP/2 proxies, curl -H, many HTTP libraries)."""

    def __init__(self, items=None):
        super().__init__()
        for k, v in dict(items or {}).items():
            super().__setitem__(str(k).lower(), v)

    def __getitem__(self, key):
        return super().__getitem__(str(key).lower())

    def __setitem__(self, key, value):
        super().__setitem__(str(key).lower(), value)

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class Request:
    def __init__(self, method, path, params, query, headers, body):
        self.method = method
        self.path = path
        self.params = params      # path params, e.g. {"id": "..."}
        self.query = query        # dict of lists
        self.headers = _Headers(headers)
        self.body = body          # raw bytes

    def json(self):
        if not self.body:
            return {}
        try:
            data = json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPError(400, f"invalid JSON body: {e}")
        # Every route treats the body as an object; a bare list/string/number
        # used to reach ``.get`` and surface as a 500.
        if not isinstance(data, dict):
            raise HTTPError(400, "JSON body must be an object")
        return data


class Router:
    def __init__(self):
        self._routes = []  # (method, compiled_regex, param_names, handler)

    def route(self, method: str, path_pattern: str):
        param_names = re.findall(r"{(\w+)}", path_pattern)
        regex_str = re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", path_pattern)
        compiled = re.compile(f"^{regex_str}$")

        def decorator(fn):
            self._routes.append((method.upper(), compiled, param_names, fn))
            return fn
        return decorator

    def get(self, path):
        return self.route("GET", path)

    def post(self, path):
        return self.route("POST", path)

    def delete(self, path):
        return self.route("DELETE", path)

    def put(self, path):
        return self.route("PUT", path)

    def match(self, method, path):
        for m, regex, _names, fn in self._routes:
            if m != method:
                continue
            mobj = regex.match(path)
            if mobj:
                return fn, mobj.groupdict()
        return None, None


def make_server(router: Router, host="127.0.0.1", port=8080):
    rate_state = defaultdict(deque)
    rate_lock = __import__("threading").Lock()

    def origin_allowed(origin):
        if not origin:
            return True
        if "*" in CORS_ALLOWED_ORIGINS:
            return True
        return origin in CORS_ALLOWED_ORIGINS

    def client_key(handler):
        return handler.client_address[0] if handler.client_address else "unknown"

    def post_allowed(handler):
        now = time.monotonic()
        key = client_key(handler)
        with rate_lock:
            q = rate_state[key]
            while q and now - q[0] > RATE_LIMIT_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= RATE_LIMIT_MAX_POSTS:
                return False
            q.append(now)
            return True

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # quiet; audit log covers what matters

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            fn, params = router.match(method, parsed.path)
            origin = self.headers.get("Origin", "")
            if method in ("POST", "PUT"):
                if not post_allowed(self):
                    return self._json(429, {"error": "rate limit exceeded; retry later"})
            if method in ("POST", "PUT", "GET", "DELETE") and origin and not origin_allowed(origin):
                return self._json(403, {"error": "origin not allowed"})
            if fn is None:
                return self._json(404, {"error": "not found", "path": parsed.path})
            query = parse_qs(parsed.query)
            raw_length = self.headers.get("Content-Length", "0") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                return self._json(400, {"error": "invalid Content-Length"})
            if length < 0 or length > MAX_HTTP_REQUEST_BYTES:
                return self._json(413, {"error": "request body too large"})
            if method in ("POST", "PUT") and parsed.path not in ("/projects/upload",) and length > MAX_JSON_BODY_BYTES:
                return self._json(413, {"error": "JSON request body too large"})
            body = self.rfile.read(length) if length else b""
            req = Request(method, parsed.path, params, query, dict(self.headers), body)
            try:
                if parsed.path not in ("/health", "/capabilities"):
                    from app.auth import authenticate_request
                    authenticate_request(req, public=False)
                else:
                    req.user_uid = None
                    req.actor = "anonymous"
                status, payload = fn(req)
                self._json(status, payload)
            except HTTPError as e:
                self._json(e.status, {"error": e.message})
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                # Client dropped the connection mid-request; nothing to do.
                pass
            except Exception as e:
                # Never leak a raw traceback to the client; log it server-side only.
                traceback.print_exc()
                self._json(500, {"error": "internal server error"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_OPTIONS(self):
            # CORS preflight — the browser sends this before any POST
            # with a JSON body (or a custom header, like the upload
            # endpoint's X-Project-Name) when the frontend is served
            # from a different origin than this API. Without this, every
            # such request from a real browser fails before it even
            # reaches the route handler.
            origin = self.headers.get("Origin", "")
            if origin and not origin_allowed(origin):
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(204)
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Project-Name, Authorization")
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _json(self, status, payload):
            body = json.dumps(payload, default=str).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                origin = self.headers.get("Origin", "")
                if origin and origin_allowed(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                # Client dropped the connection before we finished writing
                # the response (common on Windows after 401s). Silently ignore.
                pass

    return ThreadingHTTPServer((host, port), Handler)
