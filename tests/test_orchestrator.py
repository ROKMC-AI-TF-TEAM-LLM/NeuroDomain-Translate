"""단계 조율 — 계획서 §4.1, §6.5, §6.6.

검증 실패 → 재호출 경로를 여기서 시험한다. `MockBackend(miss_terms=True)` 가
용어를 일부러 빠뜨려 위반을 만든다.
"""

from __future__ import annotations

import pytest

from app.backends.mock import MockBackend
from app.glossary.index import IndexRegistry
from app.glossary.matcher import automaton_available
from app.pipeline.orchestrator import (
    InputTooLongError,
    Orchestrator,
    UnsupportedDirectionError,
    resolve_direction,
)
from app.pipeline.prompt import PromptBuilder

pytestmark = pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")

SAMPLE = "합참은 제7기동군단 예하 부대의 훈련을 참관했다고 밝혔다."


async def build(settings, backend: MockBackend) -> Orchestrator:
    registry = IndexRegistry(settings)
    await registry.ensure_loaded()
    return Orchestrator(settings, registry, backend, PromptBuilder(settings.prompts_dir))


# ── 방향 (§4.4) ───────────────────────────────────────────────


def test_resolve_direction() -> None:
    assert resolve_direction("ko", "en") == "ko2en"
    assert resolve_direction("EN", "KO") == "en2ko"


def test_same_language_is_rejected() -> None:
    with pytest.raises(UnsupportedDirectionError):
        resolve_direction("ko", "ko")


# ── 검증 · 재호출 (§6.5) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_no_retry_when_terms_are_applied(settings) -> None:
    backend = MockBackend()
    orch = await build(settings, backend)
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    assert outcome.meta["retries"] == 0
    assert [w for w in outcome.warnings if w["type"] == "term_missing"] == []
    assert backend.call_count == 1


@pytest.mark.asyncio
async def test_violation_triggers_one_retry(settings) -> None:
    """1차 위반은 해당 청크만 재호출한다. 전체 재번역이 아니다."""
    backend = MockBackend(miss_terms=True)
    orch = await build(settings, backend)
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    assert outcome.meta["retries"] == 1
    assert backend.call_count == 2  # 최초 1 + 재호출 1


@pytest.mark.asyncio
async def test_second_violation_becomes_a_warning(settings) -> None:
    """재호출 상한은 1회다. 2차 실패는 경고로 돌려 사용자가 판단한다.

    다중 접속 환경에서 재시도가 누적되면 큐를 막는다 (R-08).
    """
    backend = MockBackend(miss_terms=True)
    orch = await build(settings, backend)
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    missing = [w for w in outcome.warnings if w["type"] == "term_missing"]
    assert missing
    assert {w["term_id"] for w in missing} >= {"T-0142"}
    assert missing[0]["chunk"] == 0
    assert "expected" in missing[0]


@pytest.mark.asyncio
async def test_retry_prompt_carries_previous_output(settings) -> None:
    """이전 출력을 함께 주면 전면 재작성이 아니라 수정에 가깝게 나온다 (§7.8)."""
    backend = MockBackend(miss_terms=True)
    orch = await build(settings, backend)
    await orch.run(SAMPLE, "ko2en", "press_release")

    retry_prompt = backend.last_request.global_context.get("retry_prompt")
    assert retry_prompt is not None
    assert "[Previous attempt omitted required terms]" in retry_prompt
    assert "합동참모본부" in retry_prompt


@pytest.mark.asyncio
async def test_retry_cap_is_configurable(settings) -> None:
    backend = MockBackend(miss_terms=True)
    orch = await build(settings.model_copy(update={"max_retries": 0}), backend)
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    assert outcome.meta["retries"] == 0
    assert backend.call_count == 1
    assert [w for w in outcome.warnings if w["type"] == "term_missing"]


# ── 프롬프트 전달 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_matched_alias_reaches_the_prompt(settings) -> None:
    """본문에 `합참` 만 있어도 대응표에 표제어와 함께 보여야 한다 (§7.5)."""
    backend = MockBackend()
    orch = await build(settings, backend)
    await orch.run(SAMPLE, "ko2en", "press_release")

    system_prompt = backend.last_request.global_context["system_prompt"]
    assert "합동참모본부 / 합참 → Joint Chiefs of Staff (JCS)" in system_prompt


