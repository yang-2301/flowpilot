"""FlowPilot API: management (admin token), webhook triggers, demo endpoints."""
import hashlib
import json
import secrets
import urllib.error

from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import ADMIN_TOKEN
from .engine import validate_steps
from .models import init_db, SessionLocal, Workflow, Run, now_iso
from .scheduler import Scheduler, execute_run

app = FastAPI(
    title="FlowPilot API",
    version="1.0.0",
    description="Config-driven automation engine: webhook/interval triggers, "
                "HTTP/LLM/transform/condition steps, retries with backoff, run log with replay.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

scheduler = Scheduler()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    scheduler.stop()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(authorization: str = Header(default="")):
    """Bearer-token guard for the management API."""
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "invalid admin token")


# --- demo endpoints (targets the sample workflows point at) -------------------

@app.api_route("/demo/echo", methods=["GET", "POST"])
async def demo_echo(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = dict(request.query_params)
    return {"echo": payload, "at": now_iso()}


@app.get("/demo/flaky")
def demo_flaky(fail_rate: float = 0.5, bucket: str = ""):
    """Deterministic-ish flaky endpoint to demonstrate retries with backoff.

    Keyed by `bucket`: the first N calls fail, then it succeeds — so a retry
    policy of >= N makes the run succeed deterministically instead of randomly.
    """
    key = f"flaky:{bucket}"
    if not hasattr(app.state, "flaky_counts"):
        app.state.flaky_counts = {}
    app.state.flaky_counts[key] = app.state.flaky_counts.get(key, 0) + 1
    n = app.state.flaky_counts[key]
    fails = max(1, round(fail_rate * 10))
    if n <= fails:
        raise HTTPException(503, f"flaky failure #{n} (succeeds after {fails})")
    return {"ok": True, "attempt": n}


# --- management API (admin token) ---------------------------------------------

class StepDef(BaseModel):
    type: str
    name: str = ""
    config: dict = Field(default_factory=dict)
    max_attempts: int = Field(default=1, ge=1, le=5)


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    trigger_type: str = Field(pattern="^(webhook|interval)$")
    trigger_config: dict = Field(default_factory=dict)
    steps: list[StepDef]
    enabled: bool = True


def _wf_out(wf: Workflow) -> dict:
    return {
        "id": wf.id, "name": wf.name, "description": wf.description,
        "trigger_type": wf.trigger_type,
        "trigger_config": json.loads(wf.trigger_config),
        "steps": json.loads(wf.steps),
        "enabled": wf.enabled, "created_at": wf.created_at,
    }


@app.get("/api/workflows", dependencies=[Depends(require_admin)])
def list_workflows(db: Session = Depends(get_db)):
    return [_wf_out(wf) for wf in db.query(Workflow).order_by(Workflow.created_at).all()]


@app.post("/api/workflows", status_code=201, dependencies=[Depends(require_admin)])
def create_workflow(body: WorkflowIn, db: Session = Depends(get_db)):
    steps = [s.model_dump() for s in body.steps]
    try:
        validate_steps(steps)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.trigger_type == "interval":
        if "interval_seconds" not in body.trigger_config:
            raise HTTPException(422, "interval trigger needs trigger_config.interval_seconds")
    wf = Workflow(
        name=body.name, description=body.description,
        trigger_type=body.trigger_type,
        trigger_config=json.dumps(body.trigger_config),
        steps=json.dumps(steps), enabled=body.enabled,
    )
    if body.trigger_type == "webhook":
        secret = secrets.token_hex(8)
        cfg = dict(body.trigger_config)
        cfg.setdefault("secret", secret)
        wf.trigger_config = json.dumps(cfg)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return _wf_out(wf)


@app.put("/api/workflows/{wf_id}", dependencies=[Depends(require_admin)])
def update_workflow(wf_id: str, body: WorkflowIn, db: Session = Depends(get_db)):
    wf = db.get(Workflow, wf_id)
    if wf is None:
        raise HTTPException(404, "workflow not found")
    steps = [s.model_dump() for s in body.steps]
    try:
        validate_steps(steps)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    old_cfg = json.loads(wf.trigger_config)
    cfg = dict(body.trigger_config)
    if body.trigger_type == "webhook":
        cfg.setdefault("secret", old_cfg.get("secret", secrets.token_hex(8)))
    wf.name, wf.description = body.name, body.description
    wf.trigger_type, wf.enabled = body.trigger_type, body.enabled
    wf.trigger_config, wf.steps = json.dumps(cfg), json.dumps(steps)
    db.commit()
    return _wf_out(wf)


@app.delete("/api/workflows/{wf_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_workflow(wf_id: str, db: Session = Depends(get_db)):
    wf = db.get(Workflow, wf_id)
    if wf is None:
        raise HTTPException(404, "workflow not found")
    db.query(Run).filter(Run.workflow_id == wf_id).delete()
    db.delete(wf)
    db.commit()


@app.post("/api/runs/{run_id}/replay", dependencies=[Depends(require_admin)])
def replay_run(run_id: str, db: Session = Depends(get_db)):
    old = db.get(Run, run_id)
    if old is None:
        raise HTTPException(404, "run not found")
    wf = db.get(Workflow, old.workflow_id)
    if wf is None:
        raise HTTPException(404, "workflow deleted")
    payload = json.loads(old.trigger_payload)
    return _run_out(execute_run(db, wf, payload, replay_of=run_id))


def _run_out(run: Run) -> dict:
    return {
        "id": run.id, "workflow_id": run.workflow_id, "status": run.status,
        "trigger_payload": json.loads(run.trigger_payload or "{}"),
        "error": run.error, "started_at": run.started_at,
        "finished_at": run.finished_at, "replay_of": run.replay_of,
        "steps": [
            {"idx": int(s.idx), "name": s.name, "type": s.type, "status": s.status,
             "output": json.loads(s.output) if s.output else None,
             "error": s.error, "attempts": int(s.attempts),
             "duration_ms": int(s.duration_ms)}
            for s in run.steps
        ],
    }


@app.get("/api/runs", dependencies=[Depends(require_admin)])
def list_runs(status: str = "", workflow_id: str = "",
              page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    q = db.query(Run)
    if status:
        q = q.filter(Run.status == status)
    if workflow_id:
        q = q.filter(Run.workflow_id == workflow_id)
    runs = (q.order_by(Run.started_at.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return [{"id": r.id, "workflow_id": r.workflow_id, "status": r.status,
             "error": r.error, "started_at": r.started_at,
             "finished_at": r.finished_at, "replay_of": r.replay_of}
            for r in runs]


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_admin)])
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return _run_out(run)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "flowpilot", "version": app.version}


# --- webhook trigger (public, secret-keyed) ------------------------------------

@app.post("/hooks/{workflow_id}/{secret}", status_code=202)
async def webhook_trigger(workflow_id: str, secret: str, request: Request,
                          db: Session = Depends(get_db)):
    """Fire a webhook workflow. 202 immediately with the run id attached;
    execution is synchronous for demo simplicity (queue-ready contract)."""
    wf = db.get(Workflow, workflow_id)
    if wf is None or wf.trigger_type != "webhook" or not wf.enabled:
        raise HTTPException(404, "unknown webhook")
    cfg = json.loads(wf.trigger_config)
    if not secrets.compare_digest(secret, cfg.get("secret", "")):
        raise HTTPException(401, "bad secret")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    # Execute in the threadpool: run steps make blocking HTTP calls, and the
    # event loop must stay free (a workflow that calls back into this same
    # API would otherwise deadlock).
    from fastapi.concurrency import run_in_threadpool
    run = await run_in_threadpool(execute_run, db, wf, payload)
    return {"run_id": run.id, "status": run.status}
