"""エントリポイント・起動制御

起動フロー:
1. Config をロード
2. Compressor / Expander を初期化
3. AudioStream を構築して開始
4. QSystemTrayIcon を表示
5. QApplication のイベントループをメインスレッドで実行

終了フロー:
- トレイ「Quit」 → _do_quit() → stream.stop() → app.quit()
"""

from __future__ import annotations

import queue
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from audio_stream import AudioStream, find_device_index
from compressor import Compressor
from config import Config
from expander import Expander
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from tray import TrayIcon
from ui import APP_VERSION, SettingsWindow, apply_appearance_mode
from update_checker import UpdateChecker

# レベルメーターキューの最大サイズ
LEVEL_QUEUE_MAXSIZE: int = 16

# ストリームエラー時の自動再接続間隔 (ms)
RECONNECT_INTERVAL_MS: int = 3000


@dataclass
class _AppState:
    """main() 内のクロージャ間で共有する可変状態。"""

    quitting: bool = False
    reconnecting: bool = False
    stream_error: str | None = None
    pending_update: tuple[str, str] | None = None  # (latest_version, url)


def _build_filter_chain(
    compressor: Compressor,
    expander: Expander,
) -> list[Callable[[np.ndarray], np.ndarray]]:
    """両フィルタを常にチェーンに含める。有効/無効は各フィルタの enabled フラグで制御する。"""
    return [expander.process, compressor.process]


def main() -> None:
    app = QApplication(sys.argv)
    # 最後のウィンドウを閉じてもイベントループを継続（トレイ常駐のため）
    app.setQuitOnLastWindowClosed(False)
    # ウィンドウタイトルバーのアイコンを設定
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))

    # --- 設定ロード ---
    config = Config.load()
    apply_appearance_mode(config.appearance_mode)

    # --- フィルタ初期化 ---
    compressor = Compressor(
        ratio=config.compressor.ratio,
        threshold=config.compressor.threshold_db,
        attack_ms=config.compressor.attack_ms,
        release_ms=config.compressor.release_ms,
        output_gain_db=config.compressor.output_gain_db,
        sample_rate=config.sample_rate,
        enabled=config.compressor.enabled,
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
        enabled=config.expander.enabled,
    )

    # --- レベルメーターキュー ---
    level_queue: queue.Queue[float] = queue.Queue(maxsize=LEVEL_QUEUE_MAXSIZE)

    # --- AudioStream 構築 ---
    in_idx = find_device_index(config.input_device_name, is_input=True)
    out_idx = find_device_index(config.output_device_name, is_input=False)
    filter_chain = _build_filter_chain(compressor, expander)

    stream = AudioStream(
        input_device=in_idx,
        output_device=out_idx,
        filter_chain=filter_chain,
        sample_rate=config.sample_rate,
        block_size=config.block_size,
        level_queue=level_queue,
    )

    settings_win: SettingsWindow | None = None
    tray: TrayIcon | None = None
    state = _AppState()

    def _show_settings() -> None:
        nonlocal settings_win
        if settings_win is None:
            settings_win = SettingsWindow(
                config=config,
                compressor=compressor,
                expander=expander,
                stream=stream,
                level_queue=level_queue,
            )
        settings_win.show()
        settings_win.raise_()
        settings_win.activateWindow()
        # 未表示のアップデート通知があれば表示する
        if state.pending_update is not None:
            settings_win.show_update(*state.pending_update)
        # 未解決のストリームエラーがあれば UI にも表示する
        if state.stream_error is not None:
            settings_win.show_error(state.stream_error)
        else:
            settings_win.clear_error()

    def _do_quit() -> None:
        state.quitting = True
        stream.stop()
        app.quit()

    # --- ストリーム開始・再接続 ---
    def _start_stream() -> None:
        """ストリームを起動する。失敗時は 3 秒後に再試行する。

        _reconnecting フラグで再試行タイマーを 1 本に限定し多重スタックを防ぐ。
        """
        if state.quitting:
            return
        state.reconnecting = True
        try:
            stream.restart()
            state.reconnecting = False
            state.stream_error = None
            if tray is not None:
                tray.set_normal_state()
            if settings_win is not None:
                settings_win.clear_error()
        except Exception as exc:
            msg = str(exc)
            print(f"[Filtflow] AudioStream エラー: {msg}", file=sys.stderr)
            state.stream_error = msg
            if tray is not None:
                tray.set_error_state()
            if settings_win is not None:
                settings_win.show_error(msg)
            # state.reconnecting は True のまま保持し、次の試行が終わるまでスキップさせる
            QTimer.singleShot(RECONNECT_INTERVAL_MS, _start_stream)

    def _watch_stream() -> None:
        """起動後のストリーム死活を監視し、停止を検出したら再接続する。

        _reconnecting が True の間はスキップして再試行タイマーの多重スタックを防ぐ。
        """
        if state.quitting:
            return
        if not stream.is_active and not state.reconnecting:
            _start_stream()
        QTimer.singleShot(RECONNECT_INTERVAL_MS, _watch_stream)

    # --- 更新チェック（起動時に1回、バックグラウンドで実行） ---
    update_checker = UpdateChecker()

    def _on_update_available(latest: str, url: str) -> None:
        # update_available は UpdateChecker がメインスレッドで発火することを
        # 保証しているため、クロージャ接続でも GUI 操作は安全
        state.pending_update = (latest, url)
        if settings_win is not None:
            settings_win.show_update(latest, url)

    update_checker.update_available.connect(_on_update_available)
    if APP_VERSION:
        update_checker.check(APP_VERSION)

    # --- トレイアイコン起動 ---
    tray = TrayIcon(on_open_settings=_show_settings, on_quit=_do_quit)
    tray.show()

    # ストリーム開始（after でイベントループを先に立ち上げてから非同期に開始）
    QTimer.singleShot(100, _start_stream)
    # 死活監視ループ開始（初回起動猶予の後にスタート）
    QTimer.singleShot(100 + RECONNECT_INTERVAL_MS, _watch_stream)

    # --- メインループ（Qt） ---
    try:
        app.exec()
    finally:
        stream.stop()
        if tray is not None:
            tray.stop()


if __name__ == "__main__":
    main()
