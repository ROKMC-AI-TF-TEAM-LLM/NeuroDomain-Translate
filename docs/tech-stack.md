# 기술 스택 및 아키텍처 상세 문서

| 항목 | 내용 |
|---|---|
| 작성 | 2026-08-20 |
| 대상 | 저장소 전체 (`app/`, `prompts/`, `tools/`, `tests/`, `data/`, 설정 파일) |
| 성격 | 실제 코드를 전수 조사해 작성한 기술 스택 레퍼런스. 계획서([military-translator-plan.md](military-translator-plan.md))와 실행기록([phase0-notes.md](phase0-notes.md), [phase2-notes.md](phase2-notes.md))을 대체하지 않음 |

이 문서는 "무엇을 왜 쓰는가"를 코드 기준으로 정리한다. 결정의 배경(왜 kss 대신
Kiwi인지 등)은 `docs/phase0-notes.md`·`docs/phase2-notes.md`에 이미 있으므로
여기서는 요약만 하고 원문서를 가리킨다.

---

## 1. 한눈에 보는 스택

```
언어        Python 3.11 (Windows/Linux 겸용, 반입 번들과 버전 고정)
웹 프레임워크  FastAPI 0.115.6 + Uvicorn 0.34.0 (ASGI, ASGI ⇒ ASGI 앱 하나: app/main.py)
검증/설정    Pydantic 2.10.4 + pydantic-settings 2.7.0
템플릿       Jinja2 3.1.5 (프롬프트 조립) + PyYAML 6.0.3 (문체 프리셋)
HTTP 클라이언트 httpx 0.28.1 (모델 서버 호출, 비동기)
직렬화       orjson 3.10.13
로깅         structlog 24.4.0 (선언은 되어 있으나 표준 logging과 병행 사용)
재시도       tenacity 9.0.0 (의존성만 고정, 현재 직접 호출부는 없음)
한국어 형태소  kiwipiepy 0.22.2 + kiwipiepy-model 0.22.1 (LGPL v3)
용어 매칭    pyahocorasick 2.1.0 (Aho-Corasick 오토마톤)
TM 검색      rank-bm25 0.2.2 (BM25Okapi)
문자열 유틸  regex 2024.11.6, rapidfuzz 3.11.0(반입만, 현재 미사용 코드)
저장소       SQLite (표준 라이브러리 sqlite3, WAL 모드) — DB 서버 없음
데이터 포맷  JSONL (용어집·TM) — DB 아님, git으로 버전 관리
모델 서빙(운영) torch 2.8.0 / transformers 4.57.1 / vllm 0.11.0 (Phase 3, 아직 미설치)
모델 서빙(개발) llama.cpp (외부 프로세스, 파이썬 의존성 아님)
테스트       pytest 8.3.4 + pytest-asyncio 0.25.0 + pytest-cov 6.0.0
린트/포맷    ruff 0.8.6 (lint + format 겸용) + mypy 1.14.1
CI          없음 (2026-08-23 제거). 검사는 로컬에서 사람이 실행
오프라인 도구  pandas, openpyxl, sentence-transformers, sacrebleu, unbabel-comet (개발망 전용, 미구현)
```

---

## 2. 의존성 파일 구조와 정책

의존성은 `pyproject.toml`이 아니라 **5개의 `requirements-*.txt`가 정본**이다
(계획서 §10). `pyproject.toml`에는 의존성을 중복 기재하지 않는다 — 반입 번들이
`requirements.lock.txt`와 1:1 대응해야 하기 때문이다.

| 파일 | 용도 | 폐쇄망 반입 | GPU 필요 |
|---|---|---|---|
| [requirements-core.txt](../requirements-core.txt) | 서버 골격 (FastAPI 등) | ✅ | ✗ |
| [requirements-nlp.txt](../requirements-nlp.txt) | 형태소·매칭·TM 검색 | ✅ | ✗ |
| [requirements-serve.txt](../requirements-serve.txt) | 모델 서빙 (torch/vLLM) | ✅ (Phase 3부터) | ✅ |
| [requirements-dev.txt](../requirements-dev.txt) | 테스트·린트 | ✗ | ✗ |
| [requirements-tools.txt](../requirements-tools.txt) | 용어집/TM 구축 배치 도구 | ✗ | ✗ |
| [requirements.lock.txt](../requirements.lock.txt) | `pip download`로 해석된 실제 버전 (§10.6 산출물) | — | — |

**버전 정책(D-20)**: `mars-ai-server`(같은 폐쇄망 서버를 공유할 가능성이 있는
별도 프로젝트)와 겹치는 라이브러리는 그쪽 버전을 정본으로 삼는다. 그 결과
계획서 초안(v0.2 §10) 값에서 다음이 바뀌었다.

| 라이브러리 | 계획서 초안 | 실제 적용 |
|---|---|---|
| kiwipiepy | 0.20.4 | **0.22.2** |
| kiwipiepy-model | 0.20.0 | **0.22.1** |
| torch | 2.5.1 | **2.8.0** |
| transformers | 4.48.0 | **4.57.1** |
| vllm | 0.7.2 | **0.11.0** |

**중요 원칙**: LLM 에이전트를 포함해 누구도 §10에 없는 라이브러리를 임의로
추가하거나 버전을 올리면 안 된다(README §"지켜야 할 것" 1~2). 새 의존성은
사람 승인 후 `requirements-*.txt`에 근거 주석과 함께 추가한다 — 실제로
`pyyaml`이 이 절차(D-23, 2026-08-19 승인)로 추가됐다.

---

## 3. 언어 / 런타임

- **Python 3.11** 고정. `pyproject.toml`의 `requires-python = ">=3.11"`.
  반입 번들과 버전이 어긋나면 wheel이 안 맞을 수 있어 엄격히 고정한다.
- **Windows / Linux** 겸용 개발. 단, **번들(wheel) 생성은 반드시 폐쇄망과
  같은 OS(Linux)에서** 해야 한다 — Windows에서 만들면 `uvloop`처럼
  `sys_platform` 환경 마커가 붙은 조건부 의존성이 조용히 누락된다
  (`docs/phase0-notes.md` §3 실측).
- `PYTHONDONTWRITEBYTECODE=1` 등 에어갭 관련 환경변수를 운영에서 강제한다(§9.4).

---

## 4. 웹 프레임워크 계층

### FastAPI + Uvicorn — [app/main.py](../app/main.py)

- ASGI 앱 진입점은 `app.main:app`. 계획서 §4.2에는 이 파일이 명시돼 있지
  않아 Phase 0에서 추가했다(`docs/phase0-notes.md` §6).
- `lifespan` 컨텍스트 매니저가 앱 시작 시 `RuntimeStore`(SQLite),
  `IndexRegistry`(용어집/Kiwi/TM 인덱스), 백엔드, `PromptBuilder`,
  `Orchestrator`를 만들어 `app.state`에 걸어둔다.
- 인덱스 빌드(10~20초)는 **기다리지 않는다** — `asyncio.create_task`로
  백그라운드에서 돌리고, 그동안 `/health`가 `ready=false`, `/translate`가
  503을 반환한다.
- `uvicorn[standard]`를 써서 `uvloop`/`httptools`를 함께 쓴다(단, Windows
  빌드 번들에서는 위 이유로 빠질 수 있음에 주의).
- CORS는 `CORSMiddleware`로 처리, `NDT_CORS_ORIGINS` 환경변수로 프론트
  오리진을 지정한다(D-12: 프론트는 별도 저장소의 완성된 자산).
- 다중 워커(`uvicorn --workers N`) 사용은 보류 상태다 — SQLite 커넥션과
  인덱스 사본이 워커마다 생기는 문제(R-12) 때문에 O-04(동시 접속자 수)
  확정 전까지 워커 1개 + 비동기 동시성만 쓴다.

### Pydantic 2 / pydantic-settings — [app/config.py](../app/config.py), [app/api/schemas.py](../app/api/schemas.py)

- `Settings(BaseSettings)`가 `NDT_` 프리픽스 환경변수 → `.env` 파일 →
  기본값 순으로 약 25개 설정 항목을 로딩한다.
- 요청/응답 스키마(`TranslateRequest`, `TranslateResponse`,
  `HealthResponse`, `ReloadResponse`)는 전부 `pydantic.BaseModel`.
  `TranslateRequest`는 `extra="forbid"`로 알 수 없는 필드를 422로 거절한다
  (`test_unknown_field_is_rejected`).
- 용어집 스키마(`app/glossary/loader.py`의 `Term`)도 pydantic 모델이며
  `extra="forbid"` + `frozen=True`로 필드명 오타를 로딩 시점에 잡는다.

### Jinja2 + PyYAML — [app/pipeline/prompt.py](../app/pipeline/prompt.py)

- 시스템/재호출 프롬프트는 `.j2` 템플릿(`prompts/ko2en/`, `prompts/en2ko/`,
  `prompts/analyze/`)으로 관리한다. `StrictUndefined`로 컨텍스트 누락을
  즉시 에러로 잡는다. `autoescape`는 **끈다** — 산출물이 HTML이 아니라
  모델에 넣을 평문이라, HTML 이스케이프가 켜지면 용어의 `&`나 따옴표가
  깨진다.
- 문체 프리셋(`prompts/styles/*.yaml`)은 PyYAML `safe_load`로 읽는다.
  이것이 D-23으로 추가된 유일한 신규 의존성이다.
- 프롬프트 버전(`PromptVersion`)은 템플릿 파일들의 SHA-256 해시 12자로
  계산해 `translation_logs`와 응답 `meta.prompt_version`에 남긴다(§7.10) —
  프롬프트 수정이 개선인지 퇴보인지 추적하기 위함.

### httpx — [app/backends/vllm_openai.py](../app/backends/vllm_openai.py)

- 비동기 HTTP 클라이언트로 `/v1/chat/completions`, `/v1/models`를 호출한다.
- vLLM과 llama.cpp가 같은 OpenAI 호환 프로토콜을 쓰므로 **구현체 하나
  (`OpenAICompatBackend`)로 통합**했다(D-24). `VLLMOpenAIBackend`라는
  이름은 계획서 §4.2의 파일명 지정을 지키기 위한 별칭으로 남겨뒀다.
- `httpx.MockTransport`로 실제 서버 없이 [tests/test_backend_openai.py](../tests/test_backend_openai.py)가 프로토콜 레벨 테스트를 수행한다.

### orjson / structlog / tenacity

- `orjson`, `structlog`, `tenacity`는 `requirements-core.txt`에 고정돼
  있지만, 코드 전수 조사 결과 **현재 직접 사용하는 지점은 없다** — 표준
  `json`/`logging`을 쓰고 있다(로그 JSON 직렬화는 `store/runtime.py`에서
  표준 `json.dumps(ensure_ascii=False)`). 향후 구조화 로깅·재시도 로직을
  도입할 자리로 미리 고정해둔 것으로 보인다.

---

## 5. NLP / 텍스트 처리 계층

### Aho-Corasick — [app/glossary/matcher.py](../app/glossary/matcher.py)

