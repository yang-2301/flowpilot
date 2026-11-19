"""Models: workflows, runs, per-step execution records."""
import uuid

from sqlalchemy import (Column, String, Text, Boolean, ForeignKey, Index,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from .config import DATABASE_URL

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def new_uuid() -> str:
    return uuid.uuid4().hex[:12]


class Base(DeclarativeBase):
    pass


class Workflow(Base):
    __tablename__ = "workflows"
    id = Column(String(12), primary_key=True, default=new_uuid)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    trigger_type = Column(String(20), nullable=False, default="webhook")  # webhook|interval
    # webhook: {"secret": "..."}  interval: {"interval_seconds": 300}
    trigger_config = Column(Text, nullable=False, default="{}")
    steps = Column(Text, nullable=False, default="[]")  # JSON list of step dicts
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(32), nullable=False, default=now_iso)

    runs = relationship("Run", back_populates="workflow",
                        order_by="Run.started_at.desc()")


class Run(Base):
    __tablename__ = "runs"
    id = Column(String(12), primary_key=True, default=new_uuid)
    workflow_id = Column(String(12), ForeignKey("workflows.id"), nullable=False, index=True)
    status = Column(String(12), nullable=False, default="running",
                    index=True)  # running|success|failed|dead|skipped
    trigger_payload = Column(Text, default="{}")
    error = Column(Text)
    started_at = Column(String(32), nullable=False, default=now_iso)
    finished_at = Column(String(32))
    replay_of = Column(String(12))  # run id this was replayed from

    workflow = relationship("Workflow", back_populates="runs")
    steps = relationship("StepRun", back_populates="run",
                         order_by="StepRun.idx", cascade="all, delete-orphan")


class StepRun(Base):
    __tablename__ = "step_runs"
    id = Column(String(12), primary_key=True, default=new_uuid)
    run_id = Column(String(12), ForeignKey("runs.id"), nullable=False, index=True)
    idx = Column(String(4), nullable=False)
    name = Column(String(120), nullable=False)
    type = Column(String(20), nullable=False)
    status = Column(String(12), nullable=False, default="pending")  # ok|failed|skipped
    input = Column(Text, default="{}")
    output = Column(Text)
    error = Column(Text)
    attempts = Column(String(4), nullable=False, default="0")
    duration_ms = Column(String(10), nullable=False, default="0")

    run = relationship("Run", back_populates="steps")


Index("ix_runs_workflow_status", Run.workflow_id, Run.status)


def init_db() -> None:
    Base.metadata.create_all(engine)
