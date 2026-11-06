"""Download the official DBLP XML dump and DTD on demand.

Both files must be in the same directory because the XML references dblp.dtd.
Partial downloads are stored under .part and never treated as complete.
"""
import gzip
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DBLP_FILES = {
    "dblp.dtd": "https://dblp.org/xml/dblp.dtd",
    "dblp.xml.gz": "https://dblp.org/xml/dblp.xml.gz",
}
CHUNK_SIZE = 1024 * 1024


def _looks_valid(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if path.name == "dblp.xml.gz":
        if path.stat().st_size < 1024 * 1024:
            return False
        with path.open("rb") as stream:
            return stream.read(2) == b"\x1f\x8b"
    if path.name == "dblp.dtd":
        return path.stat().st_size > 100
    return False


def _download(url: str, target: Path) -> None:
    partial = target.with_name(target.name + ".part")
    # A previous interrupted download must not be mistaken for a complete file.
    partial.unlink(missing_ok=True)
    logger.info("Downloading %s to %s", url, target)
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(30, 120),
            headers={"User-Agent": "ConferenceScout/1.0 (academic dataset downloader)"},
        ) as response:
            response.raise_for_status()
            expected = response.headers.get("Content-Length")
            received = 0
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        output.write(chunk)
                        received += len(chunk)
            if expected is not None and received != int(expected):
                raise IOError(f"Incomplete download: {received} of {expected} bytes")
        if not _looks_valid(partial.with_name(target.name)):
            # Validation below uses the final filename's expected file type.
            if target.name == "dblp.xml.gz":
                with partial.open("rb") as stream:
                    valid = partial.stat().st_size >= 1024 * 1024 and stream.read(2) == b"\x1f\x8b"
            else:
                valid = partial.stat().st_size > 100
            if not valid:
                raise IOError(f"Downloaded file is not a valid {target.name}")
        os.replace(partial, target)
        logger.info("Downloaded %s (%.1f MB)", target.name, received / 1048576)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def ensure_dblp_dataset(dataset_dir: str | Path) -> Path:
    """Return the DBLP gzip path, downloading missing files if necessary."""
    directory = Path(dataset_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for filename, url in DBLP_FILES.items():
        target = directory / filename
        if _looks_valid(target):
            logger.info("Reusing existing DBLP file: %s", target)
            continue
        if target.exists():
            logger.warning("Replacing missing/invalid DBLP file: %s", target)
        try:
            _download(url, target)
        except (requests.RequestException, OSError, ValueError) as exc:
            raise RuntimeError(
                f"Could not download {filename} from {url}. "
                "Check connectivity or manually place the official DBLP files "
                f"in {directory}. Original error: {exc}"
            ) from exc
    return directory / "dblp.xml.gz"
