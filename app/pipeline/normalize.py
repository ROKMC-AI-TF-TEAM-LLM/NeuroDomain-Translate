"""정규화, 서식 보존/복원 — 계획서 §6.1.

보도자료는 줄바꿈과 문단 구조가 의미를 가진다. 정규화하면서 이를 날리면
결과가 한 덩어리로 나온다. 그래서 공백은 정리하되 **문단 경계는 남긴다.**

원문 위치 추적을 위해 인덱스 매핑을 함께 유지한다. 이 매핑으로 정규화 공간의
매칭 위치를 원문 위치로 되돌린다 — 프론트 용어 하이라이트에 필요하다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: 모델이 지시를 어기고 붙이는 머리말 (§7.7).
#: 프롬프트만 믿지 말고 후처리로도 걷어낸다. 작은 모델일수록 이 지시를 어긴다.
PREAMBLE_PATTERNS = [
    re.compile(r"^(Here is|Here's) the translation:?\s*", re.IGNORECASE),
    re.compile(r"^(번역|번역문|번역 결과)\s*:?\s*"),
    re.compile(r"^Translation:?\s*", re.IGNORECASE),
    re.compile(r"^\[mock:[a-z0-9]+\]\s*"),  # mock 백엔드 표식
]

_TRAILING_WS = re.compile(r"[ \t]+\n")
_HSPACE_RUN = re.compile(r"[ \t]{2,}")
_BLANK_RUN = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class FormatMap:
    """정규화 공간 ↔ 원문 공간 대응.

    `index_map[i]` 는 정규화 문자열의 i 번째 문자가 유래한 원문 인덱스다.
    """

    original: str
    index_map: tuple[int, ...]

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        """정규화 공간의 [start, end) 를 원문 공간의 [start, end) 로 되돌린다."""
        if not self.index_map or start >= end:
            return (start, end)
        start = max(0, min(start, len(self.index_map) - 1))
        end = max(start + 1, min(end, len(self.index_map)))
        orig_start = self.index_map[start]
        # end 는 열린 구간이라 마지막 문자의 원문 인덱스 +1 로 잡는다.
        orig_end = self.index_map[end - 1] + 1
        return (orig_start, orig_end)


def normalize(text: str) -> tuple[str, FormatMap]:
    """정규화 텍스트 + 복원용 맵 (§6.1)."""
    normalized, index_map = normalize_with_map(text, direction="")
    return normalized, FormatMap(original=text, index_map=tuple(index_map))


def normalize_with_map(text: str, direction: str) -> tuple[str, list[int]]:
    """정규화 문자열과, 각 문자의 원문 인덱스 배열 (§6.1).

    `direction` 은 방향별 정규화를 붙일 자리로 예약해 둔 것이며 Phase 0 에서는
    쓰지 않는다. 매칭용 정규화는 이것이 아니라 `glossary.matcher.normalize_key`
    를 쓴다 — 그쪽은 공백을 없애므로 인덱스가 보존되지 않는다.

    알려진 한계: NFKC 를 문자 단위로 적용하므로 문자 경계를 넘는 결합
    (분해된 자모열 → 완성형)은 처리하지 못한다. 붙여넣기 입력에서 실제로
    관찰되면 Phase 2 에서 NFC 선처리를 넣을 것.
    """
    del direction  # Phase 2 예약

    # 1) 줄바꿈 통일. \r\n 은 두 글자가 한 글자가 된다.
    chars: list[str] = []
    src_idx: list[int] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\r":
            chars.append("\n")
            src_idx.append(i)
            if i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
        else:
            chars.append(ch)
            src_idx.append(i)
        i += 1

    # 2) NFKC. 한 글자가 여러 글자가 될 수 있으므로(㈜ → (주)) 인덱스를 복제한다.
    nfkc_chars: list[str] = []
    nfkc_idx: list[int] = []
    for ch, orig in zip(chars, src_idx, strict=True):
        folded = unicodedata.normalize("NFKC", ch)
        for out_ch in folded:
            nfkc_chars.append(out_ch)
            nfkc_idx.append(orig)

    # 3) 공백 정리. 문단 경계(빈 줄)와 줄바꿈은 남긴다.
    out_chars: list[str] = []
    out_idx: list[int] = []
    n = len(nfkc_chars)
    j = 0
    while j < n:
        ch = nfkc_chars[j]
        if ch in " \t":
            # 연속 수평 공백을 하나로. 줄바꿈 직전이면 통째로 버린다.
            k = j
            while k < n and nfkc_chars[k] in " \t":
                k += 1
            if k < n and nfkc_chars[k] == "\n":
                j = k
                continue
            if out_chars:  # 줄 맨 앞의 들여쓰기는 버린다
                out_chars.append(" ")
                out_idx.append(nfkc_idx[j])
            j = k
            continue
        if ch == "\n":
            k = j
            while k < n and nfkc_chars[k] == "\n":
                k += 1
            count = min(k - j, 2)  # 빈 줄 3개 이상은 문단 경계 하나로
            for _ in range(count):
                out_chars.append("\n")
                out_idx.append(nfkc_idx[j])
            j = k
            continue
        out_chars.append(ch)
        out_idx.append(nfkc_idx[j])
        j += 1

    # 앞뒤 공백 제거
    start, end = 0, len(out_chars)
    while start < end and out_chars[start] in " \n":
        start += 1
    while end > start and out_chars[end - 1] in " \n":
        end -= 1

    return "".join(out_chars[start:end]), out_idx[start:end]


def strip_preamble(text: str) -> str:
    """모델이 붙인 머리말과 감싼 따옴표를 걷어낸다 (§7.7)."""
    out = text.strip()
    changed = True
    while changed:
        changed = False
        for pattern in PREAMBLE_PATTERNS:
            new = pattern.sub("", out, count=1)
            if new != out:
                out = new.lstrip()
                changed = True
    # 결과 전체를 감싼 따옴표 한 겹만 벗긴다.
    for open_q, close_q in (('"', '"'), ("“", "”"), ("'", "'")):
        if len(out) >= 2 and out.startswith(open_q) and out.endswith(close_q):
            inner = out[1:-1]
            if close_q not in inner:
                out = inner.strip()
            break
    return out


def tidy_whitespace(text: str) -> str:
    """결합 단계에서 쓰는 가벼운 정리 (§4.1 7단계)."""
    text = _TRAILING_WS.sub("\n", text)
    text = _HSPACE_RUN.sub(" ", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()
