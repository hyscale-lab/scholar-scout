
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "conference_scout"))

from config import load_config
from generative_classification import GeminiGenerativeClassifier


class GenerativeClassificationTests(unittest.TestCase):
    def setUp(self):
        config = load_config(
            str(PROJECT_ROOT / "config" / "config.example.yml")
        )
        self.client = Mock()
        self.classifier = GeminiGenerativeClassifier(config, self.client)

    def test_all_configured_categories_are_present(self):
        expected = {
            "LLM Inference",
            "Serverless Computing",
            "Agentic Execution Environment",
            "Video & Embodied Intelligence",
            "Sustainable Computing",
        }

        self.assertEqual(set(self.classifier.topics), expected)

    def test_no_matching_category(self):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text='{"categories": []}'
        )

        result = self.classifier.classify(
            "A paper outside the configured topics",
            "An unrelated research contribution.",
        )

        self.assertEqual(result, [])

    def test_unknown_category_is_rejected(self):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text='{"categories": ["Unknown Category"]}'
        )

        with self.assertRaises(ValueError):
            self.classifier.classify("Example paper", "Example abstract.")

    def test_invalid_json_is_rejected(self):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text="not valid json"
        )

        with self.assertRaises(ValueError):
            self.classifier.classify("Example paper", "Example abstract.")

    def test_empty_paper_skips_api_call(self):
        result = self.classifier.classify("", "")

        self.assertEqual(result, [])
        self.client.models.generate_content.assert_not_called()

    def test_api_error_propagates(self):
        self.client.models.generate_content.side_effect = RuntimeError(
            "Simulated API failure"
        )

        with self.assertRaises(RuntimeError):
            self.classifier.classify("Example paper", "Example abstract.")


if __name__ == "__main__":
    unittest.main()
