"""Pluggable data providers.

Importing this package must stay cheap: the Gemini SDK is only imported when
:func:`get_provider` is actually asked for ``"gemini"``. That keeps
``--offline`` runs, unit tests and ``gjter status`` free of both the dependency
and the API key requirement.
"""

from __future__ import annotations

from .base import Provider, ProviderError, ProviderResponse

__all__ = ["Provider", "ProviderError", "ProviderResponse", "get_provider"]


def get_provider(name: str, **kwargs) -> Provider:
    """Instantiate a provider by name.

    Args:
        name: ``"gemini"`` for the live API, ``"offline"`` for the bundled
            curated dataset (no network, no key).

    Raises:
        ProviderError: The name is unknown.
    """
    key = (name or "").strip().lower()
    if key in {"offline", "local", "curated", "none"}:
        from .offline import OfflineProvider

        return OfflineProvider(**kwargs)
    if key in {"gemini", "google", "genai"}:
        from .gemini import GeminiProvider

        return GeminiProvider(**kwargs)
    raise ProviderError(
        f"Unknown provider {name!r}. Available providers: 'gemini', 'offline'."
    )
