"""방향별 용어 매칭 — 계획서 §6.3.

Aho-Corasick 오토마톤으로 모든 표층형을 한 번의 스캔으로 동시 탐색한다.
텍스트 길이에 대해 O(n) 이고 용어집 크기와 무관하다.

## 두 개의 좌표계

매칭은 **정규화 공간**에서, 경계 검증과 결과 보고는 **원문 공간**에서 한다.

ko2en 정규화는 공백을 전부 없앤다 — "합동 참모 본부" 를 "합동참모본부" 로
잡기 위해서다(§6.3). 그런데 그 상태에서 경계를 보면 공백이 사라져
`"제7기동군단 예하 각 군단은"` 의 `군단` 앞이 `각` 으로 보이고, "앞이 한글이면
거부" 규칙에 걸려 정상 매칭이 탈락한다.

그래서 스캔 결과를 **원문 좌표로 되돌린 뒤** 경계를 검증한다. `build_match_space`
가 그 좌표 대응을 만든다.

`normalize_key` 는 검증(§6.5)도 함께 쓴다. 매칭과 검증이 서로 다른 정규화를
쓰면 "번역문에 있는데 위반으로 잡히는" 오류가 난다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.glossary.loader import Term

#: 한국어 조사와 그 결합형. ko2en 경계 검증에 쓴다 (§6.3).
#:
#: 계획서 §6.3 의 목록은 단일 조사만 담고 있어 `합동훈련이라고` 같은 인용
#: 구문에서 매칭이 탈락한다. 경계 판정이 "조사 뒤에 한글이 더 오면 단어의
#: 일부" 라는 규칙이라(`_continues_hangul`), `이` + `라고` 가 더 긴 단어로
#: 오인되기 때문이다. 보도자료에서 `~이라고 밝혔다` 는 가장 흔한 구문이므로
#: 결합형을 명시한다.
JOSA = (
    # 단일 조사
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "와",
    "과",
    "도",
    "만",
    "나",
    "로",
    "라",
    "에서",
    "에게",
    "에게서",
    "한테",
    "께",
    "께서",
    "으로",
    "까지",
    "부터",
    "처럼",
    "보다",
    "만큼",
    "대로",
    "조차",
    "마저",
    # 인용 · 서술 결합형
    "이라고",
    "라고",
    "이라며",
    "라며",
    "이라는",
    "라는",
    "이란",
    "란",
    "이라",
    "이라도",
    "라도",
    "이나",
    "이나마",
    "나마",
    # 보조사 결합형
    "에는",
    "에도",
    "에만",
    "에서는",
    "에서도",
    "에서의",
    "에게는",
    "에게도",
    "으로는",
    "로는",
    "으로도",
    "로도",
    "으로서",
    "로서",
    "으로써",
    "로써",
    "으로부터",
    "로부터",
    "와는",
    "과는",
    "와도",
    "과도",
    "와의",
    "과의",
    "만이",
    "만을",
    "만은",
    "부터는",
    "까지는",
)

#: 하이픈류(‐‑‒–—―−)와 슬래시를 ASCII 하이픈으로 모은다.
_DASHES = re.compile(r"[‐-―−/]")
#: 작은따옴표류를 ASCII 어퍼스트로피로 모은다.
_QUOTES = re.compile(r"[‘’`]")
_SPACES = re.compile(r"\s+")

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def normalize_key(text: str, direction: str) -> str:
    """매칭 · 검증 공용 정규화 (§6.3).

    ko2en 은 띄어쓰기 흔들림("합동 참모 본부" vs "합동참모본부")을 흡수하려고
    공백을 전부 없앤다. en2ko 는 단어 경계가 의미를 가지므로 공백을 남기고
    소문자 · 기호만 통일한다.
    """
    text = unicodedata.normalize("NFKC", text)
    if direction == "ko2en":
        return _SPACES.sub("", text)
    text = text.lower()
    text = _DASHES.sub("-", text)
    text = _QUOTES.sub("'", text)
    return _SPACES.sub(" ", text).strip()


def build_match_space(text: str, direction: str) -> tuple[str, list[int]]:
    """매칭용 문자열 + 각 문자의 원문 인덱스.

    `normalize_key` 와 **같은 규칙**을 쓰되 위치를 잃지 않는다. 두 함수가
    갈라지면 인덱스에 등록한 표층형과 스캔 대상이 어긋나 매칭이 통째로 깨진다.
    `tests/test_matcher.py::test_match_space_agrees_with_normalize_key` 가
    이 둘의 일치를 지킨다.
    """
    # 대부분의 입력은 이미 NFKC 다. 그때는 글자 단위 루프를 건너뛴다.
    if unicodedata.is_normalized("NFKC", text):
        chars: list[str] = list(text)
        idx: list[int] = list(range(len(text)))
    else:
        chars, idx = [], []
        for i, ch in enumerate(text):
            # NFKC 는 한 글자를 여러 글자로 펼 수 있다 (㈜ → (주)).
            for out_ch in unicodedata.normalize("NFKC", ch):
                chars.append(out_ch)
                idx.append(i)

    if direction == "ko2en":
        out_chars, out_idx = [], []
        for ch, src in zip(chars, idx, strict=True):
            if not ch.isspace():
                out_chars.append(ch)
                out_idx.append(src)
        return "".join(out_chars), out_idx

    # en2ko: 소문자 + 기호 통일 + 공백 축약
    folded, folded_idx = [], []
    for ch, src in zip(chars, idx, strict=True):
        c = _QUOTES.sub("'", _DASHES.sub("-", ch.lower()))
        for out_ch in c:
            folded.append(out_ch)
            folded_idx.append(src)

    out_chars, out_idx = [], []
    n = len(folded)
    j = 0
    while j < n:
        if folded[j].isspace():
            k = j
            while k < n and folded[k].isspace():
                k += 1
            if out_chars:  # 앞쪽 공백은 버린다 (strip)
                out_chars.append(" ")
                out_idx.append(folded_idx[j])
            j = k
            continue
        out_chars.append(folded[j])
        out_idx.append(folded_idx[j])
        j += 1
    while out_chars and out_chars[-1] == " ":  # 뒤쪽 공백 (strip)
        out_chars.pop()
        out_idx.pop()
    return "".join(out_chars), out_idx


def flip(direction: str) -> str:
    """방향을 뒤집는다."""
    return "en2ko" if direction == "ko2en" else "ko2en"


def target_key(text: str, direction: str) -> str:
    """**번역문** 정규화.

    `normalize_key(text, direction)` 은 그 방향의 *원문* 언어 규칙을 쓴다
    (ko2en 이면 한국어 규칙: 공백 제거). 번역문은 반대 언어이므로 방향을
    뒤집어야 한다 — ko2en 의 번역문은 영어이고, 영어 규칙은 en2ko 쪽에 있다.

    계획서 §6.5 의 코드 예시는 번역문에도 `normalize_key(tgt, direction)` 을
    그대로 써서, 정상 번역이 위반으로 잡힌다. 다음이 그 예다.
      - "the joint chiefs of staff" 에 한국어 규칙(공백 제거, 대소문자 유지)을
        적용하면 "Joint Chiefs of Staff" 와 매칭되지 않는다.
      - "합동 참모 본부" 에 영어 규칙(공백 유지)을 적용하면 "합동참모본부" 와
        매칭되지 않는다.
    """
    return normalize_key(text, flip(direction))


def is_hangul(ch: str) -> bool:
    return bool(_HANGUL.match(ch))


def check_boundary(text: str, start: int, end: int, direction: str) -> bool:
    """매칭 구간의 앞뒤가 성립하는지 본다 (§6.3 경계 검증).

    en2ko: 앞뒤가 영숫자면 거부한다. `corps` 가 `corpse` 안에서 잡히는 것을 막는다.
    ko2en: 앞이 한글이면 거부한다. 뒤는 조사이거나 한글이 아니어야 한다.
           `군단` 이 `군단장` 안에서 잡히는 것을 막는다.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""

    if direction == "en2ko":
        if before.isalnum():
            return False
        if not after.isalnum():
            return True
        # 복수형은 같은 용어다. 용어집이 단수형(`Brigade`)만 갖고 있어도
        # 본문의 `brigades` 를 잡아야 한다. `corpse` 안의 `corps` 는 뒤가
        # `e` 라 여기 걸리지 않는다.
        return _is_plural_suffix(text[end:])

    if before and is_hangul(before):
        return False
    if after and is_hangul(after):
        # 뒤에 붙은 것이 조사면 통과, 아니면 더 긴 단어의 일부로 본다.
        return _followed_by_josa(text[end:])
    return True


