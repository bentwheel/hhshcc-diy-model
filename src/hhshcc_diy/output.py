"""Generate the three output CSV files from scoring results."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from hhshcc_diy.model.engine import ScoringResult

logger = logging.getLogger(__name__)


def write_outputs(
    result: ScoringResult,
    output_dir: Path,
    benefit_year: int,
) -> dict[str, Path]:
    """Write COMPLETE, DIGEST, and COMPONENTS CSV files.

    Returns a dict mapping output type to file path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"cy{benefit_year}"
    paths: dict[str, Path] = {}

    # --- COMPLETE ---
    complete_path = output_dir / f"{prefix}_COMPLETE.csv"
    result.complete.to_csv(complete_path, index=False)
    logger.info("Wrote %s (%d rows)", complete_path, len(result.complete))
    paths["COMPLETE"] = complete_path

    # --- DIGEST ---
    digest_path = output_dir / f"{prefix}_DIGEST.csv"
    result.digest.to_csv(digest_path, index=False)
    logger.info("Wrote %s (%d rows)", digest_path, len(result.digest))
    paths["DIGEST"] = digest_path

    # --- COMPONENTS ---
    components_path = output_dir / f"{prefix}_COMPONENTS.csv"
    result.components.to_csv(components_path, index=False)
    logger.info("Wrote %s (%d rows)", components_path, len(result.components))
    paths["COMPONENTS"] = components_path

    return paths
