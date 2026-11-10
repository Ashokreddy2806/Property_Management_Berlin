import re
import json
import logging
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
import ftfy

from config import (
    BERLIN_BEZIRKE, AGGREGATOR_DOMAINS, DATA_CACHE_DIR,
    DECISION_MAKER_TITLES_WHITELIST
)
from src.cache import get_cached_http

logger = logging.getLogger(__name__)

BERLIN_POSTCODE_REGEX = re.compile(r"\b(1[0-4]\d{3})\b")

# Berlin Postcode Prefix -> Bezirk mapping (clean UTF-8)
POSTCODE_TO_BEZIRK = {
    # Mitte
    "10115": "Mitte", "10117": "Mitte", "10119": "Mitte", "10178": "Mitte", "10179": "Mitte",
    "10551": "Mitte", "10553": "Mitte", "10555": "Mitte", "10557": "Mitte", "10559": "Mitte",
    "13347": "Mitte", "13353": "Mitte", "13355": "Mitte", "13357": "Mitte", "13359": "Mitte",
    # Friedrichshain-Kreuzberg
    "10243": "Friedrichshain-Kreuzberg", "10245": "Friedrichshain-Kreuzberg", "10247": "Friedrichshain-Kreuzberg",
    "10249": "Friedrichshain-Kreuzberg", "10961": "Friedrichshain-Kreuzberg", "10963": "Friedrichshain-Kreuzberg",
    "10965": "Friedrichshain-Kreuzberg", "10967": "Friedrichshain-Kreuzberg", "10969": "Friedrichshain-Kreuzberg",
    "10997": "Friedrichshain-Kreuzberg", "10999": "Friedrichshain-Kreuzberg",
    # Pankow
    "10405": "Pankow", "10407": "Pankow", "10409": "Pankow", "10435": "Pankow", "10437": "Pankow",
    "10439": "Pankow", "13086": "Pankow", "13088": "Pankow", "13089": "Pankow", "13125": "Pankow",
    "13127": "Pankow", "13129": "Pankow", "13156": "Pankow", "13158": "Pankow", "13187": "Pankow", "13189": "Pankow",
    # Charlottenburg-Wilmersdorf
    "10585": "Charlottenburg-Wilmersdorf", "10587": "Charlottenburg-Wilmersdorf", "10589": "Charlottenburg-Wilmersdorf",
    "10623": "Charlottenburg-Wilmersdorf", "10625": "Charlottenburg-Wilmersdorf", "10627": "Charlottenburg-Wilmersdorf",
    "10629": "Charlottenburg-Wilmersdorf", "10707": "Charlottenburg-Wilmersdorf", "10709": "Charlottenburg-Wilmersdorf",
    "10711": "Charlottenburg-Wilmersdorf", "10713": "Charlottenburg-Wilmersdorf", "10715": "Charlottenburg-Wilmersdorf",
    "10717": "Charlottenburg-Wilmersdorf", "10719": "Charlottenburg-Wilmersdorf", "14050": "Charlottenburg-Wilmersdorf",
    "14052": "Charlottenburg-Wilmersdorf", "14053": "Charlottenburg-Wilmersdorf", "14055": "Charlottenburg-Wilmersdorf",
    "14057": "Charlottenburg-Wilmersdorf", "14059": "Charlottenburg-Wilmersdorf", "14193": "Charlottenburg-Wilmersdorf",
    "14195": "Charlottenburg-Wilmersdorf", "14197": "Charlottenburg-Wilmersdorf", "14199": "Charlottenburg-Wilmersdorf",
    # Spandau
    "13581": "Spandau", "13583": "Spandau", "13585": "Spandau", "13587": "Spandau", "13589": "Spandau",
    "13591": "Spandau", "13593": "Spandau", "13595": "Spandau", "13597": "Spandau", "13599": "Spandau",
    "13627": "Spandau", "13629": "Spandau",
    # Steglitz-Zehlendorf
    "12161": "Steglitz-Zehlendorf", "12163": "Steglitz-Zehlendorf", "12165": "Steglitz-Zehlendorf",
    "12167": "Steglitz-Zehlendorf", "12169": "Steglitz-Zehlendorf", "12203": "Steglitz-Zehlendorf",
    "12205": "Steglitz-Zehlendorf", "12207": "Steglitz-Zehlendorf", "12209": "Steglitz-Zehlendorf",
    "12247": "Steglitz-Zehlendorf", "12249": "Steglitz-Zehlendorf", "14109": "Steglitz-Zehlendorf",
    "14129": "Steglitz-Zehlendorf", "14163": "Steglitz-Zehlendorf", "14165": "Steglitz-Zehlendorf",
    "14167": "Steglitz-Zehlendorf", "14169": "Steglitz-Zehlendorf",
    # Tempelhof-Schöneberg
    "10777": "Tempelhof-Schöneberg", "10779": "Tempelhof-Schöneberg", "10781": "Tempelhof-Schöneberg",
    "10783": "Tempelhof-Schöneberg", "10787": "Tempelhof-Schöneberg", "10789": "Tempelhof-Schöneberg",
    "10823": "Tempelhof-Schöneberg", "10825": "Tempelhof-Schöneberg", "10827": "Tempelhof-Schöneberg",
    "10829": "Tempelhof-Schöneberg", "12099": "Tempelhof-Schöneberg", "12101": "Tempelhof-Schöneberg",
    "12103": "Tempelhof-Schöneberg", "12105": "Tempelhof-Schöneberg", "12157": "Tempelhof-Schöneberg",
    "12159": "Tempelhof-Schöneberg", "12277": "Tempelhof-Schöneberg", "12279": "Tempelhof-Schöneberg",
    # Neukölln
    "12043": "Neukölln", "12045": "Neukölln", "12047": "Neukölln", "12049": "Neukölln",
    "12051": "Neukölln", "12053": "Neukölln", "12055": "Neukölln", "12057": "Neukölln",
    "12059": "Neukölln", "12347": "Neukölln", "12349": "Neukölln", "12351": "Neukölln",
    "12353": "Neukölln", "12355": "Neukölln", "12357": "Neukölln", "12359": "Neukölln",
    # Treptow-Köpenick
    "12435": "Treptow-Köpenick", "12437": "Treptow-Köpenick", "12439": "Treptow-Köpenick",
    "12459": "Treptow-Köpenick", "12487": "Treptow-Köpenick", "12489": "Treptow-Köpenick",
    "12524": "Treptow-Köpenick", "12526": "Treptow-Köpenick", "12527": "Treptow-Köpenick",
    "12555": "Treptow-Köpenick", "12557": "Treptow-Köpenick", "12559": "Treptow-Köpenick",
    "12587": "Treptow-Köpenick", "12589": "Treptow-Köpenick",
    # Marzahn-Hellersdorf
    "12619": "Marzahn-Hellersdorf", "12621": "Marzahn-Hellersdorf", "12623": "Marzahn-Hellersdorf",
    "12627": "Marzahn-Hellersdorf", "12629": "Marzahn-Hellersdorf", "12679": "Marzahn-Hellersdorf",
    "12681": "Marzahn-Hellersdorf", "12683": "Marzahn-Hellersdorf", "12685": "Marzahn-Hellersdorf",
    "12687": "Marzahn-Hellersdorf", "12689": "Marzahn-Hellersdorf",
    # Lichtenberg
    "10315": "Lichtenberg", "10317": "Lichtenberg", "10318": "Lichtenberg", "10319": "Lichtenberg",
    "10365": "Lichtenberg", "10367": "Lichtenberg", "10369": "Lichtenberg", "13051": "Lichtenberg",
    "13053": "Lichtenberg", "13055": "Lichtenberg", "13057": "Lichtenberg", "13059": "Lichtenberg",
    # Reinickendorf
    "13349": "Reinickendorf", "13351": "Reinickendorf", "13403": "Reinickendorf", "13405": "Reinickendorf",
    "13407": "Reinickendorf", "13409": "Reinickendorf", "13435": "Reinickendorf", "13437": "Reinickendorf",
    "13439": "Reinickendorf", "13465": "Reinickendorf", "13467": "Reinickendorf", "13469": "Reinickendorf",
    "13503": "Reinickendorf", "13505": "Reinickendorf", "13507": "Reinickendorf", "13509": "Reinickendorf",
}

