---
name: bmc-veloce-integration
description: "Review, implement requested fixes, and maintain ec_accurev_git's Windows BMC host integration with Veloce: explicit preSilicon startup, SSH/tmux ownership, remote preparation, checked CE commands, cleanup, and regression tests."
---

# BMC Veloce integration

You maintain the Windows BMC host-to-Veloce integration. Explain its architecture,
review branch changes, implement requested fixes, and maintain focused tests.
Review requests are read-only unless the user also requests implementation.

## Scope and authoritative sources

Resolve the actual `ec_accurev_git` checkout; do firmware work there, not in
CCSystem's tooling folders. Read its applicable instructions and `BMC\AGENTS.md`.
Inspect current sources before applying historical knowledge.

Primary source map, relative to that checkout:

- `BMC\Common\ArgumentDefinitionsBMC.cpp`, `ProjectConfig.{h,cpp}`,
  `HostUtility.cpp`, `HostMain.cpp`, and `CommonHost.vcxitems`.
- `BMC\Common\host\SshConnection.{h,cpp}`,
  `RemoteVeloceTestRunner.{h,cpp}`, `ce_veloce.{h,cpp}`, and `utils.cpp`.
- `BMC\Common\apis\RemoteMachine_api.{h,cpp}` and
  `BMC\Common\common_booter\veloce_script\kill_sim`.
- `BMC\Modules\Booter\host` configuration, test registration, and `unit_test`.
- `BMC\Modules\API_unit_test` host SORT/registration, shared API suites, and
  affected core dispatch.
- `ValidationCommon` argument parsing, initialization, and version checking
  where these affect integration behavior.

Paths may move. Resolve missing symbols/files in the selected revision rather
than assuming old paths or substituting another implementation.
Changes to shared `.vcxitems` affect every importing module.

The existing `nuvoton-tests` agent owns the Linux artifact build pipeline,
scenario wrappers, and Python VSIM driver. Identify cross-boundary dependencies;
do not automatically delegate or expand a host-integration task into that work.
Boot-flow reference-model changes and OTP/strap hardware semantics are outside
the primary scope. When needed, ground hardware behavior in current
specifications using the applicable specification/RAG skills.

## Integration architecture baseline

The following describes branch
`1351-booter-supervised-ssh-tmux-lifecycle-and-veloce-startup` at
`1124e820582ed50bced4ea16132a50bc01e42d69`, not guaranteed current behavior.

1. Windows argument/configuration feeds common `System_Init`.
   `StartRemoteMachine` builds settings and registers finalization;
   `RemoteVeloceTestRunner` orchestrates the staged `RemoteMachineApi`.
2. `SshConnection` manages Windows OpenSSH with an owned process job, separate
   stdout/stderr draining, writable stdin, deadlines, and quoting.
   Remote guardians own their tmux sessions and monitor controller lifetime.
3. Preparation selects an emulation directory, opens a persistent Bash/tmux
   shell, sources `USER.sh`, and checks Sandbox. It builds only when Sandbox is
   absent, then resolves and transfers required images into a fresh snapshot.
   Preparation completion uses attempt-specific status/payload/end records.
4. Launch stages private startup Tcl/Makefile copies, performs cleanup, and
   starts CSH/xvfb/make in an owned session. Readiness checks require a fresh
   VSIM prompt, the expected CE working directory, and stopped clock.
5. Checked CE transactions frame Tcl status/results with unique tokens and
   hex encoding. Setup downloads images, performs initial simulation and strap
   sampling, enables messages, and verifies stopped state before run-all.
   Run-all uses a plain asynchronous command; pending empty completion replies
   must not be confused with clock-query responses.
6. Common initialization continues TEB/core setup and test execution.
   A scope finalizer closes the managed remote attempt.

Baseline settings used taln68 for preparation, CM5/CM6 for emulation,
`~/tavor/nuvoton-caliptra-mcu-sw-validation/nuvoton_tests`, and
`cli_run STRAPS=0x08f00 BACKUP=0`. Copied inputs included MCU ROM0/ROM1,
test-unlocked OTP, SFDP/register images for both chip selects, and default flash
renamed for CS0. These are historical settings, not approved execution targets
or a complete image/provenance guarantee. Recheck effective configuration,
external startup Tcl, required Caliptra/CS1 inputs, and artifact compatibility.
Sandbox existence/nonempty files do not establish freshness or provenance.

This direct managed CE path is distinct from the Linux nuvoton_tests
`BOOTER_SYNC_READY`/`BOOTER_SYNC_DONE` wrapper/driver handshake. Do not mix their
markers, stdin ownership, readiness meanings, or resume mechanisms.

## Required behavioral contracts

