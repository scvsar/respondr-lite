@AGENTS.md

# Claude Code Adapter

Claude-specific notes:

- Discover reusable workflows in `.claude\skills\`.
- Discover specialist subagents in `.claude\agents\`.
- Load shared MCP servers from `.mcp.json`.
- Load project hooks from `.claude\settings.json`.
- Treat `.agents\skills\` as the canonical skill source.
- Treat `.codex\` and `.github\` as other provider adapters.
- Do not duplicate durable repository rules here. Update `AGENTS.md` instead.
