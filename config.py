import os
from pathlib import Path
import dotenv

# Load .env file
dotenv.load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# Project directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_CACHE_DIR = DATA_DIR / "cache"
DATA_OUT_DIR = DATA_DIR / "out"
LOGS_DIR = BASE_DIR / "logs"
DOCS_DIR = BASE_DIR / "docs"

for d in [DATA_RAW_DIR, DATA_CACHE_DIR, DATA_OUT_DIR, LOGS_DIR, DOCS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# API Keys
NVIDIA_API_KEY = os.getenv("Nvdia_api") or os.getenv("NVIDIA_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY") or os.getenv("Serper_api")
HUNTER_API_KEY = os.getenv("Hunter_api") or os.getenv("HUNTER_API_KEY")
TAVILY_API_KEY = os.getenv("Tavily_api") or os.getenv("TAVILY_API_KEY")
FIRECRAWL_API_KEY = os.getenv("Fire_claw") or os.getenv("FIRECRAWL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "nvidia/nemotron-3.5-bolt-e4b")

# Prompt Version for LLM caching (bumped for correction pass 2)
PROMPT_VERSION = "2.1"

# Aggregator domains that must never be treated as direct company websites
AGGREGATOR_DOMAINS = [
    "google.com", "google.de", "gelbeseiten.de", "dasoertliche.de", "11880.com",
    "cylex.de", "wlw.de", "yelp.de", "yelp.com", "facebook.com", "xing.com",
    "linkedin.com", "immoscout24.de", "immowelt.de", "northdata.de", "wikipedia.org",
    "goyellow.de", "firmenwissen.de", "unternehmensregister.de", "handelsregister.de",
    "stadtbranchenbuch.com", "pointoo.de", "web2.cylex.de", "telefonbuch.de"
]

# Strict decision maker title whitelist
DECISION_MAKER_TITLES_WHITELIST = [
    "geschäftsführer", "geschäftsführerin", "inhaber", "inhaberin",
    "gesellschafter", "gesellschafterin", "vorstand", "vorstandsvorsitzender",
    "vorstandsvorsitzende", "prokurist", "prokuristin",
    "leitung hausverwaltung", "leiter hausverwaltung", "leiterin hausverwaltung",
    "leitung technik", "leiter technik", "leiterin technik",
    "leitung betriebskosten", "leiter betriebskosten", "leiterin betriebskosten",
    "head of", "managing director", "ceo"
]

# Exact valid email status vocabulary
VALID_EMAIL_STATUSES = {
    "hunter_verified",
    "hunter_accept_all",
    "mx_ok_unverified",
    "invalid",
    "none"
}

def assert_env_keys():
    """Validates that mandatory API keys exist in .env without printing their values."""
    required = {
        "SERPER_API_KEY": SERPER_API_KEY,
        "LLM_API_KEY (NVIDIA or GEMINI)": NVIDIA_API_KEY or GEMINI_API_KEY,
    }
    missing = [name for name, val in required.items() if not val]
    if missing:
        raise AssertionError(f"Missing required API key(s) in .env: {', '.join(missing)}")

# Berlin 12 Bezirke
BERLIN_BEZIRKE = [
    "Mitte",
    "Friedrichshain-Kreuzberg",
    "Pankow",
    "Charlottenburg-Wilmersdorf",
    "Spandau",
    "Steglitz-Zehlendorf",
    "Tempelhof-Schöneberg",
    "Neukölln",
    "Treptow-Köpenick",
    "Marzahn-Hellersdorf",
    "Lichtenberg",
    "Reinickendorf",
]

# Discovery queries per Bezirk
DISCOVERY_KEYWORDS = [
    "Hausverwaltung",
    "WEG-Verwaltung",
    "Mietverwaltung",
    "Immobilienverwaltung",
    "Sondereigentumsverwaltung",
]

# Crawling and polite scraping
USER_AGENT = "HeidiLeadBot/1.0 (B2B Lead Research for ClimateTech/Metering; research@heidi.systems)"
REQUEST_TIMEOUT = 12
CRAWL_DELAY_PER_HOST = 1.5  # seconds
MAX_INTERNAL_PAGES_PER_SITE = 8
PAGE_KEYWORDS = [
    "impressum",
    "kontakt",
    "contact",
    "team",
    "ueber-uns",
    "über-uns",
    "ueberuns",
    "about",
    "unternehmen",
    "leistungen",
    "service",
    "karriere",
    "jobs",
    "portal",
    "kundenportal",
    "referenzen",
]

# Generic email prefixes to NEVER place in contact_email
GENERIC_EMAIL_PREFIXES = {
    "info",
    "kontakt",
    "office",
    "mail",
    "post",
    "service",
    "hallo",
    "verwaltung",
    "anfrage",
    "buero",
    "team",
    "zentrale",
    "empfang",
    "support",
    "sekretariat",
    "hausverwaltung",
    "immobilien",
    "anfragen",
}

# Known software and metering mentions
KNOWN_SOFTWARE = [
    "Aareon", "Haufe", "Casavi", "Domus", "Immoware24", "WEG-Manager",
    "RealEstate", "Karthago", "iX-Haus", "facilioo", "animo", "Win-CASA",
    "VS3", "Wowinex", "Immotop", "Tenant Portal", "Kundenportal", "Eigentümerportal"
]

METERING_COMPETITORS = [
    "Techem", "ista", "Brunata", "Minol", "Kalo", "Kalorimeta", "Messtechnik", "Qundis", "BFW"
]

ENERGY_SIGNAL_TERMS = [
    "Funkzähler", "Smart Metering", "Fernablesung", "CO2", "Heizkostenverordnung",
    "Energieeffizienz", "Rauchwarnmelder", "Wärmezähler", "Wasserzähler",
    "Submetering", "LoRaWAN", "M-Bus", "Walk-by", "Drive-by", "Klimaschutz", "GEG"
]

GROWTH_SIGNALS = [
    "Stellenangebote", "Karriere", "Wir suchen", "Jobs", "Expansion", "Wachstum", "Neuer Standort"
]

# Scoring Weights
SCORING_WEIGHTS = {
    "portfolio_size": {
        "max": 30,
        "ge_2000": 30,
        "500_to_1999": 22,
        "100_to_499": 12,
        "lt_100": 5,
        "unknown": 8,
    },
    "management_type": {
        "max": 10,
        "both": 10,
        "single": 7,  # Mietverwaltung or WEG
        "unknown": 3,
    },
    "digital_maturity": {
        "max": 15,
        "portal_and_software": 15,
        "one_of_them": 8,
        "none": 0,
        "unknown": 4,
    },
    "metering_provider": {
        "max": 10,
        "none_mentioned": 10,  # prime prospect, unattached
        "in_house": 7,         # doing it themselves, ripe for SaaS
        "competitor": 5,       # attached to legacy, harder switch
    },
    "energy_signals": {
        "max": 15,
        "strong": 15,          # smart metering / remote reading / HeizkostenV
        "weak": 8,            # general energy/sustainability
        "none": 0,
    },
    "growth_signals": {
        "max": 5,
        "present": 5,
        "none": 0,
    },
    "contactability": {
        "max": 15,
        "named_decision_maker_verified_email": 15,
        "named_title_unverified_email": 9,
        "name_only": 4,
        "none": 0,
    },
}

TIER_THRESHOLDS = {
    "A": 70,
    "B": 45,
    "C": 0,
}

# Target columns for final export
LEADS_COLUMNS = [
    "company_name",
    "segment",
    "website",
    "website_status",
    "address",
    "postcode",
    "bezirk",
    "name_source",
    "phone",
    "generic_email",
    "units_managed",
    "properties_managed",
    "employees_estimate",
    "management_type",
    "software_or_portal",
    "metering_provider_mentions",
    "energy_signals",
    "growth_signals",
    "kpi_evidence",
    "lead_score",
    "kpi_fill_rate",
    "tier",
    "score_reason",
    "score_caveats",
    "contact_name",
    "contact_title",
    "academic_title",
    "contact_email",
    "email_origin",
    "email_status",
    "guessed_email",
    "linkedin_url",
    "linkedin_match_note",
    "contact_confidence",
    "data_confidence",
    "source_count",
    "source_urls",
    "last_verified",
]
