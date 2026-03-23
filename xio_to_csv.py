#!/usr/bin/env python3
"""
NGIMU XIO to CSV Converter
---------------------------
NGIMU .XIO 파일(복수의 CSV를 담은 zip 아카이브)을 하나의 통합 CSV 파일로 변환합니다.

출력 형식:
  - 1열: 데이터 종류 이름 (Data Name)
  - 2열: 시간 (HH:MM:SS.mmm)
  - 이후 열: 각 데이터 타입의 측정값

사용법:
  python xio_to_csv.py <입력 경로> [출력 파일]

  <입력 경로>:
    - .xio 파일 (zip 아카이브)
    - CSV 파일들이 있는 폴더

  예시:
    python xio_to_csv.py session.xio
    python xio_to_csv.py session.xio output.csv
    python xio_to_csv.py ./csv_folder/ output.csv
"""

import csv
import io
import os
import sys
import zipfile
from pathlib import Path
from datetime import timedelta


# ─────────────────────────────────────────────
# 시간 변환
# ─────────────────────────────────────────────

def seconds_to_hhmmss(value: str) -> str:
    """
    초(float 문자열) → HH:MM:SS.mmm 형식으로 변환.
    이미 시간 형식이면 그대로 반환.
    """
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return value  # 변환 불가 시 원본 반환

    td = timedelta(seconds=abs(seconds))
    total_s = int(td.total_seconds())
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    ms = round((seconds - int(seconds)) * 1000)
    if ms < 0:
        ms = 0
    sign = "-" if seconds < 0 else ""
    return f"{sign}{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ─────────────────────────────────────────────
# CSV 읽기
# ─────────────────────────────────────────────

