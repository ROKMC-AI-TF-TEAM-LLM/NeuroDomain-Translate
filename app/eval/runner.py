"""골든셋 회귀 테스트 — 계획서 §12.3.

구현 시점: **Phase 3**.

프롬프트나 용어집을 수정할 때마다 골든셋 전체를 재실행하고 이전 버전과 비교한다.

    python -m app.eval.runner \\
      --goldenset data/goldenset.jsonl \\
      --backend gemma4-26b \\
      --prompt-version ko2en-press-v3 \\
      --compare-with ko2en-press-v2

평가 모드는 세 가지다 (§12.2). WMT25 방식을 따르면 용어집 효과를 인과적으로
분리할 수 있다.

  noterm  용어 없음
  proper  실제 매칭된 용어
  random  원문에서 무작위 추출한 단어

`random` 이 `proper` 보다 높게 나오면 지표 설계가 잘못된 것이다.
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("골든셋 러너는 Phase 3 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
