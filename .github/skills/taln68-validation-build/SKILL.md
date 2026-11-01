---
name: taln68-validation-build
description: Configure the four per-user validation build flags on taln68 and run the Nuvoton sandbox build with explicit approval.
---

# Build Nuvoton validation artifacts on taln68

Trigger phrase: "build validation artifacts on taln68"

## Purpose

Build `nuvoton_tests/Sandbox` in
`~/tavor/nuvoton-caliptra-mcu-sw-validation` using the four flags in
`nuvoton_tests/users/<remote-user>.sh`. Keep the selected values in that
profile after the build. This skill does not run validation tests.

## Assistant workflow

1. Use the saved `taln68` SSH alias and the SSH-command skill's transport,
   output, and approval rules. Verify that `taln68` exists in the local SSH
   config; use `BatchMode=yes` and `ConnectTimeout=10`. Show the alias and
   exact remote command before each execution. Do not use `sudo`.
2. Inspect the remote repo and resolve its current user with `id -un`; confirm
   that `nuvoton_tests/validation_build_sources/main.sh` and
   `nuvoton_tests/users/<remote-user>.sh` exist. Read the four current values
   from the profile and check `git status --short` for that profile and
   `platforms/nuvoton-veloce/rom/src/tvr_rom_version.rs`. Do not overwrite
   unexpected changes or run the build if the ROM version file is modified:
   stage 00 checks that file out from `HEAD`.
   Before changing the profile or clearing `Sandbox`, compare stage 03's
   `TESTS_DIR` with the source directory selected by
   `platforms/nuvoton-veloce/runtime/build.rs`. Confirm that the directory
   exists and contains `otp_dump.rs` and `stage_7_test.rs`; stop if the
   paths disagree or either test is absent.
3. Ask the user for an explicit `0` or `1` for **each** flag, displaying the
   existing values and these effects:

   | Flag | `0` | `1` |
   | --- | --- | --- |
   | `USE_PRODUCTION_MCU_ROM` | Keep locally built MCU ROM | Replace MCU ROM hex with frozen release ROM |
   | `USE_PRODUCTION_MCU_ROM_FAST` | Regular frozen ROM if selected | Super-fast frozen ROM if selected |
   | `USE_PRODUCTION_MCU_FW` | Keep locally built default flash image | Replace default flash image with frozen firmware |
   | `USE_NUVOTON_CALIPTRA_BUILD` | Keep locally generated Caliptra ROM files | Replace Caliptra ROM files with frozen deliverables |

   The fast flag also chooses the stage-7 test and default test timeout,
   even when the MCU ROM override is disabled. Only accept `0` or `1`;
   do not assume that the existing values are what the user wants.
4. Explain the exact effects of this build: it removes and recreates
   `nuvoton_tests/Sandbox`, writes the tracked user profile, stamps and
   checks out the ROM-version file, runs all nine stages, and stage 08
   downloads/verifies the frozen release even when overrides are off.
   Display the proposed old-to-new values and the precise remote commands.
   Obtain explicit approval before overwriting the profile or running the
   build. A request to create this skill is not approval to run it.
5. On approval, validate the four values and confirm that each assignment
   occurs exactly once in the remote profile. Update only those assignments
   (for example, anchored `sed -i -E` substitutions); do not overwrite the
   whole profile. Read the values back, show `git diff --` for the profile,
   and stop if they differ from the requested values. Keep the new values
   after completion, including if the build fails.
6. Run the build from the repo root in a login Bash shell (`bash -lc`) so
   `cargo` is available over non-interactive SSH. Redirect stdin from
   `/dev/null` so the interactive selector does not reopen. A full build
   can take a long time: keep SSH attached and capture its exit status,
   stdout, and stderr; do not impose a 30-second remote timeout on the
   build. If connection loss makes the result uncertain, inspect the
   remote process and logs rather than claiming success or starting a
   second build. Never run concurrent builds in this checkout.
7. A zero exit status alone is insufficient. Check `Sandbox/release`,
   `Sandbox/flash`, and `Sandbox/otp`; verify nonempty `.bin` and `.hex`
   flash images for every non-default test source in the directory checked
   in step 2, including `otp_dump` and `stage_7_test`. Reject literal
   `flash_image_*.bin` or `flash_image_*.hex` filenames. Report the relevant
   stage logs under `nuvoton_tests/validation_build_sources/logs`. On
   failure, report the failing stage, exit status, and log without silently
   retrying or running tests.

## Manual bash workflow

