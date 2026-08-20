"""골든셋 로드 — 계획서 §11 Phase 3, §12.

계획서 §4.2 에 이 파일이 없다. `data/goldenset.jsonl` 은 §9.2 반입 번들에만
등장하고 로더의 자리가 정해져 있지 않아 여기 둔다.

골든셋은 **사람이 검수한 정답 번역**이다 (§11 Phase 3). 검수되지 않은 항목이
섞이면 평가 결과가 조용히 오염되므로, `quality` 를 필수로 두고 `verified` 가
아닌 것을 세어 알린다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.glossary.loader import GlossaryError

Direction = Literal["ko2en", "en2ko"]
#: `sample` 은 배선 확인용 합성 데이터다. 품질 지표 산출에 쓰면 안 된다.
Quality = Literal["verified", "sample"]

GOLDEN_ID_PATTERN = r"^G-\d{3,}$"


class GoldenEntry(BaseModel):
    """골든셋 한 건."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=GOLDEN_ID_PATTERN)
    direction: Direction
    src: str = Field(min_length=1)
    #: 참조 번역. chrF / COMET 의 기준이 된다.
    ref: str = Field(min_length=1)
    #: 이 문장에서 매칭되어야 할 term_id. 매칭 엔진 회귀에도 쓴다.
    expect_terms: list[str] = Field(default_factory=list)
    #: 평가 결과를 갈라 볼 축. `proper_noun_dense`, `ambiguous_rank` 등.
    tags: list[str] = Field(default_factory=list)
    quality: Quality = "sample"
    note: str = ""

    @property
    def is_verified(self) -> bool:
        return self.quality == "verified"


def load_goldenset(path: Path) -> list[GoldenEntry]:
    """JSONL 을 읽는다. 오류는 줄 번호와 함께 올린다.

    파일이 없으면 빈 목록 — 골든셋은 Phase 3 자산이라 그전에는 없는 것이 정상이다.
    """
    if not path.is_file():
        return []

    entries: list[GoldenEntry] = []
    seen: dict[str, int] = {}

    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                raise GlossaryError(path, lineno, f"JSON 파싱 실패: {e}") from e
            try:
                entry = GoldenEntry(**payload)
            except ValidationError as e:
                raise GlossaryError(path, lineno, str(e)) from e

            if entry.id in seen:
                raise GlossaryError(
                    path, lineno, f"id 중복: {entry.id} (최초 등장 {seen[entry.id]}행)"
                )
            seen[entry.id] = lineno
            entries.append(entry)

    return entries


def summarize(entries: list[GoldenEntry]) -> dict:
    """구성 요약. 러너가 실행 전에 찍어 사람이 확인하게 한다.

    `sample_count` 가 0 이 아니면 그 결과는 품질 지표가 아니다.
    """
    return {
        "total": len(entries),
        "ko2en": sum(1 for e in entries if e.direction == "ko2en"),
        "en2ko": sum(1 for e in entries if e.direction == "en2ko"),
        "verified_count": sum(1 for e in entries if e.is_verified),
        "sample_count": sum(1 for e in entries if not e.is_verified),
        "tags": sorted({t for e in entries for t in e.tags}),
    }
