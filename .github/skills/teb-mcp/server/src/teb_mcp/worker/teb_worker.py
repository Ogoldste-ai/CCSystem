"""32-bit worker process that owns the TEB session.

Why this exists
---------------
``TEB_If.dll`` is 32-bit, so it cannot be loaded by the 64-bit interpreter that
runs the MCP server. This worker is launched under a 32-bit Python and speaks
JSON-lines over stdio to the 64-bit parent.

Protecting the IPC channel
--------------------------
The DLL writes diagnostics straight to the process stdout, for example::

    TEB FATAL ERROR! TEB is not connected!

``TEB_ErrorsSuppress(True)`` stops modal dialogs but does **not** stop that
text. Writing it into the same pipe we use for JSON would corrupt every
response, so before the DLL is loaded we dup the real stdout to a private
descriptor and point fd 1 (and fd 2) at a log file. Responses are then written
to the private descriptor, which nothing else can reach.

The session is stateful (``Connect`` ... calls ... ``Close``), so one worker owns
exactly one board at a time and handles requests strictly in order.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------
# Channel isolation - must happen before teb_api imports/loads the DLL.
# --------------------------------------------------------------------------

_RESPONSE_FD = os.dup(1)

_log_path = os.environ.get("TEB_WORKER_LOG")
_log_fd = None
if _log_path:
    try:
        _log_path = os.path.expanduser(os.path.expandvars(_log_path))
        parent = os.path.dirname(_log_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        _log_fd = os.open(_log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    except OSError:
        # A bad log path must never stop the worker from serving requests.
        _log_fd = None
if _log_fd is None:
    _log_fd = os.open(os.devnull, os.O_WRONLY)

os.dup2(_log_fd, 1)
os.dup2(_log_fd, 2)
sys.stdout = os.fdopen(1, "w", buffering=1, errors="replace")
sys.stderr = os.fdopen(2, "w", buffering=1, errors="replace")

import teb_api  # noqa: E402  (deliberately after the fd redirection)


class Session:
    """Holds the single TEB connection and implements the command surface."""

    def __init__(self):
        self.api = None
        self.load_error = None
        self.connected = False
        self.target = None

        try:
            self.api = teb_api.TebApi(os.environ.get("TEB_DLL_PATH") or None)
        except Exception as exc:
            self.load_error = str(exc)

    # -- helpers -----------------------------------------------------------

    def _require_api(self):
        if self.api is None:
            raise RuntimeError("TEB library not loaded: %s" % self.load_error)
        return self.api

    def _require_connected(self):
        api = self._require_api()
        if not self.connected:
            raise RuntimeError("not connected to a TEB - call connect() first")
        return api

    def _bitstream_path(self, directory, board):
        """Reproduce FPGA_LoadRTL's filename derivation from ValidationCommon.

        Generation 4 boards use ``TEB4_FPGA_<size>K.bin``; earlier generations
        use ``TEB_FPGA_<size>K.rbf`` or ``CEB_FPGA_<size>K.rbf``. The size and
        generation come from the board itself, so this only works once comms
        are established.
        """
        api = self._require_api()
        generation = api.board_generation()
        size = api.fpga_size()

        if generation == 4:
            name = "TEB%d_FPGA_%dK.bin" % (generation, size)
        elif board == "ceb1":
            name = "CEB_FPGA_%dK.rbf" % size
        else:
            name = "TEB_FPGA_%dK.rbf" % size
        return os.path.join(directory, name)

    # -- commands ----------------------------------------------------------

    def cmd_ping(self):
        return {
            "alive": True,
            "pid": os.getpid(),
            "bits": 8 * __import__("ctypes").sizeof(__import__("ctypes").c_void_p),
            "python": sys.version.split()[0],
            "dll_loaded": self.api is not None,
            "dll_path": self.api.dll_path if self.api else None,
            "load_error": self.load_error,
            "missing_symbols": self.api.missing_symbols if self.api else [],
            "connected": self.connected,
            "target": self.target,
        }

    def cmd_versions(self):
        return self._require_api().versions()

    def cmd_connect(
        self,
        mode="virtual",
        host=None,
        port=None,
        board=None,
        instance=0,
        bitstream_dir=None,
        fpga_reset=True,
        init_modules=True,
    ):
        api = self._require_api()

        if self.connected:
            raise RuntimeError(
                "already connected to %s - call disconnect() first"
                % (self.target or "a board")
            )

        if mode not in ("virtual", "usb-local", "usb-remote"):
            raise ValueError("unknown mode %r" % (mode,))

        if board is None:
            board = "virtual" if mode == "virtual" else "any"

        if mode in ("virtual", "usb-remote"):
            if not host:
                raise ValueError("mode %r requires a host" % (mode,))
            if not port:
                raise ValueError(
                    "mode %r requires a port - there is no default, it is set "
                    "per run (TEB_PORT)" % (mode,)
                )
            api.set_tcpip_params(host, int(port))

        api.device_select(board, instance)

        # Establish comms first; board generation and FPGA size are only
        # meaningful afterwards, and the bitstream name is derived from them.
        api.connect(fpga_reset=fpga_reset, init_modules=init_modules)
        self.connected = True

        result = {
            "mode": mode,
            "board": board,
            "instance": instance,
            "interface": api.interface(),
            "interface_name": api.interface_name(),
            "bitstream": None,
        }

        if mode != "virtual":
            if not bitstream_dir:
                self.connected = False
                try:
                    api.close()
                except Exception:
                    pass
                raise ValueError(
                    "mode %r needs a real bitstream - set TEB_BITSTREAM_DIR or "
                    "pass bitstream_dir" % (mode,)
                )
            path = self._bitstream_path(bitstream_dir, board)
            if not os.path.exists(path):
                self.connected = False
                try:
                    api.close()
                except Exception:
                    pass
                raise FileNotFoundError("bitstream not found: %s" % path)
            api.open_bitstream(path)
            result["bitstream"] = path

        if host:
            result["host"] = host
            result["port"] = int(port)

        self.target = "%s:%s" % (mode, host or "local")
        return result

    def cmd_disconnect(self):
        api = self._require_api()
        if not self.connected:
            return {"connected": False, "note": "was not connected"}
        api.close()
        self.connected = False
        self.target = None
        return {"connected": False}

    def cmd_status(self):
        api = self._require_api()
        status = {
            "connected": self.connected,
            "target": self.target,
            "interface": api.interface(),
            "interface_name": api.interface_name(),
            "versions": api.versions(),
        }
        if self.connected:
            status["board_generation"] = api.board_generation()
            status["fpga_size_k"] = api.fpga_size()
            status["fpga_present"] = api.fpga_exists()
            status["fpga_version"] = api.fpga_version()
            status["fpga_build"] = api.fpga_build()
            try:
                status["fpga_composition"] = api.fpga_composition()
            except Exception:
                status["fpga_composition"] = None
        return status

    def cmd_last_error(self):
        return {"message": self._require_api().last_error()}

    def cmd_list_modules(self, max_id=64):
        api = self._require_connected()
        modules = []
        for module_id in range(int(max_id)):
            try:
                if api.module_exists(module_id):
                    modules.append(api.module_info(module_id))
            except Exception:
                continue
        return {"modules": modules, "count": len(modules)}

    # -- GPIO --------------------------------------------------------------

    def cmd_gpio_config(self, pin, direction):
        self._require_connected().gpio_config(pin, direction)
        return {"pin": int(pin), "direction": direction}

    def cmd_gpio_write(self, pin, level):
        self._require_connected().gpio_write(pin, level)
        return {"pin": int(pin), "level": level}

    def cmd_gpio_read(self, pin):
        level = self._require_connected().gpio_read(pin)
        return {"pin": int(pin), "level": level}

    def cmd_gpio_read_config(self, pin):
        return self._require_connected().gpio_read_config(pin)

    def cmd_gpio_freeze(self, mode):
        self._require_connected().gpio_freeze(mode)
        return {"freeze_mode": mode}

    # -- FPGA registers ----------------------------------------------------

    def cmd_fpga_read(self, address, width=16):
        value = self._require_connected().fpga_read(address, width)
        return {
            "address": int(address),
            "width": int(width),
            "value": value,
            "hex": "0x%0*X" % (int(width) // 4, value),
        }

    def cmd_fpga_write(self, address, data, width=16):
        self._require_connected().fpga_write(address, data, width)
        return {"address": int(address), "data": int(data), "width": int(width)}

    def cmd_fpga_write_field(self, address, start_bit, num_bits, data):
        self._require_connected().fpga_write_field(address, start_bit, num_bits, data)
        return {
            "address": int(address),
            "start_bit": int(start_bit),
            "num_bits": int(num_bits),
            "data": int(data),
        }

    def cmd_fpga_read_until(
        self, address, expected, operator="==", mask=0xFFFF, timeout_us=1000000
    ):
        value = self._require_connected().fpga_read_until(
            address, expected, operator, mask, timeout_us
        )
        return {
            "address": int(address),
            "value": value,
            "hex": "0x%04X" % value,
            "matched": (value & int(mask)) == (int(expected) & int(mask)),
        }

    def cmd_fpga_reset(self, init_modules=True):
        self._require_connected().fpga_reset(init_modules)
        return {"reset": True, "init_modules": bool(init_modules)}


def _write_response(payload):
    data = (json.dumps(payload) + "\n").encode("utf-8")
    written = 0
    while written < len(data):
        written += os.write(_RESPONSE_FD, data[written:])


def main():
    session = Session()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except ValueError as exc:
            _write_response({"id": None, "ok": False, "error": "bad JSON: %s" % exc})
            continue

        req_id = request.get("id")
        command = request.get("command")
        args = request.get("args") or {}

        if command == "shutdown":
            _write_response({"id": req_id, "ok": True, "result": {"bye": True}})
            try:
                if session.connected and session.api:
                    session.api.close()
            except Exception:
                pass
            return 0

        handler = getattr(session, "cmd_%s" % command, None) if command else None
        if handler is None:
            _write_response(
                {"id": req_id, "ok": False, "error": "unknown command %r" % command}
            )
            continue

        try:
            result = handler(**args)
            _write_response({"id": req_id, "ok": True, "result": result})
        except teb_api.TebError as exc:
            _write_response(
                {
                    "id": req_id,
                    "ok": False,
                    "error": str(exc),
                    "error_type": "TebError",
                    "code": exc.code,
                }
            )
        except Exception as exc:
            _write_response(
                {
                    "id": req_id,
                    "ok": False,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                    "error_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                }
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
