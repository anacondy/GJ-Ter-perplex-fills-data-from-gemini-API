"""Matching an API response item back to the exam row that requested it.

The original ``find_best_match`` silently assigned the wrong exam's data to a
row. Two independent defects caused it:

1. ``difflib.get_close_matches(..., cutoff=0.4)``. "UPSC CSE" and "UPSC ESE"
   score ~0.88 and differ by a single character, so the wrong one wins whenever
   the right one is missing from the response.
2. The substring fallback ran ``item.get('exam_name', '')`` and tested
   ``'' in exam_name_db``, which is **always true**. Any response item with a
   missing or empty ``exam_name`` was therefore handed to the first job asked
   about, writing one exam's eligibility rules onto another exam.

The replacement is exact-match first, then a normalised exact match, then a
conservative fuzzy pass with a high cutoff that refuses ambiguous ties.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = ["normalise", "find_best_match", "MatchResult"]

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")

# Words that carry no distinguishing signal between Indian exam names.
_NOISE_WORDS = frozenset({"exam", "examination", "test", "recruitment", "the"})

#: Alphabetic tokens no longer than this are treated as acronyms and must match
#: exactly. "CSE" and "ESE" differ by one character but are different exams.
_ACRONYM_MAX_LEN = 5


def _acronyms(normalised_name: str) -> frozenset[str]:
    """Short alphabetic tokens, which act as the identity of an exam name.

    Numeric tokens (years) and long words are excluded, so ``"SSC CGL"`` still
    matches ``"SSC CGL 2025"`` while ``"UPSC CSE"`` never matches ``"UPSC ESE"``.
    """
    return frozenset(
        token
        for token in normalised_name.split()
        if token.isalpha() and len(token) <= _ACRONYM_MAX_LEN
    )


def normalise(value: Any) -> str:
    """Fold a name to a comparable form.

    Lowercases, strips accents and punctuation, collapses whitespace and drops
    filler words, so ``"RBI Grade B Exam"`` and ``"rbi grade-b"`` compare equal
    while ``"UPSC CSE"`` and ``"UPSC ESE"`` stay distinct.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT.sub(" ", text.lower())
    tokens = [t for t in _SPACE.split(text) if t and t not in _NOISE_WORDS]
    return " ".join(tokens)


class MatchResult:
    """Outcome of one match attempt, including why it succeeded or failed."""

    __slots__ = ("item", "score", "strategy", "reason")

    def __init__(
        self,
        item: Mapping | None,
        score: float = 0.0,
        strategy: str = "none",
        reason: str = "",
    ) -> None:
        self.item = item
        self.score = score
        self.strategy = strategy
        self.reason = reason

    def __bool__(self) -> bool:
        return self.item is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"MatchResult(strategy={self.strategy!r}, score={self.score:.3f}, "
            f"reason={self.reason!r})"
        )


def find_best_match(
    exam_name_db: str,
    results: Sequence[Mapping] | Iterable[Mapping],
    *,
    cutoff: float = 0.86,
    ambiguity_margin: float = 0.04,
) -> MatchResult:
    """Find the response item describing ``exam_name_db``.

    Args:
        exam_name_db: The exam name as stored in our database (the truth).
        results: Items returned by the provider.
        cutoff: Minimum similarity for a fuzzy match to be accepted.
        ambiguity_margin: If the two best fuzzy candidates are within this
            margin the match is rejected, because picking either would be a
            coin flip. This is what stops CSE/ESE cross-contamination.

    Returns:
        A :class:`MatchResult`; falsy when nothing could be matched safely.
    """
    items = [item for item in (results or []) if isinstance(item, Mapping)]
    if not items:
        return MatchResult(None, reason="empty or non-object response")

    target_raw = (exam_name_db or "").strip()
    if not target_raw:
        return MatchResult(None, reason="blank exam name in database")

    # Only consider items that actually name themselves. An item with a missing
    # or blank exam_name is unusable, never a wildcard.
    candidates = [
        (item, str(item.get("exam_name") or "").strip())
        for item in items
        if str(item.get("exam_name") or "").strip()
    ]
    if not candidates:
        return MatchResult(
            None, reason="no response item carried a usable exam_name field"
        )

    # 1. Exact, case-sensitive. The prompt asks the model to echo the name back.
    for item, name in candidates:
        if name == target_raw:
            return MatchResult(item, 1.0, "exact", "verbatim echo")

    # 2. Exact after normalisation.
    target_norm = normalise(target_raw)
    normalised = [(item, name, normalise(name)) for item, name in candidates]
    exact_norm = [entry for entry in normalised if entry[2] == target_norm]
    if len(exact_norm) == 1:
        return MatchResult(exact_norm[0][0], 1.0, "normalised", "normalised equality")
    if len(exact_norm) > 1:
        return MatchResult(
            None,
            reason=f"{len(exact_norm)} response items normalise to {target_norm!r}",
        )

    # 3. Conservative fuzzy match, guarded by an acronym check.
    #
    # Pure character similarity is not safe here: "UPSC CSE" and "UPSC ESE"
    # score 0.875, above any cutoff loose enough to absorb real formatting
    # noise. Indian exam names are identified by their acronyms, so a candidate
    # that drops or alters one is rejected outright regardless of its score.
    target_acronyms = _acronyms(target_norm)
    viable = []
    for item, name, norm in normalised:
        if target_acronyms and not target_acronyms <= _acronyms(norm):
            continue
        viable.append((item, name, norm))

    if not viable:
        return MatchResult(
            None,
            reason=(
                f"no candidate contains the identifying token(s) "
                f"{sorted(target_acronyms)} of {target_raw!r}"
            ),
        )

    scored = sorted(
        (
            (difflib.SequenceMatcher(None, target_norm, norm).ratio(), item, name)
            for item, name, norm in viable
        ),
        key=lambda entry: entry[0],
        reverse=True,
    )
    best_score, best_item, best_name = scored[0]

    if best_score < cutoff:
        return MatchResult(
            None,
            best_score,
            "fuzzy",
            f"best candidate {best_name!r} scored {best_score:.2f} < cutoff {cutoff}",
        )

    if len(scored) > 1:
        runner_up_score, _, runner_up_name = scored[1]
        if best_score - runner_up_score < ambiguity_margin:
            return MatchResult(
                None,
                best_score,
                "fuzzy",
                f"ambiguous: {best_name!r} ({best_score:.2f}) vs "
                f"{runner_up_name!r} ({runner_up_score:.2f})",
            )

    return MatchResult(best_item, best_score, "fuzzy", f"matched {best_name!r}")