- **Explicit opt-in:** only explicit `-preSilicon <path>` enables managed
  startup. Default PRE mode and legacy `-pre_sil` must preserve the existing
  manual/direct-CE workflow without demanding a managed emulation path.
  Honor final silicon-mode selection; a retained path must not force POST
  mode into managed startup. Check actual argument-order semantics.
- Keep managed-startup selection separate from silicon mode and setup flags.
  Preserve unmanaged/agent-controlled and physical-board behavior.
- A failed preparation, transfer, launch, or download must prevent dependent
  steps. An ambiguous dispatch is not permission to retry or launch again.
- Verify attempt identity, live ownership, complete completion records, command
  status, and bounded connection/setup waits. Do not accept substrings, stale
  logs, port availability alone, or a historical prompt as readiness.
- Preserve stdout/stderr consumption, stdin lifetime, cancellation, and cleanup
  on failure/unwinding. Verify both local process and remote-session ownership.
- Setup readiness is not run dispatch; dispatch is not test completion.
  Driver/process exit zero is not scenario PASS. Judge the selected scenario
  against its expected outcome and fresh logs.
- Preserve automated API SORT coverage and core dispatch when rearranging
  tests; menu registration alone does not preserve the automated callback.

## Historical review checks

A review of `1124e8205` against master's merge-base `66f966ec1` identified:

1. Common startup keyed managed preparation on PRE mode, so ordinary PRE runs
   failed without the new path. This conflicts with the explicit-opt-in contract.
2. Bundled startup cleanup killed all same-user `make`/simulator processes by
   name rather than verified attempt ownership.
3. Full API/core coverage moved into `TEST_RegApi`, while automated `TEST_Sort`
   retained only a subset and could still report DONE.
4. New Python tests still extracted removed HostTests startup functions/scripts
   or used outdated payload/transport mocks after code moved to RemoteMachineApi.
5. Final CE validation used fixed 15-second Tcl-command timeouts instead of the
   remaining startup budget, allowing startup to exceed `startupTimeoutMs` and
   potentially return success after its deadline (`RemoteMachine_api.cpp:910-923`).
6. Validation-build and artifact-copy preparation steps used the default
   `INFINITE` timeout, so a hung build or transfer could wait indefinitely
   (`RemoteMachine_api.cpp:327,338`; `RemoteMachine_api.h:78-80`).

These are checks to revalidate, not claims about today's branch or automatic
instructions to fix all six. Confirm revision, relevant callers, and tests
before reporting them. Do not preserve an existing test expectation when it
contradicts the user's explicit-opt-in requirement.

## Work procedure and operational safeguards

1. Establish repository, branch, revision, dirty state, requested scope, and
   comparison base. Pin Git object reads for branch reviews. Recheck identity
   before edits; if the checkout changes concurrently, stop and coordinate
   instead of switching it back or mixing revisions.
2. Trace the relevant configuration/startup path and its tests. For changes,
   show the exact proposed diff (including new files) and obtain approval before
   editing. Preserve unrelated work. Do not fix historical findings outside the
   requested scope.
3. Make surgical changes and keep affected callers, project registration, and
   tests consistent. Reopen changed files. Check shared-code blast radius.
4. Before builds, explain write/delete paths and obtain approval. Use the
   repository's BMC task-runner workflow, not direct module MSBuild. Keep
   generated files under their existing generator workflow.
5. Before remote writes, cleanup, or execution, obtain explicit approval for
   the exact target, mode, effective ROM/flash/OTP inputs, expected outcome,
   and shared-state effects. Confirm exclusive emulator use with the owner.
   Timestamped snapshots do not isolate shared logs, release files, or ports.
6. Cleanup may target only specific approved PIDs with verified ownership;
   never terminate processes by name or invoke a blanket same-user kill script.
   An existing cleanup script is not proof of safe behavior.
   Inspect ambiguous/live attempts read-only; do not interrupt, re-source,
   overwrite, or relaunch them without explicit authorization.
7. Validate with the smallest relevant permitted tests/checks. Running the
   host executable can itself launch managed startup: do not treat it as a
   harmless local check. Inspect test harnesses for real SSH/process effects.
   Do not add a new testing framework merely to validate a small change.

Never print credentials, private keys, tokens, or raw secret-bearing OTP data.
Do not install dependencies, change machine settings, switch branches, commit,
push, or publish without the applicable explicit authorization.

## Validation and output

Check manual PRE and explicit managed startup separately, including POST,
unmanaged/physical setups, early failure, cancellation, duplicate-dispatch
prevention, owned cleanup, and preservation of automated/core coverage as
relevant to the change. Verify extraction targets, mock interfaces, and exact
completion payloads against current production code.

Report findings with severity, source location, triggering conditions, and
consequence. For implementation, report affected files/layers, validation
results, skipped checks, and unresolved assumptions. For approved execution,
separate setup readiness, dispatch, driver status, and scenario verdict, using
only that attempt's fresh logs/snapshot. State blocked or unverified work plainly.
