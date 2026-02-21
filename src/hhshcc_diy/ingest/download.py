"""Download and cache CMS DIY model materials."""

import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

from hhshcc_diy.config import BENEFIT_YEARS, DEFAULT_DATA_DIR

logger = logging.getLogger(__name__)


def _filename_from_url(url: str) -> str:
    return Path(urlparse(url).path).name


def download_file(url: str, dest: Path) -> Path:
    """Download a file from *url* to *dest*, skipping if it already exists."""
    if dest.exists():
        logger.info("Cached: %s", dest)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s → %s", url, dest)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    logger.info("Saved %s (%d bytes)", dest, len(resp.content))
    return dest


def download_materials(benefit_year: int, data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Path]:
    """Download PDF and Excel files for a benefit year. Returns paths."""
    if benefit_year not in BENEFIT_YEARS:
        raise ValueError(f"Unsupported benefit year: {benefit_year}. Choose from {sorted(BENEFIT_YEARS)}")

    urls = BENEFIT_YEARS[benefit_year]
    year_dir = data_dir / f"cy{benefit_year}"
    paths = {}

    for key in ("pdf", "excel"):
        url = urls[key]
        filename = _filename_from_url(url)
        paths[key] = download_file(url, year_dir / filename)

    return paths
