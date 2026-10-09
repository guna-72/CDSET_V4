from __future__ import annotations
"""
Invoked only via `nsenter --net=... -- python3 _netns_http_client.py ...`
from app/sandbox.py. Fixed, harness-authored script. All dynamic values
(port, path, method, timeout, headers) arrive as argv/stdin data, never
interpolated into code — this file's source never changes based on
project content or AI output.

argv: port path method timeout has_body headers_json
body (if has_body == "1") is read from stdin.
Prints one JSON object to stdout: {"ok", "status"|"error", "body", "latency_ms"}
"""
import json
import sys
import time
import urllib.error
import urllib.request


def main():
    port = int(sys.argv[1])
    path = sys.argv[2]
    method = sys.argv[3]
    timeout = float(sys.argv[4])
    has_body = sys.argv[5] == "1"
    headers = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
    data = sys.stdin.buffer.read() if has_body else None

    url = f"http://127.0.0.1:{port}{path}"
    start = time.time()
    try:
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(65536)
            print(json.dumps({
                "ok": True, "status": r.status,
                "body": body.decode("utf-8", "ignore")[:2000],
                "latency_ms": round((time.time() - start) * 1000, 1),
            }))
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        print(json.dumps({
            "ok": True, "status": e.code,
            "body": body[:2000].decode("utf-8", "ignore"),
            "latency_ms": round((time.time() - start) * 1000, 1),
        }))
    except Exception as e:
        print(json.dumps({
            "ok": False, "error": f"{type(e).__name__}: {e}",
            "latency_ms": round((time.time() - start) * 1000, 1),
        }))


if __name__ == "__main__":
    main()
