import pytest

from src.config import load_config


def test_load_config_reads_yaml(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "brand:\n  instagram: drinktoiletwine\n"
        "monitoring:\n  max_accounts: 75\n"
    )
    cfg = load_config(str(cfg_file))
    assert cfg["brand"]["instagram"] == "drinktoiletwine"
    assert cfg["monitoring"]["max_accounts"] == 75


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))
