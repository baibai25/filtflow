"""Expander / ノイズゲートフィルタの基本テスト。"""

from __future__ import annotations

import math

import numpy as np

from Filtflow.expander import (
    DETECTOR_PEAK,
    DETECTOR_RMS,
    EXP_MIN_THRESHOLD_DB,
    Expander,
    _db_to_mul,
)


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
        return Expander(**defaults)

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

    def test_matches_scalar_reference(self) -> None:
        """ベクトル化実装がサンプル毎のスカラー参照実装と数値一致することを確認。"""
        for detector in (DETECTOR_RMS, DETECTOR_PEAK):
            exp = self._make_expander(
                threshold=-40.0, ratio=4.0, output_gain_db=2.0, detector=detector
            )

            # スカラー参照実装（ベクトル化前のアルゴリズムを忠実に再現）
            runave = 0.0
            gain_state = 0.0
            rmscoef = exp._rmscoef
            attack = exp._attack_gain
            release = exp._release_gain

            rng = np.random.default_rng(42)
            # 複数ブロックを続けて処理し、ブロック間の状態引き継ぎも検証する
            for _ in range(3):
                frame = (rng.standard_normal((480, 1)) * 0.05).astype(np.float32)
                expected = np.empty_like(frame.flatten())
                for i, s in enumerate(frame.flatten()):
                    sample = float(s)
                    abs_sample = abs(sample)
                    if detector == DETECTOR_RMS:
                        runave = rmscoef * runave + (1.0 - rmscoef) * abs_sample * abs_sample
                        env_in = math.sqrt(max(runave, 0.0))
                    else:
                        env_in = abs_sample
                    if env_in > 1e-10:
                        env_db = max(20.0 * math.log10(env_in), EXP_MIN_THRESHOLD_DB)
                    else:
                        env_db = EXP_MIN_THRESHOLD_DB
                    if env_db < exp._threshold:
                        target = exp._slope * (exp._threshold - env_db)
                    else:
                        target = 0.0
                    if target < gain_state:
                        gain_state = attack * gain_state + (1.0 - attack) * target
                    else:
                        gain_state = release * gain_state + (1.0 - release) * target
                    expected[i] = sample * _db_to_mul(gain_state) * exp._output_gain

                out = exp.process(frame)
                np.testing.assert_allclose(out.flatten(), expected, rtol=1e-6, atol=1e-9)

    def test_multichannel_state_isolation(self) -> None:
        """ステレオ処理時にチャンネル間で状態（runave/gain_db）が混ざらないことを確認。"""
        exp_stereo = self._make_expander(threshold=-20.0, ratio=10.0)
        exp_mono = self._make_expander(threshold=-20.0, ratio=10.0)

        rng = np.random.default_rng(7)
        loud = (rng.standard_normal((480, 1)) * 0.9).astype(np.float32)
        quiet = (rng.standard_normal((480, 1)) * 0.001).astype(np.float32)
        stereo = np.hstack([loud, quiet])

        out_stereo = exp_stereo.process(stereo)
        out_quiet_alone = exp_mono.process(quiet)

        # 静かなチャンネルは大音量チャンネルの影響を受けず、単独処理と一致する
        np.testing.assert_allclose(out_stereo[:, 1:2], out_quiet_alone, rtol=1e-6, atol=1e-9)
