#!/usr/bin/env python3
"""
NGIMU XIO to CSV Converter - GUI
"""

import csv
import io
import os
import sys
import zipfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import timedelta


# ─────────────────────────────────────────────
# 변환 로직 (기존 xio_to_csv.py 와 동일)
# ─────────────────────────────────────────────

def seconds_to_hhmmss(value: str) -> str:
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return value
    td = timedelta(seconds=abs(seconds))
    total_s = int(td.total_seconds())
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    ms = round((seconds - int(seconds)) * 1000)
    ms = max(ms, 0)
    sign = "-" if seconds < 0 else ""
    return f"{sign}{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _parse_csv_text(text: str):
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def read_csv_file(filepath: Path):
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


def collect_from_zip(xio_path: Path, log):
    data = {}
    with zipfile.ZipFile(xio_path, "r") as zf:
        csv_entries = sorted(
            n for n in zf.namelist()
            if n.lower().endswith(".csv") and not os.path.basename(n).startswith(".")
        )
        if not csv_entries:
            log(f"  [경고] {xio_path.name} 안에 CSV 파일이 없습니다.")
            return data
        for entry in csv_entries:
            data_name = Path(entry).stem
            headers, rows = read_csv_from_zip(zf, entry)
            if headers and rows:
                data[data_name] = {"headers": headers, "rows": rows}
                log(f"  [OK] {entry} → {len(rows)}행")
    return data


def collect_from_directory(dir_path: Path, log):
    data = {}
    csv_files = sorted(dir_path.glob("*.csv"))
    for csv_file in csv_files:
        data_name = csv_file.stem
        headers, rows = read_csv_file(csv_file)
        if headers and rows:
            data[data_name] = {"headers": headers, "rows": rows}
            log(f"  [OK] {csv_file.name} → {len(rows)}행")
    return data


def write_unified_csv(all_data: dict, output_path: Path):
    all_columns = []
    col_index = {}
    for data_name, data in all_data.items():
        for h in data["headers"][1:]:
            key = (data_name, h.strip())
            if key not in col_index:
                col_index[key] = len(all_columns)
                all_columns.append(key)

    total_cols = 2 + len(all_columns)
    header_row = ["Data Name", "Time"] + [
        f"{name} - {col}" for name, col in all_columns
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header_row)
        total_rows = 0
        for data_name, data in all_data.items():
            headers = data["headers"]
            local_to_global = []
            for h in headers[1:]:
                key = (data_name, h.strip())
                local_to_global.append(2 + col_index[key])

            for row in data["rows"]:
                if not row:
                    continue
                time_str = seconds_to_hhmmss(row[0]) if row else ""
                out_row = [""] * total_cols
                out_row[0] = data_name
                out_row[1] = time_str
                for local_i, global_i in enumerate(local_to_global):
                    src_i = local_i + 1
                    if src_i < len(row):
                        out_row[global_i] = row[src_i]
                writer.writerow(out_row)
                total_rows += 1
    return total_rows


