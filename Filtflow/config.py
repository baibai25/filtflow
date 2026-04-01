"""設定値の定義・ロード・保存（JSON）

設定ファイルは %APPDATA%/Filtflow/config.json に保存される。
初回起動時は OBS デフォルト値で自動生成する。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

CONFIG_DIR: Path = Path(os.environ.get("APPDATA", str(Path.home()))) / "Filtflow"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"


@dataclass
class CompressorConfig:
    enabled: bool = True
    ratio: float = 10.0
    threshold_db: float = -18.0
    attack_ms: int = 6
    release_ms: int = 60
    output_gain_db: float = 0.0


@dataclass
class ExpanderConfig:
    enabled: bool = True
    preset: str = "expander"
    ratio: float = 2.0
    threshold_db: float = -40.0
    attack_ms: int = 10
    release_ms: int = 50
    output_gain_db: float = 0.0
    detector: str = "RMS"


@dataclass
class Config:
    input_device_name: str = ""
    output_device_name: str = "CABLE Input (VB-Audio Virtual Cable)"
    sample_rate: int = 48000
    block_size: int = 480
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

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = cast(dict[str, Any], json.load(f))

        cfg = cls()
        cfg.input_device_name = str(data.get("input_device_name", ""))
        cfg.output_device_name = str(
            data.get("output_device_name", "CABLE Input (VB-Audio Virtual Cable)")
        )
        cfg.sample_rate = int(data.get("sample_rate", 48000))
        cfg.block_size = int(data.get("block_size", 480))

        comp = data.get("compressor", {})
        if isinstance(comp, dict):
            cfg.compressor = CompressorConfig(
                enabled=bool(comp.get("enabled", True)),
                ratio=float(comp.get("ratio", 10.0)),
                threshold_db=float(comp.get("threshold_db", -18.0)),
                attack_ms=int(comp.get("attack_ms", 6)),
                release_ms=int(comp.get("release_ms", 60)),
                output_gain_db=float(comp.get("output_gain_db", 0.0)),
            )

        exp = data.get("expander", {})
        if isinstance(exp, dict):
            cfg.expander = ExpanderConfig(
                enabled=bool(exp.get("enabled", True)),
                preset=str(exp.get("preset", "expander")),
                ratio=float(exp.get("ratio", 2.0)),
                threshold_db=float(exp.get("threshold_db", -40.0)),
                attack_ms=int(exp.get("attack_ms", 10)),
                release_ms=int(exp.get("release_ms", 50)),
                output_gain_db=float(exp.get("output_gain_db", 0.0)),
                detector=str(exp.get("detector", "RMS")),
            )

        return cfg
