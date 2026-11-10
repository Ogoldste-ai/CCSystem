# Booter synchronization: controller integration

This guide is for Copilot or automation on the external computer controlling a
single standard `nuvoton_tests` UART/run-all scenario. It documents the existing
interface; it does not authorize an emulator run.

## 1. How to use the configuration

There are three roles:

| Role | Responsibility |
| --- | --- |
| Controller | Starts the SSH command, waits for readiness, performs the external action, and sends completion. |
| Runner host | Linux machine with this checkout, configured `nuvoton_tests/USER.sh`, and the required existing artifacts. |
| Veloce machine | Emulator target selected by the wrapper's optional first argument or runner configuration. |

Before launching, confirm exclusive emulator use with the owner. The shared
runner performs cleanup on both configured Veloce hosts, clears shared
locks/logs, uploads artifacts, and modifies release Tcl. Timestamped snapshots
do not isolate those operations from other sessions. Do not launch a test just
to inspect this interface.

From the controller, start one non-interactive SSH command:

```bash
ssh -T runner-host \
  'cd /path/to/checkout &&
   DRIVER_EXTRA_ARGS=--booter_sync \
   bash nuvoton_tests/validation_tests/veloce_test_ccft_shiny_day_hw_test_unlocked.sh veloce-machine'
```

Replace `runner-host`, `/path/to/checkout`, and `veloce-machine` with the approved
configuration. The example wrapper selects its own ROM/flash/OTP scenario.
Other wrappers must use the standard shared runner in normal UART/run-all mode.
Omit the final machine argument to use the runner's configured default.

**Pass `--booter_sync` through `DRIVER_EXTRA_ARGS`, not as a wrapper argument.**
For the example wrapper, putting `--booter_sync` in its first positional argument
would treat it as the Veloce machine name.

Keep the command's stdin open and continuously consume both stdout and stderr.
For automation, use an SSH API/channel or an SSH subprocess that supports
streaming output and writing to stdin. Do not wait for the SSH command to exit
before looking for readiness.

Controller sequence:

```text
Start the SSH command with writable stdin and streaming stdout/stderr.
Consume complete stdout lines and drain stderr independently.
Wait for the exact stdout line BOOTER_SYNC_READY.
Perform the external action.
Only if that action succeeds, write ASCII BOOTER_SYNC_DONE plus LF to stdin.
Flush stdin, then continue consuming output until the command finishes.
Inspect the final process status and the selected scenario's fresh logs.
```

If the external action fails, do not send DONE. Cancel the owned run or close
its input before DONE; the synchronization gate must not be released.

Do not use `ssh -n`, a prewritten DONE pipe/here-string, a detached run, or a
second SSH command to resume. The original open SSH command owns the handshake;
there is no reconnect, status-file, or separate resume-command interface.