@pytest.mark.asyncio
async def test_term_limit_is_respected(settings) -> None:
    """청크당 주입 용어 수 상한 (§6.3)."""
    backend = MockBackend()
    orch = await build(settings.model_copy(update={"chunk_term_limit": 2}), backend)
    await orch.run(SAMPLE, "ko2en", "press_release")

    assert len(backend.last_request.terms) <= 2


# ── 다의어 (§5.3, R-05) ───────────────────────────────────────


async def prompt_for(settings, text: str, direction: str = "ko2en") -> str:
    backend = MockBackend()
    orch = await build(settings, backend)
    await orch.run(text, direction, "press_release")
    return backend.last_request.global_context["system_prompt"]


@pytest.mark.asyncio
async def test_resolved_branch_narrows_to_one_target(settings) -> None:
    """군종이 확정되면 하나로 좁혀 '강제' 블록으로 보낸다 (§5.3).

    코드가 이미 아는 것을 모델에 맡길 이유가 없다.
    """
    prompt = await prompt_for(settings, "해군 김철수 대령은 함정 훈련을 지휘했다.")
    assert "대령 → Captain" in prompt
    assert "context-dependent" not in prompt


@pytest.mark.asyncio
async def test_army_context_picks_colonel(settings) -> None:
    prompt = await prompt_for(settings, "육군 김철수 대령은 사격 훈련을 지휘했다.")
    assert "대령 → Colonel" in prompt


@pytest.mark.asyncio
async def test_unresolved_branch_keeps_all_candidates(settings) -> None:
    """확정되지 않으면 후보 전부를 조건과 함께 넘긴다. 코드가 잘못 확정하면
    모델이 의심 없이 따른다 (R-05)."""
    prompt = await prompt_for(settings, "김철수 대령은 훈련을 지휘했다.")
    assert "[Glossary — context-dependent, choose one]" in prompt
    assert "대령 → Colonel (Army/Air Force/Marines) | Captain (Navy)" in prompt


@pytest.mark.asyncio
async def test_branch_labels_match_context_vocabulary(settings) -> None:
    """③ 이 영어인데 ④ 가 한국어면 모델이 둘을 잇지 못한다 (§7.4, §7.5)."""
    prompt = await prompt_for(settings, "김철수 대령은 훈련을 지휘했다.")
    assert "(해군)" not in prompt
    assert "(Navy)" in prompt


@pytest.mark.asyncio
async def test_response_reports_the_resolved_target(settings) -> None:
    """응답과 프롬프트가 같은 값을 말해야 한다 (§4.4).

    해군 문맥에서 `Captain` 을 요구해 놓고 응답에 `Colonel` 이라고 적으면,
    프론트가 그 값을 믿고 하이라이트할 때 어긋난다.
    """
    orch = await build(settings, MockBackend())
    outcome = await orch.run("해군 김철수 대령은 함정 훈련을 지휘했다.", "ko2en", "press_release")
    applied = {t["term_id"]: t["target"] for t in outcome.terms_applied}
    assert applied["T-0087"] == "Captain"


@pytest.mark.asyncio
async def test_response_target_falls_back_to_headword(settings) -> None:
    """군종이 확정되지 않으면 표제 대역어를 준다."""
    orch = await build(settings, MockBackend())
    outcome = await orch.run("김철수 대령은 훈련을 지휘했다.", "ko2en", "press_release")
    applied = {t["term_id"]: t["target"] for t in outcome.terms_applied}
    assert applied["T-0087"] == "Colonel"


# ── 약어 정책 (§5.1) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_always_full_term_gets_no_abbreviation(settings) -> None:
    """`대령` 은 always_full 이다. "Colonel (COL)" 로 보여주면 모델이 `COL Kim`
    을 쓴다 — 시킨 대로 한 것이다."""
    prompt = await prompt_for(settings, "김철수 대령은 훈련을 지휘했다.")
    assert "(COL)" not in prompt


