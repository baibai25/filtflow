"""エキスパンダーフィルタ（ノイズゲートを含む）

OBS Studio の plugins/obs-filters/expander-filter.c に準拠したアルゴリズム。
参照箇所: expander_defaults(), analyze_envelope(), process_sample(), process_expansion()

Based on OBS Studio - plugins/obs-filters/expander-filter.c
Copyright (C) OBS Project contributors
Licensed under the GNU General Public License v2 (GPL-2.0)
https://github.com/obsproject/obs-studio
"""

from __future__ import annotations

import math

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


def _db_to_mul(db: float) -> float:
    """dB 値を線形倍率に変換する。"""
    return math.pow(10.0, db / 20.0)


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

        # RMS 検出用ランニング平均（1チャンネル分）
        # rmscoef = exp2(-100.0 / sample_rate)
        self._rmscoef: float = math.pow(2.0, -100.0 / sample_rate)
        self._runave: float = 0.0

        # ゲイン平滑化の状態変数
        self._gain_db: float = 0.0

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

    def _detect_envelope(self, abs_sample: float) -> float:
        """analyze_envelope: RMS またはピークでエンベロープを検出する。"""
        if self._detector == DETECTOR_RMS:
            # RMS 検出: ランニング平均で二乗平均を計算
            self._runave = (
                self._rmscoef * self._runave + (1.0 - self._rmscoef) * abs_sample * abs_sample
            )
            return math.sqrt(max(self._runave, 0.0))
        else:
            # ピーク検出
            return abs_sample

    def _process_sample(self, env_db: float) -> float:
        """process_sample: ゲイン計算とアタック/リリース平滑化。

        Returns:
            平滑化後の gain_db 値。
        """
        # ゲイン計算
        # slope = 1 - ratio（ratio>1 で負値）
        # 閾値以下では (threshold - env_db) が正 → gain_db は負 = 減衰
        if env_db < self._threshold:
            target_gain_db = self._slope * (self._threshold - env_db)
        else:
            target_gain_db = 0.0

        # アタック/リリースで平滑化
        # gain_db < 前回値 (より多くの減衰へ向かう) → attack_gain で追う
        # gain_db > 前回値 (減衰から回復) → release_gain で戻す
        if target_gain_db < self._gain_db:
            self._gain_db = (
                self._attack_gain * self._gain_db + (1.0 - self._attack_gain) * target_gain_db
            )
        else:
            self._gain_db = (
                self._release_gain * self._gain_db + (1.0 - self._release_gain) * target_gain_db
            )

        return self._gain_db

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
        samples = frame.flatten()
        out = np.empty_like(samples)

        for i in range(len(samples)):
            sample = float(samples[i])
            abs_sample = abs(sample)

            # analyze_envelope: エンベロープ検出
            # モノラルなのでチャンネル間 max は不要だが設計通りに実装
            env_in = self._detect_envelope(abs_sample)

            # envelope_buf = max(envelope_buf, env_in)  ← チャンネル間でmax
            # モノラルなので env_in をそのまま使う
            if env_in > 1e-10:
                env_db = 20.0 * math.log10(env_in)
                env_db = max(env_db, EXP_MIN_THRESHOLD_DB)
            else:
                env_db = EXP_MIN_THRESHOLD_DB

            # process_sample: ゲイン計算 + 平滑化
            gain_db = self._process_sample(env_db)

            out[i] = sample * _db_to_mul(gain_db) * self._output_gain

        return out.reshape(shape)
