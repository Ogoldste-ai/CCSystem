# GitLab Review MCP Server

This MCP server connects to GitLab REST API v4 and exposes tools for merge request
and issue review workflows.

## Tools

### Read

- `health()` - auth check; also reports `write_enabled`
- `resolve_project(project="")`
- `list_branches(project="", search="", author="", name_contains="", page=1, per_page=20)`
- `list_merge_requests(...)` - summaries including reviewers, assignees, merge status
- `get_merge_request(project, iid, include_notes=False, include_approvals=False)`
- `get_merge_request_approvals(project, iid)`
- `get_merge_request_pipelines(project, iid, per_page=20)`
- `get_pipeline_jobs(project, pipeline_id, scope="", per_page=100)`
- `list_merge_request_discussions(project, iid, include_system=False, resolved=None, max_pages=20)`
- `list_merge_request_changes(project, iid, path_filter="", include_diff=True)`
- `get_merge_request_raw_diff(project, iid)`
- `list_issues(...)`
- `get_issue(project, iid, include_notes=False)`

### Write

All write tools raise `GitLabWriteDisabledError` unless `GITLAB_ALLOW_WRITE` is
enabled (see **Environment**).

- `create_merge_request_note(project, iid, body)` - merge request level comment
- `create_merge_request_diff_comment(project, iid, body, new_path="", new_line=None, old_path="", old_line=None, base_sha="", head_sha="", start_sha="")` - inline comment on a diff line
- `reply_to_merge_request_discussion(project, iid, discussion_id, body)`
- `resolve_merge_request_discussion(project, iid, discussion_id, resolved=True)`

`create_merge_request_diff_comment` fetches `base_sha`, `head_sha` and
`start_sha` from the merge request when they are not supplied. GitLab rejects a
position whose SHAs do not match the current head, and that is the most common
cause of a failed inline comment.

## Environment

The server reads its connection settings from environment variables at startup
(`GitLabConfig.from_env()`):

- `GITLAB_BASE_URL` - required, GitLab API v4 base URL
- `GITLAB_TOKEN` - required, access token with `api` scope
- `GITLAB_DEFAULT_PROJECT` - optional default project path
- `GITLAB_ALLOW_WRITE` - optional, `1`/`true`/`yes`/`on` enables the write tools

`GITLAB_ALLOW_WRITE` defaults to off. Reading is always safe, but posting a
comment is visible to the whole team and cannot be undone quietly, so the write
tools stay disabled until this is set deliberately. A `read_api` token is enough
for every read tool; posting requires `api` scope plus Developer access or above
on the project, and returns HTTP 403 otherwise.

When a client launches the server, these come from the client configuration and
the inherited environment (see **Client configuration** below). When running
manually, set them in the shell first:

```powershell
$env:GITLAB_BASE_URL = "https://gitlab.example.com/api/v4"
$env:GITLAB_TOKEN = "<token>"
$env:GITLAB_DEFAULT_PROJECT = "group/project"
$env:GITLAB_ALLOW_WRITE = "1"    # only if you intend to post comments
```

## Installation

Requires Python 3.12 or newer. From this directory:

```powershell
cd C:\ec_accurev_git\.github\skills\gitlab-mcp\server
python -m pip install -e ".[test]"
```

`-e` installs in editable mode, so edits to `src\gitlab_mcp\*.py` take effect
without reinstalling. `[test]` adds pytest.

This installs three runtime dependencies:

- `mcp` - the FastMCP server framework and transports
- `httpx` - the HTTP client used against the GitLab REST API
- `truststore` - makes TLS verification use the OS certificate store, which is
  required for GitLab servers issued by an internal corporate CA

Verify the install:

```powershell
python -m pip show gitlab-review-mcp        # check "Editable project location"
python -c "import gitlab_mcp; print(gitlab_mcp.__file__)"
python -m pytest -q
```

> The editable install records an absolute path. If this directory is ever moved
> or renamed, that path goes stale and imports break; rerun the install command
> from the new location to repair it.

Once installed, `PYTHONPATH` is no longer required - the client configurations
still set it as a harmless fallback for machines where the package was never
installed.

## Run over stdio

Normally you do not run this by hand - VS Code and Copilot CLI each spawn it
over stdio. Stdio has no address to send requests to, so it is only useful when
launched by a client.

```powershell
python -m gitlab_mcp.server --transport stdio
```

## Run over streamable HTTP

