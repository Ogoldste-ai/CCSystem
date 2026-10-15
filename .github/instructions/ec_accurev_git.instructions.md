---
description: 'ec_accurev_git work repo: layout of EC/BMC/TPM/SharedModules/ValidationCommon, BMC multi-core build model, and the Booter bootloader module'
applyTo: 'ec_accurev_git/**'
---

# ec_accurev_git — firmware & validation work repo

Nuvoton validation/firmware repository (GitLab:
`validation/ec_accurev_git`), consumed by CCSystem as a git submodule. This
is the **work repo** — do Copilot-tooling development elsewhere (see
`.github/copilot-instructions.md`).

Reviews here are usually **GitLab merge requests**: use the `gitlab-review`
MCP tools (`resolve_project`, `get_merge_request`,
`list_merge_request_changes`, `get_merge_request_raw_diff`,
`create_merge_request_diff_comment`) rather than guessing from the working
tree.

## Repo layout

```
Directory.Build.props        Root MSBuild props, applies to everything
BMC/                         Baseboard Management Controller (multi-core SoC)
EC/                          Embedded Controller
  Common/ Modules/ SIO/ Patterns/ Delivery/ SWQA/ "Doc Control"/
  CoreCompilation.props  CoreCompilationPrivate.props
  HalRuntimeCoreCompilation.props
TPM/                         TPM product line (Common/ Modules/ "Doc Control"/)
SharedModules/               Cross-product modules: GPIO, eSPI_BM, Shared_TWD,
                             VCT, ModuleVersion, SharedChipAPI, SharedExample
                             (exposed as .vcxitems shared projects)
ValidationCommon/            Host+core validation framework shared by all
                             products: ArgumentParser, LoggerOrganizer,
                             *Interface.cpp (GPIO/SVB/TEB/Power/Reset/MSWC...),
                             ValidationMain, TestReg_API, magic_enum.hpp
                             → ValidationCommonHost.vcxitems /
                               ValidationCommonCore.vcxitems
Objects/                     Build output (BMC/ Common/ EC/ TPM/)
```

Module solutions consume shared code via **`.vcxitems` shared projects**, not
static libs. A change to a `.vcxitems` file affects every solution importing
it — check the blast radius before approving.

## BMC — multi-core model

A single module solution compiles the same module for several cores at once.

| Common items          | Per-module folder   | Core  | Arch  | Purpose                     |
|-----------------------|---------------------|-------|-------|-----------------------------|
| `CommonCoreA35`       | `core_a35/`         | A35   | ARM   | Main BMC processor          |
| `CommonCoreM7`        | `core_m7/`          | M7    | ARM   | AMP co-processor            |
| `CommonCoreMCU`       | `core_mcu_riscv/`   | MCU   | RISC-V| Caliptra MCU bootloader     |
| `CommonCoreCPTRA`     | `core_cptra_riscv/` | CPTRA | RISC-V| Caliptra security subsystem |
| `CommonHost`          | `host/`             | Win32 | C++   | Host-side test harness      |

Other shared items: `CommonCores` (multi-core utils), `CommonBooter`
(bootloader state machine + OTP/Straps), `CommonHal` (register/init HAL),
`CommonRustLib` (`#![no_std]` Rust exposed to C++ via `extern "C"`).

`BMC/Common/` also holds `regs` (`tavor_regs.h`, `arbel_tip_cop_regs.h`),
`apis`, `tip_cop`, `validation`, `ttl_scripts`, and the per-core source
folders (`a35`, `m7`, `mcu_riscv`, `cptra_riscv`, `host`, `core`).

`BMC/Modules/` has ~28 modules (AMP, APB2SIB, Booter, Caliptra_Subsystem,
CoresCommunication, CR_UART, ddr, ECE, FUI, gdma, host_serial_port, KBCI,
KCS, MFT, PCIeEP, PCIeRC, PSPI, PWM, Resets, SIOX, TWD, VCD, ...).
**`Modules/BMC_template` is the reference skeleton** — new modules and
layout review should be diffed against it.

Per-module shape (canonical):

```
<Module>/
  <Module>.sln            One project per core + host + rust_lib, and the
                          Common*.vcxitems / ValidationCommon*.vcxitems refs
  ChipTarget.props        Derives CoreProcessor/CoreName/ChipType from the
                          *project file name* (contains 'a35'/'m7'/
                          'mcu_riscv'/'cptra_riscv')
  Common.h  template_defs.h  ModuleMemoryConfiguration.h
  core_<x>/   CoreMain.cpp CoreTests.cpp CoreTools.cpp <proj>.vcxproj [gcc_process.ld]
  host/       HostMain.cpp HostTests.cpp HostTools.cpp HostGeneral.cpp
              ArgumentModuleDefinitions.cpp TestInfo.cpp [unit_test/] [Tools/]
  rust_lib/   Cargo.toml Cargo.lock src/lib.rs src/rust_lib.h rust_lib.vcxproj
```

### Building BMC

