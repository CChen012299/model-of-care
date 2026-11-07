"""Role-based task visibility.

Enforced on the server: every query that returns tasks intersects the
requested task types with what the caller's role may see. The frontend only
chooses which role to send.

In production the role would come from a verified auth token claim. Here it
comes from the X-Role header or a ?role= query parameter, which keeps the
API easy to try in a browser.
"""
from __future__ import annotations

from enum import StrEnum

from fastapi import Header, HTTPException, Query


class Role(StrEnum):
    scheduler = "scheduler"
    clinical = "clinical"


class TaskType(StrEnum):
    scheduling = "scheduling"
    referral = "referral"


ROLE_TASK_TYPES: dict[Role, frozenset[str]] = {
    # Non-clinical staff: can book follow-ups for patients already established with a specialty.
    Role.scheduler: frozenset({"scheduling"}),
    # Clinical team: also reviews first-time specialist referrals.
    Role.clinical: frozenset({"scheduling", "referral"}),
}


def get_role(
    x_role: Role | None = Header(default=None, alias="X-Role"),
    role: Role | None = Query(default=None, description="Caller role (alternative to the X-Role header)"),
) -> Role:
    resolved = x_role or role
    if resolved is None:
        raise HTTPException(status_code=400, detail="Role required: send X-Role header or ?role=scheduler|clinical")
    return resolved


def visible_task_types(role: Role, requested: str | None) -> frozenset[str]:
    allowed = ROLE_TASK_TYPES[role]
    return allowed & {requested} if requested else allowed
