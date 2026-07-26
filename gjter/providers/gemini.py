"""Live Gemini provider.

Fixes carried over from the original ``ask_gemini_batch``:

* The API key is read from the environment, never from a source literal.
* Supports the current ``google-genai`` SDK and falls back to the legacy
  ``google-generativeai`` package, whose support ended on 30 November 2025.
* ``response.text`` is never accessed blindly: a blocked or truncated candidate
  raises inside the SDK, and that used to be swallowed by a bare ``except``.
  The finish reason and any safety block are surfaced instead.
* Transient failures (429, 5xx, timeouts) are retried with exponential backoff
  and jitter. The original slept a flat 30 s and moved on, losing the batch.
* The prompt pins the response schema and forbids invention, and asks for a
  per-field source URL so claims can be audited.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Sequence
from typing import Any

from ..config import Settings, load_api_key
from ..validation import ValidationError, extract_json
from .base import Provider, ProviderError, ProviderResponse, RetryableProviderError

log = logging.getLogger(__name__)

#: Substrings that mark an error as worth retrying.
_RETRYABLE_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "rate limit",
    "resource has been exhausted",
    "quota",
    "deadline",
    "timeout",
    "timed out",
    "unavailable",
    "internal error",
    "overloaded",
    "connection reset",
    "temporarily",
)

RESPONSE_SCHEMA_HINT = """Return a JSON array. Each element must be an object
with exactly these keys:
  "exam_name"        - echo the requested name back character for character
  "nationality"      - who may apply, by citizenship
  "age_limits"       - the unreserved-category age band and the reckoning date
  "age_relax"        - category-wise relaxations
  "edu_qual"         - minimum educational qualification
  "attempts"         - attempt limits by category
  "physical_std"     - physical or medical standards, or that none apply
  "stages"           - the selection stages in order
  "num_papers"       - number of papers at each stage
  "q_type"           - objective, descriptive, or the mix
  "duration"         - time allowed per paper
  "marking_scheme"   - total marks and any negative marking
  "official_website" - the conducting body's own domain, as a full https URL
  "year"             - the year the cutoffs below refer to
  "cutoffs"          - array of {"category": "...", "score": "..."}; use [] if
                       the body does not publish official cutoffs
  "source_url"       - the official page these facts were taken from
"""


class GeminiProvider(Provider):
    """Calls the Gemini API for structured exam facts."""

    name = "gemini"

    def __init__(
        self,
        settings: Settings | None = None,
        api_key: str | None = None,
        model: str | None = None,
        **_ignored,
    ) -> None:
        self.settings = settings or Settings()
        self.model_name = model or self.settings.model
        self._api_key = load_api_key(api_key, required=True)
        self._client: Any = None
        self._flavour: str = ""
        self._init_client()

    # ------------------------------------------------------------------ setup

    def _init_client(self) -> None:
        """Bind to whichever Gemini SDK is installed."""
        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self._api_key)
            self._flavour = "google-genai"
            log.debug("Using google-genai SDK")
            return
        except ImportError:
            pass
        except Exception as exc:  # pragma: no cover - SDK-specific
            raise ProviderError(
                f"Could not initialise google-genai client: {exc}"
            ) from exc

        try:
            import google.generativeai as legacy  # type: ignore

            legacy.configure(api_key=self._api_key)
            self._client = legacy.GenerativeModel(
                self.model_name,
                generation_config={"response_mime_type": "application/json"},
            )
            self._flavour = "google-generativeai"
            log.warning(
                "Using the legacy google-generativeai SDK. Support for it ended on "
                "2025-11-30; install 'google-genai' instead."
            )
            return
        except ImportError as exc:
            raise ProviderError(
                "No Gemini SDK installed. Install one with:\n"
                "    pip install google-genai\n"
                "Or run without a key using: python data_scout.py --offline"
            ) from exc
        except Exception as exc:  # pragma: no cover - SDK-specific
            raise ProviderError(f"Could not initialise Gemini client: {exc}") from exc

    # ---------------------------------------------------------------- prompting

    def build_prompt(self, exam_names: Sequence[str]) -> str:
        """Compose the batch prompt.

        Names are numbered so the model cannot silently merge two exams, and the
        instruction block forbids guessing - an unverifiable field must come
        back as the sentinel rather than as a plausible invention.
        """
        listing = "\n".join(f"{i}. {name}" for i, name in enumerate(exam_names, 1))
        return f"""You are compiling a reference table of Indian government
recruitment exams.

Provide details for exactly these {len(exam_names)} exams, one object per exam,
in the same order:
{listing}

{RESPONSE_SCHEMA_HINT}

