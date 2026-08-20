"""glossary.jsonl 로드 / 검증 — 계획서 §5.1.

사람이 직접 편집하는 파일이라 문법 오류가 실제로 발생한다 (R-11).
**로딩 실패 시 반드시 줄 번호를 알려준다.**
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Confidence = Literal["verified", "probable", "candidate"]
AbbrPolicy = Literal["first_full_then_abbr", "always_full", "always_abbr"]

#: `T-####`. 용어집이 1만 건을 넘을 수 있으므로 자릿수는 4 이상을 허용한다.
TERM_ID_PATTERN = r"^T-\d{4,}$"


class GlossaryError(ValueError):
    """줄 번호가 붙은 용어집 오류."""

    def __init__(self, path: Path, lineno: int, detail: str) -> None:
        self.path = path
        self.lineno = lineno
        self.detail = detail
        super().__init__(f"{path.name}:{lineno} — {detail}")


class Term(BaseModel):
    """용어 한 건 (§5.1).

    `extra="forbid"` 로 두어 필드명 오타를 로딩 시점에 잡는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=TERM_ID_PATTERN)
    ko: str = Field(min_length=1)
    en: str = Field(min_length=1)
    en_abbr: str | None = None
    ko_aliases: list[str]
    en_aliases: list[str]
    conditions: dict[str, Any] | None = None
    domain_tag: list[str]
    priority: int
    corpus_freq: int = Field(ge=0)
    abbr_policy: AbbrPolicy | None = None
    #: 출처. 대역 충돌 시 어느 쪽을 신뢰할지 판단하는 유일한 근거다. 비우지 말 것.
    source: str = Field(min_length=1)
    confidence: Confidence
    note: str

    # ── 방향별 표층형 ─────────────────────────────────────────

    def source_forms(self, direction: str) -> list[str]:
        """원문 쪽에서 찾아야 할 표층형. 매칭 인덱스가 쓴다 (§6.3)."""
        if direction == "ko2en":
            return _dedup([self.ko, *self.ko_aliases])
        return _dedup([self.en, *([self.en_abbr] if self.en_abbr else []), *self.en_aliases])

    def target_forms(self, direction: str) -> list[str]:
        """번역문에 나타나야 할 표층형. 검증이 쓴다 (§6.5).

        다의어(§5.3)는 분기 대역어를 전부 인정한다. 코드가 조건을 확정하지 못한
        경우 모델이 문맥으로 고른 쪽을 위반으로 처리하면 안 되기 때문이다.
        """
        if direction == "ko2en":
            forms = [self.en, *([self.en_abbr] if self.en_abbr else []), *self.en_aliases]
            forms.extend(self._branch_forms("en"))
        else:
            forms = [self.ko, *self.ko_aliases]
            forms.extend(self._branch_forms("ko"))
        return _dedup(forms)

    def _branch_forms(self, key: str) -> list[str]:
        if not self.conditions:
            return []
        out: list[str] = []
        for branch in self.conditions.get("branches", []):
            value = branch.get(key)
            if isinstance(value, str) and value:
                out.append(value)
        return out

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.conditions)


class GlossaryMeta(BaseModel):
    """glossary.meta.json (§5.1).

    인덱스 재빌드 판단에 쓴다. 파일 mtime 보다 명시적 버전이 안전하다
    (반입 과정에서 mtime 이 바뀔 수 있음).
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    updated_at: datetime
    count: int = Field(ge=0)
    note: str = ""


def _dedup(items: list[str]) -> list[str]:
    """순서를 유지하며 중복과 빈 문자열을 제거한다."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_glossary(path: Path) -> list[Term]:
    """JSONL 을 읽어 Term 목록을 만든다.

    빈 줄과 `//` 로 시작하는 주석 줄은 건너뛴다.
    오류는 줄 번호와 함께 GlossaryError 로 올린다.
    """
    terms: list[Term] = []
    seen_ids: dict[str, int] = {}

    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                raise GlossaryError(path, lineno, f"JSON 파싱 실패: {e}") from e
            if not isinstance(payload, dict):
                raise GlossaryError(path, lineno, "객체가 아님 (한 줄에 용어 하나)")
            try:
                term = Term(**payload)
            except ValidationError as e:
                raise GlossaryError(path, lineno, _format_validation_error(e)) from e

            if term.id in seen_ids:
                raise GlossaryError(
                    path, lineno, f"id 중복: {term.id} (최초 등장 {seen_ids[term.id]}행)"
                )
            seen_ids[term.id] = lineno
            terms.append(term)

    return terms


def load_meta(path: Path) -> GlossaryMeta:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GlossaryError(path, 1, f"JSON 파싱 실패: {e}") from e
    try:
        return GlossaryMeta(**payload)
    except ValidationError as e:
        raise GlossaryError(path, 1, _format_validation_error(e)) from e


def _format_validation_error(e: ValidationError) -> str:
    """pydantic 오류를 사람이 읽을 한 줄로 줄인다."""
    parts = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "(최상위)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
