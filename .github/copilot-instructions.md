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
                    gitlab-mcp/   outlook-mcp/   teams-mcp/
                    Shared-Module-Host-convert-to-param/
                    shared-module-convert-test-and-parm/
.github/agents/   Custom agent definitions (must live under .github/ for the
                  Copilot CLI to recognize them; reserved, populate as
                  agents mature)
copilot-marketplace/  Submodule → published marketplace (finished product)
ec_accurev_git/       Submodule → firmware/validation work repo
```

Keep this section in sync with `README.md`'s layout description if either
changes.

## Workflow rules

- **Adding a new skill / agent / MCP server**: build and iterate under
  `.github/skills/` or `.github/agents/` in CCSystem first. Don't add new,
  unproven items directly to `copilot-marketplace`.
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

## Security

- **Never commit private keys or secrets.** `id_rsa`, `*.pem`, `*.key`, `.env`
  are git-ignored. Keep SSH keys in `~/.ssh`.
- MCP code and configs reference internal hostnames and project paths; keep
  this repository private unless those references are removed.
