"""Unit tests for the TEB MCP server.

These run with no hardware and no 32-bit Python: the bridge is replaced by a
fake that records calls. That keeps tier gating, pin resolution, mode handling
and config parsing under test in CI, where a TEB board will never exist.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from teb_mcp import server as server_mod  # noqa: E402
from teb_mcp.bridge import WorkerError  # noqa: E402
from teb_mcp.config import TebConfig, resolve_host  # noqa: E402
from teb_mcp.pinmap import PinMap  # noqa: E402

TEB_ENV_VARS = [
    "TEB_MODE",
    "TEB_HOST",
    "TEB_PORT",
    "TEB_BOARD",
    "TEB_INSTANCE",
    "TEB_BITSTREAM_DIR",
    "TEB_DLL_PATH",
    "TEB_PYTHON32",
    "TEB_WORKER_LOG",
    "TEB_ALLOW_WRITE",
    "TEB_ALLOW_POWER",
    "TEB_MAX_VOLTAGE",
    "TEB_CONNECTOR_HEADER",
    "TEB_TESTROOT",
]


class FakeBridge:
    """Stands in for the 32-bit worker; records every call."""

    def __init__(self, config, result=None):
        self.config = config
        self.calls = []
        self.result = result if result is not None else {"ok": True}

    def call(self, command, timeout=None, **args):
        self.calls.append((command, args))
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result, command=command)

    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in TEB_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Keep a missing 32-bit Python from turning into a warning we do not care
    # about in most tests.
    monkeypatch.setenv("TEB_PYTHON32", sys.executable)


def build(monkeypatch, **env):
    """Build a server with a fake bridge and return (server, bridge)."""
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    created = {}

    def factory(config):
        bridge = FakeBridge(config)
        created["bridge"] = bridge
        return bridge

    monkeypatch.setattr(server_mod, "TebBridge", factory)
    srv = server_mod.build_server()
    return srv, created["bridge"]


async def call_tool(srv, name, **args):
    return await srv.call_tool(name, args)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_ce_machine_aliases_resolve():
    assert resolve_host("cm1") == "134.86.33.137"
    assert resolve_host("CM6") == "134.86.33.142"


def test_literal_host_passes_through():
    # The CE addresses may change, so a literal IP must always work.
    assert resolve_host("10.0.0.5") == "10.0.0.5"


def test_config_defaults_are_locked_down(monkeypatch):
    config = TebConfig.from_env()
    assert config.mode == "virtual"
    assert config.allow_write is False
    assert config.allow_power is False


def test_missing_port_warns_for_tcp_modes(monkeypatch):
    monkeypatch.setenv("TEB_MODE", "virtual")
    config = TebConfig.from_env()
    assert any("TEB_PORT" in w for w in config.warnings)


def test_port_not_required_for_usb_local(monkeypatch):
    monkeypatch.setenv("TEB_MODE", "usb-local")
    config = TebConfig.from_env()
    assert not any("TEB_PORT" in w for w in config.warnings)


def test_invalid_mode_falls_back(monkeypatch):
    monkeypatch.setenv("TEB_MODE", "nonsense")
    config = TebConfig.from_env()
    assert config.mode == "virtual"
    assert any("TEB_MODE" in w for w in config.warnings)


def test_flags_parse_truthy_spellings(monkeypatch):
    monkeypatch.setenv("TEB_ALLOW_WRITE", "yes")
    monkeypatch.setenv("TEB_ALLOW_POWER", "TRUE")
    config = TebConfig.from_env()
    assert config.allow_write is True
    assert config.allow_power is True


def test_port_accepts_hex(monkeypatch):
    monkeypatch.setenv("TEB_PORT", "0x1F90")
    assert TebConfig.from_env().port == 8080


def test_path_vars_are_expanded(monkeypatch, tmp_path):
    # MCP client configs commonly embed %LOCALAPPDATA%, and not every client
    # expands it before spawning the server.
    monkeypatch.setenv("TEB_TESTROOT", str(tmp_path))
    monkeypatch.setenv("TEB_BITSTREAM_DIR", "%TEB_TESTROOT%\\fpga")
    config = TebConfig.from_env()
    assert "%" not in config.bitstream_dir
    assert config.bitstream_dir == os.path.join(str(tmp_path), "fpga")


def test_python32_var_is_expanded(monkeypatch, tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("TEB_TESTROOT", str(tmp_path))
    monkeypatch.setenv("TEB_PYTHON32", "%TEB_TESTROOT%\\python.exe")
    assert TebConfig.from_env().python32 == str(exe)


# --------------------------------------------------------------------------
# Safety tiers
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_writes_blocked_by_default(monkeypatch):
    srv, bridge = build(monkeypatch)
    with pytest.raises(Exception) as excinfo:
        await call_tool(srv, "gpio_write", pin="101", level="high")
    assert "TEB_ALLOW_WRITE" in str(excinfo.value)
    assert bridge.calls == []


@pytest.mark.anyio
async def test_writes_allowed_when_enabled(monkeypatch):
    srv, bridge = build(monkeypatch, TEB_ALLOW_WRITE="1")
    await call_tool(srv, "gpio_write", pin="101", level="high")
    assert bridge.calls[0][0] == "gpio_write"
    assert bridge.calls[0][1] == {"pin": 101, "level": "high"}


@pytest.mark.anyio
async def test_reads_never_need_a_gate(monkeypatch):
    srv, bridge = build(monkeypatch)
    await call_tool(srv, "gpio_read", pin="101")
    await call_tool(srv, "fpga_read", address=0x10)
    assert [c[0] for c in bridge.calls] == ["gpio_read", "fpga_read"]


@pytest.mark.anyio
async def test_fpga_reset_needs_power_gate(monkeypatch):
    srv, bridge = build(monkeypatch, TEB_ALLOW_WRITE="1")
    with pytest.raises(Exception) as excinfo:
        await call_tool(srv, "fpga_reset")
    assert "TEB_ALLOW_POWER" in str(excinfo.value)
    assert bridge.calls == []


@pytest.mark.anyio
async def test_write_gate_unlocks_tier1_but_not_tier2(monkeypatch):
    # TEB_ALLOW_WRITE must enable register writes without implying the
    # destructive tier.
    srv, bridge = build(monkeypatch, TEB_ALLOW_WRITE="1")

    await call_tool(
        srv, "fpga_write_field", address=1, start_bit=0, num_bits=1, data=1
    )
    assert bridge.calls[-1][0] == "fpga_write_field"

    with pytest.raises(Exception) as excinfo:
        await call_tool(srv, "fpga_reset")
    assert "TEB_ALLOW_POWER" in str(excinfo.value)


# --------------------------------------------------------------------------
# connect()
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_connect_uses_config_defaults(monkeypatch):
    srv, bridge = build(
        monkeypatch, TEB_MODE="virtual", TEB_HOST="cm3", TEB_PORT="5000"
    )
    await call_tool(srv, "connect")
    command, args = bridge.calls[0]
    assert command == "connect"
    assert args["mode"] == "virtual"
    assert args["host"] == "134.86.33.130"
    assert args["port"] == 5000


@pytest.mark.anyio
async def test_connect_arguments_override_config(monkeypatch):
    srv, bridge = build(monkeypatch, TEB_HOST="cm1", TEB_PORT="5000")
    await call_tool(srv, "connect", host="cm5", port=6001)
    _, args = bridge.calls[0]
    assert args["host"] == "134.86.33.141"
    assert args["port"] == 6001


@pytest.mark.anyio
async def test_virtual_connect_needs_no_power_gate(monkeypatch):
    # Emulated boards cannot be physically damaged, so virtual stays ungated.
    srv, bridge = build(monkeypatch, TEB_HOST="cm1", TEB_PORT="5000")
    await call_tool(srv, "connect", mode="virtual")
    assert bridge.calls[0][0] == "connect"


@pytest.mark.anyio
async def test_real_board_connect_needs_power_gate(monkeypatch):
    # usb modes download a bitstream, which is a destructive operation.
    srv, bridge = build(monkeypatch, TEB_BITSTREAM_DIR=r"C:\fpga")
    with pytest.raises(Exception) as excinfo:
        await call_tool(srv, "connect", mode="usb-local")
    assert "TEB_ALLOW_POWER" in str(excinfo.value)
    assert bridge.calls == []


@pytest.mark.anyio
async def test_real_board_connect_allowed_when_gated(monkeypatch):
    srv, bridge = build(
        monkeypatch, TEB_ALLOW_POWER="1", TEB_BITSTREAM_DIR=r"C:\fpga"
    )
    await call_tool(srv, "connect", mode="usb-local")
    _, args = bridge.calls[0]
    assert args["mode"] == "usb-local"
    assert args["bitstream_dir"] == r"C:\fpga"


# --------------------------------------------------------------------------
# Pin map
# --------------------------------------------------------------------------


@pytest.fixture
def fake_header(tmp_path):
    header = tmp_path / "TebConnector.h"
    header.write_text(
        "#define _TEB_ADC0           0 // ADC0         Connector-6 Pin-01\n"
        "#define _TEB_GPIO_101     101 // GPIO_101     Connector-1 Pin-01\n"
        "#define _TEB_GPIO_102     102 // GPIO_102     Connector-1 Pin-02 "
        "connected also to _TEB_PLL_0_CLK_0\n",
        encoding="latin-1",
    )
    return str(header)


def test_pinmap_parses_connector_locations(fake_header):
    pins = PinMap(fake_header)
    entry = pins.data["pins"]["GPIO_101"]
    assert entry["value"] == 101
    assert entry["connector"] == 1
    assert entry["pin"] == 1
    assert entry["group"] == "GPIO"


def test_pinmap_keeps_extra_comment_notes(fake_header):
    assert "PLL_0_CLK_0" in PinMap(fake_header).data["pins"]["GPIO_102"]["note"]


def test_pinmap_resolves_names_and_numbers(fake_header):
    pins = PinMap(fake_header)
    assert pins.resolve("GPIO_101") == 101
    assert pins.resolve("_TEB_GPIO_101") == 101
    assert pins.resolve("101") == 101
    assert pins.resolve(101) == 101
    assert pins.resolve("0x65") == 101


def test_pinmap_distinguishes_adc0_from_pin_zero(fake_header):
    # ADC0 has value 0, which is falsy - it must still resolve.
    assert PinMap(fake_header).resolve("ADC0") == 0


def test_pinmap_rejects_unknown_name(fake_header):
    with pytest.raises(ValueError, match="unknown pin"):
        PinMap(fake_header).resolve("GPIO_999")


def test_pinmap_without_header_still_takes_numbers(tmp_path):
    pins = PinMap(str(tmp_path / "missing.h"))
    assert pins.resolve(42) == 42
    with pytest.raises(ValueError, match="TebConnector.h was not found"):
        pins.resolve("GPIO_101")


@pytest.mark.anyio
async def test_list_pins_filters_by_group(monkeypatch, fake_header):
    monkeypatch.setenv("TEB_CONNECTOR_HEADER", fake_header)
    srv, _ = build(monkeypatch)
    result = await call_tool(srv, "list_pins", group="GPIO")
    payload = result[1]
    assert payload["count"] == 2
    assert {p["name"] for p in payload["pins"]} == {"GPIO_101", "GPIO_102"}


# --------------------------------------------------------------------------
# health()
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_health_reports_tier_state(monkeypatch):
    srv, _ = build(monkeypatch, TEB_ALLOW_WRITE="1")
    payload = (await call_tool(srv, "health"))[1]
    assert payload["config"]["write_enabled"] is True
    assert payload["config"]["power_enabled"] is False


@pytest.mark.anyio
async def test_health_survives_a_dead_worker(monkeypatch):
    # health() is the tool used to diagnose a broken setup, so it must never
    # fail just because the worker cannot start.
    srv, bridge = build(monkeypatch)
    bridge.result = WorkerError("no 32-bit Python")
    payload = (await call_tool(srv, "health"))[1]
    assert payload["worker"]["alive"] is False
    assert "32-bit" in payload["worker"]["error"]


@pytest.mark.anyio
async def test_health_lists_ce_machines(monkeypatch):
    srv, _ = build(monkeypatch)
    payload = (await call_tool(srv, "health"))[1]
    assert payload["ce_machines"]["cm1"] == "134.86.33.137"


@pytest.fixture
def anyio_backend():
    return "asyncio"
