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
from teb_mcp import netlist as netlist_mod  # noqa: E402
from teb_mcp import usb as usb_mod  # noqa: E402
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
    "TEB_NETLIST",
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


@pytest.mark.anyio
async def test_health_reports_usb_state(monkeypatch):
    monkeypatch.setattr(
        server_mod,
        "probe_usb",
        lambda: {"available": True, "state": "no-driver", "summary": "no driver"},
    )
    srv, _ = build(monkeypatch)
    payload = (await call_tool(srv, "health"))[1]
    assert payload["usb"]["state"] == "no-driver"


# --------------------------------------------------------------------------
# USB probe
#
# TEB_ConnectEx reports code 1 both for "no board" and for "board present but
# no driver bound", so these verdicts are what makes the difference visible.
# --------------------------------------------------------------------------


def fake_devices(monkeypatch, devices):
    """Replace the cfgmgr32 layer so the verdict logic can be tested anywhere."""
    monkeypatch.setattr(
        usb_mod, "_registry_instances", lambda hwid: [d["instance_id"] for d in devices if d["instance_id"].startswith(hwid)]
    )
    monkeypatch.setattr(usb_mod, "_probe_instance", lambda _cfg, iid: next(d for d in devices if d["instance_id"] == iid))
    monkeypatch.setattr(usb_mod.ctypes, "WinDLL", lambda name: object(), raising=False)
    monkeypatch.setattr(usb_mod.sys, "platform", "win32")


def device(instance="USB\\VID_0416&PID_0030\\000000000001", **overrides):
    base = {
        "instance_id": instance,
        "present": True,
        "friendly_name": "TEB3 USB Driver",
        "location": "Port_#0004.Hub_#0006",
        "service": "WinUSB",
        "driver_bound": True,
        "problem_code": 0,
        "problem_text": None,
    }
    base.update(overrides)
    return base


def test_usb_probe_reports_a_ready_board(monkeypatch):
    fake_devices(monkeypatch, [device()])
    result = usb_mod.probe()
    assert result["available"] is True
    assert result["state"] == "ready"
    assert "WinUSB" in result["summary"]


def test_usb_probe_flags_a_board_with_no_driver(monkeypatch):
    # The exact failure seen in the field: enumerated as a Hermon device with
    # problem code 28 and no driver service.
    fake_devices(
        monkeypatch,
        [
            device(
                friendly_name="Hermon Mass Storage Device",
                service=None,
                driver_bound=False,
                problem_code=28,
                problem_text=usb_mod.PROBLEM_TEXT[28],
            )
        ],
    )
    result = usb_mod.probe()
    assert result["state"] == "no-driver"
    assert "drivers for this device are not installed" in result["summary"]
    assert "administrator" in result["summary"]


def test_usb_probe_reports_an_absent_board(monkeypatch):
    fake_devices(monkeypatch, [])
    result = usb_mod.probe()
    assert result["state"] == "absent"
    assert result["devices"] == []


def test_usb_probe_reports_other_problem_codes(monkeypatch):
    fake_devices(
        monkeypatch,
        [device(problem_code=22, problem_text=usb_mod.PROBLEM_TEXT[22])],
    )
    result = usb_mod.probe()
    assert result["state"] == "problem"
    assert "disabled" in result["summary"]


def test_usb_probe_never_raises(monkeypatch):
    # Diagnostics must degrade, never break the caller.
    def boom(_name):
        raise OSError("cfgmgr32 unavailable")

    monkeypatch.setattr(usb_mod.sys, "platform", "win32")
    monkeypatch.setattr(usb_mod.ctypes, "WinDLL", boom, raising=False)
    result = usb_mod.probe()
    assert result["available"] is False
    assert "cfgmgr32 unavailable" in result["error"]


def test_usb_probe_is_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(usb_mod.sys, "platform", "linux")
    result = usb_mod.probe()
    assert result["available"] is False
    assert result["devices"] == []


# --------------------------------------------------------------------------
# connect() failure diagnosis
# --------------------------------------------------------------------------


