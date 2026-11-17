"""Base types shared by booking-platform adapters."""

from __future__ import annotations


class SourceError(RuntimeError):
    """Source returned something we could not use (and did not guess around)."""


class SourceUnavailable(SourceError):
    """Source refused automated access; caller must preserve the last snapshot."""


def source_error_message(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"
