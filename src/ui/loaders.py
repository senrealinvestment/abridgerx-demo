"""Load Alaska Medicaid drug index, rule packs, and criteria text for the UI."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PARSED = ROOT / "data" / "alaska" / "parsed"
RULE_PACKS_DIR = PARSED / "rule_packs"
CRITERIA_TEXT_DIR = PARSED / "criteria_text"
DRUG_INDEX_PATH = PARSED / "drug_index.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_maybe_gz(path: Path) -> Any:
    """Read JSON, or gzip-compressed JSON when path ends with .gz / sibling .gz exists."""
    import gzip

    if path.suffix == ".gz" or str(path).endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    gz = Path(str(path) + ".gz")
    if not path.exists() and gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            return json.load(f)
    return _read_json(path)


@lru_cache(maxsize=1)
def load_drug_index() -> dict[str, Any]:
    return _read_json_maybe_gz(DRUG_INDEX_PATH)


@lru_cache(maxsize=1)
def load_rule_pack_catalog() -> dict[str, dict[str, Any]]:
    """slug -> rule pack. Prefer bundled rule_packs_all(.json|.json.gz), else directory."""
    bundled = PARSED / "rule_packs_all.json"
    bundled_gz = PARSED / "rule_packs_all.json.gz"
    if bundled.exists() or bundled_gz.exists():
        data = _read_json_maybe_gz(bundled if bundled.exists() else bundled_gz)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]

    catalog: dict[str, dict[str, Any]] = {}
    if RULE_PACKS_DIR.is_dir():
        for path in RULE_PACKS_DIR.glob("*.json"):
            pack = _read_json(path)
            catalog[path.stem] = pack
    # Top-level authored packs (dupixent.json, xolair.json) — same content as rule_packs
    for path in PARSED.glob("*.json"):
        if path.name in (
            "drug_index.json",
            "pdl_index.json",
            "max_units_index.json",
            "ENCODING_STATUS.json",
            "rule_packs_all.json",
            "criteria_text_all.json",
        ):
            continue
        if path.stem not in catalog:
            data = _read_json(path)
            if isinstance(data, dict) and "drug" in data and "criteria" in data:
                catalog[path.stem] = data
    return catalog


@lru_cache(maxsize=1)
def load_criteria_text_index() -> dict[str, dict[str, Any]]:
    bundled = PARSED / "criteria_text_all.json"
    bundled_gz = PARSED / "criteria_text_all.json.gz"
    if bundled.exists() or bundled_gz.exists():
        data = _read_json_maybe_gz(bundled if bundled.exists() else bundled_gz)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]

    out: dict[str, dict[str, Any]] = {}
    if not CRITERIA_TEXT_DIR.is_dir():
        return out
    for path in CRITERIA_TEXT_DIR.glob("*.json"):
        out[path.stem] = _read_json(path)
    return out


def _normalize(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def resolve_rule_pack_slug(drug_slug: str) -> str | None:
    """Map a drug_index slug to a rule_pack slug when possible."""
    catalog = load_rule_pack_catalog()
    if drug_slug in catalog:
        return drug_slug

    # Longest pack slug that is a prefix of the drug slug (e.g. dupixent-pen → dupixent)
    best: str | None = None
    for pack_slug in catalog:
        if drug_slug == pack_slug or drug_slug.startswith(pack_slug + "-"):
            if best is None or len(pack_slug) > len(best):
                best = pack_slug
    if best:
        return best

    # First hyphen segment (xolair-vial-sub-q → xolair)
    base = drug_slug.split("-")[0]
    if base in catalog:
        return base

    # Name-normalized match against pack drug names
    drugs = load_drug_index()["drugs"]
    drug = next((d for d in drugs if d["slug"] == drug_slug), None)
    if drug:
        candidates = [_normalize(n) for n in drug.get("names") or []]
        candidates.append(_normalize(drug.get("primary_name") or ""))
        for pack_slug, pack in catalog.items():
            pname = _normalize(pack.get("drug", {}).get("name") or pack_slug)
            if pname and pname in candidates:
                return pack_slug
            if any(pname and (pname == c or c.startswith(pname)) for c in candidates if c):
                return pack_slug
    return None


def get_rule_pack(slug_or_drug_slug: str) -> tuple[str, dict[str, Any]] | None:
    catalog = load_rule_pack_catalog()
    if slug_or_drug_slug in catalog:
        return slug_or_drug_slug, catalog[slug_or_drug_slug]
    resolved = resolve_rule_pack_slug(slug_or_drug_slug)
    if resolved and resolved in catalog:
        return resolved, catalog[resolved]
    return None


def get_criteria_text(pack_slug: str) -> dict[str, Any] | None:
    return load_criteria_text_index().get(pack_slug)


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


# Age bands aligned to Dupixent/Xolair gte thresholds (0.5, 1, 6, 12, 18).
# Each option value is the band minimum so evaluate() gte checks behave correctly
# for every age in that band relative to those thresholds.
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
    "rheumatologist",
    "neurologist",
    "primary_care",
    "other",
]

YES_NO_OPTIONS: list[dict[str, str]] = [
    {"value": "yes", "label": "Yes"},
    {"value": "no", "label": "No"},
]

YES_NO_UNKNOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "yes", "label": "Yes"},
    {"value": "no", "label": "No"},
    {"value": "unknown", "label": "Unknown"},
]

# Fact keys that are multi-select (therapy / agent lists).
MULTI_FACT_KEYS = {
    "prior_therapy_failures",
    "failed_therapies",
    "prior_therapies",
    "previous_therapies",
    "concomitant_medications",
}

BOOLEAN_FACT_HINTS = (
    "has_",
    "is_",
    "was_",
    "_documented",
    "_present",
    "_confirmed",
    "continuation_of_care",
    "positive_clinical_response",
)


def _walk_predicates(pred: dict[str, Any] | None):
    """Yield predicate nodes depth-first (including nested any/all args)."""
    if not isinstance(pred, dict) or not pred:
        return
    yield pred
    for arg in pred.get("args") or []:
        yield from _walk_predicates(arg)


def _collect_choice_values(pack: dict[str, Any], fact: str) -> list[str]:
    """Union of values from in/choice predicates (and eq) for a fact across the pack."""
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


def indication_options_for_pack(pack: dict[str, Any]) -> list[str] | None:
    """If any clause constrains indication with in/choice/eq, return those values."""
    opts = _collect_choice_values(pack, "indication")
    return opts or None


def specialty_options_for_pack(pack: dict[str, Any]) -> list[str] | None:
    opts = _collect_choice_values(pack, "prescriber_specialty")
    return opts or None


def _slugify_option(label: str, max_len: int = 56) -> str:
    import re

    s = re.sub(r"\([^)]*\)", "", label.lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "option")[:max_len]


def _clean_label(s: str) -> str:
    import re

    s = re.sub(r"\s+", " ", s).strip(" .;,:")
    s = s.strip("“”\"'")
    s = re.sub(r"\s+AND,?$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+OR,?$", "", s, flags=re.I).strip()
    return s


def parse_indications_from_criteria_text(text: str) -> list[dict[str, str]]:
    """Derive indication select options from archived criteria PDF text."""
    import re

    if not text:
        return []
    stop = re.compile(
        r"^(Any diagnosis|Concomitant|The patient meets|Page |Version |ALASKA|"
        r"Criteria for|Table \d|Dosage|Unless|Patient has been|Complete |"
        r"Monitoring |Previous |Requested )",
        re.I,
    )
    opts: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: str | None = None) -> None:
        label = _clean_label(label)
        if len(label) < 4 or len(label) > 140:
            return
        if stop.search(label):
            return
        if re.search(r"\b(AND;|OR;|must include|Monitoring plan)\b", label):
            return
        if label.lower().endswith((" or", " and", " of", " for", " with", " aged", " who")):
            return
        # Prefer short diagnosis titles; drop truncated mid-sentence FDA blurbs
        if " for the treatment of" in label.lower() or " as an add-on" in label.lower():
            # Keep the leading disease name before the dash/emdash
            head = re.split(r"\s*[–—\-]\s*", label, maxsplit=1)[0].strip()
            if len(head) >= 4:
                label = head
        val = value or _slugify_option(label)
        key = val.lower()
        if key in seen or label.lower() in seen:
            return
        seen.add(key)
        seen.add(label.lower())
        opts.append({"value": val, "label": label})

    for m in re.finditer(r'indicated for[:\s]+[“"]([^”"]+)[”"]', text, re.I | re.S):
        chunk = re.sub(r"\s+", " ", m.group(1))
        parts = re.split(r",\s*(?:and\s+)?|(?<=\w)\s+and\s+", chunk)
        for p in parts:
            p = re.sub(
                r"^(?:management of|treatment of|adjunctive therapy for)\s+",
                "",
                p,
                flags=re.I,
            )
            add(p)

    m = re.search(
        r"(?:FDA\s+INDICATIONS(?:\s+AND\s+USAGE)?|Indications)\s*:?\s*(.*?)"
        r"(?=\n\s*(?:APPROVAL CRITERIA|Criteria for Approval|Dosage Form|Table \d|Page \d))",
        text,
        re.I | re.S,
    )
    block = m.group(1) if m else ""
    m2 = re.search(
        r"one of the following diagnoses\s*:?\s*(.*?)"
        r"(?=\n\s*(?:The patient meets|Table \d|Criteria for|Page \d))",
        text,
        re.I | re.S,
    )
    if m2:
        block += "\n" + m2.group(1)

    for line in block.splitlines():
        mm = re.match(r"^\s*[•▪◦\-–]\s*(.+)$", line)
        if not mm:
            continue
        item = mm.group(1)
        if re.search(r"\bin adults\b", item, re.I):
            item = re.split(r"\s+in adults\b", item, maxsplit=1, flags=re.I)[0]
        add(item)

    for mm in re.finditer(
        r"(?m)^\s{0,8}([A-Z][A-Za-z][A-Za-z0-9 \-/]*\([A-Za-z]{2,8}\))\s*$",
        text,
    ):
        add(mm.group(1))

    if re.search(r"continuation of care", text, re.I):
        add("Continuation of care", "continuation_of_care")

    return opts[:18]


def parse_therapies_from_criteria_text(text: str) -> list[dict[str, str]]:
    """Derive prior-therapy checkbox options from criteria text."""
    import re

    if not text:
        return []
    junk = re.compile(
        r"^(ALL of|at least|a \d|month|the following|OR|AND|Has |an?|Complete |"
        r"Monitor |Labeled for|sedating anti|non-sedating anti)\b",
        re.I,
    )
    opts: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        label = _clean_label(label)
        label = re.sub(r"^(an|a|the)\s+", "", label, flags=re.I)
        if len(label) < 3 or len(label) > 60:
            return
        if junk.search(label):
            return
        if re.search(r"\d-month|for a$|following|vasculitic|neuropath", label, re.I):
            return
        key = label.lower()
        if key in seen:
            return
        seen.add(key)
        opts.append({"value": _slugify_option(label, 48), "label": label})

    for m in re.finditer(
        r"(?:tried and failed|failure|intolerance|hypersensitivity|contraindication)"
        r"[^\n]{0,80}(?:following)?\s*:?\s*(.*?)"
        r"(?=\n\s*\n|\n\s*[A-Z][a-z].{20,}|Criteria for|Page \d)",
        text,
        re.I | re.S,
    ):
        chunk = m.group(0)
        for mm in re.finditer(r"[•▪\-]\s*([^•▪\n]+)", chunk):
            for part in re.split(r",\s*(?:or\s+|and\s+)?", mm.group(1)):
                part = re.sub(r"\([^)]*\)", "", part).strip()
                add(part)

    for m in re.finditer(
        r"(?:failed|intolerance|hypersensitivity|contraindication)\s+to\s+"
        r"([A-Za-z][A-Za-z0-9 \-]{2,40})",
        text,
        re.I,
    ):
        add(m.group(1))

    for name in (
        "gabapentin",
        "tricyclic antidepressants",
        "capsaicin cream",
        "lidocaine patch",
        "SNRI antidepressants",
        "opioid",
        "carbamazepine",
        "phenytoin",
        "valproate",
        "TNF blocker",
        "topical agent",
        "methotrexate",
        "phototherapy",
        "systemic therapy",
        "corticosteroid",
        "cyclosporine",
        "acitretin",
    ):
        if re.search(rf"\b{re.escape(name)}\b", text, re.I):
            add(name)

    add("None documented")
    add("Contraindication to all required agents")
    return opts[:20]


def _criteria_text_blob(pack_slug: str | None, pack: dict[str, Any] | None) -> str:
    if not pack_slug:
        return ""
    ct = get_criteria_text(pack_slug) or {}
    return (ct.get("extracted_text") or "") if isinstance(ct, dict) else ""


def _is_boolean_fact(fact: str) -> bool:
    f = fact.lower()
    if f in ("yes_no", "boolean"):
        return True
    return any(h in f for h in BOOLEAN_FACT_HINTS)


def _fact_ui_entry(pack: dict[str, Any], fact: str) -> dict[str, Any] | None:
    """Optional authored UI metadata on the rule pack (fact_ui[fact])."""
    ui = pack.get("fact_ui") or {}
    entry = ui.get(fact)
    return entry if isinstance(entry, dict) else None


def _normalize_options(opts: list[Any] | None) -> list[Any]:
    out: list[Any] = []
    for o in opts or []:
        if isinstance(o, dict) and "value" in o:
            out.append(o)
        else:
            out.append(o)
    return out


def build_fact_field(
    fact: str,
    pack: dict[str, Any],
    pack_slug: str | None,
) -> dict[str, Any]:
    """Build a controlled fact control — select or multi checkbox. Never free text.

    Indication must never fall back to Yes/No/Unknown. Boolean Yes/No is reserved
    for true boolean facts (has_/is_/… or authored boolean option lists).
    """
    field: dict[str, Any] = {
        "key": fact,
        "label": fact.replace("_", " ").title(),
        "free_text": False,
    }
    text = _criteria_text_blob(pack_slug, pack)
    authored = _fact_ui_entry(pack, fact)

    # Prefer authored fact_ui from the rule pack when present.
    if authored:
        field["label"] = authored.get("label") or field["label"]
        if authored.get("hint"):
            field["hint"] = authored["hint"]
        if isinstance(authored.get("when"), dict):
            field["when"] = authored["when"]
        ftype = authored.get("type") or "select"
        if authored.get("option_style") == "age_bands" or (
            fact == "age_years" and not authored.get("options")
        ):
            field["type"] = "select"
            field["label"] = authored.get("label") or "Age"
            field["options"] = list(AGE_BAND_OPTIONS)
            field["option_style"] = "age_bands"
            field["option_source"] = "age_bands"
            field.setdefault(
                "hint",
                "Band value sets age_years to the band minimum for gte checks "
                "(0 / 0.5 / 1 / 6 / 12 / 18).",
            )
            return field
        opts = _normalize_options(authored.get("options"))
        if ftype in ("multi", "checkbox", "checkboxes"):
            field["type"] = "multi"
            field["options"] = opts
            field["option_source"] = "fact_ui"
            return field
        field["type"] = "select"
        field["options"] = opts
        field["option_source"] = "fact_ui"
        # Authored empty options for indication is still not Yes/No/Unknown
        if fact == "indication" and not opts:
            field["options"] = []
            field["hint"] = (
                field.get("hint")
                or "No indication list authored on this pack — cannot collect indication."
            )
        return field

    if fact == "age_years":
        field["type"] = "select"
        field["label"] = "Age"
        field["options"] = list(AGE_BAND_OPTIONS)
        field["option_style"] = "age_bands"
        field["option_source"] = "age_bands"
        field["hint"] = (
            "Band value sets age_years to the band minimum for gte checks "
            "(0 / 0.5 / 1 / 6 / 12 / 18)."
        )
        return field

    if fact == "indication":
        pred_opts = indication_options_for_pack(pack)
        if pred_opts:
            field["type"] = "select"
            field["options"] = pred_opts
            field["option_source"] = "predicates"
            return field
        parsed = parse_indications_from_criteria_text(text)
        if parsed:
            field["type"] = "select"
            field["options"] = parsed
            field["option_source"] = "criteria_text"
            field["hint"] = "Options parsed from archived criteria text."
            return field
        # NEVER Yes/No/Unknown for indication — leave empty controlled select
        field["type"] = "select"
        field["options"] = []
        field["option_source"] = "missing_indication_list"
        field["hint"] = (
            "No diagnosis/indication list found in predicates, fact_ui, or criteria text. "
            "Indication cannot be collected as Yes/No/Unknown."
        )
        return field

    if fact in ("prescriber_specialty", "provider_type", "specialty"):
        field["type"] = "select"
        field["label"] = "Provider / specialty"
        opts = specialty_options_for_pack(pack)
        field["options"] = opts or list(DEFAULT_SPECIALTY_OPTIONS)
        field["option_source"] = "predicates" if opts else "default_specialty"
        return field

    if (
        fact in MULTI_FACT_KEYS
        or "therapy" in fact
        or "therapies" in fact
        or fact.endswith("_failures")
    ):
        field["type"] = "multi"
        field["label"] = fact.replace("_", " ").title()
        choice = _collect_choice_values(pack, fact)
        if choice:
            field["options"] = choice
            field["option_source"] = "predicates"
            field["hint"] = "Select all that apply."
            return field
        parsed = parse_therapies_from_criteria_text(text)
        if parsed:
            field["options"] = parsed
            field["option_source"] = "criteria_text"
            field["hint"] = "Select all that apply (from criteria text)."
        else:
            field["options"] = [
                {"value": "preferred_agent_failed", "label": "Preferred / step agent failed"},
                {"value": "intolerance", "label": "Intolerance / hypersensitivity"},
                {"value": "contraindication", "label": "Contraindication"},
                {"value": "insufficient_response", "label": "Insufficient response"},
                {"value": "none_documented", "label": "None documented"},
            ]
            field["option_source"] = "fallback_therapy_placeholders"
            field["hint"] = (
                "No therapy list parsed from criteria text — curated placeholders only."
            )
        return field

    # Predicate choice values for any other fact (closed list from rule pack)
    choice = _collect_choice_values(pack, fact)
    if choice:
        field["type"] = "select"
        field["options"] = choice
        field["option_source"] = "predicates"
        return field

    # Boolean-ish facts → Yes/No select (NOT Yes/No/Unknown; not for indication)
    if _is_boolean_fact(fact):
        field["type"] = "select"
        field["options"] = list(YES_NO_OPTIONS)
        field["option_source"] = "boolean_yes_no"
        return field

    # Last resort for unknown non-boolean, non-indication facts: still controlled,
    # but do NOT use Yes/No/Unknown unless the key is clearly boolean.
    field["type"] = "select"
    field["options"] = list(YES_NO_OPTIONS)
    field["option_source"] = "fallback_boolean_yes_no"
    field["hint"] = (
        "No closed option list found — Yes/No attestation only (not Yes/No/Unknown). "
        "Free-text entry is disabled."
    )
    return field


def _generic_stem(name: str | None) -> str:
    import re

    if not name:
        return ""
    # Drop strength / route noise: "PREGABALIN 100" → pregabalin
    s = name.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    tokens = [t for t in s.split() if t and not t.isdigit() and t not in {
        "oral", "tablet", "capsule", "solution", "syringe", "vial", "patch",
        "topical", "injection", "subcutaneous", "er", "cr", "ag", "hcl", "mg",
        "ml", "pen", "autoinj", "dose", "pack",
    }]
    return tokens[0] if tokens else ""


def resolve_market_baskets(drug_slug: str, pack: dict[str, Any] | None) -> list[str]:
    """Market baskets from the drug index for this slug / brand family."""
    drugs = load_drug_index()["drugs"]
    baskets: list[str] = []
    seen: set[str] = set()
    pack_name = ((pack or {}).get("drug") or {}).get("name") or ""
    base = drug_slug.split("-")[0].lower()

    for d in drugs:
        slug = d.get("slug") or ""
        primary = (d.get("primary_name") or "").lower()
        mb = d.get("market_basket")
        if not mb:
            continue
        hit = (
            slug == drug_slug
            or slug.startswith(base + "-")
            or slug == base
            or (pack_name and pack_name.lower() in primary)
        )
        if hit and mb not in seen:
            seen.add(mb)
            baskets.append(mb)
    return baskets


def suggest_pdl_class_alternatives(
    drug_slug: str,
    pack: dict[str, Any] | None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Best-effort PDL preferred peers in the same market basket (not evaluate-verified)."""
    baskets = resolve_market_baskets(drug_slug, pack)
    if not baskets:
        return []
    drugs = load_drug_index()["drugs"]
    exclude_stems: set[str] = set()
    pack_generic = ((pack or {}).get("drug") or {}).get("generic_name")
    exclude_stems.add(_generic_stem(pack_generic))
    exclude_stems.add(_generic_stem(drug_slug.replace("-", " ")))
    exclude_stems.discard("")

    citation = ((pack or {}).get("source") or {}).get("citation")
    # Prefer a DOH PDL citation when available
    pdl_cite = "https://health.alaska.gov/en/education/prior-authorization-medication/"
    citations = [c for c in [citation, pdl_cite] if c]

    out: list[dict[str, Any]] = []
    seen_stem: set[str] = set()
    # Preferred first, then other non-preferred peers as secondary
    candidates = [
        d
        for d in drugs
        if d.get("market_basket") in baskets and d.get("pdl_status") == "preferred"
    ]
    # Stable sort by primary name
    candidates.sort(key=lambda d: (d.get("primary_name") or "").lower())

    for d in candidates:
        stem = _generic_stem(d.get("generic_name") or d.get("primary_name"))
        if not stem or stem in exclude_stems or stem in seen_stem:
            continue
        # Skip same brand family as requested
        if (d.get("slug") or "").startswith(drug_slug.split("-")[0] + "-"):
            # allow preferred generic of same molecule? usually not an "alternative"
            if stem in exclude_stems:
                continue
        seen_stem.add(stem)
        out.append(
            {
                "drug": d.get("primary_name") or d.get("slug"),
                "slug": d.get("slug"),
                "rule_id": resolve_rule_pack_slug(d["slug"]),
                "pdl_status": d.get("pdl_status"),
                "market_basket": d.get("market_basket"),
                "generic_name": (d.get("generic_name") or "").strip() or None,
                "citations": list(citations),
                "verification": "pdl_preferred_same_class",
                "verification_note": (
                    "PDL preferred agent in the same Alaska market basket — "
                    "not evaluate()-verified against this patient's facts."
                ),
            }
        )
        if len(out) >= limit:
            break
    return out


