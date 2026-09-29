# teb-mcp server

MCP server exposing the Nuvoton TEB (Test Environment Board) FPGA.

See `..\SKILL.md` for the tool reference and workflows. This file covers setup,
client wiring, manual operation and troubleshooting.

## Architecture

`TEB_If.dll` is 32-bit and lives in `C:\Windows\SysWOW64`. A 64-bit interpreter
cannot load it, so the server is split:

```
client --stdio--> teb_mcp.server   (64-bit, FastMCP)
                      |
                      | JSON-lines over a private pipe
                      v
                  teb_mcp/worker/teb_worker.py   (32-bit, ctypes)
                      |
                      v
                  TEB_If.dll
```

| File | Role |
|---|---|
| `src/teb_mcp/server.py` | FastMCP tool definitions and safety gating |
| `src/teb_mcp/bridge.py` | spawns the worker, JSON-lines RPC, timeouts, restart |
| `src/teb_mcp/config.py` | environment parsing, CE machine aliases |
| `src/teb_mcp/pinmap.py` | parses `TebConnector.h` into symbolic pin names |
| `src/teb_mcp/worker/teb_worker.py` | 32-bit session owner, command dispatch |
| `src/teb_mcp/worker/teb_api.py` | ctypes bindings to the mangled DLL exports |

The worker files must stay import-standalone. They run under a bare 32-bit
interpreter that cannot see this distribution's installed packages, so they may
not import from `teb_mcp`.

## Setup

### 1. 32-bit Python

```powershell
$dest = "$env:LOCALAPPDATA\teb-mcp\python32"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip" `
  -OutFile "$env:TEMP\py32.zip"
Expand-Archive "$env:TEMP\py32.zip" -DestinationPath $dest -Force
& "$dest\python.exe" -c "import struct; print(struct.calcsize('P')*8)"
```

Must print `32`. `winget install Python.Python.3.12 --architecture x86` does
**not** work when a 64-bit 3.12 is already installed - winget treats it as the
same package and reports "No available upgrade found".

This location is auto-discovered. Anywhere else, set `TEB_PYTHON32`.

### 2. Install

```powershell
cd C:\CCSystem\.github\skills\teb-mcp\server
pip install -e ".[test]"
```

### 3. Verify without hardware

```powershell
python -m pytest -q
```

28 tests, none of which need a board or a 32-bit Python.

To check the real DLL binding:

```powershell
& "$env:LOCALAPPDATA\teb-mcp\python32\python.exe" `
  src\teb_mcp\worker\teb_worker.py
```

then paste `{"id":1,"command":"ping"}` and press Enter. Expect
`"dll_loaded": true`, `"bits": 32` and an empty `missing_symbols`.

## Client configuration

Copilot CLI - `~\.copilot\mcp-config.json`:

```json
{
  "mcpServers": {
    "teb": {
      "type": "local",
      "command": "teb-mcp",
      "args": [],
      "tools": ["*"],
      "env": {
        "TEB_MODE": "virtual",
        "TEB_HOST": "cm1",
        "TEB_PORT": "5000"
      }
    }
  }
}
```

VS Code - `.vscode\mcp.json`:

```json
{
  "servers": {
    "teb": {
      "type": "stdio",
      "command": "teb-mcp",
      "cwd": "${userHome}\\CCSystem\\.github\\skills\\teb-mcp\\server",
      "env": {
        "TEB_MODE": "virtual",
        "TEB_HOST": "cm1",
        "TEB_PORT": "5000"
      }
    }
  }
}
```

Keep `TEB_ALLOW_WRITE` and `TEB_ALLOW_POWER` out of these files and set them as
user environment variables instead, so enabling hardware writes is a deliberate
act rather than a checked-in default:

```powershell
[Environment]::SetEnvironmentVariable("TEB_ALLOW_WRITE", "1", "User")
```

## Design notes

### Why ctypes and not a C++ shim

`TEB_If.h` starts with `#include <tl_timers.h>`, and that header ships with
neither the include directory nor the lib directory of the TEB Interface
package. The header therefore does not compile standalone, which rules out
building a bridge against `TEB_If.lib` until the TL library is located.

Fortunately every export is a `__cdecl` free function with no C++ objects on the
boundary, so ctypes can call them directly by mangled name:

```
?TEB_GPIO_Out@@YAHGH@Z            int TEB_GPIO_Out(WORD, BOOL)
?TEB_GPIO_Cfg@@YAHGW4TEB_DIR@@@Z  int TEB_GPIO_Cfg(WORD, TEB_DIR)
```

Two header features do not survive to the ABI and are handled explicitly in
`teb_api.py`:

- **Overloads** resolve to different symbols. `TEB_FPGA_Read` has three forms
  and `TEB_GetVersion` two; each binding names one exact symbol.
- **Default arguments** do not exist. `TEB_GetVersion` and
  `TEB_FPGA_ReadUntil` must always be passed every argument.

### Why the worker hides its stdout

The DLL writes diagnostics directly to the process stdout:

```
TEB FATAL ERROR! TEB is not connected!
Check TEB connectivity and make sure TEB_Connect() or TEB_Open() has been called.
```

`TEB_ErrorsSuppress(True)` stops modal dialogs - which would otherwise hang a
stdio server forever - but it does not stop that text. Since the same stream
carries JSON responses, `teb_worker.py` dups the real stdout to a private
descriptor and repoints fd 1 and fd 2 at `TEB_WORKER_LOG` (or `NUL`) *before*
importing `teb_api`. Responses go to the private descriptor.

If the protocol ever breaks, that is the first thing to check: any DLL output
reaching fd 1 after the redirect would corrupt the stream, and `bridge.py`
surfaces it as `unparseable worker output`.

### Why every call has a timeout

The DLL talks to hardware over USB or TCP/IP. An unreachable CE machine or a
wedged board can block inside a single call indefinitely, which would hang the
MCP server and the agent with it. `bridge.py` enforces `TEB_CALL_TIMEOUT` on
every request; on expiry it kills the worker, and the next call starts a fresh
one. The board session does not survive that, so `connect()` again.

### Bitstream filename derivation

Reproduced from `FPGA_LoadRTL` in `ValidationCommon\Boards\FPGA.cpp`:

```
generation 4  ->  TEB4_FPGA_<size>K.bin   via TEB_Load
otherwise     ->  TEB_FPGA_<size>K.rbf    via TEB_Open
board ceb1    ->  CEB_FPGA_<size>K.rbf    via TEB_Open
```

`TEB_BoardGeneration()` and `TEB_FPGA_Size()` only return meaningful values once
comms are established, so the worker connects first, then derives the path, then
downloads - matching the sequence in that file.

## Running manually

Stdio cannot be driven by hand, so use HTTP for troubleshooting:

```powershell
cd C:\CCSystem\.github\skills\teb-mcp\server

$env:PYTHONPATH = "$PWD\src"
$env:TEB_HOST = "cm1"
$env:TEB_PORT = "5000"

python -m teb_mcp.server --transport streamable-http --host 127.0.0.1 --port 8767 --path /mcp
```

Initialize a session and keep the `mcp-session-id` response header:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.1"}}}' |
  Out-File -Encoding utf8 -NoNewline init.json

curl.exe -s -D - -X POST http://127.0.0.1:8767/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -d "@init.json"
```

Then call a tool, reusing that session id:

```powershell
'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"health","arguments":{}}}' |
  Out-File -Encoding utf8 -NoNewline health.json

curl.exe -s -N -X POST http://127.0.0.1:8767/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Session-Id: <session-id>" `
  -d "@health.json"
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `no 32-bit Python found` | install the embeddable build, or set `TEB_PYTHON32` |
| `TEB_If.dll not found` | TEB Interface package not installed; or set `TEB_DLL_PATH` |
| `TEB_ConnectEx failed with code 1` | TEB communication error - no board reachable, wrong host/port, or the CE machine's TEB server is not running |
| `timed out after Ns` | board or link wedged; worker restarted, reconnect |
| `already connected` | the session is exclusive - `disconnect()` first |
| `Make sure TEB isn't being occupied by another tool` | the C++ harness or another TEB application holds the board |
| `unparseable worker output` | DLL output leaked onto fd 1 - set `TEB_WORKER_LOG` and inspect |

Set `TEB_WORKER_LOG` to a file path to capture everything the DLL prints; that
log is the only place its diagnostics appear.
