# Marius CLI Client

The Marius CLI is a professional terminal-based conversation client for interacting with the Marius resident agent on McServer. It provides a similar experience to `ollama run`, but with integrated access to McServer's memory, project status, and handoff tools.

## Quick Start

Run the client from the project root:

```bash
./scripts/marius
```

Or for a single message:

```bash
./scripts/marius --once "Who are you?"
```

## Installation

You can install Marius to your local bin directory (usually `~/.local/bin`) to run it from anywhere:

```bash
./scripts/install_marius_user.sh
```

## Features

- **Interactive REPL**: Clean prompt with command history (via `prompt_toolkit`).
- **API Auto-Discovery**: Automatically probes for a running Warden/Marius API server.
- **Resident Context**: Real-time access to server and project status.
- **Memory Management**: Easily save and recall facts. Supports natural language triggers like "remember that ...".
- **Agent Handoff**: Generate prompts for Codex, Grok, or Antigravity.
- **Session Stats**: Keep track of messages and memory writes in the current session.

## Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `/status` | `/s` | Show server and project health status |
| `/projects` | `/p` | List active project cards |
| `/leftoff` | `/lo` | Show the last recorded progress summary |
| `/remember <note>` | | Save a durable fact to general memory |
| `/remember <cat>: <note>` | | Save a fact under a specific category |
| `/recall <query>` | `/r` | Search through saved memories |
| `/handoff <target>` | | Generate a handoff prompt for a specific agent |
| `/model` | `/m` | Show current model and provider status |
| `/api [url]` | | View or set the API base URL |
| `/config` | | View current configuration file path and settings |
| `/session` | | View session statistics (started at, messages sent, etc.) |
| `/clear` | | Clear the terminal screen |
| `/help` | `/h` | Show available commands |
| `/exit` | `/q`, `q` | Exit the CLI |

## Natural Language Memory

Marius will automatically save memory if you start a message with:
- `remember that ...`
- `note that ...`
- `save this ...`

## Configuration

Marius stores local configuration in `~/.config/marius/config.json`. This includes the last working `api_base`.

Resolution order:
1. `--api` flag
2. `MARIUS_API_BASE` environment variable
3. `~/.config/marius/config.json`
4. Auto-probe (tries 8126, 8128, 8125)

## Troubleshooting

- **API Offline**: Ensure the Warden/McHarness dev server is running.
- **Ollama Offline**: Marius will operate in `fallback` mode. You can check status with `/model`.
- **History not working**: Ensure `prompt_toolkit` is installed in your python environment.
