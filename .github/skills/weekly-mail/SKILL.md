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

`health()` returns the current username. Inspect MR details, source branches,
notes/discussions, approvals, and pipeline history for the reporting window.
Count an MR as reviewed only when an approval or review comment/action by the
user is evidenced in that window; reviewer assignment alone is not proof.
Preserve the exact source branch name returned by GitLab.

For every MR the user reviewed during the window, collect its title/IID and
source branch. Also collect each MR pipeline or test run from the window, with
its source branch and actual `passed`/`failed` outcome. Use pipeline timestamps
and status, not the MR's current status alone. Do not claim the user triggered
a run unless the available evidence identifies them; otherwise describe it as
an MR pipeline result or ask the user to confirm. If run history or branch
identity is unavailable, state that coverage gap rather than guessing. Include
these results in a required `Git Update` section in the report. Separately
flag currently open MRs blocked on review, conflicts, unresolved discussions,
or a failing pipeline.

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
- Include a `Git Update` work-area heading every week, even when there were no
  qualifying items (say `No updates`). List reviewed MRs with title/IID and
  exact source branch, plus each MR pipeline/test run from the period with
  exact source branch and `passed`/`failed` outcome. Attribute a run to the
  user only when confirmed; otherwise report it as an MR pipeline result or
  ask for confirmation. Do not substitute current pipeline status for a run
  that occurred during the reporting period.
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
  sentences or unfinished text from the reference. Close with the user's
  Outlook **reply signature**, following the signature instructions below.
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

### Outlook reply signature

Weekly mails are replies, so use the reply signature, not the longer
new-message signature. The user's reply template is `Oren_Replay_message`;
the new-message template is `Oren_New_message`. Outlook may append an account
suffix to their filenames.

Read the matching `.htm` and `.txt` files under
`%APPDATA%\Microsoft\Signatures` using file tools. Resolve the reply template
for the sending account; if the match is missing or ambiguous, ask rather than
substituting the new-message signature or inventing one.

Use the `.txt` content as the closing in the plain-text preview. For HTML,
insert the signature's actual `<body>` contents after the report and before
the quoted thread, retaining its formatting and required styles. The current
reply signature is the short blue `Regards,` / `Oren Goldstein` closing
(`#1F497D`), with no images. Read the file each run rather than hard-coding
that appearance, so Outlook signature edits are respected.

Preserve the signature's paragraph spacing as well as its text and color.
Read its `<head>` styles, including `p.MsoNormal`, and inline the applicable
rules on the signature paragraphs before inserting the body fragment.
Copying only `<body>` drops those rules and Outlook can introduce automatic
paragraph margins. For the current compact reply signature, set each closing
paragraph to `margin:0; mso-margin-top-alt:0; mso-margin-bottom-alt:0;
line-height:normal` (single spacing). Keep these overrides scoped to the
signature, not global `MsoNormal` rules that would change the report or history.

Include the signature **once** in the new report: it replaces the typed
closing, not an extra block after it. Leave signatures in quoted history
unchanged. Outlook may insert its own `_MailAutoSig` block when an editor is
initialized; check for it before adding a signature and retain only one
closing in the new report. Do not copy a whole HTML document into the fragment
or encode the signature's markup as plain text. If a changed signature introduces images,
preserve them as embedded mail assets; if the available tools cannot do that,
report the limitation instead of inserting broken local-file links.

## Step 5 - create the draft

Build an HTML fragment from the composed body before calling Outlook. Use
paragraphs and nested `<ul>`/`<li>` lists, with inline `list-style-type:disc`
for work areas and `list-style-type:circle` for their items. Color only each
status suffix with a `<span style="color:...">` using the step 4 colors.
HTML-encode all mail-derived text before adding markup. Use `<strong>` for
any evidenced absence dates/reason. Append the actual Outlook reply-signature
fragment in place of the plain-text preview's closing.

Discover the Outlook tool schema first and confirm `reply_to_message` accepts
`html_body`. If it does not, stop before creating a draft and report that the
Outlook MCP server needs reloading after its local update. Do not silently
create a plain-text draft or fall back to a shell formatting step.

```
reply_to_message(
    entry_id="<previous weekly entry_id>",
    body="<composed body>",
    reply_all=True,
    send=False,
    subject="Weekly - WW<n+1><same suffix style as before>",
    html_body="<HTML fragment of the composed body>",
)
```

The `subject` argument is required — without it Outlook forces
`RE: Weekly - WW<n>` and the week number never advances.

The tool sets Outlook's HTML body and saves the formatted reply in the same
call. It appends the encoded quoted original below a separator, preserving
line breaks without duplicating the report. No separate PowerShell/COM
permission prompt is needed for formatting; normal MCP tool permissions
still apply, and sending remains forbidden.

Confirm the result has `saved=True`, `sent=False`, the expected subject and
`body_format="html"`. Read back the saved `entry_id` with
`get_message(include_quoted=True)` to check recipients, report wording, and
retained quoted history (page through it if truncated). If formatting failed,
report the draft as incomplete rather than claiming success. Confirm the
new report has exactly one reply signature; do not count signatures in the
quoted thread as duplicates. Plain-text readback cannot prove visual spacing.
If inspecting the rendered draft is available, check that the closing has
0 pt before/after and single line spacing for the current template; otherwise
state that rendering was not verified rather than claiming a visual match.

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