Use the VS Code tasks driven by `BMC/.vscode/BmcModuleTask.ps1` (helpers in
`BmcModuleUtilities.ps1`): `Build BMC Module (Selected Win32)`,
`Build All BMC Modules (Selected Win32)`, `Build All BMC Modules Clean`,
`Clear BMC/All Module Artifacts`. **Do not invoke MSBuild directly.**

- Tool paths: `BMC/.vscode/settings.json` (`bmc.paths.*`).
- Toolchain/compile flags: `BMC/CoreCompilation.props` (Keil armclang/armlink,
  per-core CPU flags).
- Configurations are **per-core, not uniform**: `Release`, `A35_Release`,
  `M7_Release`, `MCU_Release`, `CPTRA_Release`. Solution configs map to
  underlying per-project configs (e.g. `A35_Release|Win32` →
  `A35_DEBUG_SVB|Win32`).
- `BuildAllModules` **silently skips** modules that don't support a
  configuration — read the log, don't assume coverage.
- `A35_Release` forces a clean before building.

`BMC/AGENTS.md` is the authoritative in-repo version of the above; follow it
and keep it in sync if the build model changes.

## Modules/Booter — Tavor MCU bootloader

Booter follows the template exactly (4 cores + host + rust_lib). Its real
content lives in the shared `BMC/Common/common_booter/`:

```
common_booter/
  boot_flow_state_machine.{h,cpp}   StateMachine class: STATE enum,
                                    fsm_table of std::function<STATE()>,
                                    add_state(), run(), per-state
                                    <X>_state() / <X>_actions() /
                                    check_jump_to_state_<X>() functions
  OTP/OTPImage/, Straps/StrapsImage/, ImageGenerate/
  json/        CaliptraSS_OTP / Novoton_OTP / Straps  *_structure + *_values
  Builder/     main.py + generate_*.py + schema*.json  (JSON → C++ generator)
  SandBox/     GENERATED C++ (enums, structs, vector data) — do not hand-edit
```

Key facts to keep in mind when reviewing Booter changes:

- **The bootloader FSM currently runs on the HOST as a reference model**, not
  on the MCU. `Modules/Booter/host/HostTests.cpp::TEST_StateMachine_init()`
  constructs the `StateMachine` and registers all states;
  `core_mcu_riscv/CoreMain.cpp` is still a `while(1)` stub. Don't assume an
  FSM change is exercised on silicon/emulation.
- `BMC/Docs/Tavor/tavor_mcu_bootloader_state_machine.md` (plus
  `tavor_mcu_bootloader_hw_resources.md` and `Docs/Tavor/tavor-spec.md`) is
  the **source of truth** for the state enum, handlers, and FSM registration.
  Regenerate via the `generate_bootloader_*` prompts in
  `BMC/.github/prompts/` instead of hand-editing. States named `TBD_*` are
  intentionally excluded from stub/call generation.
- Adding a state means touching **three places consistently**: the `STATE`
  enum (before `NUM_OF_VALID_STATES`, which sizes `fsm_table`), the
  handler/actions declarations in the header + definitions in the `.cpp`, and
  the `add_state(...)` registration in `HostTests.cpp`. A missing
  registration is caught only at runtime by `check_fsm_table_validity()`.
- `Common/CommonBooter.vcxitems` runs the Python generator from a
  `BeforeTargets="ClCompile"` target with **no `Inputs`/`Outputs`** → no
  MSBuild incrementality and a hard dependency on `python` being on PATH.
  Generated `SandBox/*` files are both committed and regenerated, so expect
  large/noisy diffs and watch for drift.

## Review checklist for this repo

- Does a new/changed BMC module still match `Modules/BMC_template`
  (per-core folders, `ChipTarget.props`, host + rust_lib)?
- Does the `.sln` register every core project in **all** the configurations it
  claims to support?
- Did a `.vcxitems` change get validated against every consuming module?
- Bootloader change: spec doc updated, enum/handlers/`add_state` all in sync,
  generated `SandBox/*` regenerated rather than hand-edited, no leftover
  `TBD_NEXT_STATE` on a release path.
- Binaries (`*.exe`, e.g. `Booter/host/Tools/EVB_TOOLS/`) and large generated
  files: flag new ones rather than letting them grow.
- Rust is `no_std` and its panic handler just loops forever — errors will not
  surface. Don't rely on panics for diagnostics.

## Related tooling

- `BMC/.github/prompts/`: `create-new-file`,
  `generate_bootloader_state_enum`, `generate_bootloader_add_state_calls`,
  `generate_bootloader_state_stubs`,
  `generate_tavor_bootloader_state_machine_doc`, `tavor-spec-agent`.
- `pdftomd-rag` MCP/skill: query indexed hardware spec PDFs (Tavor NPCM9mnx,
  Arbel NPCM845x) for registers, bitfields, reset sequences.
- `teb` MCP: TEB3 board GPIO/FPGA access for bring-up and validation.
- `veloce-operator` agent: drive the Tavor Veloce emulator (emulation, chip
  control, HW trace, memory download, JTAG/OpenOCD).
