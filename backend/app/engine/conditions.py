"""Condition registry.

Eligibility and tier criteria in the program YAML are trees of conditions:

    any:
      - age_gte: 65
      - has_diagnosis: {value_set: chronic_conditions}

Each condition name maps to a builder that validates its parameters once, at
load time, and returns a callable(ctx, as_of) -> Match. Adding a new kind of
criterion (e.g. "has_medication") means writing one builder function here.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.engine.domain import PatientContext, ValueSet, months_before
from app.engine.errors import RulesConfigError


@dataclass(frozen=True)
class Match:
    ok: bool
    evidence: list[str] = field(default_factory=list)


Condition = Callable[[PatientContext, date], Match]
Builder = Callable[[Any, Mapping[str, ValueSet], str], Condition]

_BUILDERS: dict[str, Builder] = {}


def register(name: str) -> Callable[[Builder], Builder]:
    def deco(fn: Builder) -> Builder:
        _BUILDERS[name] = fn
        return fn

    return deco


def known_conditions() -> list[str]:
    return sorted(_BUILDERS)


def compile_condition(node: Any, value_sets: Mapping[str, ValueSet], path: str) -> Condition:
    if not isinstance(node, dict) or len(node) != 1:
        raise RulesConfigError(f"{path}: a condition must be a mapping with exactly one key, got {node!r}")
    ((name, params),) = node.items()
    builder = _BUILDERS.get(name)
    if builder is None:
        raise RulesConfigError(f"{path}: unknown condition {name!r}. Known: {', '.join(known_conditions())}")
    return builder(params, value_sets, f"{path}.{name}")


# Param helpers


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RulesConfigError(f"{path}: expected a number, got {value!r}")
    return float(value)


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RulesConfigError(f"{path}: expected a non-negative integer, got {value!r}")
    return value


def _mapping(value: Any, path: str, required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise RulesConfigError(f"{path}: expected a mapping, got {value!r}")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise RulesConfigError(f"{path}: missing {sorted(missing)}")
    if extra:
        raise RulesConfigError(f"{path}: unexpected keys {sorted(extra)}")
    return value


def icd_matches(code: str, prefix: str) -> bool:
    """ICD-10 family match that works with or without the dot.

    "E11" matches E11.65, "G47.3" matches G47.33, "I10" matches I10.
    """
    c = code.replace(".", "").upper().strip()
    p = prefix.replace(".", "").upper().strip()
    return bool(p) and c.startswith(p)


# Boolean combinators


@register("all")
def _all(params: Any, value_sets: Mapping[str, ValueSet], path: str) -> Condition:
    if not isinstance(params, list) or not params:
        raise RulesConfigError(f"{path}: expected a non-empty list")
    children = [compile_condition(p, value_sets, f"{path}[{i}]") for i, p in enumerate(params)]

    def run(ctx: PatientContext, as_of: date) -> Match:
        evidence: list[str] = []
        for child in children:
            m = child(ctx, as_of)
            if not m.ok:
                return Match(False)
            evidence += m.evidence
        return Match(True, evidence)

    return run


@register("any")
def _any(params: Any, value_sets: Mapping[str, ValueSet], path: str) -> Condition:
    if not isinstance(params, list) or not params:
        raise RulesConfigError(f"{path}: expected a non-empty list")
    children = [compile_condition(p, value_sets, f"{path}[{i}]") for i, p in enumerate(params)]

    def run(ctx: PatientContext, as_of: date) -> Match:
        # Evaluate every branch so the evidence lists all reasons that apply.
        hits = [m for m in (child(ctx, as_of) for child in children) if m.ok]
        return Match(bool(hits), [e for m in hits for e in m.evidence])

    return run


# Demographics


@register("age_gte")
def _age_gte(params: Any, _vs: Mapping[str, ValueSet], path: str) -> Condition:
    threshold = _int(params, path)

    def run(ctx: PatientContext, as_of: date) -> Match:
        age = ctx.age_on(as_of)
        return Match(age >= threshold, [f"Age {age} (>= {threshold})"])

    return run


# Diagnoses


@register("has_diagnosis")
def _has_diagnosis(params: Any, value_sets: Mapping[str, ValueSet], path: str) -> Condition:
    """{value_set: chronic_conditions} or {codes: [E10, E11]}."""
    if not isinstance(params, dict) or len(params) != 1 or not ({"value_set", "codes"} & params.keys()):
        raise RulesConfigError(f"{path}: expected exactly one of value_set or codes")
    if "value_set" in params:
        vs = value_sets.get(params["value_set"])
        if vs is None:
            raise RulesConfigError(f"{path}: unknown value_set {params['value_set']!r}")
        prefixes = vs.icd10_prefixes
    else:
        codes = params["codes"]
        if not isinstance(codes, list) or not codes or not all(isinstance(c, str) for c in codes):
            raise RulesConfigError(f"{path}.codes: expected a non-empty list of strings")
        prefixes = tuple(codes)

    def run(ctx: PatientContext, as_of: date) -> Match:
        hits = [d for d in ctx.diagnoses_as_of(as_of) if any(icd_matches(d.icd_code, p) for p in prefixes)]
        return Match(bool(hits), [f"Dx {d.icd_code} {d.description}" for d in hits])

    return run


# Labs

_BOUNDS = {"gte": (">=", lambda v, b: v >= b), "gt": (">", lambda v, b: v > b),
           "lte": ("<=", lambda v, b: v <= b), "lt": ("<", lambda v, b: v < b)}


@register("latest_lab")
def _latest_lab(params: Any, _vs: Mapping[str, ValueSet], path: str) -> Condition:
    """Most recent result for `test` within the lookback window satisfies every bound.

    {test: HbA1c, within_months: 6, gte: 7.0, lt: 9.0}
    No result in the window means no match (use no_recent_lab for that case).
    """
    p = _mapping(params, path, {"test", "within_months"}, set(_BOUNDS))
    test, months = str(p["test"]), _int(p["within_months"], f"{path}.within_months")
    bounds = [(k, _number(p[k], f"{path}.{k}")) for k in _BOUNDS if k in p]
    if not bounds:
        raise RulesConfigError(f"{path}: needs at least one of {sorted(_BOUNDS)}")

    def run(ctx: PatientContext, as_of: date) -> Match:
        start = months_before(as_of, months)
        recent = [lab for lab in ctx.labs_for(test) if start <= lab.result_date <= as_of]
        if not recent:
            return Match(False)
        latest = recent[-1]
        ok = all(_BOUNDS[k][1](latest.value, b) for k, b in bounds)
        desc = " and ".join(f"{_BOUNDS[k][0]} {b}" for k, b in bounds)
        return Match(ok, [f"{latest.test_name} {latest.value:g} on {latest.result_date} ({desc})"])

    return run


@register("no_recent_lab")
def _no_recent_lab(params: Any, _vs: Mapping[str, ValueSet], path: str) -> Condition:
    """No result for `test` within the lookback window. {test: HbA1c, within_months: 6}"""
    p = _mapping(params, path, {"test", "within_months"})
    test, months = str(p["test"]), _int(p["within_months"], f"{path}.within_months")

    def run(ctx: PatientContext, as_of: date) -> Match:
        start = months_before(as_of, months)
        history = [lab for lab in ctx.labs_for(test) if lab.result_date <= as_of]
        if any(lab.result_date >= start for lab in history):
            return Match(False)
        if history:
            last = history[-1]
            detail = f"last {last.value:g} on {last.result_date}"
        else:
            detail = "none on record"
        return Match(True, [f"No {test} since {start} ({detail})"])

    return run
