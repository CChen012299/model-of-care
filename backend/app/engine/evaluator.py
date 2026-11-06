"""Evaluate one patient against the rule catalog.

Pipeline per patient:
  1. Eligibility: which programs does the patient qualify for?
  2. Stratification: first tier (in file order) whose criteria match.
  3. Needs: collect the tier's needs across all programs and merge duplicates.
  4. Assessment + tasks: each need type decides status and the task, if any.

Pure function: same context, catalog and as-of date always give the same result.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.engine.conditions import Match
from app.engine.domain import (
    PRIORITY_RANK,
    EnrollmentResult,
    NeedResult,
    NeedSourceResult,
    NeedSpec,
    PatientContext,
    PatientEvaluation,
)
from app.engine.needs import NEED_TYPES
from app.engine.rules import Program, RuleCatalog, Tier

_MAX_REASON = 500


def _fmt(evidence: list[str]) -> str:
    text = "; ".join(evidence)
    return text if len(text) <= _MAX_REASON else text[: _MAX_REASON - 3] + "..."


def _select_tier(program: Program, ctx: PatientContext, as_of: date) -> tuple[Tier | None, Match]:
    for tier in program.tiers:
        if tier.when is None:
            return tier, Match(True, ["Did not meet any higher tier criteria"])
        m = tier.when(ctx, as_of)
        if m.ok:
            return tier, m
    return None, Match(False, ["No tier criteria matched"])


def _merge(specs: list[tuple[NeedSpec, str, str]]) -> tuple[NeedSpec, list[NeedSourceResult]]:
    """Several programs may ask for the same need (same type + target).

    Keep one need per patient: the shortest cadence and the highest priority
    win, and every requesting program is kept as a source for traceability.
    """
    base = specs[0][0]
    cadence = min(s.cadence_days for s, _, _ in specs)
    priority = max((s.priority for s, _, _ in specs), key=PRIORITY_RANK.__getitem__)
    notes = list(dict.fromkeys(s.note for s, _, _ in specs if s.note))
    merged = NeedSpec(base.need_type, base.target, cadence, priority, "; ".join(notes) or None)
    sources = [NeedSourceResult(program_id, tier, s.cadence_days) for s, program_id, tier in specs]
    return merged, sources


def evaluate_patient(ctx: PatientContext, catalog: RuleCatalog, as_of: date) -> PatientEvaluation:
    enrollments: list[EnrollmentResult] = []
    requested: dict[str, list[tuple[NeedSpec, str, str]]] = defaultdict(list)

    for program in catalog.programs:
        eligible = program.eligibility(ctx, as_of)
        if not eligible.ok:
            continue
        tier, tier_match = _select_tier(program, ctx, as_of)
        enrollments.append(
            EnrollmentResult(
                program_id=program.id,
                program_name=program.name,
                tier=tier.name if tier else None,
                eligibility_reason=_fmt(eligible.evidence),
                tier_reason=_fmt(tier_match.evidence),
            )
        )
        if tier:
            for spec in tier.needs:
                requested[spec.key].append((spec, program.id, tier.name))

    needs: list[NeedResult] = []
    tasks = []
    for key, specs in requested.items():
        spec, sources = _merge(specs)
        handler = NEED_TYPES[spec.need_type]
        a = handler.assess(spec, ctx, as_of)
        need = NeedResult(
            need_key=key,
            need_type=spec.need_type,
            target=spec.target,
            cadence_days=spec.cadence_days,
            priority=spec.priority,
            note=spec.note,
            status=a.status,
            last_date=a.last_date,
            next_scheduled_date=a.next_scheduled_date,
            due_date=a.due_date,
            sources=sources,
        )
        needs.append(need)
        task = handler.task_for(ctx.patient_id, need, as_of, catalog.specialties)
        if task:
            tasks.append(task)

    return PatientEvaluation(ctx.patient_id, enrollments, needs, tasks)
