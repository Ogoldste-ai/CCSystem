# Skill group template

A **group** bundles several related skills so they install as **one plugin**.

## Dev layout (CCSystem)

```text
.github\skills\<group>\
  group.json                 manifest: name, description, member skills
  <skill-a>\SKILL.md
  <skill-b>\SKILL.md         (plus any server\, scripts\, references\)
```

`group.json` is CCSystem bookkeeping, not a Copilot manifest. Copilot discovers
each member's `SKILL.md`; no generator or promotion tool reads `group.json`.
Its `skills` array lists member directory names relative to the group folder.
Keep all members inside that folder, with unique skill names across groups.

## Marketplace layout (after promotion)

```text
copilot-marketplace\plugins\<group>\
  plugin.json
  skills\<skill-a>\SKILL.md
  skills\<skill-b>\SKILL.md
```

The plugin manifest uses the marketplace's existing legacy format:

```json
{
  "name": "shared-skills-topic",
  "description": "A bundle of related skills",
  "version": "1.0.0",
  "author": {
    "name": "Oren Goldstein",
    "email": "oren.goldstein@nuvoton.com"
  },
  "skills": "skills"
}
```

Unlike `group.json`, the plugin's `skills` field is a directory string, not an
array of member names. Do not copy `group.json` unchanged as `plugin.json`.

## Naming

`shared-skills-<topic>` (usable by everyone) or `local-skills-<topic>` (this machine/team only).

## Create a new group

1. Copy this folder to `.github\skills\<group>\` and delete the copied README.
2. Rename `group.json.template` to `group.json` and fill it in.
3. For each member, create `<group>\<skill>\` and copy `SKILL.md.template` there
   as `SKILL.md`. Replace its placeholders, matching the name to the directory.
4. List each member directory in `group.json`. Remove the copied root
   `SKILL.md.template` after creating the members.

## Verified development discovery

Copilot CLI 1.0.105 was checked with temporary flat and nested skills using
`copilot skill list --json`. Both were discovered as project skills, including
`.github\skills\_group-template\<probe>\SKILL.md`. The probes were then removed.
This confirms the grouped layout on that version, not every Copilot client.

After adding members, run `/skills reload` in an interactive session, then
`/skills info <skill-name>` to check their locations. From the terminal, use
`copilot skill list --json`.

The template's files end in `.template`, not `SKILL.md`, so the template itself
does not load as a skill.

## Promote checklist (only on explicit request)

These are manual steps, not an implemented packaging command:

1. Read `copilot-marketplace\.github\copilot-instructions.md`.
2. Create `copilot-marketplace\plugins\<group>\skills\`. For each member listed
   in `group.json`, copy the entire `.github\skills\<group>\<member>\` directory
   into that destination, preserving scripts, servers, and references.
3. Create `plugins\<group>\plugin.json` using the group's `name`, `description`,
   `version`, and `author`, but set `"skills": "skills"` as shown above.
4. Register one plugin entry in
   `copilot-marketplace\.github\plugin\marketplace.json`, with the group name
   and `"source": "plugins/<group>"`. Manifest paths use forward slashes.
5. Add or update one entry per member in
   `copilot-marketplace\marketplace\skills_catalog.json`, pointing to
   `plugins/<group>/skills/<member>/SKILL.md`. Update the agent catalog only if
   the package also includes agents. Follow the marketplace's validation rules.

Once the group is published and its marketplace is registered, install all
members together with
`copilot plugin install <group>@nuvoton-copilot-marketplace`.
MCP server configuration and other member prerequisites still follow each
skill's instructions; bundling does not provision them automatically.
