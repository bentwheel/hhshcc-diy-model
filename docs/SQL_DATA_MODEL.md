# HHS-HCC DIY Model &mdash; SQL Data Model

This document describes how the CMS DIY model tables could be organized in a relational database. Each section maps a CMS Excel table (or group of related tables) to one or more SQL tables, with column definitions, keys, and notes on how the scoring engine would query them.

All tables are scoped by `benefit_year` so that multiple model years can coexist in a single database.

---

## Reference Tables (parsed from CMS Excel)

### `icd10_cc_crosswalk` &mdash; Table 3

The ICD-10 &rarr; CC crosswalk. One row per ICD-10 code per CC assignment. In the Excel file, a single ICD-10 code can produce up to three CCs (primary, second, third); in the SQL representation these are normalized into separate rows.

```sql
CREATE TABLE icd10_cc_crosswalk (
    benefit_year       INT          NOT NULL,
    icd10              VARCHAR(7)   NOT NULL,   -- e.g. 'E1010', 'S72001A'
    cc                 VARCHAR(5)   NOT NULL,   -- zero-padded: '001', '035_1'
    cc_position        SMALLINT     NOT NULL,   -- 1=primary, 2=second, 3=third
    code_valid_fy1     CHAR(1),                 -- 'Y' or 'N'
    code_valid_fy2     CHAR(1),                 -- 'Y' or 'N'
    mce_age_condition  VARCHAR(30),             -- e.g. '9 <= age <= 64', NULL if none
    mce_sex_condition  VARCHAR(10),             -- 'Male' or 'Female', NULL if none
    cc_age_split       VARCHAR(30),             -- e.g. 'age < 50', NULL if none
    cc_sex_split       VARCHAR(10),             -- 'Male' or 'Female', NULL if none
    PRIMARY KEY (benefit_year, icd10, cc, cc_position)
);
```

**Notes:**
- The Python implementation stores all three CC columns in a single DataFrame row. The SQL normalization into separate rows (with `cc_position`) eliminates NULLable second/third CC columns and simplifies joins.
- `code_valid_fy1` and `code_valid_fy2` correspond to the two fiscal year validity columns in the Excel file (e.g., FY2025 and FY2026 for benefit year 2025).
- CC numbers include underscore suffixes for split CCs: `'035_1'`, `'087_2'`, etc.

### `hcc_hierarchy` &mdash; Table 4

When a higher-severity HCC is present, it zeros out related lower-severity HCCs.

```sql
CREATE TABLE hcc_hierarchy (
    benefit_year  INT         NOT NULL,
    hcc           VARCHAR(5)  NOT NULL,   -- the dominant HCC
    hcc_to_zero   VARCHAR(5)  NOT NULL,   -- the subordinate HCC to remove
    PRIMARY KEY (benefit_year, hcc, hcc_to_zero)
);
```

**Example:** HCC 008 (Metastatic Cancer) zeroes out HCC 011 (Breast/Prostate/Colorectal Cancer):

```
benefit_year=2025, hcc='008', hcc_to_zero='011'
```

### `age_sex_variables` &mdash; Table 5

Defines demographic variable names by model segment.

```sql
CREATE TABLE age_sex_variables (
    benefit_year  INT          NOT NULL,
    segment       VARCHAR(10)  NOT NULL,   -- 'Adult', 'Child', 'Infant'
    variable      VARCHAR(30)  NOT NULL,   -- e.g. 'MAGE_LAST_21_24', 'FAGE_LAST_60_GT'
    PRIMARY KEY (benefit_year, segment, variable)
);
```

### `hcc_groups` &mdash; Tables 6, 7

Composite HCC groups. When any component HCC is present, the group fires and the individual HCCs are removed from scoring.

```sql
CREATE TABLE hcc_groups (
    benefit_year  INT          NOT NULL,
    segment       VARCHAR(10)  NOT NULL,   -- 'Adult' or 'Child'
    group_name    VARCHAR(10)  NOT NULL,   -- e.g. 'G01', 'G07A', 'G15A'
    hcc           VARCHAR(5)   NOT NULL,   -- component HCC
    PRIMARY KEY (benefit_year, segment, group_name, hcc)
);
```

