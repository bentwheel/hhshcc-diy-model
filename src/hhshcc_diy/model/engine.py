"""HHS-HCC DIY Scoring Engine — implements Steps 1A through 5."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from hhshcc_diy.model.data import ModelData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ScoringResult:
    """Results of scoring a population."""

    # One row per enrollee: all binary flags and intermediate variables
    complete: pd.DataFrame

    # One row per enrollee: ENROLID + risk score
    digest: pd.DataFrame

    # One row per enrollee × contributing component
    components: pd.DataFrame


# ---------------------------------------------------------------------------
# MCE condition evaluator
# ---------------------------------------------------------------------------

def _eval_mce_age(condition: str, age: int) -> bool:
    """Evaluate an MCE age condition string against an age value.

    Supported formats:
        'age = 0', 'age >=15', '0 <= age <= 17', '9 <= age <= 64'
    """
    condition = condition.strip()

    # Pattern: 'age = N'
    m = re.match(r"age\s*=\s*(\d+)$", condition)
    if m:
        return age == int(m.group(1))

    # Pattern: 'age >= N' or 'age >=N'
    m = re.match(r"age\s*>=\s*(\d+)$", condition)
    if m:
        return age >= int(m.group(1))

    # Pattern: 'age <= N'
    m = re.match(r"age\s*<=\s*(\d+)$", condition)
    if m:
        return age <= int(m.group(1))

    # Pattern: 'N <= age <= M'
    m = re.match(r"(\d+)\s*<=\s*age\s*<=\s*(\d+)$", condition)
    if m:
        return int(m.group(1)) <= age <= int(m.group(2))

    logger.warning("Unknown MCE age condition: '%s'", condition)
    return True  # Permissive fallback


def _eval_cc_age_split(condition: str, age: int) -> bool:
    """Evaluate a CC age split condition string."""
    condition = condition.strip()

    m = re.match(r"age\s*<\s*(\d+)$", condition)
    if m:
        return age < int(m.group(1))

    m = re.match(r"age\s*>=\s*(\d+)$", condition)
    if m:
        return age >= int(m.group(1))

    m = re.match(r"age\s*=\s*(\d+)$", condition)
    if m:
        return age == int(m.group(1))

    m = re.match(r"(\d+)\s*<=\s*age\s*<=\s*(\d+)$", condition)
    if m:
        return int(m.group(1)) <= age <= int(m.group(2))

    logger.warning("Unknown CC age split condition: '%s'", condition)
    return True


# ---------------------------------------------------------------------------
# Scoring Engine
# ---------------------------------------------------------------------------

class ScoringEngine:
    """Scores a population of enrollees using the HHS-HCC DIY model."""

    def __init__(self, model_data: ModelData):
        self.md = model_data
        self._build_lookups()

    # -----------------------------------------------------------------------
    # Lookup construction
    # -----------------------------------------------------------------------

    def _build_lookups(self):
        """Pre-build lookup structures from ModelData."""
        md = self.md

        # ICD-10 → list of crosswalk rows (dicts)
        self._icd_lookup: dict[str, list[dict]] = {}
        for _, row in md.icd10_cc.iterrows():
            icd = str(row["ICD10"]).strip().upper()
            entry = {
                "cc": row.get("CC"),
                "second_cc": row.get("SECOND_CC"),
                "third_cc": row.get("THIRD_CC"),
                "mce_age": row.get("MCE_AGE_CONDITION"),
                "mce_sex": row.get("MCE_SEX_CONDITION"),
                "cc_age_split": row.get("CC_AGE_SPLIT"),
                "cc_sex_split": row.get("CC_SEX_SPLIT"),
            }
            # Code validity: check across FY columns
            valid = False
            for col in md.icd10_cc.columns:
                if col.startswith("CODE_VALID_FY"):
                    if str(row.get(col, "")).strip().upper() == "Y":
                        valid = True
                        break
            entry["valid"] = valid
            self._icd_lookup.setdefault(icd, []).append(entry)

        # NDC → RXC
        self._ndc_lookup: dict[str, str] = {}
        for _, row in md.ndc_rxc.iterrows():
            self._ndc_lookup[str(row["NDC"]).strip()] = str(row["RXC"]).strip()

        # HCPCS → RXC
        self._hcpcs_lookup: dict[str, str] = {}
        for _, row in md.hcpcs_rxc.iterrows():
            self._hcpcs_lookup[str(row["HCPCS"]).strip()] = str(row["RXC"]).strip()

        # Factor lookup: (model, variable) → {metal: coefficient}
        self._factor_lookup: dict[tuple[str, str], dict[str, float]] = {}
        metals = ["Platinum", "Gold", "Silver", "Bronze", "Catastrophic"]
        for _, row in md.factors.iterrows():
            model = str(row["Model"]).strip()
            var = str(row["Variable"]).strip()
            coeffs = {}
            for metal in metals:
                if metal in row and pd.notna(row[metal]):
                    coeffs[metal.lower()] = float(row[metal])
            self._factor_lookup[(model, var)] = coeffs

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def score(
        self,
        person_df: pd.DataFrame,
        diag_df: pd.DataFrame,
        ndc_df: pd.DataFrame | None = None,
        hcpcs_df: pd.DataFrame | None = None,
    ) -> ScoringResult:
        """Score a population.

        Expected columns:
            person_df: ENROLID, SEX (1=M, 2=F), AGE_LAST, METAL, CSR_INDICATOR,
                       ENROLDURATION
            diag_df:   ENROLID, DIAG
            ndc_df:    ENROLID, NDC  (optional)
            hcpcs_df:  ENROLID, HCPCS (optional)
        """
        md = self.md

        # Build per-enrollee diagnosis sets
        diag_by_enrollee: dict[Any, list[str]] = {}
        for _, row in diag_df.iterrows():
            eid = row["ENROLID"]
            diag = str(row["DIAG"]).strip().upper()
            diag_by_enrollee.setdefault(eid, []).append(diag)

        # Build per-enrollee NDC sets
        ndc_by_enrollee: dict[Any, set[str]] = {}
        if ndc_df is not None and not ndc_df.empty:
            for _, row in ndc_df.iterrows():
                eid = row["ENROLID"]
                ndc = str(row["NDC"]).strip().zfill(11)
                ndc_by_enrollee.setdefault(eid, set()).add(ndc)

        # Build per-enrollee HCPCS sets
        hcpcs_by_enrollee: dict[Any, set[str]] = {}
        if hcpcs_df is not None and not hcpcs_df.empty:
            for _, row in hcpcs_df.iterrows():
                eid = row["ENROLID"]
                hcpcs = str(row["HCPCS"]).strip()
                hcpcs_by_enrollee.setdefault(eid, set()).add(hcpcs)

        complete_rows = []
        component_rows = []

        for _, person in person_df.iterrows():
            eid = person["ENROLID"]
            age = int(person["AGE_LAST"])
            sex = int(person["SEX"])  # 1=Male, 2=Female
            metal = str(person["METAL"]).strip().lower()
            csr_ind = int(person["CSR_INDICATOR"])
            enrol_months = int(person["ENROLDURATION"])

            # Determine model segment
            if age <= 1:
                segment = "Infant"
            elif age <= 20:
                segment = "Child"
            else:
                segment = "Adult"

            # CSR adjustment factor (Step 5 multiplier)
            csr_factor = md.csr_factors.get(csr_ind, 1.0)
            # Coefficients are always looked up at the enrollee's own metal level.
            # The input file is responsible for supplying the correct METAL value.
            scoring_metal = metal

            # ----- Step 1A: ICD-10 → CC → HCC -----
            diagnoses = diag_by_enrollee.get(eid, [])
            ccs = self._step1a_diagnoses_to_ccs(diagnoses, age, sex)
            hccs_pre_hierarchy = set(ccs)

            # Apply hierarchy (Table 4)
            hccs = self._apply_hcc_hierarchy(ccs)

            # ----- Step 1B: RXC creation -----
            ndcs = ndc_by_enrollee.get(eid, set())
            hcpcses = hcpcs_by_enrollee.get(eid, set())
            rxcs = self._step1b_rxc_creation(ndcs, hcpcses)

            # ----- Step 2: Variable creation -----
            flags, extra_vars = self._step2_create_variables(
                segment, age, sex, hccs, rxcs, enrol_months
            )

            # ----- Step 3 & 4: Factor lookup and score calculation -----
            components, unadjusted_score = self._step3_4_score(
                segment, scoring_metal, flags
            )

            # ----- Step 5: CSR adjustment -----
            plrs = round(unadjusted_score * csr_factor, 3)

            # Build COMPLETE row
            complete_row = {"ENROLID": eid, "MODEL_SEGMENT": segment}
            # Add all CC flags
            for cc in sorted(hccs_pre_hierarchy):
                complete_row[f"CC_{cc}"] = 1
            # Add all HCC flags (post-hierarchy)
            for hcc in sorted(hccs):
                complete_row[f"HCC_{hcc}"] = 1
            # Add all variable flags
            for var_name, val in sorted(flags.items()):
                if val:
                    complete_row[var_name] = 1
            # Add intermediate variables
            for k, v in extra_vars.items():
                complete_row[k] = v
            complete_row["UNADJUSTED_SCORE"] = unadjusted_score
            complete_row["CSR_FACTOR"] = csr_factor
            complete_row["HHS_HCC_RISK_SCORE"] = plrs
            complete_rows.append(complete_row)

            # Build COMPONENTS rows
            for var_name, weight in components:
                component_rows.append({
                    "ENROLID": eid,
                    "VARIABLE": var_name,
                    "WEIGHT": weight,
                    "CSR_ADJ_FACTOR": csr_factor,
                })

        # Assemble DataFrames
        complete_df = pd.DataFrame(complete_rows).fillna(0)
        digest_df = complete_df[["ENROLID", "HHS_HCC_RISK_SCORE"]].copy()

        # Merge PERSON columns into outputs
        person_cols = [c for c in person_df.columns if c != "ENROLID"]
        complete_df = complete_df.merge(
            person_df[["ENROLID"] + person_cols], on="ENROLID", how="left"
        )
        digest_df = digest_df.merge(
            person_df[["ENROLID"] + person_cols], on="ENROLID", how="left"
        )

        components_df = pd.DataFrame(component_rows)
        if not components_df.empty:
            components_df = components_df.merge(
                person_df[["ENROLID"] + person_cols], on="ENROLID", how="left"
            )

        # Sort outputs by ENROLID; COMPONENTS additionally by VARIABLE
        complete_df = complete_df.sort_values("ENROLID").reset_index(drop=True)
        digest_df = digest_df.sort_values("ENROLID").reset_index(drop=True)
        if not components_df.empty:
            components_df = components_df.sort_values(
                ["ENROLID", "VARIABLE"]
            ).reset_index(drop=True)

        return ScoringResult(
            complete=complete_df,
            digest=digest_df,
            components=components_df,
        )

    # -----------------------------------------------------------------------
    # Step 1A: ICD-10 → CC → HCC
    # -----------------------------------------------------------------------

    def _step1a_diagnoses_to_ccs(
        self, diagnoses: list[str], age: int, sex: int
    ) -> set[str]:
        """Map ICD-10 diagnoses to CCs, applying MCE and splits."""
        ccs: set[str] = set()
        sex_str = "male" if sex == 1 else "female"

        for diag in diagnoses:
            rows = self._icd_lookup.get(diag, [])
            for entry in rows:
                # Code validity check
                if not entry["valid"]:
                    continue

                # MCE age condition
                mce_age = entry["mce_age"]
                if pd.notna(mce_age) and mce_age:
                    if not _eval_mce_age(str(mce_age), age):
                        continue

                # MCE sex condition
                mce_sex = entry["mce_sex"]
                if pd.notna(mce_sex) and str(mce_sex).strip():
                    if str(mce_sex).strip().lower() != sex_str:
                        continue

                # CC age split
                cc_age_split = entry["cc_age_split"]
                if pd.notna(cc_age_split) and str(cc_age_split).strip():
                    if not _eval_cc_age_split(str(cc_age_split), age):
                        continue

                # CC sex split
                cc_sex_split = entry["cc_sex_split"]
                if pd.notna(cc_sex_split) and str(cc_sex_split).strip():
                    if str(cc_sex_split).strip().lower() != sex_str:
                        continue

                # Collect CCs
                for cc_field in ("cc", "second_cc", "third_cc"):
                    cc_val = entry[cc_field]
                    if cc_val is not None and str(cc_val).strip():
                        ccs.add(str(cc_val).strip().zfill(3))

        return ccs

    def _apply_hcc_hierarchy(self, ccs: set[str]) -> set[str]:
        """Apply HCC hierarchy — zero out lower-severity CCs."""
        hccs = set(ccs)
        for hcc, zeros in self.md.hcc_hierarchy.items():
            if hcc in hccs:
                for z in zeros:
                    hccs.discard(z)
        return hccs

    # -----------------------------------------------------------------------
    # Step 1B: RXC creation
    # -----------------------------------------------------------------------

    def _step1b_rxc_creation(
        self, ndcs: set[str], hcpcses: set[str]
    ) -> set[str]:
        """Map NDC/HCPCS codes to RXCs and apply RXC hierarchy."""
        rxcs: set[str] = set()

        for ndc in ndcs:
            rxc = self._ndc_lookup.get(ndc)
            if rxc:
                rxcs.add(rxc)

        for hcpcs in hcpcses:
            rxc = self._hcpcs_lookup.get(hcpcs)
            if rxc:
                rxcs.add(rxc)

        # Apply RXC hierarchy
        for rxc, zeros in self.md.rxc_hierarchy.items():
            if rxc in rxcs:
                for z in zeros:
                    rxcs.discard(z)

        return rxcs

    # -----------------------------------------------------------------------
    # Step 2: Variable creation
    # -----------------------------------------------------------------------

    def _step2_create_variables(
        self,
        segment: str,
        age: int,
        sex: int,
        hccs: set[str],
        rxcs: set[str],
        enrol_months: int,
    ) -> tuple[dict[str, bool], dict[str, Any]]:
        """Create all scoring variables for an enrollee.

        Returns:
            flags: {variable_name: True/False}
            extra_vars: {intermediate_var_name: value}
        """
        md = self.md
        flags: dict[str, bool] = {}
        extra: dict[str, Any] = {}

        # --- Age-sex variable ---
        age_sex_var = self._determine_age_sex_var(segment, age, sex)
        if age_sex_var:
            flags[age_sex_var] = True
        extra["AGE_SEX_VAR"] = age_sex_var or ""

        if segment == "Infant":
            self._create_infant_variables(age, sex, hccs, flags, extra)
            return flags, extra

        # --- HCC flags (pre-group) ---
        # Individual HCCs as scoring variables (HHS_HCC001, etc.)
        for hcc in hccs:
            flags[f"HHS_HCC{hcc}"] = True

        # --- HCC Groups ---
        # When a group fires, the group variable is set and component HCCs
        # are zeroed out of the individual HCC flags
        groups = md.hcc_groups.get(segment, {})
        active_groups: set[str] = set()
        zeroed_hccs: set[str] = set()
        for group_name, group_hccs in groups.items():
            if any(h in hccs for h in group_hccs):
                flags[group_name] = True
                active_groups.add(group_name)
                for h in group_hccs:
                    zeroed_hccs.add(h)

        # Zero component HCCs that were absorbed by groups
        for h in zeroed_hccs:
            flags.pop(f"HHS_HCC{h}", None)

        # The remaining individual HCC flags after grouping
        remaining_hccs = hccs - zeroed_hccs

        # --- HCC_CNT ---
        exclude = md.hcc_cnt_exclude.get(segment)
        counted_hccs = remaining_hccs.copy()
        if exclude:
            counted_hccs.discard(exclude)
        # Also count HCCs that were grouped (groups replace individual HCCs
        # but the HCCs still count toward HCC_CNT)
        hcc_cnt = len(hccs)
        if exclude and exclude in hccs:
            hcc_cnt -= 1
        extra["HCC_CNT"] = hcc_cnt

        # --- SEVERE and TRANSPLANT indicators ---
        severe = self._check_severity_indicator(
            segment, hccs, active_groups, "severe"
        )
        transplant = self._check_severity_indicator(
            segment, hccs, active_groups, "transplant"
        )
        extra["SEVERE"] = int(severe)
        extra["TRANSPLANT"] = int(transplant)

        # --- SEVERE_HCC_COUNT bins ---
        if severe:
            for var_name, min_val, max_val in md.severe_hcc_count_bins.get(segment, []):
                if max_val is None:
                    if hcc_cnt >= min_val:
                        flags[var_name] = True
                elif min_val == max_val:
                    if hcc_cnt == min_val:
                        flags[var_name] = True
                else:
                    if min_val <= hcc_cnt <= max_val:
                        flags[var_name] = True

        # --- TRANSPLANT_HCC_COUNT bins ---
        if transplant:
            for var_name, min_val, max_val in md.transplant_hcc_count_bins.get(segment, []):
                if max_val is None:
                    if hcc_cnt >= min_val:
                        flags[var_name] = True
                elif min_val == max_val:
                    if hcc_cnt == min_val:
                        flags[var_name] = True
                else:
                    if min_val <= hcc_cnt <= max_val:
                        flags[var_name] = True

        # --- Enrollment duration (Adult only) ---
        if segment == "Adult" and hcc_cnt >= 1:
            for var_name, month in md.enrollment_duration_vars:
                if enrol_months == month:
                    flags[var_name] = True

        # --- RXC interactions (Adult only) ---
        if segment == "Adult":
            self._create_rxc_variables(rxcs, hccs, flags)

        return flags, extra

    def _determine_age_sex_var(
        self, segment: str, age: int, sex: int
    ) -> str | None:
        """Determine the age-sex demographic variable for an enrollee."""
        prefix = "M" if sex == 1 else "F"

        if segment == "Infant":
            # AGE0_MALE or AGE1_MALE (only for males)
            if sex == 1:
                return f"AGE{age}_MALE"
            return None

        # Build all candidate variables for this segment
        vars_list = self.md.age_sex_vars.get(segment, [])
        for var in vars_list:
            if not var.startswith(prefix):
                continue
            # Parse the age range from variable name
            # Patterns: MAGE_LAST_21_24, FAGE_LAST_60_GT, AGE0_MALE
            m = re.match(r"[MF]AGE_LAST_(\d+)_(\d+)$", var)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo <= age <= hi:
                    return var
                continue

            m = re.match(r"[MF]AGE_LAST_(\d+)_GT$", var)
            if m:
                lo = int(m.group(1))
                if age >= lo:
                    return var
                continue

        return None

    def _check_severity_indicator(
        self,
        segment: str,
        hccs: set[str],
        active_groups: set[str],
        indicator_type: str,
    ) -> bool:
        """Check if SEVERE or TRANSPLANT indicator is triggered."""
        md = self.md
        if indicator_type == "severe":
            triggers = md.severe_triggers.get(segment, [])
        else:
            triggers = md.transplant_triggers.get(segment, [])

        for trigger in triggers:
            if trigger.startswith("HHS_HCC"):
                hcc_num = trigger.replace("HHS_HCC", "")
                if hcc_num in hccs:
                    return True
            elif trigger.startswith("G"):
                if trigger in active_groups:
                    return True

        return False

    def _create_rxc_variables(
        self,
        rxcs: set[str],
        hccs: set[str],
        flags: dict[str, bool],
    ):
        """Create RXC standalone and interaction variables (Adult only).

        Logic: For each RXC present, check if any interaction condition fires.
        If yes, set interaction variable(s). If no interaction fires, set
        standalone RXC variable.
        """
        md = self.md

        # Group interactions by RXC number
        interactions_by_rxc: dict[str, list[dict]] = {}
        for inter in md.rxc_interactions:
            interactions_by_rxc.setdefault(inter["rxc"], []).append(inter)

        for rxc in rxcs:
            inters = interactions_by_rxc.get(rxc, [])
            any_interaction_fired = False

            for inter in inters:
                fired = False
                if inter["logic"] == "any":
                    # RXC present AND any HCC in the list present
                    if any(h in hccs for h in inter.get("hccs", [])):
                        fired = True
                elif inter["logic"] == "all_sets":
                    # RXC present AND at least one HCC from each set present
                    if all(
                        any(h in hccs for h in hcc_set)
                        for hcc_set in inter.get("hcc_sets", [])
                    ):
                        fired = True

                if fired:
                    flags[inter["name"]] = True
                    any_interaction_fired = True

            # Standalone RXC: only if no interaction fired
            if not any_interaction_fired:
                flags[f"RXC_{rxc}"] = True
            # If interactions fired, we still flag standalone in COMPLETE for audit
            # but it doesn't get a factor — handled in step 3/4
            # Actually per the model: standalone is mutually exclusive with interactions
            # The standalone factor only applies when no interaction fires.

    def _create_infant_variables(
        self,
        age: int,
        sex: int,
        hccs: set[str],
        flags: dict[str, bool],
        extra: dict[str, Any],
    ):
        """Create infant model variables (maturity × severity interactions)."""
        md = self.md

        # Determine severity level (hierarchical — highest wins)
        severity = None
        for sev_var in ["IHCC_SEVERITY5", "IHCC_SEVERITY4", "IHCC_SEVERITY3",
                        "IHCC_SEVERITY2", "IHCC_SEVERITY1"]:
            sev_hccs = md.infant_severity_levels.get(sev_var, [])
            if any(h in hccs for h in sev_hccs):
                severity = sev_var
                break
        if severity is None:
            severity = "IHCC_SEVERITY1"  # Default lowest severity

        extra["INFANT_SEVERITY"] = severity

        # Determine maturity category
        maturity = None
        for mat_def in md.infant_maturity_categories:
            name = mat_def["name"]
            mat_age = mat_def.get("age")
            mat_hccs = mat_def.get("newborn_hccs", [])

            if name == "IHCC_AGE1" and age == 1:
                maturity = name
                break
            elif name == "IHCC_TERM" and age == 0 and not any(h in hccs for h in mat_hccs):
                maturity = name
                break
            elif name != "IHCC_AGE1" and name != "IHCC_TERM":
                if age == 0 and any(h in hccs for h in mat_hccs):
                    maturity = name
                    break

        if maturity is None:
            maturity = "IHCC_TERM"

        extra["INFANT_MATURITY"] = maturity

        # Set maturity × severity interaction variable
        for var_name, mat_var, sev_var in md.infant_maturity_severity_interactions:
            if mat_var == maturity and sev_var == severity:
                flags[var_name] = True
                break

    # -----------------------------------------------------------------------
    # Steps 3 & 4: Factor lookup and score calculation
    # -----------------------------------------------------------------------

    def _step3_4_score(
        self,
        segment: str,
        metal: str,
        flags: dict[str, bool],
    ) -> tuple[list[tuple[str, float]], float]:
        """Look up factors and calculate unadjusted score.

        Returns:
            components: [(variable_name, weight), ...]
            unadjusted_score: float
        """
        components: list[tuple[str, float]] = []
        total = 0.0

        for var_name, is_set in flags.items():
            if not is_set:
                continue

            coeffs = self._factor_lookup.get((segment, var_name))
            if coeffs is None:
                continue

            weight = coeffs.get(metal, 0.0)
            if weight != 0.0:
                components.append((var_name, weight))
                total += weight

        return components, round(total, 6)
