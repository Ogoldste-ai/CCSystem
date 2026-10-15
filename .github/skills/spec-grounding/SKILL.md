---
name: spec-grounding
description: 'Grounds implementation work in authoritative architecture, hardware, register, protocol, firmware, and design specifications.'
---

# Skill: Spec Grounding

## Purpose

Use this skill whenever work depends on architecture specifications, hardware specs, register descriptions, protocol definitions, firmware contracts, or design documents.

## When to Use

Use for:

- QEMU device modeling
- Linux driver development
- firmware and ROM work
- device tree review
- register behavior analysis
- security/lifecycle behavior
- any task where undocumented behavior would be risky

## Source and Tool Selection

Choose sources by the kind of fact being claimed:

### Local revision-specific design sources

When a task requires RTL or hardware-design information, inspect configured
local source roots when they are accessible. Record the source path and the
silicon revision to which it applies; do not extrapolate revision-specific
design evidence to other revisions.

| Revision | RTL / design source | Hardware-design documents |
|---|---|---|
| Tavor Z1 only | `~vlevyato/workspace/rtl/Tavor_z1/design/` | `~vlevyato/workspace/rtl/Tavor_z1/documents/doc/` |

These sources provide design evidence for the named revision. They do not
replace authoritative specifications for hardware facts.

- **Tavor / NPCM9mnx hardware facts:** use the `pdftomd-rag` skill to
  retrieve the relevant Tavor/NPCM9mnx PDF/spec section. Record document name,
  page/section, and the exact fact. Then inspect `qemu-tavor` code and
  `qemu-tavor/docs/tavor/README.md` for repository state and existing model
  decisions.
- **Caliptra public architecture / firmware facts:** use the rendered Caliptra
  docs and GitHub documentation listed below. For register fields, prefer the
  generated register reference when available.
- **Caliptra MCU firmware facts:** query both the current upstream `main`
  documentation and the source that matches the affected code or release (for
  example, `main-2.1` or the Nuvoton fork). Resolve `main` at task time,
  inspect `docs/src/SUMMARY.md` to discover the current relevant source, and
  record its commit SHA. For every claimed behavior, cite the exact Markdown
  source from both branches, including repository, branch, and commit SHA. If
  a fact is absent or differs, report that explicitly; the version-matched
  source determines compatibility, while `main` provides the current upstream
  perspective. Do not combine claims from different branches without
  identifying the version difference.
- **Repository implementation facts:** inspect the local checked-out child repo
  (`qemu-tavor/`, `caliptra-sw/`, `caliptra-mcu-sw/`, or
  `Tavor_Linux_Kernel/`) and cite local file paths/locations.
- **Any Caliptra-related claim (question or design work): check both
  `caliptra-mcu-sw` and `caliptra-sw`, never just one.** The two repos cover
  different layers (MCU ROM/runtime vs. Caliptra Core) and can each hold
  information the other lacks, or even state something the other
  contradicts (a register/lock semantic, a command's existence or wire
  format, an implementation-status claim). Consulting only one risks missing
  facts or asserting something the other repo disproves. When the two
  genuinely disagree about **Caliptra Core** behavior specifically (as
  opposed to MCU-side integration code, which `caliptra-mcu-sw` owns), treat
  `caliptra-sw` as the more likely correct and up-to-date source, since it
  owns Caliptra Core itself — but still record the discrepancy rather than
  silently discarding one side.
- **Nuvoton fork or platform-specific behavior:** inspect the local child repo
  first. If it differs from upstream Chips Alliance documentation, document both
  the upstream fact and the local/Nuvoton fact instead of merging them.

Do not treat QEMU models, Linux drivers, firmware code, or old design notes as
the only source of hardware truth. They can prove repository behavior, not
hardware intent.

## Process

Thorough investigation does not require lengthy documentation. Preserve the
user's approved wording and requested level of detail unless correctness
requires clarification. Record detailed evidence in the investigation or LLD;
keep only the architectural statement and necessary evidence qualifier in the
HLD. Explain a finding once and link to its owning document rather than
repeating it across artifacts. Use explicit partition, register, and field
names in backticks. Do not omit essential uncertainty or security conditions
to make an answer shorter.

1. Identify the relevant source of truth.
2. Retrieve or inspect the relevant specification sections. For Caliptra MCU
   work, resolve the current upstream `main` commit and the version-matched
   source, inspect each `docs/src/SUMMARY.md`, then inspect both relevant
   Markdown files.
3. Extract only supported facts.
4. Separate:
   - FACT FROM SPEC
   - FACT FROM REPOSITORY
   - ASSUMPTION
   - OPEN QUESTION
   - DEFERRED / OUT OF SCOPE
5. Do not infer side effects unless explicitly supported.
6. If spec and code disagree, document both.
7. If evidence is missing, say so explicitly.

## Required Output Pattern

Use this structure when relevant:

```markdown
## Spec Grounding

### Facts from Spec

| Fact | Evidence |
|---|---|

### Facts from Repository

| Fact | File / Location |
|---|---|

### Assumptions

### Open Questions

### Deferred / Out of Scope
```

For Caliptra MCU work, add these sections and populate both source tables:

