# 군사 도메인 한↔영 번역기 개발 계획서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.2 (초안) |
| 최종 수정 | 2026-08-19 |
| 문서 성격 | 내부 작업 문서 (사람 + LLM 공동 참조) |
| 상태 | 착수 전 |

---

## 0. 이 문서를 읽는 방법

### 0.1 사람에게

- **§1 확정 사항**과 **§2 미확정 항목**을 먼저 읽으세요. 나머지는 이 두 절에서 파생됩니다.
- **§11 단계별 계획**이 실제 작업 순서입니다. 각 단계에 산출물과 완료 기준이 명시되어 있습니다.
- 결정을 바꾸실 때는 **§1의 결정 로그에 추가**하고, 영향받는 절을 함께 수정하세요.

### 0.2 LLM 에이전트에게

이 문서를 컨텍스트로 받아 작업하는 LLM은 다음 규칙을 따릅니다.

1. **§2에 있는 항목은 임의로 결정하지 마십시오.** 해당 값이 필요하면 작업을 중단하고 사람에게 질문하십시오.
2. **§9 에어갭 제약을 위반하는 코드를 작성하지 마십시오.** 런타임에 네트워크에 접근하는 라이브러리 호출은 전부 금지입니다. 판단이 서지 않으면 §9.3 금지 패턴 목록을 확인하십시오.
3. **§10에 없는 라이브러리를 추가하지 마십시오.** 새 의존성이 필요하면 사람에게 승인을 요청하고, 승인 시 §10에 버전과 함께 추가하십시오.
4. **§10의 버전을 임의로 올리거나 내리지 마십시오.** 버전은 반입 번들과 1:1로 대응합니다.
5. 코드를 작성할 때는 **§4 모듈 구조**의 경로를 그대로 사용하십시오.

### 0.3 용어 정의

| 용어 | 의미 |
|---|---|
| 용어집 (Glossary) | 한↔영 대역이 확정된 전문 용어 사전. `glossary.jsonl`로 관리 |
| TM (Translation Memory) | 과거 번역 문장 쌍 저장소. few-shot 예시 공급용 |
| 청크 (Chunk) | 번역 요청 1건을 나눈 처리 단위 (3~5문장, ~800자) |
| 매칭 (Matching) | 원문에서 용어집 표제어를 찾아내는 과정 |
| 주입 (Injection) | 매칭된 용어를 프롬프트에 삽입하는 과정 |
| 검증 (Verification) | 번역문에 지정 용어가 반영됐는지 확인하는 과정 |
| 용어 준수율 | 원문에 등장한 용어가 지정 대역어로 번역된 비율. 주 품질 지표 |
| 골든셋 | 사람이 검수한 정답 번역 쌍. 회귀 테스트용 |
| 반입 번들 | 폐쇄망으로 옮길 오프라인 아티팩트 묶음 |

---

## 1. 확정 사항 (결정 로그)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| D-01 | 도메인 | 군사/국방 | 사용자 확정 |
| D-02 | 언어쌍 | 한국어 ↔ 영어 양방향 | 사용자 확정 |
| D-03 | 자료 등급 | 공개 자료만 취급 (비밀 없음) | 사용자 확정 |
| D-04 | 주 텍스트 유형 | 보도자료·공지사항 중심, 범용 사용 | 사용자 확정 |
| D-05 | 입력 형태 | 텍스트 붙여넣기 (최대 5,000자). 문서 업로드 없음 | 프론트 확정 |
| D-06 | 스트리밍 | 불필요. 요청-응답 방식, 수 초~수십 초 허용 | 사용자 확정 |
| D-07 | 사용자 | 다수 공개 (부대 내) | 사용자 확정 |
| D-08 | 모델 계열 | 범용 LLM 단일 구성 (전용 MT는 비교군) | L40S 여유 + 용어집 구축에 범용 LLM 필수 |
| D-09 | 용어 매칭 | Aho-Corasick 정확 매칭 + 형태소 분석 교차검증. 임베딩 미사용 | 오탐이 오역을 강제하는 비대칭 위험 |
| D-10 | 용어 주입 | 청크별로 매칭된 용어만 프롬프트 삽입 | 전체 주입 시 컨텍스트 초과 및 주의 분산 |
| D-11 | TM 도입 | 용어집과 별도로 TM 구축, few-shot 예시로 활용 | WMT25 및 업계 RAG 표준 |
| D-12 | 프론트엔드 | 완성됨. 백엔드가 API 계약에 맞춤 | 기존 자산 |
| D-13 | 개발 환경 | RTX 4050 6GB + 인터넷 연결 | 사용자 확정 |
| D-14 | 운영 환경 | L40S 48GB ×2, **폐쇄망(에어갭)** | 사용자 확정 |
| D-15 | 라이선스 정책 | Apache 2.0 우선. NC 라이선스 모델 배제 | 군 기관 사용의 "상업성" 해석 불확실 |
| D-16 | 용어집 확보 | 확보 가능 (미정리 상태) | 사용자 확정 |
| D-17 | AI Hub | 국방 데이터 신청 가능 | 사용자 확정 |
| D-18 | 프롬프트 자동최적화 | 미도입 (DSPy/GEPA 등) | 용어 삽입 과제에서 수동 대비 유의미한 차이 없음 |
| D-19 | 데이터 저장 | **DB 서버 미사용.** 용어집·TM은 JSONL, 로그·후보 큐는 SQLite | 에어갭 반입 부담 제거, 용어집 git 버전관리, 규모가 DB를 요구하지 않음 |

---

## 2. 미확정 항목 — 결정 전까지 진행 불가

> **LLM 에이전트 주의**: 아래 항목은 추정하지 말고 사람에게 질문할 것.

| # | 항목 | 영향 범위 | 담당 |
|---|---|---|---|
| O-01 | 용어집 검수 인력 확보 여부 | Phase 1 전체. 검수자 없으면 자동화 비중과 신뢰도 정책 재설계 | |
| O-02 | 확보 용어집의 현재 형태 (엑셀/HWP/PDF/DB) | Phase 1 파서 구현 | |
| O-03 | 확보 용어집의 대략 규모 (항목 수) | Phase 1 일정 산정 | |
| O-04 | 예상 동시 접속자 수 / 일일 요청 수 | Phase 4 처리량 설계, 모델 크기 결정 | |
| O-05 | 폐쇄망 반입 절차 (매체, 승인, 주기) | Phase 5 배포 계획. **갱신 주기가 운영 설계를 좌우** | |
| O-06 | 폐쇄망 내 GPU 서버 OS 및 CUDA 버전 | §10 의존성 확정 | |
| O-07 | 인증 방식 (부대 SSO? 자체 계정? 없음?) | Phase 4 API 설계 | |
| O-08 | TTS/STT 실제 구현 여부 (프론트에 버튼 존재) | 범위 밖 여부 확정 필요 | |
| O-09 | 기관의 모델 원산지 관련 조달 규정 | Qwen3(중국계) 후보 유지 여부 | |

> **해소됨**: 구 O-07(폐쇄망 DB 설치 가능 여부)은 D-19로 불필요해졌습니다.
> SQLite는 Python 표준 라이브러리라 별도 설치가 없습니다.

---

## 3. 제약 조건

### 3.1 하드웨어

| 환경 | 사양 | 용도 |
|---|---|---|
| 개발 | RTX 4050 **6GB** (실질 가용 4.5~5GB) | 파이프라인 로직 개발, 연결 확인 |
| 운영 | L40S 48GB ×2 (NVLink 없음) | 모델 평가, 서비스 운영 |

**핵심 판단**: 개발 환경에서는 **모델 품질을 평가하지 않습니다.** 4bit 2B 모델의 결과는 FP8 26B 모델의 결과를 예측하지 못합니다. 개발 환경의 역할은 파이프라인이 끝까지 도는지 확인하는 것입니다.

**L40S는 NVLink가 없으므로** 모델 하나를 두 카드에 쪼개는 텐서 병렬(TP=2)은 PCIe 오버헤드가 큽니다. "48GB 독립 슬롯 두 개"로 설계합니다. Ada Lovelace 아키텍처라 FP8 네이티브 지원이 있어 양자화 손실이 작습니다.

### 3.2 네트워크 — 가장 중요한 제약

```
개발망 (인터넷 O)  ──[반입 번들]──▶  폐쇄망 (인터넷 X)
```

- 운영 환경은 **완전 에어갭**입니다. 런타임 다운로드가 일절 불가능합니다.
- 개발 중 무심코 쓴 자동 다운로드 코드는 **폐쇄망에서만 터집니다.** 개발망에서는 정상 동작하므로 발견이 늦습니다.
- 대응은 §9에 상술합니다.

### 3.3 입력

- 최대 5,000자 텍스트. 문서 업로드 없음.
- **문서 메타데이터가 없으므로** 군종(육/해/공) 판정을 입력 텍스트 내부 단서만으로 해야 합니다.
- **요청 간 상태가 없으므로** 약어 최초 등장 판정은 해당 요청 텍스트 범위 안에서만 유효합니다.

---

## 4. 시스템 아키텍처

### 4.1 처리 흐름

