"""Tests for JSON extraction, coercion and URL validation."""

from __future__ import annotations

import pytest

from gjter.config import UNKNOWN
from gjter.validation import (
    ValidationError,
    clean_cutoffs,
    clean_record,
    coerce_scalar,
    extract_json,
    validate_url,
)


class TestExtractJson:
    def test_plain_array(self):
        assert extract_json('[{"a": 1}]') == [{"a": 1}]

    def test_markdown_fenced(self):
        raw = '```json\n[{"exam_name": "SSC CGL"}]\n```'
        assert extract_json(raw) == [{"exam_name": "SSC CGL"}]

    def test_fence_without_language(self):
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_prose_around_json(self):
        raw = 'Here you go:\n[{"a": 1}]\nHope that helps!'
        assert extract_json(raw) == [{"a": 1}]

    def test_trailing_commas_repaired(self):
        assert extract_json('[{"a": 1,},]') == [{"a": 1}]

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError):
            extract_json("")

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            extract_json(None)

    def test_unparseable_raises_with_preview(self):
        with pytest.raises(ValidationError, match="could not parse JSON"):
            extract_json("I'm sorry, I cannot help with that request.")


class TestCoerceScalar:
    def test_string_passthrough(self):
        assert coerce_scalar("Graduate") == "Graduate"

    def test_none_becomes_sentinel(self):
        assert coerce_scalar(None) == UNKNOWN

    def test_list_is_joined(self):
        """sqlite3 raises InterfaceError on a list; the old code hit this."""
        assert coerce_scalar(["Prelims", "Mains", "Interview"]) == (
            "Prelims; Mains; Interview"
        )

    def test_nested_dict_is_flattened(self):
        assert coerce_scalar({"SC": "5 years", "OBC": "3 years"}) == (
            "SC: 5 years; OBC: 3 years"
        )

    def test_numbers(self):
        assert coerce_scalar(3) == "3"
        assert coerce_scalar(2.5) == "2.5"

    def test_bool(self):
        assert coerce_scalar(True) == "Yes"
        assert coerce_scalar(False) == "No"

    @pytest.mark.parametrize("value", ["N/A", "null", "unknown", "-", "  "])
    def test_nullish_spellings_normalise(self, value):
        assert coerce_scalar(value) == UNKNOWN

    def test_whitespace_collapsed(self):
        assert coerce_scalar("a\n\n  b") == "a b"

    def test_long_value_truncated(self):
        assert len(coerce_scalar("x" * 9000)) <= 4000

    def test_result_is_always_bindable(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (v TEXT)")
        for value in ([1, 2], {"a": [1]}, None, True, 3.5, "ok"):
            conn.execute("INSERT INTO t VALUES (?)", (coerce_scalar(value),))
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 6


class TestValidateUrl:
    def test_valid_https(self):
        assert validate_url("https://upsc.gov.in") == "https://upsc.gov.in"

    def test_www_gets_scheme(self):
        assert validate_url("www.ibps.in") == "https://www.ibps.in"

    def test_sentinel_rejected(self):
        """Must never render 'Information not available' as a link."""
        assert validate_url(UNKNOWN) is None

    def test_prose_rejected(self):
        assert validate_url("Check the official website") is None

    def test_none_rejected(self):
        assert validate_url(None) is None

    def test_trailing_punctuation_stripped(self):
        assert validate_url("https://ssc.gov.in.") == "https://ssc.gov.in"


class TestCleanCutoffs:
    def test_documented_shape(self):
        rows = clean_cutoffs(
            [{"category": "General", "score": "92.66"}], year_hint="2025"
        )
        assert rows == [{"category": "General", "score": "92.66", "year": "2025"}]

    def test_mapping_shape_is_accepted(self):
        rows = clean_cutoffs({"General": "92.66", "OBC": "92.00"}, year_hint="2025")
        assert len(rows) == 2
        assert rows[0]["category"] == "General"

    def test_rows_without_score_are_dropped(self):
        assert clean_cutoffs([{"category": "General"}]) == []

    def test_rows_without_category_are_dropped(self):
        assert clean_cutoffs([{"score": "90"}]) == []

    def test_none_and_empty(self):
        assert clean_cutoffs(None) == []
        assert clean_cutoffs([]) == []

    def test_limit_is_enforced(self):
        many = [{"category": f"C{i}", "score": "1"} for i in range(200)]
        assert len(clean_cutoffs(many)) == 40


class TestCleanRecord:
    def test_missing_fields_become_sentinel(self):
        out = clean_record({"nationality": "Indian"}, fields=("nationality", "attempts"))
        assert out["nationality"] == "Indian"
        assert out["attempts"] == UNKNOWN

    def test_non_mapping_raises(self):
        with pytest.raises(ValidationError):
            clean_record("nope", fields=("a",))
