"""Runtime configuration.

Every knob that used to be a hardcoded literal in ``data_scout.py`` lives here
and can be overridden through the environment. Nothing in this module reads a
secret at import time; :func:`load_api_key` is called explicitly by whoever
needs it, so tests and ``--offline`` runs never require a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Repository root (the directory that holds this package).
BASE_DIR = Path(__file__).resolve().parent.parent

#: Default on-disk location of the SQLite database.
DEFAULT_DB_PATH = BASE_DIR / "jobs.db"

#: Environment variables consulted for the API key, in priority order.
API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

#: Placeholder values that used to sit in source control. Treated as "no key".
PLACEHOLDER_KEYS = frozenset(
    {"", "KEY HERE", "YOUR_API_KEY", "YOUR_KEY_HERE", "CHANGEME", "TODO"}
)

#: Sentinel written when a fact genuinely could not be established.
UNKNOWN = "Information not available"


class ConfigError(RuntimeError):
    """Raised when the runtime configuration is unusable."""


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the effective runtime configuration."""

    db_path: Path = DEFAULT_DB_PATH
    model: str = "gemini-2.5-flash"
    batch_size: int = 5
    #: Seconds to sleep between batches. Only applied between real API calls.
    batch_pause_seconds: float = 20.0
    #: Attempts per batch before giving up (1 = no retry).
    max_retries: int = 4
    #: Base delay for exponential backoff, in seconds.
    backoff_base_seconds: float = 2.0
    #: Upper bound on a single backoff sleep.
    backoff_max_seconds: float = 60.0
    request_timeout_seconds: float = 120.0
    #: When true, no network call is made and no row is written.
    dry_run: bool = False
    #: Minimum difflib ratio for a fuzzy exam-name match to be accepted.
    match_cutoff: float = 0.86
    extra: dict = field(default_factory=dict)

    def replace(self, **changes) -> Settings:
        """Return a copy with ``changes`` applied (dataclasses.replace shim)."""
        import dataclasses

        return dataclasses.replace(self, **changes)


def load_api_key(explicit: str | None = None, *, required: bool = True) -> str | None:
    """Resolve the Gemini API key.

    Resolution order: an explicit argument, then each variable in
    :data:`API_KEY_ENV_VARS`. Placeholder strings that were historically
    committed to source control are rejected as if unset.

    Args:
        explicit: A key supplied directly by the caller (e.g. a CLI flag).
        required: When true, raise instead of returning ``None``.

    Raises:
        ConfigError: ``required`` is true and no usable key was found.
    """
    candidates = [explicit] if explicit else []
    candidates += [os.environ.get(name) for name in API_KEY_ENV_VARS]

    for candidate in candidates:
        if candidate is None:
            continue
        key = candidate.strip()
        if key and key.upper() not in {p.upper() for p in PLACEHOLDER_KEYS}:
            return key

    if required:
        raise ConfigError(
            "No Gemini API key found. Export one before running:\n"
            "    export GEMINI_API_KEY='your-key'\n"
            "Get a key at https://aistudio.google.com/apikey .\n"
            "Never commit the key: it belongs in the environment or a .env file "
            "that is listed in .gitignore."
        )
    return None


def settings_from_env(**overrides) -> Settings:
    """Build :class:`Settings`, layering env vars under explicit overrides."""

    def _env_num(name: str, cast, default):
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{name}={raw!r} is not a valid number") from exc

    base = Settings(
        db_path=Path(os.environ.get("GJTER_DB_PATH", str(DEFAULT_DB_PATH))),
        model=os.environ.get("GJTER_MODEL", Settings.model),
        batch_size=_env_num("GJTER_BATCH_SIZE", int, Settings.batch_size),
        batch_pause_seconds=_env_num(
            "GJTER_BATCH_PAUSE", float, Settings.batch_pause_seconds
        ),
        max_retries=_env_num("GJTER_MAX_RETRIES", int, Settings.max_retries),
    )
    clean = {k: v for k, v in overrides.items() if v is not None}
    return base.replace(**clean) if clean else base
