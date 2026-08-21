"""문체 프리셋 — 계획서 §7.3.

문체는 **한국어 쪽 구분**이라 방향별로 효과가 다르다. 영어에는 높임법이 없어
`ko2en` 에서는 높임말과 평시문의 출력이 사실상 같다. 그 비대칭을 규칙에
정직하게 반영했는지 여기서 지킨다.
"""

from __future__ import annotations

import re

import pytest
import yaml

from app.backends.mock import MockBackend
from app.config import PROJECT_ROOT
from app.glossary.index import IndexRegistry
from app.glossary.matcher import automaton_available
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.prompt import PromptBuilder

STYLES_DIR = PROJECT_ROOT / "prompts" / "styles"
EXPECTED = {"press_release", "plain_report", "honorific", "default"}


@pytest.fixture(scope="module")
def builder() -> PromptBuilder:
    return PromptBuilder(PROJECT_ROOT / "prompts")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((STYLES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


# ── 구성 ──────────────────────────────────────────────────────


def test_all_styles_are_discovered(builder: PromptBuilder) -> None:
    assert set(builder.available_styles()) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_style_covers_both_directions(name: str) -> None:
    """한 방향만 있으면 그 방향에서 조용히 문체가 빠진다."""
    data = load_yaml(name)
    for direction in ("ko2en", "en2ko"):
        assert data.get(direction), f"{name}: {direction} 블록이 없다"
        assert data[direction].get("register")
        assert data[direction].get("rules")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_style_has_a_display_name(name: str) -> None:
    """프론트 선택기가 이 이름을 보여준다."""
    assert load_yaml(name).get("name")


def test_style_names_are_exposed(builder: PromptBuilder) -> None:
    names = builder.style_names()
    assert names["plain_report"] == "평시문"
    assert names["honorific"] == "높임말"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_display_name_is_not_the_key(name: str) -> None:
    """표시 이름이 영문 키 그대로면 선택기에 'press_release' 가 뜬다."""
    assert load_yaml(name)["name"] != name


# ── 환각 방지 (docs/phase2-notes.md §9) ───────────────────────

#: 구체적인 연·월·일. 원문에 내용이 없으면 모델이 이런 값을 그대로 베껴 쓴다.
_CONCRETE_DATE = re.compile(r"(19|20)\d{2}\s*년|\b(19|20)\d{2}\b")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_style_rules_have_no_concrete_dates(name: str) -> None:
    """**실제 사고에서 나온 검사다.**

    press_release.yaml 의 '2026년 8월 19일' 이 지어낸 문서의 첫 줄로 나왔다.
    문체 규칙은 형식만 보여줘야 하고, 값은 자리표시자여야 한다.
    """
    text = (STYLES_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    hits = _CONCRETE_DATE.findall(body)
    assert not hits, f"{name}: 규칙에 구체적인 연도가 있다 — 모델이 베껴 쓴다"


# ── 평시문 ────────────────────────────────────────────────────


def test_plain_report_forbids_honorifics() -> None:
    """평시문에 '~습니다' 가 섞이면 문체가 무너진다."""
    rules = " ".join(load_yaml("plain_report")["en2ko"]["rules"])
    assert "습니다" in rules  # 금지 규칙으로 언급되어야 한다
    assert "높임말을 쓰지 않는다" in rules


def test_plain_report_covers_nominal_endings() -> None:
    """사용자가 요청한 '했다 / 했음 / 하였음' 세 형태가 다뤄져야 한다."""
    en2ko = load_yaml("plain_report")["en2ko"]
    text = en2ko["register"] + " " + " ".join(en2ko["rules"])
    assert "했다" in text
    assert "하였음" in text


def test_plain_report_demands_consistency() -> None:
    """한 문서에서 '~했다' 와 '~함' 을 섞으면 읽기 나쁘다."""
    rules = " ".join(load_yaml("plain_report")["en2ko"]["rules"])
    assert "섞지 않는다" in rules


def test_plain_report_ko2en_explains_nominal_source() -> None:
    """원문이 개조식이면 조사가 빠진다. 모델이 그걸 알아야 완전한 문장을 만든다."""
    rules = " ".join(load_yaml("plain_report")["ko2en"]["rules"])
    assert "nominal endings" in rules
    assert "complete English sentence" in rules


# ── 높임말 ────────────────────────────────────────────────────


def test_honorific_unifies_endings() -> None:
    rules = " ".join(load_yaml("honorific")["en2ko"]["rules"])
    assert "습니다" in rules
    assert "섞지 않는다" in rules


def test_honorific_guards_against_object_honorifics() -> None:
    """'결과가 나오셨습니다' 는 한국어에서 흔한 오류다. 사물에는 존대를 안 붙인다."""
    rules = " ".join(load_yaml("honorific")["en2ko"]["rules"])
    assert "사물" in rules


def test_honorific_ko2en_does_not_invent_deference() -> None:
    """**영어에는 높임법이 없다.**

    '보고드립니다' 를 'humbly reports' 로 옮기는 것이 이 방향의 실제 오역이다.
    ko2en 규칙은 존대를 만들어내지 말라는 쪽이어야 한다.
    """
    ko2en = load_yaml("honorific")["ko2en"]
    text = ko2en["register"] + " " + " ".join(ko2en["rules"])
    assert "no honorific system" in text
    assert "humbly" in text  # 금지 예시로 언급되어야 한다


# ── 프롬프트 조립 ─────────────────────────────────────────────


@pytest.mark.parametrize("style", sorted(EXPECTED))
@pytest.mark.parametrize("direction", ["ko2en", "en2ko"])
def test_style_block_renders(builder: PromptBuilder, style: str, direction: str) -> None:
    from app.pipeline.prompt import ChunkContext

    prompt = builder.build_system(
        direction=direction,
        style=style,
        preset="full",
        terms=[],
        tm_examples=[],
        context=ChunkContext(),
    )
    assert "[Style —" in prompt


def test_prompt_version_differs_by_style(builder: PromptBuilder) -> None:
    """문체마다 버전이 갈려야 평가 결과를 문체별로 비교할 수 있다 (§7.10)."""
    ids = {builder.version("en2ko", s).id for s in EXPECTED}
    assert len(ids) == len(EXPECTED)
    assert builder.version("en2ko", "honorific").id == "en2ko-honor-v1"
    assert builder.version("en2ko", "plain_report").id == "en2ko-plain-v1"


# ── 없는 문체 (조용한 폴백 방지) ──────────────────────────────


def test_unknown_style_is_reported(builder: PromptBuilder) -> None:
    assert builder.has_style("honorific")
    assert not builder.has_style("존댓말")


@pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")
@pytest.mark.asyncio
async def test_unknown_style_warns_instead_of_silently_falling_back(settings) -> None:
    """사용자가 높임말을 골랐는데 범용체가 나오면 알 방법이 있어야 한다."""
    registry = IndexRegistry(settings)
    await registry.ensure_loaded()
    orch = Orchestrator(settings, registry, MockBackend(), PromptBuilder(settings.prompts_dir))
    outcome = await orch.run("합참은 밝혔다.", "ko2en", "존댓말")

    unknown = [w for w in outcome.warnings if w["type"] == "unknown_style"]
    assert unknown
    assert unknown[0]["requested"] == "존댓말"
    assert "honorific" in unknown[0]["available"]


@pytest.mark.skipif(not automaton_available(), reason="pyahocorasick 미설치")
@pytest.mark.asyncio
async def test_known_style_produces_no_warning(settings) -> None:
    registry = IndexRegistry(settings)
    await registry.ensure_loaded()
    orch = Orchestrator(settings, registry, MockBackend(), PromptBuilder(settings.prompts_dir))
    outcome = await orch.run("합참은 밝혔다.", "ko2en", "honorific")
    assert [w for w in outcome.warnings if w["type"] == "unknown_style"] == []


def test_health_lists_styles(client) -> None:
    """프론트가 문체 선택기를 만들 때 키를 추측하지 않아도 된다."""
    styles = client.get("/health").json()["styles"]
    assert set(styles) == EXPECTED
    assert styles["plain_report"] == "평시문"
    assert styles["press_release"] == "보도자료"