Use this when driving the server manually with `curl`, or to share a single
instance between clients:

```powershell
python -m gitlab_mcp.server --transport streamable-http --host 127.0.0.1 --port 8766 --path /mcp
```

## Client configuration

The `--transport` flag sets how the **server listens**; the client's `type` sets
how the **client talks**. They must describe the same transport.

| Scenario | `--transport` | Client entry |
|---|---|---|
| Client launches the server | `stdio` | `stdio`/`local` with `command`, `args`, `env` |
| Server already running | `streamable-http` | `http` with `url`, no `command` |

Both clients launch the installed console script `gitlab-review-mcp.exe` rather
than a bare `python` command. Bare command names are not reliably resolved by
MCP client spawners on Windows: a per-user Python install is absent from the
machine PATH, and a zero-byte Microsoft Store alias at
`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` can shadow the real
interpreter. Launching the console script directly avoids both problems, and it
is why **Installation** is a prerequisite rather than optional.

**VS Code** - `.vscode\mcp.json`, server id `gitlab-review`, `"type": "stdio"`.
This file is tracked, so it must not contain a hard-coded user name. It uses
`${userHome}`, which VS Code expands per user:

```json
"command": "${userHome}\\AppData\\Local\\Programs\\Python\\Python312\\Scripts\\gitlab-review-mcp.exe"
```

That path assumes the default per-user Python 3.12 layout. If your Python lives
elsewhere, do not edit the tracked file - override the server in your personal
VS Code user settings instead.

**Copilot CLI** - `~\.copilot\mcp-config.json`, server id `gitlab-review`,
`"type": "local"`. This file lives in your user profile and is never committed,
so an absolute path is appropriate there. Manage it with `/mcp`; reload after
edits with `/mcp reload`.

Find your own value with:

```powershell
(Get-Command gitlab-review-mcp).Source
```

Both clients set `GITLAB_BASE_URL` and `GITLAB_DEFAULT_PROJECT` in their `env`
block. `GITLAB_TOKEN` is deliberately left out of configuration files and is
inherited from the environment instead. `GITLAB_ALLOW_WRITE` is left out for the
same reason - enabling writes should be a conscious per-user act, not something
inherited by cloning the repository:

```powershell
[Environment]::SetEnvironmentVariable("GITLAB_TOKEN", "<token>", "User")
[Environment]::SetEnvironmentVariable("GITLAB_ALLOW_WRITE", "1", "User")
```

Restart the client afterwards - a spawned server inherits the client's
environment, not the environment of an unrelated terminal.

## Setup for a new user

1. Install the package (see **Installation**). This creates
   `gitlab-review-mcp.exe` in your Python `Scripts` directory.
2. Set `GITLAB_TOKEN` as a persistent user environment variable.
3. Confirm the launcher resolves: `(Get-Command gitlab-review-mcp).Source`
4. If that path does not match the `${userHome}` path in `.vscode\mcp.json`,
   override the server entry in your personal VS Code user settings.
5. For Copilot CLI, add a `gitlab-review` entry to `~\.copilot\mcp-config.json`
   using the absolute path from step 3.
6. Restart the client and verify by calling `health()`.

## Troubleshooting

**`failed to spawn MCP server process: program not found`** - the client could
not resolve `command`. Use the absolute path from
`(Get-Command gitlab-review-mcp).Source`.

**`GITLAB_BASE_URL is required` / `GITLAB_TOKEN is required`** - raised by
`GitLabConfig.from_env()` at startup. The spawned process did not inherit the
variable; set it at user scope and fully restart the client.

**`CERTIFICATE_VERIFY_FAILED`** - the GitLab certificate is issued by an
internal CA. `truststore` must be installed so verification uses the OS
certificate store. Do not disable verification.

**`GitLab write operations are disabled`** - a comment tool was called while
`GITLAB_ALLOW_WRITE` was unset. Set it at user scope and restart the client;
`health()` confirms it with `"write_enabled": true`.

**`GitLab API POST ... failed with HTTP 403`** - writes reached GitLab but were
refused. The token is `read_api` rather than `api`, or the account lacks
Developer access on the project.

**`GitLab API POST ... failed with HTTP 400`** on an inline comment - the diff
position is stale or invalid. Re-run `list_merge_request_changes()` and use a
line number that appears in the current diff.

**`getaddrinfo failed`** - `GITLAB_BASE_URL` hostname cannot be resolved; check
the URL and your VPN or network connection.
