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


@pytest.fixture
def config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CONFIG_DIR / CONFIG_FILE を tmp_path に差し替え、config.json のパスを返す。"""
    import Filtflow.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    return tmp_path / "config.json"


def _write_config(path: Path, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestConfigCorruptedFile:
    """破損した config.json からのフォールバック（Issue #15）。"""

    def test_invalid_json_falls_back_to_defaults(self, config_paths: Path) -> None:
        config_paths.write_text("{ invalid json !!", encoding="utf-8")

        cfg = Config.load()
        assert cfg.sample_rate == 48000
        assert cfg.compressor.ratio == 10.0

    def test_invalid_json_creates_backup(self, config_paths: Path) -> None:
        broken = "{ invalid json !!"
        config_paths.write_text(broken, encoding="utf-8")

        Config.load()
        backup = config_paths.with_suffix(".json.bak")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == broken

    def test_invalid_json_rewrites_valid_config(self, config_paths: Path) -> None:
        config_paths.write_text("{ invalid json !!", encoding="utf-8")

        Config.load()
        # 再生成された config.json は正常にロードできる
        with open(config_paths, encoding="utf-8") as f:
            data = json.load(f)
        assert data["sample_rate"] == 48000

    def test_non_dict_root_falls_back_to_defaults(self, config_paths: Path) -> None:
        _write_config(config_paths, [1, 2, 3])

        cfg = Config.load()
        assert cfg.sample_rate == 48000
        assert config_paths.with_suffix(".json.bak").exists()

    def test_empty_file_falls_back_to_defaults(self, config_paths: Path) -> None:
        config_paths.write_text("", encoding="utf-8")

        cfg = Config.load()
        assert cfg.sample_rate == 48000


class TestConfigValidation:
    """不正値のクランプ・フォールバック（Issue #15）。"""

    def test_compressor_ratio_zero_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"compressor": {"ratio": 0}})

        cfg = Config.load()
        assert cfg.compressor.ratio == 1.0  # COMP_MIN_RATIO

    def test_compressor_attack_zero_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"compressor": {"attack_ms": 0}})

        cfg = Config.load()
        assert cfg.compressor.attack_ms == 1  # COMP_MIN_ATK_RLS_MS

    def test_compressor_negative_attack_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"compressor": {"attack_ms": -10}})

        cfg = Config.load()
        assert cfg.compressor.attack_ms == 1

    def test_compressor_ratio_above_max_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"compressor": {"ratio": 999.0}})

        cfg = Config.load()
        assert cfg.compressor.ratio == 32.0  # COMP_MAX_RATIO

    def test_expander_ratio_zero_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"expander": {"ratio": 0, "attack_ms": 0}})

        cfg = Config.load()
        assert cfg.expander.ratio == 1.0  # EXP_MIN_RATIO
        assert cfg.expander.attack_ms == 1  # EXP_MIN_ATK_RLS_MS

    def test_sample_rate_type_mismatch_falls_back(self, config_paths: Path) -> None:
        _write_config(config_paths, {"sample_rate": "abc"})

        cfg = Config.load()
        assert cfg.sample_rate == 48000

    def test_sample_rate_zero_is_clamped(self, config_paths: Path) -> None:
        _write_config(config_paths, {"sample_rate": 0, "block_size": 0})

        cfg = Config.load()
        assert cfg.sample_rate == 8000  # MIN_SAMPLE_RATE
        assert cfg.block_size == 32  # MIN_BLOCK_SIZE

    def test_nan_and_infinity_fall_back_to_defaults(self, config_paths: Path) -> None:
        # json.load は NaN / Infinity をデフォルトで受理する
        config_paths.write_text(
            '{"compressor": {"ratio": NaN, "threshold_db": -Infinity}}', encoding="utf-8"
        )

        cfg = Config.load()
        assert cfg.compressor.ratio == 10.0
        assert cfg.compressor.threshold_db == -18.0

    def test_ratio_dict_value_falls_back(self, config_paths: Path) -> None:
        _write_config(config_paths, {"compressor": {"ratio": {"nested": 1}}})

        cfg = Config.load()
        assert cfg.compressor.ratio == 10.0

    def test_preset_allowlist(self, config_paths: Path) -> None:
        _write_config(config_paths, {"expander": {"preset": "unknown"}})

        cfg = Config.load()
        assert cfg.expander.preset == "expander"

    def test_preset_gate_is_kept(self, config_paths: Path) -> None:
        _write_config(config_paths, {"expander": {"preset": "gate"}})

        cfg = Config.load()
        assert cfg.expander.preset == "gate"

    def test_detector_allowlist(self, config_paths: Path) -> None:
        _write_config(config_paths, {"expander": {"detector": "bogus"}})

        cfg = Config.load()
        assert cfg.expander.detector == "RMS"

    def test_appearance_mode_allowlist(self, config_paths: Path) -> None:
        _write_config(config_paths, {"appearance_mode": "neon"})

        cfg = Config.load()
        assert cfg.appearance_mode == "dark"

    def test_valid_values_are_not_modified(self, config_paths: Path) -> None:
        cfg = Config()
        cfg.compressor.ratio = 5.0
        cfg.expander.threshold_db = -30.0
        cfg.save()

        loaded = Config.load()
        assert loaded.compressor.ratio == 5.0
        assert loaded.expander.threshold_db == -30.0

    def test_loaded_config_constructs_filters(self, config_paths: Path) -> None:
        """不正値を含む設定でも Compressor / Expander が例外なく構築できる。"""
        from Filtflow.compressor import Compressor
        from Filtflow.expander import Expander

        _write_config(
            config_paths,
            {
                "sample_rate": 0,
                "compressor": {"ratio": 0, "attack_ms": 0, "release_ms": 0},
                "expander": {"ratio": 0, "attack_ms": -5, "release_ms": 0, "preset": "???"},
            },
        )

        cfg = Config.load()
        Compressor(
            ratio=cfg.compressor.ratio,
            threshold=cfg.compressor.threshold_db,
            attack_ms=cfg.compressor.attack_ms,
            release_ms=cfg.compressor.release_ms,
            output_gain_db=cfg.compressor.output_gain_db,
            sample_rate=cfg.sample_rate,
        )
        Expander(
            preset=cfg.expander.preset,
            ratio=cfg.expander.ratio,
            threshold=cfg.expander.threshold_db,
            attack_ms=cfg.expander.attack_ms,
            release_ms=cfg.expander.release_ms,
            output_gain_db=cfg.expander.output_gain_db,
            detector=cfg.expander.detector,
            sample_rate=cfg.sample_rate,
        )
