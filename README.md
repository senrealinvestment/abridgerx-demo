# AbridgeRx

Clinician prior-authorization check for **Alaska Medicaid**: deterministic criteria **yes/no**, and if no, **covered alternatives** the patient qualifies for.

Working title — rename before public (trademark collision with Abridge).

## Status

v1 ingest complete for Alaska DOH hub artifacts (2026-09-26). See [data/alaska/ENCODING_STATUS.md](data/alaska/ENCODING_STATUS.md).

## Repo layout

- `docs/` — product and compliance notes
- `data/alaska/raw/` — downloaded DOH lists/PDFs (versioned) + `MANIFEST.json`
- `data/alaska/parsed/` — drug index, criteria text, rule packs
- `src/ingest/` — repeatable `download_alaska.py` / `parse_alaska.py`
- `src/rules/` — rule schema
- `src/engine/` — `evaluate()` and alternative resolver
- `src/ui/` — clinician web UI (FastAPI + static HTML/JS)
- `tests/` — evaluate fixtures

## Ingest

```bash
python3 src/ingest/download_alaska.py
python3 src/ingest/parse_alaska.py
python3 tests/test_evaluate.py
```

Source hub: https://health.alaska.gov/en/education/prior-authorization-medication/


## Clinician UI

Local advisory check against the ingested Alaska Medicaid corpus.