**Example:** In CY2024, group G07A bundles HCC 070 and 071:

```
benefit_year=2024, segment='Adult', group_name='G07A', hcc='070'
benefit_year=2024, segment='Adult', group_name='G07A', hcc='071'
```

In CY2025, these rows do not exist (the group was dissolved).

### `rxc_interactions` &mdash; Table 6

RXC-HCC interaction definitions (Adult only). Each interaction fires when a specific RXC is present along with qualifying HCC(s).

```sql
CREATE TABLE rxc_interactions (
    benefit_year     INT          NOT NULL,
    interaction_name VARCHAR(40)  NOT NULL,   -- e.g. 'RXC_01_X_HCC001'
    rxc              VARCHAR(5)   NOT NULL,   -- e.g. '01'
    hcc_set          SMALLINT     NOT NULL DEFAULT 1,  -- for AND logic: set number
    hcc              VARCHAR(5)   NOT NULL,   -- qualifying HCC
    PRIMARY KEY (benefit_year, interaction_name, hcc_set, hcc)
);
```

**Notes:**
- Most interactions use simple "any" logic: the interaction fires if the RXC and *any* listed HCC are both present. These all have `hcc_set = 1`.
- Some interactions use "AND" logic across multiple HCC sets (the enrollee must have at least one HCC from *each* set). These have `hcc_set = 1, 2, ...` to distinguish the sets.
- When no interaction fires for a given RXC, the standalone RXC variable is used instead. Standalone and interaction are mutually exclusive.

### `severe_triggers` / `transplant_triggers` &mdash; Tables 6, 7

Variables (HCCs or group names) whose presence triggers the SEVERE or TRANSPLANT indicator.

```sql
CREATE TABLE severity_triggers (
    benefit_year   INT          NOT NULL,
    segment        VARCHAR(10)  NOT NULL,   -- 'Adult' or 'Child'
    trigger_type   VARCHAR(15)  NOT NULL,   -- 'SEVERE' or 'TRANSPLANT'
    trigger_var    VARCHAR(15)  NOT NULL,   -- HCC number or group name
    PRIMARY KEY (benefit_year, segment, trigger_type, trigger_var)
);
```

### `hcc_count_bins` &mdash; Tables 6, 7

Interaction variables combining a severity/transplant indicator with HCC count ranges.

```sql
CREATE TABLE hcc_count_bins (
    benefit_year  INT          NOT NULL,
    segment       VARCHAR(10)  NOT NULL,
    indicator     VARCHAR(15)  NOT NULL,   -- 'SEVERE' or 'TRANSPLANT'
    variable      VARCHAR(30)  NOT NULL,   -- e.g. 'SEVERE_HCC_COUNT2_3'
    min_count     INT          NOT NULL,   -- inclusive lower bound
    max_count     INT,                     -- inclusive upper bound, NULL = unbounded
    PRIMARY KEY (benefit_year, segment, indicator, variable)
);
```

**Example:**

```
variable='SEVERE_HCC_COUNT2_3',   min_count=2,  max_count=3
variable='SEVERE_HCC_COUNT10PLUS', min_count=10, max_count=NULL
```

### `enrollment_duration_vars` &mdash; Table 6

Enrollment duration interaction variables (Adult only). Fire when the enrollee has at least one HCC and enrollment duration &le; the specified month threshold.

```sql
CREATE TABLE enrollment_duration_vars (
    benefit_year  INT          NOT NULL,
    variable      VARCHAR(10)  NOT NULL,   -- e.g. 'HCC_ED1', 'HCC_ED6'
    enrol_month   INT          NOT NULL,   -- threshold: 1, 2, ..., 6
    PRIMARY KEY (benefit_year, variable)
);
```

### `infant_severity_levels` &mdash; Table 8

Infant severity level definitions. Ordered from highest (SEVERITY5) to lowest (SEVERITY1); the first level for which the enrollee has a qualifying HCC is assigned.

