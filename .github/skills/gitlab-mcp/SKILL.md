---
name: gitlab-mcp
description: Query GitLab merge requests and issues through a local MCP server. Use when you need to list, inspect, and review GitLab project work items with API-backed evidence.
---

# GitLab MCP Skill

This repository ships a local GitLab MCP server under
`.github\skills\gitlab-mcp\server`. Two clients are configured to launch it over
stdio:

- **VS Code** - `.vscode\mcp.json` (server id `gitlab-review`, tracked, uses
  `${userHome}` so it contains no hard-coded user name)
- **Copilot CLI** - `~\.copilot\mcp-config.json` (server id `gitlab-review`,
  per-user, not committed)

Both launch the installed `gitlab-review-mcp.exe` console script, so
`pip install -e .` in the `server` directory is a prerequisite. Each client
spawns its own server process; no port is opened and no server has to be started
by hand. See `server\README.md` for setup and troubleshooting.

Use this skill when you need to:

- check the status of a merge request you opened: comments, pipeline, reviewers
- review a merge request assigned to you: changes, inline comments, pipeline
- list merge requests for a GitLab project
- inspect a merge request, including threaded discussions and raw diffs
- list issues for a GitLab project
- list repository branches, optionally filtered by name or tip-commit author
- inspect an issue, including notes
- resolve a GitLab project from `group/project` or numeric project id

## Required environment

The server reads its connection settings from environment variables:

- `GITLAB_BASE_URL` - full GitLab API v4 base URL, for example `https://gitlab.example.com/api/v4`
- `GITLAB_TOKEN` - personal, project, or group access token with `api` scope
- `GITLAB_DEFAULT_PROJECT` - optional default project path such as `group/project`
- `GITLAB_ALLOW_WRITE` - optional, `1`/`true`/`yes` enables the comment-posting tools

`GITLAB_BASE_URL` and `GITLAB_DEFAULT_PROJECT` are set in the client
configuration. `GITLAB_TOKEN` is deliberately kept out of configuration files and
must be inherited from the environment, so set it as a persistent user variable
and restart the client:

```powershell
[Environment]::SetEnvironmentVariable("GITLAB_TOKEN", "<token>", "User")
```

`GITLAB_ALLOW_WRITE` is **off by default** so that no tool call can post to
GitLab by accident. Every write tool fails with an explicit message until it is
enabled. Set it the same way, at user scope, and restart the client:

```powershell
[Environment]::SetEnvironmentVariable("GITLAB_ALLOW_WRITE", "1", "User")
```

Writing also requires the token to carry the `api` scope - `read_api` can read
everything here but cannot post a comment. `health()` reports `write_enabled` so
the current state is always visible.

## Available MCP tools

Read:

- `health()` - also reports `write_enabled`
- `resolve_project(project="")`
- `list_branches(...)`
- `list_merge_requests(...)` - includes reviewers, assignees, and merge status
- `get_merge_request(project, iid, include_notes=False, include_approvals=False)`
- `get_merge_request_approvals(project, iid)`
- `get_merge_request_pipelines(project, iid)`
- `get_pipeline_jobs(project, pipeline_id, scope="")`
- `list_merge_request_discussions(project, iid, include_system=False, resolved=None)`
- `list_merge_request_changes(project, iid, path_filter="", include_diff=True)`
- `get_merge_request_raw_diff(project, iid)`
- `list_issues(...)`
- `get_issue(project, iid, include_notes=False)`

Write - all require `GITLAB_ALLOW_WRITE`:

- `create_merge_request_note(project, iid, body)`
- `create_merge_request_diff_comment(project, iid, body, new_path, new_line, ...)`
- `reply_to_merge_request_discussion(project, iid, discussion_id, body)`
- `resolve_merge_request_discussion(project, iid, discussion_id, resolved=True)`

## Workflow A - status of a merge request I opened

1. `list_merge_requests(author_username="<me>", state="opened")` to find the MR
   iid. `health()` returns the current username.
2. `get_merge_request(iid)` for the overview: `reviewers` and `assignees` show
   who has to review it, `head_pipeline` shows the pipeline result, and
   `detailed_merge_status` / `has_conflicts` show whether it can merge.
