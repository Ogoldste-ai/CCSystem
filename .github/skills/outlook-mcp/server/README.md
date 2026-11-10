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

`pywin32` and `pywinauto` are pulled in automatically on Windows.

## Environment

| Variable | Meaning |
|---|---|
| `OUTLOOK_ALLOW_WRITE` | `1`/`true`/`yes` enables `send_mail`, `reply(send=True)`, `mark_read` and `save_attachments`. **Default off.** |
| `OUTLOOK_ALLOW_SEND` | Default `1`. Set to `0` to keep writes on but forbid actual sending, leaving drafts only. |
| `OUTLOOK_PREVIEW_CHARS` | Preview length in list results. Default `400`, clamped to 0-20000. |
| `OUTLOOK_MAX_RESULTS` | Hard cap on rows per call. Default `50`, clamped to 1-500. |
| `OUTLOOK_MAX_BODY_CHARS` | Cap on a single body. Default `20000`, `0` disables, clamped to 0-2000000. |
| `OUTLOOK_LIST_RECIPIENTS` | Recipients shown per row in list results. Default `3`, `0` disables. |
| `OUTLOOK_STORE` | Restrict to one mailbox by display name. Empty means all stores. |
| `OUTLOOK_ATTACHMENT_DIR` | Fallback destination for `save_attachments` when the call names none. Default `%LOCALAPPDATA%\outlook-mcp\attachments`. |
| `OUTLOOK_MAX_ATTACHMENT_MB` | Per-attachment size limit. Default `20`, `0` disables, clamped to 0-2048. |

## Tools

Read:

- `health()` - Outlook version, stores, default account, write state
- `list_folders(max_depth=3)` - paths, item counts, unread counts
- `list_messages(folder="Inbox", limit=25, unread_only=False, days=0, from_contains="", subject_contains="", received_after="", received_before="")`
- `list_messages_page(folder="Inbox", limit=25, unread_only=False, days=0, from_contains="", subject_contains="", offset=0, received_after="", received_before="", compact=True)` -
  compact paginated headers with explicit continuation, including empty scan pages
- `get_message(entry_id, include_quoted=False, body_offset=0)` - one full body
- `get_messages(entry_ids, include_quoted=False, body_offset=0, body_chars=2000)` -
  bounded bodies for explicit IDs, with per-message errors
- `search_messages(query, folder="Inbox", limit=25, days=0)` - substring over subject and sender
- `list_calendar_events(days_back=7, days_forward=0, limit=50, include_all_day=True, busy_only=False)` -
  appointments around today, earliest first; recurring meetings are expanded
  into their occurrences. `busy_only=True` drops free blocks, which is what
  cancelled meetings report as. Tentative is kept on purpose: an accepted
  meeting frequently stays tentative, so filtering it would hide most of the
  real week.
- `search_contacts(query, limit=10, include_gal=True)` - find a person's
  address by name, alias or partial address. Looks in the Contacts folder
  first, then the address book (GAL); `include_gal=False` stays local.

  Two quirks of the real object model are handled here, and both are silent
  data-loss bugs if they are not:

  - The GAL resolves on **display name**, not alias - `eran.raz` fails where
    `Eran Raz` succeeds - so the spaced spelling is tried too and `matched`
    reports which one worked.
  - Exchange-backed contacts put an unusable X500 DN in `Email1Address` and
    the real address in `Email1DisplayName`. In a corporate mailbox that is
    *every* saved contact, so the address is recovered from the display name,
    and failing that from the directory.

Write:

- `create_draft(to, subject, body, cc="", bcc="")` - **ungated**; a draft goes
  nowhere until you click Send in Outlook
- `reply_to_message(entry_id, body, reply_all=False, send=False, subject="", html_body="")` - drafts by
  default; `send=True` needs `OUTLOOK_ALLOW_WRITE`. `subject` overrides
  Outlook's automatic `RE: <original>`, which a rolling series such as a
  weekly report needs in order to advance its week number.
  Supply `html_body` as an HTML fragment to save formatted reply content in the
  same call, without a separate shell/COM formatting step. Keep `body` as the
  plain-text preview; it is not also inserted when HTML is supplied. Encode
  mail-derived text before adding markup. The quoted original is escaped and
  retained below a separator (its original visual formatting is not retained).
  The draft result reports `body_format`. Sending permissions are unchanged.
