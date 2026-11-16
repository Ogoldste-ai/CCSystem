# teams-mcp server

MCP server for Microsoft Teams chat triage. Two interchangeable backends behind
one tool surface: Microsoft Graph (delegated) and a Power Automate file drop.

## Install

```powershell
cd C:\CCSystem\.github\skills\teams-mcp\server
pip install -e ".[test]"          # filedrop backend
pip install -e ".[graph,test]"    # adds msal for the graph backend
```

Editable install, so source edits need no reinstall - but each MCP client spawns
its own process, so `/mcp reload` (CLI) or a client restart is required before
changes take effect.

## Configure

Add to `~\.copilot\mcp-config.json` (per-user, untracked):

```json
"teams": {
  "tools": ["*"],
  "type": "local",
  "command": "C:\\Users\\<you>\\AppData\\Local\\Programs\\Python\\Python312\\Scripts\\teams-mcp.exe",
  "args": ["--transport", "stdio"],
  "env": {
    "TEAMS_BACKEND": "filedrop",
    "TEAMS_INBOX_DIR": "%OneDrive%\\teams-mcp\\inbox",
    "TEAMS_OUTBOX_DIR": "%OneDrive%\\teams-mcp\\outbox"
  }
}
```

Do not put this in `.vscode\mcp.json` - that file is tracked, so folder paths and
client ids would be committed.

### Environment variables

| Variable | Backend | Purpose |
|---|---|---|
| `TEAMS_BACKEND` | both | `filedrop` (default) or `graph` |
| `TEAMS_ALLOW_WRITE` | both | `1`/`true`/`yes` enables `reply_to_chat` and `send_message`. **Default off.** |
| `TEAMS_WEBHOOK_URL` | both | Power Automate Workflows webhook used by `send_message`. A credential - keep it per-user. |
| `TEAMS_INBOX_DIR` | filedrop | Synced folder the inbound flow writes to |
| `TEAMS_OUTBOX_DIR` | filedrop | Synced folder the outbound flow watches |
| `TEAMS_STATE_FILE` | both | Seen-message state. Defaults under `%LOCALAPPDATA%\teams-mcp` |
| `TEAMS_CLIENT_ID` | graph | Application (client) id of the registered app |
| `TEAMS_TENANT_ID` | graph | Directory (tenant) id |

The server **never raises on a bad configuration**. It starts anyway and
`health()` lists the problems, which is far easier to diagnose than a client
reporting that the process died at spawn.

## Tools

Read:

- `health()`
- `list_chats(limit=20)`
- `read_messages(chat_id, since="", limit=50)`
- `get_message(message_id, chat_id="")`
- `check_new_messages(limit=25, mark_seen=True)`

Write, gated on `TEAMS_ALLOW_WRITE`:

- `send_message(body, title="")` - via the Workflows webhook, fixed destination
- `reply_to_chat(chat_id, body)` - targets a chat from `list_chats`

## Backend: `graph`

MSAL device-code flow, token cached next to the state file with `0600` where the
filesystem supports it.

Sign-in cannot complete inside a tool call - that would block the MCP server - so
the first call raises with the verification URL and code. Complete it, then call
again; the cached refresh token keeps subsequent calls silent.

`fetch_recent` expands `lastMessagePreview` over the chat list rather than issuing
one request per chat, because Graph has no cheap delegated "all my messages"
endpoint.

### Consent status in this tenant

`Chat.Read` currently returns **`AADSTS65001` - needs admin approval** for
`nuvoton.com` (tenant `a3f24931-d403-4b4a-94f1-7d83ac638e07`). Not policy-blocked,
so an admin can grant it. Directory search and starting chats additionally use
delegated `User.ReadBasic.All` and `Chat.Create`; replying uses `Chat.ReadWrite`.
Those permissions may need separate admin approval. The shared Graph error hint lists the
operation-to-permission mapping and admin-consent guidance for 401/403 responses.

Request wording that gets approved:

> Please register a single-tenant Entra application with delegated Microsoft Graph
> permission `Chat.Read` (and `User.ReadBasic.All` for people search,
> `Chat.Create` for starting chats, and `Chat.ReadWrite` for replies, as needed), **no**
> application/app-only permissions, public client with device-code flow and no
> client secret, user assignment restricted to my account. Delegated access means
> the tool can only see chats I can already see, acting as me.