```
POST /translate
  │
  ├─ 1. 입력 검증        길이(≤5000), 방향(ko2en|en2ko)
  ├─ 2. 정규화           NFKC, 공백 정리, 서식 맵 생성
  ├─ 3. 분할             문장 분할 → 청크 구성 (문단 경계 유지)
  ├─ 4. 전역 사전분석  ──┐   텍스트 전체 1회 스캔
  │     · 용어 매칭      │   · 약어 등장 순서 확정
  │     · 조건 판정      │   · 군종 등 다의어 조건
  │     · TM 검색        │   · 유사 문장 few-shot 후보
  ├─ 5. 청크별 번역 ◀────┘   프롬프트 조립 → 모델 호출 (병렬)
  ├─ 6. 검증             용어 준수 확인 → 실패 청크만 재호출 (최대 1회)
  ├─ 7. 결합             서식 복원, 청크 경계 중복/누락 점검
  └─ 8. 응답             translation, terms_applied, warnings, meta
        └─ 비동기        미등록 용어 후보 큐 적재, 로그 기록
```

**4번을 5번보다 먼저 하는 것이 핵심입니다.** 청크를 나눠 번역하면 청크 간 일관성이 깨지는데, 전역 분석 결과를 모든 청크 프롬프트에 공유시켜 해결합니다.

### 4.2 모듈 구조

> LLM 에이전트는 이 경로를 그대로 사용할 것.

```
app/
├─ api/
│  ├─ __init__.py
│  ├─ translate.py          # POST /translate 엔드포인트
│  ├─ health.py             # 헬스체크, 모델 상태
│  └─ schemas.py            # 요청/응답 Pydantic 모델
├─ pipeline/
│  ├─ normalize.py          # 정규화, 서식 보존/복원
│  ├─ segment.py            # 문장 분할, 청크 구성
│  ├─ analyze.py            # 전역 사전분석
│  ├─ prompt.py             # 프롬프트 조립 (Jinja2)
│  ├─ verify.py             # 용어 준수 검증
│  └─ orchestrator.py       # 단계 조율, 동시성 제어
├─ glossary/
│  ├─ loader.py             # glossary.jsonl 로드/검증
│  ├─ index.py              # Aho-Corasick 인덱스 관리
│  ├─ matcher.py            # 방향별 매칭 로직
│  └─ morph.py              # 형태소 분석기 래퍼 (Kiwi 풀)
├─ tm/
│  ├─ loader.py             # tm.jsonl 로드
│  └─ retriever.py          # BM25 유사 문장 검색
├─ store/
│  ├─ runtime.py            # SQLite 커넥션, 로그/후보 큐 쓰기
│  └─ schema.sql            # 테이블 DDL (§5.4)
├─ backends/
│  ├─ base.py               # TranslationBackend 프로토콜
│  ├─ vllm_openai.py        # vLLM OpenAI 호환 API
│  └─ mock.py               # 테스트용 (GPU 불필요)
├─ eval/
│  ├─ metrics.py            # 용어 준수율, 일관성 등
│  ├─ runner.py             # 골든셋 회귀 테스트
│  └─ report.py             # 결과 비교 리포트
└─ config.py                # 설정 로딩 (환경변수)

prompts/
├─ ko2en/
│  ├─ system.j2
│  └─ retry.j2
├─ en2ko/
│  ├─ system.j2
│  └─ retry.j2
├─ analyze/
│  └─ service_classify.j2   # 군종 판정
└─ styles/
   ├─ press_release.yaml
   └─ default.yaml

data/                        # 5절 참조
├─ glossary.jsonl            # 반입 대상, git 관리
├─ glossary.meta.json        # 버전 정보
├─ tm.jsonl                  # 반입 대상
└─ runtime.db                # SQLite. 폐쇄망에서 생성. git 제외

tools/                       # 오프라인 배치 도구 (개발망 전용)
├─ glossary_import.py        # 확보 용어집 파싱 → glossary.jsonl
├─ glossary_lint.py          # 스키마 검증, 중복/충돌 탐지
├─ corpus_align.py           # 병렬 코퍼스 문장 정렬
├─ term_extract.py           # 용어 후보 추출
├─ tm_build.py               # TM 구축 → tm.jsonl
└─ bundle_build.py           # 반입 번들 생성

tests/
├─ test_matcher.py
├─ test_segment.py
├─ test_verify.py
├─ test_glossary_schema.py   # glossary.jsonl 유효성
└─ test_offline.py           # 네트워크 차단 상태 동작 검증
```

**`.gitignore`에 `data/runtime.db*`를 넣으십시오.** WAL 모드는 `-wal`, `-shm` 파일도 만듭니다.

### 4.3 백엔드 인터페이스

모델 교체를 위한 추상화 계층입니다. **매칭·용어집·검증·웹앱은 모델을 모릅니다.**

```python
# app/backends/base.py
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class TermHint:
    source: str
    targets: list[str]          # 후보가 여럿이면 조건부
    conditions: dict | None = None
    abbr: str | None = None
    is_reference: bool = False  # 강제 아님, 참고용

@dataclass
class TranslationRequest:
    text: str
    direction: str                      # "ko2en" | "en2ko"
    terms: list[TermHint] = field(default_factory=list)
    tm_examples: list[tuple[str, str]] = field(default_factory=list)
    style: str = "press_release"
    global_context: dict = field(default_factory=dict)
    prompt_version: str = ""

@dataclass
class TranslationResult:
    text: str                   # 후처리 완료
    raw: str                    # 후처리 전 (디버깅)
    elapsed_ms: int

class TranslationBackend(Protocol):
    async def translate(self, req: TranslationRequest) -> TranslationResult: ...
    async def analyze(self, text: str, prompt: str) -> str: ...
    async def health(self) -> bool: ...
```

`analyze`는 번역이 아닌 보조 작업(군종 판정 등)용입니다. 전용 MT 백엔드는 `NotImplementedError`로 두고 오케스트레이터가 규칙 기반으로 폴백합니다.

### 4.4 API 계약

```jsonc
// 요청
POST /translate
{
  "text": "합참은 제7기동군단 예하 부대의 훈련을 참관했다고 밝혔다.",
  "source": "ko",
  "target": "en",
  "style": "press_release"        // 선택, 기본값 press_release
}

// 응답
{
  "translation": "The Joint Chiefs of Staff (JCS) said it observed ...",
  "terms_applied": [
    {
      "source": "합참",
      "target": "Joint Chiefs of Staff",
      "term_id": "T-0142",
      "spans": [[0, 2]],
      "confidence": "verified"
    }
  ],
  "warnings": [
    {"type": "term_missing", "term_id": "T-0301", "chunk": 2},
    {"type": "unknown_candidate", "text": "천무-Ⅱ"}
  ],
  "meta": {
    "chunks": 1,
    "retries": 0,
    "elapsed_ms": 3200,
    "backend": "gemma4-26b-a4b",
    "prompt_version": "ko2en-press-v1"
  }
}
```

**`terms_applied`와 `warnings`는 현재 프론트에 표시 위치가 없어도 처음부터 반환합니다.** 나중에 용어 하이라이트 UI를 붙일 때 백엔드를 수정하지 않기 위해서입니다.

---

## 5. 데이터 설계

### 5.0 저장 방식 — DB 서버를 쓰지 않는 이유

데이터를 성격별로 나눠 보면 DB 서버가 필요한 구간이 없습니다.

| 데이터 | 쓰기 빈도 | 실제 필요 | 선택 |
|---|---|---|---|
| 용어집 | 반입 시에만 | 시작 시 1회 로드 → 메모리 인덱스 | **JSONL** |
| TM | 반입 시에만 | 시작 시 1회 로드 → BM25 인덱스 | **JSONL** |
| 미등록 후보 큐 | 요청마다 소량 | 누적 쓰기 + 집계 조회 | **SQLite** |
| 번역 로그 | 요청마다 | 누적 쓰기 + 다양한 조건 조회 | **SQLite** |

**용어집과 TM은 매 요청마다 조회하지 않습니다.** 앱 시작 시 인덱스를 만들고 나면 그걸로 끝이라, DB에 넣어봐야 이점이 없습니다.

파일을 택한 실질적 이유는 세 가지입니다.

1. **에어갭 반입 부담 제거** — PostgreSQL 설치 패키지, 초기화 절차, 계정 설정, 백업/복구 절차가 전부 사라집니다. 용어집 갱신이 "파일 교체 후 재시작"이 되고, 백업이 "디렉터리 복사"가 됩니다.
2. **용어집의 git 버전 관리** — JSONL은 한 줄이 한 레코드라 diff가 보입니다. 누가 어떤 용어를 언제 바꿨는지 추적됩니다. DB 덤프는 diff가 안 보입니다.
3. **규모가 DB를 요구하지 않음** — 용어집 3,000개 ≈ 1~2MB, TM 50,000쌍 ≈ 20MB, 로그 연간 수백 MB. SQLite로 충분합니다.

SQLite는 **Python 표준 라이브러리**라 별도 반입 대상이 아닙니다.

```
data/
├─ glossary.jsonl        # 반입 대상. git 관리. 사람이 편집·리뷰 가능
├─ tm.jsonl              # 반입 대상
└─ runtime.db            # SQLite. 로그 + 후보 큐. 반입 대상 아님(폐쇄망에서 생성)
```

### 5.1 용어집 (`data/glossary.jsonl`)

한 줄에 한 용어. UTF-8, `ensure_ascii=False`.

