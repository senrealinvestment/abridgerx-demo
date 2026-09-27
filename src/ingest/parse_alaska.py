#!/usr/bin/env python3
"""Parse Alaska Medicaid raw artifacts into drug index + rule packs.

Deterministic only — extracts text / table rows; does not invent coverage.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "alaska" / "raw"
PARSED = ROOT / "data" / "alaska" / "parsed"
CRITERIA_TEXT = PARSED / "criteria_text"
RULE_PACKS = PARSED / "rule_packs"
MANIFEST_PATH = RAW / "MANIFEST.json"
DOWNLOAD_DATE = "2026-09-26"

SKIP_LINE_RE = re.compile(
    r"^(Alaska Medicaid|Last Updated|Medication\s+Date Added|Quantity Limit|"
    r"PA Required See website|Page \d+|^\s*$)",
    re.I,
)


def pdftotext(path: Path) -> str:
    r = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", errors="replace")


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[®™©]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "unknown"


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def parse_pa_list(text: str, source_file: str, list_kind: str) -> list[dict]:
    """Extract medication names from Interim/PA list layout."""
    drugs: list[dict] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if "Alaska Medicaid" in line and "Prior Authorization" in line:
            continue
        if "Last Updated" in line and len(line.strip()) < 40:
            continue
        if re.search(r"Medication\s+Date Added", line):
            continue
        if "PA Required See website" in line and not re.search(r"[A-Za-z]{3,}", line[:40]):
            continue
        # Medication name is left column; dates appear as m/d/yyyy patterns
        # Strip trailing URL/notes
        cleaned = re.sub(r"https?://\S+", "", line)
        cleaned = re.sub(r"PA Required See website.*", "", cleaned)
        # Find first date-like token as end of name region
        m = re.search(
            r"^(.*?)\s{2,}(\d{1,2}/\d{1,2}/\d{2,4}|N/A|Moved|PA removed|See |updated)",
            cleaned,
        )
        if m:
            name = m.group(1).strip()
        else:
            # Fallback: take left portion before large gap
            parts = re.split(r"\s{3,}", cleaned.strip())
            name = parts[0].strip() if parts else ""
        name = re.sub(r"\s+", " ", name).strip(" -|,")
        if len(name) < 3 or len(name) > 120:
            continue
        if name.lower().startswith("medication"):
            continue
        if re.match(r"^page\s+\d+", name, re.I):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        drugs.append(
            {
                "name": name,
                "slug": slugify(name),
                "requires_pa": True,
                "source_list": list_kind,
                "source_file": source_file,
            }
        )
    return drugs


def parse_pdl(text: str, source_file: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()
    for line in text.splitlines():
        # Lines start with PDL group letter then market basket
        m = re.match(
            r"^\s*[A-Z]\s{2,}(.+?)\s{2,}(.+?)\s+(SSB|GEN|BWG)\s+(.+?)\s+(\S+)\s+(ON|OFF)\s+(\S+)",
            line,
        )
        if not m:
            # Simpler: look for ON/OFF near end
            if not re.search(r"\b(ON|OFF)\b", line):
                continue
            # Try looser parse
            mo = re.search(r"\b(ON|OFF)\b", line)
            if not mo:
                continue
            status = mo.group(1)
            left = line[: mo.start()].rstrip()
            # drug type token
            dt = re.search(r"\b(SSB|GEN|BWG)\b", left)
            if not dt:
                continue
            brandish = left[dt.end() :].strip()
            # brand name is before drug type — take last big chunk before SSB/GEN/BWG
            before = left[: dt.start()].rstrip()
            # market basket often ALL CAPS words at start after group letter
            bm = re.match(r"^\s*[A-Z]\s{2,}(.+)$", before)
            rest = bm.group(1) if bm else before
            # Split market basket (early caps phrase) from brand — heuristic: 2+ spaces
            chunks = re.split(r"\s{2,}", rest.strip())
            if len(chunks) >= 2:
                market = chunks[0]
                brand = " ".join(chunks[1:])
            elif chunks:
                market = ""
                brand = chunks[0]
            else:
                continue
            gnn = brandish  # may include strength residue; good enough for index
            key = (brand.lower(), status)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "brand_name": brand.strip(),
                    "generic_name": gnn.strip(),
                    "pdl_status": "preferred" if status == "ON" else "non_preferred",
                    "market_basket": market.strip(),
                    "source_file": source_file,
                    "slug": slugify(brand),
                }
            )
            continue
        market, brand, dtype, gnn, strength, status, eff = m.groups()
        key = (brand.lower(), strength, status)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "brand_name": brand.strip(),
                "generic_name": gnn.strip(),
                "strength": strength.strip(),
                "drug_type": dtype,
                "pdl_status": "preferred" if status == "ON" else "non_preferred",
                "market_basket": market.strip(),
                "status_effective_date": eff.strip(),
                "source_file": source_file,
                "slug": slugify(brand),
            }
        )
    return rows


def parse_max_units(text: str, source_file: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        if "Max Units" in line or "BRAND NAME" in line or "Updated" in line[:40]:
            continue
        # Brand at left; max units/30 days is a number possibly with *
        m = re.match(
            r"^([A-Za-z][A-Za-z0-9 ®™\-/]+?)\s{2,}(\S.*?)\s{2,}(\d+\*?(?:mL)?)\s",
            line.strip(),
        )
        if not m:
            continue
        brand, strength, max_u = m.groups()
        if brand.lower() in ("opioids/analgesics", "brand name and all generic equivalents"):
            continue
        rows.append(
            {
                "brand_name": brand.strip(),
                "strength": strength.strip(),
                "max_units_30_days": max_u.strip(),
                "source_file": source_file,
                "slug": slugify(brand),
                "requires_pa_note": "REQUIRES PA" in line.upper(),
            }
        )
    return rows


def extract_header_meta(text: str) -> dict:
    meta: dict = {}
    m = re.search(r"Effective:\s*(\d{1,2}/\d{1,2}/\d{2,4})", text)
    if m:
        mo, d, y = m.group(1).split("/")
        yi = int(y)
        if yi < 100:
            yi += 2000
        meta["effective_date"] = f"{yi:04d}-{int(mo):02d}-{int(d):02d}"
    # Drug title: line after "Prior Authorization Criteria" often brand
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:15]):
        if re.search(r"Prior Authorization Criteria", ln, re.I) and i + 1 < len(lines):
            # next non-empty may be brand
            for j in range(i + 1, min(i + 5, len(lines))):
                cand = lines[j]
                if re.search(r"FDA INDICATIONS|APPROVAL CRITERIA|Version:", cand, re.I):
                    break
                if len(cand) < 80 and not cand.startswith("ALASKA"):
                    meta.setdefault("title_line", cand)
                    # generic in parentheses on same or next line
                    gm = re.search(r"\(([^)]+)\)", cand)
                    if gm:
                        meta["generic_name"] = gm.group(1).strip()
                    brand = re.sub(r"[®™].*", "", cand)
                    brand = re.sub(r"\(.*", "", brand).strip()
                    if brand:
                        meta["drug_name"] = brand
                    break
            break
    return meta


def infer_required_facts(text: str) -> list[str]:
    facts: list[str] = []
    tl = text.lower()
    if re.search(r"\bage\b|years of age|aged \d", tl):
        facts.append("age_years")
    if re.search(r"indication|diagnos|asthma|atopic|copd|urticaria", tl):
        facts.append("indication")
    if re.search(r"prescribed by|in consultation with|specialist", tl):
        facts.append("prescriber_specialty")
    if re.search(r"tried and failed|inadequate response|contraindication", tl):
        facts.append("prior_therapy_failures")
    if re.search(r"eosinophil|ige level|baseline ige", tl):
        facts.append("lab_ige_or_eosinophil")
    # unique preserve order
    out: list[str] = []
    for f in facts:
        if f not in out:
            out.append(f)
    return out


def drug_names_from_criteria_label(label: str, filename: str, meta: dict) -> list[str]:
    if meta.get("drug_name"):
        names = [meta["drug_name"]]
        # Also split combined titles like "Soliris, Ultomiris"
        if "," in meta["drug_name"] or "/" in meta["drug_name"]:
            parts = re.split(r"[,/]", meta["drug_name"])
            names = [p.strip() for p in parts if p.strip()]
        return names
    # From hub label
    lab = re.sub(r"\s*Criteria\s*$", "", label or "", flags=re.I)
    lab = re.sub(r"\s*\(.*$", "", lab).strip()
    if lab and lab not in ("Form", "| Form"):
        if "," in lab or " and " in lab.lower() or "/" in lab:
            parts = re.split(r",|/|\band\b", lab, flags=re.I)
            return [p.strip() for p in parts if len(p.strip()) > 1][:6]
        return [lab]
    # filename fallback
    stem = Path(filename).stem
    stem = re.sub(r"_criteria.*$", "", stem, flags=re.I)
    stem = re.sub(r"_pa.*$", "", stem, flags=re.I)
    stem = re.sub(r"^\d{6,8}[-_]?", "", stem)
    stem = re.sub(r"^ccfu_[^_]+_", "", stem)
    return [stem.replace("_", " ").replace("-", " ").title()]


def build_text_only_pack(
    drug_name: str,
    *,
    generic: str | None,
    effective_date: str | None,
    citation: str,
    criteria_pdf: str,
    section: str | None,
    required_facts: list[str],
    therapeutic_class: str | None,
) -> dict:
    pack: dict = {
        "drug": {
            "name": drug_name,
        },
        "source": {
            "payer": "alaska_medicaid",
            "list": f"{drug_name} Criteria",
            "effective_date": effective_date or "1970-01-01",
            "citation": citation,
            "criteria_pdf": criteria_pdf,
        },
        "requires_pa": True,
        "pdl_status": "unknown",
        "encoding_status": "text_only",
        "criteria": [],
        "alternatives": [],
        "notes": [
            "Criteria PDF archived and text extracted; predicate encoding pending. "
            "evaluate() must not auto-pass — returns need_info / encoding_incomplete."
        ],
    }
    if generic:
        pack["drug"]["generic_name"] = generic
    if therapeutic_class:
        pack["drug"]["therapeutic_class"] = therapeutic_class
    if section:
        pack["drug"]["therapeutic_class"] = pack["drug"].get("therapeutic_class") or slugify(section)
    # Optional need_info hint clause listing inferred facts — but empty criteria is preferred
    # per product guidance. Store inferred facts separately for UI.
    pack["inferred_required_facts"] = required_facts
    return pack


def build_dupixent_pack(manifest_entry: dict, text: str) -> dict:
    """Structured predicates clearly stated in AK Dupixent criteria PDF."""
    eff = "2025-11-01"
    pdf = manifest_entry["filename"]
    url = manifest_entry["source_url"]
    # Indication-specific FDA ages from the PDF's FDA INDICATIONS section + approval criteria
    # Approval criteria repeatedly require "Patient meets FDA labeled age"
    indication_age = {
        "atopic_dermatitis": 0.5,  # 6 months
        "asthma": 6,
        "crswnp": 12,
        "eosinophilic_esophagitis": 1,
        "prurigo_nodularis": 18,
        "copd": 18,
        "chronic_spontaneous_urticaria": 12,
        "bullous_pemphigoid": 18,
    }
    age_any = {
        "op": "any",
        "args": [
            {
                "op": "all",
                "args": [
                    {"op": "eq", "fact": "indication", "value": ind},
                    {"op": "gte", "fact": "age_years", "value": age},
                ],
            }
            for ind, age in indication_age.items()
        ],
    }
    return {
        "drug": {
            "name": "Dupixent",
            "generic_name": "dupilumab",
            "therapeutic_class": "respiratory",
        },
        "source": {
            "payer": "alaska_medicaid",
            "list": "Dupixent Criteria",
            "effective_date": eff,
            "citation": url,
            "criteria_pdf": f"data/alaska/raw/{pdf}",
        },
        "requires_pa": True,
        "pdl_status": "unknown",
        "encoding_status": "partial",
        "criteria": [
            {
                "id": "indication_fda_labeled",
                "text": (
                    "Indication must be one of the FDA-labeled uses listed in Alaska Medicaid "
                    "Dupixent Prior Authorization Criteria (AD, asthma, CRSwNP, EoE, PN, COPD, CSU, BP)."
                ),
                "citation": f"{url}#fda-indications",
                "required_facts": ["indication"],
                "predicate": {
                    "op": "in",
                    "fact": "indication",
                    "values": list(indication_age.keys()),
                },
            },
            {
                "id": "fda_labeled_age_for_indication",
                "text": (
                    "Patient meets FDA labeled age for the requested indication "
                    "(AD ≥6 months; asthma ≥6y; CRSwNP/CSU ≥12y; EoE ≥1y & weight rules separate; "
                    "PN/COPD/BP adult)."
                ),
                "citation": f"{url}#approval-criteria",
                "required_facts": ["indication", "age_years"],
                "predicate": age_any,
            },
            {
                "id": "prescriber_specialty",
                "text": (
                    "Prescribed by or in consultation with an appropriate specialist "
                    "(indication-dependent: allergist/immunologist/dermatologist/pulmonologist/ENT)."
                ),
                "citation": f"{url}#approval-criteria",
                "required_facts": ["prescriber_specialty"],
                "predicate": {
                    "op": "in",
                    "fact": "prescriber_specialty",
                    "values": [
                        "allergist",
                        "immunologist",
                        "dermatologist",
                        "pulmonologist",
                        "ent",
                    ],
                },
            },
        ],
        "alternatives": ["xolair"],
        "notes": [
            "Partial encoding from AK Dupixent criteria PDF (effective 11/1/2025). "
            "Step-therapy / labs / severity documentation remain in criteria_text; "
            "not yet expressed as predicates.",
        ],
    }


def build_xolair_pack(manifest_entry: dict, text: str) -> dict:
    eff = "2024-06-01"
    pdf = manifest_entry["filename"]
    url = manifest_entry["source_url"]
    indication_age = {
        "asthma": 6,
        "chronic_spontaneous_urticaria": 12,
        "crswnp": 18,
        "ige_mediated_food_allergy": 1,
    }
    age_any = {
        "op": "any",
        "args": [
            {
                "op": "all",
                "args": [
                    {"op": "eq", "fact": "indication", "value": ind},
                    {"op": "gte", "fact": "age_years", "value": age},
                ],
            }
            for ind, age in indication_age.items()
        ],
    }
    return {
        "drug": {
            "name": "Xolair",
            "generic_name": "omalizumab",
            "therapeutic_class": "respiratory",
        },
        "source": {
            "payer": "alaska_medicaid",
            "list": "Xolair Criteria",
            "effective_date": eff,
            "citation": url,
            "criteria_pdf": f"data/alaska/raw/{pdf}",
        },
        "requires_pa": True,
        "pdl_status": "unknown",
        "encoding_status": "partial",
        "criteria": [
            {
                "id": "indication_fda_labeled",
                "text": (
                    "Indication must be moderate-to-severe persistent asthma, CRSwNP, "
                    "IgE-mediated food allergy, or chronic spontaneous urticaria per AK Xolair criteria."
                ),
                "citation": f"{url}#fda-indications",
                "required_facts": ["indication"],
                "predicate": {
                    "op": "in",
                    "fact": "indication",
                    "values": list(indication_age.keys()),
                },
            },
            {
                "id": "age_for_indication",
                "text": (
                    "Patient age meets indication minimum: asthma ≥6y; CSU ≥12y; "
                    "nasal polyps ≥18y; IgE-mediated food allergy ≥1y."
                ),
                "citation": f"{url}#approval-criteria",
                "required_facts": ["indication", "age_years"],
                "predicate": age_any,
            },
            {
                "id": "prescriber_specialty",
                "text": "Prescribed by or in consultation with an allergist, immunologist, or pulmonologist.",
                "citation": f"{url}#approval-criteria",
                "required_facts": ["prescriber_specialty"],
                "predicate": {
                    "op": "in",
                    "fact": "prescriber_specialty",
                    "values": ["allergist", "immunologist", "pulmonologist"],
                },
            },
        ],
        "alternatives": ["dupixent"],
        "notes": [
            "Partial encoding from AK Xolair criteria PDF (effective 6/1/2024). "
            "IgE thresholds, skin-test, and prior controller therapy clauses remain text-only.",
        ],
    }


def main() -> int:
    CRITERIA_TEXT.mkdir(parents=True, exist_ok=True)
    RULE_PACKS.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    by_name = {m["filename"]: m for m in manifest if m.get("filename")}

    # --- PA / Interim lists ---
    pa_drugs: list[dict] = []
    for fname, kind in [
        ("prior-authorization-list-20250418.pdf", "pa_list_20250418"),
        ("ada-interim-prior-authorization-list-20260728.pdf", "interim_pa_20260728"),
    ]:
        path = RAW / fname
        if path.exists():
            text = pdftotext(path)
            (PARSED / f"{kind}_text.txt").write_text(text, encoding="utf-8")
            pa_drugs.extend(parse_pa_list(text, fname, kind))

    # --- PDL ---
    pdl_rows: list[dict] = []
    pdl_file = "pdl_effective-date_20260601.pdf"
    if (RAW / pdl_file).exists():
        pdl_text = pdftotext(RAW / pdl_file)
        (PARSED / "pdl_20260601_text.txt").write_text(pdl_text, encoding="utf-8")
        pdl_rows = parse_pdl(pdl_text, pdl_file)

    # --- Max units (latest) ---
    max_rows: list[dict] = []
    max_file = "maximum-units-med-list-2-25-2025.pdf"
    if (RAW / max_file).exists():
        max_text = pdftotext(RAW / max_file)
        (PARSED / "max_units_20250225_text.txt").write_text(max_text, encoding="utf-8")
        max_rows = parse_max_units(max_text, max_file)

    # Build unified drug index
    index: dict[str, dict] = {}

    def upsert(slug: str, **fields: object) -> None:
        if slug not in index:
            index[slug] = {"slug": slug, "names": [], "sources": []}
        entry = index[slug]
        for k, v in fields.items():
            if k == "name" and isinstance(v, str):
                if v not in entry["names"]:
                    entry["names"].append(v)
                entry.setdefault("primary_name", v)
            elif k == "source" and isinstance(v, str):
                if v not in entry["sources"]:
                    entry["sources"].append(v)
            elif v is not None:
                entry[k] = v

    for d in pa_drugs:
        upsert(
            d["slug"],
            name=d["name"],
            requires_pa=True,
            source=d["source_list"],
            pa_list_file=d["source_file"],
        )
    for r in pdl_rows:
        upsert(
            r["slug"],
            name=r["brand_name"],
            pdl_status=r["pdl_status"],
            generic_name=r.get("generic_name"),
            source="pdl_20260601",
            market_basket=r.get("market_basket"),
        )
    for r in max_rows:
        upsert(
            r["slug"],
            name=r["brand_name"],
            max_units_30_days=r.get("max_units_30_days"),
            source="max_units_20250225",
        )

    drug_index = {
        "generated": DOWNLOAD_DATE,
        "payer": "alaska_medicaid",
        "counts": {
            "pa_list_entries": len(pa_drugs),
            "pdl_rows": len(pdl_rows),
            "max_units_rows": len(max_rows),
            "unique_slugs": len(index),
        },
        "drugs": sorted(index.values(), key=lambda x: x.get("primary_name", x["slug"]).lower()),
    }
    (PARSED / "drug_index.json").write_text(json.dumps(drug_index, indent=2) + "\n", encoding="utf-8")
    (PARSED / "pdl_index.json").write_text(
        json.dumps({"generated": DOWNLOAD_DATE, "rows": pdl_rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    (PARSED / "max_units_index.json").write_text(
        json.dumps({"generated": DOWNLOAD_DATE, "rows": max_rows}, indent=2) + "\n",
        encoding="utf-8",
    )

    # --- Criteria PDFs ---
    criteria_entries = [m for m in manifest if m.get("category") == "criteria" and m.get("status") == "ok"]
    text_only = 0
    partial = 0
    fully = 0
    failed_parse = 0

    # Clear old example placeholders
    for old in PARSED.glob("example-*.json"):
        old.unlink()

    for entry in criteria_entries:
        fname = entry["filename"]
        path = RAW / fname
        text = pdftotext(path)
        if not text.strip():
            failed_parse += 1
            continue
        meta = extract_header_meta(text)
        drugs = drug_names_from_criteria_label(entry.get("label") or "", fname, meta)
        facts = infer_required_facts(text)
        eff = meta.get("effective_date") or entry.get("effective_date")
        # Year-only dates from download heuristic: prefer PDF Effective: line
        if eff and eff.endswith("-01-01") and meta.get("effective_date"):
            eff = meta["effective_date"]

        # Special full/partial packs
        lower_names = [d.lower() for d in drugs]
        special_slug = None
        pack = None
        if any("dupixent" in n for n in lower_names) or "dupixent" in fname.lower():
            pack = build_dupixent_pack(entry, text)
            special_slug = "dupixent"
            partial += 1
        elif any("xolair" in n for n in lower_names) or "xolair" in fname.lower():
            pack = build_xolair_pack(entry, text)
            special_slug = "xolair"
            partial += 1

        for drug_name in drugs:
            slug = special_slug or slugify(drug_name)
            ct = {
                "slug": slug,
                "drug_name": drug_name,
                "generic_name": meta.get("generic_name"),
                "source_url": entry["source_url"],
                "source_file": fname,
                "sha256": entry.get("sha256"),
                "effective_date": eff,
                "section": entry.get("section"),
                "extracted_text": text,
                "inferred_required_facts": facts,
                "download_date": DOWNLOAD_DATE,
            }
            (CRITERIA_TEXT / f"{slug}.json").write_text(
                json.dumps(ct, indent=2) + "\n", encoding="utf-8"
            )

            if pack and slug == special_slug:
                out_pack = pack
            else:
                out_pack = build_text_only_pack(
                    drug_name,
                    generic=meta.get("generic_name"),
                    effective_date=eff,
                    citation=entry["source_url"],
                    criteria_pdf=f"data/alaska/raw/{fname}",
                    section=entry.get("section"),
                    required_facts=facts,
                    therapeutic_class=None,
                )
                text_only += 1

            (RULE_PACKS / f"{slug}.json").write_text(
                json.dumps(out_pack, indent=2) + "\n", encoding="utf-8"
            )
            # Convenience copies for primary brands at parsed/
            if slug in ("dupixent", "xolair"):
                (PARSED / f"{slug}.json").write_text(
                    json.dumps(out_pack, indent=2) + "\n", encoding="utf-8"
                )

    # Encoding status report
    status = {
        "generated": DOWNLOAD_DATE,
        "timezone": "America/New_York",
        "hub": "https://health.alaska.gov/en/education/prior-authorization-medication/",
        "downloads": {
            "ok": sum(1 for m in manifest if m.get("status") == "ok"),
            "failed": sum(1 for m in manifest if m.get("status") == "failed"),
            "skipped": sum(1 for m in manifest if m.get("status") == "skipped"),
            "total_bytes": sum(m.get("bytes") or 0 for m in manifest if m.get("status") == "ok"),
            "criteria_pdfs": len(criteria_entries),
        },
        "parsed": {
            "drug_index_unique_slugs": len(index),
            "pa_list_entries": len(pa_drugs),
            "pdl_rows": len(pdl_rows),
            "max_units_rows": len(max_rows),
            "criteria_text_files": len(list(CRITERIA_TEXT.glob("*.json"))),
            "rule_packs": len(list(RULE_PACKS.glob("*.json"))),
            "fully_encoded": fully,
            "partially_encoded": partial,
            "text_only": text_only,
            "criteria_pdf_text_extract_failures": failed_parse,
        },
        "blockers": [
            {
                "item": "Drug Lookup Tool",
                "url": "https://ak.primetherapeutics.com/provider/",
                "reason": "Prime Therapeutics JS portal; no static export on hub",
            },
            {
                "item": "CoverMyMeds ePA",
                "url": "https://www.covermymeds.health/prior-authorization-forms/prime",
                "reason": "External ePA portal; out of scope for criteria ingest",
            },
            {
                "item": "Predicate encoding coverage",
                "reason": (
                    "Most criteria PDFs are text_only. Only Dupixent and Xolair have partial "
                    "structured predicates (indication + age + specialty). Step-therapy and labs pending."
                ),
            },
        ],
        "notes": [
            "Hub labels 'Prior Authorization Medication List' file content title is still "
            "'Interim Prior Authorization List' (updated 04/18/2025); separate Interim file "
            "updated 07/28/2026 also archived.",
            "evaluate() returns need_info for encoding_status text_only / empty criteria — never auto-pass.",
        ],
    }
    (PARSED / "ENCODING_STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        "# Alaska Medicaid encoding status",
        "",
        f"Generated: {DOWNLOAD_DATE} (America/New_York)",
        "",
        f"Source hub: {status['hub']}",
        "",
        "## Downloads",
        "",
        f"- OK: **{status['downloads']['ok']}**",
        f"- Failed: **{status['downloads']['failed']}**",
        f"- Skipped: **{status['downloads']['skipped']}** (Drug Lookup Tool, CoverMyMeds ePA)",
        f"- Total bytes: **{status['downloads']['total_bytes']:,}**",
        f"- Criteria PDFs: **{status['downloads']['criteria_pdfs']}**",
        "",
        "## Parsed",
        "",
        f"- Unique drugs in index: **{status['parsed']['drug_index_unique_slugs']}**",
        f"- PA list entries (both dated lists): **{status['parsed']['pa_list_entries']}**",
        f"- PDL rows: **{status['parsed']['pdl_rows']}**",
        f"- Max units rows (latest 2025-02-25): **{status['parsed']['max_units_rows']}**",
        f"- Criteria text JSON files: **{status['parsed']['criteria_text_files']}**",
        f"- Rule packs: **{status['parsed']['rule_packs']}**",
        f"- Fully encoded (all clauses as predicates): **{status['parsed']['fully_encoded']}**",
        f"- Partially encoded: **{status['parsed']['partially_encoded']}** (Dupixent, Xolair)",
        f"- Text-only (requires_pa, encoding pending): **{status['parsed']['text_only']}**",
        f"- Criteria PDF text extract failures: **{status['parsed']['criteria_pdf_text_extract_failures']}**",
        "",
        "## Blockers",
        "",
    ]
    for b in status["blockers"]:
        md_lines.append(f"- **{b['item']}**: {b.get('reason', '')}" + (f" ({b['url']})" if b.get("url") else ""))
    md_lines += [
        "",
        "## Honesty note",
        "",
        "Do **not** treat text-only packs as coverage decisions. The engine returns "
        "`need_info` with an `encoding_incomplete` note when `encoding_status` is "
        "`text_only` or criteria are empty.",
        "",
        "## Next encoding candidates",
        "",
        "Prioritize high-volume respiratory biologics already partially done, then "
        "IL-5 inhibitors, CGRP, Entyvio/Stelara/Skyrizi class, Hep C DAA, and growth hormone.",
        "",
    ]
    (PARSED / "ENCODING_STATUS.md").write_text("\n".join(md_lines), encoding="utf-8")
    # Also copy to docs-friendly path at alaska root
    (PARSED.parent / "ENCODING_STATUS.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(json.dumps(status["parsed"], indent=2))
    print("Wrote", PARSED / "ENCODING_STATUS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
