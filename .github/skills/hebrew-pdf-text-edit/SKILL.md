---
name: hebrew-pdf-text-edit
description: Edit text inside Hebrew PDFs that have plain content streams (Hilan payslips / תלוש שכר and similar) - change wording, fix dates, delete a line, add a table column, or roll a payslip to another month. Use when asked to modify, correct, roll forward or roll back the contents of an existing Hebrew PDF.
---

# Hebrew PDF text edit

Edits text **inside** a PDF by patching its content stream bytes, so fonts,
layout and every untouched element stay bit-identical. No re-typesetting, no
OCR, no external service.

Designed for payslips produced by Hilan (`חילן`), which have the properties
this skill depends on:

- content streams are **uncompressed**, one `BT … (text) Tj … ET` block per
  visible string, each with its own absolute `x y Td`;
- Hebrew is stored **reversed** (visual order) with no `/ToUnicode` map — so
  `extract_text()` returns garbage, but byte editing is exact and safe;
- text widths can be computed precisely from the font, so anything can be
  re-positioned exactly.

Two Hilan generations exist; the helper detects which one a font uses and
handles both transparently, so the commands below are identical either way:

| | older slips | newer slips |
|---|---|---|
| font | subset TrueType `David` / `David,Bold` | `/Type0` CID `David-Identity-H` |
| encoding | single-byte **cp1255** | two-byte **UTF-16BE** codes via an embedded CMap |
| widths | `/FirstChar` + `/Widths` | descendant font `/W`, indexed by CID through the CMap |
| tell-tale | — | a `מפעל …/נתונים איכותיים מוצגים נכון ל…` footer, `תפקיד`, `שווי כסף נטו` rows |

Note that strings in the newer format contain `(`/`)` bytes as part of
UTF-16 code units, so blocks must be scanned with balanced-paren logic — a
naive `\(([^)]*)\)` regex silently mangles them. The helper already does this.

## Hard rules

1. **Never overwrite the source file.** Always write a new file. The original
   is the only clean copy; treat it as read-only.
2. **Always verify by rendering.** After every change, rasterise the affected
   area and *look at it*. Text extraction cannot prove the result looks right
   (overlaps, RTL misalignment, clipped columns), a render can.
3. **Ask before applying updates that were not requested.** If a change makes
   another field stale (a month roll makes accumulations, seniority and
   balances stale), point it out and ask — do not silently "fix" it.
4. **Same digit count = safe.** Numeric cells are right-aligned by absolute x.
   Replacing `125` with `150` is free; changing the number of characters
   shifts the visual alignment — re-check it in the render.
5. **The output file may be open in a viewer.** Windows then refuses the
   overwrite; the helper falls back to `<name>-v2.pdf`. Say so in the summary.

## Tooling

```powershell
pip install pypdf pypdfium2          # pypdfium2 is only for verification renders
$EDIT = ".github\skills\hebrew-pdf-text-edit\scripts\pdf_text_edit.py"
```

Set the console to UTF-8 first, otherwise Hebrew output dies on the legacy
code page:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
```

## Workflow

### 1. Inspect

`dump` lists every text block with its position, font and *readable* text
(Hebrew is un-reversed for display):

```powershell
python $EDIT dump in.pdf                      # everything
python $EDIT dump in.pdf --page 1 --grep ותק  # find a phrase
python $EDIT dump in.pdf --page 0 --y 83.926  # one table row
```

Blocks on the same `y` form one visual line. Columns of a table share `y`;
a column shares `x` across rows. This is how you identify what to edit.

### 2. Edit

```powershell
# same-width value (numbers, dates) - position unchanged
python $EDIT set in.pdf --page 0 --x 30.614 --y 74.004 --old 125 --new 150 -o out.pdf

# a word whose width changes - keeps the RIGHT edge (correct for RTL)
python $EDIT replace-word out.pdf --page 0 --x 460.913 --y 754.099 --old מאי --new יוני

# delete a whole line (all blocks on that y)
python $EDIT delete-row out.pdf --page 1 --y 721.721

# add a new cell/word, anchored after an existing block
python $EDIT insert out.pdf --page 0 --x 56.126 --y 83.926 --text 06 --after-x 77.102 --after-y 83.926
```

Omitting `-o` edits in place (useful for chaining several commands on the
output file). Pass Hebrew in normal logical order; `--visual` means the
argument is already reversed.

### 3. Verify

```powershell
python $EDIT render out.pdf check.png --page 0 --scale 3 --crop 600,80,1200,220
```

Then **view the PNG**. Render the whole page at least once at the end.

## Recipes

### Replacing a word in an RTL line

`replace-word` fixes the right edge, which is what RTL needs. If the new word
is **wider**, its left edge grows into whatever sits to its left — check the
render, and shift those neighbours left by the width delta (`insert` the block
again at a new x, or `set` its neighbours). If it is **narrower**, nothing
else moves and the gap simply widens.

To rebuild a whole phrase (e.g. `11 חודשים` → `3 שנים ו 11 חודשים`), delete
the old word blocks and emit new ones right-to-left from a fixed anchor:

```
x = anchor_x
for word in words_right_to_left:
    x -= gap + width(word)      # gap = the line's own inter-word gap
    emit block at x
