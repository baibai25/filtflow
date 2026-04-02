"""設定 UI（PySide6）

デバイス選択・フィルタパラメータのスライダー・レベルメーターを提供する。
スライダー操作中にリアルタイムで update_params() を呼び出し即時反映する。
DPI スケーリングは PySide6 が自動処理するため、手動スケール計算は不要。
"""

from __future__ import annotations

import queue
from typing import Callable

import qdarktheme

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

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
METER_GREEN_MAX_DB: float = -20.0  # -60 〜 -20 dBFS: 緑
METER_YELLOW_MAX_DB: float = -9.0  # -20 〜 -9 dBFS: 黄
# -9 〜 0 dBFS: 赤

COLOR_GREEN = "#66ff66"
COLOR_YELLOW = "#fff59d"
COLOR_RED = "#ff8080"

COLOR_BG_GREEN: str = "#2f6f2f"
COLOR_BG_YELLOW: str = "#8a8325"
COLOR_BG_RED: str = "#8a2525"

METER_MIN_DB: float = -60.0
METER_MAX_DB: float = 0.0
METER_UPDATE_MS: int = 30
PEAK_HOLD_SEC: float = 2.0

METER_BAR_HEIGHT: int = 12
METER_SCALE_HEIGHT: int = 22
METER_TICK_MARKS: list[float] = [-60.0, -50.0, -40.0, -30.0, -20.0, -10.0, 0.0]

BLOCK_SIZE_OPTIONS: list[str] = ["128", "256", "480", "512", "960", "1024"]

# グレーアウトテキスト用スタイルシート（範囲表示・補助ラベル等）
# palette(mid) はテーマに追従するため、ダーク・ライト問わず適切なコントラストになる
_MUTED_STYLE: str = "color: palette(mid);"

# 外観切り替えトグルのスタイル（セグメントコントロール風・palette のみで統一）
# Dark / Light が連結して1つのコントロールに見えるよう角丸を片側のみに設定する
# setObjectName("darkToggle") / setObjectName("lightToggle") と組み合わせて使う
_TOGGLE_BTN_STYLE: str = """
    QPushButton {
        background-color: palette(button);
        color: palette(button-text);
        border: 1px solid palette(mid);
        padding: 4px 16px;
        border-radius: 0px;
    }
    QPushButton:hover:!checked { background-color: palette(midlight); }
    QPushButton:checked {
        background-color: palette(highlight);
        color: palette(highlighted-text);
        border-color: palette(highlight);
    }
    QPushButton#darkToggle {
        border-top-left-radius: 4px;
        border-bottom-left-radius: 4px;
    }
    QPushButton#lightToggle {
        border-top-right-radius: 4px;
        border-bottom-right-radius: 4px;
        border-left: none;
    }
"""

# QButtonGroup に渡す ID（外観モード識別用）
_APPEARANCE_ID_DARK: int = 0
_APPEARANCE_ID_LIGHT: int = 1


# apply_appearance_mode の二重適用を防ぐためのキャッシュ
_applied_appearance_mode: str = ""


def apply_appearance_mode(mode: str) -> None:
    """アプリケーション全体の外観モードを適用する（"dark" / "light"）。

    PyQtDarkTheme（qdarktheme）によるテーマ切り替え。
    スタイルシートとパレットを自動設定するため手動設定は不要。
    """
    global _applied_appearance_mode
    normalized = mode.lower()
    if normalized == _applied_appearance_mode:
        return

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return

    _applied_appearance_mode = normalized
    qdarktheme.setup_theme(normalized)


