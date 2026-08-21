"""번역문 검증 — 계획서 §6.5.

두 가지를 본다.

1. **용어 준수** — 지정 대역어가 반영됐는가 (§6.5, §12.1 주 지표)
2. **길이 이상** — 출력이 원문에 비해 터무니없이 길거나 짧은가

**자동 강제 치환은 하지 않는다.** 모델이 문맥상 더 나은 형태를 썼거나 문장
구조가 달라져 치환 시 비문이 되는 경우가 많다.

| 상황 | 처리 |
|---|---|
| 1차 용어 위반 | 해당 청크만 재호출 (전체 재번역 아님) |
| 2차 용어 위반 | warnings 에 담아 반환. 사용자 판단 |
| 길이 이상 | warnings 로만 알린다. 재호출하지 않는다 |

길이 검사를 넣은 이유는 실제 사고 때문이다. 영→한에 `"string"` 한 단어를
넣었더니 모델이 2027년 국방 예산안 보도자료를 통째로 지어냈다 — 금액, 계급,
발언까지. 시스템은 아무 경고도 내지 않았다.

원문에 내용이 없으면 모델이 시스템 프롬프트의 **문체 예시를 내용으로 가져다
쓴다.** 그 출력은 형식이 완벽해서 검수자가 놓치기 쉽다. 다수가 쓰는 환경(D-07)
에서 지어낸 국방 문서가 그럴듯하게 나오는 것은 오역보다 위험하다.

프롬프트로도 막지만(§7.2 "Do not add information not present in the source"),
프롬프트는 모델과 입력에 따라 뚫린다. 길이 비율은 모델과 무관하게 동작한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.glossary.matcher import TermMatch, target_key

#: 출력이 원문 대비 이 배수를 넘으면 환각을 의심한다.
#: 한국어는 영어보다 글자 수가 적으므로 방향마다 다르다.
#:
#: **넉넉하게 잡았다.** 실제로 관측된 환각은 45~50배였고, 정상 번역은 한→영
#: 2.8배 수준이다. 임계값을 조이면 정상 번역이 경고로 덮이고, 그러면 사용자가
#: 경고 자체를 무시하게 된다. 골든셋이 실제 문장으로 채워지면(Phase 3)
#: 분포를 보고 다시 잡을 것.
DEFAULT_MAX_EXPANSION = {"ko2en": 4.0, "en2ko": 2.5}

#: 출력이 원문 대비 이 배수에 못 미치면 누락을 의심한다 (R-09).
#: 영→한은 압축이 크다 — "The Ministry of National Defense announced" (41자)
#: → "국방부는 발표했다" (10자) 가 0.24 다. 그보다 아래만 본다.
DEFAULT_MIN_RATIO = {"ko2en": 0.35, "en2ko": 0.15}

#: 이보다 짧은 출력은 비율이 크게 흔들려도 문제 삼지 않는다.
#: `K2 → K2 흑표` 는 2.5배지만 정상이다.
DEFAULT_MIN_CHARS = 40

#: 완성형 한글 + 자모.
_HANGUL_CHARS = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")

#: 이보다 짧은 출력은 언어 판정을 하지 않는다. `K2` 처럼 번역해도 그대로인
#: 짧은 표기가 있다.
LANGUAGE_CHECK_MIN_CHARS = 20

# ── 거부 탐지 ─────────────────────────────────────────────────
#
# 모델이 번역을 내놓는 대신 거절하거나 되묻는 경우다. 실제로 `히히 집에 가야`
# 에 "I'm sorry, but I can't fulfill this request as per the given rules." 가
# 나왔다. 프롬프트로 상당 부분 막았지만 프롬프트는 모델과 입력에 따라 뚫린다.
#
# **오탐이 위험하다.** `죄송합니다` 를 옮기면 정상 번역에 "I'm sorry" 가 들어간다.
# 그래서 두 조건을 모두 만족할 때만 잡는다.
#   1) 거절 · 사과 · 되묻기 표현
#   2) **작업 자체를 가리키는 말** (translate, 번역, request, 입력 …)
# 정상 번역이 자기가 하는 작업을 언급하는 일은 드물다.

_REFUSAL_CUES = re.compile(
    r"""(?ix)
    \b i\s?'?\s?m\ sorry \b
  | \b i\ (?: cannot | can\s?'?\s?t | am\ unable\ to ) \b
  | \b as\ an\ ai \b
  | \b (?: please | could\ you ) \ (?: provide | clarify | specify ) \b
  | \b there\ is\ no \b
  | \b unable\ to\ (?: fulfill | comply | process ) \b
  | 죄송
  | 할\ ?수\ ?없
  | 제공해\ ?주
  | 알려\ ?주
    """
)

_TASK_WORDS = re.compile(
    r"(?ix) \b (?: translat\w* | request | instruction | input | prompt | guidelines? ) \b"
    r" | 번역 | 요청 | 입력 | 지시"
)

#: 출력 전체가 괄호로 묶인 설명. `(Translation provided in Korean …)` 형태.
_WHOLE_PARENTHETICAL = re.compile(r"^\s*[(（].*[)）]\s*$", re.DOTALL)


@dataclass(frozen=True)
class Violation:
    term_id: str
    kind: str  # "missing"
    source: str = ""
    expected: tuple[str, ...] = ()

    def to_warning(self, chunk: int) -> dict:
        return {
            "type": "term_missing",
            "term_id": self.term_id,
            "chunk": chunk,
            "source": self.source,
            "expected": list(self.expected),
        }


def verify(
    src: str,
    tgt: str,
    applied: list[TermMatch],
    direction: str,
) -> list[Violation]:
    """번역문에 지정 용어가 반영됐는지 본다.

    `target_forms` 는 표제어 · 약어 · 이형태, 그리고 다의어의 분기 대역어까지
    모두 인정한다. 코드가 조건을 확정하지 못한 경우 모델이 문맥으로 고른 쪽을
    위반으로 잡으면 안 되기 때문이다 (§5.3).

    정규화는 `target_key` 를 쓴다 — 번역문은 타깃 언어이므로 방향을 뒤집어야
    한다. 계획서 §6.5 예시처럼 `normalize_key(tgt, direction)` 을 쓰면 정상
    번역이 위반으로 잡힌다.
    """
    del src  # 원문은 현재 판정에 쓰지 않는다. 시그니처는 §6.5 를 따른다.

    violations: list[Violation] = []
    norm_tgt = target_key(tgt, direction)
    for m in applied:
        expected = m.term.target_forms(direction)
        if not expected:
            continue
        if any(target_key(e, direction) in norm_tgt for e in expected):
            continue
        violations.append(
            Violation(
                term_id=m.term.id,
                kind="missing",
                source=m.term.ko if direction == "ko2en" else m.term.en,
                expected=tuple(expected),
            )
        )
    return violations


def term_compliance_rate(applied: list[TermMatch], violations: list[Violation]) -> float:
    """용어 준수율 (§12.1 주 지표).

    원문에 등장한 용어 중 지정 대역어로 번역된 비율.
    """
    if not applied:
        return 1.0
    return 1.0 - (len(violations) / len(applied))


# ── 길이 이상 (환각 · 누락 탐지) ──────────────────────────────


@dataclass(frozen=True)
class LengthAnomaly:
    """출력 길이가 원문과 어긋난다."""

    kind: str  # "expansion" | "truncation"
    src_chars: int
    tgt_chars: int
    ratio: float

    def to_warning(self, chunk: int) -> dict:
        return {
            "type": "length_anomaly",
            "kind": self.kind,
            "chunk": chunk,
            "src_chars": self.src_chars,
            "tgt_chars": self.tgt_chars,
            "ratio": round(self.ratio, 1),
        }


def check_length(
    src: str,
    tgt: str,
    direction: str,
    *,
    max_expansion: float | None = None,
    min_ratio: float | None = None,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> LengthAnomaly | None:
    """출력 길이가 원문과 견주어 말이 되는지 본다.

    번역기가 원문에 없는 내용을 지어내면 출력이 크게 부푼다. 반대로 문장을
    빠뜨리면 크게 줄어든다 (R-09). 둘 다 모델과 무관하게 비율로 드러난다.

    **잡아야 하는 것은 수십 배로 부푸는 경우다.** 정상 번역을 경고로 덮으면
    사용자가 경고를 무시하게 되므로 임계값을 넉넉히 잡았다.
    """
    src_chars = len(src.strip())
    tgt_chars = len(tgt.strip())
    if not src_chars or not tgt_chars:
        return None

    ratio = tgt_chars / src_chars
    ceiling = max_expansion or DEFAULT_MAX_EXPANSION.get(direction, 3.0)
    floor = min_ratio if min_ratio is not None else DEFAULT_MIN_RATIO.get(direction, 0.5)

    # 짧은 출력은 비율이 크게 흔들린다. 절대 길이도 함께 본다.
    if tgt_chars >= min_chars and ratio > ceiling:
        return LengthAnomaly("expansion", src_chars, tgt_chars, ratio)
    if src_chars >= min_chars and ratio < floor:
        return LengthAnomaly("truncation", src_chars, tgt_chars, ratio)
    return None


def check_language(tgt: str, direction: str, min_chars: int = LANGUAGE_CHECK_MIN_CHARS) -> bool:
    """번역문이 타깃 언어로 쓰였는가. 아니면 True(이상)를 준다.

    한국어로 번역하라고 했는데 한글이 한 글자도 없으면 번역이 아니다. 실제로
    `"string"` 을 넣었을 때 모델이
    `(Translation provided in Korean, adhering to the style guidelines)` 를
    내놓았다 — 형식만 보면 응답이지만 사용자에게는 쓸모가 없다.

    길이 비율로는 못 잡는다(66자, 원문 6자라 절대 길이 하한에 걸린다).
    스크립트 검사가 더 확실한 신호다.

    `K2` 처럼 번역해도 그대로인 짧은 표기가 있으므로 짧은 출력은 보지 않는다.
    """
    body = tgt.strip()
    if len(body) < min_chars:
        return False
    pattern = _HANGUL_CHARS if direction == "en2ko" else _LATIN_CHARS
    return pattern.search(body) is None


def check_refusal(tgt: str) -> bool:
    """모델이 번역 대신 거절하거나 되물었는가. 그러면 True(이상)를 준다.

    실제로 `히히 집에 가야` 에 다음이 나왔다.
        "I'm sorry, but I can't fulfill this request as per the given rules."

    프롬프트에 "ALWAYS output a translation" 을 넣어 대부분 막았지만, 프롬프트는
    모델과 입력에 따라 뚫린다. 길이·언어 검사도 이런 형태를 늘 잡지는 못한다 —
    한→영에서 영어로 거절하면 언어 검사가 통과시키고, 원문이 길면 길이 비율도
    정상 범위에 든다.

    **오탐을 피하려고 두 조건을 모두 요구한다.** 거절 표현만으로 잡으면
    `죄송합니다` 를 옮긴 정상 번역이 걸린다. 작업 자체를 가리키는 말이 함께
    있어야 거절로 본다.
    """
    body = tgt.strip()
    if not body:
        return False
    # 출력 전체가 괄호 안 설명이고 작업을 언급하면 번역이 아니다.
    if _WHOLE_PARENTHETICAL.match(body) and _TASK_WORDS.search(body):
        return True
    return bool(_REFUSAL_CUES.search(body) and _TASK_WORDS.search(body))
