"""MCP server exposing the Nuvoton TEB FPGA board.

Tools are grouped into three safety tiers, because a careless call here changes
real hardware state rather than a remote database row:

* Tier 0 - read-only, always available.
* Tier 1 - state-changing, requires ``TEB_ALLOW_WRITE``.
* Tier 2 - reset / bitstream / power, requires ``TEB_ALLOW_POWER``.

``health()`` always reports which tiers are live.
"""

from __future__ import annotations

import argparse
import atexit
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .bridge import TebBridge, WorkerError
from .config import CE_MACHINES, TebConfig, resolve_host
from .netlist import CONNECTOR_EVIDENCE, BoardNets
from .pinmap import PinMap
from .usb import probe as probe_usb


class PermissionDenied(RuntimeError):
    """A tool was called without the environment gate that protects it."""


def _pin_sort_key(item):
    """Sort connector pins numerically, but tolerate BGA balls like ``AH33``."""
    pin = item[0]
    return (0, int(pin), "") if pin.isdigit() else (1, 0, pin)


def _explain_connect_failure(mode: str, exc: Exception) -> str:
    """Turn a bare ``TEB_ConnectEx failed with code 1`` into something useful.

    The DLL returns that one code whether the board is missing, has no driver
    bound, or is held by another tool. For USB modes the device state on this
    PC settles the question, so look it up and say which it is.
    """
    message = str(exc)
    if mode not in ("usb-local", "usb-remote") or "TEB_ConnectEx" not in message:
        return message

    info = probe_usb()
    if not info.get("available"):
        return message

    state = info.get("state")
    if state == "ready":
        detail = (
            "%s The board is attached and its driver is fine, so the most "
            "likely cause is that another tool holds the board - close the C++ "
            "test harness or any other TEB application and try again."
            % info.get("summary", "")
        )
    elif state == "absent" and mode == "usb-remote":
        # The board lives on the other PC, so local absence proves nothing.
        return message
    else:
        detail = info.get("summary", "")

    return "%s\n\nUSB diagnosis: %s" % (message, detail.strip())


