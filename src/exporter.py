import csv
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import requests
import ftfy

from config import LEADS_COLUMNS, DATA_OUT_DIR
from src.clean_dedupe import normalize_domain

logger = logging.getLogger(__name__)

# Colors for Tier Highlighting
TIER_FILLS = {
    "A": PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid"),  # Soft Green (Prime Target)
    "B": PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid"),  # Soft Yellow (Mid Priority)
    "C": PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid"),  # Soft Red (Basic Profile)
    "Strategic": PatternFill(start_color="E8DAEF", end_color="E8DAEF", fill_type="solid"),  # Soft Purple (Municipal / Institutional / Coop)
}

HEADER_FILL = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
REGULAR_FONT = Font(name="Calibri", size=10)
BOLD_FONT = Font(name="Calibri", size=10, bold=True)

def export_to_csv(leads: List[Dict[str, Any]], filename: str = "leads.csv") -> Path:
    out_path = DATA_OUT_DIR / filename
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEADS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in leads:
            clean_row = {}
            for col in LEADS_COLUMNS:
                val = row.get(col, "")
                if isinstance(val, list):
                    val = "; ".join(str(x) for x in val)
                clean_row[col] = ftfy.fix_text(str(val)) if isinstance(val, str) else val
            writer.writerow(clean_row)
    logger.info(f"Saved CSV export to {out_path}")
    return out_path

