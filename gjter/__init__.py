"""GJ-Ter: a small, auditable pipeline that fills an Indian government-exam
database with real, sourced data.

The package is deliberately import-light: importing ``gjter`` must never pull in
an LLM SDK, must never read an API key, and must never touch the network. Those
concerns live behind :mod:`gjter.providers`, which is imported lazily.
"""

__all__ = ["__version__"]

__version__ = "1.1.0"
