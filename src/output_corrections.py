import csv
import datetime
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import ftfy
from bs4 import BeautifulSoup

from config import DATA_CACHE_DIR, DATA_RAW_DIR
from src.clean_dedupe import (
    POSTCODE_TO_BEZIRK,
    extract_berlin_postcode,
    normalize_domain,
    repair_company_name,
)
from src.cache import get_cached_http


SERVICE_ONLY_RE = re.compile(
    r"^(?:hausverwaltungen?|immobilienverwaltung|weg[- ]verwaltung|"
    r"mietverwaltung|sondereigentumsverwaltung)(?:\s+(?:in|für|fuer))?"
    r"(?:\s+(?:berlin|deutschlandweit|potsdam|"
    r"[\wäöüß-]+))*(?:\s*&\s*(?:deutschlandweit|berlin))?$",
    re.IGNORECASE,
)

LEGAL_LINE_RE = re.compile(
    r"^[^\n\r]{2,70}\s+(?:GmbH & Co\. KG|GmbH|UG \(haftungsbeschränkt\)|"
    r"UG|AG|e\.K\.|GbR|KG|eG)$",
    re.MULTILINE,
)


STRATEGIC_VALIDATED = {
    "degewo": {
        "name": "degewo AG",
        "website": "https://www.degewo.de/",
        "validation_url": "https://www.degewo.de/impressum",
        "address": "Potsdamer Straße 60, 10785 Berlin",
        "postcode": "10785",
    },
    "gewobag": {
        "name": "Gewobag Wohnungsbau-Aktiengesellschaft Berlin",
        "website": "https://www.gewobag.de/",
        "validation_url": "https://www.gewobag.de/impressum-gewobag/",
        "address": "Alt-Moabit 101 A, 10559 Berlin",
        "postcode": "10559",
    },
    "berlinovo": {
        "name": "Berlinovo Immobilien Gesellschaft mbH",
        "website": "https://www.berlinovo.de/",
        "validation_url": "https://www.berlinovo.de/impressum",
        "address": "Linkstraße 10, 10785 Berlin",
        "postcode": "10785",
    },
    "heimstaden": {
        "name": "Heimstaden Germany GmbH",
        "website": "https://heimstaden.com/de/",
        "validation_url": "https://heimstaden.com/de/impressum/",
        "address": "Erkelenzdamm 11-13, 10999 Berlin",
        "postcode": "10999",
    },
    "covivio": {
        "name": "Covivio",
        "website": "https://www.covivio.immo/",
        "validation_url": "https://www.covivio.immo/office/unternehmensangaben-buero/",
        "address": "Knesebeckstraße 3, 10623 Berlin",
        "postcode": "10623",
    },
    "akelius": {
        "name": "Akelius Residential Property AB",
        "website": "https://www.akelius.com/en/",
        "validation_url": "https://www.akelius.com/en/contact",
        "address": "Franklinstraße 26a, 10587 Berlin",
        "postcode": "10587",
    },
    "vonovia": {
        "name": "Vonovia",
        "website": "https://www.vonovia.de/",
        "validation_url": "https://www.vonovia.de/mein-zuhause/kundenservice",
        "address": "Berlin, 13337 Berlin",
        "postcode": "13337",
    },
    "howoge": {
        "name": "HOWOGE Wohnungsbaugesellschaft mbH",
        "website": "https://www.howoge.de/",
        "validation_url": "https://www.howoge.de/impressum.html",
        "address": "Stefan-Heym-Platz 1, 10365 Berlin",
        "postcode": "10365",
    },
}


def _read_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _cached_legal_name(website: str, domain: str) -> str:
    candidates = [
        website,
        f"https://{domain}/impressum",
        f"https://{domain}/",
        f"https://www.{domain}/impressum",
        f"https://www.{domain}/",
    ]
    for candidate in candidates:
        cached = get_cached_http(candidate)
        if not cached or not cached.get("text"):
            continue
        soup = BeautifulSoup(cached["text"], "html.parser")
        for line in soup.get_text("\n").splitlines():
            line = ftfy.fix_text(" ".join(line.split()))
            if LEGAL_LINE_RE.fullmatch(line):
                return line
        og = soup.find("meta", property="og:site_name")
        if og and og.get("content"):
            value = ftfy.fix_text(og["content"].strip())
            if len(value) >= 4:
                return value
    return ""


