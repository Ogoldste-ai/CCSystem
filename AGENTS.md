# Copilot instructions — CCSystem

## Purpose

CCSystem is the **development workspace** for personal/shared GitHub Copilot
tooling: skills, custom agents, and MCP servers. Everything here should be
treated as **in-development** — iterate freely, and only promote items to the
marketplace (see below) once they are stable and the user explicitly asks
for that.

## Three-repo model

This workspace spans three repositories with distinct roles. Keep work in the
repo that matches its purpose:

1. **CCSystem** (this repo) — where all new/WIP Copilot skills, agents, and
   MCP servers are authored and iterated on. This is the source of truth
   while something is under development.
2. **`copilot-marketplace`** (git submodule) — the **published product**.
   It is structured as a Copilot CLI plugin marketplace consumed by other
   repos. Only finished, stable items get promoted here as plugin packages,
   and **only when the user explicitly requests the promotion**. Do not do
   exploratory/WIP development directly in this submodule, and do not
   promote items on your own initiative.
3. **`ec_accurev_git`** (git submodule) — the **work repo** for actual
   firmware/validation engineering tasks (EC, BMC, SharedModules, TPM,
   ValidationCommon, etc.). It is unrelated to Copilot-tooling development;
   follow its own `AGENTS.md` when working there. Don't develop Copilot
   tooling inside it.

## Repo layout

```
.github/skills/   Copilot skills, including bundled MCP servers:
                    gitlab-mcp/   outlook-mcp/   teams-mcp/   teb-mcp/
                    Shared-Module-Host-convert-to-param/
                    shared-module-convert-test-and-parm/
                    weekly-mail/  (weekly WW status mail drafter)
                    hebrew-pdf-text-edit/  (edit text inside Hebrew PDFs)
                    local-building-bmc-modules/  (bounded BMC builds and incremental-cache recovery)
                    _group-template/  (template for bundling many skills into
                                       one plugin; see its README)
                    tavor_veloce/
                      AGENTS.md  (checkpoint rule for current/future skills)
                      local_tavor_veloce_xwave-on/  (manual Xwave/Visualizer reminder)
                      local_tavor_veloce_connect-to-veloce-machine/  (SSH to cm5/cm6)
                      local_tavor_veloce_active-emulation/  (choose build and emu_* directory)
                      local_tavor_veloce_source-environment/  (prepare a persistent tmux/CSH shell)
                      local_tavor_veloce_run-emulation/  (choose straps; launch once to VSIM CLI)
.github/agents/   Custom agent definitions, including the ilabu21 RAG
                  operator (must live under .github/ for the Copilot CLI
                  to recognize them)
copilot-marketplace/  Submodule → published marketplace (finished product)
ec_accurev_git/       Submodule → firmware/validation work repo
```

Keep this section in sync with `README.md`'s layout description if either
changes.

## Workflow rules

- **Adding a new skill / agent / MCP server**: build and iterate under
  `.github/skills/` or `.github/agents/` in CCSystem first. Don't add new,
  unproven items directly to `copilot-marketplace`.
- **Grouping skills**: use `.github\skills\<group>\<skill>\SKILL.md` as described
  in `.github\skills\_group-template\README.md`. Nested discovery was verified
  with Copilot CLI 1.0.105. `group.json` is local bookkeeping, not a Copilot
  manifest or an automated promotion mechanism.
