"""병렬 코퍼스 문장 정렬 — 계획서 §11 Phase 1 작업 3.

구현 시점: **Phase 1**. LaBSE 임베딩 + DP 정렬.

유사도 임계값 미달 쌍은 폐기한다 — **오염된 데이터가 없는 것보다 나쁘다.**
TM 은 few-shot 예시로 모델에 그대로 제시되므로(§7.6) 잘못 정렬된 쌍이 섞이면
문체와 용어를 함께 오염시킨다.

개발망 전용이다. `sentence-transformers` 는 모델을 내려받으므로 이 스크립트를
`app/` 에서 import 하면 안 된다 (§9.3).
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("문장 정렬은 Phase 1 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
