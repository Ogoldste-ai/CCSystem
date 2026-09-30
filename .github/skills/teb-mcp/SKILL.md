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

### 2b. Board connectivity (optional)

The Allegro netlist in [`data/`](data/README.md) gives `list_pins` and
`pin_net` the signal behind each pin and everything else on that net. It ships
with the skill; `TEB_NETLIST` overrides the path, and without it connectivity
is simply reported as unavailable.

**It is Rev C.** Confirm the board on the bench matches before trusting a
lookup. Lookups **by connector location** (`pin_net(pin="J8.6")`) or by net
name come straight from the netlist and are reliable. Lookups **by
`TebConnector.h` symbol** (`GPIO_B06`) are matched on name alone and are
**not verified** - see [`data/README.md`](data/README.md). Do not drive a pin
on the strength of a symbol lookup.

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
  `list_pins`, `pin_net`, `last_error`, `gpio_read`, `gpio_read_config`,
  `fpga_read`, `fpga_read_until`, and `connect` in `virtual` mode.
- **Tier 1 - needs `TEB_ALLOW_WRITE`.** `gpio_config`, `gpio_write`,
  `gpio_freeze`, `fpga_write`, `fpga_write_field`.
- **Tier 2 - needs `TEB_ALLOW_POWER`.** `fpga_reset`, and `connect` in
  `usb-local` / `usb-remote` mode because those download a bitstream.

`health()` always reports `write_enabled` and `power_enabled`, plus a `usb`
section describing whether a real board is attached to this PC and has a driver
bound (see [A USB board that Windows will not name](#a-usb-board-that-windows-will-not-name)).

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

- `health()` - config, worker state, tier gates, pin-map status, USB board and
  driver state
- `connect(mode, host, port, board, instance, bitstream_dir, fpga_reset, init_modules)`
- `disconnect()`
- `status()` - interface, board generation, FPGA size/version/build, versions
- `list_modules(max_id=64)` - modules present in the loaded bitstream
- `list_pins(group, search)` - symbolic pin names, connector locations and the
  net each pin carries
- `pin_net(pin, net, refdes)` - board connectivity from the Allegro netlist:
  what a pin is wired to, what else is on a net, or a component's whole
  pin-to-net table
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
2. `health()` - check the `usb` section says `state: ready`. If it says
   `no-driver`, the board is plugged in but unusable until the Nuvoton TEB USB
   driver is installed; no amount of retrying `connect()` will help.
3. `connect(mode="usb-local")`. The server connects first, reads the board
   generation and FPGA size, derives the bitstream filename and downloads it.
4. Continue as in Workflow A.

Verified on a TEB3: `interface: usb`, board generation 3, FPGA 360K,
composition `Dalton/1.2`, bitstream `TEB_FPGA_360K.rbf`.

## Troubleshooting

- **`no 32-bit Python found`** - install the embeddable distribution above or
  set `TEB_PYTHON32`.
- **`TEB_ConnectEx failed with code 1`** - a generic TEB communication error.
  The DLL returns this same code whether the board is absent, present but with
  no driver bound, or held by another tool, so **do not read it as "no board
  reachable"**. For USB modes the server now appends a `USB diagnosis:` line
  that says which of the three it is; `health()` reports the same under `usb`.
  For TCP modes, check the CE machine's TEB server is running on the port you
  passed.
- **USB board that "cannot be found"** - see
  [A USB board that Windows will not name](#a-usb-board-that-windows-will-not-name)
  below. Searching Device Manager for "TEB" will not find it.
- **`timed out after 60s`** - the board or link is wedged. The worker is killed
  and restarted, so the session is gone; `connect()` again. Raise
  `TEB_CALL_TIMEOUT` for legitimately slow operations.
- **`already connected`** - the session is exclusive; `disconnect()` first.
- **Board busy from another tool** - the DLL reports
  `Make sure TEB isn't being occupied by another tool`. Close the C++ harness or
  any other TEB application.

## A USB board that Windows will not name

A real TEB attached over USB does **not** announce itself as a TEB. It
enumerates under Nuvoton/Winbond's vendor ID as a *Hermon* device:

| | |
|---|---|
| Hardware IDs | `USB\VID_0416&PID_0030`, `&PID_0031`, `&PID_0032` |
| Name with no driver | `Hermon Mass Storage Device`, no device class |
| Name once the driver is bound | `TEB3 USB Driver`, class `CustomUSBDevices`, service `WinUSB` |

Two consequences:

1. **Searching by name fails.** Filtering Device Manager or `Get-PnpDevice` for
   `TEB`/`FTDI`/`Altera` matches nothing and makes an attached board look
   absent. Search by VID/PID instead:

   ```powershell
   Get-PnpDevice -PresentOnly |
     Where-Object { $_.InstanceId -like 'USB\VID_0416*' } |
     Select-Object Status,Class,FriendlyName,Problem,Service
   ```

2. **`TEB_If.dll` talks to the board through WinUSB.** It imports
   `WinUsb_Initialize` / `ReadPipe` / `WritePipe` and finds the device through
   `SetupAPI`. If no driver is bound - Windows problem **code 28**, "The drivers
   for this device are not installed" - there is no device interface to open and
   every `connect()` fails with `TEB_ConnectEx` code 1, exactly as if no board
   were plugged in.

The fix is to install the Nuvoton TEB USB driver so the device binds to the
`WinUSB` service; that requires administrator rights. `health()` reports this
state directly:

```json
"usb": {
  "state": "no-driver",
  "summary": "TEB USB device USB\\VID_0416&PID_0030\\000000000001 is present but has no working driver ..."
}
```

`state` is one of `ready`, `no-driver`, `problem`, or `absent`. The probe is
read-only, needs no privileges, and runs in the 64-bit parent process, so it
still answers when the worker or the DLL is broken. It is diagnostics only and
never blocks a connection attempt.

## Notes

- `TEB_If.h` includes `<tl_timers.h>`, which is **not** shipped with the SDK, so
  the header cannot be compiled standalone. That is why this server binds the
  DLL through ctypes by mangled symbol name rather than building a C++ shim.
- The API has 164 functions. Only session, GPIO and raw FPGA register access are
  exposed so far; SMBus, SPI, UART, signal recorder, generators, ADC/DAC, MUX
  and power supply are deliberately left for later phases.
- Power-supply control (`TEB_PS_*`) is **not** exposed. The Tier 2 gate and
  `TEB_MAX_VOLTAGE` clamp exist so it can be added without redesign.
