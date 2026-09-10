from __future__ import annotations
import asyncio
import json
import subprocess
from datetime import datetime

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Label, RichLog
from textual.screen import ModalScreen

from netmon.config import DOCKER_POLL_INTERVAL


class _ConfirmModal(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    BINDINGS = [
        ("y", "confirm",  "Yes"),
        ("n", "cancel",   "No"),
        ("escape", "cancel", "No"),
    ]

    def __init__(self, title: str, body: str = "") -> None:
        super().__init__()
        self._title = title
        self._body  = body

    def compose(self) -> ComposeResult:
        from textual.widgets import Button, Label
        from textual.containers import Vertical
        yield Vertical(
            Label(f"[bold red]{self._title}[/bold red]", id="confirm-title"),
            Label(f"[dim]{self._body}[/dim]",            id="confirm-body"),
            Label("[bold]y[/bold] confirm   [bold]n / Esc[/bold] cancel", id="confirm-keys"),
            id="confirm-box",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class DockerLogsModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, name: str) -> None:
        super().__init__()
        self._container_name = name

    def compose(self) -> ComposeResult:
        yield RichLog(id="logs-output", markup=False, highlight=False)

    def on_mount(self) -> None:
        self.title = f"logs: {self._container_name}"
        self._load_logs()

    def _load_logs(self) -> None:
        log = self.query_one(RichLog)
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", "100", self._container_name],
                capture_output=True, text=True, timeout=5,
            )
            for line in (result.stdout + result.stderr).splitlines():
                log.write(line)
        except Exception as e:
            log.write(f"[red]Error: {e}[/red]")


class DockerPane(Widget):
    BORDER_TITLE = "DOCKER  [dim](r restart  s stop  d delete  l logs)[/dim]"

    BINDINGS = [
        ("r", "restart_selected", "Restart"),
        ("s", "stop_selected",    "Stop"),
        ("d", "delete_selected",  "Delete"),
        ("l", "show_logs",        "Logs"),
    ]

    class DockerSelected(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._available  = True
        self._containers: list[dict] = []
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="docker-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Name", key="name", width=20)
        table.add_column("Status", key="status", width=14)
        table.add_column("Ports", key="ports")
        self.set_interval(DOCKER_POLL_INTERVAL, self._poll)

    async def _poll(self) -> None:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "ps", "--format", "{{json .}}"],
                capture_output=True, text=True, timeout=5,
            )
            containers = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    containers.append(json.loads(line))
            self._containers = containers
            self._available = True
            self._refresh_table()
        except FileNotFoundError:
            self._available = False
            self._show_unavailable()
        except Exception:
            pass

    def _refresh_table(self) -> None:
        self._refreshing = True
        table = self.query_one(DataTable)
        table.clear()
        for c in self._containers:
            name = c.get("Names", c.get("Name", "?"))
            status = c.get("Status", "?")
            ports = _format_ports(c.get("Ports", ""))
            color = "green" if "Up" in status else "red"
            table.add_row(name, f"[{color}]{status}[/{color}]", ports, key=name)
        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False

    def _show_unavailable(self) -> None:
        table = self.query_one(DataTable)
        table.clear()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._refreshing and event.row_key:
            self.post_message(DockerPane.DockerSelected(str(event.row_key.value)))

    def _selected_name(self) -> str | None:
        table = self.query_one(DataTable)
        try:
            rows = list(table.ordered_rows)
            if table.cursor_row < len(rows):
                return str(rows[table.cursor_row].key.value)
        except Exception:
            pass
        return None

    def action_restart_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            subprocess.run(["docker", "restart", name], timeout=15)
            self.app.notify(f"Restarted {name}", severity="information")
        except Exception as e:
            self.app.notify(f"Restart failed: {e}", severity="error")

    def action_stop_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            subprocess.run(["docker", "stop", name], timeout=15)
            self.app.notify(f"Stopped {name}", severity="warning")
        except Exception as e:
            self.app.notify(f"Stop failed: {e}", severity="error")

    def action_delete_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        self.app.push_screen(
            _ConfirmModal(f"Delete container  {name} ?", "This cannot be undone."),
            lambda confirmed: self._do_delete(name) if confirmed else None,
        )

    def _do_delete(self, name: str) -> None:
        try:
            subprocess.run(["docker", "rm", "-f", name], timeout=15)
            self.app.notify(f"Deleted {name}", severity="error")
        except Exception as e:
            self.app.notify(f"Delete failed: {e}", severity="error")

    def action_show_logs(self) -> None:
        name = self._selected_name()
        if name:
            self.app.push_screen(DockerLogsModal(name))


def _format_ports(ports_str: str) -> str:
    if not ports_str:
        return ""
    parts = []
    for segment in ports_str.split(","):
        segment = segment.strip()
        # e.g. "0.0.0.0:8080->80/tcp" → "8080"
        if "->" in segment:
            host_part = segment.split("->")[0]
            if ":" in host_part:
                parts.append(host_part.rsplit(":", 1)[-1])
        elif segment:
            parts.append(segment)
    return ", ".join(parts[:4])
