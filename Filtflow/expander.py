# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Kotaro Ambai (baibai25)
#
# Python re-implementation of the expander filter algorithm from
# OBS Studio (plugins/obs-filters/expander-filter.c),
# originally licensed under GPL-2.0-or-later.
#
# Modified by Kotaro Ambai (baibai25) in April 2026.
# See the LICENSE file in this repository for the full license text.

"""エキスパンダーフィルタ（ノイズゲートを含む）

OBS Studio の plugins/obs-filters/expander-filter.c に準拠したアルゴリズム。
参照箇所: expander_defaults(), analyze_envelope(), process_sample(), process_expansion()
"""

from __future__ import annotations

import math
from typing import TypeVar

import numpy as np

# --- OBS expander-filter.c 由来の定数 ---
EXP_MIN_RATIO: float = 1.0
EXP_MAX_RATIO: float = 20.0
EXP_MIN_THRESHOLD_DB: float = -60.0
EXP_MAX_THRESHOLD_DB: float = 0.0
EXP_MIN_OUTPUT_GAIN: float = -32.0
EXP_MAX_OUTPUT_GAIN: float = 32.0
EXP_MIN_ATK_RLS_MS: int = 1
EXP_MAX_ATK_MS: int = 100
EXP_MAX_RLS_MS: int = 1000
EXP_DEFAULT_AUDIO_BUF_MS: int = 10  # RMS ウィンドウ幅 (10ms)

# OBS デフォルト値（expander プリセット）
EXP_DEFAULT_RATIO: float = 2.0
EXP_DEFAULT_THRESHOLD_DB: float = -40.0
EXP_DEFAULT_ATTACK_MS: int = 10
EXP_DEFAULT_RELEASE_MS: int = 50
EXP_DEFAULT_OUTPUT_GAIN_DB: float = 0.0

# OBS デフォルト値（gate プリセット）
GATE_DEFAULT_RATIO: float = 10.0
GATE_DEFAULT_THRESHOLD_DB: float = -40.0
GATE_DEFAULT_ATTACK_MS: int = 10
GATE_DEFAULT_RELEASE_MS: int = 125
GATE_DEFAULT_OUTPUT_GAIN_DB: float = 0.0

PRESET_EXPANDER: str = "expander"
PRESET_GATE: str = "gate"
DETECTOR_RMS: str = "RMS"
DETECTOR_PEAK: str = "peak"


def _gain_coefficient(sample_rate: int, time_ms: float) -> float:
    """OBS gain_coefficient() の Python 実装。"""
    return math.exp(-1.0 / (sample_rate * time_ms / 1000.0))


_DbT = TypeVar("_DbT", float, np.ndarray)


def _db_to_mul(db: _DbT) -> _DbT:
    """dB 値を線形倍率に変換する。スカラーと ndarray の両方を受け付ける。"""
    result: _DbT = 10.0 ** (db / 20.0)
    return result


