# NeuroDomain-Translate

군사 도메인 한↔영 번역기. 용어집 기반으로 전문 용어의 대역을 강제하고, 폐쇄망
(에어갭)에서 운영한다.

- 설계: [docs/military-translator-plan.md](docs/military-translator-plan.md) — **정본**
- 실행 기록 — 계획서와 다르게 구현한 부분, 계획서가 성립하지 않는 부분:
  [Phase 0](docs/phase0-notes.md) · [Phase 2](docs/phase2-notes.md)

## 현재 상태

**Phase 0 · 2 완료.** 용어집 기반 매칭과 주입이 동작하고, 실제 모델로 번역이 된다.

| 단계 | 내용 | 상태 |
|---|---|---|
| Phase 0 | 골격, mock 백엔드, SQLite, 오프라인 CI | ✅ |
| Phase 1 | 용어집 구축 | ⛔ O-01·O-02·O-03 확정 필요 |
| Phase 2 | 매칭 엔진 (Aho-Corasick + Kiwi) | ✅ |
| Phase 3 | 모델 평가 (L40S) | ⛔ O-06 확정 필요 |
| Phase 4 | 검증 루프, 처리량 | 부분 (재호출 구현, 부하 테스트 미실시) |
| Phase 5 | 에어갭 배포 | ⛔ O-05·O-06 확정 필요 |

> **`data/` 는 전부 합성 샘플이다.** 엔진은 완성됐지만 실제 번역 품질은 Phase 1
> 의 데이터가 들어와야 의미가 생긴다.
>
> | 자산 | 현재 | 목표 |
> |---|---|---|
> | `glossary.jsonl` | 샘플 20건, `verified` 0건 | 검수 500건 이상 (Phase 1) |
> | `tm.jsonl` | 샘플 15쌍 | 10,000쌍 이상 (Phase 1) |
> | `goldenset.jsonl` | 샘플 20건 | 실제 문장 50건, 사람 검수 (Phase 3) |
>
> 전부 `quality: "sample"` 로 표시했고 테스트가 `verified` 로 둔갑하는 것을 막는다.
> **이 샘플로 낸 chrF / COMET 점수를 품질 지표로 인용하지 말 것.**
> 용어 준수율만은 의미가 있다 — 참조문이 용어집 대역어를 쓰고 있어
> "지정 대역어가 반영됐는가" 는 정직하게 잰다.

### 용어 주입 효과 (A.X 4.0 Light, 샘플 용어집 20건)

같은 모델에 용어집만 붙였을 때의 차이다. 계획서 §12.2 의 `noterm` / `proper`
비교에 해당한다.

| 원문 | 용어집 없음 | 용어집 적용 |
|---|---|---|
| 연합훈련 | joint training exercise ✗ | combined exercise ✓ |
| The JCS | 국방 ✗ | 합동참모본부 ✓ |
| combined exercise | 합동훈련 ✗ | 연합훈련 ✓ |
| 해군 … 대령 | COL Kim ✗ | Captain Kim ✓ |

`연합`(다국적)과 `합동`(다군종)을 양방향으로 혼동하던 것이 교정된다.
이것이 이 프로젝트가 존재하는 이유다.

## 개발 환경

Python 3.11 (반입 번들과 같은 버전이어야 한다). Windows / Linux 둘 다 된다.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements-core.txt -r requirements-nlp.txt -r requirements-dev.txt
copy .env.example .env
```

**Linux / macOS**

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements-core.txt -r requirements-nlp.txt -r requirements-dev.txt
cp .env.example .env
```

`requirements-nlp.txt` 설치에는 시간이 걸린다. `kiwipiepy-model` 이 79MB 이고
PyPI 에 wheel 이 없어 sdist 를 빌드한다 (D-21). 이것 없이 코어만 깔아도
서비스는 돌지만 문장 분할이 규칙 기반으로 떨어진다.

`requirements-serve.txt`(torch / vLLM)는 Phase 3 에서 L40S 서버에만 깐다.
개발 환경에서는 llama.cpp 를 쓴다 — vLLM 은 KV 캐시를 미리 크게 잡아 6GB 카드에
맞지 않는다 (§8.2).

## 설정

`.env` 로 설정한다. [.env.example](.env.example) 을 복사해서 쓰면 되고,
전체 항목은 [app/config.py](app/config.py) 에 있다. `.env` 는 git 에서 제외된다.

