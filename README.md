# Heidi Systems — Berlin Hausverwaltungen Lead Generation Engine

> **Take-Home Case Submission:** AI Agent Builder Candidate  
> **Role:** Senior Python Engineer & AI Agent Builder  
> **Target Customer:** Commercial & Private Property Managers (*Hausverwaltungen*) in Berlin  
> **Client / Case:** Heidi Systems GmbH — Metering Service Provider / "Energy OS" for Real Estate  

---

## 🎯 Executive Overview

This repository contains an end-to-end, production-grade lead-generation and data-enrichment engine built specifically for **Heidi Systems**. It identifies, validates, scores, and enriches Berlin property management companies (*Hausverwaltungen*) to accelerate B2B sales cycles for heating cost allocation (*Heizkostenabrechnung*), submetering hardware installations, and energy compliance software.

**Public lead sheet:** [Google Sheets workbook](https://docs.google.com/spreadsheets/d/17fmN5F_6Fj-DWNf3XDGJreVLjX2GBru-b7V5Q3dp2e0/edit?usp=sharing)  
**Code repository:** [Property Management Berlin](https://github.com/Ashokreddy2806/Property_Management_Berlin)

### Key Deliverables:
- **`data/out/leads.xlsx`**: Master 6-tab Excel workbook:
  1. `README`: Methodology, source overview, tier definitions, column dictionary.
  2. `Leads`: 266 verified private Berlin Hausverwaltungen with 100% live websites, styled with frozen header panes, auto-filters, zebra striping, and soft tier color fills.
  3. `Strategic`: 25 municipal, institutional, and cooperative accounts kept separate from private tiers.
  4. `Directory-only`: 99 qualified property managers without an active website (optimized for SDR phone cold outreach).
  5. `Excluded`: 731 non-target entities with transparent exclusion reasons.
  6. `Sources`: Breakdown of raw leads contributed vs. surviving across all discovery channels.
  7. `Validation`: 40 representative output rows and their data fields.
- **`data/out/leads.csv`**: Full UTF-8 CSV deliverable of the 266 private enriched leads.
- **`docs/PROJECT_FLOW.md`**: Plain-language explanation of the project workflow and workbook tabs.
- **`CHANGES.md`**: Complete before/after metrics table, bug fixes, and pilot case validation notes.
- **`docs/APPROACH.md` & `docs/APPROACH.docx`**: Comprehensive technical architecture and strategy documentation.
- **`share_bundle.zip`**: Zero-secret, zero-cache distribution archive ready for submission.

---

## 🏗 System Architecture: 3 Agents + Plain Code

We strictly separate probabilistic AI judgment from deterministic computation:

1. **Agent 1 (Discovery & Qualification):** Evaluates ambiguous search snippets and titles to filter out pure brokers (*Immobilienmakler*), architects, cleaning firms, and industry associations (*IVD*, *VDIV*, *Haus & Grund*).
2. **Agent 2 (Enrichment - Prompt v2.0):** Reads raw German page text across company homepages, Impressum, team, service, and portal pages. Extracts structured JSON adhering to a Pydantic schema with mandatory verbatim evidence quotes.
3. **Agent 3 (Contact Resolution):** Identifies executive leadership (*Geschäftsführer*, *Inhaber*, *Vorstand*), verifies direct personal emails, and links dual-anchor verified LinkedIn profiles.
4. **Deterministic Code:** RapidFuzz name deduplication (score $\ge$ 92), domain normalization, phone formatting, HTTP caching, link checking, lead scoring, and Excel report generation.

---

## 📊 Final Pipeline Run Metrics

```
================================================================================
                    PIPELINE EXECUTION RUN SUMMARY
================================================================================
Total Validated Main Leads:             291 (266 private + 25 strategic)
Directory-Only (No active website):       99
Excluded Non-Target Entities:            731
Live Reachable Company Websites:         291 (100.0%)

TIER DISTRIBUTION (Main Table):
- Tier A (Score >= 70, High Priority):   12
- Tier B (Score 45-69, Mid Priority):    90
- Tier C (Score < 45, Basic Profile):    164
- Strategic (Municipal / Institutional): 25

CONTACTS & DECISION MAKERS:
- Named Decision Makers Identified:      157 (53.9%)
- Hunter-Verified Personal Emails:       7
- MX-Verified Personal Emails:           29
- Dual-Anchor Verified LinkedIn Matches: 34

COMPLIANCE & QUALITY GATES:
- Generic Emails in contact_email:       0 (100% Segregated to generic_email)
- Duplicate Domains:                     0
- Duplicate Normalized Company Names:    0
- Berlin Postcode Verified:              100.0%
================================================================================
```

---

## 🚀 Quickstart & Commands

### 1. Installation
```bash
# Clone or unpack repository
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the project root:
```env
SERPER_API_KEY=your_serper_key_here
HUNTER_API_KEY=your_hunter_key_here
NVIDIA_API_KEY=your_nvidia_key_here
GEMINI_MODEL=nvidia/nemotron-3.5-bolt-e4b
```

### 3. Run Pipeline Stages
The pipeline is fully modular, cached, and resumable:
```bash
# Run entire pipeline from start to finish
python run_pipeline.py --stage all

# Run individual stages:
python run_pipeline.py --stage dedupe       # Clean and dedupe raw leads
python run_pipeline.py --stage linkcheck    # Parallel HEAD/GET link check
python run_pipeline.py --stage crawl        # Polite crawling & Agent 2 extraction
python run_pipeline.py --stage score        # Deterministic KPI scoring (0-100 pts)
python run_pipeline.py --stage contacts     # Agent 3 decision makers, emails & LinkedIn
python run_pipeline.py --stage validate     # Sanity checks & validation sample
python run_pipeline.py --stage export       # Generate leads.xlsx, leads.csv, sources_log
python run_pipeline.py --stage audit        # Run hard quality gate audit (15 checks)
```

### 4. Run Unit Tests & Accuracy Check
```bash
# Run complete test suite (13 tests)
pytest tests/ -v

```

### 5. Build Distribution Bundle
```bash
python make_share_bundle.py
```
Produces `share_bundle.zip` excluding all secrets, caches, and virtual environments.
