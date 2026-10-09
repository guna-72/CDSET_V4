from __future__ import annotations
"""
Invoked only via `nsenter --net=... -- python3 _netns_wait_ready.py <port> <timeout>`
from app/sandbox.py. Fixed, harness-authored script — no project or
AI-generated content ever reaches this file's contents, only numeric
argv parameters. Exits 0 if the port becomes connectable before the
deadline, 1 otherwise.
"""
import socket
import sys
import time


def main():
    port = int(sys.argv[1])
    timeout = float(sys.argv[2])
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                print("READY")
                sys.exit(0)
        except OSError:
            time.sleep(0.2)
    print("NOT_READY")
    sys.exit(1)


if __name__ == "__main__":
    main()
