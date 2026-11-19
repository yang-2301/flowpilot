"""Template resolution: `{{ trigger.user.email }}` / `{{ steps.lookup.output.id }}`.

Minimal, dependency-free, and deliberately strict: unknown paths raise
TemplateError so broken configs fail loudly at run time instead of
silently shipping empty strings.
"""
import re
from typing import Any, Mapping

TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
MAX_DEPTH = 12


class TemplateError(ValueError):
    pass


def _resolve_path(path: str, context: Mapping[str, Any]) -> Any:
    node: Any = context
    for part in path.split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise TemplateError(f"unknown path '{path}'")
    return node


def render(value: Any, context: Mapping[str, Any], depth: int = 0) -> Any:
    """Recursively render strings inside arbitrary JSON structures."""
    if depth > MAX_DEPTH:
        raise TemplateError("template nesting too deep")
    if isinstance(value, str):
        # Whole-string template keeps the value's type (numbers, objects).
        whole = TEMPLATE_RE.fullmatch(value.strip())
        if whole:
            return _resolve_path(whole.group(1), context)
        return TEMPLATE_RE.sub(
            lambda m: str(_resolve_path(m.group(1), context)), value)
    if isinstance(value, dict):
        return {k: render(v, context, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context, depth + 1) for v in value]
    return value


def dig(path: str, context: Mapping[str, Any]) -> Any:
    """Resolve a dotted path without template syntax (for conditions)."""
    return _resolve_path(path, context)
