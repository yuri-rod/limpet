import json
import os
from pathlib import Path
import stat

import pytest

from limpet import config


# noqa S104: o teste existe justamente para provar que estes hosts sao recusados
@pytest.mark.parametrize("host", ["", "0.0.0.0", "::"])  # noqa: S104
def test_load_rejects_all_interfaces_hosts(tmp_path, monkeypatch, host):
    monkeypatch.setenv("LIMPET_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"host": host}))
    with pytest.raises(config.ConfigError, match=str(tmp_path / "config.json")):
        config.load()


def test_ensure_token_creates_0600_and_is_stable(tmp_path):
    p = tmp_path / "token"
    t1 = config.ensure_token(p)
    t2 = config.ensure_token(p)
    assert t1 == t2 and len(t1) >= 32
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_load_reads_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMPET_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"host": "100.64.0.9", "port": 8737}))
    cfg = config.load()
    assert cfg.host == "100.64.0.9" and cfg.port == 8737
    assert len(cfg.token) >= 32


def test_ensure_token_regenerates_short_token(tmp_path):
    p = tmp_path / "token"
    p.write_text("tooshort\n")
    token = config.ensure_token(p)
    assert len(token) >= 32
    assert p.read_text().strip() == token


def test_ensure_token_regenerates_empty_token(tmp_path):
    p = tmp_path / "token"
    p.write_text("")
    token = config.ensure_token(p)
    assert len(token) >= 32
    assert p.read_text().strip() == token


def test_ensure_token_chmods_preexisting_loose_file(tmp_path):
    p = tmp_path / "token"
    p.write_text("a" * 64 + "\n")
    p.chmod(0o644)
    config.ensure_token(p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_ensure_token_leaves_no_tmp_file_behind(tmp_path):
    p = tmp_path / "token"
    config.ensure_token(p)
    assert list(tmp_path.iterdir()) == [p]


def test_ensure_token_writes_atomically(tmp_path, monkeypatch):
    p = tmp_path / "token"
    real_replace = os.replace
    seen = {}

    def spy_replace(src, dst):
        seen["dst_existed_before_replace"] = Path(dst).exists()
        seen["src_len"] = len(Path(src).read_text().strip())
        return real_replace(src, dst)

    monkeypatch.setattr(config.os, "replace", spy_replace)
    token = config.ensure_token(p)
    assert seen["dst_existed_before_replace"] is False
    assert seen["src_len"] == len(token)


@pytest.mark.parametrize(
    "body", ["{not json", "[]", '{"port": 8737}', '{"host": "100.64.0.9", "port": "eight"}']
)
def test_load_reports_a_broken_config_as_one_line(tmp_path, monkeypatch, body):
    monkeypatch.setenv("LIMPET_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(body)
    with pytest.raises(config.ConfigError, match=str(tmp_path / "config.json")):
        config.load()


def test_load_reports_a_missing_config_as_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMPET_CONFIG_DIR", str(tmp_path))
    with pytest.raises(config.ConfigError, match=str(tmp_path / "config.json")):
        config.load()
