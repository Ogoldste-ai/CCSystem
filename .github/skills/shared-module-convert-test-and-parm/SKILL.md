---
name: shared-module-convert-test-and-parm
description: Convert a whole project-specific test (and everything it touches — project globals/constants AND project functions/HAL calls) into a portable SharedModules\Shared_* test, on BOTH the Host side and the Core side. Use when a test currently lives only in one project (e.g. EC\Modules\<X>\Host\HostTests.cpp and EC\Modules\<X>\Core\CoreTests.cpp) and needs to move into the shared module so other projects (other EC modules, BMC modules) can reuse it, while strictly respecting that SharedModules\* files may never #include anything from EC\* or BMC\*.
---

# Shared Module: Convert a Whole Test (Params + Functions, Host + Core)

## Why this exists

A single logical test (e.g. "I3C sort test", "I3C add/read/write I2C device
via JTAG") is normally split across two project-owned files:

- **Host side**: `EC\Modules\<X>\Host\HostTests.cpp` (or BMC equivalent) —
  runs on the PC, drives the test via `MSG_RunTest`/`MSG_Data`/JTAG.
- **Core side**: `EC\Modules\<X>\Core\CoreTests.cpp` (or BMC equivalent) —
  runs on the chip firmware, dispatched from `USER_Main_Core_Tests()`
  (`CoreGeneral.cpp`), does the real HAL work.

Both halves are normally full of **project-specific globals, `#define`
constants, and direct calls into project/HAL headers**
(`I3C\svc_i3c.h`, `common_hal\hal_inc.h`, `..\Common.h`, project message-code
`#define`s, `StaticDevInfo[...]`, `I3C_MasterAddI2cDevice(...)`, etc.).

**`SharedModules\*` lives at the project's top-most hierarchy and must never
`#include` anything from `EC\*` or `BMC\*`** — not even paths that look
"generic" (e.g. `common_hal\hal_inc.h`, or a project-local `I3C\svc_i3c.h`).
Moving a whole test into `SharedModules\Shared_*` therefore requires
systematically replacing **every** dependency on project code with one of
two mechanisms:

- **Params** (variables/constants) — see the sibling skill
  `Shared-Module-Host-convert-to-param`. Use for message codes, addresses,
  buffers, tables, and any other project-owned *data*.
- **Function pointers** (functions/HAL calls) — no prior skill covered this;
  this skill formalizes it. Use for anything that is a project *function
  call* the shared module cannot make directly (HAL driver calls, or any
  function only reachable via an EC/BMC-only include chain).

This skill runs **both** conversions, and runs the **whole process twice**
— once for the Host half of the test, once for the Core half — because a
test's Host and Core logic are separate translation units with separate
shared headers (`Shared_<X>\<X>_Host_SM.h/.cpp` and
`Shared_<X>\<X>_Core_SM.h/.cpp`) and separate wiring entry points
(`HostMain`/the Host test-entry function vs. `CoreGeneral.cpp`'s
`USER_AfterCoreInitialziation()`/init sequence).

## Preconditions / things to identify before editing

1. **Which shared module** owns this test family — the
   `SharedModules\Shared_<X>\<X>_Host_SM.h/.cpp` and
   `<X>_Core_SM.h/.cpp` pair (e.g. `Shared_I3C\I3C_Host_SM.*` /
   `I3C_Core_SM.*`). If the Core-side file doesn't exist yet or is an empty
   skeleton (`class Shared<X>TestParams { };` / `class <X>CoreCommon : public
   SharedModuleBase { public: static void initialize(); ... };`), that's fine
   — fill it in following this skill.
2. **The test function(s) to migrate** on each side:
   - Host: the function(s) called from the test dispatcher (often named
     `TEST_<Name>()`) in `HostTests.cpp`.
   - Core: the function(s) invoked from the matching `switch`-case(s) in
     `USER_Main_Core_Tests()` (`CoreGeneral.cpp`), defined in
     `CoreTests.cpp`.
3. **Every project dependency each half touches** — read the function body(s)
   fully and classify every non-local symbol used:
   - **Project-owned constant/`#define`/global variable/buffer/table** →
     needs a **param** (see Step A below).
   - **Project-owned function call** (including any HAL driver function only
     reachable via an EC/BMC include chain, e.g. `common_hal\hal_inc.h` →
     `ApiHalConfig.h` → `HAL_EXIST`-gated headers) → needs a **function
     pointer param** (see Step B below).
   - **Genuinely shared/external symbol** (safe to use directly, no
     conversion needed) — confirm by checking it is used **identically
     across multiple unrelated EC/BMC modules** and is not declared in any
     `EC\*`/`BMC\*` header. Typical examples already established in this
     codebase: `LogMessage`/`LogError`/`LogColor`/`LIGHT_BLUE`,
     `MSG_Data`/`MSG_TestCommand`/`MSG_RunTest`/`MSG_TestDone` (external
     `ARMM_CHATT.h`/`Test_if.h` SDK API), `BYTE`/`DWORD`/`bool`/standard C
     types. When unsure, grep the whole repo for the symbol: if it's declared
     under `EC\*`/`BMC\*`, it is **not** safe — convert it.
4. **Which project function(s) legitimately may include EC/BMC headers** and
   therefore can host the small wrapper functions the function-pointer params
   call through. This is normally the same `.cpp` the migrated function used
   to live in (`HostTests.cpp` / `CoreTests.cpp`), or another file in that
   project that already includes the needed headers.
5. **The one-time wiring entry point** for each side — the place that already
   sets (or should set) all params for this shared module once, before the
   test can run:
   - Host: the test's own entry function is usually fine (e.g. `TEST_Sort()`
     already wires several params right before calling the shared test) —
     or, if wiring should happen once for the whole module rather than
     per-test-invocation, `HostMain`'s init sequence.
   - Core: a dedicated `<X>_WireShared<X>CoreParams()` function (see the
     I3C precedent), called once from `USER_AfterCoreInitialziation()` in
     `CoreGeneral.cpp`.

