---
name: local_tavor_veloce_active-emulation
description: Use when the user wants to select a Tavor Veloce build and an emu_* emulation directory after connecting to cm5 or cm6, without starting emulation yet.
---

# Active emulation

**Selection/navigation only: this skill does not launch emulation.**

## Durable session state

Before acting, read `..\AGENTS.md` relative to this skill directory and follow
its checkpoint rule. Load this session's shared `progress.json` and use
`skills["local_tavor_veloce_active-emulation"]` and `skills["local_tavor_veloce_connect-to-veloce-machine"]`.
All fields below are relative to the local_tavor_veloce_active-emulation entry. Save the whole
document atomically, preserving other entries and applying invalidations in
that same save. Store the connection's alias, remote user, and build
root alongside `build_name`, `build_path`, `emulation_name`, and
`emulation_path` under `selection`; use `null` for choices not yet made.

Save immediately after each user choice, before the next prompt or SSH call:
`status: in_progress`, with `step: build_selected` or `emulation_selected`.
Changing a build clears its emulation fields and invalidates
`local_tavor_veloce_source-environment`, `local_tavor_veloce_run-emulation`, and Xwave context; changing an emulation
invalidates all three. Before clearing, preserve old source/launch context,
terminal identity, nonce and dispatch state under local_tavor_veloce_run-emulation's
`retired_attempts` per the group rule; stop if that save fails.
After final path confirmation, save its actual absolute path and
`verification.verified_at`, with `status: completed` and `step: directory_verified`.
On failure, save `status: failed` and `last_error`, clearing failed verification
and invalidating `local_tavor_veloce_source-environment` and `local_tavor_veloce_run-emulation`. Do not terminate,
re-source or retry an old remote shell/emulator when invalidating its checkpoint.

On resume, revalidate the saved connection and refresh the relevant directory
listings. Reuse prior explicit choices only if still present in those listings
and their paths are confirmed on the same connection; otherwise ask again.
Do not confuse a saved completed checkpoint with an active SSH shell.

## Required connection

This skill must follow a successful `local_tavor_veloce_connect-to-veloce-machine` invocation
in the current workflow. Require its verified `veloce_alias`, `remote_user`,
and `build_root`. If absent or restored after context loss, invoke that skill
first and wait for fresh verification; it may reuse this session's saved alias.
Do not treat merely mentioning the skill or remembering an old host as a
successful connection.

Use the verified alias for every SSH command, with the same non-interactive
options and output/error handling as the connection skill. Show each command
before execution. A fresh SSH call does not retain an earlier call's `cd`.

## Command templates and safe choices

The templates below are remote commands, not local PowerShell commands.
Replace each `<quoted-...>` token with one POSIX single-quoted literal argument;
encode any embedded apostrophe as `'\''`. Never insert a choice into the shell
script itself, evaluate it as code, or expand remote expressions locally.

Use `ask_user` with the exact observed names for each selection. Remove only
the listing's trailing `/`; do not split names on spaces. Reject freeform
answers outside the observed list and reject `.`/`..` or names containing `/`.
If names cannot be represented unambiguously in the line-based listing
(for example, embedded newlines), stop rather than guessing.

## 1. Choose a build

On `veloce_alias`, enter `build_root` and list its immediate directories:

```sh
timeout 30 sh -c 'cd "$1" || exit; set -- */; if [ -d "$1" ]; then ls -1d -- "$@"; fi' sh <quoted-build-root>
```

This uses `ls`, excludes regular files, and returns no entries when no
directories match. On command failure, stop and report the error; on a
successful empty listing, report that no builds are available.

Show the live directory names to the user and ask which build to use.
Do not auto-select a new entry, even if there is only one. A prior user choice
restored from this session may be reused after fresh listing validation.

## 2. Choose an emulation

Combine the verified root with the selected immediate build name. Enter that
directory on the same alias and list only immediate directories with an
`emu_` prefix:

```sh
timeout 30 sh -c 'cd "$1" || exit; set -- emu_*/; if [ -d "$1" ]; then ls -1d -- "$@"; fi' sh <quoted-build-path>
```

If the build disappeared or became inaccessible, report the failure and
refresh the build choices before asking again. If the listing succeeds but
is empty, report that this build has no `emu_*` directories.
An `emu_*` regular file is not an emulation choice.

Show the live matching directory names and ask which emulation to use.
Validate the choice against that list and require its `emu_` prefix.

## 3. Confirm the selected directory

Combine the selected build path with the selected immediate emulation name,
then verify it on the same alias:

```sh
timeout 30 sh -c 'cd "$1" && pwd -P' sh <quoted-emulation-path>
```

If the selection disappeared or access fails, do not report success.
Refresh the emulation choices and ask again, or report the error and stop.
If SSH fails at any stage, stop and re-establish the connection prerequisite
before continuing; never silently try a different machine.

Only after a successful check, save the checkpoint and retain the alias,
selected build name, selected emulation name, and verified absolute emulation
path in the conversation. Report them and the checkpoint location as
**selected/ready**, not "emulation started".

Stop here. Do not source Tcl, set up the emulator environment, start a process,
change Xwave configuration, or launch Visualizer. Future remote operations
must explicitly enter the recorded path again.
