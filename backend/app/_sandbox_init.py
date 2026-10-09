from __future__ import annotations
"""
Runs as root, ALREADY INSIDE a fresh network+mount namespace (the parent
`unshare --net --mount` call put us here before exec'ing this script).
Responsible for everything that must happen before we drop root:
  1. bring the new namespace's loopback interface up (it starts down —
     without this, nothing, not even our own harness via nsenter, could
     reach the sandboxed service on 127.0.0.1)
  2. apply resource limits
  3. drop privileges to the unprivileged sandbox uid/gid
  4. exec the real target argv (replaces this process image; same pid)

Invoked only by app/sandbox.py — never called directly on user input.
argv: uid gid cpu_seconds mem_bytes max_procs skip_as <real argv...>
skip_as: "1" to skip the RLIMIT_AS (virtual address space) limit — V8
(Node.js) reserves several hundred MB to low-GB of virtual address space
upfront for its CodeRange/heap regardless of actual usage, which is a
well-documented incompatibility between V8 and RLIMIT_AS (unlike
CPython, where RLIMIT_AS correctly tracks real allocations). Real memory
safety for Node targets instead comes from the `--max-old-space-size`
flag app/sandbox.py adds to the node invocation itself (a V8-level heap
cap) plus RLIMIT_CPU/RLIMIT_NPROC/the wall-clock timeout, which all still
apply either way.
"""
import fcntl
import os
import resource
import socket
import struct
import sys

MAX_OPEN_FILES = 256

_SIOCGIFFLAGS = 0x8913
_SIOCSIFFLAGS = 0x8914
_IFF_UP = 0x1


def _bring_up_loopback():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifreq = struct.pack("16sH", b"lo", 0)
        flags = struct.unpack("16sH", fcntl.ioctl(s.fileno(), _SIOCGIFFLAGS, ifreq))[1]
        flags |= _IFF_UP
        ifreq = struct.pack("16sH", b"lo", flags)
        fcntl.ioctl(s.fileno(), _SIOCSIFFLAGS, ifreq)
    finally:
        s.close()


def main():
    uid, gid, cpu, mem, nproc = (int(x) for x in sys.argv[1:6])
    skip_as = sys.argv[6] == "1"
    target_argv = sys.argv[7:]

    _bring_up_loopback()

    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    if not skip_as:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
    if hasattr(resource, "RLIMIT_NOFILE"):
        resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)

    os.execvp(target_argv[0], target_argv)


if __name__ == "__main__":
    main()
