"""반입 번들 생성 — 계획서 §9.2, §11 Phase 5 작업 1.

구현 시점: **Phase 5**.

⚠ **O-05(반입 절차)와 O-06(폐쇄망 OS / CUDA 버전)이 확정되어야 한다.**
플랫폼을 폐쇄망 서버와 일치시키지 못하면 wheel 이 설치되지 않는다.

번들 구성 (§9.2):
    bundle-YYYYMMDD/
    ├─ models/          HF snapshot 전체 + SHA256SUMS
    ├─ wheels/          pip download 결과 + requirements.lock.txt
    ├─ kiwi/            kiwipiepy_model-*.whl  ← 누락하면 폐쇄망에서 터진다
    ├─ data/            glossary.jsonl, glossary.meta.json, tm.jsonl, goldenset.jsonl
    │                   (runtime.db 는 반입하지 않는다 — 폐쇄망 최초 기동 시 생성)
    ├─ app/ prompts/    git archive
    ├─ INSTALL.md
    └─ MANIFEST.json    버전, 해시, 생성일시

용어집만 갱신하는 경량 절차는 §9.6 을 볼 것. 전체 번들을 다시 만들 필요가 없다.
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("번들 생성은 O-05/O-06 확정 후 Phase 5 에서 구현한다")


if __name__ == "__main__":
    raise SystemExit(main())
