# Outlook MCP Skill

This repository ships a local Outlook MCP server under
`.github\skills\outlook-mcp\server`. It talks to the **classic Outlook desktop
client over COM**, so it needs no Entra app registration, no admin consent and
no network credentials - it inherits the mail session already running as you.

Register it in `~\.copilot\mcp-config.json` (per-user, not committed) pointing at
the installed `outlook-mcp.exe`. `pip install -e .` in the `server` directory is
a prerequisite. See `server\README.md` for setup and troubleshooting.

Use this skill when you need to:

- see what new or unread mail has arrived
- find a message by sender, subject or folder
- read one message in full before acting on it
- see which meetings you attended or have coming up
- draft a reply for review, or send mail directly

## Required environment

- `OUTLOOK_ALLOW_WRITE` - `1`/`true`/`yes` enables `send_mail`,
  `reply_to_message(send=True)`, `mark_read` and `save_attachments`. **Off by
  default**, so no tool call can send mail or write files by accident.
- `OUTLOOK_ALLOW_SEND` - default `1`; set to `0` to allow writes but forbid
  actual sending, leaving drafts as the only outbound path.
- `OUTLOOK_PREVIEW_CHARS` - preview length in list results, default `400`.
- `OUTLOOK_MAX_RESULTS` - hard cap on rows per call, default `50`.
- `OUTLOOK_MAX_BODY_CHARS` - cap on one body, default `20000`, `0` disables.
- `OUTLOOK_LIST_RECIPIENTS` - recipients shown per row in list results,
  default `3`, `0` disables. `get_message` always shows all of them.
- `OUTLOOK_STORE` - restrict to a single mailbox by display name.
- `OUTLOOK_ATTACHMENT_DIR` - where `save_attachments` writes when the call
  names no directory. Defaults to `%LOCALAPPDATA%\outlook-mcp\attachments`.
- `OUTLOOK_MAX_ATTACHMENT_MB` - per-attachment size limit, default `20`,
  `0` disables.

`health()` reports `write_enabled`, `send_enabled`, the resolved
`attachment_dir` and `max_attachment_mb`, so the current state is always
visible.

## Available MCP tools

Read:

- `health()`
- `list_folders(max_depth=3)`
- `list_messages(folder="Inbox", limit=25, unread_only=False, days=0, from_contains="", subject_contains="")`
- `get_message(entry_id, include_quoted=False, body_offset=0)`
- `search_messages(query, folder="Inbox", limit=25, days=0)`
- `list_attachments(entry_id)` - names, sizes, and which are inline images
- `list_calendar_events(days_back=7, days_forward=0, limit=50, include_all_day=True, busy_only=False)`
- `search_contacts(query, limit=10, include_gal=True)`

Write:

- `create_draft(to, subject, body, cc="", bcc="")` - **ungated**, always safe
- `reply_to_message(entry_id, body, reply_all=False, send=False, subject="")`
- `send_mail(to, subject, body, cc="", bcc="")` - requires `OUTLOOK_ALLOW_WRITE`
- `mark_read(entry_id, read=True)` - requires `OUTLOOK_ALLOW_WRITE`
- `save_attachments(entry_id, dest_dir="", names=[], include_inline=False, overwrite=False)`
  - requires `OUTLOOK_ALLOW_WRITE`; writes files to disk, never changes the mail

## Workflow A - triaging new mail

1. `list_messages(unread_only=True, days=7)` for what actually needs attention.
   This returns headers and a short preview, not full bodies.
2. `get_message(entry_id)` on the ones that matter, using the `entry_id` from
   step 1. This is the only call that returns a complete body.
3. `create_draft(...)` or `reply_to_message(...)` to prepare a response, leaving
   the final send to the user.

## Workflow B - finding a specific message

1. `list_folders()` if the message is not in the Inbox, to get exact paths.
2. `search_messages(query, folder=..., days=...)` - substring match over subject
   and sender. Narrow with `days` on a large mailbox; the Inbox here holds
   thousands of items.
3. `get_message(entry_id)` for the full text.

