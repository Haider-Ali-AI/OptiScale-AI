"""Evidence-based reporting hints and explicit, immutable user clarifications."""

from datetime import datetime, timezone

import pandas as pd
from pydantic import Field

from ads_optimizer.domain import DomainError, StrictModel

DEFINITION_FIELDS = ["conversion_definition", "attribution_window"]
UNKNOWN = {"", "unspecified", "unknown", "none", "null", "nan", "n/a", "mixed"}


def known(value):
    return bool(pd.notna(value)) and str(value).strip().lower() not in UNKNOWN


def hint(values, evidence):
    values = list(values)
    supplied = [str(v).strip() for v in values if pd.notna(v)]
    distinct = sorted({v for v in supplied if known(v)})
    if len(distinct) > 1:
        return {"value": None, "status": "mixed", "evidence": evidence}
    if len(distinct) == 1:
        return {
            "value": distinct[0],
            "status": "detected" if all(known(v) for v in values) else "partial",
            "evidence": evidence,
        }
    return {
        "value": None,
        "status": "missing",
        "evidence": "This rule is not included in the report. We need your answer.",
    }


def import_hints(raw, mapping):
    result = {}
    for field in DEFINITION_FIELDS:
        column = mapping.get(field)
        if column:
            result[field] = hint(raw[column], f"Found in CSV column: {column}.")
        elif (
            field == "conversion_definition"
            and str(mapping.get("conversions", "")).strip().lower() == "purchases"
        ):
            result[field] = {
                "value": "purchases",
                "status": "detected",
                "evidence": "The mapped result column is explicitly named Purchases.",
            }
        else:
            result[field] = hint([], "")
    return result


def manifest_setup(manifest, frame=None):
    fields = {}
    for field in DEFINITION_FIELDS:
        value = getattr(manifest, field)
        if value.strip().lower() == "mixed":
            fields[field] = (
                hint(frame[field], "Some report rows lack a reporting rule.")
                if frame is not None
                else {
                    "value": None,
                    "status": "mixed",
                    "evidence": "The report includes different rules. Separate compatible exports.",
                }
            )
        else:
            fields[field] = hint(
                [value], manifest.reporting_evidence.get(field, "Recorded with this saved report.")
            )
    return {
        "fields": fields,
        "needs_answers": any(h["status"] in {"missing", "partial"} for h in fields.values()),
        "mixed": any(h["status"] == "mixed" for h in fields.values()),
        "financial_complete": all(manifest.coverage.get(k, 0) == 1 for k in ["spend", "revenue"]),
    }


class ReportingAnswers(StrictModel):
    conversion_definition: str = Field(min_length=1, max_length=100)
    attribution_window: str = Field(min_length=1, max_length=100)
    confirmed: bool = False


def clarify_report(repo, dataset_id, answers):
    if not answers.confirmed:
        raise DomainError("Review your answers and choose Save my answers to continue.")
    if not repo.selected() or repo.selected().id != dataset_id:
        raise DomainError("Select this report before saving its reporting rules.", 409)
    manifest = repo.get(dataset_id)
    frame = repo.read(dataset_id)
    changed = False
    evidence = dict(manifest.reporting_evidence)
    for field in DEFINITION_FIELDS:
        answer = getattr(answers, field).strip()
        if not known(answer):
            raise DomainError(
                "It is fine to be unsure. Keep using analytics; training needs "
                "both reporting rules before answers can be saved."
            )
        values = frame[field] if field in frame else pd.Series([getattr(manifest, field)])
        current = hint(values, "")
        if current["status"] == "mixed":
            raise DomainError(
                "This report combines different reporting rules. Separate compatible "
                "exports instead of assigning one rule to all rows."
            )
        if current["value"] and current["value"] != answer:
            raise DomainError(
                "The report already contains a different reporting rule. "
                "Keep the recorded value and review the source export."
            )
        if field not in frame or not values.map(known).all():
            frame[field] = answer
            evidence[field] = (
                "User confirmed during reporting setup at " + datetime.now(timezone.utc).isoformat()
            )
            changed = True
    if not changed:
        return manifest
    excluded = {"id", "imported_at", "rows", "date_start", "date_end", "coverage", "options"}
    metadata = manifest.model_dump(exclude=excluded)
    metadata.update(
        name=manifest.name[:87] + " · clarified",
        parent_dataset_id=manifest.id,
        reporting_evidence=evidence,
        conversion_definition=answers.conversion_definition.strip(),
        attribution_window=answers.attribution_window.strip(),
        data_ready_for_revenue=all(manifest.coverage.get(k, 0) == 1 for k in ["spend", "revenue"]),
        warnings=[
            w
            for w in manifest.warnings
            if "conversion/attribution definitions before forecasting" not in w
        ]
        + ["Reporting rules completed by the user; compare them with the source report settings."],
    )
    return repo.save(frame, metadata)