def test_connect_failure_explains_a_missing_driver(monkeypatch):
    monkeypatch.setattr(
        server_mod,
        "probe_usb",
        lambda: {"available": True, "state": "no-driver", "summary": "no driver bound"},
    )
    message = server_mod._explain_connect_failure(
        "usb-local", WorkerError("TEB_ConnectEx failed with code 1")
    )
    assert "USB diagnosis" in message
    assert "no driver bound" in message


def test_connect_failure_blames_another_tool_when_the_board_is_healthy(monkeypatch):
    monkeypatch.setattr(
        server_mod,
        "probe_usb",
        lambda: {"available": True, "state": "ready", "summary": "board is fine."},
    )
    message = server_mod._explain_connect_failure(
        "usb-local", WorkerError("TEB_ConnectEx failed with code 1")
    )
    assert "another tool holds the board" in message


def test_connect_failure_is_untouched_for_virtual_mode(monkeypatch):
    def fail():  # pragma: no cover - must never be reached
        raise AssertionError("virtual mode must not probe local USB")

    monkeypatch.setattr(server_mod, "probe_usb", fail)
    message = server_mod._explain_connect_failure(
        "virtual", WorkerError("TEB_ConnectEx failed with code 1")
    )
    assert message == "TEB_ConnectEx failed with code 1"


def test_connect_failure_ignores_local_usb_state_for_a_remote_board(monkeypatch):
    # With usb-remote the board hangs off the other PC, so its absence here
    # proves nothing and must not be reported as a diagnosis.
    monkeypatch.setattr(
        server_mod,
        "probe_usb",
        lambda: {"available": True, "state": "absent", "summary": "nothing here"},
    )
    message = server_mod._explain_connect_failure(
        "usb-remote", WorkerError("TEB_ConnectEx failed with code 1")
    )
    assert message == "TEB_ConnectEx failed with code 1"


@pytest.fixture
def anyio_backend():
    return "asyncio"


# -- netlist ---------------------------------------------------------------


NETLIST_FIXTURE = """(NETLIST)
(GENERATED BY: ALLEGRO 23.1 S002 (4170606))
$PACKAGES
400673 ! 'QSS-025-01-F-D-A_25X2_400673_QS' ! 'QSS-025-01-F-D-A' ; J7 J8 ,
        J12
$NETS
GPIO_A5 ; J7.5 U60.C3
GPIO_A6 ; J7.6 U60.D3
'QUOTED_NET' ; J8.2 U60.E3
AGND ; C1.2 C2.2 C3.2 ,
        C4.2 U39.5 ,
        U39.6
ANALOG_INPUTS7 ; C645.1 J22.15 U39.8
ANALOG_OUTPUTS3 ; J22.8 U43.7
$PACKAGES
$A_PROPERTIES
REUSE_ID '23'; 'C444'
$NETS
$A_PROPERTIES
NET_PROP 'X'; GPIO_A5
$END
"""


@pytest.fixture
def fake_netlist(tmp_path):
    path = tmp_path / "netlist.txt"
    path.write_text(NETLIST_FIXTURE, encoding="latin-1")
    return str(path)


def test_netlist_joins_continuation_lines(fake_netlist):
    data = netlist_mod.load_netlist(fake_netlist)
    # Three continuation lines must collapse into one six-pin net, not three
    # truncated ones.
    assert data["nets"]["AGND"] == [
        "C1.2", "C2.2", "C3.2", "C4.2", "U39.5", "U39.6",
    ]


def test_netlist_strips_quotes_from_names(fake_netlist):
    data = netlist_mod.load_netlist(fake_netlist)
    assert "QUOTED_NET" in data["nets"]
    assert "'QUOTED_NET'" not in data["nets"]


def test_netlist_stops_at_the_next_section(fake_netlist):
    # Allegro repeats every marker later for $A_PROPERTIES. Reading past the
    # first $NETS would swallow property records as if they were nets.
    data = netlist_mod.load_netlist(fake_netlist)
    assert data["count"] == 6
    assert not any(name.startswith("NET_PROP") for name in data["nets"])
    assert not any(name.startswith("REUSE_ID") for name in data["nets"])


def test_netlist_indexes_pins_by_refdes(fake_netlist):
    nets = netlist_mod.BoardNets(fake_netlist)
    assert nets.for_pin("J7", 5) == "GPIO_A5"
    assert nets.for_pin("j7", "6") == "GPIO_A6"
    assert nets.for_pin("J7", 99) is None


