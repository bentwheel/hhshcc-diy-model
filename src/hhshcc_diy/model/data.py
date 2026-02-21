"""ModelData container — holds all parsed Excel table data for a single benefit year."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ModelData:
    """All model data for a single benefit year, parsed from the CMS Excel tables."""

    benefit_year: int

    # Table 3: ICD-10 → CC crosswalk
    # Columns: ICD10, CC, Second_CC, Third_CC, MCE_Age_Condition, MCE_Sex_Condition,
    #          CC_Age_Split, CC_Sex_Split, Code_Valid_FY1, Code_Valid_FY2
    icd10_cc: pd.DataFrame = field(repr=False)

    # Table 4: HCC hierarchy — {hcc: [hccs_to_zero]}
    # e.g. {"1": [], "2": ["3", "4"], ...}
    hcc_hierarchy: dict[str, list[str]] = field(repr=False)

    # List of all valid HCC numbers in the model
    all_hccs: list[str] = field(repr=False)

    # Table 5 + Table 9: age-sex variable names by model segment
    # e.g. {"Adult": ["MAGE_LAST_21_24", ...], "Child": [...], "Infant": [...]}
    age_sex_vars: dict[str, list[str]] = field(repr=False)

    # Tables 6, 7: HCC group definitions by model
    # {model: {group_name: [hcc_numbers]}}
    # e.g. {"Adult": {"G01": ["019", "020", "021"], ...}}
    hcc_groups: dict[str, dict[str, list[str]]] = field(repr=False)

    # Table 6: RXC interaction definitions (adult only)
    # [{name: str, rxc: str, hccs: list[str], logic: "any"|"all_sets",
    #   hcc_sets: optional list of sets for complex logic}]
    rxc_interactions: list[dict] = field(repr=False)

    # Tables 6, 7: SEVERE trigger variables (HCCs and groups) by model
    # {model: [var_names]}
    severe_triggers: dict[str, list[str]] = field(repr=False)

    # Tables 6, 7: TRANSPLANT trigger variables by model
    transplant_triggers: dict[str, list[str]] = field(repr=False)

    # Tables 6, 7: Severe×HCC count bin definitions by model
    # {model: [(var_name, min_count, max_count_or_none)]}
    severe_hcc_count_bins: dict[str, list[tuple[str, int, int | None]]] = field(repr=False)

    # Tables 6, 7: Transplant×HCC count bin definitions by model
    transplant_hcc_count_bins: dict[str, list[tuple[str, int, int | None]]] = field(repr=False)

    # Table 6: Enrollment duration interaction vars (adult only)
    # [(var_name, enrol_month)] e.g. [("HCC_ED1", 1), ...]
    enrollment_duration_vars: list[tuple[str, int]] = field(repr=False)

    # Table 8: Infant severity level definitions
    # {severity_var: [hcc_numbers]}  ordered highest to lowest
    infant_severity_levels: dict[str, list[str]] = field(repr=False)

    # Table 8: Infant maturity category definitions
    # {maturity_var: {age: int, newborn_hccs: [str]}}
    infant_maturity_categories: list[dict] = field(repr=False)

    # Table 8: Infant maturity × severity interaction variable names
    # [(var_name, maturity_var, severity_var)]
    infant_maturity_severity_interactions: list[tuple[str, str, str]] = field(repr=False)

    # Table 9: Model factors DataFrame
    # Columns: Model, Variable, Platinum, Gold, Silver, Bronze, Catastrophic
    factors: pd.DataFrame = field(repr=False)

    # Tables 10a: NDC → RXC crosswalk
    # Columns: RXC (int), NDC (str)
    ndc_rxc: pd.DataFrame = field(repr=False)

    # Table 10b: HCPCS → RXC crosswalk
    # Columns: RXC (int), HCPCS (str)
    hcpcs_rxc: pd.DataFrame = field(repr=False)

    # Table 11: RXC hierarchy — {rxc: [rxcs_to_zero]}
    rxc_hierarchy: dict[str, list[str]] = field(repr=False)

    # All RXC numbers in the model
    all_rxcs: list[str] = field(repr=False)

    # Table 12: Model exclusions (informational)
    # {model: [excluded_hcc_numbers]}
    model_exclusions: dict[str, list[str]] = field(repr=False)

    # CSR indicator → factor mapping
    # {csr_indicator: csr_ra_factor}
    csr_factors: dict[int, float] = field(repr=False)

    # HCC_CNT exclusion: HCC number to exclude from count (e.g. "022" for adults)
    hcc_cnt_exclude: dict[str, str | None] = field(repr=False)