- `pyahocorasick`의 `Automaton`으로 용어집의 모든 표층형(표제어 + 이형태)을
  한 번의 텍스트 스캔으로 동시 탐색한다. 텍스트 길이 O(n), 용어집 크기와
  무관 — 그래서 계획서가 임베딩 대신 이 방식을 택했다(D-09: "오탐이
  오역을 강제하는 비대칭 위험"이 근거).
- **두 개의 좌표계**를 구분해서 쓴다: 스캔은 정규화 공간
  (`build_match_space`가 만든 좌표, 공백 제거·소문자화 등), 경계 검증과
  결과 보고는 **원문 좌표**로 되돌린 뒤 수행한다. 두 좌표계를 섞으면
  "제7기동군단 예하 각 군단은" 같은 사례에서 정상 매칭이 탈락한다
  (`docs/phase2-notes.md` §2에 상세 원인 기록).
- 겹침 해소(`resolve_overlaps`)는 그리디 구간 스케줄링이다 — 길이·형태소
  확인 여부·priority 순으로 정렬 후 앞에서부터 채운다. 알려진 한계(짧은
  앞쪽 구간이 긴 뒤쪽 구간을 이길 수 있음)가 README와 코드 주석에 명시돼
  있다.
- 없어도(pyahocorasick 미설치) 서비스는 죽지 않는다 — `automaton_available()`이
  False면 매칭 없이 번역만 되고, `/health`의 `matcher` 필드가 `"none"`으로
  보고된다.

### Kiwi (kiwipiepy) — [app/glossary/morph.py](../app/glossary/morph.py)

- 한국어 형태소 분석 + **문장 분할**을 겸한다. 계획서 원안은 문장 분할에
  `kss`를 쓰라고 했으나 Phase 0 의존성 트리 조사 결과 배제하고
  `Kiwi.split_into_sents()`로 교체했다(D-22). `kss`는 34개 의존성을
  끌고 오고 그중 3개는 wheel조차 없어 폐쇄망 반입이 사실상 불가능했다
  (`docs/phase0-notes.md` §2-b).
- 용어집 표제어를 `add_user_word(surface, "NNP", score=5.0)`로 사용자
  사전에 등록해 최장 일치 분석을 유도한다. 이 덕분에 **문장 분할기와
  매칭 교차검증이 같은 사전을 공유**한다 — 부대명 중간에서 문장이 끊기지
  않고, Aho-Corasick 결과와 형태소 결과가 일치하면 `confirmed=True`로
  겹침 해소 우선순위가 올라간다.
- **에어갭 특이사항**: `kiwipiepy_model`은 별도 패키지이고 PyPI에 wheel이
  없다(sdist만, 79MB). sdist를 그대로 반입하면 `pyproject.toml`이 없어
  pip이 빌드 격리 중 setuptools/wheel을 **내려받으러 나간다** — 폐쇄망에서
  실패. 해결책(D-21)은 개발망에서 `pip wheel kiwipiepy_model==0.22.1 -w
  bundle/kiwi/ --no-deps`로 미리 wheel을 만들어 반입하는 것 — 순수 데이터
  패키지라 `py3-none-any`로 플랫폼 무관 wheel이 나온다.
- `AnalyzerPool`(스레드 안전하지 않은 Kiwi 인스턴스를 `Queue`로 풀링)이
  기동 시 1회 생성되며, 인스턴스당 사용자 사전 등록에 1~3초 걸린다
  (§6.6/§6.7 — 기동 시간 10~20초의 주 원인).
- 없어도(kiwipiepy 미설치, 또는 `NDT_USE_KIWI=false`) 서비스는 죽지
  않는다 — 규칙 기반 분할기(`app/pipeline/segment.py`의
  `_split_sentences_by_rule`)로 조용히 폴백하고, `/health`의 `segmenter`
  필드가 `"rule"`로 보고된다.

### rank-bm25 — [app/tm/retriever.py](../app/tm/retriever.py)

- TM(과거 번역 문장쌍)에서 few-shot 예시를 뽑는 데 `BM25Okapi`를 쓴다.
  용어집과 달리 TM은 강제가 아니라 참고용이라 퍼지 매칭이 적합하다.
- BM25 점수는 상한이 없어 절대값으로 임계 비교가 불가능하다 — 쿼리 내
  **최고 점수로 정규화**한 뒤 `TM_MIN_SCORE=0.35`와 비교한다.
- 토큰화는 한국어 조사 흔들림을 흡수하려 단어 + 2-gram을 함께 넣는
  간이 방식이다(`tokenize()`). 형태소 분석기를 쓰면 더 정확하지만 5만
  문장 기동 시 인덱싱 비용이 커서 지금은 간이 방식을 쓰고, 품질이 부족하면
  교체하기로 했다.
- 임베딩 기반 검색으로의 승급은 **의도적으로 보류**돼 있다 — "실제 성능
  부족이 확인된 뒤에만" 검토(§6.4), 에어갭에서 임베딩 모델을 추가로
  반입하는 부담 때문.

### regex / rapidfuzz

- `regex`는 표준 `re`보다 유니코드 처리가 강력해 `app/glossary/matcher.py`,
  `app/glossary/morph.py`의 미등록 후보 탐지 정규식 등에서 실질적으로는
  표준 `re` 모듈이 쓰이고 있다(코드 확인 결과 `import re`가 대부분). 별도
  `regex` 패키지 직접 import는 발견되지 않았다 — 반입 목록에는 있으나
  현재 잠재 의존성.
- `rapidfuzz`도 `requirements-nlp.txt`에 고정돼 있지만 현재 코드베이스
  전수 검색 결과 직접 사용처가 없다. 향후 퍼지 매칭 강화용으로 미리
  반입해둔 것으로 보인다.

---

## 6. 저장소 계층 — DB 서버 없음 (D-19)

### 설계 원칙

프로젝트의 핵심 결정 중 하나가 "PostgreSQL 등 DB 서버를 쓰지 않는다"이다
(D-19). 근거는 세 가지: ① 에어갭 반입 부담 제거(설치 패키지·계정·백업
절차가 통째로 사라짐), ② 용어집의 git diff 가시성(JSONL은 한 줄=한
레코드), ③ 규모가 DB를 요구하지 않음(용어집 수천 개, TM 수만 쌍, 연간
로그 수백 MB — SQLite로 충분).

### JSONL — [app/glossary/loader.py](../app/glossary/loader.py), [app/tm/loader.py](../app/tm/loader.py)

| 파일 | 내용 | git 관리 | 필수 |
|---|---|---|---|
| `data/glossary.jsonl` | 용어집. 한 줄 = 한 용어 | ✅ | ✅ |
| `data/glossary.meta.json` | 버전 정보(`version`, `count`, `updated_at`) | ✅ | ✅ |
| `data/tm.jsonl` | 번역 메모리. 한 줄 = 한 문장쌍 | ✅ | 선택(없으면 few-shot만 빠짐) |

- 로딩은 앱 시작 시 1회, 이후 메모리 인덱스로만 서비스된다(요청마다
  파일 I/O 없음).
- `//`로 시작하는 줄과 빈 줄은 주석으로 건너뛴다 — 사람이 직접 편집하는
  파일이라 실제로 문법 오류가 난다(R-11). 로더는 **줄 번호를 포함한**
  `GlossaryError`를 던진다.
- 버전 판단은 파일 mtime이 아니라 `glossary.meta.json`의 `version`
  필드로 한다 — 반입 과정에서 mtime이 바뀔 수 있어서.
- 현재 `data/glossary.jsonl`은 **Phase 0 배선 검증용 샘플 20건**이다.
  `confidence`가 `verified`인 항목이 없고 `corpus_freq`는 전부 0
  (미측정)이다. `data/tm.jsonl` 15건도 "LLM이 지어낸 합성 샘플"이라고
  파일 헤더에 명시돼 있다 — 둘 다 Phase 1에서 통째로 교체될 예정.

### SQLite — [app/store/runtime.py](../app/store/runtime.py), [app/store/schema.sql](../app/store/schema.sql)

- `data/runtime.db`는 **폐쇄망 최초 기동 시 생성**되며 반입 대상이 아니다
  (`.gitignore`에 `data/runtime.db*` 포함 — WAL 모드가 `-wal`/`-shm`
  보조 파일도 만들기 때문).
- 표준 라이브러리 `sqlite3`만 쓴다. **ORM 없음** — README와 계획서가
  SQLAlchemy/psycopg/asyncpg 추가를 명시적으로 금지한다(테이블 2개,
  쿼리 단순).
- `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`으로
  동시 읽기/쓰기를 허용한다.
- 단일 커넥션 + `asyncio.Lock`으로 쓰기를 직렬화하고, 실제 I/O는
  `asyncio.to_thread`로 스레드에 위임해 이벤트 루프를 막지 않는다.
- 테이블 2개:
  - `translation_logs` — 매 번역 요청의 원문/번역문/적용용어/위반/백엔드/
    프롬프트버전/용어집버전/청크수/재시도/소요시간. **운영 후 골든셋의
    원천**이 되도록 설계됨(§5.4).
  - `term_candidates` — 용어집에 없는 후보. `(text, direction)` 유니크
    제약 + `UPSERT`로 빈도(freq)를 누적한다.
- 쓰기는 `BackgroundTasks`로 응답 경로 밖에서 실행한다(`app/api/translate.py`)
  — 로그 기록이 번역 응답을 지연시키지 않는다.
- 로그 보존 정책(`purge_old_logs`, 기본 180일)과 `VACUUM`이 구현돼
  있으나 스케줄러 연동은 아직 없음(운영 절차 문서화 대상, Phase 5).

---

## 7. 백엔드(모델) 추상화 계층

### 프로토콜 — [app/backends/base.py](../app/backends/base.py)

`TranslationBackend` (`typing.Protocol`)이 계약이다: `translate()`,
`analyze()`(보조 판정용, 군종 분류 등), `health()`. **매칭·용어집·검증·
웹앱 전체가 어떤 모델이 붙어 있는지 모른다** — 이 경계 덕분에 mock ↔
llama.cpp ↔ vLLM을 코드 변경 없이 스왑할 수 있다.

| `NDT_BACKEND` | 구현체 | 용도 |
|---|---|---|
| `mock` | [MockBackend](../app/backends/mock.py) | GPU/네트워크 불필요. 배선 검증용. **품질 평가 금지**(§3.1) |
| `llamacpp` | `OpenAICompatBackend` | 개발 환경 (RTX 4050 6GB). llama.cpp가 vLLM보다 적합 — vLLM은 KV 캐시를 미리 크게 잡아 6GB에 안 맞음(§8.2) |
| `vllm` | `OpenAICompatBackend` | 운영 (L40S 48GB×2) |
| `openai` | `OpenAICompatBackend` | 위 둘의 공통 별칭 |

`app/backends/__init__.py`의 `build_backend(settings)`가 설정값 하나로
인스턴스를 조립한다.

### MockBackend

용어집 힌트(`TermHint.surfaces`)의 실제 표층형을 문자열 치환으로
반영해서 검증(§6.5)·재호출 경로까지 배선 테스트가 가능하다.
`miss_terms=True`로 의도적으로 용어를 누락시켜 재호출 로직을 시험할 수
있다.

### OpenAICompatBackend

- `base_url`은 반드시 **폐쇄망 내부 주소**(§9.3). 모델 이름을 HF Hub
  식별자가 아니라 서버가 이미 서빙 중인 이름 그대로 쓴다 — 이 프로세스는
  모델을 내려받지도, 토크나이저를 로드하지도 않는다.
  `NDT_VLLM_SERVED_NAME`을 비우면 `/v1/models`의 첫 항목을 자동으로
  쓴다.
  - 실측(개발 환경, `docs/phase0-notes.md` §5-a): llama.cpp +
    `skt/A.X-4.0-Light`(GGUF 7.26B) 기준 기동 1,275ms, 1청크 번역
    2,000~4,100ms.
- 재호출(§7.8)은 대화 히스토리 누적이 아니라 **완전히 새 요청**으로
  구성한다 — 이전 출력을 프롬프트에 포함시켜 전면 재작성이 아닌 수정에
  가깝게 유도.

### Phase 3(모델 서빙 스택) — 아직 미도입

`requirements-serve.txt`(torch/transformers/vllm)는 **잠정 상태**다.
O-06(폐쇄망 서버 OS/CUDA 버전)이 확정돼야 torch wheel(cu121/cu124/cu128
등)을 고를 수 있어, `requirements.lock.txt`에도 포함돼 있지 않다. L40S는
NVLink가 없어 텐서 병렬(TP=2) 대신 "48GB 독립 슬롯 두 개"로 설계할
방침이며, FP8 네이티브 지원(Ada Lovelace)으로 양자화 손실을 줄인다(§3.1,
§8.2).

---

## 8. 파이프라인 아키텍처

### 8단계 처리 흐름 (`app/pipeline/orchestrator.py`)

```
POST /translate
  1. 입력 검증        길이(≤5000자, NDT_MAX_INPUT_CHARS), 방향(ko2en|en2ko)
  2. 정규화           NFKC, 공백 정리, 문단 경계 유지 + 원문 위치 매핑
  3. 분할             Kiwi 또는 규칙 기반 문장 분할 → 청크(~800자) 구성
  4. 전역 사전분석 ──┐  텍스트 전체 1회 스캔 (청크 분할보다 먼저!)
     · 용어 매칭      │  · Aho-Corasick + Kiwi NNP 교차검증
     · 군종 판정      │  · 규칙 우선, 실패 시 선택적 LLM 폴백
     · TM 검색        │  · BM25
     · 미등록 후보    │  · 약어 환각 방지용 탐지
  5. 청크별 번역 ◀────┘  프롬프트 조립(Jinja2) → 모델 호출 (세마포어로 병렬)
  6. 검증             용어 준수 확인 → 실패 청크만 재호출 (최대 1회, NDT_MAX_RETRIES)
  7. 결합             서식 복원(문단 경계), 청크 경계 점검
  8. 응답             translation / terms_applied / warnings / meta
        └─ 비동기      BackgroundTasks로 로그 기록 + 미등록 후보 큐 적재
```

**설계의 핵심은 4번을 5번보다 먼저 하는 것**이다. 청크를 나눠 번역하면
청크 간 일관성(같은 약어의 반복 처리 등)이 깨지므로, 텍스트 전체를 1회
스캔한 결과(`GlobalAnalysis`)를 모든 청크 프롬프트가 공유한다.

### 모듈별 책임

| 모듈 | 책임 | 핵심 함수/클래스 |
|---|---|---|
| [normalize.py](../app/pipeline/normalize.py) | NFKC 정규화, 서식 보존/복원, 원문 위치 매핑 | `normalize()`, `FormatMap`, `strip_preamble()` |
| [segment.py](../app/pipeline/segment.py) | 문장 분할(Kiwi/규칙), 청크 구성 | `build_chunks()`, `split_sentences()` |
| [analyze.py](../app/pipeline/analyze.py) | 전역 사전분석 오케스트레이션, 군종 판정 | `analyze()`, `detect_service_branch()`, `resolve_branch()` |
| [prompt.py](../app/pipeline/prompt.py) | ①~⑥층 프롬프트 조립, 문체 프리셋 로딩 | `PromptBuilder`, `group_terms()` |
| [verify.py](../app/pipeline/verify.py) | 용어 준수 검증 | `verify()`, `term_compliance_rate()` |
| [orchestrator.py](../app/pipeline/orchestrator.py) | 8단계 전체 조율, 동시성 제어, 재호출 루프 | `Orchestrator.run()` |

### 동시성 모델 (§6.6)

두 계층의 세마포어를 쓴다: `max_concurrent_requests`(전체 동시 요청,
기본 16)와 `max_concurrent_per_request`(한 요청 내 청크 병렬도, 기본 4).
CPU 바운드 작업(형태소 분석, Aho-Corasick 스캔)은 `asyncio.to_thread`로
이벤트 루프 밖에 던진다 — 안 그러면 다중 접속 시 전부 같이 느려진다.
Kiwi 인스턴스가 스레드 안전하지 않아 풀(`AnalyzerPool`, Queue 기반)로
관리한다.

---

## 9. 인덱스 생명주기 — [app/glossary/index.py](../app/glossary/index.py)

`IndexRegistry`가 Aho-Corasick 오토마톤(방향별 2개), Kiwi 풀, BM25
리트리버(방향별 2개)를 **앱 시작 시 1회** 빌드해 메모리에 상주시킨다 —
요청마다 재빌드하지 않는다.

- `IndexSnapshot`이 이 모든 것을 한 덩어리로 묶어 **원자적으로 교체**한다
  — 교체 도중의 요청이 반쪽 상태(새 오토마톤 + 옛 Kiwi 풀 등)를 보지
  않게 한다.
- `ensure_loaded()`는 `glossary.meta.json`의 `version`이 바뀌었을 때만
  재빌드한다(이중 확인 락 패턴).
- `POST /admin/reload`([app/api/health.py](../app/api/health.py))로
  무중단 핫리로드가 가능하다. **기본은 비활성**(`NDT_ADMIN_ENABLED=false`)
  — 인증이 없어서 O-07(인증 방식) 확정 전에는 열면 안 됨. 빌드 실패 시
  **기존 인덱스를 유지**하고 422를 반환한다 — 잘못된 용어집으로 교체되는
  것이 서비스 중단보다 나쁘다는 원칙(테스트:
  `test_admin_reload_keeps_old_index_on_bad_glossary`).
- 각 구성요소(Kiwi, pyahocorasick, rank-bm25)가 없어도 실패로 죽지 않고
  단계적으로 폴백한다 — `/health` 응답의 `segmenter`/`matcher`/`tm_size`
  필드로 지금 무엇으로 돌고 있는지 운영 중 확인할 수 있다.

---

## 10. 프롬프트 설계 (§7)

### 층 구조 — 고정 → 가변 순서 (vLLM 프리픽스 캐싱 전제)

```
① 역할·기본 지시     방향별 고정          ┐
② 문체 규칙          스타일 프리셋별      ├─ 프리픽스 캐시 대상
③ 전역 컨텍스트      요청 단위            ┘
④ 용어 대응표        청크별 (가변)        ← 여기서부터 재계산
⑤ TM 예시            청크별 (가변)
⑥ 출력 형식 강제     고정
──────────────────────────────
⑦ 원문               user 메시지
```

이 순서를 지키지 않으면(예: ⑥을 ④ 앞으로 옮기면) vLLM의 prefix caching
히트율이 깨진다 — 템플릿([system.j2](../prompts/ko2en/system.j2))
최상단 주석에 명시.

### ④ 용어 대응표 — 세 블록 강제 분리

```
[Glossary — apply exactly]           ← 강제 (확정된 단일 대역어)
[Glossary — context-dependent, choose one]  ← 다의어 후보 (군종 미확정 시)
[Reference — related terms, use only if they appear]  ← 참고, 강제 아님
```

전부 한 덩어리로 주면 모델이 강제와 참고를 구분하지 못한다는 관찰에서
나온 설계. 매칭된 용어가 없는 블록은 아예 생략한다(빈 헤더가 모델을
혼란스럽게 함).

### 핵심 방어 문구

> "If a term is not in the provided glossary, use standard military
> English conventions. **DO NOT invent acronyms.**"

계획서가 "이 도메인에서 가장 중요한 한 줄"이라고 명시한 지시. 모르는
약어를 만나면 LLM이 그럴듯한 영문 약어를 지어내고, 형태가 자연스러워
검수자가 놓치기 쉽다(R-04). 이를 코드 레벨에서도 보완하는 것이
`app/glossary/matcher.py`의 `find_unknown_candidates()`(미등록 용어 후보
탐지 → `warnings.unknown_candidate`로 노출 + 검수 큐 적재).

### 프리셋 2벌 (§7.9)

`NDT_PROMPT_PRESET`: `full`(①~⑥ 전부, 26B~32B급 모델용) /
`compact`(① + ④ + ⑥만, 4B~7B급 소형 모델용 — 긴 프롬프트에서 지시를
놓치는 경향 보완).

### 재호출 프롬프트 (§7.8)

대화 맥락 유지가 아니라 **매번 새 요청**으로 구성한다(`retry.j2`). 이전
출력을 함께 제시해 "전면 재작성"이 아니라 "부분 수정"에 가깝게 유도한다.

---

## 11. 데이터 모델

### `Term` — 용어집 항목 (`app/glossary/loader.py`)

핵심 필드: `id`(`T-####`), `ko`/`en`(표제어), `en_abbr`, `ko_aliases`/
`en_aliases`(이형태), `conditions`(다의어 분기), `domain_tag`, `priority`,
`corpus_freq`(주입 우선순위 계산용), `abbr_policy`
(`first_full_then_abbr`|`always_full`|`always_abbr`), `source`,
`confidence`(`verified`|`probable`|`candidate`), `note`.

`source`와 `confidence`를 비우지 않는 것이 규칙(README §"지켜야 할 것" 4)
— 나중에 대역이 충돌할 때 신뢰 판단의 유일한 근거이기 때문.

### 다의어 (`conditions`, §5.3)

```json
{"field": "service", "branches": [
  {"value": ["육군","공군","해병대"], "en": "Colonel"},
  {"value": ["해군"], "en": "Captain"}
]}
```

매칭 단계에서 군종이 확정되면 코드가 대역어를 하나로 좁히고
(`resolve_branch`), 확정되지 않으면 후보 전부를 조건과 함께 프롬프트에
넘겨 모델이 문맥으로 판단하게 한다 — "코드가 잘못 확정하면 모델이 그대로
따른다"는 원칙(R-05).

### `TMEntry` — 번역 메모리 항목 (`app/tm/loader.py`)

`ko`, `en`, `source`, `style`, `quality`(`sample`|`verified`). `id`가
없다 — 개별 참조가 아니라 검색 대상이라 인덱스상 위치로 충분하기 때문.

### `LogRecord` — 번역 로그 (`app/store/runtime.py`)

`translation_logs` 테이블 1행에 대응. 운영 후 **골든셋의 원천**이 되도록
설계됨 — 실사용 로그에서 대표 문장을 뽑아 검수하면 평가셋이 된다.
`glossary_version`을 함께 기록해 "용어집 v16과 v17 중 어느 쪽이 나았는가"를
추적할 수 있게 한다.

---

## 12. API 계약 (§4.4)

프론트엔드는 별도 저장소의 완성된 자산이며(D-12), 백엔드가 API 계약에
맞춘다. 필드를 빼거나 이름을 바꾸면 안 된다(`tests/test_api.py` 주석).

```jsonc
// POST /translate
{"text": "...", "source": "ko", "target": "en", "style": "press_release"}

// 200 응답
{
  "translation": "...",
  "terms_applied": [{"source":"...", "target":"...", "term_id":"T-0142",
                      "spans":[[0,2]], "confidence":"verified"}],
  "warnings": [{"type":"term_missing", ...}, {"type":"unknown_candidate", ...}],
  "meta": {"chunks":1, "retries":0, "elapsed_ms":3200,
           "backend":"...", "prompt_version":"ko2en-press-v1",
           "glossary_version":1}
}
```

`terms_applied`/`warnings`는 프론트에 아직 표시 UI가 없어도 처음부터
반환한다 — 나중에 용어 하이라이트 기능을 붙일 때 백엔드를 고치지 않기
위함. `spans`는 정규화 좌표가 아니라 **원문 좌표**로 되돌려서 제공한다
(`FormatMap.to_original_span`).

| 엔드포인트 | 메서드 | 용도 |
|---|---|---|
| `/translate` | POST | 번역 실행 |
| `/health` | GET | 준비 상태, 백엔드/분할기/매칭기/TM 상태 노출 |
| `/admin/reload` | POST | 용어집 핫리로드 (기본 비활성) |

---

## 13. 에어갭(폐쇄망) 대응 — 최우선 설계 제약 (§9)

이 프로젝트의 운영 목표는 **완전 에어갭 환경**이다. 개발망에서 무심코 쓴
자동 다운로드 코드는 개발망에서는 정상 동작하고 폐쇄망에서만 터지므로
발견이 늦다 — 그래서 Phase 0부터 강제한다.

### 금지 패턴 (정적 검사)

`.from_pretrained()`, `snapshot_download()`, `SentenceTransformer()`,
`nltk.download()`, `tiktoken.get_encoding()`, `spacy.load()`,
`requests.get/post/put/delete()`, `urllib.request.urlopen()`,
런타임 `pip install` — 전부 [tests/test_offline.py](../tests/test_offline.py)의
`FORBIDDEN_PATTERNS`가 `app/` 트리 전체를 정적 스캔(주석·문자열 리터럴은
제외하고 실제 호출만)한다. **CI가 없으므로 사람이 실행해야 한다** — 반입 번들을
만들기 전 `pytest tests/test_offline.py`가 통과해야 한다 (R-02).

### 런타임 네트워크 가드

같은 테스트 파일이 `socket.socket.connect`/`getaddrinfo` 등을 몽키패치해
**루프백 밖 연결**을 런타임에도 차단한 채 `/translate` 전체 파이프라인이
끝까지 도는지 확인한다(`test_pipeline_runs_offline`). 계획서 원안은
`socket.socket` 자체를 막으라고 했으나, 그러면 asyncio 이벤트 루프가
자기 깨우기용 로컬 소켓을 못 써서 테스트 프레임워크가 먼저 죽는다
(Windows에서 특히) — 그래서 실제로는 "루프백 밖"만 막도록 수정했다
(`docs/phase0-notes.md` §4-b).

### 환경변수 강제

`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`을
운영 환경과 오프라인 검증 실행 시 설정한다.

### 반입 번들 구성 (계획 — `tools/bundle_build.py`는 Phase 5까지 미구현)

```
bundle-YYYYMMDD/
├─ models/     HF snapshot 전체 + SHA256SUMS
├─ wheels/     pip download 결과 + requirements.lock.txt
├─ kiwi/       kiwipiepy_model-*.whl (개발망에서 미리 빌드, D-21)
├─ data/       glossary.jsonl, tm.jsonl, goldenset.jsonl (runtime.db는 제외)
├─ app/ prompts/  git archive
├─ INSTALL.md, MANIFEST.json
```

용어집만 갱신할 때는 전체 번들을 다시 만들 필요 없이 `glossary.jsonl` +
`glossary.meta.json` 두 파일(1~2MB)만 교체 후 재시작하면 된다(§9.6) —
DB를 썼다면 덤프-전송-복원 절차가 필요했을 자리를 JSONL이 대체한다.

---

## 14. 품질 도구 (요약)

번역 기술 자체와는 별개로, `ruff`(lint+format, 규칙셋 `E,F,W,I,UP,B,SIM,C4`)와
`mypy`(현재 `disallow_untyped_defs=false`, Phase 2에서 조일 예정)로
코드 품질을 관리한다. **CI는 두지 않았으므로**(2026-08-23) `ruff check`,
`ruff format --check`, `pytest` 는 커밋 전에 사람이 실행한다.
테스트 스위트 자체의 구조는
이 문서의 범위에서 제외한다 — 아래 절부터는 **번역 기술**(용어 매칭,
TM, 프롬프트, 검증, 모델 서빙, 평가 설계)에 집중한다.

---

## 15. 오프라인 배치 도구 — `tools/` (전부 Phase 1/5 미구현 스텁)

`tools/`는 **개발망 전용**이며 폐쇄망에 반입하지 않는다
([tools/README.md](../tools/README.md)). `requirements-tools.txt`
(pandas, openpyxl, sentence-transformers, sacrebleu, unbabel-comet)에
의존하는데, 이 중 `sentence-transformers`는 모델을 인터넷에서 내려받으므로
**`app/` 런타임 코드에서는 절대 import하면 안 된다**(§9.3).

| 스크립트 | 목적 | 상태 |
|---|---|---|
| [glossary_import.py](../tools/glossary_import.py) | 확보 용어집(엑셀/HWP/PDF 등) → JSONL 파싱 | 미구현, **O-02 확정 필요** |
| [glossary_lint.py](../tools/glossary_lint.py) | 스키마·중복·대역충돌 검증. 용어집 커밋 전 실행 | 미구현 (일부는 `test_glossary_schema.py`가 대체 중) |
| [corpus_align.py](../tools/corpus_align.py) | LaBSE 임베딩 + DP로 병렬 코퍼스 문장 정렬 | 미구현 |
| [term_extract.py](../tools/term_extract.py) | 통계(로그우도비+Dice) + LLM 기반 용어 후보 추출 | 미구현 |
| [tm_build.py](../tools/tm_build.py) | 정렬 결과 → `tm.jsonl` | 미구현 |
| [bundle_build.py](../tools/bundle_build.py) | 반입 번들 생성 | 미구현, **O-05·O-06 확정 필요** |

`app/eval/`(`metrics.py`, `runner.py`, `report.py`)도 마찬가지로 Phase 3
구현 대상 스텁이며, 유일하게 이미 동작하는 지표는 용어 준수율
(`app/pipeline/verify.py`의 `term_compliance_rate`, `eval/metrics.py`가
재노출)이다.

---

## 16. 현재 구현 상태 요약

| 단계 | 내용 | 상태 |
|---|---|---|
| Phase 0 | 골격, mock 백엔드, SQLite, 오프라인 검증 | ✅ 완료 |
| Phase 1 | 용어집 구축 (500건+) | ⛔ O-01·O-02·O-03 확정 필요, 미착수 |
| Phase 2 | 매칭 엔진 (Aho-Corasick + Kiwi) | ✅ 완료 |
| Phase 3 | 모델 평가 (L40S) | ⛔ O-06 확정 필요, 미착수 |
| Phase 4 | 검증 루프·처리량 | 부분 (재호출 로직은 구현됨, 부하 테스트 미실시) |
| Phase 5 | 에어갭 배포 | ⛔ O-05·O-06 확정 필요, 미착수 |

**엔진은 완성됐지만 용어집이 Phase 0 샘플(20건, 전부 `candidate`/
`probable` confidence, `corpus_freq=0`) 상태**라 실질적 번역 품질은 아직
평가 대상이 아니다. 용어 주입 효과 자체는 실측으로 확인됐다 — 같은 모델
(A.X 4.0 Light)에 용어집을 붙였을 때 "연합훈련"/"합동훈련"의 다국적·다군종
혼동, "JCS"의 오역("국방")이 교정됨(README 표 참조).

### 미확정 항목 (O-01~O-09)이 막고 있는 것

| # | 항목 | 막는 것 |
|---|---|---|
| O-01 | 용어집 검수 인력 확보 여부 | Phase 1 전체 |
| O-02 | 확보 용어집의 현재 형태 | `glossary_import.py` 파서 |
| O-03 | 확보 용어집 규모 | Phase 1 일정 |
| O-04 | 동시 접속자/일일 요청 수 | 워커 수, 세마포어 상한 조정 |
| O-05 | 폐쇄망 반입 절차·주기 | Phase 5, 핫리로드 기능 필수 여부 |
| O-06 | 폐쇄망 GPU 서버 OS/CUDA | `requirements-serve.txt` 최종 잠금 |
| O-07 | 인증 방식 | `/admin/reload` 활성화 여부 |
| O-08 | TTS/STT 실제 구현 여부 | 범위 확정 |
| O-09 | 모델 원산지 조달 규정 | Qwen3(중국계) 후보 유지 여부 |

이 항목들은 **추정으로 결정하면 안 된다** — 코드를 작업하는 사람이든 LLM
에이전트든, 값이 필요하면 멈추고 사람에게 확인해야 한다(계획서 §0.2,
§2).

---

## 17. 설정 항목 전체표 — `app/config.py`

`Settings(BaseSettings)`. 환경변수는 `NDT_` 프리픽스, `.env` 파일 →
프로세스 환경변수 순으로 읽히며 **명시적으로 넘긴 인자가 항상 최우선**이다
(테스트가 이 순서에 의존한다 — `tests/conftest.py`의 `settings` 픽스처
주석 참고). `get_settings()`가 `lru_cache(maxsize=1)`로 프로세스당 한
인스턴스만 만든다.

| 필드 | 타입 | 기본값 | 관련 절 | 설명 |
|---|---|---|---|---|
| `host` | str | `"0.0.0.0"` | — | 서버 바인드 주소 |
| `port` | int | `8080` | — | 서버 포트 |
| `cors_origins` | list[str] | `["http://localhost:5173", "http://127.0.0.1:5173"]` | — | 프론트 오리진 (Vite 기본 포트) |
| `data_dir` | Path | `PROJECT_ROOT/data` | §5 | 용어집·TM·runtime.db 루트 |
| `prompts_dir` | Path | `PROJECT_ROOT/prompts` | §7 | Jinja2 템플릿·스타일 루트 |
| `backend` | Literal | `"mock"` | §4.3 | `mock`\|`openai`\|`vllm`\|`llamacpp` |
| `vllm_base_url` | str | `"http://127.0.0.1:8000/v1"` | §9.3 | 모델 서버 주소. 폐쇄망 내부 주소만 |
| `vllm_served_name` | str | `""` | §9.3 | 비우면 `/v1/models` 첫 항목 자동 사용 |
| `vllm_timeout_s` | float | `180.0` | — | 모델 호출 타임아웃(초) |
| `gen_temperature` | float | `0.2` | — | 생성 온도. 번역은 결정적이어야 하므로 낮게 |
| `gen_top_p` | float | `0.9` | — | nucleus sampling |
| `gen_max_tokens` | int | `2048` | — | 출력 토큰 상한. `0`이면 서버 기본값 |
| `max_input_chars` | int | `5000` | D-05 | 입력 상한. 초과 시 413 |
| `max_chunk_chars` | int | `800` | §6.2 | 청크당 문자 예산 |
| `use_kiwi` | bool | `True` | D-22 | False/미설치 시 규칙 기반 분할기로 폴백 |
| `kiwi_pool_size` | int | `2` | §6.6 | Kiwi 인스턴스 수. 인스턴스당 등록 1~3초 |
| `kiwi_model_path` | str | `""` | §9.3 | 비우면 `kiwipiepy_model` 패키지에서 찾음. 폐쇄망 파일 반입 시만 절대경로 |
| `chunk_term_limit` | int | `10` | §6.3 | 청크당 주입 용어 수 상한 |
| `service_classify_llm` | bool | `False` | R-05 | 규칙으로 군종 미판정 시 LLM에 물을지. O-04 확정 전 기본 비활성 |
| `tm_top_k` | int | `3` | §6.4 | TM few-shot 예시 최대 개수 |
| `tm_min_score` | float | `0.35` | §6.4 | BM25 정규화 점수 임계값 |
| `max_retries` | int | `1` | §6.5, R-08 | 청크당 재호출 상한 |
| `max_concurrent_per_request` | int | `4` | §6.6 | 한 요청 내 청크 병렬도 |
| `max_concurrent_requests` | int | `16` | §6.6 | 전체 동시 요청 상한(세마포어). O-04 확정 후 조정 |
| `prompt_preset` | Literal | `"full"` | §7.9 | `full`\|`compact` |
| `default_style` | str | `"press_release"` | §7.3 | 요청에 `style`이 없을 때 기본값 |
| `admin_enabled` | bool | `False` | O-07 | `/admin/reload` 노출 여부. 인증 없어 기본 비활성 |
| `log_retention_days` | int | `180` | §5.4, R-13 | `purge_old_logs()` 보존 기간 |
| `log_text` | bool | `True` | D-03 | 원문·번역문 로그 저장 여부 |

파생 프로퍼티(계산됨, 환경변수 아님): `glossary_path`, `glossary_meta_path`,
`tm_path`, `runtime_db_path` — 전부 `data_dir` 기준 상대 경로.

---

## 18. 모듈별 API 레퍼런스

파일 전체를 읽고 정리한 공개 함수·클래스 목록이다. 실제 시그니처는 코드
링크를 확인할 것 — 여기서는 역할과 반환값 의미를 요약한다.

### `app/pipeline/normalize.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `FormatMap` | dataclass(frozen) | `original`(원문) + `index_map`(정규화 위치→원문 위치 배열). `to_original_span(start, end)`로 좌표 역변환 |
| `normalize(text)` | 함수 | `(정규화문자열, FormatMap)` 반환. NFKC + 공백정리 + 문단경계 보존 |
| `normalize_with_map(text, direction)` | 함수 | 실제 정규화 로직. `direction`은 Phase 2 예약(현재 미사용, `del direction`) |
| `strip_preamble(text)` | 함수 | 모델이 붙인 머리말(`Here is the translation:` 등)과 감싼 따옴표 한 겹 제거 |
| `tidy_whitespace(text)` | 함수 | 결합 단계용 가벼운 공백 정리 |
| `PREAMBLE_PATTERNS` | 상수 | 정규식 리스트. mock 백엔드 표식(`[mock:...]`)도 포함 |

### `app/pipeline/segment.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `Chunk` | dataclass(frozen) | `index`, `text`, `start`, `end`(정규화 공간 좌표), `paragraph_index` |
| `split_paragraphs(text)` | 함수 | `\n{2,}` 기준 1차 분리, `(오프셋, 본문)` 목록 |
| `split_sentences(text, direction, analyzer)` | 함수 | `analyzer`가 있고 `direction != "en2ko"`면 Kiwi, 아니면 규칙 기반 |
| `_split_sentences_by_rule(text)` | 내부 함수 | 소수점/약어/소문자 연결 오분할 방지 |
| `_is_false_boundary(text, m)` | 내부 함수 | 문장부호가 실제 경계가 아닌 경우 판정 |
| `build_chunks(text, direction, max_chars, analyzer)` | 함수 | 문단 경계를 넘지 않고 문자 예산 안에서 청크 구성 |
| `_group_sentences(sentences, max_chars)` | 내부 함수 | 문장 묶기. 한 문장이 예산 초과 시 하드 분할 |
| `MAX_CHUNK_CHARS` | 상수 | 기본 800 |

### `app/pipeline/analyze.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `GlobalAnalysis` | dataclass | `matches`, `service_branch`, `first_chunk_of`, `tm_examples`, `unknown_candidates`. `matches_in(chunk)` 메서드로 청크별 필터링 |
| `analyze(text, direction, chunks, registry, backend, prompts, use_llm_fallback)` | 비동기 함수 | 전역 사전분석 진입점. 오토마톤 없으면 빈 `GlobalAnalysis` |
| `_analyze_sync(...)` | 내부 함수 | 동기 본체(스캔→교차검증→겹침해소→집계→군종판정→약어추적→TM검색→미등록후보). `asyncio.to_thread` 안에서만 호출 |
| `_analyze_with_llm(...)` | 내부 비동기 함수 | 규칙 판정 실패 시 LLM에 군종 질의(R-05) |
| `detect_service_branch(text, matches)` | 함수 | 단서가 **정확히 하나**일 때만 확정, 그 외 `None` |
| `resolve_branch(term, direction, service_branch)` | 함수 | 다의어를 확정 군종에 맞는 대역어 하나로 좁힘(§5.3) |
| `display_conditions(conditions)` | 함수 | 조건 분기값을 프롬프트 표기(`Navy` 등)로 바꾼 사본 생성 |
| `branch_display(value)` | 함수 | `"해군"` → `"Navy"` 매핑 |
| `_first_chunk_of(matches, chunks)` | 내부 함수 | term_id별 최초 등장 청크 인덱스 |
| `SERVICE_CUES` / `_LLM_SERVICE_MAP` / `SERVICE_SHORT` / `_CUE_TO_SHORT` | 상수 | 군종 판정용 단서·표기 매핑 테이블 |

### `app/pipeline/prompt.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `PromptVersion` | dataclass(frozen) | `id`, `template_hash`(SHA-256 12자), `created_at` |
| `ChunkContext` | dataclass | ③ 전역 컨텍스트 값: `chunk_index`, `total_chunks`, `service_branch`, `introduced`, `first_here` |
| `PromptBuilder` | 클래스 | Jinja2 `Environment`(StrictUndefined, autoescape 끔) + 스타일 YAML 캐시 보유. 앱 수명 동안 1개 |
| `.available_styles()` | 메서드 | 로드된 스타일 이름 목록 |
| `.version(direction, style)` | 메서드(lru_cache) | 템플릿 해시 기반 `PromptVersion` |
| `.build_system(...)` | 메서드 | ①~⑥층 렌더링 |
| `.build_retry(...)` | 메서드 | 재호출 프롬프트 렌더링 |
| `.render_analyze(name, **context)` | 메서드 | `prompts/analyze/*.j2` 렌더링 |
| `group_terms(terms, direction)` | 함수 | `TermHint` 목록을 `exact`/`conditional`/`reference` 3블록으로 분류 |
| `_render_target(hint)` | 내부 함수 | `"Target (ABBR)"` 형태 조립 |
| `_render_options(hint, direction)` | 내부 함수 | `"A (조건1/조건2) | B (조건3)"` 형태 조립 |
| `PROMPT_REVISION` | 상수 | 현재 `1`. 템플릿 대개편 시 올림 |

### `app/pipeline/verify.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `Violation` | dataclass(frozen) | `term_id`, `kind`("missing"), `source`, `expected`. `.to_warning(chunk)`로 API 응답 형식 변환 |
| `verify(src, tgt, applied, direction)` | 함수 | `target_key`(방향을 뒤집은 정규화)로 번역문 검사. `src`는 현재 미사용(시그니처는 계획서 §6.5를 따름) |
| `term_compliance_rate(applied, violations)` | 함수 | 용어 준수율(§12.1 주 지표). `applied`가 비면 `1.0` |

### `app/pipeline/orchestrator.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `InputTooLongError` | 예외(ValueError) | `length`, `limit` 보유 → API가 413으로 변환 |
| `UnsupportedDirectionError` | 예외(ValueError) | → API가 400으로 변환 |
| `TranslationOutcome` | dataclass | `translation`, `terms_applied`, `warnings`, `meta`, `log_record`, `unknown_candidates` |
| `resolve_direction(source, target)` | 함수 | `("ko","en")→"ko2en"`, `("en","ko")→"en2ko"`, 그 외 예외 |
| `Orchestrator` | 클래스 | `settings`, `registry`, `backend`, `prompts` 보유 + 전체 동시 요청 세마포어 |
| `.run(text, direction, style)` | 비동기 메서드 | 8단계 전체 실행. 빈 입력은 즉시 반환(백엔드 호출 0회) |
| `._segment(text, direction)` | 내부 메서드 | Kiwi 풀 획득이 블로킹이라 `asyncio.to_thread`로 감쌈 |
| `._translate_chunk(...)` | 내부 메서드 | 청크 1개: 힌트 선별→프롬프트 조립→번역→검증→(위반 시)재호출 루프 |
| `._meta(...)` | 내부 메서드 | 응답 `meta` 딕셔너리 조립 |
| `_hints_for(matches, direction, limit, service_branch)` | 함수 | `score()` 내림차순 정렬 후 상위 `limit`개를 `TermHint`로 변환. 다의어는 확정 시 좁힘 |
| `_apply_abbr_policy(term, direction, targets)` | 함수 | `abbr_policy`별 표기 결정(§5.1 버그 수정 반영) |
| `_hint_source(headword, surfaces)` | 함수 | `"표제어 / 별칭1 / 별칭2"` 형태, 별칭 최대 `_MAX_ALIAS_IN_HINT=2`개 |
| `_context_for(chunk, all_chunks, analysis, direction)` | 함수 | ③ 블록용 `ChunkContext` 생성. `first_full_then_abbr`만 포함 |
| `_join_chunks(chunks, texts)` | 함수 | 문단 경계 복원(같은 문단이면 공백, 다르면 `\n\n`) |
| `_collect_warnings(chunks, results, analysis)` | 함수 | `term_missing` + `empty_chunk`(R-09) + `unknown_candidate` 수집 |
| `_render_terms_applied(analysis, direction, fmap)` | 함수 | 응답 `terms_applied` 조립, `spans`를 원문 좌표로 역변환 |
| `_effective_targets(term, direction, service_branch)` | 함수 | 응답에 보고할 실제 대역어(프롬프트가 요구한 것과 동일해야 함) |

### `app/glossary/loader.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `GlossaryError` | 예외(ValueError) | `path`, `lineno`, `detail` 보유. `str()`이 `"파일명:줄번호 — 상세"` 형식 |
| `Term` | pydantic 모델(frozen, extra=forbid) | §5.1 스키마 전체 필드 |
| `.source_forms(direction)` | 메서드 | 매칭 인덱스가 찾아야 할 원문 쪽 표층형 목록(중복 제거) |
| `.target_forms(direction)` | 메서드 | 검증이 인정할 번역문 쪽 표층형(다의어 전 분기 포함) |
| `._branch_forms(key)` | 내부 메서드 | 조건 분기의 `en`/`ko` 값 추출 |
| `.is_ambiguous` | 프로퍼티 | `conditions`가 있는지 |
| `GlossaryMeta` | pydantic 모델 | `version`, `updated_at`, `count`, `note` |
| `_dedup(items)` | 함수 | 순서 유지 중복/빈문자열 제거 |
| `load_glossary(path)` | 함수 | JSONL → `list[Term]`, 줄 번호 포함 오류 |
| `load_meta(path)` | 함수 | `glossary.meta.json` → `GlossaryMeta` |
| `_format_validation_error(e)` | 내부 함수 | pydantic `ValidationError`를 한 줄로 축약 |
| `TERM_ID_PATTERN` | 상수 | `^T-\d{4,}$` (1만 건 이상 대비 4자리 이상 허용) |

### `app/glossary/matcher.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `normalize_key(text, direction)` | 함수 | 매칭·검증 공용 정규화. `ko2en`은 공백 전부 제거, `en2ko`는 소문자화+기호 통일+공백 축약 |
| `build_match_space(text, direction)` | 함수 | `normalize_key`와 동일 규칙이되 위치를 잃지 않는 `(문자열, 원문인덱스배열)` 생성 |
| `flip(direction)` | 함수 | 방향 반전 |
| `target_key(text, direction)` | 함수 | **번역문** 정규화. `normalize_key(text, flip(direction))`와 동일 — 계획서 §6.5 버그 수정 |
| `is_hangul(ch)` | 함수 | 한글 여부(자모 포함 범위) |
| `check_boundary(text, start, end, direction)` | 함수 | en2ko는 앞뒤 영숫자 거부, ko2en은 앞 한글 거부 + 뒤 조사 대조 |
| `_continues_hangul(tail, josa)` | 내부 함수 | 조사처럼 보이는 것이 사실 단어의 일부인지 판정 |
| `Surface` | dataclass(frozen) | 인덱스 등록 단위: `term_id`, `text`, `is_primary`, `length` |
| `RawMatch` | dataclass | 겹침 해소 전 후보: `term_id`, `start`, `end`, `surface`, `priority`, `confirmed` |
| `TermMatch` | dataclass | 최종 결과: `term`, `spans`, `count`, `confirmed`, `surfaces` |
| `resolve_overlaps(matches)` | 함수 | 그리디 구간 스케줄링(길이→confirmed→priority 순 정렬) |
| `score(tm)` | 함수 | 주입 우선순위 = `rarity × ambiguous × count` |
| `AutomatonUnavailableError` | 예외 | pyahocorasick 없음 |
| `automaton_available()` | 함수 | import 가능 여부 확인 |
| `GlossaryAutomaton` | 클래스 | 한 방향의 표층형 전체를 담은 오토마톤. `.scan(text)`, `.term(id)`, `.terms_by_id` |
| `mark_confirmed(matches, nnp_spans)` | 함수 | Kiwi NNP 구간과 정확히 일치하는 매칭에 `confirmed=True` 표시 |
| `aggregate(matches, terms_by_id)` | 함수 | 같은 `term_id`의 여러 등장을 `TermMatch` 하나로 묶음 |
| `find_unknown_candidates(text, matches, direction, nnp_spans, limit)` | 함수 | 미등록 용어 후보 탐지(R-04). `MAX_CANDIDATES=20` |
| `_looks_like_person(text, span_end)` | 내부 함수 | 구간 뒤에 계급/직함이 오는지(사람 이름 필터) |
| `_covered_positions(matches)` | 내부 함수 | 이미 매칭된 문자 위치 집합 |
| `JOSA` / `_ACRONYM` / `_PROPER_RUN` / `_KO_DESIGNATION` / `_PERSON_TITLES` / `_PERSON_TITLE_RE` / `_STOP_PROPER` | 상수 | 경계·후보 탐지용 사전/정규식 |

### `app/glossary/morph.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `KiwiUnavailableError` | 예외 | kiwipiepy 또는 모델 패키지 없음 |
| `kiwi_available()` | 함수 | `kiwipiepy` + `kiwipiepy_model` 둘 다 있는지 |
| `MorphToken` | dataclass(frozen) | `form`, `tag`, `start`, `end` |
| `KoreanAnalyzer` | 클래스 | Kiwi 인스턴스 1개 래핑(**스레드 비안전**). 생성 시 용어집을 사용자 사전에 등록 |
| `.split_sentences(text)` | 메서드 | `(오프셋, 문장)` 목록 |
| `.tokenize(text)` | 메서드 | `list[MorphToken]` |
| `.proper_noun_spans(text)` | 메서드 | NNP 태그 구간 집합(교차검증용, 구간을 늘리지 않음) |
| `.variant_spans(text)` | 메서드 | NNP + 형식번호 접미사 구간(변형 탐지 전용, R-04) |
| `AnalyzerPool` | 클래스 | `Queue` 기반 풀. `.acquire(timeout=30.0)` 컨텍스트 매니저 |
| `build_pool(terms, size, model_path)` | 함수 | 풀 생성. 인스턴스마다 사용자 사전 재등록 |
| `USER_WORD_SCORE` / `USER_WORD_TAG` | 상수 | `5.0`, `"NNP"` |
| `_VARIANT_SUFFIX` | 상수 | 형식번호 접미사 정규식(`\b` 미사용 — 유니코드 로마숫자 함정 회피) |

### `app/glossary/index.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `GlossaryIndex` | dataclass | 한 방향의 인덱스: `direction`, `terms`, `by_id`, `automaton`. `.build(direction, terms)` 클래스메서드 |
| `IndexSnapshot` | dataclass | `version`, `meta`, `ko2en`, `en2ko`, `build_ms`, `kiwi_pool`, `tm_ko2en`, `tm_en2ko` — 원자적 교체 단위 |
| `IndexRegistry` | 클래스 | 앱 수명 동안 1개. 스냅샷 소유·재빌드 조율 |
| `.ready` / `.version` / `.last_error` / `.snapshot` | 프로퍼티 | 상태 조회 |
| `.index_for(direction)` / `.kiwi_pool` / `.automaton_for(direction)` / `.tm_for(direction)` | 접근자 | 방향별 컴포넌트 조회 |
| `.stats()` | 메서드 | `/health` 응답용 딕셔너리(`segmenter`, `matcher`, `tm_size` 등) |
| `.ensure_loaded()` | 비동기 메서드 | 메타 버전 변경 시에만 재빌드(이중 확인 락) |
| `.reload()` | 비동기 메서드 | 강제 재빌드(관리 엔드포인트용). 실패 시 기존 유지 |
| `._rebuild(meta)` / `._build_tm()` / `._build_kiwi_pool(terms)` | 내부 메서드 | 각 컴포넌트 빌드. 전부 실패해도 서비스는 계속(단계적 폴백) |

### `app/tm/loader.py`, `app/tm/retriever.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `TMEntry` | pydantic 모델(frozen) | `ko`, `en`, `source`, `style`, `quality`. `.query_side(direction)`, `.as_example(direction)` |
| `load_tm(path)` | 함수 | 파일 없으면 빈 목록(TM은 선택 자산) |
| `RetrieverUnavailableError` | 예외 | rank-bm25 없음 |
| `retriever_available()` | 함수 | import 가능 여부 |
| `tokenize(text, direction)` | 함수 | 단어 + (ko2en이면) 2-gram 토큰화 |
| `BM25Retriever` | 클래스 | 방향별 인덱스. `.retrieve(query, top_k, min_score)`가 최고점 대비 정규화 점수로 필터링 |
| `TM_TOP_K` / `TM_MIN_SCORE` | 상수 | `3`, `0.35` |

### `app/store/runtime.py`

| 이름 | 종류 | 설명 |
|---|---|---|
| `LogRecord` | dataclass | `translation_logs` 1행에 대응. `id`/`created_at` 자동 생성 |
| `RuntimeStore` | 클래스 | 단일 SQLite 커넥션 + `asyncio.Lock` |
| `.connect()` / `.close()` | 메서드 | DB 열기(스키마 자동 적용)/닫기 |
| `.log_translation(record)` | 비동기 메서드 | 로그 기록. 예외를 삼키고 로깅만(서비스 중단 방지) |
| `.record_term_candidates(texts, direction)` | 비동기 메서드 | UPSERT로 빈도 누적 |
| `.purge_old_logs(days)` | 비동기 메서드 | 보존 기간 초과 로그 삭제 + `VACUUM` |
| `.pending_candidates(limit)` / `.log_count()` | 비동기 메서드 | 조회용(운영 도구용) |

### `app/backends/*`

| 이름 | 종류 | 설명 |
|---|---|---|
| `TermHint` | dataclass | 프롬프트에 넘길 용어 1건. `source`(표기), `targets`, `surfaces`, `conditions`, `abbr`, `is_reference`, `term_id` |
| `TranslationRequest` / `TranslationResult` | dataclass | 백엔드 입출력 계약 |
| `TranslationBackend` | Protocol(runtime_checkable) | `translate()`, `analyze()`, `health()`, `name` |
| `MockBackend` | 클래스 | `miss_terms`, `latency_ms` 옵션. `last_request`/`call_count`로 테스트 검증 지원 |
| `OpenAICompatBackend` | 클래스 | `/v1/chat/completions`, `/v1/models` 호출. `resolve_model()`이 이름 자동 확정 |
| `BackendError` | 예외(RuntimeError) | 모델 서버 호출 실패(연결 실패/HTTP 오류/응답 형식 오류 구분) |
| `build_backend(settings)` | 함수 | 설정값 → 백엔드 인스턴스 팩토리 |

---

## 19. End-to-End 실행 트레이스

`tests/test_api.py`의 실제 요청으로 파이프라인 각 단계의 데이터 변화를
구체적으로 추적한다. mock 백엔드, 샘플 용어집(20건) 기준.

**요청**

```json
POST /translate
{"text": "합참은 제7기동군단 예하 부대의 훈련을 참관했다고 밝혔다.",
 "source": "ko", "target": "en"}
```

**1) 입력 검증** — 길이 27자 ≤ 5000. `resolve_direction("ko","en")` →
`"ko2en"`.

