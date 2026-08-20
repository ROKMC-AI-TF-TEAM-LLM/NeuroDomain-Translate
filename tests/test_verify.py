"""용어 준수 검증 — 계획서 §6.5."""

from __future__ import annotations

from app.glossary.loader import Term
from app.glossary.matcher import TermMatch
from app.pipeline.verify import term_compliance_rate, verify

JCS = Term(
    id="T-0142",
    ko="합동참모본부",
    en="Joint Chiefs of Staff",
    en_abbr="JCS",
    ko_aliases=["합참"],
    en_aliases=[],
    conditions=None,
    domain_tag=["편제"],
    priority=10,
    corpus_freq=0,
    abbr_policy="first_full_then_abbr",
    source="테스트",
    confidence="verified",
    note="",
)

COLONEL = Term(
    id="T-0087",
    ko="대령",
    en="Colonel",
    ko_aliases=[],
    en_aliases=[],
    conditions={
        "field": "service",
        "branches": [
            {"value": ["육군", "공군", "해병대"], "en": "Colonel"},
            {"value": ["해군"], "en": "Captain"},
        ],
    },
    domain_tag=["계급"],
    priority=10,
    corpus_freq=0,
    source="테스트",
    confidence="verified",
    note="",
)


def match(term: Term) -> TermMatch:
    return TermMatch(term=term, spans=[(0, len(term.ko))], count=1)


def test_full_form_passes() -> None:
    violations = verify("합참은 밝혔다", "The Joint Chiefs of Staff said", [match(JCS)], "ko2en")
    assert violations == []


def test_abbreviation_passes() -> None:
    """약어도 지정 대역어다. full form 만 인정하면 오탐이 쏟아진다."""
    assert verify("합참은 밝혔다", "The JCS said", [match(JCS)], "ko2en") == []


def test_missing_term_is_flagged() -> None:
    violations = verify("합참은 밝혔다", "The military headquarters said", [match(JCS)], "ko2en")
    assert len(violations) == 1
    assert violations[0].term_id == "T-0142"
    assert violations[0].kind == "missing"


def test_verification_is_case_insensitive_for_english_target() -> None:
    assert verify("합참은", "the joint chiefs of staff said", [match(JCS)], "ko2en") == []


def test_korean_target_ignores_spacing() -> None:
    """en2ko 방향에서 띄어쓰기 차이로 위반이 잡히면 안 된다."""
    assert verify("The JCS said", "합동 참모 본부는 밝혔다", [match(JCS)], "en2ko") == []


def test_ambiguous_term_accepts_any_branch() -> None:
    """조건이 확정되지 않았으면 모델이 고른 분기를 인정한다 (§5.3, R-05)."""
    assert verify("대령은", "The Captain said", [match(COLONEL)], "ko2en") == []
    assert verify("대령은", "The Colonel said", [match(COLONEL)], "ko2en") == []


def test_no_applied_terms_means_no_violations() -> None:
    assert verify("아무 말", "anything", [], "ko2en") == []


def test_violation_converts_to_warning_shape() -> None:
    """§4.4 warnings 형식을 지켜야 프론트가 파싱한다."""
    violations = verify("합참은", "headquarters said", [match(JCS)], "ko2en")
    warning = violations[0].to_warning(chunk=2)
    assert warning["type"] == "term_missing"
    assert warning["term_id"] == "T-0142"
    assert warning["chunk"] == 2


# ── 용어 준수율 (§12.1 주 지표) ───────────────────────────────


def test_compliance_rate_all_pass() -> None:
    assert term_compliance_rate([match(JCS), match(COLONEL)], []) == 1.0


def test_compliance_rate_half() -> None:
    violations = verify("합참은", "headquarters", [match(JCS)], "ko2en")
    assert term_compliance_rate([match(JCS), match(COLONEL)], violations) == 0.5


def test_compliance_rate_without_terms_is_one() -> None:
    """용어가 없으면 위반도 없다. 0으로 나누지 말 것."""
    assert term_compliance_rate([], []) == 1.0
