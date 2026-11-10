import json
import re
import html
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field
import ftfy
from config import GENERIC_EMAIL_PREFIXES, PROMPT_VERSION
from src.llm import call_llm_json

# Track values dropped by evidence verification (Section 4.2)
_DROPPED_VALUES_LOG: Dict[str, int] = {
    "units_managed": 0,
    "properties_managed": 0,
    "employees_estimate": 0,
    "management_type": 0,
    "software_or_portal": 0,
    "metering_provider_mentions": 0,
    "energy_signals": 0,
    "growth_signals": 0,
}

def get_dropped_values_log() -> Dict[str, int]:
    return dict(_DROPPED_VALUES_LOG)

class FieldWithEvidence(BaseModel):
    value: Optional[Any] = None
    evidence_quote: Optional[str] = None
    source_url: Optional[str] = None

class PersonEntry(BaseModel):
    name: str
    title: str = "Geschäftsführer"
    evidence_quote: Optional[str] = None
    source_url: Optional[str] = None

class CompanyEnrichmentSchema(BaseModel):
    units_managed: Optional[FieldWithEvidence] = None
    properties_managed: Optional[FieldWithEvidence] = None
    employees_estimate: Optional[FieldWithEvidence] = None
    management_type: FieldWithEvidence = Field(default_factory=lambda: FieldWithEvidence(value="unknown"))
    founded_year: Optional[FieldWithEvidence] = None
    software_or_portal: Optional[FieldWithEvidence] = None
    metering_provider_mentions: Optional[FieldWithEvidence] = None
    energy_signals: Optional[FieldWithEvidence] = None
    growth_signals: Optional[FieldWithEvidence] = None
    managing_directors: List[PersonEntry] = Field(default_factory=list)
    other_people: List[PersonEntry] = Field(default_factory=list)
    emails_found: List[str] = Field(default_factory=list)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

def is_generic_email(email: str) -> bool:
    if not email or "@" not in email:
        return True
    prefix = email.split("@")[0].lower()
    for g in GENERIC_EMAIL_PREFIXES:
        if prefix == g or prefix.startswith(f"{g}.") or prefix.startswith(f"{g}-") or prefix.startswith(f"{g}_"):
            return True
        if prefix.endswith(f".{g}") or prefix.endswith(f"-{g}") or prefix.endswith(f"_{g}"):
            return True
    return False

def clean_text_hygiene(raw_text: str) -> str:
    """
    Section 4.1: Fixes mojibake, normalizes whitespace and removes crawler artifacts
    such as '--- PAGE SOURCE:' headers before extraction.
    """
    if not raw_text:
        return ""
    
    # 1. Fix Unicode mojibake
    text = ftfy.fix_text(raw_text)
    
    # 2. Decode HTML entities
    text = html.unescape(text)

    # 3. Strip crawler artifact lines
    lines = []
    for line in text.splitlines():
        line_s = line.strip()
        if line_s.startswith("--- PAGE SOURCE:") or line_s.startswith("=== PAGE URL:"):
            continue
        lines.append(line)
    
    cleaned = "\n".join(lines)
    # Collapse excessive newlines and spaces
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()

def normalize_text_for_matching(text: str) -> str:
    """Normalizes text for robust quote matching against page text."""
    if not text:
        return ""
    t = ftfy.fix_text(text)
    t = html.unescape(t).lower()
    # Strip crawler artifacts if accidentally in quote
    t = re.sub(r"--- page source:.*", "", t)
    # Replace punctuation with single space
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    return " ".join(t.split())

def verify_evidence_in_text(evidence: Optional[str], full_text: str) -> bool:
    """
    Section 4.2: Strictly checks that an evidence quote appears in that company's own crawled text.
    Normalizes punctuation, entities, and whitespace.
    """
    if not evidence or not isinstance(evidence, str):
        return False
    
    ev_norm = normalize_text_for_matching(evidence)
    if len(ev_norm) < 6:
        return False
        
    txt_norm = normalize_text_for_matching(full_text)
    
    # Direct substring
    if ev_norm in txt_norm:
        return True
        
    # Check 35-char leading window
    if len(ev_norm) > 35 and ev_norm[:35] in txt_norm:
        return True

    # Check 35-char trailing window
    if len(ev_norm) > 35 and ev_norm[-35:] in txt_norm:
        return True
        
    return False

