#!/usr/bin/env python3
"""
NGIMU XIO to CSV Converter - GUI
XIO 파일 포맷: SLIP 프레임 안에 OSC 번들/메시지가 담긴 바이너리
"""

import csv
import struct
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from collections import defaultdict
from datetime import timedelta


# ─────────────────────────────────────────────
# SLIP 디코더
# ─────────────────────────────────────────────

SLIP_END     = 0xC0
SLIP_ESC     = 0xDB
SLIP_ESC_END = 0xDC
SLIP_ESC_ESC = 0xDD


def slip_decode(data: bytes) -> list:
    """SLIP 바이너리에서 패킷 목록 추출."""
    packets = []
    current = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == SLIP_END:
            if current:
                packets.append(bytes(current))
                current = bytearray()
        elif b == SLIP_ESC:
            i += 1
            if i < len(data):
                nb = data[i]
                if nb == SLIP_ESC_END:
                    current.append(SLIP_END)
                elif nb == SLIP_ESC_ESC:
                    current.append(SLIP_ESC)
                else:
                    current.append(nb)
        else:
            current.append(b)
        i += 1
    if current:
        packets.append(bytes(current))
    return packets


# ─────────────────────────────────────────────
# OSC 파서
# ─────────────────────────────────────────────

def _osc_str(data: bytes, offset: int):
    """OSC 문자열 (null 종료, 4바이트 정렬) 읽기."""
    end = data.index(0, offset)
    s = data[offset:end].decode("ascii", errors="replace")
    padded = (end + 4) & ~3
    return s, padded


def _osc_timetag(data: bytes, offset: int):
    """OSC 타임태그 (64비트 고정소수점) → float 초."""
    sec, frac = struct.unpack_from(">II", data, offset)
    return sec + frac / 2**32, offset + 8


def _parse_message(data: bytes, time: float):
    """OSC 메시지 파싱 → {'address', 'time', 'args'}"""
    try:
        address, offset = _osc_str(data, 0)
        if not address.startswith("/"):
            return None

        args = []
        if offset < len(data) and data[offset:offset + 1] == b",":
            type_str, offset = _osc_str(data, offset)
            for t in type_str[1:]:
                if t == "f":
                    args.append(struct.unpack_from(">f", data, offset)[0])
                    offset += 4
                elif t == "i":
                    args.append(struct.unpack_from(">i", data, offset)[0])
                    offset += 4
                elif t == "d":
                    args.append(struct.unpack_from(">d", data, offset)[0])
                    offset += 8
                elif t == "s":
                    val, offset = _osc_str(data, offset)
                    args.append(val)
                elif t == "t":
                    val, offset = _osc_timetag(data, offset)
                    args.append(val)
                elif t in ("T", "F"):
                    args.append(t == "T")
        return {"address": address, "time": time, "args": args}
    except Exception:
        return None


def parse_osc_packet(data: bytes, parent_time: float = 0.0) -> list:
    """OSC 번들 또는 메시지에서 메시지 목록 반환."""
    messages = []
    if data[:8] == b"#bundle\x00":
        try:
            time, offset = _osc_timetag(data, 8)
            while offset + 4 <= len(data):
                size = struct.unpack_from(">I", data, offset)[0]
                offset += 4
                if size == 0 or offset + size > len(data):
                    break
                messages.extend(parse_osc_packet(data[offset:offset + size], time))
                offset += size
        except Exception:
            pass
    else:
        msg = _parse_message(data, parent_time)
        if msg:
            messages.append(msg)
    return messages


# ─────────────────────────────────────────────
# 알려진 NGIMU OSC 주소 → 컬럼 헤더
# ─────────────────────────────────────────────

