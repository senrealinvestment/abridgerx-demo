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
- Demo corpus: full Alaska ingested set — `drug_index.json` (~4.4k searchable drugs), `rule_packs_all.json` (198 packs: 62 partial / 136 text_only; includes Somatropin, Serostim, Vyjuvek, Zynteglo, Roctavian, Auvelity, Dojolvi, Voxzogo, Cinryze, Berinert, Apokyn/Kynmobi, Anzupgo, Amrix, Ampyra, Amitiza/Linzess, CGRP antagonists, Hympavzi, Evkeeza, Dawnzera, Fabhalta, Crysvita, Hemgenix, Beqvez, Andembry, Actiq, Zolgensma, Mayzent, Mavenclad, Lemtrada, Tepezza, Praluent/Repatha, Soliris/Ultomiris, Hemlibra, Ocrevus/Ocrevus Zunovo, Kesimpta, Briumvi, Prolia/Xgeva, Evenity, Kevzara, Benlysta, Bimzelx, Infliximab, Stelara, Skyrizi, Tremfya and Zymfentra), `criteria_text_all.json` (DOH citations as URLs; no raw PDFs).


Infliximab covers Avsola/Inflectra/Remicade/Renflexis across eight indications, with gated ages and prior therapies plus shared screening, infection, HF dosing and weight-submission criteria. HS requires neither age nor prior therapy. Duration, renewal, weight-based schedules and cautions remain manual review.

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

Dawnzera (`dawnzeratm`) is partially encoded for HAE-C1-INH type 1 or 2 prophylaxis, including the two-preferred-agent requirement across two different classes. Andembry and Dawnzera are reciprocal alternatives with separately evaluated steps. Duration, quantity and cautions remain manual review.

Evkeeza encodes closed HoFH eligibility, age ≥12, specialty or consultation, genetic or clinical confirmation, both 3-month therapy steps, persistent LDL-C thresholds, reproductive attestation, baseline lipids and diet. Evidence verification, duration, reauthorization, quantity and cautions remain manual review.

Hympavzi (`hympavzi`, marstacimab-hncq) is partially encoded for hemophilia A/B routine prophylaxis without respective factor inhibitors: age ≥12, hematologist or consultation, no prophylactic factor replacement, severe factor activity <1% or ≥2 documented spontaneous joint bleeds, no breakthrough treatment, and new-start maintenance ≤150 mg weekly. Duration (initial ≤3 months; renewal ≤12 months), quantity (8 syringes or pens per 28 days), and cautions remain manual review.

CGRP antagonists (`calcitonin-gene-related-peptide`) encode preventive and acute migraine branches with agent-specific FDA age attestation, specialty, gated therapy trials and shared concurrency denials. Duration (initial ≤3 months; reauthorization ≤12 months), quantity (34 days), and cautions remain manual review.

Amitiza/Linzess (`amitiza`, lubiprostone / linaclotide) encodes three closed adult indications, age ≥18, and trial/inadequate response from two of fiber, stimulant, and osmotic laxative groups. Product-specific eligibility (including Amitiza IBS-C in women only and Amitiza-only OIC), documentation and trial dates, methadone limitation, 12-month authorization and quantity limits remain notes for manual review.

Ampyra (`ampyra`, dalfampridine) encodes MS treatment to improve walking, CrCl >50 mL/min, and EDSS >4.0 and <7.0 OR difficulty walking with ability to walk 25 feet with or without a cane, crutches or braces. Initial approval up to 6 months, renewal requiring continued eligibility and increased walking speed, 30-day supply and 2 tablets/day remain notes for manual review. No MS DMT alternatives are linked.

Amrix (`amrix`, cyclobenzaprine extended release) encodes the hospice/cancer/LTC pharmacy override OR the standard closed acute painful musculoskeletal muscle spasm indication, age 18–65 and suboptimal IR cyclobenzaprine 5mg or 10mg for ≥5 days. Hyperthyroidism and concurrent MAOI denials apply on both paths. Use up to 2–3 weeks, spasticity/CP limitations, 21 capsules / 21 days, no refills and a new PA each course remain notes for manual review.

Anzupgo (`anzupgo`, delgocitinib) encodes moderate to severe chronic hand eczema, age ≥18, allergy/dermatology/immunology specialty or consultation, either chronicity path, either medium potency TCS step path, and no concomitant other JAK inhibitor or potent immunosuppressant including biologics. Initial approval up to 3 months, reauthorization up to one year, 60 grams per 30 days, limitations of use and cautions remain notes for manual review.

Apokyn/Kynmobi (`apokyn`, apomorphine) encodes Parkinson’s off episodes, age ≥18, neurologist or consultation, concurrent anti-Parkinson therapy, end-of-dose or unpredictable hypomobility episodes, and no concurrent 5-HT3 antagonist. Duration, quantity limits and cautions remain notes only. The pack uses approval date `2020-11-20` and records the PDF/stub date discrepancy.