Sources: [example wrapper](veloce_test_ccft_shiny_day_hw_test_unlocked.sh#L16-L57),
[mode checks and reserved stdin](veloce_test_internal.sh#L64-L85), and
[shared preparation](veloce_test_internal.sh#L252-L342).

## 2. Supported arguments and configuration

| Setting or argument | Where to supply it | Meaning and effective default |
| --- | --- | --- |
| `--booter_sync` | `DRIVER_EXTRA_ARGS` | Boolean opt-in, with no following value. Omit it for ordinary execution. |
| `MACHINE` | Optional first wrapper argument | Target Veloce hostname; defaults to `USER_VELOCE_PRIMARY_MACHINE`. It is not the runner SSH hostname. |
| `--load-timeout SECS` | `DRIVER_EXTRA_ARGS` | Initial emulator-connection limit. Shared runner default: `300`. |
| `--caliptra-start-timeout SECS` | `DRIVER_EXTRA_ARGS` | Startup loading limit and synchronized test-setup acknowledgement limit. Shared runner default: `3600`. |
| `--run-timeout SECS` | `DRIVER_EXTRA_ARGS` | Monitoring limit after DONE. Shared runner selects `43200` when `USE_PRODUCTION_MCU_ROM_FAST` is `0` or unset, otherwise `3600`, unless a run-specific timeout overrides it. |

These are defaults for the wrapper/shared-runner path, not necessarily the
defaults shown by invoking the Python driver directly. Extra arguments are
appended after the shared runner's arguments, so an explicit timeout option
overrides the supplied value. Use positive integer seconds for timeout values.

Multi-option example, from the runner checkout:

```bash
DRIVER_EXTRA_ARGS="--booter_sync --load-timeout 300 --caliptra-start-timeout 3600 --run-timeout 43200" \
  bash nuvoton_tests/validation_tests/veloce_test_ccft_shiny_day_hw_test_unlocked.sh
```

The current forwarding code splits `DRIVER_EXTRA_ARGS` on whitespace. Outer
shell quotes keep the environment assignment together, but quotes inside its
value do not preserve arguments containing spaces.

**Waiting for DONE is indefinite while connected.** `--run-timeout` starts
governing monitoring only after synchronization; it does not limit the DONE
wait. `--caliptra-start-timeout` limits setup before READY, not the external
action after READY.

Normal UART/run-all mode and log paths are already supplied by the shared
runner; do not add `--run-all` or log-path arguments merely to enable this
feature. Keep image selection in the wrapper and runner configuration. Python
image-name/logging arguments are not a replacement for preparing uploaded
ROM/flash/OTP inputs.

Incompatible with synchronization: fixed-time mode, `SETUP_ONLY=1`,
`FIXED_RUN_MODE=1`, `--cc-msg`, `--seq-pattern`, and `--check-pc-fiu3`.
Campaign-level synchronization and legacy wrappers that bypass the shared
runner are outside this interface.

Sources: [timeout selection](veloce_test_internal.sh#L59-L65),
[driver argument construction](veloce_test_internal.sh#L517-L551), and
[driver options and compatibility](veloce_vsim_driver.py#L583-L630).

## 3. What to expect back

### Readiness and completion

Stdout contains human-readable preparation/simulator logs and one standalone,
flushed readiness event:

```text
BOOTER_SYNC_READY
```

Match the complete line, not a substring in logs, source previews, or the
internal Tcl setup marker. Preserve output while waiting for that event;
stderr is a separate diagnostic stream.

READY means test memory/setup work, the existing initial `run 50ns`, strap
sampling, and `cc_msg on` have completed. The simulator is idle immediately
before the final `run -all`. It does not mean no simulated time has elapsed,
that firmware passed, or that the SSH command has finished.

After the external action succeeds, send exactly these ASCII bytes on the same
command's stdin:

```python
b"BOOTER_SYNC_DONE\n"
```

This notation represents the bytes to write: the last byte is LF, not a literal
backslash and `n`. Do not send CRLF, quotes, arbitrary Tcl, extra lines, or DONE
before READY. The driver accepts fragmented delivery of the valid byte sequence.

After accepting DONE, the driver issues `run -all` once and enters the existing
UART monitor. There is no separate public DONE-acknowledgement event.

Example transcript; direction labels and `<LF>` are explanatory, not wire data:

```text
runner -> controller, stdout: [veloce] ...preparation logs...
runner -> controller, stdout: BOOTER_SYNC_READY
controller: performs its external action successfully
controller -> runner, stdin: BOOTER_SYNC_DONE<LF>
runner -> controller, stdout: [vsim] ...monitoring and collected logs...
SSH command finishes: status 0 (example; not a scenario verdict)
```

### Failures and final status

Premature/invalid input, EOF before accepted DONE, cancellation, setup timeout,
or simulator disconnect aborts the gate without automatic resume. If setup
fails, READY may never be emitted. Do not interpret a missing event or an error
as permission to send DONE or start another run.

| Runner/driver status | Meaning |
| --- | --- |
| `0` | Driver completion according to its classifier; not proof of scenario PASS. |
| `1` | Synchronization abort or execution failure, including invalid completion input, setup-acknowledgement timeout, or detected disconnect. |
| `2` | Startup-infrastructure failure. Python argument-usage errors can also return `2`; inspect diagnostics rather than assuming retry is appropriate. |
| Other nonzero status | May originate from SSH/transport or process termination; inspect stdout/stderr and do not infer readiness or PASS. |

The SSH command returns its final status only after the command finishes.
Human summary lines are not substitutes for checking that status.
Use the chosen scenario's expected outcome and fresh logs to determine PASS;
READY and status `0` alone are insufficient. Do not reuse a DONE reply for a
later test attempt.

Collected outputs are on the runner under:

```text
nuvoton_tests/validation_tests/logs_veloce/uart_*.log
nuvoton_tests/validation_tests/logs_veloce/caliptra_*.log
nuvoton_tests/validation_tests/logs_veloce/snapshots/rom_test_<timestamp>/
```

Use the paths printed by the current run. Startup failures or interrupted runs
may not produce complete logs/snapshots; do not fall back to an older run as
evidence of success.

Sources: [protocol constants and gate](veloce_vsim_driver.py#L52-L147),
[monitoring after synchronization](veloce_vsim_driver.py#L740-L774),
[startup failures](veloce_vsim_driver.py#L191-L260),
[local snapshot collection](veloce_test_internal.sh#L699-L706), and
[final status propagation](veloce_test_internal.sh#L754).
