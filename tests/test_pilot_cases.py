import csv
import pytest

def test_known_bad_cases():
    leads = list(csv.DictReader(open('data/out/leads.csv', encoding='utf-8-sig')))
    excluded = list(csv.DictReader(open('data/out/excluded.csv', encoding='utf-8-sig')))

    # 1. IVD, VDIV, Haus & Grund, Mieterverein must NOT be in Leads
    for name in ['IVD', 'VDIV', 'Haus & Grund', 'Mieterverein']:
        in_leads = any(name.lower() in l['company_name'].lower() for l in leads)
        assert not in_leads, f"{name} must not be in leads"

    # Entities returned in discovery must be present in excluded
    for name in ['IVD', 'VDIV', 'Haus & Grund']:
        in_ex = any(name.lower() in e['company_name'].lower() for e in excluded)
        assert in_ex, f"{name} must be in excluded"

    # 2. Generic names repaired or excluded
    for name in ['Sondereigentum', 'digital', 'Estavio', 'Zenveo']:
        exact_in_leads = any(l['company_name'].strip().lower() == name.lower() for l in leads)
        assert not exact_in_leads, f"Exact generic '{name}' must not be in leads"

    # 3. Anton Schmittlein (bewerbung@ must be in generic_email, not contact_email)
    for l in leads:
        if 'schmittlein' in l['company_name'].lower():
            assert 'bewerbung@' not in l.get('contact_email', ''), 'bewerbung@ must not be contact_email'
            assert 'bewerbung@' in l.get('generic_email', ''), 'bewerbung@ should be in generic_email'

    # 4. Jeanette Grau (surname mismatch)
    for l in leads:
        if 'grau' in l['company_name'].lower() and 'jeanette' in l.get('contact_name', '').lower():
            assert l.get('contact_email') != 'fabian.blume@hv-grau.de', 'fabian.blume must not be assigned to Jeanette Grau'

    # 5. Mandy Hentschel (info@ in generic_email, not contact_email)
    for l in leads:
        if 'vilicus' in l.get('company_name', '').lower() or 'hentschel' in l.get('contact_name', '').lower():
            assert l.get('contact_email') != 'info@vilicus-berlin.de', 'info@ must not be in contact_email'
            assert l.get('generic_email') == 'info@vilicus-berlin.de', 'info@ must be in generic_email'

    # 6. Units = 'ab zwei Einheiten' or '3,5 Millionen'
    for l in leads:
        u = str(l.get('units_managed', ''))
        assert 'ab ' not in u and u != '3500000', f"Bad units: {u} for {l.get('company_name')}"