@pytest.mark.asyncio
async def test_always_full_term_is_not_in_first_occurrence_block(settings) -> None:
    """③ 블록의 지시는 '첫 등장은 full form + 약어' 다. always_full 인 용어를
    여기 넣으면 정책과 반대되는 지시가 된다."""
    prompt = await prompt_for(settings, "해군 김철수 대령은 함정 훈련을 지휘했다.")
    first_here = prompt.split("First occurrence in this chunk")[-1].split("[")[0]
    assert "Colonel" not in first_here


@pytest.mark.asyncio
async def test_first_full_then_abbr_term_is_introduced(settings) -> None:
    """`합동참모본부` 는 first_full_then_abbr 이므로 ③ 에 들어간다."""
    prompt = await prompt_for(settings, "합참은 밝혔다.\n\n합참은 또 밝혔다.")
    assert "Joint Chiefs of Staff (JCS)" in prompt


@pytest.mark.asyncio
async def test_later_chunk_is_told_to_abbreviate(settings) -> None:
    """청크 간 약어 일관성 (§7.4). 이 블록이 없으면 매 청크가 full form 을 반복한다."""
    backend = MockBackend()
    orch = await build(settings, backend)
    await orch.run("합참은 밝혔다.\n\n합참은 또 밝혔다.", "ko2en", "press_release")

    last = backend.last_request.global_context["system_prompt"]
    assert "Already introduced in earlier chunks" in last
    assert "Use the abbreviated form" in last


@pytest.mark.asyncio
async def test_en2ko_skips_the_abbreviation_block(settings) -> None:
    """`en_abbr` 은 영어 쪽 약어다. 한국어 대역어에 그 지시를 걸면 안 된다."""
    prompt = await prompt_for(settings, "The JCS said.", direction="en2ko")
    assert "First occurrence in this chunk" not in prompt


# ── 결합 (§4.1 7단계) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_paragraphs_are_restored(settings) -> None:
    backend = MockBackend()
    orch = await build(settings, backend)
    outcome = await orch.run("합참은 밝혔다.\n\n국방부는 침묵했다.", "ko2en", "press_release")

    assert outcome.meta["chunks"] == 2
    assert "\n\n" in outcome.translation


@pytest.mark.asyncio
async def test_spans_are_reported_in_source_coordinates(settings) -> None:
    """프론트 하이라이트가 이 좌표를 쓴다. 정규화 전 원문 기준이어야 한다."""
    text = "  합동 참모 본부는 밝혔다."  # 앞 공백 + 띄어쓰기 흔들림
    backend = MockBackend()
    orch = await build(settings, backend)
    outcome = await orch.run(text, "ko2en", "press_release")

    applied = {t["term_id"]: t for t in outcome.terms_applied}
    start, end = applied["T-0142"]["spans"][0]
    assert text[start:end] == "합동 참모 본부"


# ── 입력 검증 (§4.1 1단계) ────────────────────────────────────


@pytest.mark.asyncio
async def test_over_length_input_is_rejected(settings) -> None:
    orch = await build(settings, MockBackend())
    with pytest.raises(InputTooLongError):
        await orch.run("가" * (settings.max_input_chars + 1), "ko2en", "press_release")


@pytest.mark.asyncio
async def test_blank_input_short_circuits(settings) -> None:
    backend = MockBackend()
    orch = await build(settings, backend)
    outcome = await orch.run("   \n\n  ", "ko2en", "press_release")

    assert outcome.translation == ""
    assert outcome.meta["chunks"] == 0
    assert backend.call_count == 0


# ── 로그 (§5.4) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_record_captures_run_context(settings) -> None:
    """운영 후 골든셋의 원천이 된다. 용어집 버전이 빠지면 회귀 비교가 안 된다."""
    orch = await build(settings, MockBackend())
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    record = outcome.log_record
    assert record is not None
    assert record.direction == "ko2en"
    assert record.src == SAMPLE
    assert record.glossary_version == 1
    assert record.prompt_version == "ko2en-press-v1"
    assert record.terms_applied


@pytest.mark.asyncio
async def test_log_text_can_be_disabled(settings) -> None:
    """보존 기간과 접근 권한은 운영 절차 사항이다 (§5.4)."""
    orch = await build(settings.model_copy(update={"log_text": False}), MockBackend())
    outcome = await orch.run(SAMPLE, "ko2en", "press_release")

    assert outcome.log_record.src == ""
    assert outcome.log_record.tgt == ""
