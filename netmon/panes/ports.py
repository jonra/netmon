from __future__ import annotations
import contextlib
import subprocess

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Input
from textual.containers import Vertical

from netmon.services.port_scanner import PortScanner, PortInfo, PortDiff
from netmon.config import POLL_INTERVAL


class PortsPane(Widget):
    BORDER_TITLE = "LISTEN PORTS  [dim](k kill  / filter  Enter details)[/dim]"

    BINDINGS = [
        ("k", "kill_selected", "Kill"),
        ("slash", "focus_filter", "Filter"),
    ]

    class PortEvent(Message):
        def __init__(self, port: int, pid: str, cmd: str, name: str, online: bool) -> None:
            super().__init__()
            self.port = port
            self.pid = pid
            self.cmd = cmd
            self.name = name
            self.online = online

    class PortSelected(Message):
        def __init__(self, port: int, pid: str, cmd: str, name: str) -> None:
            super().__init__()
            self.port = port
            self.pid = pid
            self.cmd = cmd
            self.name = name

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._scanner = PortScanner()
        self._preset = "All"
        self._paused = False
        self._filter = ""
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="ports-table", cursor_type="row", zebra_stripes=True)
        yield Input(placeholder="filter ports… (Esc to clear)", id="port-filter")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Port",           key="port",  width=6)
        table.add_column("PID",            key="pid",   width=7)
        table.add_column("CMD",            key="cmd",   width=14)
        table.add_column("Name / Service", key="name")
        inp = self.query_one(Input)
        inp.display = False
        self.set_interval(POLL_INTERVAL, self._poll)

    # --- polling ---------------------------------------------------------

    async def _poll(self) -> None:
        if self._paused:
            return
        diff = await self._scanner.scan(self._preset)
        self._apply_diff(diff)

    def _apply_diff(self, diff: PortDiff) -> None:
        self._refreshing = True
        table = self.query_one(DataTable)

        # Initial population: snapshot non-empty, no adds/removes
        if not diff.added and not diff.removed:
            if table.row_count == 0 and diff.snapshot:
                for p in diff.snapshot:
                    if self._matches(p):
                        table.add_row(*_row(p), key=str(p.port))
            self.call_after_refresh(self._clear_refreshing)
            return

        for p in diff.added:
            if self._matches(p):
                with contextlib.suppress(Exception):
                    table.add_row(*_row(p), key=str(p.port))
            self.post_message(PortsPane.PortEvent(p.port, p.pid, p.cmd, p.name, online=True))

        for port in diff.removed:
            with contextlib.suppress(Exception):
                table.remove_row(str(port))
            self.post_message(PortsPane.PortEvent(port, "", "", "", online=False))

        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False

    # --- selection -------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._refreshing or event.row_key is None:
            return
        try:
            port = int(str(event.row_key.value))
        except (ValueError, TypeError):
            return
        info = self._scanner.current.get(port)
        if info:
            self.post_message(PortsPane.PortSelected(info.port, info.pid, info.cmd, info.name))

    # --- filter ----------------------------------------------------------

    def action_focus_filter(self) -> None:
        inp = self.query_one(Input)
        inp.display = True
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._filter = event.value.strip()
        self._rebuild_table()
        self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter = event.value.strip()
        self._rebuild_table()

    def on_key(self, event) -> None:
        if event.key == "escape":
            inp = self.query_one(Input)
            inp.value = ""
            inp.display = False
            self._filter = ""
            self._rebuild_table()
            self.query_one(DataTable).focus()

    def _rebuild_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for p in self._scanner.current.values():
            if self._matches(p):
                with contextlib.suppress(Exception):
                    table.add_row(*_row(p), key=str(p.port))

    def _matches(self, p: PortInfo) -> bool:
        if not self._filter:
            return True
        f = self._filter.lower()
        return f in str(p.port) or f in p.cmd.lower() or f in p.name.lower()

    # --- preset / pause --------------------------------------------------

    def set_preset(self, preset: str) -> None:
        self._preset = preset
        self._scanner.reset()
        self.query_one(DataTable).clear()

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    # --- kill ------------------------------------------------------------

    def action_kill_selected(self) -> None:
        table = self.query_one(DataTable)
        try:
            rows = list(table.ordered_rows)
            if table.cursor_row >= len(rows):
                return
            row_key = str(rows[table.cursor_row].key.value)
            port = int(row_key)
        except Exception:
            return

        info = self._scanner.current.get(port)
        if not info:
            return
        try:
            subprocess.run(["kill", "-9", info.pid], check=True)
            self.app.notify(f"Killed pid {info.pid} (port {port})", severity="warning")
        except subprocess.CalledProcessError as e:
            self.app.notify(f"Kill failed: {e}", severity="error")


def _row(p: PortInfo) -> tuple[str, str, str, str]:
    return (str(p.port), p.pid, p.cmd[:14], p.name or p.cmd)
