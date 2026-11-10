import json
import logging
import re
import time
import urllib.parse
from typing import Dict, Any, Optional, Tuple, List
import dns.resolver
import requests
from config import (
    HUNTER_API_KEY, SERPER_API_KEY, REQUEST_TIMEOUT,
    DECISION_MAKER_TITLES_WHITELIST, VALID_EMAIL_STATUSES
)
import ftfy
from src.cache import get_cached_http, set_cached_http

logger = logging.getLogger(__name__)

# Quota management for Hunter
_HUNTER_FINDER_CALLS = 0
_HUNTER_VERIFIER_CALLS = 0
MAX_HUNTER_CALLS = 40  # Respect free tier limit

EMAIL_STRICT_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Extended generic / role-based mailboxes (Section 2.3)
GENERIC_EMAIL_PREFIXES = {
    "info", "kontakt", "contact", "office", "mail", "post", "service", "hallo",
    "anfrage", "anfragen", "buero", "büro", "verwaltung", "hausverwaltung", "hv",
    "zentrale", "empfang", "sekretariat", "support", "team", "datenschutz",
    "impressum", "bewerbung", "bewerbungen", "jobs", "karriere", "presse",
    "marketing", "vertrieb", "verkauf", "vermietung", "neuvermietung", "mieter",
    "mieterservice", "kundenservice", "kundenbetreuung", "buchhaltung", "rechnung",
    "rechnungen", "abrechnung", "technik", "schaden", "reparatur", "notdienst",
    "webmaster", "admin", "noreply", "no-reply", "zentral", "kundencenter",
    "hotline", "immobilien", "zentralbuero"
}

PLACEHOLDER_LOCAL_PARTS = {
    "email", "name", "vorname.nachname", "vorname", "nachname", "user",
    "max.mustermann", "mustermann", "email1", "email2", "your-email",
    "ihre-email", "test", "sample", "example", "mail"
}

PLACEHOLDER_DOMAINS = {
    "domain.de", "domain.com", "example.com", "example.de", "example.org",
    "beispiel.de", "beispiel.com", "ihre-domain.de", "ihre-domain.com",
    "ihredomain.de", "your-domain.com"
}

# Whitelist of decision-maker title stems (Section 3.2)
TITLE_WHITELIST = [
    "geschäftsführer", "geschaeftsfuehrer", "inhaber", "gesellschafter",
    "vorstand", "prokurist", "leiter", "leitung", "bereichsleiter",
    "abteilungsleiter", "head of", "managing director", "ceo", "geschäftsführung",
    "geschaeftsfuehrung"
]

# Blacklisted titles to strictly reject (Section 3.2)
TITLE_BLACKLIST = [
    "fotograf", "hauswart", "hausmeister", "handelsregister", "hrb", "e.k.",
    "datenschutzbeauftragter", "webdesign", "bildnachweis", "vorsitzender",
    "rechtsanwalt", "notar", "steuerberater", "architekt", "bauleiter",
    "assistenz", "praktikant", "werkstudent", "azubi", "sachbearbeiter"
]

def transliterate_german(text: str) -> str:
    """Replaces German umlauts and ß with standard ASCII equivalents."""
    mapping = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text

def normalize_email(email: Optional[str]) -> str:
    """
    Section 2.2: Cleans, unescapes and strictly normalizes an email address.
    Rejects malformed, trailing punctuation, and placeholder addresses.
    """
    if not email or not isinstance(email, str):
        return ""
    em = email.strip()
    if em.lower().startswith("mailto:"):
        em = em[7:].strip()
    em = urllib.parse.unquote(em).strip()
    em = em.strip("<>.,;)\"]'\\/ ")
    em = em.lower()

    if not em or "@" not in em:
        return ""

    parts = em.split("@")
    if len(parts) != 2:
        return ""
    local_part, domain_part = parts[0], parts[1]

    # Check placeholder local parts or domains
    if local_part in PLACEHOLDER_LOCAL_PARTS or domain_part in PLACEHOLDER_DOMAINS:
        return ""
    if any(local_part.startswith(f"{p}.") or local_part == p for p in PLACEHOLDER_LOCAL_PARTS):
        return ""
    if local_part.startswith(".") or local_part.endswith("."):
        return ""
    if "." not in domain_part or domain_part.startswith(".") or domain_part.endswith("."):
        return ""

    if not EMAIL_STRICT_REGEX.match(em):
        return ""

    return em

