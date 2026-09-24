# CCSystem — Copilot agents, MCP servers & skills

Personal/shared Copilot tooling extracted from the `ec_accurev_git` firmware
repo so it can be versioned independently.

## Layout

```
.github/skills/   Copilot skills, including bundled MCP servers:
                    gitlab-mcp/   outlook-mcp/   teams-mcp/
                    Shared-Module-Host-convert-to-param/
                    shared-module-convert-test-and-parm/
                    weekly-mail/  (weekly WW status mail drafter)
.github/agents/   (reserved) custom agent definitions
ec_accurev_git/   git submodule → firmware repo (added separately)
```

## MCP servers

Each `*-mcp` skill ships a Python server under `skills/<name>/server`. Install
with `pip install -e .` in that folder, then register the server in your
client's MCP config (VS Code `.vscode/mcp.json` or Copilot CLI
`~/.copilot/mcp-config.json`). See each skill's `server/README.md`.

## Security

- **Never commit private keys or secrets.** `id_rsa`, `*.pem`, `*.key`, `.env`
  are git-ignored. Keep SSH keys in `~/.ssh`.
- MCP code and configs reference internal hostnames and project paths; keep this
  repository private unless those references are removed.
