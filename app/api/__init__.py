"""HTTP API — 계획서 §4.4."""

from __future__ import annotations

from app.api.health import router as health_router
from app.api.translate import router as translate_router

__all__ = ["health_router", "translate_router"]