#: 조사 목록을 **긴 것부터** 늘어놓은 정규식. 파이썬 교대는 최장이 아니라
#: 선순위로 매치하므로, 길이 내림차순이어야 최장 조사를 얻는다.
#:
#: 목록을 늘리면서 문자열 비교 루프가 병목이 됐다 (5,000자 기준 250ms).
#: 정규식 한 번으로 바꿔 C 레벨에서 처리한다.
_JOSA_RE = re.compile("|".join(sorted(JOSA, key=len, reverse=True)))


def _followed_by_josa(tail: str) -> bool:
    """구간 뒤에 온 것이 조사인가.

    **가장 긴 조사 하나만 보면 된다.** 그보다 짧은 조사를 택하면 그 뒤에는
    반드시 한글(긴 조사의 나머지)이 오므로 어차피 "더 긴 단어의 일부" 로
    걸러진다. 따라서 최장 매치가 실패하면 나머지도 전부 실패한다.
    """
    m = _JOSA_RE.match(tail)
    if m is None:
        return False
    rest = tail[m.end() :]
    return not (rest and is_hangul(rest[0]))


def _is_plural_suffix(tail: str) -> bool:
    """뒤에 붙은 것이 영어 복수 어미뿐인가. `brigades` → True, `corpse` → False."""
    for suffix in ("es", "s"):
        if tail.startswith(suffix) and not tail[len(suffix) :][:1].isalnum():
            return True
    return False


