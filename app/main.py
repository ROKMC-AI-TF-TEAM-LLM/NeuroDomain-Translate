"""ASGI 진입점.

계획서 §4.2 모듈 구조에 진입점이 명시되어 있지 않아 여기에 둔다.
실행: `uvicorn app.main:app --host 0.0.0.0 --port 8080`

에어갭 (§9): 이 프로세스는 기동 시에도 런타임에도 외부 네트워크에 접근하지
않는다. 유일한 외부 통신은 폐쇄망 내부의 vLLM 서버 호출이며, 그것도 Phase 3
부터다.

다중 워커 주의 (R-12): `--workers N` 을 쓰면 프로세스마다 SQLite 커넥션과
인덱스 사본이 생긴다. WAL 모드라 동작은 하지만, 워커 수는 O-04(동시 접속자 수)
확정 후 결정한다. 그전까지는 워커 1개 + 비동기 동시성만 쓴다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router as health_router
from app.api.translate import router as translate_router
from app.backends import build_backend
from app.config import Settings, get_settings
from app.glossary.index import IndexRegistry
from app.logging import get_logger, setup_logging
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.prompt import PromptBuilder
from app.store.runtime import RuntimeStore

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # 진입점에서 한 번 부른다. uvicorn · httpx 로그까지 같은 포맷으로 맞춘다.
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "기동: backend=%s, 용어집=%s, 프롬프트=%s, 로그레벨=%s",
            settings.backend,
            settings.glossary_path,
            settings.prompts_dir,
            settings.log_level,
        )

        # 저장소는 즉시 연다. runtime.db 가 없으면 여기서 만들어진다 (§5.4).
        store = RuntimeStore(settings.runtime_db_path)
        store.connect()

        registry = IndexRegistry(settings)
        backend = build_backend(settings)
        prompts = PromptBuilder(settings.prompts_dir)

        app.state.settings = settings
        app.state.store = store
        app.state.registry = registry
        app.state.backend = backend
        app.state.prompts = prompts
        app.state.orchestrator = Orchestrator(settings, registry, backend, prompts)

        # 인덱스 빌드는 기다리지 않는다. 10~20초 걸리므로(§6.7) 그동안
        # /health 가 ready=false 를, /translate 가 503 을 돌려주게 둔다.
        app.state.index_task = asyncio.create_task(_load_index(registry))

        try:
            yield
        finally:
            task: asyncio.Task = app.state.index_task
            if not task.done():
                task.cancel()
            # HTTP 백엔드는 커넥션 풀을 들고 있다. 닫지 않으면 경고가 뜬다.
            aclose = getattr(backend, "aclose", None)
            if aclose is not None:
                await aclose()
            store.close()

    app = FastAPI(
        title="군사 도메인 한↔영 번역기",
        version=__version__,
        lifespan=lifespan,
    )

    # 프론트가 별도 오리진에서 뜬다 (Vite dev server 등).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(translate_router)
    return app


async def _load_index(registry: IndexRegistry) -> None:
    """기동 시 인덱스를 만든다. 실패해도 프로세스를 죽이지 않는다.

    죽이면 재시작 루프에 빠져 원인을 보기 어렵다. 대신 /health 가 status=error
    와 함께 줄 번호가 붙은 원인을 노출한다 (R-11).
    """
    try:
        await registry.ensure_loaded()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("기동 시 인덱스 적재 실패: %s", e)


app = create_app()
