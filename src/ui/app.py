"""AbridgeRx clinician FastAPI app — Alaska Medicaid PA check (advisory)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

UI_DIR = Path(__file__).resolve().parent
SRC_DIR = UI_DIR.parent
ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from engine.evaluate import check  # noqa: E402
from ui.loaders import (  # noqa: E402
    drug_detail,
    get_rule_pack,
    load_rule_pack_catalog,
    merge_alternatives,
    search_drugs,
    suggest_pdl_class_alternatives,
)

STATIC_DIR = UI_DIR / "static"

app = FastAPI(
    title="AbridgeRx",
    description="Alaska Medicaid prior-authorization criteria check (advisory).",
    version="0.1.7",
)


class CheckRequest(BaseModel):
    slug: str = Field(..., description="Drug index or rule-pack slug")
    patient: dict[str, Any] = Field(default_factory=dict)


def _coerce_patient(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize form values; drop empty strings; coerce age_years to float.

    Multi-select facts may arrive as a list (checkbox group) or a single string.
    """
    out: dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            cleaned = [x for x in v if x is not None and x != ""]
            if cleaned:
                out[k] = cleaned
            continue
        if k == "age_years":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        elif isinstance(v, str) and v.lower() in ("true", "false", "yes", "no"):
            out[k] = v.lower() in ("true", "yes")
        else:
            out[k] = v
    return out


def _with_class_alternatives(
    *,
    slug: str,
    pack: dict[str, Any],
    result_alternatives: list[dict[str, Any]] | None,
    decision: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Merge evaluate()-verified alts with PDL preferred same-class suggestions.

    Always attach best-effort PDL peers on fail, and on text_only flows regardless
    of decision (labeled as not evaluate()-verified).
    """
    want_pdl = decision == "fail" or mode == "text_only"
    pdl = (
        suggest_pdl_class_alternatives(slug, pack)
        if want_pdl
        else []
    )
    return merge_alternatives(result_alternatives or [], pdl)


@app.get("/api/health")
def health() -> dict[str, Any]:
    catalog = load_rule_pack_catalog()
    return {
        "ok": True,
        "product": "AbridgeRx",
        "payer": "alaska_medicaid",
        "rule_packs": len(catalog),
    }


@app.get("/api/drugs/search")
def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=50),
) -> dict[str, Any]:
    return {"query": q, "results": search_drugs(q, limit=limit)}


@app.get("/api/drugs/{slug}")
def api_drug(slug: str) -> dict[str, Any]:
    detail = drug_detail(slug)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Unknown drug slug: {slug}")
    return detail


@app.post("/api/check")
def api_check(body: CheckRequest) -> dict[str, Any]:
    resolved = get_rule_pack(body.slug)
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail="No rule pack for this drug. PA list / PDL status may still apply — open drug detail.",
        )
    pack_slug, pack = resolved
    patient = _coerce_patient(body.patient)
    catalog = load_rule_pack_catalog()
    encoding = pack.get("encoding_status")
    detail = drug_detail(body.slug) or drug_detail(pack_slug)

    # text_only / encoding_incomplete: never invent yes/no coverage
    if encoding in ("text_only", "encoding_incomplete") or (
        encoding is None and not (pack.get("criteria") or [])
    ):
        result = check(pack, patient, catalog)
        alts = _with_class_alternatives(
            slug=body.slug,
            pack=pack,
            result_alternatives=result.alternatives,
            decision=result.decision,
            mode="text_only",
        )
        return {
            "mode": "text_only",
            "decision": result.decision,
            "drug": result.drug,
            "rule_pack_slug": pack_slug,
            "encoding_status": encoding,
            "failed_clauses": result.failed_clauses,
            "missing_facts": result.missing_facts,
            "citations": result.citations,
            "alternatives": alts,
            "notes": result.notes
            + (
                [
                    "Alternatives include PDL preferred peers in the same market basket "
                    "(best-effort; not evaluate()-verified for text_only packs)."
                ]
                if alts
                else []
            ),
            "criteria_text": (detail or {}).get("criteria_text"),
            "checklist": (detail or {}).get("fact_fields")
            or [
                {
                    "key": f,
                    "label": f.replace("_", " ").title(),
                    "type": "select",
                    "options": [
                        {"value": "yes", "label": "Yes"},
                        {"value": "no", "label": "No"},
                        {"value": "unknown", "label": "Unknown"},
                    ],
                }
                for f in ((detail or {}).get("inferred_required_facts") or [])
            ],
            "patient_facts_used": patient,
            "advisory": True,
        }

    result = check(pack, patient, catalog)
    alts = _with_class_alternatives(
        slug=body.slug,
        pack=pack,
        result_alternatives=result.alternatives,
        decision=result.decision,
        mode="evaluate",
    )
    return {
        "mode": "evaluate",
        "decision": result.decision,
        "drug": result.drug,
        "rule_pack_slug": pack_slug,
        "encoding_status": encoding,
        "failed_clauses": result.failed_clauses,
        "missing_facts": result.missing_facts,
        "citations": result.citations,
        "alternatives": alts,
        "notes": result.notes,
        "criteria_clauses": (detail or {}).get("criteria_clauses") or [],
        "patient_facts_used": patient,
        "advisory": True,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
