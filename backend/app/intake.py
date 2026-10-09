from __future__ import annotations
"""
Project intake — upload validation + safe extraction (spec section 39).

Every uploaded archive is untrusted. This module is the only place that
touches a raw zip before it's inside a controlled, size-checked directory.
"""
import os
import shutil
import zipfile

from app.longpath import lp
from app.config import (
    IGNORED_DIRS,
    STORAGE_DIR,
    MAX_ARCHIVE_BYTES,
    MAX_EXTRACTED_BYTES,
    MAX_FILES,
    MAX_SINGLE_FILE_BYTES,
    MAX_PATH_LEN,
    MAX_FILENAME_LEN,
)


class IntakeError(Exception):
    """Raised for any validation failure; message is safe to show the user."""


# Generated/dependency directories are not useful as uploaded source and can
# contain tens of thousands of files. They are recreated by the real project
# runtime when needed, so the import pipeline excludes them while preserving
# the user's source tree.
# IGNORED_DIRS now lives in app.config (shared with git intake + sandbox).

def validate_and_extract(zip_path: str, dest_dir: str) -> dict:
    """Validate a zip archive against the MVP_SAFE limits and extract it
    into dest_dir (which must not exist yet). Returns a small manifest
    summary. Raises IntakeError with a specific, honest reason on any
    violation — never partially extracts an unsafe archive."""
    if os.path.exists(dest_dir):
        raise IntakeError(f"destination already exists: {dest_dir}")

    archive_size = os.path.getsize(zip_path)
    if archive_size > MAX_ARCHIVE_BYTES:
        raise IntakeError(
            f"archive too large: {archive_size} bytes > {MAX_ARCHIVE_BYTES} byte limit"
        )

    if not zipfile.is_zipfile(zip_path):
        raise IntakeError("not a valid zip archive")

    total_uncompressed = 0
    file_count = 0
    ignored_count = 0
    real_dest = os.path.abspath(dest_dir)
    top_levels = set()
    top_level_is_file = False

    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()

        for info in infos:
            name = info.filename

            # --- path traversal / absolute path protection ---
            if name.startswith("/") or name.startswith("\\"):
                raise IntakeError(f"rejected absolute path in archive: {name}")
            if os.path.isabs(name):
                raise IntakeError(f"rejected absolute path in archive: {name}")
            # Reject on the ".." path *component* (after treating "\\" as a
            # separator too), not on a substring: names such as "..hidden" or
            # "a/..b" are legitimate and must not be refused.
            normalized = os.path.normpath(name.replace("\\", "/"))
            if ".." in normalized.replace("\\", "/").split("/"):
                raise IntakeError(f"rejected path traversal entry: {name}")
            # Windows drive letters (C:\...) smuggled into a name on a
            # posix host would not normalize away — reject explicitly.
            if len(name) >= 2 and name[1] == ":":
                raise IntakeError(f"rejected drive-qualified path: {name}")

            if len(name) > MAX_PATH_LEN:
                raise IntakeError(f"path exceeds {MAX_PATH_LEN} chars: {name}")
            base = os.path.basename(name)
            if len(base) > MAX_FILENAME_LEN:
                raise IntakeError(f"filename exceeds {MAX_FILENAME_LEN} chars: {base}")

            # --- symlink protection: validate this before any ignore rule.
            # Never allow an ignored directory to become a security bypass. ---
            mode = (info.external_attr >> 16) & 0xFFFF
            is_symlink = bool(mode) and _is_symlink_mode(mode)
            if is_symlink:
                raise IntakeError(f"rejected symlink entry in archive: {name}")

            # Skip generated dependency/build trees after all path-safety
            # checks have passed. This keeps normal source archives usable
            # even when they contain a large node_modules/.git/venv tree.
            parts = [p for p in name.replace("\\", "/").split("/") if p]
            check_parts = parts if info.is_dir() else parts[:-1]
            if any(part in IGNORED_DIRS for part in check_parts if part):
                ignored_count += 1
                continue

            if parts:
                top_levels.add(parts[0])
                if len(parts) == 1 and not info.is_dir():
                    top_level_is_file = True

            if not info.is_dir():
                file_count += 1
            if file_count > MAX_FILES:
                raise IntakeError(f"project contains more than {MAX_FILES} source files after generated files were excluded")

            # --- archive bomb protection (uncompressed size ceiling +
            # a sane compression-ratio ceiling to catch zip bombs that
            # are individually under the per-file cap) ---
            if info.file_size > MAX_SINGLE_FILE_BYTES:
                raise IntakeError(
                    f"file too large in archive: {name} ({info.file_size} bytes)"
                )
            if info.compress_size > 0:
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > 200 and info.file_size > 10 * 1024 * 1024:
                    raise IntakeError(
                        f"suspicious compression ratio ({ratio:.0f}x) on {name} — "
                        "rejected as a likely archive bomb"
                    )

            total_uncompressed += info.file_size
            if total_uncompressed > MAX_EXTRACTED_BYTES:
                raise IntakeError(
                    f"extracted size exceeds {MAX_EXTRACTED_BYTES} byte limit"
                )

            # Fast normalized containment check (symlinks are already blocked above)
            target_path = os.path.abspath(os.path.join(dest_dir, name))
            if not (target_path == real_dest or target_path.startswith(real_dest + os.sep)):
                raise IntakeError(f"entry resolves outside destination: {name}")

        # All entries validated — now actually extract. Files are written with
        # long-path-safe names (\\?\\ prefix on Windows) so deeply nested
        # projects do not fail with WinError 206.
        os.makedirs(lp(dest_dir), exist_ok=True)
        try:
            for info in infos:
                parts = [p for p in info.filename.replace("\\", "/").split("/") if p]
                check_parts = parts if info.is_dir() else parts[:-1]
                if any(part in IGNORED_DIRS for part in check_parts if part):
                    continue
                if not parts:
                    continue
                target = os.path.join(dest_dir, *parts)
                if info.is_dir():
                    os.makedirs(lp(target), exist_ok=True)
                    continue
                os.makedirs(lp(os.path.dirname(target)), exist_ok=True)
                with zf.open(info) as src, open(lp(target), "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as e:
            # Corrupt/encrypted/unsupported archive or a disk error part-way
            # through: never leave a half-extracted project behind, and report
            # a clean rejection instead of an internal server error.
            shutil.rmtree(lp(dest_dir), ignore_errors=True)
            raise IntakeError(f"could not extract archive: {e}") from e

    meaningful_root = next(iter(top_levels)) if len(top_levels) == 1 else ""
    if meaningful_root and top_level_is_file:
        meaningful_root = os.path.splitext(meaningful_root)[0]

    # Flatten a single wrapping top-level folder (e.g. "myproject/app.py",
    # "myproject/package.json") so marker-file and entrypoint detection see
    # files at the true project root. This is how virtually every zip tool
    # packages a project (Compress/right-click on Mac/Windows, GitHub's
    # "Download ZIP", etc.) — without this, package.json/requirements.txt/
    # Dockerfile checks silently miss and framework detection falls back
    # to guessing, even though the project itself is perfectly supported.
    if meaningful_root and not top_level_is_file:
        wrapper_path = os.path.join(dest_dir, meaningful_root)
        if os.path.isdir(lp(wrapper_path)):
            # Rename the wrapper out of the way first. Otherwise a very common
            # layout such as "mysite/mysite/settings.py" (project folder that
            # contains a package of the same name) makes shutil.move() try to
            # move the inner folder onto the wrapper itself and crash.
            tmp_wrapper = os.path.join(dest_dir, f".chaos_unwrap_{os.getpid()}_{id(wrapper_path)}")
            os.rename(lp(wrapper_path), lp(tmp_wrapper))
            for entry in os.listdir(lp(tmp_wrapper)):
                shutil.move(lp(os.path.join(tmp_wrapper, entry)), lp(os.path.join(dest_dir, entry)))
            os.rmdir(lp(tmp_wrapper))

    return {
        "file_count": file_count,
        "total_uncompressed_bytes": total_uncompressed,
        "archive_bytes": archive_size,
        "ignored_entries": ignored_count,
        "project_root_name": meaningful_root,
    }


def _is_symlink_mode(unix_mode: int) -> bool:
    S_IFLNK = 0o120000
    return (unix_mode & 0o170000) == S_IFLNK