@dataclass(frozen=True)
class Surface:
    """인덱스에 등록되는 표층형 하나 (§6.3).

    하나의 `term_id` 에 표층형이 여러 개 붙는다.
    "합동참모본부"와 "합참"은 같은 term_id 를 가리킨다.
    """

    term_id: str
    text: str  # 정규화된 표층형
    is_primary: bool
    length: int


@dataclass
class RawMatch:
    """겹침 해소 전의 매칭 후보."""

    term_id: str
    start: int  # 원문 인덱스
    end: int
    surface: str
    priority: int
    #: 형태소 분석 결과와 일치했는가 (§6.3). 겹침 해소에서 우선순위를 올린다.
    confirmed: bool = False


@dataclass
class TermMatch:
    """최종 매칭 결과. 프롬프트 주입과 검증이 함께 쓴다."""

    term: Term
    spans: list[tuple[int, int]]
    count: int
    confirmed: bool = False
    #: 원문에 **실제로 나타난** 표층형. 표제어와 다를 수 있다("합참" vs
    #: "합동참모본부"). 프롬프트에 이것을 함께 보여줘야 모델이 본문의 말과
    #: 지정 대역어를 연결한다 (§7.5).
    surfaces: list[str] = field(default_factory=list)


def resolve_overlaps(matches: list[RawMatch]) -> list[RawMatch]:
    """구간 스케줄링으로 겹침을 없앤다 (§6.3).

    "제7기동군단"에 `제7기동군단`, `기동군단`, `군단`이 모두 걸리면 가장 긴 것만 남긴다.

    알려진 한계: 그리디라 [0,5]와 [3,20]이 경합하면 짧은 앞쪽을 택한다.
    실무에서 문제가 확인되면 가중 구간 스케줄링(DP)으로 교체한다.
    """
    ordered = sorted(
        matches,
        key=lambda m: (m.start, -(m.end - m.start), not m.confirmed, -m.priority),
    )
    out: list[RawMatch] = []
    cursor = -1
    for m in ordered:
        if m.start >= cursor:
            out.append(m)
            cursor = m.end
    return out


