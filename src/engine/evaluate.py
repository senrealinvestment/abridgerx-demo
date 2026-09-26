"""Deterministic PA criteria evaluator.

Returns pass | fail | need_info. Never invents coverage.
Unknown rule-pack fields are ignored. Empty / text_only packs never auto-pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    decision: str  # pass | fail | need_info
    drug: str
    failed_clauses: list[dict[str, Any]] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _fact(patient: dict[str, Any], key: str) -> Any:
    return patient.get(key)


def _eval_predicate(predicate: dict[str, Any], patient: dict[str, Any]) -> bool | None:
    """Return True/False, or None if required inputs are missing."""
    op = predicate.get("op")
    if op == "eq":
        val = _fact(patient, predicate["fact"])
        if val is None:
            return None
        return val == predicate["value"]
    if op == "gte":
        val = _fact(patient, predicate["fact"])
        if val is None:
            return None
        return val >= predicate["value"]
    if op == "in":
        val = _fact(patient, predicate["fact"])
        if val is None:
            return None
        return val in predicate["values"]
    if op == "all":
        results = [_eval_predicate(p, patient) for p in predicate["args"]]
        if any(r is None for r in results):
            return None
        return all(results)
    if op == "any":
        results = [_eval_predicate(p, patient) for p in predicate["args"]]
        if all(r is None for r in results):
            return None
        known = [r for r in results if r is not None]
        return any(known)
    raise ValueError(f"Unknown predicate op: {op}")


def evaluate(rule_pack: dict[str, Any], patient: dict[str, Any]) -> EvalResult:
    drug_name = rule_pack["drug"]["name"]
    citations = [rule_pack["source"]["citation"]]
    missing: list[str] = []
    failed: list[dict[str, Any]] = []
    notes: list[str] = list(rule_pack.get("notes") or [])

    if not rule_pack.get("requires_pa", True):
        return EvalResult(
            decision="pass",
            drug=drug_name,
            citations=citations,
            notes=notes
            + ["Drug does not require prior authorization on this rule pack."],
        )

    encoding = rule_pack.get("encoding_status")
    criteria = rule_pack.get("criteria") or []

    # Incomplete encodings must never auto-pass.
    if encoding in ("text_only", "encoding_incomplete") or (
        encoding is None and not criteria
    ):
        for fact in rule_pack.get("inferred_required_facts") or []:
            if _fact(patient, fact) is None and fact not in missing:
                missing.append(fact)
        if not missing:
            # Still cannot decide coverage without predicates
            missing.append("_criteria_review")
        return EvalResult(
            decision="need_info",
            drug=drug_name,
            missing_facts=missing,
            citations=list(dict.fromkeys(citations)),
            notes=notes
            + [
                "encoding_incomplete: criteria PDF text archived but predicates not yet encoded; "
                "manual review against source citation required."
            ],
        )

    if not criteria and rule_pack.get("requires_pa", True):
        return EvalResult(
            decision="need_info",
            drug=drug_name,
            missing_facts=["_criteria_review"],
            citations=list(dict.fromkeys(citations)),
            notes=notes
            + ["encoding_incomplete: requires_pa with empty criteria array."],
        )

    for clause in criteria:
        for fact in clause.get("required_facts", []):
            if _fact(patient, fact) is None and fact not in missing:
                missing.append(fact)
        result = _eval_predicate(clause["predicate"], patient)
        citations.append(clause["citation"])
        if result is None:
            continue
        if result is False:
            failed.append(
                {
                    "id": clause["id"],
                    "text": clause["text"],
                    "citation": clause["citation"],
                }
            )

    if missing:
        return EvalResult(
            decision="need_info",
            drug=drug_name,
            failed_clauses=failed,
            missing_facts=missing,
            citations=list(dict.fromkeys(citations)),
            notes=notes,
        )
    if failed:
        return EvalResult(
            decision="fail",
            drug=drug_name,
            failed_clauses=failed,
            citations=list(dict.fromkeys(citations)),
            notes=notes,
        )
    return EvalResult(
        decision="pass",
        drug=drug_name,
        citations=list(dict.fromkeys(citations)),
        notes=notes,
    )


def find_alternatives(
    requested: dict[str, Any],
    patient: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-run evaluate() on named alternatives; return those that pass."""
    alts: list[dict[str, Any]] = []
    for alt_id in requested.get("alternatives", []):
        pack = catalog.get(alt_id)
        if not pack:
            continue
        result = evaluate(pack, patient)
        if result.decision == "pass":
            alts.append(
                {
                    "drug": pack["drug"]["name"],
                    "rule_id": alt_id,
                    "citations": result.citations,
                }
            )
    return alts


def check(
    rule_pack: dict[str, Any],
    patient: dict[str, Any],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> EvalResult:
    result = evaluate(rule_pack, patient)
    if result.decision == "fail" and catalog:
        result.alternatives = find_alternatives(rule_pack, patient, catalog)
    return result
