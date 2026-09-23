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
- draft a reply for review, or send mail directly

## Required environment

- `OUTLOOK_ALLOW_WRITE` - `1`/`true`/`yes` enables `send_mail`,
  `reply_to_message(send=True)` and `mark_read`. **Off by default**, so no tool
  call can send mail by accident.
- `OUTLOOK_ALLOW_SEND` - default `1`; set to `0` to allow writes but forbid
  actual sending, leaving drafts as the only outbound path.
- `OUTLOOK_PREVIEW_CHARS` - preview length in list results, default `400`.
- `OUTLOOK_MAX_RESULTS` - hard cap on rows per call, default `50`.
- `OUTLOOK_MAX_BODY_CHARS` - cap on one body, default `20000`, `0` disables.
- `OUTLOOK_LIST_RECIPIENTS` - recipients shown per row in list results,
  default `3`, `0` disables. `get_message` always shows all of them.
- `OUTLOOK_STORE` - restrict to a single mailbox by display name.

`health()` reports `write_enabled` and `send_enabled`, so the current state is
always visible.

## Available MCP tools

Read:

- `health()`
- `list_folders(max_depth=3)`
- `list_messages(folder="Inbox", limit=25, unread_only=False, days=0, from_contains="", subject_contains="")`
- `get_message(entry_id, include_quoted=False, body_offset=0)`
- `search_messages(query, folder="Inbox", limit=25, days=0)`

Write:

- `create_draft(to, subject, body, cc="", bcc="")` - **ungated**, always safe
- `reply_to_message(entry_id, body, reply_all=False, send=False)`
- `send_mail(to, subject, body, cc="", bcc="")` - requires `OUTLOOK_ALLOW_WRITE`
- `mark_read(entry_id, read=True)` - requires `OUTLOOK_ALLOW_WRITE`

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

## Workflow C - sending mail

1. Draft the exact subject, recipients and body, and **show them to the user**.
2. Prefer `create_draft(...)`: it lands in the Outlook Drafts folder and goes
   nowhere until the user clicks Send.
3. Only use `send_mail(...)` after explicit approval of the exact text. It
   requires `OUTLOOK_ALLOW_WRITE=1`, goes out under the user's real address, and
   cannot be unsent.

## Notes

- **This reads real work email.** Customer, HR, legal and personal content all
  live here, and anything a tool returns enters model context. Prefer targeted
  queries (`unread_only`, `days`, `from_contains`, a specific folder) over broad
  listings, and pull full bodies only for messages that actually matter.
- **Sent mail is indistinguishable from mail the user typed.** Recipients cannot
  tell. Treat every send as irreversible and confirm the exact wording first -
  the same discipline as GitLab comments, but the blast radius is larger.
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
