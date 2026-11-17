---
name: shared_review_changes
description: Open the changed files of a git repo in side-by-side diff views (left = original, right = updated) in VS Code. Use when the user wants to review changes, a branch, or a commit visually.
---

# Review changes side by side

Trigger phrase: "review changes" / "show diff side by side"

## Purpose

Show the user a side-by-side diff of what changed: the **original** version on
the left and the **updated** version on the right. The assistant cannot render
this inside the chat, so it opens VS Code diff tabs on the user's machine.

## Assistant workflow

1. Discover every git repo in the workspace that has changes, then **ask which
   one to review before showing anything**. Do not guess or default.
   - Find repos: the workspace root, its submodules, and nested clones, e.g.

     ```powershell
     $root = (Get-Location).Path
     $repos = @($root) + (git -C $root submodule foreach --quiet 'echo $toplevel/$sm_path' 2>$null) +
         (Get-ChildItem $root -Directory -Recurse -Depth 2 -Force -Filter .git -ErrorAction SilentlyContinue |
             ForEach-Object { $_.Parent.FullName })
     $repos = $repos | ForEach-Object { (Resolve-Path $_).Path } | Sort-Object -Unique
     foreach ($r in $repos) {
         $n = (git -C $r status --short 2>$null | Measure-Object).Count
         if ($n) { "{0}  ({1} changed)" -f $r, $n }
     }
     ```

   - Show only repos with changes (uncommitted changes, or new commits in a
     submodule), with the changed-file count, for example: CCSystem,
     copilot-marketplace, ec_accurev_git, pdftomd-rag.
   - Ask with `ask_user` (single-select of those repos; the user can also type
     another path). If exactly one repo has changes, still confirm it. If none
     have changes, say so and stop.
   - Only after the user picks a repo continue; all later steps use that repo
     as `$repo`. Note a parent repo lists a submodule as one modified entry;
     review the submodule as its own repo, not through the parent.
2. Choose what "original" means; default is `HEAD` (uncommitted work):
   - uncommitted changes -> base `HEAD`
   - a branch review -> base is the merge-base with `master`
     (`git merge-base master HEAD`), compared against the working tree
   - a commit -> base `<sha>^`
3. List the changed files first (`git diff --name-status <base>`) and show the
   list. If there are more than ~10 files, ask which to open so the user is not
   flooded with tabs.
4. For each file, write the original version to a temp folder and open the
   diff. Added files diff against an empty file. Do not edit the temp copies.

   ```powershell
   $repo = 'C:\path\to\repo'; $base = 'HEAD'
   $tmp = Join-Path $env:TEMP ('review_' + (Get-Date -Format yyyyMMdd_HHmmss))
   New-Item -ItemType Directory -Force $tmp | Out-Null
   foreach ($f in git -C $repo diff --name-only $base) {
       $left = Join-Path $tmp ($f -replace '[\\/]', '__')
       git -C $repo show "${base}:$f" 2>$null | Set-Content -Encoding utf8 $left
       if (-not (Test-Path $left)) { New-Item -ItemType File $left | Out-Null }
       Start-Process code -ArgumentList '--diff', "`"$left`"", "`"$(Join-Path $repo $f)`"" -WindowStyle Hidden
   }
   ```

5. Tell the user what was opened (which base, how many tabs), that left is
   original and right is updated, and that they can jump between changes with
   `F7` / `Shift+F7`. State that you could not verify the tabs appeared.
6. Offer to delete the temp folder when the user is done. Never commit or push.

## Manual bash workflow

```bash
git submodule foreach --quiet 'echo "$displaypath: $(git status --short | wc -l) changed"'; git status --short | wc -l
```
Shows how many changed files each submodule has, plus the current repo, so you
can pick which repo to review.

```bash
git diff --name-status HEAD
```
Lists the changed files and whether each is added, modified or deleted.

```bash
git config diff.tool vscode && git config difftool.vscode.cmd 'code --wait --diff "$LOCAL" "$REMOTE"'
```
One-time setup that makes VS Code the diff tool for this repo.

```bash
git difftool --dir-diff HEAD
```
Opens all changes against `HEAD` in one side-by-side view. For a branch review
use `git difftool --dir-diff master...HEAD`.

```bash
code --diff <original-file> <updated-file>
```
Opens a single side-by-side diff of any two files.

## Notes / approval

- Read-only: this skill never stages, commits, pushes or modifies tracked files.
- Requires `code` (VS Code) on PATH; if missing, fall back to `git diff` or
  ask which tool to use.
- The left-side copies live in `%TEMP%`; edits there are not saved to the repo.
