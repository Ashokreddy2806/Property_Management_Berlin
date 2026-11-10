import pytest
from src.clean_dedupe import (
    normalize_domain, normalize_phone, extract_berlin_postcode, detect_bezirk,
    repair_company_name, is_valid_company_row, deduplicate_leads
)
from src.agent_contact import (
    normalize_email, is_generic_email, match_person_to_email,
    infer_email_pattern, clean_person_name, is_whitelisted_decision_maker_title,
    validate_linkedin_url
)
from src.agent_enrichment import (
    verify_evidence_in_text, validate_units_managed, clean_text_hygiene
)
from src.scoring import calculate_lead_score

def test_normalize_email():
    # mailto prefix stripping
    assert normalize_email("mailto:info@hv-liebel.de") == "info@hv-liebel.de"
    # Trailing dot stripping
    assert normalize_email("berlin@hachmann-hausverwaltung.de.") == "berlin@hachmann-hausverwaltung.de"
    assert normalize_email("contact@verwaltung.de,") == "contact@verwaltung.de"
    assert normalize_email("<service@domus.de>") == "service@domus.de"
    # Placeholders rejection
    assert normalize_email("email@domain.de") == ""
    assert normalize_email("email@innoflat.de") == ""
    assert normalize_email("name@example.com") == ""
    assert normalize_email("vorname.nachname@ihre-domain.de") == ""
    assert normalize_email("max.mustermann@beispiel.de") == ""
    # Valid emails
    assert normalize_email("mandy.hentschel@vilicus-berlin.de") == "mandy.hentschel@vilicus-berlin.de"
    assert normalize_email("thomas.schmidt@berlin-hv.de") == "thomas.schmidt@berlin-hv.de"

def test_role_mailbox_rejection():
    # Roles that must be flagged as generic
    assert is_generic_email("bewerbung@anton-schmittlein.de") is True
    assert is_generic_email("bewerbungen@immobilien.de") is True
    assert is_generic_email("datenschutz@hausverwaltung.de") is True
    assert is_generic_email("impressum@hv-berlin.de") is True
    assert is_generic_email("rechnung@property.de") is True
    assert is_generic_email("rechnungen@hv.de") is True
    assert is_generic_email("reparatur@wohnen.de") is True
    assert is_generic_email("kundenservice@haus.de") is True
    assert is_generic_email("mieterservice@wohnen.berlin") is True
    assert is_generic_email("zentrale@schmidt-hv.de") is True
    assert is_generic_email("info@verwaltung.de") is True
    assert is_generic_email("post@verwaltung.de") is True
    # Personal emails should not be generic
    assert is_generic_email("markus.schmidt@verwaltung.de") is False
    assert is_generic_email("t.mueller@immobilien-schmidt.de") is False

def test_surname_matching_with_umlauts():
    # Mueller / Müller
    assert match_person_to_email("Karsten Müller", "karsten.mueller@hv-berlin.de") is True
    assert match_person_to_email("Karsten Müller", "k.mueller@hv-berlin.de") is True
    assert match_person_to_email("Karsten Müller", "kmueller@hv-berlin.de") is True
    # Should reject when surname doesn't match
    assert match_person_to_email("Jeanette Grau", "fabian.blume@hv-grau.de") is False
    assert match_person_to_email("Mandy Hentschel", "info@vilicus-berlin.de") is False

def test_infer_email_pattern():
    # Without evidence -> returns None
    assert infer_email_pattern("Markus Schmidt", "unknown-domain.de", []) is None
    assert infer_email_pattern("Markus Schmidt", "unknown-domain.de", ["info@unknown-domain.de"]) is None
    # With evidence of colleague email pattern
    colleagues = ["anna.weber@sample-hv.de", "info@sample-hv.de"]
    inferred = infer_email_pattern("Markus Schmidt", "sample-hv.de", colleagues)
    assert inferred == "markus.schmidt@sample-hv.de"

def test_name_cleaning():
    # Stripping salutations
    assert clean_person_name("Herr Thomas Schmidt")[0] == "Thomas Schmidt"
    assert clean_person_name("Frau Dr. Julia Meyer") == ("Julia Meyer", "Dr.")
    assert clean_person_name("Dipl.-Ing. Markus Weber") == ("Markus Weber", "Dipl.-Ing.")
    # Rejection of company names or digits
    assert clean_person_name("GmbH Verwaltung")[0] is None
    assert clean_person_name("Team Hausverwaltung")[0] is None
    assert clean_person_name("Hauswart 123")[0] is None

def test_title_whitelist_and_blacklist():
    # Whitelisted
    assert is_whitelisted_decision_maker_title("Geschäftsführer") is True
    assert is_whitelisted_decision_maker_title("Inhaber") is True
    assert is_whitelisted_decision_maker_title("Vorstand") is True
    assert is_whitelisted_decision_maker_title("Prokurist") is True
    assert is_whitelisted_decision_maker_title("Leitung Hausverwaltung") is True
    assert is_whitelisted_decision_maker_title("Managing Director") is True
    # Blacklisted
    assert is_whitelisted_decision_maker_title("Fotograf") is False
    assert is_whitelisted_decision_maker_title("Hauswart") is False
    assert is_whitelisted_decision_maker_title("Hausmeister") is False
    assert is_whitelisted_decision_maker_title("Handelsregister B HRB 12345") is False
    assert is_whitelisted_decision_maker_title("Webdesign") is False
    assert is_whitelisted_decision_maker_title("Datenschutzbeauftragter") is False

