# ABOUTME: Guards the shipped example config: it must validate once its env
# ABOUTME: vars are set and its checkout path points at a real repo.
from pathlib import Path

import yaml

from tedsbot.config import load_config

EXAMPLE = Path(__file__).resolve().parents[2] / "tedsbot.example.yaml"


def test_example_config_validates(tmp_path: Path, checkout: Path, env_tokens: None, monkeypatch) -> None:
    monkeypatch.setenv("GRAFANA_SERVICE_ACCOUNT_TOKEN", "g")
    data = yaml.safe_load(EXAMPLE.read_text())
    data["repo"]["path"] = str(checkout)
    p = tmp_path / "tedsbot.yaml"
    p.write_text(yaml.safe_dump(data))
    cfg = load_config(p)
    assert cfg.tickets.project == "APP" and cfg.errors.org == "example-org"
    assert "example" in cfg.tickets.url
