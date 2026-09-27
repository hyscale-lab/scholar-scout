"""Publisher/API abstract sources, identity checks and shared rate limiting."""

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text).casefold() if c.isalnum())


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".abstract-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def doi_of(paper):
    value = paper.get("doi") or ""
    parsed = urlparse(paper.get("url", ""))
    if not value and parsed.hostname in ("doi.org", "dx.doi.org", "dl.acm.org"):
        value = unquote(parsed.path)
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", value, re.I)
    return match[0].rstrip("/").casefold() if match else ""


def expected_authors(paper):
    authors = paper.get("authors")
    if authors:
        return authors if isinstance(authors, list) else [authors]
    # Scholar uses an author list followed by a spaced dash and venue/year.
    metadata = re.split(r"\s[-–—]\s", paper.get("email_metadata", ""), maxsplit=1)[0]
    return [a.strip(" .…") for a in metadata.split(",") if a.strip(" .…")]


def surnames(authors):
    return {
        normalized((a.split(",")[0] if "," in a else a.split()[-1]).strip(" .…"))
        for a in authors
        if isinstance(a, str) and a.split() and not a.strip().isdigit()
    }


def identity_matches(paper, record):
    if normalized(paper["title"]) != normalized(record.get("title", "")):
        return False
    wanted, actual = doi_of(paper), doi_of(record)
    if wanted and actual and wanted != actual:
        return False
    authors = surnames(expected_authors(paper))
    if authors and not authors.intersection(surnames(record.get("authors", []))):
        return False
    return True


def is_usable_abstract(record):
    text = record.get("abstract") or ""
    return (
        isinstance(text, str)
        and 200 <= len(text.strip()) <= 30000
        and not re.search(r"(?:\.{3,}|…|read more|view full abstract)\s*$", text, re.I)
        and bool(record.get("source"))
    )


class SourceFailure(Exception):
    """Safe diagnostic: never contains a request URL, response body or secret."""

    def __init__(self, code, retry_at=0):
        super().__init__(code)
        self.retry_at = retry_at


