"""設定 UI（CustomTkinter）

デバイス選択・フィルタパラメータのスライダー・レベルメーターを提供する。
スライダー操作中にリアルタイムで update_params() を呼び出し即時反映する。
"""

from __future__ import annotations

import queue
import tkinter as tk
from typing import Callable

import customtkinter as ctk

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

ctk.set_default_color_theme("blue")

# --- OBS 準拠レベルメーターの色しきい値 ---
METER_GREEN_MAX_DB: float = -20.0  # -60 〜 -20 dBFS: 緑
METER_YELLOW_MAX_DB: float = -9.0  # -20 〜 -9 dBFS:  黄
# -9 〜 0 dBFS: 赤
COLOR_GREEN: str = "#00cc00"
COLOR_YELLOW: str = "#ffff00"
COLOR_RED: str = "#ff0000"

METER_MIN_DB: float = -60.0
METER_MAX_DB: float = 0.0
METER_UPDATE_MS: int = 30
PEAK_HOLD_SEC: float = 2.0

BLOCK_SIZE_OPTIONS: list[str] = ["128", "256", "480", "512", "960", "1024"]


class LevelMeter(ctk.CTkFrame):
    """OBS 準拠配色の OUT レベルメーター。

    フィルタ後の音声レベルを 30ms ごとに更新し、2 秒ピーク保持で表示する。
    """

    def __init__(self, parent: ctk.CTkFrame, level_queue: queue.Queue[float]) -> None:
        super().__init__(parent)
        self._queue = level_queue
        self._level_db: float = METER_MIN_DB
        self._peak_db: float = METER_MIN_DB
        self._peak_counter: int = 0
        self._peak_hold_frames: int = int(PEAK_HOLD_SEC * 1000 / METER_UPDATE_MS)

        # ラベル行
        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(header, text="OUT", anchor="w", width=40).pack(side="left")
        self._label_peak = ctk.CTkLabel(
            header, text="peak: -60.0 dB", text_color="gray60", anchor="e", width=130
        )
        self._label_peak.pack(side="right")
        self._label_db = ctk.CTkLabel(header, text="-60.0 dB", anchor="e", width=90)
        self._label_db.pack(side="right")

        # キャンバス（メーターバー）
        self._canvas = tk.Canvas(self, height=16, highlightthickness=0)
        self._canvas.pack(fill="x", padx=4, pady=(2, 6))

        self._update()

    def _db_to_x(self, db: float, width: int) -> int:
        """dB 値をキャンバス上の x 座標に変換する（対数スケール）。"""
        clamped = max(METER_MIN_DB, min(METER_MAX_DB, db))
        ratio = (clamped - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)
        return int(ratio * width)

    def _update(self) -> None:
        """30ms ごとにキューを読み出してメーターを再描画する。"""
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

        self._draw_meter()
        self._label_db.configure(text=f"{self._level_db:+.1f} dB")
        self._label_peak.configure(text=f"peak: {self._peak_db:+.1f} dB")
        self.after(METER_UPDATE_MS, self._update)

    def _draw_meter(self) -> None:
        self._canvas.delete("all")
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w <= 1:
            return

        x_green = self._db_to_x(METER_GREEN_MAX_DB, w)
        x_yellow = self._db_to_x(METER_YELLOW_MAX_DB, w)
        x_level = self._db_to_x(self._level_db, w)
        x_peak = self._db_to_x(self._peak_db, w)

        # --- アクティブレベル ---
        end_green = min(x_level, x_green)
        if end_green > 0:
            self._canvas.create_rectangle(0, 0, end_green, h, fill=COLOR_GREEN, outline="")

        if x_level > x_green:
            end_yellow = min(x_level, x_yellow)
            self._canvas.create_rectangle(x_green, 0, end_yellow, h, fill=COLOR_YELLOW, outline="")

        if x_level > x_yellow:
            self._canvas.create_rectangle(x_yellow, 0, x_level, h, fill=COLOR_RED, outline="")

        # --- ピーク線 ---
        if 0 < x_peak < w:
            peak_color = (
                COLOR_RED
                if self._peak_db > METER_YELLOW_MAX_DB
                else COLOR_YELLOW
                if self._peak_db > METER_GREEN_MAX_DB
                else COLOR_GREEN
            )
            self._canvas.create_line(x_peak, 0, x_peak, h, fill=peak_color, width=2)


