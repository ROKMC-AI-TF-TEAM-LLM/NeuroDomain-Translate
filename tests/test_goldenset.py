"""골든셋 — 계획서 §11 Phase 3, §12.

저장소의 골든셋은 **합성 샘플**이다. 이 파일의 상당 부분은 그 사실이 잊히지
않게 하는 데 쓴다 — 샘플로 낸 점수가 품질 지표로 인용되면 전체 평가가 무의미해진다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT
from app.eval.goldenset import GoldenEntry, load_goldenset, summarize
from app.glossary.loader import GlossaryError, load_glossary
from app.glossary.matcher import (
    GlossaryAutomaton,
    aggregate,
    automaton_available,
    resolve_overlaps,
)
from app.pipeline.normalize import normalize
from app.tm.loader import load_tm

GOLDENSET = PROJECT_ROOT / "data" / "goldenset.jsonl"
TM = PROJECT_ROOT / "data" / "tm.jsonl"
GLOSSARY = PROJECT_ROOT / "data" / "glossary.jsonl"

VALID = {
    "id": "G-001",
    "direction": "ko2en",
    "src": "합참은 밝혔다.",
    "ref": "The JCS said.",
    "expect_terms": ["T-0142"],
    "tags": ["abbreviation"],
    "quality": "sample",
    "note": "",
}


@pytest.fixture(scope="module")
def entries() -> list[GoldenEntry]:
    return load_goldenset(GOLDENSET)


# ── 로더 ──────────────────────────────────────────────────────


def test_repo_goldenset_loads(entries: list[GoldenEntry]) -> None:
    assert entries


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """골든셋은 Phase 3 자산이다. 그전에는 없는 것이 정상이다."""
    assert load_goldenset(tmp_path / "nope.jsonl") == []


def test_error_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(VALID, ensure_ascii=False) + "\n{ broken\n", encoding="utf-8")
    with pytest.raises(GlossaryError) as exc:
        load_goldenset(path)
    assert exc.value.lineno == 2


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    line = json.dumps(VALID, ensure_ascii=False)
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(GlossaryError):
        load_goldenset(path)


def test_unknown_quality_is_rejected(tmp_path: Path) -> None:
    """`verified` 와 `sample` 외의 값이 들어오면 구분이 무너진다."""
    path = tmp_path / "g.jsonl"
    path.write_text(
        json.dumps({**VALID, "quality": "probably-fine"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GlossaryError):
        load_goldenset(path)


# ── 샘플 표시가 유지되는가 ────────────────────────────────────


def test_repo_goldenset_is_all_sample(entries: list[GoldenEntry]) -> None:
    """저장소의 골든셋은 사람이 검수하지 않았다.

    Phase 3 에서 실제 문장으로 교체하고 사람이 검수한 뒤에 이 테스트를
    뒤집을 것. 그전에 `verified` 가 나타나면 누군가 표시만 바꾼 것이다.
    """
    assert [e for e in entries if e.is_verified] == []


def test_summary_counts_unverified(entries: list[GoldenEntry]) -> None:
    """러너가 실행 전에 찍어 사람이 확인하게 한다."""
    summary = summarize(entries)
    assert summary["verified_count"] == 0
    assert summary["sample_count"] == summary["total"]


# ── 평가 오염 방지 ────────────────────────────────────────────


def test_goldenset_and_tm_do_not_overlap(entries: list[GoldenEntry]) -> None:
    """TM 은 few-shot 예시로 프롬프트에 들어간다 (§7.6).

    골든셋 문장이 TM 에 있으면 모델이 정답을 보고 답하는 셈이라 평가가
    무의미해진다. Phase 1 에서 실제 TM 을 만들 때도 이 분리를 지킬 것.
    """
    tm_sources = {e.ko for e in load_tm(TM)} | {e.en for e in load_tm(TM)}
    leaked = [e.id for e in entries if e.src in tm_sources or e.ref in tm_sources]
    assert leaked == [], f"골든셋 문장이 TM 에 있다: {leaked}"


# ── 구성 (§11 Phase 3) ────────────────────────────────────────


def test_both_directions_are_covered(entries: list[GoldenEntry]) -> None:
    summary = summarize(entries)
    assert summary["ko2en"] > 0
    assert summary["en2ko"] > 0


def test_proper_noun_dense_case_is_present(entries: list[GoldenEntry]) -> None:
    """**고유명사 밀집 문장을 의도적으로 포함**할 것 (§11 Phase 3)."""
    dense = [e for e in entries if "proper_noun_dense" in e.tags]
    assert dense
    assert max(len(e.expect_terms) for e in dense) >= 5


def test_ambiguous_rank_cases_cover_both_branches(entries: list[GoldenEntry]) -> None:
    """다의어는 분기마다 사례가 있어야 회귀를 잡는다 (§5.3, R-05)."""
    cases = [e for e in entries if "ambiguous_rank" in e.tags]
    refs = " ".join(e.ref for e in cases)
    assert "Captain" in refs
    assert "Colonel" in refs


def test_multi_paragraph_case_is_present(entries: list[GoldenEntry]) -> None:
    """장문 · 청크 경계 케이스를 포함할 것 (R-09)."""
    assert any("\n\n" in e.src for e in entries)


# ── 매칭 엔진 회귀 ────────────────────────────────────────────


@pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")
def test_expect_terms_match_the_engine(entries: list[GoldenEntry]) -> None:
    """`expect_terms` 가 실제 매칭 결과와 같아야 한다.

    골든셋이 매칭 엔진의 회귀 테스트를 겸한다. 어긋나면 둘 중 하나가 틀린
    것이고, 어느 쪽이든 알아야 한다 — 실제로 이 검사가 조사 결합형(`이라고`)과
    영어 복수형(`brigades`) 누락을 잡아냈다.
    """
    terms = load_glossary(GLOSSARY)
    automata = {d: GlossaryAutomaton(d, terms) for d in ("ko2en", "en2ko")}

    mismatches: list[str] = []
    for entry in entries:
        automaton = automata[entry.direction]
        normalized, _ = normalize(entry.src)
        found = {
            m.term.id
            for m in aggregate(resolve_overlaps(automaton.scan(normalized)), automaton.terms_by_id)
        }
        expected = set(entry.expect_terms)
        if found != expected:
            mismatches.append(
                f"{entry.id}: 누락={sorted(expected - found)} 초과={sorted(found - expected)}"
            )
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")
def test_reference_translations_use_the_glossary(entries: list[GoldenEntry]) -> None:
    """참조 번역이 지정 대역어를 쓰고 있어야 용어 준수율 측정이 성립한다.

    참조문 자체가 용어집을 어기면 100% 준수한 번역도 오답으로 잡힌다.
    """
    from app.glossary.matcher import target_key
    from app.pipeline.verify import verify

    terms = load_glossary(GLOSSARY)
    by_id = {t.id: t for t in terms}
    automata = {d: GlossaryAutomaton(d, terms) for d in ("ko2en", "en2ko")}

    problems: list[str] = []
    for entry in entries:
        automaton = automata[entry.direction]
        normalized, _ = normalize(entry.src)
        matches = aggregate(resolve_overlaps(automaton.scan(normalized)), automaton.terms_by_id)
        # 다의어는 분기 대역어를 전부 인정하므로 verify 가 알아서 통과시킨다.
        violations = verify(entry.src, entry.ref, matches, entry.direction)
        for v in violations:
            term = by_id[v.term_id]
            problems.append(
                f"{entry.id}: {term.ko} → {v.expected} 가 참조문에 없다 "
                f"(정규화: {target_key(entry.ref, entry.direction)[:60]}…)"
            )
    assert not problems, "\n".join(problems)
