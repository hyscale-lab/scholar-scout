"""
MIT License

Copyright (c) 2024 Dmitrii Ustiugov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
"""

import email
import os
import tempfile
import unittest
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.config import load_config
from scholar_scout.classifier import ScholarClassifier


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "Live services require explicit opt-in")
class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv(Path(__file__).with_name(".env.test"))
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("Missing GEMINI_API_KEY for live classification")
        state = tempfile.TemporaryDirectory(prefix="scholar-scout-test-")
        cls.addClassCleanup(state.cleanup)
        cls.config = load_config(str(Path(__file__).with_name("test_config.yml")))
        cls.config.state_dir = state.name
        cls.classifier = ScholarClassifier(cls.config)

    def test_reference_paper_abstract_and_classification(self):
        message = email.message_from_string("""From: scholaralerts-noreply@google.com
Subject: new articles
Content-Type: text/html; charset=utf-8

<h3><a href="https://arxiv.org/abs/2309.06180">Efficient Memory Management for Large Language Model Serving with PagedAttention</a></h3>
<div>Woosuk Kwon - arXiv, 2023</div>
<div class="gse_alrt_sni">Incomplete alert snippet...</div>
""")
        results = self.classifier.classify_papers([message])
        self.assertEqual(len(results), 1, self.classifier.diagnostics)
        self.assertEqual(self.classifier.pending, {})
        paper, _ = results[0]
        self.assertIn("PagedAttention", paper.title)
        self.assertGreaterEqual(len(paper.abstract), 200)
        decisions = self.classifier.diagnostics[0]["decisions"]
        self.assertEqual(set(decisions), set(self.classifier.topic_classifier.topics))
        self.assertTrue(all(d["decision"] in ("match", "no_match") for d in decisions.values()))
