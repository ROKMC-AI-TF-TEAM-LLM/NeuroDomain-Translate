"""전역 사전분석 — 계획서 §4.1 (4단계), §6.3, §7.4.

**4번을 5번보다 먼저 하는 것이 핵심이다.** 청크를 나눠 번역해도 일관성이
유지되는지가 여기 달려 있다.
"""

from __future__ import annotations

import time

import pytest

from app.glossary.index import IndexRegistry
from app.glossary.matcher import automaton_available
from app.pipeline.analyze import analyze, detect_service_branch
from app.pipeline.segment import build_chunks

pytestmark = pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")


async def run_analysis(settings, text: str, direction: str = "ko2en"):
    registry = IndexRegistry(settings)
    await registry.ensure_loaded()
    chunks = build_chunks(text, direction, max_chars=settings.max_chunk_chars)
    analysis = await analyze(text, direction, chunks, registry)
    return analysis, chunks


# ── 매칭 결합 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terms_are_matched_end_to_end(settings) -> None:
    analysis, _ = await run_analysis(settings, "합참은 제7기동군단 예하 부대의 훈련을 참관했다.")
    ids = {m.term.id for m in analysis.matches}
    assert {"T-0142", "T-0301"} <= ids


@pytest.mark.asyncio
async def test_spans_are_source_coordinates(settings) -> None:
    text = "합참은 밝혔다."
    analysis, _ = await run_analysis(settings, text)
    start, end = analysis.matches[0].spans[0]
    assert text[start:end] == "합참"


@pytest.mark.asyncio
async def test_matches_in_chunk_filters_by_span(settings) -> None:
    """청크별 주입은 그 청크에 실제로 등장한 용어만 담아야 한다 (§6.3)."""
    text = "합참은 밝혔다.\n\n제7기동군단이 이동했다."
    analysis, chunks = await run_analysis(settings, text)
    assert len(chunks) == 2

    first = {m.term.id for m in analysis.matches_in(chunks[0])}
    second = {m.term.id for m in analysis.matches_in(chunks[1])}
    assert "T-0142" in first
    assert "T-0142" not in second
    assert "T-0301" in second


@pytest.mark.asyncio
async def test_no_matches_for_plain_text(settings) -> None:
    analysis, _ = await run_analysis(settings, "오늘 날씨가 좋다.")
    assert analysis.matches == []


# ── 군종 판정 (§7.4, R-05) ────────────────────────────────────


def test_single_cue_confirms_branch() -> None:
    assert detect_service_branch("해군 함정이 입항했다", []) == "Republic of Korea Navy"


def test_multiple_cues_leave_it_unresolved() -> None:
    """둘 이상이면 확정하지 않는다. 코드가 잘못 확정하면 모델이 그대로 따른다."""
    assert detect_service_branch("육군과 해군이 함께 참가했다", []) is None


def test_no_cue_leaves_it_unresolved() -> None:
    assert detect_service_branch("부대가 이동했다", []) is None


def test_english_cue_is_detected() -> None:
    assert detect_service_branch("The ROK Navy said", []) == "Republic of Korea Navy"


@pytest.mark.asyncio
async def test_branch_flows_into_analysis(settings) -> None:
    analysis, _ = await run_analysis(settings, "해군 함정이 입항했다고 밝혔다.")
    assert analysis.service_branch == "Republic of Korea Navy"


# ── 약어 최초 등장 (§7.4) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_first_chunk_of_tracks_introduction(settings) -> None:
    """이 정보가 없으면 각 청크가 독립적으로 '첫 등장'이라 판단한다."""
    text = "합참은 밝혔다.\n\n합참은 또 밝혔다.\n\n국방부는 침묵했다."
    analysis, chunks = await run_analysis(settings, text)
    assert len(chunks) == 3
    assert analysis.first_chunk_of["T-0142"] == 0  # 합참
    assert analysis.first_chunk_of["T-0100"] == 2  # 국방부


# ── 미등록 후보 (R-04) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_acronym_is_collected(settings) -> None:
    analysis, _ = await run_analysis(settings, "The CFAC signed the deal", direction="en2ko")
    assert "CFAC" in analysis.unknown_candidates


# ── 성능 (§11 Phase 2 완료 기준) ──────────────────────────────


@pytest.mark.asyncio
async def test_5000_char_analysis_under_200ms(settings) -> None:
    """5,000자 매칭이 200ms 이내 (**형태소 분석 포함**) — §11 Phase 2 완료 기준.

    인덱스 빌드는 기동 시 1회이므로(§6.7) 측정에서 제외한다. 재는 것은
    요청당 비용이다.

    한 번만 재면 CI 에서 변동으로 흔들린다. 여러 번 돌려 **중앙값**을 본다 —
    정착 상태 비용을 재는 것이 목적이고, 회귀는 중앙값에서 드러난다.

    측정 범위는 `analyze`(§6.3 매칭 + §6.4 TM)다. 문장 분할(§6.2)은 별도
    단계이며 5,000자 기준 약 90ms 를 더 쓴다 — 요청 전체 비용을 볼 때는
    합쳐서 봐야 한다.
    """
    kiwi_settings = settings.model_copy(update={"use_kiwi": True, "kiwi_pool_size": 1})
    registry = IndexRegistry(kiwi_settings)
    await registry.ensure_loaded()

    sentence = "합동참모본부는 제7기동군단 예하 제20기계화보병사단의 연합훈련을 참관했다. "
    text = (sentence * (5000 // len(sentence) + 1))[:5000]
    chunks = build_chunks(text, "ko2en", max_chars=800)

    # 첫 호출은 Kiwi 내부 캐시를 데운다. 측정에서 뺀다.
    analysis = await analyze(text, "ko2en", chunks, registry)
    assert analysis.matches, "5,000자에서 아무것도 못 잡았다"

    samples: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        await analyze(text, "ko2en", chunks, registry)
        samples.append((time.perf_counter() - started) * 1000)

    median = sorted(samples)[len(samples) // 2]
    assert median < 200, f"중앙값 {median:.1f}ms (기준 200ms). 전체: " + " ".join(
        f"{s:.0f}" for s in sorted(samples)
    )


@pytest.mark.asyncio
async def test_analysis_without_automaton_is_empty(settings) -> None:
    """매칭이 없어도 번역은 돌아야 한다. 용어 주입만 빠진다."""
    registry = IndexRegistry(settings)
    # ensure_loaded 를 부르지 않아 스냅샷이 없는 상태.
    analysis = await analyze("합참은 밝혔다.", "ko2en", [], registry)
    assert analysis.matches == []
    assert analysis.unknown_candidates == []
