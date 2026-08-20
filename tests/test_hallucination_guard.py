"""환각 · 누락 탐지 — 계획서 §6.5.

실제 사고에서 나온 테스트다. 영→한에 `"string"` 한 단어를 넣었더니 모델이
2027년 국방 예산안 보도자료를 통째로 지어냈다 — 금액(50조 원), 계급(김철수
중장), 발언까지. 응답의 `warnings` 는 비어 있었다.

원문에 내용이 없으면 모델이 시스템 프롬프트의 **문체 예시를 내용으로 가져다
쓴다.** 실제 출력이 `2026년 8월 19일` 로 시작했는데, 그것은 스타일 프리셋
(§7.3)에 적어 둔 날짜 예시였다.

형식이 완벽해서 검수자가 놓치기 쉽다. 다수가 쓰는 환경(D-07)에서 지어낸
국방 문서가 그럴듯하게 나오는 것은 오역보다 위험하다.
"""

from __future__ import annotations

import pytest

from app.pipeline.verify import (
    DEFAULT_MAX_EXPANSION,
    check_language,
    check_length,
)

#: 사고 당시 실제 출력 (일부).
FABRICATED = (
    "2026년 8월 19일, 국방부는 2027년 국방 예산안에 대한 계획을 발표했다. "
    "이번 예산안은 총 50조 원 규모로, 전년 대비 5% 증가했다. 특히, 첨단 "
    "무기체계 도입과 국방 연구개발에 중점을 두었다."
)

#: 사고 이후 관측된 두 번째 실패 형태 — 번역 대신 메타 코멘트.
META_COMMENT = "(Translation provided in Korean, adhering to the style guidelines)"


# ── 길이 이상 ─────────────────────────────────────────────────


def test_fabricated_document_is_flagged() -> None:
    """`string` (6자) → 지어낸 문서. 이것을 놓치면 안 된다."""
    anomaly = check_length("string", FABRICATED, "en2ko")
    assert anomaly is not None
    assert anomaly.kind == "expansion"
    assert anomaly.ratio > 10


def test_flagged_anomaly_reports_numbers() -> None:
    """사용자가 판단하려면 얼마나 부풀었는지 보여야 한다 (§4.4)."""
    warning = check_length("string", FABRICATED, "en2ko").to_warning(chunk=0)
    assert warning["type"] == "length_anomaly"
    assert warning["kind"] == "expansion"
    assert warning["src_chars"] == 6
    assert warning["ratio"] > 10


@pytest.mark.parametrize(
    "direction,src,tgt",
    [
        # 정상 en2ko: 한국어가 더 짧다
        (
            "en2ko",
            "The JCS said the Republic of Korea Navy will conduct a combined exercise "
            "for four days from Aug. 20.",
            "합동참모본부는 대한민국 해군이 8월 20일부터 4일간 연합훈련을 실시한다고 밝혔다.",
        ),
        # 정상 ko2en: 영어가 더 길다 (실측 2.8배)
        (
            "ko2en",
            "합참은 20일 연합훈련을 실시했다고 밝혔다.",
            "The JCS announced that it conducted a combined exercise on the 20th.",
        ),
        # 짧은 표기는 비율이 흔들려도 정상
        ("en2ko", "JCS", "합동참모본부"),
        ("en2ko", "K2", "K2 흑표"),
        ("ko2en", "합참", "Joint Chiefs of Staff (JCS)"),
    ],
)
def test_normal_translations_are_not_flagged(direction: str, src: str, tgt: str) -> None:
    """**오탐이 더 나쁘다.** 정상 번역에 경고가 붙으면 사용자가 경고를 무시한다."""
    assert check_length(src, tgt, direction) is None


def test_truncation_is_flagged() -> None:
    """문장을 빠뜨려도 비율로 드러난다 (R-09)."""
    src = "합참은 20일 연합훈련을 실시했다고 밝혔다. " * 6
    anomaly = check_length(src, "The JCS said.", "ko2en")
    assert anomaly is not None
    assert anomaly.kind == "truncation"


def test_empty_output_is_left_to_the_empty_chunk_check() -> None:
    assert check_length("합참은 밝혔다.", "", "ko2en") is None


def test_thresholds_are_direction_aware() -> None:
    """한국어는 영어보다 글자 수가 적다. 같은 임계값을 쓰면 한쪽이 늘 틀린다."""
    assert DEFAULT_MAX_EXPANSION["ko2en"] > DEFAULT_MAX_EXPANSION["en2ko"]


# ── 언어 이상 ─────────────────────────────────────────────────


def test_meta_comment_is_flagged() -> None:
    """한국어로 번역하라고 했는데 한글이 한 글자도 없으면 번역이 아니다."""
    assert check_language(META_COMMENT, "en2ko") is True
    # 이 길이(66자)면 길이 검사도 함께 잡는다. 신호가 둘이면 그만큼 낫다.
    assert check_length("string", META_COMMENT, "en2ko") is not None


def test_short_meta_comment_needs_the_language_check() -> None:
    """짧은 메타 코멘트는 길이 검사를 빠져나간다.

    두 검사를 함께 두는 이유다 — 길이는 부풀기를, 스크립트는 언어를 본다.
    """
    short = "(Translated to Korean)"
    assert check_length("string", short, "en2ko") is None  # 22자, 하한 40 미만
    assert check_language(short, "en2ko") is True


def test_korean_output_passes_language_check() -> None:
    assert check_language("합동참모본부는 연합훈련을 실시했다고 밝혔다.", "en2ko") is False


def test_english_output_passes_language_check() -> None:
    assert check_language("The JCS said it conducted a combined exercise.", "ko2en") is False


def test_korean_output_in_ko2en_is_flagged() -> None:
    """한→영인데 한글만 나왔다면 번역이 아니라 반향이다."""
    assert check_language("합참은 연합훈련을 실시했다고 밝혔다. 훈련이 끝났다.", "ko2en") is True


def test_short_output_skips_language_check() -> None:
    """`K2` 처럼 번역해도 그대로인 짧은 표기가 있다."""
    assert check_language("K2", "en2ko") is False
    assert check_language("DAPA", "en2ko") is False


def test_mixed_output_passes() -> None:
    """한국어 번역에 영문 약어가 섞이는 것은 정상이다."""
    assert check_language("합참은 K2 흑표 전차를 배치했다고 밝혔다.", "en2ko") is False


# ── 파이프라인 결합 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_warnings_surface_through_the_api(client) -> None:
    """탐지해도 응답에 실리지 않으면 소용없다 (§4.4)."""
    # mock 은 입력을 그대로 돌려준다. 용어집에 걸리는 말이 없는 문장을 쓰면
    # 치환이 일어나지 않아 en2ko 출력에 한글이 하나도 없다 → wrong_language.
    res = client.post(
        "/translate",
        json={
            "text": "The unit completed its scheduled maintenance work today without incident.",
            "source": "en",
            "target": "ko",
        },
    )
    assert res.status_code == 200
    types = {w["type"] for w in res.json()["warnings"]}
    assert "wrong_language" in types
