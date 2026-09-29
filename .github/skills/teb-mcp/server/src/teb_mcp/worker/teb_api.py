"""ctypes bindings for Nuvoton's TEB_If.dll.

This module runs inside the **32-bit** worker process only. `TEB_If.dll` is a
32-bit library installed in ``C:\\Windows\\SysWOW64``, so a 64-bit interpreter
physically cannot load it.

Only the standard library is used, so the worker can run under a bare
embeddable Python distribution with no site-packages.

Binding notes
-------------
Every export is an MSVC-mangled ``__cdecl`` free function, e.g.
``?TEB_GPIO_Out@@YAHGH@Z``. There are no C++ objects on the boundary, so
ctypes can call them directly by mangled name.

Two traps the header hides:

* **Overloads** share a C++ name but not a symbol. ``TEB_FPGA_Read`` has three
  forms and ``TEB_GetVersion`` two. Each binding below names one exact symbol.
* **Default arguments** are a compile-time fiction. ``TEB_GetVersion`` and
  ``TEB_FPGA_ReadUntil`` must always be called with every argument.
"""

from __future__ import annotations

import ctypes
import os

DEFAULT_DLL_PATH = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "TEB_If.dll"
)

# --------------------------------------------------------------------------
# Enums mirrored from TEB_Common.h
# --------------------------------------------------------------------------

TEB_IF_SEL = {0: "none", 1: "usb", 2: "pcie", 3: "tcpip"}

FPGA_BOARD_NAME = {
    "any": 0,
    "virtual": 1,
    "teb3": 2,
    "teb4": 3,
    "ceb1": 4,
}

TEB_DIR = {"in": 0, "out": 1}
TEB_DIR_NAME = {0: "in", 1: "out"}

TEB_LEVEL = {"low": 0, "high": 1, "tristate": 2}
TEB_LEVEL_NAME = {0: "low", 1: "high", 2: "tristate"}

TEB_GPIO_FREEZE_MODE = {
    "none": 0,
    "in": 1,
    "out": 2,
    "dir": 4,
    "all": 7,
}

VER_STR_SIZE = 32
TB_STD_STR_SIZE = 256

