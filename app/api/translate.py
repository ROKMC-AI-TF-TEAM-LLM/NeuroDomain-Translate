"""POST /translate — 계획서 §4.4.

로그 기록이 번역 응답을 지연시키면 안 된다. BackgroundTasks 로 분리한다 (§5.4).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.deps import get_orchestrator, get_settings, get_store
from app.api.schemas import TranslateRequest, TranslateResponse
from app.config import Settings
from app.logging import get_logger
from app.pipeline.orchestrator import (
    InputTooLongError,
    Orchestrator,
    UnsupportedDirectionError,
    resolve_direction,
)
from app.store.runtime import RuntimeStore

logger = get_logger(__name__)

router = APIRouter(tags=["translate"])


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    req: TranslateRequest,
    bg: BackgroundTasks,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    store: RuntimeStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> TranslateResponse:
    try:
        direction = resolve_direction(req.source, req.target)
    except UnsupportedDirectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    style = req.style or settings.default_style

    try:
        outcome = await orchestrator.run(req.text, direction, style)
    except InputTooLongError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
        ) from e

    # 응답을 보낸 뒤에 기록한다 (§5.4).
    if outcome.log_record is not None:
        bg.add_task(store.log_translation, outcome.log_record)
    if outcome.unknown_candidates:
        bg.add_task(store.record_term_candidates, outcome.unknown_candidates, direction)

    return TranslateResponse(
        translation=outcome.translation,
        terms_applied=outcome.terms_applied,
        warnings=outcome.warnings,
        meta=outcome.meta,
    )
