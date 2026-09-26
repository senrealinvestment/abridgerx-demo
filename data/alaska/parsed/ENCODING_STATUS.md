# Alaska Medicaid encoding status

Generated: 2026-09-26 (America/New_York)

Source hub: https://health.alaska.gov/en/education/prior-authorization-medication/

## Downloads

- OK: **214**
- Failed: **0**
- Skipped: **2** (Drug Lookup Tool, CoverMyMeds ePA)
- Total bytes: **60,910,810**
- Criteria PDFs: **190**

## Parsed

- Unique slugs in combined drug index (PA + PDL + max units): **4431**
- Approx unique PA-list drugs (both dated lists, deduped): **1170**
- PA list raw entries (both lists, pre-dedupe): **2184**
- PDL rows: **3638**
- Max units rows (latest 2025-02-25): **585**
- Criteria text JSON files: **198**
- Rule packs: **198**
- Fully encoded (all clauses as predicates): **0**
- Partially encoded: **8** (Adbry, Adcirca, Cinqair, Dupixent, Fasenra, Nucala, Tezspire, Xolair)
- Text-only (requires_pa, encoding pending): **190**
- Scanned image criteria PDFs (OCR needed): **7**

## Blockers

- **Drug Lookup Tool**: Prime Therapeutics JS portal; no static export on hub (https://ak.primetherapeutics.com/provider/)
- **CoverMyMeds ePA**: External ePA portal; out of scope for criteria ingest (https://www.covermymeds.health/prior-authorization-forms/prime)
- **Predicate encoding coverage**: Most criteria PDFs are text_only. Partially encoded: adbry, adcirca, cinqair, dupixent, fasenra, nucala, tezspire, xolair. Step-therapy encoded as attestations; labs/qty attestation-only; other drugs pending.
- **Scanned 2009 criteria PDFs**: 7 legacy files are image-only; OCR needed before text encoding.

## Honesty note

Do **not** treat text-only packs as coverage decisions. The engine returns `need_info` with an `encoding_incomplete` note when `encoding_status` is `text_only` or criteria are empty.

## Next encoding candidates

Next candidates: Aduhelm, Ebglyss, CGRP therapies, Entyvio/Stelara/Skyrizi class, Hep C DAA, and growth hormone.
