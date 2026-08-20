"""전역 사전분석 — 계획서 §4.1 (4단계), §6.3, §6.4.

**4번을 5번보다 먼저 하는 것이 이 파이프라인의 핵심이다.** 청크를 나눠 번역하면
청크 간 일관성이 깨지는데, 텍스트 전체를 1회 스캔한 결과를 모든 청크 프롬프트에
공유시켜 해결한다.

순서 (§4.1):
  1. Aho-Corasick 스캔 → RawMatch 목록 (§6.3)
  2. 형태소 교차검증으로 confirmed 표시
  3. 겹침 해소
  4. 군종 판정 — 규칙 우선, 실패 시 LLM 폴백 (R-05)
  5. 약어 최초 등장 청크 확정 (§7.4)
  6. TM 검색 (§6.4)
  7. 미등록 용어 후보 수집 (R-04)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.glossary.index import IndexRegistry
from app.glossary.matcher import (
    TermMatch,
    aggregate,
    find_unknown_candidates,
    mark_confirmed,
    resolve_overlaps,
)
from app.logging import get_logger
from app.pipeline.segment import Chunk

logger = get_logger(__name__)

#: 군종 판정용 단서. 값은 §7.4 의 프롬프트에 들어갈 영문 표기다.
SERVICE_CUES: dict[str, tuple[str, ...]] = {
    "Republic of Korea Army": ("육군", "ROK Army", "ROKA"),
    "Republic of Korea Navy": ("해군", "ROK Navy", "ROKN"),
    "Republic of Korea Air Force": ("공군", "ROK Air Force", "ROKAF"),
    "Republic of Korea Marine Corps": ("해병대", "ROK Marine Corps", "ROKMC"),
}

#: LLM 판정 결과 토큰 → 영문 표기 (prompts/analyze/service_classify.j2).
_LLM_SERVICE_MAP = {
    "ARMY": "Republic of Korea Army",
    "NAVY": "Republic of Korea Navy",
    "AIR_FORCE": "Republic of Korea Air Force",
    "MARINE_CORPS": "Republic of Korea Marine Corps",
}

#: 프롬프트에 쓸 짧은 표기. ③ 전역 컨텍스트와 ④ 용어 대응표가 **같은 어휘**를
#: 써야 모델이 둘을 잇는다. ③ 이 "Republic of Korea Navy" 인데 ④ 가 "(해군)" 이면
#: 모델이 연결에 실패한다 (§7.4, §7.5).
SERVICE_SHORT = {
    "Republic of Korea Army": "Army",
    "Republic of Korea Navy": "Navy",
    "Republic of Korea Air Force": "Air Force",
    "Republic of Korea Marine Corps": "Marines",
}

#: 조건 분기 값("해군", "ROKN") → 짧은 표기("Navy").
_CUE_TO_SHORT = {
    cue: SERVICE_SHORT[label]
    for label, cues in SERVICE_CUES.items()
    for cue in cues
    if label in SERVICE_SHORT
}


def branch_display(value: str) -> str:
    """조건 분기 값을 프롬프트 표기로 바꾼다. `해군` → `Navy`."""
    return _CUE_TO_SHORT.get(value, value)


def resolve_branch(term, direction: str, service_branch: str | None) -> str | None:  # noqa: ANN001
    """확정된 군종에 해당하는 대역어를 고른다 (§5.3).

    **매칭 단계에서 조건이 확정되면 하나로 좁힌다.** 후보를 그대로 넘기면
    모델이 문맥으로 골라야 하는데, 이미 코드가 아는 것을 굳이 맡길 이유가 없다.
    확정되지 않았을 때만 후보 전부를 조건과 함께 넘긴다.
    """
    if not service_branch or not term.conditions:
        return None
    if term.conditions.get("field") != "service":
        return None

    want = SERVICE_SHORT.get(service_branch)
    if want is None:
        return None

    key = "en" if direction == "ko2en" else "ko"
    for branch in term.conditions.get("branches", []):
        values = branch.get("value") or []
        if any(_CUE_TO_SHORT.get(str(v)) == want for v in values):
            label = branch.get(key)
            if label:
                return str(label)
    return None


def display_conditions(conditions: dict) -> dict:
    """분기 값을 프롬프트 표기로 바꾼 사본을 만든다. 원본은 건드리지 않는다."""
    branches = []
    for branch in conditions.get("branches", []):
        copy = dict(branch)
        copy["value"] = [branch_display(str(v)) for v in branch.get("value") or []]
        branches.append(copy)
    return {**conditions, "branches": branches}


@dataclass
class GlobalAnalysis:
    """텍스트 전체를 1회 스캔한 결과. 모든 청크가 공유한다."""

    matches: list[TermMatch] = field(default_factory=list)
    #: 군종. 판정되지 않으면 None — 그때는 후보를 조건과 함께 넘긴다 (§7.4).
    service_branch: str | None = None
    #: term_id → 그 용어가 처음 등장하는 청크 번호. 약어 처리에 쓴다 (§7.4).
    first_chunk_of: dict[str, int] = field(default_factory=dict)
    #: 청크별 TM few-shot 예시 (§6.4).
    tm_examples: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    #: 용어집에 없는 고유명사 후보. 비동기로 큐에 쌓는다 (§4.1 8단계).
    unknown_candidates: list[str] = field(default_factory=list)

    def matches_in(self, chunk: Chunk) -> list[TermMatch]:
        """해당 청크 구간에 걸리는 매칭만 고른다."""
        return [m for m in self.matches if any(chunk.start <= s < chunk.end for s, _ in m.spans)]


async def analyze(
    text: str,
    direction: str,
    chunks: list[Chunk],
    registry: IndexRegistry,
    backend=None,  # noqa: ANN001 - 순환 import 회피. TranslationBackend | None
    prompts=None,  # noqa: ANN001 - PromptBuilder | None
    use_llm_fallback: bool = False,
) -> GlobalAnalysis:
    """전역 사전분석 (§4.1 4단계)."""
    automaton = registry.automaton_for(direction)
    if automaton is None:
        # 매칭 없이도 번역은 된다. 용어 주입과 검증만 빠진다.
        return GlobalAnalysis()

    if use_llm_fallback:
        return await _analyze_with_llm(
            text, direction, chunks, registry, automaton, backend, prompts
        )

    # CPU 작업이다. 5,000자 + 형태소 분석까지 200ms 예산이지만(§11 Phase 2)
    # 이벤트 루프를 잡고 있으면 다중 접속에서 전부 같이 느려진다 (§6.6).
    return await asyncio.to_thread(_analyze_sync, text, direction, chunks, registry, automaton)


def _analyze_sync(text, direction, chunks, registry, automaton) -> GlobalAnalysis:  # noqa: ANN001
    """동기 본체. `asyncio.to_thread` 안에서만 부른다."""
    # ── 1. 스캔 ───────────────────────────────────────────────
    raw = automaton.scan(text)

    # ── 2. 형태소 교차검증 (ko2en 만) ─────────────────────────
    nnp_spans: set[tuple[int, int]] = set()
    candidate_spans: set[tuple[int, int]] = set()
    pool = registry.kiwi_pool
    if pool is not None and direction == "ko2en":
        with pool.acquire() as analyzer:
            # 토큰화는 한 번만 한다. 따로 부르면 5,000자를 두 번 분석한다.
            nnp_spans, variants = analyzer.span_sets(text)
        # 교차검증은 정확히 일치하는 구간만 본다. 변형 구간은 후보 탐지에만 쓴다.
        mark_confirmed(raw, nnp_spans)
        candidate_spans = nnp_spans | variants

    # ── 3. 겹침 해소 ──────────────────────────────────────────
    resolved = resolve_overlaps(raw)
    matches = aggregate(resolved, automaton.terms_by_id)

    analysis = GlobalAnalysis(matches=matches)

    # ── 4. 군종 판정 (규칙) ───────────────────────────────────
    analysis.service_branch = detect_service_branch(text, matches)

    # ── 5. 약어 최초 등장 청크 ────────────────────────────────
    analysis.first_chunk_of = _first_chunk_of(matches, chunks)

    # ── 6. TM 검색 ────────────────────────────────────────────
    retriever = registry.tm_for(direction)
    if retriever is not None:
        for chunk in chunks:
            examples = retriever.retrieve(chunk.text)
            if examples:
                analysis.tm_examples[chunk.index] = examples

    # ── 7. 미등록 후보 ────────────────────────────────────────
    analysis.unknown_candidates = find_unknown_candidates(
        text, resolved, direction, candidate_spans
    )
    return analysis


async def _analyze_with_llm(
    text, direction, chunks, registry, automaton, backend, prompts
) -> GlobalAnalysis:  # noqa: ANN001
    """규칙으로 군종이 안 나오면 모델에 물어본다 (R-05).

    요청당 모델 호출이 하나 늘어난다. O-04(동시 접속자 수)가 확정되기 전에는
    기본 비활성이다 — 처리량 영향을 모른 채 켤 수 없다.
    """
    analysis = await asyncio.to_thread(_analyze_sync, text, direction, chunks, registry, automaton)
    if analysis.service_branch is not None or backend is None or prompts is None:
        return analysis

    try:
        prompt = prompts.render_analyze("service_classify", text=text)
        answer = (await backend.analyze(text, prompt)).strip().upper()
    except Exception as e:  # noqa: BLE001 - 보조 판정 실패로 번역을 막지 않는다
        logger.warning("군종 LLM 판정 실패, 미판정으로 진행한다: %s", e)
        return analysis

    # UNKNOWN / JOINT 는 확정하지 않는다. 코드가 잘못 확정하면 모델이 그대로
    # 따르므로, 확신이 없으면 후보를 조건과 함께 넘기는 편이 낫다 (§5.3, R-05).
    branch = _LLM_SERVICE_MAP.get(answer)
    if branch:
        analysis.service_branch = branch
        logger.debug("군종 LLM 판정: %s", branch)
    return analysis


def detect_service_branch(text: str, matches: list[TermMatch]) -> str | None:
    """규칙 기반 군종 판정 (§7.4).

    단서가 **정확히 하나** 나올 때만 확정한다. 둘 이상이면 합동 문서이거나
    비교 서술이므로 확정하지 않고 모델에 후보를 넘긴다 — 코드가 잘못 확정하면
    모델이 의심 없이 따른다 (R-05).
    """
    found: set[str] = set()

    for branch, cues in SERVICE_CUES.items():
        if any(cue in text for cue in cues):
            found.add(branch)
        # 용어집이 군종 용어를 잡았다면 표층 검색보다 신뢰할 만하다.
        if any(m.term.ko in cues or m.term.en in cues for m in matches):
            found.add(branch)

    return next(iter(found)) if len(found) == 1 else None


def _first_chunk_of(matches: list[TermMatch], chunks: list[Chunk]) -> dict[str, int]:
    """각 용어가 처음 등장하는 청크 번호 (§7.4).

    이 정보가 없으면 각 청크가 독립적으로 "첫 등장" 이라 판단해 full form 을
    반복한다. 약어 정책(`first_full_then_abbr`)이 있는 용어에만 의미가 있지만,
    계산이 싸므로 전부 담는다.
    """
    out: dict[str, int] = {}
    for m in matches:
        first_pos = m.spans[0][0]
        for chunk in chunks:
            if chunk.start <= first_pos < chunk.end:
                out[m.term.id] = chunk.index
                break
        else:
            # 청크 경계 밖(정규화 여백 등)에 걸리면 첫 청크로 본다.
            out[m.term.id] = 0
    return out
