from __future__ import annotations
import asyncio
import subprocess

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog


class DetailPane(Widget):
    BORDER_TITLE = "DETAILS"

    def compose(self) -> ComposeResult:
        yield RichLog(id="detail-log", wrap=True, markup=True, highlight=False)

    # ── public API ────────────────────────────────────────────────────────────

    def show_port(self, port: int, pid: str, cmd: str, name: str) -> None:
        self.border_title = f"DETAILS  port {port}"
        self._clear()
        self._load_port(port, pid, cmd, name)

    def show_docker(self, name: str) -> None:
        self.border_title = f"DETAILS  {name}"
        self._clear()
        self._load_docker(name)

    def show_agent(self, name: str, pid: str) -> None:
        self.border_title = f"DETAILS  {name}"
        self._clear()
        self._load_agent(name, pid)

    def show_session(self, session) -> None:
        self.border_title = f"DETAILS  {session.project}"
        self._clear()
        self._load_session(session)

    def show_cursor_session(self, session) -> None:
        self.border_title = f"DETAILS  {session.project} · {session.name}"
        self._clear()
        self._load_cursor_session(session)

    def show_heroku(self, name: str, web_url: str) -> None:
        self.border_title = f"DETAILS  {name}"
        self._clear()
        self._load_heroku(name, web_url)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _clear(self) -> None:
        self.query_one(RichLog).clear()

    def _w(self, text: str = "") -> None:
        self.query_one(RichLog).write(text)

    # ── workers ───────────────────────────────────────────────────────────────

    @work(exclusive=True, group="detail-fetch")
    async def _load_port(self, port: int, pid: str, cmd: str, name: str) -> None:
        self._w(f"[bold cyan]:{port}[/bold cyan]  [bold]{name or cmd}[/bold]  [dim]pid {pid}[/dim]\n")

        ps = await asyncio.to_thread(
            _run, ["ps", "-p", pid, "-o", "user=,pcpu=,pmem=,etime=,command="]
        )
        if ps:
            parts = ps.split(None, 4)
            for label, val in zip(["user", "cpu%", "mem%", "uptime", "command"], parts):
                self._w(f"  [dim]{label:<9}[/dim]{val}")
            self._w()

        net = await asyncio.to_thread(
            _run, ["lsof", "-p", pid, "-i", "-P", "-n"]
        )
        if net:
            self._w("[bold]Connections[/bold]")
            for line in net.splitlines()[1:]:
                self._w(f"  {line}")
        else:
            self._w("[dim]No network connections found[/dim]")

    @work(exclusive=True, group="detail-fetch")
    async def _load_docker(self, name: str) -> None:
        self._w(f"[bold cyan]{name}[/bold cyan]\n")

        inspect = await asyncio.to_thread(_run, [
            "docker", "inspect", "--format",
            "  image:    {{.Config.Image}}\n"
            "  status:   {{.State.Status}}\n"
            "  restarts: {{.RestartCount}}\n"
            "  created:  {{.Created}}",
            name,
        ])
        if inspect:
            self._w(inspect)
            self._w()

        logs = await asyncio.to_thread(
            _run, ["docker", "logs", "--tail", "50", "--timestamps", name], True
        )
        if logs:
            self._w("[bold]Logs (last 50 lines)[/bold]")
            for line in logs.splitlines():
                self._w(f"  {line}")
        else:
            self._w("[dim]No logs[/dim]")

    @work(exclusive=True, group="detail-fetch")
    async def _load_agent(self, name: str, pid: str) -> None:
        self._w(f"[bold cyan]{name}[/bold cyan]  [dim]pid {pid}[/dim]\n")

        ps = await asyncio.to_thread(
            _run, ["ps", "-p", pid, "-o", "user=,pcpu=,pmem=,etime=,command="]
        )
        if ps:
            parts = ps.split(None, 4)
            for label, val in zip(["user", "cpu%", "mem%", "uptime", "command"], parts):
                self._w(f"  [dim]{label:<9}[/dim]{val}")
            self._w()

        net = await asyncio.to_thread(
            _run, ["lsof", "-p", pid, "-i", "-P", "-n"]
        )
        if net:
            self._w("[bold]Connections[/bold]")
            for line in net.splitlines()[1:]:
                self._w(f"  {line}")
        else:
            self._w("[dim]No network connections[/dim]")


    @work(exclusive=True, group="detail-fetch")
    async def _load_cursor_session(self, session) -> None:
        from netmon.panes.cursor_sessions import _read_composers
        from pathlib import Path

        mode_color = "cyan" if session.mode == "agent" else "dim"
        ctx_color = "red" if session.context_pct > 80 else ("yellow" if session.context_pct > 50 else "green")
        self._w(f"[bold cyan]{session.project}[/bold cyan]  [dim]{session.name}[/dim]\n")
        self._w(f"  [dim]{'mode':<12}[/dim][{mode_color}]{session.mode}[/{mode_color}]")
        self._w(f"  [dim]{'branch':<12}[/dim]{session.branch or '—'}")
        self._w(f"  [dim]{'context':<12}[/dim][{ctx_color}]{session.context_pct:.1f}%[/{ctx_color}]")
        self._w(f"  [dim]{'lines added':<12}[/dim][green]+{session.lines_added}[/green]  [red]-{session.lines_removed}[/red]")
        self._w(f"  [dim]{'files':<12}[/dim]{session.files_changed}")
        self._w(f"  [dim]{'path':<12}[/dim]{session.project_path}")
        if session.last_updated:
            self._w(f"  [dim]{'updated':<12}[/dim]{session.last_updated.strftime('%Y-%m-%d %H:%M UTC')}")
        if session.created_at:
            self._w(f"  [dim]{'created':<12}[/dim]{session.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
        self._w(f"  [dim]{'id':<12}[/dim]{session.composer_id}")

    @work(exclusive=True, group="detail-fetch")
    async def _load_heroku(self, name: str, web_url: str) -> None:
        self._w(f"[bold cyan]{name}[/bold cyan]\n")
        if web_url:
            self._w(f"  [dim]url[/dim]  {web_url}\n")

        # Dyno status
        ps = await asyncio.to_thread(
            _run, ["heroku", "ps", "--app", name]
        )
        if ps:
            self._w("[bold]Dynos[/bold]")
            for line in ps.splitlines():
                self._w(f"  {line}")
            self._w()

        # Recent logs tail
        logs = await asyncio.to_thread(
            _run, ["heroku", "logs", "--app", name, "--num", "40"]
        )
        if logs:
            self._w("[bold]Logs (last 40 lines)[/bold]")
            for line in logs.splitlines():
                self._w(f"  {line}")

    @work(exclusive=True, group="detail-fetch")
    async def _load_session(self, session) -> None:
        from netmon.panes.sessions import _parse_jsonl, PROJECTS_DIR
        from pathlib import Path

        state_color = "green" if session.state == "active" else ("yellow" if session.state == "recent" else "dim")
        self._w(f"[bold cyan]{session.project}[/bold cyan]  [{state_color}]{session.state}[/{state_color}]\n")

        self._w(f"  [dim]{'session':<12}[/dim]{session.session_id}")
        self._w(f"  [dim]{'path':<12}[/dim]{session.project_path}")
        if session.git_branch:
            self._w(f"  [dim]{'branch':<12}[/dim]{session.git_branch}")
        if session.model:
            self._w(f"  [dim]{'model':<12}[/dim]{session.model}")
        if session.permission_mode:
            self._w(f"  [dim]{'permissions':<12}[/dim]{session.permission_mode}")
        self._w(f"  [dim]{'tokens':<12}[/dim]{session.tokens:,}")
        self._w(f"  [dim]{'tool calls':<12}[/dim]{session.tool_calls}")
        if session.last_active:
            self._w(f"  [dim]{'last active':<12}[/dim]{session.last_active.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        self._w()

        # Read recent tool calls from JSONL tail
        proj_encoded = session.project_path.replace("/", "-")
        jsonl_path = PROJECTS_DIR / proj_encoded / f"{session.session_id}.jsonl"
        if not jsonl_path.exists():
            # try to find it
            for d in PROJECTS_DIR.iterdir():
                candidate = d / f"{session.session_id}.jsonl"
                if candidate.exists():
                    jsonl_path = candidate
                    break

        recent_tools = await asyncio.to_thread(_recent_tool_calls, jsonl_path)
        if recent_tools:
            self._w("[bold]Recent tool calls[/bold]")
            for tool in recent_tools:
                self._w(f"  {tool}")


def _recent_tool_calls(path, n: int = 15) -> list[str]:
    """Extract the last N tool_use entries from a session JSONL."""
    import json
    tools: list[str] = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 32768))
            tail = f.read().decode("utf-8", errors="replace")
        for raw in tail.splitlines():
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            msg = entry.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    detail = ""
                    if "command" in inp:
                        detail = str(inp["command"])[:60]
                    elif "path" in inp:
                        detail = str(inp["path"])[:60]
                    elif "query" in inp:
                        detail = str(inp["query"])[:60]
                    tools.append(f"[cyan]{name}[/cyan]  [dim]{detail}[/dim]")
    except Exception:
        pass
    return tools[-n:]


def _run(cmd: list[str], include_stderr: bool = False) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        out = r.stdout + (r.stderr if include_stderr else "")
        return out.strip()
    except Exception:
        return ""
