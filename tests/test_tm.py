"""TM 로드와 BM25 검색 — 계획서 §5.2, §6.4.

TM 은 **선택 자산**이다. 없어도 서비스는 돌고 few-shot 예시만 빠진다.
저장소의 `data/tm.jsonl` 은 Phase 1 까지 비어 있으므로 여기서는 합성 데이터를 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tm.loader import load_tm
from app.tm.retriever import BM25Retriever, retriever_available, tokenize

ENTRIES = [
    {
        "ko": "합참은 20일부터 나흘간 연합훈련을 실시한다고 밝혔다.",
        "en": "The JCS said a combined exercise will be conducted for four days from the 20th.",
        "source": "테스트",
        "style": "press_release",
        "quality": "verified",
    },
    {
        "ko": "국방부는 신형 전차 도입 계획을 발표했다.",
        "en": "The Ministry of National Defense announced a plan to acquire new tanks.",
        "source": "테스트",
        "style": "press_release",
        "quality": "verified",
    },
    {
        "ko": "해군은 정례 훈련을 마쳤다고 전했다.",
        "en": "The Navy said it had completed a routine drill.",
        "source": "테스트",
        "style": "press_release",
        "quality": "verified",
    },
]


@pytest.fixture
def tm_path(tmp_path: Path) -> Path:
    path = tmp_path / "tm.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in ENTRIES) + "\n",
        encoding="utf-8",
    )
    return path


# ── 로더 (§5.2) ───────────────────────────────────────────────


def test_load_tm(tm_path: Path) -> None:
    assert len(load_tm(tm_path)) == 3


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """TM 이 없어도 서비스는 돈다. 용어집과 달리 필수가 아니다."""
    assert load_tm(tmp_path / "nope.jsonl") == []


def test_repo_tm_is_loadable() -> None:
    from app.config import PROJECT_ROOT

    assert load_tm(PROJECT_ROOT / "data" / "tm.jsonl")


def test_repo_tm_is_all_sample_quality() -> None:
    """저장소의 TM 은 합성 샘플이다. `verified` 로 표시된 항목이 있으면 안 된다.

    TM 은 few-shot 예시로 프롬프트에 그대로 들어간다 (§7.6). 검수되지 않은
    쌍이 verified 로 둔갑하면 문체와 용어가 조용히 오염된다. Phase 1 에서
    실제 정렬 결과로 교체할 때 이 테스트를 뒤집을 것.
    """
    from app.config import PROJECT_ROOT

    entries = load_tm(PROJECT_ROOT / "data" / "tm.jsonl")
    assert [e for e in entries if e.quality != "sample"] == []


def test_entry_direction_helpers(tm_path: Path) -> None:
    entry = load_tm(tm_path)[0]
    assert entry.query_side("ko2en") == entry.ko
    assert entry.query_side("en2ko") == entry.en
    assert entry.as_example("ko2en") == (entry.ko, entry.en)
    assert entry.as_example("en2ko") == (entry.en, entry.ko)


# ── 토큰화 ────────────────────────────────────────────────────


def test_korean_tokenizer_adds_bigrams() -> None:
    """조사가 붙어 표층형이 흔들리므로 2-gram 을 함께 넣는다."""
    tokens = tokenize("연합훈련을", "ko2en")
    assert "연합훈련을" in tokens
    assert "연합" in tokens


def test_english_tokenizer_lowercases() -> None:
    assert tokenize("The JCS Said", "en2ko") == ["the", "jcs", "said"]


# ── BM25 검색 (§6.4) ──────────────────────────────────────────

pytestmark_bm25 = pytest.mark.skipif(not retriever_available(), reason="rank-bm25 미설치")


@pytest.fixture
def ko_retriever(tm_path: Path) -> BM25Retriever:
    if not retriever_available():
        pytest.skip("rank-bm25 미설치")
    return BM25Retriever(load_tm(tm_path), "ko2en")


def test_similar_sentence_is_retrieved(ko_retriever: BM25Retriever) -> None:
    results = ko_retriever.retrieve("합참은 연합훈련을 실시한다고 밝혔다.")
    assert results
    assert "연합훈련" in results[0][0]


def test_result_is_a_source_target_pair(ko_retriever: BM25Retriever) -> None:
    """few-shot 예시로 그대로 프롬프트에 들어간다 (§7.6)."""
    src, tgt = ko_retriever.retrieve("합참은 연합훈련을 실시했다.")[0]
    assert "합참" in src
    assert "JCS" in tgt


def test_top_k_is_respected(ko_retriever: BM25Retriever) -> None:
    assert len(ko_retriever.retrieve("훈련", top_k=1)) <= 1


def test_unrelated_query_returns_nothing(ko_retriever: BM25Retriever) -> None:
    assert ko_retriever.retrieve("피자와 파스타 조리법") == []


def test_empty_query_returns_nothing(ko_retriever: BM25Retriever) -> None:
    assert ko_retriever.retrieve("   ") == []


def test_empty_tm_is_safe() -> None:
    if not retriever_available():
        pytest.skip("rank-bm25 미설치")
    assert BM25Retriever([], "ko2en").retrieve("무엇이든") == []


def test_en2ko_direction(tm_path: Path) -> None:
    if not retriever_available():
        pytest.skip("rank-bm25 미설치")
    retriever = BM25Retriever(load_tm(tm_path), "en2ko")
    src, tgt = retriever.retrieve("The JCS said a combined exercise was held.")[0]
    assert "JCS" in src
    assert "합참" in tgt


def test_min_score_filters_weak_matches(ko_retriever: BM25Retriever) -> None:
    """상대 점수 기준이다. 최고 점수 대비 얼마나 비슷한지를 본다."""
    strict = ko_retriever.retrieve("합참은 연합훈련을 실시했다.", min_score=0.99)
    loose = ko_retriever.retrieve("합참은 연합훈련을 실시했다.", min_score=0.0)
    assert len(strict) <= len(loose)
