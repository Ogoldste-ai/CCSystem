---
name: weekly-mail
description: Draft the weekly "Weekly - WW<n>" status mail as a reply-all on last week's thread, gathering the week's work from git commits, sent mail, calendar, GitLab merge requests and Teams. Use when asked to write, prepare or draft the weekly report/status mail.
---

# Weekly Mail

Builds the user's Wednesday status mail and leaves it **as a draft** in Outlook.

The mail is always a **reply-all on the previous week's thread** with the work
week number incremented, so the whole series stays in one conversation.

## Hard rules

1. **Never send.** Always call `reply_to_message(..., send=False)`. This mail
   goes to a wide distribution; an unreviewed send cannot be recalled.
2. **Never invent work.** Every line must trace to a gathered artefact — a
   commit, a mail, a meeting, an MR. If a source is empty, say so rather than
   filling the gap.
3. **Show the full drafted body in chat** before creating the draft, so the
   user can correct it.

## Step 1 - find the previous weekly mail

```
search_messages(query="Weekly - WW", folder="Sent Items", days=30, limit=10)
```

Take the **most recent** hit. Keep its `entry_id` — it is the reply target.
Call `get_message(entry_id)` to read the body: that body is the **format
template** for the new mail. Match its section headings, ordering, tone and
length. Do not impose a different layout.

If nothing is found, widen to `days=90`. If still nothing, stop and ask the
user for the subject of the last weekly rather than guessing a WW number.

## Step 2 - work out the new WW number

Parse `WW\s*(\d{1,2})` from the previous subject and add 1.

- `WW52` or `WW53` rolls to `WW01`.
- Preserve the original zero padding (`WW09` → `WW10`).
- Preserve any suffix the user habitually appends (dates, a name, a project
  tag) — re-derive it for the new week rather than copying it verbatim.

**Staleness guard.** Compare the previous weekly's sent date to today. If it
is more than ~10 days old, one or more weeks were skipped, so a blind `+1`
produces the wrong number. **Stop and ask the user** which WW to use.

## Step 3 - gather the week's work

Run these in parallel. Cover the last 7 days.

**Git commits** (primary source — this is the concrete record of work):

```powershell
.github\skills\weekly-mail\scripts\Get-WeeklyActivity.ps1 -Days 7
```

Returns JSON with a `modules` array already grouped by work area, plus the
raw `commits`. Prefer the grouping: the mail should read "I3C: added X, fixed
Y", not a list of SHAs. Pass `-IncludeSubmodules` to sweep submodules too.

**Mail the user sent:**

```
list_messages(folder="Sent Items", days=7, limit=40)
```

Exclude the previous weekly mail itself. Look for decisions communicated,
issues escalated, and reviews requested — not routine chatter.

**Meetings attended:**

```
list_calendar_events(days_back=7, busy_only=True)
```

`busy_only=True` drops free blocks — which is how **cancelled** meetings and
self-booked focus time report — while keeping tentative ones. Do not filter
tentative: an accepted meeting routinely stays tentative in Outlook, so
excluding it would drop most of the real week.

Use these for design reviews, syncs, bringups and demos worth reporting.
Ignore recurring admin blocks unless something notable happened. Entries whose
subject starts with `Canceled:` did not take place — skip them.

**GitLab merge requests:**

```
list_merge_requests(author_username="<me>", state="all")
list_merge_requests(reviewer_username="<me>", state="all")
```

`health()` returns the current username. Report MRs opened, merged and
reviewed. Note any still blocked on review or a red pipeline — that is the
kind of thing a status mail exists to surface.

**Teams** (best effort):

```
check_new_messages(limit=25, mark_seen=False)
```

The `filedrop` backend only holds *incoming* messages the Power Automate flow
captured, and has no history of what the user sent. Treat it as a weak
supplementary signal. **If it returns nothing, do not imply Teams was
covered** — just leave it out.

## Step 4 - compose

- Follow the previous mail's structure exactly (step 1).
- Group by work area, using the `modules` grouping from the git script.
- Write outcomes, not activity: "closed the I3C timing gap" beats "pushed 6
  commits".
- Merge duplicates: one design review may appear as a meeting, an MR and
  three commits. Report it once.
- Keep it to the length of previous weeks' mails.
- Flag blockers and next steps if the previous mails have such a section.

Show the complete body to the user and incorporate any corrections.

## Step 5 - create the draft

```
reply_to_message(
    entry_id="<previous weekly entry_id>",
    body="<composed body>",
    reply_all=True,
    send=False,
    subject="Weekly - WW<n+1><same suffix style as before>",
)
```

The `subject` argument is required — without it Outlook forces
`RE: Weekly - WW<n>` and the week number never advances.

## Step 6 - report back

State the WW number used, where the draft is (Outlook Drafts), the recipient
count, and **which sources were thin or empty**, so the user knows what to
double-check before sending.

## Notes

- Requires `outlook-mcp` and `gitlab-mcp` to be connected; if their tools are
  missing, the CLI was started before they were installed — tell the user to
  restart rather than silently skipping a source.
- Outlook must be running (classic desktop client) for COM access.
- This skill reads real work mail and chat into context. Keep queries scoped
  to 7 days and to the folders named above.
