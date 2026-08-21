"""요청/응답 Pydantic 모델 — 계획서 §4.4.

`terms_applied` 와 `warnings` 는 현재 프론트에 표시 위치가 없어도 처음부터
반환한다. 나중에 용어 하이라이트 UI 를 붙일 때 백엔드를 고치지 않기 위해서다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["ko", "en"]


class TranslateRequest(BaseModel):
    """POST /translate 요청 본문.

    길이 상한은 여기서 걸지 않는다. `NDT_MAX_INPUT_CHARS` 를 단일 출처로 두고
    엔드포인트에서 검사해 413 을 돌려준다.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    source: Lang
    target: Lang
    #: 문체 (§7.3). 비우면 `NDT_DEFAULT_STYLE` 을 쓴다.
    #: 여기에 기본값을 박으면 설정값이 영영 적용되지 않는다 — 요청마다 항상
    #: 값이 채워져 `req.style or settings.default_style` 의 오른쪽이 죽는다.
    style: str | None = None


class TermApplied(BaseModel):
    """적용된 용어 한 건. `spans` 는 **원문 좌표**다 (정규화 전 기준)."""

    source: str
    target: str
    term_id: str
    spans: list[list[int]] = Field(default_factory=list)
    confidence: str


class TranslateMeta(BaseModel):
    chunks: int
    retries: int
    elapsed_ms: int
    backend: str
    prompt_version: str
    #: 어느 용어집 버전으로 번역했는지. 회귀 비교에 필요하다 (§5.4).
    glossary_version: int | None = None


class TranslateResponse(BaseModel):
    translation: str
    terms_applied: list[TermApplied] = Field(default_factory=list)
    #: 형태가 종류마다 다르다 (term_missing / unknown_candidate / empty_chunk).
    #: 종류를 늘릴 때 스키마를 고치지 않도록 열어 둔다 (§4.4).
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    meta: TranslateMeta


class HealthResponse(BaseModel):
    """헬스체크 (§6.7).

    인덱스 빌드에 10~20초가 걸리므로 그동안 `ready=false` 를 반환해야 한다.
    """

    status: Literal["ok", "starting", "error"]
    ready: bool
    version: str
    backend: str
    backend_ready: bool
    glossary_version: int | None = None
    term_count: int | None = None
    build_ms: int | None = None
    #: 실제로 쓰이는 문장 분할기: `kiwi` 또는 `rule` (D-22).
    #: `rule` 이면 kiwipiepy 가 없거나 use_kiwi=False 다.
    segmenter: str | None = None
    #: 용어 매칭기: `aho-corasick` 또는 `none`.
    #: `none` 이면 pyahocorasick 이 없어 용어 주입 없이 번역만 된다.
    matcher: str | None = None
    #: TM 세그먼트 수. 0 이면 few-shot 예시 없이 동작한다.
    tm_size: int | None = None
    #: 쓸 수 있는 문체 (§7.3). `{키: 표시이름}`.
    #: 프론트의 문체 선택기가 이걸 보고 만들면 키를 추측하지 않아도 된다.
    styles: dict[str, str] | None = None
    #: 모델 서버가 서빙 중인 모델 이름. mock 이면 None.
    model: str | None = None
    detail: str | None = None


class ReloadResponse(BaseModel):
    """POST /admin/reload (§6.7 핫리로드)."""

    glossary_version: int
    term_count: int
    build_ms: int
