# HHS-HCC DIY Model

A Python implementation of the CMS HHS-HCC "Do-It-Yourself" (DIY) risk adjustment model for the ACA individual and small group markets, covering benefit years 2023, 2024, and 2025.

## Background

Each year, CMS publishes [DIY instructions](https://www.cms.gov/marketplace/resources/regulations-guidance) and accompanying Excel tables that describe how to calculate Plan Liability Risk Scores (PLRS) for ACA marketplace enrollees. The instructions are written as a series of numbered algorithm steps with SAS-like pseudocode, and the Excel tables contain every crosswalk, hierarchy, coefficient, and variable definition needed to execute the model.

This project translates those instructions into a working Python implementation. It downloads the official CMS materials, parses the Excel tables into structured data, applies the full scoring algorithm to a population of enrollees, and produces three output files that document both the final risk scores and the intermediate logic that produced them.

The implementation is parameterized by benefit year &mdash; the same scoring engine handles 2023, 2024, and 2025, with all year-specific differences (coefficients, crosswalks, hierarchy rules) encoded in the parsed model data rather than in code branches.

## Use Cases

- **Validation and testing** &mdash; Run the model against simulated or real enrollee data and compare results to other implementations or expected outcomes.
- **Score decomposition** &mdash; The COMPONENTS output breaks every enrollee's risk score into its constituent parts (demographic factor, each HCC, each interaction term, RXC contributions), making it straightforward to understand why a particular score is what it is.
- **Education** &mdash; The codebase follows the CMS DIY steps closely enough to serve as a readable companion to the official instructions.
- **Prototyping** &mdash; Use as a foundation for experimenting with model variations or building downstream analytics.

## Requirements

- Python 3.10 or later
- Internet access for the initial CMS material download (~10 MB per benefit year, cached after first run)

## Installation

```bash
git clone https://github.com/bentwheel/hhshcc-diy-model.git
cd hhshcc-diy-model
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

## Usage

### Scoring a population

```bash
# Run the model for benefit year 2025
hhshcc-diy run --benefit-year 2025 --input-dir ./input --output-dir ./output

# With verbose logging
hhshcc-diy run -y 2025 -i ./input -o ./output -v
```

### Pre-downloading CMS materials

```bash
# Download materials for a benefit year without running the model
hhshcc-diy download --benefit-year 2025

# Specify a custom cache directory
hhshcc-diy download -y 2025 -d ./my-data
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--benefit-year` / `-y` | *(required)* | Benefit year: 2023, 2024, or 2025 |
| `--input-dir` / `-i` | *(required)* | Directory containing PERSON.csv, DIAG.csv, and optionally NDC.csv and HCPCS.csv |
| `--output-dir` / `-o` | *(required)* | Directory for output CSV files |
| `--data-dir` / `-d` | `./data` | Directory for cached CMS materials |
| `-v` / `--verbose` | off | Enable verbose (DEBUG-level) logging |

### Input Files

The model expects CSV files matching the specification produced by the companion [hhshcc-model-data-simulator](https://github.com/bentwheel/hhshcc-model-data-simulator):

| File | Required | Description |
|------|----------|-------------|
| `PERSON.csv` | Yes | One row per enrollee: `ENROLID`, `SEX` (1=Male, 2=Female), `DOB`, `AGE_LAST`, `METAL`, `CSR_INDICATOR`, `ENROLDURATION` |
| `DIAG.csv` | Yes | One row per diagnosis: `ENROLID`, `DIAG` (ICD-10-CM code) |
| `NDC.csv` | No | One row per drug: `ENROLID`, `NDC` (11-digit NDC code) |
| `HCPCS.csv` | No | One row per procedure: `ENROLID`, `HCPCS` |

### Output Files

Three CSV files are written to the output directory, each prefixed with the benefit year (e.g., `cy2025_`):

| File | Grain | Purpose |
|------|-------|---------|
| `COMPLETE` | One row per enrollee | Logic audit file &mdash; binary (1/0) indicators for every model variable (CCs, HCCs, RXCs, groups, interactions, severity flags) plus intermediate values like `HCC_CNT` and `MODEL_SEGMENT`. No weights or coefficients. |
| `DIGEST` | One row per enrollee | Summary file &mdash; `ENROLID`, all PERSON columns, and the final `HHS_HCC_RISK_SCORE`. |
| `COMPONENTS` | One row per enrollee &times; contributing variable | Score breakdown &mdash; `ENROLID`, all PERSON columns, `VARIABLE`, `WEIGHT`, and `CSR_ADJ_FACTOR`. Only variables with non-zero weight are included. The validation property `SUM(WEIGHT * CSR_ADJ_FACTOR) = HHS_HCC_RISK_SCORE` holds for every enrollee. |

### Included Demo Data

The `input/` directory ships with a pre-generated set of 1,000 simulated enrollees (benefit year 2025) produced by the [hhshcc-model-data-simulator](https://github.com/bentwheel/hhshcc-model-data-simulator) using MEPS 2023 data. You can run the model immediately against this data:

```bash
hhshcc-diy run -y 2025 -i ./input -o ./output -v
```

The demo population covers all three model segments (25 infants, 223 children, 752 adults), five metal levels, and CSR indicators 1 and 3. See `input/SUMMARY.txt` for a detailed breakdown.

### Running Tests

```bash
pytest
```

---

## How It Works

The sections below describe, in detail, how this implementation turns the official CMS materials into risk scores. This is not a rehash of the DIY instructions themselves &mdash; it describes the engineering decisions required to make those instructions executable in Python.

### Overview

The pipeline has five stages:

1. **Download** &mdash; Fetch the official PDF instructions and Excel tables from CMS.
2. **Parse** &mdash; Extract every table from the Excel workbook into structured Python objects.
3. **Load** &mdash; Read the enrollee-level input CSV files.
4. **Score** &mdash; Apply the full DIY algorithm to each enrollee.
5. **Output** &mdash; Write the three output CSV files.

### Stage 1: Downloading CMS Materials

Each benefit year has two files published by CMS: a PDF document containing the DIY instructions, and an Excel workbook containing all of the model tables. The URLs follow a consistent pattern under `https://www.cms.gov/files/document/` but with year-specific filenames and date suffixes that vary by release.

The download module (`ingest/download.py`) resolves the URLs from a static configuration, downloads both files into a year-specific subdirectory (e.g., `data/cy2025/`), and skips any file that already exists locally. The `data/` directory is gitignored.

### Stage 2: Parsing the Excel Workbook

This is the most complex stage. The CMS Excel workbook contains 11+ sheets, each with its own layout conventions, header rows, footnotes, and edge cases. The parser (`ingest/parse.py`) reads each sheet into a `ModelData` dataclass (`model/data.py`) that holds every crosswalk, hierarchy, coefficient, and variable definition needed by the scoring engine.

#### Table 3: ICD-10 &rarr; CC Crosswalk

Table 3 is the largest table &mdash; roughly 11,500 rows mapping ICD-10-CM diagnosis codes to Condition Categories (CCs) under the V08 HHS-HCC classification. Each row also contains:

- **Code validity flags** (`CODE_VALID_FY{year}`) indicating whether the ICD-10 code is valid in a given fiscal year.
- **MCE (Medicare Code Edit) conditions** that restrict which age or sex a diagnosis code is valid for (e.g., pregnancy codes restricted to females, neonatal codes restricted to age 0).
- **CC age splits** and **CC sex splits** that route the same ICD-10 code to different CC numbers depending on the enrollee's age or sex.

A critical parsing detail: CCs in the Excel file are stored as floating-point numbers. Most CCs are plain integers (e.g., `35.0` &rarr; CC 035), but some CCs have decimal suffixes representing "split" CCs (e.g., `35.1` &rarr; CC 035\_1, `35.2` &rarr; CC 035\_2). These split CCs correspond to clinically distinct conditions with different risk weights &mdash; for example, HCC 035\_1 is "Acute Liver Failure/Disease" while HCC 035\_2 is "Chronic Liver Failure/End-Stage Liver Disorders". The parser uses a `_format_cc()` helper that preserves these decimal suffixes as underscore-delimited strings (`"035_1"`, `"087_2"`, etc.) rather than truncating them.

All CC and HCC numbers are stored as zero-padded 3-digit strings throughout the system, with underscore suffixes for split categories (e.g., `"001"`, `"035_1"`, `"161_2"`).

#### Table 4: HCC Hierarchy

Table 4 defines the condition hierarchy &mdash; when a higher-severity HCC is present, it "zeros out" related lower-severity HCCs. For example, if an enrollee has both HCC 008 (Metastatic Cancer) and HCC 011 (Breast/Prostate/Colorectal and Other Cancers), the hierarchy removes HCC 011 because HCC 008 already captures a more severe version of the same disease group.

The parser normalizes all HCC keys to zero-padded format using `_normalize_hcc_key()` so that hierarchy keys align with the CC format from Table 3.

#### Table 5: Age-Sex Variables

Table 5 defines the demographic variables used in the model. The parser extracts variable names by model segment (Adult, Child, Infant) and filters to only those marked "Yes" in the "Used in Risk Score Formula" column. Variable names follow patterns like `MAGE_LAST_21_24` (Male, age 21&ndash;24) and `FAGE_LAST_60_GT` (Female, age 60+).

#### Tables 6, 7, 8: Variable Definitions (Adult, Child, Infant)

These are the most structurally complex tables. Each one defines, in SAS-like pseudocode, every scoring variable for its model segment. The parser processes these row by row, tracking context as it moves through different sections:

- **HCC Groups** (e.g., `G01`, `G02A`, `G15A`): Some HCCs are grouped into composite variables. When any HCC in a group is present, the group variable fires and the individual component HCCs are zeroed out of the score. The group variable has its own coefficient. The parser extracts HCC numbers from the SAS pseudocode using regex (`HHS_HCC\d{3}(?:_\d+)?`) and deduplicates them, because the pseudocode mentions each HCC in both the assignment and zeroing lines.
- **RXC Interactions** (Adult only): Thirteen interaction variables that fire when a specific Prescription Drug Category (RXC) and a corresponding HCC are both present. Some interactions have complex "AND" logic requiring HCCs from multiple disease sets. The parser detects `_AND_` patterns in variable names and splits the definition into separate HCC sets accordingly.
- **SEVERE and TRANSPLANT indicators**: Binary flags indicating whether any HCC or group variable from a defined trigger list is present. These feed into HCC count interaction bins (`SEVERE_HCC_COUNT1`, `SEVERE_HCC_COUNT2_3`, `SEVERE_HCC_COUNT10PLUS`, etc.).
- **Enrollment duration variables** (Adult only): `HCC_ED1` through `HCC_ED6`, which fire when an adult enrollee has at least one HCC and 6 or fewer months of enrollment.
- **Infant severity levels and maturity categories** (Infant only): Five severity levels (hierarchical, highest wins) and five maturity categories (Age 1, Extremely Immature, Immature, Premature Multiples, Term), which combine into 25 maturity &times; severity interaction variables.

#### Table 9: Model Factors (Coefficients)

Table 9 contains the actual risk weights &mdash; one row per scoring variable, with columns for each metal level (Platinum, Gold, Silver, Bronze, Catastrophic). The parser forward-fills the Model column (which spans multiple rows per segment) and builds a lookup keyed by `(segment, variable_name) → {metal: coefficient}`.

#### Tables 10a and 10b: NDC &rarr; RXC and HCPCS &rarr; RXC Crosswalks

These tables map National Drug Codes and HCPCS procedure codes to Prescription Drug Categories (RXCs). NDC codes are zero-padded to 11 digits; RXC codes are zero-padded to 2 digits.

#### Table 11: RXC Hierarchy

Analogous to Table 4 but for RXCs &mdash; higher-severity RXCs zero out lower-severity ones.

#### Table 12: Model Exclusions

An informational table listing which HCCs are excluded from each model segment (e.g., infant-specific HCCs excluded from the Adult model). Parsed for completeness but not directly used in scoring since the factor table already implicitly excludes these.

#### Table 13: CSR Indicators (CY2025 only)

Table 13 maps HIOS Variant IDs to CSR (Cost-Sharing Reduction) Indicators and their corresponding CSR Risk Adjustment factors. Only CY2025 includes this table in the Excel workbook; for CY2023 and CY2024, the parser falls back to a hardcoded default mapping. The CSR indicator is used solely to determine the CSR adjustment factor applied in Step 5 &mdash; it does not influence which metal level's coefficients are used for scoring. The input file is responsible for supplying both the correct metal level and the correct CSR indicator for each enrollee.

### Stage 3: Loading Input Files

The pipeline reads `PERSON.csv` and `DIAG.csv` (required), plus `NDC.csv` and `HCPCS.csv` (optional). Diagnosis codes are read as strings to preserve leading characters; NDC codes are read as strings and zero-padded to 11 digits.

### Stage 4: Scoring

The scoring engine (`model/engine.py`) implements the five steps described in the CMS DIY instructions. It processes each enrollee independently.

#### Initialization: Building Lookup Structures

Before scoring begins, the engine pre-builds four lookup dictionaries from the parsed `ModelData`:

- `_icd_lookup`: Maps each ICD-10-CM code to its crosswalk row(s), including CC assignments, MCE conditions, and split rules.
- `_ndc_lookup` / `_hcpcs_lookup`: Maps NDC and HCPCS codes to their RXC assignments.
- `_factor_lookup`: Maps `(segment, variable_name)` to a dict of `{metal_level: coefficient}`.

#### Step 1A: ICD-10 &rarr; CC &rarr; HCC

For each enrollee, every diagnosis code is processed through the crosswalk:

1. **Code validity**: The diagnosis must be marked valid (`Y`) in at least one `CODE_VALID_FY` column.
2. **MCE age condition**: If the crosswalk row specifies an age restriction (e.g., `"9 <= age <= 64"`), the enrollee's age must satisfy it. These conditions are stored as string expressions in the Excel file; the engine evaluates them with a regex-based parser that handles `age = N`, `age >= N`, `age <= N`, and `N <= age <= M` patterns.
3. **MCE sex condition**: If specified, the enrollee's sex must match.
4. **CC age split**: Routes the diagnosis to different CCs depending on age (e.g., `"age < 50"` vs. `"age >= 50"`).
5. **CC sex split**: Routes to different CCs depending on sex.
6. **CC collection**: All CCs from the primary, second, and third CC columns are collected.

After CC assignment, the **HCC hierarchy** (Table 4) is applied: for every HCC present, any lower-severity HCCs it dominates are removed. The surviving set of HCCs is what enters the scoring variables.

#### Step 1B: RXC Creation

NDC and HCPCS codes are mapped to RXCs via the Table 10a/10b crosswalks, and the RXC hierarchy (Table 11) is applied in the same manner as the HCC hierarchy.

#### Step 2: Variable Creation

This step assembles the full set of scoring variables for each enrollee. The process differs by model segment:

**Adult and Child models:**

1. **Age-sex variable**: Determined by matching the enrollee's age and sex to the variable name patterns (e.g., `MAGE_LAST_45_49`).
2. **Individual HCC flags**: Each surviving HCC becomes a variable (e.g., `HHS_HCC019`).
3. **HCC groups**: If any HCC in a group definition is present, the group variable fires (e.g., `G01`) and the component HCCs are removed from the individual HCC flags. The HCCs still count toward `HCC_CNT`.
4. **HCC count**: The total number of HCCs (before grouping removes them from individual flags, but after any segment-specific exclusion).
5. **SEVERE and TRANSPLANT indicators**: Binary flags set when any trigger HCC or group variable is present.
6. **SEVERE/TRANSPLANT HCC count bins**: Interaction variables combining the severity indicator with HCC count ranges (e.g., `SEVERE_HCC_COUNT2_3` fires when `SEVERE=1` and `HCC_CNT` is 2 or 3).
7. **Enrollment duration** (Adult only): If the enrollee has at least one HCC and &le;6 months of enrollment, the corresponding `HCC_ED{N}` variable fires.
8. **RXC interactions** (Adult only): For each RXC present, the engine checks whether any defined RXC-HCC interaction fires. If yes, the interaction variable is set (e.g., `RXC_01_X_HCC001`); if no interaction fires, the standalone RXC variable is set instead (e.g., `RXC_01`). Standalone and interaction are mutually exclusive.

**Infant model:**

1. **Age-sex variable**: `AGE0_MALE` or `AGE1_MALE` (males only; no demographic variable for female infants).
2. **Severity level**: Determined hierarchically (IHCC\_SEVERITY5 is highest, IHCC\_SEVERITY1 is lowest). The highest severity level for which the enrollee has any qualifying HCC is assigned.
3. **Maturity category**: One of five categories (AGE1, Extremely Immature, Immature, Premature Multiples, Term) based on age and the presence of specific newborn HCCs.
4. **Maturity &times; Severity interaction**: The single interaction variable (e.g., `TERM_X_SEVERITY2`) that corresponds to the enrollee's maturity category and severity level.

#### Steps 3 & 4: Factor Lookup and Score Calculation

For each active variable, the engine looks up the coefficient from Table 9 at the enrollee's scoring metal level. All non-zero coefficients are summed to produce the **unadjusted score**.

Coefficients are always looked up at the enrollee's own metal level as specified in the PERSON input file. It is the responsibility of the input file creator to ensure that `METAL` and `CSR_INDICATOR` are consistent for each enrollee (e.g., a member with CSR indicator 2 should already be listed with a Gold metal level in the input).

#### Step 5: CSR Adjustment

The unadjusted score is multiplied by the enrollee's CSR Risk Adjustment Factor (looked up by CSR indicator) to produce the final **Plan Liability Risk Score (PLRS)**.

The COMPONENTS output preserves this decomposition: `SUM(WEIGHT) * CSR_ADJ_FACTOR = HHS_HCC_RISK_SCORE` for every enrollee.

### Model Segments

| Segment | Age Range | Notable Features |
|---------|-----------|------------------|
| **Adult** | 21+ | HCC groups, RXC interactions, enrollment duration adjustments, SEVERE/TRANSPLANT indicators with HCC count bins |
| **Child** | 2&ndash;20 | HCC groups, SEVERE/TRANSPLANT indicators with HCC count bins; no RXC interactions, no enrollment duration |
| **Infant** | 0&ndash;1 | Maturity &times; Severity interaction model (25 variables); no HCC groups, no RXC interactions |

### Metal Levels

Five base metal levels &mdash; Platinum, Gold, Silver, Bronze, Catastrophic &mdash; each with their own set of coefficients in Table 9. Coefficients are always looked up at the metal level supplied in the PERSON input file. For Silver plans with Cost-Sharing Reductions (73% AV, 87% AV, 94% AV variants), the CSR adjustment is applied solely as a multiplier on the unadjusted score in Step 5. It is the responsibility of the input file creator to ensure that `METAL` and `CSR_INDICATOR` values are consistent for each enrollee.

### Year-Specific Behavior

The scoring engine has no year-specific code paths. All differences between benefit years are captured in the parsed `ModelData`:

- Different ICD-10 codes may be valid in different fiscal years (Table 3 code validity columns).
- Hierarchy rules, HCC groupings, and interaction definitions may change (Tables 4, 6&ndash;8).
- Coefficients differ by year (Table 9).
- Table 13 (CSR indicators from HIOS Variant IDs) is only present in CY2025; CY2023 and CY2024 use a hardcoded default mapping.

---

## Project Structure

```
hhshcc-diy-model/
├── pyproject.toml                    # pip-based project config
├── src/
│   └── hhshcc_diy/
│       ├── config.py                 # CMS URLs and benefit year configs
│       ├── ingest/
│       │   ├── download.py           # Download and cache CMS materials
│       │   └── parse.py              # Parse Excel tables → ModelData
│       ├── model/
│       │   ├── data.py               # ModelData dataclass
│       │   └── engine.py             # Scoring engine (Steps 1A–5)
│       ├── output.py                 # Write COMPLETE, DIGEST, COMPONENTS CSVs
│       ├── pipeline.py               # End-to-end orchestrator
│       └── cli.py                    # Click CLI entry point
├── input/                            # Demo input files (tracked in git)
│   ├── PERSON.csv                    # 1,000 simulated enrollees (BY 2025)
│   ├── DIAG.csv                      # 2,301 diagnosis records
│   ├── NDC.csv                       # 2,376 NDC drug records
│   ├── HCPCS.csv                     # 60 HCPCS procedure records
│   ├── SUMMARY.txt                   # Simulation run summary
│   └── manifest.json                 # Reproducibility manifest
├── output/                           # Scoring output (gitignored)
├── data/                             # Cached CMS materials (gitignored)
└── tests/
```

## Related Projects

- [hhshcc-model-data-simulator](https://github.com/bentwheel/hhshcc-model-data-simulator) &mdash; Generates realistic, HIPAA-safe test input files for this model using publicly available MEPS survey data. Use it to produce the PERSON.csv, DIAG.csv, NDC.csv, and HCPCS.csv files that this project consumes.

## Known Limitations

- **No RXC interactions for Child or Infant segments.** The CMS model defines RXC-HCC interactions only for the Adult model. NDC and HCPCS data is accepted for all segments but only contributes to Adult scoring.
- **MCE conditions are string-evaluated.** The MCE age conditions from Table 3 are stored as human-readable strings (e.g., `"9 <= age <= 64"`) and parsed with regex at runtime. Unusual condition formats not yet encountered in CY2023&ndash;2025 data may fall through to a permissive default.
- **No incremental scoring.** The engine scores the entire population in a single pass. There is no API for scoring a single enrollee without constructing a one-row DataFrame.
- **Coefficient precision.** Risk scores are rounded to 3 decimal places after CSR adjustment, matching the precision used in CMS example calculations.

## Disclaimer

This project was primarily written with AI assistance (Claude). The code has been reviewed and tested, but **no warranty is made regarding its correctness, completeness, or fitness for any particular purpose**. Use at your own risk.

This software is intended for **testing, education, and research purposes only**. Output risk scores may not match official CMS results due to differences in interpretation, rounding, or data preparation. Do not use these scores for regulatory reporting, rate filing, risk adjustment transfer calculations, or any official actuarial or compliance purpose without independent validation.

The authors are not affiliated with CMS. This project is not endorsed by or associated with the Centers for Medicare & Medicaid Services or any government agency.

## License

[MIT](LICENSE)
