"""Step engine: executes workflow steps with retries, backoff and dead-lettering.

Step types:
  transform     — render a JSON template against the run context
  http_request  — call an HTTP endpoint (urllib, timeout, template body)
  llm           — LLM completion (OpenAI when configured; mock offline mode)
  condition     — compare two context paths; false => remaining steps skipped

Every step result lands in context["steps"][<name>] = {"output": ..., "status": ...}.
"""
import json
import random
import time
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, List, Mapping, Optional

from .config import (BACKOFF_BASE_SECONDS, MAX_STEP_ATTEMPTS,
                     OPENAI_API_KEY, LLM_MODEL)
from .templates import render, dig, TemplateError

STEP_TYPES = {"transform", "http_request", "llm", "condition"}
COMPARATORS = {"eq", "ne", "gt", "lt", "contains"}


class StepFailure(Exception):
    """Permanent failure of a step after exhausting retries."""


def _sleep_backoff(attempt: int) -> None:
    # Exponential with full jitter (README documents "jittered backoff"):
    # randomising the delay prevents thundering-herd retries when many runs
    # fail against the same endpoint at once. Capped at 10s.
    delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    time.sleep(random.uniform(0, min(delay, 10)))


def _http_request(step: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    cfg = render(dict(step.get("config", {})), context)
    url = cfg["url"]
    method = cfg.get("method", "GET").upper()
    headers = {str(k): str(v) for k, v in cfg.get("headers", {}).items()}
    body = cfg.get("body")
    data = None
    if body is not None:
        payload = body if isinstance(body, str) else json.dumps(body)
        data = payload.encode()
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_seconds", 15)) as resp:
            raw = resp.read().decode()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except urllib.error.HTTPError as exc:
        raise StepFailure(f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StepFailure(f"request to {url} failed: {exc}") from exc


def _llm(step: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    cfg = render(dict(step.get("config", {})), context)
    prompt = cfg["prompt"]
    system = cfg.get("system", "You are a helpful automation assistant.")

    if not OPENAI_API_KEY:
        # Offline mock: keeps the engine demoable without credentials.
        # Documented honestly in the README; production uses the real API.
        return {"mode": "mock", "prompt": prompt,
                "completion": f"[mock llm] processed: {prompt[:120]}"}

    import json as _json
    body = _json.dumps({
        "model": cfg.get("model", LLM_MODEL),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": cfg.get("temperature", 0.2),
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
        return {"mode": "openai", "completion": data["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as exc:
        raise StepFailure(f"LLM API returned HTTP {exc.code}") from exc


def _transform(step: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    return render(step.get("config", {}).get("template", {}), context)


def _condition(step: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    cfg = render(dict(step.get("config", {})), context)
    left = dig(cfg["left"], context)
    op = cfg.get("op", "eq")
    right = cfg.get("right")
    if op not in COMPARATORS:
        raise StepFailure(f"unknown comparator '{op}'")
    result = {
        "eq": lambda: left == right,
        "ne": lambda: left != right,
        "gt": lambda: float(left) > float(right),
        "lt": lambda: float(left) < float(right),
        "contains": lambda: right in left if isinstance(left, (str, list, dict)) else False,
    }[op]()
    if not result:
        raise _ConditionFalse()
    return {"condition": True, "left": left, "op": op, "right": right}


class _ConditionFalse(Exception):
    """Internal: condition evaluated false => skip remaining steps."""


EXECUTORS: Dict[str, Callable[[Mapping, Mapping], Any]] = {
    "transform": _transform,
    "http_request": _http_request,
    "llm": _llm,
    "condition": _condition,
}


def validate_steps(steps: List[Dict[str, Any]]) -> None:
    """Static validation at save time: fail broken configs before they run."""
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    if len(steps) == 0:
        raise ValueError("workflow needs at least one step")
    names = set()
    for i, step in enumerate(steps):
        if step.get("type") not in STEP_TYPES:
            raise ValueError(f"step {i}: type must be one of {sorted(STEP_TYPES)}")
        name = step.get("name") or f"step_{i + 1}"
        if name in names:
            raise ValueError(f"step {i}: duplicate name '{name}'")
        names.add(name)
        if step.get("type") == "http_request" and "url" not in step.get("config", {}):
            raise ValueError(f"step {i} ({name}): http_request requires config.url")
        if step.get("type") == "llm" and "prompt" not in step.get("config", {}):
            raise ValueError(f"step {i} ({name}): llm requires config.prompt")
        if step.get("type") == "condition":
            cfg = step.get("config", {})
            if "left" not in cfg:
                raise ValueError(f"step {i} ({name}): condition requires config.left")
        max_attempts = step.get("max_attempts", 1)
        if not (1 <= int(max_attempts) <= MAX_STEP_ATTEMPTS):
            raise ValueError(f"step {i} ({name}): max_attempts must be 1..{MAX_STEP_ATTEMPTS}")


def run_steps(steps: List[Dict[str, Any]], trigger_payload: Dict[str, Any],
              on_step_start=None, on_step_finish=None) -> Dict[str, Any]:
    """Execute steps sequentially. Returns a summary dict.

    Raises StepFailure after retries are exhausted; _ConditionFalse => skipped.
    """
    context: Dict[str, Any] = {"trigger": trigger_payload, "steps": {}}
    summary: Dict[str, Any] = {"status": "success", "steps": []}

    for i, step in enumerate(steps):
        name = step.get("name") or f"step_{i + 1}"
        step_type = step["type"]
        max_attempts = int(step.get("max_attempts", 1))

        record: Dict[str, Any] = {"idx": i, "name": name, "type": step_type,
                                  "status": "pending", "attempts": 0,
                                  "duration_ms": 0, "error": None,
                                  "output": None}
        summary["steps"].append(record)
        if on_step_start:
            on_step_start(record, step, context)

        started = time.perf_counter()
        last_error: Optional[Exception] = None
        output: Any = None
        for attempt in range(1, max_attempts + 1):
            record["attempts"] = attempt
            try:
                output = EXECUTORS[step_type](step, context)
                last_error = None  # success clears earlier failures
                break
            except _ConditionFalse:
                record["status"] = "skipped"
                record["attempts"] = 1
                record["output"] = {"condition": False}
                summary["status"] = "skipped"
                context["steps"][name] = {"output": {"condition": False}, "status": "skipped"}
                # Skip all remaining steps.
                for later in steps[i + 1:]:
                    lname = later.get("name") or f"step_{len(summary['steps']) + 1}"
                    summary["steps"].append({"idx": summary["steps"][-1]["idx"] + 1,
                                             "name": lname, "type": later["type"],
                                             "status": "skipped", "attempts": 0,
                                             "duration_ms": 0, "error": None,
                                             "output": None})
                return summary
            except Exception as exc:  # noqa: BLE001 — a failing step must never 500 the API
                last_error = exc
                if attempt < max_attempts:
                    _sleep_backoff(attempt)
        elapsed = int((time.perf_counter() - started) * 1000)
        record["duration_ms"] = elapsed

        if last_error is not None:
            record["status"] = "failed"
            record["error"] = str(last_error)
            summary["status"] = "failed"
            summary["error"] = f"step '{name}' failed after {record['attempts']} attempt(s): {last_error}"
            context["steps"][name] = {"output": None, "status": "failed"}
            return summary

        record["status"] = "ok"
        record["output"] = output
        context["steps"][name] = {"output": output, "status": "ok"}
        if on_step_finish:
            on_step_finish(record, step, context)

    return summary
