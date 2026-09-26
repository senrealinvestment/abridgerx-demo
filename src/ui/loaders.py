"""Minimal loaders for Vercel demo (bundled JSON only)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PARSED = ROOT / "data" / "alaska" / "parsed"

# Age bands aligned to Dupixent/Xolair gte thresholds (0.5, 1, 6, 12, 18).
# Each option value is the band minimum so evaluate() gte checks behave correctly.
AGE_BAND_OPTIONS: list[dict[str, str]] = [
    {"value": "0", "label": "Under 6 months"},
    {"value": "0.5", "label": "6 months – under 1 year"},
    {"value": "1", "label": "1–5 years"},
    {"value": "6", "label": "6–11 years"},
    {"value": "12", "label": "12–17 years"},
    {"value": "18", "label": "18+ years"},
]

DEFAULT_SPECIALTY_OPTIONS: list[str] = [
    "dermatologist",
    "allergist",
    "immunologist",
    "pulmonologist",
    "ent",
    "primary_care",
    "other",
]


@lru_cache(maxsize=1)
def _drug_index() -> dict[str, Any]:
    return json.loads((PARSED / "drug_index.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_rule_pack_catalog() -> dict[str, Any]:
    path = PARSED / "rule_packs_all.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        isinstance(data, dict)
        and "packs" not in data
        and any(isinstance(v, dict) and "criteria" in v for v in data.values())
    ):
        return data
    if isinstance(data, dict) and "packs" in data:
        return {
            p.get("slug") or p.get("drug", {}).get("name", "").lower(): p
            for p in data["packs"]
        }
    return data if isinstance(data, dict) else {}


def search_drugs(q: str, limit: int = 25) -> list[dict[str, Any]]:
    qn = (q or "").strip().lower()
    out: list[dict[str, Any]] = []
    catalog = load_rule_pack_catalog()
    for d in _drug_index().get("drugs") or []:
        names = [d.get("primary_name") or ""] + list(d.get("names") or [])
        hay = " ".join(names).lower() + " " + (d.get("slug") or "")
        if qn not in hay:
            continue
        slug = d.get("slug") or ""
        pack_slug = None
        if slug in catalog:
            pack_slug = slug
        else:
            base = slug.split("-")[0]
            if base in catalog:
                pack_slug = base
        out.append(
            {
                "slug": slug,
                "primary_name": d.get("primary_name")
                or (d.get("names") or [""])[0],
                "name": d.get("primary_name") or (d.get("names") or [""])[0],
                "requires_pa": d.get("requires_pa"),
                "pdl_status": d.get("pdl_status"),
                "max_units_30_days": d.get("max_units_30_days"),
                "rule_pack_slug": pack_slug,
                "encoding_status": (
                    catalog[pack_slug].get("encoding_status") if pack_slug else None
                ),
            }
        )
        if len(out) >= limit:
            break
    return out


def get_rule_pack(slug: str):
    catalog = load_rule_pack_catalog()
    if slug in catalog:
        return slug, catalog[slug]
    base = slug.split("-")[0] if slug else slug
    for key, pack in catalog.items():
        if key == base or key.startswith(base + "-") or slug.startswith(key + "-"):
            return key, pack
        names = pack.get("drug", {}) if isinstance(pack.get("drug"), dict) else {}
        if (names.get("name") or "").lower().replace(" ", "-") == base:
            return key, pack
    for d in _drug_index().get("drugs") or []:
        if d.get("slug") == slug:
            for key in catalog:
                if key in slug or slug.startswith(key):
                    return key, catalog[key]
    return None


def _walk_predicates(pred: dict[str, Any] | None):
    if not isinstance(pred, dict) or not pred:
        return
    yield pred
    for arg in pred.get("args") or []:
        yield from _walk_predicates(arg)


def _collect_choice_values(pack: dict[str, Any], fact: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for clause in pack.get("criteria") or []:
        for pred in _walk_predicates(clause.get("predicate")):
            if pred.get("fact") != fact:
                continue
            op = pred.get("op")
            if op in ("in", "choice"):
                for v in pred.get("values") or []:
                    s = str(v)
                    if s not in seen:
                        seen.add(s)
                        ordered.append(s)
            elif op == "eq" and "value" in pred:
                s = str(pred["value"])
                if s not in seen:
                    seen.add(s)
                    ordered.append(s)
    return ordered


def required_facts_for_pack(pack: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    for clause in pack.get("criteria") or []:
        for f in clause.get("required_facts") or []:
            if f not in seen:
                seen.add(f)
                facts.append(f)
    for f in pack.get("inferred_required_facts") or []:
        if f not in seen:
            seen.add(f)
            facts.append(f)
    return facts


def build_fact_fields(pack: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for fact in required_facts_for_pack(pack):
        field: dict[str, Any] = {"key": fact, "label": fact.replace("_", " ").title()}
        if fact == "age_years":
            field["type"] = "select"
            field["label"] = "Age"
            field["options"] = list(AGE_BAND_OPTIONS)
            field["option_style"] = "age_bands"
            field["hint"] = (
                "Band value sets age_years to the band minimum for gte checks "
                "(0 / 0.5 / 1 / 6 / 12 / 18)."
            )
        elif fact == "indication":
            opts = _collect_choice_values(pack, "indication")
            if opts:
                field["type"] = "select"
                field["options"] = opts
                field["free_text"] = False
            else:
                field["type"] = "text"
                field["free_text"] = True
        elif fact in ("prescriber_specialty", "provider_type", "specialty"):
            field["type"] = "select"
            field["label"] = "Provider / specialty"
            opts = _collect_choice_values(pack, "prescriber_specialty")
            field["options"] = opts or list(DEFAULT_SPECIALTY_OPTIONS)
            field["free_text"] = False
        else:
            field["type"] = "text"
        fields.append(field)
    return fields


def drug_detail(slug: str) -> dict[str, Any] | None:
    drug = next((d for d in (_drug_index().get("drugs") or []) if d.get("slug") == slug), None)
    resolved = get_rule_pack(slug)
    pack = resolved[1] if resolved else None
    pack_slug = resolved[0] if resolved else None

    if drug is None and pack is None:
        return None

    encoding = (pack or {}).get("encoding_status")
    can_evaluate = encoding in ("full", "partial") and bool((pack or {}).get("criteria"))
    citations: list[str] = []
    if pack and pack.get("source", {}).get("citation"):
        citations.append(pack["source"]["citation"])
    for clause in (pack or {}).get("criteria") or []:
        c = clause.get("citation")
        if c and c not in citations:
            citations.append(c)

    primary = (
        (drug or {}).get("primary_name")
        or (pack or {}).get("drug", {}).get("name")
        or slug
    )
    fact_fields = build_fact_fields(pack) if pack else []

    return {
        "slug": slug,
        "primary_name": primary,
        "generic_name": (drug or {}).get("generic_name")
        or (pack or {}).get("drug", {}).get("generic_name"),
        "names": (drug or {}).get("names") or [primary],
        "requires_pa": bool(
            (drug or {}).get("requires_pa")
            if drug and "requires_pa" in drug
            else (pack or {}).get("requires_pa", False)
        ),
        "pdl_status": (drug or {}).get("pdl_status") or (pack or {}).get("pdl_status"),
        "max_units_30_days": (drug or {}).get("max_units_30_days"),
        "market_basket": (drug or {}).get("market_basket")
        or (pack or {}).get("drug", {}).get("therapeutic_class"),
        "rule_pack_slug": pack_slug,
        "encoding_status": encoding,
        "can_evaluate": can_evaluate,
        "citations": citations,
        "source": (pack or {}).get("source") or {},
        "notes": (pack or {}).get("notes") or [],
        "criteria_clauses": [
            {
                "id": c.get("id"),
                "text": c.get("text"),
                "citation": c.get("citation"),
                "required_facts": c.get("required_facts") or [],
            }
            for c in (pack or {}).get("criteria") or []
        ],
        "fact_fields": fact_fields,
        "inferred_required_facts": required_facts_for_pack(pack) if pack else [],
        "alternatives": (pack or {}).get("alternatives") or [],
    }
