# Teams MCP Skill

A local MCP server for triaging Microsoft Teams chats: read messages sent to
you, get alerted when new ones arrive, and draft replies.

Server lives in `.github\skills\teams-mcp\server`. Like `gitlab-mcp`, each MCP
client spawns its own process over stdio; nothing has to be started by hand.

Use this skill when you need to:

- see what messages arrived while you were heads-down
- summarise or triage a chat
- draft and send a reply with help

## Two backends, one tool surface

The tools are identical either way. Only `TEAMS_BACKEND` changes.

| | `graph` | `filedrop` |
|---|---|---|
| Source | Microsoft Graph, delegated | JSON files dropped by a Power Automate flow |
| Latency | Seconds | Minutes (flow polling + file sync) |
| Needs admin consent | **Yes** | No |
| History and search | Full | Only what the flow has dropped |

**In this tenant (Nuvoton), `Chat.Read` returns `AADSTS65001` — needs admin
approval.** It is *not* blocked by policy, so an administrator can grant it. Until
then, `filedrop` is the working backend.

### Getting the `graph` backend approved

Do **not** ask IT to consent `Chat.Read` on the Microsoft Graph PowerShell app -
that grants the scope to every Graph PowerShell user in the tenant. Ask for a
dedicated app instead:

- name `teams-mcp`, **single tenant**
- **public client / native**, device-code flow, **no client secret**
- Microsoft Graph **delegated** `Chat.Read` (and `Chat.ReadWrite` to reply)
- **no** application/app-only permissions
- user assignment restricted to your account

Delegated means the tool only ever sees chats you can already see, acting as you.
`Chat.Read` and `Chat.ReadWrite` are separate consent decisions - read may be
granted while write is refused, and the server degrades cleanly to read-only.

## Required environment

- `TEAMS_BACKEND` - `filedrop` (default) or `graph`
- `TEAMS_ALLOW_WRITE` - `1`/`true`/`yes` enables `send_message` and
  `reply_to_chat`; **off by default**
- `TEAMS_WEBHOOK_URL` - Workflows webhook for `send_message`. This is a
  credential: it embeds a signature and anyone holding it can post to that
  destination.

For `filedrop`:

- `TEAMS_INBOX_DIR` - synced folder the flow drops message JSON into
- `TEAMS_OUTBOX_DIR` - synced folder the reply flow watches
- `TEAMS_STATE_FILE` - optional; defaults under `%LOCALAPPDATA%\teams-mcp`

For `graph`:

- `TEAMS_CLIENT_ID` - application id of the registered app
- `TEAMS_TENANT_ID` - `a3f24931-d403-4b4a-94f1-7d83ac638e07` for Nuvoton

Set them in the per-user client config (`~\.copilot\mcp-config.json`), never in
the tracked `.vscode\mcp.json`.

```powershell
[Environment]::SetEnvironmentVariable("TEAMS_ALLOW_WRITE", "1", "User")
```

`health()` always reports `write_enabled` and any configuration problems.

## Available MCP tools

Read:

- `health()` - backend status, config problems, `write_enabled`
- `list_chats(limit=20)` - most recently active first; gives you `chat_id`
- `read_messages(chat_id, since="", limit=50)` - oldest first
- `get_message(message_id, chat_id="")`
- `check_new_messages(limit=25, mark_seen=True)` - **the alert**; suppresses
  anything already reported, so it is safe to call repeatedly

Write - requires `TEAMS_ALLOW_WRITE`:

- `send_message(body, title="")` - sends through a Teams **Workflows webhook**.
  No admin consent, no synced folder, works today. The destination is fixed by
  the webhook URL and the message arrives as the Workflows bot, not as you.
- `reply_to_chat(chat_id, body)` - targets a specific chat from `list_chats`, so
  it needs a working read backend. On `graph` it posts under your own identity.

## Fastest way to actually send a message

1. Teams → **Workflows** app → a template built on *"When a Teams webhook
   request is received"* (channel or chat variant).
2. Pick the destination, finish, copy the generated URL.
3. Put `TEAMS_WEBHOOK_URL` and `TEAMS_ALLOW_WRITE=1` in the `teams` env block of
   `~\.copilot\mcp-config.json`, then `/mcp reload`.
4. `send_message("...")`.

One webhook = one destination. Messaging someone else means another webhook.

## Workflow - catch up and reply

1. `check_new_messages()` - what arrived since last time. Returns nothing on a
   second call, so it will not re-report the same messages.
2. `read_messages(chat_id)` for context on anything that needs a real answer.
3. Draft the reply and **show the exact text to the user for approval**.
4. `reply_to_chat(chat_id, body)` once approved.

## Notes

- **Replies post under the user's own Teams identity.** Recipients cannot tell a
  drafted reply from a typed one. Always confirm the exact wording first - this
  matters more than it does for a GitLab comment.
- **Reading chats pulls private conversations into model context.** Prefer scoping
  the inbound flow to specific chats or `@`-mentions rather than every message.
- `filedrop` replies are **queued, not sent** - the file must sync and the flow
  must poll before the message appears in Teams. `reply_to_chat` says so in its
  result.
- Files caught mid-sync are skipped rather than failing the whole listing.
- Do not log or hardcode tokens, client ids, or flow URLs.