```jsonc
{"id":"T-0142","ko":"합동참모본부","en":"Joint Chiefs of Staff","en_abbr":"JCS","ko_aliases":["합참","합동참모부"],"en_aliases":["ROK JCS"],"conditions":null,"domain_tag":["편제"],"priority":10,"corpus_freq":842,"abbr_policy":"first_full_then_abbr","source":"국방백서 국/영문판","confidence":"verified","note":""}
```

필드 정의입니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✔ | `T-####` 형식. 영구 불변 |
| `ko` / `en` | string | ✔ | 표제어 |
| `en_abbr` | string\|null | | 영문 약어 |
| `ko_aliases` / `en_aliases` | string[] | ✔ | 이형태. 없으면 `[]` |
| `conditions` | object\|null | | 다의어 분기 (§5.3) |
| `domain_tag` | string[] | ✔ | 분류 태그 |
| `priority` | int | ✔ | 겹침 해소 시 가중치 |
| `corpus_freq` | int | ✔ | 코퍼스 등장 빈도. 주입 우선순위 계산용 |
| `abbr_policy` | string\|null | | `first_full_then_abbr` \| `always_full` \| `always_abbr` |
| `source` | string | ✔ | 출처. **대역 충돌 시 판단 근거** |
| `confidence` | string | ✔ | `verified` \| `probable` \| `candidate` |
| `note` | string | ✔ | 자유 메모. 없으면 `""` |

**`source`와 `confidence`는 비워두지 마십시오.** 나중에 대역이 충돌할 때 어느 쪽을 신뢰할지 판단하는 유일한 근거입니다.

```python
# app/glossary/loader.py
def load_glossary(path: Path) -> list[Term]:
    terms = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                terms.append(Term(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(f"glossary.jsonl:{lineno} — {e}") from e
    return terms
```

**로딩 실패 시 줄 번호를 반드시 알려주십시오.** 사람이 직접 편집하는 파일이라 문법 오류가 발생합니다.

#### 버전 관리

```
data/glossary.meta.json
{"version": 17, "updated_at": "2026-08-19T10:00:00+09:00", "count": 1042, "note": "해군 계급 조건 보강"}
```

인덱스 재빌드 판단에 사용합니다. 파일 mtime보다 명시적 버전이 안전합니다(반입 시 mtime이 바뀔 수 있음).

### 5.2 TM (`data/tm.jsonl`)

```jsonc
{"ko":"합참은 20일부터 나흘간 연합훈련을 실시한다고 밝혔다.","en":"The JCS said a combined exercise will be conducted for four days from the 20th.","source":"국방부 보도자료 2025-03","style":"press_release","quality":"verified"}
```

`id`가 없습니다. TM은 개별 참조가 아니라 검색 대상이라 인덱스상 위치로 충분합니다.

### 5.3 다의어 표현

```jsonc
{
  "id": "T-0087",
  "ko": "대령",
  "en": "Colonel",
  "conditions": {
    "field": "service",
    "branches": [
      {"value": ["육군", "공군", "해병대"], "en": "Colonel"},
      {"value": ["해군"], "en": "Captain"}
    ]
  },
  "confidence": "verified"
}
```

매칭 단계에서 조건이 확정되면 하나로 좁히고, 확정되지 않으면 **후보 전부를 조건과 함께 프롬프트에 넘깁니다.** 코드가 잘못 확정하면 모델이 그대로 따르지만, 후보를 주면 모델이 문맥으로 판단할 여지가 생깁니다.

### 5.4 런타임 저장소 (`data/runtime.db`, SQLite)

폐쇄망에서 앱이 처음 뜰 때 생성합니다. **반입 대상이 아닙니다.**

```sql
PRAGMA journal_mode = WAL;      -- 동시 읽기/쓰기 허용
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS term_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    freq        INTEGER NOT NULL DEFAULT 1,
    first_seen  TEXT NOT NULL,            -- ISO8601
    last_seen   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending|accepted|rejected
    UNIQUE (text, direction)
);

CREATE TABLE IF NOT EXISTS translation_logs (
    id              TEXT PRIMARY KEY,      -- UUID
    created_at      TEXT NOT NULL,
    direction       TEXT NOT NULL,
    src             TEXT NOT NULL,
    tgt             TEXT NOT NULL,
    terms_applied   TEXT,                  -- JSON 문자열
    violations      TEXT,                  -- JSON 문자열
    backend         TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    glossary_version INTEGER,
    chunks          INTEGER,
    retries         INTEGER,
    elapsed_ms      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_logs_created ON translation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_backend ON translation_logs(backend, prompt_version);
CREATE INDEX IF NOT EXISTS idx_cand_status ON term_candidates(status, freq DESC);
```

`translation_logs`는 운영 후 **골든셋의 원천**이 됩니다. 실제 사용 로그에서 대표 문장을 뽑아 사람이 검수하면 평가셋이 됩니다. `glossary_version`을 함께 기록해야 "용어집 v16과 v17 중 어느 쪽이 나았는가"를 나중에 따질 수 있습니다.

#### 쓰기 처리

로그 기록이 번역 응답을 지연시키면 안 됩니다. 백그라운드 태스크로 분리합니다.

```python
# app/api/translate.py
@router.post("/translate")
async def translate(req: TranslateRequest, bg: BackgroundTasks):
    result = await orchestrator.run(req)
    bg.add_task(store.log_translation, result)   # 응답 후 기록
    return result.to_response()
```

SQLite는 쓰기가 직렬화되므로 단일 커넥션 + 락으로 관리합니다.

```python
# app/store/runtime.py
_conn: sqlite3.Connection
_lock = asyncio.Lock()

async def log_translation(record: dict) -> None:
    async with _lock:
        await asyncio.to_thread(_insert_log, record)
```

**다중 워커(uvicorn `--workers N`)를 쓰면 프로세스마다 커넥션이 생깁니다.** WAL 모드면 동작하지만, 안전하게 하려면 워커 수를 1로 두고 비동기 동시성만 쓰거나, 워커별 DB 파일을 나눈 뒤 분석 시 합치십시오. 처리량 요구(O-04)가 확정된 뒤 결정합니다.

#### 로그 보존

무한 누적되면 파일이 커집니다. 운영 절차에 정리 주기를 넣으십시오.

```sql
DELETE FROM translation_logs WHERE created_at < date('now', '-180 days');
VACUUM;
```

원문이 로그에 그대로 저장된다는 점도 유의하십시오. 공개 자료만 다루므로(D-03) 등급 문제는 없으나, **보존 기간과 접근 권한은 운영 절차에 명시**해야 합니다.

---

## 6. 파이프라인 상세

### 6.1 정규화 (`normalize.py`)

보도자료는 줄바꿈과 문단 구조가 의미를 가집니다. 정규화하면서 이를 날리면 결과가 한 덩어리로 나옵니다.

```python
def normalize(text: str) -> tuple[str, FormatMap]:
    """정규화 텍스트 + 복원용 맵"""
    # NFKC 정규화
    # 전각/반각 통일
    # 연속 공백 정리 (줄바꿈 위치는 기록)
    # 문단 경계 토큰 치환
```

원문 위치 추적을 위해 인덱스 매핑을 함께 유지합니다.

```python
def normalize_with_map(text: str, direction: str) -> tuple[str, list[int]]:
    """정규화 문자열, 각 문자의 원문 인덱스 배열"""
```

이 매핑으로 정규화 공간의 매칭 위치를 원문 위치로 되돌립니다. 프론트 하이라이트에 필요합니다.

### 6.2 분할 (`segment.py`)

한국어 문장 분할은 마침표만으로 자르면 "제7사단", 약어, 소수점에서 오작동합니다. `kss`를 사용합니다.

```python
MAX_CHUNK_CHARS = 800

def build_chunks(text: str, direction: str) -> list[Chunk]:
    # 1) 문단 경계로 1차 분리
    # 2) 각 문단을 문장 분할
    # 3) MAX_CHUNK_CHARS 내에서 문장 묶기
    # 4) 문단 경계는 넘지 않음
```

**컨텍스트가 커도 청크 분할을 생략하지 마십시오.** 작은 모델일수록 긴 입력에서 용어를 놓치거나 문장을 빠뜨립니다.

### 6.3 매칭 (`glossary/matcher.py`)

#### 인덱스 구조

Aho-Corasick 오토마톤으로 모든 표층형을 한 번의 스캔으로 동시 탐색합니다. 텍스트 길이에 대해 O(n)이고 용어집 크기와 무관합니다.

```python
@dataclass(frozen=True)
class Surface:
    term_id: str
    text: str          # 정규화된 표층형
    is_primary: bool
    length: int
```

하나의 `term_id`에 표층형이 여러 개 붙습니다. "합동참모본부"와 "합참"은 같은 `term_id`를 가리킵니다.

#### 정규화 (방향별)

```python
def normalize_key(text: str, direction: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    if direction == "ko2en":
        return re.sub(r"\s+", "", text)        # 띄어쓰기 흔들림 흡수
    else:
        text = text.lower()
        text = re.sub(r"[\u2010-\u2015\u2212/]", "-", text)
        text = re.sub(r"[\u2018\u2019`]", "'", text)
        return re.sub(r"\s+", " ", text).strip()
