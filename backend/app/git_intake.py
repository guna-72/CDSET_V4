from __future__ import annotations
"""
Git project intake - import a *public* HTTPS repository as a project.

Same trust model as app/intake.py: the repository is untrusted input. It is
cloned shallowly (one commit, one branch) straight into a controlled
directory, then checked against the same size/file-count limits as a zip
upload. The clone keeps its .git directory so the project can later be
refreshed from the remote; .git is never exposed through the file APIs and
is never copied into throwaway chaos workspaces (see app/config.py
IGNORED_DIRS).

Scope (v1, deliberate): public repositories over https:// only. URLs that
embed credentials (https://user:token@host/...), ssh://, git://, file://,
ext:: and friends are rejected - storing credentials for private repos is a
separate security design, not something to bolt on quietly.

Every git invocation is hardened: terminal/credential prompts disabled (a
private repo fails fast instead of hanging or popping a Windows credential
dialog), only http(s) transports allowed (so a redirect or submodule cannot
pivot to file:// or ext::), and symlink checkout disabled (zip intake
rejects symlinks; a repo must not be able to smuggle one in either).
"""
import os
import re
import shutil
import subprocess
import time
from urllib.parse import urlparse

from app.config import (
    IGNORED_DIRS,
    MAX_EXTRACTED_BYTES,
    MAX_FILENAME_LEN,
    MAX_FILES,
    MAX_PATH_LEN,
    MAX_SINGLE_FILE_BYTES,
    GIT_CLONE_TIMEOUT_SECONDS,
    GIT_MAX_URL_LEN,
)
from app.intake import IntakeError
from app.longpath import lp

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")
_SAFE_CONFIG = [
    "-c", "protocol.allow=never",
    "-c", "protocol.https.allow=always",
    "-c", "core.symlinks=false",
    "-c", "credential.helper=",
    "-c", "core.fsmonitor=false",
    "-c", "core.longpaths=true",   # Windows: don't fail checkout on paths > 260 chars
]
# NOTE: system git config is deliberately NOT disabled (GIT_CONFIG_NOSYSTEM):
# Git for Windows keeps its TLS certificate settings there, so ignoring it
# risks breaking every https clone on the very platform this ships for.


class GitIntakeError(IntakeError):
    """Any git import/refresh failure; message is safe to show the user."""


class DirtyWorkingTree(GitIntakeError):
    """Refresh refused because tracked files have local (IDE) edits."""

    def __init__(self, files):
        self.files = files
        super().__init__(
            f"{len(files)} file(s) have local edits that a refresh would overwrite"
        )


def git_available() -> bool:
    return shutil.which("git") is not None


def validate_repo_url(url) -> str:
    """Return the normalized URL or raise GitIntakeError."""
    if not isinstance(url, str):
        raise GitIntakeError("repository URL must be text")
    url = url.strip()
    if not url:
        raise GitIntakeError("repository URL is required")
    if len(url) > GIT_MAX_URL_LEN:
        raise GitIntakeError(f"repository URL is longer than {GIT_MAX_URL_LEN} characters")
    if url.startswith("-"):
        raise GitIntakeError("invalid repository URL")
    if any(ord(c) < 33 or ord(c) == 127 for c in url) or "\\" in url:
        raise GitIntakeError("repository URL contains invalid characters")
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise GitIntakeError(
            "only public https:// repository URLs are supported "
            "(ssh://, git://, file:// and http:// are not allowed)"
        )
    if "@" in parsed.netloc or parsed.username or parsed.password:
        raise GitIntakeError(
            "URLs with embedded credentials are not supported - "
            "import a public repository, or download the ZIP and upload it instead"
        )
    if not parsed.hostname or "." not in parsed.hostname:
        raise GitIntakeError("repository URL must include a valid host name")
    if parsed.fragment:
        raise GitIntakeError("repository URL must not contain a #fragment")
    path = parsed.path.strip("/")
    if not path or len(path.split("/")) < 2:
        raise GitIntakeError("repository URL must point to a repository (https://host/owner/repo)")
    return url


def validate_branch(branch):
    if branch is None:
        return None
    if not isinstance(branch, str):
        raise GitIntakeError("branch must be text")
    branch = branch.strip()
    if not branch:
        return None
    if not _BRANCH_RE.match(branch) or ".." in branch or branch.endswith((".lock", "/", ".")):
        raise GitIntakeError("invalid branch name")
    return branch


