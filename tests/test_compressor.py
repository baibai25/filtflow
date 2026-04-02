"""Compressor フィルタの基本テスト。"""

from __future__ import annotations

import math

import numpy as np

from Filtflow.compressor import Compressor, _db_to_mul, _gain_coefficient


class TestHelpers:
    def test_db_to_mul_zero(self) -> None:
        assert _db_to_mul(0.0) == 1.0

    def test_db_to_mul_positive(self) -> None:
        # +6 dB ≈ 2.0
        assert abs(_db_to_mul(6.0) - 10 ** (6.0 / 20.0)) < 1e-10

    def test_db_to_mul_negative(self) -> None:
        # -20 dB = 0.1
        assert abs(_db_to_mul(-20.0) - 0.1) < 1e-10

    def test_gain_coefficient(self) -> None:
        coeff = _gain_coefficient(48000, 10.0)
        expected = math.exp(-1.0 / (48000 * 10.0 / 1000.0))
        assert abs(coeff - expected) < 1e-15


class TestCompressor:
    def _make_compressor(self, **kwargs: float | int | bool) -> Compressor:
        defaults: dict[str, float | int | bool] = {
            "ratio": 10.0,
            "threshold": -18.0,
            "attack_ms": 6,
            "release_ms": 60,
            "output_gain_db": 0.0,
            "sample_rate": 48000,
            "enabled": True,
        }
        defaults.update(kwargs)
        return Compressor(**defaults)  # type: ignore[arg-type]

    def test_silence_passes_through(self) -> None:
        comp = self._make_compressor()
        frame = np.zeros((480, 1), dtype=np.float32)
        out = comp.process(frame)
        np.testing.assert_array_equal(out, frame)

    def test_disabled_passthrough(self) -> None:
        comp = self._make_compressor(enabled=False)
        frame = np.random.randn(480, 1).astype(np.float32) * 0.5
        out = comp.process(frame)
        np.testing.assert_array_equal(out, frame)

    def test_loud_signal_is_compressed(self) -> None:
        comp = self._make_compressor(threshold=-18.0, ratio=10.0)
        # 0 dBFS の信号 (振幅 1.0)
        frame = np.ones((480, 1), dtype=np.float32) * 0.9
        out = comp.process(frame)
        # 閾値を超えているので圧縮される（出力 < 入力）
        assert float(np.max(np.abs(out))) < 0.9

    def test_quiet_signal_not_compressed(self) -> None:
        comp = self._make_compressor(threshold=-18.0, ratio=10.0)
        # 閾値よりかなり小さい信号
        frame = np.ones((480, 1), dtype=np.float32) * 0.01
        out = comp.process(frame)
        # 圧縮されずほぼ同じ（エンベロープ追従のため完全一致はしない）
        ratio = float(np.mean(np.abs(out))) / float(np.mean(np.abs(frame)))
        assert ratio > 0.9

    def test_output_shape_preserved(self) -> None:
        comp = self._make_compressor()
        frame = np.random.randn(480, 1).astype(np.float32) * 0.5
        out = comp.process(frame)
        assert out.shape == frame.shape

    def test_output_gain(self) -> None:
        comp = self._make_compressor(output_gain_db=6.0)
        # 非常に小さい信号（圧縮がかからない範囲）
        frame = np.ones((480, 1), dtype=np.float32) * 0.001
        out = comp.process(frame)
        # output_gain で増幅されるので入力より大きくなる
        assert float(np.mean(np.abs(out))) > float(np.mean(np.abs(frame)))

    def test_update_params(self) -> None:
        comp = self._make_compressor()
        comp.update_params(
            ratio=2.0, threshold=-30.0, attack_ms=10, release_ms=100, output_gain_db=3.0
        )
        assert comp._ratio == 2.0
        assert comp._threshold == -30.0