```

#### 경계 검증

| 방향 | 방법 |
|---|---|
| en2ko | 앞뒤 문자가 영숫자면 거부 (`corps` vs `corpse`) |
| ko2en | 앞이 한글이면 거부. 뒤는 조사 목록 대조 |

```python
JOSA = ("은","는","이","가","을","를","의","에","에서","에게","와","과",
        "으로","로","도","만","까지","부터","라도","이나","나","께서")
```

#### 형태소 분석 병행 (한→영)

용어집 표제어를 Kiwi 사용자 사전에 `NNP`로 등록하면 분석기가 최장 일치로 끊어줍니다. "기계화보병사단에서는" → `기계화보병사단/NNP + 에서/JKB + 는/JX`

```python
class KoreanAnalyzer:
    def __init__(self, terms: list[Term]):
        self.kiwi = Kiwi()
        for t in terms:
            self.kiwi.add_user_word(t.ko, "NNP", score=5.0)
            for a in t.ko_aliases:
                self.kiwi.add_user_word(a, "NNP", score=5.0)
```

Aho-Corasick 결과와 형태소 결과가 일치하면 `confirmed=True`로 표시하고, 겹침 해소에서 우선순위를 높입니다.

#### 겹침 해소

"제7기동군단"에 `제7기동군단`, `기동군단`, `군단`이 모두 걸립니다. 구간 스케줄링으로 해결합니다.

```python
def resolve_overlaps(matches: list[RawMatch]) -> list[RawMatch]:
    matches.sort(key=lambda m: (
        m.start,
        -(m.end - m.start),      # 긴 것 우선
        not m.confirmed,          # 형태소 확인된 것 우선
        -m.priority,
    ))
    out, cursor = [], -1
    for m in matches:
        if m.start >= cursor:
            out.append(m)
            cursor = m.end
    return out
```

서로 다른 위치의 같은 용어는 둘 다 남습니다(구간 기준이므로 자동 처리).

**알려진 한계**: 그리디 방식이라 `[0,5]`와 `[3,20]`이 경합하면 짧은 앞쪽을 택합니다. 실무에서 문제가 확인되면 가중 구간 스케줄링(DP)으로 교체합니다.

#### 주입 선별

```python
CHUNK_TERM_LIMIT = 10

def score(tm: TermMatch) -> float:
    rarity = 1.0 / (1 + tm.term.corpus_freq)     # 희소할수록 우선
    ambiguous = 2.0 if tm.term.conditions else 1.0
    return rarity * ambiguous * tm.count
```

`사단`, `부대` 같은 흔한 용어는 후순위입니다. 모델이 이미 알고 있어 넣지 않아도 맞습니다.

### 6.4 TM 검색 (`tm/retriever.py`)

용어집과 달리 TM은 **퍼지 검색이 적합합니다.** 문장 단위 유사도라 오탐 위험이 낮고, 예시로만 쓰이므로 강제되지 않습니다.

```python
TM_TOP_K = 3
TM_MIN_SCORE = 0.35

def retrieve(query: str, direction: str) -> list[tuple[str, str]]:
    """BM25로 유사 문장 쌍 조회"""
```

BM25로 시작하고, 필요 시 임베딩으로 승급합니다. **임베딩 도입은 실제 성능 부족이 확인된 뒤에만** 검토합니다(에어갭에서 임베딩 모델 추가 반입 부담).

### 6.5 검증 (`verify.py`)

```python
def verify(src, tgt, applied: list[TermMatch], direction: str) -> list[Violation]:
    violations = []
    for m in applied:
        expected = m.term.target_forms(direction)   # full form, 약어, 이형태
        norm_tgt = normalize_key(tgt, direction)
        if not any(normalize_key(e, direction) in norm_tgt for e in expected):
            violations.append(Violation(term_id=m.term.id, kind="missing"))
    return violations
```

**자동 강제 치환은 하지 않습니다.** 모델이 문맥상 더 나은 형태를 썼거나 문장 구조가 달라져 치환 시 비문이 되는 경우가 많습니다.

| 상황 | 처리 |
|---|---|
| 1차 위반 | 해당 청크만 재호출 (전체 재번역 아님) |
| 2차 위반 | `warnings`에 담아 반환. 사용자 판단 |

**재호출 상한은 1회입니다.** 다중 접속 환경에서 재시도가 누적되면 큐를 막습니다.

### 6.6 동시성

```python
MAX_CONCURRENT_PER_REQUEST = 4   # 한 요청 내 청크 병렬도
MAX_CONCURRENT_REQUESTS = 16     # 전체 동시 요청 (O-04 확정 후 조정)
```

사용자 1명이 5,000자를 넣으면 청크가 6~7개 생깁니다. 동시 접속 10명이면 순간 70개 요청이 되므로 세마포어로 상한을 겁니다.

Kiwi 인스턴스는 스레드 안전하지 않으므로 풀로 관리합니다.

```python
kiwi_pool: Queue[KoreanAnalyzer]   # 워커 수만큼 사전 생성
```

### 6.7 인덱스 생명주기

Aho-Corasick 인덱스, Kiwi 사용자 사전, BM25 인덱스는 **매 요청마다 만들면 안 됩니다.** 앱 시작 시 1회 빌드하고 메모리에 상주시킵니다.

```python
# app/glossary/index.py
class IndexRegistry:
    def __init__(self):
        self._version: int | None = None
        self._ko2en: GlossaryIndex | None = None
        self._en2ko: GlossaryIndex | None = None
        self._kiwi_pool: Queue[KoreanAnalyzer] | None = None
        self._tm: BM25Retriever | None = None
        self._lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        meta = read_meta(DATA_DIR / "glossary.meta.json")
        if self._version == meta.version:
            return
        async with self._lock:
            if self._version == meta.version:   # 이중 확인
                return
            await self._rebuild(meta.version)
```

**빌드 시간 참고** (용어집 3,000개 기준)

| 항목 | 소요 |
|---|---|
| JSONL 로드 + 검증 | ~50ms |
| Aho-Corasick 빌드 (방향별) | ~50ms |
| Kiwi 사용자 사전 등록 (인스턴스당) | ~1~3초 |
| BM25 인덱스 (TM 50,000쌍) | ~5~10초 |

Kiwi와 BM25가 병목이라 **기동 시간이 10~20초** 걸립니다. 헬스체크가 이 시간 동안 `not ready`를 반환하도록 하십시오.

#### 핫리로드 (선택)

무중단 용어집 갱신이 필요하면 관리 엔드포인트를 둡니다.

```python
@router.post("/admin/reload", status_code=202)
async def reload_glossary():
    """glossary.jsonl 교체 후 호출. 새 인덱스를 백그라운드로 빌드하고 원자적 교체."""
```

새 인덱스를 **완전히 빌드한 뒤 참조를 교체**해야 합니다. 빌드 중 기존 인덱스로 계속 서비스합니다. 빌드 실패 시 기존 인덱스를 유지하고 오류를 반환하십시오 — 잘못된 용어집으로 교체되는 것이 서비스 중단보다 나쁩니다.

O-05(반입 주기)가 월 1회 이하로 확정되면 이 기능이 필수가 됩니다.

---

## 7. 프롬프트 설계

### 7.1 층 구조

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

**층 순서는 고정 → 가변이어야 vLLM 프리픽스 캐싱이 동작합니다.** ⑥(출력 형식)을 ④ 앞으로 옮기면 캐시 히트가 깨집니다.

### 7.2 ① 역할·기본 지시 (한→영 예시)

```
You are a professional Korean-to-English translator specializing in
Republic of Korea military and defense documents.

Core rules:
- Translate the source text completely. Do not omit or summarize.
- Do not add information not present in the source.
- If a term is not in the provided glossary, use standard military
  English conventions. DO NOT invent acronyms.
- For Korean proper nouns without an established English form, use
  Revised Romanization.
- Preserve all numbers, dates, and units exactly.
```

**"DO NOT invent acronyms"가 이 도메인에서 가장 중요한 한 줄입니다.** 범용 LLM은 모르는 약어를 만나면 그럴듯한 영문 약어를 지어내고, 형태가 자연스러워 검수자가 놓치기 쉽습니다.

### 7.3 ② 문체 프리셋 (`prompts/styles/press_release.yaml`)

```yaml
ko2en:
  register: "News wire style. Active voice preferred."
  rules:
    - "Rank precedes surname: 'Colonel Kim', not 'Kim Colonel'."
    - "Unit designations: 'the 7th Maneuver Corps'."
    - "Dates: 'August 19, 2026' or 'Aug. 19' in tight copy."
    - "Attribution: 'the JCS said', not 'it was announced by the JCS'."
    - "Spell out numbers one through nine; figures for 10 and above."
en2ko:
  register: "보도자료체. 종결어미 '~했다', '~밝혔다'."
  rules:
    - "직함은 이름 앞: '김OO 대령'."
    - "날짜: '2026년 8월 19일' 또는 '8월 19일'."
    - "피동 표현 최소화: '발표되었다' → '발표했다'."
    - "부대명·계급은 국군 공식 용어 사용. 직역 금지."
```

### 7.4 ③ 전역 컨텍스트

```
[Document context]
- Service branch: Republic of Korea Navy
  (Resolve branch-dependent terms accordingly.)
- This is chunk 2 of 4. Already introduced in earlier chunks:
  Joint Chiefs of Staff (JCS), Combined Forces Command (CFC)
  → Use the abbreviated form for these.
