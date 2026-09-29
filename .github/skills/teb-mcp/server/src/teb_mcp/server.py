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
from typing import Any

from mcp.server.fastmcp import FastMCP

from .bridge import TebBridge, WorkerError
from .config import CE_MACHINES, TebConfig, resolve_host
from .pinmap import PinMap


class PermissionDenied(RuntimeError):
    """A tool was called without the environment gate that protects it."""


def build_server() -> FastMCP:
    config = TebConfig.from_env()
    bridge = TebBridge(config)
    pins = PinMap()
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
        DLL from an actual connection problem.
        """
        result: dict[str, Any] = {
            "server": "teb",
            "config": config.describe(),
            "pin_map": {
                "available": pins.data.get("available"),
                "source": pins.data.get("source"),
                "count": pins.data.get("count"),
            },
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
        """Look up symbolic pin names and their connector locations.

        Filter by `group` (``GPIO``, ``ADC``, ``DA``, ``PLL``) or by a substring
        `search`. Any name returned here can be passed to the GPIO tools instead
        of a raw number.
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
        return {
            "available": True,
            "source": data.get("source"),
            "count": len(selected),
            "pins": selected,
        }

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