## Step A — Convert params (variables/constants), both sides

Follow `Shared-Module-Host-convert-to-param` exactly, once per project-owned
data symbol identified in precondition 3, for **each** side independently
(the Host half and the Core half get their own params on their own
`Shared<X>TestParams` class — do not try to share one params instance across
Host and Core, they are different binaries/translation units):

1. Add `static bool setX(...)` / `static T getX()` to the relevant
   `Shared<X>TestParams` class in `<X>_Host_SM.h` or `<X>_Core_SM.h`.
2. Add a matching `inline static T _x = <default>;` private member (plus an
   `_xIsSet` bool if `T` is a scalar/value type with no natural null
   sentinel — pointers can just use `nullptr` as the "unset" sentinel).
3. Implement the setter (set-once: no-op + `LogError` + `false` if already
   set) and getter (`LogError` + safe default if not yet set) in the
   matching `.cpp`.
4. Replace every direct use of the project symbol inside the shared `.cpp`
   with the getter call.
5. Wire the setter from the project's one-time wiring point (precondition 5).

## Step B — Convert function calls (Rule 3: function-pointer params), both sides

For each project-owned **function** identified in precondition 3 (most
commonly HAL driver calls unreachable without EC/BMC-only includes):

1. **Decide the function-pointer signature** using only portable types
   (`BYTE`, `DWORD`, `bool`, pointers to those, standard C types) — never a
   project-only type (`I3C_MODULE_T`, `UINT8`, `DEFS_STATUS`, project enums
   like `TCMD_ENUM`, etc.) in the signature itself. If the original function
   returns/consumes a project type, the **wrapper** (step 3 below) does the
   cast; the pointer type stays portable.

2. **Add to the shared `*Parameters` class** (mirroring the existing
   `setI3cStaticSlaveAddrLookup`/`getI3cStaticSlaveAddr` and
   `setI3cMasterAddI2cDeviceFn`/`addI3cMasterI2cDevice` precedent in
   `I3C_Core_SM.h`):
   ```cpp
   static bool setXFn(bool(*fn)(DWORD arg1, BYTE arg2));
   static bool callX(DWORD arg1, BYTE arg2);   // "invoke" method, NOT a getter
   ```
   with a private member:
   ```cpp
   inline static bool(*_xFn)(DWORD, BYTE) = nullptr;
   ```
   Naming convention: the setter is always `setXFn`/`setXLookup` (ends in
   `Fn`/`Lookup` to distinguish from a data setter); the invoke method uses a
   plain verb describing the action (`addI3cMasterI2cDevice`,
   `readI3cMasterSdr`, `getI3cStaticSlaveAddr`) — it is *not* named
   `getXFn` because it invokes rather than returns the pointer.

