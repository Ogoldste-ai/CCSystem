---
description: 'Manual Mode: teach the user to perform a task themselves, one command-line step at a time'
applyTo: '**'
---

# Manual Mode

## Purpose

Manual Mode is an **opt-in teaching mode**. Instead of Copilot performing the
user's task itself, Copilot builds a plan and walks the user through it one
command-line step at a time, so the user learns to perform the task on their
own.

## Default state: OFF

This instruction is **off by default**. There is no CLI-level toggle for it —
activation is controlled entirely by the trigger phrase below, evaluated by
you (the agent) against the user's own message text.

## Activation

- **Trigger phrase**: the user's prompt contains the phrase `manual mode`
  (case-insensitive, anywhere in the message).
- Once triggered, Manual Mode stays active for the rest of that task/session
  until either:
  - the user says `manual mode off` (deactivate — confirm briefly, then
    resume normal behavior for the rest of that task), or
  - the task is completed.
- If the trigger phrase is not present, ignore this file entirely and behave
  normally (execute tasks yourself as usual).

## Behavior when active

1. **Do not execute the task yourself.** Do not run the commands that
   accomplish the user's task on their behalf.
2. **Create the plan using a high-capability model.** Because this
   instruction explicitly requires it, delegate plan creation for the user's
   task to a sub-agent (`task` tool) with an explicit model override of
   `claude-opus-5.5`. If that model is unavailable, fall back to
   `claude-opus-5`, then to `claude-opus-4.8` — i.e. "Opus 4.8 or higher".
   Give the sub-agent full context of the user's task and ask it to return a
   complete plan broken into ordered command-line steps.
3. **Split the plan into individual command-line steps.** Each step should
   be one runnable command (or a small tightly-related group of commands)
   that the user can copy/paste and execute themselves.
4. **Present exactly one step at a time**:
   - Show the exact command(s) to run.
   - Give a short (1-2 line) reason for the step.
   - Stop and wait for the user to run it themselves — do not run it for
     them.
5. **Adapt after each step.** After the user reports back the command's
   output/result, use that result to adjust the remaining plan if needed
   (e.g. skip a step that's no longer necessary, add a step to handle an
   error, change a path/value based on actual output), then present only the
   next single step.
6. **Repeat** until the plan is complete, then briefly summarize what was
   accomplished.

## Notes

- This file lives in this repo (`CCSystem`) only. Copy it to
  `$HOME/.copilot/instructions/manual_mode.instructions.md` if you want
  Manual Mode available in all repos/sessions.
- Manual Mode does not change permission settings or other instructions —
  it only changes *who* executes the commands and *how* the plan is
  delivered.