def _is_service_only(name: str) -> bool:
    normalized = re.sub(r"\s+", " ", ftfy.fix_text(name).strip())
    if not normalized:
        return False
    tokens = re.findall(r"[a-zäöüß-]+", normalized.lower())
    service_tokens = {
        "hausverwaltung", "hausverwaltungen", "immobilienverwaltung",
        "weg", "verwaltung", "weg-verwaltung", "mietverwaltung",
        "sondereigentumsverwaltung", "sondereigentum", "eigentümer",
        "eigentuem er", "berlin", "potsdam", "deutschlandweit",
        "friedrichshain", "charlottenburg", "spandau", "lichtenberg",
        "pankow", "reinickendorf", "steglitz", "zehlendorf", "mitte",
        "und", "in", "für", "fuer", "für", "eigentuemer", "digitale",
        "beste", "erste", "ihre", "top",
    }
    if tokens and all(token in service_tokens for token in tokens):
        return True
    if SERVICE_ONLY_RE.fullmatch(normalized):
        return True
    return bool(
        re.fullmatch(
            r"(?:hausverwaltung|hausverwaltungen|immobilienverwaltung|weg[- ]verwaltung)"
            r"(?:\s+(?:in|für|fuer))?\s+[\wäöüß-]+(?:\s*&\s*[\wäöüß-]+)?",
            normalized,
            re.IGNORECASE,
        )
    )


def _clean_name(lead: Dict[str, Any]) -> None:
    name = ftfy.fix_text(str(lead.get("company_name", "")).strip())
    name = re.sub(r"^©\s*2026\s+", "", name, flags=re.IGNORECASE).strip()
    exact = {
        "Kundenservice & Kontakt zu Vonovia": "Vonovia",
        "Hier finden Sie Ihre neue Wohnung": "",
        "Quartierbüro Spandau": "",
        "Charlottenburger Baugenossenschaft eG , Hausverwaltung Spandau":
            "Charlottenburger Baugenossenschaft eG",
    }
    if name in exact:
        name = exact[name]
        lead["name_source"] = "manual_boilerplate_cleanup"
    if not name:
        domain = normalize_domain(str(lead.get("website", "")))
        name = _cached_legal_name(str(lead.get("website", "")), domain)
        if not name and domain:
            name = domain.split(".")[0].replace("-", " ").title()
            lead["name_source"] = "domain_derived"
        elif name:
            lead["name_source"] = "impressum_legal_line"
    domain = normalize_domain(str(lead.get("website", "")))
    if (
        len(name) > 80
        or any(delimiter in name for delimiter in (" - ", " | ", ": "))
    ):
        for part in re.split(r"\s+(?:-\||-|–|—|\|)\s+", name):
            part = part.strip()
            if re.search(r"\b(?:GmbH|AG|UG|eG|GbR|KG|e\.K\.)$", part):
                name = part
                lead["name_source"] = "html_title_cleaned"
                break
        repaired, source = repair_company_name(
            name, str(lead.get("website", "")), domain
        )
        if repaired and repaired != name:
            name = repaired
            lead["name_source"] = source
    lead["company_name"] = name