**2) 정규화** (`normalize()`) — 이미 정규 형태라 문자 그대로 유지,
`FormatMap.index_map`은 `[0,1,2,...,26]`(항등 매핑).

**3) 분할** (`build_chunks`) — 문단 1개, Kiwi(or 규칙 기반)가 문장 1개로
판단 → `Chunk(index=0, text="합참은 ... 밝혔다.", start=0, end=27,
paragraph_index=0)` 1개.

**4) 전역 사전분석** (`analyze()`):

- Aho-Corasick 스캔이 정규화 공간(공백 제거)에서 실행되고 원문 좌표로
  환원됨. 결과 `RawMatch` 후보:
  - `(term_id="T-0142", start=0, end=2, surface="합참")` — `T-0142`의
    별칭 표층형과 일치
  - `(term_id="T-0301", start=4, end=10, surface="제7기동군단")`
- ko2en이므로 Kiwi 교차검증 실행 — 두 구간 모두 NNP로 확인되어
  `confirmed=True`.
- `resolve_overlaps()` — 겹침 없음(서로 다른 위치), 둘 다 통과.
- `aggregate()` → `TermMatch(term=T-0142, spans=[(0,2)], surfaces=["합참"])`,
  `TermMatch(term=T-0301, spans=[(4,10)], surfaces=["제7기동군단"])`.
