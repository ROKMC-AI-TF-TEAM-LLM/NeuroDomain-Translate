"""로깅 유틸: 통일 포맷 로거 팩토리.

- 각 모듈: ``logger = get_logger(__name__)``
- 진입점(main.py, tools/*): ``setup_logging()`` 을 함께 호출해
  서드파티(httpx, uvicorn 등) 로그까지 같은 포맷으로 맞춘다

출력 예: ``[19:26:31.482] INFO app.pipeline.orchestrator: [a3f10c2b] 번역 시작: ...``
로그 레벨은 `NDT_LOG_LEVEL`(.env)로 제어한다.

계획서 §4.2 에 이 모듈이 없다. 진입점과 파이프라인 전 구간이 같은 포맷을
써야 요청 하나를 처음부터 끝까지 따라갈 수 있어 추가했다.

**에어갭 (§9.3)**: 로그는 표준 출력으로만 나간다. 원격 수집기로 보내지 않는다.
원문이 로그에 남을 수 있으므로(§5.4) 보존 기간과 접근 권한은 운영 절차 사항이다.
"""

from __future__ import annotations

import logging

from app.config import get_settings

# 밀리초 포함: 청크 병렬 처리(§6.6)의 간격이 로그에서 구분돼야 한다
LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

#: 자기 핸들러를 다는 서드파티 로거. setup_logging 이 루트 포맷으로 되돌린다.
#:
#: 값은 **하한 레벨**이다. None 이면 루트 레벨을 따른다. 우리 앱을 DEBUG 로
#: 보려고 루트를 DEBUG 로 내리면 전송 계층 로그가 함께 쏟아져 정작 봐야 할
#: 줄을 덮는다 — `httpcore` 는 TCP 연결과 HTTP 프레임마다 한 줄씩 찍는다.
_THIRD_PARTY_LEVELS: dict[str, int | None] = {
    "uvicorn": None,
    "uvicorn.error": None,
    "uvicorn.access": None,
    # 요청당 한 줄이라 쓸모가 있다.
    "httpx": logging.INFO,
    # 프레임 단위라 DEBUG 에서 우리 로그를 덮는다.
    "httpcore": logging.WARNING,
}


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """통일 포맷 로거를 반환한다. 모듈 상단에서 logger = get_logger(__name__) 로 사용."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(get_settings().log_level.upper())
        handler = logging.StreamHandler()
        handler.setFormatter(_make_formatter())
        logger.addHandler(handler)
        logger.propagate = False  # 루트 핸들러와의 중복 출력 방지
    return logger


def setup_logging(level: str | None = None) -> None:
    """루트 로거에 같은 포맷을 적용한다 (서드파티 로그용). 중복 호출 안전."""
    resolved = (level or get_settings().log_level).upper()
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(_make_formatter())
        root.setLevel(resolved)
    else:
        logging.basicConfig(level=resolved, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    # uvicorn 은 자기 포맷의 핸들러를 단다. 걷어내고 루트로 흘려보내야
    # 접속 로그와 우리 로그가 한 포맷으로 섞인다.
    root_level = logging.getLevelName(resolved)
    for name, floor in _THIRD_PARTY_LEVELS.items():
        third = logging.getLogger(name)
        third.handlers.clear()
        third.propagate = True
        if floor is not None and isinstance(root_level, int):
            third.setLevel(max(root_level, floor))
        else:
            third.setLevel(logging.NOTSET)