# Friendly name -> (mangled symbol, restype, argtypes).
_C = ctypes
_SIGNATURES = {
    # -- session / connection ---------------------------------------------
    "TEB_Connect": ("?TEB_Connect@@YAHXZ", _C.c_int, []),
    "TEB_ConnectEx": ("?TEB_ConnectEx@@YAH_N0@Z", _C.c_int, [_C.c_bool, _C.c_bool]),
    "TEB_Open": ("?TEB_Open@@YAHPBD@Z", _C.c_int, [_C.c_char_p]),
    "TEB_OpenEx": (
        "?TEB_OpenEx@@YAHPBD_N1@Z",
        _C.c_int,
        [_C.c_char_p, _C.c_bool, _C.c_bool],
    ),
    "TEB_Load": ("?TEB_Load@@YAHPBD@Z", _C.c_int, [_C.c_char_p]),
    "TEB_Close": ("?TEB_Close@@YAHXZ", _C.c_int, []),
    "TEB_DeviceSelect": (
        "?TEB_DeviceSelect@@YAHW4FPGA_BOARD_NAME@@E@Z",
        _C.c_int,
        [_C.c_int, _C.c_ubyte],
    ),
    "TEB_HIF_TCPIP_SetParams": (
        "?TEB_HIF_TCPIP_SetParams@@YAHPBDG@Z",
        _C.c_int,
        [_C.c_char_p, _C.c_ushort],
    ),
    "TEB_InterfaceConnected": (
        "?TEB_InterfaceConnected@@YA?AW4TEB_IF_SEL@@XZ",
        _C.c_int,
        [],
    ),
    "TEB_InterfaceConnectedName": (
        "?TEB_InterfaceConnectedName@@YAPBDXZ",
        _C.c_char_p,
        [],
    ),
    # -- meta / diagnostics ------------------------------------------------
    "TEB_GetVersion": (
        "?TEB_GetVersion@@YAHPAK0@Z",
        _C.c_int,
        [_C.POINTER(_C.c_uint32), _C.POINTER(_C.c_uint32)],
    ),
    "TEB_GetErrorString": (
        "?TEB_GetErrorString@@YAHPADH@Z",
        _C.c_int,
        [_C.c_char_p, _C.c_int],
    ),
    "TEB_ErrorsSuppress": ("?TEB_ErrorsSuppress@@YAH_N@Z", _C.c_int, [_C.c_bool]),
    "TEB_BoardGeneration": ("?TEB_BoardGeneration@@YAHXZ", _C.c_int, []),
    "TEB_Delay": ("?TEB_Delay@@YAHK@Z", _C.c_int, [_C.c_uint32]),
    # -- FPGA --------------------------------------------------------------
    "TEB_FPGA_Exist": ("?TEB_FPGA_Exist@@YAHXZ", _C.c_int, []),
    "TEB_FPGA_Size": ("?TEB_FPGA_Size@@YAHXZ", _C.c_int, []),
    "TEB_FPGA_Version": (
        "?TEB_FPGA_Version@@YAHPAG@Z",
        _C.c_int,
        [_C.POINTER(_C.c_ushort)],
    ),
    "TEB_FPGA_BuildDateAndTime": (
        "?TEB_FPGA_BuildDateAndTime@@YAHPAK0@Z",
        _C.c_int,
        [_C.POINTER(_C.c_uint32), _C.POINTER(_C.c_uint32)],
    ),
    "TEB_FPGA_Composition": (
        "?TEB_FPGA_Composition@@YAHQAD@Z",
        _C.c_int,
        [_C.c_char_p],
    ),
    "TEB_FPGA_Reset": ("?TEB_FPGA_Reset@@YAH_N@Z", _C.c_int, [_C.c_bool]),
    "TEB_FPGA_Read": ("?TEB_FPGA_Read@@YAGG@Z", _C.c_ushort, [_C.c_ushort]),
    "TEB_FPGA_Read32": ("?TEB_FPGA_Read32@@YAKG@Z", _C.c_uint32, [_C.c_ushort]),
    "TEB_FPGA_Write": (
        "?TEB_FPGA_Write@@YAHGG@Z",
        _C.c_int,
        [_C.c_ushort, _C.c_ushort],
    ),
    "TEB_FPGA_Write32": (
        "?TEB_FPGA_Write32@@YAHGK@Z",
        _C.c_int,
        [_C.c_ushort, _C.c_uint32],
    ),
    "TEB_FPGA_WriteField": (
        "?TEB_FPGA_WriteField@@YAHGEEG@Z",
        _C.c_int,
        [_C.c_ushort, _C.c_ubyte, _C.c_ubyte, _C.c_ushort],
    ),
    "TEB_FPGA_ReadUntil": (
        "?TEB_FPGA_ReadUntil@@YAGGGPBDGK@Z",
        _C.c_ushort,
        [_C.c_ushort, _C.c_ushort, _C.c_char_p, _C.c_ushort, _C.c_uint32],
    ),
    # -- GPIO --------------------------------------------------------------
    "TEB_GPIO_Cfg": (
        "?TEB_GPIO_Cfg@@YAHGW4TEB_DIR@@@Z",
        _C.c_int,
        [_C.c_ushort, _C.c_int],
    ),
    "TEB_GPIO_Out": ("?TEB_GPIO_Out@@YAHGH@Z", _C.c_int, [_C.c_ushort, _C.c_int]),
    "TEB_GPIO_In": (
        "?TEB_GPIO_In@@YAHGPAE@Z",
        _C.c_int,
        [_C.c_ushort, _C.POINTER(_C.c_ubyte)],
    ),
    "TEB_GPIO_CfgRead": (
        "?TEB_GPIO_CfgRead@@YAHGPAW4TEB_DIR@@PAW4TEB_LEVEL@@@Z",
        _C.c_int,
        [_C.c_ushort, _C.POINTER(_C.c_int), _C.POINTER(_C.c_int)],
    ),
    "TEB_GPIO_Freeze": (
        "?TEB_GPIO_Freeze@@YAHW4TEB_GPIO_FREEZE_MODE@@@Z",
        _C.c_int,
        [_C.c_int],
    ),
    # -- modules -----------------------------------------------------------
    "TEB_ModuleExists": ("?TEB_ModuleExists@@YA_NG@Z", _C.c_bool, [_C.c_ushort]),
    "TEB_ModuleName": (
        "?TEB_ModuleName@@YAGGQAD@Z",
        _C.c_ushort,
        [_C.c_ushort, _C.c_char_p],
    ),
    "TEB_ModuleNumOfChannels": (
        "?TEB_ModuleNumOfChannels@@YAHG@Z",
        _C.c_int,
        [_C.c_ushort],
    ),
    "TEB_ModuleNumOfBuses": ("?TEB_ModuleNumOfBuses@@YAHG@Z", _C.c_int, [_C.c_ushort]),
    "TEB_ModuleReset": ("?TEB_ModuleReset@@YAHG@Z", _C.c_int, [_C.c_ushort]),
}


