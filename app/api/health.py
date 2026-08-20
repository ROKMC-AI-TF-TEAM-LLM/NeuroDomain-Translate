"""헬스체크, 모델 상태 — 계획서 §4.2, §6.7."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app import __version__
from app.api.deps import get_registry, get_settings
from app.api.schemas import HealthResponse, ReloadResponse
from app.config import Settings
from app.glossary.index import IndexRegistry
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    registry: IndexRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """인덱스 빌드 중에는 `ready=false` 를 반환한다 (§6.7).

    로드밸런서·오케스트레이터가 이 값을 보고 트래픽을 붙인다. 기동 시간이
    10~20초 걸리므로 이 신호가 없으면 준비 전 요청이 들어온다.
    """
    stats = registry.stats()

    backend = request.app.state.backend
    try:
        backend_ready = await backend.health()
    except NotImplementedError:
        backend_ready = False
    except Exception as e:  # noqa: BLE001 - 헬스체크가 예외로 죽으면 안 된다
        logger.warning("백엔드 헬스체크 실패: %s", e)
        backend_ready = False

    if registry.last_error:
        return HealthResponse(
            status="error",
            ready=False,
            version=__version__,
            backend=settings.backend,
            backend_ready=backend_ready,
            detail=registry.last_error,
        )

    ready = bool(stats.get("ready")) and backend_ready
    return HealthResponse(
        status="ok" if ready else "starting",
        ready=ready,
        version=__version__,
        backend=settings.backend,
        backend_ready=backend_ready,
        glossary_version=stats.get("glossary_version"),
        term_count=stats.get("term_count"),
        build_ms=stats.get("build_ms"),
        segmenter=stats.get("segmenter"),
        matcher=stats.get("matcher"),
        tm_size=stats.get("tm_size"),
        model=getattr(backend, "served_name", None) or None,
    )


@router.post(
    "/admin/reload",
    response_model=ReloadResponse,
    status_code=status.HTTP_200_OK,
)
async def reload_glossary(
    registry: IndexRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> ReloadResponse:
    """glossary.jsonl 교체 후 호출한다 (§6.7 핫리로드).

    새 인덱스를 완전히 빌드한 뒤 참조를 원자적으로 교체한다. 빌드에 실패하면
    기존 인덱스를 유지하고 오류를 반환한다 — 잘못된 용어집으로 교체되는 것이
    서비스 중단보다 나쁘다.

    ⚠ 기본값은 **비활성**이다. 이 엔드포인트는 인증이 없으므로 O-07(인증 방식)
    이 정해지기 전에 다수 사용자 환경(D-07)에 열어 두면 안 된다.
    `NDT_ADMIN_ENABLED=true` 로 켠다.
    """
    if not settings.admin_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="관리 엔드포인트가 비활성 상태입니다 (O-07 인증 방식 미확정).",
        )
    try:
        snapshot = await registry.reload()
    except Exception as e:  # noqa: BLE001 - 원인을 그대로 알려야 고칠 수 있다
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"용어집 재적재 실패, 기존 인덱스를 유지합니다: {e}",
        ) from e

    return ReloadResponse(
        glossary_version=snapshot.version,
        term_count=len(snapshot.ko2en.terms),
        build_ms=snapshot.build_ms,
    )
