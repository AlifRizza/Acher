"""Config read/write API + interval 1-120 validation."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from acher import config as cfgmod
from acher.api import create_app
from acher.config import Config


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Redirect the config file to a temp path so tests never touch the real one.
    cfg_path = tmp_path / "config.json"
    cfgmod.save(Config(), cfg_path)
    monkeypatch.setattr(cfgmod, "DEFAULT_CONFIG_PATH", cfg_path)
    return TestClient(create_app()), cfg_path


def test_get_config(client):
    c, _ = client
    r = c.get("/api/config")
    assert r.status_code == 200
    assert r.json()["interval_minutes"] == 3


def test_put_arbitrary_interval(client):
    # The whole point: interval is now any integer 1-120, not just 1/3/5.
    c, cfg_path = client
    r = c.put("/api/config", json={"interval_minutes": 7})
    assert r.status_code == 200
    assert r.json()["interval_minutes"] == 7
    assert json.loads(cfg_path.read_text())["interval_minutes"] == 7  # persisted


@pytest.mark.parametrize("val", [1, 2, 60, 120])
def test_put_interval_bounds_ok(client, val):
    c, _ = client
    assert c.put("/api/config", json={"interval_minutes": val}).status_code == 200


@pytest.mark.parametrize("val", [0, 121, -1, 999])
def test_put_interval_out_of_range_rejected(client, val):
    c, _ = client
    assert c.put("/api/config", json={"interval_minutes": val}).status_code == 400


def test_put_idle_and_sample(client):
    c, _ = client
    r = c.put("/api/config", json={"idle_threshold_minutes": 10, "activity_sample_seconds": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["idle_threshold_minutes"] == 10
    assert body["activity_sample_seconds"] == 3


def test_put_unknown_field_ignored(client):
    c, _ = client
    r = c.put("/api/config", json={"bogus": 1, "interval_minutes": 4})
    assert r.status_code == 200
    assert "bogus" not in r.json()
    assert r.json()["interval_minutes"] == 4


def test_put_invalid_retention_rejected(client):
    c, _ = client
    assert c.put("/api/config", json={"retention_period": "forever"}).status_code == 400
