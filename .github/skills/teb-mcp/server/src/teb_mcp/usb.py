"""Read-only probe of the TEB board's USB presence and driver state.

This exists because ``TEB_ConnectEx`` reports a single error code (1) for two
very different situations: no board attached, and a board that is attached but
has no driver bound. The DLL reaches the board through **WinUSB**, so without a
driver there is no device interface to open and the call fails exactly as if
the board were absent.

The probe runs in the 64-bit parent process and touches nothing but the
configuration manager and the registry, so it still works when the 32-bit
worker or ``TEB_If.dll`` is broken - which is precisely when it is needed. It
is diagnostics only: every failure degrades to a result that says "unknown",
and nothing here may ever block a connection attempt.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

# Hardware IDs matched by TEB_If.dll itself (the strings VID_0416&PID_0030,
# &PID_0031 and &PID_0032 are embedded in the binary). 0416 is Nuvoton /
# Winbond; the USB endpoint is named after the "Hermon" chip family rather
# than after the board, which is why searching for "TEB" finds nothing.
TEB_HARDWARE_IDS = (
    "USB\\VID_0416&PID_0030",
    "USB\\VID_0416&PID_0031",
    "USB\\VID_0416&PID_0032",
)

# Subset of CM_PROB_* worth naming. Code 28 is the one that matters here.
PROBLEM_TEXT = {
    0: "no problem",
    1: "not configured correctly",
    10: "cannot start",
    12: "cannot find enough free resources",
    18: "drivers need to be reinstalled",
    19: "registry configuration is corrupt",
    22: "disabled",
    28: "the drivers for this device are not installed",
    31: "Windows cannot load the drivers for this device",
    43: "stopped after reporting a problem",
}

DRIVER_HINT = (
    "The board is plugged in but no driver is bound to it, so TEB_If.dll "
    "cannot open a WinUSB handle and every connect attempt fails. Install the "
    "Nuvoton TEB USB driver (the device should end up with service 'WinUSB' "
    "and a name like 'TEB3 USB Driver'); this needs administrator rights."
)

_CR_SUCCESS = 0
_CM_DRP_DEVICEDESC = 0x00000001
_CM_DRP_FRIENDLYNAME = 0x0000000D
_CM_DRP_SERVICE = 0x00000005
_CM_DRP_LOCATION_INFORMATION = 0x0000000E
_DN_HAS_PROBLEM = 0x00000400


def _registry_instances(hardware_id: str) -> list[str]:
    """List the instance IDs present under one hardware ID, via the registry.

    ``CM_Locate_DevNode`` needs a full instance ID, but a hardware ID may have
    several instances, so enumerate them first. Reading the Enum key requires
    no special privileges.
    """
    import winreg

    key_path = "SYSTEM\\CurrentControlSet\\Enum\\" + hardware_id
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return []

    instances = []
    with key:
        index = 0
        while True:
            try:
                instances.append(winreg.EnumKey(key, index))
            except OSError:
                break
            index += 1
    return ["%s\\%s" % (hardware_id, name) for name in instances]


def _device_property(cfgmgr, devinst: int, prop: int) -> str | None:
    size = ctypes.c_ulong(0)
    reg_type = ctypes.c_ulong(0)
    cfgmgr.CM_Get_DevNode_Registry_PropertyW(
        devinst, prop, ctypes.byref(reg_type), None, ctypes.byref(size), 0
    )
    if not size.value:
        return None
    buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
    rc = cfgmgr.CM_Get_DevNode_Registry_PropertyW(
        devinst, prop, ctypes.byref(reg_type), buf, ctypes.byref(size), 0
    )
    if rc != _CR_SUCCESS:
        return None
    return buf.value or None


def _probe_instance(cfgmgr, instance_id: str) -> dict[str, Any]:
    devinst = ctypes.c_ulong(0)
    rc = cfgmgr.CM_Locate_DevNodeW(
        ctypes.byref(devinst), ctypes.c_wchar_p(instance_id), 0
    )
    if rc != _CR_SUCCESS:
        return {"instance_id": instance_id, "present": False}

    status = ctypes.c_ulong(0)
    problem = ctypes.c_ulong(0)
    problem_code: int | None = None
    if (
        cfgmgr.CM_Get_DevNode_Status(
            ctypes.byref(status), ctypes.byref(problem), devinst, 0
        )
        == _CR_SUCCESS
    ):
        problem_code = problem.value if status.value & _DN_HAS_PROBLEM else 0

    service = _device_property(cfgmgr, devinst, _CM_DRP_SERVICE)
    # Most TEB devices carry only a device description, not a friendly name.
    name = _device_property(cfgmgr, devinst, _CM_DRP_FRIENDLYNAME) or _device_property(
        cfgmgr, devinst, _CM_DRP_DEVICEDESC
    )
    return {
        "instance_id": instance_id,
        "present": True,
        "friendly_name": name,
        "location": _device_property(
            cfgmgr, devinst, _CM_DRP_LOCATION_INFORMATION
        ),
        "service": service,
        "driver_bound": bool(service),
        "problem_code": problem_code,
        "problem_text": (
            None
            if problem_code in (None, 0)
            else PROBLEM_TEXT.get(problem_code, "problem code %d" % problem_code)
        ),
    }


def _verdict(devices: list[dict[str, Any]]) -> dict[str, Any]:
    if not devices:
        return {
            "state": "absent",
            "summary": (
                "No TEB USB device is enumerated (looked for %s). The board is "
                "not plugged in, not powered, or on another machine."
                % ", ".join(TEB_HARDWARE_IDS)
            ),
        }

    ready = [d for d in devices if d.get("driver_bound") and not d.get("problem_code")]
    if ready:
        device = ready[0]
        return {
            "state": "ready",
            "summary": "TEB USB device %s is bound to driver service %r and has "
            "no problem reported." % (device["instance_id"], device["service"]),
        }

    device = devices[0]
    if device.get("problem_code") == 28 or not device.get("driver_bound"):
        return {
            "state": "no-driver",
            "summary": "TEB USB device %s is present but has no working driver "
            "(%s). %s"
            % (
                device["instance_id"],
                device.get("problem_text") or "no driver service bound",
                DRIVER_HINT,
            ),
        }

    return {
        "state": "problem",
        "summary": "TEB USB device %s is present but Windows reports a problem: "
        "%s." % (device["instance_id"], device.get("problem_text")),
    }


def probe() -> dict[str, Any]:
    """Describe the TEB USB device(s) attached to this machine.

    Always returns a dict; never raises. ``available`` is False when the probe
    itself could not run, in which case the caller should draw no conclusion
    about the hardware.
    """
    if sys.platform != "win32":
        return {
            "available": False,
            "error": "USB probing is implemented for Windows only",
            "devices": [],
        }

    try:
        cfgmgr = ctypes.WinDLL("cfgmgr32")
        devices = []
        for hardware_id in TEB_HARDWARE_IDS:
            for instance_id in _registry_instances(hardware_id):
                info = _probe_instance(cfgmgr, instance_id)
                if info.get("present"):
                    devices.append(info)
    except Exception as exc:  # diagnostics must never break the caller
        return {
            "available": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "devices": [],
        }

    result: dict[str, Any] = {
        "available": True,
        "hardware_ids": list(TEB_HARDWARE_IDS),
        "devices": devices,
    }
    result.update(_verdict(devices))
    return result