- First occurrence in this chunk (use full form + abbreviation):
  Defense Acquisition Program Administration (DAPA)
```

이 블록이 없으면 각 청크가 독립적으로 "첫 등장"이라 판단해 full form을 반복합니다.

군종이 판정되지 않았으면 해당 줄을 생략하고 ④에서 후보를 조건과 함께 넘깁니다.

### 7.5 ④ 용어 대응표 — 세 블록 분리

```
[Glossary — apply exactly]
합동참모본부 / 합참 → Joint Chiefs of Staff (JCS)
제7기동군단 → VII Maneuver Corps

[Glossary — context-dependent, choose one]
대령 → Colonel (Army/Air Force/Marines) | Captain (Navy)

[Reference — related terms, use only if they appear]
방위사업청 → Defense Acquisition Program Administration (DAPA)
```

**전부 한 덩어리로 주면 모델이 강제와 참고를 구분하지 못합니다.**

매칭된 용어가 하나도 없으면 블록 자체를 생략합니다. 빈 헤더를 남기면 모델이 혼란스러워합니다.

### 7.6 ⑤ TM 예시

```
[Reference translations from past work — match the style]
KO: 합참은 20일부터 나흘간 연합훈련을 실시한다고 밝혔다.
EN: The JCS said a combined exercise will be conducted for four days from the 20th.
```

few-shot 예시 선택 시 **의미 유사성보다 구문 유사성을 우선**하십시오. 용어 경계 포착에 더 신뢰할 만한 지침을 제공한다는 연구 결과가 있습니다. 군사 보도자료는 구문 패턴이 반복되므로 효과가 큽니다.

### 7.7 ⑥ 출력 형식 + 후처리

```
Output ONLY the translation. No preamble, no explanation,
no quotation marks around the result, no notes.
```

**프롬프트만 믿지 말고 후처리로도 걷어냅니다.** 작은 모델일수록 이 지시를 어깁니다.

```python
PREAMBLE_PATTERNS = [
    r"^(Here is|Here's) the translation:?\s*",
    r"^(번역|번역문|번역 결과):?\s*",
    r"^Translation:?\s*",
]
```

### 7.8 재호출 프롬프트

대화형이 아니라 **새 요청**으로 구성합니다.

```
[Previous attempt omitted required terms]
Missing:
  합동참모본부 → Joint Chiefs of Staff (JCS)

[Your previous output]
{{ previous }}

[Source text]
{{ source }}
```

이전 출력을 함께 주면 전면 재작성이 아니라 수정에 가깝게 나옵니다.

### 7.9 프리셋 두 벌

| 프리셋 | 구성 | 대상 |
|---|---|---|
| `full` | ①~⑥ 전부 | 26B~32B급 |
| `compact` | ① + ④ + ⑥ | 4B~7B급 |

**작은 모델은 프롬프트가 길수록 지시를 놓칩니다.** 평가에서 모델별로 어느 쪽이 나은지 확인하고 고릅니다.

### 7.10 버전 관리

```python
@dataclass
class PromptVersion:
    id: str            # "ko2en-press-v3"
    template_hash: str
    created_at: datetime
```

`translation_logs`와 평가 결과에 이 id를 기록합니다. 기록이 없으면 프롬프트 수정이 개선인지 퇴보인지 알 수 없습니다.

---

## 8. 모델 후보

### 8.1 라이선스 검증 결과

| 모델 | 크기 | 라이선스 | 상태 |
|---|---|---|---|
| Gemma 4 | E2B/E4B/12B/26B-A4B/31B | **Apache 2.0** | 검증됨 |
| Qwen3 | 0.6B~32B, 30B-A3B, 235B-A22B | **Apache 2.0** | 검증됨 |
| A.X 4.0 Light | 7B | **Apache 2.0** | 검증됨 (HF 모델카드) |
| K-EXAONE 2.0 | 750B | Apache 2.0 | 크기 초과 |
| HyperCLOVA X SEED Think | 32B | 네이버 커스텀 (조건부 상업) | 조건 확인 필요 |
| TranslateGemma | 4B/12B/27B | Gemma ToU + 금지사용정책 | **운영 전 법무 검토** |
| EXAONE 3.5 / 4.x | 7.8B/32B/33B | EXAONE License NC | **배제** |
| Kanana nano | 2.1B | CC-BY-NC | **배제** |
| SOLAR-10.7B | 10.7B | CC-BY-NC | **배제** |
| NLLB-200 | 600M~3.3B | CC-BY-NC | 기준선 사용 시 검토 |

### 8.2 하드웨어 적재

**L40S 48GB (1장 기준)**

| 크기 | FP16 | FP8 | 판정 |
|---|---|---|---|
| 4B | ~8GB | ~4GB | 여유 |
| 7B | ~15GB | ~8GB | 여유 |
| 12B | ~24GB | ~12GB | 여유 |
| 26B-A4B (MoE) | ~52GB ✗ | ~26GB | 가능, KV 여유 20GB |
| 31B 덴스 | ~62GB ✗ | ~31GB | 가능, KV 여유 15GB |

**RTX 4050 6GB (실질 4.5~5GB)**

| 모델 | Q4_K_M | 판정 |
|---|---|---|
| Gemma 4 E2B | ~1.5GB | 여유 |
| Qwen3-1.7B | ~1.2GB | 여유 |
| Gemma 4 E4B | ~2.8GB | 가능 |
| Qwen3-4B | ~2.5GB | 가능 |
| A.X 4.0 Light 7B | ~4.5GB | 빠듯 (컨텍스트 축소) |

개발 환경은 vLLM보다 llama.cpp/Ollama가 적합합니다. vLLM은 KV 캐시를 미리 크게 잡습니다.

### 8.3 평가 후보 (5개 + 기준선)

| # | 모델 | 답하려는 질문 |
|---|---|---|
| A | Gemma 4 26B-A4B | 주 후보. MoE로 처리량 유리 |
| B | Qwen3-30B-A3B | 계열 간 한↔영 군사 용어 우열 (A vs B) |
| C | A.X 4.0 Light 7B | 한국어 특화 + 소형으로 충분한가 (A vs C) |
| D | TranslateGemma 12B | 범용 vs 번역 특화 (A vs D) — **핵심 질문** |
| E | Gemma 4 E4B | 개발 환경 검증용 |
| — | NLLB-1.3B | 기준선 대조군 (라이선스 검토 후) |

**A vs D가 이 프로젝트에서 가장 중요한 비교입니다.**

---

## 9. 에어갭 대응 (최우선 설계 제약)

### 9.1 원칙

> 개발 중 무심코 쓴 자동 다운로드는 **개발망에서 정상 동작하고 폐쇄망에서만 터집니다.**
> 따라서 개발 단계부터 오프라인을 강제해야 합니다.

### 9.2 반입 번들 구성

```
bundle-YYYYMMDD/
├─ models/
│  ├─ gemma-4-26b-a4b/          # HF snapshot 전체 (config, tokenizer, safetensors)
│  ├─ qwen3-30b-a3b/
│  ├─ ax-4.0-light/
│  └─ SHA256SUMS
├─ wheels/                       # pip download 결과 (플랫폼 고정)
│  ├─ *.whl
│  └─ requirements.lock.txt
├─ kiwi/
│  └─ kiwipiepy_model-*.whl      # 형태소 분석기 모델 (별도 패키지)
├─ images/                       # 선택: 컨테이너 배포 시
│  ├─ translator-api.tar
│  └─ vllm.tar
├─ data/
│  ├─ glossary.jsonl             # 용어집 (D-19: DB 덤프 아님)
│  ├─ glossary.meta.json         # 버전 정보
│  ├─ tm.jsonl                   # 번역 메모리
│  └─ goldenset.jsonl            # 평가셋
│  # runtime.db는 반입하지 않음 — 폐쇄망에서 최초 기동 시 생성
├─ app/                          # 애플리케이션 소스 (git archive)
├─ prompts/
├─ INSTALL.md                    # 폐쇄망 설치 절차
└─ MANIFEST.json                 # 버전, 해시, 생성일시
```

### 9.3 금지 패턴 — LLM 에이전트 필독

**아래 코드는 절대 작성하지 마십시오.** 전부 런타임 네트워크 접근을 유발합니다.

| 금지 | 이유 | 대안 |
|---|---|---|
| `AutoModel.from_pretrained("org/model")` | HF Hub 다운로드 | 로컬 절대경로 사용 |
| `snapshot_download(...)` | HF Hub 다운로드 | 번들에 사전 포함 |
| `SentenceTransformer("model-name")` | HF Hub 다운로드 | 로컬 경로 |
| `nltk.download(...)` | 런타임 다운로드 | 사용 금지 |
| `tiktoken.get_encoding(...)` | BPE 파일 다운로드 | 사용 금지 |
| `spacy.load()` (모델 미설치 시) | 모델 다운로드 | 사용 금지 |
| `requests.get(...)` (외부 URL) | 명백한 외부 접근 | 사용 금지 |
| `pip install` (런타임) | 패키지 다운로드 | 번들 wheel만 |
| 폰트/CDN 링크 (프론트) | 외부 리소스 | 로컬 번들 |

### 9.4 환경변수 강제

폐쇄망 서버와 **개발망 테스트 시** 모두 설정합니다.

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export NO_PROXY="*"
export PYTHONDONTWRITEBYTECODE=1
```