Hard rules:
- Return ONLY the JSON array. No prose, no markdown fences, no trailing commas.
- Echo "exam_name" exactly as written above. Do not rename, expand or merge them.
- These are distinct exams even when the names look similar. Never blend facts
  between them.
- If you cannot verify a field from the conducting body's own published
  material, set it to the exact string "Information not available".
  A wrong confident answer is far worse than that sentinel.
- Do not invent cutoff marks. Many bodies never publish them; return [] instead.
- Every value must be a plain string, except "cutoffs" which is an array of
  objects. Do not nest objects inside the other fields.
"""

    # ------------------------------------------------------------------ calling

    def _call_model(self, prompt: str) -> str:
        """One API call. Returns raw response text."""
        if self._flavour == "google-genai":
            from google.genai import types  # type: ignore

            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return self._text_from_genai(response)

        response = self._client.generate_content(prompt)
        return self._text_from_legacy(response)

    @staticmethod
    def _text_from_genai(response: Any) -> str:
        """Pull text out of a google-genai response, explaining any refusal."""
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            feedback = getattr(response, "prompt_feedback", None)
            raise ProviderError(
                f"Model returned no candidates (prompt_feedback={feedback!r})"
            )
        finish = str(getattr(candidates[0], "finish_reason", "") or "")
        if "MAX_TOKENS" in finish.upper():
            raise RetryableProviderError(
                "Response truncated at the token limit; retry with a smaller batch"
            )
        if "SAFETY" in finish.upper() or "BLOCK" in finish.upper():
            raise ProviderError(f"Response blocked by safety filters ({finish})")
        text = getattr(response, "text", None)
        if not text:
            raise ProviderError(f"Model returned empty text (finish_reason={finish})")
        return text

    @staticmethod
    def _text_from_legacy(response: Any) -> str:
        """Same, for the legacy SDK, where ``.text`` raises rather than returns."""
        try:
            text = response.text
        except (ValueError, AttributeError) as exc:
            feedback = getattr(response, "prompt_feedback", None)
            raise ProviderError(
                f"Could not read response text ({exc}); prompt_feedback={feedback!r}"
            ) from exc
        if not text:
            raise ProviderError("Model returned empty text")
        return text

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, RetryableProviderError):
            return True
        if isinstance(exc, ValidationError):
            return True  # a malformed body is often transient; one more try is cheap
        blob = f"{type(exc).__name__} {exc}".lower()
        return any(marker in blob for marker in _RETRYABLE_MARKERS)

    def _sleep_for_attempt(self, attempt: int) -> None:
        delay = min(
            self.settings.backoff_base_seconds * (2 ** (attempt - 1)),
            self.settings.backoff_max_seconds,
        )
        delay += random.uniform(0, delay * 0.25)  # jitter, to avoid lockstep retries
        log.info("Retrying in %.1fs (attempt %d)", delay, attempt + 1)
        time.sleep(delay)

    # ------------------------------------------------------------------- public

    def fetch_batch(self, exam_names: Sequence[str]) -> ProviderResponse:
        """Fetch one batch, retrying transient failures with backoff."""
        if not exam_names:
            return ProviderResponse([], {"provider": self.name, "requested": []})

        prompt = self.build_prompt(exam_names)
        attempts = max(1, self.settings.max_retries)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                raw = self._call_model(prompt)
                parsed = extract_json(raw)

                if isinstance(parsed, dict):
                    # Models sometimes wrap the array in {"exams": [...]}.
                    for key in ("exams", "data", "results", "items"):
                        if isinstance(parsed.get(key), list):
                            parsed = parsed[key]
                            break
                    else:
                        parsed = [parsed]

                if not isinstance(parsed, list):
                    raise ValidationError(
                        f"expected a JSON array, got {type(parsed).__name__}"
                    )

                records = [item for item in parsed if isinstance(item, dict)]
                returned = {str(r.get("exam_name", "")).strip() for r in records}
                missing = [n for n in exam_names if n not in returned]

                return ProviderResponse(
                    records=records,
                    meta={
                        "provider": self.name,
                        "model": self.model_name,
                        "sdk": self._flavour,
                        "attempts": attempt,
                        "requested": list(exam_names),
                        "returned": len(records),
                        "missing_exact_echo": missing,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - classified immediately below
                last_error = exc
                if attempt >= attempts or not self._is_retryable(exc):
                    break
                log.warning("Batch attempt %d/%d failed: %s", attempt, attempts, exc)
                self._sleep_for_attempt(attempt)

        raise ProviderError(
            f"Gemini request failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def close(self) -> None:
        self._client = None
