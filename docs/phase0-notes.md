# Phase 0 실행 기록 — 확인된 사실과 계획서 수정 필요 사항

| 항목 | 내용 |
|---|---|
| 작성 | 2026-08-19 |
| 대상 | 계획서 v0.2 (`docs/military-translator-plan.md`) |
| 성격 | Phase 0 을 실제로 돌려보며 드러난 것들. 계획서 §1 / §10 갱신 근거 |

이 문서는 계획서를 대체하지 않는다. **계획서와 다르게 구현한 부분과 그 이유**,
그리고 **계획서가 틀렸거나 성립하지 않는 부분**만 적는다.

---

## 1. 버전 정책 변경 (D-20 제안)

사용자 지시로 `mars-ai-server/requirements.txt` 와 겹치는 라이브러리는 그쪽
버전을 정본으로 삼았다. 계획서 §10 의 값과 다른 항목은 다음과 같다.

| 라이브러리 | 계획서 §10 | mars-ai-server | 적용 |
|---|---|---|---|
| fastapi | 0.115.6 | 0.115.6 | 동일 |
| uvicorn[standard] | 0.34.0 | 0.34.0 | 동일 |
| pydantic | 2.10.4 | 2.10.4 | 동일 |
| kiwipiepy | 0.20.4 | **0.22.2** | 0.22.2 |
| torch | 2.5.1 | **2.8.0** | 2.8.0 |
| transformers | 4.48.0 | **4.57.1** | 4.57.1 |
| vllm | 0.7.2 | **0.11.0** | 0.11.0 |

> **§1 결정 로그에 D-20 으로 추가할 것.**
> 근거: 두 프로젝트가 같은 폐쇄망 서버를 공유할 가능성이 있고, 서빙 스택
> (torch/vllm/transformers)이 갈리면 번들이 두 벌이 된다.

`mars-ai-server` 가 함께 고정한 전이 의존성(`tokenizers==0.22.1`,
`triton==3.5.0`, `torchvision`, `torchaudio`)은 계획서 §10 에 없는 항목이라
임의로 추가하지 않았다. `requirements-serve.txt` 에 주석으로만 남겼다.

### 1-b. 신규 의존성 (D-23, 승인됨)

| 패키지 | 사유 | 상태 |
|---|---|---|
| `pyyaml==6.0.3` | §4.2 와 §7.3 이 문체 프리셋을 `.yaml` 로 규정하는데 §10 에 파서가 없었다 | **승인 2026-08-19** |

`uvicorn[standard]` 의 전이 의존성으로 이미 설치되므로 반입 번들이 커지지
않는다. 명시적으로 고정만 했다. **§10.1 에 추가할 것.**

### 1-c. 결정 로그에 추가할 항목

Phase 0 에서 확정된 것들이다. 계획서 §1 에 옮길 것.

| # | 결정 | 근거 |
|---|---|---|
| D-20 | mars-ai-server 와 겹치는 라이브러리는 그쪽 버전을 정본으로 함 | 같은 폐쇄망 서버를 공유할 가능성. 서빙 스택이 갈리면 번들이 두 벌이 된다 |
| D-21 | `kiwipiepy_model` 은 개발망에서 wheel 로 빌드해 번들에 넣음 | PyPI 에 wheel 이 없고, sdist 는 폐쇄망 설치 시 빌드 의존성을 받으러 나간다 (§2-a) |
| D-22 | 문장 분할을 `kss` → `Kiwi.split_into_sents()` 로 교체 | kss 가 sdist 3개 포함 34개 의존성을 끌고 온다. Kiwi 는 이미 쓰며 용어집 사전을 공유한다 (§2-b) |
| D-23 | `pyyaml` 을 §10.1 에 추가 | 문체 프리셋 파서 |
| D-24 | 백엔드를 `OpenAICompatBackend` 하나로 통합 (vLLM · llama.cpp 공용) | 둘이 같은 `/v1/chat/completions` 프로토콜을 쓴다 (§5) |

---

## 2. 에어갭 문제: wheel 이 없는 패키지들

계획서 §10.6 은 `pip download --only-binary=:all:` 로 번들을 만든다고 되어
있다. **다음 패키지들이 그 명령에서 실패한다.**

### 2-a. `kiwipiepy_model` — 해결됨

