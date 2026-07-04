"""設定値の定義・ロード・保存（JSON）

設定ファイルは %APPDATA%/Filtflow/config.json に保存される。
初回起動時は OBS デフォルト値で自動生成する。
ファイルが破損している場合は config.json.bak に退避してデフォルト値で再生成し、
不正な値は安全な範囲にクランプまたはデフォルト値へフォールバックする。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

try:
    import compressor
    import expander
except ImportError:  # pytest などからパッケージとしてインポートされる場合
    from Filtflow import (
        compressor,  # type: ignore[no-redef]
        expander,  # type: ignore[no-redef]
    )

CONFIG_DIR: Path = Path(os.environ.get("APPDATA", str(Path.home()))) / "Filtflow"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"

# --- オーディオ設定の安全範囲 ---
DEFAULT_SAMPLE_RATE: int = 48000
MIN_SAMPLE_RATE: int = 8000
MAX_SAMPLE_RATE: int = 384000
DEFAULT_BLOCK_SIZE: int = 480
MIN_BLOCK_SIZE: int = 32
MAX_BLOCK_SIZE: int = 8192

DEFAULT_OUTPUT_DEVICE_NAME: str = "CABLE Input (VB-Audio Virtual Cable)"


def _as_float(value: Any, default: float) -> float:
    """value を float に変換する。変換不能・非有限値（NaN/Inf）は default を返す。"""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: float に収まらない巨大な int
        return default
    if not math.isfinite(result):
        return default
    return result


def _as_int(value: Any, default: int) -> int:
    """value を int に変換する。変換不能な値は default を返す。"""
    return int(_as_float(value, float(default)))


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    """value を float に変換し [lo, hi] にクランプする。"""
    return min(max(_as_float(value, default), lo), hi)


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    """value を int に変換し [lo, hi] にクランプする。"""
    return min(max(_as_int(value, default), lo), hi)


def _as_choice(value: Any, default: str, allowed: tuple[str, ...]) -> str:
    """value が許可リストに含まれる文字列ならそのまま返し、それ以外は default を返す。"""
    text = str(value)
    return text if text in allowed else default


def _backup_broken_config() -> None:
    """破損した設定ファイルを config.json.bak として退避する。"""
    try:
        shutil.copyfile(CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bak"))
    except OSError:
        pass


@dataclass
class CompressorConfig:
    enabled: bool = True
    ratio: float = compressor.COMP_DEFAULT_RATIO
    threshold_db: float = compressor.COMP_DEFAULT_THRESHOLD_DB
    attack_ms: int = compressor.COMP_DEFAULT_ATTACK_MS
    release_ms: int = compressor.COMP_DEFAULT_RELEASE_MS
    output_gain_db: float = compressor.COMP_DEFAULT_OUTPUT_GAIN_DB


@dataclass
class ExpanderConfig:
    enabled: bool = True
    preset: str = expander.PRESET_EXPANDER
    ratio: float = expander.EXP_DEFAULT_RATIO
    threshold_db: float = expander.EXP_DEFAULT_THRESHOLD_DB
    attack_ms: int = expander.EXP_DEFAULT_ATTACK_MS
    release_ms: int = expander.EXP_DEFAULT_RELEASE_MS
    output_gain_db: float = expander.EXP_DEFAULT_OUTPUT_GAIN_DB
    detector: str = expander.DETECTOR_RMS


@dataclass
class Config:
    input_device_name: str = ""
    output_device_name: str = DEFAULT_OUTPUT_DEVICE_NAME
    sample_rate: int = DEFAULT_SAMPLE_RATE
    block_size: int = DEFAULT_BLOCK_SIZE
    appearance_mode: str = "dark"
    compressor: CompressorConfig = field(default_factory=CompressorConfig)
    expander: ExpanderConfig = field(default_factory=ExpanderConfig)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls) -> Config:
        if not CONFIG_FILE.exists():
            cfg = cls()
            cfg.save()
            return cfg

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("config root must be a JSON object")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            # json.JSONDecodeError は ValueError のサブクラス
            print(
                f"[Filtflow] config.json の読み込みに失敗しました ({exc})。"
                "config.json.bak に退避してデフォルト設定に戻します。",
                file=sys.stderr,
            )
            _backup_broken_config()
            cfg = cls()
            cfg.save()
            return cfg

        return cls._from_dict(cast(dict[str, Any], raw))

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Config:
        """dict から Config を構築する。不正値はクランプまたはデフォルト値に置き換える。"""
        cfg = cls()
        cfg.input_device_name = str(data.get("input_device_name", ""))
        cfg.output_device_name = str(data.get("output_device_name", DEFAULT_OUTPUT_DEVICE_NAME))
        cfg.sample_rate = _clamp_int(
            data.get("sample_rate"), DEFAULT_SAMPLE_RATE, MIN_SAMPLE_RATE, MAX_SAMPLE_RATE
        )
        cfg.block_size = _clamp_int(
            data.get("block_size"), DEFAULT_BLOCK_SIZE, MIN_BLOCK_SIZE, MAX_BLOCK_SIZE
        )
        raw_mode = str(data.get("appearance_mode", "dark"))
        # qt-material テーマ名（旧形式）を dark / light に正規化する
        if raw_mode.startswith("dark"):
            cfg.appearance_mode = "dark"
        elif raw_mode.startswith("light"):
            cfg.appearance_mode = "light"
        else:
            cfg.appearance_mode = "dark"

        comp = data.get("compressor")
        if isinstance(comp, dict):
            cfg.compressor = CompressorConfig(
                enabled=bool(comp.get("enabled", True)),
                ratio=_clamp_float(
                    comp.get("ratio"),
                    compressor.COMP_DEFAULT_RATIO,
                    compressor.COMP_MIN_RATIO,
                    compressor.COMP_MAX_RATIO,
                ),
                threshold_db=_clamp_float(
                    comp.get("threshold_db"),
                    compressor.COMP_DEFAULT_THRESHOLD_DB,
                    compressor.COMP_MIN_THRESHOLD_DB,
                    compressor.COMP_MAX_THRESHOLD_DB,
                ),
                attack_ms=_clamp_int(
                    comp.get("attack_ms"),
                    compressor.COMP_DEFAULT_ATTACK_MS,
                    compressor.COMP_MIN_ATK_RLS_MS,
                    compressor.COMP_MAX_ATK_MS,
                ),
                release_ms=_clamp_int(
                    comp.get("release_ms"),
                    compressor.COMP_DEFAULT_RELEASE_MS,
                    compressor.COMP_MIN_ATK_RLS_MS,
                    compressor.COMP_MAX_RLS_MS,
                ),
                output_gain_db=_clamp_float(
                    comp.get("output_gain_db"),
                    compressor.COMP_DEFAULT_OUTPUT_GAIN_DB,
                    compressor.COMP_MIN_OUTPUT_GAIN,
                    compressor.COMP_MAX_OUTPUT_GAIN,
                ),
            )

        exp = data.get("expander")
        if isinstance(exp, dict):
            cfg.expander = ExpanderConfig(
                enabled=bool(exp.get("enabled", True)),
                preset=_as_choice(
                    exp.get("preset"),
                    expander.PRESET_EXPANDER,
                    (expander.PRESET_EXPANDER, expander.PRESET_GATE),
                ),
                ratio=_clamp_float(
                    exp.get("ratio"),
                    expander.EXP_DEFAULT_RATIO,
                    expander.EXP_MIN_RATIO,
                    expander.EXP_MAX_RATIO,
                ),
                threshold_db=_clamp_float(
                    exp.get("threshold_db"),
                    expander.EXP_DEFAULT_THRESHOLD_DB,
                    expander.EXP_MIN_THRESHOLD_DB,
                    expander.EXP_MAX_THRESHOLD_DB,
                ),
                attack_ms=_clamp_int(
                    exp.get("attack_ms"),
                    expander.EXP_DEFAULT_ATTACK_MS,
                    expander.EXP_MIN_ATK_RLS_MS,
                    expander.EXP_MAX_ATK_MS,
                ),
                release_ms=_clamp_int(
                    exp.get("release_ms"),
                    expander.EXP_DEFAULT_RELEASE_MS,
                    expander.EXP_MIN_ATK_RLS_MS,
                    expander.EXP_MAX_RLS_MS,
                ),
                output_gain_db=_clamp_float(
                    exp.get("output_gain_db"),
                    expander.EXP_DEFAULT_OUTPUT_GAIN_DB,
                    expander.EXP_MIN_OUTPUT_GAIN,
                    expander.EXP_MAX_OUTPUT_GAIN,
                ),
                detector=_as_choice(
                    exp.get("detector"),
                    expander.DETECTOR_RMS,
                    (expander.DETECTOR_RMS, expander.DETECTOR_PEAK),
                ),
            )

        return cfg