def score(tm: TermMatch) -> float:
    """주입 우선순위 (§6.3).

    `사단`, `부대` 같은 흔한 용어는 후순위다. 모델이 이미 알고 있어
    넣지 않아도 맞고, 자리를 차지하면 정작 필요한 희소 용어가 밀린다.
    """
    rarity = 1.0 / (1 + tm.term.corpus_freq)
    ambiguous = 2.0 if tm.term.is_ambiguous else 1.0
    return rarity * ambiguous * tm.count


# ── Aho-Corasick 인덱스 (§6.3) ────────────────────────────────


class AutomatonUnavailableError(RuntimeError):
    """pyahocorasick 이 없다."""


def automaton_available() -> bool:
    try:
        import ahocorasick  # noqa: F401
    except ImportError:
        return False
    return True


class GlossaryAutomaton:
    """한 방향의 표층형 전체를 담은 오토마톤.

    빌드는 기동 시 1회다 (§6.7). 요청마다 만들면 안 된다.

    `pyahocorasick` 은 requirements.txt 에 있다. 없으면 생성 시점에
    예외를 내고, 레지스트리가 받아 매칭 없이 동작한다 — 번역은 되고 용어
    주입만 빠진다.
    """

    def __init__(self, direction: str, terms: list[Term]) -> None:
        try:
            import ahocorasick
        except ImportError as e:  # pragma: no cover - 설치 환경에 따름
            raise AutomatonUnavailableError(
                "pyahocorasick 이 설치되어 있지 않다. requirements.txt 를 볼 것"
            ) from e

        self.direction = direction
        self._by_id: dict[str, Term] = {t.id: t for t in terms}

        # 같은 표층형에 여러 용어가 걸릴 수 있다(대역 충돌). 전부 남기고
        # 겹침 해소의 priority 가 고르게 한다. 충돌 자체는 glossary lint 가 잡는다.
        surfaces: dict[str, list[Surface]] = {}
        for term in terms:
            for rank, form in enumerate(term.source_forms(direction)):
                key = normalize_key(form, direction)
                if not key:
                    continue
                surfaces.setdefault(key, []).append(
                    Surface(
                        term_id=term.id,
                        text=key,
                        is_primary=(rank == 0),
                        length=len(key),
                    )
                )

        self._automaton = ahocorasick.Automaton()
        for key, items in surfaces.items():
            self._automaton.add_word(key, (key, items))
        if surfaces:
            self._automaton.make_automaton()

        self.surface_count = len(surfaces)
        self.term_count = len(terms)
        self._empty = not surfaces

    def scan(self, text: str) -> list[RawMatch]:
        """원문에서 표층형을 찾는다. 반환 좌표는 **원문 기준**이다."""
        if self._empty or not text:
            return []

        match_text, index_map = build_match_space(text, self.direction)
        if not match_text:
            return []

        out: list[RawMatch] = []
        for end_idx, (key, items) in self._automaton.iter(match_text):
            m_start = end_idx - len(key) + 1
            start = index_map[m_start]
            end = index_map[end_idx] + 1
            # 경계는 공백이 살아 있는 원문에서 본다. 위 모듈 docstring 참조.
            if not check_boundary(text, start, end, self.direction):
                continue
            surface = text[start:end]
            for item in items:
                out.append(
                    RawMatch(
                        term_id=item.term_id,
                        start=start,
                        end=end,
                        surface=surface,
                        priority=self._by_id[item.term_id].priority,
                    )
                )
        return out

    def term(self, term_id: str) -> Term:
        return self._by_id[term_id]

    @property
    def terms_by_id(self) -> dict[str, Term]:
        return self._by_id


def mark_confirmed(matches: list[RawMatch], nnp_spans: set[tuple[int, int]]) -> None:
    """형태소 분석 결과와 일치하는 매칭에 표시를 남긴다 (§6.3).

    Kiwi 가 용어집 표제어를 NNP 하나로 끊었다면 그 매칭은 신뢰도가 높다.
    겹침 해소에서 같은 길이 경합 시 이쪽이 이긴다.
    """
    for m in matches:
        if (m.start, m.end) in nnp_spans:
            m.confirmed = True


