---
name: local_tavor_veloce_connect-to-veloce-machine
description: Use when the user wants to connect to a Tavor Veloce machine, choose cm5 or cm6, or access the remote TavorBuilds directory before selecting a build and emulation.
---

# Connect to Veloce machine

Execute read-only SSH checks and establish verified context for
`local_tavor_veloce_active-emulation`. Do not launch an emulator or modify remote files.

## Durable session state

Before acting, read `..\AGENTS.md` relative to this skill directory and follow
its checkpoint rule. Load this session's shared `progress.json` and use
`skills["local_tavor_veloce_connect-to-veloce-machine"]` as this skill's checkpoint.
All fields below are relative to that entry; preserve the other skills'
entries on every whole-file atomic save, including dependent invalidations.
Save `selection.veloce_alias` immediately after the user's machine choice,
with `status: in_progress` and `step: machine_selected`.

Save successful `remote_user`, `build_root`, and `verified_at` under
`verification`, with `status: completed` and `step: connection_verified`.
On failure, clear verified fields, save `status: failed` and `last_error`,
and invalidate `local_tavor_veloce_active-emulation`, `local_tavor_veloce_source-environment`, `local_tavor_veloce_run-emulation`, and
`local_tavor_veloce_xwave-on` as the group rule requires. Before clearing, preserve old source/
launch identity and uncertain dispatch under local_tavor_veloce_run-emulation's `retired_attempts`;
stop if that save fails. Invalidation does not authorize terminating remote
shells or an emulator, re-sourcing, or retrying a launch.

After context loss, a saved alias is a previous user choice, so it need not
be asked again. Re-run the access/root check before treating restored context
as verified. Before changing aliases, invalidate dependent checkpoints.

## Choose the machine

1. Read the user's SSH config (`$HOME\.ssh\config` on Windows). Inspect only
   the `cm5` and `cm6` aliases; never read private-key contents.
2. Use `ask_user` to choose between the available aliases unless the user
   already explicitly selected one for this workflow (including a valid saved
   choice). If the requested alias
   is missing, stop and report it. Do not guess a hostname or switch machines.
3. Use the chosen alias unchanged so SSH applies its saved user, identity, and
   host-verification settings. Do not edit the config or bypass host checks.

## Verify access and enter TavorBuilds

Show the exact command before execution. Use non-interactive SSH with
`BatchMode=yes`, `ConnectTimeout=10`, `ServerAliveInterval=10`, and
`ServerAliveCountMax=2`. Capture stdout, stderr, and exit status separately.
Do not hang on a password prompt or ask the user to disclose a password.

In PowerShell, after setting `$alias` to the chosen `cm5` or `cm6`, use:

```powershell
$remoteCommand = 'timeout 30 sh -c ''set -eu; remote_user=$(whoami); cd "/home/data3/$remote_user/TavorBuilds/"; printf "remote_user=%s\nbuild_root=%s\n" "$remote_user" "$(pwd -P)"'''
ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 $alias -- $remoteCommand
```

The single-quoted PowerShell string deliberately leaves `$(whoami)` for the
remote shell. The remote username, not the local Windows username, determines
`/home/data3/$(whoami)/TavorBuilds/`.

Only after exit status zero and valid `remote_user` and absolute `build_root`
output, save the checkpoint and restore these values into the conversation:

- `veloce_alias`: the chosen alias.
- `remote_user`: the verified remote username.
- `build_root`: the verified absolute directory returned by `pwd -P`.

If SSH authentication, transport, `timeout`/`sh`, or directory access fails,
stop and report the command, exit status, stdout, and stderr. Distinguish SSH
failure from a remote command failure using the diagnostics; do not report
connection success or invent context from failed output.

## Handoff

Report the verified alias, TavorBuilds path, and checkpoint location.
This check is a short SSH call,
not an interactive shell left open. Later commands must use the same alias
and explicitly `cd` to their required directory. The `local_tavor_veloce_active-emulation` skill
may now list builds using this context; it still must ask for the user's choices.