- `send_mail(to, subject, body, cc="", bcc="")` - needs `OUTLOOK_ALLOW_WRITE`
- `create_meeting(attendees, subject, start, duration_minutes=30, body="", optional_attendees="", location="", teams=True, send=False)`
  - saves the invite **unsent** in your Calendar by default (ungated, like
  `create_draft`); `send=True` mails the invitations and needs
  `OUTLOOK_ALLOW_WRITE`. See [Meetings](#meetings).
- `mark_read(entry_id, read=True)` - needs `OUTLOOK_ALLOW_WRITE`
- `mark_messages_read(entry_ids, read=True)` - needs `OUTLOOK_ALLOW_WRITE`;
  explicit IDs only, deduplicated, saved state verified, per-message errors
- `save_attachments(entry_id, dest_dir="", names=[], include_inline=False, overwrite=False)`
  - needs `OUTLOOK_ALLOW_WRITE`. Writes attachments to a directory; the message
  itself is never modified. See [Attachments](#attachments).

- `find_free_slots(attendees, start, end, duration_minutes=30, work_start="09:00", work_end="18:00", workdays="sun,mon,tue,wed,thu", limit=10, allow_tentative=False, include_me=True)`
  - read-only Scheduling Assistant equivalent. See [Meetings](#meetings).

Attachments are also listed read-only by `list_attachments(entry_id)`, which
reports name, size, kind and whether the entry is an inline body image.

## Mail triage: pages, dates and batches

For unread mail, start with `list_messages_page(unread_only=True, limit=50)`.
The result is an object containing `messages`, `more_available`, `next_offset`
and `scanned`. Keep the same folder and filters, pass `next_offset` as
`offset`, and continue until `more_available` is false. A page can be empty
while `more_available` is true: a bounded scan found no matching mail yet.
`scanned` is the number of collection entries examined, not matching messages.
`OUTLOOK_MAX_RESULTS` limits each page, not the total number of pages.
`compact=True` omits recipients/folder metadata and bounds previews to 160
characters; `preview_truncated` reports cuts. Use `compact=False` for the
ordinary list headers.

**Pages are not snapshots.** Offsets index the live sorted collection after
Outlook restrictions. Collect all pages before changing read state. New mail,
moves, deletions or read-state changes can shift offsets; if the collection
changes, restart from zero and deduplicate IDs. Prefer fixed received bounds
over a rolling `days` cutoff when paging.

Both list tools accept `received_after` (inclusive) and `received_before`
(exclusive). Values are ISO dates or date/times: a date-only or offset-free
value uses the server computer's local time, and an explicit offset is
converted to that timezone. For November 8 in Israel, use
`received_after="2026-11-08T00:00:00+02:00"` and
`received_before="2026-11-09T00:00:00+02:00"`. Using
`"2026-11-08"` / `"2026-11-09"` instead is equivalent only when the server
runs in that local timezone. Invalid/reversed ranges are rejected. When
`days` is supplied too, it intersects the exact range. COM restrictions are
broadened to local calendar days; exact Python-side comparisons retain UTC
instants so the repeated hour at daylight-saving fallback cannot reverse or
widen the requested interval.

Read relevant messages with `get_messages(entry_ids=[...])`. It never marks
mail read. The default body window is 2000 characters per message.
`body_chars` must be 1-10000, and the configured single-body limit also
applies. Even when that limit is disabled, the batch has a 100000-character
body budget, divided equally across unique IDs. Previews stay within 160
characters, and recipient lists show up to the configured limit (at most 10;
3 when the configured limit is disabled), followed by a `+N more` marker.
Use `get_message` with the returned `body_next_offset` for more body text or
all recipients.

After explicit user authorization, pass only the IDs actually reviewed to
`mark_messages_read(entry_ids=[...])`. It is not a mailbox-wide mark-all tool.
Both batch tools accept 1 to `OUTLOOK_MAX_RESULTS` input IDs; larger or empty
batches and blank IDs are rejected rather than silently shortened.
Duplicates are handled once in input order. They return `results`,
`succeeded`, and `failed`; each result contains the message/state or its
`entry_id` and `error`. A stale ID, wrong item type or individual save failure
does not stop later IDs. Writes are not transactional: successful changes are
not rolled back if another ID fails.

Reload/reconnect the Outlook MCP server after updating its Python code so the
running process and its tool schemas pick up the new tools. An existing
editable install needs no reinstall for these source-only changes.

## Meetings

`find_free_slots` reads Exchange free/busy through `Recipient.FreeBusy` (you
plus the attendees) and returns earliest-first slots where everyone is free
inside working hours. Tentative counts as busy unless `allow_tentative`; the
default work week is Sun-Thu. People whose calendar cannot be read come back in
`no_data` and are **not** checked; names that do not resolve come back in
`unresolved`. Times past the end of the returned free/busy data are never offered.

`create_meeting` builds a meeting request. The Teams link cannot be added over
COM (the add-in has no COM surface and its ribbon button is not an `ExecuteMso`
command), so with `teams=True` it briefly displays the invite and clicks the
**Teams Meeting** ribbon button through Windows UI Automation (`pywinauto`).
Consequences: needs the Teams add-in and an English Outlook UI, and Outlook
must not be used while it runs. If the link cannot be added, the half-built
item is discarded and the call fails rather than leaving an invite without a
link. `teams_ui` imports `pywinauto` at module load on purpose; importing it
after Outlook COM objects exist breaks them.

An unsent invite is saved in your Calendar (it blocks that time) until you
open it and click Send.

## Design notes

**Previews, not bodies.** `list_messages` returns headers plus a truncated
preview with the quoted reply chain stripped. Work email carries customer, HR
and legal content, and everything a tool returns enters model context, so full
bodies are opt-in via `get_message` or a bounded explicit-ID `get_messages`
batch.

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
result limit, or the scan cap before the end of the folder. Use
`list_messages_page` for explicit continuation, including empty pages.
Without it a full
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

## Attachments

`save_attachments` exists so a mailed file can be handed to whatever is driving
the server - an agent's session folder, a scratch directory - without a human
opening Outlook and clicking Save As.

**The destination is the caller's choice.** The server is a separate process
and cannot know where its client keeps working files, so `dest_dir` wins,
`OUTLOOK_ATTACHMENT_DIR` is the fallback, and
`%LOCALAPPDATA%\outlook-mcp\attachments` is the last resort. The default is
deliberately outside any repository: attachments are untrusted files, and they
should not land somewhere a build or a commit might sweep them up.

**Filenames are treated as hostile.** The name is chosen by whoever sent the
mail. `safe_filename` keeps only the basename, so `..\..\Windows\evil.dll`
becomes `evil.dll` inside the destination, neutralises characters Windows
forbids, and replaces reserved device names (`CON`, `LPT1`) which cannot be
created at all. A name that sanitises to nothing becomes `attachment_<n>`.

**Nothing is overwritten and nothing is silently dropped.** A collision becomes
`report (2).pdf`, including when one message carries two attachments with the
same name - which is why the run tracks names it has already written rather
than only checking the filesystem. Every attachment that is *not* written
appears in `skipped` with a reason: inline, too large, or refused by Outlook.
A `names` entry matching no attachment comes back in `not_found`.

**Inline images are skipped by default.** Signature logos are attachments too;
they are detected through `PR_ATTACH_CONTENT_ID` and `PR_ATTACHMENT_HIDDEN` and
excluded unless `include_inline=True`.

**Gated behind `OUTLOOK_ALLOW_WRITE`.** The message is never modified, but the
filesystem is, with content from outside the organisation - so it shares the
switch that guards sending. The error message says so, rather than talking
about mail.

## Tests

```powershell
cd C:\ec_accurev_git\.github\skills\outlook-mcp\server
python -m pytest -q
```

153 tests, no Outlook required: the COM layer is injectable and the suite drives
it with fake folder, item, recipient and attachment objects.

## Troubleshooting

- **"Could not start or attach to Outlook"** - classic Outlook is not installed,
  or only the new Outlook is. Check
  `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE`.
- **Empty folder list** - the profile may not be loaded. Open Outlook once.
- **A folder path does not resolve** - call `list_folders()` and use the exact
  `path` it returns; both `/` and `\` work, and the store prefix is optional.
- **Hebrew or other non-Latin subjects look broken in a terminal** - that is the
  console codepage. MCP stdio is forced to UTF-8, so tool results are unaffected.