def aggregate(matches: list[RawMatch], terms_by_id: dict[str, Term]) -> list[TermMatch]:
    """같은 용어의 여러 등장을 하나로 묶는다.

    서로 다른 위치의 같은 용어는 `spans` 에 나란히 담긴다 — 주입은 한 번만
    하되 검증과 하이라이트는 모든 위치를 알아야 한다.
    """
    grouped: dict[str, list[RawMatch]] = {}
    for m in matches:
        grouped.setdefault(m.term_id, []).append(m)

    out: list[TermMatch] = []
    for term_id, group in grouped.items():
        group.sort(key=lambda m: m.start)
        out.append(
            TermMatch(
                term=terms_by_id[term_id],
                spans=[(m.start, m.end) for m in group],
                count=len(group),
                confirmed=any(m.confirmed for m in group),
                surfaces=list(dict.fromkeys(m.surface for m in group)),
            )
        )
    out.sort(key=lambda tm: tm.spans[0][0])
    return out


# ── 미등록 용어 후보 (§4.1 8단계, R-04) ───────────────────────

#: 영문 약어. `ROK-US`, `DAPA` 같은 형태.
_ACRONYM = re.compile(r"\b[A-Z]{2,}(?:[-/][A-Z0-9]{1,})*\b")
#: 연속된 대문자 시작 단어. `Combined Forces Command` 같은 형태.
_PROPER_RUN = re.compile(r"\b(?:[A-Z][a-z]{1,}\s+){0,3}[A-Z][a-z]{1,}\b")

#: 한글 + 형식 번호. `현무-Ⅴ`, `천무-Ⅱ`, `백호-3` 같은 무기·체계 명칭.
#:
#: 형태소 태그에 기대지 않는다. Kiwi 는 사전에 없는 고유명사를 NNG 로 넘기는데
#: (`현무` 가 그렇다), 정작 그런 것들이 미등록이라 모델이 약어를 지어낼 위험이
#: 가장 크다 (R-04). 이 패턴은 태그와 무관하게 잡는다.
_KO_DESIGNATION = re.compile(r"[가-힣]{2,}[-‐‑‒–—―][0-9IVXLCDMⅠ-ⅫA-Z]+")

#: 한 요청에서 큐에 올릴 후보 상한. 잡음이 검수 대기열을 덮지 않게 한다.
MAX_CANDIDATES = 20

#: 인명 뒤에 붙는 계급 · 직함. 후보에서 사람 이름을 걸러내는 데 쓴다.
#:
#: 보도자료에는 이름이 계속 나오는데(D-04), 사람 이름은 용어집 항목이 아니다.
#: 그대로 두면 Phase 6 의 검수 대기열이 이름으로 뒤덮인다. 약어 환각(R-04)의
#: 대상도 아니다 — 프롬프트가 이미 로마자 표기를 지시한다 (§7.2).
#:
#: 성씨 목록으로 거르지 않는 이유: `정찰기`, `조종사`, `신호탄` 처럼 성씨
#: 음절로 시작하는 실제 군사 용어가 대량으로 걸린다. 뒤따르는 계급·직함은
#: 훨씬 정확한 신호다.
_PERSON_TITLES = (
    # 장교
    "원수",
    "대장",
    "중장",
    "소장",
    "준장",
    "대령",
    "중령",
    "소령",
    "대위",
    "중위",
    "소위",
    "준위",
    # 부사관 · 병
    "원사",
    "상사",
    "중사",
    "하사",
    "병장",
    "상병",
    "일병",
    "이병",
    # 직책 · 일반 호칭
    "장군",
    "제독",
    "총장",
    "참모총장",
    "사령관",
    "함장",
    "단장",
    "여단장",
    "사단장",
    "군단장",
    "대대장",
    "중대장",
    "소대장",
    "지휘관",
    "장관",
    "차관",
    "청장",
    "실장",
    "국장",
    "과장",
    "부장",
    "팀장",
    "대변인",
    "의원",
    "위원장",
    "씨",
    "님",
)

