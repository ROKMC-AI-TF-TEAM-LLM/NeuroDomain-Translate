"""평가 지표 — 계획서 §12.1.

구현 시점: **Phase 3**. Phase 0 은 자동 측정이 가능한 것 하나만 둔다.

**용어 준수율이 1순위다.** 용어집 기반이라 자동 측정이 가능하고 이 도메인의
핵심 요구사항과 직결된다. 일반 번역 품질 지표(chrF/COMET)는 보조다.

| 지표 | 계산 | 자동화 |
|---|---|---|
| 용어 준수율 | 원문 등장 용어 중 지정 대역어로 번역된 비율 | 완전 자동 |
| 용어 일관성 | 같은 용어가 텍스트 내 동일하게 번역된 비율 | 완전 자동 |
| 약어 처리 정확도 | 첫 등장 full form + 이후 약어 규칙 준수율 | 완전 자동 |
| chrF | 문자 n-gram F-score | 자동 (골든셋 필요) |
| COMET | 신경망 품질 추정 | 자동 (모델 반입 필요, 선택) |
"""

from __future__ import annotations

from app.pipeline.verify import term_compliance_rate

__all__ = ["term_compliance_rate", "term_consistency", "abbr_accuracy"]


def term_consistency(*args, **kwargs):
    """같은 용어가 문서 내 동일하게 번역되는가 (§12.1). Phase 3."""
    raise NotImplementedError("용어 일관성 지표는 Phase 3 에서 구현한다")


def abbr_accuracy(*args, **kwargs):
    """첫 등장 full form, 이후 약어 규칙 준수율 (§12.1). Phase 3."""
    raise NotImplementedError("약어 처리 정확도는 Phase 3 에서 구현한다")