```

Derive `gap` from two existing words on the same line:
`gap = x(right_word) − (x(left_word) + width(left_word))`, typically ≈2.4pt.

### Deleting a line

`delete-row --y` removes every block on that line, including dates drawn
character-by-character. It leaves the row's background band and any table
borders, so the row shows as an empty stripe. Mention this to the user and
offer to pull the lines below it up.

### Growing a table

Adding a column: `insert` a header cell and a value cell at
`x = x(last_column) − column_pitch` (pitch = the spacing between existing
column x values, e.g. 20.976pt), then update the total.

When a row is full, the generator wraps to a second line instead of shrinking
the pitch — copy the geometry from a real example with more columns
(`07.22.pdf` has a 7-month table):

- add header + value blocks on a new pair of `y` values (row pitch 9.921pt),
  restarting from the rightmost column x;
- duplicate the grey band rectangle (`0.867 0.867 0.867 rg <x> <y> <w> 7.37 re f`)
  at `value_y − 0.87`;
- extend the rounded-box path by the same amount: subtract the added height
  from every *bottom* coordinate of the `m/l/c` path (for a 2-row addition,
  19.842pt).

## Payslip month roll (תלוש שכר)

Rolling a Hilan payslip to another month touches five areas. The monthly
figures come from the payslip itself, so each step is arithmetic, not
invention.

| Area | What changes |
|---|---|
| Header (both pages) | `תלוש שכר לחודש: <month> <year>` |
| `יחידות מס` | one column per elapsed month (25 units each); `ס"ה` = their sum |
| `סכומים מצטברים לשנת המס` | each accumulator ± one month (table below) |
| `נתונים מצטברים של קופות גמל` | `שכר בסיס` ± monthly base, `הפרשה` ± monthly employer contribution |
| `היעדרויות` | `יתרה קודמת` ← previous `יתרה חדשה`; `זיכוי/ניצול מצטבר` ± this month; `יתרה חדשה = יתרה קודמת + זיכוי − ניצול` |
| `ותק אצל המעסיק` | recompute from `התחלת עבודה` to the payslip month |

Monthly increments, and where each one is read from:

| מצטבר | += monthly source |
|---|---|
| ברוטו רגיל | `ברוטו למס הכנסה` (נתונים חודשיים) |
| שווי למס | `סה"כ זקיפות שכר` |
| נטו לגילום | `גילום תשלומי נט` |
| מס רגיל | `מס הכנסה` (ניכויי חובה - מסים) |
| הכנסה לא מבוטחת | `סה"כ תשלומים בגין הוצאות` |
| ניכוי לסעיף 45א 35% | employee deduction, `סה"כ קופות גמל בהסכם` — on newer slips this cell equals the cumulative `קרן השתלמות` `הפרשה` rounded, so it must follow any change there |
| ערך נקודות זיכוי | `נקודות זיכוי` × the point value implied by the current cumulative |
| הכנסה חייבת במס / שכר חייב ב.ל. | identity: `ברוטו רגיל + נטו לגילום + גילום מס + גילום ב.ל.`, plus `שווי כסף נטו` when that row exists (newer slips) |

Checks that catch mistakes:

- the identity above must hold **before** the edit too — if it doesn't, the
  field mapping is wrong, stop and re-read the boxes;
- divide each accumulator by the number of elapsed months; the result should
  land on the monthly figure (small drift is normal, a factor-of-2 is a bug);
- gross-up cells (`גילום מס`, `גילום ב.ל.`) only move when there is a real
  gross-up that month;
- flag, don't silently fix, an accrual that would exceed its `מכסה שנתית`.

### Shifting the whole year instead of the month

Moving a slip from e.g. 2024 to 2026 while keeping its month is much smaller
than a month roll: the month-dependent tables (`יחידות מס`, all accumulators,
`היעדרויות`) describe position *within* the tax year and stay untouched. What
must move:

- every `<month> <year>` header (both pages of each slip);
- `ותק אצל המעסיק`, by the same number of years;
- any "previous year" note such as `שכר שווה לעובדת ולעובד … לשנת <year-1>`.

`ותק` counts the starting month **inclusive**: start 03/07/2022 → April 2024
is `1 שנים 10 חודשים` (Jul-22 … Apr-24 = 22 months). Note the wording differs
between generations — older slips write `3 שנים ו 11 חודשים`, newer ones omit
the `ו`, and an exact number of years is written `4 שנים` with no months part.
Copy the file's own wording.

### Gender

The slip is written in the employee's grammatical gender throughout. Check
which form the file uses before editing: `רווק`→`נשוי` for a man,
`רווקה`→`נשואה` for a woman. Getting this wrong is the most visible possible
mistake, and `replace-word` will happily insert either.

Produce the months as a **set in their own folder** (`final\05-2026-*.pdf`,
`06-…`, `07-…`) when generating several — it keeps naming clean and avoids
clashing with files the user has open.

## Known limits

- Only works where content streams are plain text. If `dump` prints nothing,
  the streams are compressed or use a different operator layout — re-generate
  the file or fall back to a full re-layout tool.
- Bold/regular is chosen by font resource (`/F1` = bold, `/F0` = regular in
  these payslips); a subset font may lack glyphs a brand-new word needs —
  confirm in the render, not just in `dump`.
