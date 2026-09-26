
"""Minimal loaders for Vercel demo (bundled JSON only)."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PARSED = ROOT / "data" / "alaska" / "parsed"

@lru_cache(maxsize=1)
def _drug_index() -> dict[str, Any]:
    return json.loads((PARSED / "drug_index.json").read_text())

@lru_cache(maxsize=1)
def load_rule_pack_catalog() -> dict[str, Any]:
    path = PARSED / "rule_packs_all.json"
    data = json.loads(path.read_text())
    # catalog may be {slug: pack} or {"packs": [...]}
    if isinstance(data, dict) and "packs" not in data and any(isinstance(v, dict) and "criteria" in v for v in data.values()):
        return data
    if isinstance(data, dict) and "packs" in data:
        return {p.get("slug") or p.get("drug", {}).get("name", "").lower(): p for p in data["packs"]}
    return data if isinstance(data, dict) else {}

def search_drugs(q: str, limit: int = 25) -> list[dict[str, Any]]:
    qn = (q or "").strip().lower()
    out = []
    for d in _drug_index().get("drugs") or []:
        names = [d.get("primary_name") or ""] + list(d.get("names") or [])
        hay = " ".join(names).lower() + " " + (d.get("slug") or "")
        if qn in hay:
            out.append({"slug": d.get("slug"), "name": d.get("primary_name") or (d.get("names") or [""])[0], "requires_pa": d.get("requires_pa"), "pdl_status": d.get("pdl_status")})
        if len(out) >= limit:
            break
    return out

def get_rule_pack(slug: str):
    catalog = load_rule_pack_catalog()
    # direct
    if slug in catalog:
        return slug, catalog[slug]
    # strip formulation suffixes
    base = slug.split("-")[0] if slug else slug
    for key, pack in catalog.items():
        if key == base or key.startswith(base):
            return key, pack
        names = pack.get("drug", {}) if isinstance(pack.get("drug"), dict) else {}
        if (names.get("name") or "").lower().replace(" ", "-") == base:
            return key, pack
    # try primary name match via index
    for d in _drug_index().get("drugs") or []:
        if d.get("slug") == slug:
            for key in catalog:
                if key in slug or slug.startswith(key):
                    return key, catalog[key]
    return None

def drug_detail(slug: str) -> dict[str, Any] | None:
    for d in _drug_index().get("drugs") or []:
        if d.get("slug") == slug:
            resolved = get_rule_pack(slug)
            pack = resolved[1] if resolved else {}
            pack_slug = resolved[0] if resolved else None
            facts = set()
            for c in pack.get("criteria") or []:
                for f in c.get("required_facts") or []:
                    facts.add(f)
            return {
                **d,
                "rule_pack_slug": pack_slug,
                "encoding_status": pack.get("encoding_status"),
                "requires_pa": d.get("requires_pa", pack.get("requires_pa")),
                "pdl_status": d.get("pdl_status", pack.get("pdl_status")),
                "inferred_required_facts": sorted(facts),
                "fact_fields": [
                    {"key": f, "label": f.replace("_", " ").title(), "type": "number" if f == "age_years" else "text"}
                    for f in sorted(facts)
                ],
                "criteria_clauses": pack.get("criteria") or [],
                "alternatives": pack.get("alternatives") or [],
                "notes": pack.get("notes") or [],
                "source": pack.get("source") or {},
            }
    return None