class TebError(RuntimeError):
    """A TEB API call returned a non-zero status."""

    def __init__(self, func, code, detail=""):
        self.func = func
        self.code = code
        self.detail = detail
        msg = "%s failed with code %d" % (func, code)
        if detail and detail.lower() != "no error":
            msg += ": %s" % detail
        super().__init__(msg)


class TebApi:
    """Thin, typed wrapper over the exported TEB functions."""

    def __init__(self, dll_path=None):
        self.dll_path = dll_path or DEFAULT_DLL_PATH
        if not os.path.exists(self.dll_path):
            raise FileNotFoundError("TEB_If.dll not found at %s" % self.dll_path)

        if ctypes.sizeof(ctypes.c_void_p) != 4:
            raise RuntimeError(
                "TEB_If.dll is 32-bit and cannot be loaded by this %d-bit "
                "interpreter" % (ctypes.sizeof(ctypes.c_void_p) * 8)
            )

        self._lib = ctypes.CDLL(self.dll_path)
        self._fn = {}
        self._missing = []

        for name, (symbol, restype, argtypes) in _SIGNATURES.items():
            try:
                fn = getattr(self._lib, symbol)
            except AttributeError:
                self._missing.append(name)
                continue
            fn.restype = restype
            fn.argtypes = argtypes
            self._fn[name] = fn

        # Keep the DLL from raising modal dialogs. It still writes diagnostics
        # to the process stdout, which the worker redirects away from the IPC
        # channel before this class is ever constructed.
        if "TEB_ErrorsSuppress" in self._fn:
            self._fn["TEB_ErrorsSuppress"](True)

    # -- plumbing ----------------------------------------------------------

    def _call(self, name, *args):
        fn = self._fn.get(name)
        if fn is None:
            raise TebError(name, -1, "symbol not exported by this DLL version")
        return fn(*args)

    def _checked(self, name, *args):
        rc = self._call(name, *args)
        if rc != 0:
            raise TebError(name, int(rc), self.last_error())
        return int(rc)

    def last_error(self):
        fn = self._fn.get("TEB_GetErrorString")
        if fn is None:
            return ""
        buf = ctypes.create_string_buffer(512)
        try:
            fn(buf, 512)
        except Exception:
            return ""
        return buf.value.decode("latin-1", "replace")

    @property
    def missing_symbols(self):
        return list(self._missing)

    # -- session -----------------------------------------------------------

    def set_tcpip_params(self, ip, port):
        self._checked("TEB_HIF_TCPIP_SetParams", ip.encode("ascii"), int(port))

    def device_select(self, board, instance=0):
        value = FPGA_BOARD_NAME.get(board)
        if value is None:
            raise ValueError(
                "unknown board %r, expected one of %s"
                % (board, ", ".join(sorted(FPGA_BOARD_NAME)))
            )
        self._checked("TEB_DeviceSelect", value, int(instance))

    def connect(self, fpga_reset=True, init_modules=True):
        self._checked("TEB_ConnectEx", bool(fpga_reset), bool(init_modules))

    def open_bitstream(self, path):
        """Download a bitstream. Generation 4 boards use TEB_Load (.bin)."""
        encoded = path.encode("mbcs" if os.name == "nt" else "utf-8")
        if self.board_generation() == 4:
            self._checked("TEB_Load", encoded)
        else:
            self._checked("TEB_Open", encoded)

    def close(self):
        self._checked("TEB_Close")

    def interface(self):
        return TEB_IF_SEL.get(int(self._call("TEB_InterfaceConnected")), "unknown")

    def interface_name(self):
        raw = self._call("TEB_InterfaceConnectedName")
        return raw.decode("latin-1", "replace") if raw else ""

    # -- meta --------------------------------------------------------------

    def versions(self):
        dll_ver = ctypes.c_uint32(0)
        fw_ver = ctypes.c_uint32(0)
        self._call("TEB_GetVersion", ctypes.byref(dll_ver), ctypes.byref(fw_ver))
        return {
            "dll": format_version(dll_ver.value),
            "dll_raw": dll_ver.value,
            "firmware": format_version(fw_ver.value),
            "firmware_raw": fw_ver.value,
        }

    def board_generation(self):
        return int(self._call("TEB_BoardGeneration"))

    def fpga_size(self):
        return int(self._call("TEB_FPGA_Size"))

    def fpga_exists(self):
        return bool(self._call("TEB_FPGA_Exist"))

    def fpga_version(self):
        value = ctypes.c_ushort(0)
        self._call("TEB_FPGA_Version", ctypes.byref(value))
        return int(value.value)

    def fpga_build(self):
        date = ctypes.c_uint32(0)
        time_ = ctypes.c_uint32(0)
        self._call("TEB_FPGA_BuildDateAndTime", ctypes.byref(date), ctypes.byref(time_))
        return {"date": date.value, "time": time_.value}

    def fpga_composition(self):
        buf = ctypes.create_string_buffer(TB_STD_STR_SIZE)
        self._call("TEB_FPGA_Composition", buf)
        return buf.value.decode("latin-1", "replace")

    # -- FPGA registers ----------------------------------------------------

    def fpga_read(self, address, width=16):
        if width == 32:
            return int(self._call("TEB_FPGA_Read32", int(address)))
        return int(self._call("TEB_FPGA_Read", int(address)))

    def fpga_write(self, address, data, width=16):
        if width == 32:
            self._checked("TEB_FPGA_Write32", int(address), int(data))
        else:
            self._checked("TEB_FPGA_Write", int(address), int(data))

    def fpga_write_field(self, address, start_bit, num_bits, data):
        self._checked(
            "TEB_FPGA_WriteField",
            int(address),
            int(start_bit),
            int(num_bits),
            int(data),
        )

    def fpga_read_until(
        self, address, expected, operator="==", mask=0xFFFF, timeout_us=1000000
    ):
        return int(
            self._call(
                "TEB_FPGA_ReadUntil",
                int(address),
                int(expected),
                operator.encode("ascii"),
                int(mask),
                int(timeout_us),
            )
        )

    def fpga_reset(self, init_modules=True):
        self._checked("TEB_FPGA_Reset", bool(init_modules))

    # -- GPIO --------------------------------------------------------------

    def gpio_config(self, pin, direction):
        value = TEB_DIR.get(direction)
        if value is None:
            raise ValueError("direction must be 'in' or 'out', got %r" % (direction,))
        self._checked("TEB_GPIO_Cfg", int(pin), value)

    def gpio_write(self, pin, level):
        value = TEB_LEVEL.get(level)
        if value is None:
            raise ValueError(
                "level must be one of %s, got %r" % (", ".join(sorted(TEB_LEVEL)), level)
            )
        self._checked("TEB_GPIO_Out", int(pin), value)

    def gpio_read(self, pin):
        state = ctypes.c_ubyte(0)
        self._checked("TEB_GPIO_In", int(pin), ctypes.byref(state))
        return TEB_LEVEL_NAME.get(int(state.value), str(state.value))

    def gpio_read_config(self, pin):
        direction = ctypes.c_int(0)
        level = ctypes.c_int(0)
        self._checked(
            "TEB_GPIO_CfgRead", int(pin), ctypes.byref(direction), ctypes.byref(level)
        )
        return {
            "pin": int(pin),
            "direction": TEB_DIR_NAME.get(direction.value, str(direction.value)),
            "level": TEB_LEVEL_NAME.get(level.value, str(level.value)),
        }

    def gpio_freeze(self, mode):
        value = TEB_GPIO_FREEZE_MODE.get(mode)
        if value is None:
            raise ValueError(
                "mode must be one of %s, got %r"
                % (", ".join(sorted(TEB_GPIO_FREEZE_MODE)), mode)
            )
        self._checked("TEB_GPIO_Freeze", value)

    # -- modules -----------------------------------------------------------

    def module_exists(self, module_id):
        return bool(self._call("TEB_ModuleExists", int(module_id)))

    def module_name(self, module_id):
        buf = ctypes.create_string_buffer(TB_STD_STR_SIZE)
        self._call("TEB_ModuleName", int(module_id), buf)
        return buf.value.decode("latin-1", "replace")

    def module_info(self, module_id):
        return {
            "id": int(module_id),
            "name": self.module_name(module_id),
            "channels": int(self._call("TEB_ModuleNumOfChannels", int(module_id))),
            "buses": int(self._call("TEB_ModuleNumOfBuses", int(module_id))),
        }


def format_version(raw):
    """0x03010000 -> '3.1.0.0'."""
    return "%d.%d.%d.%d" % (
        (raw >> 24) & 0xFF,
        (raw >> 16) & 0xFF,
        (raw >> 8) & 0xFF,
        raw & 0xFF,
    )
