#!/usr/bin/env python3
"""
Papers Extractor — Combined dblp Scraping + Abstract Enrichment Pipeline

Scrapes dblp conference index pages, fetches paper metadata, filters by date,
then attempts to fetch abstracts via Semantic Scholar. Outputs two files:
  1. Enriched papers (with abstracts) — ready for classification
  2. Unenriched papers (no abstract found) — for agentic AI to attempt scraping

Usage (standalone):
    python papers_extractor.py
"""

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin

import requests

from config import ConferencesConfig, load_config

# ==============================================================================
# Internal constants (not user-facing, not in config.yml)
# ==============================================================================

dblp_BASE_URL = "https://dblp.org/"
dblp_HEADERS = {
    "User-Agent": "dblp-Scraper/1.0 (academic research; polite crawling)",
    "Accept": "application/xml, text/xml, */*",
}
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1/paper"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# Rate-limiting delays (internal, not in config.yml)
dblp_REQUEST_DELAY = 2.0
SEMANTIC_SCHOLAR_DELAY = 1.0

logger = logging.getLogger(__name__)


# ==============================================================================
# dblp Scraping Functions
# ==============================================================================


def normalize_url_to_xml(url: str) -> str:
    """Convert a dblp HTML URL to its XML equivalent."""
    url = url.strip()
    if url.endswith(".html"):
        url = url[:-5] + ".xml"
    elif not url.endswith(".xml"):
        if url.endswith("/"):
            url += "index.xml"
        else:
            url += ".xml"
    return url


def relative_url_to_absolute_xml(relative_path: str) -> str:
    """Convert a relative dblp path to an absolute XML URL."""
    relative_path = relative_path.lstrip("/")
    if relative_path.endswith(".html"):
        relative_path = relative_path[:-5] + ".xml"
    elif not relative_path.endswith(".xml"):
        relative_path += ".xml"
    return urljoin(dblp_BASE_URL, relative_path)


