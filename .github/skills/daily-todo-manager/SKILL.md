---
name: daily-todo-manager
description: Manages daily to-do lists by asking for tasks, assigning 0-9 priorities (0 is highest), and organizing the list. Use when the user wants to plan their day or tasks.
---

# Daily Todo Manager

This skill helps the user collect, prioritize, and arrange their daily tasks using a 0-9 priority scale where 0 is the highest priority.

## When to Use

- The user wants to manage, create, or organize their daily to-do list.
- The user asks to arrange their tasks for the day.

## Workflow

1. **Ask for Tasks**: If the user hasn't provided any tasks, politely ask them to list the tasks they need to complete.
2. **Ask for Priorities**: Ask for a 0–9 priority for every task that does not already have one. Explicitly remind the user that 0 is highest and 9 is lowest. Never omit, discard, or ignore a task because its priority is missing.
3. **Preserve Unprioritized Tasks**: If the user cannot provide a missing priority yet or is unavailable, keep the task in today's file with priority `TBD` and `[ ]` status, then ask again when possible. Do not guess its priority. Keep `TBD` tasks after all numbered priorities until the user assigns a weight.
4. **Organize the List**: Sort tasks with numeric priorities in ascending order (0 at the top, down to 9); retain unprioritized `TBD` tasks at the bottom until their weights are provided.
5. **Present the Plan**: Display the list using a clean Markdown table or numbered list. Group tasks with the same weight together and make any `TBD` priorities explicit.

## Storage

Persist the list outside the chat so it survives across sessions:

- Location: `~\.copilot\daily-todo\YYYY-MM-DD.md` (one file per day, personal, outside any git repo). Create the folder if missing.
- Format: a Markdown table with columns `Priority | Task | Done` (`[ ]` / `[x]`), sorted by numeric priority ascending; temporary `TBD` priority rows go after numbered rows.
- At the start: if today's file exists, read and show it; do not carry unfinished tasks from a previous day into an existing list.
- If today's file does not exist and the user is creating one, find the most recent previous daily file and ask separately for each unfinished (`[ ]`) task whether to move it to today's list. Carry only the tasks the user explicitly selects, keeping their existing priorities. If the user does not answer, do not carry any tasks automatically.
- After every change (add, re-prioritize, mark done, remove): rewrite the file with the edit/create tools and tell the user the path.

## Gotchas

- Do not assume weights for the tasks; explicitly ask the user for them and preserve tasks with missing weights as `TBD` rather than dropping them.
- Ensure the user understands that lower numbers equal higher priority.
