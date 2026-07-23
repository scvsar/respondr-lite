# Copilot Customization Instructions

## Customization Layout

| Type | Location | Pattern | Purpose |
|---|---|---|---|
| Shared rules | repository root | `AGENTS.md` | Canonical guidance |
| Shared skills | `.agents/skills/<name>/` | `SKILL.md` | On-demand workflow |
| Codex agents | `.codex/agents/` | `*.toml` | Codex specialists |
| Claude agents | `.claude/agents/` | `*.md` | Claude specialists |
| Copilot agents | `.github/agents/` | `*.agent.md` | Copilot specialists |
| Instructions | `.github/instructions/` | `*.instructions.md` | Focused adapters |
| Prompts | `.github/prompts/` | `*.prompt.md` | Task templates |
| Hooks | `.github/hooks/` | JSON and PowerShell | Policy checks |

## Rules

- Keep durable repository policy in `AGENTS.md`.
- Keep canonical reusable skills in `.agents\skills\`.
- Let Codex and Copilot discover `.agents\skills\` directly.
- Keep byte-identical Claude mirrors in `.claude\skills\`.
- Do not add duplicate skills under `.github\skills\`.
- Give skills, Copilot agents, and prompts valid YAML frontmatter.
- Use lowercase names with letters, numbers, and hyphens.
- Make a skill `name` match its folder.
- Write descriptions that state when to use the customization.
- Keep credentials and personal MCP defaults outside the repository.
- Run `.\scripts\test-agent-artifacts.ps1` after each artifact change.

## Skill Frontmatter

```yaml
---
name: example-skill
description: Use this skill when a task needs an example workflow.
---
```

Do not add a blank line before the opening delimiter.
