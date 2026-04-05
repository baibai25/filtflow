"""コンプレッサーフィルタ

OBS Studio の plugins/obs-filters/compressor-filter.c に準拠したアルゴリズム。
参照箇所: compressor_defaults(), analyze_envelope(), process_compression()

Based on OBS Studio - plugins/obs-filters/compressor-filter.c
Copyright (C) OBS Project contributors
Licensed under the GNU General Public License v2 (GPL-2.0)
https://github.com/obsproject/obs-studio
"""

from __future__ import annotations

import math

import numpy as np

# --- OBS compressor-filter.c 由来の定数 ---
COMP_MIN_RATIO: float = 1.0
COMP_MAX_RATIO: float = 32.0
COMP_MIN_THRESHOLD_DB: float = -60.0
COMP_MAX_THRESHOLD_DB: float = 0.0
COMP_MIN_OUTPUT_GAIN: float = -32.0
COMP_MAX_OUTPUT_GAIN: float = 32.0
COMP_MIN_ATK_RLS_MS: int = 1
COMP_MAX_ATK_MS: int = 100
COMP_MAX_RLS_MS: int = 1000

# OBS デフォルト値
COMP_DEFAULT_RATIO: float = 10.0
COMP_DEFAULT_THRESHOLD_DB: float = -18.0
COMP_DEFAULT_ATTACK_MS: int = 6
COMP_DEFAULT_RELEASE_MS: int = 60
COMP_DEFAULT_OUTPUT_GAIN_DB: float = 0.0


def _gain_coefficient(sample_rate: int, time_ms: float) -> float:
    """OBS gain_coefficient() の Python 実装。

    exp(-1.0 / (sample_rate * time_ms / 1000))
    """
    return math.exp(-1.0 / (sample_rate * time_ms / 1000.0))


def _db_to_mul(db: float) -> float:
    """dB 値を線形倍率に変換する。"""
    return math.pow(10.0, db / 20.0)


class Compressor:
    """OBS compressor-filter.c 準拠のコンプレッサーフィルタ。

    analyze_envelope() でピーク検出し、process_compression() でゲイン適用する。
    """

    def __init__(
        self,
        ratio: float,
        threshold: float,
        attack_ms: int,
        release_ms: int,
        output_gain_db: float,
        sample_rate: int,
        enabled: bool = True,
    ) -> None:
        self._sample_rate = sample_rate
        self.enabled: bool = enabled
        # エンベロープ検出器の状態変数
        self._envelope: float = 0.0

        # パラメータを設定（_slope 等の派生値も同時に計算）
        self._ratio: float = ratio
        self._slope: float = 1.0 - (1.0 / ratio)
        self._threshold: float = threshold
        self._attack_gain: float = _gain_coefficient(sample_rate, attack_ms)
        self._release_gain: float = _gain_coefficient(sample_rate, release_ms)
        self._output_gain: float = _db_to_mul(output_gain_db)

    def update_params(self, **kwargs: float | int) -> None:
        """パラメータをリアルタイム更新する。スライダー操作中に呼び出される。"""
        if "ratio" in kwargs:
            self._ratio = float(kwargs["ratio"])
            self._slope = 1.0 - (1.0 / self._ratio)
        if "threshold" in kwargs:
            self._threshold = float(kwargs["threshold"])
        if "attack_ms" in kwargs:
            self._attack_gain = _gain_coefficient(self._sample_rate, float(kwargs["attack_ms"]))
        if "release_ms" in kwargs:
            self._release_gain = _gain_coefficient(self._sample_rate, float(kwargs["release_ms"]))
        if "output_gain_db" in kwargs:
            self._output_gain = _db_to_mul(float(kwargs["output_gain_db"]))

    def process(self, frame: np.ndarray) -> np.ndarray:
        """1フレーム分の音声データにコンプレッションを適用する。

        Args:
            frame: shape (block_size, channels) の float32 配列。

        Returns:
            同 shape の処理済み配列。enabled=False のときは入力をそのまま返す。
        """
        if not self.enabled:
            return frame

        shape = frame.shape
        samples = frame.flatten()
        out = np.empty_like(samples)

        for i in range(len(samples)):
            sample = float(samples[i])
            abs_sample = abs(sample)

            # analyze_envelope: ピーク検出
            # 上昇時は attack_gain、下降時は release_gain を使う
            if abs_sample >= self._envelope:
                self._envelope = (
                    self._attack_gain * self._envelope + (1.0 - self._attack_gain) * abs_sample
                )
            else:
                self._envelope = (
                    self._release_gain * self._envelope + (1.0 - self._release_gain) * abs_sample
                )

            # process_compression: ゲイン計算
            if self._envelope > 1e-10:
                envelope_db = 20.0 * math.log10(self._envelope)
                if envelope_db > self._threshold:
                    gain_db = self._slope * (self._threshold - envelope_db)
                else:
                    gain_db = 0.0
            else:
                gain_db = 0.0

            out[i] = sample * _db_to_mul(gain_db) * self._output_gain

        return out.reshape(shape)
