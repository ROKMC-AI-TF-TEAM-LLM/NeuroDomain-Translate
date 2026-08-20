"""런타임 저장소 — 계획서 §5.4.

Phase 0 완료 기준: `runtime.db` 가 최초 기동 시 자동 생성되고 로그가 기록된다.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.store.runtime import LogRecord, RuntimeStore


@pytest.fixture
def store(tmp_path: Path):
    s = RuntimeStore(tmp_path / "runtime.db")
    s.connect()
    yield s
    s.close()


def record(**overrides) -> LogRecord:
    base = {
        "direction": "ko2en",
        "src": "합참은 밝혔다.",
        "tgt": "The JCS said.",
        "backend": "mock",
        "prompt_version": "ko2en-press-v1",
        "glossary_version": 1,
        "chunks": 1,
        "retries": 0,
        "elapsed_ms": 12,
    }
    return LogRecord(**{**base, **overrides})


def test_db_file_is_created_on_connect(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runtime.db"
    s = RuntimeStore(path)
    s.connect()
    assert path.is_file()
    s.close()


def test_wal_mode_is_enabled(store: RuntimeStore) -> None:
    """동시 읽기/쓰기를 위해 WAL 이어야 한다 (§5.4, R-12)."""
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_schema_is_idempotent(tmp_path: Path) -> None:
    """재기동할 때마다 스키마를 다시 적용해도 안전해야 한다."""
    path = tmp_path / "runtime.db"
    for _ in range(3):
        s = RuntimeStore(path)
        s.connect()
        s.close()
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"translation_logs", "term_candidates"} <= tables


@pytest.mark.asyncio
async def test_log_translation_writes_row(store: RuntimeStore) -> None:
    await store.log_translation(record())
    assert await store.log_count() == 1


@pytest.mark.asyncio
async def test_log_keeps_glossary_version(store: RuntimeStore) -> None:
    """용어집 v16 과 v17 중 어느 쪽이 나았는지 따지려면 이 값이 필요하다 (§5.4)."""
    await store.log_translation(record(glossary_version=17))
    row = store.conn.execute("SELECT glossary_version FROM translation_logs").fetchone()
    assert row[0] == 17


@pytest.mark.asyncio
async def test_log_serialises_terms_as_json(store: RuntimeStore) -> None:
    await store.log_translation(record(terms_applied=[{"term_id": "T-0142", "target": "JCS"}]))
    row = store.conn.execute("SELECT terms_applied FROM translation_logs").fetchone()
    assert json.loads(row[0])[0]["term_id"] == "T-0142"


@pytest.mark.asyncio
async def test_log_failure_does_not_raise(store: RuntimeStore) -> None:
    """로그 실패가 번역 응답을 깨뜨리면 안 된다."""
    store.close()
    await store.log_translation(record())  # 예외가 새어나오지 않아야 한다


@pytest.mark.asyncio
async def test_term_candidates_accumulate_frequency(store: RuntimeStore) -> None:
    await store.record_term_candidates(["천무-Ⅱ"], "ko2en")
    await store.record_term_candidates(["천무-Ⅱ"], "ko2en")
    row = store.conn.execute(
        "SELECT freq, status FROM term_candidates WHERE text = ?", ("천무-Ⅱ",)
    ).fetchone()
    assert row[0] == 2
    assert row[1] == "pending"


@pytest.mark.asyncio
async def test_term_candidates_are_deduped_within_a_call(store: RuntimeStore) -> None:
    await store.record_term_candidates(["천무", "천무"], "ko2en")
    row = store.conn.execute(
        "SELECT freq FROM term_candidates WHERE text = ?", ("천무",)
    ).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_pending_candidates_sorted_by_frequency(store: RuntimeStore) -> None:
    await store.record_term_candidates(["희귀어"], "ko2en")
    for _ in range(3):
        await store.record_term_candidates(["빈발어"], "ko2en")
    rows = await store.pending_candidates()
    assert rows[0]["text"] == "빈발어"


@pytest.mark.asyncio
async def test_purge_removes_only_old_logs(store: RuntimeStore) -> None:
    """보존 기간(기본 180일) 정리 (§5.4, R-13)."""
    await store.log_translation(record())
    store.conn.execute(
        "INSERT INTO translation_logs "
        "(id, created_at, direction, src, tgt, backend, prompt_version) "
        "VALUES ('old', datetime('now', '-400 days'), 'ko2en', 'a', 'b', 'mock', 'v1')"
    )
    store.conn.commit()
    assert await store.log_count() == 2

    deleted = await store.purge_old_logs(180)
    assert deleted == 1
    assert await store.log_count() == 1


@pytest.mark.asyncio
async def test_translate_endpoint_writes_a_log(client, data_dir: Path) -> None:
    """Phase 0 완료 기준: 요청 한 건이 로그 한 줄이 된다."""
    res = client.post(
        "/translate",
        json={"text": "합참은 밝혔다.", "source": "ko", "target": "en"},
    )
    assert res.status_code == 200

    conn = sqlite3.connect(data_dir / "runtime.db")
    rows = conn.execute(
        "SELECT direction, backend, prompt_version, chunks FROM translation_logs"
    ).fetchall()
    conn.close()
    assert rows == [("ko2en", "mock", "ko2en-press-v1", 1)]
