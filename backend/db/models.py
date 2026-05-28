import enum
import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, Text, String, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    QUEUED                = "QUEUED"
    GATHERING_CONTEXT     = "GATHERING_CONTEXT"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    PLANNING              = "PLANNING"
    AWAITING_APPROVAL     = "AWAITING_APPROVAL"
    EXECUTING             = "EXECUTING"
    RAISING_PR            = "RAISING_PR"
    COMPLETED             = "COMPLETED"
    FAILED                = "FAILED"
    TIMED_OUT             = "TIMED_OUT"


# One row per ticket assigned to the agent. Tracks current state.
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ticket_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    ticket_title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.QUEUED
    )
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list["EventLog"]] = relationship("EventLog", back_populates="job")
    training_examples: Mapped[list["TrainingExample"]] = relationship("TrainingExample", back_populates="job")

# Every state transition ever. Full audit trail. Never deleted.
class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("jobs.id"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="events")

# System prompts per step (planner, executor, PR raiser). Versioned.
class PromptConfig(Base):
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    step: Mapped[str] = mapped_column(String(50), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    custom_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    top_p: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

# Training data collected from approved jobs. Used for fine-tuning.
class TrainingExample(Base):
    __tablename__ = "training_examples"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("jobs.id"), nullable=False, index=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_content: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_content: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="training_examples")

class JobEmbedding(Base):
    """
    Stores vector embeddings for completed jobs.
    
    How it works:
    - When a job is approved, we take the ticket description + plan
    - Convert that text to 1536 numbers using OpenAI embedding model
    - Store those numbers here as a vector
    - When new ticket arrives, embed it the same way
    - Search this table: find rows whose vector is closest to new ticket's vector
    - Closest vectors = most similar past jobs = inject as examples for planner
    """
    __tablename__ = "job_embeddings"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=str(uuid.uuid4()))
    job_id     = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    content    = Column(Text, nullable=False)   # text that was embedded — shown to planner
    embedding  = Column(Vector(1536), nullable=False)  # 1536 numbers = meaning of content
    created_at = Column(DateTime(timezone=True), server_default=func.now())