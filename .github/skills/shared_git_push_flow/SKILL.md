---
name: shared_git_push_flow
description: Use when pending Git changes in one repository need to be split into logical commits before pushing, or when the user requests shared_git_push_flow.
---

# Shared Git Push Flow

## Purpose

Create one commit per logical group of changes, then push once after all
approved groups are committed. Use ordinary Git commands, not the `git-flow`
extension or its branching model.

Trigger phrase: "shared_git_push_flow"

## Assistant workflow

1. **Select one repository.** Confirm the exact checkout, current branch, HEAD,
   and intended remote branch. Read the applicable repository instructions,
   including Git safety rules. Stop on detached HEAD or an in-progress merge,
   rebase, cherry-pick, or revert. Treat parent repositories and submodules as
   separate runs; do not include submodule pointer changes incidentally.
2. **Propose the groups.** Inspect status, both diff layers, and the full
   contents of candidate untracked files. Group changes by intent, not by file
   count. Keep dependent implementation and tests together where practical.
   Show the proposed order, paths or hunks, commit messages, and exclusions.
   Keep unrelated work out and stop rather than stage credentials or secrets.
3. **Stage and commit one group.** Show its complete proposed diff and status,
   including new-file contents, and ask for explicit authorization to stage and
   commit that group. Recheck HEAD and the relevant changes before staging.
   Use exact paths for whole-file changes and only approved hunks for mixed
   files. If the index already contains changes outside the group, or the
   approved hunks cannot be staged safely, stop. Do not unstage, stash, or
   overwrite the user's work. Show the complete staged diff and verify it
   matches the approval before running `git commit` with the required trailers.
   Verify the resulting commit and record its SHA. Repeat for each group.
4. **Approve one final push.** Once all intended groups are committed, verify
   the local branch and tip and resolve the single push URL and exact
   destination ref without exposing credentials. Check the live destination
   tip and confirm the update is a fast-forward. Show all outgoing commits,
   including any that predate this run, and identify anything left uncommitted.
   Ask for explicit push authorization covering that tip and destination.
   Stop if the destination is absent or ambiguous, the history needed for
   review is unavailable, or either tip changes after review.
5. **Push and verify.** Push the approved commit SHA to the confirmed branch
   with one explicit refspec and no force, tag, or recursive submodule push.
   Confirm the destination ref points to the approved SHA. Report the commits
   created and whether the push succeeded, was skipped, or failed. If there
   are no outgoing commits, do not push.

## Manual Bash workflow

Run these commands from the selected repository, one step at a time.

```bash
git rev-parse --show-toplevel
git symbolic-ref --short HEAD
git rev-parse HEAD
git status --short --branch --untracked-files=all
git --no-pager diff
git --no-pager diff --staged
```

Identify the checkout, branch, and current commit, then inspect unstaged and
staged changes separately. Open the candidate untracked files as well; neither
diff lists their contents.

```bash
git --literal-pathspecs add -- 'parser.cpp' 'parser_test.cpp'
git --no-pager diff --staged
git commit -m 'Handle incomplete parser records'
git --no-pager show HEAD
```

After approval, substitute the exact paths for one group and stage them. If a
file contains changes for more than one group, use `git add -p -- 'parser.cpp'`
instead for the approved hunks. Read the entire staged diff before committing;
do not run the commit command if the index includes extra changes. Substitute
the reviewed message, add required trailers, and inspect the resulting commit.
Repeat for each group.

```bash
git remote get-url --push --all "$remote"
git ls-remote --exit-code --refs "$push_url" "$destination_ref"
git merge-base --is-ancestor "$remote_tip" "$approved_tip"
git --no-pager log --oneline "$remote_tip..$approved_tip"
```

Set `remote` to the intended remote and `destination_ref` to the full branch
ref (for example, `refs/heads/my-branch`). Use the single resolved push URL for
`push_url`, the live destination SHA for `remote_tip`, and the reviewed local
SHA for `approved_tip`. Check that the remote tip is an ancestor and inspect
the complete list of commits that would be published.

```bash
git push --no-follow-tags --recurse-submodules=no -- "$push_url" "$approved_tip:$destination_ref"
git ls-remote --exit-code --refs "$push_url" "$destination_ref"
```

After separate push approval and a final tip check, send only the approved SHA
to the intended branch. Compare the returned remote SHA with `approved_tip`.

## Notes / approval

- Invoking this skill, approving the grouping, or approving this skill draft
  does not authorize a commit or push. Obtain per-group commit authorization
  and separate final push authorization in the current conversation.
- On failure, cancellation, or uncertain verification, stop and report what
  was committed and what remains staged or unstaged. Do not push a partial
  batch or automatically retry, reset, amend, rebase, or force-push.
