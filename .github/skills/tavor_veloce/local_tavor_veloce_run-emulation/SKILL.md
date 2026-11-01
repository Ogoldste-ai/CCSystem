---
name: local_tavor_veloce_run-emulation
description: Use when the user requests "run emulation" or Tavor Veloce startup after local_tavor_veloce_source-environment preparation, or asks to inspect a previously attempted launch.
---

# Run emulation

## Purpose

Start Veloce once in the **exact persistent tmux/CSH pane** prepared by
`local_tavor_veloce_source-environment`. Stop at a fresh numbered VSIM input prompt. This means
**CLI ready**, not boot complete, firmware success, or debug access granted.

Trigger phrase: "run emulation"

## Assistant workflow

### 1. Restore first; existing launches are inspection-only

Read `..\AGENTS.md` before acting, including after context loss. Load this
session's single `.copilot\state\tavor_veloce\<session-id>\progress.json`.
Use `skills["local_tavor_veloce_run-emulation"]` and the upstream entries in its `skills` map;
validate the shared document and nested envelopes before using any strings.

**Before invoking local_tavor_veloce_source-environment or sending any CSH probe**, inspect any
saved attempt, including `retired_attempts` retained after invalidation. Use
only read-only tmux identity/capture operations on its recorded alias/socket/
session/pane. Never redirect an old inspection to the newly selected host.
An intent, staged command, attempted send, SSH timeout, or missing acknowledgement
is a possibly live launch, not permission to resend. Preserve its identity,
nonce and dispatch state even when upstream readiness is invalidated.

| Saved/live condition | Action |
|---|---|
| Current fresh VSIM prompt and unchanged owned identity | Revalidate twice read-only; report already CLI ready; send nothing |
| Busy, startup in progress, uncertain dispatch, stale prompt, missing boundary | Inspect/report only; no CSH probes or automatic retry |
| Pane gone/replaced, returned shell, launch failure, timeout | Save failure/unknown result; preserve diagnostics and remote process |
| No attempt, no retained attempt, new launch explicitly requested | Validate prerequisites below |

Saved success is historical. A retained invalidated attempt may be reported
as an observed old CLI, never as readiness for new host/build selections.
Resolving an old attempt or authorizing another launch is an explicit user
decision; it is not automatic cleanup, re-source, restart, or interrupt.

### 2. Verify prerequisites for a new attempt

Require freshly verified connection and `local_tavor_veloce_active-emulation` context and a
successful `local_tavor_veloce_source-environment` in that **same** private tmux pane. If missing,
invoke the prerequisite only after the inspection gate above. Do not source
implicitly in the launch command, create a replacement pane, use `run-shell`,
or run make in a new SSH shell.

Follow local_tavor_veloce_source-environment's live resume checks: compare alias/remote user,
canonical build/emulation paths, socket/session name, session ID/creation time,
pane ID/shell PID; require a live idle tcsh/csh foreground and the exact owner
prompt with an empty input line. Normalize leading login dash/path when
comparing shell executable names. Only then send a fresh nonce-tagged CSH
readiness probe in this pane for `tv_owner`, `tv_ready`, `$ROOT_DIR`, `$cwd`
and accessible allowlisted tools. Require its saved source readiness nonce
and expected paths; a JSON `completed` flag alone is insufficient. A busy or
ambiguous pane receives **no input**. Failure invalidates launch readiness.

Show remote commands before execution. Use the connection skill's verified
alias/options and separate stdout/stderr/exit status. Wrap controller scripts
explicitly in POSIX `sh -c`; the login shell may be CSH. Quote every argument
as data (POSIX single-quote, embedded apostrophe `'\''`); prevent PowerShell
from expanding remote `$` expressions.

### 3. Show JTAG options, ask for a choice, then calculate STRAPS

Before presets, inspect the selected build's makefiles/launch scripts
**read-only** to establish how `STRAPS` maps to the pins and which revision
it implements. Record evidence/path or explicit user confirmation of the
proposed mapping. If unverified, explain the numbering conflict below and
ask for confirmation of `(debug << 12) | (boot << 8)`; alternatively accept
an explicitly selected raw value without claiming verified hardware semantics.
Do not silently treat either user examples or the latest spec as build proof.

**FACT FROM SPEC:** `NPCM9mnx_AS_Rev.0.77_A1`, Table 3, pp.51–52
(chunk `39076916595cabe11a8033e0d800941c`) defines 17 straps, boot [11:8],
debug [16:12]. Section 6.4.1/Table 57, pp.800–801
(chunk `a0715a415bf915feb7aad5882774da39`, continuation
`c26b25af5454ad08309e21a8e36ad607`) calls the debug field STRAP0–4 /
DBGSTRAP0–4. This numbering ambiguity remains unresolved until build
verification/explicit confirmation. Labels below are spec labels only,
not inferred firmware, lifecycle, security-bypass, or processor-enable behavior.

For the chooser, **Display both JTAG tables** below before asking which
combination the user wants. Use `ask_user` with the five-bit value and JS1/JS2
connections for each selectable option. Save the explicit choice immediately;
do not infer it from an example. Mark "current selection" only when this
session's saved progress actually contains that user choice.

Then show the separate boot/recovery table and use `ask_user` for that field.
Save it before calculating the full value. Neither field is fixed or silently
selected. Preserve the custom full-hexadecimal input alternative.

`LCC` means **Life Cycle Controller** / LCC-TAPC; Caliptra Core is Cal-TAPC
and MCU is MCU-TAPC.

#### Pair configurations

| Debug bits / value | JS1 routing | JS2 routing |
|---|---|---|
| 01010 / 0a | MCU | A35 |
| 01001 / 09 | MCU | M7 |
| 00101 / 05 | A35 | M7 |
| 10010 / 12 | Caliptra Core | A35 |
| 10001 / 11 | Caliptra Core | M7 |
| 01000 / 08 | MCU | Caliptra Core |
| 00010 / 02 | LCC | A35 |
| 00001 / 01 | LCC | M7 |
| 00100 / 04 | LCC | Caliptra Core |
| 00011 / 03 | LCC | MCU |

#### Star and daisy-chain configurations

For star options, JS1 accesses the listed controllers through CLTAP.

| Debug bits / value | JS1 routing | JS2 routing |
|---|---|---|
| 01111 / 0f | Full-star: all five via CLTAP | Unused |
| 11110 / 1e | Star: all except A35 via CLTAP | A35 |
| 11101 / 1d | Star: all except M7 via CLTAP | M7 |
| 11100 / 1c | Star: all except Caliptra Core via CLTAP | Caliptra Core |
| 11011 / 1b | Star: all except MCU via CLTAP | MCU |
| 11010 / 1a | Star: all except LCC via CLTAP | LCC |
| 00110 / 06 | Daisy chain: M7 → Caliptra Core → MCU → A35 | LCC |
| 00000 / 00 | Daisy chain: A35 → M7 → Caliptra Core → MCU → LCC | Unused |
| Other values | No TAP selected | No TAP selected |

"Other values" is a category, not a literal input. For an explicit no-TAP
choice use `11111` / `1f`, documented as debug disabled by Table 3 and covered
by Table 57's "None"; do not select an arbitrary undefined encoding.

All ten fallback pairs, six star variants and both daisy chains are listed.
**CLTAP configurations are not implemented on Tavor-Z1**; show all six star
rows as unavailable there, not as selectable presets. With unknown revision
do not offer them as compatible:
establish a supported non-Z1 revision first, or stop. Table 57 labels other
vectors "None" (TAP inputs including TRSTn driven 0); do not invent additional
named presets. Debug routing is not a core-enable mask, and does not prove
access to target logic. No debug-unlock procedure is authorized.

| Boot [11:8] / value | Table 3 label |
|---|---|
| 1111 / f | Normal SPI boot, no recovery, continue |
| 1110 / e | SPI boot with `MCI_BOOT_SEQ_BRKPOINT` |
| 1011 / b | I3C boot, continue |
| 1010 / a | I3C boot with `MCI_BOOT_SEQ_BRKPOINT` |
| 1101 / d | LAN boot, continue |
| 1100 / c | LAN boot with `MCI_BOOT_SEQ_BRKPOINT` |
| 0001 / 1 | USB boot, continue |
| 0000 / 0 | USB boot with `MCI_BOOT_SEQ_BRKPOINT` |
| 0101 / 5 | "LLC Bypass and Jump to Flash" |
| 0100 / 4 | "LCC Bypass, Normal MCU ROM Execution" |
| 0011 / 3 | "Normal LLC and Jump to flash" |

Other boot values (2, 6, 7, 8, 9) are reserved and should not be used;
never offer them as presets. Preserve the draft's **LLC/LCC** wording and
its unresolved cross-reference. These labels do not establish firmware
behavior or any security bypass.

**USER-CONFIRMED WORKFLOW SETTING:** keep chooser low byte `[7:0]=0x00`;
this is not a verified hardware default. Show it explicitly. Nonzero
low bytes require custom input, with warnings about reserved low bits:
Table 3 labels 0–6 reserved (with notes), and bit 7 selects debug serial
routing. Do not extrapolate those notes into supported features.

**OPEN QUESTION:** selected build mapping/revision until checked as above.
Save each user choice immediately, before the next question or operation.

The following local Python example is the actual validation/composition
recipe, not a remote helper. Hex input is a complete string, no trimming,
signs, shell syntax, separators or repeated prefix. Range is `0..0x1ffff`;
leading zeroes are allowed. Show decoded fields for custom values too.

```python
import re

BOOT_VALUES = {0, 1, 3, 4, 5, 10, 11, 12, 13, 14, 15}
STAR_VALUES = {15, 26, 27, 28, 29, 30}
DEBUG_VALUES = {0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 17, 18, 31} | STAR_VALUES

def normalize_straps(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]+", raw):
        raise ValueError("one optional hex prefix and hexadecimal digits only")
    digits = raw[2:] if raw.startswith(("0x", "0X")) else raw
    digits = digits.lstrip("0") or "0"
    if len(digits) > 5 or int(digits, 16) > 0x1ffff:
        raise ValueError("STRAPS must fit 17 bits")
    return f"0x{int(digits, 16):05x}"

def preset_straps(debug, boot, mapping, revision):
    if mapping not in ("verified", "confirmed"):
        raise ValueError("verify build mapping or obtain explicit confirmation")
    if type(debug) is not int or debug not in DEBUG_VALUES:
        raise ValueError("not a listed debug preset")
    if type(boot) is not int or boot not in BOOT_VALUES:
        raise ValueError("reserved boot setting is not a preset")
    if debug in STAR_VALUES and revision not in ("non-Z1-supported", "A1"):
        raise ValueError("CLTAP requires verified supported non-Z1 revision")
    return normalize_straps(f"{(debug << 12) | (boot << 8):x}")

def custom_straps(raw, reserved_ack, z1, compatibility_ack=False, revision_known=False):
    value = normalize_straps(raw)
    bits = int(value, 16)
    debug, boot, low = bits >> 12, (bits >> 8) & 15, bits & 255
    if z1 and debug in STAR_VALUES:
        raise ValueError("CLTAP unsupported on Tavor-Z1")
    if debug in STAR_VALUES and not revision_known and not compatibility_ack:
        raise ValueError("explicit acknowledgement of unknown CLTAP compatibility required")
    if (boot not in BOOT_VALUES or debug not in DEBUG_VALUES or low & 0x7f) and not reserved_ack:
        raise ValueError("warn about reserved/undefined settings; explicit acknowledgement required")
    return value
```

`A1` in the example means **verified build support**, not the PDF's title.
For raw star vectors with unknown revision, explain compatibility is unknown
and require explicit acknowledgement of that uncertainty; never imply support.
`reserved_ack` and `compatibility_ack` are recorded user acknowledgements,
not inferred consent. Pass `revision_known=False` when build revision is
unknown; `z1` must reflect verified build evidence, not the spec title.

After both choices, calculate `(jtag_value << 12) | (boot_value << 8) | 0x00`
and normalize the result to one `0x` prefix and five hexadecimal digits.
Display the chosen labels, five-bit JTAG value, boot/low fields and calculated
full value, then construct the exact command using that result:
`make cli_run STRAPS=<calculated-0x-prefixed-value> BACKUP=0`.
Never treat an example value as the user's selection.

Examples only, with normal SPI boot (`boot_value=0xf`) and low byte 0x00:
`01010` (MCU+A35) → `0x0af00`; `01001` (MCU+M7) → `0x09f00`;
`00101` (A35+M7) → `0x05f00`. A different boot choice changes the full value.
**Require explicit final-command confirmation before any launch send/Enter.**

### 4. Stage once, dispatch once, observe with a deadline

Save intent and a generated attempt nonce before boundary preparation.
Recheck exact owned idle CSH/readiness immediately before staging the boundary
and again before the launch send. Only a standalone **fresh**
`__TV_RUN_BEGIN_<nonce>__` printed by the boundary recipe counts; never an
echoed command. Require its idle owner prompt again before sending make.

Save `staged` after boundary verification; save `attempted` **before the first
launch send-keys**, then send the one literal command and separate Enter.
No commands or keystrokes may be queued after make. On acknowledgement save
`sent`; on any partial/ambiguous dispatch save `uncertain`. Neither local
timeout nor SSH error proves the command was not delivered. **Never resend
an uncertain dispatch**, even if no prompt is visible.

Start a **600-second monotonic deadline immediately before the first launch
send**, not after SSH returns. Every SSH call (including preparation and
inspection) has a local process timeout, normally at most 15 seconds, capped
by the remaining observation time. SSH connection options alone do not bound
a remote call. Terminating a timed-out local SSH client does not authorize
remote cleanup; dispatch may have occurred. Use no unbounded retries.

Inspect unchanged identity and current cursor/screen, not just scrollback.
Require the fresh boundary still present exactly once and current standalone
`VSIM <decimal-number> >` (flexible horizontal whitespace, optional final
newline). Literal brackets are not assumed. Two separated read-only snapshots
must agree on identity/prompt/cursor, with a verified simulator foreground
(`vsim`/`vsimk`). If tmux instead reports make, use read-only process/foreground
group evidence to establish the actual simulator, or remain unverified.
Make foreground alone is neither success nor definitive launch failure.

Reject stale history, command echoes, quoted strings, mid-log text, later
output after a prompt, returned CSH, replaced/dead panes, missing boundary
and SSH failure. A prompt-like line is not enough. The sample below rejects
uncertain evidence conservatively; its `foreground` is a verified executable
basename, not a label inferred from the text. Do not normalize brackets or
strip quote characters to force a match.

```python
def current_prompt(s, identity, nonce):
    if not s["live"] or s["identity"] != identity or s["foreground"] not in ("vsim", "vsimk"):
        return None
    boundary = "__TV_RUN_BEGIN_" + nonce + "__"
    lines = [line.rstrip(" \t") for line in s["history"].splitlines()]
    if lines.count(boundary) != 1:
        return None
    fresh = lines[lines.index(boundary) + 1:]
    while fresh and not fresh[-1].strip(" \t"):
        fresh.pop()
    rows = s["screen"].splitlines()
    y = s["cursor_y"]
    if not fresh or not 0 <= y < len(rows):
        return None
    row = rows[y].rstrip(" \t")
    if row != fresh[-1] or any(r.strip(" \t") for r in rows[y + 1:]):
        return None
    match = re.fullmatch(r"[ \t]*VSIM[ \t]+([0-9]+)[ \t]*>[ \t]*", row)
    if not match or s["cursor_x"] < len(row) or s["cursor_x"] > len(rows[y]):
        return None
    return {"text": row, "number": match[1], "cursor": (y, s["cursor_x"])}

def observe_or_launch(attempt, straps, confirmed, save, call, clock, sleep):
    # Local controller pattern. call is bounded SSH; save atomically writes
    # progress.json, merging this attempt into this skill's verification.
    existing = attempt["dispatch_state"] != "not_started"
    if not existing:
        if not confirmed:
            return {"outcome": "blocked"}
        command = "make cli_run STRAPS=" + normalize_straps(straps) + " BACKUP=0"
        attempt["dispatch_state"] = "intent"
        save(attempt)
        try:
            prepared = call("prepare", 15, nonce=attempt["nonce"])
        except (OSError, TimeoutError):
            attempt["dispatch_state"] = "uncertain"
            save(attempt)
            return {"outcome": "uncertain"}
        if not prepared["idle_verified"] or not prepared["boundary_verified"]:
            return {"outcome": "blocked"}
        attempt["dispatch_state"] = "staged"
        save(attempt)
        attempt["dispatch_state"] = "attempted"
        save(attempt)
        deadline = clock() + 600
        try:
            call("dispatch", min(15, deadline - clock()), command=command)
        except (OSError, TimeoutError):
            attempt["dispatch_state"] = "uncertain"
            save(attempt)
            return {"outcome": "uncertain"}
        attempt["dispatch_state"] = "sent"
        save(attempt)
    else:
        # Reentry is one read-only observation pair, not a renewed startup wait.
        deadline = clock() + 30
    previous = None
    while clock() < deadline:
        remaining = deadline - clock()
        try:
            s = call("inspect", min(15, remaining))
        except (OSError, TimeoutError):
            return {"outcome": "failed"}
        if clock() >= deadline:
            break
        if not s["live"] or s["identity"] != attempt["identity"]:
            return {"outcome": "failed"}
        foreground = s["foreground"].lstrip("-").split("/")[-1]
        if foreground in ("tcsh", "csh"):
            return {"outcome": "failed"}
        observed = current_prompt(s, attempt["identity"], attempt["nonce"])
        if observed is not None and observed == previous:
            return {"outcome": "ready", "prompt": observed}
        if existing and previous is not None:
            return {"outcome": "inspection_only"}
        previous = observed
        if existing and observed is None:
            return {"outcome": "inspection_only"}
        sleep(min(1, max(0, deadline - clock())))
    return {"outcome": "inspection_only" if existing else "timeout"}
```

The callback contract is mandatory, not a shortcut around prerequisite checks:
`prepare` performs fresh upstream/source checks and the boundary recipe,
then verifies idle identity again; `dispatch` repeats the idle/identity
read-only check immediately before the send recipe. A failed dispatch gate
raises `OSError` without sending, leaving attempted delivery conservatively
uncertain. `inspect` runs only the read-only recipe and checks identity
before and after capture. If state changes during capture, reject it.
`identity` includes alias, remote user, socket name, session ID/creation time,
pane ID and shell PID; also compare selected cwd/owner context in the adapters.
The source readiness nonce and owner marker are validated in `prepare`, not
re-probed once a possible emulator owns the pane.

`save` reloads the latest shared `progress.json` under exclusive writer
ownership and merges the attempt into `skills["local_tavor_veloce_run-emulation"].verification`;
it preserves all other entries and fields, applies dependent updates in the
same atomic replacement, and updates both entry/shared timestamps.
`save` failures propagate and stop all further operations. Translate outcomes
to the envelope and save: ready → `completed` / `vsim_ready`, prompt number/
text and UTC `verified_at`; timeout/error → `failed` with concise error and
no readiness; inspection_only/uncertain → retain unresolved attempt, no new
readiness. Do not overwrite dispatch provenance with a timeout label.
Save UTC dispatch time as well as local monotonic budget information.
Across process/context restart monotonic origins cannot be trusted: reentry
uses only bounded read-only inspection, never a new 600-second launch budget.
Confirmed fresh fatal startup output is failure; ambiguous warnings remain
unverified. All non-success paths preserve the remote process untouched.

### 5. Checkpoint and report

`skills["local_tavor_veloce_run-emulation"]` in the session's `progress.json` uses the existing
skill envelope. Follow the shared whole-file atomic save rule, preserving
other entries; do not write an independent skill file. Fields below are
relative to this entry.

- `selection`: alias, remote user, build root/name/path, emulation name/path,
  source terminal identity/readiness nonce, mode (chooser/custom), mapping
  status/evidence or confirmation, revision/support evidence, debug and boot
  values/labels, low byte, raw input, normalized straps, reserved/compatibility
  acknowledgements, `backup: 0`, and final-command confirmation. Unknown is null.
- `verification`: exact source/terminal identity, attempt nonce, dispatch
  state, dispatch UTC time, last observation time, observed prompt/number,
  `verified_at`, and `retired_attempts`. No raw transcript or environment.
- Save after every choice, before any remote operation that can send input,
  after each dispatch transition, and on every outcome. A clean initialization
  is `not_started`, all unknown selections/verification null; BACKUP=0 is a
  command requirement, not a fabricated user selection.
- Changes/failures of host, build, emulation or source readiness invalidate
  launch readiness transitively. Before clearing, report and preserve the
  old terminal/attempt under `verification.retired_attempts`, with original
  context, nonce and dispatch state. Never erase the only evidence of a
  possibly live emulator, including on repeated invalidations.

Report selected straps/command, host/build/emulation, exact pane identity,
CLI-ready observation or honest failure/uncertainty, and checkpoint path.
At readiness **send nothing else**, not even Enter or a CSH verification probe.

## Manual workflow

