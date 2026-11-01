---
name: local_tavor_veloce_xwave-on
description: Use when the user needs a manual reminder about Xwave waveform dumping in Tavor Veloce emulation, enabling or disabling dump configuration, opening waves in Visualizer, or a missing tbx.stw trace directory.
---

# Xwave on

## Durable session state

Before acting, read `..\AGENTS.md` relative to this skill directory and follow
its checkpoint rule. Load this session's shared `progress.json` and use
`skills["local_tavor_veloce_xwave-on"]`; all fields below are relative to that entry. Save the
whole document atomically, preserving every other skill's data. Save each
explicit choice immediately: requested `action` (enable, disable, or open), target
`module`, `veloce_alias`, `build_path`, and `emulation_path` under `selection`.
Keep unknown values `null`; a generic reminder does not require making choices.
Use `status: in_progress` and `step: context_selected` when context is provided.

When upstream checkpoints contain build/emulation choices, saved context must
match them; otherwise clear stale context and ask the user. If no upstream
selection exists, obtain manual context directly without requiring connection.
Local checkpoint updates are allowed, but do not perform remote checks here.
On resume, present saved context as prior choices and have the user confirm it
before applying instructions; no saved value proves a live emulator state.

After presenting the reminder, save `status: completed` and
`step: reminder_shown`. Record configuration or trace outcomes under
`verification` only when explicitly reported by the user, with
`source: user_report` and `reported_at`; otherwise leave them `unknown`.
Giving instructions does not prove dumping was enabled or Visualizer launched.

## Manual reference only

Remind the user of this checklist when Xwave or Tavor Veloce wave dumps are
relevant. Present the steps for the user to perform manually; do not edit build
files, connect to a machine, start emulation, or launch Visualizer.
This is an on-demand reminder, not a scheduled notification.

The procedure below was supplied by the user. It is not independently verified
against an emulator build. If applying it to a specific run, obtain the target
module, `<BUILD>` directory, and `<EMU>` run directory before filling in paths.
For a general reminder, retain the placeholders.

## Manual checklist

1. **Check module availability in this build.** Inspect
   `<BUILD>/veloce_directives/xwave_sig.list` and verify the requested module
   appears. If it is absent, stop: the module is not included in this build's
   Xwave signal list. Do not invent a build or signal-generation procedure.

2. **Enable Xwave configuration.** Open
   `<BUILD>/tcl_files/tavor_debug_dfi_veloce.tcl` and uncomment both lines:

   ```tcl
   velocecmd "xwave on"
   velocecmd "xwave select_all_groups"
   ```

   To disable this configuration, comment both lines again:

   ```tcl
   #velocecmd "xwave on"
   #velocecmd "xwave select_all_groups"
   ```

   If a required file or either command is missing, report that prerequisite
   and stop rather than inventing replacement content. Commenting these lines
   configures activation; it is not a command to stop an already running dump.

3. **Run emulation using the user's existing procedure.** No emulation launch
   command is supplied by this reference. Editing the Tcl file alone does not
   create a dump.

4. **Check the dump after the run.** The dump location is
   `<BUILD>/<EMU>/veloce.wave`. Expect a `tbx.stw` directory inside it:
   `<BUILD>/<EMU>/veloce.wave/tbx.stw`.
   If `tbx.stw` does not exist, the dump failed according to this procedure.
   Its presence alone does not establish that the dump is complete or useful.

5. **Open the dump manually.** From `<BUILD>/<EMU>/veloce.wave`, run:

   ```sh
   visualizer -tracedir tbx.stw
   ```

   The relative trace path is resolved from that working directory, not the
   build root.
