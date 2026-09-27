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
- Partially encoded: **22** (Adbry, Adcirca, Aduhelm, Bimzelx, Cinqair, Dupixent, Ebglyss, Egrifta, Ekterly, Elevidys, Emflaza, Empaveli, Entyvio, Fasenra, Infliximab, Nucala, Skyrizi, Stelara, Tezspire, Tremfya, Xolair, Zymfentra)
- Text-only (requires_pa, encoding pending): **176**
- Scanned image criteria PDFs (OCR needed): **7**

## Blockers

- **Drug Lookup Tool**: Prime Therapeutics JS portal; no static export on hub (https://ak.primetherapeutics.com/provider/)
- **CoverMyMeds ePA**: External ePA portal; out of scope for criteria ingest (https://www.covermymeds.health/prior-authorization-forms/prime)
- **Predicate encoding coverage**: Most criteria PDFs are text_only. Partially encoded: adbry, adcirca, aduhelm, bimzelx, cinqair, dupixent, ebglyss, egrifta, ekterly, elevidys, emflaza, empaveli, entyvio, fasenra, infliximab, nucala, skyrizi, stelara, tezspire, tremfya, xolair, zymfentra. Step-therapy encoded as attestations; labs/qty attestation-only; Aduhelm ARIA monitoring and reauthorization remain notes only; Ebglyss weight ≥40 kg and quantity limits remain attestation-only notes; Egrifta encodes its closed indication and HIV-positive criterion, with reauthorization and FDA limitations in notes only; Ekterly encodes acute HAE eligibility and denial exclusions, with duration, quantity limits, and cautions in notes only; Elevidys encodes DMD eligibility and denial exclusions, with ongoing monitoring, duration, no reauthorization, and the lifetime infusion limit in notes only; Emflaza encodes DMD eligibility, the prednisone step, and the live vaccination exclusion, with duration, dosing, and cautions in notes only; Empaveli encodes adult PNH eligibility, baseline lab and vaccination attestations, and combination/infection/REMS exclusions, with duration, reauthorization, dosing, quantity enforcement, and cautions in notes only; Entyvio encodes adult UC/CD eligibility, shared 60-day therapy failures, CD-only CDAI, and safety exclusions, with documentation, renewal, monitoring, dosing, and quantity enforcement in notes only; Stelara encodes four indication branches, labeled age, TNF and additional therapy failures, disease activity and safety exclusions, with documentation, renewal, dosing, quantity and cautions in notes only; Skyrizi encodes adult eligibility for four indications, TNF and additional therapy failures, gated disease activity and three safety exclusions, with documentation, duration, dosing, quantity and cautions in notes only; Tremfya encodes three adult indications, TNF and additional therapy failures, gated PASI/HAQ-DI/Mayo activity and four safety exclusions, with documentation, duration, FDA dosing and cautions in notes only; Zymfentra encodes adult UC/CD maintenance after IV infliximab, gastroenterology specialty, ≥10-week positive IV response, TB/HBV screening and safety exclusions, with duration, dosing, quantity enforcement and cautions in notes only; Infliximab encodes eight indications, gated ages and prior therapies, TB/hepatitis screening, infection/HF safety and weight submission; HS has no age or prior-therapy requirement; duration, renewal, dosing and cautions remain notes only; Bimzelx encodes five adult indications with gated specialty, severity, prior therapy and baseline labs/weight plus shared safety exclusions; baseline PASI documentation on non-PASI paths, PsA contraindication source discrepancy, duration, quantity and cautions require manual review; other drugs pending.
- **Scanned 2009 criteria PDFs**: 7 legacy files are image-only; OCR needed before text encoding.

## Honesty note

Do **not** treat text-only packs as coverage decisions. The engine returns `need_info` with an `encoding_incomplete` note when `encoding_status` is `text_only` or criteria are empty.

## Next encoding candidates

Next candidate: Actiq (first remaining text_only brand alphabetically); Amitiza follows. Other candidates: CGRP therapies, Hep C DAA, and growth hormone.