class Expander:
    """OBS expander-filter.c 準拠のエキスパンダー / ノイズゲートフィルタ。

    preset="expander": ソフトなエキスパンション（ratio=2.0）
    preset="gate": ハードなノイズゲート（ratio=10.0）

    detector="RMS": 10ms RMS ウィンドウでレベル検出
    detector="peak": ピーク検出
    """

    def __init__(
        self,
        preset: str,
        ratio: float,
        threshold: float,
        attack_ms: int,
        release_ms: int,
        output_gain_db: float,
        detector: str,
        sample_rate: int,
        enabled: bool = True,
    ) -> None:
        self._sample_rate = sample_rate
        self.enabled: bool = enabled
        self._preset = preset
        self._detector = detector

        # RMS 検出用ランニング平均（チャンネル毎に独立）
        # rmscoef = exp2(-100.0 / sample_rate)
        self._rmscoef: float = math.pow(2.0, -100.0 / sample_rate)
        self._runave: list[float] = [0.0]

        # ゲイン平滑化の状態変数（チャンネル毎に独立）
        self._gain_db: list[float] = [0.0]

        # パラメータ設定
        self._ratio: float = ratio
        self._slope: float = 1.0 - ratio  # OBS: slope = 1.0f - cd->ratio
        self._threshold: float = threshold
        self._attack_gain: float = _gain_coefficient(sample_rate, attack_ms)
        self._release_gain: float = _gain_coefficient(sample_rate, release_ms)
        self._output_gain: float = _db_to_mul(output_gain_db)

    def update_params(self, **kwargs: float | int | str) -> None:
        """パラメータをリアルタイム更新する。スライダー操作中に呼び出される。"""
        if "preset" in kwargs:
            self._preset = str(kwargs["preset"])
        if "ratio" in kwargs:
            self._ratio = float(kwargs["ratio"])
            self._slope = 1.0 - self._ratio
        if "threshold" in kwargs:
            self._threshold = float(kwargs["threshold"])
        if "attack_ms" in kwargs:
            self._attack_gain = _gain_coefficient(
                self._sample_rate,
                float(kwargs["attack_ms"]),
            )
        if "release_ms" in kwargs:
            self._release_gain = _gain_coefficient(
                self._sample_rate,
                float(kwargs["release_ms"]),
            )
        if "output_gain_db" in kwargs:
            self._output_gain = _db_to_mul(float(kwargs["output_gain_db"]))
        if "detector" in kwargs:
            self._detector = str(kwargs["detector"])

    def _detect_envelope(self, abs_samples: np.ndarray, channel: int) -> np.ndarray:
        """analyze_envelope: RMS またはピークでエンベロープを検出する（1チャンネル分）。"""
        if self._detector == DETECTOR_RMS:
            # RMS 検出: ランニング平均で二乗平均を計算
            # 一次 IIR のため逐次ループが必要だが、ローカル変数キャッシュで高速化する
            rmscoef = self._rmscoef
            inv_rmscoef = 1.0 - rmscoef
            runave = self._runave[channel]

            result: list[float] = []
            append = result.append
            for squared in (abs_samples * abs_samples).tolist():
                runave = rmscoef * runave + inv_rmscoef * squared
                append(runave)

            self._runave[channel] = runave
            env: np.ndarray = np.sqrt(np.maximum(np.asarray(result), 0.0))
            return env
        else:
            # ピーク検出
            return abs_samples

    def _smooth_gain(self, target_gain_db: np.ndarray, channel: int) -> np.ndarray:
        """process_sample のアタック/リリース平滑化（1チャンネル分）。

        係数が attack/release で切り替わる一次 IIR のため逐次ループが必要だが、
        ローカル変数キャッシュで属性参照・関数呼び出しを排除する。

        Returns:
            平滑化後の gain_db 配列。
        """
        attack = self._attack_gain
        release = self._release_gain
        inv_attack = 1.0 - attack
        inv_release = 1.0 - release
        gain_db = self._gain_db[channel]

        result: list[float] = []
        append = result.append
        # gain_db < 前回値 (より多くの減衰へ向かう) → attack_gain で追う
        # gain_db > 前回値 (減衰から回復) → release_gain で戻す
        for target in target_gain_db.tolist():
            if target < gain_db:
                gain_db = attack * gain_db + inv_attack * target
            else:
                gain_db = release * gain_db + inv_release * target
            append(gain_db)

        self._gain_db[channel] = gain_db
        return np.asarray(result)

    def process(self, frame: np.ndarray) -> np.ndarray:
        """1フレーム分の音声データにエキスパンションを適用する。

        Args:
            frame: shape (block_size, channels) の float32 配列。

        Returns:
            同 shape の処理済み配列。enabled=False のときは入力をそのまま返す。
        """
        if not self.enabled:
            return frame

        shape = frame.shape
        block = frame.reshape(-1, 1) if frame.ndim == 1 else frame
        channels = block.shape[1]
        # チャンネル数が変わったら状態をリセット
        if len(self._runave) != channels:
            self._runave = [0.0] * channels
            self._gain_db = [0.0] * channels

        out = np.empty_like(block)
        for ch in range(channels):
            samples = block[:, ch].astype(np.float64)

            # analyze_envelope: エンベロープ検出
            env_in = self._detect_envelope(np.abs(samples), ch)

            # env_in <= 1e-10 は log10 後に必ず EXP_MIN_THRESHOLD_DB を下回るためクランプで吸収
            env_db = np.maximum(
                20.0 * np.log10(np.maximum(env_in, 1e-10)),
                EXP_MIN_THRESHOLD_DB,
            )

            # process_sample: ゲイン計算（ブロック一括のベクトル化）+ 平滑化
            # slope = 1 - ratio（ratio>1 で負値）
            # 閾値以下では (threshold - env_db) が正 → gain_db は負 = 減衰
            target_gain_db = np.where(
                env_db < self._threshold,
                self._slope * (self._threshold - env_db),
                0.0,
            )
            gain_db = self._smooth_gain(target_gain_db, ch)

            out[:, ch] = samples * _db_to_mul(gain_db) * self._output_gain

        return out.reshape(shape)
