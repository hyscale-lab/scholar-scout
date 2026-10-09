"""Offline source resolution, identity checks, and request safety."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout import abstract_sources as sources

ABSTRACT = "This system improves scheduling efficiency with a measured implementation. " * 8


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.data = json.dumps(data or {}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.data


class AbstractSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.resolver = sources.AbstractResolver(self.root / "cache", state_dir=self.root / "state")
        self.resolver.recovery.max_rounds = 0
        self.resolver.keys = {
            "IEEE_API_KEY": "secret-ieee",
            "SEMANTIC_SCHOLAR_API_KEY": "secret-s2",
        }
        self.paper = {
            "id": "sample",
            "title": "Paper One",
            "url": "https://doi.org/10.1145/123.456",
            "email_metadata": "A Author - Conference, 2026",
        }
        self.record = {
            "title": "Paper One",
            "abstract": ABSTRACT,
            "authors": ["Alice Author"],
            "doi": "10.1145/123.456",
            "source": "fixture",
            "url": self.paper["url"],
        }

    def test_identity_rejects_conflicts_but_accepts_name_normalization(self):
        self.assertTrue(sources.identity_matches(self.paper, self.record))
        for changes in (
            {"title": "Wrong paper"},
            {"doi": "10.1145/123.999"},
            {"authors": ["Another Person"]},
            {"authors": []},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(sources.identity_matches(self.paper, dict(self.record, **changes)))
        for paper, record in (
            (
                {"title": "Café Systems", "email_metadata": "JF Martínez… - Venue"},
                {"title": "Cafe Systems", "authors": ["Jose F. Martinez"]},
            ),
            (
                {"title": "Paper One", "email_metadata": "T Li, Q Zhang… - Venue"},
                dict(self.record, authors=["Li, Tianyu", "Zhang, Qingang"]),
            ),
        ):
            with self.subTest(paper=paper):
                self.assertTrue(sources.identity_matches(paper, record))

    def test_missing_or_truncated_abstract_is_not_usable(self):
        for text in (None, "", "too short", ABSTRACT + "…", ABSTRACT + "View full abstract"):
            self.assertFalse(sources.is_usable_abstract(dict(self.record, abstract=text)))
        self.assertTrue(sources.is_usable_abstract(self.record))
        description = dict(
            self.record,
            source="Google Scholar Description",
            abstract=ABSTRACT + "…",
            truncated=True,
        )
        self.assertTrue(sources.is_usable_abstract(description))
        self.assertFalse(sources.is_usable_abstract(dict(description, abstract="too short…")))

    def test_ieee_links_resolve_article_metadata(self):
        payload = {
            "articles": [
                {
                    "title": "Paper One",
                    "abstract": ABSTRACT,
                    "article_number": "11684999",
                    "doi": "10.1109/example",
                    "authors": {"authors": [{"full_name": "Alice Author"}]},
                }
            ]
        }
        for url in (
            "https://ieeexplore.ieee.org/iel8/40/123/11684999.pdf",
            "https://ieeexplore.ieee.org/abstract/document/11684999/",
            "https://ieeexplore.ieee.org/document/11684999",
            "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=11684999",
        ):
            with (
                self.subTest(url=url),
                patch.object(self.resolver, "get", return_value=json.dumps(payload)) as get,
            ):
                rows = self.resolver.ieee(dict(self.paper, url=url))
            self.assertEqual(get.call_args.args[1]["article_number"], "11684999")
            self.assertEqual(rows[0]["title"], "Paper One")
            self.assertEqual(rows[0]["authors"], ["Alice Author"])
            self.assertEqual(rows[0]["abstract"], ABSTRACT)
            self.assertNotIn("apikey", rows[0]["url"])

    def test_publication_pages_extract_identity_matched_abstracts(self):
        page = (
            '<h1>Paper One</h1><meta name="citation_author" content="Alice Author">'
            '<div class="field-name-field-paper-description-long">' + ABSTRACT + "</div>"
        )
        program = (
            '<article class="node-paper"><h2>'
            '<a href="/conference/osdi26/presentation/author">Paper One</a></h2>'
            '<div class="field-name-field-paper-description">' + ABSTRACT + "</div></article>"
        )
        arxiv = (
            '<h1 class="title">Title: Paper One</h1>'
            '<div class="authors"><a>Alice Author</a></div>'
            '<blockquote class="abstract">Abstract: ' + ABSTRACT + "</blockquote>"
        )
        google = (
            '<meta name="citation_title" content="Paper One">'
            '<meta name="citation_author" content="Alice Author">'
            "<div><div><h2>Abstract</h2></div><div>" + ABSTRACT + "</div></div>"
        )
        google_url = "https://research.google/pubs/paper-one/"
        cases = [
            ("https://www.usenix.org/conference/osdi26/presentation/author", [page], True),
            ("https://www.usenix.org/system/files/osdi26-author.pdf", [program, page], True),
            (google_url, [google], True),
            (google_url, [google.replace("Paper One", "Wrong Paper")], False),
            (google_url, [google.replace("Alice Author", "Wrong Person")], False),
            (google_url, [google.replace("Abstract</h2>", "Overview</h2>")], False),
            (google_url, [google.replace(ABSTRACT, "Truncated snippet…")], False),
        ]
        for host in (
            "scholar.google.com",
            "scholar.google.co.uk",
            "scholar.google.co.jp",
            "redirect.example.org",
        ):
            cases.append(
                (
                    f"https://{host}/scholar_url?url=https%3A%2F%2Farxiv.org%2Fpdf%2F2601.00001",
                    [arxiv],
                    True,
                )
            )
        for index, (url, responses, accepted) in enumerate(cases):
            with (
                self.subTest(url=url, index=index),
                patch.object(self.resolver, "get", side_effect=responses) as get,
                patch.object(self.resolver, "crossref", return_value=[]),
                patch.object(self.resolver, "semantic_scholar", return_value=[]),
                patch.object(self.resolver, "arxiv", return_value=[]),
            ):
                record, _ = self.resolver.resolve(dict(self.paper, id=str(index), url=url))
            self.assertEqual(record is not None, accepted)
            if accepted:
                self.assertEqual(record["title"], "Paper One")
                self.assertEqual(record["authors"], ["Alice Author"])
                self.assertEqual(record["abstract"], ABSTRACT.strip())
            self.assertNotIn("scholar.google", get.call_args.args[0])
        profile = (
            '<a class="gsc_a_at" href="/citations?citation_for_view=profile1:paper1">Paper One</a>'
        )
        detail = (
            '<a id="gsc_oci_title">Paper One</a>'
            '<div class="gs_scl"><div class="gsc_oci_field">Authors</div>'
            '<div class="gsc_oci_value">Alice Author</div></div>'
            '<div class="gs_scl"><div class="gsc_oci_field">Description</div>'
            '<div class="gsc_oci_value">' + ABSTRACT + "…</div></div>"
        )
        paper = dict(self.paper, id="scholar", scholar_profiles=["profile1"])
        with (
            patch.object(self.resolver, "get", side_effect=[profile, detail]) as get,
            patch.object(self.resolver, "arxiv_html", return_value=[self.record]) as original,
            patch.object(self.resolver, "crossref", return_value=[self.record]) as crossref,
            patch.object(self.resolver, "semantic_scholar", return_value=[self.record]) as s2,
            patch.object(self.resolver, "arxiv", return_value=[self.record]) as arxiv_api,
        ):
            record, _ = self.resolver.resolve(paper)
        self.assertEqual(get.call_count, 2)
        for provider in (original, crossref, s2, arxiv_api):
            provider.assert_not_called()
        self.assertEqual(record["source"], "Google Scholar Description")
        self.assertTrue(record["truncated"])
        with patch.object(self.resolver, "get") as get:
            cached, _ = self.resolver.resolve(paper)
        get.assert_not_called()
        self.assertEqual(cached, record)
        with patch.object(
            self.resolver, "get", return_value=detail.replace("Alice Author", "Wrong Person")
        ) as get:
            self.assertEqual(self.resolver.scholar_description(paper), [])
        get.assert_called_once()  # The profile index is reused within the run.
        for index, result in enumerate(
            (
                [],
                [dict(self.record, title="Wrong Paper")],
                [dict(self.record, abstract="too short")],
                sources.SourceFailure("scholar_access_blocked"),
            )
        ):
            with (
                self.subTest(scholar_fallback=index),
                patch.object(self.resolver, "scholar_description", side_effect=[result]) as scholar,
                patch.object(self.resolver, "arxiv_html", return_value=[self.record]) as original,
            ):
                resolved, _ = self.resolver.resolve(dict(paper, id=f"scholar-fallback-{index}"))
            scholar.assert_called_once()
            original.assert_called_once()
            self.assertEqual(resolved["source"], self.record["source"])

    def test_crossref_doi_without_abstract_is_passed_to_s2(self):
        paper = dict(self.paper, url="https://example.org/paper")
        with (
            patch.object(self.resolver, "ieee", return_value=[]),
            patch.object(self.resolver, "usenix", return_value=[]),
            patch.object(self.resolver, "arxiv_html", return_value=[]),
            patch.object(self.resolver, "institutional", return_value=[]),
            patch.object(self.resolver, "crossref", return_value=[dict(self.record, abstract="")]),
            patch.object(self.resolver, "semantic_scholar", return_value=[self.record]) as s2,
        ):
            record, _ = self.resolver.resolve(paper)
        self.assertEqual(s2.call_args.args[0]["doi"], self.record["doi"])
        self.assertEqual(record["abstract"], ABSTRACT)
        self.assertNotIn("doi", paper)

    def test_s2_fallback_distinguishes_missing_wrong_and_rate_limited_records(self):
        record = {
            "title": "Paper One",
            "abstract": ABSTRACT,
            "authors": [{"name": "Alice Author"}],
            "externalIds": {"DOI": self.record["doi"]},
        }
        wrong = dict(record, title="Wrong Paper", externalIds={"DOI": "10.1145/999"})
        cases = (
            ("missing", [sources.SourceFailure("http_404"), json.dumps({"data": [record]})], True),
            ("wrong", [json.dumps(wrong), json.dumps({"data": [wrong]})], False),
            ("limited", [sources.SourceFailure("http_429", 5000)], None),
        )
        for label, responses, accepted in cases:
            with (
                self.subTest(label=label),
                patch.object(self.resolver, "get", side_effect=responses) as get,
            ):
                if accepted is None:
                    with self.assertRaises(sources.SourceFailure):
                        self.resolver.semantic_scholar(self.paper)
                    get.assert_called_once()
                else:
                    rows = self.resolver.semantic_scholar(self.paper)
                    self.assertEqual(
                        any(sources.identity_matches(self.paper, row) for row in rows), accepted
                    )
                    self.assertEqual(get.call_count, 2)
                    self.assertTrue(get.call_args.args[0].endswith("/search"))

    def test_requests_keep_credentials_on_allowed_hosts_and_out_of_errors(self):
        target = "https://arxiv.org/abs/2601.00001"
        wrapper = "https://scholar.google.de/scholar_url?url="
        nested = wrapper + sources.quote(wrapper + sources.quote(target, safe=""), safe="")
        self.assertEqual(sources.unwrap_scholar_url(nested), target)
        for url in (
            "https://example.org/paper?url=" + target,
            wrapper + "javascript:alert(1)",
            wrapper + "/relative/path",
            wrapper + "https://user:password@arxiv.org/abs/2601.00001",
            wrapper + "https://[invalid",
            wrapper + target + "&url=https://example.org/other",
            wrapper,
        ):
            with self.subTest(url=url):
                self.assertEqual(sources.unwrap_scholar_url(url), url)
        with (
            patch.object(self.resolver.limiter, "before"),
            patch.object(sources.requests, "get", return_value=Response()) as get,
        ):
            self.resolver.get("https://api.semanticscholar.org/graph/v1/paper/search")
            self.assertEqual(get.call_args.kwargs["headers"]["x-api-key"], "secret-s2")
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.resolver.get("https://ieeexploreapi.ieee.org/api/v1/search/articles")
            self.assertEqual(get.call_args.kwargs["params"]["apikey"], "secret-ieee")
            self.assertNotIn("x-api-key", get.call_args.kwargs["headers"])
            self.resolver.get("https://api.crossref.org/works")
            self.assertNotIn("apikey", get.call_args.kwargs["params"])
            self.assertNotIn("x-api-key", get.call_args.kwargs["headers"])
            self.resolver.get("https://research.google/pubs/paper-one/")
            self.assertNotIn("apikey", get.call_args.kwargs["params"])
            self.assertNotIn("x-api-key", get.call_args.kwargs["headers"])
            get.reset_mock()
            for url in (
                "https://localhost/",
                "http://api.crossref.org/works",
                "https://user:secret@api.crossref.org/works",
                "https://api.crossref.org:8443/works",
            ):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.resolver.get(url)
            get.assert_not_called()
            get.return_value = Response(status=302)
            with self.assertRaisesRegex(sources.SourceFailure, "http_302"):
                self.resolver.get("https://api.crossref.org/works")
            get.assert_called_once()
            get.side_effect = sources.requests.ConnectionError("apikey=secret-ieee")
            with self.assertRaises(sources.SourceFailure) as error:
                self.resolver.get("https://ieeexploreapi.ieee.org/api/v1/search/articles")
            self.assertEqual(str(error.exception), "transport_error")
            get.reset_mock(side_effect=True)
            get.return_value = Response(status=429)
            with self.assertRaisesRegex(sources.SourceFailure, "scholar_access_blocked"):
                self.resolver.get("https://scholar.google.com/citations")
            with self.assertRaisesRegex(sources.SourceFailure, "source_disabled_for_run"):
                self.resolver.get("https://scholar.google.com/citations")
            get.assert_called_once()
            self.assertNotIn("apikey", get.call_args.kwargs["params"])
            self.assertNotIn("x-api-key", get.call_args.kwargs["headers"])
        with patch.object(self.resolver, "get", return_value="<html>unusual traffic</html>"):
            with self.assertRaisesRegex(sources.SourceFailure, "scholar_access_blocked"):
                self.resolver.scholar_description(dict(self.paper, scholar_profiles=["profile2"]))

    def test_rate_limits_and_cooldown_survive_new_instances_and_metadata(self):
        now, sleeps = [100.0], []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        self.resolver.limiter = sources.SharedLimiter(self.root / "state", lambda: now[0], sleep)
        other = sources.SharedLimiter(self.root / "state", lambda: now[0], sleep)
        self.resolver.limiter.before("semantic_scholar")
        other.before("semantic_scholar")
        self.resolver.limiter.before("semantic_scholar")
        self.assertEqual(sleeps, [2.0, 2.0])
        with patch.object(
            sources.requests,
            "get",
            return_value=Response(status=429, headers={"Retry-After": "120"}),
        ) as get:
            with self.assertRaises(sources.SourceFailure):
                self.resolver.get("https://api.semanticscholar.org/graph/v1/paper/search")
            restarted = sources.AbstractResolver(
                self.root / "other-cache", state_dir=self.root / "state"
            )
            restarted.limiter = other
            with self.assertRaisesRegex(sources.SourceFailure, "cooldown_active"):
                restarted.get("https://api.semanticscholar.org/graph/v1/paper/DOI:test")
            get.assert_called_once()
        self.resolver.limiter.defer("ieee", "120")
        updated = dict(
            self.paper, urls=[self.paper["url"], "https://ieeexplore.ieee.org/document/11684999"]
        )
        with (
            patch.object(self.resolver, "usenix", return_value=[]),
            patch.object(self.resolver, "arxiv_html", return_value=[]),
            patch.object(self.resolver, "institutional", return_value=[]),
            patch.object(self.resolver, "crossref", return_value=[]),
            patch.object(self.resolver, "semantic_scholar", return_value=[]),
            patch.object(self.resolver, "arxiv", return_value=[]),
            patch.object(sources.requests, "get") as get,
        ):
            record, notes = self.resolver.resolve(updated)
        self.assertIsNone(record)
        self.assertIn("ieee: cooldown_active", notes)
        get.assert_not_called()
        self.assertTrue(self.resolver.retry_deferred)
        self.assertEqual(self.resolver.last_pending["attempts"], 0)
        self.assertNotIn("secret", (self.root / "state/limits.json").read_text())
        self.resolver.limiter.before("arxiv")
        self.resolver.limiter.defer("arxiv", "60")
        with patch.object(sources.requests, "get", return_value=Response()) as get:
            self.resolver.get("https://arxiv.org/abs/2309.06180")
            with self.assertRaisesRegex(sources.SourceFailure, "cooldown_active"):
                self.resolver.get("https://export.arxiv.org/api/query")
            get.assert_called_once()
        self.assertAlmostEqual(sleeps[-1], 3.1)

    def test_ambiguous_abstract_is_deferred_and_retried_when_due(self):
        def ambiguous_lookup(paper):
            self.resolver.get("https://ieeexploreapi.ieee.org/api/v1/search/articles")
            return [self.record, self.record]

        with (
            patch.object(sources.requests, "get", return_value=Response()),
            patch.object(self.resolver, "ieee", side_effect=ambiguous_lookup),
            patch.object(self.resolver, "usenix", return_value=[]),
            patch.object(self.resolver, "arxiv_html", return_value=[]),
            patch.object(self.resolver, "institutional", return_value=[]),
            patch.object(self.resolver, "crossref", return_value=[]),
            patch.object(self.resolver, "semantic_scholar", return_value=[]),
            patch.object(self.resolver, "arxiv", return_value=[]),
        ):
            record, _ = self.resolver.resolve(self.paper)
        self.assertIsNone(record)
        self.assertEqual(self.resolver.last_pending["attempts"], 1)
        self.assertFalse(self.resolver.retry_deferred)
        with patch.object(sources.requests, "get") as get:
            record, notes = self.resolver.resolve(self.paper)
        get.assert_not_called()
        self.assertIn("deferred", notes[-1])
        self.assertTrue(self.resolver.retry_deferred)
        pending = self.root / "cache/pending-abstracts/sample.json"
        data = json.loads(pending.read_text())
        data["next_retry_at"] = 0
        sources.atomic_json(pending, data)
        with patch.object(self.resolver, "ieee", return_value=[self.record]):
            record, _ = self.resolver.resolve(self.paper)
        self.assertEqual(record["title"], "Paper One")
        self.assertEqual(json.loads(pending.read_text())["status"], "resolved")
        self.assertFalse(self.resolver.retry_deferred)

    def test_recovery_tries_alternatives_first_and_shares_a_bounded_wait_budget(self):
        for alternative, budget, retry_after, expected_calls in (
            (True, 120, 60, 1),
            (False, 120, 60, 2),
            (False, 60, 60, 2),
            (False, 120, 300, 1),
        ):
            with (
                self.subTest(alternative=alternative, budget=budget, retry_after=retry_after),
                tempfile.TemporaryDirectory() as temp,
            ):
                now, sleeps = [100.0], []

                def sleep(delay):
                    sleeps.append(delay)
                    now[0] += delay

                resolver = sources.AbstractResolver(temp)
                resolver.recovery.max_rounds = 2 if budget == 60 else 1
                resolver.recovery.max_wait_seconds = budget
                resolver.limiter = sources.SharedLimiter(
                    Path(temp) / "state", lambda: now[0], sleep
                )

                def crossref(paper):
                    resolver.get("https://api.crossref.org/works")
                    return [self.record]

                with (
                    patch.object(sources.time, "time", side_effect=lambda: now[0]),
                    patch.object(sources.time, "sleep", side_effect=sleep),
                    patch.object(resolver, "ieee", return_value=[]),
                    patch.object(resolver, "crossref", side_effect=crossref),
                    patch.object(
                        resolver,
                        "semantic_scholar",
                        return_value=[self.record] if alternative else [],
                    ),
                    patch.object(resolver, "arxiv", return_value=[]),
                    patch.object(
                        sources.requests,
                        "get",
                        side_effect=[
                            Response(status=429, headers={"Retry-After": str(retry_after)}),
                            Response(),
                        ],
                    ) as get,
                ):
                    record, notes = resolver.resolve(self.paper)
                    self.assertEqual(get.call_count, expected_calls)
                    self.assertEqual(bool(record), alternative or expected_calls == 2)
                    self.assertLessEqual(sum(sleeps), budget)
                    if expected_calls == 2:
                        self.assertEqual(sum(sleeps), retry_after)
                        get.reset_mock(side_effect=True)
                        get.return_value = Response(status=429)
                        resolver.resolve(dict(self.paper, id="second", title="Second paper"))
                        get.assert_called_once()
                        self.assertEqual(resolver.recovery_rounds, 1)

    def test_cached_abstract_identity_is_rechecked(self):
        sources.atomic_json(
            self.root / "cache/sample.json", dict(self.record, authors=["Wrong Person"])
        )
        self.resolver.offline = True
        with patch.object(sources.requests, "get") as get:
            record, _ = self.resolver.resolve(self.paper)
        self.assertIsNone(record)
        get.assert_not_called()

    def test_new_pending_link_is_tried_before_paper_retry_deadline(self):
        sources.atomic_json(
            self.root / "cache/pending-abstracts/sample.json",
            {"paper": self.paper, "attempts": 1, "next_retry_at": sources.time.time() + 3600},
        )
        new_url = "https://www.usenix.org/conference/osdi26/presentation/author"
        updated = dict(self.paper, urls=[self.paper["url"], new_url])
        with (
            patch.object(self.resolver, "ieee", return_value=[]),
            patch.object(
                self.resolver,
                "usenix",
                side_effect=lambda p: [self.record] if p["url"] == new_url else [],
            ) as usenix,
            patch.object(self.resolver, "crossref") as crossref,
            patch.object(sources.requests, "get", side_effect=AssertionError("Network forbidden")),
        ):
            record, _ = self.resolver.resolve(updated)
        self.assertEqual(record["abstract"], ABSTRACT)
        self.assertEqual([call.args[0]["url"] for call in usenix.call_args_list], updated["urls"])
        crossref.assert_not_called()


if __name__ == "__main__":
    unittest.main()