### 9.5 오프라인 검증 절차

**개발망에서 네트워크를 차단한 상태로 전체 테스트를 통과해야 반입 승인**입니다.

```bash
# tests/test_offline.py 에서 수행
# 1) 네트워크 차단 (컨테이너: --network none)
docker run --network none translator-api pytest tests/

# 2) 또는 방화벽 규칙으로 아웃바운드 차단 후
HF_HUB_OFFLINE=1 pytest tests/ -v
```

```python
# tests/test_offline.py
import socket, pytest

@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """모든 소켓 연결을 차단. 네트워크 접근 시 즉시 실패."""
    def guard(*args, **kwargs):
        raise RuntimeError("Network access attempted in offline test")
    monkeypatch.setattr(socket, "socket", guard)
    monkeypatch.setattr(socket, "create_connection", guard)

def test_pipeline_runs_offline():
    ...
```

**반입 번들을 만들기 전에 반드시 실행하십시오.** 새 의존성이 몰래 네트워크를 쓰면 여기서 걸립니다.

```bash
pytest tests/test_offline.py -v
```

> CI 자동화는 도입하지 않았습니다(2026-08-23 결정). 따라서 이 검사는 **사람이 실행해야 하는 절차**입니다.
> 자동으로 걸러주지 않으므로 §9.2 반입 번들 생성 절차의 첫 단계에 넣고, 통과하지 못하면 번들을 만들지 마십시오.

### 9.6 번들 갱신 주기 (O-05 미결)

용어집이 갱신되면 폐쇄망에도 반영해야 합니다. **반입 절차가 오래 걸리면 운영 설계가 달라집니다.**

| 반입 주기 | 설계 영향 |
|---|---|
| 주 1회 이상 | 용어집 피드백 루프가 실질적으로 동작. 계획대로 진행 |
| 월 1회 | 용어집을 폐쇄망 내에서 직접 편집하는 관리 UI 필요 |
| 분기 1회 이하 | 폐쇄망 내 완전 자립 필요. 검수 도구까지 반입 |

**O-05 확정 전에는 "폐쇄망 내 용어집 편집 UI"를 선택 기능으로 남겨둡니다.**

#### 용어집만 갱신하는 경량 절차 (D-19의 이점)

전체 번들을 다시 만들 필요가 없습니다. 모델과 wheel은 그대로 두고 파일 두 개만 교체합니다.

```bash
# 개발망: 최소 번들 생성
tar czf glossary-update-$(date +%Y%m%d).tar.gz \
    data/glossary.jsonl data/glossary.meta.json
sha256sum glossary-update-*.tar.gz > SHA256SUM

# 폐쇄망: 교체 후 재시작
tar xzf glossary-update-YYYYMMDD.tar.gz -C /opt/translator/
systemctl restart translator-api
```

파일 크기가 1~2MB 수준이라 반입 매체 부담이 작습니다. **DB를 썼다면 덤프 생성 → 전송 → 복원 절차가 필요했을 자리입니다.**

무중단 갱신이 필요하면 §6.7의 인덱스 핫리로드를 쓰십시오.

---

## 10. 의존성 (버전 고정)

> **⚠ 중요**: 아래 버전은 계획 시점의 기준값입니다.
> Phase 0에서 `pip download`로 실제 해석되는 버전을 확인하고
> `requirements.lock.txt`를 생성한 뒤, **그 lock 파일이 정본**이 됩니다.
> 임의로 버전을 올리거나 내리지 마십시오. 번들과 1:1 대응합니다.

> **파일 구성 변경 (D-25, 2026-09-01)**: 원안은 목적별로 5개 파일을 두었으나
> **2개로 합쳤습니다.** 판단 기준을 "무엇에 쓰는가"에서 **"폐쇄망에 반입하는가"**로
> 바꾼 결과입니다 — 파일이 여러 개여도 반입 결정이 갈리는 지점은 그 하나뿐이고,
> 나머지 구분은 주석으로 충분합니다. 실제로 쓰이지 않는 패키지도 함께 걷어냈습니다.
>
> | 파일 | 용도 | 반입 |
> |---|---|---|
> | `requirements.txt` | 폐쇄망 런타임 | ✅ |
> | `requirements-dev.txt` | 개발 전용 (`-r requirements.txt` 포함) | ✗ |

### 10.1 런타임 — `requirements.txt` (반입 대상)

```
# 웹 · 설정
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
pydantic-settings==2.7.0

# 프롬프트 템플릿(§7) · 문체 프리셋(§7.3)
jinja2==3.1.6
pyyaml==6.0.3

# 모델 서버 호출 (§4.3). 폐쇄망 내부 주소로만
httpx==0.28.1

# 용어 매칭 · 형태소 (§6.2, §6.3)
pyahocorasick==2.1.0
kiwipiepy==0.22.2
kiwipiepy-model==0.22.1         # ★ 별도 패키지. 누락 시 런타임 다운로드 시도

# TM few-shot 검색 (§6.4)
rank-bm25==0.2.2
```

> **DB 드라이버 없음** (D-19). SQLite는 Python 표준 라이브러리 `sqlite3`를 씁니다.
> ORM도 쓰지 않습니다 — 테이블이 2개뿐이고 쿼리가 단순해서 `sqlite3` 직접 사용이 낫습니다.
> **LLM 에이전트는 SQLAlchemy, psycopg, asyncpg 등을 추가하지 마십시오.**

> **`kss` 제외** (D-22): 의존성 34개에 sdist-only 3개가 섞여 있어 반입 비용이
> 컸습니다. `Kiwi.split_into_sents()`로 대체했고, 용어집 사용자 사전이 문장
> 분할에도 적용되는 이득까지 얻었습니다. `docs/phase0-notes.md §2-b`.

> **버전 정책** (D-20): `mars-ai-server/requirements.txt`와 겹치는 항목은
> 그쪽 버전을 정본으로 삼습니다. 반입 번들을 공유하기 위해서입니다.

> **넣지 않은 것**: 원안의 `python-multipart`, `orjson`, `structlog`,
> `tenacity`, `rapidfuzz`, `regex`는 코드베이스 어디서도 import하지 않아
> 뺐습니다. 파일 업로드(`python-multipart`)나 유사도 매칭(`rapidfuzz`)이
> 실제로 필요해지면 그때 다시 넣으십시오.

### 10.2 개발 환경 — `requirements-dev.txt` (반입 제외)

```
-r requirements.txt

pytest==8.3.4
pytest-asyncio==0.25.0
ruff==0.8.6
mypy==1.14.1
openpyxl==3.1.5                 # 엑셀 용어집 (O-02 확정)
```

개발자는 이 파일 하나만 설치하면 됩니다. 런타임까지 함께 깔립니다.

Phase 1·3 도구 의존성(`pandas`, `sentence-transformers`, `sacrebleu`,
`unbabel-comet`)은 해당 스크립트가 전부 미구현이라 **주석으로만** 남겼습니다.
구현할 때 주석을 푸십시오.

> ⚠ `sentence-transformers`는 런타임에 모델을 내려받습니다. 개발망 전용이므로
> 허용되지만 **`app/` 아래에서는 절대 import하지 마십시오** (§9.3).

### 10.3 서빙 (GPU, 폐쇄망 서버)

**requirements 파일에 넣지 않습니다.** 번역기 앱은 `torch`를 import하지 않고,
vLLM은 HTTP로 부르는 **별도 서비스**입니다 — DB를 requirements에 적지 않는 것과
같은 이유입니다. 여기 넣으면 앱 서버가 쓰지도 않는 수 GB를 받습니다.

GPU 서버에 따로 설치합니다. `requirements.txt` 하단에 주석으로 기록해 두었습니다.

```
torch==2.8.0                    # D-20: mars-ai-server 기준
transformers==4.57.1            # D-20
vllm==0.11.0                    # D-20
accelerate==1.14.0
safetensors==0.8.0
```

> **O-06 미결**: 폐쇄망 서버의 CUDA 버전에 따라 `torch` 휠이 달라집니다
> (cu121 / cu124 / cu128 …). 확인 전까지 잠금하지 못합니다.

### 10.4 번들 생성 명령

```bash
# ① kiwipiepy_model 을 먼저 만든다 (D-21).
#    PyPI 에 sdist 만 있어서 --only-binary=:all: 이 이 줄에서 멈춘다.
#    순수 데이터 패키지라 결과가 py3-none-any 이고 플랫폼을 안 탄다.
pip wheel kiwipiepy_model==0.22.1 -w bundle/wheels/ --no-deps

# ② 나머지를 받는다. 플랫폼을 폐쇄망 서버와 일치시켜야 함 (O-06)
pip download -r requirements.txt \
  --platform manylinux2014_x86_64 \
  --python-version 3.11 \
  --only-binary=:all: \
  --find-links bundle/wheels/ \
  -d bundle/wheels/

sha256sum bundle/wheels/*.whl > bundle/wheels/SHA256SUMS
```

해석 결과는 `requirements.lock.txt`에 있습니다. **그 lock 파일이 정본**이며
번들과 1:1 대응합니다. 재생성은 반드시 **폐쇄망과 같은 OS(Linux)**에서
하십시오 — Windows에서 만들면 환경 마커가 현재 인터프리터 기준으로 평가돼
`uvloop`이 빠집니다.