def repo_name_from_url(url: str) -> str:
    last = urlparse(url).path.rstrip("/").split("/")[-1]
    if last.lower().endswith(".git"):
        last = last[:-4]
    return last or "git-project"


# Windows: never let git.exe pop up a console window (no-op elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"     # never wait for a username/password
    env["GCM_INTERACTIVE"] = "never"     # Git Credential Manager: no dialog
    env["GIT_ASKPASS"] = ""              # no askpass helper
    return env


def _git(args, cwd=None, timeout=60):
    try:
        return subprocess.run(
            ["git", *_SAFE_CONFIG, *args],
            cwd=cwd, env=_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        raise GitIntakeError(
            "git is not installed or not on PATH - install Git for Windows "
            "from https://git-scm.com/download/win and restart Chaos Tutor"
        )
    except subprocess.TimeoutExpired:
        raise GitIntakeError(f"git timed out after {timeout}s")


def _tidy(stderr: str) -> str:
    text = " ".join((stderr or "").split())
    text = re.sub(r"^(fatal|error):\s*", "", text, flags=re.I)
    low = text.lower()
    # Branch check first: "Remote branch X not found" also contains "not found".
    if "remote branch" in low and "not found" in low:
        return "branch not found in that repository"
    if "could not read username" in low or "authentication failed" in low or "terminal prompts disabled" in low:
        # GitHub answers a nonexistent repo exactly like a private one.
        return "repository not found, or it is private - only public repositories are supported"
    if "not found" in low or "does not exist" in low:
        return "repository not found (check the URL, and that it is public)"
    return text[:300] or "git failed"


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _scan_limits(root: str) -> tuple[int, int, int]:
    """Enforce the same ceilings as zip intake on the checked-out source
    tree (ignored dirs excluded, .git excluded). Returns
    (file_count, total_bytes, ignored_dir_count)."""
    files = total = ignored = 0
    for cur, dirs, names in os.walk(root):
        keep = []
        for d in dirs:
            if d in IGNORED_DIRS:
                ignored += 1
            else:
                keep.append(d)
        dirs[:] = keep
        for n in names:
            full = os.path.join(cur, n)
            rel = os.path.relpath(full, root)
            if len(rel) > MAX_PATH_LEN:
                raise GitIntakeError(f"path exceeds {MAX_PATH_LEN} chars: {rel[:80]}...")
            if len(n) > MAX_FILENAME_LEN:
                raise GitIntakeError(f"filename exceeds {MAX_FILENAME_LEN} chars: {n[:80]}...")
            if os.path.islink(full):
                raise GitIntakeError(f"rejected symlink in repository: {rel}")
            size = os.lstat(full).st_size
            if size > MAX_SINGLE_FILE_BYTES:
                raise GitIntakeError(f"file too large in repository: {rel} ({size} bytes)")
            files += 1
            total += size
            if files > MAX_FILES:
                raise GitIntakeError(f"repository contains more than {MAX_FILES} source files")
            if total > MAX_EXTRACTED_BYTES:
                raise GitIntakeError(f"repository exceeds the {MAX_EXTRACTED_BYTES} byte size limit")
    return files, total, ignored


def head_commit(repo_dir: str) -> str:
    r = _git(["rev-parse", "HEAD"], cwd=repo_dir, timeout=15)
    return r.stdout.strip() if r.returncode == 0 else ""


def current_branch(repo_dir: str) -> str:
    r = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, timeout=15)
    return r.stdout.strip() if r.returncode == 0 else ""