# Municipal / Mega housing companies (Section 1.6 & Problem 3)
MUNICIPAL_OR_MEGA = {
    "gewobag", "degewo", "howoge", "gesobau", "wbm", "stadt und land",
    "vonovia", "deutsche wohnen", "adler group", "adler real estate",
    "berliner stadtbau", "covivio", "heimstaden", "tag immobilien",
    "grand city property", "akelius"
}

# Generic / Article titles to exclude (Section 1 b)
GENERIC_EXACT = {
    "hausverwaltung", "service", "digital", "sondereigentum",
    "verwaltung von sondereigentum", "leistungen", "unsere leistungen",
    "immobilienverwaltung", "weg-verwaltung", "mietverwaltung", "verwaltung",
    "top 10", "berlin", "immobilien", "property management"
}

ARTICLE_PATTERNS = [
    re.compile(r"\b(anbieter|geprüfte fakten|unsere leistungen|im überblick|vergleich|ratgeber|kosten|erfahrungen|test|top \d+|\d+ anbieter|eine weitere)\b", re.I)
]

ASSOCIATION_PATTERNS = [
    re.compile(r"\b(ivd|vdiv|bfw|ddiv|haus & grund|haus und grund|mieterverein|mieterbund|ihk|verband|immoscout|immobilienscout|immowelt|gelbe seiten|11880|wikipedia|vergleichdoch|jacasa)\b", re.I)
]

