"""Seed: three demo workflows covering the engine's surface."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.models import init_db, SessionLocal, engine, Base, Workflow

BASE = "http://127.0.0.1:8123"

WORKFLOWS = [
    {
        "name": "Lead enrichment (webhook)",
        "description": "CRM webhook in → normalise fields → enrich via HTTP → draft outreach with LLM.",
        "trigger_type": "webhook",
        "trigger_config": {"secret": "demo-secret-lead"},
        "enabled": True,
        "steps": [
            {"type": "transform", "name": "normalise", "config": {"template": {
                "email": "{{ trigger.email }}", "company": "{{ trigger.company }}",
                "source": "{{ trigger.source }}",
            }}, "max_attempts": 1},
            {"type": "http_request", "name": "enrich", "config": {
                "method": "POST", "url": f"{BASE}/demo/echo",
                "body": {"email": "{{ steps.normalise.output.email }}", "company": "{{ steps.normalise.output.company }}"},
            }, "max_attempts": 3},
            {"type": "llm", "name": "draft_outreach", "config": {
                "prompt": "Write a 2-sentence outreach email to {{ steps.normalise.output.email }} at {{ steps.normalise.output.company }}.",
            }, "max_attempts": 2},
            {"type": "condition", "name": "is_enterprise", "config": {
                "left": "trigger.company_size", "op": "gt", "right": 100,
            }, "max_attempts": 1},
            {"type": "transform", "name": "flag_priority", "config": {"template": {
                "priority": "high", "reason": "company_size > 100",
            }}, "max_attempts": 1},
        ],
    },
    {
        "name": "Retry demo against flaky endpoint (webhook)",
        "description": "Calls /demo/flaky (fails twice per bucket), retried with backoff until success. Watch attempts in the run log.",
        "trigger_type": "webhook",
        "trigger_config": {"secret": "demo-secret-flaky"},
        "enabled": True,
        "steps": [
            {"type": "http_request", "name": "flaky_call", "config": {
                "method": "GET",
                "url": BASE + "/demo/flaky?fail_rate=0.3&bucket={{ trigger.bucket }}",
                "timeout_seconds": 5,
            }, "max_attempts": 4},
            {"type": "transform", "name": "summary", "config": {"template": {
                "succeeded_on_attempt": "{{ steps.flaky_call.output.attempt }}",
            }}, "max_attempts": 1},
        ],
    },
    {
        "name": "Health watchdog (interval)",
        "description": "Pings the API every 60s and records the result. Shows the interval scheduler.",
        "trigger_type": "interval",
        "trigger_config": {"interval_seconds": 60},
        "enabled": True,
        "steps": [
            {"type": "http_request", "name": "ping", "config": {
                "url": f"{BASE}/api/health", "timeout_seconds": 5,
            }, "max_attempts": 2},
        ],
    },
]


def main(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    init_db()
    db = SessionLocal()
    if db.query(Workflow).count() > 0:
        print("Already seeded — pass --reset to rebuild.")
        return
    for spec in WORKFLOWS:
        steps = spec.pop("steps")
        spec = dict(spec)
        spec["trigger_config"] = json.dumps(spec["trigger_config"])
        wf = Workflow(steps=json.dumps(steps), **spec)
        db.add(wf)
    db.commit()
    print(f"Seeded {db.query(Workflow).count()} workflows")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