```bash
# 폐쇄망 설치
pip install --no-index --find-links=./wheels -r requirements.lock.txt
```

---

## 11. 단계별 계획

### Phase 0 — 환경 구축 및 골격 (GPU 불필요)

| 항목 | 내용 |
|---|---|
| 목표 | 프론트-백엔드 연결 확인, 오프라인 검증 체계 확립 |
| 선행 | 없음 |
| 산출물 | 동작하는 `/translate` (mock 백엔드), `requirements.lock.txt`, `tests/test_offline.py` |

**작업**

1. 저장소 구조 생성 (§4.2 그대로)
2. `backends/mock.py` 구현 — 입력을 그대로 반환하거나 고정 응답
3. `/translate` 엔드포인트 + 스키마 (§4.4)
4. `store/runtime.py` — SQLite 초기화(`schema.sql` 적용), 로그 쓰기
5. 샘플 `data/glossary.jsonl` 20개로 로더 동작 확인
6. 프론트 연동 확인
7. `pip download`로 실제 버전 해석 → `requirements.lock.txt` 생성 → **§10 갱신**
8. `tests/test_offline.py` 작성 — §9.3 금지 패턴 정적 검사 포함. 반입 전 필수 실행

**완료 기준**
- [ ] 프론트에서 텍스트 입력 시 mock 응답이 화면에 표시됨
- [ ] `runtime.db`가 최초 기동 시 자동 생성되고 로그가 기록됨
- [ ] `pytest tests/` 가 네트워크 차단 상태에서 통과
- [ ] `requirements.lock.txt` 생성 완료, §10에 반영

---

### Phase 1 — 용어집 구축 (GPU 불필요, 최대 병목)

| 항목 | 내용 |
|---|---|
| 목표 | 검수된 용어집 500~1,000개 + TM 구축 |
| 선행 | **O-01, O-02, O-03 확정 필수** |
| 산출물 | `data/glossary.jsonl`, `data/glossary.meta.json`, `data/tm.jsonl` (git 커밋) |

**작업**

1. **확보 용어집 파싱** (`tools/glossary_import.py`)
   - O-02 확정 후 파서 작성
   - `ko / en / en_abbr / ko_aliases / en_aliases` 5열로 정규화
   - 이형태 자동 생성 (로마숫자↔아라비아, 하이픈 유무 등)
   - 출력은 `data/glossary.jsonl` (§5.1 스키마)

1-b. **검증 도구** (`tools/glossary_lint.py`)
   - 스키마 필수 필드 확인
   - 표층형 중복 탐지 (서로 다른 `id`가 같은 `ko`를 가리키는 경우)
   - 대역 충돌 탐지 (같은 `ko`에 다른 `en`)
   - `source`/`confidence` 누락 탐지
   - **용어집을 갱신할 때마다 실행.** `glossary.jsonl`을 커밋하기 전에 통과해야 합니다

2. **AI Hub 데이터 신청 및 수령** (O-17 활용)
   - 국방 데이터: 군 담당자 경유 신청
   - 공개 데이터: 전문분야 한영 말뭉치, 기술과학 분야 한영 병렬 말뭉치, 한국어-영어 번역(병렬) 말뭉치
   - 휴대폰 본인인증 후 다운로드 승인 필요

3. **문장 정렬 → TM 구축** (`tools/corpus_align.py`, `tools/tm_build.py`)
   - LaBSE 임베딩 + DP 정렬
   - 유사도 임계값 미달 쌍은 폐기 (오염된 데이터가 더 나쁨)

4. **용어 후보 추출** (`tools/term_extract.py`)
   - 통계: 로그 우도비 + Dice 계수로 다어절 병합
   - LLM: 정렬 문장 쌍에서 용어 쌍 추출. **few-shot 예시는 구문 유사성 기준으로 선택**
   - 두 결과 교차 검증, 빈도 집계

5. **`corpus_freq` 채우기** — 실제 코퍼스 등장 빈도. 주입 우선순위 계산에 사용

6. **검수** (O-01)
   - 신뢰도별 분류: 단일 후보+고빈도 → 훑어보기 / 복수 후보 → 선택 / 저빈도 → 보류
   - 다의어 `conditions` 필드 작성

**완료 기준**
- [ ] `confidence="verified"` 용어 500개 이상
- [ ] TM 세그먼트 10,000쌍 이상
- [ ] 다의어(계급 등) `conditions` 필드 작성 완료
- [ ] 모든 항목에 `source`, `confidence` 채워짐
- [ ] `glossary_lint.py` 통과 (중복·충돌 없음)
- [ ] `data/glossary.jsonl`이 git에 커밋됨

---

### Phase 2 — 매칭 엔진 (GPU 불필요)

| 항목 | 내용 |
|---|---|
| 목표 | 정확한 용어 매칭 + 프롬프트 조립 |
| 선행 | Phase 1 (용어집 최소 200개) |
| 산출물 | `glossary/`, `pipeline/normalize.py`, `segment.py`, `analyze.py`, `prompt.py` |

**작업**

1. 정규화 + 서식 보존/복원 (§6.1)
2. 문장 분할 + 청크 구성 (§6.2)
3. Aho-Corasick 인덱스 + 방향별 매칭 (§6.3)
4. Kiwi 사용자 사전 + 교차 검증
5. 겹침 해소, 집계, 주입 선별
6. 미등록 후보 수집
7. TM 검색 (BM25)
8. Jinja2 프롬프트 템플릿 (§7)

**단위 테스트 (필수)**

```python
CASES = [
    ("합참은 발표했다", {"T-0142"}),
    ("합동참모본부(합참)는", {"T-0142"}),          # 중복 아님
    ("합동 참모 본부는", {"T-0142"}),              # 띄어쓰기 흔들림
    ("제7기동군단 예하 각 군단은", {"T-0301", "T-0300"}),
    ("군단장은", set()),                           # 경계 오탐 방지
    ("The JCS said", {"T-0142"}),
    ("the corpse was found", set()),               # corps 오탐 방지
]
```

**완료 기준**
- [ ] 위 테스트 전부 통과
- [ ] 5,000자 매칭이 200ms 이내 (형태소 분석 포함)
- [ ] 프롬프트 조립 결과가 §7 층 순서를 지킴
- [ ] mock 백엔드로 전체 파이프라인 관통

---

### Phase 3 — 모델 평가 (L40S 필수)

| 항목 | 내용 |
|---|---|
| 목표 | 운영 모델 확정 |
| 선행 | Phase 1, 2 + 골든셋 |
| 산출물 | 모델별 비교 리포트, 운영 모델 결정 |

**작업**

1. **골든셋 구축** — 보도자료 실제 문장 50개 (한→영 25, 영→한 25)
   - 사람이 검수한 정답 번역
   - **고유명사 밀집 문장을 의도적으로 포함**할 것:
     > "제7기동군단 예하 제20기계화보병사단은 K2 흑표와 천무 다연장로켓을 동원한 합동훈련을 실시했다고 합동참모본부가 밝혔다."

2. **평가 지표 구현** (`eval/metrics.py`)
   - 용어 준수율 (주 지표, 자동)
   - 용어 일관성 (같은 용어가 문서 내 동일하게 번역되는가)
   - 약어 처리 정확도 (첫 등장 full form, 이후 약어)
   - chrF / COMET (보조)

3. **`vllm_openai.py` 백엔드 구현**

4. **A/B 실행** — 카드 2장에 후보를 하나씩 올려 동시 비교

```bash
CUDA_VISIBLE_DEVICES=0 vllm serve /models/gemma-4-26b-a4b \
  --quantization fp8 --enable-prefix-caching \
  --max-model-len 8192 --port 8001
CUDA_VISIBLE_DEVICES=1 vllm serve /models/qwen3-30b-a3b \
  --quantization fp8 --enable-prefix-caching \
  --max-model-len 8192 --port 8002
```

5. **프리셋 비교** — 모델별로 `full` vs `compact` 어느 쪽이 나은지

**완료 기준**
- [ ] 후보 A~D + 기준선 전부 같은 골든셋으로 측정
- [ ] 용어 준수율 표 작성
- [ ] 운영 모델 1개 확정 (근거를 §1 결정 로그에 추가)
- [ ] TranslateGemma 선택 시 법무 검토 완료

---

### Phase 4 — 검증 루프 및 처리량 (L40S)

| 항목 | 내용 |
|---|---|
| 목표 | 검증·재호출 완성, 다중 접속 대응 |
| 선행 | Phase 3 |
| 산출물 | 완성된 파이프라인, 부하 테스트 결과 |

**작업**

1. 검증 로직 + 재호출 (§6.5)
2. 동시성 제어 (§6.6)
3. `translation_logs` 기록
4. 미등록 후보 큐 적재
5. 부하 테스트 — O-04 기준 동시 접속 시 응답 시간 측정
6. 프리픽스 캐싱 효과 측정

**완료 기준**
- [ ] 재호출 후 용어 준수율이 재호출 전보다 유의미하게 개선
- [ ] O-04 목표 동시 접속에서 p95 응답시간이 허용 범위
- [ ] 로그가 정상 기록되고 골든셋 추출이 가능

---

