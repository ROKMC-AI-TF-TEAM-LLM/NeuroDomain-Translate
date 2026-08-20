"""용어 매칭 — 계획서 §6.3.

`MATCH_CASES` 는 계획서 §11 Phase 2 의 "단위 테스트 (필수)" 를 그대로 옮긴 것이며
이 단계의 완료 기준이다.

`pyahocorasick` 이 없는 환경(코어만 설치한 CI)에서는 오토마톤 테스트가 skip 된다.
그 경우 매칭 없이 번역만 되는 것이 정상 동작이다.
"""

from __future__ import annotations

import time

import pytest

from app.config import PROJECT_ROOT
from app.glossary.loader import Term, load_glossary
from app.glossary.matcher import (
    GlossaryAutomaton,
    RawMatch,
    TermMatch,
    aggregate,
    automaton_available,
    build_match_space,
    check_boundary,
    find_unknown_candidates,
    mark_confirmed,
    normalize_key,
    resolve_overlaps,
    score,
)

# ── normalize_key (§6.3) ──────────────────────────────────────


def test_ko_normalization_absorbs_spacing() -> None:
    """띄어쓰기 흔들림을 흡수해야 '합동 참모 본부'가 잡힌다."""
    assert normalize_key("합동 참모 본부", "ko2en") == normalize_key("합동참모본부", "ko2en")


def test_en_normalization_lowercases_and_keeps_word_gaps() -> None:
    assert normalize_key("Joint  Chiefs of Staff", "en2ko") == "joint chiefs of staff"


def test_en_normalization_unifies_dashes_and_quotes() -> None:
    assert normalize_key("ROK–US", "en2ko") == normalize_key("ROK-US", "en2ko")
    assert normalize_key("ROK/US", "en2ko") == normalize_key("ROK-US", "en2ko")


def test_normalization_is_nfkc() -> None:
    assert normalize_key("Ｋ２", "en2ko") == "k2"


# ── 경계 검증 (§6.3) ──────────────────────────────────────────


def test_en_boundary_rejects_substring() -> None:
    """`corps` 가 `corpse` 안에서 잡히면 안 된다."""
    text = "the corpse was found"
    start = text.index("corps")
    assert not check_boundary(text, start, start + 5, "en2ko")


def test_en_boundary_accepts_standalone_word() -> None:
    text = "the corps moved out"
    start = text.index("corps")
    assert check_boundary(text, start, start + 5, "en2ko")


def test_ko_boundary_rejects_longer_compound() -> None:
    """`군단`이 `군단장`에서 잡히면 안 된다."""
    text = "군단장은 참관했다"
    assert not check_boundary(text, 0, 2, "ko2en")


def test_ko_boundary_accepts_josa() -> None:
    text = "군단은 이동했다"
    assert check_boundary(text, 0, 2, "ko2en")


def test_ko_boundary_rejects_when_preceded_by_hangul() -> None:
    text = "기동군단은"
    assert not check_boundary(text, 2, 4, "ko2en")


# ── 겹침 해소 (§6.3) ──────────────────────────────────────────


def test_longest_match_wins() -> None:
    """`제7기동군단`에 `제7기동군단` / `기동군단` / `군단`이 모두 걸린다."""
    matches = [
        RawMatch("T-0301", 0, 6, "제7기동군단", priority=20),
        RawMatch("T-0300", 4, 6, "군단", priority=3),
        RawMatch("T-0999", 2, 6, "기동군단", priority=5),
    ]
    resolved = resolve_overlaps(matches)
    assert [m.term_id for m in resolved] == ["T-0301"]


def test_same_term_at_different_positions_both_survive() -> None:
    matches = [
        RawMatch("T-0300", 0, 2, "군단", priority=3),
        RawMatch("T-0300", 10, 12, "군단", priority=3),
    ]
    assert len(resolve_overlaps(matches)) == 2


def test_morph_confirmed_wins_on_equal_span() -> None:
    matches = [
        RawMatch("T-A", 0, 4, "가나다라", priority=5, confirmed=False),
        RawMatch("T-B", 0, 4, "가나다라", priority=5, confirmed=True),
    ]
    assert resolve_overlaps(matches)[0].term_id == "T-B"


# ── 주입 선별 (§6.3) ──────────────────────────────────────────


def _term(term_id: str, freq: int, conditions: dict | None = None) -> Term:
    return Term(
        id=term_id,
        ko="테스트",
        en="test",
        ko_aliases=[],
        en_aliases=[],
        conditions=conditions,
        domain_tag=["편제"],
        priority=10,
        corpus_freq=freq,
        source="테스트",
        confidence="verified",
        note="",
    )


