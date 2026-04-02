"""エントリポイント・起動制御

起動フロー:
1. Config をロード
2. Compressor / Expander を初期化
3. AudioStream を構築して開始
4. pystray トレイアイコンをデーモンスレッドで起動
5. QApplication のイベントループをメインスレッドで実行

終了フロー:
- トレイ「終了」 → _AppBridge.quit_requested シグナル（QueuedConnection）
  → _do_quit() → stream.stop() → app.quit()
"""

from __future__ import annotations

import queue
import sys
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication

from audio_stream import AudioStream, find_device_index
from compressor import Compressor
from config import Config
from expander import Expander
from tray import TrayIcon
from ui import SettingsWindow, apply_appearance_mode

# レベルメーターキューの最大サイズ
LEVEL_QUEUE_MAXSIZE: int = 16

# ストリームエラー時の自動再接続間隔 (ms)
RECONNECT_INTERVAL_MS: int = 3000


class _AppBridge(QObject):
    """トレイスレッドからメインスレッドへのスレッドセーフなシグナル橋渡し。

    pystray はデーモンスレッドで動くため、UI 操作は QueuedConnection 経由で
    メインスレッドに委譲する。
    """

    open_settings_requested = Signal()
    quit_requested = Signal()


def _build_filter_chain(
    compressor: Compressor,
    expander: Expander,
) -> list[Callable[[np.ndarray], np.ndarray]]:
    """両フィルタを常にチェーンに含める。有効/無効は各フィルタの enabled フラグで制御する。"""
    return [compressor.process, expander.process]


def main() -> None:
    app = QApplication(sys.argv)
    # 最後のウィンドウを閉じてもイベントループを継続（トレイ常駐のため）
    app.setQuitOnLastWindowClosed(False)

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

    # --- シグナルブリッジ（トレイスレッド → メインスレッド） ---
    bridge = _AppBridge()

    settings_win: SettingsWindow | None = None
    tray: TrayIcon | None = None

    # 終了フラグ・再接続中フラグ・エラーメッセージ（list で可変にして内側関数から参照する）
    _quitting: list[bool] = [False]
    _reconnecting: list[bool] = [False]  # 再試行タイマーがすでにキューにあるか
    _stream_error: list[str | None] = [None]  # 最新のストリームエラーメッセージ

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
        # 未解決のストリームエラーがあれば UI にも表示する
        if _stream_error[0] is not None:
            settings_win.show_error(_stream_error[0])
        else:
            settings_win.clear_error()

    def _do_quit() -> None:
        _quitting[0] = True
        stream.stop()
        app.quit()

    # QueuedConnection で確実にメインスレッドで実行させる
    bridge.open_settings_requested.connect(_show_settings, Qt.ConnectionType.QueuedConnection)
    bridge.quit_requested.connect(_do_quit, Qt.ConnectionType.QueuedConnection)

    def open_settings() -> None:
        """トレイから設定ウィンドウを開く。スレッドセーフ。"""
        bridge.open_settings_requested.emit()

    def quit_app() -> None:
        """アプリケーション終了。スレッドセーフ。"""
        bridge.quit_requested.emit()

    # --- ストリーム開始・再接続 ---
    def _start_stream() -> None:
        """ストリームを起動する。失敗時は 3 秒後に再試行する。

        _reconnecting フラグで再試行タイマーを 1 本に限定し多重スタックを防ぐ。
        """
        if _quitting[0]:
            return
        _reconnecting[0] = True
        try:
            stream.restart()
            _reconnecting[0] = False
            _stream_error[0] = None
            if tray is not None:
                tray.set_normal_state()
            if settings_win is not None:
                settings_win.clear_error()
        except Exception as exc:
            msg = str(exc)
            print(f"[Filtflow] AudioStream エラー: {msg}", file=sys.stderr)
            _stream_error[0] = msg
            if tray is not None:
                tray.set_error_state()
            if settings_win is not None:
                settings_win.show_error(msg)
            # _reconnecting[0] は True のまま保持し、次の試行が終わるまでスキップさせる
            QTimer.singleShot(RECONNECT_INTERVAL_MS, _start_stream)

    def _watch_stream() -> None:
        """起動後のストリーム死活を監視し、停止を検出したら再接続する。

        _reconnecting が True の間はスキップして再試行タイマーの多重スタックを防ぐ。
        """
        if _quitting[0]:
            return
        if not stream.is_active and not _reconnecting[0]:
            _start_stream()
        QTimer.singleShot(RECONNECT_INTERVAL_MS, _watch_stream)

    # --- トレイアイコン起動 ---
    tray = TrayIcon(on_open_settings=open_settings, on_quit=quit_app)
    tray.run_detached()

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
