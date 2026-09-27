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
- Demo corpus: full Alaska ingested set — `drug_index.json` (~4.4k searchable drugs), `rule_packs_all.json` (198 packs: 24 partial / 174 text_only; includes Kevzara, Benlysta, Bimzelx, Infliximab, Stelara, Skyrizi, Tremfya and Zymfentra), `criteria_text_all.json` (DOH citations as URLs; no raw PDFs).


Infliximab covers Avsola/Inflectra/Remicade/Renflexis across eight indications, with gated ages and prior therapies plus shared screening, infection, HF dosing and weight-submission criteria. HS requires neither age nor prior therapy. Duration, renewal, weight-based schedules and cautions remain manual review. Next alphabetical text-only brand: Actiq, followed by Amitiza; next biologic candidates: Evenity and Prolia.

Benlysta encodes SLE and lupus nephritis with age ≥5, pediatric IV-only routing, indication-gated specialty/labs/standard therapy and shared safety denials. Duration, reauthorization, dosing, quantity and cautions remain notes for manual review.

Kevzara encodes adult RA/PMR, rheumatology specialty, gated RA therapy failures and PMR EULAR/ACR consistency plus either steroid-history path, shared infection/combination exclusions, and baseline lab thresholds. Documentation, duration, renewal, dosing, quantity enforcement and cautions remain manual review.
