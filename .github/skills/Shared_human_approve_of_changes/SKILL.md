---
name: Shared_human_approve_of_changes
description: Use after completing changes in ec_accurev_git when the user needs a module checked for build readiness and human approval before publication, or requests Shared_human_approve_of_changes.
---

# Shared_human_approve_of_changes

## Purpose

Give the user a checked build and a human review checkpoint after implementation.
Build success means **ready for testing**, not runtime test PASS.

Trigger phrase: "Shared_human_approve_of_changes" / "human approve changes"

## Assistant workflow

1. **Select the target.** Resolve the actual firmware checkout and read its
   applicable instructions. Inspect branch, HEAD, status and task changes;
   preserve unrelated and staged work. Use `ask_user` to select the project
   first: **EC, BMC or TPM**. Then discover that project's modules/solutions
   and ask which module to check. Ask for a configuration supported by that
   solution; never default silently to Booter, Release or the previous target.

2. **Confirm the build.** Identify the existing project-specific build workflow.
   For BMC, invoke `local-building-bmc-modules` and follow its checks and
   repository task runner. Its normal **Clean + Rebuild** satisfies this step:
   do not add `ClearArtifacts`, delete `.vs`, or invoke the artifact-clearing
   skill. Disclose and obtain approval for any configuration-specific extra
   cleanup, including `A35_Release`. For EC/TPM, use a verified existing
   project-specific skill/workflow; if unavailable, stop and explain the gap.
   Never substitute BMC commands. Show the resolved checkout, module,
   configuration, commands and write/delete effects; obtain build approval.

3. **Clean and build.** Run only the approved workflow. Check its exit status,
   complete summary and expected fresh outputs according to the build skill.
   Inspect post-build Git status for generated changes. On any failure or
   missing evidence, stop before review/publication and report the blocker.
   Do not silently retry, expand cleanup or fix unrelated failures.
   On success, report: "Clean + Rebuild passed; ready for testing.
   Runtime tests were not run." Do not launch Host.exe, remote jobs or hardware.

4. **Open human review.** Invoke `shared_review_changes`; follow its repository
   selection and side-by-side diff workflow. Confirm the reviewed repository
   matches the checked firmware checkout. Include staged and untracked task
   files in the review scope; ordinary `git diff` omits new files.
   If the review tool cannot display them, show their full contents explicitly.
   Ask for the user's review decision with `ask_user`. Rejection, cancellation
   or no response leaves the changes uncommitted. Do not equate opening an
   editor with approval or claim its tabs appeared without evidence.

5. **Request publishing permission.** After review approval, read the
   applicable Git safety instructions. Display the complete unstaged/staged
   diff and status, plus full new-file contents intended for this commit.
   Identify the exact task files, commit message, remote and destination branch.
   Disclose any earlier unpushed commits that the push would also publish.
   Ask explicitly: **"Commit & push these changes?"** Review approval or
   approval to create this skill does not authorize either operation.
   A commit-only request does not authorize a push.

6. **Publish only when explicitly authorized.** Stage only approved changes;
   never use blanket staging or include unrelated pre-staged changes. Check
   the complete staged diff matches approval before committing. Apply required
   commit trailers. Verify commit identity/content, then push only to the
   confirmed destination if push was authorized. Verify the remote branch
   points to the intended commit. Report commit and push outcomes separately;
   on failure, stop without force-push, reset, amend or automatic retry.

7. **Invalidate stale approval.** If sources, build inputs, configuration,
   checkout/HEAD or reviewed diff change, stop publication and repeat affected
   build/review/authorization steps. Report the scope actually built; a single
   module build does not validate all consumers of shared code.

## Manual Bash workflow

These are examples for Bash on the Windows build machine, not authorization
to execute them. Replace the checkout, module and configuration with the
confirmed target. Follow the build skill's preflight and output checks.

```bash
pwsh.exe -NoProfile -Command 'Set-Location "C:\CCSystem\ec_accurev_git"; & ".\BMC\.vscode\BmcModuleTask.ps1" -Action BuildModuleConfiguration -WorkspaceFolder (Resolve-Path ".\BMC").Path -Module BMC_template -Configuration Release; exit $LASTEXITCODE'
```

Runs BMC's existing Clean + Rebuild task and propagates its exit status.
This is not an EC/TPM build command.

```bash
git -C 'C:\CCSystem\ec_accurev_git' status --short
git -C 'C:\CCSystem\ec_accurev_git' --no-pager diff
git -C 'C:\CCSystem\ec_accurev_git' --no-pager diff --staged
```

Lists pending files and displays both diff layers. Read new files separately.
Use `shared_review_changes`' manual workflow for side-by-side VS Code review.
Only after explicit publishing approval, run the reviewed, exact-file
`git add`, `git commit` and destination-specific `git push` commands individually.

## Notes / approval

- This skill coordinates existing skills; it does not create missing EC/TPM
  build tooling or authorize broader artifact deletion.
- A build cannot establish runtime behavior, emulator readiness or scenario PASS.
- Keep the working tree for review if any gate is declined or blocked.
- Never commit parent-repository submodule pointers or publish to the
  marketplace as an incidental part of this firmware workflow.
