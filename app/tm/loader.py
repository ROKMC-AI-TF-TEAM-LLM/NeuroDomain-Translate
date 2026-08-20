"""tm.jsonl 로드 — 계획서 §5.2.

TM 에는 `id` 가 없다. 개별 참조가 아니라 검색 대상이라 인덱스상 위치로 충분하다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.glossary.loader import GlossaryError


class TMEntry(BaseModel):
    """과거 번역 문장 쌍 하나 (§5.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ko: str = Field(min_length=1)
    en: str = Field(min_length=1)
    source: str = ""
    style: str = "press_release"
    quality: str = "verified"

    def query_side(self, direction: str) -> str:
        return self.ko if direction == "ko2en" else self.en

    def as_example(self, direction: str) -> tuple[str, str]:
        return (self.ko, self.en) if direction == "ko2en" else (self.en, self.ko)


def load_tm(path: Path) -> list[TMEntry]:
    """JSONL 을 읽는다. 파일이 없으면 빈 목록 — TM 은 선택 자산이다.

    용어집과 달리 TM 이 없어도 서비스는 돈다. few-shot 예시가 빠질 뿐이다.
    """
    if not path.is_file():
        return []

    entries: list[TMEntry] = []
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
                entries.append(TMEntry(**payload))
            except ValidationError as e:
                raise GlossaryError(path, lineno, str(e)) from e
    return entries
