"""State snapshots, GitHub write conflicts, and configured storage paths."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scholar_state", ROOT / "scripts/scholar_state.py")
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)
KEY = "a" * 20


class StatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "version": 1,
            "pending": {
                KEY: {
                    "paper": {
                        "id": KEY,
                        "title": "A paper",
                        "url": "https://arxiv.org/abs/2309.06180",
                    },
                    "status": "pending_abstract",
                    "attempts": 3,
                    "first_pending_at": 10,
                }
            },
            "expired": {},
            "retries": {KEY: {"attempts": 3, "last_attempt_at": 100, "next_retry_at": 500}},
            "source_limits": {"semantic_scholar": {"cooldown_until": 500, "failures": 1}},
        }
        self.storage = state.StateStorageConfig(branch="test/state-queue", file="queue.json")
        self.remote = state.StateBranch("owner/repo", "secret-test-token", self.storage)

    def test_queue_and_retry_roundtrip_without_abstract_cache(self):
        expired_key = "b" * 20
        expired = copy.deepcopy(self.snapshot["pending"][KEY])
        expired["paper"]["id"] = expired_key
        expired.update(expired_at=600, expiration_reason="max_attempts")
        self.snapshot["expired"][expired_key] = expired
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            state.restore(directory, self.snapshot)
            self.assertEqual(state.collect(directory), self.snapshot)
            self.assertFalse(list((directory / "abstracts").glob("*.json")))
            state.atomic_json(directory / "abstracts/cached.json", {"abstract": "not state"})
            state.atomic_json(directory / "last-run.json", {"diagnostic": "not state"})
            (directory / ".env").write_text("SECRET=not-state")
            self.assertEqual(state.collect(directory), self.snapshot)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                state.restore(directory, self.snapshot)
            state.atomic_json(directory / "pending-papers.json", {})
            self.assertEqual(state.collect(directory)["retries"], {})
            self.assertEqual(state.collect(directory)["expired"], {expired_key: expired})
        self.snapshot["pending"][KEY]["attempts"] = 0
        self.snapshot["retries"][KEY].update(attempts=0, last_attempt_at=0)
        self.snapshot["source_limits"]["arxiv_web"] = {"cooldown_until": 800, "failures": 1}
        with tempfile.TemporaryDirectory() as temp:
            state.restore(Path(temp), self.snapshot)
            self.assertEqual(state.collect(Path(temp)), self.snapshot)

    def test_invalid_state_and_missing_remote_fail_without_empty_fallback(self):
        invalid = copy.deepcopy(self.snapshot)
        invalid["pending"] = {"../../escape": invalid["pending"][KEY]}
        for snapshot in (invalid, {"version": 2}, dict(self.snapshot, pending=[])):
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    state.restore(Path(temp), snapshot)
                self.assertEqual(list(Path(temp).iterdir()), [])
        for status in (403, 404, 500):
            with self.subTest(status=status), patch.object(state.requests, "request") as request:
                request.return_value.status_code = status
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                    self.remote.head()
                self.assertEqual(request.call_args.args[0], "GET")
        with patch.object(
            state.requests, "request", side_effect=requests.ConnectionError("secret-test-token")
        ):
            with self.assertRaises(RuntimeError) as error:
                self.remote.head()
            self.assertNotIn("secret-test-token", str(error.exception))

    def test_save_is_verified_and_conflicts_never_force_overwrite(self):
        empty = dict(self.snapshot, pending={}, retries={})
        self.remote.api = Mock(
            side_effect=[
                {"object": {"sha": "old"}},
                empty,
                {"sha": "tree"},
                {"sha": "new"},
                {},
                {"object": {"sha": "new"}},
                self.snapshot,
            ]
        )
        self.assertEqual(self.remote.write(self.snapshot, "old"), "new")
        calls = self.remote.api.call_args_list
        tree = calls[2].kwargs["data"]["tree"]
        self.assertEqual([row["path"] for row in tree], [self.storage.file])
        self.assertEqual(calls[0].args, ("GET", f"/git/ref/heads/{self.storage.branch}"))
        self.assertEqual(calls[1].args, ("GET", f"/contents/{self.storage.file}?ref=old"))
        self.assertEqual(json.loads(tree[0]["content"]), self.snapshot)
        self.assertEqual(calls[3].kwargs["data"]["parents"], ["old"])
        self.assertEqual(calls[4].kwargs["data"], {"sha": "new", "force": False})
        self.assertEqual(calls[4].args, ("PATCH", f"/git/refs/heads/{self.storage.branch}"))
        self.assertIn("Signed-off-by:", calls[3].kwargs["data"]["message"])
        self.remote.api = Mock(return_value={"object": {"sha": "someone-else"}})
        with self.assertRaisesRegex(RuntimeError, "changed since restore"):
            self.remote.write(self.snapshot, "old")
        self.remote.api.assert_called_once()
        for failure in (RuntimeError("HTTP 422"), None):
            with self.subTest(failure=failure):
                replies = [{"object": {"sha": "old"}}, empty, {"sha": "tree"}, {"sha": "new"}]
                replies += [failure] if failure else [{}, {"object": {"sha": "new"}}, empty]
                self.remote.api = Mock(side_effect=replies)
                with self.assertRaises(RuntimeError):
                    self.remote.write(self.snapshot, "old")
                self.assertFalse(self.remote.api.call_args_list[4].kwargs["data"]["force"])
        self.remote.api = Mock(side_effect=[{"object": {"sha": "old"}}, self.snapshot])
        self.assertEqual(self.remote.write(self.snapshot, "old"), "old")
        self.assertEqual(self.remote.api.call_count, 2)

    def test_save_requires_an_existing_restored_revision(self):
        self.remote.api = Mock()
        with self.assertRaises(RuntimeError):
            self.remote.write(self.snapshot, None)
        self.remote.api.assert_not_called()
        self.remote.api.side_effect = RuntimeError("HTTP 404")
        with self.assertRaises(RuntimeError):
            self.remote.write(self.snapshot, "old")
        self.remote.api.assert_called_once_with("GET", f"/git/ref/heads/{self.storage.branch}")
        with patch.dict(os.environ, {"GITHUB_REF": f"refs/heads/{self.storage.branch}"}):
            with self.assertRaisesRegex(RuntimeError, "source branch"):
                state.StateBranch("owner/repo", "secret-test-token", self.storage)

    def test_cli_uses_configured_directory_for_restore_save_and_workflow(self):
        config = state.load_config(str(ROOT / "config/config.example.yml"))
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "custom queue"
            config.state_dir = str(directory)
            output = Path(temp) / "outputs"
            with (
                patch.object(state, "load_config", return_value=config),
                patch.object(state, "StateBranch") as factory,
                patch.object(state, "report"),
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_REPOSITORY": "owner/repo",
                        "GH_TOKEN": "test",
                        "GITHUB_OUTPUT": str(output),
                    },
                ),
            ):
                remote = factory.return_value
                remote.branch = config.state_storage.branch
                remote.file = config.state_storage.file
                remote.head.return_value = "baseline"
                remote.read.return_value = self.snapshot
                with patch.object(sys, "argv", ["scholar_state.py", "restore"]):
                    state.main()
                self.assertEqual(state.collect(directory), self.snapshot)
                self.assertEqual(output.read_text().strip(), f"state_dir={directory}")
                self.assertEqual(
                    json.loads((directory / "restored-revision.json").read_text())["revision"],
                    "baseline",
                )
                with patch.object(sys, "argv", ["scholar_state.py", "save"]):
                    state.main()
                remote.write.assert_called_once_with(self.snapshot, "baseline")