EXCLUDED_INDUSTRIES = [
    re.compile(r"\b(construction|spezialbau|malerbetrieb|gebäudereinigung|gebaeudereinigung|reinigung|architekt|architekten|rechtsanwalt|notar|steuerberater|visualisierung|ingenieurbüro|tiefbau|hochbau)\b", re.I)
]

# Service terms for property management (for rescuing brokers)
HV_SERVICE_REGEX = re.compile(r"\b(hausverwaltung|weg-verwaltung|mietverwaltung|sondereigentumsverwaltung|sondereigentum|immobilienverwaltung|wohneigentumsverwaltung)\b", re.I)

# Lazy index of domain -> (plz, address_snippet) from cached HTTP responses
_CACHED_DOMAIN_PLZ_INDEX: Optional[Dict[str, Tuple[str, str]]] = None

def _get_cached_domain_plz_index() -> Dict[str, Tuple[str, str]]:
    global _CACHED_DOMAIN_PLZ_INDEX
    if _CACHED_DOMAIN_PLZ_INDEX is not None:
        return _CACHED_DOMAIN_PLZ_INDEX

    idx: Dict[str, Tuple[str, str]] = {}
    cache_dir = DATA_CACHE_DIR / "http"
    if cache_dir.exists():
        for p in cache_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    u = d.get("url", "")
                    t = d.get("text", "")
                    if u and t and "serper.dev" not in u and "hunter.io" not in u:
                        netloc = urlparse(u).netloc.lower()
                        if netloc.startswith("www."):
                            netloc = netloc[4:]
                        if netloc and netloc not in idx:
                            for m in re.finditer(r"\b(1[0-4]\d{3})\b", t):
                                plz = m.group(1)
                                if 10115 <= int(plz) <= 14199:
                                    win = t[max(0, m.start() - 60):min(len(t), m.end() + 60)]
                                    if "berlin" in win.lower() or "berlin" in t.lower():
                                        idx[netloc] = (plz, " ".join(win.split()))
                                        break
            except Exception:
                pass
    _CACHED_DOMAIN_PLZ_INDEX = idx
    return _CACHED_DOMAIN_PLZ_INDEX

# Lazy loaded goto redirects map
_GOTO_RESOLVED_MAP: Optional[Dict[str, str]] = None

