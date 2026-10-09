"""Persist the Scholar retry queue on a dedicated GitHub branch."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout.abstract_sources import atomic_json
from scholar_scout.config import StateStorageConfig, load_config

BOT = {
    "name": "github-actions[bot]",
    "email": "41898282+github-actions[bot]@users.noreply.github.com",
}


def validate(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "version",
        "pending",
        "expired",
        "retries",
        "source_limits",
    }:
        raise ValueError("Invalid state snapshot")
    if snapshot["version"] != 1:
        raise ValueError("Unsupported state version")
    for name in ("pending", "expired", "retries", "source_limits"):
        if not isinstance(snapshot[name], dict):
            raise ValueError("Invalid state section")
    if snapshot["pending"].keys() & snapshot["expired"].keys():
        raise ValueError("Paper cannot be both pending and expired")
    for key, row in {**snapshot["pending"], **snapshot["expired"]}.items():
        if not re.fullmatch(r"[a-f0-9]{20}", key) or not isinstance(row, dict):
            raise ValueError("Invalid pending paper")
        fields = {"paper", "status", "attempts", "first_pending_at"}
        if key in snapshot["expired"]:
            fields |= {"expired_at", "expiration_reason"}
            if row.get("expiration_reason") not in ("max_age", "max_attempts"):
                raise ValueError("Invalid expiration reason")
        if set(row) != fields or row["status"] not in (
            "pending_abstract",
            "pending_model",
        ):
            raise ValueError("Invalid pending status")
        if type(row["attempts"]) is not int or row["attempts"] < 0:
            raise ValueError("Invalid processing attempt count")
        for field in ("first_pending_at", "expired_at"):
            if field in row and (type(row[field]) not in (int, float) or row[field] < 0):
                raise ValueError("Invalid queue timestamp")
        paper = row["paper"]
        if not isinstance(paper, dict) or set(paper) - {
            "id",
            "title",
            "authors",
            "abstract",
            "url",
            "urls",
            "venue",
            "scholar_profiles",
        }:
            raise ValueError("Invalid paper metadata")
        if (
            paper.get("id") != key
            or not isinstance(paper.get("title"), str)
            or not paper["title"].strip()
        ):
            raise ValueError("Missing paper identity")
        for field in ("abstract", "url", "venue"):
            if not isinstance(paper.get(field, ""), str):
                raise ValueError("Invalid paper text")
        for field in ("authors", "urls", "scholar_profiles"):
            if not isinstance(paper.get(field, []), list) or not all(
                isinstance(v, str) for v in paper.get(field, [])
            ):
                raise ValueError("Invalid paper list")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", p) for p in paper.get("scholar_profiles", [])
        ):
            raise ValueError("Invalid Scholar profile")
    for key, retry in snapshot["retries"].items():
        if key not in snapshot["pending"] or not isinstance(retry, dict):
            raise ValueError("Retry without pending paper")
        if set(retry) != {"attempts", "last_attempt_at", "next_retry_at"}:
            raise ValueError("Invalid retry fields")
        if not isinstance(retry["attempts"], int) or retry["attempts"] < 0:
            raise ValueError("Invalid retry count")
        if not all(
            isinstance(retry[f], (int, float)) and retry[f] >= 0
            for f in ("last_attempt_at", "next_retry_at")
        ):
            raise ValueError("Invalid retry time")
    for service, limits in snapshot["source_limits"].items():
        if service not in {
            "semantic_scholar",
            "ieee",
            "arxiv",
            "arxiv_web",
            "crossref",
            "usenix",
            "ntu",
            "google_research",
            "google_scholar",
        } or not isinstance(limits, dict):
            raise ValueError("Invalid source limits")
        if set(limits) - {"next_start", "cooldown_until", "failures"} or not all(
            isinstance(v, (int, float)) and v >= 0 for v in limits.values()
        ):
            raise ValueError("Invalid source cooldown")
    json.dumps(snapshot, allow_nan=False)
    return snapshot


def collect(directory):
    pending = json.loads((directory / "pending-papers.json").read_text())
    expired = json.loads((directory / "expired-papers.json").read_text())
    pending = {key: row for key, row in pending.items() if key not in expired}
    retries = {}
    for key in pending:
        if not re.fullmatch(r"[a-f0-9]{20}", key):
            raise ValueError("Invalid pending identifier")
        path = directory / "abstracts/pending-abstracts" / f"{key}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row.get("status") != "resolved":
                retries[key] = {
                    field: row[field] for field in ("attempts", "last_attempt_at", "next_retry_at")
                }
    limits = directory / "source-state/limits.json"
    return validate(
        {
            "version": 1,
            "pending": pending,
            "expired": expired,
            "retries": retries,
            "source_limits": json.loads(limits.read_text()) if limits.exists() else {},
        }
    )


def restore(directory, snapshot):
    validate(snapshot)
    if (
        (directory / "pending-papers.json").exists()
        or (directory / "expired-papers.json").exists()
        or (directory / "abstracts/pending-abstracts").exists()
        or (directory / "source-state").exists()
    ):
        raise ValueError(
            "Refusing to overwrite existing local queue; restore into a fresh state directory"
        )
    atomic_json(directory / "pending-papers.json", snapshot["pending"])
    atomic_json(directory / "expired-papers.json", snapshot["expired"])
    for key, retry in snapshot["retries"].items():
        atomic_json(
            directory / "abstracts/pending-abstracts" / f"{key}.json",
            dict(retry, paper=snapshot["pending"][key]["paper"], status="pending_abstract"),
        )
    atomic_json(directory / "source-state/limits.json", snapshot["source_limits"])


class StateBranch:
    def __init__(self, repository, token, storage: StateStorageConfig):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not token:
            raise ValueError("Repository and GitHub token are required")
        self.url = f"https://api.github.com/repos/{repository}"
        self.branch = storage.branch
        self.file = storage.file
        if os.environ.get("GITHUB_REF") == f"refs/heads/{self.branch}":
            raise RuntimeError("State branch must differ from the workflow's source branch")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def api(self, method, path, *, raw=False, data=None):
        headers = dict(self.headers)
        if raw:
            headers["Accept"] = "application/vnd.github.raw+json"
        try:
            response = requests.request(
                method,
                self.url + path,
                headers=headers,
                json=data,
                timeout=60,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise RuntimeError(
                "GitHub state request failed; remote write outcome may be unknown"
            ) from None
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"GitHub state request failed (HTTP {response.status_code}); no empty-state fallback"
            )
        return response.json()

    def head(self):
        return self.api("GET", f"/git/ref/heads/{quote(self.branch, safe='/')}")["object"]["sha"]

    def read(self, revision):
        return validate(
            self.api("GET", f"/contents/{self.file}?ref={quote(revision, safe='')}", raw=True)
        )

    def write(self, snapshot, parent):
        validate(snapshot)
        if not parent or self.head() != parent:
            raise RuntimeError("State branch changed since restore; refusing to overwrite")
        if self.read(parent) == snapshot:
            return parent
        tree = self.api(
            "POST",
            "/git/trees",
            data={
                "tree": [
                    {
                        "path": self.file,
                        "mode": "100644",
                        "type": "blob",
                        "content": json.dumps(
                            snapshot, ensure_ascii=False, indent=2, allow_nan=False
                        )
                        + "\n",
                    }
                ]
            },
        )
        commit = self.api(
            "POST",
            "/git/commits",
            data={
                "message": "Update Scholar pending state\n\nSigned-off-by: "
                + BOT["name"]
                + " <"
                + BOT["email"]
                + ">",
                "tree": tree["sha"],
                "parents": [parent],
                "author": BOT,
                "committer": BOT,
            },
        )
        revision = commit["sha"]
        self.api(
            "PATCH",
            f"/git/refs/heads/{quote(self.branch, safe='/')}",
            data={"sha": revision, "force": False},
        )
        if self.head() != revision or self.read(revision) != snapshot:
            raise RuntimeError("Saved state could not be verified")
        return revision


def report(message):
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(message + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "save"))
    parser.add_argument("--config", default="config/config.yml")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--revision-file", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        directory = (args.state_dir or Path(config.state_dir)).resolve()
        if "\n" in str(directory) or "\r" in str(directory):
            raise RuntimeError("State directory must not contain newlines")
        revision_file = args.revision_file or directory / "restored-revision.json"
        remote = StateBranch(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GH_TOKEN", ""),
            config.state_storage,
        )
        target = {
            "repository": os.environ["GITHUB_REPOSITORY"],
            "branch": remote.branch,
            "file": remote.file,
        }
        if args.operation == "restore":
            revision = remote.head()
            restore(directory, remote.read(revision))
            atomic_json(revision_file, dict(target, revision=revision))
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                    stream.write(f"state_dir={directory}\n")
        else:
            restored = json.loads(revision_file.read_text())
            if any(restored.get(key) != value for key, value in target.items()):
                raise RuntimeError(
                    "State storage configuration changed since restore; refusing to save"
                )
            revision = restored["revision"]
            revision = remote.write(collect(directory), revision)
        report(f"State {args.operation}: verified `{remote.branch}/{remote.file}` at `{revision}`.")
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        report(f"::error::State {args.operation} failed: {message}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