def validate_units_managed(units_val: Any, evidence_quote: Optional[str], is_private_company: bool = True) -> Optional[int]:
    """
    Section 4.4: Deterministic post-validator for units_managed.
    - Rejects minimum service sizes ('ab zwei Einheiten', 'ab 5 Einheiten')
    - Rejects association / market-wide totals (IVD '3,5 Millionen')
    - Rejects values > 50,000 for private companies
    - Requires the integer to appear in the evidence quote
    """
    if units_val is None or not evidence_quote:
        return None
        
    q_lower = evidence_quote.lower()
    
    # Reject minimum service threshold phrases
    minimum_phrases = [
        "ab zwei einheiten", "ab 2 einheiten", "ab 5 einheiten", "ab 1 einheit",
        "ab 3 einheiten", "ab 10 einheiten", "ab zehn einheiten", "ab 1 we", "ab 2 we"
    ]
    if any(p in q_lower for p in minimum_phrases):
        return None

    # Reject association / macro market totals
    association_phrases = [
        "3,5 millionen", "3.5 millionen", "3,5 mio", "3.500.000", "millionen wohnungen",
        "deutschlandweit verwalten mitglieder", "ivd-mitglieder"
    ]
    if any(p in q_lower for p in association_phrases):
        return None

    # Parse integer from value
    val_str = str(units_val).replace(".", "").replace(",", "").strip()
    digits = re.findall(r"\b\d+\b", val_str)
    if not digits:
        return None
    val_int = int(digits[0])

    # Private company cap
    if is_private_company and val_int > 50000:
        return None

    # Require integer or formatted number to appear in evidence quote
    q_digits = [int(n.replace(".", "").replace(",", "")) for n in re.findall(r"\b\d[\d.,]*\b", evidence_quote) if re.search(r"\d", n)]
    if val_int not in q_digits:
        # Check if range average
        if len(q_digits) >= 2 and min(q_digits) <= val_int <= max(q_digits):
            return val_int
        return None

    return val_int

_EXTRACTION_CACHE_INDEX: Optional[Dict[str, dict]] = None

def _load_extraction_cache_index() -> Dict[str, dict]:
    global _EXTRACTION_CACHE_INDEX
    if _EXTRACTION_CACHE_INDEX is not None:
        return _EXTRACTION_CACHE_INDEX
    
    index: Dict[str, dict] = {}
    from config import DATA_CACHE_DIR
    import glob
    cache_files = glob.glob(str(DATA_CACHE_DIR / "llm" / "*.json"))
    for p in cache_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                prompt = d.get("prompt", "")
                resp = d.get("response", "")
                if prompt.startswith("You are an expert real estate data extraction agent"):
                    m = re.search(r'Target Company:\s*(?:\"([^\"]+)\"|([^\n\r(]+))(?:\s*\(([^)]+)\))?', prompt)
                    if m:
                        cname = (m.group(1) or m.group(2) or "").strip().lower()
                        url = (m.group(3) or "").strip()
                        r_clean = resp.strip()
                        if r_clean.startswith("```"):
                            r_clean = re.sub(r"^```(?:json)?\s*", "", r_clean)
                            r_clean = re.sub(r"\s*```$", "", r_clean)
                        parsed = json.loads(r_clean)
                        if url:
                            from src.clean_dedupe import normalize_domain
                            dom = normalize_domain(url)
                            if dom:
                                index[f"dom:{dom}"] = parsed
                        if cname:
                            index[f"name:{cname}"] = parsed
        except Exception:
            pass
    _EXTRACTION_CACHE_INDEX = index
    return _EXTRACTION_CACHE_INDEX

def _get_cached_extraction_json(company_name: str, website: str) -> Optional[dict]:
    index = _load_extraction_cache_index()
    from src.clean_dedupe import normalize_domain
    dom = normalize_domain(website)
    if dom and f"dom:{dom}" in index:
        return index[f"dom:{dom}"]
    cname = company_name.strip().lower()
    if cname and f"name:{cname}" in index:
        return index[f"name:{cname}"]
    return None

