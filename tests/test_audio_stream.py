"""AudioStream のコールバック・レベルメーターテスト。

sounddevice は PortAudio に依存するため、CI 環境ではモックを使用する。
"""

from __future__ import annotations

import queue
import sys
import types
from unittest import mock

import numpy as np

# sounddevice が PortAudio なしでインポートに失敗する環境向けにモックを差し込む
_sd_mock = types.ModuleType("sounddevice")
_sd_mock.Stream = mock.MagicMock  # type: ignore[attr-defined]
_sd_mock.CallbackFlags = type(None)  # type: ignore[attr-defined]
_sd_mock.query_devices = mock.MagicMock(return_value=[])  # type: ignore[attr-defined]
_sd_mock.query_hostapis = mock.MagicMock(return_value=[])  # type: ignore[attr-defined]
sys.modules.setdefault("sounddevice", _sd_mock)

from Filtflow.audio_stream import AudioStream  # noqa: E402


class TestAudioStreamCallback:
    def test_callback_applies_filter_chain(self) -> None:
        """コールバックがフィルタチェーンを適用することを確認。"""

        def double_filter(frame: np.ndarray) -> np.ndarray:
            return frame * 2.0

        stream = AudioStream(
            input_device=0,
            output_device=1,
            filter_chain=[double_filter],
            sample_rate=48000,
            block_size=480,
        )

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)

        stream._callback(indata, outdata, 480, None, None)  # type: ignore[arg-type]
        np.testing.assert_allclose(outdata, 1.0)

    def test_callback_chain_order(self) -> None:
        """フィルタチェーンが順番に適用されることを確認。"""
        log: list[str] = []

        def filter_a(frame: np.ndarray) -> np.ndarray:
            log.append("a")
            return frame + 0.1

        def filter_b(frame: np.ndarray) -> np.ndarray:
            log.append("b")
            return frame * 2.0

        stream = AudioStream(
            input_device=0,
            output_device=1,
            filter_chain=[filter_a, filter_b],
            sample_rate=48000,
            block_size=480,
        )

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)
        stream._callback(indata, outdata, 480, None, None)  # type: ignore[arg-type]

        assert log == ["a", "b"]
        # (0.5 + 0.1) * 2.0 = 1.2
        np.testing.assert_allclose(outdata, 1.2, atol=1e-6)

    def test_callback_pushes_level(self) -> None:
        """コールバック後にレベルキューに値が積まれることを確認。"""
        level_q: queue.Queue[float] = queue.Queue(maxsize=100)
        stream = AudioStream(
            input_device=0,
            output_device=1,
            filter_chain=[],
            sample_rate=48000,
            block_size=480,
            level_queue=level_q,
        )

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)
        stream._callback(indata, outdata, 480, None, None)  # type: ignore[arg-type]

        assert not level_q.empty()
        level_db = level_q.get_nowait()
        assert isinstance(level_db, float)
        assert level_db <= 0.0  # 0.5 RMS → 約 -6 dB

    def test_start_without_input_device_raises(self) -> None:
        """入力デバイス未設定で start() すると RuntimeError。"""
        stream = AudioStream(
            input_device=None,
            output_device=1,
            filter_chain=[],
            sample_rate=48000,
            block_size=480,
        )
        try:
            stream.start()
            assert False, "Expected RuntimeError"
        except RuntimeError:
            assert stream.error is not None

    def test_start_without_output_device_raises(self) -> None:
        """出力デバイス未設定で start() すると RuntimeError。"""
        stream = AudioStream(
            input_device=0,
            output_device=None,
            filter_chain=[],
            sample_rate=48000,
            block_size=480,
        )
        try:
            stream.start()
            assert False, "Expected RuntimeError"
        except RuntimeError:
            assert stream.error is not None