### Phase 5 — 에어갭 배포

| 항목 | 내용 |
|---|---|
| 목표 | 폐쇄망 서비스 개시 |
| 선행 | Phase 4 + O-05, O-06 확정 |
| 산출물 | 반입 번들, 설치 문서, 운영 절차 |

**작업**

1. `tools/bundle_build.py` 구현 (§9.2)
2. 오프라인 검증 통과 (§9.5)
3. `INSTALL.md` 작성 — 폐쇄망 담당자가 따라할 수 있는 수준
4. 폐쇄망 설치 및 스모크 테스트
5. 용어집 경량 갱신 절차 리허설 (§9.6)
6. 로그 정리 주기 및 보존 정책 문서화 (§5.4)

**완료 기준**
- [ ] 네트워크 완전 차단 상태에서 전체 테스트 통과
- [ ] 폐쇄망에서 실제 번역 동작 확인
- [ ] `runtime.db`가 폐쇄망 최초 기동 시 정상 생성됨
- [ ] 용어집 경량 갱신(파일 2개 교체 → 재시작)이 1회 이상 리허설 완료
- [ ] 전체 번들 재생성 → 반입 절차가 문서화됨

---

### Phase 6 — 운영 및 개선 (지속)

- 미등록 용어 큐 주기적 검수 → 용어집 반영
- 사용자 대역어 교체 이력 수집 (UI 추가 시)
- 검증 실패가 반복되는 용어 → 용어집 쪽 오류 가능성 검토
- 프롬프트 버전별 성능 추적

**차기 검토 카드** (지금은 하지 않음)

| 카드 | 도입 조건 |
|---|---|
| 파인튜닝 (SFT + GRPO) | 프롬프트 주입으로 용어 준수율이 정체될 때 |
| 임베딩 기반 퍼지 폴백 | 표기 흔들림 누락 사례가 로그에 축적될 때 |
| 문체 프리셋 확장 (교범체 등) | 다른 문서 유형 요구가 실제로 발생할 때 |
| 폐쇄망 용어집 편집 UI | O-05 반입 주기가 월 1회 이상일 때 |

---

## 12. 평가 설계

### 12.1 주 지표

| 지표 | 계산 | 자동화 |
|---|---|---|
| **용어 준수율** | 원문 등장 용어 중 지정 대역어로 번역된 비율 | 완전 자동 |
| 용어 일관성 | 같은 용어가 텍스트 내 동일하게 번역된 비율 | 완전 자동 |
| 약어 처리 정확도 | 첫 등장 full form + 이후 약어 규칙 준수율 | 완전 자동 |
| chrF | 문자 n-gram F-score | 자동 (골든셋 필요) |
| COMET | 신경망 품질 추정 | 자동 (모델 반입 필요, 선택) |

**용어 준수율이 1순위입니다.** 용어집 기반이라 자동 측정이 가능하고, 이 도메인의 핵심 요구사항과 직결됩니다.

일반 번역 품질 지표(chrF/COMET)는 보조입니다. WMT25 기준으로도 주 평가는 **일반 품질 × 용어 성공률** 조합입니다.
지금
### 12.2 평가 모드

WMT25 방식을 따라 세 모드로 측정하면 용어집 효과를 인과적으로 분리할 수 있습니다.

| 모드 | 프롬프트에 넣는 것 |
|---|---|
| `noterm` | 용어 없음 |
| `proper` | 실제 매칭된 용어 |
| `random` | 원문에서 무작위 추출한 단어 |

`random`이 `proper`보다 높게 나오면 지표 설계가 잘못된 것입니다(무작위 단어는 대개 일반 어휘라 원래 잘 맞음).

### 12.3 회귀 테스트

프롬프트나 용어집을 수정할 때마다 골든셋 전체를 재실행하고 이전 버전과 비교합니다.

```bash
python -m app.eval.runner \
  --goldenset data/goldenset.jsonl \
  --backend gemma4-26b \
  --prompt-version ko2en-press-v3 \
  --compare-with ko2en-press-v2
```

---

## 13. 리스크

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| R-01 | 용어집 검수 인력 미확보 (O-01) | Phase 1 정체 → 전체 지연 | 자동 추출 신뢰도 임계값을 높이고 고빈도 항목만 우선 반영 |
| R-02 | 에어갭 위반 코드가 늦게 발견 | Phase 5에서 대규모 수정 | §9.5 오프라인 테스트 + §9.3 금지 패턴 정적 검사. **CI 미도입이라 사람이 실행해야 한다** — 번들 생성 절차의 첫 단계로 못박을 것 |
| R-03 | 개발 환경(6GB)과 운영 환경 격차 | 평가 결과 재현 불가 | 품질 평가는 반드시 L40S에서. 4050은 로직 검증만 |
| R-04 | 모델의 약어 환각 | 오역이 자연스러워 검수자가 놓침 | "DO NOT invent acronyms" 지시 + 미등록 후보 탐지 + `warnings` 노출 |
| R-05 | 다의어 오판정 (군종별 계급 등) | 확신을 갖고 틀린 번역 생성 | 코드가 확정하지 않고 후보를 모델에 넘김. 규칙 우선, LLM 폴백 |
| R-06 | 반입 주기가 길어 용어집 피드백 단절 (O-05) | 개선 루프 무력화 | 폐쇄망 내 편집 UI를 선택 기능으로 준비 |
| R-07 | TranslateGemma 라이선스 문제 | 운영 배포 불가 | 평가는 진행하되 운영 후보는 Apache 2.0 우선 |
| R-08 | 재호출 누적으로 큐 포화 | 다중 접속 시 응답 지연 | 재호출 1회 상한, 2차 실패는 경고로 전환 |
| R-09 | 5,000자 입력 시 청크 경계 문제 | 문장 중복/누락 | 결합 단계 점검 로직 + 골든셋에 장문 케이스 포함 |
| R-10 | 모델 원산지 조달 규정 (O-09) | Qwen3 배제 시 후보 축소 | Gemma 4, A.X 4.0으로 대체 가능하도록 후보 유지 |
| R-11 | 사람이 편집한 `glossary.jsonl` 문법 오류 | 앱 기동 실패 | 로더가 줄 번호와 함께 오류 보고 + `glossary_import.py`가 시트·행 번호로 거부. 커밋 전 `glossary_lint.py` 실행 |
| R-12 | SQLite 다중 워커 동시 쓰기 경합 | 로그 유실 또는 `database is locked` | WAL 모드 + `busy_timeout`. 워커 수는 O-04 확정 후 결정. 최악의 경우 워커별 DB 분리 |
| R-13 | 번역 로그 무한 누적 | 디스크 포화 | 보존 기간(기본 180일) 정리 작업을 운영 절차에 포함 (§5.4) |

---

## 14. 부록

### 14.1 참고 자료

| 자료 | 용도 | 비고 |
|---|---|---|
| WMT25 Terminology Shared Task | 평가 지표 정의, 테스트셋, 평가 코드 | 저장소 CC BY-NC 4.0 |
| WMT23 Terminology Shared Task | 용어 주입 방식 계보 | |
| VARCO-MT (NCSOFT, WMT23) | 국내 사례. 한국어 실무 회고 블로그 존재 | 중→영 기준 용어 재현율 +21.51%p |
| AI Hub 병렬 말뭉치 | TM 및 용어 추출 원천 | 본인인증 + 다운로드 승인 필요 |
| AI Hub 국방 데이터 | 도메인 특화 자료 | 군 담당자 경유 별도 신청 |
| DoD Dictionary of Military and Associated Terms | 영어 측 표준 용어 확정 | |
| NATO AAP-6 | 영어 측 표준 용어 확정 | |

### 14.2 확인이 필요한 사항 (제가 검증하지 못한 것)

이 계획서 작성 시점에 **검색으로 확인하지 못했거나 시점이 지나 변동 가능성이 있는 항목**입니다. 진행 전 재확인하십시오.

- §10의 모든 라이브러리 버전 — Phase 0에서 `pip download`로 실제 해석 결과 확인 필요
- Gemma 4 / Qwen3 최신 라인업 — Qwen3.6, Qwen3.8 등 후속 모델 존재 확인됨. 도입 시점에 재조사
- MADLAD-400 라이선스 — 미확인 (기준선 후보로만 언급)
- Hy-MT2 라이선스 — 미확인 (후보에서 제외했으나 재검토 가능)
- A.X 4.0 (72B) 라이선스 — Light(7B)는 Apache 2.0 확인. 72B는 미확인이나 하드웨어 범위 밖
- AI Hub 각 데이터셋의 현재 제공 여부 및 이용 조건
- Google Gemma Prohibited Use Policy 세부 조항 (TranslateGemma 관련)
- 폐쇄망 서버 사양 전반 (O-06)

### 14.3 변경 이력

| 버전 | 날짜 | 변경 |
|---|---|---|
| v0.1 | 2026-08-19 | 최초 작성 |
| v0.2 | 2026-08-19 | D-19 추가 — DB 서버 제거, JSONL + SQLite로 전환.<br>§5 전면 개정, §6.7 인덱스 생명주기 신설,<br>§9.6 경량 갱신 절차 추가, §10 DB 드라이버 제거,<br>구 O-07 해소로 미확정 항목 재번호(O-07~O-09),<br>R-11~R-13 추가 |
