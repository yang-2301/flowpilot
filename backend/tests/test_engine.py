"""Engine + API tests: retries, dead-lettering, conditions, webhook auth, replay."""
import json
import os
import tempfile

_tmpdir = tempfile.mkdtemp()
os.environ["FLOWPILOT_DB"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["FLOWPILOT_ADMIN_TOKEN"] = "test-token"
os.environ.pop("OPENAI_API_KEY", None)

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import init_db, SessionLocal, engine, Base, Workflow
from app.engine import run_steps, validate_steps, StepFailure
from app.templates import render, TemplateError

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(scope="module", autouse=True)
def _db():
    Base.metadata.drop_all(engine)
    init_db()
    yield
    Base.metadata.drop_all(engine)


DEMO_PORT = 8125
DEMO_BASE = f"http://127.0.0.1:{DEMO_PORT}"


@pytest.fixture(scope="module", autouse=True)
def demo_server():
    """The engine's http steps make REAL socket calls, so tests need a live
    server to target — run the same app on a side port for /demo/* endpoints."""
    import threading
    import time as _time
    import urllib.request as _urlreq
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=DEMO_PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        try:
            _urlreq.urlopen(f"{DEMO_BASE}/api/health", timeout=1)
            break
        except Exception:
            _time.sleep(0.2)
    yield
    server.should_exit = True


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _mk_headers():
    return AUTH


# --- engine unit tests --------------------------------------------------------

def test_transform_with_nested_paths():
    ctx = {"trigger": {"user": {"email": "a@b.c"}}, "steps": {}}
    assert render("{{ trigger.user.email }}", ctx) == "a@b.c"
    assert render({"to": "{{ trigger.user.email }}"}, ctx) == {"to": "a@b.c"}


def test_unknown_template_path_raises():
    with pytest.raises(TemplateError):
        render("{{ trigger.nope.deep }}", {"trigger": {}})


def test_condition_false_skips_remaining_steps():
    steps = [
        {"type": "condition", "name": "gate", "config": {"left": "trigger.size", "op": "gt", "right": 10}},
        {"type": "transform", "name": "after", "config": {"template": {"x": 1}}},
    ]
    out = run_steps(steps, {"size": 5})
    assert out["status"] == "skipped"
    assert [s["status"] for s in out["steps"]] == ["skipped", "skipped"]


def test_condition_true_continues():
    steps = [
        {"type": "condition", "name": "gate", "config": {"left": "trigger.size", "op": "gt", "right": 10}},
        {"type": "transform", "name": "after", "config": {"template": {"x": 1}}},
    ]
    out = run_steps(steps, {"size": 50})
    assert out["status"] == "success"
    assert out["steps"][1]["status"] == "ok"


def test_retry_then_success(monkeypatch):
    calls = {"n": 0}

    def flaky(step, context):
        calls["n"] += 1
        if calls["n"] < 3:
            raise StepFailure("boom")
        return {"attempt": calls["n"]}

    from app import engine
    monkeypatch.setitem(engine.EXECUTORS, "http_request", flaky)
    # shorten backoff for the test
    monkeypatch.setattr(engine, "_sleep_backoff", lambda attempt: None)

    steps = [{"type": "http_request", "name": "call", "config": {"url": "http://x"}, "max_attempts": 4}]
    out = run_steps(steps, {})
    assert out["status"] == "success"
    assert out["steps"][0]["attempts"] == 3


def test_exhausted_retries_fail(monkeypatch):
    from app import engine
    monkeypatch.setattr(engine, "_sleep_backoff", lambda attempt: None)

    def always_fail(step, context):
        raise StepFailure("down")

    monkeypatch.setitem(engine.EXECUTORS, "http_request", always_fail)
    steps = [{"type": "http_request", "name": "call", "config": {"url": "http://x"}, "max_attempts": 2}]
    out = run_steps(steps, {})
    assert out["status"] == "failed"
    assert "2 attempt(s)" in out["error"]


def test_validate_steps_rejects_bad_configs():
    with pytest.raises(ValueError):
        validate_steps([{"type": "nope", "config": {}}])
    with pytest.raises(ValueError):
        validate_steps([])  # empty
    with pytest.raises(ValueError):
        validate_steps([{"type": "http_request", "config": {}, "name": "a"}])  # no url
    with pytest.raises(ValueError):
        validate_steps([{"type": "transform", "config": {}, "name": "a"},
                        {"type": "transform", "config": {}, "name": "a"}])  # dup name


# --- API tests ----------------------------------------------------------------

def test_admin_token_required(client):
    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/workflows", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/workflows", headers=AUTH).status_code == 200


