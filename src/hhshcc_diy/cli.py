"""CLI entry point for the HHS-HCC DIY model."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from hhshcc_diy.config import BENEFIT_YEARS


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """HHS-HCC DIY Risk Adjustment Model (2023-2025)."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
@click.option(
    "--benefit-year", "-y",
    type=click.IntRange(min=min(BENEFIT_YEARS), max=max(BENEFIT_YEARS)),
    required=True,
    help="Benefit year (2023, 2024, or 2025).",
)
@click.option(
    "--input-dir", "-i",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Directory containing PERSON.csv, DIAG.csv, NDC.csv, HCPCS.csv.",
)
@click.option(
    "--output-dir", "-o",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory for output CSVs.",
)
@click.option(
    "--data-dir", "-d",
    type=click.Path(file_okay=False, path_type=Path),
    default="data",
    show_default=True,
    help="Directory for cached CMS materials.",
)
def run(benefit_year: int, input_dir: Path, output_dir: Path, data_dir: Path):
    """Run the HHS-HCC DIY model."""
    from hhshcc_diy.pipeline import run as run_pipeline

    paths = run_pipeline(
        benefit_year=benefit_year,
        input_dir=input_dir,
        output_dir=output_dir,
        data_dir=data_dir,
    )

    click.echo(f"\nOutput files:")
    for name, path in paths.items():
        click.echo(f"  {name}: {path}")


@cli.command()
@click.option(
    "--benefit-year", "-y",
    type=click.IntRange(min=min(BENEFIT_YEARS), max=max(BENEFIT_YEARS)),
    required=True,
    help="Benefit year to download.",
)
@click.option(
    "--data-dir", "-d",
    type=click.Path(file_okay=False, path_type=Path),
    default="data",
    show_default=True,
    help="Directory for cached CMS materials.",
)
def download(benefit_year: int, data_dir: Path):
    """Download CMS model materials for a benefit year."""
    from hhshcc_diy.ingest.download import download_materials

    materials = download_materials(benefit_year, data_dir)
    click.echo(f"Downloaded materials for CY{benefit_year}:")
    for name, path in materials.items():
        click.echo(f"  {name}: {path}")
