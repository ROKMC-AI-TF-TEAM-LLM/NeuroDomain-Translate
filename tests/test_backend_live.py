"""실제 모델 서버 연동 확인 (선택).

`.env` 의 `NDT_VLLM_BASE_URL` 이 가리키는 서버가 떠 있을 때만 돈다.
서버가 없으면 전부 skip 된다 — CI 에는 모델 서버가 없다.

품질을 재는 곳이 아니다. **개발 환경에서는 모델 품질을 평가하지 않는다** (§3.1).
여기서 보는 것은 배선뿐이다: 요청이 나가고, 응답이 파싱되고, 후처리가 걸리는가.

수동 실행:
    pytest tests/test_backend_live.py -v -s
"""

from __future__ import annotations

import os

import httpx
import pytest
import pytest_asyncio

from app.backends.base import TranslationRequest
from app.backends.vllm_openai import OpenAICompatBackend

BASE_URL = os.environ.get("NDT_VLLM_BASE_URL", "http://127.0.0.1:8000/v1")


def server_is_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/models", timeout=2.0).status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not server_is_up(), reason=f"모델 서버가 없다: {BASE_URL}")


@pytest_asyncio.fixture
async def backend():
    b = OpenAICompatBackend(BASE_URL, timeout_s=300.0, temperature=0.0)
    yield b
    await b.aclose()


@pytest.mark.asyncio
async def test_health(backend) -> None:
    assert await backend.health() is True


@pytest.mark.asyncio
async def test_model_is_resolved(backend) -> None:
    name = await backend.resolve_model()
    assert name
    print(f"\n서빙 중인 모델: {name}")


@pytest.mark.asyncio
async def test_ko2en_produces_english(backend) -> None:
    req = TranslationRequest(
        text="합동참모본부는 훈련을 실시했다고 밝혔다.",
        direction="ko2en",
        global_context={
            "system_prompt": (
                "You are a Korean-to-English translator. Output ONLY the translation."
            )
        },
    )
    result = await backend.translate(req)
    print(f"\n출력: {result.text}")
    assert result.text.strip()
    assert result.elapsed_ms > 0
    # 한글이 그대로 남아 있으면 번역이 아니라 반향이다.
    assert not any("가" <= ch <= "힣" for ch in result.text)


@pytest.mark.asyncio
async def test_analyze_returns_short_answer(backend) -> None:
    out = await backend.analyze("본문", "Answer with exactly one word: NAVY. Nothing else.")
    assert out.strip()
    assert len(out) < 60