```bash
cd /path/to/abridgerx
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m ui
# or: PYTHONPATH=src .venv/bin/uvicorn ui.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**

- Typeahead search over `data/alaska/parsed/drug_index.json`
- Drug card: `requires_pa`, PDL, max units, citations, encoding status
- **partial / full** packs: fact form → `evaluate()` → pass / fail / need_info + failed clauses + alternatives
- **text_only**: archived criteria text + required-fact checklist — no invented coverage decision
- Smoke: `PYTHONPATH=src .venv/bin/python tests/test_ui_smoke.py`

## Encoding honesty

Most criteria PDFs are archived as **text_only** rule packs (`encoding_status: text_only`). The engine returns `need_info` / `encoding_incomplete` — it never auto-passes empty criteria. Adbry, Adcirca, Aduhelm, Dupixent, Ebglyss, Egrifta, Ekterly, Elevidys, Emflaza, Empaveli, Entyvio, Xolair, Fasenra, Nucala, Cinqair, Tezspire, Stelara, Skyrizi, Tremfya, Zymfentra, and Infliximab have **partial** structured predicates from the published AK PDFs (IL-5 brands share the Interleukin-5 Inhibitors criteria PDF; Tezspire has its own 2023 criteria PDF; Adbry has its own 2024 AD criteria PDF; Adcirca encodes the WHO Group I PAH, nitrate exclusion, and generic sildenafil step criteria; Aduhelm encodes initial Alzheimer's eligibility and denial exclusions, with ARIA monitoring and reauthorization in notes; Ebglyss encodes the 2026 AD criteria with weight ≥40 kg and quantity limits in attestation-only notes; Egrifta encodes the closed HIV lipodystrophy indication and HIV-positive criterion, with reauthorization and FDA limitations in notes only; Ekterly encodes acute HAE eligibility and denial exclusions, with duration, quantity limits, and cautions in notes only; Elevidys encodes DMD eligibility and denial exclusions, with ongoing monitoring, duration, no reauthorization, and the lifetime infusion limit in notes only; Emflaza encodes DMD eligibility, the prednisone step, and the live vaccination exclusion, with duration, dosing, and cautions in notes only; Empaveli encodes adult PNH eligibility, baseline lab and vaccination attestations, and combination/infection/REMS exclusions, with duration, reauthorization, dosing, quantity enforcement, and cautions in notes only; Entyvio encodes adult UC/CD eligibility, shared 60-day therapy failures, CD-only CDAI, and safety exclusions, with documentation, renewal, monitoring, dosing, and quantity enforcement in notes only).

## Vercel demo

Live clinician PA-check demo (advisory; published AK criteria):

- **Production URL:** https://abridgerx.vercel.app
- **Vercel project:** `abridgerx` (team `sergio-navarretes-projects`)
- **Deploy source (public mirror for Vercel Git):** https://github.com/senrealinvestment/abridgerx-demo  
  Private canonical repo remains https://github.com/senrealinvestment/abridgerx — grant the Vercel GitHub App access to link it directly later.
- Framework: FastAPI (`app.py` entry + `vercel.json`). Rules engine only; no TypeSafe / SYSTEM_ONE keys in the client.
- Demo corpus: full Alaska ingested set — `drug_index.json` (~4.4k searchable drugs), `rule_packs_all.json` (198 packs: 50 partial / 148 text_only; includes Amrix, Ampyra, Amitiza/Linzess, CGRP antagonists, Hympavzi, Evkeeza, Dawnzera, Fabhalta, Crysvita, Hemgenix, Beqvez, Andembry, Actiq, Zolgensma, Mayzent, Mavenclad, Lemtrada, Tepezza, Praluent/Repatha, Soliris/Ultomiris, Hemlibra, Ocrevus/Ocrevus Zunovo, Kesimpta, Briumvi, Prolia/Xgeva, Evenity, Kevzara, Benlysta, Bimzelx, Infliximab, Stelara, Skyrizi, Tremfya and Zymfentra), `criteria_text_all.json` (DOH citations as URLs; no raw PDFs).


Infliximab covers Avsola/Inflectra/Remicade/Renflexis across eight indications, with gated ages and prior therapies plus shared screening, infection, HF dosing and weight-submission criteria. HS requires neither age nor prior therapy. Duration, renewal, weight-based schedules and cautions remain manual review. Next text-only encoding candidate: Amrix.

Benlysta encodes SLE and lupus nephritis with age ≥5, pediatric IV-only routing, indication-gated specialty/labs/standard therapy and shared safety denials. Duration, reauthorization, dosing, quantity and cautions remain notes for manual review.

Kevzara encodes adult RA/PMR, rheumatology specialty, gated RA therapy failures and PMR EULAR/ACR consistency plus either steroid-history path, shared infection/combination exclusions, and baseline lab thresholds. Documentation, duration, renewal, dosing, quantity enforcement and cautions remain manual review.

Ocrevus covers Ocrevus and Ocrevus Zunovo in one pack: four adult MS indications including PPMS, neurology specialty, two MS DMT failures/intolerance/contraindications within 12 months for every indication, and concurrent MS DMT/active hepatitis B exclusions. Documentation, duration, renewal, product dosing, quantity enforcement and cautions remain notes for manual review.

Hemlibra encodes one closed hemophilia A prophylaxis indication (with or without FVIII inhibitors), coagulation-test confirmation, hematology specialty or consultation, no ITI combination, routine prophylaxis intent, and bleed log agreement. FDA eligibility is newborn and older with no age gate. Duration, renewal response and neutralizing antibodies, dosing, quantity and cautions remain notes for manual review.

Tepezza encodes adult Graves’ TED eligibility, specialty, thyroid status, CAS, active daily living impact, glucocorticoid step, reproductive attestation and diabetes denial. Duration, no reauthorization, eight-infusion dosing and cautions remain notes for manual review.

Lemtrada encodes RRMS only, J0202, inadequate response to at least two FDA-indicated MS drugs, REMS enrollment/compliance and baseline labs, administering provider enrollment, no Home Infusion Therapy, no concurrent MS DMT, and negative HIV/TB tests. No numeric age gate is stated. Documentation, duration, reauthorization, dosing and quantity enforcement remain manual review.

Mavenclad encodes adult RRMS and active SPMS (CIS denied), neurology specialty, appropriate CBC/LFT, reproductive contraception counseling, one failed MS drug, and malignancy, HIV/active chronic infection, concurrent MS DMT and pregnancy exclusions. Documentation, duration, reauthorization, dosing, quantity and cautions remain manual review.

Mayzent encodes adult CIS, RRMS and active SPMS, neurology specialty, baseline ECG/CBC/liver enzymes/ophthalmic evaluation, 6-month cardiovascular exclusions, conduction disease with a functioning-pacemaker exception, CYP2C9 genotyping, two failed MS drugs, baseline skin examination and no concurrent MS DMT. Documentation, duration, reauthorization, dosing, quantity and cautions remain manual review.

Zolgensma encodes SMA eligibility for age <2 years, pediatric neurology specialty, SMN1 genetics, anti-AAV9 titer, baseline labs and treatment/safety exclusions. Duration, no reauthorization, lifetime quantity, dosing and liver cautions remain notes for manual review.

Actiq encodes a closed cancer breakthrough pain indication, age ≥16, existing around-the-clock opioid therapy and opioid tolerance. TIRF REMS dispensing limitations, up-to-6-month authorization and 3-per-day quantity limit remain notes for manual review.

Hemgenix encodes moderate to severe hemophilia B, three clinical eligibility paths, adult age, hematology specialty, Factor IX severity and exposure, inhibitor history/screen, hepatic imaging and four denial exclusions. No AAV neutralizing antibody test is required. Hemgenix and Beqvez have reciprocal alternative links. Documentation, initial 3-month duration, no reauthorization, lifetime infusion limit and post-dose monitoring remain notes for manual review.

Dawnzera (`dawnzeratm`) is partially encoded for HAE-C1-INH type 1 or 2 prophylaxis, including the two-preferred-agent requirement across two different classes. Andembry and Dawnzera are reciprocal alternatives with separately evaluated steps. Duration, quantity and cautions remain manual review. Next encoding candidate: `anzupgo`.

Evkeeza encodes closed HoFH eligibility, age ≥12, specialty or consultation, genetic or clinical confirmation, both 3-month therapy steps, persistent LDL-C thresholds, reproductive attestation, baseline lipids and diet. Evidence verification, duration, reauthorization, quantity and cautions remain manual review.

Hympavzi (`hympavzi`, marstacimab-hncq) is partially encoded for hemophilia A/B routine prophylaxis without respective factor inhibitors: age ≥12, hematologist or consultation, no prophylactic factor replacement, severe factor activity <1% or ≥2 documented spontaneous joint bleeds, no breakthrough treatment, and new-start maintenance ≤150 mg weekly. Duration (initial ≤3 months; renewal ≤12 months), quantity (8 syringes or pens per 28 days), and cautions remain manual review.

CGRP antagonists (`calcitonin-gene-related-peptide`) encode preventive and acute migraine branches with agent-specific FDA age attestation, specialty, gated therapy trials and shared concurrency denials. Duration (initial ≤3 months; reauthorization ≤12 months), quantity (34 days), and cautions remain manual review.

Amitiza/Linzess (`amitiza`, lubiprostone / linaclotide) encodes three closed adult indications, age ≥18, and trial/inadequate response from two of fiber, stimulant, and osmotic laxative groups. Product-specific eligibility (including Amitiza IBS-C in women only and Amitiza-only OIC), documentation and trial dates, methadone limitation, 12-month authorization and quantity limits remain notes for manual review.

Ampyra (`ampyra`, dalfampridine) encodes MS treatment to improve walking, CrCl >50 mL/min, and EDSS >4.0 and <7.0 OR difficulty walking with ability to walk 25 feet with or without a cane, crutches or braces. Initial approval up to 6 months, renewal requiring continued eligibility and increased walking speed, 30-day supply and 2 tablets/day remain notes for manual review. No MS DMT alternatives are linked.

Amrix (`amrix`, cyclobenzaprine extended release) encodes the hospice/cancer/LTC pharmacy override OR the standard closed acute painful musculoskeletal muscle spasm indication, age 18–65 and suboptimal IR cyclobenzaprine 5mg or 10mg for ≥5 days. Hyperthyroidism and concurrent MAOI denials apply on both paths. Use up to 2–3 weeks, spasticity/CP limitations, 21 capsules / 21 days, no refills and a new PA each course remain notes for manual review.