def _get_goto_map() -> Dict[str, str]:
    global _GOTO_RESOLVED_MAP
    if _GOTO_RESOLVED_MAP is not None:
        return _GOTO_RESOLVED_MAP
    p = DATA_CACHE_DIR / "goto_resolved_map.json"
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                _GOTO_RESOLVED_MAP = json.load(f)
        except Exception:
            _GOTO_RESOLVED_MAP = {}
    else:
        _GOTO_RESOLVED_MAP = {}
    return _GOTO_RESOLVED_MAP

def normalize_domain(url: Optional[str]) -> str:
    if not url or not isinstance(url, str):
        return ""
    u = url.strip().lower()
    if not u or u in ["unknown", "none"]:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "http://" + u
    try:
        parsed = urlparse(u)
        netloc = parsed.netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Check against aggregator domains
        for agg in AGGREGATOR_DOMAINS:
            if netloc == agg or netloc.endswith(f".{agg}"):
                return ""
        return netloc.strip()
    except Exception:
        return ""

def normalize_phone(phone: Optional[str]) -> str:
    if not phone or not isinstance(phone, str):
        return "unknown"
    p = phone.strip()
    if not p or p.lower() in ["unknown", "none", "-", "/"]:
        return "unknown"
    
    cleaned = re.sub(r"[^\d+]", "", p)
    if not cleaned:
        return "unknown"
    
    if cleaned.startswith("0049"):
        cleaned = "+49" + cleaned[4:]
    elif cleaned.startswith("0"):
        cleaned = "+49" + cleaned[1:]
    elif not cleaned.startswith("+"):
        if cleaned.startswith("49"):
            cleaned = "+" + cleaned
        elif cleaned.startswith("30"):
            cleaned = "+49" + cleaned
        else:
            cleaned = "+4930" + cleaned

    if cleaned.startswith("+4930"):
        rest = cleaned[5:]
        return f"+49 30 {rest}"
    elif cleaned.startswith("+49"):
        return f"+49 {cleaned[3:]}"
    
    return p

def extract_berlin_postcode(text: Optional[str]) -> Optional[str]:
    """Extracts a valid Berlin postcode (10115 to 14199)."""
    if not text or not isinstance(text, str):
        return None
    matches = BERLIN_POSTCODE_REGEX.findall(text)
    for m in matches:
        val = int(m)
        if 10115 <= val <= 14199:
            return m
    return None

def detect_bezirk(address: str, snippet: str = "") -> str:
    postcode = extract_berlin_postcode(address) or extract_berlin_postcode(snippet)
    if postcode and postcode in POSTCODE_TO_BEZIRK:
        return POSTCODE_TO_BEZIRK[postcode]

    text = f"{address} {snippet}".lower()
    for b in BERLIN_BEZIRKE:
        b_lower = b.lower()
        if b_lower in text:
            return b
        if "-" in b_lower:
            parts = b_lower.split("-")
            if any(p in text for p in parts if len(p) > 4):
                return b
        elif b_lower == "mitte" and ("berlin-mitte" in text or " berlin mitte" in text):
            return "Mitte"
            
    return "Berlin"