- `detect_service_branch()` — 군종 단서 없음 → `service_branch=None`.
- `_first_chunk_of` → `{"T-0142":0, "T-0301":0}`.
- TM 검색 — `data/tm.jsonl`에 유사 문장("합참은 20일부터...") 있으면
  BM25 top-3 후보 반환(정규화 점수 ≥0.35인 것만).
- 미등록 후보 — "부대", "훈련" 등은 용어집에 없지만 계급/직함 패턴이 아니고
  대문자 고유명사 패턴에도 안 걸려 후보에 오르지 않음.

**5) 청크별 번역** (`_translate_chunk`, 청크 1개이므로 병렬성 미발동):

- `_hints_for()` — `score()`로 정렬(둘 다 `corpus_freq=0`이므로 희소도
  가중 동일, T-0301이 priority 20으로 우선). 다의어 아니므로 조건 없음.
  `_apply_abbr_policy(T-0142)` — `abbr_policy="first_full_then_abbr"`이므로
  `targets=["Joint Chiefs of Staff"]`, `abbr="JCS"` 유지.
- `_hint_source("합동참모본부", ["합참"])` → `"합동참모본부 / 합참"` —
  본문의 실제 표층형(별칭)을 표제어와 함께 보여줌(§7.5).
- `_context_for()` — 단일 청크, 군종 미확정, `first_full_then_abbr`
  용어(T-0142)가 이 청크가 첫 등장이므로 `first_here=["Joint Chiefs of
  Staff (JCS)"]`.
