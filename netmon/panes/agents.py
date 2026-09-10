from __future__ import annotations
import asyncio
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from netmon.config import AI_PROCESS_PATTERNS, AI_SERVICE_PORTS

_AGENT_POLL_INTERVAL = 3.0


@dataclass
class AgentProcess:
    pid: str
    name: str
    cpu: str
    mem: str
    started: str
    note: str


class AgentsPane(Widget):
    BORDER_TITLE = "AI AGENTS"

    class AgentSelected(Message):
        def __init__(self, name: str, pid: str) -> None:
            super().__init__()
            self.name = name
            self.pid = pid

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._seen: set[str] = set()
        self._agents: dict[str, AgentProcess] = {}
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="agents-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Name",    key="name",    width=16)
        table.add_column("PID",     key="pid",     width=7)
        table.add_column("CPU%",    key="cpu",     width=6)
        table.add_column("MEM%",    key="mem",     width=6)
        table.add_column("Note",    key="note")
        self.set_interval(_AGENT_POLL_INTERVAL, self._poll)

    async def _poll(self) -> None:
        agents = await asyncio.to_thread(_scan_agents)
        self._agents = {a.pid: a for a in agents}
        self._refresh_table(agents)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._refreshing and event.row_key:
            pid = str(event.row_key.value)
            agent = self._agents.get(pid)
            if agent:
                self.post_message(AgentsPane.AgentSelected(agent.name, pid))

    def _refresh_table(self, agents: list[AgentProcess]) -> None:
        self._refreshing = True
        table = self.query_one(DataTable)
        current_pids = {a.pid for a in agents}

        # Remove stale rows
        for pid in self._seen - current_pids:
            try:
                table.remove_row(pid)
            except Exception:
                pass

        for a in agents:
            cpu_color = "red" if float(a.cpu or 0) > 10 else "green"
            row = (
                a.name,
                a.pid,
                f"[{cpu_color}]{a.cpu}[/{cpu_color}]",
                a.mem,
                a.note,
            )
            if a.pid not in self._seen:
                try:
                    table.add_row(*row, key=a.pid)
                except Exception:
                    pass
            else:
                for col, val in zip(["name", "cpu", "mem", "note"], [a.name, row[2], a.mem, a.note]):
                    try:
                        table.update_cell(a.pid, col, val, update_width=False)
                    except Exception:
                        pass

        self._seen = current_pids
        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False


def _scan_agents() -> list[AgentProcess]:
    agents: dict[str, AgentProcess] = {}

    # --- ps-based detection -------------------------------------------
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines()[1:]:  # skip header
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            pid, cpu, mem, command = parts[1], parts[2], parts[3], parts[10]
            cmd_lower = command.lower()

            # Skip our own processes and noise
            if "ps aux" in cmd_lower or "grep" in cmd_lower:
                continue
            # Skip Electron sub-processes (renderer, GPU, utility, crash handler)
            if _is_electron_helper(cmd_lower):
                continue

            matched_name = _match_pattern(cmd_lower)
            if not matched_name:
                continue

            note = _summarise_command(command)
            agents[pid] = AgentProcess(
                pid=pid,
                name=matched_name,
                cpu=cpu,
                mem=mem,
                started=parts[8],
                note=note,
            )
    except Exception:
        pass

    # --- port-based detection (AI services) ---------------------------
    try:
        lsof = subprocess.run(
            ["lsof", "-i", "-P", "-n"],
            capture_output=True, text=True, timeout=5,
        )
        for line in lsof.stdout.splitlines():
            if "LISTEN" not in line:
                continue
            parts = line.split()
            if len(parts) < 9:
                continue
            cmd, pid, addr = parts[0], parts[1], parts[8]
            try:
                port = int(addr.rsplit(":", 1)[-1])
            except ValueError:
                continue
            service = AI_SERVICE_PORTS.get(port)
            if service and pid not in agents:
                agents[pid] = AgentProcess(
                    pid=pid, name=cmd, cpu="", mem="",
                    started="", note=f":{port} {service}",
                )
    except Exception:
        pass

    # --- Ollama model info (best-effort) ------------------------------
    try:
        r = subprocess.run(
            ["curl", "-sf", "http://localhost:11434/api/ps"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            models = [m.get("name", "") for m in data.get("models", [])]
            if models:
                for a in agents.values():
                    if "ollama" in a.name.lower():
                        object.__setattr__(a, "note", f"models: {', '.join(models)}")
    except Exception:
        pass

    return sorted(agents.values(), key=lambda a: a.name.lower())


def _is_electron_helper(cmd_lower: str) -> bool:
    """Return True for Electron renderer/GPU/utility sub-processes — skip these."""
    noisy = (
        "--type=renderer", "--type=gpu-process", "--type=utility",
        "--type=crashpad-handler", "--monitor-self", "shipit",
        "chrome-native-host",
    )
    return any(n in cmd_lower for n in noisy)


def _match_pattern(cmd_lower: str) -> str | None:
    for pattern, label in AI_PROCESS_PATTERNS:
        if pattern in cmd_lower:
            return label
    return None


def _summarise_command(command: str) -> str:
    """Return a short human-readable summary of the command."""
    parts = command.split()
    if not parts:
        return ""
    # Strip path from binary name
    binary = parts[0].split("/")[-1]
    flags = [p for p in parts[1:] if p.startswith("-")]
    args = [p for p in parts[1:] if not p.startswith("-") and "/" not in p][:2]
    summary_parts = flags[:2] + args[:1]
    return " ".join(summary_parts) if summary_parts else binary
