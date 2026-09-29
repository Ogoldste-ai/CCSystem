---
name: teb-mcp
description: Drive a Nuvoton TEB (Test Environment Board) FPGA over MCP - connect to an emulated board on a Veloce CE machine or a real USB-attached board, then read and write GPIO pins and raw FPGA registers. Use when you need to inspect or control TEB hardware interactively instead of writing a C++ test harness.
---

# TEB MCP Skill

This repository ships a local TEB MCP server under
`.github\skills\teb-mcp\server`. It exposes the Nuvoton `TEB_If.dll` API as MCP
tools so an agent can drive the board directly.

Like the other servers here, it is launched over stdio by the client and
requires `pip install -e .` in the `server` directory.

## The 32-bit split, and why it exists

`TEB_If.dll` is a **32-bit** library installed in `C:\Windows\SysWOW64`. A
64-bit Python cannot load it, at all.

So the server runs as two processes:

```
Copilot CLI --stdio--> teb-mcp (64-bit, FastMCP)
                          |
                          | JSON-lines
                          v
                    teb_worker.py (32-bit, ctypes)
                          |
                          v
                    C:\Windows\SysWOW64\TEB_If.dll
```

The worker holds the board session, which is stateful (`connect` … calls …
`disconnect`), and handles one request at a time. **A board session is
exclusive** - while it is open, the normal C++ test harness cannot use that
board, so call `disconnect` when you are done.

One subtlety worth knowing when debugging: the DLL prints diagnostics such as
`TEB FATAL ERROR! TEB is not connected!` straight to stdout. The worker
redirects its real stdout to a private descriptor before loading the DLL, so
that text can never corrupt the JSON channel. Set `TEB_WORKER_LOG` to capture
it.

## Required setup

### 1. A 32-bit Python

`winget` will not install the x86 build alongside an existing 64-bit Python, so
use the embeddable distribution - the worker needs only the standard library:

```powershell
$dest = "$env:LOCALAPPDATA\teb-mcp\python32"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip" `
  -OutFile "$env:TEMP\py32.zip"