def test_rare_terms_outrank_common_ones() -> None:
    """`사단`, `부대` 같은 흔한 용어는 후순위다. 모델이 이미 알고 있다."""
    rare = TermMatch(term=_term("T-0001", freq=2), spans=[(0, 2)], count=1)
    common = TermMatch(term=_term("T-0002", freq=5000), spans=[(0, 2)], count=1)
    assert score(rare) > score(common)


def test_ambiguous_terms_get_priority_boost() -> None:
    """다의어는 모델이 틀리기 쉬우므로 먼저 넣는다."""
    plain = TermMatch(term=_term("T-0001", freq=100), spans=[(0, 2)], count=1)
    ambiguous = TermMatch(
        term=_term("T-0002", freq=100, conditions={"field": "service", "branches": []}),
        spans=[(0, 2)],
        count=1,
    )
    assert score(ambiguous) > score(plain)


# ── 매칭 공간 (§6.3) ──────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "합동 참모 본부는 밝혔다",
        "  앞뒤 공백  ",
        "The  ROK–US  Combined Forces Command",
        "Ｋ２ 흑표",
        "",
        "제7기동군단\n예하 부대",
    ],
)
@pytest.mark.parametrize("direction", ["ko2en", "en2ko"])
def test_match_space_agrees_with_normalize_key(text: str, direction: str) -> None:
    """매칭 공간과 `normalize_key` 가 갈라지면 매칭이 통째로 깨진다.

    인덱스에는 `normalize_key` 로 만든 표층형이 들어가고, 스캔은 매칭 공간에서
    돈다. 둘의 규칙이 다르면 아무것도 안 잡히거나 엉뚱한 것이 잡힌다.
    """
    match_text, index_map = build_match_space(text, direction)
    assert match_text == normalize_key(text, direction)
    assert len(index_map) == len(match_text)


def test_match_space_maps_back_to_source() -> None:
    text = "합동 참모 본부는"
    match_text, index_map = build_match_space(text, "ko2en")
    assert match_text == "합동참모본부는"
    # 매칭 공간 [0,6) = "합동참모본부" → 원문 [0,8) = "합동 참모 본부"
    start, end = index_map[0], index_map[5] + 1
    assert text[start:end] == "합동 참모 본부"


def test_match_space_indexes_are_monotonic() -> None:
    text = "The ROK–US Combined Forces Command said."
    _, index_map = build_match_space(text, "en2ko")
    assert index_map == sorted(index_map)


# ── §11 Phase 2 수용 테스트 (필수) ────────────────────────────

#: 계획서 §11 Phase 2 "단위 테스트 (필수)" 를 그대로 옮긴 것.
MATCH_CASES = [
    ("합참은 발표했다", {"T-0142"}),
    ("합동참모본부(합참)는", {"T-0142"}),  # 중복 아님
    ("합동 참모 본부는", {"T-0142"}),  # 띄어쓰기 흔들림
    ("제7기동군단 예하 각 군단은", {"T-0301", "T-0300"}),
    ("군단장은", set()),  # 경계 오탐 방지
    ("The JCS said", {"T-0142"}),
    ("the corpse was found", set()),  # corps 오탐 방지
]


#: 오토마톤이 필요한 테스트에 붙인다. 코어만 설치한 CI 에서는 skip 된다.
requires_automaton = pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")


@pytest.fixture(scope="module")
def terms() -> list[Term]:
    return load_glossary(PROJECT_ROOT / "data" / "glossary.jsonl")


@pytest.fixture(scope="module")
def ko_automaton(terms: list[Term]) -> GlossaryAutomaton:
    if not automaton_available():
        pytest.skip("pyahocorasick 미설치")
    return GlossaryAutomaton("ko2en", terms)


@pytest.fixture(scope="module")
def en_automaton(terms: list[Term]) -> GlossaryAutomaton:
    if not automaton_available():
        pytest.skip("pyahocorasick 미설치")
    return GlossaryAutomaton("en2ko", terms)


def matched_ids(automaton: GlossaryAutomaton, text: str) -> set[str]:
    resolved = resolve_overlaps(automaton.scan(text))
    return {m.term.id for m in aggregate(resolved, automaton.terms_by_id)}


@requires_automaton
@pytest.mark.parametrize("text,expected", MATCH_CASES)
def test_match_cases(text: str, expected: set[str], terms: list[Term]) -> None:
    direction = "en2ko" if text[0].isascii() and text[0].isalpha() else "ko2en"
    automaton = GlossaryAutomaton(direction, terms)
    assert matched_ids(automaton, text) == expected