Run these commands in a local Bash terminal; after the first command the
remaining commands run in the `taln68` shell:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 taln68
```

Opens a key-authenticated remote shell without an SSH password prompt.

```bash
cd ~/tavor/nuvoton-caliptra-mcu-sw-validation
cfg="nuvoton_tests/users/$(id -un).sh"
git status --short -- "$cfg" platforms/nuvoton-veloce/rom/src/tvr_rom_version.rs
grep -E '^(USE_PRODUCTION_MCU_ROM|USE_PRODUCTION_MCU_ROM_FAST|USE_PRODUCTION_MCU_FW|USE_NUVOTON_CALIPTRA_BUILD)=' "$cfg"
```

Selects the checkout, identifies your user profile, and shows existing
changes and flag values. Stop if the ROM version file has local edits.

```bash
grep -n '^TESTS_DIR=' nuvoton_tests/validation_build_sources/03_build_fw_variants.sh
grep -n -A5 'let tests_dir' platforms/nuvoton-veloce/runtime/build.rs
tests_dir=platforms/nuvoton-veloce/runtime/src/nuvoton_tests/tests
test -d "$tests_dir" && test -f "$tests_dir/otp_dump.rs" && test -f "$tests_dir/stage_7_test.rs"
```

Compares the variant builder's input path with the runtime's actual test
source path and checks the two variants required by the test menu. Stop
before editing flags or building if the paths disagree or this check fails.

```bash
rom=0 fast=1 fw=1 caliptra=1
for value in "$rom" "$fast" "$fw" "$caliptra"; do
    [[ "$value" == 0 || "$value" == 1 ]] || { echo "Flags must be 0 or 1" >&2; exit 1; }
done
for flag in USE_PRODUCTION_MCU_ROM USE_PRODUCTION_MCU_ROM_FAST USE_PRODUCTION_MCU_FW USE_NUVOTON_CALIPTRA_BUILD; do
    [[ $(grep -Ec "^${flag}=[01]$" "$cfg") == 1 ]] || { echo "Missing or duplicate flag: $flag" >&2; exit 1; }
done
```

Replace the example values with your four chosen values in the table's order.
Checks that each is `0` or `1` and occurs exactly once in the profile;
invalid values or missing/duplicate assignments stop the remote shell.

```bash
sed -i -E \
    -e "s/^USE_PRODUCTION_MCU_ROM=.*/USE_PRODUCTION_MCU_ROM=$rom/" \
    -e "s/^USE_PRODUCTION_MCU_ROM_FAST=.*/USE_PRODUCTION_MCU_ROM_FAST=$fast/" \
    -e "s/^USE_PRODUCTION_MCU_FW=.*/USE_PRODUCTION_MCU_FW=$fw/" \
    -e "s/^USE_NUVOTON_CALIPTRA_BUILD=.*/USE_NUVOTON_CALIPTRA_BUILD=$caliptra/" \
    "$cfg"
git diff -- "$cfg"
```

Updates only the four assignments and shows the profile change for review.

```bash
bash -lc "cd ~/tavor/nuvoton-caliptra-mcu-sw-validation && bash nuvoton_tests/validation_build_sources/main.sh </dev/null"
```

Uses the login shell's Cargo PATH and runs the full build with the saved
profile, without reopening the interactive selector. This clears the old
sandbox; run it only after reviewing and approving that effect. Do not
launch another build while this one is running.

```bash
find nuvoton_tests/Sandbox/release nuvoton_tests/Sandbox/flash nuvoton_tests/Sandbox/otp -maxdepth 1 -type f
flash_dir=nuvoton_tests/Sandbox/flash
for rs in "$tests_dir"/*.rs; do
    name="${rs##*/}"
    name="${name%.rs}"
    case "$name" in default|mod) continue ;; esac
    test -s "$flash_dir/flash_image_${name}.bin" &&
    test -s "$flash_dir/flash_image_${name}.hex" || { echo "Missing variant: $name" >&2; exit 1; }
done
test ! -e "$flash_dir/flash_image_*.bin" && test ! -e "$flash_dir/flash_image_*.hex" ||
    { echo "Literal wildcard flash image found" >&2; exit 1; }
```

Lists the resulting ROM, flash, and OTP files and checks that every named
firmware variant exists. Literal wildcard filenames indicate that stage
03 did not find its source directory, even if `main.sh` exited successfully.

## Notes / approval

The four settings live in a tracked per-user profile, not in command-line
options to `main.sh`. The normal interactive build opens
`validation_build_sources/user_selection.sh` and saves changes to that
profile; non-interactive SSH skips the selector. Stage 03 compiles a separate
runtime and matching signed manifest for each validation firmware variant.
Stage 08 overrides selected files in the sandbox but does not undo the
earlier local builds. Do not run the test menu as part of this skill.