def run_conversion(input_paths: list, dest_dir: Path, log, on_done):
    """여러 XIO 파일 또는 폴더를 변환."""
    try:
        total_files = 0
        for inp in input_paths:
            inp = Path(inp)
            log(f"\n▶ {inp.name} 처리 중...")

            if inp.is_file() and inp.suffix.lower() == ".xio":
                try:
                    all_data = collect_from_zip(inp, log)
                except zipfile.BadZipFile:
                    log(f"  [오류] zip 형식이 아닙니다. NGIMU 소프트웨어로 먼저 CSV 변환 후 폴더를 선택하세요.")
                    continue
            elif inp.is_dir():
                all_data = collect_from_directory(inp, log)
            else:
                log(f"  [오류] 지원하지 않는 형식: {inp.suffix}")
                continue

            if not all_data:
                log("  [경고] 변환할 데이터가 없습니다.")
                continue

            out_path = dest_dir / (inp.stem + "_unified.csv")
            log(f"\n  CSV 생성 중 → {out_path.name}")
            total_rows = write_unified_csv(all_data, out_path)
            log(f"  ✓ 완료 | {total_rows:,}행 | 데이터: {', '.join(all_data.keys())}")
            total_files += 1

        on_done(total_files)
    except Exception as e:
        log(f"\n[오류] {e}")
        on_done(0)


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NGIMU XIO to CSV Converter v1.0")
        self.resizable(False, False)
        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build_ui(self):
        PAD = {"padx": 8, "pady": 4}

        # ── 입력 파일 행 ──────────────────────────
        tk.Label(self, text="SD Card File(s):").grid(
            row=0, column=0, sticky="e", **PAD)

        self.files_var = tk.StringVar(value="")
        self.files_entry = tk.Entry(
            self, textvariable=self.files_var, width=52,
            fg="grey", relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4")
        self.files_entry.insert(0, "Select SD card file(s)")
        self.files_entry.bind("<FocusIn>", self._clear_placeholder)
        self.files_entry.grid(row=0, column=1, sticky="ew", **PAD)

        tk.Button(self, text="...", width=3,
                  command=self._browse_files).grid(row=0, column=2, **PAD)

        # ── 출력 폴더 행 ──────────────────────────
        tk.Label(self, text="Destination Directory:").grid(
            row=1, column=0, sticky="e", **PAD)

        self.dest_var = tk.StringVar(value=str(Path.home() / "Desktop"))
        self.dest_entry = tk.Entry(
            self, textvariable=self.dest_var, width=52,
            relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4")
        self.dest_entry.grid(row=1, column=1, sticky="ew", **PAD)

        tk.Button(self, text="...", width=3,
                  command=self._browse_dest).grid(row=1, column=2, **PAD)

        # ── Convert 버튼 ──────────────────────────
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=3, sticky="e", padx=8, pady=4)
        self.convert_btn = tk.Button(
            btn_frame, text="Convert", width=10,
            command=self._start_convert)
        self.convert_btn.pack()

        # ── 로그 창 (초기엔 숨김) ─────────────────
        self.log_frame = tk.Frame(self)
        self.log_frame.grid(row=3, column=0, columnspan=3,
                            sticky="nsew", padx=8, pady=(0, 8))
        self.log_frame.grid_remove()

        self.log_text = tk.Text(
            self.log_frame, width=70, height=12,
            state="disabled", relief="flat", bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

        # ── 진행 바 (초기엔 숨김) ────────────────
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=480)
        self.progress.grid(row=4, column=0, columnspan=3,
                           padx=8, pady=(0, 8), sticky="ew")
        self.progress.grid_remove()

        self._input_paths = []

    # ── 이벤트 핸들러 ──────────────────────────────

    def _clear_placeholder(self, event):
        if self.files_entry.get() == "Select SD card file(s)":
            self.files_entry.delete(0, "end")
            self.files_entry.config(fg="black")

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title="SD Card File(s) 선택",
            filetypes=[("XIO files", "*.xio"), ("All files", "*.*")])
        if paths:
            self._input_paths = list(paths)
            display = "; ".join(Path(p).name for p in paths)
            self.files_entry.config(fg="black")
            self.files_var.set(display)

    def _browse_dest(self):
        path = filedialog.askdirectory(title="Destination Directory 선택")
        if path:
            self.dest_var.set(path)

    def _log(self, msg: str):
        """로그 창에 텍스트 추가 (스레드 안전)."""
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _append)

    def _start_convert(self):
        # 입력 검증
        paths = self._input_paths
        if not paths:
            raw = self.files_var.get().strip()
            if raw and raw != "Select SD card file(s)":
                paths = [p.strip() for p in raw.split(";") if p.strip()]

        if not paths:
            messagebox.showwarning("입력 없음", "SD Card File(s)을 선택하세요.")
            return

        dest = self.dest_var.get().strip()
        if not dest:
            messagebox.showwarning("출력 없음", "Destination Directory를 선택하세요.")
            return

        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)

        # UI 상태 변경
        self.convert_btn.config(state="disabled")
        self.log_frame.grid()
        self.progress.grid()
        self.progress.start(10)

        # 로그 초기화
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self._log(f"변환 시작 | 파일 수: {len(paths)}")
        self._log(f"출력 경로: {dest_path}\n")

        def on_done(total_files):
            def _finish():
                self.progress.stop()
                self.progress.grid_remove()
                self.convert_btn.config(state="normal")
                if total_files > 0:
                    self._log(f"\n모든 변환 완료 ({total_files}개 파일)")
                    messagebox.showinfo(
                        "완료",
                        f"{total_files}개 파일 변환 완료!\n\n출력 위치:\n{dest_path}")
                else:
                    self._log("\n변환된 파일이 없습니다.")
            self.after(0, _finish)

        threading.Thread(
            target=run_conversion,
            args=(paths, dest_path, self._log, on_done),
            daemon=True
        ).start()


# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
