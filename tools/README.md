# tools/ — 오프라인 배치 도구

**개발망에서만 실행한다.** 폐쇄망에 반입하지 않는다 (계획서 §10.5).

용어집·TM 구축은 개발망에서 끝내고 결과물(JSONL)만 반입한다. 이 디렉터리의
스크립트는 `requirements-tools.txt` 에 의존하며, 그중 `sentence-transformers`
는 모델을 내려받는다 — `app/` 아래 런타임 코드에서는 절대 import 하지 말 것
(§9.3).

| 스크립트 | 단계 | 상태 |
|---|---|---|
| `glossary_schema.py` | — | ✅ 엑셀 열 정의. 양식과 파서가 공유 |
| `glossary_template.py` | Phase 1 | ✅ 엑셀 양식 생성 |
| `glossary_import.py` | Phase 1 | ✅ 엑셀 → glossary.jsonl |
| `glossary_lint.py` | Phase 1 | 미구현 — 용어집 커밋 전 실행할 도구 |
| `corpus_align.py` | Phase 1 | 미구현 |
| `term_extract.py` | Phase 1 | 미구현 |
| `tm_build.py` | Phase 1 | 미구현 |
| `bundle_build.py` | Phase 5 | 미구현 — **O-05, O-06 확정 필요** |

## 용어집 만들기 (O-02: 엑셀 확정)

**양식을 먼저 받아 가서 채울 것.** 임의 배치로 채운 뒤에 맞추면 필수 필드
(출처·신뢰도)가 빠져 다시 채워야 한다.

```bash
# 1. 양식 생성 → data/glossary_template.xlsx
python -m tools.glossary_template

# 2. 엑셀에서 채운다 ('작성안내' 시트에 규칙이 있다)

# 3. 검사만 (파일을 쓰지 않는다)
python -m tools.glossary_import 채운파일.xlsx --dry-run

# 4. 통과하면 반영
python -m tools.glossary_import 채운파일.xlsx
#    → data/glossary.jsonl + data/glossary.meta.json (version 자동 증가)

# 5. 확인
pytest tests/test_glossary_schema.py
```

오류는 **시트와 행 번호**로 나온다.

```
오류 5건 — 고친 뒤 다시 실행할 것:
  [다의어] 5행 — '용어' 시트에 없는 표제어: '준장'. 표기를 확인할 것
  [용어] 4행 — 한국어와 영어는 둘 다 필요하다
  [용어] 5행 — source: String should have at least 1 character
  [용어] 6행 — confidence: Input should be 'verified', 'probable' or 'candidate'
  [용어] 7행 — 한국어 중복: '합동참모본부' (먼저 3행)
```

### 시트 구성

| 시트 | 내용 |
|---|---|
| `용어` | 한 행에 용어 하나. 대부분 여기만 채운다 |
| `다의어` | 조건에 따라 대역이 갈리는 것만 (`대령` → Colonel / Captain) |
| `작성안내` | 규칙 |

### 자동으로 채워지는 것

검수 인력이 병목이므로(O-01) 사람이 입력할 것을 줄였다.

| 항목 | 처리 |
|---|---|
| `id` | 비우면 `T-0001` 부터. 적어 넣은 것은 그대로 두고 겹치지 않게 번호를 준다 |
| `우선순위` | 표제어 길이로. `제7기동군단`이 `군단`을 이기게 (§6.3) |
| `corpus_freq` | 0. 실측값은 Phase 1 작업 5 에서 |
| 로마숫자 이형태 | `천무-Ⅱ` → `천무-2` 를 만들어 붙이고 보고한다 |

**띄어쓰기·대소문자·하이픈·복수형·전각반각 이형태는 적지 않아도 된다.**
매칭이 정규화로 흡수한다(§6.3). 적어야 하는 것은 `합참`처럼 형태가 다른 줄임말이다.

## Phase 0 시점의 대체 수단

`glossary_lint.py` 가 담당할 검사 중 다음은 이미 `tests/test_glossary_schema.py`
가 이미 덮고 있다 (`pytest tests/test_glossary_schema.py`).

- 스키마 필수 필드 확인
- `source` / `confidence` 누락 탐지
- 표층형 중복 탐지
- `glossary.meta.json` 의 count 와 실제 용어 수 일치

Phase 1 에서 전용 도구로 옮기면서 **대역 충돌 탐지**(같은 `ko` 에 다른 `en`)를
추가한다. 지금은 용어가 20건뿐이라 충돌이 발생할 수 없다.
