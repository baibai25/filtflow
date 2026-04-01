"""デバイス列挙・WASAPI ストリーム管理

sounddevice を使って WASAPI ストリームを開通し、
コールバック経由でフィルタチェーン（Compressor → Expander）を呼び出す。
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

import numpy as np
import sounddevice as sd

# デフォルト値
DEFAULT_SAMPLE_RATE: int = 48000
DEFAULT_BLOCK_SIZE: int = 480  # 10ms @ 48kHz
DEFAULT_CHANNELS: int = 1


def _get_wasapi_hostapi_index() -> int | None:
    """WASAPI ホスト API のインデックスを返す。

    Windows 以外など WASAPI が存在しない環境では None を返す。
    """
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in str(api.get("name", "")):
            return i
    return None


def list_devices() -> list[dict[str, Any]]:
    """WASAPI デバイス一覧を返す。

    設計書「WASAPI ストリーム管理」に準拠し、WASAPI ホスト API のデバイスのみを返す。
    WASAPI が利用不可の環境（非 Windows 等）ではすべてのデバイスを返す。

    Returns:
        sounddevice のデバイス情報 dict のリスト。
        各要素は "index", "name", "max_input_channels", "max_output_channels" を含む。
    """
    wasapi_idx = _get_wasapi_hostapi_index()
    result: list[dict[str, Any]] = []
    for idx, dev in enumerate(sd.query_devices()):
        d = dict(dev)
        d["index"] = idx
        # WASAPI が利用可能な場合は WASAPI デバイスのみに絞る
        if wasapi_idx is not None and int(d.get("hostapi", -1)) != wasapi_idx:
            continue
        result.append(d)
    return result


def list_input_devices() -> list[dict[str, Any]]:
    """入力チャンネルを持つデバイスのみ返す。"""
    return [d for d in list_devices() if int(d.get("max_input_channels", 0)) > 0]


def list_output_devices() -> list[dict[str, Any]]:
    """出力チャンネルを持つデバイスのみ返す。"""
    return [d for d in list_devices() if int(d.get("max_output_channels", 0)) > 0]


def find_device_index(name: str, is_input: bool = True) -> int | None:
    """デバイス名からインデックスを取得する。

    Args:
        name: デバイス名（部分一致）
        is_input: True なら入力デバイスを検索、False なら出力デバイス

    Returns:
        見つかった場合はデバイスインデックス、見つからない場合は None。
    """
    # 空・空白のみは未設定とみなし None を返す（デフォルトデバイスへのフォールバックを防ぐ）
    if not name.strip():
        return None

    devices = list_input_devices() if is_input else list_output_devices()
    name_lower = name.lower()

    # 完全一致を優先してから部分一致にフォールバック
    for dev in devices:
        if str(dev.get("name", "")).lower() == name_lower:
            return int(dev["index"])
    for dev in devices:
        if name_lower in str(dev.get("name", "")).lower():
            return int(dev["index"])
    return None


class AudioStream:
    """WASAPI 入出力ストリームを管理し、フィルタチェーンを適用する。

    コールバック内でフィルタチェーンを順番に呼び出し、
    フィルタ後の音声を出力デバイスに書き出す。
    レベルメーター用に level_queue へ RMS 値 (dB) を積む。
    """

    def __init__(
        self,
        input_device: int | None,
        output_device: int | None,
        filter_chain: list[Callable[[np.ndarray], np.ndarray]],
        sample_rate: int,
        block_size: int,
        level_queue: queue.Queue[float] | None = None,
    ) -> None:
        self._input_device = input_device
        self._output_device = output_device
        self._filter_chain = filter_chain
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._level_queue = level_queue

        self._stream: sd.Stream | None = None
        self._lock = threading.Lock()
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        """最後に発生したエラーメッセージ。正常時は None。"""
        return self._error

    def _callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """sounddevice コールバック。リアルタイムスレッドから呼ばれる。"""
        if status:
            # xrun 等を stderr に出力（UI 更新は行わない）
            pass

        audio: np.ndarray = indata.copy()

        # フィルタチェーン適用: Compressor → Expander
        for fn in self._filter_chain:
            audio = fn(audio)

        outdata[:] = audio

        # レベルメーター用: フィルタ後 RMS を dB で積む
        if self._level_queue is not None:
            rms = float(np.sqrt(np.mean(audio**2) + 1e-10))
            level_db = 20.0 * np.log10(rms)
            level_db = max(-60.0, float(level_db))
            try:
                self._level_queue.put_nowait(level_db)
            except queue.Full:
                pass

    def start(self) -> None:
        """ストリームを開始する。デバイスが未解決の場合は RuntimeError を送出する。"""
        with self._lock:
            if self._stream is not None:
                return
            self._error = None

            # None のままでは sounddevice がシステムデフォルトにフォールバックするため、
            # 起動前に必ず解決済みデバイスを要求する
            if self._input_device is None:
                self._error = "入力デバイスが見つかりません。UIから入力デバイスを選択してください。"
                raise RuntimeError(self._error)
            if self._output_device is None:
                self._error = (
                    "出力デバイスが見つかりません。"
                    "VB-Cable がインストールされているか確認してください。"
                )
                raise RuntimeError(self._error)

            try:
                self._stream = sd.Stream(
                    device=(self._input_device, self._output_device),
                    samplerate=self._sample_rate,
                    blocksize=self._block_size,
                    channels=(DEFAULT_CHANNELS, DEFAULT_CHANNELS),
                    dtype="float32",
                    callback=self._callback,
                )
                self._stream.start()
            except Exception as exc:
                self._error = str(exc)
                self._stream = None
                raise

    def stop(self) -> None:
        """ストリームを停止する。"""
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def restart(self) -> None:
        """デバイス変更時にストリームを再起動する。"""
        self.stop()
        self.start()

    def update_devices(
        self,
        input_device: int | None,
        output_device: int | None,
    ) -> None:
        """入出力デバイスを変更してストリームを再起動する。"""
        self._input_device = input_device
        self._output_device = output_device
        self.restart()

    def update_block_size(self, block_size: int) -> None:
        """ブロックサイズを変更してストリームを再起動する。"""
        self._block_size = block_size
        self.restart()

    @property
    def is_active(self) -> bool:
        """ストリームが動作中かどうか。"""
        with self._lock:
            return self._stream is not None and self._stream.active