def _strategic_row(spec: Dict[str, str], existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = deepcopy(existing) if existing else {}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    row.update({
        "company_name": spec["name"],
        "segment": "Large housing company",
        "website": spec["website"],
        "website_status": "ok",
        "address": spec["address"],
        "postcode": spec["postcode"],
        "bezirk": POSTCODE_TO_BEZIRK.get(spec["postcode"], "Berlin"),
        "normalized_domain": normalize_domain(spec["website"]),
        "name_source": "official_impressum",
        "sources": ["serper_organic", "targeted_strategic_query"],
        "source_count": 2,
        "source_urls": [spec["website"], spec["validation_url"]],
        "last_verified": now,
        "tier": "Strategic",
        "data_confidence": "high",
        "website_status": "ok",
    })
    for field in (
        "phone", "generic_email", "units_managed", "properties_managed",
        "employees_estimate", "management_type", "software_or_portal",
        "metering_provider_mentions", "energy_signals", "growth_signals",
        "contact_name", "contact_title", "academic_title", "contact_email",
        "email_origin", "guessed_email", "linkedin_url",
        "linkedin_match_note", "contact_confidence",
    ):
        row.setdefault(field, "unknown" if field not in {"linkedin_url"} else "")
    row["email_status"] = "none"
    row["kpi_evidence"] = "unknown"
    row["lead_score"] = row.get("lead_score", 0)
    row["kpi_fill_rate"] = row.get("kpi_fill_rate", 0)
    row["score_reason"] = "Strategic account validated on official company website"
    row["score_caveats"] = "Strategic coverage row; KPI enrichment not rerun"
    return row


def apply_cached_output_corrections() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    leads = _read_csv(DATA_RAW_DIR / "final_processed.csv")
    directory = _read_csv(DATA_RAW_DIR / "directory_only.csv")
    excluded = _read_csv(DATA_RAW_DIR / "excluded_discovered.csv")

    for row in leads + directory + excluded:
        _clean_name(row)
        row["postcode"] = extract_berlin_postcode(row.get("address", "")) or row.get("postcode", "")

    unresolved = []
    kept = []
    for row in leads:
        if row.get("company_name", "").strip().lower() == "zenveo":
            row["exclusion_reason"] = "name_unresolvable"
            unresolved.append(row)
            continue
        if _is_service_only(row.get("company_name", "")):
            domain = normalize_domain(row.get("website", ""))
            legal = _cached_legal_name(row.get("website", ""), domain)
            if legal:
                row["company_name"] = legal
                row["name_source"] = "impressum_legal_line"
            elif domain:
                row["company_name"] = domain.split(".")[0].replace("-", " ").title()
                row["name_source"] = "domain_derived"
            else:
                row["exclusion_reason"] = "name_unresolvable"
                unresolved.append(row)
                continue
        kept.append(row)
    leads = kept
    excluded.extend(unresolved)
    excluded = [
        row for row in excluded
        if "degewo" not in f"{row.get('company_name', '')} {row.get('website', '')}".lower()
    ]

    by_domain: Dict[str, Dict[str, Any]] = {}
    duplicates = []
    for row in sorted(
        leads,
        key=lambda item: (
            item.get("tier") == "Strategic",
            float(item.get("lead_score") or 0),
        ),
        reverse=True,
    ):
        domain = normalize_domain(row.get("website", ""))
        row["normalized_domain"] = domain
        if domain and domain in by_domain:
            row["notes"] = "Duplicate domain merged; retained for directory outreach."
            duplicates.append(row)
        else:
            by_domain[domain] = row
    leads = list(by_domain.values())
    directory.extend(duplicates)

    existing_by_domain = {normalize_domain(r.get("website", "")): r for r in leads}
    for key, spec in STRATEGIC_VALIDATED.items():
        domain = normalize_domain(spec["website"])
        existing = existing_by_domain.get(domain)
        if existing:
            row = _strategic_row(spec, existing)
            leads[leads.index(existing)] = row
        else:
            leads.append(_strategic_row(spec))
        existing_by_domain[domain] = leads[-1] if not existing else row

    unique_directory = {}
    for row in directory:
        key = (normalize_domain(row.get("website", "")), row.get("company_name", ""))
        unique_directory[key] = row
    directory = list(unique_directory.values())

    _write_csv(DATA_RAW_DIR / "final_processed.csv", leads)
    _write_csv(DATA_RAW_DIR / "directory_only.csv", directory)
    _write_csv(DATA_RAW_DIR / "excluded_discovered.csv", excluded)
    return leads, directory, excluded
