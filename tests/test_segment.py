"""정규화 · 분할 — 계획서 §6.1, §6.2."""

from __future__ import annotations

from app.pipeline.normalize import normalize, strip_preamble
from app.pipeline.segment import build_chunks, split_paragraphs, split_sentences

# ── 정규화 (§6.1) ─────────────────────────────────────────────


def test_paragraph_structure_survives() -> None:
    """보도자료는 문단 구조가 의미를 가진다. 정규화가 날리면 안 된다."""
    text = "첫 문단이다.\n\n둘째 문단이다."
    out, _ = normalize(text)
    assert "\n\n" in out


def test_runs_of_spaces_collapse() -> None:
    out, _ = normalize("합참은   오늘    발표했다.")
    assert "  " not in out


def test_excess_blank_lines_collapse_to_one_boundary() -> None:
    out, _ = normalize("가.\n\n\n\n나.")
    assert out.count("\n") == 2


def test_index_map_points_back_to_original() -> None:
    """정규화 공간의 위치를 원문 위치로 되돌릴 수 있어야 한다.

    프론트 용어 하이라이트가 이 매핑에 의존한다.
    """
    text = "  합참은 발표했다."
    out, fmap = normalize(text)
    idx = out.index("합참")
    start, end = fmap.to_original_span(idx, idx + 2)
    assert text[start:end] == "합참"


def test_index_map_survives_fullwidth_folding() -> None:
    """NFKC 로 글자 수가 바뀌어도 원문 좌표가 맞아야 한다."""
    text = "Ｋ２ 흑표"
    out, fmap = normalize(text)
    assert out.startswith("K2")
    start, end = fmap.to_original_span(0, 2)
    assert text[start:end] == "Ｋ２"


def test_crlf_normalized() -> None:
    out, _ = normalize("가.\r\n나.")
    assert "\r" not in out


# ── 후처리 (§7.7) ─────────────────────────────────────────────


def test_strip_preamble_removes_model_chatter() -> None:
    assert strip_preamble("Here is the translation: The JCS said") == "The JCS said"
    assert strip_preamble("번역: 합참이 밝혔다") == "합참이 밝혔다"
    assert strip_preamble('"The JCS said"') == "The JCS said"


def test_strip_preamble_keeps_internal_quotes() -> None:
    text = 'He said "go" and left'
    assert strip_preamble(text) == text


# ── 분할 (§6.2) ───────────────────────────────────────────────


def test_paragraph_split() -> None:
    paras = split_paragraphs("가.\n\n나.\n\n다.")
    assert len(paras) == 3


def test_decimal_point_does_not_split() -> None:
    """마침표만으로 자르면 소수점에서 오작동한다."""
    sentences = split_sentences("탄약 3.5톤을 옮겼다. 끝났다.")
    assert len(sentences) == 2


def test_english_abbreviation_does_not_split() -> None:
    sentences = split_sentences("Gen. Kim arrived. The unit moved out.")
    assert len(sentences) == 2


def test_lowercase_continuation_does_not_split() -> None:
    sentences = split_sentences("The unit (7th Corps) moved. It arrived at dawn.")
    assert len(sentences) == 2


def test_chunks_respect_char_budget() -> None:
    sentence = "합참은 오늘 훈련을 실시했다고 밝혔다. "
    text = sentence * 60
    chunks = build_chunks(text, "ko2en", max_chars=200)
    assert chunks
    assert all(len(c.text) <= 200 for c in chunks)


def test_chunks_never_cross_paragraph_boundary() -> None:
    text = "가나다라.\n\n마바사아."
    chunks = build_chunks(text, "ko2en", max_chars=800)
    assert len(chunks) == 2
    assert chunks[0].paragraph_index != chunks[1].paragraph_index


def test_oversized_single_sentence_is_hard_split() -> None:
    """한 문장이 예산을 통째로 넘어도 파이프라인이 막히면 안 된다."""
    text = "가" * 500
    chunks = build_chunks(text, "ko2en", max_chars=100)
    assert len(chunks) == 5
    assert all(len(c.text) <= 100 for c in chunks)


def test_empty_input_yields_no_chunks() -> None:
    assert build_chunks("   \n\n  ", "ko2en") == []


def test_chunk_indices_are_sequential() -> None:
    chunks = build_chunks("가.\n\n나.\n\n다.", "ko2en")
    assert [c.index for c in chunks] == list(range(len(chunks)))
