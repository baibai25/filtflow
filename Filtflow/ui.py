"""設定 UI（tkinter）

デバイス選択・フィルタパラメータのスライダー・レベルメーターを提供する。
スライダー操作中にリアルタイムで update_params() を呼び出し即時反映する。
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_stream import (
    AudioStream,
    find_device_index,
    list_input_devices,
    list_output_devices,
)
from compressor import (
    COMP_DEFAULT_ATTACK_MS,
    COMP_DEFAULT_OUTPUT_GAIN_DB,
    COMP_DEFAULT_RATIO,
    COMP_DEFAULT_RELEASE_MS,
    COMP_DEFAULT_THRESHOLD_DB,
    COMP_MAX_ATK_MS,
    COMP_MAX_OUTPUT_GAIN,
    COMP_MAX_RATIO,
    COMP_MAX_RLS_MS,
    COMP_MIN_ATK_RLS_MS,
    COMP_MIN_OUTPUT_GAIN,
    COMP_MIN_RATIO,
    COMP_MIN_THRESHOLD_DB,
    Compressor,
)
from config import Config
from expander import (
    DETECTOR_PEAK,
    DETECTOR_RMS,
    EXP_DEFAULT_ATTACK_MS,
    EXP_DEFAULT_OUTPUT_GAIN_DB,
    EXP_DEFAULT_RATIO,
    EXP_DEFAULT_RELEASE_MS,
    EXP_DEFAULT_THRESHOLD_DB,
    EXP_MAX_ATK_MS,
    EXP_MAX_OUTPUT_GAIN,
    EXP_MAX_RATIO,
    EXP_MAX_RLS_MS,
    EXP_MIN_ATK_RLS_MS,
    EXP_MIN_OUTPUT_GAIN,
    EXP_MIN_RATIO,
    EXP_MIN_THRESHOLD_DB,
    GATE_DEFAULT_RATIO,
    GATE_DEFAULT_RELEASE_MS,
    PRESET_EXPANDER,
    PRESET_GATE,
    Expander,
)

# --- OBS 準拠レベルメーターの色しきい値 ---
METER_GREEN_MAX_DB: float = -20.0   # -60 〜 -20 dBFS: 緑
METER_YELLOW_MAX_DB: float = -9.0   # -20 〜 -9 dBFS:  黄
# -9 〜 0 dBFS: 赤
COLOR_GREEN: str = "#00cc00"
COLOR_YELLOW: str = "#ffff00"
COLOR_RED: str = "#ff0000"
COLOR_BACKGROUND: str = "#1a1a1a"

METER_MIN_DB: float = -60.0
METER_MAX_DB: float = 0.0
METER_UPDATE_MS: int = 30
PEAK_HOLD_SEC: float = 2.0


class LevelMeter(tk.Frame):
    """OBS 準拠配色の OUT レベルメーター。

    フィルタ後の音声レベルを 30ms ごとに更新し、2 秒ピーク保持で表示する。
    """

    def __init__(self, parent: tk.Widget, level_queue: queue.Queue[float]) -> None:
        super().__init__(parent, bg=COLOR_BACKGROUND)
        self._queue = level_queue
        self._level_db: float = METER_MIN_DB
        self._peak_db: float = METER_MIN_DB
        self._peak_counter: int = 0
        self._peak_hold_frames: int = int(PEAK_HOLD_SEC * 1000 / METER_UPDATE_MS)

        # ラベル行
        header = tk.Frame(self, bg=COLOR_BACKGROUND)
        header.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(header, text="OUT", fg="white", bg=COLOR_BACKGROUND, width=4).pack(
            side="left"
        )
        self._label_db = tk.Label(
            header, text="-60.0 dB", fg="white", bg=COLOR_BACKGROUND, width=10
        )
        self._label_db.pack(side="right")
        self._label_peak = tk.Label(
            header, text="peak: -60.0 dB", fg="#aaaaaa", bg=COLOR_BACKGROUND, width=16
        )
        self._label_peak.pack(side="right")

        # キャンバス（メーターバー）
        self._canvas = tk.Canvas(
            self, height=16, bg="#333333", highlightthickness=0
        )
        self._canvas.pack(fill="x", padx=4, pady=(2, 4))

        self._update()

    def _db_to_x(self, db: float, width: int) -> int:
        """dB 値をキャンバス上の x 座標に変換する（対数スケール）。"""
        clamped = max(METER_MIN_DB, min(METER_MAX_DB, db))
        ratio = (clamped - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)
        return int(ratio * width)

    def _update(self) -> None:
        """30ms ごとにキューを読み出してメーターを再描画する。"""
        # キューから最新の値を取得（複数積まれていれば最後の値を使う）
        latest_db = self._level_db
        try:
            while True:
                latest_db = self._queue.get_nowait()
        except queue.Empty:
            pass
        self._level_db = latest_db

        # ピーク保持
        if self._level_db >= self._peak_db:
            self._peak_db = self._level_db
            self._peak_counter = 0
        else:
            self._peak_counter += 1
            if self._peak_counter > self._peak_hold_frames:
                self._peak_db = self._level_db
                self._peak_counter = 0

        # 描画
        self._draw()

        # ラベル更新
        self._label_db.config(text=f"{self._level_db:+.1f} dB")
        self._label_peak.config(text=f"peak: {self._peak_db:+.1f} dB")

        self.after(METER_UPDATE_MS, self._update)

    def _draw(self) -> None:
        self._canvas.delete("all")
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w <= 1:
            return

        # 区切り x 座標
        x_green = self._db_to_x(METER_GREEN_MAX_DB, w)   # -20 dBFS
        x_yellow = self._db_to_x(METER_YELLOW_MAX_DB, w)  # -9 dBFS
        x_level = self._db_to_x(self._level_db, w)
        x_peak = self._db_to_x(self._peak_db, w)

        # 緑区間
        end_green = min(x_level, x_green)
        if end_green > 0:
            self._canvas.create_rectangle(0, 0, end_green, h, fill=COLOR_GREEN, outline="")

        # 黄区間
        if x_level > x_green:
            end_yellow = min(x_level, x_yellow)
            self._canvas.create_rectangle(
                x_green, 0, end_yellow, h, fill=COLOR_YELLOW, outline=""
            )

        # 赤区間
        if x_level > x_yellow:
            self._canvas.create_rectangle(
                x_yellow, 0, x_level, h, fill=COLOR_RED, outline=""
            )

        # ピーク線
        if 0 < x_peak < w:
            peak_color = (
                COLOR_RED
                if self._peak_db > METER_YELLOW_MAX_DB
                else COLOR_YELLOW
                if self._peak_db > METER_GREEN_MAX_DB
                else COLOR_GREEN
            )
            self._canvas.create_line(x_peak, 0, x_peak, h, fill=peak_color, width=2)


class _SliderRow(tk.Frame):
    """ラベル + スライダー + 値表示の 1 行コンポーネント。"""

    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        from_: float,
        to: float,
        resolution: float,
        initial: float,
        unit: str,
        on_change: Callable[[float], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._on_change = on_change
        self._unit = unit

        tk.Label(self, text=label, width=14, anchor="w").pack(side="left")
        self._var = tk.DoubleVar(value=initial)
        self._var.trace_add("write", self._on_trace)
        tk.Scale(
            self,
            variable=self._var,
            from_=from_,
            to=to,
            resolution=resolution,
            orient="horizontal",
            length=180,
            showvalue=False,
        ).pack(side="left")
        range_text = f"({from_:.0f}-{to:.0f}{unit})"
        self._val_label = tk.Label(self, text=self._format(initial), width=18, anchor="w")
        self._val_label.pack(side="left")
        tk.Label(self, text=range_text, fg="#888888", anchor="w").pack(side="left")

    def _format(self, v: float) -> str:
        return f"{v:.1f} {self._unit}"

    def _on_trace(self, *_: object) -> None:
        v = self._var.get()
        self._val_label.config(text=self._format(v))
        self._on_change(v)

    def set(self, value: float) -> None:
        self._var.set(value)


class SettingsWindow(tk.Toplevel):
    """Filtflow 設定ウィンドウ。

    デバイス選択・フィルタパラメータ・レベルメーターを提供する。
    スライダー操作中にリアルタイムでフィルタパラメータを更新する。
    """

    def __init__(
        self,
        master: tk.Tk,
        config: Config,
        compressor: Compressor,
        expander: Expander,
        stream: AudioStream,
        level_queue: queue.Queue[float],
    ) -> None:
        super().__init__(master)
        self._config = config
        self._compressor = compressor
        self._expander = expander
        self._stream = stream

        self.title("Filtflow 設定")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self._build_ui(level_queue)
        self._refresh_device_lists()

    def _build_ui(self, level_queue: queue.Queue[float]) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- レベルメーター ---
        meter_frame = tk.LabelFrame(self, text="レベルメーター")
        meter_frame.pack(fill="x", **pad)
        LevelMeter(meter_frame, level_queue).pack(fill="x")

        # --- デバイス設定 ---
        dev_frame = tk.LabelFrame(self, text="デバイス設定")
        dev_frame.pack(fill="x", **pad)

        tk.Label(dev_frame, text="入力デバイス:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=6, pady=2
        )
        self._input_var = tk.StringVar(value=self._config.input_device_name)
        self._input_combo = ttk.Combobox(
            dev_frame, textvariable=self._input_var, width=40, state="readonly"
        )
        self._input_combo.grid(row=0, column=1, padx=6, pady=2)
        self._input_combo.bind("<<ComboboxSelected>>", self._on_device_change)

        tk.Label(dev_frame, text="出力デバイス:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=6, pady=2
        )
        self._output_var = tk.StringVar(value=self._config.output_device_name)
        self._output_combo = ttk.Combobox(
            dev_frame, textvariable=self._output_var, width=40, state="readonly"
        )
        self._output_combo.grid(row=1, column=1, padx=6, pady=2)
        self._output_combo.bind("<<ComboboxSelected>>", self._on_device_change)

        # --- Compressor ---
        comp_frame = tk.LabelFrame(self, text="Compressor")
        comp_frame.pack(fill="x", **pad)

        self._comp_enabled = tk.BooleanVar(value=self._config.compressor.enabled)
        tk.Checkbutton(
            comp_frame, text="有効", variable=self._comp_enabled,
            command=self._on_comp_enabled_change,
        ).pack(anchor="e", padx=6)

        self._comp_ratio = _SliderRow(
            comp_frame, "Ratio", COMP_MIN_RATIO, COMP_MAX_RATIO, 0.5,
            self._config.compressor.ratio, ":1",
            lambda v: self._compressor.update_params(ratio=v),
        )
        self._comp_ratio.pack(fill="x", padx=6, pady=1)

        self._comp_threshold = _SliderRow(
            comp_frame, "Threshold", COMP_MIN_THRESHOLD_DB, 0.0, 0.5,
            self._config.compressor.threshold_db, "dB",
            lambda v: self._compressor.update_params(threshold=v),
        )
        self._comp_threshold.pack(fill="x", padx=6, pady=1)

        self._comp_attack = _SliderRow(
            comp_frame, "Attack", COMP_MIN_ATK_RLS_MS, COMP_MAX_ATK_MS, 1,
            self._config.compressor.attack_ms, "ms",
            lambda v: self._compressor.update_params(attack_ms=int(v)),
        )
        self._comp_attack.pack(fill="x", padx=6, pady=1)

        self._comp_release = _SliderRow(
            comp_frame, "Release", COMP_MIN_ATK_RLS_MS, COMP_MAX_RLS_MS, 5,
            self._config.compressor.release_ms, "ms",
            lambda v: self._compressor.update_params(release_ms=int(v)),
        )
        self._comp_release.pack(fill="x", padx=6, pady=1)

        self._comp_output_gain = _SliderRow(
            comp_frame, "Output Gain", COMP_MIN_OUTPUT_GAIN, COMP_MAX_OUTPUT_GAIN, 0.5,
            self._config.compressor.output_gain_db, "dB",
            lambda v: self._compressor.update_params(output_gain_db=v),
        )
        self._comp_output_gain.pack(fill="x", padx=6, pady=1)

        # --- Expander ---
        exp_frame = tk.LabelFrame(self, text="Expander")
        exp_frame.pack(fill="x", **pad)

        self._exp_enabled = tk.BooleanVar(value=self._config.expander.enabled)
        tk.Checkbutton(
            exp_frame, text="有効", variable=self._exp_enabled,
            command=self._on_exp_enabled_change,
        ).pack(anchor="e", padx=6)

        preset_row = tk.Frame(exp_frame)
        preset_row.pack(fill="x", padx=6, pady=1)
        tk.Label(preset_row, text="Preset", width=14, anchor="w").pack(side="left")
        self._exp_preset_var = tk.StringVar(value=self._config.expander.preset)
        ttk.Combobox(
            preset_row, textvariable=self._exp_preset_var,
            values=[PRESET_EXPANDER, PRESET_GATE], width=12, state="readonly",
        ).pack(side="left")
        self._exp_preset_var.trace_add("write", self._on_preset_change)

        self._exp_ratio = _SliderRow(
            exp_frame, "Ratio", EXP_MIN_RATIO, EXP_MAX_RATIO, 0.5,
            self._config.expander.ratio, ":1",
            lambda v: self._expander.update_params(ratio=v),
        )
        self._exp_ratio.pack(fill="x", padx=6, pady=1)

        self._exp_threshold = _SliderRow(
            exp_frame, "Threshold", EXP_MIN_THRESHOLD_DB, 0.0, 0.5,
            self._config.expander.threshold_db, "dB",
            lambda v: self._expander.update_params(threshold=v),
        )
        self._exp_threshold.pack(fill="x", padx=6, pady=1)

        self._exp_attack = _SliderRow(
            exp_frame, "Attack", EXP_MIN_ATK_RLS_MS, EXP_MAX_ATK_MS, 1,
            self._config.expander.attack_ms, "ms",
            lambda v: self._expander.update_params(attack_ms=int(v)),
        )
        self._exp_attack.pack(fill="x", padx=6, pady=1)

        self._exp_release = _SliderRow(
            exp_frame, "Release", EXP_MIN_ATK_RLS_MS, EXP_MAX_RLS_MS, 5,
            self._config.expander.release_ms, "ms",
            lambda v: self._expander.update_params(release_ms=int(v)),
        )
        self._exp_release.pack(fill="x", padx=6, pady=1)

        self._exp_output_gain = _SliderRow(
            exp_frame, "Output Gain", EXP_MIN_OUTPUT_GAIN, EXP_MAX_OUTPUT_GAIN, 0.5,
            self._config.expander.output_gain_db, "dB",
            lambda v: self._expander.update_params(output_gain_db=v),
        )
        self._exp_output_gain.pack(fill="x", padx=6, pady=1)

        detector_row = tk.Frame(exp_frame)
        detector_row.pack(fill="x", padx=6, pady=1)
        tk.Label(detector_row, text="Detector", width=14, anchor="w").pack(side="left")
        self._exp_detector_var = tk.StringVar(value=self._config.expander.detector)
        ttk.Combobox(
            detector_row, textvariable=self._exp_detector_var,
            values=[DETECTOR_RMS, DETECTOR_PEAK], width=12, state="readonly",
        ).pack(side="left")
        self._exp_detector_var.trace_add("write", self._on_detector_change)

        # --- ボタン行 ---
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", **pad)
        tk.Button(btn_frame, text="保存", width=12, command=self._on_save).pack(
            side="left", padx=4
        )
        tk.Button(
            btn_frame, text="デフォルトに戻す", width=16, command=self._on_reset
        ).pack(side="left", padx=4)

        # --- エラー表示ラベル ---
        self._error_label = tk.Label(self, text="", fg="red")
        self._error_label.pack(fill="x", padx=8)

    def _refresh_device_lists(self) -> None:
        """デバイス一覧を再取得してコンボボックスを更新する。"""
        in_names = [str(d["name"]) for d in list_input_devices()]
        out_names = [str(d["name"]) for d in list_output_devices()]
        self._input_combo["values"] = in_names
        self._output_combo["values"] = out_names

    def show_error(self, msg: str) -> None:
        self._error_label.config(text=msg)

    def clear_error(self) -> None:
        self._error_label.config(text="")

    # --- イベントハンドラ ---

    def _on_device_change(self, _event: object = None) -> None:
        in_name = self._input_var.get()
        out_name = self._output_var.get()
        in_idx = find_device_index(in_name, is_input=True)
        out_idx = find_device_index(out_name, is_input=False)
        try:
            self._stream.update_devices(in_idx, out_idx)
            self._config.input_device_name = in_name
            self._config.output_device_name = out_name
            self.clear_error()
        except Exception as exc:
            self.show_error(f"デバイスエラー: {exc}")

    def _on_comp_enabled_change(self) -> None:
        enabled = self._comp_enabled.get()
        self._config.compressor.enabled = enabled
        self._compressor.enabled = enabled

    def _on_exp_enabled_change(self) -> None:
        enabled = self._exp_enabled.get()
        self._config.expander.enabled = enabled
        self._expander.enabled = enabled

    def _on_preset_change(self, *_: object) -> None:
        preset = self._exp_preset_var.get()
        self._expander.update_params(preset=preset)
        self._config.expander.preset = preset

        # プリセットに対応するデフォルト値をスライダーとフィルタに適用する。
        # ratio と release_ms がプリセット間で異なる（設計書 §3.2 参照）。
        if preset == PRESET_GATE:
            ratio: float = GATE_DEFAULT_RATIO
            release_ms: int = GATE_DEFAULT_RELEASE_MS
        else:
            ratio = EXP_DEFAULT_RATIO
            release_ms = EXP_DEFAULT_RELEASE_MS

        self._exp_ratio.set(ratio)
        self._exp_release.set(float(release_ms))
        self._expander.update_params(ratio=ratio, release_ms=release_ms)

    def _on_detector_change(self, *_: object) -> None:
        detector = self._exp_detector_var.get()
        self._expander.update_params(detector=detector)
        self._config.expander.detector = detector

    def _on_save(self) -> None:
        """現在の UI 値を config に反映して JSON 保存する。"""
        c = self._config.compressor
        c.enabled = self._comp_enabled.get()
        c.ratio = self._comp_ratio._var.get()
        c.threshold_db = self._comp_threshold._var.get()
        c.attack_ms = int(self._comp_attack._var.get())
        c.release_ms = int(self._comp_release._var.get())
        c.output_gain_db = self._comp_output_gain._var.get()

        e = self._config.expander
        e.enabled = self._exp_enabled.get()
        e.preset = self._exp_preset_var.get()
        e.ratio = self._exp_ratio._var.get()
        e.threshold_db = self._exp_threshold._var.get()
        e.attack_ms = int(self._exp_attack._var.get())
        e.release_ms = int(self._exp_release._var.get())
        e.output_gain_db = self._exp_output_gain._var.get()
        e.detector = self._exp_detector_var.get()

        try:
            self._config.save()
            self.clear_error()
        except Exception as exc:
            self.show_error(f"保存エラー: {exc}")

    def _on_reset(self) -> None:
        """OBS デフォルト値を UI とフィルタに適用する。"""
        # Compressor
        self._comp_enabled.set(True)
        self._compressor.enabled = True
        self._config.compressor.enabled = True
        self._comp_ratio.set(COMP_DEFAULT_RATIO)
        self._comp_threshold.set(COMP_DEFAULT_THRESHOLD_DB)
        self._comp_attack.set(float(COMP_DEFAULT_ATTACK_MS))
        self._comp_release.set(float(COMP_DEFAULT_RELEASE_MS))
        self._comp_output_gain.set(COMP_DEFAULT_OUTPUT_GAIN_DB)
        self._compressor.update_params(
            ratio=COMP_DEFAULT_RATIO,
            threshold=COMP_DEFAULT_THRESHOLD_DB,
            attack_ms=COMP_DEFAULT_ATTACK_MS,
            release_ms=COMP_DEFAULT_RELEASE_MS,
            output_gain_db=COMP_DEFAULT_OUTPUT_GAIN_DB,
        )

        # Expander
        self._exp_enabled.set(True)
        self._expander.enabled = True
        self._config.expander.enabled = True
        self._exp_preset_var.set(PRESET_EXPANDER)
        self._exp_ratio.set(EXP_DEFAULT_RATIO)
        self._exp_threshold.set(EXP_DEFAULT_THRESHOLD_DB)
        self._exp_attack.set(float(EXP_DEFAULT_ATTACK_MS))
        self._exp_release.set(float(EXP_DEFAULT_RELEASE_MS))
        self._exp_output_gain.set(EXP_DEFAULT_OUTPUT_GAIN_DB)
        self._exp_detector_var.set(DETECTOR_RMS)
        self._expander.update_params(
            preset=PRESET_EXPANDER,
            ratio=EXP_DEFAULT_RATIO,
            threshold=EXP_DEFAULT_THRESHOLD_DB,
            attack_ms=EXP_DEFAULT_ATTACK_MS,
            release_ms=EXP_DEFAULT_RELEASE_MS,
            output_gain_db=EXP_DEFAULT_OUTPUT_GAIN_DB,
            detector=DETECTOR_RMS,
        )