def test_netlist_accepts_either_zero_padding(fake_netlist):
    # TebConnector.h writes GPIO_A05; the netlist writes GPIO_A5. A lookup has
    # to succeed from either spelling or the join silently returns nothing.
    nets = netlist_mod.BoardNets(fake_netlist)
    for spelling in ("GPIO_A5", "GPIO_A05", "_TEB_GPIO_A05"):
        found = nets.for_symbol(spelling)
        assert found is not None, spelling
        assert found["connector"] == {"refdes": "J7", "pin": "5"}


def test_netlist_maps_adc_and_dac_through_analog_nets(fake_netlist):
    nets = netlist_mod.BoardNets(fake_netlist)
    assert nets.for_symbol("ADC7")["net"] == "ANALOG_INPUTS7"
    assert nets.for_symbol("ADC7")["connector"] == {"refdes": "J22", "pin": "15"}
    assert nets.for_symbol("DA3")["net"] == "ANALOG_OUTPUTS3"


def test_netlist_excludes_the_connector_from_endpoints(fake_netlist):
    # The useful part of a lookup is where else the net goes, so the connector
    # pin the caller already named must not be echoed back as an endpoint.
    nets = netlist_mod.BoardNets(fake_netlist)
    assert nets.for_symbol("GPIO_A5")["endpoints"] == ["U60.C3"]


def test_netlist_reports_unrouted_symbols_as_missing(fake_netlist):
    # GPIO_F* and GPIO_101 have no verified connector. Returning None is the
    # point: a guess here means probing the wrong physical pin.
    nets = netlist_mod.BoardNets(fake_netlist)
    assert nets.for_symbol("GPIO_F1") is None
    assert nets.for_symbol("GPIO_101") is None


def test_netlist_degrades_to_empty_when_absent(tmp_path):
    nets = netlist_mod.BoardNets(str(tmp_path / "nope.txt"))
    assert nets.available is False
    assert nets.data["nets"] == {}
    assert nets.for_symbol("GPIO_A5") is None
    assert nets.for_pin("J7", 5) is None


def test_shipped_netlist_maps_every_family_to_one_connector():
    # The guard on the real derivation: if a future netlist put a family on two
    # refdes, the mapping would be ambiguous and must not be trusted.
    nets = netlist_mod.BoardNets()
    if not nets.available:
        pytest.skip("shipped netlist not present")
    seen = {}
    for entry in nets.data["connectors"].values():
        if entry["connector"]:
            seen.setdefault(entry["family"], set()).add(
                entry["connector"]["refdes"]
            )
    for family, refdes in seen.items():
        assert len(refdes) == 1, (family, refdes)
        assert netlist_mod.CONNECTOR_REFDES[family] in refdes


def test_netlist_names_devices_from_packages(fake_netlist):
    nets = netlist_mod.BoardNets(fake_netlist)
    # The $PACKAGES record spans a continuation line; J12 is on the second.
    assert nets.device("J7") == "QSS-025-01-F-D-A"
    assert nets.device("J12") == "QSS-025-01-F-D-A"
    assert nets.device("U999") is None


def test_netlist_device_lookup_survives_a_missing_file(tmp_path):
    assert netlist_mod.BoardNets(str(tmp_path / "nope.txt")).device("J7") is None


def test_pinmap_accepts_the_netlist_spelling_of_a_padded_name():
    # TebConnector.h writes GPIO_B06 but pin_net and list_pins hand back
    # GPIO_B6, so both spellings must reach the same pin or the server rejects
    # a name it just produced.
    pins = PinMap()
    if not pins.data.get("available"):
        pytest.skip("TebConnector.h not installed")
    assert pins.resolve("GPIO_B6") == pins.resolve("GPIO_B06")
    assert pins.resolve("_TEB_GPIO_B6") == pins.resolve("GPIO_B06")


def test_pinmap_still_rejects_an_unpadded_name_that_does_not_exist():
    pins = PinMap()
    if not pins.data.get("available"):
        pytest.skip("TebConnector.h not installed")
    with pytest.raises(ValueError):
        pins.resolve("GPIO_Z9")
