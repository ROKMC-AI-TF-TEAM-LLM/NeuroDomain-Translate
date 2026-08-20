"""용어 후보 추출 — 계획서 §11 Phase 1 작업 4.

구현 시점: **Phase 1**.

  - 통계: 로그 우도비 + Dice 계수로 다어절 병합
  - LLM: 정렬 문장 쌍에서 용어 쌍 추출.
    **few-shot 예시는 구문 유사성 기준으로 선택할 것** (§7.6)
  - 두 결과 교차 검증, 빈도 집계

작업 5(`corpus_freq` 채우기)도 여기서 함께 처리한다. 실제 코퍼스 등장 빈도가
주입 우선순위 계산(§6.3)에 쓰이므로, 0 으로 두면 희소도 가중이 동작하지 않는다.
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("용어 후보 추출은 Phase 1 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