def repair_company_name(raw_name: str, website: str, domain: str) -> Tuple[str, str]:
    """
    Section 1.1 & Problem 3: Repairs scraped company names looking like page titles,
    slogans, or mangled strings.
    Returns (repaired_name, name_source).
    """
    name = ftfy.fix_text(raw_name.strip())
    
    needs_repair = (
        name.endswith("...") or name.endswith("…") or "..." in name or "…" in name
        or len(name) < 4 or len(name) > 80
        or any(sep in name for sep in [" - ", " | ", " : ", ": ", " – ", " — "])
        or "treffer" in name.lower()
        or name.lower() in GENERIC_EXACT
        or any(pat.search(name) for pat in ARTICLE_PATTERNS)
        or any(slogan in name.lower() for slogan in [
            "modern & zuverlässig", "ihr partner", "ihre hausverwaltung",
            "im überblick", "geprüfte fakten", "unsere leistungen"
        ])
        or bool(re.search(r"^(?:hotline|adresse|sprechzeiten|kontakt|telefon|navigation|startseite|willkommen)", name, re.I))
    )

    if not needs_repair:
        return name, "original_scraped"

    # Strategy 1: Check embedded legal entity line in mangled string
    m = re.search(r'([A-ZÄÖÜ][a-zA-Z0-9ÄÖÜäöüß\s\.\&\-]{2,50}?\s+(?:GmbH & Co\. KG|GmbH|UG \(haftungsbeschränkt\)|UG|AG|e\.K\.|GbR|KG|eG))\b', name)
    if m:
        cand = m.group(1).strip()
        cand = re.sub(r'^(?:Hotline|Adresse|Sprechzeiten|Kontakt|Telefon|Navigation|Startseite|Willkommen|Ueber uns)+', '', cand).strip()
        if len(cand) >= 4 and any(suf in cand for suf in ['GmbH', 'UG', 'AG', 'e.K.', 'GbR', 'eG', 'KG']):
            return cand, "name_embedded_legal_line"

    # Strategy 2: If separated by delimiters (" - ", " | "), pick the clean company component
    for sep in [" - ", " | ", " – ", " — ", ": "]:
        if sep in name:
            parts = [p.strip() for p in name.split(sep)]
            for p in parts:
                p_clean = ftfy.fix_text(p)
                p_lower = p_clean.lower()
                # Must not be a generic phrase or article title
                if any(bad in p_lower for bad in [
                    "modern &", "zuverlässig", "berlin mitte", "leistungen",
                    "sondereigentumsverwaltung berlin", "treffer", "anbieter",
                    "kosten", "ratgeber", "vergleich", "erfahrungen", "test"
                ]):
                    continue
                if p_lower in GENERIC_EXACT:
                    continue
                if any(suf in p_clean for suf in ["GmbH", "UG", "AG", "e.K.", "GbR", "eG", "Hausverwaltung", "Management", "Immobilien"]):
                    if 4 <= len(p_clean) <= 60:
                        return p_clean, "html_title_cleaned"

    # Strategy 3: Check cached HTML for domain (Impressum, homepage, kontakt)
    candidates = []
    if website and "google.com/goto" not in website and "gelbeseiten" not in website:
        candidates.append(website)
    if domain:
        base = f"https://{domain}"
        candidates.extend([f"{base}/", f"{base}/impressum", f"{base}/ueber-uns", f"{base}/kontakt"])
        base_www = f"https://www.{domain}"
        candidates.extend([f"{base_www}/", f"{base_www}/impressum", f"{base_www}/ueber-uns", f"{base_www}/kontakt"])

    legal_regex = re.compile(r"^[^\n\r]{2,50}\s+(?:GmbH & Co\. KG|GmbH|UG \(haftungsbeschränkt\)|UG|AG|e\.K\.|GbR|KG|eG)$", re.M)

    for cand_url in candidates:
        cached = get_cached_http(cand_url)
        if cached and cached.get("text"):
            try:
                soup = BeautifulSoup(cached["text"], "html.parser")
                text = soup.get_text()
                
                # Impressum legal company line
                for line in text.splitlines():
                    line = ftfy.fix_text(line.strip())
                    if legal_regex.match(line):
                        if not any(bad in line.lower() for bad in ["anzeige", "datenschutz", "agb", "cookies", "anbieter", "register"]):
                            return line, "impressum_legal_line"

                # og:site_name
                og = soup.find("meta", property="og:site_name")
                if og and og.get("content"):
                    c_og = ftfy.fix_text(og["content"].strip())
                    if 4 <= len(c_og) <= 50 and not any(bad in c_og.lower() for bad in ["anbieter", "kosten", "ratgeber", "vergleich", "portal"]):
                        return c_og, "og_site_name"
            except Exception:
                pass

    # Strategy 4: Clean domain name
    if domain:
        dom_clean = domain.split(".")[0].replace("-", " ").title()
        if len(dom_clean) >= 4 and not any(bad in dom_clean.lower() for bad in ["anbieter", "vergleich", "ratgeber", "portal"]):
            final_name = f"{dom_clean} Hausverwaltung" if "hausverwaltung" not in dom_clean.lower() else dom_clean
            return final_name, "domain_derived"

    return name, "unrepaired"