Berinert (`berinert`, C1 esterase inhibitor, human) encodes acute abdominal/facial/laryngeal HAE attacks, diagnosis by an immunologist, monthly abdominal/respiratory attacks requiring ER intervention in the previous 6 months, no concurrent ACE inhibitor or estrogen replacement, and insufficient response or contraindication to BOTH androgen and antifibrinolytic classes. Letter of medical necessity, ER records, endocrinologist documentation of androgen contraindications, and adult/adolescent eligibility require manual review. Prophylaxis is not established. Stub effective date 2022-11-01 is retained with PDF dates in notes.

Cinryze (`cinryze`, C1 esterase inhibitor) encodes routine HAE prophylaxis only, immunologist diagnosis, monthly abdominal/respiratory ER attacks in the prior 6 months (generally with Berinert or Kalbitor), no concurrent ACE inhibitor or estrogen replacement, and insufficient response or contraindication to BOTH androgen and antifibrinolytic classes. Adolescent/adult eligibility, medical necessity letter, ER records, endocrinologist documentation and Medical Director ER availability remain notes for manual review. The last-updated date 2011-07-06 replaces the placeholder effective date. Reciprocal peer links connect Cinryze with Andembry, Berinert and Dawnzera, each subject to its own indication and criteria.

Voxzogo (`voxzogo`, vosoritide) encodes the closed achondroplasia linear-growth indication, age ≥5 and <18, endocrinology specialty or consultation, FGFR3 genetic confirmation, baseline and ongoing growth measurements, open epiphyses, surgery exclusions, no concurrent human growth hormone or insulin-like growth factor, and exclusion of other causes of short stature. Accelerated approval and confirmatory-trial caveat, duration, renewal, quantity limits and cautions remain notes for manual review. Next encoding candidate: `clotting-factor`.

Dojolvi (triheptanoin) encodes closed molecularly confirmed LC-FAOD eligibility, at least two of three diagnostic pathways, specialty or consultation, weight and daily caloric intake submission, dose ≤35% of daily caloric intake, and no concurrent other medium chain triglyceride. No numeric age gate is stated. Documentation, duration, quantity and pancreatic lipase inhibitor cautions remain manual review. Next encoding candidate: `clotting-factor`.

Auvelity (`auvelity`, dextromethorphan hbr / bupropion hcl) encodes adult MDD, age ≥18, failure of ≥2 different antidepressants for ≥60 days each at therapeutic doses, and all explicit seizure disorder, current/prior anorexia or bulimia, MAOI within 14 days, and severe hepatic/renal impairment denials. Initial approval 3 months, renewal up to 12 months, 68 tablets within 34 days / maximum 2 per day, and fetal harm, hypertension and suicidality cautions remain notes for manual review. Next encoding candidate: `clotting-factor`.

Roctavian (`roctavian`, valoctocogene roxaparvovec-rvox) encodes adult severe hemophilia A eligibility, hematology specialty, FVIII and exposure criteria, inhibitor and AAV5 screening, liver assessments and denial exclusions. Duration, no reauthorization, lifetime infusion limit and monitoring remain notes for manual review. Next encoding candidate: `clotting-factor`.

Zynteglo (`zynteglo`, betibeglogene autotemcel) encodes transfusion-dependent β-thalassemia, age ≥4, hematology specialty or consultation, genetic confirmation, weight ≥6 kg, adequate CD34+ cells, negative infectious tests before cell collection, either transfusion-history path and prior gene therapy/allogeneic HSCT exclusions. Documentation, initial approval up to 6 months, no reauthorization, one lifetime infusion (J3393) and cautions remain manual review. Next encoding candidate: `clotting-factor`.

Vyjuvek (`vyjuvek`, beremagene geperpavec-svdt) encodes DEB wounds with COL7A1 mutations, age ≥6 months, dermatology specialty or consultation, genetic confirmation, baseline target wound size documentation and all four wound readiness conditions in one attestation. Documentation verification, initial and reauthorization duration up to 6 months, age-based 28-day quantity limits (J3401) and cautions remain notes for manual review. Next encoding candidate: `clotting-factor`.

Serostim (`serostim`, somatropin) encodes HIV/AIDS wasting/cachexia, HIV infection, current ART, either dronabinol/megestrol step, exclusion of other weight-loss causes, any of four severity paths, either clinical syndrome, and body-mass/anti-aging/GH contraindication/Increlex exclusions. No age gate is specified. Reauthorization response, initial ≤6 months and renewal ≤12 months, quantity limit (None), and mechanism remain notes only. Alternatives are empty because Egrifta has a distinct indication. Next encoding candidate: `clotting-factor`.

Somatropin (`somatropin`, Growth Hormone) encodes nine closed indications, seven shared denials, gated Table 1 step therapy (except SHOX), genetic confirmation and growth criteria, six pediatric GHD eligibility paths, three transition reconfirmation paths, and four adult paths. Reauthorization, duration, quantity (None), product FDA/step matrices and dosage forms remain notes only. ISS and short bowel syndrome are excluded. Next encoding candidate: `clotting-factor`.