#: 끝에 `\b` 를 붙이면 안 된다. 뒤따르는 조사(`대령은`의 `은`)가 단어 문자라
#: 경계가 생기지 않아 매치가 통째로 실패한다. `_VARIANT_SUFFIX` 와 같은 함정이다.
#: 긴 직함을 먼저 시도하도록 정렬한다 — 파이썬 정규식 교대는 최장이 아니라 선순위다.
_PERSON_TITLE_RE = re.compile(
    r"\s*(?:" + "|".join(sorted(_PERSON_TITLES, key=len, reverse=True)) + r")"
)

#: 후보에서 제외할 영문 상용어. 문장 첫 단어가 대문자라 걸리는 것들과,
#: 날짜 · 직함 약어처럼 고유명사가 아닌데 대문자로 시작하는 것들이다.
#: `Aug. 20` 의 `Aug` 가 실제로 후보 큐에 올라와서 추가했다.
_STOP_PROPER = frozenset(
    """
    The A An In On At To Of For And But Or If It Its This That These Those
    He She They We You I His Her Their Our Your My Is Are Was Were Be Been
    January February March April May June July August September October
    November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday
    Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec
    Mon Tue Tues Wed Thu Thur Thurs Fri Sat Sun
    Mr Mrs Ms Dr Prof St No Vs Etc
    """.split()
)


def find_unknown_candidates(
    text: str,
    matches: list[RawMatch],
    direction: str,
    nnp_spans: set[tuple[int, int]] | None = None,
    limit: int = MAX_CANDIDATES,
) -> list[str]:
    """용어집에 없는 고유명사 후보를 뽑는다.

    모르는 약어를 만나면 모델이 그럴듯한 것을 지어내고, 형태가 자연스러워
    검수자가 놓친다 (R-04). 여기서 잡아 `warnings` 로 노출하고 후보 큐에 쌓는다.

    ko2en 은 Kiwi 의 NNP 구간을, en2ko 는 약어·고유명사 패턴을 쓴다.
    """
    covered = _covered_positions(matches)
    spans: list[tuple[int, int]] = []

    if direction == "ko2en":
        # 뒤에 계급·직함이 오면 사람 이름이다. 용어집 항목이 아니다.
        spans.extend((s, e) for s, e in (nnp_spans or ()) if not _looks_like_person(text, e))
        # 형태소 태그로 못 잡는 무기·체계 명칭을 표층 패턴으로 보강한다.
        spans.extend((m.start(), m.end()) for m in _KO_DESIGNATION.finditer(text))
    else:
        spans.extend((m.start(), m.end()) for m in _ACRONYM.finditer(text))
        spans.extend(
            (m.start(), m.end())
            for m in _PROPER_RUN.finditer(text)
            if m.group(0) not in _STOP_PROPER
        )

    # **완전히** 덮인 것만 제외한다. 일부만 겹치면 변형이라는 뜻이고, 변형이야말로
    # 등록이 필요한 후보다 — 용어집에 `천무` 가 있어도 `천무-Ⅱ` 는 따로
    # 올라와야 한다 (§4.4 응답 예시).
    spans = [(s, e) for s, e in set(spans) if not all(p in covered for p in range(s, e))]

    # 긴 것이 짧은 것을 삼킨다. `백호` 와 `백호-3` 을 둘 다 올리면 검수 대기열에
    # 같은 항목이 두 번 쌓인다.
    spans.sort(key=lambda p: (-(p[1] - p[0]), p[0]))
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if any(k_start <= start and end <= k_end for k_start, k_end in kept):
            continue
        kept.append((start, end))

    found: list[str] = []
    seen: set[str] = set()
    for start, end in sorted(kept):
        surface = text[start:end].strip()
        if len(surface) < 2 or surface in seen:
            continue
        seen.add(surface)
        found.append(surface)

    return found[:limit]


def _looks_like_person(text: str, span_end: int) -> bool:
    """구간 바로 뒤에 계급이나 직함이 오는가.

    `김철수 대령` → True. `제7기동군단 예하` → False.
    """
    return bool(_PERSON_TITLE_RE.match(text, span_end))


def _covered_positions(matches: list[RawMatch]) -> set[int]:
    covered: set[int] = set()
    for m in matches:
        covered.update(range(m.start, m.end))
    return covered
