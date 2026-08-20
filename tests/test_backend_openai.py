"""OpenAI 호환 백엔드 — 계획서 §4.3.

vLLM 과 llama.cpp 가 같은 프로토콜을 쓰므로 구현이 하나다. 여기서는
`httpx.MockTransport` 로 서버를 흉내 내므로 **모델 서버 없이도 돈다.**
실제 서버를 쓰는 확인은 tests/test_backend_live.py 가 담당한다.
"""

from __future__ import annotations

import httpx
import pytest

from app.backends.base import TermHint, TranslationRequest
from app.backends.vllm_openai import BackendError, OpenAICompatBackend

MODELS_BODY = {"data": [{"id": "skt/A.X-4.0-Light", "object": "model"}]}


def chat_body(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def make_backend(handler, **kwargs) -> OpenAICompatBackend:
    backend = OpenAICompatBackend("http://127.0.0.1:8000/v1", **kwargs)
    backend._client = httpx.AsyncClient(  # noqa: SLF001 - 테스트 이음매
        transport=httpx.MockTransport(handler), base_url=backend.base_url
    )
    return backend


def request_of(direction: str = "ko2en", **kwargs) -> TranslationRequest:
    base = {
        "text": "합참은 밝혔다.",
        "direction": direction,
        "global_context": {"system_prompt": "SYSTEM-LAYERS"},
    }
    base.update(kwargs)
    return TranslationRequest(**base)


# ── 모델 이름 확정 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolves_model_from_server() -> None:
    """이름을 안 주면 /v1/models 의 첫 항목을 쓴다."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/models")
        return httpx.Response(200, json=MODELS_BODY)

    backend = make_backend(handler)
    assert await backend.resolve_model() == "skt/A.X-4.0-Light"
    # 어느 모델로 번역했는지가 로그에 남아야 회귀 비교가 된다 (§5.4).
    assert backend.name == "skt/A.X-4.0-Light"
    await backend.aclose()


@pytest.mark.asyncio
async def test_configured_name_wins_and_skips_lookup() -> None:
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("이름이 설정되어 있으면 조회하지 않아야 한다")

    backend = make_backend(handler, served_name="my-local-model")
    assert await backend.resolve_model() == "my-local-model"
    await backend.aclose()


# ── 번역 (§7.1 층 구조) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_system_and_user_messages_are_separated() -> None:
    """①~⑥ 은 system, 원문은 user. 이 분리가 프리픽스 캐싱의 전제다 (§7.1)."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        import json

        captured.update(json.loads(req.content))
        return httpx.Response(200, json=chat_body("The JCS said."))

    backend = make_backend(handler)
    result = await backend.translate(request_of())

    assert result.text == "The JCS said."
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]
    assert captured["messages"][0]["content"] == "SYSTEM-LAYERS"
    assert captured["messages"][1]["content"] == "합참은 밝혔다."
    assert captured["stream"] is False
    await backend.aclose()


@pytest.mark.asyncio
async def test_retry_prompt_replaces_user_content() -> None:
    """재호출은 대화형이 아니라 새 요청으로 구성한다 (§7.8)."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        import json

        captured.update(json.loads(req.content))
        return httpx.Response(200, json=chat_body("fixed"))

    backend = make_backend(handler)
    await backend.translate(
        request_of(
            global_context={
                "system_prompt": "SYSTEM-LAYERS",
                "retry_prompt": "RETRY-BLOCK",
            }
        )
    )
    assert captured["messages"][1]["content"] == "RETRY-BLOCK"
    await backend.aclose()


@pytest.mark.asyncio
async def test_generation_params_are_sent() -> None:
    """번역은 결정적이어야 한다. 온도가 서버 기본값(0.8)으로 새면 안 된다."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        import json

        captured.update(json.loads(req.content))
        return httpx.Response(200, json=chat_body("ok"))

    backend = make_backend(handler, temperature=0.2, top_p=0.9, max_tokens=1024)
    await backend.translate(request_of())
    assert captured["temperature"] == 0.2
    assert captured["top_p"] == 0.9
    assert captured["max_tokens"] == 1024
    await backend.aclose()


@pytest.mark.asyncio
async def test_term_hints_do_not_reach_the_wire_directly() -> None:
    """용어는 프롬프트 조립 단계에서 system 층에 들어간다.

    백엔드가 임의로 덧붙이면 §7.1 층 순서가 깨진다.
    """
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        import json

        captured.update(json.loads(req.content))
        return httpx.Response(200, json=chat_body("ok"))

    backend = make_backend(handler)
    await backend.translate(
        request_of(terms=[TermHint(source="합참", targets=["JCS"], term_id="T-0142")])
    )
    assert len(captured["messages"]) == 2
    assert "T-0142" not in str(captured["messages"])
    await backend.aclose()


# ── 보조 작업 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_uses_tight_budget() -> None:
    """군종 판정은 토큰 하나면 된다. 길게 뽑으면 요청당 지연이 늘어난다."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        import json

        captured.update(json.loads(req.content))
        return httpx.Response(200, json=chat_body("  NAVY \n"))

    backend = make_backend(handler)
    assert await backend.analyze("본문", "PROMPT") == "NAVY"
    assert captured["max_tokens"] == 16
    assert captured["temperature"] == 0.0
    await backend.aclose()


# ── 오류 처리 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_error_becomes_backend_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        return httpx.Response(500, text="context length exceeded")

    backend = make_backend(handler)
    with pytest.raises(BackendError) as exc:
        await backend.translate(request_of())
    assert "500" in str(exc.value)
    assert "context length exceeded" in str(exc.value)
    await backend.aclose()


@pytest.mark.asyncio
async def test_connection_failure_names_the_address() -> None:
    """폐쇄망에서 서버가 안 떠 있을 때 원인을 바로 알 수 있어야 한다."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    backend = make_backend(handler)
    with pytest.raises(BackendError) as exc:
        await backend.translate(request_of())
    assert "127.0.0.1:8000" in str(exc.value)
    await backend.aclose()


@pytest.mark.asyncio
async def test_unexpected_payload_is_reported() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_BODY)
        return httpx.Response(200, json={"unexpected": True})

    backend = make_backend(handler)
    with pytest.raises(BackendError):
        await backend.translate(request_of())
    await backend.aclose()


# ── 헬스체크 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_true_when_models_reachable() -> None:
    backend = make_backend(lambda r: httpx.Response(200, json=MODELS_BODY))
    assert await backend.health() is True
    await backend.aclose()


@pytest.mark.asyncio
async def test_health_false_on_connection_error() -> None:
    """헬스체크가 예외로 죽으면 /health 자체가 500 이 된다."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    backend = make_backend(handler)
    assert await backend.health() is False
    await backend.aclose()


# ── 팩토리 (§4.3) ─────────────────────────────────────────────


@pytest.mark.parametrize("name", ["openai", "vllm", "llamacpp"])
def test_factory_builds_openai_backend_for_all_aliases(settings, name: str) -> None:
    from app.backends import build_backend

    backend = build_backend(settings.model_copy(update={"backend": name}))
    assert isinstance(backend, OpenAICompatBackend)
    assert backend.name == name


def test_factory_rejects_unknown_backend(settings) -> None:
    from app.backends import build_backend

    with pytest.raises(ValueError, match="알 수 없는 백엔드"):
        build_backend(settings.model_copy(update={"backend": "gpt-9"}))