def merge_alternatives(
    evaluate_alts: list[dict[str, Any]] | None,
    pdl_alts: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Deduplicate evaluate-pass alts ahead of PDL suggestions."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def key_of(a: dict[str, Any]) -> str:
        return (
            (a.get("rule_id") or "")
            + "|"
            + _generic_stem(a.get("drug"))
            + "|"
            + (a.get("slug") or "")
        ).lower()

    for a in evaluate_alts or []:
        enriched = dict(a)
        enriched.setdefault("verification", "evaluate_pass")
        enriched.setdefault(
            "verification_note",
            "Passes evaluate() on the linked rule pack for the submitted facts.",
        )
        k = key_of(enriched)
        if k in seen:
            continue
        seen.add(k)
        merged.append(enriched)
    for a in pdl_alts or []:
        k = key_of(a)
        # Also skip if same display name already present
        name = (a.get("drug") or "").lower()
        if k in seen or any((m.get("drug") or "").lower() == name for m in merged):
            continue
        seen.add(k)
        merged.append(a)
    return merged


def search_drugs(query: str, limit: int = 25) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return []
    drugs = load_drug_index()["drugs"]
    catalog = load_rule_pack_catalog()
    hits: list[tuple[int, dict[str, Any]]] = []

    for d in drugs:
        slug = d["slug"]
        names = " ".join(d.get("names") or [])
        primary = d.get("primary_name") or ""
        generic = d.get("generic_name") or ""
        hay = f"{slug} {primary} {names} {generic}".lower()
        if q not in hay:
            continue
        # Rank: prefix on primary/slug first
        rank = 50
        if primary.lower().startswith(q) or slug.startswith(q):
            rank = 0
        elif any(n.lower().startswith(q) for n in (d.get("names") or [])):
            rank = 5
        elif q in primary.lower() or q in slug:
            rank = 10
        pack_slug = resolve_rule_pack_slug(slug)
        hits.append(
            (
                rank,
                {
                    "slug": slug,
                    "primary_name": primary,
                    "names": d.get("names") or [],
                    "generic_name": d.get("generic_name"),
                    "requires_pa": bool(d.get("requires_pa")),
                    "pdl_status": d.get("pdl_status"),
                    "max_units_30_days": d.get("max_units_30_days"),
                    "market_basket": d.get("market_basket"),
                    "rule_pack_slug": pack_slug,
                    "encoding_status": (
                        catalog[pack_slug].get("encoding_status") if pack_slug else None
                    ),
                    "has_criteria_pdf": pack_slug is not None,
                },
            )
        )

    # Also surface rule-pack drugs that may not appear as exact PA-list rows
    for pack_slug, pack in catalog.items():
        name = pack.get("drug", {}).get("name") or pack_slug
        hay = f"{pack_slug} {name}".lower()
        if q not in hay:
            continue
        # Skip if already represented as exact slug hit
        if any(h[1]["slug"] == pack_slug for h in hits):
            continue
        rank = 2 if name.lower().startswith(q) or pack_slug.startswith(q) else 15
        hits.append(
            (
                rank,
                {
                    "slug": pack_slug,
                    "primary_name": name,
                    "names": [name],
                    "generic_name": pack.get("drug", {}).get("generic_name"),
                    "requires_pa": bool(pack.get("requires_pa", True)),
                    "pdl_status": pack.get("pdl_status"),
                    "max_units_30_days": None,
                    "market_basket": pack.get("drug", {}).get("therapeutic_class"),
                    "rule_pack_slug": pack_slug,
                    "encoding_status": pack.get("encoding_status"),
                    "has_criteria_pdf": True,
                    "from_rule_pack": True,
                },
            )
        )

    hits.sort(key=lambda t: (t[0], t[1]["primary_name"].lower()))
    return [h[1] for h in hits[:limit]]


def drug_detail(slug: str) -> dict[str, Any] | None:
    drugs = load_drug_index()["drugs"]
    drug = next((d for d in drugs if d["slug"] == slug), None)
    pack_info = get_rule_pack(slug)
    pack_slug = pack_info[0] if pack_info else None
    pack = pack_info[1] if pack_info else None

    if drug is None and pack is None:
        return None

    primary = (
        (drug or {}).get("primary_name")
        or (pack or {}).get("drug", {}).get("name")
        or slug
    )
    requires_pa = bool(
        (drug or {}).get("requires_pa")
        if drug and "requires_pa" in drug
        else (pack or {}).get("requires_pa", False)
    )
    pdl = (drug or {}).get("pdl_status") or (pack or {}).get("pdl_status")
    max_units = (drug or {}).get("max_units_30_days")
    if max_units is None and pack and pack.get("max_units"):
        max_units = pack["max_units"]

    citations: list[str] = []
    if pack and pack.get("source", {}).get("citation"):
        citations.append(pack["source"]["citation"])
    for clause in (pack or {}).get("criteria") or []:
        c = clause.get("citation")
        if c and c not in citations:
            citations.append(c)

    criteria_text = get_criteria_text(pack_slug) if pack_slug else None
    encoding = (pack or {}).get("encoding_status")
    can_evaluate = encoding in ("full", "partial") and bool((pack or {}).get("criteria"))

    fact_fields: list[dict[str, Any]] = []
    if pack:
        for fact in required_facts_for_pack(pack):
            fact_fields.append(build_fact_field(fact, pack, pack_slug))

    return {
        "slug": slug,
        "primary_name": primary,
        "generic_name": (drug or {}).get("generic_name")
        or (pack or {}).get("drug", {}).get("generic_name"),
        "names": (drug or {}).get("names") or [primary],
        "requires_pa": requires_pa,
        "pdl_status": pdl,
        "max_units_30_days": max_units,
        "market_basket": (drug or {}).get("market_basket")
        or (pack or {}).get("drug", {}).get("therapeutic_class"),
        "sources": (drug or {}).get("sources") or [],
        "pa_list_file": (drug or {}).get("pa_list_file"),
        "rule_pack_slug": pack_slug,
        "encoding_status": encoding,
        "can_evaluate": can_evaluate,
        "citations": citations,
        "source": (pack or {}).get("source"),
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
        "inferred_required_facts": (pack or {}).get("inferred_required_facts") or [],
        "criteria_text": (
            {
                "extracted_text": (criteria_text or {}).get("extracted_text"),
                "source_url": (criteria_text or {}).get("source_url"),
                "source_file": (criteria_text or {}).get("source_file"),
                "effective_date": (criteria_text or {}).get("effective_date"),
                "inferred_required_facts": (criteria_text or {}).get(
                    "inferred_required_facts"
                )
                or [],
            }
            if criteria_text
            else None
        ),
        "alternatives": (pack or {}).get("alternatives") or [],
        "market_baskets": resolve_market_baskets(slug, pack),
    }
