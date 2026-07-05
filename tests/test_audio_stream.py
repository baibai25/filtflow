"""AudioStream のコールバック・レベルメーターテスト。

sounddevice は PortAudio に依存するため、CI 環境ではモックを使用する。
"""

from __future__ import annotations

import importlib
import queue
import sys
import types
from typing import TYPE_CHECKING
from unittest import mock

import numpy as np
import pytest

if TYPE_CHECKING:
    from Filtflow.audio_stream import AudioStream


@pytest.fixture(autouse=True)
def _mock_sounddevice(monkeypatch: pytest.MonkeyPatch) -> None:
    """各テストごとに sounddevice をモックし、AudioStream を読み込む。"""
    sd_mock = types.ModuleType("sounddevice")
    sd_mock.Stream = mock.MagicMock  # type: ignore[attr-defined]
    sd_mock.CallbackFlags = type(None)  # type: ignore[attr-defined]
    sd_mock.query_devices = mock.MagicMock(return_value=[])  # type: ignore[attr-defined]
    sd_mock.query_hostapis = mock.MagicMock(return_value=[])  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", sd_mock)

    # Filtflow.audio_stream を再読み込みしてモック済み sd を使わせる
    sys.modules.pop("Filtflow.audio_stream", None)
    mod = importlib.import_module("Filtflow.audio_stream")
    globals()["AudioStream"] = mod.AudioStream


def _make_stream(**kwargs: object) -> "AudioStream":
    """AudioStream のヘルパーコンストラクタ。"""
    defaults: dict[str, object] = {
        "input_device": 0,
        "output_device": 1,
        "filter_chain": [],
        "sample_rate": 48000,
        "block_size": 480,
    }
    defaults.update(kwargs)
    cls = globals()["AudioStream"]
    return cls(**defaults)  # type: ignore[no-any-return]


class TestAudioStreamCallback:
    def test_callback_applies_filter_chain(self) -> None:
        """コールバックがフィルタチェーンを適用することを確認。"""

        def double_filter(frame: np.ndarray) -> np.ndarray:
            return frame * 2.0

        stream = _make_stream(filter_chain=[double_filter])

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)

        stream._callback(indata, outdata, 480, None, None)
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

        stream = _make_stream(filter_chain=[filter_a, filter_b])

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)
        stream._callback(indata, outdata, 480, None, None)

        assert log == ["a", "b"]
        # (0.5 + 0.1) * 2.0 = 1.2
        np.testing.assert_allclose(outdata, 1.2, atol=1e-6)

    def test_callback_pushes_level(self) -> None:
        """コールバック後にレベルキューに値が積まれることを確認。"""
        level_q: queue.Queue[float] = queue.Queue(maxsize=100)
        stream = _make_stream(filter_chain=[], level_queue=level_q)

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)
        stream._callback(indata, outdata, 480, None, None)

        assert not level_q.empty()
        level_db = level_q.get_nowait()
        assert isinstance(level_db, float)
        assert level_db <= 0.0  # 0.5 RMS → 約 -6 dB

    def test_callback_counts_status(self) -> None:
        """CallbackFlags（xrun 等）が渡されたときにカウントされることを確認。"""
        stream = _make_stream(filter_chain=[])

        indata = np.ones((480, 1), dtype=np.float32) * 0.5
        outdata = np.zeros((480, 1), dtype=np.float32)

        assert stream.status_count == 0
        stream._callback(indata, outdata, 480, None, "input_underflow")
        assert stream.status_count == 1
        stream._callback(indata, outdata, 480, None, "input_underflow")
        assert stream.status_count == 2
        # status が偽値のときはカウントされない
        stream._callback(indata, outdata, 480, None, None)
        assert stream.status_count == 2

    def test_start_without_input_device_raises(self) -> None:
        """入力デバイス未設定で start() すると RuntimeError。"""
        stream = _make_stream(input_device=None)
        try:
            stream.start()
            raise AssertionError("Expected RuntimeError")
        except RuntimeError:
            assert stream.error is not None

    def test_start_without_output_device_raises(self) -> None:
        """出力デバイス未設定で start() すると RuntimeError。"""
        stream = _make_stream(output_device=None)
        try:
            stream.start()
            raise AssertionError("Expected RuntimeError")
        except RuntimeError:
            assert stream.error is not None