3. **Implement in the shared `.cpp`**:
   - Setter: set-once (`nullptr` check), `LogError` + `false` if already set.
   - Invoke method: if the stored pointer is `nullptr`, `LogError` + a safe
     default return (`false`/`0`); otherwise call through it and return the
     result. Never dereference a possibly-unset pointer without this guard.

4. **Replace the direct call inside the shared `.cpp`** (e.g.
   `I3C_MasterAddI2cDevice(...)`) with the invoke method
   (`I3cCoreCommon::params.addI3cMasterI2cDevice(...)`).

5. **Add a small `static` wrapper function in the project file** that
   legitimately includes the needed EC/BMC headers (precondition 4),
   matching the portable pointer signature exactly and doing the real call
   + any type casting/adaptation:
   ```cpp
   static bool I3C_MasterAddI2cDeviceWrapper(DWORD moduleIdx, BYTE i2cStaticAddr)
   {
       DEFS_STATUS status = I3C_MasterAddI2cDevice((I3C_MODULE_T)moduleIdx, (UINT8)i2cStaticAddr, 0, NULL);
       return status == DEFS_STATUS_OK;
   }
   ```
   Preserve the original function's exact behavior/semantics (including any
   pre-existing quirky truthiness conversions) — don't "fix" unrelated
   behavior while doing this mechanical conversion.

6. **Wire the setter** from the project's one-time wiring point (precondition
   5), passing the wrapper function by name:
   ```cpp
   I3cCoreCommon::params.setI3cMasterAddI2cDeviceFn(I3C_MasterAddI2cDeviceWrapper);
   ```

## Step C — Run the whole process twice (Host, then Core)

Because Host and Core are separate binaries with separate shared headers:

1. Do Step A + Step B completely for the **Host** half first
   (`<X>_Host_SM.h/.cpp`, wiring in `HostTests.cpp`/`HostMain`). Build the
   Host project/solution config and confirm zero errors/warnings.
2. Do Step A + Step B completely for the **Core** half
   (`<X>_Core_SM.h/.cpp`, wiring in `CoreTests.cpp` +
   `USER_AfterCoreInitialziation()` in `CoreGeneral.cpp`). Build the Core
   project/solution config (ARM/armclang target — check
   `CoreCompilation.props`/the solution's valid configs, e.g.
   `Release|Win32`, NOT `HostDebug|Win32`) and confirm zero errors/warnings.
3. Update the call sites that used to invoke the old project-local
   function(s) directly (the Host test dispatcher call, and the
   `switch`-case(s) in `USER_Main_Core_Tests()`) to call the new shared
   methods instead (e.g. `I3cCoreCommon::sharedHostI3cChipAddI2cDevice()`).
4. Remove the old now-dead project-local function bodies/prototypes once
   confirmed (via repo-wide grep) that nothing else calls them.

## Verify (do this for BOTH sides before considering the migration done)

- **Grep the shared `.h`/`.cpp`** for:
  - Any `#include` of a path containing `EC\` or `BMC\`, or any bare
    project-local header (`common_hal\hal_inc.h`, `I3C\svc_i3c.h`,
    `ApiHalConfig.h`, `..\Common.h`, `CoreGeneral.h`, `CoreTests.h`, etc.) —
    must be **zero** matches.
  - Any remaining direct reference to the converted project constants/types
    (project `#define` names, `byte`/`word`/project typedefs, project enums
    like `TCMD_KEYPRESS`, project HAL types like `I3C_MODULE_T`/`UINT8`/
    `DEFS_STATUS`) — must be **zero** matches (log-message string literals
    that merely *mention* a name are fine).
- **Build both**: the Host solution config (e.g. `HostDebug|Win32`) and the
  Core solution config (ARM target, e.g. `Release|Win32`) — both must show
  0 warnings, 0 errors.
- Confirm (grep) the old project-local function(s) that used to hold this
  test's logic are either deleted or reduced to a thin wrapper, with no
  leftover duplicate logic.

## Worked example (I3C: `HOST_I3C_CHIP_*` test family)

- **Host side**: `I3cCommon::_sharedTestI3cSort()`
  (`SharedModules\Shared_I3C\I3C_Host_SM.cpp`) — converted
  `_i3cVoltageTable`, `_i3cVoltageLevelSupportTable`, `_i3cTransmitDataBuff`
  (Step A, pointer params), and `SCT_CORE_USER_BA`, `I3C_NUM`,
  `I3C_I2C_SLAVE_INDEX` (Step A, scalar params with `BYTE`/`DWORD` +
  `IsSet` flags). Wired in `EC\Modules\I3C_Ramon\Host\HostTests.cpp::TEST_Sort()`.
