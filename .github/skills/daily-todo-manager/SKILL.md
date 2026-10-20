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
2. **Ask for Priorities**: Once the user provides the tasks, ask them to assign a priority weight to each task from 0 to 9. Explicitly remind them that 0 is the highest priority and 9 is the lowest.
3. **Organize the List**: When the user provides the weights, sort the tasks in ascending order of weight (0 at the top, down to 9).
4. **Present the Plan**: Display the sorted daily to-do list using a clean Markdown table or numbered list. Group tasks with the same weight together.

## Storage

Persist the list outside the chat so it survives across sessions:

- Location: `~\.copilot\daily-todo\YYYY-MM-DD.md` (one file per day, personal, outside any git repo). Create the folder if missing.
- Format: a Markdown table with columns `Priority | Task | Done` (`[ ]` / `[x]`), sorted by priority ascending.
- At the start: if today's file exists, read it and show it instead of asking for tasks from scratch. If it doesn't exist, offer to carry over unfinished (`[ ]`) tasks from the most recent previous file.
- After every change (add, re-prioritize, mark done, remove): rewrite the file with the edit/create tools and tell the user the path.

## Gotchas

- Do not assume weights for the tasks; explicitly ask the user for them.
- Ensure the user understands that lower numbers equal higher priority.