## Workflow C - getting a mailed file onto disk

Use this when a message carries something you need to actually read or process
- a netlist, a spreadsheet, a log - rather than just describe.

1. `search_messages(...)` or `list_messages(...)` to find the message, then
   note its `entry_id`. Rows that carry attachments list their filenames in
   `attachments`.
2. `list_attachments(entry_id)` to see names, sizes and which entries are
   inline signature images rather than real documents.
3. `save_attachments(entry_id, dest_dir=...)` with `dest_dir` set to the folder
   you want the files in - your own session/working folder, typically, since
   the server has no way to know where that is. Omit it to fall back to
   `OUTLOOK_ATTACHMENT_DIR`.
4. Read the returned `path` values with your normal file tools.

The result lists every file written with its absolute path and size, plus a
`skipped` entry (with a reason) for anything left out, so a missing file is
never silent. Inline images are skipped unless `include_inline=True`, existing
files are never overwritten - a collision becomes `report (2).pdf` - and
anything over `OUTLOOK_MAX_ATTACHMENT_MB` is reported instead of written.

Pass `names=[...]` to pick specific attachments by filename or 1-based index.

## Workflow D - sending mail

1. Draft the exact subject, recipients and body, and **show them to the user**.
2. Prefer `create_draft(...)`: it lands in the Outlook Drafts folder and goes
   nowhere until the user clicks Send.
3. Only use `send_mail(...)` after explicit approval of the exact text. It
   requires `OUTLOOK_ALLOW_WRITE=1`, goes out under the user's real address, and
   cannot be unsent.

## Notes

- Replying to a rolling series (a weekly report, a numbered status thread)
  needs the `subject` argument: Outlook otherwise forces `RE: <original>`, so
  the number in the subject never advances.
- `list_calendar_events` expands recurring meetings into occurrences. Use
  `busy_only=True` to drop free blocks, which is how cancelled meetings and
  self-booked focus time report. **Tentative is deliberately kept** - an
  accepted meeting often stays tentative, so excluding it would hide most of
  a normal working week.
- To find someone's address, use `search_contacts` - **not** a mail search.
  Searching folders only finds people you have already corresponded with, so
  a colleague you have never mailed looks like they do not exist.
  `search_contacts` checks your Contacts folder and then the organisation's
  address book (GAL).
- The GAL matches on **display name**, not alias: `eran.raz` and `eran` both
  fail where `Eran Raz` resolves. The tool tries the spaced spelling for you
  and reports which one hit in `matched`.
- **This reads real work email.** Customer, HR, legal and personal content all
  live here, and anything a tool returns enters model context. Prefer targeted
  queries (`unread_only`, `days`, `from_contains`, a specific folder) over broad
  listings, and pull full bodies only for messages that actually matter.
- **Sent mail is indistinguishable from mail the user typed.** Recipients cannot
  tell. Treat every send as irreversible and confirm the exact wording first -
  the same discipline as GitLab comments, but the blast radius is larger.
- **Attachments are untrusted input.** They are files a stranger can put in
  your mailbox, so `save_attachments` reduces every name to a bare basename:
  a name like `..\..\Windows\evil.dll` is written as `evil.dll` inside the
  destination and cannot escape it. Windows-illegal characters and device
  names (`CON`, `LPT1`) are neutralised too. Saving a file does not make its
  contents safe - treat what you then read with the same suspicion.
- Previews strip the quoted reply chain, so a long thread does not swamp the
  result with text the reader has already seen.
- If the last entry of a list/search result carries `more_available: true`, the
  answer is partial - read its `scan_hint` and raise `limit` or narrow with
  `days` before concluding you have seen everything.
- `search_messages` matches **subject and sender only, not bodies**.
- `entry_id` values come from `list_messages` / `search_messages` and change if
  an item moves between stores. Re-read rather than caching them across turns.
- Only **classic** Outlook exposes COM; the new Outlook for Windows does not.
- Only synced mail is visible. Mail outside the offline window will not appear.
- Attaching to COM starts Outlook if it is closed.
