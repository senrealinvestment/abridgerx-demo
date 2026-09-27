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
- Partially encoded: **35** (Adbry, Adcirca, Aduhelm, Benlysta, Bimzelx, Briumvi, Cinqair, Dupixent, Ebglyss, Egrifta, Ekterly, Elevidys, Emflaza, Empaveli, Entyvio, Evenity, Fasenra, Hemlibra, Infliximab, Kesimpta, Kevzara, Lemtrada, Mavenclad, Nucala, Ocrevus, Praluent/Repatha, Prolia, Skyrizi, Soliris/Ultomiris, Stelara, Tepezza, Tezspire, Tremfya, Xolair, Zymfentra)
- Text-only (requires_pa, encoding pending): **163**
- Scanned image criteria PDFs (OCR needed): **7**

## Blockers

- **Drug Lookup Tool**: Prime Therapeutics JS portal; no static export on hub (https://ak.primetherapeutics.com/provider/)
- **CoverMyMeds ePA**: External ePA portal; out of scope for criteria ingest (https://www.covermymeds.health/prior-authorization-forms/prime)
- **Predicate encoding coverage**: Most criteria PDFs are text_only. Partially encoded: adbry, adcirca, aduhelm, benlysta, bimzelx, briumvi, cinqair, dupixent, ebglyss, egrifta, ekterly, elevidys, emflaza, empaveli, entyvio, evenity, fasenra, hemlibra, infliximab, kesimpta, kevzara, lemtrada, mavenclad, nucala, ocrevus, prolia, skyrizi, soliris, stelara, tepezza, tezspire, tremfya, xolair, zymfentra. Step-therapy encoded as attestations; labs/qty attestation-only; Aduhelm ARIA monitoring and reauthorization remain notes only; Ebglyss weight ≥40 kg and quantity limits remain attestation-only notes; Egrifta encodes its closed indication and HIV-positive criterion, with reauthorization and FDA limitations in notes only; Ekterly encodes acute HAE eligibility and denial exclusions, with duration, quantity limits, and cautions in notes only; Elevidys encodes DMD eligibility and denial exclusions, with ongoing monitoring, duration, no reauthorization, and the lifetime infusion limit in notes only; Emflaza encodes DMD eligibility, the prednisone step, and the live vaccination exclusion, with duration, dosing, and cautions in notes only; Empaveli encodes adult PNH eligibility, baseline lab and vaccination attestations, and combination/infection/REMS exclusions, with duration, reauthorization, dosing, quantity enforcement, and cautions in notes only; Entyvio encodes adult UC/CD eligibility, shared 60-day therapy failures, CD-only CDAI, and safety exclusions, with documentation, renewal, monitoring, dosing, and quantity enforcement in notes only; Stelara encodes four indication branches, labeled age, TNF and additional therapy failures, disease activity and safety exclusions, with documentation, renewal, dosing, quantity and cautions in notes only; Skyrizi encodes adult eligibility for four indications, TNF and additional therapy failures, gated disease activity and three safety exclusions, with documentation, duration, dosing, quantity and cautions in notes only; Tremfya encodes three adult indications, TNF and additional therapy failures, gated PASI/HAQ-DI/Mayo activity and four safety exclusions, with documentation, duration, FDA dosing and cautions in notes only; Zymfentra encodes adult UC/CD maintenance after IV infliximab, gastroenterology specialty, ≥10-week positive IV response, TB/HBV screening and safety exclusions, with duration, dosing, quantity enforcement and cautions in notes only; Infliximab encodes eight indications, gated ages and prior therapies, TB/hepatitis screening, infection/HF safety and weight submission; HS has no age or prior-therapy requirement; duration, renewal, dosing and cautions remain notes only; Bimzelx encodes five adult indications with gated specialty, severity, prior therapy and baseline labs/weight plus shared safety exclusions; baseline PASI documentation on non-PASI paths, PsA contraindication source discrepancy, duration, quantity and cautions require manual review; other drugs pending.
- **Scanned 2009 criteria PDFs**: 7 legacy files are image-only; OCR needed before text encoding.

Benlysta encodes closed SLE/LN diagnoses, age and route coupling, gated specialty, autoantibody/biopsy and standard therapy, and shared biologic/Lupkynis and severe active CNS lupus denials. Duration, renewal, dosing, quantity and cautions remain notes only.

Kevzara encodes adult RA/PMR indications, rheumatology specialty, both RA 90-day therapy failures, PMR EULAR/ACR consistency and either steroid-history path, shared infection/combination exclusions and baseline lab thresholds. Documentation, duration, renewal, dosing, quantity enforcement and cautions remain notes only.

Evenity encodes the closed postmenopausal osteoporosis indication, population and diagnosis, oral and injectable therapy steps, healthcare provider administration, calcium/vitamin D counseling, MI/stroke and hypocalcemia exclusions, and prior monthly doses <12. Authorization duration, requested-course lifetime cap verification, quantity and cautions remain manual review.

Prolia/Xgeva encodes eight closed indications, gated ages, Prolia BMD/FRAX and two-treatment history including a bisphosphonate, GCT maturity/resectability, HCM calcium and bisphosphonate history, and shared RANKL/hypocalcemia exclusions. SRE has no bisphosphonate step; source conjunction ambiguity is recorded in pack notes. Documentation, duration, renewal, quantity and cautions remain manual review.

Briumvi encodes three closed adult relapsing MS indications, specialty, two prior MS drugs within 12 months, reproductive attestation, and concurrent MS DMT/active hepatitis B exclusions. Duration, reauthorization, dosing, quantity and cautions remain notes only.

Kesimpta encodes three closed adult relapsing MS indications, specialty, immunoglobulin monitoring agreement, vaccination windows, negative pretherapy hepatitis B screening, one failed drug for the same MS indication, and combination/active infection exclusions. Duration, reauthorization, quantity and cautions remain notes only.

## Honesty note

Do **not** treat text-only packs as coverage decisions. The engine returns `need_info` with an `encoding_incomplete` note when `encoding_status` is `text_only` or criteria are empty.

Ocrevus covers Ocrevus and Ocrevus Zunovo in one pack: four adult MS indications including PPMS, neurology specialty, two MS DMT failures/intolerance/contraindications within 12 months for every indication, and concurrent MS DMT/active hepatitis B exclusions. Documentation, duration, renewal, product dosing, quantity enforcement and cautions remain notes for manual review.

Hemlibra encodes one closed hemophilia A prophylaxis indication (with or without FVIII inhibitors), coagulation-test confirmation, hematology specialty or consultation, no ITI combination, routine prophylaxis intent, and bleed log agreement. FDA eligibility is newborn and older with no age gate. Duration, renewal response and neutralizing antibodies, dosing, quantity and cautions remain notes for manual review.

## Next encoding candidates

Next candidate: Actiq (first remaining text_only brand alphabetically); Amitiza follows. Biologics batch exhausted: Evenity, Prolia, Kevzara, Benlysta and Bimzelx are partially encoded. Other candidates: CGRP therapies, Hep C DAA, and growth hormone.

Soliris/Ultomiris encodes aHUS, PNH, gMG and Soliris-only NMOSD, indication-specific ages and clinical gates, and shared vaccination, specialty and REMS requirements. Duration, renewal, quantity and cautions remain manual review.

Praluent/Repatha encodes three closed indication paths, product-specific familial age floors, cardiology specialty, statin failure/intolerance, failed LDL target, baseline lipids and no dual PCSK9 therapy. Praluent HoFH adult-only labeling, evidence verification, duration, renewal, quantity and cautions remain manual review.

Tepezza encodes adult Graves’ TED, specialty, thyroid status, CAS, active daily living impact, glucocorticoid step, reproductive attestation and uncontrolled diabetes exclusion. Initial 6-month duration, no reauthorization, eight infusions, dosing and cautions remain notes for manual review.

Lemtrada encodes RRMS only, J0202, inadequate response to at least two FDA-indicated MS drugs, REMS enrollment/compliance and baseline labs, administering provider enrollment, no Home Infusion Therapy, no concurrent MS DMT, and negative HIV/TB tests. No numeric age gate is stated. Documentation, duration, reauthorization, dosing and quantity enforcement remain manual review.

Mavenclad encodes adult RRMS and active SPMS (CIS denied), neurology specialty, appropriate CBC/LFT, reproductive contraception counseling, one failed MS drug, and malignancy, HIV/active chronic infection, concurrent MS DMT and pregnancy exclusions. Documentation, duration, reauthorization, dosing, quantity and cautions remain manual review.