def test_linkedin_acceptance_rule():
    # Correct case: surname in slug and company in snippet
    valid, note = validate_linkedin_url(
        url="https://de.linkedin.com/in/markus-schmidt-berlin",
        title="Markus Schmidt - Geschäftsführer - Schmidt Hausverwaltung",
        snippet="Markus Schmidt leitet die Schmidt Hausverwaltung in Berlin.",
        surname="Schmidt",
        company="Schmidt Hausverwaltung GmbH",
        domain="schmidt-hv.de"
    )
    assert valid is True

    # Bad case (Jeanette Grau matched to Fabian Blume)
    bad_valid, bad_note = validate_linkedin_url(
        url="https://de.linkedin.com/in/fabian-blume-363226215",
        title="Fabian Blume - Account Manager",
        snippet="Erfahrung bei Hausverwaltung Jeanette Grau",
        surname="Grau",
        company="Hausverwaltung Jeanette Grau",
        domain="hausverwaltung-jeanette-grau.de"
    )
    assert bad_valid is False
    assert "Surname 'Grau' not found in profile slug or SERP title" in bad_note

def test_units_validator():
    # Minimum threshold phrase -> Rejected
    assert validate_units_managed(2, "Wir bieten Verwaltung bereits ab zwei Einheiten an.") is None
    assert validate_units_managed(5, "Verwaltung von WEG ab 5 Einheiten.") is None
    # Association total -> Rejected
    assert validate_units_managed(3500000, "IVD-Mitglieder verwalten bundesweit über 3,5 Millionen Wohnungen.") is None
    # Valid own-portfolio unit counts -> Accepted
    assert validate_units_managed(11500, "Aktuell verwalten wir über 11.500 Einheiten im Raum Berlin.") == 11500
    assert validate_units_managed(10000, "Unser Portfolio umfasst mehr als 10.000+ Einheiten.") == 10000
    assert validate_units_managed(1500, "Wir betreuen 1.000 bis 2.000 Wohneinheiten.") == 1500
    # Over 50k for private firm -> Rejected
    assert validate_units_managed(120000, "Wir verwalten 120.000 Einheiten.") is None

def test_evidence_verification_with_mojibake():
    raw_html_text = "Wir betreuen rund 2.500 Wohneinheiten im Großraum Berlin für unsere Eigentümer."
    quote = "Wir betreuen rund 2.500 Wohneinheiten im Groraum Berlin fr unsere Eigentmer."
    assert verify_evidence_in_text(quote, raw_html_text) is True

def test_berlin_postcode_check():
    # Valid Berlin postcodes (10115 to 14199)
    assert extract_berlin_postcode("Friedrichstraße 123, 10117 Berlin") == "10117"
    assert extract_berlin_postcode("Bölschestraße 77, 12587 Berlin") == "12587"
    assert extract_berlin_postcode("Kudamm 200, 10719 Berlin") == "10719"
    # Non-Berlin postcode (Potsdam, Hamburg, etc.)
    assert extract_berlin_postcode("Hauptstraße 1, 14467 Potsdam") is None
    assert extract_berlin_postcode("Mönckebergstraße 5, 20095 Hamburg") is None

def test_company_name_exclusion_patterns():
    # Associations
    row_ivd = {"company_name": "IVD Berlin-Brandenburg", "normalized_domain": "ivd.net", "website": "https://ivd.net", "address": "Berlin"}
    assert is_valid_company_row(row_ivd)[0] is False
    
    # Generic names
    row_generic = {"company_name": "Sondereigentum", "normalized_domain": "vilicus-berlin.de", "website": "https://vilicus-berlin.de", "address": "10117 Berlin"}
    assert is_valid_company_row(row_generic)[0] is False

    row_comparison = {"company_name": "9 im neutralen Vergleich", "normalized_domain": "vergleichdoch.de", "website": "https://vergleichdoch.de", "address": "10117 Berlin"}
    assert is_valid_company_row(row_comparison)[0] is False

    # Construction
    row_construction = {"company_name": "Anton Schmittlein Construction GmbH", "normalized_domain": "anton-schmittlein.de", "website": "https://anton-schmittlein.de", "address": "10117 Berlin"}
    assert is_valid_company_row(row_construction)[0] is False

def test_scoring_tier_a_rules():
    # Must meet all 5 requirements for Tier A
    qualified_lead = {
        "company_name": "Berliner Hausverwaltung GmbH",
        "segment": "Private Hausverwaltung",
        "units_managed": "2500",
        "management_type": "both",
        "software_or_portal": "Kundenportal, Domus ERP",
        "metering_provider_mentions": "none",
        "energy_signals": "Smart Metering, Funkzähler",
        "growth_signals": "Stellenangebote",
        "contact_name": "Thomas Schmidt",
        "contact_title": "Geschäftsführer",
        "contact_email": "t.schmidt@berlin-hv.de",
        "email_status": "hunter_verified",
        "email_origin": "hunter",
        "website_status": "ok",
        "address": "Friedrichstraße 1, 10117 Berlin",
        "source_count": 3
    }
    scored = calculate_lead_score(qualified_lead)
    assert scored["tier"] == "A"
    assert scored["kpi_fill_rate"] >= 0.5
    assert scored["data_confidence"] == "high"

    # If website is dead or kpi_fill_rate < 0.5 -> Capped at Tier B
    capped_lead = dict(qualified_lead)
    capped_lead["website_status"] = "dead"
    scored_capped = calculate_lead_score(capped_lead)
    assert scored_capped["tier"] == "B"
    assert "Tier A capped to B" in scored_capped["score_caveats"]