def _parse_csv_text(text: str):
    """CSV 텍스트에서 (headers, rows) 반환."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def read_csv_file(filepath: Path):
    """파일에서 CSV 읽기."""
    for enc in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            text = filepath.read_text(encoding=enc)
            headers, rows = _parse_csv_text(text)
            if headers:
                return headers, rows
        except UnicodeDecodeError:
            continue
    return [], []


def read_csv_from_zip(zf: zipfile.ZipFile, name: str):
    """zip 내 파일에서 CSV 읽기."""
    raw = zf.read(name)
    for enc in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            text = raw.decode(enc)
            headers, rows = _parse_csv_text(text)
            if headers:
                return headers, rows
        except UnicodeDecodeError:
            continue
    return [], []


# ─────────────────────────────────────────────
# 데이터 수집
# ─────────────────────────────────────────────

def collect_from_zip(xio_path: Path) -> dict:
    """XIO(zip) 파일에서 모든 CSV 데이터 수집."""
    data = {}
    try:
        with zipfile.ZipFile(xio_path, "r") as zf:
            csv_entries = sorted(
                n for n in zf.namelist()
                if n.lower().endswith(".csv") and not os.path.basename(n).startswith(".")
            )
            if not csv_entries:
                print(f"  [경고] {xio_path.name} 안에 CSV 파일이 없습니다.")
                return data
            for entry in csv_entries:
                # 폴더 구조가 있을 수 있으므로 파일명만 사용
                data_name = Path(entry).stem
                headers, rows = read_csv_from_zip(zf, entry)
                if headers and rows:
                    data[data_name] = {"headers": headers, "rows": rows}
                    print(f"  [OK] {entry} → {len(rows)}행")
    except zipfile.BadZipFile:
        print(f"\n[오류] {xio_path.name}은 zip 형식이 아닙니다.")
        print("      NGIMU 소프트웨어로 먼저 CSV로 변환한 뒤, 그 폴더를 입력하세요.")
        sys.exit(1)
    return data


def collect_from_directory(dir_path: Path) -> dict:
    """폴더 내 모든 CSV 파일에서 데이터 수집."""
    data = {}
    csv_files = sorted(dir_path.glob("*.csv"))
    if not csv_files:
        print(f"[오류] {dir_path} 폴더에 CSV 파일이 없습니다.")
        sys.exit(1)
    for csv_file in csv_files:
        data_name = csv_file.stem
        headers, rows = read_csv_file(csv_file)
        if headers and rows:
            data[data_name] = {"headers": headers, "rows": rows}
            print(f"  [OK] {csv_file.name} → {len(rows)}행")
    return data


# ─────────────────────────────────────────────
# 통합 CSV 생성
# ─────────────────────────────────────────────

def write_unified_csv(all_data: dict, output_path: Path):
    """
    모든 데이터를 하나의 CSV로 통합.

    열 구조:
      Data Name | Time | <데이터타입1 컬럼들> | <데이터타입2 컬럼들> | ...

    각 행에서 해당 데이터 타입의 열만 채워지고 나머지는 빈 값.
    """
    # 전체 열 목록 구성 (타임스탬프 열 제외)
    # (data_name, header) 순서 유지
    all_columns = []
    col_index = {}  # (data_name, header) → 전역 인덱스

    for data_name, data in all_data.items():
        headers = data["headers"]
        for h in headers[1:]:  # headers[0]은 타임스탬프
            key = (data_name, h.strip())
            if key not in col_index:
                col_index[key] = len(all_columns)
                all_columns.append(key)

    total_cols = 2 + len(all_columns)  # Data Name + Time + 데이터 열

    # 헤더 행
    header_row = ["Data Name", "Time"] + [
        f"{name} - {col}" for name, col in all_columns
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header_row)

        total_rows = 0
        for data_name, data in all_data.items():
            headers = data["headers"]
            # 이 데이터 타입의 열들이 전역 인덱스에서 어디에 있는지 미리 계산
            local_to_global = []
            for h in headers[1:]:
                key = (data_name, h.strip())
                local_to_global.append(2 + col_index[key])

            for row in data["rows"]:
                if not row:
                    continue

                # 타임스탬프 변환
                time_str = seconds_to_hhmmss(row[0]) if row else ""

                out_row = [""] * total_cols
                out_row[0] = data_name
                out_row[1] = time_str

                for local_i, global_i in enumerate(local_to_global):
                    src_i = local_i + 1  # row[0]은 타임스탬프
                    if src_i < len(row):
                        out_row[global_i] = row[src_i]

                writer.writerow(out_row)
                total_rows += 1

    return total_rows


# ─────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────

def convert(input_path: str, output_path: str = None):
    inp = Path(input_path)

    if not inp.exists():
        print(f"[오류] 경로를 찾을 수 없습니다: {inp}")
        sys.exit(1)

    # 출력 경로 결정
    if output_path:
        out = Path(output_path)
    elif inp.is_file():
        out = inp.with_name(inp.stem + "_unified.csv")
    else:
        out = inp / "unified_output.csv"

    print(f"\n입력: {inp}")
    print(f"출력: {out}\n")

    # 데이터 수집
    if inp.is_file() and inp.suffix.lower() == ".xio":
        print("XIO 파일(zip)에서 데이터 읽는 중...")
        all_data = collect_from_zip(inp)
    elif inp.is_dir():
        print("폴더에서 CSV 파일 읽는 중...")
        all_data = collect_from_directory(inp)
    else:
        print(f"[오류] 지원하지 않는 입력 형식입니다: {inp.suffix}")
        print("  .xio 파일 또는 CSV 파일이 있는 폴더를 입력하세요.")
        sys.exit(1)

    if not all_data:
        print("[오류] 변환할 데이터가 없습니다.")
        sys.exit(1)

    # 통합 CSV 생성
    print(f"\n통합 CSV 생성 중...")
    total_rows = write_unified_csv(all_data, out)

    print(f"\n✓ 변환 완료!")
    print(f"  출력 파일 : {out}")
    print(f"  데이터 종류: {', '.join(all_data.keys())}")
    print(f"  총 행 수  : {total_rows:,}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n사용 예시:")
        print("  python xio_to_csv.py session.xio")
        print("  python xio_to_csv.py session.xio output.csv")
        print("  python xio_to_csv.py ./csv_folder/")
        sys.exit(0)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    convert(input_path, output_path)


if __name__ == "__main__":
    main()