def clone_repository(url: str, dest_dir: str, branch=None) -> dict:
    """Shallow-clone url into dest_dir (must not exist). Returns a manifest
    shaped like intake.validate_and_extract's, plus commit/branch. Never
    leaves a partial or over-limit clone behind."""
    url = validate_repo_url(url)
    branch = validate_branch(branch)
    if os.path.exists(dest_dir):
        raise GitIntakeError(f"destination already exists: {dest_dir}")
    if not git_available():
        raise GitIntakeError(
            "git is not installed or not on PATH - install Git for Windows "
            "from https://git-scm.com/download/win and restart Chaos Tutor"
        )

    cmd = ["git", *_SAFE_CONFIG, "clone", "--depth", "1", "--single-branch",
           "--no-tags", "--no-recurse-submodules"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", url, dest_dir]

    proc = subprocess.Popen(cmd, env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=_NO_WINDOW)
    started = time.monotonic()
    stderr = ""
    try:
        while True:
            try:
                _out, stderr = proc.communicate(timeout=2)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started > GIT_CLONE_TIMEOUT_SECONDS:
                    proc.kill(); proc.communicate()
                    raise GitIntakeError(f"clone timed out after {GIT_CLONE_TIMEOUT_SECONDS}s")
                if os.path.isdir(dest_dir) and _dir_size(dest_dir) > MAX_EXTRACTED_BYTES:
                    proc.kill(); proc.communicate()
                    raise GitIntakeError(f"repository exceeds the {MAX_EXTRACTED_BYTES} byte size limit")
    except GitIntakeError:
        _rm(dest_dir)
        raise
    except BaseException:
        proc.kill()
        _rm(dest_dir)
        raise

    if proc.returncode != 0:
        _rm(dest_dir)
        raise GitIntakeError(_tidy(stderr))

    try:
        files, total, ignored = _scan_limits(dest_dir)
    except GitIntakeError:
        _rm(dest_dir)
        raise
    return {
        "file_count": files,
        "total_uncompressed_bytes": total,
        "archive_bytes": total,
        "ignored_entries": ignored,
        "project_root_name": repo_name_from_url(url),
        "commit": head_commit(dest_dir),
        "branch": current_branch(dest_dir),
    }


def working_tree_changes(repo_dir: str) -> list[str]:
    """Tracked files with local edits (IDE saves). Untracked files and the
    harness's own .chaos_* files are not overwritten by a refresh."""
    r = _git(["status", "--porcelain", "--untracked-files=no"], cwd=repo_dir, timeout=30)
    if r.returncode != 0:
        raise GitIntakeError(_tidy(r.stderr))
    out = []
    for line in r.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if path and not os.path.basename(path).startswith(".chaos_"):
            out.append(path)
    return out


def refresh_repository(repo_dir: str, branch=None, discard_local_changes=False) -> dict:
    """Fetch the latest commit of the tracked branch and move the working
    tree to it. Refuses (DirtyWorkingTree) if tracked files were edited
    locally unless discard_local_changes is True."""
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        raise GitIntakeError("this project has no git metadata to refresh from")
    if not git_available():
        raise GitIntakeError(
            "git is not installed or not on PATH - install Git for Windows "
            "from https://git-scm.com/download/win and restart Chaos Tutor"
        )
    branch = validate_branch(branch) or current_branch(repo_dir)
    if not branch or branch == "HEAD":
        raise GitIntakeError("cannot determine which branch to refresh")

    dirty = working_tree_changes(repo_dir)
    if dirty and not discard_local_changes:
        raise DirtyWorkingTree(dirty)

    before = head_commit(repo_dir)
    f = _git(["fetch", "--depth", "1", "--no-tags", "origin", branch],
             cwd=repo_dir, timeout=GIT_CLONE_TIMEOUT_SECONDS)
    if f.returncode != 0:
        raise GitIntakeError(_tidy(f.stderr))
    r = _git(["reset", "--hard", "FETCH_HEAD"], cwd=repo_dir, timeout=60)
    if r.returncode != 0:
        raise GitIntakeError(_tidy(r.stderr))
    after = head_commit(repo_dir)

    files, total, ignored = _scan_limits(repo_dir)   # repo may have grown
    return {
        "changed": before != after,
        "previous_commit": before,
        "commit": after,
        "branch": branch,
        "discarded_files": dirty if discard_local_changes else [],
        "file_count": files,
        "total_uncompressed_bytes": total,
        "ignored_entries": ignored,
    }


def remove_tree(path: str):
    """rmtree that also works on Windows, where git's object/pack files are
    read-only and a plain shutil.rmtree(ignore_errors=True) silently leaves
    the whole .git directory (and a half-finished clone) behind."""
    import stat

    def _writable_retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if os.path.isdir(lp(path)):
        shutil.rmtree(lp(path), onerror=_writable_retry)


_rm = remove_tree
