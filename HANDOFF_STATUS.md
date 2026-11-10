# Handoff Status

| Item | Status | Evidence |
|---|---|---|
| 1. Websites | DONE | Aggregator redirects rejected/resolved; final audit passed Gate 1; 291 active websites are `ok`. |
| 2. Berlin verification | DONE | Cached Impressum postcode rescue wired into dedupe; final audit passed Gate 5. |
| 3. Names/segments/encoding | DONE | Boilerplate names removed, service-only names resolved from cached Impressum/domain evidence or excluded as `name_unresolvable`, and Strategic segmentation enforced; final audit passed Gates 2-4. |
| 4. Extraction integrity | DONE | Eight-page crawl configured; unsupported KPI values dropped when evidence is invalid; final audit passed Gate 6. |
| 5. Emails/contacts | DONE | Generic/guessed hygiene and `none` status enforced; final audit passed Gates 7-8 and 11. |
| 6. Coverage/recall | DONE | `data/out/recall_report.md` regenerated from the seed file. |
| 7. Provenance | DONE | `sources_log.csv` reports raw rows, duplicate merges, rows per tab, exclusions, and notes that companies may appear under several sources; final audit passed Gate 12. |
| 8. Validation sample | DONE | 40 stratified rows generated with all manual columns empty; `compute_accuracy.py` withholds accuracy while pending. |
| 9. Audit/tests/export | DONE | `pytest -q`: 13 passed; hard audit: passed; seven-tab workbook exported. Google Sheet blocked because `GOOGLE_SERVICE_ACCOUNT_JSON` is absent. |

Remaining user actions: complete the manual validation sample, rerun `compute_accuracy.py`, test any uploaded Sheet link, rotate keys if shared, and submit the deliverables.
