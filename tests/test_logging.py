"""로깅 — `app/logging.py`.

로그는 조용히 썩는다. 포맷이 어긋나거나 줄이 사라져도 테스트가 없으면
사고가 난 뒤에야 안다. 특히 환각 경고(§6.5)는 프론트에 표시 위치가 없어
**로그가 유일한 통로**다.
"""

from __future__ import annotations

import logging

import pytest

from app.logging import DATE_FORMAT, LOG_FORMAT, get_logger, setup_logging


@pytest.fixture(autouse=True)
def restore_logging():
    """테스트가 전역 로깅 상태를 건드리므로 되돌린다."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)


@pytest.fixture
def app_logs(caplog):
    """`app.*` 로그를 caplog 로 잡는다.

    `get_logger` 는 루트와의 중복 출력을 막으려고 `propagate=False` 로 둔다.
    그런데 pytest 의 caplog 는 루트에 핸들러를 붙여 잡으므로 그대로면 아무것도
    안 잡힌다. 테스트 동안만 전파를 켠다.

    운영에서 로그를 외부로 모을 일이 생기면 같은 제약을 만난다 — 루트를
    타지 않으므로 `app.*` 로거에 직접 핸들러를 달아야 한다.
    """
    loggers = [
        logging.getLogger(name)
        for name in list(logging.root.manager.loggerDict)
        if name.startswith("app.")
    ]
    saved = [(lg, lg.propagate) for lg in loggers]
    for lg, _ in saved:
        lg.propagate = True
    yield caplog
    for lg, prev in saved:
        lg.propagate = prev


def rendered(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


# ── 팩토리 ────────────────────────────────────────────────────


def test_logger_has_a_handler_and_does_not_propagate() -> None:
    """루트로 전파되면 같은 줄이 두 번 찍힌다."""
    logger = get_logger("app.test.factory")
    assert logger.handlers
    assert logger.propagate is False


def test_repeated_calls_do_not_stack_handlers() -> None:
    """모듈이 여러 번 import 돼도 핸들러가 쌓이면 안 된다."""
    first = get_logger("app.test.idempotent")
    count = len(first.handlers)
    for _ in range(3):
        get_logger("app.test.idempotent")
    assert len(first.handlers) == count


def test_level_comes_from_settings(settings) -> None:
    logger = get_logger("app.test.level")
    assert logging.getLevelName(logger.level) == settings.log_level


# ── 포맷 ──────────────────────────────────────────────────────


def test_format_includes_time_level_name_message() -> None:
    record = logging.LogRecord(
        name="app.pipeline.orchestrator",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[a3f10c2b] 번역 시작: ko2en, 24자",
        args=(),
        exc_info=None,
    )
    line = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT).format(record)

    assert "INFO" in line
    assert "app.pipeline.orchestrator" in line
    assert "[a3f10c2b] 번역 시작: ko2en, 24자" in line
    # 밀리초: 청크 병렬 처리(§6.6)의 간격이 구분돼야 한다
    assert line.startswith("[")
    stamp = line[1 : line.index("]")]
    assert stamp.count(":") == 2
    assert "." in stamp


def test_setup_logging_normalizes_third_party_handlers() -> None:
    """uvicorn 은 자기 포맷의 핸들러를 단다. 걷어내야 한 포맷으로 섞인다."""
    uvicorn = logging.getLogger("uvicorn.access")
    uvicorn.addHandler(logging.StreamHandler())
    uvicorn.propagate = False

    setup_logging("INFO")

    assert uvicorn.handlers == []
    assert uvicorn.propagate is True


def test_setup_logging_is_safe_to_call_twice() -> None:
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_transport_noise_is_capped_at_debug() -> None:
    """앱을 DEBUG 로 보려고 루트를 내려도 전송 계층 로그가 쏟아지면 안 된다.

    `httpcore` 는 TCP 연결과 HTTP 프레임마다 한 줄씩 찍어 우리 로그를 덮는다.
    """
    setup_logging("DEBUG")
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.INFO
    # uvicorn 은 하한이 없어 루트를 따른다.
    assert logging.getLogger("uvicorn.access").level == logging.NOTSET


# ── 파이프라인이 실제로 찍는가 ────────────────────────────────


def test_translate_request_is_logged(client, app_logs) -> None:
    """요청 하나가 시작 · 분할 · 사전분석 · 완료로 남아야 한다."""
    with app_logs.at_level(logging.INFO):
        res = client.post(
            "/translate",
            json={"text": "합참은 연합훈련을 실시했다고 밝혔다.", "source": "ko", "target": "en"},
        )
    assert res.status_code == 200

    text = rendered(app_logs)
    assert "번역 시작" in text
    assert "분할" in text
    assert "사전분석" in text
    assert "번역 완료" in text


def test_request_id_ties_lines_together(client, app_logs) -> None:
    """동시 요청이 섞이므로 한 요청의 줄을 골라낼 수 있어야 한다."""
    with app_logs.at_level(logging.INFO):
        client.post(
            "/translate",
            json={"text": "합참은 밝혔다.", "source": "ko", "target": "en"},
        )

    lines = [r.getMessage() for r in app_logs.records if r.name == "app.pipeline.orchestrator"]
    ids = {line[1:9] for line in lines if line.startswith("[")}
    assert len(ids) == 1, f"요청 하나에 id 가 여러 개다: {ids}"


def test_request_id_matches_the_db_row(client, data_dir) -> None:
    """콘솔 한 줄에서 translation_logs 행을 찾을 수 있어야 사고 조사가 된다."""
    import sqlite3

    res = client.post(
        "/translate",
        json={"text": "합참은 밝혔다.", "source": "ko", "target": "en"},
    )
    assert res.status_code == 200

    conn = sqlite3.connect(data_dir / "runtime.db")
    rows = conn.execute("SELECT id FROM translation_logs").fetchall()
    conn.close()
    assert len(rows) == 1
    # 로그의 [xxxxxxxx] 는 이 id 의 앞 8자다.
    assert len(rows[0][0]) == 36  # UUID


def test_hallucination_warning_reaches_the_log(client, app_logs) -> None:
    """**이것이 이 파일의 핵심이다.**

    환각 경고는 프론트에 표시 위치가 없다 (§4.4). 로그에도 안 남으면
    아무도 모르고 지나간다.
    """
    with app_logs.at_level(logging.WARNING):
        res = client.post(
            "/translate",
            json={
                # mock 은 입력을 그대로 돌려준다 → en2ko 출력에 한글이 없다
                "text": "The unit completed its scheduled maintenance work today without incident.",
                "source": "en",
                "target": "ko",
            },
        )
    assert res.status_code == 200

    warnings = [r for r in app_logs.records if r.levelno >= logging.WARNING]
    assert warnings, "경고가 응답에는 실렸는데 로그에는 없다"
    text = "\n".join(r.getMessage() for r in warnings)
    assert "타깃 언어가 아님" in text


def test_over_length_input_is_logged(client, app_logs) -> None:
    with app_logs.at_level(logging.WARNING):
        res = client.post(
            "/translate",
            json={"text": "가" * 5001, "source": "ko", "target": "en"},
        )
    assert res.status_code == 413
    assert "입력 길이 초과" in rendered(app_logs)
