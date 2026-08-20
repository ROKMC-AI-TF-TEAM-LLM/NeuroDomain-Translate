"""인덱스 생명주기 — 계획서 §6.7.

Aho-Corasick 인덱스, Kiwi 사용자 사전, BM25 인덱스는 **매 요청마다 만들면 안 된다.**
앱 시작 시 1회 빌드하고 메모리에 상주시킨다.

구현 범위:
  - Phase 0: 용어집 · 메타 로드, 버전 기반 재빌드 판단, 준비 상태 노출, 원자적 교체.
  - Phase 2: Aho-Corasick 오토마톤, Kiwi 풀, BM25 인덱스 빌드.

빌드 시간이 10~20초 걸리므로(§6.7) 그동안 헬스체크가 `not ready` 를 반환해야 한다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config import Settings
from app.glossary.loader import GlossaryMeta, Term, load_glossary, load_meta
from app.glossary.matcher import GlossaryAutomaton, automaton_available
from app.glossary.morph import AnalyzerPool, build_pool, kiwi_available
from app.logging import get_logger
from app.tm.loader import load_tm
from app.tm.retriever import BM25Retriever, retriever_available

logger = get_logger(__name__)


@dataclass
class GlossaryIndex:
    """한 방향(ko2en / en2ko)의 매칭 인덱스."""

    direction: str
    terms: list[Term]
    by_id: dict[str, Term] = field(default_factory=dict)
    #: Aho-Corasick 오토마톤. pyahocorasick 이 없으면 None 이고, 그때는
    #: 용어 매칭 없이 번역만 된다.
    automaton: GlossaryAutomaton | None = None

    @classmethod
    def build(cls, direction: str, terms: list[Term]) -> GlossaryIndex:
        automaton: GlossaryAutomaton | None = None
        if automaton_available():
            try:
                automaton = GlossaryAutomaton(direction, terms)
            except Exception as e:  # noqa: BLE001
                logger.error("%s 오토마톤 생성 실패: %s", direction, e)
        else:
            logger.warning(
                "pyahocorasick 이 없어 용어 매칭 없이 동작한다. "
                "requirements-nlp.txt 를 설치할 것"
            )
        return cls(
            direction=direction,
            terms=terms,
            by_id={t.id: t for t in terms},
            automaton=automaton,
        )


@dataclass
class IndexSnapshot:
    """한꺼번에 교체되는 인덱스 묶음.

    참조를 통째로 바꾸므로 교체 도중의 요청이 반쪽 상태를 보지 않는다 (§6.7).
    """

    version: int
    meta: GlossaryMeta
    ko2en: GlossaryIndex
    en2ko: GlossaryIndex
    build_ms: int
    #: Kiwi 분석기 풀. kiwipiepy 미설치이거나 use_kiwi=False 면 None 이고,
    #: 그때는 규칙 기반 문장 분할기로 떨어진다 (D-22).
    kiwi_pool: AnalyzerPool | None = None
    #: 방향별 TM 검색기. tm.jsonl 이 비었거나 rank-bm25 가 없으면 None.
    tm_ko2en: BM25Retriever | None = None
    tm_en2ko: BM25Retriever | None = None


class IndexRegistry:
    """인덱스 소유자. 앱 수명 동안 하나만 둔다."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._snapshot: IndexSnapshot | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    # ── 상태 ──────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._snapshot is not None

    @property
    def version(self) -> int | None:
        return self._snapshot.version if self._snapshot else None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def snapshot(self) -> IndexSnapshot:
        if self._snapshot is None:
            raise RuntimeError("인덱스가 아직 준비되지 않았다. ensure_loaded() 먼저.")
        return self._snapshot

    def index_for(self, direction: str) -> GlossaryIndex:
        snap = self.snapshot
        return snap.ko2en if direction == "ko2en" else snap.en2ko

    @property
    def kiwi_pool(self) -> AnalyzerPool | None:
        return self._snapshot.kiwi_pool if self._snapshot else None

    def automaton_for(self, direction: str) -> GlossaryAutomaton | None:
        if self._snapshot is None:
            return None
        return self.index_for(direction).automaton

    def tm_for(self, direction: str) -> BM25Retriever | None:
        if self._snapshot is None:
            return None
        snap = self._snapshot
        return snap.tm_ko2en if direction == "ko2en" else snap.tm_en2ko

    def stats(self) -> dict:
        if self._snapshot is None:
            return {"ready": False, "last_error": self._last_error}
        snap = self._snapshot
        return {
            "ready": True,
            "glossary_version": snap.version,
            "term_count": len(snap.ko2en.terms),
            "updated_at": snap.meta.updated_at.isoformat(),
            "build_ms": snap.build_ms,
            "segmenter": "kiwi" if snap.kiwi_pool else "rule",
            "matcher": "aho-corasick" if snap.ko2en.automaton else "none",
            "tm_size": len(snap.tm_ko2en) if snap.tm_ko2en else 0,
        }

    # ── 적재 ──────────────────────────────────────────────────

    async def ensure_loaded(self) -> None:
        """메타 버전이 바뀌었을 때만 다시 빌드한다 (§6.7)."""
        meta = await asyncio.to_thread(load_meta, self._settings.glossary_meta_path)
        if self._snapshot is not None and self._snapshot.version == meta.version:
            return
        async with self._lock:
            # 이중 확인: 락을 기다리는 동안 다른 태스크가 이미 빌드했을 수 있다.
            if self._snapshot is not None and self._snapshot.version == meta.version:
                return
            await self._rebuild(meta)

    async def reload(self) -> IndexSnapshot:
        """메타 버전과 무관하게 강제로 다시 빌드한다 (관리 엔드포인트용).

        빌드에 실패하면 **기존 인덱스를 유지하고** 예외를 올린다.
        잘못된 용어집으로 교체되는 것이 서비스 중단보다 나쁘다 (§6.7).
        """
        async with self._lock:
            meta = await asyncio.to_thread(load_meta, self._settings.glossary_meta_path)
            await self._rebuild(meta)
            return self.snapshot

    async def _rebuild(self, meta: GlossaryMeta) -> None:
        started = time.perf_counter()
        try:
            terms = await asyncio.to_thread(load_glossary, self._settings.glossary_path)
        except Exception as e:  # noqa: BLE001 - 원인을 그대로 노출해야 한다 (R-11)
            self._last_error = str(e)
            logger.error("용어집 로드 실패: %s", e)
            raise

        if meta.count != len(terms):
            # 치명적이지는 않지만 반입 사고의 신호다. 막지 않고 알린다.
            logger.warning(
                "glossary.meta.json 의 count(%d)와 실제 용어 수(%d)가 다르다",
                meta.count,
                len(terms),
            )

        kiwi_pool = await self._build_kiwi_pool(terms)
        tm_ko2en, tm_en2ko = await self._build_tm()

        snapshot = IndexSnapshot(
            version=meta.version,
            meta=meta,
            ko2en=await asyncio.to_thread(GlossaryIndex.build, "ko2en", terms),
            en2ko=await asyncio.to_thread(GlossaryIndex.build, "en2ko", terms),
            build_ms=int((time.perf_counter() - started) * 1000),
            kiwi_pool=kiwi_pool,
            tm_ko2en=tm_ko2en,
            tm_en2ko=tm_en2ko,
        )
        # 완전히 빌드한 뒤에 참조를 바꾼다 (§6.7).
        self._snapshot = snapshot
        self._last_error = None
        logger.info(
            "인덱스 준비 완료: 용어집 v%d %d건, %dms, 분할기=%s, 매칭=%s, TM=%d",
            snapshot.version,
            len(terms),
            snapshot.build_ms,
            "kiwi" if kiwi_pool else "rule",
            "aho-corasick" if snapshot.ko2en.automaton else "none",
            len(tm_ko2en) if tm_ko2en else 0,
        )

    async def _build_tm(self) -> tuple[BM25Retriever | None, BM25Retriever | None]:
        """TM 검색 인덱스 (§6.4, §6.7).

        TM 은 선택 자산이다. 없어도 서비스는 돌고 few-shot 예시만 빠진다.
        5만 쌍 기준 빌드에 5~10초 걸리므로 기동 시 한 번만 만든다.
        """
        try:
            entries = await asyncio.to_thread(load_tm, self._settings.tm_path)
        except Exception as e:  # noqa: BLE001
            logger.error("TM 로드 실패, TM 없이 진행한다: %s", e)
            return None, None

        if not entries:
            return None, None
        if not retriever_available():
            logger.warning("rank-bm25 가 없어 TM 검색을 건너뛴다")
            return None, None

        try:
            return (
                await asyncio.to_thread(BM25Retriever, entries, "ko2en"),
                await asyncio.to_thread(BM25Retriever, entries, "en2ko"),
            )
        except Exception as e:  # noqa: BLE001
            logger.error("TM 인덱스 생성 실패, TM 없이 진행한다: %s", e)
            return None, None

    async def _build_kiwi_pool(self, terms: list[Term]) -> AnalyzerPool | None:
        """Kiwi 풀을 만든다 (§6.6, §6.7).

        인스턴스당 사용자 사전 등록에 1~3초 걸리므로 기동 시 한 번만 만든다.
        실패해도 서비스를 멈추지 않고 규칙 기반 분할기로 떨어진다 — 문장 분할이
        조금 나빠질 뿐이고, 그것 때문에 번역기가 안 뜨는 편이 더 나쁘다.
        """
        if not self._settings.use_kiwi:
            logger.info("use_kiwi=False. 규칙 기반 문장 분할기를 쓴다")
            return None
        if not kiwi_available():
            logger.warning(
                "kiwipiepy 가 없어 규칙 기반 문장 분할기로 동작한다. "
                "requirements-nlp.txt 를 설치할 것"
            )
            return None
        try:
            return await asyncio.to_thread(
                build_pool,
                terms,
                self._settings.kiwi_pool_size,
                model_path=self._settings.kiwi_model_path or None,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Kiwi 풀 생성 실패, 규칙 기반으로 폴백한다: %s", e)
            return None
