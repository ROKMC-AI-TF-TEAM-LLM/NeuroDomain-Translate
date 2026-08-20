"""번역 백엔드 — 계획서 §4.3."""

from __future__ import annotations

from app.backends.base import (
    TermHint,
    TranslationBackend,
    TranslationRequest,
    TranslationResult,
)
from app.backends.mock import MockBackend

__all__ = [
    "TermHint",
    "TranslationBackend",
    "TranslationRequest",
    "TranslationResult",
    "MockBackend",
    "build_backend",
]

#: OpenAI 호환 프로토콜을 쓰는 서버들. 구현은 하나다.
_OPENAI_COMPAT = {"openai", "vllm", "llamacpp"}


def build_backend(settings) -> TranslationBackend:  # noqa: ANN001 - 순환 import 회피
    """설정에 따라 백엔드를 만든다."""
    if settings.backend == "mock":
        return MockBackend()

    if settings.backend in _OPENAI_COMPAT:
        # httpx 는 코어 의존성이라 여기서 import 해도 안전하지만, mock 만 쓰는
        # 경로에서 불필요한 import 를 피하려고 지연시킨다.
        from app.backends.vllm_openai import OpenAICompatBackend

        return OpenAICompatBackend(
            base_url=settings.vllm_base_url,
            served_name=settings.vllm_served_name,
            timeout_s=settings.vllm_timeout_s,
            temperature=settings.gen_temperature,
            top_p=settings.gen_top_p,
            max_tokens=settings.gen_max_tokens,
            label=settings.backend,
        )

    raise ValueError(f"알 수 없는 백엔드: {settings.backend!r}")
