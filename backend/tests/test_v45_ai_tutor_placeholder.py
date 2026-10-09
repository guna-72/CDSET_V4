"""When the optional ai_tutor_backend service is running but has no Gemini key it answers
HTTP 200 with a status message. That message must never be shown to the student as a
tutoring answer; the caller must get None so the rule-based tutor answers instead."""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import tutor  # noqa: E402

RUN = {"outcome": "APPLICATION_FAILURE"}


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _service_says(answer):
    return _Resp(json.dumps({"answer": answer, "status": "success"}).encode())


class TestPlaceholderAnswers(unittest.TestCase):
    def test_placeholder_detection(self):
        for text in ("Gemini API keys are not configured in ai_tutor_backend/.env.",
                     "  gemini api keys are not configured",
                     "I am currently unable to reach the AI model. Please verify your key.",
                     "", None):
            self.assertTrue(tutor._is_placeholder_answer(text), repr(text))
        self.assertFalse(tutor._is_placeholder_answer("Add a try/except around json.loads and return 400."))

    def test_http_placeholder_is_not_returned_as_an_answer(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_service_says("Gemini API keys are not configured in ai_tutor_backend/.env.")), \
             mock.patch("os.path.exists", return_value=False):  # also skip the direct-import path
            self.assertIsNone(tutor.answer_with_ai_tutor_backend("How do I fix this?", RUN, None, "", [], None))

    def test_real_http_answer_is_still_returned(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_service_says("Wrap json.loads in try/except and return a 400.")):
            res = tutor.answer_with_ai_tutor_backend("How do I fix this?", RUN, None, "", [], None)
        self.assertEqual(res["answer"], "Wrap json.loads in try/except and return a 400.")


if __name__ == "__main__":
    unittest.main()
