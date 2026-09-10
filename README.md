# netmon

A terminal UI for keeping an eye on what's running on your dev machine: listening
ports, Docker containers, Heroku apps, AI/agent processes, and local Claude Code /
Cursor sessions — all in one screen, built with [Textual](https://github.com/Textualize/textual).

## Features

- **Ports** — live table of listening ports with process name/PID, filterable, killable
- **Docker** — running containers with quick restart / log tailing
- **Heroku** — apps and dyno status (via the `heroku` CLI)
- **Agents** — detects running AI/agent processes (Claude, Ollama, LangChain, etc.)
- **Sessions** — recent Claude Code and Cursor sessions with token/tool-call counts
- **System metrics** — CPU/memory sparkline history

## Install

```bash
./install.sh
```

This creates a virtual environment in `.venv`, installs dependencies, and adds a
`netmon` launcher to `~/.local/bin` (added to your `PATH` automatically).

Then just run:

```bash
netmon
```

## Run without installing

```bash
./run-netmon
```

## Key bindings

| Key | Action |
| --- | --- |
| `1`–`5` | Jump to a pane (Ports, Details, Docker, Agents, Sessions) |
| `Space` | Pause/resume polling |
| `k` | Kill selected port's process |
| `/` | Filter |
| `r` | Restart selected Docker container |
| `l` | Tail logs for selected Docker container |
| `q` | Quit |
| `?` | Show help |

## Requirements

- Python 3.8+
- `docker` and/or `heroku` CLI on your `PATH`, if you want those panes populated

## License

MIT