```sql
CREATE TABLE infant_severity_levels (
    benefit_year    INT          NOT NULL,
    severity_var    VARCHAR(20)  NOT NULL,   -- e.g. 'IHCC_SEVERITY5'
    severity_rank   SMALLINT     NOT NULL,   -- 5=highest, 1=lowest
    hcc             VARCHAR(5)   NOT NULL,   -- qualifying HCC
    PRIMARY KEY (benefit_year, severity_var, hcc)
);
```

### `infant_maturity_categories` &mdash; Table 8

Infant maturity category definitions.

```sql
CREATE TABLE infant_maturity_categories (
    benefit_year    INT          NOT NULL,
    maturity_var    VARCHAR(25)  NOT NULL,   -- e.g. 'TERM', 'EXTREMELY_IMMATURE'
    age             INT,                     -- required age (NULL = any)
    newborn_hcc     VARCHAR(5),              -- required newborn HCC (NULL = none)
    PRIMARY KEY (benefit_year, maturity_var)
);
```

### `infant_maturity_severity_interactions` &mdash; Table 8

The 25 maturity &times; severity interaction variables for the Infant model.

```sql
CREATE TABLE infant_maturity_severity_interactions (
    benefit_year   INT          NOT NULL,
    variable       VARCHAR(40)  NOT NULL,   -- e.g. 'TERM_X_SEVERITY2'
    maturity_var   VARCHAR(25)  NOT NULL,
    severity_var   VARCHAR(20)  NOT NULL,
    PRIMARY KEY (benefit_year, variable)
);
```

### `model_factors` &mdash; Table 9

Risk weights (coefficients) for every scoring variable, by segment and metal level.

```sql
CREATE TABLE model_factors (
    benefit_year  INT            NOT NULL,
    segment       VARCHAR(10)    NOT NULL,   -- 'Adult', 'Child', 'Infant'
    variable      VARCHAR(40)    NOT NULL,   -- e.g. 'MAGE_LAST_21_24', 'HHS_HCC019', 'G01'
    platinum      DECIMAL(10,6)  NOT NULL DEFAULT 0,
    gold          DECIMAL(10,6)  NOT NULL DEFAULT 0,
    silver        DECIMAL(10,6)  NOT NULL DEFAULT 0,
    bronze        DECIMAL(10,6)  NOT NULL DEFAULT 0,
    catastrophic  DECIMAL(10,6)  NOT NULL DEFAULT 0,
    PRIMARY KEY (benefit_year, segment, variable)
);
```

**Notes:**
- This table is the heart of the model. Every scoring variable (demographics, HCCs, groups, interactions, RXCs, severity bins, enrollment duration, infant interactions) has a row here.
- Variables that don't apply to a metal level have a coefficient of 0.
- A variable present in an enrollee's flag set but absent from this table contributes nothing to the score.

### `ndc_rxc_crosswalk` &mdash; Table 10a

Maps 11-digit NDC codes to Prescription Drug Categories.

```sql
CREATE TABLE ndc_rxc_crosswalk (
    benefit_year  INT          NOT NULL,
    ndc           CHAR(11)     NOT NULL,   -- zero-padded 11-digit NDC
    rxc           VARCHAR(5)   NOT NULL,   -- e.g. '01', '02'
    PRIMARY KEY (benefit_year, ndc)
);
```

### `hcpcs_rxc_crosswalk` &mdash; Table 10b

Maps HCPCS procedure codes to RXCs.

```sql
CREATE TABLE hcpcs_rxc_crosswalk (
    benefit_year  INT          NOT NULL,
    hcpcs         VARCHAR(5)   NOT NULL,
    rxc           VARCHAR(5)   NOT NULL,
    PRIMARY KEY (benefit_year, hcpcs)
);
```

### `rxc_hierarchy` &mdash; Table 11

RXC hierarchy, analogous to HCC hierarchy.