- 시스템 프롬프트 조립 결과에 다음이 포함됨:
  ```
  [Glossary — apply exactly]
  합동참모본부 / 합참 → Joint Chiefs of Staff (JCS)
  제7기동군단 → VII Maneuver Corps
  ```
- `MockBackend.translate()` — `req.terms`의 `surfaces`(`["합참"]`,
  `["제7기동군단"]`)를 원문에서 긴 것부터 치환:
  `"[mock:ko2en] Joint Chiefs of Staff Chiefs of Staff... "` 형태가
  아니라 실제로는 `"합참"→"Joint Chiefs of Staff"`,
  `"제7기동군단"→"VII Maneuver Corps"`로 치환한 뒤
  `"[mock:ko2en] "` 접두어를 붙임.
- `strip_preamble()`이 `[mock:ko2en]` 접두어를 제거(PREAMBLE_PATTERNS에
  포함).

**6) 검증** (`verify()`) — `target_key(text, "ko2en")`는 영어 규칙(소문자화)
적용. 치환이 이미 반영됐으므로 `"Joint Chiefs of Staff"`,
`"VII Maneuver Corps"`가 모두 발견됨 → `violations=[]` → 재호출 없음.

**7) 결합** — 청크 1개이므로 그대로.

**8) 응답**:

```json
{
  "translation": "Joint Chiefs of Staff observed the training of a unit under VII Maneuver Corps.",
  "terms_applied": [
    {"source":"합동참모본부","target":"Joint Chiefs of Staff","term_id":"T-0142",
     "spans":[[0,2]],"confidence":"probable"},
    {"source":"제7기동군단","target":"VII Maneuver Corps","term_id":"T-0301",
     "spans":[[4,10]],"confidence":"candidate"}
  ],
  "warnings": [],
  "meta": {"chunks":1,"retries":0,"elapsed_ms":"...","backend":"mock",
           "prompt_version":"ko2en-press-v1","glossary_version":1}
}
```

(`test_matched_terms_are_applied`가 `"Joint Chiefs of Staff" in
translation`, `{"T-0142","T-0301"} <= term_ids`, `retries==0`을 실제로
단언한다.)

**비동기 후처리** — 응답 전송 후 `BackgroundTasks`가
`store.log_translation()`(→ `translation_logs` 1행)과
`store.record_term_candidates()`(미등록 후보 없으므로 no-op)를 실행.

### 재호출이 발생하는 경우 — `MockBackend(miss_terms=True)`

용어 치환을 생략하면 `verify()`가 `T-0142`, `T-0301` 둘 다 `missing`으로
판정 → `retry.j2`로 새 요청 구성(`[Previous attempt omitted required
terms]` + 이전 출력 + 원문) → 재호출 1회 → 여전히 실패 시(`miss_terms`가
계속 켜져 있으므로) `warnings`에 `term_missing` 2건, `meta.retries=1`로
응답(`test_second_violation_becomes_a_warning`).

---

## 20. 핵심 알고리즘 코드 워크스루

### 20.1 두 좌표계 분리 — `build_match_space` (`app/glossary/matcher.py`)

```python
def build_match_space(text: str, direction: str) -> tuple[str, list[int]]:
    if unicodedata.is_normalized("NFKC", text):
        chars, idx = list(text), list(range(len(text)))
    else:
        chars, idx = [], []
        for i, ch in enumerate(text):
            for out_ch in unicodedata.normalize("NFKC", ch):
                chars.append(out_ch); idx.append(i)

    if direction == "ko2en":
        out_chars, out_idx = [], []
        for ch, src in zip(chars, idx, strict=True):
            if not ch.isspace():
                out_chars.append(ch); out_idx.append(src)
        return "".join(out_chars), out_idx
    # en2ko: 소문자 + 기호 통일 + 공백 축약 (생략)
```

