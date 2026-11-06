"""Load and validate the rule catalog from YAML.

rules/
  value_sets.yaml         named ICD-10 code groups
  specialties.yaml        specialties and whether first visits need a referral
  programs/*.yaml         one file per clinical program

Adding a program is adding a YAML file. Everything is validated here so the
engine never sees a malformed rule.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.engine.conditions import Condition, compile_condition
from app.engine.domain import PRIORITY_RANK, NeedSpec, Specialty, ValueSet, norm
from app.engine.errors import RulesConfigError
from app.engine.needs import NEED_TYPES


@dataclass(frozen=True)
class Tier:
    name: str
    when: Condition | None  # None = default tier ("all other eligible patients")
    needs: tuple[NeedSpec, ...]


@dataclass(frozen=True)
class Program:
    id: str
    name: str
    description: str
    eligibility: Condition
    tiers: tuple[Tier, ...]


@dataclass(frozen=True)
class RuleCatalog:
    programs: tuple[Program, ...]
    value_sets: dict[str, ValueSet]
    specialties: dict[str, Specialty]  # keyed by norm(name)
    version: str  # content hash of all rule files, stored on each engine run


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulesConfigError(f"{path.name}: invalid YAML: {exc}") from exc


def _load_value_sets(path: Path) -> dict[str, ValueSet]:
    raw = _load_yaml(path) or {}
    out: dict[str, ValueSet] = {}
    for name, body in raw.items():
        prefixes = (body or {}).get("icd10_prefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise RulesConfigError(f"value_sets.{name}: icd10_prefixes must be a non-empty list")
        out[name] = ValueSet(name, str(body.get("description", "")), tuple(str(p) for p in prefixes))
    return out


def _load_specialties(path: Path) -> dict[str, Specialty]:
    raw = _load_yaml(path) or {}
    out: dict[str, Specialty] = {}
    for name, body in raw.items():
        body = body or {}
        category = body.get("category")
        if category not in {"primary_care", "specialist"}:
            raise RulesConfigError(f"specialties.{name}: category must be primary_care or specialist")
        out[norm(name)] = Specialty(name, category, bool(body.get("referral_required", category == "specialist")))
    return out


def _parse_need(raw: Any, specialties: dict[str, Specialty], path: str) -> NeedSpec:
    if not isinstance(raw, dict):
        raise RulesConfigError(f"{path}: expected a mapping")
    need_type = NEED_TYPES.get(raw.get("type", ""))
    if need_type is None:
        raise RulesConfigError(f"{path}.type: unknown need type {raw.get('type')!r}. Known: {sorted(NEED_TYPES)}")
    allowed = {"type", need_type.target_field, "every_days", "priority", "note"}
    if extra := raw.keys() - allowed:
        raise RulesConfigError(f"{path}: unexpected keys {sorted(extra)}")
    if need_type.target_field not in raw:
        raise RulesConfigError(f"{path}: missing {need_type.target_field!r}")
    target = need_type.validate_target(str(raw[need_type.target_field]), specialties, path)
    every = raw.get("every_days")
    if not isinstance(every, int) or isinstance(every, bool) or every <= 0:
        raise RulesConfigError(f"{path}.every_days: expected a positive integer, got {every!r}")
    priority = raw.get("priority", "routine")
    if priority not in PRIORITY_RANK:
        raise RulesConfigError(f"{path}.priority: expected one of {sorted(PRIORITY_RANK)}")
    return NeedSpec(need_type.name, target, every, priority, raw.get("note"))


def _parse_program(raw: Any, file: str, value_sets: dict[str, ValueSet], specialties: dict[str, Specialty]) -> Program:
    if not isinstance(raw, dict):
        raise RulesConfigError(f"{file}: expected a mapping at top level")
    for key in ("id", "name", "eligibility", "tiers"):
        if key not in raw:
            raise RulesConfigError(f"{file}: missing {key!r}")
    pid = str(raw["id"])
    eligibility = compile_condition(raw["eligibility"], value_sets, f"{pid}.eligibility")

    tiers_raw = raw["tiers"]
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise RulesConfigError(f"{pid}.tiers: expected a non-empty list")
    tiers: list[Tier] = []
    for i, t in enumerate(tiers_raw):
        path = f"{pid}.tiers[{i}]"
        if not isinstance(t, dict) or "name" not in t:
            raise RulesConfigError(f"{path}: each tier needs a name")
        when = compile_condition(t["when"], value_sets, f"{path}.when") if "when" in t else None
        if when is None and i != len(tiers_raw) - 1:
            raise RulesConfigError(f"{path}: only the last tier may omit 'when' (it is the default tier)")
        needs = tuple(_parse_need(n, specialties, f"{path}.needs[{j}]") for j, n in enumerate(t.get("needs") or []))
        tiers.append(Tier(str(t["name"]), when, needs))
    names = [t.name for t in tiers]
    if len(set(names)) != len(names):
        raise RulesConfigError(f"{pid}.tiers: duplicate tier names")
    return Program(pid, str(raw["name"]), str(raw.get("description", "")), eligibility, tuple(tiers))


def load_catalog(rules_dir: Path) -> RuleCatalog:
    rules_dir = Path(rules_dir)
    files = [rules_dir / "value_sets.yaml", rules_dir / "specialties.yaml"]
    program_files = sorted((rules_dir / "programs").glob("*.yaml"))
    if not program_files:
        raise RulesConfigError(f"no program files found in {rules_dir / 'programs'}")

    value_sets = _load_value_sets(files[0])
    specialties = _load_specialties(files[1])
    programs = [_parse_program(_load_yaml(f), f.name, value_sets, specialties) for f in program_files]

    ids = [p.id for p in programs]
    if len(set(ids)) != len(ids):
        raise RulesConfigError(f"duplicate program ids: {ids}")

    digest = hashlib.sha256()
    for f in files + program_files:
        digest.update(f.name.encode())
        digest.update(f.read_bytes())
    return RuleCatalog(tuple(programs), value_sets, specialties, digest.hexdigest()[:12])
