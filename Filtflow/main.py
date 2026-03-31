"""エントリポイント・起動制御

起動フロー:
1. Config をロード
2. Compressor / Expander を初期化
3. AudioStream を構築して開始
4. pystray トレイアイコンをデーモンスレッドで起動
5. tkinter mainloop() をメインスレッドで実行

終了フロー:
- トレイ「終了」 → tkinter.Tk.quit() → mainloop() 終了 → AudioStream.stop()
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
from typing import Callable

import numpy as np

from audio_stream import AudioStream, find_device_index
from compressor import Compressor
from config import Config
from expander import Expander
from tray import TrayIcon
from ui import SettingsWindow

# レベルメーターキューの最大サイズ
LEVEL_QUEUE_MAXSIZE: int = 16

# ストリームエラー時の自動再接続間隔 (ms)
RECONNECT_INTERVAL_MS: int = 3000


def _build_filter_chain(
    compressor: Compressor,
    expander: Expander,
) -> list[Callable[[np.ndarray], np.ndarray]]:
    """両フィルタを常にチェーンに含める。有効/無効は各フィルタの enabled フラグで制御する。"""
    return [compressor.process, expander.process]


def main() -> None:
    # --- 設定ロード ---
    config = Config.load()

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

    # --- tkinter ルートウィンドウ（非表示で常駐） ---
    root = tk.Tk()
    root.withdraw()
    root.title("Filtflow")

    # 設定ウィンドウの参照（遅延生成）
    settings_win: SettingsWindow | None = None
    tray: TrayIcon | None = None

    # 終了フラグ（list で可変にして内側関数から参照する）
    _quitting: list[bool] = [False]

    def open_settings() -> None:
        """トレイから設定ウィンドウを開く。tkinter スレッドセーフ呼び出し。"""
        root.after(0, _show_settings)

    def _show_settings() -> None:
        nonlocal settings_win
        if settings_win is None or not settings_win.winfo_exists():
            settings_win = SettingsWindow(
                master=root,
                config=config,
                compressor=compressor,
                expander=expander,
                stream=stream,
                level_queue=level_queue,
            )
        else:
            settings_win.deiconify()
            settings_win.lift()
            settings_win.focus_force()

    def quit_app() -> None:
        """アプリケーション終了。tkinter スレッドセーフ呼び出し。"""
        root.after(0, _do_quit)

    def _do_quit() -> None:
        _quitting[0] = True
        stream.stop()
        root.quit()

    # --- ストリーム開始・再接続 ---
    def _start_stream() -> None:
        """ストリームを起動する。失敗時は 3 秒後に再試行する。

        restart() を使うことで、起動時の初回起動と
        起動後の再接続（stream.stop() 後の再起動）の両方に対応する。
        """
        if _quitting[0]:
            return
        try:
            stream.restart()
            if tray is not None:
                tray.set_normal_state()
        except Exception as exc:
            print(f"[Filtflow] AudioStream エラー: {exc}", file=sys.stderr)
            if tray is not None:
                tray.set_error_state()
            root.after(RECONNECT_INTERVAL_MS, _start_stream)

    def _watch_stream() -> None:
        """起動後のストリーム死活を監視し、停止を検出したら再接続する。

        設計書「ストリーム途切れ → 3秒後に自動再接続」に対応。
        デバイス抜き差しや予期しない停止を拾う。
        """
        if _quitting[0]:
            return
        if not stream.is_active:
            _start_stream()
        root.after(RECONNECT_INTERVAL_MS, _watch_stream)

    # --- トレイアイコン起動 ---
    tray = TrayIcon(on_open_settings=open_settings, on_quit=quit_app)
    tray.run_detached()

    # ストリーム開始（tkinter の after で非同期に開始してメインループを先に立ち上げる）
    root.after(100, _start_stream)
    # 死活監視ループ開始（初回起動猶予の後にスタート）
    root.after(100 + RECONNECT_INTERVAL_MS, _watch_stream)

    # --- メインループ（tkinter） ---
    try:
        root.mainloop()
    finally:
        stream.stop()
        if tray is not None:
            tray.stop()


if __name__ == "__main__":
    main()
