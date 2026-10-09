import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import experiment_generator, failure_discovery

BASE_PROFILE = {
    "execution_status": "SUPPORTED",
    "adapter": "python_generic_http",
    "entrypoint": "app.py",
    "components": {
        "http_endpoints": [{"method": "GET", "path": "/health"}, {"method": "POST", "path": "/tasks"}],
        "env_vars": ["PORT"],
        "filesystem_paths": [],
        "subprocess_call_count": 0,
        "database_signals": [],
        "detected_port": None,
    },
}


class TestExperimentGenerator(unittest.TestCase):
    def test_no_database_signal_means_no_database_experiments(self):
        fps = failure_discovery.discover_failure_points(BASE_PROFILE, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(BASE_PROFILE, fps)
        self.assertFalse(any(e["fault_type"] == "db_connection_refused" for e in exps),
                          "no DB detected -> must not generate DB experiments (spec section 16)")

    def test_database_signal_generates_database_experiment(self):
        profile = dict(BASE_PROFILE)
        profile["components"] = dict(BASE_PROFILE["components"])
        profile["components"]["database_signals"] = ["PostgreSQL"]
        fps = failure_discovery.discover_failure_points(profile, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(profile, fps)
        self.assertTrue(any(e["fault_type"] == "db_connection_refused" for e in exps))

    def test_port_env_var_excluded_from_missing_env_var(self):
        fps = failure_discovery.discover_failure_points(BASE_PROFILE, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(BASE_PROFILE, fps)
        port_env_experiments = [e for e in exps if e["fault_type"] == "missing_env_var"
                                 and e["parameters"].get("env_var") == "PORT"]
        self.assertEqual(port_env_experiments, [],
                          "PORT is the harness's own control variable and must never be fault-injected")

    def test_bounded_by_max_experiments(self):
        profile = dict(BASE_PROFILE)
        profile["components"] = dict(BASE_PROFILE["components"])
        profile["components"]["env_vars"] = [f"VAR_{i}" for i in range(30)]  # force a huge failure surface
        fps = failure_discovery.discover_failure_points(profile, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(profile, fps)
        self.assertLessEqual(len(exps), experiment_generator.MAX_EXPERIMENTS)

    def test_not_executable_project_generates_nothing(self):
        profile = dict(BASE_PROFILE)
        profile["execution_status"] = "ANALYZED_BUT_NOT_EXECUTABLE"
        fps = failure_discovery.discover_failure_points(profile, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(profile, fps)
        self.assertEqual(exps, [])

    def test_body_fault_experiments_target_a_post_path_when_known(self):
        fps = failure_discovery.discover_failure_points(BASE_PROFILE, "/tmp/nonexistent")
        exps = experiment_generator.generate_experiments(BASE_PROFILE, fps)
        malformed = next(e for e in exps if e["fault_type"] == "malformed_request")
        self.assertEqual(malformed["parameters"]["candidate_paths"][0], "/tasks")


if __name__ == "__main__":
    unittest.main(verbosity=2)
