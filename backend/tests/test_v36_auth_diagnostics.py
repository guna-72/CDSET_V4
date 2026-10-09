import unittest
import os
import tempfile
from app.auth import _explain_verify_failure, _discover_project_id, _read_env_file_value


class ExpiredIdTokenError(Exception):
    pass


class AuthDiagnosticsTests(unittest.TestCase):
    def test_project_mismatch(self):
        r, h = _explain_verify_failure(ValueError('Firebase ID token has incorrect "aud" (audience) claim.'))
        self.assertEqual(r, "project mismatch")

    def test_expired(self):
        self.assertEqual(_explain_verify_failure(ExpiredIdTokenError("x"))[0], "expired token")

    def test_clock(self):
        self.assertEqual(_explain_verify_failure(ValueError("Token used too early, 1 < 2"))[0], "clock skew")

    def test_network(self):
        self.assertEqual(_explain_verify_failure(Exception("Max retries exceeded"))[0], "cannot reach Google")

    def test_not_id_token(self):
        self.assertEqual(_explain_verify_failure(ValueError("Wrong number of segments in token"))[0], "not a Firebase ID token")

    def test_unknown_leaks_nothing(self):
        r, h = _explain_verify_failure(Exception("boom secret"))
        self.assertNotIn("secret", h)

    def test_missing_project_id_is_explained(self):
        r, h = _explain_verify_failure(ValueError("A project ID is required to access the auth service."))
        self.assertEqual(r, "no Firebase project")

    def test_adc_missing_is_explained(self):
        r, h = _explain_verify_failure(Exception("Your default credentials were not found."))
        self.assertEqual(r, "adc missing")

    def test_project_id_read_from_frontend_env(self):
        keys = ("FIREBASE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            with tempfile.TemporaryDirectory() as td:
                with open(os.path.join(td, ".env"), "w") as f:
                    f.write("# c\nVITE_API_URL=http://x\nVITE_FIREBASE_PROJECT_ID=\"my-proj\"\n")
                self.assertEqual(_discover_project_id(td), "my-proj")
                os.environ["FIREBASE_PROJECT_ID"] = "from-env"
                self.assertEqual(_discover_project_id(td), "from-env")
        finally:
            os.environ.pop("FIREBASE_PROJECT_ID", None)
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_env_file_missing_returns_none(self):
        self.assertIsNone(_read_env_file_value("/nonexistent/.env", "X"))


if __name__ == "__main__":
    unittest.main()