```markdown
### Facts from Current Upstream (`main`)

| Fact | Exact file / branch / commit |
|---|---|

### Facts from Version-Matched Source

| Fact | Exact file / branch / commit |
|---|---|

### Source Divergences and Applicability
```

## Known Sources and Entry Points

| Source | Location | Scope |
|---|---|---|
| Tavor / NPCM9mnx hardware PDFs | global `pdftomd-rag` skill | Authoritative Tavor hardware registers, memory map, reset, interrupt, clock, boot, and block-level behavior |
| QEMU Tavor docs entry point | `qemu-tavor/docs/tavor/README.md` | QEMU-local design and validation index; repository context, not a hardware specification |
| Caliptra 2.1 documentation set (rendered) | https://chipsalliance.github.io/caliptra-web/docs/2.1/ | Entry point (mdBook root) for the Caliptra 2.1 spec set: core/overview, ROM, FMC, runtime, DICE/attestation, image format, integration, and the subsystem hardware spec. Navigate to the exact sub-page and cite it for final citations. |
| Caliptra Subsystem Hardware Spec v2.1 | https://chipsalliance.github.io/caliptra-web/docs/2.1/subsystem/ss_hardware_spec.html | Deep-link sub-page of the row above (precise citation anchor): Caliptra subsystem registers, memory map, interfaces, lifecycle |
| Caliptra MCU SW docs (rendered) | https://chipsalliance.github.io/caliptra-mcu-sw/ | MCU, ROM, and runtime specifications; I3C/DOT/recovery; fuses/SVN; firmware packaging/loading/update/attestation; flash; MCTP/PLDM/SPDM/DOE/IDE-KM/TDISP; commands/logging; provisioning, integration, host tools, recovery, and testing |
| Caliptra MCU SW docs source (current) | https://github.com/chipsalliance/caliptra-mcu-sw/tree/main/docs/src | Query at task time; inspect `SUMMARY.md`, record the resolved `main` commit, and cite exact Markdown files |
| Caliptra MCU SW docs source (v2.1) | https://github.com/chipsalliance/caliptra-mcu-sw/tree/main-2.1/docs/src | Versioned upstream Markdown source; compare it with current `main` when the code or requirement is on the v2.1 release line |
| Nuvoton Caliptra MCU fork docs source (v2.1) | https://github.com/Nuvoton-Israel/nuvoton-caliptra-mcu-sw/tree/main-2.1/docs/src | Version-matched Nuvoton source; compare it with current upstream `main` and record platform deviations |
| Caliptra SS Integration Specification | https://github.com/chipsalliance/caliptra-ss/blob/main/docs/CaliptraSSIntegrationSpecification.md | Caliptra SS integration behavior, interfaces, and integration contract details |
| Caliptra SS fuse_ctrl docs directory | https://github.com/chipsalliance/caliptra-ss/tree/main/src/fuse_ctrl/doc | Entry point for upstream OTP/fuse memory-map and zeroization docs; prefer the exact document link in final citations |
| Caliptra SS MCI Top register reference (`soc.mci_top`) | https://chipsalliance.github.io/caliptra-ss/main/regs/?p=soc.mci_top | MCI mailbox register definitions and field-level documentation for the subsystem MCI block |
| Caliptra RTL external register index | https://chipsalliance.github.io/caliptra-rtl/main/external-regs/ | Entry point for Caliptra external register browsing; prefer the exact `?p=` page for final citations |



For every Caliptra MCU behavior, query current upstream `main` and the
version-matched source during the task. Cite the exact `docs/src/*.md` file
from each source, including repository, branch, and commit SHA. If one source
does not contain an equivalent fact or the sources differ, state that in
`Source Divergences and Applicability`; do not cite only the rendered book or
repo root when a specific document supports the claim.


## External-Visible Software Architecture Documents

If the task is to create, generate, update, or review an external-visible
software architecture document under `docs/design/`, also follow the
[`high-level-design-workflow.md`](../../../docs/development/high-level-design-workflow.md)
contract in addition to this skill's grounding process.

For topic HLDs, grounding detail must respect the HLD/LLD boundary:

- keep only the citation or evidence qualifier needed to support an
  architectural statement in the HLD;
- put the collected source inventory in
  `docs/agentic/<feature>/low-level-design.md` `§5 Sources Used`;
- put repository/specification evidence classification in LLD
  `§7 Evidence Classification`;
- put unresolved source conflicts, decision owners, and consequences in LLD
  `§20 Open Questions`;
- do not create `References`, `Implementation status and evidence`, or
  `Open Questions / Concerns` sections in a topic HLD;
- when a grounding diagram is useful at both levels, keep the concise
  architecture copy in the HLD and copy it to the LLD with the detailed
  evidence.

Grounding remains mandatory even though the detailed evidence moves out of the
HLD. Never weaken, omit, or invent a claim merely to keep the HLD concise.

## Red Flags

- Hardware behavior described without spec evidence
- Previous silicon behavior assumed as valid
- Register side effects inferred from naming only
- Driver behavior used as the only source of hardware truth
- Missing reset values
- Missing interrupt semantics
- Missing access-width rules
- A Caliptra-related claim (in an answer or a design document) grounded in
  only `caliptra-mcu-sw` or only `caliptra-sw` when the other repo was never checked