class _MeterBar(QWidget):
    """OBS 準拠配色のメーターバーを描画するカスタムウィジェット。

    QPainter で論理座標を使って描画するため DPI スケーリングは自動適用される。
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(METER_BAR_HEIGHT + METER_SCALE_HEIGHT)
        self._level_db: float = METER_MIN_DB
        self._peak_db: float = METER_MIN_DB

        # paintEvent 内で毎回生成しないようオブジェクトをキャッシュ
        self._tick_font = QFont()
        self._tick_font.setPointSize(7)
        self._tick_pen = QPen(QColor("#999999"), 1)
        self._tick_fm = QFontMetrics(self._tick_font)

        # 幅が変わったときのみ再計算する閾値 x 座標キャッシュ
        self._cached_w: int = -1
        self._cached_x_green: int = 0
        self._cached_x_yellow: int = 0

    def update_levels(self, level_db: float, peak_db: float) -> None:
        self._level_db = level_db
        self._peak_db = peak_db
        self.update()

    def _db_to_x(self, db: float, width: int) -> int:
        clamped = max(METER_MIN_DB, min(METER_MAX_DB, db))
        ratio = (clamped - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)
        return min(int(ratio * width), width - 1)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        w = self.width()
        bar_h = METER_BAR_HEIGHT

        # 幅が変わった場合のみ閾値 x 座標を再計算
        if w != self._cached_w:
            self._cached_w = w
            self._cached_x_green = self._db_to_x(METER_GREEN_MAX_DB, w)
            self._cached_x_yellow = self._db_to_x(METER_YELLOW_MAX_DB, w)

        x_green = self._cached_x_green
        x_yellow = self._cached_x_yellow
        x_level = self._db_to_x(self._level_db, w)
        x_peak = self._db_to_x(self._peak_db, w)

        # --- 背景帯 ---
        painter.fillRect(0, 0, x_green, bar_h, QColor(COLOR_BG_GREEN))
        painter.fillRect(x_green, 0, x_yellow - x_green, bar_h, QColor(COLOR_BG_YELLOW))
        painter.fillRect(x_yellow, 0, w - x_yellow, bar_h, QColor(COLOR_BG_RED))

        # --- アクティブレベル ---
        end_green = min(x_level, x_green)
        if end_green > 0:
            painter.fillRect(0, 0, end_green, bar_h, QColor(COLOR_GREEN))

        if x_level > x_green:
            end_yellow = min(x_level, x_yellow)
            if end_yellow > x_green:
                painter.fillRect(x_green, 0, end_yellow - x_green, bar_h, QColor(COLOR_YELLOW))

        if x_level > x_yellow:
            painter.fillRect(x_yellow, 0, x_level - x_yellow, bar_h, QColor(COLOR_RED))

        # --- ピーク線 ---
        if 0 < x_peak < w:
            peak_color = (
                QColor(COLOR_RED)
                if self._peak_db > METER_YELLOW_MAX_DB
                else QColor(COLOR_YELLOW)
                if self._peak_db > METER_GREEN_MAX_DB
                else QColor(COLOR_GREEN)
            )
            painter.setPen(QPen(peak_color, 2))
            painter.drawLine(x_peak, 0, x_peak, bar_h)

        # --- 目盛り ---
        tick_top = bar_h + 2
        tick_bot = bar_h + 6
        label_y = bar_h + 8
        painter.setFont(self._tick_font)
        painter.setPen(self._tick_pen)
        fm = self._tick_fm

        for db in METER_TICK_MARKS:
            x = self._db_to_x(db, w)
            painter.drawLine(x, tick_top, x, tick_bot)
            label = "0" if db == 0.0 else str(int(db))
            text_w = fm.horizontalAdvance(label)
            if db == METER_MIN_DB:
                text_x = x
            elif db == METER_MAX_DB:
                text_x = x - text_w
            else:
                text_x = x - text_w // 2
            painter.drawText(text_x, label_y + fm.ascent(), label)

        painter.end()


class LevelMeter(QWidget):
    """OBS 準拠配色の OUT レベルメーター。

    フィルタ後の音声レベルを 30ms ごとに更新し、2 秒ピーク保持で表示する。
    """

    def __init__(self, parent: QWidget, level_queue: queue.Queue[float]) -> None:
        super().__init__(parent)
        self._queue = level_queue
        self._level_db: float = METER_MIN_DB
        self._peak_db: float = METER_MIN_DB
        self._peak_counter: int = 0
        self._peak_hold_frames: int = int(PEAK_HOLD_SEC * 1000 / METER_UPDATE_MS)

        # ヘッダー行
        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(QLabel("OUT"))
        header_layout.addStretch()
        self._label_db = QLabel("-60.0 dB")
        self._label_peak = QLabel("peak: -60.0 dB")
        self._label_peak.setStyleSheet(_MUTED_STYLE)
        header_layout.addWidget(self._label_db)
        header_layout.addWidget(self._label_peak)

        self._bar = _MeterBar(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 6)
        layout.setSpacing(2)
        layout.addWidget(header)
        layout.addWidget(self._bar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(METER_UPDATE_MS)

    def _update(self) -> None:
        latest_db = self._level_db
        try:
            while True:
                latest_db = self._queue.get_nowait()
        except queue.Empty:
            pass

        self._level_db = latest_db

        if self._level_db >= self._peak_db:
            self._peak_db = self._level_db
            self._peak_counter = 0
        else:
            self._peak_counter += 1
            if self._peak_counter > self._peak_hold_frames:
                self._peak_db = self._level_db
                self._peak_counter = 0

        self._bar.update_levels(self._level_db, self._peak_db)
        self._label_db.setText(f"{self._level_db:+.1f} dB")
        self._label_peak.setText(f"peak: {self._peak_db:+.1f} dB")

    def stop(self) -> None:
        """タイマーを停止する。"""
        self._timer.stop()


class _SliderRow(QWidget):
    """ラベル + スライダー + 値表示の 1 行コンポーネント。

    QSlider は整数値を扱うため、resolution でステップ数に変換して浮動小数点値を扱う。
    """

    def __init__(
        self,
        parent: QWidget,
        label: str,
        from_: float,
        to: float,
        resolution: float,
        initial: float,
        unit: str,
        on_change: Callable[[float], None],
    ) -> None:
        super().__init__(parent)
        self._from = from_
        self._resolution = resolution
        self._unit = unit
        self._on_change = on_change

        steps = max(1, int(round((to - from_) / resolution)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        layout.addWidget(lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, steps)
        self._slider.setFixedWidth(200)
        self._slider.setValue(self._to_int(initial))
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

        self._val_label = QLabel(self._format(initial))
        self._val_label.setFixedWidth(90)
        layout.addWidget(self._val_label)

        range_text = f"({from_:.0f}–{to:.0f} {unit})"
        range_lbl = QLabel(range_text)
        range_lbl.setStyleSheet(_MUTED_STYLE)
        layout.addWidget(range_lbl)
        layout.addStretch()

    def _to_int(self, value: float) -> int:
        return int(round((value - self._from) / self._resolution))

    def _to_float(self, steps: int) -> float:
        return self._from + steps * self._resolution

    def _format(self, v: float) -> str:
        return f"{v:.1f} {self._unit}"

    def _on_slider_changed(self, step: int) -> None:
        v = self._to_float(step)
        self._val_label.setText(self._format(v))
        self._on_change(v)

    def get(self) -> float:
        return self._to_float(self._slider.value())

    def set(self, value: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(self._to_int(value))
        self._slider.blockSignals(False)
        self._val_label.setText(self._format(value))


def _build_labeled_combo_row(
    label: str,
    items: list[str],
    current: str,
    on_change: Callable[[], None],
) -> tuple[QWidget, QComboBox]:
    """ラベル + コンボボックス の 1 行ウィジェットを作成して返す。"""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label)
    lbl.setFixedWidth(110)
    layout.addWidget(lbl)
    combo = QComboBox()
    combo.addItems(items)
    combo.setCurrentText(current)
    combo.setFixedWidth(140)
    combo.currentTextChanged.connect(lambda _text: on_change())
    layout.addWidget(combo)
    layout.addStretch()
    return row, combo


class SettingsWindow(QWidget):
    """Filtflow 設定ウィンドウ。

    デバイス選択・フィルタパラメータ・レベルメーターを提供する。
    スライダー操作中にリアルタイムでフィルタパラメータを更新する。
    閉じるボタンは withdraw（非表示）のみ行い、ウィジェットは破棄しない。
    """

    def __init__(
        self,
        config: Config,
        compressor: Compressor,
        expander: Expander,
        stream: AudioStream,
        level_queue: queue.Queue[float],
    ) -> None:
        super().__init__()
        self._config = config
        self._compressor = compressor
        self._expander = expander
        self._stream = stream

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self.setWindowTitle("Filtflow Settings")
        self.setMinimumSize(600, 400)
        self.resize(600, 880)

        self._build_ui(level_queue)
        self._refresh_device_lists()

    def closeEvent(self, event: QCloseEvent) -> None:
        """× ボタンは非表示のみ行い、ウィジェットを破棄しない。"""
        event.ignore()
        self.hide()

    def _build_ui(self, level_queue: queue.Queue[float]) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # --- 右上の外観切り替えトグル ---
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addStretch()

        self._dark_btn = QPushButton("Dark")
        self._dark_btn.setCheckable(True)
        self._dark_btn.setObjectName("darkToggle")
        self._dark_btn.setStyleSheet(_TOGGLE_BTN_STYLE)

        self._light_btn = QPushButton("Light")
        self._light_btn.setCheckable(True)
        self._light_btn.setObjectName("lightToggle")
        self._light_btn.setStyleSheet(_TOGGLE_BTN_STYLE)

        self._appearance_group = QButtonGroup(self)
        self._appearance_group.setExclusive(True)
        self._appearance_group.addButton(self._dark_btn, _APPEARANCE_ID_DARK)
        self._appearance_group.addButton(self._light_btn, _APPEARANCE_ID_LIGHT)
        self._appearance_group.idClicked.connect(self._on_appearance_change)

        if self._config.appearance_mode.lower() == "dark":
            self._dark_btn.setChecked(True)
        else:
            self._light_btn.setChecked(True)

        header_layout.addWidget(self._dark_btn)
        header_layout.addWidget(self._light_btn)
        main_layout.addWidget(header)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        main_layout.addWidget(scroll_area)

        container = QWidget()
        scroll_layout = QVBoxLayout(container)
        scroll_layout.setContentsMargins(4, 4, 4, 4)
        scroll_layout.setSpacing(4)
        scroll_area.setWidget(container)

        # --- Level Meter ---
        meter_group = QGroupBox("Level Meter")
        scroll_layout.addWidget(meter_group)
        meter_layout = QVBoxLayout(meter_group)
        meter_layout.setContentsMargins(6, 6, 6, 6)
        meter_layout.addWidget(LevelMeter(meter_group, level_queue))

        # --- Device ---
        dev_group = QGroupBox("Device")
        scroll_layout.addWidget(dev_group)
        dev_layout = QVBoxLayout(dev_group)
        dev_layout.setContentsMargins(6, 6, 6, 8)

        dev_grid = QWidget()
        grid = QGridLayout(dev_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        dev_layout.addWidget(dev_grid)

        grid.addWidget(QLabel("Input Device:"), 0, 0)
        self._input_combo = QComboBox()
        self._input_combo.setMinimumWidth(330)
        self._input_combo.currentIndexChanged.connect(
            lambda _idx: self._on_device_change()
        )
        grid.addWidget(self._input_combo, 0, 1, 1, 2)

        grid.addWidget(QLabel("Output Device:"), 1, 0)
        self._output_combo = QComboBox()
        self._output_combo.setMinimumWidth(330)
        self._output_combo.currentIndexChanged.connect(
            lambda _idx: self._on_device_change()
        )
        grid.addWidget(self._output_combo, 1, 1, 1, 2)

        grid.addWidget(QLabel("Block Size:"), 2, 0)
        self._block_size_combo = QComboBox()
        self._block_size_combo.addItems(BLOCK_SIZE_OPTIONS)
        self._block_size_combo.setCurrentText(str(self._config.block_size))
        self._block_size_combo.setFixedWidth(120)
        self._block_size_combo.currentIndexChanged.connect(
            lambda _idx: self._on_block_size_change()
        )
        grid.addWidget(self._block_size_combo, 2, 1)
        samples_lbl = QLabel("samples")
        samples_lbl.setStyleSheet(_MUTED_STYLE)
        grid.addWidget(samples_lbl, 2, 2)

        # --- Compressor ---
        comp_group = QGroupBox("Compressor")
        scroll_layout.addWidget(comp_group)
        comp_layout = QVBoxLayout(comp_group)
        comp_layout.setContentsMargins(6, 4, 6, 8)
        comp_layout.setSpacing(2)

        comp_top = QWidget()
        comp_top_layout = QHBoxLayout(comp_top)
        comp_top_layout.setContentsMargins(0, 0, 0, 0)
        comp_top_layout.addStretch()
        self._comp_enabled = QCheckBox("Enable")
        self._comp_enabled.setChecked(self._config.compressor.enabled)
        self._comp_enabled.stateChanged.connect(
            lambda _state: self._on_comp_enabled_change()
        )
        comp_top_layout.addWidget(self._comp_enabled)
        comp_layout.addWidget(comp_top)

        self._comp_ratio = _SliderRow(
            comp_group,
            "Ratio",
            COMP_MIN_RATIO,
            COMP_MAX_RATIO,
            0.5,
            self._config.compressor.ratio,
            ":1",
            lambda v: (self._compressor.update_params(ratio=v), self._schedule_save()),
        )
        comp_layout.addWidget(self._comp_ratio)

        self._comp_threshold = _SliderRow(
            comp_group,
            "Threshold",
            COMP_MIN_THRESHOLD_DB,
            0.0,
            0.5,
            self._config.compressor.threshold_db,
            "dB",
            lambda v: (self._compressor.update_params(threshold=v), self._schedule_save()),
        )
        comp_layout.addWidget(self._comp_threshold)

        self._comp_attack = _SliderRow(
            comp_group,
            "Attack",
            COMP_MIN_ATK_RLS_MS,
            COMP_MAX_ATK_MS,
            1,
            self._config.compressor.attack_ms,
            "ms",
            lambda v: (self._compressor.update_params(attack_ms=int(v)), self._schedule_save()),
        )
        comp_layout.addWidget(self._comp_attack)

        self._comp_release = _SliderRow(
            comp_group,
            "Release",
            5,
            COMP_MAX_RLS_MS,
            5,
            self._config.compressor.release_ms,
            "ms",
            lambda v: (self._compressor.update_params(release_ms=int(v)), self._schedule_save()),
        )
        comp_layout.addWidget(self._comp_release)

        self._comp_output_gain = _SliderRow(
            comp_group,
            "Output Gain",
            COMP_MIN_OUTPUT_GAIN,
            COMP_MAX_OUTPUT_GAIN,
            0.5,
            self._config.compressor.output_gain_db,
            "dB",
            lambda v: (self._compressor.update_params(output_gain_db=v), self._schedule_save()),
        )
        comp_layout.addWidget(self._comp_output_gain)

        comp_bottom = QWidget()
        comp_bottom_layout = QHBoxLayout(comp_bottom)
        comp_bottom_layout.setContentsMargins(0, 4, 0, 0)
        comp_defaults_btn = QPushButton("Defaults")
        comp_defaults_btn.clicked.connect(self._on_comp_reset)
        comp_bottom_layout.addWidget(comp_defaults_btn)
        comp_bottom_layout.addStretch()
        comp_layout.addWidget(comp_bottom)

        # --- Expander ---
        exp_group = QGroupBox("Expander")
        scroll_layout.addWidget(exp_group)
        exp_layout = QVBoxLayout(exp_group)
        exp_layout.setContentsMargins(6, 4, 6, 8)
        exp_layout.setSpacing(2)

        exp_top = QWidget()
        exp_top_layout = QHBoxLayout(exp_top)
        exp_top_layout.setContentsMargins(0, 0, 0, 0)
        exp_top_layout.addStretch()
        self._exp_enabled = QCheckBox("Enable")
        self._exp_enabled.setChecked(self._config.expander.enabled)
        self._exp_enabled.stateChanged.connect(
            lambda _state: self._on_exp_enabled_change()
        )
        exp_top_layout.addWidget(self._exp_enabled)
        exp_layout.addWidget(exp_top)

        preset_row, self._exp_preset_combo = _build_labeled_combo_row(
            "Preset",
            [PRESET_EXPANDER, PRESET_GATE],
            self._config.expander.preset,
            self._on_preset_change,
        )
        exp_layout.addWidget(preset_row)

        self._exp_ratio = _SliderRow(
            exp_group,
            "Ratio",
            EXP_MIN_RATIO,
            EXP_MAX_RATIO,
            0.5,
            self._config.expander.ratio,
            ":1",
            lambda v: (self._expander.update_params(ratio=v), self._schedule_save()),
        )
        exp_layout.addWidget(self._exp_ratio)

        self._exp_threshold = _SliderRow(
            exp_group,
            "Threshold",
            EXP_MIN_THRESHOLD_DB,
            0.0,
            0.5,
            self._config.expander.threshold_db,
            "dB",
            lambda v: (self._expander.update_params(threshold=v), self._schedule_save()),
        )
        exp_layout.addWidget(self._exp_threshold)

        self._exp_attack = _SliderRow(
            exp_group,
            "Attack",
            EXP_MIN_ATK_RLS_MS,
            EXP_MAX_ATK_MS,
            1,
            self._config.expander.attack_ms,
            "ms",
            lambda v: (self._expander.update_params(attack_ms=int(v)), self._schedule_save()),
        )
        exp_layout.addWidget(self._exp_attack)

        self._exp_release = _SliderRow(
            exp_group,
            "Release",
            5,
            EXP_MAX_RLS_MS,
            5,
            self._config.expander.release_ms,
            "ms",
            lambda v: (self._expander.update_params(release_ms=int(v)), self._schedule_save()),
        )
        exp_layout.addWidget(self._exp_release)

        self._exp_output_gain = _SliderRow(
            exp_group,
            "Output Gain",
            EXP_MIN_OUTPUT_GAIN,
            EXP_MAX_OUTPUT_GAIN,
            0.5,
            self._config.expander.output_gain_db,
            "dB",
            lambda v: (self._expander.update_params(output_gain_db=v), self._schedule_save()),
        )
        exp_layout.addWidget(self._exp_output_gain)

        detector_row, self._exp_detector_combo = _build_labeled_combo_row(
            "Detector",
            [DETECTOR_RMS, DETECTOR_PEAK],
            self._config.expander.detector,
            self._on_detector_change,
        )
        exp_layout.addWidget(detector_row)

        exp_bottom = QWidget()
        exp_bottom_layout = QHBoxLayout(exp_bottom)
        exp_bottom_layout.setContentsMargins(0, 4, 0, 0)
        exp_defaults_btn = QPushButton("Defaults")
        exp_defaults_btn.clicked.connect(self._on_exp_reset)
        exp_bottom_layout.addWidget(exp_defaults_btn)
        exp_bottom_layout.addStretch()
        exp_layout.addWidget(exp_bottom)

        # --- ボタン行 ---
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 4, 0, 4)
        scroll_layout.addWidget(btn_widget)

        reset_all_btn = QPushButton("Reset All")
        reset_all_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(reset_all_btn)

        btn_layout.addStretch()

        # --- エラー表示ラベル ---
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #ff6666;")
        scroll_layout.addWidget(self._error_label)

        scroll_layout.addStretch()

    @staticmethod
    def _refresh_combo(combo: QComboBox, items: list[str], current: str) -> None:
        """コンボボックスの内容を一括更新し、シグナルを一時停止する。"""
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current:
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _refresh_device_lists(self) -> None:
        """デバイス一覧を再取得してコンボボックスを更新する。"""
        in_names = [str(d["name"]) for d in list_input_devices()]
        out_names = [str(d["name"]) for d in list_output_devices()]
        self._refresh_combo(self._input_combo, in_names, self._config.input_device_name)
        self._refresh_combo(self._output_combo, out_names, self._config.output_device_name)

    def show_error(self, msg: str) -> None:
        self._error_label.setText(msg)

    def clear_error(self) -> None:
        self._error_label.setText("")

    # --- イベントハンドラ ---

    def _on_device_change(self) -> None:
        in_name = self._input_combo.currentText()
        out_name = self._output_combo.currentText()
        if not in_name or not out_name:
            return
        in_idx = find_device_index(in_name, is_input=True)
        out_idx = find_device_index(out_name, is_input=False)
        try:
            self._stream.update_devices(in_idx, out_idx)
            self._config.input_device_name = in_name
            self._config.output_device_name = out_name
            self.clear_error()
        except Exception as exc:
            self.show_error(f"Device error: {exc}")
        self._schedule_save()

    def _on_block_size_change(self) -> None:
        block_size = int(self._block_size_combo.currentText())
        try:
            self._stream.update_block_size(block_size)
            self._config.block_size = block_size
            self.clear_error()
        except Exception as exc:
            self.show_error(f"Device error: {exc}")
        self._schedule_save()

    def _on_comp_enabled_change(self) -> None:
        enabled = self._comp_enabled.isChecked()
        self._config.compressor.enabled = enabled
        self._compressor.enabled = enabled
        self._schedule_save()

    def _on_exp_enabled_change(self) -> None:
        enabled = self._exp_enabled.isChecked()
        self._config.expander.enabled = enabled
        self._expander.enabled = enabled
        self._schedule_save()

    def _on_preset_change(self) -> None:
        preset = self._exp_preset_combo.currentText()
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
        detector = self._exp_detector_combo.currentText()
        self._expander.update_params(detector=detector)
        self._config.expander.detector = detector
        self._schedule_save()

    def _on_appearance_change(self, btn_id: int) -> None:
        mode = "dark" if btn_id == _APPEARANCE_ID_DARK else "light"
        apply_appearance_mode(mode)
        self._config.appearance_mode = mode
        self._schedule_save()

    def _schedule_save(self) -> None:
        """500ms デバウンスで _do_save を呼ぶ。連続操作中は延期する。"""
        self._save_timer.start(500)

    def _do_save(self) -> None:
        """現在の UI 値を config に反映して JSON 保存する。"""
        c = self._config.compressor
        c.enabled = self._comp_enabled.isChecked()
        c.ratio = self._comp_ratio.get()
        c.threshold_db = self._comp_threshold.get()
        c.attack_ms = int(self._comp_attack.get())
        c.release_ms = int(self._comp_release.get())
        c.output_gain_db = self._comp_output_gain.get()

        e = self._config.expander
        e.enabled = self._exp_enabled.isChecked()
        e.preset = self._exp_preset_combo.currentText()
        e.ratio = self._exp_ratio.get()
        e.threshold_db = self._exp_threshold.get()
        e.attack_ms = int(self._exp_attack.get())
        e.release_ms = int(self._exp_release.get())
        e.output_gain_db = self._exp_output_gain.get()
        e.detector = self._exp_detector_combo.currentText()

        try:
            self._config.save()
        except Exception as exc:
            self.show_error(f"Save error: {exc}")

    def _on_comp_reset(self) -> None:
        """Compressor を OBS デフォルト値にリセットする。"""
        self._comp_enabled.setChecked(True)
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
        self._schedule_save()

    def _on_exp_reset(self) -> None:
        """Expander を OBS デフォルト値にリセットする。"""
        self._exp_enabled.setChecked(True)
        self._expander.enabled = True
        self._config.expander.enabled = True
        self._exp_preset_combo.setCurrentText(PRESET_EXPANDER)
        self._exp_ratio.set(EXP_DEFAULT_RATIO)
        self._exp_threshold.set(EXP_DEFAULT_THRESHOLD_DB)
        self._exp_attack.set(float(EXP_DEFAULT_ATTACK_MS))
        self._exp_release.set(float(EXP_DEFAULT_RELEASE_MS))
        self._exp_output_gain.set(EXP_DEFAULT_OUTPUT_GAIN_DB)
        self._exp_detector_combo.setCurrentText(DETECTOR_RMS)
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

    def _on_reset(self) -> None:
        """全フィルタを OBS デフォルト値にリセットする。"""
        self._on_comp_reset()
        self._on_exp_reset()