환경변수 `NDT_*` 가 `.env` 보다 우선한다.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `NDT_PORT` | `8080` | 서버 포트 |
| `NDT_LOG_LEVEL` | `INFO` | `DEBUG` 면 청크별 호출까지 나온다 |
| `NDT_BACKEND` | `mock` | `mock` \| `llamacpp` \| `vllm` \| `openai` |
| `NDT_VLLM_BASE_URL` | `http://127.0.0.1:8000/v1` | 모델 서버. **폐쇄망 내부 주소만** |
| `NDT_VLLM_SERVED_NAME` | (자동) | 비우면 `/v1/models` 첫 항목 |
| `NDT_PROMPT_PRESET` | `full` | `full` \| `compact` (§7.9) |
| `NDT_USE_KIWI` | `true` | false 면 규칙 기반 문장 분할 |
| `NDT_MAX_INPUT_CHARS` | `5000` | 입력 상한 (D-05) |
| `NDT_ADMIN_ENABLED` | `false` | `/admin/reload`. **O-07 확정 전까지 켜지 말 것** |
| `NDT_LOG_TEXT` | `true` | 원문·번역문을 로그에 남길지 |
| `NDT_LENGTH_CHECK_MIN_CHARS` | `40` | 환각 탐지 하한 (아래 참조) |

### 환각 · 누락 경고

원문에 내용이 없으면 모델이 문서를 지어낸다. 실제로 `"string"` 한 단어를 넣었을
때 국방 예산안 보도자료가 통째로 나온 적이 있다 — 금액, 계급, 발언까지.

출력/원문 길이 비율과 타깃 언어 문자 유무로 잡아 응답의 `warnings` 에 싣는다.

```jsonc
{"type": "length_anomaly", "kind": "expansion", "chunk": 0,
 "src_chars": 3, "tgt_chars": 174, "ratio": 58.0}
{"type": "wrong_language", "chunk": 0}
```

> ⚠ **이 경고는 아직 화면에 보이지 않는다.** API 는 반환하지만 프론트에 표시
> 위치가 없다. 지금은 API 응답과 로그로만 확인할 수 있다.
> 자세한 경위는 [phase2-notes §9](docs/phase2-notes.md) 참조.

## 로그

모든 모듈이 [app/logging.py](app/logging.py) 의 `get_logger` 를 쓴다.
진입점에서 `setup_logging()` 을 부르면 uvicorn · httpx 로그까지 같은 포맷이 된다.

```
[07:56:23.891] INFO app.pipeline.orchestrator: [1580d8eb] 번역 시작: ko2en, 74자, style=press_release, prompt=ko2en-press-v1
[07:56:25.745] INFO app.pipeline.orchestrator: [1580d8eb] 분할: 2청크 (분할기=kiwi)
[07:56:27.481] INFO app.pipeline.orchestrator: [1580d8eb] 사전분석: 용어 6건 [T-0142, T-0301, …], 군종=미확정, 미등록후보 1건, TM예시 2청크, 1733ms
[07:56:27.489] DEBUG app.pipeline.orchestrator: [1580d8eb] 청크 1/2 호출: 53자, 용어 5건 (TM 3건)
[07:56:32.293] DEBUG app.pipeline.orchestrator: [1580d8eb] 청크 1 응답: 146자, 4800ms
[07:56:32.295] INFO app.pipeline.orchestrator: [1580d8eb] 미등록 용어 후보 1건: 천무-II
[07:56:32.295] INFO app.pipeline.orchestrator: [1580d8eb] 번역 완료: 74자 → 210자, 청크 2, 재호출 0, 경고 1, 8404ms
[07:56:32.296] DEBUG app.store.runtime: [1580d8eb] translation_logs 기록: ko2en, 용어 6건, 위반 0건
```

`[1580d8eb]` 는 **요청 id** 다. 동시 요청이 최대 16개까지 섞이므로(§6.6) 이걸로
한 요청을 처음부터 끝까지 골라낼 수 있다. `data/runtime.db` 의
`translation_logs.id` 앞 8자와 같으므로, 콘솔 한 줄에서 DB 행을 바로 찾는다.

```sql
SELECT * FROM translation_logs WHERE id LIKE '1580d8eb%';
```

환각 · 누락 탐지는 `WARNING` 으로 나온다.

```
[07:56:36.085] WARNING app.pipeline.orchestrator: [dd257e03] 길이 이상(expansion): 청크 0, 원문 3자 → 출력 171자 (57.0배). 환각 또는 누락 가능성
```

## 실행

### mock 백엔드 (모델 불필요)

배선 확인용이다. **번역 품질 평가에 쓰지 말 것** (§3.1).

```bash
NDT_BACKEND=mock uvicorn app.main:app --port 8080
```

### 실제 모델 (llama.cpp)

llama.cpp 서버를 먼저 띄운다.

```bash
llama-server -m /path/to/model.gguf --port 8000 --ctx-size 8192
```

`.env` 에서 백엔드를 가리킨다.

```ini
NDT_BACKEND=llamacpp
NDT_VLLM_BASE_URL=http://127.0.0.1:8000/v1
```