OSC_HEADERS = {
    "/battery":    ["Charge (%)", "Voltage (V)", "Current (mA)", "Temperature (°C)"],
    "/temperature":["Temperature (°C)"],
    "/humidity":   ["Humidity (%)"],
    "/barometer":  ["Pressure (hPa)"],
    "/magnetics":  ["Mag X (uT)", "Mag Y (uT)", "Mag Z (uT)"],
    "/inertial":   ["Gyro X (deg/s)", "Gyro Y (deg/s)", "Gyro Z (deg/s)",
                    "Accel X (g)",   "Accel Y (g)",    "Accel Z (g)"],
    "/sensors":    ["Gyro X (deg/s)", "Gyro Y (deg/s)", "Gyro Z (deg/s)",
                    "Accel X (g)",   "Accel Y (g)",    "Accel Z (g)",
                    "Mag X (uT)",    "Mag Y (uT)",     "Mag Z (uT)"],
    "/quaternion": ["W", "X", "Y", "Z"],
    "/euler":      ["Roll (deg)", "Pitch (deg)", "Yaw (deg)"],
    "/linear":     ["Linear Accel X (g)", "Linear Accel Y (g)", "Linear Accel Z (g)"],
    "/earth":      ["Earth Accel X (g)",  "Earth Accel Y (g)",  "Earth Accel Z (g)"],
    "/altitude":   ["Altitude (m)"],
    "/analogue":   [f"Analogue {i}" for i in range(1, 9)],
    "/rssi":       ["RSSI (dBm)"],
}


def seconds_to_hhmmss(t: float) -> str:
    td = timedelta(seconds=abs(t))
    total_s = int(td.total_seconds())
    h  = total_s // 3600
    m  = (total_s % 3600) // 60
    s  = total_s % 60
    ms = round((abs(t) - int(abs(t))) * 1000)
    sign = "-" if t < 0 else ""
    return f"{sign}{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ─────────────────────────────────────────────
# 변환 로직
# ─────────────────────────────────────────────

def convert_xio(xio_path: Path, dest_dir: Path, log):
    """XIO 바이너리 파일 → 타입별 CSV."""
    raw = xio_path.read_bytes()
    log(f"  파일 크기: {len(raw):,} bytes")

    packets = slip_decode(raw)
    log(f"  SLIP 패킷 수: {len(packets):,}")

    # 메시지 분류
    by_address = defaultdict(list)
    for pkt in packets:
        for msg in parse_osc_packet(pkt):
            by_address[msg["address"]].append(msg)

    if not by_address:
        log("  [경고] 파싱된 데이터가 없습니다.")
        return 0

    log(f"  발견된 데이터 타입: {', '.join(sorted(by_address.keys()))}")

    # 타입별 CSV 저장
    written = 0
    for address, messages in sorted(by_address.items()):
        safe_name = address.strip("/").replace("/", "_") or "root"
        out_path = dest_dir / f"{xio_path.stem}_{safe_name}.csv"

        # 컬럼 헤더 결정
        known = OSC_HEADERS.get(address)
        max_args = max((len(m["args"]) for m in messages), default=0)
        if known and len(known) >= max_args:
            value_headers = known[:max_args]
        else:
            value_headers = [f"Value_{i+1}" for i in range(max_args)]

        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Time (s)", "Time (HH:MM:SS.mmm)"] + value_headers)
            for msg in messages:
                t = msg["time"]
                row = [f"{t:.6f}", seconds_to_hhmmss(t)]
                row += [str(a) for a in msg["args"]]
                writer.writerow(row)

        log(f"  ✓ {out_path.name}  ({len(messages):,}행)")
        written += 1

    return written


def run_conversion(input_paths: list, dest_dir: Path, log, on_done):
    try:
        total = 0
        for p in input_paths:
            p = Path(p)
            log(f"\n▶ {p.name} 처리 중...")
            if not p.is_file():
                log("  [오류] 파일이 아닙니다.")
                continue
            if p.suffix.upper() != ".XIO":
                log(f"  [오류] .XIO 파일이 아닙니다: {p.suffix}")
                continue
            n = convert_xio(p, dest_dir, log)
            total += n
        on_done(total)
    except Exception as e:
        log(f"\n[오류] {e}")
        import traceback
        log(traceback.format_exc())
        on_done(0)


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

