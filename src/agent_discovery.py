import re
import time
from typing import Dict, Any, Tuple
from src.llm import call_llm_json

# Known municipal / mega institutional housing companies in Berlin
MUNICIPAL_OR_MEGA = {
    "gewobag", "degewo", "howoge", "gesobau", "wbm", "stadt und land",
    "vonovia", "deutsche wohnen", "adler group", "adler real estate",
    "berliner stadtbau", "covivio", "heimstaden", "tag immobilien",
    "grand city property", "akelius"
}

# Clear negative keywords in company name or description
EXCLUDED_PATTERNS = [
    r"\breinigung\b", r"\bgebaeudereinigung\b", r"\bgebäudereinigung\b",
    r"\barchitekt\b", r"\barchitekten\b", r"\bmalerbetrieb\b",
    r"\bumzug\b", r"\bumzüge\b", r"\bentruempelung\b",
    r"\brechtsanwalt\b", r"\bnotar\b", r"\bsteuerberater\b",
    r"\bmakler allein\b", r"\breines maklerbuero\b",
    r"\bhotel\b", r"\bhostel\b", r"\bpension\b", r"\bgastronomie\b",
    r"\bconstruction\b", r"\bspezialbau\b", r"\bvisualisierung\b"
]

HV_INDICATORS = [
    "hausverwaltung", "immobilienverwaltung", "weg-verwaltung", "mietverwaltung",
    "hausverwaltungen", "haus- und vermögensverwaltung", "gebäudeverwaltung",
    "grundstücksverwaltung", "sondereigentumsverwaltung", "property management",
    "wohnungsverwaltung", "hausbetreuung", "hausverwaltung-berlin", "hv-berlin"
]

ASSOCIATION_INDICATORS = [
    "ivd", "vdiv", "bfw", "ddiv", "haus & grund", "mieterverein", "mieterbund", "ihk", "verband"
]

_CLASSIFICATION_FAILURES = 0

def get_classification_failure_count() -> int:
    global _CLASSIFICATION_FAILURES
    return _CLASSIFICATION_FAILURES

def rule_based_classify(name: str, snippet: str = "", website: str = "") -> Tuple[str, str]:
    name_lower = name.lower()
    snip_lower = snippet.lower()
    web_lower = website.lower()
    combined = f"{name_lower} {snip_lower} {web_lower}"

    # 1. Check associations / directories
    for assoc in ASSOCIATION_INDICATORS:
        if assoc in name_lower or assoc in web_lower:
            return "Other/not a Hausverwaltung", f"Industry association or public body: {assoc}"

    # 2. Check municipal / mega housing companies
    for m in MUNICIPAL_OR_MEGA:
        if m in name_lower or m in web_lower:
            return "Municipal/Large housing company", f"Recognized municipal or institutional housing company: {m}"

    # 3. Check non-HV excluded services
    for pat in EXCLUDED_PATTERNS:
        if re.search(pat, name_lower) or re.search(pat, snip_lower):
            return "Other/not a Hausverwaltung", f"Identified non-property-management service ({pat})"

    # 4. Check if pure broker without management
    if "makler" in name_lower and not any(ind in combined for ind in ["verwaltung", "management", "weg", "miet"]):
        return "Other/not a Hausverwaltung", "Real estate broker without property management service"

    # 5. Check clear property management indicators
    for ind in HV_INDICATORS:
        if ind in name_lower or ind in web_lower:
            return "Private Hausverwaltung", f"Direct property management indicator in name/website: {ind}"
        if ind in snip_lower and not any(re.search(pat, name_lower) for pat in EXCLUDED_PATTERNS):
            return "Private Hausverwaltung", f"Property management service identified in snippet: {ind}"

    return "AMBIGUOUS", ""

def classify_company_discovery(name: str, snippet: str = "", website: str = "") -> Dict[str, str]:
    global _CLASSIFICATION_FAILURES
    fast_seg, fast_reason = rule_based_classify(name, snippet, website)
    if fast_seg != "AMBIGUOUS":
        return {"segment": fast_seg, "reason": fast_reason}

    prompt = f"""You are an expert German real estate analyst evaluating B2B leads for Heidi Systems, an Energy OS and submetering provider for property managers (Hausverwaltungen) in Berlin.

STRICT RULE:
An entity MUST be classified as "Private Hausverwaltung" ONLY if the entity ITSELF directly offers active property management services (WEG-Verwaltung, Mietverwaltung, or Sondereigentumsverwaltung) in Berlin.

NEGATIVE EXAMPLES (DO NOT classify as Private Hausverwaltung):
- Associations & federations (IVD, VDIV, BFW, DDIV, Haus & Grund, Mieterverein, Verband) -> "Other/not a Hausverwaltung"
- Directory or comparison articles ("Top 10 Hausverwaltungen", "Vergleich", "Ratgeber", "Kosten") -> "Other/not a Hausverwaltung"
- Pure real estate brokers (Immobilienmakler only, sales/rentals without administration) -> "Other/not a Hausverwaltung"
- Construction, renovation, architects, cleaning, crafts firms (e.g. Anton Schmittlein Construction GmbH) -> "Other/not a Hausverwaltung"
- Facility management / cleaning only without commercial/legal WEG/Miet management -> "Other/not a Hausverwaltung"
- Municipal or giant listed housing corporations (degewo, gewobag, HOWOGE, GESOBAU, WBM, Stadt und Land, Vonovia) -> "Municipal/Large housing company"

Entity to classify:
- Name: {name}
- Website: {website}
- Snippet: {snippet}

Return valid JSON with exactly two fields:
{{
  "segment": "Private Hausverwaltung" | "Municipal/Large housing company" | "Other/not a Hausverwaltung",
  "reason": "Clear explanation justifying the classification"
}}"""

    # Retry up to 3 times with exponential backoff on failure (Section 1.4)
    for attempt in range(3):
        try:
            res = call_llm_json(prompt, stage="discovery_agent1")
            seg = res.get("segment")
            if seg in ["Private Hausverwaltung", "Municipal/Large housing company", "Other/not a Hausverwaltung"]:
                return {"segment": seg, "reason": res.get("reason", "LLM classified")}
        except Exception:
            time.sleep(1.5 * (attempt + 1))

    # On failure: NEVER default to Private Hausverwaltung!
    _CLASSIFICATION_FAILURES += 1
    return {
        "segment": "needs_review",
        "reason": "classification_failed"
    }
