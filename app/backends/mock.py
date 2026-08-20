"""테스트용 백엔드 (GPU 불필요) — 계획서 §4.2, Phase 0.

네트워크도 GPU도 쓰지 않는다. 파이프라인이 끝까지 도는지 확인하는 것이
유일한 목적이며, **번역 품질을 평가하는 데 쓰면 안 된다** (§3.1).

주입된 용어를 실제로 치환하므로 검증 단계(§6.5)까지 배선을 확인할 수 있다.
`miss_terms` 를 켜면 일부러 용어를 빠뜨려 재호출 경로를 시험할 수 있다.
"""

from __future__ import annotations

import time

from app.backends.base import TranslationRequest, TranslationResult


class MockBackend:
    name = "mock"

    def __init__(self, *, miss_terms: bool = False, latency_ms: int = 0) -> None:
        #: True 면 용어를 치환하지 않는다. 검증 실패 → 재호출 경로 테스트용.
        self.miss_terms = miss_terms
        self.latency_ms = latency_ms
        #: 테스트가 프롬프트 조립 결과를 들여다볼 수 있게 마지막 요청을 남긴다.
        self.last_request: TranslationRequest | None = None
        self.call_count = 0

    async def translate(self, req: TranslationRequest) -> TranslationResult:
        started = time.perf_counter()
        self.last_request = req
        self.call_count += 1

        out = req.text
        if not self.miss_terms:
            # 원문에 실제로 나타난 표층형을 치환한다. `source` 는 프롬프트용
            # 표기("합동참모본부 / 합참")라 본문과 일치하지 않는다.
            replacements: list[tuple[str, str]] = []
            for hint in req.terms:
                if hint.is_reference or not hint.targets:
                    continue
                for surface in hint.surfaces or [hint.source]:
                    replacements.append((surface, hint.targets[0]))
            # 긴 표층형부터 치환해야 짧은 것이 먼저 먹지 않는다.
            for surface, target in sorted(replacements, key=lambda p: len(p[0]), reverse=True):
                out = out.replace(surface, target)

        raw = f"[mock:{req.direction}] {out}"
        elapsed = int((time.perf_counter() - started) * 1000) + self.latency_ms
        return TranslationResult(text=raw, raw=raw, elapsed_ms=elapsed)

    async def analyze(self, text: str, prompt: str) -> str:
        """보조 작업. mock 은 판정하지 않고 빈 문자열을 돌려준다.

        오케스트레이터가 규칙 기반으로 폴백한다 (§4.3).
        """
        return ""

    async def health(self) -> bool:
        return True