def test_create_workflow_rejects_invalid_steps(client):
    r = client.post("/api/workflows", headers=AUTH, json={
        "name": "bad", "trigger_type": "webhook",
        "trigger_config": {}, "steps": [{"type": "teleport", "config": {}}]})
    assert r.status_code == 422


def test_webhook_flow_end_to_end(client):
    r = client.post("/api/workflows", headers=AUTH, json={
        "name": "t-flow", "trigger_type": "webhook",
        "trigger_config": {"secret": "s3cret"},
        "steps": [
            {"type": "transform", "name": "prep", "config": {"template": {"email": "{{ trigger.email }}"}}},
            {"type": "http_request", "name": "echo", "config": {
                "method": "POST", "url": f"{DEMO_BASE}/demo/echo",
                "body": {"email": "{{ steps.prep.output.email }}"}}, "max_attempts": 2},
        ]})
    assert r.status_code == 201
    wf = r.json()

    # wrong secret rejected
    r = client.post(f"/hooks/{wf['id']}/wrong", json={"email": "x@y.z"})
    assert r.status_code == 401

    r = client.post(f"/hooks/{wf['id']}/s3cret", json={"email": "x@y.z"})
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    run = client.get(f"/api/runs/{run_id}", headers=AUTH).json()
    assert run["status"] == "success"
    assert run["steps"][0]["output"] == {"email": "x@y.z"}
    assert run["steps"][1]["output"]["echo"]["email"] == "x@y.z"


def test_webhook_unknown_workflow_404(client):
    assert client.post("/hooks/nonexistent/abc", json={}).status_code == 404


def test_interval_workflow_fires(client):
    r = client.post("/api/workflows", headers=AUTH, json={
        "name": "t-interval", "trigger_type": "interval",
        "trigger_config": {"interval_seconds": 10},
        "steps": [{"type": "http_request", "name": "ping", "config": {
            "url": f"{DEMO_BASE}/api/health"}, "max_attempts": 1}]})
    assert r.status_code == 201
    # scheduler ticks every ~2s in test env; wait for at least one run
    import time
    deadline = time.time() + 10
    seen = []
    while time.time() < deadline:
        runs = client.get("/api/runs", headers=AUTH,
                          params={"workflow_id": r.json()["id"]}).json()
        seen = runs
        if runs:
            break
        time.sleep(1)
    assert seen, "interval scheduler did not fire"
    assert seen[0]["status"] == "success"


def test_replay_reruns_same_payload(client):
    wf = client.post("/api/workflows", headers=AUTH, json={
        "name": "t-replay", "trigger_type": "webhook",
        "trigger_config": {"secret": "rp"},
        "steps": [{"type": "transform", "name": "t", "config": {"template": {"v": "{{ trigger.n }}"}}}],
    }).json()
    run_id = client.post(f"/hooks/{wf['id']}/rp", json={"n": 42}).json()["run_id"]
    replay = client.post(f"/api/runs/{run_id}/replay", headers=AUTH).json()
    assert replay["status"] == "success"
    assert replay["replay_of"] == run_id
    assert replay["steps"][0]["output"] == {"v": 42}
    assert replay["id"] != run_id
