from __future__ import annotations
"""
Recovery Engine (spec section 24, P1 — first strategy implemented here).

Of the strategies the spec lists (timeout handling, bounded retries,
exponential backoff, fallback, circuit breaker, graceful degradation,
restart, failover, validation, error handling), "restart" is the one
directly testable without the sample project needing any orchestration
code of its own: SupervisedService wraps a sandboxed process with a real
monitor thread that restarts it (same workspace, same argv/env/port) if
it dies, up to a bounded number of times. This genuinely restarts a real
process in a real sandbox — it doesn't simulate recovery.

Never modifies the original source; every restart reuses the same
already-isolated sandbox workspace made by app.sandbox.make_workspace.
"""
import threading
import time

from app import sandbox

DEFAULT_MAX_RESTARTS = 3
DEFAULT_POLL_INTERVAL = 0.25


class SupervisedService:
    def __init__(self, argv, cwd, extra_env=None,
                 max_restarts=DEFAULT_MAX_RESTARTS, poll_interval=DEFAULT_POLL_INTERVAL):
        self.argv = argv
        self.cwd = cwd
        self.extra_env = extra_env
        self.max_restarts = max_restarts
        self.poll_interval = poll_interval
        self.restart_count = 0
        self.restart_events = []  # [{"attempt": n, "restarted": bool, "recovered_after_s": float|None, "reason": str|None}]
        self._lock = threading.Lock()
        self._stopped = False
        self.handle = sandbox.start_service(argv, cwd=cwd, extra_env=extra_env)
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()

    def _monitor(self):
        while True:
            time.sleep(self.poll_interval)
            with self._lock:
                if self._stopped:
                    return
                handle = self.handle
                if sandbox.service_is_alive(handle):
                    continue
                died_at = time.time()
                if self.restart_count >= self.max_restarts:
                    self.restart_events.append({
                        "attempt": self.restart_count + 1, "restarted": False,
                        "recovered_after_s": None, "reason": "max_restarts exceeded",
                    })
                    return
                self.restart_count += 1
                new_handle = sandbox.start_service(self.argv, cwd=self.cwd, extra_env=self.extra_env)
                self.handle = new_handle
                self.restart_events.append({
                    "attempt": self.restart_count, "restarted": True,
                    "recovered_after_s": round(time.time() - died_at, 3), "reason": None,
                })

    def current_handle(self):
        with self._lock:
            return self.handle

    def wait_for_new_handle(self, old_handle, timeout: float, cancel_check=None) -> "sandbox.ServiceHandle | None":
        """Blocks until the supervisor has installed a handle different
        from old_handle (i.e. a restart happened), or timeout elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel_check and cancel_check():
                return None
            h = self.current_handle()
            if h is not old_handle:
                return h
            time.sleep(0.05)
        return None

    def stop(self):
        with self._lock:
            self._stopped = True
            handle = self.handle
        sandbox.stop_service(handle)