def dblp_fetch(url: str, session: requests.Session) -> Optional[str]:
    """Fetch a dblp URL with retry logic and rate limiting."""
    time.sleep(dblp_REQUEST_DELAY)

    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            response = session.get(url, headers=dblp_HEADERS, timeout=30)

            if response.status_code == 200:
                return response.text
            elif response.status_code == 429:
                retry_after_val = response.headers.get("Retry-After", "10")
                retry_after = int(retry_after_val) if str(retry_after_val).isdigit() else 10
                retry_after = max(retry_after, 10)
                logger.warning(f"Rate limited (429) for {url}. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            elif response.status_code >= 500:
                logger.warning(f"Server error ({response.status_code}) for {url}. Retrying...")
            else:
                logger.error(f"HTTP {response.status_code} for {url}. Skipping.")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout for {url} (attempt {attempt + 1}/{MAX_RETRIES})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {url} (attempt {attempt + 1}/{MAX_RETRIES})")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

        attempt += 1
        if attempt < MAX_RETRIES:
            backoff = RETRY_BACKOFF_BASE ** attempt
            logger.info(f"  Retrying in {backoff}s...")
            time.sleep(backoff)

    logger.error(f"All {MAX_RETRIES} attempts failed for {url}")
    return None


def parse_xml_safe(xml_text: str) -> Optional[ET.Element]:
    """Safely parse XML text."""
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return None


def normalize_venue(booktitle: str) -> str:
    """Normalize venue name: 'ASPLOS (1)' -> 'ASPLOS'."""
    return re.sub(r"\s*\(\d+\)\s*$", "", booktitle).strip()


def extract_venue_from_index_url(index_url: str) -> str:
    """Extract conference short name from URL path."""
    match = re.search(r"/db/conf/([^/]+)/", index_url)
    return match.group(1).upper() if match else ""


def fetch_conference_volumes(index_url: str, session: requests.Session,
                             max_volumes: int, volume_date_filter_days: int) -> tuple:
    """Fetch conference index and return (venue_name, volumes_list).

    Filters volumes by their proceedings mdate — only returns volumes
    whose mdate is within volume_date_filter_days (i.e., newly added to dblp).
    """
    xml_url = normalize_url_to_xml(index_url)
    logger.info(f"Fetching conference index: {xml_url}")

    xml_text = dblp_fetch(xml_url, session)
    if not xml_text:
        logger.error(f"Failed to fetch index: {xml_url}")
        return "", []

    root = parse_xml_safe(xml_text)
    if root is None:
        return "", []

    today = datetime.now(timezone.utc).date()
    threshold = today - timedelta(days=volume_date_filter_days)

    volumes = []
    venue_name = ""

    for proceedings in root.iter("proceedings"):
        url_elem = proceedings.find("url")
        year_elem = proceedings.find("year")
        booktitle_elem = proceedings.find("booktitle")
        volume_mdate = proceedings.get("mdate", "")

        if url_elem is None or url_elem.text is None:
            continue

        year = int(year_elem.text) if year_elem is not None and year_elem.text and year_elem.text.isdigit() else 0
        booktitle = booktitle_elem.text if booktitle_elem is not None else ""

        if not venue_name and booktitle:
            venue_name = normalize_venue(booktitle)

        # Filter: only keep volumes with recent mdate AND recent year
        if volume_mdate:
            try:
                vol_date = datetime.strptime(volume_mdate, "%Y-%m-%d").date()
                if vol_date < threshold:
                    continue  # mdate too old
            except ValueError:
                continue
        else:
            continue  # No mdate at all, skip

        # Year check: volume must be from current or previous year
        current_year = today.year
        if year < current_year - 1:
            continue  # Old conference, mdate was just a metadata edit

        volumes.append({
            "url": relative_url_to_absolute_xml(url_elem.text),
            "year": year,
            "booktitle": booktitle,
            "mdate": volume_mdate,
        })

    if not venue_name:
        venue_name = extract_venue_from_index_url(index_url)

    volumes.sort(key=lambda v: v["year"], reverse=True)
    volumes = volumes[:max_volumes]

    logger.info(f"  Venue: {venue_name} | {len(volumes)} new volumes (mdate within last {volume_date_filter_days} days)")
    for v in volumes:
        logger.info(f"    {v['booktitle']} {v['year']} (mdate: {v['mdate']})")
    return venue_name, volumes


def fetch_volume_papers(volume_url: str, venue_name: str, session: requests.Session) -> List[Dict]:
    """Fetch and parse a volume TOC page to extract paper metadata."""
    logger.info(f"  Fetching volume TOC: {volume_url}")

    xml_text = dblp_fetch(volume_url, session)
    if not xml_text:
        logger.error(f"  Failed to fetch volume: {volume_url}")
        return []

    root = parse_xml_safe(xml_text)
    if root is None:
        return []

    papers = []

    for inproc in root.iter("inproceedings"):
        key = inproc.get("key", "")
        mdate = inproc.get("mdate", "")

        title_elem = inproc.find("title")
        title = "".join(title_elem.itertext()) if title_elem is not None else ""

        authors = []
        for author_elem in inproc.findall("author"):
            author_text = "".join(author_elem.itertext())
            if author_text:
                authors.append(author_text)

        ee_links = []
        for ee_elem in inproc.findall("ee"):
            ee_text = ee_elem.text if ee_elem.text else ""
            if ee_text:
                ee_links.append(ee_text)

        ee = ee_links[0] if ee_links else ""
        ee_others = ee_links[1:] if len(ee_links) > 1 else []

        paper_data = {
            "key": key,
            "mdate": mdate,
            "title": title,
            "authors": authors,
            "venue": venue_name,
            "ee": ee,
            "dblp_url": f"https://dblp.org/rec/{key}" if key else "",
        }

        if ee_others:
            paper_data["ee_others"] = ee_others

        papers.append(paper_data)

    logger.info(f"    Parsed {len(papers)} papers")
    return papers


# ==============================================================================
# Semantic Scholar Abstract Fetching Functions
# ==============================================================================


def ss_headers(api_key: str) -> Dict:
    """Build Semantic Scholar request headers."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def fetch_abstract_by_doi(doi_url: str, session: requests.Session, api_key: str) -> Optional[str]:
    """Fetch abstract from Semantic Scholar using a DOI."""
    if "doi.org/" in doi_url:
        doi_id = doi_url.split("doi.org/")[1]
    else:
        doi_id = doi_url

    url = f"{SEMANTIC_SCHOLAR_BASE}/DOI:{doi_id}?fields=abstract,title"

    try:
        response = session.get(url, headers=ss_headers(api_key), timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("abstract")
        elif response.status_code == 429:
            logger.warning("Semantic Scholar rate limited. Waiting 5s...")
            time.sleep(5)
            return None
        else:
            return None
    except requests.exceptions.RequestException as e:
        logger.debug(f"Semantic Scholar DOI fetch failed: {e}")
        return None


def fetch_abstract_by_title(title: str, session: requests.Session, api_key: str) -> Optional[str]:
    """Fetch abstract from Semantic Scholar by title search."""
    clean_title = title.rstrip(".").strip()
    query = quote(clean_title)
    url = f"{SEMANTIC_SCHOLAR_BASE}/search?query={query}&fields=abstract,title&limit=1"

    try:
        response = session.get(url, headers=ss_headers(api_key), timeout=15)
        if response.status_code == 200:
            data = response.json()
            papers = data.get("data", [])
            if papers:
                return papers[0].get("abstract")
            return None
        elif response.status_code == 429:
            logger.warning("Semantic Scholar rate limited. Waiting 5s...")
            time.sleep(5)
            return None
        else:
            return None
    except requests.exceptions.RequestException as e:
        logger.debug(f"Semantic Scholar title search failed: {e}")
        return None


def fetch_abstract(paper: Dict, session: requests.Session, api_key: str) -> Optional[str]:
    """Try to fetch abstract: first by DOI, then by title."""
    ee = paper.get("ee", "")

    # Strategy 1: DOI lookup
    if ee and "doi.org/" in ee:
        abstract = fetch_abstract_by_doi(ee, session, api_key)
        if abstract:
            return abstract

    # Strategy 2: Check ee_others for DOIs
    for other_link in paper.get("ee_others", []):
        if "doi.org/" in other_link:
            abstract = fetch_abstract_by_doi(other_link, session, api_key)
            if abstract:
                return abstract

    # Strategy 3: Title search (fallback)
    title = paper.get("title", "")
    if title:
        time.sleep(SEMANTIC_SCHOLAR_DELAY)
        abstract = fetch_abstract_by_title(title, session, api_key)
        if abstract:
            return abstract

    return None


# ==============================================================================
# Main Pipeline
# ==============================================================================


def run_pipeline(conferences_config: ConferencesConfig,
                 output_enriched: str,
                 output_unenriched: str) -> None:
    """
    Run the full scraping + enrichment pipeline.

    Args:
        conferences_config: Conference settings from config.yml.
        output_enriched: Output path for papers with abstracts.
        output_unenriched: Output path for papers without abstracts.
    """
    session = requests.Session()

    # Resolve Semantic Scholar API key (ignore unsubstituted env var placeholder or None)
    ss_api_key = conferences_config.semantic_scholar_api_key or ""
    if ss_api_key.startswith("${"):
        ss_api_key = ""
    if ss_api_key:
        logger.info("Semantic Scholar API key: set")
    else:
        logger.info("Semantic Scholar API key: not set (free tier)")

    # ========== PHASE 1: dblp Scraping ==========
    logger.info("=" * 60)
    logger.info("PHASE 1: Scraping dblp for papers")
    logger.info("=" * 60)

    all_papers = []
    for index_url in conferences_config.urls:
        logger.info(f"\nProcessing: {index_url}")

        venue_name, volumes = fetch_conference_volumes(
            index_url, session,
            max_volumes=conferences_config.max_volumes,
            volume_date_filter_days=conferences_config.volume_date_filter_days,
        )
        if not volumes:
            logger.info("  No new volumes found, skipping")
            continue

        for volume in volumes:
            papers = fetch_volume_papers(volume["url"], venue_name, session)
            all_papers.extend(papers)

    logger.info(f"\nPhase 1 complete: {len(all_papers)} papers from new volumes")

    # ========== PHASE 2: Abstract Enrichment ==========
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 2: Fetching abstracts via Semantic Scholar")
    logger.info("=" * 60)

    enriched_papers = []
    unenriched_papers = []
    total = len(all_papers)

    for i, paper in enumerate(all_papers):
        title_short = paper.get("title", "")[:60]
        logger.info(f"[{i + 1}/{total}] {title_short}...")

        time.sleep(SEMANTIC_SCHOLAR_DELAY)
        abstract = fetch_abstract(paper, session, ss_api_key)

        if abstract:
            paper["abstract"] = abstract
            enriched_papers.append(paper)
            logger.info(f"  ✓ Abstract found ({len(abstract)} chars)")
        else:
            unenriched_papers.append(paper)
            logger.info("  ✗ No abstract")

    # ========== PHASE 3: Write Outputs ==========
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 3: Writing output files")
    logger.info("=" * 60)

    with open(output_enriched, "w", encoding="utf-8") as f:
        json.dump(enriched_papers, f, indent=2, ensure_ascii=False)
    logger.info(f"  Enriched papers ({len(enriched_papers)}): {output_enriched}")

    with open(output_unenriched, "w", encoding="utf-8") as f:
        json.dump(unenriched_papers, f, indent=2, ensure_ascii=False)
    logger.info(f"  Unenriched papers ({len(unenriched_papers)}): {output_unenriched}")

    # ========== Summary ==========
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Total papers from new volumes: {len(all_papers)}")
    logger.info(f"  With abstract: {len(enriched_papers)}")
    logger.info(f"  Without abstract: {len(unenriched_papers)}")
    logger.info(f"  → {output_enriched} — ready for classification")
    logger.info(f"  → {output_unenriched} — pass to agent for abstract scraping")


# ==============================================================================
# Standalone execution
# ==============================================================================

if __name__ == "__main__":
    import os
    import sys

    from dotenv import load_dotenv

    sys.path.insert(0, os.path.dirname(__file__))

    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(project_root, ".env"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config(os.path.join(project_root, "config", "config.yml"))

    output_enriched = os.path.join(project_root, "data", "papers_enriched.json")
    output_unenriched = os.path.join(project_root, "data", "papers_unenriched.json")

    logger.info("Starting Papers Extractor Pipeline")
    logger.info(f"  Conferences: {len(config.conferences.urls)}")
    logger.info(f"  Max volumes/conference: {config.conferences.max_volumes}")
    logger.info(f"  Volume date filter: last {config.conferences.volume_date_filter_days} days")
    logger.info(f"  Output enriched: {output_enriched}")
    logger.info(f"  Output unenriched: {output_unenriched}")
    logger.info("")

    run_pipeline(config.conferences, output_enriched, output_unenriched)