def check_berlin_in_crawled_pages(website: str, domain: str) -> Optional[Tuple[str, str]]:
    """Checks cached HTML for a Berlin postcode (10115 to 14199) and returns (postcode, address)."""
    # First check cached index
    plz_idx = _get_cached_domain_plz_index()
    if domain in plz_idx:
        return plz_idx[domain]

    candidates = []
    if website:
        candidates.append(website)
    if domain:
        base = f"https://{domain}"
        candidates.extend([f"{base}/", f"{base}/impressum", f"{base}/kontakt", f"{base}/ueber-uns"])
        base_www = f"https://www.{domain}"
        candidates.extend([f"{base_www}/", f"{base_www}/impressum", f"{base_www}/kontakt", f"{base_www}/ueber-uns"])

    for cand_url in candidates:
        cached = get_cached_http(cand_url)
        if cached and cached.get("text"):
            try:
                soup = BeautifulSoup(cached["text"], "html.parser")
                text = soup.get_text()
                for m in re.finditer(r"\b(1[0-4]\d{3})\b", text):
                    plz = m.group(1)
                    if 10115 <= int(plz) <= 14199:
                        window = text[max(0, m.start() - 60):min(len(text), m.end() + 60)]
                        if "berlin" in window.lower() or "berlin" in text.lower():
                            addr_snippet = " ".join(window.split())
                            return plz, addr_snippet
            except Exception:
                pass
    return None

