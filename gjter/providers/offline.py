"""Offline provider backed by the curated, source-checked dataset.

This exists so the pipeline can be exercised end to end with **no API key, no
network and no cost** - which is what makes the project testable in CI and what
lets a reviewer verify the write path independently of the model.

Every record it serves was checked by hand against the conducting body's own
site; the source URL travels with the data into the database.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from ..matching import find_best_match
from .base import Provider, ProviderError, ProviderResponse

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "curated_exams.json"


@lru_cache(maxsize=4)
def load_dataset(path: str | None = None) -> dict:
    """Read and cache the curated dataset."""
    target = Path(path) if path else DATA_PATH
    if not target.exists():
        raise ProviderError(f"Curated dataset missing at {target}")
    try:
        with target.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"Curated dataset at {target} is not valid JSON: {exc}"
        ) from exc
    if "exams" not in payload:
        raise ProviderError(f"Curated dataset at {target} has no 'exams' key")
    return payload


class OfflineProvider(Provider):
    """Serves curated records. Never touches the network."""

    name = "curated-offline"

    def __init__(self, dataset_path: str | None = None, **_ignored) -> None:
        self._payload = load_dataset(dataset_path)
        self._records: list[dict] = list(self._payload.get("exams", []))
        self.meta = dict(self._payload.get("_meta", {}))

    @property
    def records(self) -> list[dict]:
        """Every curated record."""
        return list(self._records)

    def fetch_batch(self, exam_names: Sequence[str]) -> ProviderResponse:
        """Return curated records for the requested exam names.

        Uses the same strict matcher as the live path, so an exam that is not in
        the dataset is reported as missing instead of being fuzzily mapped onto
        a neighbouring exam.
        """
        found: list[dict] = []
        missing: list[str] = []
        for name in exam_names:
            match = find_best_match(name, self._records)
            if match:
                record = dict(match.item)
                record["exam_name"] = name  # echo the caller's spelling back
                found.append(record)
            else:
                missing.append(name)

        return ProviderResponse(
            records=found,
            meta={
                "provider": self.name,
                "requested": list(exam_names),
                "missing": missing,
                "compiled_on": self.meta.get("compiled_on"),
            },
        )
