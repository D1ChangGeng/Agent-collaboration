"""Historical v6 input shapes for archive regression fixtures only."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClosedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TeamMember(ClosedInput):
    agent_slot_id: str = Field(min_length=1, max_length=128)
    principal_ref: str = Field(min_length=1, max_length=256)
    role: Literal["root", "route", "engineer", "reviewer", "finalizer", "specialist"]
    profile: Literal["root_manager", "route_manager", "engineer", "reviewer", "operator"] = "engineer"
    grant_ref: str | None = Field(default=None, min_length=1, max_length=256)
    permissions: list[str] = Field(default_factory=list, max_length=128)
    expires_at: datetime | None = None
    budget_ref: str | None = Field(default=None, min_length=1, max_length=256)
    harness_requirements: list[Literal["codex", "opencode"]] = Field(max_length=2)
    organization_level: Literal["root", "route", "task"] | None = None
    responsibilities: list[Literal["project_coordination", "route_coordination", "engineer",
                                    "reviewer", "specialist", "finalizer"]] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def role_declaration(self):
        if len(set(self.responsibilities)) != len(self.responsibilities):
            raise ValueError("responsibilities must be unique")
        primary = {"root": "project_coordination", "route": "route_coordination"}.get(self.role, self.role)
        if self.responsibilities and primary not in self.responsibilities:
            raise ValueError("responsibilities must include the primary role")
        return self

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("Grant expiry requires a timezone")
        return value


class TeamBudget(ClosedInput):
    budget_ref: str = Field(min_length=1, max_length=256)
    max_messages: int = Field(ge=1, le=10000)
    max_pending_messages: int = Field(ge=1, le=1000)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        return TeamMember.aware(value)


class TeamRules(ClosedInput):
    allowed_activations: list[Literal["message_only", "invoke"]] = Field(min_length=1, max_length=2)
    allowed_delivery_policies: list[Literal["queue_until_idle", "steer_active_turn"]] = Field(min_length=1, max_length=2)
    max_deadline_seconds: int = Field(ge=1, le=86400)


class TeamPolicy(ClosedInput):
    policy_ref: str = Field(min_length=1, max_length=256)
    rules: TeamRules
