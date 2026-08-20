# tools/ — 오프라인 배치 도구

**개발망에서만 실행한다.** 폐쇄망에 반입하지 않는다 (계획서 §10.5).

용어집·TM 구축은 개발망에서 끝내고 결과물(JSONL)만 반입한다. 이 디렉터리의
스크립트는 `requirements-tools.txt` 에 의존하며, 그중 `sentence-transformers`
는 모델을 내려받는다 — `app/` 아래 런타임 코드에서는 절대 import 하지 말 것
(§9.3).

| 스크립트 | 단계 | 상태 |
|---|---|---|
| `glossary_import.py` | Phase 1 | 미구현 — **O-02 확정 필요** (확보 용어집 형태) |
| `glossary_lint.py` | Phase 1 | 미구현 — CI 등록 대상 |
| `corpus_align.py` | Phase 1 | 미구현 |
| `term_extract.py` | Phase 1 | 미구현 |
| `tm_build.py` | Phase 1 | 미구현 |
| `bundle_build.py` | Phase 5 | 미구현 — **O-05, O-06 확정 필요** |

## Phase 0 시점의 대체 수단

`glossary_lint.py` 가 담당할 검사 중 다음은 이미 `tests/test_glossary_schema.py`
가 CI 에서 강제하고 있다.

- 스키마 필수 필드 확인
- `source` / `confidence` 누락 탐지
- 표층형 중복 탐지
- `glossary.meta.json` 의 count 와 실제 용어 수 일치

Phase 1 에서 전용 도구로 옮기면서 **대역 충돌 탐지**(같은 `ko` 에 다른 `en`)를
추가한다. 지금은 용어가 20건뿐이라 충돌이 발생할 수 없다.