def test_duplicate_surface_in_same_text_is_one_term(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """'합동참모본부(합참)는' 은 두 표층형이지만 용어는 하나다."""
    resolved = resolve_overlaps(ko_automaton.scan("합동참모본부(합참)는"))
    merged = aggregate(resolved, ko_automaton.terms_by_id)
    assert len(merged) == 1
    assert merged[0].term.id == "T-0142"
    assert merged[0].count == 2  # 등장 위치는 둘 다 남는다


def test_spans_point_into_source_text(ko_automaton: GlossaryAutomaton) -> None:
    """하이라이트가 이 좌표를 쓴다. 정규화 공간이 아니라 원문이어야 한다."""
    text = "합동 참모 본부는 밝혔다"
    matches = aggregate(resolve_overlaps(ko_automaton.scan(text)), ko_automaton.terms_by_id)
    start, end = matches[0].spans[0]
    assert text[start:end] == "합동 참모 본부"


def test_longer_term_wins_over_substring(ko_automaton: GlossaryAutomaton) -> None:
    """'제7기동군단' 안의 '군단' 은 겹침 해소에서 탈락한다."""
    matches = aggregate(
        resolve_overlaps(ko_automaton.scan("제7기동군단이 이동했다")),
        ko_automaton.terms_by_id,
    )
    assert {m.term.id for m in matches} == {"T-0301"}


def test_same_term_twice_is_counted(ko_automaton: GlossaryAutomaton) -> None:
    matches = aggregate(
        resolve_overlaps(ko_automaton.scan("합참은 밝혔다. 합참은 또 밝혔다.")),
        ko_automaton.terms_by_id,
    )
    assert len(matches) == 1
    assert matches[0].count == 2


def test_english_abbreviation_matches(en_automaton: GlossaryAutomaton) -> None:
    assert "T-0160" in matched_ids(en_automaton, "DAPA announced the plan")


def test_english_full_form_matches(en_automaton: GlossaryAutomaton) -> None:
    assert "T-0142" in matched_ids(en_automaton, "the Joint Chiefs of Staff said")


def test_english_match_is_case_insensitive(en_automaton: GlossaryAutomaton) -> None:
    assert "T-0142" in matched_ids(en_automaton, "THE JOINT CHIEFS OF STAFF SAID")


def test_empty_text_yields_no_matches(ko_automaton: GlossaryAutomaton) -> None:
    assert ko_automaton.scan("") == []


def test_text_without_terms_yields_no_matches(ko_automaton: GlossaryAutomaton) -> None:
    assert ko_automaton.scan("오늘 날씨가 좋다") == []


# ── 형태소 교차검증 (§6.3) ────────────────────────────────────


def test_mark_confirmed_flags_matching_spans() -> None:
    matches = [RawMatch("T-0301", 0, 6, "제7기동군단", priority=20)]
    mark_confirmed(matches, {(0, 6)})
    assert matches[0].confirmed is True


def test_mark_confirmed_ignores_other_spans() -> None:
    matches = [RawMatch("T-0301", 0, 6, "제7기동군단", priority=20)]
    mark_confirmed(matches, {(2, 6)})
    assert matches[0].confirmed is False


# ── 미등록 용어 후보 (R-04) ───────────────────────────────────


def test_unknown_acronym_is_collected(en_automaton: GlossaryAutomaton) -> None:
    """모델이 지어낸 약어를 잡으려면 먼저 미등록 약어를 알아야 한다."""
    text = "The CFAC and DAPA signed the deal"
    resolved = resolve_overlaps(en_automaton.scan(text))
    candidates = find_unknown_candidates(text, resolved, "en2ko")
    assert "CFAC" in candidates
    # DAPA 는 용어집에 있으므로 후보가 아니다.
    assert "DAPA" not in candidates


def test_known_terms_are_not_candidates(ko_automaton: GlossaryAutomaton) -> None:
    text = "합참은 밝혔다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert find_unknown_candidates(text, resolved, "ko2en", {(0, 2)}) == []


def test_unknown_korean_proper_noun_is_collected(
    ko_automaton: GlossaryAutomaton,
) -> None:
    text = "현무-Ⅴ가 배치됐다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    candidates = find_unknown_candidates(text, resolved, "ko2en", {(0, 4)})
    assert candidates == ["현무-Ⅴ"]


def test_variant_of_known_term_is_still_a_candidate(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """용어집에 `천무` 가 있어도 `천무-Ⅱ` 는 후보로 올라와야 한다.

    계획서 §4.4 의 응답 예시가 이 사례다. 일부만 겹친다는 것은 변형이라는
    뜻이고, 변형은 자기 항목이 필요하다.
    """
    text = "천무-Ⅱ가 배치됐다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert {m.term_id for m in resolved} == {"T-0401"}  # `천무` 는 잡힌 상태
    assert find_unknown_candidates(text, resolved, "ko2en", {(0, 4)}) == ["천무-Ⅱ"]


def test_common_english_words_are_not_candidates(
    en_automaton: GlossaryAutomaton,
) -> None:
    text = "The unit moved out"
    resolved = resolve_overlaps(en_automaton.scan(text))
    assert "The" not in find_unknown_candidates(text, resolved, "en2ko")


@pytest.mark.parametrize("token", ["Aug", "Sept", "Mon", "Dr", "Mrs"])
def test_date_and_title_abbreviations_are_not_candidates(
    token: str, en_automaton: GlossaryAutomaton
) -> None:
    """`Aug. 20` 의 `Aug` 가 실제로 후보 큐에 올라왔다. 잡음은 검수를 마비시킨다."""
    text = f"The drill began on {token}. 20 at the base."
    resolved = resolve_overlaps(en_automaton.scan(text))
    assert token not in find_unknown_candidates(text, resolved, "en2ko")


def test_candidate_count_is_capped(en_automaton: GlossaryAutomaton) -> None:
    """잡음이 검수 대기열을 덮으면 안 된다."""
    text = " ".join(f"XY{i}Z" for i in range(50))
    resolved = resolve_overlaps(en_automaton.scan(text))
    assert len(find_unknown_candidates(text, resolved, "en2ko", limit=5)) <= 5


def test_designation_is_found_without_morph_tags(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """`현무-Ⅴ` 는 Kiwi 가 NNG 로 넘긴다. 표층 패턴으로 잡아야 한다 (R-04).

    사전에 없는 고유명사일수록 모델이 약어를 지어낼 위험이 크다 — 정작
    그 부류를 형태소 태그로는 못 잡는다.
    """
    text = "현무-Ⅴ가 배치됐다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert find_unknown_candidates(text, resolved, "ko2en", set()) == ["현무-Ⅴ"]


def test_shorter_candidate_is_absorbed_by_longer(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """`백호` 와 `백호-3` 을 둘 다 올리면 검수 대기열에 같은 항목이 두 번 쌓인다."""
    text = "백호-3이 배치됐다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    candidates = find_unknown_candidates(text, resolved, "ko2en", {(0, 2)})
    assert candidates == ["백호-3"]


@pytest.mark.parametrize("title", ["대령", "소장", "장관", "사령관", "씨"])
def test_person_names_are_not_candidates(title: str, ko_automaton: GlossaryAutomaton) -> None:
    """보도자료마다 이름이 나온다. 그대로 두면 검수 대기열이 이름으로 덮인다.

    사람 이름은 용어집 항목이 아니고, 약어 환각(R-04)의 대상도 아니다 —
    프롬프트가 이미 로마자 표기를 지시한다.
    """
    text = f"김철수 {title}은 훈련을 지휘했다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert find_unknown_candidates(text, resolved, "ko2en", {(0, 3)}) == []


def test_terms_starting_with_a_surname_syllable_survive(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """성씨 목록으로 걸렀다면 `정찰기`, `조종사` 가 함께 사라진다.

    그래서 성씨가 아니라 뒤따르는 계급·직함을 신호로 쓴다.
    """
    text = "정찰기가 이륙했다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert find_unknown_candidates(text, resolved, "ko2en", {(0, 3)}) == ["정찰기"]


def test_unit_name_before_a_noun_is_still_a_candidate(
    ko_automaton: GlossaryAutomaton,
) -> None:
    """`제9공수여단 예하` 처럼 직함이 아닌 말이 뒤따르면 후보로 남는다."""
    text = "제9공수여단 예하 부대가 이동했다"
    resolved = resolve_overlaps(ko_automaton.scan(text))
    assert "제9공수여단" in find_unknown_candidates(text, resolved, "ko2en", {(0, 6)})


# ── 성능 (§11 Phase 2 완료 기준) ──────────────────────────────


def test_5000_char_match_under_200ms(ko_automaton: GlossaryAutomaton) -> None:
    """5,000자 매칭이 200ms 이내여야 한다 (형태소 분석 제외).

    형태소 분석을 포함한 전체 예산은 tests/test_analyze.py 가 잰다.
    """
    sentence = "합동참모본부는 제7기동군단 예하 제20기계화보병사단의 연합훈련을 참관했다. "
    text = (sentence * (5000 // len(sentence) + 1))[:5000]

    started = time.perf_counter()
    aggregate(resolve_overlaps(ko_automaton.scan(text)), ko_automaton.terms_by_id)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 200, f"{elapsed_ms:.1f}ms 걸렸다"