Do **not** request admin consent on the Graph PowerShell client id - that grants
the scope tenant-wide for every user of that app.

## Backend: `filedrop`

Bridges Power Automate to this process through a synced folder. Power Automate's
Teams connector is a *standard* connector needing no app registration or admin
consent, but its HTTP trigger is premium-only - hence files.

**Inbound flow:** trigger *"When a new chat message is added"* → create a file in
a synced work OneDrive folder, one JSON object per message. The trigger emits a notification
array, not the message text. Inside an **Apply to each** over
`triggerBody()?['value']`, add Teams **Get message details** (message type
**Group chat**, message `item()?['messageId']`, group chat
`item()?['conversationId']`). Rename that action `Fetch_chat_message`, then
use OneDrive for Business **Create file** inside the loop:

- Folder: `/teams-mcp/inbox` in a work OneDrive that is synced to this PC
- File name (expression): `concat(guid(), '.json')`
- File content (expression):
  `string(setProperty(body('Fetch_chat_message'), 'chatId', item()?['conversationId']))`

Set `TEAMS_INBOX_DIR` to the synced **local** `teams-mcp\inbox` folder, not
the OneDrive web path. Notification-only files from older flow versions contain
no sender or text and are ignored. The filedrop backend accepts both the
fetched Teams message details (nested `from.user` and `body.content`) and
the simpler format below:

```json
{
  "id": "1700000000000",
  "chatId": "19:abc...@thread.v2",
  "chatName": "Shir Zamir",
  "from": "Shir Zamir",
  "fromEmail": "szamir@nuvoton.com",
  "createdAt": "2026-09-10T10:00:00Z",
  "body": "<p>message html</p>"
}
```

Key spellings are flexible - `messageId`/`conversationId`/`sender`/`content`/
`createdDateTime` are all accepted, and `from`/`sender` may be an object with a
`displayName`. HTML bodies are flattened to plain text.

**Outbound flow:** trigger *"When a file is created"* on `TEAMS_OUTBOX_DIR` →
**Parse JSON** with file content `base64ToString(triggerBody()?['$content'])`
and required string fields `chatId` and `body` → Teams *"Post message in a chat
or channel"* with **Post as: User**, **Post in: Group chat**, Group chat set to
the parsed `chatId` (custom value), and Message set to the parsed `body`.
Choose the work OneDrive `/teams-mcp/outbox` folder in the trigger's folder
picker and set `TEAMS_OUTBOX_DIR` to its synced local path. Replies are staged
outside the watched folder and atomically moved into it, so the flow cannot
trigger on a temporary file that disappears during the rename.

Prerequisite: a synced work folder. OneDrive **for Business** or a SharePoint
library - the consumer OneDrive is not reachable by the standard connectors.

### Fast inbox checks and incomplete results

In File Explorer, right-click the local inbox and choose **Always keep on this
device** if you want the complete inbox available without cloud retrieval.
Wait for OneDrive to finish downloading; setting the pin alone does not mean
all contents are already local.

Filedrop reads run in one short-lived scan worker with a **3-second scan budget**,
including startup. The worker checks file attributes before opening content and
defers Windows files marked as offline or requiring remote data. An unexpectedly
blocked scan is killed and reaped on deadline or cancellation, rather than
blocking the MCP event loop. Concurrent reads fail promptly with an "already
running" error instead of queuing more scans. Health does not wait for the worker
and does not read message content.

`check_new_messages` retains `new_count`, `marked_seen`, and `messages`, and adds:

- `complete`: whether all local inbox files were successfully scanned
- `scan`: `files_scanned`, `deferred_files`, `unreadable_files`, `invalid_files`,
  `timed_out`, and `elapsed_ms`
- `warning`: present on incomplete scans, with the reason and recovery guidance

Incomplete checks return available messages but **never mark them seen**, even
with `mark_seen=True`. They may therefore repeat on the next check. An empty
incomplete result **does not mean there are no new messages**. Download deferred
files, resolve sync/read errors, or correct malformed JSON, then check again.
Notification-only files are intentionally ignored and do not make a scan
incomplete.

`list_chats`, `read_messages`, and `get_message` raise an explicit error for
incomplete scans instead of returning misleading lists or "not found."
Scanner failures also produce tool errors, not empty successes.

