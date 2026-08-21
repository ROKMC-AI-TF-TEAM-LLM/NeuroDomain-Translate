"""엑셀 용어집 → data/glossary.jsonl — 계획서 §11 Phase 1 작업 1.

    python -m tools.glossary_import <파일.xlsx> [--out data/glossary.jsonl]
    python -m tools.glossary_import <파일.xlsx> --dry-run

O-02 가 "엑셀" 로 확정되어 구현했다. 양식은 `tools/glossary_template.py` 가
만든다 — 두 파일은 `tools/glossary_schema.py` 의 열 정의를 공유한다.

개발망 전용이다. 폐쇄망에 반입하지 않는다 (§10.5).

## 하는 일

1. `용어` 시트를 읽어 Term 으로 만든다
2. `다의어` 시트를 합쳐 `conditions` 를 채운다 (§5.3)
3. 비워 둔 `id` / `priority` / `corpus_freq` / `note` 를 채운다
4. 로마숫자↔아라비아 이형태를 만들어 붙인다
5. 스키마로 검증하고, 틀린 곳을 **시트와 행 번호로** 보고한다

## 하지 않는 일

**틀렸을 가능성이 있으면 통과시키지 않는다.** 용어집은 번역을 강제하는 장치라
잘못된 항목 하나가 빠진 항목 백 개보다 나쁘다 — 파이프라인이 그 오역을
강제하고 검증까지 통과시킨다. 애매하면 오류로 올려 사람이 보게 한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError

from app.glossary.loader import Term
from tools.glossary_schema import (
    CONDITION_COLUMNS,
    LIST_SEP,
    SHEET_CONDITIONS,
    SHEET_TERMS,
    TERM_COLUMNS,
    ImportReport,
    RowError,
)

DEFAULT_OUT = Path("data/glossary.jsonl")
DEFAULT_META = Path("data/glossary.meta.json")

#: 첫 데이터 행. 1행 = 열 이름, 2행 = 설명.
FIRST_DATA_ROW = 3

#: 로마 숫자 ↔ 아라비아. 무기 · 체계 명칭에 흔하다 (천무-Ⅱ / 천무-2).
_ROMAN = {
    "Ⅰ": "1",
    "Ⅱ": "2",
    "Ⅲ": "3",
    "Ⅳ": "4",
    "Ⅴ": "5",
    "Ⅵ": "6",
    "Ⅶ": "7",
    "Ⅷ": "8",
    "Ⅸ": "9",
    "Ⅹ": "10",
    "Ⅺ": "11",
    "Ⅻ": "12",
}
_ROMAN_RE = re.compile("[" + "".join(_ROMAN) + "]")

#: 기본 조건 분야. 지금 다루는 다의어는 전부 군종이다 (§5.3).
DEFAULT_CONDITION_FIELD = "service"


def _cell(value) -> str:  # noqa: ANN001
    if value is None:
        return ""
    return str(value).strip()


def _split_list(raw: str) -> list[str]:
    """`;` 로 나눈다. 빈 항목과 중복은 버린다."""
    parts = [p.strip() for p in raw.split(LIST_SEP)]
    return list(dict.fromkeys(p for p in parts if p))


def _get(ws, index: dict[str, int], row: int, key: str) -> str:  # noqa: ANN001
    """행·열 이름으로 셀 값을 꺼낸다.

    루프 안에서 람다로 만들면 루프 변수를 잡아 깨지기 쉽다. 행을 인자로 받는다.
    """
    if key not in index:
        return ""
    return _cell(ws.cell(row=row, column=index[key]).value)


def _header_index(ws, columns) -> dict[str, int]:  # noqa: ANN001
    """열 이름 → 열 번호. 사람이 열 순서를 바꿔도 읽을 수 있어야 한다."""
    found: dict[str, int] = {}
    for idx, cell in enumerate(ws[1], start=1):
        name = _cell(cell.value).rstrip(" *")
        for col in columns:
            if name == col.header:
                found[col.key] = idx
    return found


def _generate_aliases(surface: str) -> list[str]:
    """안전하게 만들 수 있는 이형태만 만든다.

    **매칭이 이미 흡수하는 변형은 만들지 않는다.** 띄어쓰기 · 대소문자 ·
    하이픈 종류 · 전각반각 · 영문 복수형은 `normalize_key` 와 경계 검증이
    처리하므로(§6.3), 여기서 또 만들면 인덱스만 부풀고 얻는 것이 없다.

    남는 것은 로마숫자↔아라비아뿐이다. 이건 정규화로 흡수되지 않는다.
    """
    if not _ROMAN_RE.search(surface):
        return []
    arabic = _ROMAN_RE.sub(lambda m: _ROMAN[m.group()], surface)
    return [arabic] if arabic != surface else []


def _auto_priority(ko: str) -> int:
    """긴 표제어가 짧은 것을 이겨야 한다 (§6.3 겹침 해소).

    `제7기동군단` 이 `군단` 을 이기는 그 값이다. 사람이 비워 두면 길이로 정한다.
    """
    length = len(ko.replace(" ", ""))
    if length >= 8:
        return 20
    if length >= 5:
        return 15
    if length >= 3:
        return 10
    return 5


def _read_conditions(  # noqa: ANN001
    wb, report: ImportReport
) -> tuple[dict[str, dict], dict[str, int]]:
    """`다의어` 시트를 한국어 표제어별로 묶는다 (§5.3).

    (표제어 → 조건, 표제어 → 첫 등장 행) 을 준다. 행 번호를 함께 들고 있어야
    나중에 오류를 낼 때 "몇 번째 줄" 을 말할 수 있다 (R-11).
    """
    if SHEET_CONDITIONS not in wb.sheetnames:
        return {}, {}

    ws = wb[SHEET_CONDITIONS]
    index = _header_index(ws, CONDITION_COLUMNS)
    missing = [c.header for c in CONDITION_COLUMNS if c.required and c.key not in index]
    if missing:
        report.errors.append(RowError(SHEET_CONDITIONS, 1, f"필수 열이 없다: {', '.join(missing)}"))
        return {}, {}

    grouped: dict[str, dict] = {}
    first_row: dict[str, int] = {}
    for row in range(FIRST_DATA_ROW, ws.max_row + 1):
        ko = _get(ws, index, row, "ko")
        value = _get(ws, index, row, "value")
        en = _get(ws, index, row, "en")
        if not any((ko, value, en)):
            continue  # 빈 행

        if not ko or not value or not en:
            report.errors.append(
                RowError(SHEET_CONDITIONS, row, "한국어 · 조건값 · 그때의 영어는 모두 필요하다")
            )
            continue

        field = _get(ws, index, row, "field") or DEFAULT_CONDITION_FIELD
        first_row.setdefault(ko, row)
        entry = grouped.setdefault(ko, {"field": field, "branches": []})
        if entry["field"] != field:
            report.errors.append(
                RowError(
                    SHEET_CONDITIONS,
                    row,
                    f"'{ko}' 의 조건분야가 행마다 다르다: {entry['field']} vs {field}",
                )
            )
            continue
        entry["branches"].append({"value": _split_list(value), "en": en})

    # 분기 개수 판정은 여기서 하지 않는다. 먼저 해버리면 '용어' 시트에 없는
    # 이름(표기 오타)이 "분기가 1개뿐" 경고에 가려져 사라진다. 존재 확인이 먼저다.
    return grouped, first_row


def read_workbook(path: Path) -> ImportReport:
    """엑셀을 읽어 Term 목록과 오류 보고를 만든다."""
    report = ImportReport()
    wb = load_workbook(path, data_only=True, read_only=False)

    if SHEET_TERMS not in wb.sheetnames:
        report.errors.append(
            RowError(SHEET_TERMS, 0, f"'{SHEET_TERMS}' 시트가 없다. 양식을 확인할 것")
        )
        return report

    conditions_by_ko, condition_rows = _read_conditions(wb, report)

    ws = wb[SHEET_TERMS]
    index = _header_index(ws, TERM_COLUMNS)
    missing = [c.header for c in TERM_COLUMNS if c.required and c.key not in index]
    if missing:
        report.errors.append(RowError(SHEET_TERMS, 1, f"필수 열이 없다: {', '.join(missing)}"))
        return report

    seen_ko: dict[str, int] = {}
    seen_id: dict[str, int] = {}
    used_ids: set[str] = set()
    used_conditions: set[str] = set()
    pending: list[tuple[int, dict]] = []

    for row in range(FIRST_DATA_ROW, ws.max_row + 1):
        ko, en = _get(ws, index, row, "ko"), _get(ws, index, row, "en")
        if not any(_cell(c.value) for c in ws[row]):
            continue  # 빈 행
        if not ko and not en:
            continue

        if not ko or not en:
            report.errors.append(RowError(SHEET_TERMS, row, "한국어와 영어는 둘 다 필요하다"))
            continue

        if ko in seen_ko:
            report.errors.append(
                RowError(SHEET_TERMS, row, f"한국어 중복: '{ko}' (먼저 {seen_ko[ko]}행)")
            )
            continue
        seen_ko[ko] = row

        term_id = _get(ws, index, row, "id")
        if term_id:
            if term_id in seen_id:
                report.errors.append(
                    RowError(SHEET_TERMS, row, f"ID 중복: {term_id} (먼저 {seen_id[term_id]}행)")
                )
                continue
            seen_id[term_id] = row
            used_ids.add(term_id)

        ko_aliases = _split_list(_get(ws, index, row, "ko_aliases"))
        en_aliases = _split_list(_get(ws, index, row, "en_aliases"))
        for surface in (ko, *ko_aliases):
            for extra in _generate_aliases(surface):
                if extra not in ko_aliases and extra != ko:
                    ko_aliases.append(extra)
                    report.generated_aliases.append((ko, extra))
        for surface in (en, *en_aliases):
            for extra in _generate_aliases(surface):
                if extra not in en_aliases and extra != en:
                    en_aliases.append(extra)
                    report.generated_aliases.append((en, extra))

        # 쉼표만 있고 세미콜론이 없으면 구분자를 잘못 쓴 것일 수 있다.
        for label, raw in (
            ("한국어 이형태", _get(ws, index, row, "ko_aliases")),
            ("분류", _get(ws, index, row, "domain_tag")),
        ):
            if "," in raw and LIST_SEP not in raw:
                report.warnings.append(
                    RowError(SHEET_TERMS, row, f"{label} 에 쉼표가 있다. 구분자는 '{LIST_SEP}' 다")
                )

        conditions = conditions_by_ko.get(ko)
        if conditions is not None:
            used_conditions.add(ko)
            # 분기가 하나뿐이면 다의어가 아니다. 조건 없이 그냥 대역어를 쓰면 된다.
            if len(conditions["branches"]) < 2:
                report.warnings.append(
                    RowError(
                        SHEET_CONDITIONS,
                        condition_rows.get(ko, 0),
                        f"'{ko}' 의 분기가 1개뿐이라 조건을 붙이지 않았다. "
                        "조건이 필요 없거나 다른 분기를 빠뜨린 것이다",
                    )
                )
                conditions = None

        payload = {
            "id": term_id,
            "ko": ko,
            "en": en,
            "en_abbr": _get(ws, index, row, "en_abbr") or None,
            "ko_aliases": ko_aliases,
            "en_aliases": en_aliases,
            "conditions": conditions,
            "domain_tag": _split_list(_get(ws, index, row, "domain_tag")),
            "priority": int(_get(ws, index, row, "priority"))
            if _get(ws, index, row, "priority").isdigit()
            else _auto_priority(ko),
            "corpus_freq": 0,  # Phase 1 작업 5 에서 실측값으로 채운다
            "abbr_policy": _get(ws, index, row, "abbr_policy") or None,
            "source": _get(ws, index, row, "source"),
            "confidence": _get(ws, index, row, "confidence"),
            "note": _get(ws, index, row, "note"),
        }
        pending.append((row, payload))

    # 용어 시트에 없는 다의어 행이 남았다면 표기 오타다. 조용히 넘기면 조건이
    # 사라진 채로 통과하고, 그건 그대로 오역이 된다 (§5.3).
    for ko in conditions_by_ko:
        if ko not in used_conditions:
            report.errors.append(
                RowError(
                    SHEET_CONDITIONS,
                    condition_rows.get(ko, 0),
                    f"'{SHEET_TERMS}' 시트에 없는 표제어: '{ko}'. 표기를 확인할 것",
                )
            )

    # ID 자동 부여는 수동 ID 를 전부 걷은 뒤에 한다.
    counter = 1
    for row, payload in pending:
        if not payload["id"]:
            while f"T-{counter:04d}" in used_ids:
                counter += 1
            payload["id"] = f"T-{counter:04d}"
            used_ids.add(payload["id"])
            report.assigned_ids += 1
        try:
            report.terms.append(Term(**payload))
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"]) or "(최상위)"
                report.errors.append(RowError(SHEET_TERMS, row, f"{loc}: {err['msg']}"))

    return report


def write_outputs(report: ImportReport, out: Path, meta: Path, note: str = "") -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("// 용어집 — 계획서 §5.1. tools/glossary_import.py 가 생성했다.\n")
        f.write("// 직접 편집해도 되지만, 엑셀 원본과 어긋나지 않게 주의할 것.\n")
        for term in report.terms:
            f.write(json.dumps(term.model_dump(), ensure_ascii=False) + "\n")

    version = 1
    if meta.is_file():
        try:
            version = int(json.loads(meta.read_text(encoding="utf-8")).get("version", 0)) + 1
        except (json.JSONDecodeError, TypeError, ValueError):
            version = 1

    meta.write_text(
        json.dumps(
            {
                "version": version,
                "updated_at": datetime.now(UTC).astimezone().isoformat(),
                "count": len(report.terms),
                "note": note or "tools/glossary_import.py 생성",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _print_report(report: ImportReport, path: Path) -> None:
    # 500행짜리 파일이면 위에서부터 훑으며 고친다. 행 순으로 정렬한다.
    report.errors.sort(key=lambda e: (e.sheet, e.row))
    report.warnings.sort(key=lambda e: (e.sheet, e.row))
    print(f"입력: {path}")
    print(f"  용어 {len(report.terms)}건")
    if report.assigned_ids:
        print(f"  ID 자동 부여 {report.assigned_ids}건")
    if report.generated_aliases:
        print(f"  이형태 자동 생성 {len(report.generated_aliases)}건:")
        for base, extra in report.generated_aliases[:10]:
            print(f"    {base} → {extra}")
        if len(report.generated_aliases) > 10:
            print(f"    … 외 {len(report.generated_aliases) - 10}건")

    by_confidence: dict[str, int] = {}
    for term in report.terms:
        by_confidence[term.confidence] = by_confidence.get(term.confidence, 0) + 1
    if by_confidence:
        print("  신뢰도: " + ", ".join(f"{k} {v}건" for k, v in sorted(by_confidence.items())))

    ambiguous = [t for t in report.terms if t.is_ambiguous]
    if ambiguous:
        print(f"  다의어 {len(ambiguous)}건: " + ", ".join(t.ko for t in ambiguous[:10]))

    if report.warnings:
        print(f"\n경고 {len(report.warnings)}건:")
        for w in report.warnings:
            print(f"  {w}")

    if report.errors:
        print(f"\n오류 {len(report.errors)}건 — 고친 뒤 다시 실행할 것:")
        for e in report.errors:
            print(f"  {e}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엑셀 용어집 → glossary.jsonl")
    parser.add_argument("excel", type=Path, help="채운 엑셀 파일")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--note", default="", help="glossary.meta.json 에 남길 메모")
    parser.add_argument("--dry-run", action="store_true", help="검사만 하고 쓰지 않는다")
    args = parser.parse_args(argv)

    if not args.excel.is_file():
        print(f"파일이 없다: {args.excel}", file=sys.stderr)
        return 2

    report = read_workbook(args.excel)
    _print_report(report, args.excel)

    if not report.ok:
        return 1
    if args.dry_run:
        print("\n--dry-run: 파일을 쓰지 않았다.")
        return 0

    write_outputs(report, args.out, args.meta, args.note)
    print(f"\n생성: {args.out} ({len(report.terms)}건), {args.meta}")
    print("확인: pytest tests/test_glossary_schema.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