- **Core side**: `I3cCoreCommon::sharedHostI3cChipAddI2cDevice()` /
  `sharedHostI3cChipReadAndCompareI2cData()` / `sharedHostI3cChipWriteI2cData()`
  (`SharedModules\Shared_I3C\I3C_Core_SM.cpp`) — migrated from
  `new_Host_I3C_chip_add_I2C_device()` / `new_Host_I3C_chip_read_and_compare_I2C_data()` /
  `Host_I3C_chip_write_I2C_data()` in `EC\Modules\I3C_Ramon\Core\CoreTests.cpp`.
  - Step A params: `I3C_NUM`/`I3C_I2C_STATIC_ADDR`/`I3C_I2C_SLAVE_INDEX`
    (message codes, `BYTE`), `SCT_CORE_USER_BA` (`DWORD`), `TCMD_KEYPRESS`
    (`BYTE`).
  - Step A function-pointer-as-lookup: `setI3cStaticSlaveAddrLookup(BYTE(*)(DWORD,DWORD))`
    wired to a small `GetStaticDevInfoSlaveAddr()` adapter in `CoreTests.cpp`
    (keeps `StaticDevInfo[...]`'s array shape out of the shared header).
  - Step B function pointers: `setI3cMasterAddI2cDeviceFn`,
    `setI3cMasterSdrReadFn`, `setI3cMasterSdrWriteFn`, wired to
    `I3C_MasterAddI2cDeviceWrapper`/`I3C_MasterSdrReadWrapper`/
    `I3C_MasterSdrWriteWrapper` (static functions in `CoreTests.cpp`, which
    legitimately includes `common_hal\hal_inc.h` etc.), each casting to
    `I3C_MODULE_T`/`UINT8`/`DEFS_STATUS` internally and returning a plain
    `bool`.
  - All wiring centralized in `I3C_WireSharedI3cCoreParams()`
    (`CoreTests.cpp`), called once from
    `USER_AfterCoreInitialziation()` in `CoreGeneral.cpp`.
  - The 3 `switch`-cases in `USER_Main_Core_Tests()` now call
    `I3cCoreCommon::sharedHostI3cChip*()` instead of the old project-local
    functions.
- Verified: `MSBuild I3C_Ramon.sln /t:Host /p:Configuration=HostDebug /p:Platform=Win32`
  and `MSBuild I3C_Ramon.sln /t:Core /p:Configuration=Release /p:Platform=Win32` —
  both 0 warnings/0 errors. Grep-confirmed zero `EC\*`/`BMC\*` includes and
  zero remaining project-type references in `I3C_Core_SM.h/.cpp`.

## Common pitfalls

- **Leaking project types through a function-pointer signature** — if the
  pointer type itself uses `I3C_MODULE_T`/`UINT8`/a project enum, the shared
  header still can't compile without an EC/BMC include. Always push the
  cast into the project-side wrapper, keep the pointer signature portable
  (`BYTE`/`DWORD`/`bool`/plain pointers only).
- **"It builds, so it must be fine"** — a shared `.cpp` that copies the
  project's entire include list to make the direct calls resolve *will*
  compile (this was the exact mistake this skill exists to prevent), but it
  violates the architecture. Builder success alone doesn't prove the
  conversion is correct — always also grep-verify no EC/BMC includes/types
  remain.
- **Confusing "shared" with "reachable from `-I$(ProjectDir)`"** — a header
  is only safe to include from `SharedModules\*` if it lives in a genuinely
  top-level shared location (`SharedModules\`, `ValidationCommon\`,
  `Objects\Common\HAL\`, external SDK dirs like `TESTEC_DIR`), never because
  the build system's include-path flags happen to make an EC/BMC header
  resolve for one particular consuming project.
- **Doing only one side** — a test's Host half and Core half are easy to
  forget about each other; always re-check precondition 2/3 for **both**
  halves before considering the migration complete, even if the user's
  request only explicitly mentions one side.
- **Skipping the "genuinely shared" classification step** — not everything
  needs conversion. Logging (`LogMessage`/`LogError`/`LogColor`) and the
  JTAG messaging API (`MSG_Data`/`MSG_TestCommand`/`MSG_RunTest`) are
  external SDK APIs used identically everywhere; converting them into params
  would be unnecessary churn. Only convert symbols actually declared in an
  `EC\*`/`BMC\*` header.
