"""프롬프트 조립 (Jinja2) — 계획서 §7.

층 순서는 템플릿이 지킨다 (§7.1). 이 모듈은 층에 넣을 값을 만들 뿐이다.
**고정 → 가변 순서여야 vLLM 프리픽스 캐싱이 동작한다.** 템플릿을 고칠 때
⑥(출력 형식)을 ④(용어) 앞으로 옮기지 말 것 — 캐시 히트가 깨진다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.backends.base import TermHint

#: 프롬프트를 고칠 때마다 올린다. translation_logs 와 평가 결과에 함께 남는다.
#: 기록이 없으면 프롬프트 수정이 개선인지 퇴보인지 알 수 없다 (§7.10).
PROMPT_REVISION = 1

#: 프롬프트 버전 id 에 들어갈 짧은 이름 (§7.10). 없으면 style 이름을 그대로 쓴다.
_STYLE_SHORT = {
    "press_release": "press",
    "plain_report": "plain",
    "honorific": "honor",
    "default": "default",
}


@dataclass(frozen=True)
class PromptVersion:
    """§7.10. 응답 meta 와 로그에 실린다."""

    id: str  # "ko2en-press-v1"
    template_hash: str
    created_at: datetime


@dataclass
class ChunkContext:
    """③ 전역 컨텍스트에 들어갈 값 (§7.4).

    이 블록이 없으면 각 청크가 독립적으로 "첫 등장"이라 판단해 full form 을
    반복한다.
    """

    chunk_index: int = 0
    total_chunks: int = 1
    #: 군종. 판정되지 않았으면 None 이고 해당 줄을 생략한다.
    service_branch: str | None = None
    #: 앞선 청크에서 이미 소개된 용어 → 약어를 쓴다.
    introduced: list[str] = None  # type: ignore[assignment]
    #: 이 청크에서 처음 등장 → full form + 약어.
    first_here: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.introduced is None:
            self.introduced = []
        if self.first_here is None:
            self.first_here = []


class PromptBuilder:
    """템플릿과 문체 프리셋을 들고 있는다. 앱 수명 동안 하나만 둔다."""

    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir
        # autoescape 를 켜지 않는다: 산출물은 HTML 이 아니라 모델에 넣을 평문이다.
        # HTML 이스케이프가 끼면 용어의 & 나 따옴표가 망가진다.
        self.env = Environment(  # noqa: S701 - 평문 프롬프트. HTML 아님.
            loader=FileSystemLoader(str(prompts_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self._styles = self._load_styles(prompts_dir / "styles")

    # ── 문체 프리셋 ───────────────────────────────────────────

    @staticmethod
    def _load_styles(styles_dir: Path) -> dict[str, dict]:
        styles: dict[str, dict] = {}
        if not styles_dir.is_dir():
            return styles
        for path in sorted(styles_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            styles[path.stem] = data
        return styles

    def available_styles(self) -> list[str]:
        return sorted(self._styles)

    def has_style(self, style: str) -> bool:
        """그 문체가 실제로 있는가.

        없으면 `_style_block` 이 `default` 로 떨어진다. 조용히 떨어지면
        사용자가 높임말을 골랐는데 범용체가 나와도 알 방법이 없으므로,
        호출부가 이걸로 확인해 경고를 남긴다.
        """
        return style in self._styles

    def style_names(self) -> dict[str, str]:
        """style 키 → 사람이 읽을 이름. 프론트의 문체 선택기가 쓴다."""
        return {key: (data.get("name") or key) for key, data in self._styles.items()}

    def _style_block(self, style: str, direction: str) -> dict | None:
        data = self._styles.get(style) or self._styles.get("default")
        if not data:
            return None
        block = data.get(direction)
        if not block:
            return None
        return {
            "name": data.get("name", style),
            "register": block.get("register", ""),
            "rules": block.get("rules", []),
        }

    # ── 버전 (§7.10) ──────────────────────────────────────────

    @lru_cache(maxsize=16)  # noqa: B019 - 인스턴스 수명이 앱 수명과 같다
    def version(self, direction: str, style: str) -> PromptVersion:
        parts = [
            (self.prompts_dir / direction / "system.j2").read_bytes(),
            (self.prompts_dir / direction / "retry.j2").read_bytes(),
        ]
        style_path = self.prompts_dir / "styles" / f"{style}.yaml"
        if style_path.is_file():
            parts.append(style_path.read_bytes())
        digest = hashlib.sha256(b"\x00".join(parts)).hexdigest()[:12]
        short = _STYLE_SHORT.get(style, style)
        return PromptVersion(
            id=f"{direction}-{short}-v{PROMPT_REVISION}",
            template_hash=digest,
            created_at=datetime.now(UTC),
        )

    # ── 조립 ──────────────────────────────────────────────────

    def build_system(
        self,
        *,
        direction: str,
        style: str,
        preset: str,
        terms: list[TermHint],
        tm_examples: list[tuple[str, str]],
        context: ChunkContext,
    ) -> str:
        """①~⑥ 층을 채운 system 프롬프트를 만든다 (§7.1)."""
        template = self.env.get_template(f"{direction}/system.j2")
        return template.render(
            preset=preset,
            style=self._style_block(style, direction),
            context=context,
            terms=group_terms(terms, direction),
            tm_examples=tm_examples,
        )

    def build_retry(
        self,
        *,
        direction: str,
        previous: str,
        source: str,
        missing: list[dict[str, str]],
    ) -> str:
        """재호출 프롬프트 (§7.8). 대화형이 아니라 새 요청으로 구성한다."""
        template = self.env.get_template(f"{direction}/retry.j2")
        return template.render(previous=previous, source=source, missing=missing)

    def render_analyze(self, name: str, **context) -> str:
        """보조 판정 프롬프트 (prompts/analyze/). 군종 판정 등 (§7.4, R-05)."""
        return self.env.get_template(f"analyze/{name}.j2").render(**context)


def group_terms(terms: list[TermHint], direction: str) -> dict[str, list[dict]]:
    """④ 용어 대응표를 세 블록으로 나눈다 (§7.5).

    전부 한 덩어리로 주면 모델이 강제와 참고를 구분하지 못한다.
    """
    exact: list[dict] = []
    conditional: list[dict] = []
    reference: list[dict] = []

    for hint in terms:
        if hint.is_reference:
            reference.append({"source": hint.source, "target": _render_target(hint)})
        elif hint.conditions:
            conditional.append({"source": hint.source, "options": _render_options(hint, direction)})
        else:
            exact.append({"source": hint.source, "target": _render_target(hint)})

    return {"exact": exact, "conditional": conditional, "reference": reference}


def _render_target(hint: TermHint) -> str:
    """`Joint Chiefs of Staff (JCS)` 형태로 만든다."""
    target = hint.targets[0] if hint.targets else ""
    if hint.abbr and hint.abbr != target:
        return f"{target} ({hint.abbr})"
    return target


def _render_options(hint: TermHint, direction: str) -> str:
    """`Colonel (Army/Air Force/Marines) | Captain (Navy)` 형태로 만든다 (§5.3)."""
    key = "en" if direction == "ko2en" else "ko"
    branches: list[dict[str, Any]] = (hint.conditions or {}).get("branches", [])
    parts: list[str] = []
    for branch in branches:
        label = branch.get(key)
        if not label:
            continue
        values = branch.get("value") or []
        if values:
            parts.append(f"{label} ({'/'.join(str(v) for v in values)})")
        else:
            parts.append(str(label))
    if not parts:
        parts = list(hint.targets)
    return " | ".join(parts)
