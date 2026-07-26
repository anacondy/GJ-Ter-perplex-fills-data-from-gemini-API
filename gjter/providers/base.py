"""Provider interface shared by the live and offline backends."""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """A provider could not fulfil a request."""


class RetryableProviderError(ProviderError):
    """A transient failure (rate limit, 5xx, timeout). Worth retrying."""


@dataclass
class ProviderResponse:
    """What a provider returns for one batch."""

    #: One mapping per exam the provider could describe.
    records: list[dict] = field(default_factory=list)
    #: Free-form backend detail, surfaced in logs and the run report.
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.records)


class Provider(abc.ABC):
    """Fetches structured exam facts for a batch of exam names."""

    #: Short identifier recorded in ``data_source`` columns.
    name: str = "provider"

    @abc.abstractmethod
    def fetch_batch(self, exam_names: Sequence[str]) -> ProviderResponse:
        """Return facts for each name in ``exam_names``.

        Implementations should return whatever they could resolve rather than
        raising when only some names are unknown.
        """

    def close(self) -> None:
        """Release any held resources. Safe to call more than once."""

    def __enter__(self) -> Provider:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