| 사실 | 내용 |
|---|---|
| 배포 형태 | sdist(.tar.gz) 만 있음. wheel 없음 |
| 크기 | 79 MB (압축), 99 MB (해제) |
| 내용 | 순수 데이터 + `get_model_path()` 뿐. **컴파일 확장 없음** |
| 빌드 백엔드 | `pyproject.toml` 없음 (레거시 setup.py) |
| 라이선스 | LGPL v3 (kiwipiepy 본체와 동일) |
| 요구 버전 | kiwipiepy 0.22.2 → `kiwipiepy_model>=0.22,<0.23` → **0.22.1** |

계획서가 `kiwipiepy-model==0.20.0` 으로 적어둔 값은 kiwipiepy 0.20.4 짝이라
D-20 적용 후에는 맞지 않는다.

**sdist 를 그대로 반입하면 안 되는 이유**: `pyproject.toml` 이 없어 pip 이 빌드
격리 환경을 만들면서 setuptools/wheel 을 **내려받으러 나간다.** 폐쇄망에서 터진다.

**채택한 방법 (사용자 승인)**: 개발망에서 wheel 로 미리 빌드해 번들에 넣는다.

```bash
pip wheel kiwipiepy_model==0.22.1 -w bundle/kiwi/ --no-deps
#  → kiwipiepy_model-0.22.1-py3-none-any.whl   (검증 완료)
```

순수 데이터 패키지라 결과가 `py3-none-any` 이고, **Windows 개발망에서 만들어도
Linux 폐쇄망에 그대로 설치된다.** 계획서 §9.2 의 `kiwi/kiwipiepy_model-*.whl`
레이아웃과 정확히 일치한다.

### 2-b. `kss` 제거 — 해결됨 (D-22)

계획서 §10.2 가 "Phase 0 에서 의존성 트리를 확인하십시오" 라고 지시한 항목이다.
확인 결과는 다음과 같다.

| 항목 | 결과 |
|---|---|
| `kss==6.0.4` | **해당 플랫폼 wheel 없음.** 6.0.5 가 wheel 이 있는 최소 6.0.x |
| 의존 패키지 수 | 34개 |
| wheel 없는 것 | `pecab==1.0.8`, `tossi==0.3.1`, `Distance==0.1.3` |
| 딸려오는 무거운 것 | `pyarrow`, `scipy`, `numpy`, `networkx`, `whoosh`, `bs4`, **`pytest`** |

문장 분할기 하나 때문에 런타임 번들에 `pyarrow` 와 `pytest` 가 들어간다.

**채택한 방법 (사용자 승인)**: `kiwipiepy` 의 `Kiwi.split_into_sents()` 를 쓴다.

- §6.3 이 이미 Kiwi 풀을 요구하므로 **새 의존성이 0개**다.
- 용어집 사용자 사전이 문장 분할에도 적용된다. 부대명 중간에서 끊기는 사고가 준다.
- `kss` 와 그 34개 의존성이 통째로 사라진다. sdist 문제 3건도 함께 사라진다.
- 영어 문장 분할은 어차피 둘 다 다루지 않는다. 규칙 기반 분할기가 `en2ko` 를
  담당한다.

구현: `app/glossary/morph.py` (분석기 + 풀), `app/pipeline/segment.py`
(`analyzer` 인자), `app/glossary/index.py` (기동 시 풀 생성).

동작 확인 (`tests/test_morph.py`):

| 입력 | 결과 |
|---|---|
| `장비 3.5t 을 옮겼다. 훈련이 끝났다.` | 2문장 — 소수점에서 안 끊긴다 |
| `제7기동군단 예하 제20기계화보병사단이 참가했다.` | 1문장 — 부대명에서 안 끊긴다 |
| `제20기계화보병사단에서는` | `제20기계화보병사단/NNP + 에서/JKB + 는/JX` |

**폴백**: `kiwipiepy` 가 없거나 `NDT_USE_KIWI=false` 면 규칙 기반 분할기로
떨어지고 서비스는 계속된다. `/health` 의 `segmenter` 필드가 어느 쪽인지 알려준다.
문장 분할이 조금 나빠지는 것보다 번역기가 안 뜨는 편이 나쁘다.

§6.2 를 이 내용으로 갱신할 것.

---

## 3. 번들은 반드시 Linux 에서 생성할 것

`requirements.lock.txt` 를 Windows 개발망에서 만들었더니 **`uvloop` 이 빠졌다.**