This bounds the cost of reading files already delivered to the local inbox; it
does not remove Teams -> Power Automate -> OneDrive polling and sync delays.
Every scan still considers the inbox, so lowering the result limit does not avoid
file reads. The HTTP client timeout applies to Graph/webhook requests, not these
file reads. There is no parsed-message cache to become stale after sync changes.

After updating this editable install, reload the MCP client before using the
new behavior. If an old process is stuck in a content read, restore/reload the
connection instead of blindly repeating the timed-out call.

## Sending: the Workflows webhook

**This is the fastest path to actually sending a Teams message.** It needs no
Entra app registration, no admin consent, no premium licence and no synced
folder - so it usually works long before any read path does.

Create the webhook in Teams:

1. In Teams, open the **Workflows** app (or right-click a chat/channel →
   **Workflows**).
2. Pick a template built on *"When a Teams webhook request is received"* - for a
   channel, **"Post to a channel when a webhook request is received"**; there is
   a chat equivalent for 1:1 and group chats.
3. Choose the destination chat or channel and finish. Copy the generated URL.
4. Set it on the server and enable writes:

```json
"env": {
  "TEAMS_BACKEND": "filedrop",
  "TEAMS_WEBHOOK_URL": "https://prod-xx.westeurope.logic.azure.com/workflows/...",
  "TEAMS_ALLOW_WRITE": "1"
}
```

Then `/mcp reload` and call `send_message(body, title="")`.

Trade-offs, all of them deliberate:

- **The destination is fixed by the URL.** One webhook posts to exactly one chat
  or channel. Messaging a different person means a different webhook.
- **It arrives as the Workflows bot, not as you.** Custom bot name and icon are
  not supported. Use the `graph` backend when the message must come from your own
  identity.
- **It cannot read.** Sending and reading are independent here; pair it with a
  read backend for the full workflow.
- **The URL is a credential** - it embeds a signature, and anyone holding it can
  post to that destination. Keep it in the per-user config, never in tracked
  files. `health()` deliberately reports only the host, never the signature.

`reply_to_chat` is the other sender: it targets a specific `chat_id` from
`list_chats`, so it needs a working read backend, but on `graph` it posts under
your own identity.

## Evaluated and rejected: the local Teams cache

The new Teams client keeps an IndexedDB cache at

```
%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams
  \EBWebView\WV2Profile_tfw\IndexedDB\https_teams.microsoft.com_0.indexeddb.leveldb
```

It is tempting because it needs **no admin consent and no synced folder**. A probe
confirmed real data is there and that the files copy cleanly even while Teams holds
its lock (425 conversation ids, 119 `composetime` keys, 1024 `RichText/Html`
markers across ~49 MB).

It was still rejected:

- **Read-only.** There is no way to send a reply, so it cannot satisfy the whole
  use case - a second backend would be needed anyway.
- LevelDB Snappy-compresses its blocks, so records are not recoverable by scanning;
  it needs a LevelDB reader plus IndexedDB envelope parsing plus Teams' own
  undocumented schema. `ccl-chromium-reader` has no distribution for this Python.
- That schema is internal and changes without notice, so it would break on Teams
  updates with no warning.

Revisit only if admin consent is refused outright *and* read-only triage is enough.

## Tests

```powershell
cd C:\CCSystem\.github\skills\teams-mcp\server
python -m pytest -q
```

Tests require no network or Teams access: the Graph backend runs against
a fake HTTP client and `filedrop` against a temp directory.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `health()` shows `status: misconfigured` | Read `problems` - it names the exact variable |
| `Teams write operations are disabled` | `TEAMS_ALLOW_WRITE` not set, or client not reloaded |
| `Interactive sign-in required` | Expected on first `graph` use; complete the device code, then retry |
| Graph 403 mentioning consent | Admin has not granted `Chat.Read`/`Chat.ReadWrite` |
| `filedrop` returns nothing | Check the flow ran and the folder actually synced locally |
| `complete: false`, `deferred_files` is nonzero | Use **Always keep on this device** for the inbox and wait for OneDrive downloads |
| `complete: false`, read/JSON errors | Wait for sync to finish, check access, and correct malformed message files |
| `timed_out: true` | The scan worker was stopped; resolve local filesystem/OneDrive stalls before retrying |
| `A Teams inbox scan is already running` | Let the active scan finish or reach its deadline; do not queue retries |
| Reply queued but never appears | Outbound flow not running, or watching the wrong folder |
