"""엑셀 용어집 양식의 열 정의 — 계획서 §11 Phase 1 작업 1 (O-02: 엑셀 확정).

양식 생성기(`glossary_template.py`)와 파서(`glossary_import.py`)가 이 정의를
공유한다. 한쪽만 고치면 채운 파일을 못 읽으므로 반드시 여기서만 바꿀 것.

## 설계 원칙

**검수자가 입력할 것을 최소로 줄인다.** O-01(검수 인력)이 최대 병목이므로,
자동으로 채울 수 있는 값(`id`, `priority`, `corpus_freq`, `note`)은 비워 두면
파서가 채운다. 사람은 판단이 필요한 것만 적는다.

**드롭다운으로 오타를 막는다.** `confidence` 와 `abbr_policy` 는 로더가
enum 으로 검증하므로(§5.1) 오타 하나로 500행짜리 파일이 통째로 거부된다.
엑셀 데이터 유효성 검사로 애초에 못 넣게 한다.

**다의어는 별도 시트로 분리한다.** 한 셀에 `육군|공군=Colonel; 해군=Captain`
같은 문법을 넣으면 사람이 못 쓴다. 행으로 펼치면 엑셀에서 자연스럽다 (§5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 목록형 셀의 구분자. 쉼표는 영문 용어 안에 들어갈 수 있어 쓰지 않는다.
LIST_SEP = ";"

SHEET_TERMS = "용어"
SHEET_CONDITIONS = "다의어"
SHEET_GUIDE = "작성안내"


@dataclass(frozen=True)
class Column:
    key: str  # Term 필드명 또는 파서 내부 키
    header: str  # 엑셀에 보일 열 이름
    required: bool = False
    width: int = 18
    choices: tuple[str, ...] = ()
    hint: str = ""
    #: 비우면 파서가 채운다
    auto: bool = False


TERM_COLUMNS: tuple[Column, ...] = (
    Column("id", "ID", width=10, auto=True, hint="비우면 T-0001 부터 자동 부여"),
    Column("ko", "한국어", required=True, width=22, hint="표제어. 가장 대표적인 표기"),
    Column("en", "영어", required=True, width=34, hint="표제어 대역"),
    Column("en_abbr", "영문약어", width=12, hint="JCS, DAPA 등. 없으면 비움"),
    Column(
        "ko_aliases",
        "한국어 이형태",
        width=26,
        hint=f"{LIST_SEP} 로 구분. 예: 합참{LIST_SEP}합동참모부",
    ),
    Column(
        "en_aliases",
        "영어 이형태",
        width=26,
        hint=f"{LIST_SEP} 로 구분. 예: ROK JCS",
    ),
    Column(
        "domain_tag",
        "분류",
        required=True,
        width=16,
        hint=f"{LIST_SEP} 로 구분. 편제/계급/기관/장비/훈련",
    ),
    Column(
        "abbr_policy",
        "약어정책",
        width=20,
        choices=("first_full_then_abbr", "always_full", "always_abbr"),
        hint="첫등장full후약어 / 항상full / 항상약어. 비우면 약어 안 씀",
    ),
    Column("source", "출처", required=True, width=30, hint="어느 자료에서 왔는지"),
    Column(
        "confidence",
        "신뢰도",
        required=True,
        width=12,
        choices=("verified", "probable", "candidate"),
        hint="verified 는 사람이 검수를 마친 것만",
    ),
    Column("priority", "우선순위", width=10, auto=True, hint="비우면 표제어 길이로 자동"),
    Column("note", "메모", width=30, hint="자유"),
)

CONDITION_COLUMNS: tuple[Column, ...] = (
    Column("ko", "한국어", required=True, width=22, hint="'용어' 시트의 한국어와 정확히 같아야 함"),
    Column("field", "조건분야", width=14, auto=True, hint="비우면 service (군종)"),
    Column(
        "value",
        "조건값",
        required=True,
        width=28,
        hint=f"{LIST_SEP} 로 구분. 예: 육군{LIST_SEP}공군{LIST_SEP}해병대",
    ),
    Column("en", "그때의 영어", required=True, width=30, hint="이 조건일 때 쓸 대역어"),
)


@dataclass
class RowError:
    """시트 · 행 번호가 붙은 오류.

    사람이 500행을 채우는 파일이라 "몇 번째 줄이 틀렸는지"가 없으면 못 고친다.
    용어집 로더가 줄 번호를 알려주는 것과 같은 이유다 (R-11).
    """

    sheet: str
    row: int
    detail: str

    def __str__(self) -> str:
        return f"[{self.sheet}] {self.row}행 — {self.detail}"


@dataclass
class ImportReport:
    """파싱 결과 요약. 사람이 보고 판단한다."""

    terms: list = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    warnings: list[RowError] = field(default_factory=list)
    #: 자동으로 만들어 붙인 이형태. 검수자가 눈으로 확인할 수 있어야 한다.
    generated_aliases: list[tuple[str, str]] = field(default_factory=list)
    assigned_ids: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors
