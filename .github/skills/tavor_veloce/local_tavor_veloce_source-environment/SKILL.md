---
name: local_tavor_veloce_source-environment
description: Use when the user requests source environment or Tavor Veloce environment preparation after selecting a build and emu_* directory with local_tavor_veloce_active-emulation.
---

# Source environment

## Purpose

Prepare a persistent CSH shell for later Veloce commands. Source
`../scripts/local_env` from the selected emulation directory, verify the
result, and stop. **Do not launch Veloce, VSIM, Visualizer, or change straps
or Xwave.** Environment preparation is not emulation startup.

Trigger phrase: "source environment"

## Assistant workflow

### 1. Restore and validate prerequisites

Read `..\AGENTS.md` before acting, including after context loss. Load this
session's shared `progress.json`: use `skills["local_tavor_veloce_source-environment"]` for this
skill, and read the connection, local_tavor_veloce_active-emulation and local_tavor_veloce_run-emulation entries
from the same `skills` map. **Before invoking another prerequisite or
sending any CSH probe**, inspect existing/retired launch attempts read-only as
local_tavor_veloce_run-emulation requires. A VSIM-owned, busy or ambiguous pane is not an idle CSH.
Do not silently re-source, replace, interrupt or restart it. User resolution
is required even if its old checkpoint readiness has been invalidated.
Require a freshly validated `local_tavor_veloce_active-emulation` result; invoke that skill
first if absent or restored. Reuse saved choices only after its live checks.

Use the same verified SSH alias and non-interactive options as the connection
skill. Show commands before execution; capture SSH exit code, stdout and
stderr separately. Pane capture is combined terminal output, not separate
source stdout/stderr. Quote remote paths as literal arguments, never shell
code; prevent local PowerShell expansion of remote `$` expressions.

Confirm the emulation directory and readable `../scripts/local_env`.
Read its source chain to establish the required shell and build root.
For the known wrapper, also require readable `../build_dir/local_env.csh`;
resolve that build directory with `pwd -P`. Check remote tmux and tcsh/csh
availability. Stop on failure; do not install tools or substitute Bash.

### 2. Create an owned persistent shell

Use the manual recipes below, through bounded SSH calls and a POSIX controller
shell. Create a fresh name from this Copilot session ID and a generated nonce;
restrict the name/nonce to letters, digits and hyphens. Use that name for a
private tmux socket and session. Never reuse an existing name on collision.
The private server uses `/dev/null` instead of user tmux configuration.
Verify the CSH executable before using its absolute path in the recipe.

Save the exact socket/session name, session ID/creation time, pane ID and
shell PID immediately after creation, before sourcing. If saving fails, stop.
Require a live tcsh/csh pane in the selected directory before sending input.
Normalize a leading login-shell dash and executable path in tmux's command
name, then compare the basename to `tcsh`/`csh`.
Do not send commands to an existing Veloce process, unrelated pane, or shell
whose identity or idleness cannot be established.

### 3. Source and verify

Generate a fresh operation nonce and record `in_progress` / `sourcing` before
sending the source recipe. Start a **120-second monotonic deadline** before
sending it. Bound individual SSH calls too; poll capture within that deadline.
Only standalone begin/end lines containing this operation's nonce count.
Normalize tmux capture's right-padding spaces before comparing lines.
Echoed command text, a prompt, or an earlier operation's output is not proof.
If markers are lost from capture history, fail rather than guess.

Inspect only the fresh marked output. All these conditions are required:

| Check | Required result |
|---|---|
| Completion | Fresh end marker and source status `0` |
| Version | Nonempty `Veloce Version ...`; never pin `24.3` |
| Tools | Fresh `:Ok` entries for `VLAB_HOME`, `VELOCE_HOME`, `VELOCE_XACTOR_HOME`, `QUESTA_HOME`; reported directories accessible |
| Errors | No unresolved source/file/permission/syntax/undefined-variable/command-not-found errors or failed tool checks |
| Build root | Reported CSH `ROOT_DIR`, resolved canonically, matches the selected build's expected root |
| Directory | Reported post-source `$cwd` matches the selected emulation directory, without an extra `cd` to repair it |

The wrapper's final `cd` can mask an earlier source error: status zero and
positive tool lines alone do not pass. `ROOT_DIR` can be a CSH-only variable,
so `printenv` is insufficient. Printed `VIS_HOME` may mean `VISUALIZER_HOME`.
Versions, usernames, installation paths and emulator names may change.
`OSCI should be 0!` is expected informational output, not a failure.

After passing, verify the idle owner prompt and pane identity again. Set
`tv_ready` to the operation nonce in that same shell and read it back with a
fresh probe before recording `completed` / `environment_verified`.
Leave the shell alive. Report the observed version, host/build/emulation,
socket/session/pane identity and checkpoint location as **environment ready**.

### 4. Checkpoint and resume

All skill checkpoints are entries in the single
`.copilot\state\tavor_veloce\<session-id>\progress.json`.
Fields below belong to `skills["local_tavor_veloce_source-environment"]`. Save the whole shared
document atomically, preserving other entries and applying dependent
invalidations/history retention in the same save. This is bookkeeping, not
a Veloce configuration or environment backup.

- `selection`: copy the validated alias, remote user, build root/name/path,
  emulation name/path, plus generated `tmux_name`.
- `verification`: observed tmux session ID/creation time, pane ID, shell
  PID/path, operation nonce, version, root/cwd, allowlisted tool checks and
  `verified_at`. Unknown fields are `null`.
- Save atomically after context selection, shell creation, before sourcing,
  and after verification or failure, following the shared JSON envelope.
- On timeout/error, save `failed` and a concise `last_error`; clear environment
  readiness/`verified_at` but retain owned shell identity for inspection.
  Leave the shell alone: no automatic retry, interrupt, killing, or more input
  to a potentially busy pane.
- On resume, first revalidate upstream context and exact live tmux identity.
  Require tcsh/csh as the foreground command and the recorded idle prompt.
  Only then send a fresh nonce-tagged probe of `tv_owner`, `tv_ready`,
  `$ROOT_DIR`, `$cwd`, and allowlisted tool variables identified from the
  source chain. Require the recorded readiness nonce, expected paths and
  accessible tools. A missing/busy/replaced shell is not ready; stop instead
  of injecting input or silently creating another session.
- Changing host/build/emulation or a failed prerequisite invalidates this
  readiness and `local_tavor_veloce_run-emulation` transitively. Before any invalidation,
  failure, re-source or replacement, preserve old source/terminal/attempt
  identity, nonce and dispatch state in local_tavor_veloce_run-emulation's `retired_attempts`
  per the group rule; stop if preservation fails. Never destroy the old remote
  session, inject shell probes into a possibly running emulator, or retry a
  launch merely to invalidate JSON.
  Do not persist the complete environment, license settings or transcripts.

## Manual workflow

These are **remote POSIX controller-shell recipes**, not local PowerShell
commands. Source runs inside the CSH pane. Set `emu` to the verified absolute
emulation path, and `name`/`token` to fresh generated identifiers as above.
Pass these as safely quoted arguments when controlling SSH from Windows.

### Create the shell

```sh
set -eu
tmux -L "$name" -f /dev/null new-session -d -s "$name" -c "$emu" -x 240 -y 80 '/usr/bin/tcsh -f'
pane=$(tmux -L "$name" display-message -p -t "$name:0.0" '#{pane_id}')
tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}'
```

This creates an isolated terminal without changing other tmux sessions.
The executable path is an example: use the tcsh/csh path verified on that host.
Check every command's exit status and save the returned identity before
proceeding. On any failure stop, rather than running the next recipe.

### Send the source operation

```sh
set -eu
payload=$(cat <<EOF
set prompt = "__TV_IDLE_${token}__ "
set tv_owner = "$token"
set tv_ready = ""
echo "__TV_BEGIN_${token}__"
source ../scripts/local_env
set tv_rc = \$status
echo "__TV_RC_${token}__=\$tv_rc"
echo "__TV_ROOT_${token}__=\$ROOT_DIR"
echo "__TV_CWD_${token}__=\$cwd"
echo "__TV_END_${token}__"
EOF
)
tmux -L "$name" send-keys -t "$pane" -l -- "$payload"
tmux -L "$name" send-keys -t "$pane" Enter
```

Literal sending prevents tmux interpreting command text as key names.
Separate CSH input lines capture `$status` before later commands replace it.
The controller's escaped dollar signs deliberately reach the CSH unchanged.

### Inspect, verify and keep the shell

```sh
set -eu
tmux -L "$name" capture-pane -p -J -S - -t "$pane"
tmux -L "$name" display-message -p -t "$pane" '#{session_id}|#{session_created}|#{pane_id}|#{pane_pid}|#{pane_current_command}|#{pane_current_path}'
```

Repeat inspection only within the 120-second deadline. Apply every success
check above; do not equate capture success with source success. After those
checks and a fresh idle-identity check, send `set tv_ready = "<token>"` plus
Enter literally and probe its value in the same shell.

Later commands must use this recorded socket and pane. A new SSH shell, or
`tmux run-shell`, does not inherit the pane's CSH variables/environment.
`local_tavor_veloce_run-emulation` is the next explicit step: it requires this live readiness,
asks for straps/final-command confirmation, and stops at a fresh VSIM prompt.

## Notes / approval

Creating the skill does not execute it. Source the real environment only
when the user invokes this preparation step. Ask before replacing, re-sourcing,
or cleaning up an existing session; do not guess the user's next VSIM command.
Normal success leaves the prepared shell running, but JSON cannot recreate
its environment after it exits. Do not claim emulation has started.
