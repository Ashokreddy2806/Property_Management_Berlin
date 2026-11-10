import re
import os
import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from rapidfuzz import fuzz

from config import (
    DATA_OUT_DIR, DOCS_DIR, LOGS_DIR, DATA_CACHE_DIR,
    AGGREGATOR_DOMAINS, DECISION_MAKER_TITLES_WHITELIST, VALID_EMAIL_STATUSES
)
from src.agent_contact import (
    GENERIC_EMAIL_PREFIXES, PLACEHOLDER_LOCAL_PARTS, PLACEHOLDER_DOMAINS,
    TITLE_BLACKLIST, is_whitelisted_decision_maker_title, normalize_email
)
from src.clean_dedupe import (
    GENERIC_EXACT, ARTICLE_PATTERNS, ASSOCIATION_PATTERNS, EXCLUDED_INDUSTRIES,
    extract_berlin_postcode, normalize_domain, _get_cached_domain_plz_index
)
from src.agent_enrichment import verify_evidence_in_text

MOJIBAKE_REGEX = re.compile(
    r"(?:\u00c3.|\u00c2.|\u00e2[\u0080-\u00bf]|\ufffd|SchA neberg|NeukA lln|Treptow-KA penick)"
)

def run_lead_audit(
    leads: List[Dict[str, Any]],
    strategic_leads: List[Dict[str, Any]] = None,
    directory_only: List[Dict[str, Any]] = None,
    excluded: List[Dict[str, Any]] = None
) -> Tuple[bool, List[str]]:
    """
    Problem 10: Rigorous audit of all 15 hard quality gates.
    Fails with clear offenders listed if ANY quality gate is violated.
    """
    failures: List[str] = []
    strat_rows = strategic_leads or [l for l in leads if l.get("tier") == "Strategic"]
    main_leads = [l for l in leads if l.get("tier") != "Strategic"]
    dir_rows = directory_only or []
    ex_rows = excluded or []

    # Gate 1: Any aggregator/redirect website or non-ok status in Leads
    for idx, l in enumerate(main_leads, 1):
        w = l.get("website", "").lower()
        w_stat = l.get("website_status", "")
        if "google.com/goto" in w:
            failures.append(f"Gate 1 (Leads Row {idx} '{l.get('company_name')}'): Contains unresolved google.com/goto URL: {w}")
        w_domain = normalize_domain(w)
        if any(w_domain == agg or w_domain.endswith(f".{agg}") for agg in AGGREGATOR_DOMAINS):
            failures.append(f"Gate 1 (Leads Row {idx} '{l.get('company_name')}'): Contains aggregator website ({w_domain}): {w}")
        if w_stat != "ok":
            failures.append(f"Gate 1 (Leads Row {idx} '{l.get('company_name')}'): Website status is '{w_stat}' (must be 'ok' in Leads)")

    # Gate 2: Page-title / truncated company names
    for idx, l in enumerate(main_leads + strat_rows, 1):
        name = l.get("company_name", "").strip()
        if name.endswith("...") or name.endswith("…"):
            failures.append(f"Gate 2 (Row {idx} '{name}'): Name is truncated (ends with ellipsis)")
        elif len(name) < 4:
            failures.append(f"Gate 2 (Row {idx} '{name}'): Name is shorter than 4 characters")
        elif len(name) > 80:
            failures.append(f"Gate 2 (Row {idx} '{name}'): Name is longer than 80 characters (page title)")
        elif any(sep in name for sep in [" - ", " | ", ": "]):
            failures.append(f"Gate 2 (Row {idx} '{name}'): Name contains page-title delimiters (' - ', ' | ', ': ')")
        elif "treffer" in name.lower():
            failures.append(f"Gate 2 (Row {idx} '{name}'): Name contains 'Treffer' (directory listing)")

    # Gate 3: Mojibake in any cell
    for idx, l in enumerate(main_leads + strat_rows, 1):
        for k, v in l.items():
            if k.startswith("_"):
                continue
            if isinstance(v, str) and MOJIBAKE_REGEX.search(v):
                failures.append(f"Gate 3 (Row {idx} '{l.get('company_name')}'): Mojibake detected in column '{k}': {v[:60]}")

    # Gate 4: Duplicate domains or duplicate normalized names
    all_active = main_leads + strat_rows
    domains = [l.get("normalized_domain") for l in all_active if l.get("normalized_domain")]
    dup_domains = [d for d in set(domains) if domains.count(d) > 1]
    if dup_domains:
        failures.append(f"Gate 4: Duplicate domains found in Leads/Strategic: {dup_domains}")

    def _norm_name(n: str) -> str:
        s = n.lower()
        s = re.sub(r"\b(gmbh & co\. kg|gmbh|ug|ag|e\.k\.|gbr|kg|haftungsbeschränkt|hausverwaltung|verwaltung|immobilien|management)\b", "", s)
        s = re.sub(r"[^\w\s]", "", s)
        return " ".join(s.split())

    norm_names = [_norm_name(l.get("company_name", "")) for l in all_active if l.get("company_name")]
    dup_names = []
    for idx, n1 in enumerate(norm_names):
        if len(n1) > 3:
            for n2 in norm_names[idx+1:]:
                if fuzz.token_sort_ratio(n1, n2) >= 92:
                    dup_names.append(f"'{n1}' ~= '{n2}'")
    if dup_names:
        failures.append(f"Gate 4: Duplicate normalized names found in Leads/Strategic: {dup_names[:5]}")

    # Gate 5: berlin_not_verified exclusion with provable Impressum postcode
    plz_index = _get_cached_domain_plz_index()
    for idx, ex in enumerate(ex_rows, 1):
        if ex.get("exclusion_reason") == "berlin_not_verified":
            dom = normalize_domain(ex.get("website", ""))
            if dom and dom in plz_index:
                plz, addr = plz_index[dom]
                failures.append(f"Gate 5 (Excluded Row {idx} '{ex.get('company_name')}'): Excluded as berlin_not_verified but Impressum has Berlin PLZ {plz} ({dom})")

    # Gate 6: KPI without own-domain evidence or domain mismatch
    for idx, l in enumerate(all_active, 1):
        comp_dom = l.get("normalized_domain", "")
        kpi_ev = l.get("kpi_evidence", "")
        # If units_managed is populated, evidence quote must be non-empty
        if l.get("units_managed") not in [None, "", "unknown"]:
            if "units_managed:" not in kpi_ev:
                failures.append(f"Gate 6 (Row {idx} '{l.get('company_name')}'): units_managed populated without evidence quote in kpi_evidence")
        
        enrichment = l.get("_enrichment_data") or {}
        if isinstance(enrichment, str):
            try:
                enrichment = json.loads(enrichment)
            except json.JSONDecodeError:
                enrichment = {}
        source_map = enrichment.get("kpi_source_urls", {}) if isinstance(enrichment, dict) else {}
        for field, source_url in source_map.items():
            if "page source" in str(source_url).lower():
                continue
            source_dom = normalize_domain(source_url)
            if source_dom and comp_dom and source_dom != comp_dom:
                failures.append(f"Gate 6 (Row {idx} '{l.get('company_name')}'): KPI '{field}' source domain {source_dom} != company domain {comp_dom}")

    # Gate 7: contact_email hygiene (generic / placeholder / guessed)
    for idx, l in enumerate(all_active, 1):
        ce = l.get("contact_email", "")
        if ce and ce != "unknown":
            norm = normalize_email(ce)
            if not norm:
                failures.append(f"Gate 7 (Row {idx} '{l.get('company_name')}'): contact_email '{ce}' failed normalization")
            prefix = ce.split("@")[0].lower()
            if any(prefix == g or prefix.startswith(f"{g}.") or prefix.startswith(f"{g}-") for g in GENERIC_EMAIL_PREFIXES):
                failures.append(f"Gate 7 (Row {idx} '{l.get('company_name')}'): Generic/role-based email in contact_email: '{ce}'")
            if l.get("email_origin") == "guessed":
                failures.append(f"Gate 7 (Row {idx} '{l.get('company_name')}'): Guessed email placed in contact_email")

    # Gate 8: email_status 'none' mismatch
    for idx, l in enumerate(all_active, 1):
        ce = l.get("contact_email", "")
        st = l.get("email_status", "")
        if ce in ["", "unknown", None]:
            if st != "none":
                failures.append(f"Gate 8 (Row {idx} '{l.get('company_name')}'): contact_email is unknown but email_status is '{st}' (must be 'none')")
        else:
            if st == "none":
                failures.append(f"Gate 8 (Row {idx} '{l.get('company_name')}'): contact_email is populated ('{ce}') but email_status is 'none'")
            if st not in VALID_EMAIL_STATUSES:
                failures.append(f"Gate 8 (Row {idx} '{l.get('company_name')}'): Invalid email_status '{st}' (must be in {VALID_EMAIL_STATUSES})")

    # Gate 9: Tier A rule violations
    for idx, l in enumerate(main_leads, 1):
        if l.get("tier") == "A":
            score = float(l.get("lead_score", 0))
            fill_rate = float(l.get("kpi_fill_rate", 0))
            w_stat = l.get("website_status", "")
            seg = l.get("segment", "")
            plz = extract_berlin_postcode(l.get("address", ""))

            if score < 70:
                failures.append(f"Gate 9 (Tier A Row {idx} '{l.get('company_name')}'): Score ({score}) < 70")
            if fill_rate < 0.5:
                failures.append(f"Gate 9 (Tier A Row {idx} '{l.get('company_name')}'): KPI fill rate ({fill_rate}) < 0.5")
            if w_stat != "ok":
                failures.append(f"Gate 9 (Tier A Row {idx} '{l.get('company_name')}'): website_status ({w_stat}) != ok")
            if not plz or not (10115 <= int(plz) <= 14199):
                failures.append(f"Gate 9 (Tier A Row {idx} '{l.get('company_name')}'): Berlin postcode missing or invalid ({plz})")
            if seg != "Private Hausverwaltung":
                failures.append(f"Gate 9 (Tier A Row {idx} '{l.get('company_name')}'): Segment ({seg}) != 'Private Hausverwaltung'")

    # Gate 10: Cooperatives or Large housing companies in A/B/C tiers
    for idx, l in enumerate(main_leads, 1):
        seg = l.get("segment", "")
        if seg in ["Housing cooperative", "Large housing company"]:
            failures.append(f"Gate 10 (Leads Row {idx} '{l.get('company_name')}'): Segment '{seg}' is in Leads tab with tier '{l.get('tier')}' (must be on Strategic tab)")

    # Gate 11: LinkedIn without match note
    for idx, l in enumerate(all_active, 1):
        l_url = l.get("linkedin_url", "")
        if l_url:
            note = l.get("linkedin_match_note", "").strip()
            if not note:
                failures.append(f"Gate 11 (Row {idx} '{l.get('company_name')}'): LinkedIn URL present without linkedin_match_note")

    # Gate 12: Tab counts not reconciling with Sources
    sources_p = DATA_OUT_DIR / "sources_log.csv"
    if not sources_p.exists():
        failures.append("Gate 12: sources_log.csv does not exist in data/out/")
    else:
        with open(sources_p, "r", encoding="utf-8-sig") as f:
            src_rows = list(csv.DictReader(f))
        tot_row = [r for r in src_rows if "TOTAL" in r.get("source_name", "")]
        if not tot_row:
            failures.append("Gate 12: sources_log.csv missing TOTAL reconciliation row")
        else:
            total = tot_row[0]
            expected_counts = {
                "survivors_leads": len(main_leads),
                "survivors_strategic": len(strat_rows),
                "survivors_directory": len(dir_rows),
                "rows_excluded": len(ex_rows),
            }
            for key, expected in expected_counts.items():
                actual = int(float(total.get(key, -1) or -1))
                if actual != expected:
                    failures.append(f"Gate 12: {key} is {actual}, expected {expected}")

    # Gate 13: Missing recall report
    recall_p = DATA_OUT_DIR / "recall_report.md"
    if not recall_p.exists():
        failures.append("Gate 13: recall_report.md does not exist in data/out/")

    # Gate 14: Security scan for key-like strings
    key_patterns = [
        re.compile(r"nvapi-[A-Za-z0-9_-]{20,}"),
        re.compile(r"tvly-[A-Za-z0-9_-]{20,}"),
        re.compile(r"fc-[A-Za-z0-9_-]{20,}"),
        re.compile(r"(?:api_key|apiKey|token)\s*=\s*['\"][A-Za-z0-9_-]{20,}['\"]")
    ]
    for scan_dir in [DATA_OUT_DIR, DOCS_DIR, LOGS_DIR]:
        if not scan_dir.exists():
            continue
        for root, _, files in os.walk(scan_dir):
            if "backup_before_fix" in root:
                continue
            for f in files:
                f_path = Path(root) / f
                if f.endswith((".csv", ".md", ".json", ".log", ".txt")):
                    try:
                        content = f_path.read_text(encoding="utf-8", errors="ignore")
                        for pat in key_patterns:
                            if pat.search(content):
                                failures.append(f"Gate 14 (Security): Key-like pattern found in output file: {f_path}")
                                break
                    except Exception:
                        pass

    # Gate 15: Pre-filled manual validation columns
    val_sample_p = DATA_OUT_DIR / "validation_sample.csv"
    if not val_sample_p.exists():
        failures.append("Gate 15: validation_sample.csv does not exist in data/out/")
    else:
        with open(val_sample_p, "r", encoding="utf-8-sig") as f:
            sample_rows = list(csv.DictReader(f))
        for idx, row in enumerate(sample_rows, 1):
            for col in ["manual_units_managed", "manual_contact_name", "manual_contact_email", "units_correct", "contact_correct", "email_correct"]:
                val = row.get(col, "").strip()
                if val:
                    failures.append(f"Gate 15: validation_sample.csv Row {idx} has pre-filled manual column '{col}' = '{val}' (must be empty for human verification)")
                    break

    is_passed = len(failures) == 0
    return is_passed, failures
