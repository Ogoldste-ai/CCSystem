---
description: 'Git safety: show the full diff before committing, and never commit or push without an explicit user request'
applyTo: '**'
---

# Git commit & push safety

## Purpose

Committing and pushing are the points where work stops being local and
reversible. A commit rewrites the repository's history; a push makes it
visible to everyone and, on a shared branch, effectively permanent. These
rules make sure the user sees exactly what is being recorded, and decides
when it happens.

These rules are **always on**. They are not affected by autopilot, YOLO,
`--allow-all-tools`, an approved plan, or a scheduled/headless run.

## Rule 1 — Show the full diff before committing

Before creating any commit, display the complete diff of what will be
committed:

```bash
git --no-pager diff            # unstaged changes
git --no-pager diff --staged   # staged changes
git status --short             # includes untracked files
```

- Show the **whole** diff, not a summary, a file list, or a description of
  it. "I updated the parser" is not a diff.
- Include **untracked files** that are about to be added. `git diff` alone
  hides them, and a new file is just as much part of the commit as an edit.
- If the diff is genuinely too large to display in full, say so explicitly,
  show the per-file stat (`git diff --stat`), and show the full diff of the
  substantive files — never silently truncate.
- Point out anything the user should look at closely: secrets or
  credentials, generated or vendored files, large binaries, unrelated
  drive-by changes, or files that look accidentally included.

## Rule 2 — Commit and push only when the user asks

**Never run `git commit` or `git push` on your own initiative.** Both require
an explicit request from the user in the current conversation.

- An instruction to implement, fix, refactor, or "finish" something is **not**
  a request to commit. Finishing work means the code is written and verified,
  and the working tree is left for the user to review.
- Approving a plan that mentions committing is **not** a commit approval.
  Ask again at the moment the commit would happen.
- Autopilot / auto-approved tool modes remove the *permission prompt*, not the
  *requirement to be asked*. They mean "you may run commands without me
  confirming each one", not "you may decide to publish my work".
- Permission does not carry over. "Commit this" authorizes that one commit,
  not the next one later in the session.
- `git push` needs its own explicit request, separate from the commit. Being
  told to commit is not permission to push.

When work is ready but uncommitted, say so and stop: report what changed,
show the diff, and let the user decide.

## What is always allowed

Read-only git is fine without asking: `status`, `diff`, `log`, `show`,
`branch`, `remote -v`, and similar inspection commands. Use them freely to
understand the repository.

## Also treat as publishing

Apply Rule 2 to anything else that rewrites shared history or exposes work:
`git commit --amend`, `git rebase`, `git reset --hard`, `git push --force`,
tag creation/deletion, and opening or merging a pull request.
