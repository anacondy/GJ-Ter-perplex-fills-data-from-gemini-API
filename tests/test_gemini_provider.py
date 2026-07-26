"""Tests for the live provider's retry, refusal and parsing logic.

No network and no API key: the SDK client is replaced with a fake, so every
branch that used to be unreachable in testing is now covered.
"""

from __future__ import annotations

import pytest

from gjter.config import Settings
from gjter.providers.base import ProviderError
from gjter.providers.gemini import GeminiProvider


class FakeResponse:
    """Mimics the shape the SDK returns, including its failure modes."""

    def __init__(self, text=None, raises=None):
        self._text = text
        self._raises = raises
        self.prompt_feedback = "blocked" if raises else None

    @property
    def text(self):
        if self._raises:
            raise self._raises
        return self._text


@pytest.fixture()
def provider(monkeypatch):
    """A GeminiProvider wired to a fake legacy client."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(GeminiProvider, "_init_client", lambda self: None)
    p = GeminiProvider(settings=Settings(backoff_base_seconds=0, max_retries=3))
    p._flavour = "google-generativeai"
    return p


def _wire(provider, monkeypatch, responses):
    """Make successive calls return successive items from ``responses``."""
    calls = {"n": 0}

    def fake_call(_prompt):
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        result = responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(provider, "_call_model", fake_call)
    return calls


class TestPrompt:
    def test_prompt_lists_every_exam(self, provider):
        prompt = provider.build_prompt(["UPSC CSE", "SSC CGL"])
        assert "1. UPSC CSE" in prompt
        assert "2. SSC CGL" in prompt

    def test_prompt_forbids_invention(self, provider):
        prompt = provider.build_prompt(["UPSC CSE"])
        assert "Information not available" in prompt
        assert "Do not invent cutoff marks" in prompt

    def test_prompt_warns_against_blending_similar_names(self, provider):
        assert "Never blend facts" in provider.build_prompt(["UPSC CSE", "UPSC ESE"])

    def test_prompt_requests_a_source(self, provider):
        assert "source_url" in provider.build_prompt(["UPSC CSE"])


class TestFetchBatch:
    def test_happy_path(self, provider, monkeypatch):
        _wire(provider, monkeypatch, ['[{"exam_name": "SSC CGL"}]'])
        response = provider.fetch_batch(["SSC CGL"])
        assert len(response) == 1
        assert response.meta["attempts"] == 1

    def test_markdown_fences_are_tolerated(self, provider, monkeypatch):
        _wire(provider, monkeypatch, ['```json\n[{"exam_name": "SSC CGL"}]\n```'])
        assert len(provider.fetch_batch(["SSC CGL"])) == 1

    def test_object_wrapper_is_unwrapped(self, provider, monkeypatch):
        _wire(provider, monkeypatch, ['{"exams": [{"exam_name": "SSC CGL"}]}'])
        assert len(provider.fetch_batch(["SSC CGL"])) == 1

    def test_retries_then_succeeds(self, provider, monkeypatch):
        calls = _wire(
            provider,
            monkeypatch,
            [Exception("429 rate limit exceeded"), '[{"exam_name": "SSC CGL"}]'],
        )
        response = provider.fetch_batch(["SSC CGL"])
        assert calls["n"] == 2
        assert response.meta["attempts"] == 2

    def test_gives_up_after_max_retries(self, provider, monkeypatch):
        calls = _wire(provider, monkeypatch, [Exception("503 unavailable")])
        with pytest.raises(ProviderError, match="after 3 attempt"):
            provider.fetch_batch(["SSC CGL"])
        assert calls["n"] == 3

    def test_non_retryable_error_fails_fast(self, provider, monkeypatch):
        calls = _wire(provider, monkeypatch, [ProviderError("API key not valid")])
        with pytest.raises(ProviderError):
            provider.fetch_batch(["SSC CGL"])
        assert calls["n"] == 1, "an auth failure must not be retried"

    def test_malformed_json_is_retried_then_reported(self, provider, monkeypatch):
        calls = _wire(provider, monkeypatch, ["I cannot help with that."])
        with pytest.raises(ProviderError):
            provider.fetch_batch(["SSC CGL"])
        assert calls["n"] == 3

    def test_empty_batch_short_circuits(self, provider):
        assert len(provider.fetch_batch([])) == 0

    def test_missing_echo_is_reported_in_meta(self, provider, monkeypatch):
        _wire(provider, monkeypatch, ['[{"exam_name": "SSC CGL"}]'])
        response = provider.fetch_batch(["SSC CGL", "UPSC CSE"])
        assert response.meta["missing_exact_echo"] == ["UPSC CSE"]

    def test_non_object_entries_are_dropped(self, provider, monkeypatch):
        _wire(provider, monkeypatch, ['["junk", 42, {"exam_name": "SSC CGL"}]'])
        response = provider.fetch_batch(["SSC CGL"])
        assert len(response) == 1


class TestResponseExtraction:
    def test_safety_block_raises_with_reason(self):
        """The old code let this surface as an empty batch and a success line."""
        response = FakeResponse(raises=ValueError("blocked"))
        with pytest.raises(ProviderError, match="Could not read response text"):
            GeminiProvider._text_from_legacy(response)

    def test_empty_text_raises(self):
        with pytest.raises(ProviderError, match="empty text"):
            GeminiProvider._text_from_legacy(FakeResponse(text=""))

    def test_valid_text_passes_through(self):
        assert GeminiProvider._text_from_legacy(FakeResponse(text="[]")) == "[]"


class TestRetryClassification:
    @pytest.mark.parametrize(
        "message",
        [
            "429 Too Many Requests",
            "503 Service Unavailable",
            "deadline exceeded",
            "connection reset by peer",
            "The model is overloaded",
            "Resource has been exhausted",
        ],
    )
    def test_transient_errors_are_retryable(self, provider, message):
        assert provider._is_retryable(Exception(message))

    @pytest.mark.parametrize(
        "message",
        ["API key not valid", "permission denied", "model not found"],
    )
    def test_permanent_errors_are_not_retryable(self, provider, message):
        assert not provider._is_retryable(ProviderError(message))