`GlossaryAutomaton.scan()`이 이 함수로 만든 `match_text`에서 Aho-Corasick을
돌리고, 매치 위치(`m_start`, `end_idx`)를 `index_map`으로 **원문 좌표로
환원한 뒤** `check_boundary()`를 원문(`text`, 공백 포함)에서 호출한다.
이 순서가 뒤바뀌면 "제7기동군단 예하 각 군단은"에서 공백 제거 후
`"...예하각군단은"`이 되어 `군단` 앞이 `각`으로 붙어 "앞이 한글이면 거부"
규칙에 걸려 정상 매칭(T-0300)이 탈락한다 — Phase 2에서 실제로 발견되고
고쳐진 버그(`docs/phase2-notes.md` §2).

### 20.2 검증 방향 반전 — `target_key` (`app/glossary/matcher.py`)

```python
def target_key(text: str, direction: str) -> str:
    return normalize_key(text, flip(direction))
```

계획서 §6.5 원안은 `normalize_key(tgt, direction)`을 그대로 썼다.
`direction="ko2en"`일 때 `normalize_key`는 **한국어 규칙**(공백 제거,
대소문자 유지)을 적용하는데, `tgt`(번역문)는 **영어**다. 그 결과
`"the joint chiefs of staff said"`가 `"Joint Chiefs of Staff"`와
매칭되지 않아(대소문자 불일치) 정상 번역이 위반으로 오판된다. `verify()`는
`target_key`를 써서 방향을 뒤집어 번역문 언어에 맞는 규칙을 적용한다.
(`docs/phase0-notes.md` §4-a, `tests/test_verify.py`의
`test_verification_is_case_insensitive_for_english_target`,
`test_korean_target_ignores_spacing`이 회귀 방지.)

### 20.3 겹침 해소 — `resolve_overlaps` (`app/glossary/matcher.py`)

```python
def resolve_overlaps(matches: list[RawMatch]) -> list[RawMatch]:
    ordered = sorted(matches, key=lambda m: (
        m.start, -(m.end - m.start), not m.confirmed, -m.priority,
    ))
    out, cursor = [], -1
    for m in ordered:
        if m.start >= cursor:
            out.append(m)
            cursor = m.end
    return out
```

정렬 키 우선순위: **시작 위치 → 긴 길이 우선 → 형태소 확인 우선 →
priority 높은 순**. "제7기동군단"에 `제7기동군단`(T-0301, priority 20),
`군단`(T-0300, priority 3)이 겹치면 길이가 긴 T-0301이 이긴다. 알려진
한계: `[0,5]`와 `[3,20]`처럼 서로 다른 시작 위치의 구간이 경합하면 그리디라
짧은 앞쪽이 뒤쪽 긴 구간을 막을 수 있다 — 실무에서 문제가 확인되면
가중 구간 스케줄링(DP)으로 교체 예정(README/코드 주석에 명시된 기술 부채).

### 20.4 미등록 후보 탐지 — 완전 포함만 제외 (`app/glossary/matcher.py`)

```python
spans = [(s, e) for s, e in set(spans)
         if not all(p in covered for p in range(s, e))]
```

처음 구현은 "한 글자라도 기존 매칭과 겹치면 제외"였다. 그러면 용어집에
`천무`(T-0401)가 있을 때 `천무-Ⅱ`가 일부 겹친다는 이유로 후보에서
빠진다 — 그런데 API 계약 예시(`{"type":"unknown_candidate","text":
"천무-Ⅱ"}`)가 보여주듯 **정작 등록이 필요한 것은 변형 쪽**이다. 그래서
"완전히" 덮인 구간만 제외하도록 수정했다(`docs/phase2-notes.md` §6-a).
변형 구간 자체는 `KoreanAnalyzer.variant_spans()`가 별도로 탐지한다 —
Kiwi가 하이픈에서 끊어 NNP가 `천무`까지만 잡히기 때문에, 뒤에 붙는
형식번호(`_VARIANT_SUFFIX` 정규식)를 별도로 확장해서 구간을 만든다.

**정규식 함정**: `_VARIANT_SUFFIX`와 `_PERSON_TITLE_RE`는 끝에 `\b`를
붙이지 않는다. 유니코드 로마 숫자(`Ⅱ`, U+2161)와 뒤따르는 한글 조사가
둘 다 "단어 문자"로 취급돼 그 사이에 단어 경계가 생기지 않아 `\b`를 쓰면
매치가 통째로 실패한다(`docs/phase2-notes.md` §6-b에 명시된 실제 함정).

### 20.5 약어 정책 적용 — `_apply_abbr_policy` (`app/pipeline/orchestrator.py`)

```python
def _apply_abbr_policy(term, direction, targets):
    abbr = term.en_abbr if direction == "ko2en" else None
    if not abbr:
        return targets, None
    if term.abbr_policy == "always_full":
        return targets, None                      # 약어를 아예 안 보여줌
    if term.abbr_policy == "always_abbr":
        return [abbr, *[t for t in targets if t != abbr]], None  # 약어 자체가 대역어
    return targets, abbr                            # first_full_then_abbr: 둘 다 노출
```

`대령`(T-0087)은 `always_full`인데, 초기 구현은 `en_abbr`("COL")이 있으면
정책과 무관하게 ③ 전역 컨텍스트에 "Colonel (COL)"로 노출했다. 실제 모델
(A.X 4.0 Light)이 `COL Kim Cheol-soo`를 출력했다 — **시킨 대로 한 것**이다.
수정 후 ③ 블록(`_context_for`)은 `abbr_policy == "first_full_then_abbr"`인
용어만 포함하도록 필터링한다(`docs/phase2-notes.md` §4).

---

## 21. 번역 메모리(TM) 시스템 심층 분석

### 21.1 TM이란 무엇이고 왜 용어집과 분리했는가 (D-11)

TM(Translation Memory)은 **과거 번역 문장쌍 저장소**로, 용어집과는 목적이
다르다.

| | 용어집 (Glossary) | TM |
|---|---|---|
| 저장 단위 | 단어/구(용어) | 문장 전체 |
| 역할 | **강제** — 프롬프트가 "이 표현은 반드시 이 대역어로" 지시 | **참고** — few-shot 예시로 문체·구문 패턴을 시연 |
| 매칭 방식 | 정확 매칭(Aho-Corasick) + 형태소 교차검증 | 퍼지 검색(BM25) |
| 검증 대상 | `verify()`가 사용 여부를 강제 확인 | 검증 안 함. 예시일 뿐 |
| 오탐 시 피해 | 오역 강제(비대칭 위험, D-09) | 스타일이 살짝 안 맞는 정도 |

이 비대칭성이 알고리즘 선택을 가른다 — 용어집은 오탐이 곧바로 오역으로
이어지므로 정확 매칭만 쓰고 임베딩을 배제했다(D-09). TM은 예시로만
쓰이므로 퍼지 매칭이 허용된다(§6.4). "BM25로 시작하고, 필요하면 임베딩
으로 승급한다"는 방침도 TM에만 해당하며, **임베딩 도입은 실제 성능
부족이 확인된 뒤에만** 검토한다 — 에어갭에서 임베딩 모델을 추가로
반입하는 부담이 크기 때문(계획서 §6.4, §9.2).

### 21.2 데이터 스키마 — [app/tm/loader.py](../app/tm/loader.py)

```jsonc
{"ko":"합참은 20일부터 나흘간 연합훈련을 실시한다고 밝혔다.",
 "en":"The JCS said a combined exercise will be conducted for four days from the 20th.",
 "source":"국방부 보도자료 2025-03","style":"press_release","quality":"verified"}
```

`TMEntry`(pydantic, `extra="forbid"`, `frozen=True`): `ko`, `en`,
`source`(선택, 기본 `""`), `style`(기본 `"press_release"`),
`quality`(`"sample"`|`"verified"`, 기본 `"verified"`). **`id` 필드가
없다** — 용어집(`Term`)과 달리 개별 참조 대상이 아니라 검색 대상이라
인덱스상 위치만으로 충분하다는 설계 판단(§5.2).

`load_tm(path)`은 파일이 없으면 **에러 없이 빈 목록**을 반환한다 — TM은
선택 자산이라 없어도 서비스가 죽지 않고 few-shot 예시만 빠진다. 있으면
`//` 주석 줄과 빈 줄을 건너뛰며 JSONL을 한 줄씩 파싱하고, 실패 시
용어집과 같은 `GlossaryError`(줄 번호 포함)를 재사용해서 던진다.

### 21.3 인덱싱 — 방향별 BM25 (`app/glossary/index.py` → `IndexRegistry._build_tm`)

기동 시 1회, `ko2en`·`en2ko` **방향마다 별도의 `BM25Okapi` 인덱스**를
만든다(`app/tm/retriever.py`). 5만 쌍 기준 5~10초가 걸리는 것으로
계획서에 산정돼 있다(§6.7) — 요청마다 만들면 안 되는 이유다.
`rank_bm25`가 미설치이거나 `tm.jsonl`이 비어 있으면 두 인덱스 모두
`None`이 되고 `/health`의 `tm_size`가 `0`으로 보고된다 — TM 없이도
번역은 되지만 프롬프트 ⑤층(TM 예시)이 통째로 생략된다.

### 21.4 토큰화 — `tokenize(text, direction)`

```python
def tokenize(text: str, direction: str) -> list[str]:
    words = [w.lower() for w in _WORD.findall(text)]   # [0-9a-z]+|[가-힣]+
    if direction != "ko2en":
        return words
    tokens = list(words)
    for word in words:
        if len(word) > 2 and "가" <= word[0] <= "힣":
            tokens.extend(word[i:i+2] for i in range(len(word)-1))  # 2-gram
    return tokens
```

한국어는 조사가 단어에 들러붙어("합참은" vs "합참이") 표층형이 흔들리므로,
단어 유니그램에 더해 **한글 단어의 문자 2-gram**을 추가로 넣어 부분
일치를 잡는다. 형태소 분석기로 정확히 토큰화하면 품질이 오르겠지만,
TM 인덱스는 기동 시 한 번에 5만 문장을 처리해야 해서(§6.7) 그 비용을
감수하지 않고 간이 방식을 택했다 — "검색 품질이 부족하면 그때 교체한다"는
방침이 코드 주석에 명시돼 있다(향후 개선 여지로 남겨둔 기술 부채).

### 21.5 검색과 점수 정규화 — `BM25Retriever.retrieve()`

```python
scores = self._bm25.get_scores(tokens)
best = max(scores) if len(scores) else 0.0
if best <= 0:
    return []
ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
out = []
for i in ranked[:top_k]:
    if scores[i] / best < min_score:
        break
    out.append(self.entries[i].as_example(self.direction))
return out
```

BM25 점수는 코퍼스 크기·문서 길이에 따라 상한이 없어 **절대값으로
임계 비교가 불가능**하다. 그래서 "쿼리 내 최고 점수 대비 상대 비율"로
정규화한 뒤 `TM_MIN_SCORE=0.35`와 비교한다 — "가장 비슷한 후보 대비
얼마나 비슷한가"를 보는 것이지 절대적인 유사도를 보는 게 아니다.
`TM_TOP_K=3`이 최대 예시 개수(`NDT_TM_MIN_SCORE`/구성 없음, 코드
상수지만 `Settings.tm_top_k`/`tm_min_score`로 오버라이드 가능).

이 정규화 방식이 아직 실데이터로 검증되지 않았다는 점이 `docs/phase2-notes.md`
§9에 명시돼 있다 — 현재는 합성 데이터로만 테스트했고, **Phase 1에서 실제
TM이 들어오면 이 임계값을 재조정해야 한다.**

### 21.6 few-shot 선택 원칙 — 의미 유사성보다 구문 유사성 (§7.6)

