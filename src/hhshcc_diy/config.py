"""CMS URLs and benefit year configuration for HHS-HCC DIY model materials."""

from pathlib import Path

CMS_BASE_URL = "https://www.cms.gov/files/document"

BENEFIT_YEARS = {
    2023: {
        "pdf": f"{CMS_BASE_URL}/cy2023-diy-instructions-04102024.pdf",
        "excel": f"{CMS_BASE_URL}/cy2023-diy-tables-04102024.xlsx",
    },
    2024: {
        "pdf": f"{CMS_BASE_URL}/cy2024-diy-instructions-04092025.pdf",
        "excel": f"{CMS_BASE_URL}/cy2024-diy-tables-04-09-2025.xlsx",
    },
    2025: {
        "pdf": f"{CMS_BASE_URL}/cy2025-diy-instructions-01-23-2026.pdf",
        "excel": f"{CMS_BASE_URL}/cy2025-diy-tables-01-23-2026.xlsx",
    },
}

DEFAULT_DATA_DIR = Path("data")
