---
name: Shared-Module-Host-convert-to-param
description: Convert a Host-project global variable/buffer/table that a SharedModules\Shared_* test file references directly (via extern) into a properly encapsulated parameter on that module's *Parameters/params class, using a static set/get accessor pair. Use when a Shared_* module (e.g. Shared_I3C, Shared_GPIO, Shared_VCT) needs data owned by a specific Host project (e.g. EC\Modules\<X>\Host, BMC\Modules\<X>\host) without taking a hard compile-time dependency on that project's globals.
---

# Shared Module: Convert Host Global to Param

## Why this exists

`SharedModules\Shared_*` code is compiled into many different Host projects
(EC and BMC), each of which owns its own project-specific globals (voltage
tables, transmit/receive buffers, support tables, etc.). A shared test must
never reference a Host project's global directly via `extern` — that creates
a hidden compile/link dependency that only works for projects which happen to
define a matching symbol, and breaks portability of the shared module.

The established convention (see `SharedI3cTestParams` in
`SharedModules\Shared_I3C\I3C_Host_SM.h/.cpp`, and `GPIO_Parameters` in
`SharedModules\Shared_GPIO.h`) is a small `*Parameters`/`params` holder class
with **private pointer members**, set once from the Host project and read via
accessors from the shared module. This skill captures the exact steps to
apply that pattern to a new Host global.

## Preconditions / things to identify before editing

1. The **Shared module header** that declares a `<Something>Parameters` class
   or a `params` member (e.g. `SharedI3cTestParams`, `GPIO_Parameters`). If
   the shared module has no such class yet, create one following the existing
   examples (private pointer members, public static or instance `setX`/`getX`
   pair, exposed as `inline static <Class> params;` on the owning
   `Shared*`/`*Common` class).
2. The **Host global** to convert: its exact type, declaring `.cpp`, and
   `extern` declaration in the matching `.h` (e.g. `HostGeneral.h/.cpp`).
3. Every place inside the **shared** `.cpp` that references the global
   directly — these must all be redirected through the getter.
4. The **Host test entry point** that already wires up other params for the
   same shared module (e.g. `TEST_Sort()` in `HostTests.cpp` calling
   `I3cCommon::params.setI3cVoltageTable(...)`) — the new setter call belongs
   next to those, called once before the shared test runs.

## Steps

1. **Add the accessor declarations** to the `*Parameters` class in the shared
   module's header:
   ```cpp
   static bool   setI3cTransmitDataBuff(BYTE* buffer);
   static BYTE*  getI3cTransmitDataBuff();
   ```
   and a matching private pointer member initialized to `nullptr`:
   ```cpp
   inline static BYTE* _i3cTransmitDataBuff = nullptr;
   ```
   Match the existing member's storage style (`inline static` for
   header-only definitions is the convention already used here).

2. **Implement the setter/getter** in the shared module's `.cpp`, mirroring
   the existing pair (e.g. `setI3cVoltageTable`/`getI3cVoltageTable`) exactly:
   - Setter: set the pointer **only if currently `nullptr`**; otherwise
     `LogError(...)` and return `false`. This makes the set-once contract
     explicit and catches accidental double-registration.
   - Getter: if the pointer is still `nullptr`, `LogError(...)` and return
     `nullptr`; otherwise return the stored pointer.

3. **Replace every direct use of the Host global inside the shared `.cpp`**
   with a call to the new getter, e.g.
   `g_transmitDataBuff[i]` → `I3cCommon::params.getI3cTransmitDataBuff()[i]`.
   Do this for all reads *and* writes, and for any call that passes the
   buffer/table by pointer (e.g. `CoreWrite(..., g_transmitDataBuff)` →
   `CoreWrite(..., I3cCommon::params.getI3cTransmitDataBuff())`).
   Do **not** leave a residual `extern` reference to the Host global inside
   the shared module.

4. **Wire the setter call from the Host project** at the same place the
   other params for this shared module are already set (typically the test
   entry function, e.g. `TEST_Sort()` in `HostTests.cpp`), passing the
   project's own global:
   ```cpp
   I3cCommon::params.setI3cTransmitDataBuff(g_transmitDataBuff);
   ```
   Add it next to the existing `set*` calls, not somewhere else in the file.

5. **Verify**:
   - Grep the shared `.cpp` for the old global name — there should be zero
     remaining references outside of unrelated files.
   - Build the smallest Host project/solution that compiles both the shared
     `.cpp` and the Host `.cpp` that calls the setter (e.g. via MSBuild on the
     relevant `*.sln` with the correct solution configuration/platform, such
     as `HostDebug|Win32`). Confirm zero errors.

## Worked example (I3C)

- Shared class: `SharedI3cTestParams` in
  `SharedModules\Shared_I3C\I3C_Host_SM.h/.cpp`.
- Existing pattern reference: `_i3cVoltageTable` /
  `setI3cVoltageTable(double*)` / `getI3cVoltageTable()`.
- Converted global: `BYTE g_transmitDataBuff[200]` (declared/defined in
  `EC\Modules\I3C_Ramon\Host\HostGeneral.h/.cpp`), previously accessed
  directly inside `I3cCommon::_sharedTestI3cSort()`.
- New accessors added: `setI3cTransmitDataBuff(BYTE*)` /
  `getI3cTransmitDataBuff()`, backed by `inline static BYTE*
  _i3cTransmitDataBuff = nullptr;`.
- Setter wired in `EC\Modules\I3C_Ramon\Host\HostTests.cpp::TEST_Sort()`,
  next to the existing `setI3cVoltageTable` / `setI3cVoltageLevelSupportTable`
  calls.
- Verified with:
  `MSBuild EC\Modules\I3C_Ramon\I3C_Ramon.sln /t:Host /p:Configuration=HostDebug /p:Platform=Win32`

## Common pitfalls

- **Forgetting a usage site**: a global used in a read-compare loop, a
  fill/write loop, *and* a bulk `CoreRead`/`CoreWrite` call is easy to
  partially convert. Search the whole shared `.cpp` (not just the first hit)
  for the global's name before declaring the conversion done.
- **Wrong pointer type**: match the getter/setter type exactly to the Host
  global's element type (e.g. `BYTE*` for a `BYTE[]`, not `int*` or `void*`).
- **Flattened 2D tables**: if the Host global is a 2D array
  (`T table[ROWS][COLS]`) passed in as `&table[0][0]`, remember the row-major
  index formula is `row * COLS + col` — the stride is the **column** count,
  not the row count. This is an easy off-by-index-formula bug (see the
  `I3C_MODULE_NUM` vs `I3C_LEVEL_NUM` stride bug fixed in
  `isI3cSupportVoltageShared()` as a cautionary example).
- **Multiple Host projects, one shared module**: since the shared `.cpp` is
  compiled per-project, do not assume the setter has been called — always
  guard on `nullptr` in the getter and log clearly rather than dereferencing
  blindly.