3. `list_merge_request_discussions(iid)` to read the comments. This is threaded,
   covers every page, and hides system notes; use `resolved=False` to see only
   the threads still waiting on a response.
4. `get_merge_request_approvals(iid)` for who approved, when the instance
   supports approvals.
5. If the pipeline failed, `get_pipeline_jobs(pipeline_id, scope="failed")` names
   the failing job.

## Workflow B - reviewing a merge request assigned to me

1. `list_merge_requests(reviewer_username="<me>", state="opened")` to find work
   awaiting your review.
2. `list_merge_request_changes(iid)` to read the change file by file. Start with
   `include_diff=False` for an overview on a large MR, then narrow with
   `path_filter`. Use `get_merge_request_raw_diff(iid)` when one continuous diff
   is easier.
3. `get_merge_request_pipelines(iid)` to confirm CI passed before reviewing.
4. `list_merge_request_discussions(iid)` to avoid repeating a point someone
   already raised.
5. Comment:
   - line-specific feedback: `create_merge_request_diff_comment(iid, body,
     new_path=..., new_line=...)` using the paths and line numbers from step 2
   - overall feedback: `create_merge_request_note(iid, body)`
   - follow-up in a thread: `reply_to_merge_request_discussion(...)`
   - closing a thread: `resolve_merge_request_discussion(...)`

## Running the server manually

Manual startup is only needed for troubleshooting, for driving the server with
`curl`, or for sharing one instance between clients. It is not part of normal
use.

Stdio cannot be driven usefully by hand - there is no address to send requests
to - so run it over HTTP instead:

```powershell
cd C:\ec_accurev_git\.github\skills\gitlab-mcp\server

$env:PYTHONPATH = "$PWD\src"
$env:GITLAB_BASE_URL = "https://gitlab2.nuvoton.co.il/api/v4"
$env:GITLAB_TOKEN = "<token>"

python -m gitlab_mcp.server --transport streamable-http --host 127.0.0.1 --port 8766 --path /mcp
```

The endpoint is then `http://127.0.0.1:8766/mcp`. Drive it from a second shell.
Because PowerShell mangles inline JSON, write each request to a file first.

Initialize a session and read the `mcp-session-id` response header:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0.1"}}}' |
  Out-File -Encoding utf8 -NoNewline init.json

curl.exe -s -D - -X POST http://127.0.0.1:8766/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -d "@init.json"
```

Send the required `initialized` notification, then call a tool, reusing that
session id on every subsequent request:

```powershell
'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' |
  Out-File -Encoding utf8 -NoNewline initialized.json

'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"health","arguments":{}}}' |
  Out-File -Encoding utf8 -NoNewline health.json

curl.exe -s -N -X POST http://127.0.0.1:8766/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Session-Id: <session-id>" `
  -d "@health.json"
```

Use `tools/list` to inspect the registered tools and their argument schemas.

To point a client at a manually started server instead of letting it spawn one,
switch that client's entry to HTTP (`"type": "http"` with
`"url": "http://127.0.0.1:8766/mcp"`) and drop `command`, `args`, and `cwd`. The
client `type` and the server's `--transport` must always describe the same
transport.

## Notes

- Prefer explicit `project` arguments unless `GITLAB_DEFAULT_PROJECT` is set.
- The server uses GitLab REST API v4 and keeps auth in headers only.
- Do not log or hardcode tokens in files.
- TLS verification uses the Windows certificate store via `truststore`, which is
  what allows the internal GitLab certificate to validate without a PEM bundle.
- `list_merge_request_discussions()` paginates fully and is the right tool for
  reading review comments. `get_merge_request(include_notes=True)` and
  `get_issue(include_notes=True)` still return only the first page of raw notes.
- Inline comments are anchored to the merge request `diff_refs`. Those are
  fetched automatically, but a new push invalidates them, so re-read
  `list_merge_request_changes()` before commenting on a busy merge request.
- `get_merge_request_approvals()` returns `{"supported": false}` instead of
  failing when the instance does not offer the approvals API.