PLACEHOLDER = "Select SD card file(s)"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NGIMU XIO to CSV Converter v2.0")
        self.resizable(False, False)
        self._input_paths = []
        self._build_ui()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):
        P = {"padx": 8, "pady": 4}

        # SD Card File(s)
        tk.Label(self, text="SD Card File(s):").grid(row=0, column=0, sticky="e", **P)
        self.files_var = tk.StringVar()
        self.files_entry = tk.Entry(
            self, textvariable=self.files_var, width=52, fg="grey",
            relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4")
        self.files_entry.insert(0, PLACEHOLDER)
        self.files_entry.bind("<FocusIn>", self._clear_ph)
        self.files_entry.grid(row=0, column=1, sticky="ew", **P)
        tk.Button(self, text="...", width=3, command=self._browse_files).grid(row=0, column=2, **P)

        # Destination Directory
        tk.Label(self, text="Destination Directory:").grid(row=1, column=0, sticky="e", **P)
        self.dest_var = tk.StringVar(value=str(Path.home() / "Desktop"))
        tk.Entry(
            self, textvariable=self.dest_var, width=52,
            relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4"
        ).grid(row=1, column=1, sticky="ew", **P)
        tk.Button(self, text="...", width=3, command=self._browse_dest).grid(row=1, column=2, **P)

        # Convert 버튼
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=3, sticky="e", padx=8, pady=4)
        self.convert_btn = tk.Button(btn_frame, text="Convert", width=10, command=self._start)
        self.convert_btn.pack()

        # 로그창
        self.log_frame = tk.Frame(self)
        self.log_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 4))
        self.log_frame.grid_remove()
        self.log_text = tk.Text(
            self.log_frame, width=70, height=14, state="disabled",
            relief="flat", bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

        # 진행바
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=480)
        self.progress.grid(row=4, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="ew")
        self.progress.grid_remove()

    def _clear_ph(self, _):
        if self.files_entry.get() == PLACEHOLDER:
            self.files_entry.delete(0, "end")
            self.files_entry.config(fg="black")

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title="XIO 파일 선택",
            filetypes=[("XIO files", "*.xio *.XIO"), ("All files", "*.*")])
        if paths:
            self._input_paths = list(paths)
            self.files_entry.config(fg="black")
            self.files_var.set("; ".join(Path(p).name for p in paths))

    def _browse_dest(self):
        p = filedialog.askdirectory(title="출력 폴더 선택")
        if p:
            self.dest_var.set(p)

    def _log(self, msg: str):
        def _do():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _do)

    def _start(self):
        paths = self._input_paths or []
        if not paths:
            raw = self.files_var.get().strip()
            if raw and raw != PLACEHOLDER:
                paths = [p.strip() for p in raw.split(";") if p.strip()]
        if not paths:
            messagebox.showwarning("입력 없음", "XIO 파일을 선택하세요.")
            return

        dest = self.dest_var.get().strip()
        if not dest:
            messagebox.showwarning("출력 없음", "Destination Directory를 선택하세요.")
            return

        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)

        self.convert_btn.config(state="disabled")
        self.log_frame.grid()
        self.progress.grid()
        self.progress.start(10)

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self._log(f"변환 시작 | 파일 수: {len(paths)}")
        self._log(f"출력 경로: {dest_path}")

        def on_done(total):
            def _finish():
                self.progress.stop()
                self.progress.grid_remove()
                self.convert_btn.config(state="normal")
                if total > 0:
                    self._log(f"\n완료! CSV 파일 {total}개 생성됨.")
                    messagebox.showinfo("완료",
                        f"CSV {total}개 파일 생성 완료!\n\n출력 위치:\n{dest_path}")
                else:
                    self._log("\n변환된 파일이 없습니다.")
                    messagebox.showwarning("결과 없음", "변환된 데이터가 없습니다.")
            self.after(0, _finish)

        threading.Thread(
            target=run_conversion,
            args=(paths, dest_path, self._log, on_done),
            daemon=True
        ).start()


if __name__ == "__main__":
    App().mainloop()
