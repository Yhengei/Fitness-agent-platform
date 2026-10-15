from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CheckIn(Base):
    __tablename__ = "check_in"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    date: Mapped[object] = mapped_column(Date, unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PlanningRun(Base):
    __tablename__ = "planning_run"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    checkin_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("check_in.id"))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conflicts: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    agents: Mapped[list["AgentRun"]] = relationship(back_populates="planning_run", cascade="all, delete-orphan")


class AgentRun(Base):
    __tablename__ = "agent_run"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    planning_run_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("planning_run.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    parent_run_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    planning_run: Mapped[PlanningRun] = relationship(back_populates="agents")


class LearningProposalRow(Base):
    __tablename__ = "learning_proposal"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    parameter: Mapped[str] = mapped_column(String(100), index=True)
    proposal: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LearningProfileVersion(Base):
    __tablename__ = "learning_profile_version"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    values: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_proposal_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_proposal.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
