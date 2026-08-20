"""glossary.jsonl 유효성 — 계획서 §4.2, §5.1, R-11.

사람이 편집하는 파일이라 문법 오류가 실제로 난다. 로더가 **줄 번호와 함께**
원인을 알려주는지가 이 파일의 핵심 관심사다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT
from app.glossary.loader import (
    GlossaryError,
    Term,
    load_glossary,
    load_meta,
)

GLOSSARY = PROJECT_ROOT / "data" / "glossary.jsonl"
META = PROJECT_ROOT / "data" / "glossary.meta.json"

VALID_LINE = {
    "id": "T-0142",
    "ko": "합동참모본부",
    "en": "Joint Chiefs of Staff",
    "en_abbr": "JCS",
    "ko_aliases": ["합참"],
    "en_aliases": [],
    "conditions": None,
    "domain_tag": ["편제"],
    "priority": 10,
    "corpus_freq": 0,
    "abbr_policy": "first_full_then_abbr",
    "source": "테스트",
    "confidence": "verified",
    "note": "",
}


def write_jsonl(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── 실제 저장소 파일 ──────────────────────────────────────────


def test_repo_glossary_loads() -> None:
    terms = load_glossary(GLOSSARY)
    assert terms, "샘플 용어집이 비어 있다"


def test_repo_meta_matches_count() -> None:
    """meta.count 와 실제 용어 수가 같아야 한다. 반입 사고의 신호다."""
    terms = load_glossary(GLOSSARY)
    meta = load_meta(META)
    assert meta.count == len(terms)


def test_repo_glossary_required_fields_filled() -> None:
    """`source` 와 `confidence` 는 비워두지 않는다 (§5.1).

    나중에 대역이 충돌할 때 어느 쪽을 신뢰할지 판단하는 유일한 근거다.
    """
    for term in load_glossary(GLOSSARY):
        assert term.source.strip(), f"{term.id}: source 가 비었다"
        assert term.confidence in {"verified", "probable", "candidate"}


def test_repo_glossary_no_duplicate_surface() -> None:
    """서로 다른 id 가 같은 표층형을 가리키면 매칭이 흔들린다 (Phase 1 lint 선행)."""
    seen: dict[str, str] = {}
    collisions: list[str] = []
    for term in load_glossary(GLOSSARY):
        for surface in term.source_forms("ko2en"):
            owner = seen.setdefault(surface, term.id)
            if owner != term.id:
                collisions.append(f"{surface!r}: {owner} vs {term.id}")
    assert not collisions, "표층형 충돌: " + ", ".join(collisions)


# ── 로더 오류 보고 (R-11) ─────────────────────────────────────


def test_error_reports_line_number(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "g.jsonl",
        [
            json.dumps(VALID_LINE, ensure_ascii=False),
            "{ this is not json }",
        ],
    )
    with pytest.raises(GlossaryError) as exc:
        load_glossary(path)
    assert exc.value.lineno == 2
    assert "g.jsonl:2" in str(exc.value)


def test_missing_required_field_reports_field_name(tmp_path: Path) -> None:
    broken = {k: v for k, v in VALID_LINE.items() if k != "source"}
    path = write_jsonl(tmp_path / "g.jsonl", [json.dumps(broken, ensure_ascii=False)])
    with pytest.raises(GlossaryError) as exc:
        load_glossary(path)
    assert "source" in str(exc.value)


def test_typo_in_field_name_is_caught(tmp_path: Path) -> None:
    """`extra="forbid"` 가 필드명 오타를 잡는다."""
    typo = {**VALID_LINE, "confidance": "verified"}
    del typo["confidence"]
    path = write_jsonl(tmp_path / "g.jsonl", [json.dumps(typo, ensure_ascii=False)])
    with pytest.raises(GlossaryError) as exc:
        load_glossary(path)
    assert "confid" in str(exc.value)


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    line = json.dumps(VALID_LINE, ensure_ascii=False)
    path = write_jsonl(tmp_path / "g.jsonl", [line, line])
    with pytest.raises(GlossaryError) as exc:
        load_glossary(path)
    assert "중복" in str(exc.value)
    assert exc.value.lineno == 2


def test_bad_id_format_is_rejected(tmp_path: Path) -> None:
    bad = {**VALID_LINE, "id": "142"}
    path = write_jsonl(tmp_path / "g.jsonl", [json.dumps(bad, ensure_ascii=False)])
    with pytest.raises(GlossaryError):
        load_glossary(path)


def test_comments_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "g.jsonl",
        [
            "// 머리말",
            "",
            json.dumps(VALID_LINE, ensure_ascii=False),
            "",
            "// 꼬리말",
        ],
    )
    assert len(load_glossary(path)) == 1


# ── 표층형 전개 ───────────────────────────────────────────────


def test_source_forms_by_direction() -> None:
    term = Term(**VALID_LINE)
    assert term.source_forms("ko2en") == ["합동참모본부", "합참"]
    assert term.source_forms("en2ko") == ["Joint Chiefs of Staff", "JCS"]


def test_target_forms_include_abbr() -> None:
    term = Term(**VALID_LINE)
    assert "JCS" in term.target_forms("ko2en")
    assert "합참" in term.target_forms("en2ko")


def test_ambiguous_target_forms_include_all_branches() -> None:
    """다의어는 분기 대역어를 전부 인정한다 (§5.3).

    코드가 조건을 확정하지 못했을 때 모델이 문맥으로 고른 쪽을 위반으로
    잡으면 안 된다.
    """
    term = Term(
        **{
            **VALID_LINE,
            "id": "T-0087",
            "ko": "대령",
            "en": "Colonel",
            "en_abbr": None,
            "ko_aliases": [],
            "conditions": {
                "field": "service",
                "branches": [
                    {"value": ["육군", "공군", "해병대"], "en": "Colonel"},
                    {"value": ["해군"], "en": "Captain"},
                ],
            },
        }
    )
    forms = term.target_forms("ko2en")
    assert "Colonel" in forms
    assert "Captain" in forms
    assert term.is_ambiguous