def build_server() -> FastMCP:
    config = TebConfig.from_env()
    bridge = TebBridge(config)
    pins = PinMap()
    nets = BoardNets()
    atexit.register(bridge.stop)

    server = FastMCP("teb")

    def require_write() -> None:
        if not config.allow_write:
            raise PermissionDenied(
                "This tool changes board state and is disabled. Set "
                "TEB_ALLOW_WRITE=1 in the client environment and restart to "
                "enable it."
            )

    def require_power() -> None:
        if not config.allow_power:
            raise PermissionDenied(
                "This tool resets hardware or programs the FPGA and is "
                "disabled. Set TEB_ALLOW_POWER=1 in the client environment and "
                "restart to enable it."
            )

    # -- session / meta ----------------------------------------------------

    @server.tool()
    def health() -> dict[str, Any]:
        """Report server configuration, worker state, and which tiers are enabled.

        Safe to call at any time; it never touches the board. Use it first when
        something is not working - it distinguishes a missing 32-bit Python or
        DLL from an actual connection problem, and reports whether a real TEB
        board is attached to this PC and has a driver bound to it.
        """
        result: dict[str, Any] = {
            "server": "teb",
            "config": config.describe(),
            "pin_map": {
                "available": pins.data.get("available"),
                "source": pins.data.get("source"),
                "count": pins.data.get("count"),
            },
            "netlist": {
                "available": nets.data.get("available"),
                "source": nets.data.get("source"),
                "count": nets.data.get("count"),
            },
            "usb": probe_usb(),
            "ce_machines": CE_MACHINES,
        }
        try:
            result["worker"] = bridge.call("ping", timeout=30)
        except WorkerError as exc:
            result["worker"] = {"alive": False, "error": str(exc)}
        return result

    @server.tool()
    def connect(
        mode: str = "",
        host: str = "",
        port: int = 0,
        board: str = "",
        instance: int = -1,
        bitstream_dir: str = "",
        fpga_reset: bool = True,
        init_modules: bool = True,
    ) -> dict[str, Any]:
        """Open a session with a TEB board. Every empty argument falls back to config.

        Modes:

        * ``virtual`` - emulated TEB on a Veloce CE machine over TCP/IP. Needs
          `host` and `port`; never downloads a bitstream.
        * ``usb-local`` - real board on this PC. Needs `bitstream_dir`.
        * ``usb-remote`` - real board on another PC, reached over TCP/IP. Needs
          `host`, `port` and `bitstream_dir`.

        `host` accepts a CE machine alias (``cm1``..``cm6``) or a literal IP.
        There is no default port - it is chosen per run, matching the
        ``-tebServerPort`` argument the C++ harness requires.

        The session is exclusive: while it is open the board is unavailable to
        other tools, so call `disconnect` when finished.
        """
        chosen_mode = (mode or config.mode).strip().lower()
        chosen_host = resolve_host(host) or config.host
        chosen_port = port or config.port
        chosen_dir = bitstream_dir or config.bitstream_dir
        chosen_board = (board or config.board).strip().lower() or None
        chosen_instance = config.instance if instance < 0 else instance

        if chosen_mode != "virtual":
            require_power()

        # A USB-local board has no network endpoint; passing the configured
        # host through would only mislabel the session.
        if chosen_mode == "usb-local":
            chosen_host = ""
            chosen_port = 0

        try:
            return bridge.call(
                "connect",
                timeout=config.connect_timeout,
                mode=chosen_mode,
                host=chosen_host or None,
                port=chosen_port or None,
                board=chosen_board,
                instance=chosen_instance,
                bitstream_dir=chosen_dir or None,
                fpga_reset=fpga_reset,
                init_modules=init_modules,
            )
        except WorkerError as exc:
            raise WorkerError(_explain_connect_failure(chosen_mode, exc)) from exc

    @server.tool()
    def disconnect() -> dict[str, Any]:
        """Close the board session and release the board for other tools."""
        return bridge.call("disconnect")

    @server.tool()
    def status() -> dict[str, Any]:
        """Report connection state, interface, board generation and versions.

        Includes DLL/firmware versions, FPGA size, FPGA version and build
        timestamp once connected.
        """
        return bridge.call("status")

    @server.tool()
    def list_modules(max_id: int = 64) -> dict[str, Any]:
        """List the FPGA modules present in the loaded bitstream.

        Each entry gives the module id, name, channel count and bus count.
        Useful for discovering what the current FPGA image actually supports.
        """
        return bridge.call("list_modules", max_id=max_id)

    @server.tool()
    def last_error() -> dict[str, Any]:
        """Return the TEB library's most recent error string."""
        return bridge.call("last_error")

    @server.tool()
    def list_pins(group: str = "", search: str = "") -> dict[str, Any]:
        """Look up symbolic pin names, connector locations and board nets.

        Filter by `group` (``GPIO``, ``ADC``, ``DA``, ``PLL``) or by a substring
        `search`. Any name returned here can be passed to the GPIO tools instead
        of a raw number.

        When the board netlist is present each pin also carries `net` (the
        signal name), `connector` (refdes and pin, e.g. ``J7`` pin 5) and
        `endpoints` (the other components on that net). Pins with no `net` are
        not routed on this board revision - see `pin_net` for detail.
        """
        data = pins.data
        if not data.get("available"):
            return {
                "available": False,
                "source": data.get("source"),
                "note": "TebConnector.h not found; use numeric pins",
                "pins": [],
            }

        selected = list((data.get("pins") or {}).values())
        if group:
            key = group.strip().upper().rstrip("_")
            selected = [p for p in selected if p.get("group", "").upper() == key]
        if search:
            needle = search.strip().lower()
            selected = [p for p in selected if needle in p["name"].lower()]

        selected.sort(key=lambda p: (p.get("group", ""), p["value"]))

        if nets.available:
            enriched = []
            for pin in selected:
                found = nets.for_symbol(pin["name"])
                if found:
                    pin = dict(pin, net=found["net"], endpoints=found["endpoints"])
                    if found.get("connector"):
                        pin["connector"] = found["connector"]
                    pin["net_match"] = "by-name-only, UNVERIFIED"
                enriched.append(pin)
            selected = enriched

        return {
            "available": True,
            "source": data.get("source"),
            "netlist": nets.data.get("source") if nets.available else None,
            "count": len(selected),
            "pins": selected,
        }

    @server.tool()
    def pin_net(pin: str = "", net: str = "", refdes: str = "") -> dict[str, Any]:
        """Trace board connectivity from the Allegro netlist.

        Give exactly one of:

        * `pin` - a symbolic name (``GPIO_A5``, ``ADC7``, ``DA3``) or a
          connector location (``J7.5``). Returns the net and everything else on
          it, which is what tells you where to probe.
        * `net` - a signal name (``ANALOG_INPUTS7``). Returns every pin on it.
        * `refdes` - a component (``J7``, ``U60``). Returns its pin-to-net table.

        The connector mapping was derived from the netlist and verified, not
        assumed. A symbol with no net is reported as unfound, with `evidence`
        explaining why, rather than guessed - a wrong pin here means probing or
        driving the wrong physical one. J13 and J21 have no symbolic names in
        the header and are reachable only as ``J13.4``-style locations.
        """
        if not nets.available:
            return {
                "available": False,
                "source": nets.data.get("source"),
                "note": "netlist not found; connectivity is unavailable",
            }

        given = [name for name, value in
                 (("pin", pin), ("net", net), ("refdes", refdes)) if value.strip()]
        if len(given) != 1:
            raise ValueError("pass exactly one of pin, net or refdes")

        base = {"available": True, "source": nets.data.get("source")}

        if refdes:
            table = (nets.data.get("refdes") or {}).get(refdes.strip().upper())
            if table is None:
                return dict(base, refdes=refdes, found=False,
                            note="no such component in the netlist")
            return dict(base, refdes=refdes.strip().upper(), found=True,
                        device=nets.device(refdes),
                        pin_count=len(table),
                        pins=[{"pin": k, "net": v} for k, v in
                              sorted(table.items(), key=_pin_sort_key)])

        if net:
            found = nets.net(net.strip())
            if not found:
                return dict(base, net=net, found=False,
                            note="no such net in the netlist")
            return dict(base, found=True, **found)

        text = pin.strip()
        if "." in text:
            part, _, number = text.rpartition(".")
            name = nets.for_pin(part, number)
            if not name:
                return dict(base, pin=text, found=False,
                            note="that connector pin carries no net")
            return dict(base, pin=text, found=True, **nets.net(name))

        found = nets.for_symbol(text)
        if not found:
            return dict(
                base, pin=text, found=False,
                note=("no net for this symbol on %s - it is not routed on this "
                      "board revision, or its connector is not established"
                      % os.path.basename(nets.data.get("source") or "")),
                evidence=CONNECTOR_EVIDENCE,
            )
        return dict(
            base, pin=text, found=True,
            warning=("This match is by NAME ONLY and is not verified. "
                     "TebConnector.h symbol %s was matched to a net of the "
                     "same spelling; that join is unproven and known to be "
                     "doubtful. Do not drive a pin on the strength of it - "
                     "look it up by connector location instead." % text),
            evidence=CONNECTOR_EVIDENCE,
            **found)

    # -- GPIO --------------------------------------------------------------

    @server.tool()
    def gpio_read(pin: str) -> dict[str, Any]:
        """Read the level of a GPIO. Accepts ``101`` or ``GPIO_101``. Tier 0."""
        return bridge.call("gpio_read", pin=pins.resolve(pin))

    @server.tool()
    def gpio_read_config(pin: str) -> dict[str, Any]:
        """Read a GPIO's configured direction and level. Tier 0."""
        return bridge.call("gpio_read_config", pin=pins.resolve(pin))

    @server.tool()
    def gpio_config(pin: str, direction: str) -> dict[str, Any]:
        """Set a GPIO's direction, ``in`` or ``out``. Requires TEB_ALLOW_WRITE.

        Note the ordering used by the production harness: drive the output level
        first with `gpio_write`, then switch the direction to ``out``. That
        avoids a glitch on the line.
        """
        require_write()
        return bridge.call(
            "gpio_config", pin=pins.resolve(pin), direction=direction.strip().lower()
        )

    @server.tool()
    def gpio_write(pin: str, level: str) -> dict[str, Any]:
        """Drive a GPIO ``low``, ``high`` or ``tristate``. Requires TEB_ALLOW_WRITE."""
        require_write()
        return bridge.call(
            "gpio_write", pin=pins.resolve(pin), level=level.strip().lower()
        )

    @server.tool()
    def gpio_freeze(mode: str = "none") -> dict[str, Any]:
        """Freeze GPIO ``in``, ``out``, ``dir``, ``all``, or ``none`` to release.

        Requires TEB_ALLOW_WRITE.
        """
        require_write()
        return bridge.call("gpio_freeze", mode=mode.strip().lower())

    # -- raw FPGA registers ------------------------------------------------

    @server.tool()
    def fpga_read(address: int, width: int = 16) -> dict[str, Any]:
        """Read an FPGA register, 16- or 32-bit. Tier 0."""
        return bridge.call("fpga_read", address=address, width=width)

    @server.tool()
    def fpga_read_until(
        address: int,
        expected: int,
        operator: str = "==",
        mask: int = 0xFFFF,
        timeout_us: int = 1000000,
    ) -> dict[str, Any]:
        """Poll an FPGA register until it matches, or the timeout expires. Tier 0.

        `timeout_us` is enforced inside the DLL, so keep it well below the
        server's own call timeout or the worker will be restarted first.
        """
        return bridge.call(
            "fpga_read_until",
            address=address,
            expected=expected,
            operator=operator,
            mask=mask,
            timeout_us=timeout_us,
        )

    @server.tool()
    def fpga_write(address: int, data: int, width: int = 16) -> dict[str, Any]:
        """Write an FPGA register, 16- or 32-bit. Requires TEB_ALLOW_WRITE."""
        require_write()
        return bridge.call("fpga_write", address=address, data=data, width=width)

    @server.tool()
    def fpga_write_field(
        address: int, start_bit: int, num_bits: int, data: int
    ) -> dict[str, Any]:
        """Write a bitfield within an FPGA register. Requires TEB_ALLOW_WRITE."""
        require_write()
        return bridge.call(
            "fpga_write_field",
            address=address,
            start_bit=start_bit,
            num_bits=num_bits,
            data=data,
        )

    @server.tool()
    def fpga_reset(init_modules: bool = True) -> dict[str, Any]:
        """Reset the FPGA, affecting every module. Requires TEB_ALLOW_POWER."""
        require_power()
        return bridge.call("fpga_reset", init_modules=init_modules)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="TEB MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--path", default="/mcp")
    args = parser.parse_args()

    server = build_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.settings.host = args.host
        server.settings.port = args.port
        server.settings.streamable_http_path = args.path
        server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