pip 의 `--platform` 은 wheel 의 플랫폼 태그만 바꾸고, 환경 마커
(`sys_platform != 'win32'`)는 **현재 인터프리터 기준으로 평가한다.**
`uvicorn[standard]` 는 `uvloop` 을 그 마커로 걸어두었으므로 Windows 에서
생성한 번들에는 조용히 누락된다. 설치는 성공하고 서버도 뜨지만 asyncio 기본
루프로 떨어진다.

계획서 §10.6 은 "플랫폼을 폐쇄망 서버와 일치시켜야 함" 이라고만 적혀 있는데,
플랫폼 태그가 아니라 **생성 호스트의 OS** 문제다. 다음 문장을 §10.6 에 넣을 것.

> 번들 생성은 폐쇄망 서버와 같은 OS 에서 수행한다. `--platform` 만으로는
> 조건부 의존성이 누락된다. 컨테이너를 쓰면 다음과 같다.
> ```bash
> docker run --rm -v "$PWD:/w" -w /w python:3.11-slim \
>   pip download -r requirements-core.txt -r requirements-nlp.txt \
>     --only-binary=:all: -d bundle/wheels/
> ```

---

## 4. 계획서 코드 예시의 오류

### 4-a. §6.5 검증 코드 — 정상 번역을 위반으로 잡는다

계획서 §6.5 의 예시는 다음과 같다.

```python
norm_tgt = normalize_key(tgt, direction)
if not any(normalize_key(e, direction) in norm_tgt for e in expected):
```

`normalize_key(text, direction)` 은 §6.3 정의상 **그 방향의 원문 언어** 규칙이다
(ko2en 이면 한국어 규칙: 공백 전부 제거, 소문자화 없음). 그런데 위 코드는 그것을
**번역문**에 적용한다. 번역문은 반대 언어다.

실제로 깨지는 사례:

| 방향 | 번역문 | 기대 대역어 | §6.5 코드 결과 |
|---|---|---|---|
| ko2en | `the joint chiefs of staff said` | `Joint Chiefs of Staff` | **위반으로 오판** (소문자화 안 함) |
| en2ko | `합동 참모 본부는 밝혔다` | `합동참모본부` | **위반으로 오판** (공백 유지) |

용어 준수율(§12.1 주 지표)이 직접 오염되고, 재호출(§6.5)이 불필요하게 돌아
처리량까지 깎인다.

**수정**: `app/glossary/matcher.py` 에 `target_key(text, direction)` 를 두었다.
방향을 뒤집어 타깃 언어 규칙을 적용한다. `tests/test_verify.py` 가 위 두 사례를
회귀 테스트로 잡고 있다.

### 4-b. §9.5 오프라인 테스트 — 그대로 쓰면 테스트가 돌지 않는다

계획서 §9.5 예시는 `socket.socket` 자체를 차단한다. asyncio 이벤트 루프가
자기 깨우기용으로 로컬 소켓을 쓰기 때문에(특히 Windows) 이대로면 테스트
프레임워크가 먼저 죽는다.

**수정**: `tests/test_offline.py` 는 **루프백 밖으로 나가는 연결과 외부 이름
해석**만 막는다. 에어갭에서 문제가 되는 것은 외부 접근이고(§9.3), 폐쇄망 내
vLLM 호출은 허용되어야 하므로 의미도 이쪽이 맞다. 가드가 실제로 동작하는지는
`test_guard_actually_blocks` 가 먼저 확인한다.

여기에 더해 **§9.3 금지 패턴 정적 검사**를 넣었다. `app/` 의 주석과 문자열
리터럴을 걷어낸 뒤 실제 호출만 본다.

---

## 5. 백엔드를 하나로 통합 (D-24)

계획서 §4.2 는 `backends/vllm_openai.py` 를 두고 Phase 3 에서 구현한다고 되어
있다. 그런데 **llama.cpp 서버가 vLLM 과 같은 `/v1/chat/completions` 프로토콜을
쓴다.** 구현을 나눌 이유가 없어 `OpenAICompatBackend` 하나로 합쳤다.

| `NDT_BACKEND` | 대상 |
|---|---|
| `mock` | 모델 없이 배선만 확인 (§3.1) |
| `llamacpp` | 개발 환경. RTX 4050 6GB 에는 vLLM 보다 적합하다 (§8.2) |
| `vllm` | 운영 (L40S) |
| `openai` | 위 둘의 공통 이름 |

파일 경로와 `VLLMOpenAIBackend` 이름은 §4.2 를 지키려고 별칭으로 남겼다.

