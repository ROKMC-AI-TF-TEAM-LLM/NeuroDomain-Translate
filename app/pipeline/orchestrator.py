"""단계 조율, 동시성 제어 — 계획서 §4.1, §6.6.

    1. 입력 검증 → 2. 정규화 → 3. 분할 → 4. 전역 사전분석
 → 5. 청크별 번역(병렬) → 6. 검증/재호출 → 7. 결합 → 8. 응답

4번을 5번보다 먼저 하는 것이 핵심이다. 청크를 나눠 번역하면 청크 간 일관성이
깨지는데, 전역 분석 결과를 모든 청크 프롬프트에 공유시켜 해결한다.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.backends.base import TermHint, TranslationBackend, TranslationRequest
from app.config import Settings
from app.glossary.index import IndexRegistry
from app.glossary.matcher import TermMatch, score
from app.logging import get_logger
from app.pipeline.analyze import (
    GlobalAnalysis,
    analyze,
    display_conditions,
    resolve_branch,
)
from app.pipeline.normalize import FormatMap, normalize, strip_preamble
from app.pipeline.prompt import ChunkContext, PromptBuilder
from app.pipeline.segment import Chunk, build_chunks
from app.pipeline.verify import (
    DEFAULT_MIN_CHARS,
    Violation,
    check_language,
    check_length,
    verify,
)
from app.store.runtime import LogRecord

logger = get_logger(__name__)


class InputTooLongError(ValueError):
    def __init__(self, length: int, limit: int) -> None:
        self.length = length
        self.limit = limit
        super().__init__(f"입력이 {limit}자 제한을 넘었다 ({length}자)")


class UnsupportedDirectionError(ValueError):
    pass


@dataclass
class TranslationOutcome:
    """API 응답과 로그의 원재료 (§4.4)."""

    translation: str
    terms_applied: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    log_record: LogRecord | None = None
    unknown_candidates: list[str] = field(default_factory=list)


def resolve_direction(source: str, target: str) -> str:
    """`source`/`target` 을 내부 방향 문자열로 바꾼다."""
    pair = (source.lower(), target.lower())
    if pair == ("ko", "en"):
        return "ko2en"
    if pair == ("en", "ko"):
        return "en2ko"
    raise UnsupportedDirectionError(f"지원하지 않는 언어쌍: {source}→{target} (ko↔en 만 지원)")


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        registry: IndexRegistry,
        backend: TranslationBackend,
        prompts: PromptBuilder,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.backend = backend
        self.prompts = prompts
        #: 전체 동시 요청 상한 (§6.6). O-04 확정 후 조정.
        self._request_sem = asyncio.Semaphore(settings.max_concurrent_requests)

    async def run(self, text: str, direction: str, style: str) -> TranslationOutcome:
        started = time.perf_counter()
        # 동시 요청이 섞이므로 요청마다 id 를 붙여 로그를 따라갈 수 있게 한다.
        # 이 id 를 translation_logs 의 기본키로 그대로 쓴다 — 콘솔 한 줄에서
        # DB 행을 바로 찾을 수 있어야 사고 조사가 된다 (§5.4).
        request_id = str(uuid.uuid4())
        rid = request_id[:8]

        # ── 1. 입력 검증 ──────────────────────────────────────
        if len(text) > self.settings.max_input_chars:
            logger.warning(
                "[%s] 입력 길이 초과: %d자 (상한 %d)",
                rid,
                len(text),
                self.settings.max_input_chars,
            )
            raise InputTooLongError(len(text), self.settings.max_input_chars)

        version = self.prompts.version(direction, style)
        logger.info(
            "[%s] 번역 시작: %s, %d자, style=%s, prompt=%s",
            rid,
            direction,
            len(text),
            style,
            version.id,
        )

        if not text.strip():
            logger.info("[%s] 빈 입력. 모델 호출 없이 종료", rid)
            return TranslationOutcome(
                translation="",
                meta=self._meta(0, 0, started, version.id),
            )

        async with self._request_sem:
            # ── 2. 정규화 ─────────────────────────────────────
            normalized, fmap = normalize(text)

            # ── 3. 분할 ───────────────────────────────────────
            chunks = await self._segment(normalized, direction)
            logger.info(
                "[%s] 분할: %d청크 (분할기=%s)",
                rid,
                len(chunks),
                "kiwi" if self.registry.kiwi_pool and direction == "ko2en" else "rule",
            )

            # ── 4. 전역 사전분석 ──────────────────────────────
            analyze_started = time.perf_counter()
            analysis = await analyze(
                normalized,
                direction,
                chunks,
                self.registry,
                backend=self.backend,
                prompts=self.prompts,
                use_llm_fallback=self.settings.service_classify_llm,
            )
            logger.info(
                "[%s] 사전분석: 용어 %d건%s, 군종=%s, 미등록후보 %d건, TM예시 %d청크, %dms",
                rid,
                len(analysis.matches),
                (
                    " [" + ", ".join(m.term.id for m in analysis.matches[:5]) + "]"
                    if analysis.matches
                    else ""
                ),
                analysis.service_branch or "미확정",
                len(analysis.unknown_candidates),
                len(analysis.tm_examples),
                int((time.perf_counter() - analyze_started) * 1000),
            )

            # ── 5. 청크별 번역 (병렬) ─────────────────────────
            chunk_sem = asyncio.Semaphore(self.settings.max_concurrent_per_request)
            results = await asyncio.gather(
                *(
                    self._translate_chunk(
                        chunk, chunks, direction, style, analysis, version.id, chunk_sem, rid
                    )
                    for chunk in chunks
                )
            )

            # ── 6~7. 결합 ─────────────────────────────────────
            translation = _join_chunks(chunks, [r.text for r in results])
            warnings = _collect_warnings(chunks, results, analysis, direction, self.settings)
            retries = sum(r.retries for r in results)

        terms_applied = _render_terms_applied(analysis, direction, fmap)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        meta = self._meta(len(chunks), retries, started, version.id)

        _log_warnings(rid, warnings)
        logger.info(
            "[%s] 번역 완료: %d자 → %d자, 청크 %d, 재호출 %d, 경고 %d, %dms",
            rid,
            len(text),
            len(translation),
            len(chunks),
            retries,
            len(warnings),
            elapsed_ms,
        )

        return TranslationOutcome(
            translation=translation,
            terms_applied=terms_applied,
            warnings=warnings,
            meta=meta,
            unknown_candidates=analysis.unknown_candidates,
            log_record=LogRecord(
                id=request_id,
                direction=direction,
                src=text if self.settings.log_text else "",
                tgt=translation if self.settings.log_text else "",
                backend=getattr(self.backend, "name", "unknown"),
                prompt_version=version.id,
                terms_applied=terms_applied,
                violations=[w for w in warnings if w.get("type") == "term_missing"],
                glossary_version=self.registry.version,
                chunks=len(chunks),
                retries=retries,
                elapsed_ms=elapsed_ms,
            ),
        )

    async def _segment(self, text: str, direction: str) -> list[Chunk]:
        """문장 분할 + 청크 구성 (§6.2).

        Kiwi 는 CPU 작업이고 풀 획득이 블로킹이라 스레드로 넘긴다. 이벤트 루프를
        막으면 다중 접속에서 전부 같이 느려진다 (§6.6).

        영어 원문(en2ko)과 Kiwi 미설치 환경은 규칙 기반 분할기를 쓴다.
        """
        max_chars = self.settings.max_chunk_chars
        pool = self.registry.kiwi_pool
        if pool is None or direction == "en2ko":
            return build_chunks(text, direction, max_chars=max_chars)

        def run() -> list[Chunk]:
            with pool.acquire() as analyzer:
                return build_chunks(text, direction, max_chars=max_chars, analyzer=analyzer)

        return await asyncio.to_thread(run)

    # ── 청크 처리 ─────────────────────────────────────────────

    async def _translate_chunk(
        self,
        chunk: Chunk,
        all_chunks: list[Chunk],
        direction: str,
        style: str,
        analysis: GlobalAnalysis,
        prompt_version: str,
        sem: asyncio.Semaphore,
        rid: str = "-",
    ) -> _ChunkResult:
        async with sem:
            matches = analysis.matches_in(chunk)
            hints = _hints_for(
                matches,
                direction,
                self.settings.chunk_term_limit,
                analysis.service_branch,
            )
            context = _context_for(chunk, all_chunks, analysis, direction)
            tm_examples = analysis.tm_examples.get(chunk.index, [])

            system_prompt = self.prompts.build_system(
                direction=direction,
                style=style,
                preset=self.settings.prompt_preset,
                terms=hints,
                tm_examples=tm_examples,
                context=context,
            )

            req = TranslationRequest(
                text=chunk.text,
                direction=direction,
                terms=hints,
                tm_examples=tm_examples,
                style=style,
                global_context={
                    "system_prompt": system_prompt,
                    "chunk_index": chunk.index,
                    "total_chunks": len(all_chunks),
                    "service_branch": analysis.service_branch,
                },
                prompt_version=prompt_version,
            )

            logger.debug(
                "[%s] 청크 %d/%d 호출: %d자, 용어 %d건%s",
                rid,
                chunk.index + 1,
                len(all_chunks),
                len(chunk.text),
                len(hints),
                f" (TM {len(tm_examples)}건)" if tm_examples else "",
            )
            result = await self.backend.translate(req)
            text = strip_preamble(result.text)
            logger.debug(
                "[%s] 청크 %d 응답: %d자, %dms",
                rid,
                chunk.index + 1,
                len(text),
                result.elapsed_ms,
            )

            # ── 6. 검증 → 실패 청크만 재호출 (상한 1회) ──────
            violations = verify(chunk.text, text, matches, direction)
            retries = 0
            while violations and retries < self.settings.max_retries:
                retries += 1
                logger.info(
                    "[%s] 청크 %d 용어 누락 %d건 → 재호출 %d/%d: %s",
                    rid,
                    chunk.index + 1,
                    len(violations),
                    retries,
                    self.settings.max_retries,
                    ", ".join(v.term_id for v in violations),
                )
                retry_prompt = self.prompts.build_retry(
                    direction=direction,
                    previous=text,
                    source=chunk.text,
                    missing=[
                        {"source": v.source, "expected": " / ".join(v.expected)} for v in violations
                    ],
                )
                retry_req = TranslationRequest(
                    text=chunk.text,
                    direction=direction,
                    terms=hints,
                    tm_examples=tm_examples,
                    style=style,
                    global_context={**req.global_context, "retry_prompt": retry_prompt},
                    prompt_version=prompt_version,
                )
                retry_result = await self.backend.translate(retry_req)
                text = strip_preamble(retry_result.text)
                violations = verify(chunk.text, text, matches, direction)
                if violations:
                    logger.info(
                        "[%s] 청크 %d 재호출 후에도 %d건 미반영 → 경고로 전환 (§6.5)",
                        rid,
                        chunk.index + 1,
                        len(violations),
                    )

            return _ChunkResult(
                index=chunk.index, text=text, violations=violations, retries=retries
            )

    def _meta(self, chunks: int, retries: int, started: float, prompt_version: str) -> dict:
        return {
            "chunks": chunks,
            "retries": retries,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "backend": getattr(self.backend, "name", "unknown"),
            "prompt_version": prompt_version,
            "glossary_version": self.registry.version,
        }


@dataclass
class _ChunkResult:
    index: int
    text: str
    violations: list[Violation]
    retries: int


# ── 보조 ──────────────────────────────────────────────────────


def _hints_for(
    matches: list[TermMatch],
    direction: str,
    limit: int,
    service_branch: str | None = None,
) -> list[TermHint]:
    """청크에 주입할 용어를 고른다 (§6.3 주입 선별).

    희소하고 다의적인 용어가 앞선다. `사단`, `부대` 같은 흔한 용어는 후순위다 —
    모델이 이미 알고 있어 넣지 않아도 맞는다.

    다의어는 군종이 확정됐으면 하나로 좁혀 "강제" 블록으로 보내고, 확정되지
    않았으면 후보 전부를 조건과 함께 넘긴다 (§5.3).
    """
    ranked = sorted(matches, key=score, reverse=True)[:limit]
    hints: list[TermHint] = []
    for m in ranked:
        term = m.term
        headword = term.ko if direction == "ko2en" else term.en
        targets = term.target_forms(direction)
        conditions = term.conditions

        # §5.3: 조건이 확정되면 하나로 좁힌다.
        if conditions:
            resolved = resolve_branch(term, direction, service_branch)
            if resolved:
                targets = [resolved]
                conditions = None
            else:
                # ③ 전역 컨텍스트와 어휘를 맞춘다 ("해군" → "Navy").
                conditions = display_conditions(conditions)

        targets, abbr = _apply_abbr_policy(term, direction, targets)

        hints.append(
            TermHint(
                source=_hint_source(headword, m.surfaces),
                targets=targets,
                surfaces=list(m.surfaces),
                conditions=conditions,
                abbr=abbr,
                is_reference=False,
                term_id=term.id,
            )
        )
    return hints


def _apply_abbr_policy(term, direction: str, targets: list[str]) -> tuple[list[str], str | None]:  # noqa: ANN001
    """`abbr_policy` 를 대응표 표기에 반영한다 (§5.1).

    이걸 무시하면 프롬프트가 정책과 반대되는 지시를 낸다. `대령` 은
    `always_full` 인데 "Colonel (COL)" 로 보여주면 모델이 `COL Kim` 을 쓴다 —
    시킨 대로 한 것이다.
    """
    abbr = term.en_abbr if direction == "ko2en" else None
    if not abbr:
        return targets, None
    if term.abbr_policy == "always_full":
        return targets, None
    if term.abbr_policy == "always_abbr":
        # 약어 자체가 대역어다. 괄호로 덧붙이지 않는다.
        return [abbr, *[t for t in targets if t != abbr]], None
    return targets, abbr


#: 프롬프트에 보일 별칭 수 상한. 표기가 길어지면 대응표가 읽기 나빠진다.
_MAX_ALIAS_IN_HINT = 2


def _hint_source(headword: str, surfaces: list[str]) -> str:
    """`합동참모본부 / 합참` 형태로 만든다 (§7.5).

    본문에 별칭만 등장했는데 표제어만 보여주면, 모델이 둘을 잇지 못해 지정
    대역어를 놓친다. 실제로 나타난 표층형을 함께 준다.
    """
    aliases = [s for s in dict.fromkeys(surfaces) if s != headword]
    if not aliases:
        return headword
    return " / ".join([headword, *aliases[:_MAX_ALIAS_IN_HINT]])


def _context_for(
    chunk: Chunk,
    all_chunks: list[Chunk],
    analysis: GlobalAnalysis,
    direction: str = "ko2en",
) -> ChunkContext:
    """③ 전역 컨텍스트를 만든다 (§7.4).

    이 블록이 없으면 각 청크가 독립적으로 "첫 등장"이라 판단해 full form 을
    반복한다.

    **`first_full_then_abbr` 인 용어만 넣는다.** 이 블록의 지시가 "첫 등장은
    full form + 약어, 이후는 약어" 이므로, `always_full` 인 용어를 여기 넣으면
    정책과 반대되는 지시가 된다 (§5.1).

    영→한은 이 블록을 쓰지 않는다. `en_abbr` 은 영어 쪽 약어이고, 한국어
    대역어는 약어 도입 관행이 다르다.
    """
    introduced: list[str] = []
    first_here: list[str] = []

    if direction == "ko2en":
        for m in analysis.matches:
            term = m.term
            if term.abbr_policy != "first_full_then_abbr" or not term.en_abbr:
                continue
            first = analysis.first_chunk_of.get(term.id)
            if first is None:
                continue
            label = f"{term.en} ({term.en_abbr})"
            if first < chunk.index:
                introduced.append(label)
            elif first == chunk.index:
                first_here.append(label)

    return ChunkContext(
        chunk_index=chunk.index,
        total_chunks=len(all_chunks),
        service_branch=analysis.service_branch,
        introduced=introduced,
        first_here=first_here,
    )


def _join_chunks(chunks: list[Chunk], texts: list[str]) -> str:
    """서식 복원 (§4.1 7단계). 문단 경계를 되살린다."""
    if not chunks:
        return ""
    parts: list[str] = []
    for i, (chunk, text) in enumerate(zip(chunks, texts, strict=True)):
        if i > 0:
            same_paragraph = chunk.paragraph_index == chunks[i - 1].paragraph_index
            parts.append(" " if same_paragraph else "\n\n")
        parts.append(text)
    return "".join(parts).strip()


def _collect_warnings(
    chunks: list[Chunk],
    results: list[_ChunkResult],
    analysis: GlobalAnalysis,
    direction: str = "ko2en",
    settings: Settings | None = None,
) -> list[dict]:
    """§4.4 warnings. 2차까지 실패한 용어, 길이 이상, 미등록 후보를 담는다."""
    warnings: list[dict] = []
    for chunk, result in zip(chunks, results, strict=True):
        for v in result.violations:
            warnings.append(v.to_warning(chunk.index))
        # 청크 경계 누락 점검 (R-09)
        if chunk.text.strip() and not result.text.strip():
            warnings.append({"type": "empty_chunk", "chunk": chunk.index})
            continue
        # 환각 · 누락 탐지. 원문에 없는 내용을 지어내면 출력이 크게 부푼다.
        anomaly = check_length(
            chunk.text,
            result.text,
            direction,
            max_expansion=(settings.max_expansion_ratio or None) if settings else None,
            min_ratio=(settings.min_length_ratio or None) if settings else None,
            min_chars=settings.length_check_min_chars if settings else DEFAULT_MIN_CHARS,
        )
        if anomaly is not None:
            warnings.append(anomaly.to_warning(chunk.index))
        # 타깃 언어로 쓰이지 않았으면 번역이 아니다. 길이 비율로는 못 잡는다.
        if check_language(result.text, direction):
            warnings.append({"type": "wrong_language", "chunk": chunk.index})
    for text in analysis.unknown_candidates:
        warnings.append({"type": "unknown_candidate", "text": text})
    return warnings


def _log_warnings(rid: str, warnings: list[dict]) -> None:
    """경고를 로그로도 남긴다.

    `warnings` 는 응답에 실리지만 프론트에 아직 표시 위치가 없다 (§4.4).
    환각 탐지가 로그에도 안 남으면 아무도 모르고 지나간다.

    환각 · 언어 이상은 WARNING, 나머지는 INFO 다. 미등록 후보는 정상 운영의
    일부이므로(§4.1 8단계) 개수만 남긴다 — 매 요청 몇 건씩 나오는 것을
    전부 찍으면 로그가 그것으로 덮인다.
    """
    for w in warnings:
        kind = w.get("type")
        if kind == "length_anomaly":
            logger.warning(
                "[%s] 길이 이상(%s): 청크 %d, 원문 %d자 → 출력 %d자 (%.1f배). "
                "환각 또는 누락 가능성",
                rid,
                w.get("kind"),
                w.get("chunk"),
                w.get("src_chars"),
                w.get("tgt_chars"),
                w.get("ratio", 0),
            )
        elif kind == "wrong_language":
            logger.warning(
                "[%s] 타깃 언어가 아님: 청크 %d. 번역 대신 다른 응답이 나왔을 수 있다",
                rid,
                w.get("chunk"),
            )
        elif kind == "empty_chunk":
            logger.warning("[%s] 빈 청크: %d", rid, w.get("chunk"))
        elif kind == "term_missing":
            logger.info(
                "[%s] 용어 미반영: %s (%s), 청크 %d",
                rid,
                w.get("term_id"),
                w.get("source"),
                w.get("chunk"),
            )

    unknown = [w["text"] for w in warnings if w.get("type") == "unknown_candidate"]
    if unknown:
        logger.info(
            "[%s] 미등록 용어 후보 %d건: %s",
            rid,
            len(unknown),
            ", ".join(unknown[:5]) + (" …" if len(unknown) > 5 else ""),
        )


def _render_terms_applied(analysis: GlobalAnalysis, direction: str, fmap: FormatMap) -> list[dict]:
    """§4.4 terms_applied. spans 는 **원문 좌표**로 되돌려서 준다.

    프론트에 표시 위치가 없어도 처음부터 반환한다. 나중에 용어 하이라이트 UI 를
    붙일 때 백엔드를 수정하지 않기 위해서다 (§4.4).
    """
    out: list[dict] = []
    for m in analysis.matches:
        targets = _effective_targets(m.term, direction, analysis.service_branch)
        out.append(
            {
                "source": m.term.ko if direction == "ko2en" else m.term.en,
                "target": targets[0] if targets else "",
                "term_id": m.term.id,
                "spans": [list(fmap.to_original_span(s, e)) for s, e in m.spans],
                "confidence": m.term.confidence,
            }
        )
    return out


def _effective_targets(term, direction: str, service_branch: str | None) -> list[str]:  # noqa: ANN001
    """실제로 요구한 대역어. 다의어는 확정된 분기를, 아니면 표제 대역어를 준다.

    응답의 `terms_applied` 와 프롬프트가 같은 값을 말해야 한다. 해군 문맥에서
    `Captain` 을 요구해 놓고 응답에는 `Colonel` 이라고 적으면, 프론트가 그 값을
    믿고 하이라이트하거나 사용자가 대역어를 확인할 때 어긋난다.
    """
    resolved = resolve_branch(term, direction, service_branch)
    if resolved:
        return [resolved]
    targets = term.target_forms(direction)
    if direction == "ko2en" and term.abbr_policy == "always_abbr" and term.en_abbr:
        return [term.en_abbr, *[t for t in targets if t != term.en_abbr]]
    return targets
