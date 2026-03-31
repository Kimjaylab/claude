#!/usr/bin/env python3
"""
NGIMU XIO to CSV Converter - GUI v3.0
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
# 출력할 OSC 주소와 컬럼 헤더 (순서 유지)
# ─────────────────────────────────────────────

GPS_ADDRESS = "/gps"

WANTED_ADDRESSES = {
    "/humidity":    ["Humidity (%)"],
    "/quaternion":  ["W", "X", "Y", "Z"],
    "/sensors":     ["Gyro X (deg/s)", "Gyro Y (deg/s)", "Gyro Z (deg/s)",
                     "Accel X (g)",   "Accel Y (g)",    "Accel Z (g)",
                     "Mag X (uT)",    "Mag Y (uT)",     "Mag Z (uT)"],
    "/temperature": ["Temperature (°C)"],
}


def seconds_to_hhmmss(t: float) -> str:
    total_s = int(abs(t))
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    sign = "-" if t < 0 else ""
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


def seconds_to_ms(t: float) -> str:
    """초 → ms 정수 문자열."""
    return str(round(t * 1000))


# ─────────────────────────────────────────────
# 변환 로직
# ─────────────────────────────────────────────

def _find_closest(msgs: list, t: float):
    """
    시각 t에 가장 가까운 메시지 args 반환.
    이진 탐색으로 O(log n) 처리.
    """
    if not msgs:
        return None
    lo, hi = 0, len(msgs) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if msgs[mid]["time"] < t:
            lo = mid + 1
        else:
            hi = mid
    candidates = [lo]
    if lo > 0:
        candidates.append(lo - 1)
    best = min(candidates, key=lambda i: abs(msgs[i]["time"] - t))
    return msgs[best]["args"]


def _forward_fill(msgs: list, t: float):
    """시각 t 이하의 가장 최근 메시지 args 반환 (이진 탐색)."""
    lo, hi, result = 0, len(msgs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if msgs[mid]["time"] <= t:
            result = msgs[mid]["args"]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def _fmt_time(t: float, fmt: str) -> str:
    return seconds_to_ms(t) if fmt == "tick_ms" else seconds_to_hhmmss(t)


def convert_xio(xio_path: Path, dest_dir: Path, log, opts: dict):
    """XIO 바이너리 파일 → 통합 CSV 1개."""
    raw = xio_path.read_bytes()
    log(f"  파일 크기: {len(raw):,} bytes")

    packets = slip_decode(raw)
    log(f"  SLIP 패킷 수: {len(packets):,}")

    # 주소별 메시지 수집 후 시간순 정렬
    by_address = defaultdict(list)
    for pkt in packets:
        for msg in parse_osc_packet(pkt):
            by_address[msg["address"]].append(msg)
    for addr in by_address:
        by_address[addr].sort(key=lambda m: m["time"])

    if not by_address:
        log("  [경고] 파싱된 데이터가 없습니다.")
        return 0

    # NTP 절대시각 → 녹화 시작 기준 상대시각 정규화
    valid_times = [m["time"] for msgs in by_address.values() for m in msgs if m["time"] > 0]
    t0 = min(valid_times) if valid_times else 0.0
    if t0 > 0:
        for msgs in by_address.values():
            for m in msgs:
                if m["time"] > 0:
                    m["time"] -= t0
    log(f"  시작 시각 기준 정규화 완료 (t0 = {t0:.2f}s)")
    log(f"  파일 내 전체 주소: {', '.join(sorted(by_address.keys()))}")

    # ms 단위 시간값 존재 여부 확인
    has_ms_precision = any(
        (m["time"] % 1.0) != 0.0
        for msgs in by_address.values() for m in msgs if m["time"] > 0
    )
    log(f"  ms 단위 시간값: {'있음' if has_ms_precision else '없음 (초 단위만)'}")

    # GPS 확인
    gps_msgs = by_address.get(GPS_ADDRESS, [])
    if gps_msgs:
        log(f"  GPS ({GPS_ADDRESS}): {len(gps_msgs):,}개")
    else:
        log(f"  [경고] GPS 데이터({GPS_ADDRESS}) 없음")

    for addr, cols in WANTED_ADDRESSES.items():
        n = len(by_address.get(addr, []))
        log(f"  {addr}: {n:,}개" if n else f"  [없음] {addr}")

    # 옵션 파싱
    time_fmt      = opts.get("time_format", "hhmmss")   # "hhmmss" | "tick_ms"
    save_hz       = opts.get("save_hz", 0.0)
    use_period    = save_hz > 0
    enabled_ch    = opts.get("enabled_channels", set(WANTED_ADDRESSES.keys()) | {GPS_ADDRESS})
    encoding      = "utf-8-sig" if opts.get("utf8bom", True) else "utf-8"

    # 활성화된 센서 컬럼 구성
    col_specs = [
        (addr, cols)
        for addr, cols in WANTED_ADDRESSES.items()
        if addr in by_address and addr in enabled_ch
    ]
    has_gps = bool(gps_msgs) and (GPS_ADDRESS in enabled_ch)

    # 시간 헤더
    time_header = "Time (ms)" if time_fmt == "tick_ms" else "Time (HH:MM:SS)"
    gps_headers = ["Latitude", "Longitude"] if has_gps else []
    headers = [time_header] + gps_headers + [c for _, cols in col_specs for c in cols]

    # 출력 파일명: 시간 형식 + 저장 주기 포함 (중복 방지)
    fmt_tag = "ms" if time_fmt == "tick_ms" else "hhmmss"
    hz_tag  = f"_{save_hz:g}Hz" if use_period else ""
    # 채널 약어 (전체 선택 시 태그 없음, 일부만 선택 시 약어 나열)
    ALL_CH = {GPS_ADDRESS} | set(WANTED_ADDRESSES.keys())
    CH_ABBR = {
        GPS_ADDRESS:    "gps",
        "/sensors":     "sen",
        "/quaternion":  "quat",
        "/humidity":    "hum",
        "/temperature": "temp",
    }
    CH_ORDER = [GPS_ADDRESS, "/sensors", "/quaternion", "/humidity", "/temperature"]
    if enabled_ch >= ALL_CH:
        ch_tag = ""
    else:
        ch_tag = "_" + "-".join(CH_ABBR[a] for a in CH_ORDER if a in enabled_ch)
    out_path = dest_dir / f"{xio_path.stem}_{fmt_tag}{hz_tag}{ch_tag}.csv"

    # ── 타임라인 결정 ───────────────────────────
    # HH:MM:SS 형식은 초 단위 해상도 → Hz 미설정이어도 1Hz 최근접값 사용
    if use_period or time_fmt == "hhmmss":
        period = 1.0 / save_hz if use_period else 1.0
        t_max = max(m["time"] for msgs in by_address.values() for m in msgs if m["time"] > 0)
        n_steps = int(t_max / period) + 1
        if use_period:
            log(f"  저장 주기: {save_hz}Hz  간격: {period*1000:.1f}ms  총 {n_steps}행")
        else:
            log(f"  HH:MM:SS 형식 → 1Hz 자동 적용  총 {n_steps}행")
        with open(out_path, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for i in range(n_steps):
                t = i * period
                row = [_fmt_time(t, time_fmt)]

                # GPS
                if has_gps:
                    args = _find_closest(gps_msgs, t)
                    row += ([f"{args[0]:.7f}", f"{args[1]:.7f}"]
                            if args and len(args) >= 2 else ["", ""])

                # 센서
                for addr, cols in col_specs:
                    args = _find_closest(by_address[addr], t) or []
                    row += [str(args[k]) if k < len(args) else "" for k in range(len(cols))]

                writer.writerow(row)

        log(f"  ✓ {out_path.name}  ({n_steps:,}행, {len(headers)}개 컬럼)")
        return 1

    else:
        # 원시 타임라인: GPS 또는 가장 많은 센서 기준 + forward-fill
        if has_gps:
            primary = gps_msgs
            primary_is_gps = True
        else:
            available = {a: by_address[a] for a in WANTED_ADDRESSES
                         if a in by_address and a in enabled_ch}
            if not available:
                log("  [경고] 사용 가능한 데이터가 없습니다.")
                return 0
            primary_addr = max(available, key=lambda a: len(available[a]))
            primary = available[primary_addr]
            primary_is_gps = False
            log(f"  {primary_addr}를 주 타임라인으로 사용")

        with open(out_path, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for msg in primary:
                t = msg["time"]
                row = [_fmt_time(t, time_fmt)]

                # GPS
                if has_gps:
                    if primary_is_gps and len(msg["args"]) >= 2:
                        row += [f"{msg['args'][0]:.7f}", f"{msg['args'][1]:.7f}"]
                    else:
                        args = _forward_fill(gps_msgs, t)
                        row += ([f"{args[0]:.7f}", f"{args[1]:.7f}"]
                                if args and len(args) >= 2 else ["", ""])

                # 센서 (forward-fill)
                for addr, cols in col_specs:
                    args = _forward_fill(by_address[addr], t) or []
                    row += [str(args[k]) if k < len(args) else "" for k in range(len(cols))]

                writer.writerow(row)

        log(f"  ✓ {out_path.name}  ({len(primary):,}행, {len(headers)}개 컬럼)")
        return 1


def run_conversion(input_paths: list, dest_dir: Path, log, on_done, opts: dict):
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
            n = convert_xio(p, dest_dir, log, opts)
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
        self.title("NGIMU XIO to CSV Converter v3.0")
        self.resizable(True, False)
        self._input_paths = []
        self._build_ui()
        self._center()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        P = {"padx": 8, "pady": 3}

        # ── Input / Output ──────────────────────────
        io_frame = tk.LabelFrame(self, text="Input / Output", padx=6, pady=4)
        io_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        io_frame.columnconfigure(1, weight=1)

        tk.Label(io_frame, text="SD Card File(s):").grid(row=0, column=0, sticky="e", **P)
        self.files_var = tk.StringVar()
        self.files_entry = tk.Entry(
            io_frame, textvariable=self.files_var, width=55, fg="grey",
            relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4")
        self.files_entry.insert(0, PLACEHOLDER)
        self.files_entry.bind("<FocusIn>", self._clear_ph)
        self.files_entry.grid(row=0, column=1, sticky="ew", **P)
        tk.Button(io_frame, text="...", width=3,
                  command=self._browse_files).grid(row=0, column=2, **P)

        tk.Label(io_frame, text="Destination Directory:").grid(row=1, column=0, sticky="e", **P)
        self.dest_var = tk.StringVar(value=str(Path.home() / "Desktop"))
        tk.Entry(
            io_frame, textvariable=self.dest_var, width=55,
            relief="flat", highlightthickness=1,
            highlightbackground="#aaa", highlightcolor="#0078d4"
        ).grid(row=1, column=1, sticky="ew", **P)
        tk.Button(io_frame, text="...", width=3,
                  command=self._browse_dest).grid(row=1, column=2, **P)

        # ── Save Options (스크롤 가능) ──────────────
        opts_outer = tk.LabelFrame(self, text="Save Options", padx=6, pady=4)
        opts_outer.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        opts_outer.columnconfigure(0, weight=1)

        canvas = tk.Canvas(opts_outer, height=240, highlightthickness=0)
        vsb = tk.Scrollbar(opts_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.opts_frame = tk.Frame(canvas)
        self.opts_frame.columnconfigure(0, weight=1)
        win_id = canvas.create_window((0, 0), window=self.opts_frame, anchor="nw")

        self.opts_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        # 마우스 휠 스크롤
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._build_options(self.opts_frame)

        # ── Convert 버튼 ────────────────────────────
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=2, column=0, sticky="e", padx=10, pady=4)
        self.convert_btn = tk.Button(btn_frame, text="Convert", width=14,
                                     command=self._start)
        self.convert_btn.pack()

        # ── 로그창 ──────────────────────────────────
        self.log_frame = tk.Frame(self)
        self.log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 4))
        self.log_frame.grid_remove()
        self.log_text = tk.Text(
            self.log_frame, width=72, height=14, state="disabled",
            relief="flat", bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

        # ── 진행바 ──────────────────────────────────
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=500)
        self.progress.grid(row=4, column=0, padx=10, pady=(0, 8), sticky="ew")
        self.progress.grid_remove()

    # ────────────────────────────────────────────
    # 옵션 패널 구성 (항목 추가/수정 용이하도록 섹션별 분리)
    # ────────────────────────────────────────────

    def _build_options(self, parent):
        P = {"padx": 6, "pady": 2}
        r = 0

        # ── 섹션 1: 시간 형식 ────────────────────
        tf = tk.LabelFrame(parent, text="Time Format", padx=6, pady=4)
        tf.grid(row=r, column=0, sticky="ew", padx=4, pady=(4, 2))
        tf.columnconfigure(2, weight=1)
        r += 1

        self.time_fmt_var = tk.StringVar(value="hhmmss")
        tk.Radiobutton(tf, text="HH:MM:SS  (시:분:초)",
                       variable=self.time_fmt_var, value="hhmmss").grid(
                       row=0, column=0, sticky="w", padx=10)
        tk.Radiobutton(tf, text="Tick (ms)  (밀리초 정수)",
                       variable=self.time_fmt_var, value="tick_ms").grid(
                       row=0, column=1, sticky="w", padx=10)

        # ── 섹션 2: 저장 주기 ────────────────────
        pf = tk.LabelFrame(parent, text="Save Period", padx=6, pady=4)
        pf.grid(row=r, column=0, sticky="ew", padx=4, pady=2)
        pf.columnconfigure(3, weight=1)
        r += 1

        self.use_period_var = tk.BooleanVar(value=False)
        tk.Checkbutton(pf, text="고정 주기 활성화:",
                       variable=self.use_period_var,
                       command=self._on_period_toggle).grid(
                       row=0, column=0, sticky="w")

        self.hz_var = tk.StringVar(value="1")
        self.hz_entry = tk.Entry(pf, textvariable=self.hz_var, width=8,
                                 state="disabled", relief="flat",
                                 highlightthickness=1, highlightbackground="#aaa")
        self.hz_entry.grid(row=0, column=1, padx=4)
        tk.Label(pf, text="Hz").grid(row=0, column=2, sticky="w")

        self.period_info_lbl = tk.Label(pf, text="", fg="grey", font=("Arial", 8))
        self.period_info_lbl.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 2))

        self.hz_var.trace_add("write", self._update_period_info)
        self._on_period_toggle()

        # ── 섹션 3: 데이터 채널 선택 ─────────────
        cf = tk.LabelFrame(parent, text="Data Channels", padx=6, pady=4)
        cf.grid(row=r, column=0, sticky="ew", padx=4, pady=2)
        r += 1

        CHANNELS = [
            (GPS_ADDRESS,    "GPS (Lat / Lon)"),
            ("/sensors",     "Sensors  (Gyro / Accel / Mag)"),
            ("/quaternion",  "Quaternion  (W / X / Y / Z)"),
            ("/humidity",    "Humidity"),
            ("/temperature", "Temperature"),
        ]
        self.ch_vars = {}
        for idx, (addr, label) in enumerate(CHANNELS):
            v = tk.BooleanVar(value=True)
            self.ch_vars[addr] = v
            tk.Checkbutton(cf, text=label, variable=v).grid(
                row=idx // 2, column=idx % 2, sticky="w", padx=10, pady=1)

        # ── 섹션 4: 출력 옵션 ────────────────────
        of = tk.LabelFrame(parent, text="Output Options", padx=6, pady=4)
        of.grid(row=r, column=0, sticky="ew", padx=4, pady=(2, 6))
        r += 1

        self.utf8bom_var = tk.BooleanVar(value=True)
        tk.Checkbutton(of, text="UTF-8 BOM 포함  (Excel 한글 호환)",
                       variable=self.utf8bom_var).grid(
                       row=0, column=0, sticky="w", padx=10)

        self.open_after_var = tk.BooleanVar(value=False)
        tk.Checkbutton(of, text="변환 완료 후 출력 폴더 열기",
                       variable=self.open_after_var).grid(
                       row=0, column=1, sticky="w", padx=10)

    # ────────────────────────────────────────────
    # 콜백
    # ────────────────────────────────────────────

    def _on_period_toggle(self):
        if self.use_period_var.get():
            self.hz_entry.config(state="normal")
            self._update_period_info()
        else:
            self.hz_entry.config(state="disabled")
            self.period_info_lbl.config(
                text="주기 미설정: 원시 데이터 타임라인 사용 (GPS 또는 최다 센서 기준)",
                fg="grey")

    def _update_period_info(self, *_):
        if not self.use_period_var.get():
            return
        try:
            hz = float(self.hz_var.get())
            if hz <= 0:
                raise ValueError
            ms = 1000.0 / hz
            self.period_info_lbl.config(
                text=f"간격 {ms:.2f} ms → 초당 최대 {hz:.0f}개 저장  "
                     f"(평균 없음, 해당 시각에 가장 가까운 값 1개 사용)",
                fg="#0055aa")
        except ValueError:
            self.period_info_lbl.config(text="Hz 값이 올바르지 않습니다.", fg="red")

    def _get_opts(self) -> dict:
        opts = {
            "time_format":      self.time_fmt_var.get(),
            "save_hz":          0.0,
            "enabled_channels": {addr for addr, v in self.ch_vars.items() if v.get()},
            "utf8bom":          self.utf8bom_var.get(),
            "open_after":       self.open_after_var.get(),
        }
        if self.use_period_var.get():
            try:
                hz = float(self.hz_var.get())
                if hz > 0:
                    opts["save_hz"] = hz
            except ValueError:
                pass
        return opts

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

        opts = self._get_opts()
        if self.use_period_var.get() and opts["save_hz"] == 0.0:
            messagebox.showwarning("주기 오류", "저장 주기(Hz)를 올바르게 입력하세요.")
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
        self._log(f"시간 형식: {'Tick (ms)' if opts['time_format'] == 'tick_ms' else 'HH:MM:SS'}")
        if opts["save_hz"] > 0:
            self._log(f"저장 주기: {opts['save_hz']}Hz  ({1000/opts['save_hz']:.2f}ms 간격, 최근접값)")
        else:
            self._log("저장 주기: 원시 타임라인 사용")

        def on_done(total):
            def _finish():
                self.progress.stop()
                self.progress.grid_remove()
                self.convert_btn.config(state="normal")
                if total > 0:
                    self._log(f"\n완료! CSV 파일 {total}개 생성됨.")
                    messagebox.showinfo("완료",
                        f"CSV {total}개 파일 생성 완료!\n\n출력 위치:\n{dest_path}")
                    if opts.get("open_after") and sys.platform == "win32":
                        os.startfile(dest_path)
                else:
                    self._log("\n변환된 파일이 없습니다.")
                    messagebox.showwarning("결과 없음", "변환된 데이터가 없습니다.")
            self.after(0, _finish)

        threading.Thread(
            target=run_conversion,
            args=(paths, dest_path, self._log, on_done, opts),
            daemon=True
        ).start()


if __name__ == "__main__":
    App().mainloop()
