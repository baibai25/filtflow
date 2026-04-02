"""Config のロード・保存テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Filtflow.config import CompressorConfig, Config, ExpanderConfig


class TestConfigDefaults:
    def test_default_compressor(self) -> None:
        cfg = CompressorConfig()
        assert cfg.enabled is True
        assert cfg.ratio == 10.0
        assert cfg.threshold_db == -18.0

    def test_default_expander(self) -> None:
        cfg = ExpanderConfig()
        assert cfg.enabled is True
        assert cfg.preset == "expander"
        assert cfg.detector == "RMS"

    def test_default_config(self) -> None:
        cfg = Config()
        assert cfg.sample_rate == 48000
        assert cfg.block_size == 480
        assert cfg.appearance_mode == "dark"
        assert isinstance(cfg.compressor, CompressorConfig)
        assert isinstance(cfg.expander, ExpanderConfig)


class TestConfigSaveLoad:
    def test_round_trip(self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> None:
        import Filtflow.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")

        cfg = Config()
        cfg.input_device_name = "Test Mic"
        cfg.compressor.ratio = 5.0
        cfg.expander.threshold_db = -30.0
        cfg.save()

        loaded = Config.load()
        assert loaded.input_device_name == "Test Mic"
        assert loaded.compressor.ratio == 5.0
        assert loaded.expander.threshold_db == -30.0

    def test_load_missing_file_creates_default(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        import Filtflow.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")

        cfg = Config.load()
        assert cfg.sample_rate == 48000
        assert (tmp_path / "config.json").exists()

    def test_legacy_appearance_mode(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        import Filtflow.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")

        # 旧形式のテーマ名
        data = {"appearance_mode": "dark_teal.xml"}
        with open(tmp_path / "config.json", "w") as f:
            json.dump(data, f)

        cfg = Config.load()
        assert cfg.appearance_mode == "dark"

    def test_legacy_light_mode(self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> None:
        import Filtflow.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")

        data = {"appearance_mode": "light_blue.xml"}
        with open(tmp_path / "config.json", "w") as f:
            json.dump(data, f)

        cfg = Config.load()
        assert cfg.appearance_mode == "light"
