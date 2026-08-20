"""용어집 — 계획서 §5.1, §6.3."""

from __future__ import annotations

from app.glossary.loader import (
    GlossaryError,
    GlossaryMeta,
    Term,
    load_glossary,
    load_meta,
)

__all__ = [
    "GlossaryError",
    "GlossaryMeta",
    "Term",
    "load_glossary",
    "load_meta",
]
