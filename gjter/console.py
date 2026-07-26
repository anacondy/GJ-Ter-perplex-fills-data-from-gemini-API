"""Console output that survives a legacy Windows code page.

On Windows, ``sys.stdout`` often uses cp1252 (or cp437 in older consoles), which
cannot encode ``₹``, ``→`` or ``…``. Printing any of those raises
``UnicodeEncodeError`` and kills the process - so ``python app.py`` and
``gjter export`` crashed on a stock Git Bash / PowerShell console before this
module existed.

Python 3.7+ lets us reconfigure the stream to UTF-8, which fixes it outright on
modern terminals (Windows Terminal, VS Code, and Git Bash all handle UTF-8).
Where reconfiguration is not possible we fall back to transliterating the few
characters this project actually emits.
"""

from __future__ import annotations

import sys
from typing import TextIO

#: Fallbacks for the non-ASCII characters this project prints.
_TRANSLITERATIONS = {
    "\u20b9": "Rs.",  # ₹
    "\u2192": "->",  # →
    "\u2190": "<-",  # ←
    "\u2026": "...",  # …
    "\u2013": "-",  # – en dash
    "\u2014": "--",  # — em dash
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00b7": "-",  # ·
    "\u2713": "OK",  # ✓
    "\u2717": "x",  # ✗
}


def enable_utf8() -> bool:
    """Try to switch stdout/stderr to UTF-8.

    Returns:
        True if both streams can now handle non-ASCII text.
    """
    ok = True
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            ok = ok and _stream_supports_unicode(stream)
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            ok = ok and _stream_supports_unicode(stream)
    return ok


def _stream_supports_unicode(stream: TextIO) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "\u20b9\u2192".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def supports_unicode(stream: TextIO | None = None) -> bool:
    """Whether ``stream`` (default stdout) can render the characters we use."""
    return _stream_supports_unicode(stream or sys.stdout)


def safe(text: str, *, stream: TextIO | None = None) -> str:
    """Return ``text``, transliterated only if the console cannot encode it."""
    if supports_unicode(stream):
        return text
    for char, replacement in _TRANSLITERATIONS.items():
        text = text.replace(char, replacement)
    encoding = getattr(stream or sys.stdout, "encoding", None) or "ascii"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def emit(text: str = "") -> None:
    """``print`` that cannot raise ``UnicodeEncodeError``."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(safe(text), flush=True)
