"""형태소 분석기와 Kiwi 문장 분할 — 계획서 §6.2, §6.3, §6.6 (D-22).

`kss` 를 걷어내고 `Kiwi.split_into_sents()` 로 대체한 결정을 이 파일이 지킨다.
kiwipiepy 가 없는 환경(코어만 설치한 CI)에서는 통째로 skip 된다 — 그 경우
규칙 기반 분할기로 폴백하는 것이 정상 동작이고, tests/test_segment.py 가 덮는다.
"""

from __future__ import annotations

import pytest

from app.config import PROJECT_ROOT
from app.glossary.loader import load_glossary
from app.glossary.morph import KoreanAnalyzer, build_pool, kiwi_available
from app.pipeline.segment import build_chunks, split_sentences

pytestmark = pytest.mark.skipif(not kiwi_available(), reason="kiwipiepy / kiwipiepy-model 미설치")

GLOSSARY = PROJECT_ROOT / "data" / "glossary.jsonl"


@pytest.fixture(scope="module")
def analyzer() -> KoreanAnalyzer:
    """모듈 전체가 하나를 공유한다. 생성에 1~3초 걸린다 (§6.7)."""
    return KoreanAnalyzer(load_glossary(GLOSSARY))


# ── 문장 분할 (§6.2) ──────────────────────────────────────────


def test_decimal_does_not_split(analyzer: KoreanAnalyzer) -> None:
    """마침표만으로 자르면 소수점에서 오작동한다."""
    sents = analyzer.split_sentences("장비 3.5t 을 옮겼다. 훈련이 끝났다.")
    assert len(sents) == 2


def test_unit_designation_does_not_split(analyzer: KoreanAnalyzer) -> None:
    """'제7사단' 같은 부대명에서 끊기면 안 된다."""
    sents = analyzer.split_sentences("제7기동군단 예하 제20기계화보병사단이 참가했다.")
    assert len(sents) == 1


def test_offsets_point_into_source(analyzer: KoreanAnalyzer) -> None:
    text = "합참은 밝혔다. 국방부는 침묵했다."
    for start, sentence in analyzer.split_sentences(text):
        assert text[start : start + len(sentence)] == sentence


def test_multiple_sentences(analyzer: KoreanAnalyzer) -> None:
    text = "합참은 훈련을 실시했다. 국방부는 입장을 냈다. 해군도 참가했다."
    assert len(analyzer.split_sentences(text)) == 3


# ── 용어집 사용자 사전 (§6.3) ─────────────────────────────────


def test_glossary_term_is_one_proper_noun(analyzer: KoreanAnalyzer) -> None:
    """용어집 표제어가 NNP 하나로 끊겨야 한다.

    이것이 kss 대신 Kiwi 를 고른 이유다 — 분할기와 매칭이 같은 사전을 본다.
    "기계화보병사단에서는" → 제20기계화보병사단/NNP + 에서/JKB + 는/JX
    """
    tokens = analyzer.tokenize("제20기계화보병사단에서는")
    forms = [t.form for t in tokens]
    assert "제20기계화보병사단" in forms
    assert forms[0] == "제20기계화보병사단"
    assert [t.tag for t in tokens][1:] == ["JKB", "JX"]


def test_alias_is_registered(analyzer: KoreanAnalyzer) -> None:
    """이형태도 사용자 사전에 들어간다. '합참'은 T-0142 의 별칭이다."""
    forms = [t.form for t in analyzer.tokenize("합참은 밝혔다")]
    assert "합참" in forms


def test_proper_noun_spans_are_reported(analyzer: KoreanAnalyzer) -> None:
    """Phase 2 의 매칭 교차검증이 이 구간을 쓴다."""
    text = "제7기동군단이 이동했다"
    spans = analyzer.proper_noun_spans(text)
    assert (0, len("제7기동군단")) in spans


def test_proper_noun_spans_stay_exact(analyzer: KoreanAnalyzer) -> None:
    """교차검증은 구간이 정확히 일치해야 성립한다. 여기서 늘리면 안 된다."""
    text = "천무-Ⅱ가 배치됐다"
    assert (0, 2) in analyzer.proper_noun_spans(text)  # `천무` 까지만
    assert (0, 4) not in analyzer.proper_noun_spans(text)


def test_variant_span_extends_over_designation(analyzer: KoreanAnalyzer) -> None:
    """Kiwi 는 하이픈에서 끊는다. 변형 탐지는 그 너머를 봐야 한다 (§4.4, R-04)."""
    text = "천무-Ⅱ가 배치됐다"
    assert (0, 4) in analyzer.variant_spans(text)
    assert text[0:4] == "천무-Ⅱ"


def test_variant_span_survives_following_josa(analyzer: KoreanAnalyzer) -> None:
    """로마 숫자와 조사가 둘 다 단어 문자라, 정규식 끝에 `\\b` 를 붙이면 실패한다."""
    for text in ("천무-Ⅱ가 왔다", "천무-Ⅱ도 왔다", "천무-Ⅱ와 함께"):
        assert (0, 4) in analyzer.variant_spans(text), text


# ── 풀 (§6.6) ─────────────────────────────────────────────────


def test_pool_hands_out_and_returns() -> None:
    """Kiwi 는 스레드 안전하지 않으므로 풀로 관리한다."""
    pool = build_pool(load_glossary(GLOSSARY), size=1)
    with pool.acquire() as a:
        assert a.split_sentences("합참은 밝혔다.")
    # 반납됐으므로 다시 받을 수 있어야 한다.
    with pool.acquire(timeout=1.0) as a:
        assert a is not None


def test_pool_size_is_at_least_one() -> None:
    assert build_pool(load_glossary(GLOSSARY), size=0).size == 1


# ── 파이프라인 결합 ───────────────────────────────────────────


def test_segment_uses_analyzer_when_given(analyzer: KoreanAnalyzer) -> None:
    text = "장비 3.5t 을 옮겼다. 훈련이 끝났다."
    assert len(split_sentences(text, "ko2en", analyzer)) == 2


def test_segment_ignores_analyzer_for_english_source(analyzer: KoreanAnalyzer) -> None:
    """영어 원문에는 Kiwi 를 쓰지 않는다. 규칙 기반이 담당한다."""
    text = "Gen. Kim arrived. The unit moved out."
    assert len(split_sentences(text, "en2ko", analyzer)) == 2


def test_chunks_respect_paragraphs_with_kiwi(analyzer: KoreanAnalyzer) -> None:
    text = "합참은 밝혔다. 훈련이 끝났다.\n\n국방부는 침묵했다."
    chunks = build_chunks(text, "ko2en", max_chars=800, analyzer=analyzer)
    assert len(chunks) == 2
    assert chunks[0].paragraph_index != chunks[1].paragraph_index


def test_app_reports_kiwi_segmenter(kiwi_client) -> None:
    """/health 가 어느 분할기를 쓰는지 알려준다."""
    body = kiwi_client.get("/health").json()
    assert body["segmenter"] == "kiwi"


def test_app_falls_back_to_rule_segmenter(client) -> None:
    """use_kiwi=False 면 규칙 기반으로 떨어지고 서비스는 계속된다."""
    body = client.get("/health").json()
    assert body["segmenter"] == "rule"