def is_generic_email(email: str) -> bool:
    """Section 2.3: Returns True if the email is a role-based / generic mailbox."""
    clean = normalize_email(email)
    if not clean:
        return True
    prefix = clean.split("@")[0].lower()
    for g in GENERIC_EMAIL_PREFIXES:
        if prefix == g or prefix.startswith(f"{g}.") or prefix.startswith(f"{g}-") or prefix.startswith(f"{g}_"):
            return True
        if prefix.endswith(f".{g}") or prefix.endswith(f"-{g}") or prefix.endswith(f"_{g}"):
            return True
    return False

def check_dns_mx(domain: str) -> bool:
    """Checks if a domain has valid DNS MX records."""
    if not domain or "." not in domain:
        return False
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=4)
        return len(answers) > 0
    except Exception:
        return False

def clean_person_name(raw_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Section 3.1: Strips salutations and academic titles from person names.
    Valid person name must have 2 to 4 tokens, no digits, no company words.
    Returns (cleaned_name, academic_title).
    """
    if not raw_name or not isinstance(raw_name, str):
        return None, None
    s = raw_name.strip()
    if s.lower() in ["unknown", "none", "n/a", "-"]:
        return None, None

    # Strip company words
    company_words = ["gmbh", "ug", "ag", "e.k.", "verwaltung", "immobilien", "hausverwaltung", "team", "service", "gruppe"]
    if any(re.search(rf"\b{re.escape(w)}\b", s, re.I) for w in company_words):
        return None, None
    if re.search(r"\d", s):
        return None, None

    # Salutations (stripped first)
    gender_salutations = ["Herrn ", "Herr ", "Frau ", "Hr. ", "Fr. "]
    for sal in gender_salutations:
        if s.startswith(sal):
            s = s[len(sal):].strip()
            break

    # Academic titles (stripped next and captured)
    academic_titles = [
        ("Prof. Dr. ", "Prof. Dr."), ("Dr. jur. ", "Dr. jur."), ("Dr. med. ", "Dr. med."),
        ("Dr.-Ing. ", "Dr.-Ing."), ("Dr. ", "Dr."), ("Prof. ", "Prof."),
        ("Dipl.-Ing. ", "Dipl.-Ing."), ("Dipl.-Kfm. ", "Dipl.-Kfm."), ("Dipl.-Oec. ", "Dipl.-Oec."),
        ("Dipl.-Kaufmann ", "Dipl.-Kaufmann"), ("Dipl.-Betriebswirt ", "Dipl.-Betriebswirt"),
        ("Dipl.-Volkswirt ", "Dipl.-Volkswirt"), ("Dipl.-Wirt.-Ing. ", "Dipl.-Wirt.-Ing.")
    ]

    academic_title = None
    for tit, ac in academic_titles:
        if s.startswith(tit):
            s = s[len(tit):].strip()
            academic_title = ac
            break

    # Re-check tokens: must have 2 to 4 tokens
    tokens = s.split()
    if len(tokens) < 2 or len(tokens) > 4:
        return None, None

    # Each token must look like a capitalized name
    if not all(len(t) >= 2 and (t[0].isupper() or t.lower() in ["von", "van", "de", "der", "den", "zu"]) for t in tokens):
        return None, None

    return s, academic_title

def is_whitelisted_decision_maker_title(title: Optional[str]) -> bool:
    """Section 3.2 & Problem 4: Returns True if the title matches a whitelisted decision maker."""
    if not title or not isinstance(title, str):
        return False
    t_lower = title.strip().lower()

    # Reject blacklisted
    if any(b in t_lower for b in TITLE_BLACKLIST):
        return False

    # Check strict whitelist from config
    return any(w in t_lower for w in DECISION_MAKER_TITLES_WHITELIST)

def match_person_to_email(full_name: str, email: str) -> bool:
    """
    Section 2.4: Verifies whether the email local part matches the person's surname
    (or first-initial + surname) with German transliteration.
    """
    clean_em = normalize_email(email)
    if not clean_em or is_generic_email(clean_em):
        return False
    if not full_name:
        return False

    parts = full_name.strip().split()
    if len(parts) < 2:
        return False

    first_name = parts[0].lower()
    surname = parts[-1].lower()

    # Candidate surnames (original, transliterated, simplified vowel)
    surname_variants = {
        surname,
        transliterate_german(surname),
        surname.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "s")
    }

    local_part = clean_em.split("@")[0].lower()
    first_initial = first_name[0] if first_name else ""

    for s_var in surname_variants:
        if len(s_var) < 3:
            continue
        # Direct surname match
        if s_var in local_part:
            return True
        # First initial + surname (e.g. tmueller, t.mueller, t-mueller)
        if first_initial and f"{first_initial}.{s_var}" in local_part:
            return True
        if first_initial and f"{first_initial}{s_var}" in local_part:
            return True
        if first_initial and f"{first_initial}_{s_var}" in local_part:
            return True
        if first_initial and f"{first_initial}-{s_var}" in local_part:
            return True

    return False

def select_best_decision_maker(enrichment_data: Dict[str, Any], default_url: str, crawled_text: str = "") -> Tuple[Optional[str], Optional[str], Optional[str], str, Optional[str]]:
    """
    Section 3.3: Decision Maker Selection with strict title whitelist and verbatim check.
    Returns (contact_name, contact_title, contact_source_url, contact_confidence, academic_title).
    """
    text_lower = crawled_text.lower() if crawled_text else ""

    # Priority 1: Managing Directors / Inhaber from Impressum
    mds = enrichment_data.get("managing_directors", [])
    for md in mds:
        raw_name = md.get("name")
        c_name, ac_title = clean_person_name(raw_name)
        if c_name:
            # Verbatim text check
            if not text_lower or c_name.lower() in text_lower:
                t = md.get("title", "Geschäftsführer")
                if is_whitelisted_decision_maker_title(t):
                    src = md.get("source_url") or default_url
                    return c_name, t, src, "high", ac_title

    # Priority 2: Leitung / Prokurist / Bereichsleitung
    others = enrichment_data.get("other_people", [])
    for p in others:
        raw_name = p.get("name")
        c_name, ac_title = clean_person_name(raw_name)
        if c_name:
            if not text_lower or c_name.lower() in text_lower:
                t = p.get("title", "")
                if is_whitelisted_decision_maker_title(t):
                    src = p.get("source_url") or default_url
                    return c_name, t, src, "high", ac_title

    # Priority 3: Candidate without whitelisted title -> kept with low confidence, title 'unknown'
    for p in mds + others:
        raw_name = p.get("name")
        c_name, ac_title = clean_person_name(raw_name)
        if c_name:
            if not text_lower or c_name.lower() in text_lower:
                src = p.get("source_url") or default_url
                return c_name, "unknown", src, "low", ac_title

    return None, None, None, "none", None

def infer_email_pattern(name: str, domain: str, existing_personal_emails: List[str]) -> Optional[str]:
    """
    Section 2.1: Returns pattern-inferred email ONLY if at least one real personal
    email on the same domain reveals a pattern (first.last, f.last, firstlast, last, etc.).
    If no evidence, returns None.
    """
    if not name or not domain or not existing_personal_emails:
        return None

    parts = name.strip().lower().split()
    if len(parts) < 2:
        return None

    first = transliterate_german(re.sub(r"[^a-zäöüß]", "", parts[0]))
    last = transliterate_german(re.sub(r"[^a-zäöüß]", "", parts[-1]))
    if not first or not last:
        return None

    # Detect pattern from existing real personal emails
    for em in existing_personal_emails:
        clean_em = normalize_email(em)
        if not clean_em or is_generic_email(clean_em):
            continue
        em_domain = clean_em.split("@")[-1].lower()
        if em_domain != domain.lower():
            continue

        prefix = clean_em.split("@")[0].lower()
        # Pattern 1: first.last
        if "." in prefix:
            p_parts = prefix.split(".")
            if len(p_parts) == 2:
                if len(p_parts[0]) == 1:
                    return f"{first[0]}.{last}@{domain}"
                else:
                    return f"{first}.{last}@{domain}"
        # Pattern 2: first_last
        elif "_" in prefix:
            return f"{first}_{last}@{domain}"
        # Pattern 3: f-last or first-last
        elif "-" in prefix:
            p_parts = prefix.split("-")
            if len(p_parts) == 2 and len(p_parts[0]) == 1:
                return f"{first[0]}-{last}@{domain}"
            return f"{first}-{last}@{domain}"

    return None

def guess_email_fallback(name: str, domain: str) -> Optional[str]:
    """Fallback guess stored ONLY in guessed_email (never in contact_email)."""
    if not name or not domain:
        return None
    parts = name.strip().lower().split()
    if len(parts) < 2:
        return None
    first = transliterate_german(re.sub(r"[^a-zäöüß]", "", parts[0]))
    last = transliterate_german(re.sub(r"[^a-zäöüß]", "", parts[-1]))
    if first and last:
        return f"{first}.{last}@{domain}"
    return None

def hunter_verify_email(email: str) -> Tuple[str, Optional[dict]]:
    """
    Section 2.5: Verifies email with Hunter's email-verifier endpoint.
    Returns status in {'hunter_verified', 'hunter_accept_all', 'invalid'} and raw payload.
    """
    global _HUNTER_VERIFIER_CALLS
    if not HUNTER_API_KEY or _HUNTER_VERIFIER_CALLS >= MAX_HUNTER_CALLS or not email:
        return "mx_ok_unverified", None

    url = f"https://api.hunter.io/v2/email-verifier?email={email}&api_key={HUNTER_API_KEY}"
    cached = get_cached_http(url)
    if cached:
        data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
    else:
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            _HUNTER_VERIFIER_CALLS += 1
            if resp.status_code == 200:
                data = resp.json()
                set_cached_http(url, resp.status_code, resp.text)
            elif resp.status_code == 429:
                return "mx_ok_unverified", None
            else:
                return "invalid", None
        except Exception:
            return "mx_ok_unverified", None

    result = data.get("data", {}).get("result")
    status = data.get("data", {}).get("status")
    if result == "deliverable" or status == "valid":
        return "hunter_verified", data
    elif result == "risky" or status == "accept_all":
        return "hunter_accept_all", data
    elif result == "undeliverable" or status == "invalid":
        return "invalid", data
    return "mx_ok_unverified", data

def hunter_find_email(first_name: str, last_name: str, domain: str) -> Optional[Dict[str, Any]]:
    """Section 2.5: Calls Hunter Email Finder respecting quota."""
    global _HUNTER_FINDER_CALLS
    if not HUNTER_API_KEY or _HUNTER_FINDER_CALLS >= MAX_HUNTER_CALLS or not domain:
        return None

    fn = transliterate_german(first_name)
    ln = transliterate_german(last_name)
    url = f"https://api.hunter.io/v2/email-finder?domain={domain}&first_name={fn}&last_name={ln}&api_key={HUNTER_API_KEY}"
    cached = get_cached_http(url)
    if cached:
        return json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        _HUNTER_FINDER_CALLS += 1
        if resp.status_code == 200:
            data = resp.json()
            set_cached_http(url, resp.status_code, resp.text)
            return data
    except Exception:
        return None
    return None

def validate_linkedin_url(url: str, title: str, snippet: str, surname: str, company: str, domain: str) -> Tuple[bool, str]:
    """
    Section 3.4: Re-validates LinkedIn matches according to the strict rule:
    (a) URL is linkedin.com/in/...
    (b) Profile slug OR result title contains person's surname
    (c) Title/snippet contains company name or domain.
    """
    if not url or "linkedin.com/in/" not in url:
        return False, "Not a personal LinkedIn profile URL"

    slug = url.split("linkedin.com/in/")[-1].strip("/").lower()
    t_lower = title.lower()
    s_lower = snippet.lower()
    combined_serp = f"{t_lower} {s_lower}"

    surname_lower = surname.lower()
    surname_trans = transliterate_german(surname_lower)

    # Condition (b): profile slug OR title contains surname
    surname_in_slug = (surname_lower in slug) or (surname_trans in slug)
    surname_in_title = (surname_lower in t_lower) or (surname_trans in t_lower)
    if not (surname_in_slug or surname_in_title):
        return False, f"Surname '{surname}' not found in profile slug or SERP title"

    # Condition (c): title or snippet contains company or domain
    clean_comp = re.sub(r"\b(gmbh & co\. kg|gmbh|ug|ag|e\.k\.|gbr|kg|hausverwaltung|verwaltung)\b", "", company, flags=re.I).strip().lower()
    comp_match = (clean_comp and len(clean_comp) >= 3 and clean_comp in combined_serp)
    dom_match = (domain and len(domain) >= 4 and domain.lower() in combined_serp)
    if not (comp_match or dom_match):
        return False, f"Company '{clean_comp}' or domain '{domain}' not found in SERP snippet"

    return True, f"Verified: surname '{surname}' and company/domain matched in SERP metadata"

def search_linkedin_serper(name: str, company_name: str, domain: str) -> Tuple[str, str]:
    """Searches Serper for a LinkedIn profile and validates strictly with Section 3.4."""
    if not SERPER_API_KEY or not name:
        return "", ""

    parts = name.strip().split()
    if len(parts) < 2:
        return "", ""
    surname = parts[-1]

    clean_company = re.sub(r"\b(gmbh|ag|kg|ug|haftungsbeschränkt|e\.k\.|co\.)\b", "", company_name, flags=re.I).strip()
    query = f'"{name}" "{clean_company}" site:linkedin.com/in'
    url = "https://google.serper.dev/search"
    payload = {"q": query, "num": 3, "gl": "de", "hl": "de"}

    cached = get_cached_http(url, json_body=payload)
    if cached:
        data = json.loads(cached["text"]) if isinstance(cached["text"], str) else cached["text"]
    else:
        try:
            resp = requests.post(
                url,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                set_cached_http(url, resp.status_code, resp.text, json_body=payload)
            else:
                return "", ""
        except Exception:
            return "", ""

    for org in data.get("organic", []):
        link = org.get("link", "")
        title = org.get("title", "")
        snippet = org.get("snippet", "")
        is_valid, note = validate_linkedin_url(link, title, snippet, surname, clean_company, domain)
        if is_valid:
            return link, note

    return "", ""

def resolve_contact_for_lead(lead: Dict[str, Any], enrichment_data: Dict[str, Any], verify_hunter: bool = False, crawled_text: str = "") -> Dict[str, Any]:
    """
    Section 2 & 3: Resolves decision maker, on-site matching email, pattern inference,
    guessed fallback, and LinkedIn profile.
    """
    domain = lead.get("normalized_domain", "")
    default_url = lead.get("website", "")

    # 1. Select decision maker
    c_name, c_title, c_src, c_conf, ac_title = select_best_decision_maker(enrichment_data, default_url, crawled_text)
    lead["contact_name"] = c_name or "unknown"
    lead["contact_title"] = c_title or "unknown"
    lead["academic_title"] = ac_title or ""
    lead["contact_confidence"] = c_conf
    lead["contact_source_url"] = c_src or default_url

    # 2. LinkedIn Search & Strict Re-validation
    existing_linkedin = lead.get("linkedin_url", "")
    parts = c_name.split() if c_name and c_name != "unknown" else []
    surname = parts[-1] if parts else ""

    if existing_linkedin and surname:
        valid, note = validate_linkedin_url(existing_linkedin, "", lead.get("snippet", ""), surname, lead.get("company_name", ""), domain)
        if valid:
            lead["linkedin_url"] = existing_linkedin
            lead["linkedin_match_note"] = note
        else:
            # Query Serper
            l_url, l_note = search_linkedin_serper(c_name, lead.get("company_name", ""), domain)
            lead["linkedin_url"] = l_url
            lead["linkedin_match_note"] = l_note
    elif c_name and c_name != "unknown":
        l_url, l_note = search_linkedin_serper(c_name, lead.get("company_name", ""), domain)
        lead["linkedin_url"] = l_url
        lead["linkedin_match_note"] = l_note
    else:
        lead["linkedin_url"] = ""
        lead["linkedin_match_note"] = ""

    # 3. Email processing
    raw_personal = enrichment_data.get("personal_emails", [])
    raw_generic = enrichment_data.get("generic_emails", [])

    # Clean all found emails
    clean_personal = [normalize_email(e) for e in raw_personal if normalize_email(e) and not is_generic_email(e)]
    clean_generic = [normalize_email(e) for e in raw_generic if normalize_email(e) and is_generic_email(e)]

    # Populate generic_email column
    if clean_generic:
        lead["generic_email"] = clean_generic[0]
    elif domain:
        lead["generic_email"] = f"info@{domain}"
    else:
        lead["generic_email"] = "unknown"

    contact_email = ""
    email_origin = "none"
    email_status = "unverified"
    guessed_email = ""

    # Option A: On-site email matching person's surname
    if c_name and c_name != "unknown" and clean_personal:
        for em in clean_personal:
            if match_person_to_email(c_name, em):
                contact_email = em
                email_origin = "found_on_site"
                mail_dom = em.split("@")[-1]
                email_status = "mx_ok_unverified" if check_dns_mx(mail_dom) else "invalid"
                break

    # Option B: Hunter Email Finder
    if not contact_email and c_name and c_name != "unknown" and domain:
        hunter_data = hunter_find_email(parts[0], surname, domain)
        if hunter_data and hunter_data.get("data", {}).get("email"):
            h_email = normalize_email(hunter_data["data"]["email"])
            if h_email and not is_generic_email(h_email):
                contact_email = h_email
                email_origin = "hunter"
                email_status = "mx_ok_unverified" if check_dns_mx(domain) else "invalid"

    # Option C: Pattern Inferred from real personal emails on the domain
    if not contact_email and c_name and c_name != "unknown" and domain:
        pattern_email = infer_email_pattern(c_name, domain, clean_personal)
        if pattern_email:
            contact_email = normalize_email(pattern_email)
            email_origin = "pattern_inferred_from_evidence"
            email_status = "mx_ok_unverified" if check_dns_mx(domain) else "invalid"

    # Option D: Guessed email (NEVER in contact_email, stored ONLY in guessed_email!)
    if not contact_email and c_name and c_name != "unknown" and domain:
        guessed_email = guess_email_fallback(c_name, domain) or ""

    # Top 40 verification via Hunter Verifier (Section 2.5)
    if verify_hunter and contact_email and contact_email != "unknown" and email_status != "invalid":
        h_status, _ = hunter_verify_email(contact_email)
        if h_status in ["hunter_verified", "hunter_accept_all", "invalid"]:
            email_status = h_status

    if not contact_email or contact_email == "unknown":
        contact_email = "unknown"
        email_status = "none"
        email_origin = "none"
    else:
        if email_status not in VALID_EMAIL_STATUSES:
            email_status = "mx_ok_unverified"

    lead["contact_email"] = contact_email
    lead["email_origin"] = email_origin
    lead["email_status"] = email_status
    lead["guessed_email"] = guessed_email

    # Clean text hygiene on contact strings
    if lead.get("contact_name"):
        lead["contact_name"] = ftfy.fix_text(lead["contact_name"])
    if lead.get("contact_title"):
        lead["contact_title"] = ftfy.fix_text(lead["contact_title"])

    return lead
