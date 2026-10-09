from __future__ import annotations
"""
Windows long-path helper.

Windows limits normal paths to 260 characters (WinError 206 "The filename or
extension is too long"). Prefixing an absolute path with \\\\?\\ lifts that
limit for file APIs, without needing any registry change. On Linux/macOS this
is a no-op.
"""
import os


def lp(path: str) -> str:
    """Return `path` in a form that is safe for very long Windows paths."""
    if os.name != "nt" or not path:
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):                 # UNC share
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path