class SharedLimiter:
    """Persistent per-service quota shared by cooperating processes on this host."""

    INTERVALS = {
        "semantic_scholar": 2.0,
        "ieee": 2.0,
        "arxiv": 3.1,
        "crossref": 1.0,
        "usenix": 1.0,
        "ntu": 1.0,
    }

    def __init__(self, directory, clock=time.time, sleep=time.sleep):
        self.directory = Path(directory)
        self.clock, self.sleep = clock, sleep

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / "limits.json"
        with (self.directory / "limits.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(path.read_text()) if path.exists() else {}
            yield state
            atomic_json(path, state)

    def before(self, service):
        with self.locked() as state:
            entry = state.setdefault(service, {})
            now = self.clock()
            if entry.get("cooldown_until", 0) > now:
                raise SourceFailure("cooldown_active", entry["cooldown_until"])
            wait = max(0, entry.get("next_start", 0) - now)
            if wait > 5:
                raise SourceFailure("request_deferred", entry["next_start"])
            if wait:
                self.sleep(wait)
            entry["next_start"] = self.clock() + self.INTERVALS[service]

    def defer(self, service, retry_after=None):
        with self.locked() as state:
            entry = state.setdefault(service, {})
            entry["failures"] = min(entry.get("failures", 0) + 1, 8)
            delay = min(3600, 60 * 2 ** (entry["failures"] - 1))
            if retry_after:
                try:
                    seconds = float(retry_after)
                except ValueError:
                    try:
                        seconds = parsedate_to_datetime(retry_after).timestamp() - self.clock()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                if math.isfinite(seconds):
                    delay = max(delay, seconds)
            entry["cooldown_until"] = max(entry.get("cooldown_until", 0), self.clock() + delay)
            return entry["cooldown_until"]

    def success(self, service):
        with self.locked() as state:
            state.setdefault(service, {})["failures"] = 0


class AbstractResolver:
    HOSTS = {
        "arxiv.org",
        "export.arxiv.org",
        "api.crossref.org",
        "www.usenix.org",
        "dr.ntu.edu.sg",
        "api.semanticscholar.org",
        "ieeexploreapi.ieee.org",
    }
    SERVICES = {
        "arxiv.org": "arxiv",
        "export.arxiv.org": "arxiv",
        "api.crossref.org": "crossref",
        "www.usenix.org": "usenix",
        "dr.ntu.edu.sg": "ntu",
        "api.semanticscholar.org": "semantic_scholar",
        "ieeexploreapi.ieee.org": "ieee",
    }

    def __init__(self, cache, offline=False, env_file=None, state_dir=None):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.offline = offline
        values = dotenv_values(env_file) if env_file else {}
        self.keys = {
            name: os.environ.get(name) or values.get(name)
            for name in ("IEEE_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")
        }
        self.limiter = SharedLimiter(state_dir or self.cache.parent / "source-state")
        self.disabled = set()
        self.programs = {}
        self.last_pending = None

    def get(self, url, params=None):
        if self.offline:
            raise SourceFailure("network_disabled")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Unsupported source host")
        service = self.SERVICES[parsed.hostname]
        if service in self.disabled:
            raise SourceFailure("authentication_disabled_for_run")
        params = dict(params or {})
        headers = {"User-Agent": "ScholarScoutAbstractResolver/2.0"}
        if service == "ieee":
            if not self.keys["IEEE_API_KEY"]:
                raise SourceFailure("missing_ieee_key")
            params["apikey"] = self.keys["IEEE_API_KEY"]
        if service == "semantic_scholar" and self.keys["SEMANTIC_SCHOLAR_API_KEY"]:
            headers["x-api-key"] = self.keys["SEMANTIC_SCHOLAR_API_KEY"]
        self.limiter.before(service)
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=(5, 20),
                allow_redirects=False,
                stream=True,
            )
            with response:
                status = response.status_code
                if status in (429, 408) or status >= 500:
                    until = self.limiter.defer(service, response.headers.get("Retry-After"))
                    raise SourceFailure("http_" + str(status), until)
                if status in (401, 403):
                    self.disabled.add(service)
                if status != 200:
                    raise SourceFailure("http_" + str(status))
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 4_000_000:
                        raise SourceFailure("response_too_large")
                    chunks.append(chunk)
                self.limiter.success(service)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except requests.RequestException:
            raise SourceFailure("transport_error", self.limiter.defer(service)) from None

    def ieee(self, paper):
        parsed = urlparse(paper.get("url", ""))
        number = None
        if parsed.hostname == "ieeexplore.ieee.org":
            match = re.search(r"/(?:document/)?(\d{5,})(?:\.pdf)?/?$", parsed.path)
            number = match[1] if match else parse_qs(parsed.query).get("arnumber", [None])[0]
        doi = doi_of(paper)
        if not number and not doi.startswith("10.1109/"):
            return []
        params = {"article_number": number} if number else {"doi": doi}
        data = json.loads(
            self.get(
                "https://ieeexploreapi.ieee.org/api/v1/search/articles", dict(params, format="json")
            )
        )
        return [
            {
                "title": a.get("title", ""),
                "abstract": a.get("abstract") or "",
                "doi": a.get("doi", ""),
                "authors": [
                    x.get("full_name", "") for x in a.get("authors", {}).get("authors", [])
                ],
                "url": "https://ieeexplore.ieee.org/document/" + str(a.get("article_number", "")),
                "venue": a.get("publication_title", ""),
                "source": "IEEE Xplore Metadata API",
            }
            for a in data.get("articles", [])
        ]

    def crossref(self, paper):
        doi = doi_of(paper)
        if doi:
            data = json.loads(self.get("https://api.crossref.org/works/" + quote(doi, safe="")))
            entries = [data["message"]]
        else:
            data = json.loads(
                self.get(
                    "https://api.crossref.org/works", {"query.title": paper["title"], "rows": 5}
                )
            )
            entries = data["message"]["items"]
        return [
            {
                "title": (x.get("title") or [""])[0],
                "abstract": BeautifulSoup(x.get("abstract") or "", "html.parser").get_text(
                    " ", strip=True
                ),
                "authors": [
                    " ".join([a.get("given", ""), a.get("family", "")]).strip()
                    for a in x.get("author", [])
                ],
                "doi": x.get("DOI", ""),
                "url": "https://doi.org/" + x.get("DOI", ""),
                "source": "Crossref deposited abstract",
                "venue": (x.get("container-title") or [""])[0],
            }
            for x in entries
        ]

    def semantic_scholar(self, paper):
        fields = "title,abstract,authors,externalIds,url,venue"
        doi = doi_of(paper)
        parsed = urlparse(paper.get("url", ""))
        arxiv = (
            re.search(r"\d{4}\.\d{4,5}", parsed.path)
            if parsed.hostname in ("arxiv.org", "export.arxiv.org")
            else None
        )
        identifier = "DOI:" + doi if doi else "ARXIV:" + arxiv[0] if arxiv else None
        base = "https://api.semanticscholar.org/graph/v1/paper/"

        def records(items):
            return [
                {
                    "title": d.get("title") or "",
                    "abstract": d.get("abstract") or "",
                    "authors": [a.get("name", "") for a in d.get("authors", [])],
                    "doi": (d.get("externalIds") or {}).get("DOI", ""),
                    "url": d.get("url", ""),
                    "venue": d.get("venue") or "",
                    "source": "Semantic Scholar Academic Graph API",
                }
                for d in items
                if d
            ]

        if identifier:
            try:
                data = json.loads(self.get(base + quote(identifier, safe=""), {"fields": fields}))
                rows = records([data])
                if any(identity_matches(paper, r) and is_usable_abstract(r) for r in rows):
                    return rows
            except SourceFailure as exc:
                if str(exc) != "http_404":
                    raise
        # A DOI 404 or wrong merged record is not evidence of an irrelevant paper.
        data = json.loads(
            self.get(base + "search", {"query": paper["title"], "limit": 5, "fields": fields})
        )
        return records(data.get("data", []))

    def usenix(self, paper):
        parsed = urlparse(paper.get("url", ""))
        if parsed.hostname not in ("www.usenix.org", "usenix.org"):
            return []
        path = unquote(parsed.path)
        conf = re.search(r"/conference/([a-z]+\d{2})/", path)
        if "/presentation/" in path and conf:
            url = "https://www.usenix.org" + parsed.path
            soup = BeautifulSoup(self.get(url), "html.parser")
            title = soup.select_one("h1")
            abstract = soup.select_one(
                ".field-name-field-paper-description-long, .field-name-field-paper-description"
            )
            if not title or not abstract:
                return []
            return [
                {
                    "title": title.get_text(" ", strip=True),
                    "abstract": abstract.get_text(" ", strip=True),
                    "authors": [
                        a.get("content", "") for a in soup.select('meta[name="citation_author"]')
                    ],
                    "url": url,
                    "venue": conf[1],
                    "source": "USENIX official abstract page",
                }
            ]
        if not conf:
            conf = re.search(r"/(?:conference/)?([a-z]+\d{2})(?:[-_/])", path)
        if not conf:
            return []
        code = conf[1]
        if code not in self.programs:
            url = "https://www.usenix.org/conference/" + code + "/technical-sessions"
            self.programs[code] = BeautifulSoup(self.get(url), "html.parser")
        rows = []
        for node in self.programs[code].select("article.node-paper"):
            title = node.select_one('h2 a[href*="/presentation/"]')
            abstract = node.select_one(
                ".field-name-field-paper-description-long, .field-name-field-paper-description"
            )
            if (
                not title
                or not abstract
                or normalized(title.get_text(" ", strip=True)) != normalized(paper["title"])
            ):
                continue
            link = urljoin("https://www.usenix.org", title["href"])
            # The individual page has structured author names, unlike the program's affiliations.
            rows.extend(self.usenix(dict(paper, url=link)))
        return rows

    def resolve(self, paper):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", paper["id"]):
            raise ValueError("Invalid cache identifier")
        self.last_pending = None
        path = self.cache / (paper["id"] + ".json")
        pending_path = self.cache / "pending-abstracts" / (paper["id"] + ".json")
        context = dict(paper)
        notes, retry_at = [], 0
        if path.exists():
            try:
                record = json.loads(path.read_text())
                if identity_matches(context, record) and is_usable_abstract(record):
                    if pending_path.exists():
                        previous = json.loads(pending_path.read_text())
                        if previous.get("status") != "resolved":
                            atomic_json(
                                pending_path, dict(previous, status="resolved", next_retry_at=0)
                            )
                    return record, []
                notes.append("cache: identity or abstract usability check failed")
            except (ValueError, TypeError, KeyError):
                notes.append("cache: invalid record")
        if self.offline:
            return None, notes + ["No identity-matched, usable abstract in local cache"]
        previous = json.loads(pending_path.read_text()) if pending_path.exists() else {}
        if previous.get("next_retry_at", 0) > time.time() and previous.get("paper") == paper:
            self.last_pending = previous
            return None, notes + ["abstract retry deferred until scheduled time"]
        urls = list(dict.fromkeys([paper.get("url", ""), *paper.get("urls", [])]))
        if not doi_of(context):
            dois = {doi_of({"url": url}) for url in urls} - {""}
            if len(dois) == 1:
                context["doi"] = next(iter(dois))
        sources = [
            (name, dict(context, url=url))
            for name in ("ieee", "usenix", "arxiv_html", "institutional")
            for url in urls
        ]
        sources.extend((name, context) for name in ("crossref", "semantic_scholar", "arxiv"))
        for name, source_paper in sources:
            try:
                records = getattr(self, name)(source_paper)
                matched = [r for r in records if identity_matches(context, r)]
                if len(matched) == 1 and is_usable_abstract(matched[0]):
                    record = dict(matched[0])
                    record["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                    record["identity_check"] = (
                        "exact normalized title; DOI agreement when available; author surname overlap when supplied"
                    )
                    atomic_json(path, record)
                    if pending_path.exists():
                        # Preserve retry history, but mark the queue item complete.
                        atomic_json(
                            pending_path, dict(previous, status="resolved", next_retry_at=0)
                        )
                    return record, notes
                if len(matched) == 1 and name == "crossref" and not doi_of(context):
                    context["doi"] = matched[0].get("doi", "")
                if records:
                    notes.append(
                        name + ": identity mismatch, ambiguous result, or unusable abstract"
                    )
            except SourceFailure as exc:
                notes.append(name + ": " + str(exc))
                retry_at = max(retry_at, exc.retry_at)
            except Exception as exc:
                notes.append(name + ": " + type(exc).__name__)
        attempts = previous.get("attempts", 0) + 1
        # Retry on a subsequent invocation, never spin or invent a negative label.
        pending = {
            "paper": paper,
            "status": "pending_abstract",
            "attempts": attempts,
            "last_attempt_at": time.time(),
            "next_retry_at": max(
                retry_at, time.time() + min(86400, 3600 * 2 ** min(attempts - 1, 5))
            ),
            "reasons": notes,
        }
        atomic_json(pending_path, pending)
        self.last_pending = pending
        return None, notes

    def arxiv(self, paper):
        parsed = urlparse(paper["url"])
        identifier = (
            re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", parsed.path)
            if parsed.hostname in ("arxiv.org", "export.arxiv.org")
            else None
        )
        params = (
            {"id_list": identifier[1]}
            if identifier
            else {"search_query": 'ti:"' + paper["title"].replace('"', "") + '"'}
        )
        params["max_results"] = 5
        root = ET.fromstring(self.get("https://export.arxiv.org/api/query", params))
        ns = {"a": "http://www.w3.org/2005/Atom"}
        records = []
        for entry in root.findall("a:entry", ns):
            records.append(
                {
                    "title": entry.findtext("a:title", "", ns),
                    "abstract": entry.findtext("a:summary", "", ns).strip(),
                    "authors": [
                        a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)
                    ],
                    "url": entry.findtext("a:id", "", ns).replace("http:", "https:"),
                    "venue": "arXiv preprint",
                    "source": "arXiv API abstract",
                }
            )
        if identifier and not records:
            raise ValueError("No arXiv record")
        return records

    def arxiv_html(self, paper):
        parsed = urlparse(paper["url"])
        m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", parsed.path)
        if parsed.hostname not in ("arxiv.org", "export.arxiv.org") or not m:
            return []
        url = "https://arxiv.org/abs/" + m[1]
        soup = BeautifulSoup(self.get(url), "html.parser")
        title = soup.select_one("h1.title")
        abstract = soup.select_one("blockquote.abstract")
        if not title or not abstract:
            return []
        return [
            {
                "title": re.sub(r"^Title:\s*", "", title.get_text(" ", strip=True)),
                "abstract": re.sub(r"^Abstract:\s*", "", abstract.get_text(" ", strip=True)),
                "authors": [a.get_text(" ", strip=True) for a in soup.select(".authors a")],
                "url": url,
                "source": "arXiv abstract page",
                "venue": "arXiv preprint",
            }
        ]

    def institutional(self, paper):
        if urlparse(paper["url"]).hostname != "dr.ntu.edu.sg":
            return []
        soup = BeautifulSoup(self.get(paper["url"]), "html.parser")
        records = []
        for tag in soup.find_all("script", type="application/ld+json"):
            raw = json.loads(tag.string or "{}")
            entries = raw if isinstance(raw, list) else raw.get("@graph", [raw])
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item.get("abstract"), str):
                    continue
                authors = item.get("author", [])
                if not isinstance(authors, list):
                    authors = [authors]
                records.append(
                    {
                        "title": item.get("name", item.get("headline", "")),
                        "abstract": BeautifulSoup(item["abstract"], "html.parser").get_text(
                            " ", strip=True
                        ),
                        "authors": [
                            a if isinstance(a, str) else a.get("name", "") for a in authors
                        ],
                        "url": paper["url"],
                        "venue": "",
                        "source": "NTU repository structured abstract",
                    }
                )
        return records
