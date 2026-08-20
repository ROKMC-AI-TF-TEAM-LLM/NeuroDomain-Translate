"""문장 분할, 청크 구성 — 계획서 §6.2.

**컨텍스트가 커도 청크 분할을 생략하지 말 것.** 작은 모델일수록 긴 입력에서
용어를 놓치거나 문장을 빠뜨린다.

한국어 문장 분할을 마침표만으로 자르면 "제7사단", 약어, 소수점에서 오작동한다.
계획서 §6.2 는 `kss` 를 쓰라고 하지만 Phase 0 의존성 트리 확인 결과 제외하고
`Kiwi.split_into_sents()` 로 대체했다 (D-22, docs/phase0-notes.md §2-b).

분할기는 두 가지다.

| 경로 | 대상 | 구현 |
|---|---|---|
| Kiwi | 한국어 원문 (ko2en) | `analyzer` 를 넘기면 사용. 용어집 사용자 사전이 함께 적용된다 |
| 규칙 기반 | 영어 원문 (en2ko), Kiwi 미설치 | 아래 `_split_sentences_by_rule` |

규칙 기반 분할기는 소수점 · 약어 · 소문자 연결만 막는 최소한이다. 한국어에
쓰면 Kiwi 보다 확실히 나쁘므로, `analyzer` 가 있으면 반드시 그쪽을 쓸 것.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.glossary.morph import KoreanAnalyzer

MAX_CHUNK_CHARS = 800

#: 뒤에 마침표가 와도 문장 끝이 아닌 것들.
_ABBREVIATIONS = frozenset(
    """
    mr mrs ms dr prof st sgt maj gen col lt capt cmdr adm brig
    no vs etc al inc ltd co corp dept est fig approx
    u.s u.k e.g i.e a.m p.m
    """.split()
)

_SENT_PUNCT = re.compile(r"[.!?…。！？]+[\"'”’)\]]*")
_TOKEN_BEFORE = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_PARAGRAPH_SPLIT = re.compile(r"\n{2,}")


@dataclass(frozen=True)
class Chunk:
    """번역 요청 1건을 나눈 처리 단위 (3~5문장, ~800자)."""

    index: int
    text: str
    #: 정규화 공간에서의 위치. 원문 좌표로 되돌리려면 FormatMap 을 쓴다.
    start: int
    end: int
    paragraph_index: int


def split_paragraphs(text: str) -> list[tuple[int, str]]:
    """문단 경계로 1차 분리. (시작 오프셋, 본문) 목록을 준다."""
    out: list[tuple[int, str]] = []
    cursor = 0
    for part in _PARAGRAPH_SPLIT.split(text):
        offset = text.find(part, cursor) if part else cursor
        if offset < 0:
            offset = cursor
        if part.strip():
            out.append((offset, part))
        cursor = offset + len(part)
    return out


def split_sentences(
    text: str,
    direction: str = "",
    analyzer: KoreanAnalyzer | None = None,
) -> list[tuple[int, str]]:
    """문장 분할. (시작 오프셋, 문장) 목록을 준다.

    `analyzer` 가 있고 원문이 한국어면 Kiwi 를 쓴다. 그 외에는 규칙 기반이다.
    """
    if analyzer is not None and direction != "en2ko":
        return analyzer.split_sentences(text)
    return _split_sentences_by_rule(text)


def _split_sentences_by_rule(text: str) -> list[tuple[int, str]]:
    """Kiwi 없이 쓰는 분할기. 영어 원문과 폴백 경로가 쓴다."""
    sentences: list[tuple[int, str]] = []
    start = 0
    for m in _SENT_PUNCT.finditer(text):
        end = m.end()
        if end >= len(text):
            break
        if not text[end].isspace():
            continue  # 문장부호 뒤에 공백이 없으면 경계가 아니다
        if _is_false_boundary(text, m):
            continue
        piece = text[start:end]
        if piece.strip():
            sentences.append((start, piece.strip()))
        start = end
        while start < len(text) and text[start].isspace():
            start += 1

    tail = text[start:]
    if tail.strip():
        sentences.append((start, tail.strip()))
    return sentences


def _is_false_boundary(text: str, m: re.Match[str]) -> bool:
    """소수점 · 서수 · 약어에서 잘못 끊는 것을 막는다."""
    punct_start = m.start()
    before = text[:punct_start]
    after = text[m.end() :].lstrip()

    # 소수점: 3.5, 제7.5 …
    if before and before[-1].isdigit() and after[:1].isdigit():
        return True
    # "제7사단." 같이 숫자로 끝나고 뒤가 이어지는 경우는 경계로 본다(마침표가 있으므로).
    # 약어: Gen. Kim / e.g. …
    token = _TOKEN_BEFORE.search(before)
    if token and token.group(1).lower().rstrip(".") in _ABBREVIATIONS:
        return True
    # 영문에서 소문자로 이어지면 문장이 끝나지 않은 것으로 본다.
    return bool(after[:1].islower())


def build_chunks(
    text: str,
    direction: str = "",
    max_chars: int = MAX_CHUNK_CHARS,
    analyzer: KoreanAnalyzer | None = None,
) -> list[Chunk]:
    """문단 경계를 넘지 않으면서 문자 예산 안에서 문장을 묶는다 (§6.2)."""
    chunks: list[Chunk] = []
    if not text.strip():
        return chunks

    for para_index, (para_offset, para) in enumerate(split_paragraphs(text)):
        sentences = split_sentences(para, direction, analyzer)
        for group in _group_sentences(sentences, max_chars):
            body = " ".join(s for _, s in group)
            start = para_offset + group[0][0]
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=body,
                    start=start,
                    end=start + len(body),
                    paragraph_index=para_index,
                )
            )

    return chunks


def _group_sentences(
    sentences: list[tuple[int, str]], max_chars: int
) -> list[list[tuple[int, str]]]:
    """문자 예산 안에서 문장을 묶는다.

    한 문장이 예산을 통째로 넘으면 하드 분할한다. 드물지만 막히면 안 된다.
    """
    groups: list[list[tuple[int, str]]] = []
    buffer: list[tuple[int, str]] = []
    buffer_len = 0

    for offset, sentence in sentences:
        if len(sentence) > max_chars:
            if buffer:
                groups.append(buffer)
                buffer, buffer_len = [], 0
            for piece_start in range(0, len(sentence), max_chars):
                piece = sentence[piece_start : piece_start + max_chars]
                groups.append([(offset + piece_start, piece)])
            continue

        addition = len(sentence) + (1 if buffer else 0)
        if buffer and buffer_len + addition > max_chars:
            groups.append(buffer)
            buffer, buffer_len = [], 0
            addition = len(sentence)
        buffer.append((offset, sentence))
        buffer_len += addition

    if buffer:
        groups.append(buffer)
    return groups
