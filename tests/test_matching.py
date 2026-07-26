"""Regression tests for the exam-name matcher.

Each test here corresponds to a defect that silently corrupted data in the
original ``find_best_match``.
"""

from __future__ import annotations

import pytest

from gjter.matching import find_best_match, normalise


def test_exact_match_wins():
    results = [{"exam_name": "SSC CGL", "edu_qual": "Graduate"}]
    match = find_best_match("SSC CGL", results)
    assert match
    assert match.strategy == "exact"
    assert match.item["edu_qual"] == "Graduate"


def test_normalised_match_ignores_punctuation_and_filler():
    results = [{"exam_name": "rbi grade-b examination"}]
    match = find_best_match("RBI Grade B Exam", results)
    assert match
    assert match.strategy == "normalised"


def test_cse_is_never_matched_to_ese():
    """The headline bug: cutoff=0.4 mapped UPSC CSE onto UPSC ESE.

    These are different exams with different age limits and qualifications, so
    a wrong match writes engineering eligibility rules onto the IAS row.
    """
    results = [{"exam_name": "UPSC ESE", "age_limits": "21-30"}]
    match = find_best_match("UPSC CSE", results)
    assert not match, "UPSC CSE must not be satisfied by UPSC ESE data"


def test_ambiguous_candidates_are_rejected():
    results = [{"exam_name": "UPSC ESE"}, {"exam_name": "UPSC CSE "}]
    # Exact-after-normalisation should still pick the right one.
    match = find_best_match("UPSC CSE", results)
    assert match
    assert match.item["exam_name"].strip() == "UPSC CSE"


def test_blank_exam_name_is_not_a_wildcard():
    """``'' in anything`` is always True; the old fallback matched everything."""
    results = [{"exam_name": "", "age_limits": "garbage"}]
    match = find_best_match("UPSC CSE", results)
    assert not match
    assert "usable exam_name" in match.reason


def test_missing_exam_name_key_is_not_a_wildcard():
    results = [{"age_limits": "garbage"}]
    assert not find_best_match("SSC CGL", results)


def test_empty_results_returns_falsy_result():
    match = find_best_match("SSC CGL", [])
    assert not match
    assert match.item is None


def test_non_mapping_entries_are_ignored():
    results = ["not an object", 42, None, {"exam_name": "NDA Exam"}]
    match = find_best_match("NDA Exam", results)
    assert match
    assert match.item["exam_name"] == "NDA Exam"


def test_blank_database_name_is_rejected():
    assert not find_best_match("   ", [{"exam_name": "SSC CGL"}])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("UPSC  CSE", "upsc cse"),
        ("RBI Grade-B Exam", "rbi grade b"),
        ("SBI PO Examination", "sbi po"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_normalise_keeps_cse_and_ese_distinct():
    assert normalise("UPSC CSE") != normalise("UPSC ESE")
