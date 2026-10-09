import os
import sys
import shutil
import zipfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import intake

TMP = "/tmp/intake_test"


def make_zip(path, entries):
    """entries: list of (arcname, content_bytes_or_None_for_dir)"""
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in entries:
            if content is None:
                zi = zipfile.ZipInfo(arcname + "/")
                zf.writestr(zi, "")
            else:
                zf.writestr(arcname, content)


class TestIntakeSecurity(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_valid_archive_extracts_cleanly(self):
        zpath = os.path.join(TMP, "ok.zip")
        make_zip(zpath, [("app.py", b"print('hi')"), ("requirements.txt", b"")])
        dest = os.path.join(TMP, "dest1")
        manifest = intake.validate_and_extract(zpath, dest)
        self.assertEqual(manifest["file_count"], 2)
        self.assertTrue(os.path.exists(os.path.join(dest, "app.py")))

    def test_path_traversal_rejected(self):
        zpath = os.path.join(TMP, "traversal.zip")
        make_zip(zpath, [("../../etc/passwd", b"pwned")])
        dest = os.path.join(TMP, "dest2")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(zpath, dest)
        self.assertFalse(os.path.exists(dest), "unsafe archive must not partially extract")

    def test_absolute_path_rejected(self):
        zpath = os.path.join(TMP, "abs.zip")
        make_zip(zpath, [("/etc/cron.d/evil", b"pwned")])
        dest = os.path.join(TMP, "dest3")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(zpath, dest)

    def test_symlink_entry_rejected(self):
        zpath = os.path.join(TMP, "symlink.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zi = zipfile.ZipInfo("evil_link")
            zi.create_system = 3  # unix
            zi.external_attr = (0o120777 << 16)  # S_IFLNK
            zf.writestr(zi, "/etc/passwd")
        dest = os.path.join(TMP, "dest4")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(zpath, dest)

    def test_oversized_single_file_rejected(self):
        zpath = os.path.join(TMP, "big.zip")
        # Monkeypatch limit down for a fast test
        original = intake.MAX_SINGLE_FILE_BYTES
        intake.MAX_SINGLE_FILE_BYTES = 100
        try:
            make_zip(zpath, [("big.bin", b"x" * 1000)])
            dest = os.path.join(TMP, "dest5")
            with self.assertRaises(intake.IntakeError):
                intake.validate_and_extract(zpath, dest)
        finally:
            intake.MAX_SINGLE_FILE_BYTES = original

    def test_too_many_files_rejected(self):
        zpath = os.path.join(TMP, "manyfiles.zip")
        original = intake.MAX_FILES
        intake.MAX_FILES = 5
        try:
            entries = [(f"f{i}.txt", b"x") for i in range(10)]
            make_zip(zpath, entries)
            dest = os.path.join(TMP, "dest6")
            with self.assertRaises(intake.IntakeError):
                intake.validate_and_extract(zpath, dest)
        finally:
            intake.MAX_FILES = original

    def test_not_a_zip_rejected(self):
        fake = os.path.join(TMP, "notazip.zip")
        with open(fake, "wb") as f:
            f.write(b"this is not a zip file")
        dest = os.path.join(TMP, "dest7")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(fake, dest)

    def test_windows_drive_path_rejected(self):
        zpath = os.path.join(TMP, "drive.zip")
        make_zip(zpath, [("C:/Windows/System32/evil.dll", b"x")])
        dest = os.path.join(TMP, "dest8")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(zpath, dest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
