"""Engine input and output types."""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

# Helpers


def age_on(dob: date, on: date) -> int:
    """Age in whole years on a given date."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def months_before(d: date, months: int) -> date:
    """Same calendar day N months earlier, clamped to month end (Aug 31 - 6mo = Feb 28/29)."""
    total = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def norm(value: str) -> str:
    """Case and whitespace insensitive key for matching specialty / test names."""
    return " ".join(value.split()).casefold()


# Inputs


@dataclass(frozen=True)
class DiagnosisFact:
    icd_code: str
    description: str
    diagnosed_date: date


@dataclass(frozen=True)
class LabFact:
    test_name: str
    value: float
    result_date: date


@dataclass(frozen=True)
class EncounterFact:
    specialty: str
    encounter_date: date
    provider_name: str


@dataclass
class PatientContext:
    """Everything the rules may look at for one patient, pre-indexed."""

    patient_id: str
    date_of_birth: date
    diagnoses: list[DiagnosisFact] = field(default_factory=list)
    labs: list[LabFact] = field(default_factory=list)
    encounters: list[EncounterFact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._labs_by_test: dict[str, list[LabFact]] = defaultdict(list)
        for lab in sorted(self.labs, key=lambda x: x.result_date):
            self._labs_by_test[norm(lab.test_name)].append(lab)
        self._enc_by_specialty: dict[str, list[EncounterFact]] = defaultdict(list)
        for enc in sorted(self.encounters, key=lambda x: x.encounter_date):
            self._enc_by_specialty[norm(enc.specialty)].append(enc)

    def age_on(self, on: date) -> int:
        return age_on(self.date_of_birth, on)

    def diagnoses_as_of(self, as_of: date) -> list[DiagnosisFact]:
        return [d for d in self.diagnoses if d.diagnosed_date <= as_of]

    def labs_for(self, test_name: str) -> list[LabFact]:
        """Results for one test, oldest first."""
        return self._labs_by_test.get(norm(test_name), [])

    def encounters_for(self, specialty: str) -> list[EncounterFact]:
        """Encounters for one specialty (past and future), oldest first."""
        return self._enc_by_specialty.get(norm(specialty), [])


# Rule definitions

PRIORITY_RANK = {"routine": 0, "high": 1}


@dataclass(frozen=True)
class ValueSet:
    """A named group of ICD-10 code prefixes, e.g. chronic_conditions."""

    name: str
    description: str
    icd10_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class Specialty:
    name: str
    # Never-seen patients get a referral task (clinical review) only when True.
    referral_required: bool


@dataclass(frozen=True)
class NeedSpec:
    """One line of a tier's needs list, e.g. Endocrinology visit every 90 days."""

    need_type: str
    target: str
    cadence_days: int
    priority: str = "routine"
    note: str | None = None

    @property
    def key(self) -> str:
        return f"{self.need_type}:{self.target}"


# Outputs


@dataclass
class EnrollmentResult:
    program_id: str
    program_name: str
    tier: str | None
    eligibility_reason: str
    tier_reason: str


@dataclass(frozen=True)
class NeedSourceResult:
    program_id: str
    tier: str
    cadence_days: int


@dataclass
class NeedResult:
    need_key: str
    need_type: str
    target: str
    cadence_days: int
    priority: str
    note: str | None
    status: str  # scheduled | up_to_date | overdue | never_seen
    last_date: date | None
    next_scheduled_date: date | None
    due_date: date | None
    sources: list[NeedSourceResult]


@dataclass
class TaskDraft:
    task_key: str
    need_key: str
    task_type: str
    target: str
    priority: str
    due_date: date | None
    days_overdue: int | None
    reason: str


@dataclass
class PatientEvaluation:
    patient_id: str
    enrollments: list[EnrollmentResult]
    needs: list[NeedResult]
    tasks: list[TaskDraft]
