"""Expander / ノイズゲートフィルタの基本テスト。"""

from __future__ import annotations

import numpy as np

from Filtflow.expander import Expander, DETECTOR_PEAK, DETECTOR_RMS


class TestExpander:
    def _make_expander(self, **kwargs: float | int | str | bool) -> Expander:
        defaults: dict[str, float | int | str | bool] = {
            "preset": "expander",
            "ratio": 2.0,
            "threshold": -40.0,
            "attack_ms": 10,
            "release_ms": 50,
            "output_gain_db": 0.0,
            "detector": "RMS",
            "sample_rate": 48000,
            "enabled": True,
        }
        defaults.update(kwargs)
        return Expander(**defaults)  # type: ignore[arg-type]

    def test_silence_stays_silent(self) -> None:
        exp = self._make_expander()
        frame = np.zeros((480, 1), dtype=np.float32)
        out = exp.process(frame)
        np.testing.assert_array_equal(out, frame)

    def test_disabled_passthrough(self) -> None:
        exp = self._make_expander(enabled=False)
        frame = np.random.randn(480, 1).astype(np.float32) * 0.5
        out = exp.process(frame)
        np.testing.assert_array_equal(out, frame)

    def test_quiet_signal_is_attenuated(self) -> None:
        exp = self._make_expander(threshold=-20.0, ratio=10.0, detector="peak")
        # 閾値 (-20 dB ≈ 0.1) より小さい信号
        frame = np.ones((480, 1), dtype=np.float32) * 0.01
        out = exp.process(frame)
        # ゲートで減衰される
        assert float(np.max(np.abs(out))) < float(np.max(np.abs(frame)))

    def test_loud_signal_passes(self) -> None:
        exp = self._make_expander(threshold=-40.0, ratio=2.0, detector="peak")
        # 閾値 (-40 dB ≈ 0.01) より十分大きい信号
        frame = np.ones((480, 1), dtype=np.float32) * 0.5
        out = exp.process(frame)
        # ほとんど減衰されない
        ratio = float(np.mean(np.abs(out))) / float(np.mean(np.abs(frame)))
        assert ratio > 0.9

    def test_output_shape_preserved(self) -> None:
        exp = self._make_expander()
        frame = np.random.randn(480, 1).astype(np.float32) * 0.5
        out = exp.process(frame)
        assert out.shape == frame.shape

    def test_rms_detector(self) -> None:
        exp = self._make_expander(detector=DETECTOR_RMS)
        frame = np.ones((480, 1), dtype=np.float32) * 0.5
        out = exp.process(frame)
        assert out.shape == frame.shape

    def test_peak_detector(self) -> None:
        exp = self._make_expander(detector=DETECTOR_PEAK)
        frame = np.ones((480, 1), dtype=np.float32) * 0.5
        out = exp.process(frame)
        assert out.shape == frame.shape

    def test_gate_preset(self) -> None:
        exp = self._make_expander(preset="gate", ratio=10.0, threshold=-30.0, detector="peak")
        # 閾値以下の信号はゲートで強く減衰される
        frame = np.ones((480, 1), dtype=np.float32) * 0.001
        out = exp.process(frame)
        assert float(np.max(np.abs(out))) < float(np.max(np.abs(frame)))

    def test_update_params(self) -> None:
        exp = self._make_expander()
        exp.update_params(ratio=5.0, threshold=-30.0, detector="peak", preset="gate")
        assert exp._ratio == 5.0
        assert exp._threshold == -30.0
        assert exp._detector == "peak"
        assert exp._preset == "gate"
