"""엔드포인트 공용 의존성.

앱 수명 객체(레지스트리 · 저장소 · 오케스트레이터)는 `app.state` 에 두고
여기서 꺼낸다. 모듈 전역에 두지 않는 이유는 테스트가 인스턴스를 갈아끼울 수
있어야 하기 때문이다.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.config import Settings
from app.glossary.index import IndexRegistry
from app.pipeline.orchestrator import Orchestrator
from app.store.runtime import RuntimeStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> IndexRegistry:
    return request.app.state.registry


def get_store(request: Request) -> RuntimeStore:
    return request.app.state.store


def get_orchestrator(request: Request) -> Orchestrator:
    """인덱스가 아직 준비되지 않았으면 503 을 낸다 (§6.7).

    기동 중 요청을 받아 반쪽 인덱스로 번역하는 것보다 거절하는 편이 낫다.
    """
    registry: IndexRegistry = request.app.state.registry
    if not registry.ready:
        detail = registry.last_error or "인덱스 준비 중입니다. 잠시 후 다시 시도하십시오."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return request.app.state.orchestrator
