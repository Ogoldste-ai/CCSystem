---
name: local-building-bmc-modules
description: Use when compiling a BMC module or BMC_template in ec_accurev_git with a Release, A35_Release, M7_Release, MCU_Release, or CPTRA_Release solution configuration.
---

# Build BMC modules in ec_accurev_git

1. Read `BMC\AGENTS.md`. Confirm the checkout, module, Win32 solution
   configuration, and required targets. Check the module's `.sln` and Git
   status. Do not invoke MSBuild directly.
2. From the firmware checkout, use the repository's incremental build task.
   `A35_Release` forces module artifact cleanup and needs explicit approval.
   Do not add upfront cleanup or delete `.vs`.

   ```powershell
   & .\BMC\.vscode\BmcModuleTask.ps1 -Action BuildModuleConfiguration -WorkspaceFolder (Resolve-Path .\BMC).Path -Module Booter -Configuration Release
   ```

   Replace `Booter` and `Release` with the confirmed values. Save the complete
   log and capture `$LASTEXITCODE` immediately. Inspect post-build Git status
   for generated changes. Do not run the built binaries or hardware tests.
3. Report a full build pass only with exit code 0, the `Build Complete`
   summary, and nonempty outputs for the selected targets that were produced
   during the build or explicitly verified up to date. An old executable on
   disk is not proof.

## Incremental `objs.txt` diagnostics

- `Could Not Find ...\objs.txt` from the pre-build delete is harmless by itself.
- `cannot find @..\objs.txt` or `...objs.txt: No such file or directory` from a
  core linker is a known incremental build issue: the pre-build deletes the
  generated response file and the incremental compile may not recreate it.
  The corresponding missing `.elf`, `collect2`, and `MSB3073` messages are
  follow-on errors only when the full log ties them to that same core failure.
- **For host-only changes**, treat this known core issue as a non-blocking
  warning for code review when **all** of the following hold:
  - No changed input affects a core build, and fresh core images are not required
    for the requested check.
  - Every failed target is a core with the confirmed missing response-file
    signature; there are no independent errors or unexplained failed targets.
  - The selected Win32 host target independently passed for the same checkout,
    configuration mapping, and source state. Verify its nonempty output and
    use a successful host-target build or explicit build evidence that it was
    up to date. Do not infer this from an existing `Host.exe` alone.

  Report: **Host build verified; ready for code review. The solution build
  exited nonzero because the affected cores did not relink (`objs.txt`).
  Runtime tests were not run.** Preserve the real solution exit code. Do not
  claim a full build pass or fresh core images, retry, or clear artifacts just
  to remove this warning.
- If a core is required, a failed target is unexplained, or the host result
  cannot be verified, report the blocker. If fresh core images are required
  and the only blocker is the known response-file issue, get explicit approval
  before using `local-clearing-bmc-module-artifacts` for this module only,
  retaining `.vs`, and running the build task again once.