def is_valid_company_row(lead: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Section 1 & Problems 1, 2, 3: Evaluates whether a candidate row is a valid Berlin Hausverwaltung.
    Returns (is_valid: bool, exclusion_reason: str, segment: str).
    """
    name = ftfy.fix_text(lead.get("company_name", "").strip())
    domain = lead.get("normalized_domain", "").strip().lower()
    website = lead.get("website", "").strip().lower()
    address = ftfy.fix_text(lead.get("address", "").strip())
    name_source = lead.get("name_source", "original_scraped")

    # 1. Directory listing pages ("Treffer", /branchen/ URLs)
    if "treffer" in name.lower() or "/branchen/" in website or "gelbeseiten.de/branchen" in website:
        return False, "directory_listing_page", "Other/not a Hausverwaltung"

    # 2. Truncated or too short
    if name.endswith("...") or name.endswith("…") or len(name) < 4:
        return False, "truncated_name_or_too_short", "Other/not a Hausverwaltung"

    # 3. Unrepaired title / slogan name (>80 chars or contains delimiters)
    if len(name) > 80 or any(sep in name for sep in [" - ", " | ", ": "]):
        return False, "name_unresolvable", "Other/not a Hausverwaltung"

    # 4. Generic name or article/comparison title
    name_lower = name.lower()
    if name_lower in GENERIC_EXACT:
        return False, "generic_unspecific_name", "Other/not a Hausverwaltung"
    for pat in ARTICLE_PATTERNS:
        if pat.search(name):
            return False, f"article_or_comparison_title: {pat.pattern}", "Other/not a Hausverwaltung"

    # 5. Association, portal, or directory
    for pat in ASSOCIATION_PATTERNS:
        if pat.search(name) or (domain and pat.search(domain)):
            return False, f"association_directory_or_portal: {pat.pattern}", "Other/not a Hausverwaltung"
    if name_lower.endswith(" e.v.") or " e. v." in name_lower:
        if not any(hv in name_lower for hv in ["hausverwaltung", "immobilienverwaltung", "eigentümergemeinschaft"]):
            return False, "association_ev", "Other/not a Hausverwaltung"

    # 6. Excluded industry (construction, facility, cleaning, architecture, law)
    for pat in EXCLUDED_INDUSTRIES:
        if pat.search(name) or (domain and pat.search(domain)):
            return False, f"excluded_industry: {pat.pattern}", "Other/not a Hausverwaltung"

    # 7. Real estate broker check (Problem 2):
    # Only exclude if NO property management service is offered on website
    is_broker_name = bool(re.search(r"\b(makler|immobilienmakler|real estate broker|real estate agency)\b", name, re.I))
    if is_broker_name:
        # Check website text
        has_hv_service = False
        if domain:
            for test_url in [website, f"https://{domain}/", f"https://{domain}/leistungen", f"https://www.{domain}/leistungen"]:
                cached = get_cached_http(test_url)
                if cached and cached.get("text"):
                    if HV_SERVICE_REGEX.search(cached["text"]):
                        has_hv_service = True
                        break
        if not has_hv_service:
            return False, "real_estate_broker_no_hv", "Other/not a Hausverwaltung"

    # 8. Segment Classification (Problem 3)
    # Check cooperative first
    is_coop = bool(re.search(r"\b(eG|e\.G\.|Wohnungsgenossenschaft|Wohnungsbaugenossenschaft|Baugenossenschaft)\b", name, re.I))
    if is_coop:
        segment = "Housing cooperative"
    else:
        # Check municipal or large housing company
        is_municipal = any(m in name_lower for m in MUNICIPAL_OR_MEGA) or (domain and any(m in domain for m in MUNICIPAL_OR_MEGA))
        if is_municipal:
            segment = "Large housing company"
        else:
            segment = "Private Hausverwaltung"

    # 9. Berlin postcode verification (Section 1.5 & Problem 2)
    # Require 10115 to 14199 in address or Impressum
    postcode = extract_berlin_postcode(address)
    if not postcode:
        crawled_res = check_berlin_in_crawled_pages(website, domain)
        if crawled_res:
            plz, full_addr = crawled_res
            lead["address"] = f"{address}, {plz} Berlin".strip(", ") if address and address != "Berlin" else f"{plz} Berlin"
            lead["bezirk"] = POSTCODE_TO_BEZIRK.get(plz, "Berlin")
            lead["berlin_verified_via"] = "impressum"
        else:
            return False, "berlin_not_verified", "Other/not a Hausverwaltung"

    return True, "", segment

def deduplicate_leads(raw_leads: List[Dict[str, Any]], name_threshold: int = 92) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Section 1.2 & Problems 1, 2, 3: Normalizes, repairs names, resolves redirects/aggregators,
    and deduplicates leads.
    Returns (valid_leads, excluded_leads).
    Guarantees 0 duplicate domains and 0 duplicate normalized names.
    """
    goto_map = _get_goto_map()
    by_domain: Dict[str, Dict[str, Any]] = {}
    no_domain: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    # First pass: resolve goto URLs, repair names, and dedupe by domain
    for lead in raw_leads:
        w = lead.get("website", "").strip()
        # 1. Resolve google.com/goto redirects
        if "google.com/goto" in w and w in goto_map and goto_map[w]:
            w = goto_map[w]
            lead["website"] = w

        # 2. Aggregator domain check
        domain = normalize_domain(w)
        if not domain and w:
            # Website was an aggregator domain or invalid
            lead["website"] = ""
            lead["website_status"] = "none"
        else:
            lead["website"] = w

        lead["normalized_domain"] = domain
        lead["company_name"] = ftfy.fix_text(lead.get("company_name", ""))
        lead["address"] = ftfy.fix_text(lead.get("address", ""))

        # 3. Repair company name
        repaired_name, name_source = repair_company_name(lead["company_name"], lead.get("website", ""), domain)
        lead["company_name"] = ftfy.fix_text(repaired_name)
        lead["name_source"] = name_source
        
        lead["phone"] = normalize_phone(lead.get("phone"))
        lead["bezirk"] = ftfy.fix_text(detect_bezirk(lead.get("address", ""), lead.get("snippet", "")))

        src = lead.get("source", "unknown")
        src_url = lead.get("source_url", "")

        if domain:
            if domain in by_domain:
                existing = by_domain[domain]
                existing_sources = set(existing.get("sources", []))
                existing_sources.add(src)
                existing["sources"] = sorted(list(existing_sources))
                existing["source_count"] = len(existing["sources"])
                
                existing_urls = set(existing.get("source_urls", []))
                if src_url:
                    existing_urls.add(src_url)
                existing["source_urls"] = sorted(list(existing_urls))

                # Upgrade fields if current has better information
                if existing.get("phone") == "unknown" and lead.get("phone") != "unknown":
                    existing["phone"] = lead["phone"]
                if existing.get("address") in ["Berlin", ""] and lead.get("address") not in ["Berlin", ""]:
                    existing["address"] = lead.get("address")
                    existing["bezirk"] = lead.get("bezirk")
                if existing.get("name_source") in ["unrepaired", "domain_derived"] and lead.get("name_source") in ["impressum_legal_line", "html_title_cleaned", "name_embedded_legal_line"]:
                    existing["company_name"] = lead["company_name"]
                    existing["name_source"] = lead["name_source"]
            else:
                lead["sources"] = [src]
                lead["source_count"] = 1
                lead["source_urls"] = [src_url] if src_url else []
                by_domain[domain] = lead
        else:
            lead["sources"] = [src]
            lead["source_count"] = 1
            lead["source_urls"] = [src_url] if src_url else []
            no_domain.append(lead)

    domain_merged = list(by_domain.values())

    # Fuzzy match rows without domain against domain_merged
    for item in no_domain:
        matched = False
        item_name = item.get("company_name", "").strip().lower()
        if not item_name:
            continue

        for existing in domain_merged:
            ex_name = existing.get("company_name", "").strip().lower()
            score = fuzz.token_sort_ratio(item_name, ex_name)
            if score >= name_threshold:
                ex_sources = set(existing.get("sources", []))
                ex_sources.add(item.get("source", "unknown"))
                existing["sources"] = sorted(list(ex_sources))
                existing["source_count"] = len(existing["sources"])
                if item.get("source_url"):
                    ex_urls = set(existing.get("source_urls", []))
                    ex_urls.add(item["source_url"])
                    existing["source_urls"] = sorted(list(ex_urls))
                matched = True
                break

        if not matched:
            domain_merged.append(item)

    # Second pass: dedupe on normalized name across all rows
    def _normalize_name_for_dedupe(n: str) -> str:
        s = n.lower()
        s = re.sub(r"\b(gmbh & co\. kg|gmbh|ug|ag|e\.k\.|gbr|kg|haftungsbeschränkt|hausverwaltung|verwaltung|immobilien|management)\b", "", s)
        s = re.sub(r"[^\w\s]", "", s)
        return " ".join(s.split())

    final_unique: List[Dict[str, Any]] = []
    seen_normalized_names: Dict[str, Dict[str, Any]] = {}

    for lead in domain_merged:
        norm_name = _normalize_name_for_dedupe(lead["company_name"])
        if not norm_name or len(norm_name) < 3:
            norm_name = lead["company_name"].strip().lower()

        duplicate_found = False
        for seen_norm, existing_lead in seen_normalized_names.items():
            if fuzz.token_sort_ratio(norm_name, seen_norm) >= name_threshold:
                ex_sources = set(existing_lead.get("sources", []))
                ex_sources.update(lead.get("sources", []))
                existing_lead["sources"] = sorted(list(ex_sources))
                existing_lead["source_count"] = len(existing_lead["sources"])

                ex_urls = set(existing_lead.get("source_urls", []))
                ex_urls.update(lead.get("source_urls", []))
                existing_lead["source_urls"] = sorted(list(ex_urls))
                duplicate_found = True
                break

        if not duplicate_found:
            seen_normalized_names[norm_name] = lead
            final_unique.append(lead)

    # Validate each row with is_valid_company_row
    valid_leads: List[Dict[str, Any]] = []
    for lead in final_unique:
        is_valid, reason, segment = is_valid_company_row(lead)
        lead["segment"] = segment
        if is_valid:
            valid_leads.append(lead)
        else:
            lead["exclusion_reason"] = reason
            excluded.append(lead)

    return valid_leads, excluded
