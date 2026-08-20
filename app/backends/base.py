"""번역 백엔드 추상화 — 계획서 §4.3.

모델 교체를 위한 경계다. **매칭·용어집·검증·웹앱은 모델을 모른다.**
새 백엔드를 추가할 때 이 파일의 자료구조를 바꾸지 말고 구현체만 늘릴 것.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class TermHint:
    """프롬프트에 넘길 용어 한 건 (§7.5)."""

    #: 프롬프트에 보일 원문 쪽 표기. 표제어와 매칭된 별칭을 함께 쓴다
    #: ("합동참모본부 / 합참"). 본문에 있는 말과 지정 대역어를 잇는 역할이다.
    source: str
    #: 후보가 여럿이면 조건부 (§5.3). 확정됐으면 원소 1개.
    targets: list[str]
    #: 원문에 실제로 나타난 표층형들. 백엔드와 테스트가 위치를 찾을 때 쓴다.
    #: 프롬프트 표기는 `source` 이며 이것을 직접 렌더링하지 않는다.
    surfaces: list[str] = field(default_factory=list)
    #: 다의어 분기 조건. 예: {"field": "service", "branches": [...]}
    conditions: dict | None = None
    #: 영문 약어. 첫 등장 처리(§7.4)에 쓴다.
    abbr: str | None = None
    #: True 면 "참고" 블록으로 간다. 강제하지 않으며 검증 대상도 아니다.
    is_reference: bool = False
    #: 역추적용. 응답 terms_applied 와 warnings 에 실린다.
    term_id: str = ""


@dataclass
class TranslationRequest:
    text: str
    direction: str  # "ko2en" | "en2ko"
    terms: list[TermHint] = field(default_factory=list)
    tm_examples: list[tuple[str, str]] = field(default_factory=list)
    style: str = "press_release"
    global_context: dict = field(default_factory=dict)
    prompt_version: str = ""


@dataclass
class TranslationResult:
    text: str  # 후처리 완료
    raw: str  # 후처리 전 (디버깅)
    elapsed_ms: int


@runtime_checkable
class TranslationBackend(Protocol):
    """백엔드 계약.

    `analyze` 는 번역이 아닌 보조 작업(군종 판정 등)용이다. 전용 MT 백엔드는
    `NotImplementedError` 로 두고 오케스트레이터가 규칙 기반으로 폴백한다.
    """

    #: 응답 meta.backend 에 실릴 이름.
    name: str

    async def translate(self, req: TranslationRequest) -> TranslationResult: ...

    async def analyze(self, text: str, prompt: str) -> str: ...

    async def health(self) -> bool: ...
