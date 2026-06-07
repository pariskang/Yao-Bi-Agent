from __future__ import annotations

import json
import re
from typing import Any


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_SINGLE_QUOTED_KEY_RE = re.compile(r"(?P<prefix>[{,]\s*)'(?P<key>[^'\\]*(?:\\.[^'\\]*)*)'\s*:")
_SINGLE_QUOTED_VALUE_RE = re.compile(r":\s*'(?P<value>[^'\\]*(?:\\.[^'\\]*)*)'(?P<suffix>\s*[,}])")


class JsonRepairError(ValueError):
    """Raised when a model response cannot be repaired into valid JSON."""


def _strip_code_fence(text: str) -> str:
    match = _CODE_FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def _extract_balanced_json(text: str) -> str:
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not starts:
        return text
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    quote = ""
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:]


def _quote_single_json(text: str) -> str:
    text = _SINGLE_QUOTED_KEY_RE.sub(lambda m: f'{m.group("prefix")}"{m.group("key")}":', text)
    text = _SINGLE_QUOTED_VALUE_RE.sub(lambda m: f': "{m.group("value")}"{m.group("suffix")}', text)
    return text


def repair_json_text(text: str) -> str:
    """Best-effort repair for common LLM JSON errors.

    This intentionally stays conservative: it handles markdown fences, prose around a
    JSON object, trailing commas, smart quotes, and simple single-quoted keys/values.
    It does not invent missing clinical fields.
    """

    candidate = _strip_code_fence(text)
    candidate = _extract_balanced_json(candidate)
    candidate = candidate.replace("\ufeff", "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    candidate = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    candidate = _quote_single_json(candidate)
    return candidate.strip()


def loads_with_repair(text: str) -> tuple[Any, dict[str, Any]]:
    """Parse JSON, repairing common model-output formatting issues.

    Returns the parsed object and metadata indicating whether repair was needed.
    """

    try:
        return json.loads(text), {"repaired": False, "strategy": "json.loads"}
    except json.JSONDecodeError as first_error:
        repaired = repair_json_text(text)
        try:
            return json.loads(repaired), {"repaired": True, "strategy": "fence_extract_trailing_comma_single_quote", "original_error": str(first_error)}
        except json.JSONDecodeError as second_error:
            raise JsonRepairError(f"Could not parse repaired JSON: {second_error}") from second_error
