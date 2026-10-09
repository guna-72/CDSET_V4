"""V38: import a public git repository as a project.

Fully offline: a throwaway local git repository stands in for the remote.
The two guards that would (correctly) reject a local repo - https-only URL
validation and the http(s)-only transport allowlist - are relaxed *only for
the clone plumbing under test*; the validators themselves are covered
directly by the URL/branch tables below.
"""
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ.setdefault("CHAOS_TUTOR_DB_PATH", _TEST_DB)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import api, db, git_intake, orchestrator, sandbox  # noqa: E402
from app.http_framework import HTTPError  # noqa: E402

db.init_db()

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_ZIP = ROOT / "sample_projects" / "mini_task_api.zip"
HAVE_GIT = git_intake.git_available()

_LOCAL_CONFIG = ["-c", "protocol.file.allow=always", "-c", "core.symlinks=false",
                 "-c", "credential.helper="]


def _run(args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def _commit_file(repo, name, text, msg):
    p = pathlib.Path(repo) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _run(["add", "-A"], repo)
    _run(["commit", "-m", msg], repo)


class TestUrlAndBranchValidation(unittest.TestCase):
    GOOD = [
        "https://github.com/octocat/Hello-World.git",
        "https://github.com/octocat/Hello-World",
        "https://gitlab.com/group/sub/project.git",
    ]
    BAD = [
        "", "   ", None, 5,
        "http://github.com/o/r.git",                 # no TLS
        "ssh://git@github.com/o/r.git", "git://github.com/o/r.git",
        "file:///etc/passwd", "ext::sh -c id", "git@github.com:o/r.git",
        "https://user:pw@github.com/o/r.git",        # embedded credentials
        "https://user@github.com/o/r.git",
        "--upload-pack=calc", "-c core.sshCommand=x", "-oProxyCommand=x",
        "https://github.com/o", "https://github.com/",
        "https://localhost/o/r", "https://github.com/o/r#frag",
        "https://github.com/o/r .git", "https://github.com/o/r\n--x",
        "https://github.com\\o\\r", "https://" + "a" * 600 + ".com/o/r",
    ]

    def test_good_urls_accepted(self):
        for u in self.GOOD:
            self.assertEqual(git_intake.validate_repo_url(u), u)

    def test_bad_urls_rejected(self):
        for u in self.BAD:
            with self.subTest(url=u):
                with self.assertRaises(git_intake.GitIntakeError):
                    git_intake.validate_repo_url(u)

    def test_branch_validation(self):
        self.assertIsNone(git_intake.validate_branch(None))
        self.assertIsNone(git_intake.validate_branch("  "))
        for ok in ("main", "release/1.2", "feature_x-2", "v1.0.0"):
            self.assertEqual(git_intake.validate_branch(ok), ok)
        for bad in ("--foo", "-x", "a..b", "a b", "x;rm", "a/", "x.lock", "$(id)", "a" * 200, 7):
            with self.subTest(branch=bad):
                with self.assertRaises(git_intake.GitIntakeError):
                    git_intake.validate_branch(bad)

    def test_repo_name(self):
        self.assertEqual(git_intake.repo_name_from_url("https://github.com/o/Hello-World.git"), "Hello-World")
        self.assertEqual(git_intake.repo_name_from_url("https://github.com/o/repo/"), "repo")

    def test_error_messages_are_specific(self):
        self.assertIn("branch", git_intake._tidy("fatal: Remote branch zz not found in upstream origin"))
        self.assertIn("private", git_intake._tidy("fatal: could not read Username: terminal prompts disabled"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestCloneAndRefresh(unittest.TestCase):
    def setUp(self):
        self._patches = (git_intake._SAFE_CONFIG, git_intake.validate_repo_url)
        git_intake._SAFE_CONFIG = _LOCAL_CONFIG
        git_intake.validate_repo_url = lambda u: u
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "origin")
        os.makedirs(self.origin)
        _run(["init", "-b", "main"], self.origin)
        _commit_file(self.origin, "app.py", "print('v1')\n", "one")
        self.url = pathlib.Path(self.origin).as_uri()
        self.dest = os.path.join(self.tmp, "clone")

    def tearDown(self):
        git_intake._SAFE_CONFIG, git_intake.validate_repo_url = self._patches
        git_intake.remove_tree(self.tmp)

    def test_clone_manifest_and_git_dir_kept(self):
        m = git_intake.clone_repository(self.url, self.dest)
        self.assertEqual(m["file_count"], 1)
        self.assertEqual(m["branch"], "main")
        self.assertEqual(len(m["commit"]), 40)
        self.assertTrue(os.path.isdir(os.path.join(self.dest, ".git")))

    def test_clone_refuses_existing_destination(self):
        os.makedirs(self.dest)
        with self.assertRaises(git_intake.GitIntakeError):
            git_intake.clone_repository(self.url, self.dest)

    def test_bad_remote_leaves_nothing_behind(self):
        with self.assertRaises(git_intake.GitIntakeError):
            git_intake.clone_repository(pathlib.Path(self.tmp, "nope").as_uri(), self.dest)
        self.assertFalse(os.path.exists(self.dest))

    def test_over_limit_clone_is_removed(self):
        old = git_intake.MAX_FILES
        git_intake.MAX_FILES = 0
        try:
            with self.assertRaises(git_intake.GitIntakeError):
                git_intake.clone_repository(self.url, self.dest)
        finally:
            git_intake.MAX_FILES = old
        self.assertFalse(os.path.exists(self.dest))

    def test_refresh_no_change_then_new_commit(self):
        git_intake.clone_repository(self.url, self.dest)
        r = git_intake.refresh_repository(self.dest)
        self.assertFalse(r["changed"])
        _commit_file(self.origin, "app.py", "print('v2')\n", "two")
        r = git_intake.refresh_repository(self.dest)
        self.assertTrue(r["changed"])
        self.assertNotEqual(r["previous_commit"], r["commit"])
        self.assertEqual(pathlib.Path(self.dest, "app.py").read_text(), "print('v2')\n")

    def test_refresh_refuses_to_overwrite_ide_edits(self):
        git_intake.clone_repository(self.url, self.dest)
        pathlib.Path(self.dest, "app.py").write_text("MY EDIT\n")
        with self.assertRaises(git_intake.DirtyWorkingTree) as cm:
            git_intake.refresh_repository(self.dest)
        self.assertEqual(cm.exception.files, ["app.py"])
        self.assertEqual(pathlib.Path(self.dest, "app.py").read_text(), "MY EDIT\n")  # untouched
        r = git_intake.refresh_repository(self.dest, discard_local_changes=True)
        self.assertEqual(r["discarded_files"], ["app.py"])
        self.assertEqual(pathlib.Path(self.dest, "app.py").read_text(), "print('v1')\n")

    def test_refresh_keeps_new_untracked_files(self):
        git_intake.clone_repository(self.url, self.dest)
        pathlib.Path(self.dest, "notes.txt").write_text("mine")
        git_intake.refresh_repository(self.dest)          # not "dirty": nothing tracked changed
        self.assertTrue(pathlib.Path(self.dest, "notes.txt").exists())

    def test_refresh_without_git_dir(self):
        os.makedirs(self.dest)
        with self.assertRaises(git_intake.GitIntakeError):
            git_intake.refresh_repository(self.dest)

    def test_orchestrator_refresh_invalidates_stale_analysis_but_keeps_runs(self):
        p = orchestrator.create_project_from_git(self.url, None, "demo")
        self.addCleanup(git_intake.remove_tree, p["storage_path"])
        self.assertEqual((p["source_type"], p["git_branch"], p["name"]), ("git", "main", "demo"))
        pid = p["id"]
        now = db.now()
        db.insert("project_analysis", {"id": db.new_id(), "project_id": pid, "status": "DONE", "created_at": now})
        fp_run, fp_free = db.new_id(), db.new_id()
        for fid in (fp_run, fp_free):
            db.insert("failure_points", {"id": fid, "project_id": pid, "component": fid[:4], "type": "t", "created_at": now})
        ex_run, ex_free = db.new_id(), db.new_id()
        for eid, fid in ((ex_run, fp_run), (ex_free, fp_free)):
            db.insert("experiments", {"id": eid, "project_id": pid, "failure_point_id": fid, "name": "n",
                                      "category": "c", "target": "t", "fault_type": "f", "risk_level": 1, "created_at": now})
        db.insert("experiment_runs", {"id": db.new_id(), "experiment_id": ex_run, "project_id": pid})
        db.update("projects", pid, {"status": "ANALYZED"})

        # nothing changed upstream -> nothing invalidated
        out = orchestrator.refresh_git_project(pid)
        self.assertFalse(out["refresh"]["analysis_invalidated"])
        self.assertEqual(len(db.get_many("project_analysis", "project_id = ?", (pid,))), 1)

        _commit_file(self.origin, "app.py", "print('v2')\n", "two")
        out = orchestrator.refresh_git_project(pid)
        self.assertTrue(out["refresh"]["analysis_invalidated"])
        self.assertEqual(out["status"], "UPLOADED")
        self.assertEqual(out["git_commit"], out["refresh"]["commit"])
        self.assertEqual(db.get_many("project_analysis", "project_id = ?", (pid,)), [])
        self.assertEqual([e["id"] for e in db.get_many("experiments", "project_id = ?", (pid,))], [ex_run])
        self.assertEqual([f["id"] for f in db.get_many("failure_points", "project_id = ?", (pid,))], [fp_run])
        self.assertEqual(len(db.get_many("experiment_runs", "project_id = ?", (pid,))), 1)

    def test_refresh_rejects_zip_projects(self):
        if not PY_ZIP.exists():
            self.skipTest("sample zip missing")
        z = orchestrator.create_project(str(PY_ZIP), "zipped")
        self.addCleanup(git_intake.remove_tree, z["storage_path"])
        self.assertEqual(z["source_type"], "upload")
        with self.assertRaises(orchestrator.OrchestratorError):
            orchestrator.refresh_git_project(z["id"])


class TestIdeSavePreservesLineEndings(unittest.TestCase):
    """Windows regression: write_text() turned every \\n into \\r\\n, so
    open-and-save of an untouched file rewrote every line."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _save(self, name, content):
        api._write_text_keep_newlines(self.dir / name, content)
        return (self.dir / name).read_bytes()

    def test_lf_file_stays_lf(self):
        (self.dir / "a.py").write_bytes(b"one\ntwo\n")
        self.assertEqual(self._save("a.py", "one\ntwo\nthree\n"), b"one\ntwo\nthree\n")

    def test_crlf_file_stays_crlf(self):
        (self.dir / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        self.assertEqual(self._save("a.txt", "one\ntwo\nthree\n"), b"one\r\ntwo\r\nthree\r\n")

    def test_new_file_is_always_lf(self):
        self.assertEqual(self._save("new.py", "a\nb\n"), b"a\nb\n")

    def test_majority_style_wins_for_mixed_files(self):
        (self.dir / "m.txt").write_bytes(b"a\r\nb\r\nc\n")
        self.assertEqual(self._save("m.txt", "x\ny\n"), b"x\r\ny\r\n")
        (self.dir / "n.txt").write_bytes(b"a\nb\nc\r\n")
        self.assertEqual(self._save("n.txt", "x\ny\n"), b"x\ny\n")

    def test_content_that_already_has_crlf_is_not_doubled(self):
        (self.dir / "c.txt").write_bytes(b"a\r\n")
        self.assertEqual(self._save("c.txt", "a\r\nb\r\n"), b"a\r\nb\r\n")

    def test_no_trailing_newline_and_unicode(self):
        self.assertEqual(self._save("u.txt", "h\u00e9llo \u2713"), "h\u00e9llo \u2713".encode("utf-8"))

    def test_open_then_save_untouched_is_byte_identical(self):
        for raw in (b"x = 1\ny = 2\n", b"x = 1\r\ny = 2\r\n", b"no newline at end", b""):
            with self.subTest(raw=raw):
                f = self.dir / "r.py"
                f.write_bytes(raw)
                shown = f.read_text(encoding="utf-8")            # what api.read_project_file returns
                self.assertEqual(self._save("r.py", shown), raw)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_saving_an_untouched_tracked_file_is_not_a_git_change(self):
        origin = self.dir / "o"
        origin.mkdir()
        _run(["init", "-b", "main"], str(origin))
        _run(["config", "core.autocrlf", "false"], str(origin))
        (origin / "app.py").write_bytes(b"print(1)\nprint(2)\n")
        _run(["add", "-A"], str(origin))
        _run(["commit", "-m", "x"], str(origin))
        api._write_text_keep_newlines(origin / "app.py", (origin / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(git_intake.working_tree_changes(str(origin)), [])


class TestGitGuards(unittest.TestCase):
    def test_ide_endpoints_refuse_dot_git(self):
        project = {"storage_path": tempfile.gettempdir()}
        for rel in (".git/config", ".git/HEAD", "sub/.git/config", ".GIT/config", "a/.Git/x"):
            with self.subTest(path=rel):
                with self.assertRaises(HTTPError):
                    api._safe_project_file(project, rel)

    def test_ide_endpoints_still_allow_dotfiles_that_are_not_git(self):
        project = {"storage_path": tempfile.gettempdir()}
        target, rel = api._safe_project_file(project, ".gitignore")
        self.assertEqual(rel, ".gitignore")
        api._safe_project_file(project, ".github/workflows/ci.yml")

    def test_workspace_copy_skips_git_and_caches_but_keeps_dependencies(self):
        """Regression: an earlier version also skipped node_modules/venv/dist,
        so a real Express app died with "Cannot find module 'express'" and every
        experiment came back TARGET_UNREACHABLE."""
        src = tempfile.mkdtemp()
        try:
            for d in (".git/objects", "__pycache__", "node_modules/express", ".venv/lib", "dist", "src"):
                os.makedirs(os.path.join(src, d))
            for f in ("src/main.py", "node_modules/express/index.js", ".venv/lib/x.py", "dist/app.js", ".git/objects/pack"):
                pathlib.Path(src, f).write_text("x")
            ws = sandbox.make_workspace(src, "t38")
            try:
                self.assertEqual(sorted(os.listdir(ws)), [".venv", "dist", "node_modules", "src"])
                self.assertTrue(os.path.exists(os.path.join(ws, "node_modules", "express", "index.js")))
            finally:
                sandbox.destroy_workspace(ws)
        finally:
            shutil.rmtree(src, ignore_errors=True)

    def test_remove_tree_deletes_read_only_files(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, ".git", "objects", "pack.idx")
        os.makedirs(os.path.dirname(f))
        pathlib.Path(f).write_text("x")
        os.chmod(f, stat.S_IREAD)                  # how git stores pack files
        git_intake.remove_tree(d)
        self.assertFalse(os.path.exists(d))

    def test_migration_upgrades_a_pre_git_database_in_place(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, original_filename TEXT, "
                     "storage_path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'UPLOADED', created_at REAL NOT NULL)")
        conn.execute("INSERT INTO projects (id,name,storage_path,created_at) VALUES ('a','old','/x',1)")
        db._ensure_columns(conn)
        db._ensure_columns(conn)                       # idempotent
        row = conn.execute("SELECT owner_uid, source_type, git_url, git_branch, git_commit FROM projects").fetchone()
        conn.close()
        self.assertEqual(row, ("local", "upload", None, None, None))


@unittest.skipUnless(PY_ZIP.exists(), "sample project missing")
class TestIdempotentSteps(unittest.TestCase):
    def test_discover_and_generate_do_not_stack_duplicates(self):
        p = orchestrator.create_project(str(PY_ZIP), "idem")
        self.addCleanup(git_intake.remove_tree, p["storage_path"])
        pid = p["id"]
        profile = orchestrator.analyze_project(pid)["profile"]
        orchestrator.analyze_project(pid)
        self.assertEqual(len(db.get_many("project_analysis", "project_id = ?", (pid,))), 1)

        counts = []
        for _ in range(3):
            pts = orchestrator.discover_failures(pid, profile)
            fps = db.get_many("failure_points", "project_id = ?", (pid,))
            counts.append(len(fps))
            exps = orchestrator.generate_and_gate_experiments(
                pid, profile, [{**f, "dependencies": db.loads(f["dependencies_json"]),
                                "failure_modes": db.loads(f["failure_modes_json"])} for f in fps])
            counts.append(len(db.get_many("experiments", "project_id = ?", (pid,))))
        self.assertEqual(counts[0::2], [len(pts)] * 3)          # failure points stable
        self.assertEqual(len(set(counts[1::2])), 1)             # experiments stable

    def test_experiments_with_run_history_survive_regeneration(self):
        p = orchestrator.create_project(str(PY_ZIP), "keep-runs")
        self.addCleanup(git_intake.remove_tree, p["storage_path"])
        pid = p["id"]
        profile = orchestrator.analyze_project(pid)["profile"]
        orchestrator.discover_failures(pid, profile)
        fps = lambda: [{**f, "dependencies": db.loads(f["dependencies_json"]),
                        "failure_modes": db.loads(f["failure_modes_json"])}
                       for f in db.get_many("failure_points", "project_id = ?", (pid,))]
        orchestrator.generate_and_gate_experiments(pid, profile, fps())
        keep = db.get_many("experiments", "project_id = ?", (pid,))[0]
        db.insert("experiment_runs", {"id": db.new_id(), "experiment_id": keep["id"], "project_id": pid})
        orchestrator.discover_failures(pid, profile)            # must not raise a FOREIGN KEY error
        orchestrator.generate_and_gate_experiments(pid, profile, fps())
        self.assertIsNotNone(db.get_one("experiments", keep["id"]))


if __name__ == "__main__":
    unittest.main()