def extract_company_kpis(company_name: str, website: str, combined_text: str, default_url: str) -> Dict[str, Any]:
    """
    Agent 2 Enrichment (Prompt Version 2.0):
    Extracts KPI fields from crawled text with evidence quotes and strict validation.
    """
    global _DROPPED_VALUES_LOG

    cleaned_text = clean_text_hygiene(combined_text)
    if not cleaned_text or len(cleaned_text.strip()) < 100:
        return _empty_kpi_result(default_url)

    # Section 4.3: Few-shot prompt with strict negative examples
    prompt = f"""You are an expert real estate data extraction agent analyzing a German property manager's website for Heidi Systems (a metering provider).
The website text is in German. Understand the German terminology accurately.

CRITICAL RULES (PROMPT VERSION {PROMPT_VERSION}):
1. NEVER INVENT OR GUESS DATA. If a field is not explicitly stated in the text for THIS SPECIFIC COMPANY, set its "value" to null.
2. For EVERY filled field, you MUST provide an "evidence_quote" copied EXACTLY from the page text.
3. units_managed counts ONLY the company's own current portfolio statements ("wir verwalten/betreuen ... Wohneinheiten/Einheiten/WE").
   - DO NOT extract: minimum service sizes ("ab zwei Einheiten", "ab 5 Einheiten"), prices, client testimonials, association-wide totals (IVD "3,5 Millionen"), single-property reference lists, or blog posts.
4. properties_managed and employees_estimate follow the same own-company rule.
5. software_or_portal: ONLY tenant/owner portals (Mieterportal, Eigentümerportal, Kundenportal, Mieter-App) and named property management software (Aareon, Domus, Haufe, Casavi, Immoware24).
   - DO NOT count contact forms, job portals, career pages, or inquiry forms as portals.
6. management_type evidence must name Miet- and/or WEG-/Eigentümerverwaltung.
7. growth_signals: ONLY active hiring statements ("Wir stellen ein", "Stellenangebote") or expansion announcements. A plain link to an empty career page is null.

FEW-SHOT EXAMPLES:
Example 1 (Correct units):
Text: "Aktuell betreuen wir über 3.500 Einheiten im gesamten Berliner Stadtgebiet."
-> units_managed: {{"value": 3500, "evidence_quote": "Aktuell betreuen wir über 3.500 Einheiten im gesamten Berliner Stadtgebiet."}}

Example 2 (Incorrect units - minimum service threshold):
Text: "Wir bieten professionelle WEG-Verwaltung bereits ab zwei Einheiten an."
-> units_managed: {{"value": null, "evidence_quote": null}}  // "ab zwei Einheiten" is a minimum threshold, NOT current portfolio size!

Example 3 (Incorrect units - association total):
Text: "Als Mitglied im Verband der Immobilienverwalter betreuen die Mitgliedsunternehmen bundesweit über 3,5 Millionen Wohnungen."
-> units_managed: {{"value": null, "evidence_quote": null}}  // Association total, NOT this company's units!

Example 4 (Correct portal vs incorrect):
Text: "Nutzen Sie unser 24/7 Kundenportal für Schadensmeldungen. Bewerbungen richten Sie bitte an jobs@firma.de."
-> software_or_portal: {{"value": ["Kundenportal"], "evidence_quote": "Nutzen Sie unser 24/7 Kundenportal für Schadensmeldungen"}}

Target Company: {company_name} ({website})

Extract the following JSON schema:
{{
  "units_managed": {{"value": integer or null, "evidence_quote": string or null, "source_url": string or null}},
  "properties_managed": {{"value": integer or null, "evidence_quote": string or null, "source_url": string or null}},
  "employees_estimate": {{"value": integer or null, "evidence_quote": string or null, "source_url": string or null}},
  "management_type": {{"value": "Mietverwaltung" | "WEG" | "both" | "unknown", "evidence_quote": string or null, "source_url": string or null}},
  "founded_year": {{"value": integer or null, "evidence_quote": string or null, "source_url": string or null}},
  "software_or_portal": {{"value": ["Casavi", "Domus", "Kundenportal", etc.] or [], "evidence_quote": string or null, "source_url": string or null}},
  "metering_provider_mentions": {{"value": ["Techem", "ista", "Brunata", "Minol", "in-house"] or [], "evidence_quote": string or null, "source_url": string or null}},
  "energy_signals": {{"value": ["Funkzähler", "Smart Metering", "Fernablesung", "Heizkostenverordnung"] or [], "evidence_quote": string or null, "source_url": string or null}},
  "growth_signals": {{"value": ["Stellenangebote", "Expansion", "Wachstum"] or [], "evidence_quote": string or null, "source_url": string or null}},
  "managing_directors": [{{"name": "Full Name", "title": "Geschäftsführer/Inhaber", "evidence_quote": string, "source_url": string}}],
  "other_people": [{{"name": "Full Name", "title": "Prokurist / Bereichsleitung", "evidence_quote": string, "source_url": string}}],
  "emails_found": ["personal.email@domain.de", "info@domain.de"]
}}

PAGE TEXT:
{cleaned_text[:18000]}
"""

    raw_json = _get_cached_extraction_json(company_name, website)
    if raw_json is None:
        try:
            raw_json = call_llm_json(prompt, stage="enrichment_agent2")
        except Exception:
            return _empty_kpi_result(default_url)

    try:
        parsed = CompanyEnrichmentSchema.model_validate(raw_json)
    except Exception:
        return _empty_kpi_result(default_url)

    # Scan regex emails
    regex_emails = set(EMAIL_REGEX.findall(cleaned_text))
    clean_emails = set()
    for em in list(parsed.emails_found) + list(regex_emails):
        em_clean = em.strip().lower()
        if "@" in em_clean and "." in em_clean.split("@")[-1] and len(em_clean) <= 60:
            if not em_clean.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".pdf")):
                clean_emails.add(em_clean)

    res = {
        "units_managed": "unknown",
        "properties_managed": "unknown",
        "employees_estimate": "unknown",
        "management_type": "unknown",
        "founded_year": "unknown",
        "software_or_portal": "none",
        "metering_provider_mentions": "none",
        "energy_signals": "none",
        "growth_signals": "none",
        "managing_directors": [],
        "other_people": [],
        "generic_emails": [],
        "personal_emails": [],
        "evidence_quotes": {},
        "kpi_source_urls": {}
    }

    from src.clean_dedupe import normalize_domain
    company_domain = normalize_domain(website or default_url)

    def _is_own_domain_source(src_url: Optional[str]) -> bool:
        if not src_url:
            return True
        src_dom = normalize_domain(src_url)
        if not src_dom or not company_domain:
            return True
        return (src_dom == company_domain) or src_dom.endswith(f".{company_domain}") or company_domain.endswith(f".{src_dom}")

    # 1. Units managed with post-validation and strict company isolation (Problem 4)
    if parsed.units_managed and parsed.units_managed.value is not None:
        quote = ftfy.fix_text(parsed.units_managed.evidence_quote or "")
        src_url = parsed.units_managed.source_url or default_url
        if _is_own_domain_source(src_url) and verify_evidence_in_text(quote, cleaned_text):
            validated_int = validate_units_managed(parsed.units_managed.value, quote, is_private_company=True)
            if validated_int is not None:
                res["units_managed"] = str(validated_int)
                res["evidence_quotes"]["units_managed"] = quote
                res["kpi_source_urls"]["units_managed"] = src_url
            else:
                _DROPPED_VALUES_LOG["units_managed"] += 1
        else:
            _DROPPED_VALUES_LOG["units_managed"] += 1

    # 2. Properties managed
    if parsed.properties_managed and parsed.properties_managed.value is not None:
        quote = parsed.properties_managed.evidence_quote
        if verify_evidence_in_text(quote, cleaned_text):
            res["properties_managed"] = str(parsed.properties_managed.value)
            res["evidence_quotes"]["properties_managed"] = quote
            res["kpi_source_urls"]["properties_managed"] = parsed.properties_managed.source_url or default_url
        else:
            _DROPPED_VALUES_LOG["properties_managed"] += 1

    # 3. Employees estimate
    if parsed.employees_estimate and parsed.employees_estimate.value is not None:
        quote = parsed.employees_estimate.evidence_quote
        if verify_evidence_in_text(quote, cleaned_text):
            res["employees_estimate"] = str(parsed.employees_estimate.value)
            res["evidence_quotes"]["employees_estimate"] = quote
            res["kpi_source_urls"]["employees_estimate"] = parsed.employees_estimate.source_url or default_url
        else:
            _DROPPED_VALUES_LOG["employees_estimate"] += 1

    # 4. Management type
    if parsed.management_type and parsed.management_type.value:
        quote = parsed.management_type.evidence_quote
        m_val = str(parsed.management_type.value).lower()
        if "both" in m_val or ("miet" in m_val and "weg" in m_val):
            final_type = "both"
        elif "weg" in m_val:
            final_type = "WEG"
        elif "miet" in m_val:
            final_type = "Mietverwaltung"
        else:
            final_type = "unknown"
            
        if final_type != "unknown" and verify_evidence_in_text(quote, cleaned_text):
            res["management_type"] = final_type
            res["evidence_quotes"]["management_type"] = quote
            res["kpi_source_urls"]["management_type"] = parsed.management_type.source_url or default_url
        elif final_type != "unknown":
            _DROPPED_VALUES_LOG["management_type"] += 1

    # 5. Software / Portal
    if parsed.software_or_portal and parsed.software_or_portal.value:
        quote = parsed.software_or_portal.evidence_quote
        val_list = parsed.software_or_portal.value if isinstance(parsed.software_or_portal.value, list) else [parsed.software_or_portal.value]
        # Filter out false portals
        valid_items = [
            v for v in val_list
            if v and v.lower() not in ["none", "null", "karriere", "bewerbung", "kontaktformular", "online-bewerbung"]
        ]
        if valid_items and verify_evidence_in_text(quote, cleaned_text):
            res["software_or_portal"] = ", ".join(valid_items)
            res["evidence_quotes"]["software_or_portal"] = quote
            res["kpi_source_urls"]["software_or_portal"] = parsed.software_or_portal.source_url or default_url
        elif valid_items:
            _DROPPED_VALUES_LOG["software_or_portal"] += 1

    # 6. Metering provider mentions
    if parsed.metering_provider_mentions and parsed.metering_provider_mentions.value:
        quote = parsed.metering_provider_mentions.evidence_quote
        val_list = parsed.metering_provider_mentions.value if isinstance(parsed.metering_provider_mentions.value, list) else [parsed.metering_provider_mentions.value]
        valid_items = [v for v in val_list if v and v.lower() not in ["none", "null"]]
        if valid_items and verify_evidence_in_text(quote, cleaned_text):
            res["metering_provider_mentions"] = ", ".join(valid_items)
            res["evidence_quotes"]["metering_provider_mentions"] = quote
            res["kpi_source_urls"]["metering_provider_mentions"] = parsed.metering_provider_mentions.source_url or default_url
        elif valid_items:
            _DROPPED_VALUES_LOG["metering_provider_mentions"] += 1

    # 7. Energy signals
    if parsed.energy_signals and parsed.energy_signals.value:
        quote = parsed.energy_signals.evidence_quote
        val_list = parsed.energy_signals.value if isinstance(parsed.energy_signals.value, list) else [parsed.energy_signals.value]
        valid_items = [v for v in val_list if v and v.lower() not in ["none", "null"]]
        if valid_items and verify_evidence_in_text(quote, cleaned_text):
            res["energy_signals"] = ", ".join(valid_items)
            res["evidence_quotes"]["energy_signals"] = quote
            res["kpi_source_urls"]["energy_signals"] = parsed.energy_signals.source_url or default_url
        elif valid_items:
            _DROPPED_VALUES_LOG["energy_signals"] += 1

    # 8. Growth signals
    if parsed.growth_signals and parsed.growth_signals.value:
        quote = parsed.growth_signals.evidence_quote
        val_list = parsed.growth_signals.value if isinstance(parsed.growth_signals.value, list) else [parsed.growth_signals.value]
        valid_items = [v for v in val_list if v and v.lower() not in ["none", "null"]]
        if valid_items and verify_evidence_in_text(quote, cleaned_text):
            res["growth_signals"] = ", ".join(valid_items)
            res["evidence_quotes"]["growth_signals"] = quote
            res["kpi_source_urls"]["growth_signals"] = parsed.growth_signals.source_url or default_url
        elif valid_items:
            _DROPPED_VALUES_LOG["growth_signals"] += 1

    # People verification
    for p in parsed.managing_directors:
        if p.name and len(p.name) > 3 and verify_evidence_in_text(p.name, cleaned_text):
            res["managing_directors"].append({
                "name": p.name.strip(),
                "title": p.title.strip() or "Geschäftsführer",
                "evidence_quote": p.evidence_quote or p.name,
                "source_url": p.source_url or default_url
            })

    for p in parsed.other_people:
        if p.name and len(p.name) > 3 and verify_evidence_in_text(p.name, cleaned_text):
            res["other_people"].append({
                "name": p.name.strip(),
                "title": p.title.strip() or "Mitarbeiter",
                "evidence_quote": p.evidence_quote or p.name,
                "source_url": p.source_url or default_url
            })

    # Segregate generic vs personal emails
    for em in clean_emails:
        if is_generic_email(em):
            res["generic_emails"].append(em)
        else:
            res["personal_emails"].append(em)

    return res

def _empty_kpi_result(default_url: str) -> Dict[str, Any]:
    return {
        "units_managed": "unknown",
        "properties_managed": "unknown",
        "employees_estimate": "unknown",
        "management_type": "unknown",
        "founded_year": "unknown",
        "software_or_portal": "none",
        "metering_provider_mentions": "none",
        "energy_signals": "none",
        "growth_signals": "none",
        "managing_directors": [],
        "other_people": [],
        "generic_emails": [],
        "personal_emails": [],
        "evidence_quotes": {},
        "kpi_source_urls": {}
    }
