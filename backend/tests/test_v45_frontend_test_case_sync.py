"""Guards that every backend test case (fault type) is wired correctly in the UI.

If a fault type is added/renamed in experiment_library.TEMPLATES but not in the
Chaos Lab list, the api.js preset map, or the Experiments labels, that test case
would silently never grey out, never run, or show a raw code name.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import experiment_library  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(os.path.dirname(BACKEND), "chaos", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as fh:
        return fh.read()


class TestFrontendTestCaseSync(unittest.TestCase):
    def setUp(self):
        self.backend = set(experiment_library.TEMPLATES)
        api = _read("api.js")
        block = api[api.index("const PRESET_FAULT"):api.index("const findExperimentForPreset")]
        self.preset_fault = dict(re.findall(r"(\w+): '(\w+)'", block))
        lab = _read("pages", "ChaosLabPage.jsx")
        self.lab_presets = re.findall(r"preset: '([a-z_0-9]+)', label:", lab)
        exp = _read("pages", "ExperimentsPage.jsx")
        self.type_info = set(re.findall(r"^\s+([a-z_0-9]+): \{ label:'", exp, re.M))

    def test_every_chaos_lab_preset_has_a_backend_mapping(self):
        for preset in self.lab_presets:
            self.assertIn(preset, self.preset_fault, f"{preset} missing from PRESET_FAULT in api.js")
            self.assertIn(self.preset_fault[preset], self.backend, f"{preset} maps to an unknown fault type")

    def test_every_backend_test_case_is_in_chaos_lab(self):
        exposed = {self.preset_fault[p] for p in self.lab_presets}
        self.assertEqual(self.backend - exposed, set())

    def test_every_backend_test_case_has_an_experiments_label(self):
        self.assertEqual(self.backend - self.type_info, set())
        self.assertEqual(self.type_info - self.backend, set())

    def test_no_duplicate_chaos_lab_presets(self):
        self.assertEqual(len(self.lab_presets), len(set(self.lab_presets)))


if __name__ == "__main__":
    unittest.main()
