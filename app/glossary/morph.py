"""형태소 분석기 래퍼 (Kiwi 풀) — 계획서 §6.3, §6.6.

문장 분할(§6.2)도 여기서 담당한다. 계획서는 `kss` 를 쓰라고 하지만 Phase 0 의
의존성 트리 확인 결과 제외했다 (D-22, docs/phase0-notes.md §2-b). 대신
`Kiwi.split_into_sents()` 를 쓴다 — **용어집 사용자 사전이 문장 분할에도
적용되므로** 부대명이나 장비명 중간에서 문장이 끊기지 않는다.

에어갭 (§9.3): `kiwipiepy` 는 모델이 별도 패키지(`kiwipiepy_model`)이고
PyPI 에 wheel 이 없다. 반입 번들에는 개발망에서 만든 wheel 을 넣는다 (D-21).
런타임에 모델을 내려받는 경로는 없다 — 패키지가 없으면 여기서 조용히
규칙 기반으로 폴백하고 경고를 남긴다.

import 를 모듈 최상단에 두지 않는 이유: 런타임 의존성만 설치한
환경(CI, Phase 0)에서도 `app` 전체가 import 되어야 오프라인 테스트(§9.5)가 돈다.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Empty, Queue

from app.glossary.loader import Term
from app.logging import get_logger

logger = get_logger(__name__)

#: 고유명사 뒤에 붙는 형식 번호. `-Ⅱ`, `-5`, `-A`, `‑Ⅴ` 등.
#: 아라비아 숫자, 로마 숫자(ASCII · 유니코드), 대문자 한 덩어리를 받는다.
#:
#: 끝에 `\b` 를 붙이면 안 된다. 유니코드 로마 숫자(Ⅱ, U+2161)와 뒤따르는
#: 조사(도, 가)가 둘 다 단어 문자라 그 사이에 경계가 없어 매치가 통째로 실패한다.
#: 문자 클래스가 이미 범위를 막고 있으므로 `\b` 없이도 과하게 먹지 않는다.
_VARIANT_SUFFIX = re.compile(r"[-‐‑‒–—―][0-9IVXLCDMⅠ-ⅫA-Z]+")

#: 용어집 표제어를 사용자 사전에 넣을 때 주는 가중치.
#: 분석기가 최장 일치로 끊게 만드는 것이 목적이라 기본값보다 높게 준다.
USER_WORD_SCORE = 5.0

#: 고유명사 태그. "기계화보병사단에서는" → 기계화보병사단/NNP + 에서/JKB + 는/JX
USER_WORD_TAG = "NNP"


class KiwiUnavailableError(RuntimeError):
    """kiwipiepy 또는 그 모델 패키지가 없다."""


def kiwi_available() -> bool:
    """kiwipiepy 와 모델 패키지가 모두 있는지 본다."""
    try:
        import kiwipiepy  # noqa: F401
        import kiwipiepy_model  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class MorphToken:
    """형태소 하나. Phase 2 의 매칭 교차검증이 쓴다 (§6.3)."""

    form: str
    tag: str
    start: int
    end: int


class KoreanAnalyzer:
    """Kiwi 인스턴스 하나를 감싼다. **스레드 안전하지 않다** — 풀로 쓸 것 (§6.6).

    용어집 표제어를 사용자 사전에 `NNP` 로 등록하면 분석기가 최장 일치로 끊는다.
    Aho-Corasick 결과와 형태소 결과가 일치하면 `confirmed=True` 로 표시하고
    겹침 해소에서 우선순위를 올린다 (§6.3, Phase 2).
    """

    def __init__(self, terms: list[Term], *, model_path: str | None = None) -> None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as e:  # pragma: no cover - 설치 환경에 따름
            raise KiwiUnavailableError(
                "kiwipiepy 가 설치되어 있지 않다. requirements.txt 를 볼 것"
            ) from e

        # model_path 를 주지 않으면 kiwipiepy 가 kiwipiepy_model 패키지에서 찾는다.
        # 어느 쪽이든 로컬 파일이며 네트워크로 나가지 않는다.
        self.kiwi = Kiwi(model_path=model_path) if model_path else Kiwi()
        self._register_terms(terms)

    def _register_terms(self, terms: list[Term]) -> None:
        registered = 0
        for term in terms:
            for surface in term.source_forms("ko2en"):
                # 한 글자짜리는 등록하지 않는다. 오분석을 늘리기만 한다.
                if len(surface) < 2:
                    continue
                self.kiwi.add_user_word(surface, USER_WORD_TAG, USER_WORD_SCORE)
                registered += 1
        logger.debug("Kiwi 사용자 사전 등록: %d개 표층형", registered)

    # ── 문장 분할 (§6.2) ──────────────────────────────────────

    def split_sentences(self, text: str) -> list[tuple[int, str]]:
        """(시작 오프셋, 문장) 목록. 오프셋은 입력 문자열 기준이다.

        마침표만으로 자를 때 생기는 "제7사단", 약어, 소수점 오작동을 Kiwi 가
        문장 모델로 처리한다.
        """
        out: list[tuple[int, str]] = []
        for sent in self.kiwi.split_into_sents(text):
            body = sent.text.strip()
            if body:
                out.append((sent.start, body))
        return out

    # ── 형태소 분석 (§6.3, Phase 2 교차검증용) ────────────────

    def tokenize(self, text: str) -> list[MorphToken]:
        return [
            MorphToken(form=t.form, tag=t.tag, start=t.start, end=t.start + t.len)
            for t in self.kiwi.tokenize(text)
        ]

    def span_sets(self, text: str) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        """(NNP 구간, 변형 구간)을 **한 번의 토큰화**로 얻는다.

        두 종류를 따로 부르면 같은 텍스트를 두 번 분석한다. 5,000자 기준
        약 80ms 를 헛되이 쓰며, §11 Phase 2 의 200ms 예산을 그것만으로 넘긴다.
        전역 사전분석은 이쪽을 쓸 것.

        - NNP 구간: 매칭 결과와 **정확히** 비교해 confirmed 를 매긴다.
          여기서 구간을 늘리면 교차검증이 깨진다.
        - 변형 구간: `천무-Ⅱ`, `현무-Ⅴ` 처럼 형식 번호가 붙은 것. Kiwi 는
          하이픈에서 끊으므로 NNP 는 `천무` 까지만이고, 용어집에 `천무` 가
          있으면 완전히 덮여 미등록 후보에서 빠진다 — 정작 자기 항목이
          필요한 것은 변형 쪽이다 (§4.4 응답 예시, R-04).
        """
        nnp: set[tuple[int, int]] = set()
        variants: set[tuple[int, int]] = set()
        for token in self.tokenize(text):
            if token.tag != USER_WORD_TAG:
                continue
            nnp.add((token.start, token.end))
            m = _VARIANT_SUFFIX.match(text, token.end)
            if m:
                variants.add((token.start, m.end()))
        return nnp, variants

    def proper_noun_spans(self, text: str) -> set[tuple[int, int]]:
        """NNP 로 끊긴 구간. 둘 다 필요하면 `span_sets` 를 쓸 것."""
        return self.span_sets(text)[0]

    def variant_spans(self, text: str) -> set[tuple[int, int]]:
        """형식 번호가 붙은 구간. 둘 다 필요하면 `span_sets` 를 쓸 것."""
        return self.span_sets(text)[1]


class AnalyzerPool:
    """Kiwi 인스턴스 풀 (§6.6).

    인스턴스당 사용자 사전 등록이 1~3초 걸리므로(§6.7) 기동 시 한 번만 만든다.
    요청마다 만들면 안 된다.

    `acquire()` 는 블로킹이다. 비동기 코드에서는 `asyncio.to_thread` 안에서
    호출할 것 — 이벤트 루프를 막으면 안 된다.
    """

    def __init__(self, analyzers: list[KoreanAnalyzer]) -> None:
        if not analyzers:
            raise ValueError("분석기가 최소 1개는 있어야 한다")
        self._queue: Queue[KoreanAnalyzer] = Queue()
        for a in analyzers:
            self._queue.put(a)
        self.size = len(analyzers)

    @contextmanager
    def acquire(self, timeout: float = 30.0):
        try:
            analyzer = self._queue.get(timeout=timeout)
        except Empty as e:  # pragma: no cover - 포화 상태에서만
            raise TimeoutError(
                f"{timeout}초 안에 형태소 분석기를 얻지 못했다 (풀 크기 {self.size})"
            ) from e
        try:
            yield analyzer
        finally:
            self._queue.put(analyzer)


def build_pool(terms: list[Term], size: int, *, model_path: str | None = None) -> AnalyzerPool:
    """분석기 풀을 만든다. 인스턴스마다 사용자 사전을 새로 등록한다."""
    size = max(1, size)
    analyzers = [KoreanAnalyzer(terms, model_path=model_path) for _ in range(size)]
    return AnalyzerPool(analyzers)
