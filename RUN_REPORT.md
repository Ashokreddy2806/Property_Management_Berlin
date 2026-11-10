# Executive Run Report: Berlin Hausverwaltungen Lead Generation Pipeline

**Execution Date:** 2026-11-10 00:50:51 UTC  
**Target:** Case Study for Heidi Systems ("AI Agent Builder")  
**Runtime:** 2.09 seconds

## 1. Executive Summary
The end-to-end lead generation pipeline executed successfully with all correction pass fixes applied:
- **Total Validated Main Leads:** **291** (Target was >= 400).
- **Directory-Only Leads (No active website):** **99** (Retained in dedicated workbook tab).
- **Excluded Candidates:** **731** (Brokers, architects, cleaning firms, associations, portals).
- **Live Websites:** **291** (100.0%).
- **Tier Distribution:** Tier A: 12 | Tier B: 90 | Tier C: 164 | Strategic: 25.
- **Decision Makers Identified:** 157 (54.0%).
- **Personal Emails:** 7 Hunter-verified, 29 MX-verified (0 generic mailboxes in contact_email).
- **LinkedIn Profiles Verified:** 34 (dual-anchor verified without scraping linkedin.com).

## 2. Deliverables Generated
- `data/out/leads.xlsx`: 6-tab Excel workbook (README, Leads, Directory-only, Excluded, Sources, Validation).
- `data/out/leads.csv`: Full UTF-8 CSV containing all 36 target columns in exact order.
- `data/out/excluded.csv`: Excluded entities with explicit reason strings.
- `data/out/sources_log.csv`: Breakdown of discovery sources, raw contributed counts, and surviving counts.
- `data/out/validation_report.md`: Automated quality assurance audit.
- `data/out/validation_sample.csv`: Stratified 40-row sample for manual accuracy auditing.
- `compute_accuracy.py`: CLI tool to score manual validation results.
- `docs/APPROACH.md` & `docs/APPROACH.docx`: Methodology and architecture document.
- `CHANGES.md`: Full audit log of all correction pass changes.

## 3. Manual To-Dos for Submission
1. Open `data/out/validation_sample.csv` in Excel or VS Code.
2. Review the 40 stratified rows and mark `1` or `yes` for:
   - `is_berlin_hausverwaltung_correct`
   - `contact_correct`
   - `kpi_values_correct`
3. Run `python compute_accuracy.py` to print your real accuracy percentages.
4. Open the Google Sheet URL (or verify `leads.xlsx` in Excel).
5. Rotate any shared API keys.
6. Attach `leads.xlsx` and `docs/APPROACH.docx` to your take-home case reply!
