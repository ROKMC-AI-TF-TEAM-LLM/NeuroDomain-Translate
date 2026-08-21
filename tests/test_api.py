"""API 계약 — 계획서 §4.4.

프론트가 이 형태에 맞춰져 있다 (D-12). 필드를 빼거나 이름을 바꾸지 말 것.
"""

from __future__ import annotations

import pytest

SAMPLE_KO = "합참은 제7기동군단 예하 부대의 훈련을 참관했다고 밝혔다."


def test_translate_returns_contract_shape(client) -> None:
    res = client.post(
        "/translate",
        json={"text": SAMPLE_KO, "source": "ko", "target": "en"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"translation", "terms_applied", "warnings", "meta"}
    assert set(body["meta"]) >= {
        "chunks",
        "retries",
        "elapsed_ms",
        "backend",
        "prompt_version",
    }


def test_matched_terms_are_applied(client) -> None:
    """Phase 2 부터 mock 백엔드가 주입된 용어를 실제로 치환한다.

    `합참` 은 T-0142 의 별칭이다. 표제어(`합동참모본부`)만 힌트로 넘기면
    본문의 `합참` 과 이어지지 않아 대역어가 반영되지 않는다 (§7.5).
    """
    res = client.post("/translate", json={"text": SAMPLE_KO, "source": "ko", "target": "en"})
    body = res.json()
    assert "Joint Chiefs of Staff" in body["translation"]
    assert {t["term_id"] for t in body["terms_applied"]} >= {"T-0142", "T-0301"}
    # 용어가 반영됐으므로 위반도 재호출도 없어야 한다 (§6.5).
    assert [w for w in body["warnings"] if w["type"] == "term_missing"] == []
    assert body["meta"]["retries"] == 0


def test_prompt_version_is_recorded(client) -> None:
    """프롬프트 버전 기록이 없으면 수정이 개선인지 퇴보인지 알 수 없다 (§7.10)."""
    res = client.post("/translate", json={"text": SAMPLE_KO, "source": "ko", "target": "en"})
    assert res.json()["meta"]["prompt_version"] == "ko2en-plain-v1"


def test_style_defaults_to_settings(client, settings) -> None:
    """스키마에 기본값을 박으면 `NDT_DEFAULT_STYLE` 이 영영 적용되지 않는다.

    요청마다 값이 채워져 `req.style or settings.default_style` 의 오른쪽이 죽는다.
    """
    assert settings.default_style == "plain_report"
    res = client.post("/translate", json={"text": SAMPLE_KO, "source": "ko", "target": "en"})
    assert res.json()["meta"]["prompt_version"] == "ko2en-plain-v1"


def test_explicit_style_overrides_the_default(client) -> None:
    res = client.post(
        "/translate",
        json={"text": SAMPLE_KO, "source": "ko", "target": "en", "style": "press_release"},
    )
    assert res.json()["meta"]["prompt_version"] == "ko2en-press-v1"


def test_en2ko_direction(client) -> None:
    res = client.post(
        "/translate",
        json={"text": "The JCS said it observed the drill.", "source": "en", "target": "ko"},
    )
    assert res.status_code == 200
    assert res.json()["meta"]["prompt_version"] == "en2ko-plain-v1"


# ── 같은 언어 요청 ────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_same_language_returns_the_input_unchanged(client, lang: str) -> None:
    """방향을 잘못 골랐다고 화면이 깨지면 무엇이 잘못됐는지 알기 어렵다.

    넣은 글을 그대로 보여주면서 경고를 붙이면 실수를 바로 알아채고 고칠 수 있다.
    """
    text = "합참은 밝혔다." if lang == "ko" else "The JCS said."
    res = client.post("/translate", json={"text": text, "source": lang, "target": lang})

    assert res.status_code == 200
    body = res.json()
    assert body["translation"] == text
    assert body["terms_applied"] == []

    same = [w for w in body["warnings"] if w["type"] == "same_language"]
    assert same
    assert same[0]["source"] == lang
    assert same[0]["target"] == lang
    assert same[0]["detail"]


def test_same_language_does_not_call_the_model(client) -> None:
    """번역이 아니므로 모델을 부르지 않는다. 청크도 0 이다."""
    res = client.post("/translate", json={"text": "합참은 밝혔다.", "source": "ko", "target": "ko"})
    meta = res.json()["meta"]
    assert meta["chunks"] == 0
    assert meta["retries"] == 0
    assert meta["prompt_version"] == "passthrough"


def test_same_language_preserves_formatting(client) -> None:
    """정규화도 거치지 않는다. 넣은 그대로여야 한다."""
    text = "  합참은 밝혔다.\n\n  국방부는 침묵했다.  "
    res = client.post("/translate", json={"text": text, "source": "ko", "target": "ko"})
    assert res.json()["translation"] == text


def test_unsupported_language_is_rejected(client) -> None:
    res = client.post("/translate", json={"text": "テスト", "source": "ja", "target": "en"})
    assert res.status_code == 422  # pydantic Literal 검증


def test_over_length_input_is_rejected(client) -> None:
    """최대 5,000자 (D-05)."""
    res = client.post(
        "/translate",
        json={"text": "가" * 5001, "source": "ko", "target": "en"},
    )
    assert res.status_code == 413


def test_max_length_input_is_accepted(client) -> None:
    text = "가나다라. " * 800  # 4,800자
    assert len(text) <= 5000
    res = client.post("/translate", json={"text": text, "source": "ko", "target": "en"})
    assert res.status_code == 200


def test_unknown_field_is_rejected(client) -> None:
    res = client.post(
        "/translate",
        json={"text": "테스트", "source": "ko", "target": "en", "temperature": 0.7},
    )
    assert res.status_code == 422


def test_empty_text_returns_empty_translation(client) -> None:
    res = client.post("/translate", json={"text": "   ", "source": "ko", "target": "en"})
    assert res.status_code == 200
    assert res.json()["translation"] == ""


def test_multi_paragraph_input_is_chunked_and_rejoined(client) -> None:
    text = "첫 문단이다.\n\n둘째 문단이다."
    res = client.post("/translate", json={"text": text, "source": "ko", "target": "en"})
    body = res.json()
    assert body["meta"]["chunks"] == 2
    assert "\n\n" in body["translation"]


# ── 헬스체크 (§6.7) ───────────────────────────────────────────


def test_health_reports_glossary_version(client) -> None:
    body = client.get("/health").json()
    assert body["ready"] is True
    assert body["glossary_version"] == 1
    assert body["term_count"] == 20
    assert body["backend"] == "mock"


def test_health_reports_active_components(client) -> None:
    """지금 무엇으로 돌고 있는지 알 수 있어야 한다.

    NLP 의존성이 빠지면 조용히 성능이 떨어지므로(분할기 · 매칭기 폴백),
    운영 중에 확인할 방법이 필요하다.
    """
    body = client.get("/health").json()
    assert body["segmenter"] in {"kiwi", "rule"}
    assert body["matcher"] in {"aho-corasick", "none"}
    assert body["tm_size"] > 0


# ── 관리 엔드포인트 (§6.7) ────────────────────────────────────


def test_admin_reload_disabled_by_default(client) -> None:
    """O-07(인증 방식) 확정 전에는 열려 있으면 안 된다."""
    assert client.post("/admin/reload").status_code == 404


def test_admin_reload_rebuilds_index(admin_client) -> None:
    res = admin_client.post("/admin/reload")
    assert res.status_code == 200
    assert res.json()["term_count"] == 20


def test_admin_reload_keeps_old_index_on_bad_glossary(admin_client, data_dir) -> None:
    """잘못된 용어집으로 교체되는 것이 서비스 중단보다 나쁘다 (§6.7)."""
    (data_dir / "glossary.jsonl").write_text("{ broken\n", encoding="utf-8")

    res = admin_client.post("/admin/reload")
    assert res.status_code == 422
    assert "glossary.jsonl:1" in res.json()["detail"]

    # 기존 인덱스로 계속 서비스해야 한다.
    still = admin_client.post(
        "/translate", json={"text": "합참은 밝혔다.", "source": "ko", "target": "en"}
    )
    assert still.status_code == 200
