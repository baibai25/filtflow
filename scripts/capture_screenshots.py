#!/usr/bin/env python
"""UI スクリーンショット生成スクリプト

Xvfb 上で SettingsWindow をダーク/ライト両テーマで描画し、
docs/images/ に PNG を保存する。

Usage:
    xvfb-run -a uv run python scripts/capture_screenshots.py
"""

from __future__ import annotations

import os
import queue
import sys

# リポジトリルートのパスを通して Filtflow パッケージを import 可能にする
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# --- audio_stream のモック ---
# sounddevice が利用できない環境でも UI を描画できるようにする
import types

mock_audio_stream = types.ModuleType("Filtflow.audio_stream")


class _MockAudioStream:
    def update_devices(self, *a, **kw):
        pass

    def update_block_size(self, *a, **kw):
        pass


def _list_input_devices():
    return [
        {"name": "Microphone (Realtek High Definition Audio)"},
        {"name": "Headset Microphone (USB Audio)"},
    ]


def _list_output_devices():
    return [
        {"name": "CABLE Input (VB-Audio Virtual Cable)"},
        {"name": "Speakers (Realtek High Definition Audio)"},
    ]


def _find_device_index(name, is_input=True):
    return 0


mock_audio_stream.AudioStream = _MockAudioStream
mock_audio_stream.list_input_devices = _list_input_devices
mock_audio_stream.list_output_devices = _list_output_devices
mock_audio_stream.find_device_index = _find_device_index

sys.modules["Filtflow.audio_stream"] = mock_audio_stream

# --- _version のモック ---
mock_version = types.ModuleType("Filtflow._version")
mock_version.__version__ = "0.1.0"
sys.modules["Filtflow._version"] = mock_version

# --- ここから Qt ---
import qdarktheme
from PySide6.QtWidgets import QApplication

from Filtflow.compressor import Compressor
from Filtflow.config import Config
from Filtflow.expander import Expander
from Filtflow.ui import SettingsWindow, apply_appearance_mode

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "images")


def capture(theme: str) -> None:
    """指定テーマで SettingsWindow を描画しスクリーンショットを保存する。"""
    config = Config()
    config.appearance_mode = theme
    config.input_device_name = "Microphone (Realtek High Definition Audio)"
    config.output_device_name = "CABLE Input (VB-Audio Virtual Cable)"

    compressor = Compressor(
        ratio=config.compressor.ratio,
        threshold=config.compressor.threshold_db,
        attack_ms=config.compressor.attack_ms,
        release_ms=config.compressor.release_ms,
        output_gain_db=config.compressor.output_gain_db,
        sample_rate=config.sample_rate,
    )
    expander = Expander(
        preset=config.expander.preset,
        ratio=config.expander.ratio,
        threshold=config.expander.threshold_db,
        attack_ms=config.expander.attack_ms,
        release_ms=config.expander.release_ms,
        output_gain_db=config.expander.output_gain_db,
        detector=config.expander.detector,
        sample_rate=config.sample_rate,
    )

    level_q: queue.Queue[float] = queue.Queue()
    # メーターに適度なレベルを入れておく
    level_q.put(-25.0)

    apply_appearance_mode(theme)

    win = SettingsWindow(config, compressor, expander, _MockAudioStream(), level_q)
    win.resize(620, 650)
    win.show()

    # レイアウト確定のためイベント処理
    app = QApplication.instance()
    app.processEvents()
    app.processEvents()

    pixmap = win.grab()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"screenshot_{theme}.png")
    pixmap.save(path, "PNG")
    print(f"Saved: {path}")

    win.close()


def main() -> None:
    app = QApplication(sys.argv)
    qdarktheme.setup_theme("dark")

    for theme in ("dark", "light"):
        capture(theme)

    print("Done.")


if __name__ == "__main__":
    main()
