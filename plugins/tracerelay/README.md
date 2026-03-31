# TraceRelay Plugin Support

## Codex

Run:

```bash
bash ./scripts/install_codex_plugin.sh
```

It creates:

- `~/plugins/tracerelay`
- `~/.agents/plugins/marketplace.json`

The installer reads `./.env` from the repository and writes a home-local MCP config for the plugin.
Codex connects to the running docker-compose MCP server through `.codex-plugin/mcp.json` at `http://127.0.0.1:5064/mcp` by default.
If you change `TRACERELAY_PLUGIN_MCP_URL`, rerun the installer.

## Claude Code

Run:

```bash
bash ./scripts/install_claude_code_plugin.sh
```

It installs:

- local marketplace: `tracerelay-local`
- plugin: `tracerelay`

Rerun the installer after changing `.env` or plugin files so Claude Code picks up the latest TraceRelay behavior.
Claude Code uses the root `.mcp.json` and expects the docker-compose MCP server to already be running at `http://127.0.0.1:5064/mcp` by default.

Natural prompts that should route well in Claude Code:

- `Continue what we learned about ASPI and use prior findings before searching again.`
- `What changed in the latest run and why did it retry?`
- `Structure this company and keep the previous memory in play.`
