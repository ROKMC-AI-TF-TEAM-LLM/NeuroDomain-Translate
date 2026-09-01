"""오프라인 동작 검증 — 계획서 §9.5.

**개발망에서 네트워크를 차단한 상태로 전체 테스트를 통과해야 반입 승인이다.**

개발 중 무심코 쓴 자동 다운로드는 개발망에서 정상 동작하고 폐쇄망에서만 터진다.
발견이 늦으면 Phase 5 에서 대규모 수정이 된다 (R-02). 그래서 Phase 0 부터 CI 에
넣는다.

계획서 §9.5 의 예시는 `socket.socket` 자체를 막는데, 그대로 적용하면 테스트가
돌지 않는다 — asyncio 이벤트 루프가 자기 깨우기용으로 로컬 소켓을 쓰기 때문이다
(특히 Windows). 그래서 여기서는 **루프백 밖으로 나가는 연결과 외부 이름 해석**을
막는다. 에어갭에서 문제가 되는 것은 외부 접근이며(§9.3), 폐쇄망 안의 vLLM 호출은
허용되어야 하므로 의미도 이쪽이 맞다.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import socket
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


class ExternalNetworkAttempted(RuntimeError):
    """테스트 중 외부 네트워크 접근이 일어났다."""


def _check_address(address) -> None:
    host = address[0] if isinstance(address, tuple | list) and address else address
    if isinstance(host, bytes):
        host = host.decode("utf-8", "replace")
    if isinstance(host, str) and host.lower() in LOOPBACK_HOSTS:
        return
    raise ExternalNetworkAttempted(
        f"오프라인 테스트 중 외부 접근 시도: {address!r} (§9.3 금지 패턴 확인)"
    )


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """루프백 밖으로 나가는 모든 연결을 차단한다."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args, **kwargs):
        _check_address(address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        _check_address(address)
        return real_connect_ex(self, address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        _check_address((host,))
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        _check_address(address)
        raise ExternalNetworkAttempted(f"create_connection 시도: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


# ── 실제 동작 ─────────────────────────────────────────────────


def test_guard_actually_blocks() -> None:
    """가드 자체가 동작하는지 먼저 확인한다.

    이게 통과하지 않으면 아래 테스트들이 '차단된 상태에서 통과'한 것이 아니다.
    """
    with pytest.raises(ExternalNetworkAttempted):
        socket.create_connection(("huggingface.co", 443), timeout=1)
    with pytest.raises(ExternalNetworkAttempted):
        socket.getaddrinfo("pypi.org", 443)


def test_pipeline_runs_offline(client) -> None:
    """네트워크 차단 상태에서 /translate 가 끝까지 돈다."""
    res = client.post(
        "/translate",
        json={
            "text": "합참은 제7기동군단 예하 부대의 훈련을 참관했다고 밝혔다.",
            "source": "ko",
            "target": "en",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["translation"]


def test_health_offline(client) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["ready"] is True


def test_all_app_modules_import_offline() -> None:
    """app 하위 모듈 전부가 네트워크 없이 import 된다.

    import 시점에 모델을 내려받는 라이브러리가 섞이면 여기서 걸린다.
    """
    import app

    failures: list[str] = []
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            importlib.import_module(info.name)
        except ModuleNotFoundError:
            # 선택 의존성(kiwipiepy, pyahocorasick 등) 미설치는 정상이다.
            continue
        except Exception as e:  # noqa: BLE001 - 원인 종류와 무관하게 보고한다
            failures.append(f"{info.name}: {type(e).__name__}: {e}")
    assert not failures, "import 중 문제 발생:\n" + "\n".join(failures)


# ── 정적 검사: §9.3 금지 패턴 ─────────────────────────────────

#: 계획서 §9.3. 전부 런타임 네트워크 접근을 유발한다.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\.from_pretrained\s*\(", "HF Hub 다운로드. 로컬 절대경로를 쓸 것"),
    (r"\bsnapshot_download\s*\(", "HF Hub 다운로드. 번들에 사전 포함할 것"),
    (r"\bSentenceTransformer\s*\(", "HF Hub 다운로드. 로컬 경로를 쓸 것"),
    (r"\bnltk\.download\s*\(", "런타임 다운로드. 사용 금지"),
    (r"\btiktoken\.get_encoding\s*\(", "BPE 파일 다운로드. 사용 금지"),
    (r"\bspacy\.load\s*\(", "모델 다운로드 가능. 사용 금지"),
    (r"\brequests\.(get|post|put|delete)\s*\(", "외부 접근. 사용 금지"),
    (r"\burllib\.request\.urlopen\s*\(", "외부 접근. 사용 금지"),
    (r"\bpip\s+install\b", "런타임 패키지 다운로드. 번들 wheel 만 쓸 것"),
]

#: 런타임 코드만 본다. tools/ 는 개발망 전용이라 제외한다 (§10.5).
SCANNED_ROOTS = [PROJECT_ROOT / "app"]


def _strip_comments_and_docstrings(source: str) -> str:
    """주석과 문자열 리터럴을 지운다.

    설명문에 금지 패턴이 적혀 있는 것은 위반이 아니다. 실제 호출만 본다.
    """
    import io
    import tokenize

    out: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):  # pragma: no cover
        return source
    return " ".join(out)


@pytest.mark.parametrize("pattern,reason", FORBIDDEN_PATTERNS)
def test_no_forbidden_network_patterns(pattern: str, reason: str) -> None:
    """§9.3 금지 패턴이 런타임 코드에 없어야 한다.

    새 의존성이 몰래 네트워크를 쓰면 런타임에야 드러나지만, 우리가 직접 쓴
    호출은 여기서 걷어낼 수 있다.
    """
    regex = re.compile(pattern)
    hits: list[str] = []
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
            if regex.search(code):
                hits.append(str(path.relative_to(PROJECT_ROOT)))
    assert not hits, f"금지 패턴 `{pattern}` 발견 ({reason}): {hits}"


def test_no_cdn_links_in_prompts() -> None:
    """프롬프트 · 스타일 파일에 외부 URL 이 없어야 한다 (§9.3 폰트/CDN 링크)."""
    url = re.compile(r"https?://(?!127\.0\.0\.1|localhost)", re.IGNORECASE)
    hits: list[str] = []
    prompts = PROJECT_ROOT / "prompts"
    for path in sorted(prompts.rglob("*")):
        if path.is_file() and url.search(path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(PROJECT_ROOT)))
    assert not hits, f"프롬프트에 외부 URL 이 있다: {hits}"


def test_offline_env_vars_documented() -> None:
    """§9.4 환경변수가 문서에 남아 있는지 확인한다.

    폐쇄망 서버와 개발망 테스트 양쪽에서 설정해야 하는 값들이다.
    """
    required = [
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "HF_DATASETS_OFFLINE",
    ]
    text = Path(PROJECT_ROOT / "docs" / "military-translator-plan.md").read_text(encoding="utf-8")
    missing = [name for name in required if name not in text]
    assert not missing, f"§9.4 환경변수가 계획서에서 사라졌다: {missing}"
