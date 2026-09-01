"""BM25 유사 문장 검색 — 계획서 §6.4.

용어집과 달리 TM 은 **퍼지 검색이 적합하다.** 문장 단위 유사도라 오탐 위험이
낮고, 예시로만 쓰이므로 강제되지 않는다.

BM25 로 시작하고, 필요하면 임베딩으로 승급한다. **임베딩 도입은 실제 성능
부족이 확인된 뒤에만** 검토한다 — 에어갭에서 임베딩 모델을 추가 반입하는
부담이 크다 (§6.4, §9.2).

few-shot 예시는 **의미 유사성보다 구문 유사성을 우선**한다 (§7.6). BM25 는
표층 토큰을 보므로 의미 임베딩보다 구문 쪽에 가깝다 — 이 과제에서는 그 편이
맞다. 군사 보도자료는 구문 패턴이 반복된다.
"""

from __future__ import annotations

import re

from app.logging import get_logger
from app.tm.loader import TMEntry

logger = get_logger(__name__)

TM_TOP_K = 3
TM_MIN_SCORE = 0.35

_WORD = re.compile(r"[0-9a-z]+|[가-힣]+", re.IGNORECASE)


class RetrieverUnavailableError(RuntimeError):
    """rank-bm25 가 없다."""


def retriever_available() -> bool:
    try:
        import rank_bm25  # noqa: F401
    except ImportError:
        return False
    return True


def tokenize(text: str, direction: str) -> list[str]:
    """BM25 용 토큰.

    한국어는 조사가 붙어 표층형이 흔들리므로 2-gram 도 함께 넣는다.
    형태소 분석기를 쓰면 더 정확하지만, TM 인덱스는 기동 시 한 번에 5만 문장을
    처리해야 해서(§6.7) 비용이 크다. 검색 품질이 부족하면 그때 교체한다.
    """
    words = [w.lower() for w in _WORD.findall(text)]
    if direction != "ko2en":
        return words

    tokens = list(words)
    for word in words:
        if len(word) > 2 and "가" <= word[0] <= "힣":
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


class BM25Retriever:
    """한 방향의 TM 인덱스.

    인덱스 빌드가 TM 5만 쌍 기준 5~10초 걸린다 (§6.7). 기동 시 한 번만 만든다.
    """

    def __init__(self, entries: list[TMEntry], direction: str) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as e:  # pragma: no cover - 설치 환경에 따름
            raise RetrieverUnavailableError(
                "rank-bm25 가 설치되어 있지 않다. requirements.txt 를 볼 것"
            ) from e

        self.direction = direction
        self.entries = entries
        corpus = [tokenize(e.query_side(direction), direction) for e in entries]
        # 빈 문서가 있으면 BM25Okapi 가 0으로 나눈다.
        self._usable = bool(corpus) and any(corpus)
        self._bm25 = BM25Okapi(corpus) if self._usable else None

    def __len__(self) -> int:
        return len(self.entries)

    def retrieve(
        self,
        query: str,
        top_k: int = TM_TOP_K,
        min_score: float = TM_MIN_SCORE,
    ) -> list[tuple[str, str]]:
        """유사 문장 쌍을 준다. 반환은 (원문, 번역문).

        BM25 점수는 상한이 없어 그대로 임계값과 비교할 수 없다. 이 검색의
        최고 점수로 나눠 [0,1] 로 정규화한 뒤 `min_score` 와 견준다 — 절대
        점수가 아니라 "가장 비슷한 것 대비 얼마나 비슷한가" 를 본다.
        """
        if not self._usable or not query.strip():
            return []

        tokens = tokenize(query, self.direction)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        best = max(scores) if len(scores) else 0.0
        if best <= 0:
            return []

        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: list[tuple[str, str]] = []
        for i in ranked[:top_k]:
            if scores[i] / best < min_score:
                break
            out.append(self.entries[i].as_example(self.direction))
        return out