class _SliderRow(ctk.CTkFrame):
    """ラベル + スライダー + 値表示の 1 行コンポーネント。"""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        label: str,
        from_: float,
        to: float,
        resolution: float,
        initial: float,
        unit: str,
        on_change: Callable[[float], None],
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self._on_change = on_change
        self._unit = unit
        self._value = initial

        ctk.CTkLabel(self, text=label, width=110, anchor="w").pack(side="left")

        steps = max(1, int(round((to - from_) / resolution)))
        self._slider = ctk.CTkSlider(
            self,
            from_=from_,
            to=to,
            number_of_steps=steps,
            command=self._on_slider,
            width=200,
        )
        self._slider.set(initial)
        self._slider.pack(side="left", padx=(0, 8))

        self._val_label = ctk.CTkLabel(self, text=self._format(initial), width=90, anchor="w")
        self._val_label.pack(side="left")

        range_text = f"({from_:.0f}–{to:.0f} {unit})"
        ctk.CTkLabel(self, text=range_text, text_color="gray60", anchor="w").pack(side="left")

    def _format(self, v: float) -> str:
        return f"{v:.1f} {self._unit}"

    def _on_slider(self, v: float) -> None:
        self._value = v
        self._val_label.configure(text=self._format(v))
        self._on_change(v)

    def get(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = value
        self._slider.set(value)
        self._val_label.configure(text=self._format(value))


def _section_frame(parent: ctk.CTkScrollableFrame, title: str) -> ctk.CTkFrame:
    """タイトルラベル付きのカードフレームを作成して返す。"""
    card = ctk.CTkFrame(parent, corner_radius=8)
    card.pack(fill="x", padx=8, pady=4)
    ctk.CTkLabel(
        card,
        text=title,
        font=ctk.CTkFont(size=12, weight="bold"),
        anchor="w",
    ).pack(fill="x", padx=10, pady=(8, 2))
    return card


class SettingsWindow(ctk.CTkToplevel):
    """Filtflow 設定ウィンドウ。

    デバイス選択・フィルタパラメータ・レベルメーターを提供する。
    スライダー操作中にリアルタイムでフィルタパラメータを更新する。
    """

    def __init__(
        self,
        master: ctk.CTk,
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

        self._save_after_id: str | None = None

        self.title("Filtflow 設定")
        self.resizable(False, True)
        self.minsize(560, 400)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self._build_ui(level_queue)
        self._refresh_device_lists()

    def _build_ui(self, level_queue: queue.Queue[float]) -> None:
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # --- レベルメーター ---
        meter_card = _section_frame(scroll, "レベルメーター")
        LevelMeter(meter_card, level_queue).pack(fill="x", padx=6, pady=(0, 6))

        # --- デバイス設定 ---
        dev_card = _section_frame(scroll, "デバイス設定")
        dev_grid = ctk.CTkFrame(dev_card, fg_color="transparent")
        dev_grid.pack(fill="x", padx=6, pady=(0, 8))

        ctk.CTkLabel(dev_grid, text="入力デバイス:", anchor="w", width=110).grid(
            row=0, column=0, sticky="w", padx=4, pady=3
        )
        self._input_var = tk.StringVar(value=self._config.input_device_name)
        self._input_combo = ctk.CTkComboBox(
            dev_grid,
            variable=self._input_var,
            values=[],
            width=330,
            state="readonly",
            command=lambda _: self._on_device_change(),
        )
        self._input_combo.grid(row=0, column=1, columnspan=2, padx=4, pady=3, sticky="w")

        ctk.CTkLabel(dev_grid, text="出力デバイス:", anchor="w", width=110).grid(
            row=1, column=0, sticky="w", padx=4, pady=3
        )
        self._output_var = tk.StringVar(value=self._config.output_device_name)
        self._output_combo = ctk.CTkComboBox(
            dev_grid,
            variable=self._output_var,
            values=[],
            width=330,
            state="readonly",
            command=lambda _: self._on_device_change(),
        )
        self._output_combo.grid(row=1, column=1, columnspan=2, padx=4, pady=3, sticky="w")

        ctk.CTkLabel(dev_grid, text="ブロックサイズ:", anchor="w", width=110).grid(
            row=2, column=0, sticky="w", padx=4, pady=3
        )
        self._block_size_var = tk.StringVar(value=str(self._config.block_size))
        self._block_size_combo = ctk.CTkComboBox(
            dev_grid,
            variable=self._block_size_var,
            values=BLOCK_SIZE_OPTIONS,
            width=120,
            state="readonly",
            command=lambda _: self._on_block_size_change(),
        )
        self._block_size_combo.grid(row=2, column=1, padx=4, pady=3, sticky="w")
        ctk.CTkLabel(dev_grid, text="samples", text_color="gray60", anchor="w").grid(
            row=2, column=2, padx=2, pady=3, sticky="w"
        )

        # --- Compressor ---
        comp_card = _section_frame(scroll, "Compressor")

        comp_top = ctk.CTkFrame(comp_card, fg_color="transparent")
        comp_top.pack(fill="x", padx=6)
        self._comp_enabled = tk.BooleanVar(value=self._config.compressor.enabled)
        ctk.CTkCheckBox(
            comp_top,
            text="有効",
            variable=self._comp_enabled,
            command=self._on_comp_enabled_change,
        ).pack(anchor="e")

        self._comp_ratio = _SliderRow(
            comp_card,
            "Ratio",
            COMP_MIN_RATIO,
            COMP_MAX_RATIO,
            0.5,
            self._config.compressor.ratio,
            ":1",
            lambda v: (self._compressor.update_params(ratio=v), self._schedule_save()),
        )
        self._comp_ratio.pack(fill="x", padx=6, pady=1)

        self._comp_threshold = _SliderRow(
            comp_card,
            "Threshold",
            COMP_MIN_THRESHOLD_DB,
            0.0,
            0.5,
            self._config.compressor.threshold_db,
            "dB",
            lambda v: (self._compressor.update_params(threshold=v), self._schedule_save()),
        )
        self._comp_threshold.pack(fill="x", padx=6, pady=1)

        self._comp_attack = _SliderRow(
            comp_card,
            "Attack",
            COMP_MIN_ATK_RLS_MS,
            COMP_MAX_ATK_MS,
            1,
            self._config.compressor.attack_ms,
            "ms",
            lambda v: (self._compressor.update_params(attack_ms=int(v)), self._schedule_save()),
        )
        self._comp_attack.pack(fill="x", padx=6, pady=1)

        self._comp_release = _SliderRow(
            comp_card,
            "Release",
            COMP_MIN_ATK_RLS_MS,
            COMP_MAX_RLS_MS,
            5,
            self._config.compressor.release_ms,
            "ms",
            lambda v: (self._compressor.update_params(release_ms=int(v)), self._schedule_save()),
        )
        self._comp_release.pack(fill="x", padx=6, pady=1)

        self._comp_output_gain = _SliderRow(
            comp_card,
            "Output Gain",
            COMP_MIN_OUTPUT_GAIN,
            COMP_MAX_OUTPUT_GAIN,
            0.5,
            self._config.compressor.output_gain_db,
            "dB",
            lambda v: (self._compressor.update_params(output_gain_db=v), self._schedule_save()),
        )
        self._comp_output_gain.pack(fill="x", padx=6, pady=(1, 8))

        # --- Expander ---
        exp_card = _section_frame(scroll, "Expander")

        exp_top = ctk.CTkFrame(exp_card, fg_color="transparent")
        exp_top.pack(fill="x", padx=6)
        self._exp_enabled = tk.BooleanVar(value=self._config.expander.enabled)
        ctk.CTkCheckBox(
            exp_top,
            text="有効",
            variable=self._exp_enabled,
            command=self._on_exp_enabled_change,
        ).pack(anchor="e")

        preset_row = ctk.CTkFrame(exp_card, fg_color="transparent")
        preset_row.pack(fill="x", padx=6, pady=1)
        ctk.CTkLabel(preset_row, text="Preset", width=110, anchor="w").pack(side="left")
        self._exp_preset_var = tk.StringVar(value=self._config.expander.preset)
        ctk.CTkComboBox(
            preset_row,
            variable=self._exp_preset_var,
            values=[PRESET_EXPANDER, PRESET_GATE],
            width=140,
            state="readonly",
            command=lambda _: self._on_preset_change(),
        ).pack(side="left")

        self._exp_ratio = _SliderRow(
            exp_card,
            "Ratio",
            EXP_MIN_RATIO,
            EXP_MAX_RATIO,
            0.5,
            self._config.expander.ratio,
            ":1",
            lambda v: (self._expander.update_params(ratio=v), self._schedule_save()),
        )
        self._exp_ratio.pack(fill="x", padx=6, pady=1)

        self._exp_threshold = _SliderRow(
            exp_card,
            "Threshold",
            EXP_MIN_THRESHOLD_DB,
            0.0,
            0.5,
            self._config.expander.threshold_db,
            "dB",
            lambda v: (self._expander.update_params(threshold=v), self._schedule_save()),
        )
        self._exp_threshold.pack(fill="x", padx=6, pady=1)

        self._exp_attack = _SliderRow(
            exp_card,
            "Attack",
            EXP_MIN_ATK_RLS_MS,
            EXP_MAX_ATK_MS,
            1,
            self._config.expander.attack_ms,
            "ms",
            lambda v: (self._expander.update_params(attack_ms=int(v)), self._schedule_save()),
        )
        self._exp_attack.pack(fill="x", padx=6, pady=1)

        self._exp_release = _SliderRow(
            exp_card,
            "Release",
            EXP_MIN_ATK_RLS_MS,
            EXP_MAX_RLS_MS,
            5,
            self._config.expander.release_ms,
            "ms",
            lambda v: (self._expander.update_params(release_ms=int(v)), self._schedule_save()),
        )
        self._exp_release.pack(fill="x", padx=6, pady=1)

        self._exp_output_gain = _SliderRow(
            exp_card,
            "Output Gain",
            EXP_MIN_OUTPUT_GAIN,
            EXP_MAX_OUTPUT_GAIN,
            0.5,
            self._config.expander.output_gain_db,
            "dB",
            lambda v: (self._expander.update_params(output_gain_db=v), self._schedule_save()),
        )
        self._exp_output_gain.pack(fill="x", padx=6, pady=1)

        detector_row = ctk.CTkFrame(exp_card, fg_color="transparent")
        detector_row.pack(fill="x", padx=6, pady=(1, 8))
        ctk.CTkLabel(detector_row, text="Detector", width=110, anchor="w").pack(side="left")
        self._exp_detector_var = tk.StringVar(value=self._config.expander.detector)
        ctk.CTkComboBox(
            detector_row,
            variable=self._exp_detector_var,
            values=[DETECTOR_RMS, DETECTOR_PEAK],
            width=140,
            state="readonly",
            command=lambda _: self._on_detector_change(),
        ).pack(side="left")

        # --- ボタン行 ---
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            btn_frame,
            text="デフォルトに戻す",
            width=140,
            fg_color="gray30",
            hover_color="gray40",
            command=self._on_reset,
        ).pack(side="left", padx=4)

        self._appearance_btn = ctk.CTkSegmentedButton(
            btn_frame,
            values=["Dark", "Light"],
            command=self._on_appearance_change,
            width=140,
        )
        self._appearance_btn.set(self._config.appearance_mode.capitalize())
        self._appearance_btn.pack(side="right", padx=4)

        # --- エラー表示ラベル ---
        self._error_label = ctk.CTkLabel(scroll, text="", text_color="#ff6666")
        self._error_label.pack(fill="x", padx=8, pady=(0, 4))

    def _refresh_device_lists(self) -> None:
        """デバイス一覧を再取得してコンボボックスを更新する。"""
        in_names = [str(d["name"]) for d in list_input_devices()]
        out_names = [str(d["name"]) for d in list_output_devices()]
        self._input_combo.configure(values=in_names)
        self._output_combo.configure(values=out_names)
        if self._config.input_device_name:
            self._input_combo.set(self._config.input_device_name)
        if self._config.output_device_name:
            self._output_combo.set(self._config.output_device_name)

    def show_error(self, msg: str) -> None:
        self._error_label.configure(text=msg)

    def clear_error(self) -> None:
        self._error_label.configure(text="")

    # --- イベントハンドラ ---

    def _on_device_change(self) -> None:
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
        self._schedule_save()

    def _on_block_size_change(self) -> None:
        block_size = int(self._block_size_var.get())
        self._config.block_size = block_size
        try:
            self._stream.update_block_size(block_size)
            self.clear_error()
        except Exception as exc:
            self.show_error(f"デバイスエラー: {exc}")
        self._schedule_save()

    def _on_comp_enabled_change(self) -> None:
        enabled = self._comp_enabled.get()
        self._config.compressor.enabled = enabled
        self._compressor.enabled = enabled
        self._schedule_save()

    def _on_exp_enabled_change(self) -> None:
        enabled = self._exp_enabled.get()
        self._config.expander.enabled = enabled
        self._expander.enabled = enabled
        self._schedule_save()

    def _on_preset_change(self) -> None:
        preset = self._exp_preset_var.get()
        self._expander.update_params(preset=preset)
        self._config.expander.preset = preset

        if preset == PRESET_GATE:
            ratio: float = GATE_DEFAULT_RATIO
            release_ms: int = GATE_DEFAULT_RELEASE_MS
        else:
            ratio = EXP_DEFAULT_RATIO
            release_ms = EXP_DEFAULT_RELEASE_MS

        self._exp_ratio.set(ratio)
        self._exp_release.set(float(release_ms))
        self._expander.update_params(ratio=ratio, release_ms=release_ms)
        self._schedule_save()

    def _on_detector_change(self) -> None:
        detector = self._exp_detector_var.get()
        self._expander.update_params(detector=detector)
        self._config.expander.detector = detector
        self._schedule_save()

    def _on_appearance_change(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        self._config.appearance_mode = mode.lower()
        self._schedule_save()

    def _schedule_save(self) -> None:
        """500ms デバウンスで _do_save を呼ぶ。連続操作中は延期する。"""
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
        self._save_after_id = self.after(500, self._do_save)

    def _do_save(self) -> None:
        """現在の UI 値を config に反映して JSON 保存する。"""
        self._save_after_id = None

        c = self._config.compressor
        c.enabled = self._comp_enabled.get()
        c.ratio = self._comp_ratio.get()
        c.threshold_db = self._comp_threshold.get()
        c.attack_ms = int(self._comp_attack.get())
        c.release_ms = int(self._comp_release.get())
        c.output_gain_db = self._comp_output_gain.get()

        e = self._config.expander
        e.enabled = self._exp_enabled.get()
        e.preset = self._exp_preset_var.get()
        e.ratio = self._exp_ratio.get()
        e.threshold_db = self._exp_threshold.get()
        e.attack_ms = int(self._exp_attack.get())
        e.release_ms = int(self._exp_release.get())
        e.output_gain_db = self._exp_output_gain.get()
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
        self._schedule_save()