### 5-a. 개발 환경 실측 (2026-08-19)

llama.cpp 가 `skt/A.X-4.0-Light` (GGUF, 7.26B, n_ctx 12288) 를 8000 포트에
서빙 중인 상태에서 확인했다. §8.3 의 평가 후보 **C** 다.

**이 수치는 품질 평가가 아니다.** 개발 환경에서는 모델 품질을 평가하지 않는다
(§3.1). 배선이 도는지만 본 것이다.

| 항목 | 결과 |
|---|---|
| 기동 (용어집 20건 + Kiwi 풀 2개) | 1,275 ms |
| 1청크 번역 | 약 2,000~4,100 ms |
| 2문단 → 2청크 분할 · 결합 | 정상. 문단 경계 복원됨 |

**용어집 없이 돌린 기준선** (§12.2 의 `noterm` 모드에 해당). Phase 2 매칭이
없어 용어가 하나도 주입되지 않은 상태다.

| 원문 | A.X 출력 | 용어집 지정 | 판정 |
|---|---|---|---|
| `The JCS` | 국방 | 합동참모본부 / 합참 | ✗ |
| `combined exercise` | 합동훈련 | 연합훈련 | ✗ |
| `연합훈련` | joint training exercise | combined exercise | ✗ |
| `제20기계화보병사단` | 20th Mechanized Infantry Division | 동일 | ✓ |
| `국방부` | Ministry of National Defense | 동일 | ✓ |

`연합훈련`(다국적)과 `합동훈련`(다군종)을 양방향으로 혼동했고, `JCS` 는
"국방" 으로 잘못 풀었다. **Phase 2 의 용어 주입이 정확히 이 오류를 겨냥한다.**
Phase 3 에서 골든셋으로 `noterm` / `proper` 를 비교할 때 이 사례들을 포함할 것.

---

## 6. 계획서 §4.2 에 없어서 추가한 것

| 경로 | 사유 |
|---|---|
| `app/main.py` | ASGI 진입점이 §4.2 에 없다. `uvicorn app.main:app` 으로 띄운다 |
| `app/api/deps.py` | 엔드포인트 공용 의존성. `app.state` 접근을 한곳에 모았다 |
| `pyproject.toml` | pytest / ruff / mypy 설정. 의존성은 여기 적지 않았다 |
| `requirements.lock.txt` | §10.6 산출물 |
| `.env.example` / `.env` | 설정 예시와 로컬 설정. `.env` 는 git 제외 |
| ~~`.github/workflows/ci.yml`~~ | §9.5 자동 강제용이었으나 2026-08-23 제거. 수동 실행으로 전환 |
| `tools/README.md` | 각 도구의 단계와 선행 조건 |
| `docs/phase0-notes.md` | 이 문서 |

---

## 7. 여전히 막혀 있는 것

Phase 0 은 끝났지만 다음이 확정되어야 다음 단계가 열린다.

| # | 항목 | 막는 것 |
|---|---|---|
| O-01 | 용어집 검수 인력 | Phase 1 전체 |
| O-02 | 확보 용어집의 형태 | `tools/glossary_import.py` 파서 |
| O-03 | 확보 용어집 규모 | Phase 1 일정 |
| O-04 | 동시 접속자 수 | 워커 수, 세마포어 상한 (R-12) |
| O-05 | 반입 절차·주기 | Phase 5, 핫리로드 필수 여부 |
| O-06 | 폐쇄망 OS / CUDA | `requirements-serve.txt` 잠금 |
| O-07 | 인증 방식 | `/admin/reload` 활성화 (현재 기본 비활성) |
| O-08 | TTS/STT 범위 | — |
| O-09 | 모델 원산지 규정 | Qwen3 후보 유지 여부 |

추가로 확인이 필요한 것:

- **프론트 연동 확인 (Phase 0 작업 6)** — `llm-frontend/src/pages/TranslatePage.tsx`
  가 기대하는 요청/응답 형태를 대조하지 못했다. 백엔드는 계획서 §4.4 를 그대로
  구현했다. 실제 화면에 붙여 확인하는 절차가 남아 있다.
- **계획서 반영** — D-20 ~ D-24 를 §1 결정 로그에, `pyyaml` 을 §10.1 에,
  Kiwi 문장 분할을 §6.2 에, 번들 생성 호스트 조건을 §10.6 에 옮길 것.
