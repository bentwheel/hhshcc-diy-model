"""End-to-end pipeline: ingest → model → output."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from hhshcc_diy.config import BENEFIT_YEARS, DEFAULT_DATA_DIR
from hhshcc_diy.ingest.download import download_materials
from hhshcc_diy.ingest.parse import parse_excel
from hhshcc_diy.model.engine import ScoringEngine, ScoringResult
from hhshcc_diy.output import write_outputs

logger = logging.getLogger(__name__)


def run(
    benefit_year: int,
    input_dir: Path,
    output_dir: Path,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> dict[str, Path]:
    """Run the full HHS-HCC DIY model pipeline.

    Args:
        benefit_year: 2023, 2024, or 2025.
        input_dir: Directory containing PERSON.csv, DIAG.csv,
                   and optionally NDC.csv and HCPCS.csv.
        output_dir: Directory for output CSVs.
        data_dir: Directory for cached CMS materials.

    Returns:
        Dict mapping output type to file path.
    """
    if benefit_year not in BENEFIT_YEARS:
        raise ValueError(
            f"Unsupported benefit year {benefit_year}. "
            f"Supported: {sorted(BENEFIT_YEARS.keys())}"
        )

    # Step 1: Download CMS materials
    logger.info("Downloading CMS materials for CY%d...", benefit_year)
    materials = download_materials(benefit_year, data_dir)
    excel_path = materials["excel"]

    # Step 2: Parse Excel tables
    logger.info("Parsing model tables...")
    model_data = parse_excel(excel_path, benefit_year)

    # Step 3: Load input files
    logger.info("Loading input files from %s...", input_dir)
    person_df = pd.read_csv(input_dir / "PERSON.csv")
    diag_df = pd.read_csv(input_dir / "DIAG.csv", dtype={"DIAG": str})

    ndc_df = None
    ndc_path = input_dir / "NDC.csv"
    if ndc_path.exists():
        ndc_df = pd.read_csv(ndc_path, dtype={"NDC": str})
        logger.info("Loaded %d NDC records", len(ndc_df))

    hcpcs_df = None
    hcpcs_path = input_dir / "HCPCS.csv"
    if hcpcs_path.exists():
        hcpcs_df = pd.read_csv(hcpcs_path, dtype={"HCPCS": str})
        logger.info("Loaded %d HCPCS records", len(hcpcs_df))

    logger.info(
        "Scoring %d enrollees with %d diagnoses...",
        len(person_df), len(diag_df),
    )

    # Step 4: Score
    engine = ScoringEngine(model_data)
    result = engine.score(person_df, diag_df, ndc_df, hcpcs_df)

    # Step 5: Write outputs
    logger.info("Writing output files to %s...", output_dir)
    paths = write_outputs(result, output_dir, benefit_year)

    logger.info("Pipeline complete.")
    return paths
