"""Parsing, repairing and validating provider output.

The original code called ``json.loads(response.text)`` directly and trusted the
result. That failed in three ways seen in practice:

* ``response.text`` raises if the model returned no candidate (safety block or
  ``MAX_TOKENS``); the bare ``except`` swallowed it and returned ``[]``.
* Models wrap JSON in ``` fences even when asked not to.
* Nested values arrive as lists or dicts, and sqlite3 refuses to bind those,
  raising ``InterfaceError`` per row. The old code caught that per job and
  printed a database error, so entire exams silently ended up with no data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .config import UNKNOWN

__all__ = [
    "extract_json",
    "coerce_scalar",
    "clean_record",
    "clean_cutoffs",
    "validate_url",
    "ValidationError",
]


class ValidationError(ValueError):
    """Raised when provider output cannot be turned into usable records."""


_FENCE = re.compile(
    r"^\s*```(?:json|JSON)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL
)
_TRAILING_COMMA = re.compile(r",\s*(?=[}\]])")

#: Strings a model uses to mean "I don't know". Normalised to :data:`UNKNOWN`.
_NULLISH = frozenset(
    {
        "",
        "n/a",
        "na",
        "null",
        "none",
        "nil",
        "unknown",
        "not available",
        "not applicable",
        "information not available",
        "no information",
        "tbd",
        "-",
        "--",
    }
)


def extract_json(raw: str) -> Any:
    """Parse JSON out of a model response, tolerating common wrappers.

    Tries, in order: the raw string, the contents of a fenced code block, and
    the outermost ``[...]`` or ``{...}`` slice with trailing commas removed.

    Raises:
        ValidationError: Nothing JSON-shaped could be recovered.
    """
    if raw is None:
        raise ValidationError("provider returned no text at all")
    text = str(raw).strip()
    if not text:
        raise ValidationError("provider returned an empty string")

    attempts = [text]

    fenced = _FENCE.match(text)
    if fenced:
        attempts.append(fenced.group("body"))

    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            attempts.append(text[start : end + 1])

    errors = []
    for attempt in attempts:
        for candidate in (attempt, _TRAILING_COMMA.sub("", attempt)):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                errors.append(str(exc))

    preview = text[:200].replace("\n", " ")
    raise ValidationError(
        f"could not parse JSON from response (first error: {errors[0]}); "
        f"response began: {preview!r}"
    )


def coerce_scalar(value: Any, *, default: str = UNKNOWN, max_length: int = 4000) -> str:
    """Flatten any JSON value into a single trimmed string sqlite3 can bind.

    Lists become ``"a; b; c"``, dicts become ``"key: value; ..."``, and
    "don't know" spellings collapse to :data:`~gjter.config.UNKNOWN`. This is
    what stops the ``InterfaceError: Error binding parameter`` failures.
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, Mapping):
        parts = [
            f"{k}: {coerce_scalar(v, default='')}".strip(": ")
            for k, v in value.items()
        ]
        flattened = "; ".join(p for p in parts if p)
    elif isinstance(value, (list, tuple, set)):
        parts = [coerce_scalar(v, default="") for v in value]
        flattened = "; ".join(p for p in parts if p and p != default)
    else:
        flattened = str(value)

    flattened = re.sub(r"\s+", " ", flattened).strip()
    if flattened.lower() in _NULLISH:
        return default
    if len(flattened) > max_length:
        flattened = flattened[: max_length - 1].rstrip() + "…"
    return flattened or default


def validate_url(value: Any) -> str | None:
    """Return a plausible ``http(s)`` URL, or ``None``.

    Deliberately strict: a hallucinated ``"Information not available"`` must
    never be written into ``jobs.official_website``, because a reader will
    render it as a link.
    """
    if value is None:
        return None
    text = coerce_scalar(value, default="")
    if not text or text == UNKNOWN:
        return None
    text = text.split(";")[0].strip().rstrip(".,)")
    if text.startswith("www."):
        text = "https://" + text
    if not re.match(r"^https?://", text, re.IGNORECASE):
        return None
    if " " in text or "." not in text:
        return None
    if len(text) > 500:
        return None
    return text


def clean_record(record: Mapping, *, fields: Iterable[str]) -> dict[str, str]:
    """Coerce every requested field of one response item to a bindable string."""
    if not isinstance(record, Mapping):
        raise ValidationError(f"expected an object, got {type(record).__name__}")
    return {field: coerce_scalar(record.get(field)) for field in fields}


def clean_cutoffs(value: Any, *, year_hint: Any = None, limit: int = 40) -> list[dict]:
    """Normalise the ``cutoffs`` array into rows for ``job_cutoffs``.

    Accepts the documented ``[{"category": ..., "score": ...}]`` shape and also
    the ``{"General": 95.4, ...}`` mapping that models return roughly a third of
    the time. Rows without a usable category are dropped rather than stored as
    ``"Information not available"`` noise.
    """
    if value is None:
        return []

    default_year = coerce_scalar(year_hint, default="")
    rows: list[dict] = []

    if isinstance(value, Mapping):
        pairs: list[tuple[Any, Any]] = list(value.items())
        entries = [{"category": k, "score": v} for k, v in pairs]
    elif isinstance(value, (list, tuple)):
        entries = list(value)
    else:
        return []

    for entry in entries:
        if isinstance(entry, Mapping):
            category = coerce_scalar(
                entry.get("category", entry.get("Category")), default=""
            )
            score = coerce_scalar(entry.get("score", entry.get("Score")), default="")
            year = coerce_scalar(
                entry.get("year", entry.get("Year")), default=default_year
            )
        else:
            category = coerce_scalar(entry, default="")
            score = ""
            year = default_year

        if not category or category == UNKNOWN:
            continue
        if not score or score == UNKNOWN:
            continue

        rows.append(
            {
                "category": category,
                "score": score,
                "year": year or default_year or UNKNOWN,
            }
        )
        if len(rows) >= limit:
            break

    return rows
