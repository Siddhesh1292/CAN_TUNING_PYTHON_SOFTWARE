"""
Basic smoke tests for the CAN Tuner Flask app.
Run: pytest tests/ -v
"""
import sys
import types
import pytest


# ── Stub out hardware deps so tests run without a serial port ─────────────────
def _make_serial_stub():
    serial_mod = types.ModuleType("serial")
    class FakeSerial:
        def __init__(self, *a, **kw): pass
        def close(self): pass
    serial_mod.Serial = FakeSerial
    tools = types.ModuleType("serial.tools")
    list_ports_mod = types.ModuleType("serial.tools.list_ports")
    list_ports_mod.comports = lambda: []
    tools.list_ports = list_ports_mod
    serial_mod.tools = tools
    sys.modules["serial"] = serial_mod
    sys.modules["serial.tools"] = tools
    sys.modules["serial.tools.list_ports"] = list_ports_mod

def _make_can_tuner3_stub():
    mod = types.ModuleType("can_tuner3")
    mod.CAN_BITRATE = 500_000
    mod.CAN_ID_READ_RESP = 0xE1
    mod.PARAM_NAMES = {}
    mod.READ_COMMAND = 0x01
    mod.SERIAL_BAUDRATE = 2_000_000
    mod.WRITE_COMMAND = 0x02
    mod.ZERO_ANGLE_ROW = 3
    mod.read_matching_response = lambda *a, **kw: None
    mod.read_zero_angle_frame = lambda *a, **kw: None
    mod.send_read_request = lambda *a, **kw: None
    mod.send_write_complete_request = lambda *a, **kw: None
    mod.send_write_request = lambda *a, **kw: None
    sys.modules["can_tuner3"] = mod

def _make_waveshare_stub():
    mod = types.ModuleType("waveshare_can")
    mod.CAN_BITRATE_CODES = {500_000: 0x06}
    class WaveshareCANA:
        def __init__(self, *a, **kw): pass
        def close(self): pass
        def send(self, *a): pass
        def receive(self, *a, **kw): return None
    mod.WaveshareCANA = WaveshareCANA
    sys.modules["waveshare_can"] = mod

_make_serial_stub()
_make_can_tuner3_stub()
_make_waveshare_stub()

import app as app_module

@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"

def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200

def test_ports_endpoint(client):
    r = client.get("/api/ports")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert isinstance(data["ports"], list)

def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    for field in ("connected", "busy", "operation", "state", "message", "values"):
        assert field in data["status"]

def test_connect_requires_port(client):
    r = client.post("/api/connect", json={})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False

def test_read_without_connection(client):
    r = client.post("/api/read")
    assert r.status_code == 400

def test_write_without_connection(client):
    r = client.post("/api/write", json={"items": [{"row": 1, "col": 1, "value": 1.0}]})
    assert r.status_code == 400

def test_export_tuning(client):
    r = client.post("/api/export-tuning", json={"values": {}})
    assert r.status_code == 200
    assert "spreadsheetml" in r.content_type

def test_import_no_file(client):
    r = client.post("/api/import-tuning")
    assert r.status_code == 400

def test_parameters_count():
    params = app_module.build_parameters()
    assert len(params) == 60
    writable = [p for p in params if p["writable"]]
    assert len(writable) == 48
