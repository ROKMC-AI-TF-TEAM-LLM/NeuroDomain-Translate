"""용어집 검증 — 계획서 §11 Phase 1 작업 1-b.

구현 시점: **Phase 1**. 지금은 `tests/test_glossary_schema.py` 가 같은 검사를
CI 에서 강제한다 (tools/README.md 참조).

Phase 1 에서 구현할 검사:
  - 스키마 필수 필드 확인                    ← 이미 로더가 한다
  - 표층형 중복 탐지 (서로 다른 id 가 같은 ko)  ← 이미 테스트가 한다
  - 대역 충돌 탐지 (같은 ko 에 다른 en)        ← **미구현**
  - source / confidence 누락 탐지             ← 이미 테스트가 한다

**CI 에 등록해 매 커밋마다 실행할 것** (R-11).
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("용어집 lint 도구는 Phase 1 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
