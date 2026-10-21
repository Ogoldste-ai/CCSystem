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
Call `get_message(entry_id)` to read the body for relevant work areas, tone
and length. Use the formatting in step 4, even if the previous weekly uses
the older three-level plain-text outline.

The approved format reference is the sent mail to Ben titled
`MonthReview - WW38, WW39, WW40, WW43 - Booter` (October 20, 2026).
It supplies the layout and status colors only: do not use it as the weekly
reply target, copy its reporting period, or change the weekly recipients.

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

- Use the approved mail to Ben's **two-level bulleted layout**, not the older
  section/subheading/item outline. Start with a greeting appropriate to the
  weekly recipients (`Hi all,` for the distribution, not `Hi Ben,`), then a
  reporting-period line such as `Weekly - WW<n> (<start date>-<end date>)`.
  Include a vacation/absence line only when supported by the gathered sources
  or supplied by the user; bold the dates and reason as in the reference.
- Use filled-disc bullets for work-area headings and nested hollow-circle
  bullets for their items. The reference orders the areas as `BMC and Tavor
  SVB`, `Validation infrastructure`, `I3C`, then `Booter`. Keep relevant areas
  in that order, omit empty ones, and add other evidenced work areas as needed.
  Fold subareas such as SWQA into the item wording rather than a third level.
- End each item with an evidence-backed status, coloring **only the suffix**:
  `- done` in green (`#4EA72E`) for completed work, `- to-do` in red
  (`#FF0000`) for pending work, and `- still going` in amber (`#FFC000`)
  for ongoing or blocked work. State the blocker in the item itself. A
  completed review can be `done` without implying the MR was merged.
  If status is unclear, ask the user rather than inventing one.
- Keep sibling items compact, with visual separation between work areas.
  Keep each outcome in one bullet; do not reproduce accidental split
  sentences or unfinished text from the reference. Close with `Regards,`
  and `Oren Goldstein` on separate lines.
- Show a plain-text preview in chat, using four spaces for nested items
  and retaining the status words. For example (illustrative, not work to copy):

  ```text
  Hi all,

  Weekly - WW<n> (<start date>-<end date>)

  * BMC and Tavor SVB
      o Updated the API unit-test module. - done
      o Flash programming tool review is pending. - to-do

  * I3C
      o Shared-module work is blocked on review. - still going

  Regards,
  Oren Goldstein
  ```

- Group by work area, using the `modules` grouping from the git script.
- Write outcomes, not activity: "closed the I3C timing gap" beats "pushed 6
  commits".
- Merge duplicates: one design review may appear as a meeting, an MR and
  three commits. Report it once.
- Keep it to the length of previous weeks' mails.
- Include blockers and next steps in the relevant work-area items.

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

### Apply the HTML formatting

The current `reply_to_message` tool assigns plain-text `Body`; it does not
accept HTML. Do not pass HTML tags in `body` or claim that the plain-text
draft has the reference's bullets and colors.

After creating the draft, use local Outlook COM to format **that saved
draft**, identified by the returned `entry_id`:

1. Read its `Body`. Normalize CRLF/LF in both it and the composed plain-text
   body, and verify that it starts with the exact composed body. If it does
   not, stop and report the mismatch without changing the draft.
2. Remove that prefix only, retaining the remaining quoted reply text.
   HTML-encode all mail text, including the quoted text, before inserting
   it into markup.
3. Build the new content as HTML paragraphs and nested `<ul>`/`<li>` lists.
   Set the outer list's `list-style-type:disc` and the inner lists'
   `list-style-type:circle`, using inline styles. Add each status suffix
   in a `<span style="color:<status color>">`. Keep normal text in the
   default color and use `<strong>` for any evidenced absence dates/reason.
4. Append the retained, encoded reply text after a separator, preserving its
   line breaks with `<br>`. Set the draft's `BodyFormat` to `2` (HTML),
   assign the complete HTML document to `HTMLBody`, and call `Save()`.
   Do not append the old `HTMLBody` wholesale: it already includes the new
   plain-text content and would duplicate the report. Do not change the
   subject, recipients or reply target, create a second draft, or call `Send()`.
5. Reopen the saved item by its `entry_id` and verify that it is unsent,
   retains the expected subject and recipients, and has HTML lists and the
   applicable status colors. Check that the new report appears once and the
   quoted reply text remains below it.

If COM formatting is unavailable or fails, explicitly report that the saved
draft is plain text or that formatting is incomplete; do not claim a visual
match. This formatting step never sends mail.

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
