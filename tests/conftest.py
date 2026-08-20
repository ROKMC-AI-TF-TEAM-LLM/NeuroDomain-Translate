"""공용 픽스처.

각 테스트는 자기만의 `data/` 사본을 쓴다. runtime.db 가 테스트 간에 섞이면
로그 건수 단언이 서로를 깨뜨린다.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings
from app.main import create_app

REPO_DATA = PROJECT_ROOT / "data"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """저장소의 샘플 용어집을 임시 디렉터리로 복사한다."""
    target = tmp_path / "data"
    target.mkdir()
    for name in ("glossary.jsonl", "glossary.meta.json", "tm.jsonl"):
        src = REPO_DATA / name
        if src.is_file():
            shutil.copy(src, target / name)
    return target


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """테스트 기본 설정.

    저장소 루트의 `.env` 도 pydantic-settings 가 읽으므로, 결과가 개발자
    로컬 설정에 흔들리지 않도록 중요한 값은 전부 명시한다 (명시 인자가
    환경변수와 .env 보다 우선한다).

    `use_kiwi=False` 인 이유: Kiwi 인스턴스 하나를 만드는 데 사용자 사전
    등록으로 1~3초가 걸린다(§6.7). 매 픽스처마다 풀을 만들면 스위트가
    분 단위로 늘어난다. Kiwi 경로는 tests/test_morph.py 가 따로 덮는다.
    """
    for key in [k for k in os.environ if k.startswith("NDT_")]:
        monkeypatch.delenv(key, raising=False)
    return Settings(
        data_dir=data_dir,
        prompts_dir=PROJECT_ROOT / "prompts",
        backend="mock",
        admin_enabled=False,
        use_kiwi=False,
    )


@pytest.fixture
def client(settings: Settings):
    """lifespan 을 돌린 TestClient. 인덱스가 준비될 때까지 기다린다."""
    app = create_app(settings)
    with TestClient(app) as c:
        wait_ready(c)
        yield c


@pytest.fixture
def admin_client(settings: Settings):
    """/admin/reload 를 켠 클라이언트 (§6.7)."""
    app = create_app(settings.model_copy(update={"admin_enabled": True}))
    with TestClient(app) as c:
        wait_ready(c)
        yield c


@pytest.fixture
def kiwi_client(settings: Settings):
    """Kiwi 문장 분할기를 켠 클라이언트 (D-22).

    풀 생성에 시간이 걸리므로 꼭 필요한 테스트만 쓴다.
    """
    pytest.importorskip("kiwipiepy", reason="requirements-nlp.txt 미설치")
    pytest.importorskip("kiwipiepy_model", reason="kiwipiepy-model 미설치")
    app = create_app(settings.model_copy(update={"use_kiwi": True, "kiwi_pool_size": 1}))
    with TestClient(app) as c:
        wait_ready(c, timeout=60.0)
        yield c


def wait_ready(client: TestClient, timeout: float = 20.0) -> dict:
    """/health 가 ready 가 될 때까지 폴링한다 (§6.7).

    인덱스 빌드는 기동을 막지 않으므로(§6.7) 테스트가 명시적으로 기다려야 한다.
    """
    deadline = time.monotonic() + timeout
    payload: dict = {}
    while time.monotonic() < deadline:
        payload = client.get("/health").json()
        if payload.get("ready"):
            return payload
        if payload.get("status") == "error":
            raise AssertionError(f"인덱스 적재 실패: {payload.get('detail')}")
        time.sleep(0.02)
    raise AssertionError(f"{timeout}초 안에 준비되지 않았다: {payload}")
