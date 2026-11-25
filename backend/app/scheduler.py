"""Interval scheduler: background thread that fires interval workflows."""
import json
import threading
import time
import traceback
from typing import Optional

from .models import SessionLocal, Workflow, Run, StepRun, new_uuid, now_iso
from .engine import run_steps


class Scheduler:
    """Polls for due interval workflows. One thread; DB is the source of truth.

    Keeps its own last-fired map in memory: restarting the process re-arms
    intervals from now, which is the sane behaviour for a demo-grade engine.
    """

    def __init__(self, tick_seconds: int = 5):
        self.tick_seconds = tick_seconds
        self._last_fired: dict = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="flowpilot-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self._tick()
            except Exception:
                traceback.print_exc()

    def _tick(self) -> None:
        db = SessionLocal()
        try:
            workflows = (db.query(Workflow)
                         .filter(Workflow.enabled == True,  # noqa: E712
                                 Workflow.trigger_type == "interval")
                         .all())
            now = time.time()
            for wf in workflows:
                cfg = json.loads(wf.trigger_config or "{}")
                interval = max(int(cfg.get("interval_seconds", 300)), 10)
                last = self._last_fired.get(wf.id, 0)
                if now - last >= interval:
                    self._last_fired[wf.id] = now
                    execute_run(db, wf, {"trigger": "interval", "fired_at": now_iso()})
        finally:
            db.close()


def execute_run(db, workflow: Workflow, payload: dict,
                replay_of: Optional[str] = None) -> Run:
    """Create a Run row and execute the workflow's steps synchronously."""
    from .engine import run_steps

    run = Run(id=new_uuid(), workflow_id=workflow.id,
              trigger_payload=json.dumps(payload), status="running",
              replay_of=replay_of)
    db.add(run)
    db.flush()

    steps = json.loads(workflow.steps)
    from .engine import run_steps as _run
    summary = _run(steps, payload)

    for rec in summary["steps"]:
        db.add(StepRun(
            id=new_uuid(), run_id=run.id, idx=str(rec["idx"]),
            name=rec["name"], type=rec["type"], status=rec["status"],
            input="{}", output=json.dumps(rec["output"]) if rec["output"] is not None else None,
            error=rec["error"], attempts=str(rec["attempts"]),
            duration_ms=str(rec["duration_ms"]),
        ))

    run.status = summary["status"]
    if summary["status"] == "failed":
        run.error = summary.get("error")
        # Failed runs stay queryable for replay; "dead" marks runs that
        # exhausted retries AND were not replayed within their workflow's policy.
        run.status = "dead" if any(
            s["attempts"] > 1 and s["status"] == "failed" for s in summary["steps"]) else "failed"
    run.finished_at = now_iso()
    db.commit()
    db.refresh(run)
    return run
