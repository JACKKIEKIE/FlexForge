"""Run with: python -m unittest test_flexforge.py"""
import tempfile
import unittest
from pathlib import Path
from flexforge_demo import (
    make_jobs, greedy_schedule, build_fixed, validate_schedule,
    FAIL_TIME, DOWN_TIME, demo, metrics,
)


class TestFlexForge(unittest.TestCase):
    def test_reproducible_seed(self):
        self.assertEqual(make_jobs(7), make_jobs(7))
        self.assertNotEqual(make_jobs(7), make_jobs(8))

    def test_machine_failure_and_recovery(self):
        jobs = make_jobs(7)
        before = greedy_schedule(jobs)
        validate_schedule(jobs, before)
        fixed, interrupted = build_fixed(before, 0, FAIL_TIME)
        self.assertGreater(len(fixed), 0)
        self.assertIn((1, 1), interrupted)
        after = greedy_schedule(jobs, fixed, FAIL_TIME, 0, DOWN_TIME)
        validate_schedule(jobs, after, fixed, FAIL_TIME, 0, DOWN_TIME)
        self.assertEqual(len(after), len(before))
        self.assertNotEqual(before, after)

    def test_seed_sweep_invariants(self):
        for seed in range(100):
            jobs = make_jobs(seed)
            before = greedy_schedule(jobs)
            frozen, _ = build_fixed(before, 0, FAIL_TIME)
            for mode in ("edd", "fifo"):
                after = greedy_schedule(jobs, frozen, FAIL_TIME, 0, DOWN_TIME, mode)
                validate_schedule(jobs, after, frozen, FAIL_TIME, 0, DOWN_TIME)
                self.assertEqual(metrics(jobs, after)["completed_jobs"], len(jobs))

    def test_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            report = demo(7, "heuristic", 2.0, Path(directory))
            self.assertEqual(report["status"], "HEURISTIC")
            for name in ("baseline.csv", "recovery_edd.csv", "recovery_selected.csv", "summary.json"):
                self.assertGreater((Path(directory) / name).stat().st_size, 10)


if __name__ == "__main__":
    unittest.main()