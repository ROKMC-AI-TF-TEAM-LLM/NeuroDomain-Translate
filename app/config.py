"""설정 로딩 (환경변수) — 계획서 §4.2.

에어갭 제약(§9): 이 모듈은 네트워크에 접근하지 않는다. 모든 경로는 로컬이며,
모델 식별자는 HF Hub 이름이 아니라 **로컬 절대경로**를 받는다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

Direction = Literal["ko2en", "en2ko"]


class Settings(BaseSettings):
    """환경변수 `NDT_*` 로 덮어쓴다. 예: `NDT_PORT=9000`."""

    model_config = SettingsConfigDict(
        env_prefix="NDT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 서버 ──────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 9001
    #: 로그 레벨. DEBUG 면 청크별 상세까지 나온다.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # ── 경로 ──────────────────────────────────────────────────
    data_dir: Path = PROJECT_ROOT / "data"
    prompts_dir: Path = PROJECT_ROOT / "prompts"

    # ── 백엔드 (§4.3) ─────────────────────────────────────────
    #: `openai` 는 OpenAI 호환 HTTP 백엔드다. vLLM 과 llama.cpp 가 같은 프로토콜을
    #: 쓰므로 하나로 처리한다. `vllm` / `llamacpp` 는 같은 것을 가리키는 별칭이다.
    backend: Literal["mock", "openai", "vllm", "llamacpp"] = "mock"
    #: 모델 서버 주소. **폐쇄망 내부 주소여야 한다** (§9.3).
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    #: 서버에 등록된 모델 이름. 비우면 /v1/models 의 첫 항목을 쓴다.
    #: HF Hub 식별자를 다운로드용으로 쓰지 말 것 — 서버가 이미 로컬에서 서빙 중인
    #: 이름을 그대로 적는다 (§9.3).
    vllm_served_name: str = ""
    vllm_timeout_s: float = 180.0
    #: 생성 파라미터. 번역은 결정적이어야 하므로 온도를 낮게 둔다.
    gen_temperature: float = 0.2
    gen_top_p: float = 0.9
    #: 출력 토큰 상한. 0 이면 서버 기본값에 맡긴다.
    gen_max_tokens: int = 2048

    # ── 입력 제약 (D-05) ──────────────────────────────────────
    max_input_chars: int = 5000

    # ── 분할 · 형태소 (§6.2, §6.6) ────────────────────────────
    max_chunk_chars: int = 800
    #: Kiwi 를 문장 분할과 형태소 교차검증에 쓸지 (D-22).
    #: False 면 규칙 기반 분할기로 떨어진다. kiwipiepy 미설치 시에도 자동 폴백.
    use_kiwi: bool = True
    #: Kiwi 인스턴스 수 (§6.6). 인스턴스당 사용자 사전 등록에 1~3초 걸린다.
    kiwi_pool_size: int = 2
    #: Kiwi 모델 경로. 비우면 kiwipiepy_model 패키지에서 찾는다.
    #: 폐쇄망에서 모델을 파일로 반입한 경우에만 절대경로를 준다 (§9.3).
    kiwi_model_path: str = ""

    # ── 주입 선별 (§6.3) ──────────────────────────────────────
    chunk_term_limit: int = 10

    # ── 군종 판정 (§7.4, R-05) ────────────────────────────────
    #: 규칙으로 군종이 안 나올 때 모델에 물어볼지. 요청당 모델 호출이 하나
    #: 늘어나므로 O-04(동시 접속자 수) 확정 전까지 기본 비활성이다.
    #: 꺼져 있어도 다의어는 후보를 조건과 함께 프롬프트에 넘긴다 (§5.3).
    service_classify_llm: bool = False

    # ── TM 검색 (§6.4) ────────────────────────────────────────
    tm_top_k: int = 3
    tm_min_score: float = 0.35

    # ── 검증 / 재호출 (§6.5) ──────────────────────────────────
    #: 재호출 상한. 다중 접속 환경에서 재시도가 누적되면 큐를 막는다.
    max_retries: int = 1

    # ── 길이 이상 탐지 (§6.5) ─────────────────────────────────
    #: 출력이 원문 대비 이 배수를 넘으면 환각을 의심해 경고한다.
    #: 0 이면 검사하지 않는다. 방향별 기본값은 verify.py 참조.
    max_expansion_ratio: float = 0.0
    #: 출력이 원문 대비 이 배수에 못 미치면 누락을 의심한다 (R-09).
    min_length_ratio: float = 0.0
    #: 이보다 짧은 출력은 비율이 흔들려도 문제 삼지 않는다.
    length_check_min_chars: int = 40

    # ── 동시성 (§6.6) ─────────────────────────────────────────
    max_concurrent_per_request: int = 4
    max_concurrent_requests: int = 16

    # ── 프롬프트 (§7.9) ───────────────────────────────────────
    prompt_preset: Literal["full", "compact"] = "full"
    #: 요청에 style 이 없을 때 쓸 문체 (§7.3). 부대 내부 문서가 기본이다.
    default_style: str = "plain_report"

    # ── 관리 엔드포인트 (§6.7) ────────────────────────────────
    #: /admin/reload 허용 여부. 기본 비활성.
    #: 인증이 없으므로 O-07(인증 방식) 확정 전에는 다수 사용자 환경(D-07)에
    #: 열어 두면 안 된다.
    admin_enabled: bool = False

    # ── 로그 보존 (§5.4) ──────────────────────────────────────
    log_retention_days: int = 180
    #: 원문/번역문을 로그에 남길지. 공개 자료만 다루므로(D-03) 기본 True.
    log_text: bool = True

    @property
    def glossary_path(self) -> Path:
        return self.data_dir / "glossary.jsonl"

    @property
    def glossary_meta_path(self) -> Path:
        return self.data_dir / "glossary.meta.json"

    @property
    def tm_path(self) -> Path:
        return self.data_dir / "tm.jsonl"

    @property
    def runtime_db_path(self) -> Path:
        return self.data_dir / "runtime.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