Expand-Archive "$env:TEMP\py32.zip" -DestinationPath $dest -Force
& "$dest\python.exe" -c "import struct; print(struct.calcsize('P')*8)"   # must print 32
```

That path is discovered automatically. Anywhere else, set `TEB_PYTHON32`.

### 2. The TEB SDK

`TEB_If.dll` must be present in `SysWOW64` (installed by the Nuvoton TEB
Interface package). `TebConnector.h` from the same package is optional; without
it symbolic pin names are unavailable but numeric pins still work.

### 3. Install the server

```powershell
cd C:\CCSystem\.github\skills\teb-mcp\server
pip install -e .
```

## Environment

| Variable | Meaning |
|---|---|
| `TEB_MODE` | `virtual` (default), `usb-local`, or `usb-remote` |
| `TEB_HOST` | `cm1`..`cm6` alias, or a literal IP |
| `TEB_PORT` | TEB server port. **Required** for TCP modes, no default |
| `TEB_BOARD` | `any`, `virtual`, `teb3`, `teb4`, `ceb1` |
| `TEB_INSTANCE` | board instance number, default `0` |
| `TEB_BITSTREAM_DIR` | directory holding `TEB*_FPGA_*K.rbf` / `.bin` |
| `TEB_PYTHON32` | path to the 32-bit `python.exe` |
| `TEB_DLL_PATH` | override the DLL location |
| `TEB_WORKER_LOG` | capture the DLL's stdout chatter to a file |
| `TEB_CALL_TIMEOUT` | per-call timeout in seconds, default `60` |
| `TEB_CONNECT_TIMEOUT` | connect timeout in seconds, default `300` |
| `TEB_ALLOW_WRITE` | **off by default** - enables state-changing tools |
| `TEB_ALLOW_POWER` | **off by default** - enables reset/bitstream tools |

There is deliberately no default port: in the C++ harness it is supplied per run
via `-tebServerPort` / the `TEB_PORT` key in the run `.cfg`, and it differs
between setups.

```powershell
[Environment]::SetEnvironmentVariable("TEB_ALLOW_WRITE", "1", "User")
```

## Safety tiers

A bad call here changes real hardware, not a database row, so tools are gated:

- **Tier 0 - always available.** `health`, `status`, `list_modules`,
  `list_pins`, `last_error`, `gpio_read`, `gpio_read_config`, `fpga_read`,
  `fpga_read_until`, and `connect` in `virtual` mode.
- **Tier 1 - needs `TEB_ALLOW_WRITE`.** `gpio_config`, `gpio_write`,
  `gpio_freeze`, `fpga_write`, `fpga_write_field`.
- **Tier 2 - needs `TEB_ALLOW_POWER`.** `fpga_reset`, and `connect` in
  `usb-local` / `usb-remote` mode because those download a bitstream.

`health()` always reports `write_enabled` and `power_enabled`.

## Target modes

| Mode | What it is | Needs |
|---|---|---|
| `virtual` | emulated TEB on a Veloce CE machine, over TCP/IP | `host`, `port` |
| `usb-local` | real board on this PC | `bitstream_dir` |
| `usb-remote` | real board on another PC, over TCP/IP | `host`, `port`, `bitstream_dir` |

CE machine aliases (from `BMC\Common\host\ce_veloce.h` in the work repo):

```
cm1 134.86.33.137   cm2 134.86.33.138   cm3 134.86.33.130
cm4 134.86.33.131   cm5 134.86.33.141   cm6 134.86.33.142
```

These are aliases only - `TEB_HOST` accepts a literal IP, since the addresses
are expected to change.

For real boards the bitstream **filename is derived, not given**, reproducing
`FPGA_LoadRTL` in `ValidationCommon\Boards\FPGA.cpp`: generation 4 uses
`TEB4_FPGA_<size>K.bin` via `TEB_Load`, earlier generations use
`TEB_FPGA_<size>K.rbf` or `CEB_FPGA_<size>K.rbf` via `TEB_Open`. Point
`TEB_BITSTREAM_DIR` at the containing directory.

## Available MCP tools

Session and discovery:

- `health()` - config, worker state, tier gates, pin-map status
- `connect(mode, host, port, board, instance, bitstream_dir, fpga_reset, init_modules)`
- `disconnect()`
- `status()` - interface, board generation, FPGA size/version/build, versions
- `list_modules(max_id=64)` - modules present in the loaded bitstream
- `list_pins(group, search)` - symbolic pin names and connector locations
- `last_error()`

GPIO - accepts `101` or `GPIO_101`:

- `gpio_read(pin)`, `gpio_read_config(pin)`
- `gpio_config(pin, direction)`, `gpio_write(pin, level)`, `gpio_freeze(mode)`

Raw FPGA registers:

- `fpga_read(address, width)`, `fpga_read_until(address, expected, operator, mask, timeout_us)`
- `fpga_write(address, data, width)`, `fpga_write_field(address, start_bit, num_bits, data)`
- `fpga_reset(init_modules)`

## Workflow A - poke at an emulated board on a CE machine

1. `health()` - confirm the worker is alive, `dll_loaded` is true, and note
   which tiers are enabled.
2. `connect(mode="virtual", host="cm3", port=<port>)`. The port must match the
   `-tebServerPort` the emulation run was started with.
3. `status()` - confirm `interface` is `tcpip` and check the FPGA version.
4. `list_modules()` - see what the loaded image supports.
5. `gpio_read("GPIO_101")`, `fpga_read(0x10)` to inspect state.
6. `disconnect()` when done - the session is exclusive.

## Workflow B - drive a pin

Match the ordering the production harness uses: set the level *before*
switching the pin to an output, so the line does not glitch.

1. `gpio_write(pin="GPIO_101", level="low")`
2. `gpio_config(pin="GPIO_101", direction="out")`
3. `gpio_read_config(pin="GPIO_101")` to confirm.

Both write steps need `TEB_ALLOW_WRITE=1`.

## Workflow C - a real USB board

1. Set `TEB_BITSTREAM_DIR` and `TEB_ALLOW_POWER=1`.
2. `connect(mode="usb-local")`. The server connects first, reads the board
   generation and FPGA size, derives the bitstream filename and downloads it.
3. Continue as in Workflow A.

## Troubleshooting

- **`no 32-bit Python found`** - install the embeddable distribution above or
  set `TEB_PYTHON32`.
- **`TEB_ConnectEx failed with code 1`** - TEB communication error: no board
  reachable. Check the board is attached, or that the CE machine's TEB server is
  running on the port you passed.
- **`timed out after 60s`** - the board or link is wedged. The worker is killed
  and restarted, so the session is gone; `connect()` again. Raise
  `TEB_CALL_TIMEOUT` for legitimately slow operations.
- **`already connected`** - the session is exclusive; `disconnect()` first.
- **Board busy from another tool** - the DLL reports
  `Make sure TEB isn't being occupied by another tool`. Close the C++ harness or
  any other TEB application.

## Notes

- `TEB_If.h` includes `<tl_timers.h>`, which is **not** shipped with the SDK, so
  the header cannot be compiled standalone. That is why this server binds the
  DLL through ctypes by mangled symbol name rather than building a C++ shim.
- The API has 164 functions. Only session, GPIO and raw FPGA register access are
  exposed so far; SMBus, SPI, UART, signal recorder, generators, ADC/DAC, MUX
  and power supply are deliberately left for later phases.
- Power-supply control (`TEB_PS_*`) is **not** exposed. The Tier 2 gate and
  `TEB_MAX_VOLTAGE` clamp exist so it can be added without redesign.
