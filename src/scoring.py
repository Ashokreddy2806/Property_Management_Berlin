import re
from typing import Dict, Any, Tuple
from config import SCORING_WEIGHTS, TIER_THRESHOLDS

def parse_units_count(units_val: Any) -> int:
    """Parses units string or integer into an approximate number. Returns -1 if unknown."""
    if units_val is None:
        return -1
    s = str(units_val).strip().lower()
    if not s or s in ["unknown", "none", "null"]:
        return -1
    
    s = s.replace(".", "").replace(",", "")
    numbers = [int(n) for n in re.findall(r"\b\d+\b", s)]
    if not numbers:
        return -1
    if len(numbers) >= 2:
        return int(sum(numbers) / len(numbers))
    return numbers[0]

def calculate_lead_score(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Section 5: Calculates lead score (0-100), kpi_fill_rate, tier (A/B/C or Strategic),
    score_reason, score_caveats, and data_confidence.
    """
    segment = lead.get("segment", "Private Hausverwaltung")

    # Section 1.6 & Problem 3: Large / Municipal housing companies and Cooperatives get tier "Strategic"
    if segment in ["Large housing company", "Housing cooperative"]:
        lead["lead_score"] = 100
        lead["tier"] = "Strategic"
        lead["kpi_fill_rate"] = 1.0
        lead["score_reason"] = f"{segment} (Strategic Account)"
        lead["score_caveats"] = "Strategic institutional account; handled via specialized enterprise sales"
        lead["data_confidence"] = "high"
        return lead

    score = 0
    reasons = []
    caveats = []

    # 1. Portfolio size (max 30)
    units_num = parse_units_count(lead.get("units_managed"))
    if units_num >= 2000:
        pts = SCORING_WEIGHTS["portfolio_size"]["ge_2000"]
        reasons.append(f"Large portfolio (>={units_num} units, +{pts})")
    elif units_num >= 500:
        pts = SCORING_WEIGHTS["portfolio_size"]["500_to_1999"]
        reasons.append(f"Mid-large portfolio ({units_num} units, +{pts})")
    elif units_num >= 100:
        pts = SCORING_WEIGHTS["portfolio_size"]["100_to_499"]
        reasons.append(f"Mid-size portfolio ({units_num} units, +{pts})")
    elif units_num > 0:
        pts = SCORING_WEIGHTS["portfolio_size"]["lt_100"]
        reasons.append(f"Boutique portfolio ({units_num} units, +{pts})")
    else:
        pts = SCORING_WEIGHTS["portfolio_size"]["unknown"]
        reasons.append(f"Portfolio size undisclosed (+{pts})")
        caveats.append("units unknown, estimate only")
    score += pts

    # 2. Management type (max 10)
    mtype = str(lead.get("management_type", "unknown")).lower()
    if "both" in mtype or ("miet" in mtype and "weg" in mtype):
        pts = SCORING_WEIGHTS["management_type"]["both"]
        reasons.append(f"Both WEG & Mietverwaltung (+{pts})")
    elif "weg" in mtype or "miet" in mtype:
        pts = SCORING_WEIGHTS["management_type"]["single"]
        reasons.append(f"Specialized {lead.get('management_type')} (+{pts})")
    else:
        pts = SCORING_WEIGHTS["management_type"]["unknown"]
    score += pts

    # 3. Digital maturity (max 15)
    sw = str(lead.get("software_or_portal", "none")).lower()
    has_portal = any(p in sw for p in ["portal", "mieter-app", "app"])
    has_software = any(s in sw for s in ["aareon", "haufe", "casavi", "domus", "immoware", "weg-manager", "karthago", "ix-haus", "win-casa", "realestate"])
    if has_portal and has_software:
        pts = SCORING_WEIGHTS["digital_maturity"]["portal_and_software"]
        reasons.append(f"High digital maturity (portal & ERP, +{pts})")
    elif has_portal or has_software:
        pts = SCORING_WEIGHTS["digital_maturity"]["one_of_them"]
        reasons.append(f"Digitalized operations (+{pts})")
    elif sw in ["none", "unknown"]:
        pts = SCORING_WEIGHTS["digital_maturity"]["unknown"]
    else:
        pts = SCORING_WEIGHTS["digital_maturity"]["none"]
    score += pts

    # 4. Current metering provider signal (max 10)
    mp = str(lead.get("metering_provider_mentions", "none")).lower()
    if mp in ["none", "unknown", ""]:
        pts = SCORING_WEIGHTS["metering_provider"]["none_mentioned"]
        reasons.append(f"Unattached metering prospect (+{pts})")
    elif "in-house" in mp or "eigen" in mp:
        pts = SCORING_WEIGHTS["metering_provider"]["in_house"]
        reasons.append(f"In-house metering operations (+{pts})")
    else:
        pts = SCORING_WEIGHTS["metering_provider"]["competitor"]
        reasons.append(f"Competitor mentioned ({lead.get('metering_provider_mentions')}, +{pts})")
    score += pts

    # 5. Energy/metering signals (max 15)
    es = str(lead.get("energy_signals", "none")).lower()
    strong_terms = ["smart metering", "funkzähler", "fernablesung", "heizkostenverordnung", "lorawan", "m-bus", "submetering"]
    if any(t in es for t in strong_terms):
        pts = SCORING_WEIGHTS["energy_signals"]["strong"]
        reasons.append(f"Strong smart-metering signals (+{pts})")
    elif es not in ["none", "unknown", ""]:
        pts = SCORING_WEIGHTS["energy_signals"]["weak"]
        reasons.append(f"General energy awareness (+{pts})")
    else:
        pts = SCORING_WEIGHTS["energy_signals"]["none"]
    score += pts

    # 6. Growth signals (max 5)
    gs = str(lead.get("growth_signals", "none")).lower()
    if gs not in ["none", "unknown", ""]:
        pts = SCORING_WEIGHTS["growth_signals"]["present"]
        reasons.append(f"Active hiring/expansion (+{pts})")
    else:
        pts = SCORING_WEIGHTS["growth_signals"]["none"]
    score += pts

    # 7. Contactability (max 15) (Section 5.2)
    contact_name = lead.get("contact_name")
    contact_title = lead.get("contact_title")
    contact_email = lead.get("contact_email")
    email_status = lead.get("email_status", "unverified")
    email_origin = lead.get("email_origin", "none")

    has_whitelisted_title = contact_title and contact_title != "unknown"
    has_name = contact_name and contact_name != "unknown"
    has_real_email = contact_email and contact_email != "unknown" and email_origin != "guessed"

    if has_name and has_whitelisted_title and has_real_email and email_status in ["hunter_verified", "found_on_site"]:
        pts = SCORING_WEIGHTS["contactability"]["named_decision_maker_verified_email"]
        reasons.append(f"Decision maker with verified email (+{pts})")
    elif has_name and has_whitelisted_title and has_real_email and email_status in ["mx_ok_unverified", "hunter_accept_all"]:
        pts = SCORING_WEIGHTS["contactability"]["named_title_unverified_email"]
        reasons.append(f"Decision maker with personal email (+{pts})")
    elif has_name:
        pts = SCORING_WEIGHTS["contactability"]["name_only"]
        reasons.append(f"Named decision maker (+{pts})")
    else:
        pts = SCORING_WEIGHTS["contactability"]["none"]
    score += pts

    # Clamp 0-100
    final_score = min(100, max(0, score))

    # Section 5.1: KPI fill rate = share of the 7 KPI fields that are not 'unknown'
    kpi_fields = [
        lead.get("units_managed"),
        lead.get("management_type"),
        lead.get("software_or_portal"),
        lead.get("metering_provider_mentions"),
        lead.get("energy_signals"),
        lead.get("growth_signals"),
        contact_name
    ]
    known_kpi_count = sum(1 for v in kpi_fields if v not in [None, "", "unknown", "none"])
    kpi_fill_rate = round(known_kpi_count / 7.0, 2)

    # Section 5.3: Tier Assignment with strict capping
    web_stat = lead.get("website_status", "none")
    addr = str(lead.get("address", ""))
    berlin_plz_match = re.search(r"\b(1[0-4]\d{3})\b", addr)
    berlin_ok = bool(berlin_plz_match and 10115 <= int(berlin_plz_match.group(1)) <= 14199)

    tier = "C"
    if final_score >= TIER_THRESHOLDS["A"]:
        # Tier A requires ALL 5 conditions
        cond_score = (final_score >= 70)
        cond_fill = (kpi_fill_rate >= 0.5)
        cond_web = (web_stat == "ok")
        cond_plz = berlin_ok
        cond_seg = (segment == "Private Hausverwaltung")

        if cond_score and cond_fill and cond_web and cond_plz and cond_seg:
            tier = "A"
        else:
            tier = "B"
            failed_conds = []
            if not cond_fill:
                failed_conds.append("kpi_fill_rate < 0.5")
            if not cond_web:
                failed_conds.append(f"website_status={web_stat}")
            if not cond_plz:
                failed_conds.append("Berlin postcode unverified")
            caveats.append(f"Tier A capped to B: {', '.join(failed_conds)}")
    elif final_score >= TIER_THRESHOLDS["B"]:
        tier = "B"
    else:
        tier = "C"

    # Section 5.4: Data confidence
    try:
        src_cnt = int(lead.get("source_count", 1) or 1)
    except (ValueError, TypeError):
        src_cnt = 1

    if web_stat in ["ok", "redirected"] and src_cnt >= 2 and kpi_fill_rate >= 0.5:
        confidence = "high"
    elif web_stat in ["ok", "redirected"] and kpi_fill_rate >= 0.25:
        confidence = "medium"
    else:
        confidence = "low"

    lead["lead_score"] = final_score
    lead["kpi_fill_rate"] = kpi_fill_rate
    lead["tier"] = tier
    lead["score_reason"] = "; ".join(reasons[:4])
    lead["score_caveats"] = "; ".join(caveats) if caveats else "None"
    lead["data_confidence"] = confidence

    return lead