```bash
uvicorn app.main:app --port 8080
```

vLLM 도 같은 설정으로 붙는다 — 프로토콜이 같아서 구현이 하나다 (D-24).

### 호출

```bash
curl http://localhost:8080/health

curl -X POST http://localhost:8080/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"합참은 훈련을 참관했다고 밝혔다.","source":"ko","target":"en"}'
```

기동 직후에는 `/health` 가 `ready: false` 를 반환한다. 인덱스와 Kiwi 풀이
준비돼야 `/translate` 가 200 을 준다 (그전에는 503).

`/health` 응답의 `segmenter` 가 `kiwi` 인지 `rule` 인지, `model` 이 무엇인지
확인하면 지금 무엇으로 돌고 있는지 알 수 있다.

## 테스트

```bash
pytest tests/ -v
ruff check .
ruff format --check .
```

Windows 에서도 그대로 돈다. 모델 서버나 GPU 가 없어도 전부 통과한다 —
없는 것에 의존하는 테스트는 skip 된다.

| 파일 | 담당 | 없으면 |
|---|---|---|
| `test_offline.py` | **에어갭 검증** (§9.5, R-02) | — |
| `test_matcher.py` | 매칭. **§11 Phase 2 수용 케이스 7건** + 성능 기준 | pyahocorasick 없으면 skip |
| `test_analyze.py` | 전역 사전분석, 군종 판정, 5,000자 200ms 기준 | pyahocorasick 없으면 skip |
| `test_orchestrator.py` | 검증 · 재호출, 다의어, 약어 정책 | pyahocorasick 없으면 skip |
| `test_morph.py` | Kiwi 문장 분할, 용어집 사용자 사전 | kiwipiepy 없으면 skip |
| `test_tm.py` | TM 로드, BM25 검색 | rank-bm25 없으면 일부 skip |
| `test_goldenset.py` | 골든셋 구성, **샘플 표시 유지**, TM 오염 검사 | — |
| `test_prompt.py` | §7 층 순서, 세 블록 분리, 프리셋 | — |
| `test_backend_openai.py` | 백엔드 (httpx MockTransport) | — |
| `test_backend_live.py` | 실제 모델 서버 연동 | 서버 없으면 skip |

`test_offline.py` 는 외부 연결·이름 해석을 차단한 상태에서 파이프라인을 돌리고,
`app/` 에 §9.3 금지 패턴이 있는지 정적으로도 검사한다. CI 에서 매 커밋 실행된다.

실제 모델로 확인하려면 서버를 띄운 뒤:

```bash
pytest tests/test_backend_live.py -v -s
```

## 구조

```
app/
├─ api/         /translate, /health, 스키마
├─ pipeline/    정규화 → 분할 → 사전분석 → 프롬프트 → 검증 → 조율
├─ glossary/    용어집 로드, 인덱스, 매칭
├─ tm/          번역 메모리
├─ store/       SQLite (로그, 미등록 용어 후보)
├─ backends/    mock / vLLM
└─ eval/        평가 지표 (Phase 3)

prompts/        Jinja2 템플릿 + 문체 프리셋
data/           glossary.jsonl, tm.jsonl (반입 대상) / runtime.db (git 제외)
tools/          오프라인 배치 도구 — 개발망 전용, 반입하지 않음
```

미구현 모듈에는 **어느 단계에서 구현하는지**가 docstring 에 적혀 있다.

## 지켜야 할 것

이 저장소에서 작업하는 사람과 LLM 에이전트 모두에게 해당한다.
자세한 내용은 계획서 §0.2 를 볼 것.

1. **런타임에 네트워크를 쓰는 코드를 넣지 말 것** (§9.3). 모델은 로컬 절대경로로
   지정한다. `from_pretrained("org/model")`, `snapshot_download`, `nltk.download`,
   `requests.get` 등은 CI 가 잡는다.
2. **계획서 §10 에 없는 라이브러리를 추가하지 말 것.** 필요하면 사람에게 승인을
   받고 §10 에 버전과 함께 적는다.
3. **§2 미확정 항목(O-01~O-09)을 추정으로 결정하지 말 것.** 값이 필요하면 멈추고
   물어본다.
4. **`data/glossary.jsonl` 의 `source` 와 `confidence` 를 비우지 말 것.** 나중에
   대역이 충돌할 때 어느 쪽을 신뢰할지 판단하는 유일한 근거다.
5. 코드 경로는 계획서 §4.2 를 그대로 쓴다.

> 현재 `data/glossary.jsonl` 은 **Phase 0 배선 검증용 샘플 20건**이다.
> `confidence` 가 `verified` 인 항목이 하나도 없고 `corpus_freq` 는 전부 0 이다.
> Phase 1 에서 통째로 교체한다.