```sql
CREATE TABLE rxc_hierarchy (
    benefit_year  INT         NOT NULL,
    rxc           VARCHAR(5)  NOT NULL,   -- the dominant RXC
    rxc_to_zero   VARCHAR(5)  NOT NULL,   -- the subordinate RXC to remove
    PRIMARY KEY (benefit_year, rxc, rxc_to_zero)
);
```

### `model_exclusions` &mdash; Table 12

HCCs excluded from each model segment (informational).

```sql
CREATE TABLE model_exclusions (
    benefit_year  INT          NOT NULL,
    segment       VARCHAR(10)  NOT NULL,
    hcc           VARCHAR(5)   NOT NULL,
    PRIMARY KEY (benefit_year, segment, hcc)
);
```

### `csr_factors` &mdash; Table 13

CSR indicator to risk adjustment factor mapping.

```sql
CREATE TABLE csr_factors (
    benefit_year   INT            NOT NULL,
    csr_indicator  INT            NOT NULL,   -- 1 through 11
    csr_ra_factor  DECIMAL(4,2)   NOT NULL,   -- e.g. 1.00, 1.12, 1.51
    PRIMARY KEY (benefit_year, csr_indicator)
);
```

### `hcc_cnt_exclusion` &mdash; From Tables 6, 7

HCC numbers to exclude from the HCC count for specific segments.

```sql
CREATE TABLE hcc_cnt_exclusion (
    benefit_year  INT          NOT NULL,
    segment       VARCHAR(10)  NOT NULL,   -- 'Adult' or 'Child'
    hcc           VARCHAR(5)   NOT NULL,   -- HCC to exclude from count
    PRIMARY KEY (benefit_year, segment, hcc)
);
```

---

## Input Tables (enrollee data)

These correspond to the CSV input files consumed by the scoring engine.

```sql
CREATE TABLE person (
    enrolid          VARCHAR(30)  NOT NULL PRIMARY KEY,
    sex              SMALLINT     NOT NULL,  -- 1=Male, 2=Female
    dob              INT,                    -- YYYYMMDD
    age_last         INT          NOT NULL,  -- age as of benefit year
    metal            VARCHAR(15)  NOT NULL,  -- 'platinum','gold','silver','bronze','catastrophic'
    csr_indicator    INT          NOT NULL,  -- 1-11
    enrolduration    INT          NOT NULL   -- months of enrollment (1-12)
);

CREATE TABLE diagnosis (
    enrolid  VARCHAR(30)  NOT NULL,
    diag     VARCHAR(7)   NOT NULL,  -- ICD-10-CM code, no dots
    FOREIGN KEY (enrolid) REFERENCES person(enrolid)
);
CREATE INDEX idx_diagnosis_enrolid ON diagnosis(enrolid);

CREATE TABLE ndc_claim (
    enrolid  VARCHAR(30)  NOT NULL,
    ndc      CHAR(11)     NOT NULL,  -- zero-padded 11-digit NDC
    FOREIGN KEY (enrolid) REFERENCES person(enrolid)
);
CREATE INDEX idx_ndc_enrolid ON ndc_claim(enrolid);

CREATE TABLE hcpcs_claim (
    enrolid  VARCHAR(30)  NOT NULL,
    hcpcs    VARCHAR(5)   NOT NULL,
    FOREIGN KEY (enrolid) REFERENCES person(enrolid)
);
CREATE INDEX idx_hcpcs_enrolid ON hcpcs_claim(enrolid);
```

---

## Output Tables (scoring results)

These correspond to the three output CSV files.

```sql
-- DIGEST: one row per enrollee with the final risk score
CREATE TABLE score_digest (
    benefit_year       INT            NOT NULL,
    enrolid            VARCHAR(30)    NOT NULL,
    hhs_hcc_risk_score DECIMAL(10,3)  NOT NULL,
    PRIMARY KEY (benefit_year, enrolid)
);

-- COMPONENTS: one row per enrollee x contributing variable
CREATE TABLE score_components (
    benefit_year    INT            NOT NULL,
    enrolid         VARCHAR(30)    NOT NULL,
    variable        VARCHAR(40)    NOT NULL,   -- e.g. 'FAGE_LAST_50_54', 'G01', 'RXC_01'
    weight          DECIMAL(10,6)  NOT NULL,   -- coefficient at enrollee's metal level
    csr_adj_factor  DECIMAL(4,2)   NOT NULL,   -- CSR RA factor for this enrollee
    PRIMARY KEY (benefit_year, enrolid, variable)
);
-- Validation: SUM(weight * csr_adj_factor) = hhs_hcc_risk_score for each enrollee
```

