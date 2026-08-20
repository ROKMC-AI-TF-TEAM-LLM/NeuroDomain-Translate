"""확보 용어집 파싱 → glossary.jsonl — 계획서 §11 Phase 1 작업 1.

구현 시점: **Phase 1**.

⚠ **O-02(확보 용어집의 현재 형태: 엑셀/HWP/PDF/DB)가 확정되기 전에는 파서를
쓸 수 없다.** 추정해서 만들지 말 것 (§0.2 규칙 1).

확정 후 할 일:
  - `ko / en / en_abbr / ko_aliases / en_aliases` 5열로 정규화
  - 이형태 자동 생성 (로마숫자↔아라비아, 하이픈 유무 등)
  - 출력은 data/glossary.jsonl (§5.1 스키마)
  - `source` 와 `confidence` 를 반드시 채울 것. 비면 대역 충돌 시 판단 근거가 없다.
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("용어집 파서는 O-02 확정 후 Phase 1 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
