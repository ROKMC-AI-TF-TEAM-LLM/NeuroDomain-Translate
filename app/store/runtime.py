"""SQLite 런타임 저장소 — 계획서 §5.4.

DB 서버를 쓰지 않는다 (D-19). SQLite 는 Python 표준 라이브러리라 반입 대상이
아니며, ORM 도 쓰지 않는다 — 테이블이 2개뿐이고 쿼리가 단순하다.

쓰기는 **응답 경로 밖에서** 일어나야 한다. 번역 응답을 로그 기록이 지연시키면
안 되므로 API 는 BackgroundTasks 로 넘긴다.

SQLite 는 쓰기가 직렬화되므로 단일 커넥션 + 락으로 관리한다. 다중 워커
(uvicorn --workers N)를 쓰면 프로세스마다 커넥션이 생긴다. WAL 모드면 동작하지만
워커 수는 O-04 확정 후 결정할 것 (R-12).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.logging import get_logger

logger = get_logger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class LogRecord:
    """translation_logs 한 행 (§5.4).

    운영 후 **골든셋의 원천**이 된다. 실제 사용 로그에서 대표 문장을 뽑아
    사람이 검수하면 평가셋이 된다. `glossary_version` 을 함께 남겨야
    "용어집 v16 과 v17 중 어느 쪽이 나았는가"를 나중에 따질 수 있다.
    """

    direction: str
    src: str
    tgt: str
    backend: str
    prompt_version: str
    terms_applied: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    glossary_version: int | None = None
    chunks: int = 0
    retries: int = 0
    elapsed_ms: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now_iso)


class RuntimeStore:
    """단일 커넥션 + 비동기 락.

    커넥션을 만든 스레드가 아닌 곳에서도 쓰므로 `check_same_thread=False` 를
    준다. 동시 접근은 `_lock` 이 막는다.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ── 수명 ──────────────────────────────────────────────────

    def connect(self) -> None:
        """DB 를 열고 스키마를 적용한다. 파일이 없으면 만든다."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # journal_mode 만 파일에 남는다. 나머지는 커넥션마다 다시 걸어야 한다.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        self._conn = conn
        logger.info("런타임 저장소 준비 완료: %s", self.db_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("저장소가 열려 있지 않다. connect() 먼저.")
        return self._conn

    # ── 쓰기 (비동기) ─────────────────────────────────────────

    async def log_translation(self, record: LogRecord) -> None:
        """번역 로그를 남긴다. BackgroundTasks 에서 호출한다.

        로그 실패가 번역 응답을 깨뜨리면 안 되므로 예외를 삼키고 기록만 남긴다.
        """
        try:
            async with self._lock:
                await asyncio.to_thread(self._insert_log, record)
            # 응답이 나간 뒤에 도는 백그라운드 작업이라, 로그가 없으면 기록이
            # 됐는지 확인할 방법이 없다.
            logger.debug(
                "[%s] translation_logs 기록: %s, 용어 %d건, 위반 %d건",
                record.id[:8],
                record.direction,
                len(record.terms_applied),
                len(record.violations),
            )
        except Exception as e:  # noqa: BLE001 - 로그 실패로 서비스를 멈추지 않는다
            logger.error("번역 로그 기록 실패 (id=%s): %s", record.id, e)

    async def record_term_candidates(self, texts: Iterable[str], direction: str) -> None:
        """미등록 용어 후보를 큐에 쌓는다 (§4.1 8단계).

        같은 (text, direction) 이 다시 들어오면 freq 를 올리고 last_seen 을 갱신한다.
        """
        items = [t for t in dict.fromkeys(texts) if t]
        if not items:
            return
        try:
            async with self._lock:
                await asyncio.to_thread(self._upsert_candidates, items, direction)
            logger.debug("용어 후보 큐 적재 %d건 (%s)", len(items), direction)
        except Exception as e:  # noqa: BLE001
            logger.error("용어 후보 기록 실패: %s", e)

    async def purge_old_logs(self, days: int) -> int:
        """보존 기간이 지난 로그를 지운다 (§5.4, R-13).

        무한 누적되면 디스크가 찬다. 운영 절차의 정리 주기에서 호출한다.
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete_old_logs, days)

    # ── 읽기 ──────────────────────────────────────────────────

    async def pending_candidates(self, limit: int = 100) -> list[dict]:
        """검수 대기 중인 용어 후보를 빈도순으로 준다 (Phase 6 운영용)."""
        async with self._lock:
            return await asyncio.to_thread(self._select_candidates, limit)

    async def log_count(self) -> int:
        async with self._lock:
            return await asyncio.to_thread(
                lambda: self.conn.execute("SELECT COUNT(*) FROM translation_logs").fetchone()[0]
            )

    # ── 동기 구현부 (to_thread 안에서만 호출) ─────────────────

    def _insert_log(self, r: LogRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO translation_logs (
                id, created_at, direction, src, tgt, terms_applied, violations,
                backend, prompt_version, glossary_version, chunks, retries, elapsed_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.id,
                r.created_at,
                r.direction,
                r.src,
                r.tgt,
                json.dumps(r.terms_applied, ensure_ascii=False),
                json.dumps(r.violations, ensure_ascii=False),
                r.backend,
                r.prompt_version,
                r.glossary_version,
                r.chunks,
                r.retries,
                r.elapsed_ms,
            ),
        )
        self.conn.commit()

    def _upsert_candidates(self, texts: list[str], direction: str) -> None:
        now = _now_iso()
        self.conn.executemany(
            """
            INSERT INTO term_candidates (text, direction, freq, first_seen, last_seen)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(text, direction) DO UPDATE SET
                freq = freq + 1,
                last_seen = excluded.last_seen
            """,
            [(t, direction, now, now) for t in texts],
        )
        self.conn.commit()

    def _delete_old_logs(self, days: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM translation_logs WHERE created_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        self.conn.commit()
        deleted = cur.rowcount
        if deleted:
            # VACUUM 은 트랜잭션 밖에서만 된다.
            self.conn.execute("VACUUM")
        return deleted

    def _select_candidates(self, limit: int) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT text, direction, freq, first_seen, last_seen
            FROM term_candidates
            WHERE status = 'pending'
            ORDER BY freq DESC, last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
