"""Offline classification and retry behavior."""

import email
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout.classifier import ScholarClassifier
from scholar_scout.abstract_sources import AbstractResolver
from scholar_scout.config import ResearchTopic, load_config
from scholar_scout.topic_classification import TopicClassifier

ROOT = Path(__file__).resolve().parents[1]
ABSTRACT = "We reduce KV cache memory during LLM serving. " * 8
TOPIC_NAMES = (
    "LLM Inference",
    "Serverless Computing",
    "Agentic Execution Environment",
    "Video & Embodied Intelligence",
    "Sustainable Computing",
)


def response(
    matches=("LLM Inference",),
    quote="We reduce KV cache memory during LLM serving.",
    topics=TOPIC_NAMES,
):
    rows = [
        {
            "topic": name,
            "decision": "match" if name in matches else "no_match",
            "evidence": [quote] if name in matches else [],
            "reason": "Systems contribution.",
        }
        for name in topics
    ]
    return SimpleNamespace(
        text=json.dumps({"decisions": rows}), candidates=[SimpleNamespace(finish_reason="STOP")]
    )


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = load_config(str(ROOT / "config/config.example.yml"))
        self.config.state_dir = temp.name
        self.config.gemini.api_key = "test-key"
        client = patch("scholar_scout.classifier.genai.Client")
        self.client_factory = client.start()
        self.addCleanup(client.stop)
        network = patch(
            "requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")
        )
        network.start()
        self.addCleanup(network.stop)
        self.app = ScholarClassifier(self.config)
        self.client = self.client_factory.return_value
        self.client.models.generate_content.return_value = response()
        self.record = {
            "title": "Paper One",
            "authors": ["Alice Author"],
            "abstract": ABSTRACT,
            "url": "https://arxiv.org/abs/2601.00001",
            "venue": "arXiv",
            "source": "fixture",
        }
        self.app.resolver.resolve = Mock(return_value=(self.record, []))
        self.mail = email.message_from_string(
            'Content-Type: text/html; charset=utf-8\n\n<h3><a href="https://arxiv.org/abs/2601.00001">Paper One</a></h3><div>A Author - arXiv, 2026</div><div class="gse_alrt_sni">Incomplete snippet…</div>'
        )

    def test_full_abstract_classification_preserves_independent_matches(self):
        self.mail.set_payload(
            self.mail.get_payload().replace(
                "https://arxiv.org/abs/2601.00001",
                "https://scholar.google.co.uk/scholar_url?url=https%3A%2F%2Farxiv.org%2Fabs%2F2601.00001",
            )
        )
        self.client.models.generate_content.return_value = response(
            matches=("LLM Inference", "Video & Embodied Intelligence")
        )
        results = self.app.classify_papers([self.mail])
        self.assertEqual(
            self.app.resolver.resolve.call_args.args[0]["url"],
            "https://arxiv.org/abs/2601.00001",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(
            [topic.name for topic in results[0][1]],
            ["LLM Inference", "Video & Embodied Intelligence"],
        )
        call = self.client.models.generate_content.call_args.kwargs
        self.assertEqual(json.loads(call["contents"]), {"title": "Paper One", "abstract": ABSTRACT})
        self.assertEqual(results[0][0].authors, ["Alice Author"])
        self.client.models.embed_content.assert_not_called()
        self.assertEqual(self.app.pending, {})

    def test_no_match_is_not_pending_or_forced_into_a_topic(self):
        self.client.models.generate_content.return_value = response(matches=())
        self.assertEqual(self.app.classify_papers([self.mail])[0][1], [])
        self.assertEqual(self.app.pending, {})

    def test_policy_is_authoritative_and_unknown_topics_fail(self):
        policies = json.loads((ROOT / "config/topic_policy.json").read_text())
        topic = ResearchTopic(
            name="LLM Inference", slack_users=[], description="Ignored legacy scope"
        )
        classifier = TopicClassifier(self.client, "test-model", [topic])
        self.assertEqual(
            json.loads(classifier.prompt.split("\nTOPICS:\n")[1]),
            {topic.name: policies[topic.name]},
        )
        self.assertNotIn("Ignored legacy scope", classifier.prompt)
        topic.name = "Unknown Topic"
        with self.assertRaises(ValueError):
            TopicClassifier(self.client, "test-model", [topic])
        self.client.models.generate_content.assert_not_called()
        topic.name = "Custom Systems Topic"
        custom_policy = {topic.name: policies["LLM Inference"]}
        read_text = Path.read_text

        def read_policy(path, *args, **kwargs):
            if path.name == "topic_policy.json":
                return json.dumps(custom_policy)
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_policy):
            classifier = TopicClassifier(self.client, "test-model", [topic])
        self.assertEqual(json.loads(classifier.prompt.split("\nTOPICS:\n")[1]), custom_policy)
        self.client.models.generate_content.return_value = response(
            matches=(topic.name,), topics=(topic.name,)
        )
        decisions = classifier.classify(SimpleNamespace(**self.record))
        self.assertEqual(set(decisions), {topic.name})
        self.assertEqual(decisions[topic.name]["decision"], "match")

    def test_invalid_output_retries_then_stays_pending(self):
        invalid_decision = response()
        rows = json.loads(invalid_decision.text)
        rows["decisions"][0]["decision"] = "maybe"
        invalid_decision.text = json.dumps(rows)
        truncated = response()
        truncated.candidates[0].finish_reason = "MAX_TOKENS"
        duplicate = response()
        rows = json.loads(duplicate.text)
        rows["decisions"][-1]["topic"] = "LLM Inference"
        duplicate.text = json.dumps(rows)
        missing = response()
        rows = json.loads(missing.text)
        rows["decisions"].pop()
        missing.text = json.dumps(rows)
        unknown = response()
        rows = json.loads(unknown.text)
        rows["decisions"][0]["topic"] = "Unknown Topic"
        unknown.text = json.dumps(rows)
        for label, invalid in (
            ("decision", invalid_decision),
            ("quote", response(quote="invented")),
            ("truncated", truncated),
            ("duplicate", duplicate),
            ("missing", missing),
            ("unknown", unknown),
        ):
            with self.subTest(label=label):
                self.app.pending.clear()
                self.client.models.generate_content.reset_mock()
                self.client.models.generate_content.return_value = invalid
                self.assertEqual(self.app.classify_papers([self.mail]), [])
                self.assertEqual(self.client.models.generate_content.call_count, 2)
                self.assertEqual(next(iter(self.app.pending.values()))["status"], "pending_model")

    def test_invalid_then_valid_response_recovers(self):
        self.client.models.generate_content.side_effect = [response(quote="invented"), response()]
        self.assertEqual(len(self.app.classify_papers([self.mail])), 1)
        self.assertEqual(self.client.models.generate_content.call_count, 2)
        self.assertEqual(self.app.pending, {})

    def test_missing_abstract_survives_restart_without_original_email(self):
        self.mail.set_payload(
            self.mail.get_payload()
            + '<a href="https://scholar.google.co.uk/citations?user=profile1">Author</a>'
        )
        self.app.resolver.resolve.return_value = (None, [])
        self.assertEqual(self.app.classify_papers([self.mail]), [])
        self.client.models.generate_content.assert_not_called()
        restarted = ScholarClassifier(self.config)
        self.assertEqual(
            next(iter(restarted.pending.values()))["paper"]["scholar_profiles"], ["profile1"]
        )
        restarted.resolver.resolve = Mock(return_value=(self.record, []))
        self.assertEqual(len(restarted.classify_papers([])), 1)
        self.assertEqual(ScholarClassifier(self.config).pending, {})

    def test_retry_limits_survive_restart_and_do_not_requeue_expired_papers(self):
        self.config.pending_policy.max_attempts = 2
        for failure in ("abstract", "model"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                self.config.state_dir = temp
                app = ScholarClassifier(self.config)
                app.resolver.resolve = Mock(
                    return_value=(None if failure == "abstract" else self.record, [])
                )
                self.client.models.generate_content.side_effect = TimeoutError()
                app.classify_papers([self.mail])
                row = next(iter(app.pending.values()))
                self.assertEqual(row["attempts"], 1)
                first_pending_at = row["first_pending_at"]
                restarted = ScholarClassifier(self.config)
                restarted.resolver.resolve = app.resolver.resolve
                restarted.classify_papers([])
                self.assertEqual(restarted.pending, {})
                expired = next(iter(restarted.newly_expired.values()))
                self.assertEqual(expired["attempts"], 2)
                self.assertEqual(expired["first_pending_at"], first_pending_at)
                self.assertEqual(expired["expiration_reason"], "max_attempts")
                restarted = ScholarClassifier(self.config)
                restarted.resolver.resolve = Mock()
                self.assertEqual(restarted.classify_papers([self.mail]), [])
                restarted.resolver.resolve.assert_not_called()
                self.assertEqual(restarted.newly_expired, {})
                self.assertEqual(len(restarted.expired), 1)

    def test_age_limit_stops_before_network_and_cooldown_does_not_count(self):
        self.app.resolver = AbstractResolver(self.app.state_dir / "abstracts")
        resolver = self.app.resolver
        resolver.recovery.max_rounds = 0
        resolver.limiter.clock = lambda: 100
        for service in ("arxiv", "arxiv_web", "semantic_scholar", "crossref"):
            resolver.limiter.defer(service, "60")
        with patch("scholar_scout.classifier.time.time", return_value=100):
            self.app.classify_papers([self.mail])
        self.assertTrue(self.app.run_failed)
        self.client.models.generate_content.assert_not_called()
        self.assertEqual(ScholarClassifier(self.config).pending, self.app.pending)
        row = next(iter(self.app.pending.values()))
        self.assertEqual(row["attempts"], 0)
        self.app.resolver.resolve = Mock(return_value=(None, []))
        self.app.resolver.retry_deferred = True
        with patch("scholar_scout.classifier.time.time", return_value=200):
            self.app.classify_papers([])
        self.assertEqual(next(iter(self.app.pending.values()))["attempts"], 0)
        self.app.resolver.resolve.reset_mock()
        deadline = row["first_pending_at"] + self.config.pending_policy.max_age_days * 86400
        with patch("scholar_scout.classifier.time.time", return_value=deadline):
            self.app.classify_papers([])
        self.app.resolver.resolve.assert_not_called()
        self.assertEqual(self.app.pending, {})
        self.assertEqual(
            next(iter(self.app.newly_expired.values()))["expiration_reason"], "max_age"
        )

    def test_api_failure_defers_without_retry_or_secret_logging(self):
        self.client.models.generate_content.side_effect = RuntimeError("secret-token")
        with self.assertLogs("scholar_scout.classifier", level="WARNING") as logs:
            self.assertEqual(self.app.classify_papers([self.mail]), [])
        self.assertNotIn("secret-token", str(logs.output))
        self.assertEqual(self.client.models.generate_content.call_count, 1)
        self.assertEqual(next(iter(self.app.pending.values()))["status"], "pending_model")

    def test_api_key_and_service_account_authentication(self):
        self.assertEqual(self.client_factory.call_args.kwargs["api_key"], "test-key")
        self.assertNotIn("credentials", self.client_factory.call_args.kwargs)
        self.config.gemini.api_key = {"type": "service_account"}
        with patch("google.oauth2.service_account.Credentials.from_service_account_info") as make:
            make.return_value.project_id = "test-project"
            ScholarClassifier(self.config)
        args = self.client_factory.call_args.kwargs
        self.assertTrue(args["vertexai"])
        self.assertEqual(args["project"], "test-project")
        self.assertEqual(args["credentials"], make.return_value)
        self.assertNotIn("api_key", args)

    def test_duplicate_pending_papers_merge_metadata_across_restarts(self):
        self.app.resolver.resolve.return_value = (None, [])
        self.app.classify_papers([self.mail])
        new_url = "https://www.usenix.org/conference/osdi26/presentation/author"
        updated = email.message_from_string(
            self.mail.as_string()
            .replace(self.record["url"], new_url)
            .replace("A Author -", "Alice Author, B Writer -")
        )
        restarted = ScholarClassifier(self.config)
        restarted.resolver.resolve = Mock(return_value=(None, []))
        restarted.classify_papers([updated, updated])
        candidate = restarted.resolver.resolve.call_args.args[0]
        self.assertEqual(candidate["urls"], [self.record["url"], new_url])
        self.assertEqual(candidate["authors"], ["A Author", "Alice Author", "B Writer"])
        restarted.resolver.resolve.assert_called_once()
        stored = ScholarClassifier(self.config).pending
        self.assertEqual(next(iter(stored.values()))["paper"], candidate)

    def test_entrypoint_reports_failures_without_misleading_notifications(self):
        spec = importlib.util.spec_from_file_location(
            "entrypoint", ROOT / "scripts/run_classifier.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.client.models.generate_content.return_value = response(matches=())
        for case in ("mail_failure", "outage", "missing_abstract", "no_matches", "empty_mailbox"):
            with self.subTest(case=case):
                self.app.pending.clear()
                self.app.resolver.had_source_failure = case == "outage"
                self.app.resolver.retry_deferred = case == "outage"
                self.app.resolver.resolve.return_value = (
                    self.record if case == "no_matches" else None,
                    [],
                )
                with (
                    patch.object(sys, "argv", ["run_classifier.py"]),
                    patch.object(module, "load_dotenv"),
                    patch.object(module, "load_config", return_value=self.config),
                    patch.object(module, "EmailClient") as email_client,
                    patch.object(module, "ScholarClassifier", return_value=self.app) as classifier,
                    patch.object(module, "SlackNotifier") as notifier,
                ):
                    client = email_client.return_value.__enter__.return_value
                    client.fetch_scholar_alerts.return_value = (
                        [] if case == "empty_mailbox" else [self.mail]
                    )
                    if case == "mail_failure":
                        client.fetch_scholar_alerts.side_effect = RuntimeError(
                            "Failed to fetch email"
                        )
                        with self.assertRaisesRegex(RuntimeError, "Failed to fetch email"):
                            module.main()
                        client.delete_old_emails.assert_not_called()
                        classifier.assert_not_called()
                        notifier.assert_not_called()
                        continue
                    if case == "outage":
                        with self.assertRaisesRegex(RuntimeError, "pending state retained"):
                            module.main()
                        notifier.return_value.notify_matches.assert_not_called()
                        self.assertTrue(json.loads(self.app.pending_path.read_text()))
                    else:
                        module.main()
                    notify = notifier.return_value
                    self.assertEqual(
                        notify.send_weekly_update.called, case in ("no_matches", "empty_mailbox")
                    )
                    self.assertEqual(
                        notify.send_pending_update.call_args.kwargs["run_failed"], case == "outage"
                    )


if __name__ == "__main__":
    unittest.main()