The COMPLETE output (binary flags for every model variable) is wide-format and not well suited to a relational table. A normalized representation would be:

```sql
-- COMPLETE (normalized): one row per enrollee x active flag
CREATE TABLE score_complete (
    benefit_year  INT          NOT NULL,
    enrolid       VARCHAR(30)  NOT NULL,
    variable      VARCHAR(40)  NOT NULL,   -- CC_019, HCC_019, G01, SEVERE, HCC_CNT, etc.
    value         VARCHAR(20)  NOT NULL,   -- '1' for flags, numeric string for counts
    PRIMARY KEY (benefit_year, enrolid, variable)
);
```

---

## Entity-Relationship Summary

```
icd10_cc_crosswalk ──┐
                     ├── referenced during Step 1A (ICD-10 → CC → HCC)
hcc_hierarchy ───────┘

ndc_rxc_crosswalk ───┐
hcpcs_rxc_crosswalk ─┤── referenced during Step 1B (NDC/HCPCS → RXC)
rxc_hierarchy ───────┘

age_sex_variables ───┐
hcc_groups ──────────┤
rxc_interactions ────┤
severity_triggers ───┤── referenced during Step 2 (variable creation)
hcc_count_bins ──────┤
enrollment_dur_vars ─┤
infant_severity_* ───┤
infant_maturity_* ───┘

model_factors ───────── referenced during Steps 3-4 (coefficient lookup + summation)

csr_factors ─────────── referenced during Step 5 (CSR adjustment)

model_exclusions ────── informational only (not used in scoring)
hcc_cnt_exclusion ───── referenced during Step 2 (HCC count calculation)
```

---

## Mapping to Python `ModelData`

| SQL Table | `ModelData` Field | CMS Table |
|-----------|-------------------|-----------|
| `icd10_cc_crosswalk` | `icd10_cc` (DataFrame) | Table 3 |
| `hcc_hierarchy` | `hcc_hierarchy` (dict) | Table 4 |
| `age_sex_variables` | `age_sex_vars` (dict) | Table 5 |
| `hcc_groups` | `hcc_groups` (dict) | Tables 6, 7 |
| `rxc_interactions` | `rxc_interactions` (list[dict]) | Table 6 |
| `severity_triggers` | `severe_triggers`, `transplant_triggers` (dict) | Tables 6, 7 |
| `hcc_count_bins` | `severe_hcc_count_bins`, `transplant_hcc_count_bins` (dict) | Tables 6, 7 |
| `enrollment_duration_vars` | `enrollment_duration_vars` (list[tuple]) | Table 6 |
| `infant_severity_levels` | `infant_severity_levels` (dict) | Table 8 |
| `infant_maturity_categories` | `infant_maturity_categories` (list[dict]) | Table 8 |
| `infant_maturity_severity_interactions` | `infant_maturity_severity_interactions` (list[tuple]) | Table 8 |
| `model_factors` | `factors` (DataFrame) | Table 9 |
| `ndc_rxc_crosswalk` | `ndc_rxc` (DataFrame) | Table 10a |
| `hcpcs_rxc_crosswalk` | `hcpcs_rxc` (DataFrame) | Table 10b |
| `rxc_hierarchy` | `rxc_hierarchy` (dict) | Table 11 |
| `model_exclusions` | `model_exclusions` (dict) | Table 12 |
| `csr_factors` | `csr_factors` (dict) | Table 13 |
| `hcc_cnt_exclusion` | `hcc_cnt_exclude` (dict) | Tables 6, 7 |
