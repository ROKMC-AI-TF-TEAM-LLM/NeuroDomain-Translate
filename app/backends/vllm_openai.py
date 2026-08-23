"""OpenAI 호환 HTTP 백엔드 — 계획서 §4.2, §4.3.

vLLM 과 llama.cpp 가 같은 `/v1/chat/completions` 프로토콜을 쓰므로 하나로
처리한다. 서버가 어느 쪽이든 이 클래스가 담당한다.

에어갭 (§9.3):
  - `base_url` 은 **폐쇄망 내부 주소**여야 한다. 외부 URL 을 넣지 말 것.
  - 모델 이름은 서버가 이미 로컬에서 서빙 중인 이름을 그대로 쓴다. 이 프로세스는
    모델을 내려받지도, 토크나이저를 로드하지도 않는다.
  - 토큰 수가 필요하면 응답의 `usage` 를 쓴다.

프리픽스 캐싱 (§7.1): system 메시지에 ①~⑥ 층을 순서대로 넣고 원문은 user
메시지로 분리한다. 층 순서가 고정 → 가변이어야 캐시가 동작하며, 그 순서는
`pipeline/prompt.py` 와 템플릿이 보장한다.
"""

from __future__ import annotations

import time

import httpx

from app.backends.base import TranslationRequest, TranslationResult
from app.logging import get_logger

logger = get_logger(__name__)


class BackendError(RuntimeError):
    """모델 서버 호출 실패."""


class OpenAICompatBackend:
    """`/v1/chat/completions` 를 부르는 백엔드."""

    def __init__(
        self,
        base_url: str,
        served_name: str = "",
        *,
        timeout_s: float = 180.0,
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_tokens: int = 2048,
        label: str = "openai",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.served_name = served_name
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        #: 응답 meta.backend 와 translation_logs 에 실린다. 모델이 확인되면
        #: 실제 모델 이름으로 바뀐다 — 어느 모델로 번역했는지가 로그에 남아야
        #: 나중에 회귀 비교가 된다 (§5.4).
        self.name = label
        self._client: httpx.AsyncClient | None = None

    # ── 수명 ──────────────────────────────────────────────────

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 모델 이름 ─────────────────────────────────────────────

    async def resolve_model(self) -> str:
        """서빙 중인 모델 이름을 확정한다.

        설정에 이름이 없으면 `/v1/models` 의 첫 항목을 쓴다. llama.cpp 는 보통
        한 모델만 올리므로 이 편이 설정 부담이 적다.
        """
        if self.served_name:
            return self.served_name
        try:
            res = await self.client.get("/models")
            res.raise_for_status()
            data = res.json().get("data") or []
            if data:
                self.served_name = data[0]["id"]
                self.name = self.served_name
                logger.info("모델 확인: %s", self.served_name)
                return self.served_name
        except Exception as e:  # noqa: BLE001
            # 주소를 함께 알려야 한다. 폐쇄망에서 서버가 안 떠 있는 것인지
            # 주소가 틀린 것인지 로그만 보고 구분할 수 있어야 한다.
            raise BackendError(
                f"모델 서버({self.base_url})에서 모델 목록을 가져오지 못했다: {e}"
            ) from e
        raise BackendError(f"모델 서버({self.base_url})에 등록된 모델이 없다")

    # ── 번역 (§4.3) ───────────────────────────────────────────

    async def translate(self, req: TranslationRequest) -> TranslationResult:
        system_prompt = req.global_context.get("system_prompt", "")
        retry_prompt = req.global_context.get("retry_prompt")

        # 재호출은 대화형이 아니라 **새 요청**으로 구성한다 (§7.8).
        # 평시에는 표식으로 감싼 원문을 쓴다 — 없으면 원문 그대로 (§7.1 ⑦).
        user_content = retry_prompt or req.global_context.get("user_prompt") or req.text

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        raw = await self._chat(messages)
        return TranslationResult(text=raw, raw=raw, elapsed_ms=self._last_elapsed_ms)

    async def analyze(self, text: str, prompt: str) -> str:
        """보조 작업(군종 판정 등). 짧은 답만 받으면 되므로 상한을 줄인다."""
        raw = await self._chat(
            [{"role": "user", "content": prompt}], max_tokens=16, temperature=0.0
        )
        return raw.strip()

    async def health(self) -> bool:
        try:
            res = await self.client.get("/models")
            return res.status_code == 200
        except Exception as e:  # noqa: BLE001 - 헬스체크가 예외로 죽으면 안 된다
            logger.debug("백엔드 헬스체크 실패: %s", e)
            return False

    # ── 내부 ──────────────────────────────────────────────────

    _last_elapsed_ms: int = 0

    async def _chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        model = await self.resolve_model()
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "top_p": self.top_p,
            "stream": False,
        }
        limit = self.max_tokens if max_tokens is None else max_tokens
        if limit:
            payload["max_tokens"] = limit

        started = time.perf_counter()
        try:
            res = await self.client.post("/chat/completions", json=payload)
            res.raise_for_status()
            body = res.json()
        except httpx.HTTPStatusError as e:
            raise BackendError(
                f"모델 서버가 {e.response.status_code} 를 반환했다: {e.response.text[:300]}"
            ) from e
        except httpx.RequestError as e:
            raise BackendError(f"모델 서버({self.base_url})에 연결하지 못했다: {e}") from e
        self._last_elapsed_ms = int((time.perf_counter() - started) * 1000)

        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise BackendError(f"응답 형식이 예상과 다르다: {str(body)[:300]}") from e


#: 계획서 §4.2 가 이 파일을 vllm_openai.py 로 지정하고 있어 이름을 남겨 둔다.
VLLMOpenAIBackend = OpenAICompatBackend