계획서가 명시적으로 강조하는 설계 원칙: TM few-shot 예시를 고를 때
**의미적으로 비슷한 문장보다 구문(syntax) 패턴이 비슷한 문장을
우선한다.** 근거는 "용어 경계 포착에 더 신뢰할 만한 지침을 제공한다는
연구 결과"이며, 군사 보도자료는 "~라고 밝혔다", "~을 실시했다" 같은
구문 패턴이 반복되므로 이 도메인에 특히 잘 맞는다고 판단했다. BM25가
바로 이 성질(표층 토큰 중첩)을 재는 알고리즘이라 임베딩 기반 의미
검색보다 오히려 이 과제에 적합하다는 것이 TM 검색기 docstring의 명시적
주장이다.

`data/tm.jsonl`의 실제 샘플 15건도 이 원칙을 반영해 "국방부는 ~라고
밝혔다", "~은 ~을 실시했다고 밝혔다"류의 반복 구문으로 의도적으로
구성돼 있다(파일 헤더 주석).

### 21.7 현재 데이터 상태 — 경고

`data/tm.jsonl`은 파일 헤더에 이중 경고(`⚠⚠`)가 붙어 있다:

> **"이것은 검수된 번역 메모리가 아니다. LLM이 지어낸 합성 샘플
> 15건이다."** ... **"이 파일의 문장을 실제 번역 사례로 인용하지 말
> 것."**

Phase 1 완료 기준은 "TM 세그먼트 10,000쌍 이상"이며, 원천은 AI Hub
병렬 말뭉치와 국방부 보도자료를 정렬한 것으로 계획돼 있다(§11 Phase 1).
현재 15건은 순전히 **BM25 검색 경로의 배선(wiring)을 확인**하기 위한
placeholder다. `quality` 필드가 전부 `"sample"`인 것도 이 상태를
반영한다(`"verified"`는 사람 검수를 마친 것만 표시하도록 예약돼 있음).

### 21.8 평가 오염 방지 — TM과 골든셋의 분리

TM과 골든셋(평가용 정답 세트)이 문장을 공유하면 안 된다는 규칙이 파일
헤더에 명시돼 있다:

> "data/goldenset.jsonl과 문장이 겹치면 안 된다. 겹치면 모델이
> few-shot으로 정답을 받아 보고 답하는 셈이라 평가가 무의미해진다."

TM은 프롬프트 ⑤층에 **그대로 노출되는** few-shot 예시이므로, 평가
문장과 TM 문장이 같으면 모델이 정답을 참고해서 맞히는 데이터 누수
(data leakage)가 발생한다. `tests/test_goldenset.py`가 이 분리를
검사하도록 설계돼 있다고 주석에 언급돼 있으나(코드베이스 전수 확인
결과 `data/goldenset.jsonl` 자체가 아직 존재하지 않아 이 테스트는
Phase 3에서 골든셋이 만들어질 때 함께 추가될 예정으로 보인다).

---

## 22. 평가 설계 — 골든셋과 지표 (Phase 3, 설계는 확정·구현은 대기)

### 22.1 골든셋(Goldenset)이란

**사람이 검수한 정답 번역 쌍의 회귀 테스트셋**이다(계획서 §0.3 용어
정의). 프롬프트나 용어집을 수정할 때마다 골든셋 전체를 재실행해 이전
버전과 비교하는 것이 목적이다(§12.3). 아직 `data/goldenset.jsonl`은
존재하지 않고, `app/eval/runner.py`도 스텁 상태(`NotImplementedError`)다.

**구축 계획**(§11 Phase 3 작업 1): 보도자료 실제 문장 50개(한→영 25,
영→한 25)를 사람이 검수한다. **고유명사 밀집 문장을 의도적으로
포함**하도록 명시돼 있으며, 계획서가 예시로 든 문장이 이 도메인의
난이도를 잘 보여준다:

> "제7기동군단 예하 제20기계화보병사단은 K2 흑표와 천무 다연장로켓을
> 동원한 합동훈련을 실시했다고 합동참모본부가 밝혔다."

이 한 문장에 부대명(제7기동군단, 제20기계화보병사단), 장비명(K2
흑표, 천무), 다의어 위험 용어(합동훈련 vs 연합훈련), 약어 대상 기관
(합동참모본부)이 전부 들어 있다 — 골든셋을 이런 문장 위주로 구성하는
것 자체가 "일반 번역 품질보다 용어 처리 정확도를 재는 것이 이 평가의
목적"이라는 설계 의도를 보여준다.

**운영 후 대체 경로**: `translation_logs`(SQLite)가 "운영 후 골든셋의
원천"이 되도록 이미 설계돼 있다(§5.4) — 실사용 로그에서 대표 문장을
뽑아 검수하면 자연스럽게 골든셋이 확장된다. 이를 위해 매 로그 행에
`glossary_version`, `prompt_version`을 함께 남기는 것이 필수였다 —
"용어집 v16과 v17 중 어느 쪽이 나았는가"를 나중에 따지려면 그 시점의
버전 정보가 있어야 하기 때문이다.

### 22.2 세 가지 평가 모드 — WMT25 방식 (§12.2)

```
noterm   프롬프트에 용어 정보를 전혀 넣지 않음
proper   실제 매칭된 용어(정상 파이프라인 그대로)
random   원문에서 무작위로 추출한 단어를 "용어"인 것처럼 주입
```

이 세 모드를 같은 골든셋·같은 모델로 비교하면 **용어집이 실제로 기여하는
정도를 인과적으로 분리**할 수 있다. `random`은 대조군 역할이다 — 무작위
단어는 대개 일반 어휘라 용어집 없이도 모델이 이미 잘 번역하므로,
`proper`보다 점수가 낮아야 정상이다. 계획서가 명시하는 함정: **"random이
proper보다 높게 나오면 지표 설계가 잘못된 것"** — 즉 이 비교 자체가
평가 파이프라인의 자체 검증 장치로 쓰인다.

README에 실제로 기록된 실측(A.X 4.0 Light, 샘플 용어집 20건)이 `noterm`
vs `proper`(계획서 용어로는 "용어집 없음" vs "용어집 적용")의 실제
사례다:

| 원문 | noterm(용어집 없음) | proper(용어집 적용) |
|---|---|---|
| 연합훈련 | joint training exercise ✗ | combined exercise ✓ |
| The JCS | 국방 ✗ | 합동참모본부 ✓ |
| combined exercise | 합동훈련 ✗ | 연합훈련 ✓ |
| 해군 … 대령 | COL Kim ✗ | Captain Kim ✓ |

"연합"(다국적)과 "합동"(다군종)의 양방향 혼동이 용어 주입으로
교정되는 것이 이 프로젝트가 존재하는 근거로 README에 명시돼 있다.

### 22.3 지표 — [app/eval/metrics.py](../app/eval/metrics.py)

| 지표 | 계산 방식 | 자동화 | 구현 상태 |
|---|---|---|---|
| **용어 준수율** (주 지표) | 원문에 등장한 용어 중 지정 대역어로 번역된 비율 | 완전 자동 | ✅ 이미 동작(`verify.py`) |
| 용어 일관성 | 같은 용어가 문서 내 동일하게 번역되는 비율 | 완전 자동 | Phase 3 (`term_consistency`, 스텁) |
| 약어 처리 정확도 | 첫 등장 full form + 이후 약어 규칙 준수율 | 완전 자동 | Phase 3 (`abbr_accuracy`, 스텁) |
| chrF | 문자 n-gram F-score | 자동(골든셋 필요) | Phase 3 미착수 |
| COMET | 신경망 기반 품질 추정 | 자동(모델 반입 필요, 선택) | Phase 3 미착수, `unbabel-comet`(requirements-tools) |

**용어 준수율이 1순위 지표**인 이유가 명확히 서술돼 있다 — "용어집
기반이라 자동 측정이 가능하고, 이 도메인의 핵심 요구사항과 직결된다."
일반 번역 품질 지표(chrF/COMET)는 보조로 규정된다. WMT25 기준으로도
주 평가는 "일반 품질 × 용어 성공률" 조합이라는 것이 근거로 인용된다.

**이미 동작하는 부분**: `term_compliance_rate()`(`app/pipeline/verify.py`)가
실제로 매 번역 요청마다 계산되며, 그 결과(`violations`)가
`translation_logs`에 저장된다. 즉 §12.1의 "주 지표"는 평가 스크립트를
기다릴 필요 없이 **운영 중에도 이미 수집되고 있다** — Phase 3에서
필요한 것은 골든셋에 대해 일괄 집계하는 러너(`eval/runner.py`)뿐이다.

**아직 없는 부분**: `term_consistency`, `abbr_accuracy`,
`build_report()`(`app/eval/report.py`)는 전부 `NotImplementedError`를
던지는 스텁이며, chrF/COMET을 계산할 라이브러리(`sacrebreu`,
`unbabel-comet`)는 `requirements-tools.txt`에 반입돼 있지만 아직
어떤 코드도 이를 import하지 않는다.

### 22.4 회귀 테스트 실행 형태 (계획, §12.3)

```bash
python -m app.eval.runner \
  --goldenset data/goldenset.jsonl \
  --backend gemma4-26b \
  --prompt-version ko2en-press-v3 \
  --compare-with ko2en-press-v2
```

`--prompt-version`/`--compare-with`가 요구하는 값은 `app/pipeline/prompt.py`의
`PromptBuilder.version()`이 이미 생성하고 있는 `PromptVersion.id`
(예: `"ko2en-press-v1"`)와 정확히 대응한다 — 즉 버전 추적 인프라는
Phase 0/2에서 이미 완성됐고, 이를 소비하는 비교 러너만 Phase 3에
남아 있다.

### 22.5 모델 후보 비교 설계 (§8.3)

평가는 5개 후보 + 기준선 1개로 설계돼 있으며, 각 비교가 **답하려는
질문**이 명시적이다 — 임의 벤치마크가 아니라 가설 검증형 설계다.

| 후보 | 답하려는 질문 |
|---|---|
| Gemma 4 26B-A4B (A) | 주 후보. MoE로 처리량 유리 |
| Qwen3-30B-A3B (B) | 계열 간 한↔영 군사 용어 우열 (A vs B) |
| A.X 4.0 Light 7B (C) | 한국어 특화 + 소형으로 충분한가 (A vs C) — 현재 개발 환경에서 배선 검증에 실사용 중인 모델 |
| TranslateGemma 12B (D) | 범용 vs 번역 특화 (A vs D) — **계획서가 "가장 중요한 비교"로 명시** |
| Gemma 4 E4B (E) | 개발 환경(6GB) 검증용 |
| NLLB-1.3B | 기준선 대조군(라이선스 검토 후) |

A(범용 LLM) vs D(전용 번역 모델 TranslateGemma)의 비교가 핵심인 이유는
D-08 결정("범용 LLM 단일 구성, 전용 MT는 비교군")과 직결된다 — 이
프로젝트가 범용 LLM을 주력으로 택한 근거(L40S 여유 + 용어집 구축에
범용 LLM 필수)가 실제로 맞는지 이 비교로 검증하는 구조다.

### 22.6 재호출과 평가의 관계 — 정량적 개선 확인 포인트

Phase 4 완료 기준(§11)에 "재호출 후 용어 준수율이 재호출 전보다
유의미하게 개선"이 명시돼 있다. 즉 `orchestrator.py`의 재호출 로직
(§6.5, 최대 1회)이 실제로 품질을 올리는지도 같은 용어 준수율 지표로
검증하도록 설계돼 있다 — 재호출 로직과 평가 지표가 같은 측정 도구
(`verify()`/`term_compliance_rate()`)를 공유하는 구조.

---

## 23. 참고 문서

- [docs/military-translator-plan.md](military-translator-plan.md) — 설계 정본. 아키텍처·데이터
  스키마·리스크·단계별 계획의 근거가 전부 여기 있다.
- [docs/phase0-notes.md](phase0-notes.md) — 계획 대비 실제 구현 차이(D-20~D-24), 에어갭
  wheel 문제 해결 기록.
- [docs/phase2-notes.md](phase2-notes.md) — 매칭 엔진 구현 중 발견된 계획서 오류 수정 기록
  (좌표계 분리, 검증 방향 버그, abbr_policy 무시 버그 등).
- [README.md](../README.md) — 실행 방법, 환경변수 목록, 지켜야 할 원칙 5가지.