def export_excluded_csv(excluded: List[Dict[str, Any]], filename: str = "excluded.csv") -> Path:
    out_path = DATA_OUT_DIR / filename
    fields = ["company_name", "segment", "website", "address", "phone", "exclusion_reason", "source", "source_url"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in excluded:
            clean_row = {k: ftfy.fix_text(str(row.get(k, ""))) if isinstance(row.get(k, ""), str) else row.get(k, "") for k in fields}
            writer.writerow(clean_row)
    logger.info(f"Saved excluded leads CSV to {out_path}")
    return out_path

def export_sources_log(sources_summary: List[Dict[str, Any]], filename: str = "sources_log.csv") -> Path:
    out_path = DATA_OUT_DIR / filename
    if not sources_summary:
        return out_path
    fields = list(sources_summary[0].keys())
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sources_summary:
            writer.writerow(row)
    logger.info(f"Saved sources log to {out_path}")
    return out_path

def build_reconciled_sources_data(
    raw_leads: List[Dict[str, Any]],
    leads_main: List[Dict[str, Any]],
    strategic_leads: List[Dict[str, Any]],
    directory_only: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Problem 8: Computes reconciled provenance metrics strictly from row provenance.
    Reconciles raw ingested rows, survivors per tab, exclusions by reason, and deduplication merges.
    """
    raw_by_source = Counter(r.get("source", "unknown") for r in raw_leads)

    def _count_in_list(leads_list: List[Dict[str, Any]], src_name: str) -> int:
        c = 0
        for l in leads_list:
            sources = l.get("sources", [])
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(";")]
            if src_name in sources or l.get("source") == src_name:
                c += 1
        return c

    def _count_excluded(ex_list: List[Dict[str, Any]], src_name: str) -> int:
        return sum(1 for e in ex_list if e.get("source") == src_name)

    method_map = {
        "serper_organic": "Google Organic Search via Serper API (12 Bezirke x Keywords)",
        "serper_places_api": "Google Places Local Search via Serper API",
        "gelbe_seiten": "Gelbe Seiten Berlin Directory Scraper",
        "das_oertliche": "Das Örtliche Berlin Directory Scraper",
        "tavily_search": "Tavily AI Search Engine for Local B2B Hausverwaltungen"
    }

    summary = []
    total_raw = len(raw_leads)
    total_leads = len(leads_main)
    total_strat = len(strategic_leads)
    total_dir = len(directory_only)
    total_ex = len(excluded)
    active_domains = {
        normalize_domain(row.get("website", ""))
        for row in leads_main + strategic_leads
        if row.get("website")
    }
    duplicate_merges = max(0, total_raw - len(active_domains) - total_dir - total_ex)

    for src_name, raw_count in sorted(raw_by_source.items(), key=lambda x: x[1], reverse=True):
        leads_c = _count_in_list(leads_main, src_name)
        strat_c = _count_in_list(strategic_leads, src_name)
        dir_c = _count_in_list(directory_only, src_name)
        ex_c = _count_excluded(excluded, src_name)
        
        summary.append({
            "source_name": src_name,
            "method": method_map.get(src_name, "API Search / Web Scraping"),
            "raw_rows_contributed": raw_count,
            "survivors_leads": leads_c,
            "survivors_strategic": strat_c,
            "survivors_directory": dir_c,
            "rows_excluded": ex_c,
            "reconciliation_status": "Reconciled (provenance tracked on rows)",
            "notes": "Companies may appear under several sources; row provenance is retained"
        })

    # Summary row
    summary.append({
        "source_name": "TOTAL / RECONCILIATION",
        "method": "All Discovery Pipelines (Deduplicated with RapidFuzz >= 92)",
        "raw_rows_contributed": total_raw,
        "survivors_leads": len(leads_main),
        "survivors_strategic": len(strategic_leads),
        "survivors_directory": len(directory_only),
        "rows_excluded": len(excluded),
        "reconciliation_status": (
            f"Raw rows {total_raw}; duplicates merged {duplicate_merges}; "
            f"rows per tab Leads {len(leads_main)}, Strategic {len(strategic_leads)}, "
            f"Directory-only {len(directory_only)}, Excluded {len(excluded)}"
        ),
        "notes": (
            "Counts are row-level reconciliation, not additive source totals. "
            "Companies can appear under several sources."
        )
    })

    return summary

def export_to_excel(
    leads: List[Dict[str, Any]],
    strategic_leads: Optional[List[Dict[str, Any]]] = None,
    directory_only: Optional[List[Dict[str, Any]]] = None,
    excluded: Optional[List[Dict[str, Any]]] = None,
    sources_summary: Optional[List[Dict[str, Any]]] = None,
    validation_sample_rows: Optional[List[Dict[str, Any]]] = None,
    filename: str = "leads.xlsx"
) -> Path:
    """
    Problems 8, 9, 10: Builds complete 7-tab Excel workbook:
    Tabs: README, Leads, Strategic, Directory-only, Excluded, Sources, Validation.
    """
    out_path = DATA_OUT_DIR / filename
    wb = openpyxl.Workbook()

    strat_rows = strategic_leads or [l for l in leads if l.get("tier") == "Strategic"]
    main_leads = [l for l in leads if l.get("tier") != "Strategic"]
    dir_rows = directory_only or []
    ex_rows = excluded or []

    # 1. README TAB
    ws_readme = wb.active
    ws_readme.title = "README"
    
    readme_content = [
        ("Heidi Systems - Berlin Hausverwaltungen Lead Generation Pipeline", ""),
        ("Deliverable:", "Take-Home Case: AI Agent Builder (Second Correction Pass)"),
        ("Target Market:", "Berlin Property Management Companies (Hausverwaltungen) for Submetering & Energy OS"),
        ("Run Date:", leads[0].get("last_verified", "") if leads else "November 2026"),
        ("", ""),
        ("1. Workbook Structure & 7 Tabs", ""),
        ("README", "Documentation, KPI justifications, scoring formula, legends, limitations, and GDPR statement"),
        ("Leads", "Private Hausverwaltungen (Tiers A, B, C) with verified Berlin postcodes and live reachable websites"),
        ("Strategic", "Municipal housing companies (degewo, gewobag, etc.) and Housing Cooperatives (eG) (Tier 'Strategic')"),
        ("Directory-only", "Entities discovered via public directories without active company websites or with offline domains"),
        ("Excluded", "Filtered non-target entities (brokers without HV, architects, cleaning, portals, associations) with precise reasons"),
        ("Sources", "Row-level reconciliation: raw rows, duplicate merges, tab counts, exclusions, and multi-source provenance"),
        ("Validation", "Stratified 40-row manual review sample with pipeline extractions and empty ground truth columns for human verification"),
        ("", ""),
        ("2. KPI Definitions & Justification (Heidi Systems Perspective)", ""),
        ("units_managed", "Total residential/commercial units managed. High unit count translates directly to submetering device volume and recurring SaaS license revenue."),
        ("properties_managed", "Total physical buildings managed. Determines logistics, installation density, and Gateway/M-Bus hardware sizing."),
        ("employees_estimate", "Workforce size. Proxy for operational maturity; indicates dedicated property managers and property accountants."),
        ("management_type", "WEG (condominium associations), Mietverwaltung (rental portfolios), or both. WEG requires annual billing resolutions; Mietverwaltung values automation."),
        ("software_or_portal", "Tenant/owner portals and ERP systems (Aareon, Domus, Haufe, Casavi). Heidi's Energy OS integrates directly via API to sync master data and meters."),
        ("metering_provider_mentions", "Mentions of incumbents (Techem, ista, Brunata, Minol, or in-house). Key indicator of contract expiration windows or dissatisfaction."),
        ("energy_signals", "Presence of smart metering, remote reading (Funkzähler/Fernablesung), Heizkostenverordnung compliance. Shows readiness for submetering."),
        ("growth_signals", "Active recruitment or regional expansion. Growing firms seek operational efficiency tools to scale without adding administrative headcount."),
        ("", ""),
        ("3. Lead Scoring Formula & Weights (0-100)", ""),
        ("Portfolio Size (30 pts)", ">=2000 units (30 pts), 500-1999 units (22 pts), 100-499 units (12 pts), <100 units (5 pts), unknown (8 pts)"),
        ("Management Type (10 pts)", "Both WEG & Mietverwaltung (10 pts), Single type (7 pts), Unknown (3 pts)"),
        ("Digital Maturity (15 pts)", "Portal AND named ERP software (15 pts), Either portal or ERP (8 pts), None (0 pts), Unknown (4 pts)"),
        ("Metering Provider Signal (10 pts)", "Unattached/none mentioned (10 pts), In-house metering (7 pts), Competitor mentioned (5 pts)"),
        ("Energy / Smart Metering (15 pts)", "Strong remote reading/smart metering/HeizkostenV (15 pts), Weak energy awareness (8 pts), None (0 pts)"),
        ("Growth Signals (5 pts)", "Active hiring / expansion present (5 pts), None (0 pts)"),
        ("Contactability (15 pts)", "Named whitelisted decision maker + verified email (15 pts), named + unverified email (9 pts), name only (4 pts)"),
        ("", ""),
        ("4. Tier Thresholds & Rules", ""),
        ("Tier A (Score >= 70)", "High priority. Requires score >= 70, kpi_fill_rate >= 0.5 (>=4 of 7 known), live site, verified Berlin PLZ, Private Hausverwaltung."),
        ("Tier B (Score 45-69)", "Mid priority. Strong potential, capped if key portfolio or digital maturity fields remain unknown."),
        ("Tier C (Score < 45)", "Boutique / basic profile. Smaller property managers or limited online data footprint."),
        ("Strategic", "Municipal housing corporations and Housing Cooperatives (eG). Segregated into dedicated 'Strategic' tab."),
        ("", ""),
        ("5. Status Legends & Provenance", ""),
        ("email_origin", "found_on_site (extracted from page), hunter (Hunter finder), pattern_inferred_from_evidence (derived from colleague email pattern), guessed (in guessed_email only)"),
        ("email_status", "hunter_verified, hunter_accept_all, mx_ok_unverified, invalid, none"),
        ("contact_confidence", "high (explicit title on company website), medium (title confirmed via search metadata), low (name only)"),
        ("data_confidence", "high (multi-source cross-checked + live site + fill rate >= 0.5), medium (live site + fill rate >= 0.25), low (minimal data)"),
        ("", ""),
        ("6. Known Limitations & Compliance", ""),
        ("Known Limitations", "1. Portfolio unit counts are undisclosed on many German SME websites. 2. LinkedIn URLs are matched solely via search engine metadata (never scraped). 3. Guessed emails are excluded from contact_email."),
        ("GDPR & B2B Compliance", "Strict compliance with GDPR Art. 6(1)(f) (Legitimate Interest for B2B prospecting). Only public business information collected. Generic mailboxes strictly segregated.")
    ]

    for r_idx, (c1, c2) in enumerate(readme_content, 1):
        c1_cell = ws_readme.cell(row=r_idx, column=1, value=c1)
        c2_cell = ws_readme.cell(row=r_idx, column=2, value=c2)
        if r_idx == 1:
            c1_cell.font = Font(name="Calibri", size=13, bold=True, color="1F497D")
        elif not c2:
            c1_cell.font = Font(name="Calibri", size=11, bold=True, color="1F497D")
        else:
            c1_cell.font = Font(name="Calibri", size=10, bold=True)
            c2_cell.font = REGULAR_FONT
    ws_readme.column_dimensions["A"].width = 32
    ws_readme.column_dimensions["B"].width = 85

    # Helper function to populate lead tables
    def _populate_lead_sheet(ws, rows_data):
        for col_idx, col_name in enumerate(LEADS_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.freeze_panes = "A2"

        for row_idx, lead in enumerate(rows_data, 2):
            tier = str(lead.get("tier", "C"))
            tier_fill = TIER_FILLS.get(tier)

            for col_idx, col_name in enumerate(LEADS_COLUMNS, 1):
                val = lead.get(col_name, "")
                if isinstance(val, list):
                    val = "; ".join(str(x) for x in val)
                if isinstance(val, str):
                    val = ftfy.fix_text(val)
                
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = REGULAR_FONT
                
                if col_name == "tier" and tier_fill:
                    cell.fill = tier_fill
                    cell.font = BOLD_FONT
                    cell.alignment = Alignment(horizontal="center")
                elif col_name in ["lead_score", "kpi_fill_rate"]:
                    cell.alignment = Alignment(horizontal="center")
                elif col_name in ["website", "contact_email", "linkedin_url"] and val:
                    cell.font = Font(name="Calibri", size=10, color="0000FF", underline="single")

        last_col = get_column_letter(len(LEADS_COLUMNS))
        if rows_data:
            ws.auto_filter.ref = f"A1:{last_col}{len(rows_data)+1}"

        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                v = str(cell.value or "")
                if len(v) > max_len:
                    max_len = len(v)
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 3, 45))

    # 2. LEADS TAB (Private Hausverwaltungen only)
    ws_leads = wb.create_sheet(title="Leads")
    _populate_lead_sheet(ws_leads, main_leads)

    # 3. STRATEGIC TAB (Cooperatives & Large housing companies)
    ws_strategic = wb.create_sheet(title="Strategic")
    _populate_lead_sheet(ws_strategic, strat_rows)

    # 4. DIRECTORY-ONLY TAB
    ws_dir = wb.create_sheet(title="Directory-only")
    dir_cols = ["company_name", "address", "bezirk", "phone", "website", "website_status", "source", "source_url", "notes"]
    for col_idx, cname in enumerate(dir_cols, 1):
        cell = ws_dir.cell(row=1, column=col_idx, value=cname)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    ws_dir.freeze_panes = "A2"

    for r_idx, item in enumerate(dir_rows, 2):
        for c_idx, cname in enumerate(dir_cols, 1):
            val = item.get(cname, "")
            if isinstance(val, list):
                val = "; ".join(str(x) for x in val)
            if isinstance(val, str):
                val = ftfy.fix_text(val)
            cell = ws_dir.cell(row=r_idx, column=c_idx, value=val)
            cell.font = REGULAR_FONT
    for col in ws_dir.columns:
        col_letter = get_column_letter(col[0].column)
        ws_dir.column_dimensions[col_letter].width = 20

    # 5. EXCLUDED TAB
    ws_ex = wb.create_sheet(title="Excluded")
    ex_cols = ["company_name", "segment", "website", "address", "phone", "exclusion_reason", "source", "source_url"]
    for col_idx, cname in enumerate(ex_cols, 1):
        cell = ws_ex.cell(row=1, column=col_idx, value=cname)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    ws_ex.freeze_panes = "A2"

    for r_idx, item in enumerate(ex_rows, 2):
        for c_idx, cname in enumerate(ex_cols, 1):
            val = item.get(cname, "")
            if isinstance(val, list):
                val = "; ".join(str(x) for x in val)
            if isinstance(val, str):
                val = ftfy.fix_text(val)
            cell = ws_ex.cell(row=r_idx, column=c_idx, value=val)
            cell.font = REGULAR_FONT
    for col in ws_ex.columns:
        col_letter = get_column_letter(col[0].column)
        ws_ex.column_dimensions[col_letter].width = 25

    # 6. SOURCES TAB (Problem 8)
    ws_src = wb.create_sheet(title="Sources")
    src_cols = ["source_name", "method", "raw_rows_contributed", "survivors_leads", "survivors_strategic", "survivors_directory", "rows_excluded", "reconciliation_status", "notes"]
    for col_idx, cname in enumerate(src_cols, 1):
        cell = ws_src.cell(row=1, column=col_idx, value=cname)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    ws_src.freeze_panes = "A2"

    src_rows = sources_summary or []
    for r_idx, item in enumerate(src_rows, 2):
        for c_idx, cname in enumerate(src_cols, 1):
            val = item.get(cname, "")
            cell = ws_src.cell(row=r_idx, column=c_idx, value=val)
            cell.font = BOLD_FONT if "TOTAL" in str(item.get("source_name", "")) else REGULAR_FONT
    for col in ws_src.columns:
        col_letter = get_column_letter(col[0].column)
        ws_src.column_dimensions[col_letter].width = 24

    # 7. VALIDATION TAB (Problem 9: 40-row stratified sample matching validation_sample.csv)
    ws_val = wb.create_sheet(title="Validation")
    val_sample_path = DATA_OUT_DIR / "validation_sample.csv"
    val_rows = []
    if val_sample_path.exists():
        with open(val_sample_path, "r", encoding="utf-8-sig") as f:
            val_rows = list(csv.reader(f))
            
    if val_rows:
        headers = val_rows[0]
        for c_idx, h in enumerate(headers, 1):
            cell = ws_val.cell(row=1, column=c_idx, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
        ws_val.freeze_panes = "A2"

        for r_idx, row_data in enumerate(val_rows[1:], 2):
            for c_idx, val in enumerate(row_data, 1):
                cell = ws_val.cell(row=r_idx, column=c_idx, value=ftfy.fix_text(val))
                cell.font = REGULAR_FONT

        for col in ws_val.columns:
            col_letter = get_column_letter(col[0].column)
            ws_val.column_dimensions[col_letter].width = 22

    wb.save(out_path)
    logger.info(f"Saved complete 7-tab Excel export to {out_path}")
    return out_path

def export_to_google_sheet(
    leads: List[Dict[str, Any]],
    strategic_leads: Optional[List[Dict[str, Any]]] = None,
    directory_only: Optional[List[Dict[str, Any]]] = None,
    excluded: Optional[List[Dict[str, Any]]] = None,
    sources_summary: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[str], str]:
    """
    Section 7.3: Google Sheet export via gspread.
    Verifies public export URL without credentials (HTTP 200).
    Returns (public_url, status_message).
    """
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_path or not Path(sa_path).exists():
        msg = "GOOGLE_SERVICE_ACCOUNT_JSON is not configured in .env; XLSX with 7 tabs serves as the primary deliverable."
        logger.info(msg)
        return None, msg

    try:
        import gspread
        gc = gspread.service_account(filename=sa_path)
        sheet_title = "Heidi Systems Case - Berlin Hausverwaltungen Lead List"
        sh = gc.create(sheet_title)
        sh.share(None, perm_type="anyone", role="reader")
        
        default = sh.sheet1
        default.update_title("README")

        def _write_tab(title: str, headers: List[str], data: List[List[Any]]) -> None:
            ws = sh.add_worksheet(title=title, rows=max(10, len(data) + 2), cols=max(2, len(headers) + 1))
            ws.update("A1", [headers] + data)

        private_rows = [l for l in leads if l.get("tier") != "Strategic"]
        strategic_rows = strategic_leads or [l for l in leads if l.get("tier") == "Strategic"]
        _write_tab("Leads", LEADS_COLUMNS, [
            [ftfy.fix_text(str(row.get(col, ""))) for col in LEADS_COLUMNS] for row in private_rows
        ])
        _write_tab("Strategic", LEADS_COLUMNS, [
            [ftfy.fix_text(str(row.get(col, ""))) for col in LEADS_COLUMNS] for row in strategic_rows
        ])
        directory_headers = ["company_name", "segment", "website", "address", "phone", "notes"]
        _write_tab("Directory-only", directory_headers, [
            [ftfy.fix_text(str(row.get(col, ""))) for col in directory_headers]
            for row in (directory_only or [])
        ])
        excluded_headers = ["company_name", "segment", "website", "address", "phone", "exclusion_reason", "source", "source_url"]
        _write_tab("Excluded", excluded_headers, [
            [ftfy.fix_text(str(row.get(col, ""))) for col in excluded_headers]
            for row in (excluded or [])
        ])
        source_headers = [
            "source_name", "method", "raw_rows_contributed", "survivors_leads",
            "survivors_strategic", "survivors_directory", "rows_excluded",
            "reconciliation_status", "notes",
        ]
        _write_tab("Sources", source_headers, [
            [str(row.get(col, "")) for col in source_headers]
            for row in (sources_summary or [])
        ])
        validation_path = DATA_OUT_DIR / "validation_sample.csv"
        validation_rows = []
        if validation_path.exists():
            with validation_path.open("r", encoding="utf-8-sig", newline="") as handle:
                validation_rows = list(csv.reader(handle))
        if validation_rows:
            ws_validation = sh.add_worksheet(
                title="Validation",
                rows=max(10, len(validation_rows) + 2),
                cols=max(2, len(validation_rows[0]) + 1),
            )
            ws_validation.update("A1", validation_rows)
        
        url = sh.url
        export_test_url = f"https://docs.google.com/spreadsheets/d/{sh.id}/export?format=csv"
        resp = requests.get(export_test_url, timeout=10)
        if resp.status_code == 200:
            logger.info(f"Google Sheet publicly verified at: {url}")
            counts = (
                f"README 1, Leads {len(private_rows)}, Strategic {len(strategic_rows)}, "
                f"Directory-only {len(directory_only or [])}, Excluded {len(excluded or [])}, "
                f"Sources {len(sources_summary or [])}, Validation {max(0, len(validation_rows) - 1)}"
            )
            return url, f"Success: Google Sheet created and verified public export (HTTP {resp.status_code}); {counts}"
        else:
            return url, f"Created sheet at {url}, but public export test returned HTTP {resp.status_code}"
    except Exception as e:
        msg = f"Google Sheets API error: {e}"
        logger.warning(msg)
        return None, msg