These are **remote POSIX controller-shell recipes**, executed through bounded
SSH, not local PowerShell commands. Set verified `name`, `pane`, `expected`,
`idle`, and generated alphanumeric/hyphen `nonce` as safely quoted arguments.
`expected` is exactly the six-field metadata string used in the staging/
dispatch gates (session ID, creation time, pane ID, shell PID, current CSH
command and path), not the expanded inspection record; `idle` is the source
owner prompt without its trailing space. Fresh source checks must already
have passed.

### Inspect without sending

```sh
set -eu
printf '__TV_SNAPSHOT_%s_META_BEFORE__\n' "$nonce"
tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}|#{pane_dead}|#{cursor_x}|#{cursor_y}'
printf '__TV_SNAPSHOT_%s_HISTORY__\n' "$nonce"
tmux -L "$name" capture-pane -p -J -S - -t "$pane"
printf '__TV_SNAPSHOT_%s_SCREEN__\n' "$nonce"
tmux -L "$name" capture-pane -p -t "$pane"
printf '__TV_SNAPSHOT_%s_META_AFTER__\n' "$nonce"
tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}|#{pane_dead}|#{cursor_x}|#{cursor_y}'
printf '__TV_SNAPSHOT_%s_END__\n' "$nonce"
```

First capture is joined history (boundary/fresh tail); second is the current
screen without `-J` (cursor coordinates). Parse separately from metadata.
The nonce-framed sections distinguish variable-length captures from metadata;
require every standalone frame marker exactly once and in the shown order,
and exit status zero before using any partial output. Never treat frame
markers inside captured text as valid duplicates.
tmux 2.7 right-pads captures; strip only horizontal right padding when matching
markers. Require matching metadata before/after; never use an old cursor
position against a newer screen. Refuse wrapped/truncated prompt ambiguity.
No `attach`, process replacement, interrupt, restart, or new server is used.

### Stage the fresh boundary in an already verified idle CSH

```sh
set -eu
actual=$(tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}')
test "$actual" = "$expected"
screen=$(tmux -L "$name" capture-pane -p -t "$pane")
tail=$(printf '%s\n' "$screen" | sed 's/[[:blank:]]*$//' | sed '/^$/d' | tail -n 1)
test "$tail" = "$idle"
tmux -L "$name" send-keys -t "$pane" -l -- "echo \"__TV_RUN_BEGIN_${nonce}__\""
tmux -L "$name" send-keys -t "$pane" Enter
```

Inspect until the standalone boundary and the same idle owner prompt are
visible; bound this preparation separately to 30 seconds. On any failure or
ambiguity stop, retain intent and inspect read-only. Checkpoint `staged` only
after verification. This boundary operation is not make and is never replayed
automatically after an uncertain send.

### Dispatch the confirmed launch once

```sh
set -eu
actual=$(tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}')
test "$actual" = "$expected"
screen=$(tmux -L "$name" capture-pane -p -t "$pane")
tail=$(printf '%s\n' "$screen" | sed 's/[[:blank:]]*$//' | sed '/^$/d' | tail -n 1)
test "$tail" = "$idle"
tmux -L "$name" send-keys -t "$pane" -l -- "$command"
tmux -L "$name" send-keys -t "$pane" Enter
```

`command` is constructed **only** by validated normalization above as
`make cli_run STRAPS=0x<five-lowercase-hex-digits> BACKUP=0`; never interpolate
raw user input. Persist `attempted` and start the monotonic deadline before
this recipe. A failed literal send must stop before Enter (`set -eu`).
A failed capture stops at its standalone assignment; do not hide tmux's exit
status inside a POSIX pipeline whose final filter could succeed.
A failed Enter/transport acknowledgement leaves uncertain delivery and must
not trigger a resend. Poll only the read-only inspection recipe afterward.

## Notes / approval

Creating/testing this instruction-only skill is **not** permission to SSH,
source the real environment or run real Veloce. Execution requires the user
to invoke this step and confirm the selected final command. Do not change
Xwave, open Visualizer, enter a VSIM command, interrupt, clean up or retry a
remote process automatically. A stable rendered prompt plus foreground
evidence is an operational heuristic, not cryptographic proof: deliberately
spoofed simulator output cannot be distinguished from a genuine prompt by
terminal text alone. If evidence is ambiguous, report unknown, not success.
tmux send/capture operations are not atomic against an outside typist:
if another client may control the pane, stop for exclusive ownership rather
than claiming the check/send race is eliminated.