- **Tavor Veloce state**: every skill under `.github\skills\tavor_veloce\`
  must follow that group's `AGENTS.md` and use the single ignored per-session
  `.copilot\state\tavor_veloce\<session-id>\progress.json`. All skills' progress/
  status lives under `skills["<skill-name>"]`; never create per-skill files.
  Save each user selection immediately, preserving other entries and applying
  dependent invalidations in one atomic save. Apply this to future skills too.
  Keep the file after each session for user review. Saved choices
  do not prove a live SSH connection or successful emulator action.
  `local_tavor_veloce_source-environment` follows `local_tavor_veloce_active-emulation`, leaves a verified tmux/CSH
  shell for future commands, and does not launch Veloce. Its entry records
  readiness; environment changes live in the remote pane, not in the JSON.
  `local_tavor_veloce_run-emulation` follows verified source readiness in that exact pane and
  records straps, guarded dispatch and a fresh numbered VSIM CLI prompt in
  its entry in that same file. Inspect existing attempts read-only before
  any source skill/CSH probe. Host/build/emulation/source invalidation clears
  launch readiness but retains old terminal/attempt identity in
  `skills["local_tavor_veloce_run-emulation"].verification.retired_attempts`; it never authorizes
  interruption, re-source, cleanup or a duplicate launch. CLI ready is not
  boot complete.
- **Promoting something to the marketplace**: only do this when the user
  explicitly requests it. When requested:
  1. Package it under `copilot-marketplace/plugins/<name>/`, with a
     `plugin.json` pointing at its `skills/` and/or `agents/` folder(s).
  2. Register the plugin in
     `copilot-marketplace/.github/plugin/marketplace.json`.
  3. Update the internal registries:
     `copilot-marketplace/marketplace/skills_catalog.json` and
     `copilot-marketplace/marketplace/agent-catalog.json`.
  4. Follow `copilot-marketplace`'s own `.github/copilot-instructions.md`
     for marketplace-specific conventions when editing inside that submodule.
- **Work tasks** (firmware/validation, not Copilot tooling): do these in
  `ec_accurev_git`, following its own `AGENTS.md`. Keep CCSystem focused on
  Copilot tooling development only.

## Submodules

Declared in `.gitmodules`:

| Path                 | Remote |
|----------------------|--------|
| `ec_accurev_git`      | `git@gitlab2.nuvoton.co.il:validation/ec_accurev_git.git` |
| `copilot-marketplace` | `git@github:Ogoldste-ai/copilot-marketplace.git` |

Common commands:

```bash
# Clone with submodules
git clone --recurse-submodules <CCSystem-url>

# Initialize/update submodules after a plain clone or pull
git submodule update --init --recursive

# Pull the latest from a submodule's own remote (e.g. after upstream changes)
git submodule update --remote copilot-marketplace

# After updating a submodule's contents, commit the new pointer in CCSystem
git add copilot-marketplace   # or ec_accurev_git
git commit -m "Bump <submodule> to latest"
```

## Code writing rules (C/C++)

- Do not add unit tests unless explicitly requested by the user.
- Follow the coding standards in the repository's `Docs\CodingStandards.cpp`
  (in CCSystem: `C:\CCSystem\Docs\CodingStandards.cpp`).
- Declare structs, classes, enums, defines and variable definitions in `.h`
  files only. ("Struct" below also means "class".)
- No hard-coded numbers (e.g. `0`, `0x05f00`); use `#define`s that describe
  what the value means.
- Document everything in `.h` files: (a) every function, (b) every enum,
  struct and define, (c) every member of each struct.

## Security

- **Never commit private keys or secrets.** `id_rsa`, `*.pem`, `*.key`, `.env`
  are git-ignored. Keep SSH keys in `~/.ssh`.
- MCP code and configs reference internal hostnames and project paths; keep
  this repository private unless those references are removed.

## Additional instruction files (read on demand)

These live in `.github\instructions\`. Read the file before acting when its
condition applies:

| File | Read when |
|---|---|
| `.github\instructions\git_commit.instructions.md` | Always before any git commit, push, amend, rebase, reset, tag or PR: show the full diff first, and never commit or push unless the user explicitly asks. |
| `.github\instructions\manual_mode.instructions.md` | The user's message contains "manual mode": teach one command-line step at a time instead of executing. |
| `.github\instructions\ec_accurev_git.instructions.md` | Working on anything under `ec_accurev_git/`. |
| `.github\instructions\BMC_booter_sync_how_to_use.instructions.md` | Running or integrating a `nuvoton_tests` UART/run-all scenario with `--booter_sync`. |
