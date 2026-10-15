from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Exercise(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sets: int = Field(ge=1, le=20)
    reps: int = Field(ge=1, le=100)
    load_kg: float | None = Field(default=None, ge=0, le=1000)


class ProfileInput(BaseModel):
    experience: Literal["beginner", "intermediate", "advanced"] = "beginner"
    weekly_days: int = Field(default=3, ge=1, le=7)
    session_minutes: int = Field(default=60, ge=20, le=180)
    limitations: str = Field(default="", max_length=1000)
    preferences: str = Field(default="", max_length=1000)


class CheckInInput(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    energy: int = Field(ge=1, le=5)
    fatigue: int = Field(ge=1, le=5)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    weight_kg: float | None = Field(default=None, ge=25, le=300)
    completion: Literal["full", "partial", "missed", "none"] = "none"
    completion_pct: int = Field(default=100, ge=0, le=100)
    did_train: bool = False
    rpe: int | None = Field(default=None, ge=1, le=10)
    pain: bool = False
    notes: str = Field(default="", max_length=2000)
    exercises: list[Exercise] = Field(default_factory=list, max_length=30)


class Evidence(BaseModel):
    claim: str
    source_ids: list[str] = Field(default_factory=list)


class SpecialistOutput(BaseModel):
    agent: str
    decision: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence] = Field(default_factory=list)
    constraints: dict[str, str | float | bool] = Field(default_factory=dict)
    rationale: str = Field(max_length=2000)


class TrainingOutput(SpecialistOutput):
    exercises: list[Exercise] = Field(default_factory=list)
    status: Literal["train", "reduce", "recover", "stop"] = "train"


class CoachOutput(BaseModel):
    title: str
    status: Literal["train", "reduce", "recover", "stop"]
    summary: str
    accepted_claims: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    exercises: list[Exercise] = Field(default_factory=list)


class LearningProposal(BaseModel):
    parameter: Literal["typical_rpe"]
    old_value: float | None = None
    proposed_value: float = Field(ge=1, le=10)
    evidence_ids: list[str]
    sample_count: int = Field(ge=0)
    confidence: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    rationale: str


class AgentRunView(BaseModel):
    id: UUID
    agent: str
    status: str
    output: dict | None = None
    error: str | None = None
    duration_ms: int | None = None


class PlanningRunView(BaseModel):
    id: UUID
    status: str
    provider: str
    model: str
    plan: dict | None = None
    conflicts: list[dict] = Field(default_factory=list)
    agents: list[AgentRunView] = Field(default_factory=list)
