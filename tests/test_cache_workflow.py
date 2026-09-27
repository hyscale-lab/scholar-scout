"""Run cache reporting scripts without contacting GitHub."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CacheWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.load(
            (ROOT / ".github/workflows/scholar_classifier.yml").read_text(), Loader=yaml.BaseLoader
        )
        cls.steps = {
            step["name"]: step
            for step in workflow["jobs"]["run-classifier"]["steps"]
            if "name" in step
        }

    def run_report(self, name, **values):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            result = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    self.steps[name]["run"],
                ],
                env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary), **values),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, summary.read_text()

    def test_restore_distinguishes_hit_miss_and_failure(self):
        for outcome, key, success, marker in (
            ("success", "previous-run-key", True, "previous-run-key"),
            ("success", "", True, "cache miss"),
            ("failure", "", False, "failed"),
        ):
            with self.subTest(outcome=outcome, key=key):
                result, summary = self.run_report(
                    "Report state restoration", RESTORE_OUTCOME=outcome, RESTORED_KEY=key
                )
                self.assertEqual(result.returncode == 0, success)
                self.assertIn(marker, summary)
                if not success:
                    self.assertIn("::error::", result.stdout)
                elif not key:
                    self.assertIn("::warning::", result.stdout)
                else:
                    self.assertNotIn("cache miss", summary)

    def test_save_success_requires_exact_key_confirmation(self):
        save = self.steps["Save abstract and pending state"]
        verify = self.steps["Verify saved state cache"]
        self.assertEqual(save["with"]["key"], verify["with"]["key"])
        self.assertEqual(save["with"]["path"], verify["with"]["path"])
        self.assertEqual(verify["with"]["lookup-only"], "true")
        self.assertNotIn("restore-keys", verify["with"])
        result, summary = self.run_report(
            "Report state persistence",
            SAVE_OUTCOME="success",
            VERIFY_OUTCOME="success",
            SAVED_KEY="current-key",
            STATE_CACHE_KEY="current-key",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("**confirmed**", summary)

    def test_unconfirmed_save_fails_even_after_warning_only_action(self):
        for save, verify, key in (
            ("failure", "success", "current-key"),
            ("success", "success", ""),
            ("success", "success", "old-key"),
            ("success", "failure", ""),
        ):
            with self.subTest(save=save, verify=verify, key=key):
                result, summary = self.run_report(
                    "Report state persistence",
                    SAVE_OUTCOME=save,
                    VERIFY_OUTCOME=verify,
                    SAVED_KEY=key,
                    STATE_CACHE_KEY="current-key",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("::error::", result.stdout)
                self.assertIn("**unconfirmed**", summary)


if __name__ == "__main__":
    unittest.main()
