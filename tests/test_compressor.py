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
        # attack_ms の立ち上がり直後は未圧縮のサンプルが残りうるため、
        # エンベロープが十分追従した末尾区間で圧縮を確認する
        steady_state = out[-120:]
        assert float(np.max(np.abs(steady_state))) < 0.9

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

    def test_matches_scalar_reference(self) -> None:
        """ベクトル化実装がサンプル毎のスカラー参照実装と数値一致することを確認。"""
        comp = self._make_compressor(threshold=-18.0, ratio=10.0, output_gain_db=3.0)

        # スカラー参照実装（ベクトル化前のアルゴリズムを忠実に再現）
        envelope = 0.0
        attack = comp._attack_gain
        release = comp._release_gain

        rng = np.random.default_rng(42)
        # 複数ブロックを続けて処理し、ブロック間の状態引き継ぎも検証する
        for _ in range(3):
            frame = (rng.standard_normal((480, 1)) * 0.5).astype(np.float32)
            expected = np.empty_like(frame.flatten())
            for i, s in enumerate(frame.flatten()):
                sample = float(s)
                abs_sample = abs(sample)
                if abs_sample >= envelope:
                    envelope = attack * envelope + (1.0 - attack) * abs_sample
                else:
                    envelope = release * envelope + (1.0 - release) * abs_sample
                if envelope > 1e-10:
                    envelope_db = 20.0 * math.log10(envelope)
                    gain_db = (
                        comp._slope * (comp._threshold - envelope_db)
                        if envelope_db > comp._threshold
                        else 0.0
                    )
                else:
                    gain_db = 0.0
                expected[i] = sample * _db_to_mul(gain_db) * comp._output_gain

            out = comp.process(frame)
            np.testing.assert_allclose(out.flatten(), expected, rtol=1e-6, atol=1e-9)

    def test_multichannel_envelope_isolation(self) -> None:
        """ステレオ処理時にチャンネル間でエンベロープ状態が混ざらないことを確認。"""
        comp_stereo = self._make_compressor()
        comp_mono = self._make_compressor()

        rng = np.random.default_rng(7)
        loud = (rng.standard_normal((480, 1)) * 0.9).astype(np.float32)
        quiet = (rng.standard_normal((480, 1)) * 0.001).astype(np.float32)
        stereo = np.hstack([loud, quiet])

        out_stereo = comp_stereo.process(stereo)
        out_quiet_alone = comp_mono.process(quiet)

        # 静かなチャンネルは大音量チャンネルの影響を受けず、単独処理と一致する
        np.testing.assert_allclose(out_stereo[:, 1:2], out_quiet_alone, rtol=1e-6, atol=1e-9)
