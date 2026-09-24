# outlook-mcp server

An MCP server that reads, searches, drafts and sends mail through the **local
Outlook desktop client** over COM.

## Why COM and not Microsoft Graph

Graph's `Mail.Read` needs tenant admin consent, exactly like the Teams scopes
that blocked `teams-mcp`. Outlook COM needs none: it talks to the mail client
already running as you, so it inherits your existing session. It also sends
under your real address, which the Teams webhook could never do.

The trade-offs:

- **Classic Outlook only.** The new Outlook for Windows dropped COM entirely.
  `Get-AppxPackage Microsoft.OutlookForWindows` should return nothing.
- **Local, not cloud.** Only what the profile has synced is visible. Folders set
  to "keep offline for 12 months" will not show older mail.
- **Outlook gets started if it is closed.** Attaching to COM launches it.
- **Windows only.**

## Install

```powershell
cd C:\ec_accurev_git\.github\skills\outlook-mcp\server
pip install -e .
```

`pywin32` is pulled in automatically on Windows.

## Environment

| Variable | Meaning |
|---|---|
| `OUTLOOK_ALLOW_WRITE` | `1`/`true`/`yes` enables `send_mail`, `reply(send=True)` and `mark_read`. **Default off.** |
| `OUTLOOK_ALLOW_SEND` | Default `1`. Set to `0` to keep writes on but forbid actual sending, leaving drafts only. |
| `OUTLOOK_PREVIEW_CHARS` | Preview length in list results. Default `400`, clamped to 0-20000. |
| `OUTLOOK_MAX_RESULTS` | Hard cap on rows per call. Default `50`, clamped to 1-500. |
| `OUTLOOK_MAX_BODY_CHARS` | Cap on a single body. Default `20000`, `0` disables, clamped to 0-2000000. |
| `OUTLOOK_LIST_RECIPIENTS` | Recipients shown per row in list results. Default `3`, `0` disables. |
| `OUTLOOK_STORE` | Restrict to one mailbox by display name. Empty means all stores. |

## Tools

Read:

- `health()` - Outlook version, stores, default account, write state
- `list_folders(max_depth=3)` - paths, item counts, unread counts
- `list_messages(folder="Inbox", limit=25, unread_only=False, days=0, from_contains="", subject_contains="")`
- `get_message(entry_id, include_quoted=False, body_offset=0)` - the only call that returns a full body
- `search_messages(query, folder="Inbox", limit=25, days=0)` - substring over subject and sender
- `list_calendar_events(days_back=7, days_forward=0, limit=50, include_all_day=True, busy_only=False)` -
  appointments around today, earliest first; recurring meetings are expanded
  into their occurrences. `busy_only=True` drops free blocks, which is what
  cancelled meetings report as. Tentative is kept on purpose: an accepted
  meeting frequently stays tentative, so filtering it would hide most of the
  real week.

Write:

- `create_draft(to, subject, body, cc="", bcc="")` - **ungated**; a draft goes
  nowhere until you click Send in Outlook
- `reply_to_message(entry_id, body, reply_all=False, send=False, subject="")` - drafts by
  default; `send=True` needs `OUTLOOK_ALLOW_WRITE`. `subject` overrides
  Outlook's automatic `RE: <original>`, which a rolling series such as a
  weekly report needs in order to advance its week number.
- `send_mail(to, subject, body, cc="", bcc="")` - needs `OUTLOOK_ALLOW_WRITE`
- `mark_read(entry_id, read=True)` - needs `OUTLOOK_ALLOW_WRITE`

## Design notes

**Previews, not bodies.** `list_messages` returns headers plus a truncated
preview with the quoted reply chain stripped. Work email carries customer, HR
and legal content, and everything a tool returns enters model context, so full
bodies are opt-in per message via `get_message`.

**Everything returned is bounded.** Real mail is far bigger than it looks, and
each of these limits exists because an unbounded version produced output that
could not be read in one pass:

- bodies are cut at `OUTLOOK_MAX_BODY_CHARS`, and the quoted reply chain is
  dropped unless `include_quoted=True`. One GitHub notification measured
  310,000 characters, of which about ten lines were written by the sender.
  When a body is cut the result carries `body_total_chars` and
  `body_next_offset`; pass the latter back as `body_offset` to read on.
- list results show `OUTLOOK_LIST_RECIPIENTS` recipients per row plus a
  `+N more` marker. One mail had 54 recipients, and 25 such rows came to 76 KB.
  `get_message` still returns every recipient, because knowing exactly who was
  on a mail matters when you reply to it.

Nothing is ever silently shortened: every cut is reported in the result
alongside the original size.

**Drafting is separate from sending.** `create_draft` is deliberately ungated
because it is recoverable; `send_mail` is guarded because it is not. Mail sent
this way is indistinguishable from mail you typed, so the exact recipients and
wording should be confirmed before any send.

**SMTP addresses, not X500.** Exchange returns a useless
`/O=EXCH/CN=...` distinguished name from `SenderEmailAddress`. The client reads
`PR_SENT_REPRESENTING_SMTP_ADDRESS` instead and only falls back when absent, so
addresses are actually replyable.

**Bounded scans.** A folder here holds 6000+ items. `list_messages` sorts newest
first and stops after `limit` matches or a scan cap, so one tool call can never
turn into a full-store walk. Use `days` to narrow further.

When the answer is partial, the **last** entry in the result carries
`more_available: true` and a `scan_hint` explaining which bound was hit — the
result limit, or the scan cap before the end of the folder. Without it a full
page of results is indistinguishable from "that is everything". The sort is
applied *after* any `Restrict`, because Restrict returns a new collection that
does not inherit a previously applied sort.

**Search covers subject and sender only, never bodies.** A mail discussing a
topic under an unrelated subject line will not be found.

**COM is initialised per thread.** MCP tool calls can land on different worker
threads and COM demands per-thread `CoInitialize`; skipping it surfaces as a
confusing failure deep inside pywin32.

**Defensive property access.** Mailboxes contain meeting requests, delivery
reports and corrupt items. Every COM property read goes through a helper that
treats failure as "missing" rather than letting one bad item break a listing.
That helper takes a default, and the default matters: reading `Class` falls back
to "not mail" so an item that cannot even report its own type is skipped.
Falling back to "mail" instead once emitted a row with every field blank, since
every other read on that item failed too. Items with no `EntryID` are skipped
for the same reason - nothing could be done with them later anyway.

## Tests

```powershell
cd C:\ec_accurev_git\.github\skills\outlook-mcp\server
python -m pytest -q
```

61 tests, no Outlook required: the COM layer is injectable and the suite drives
it with fake folder, item and recipient objects.

## Troubleshooting

- **"Could not start or attach to Outlook"** - classic Outlook is not installed,
  or only the new Outlook is. Check
  `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE`.
- **Empty folder list** - the profile may not be loaded. Open Outlook once.
- **A folder path does not resolve** - call `list_folders()` and use the exact
  `path` it returns; both `/` and `\` work, and the store prefix is optional.
- **Hebrew or other non-Latin subjects look broken in a terminal** - that is the
  console codepage. MCP stdio is forced to UTF-8, so tool results are unaffected.
