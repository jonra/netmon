from __future__ import annotations

import asyncio
import sys
from collections import deque

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from netmon.config import SYSMETRICS_INTERVAL, SYSMETRICS_HISTORY
from netmon.services.sysmetrics import (
    CpuSnapshot,
    MemSnapshot,
    collect_cpu,
    collect_memory,
    format_bytes,
)
from netmon.widgets.braille_plot import BraillePlot, Series


class CpuMetricsPane(Widget):
    BORDER_TITLE = "CPU"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history_sys: deque[float] = deque(maxlen=SYSMETRICS_HISTORY)
        self._history_user: deque[float] = deque(maxlen=SYSMETRICS_HISTORY)
        self._last: CpuSnapshot | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("", id="cpu-stats")
            with Vertical(id="cpu-chart-col"):
                yield Static("[dim]CPU LOAD[/dim]", id="cpu-chart-title")
                yield BraillePlot(id="cpu-plot", stacked=True)

    def on_mount(self) -> None:
        self._render_stats(None)
        self._poll()
        self.set_interval(SYSMETRICS_INTERVAL, self._poll)

    @work(exclusive=True, group="cpu-metrics")
    async def _poll(self) -> None:
        snap = await asyncio.to_thread(collect_cpu)
        if snap is None:
            return
        self._last = snap
        self._history_sys.append(snap.system)
        self._history_user.append(snap.user)
        self._render_stats(snap)
        self._draw_chart()

    def _render_stats(self, snap: CpuSnapshot | None) -> None:
        if snap is None:
            text = "[dim]System[/dim]  —\n[dim]User[/dim]    —\n[dim]Idle[/dim]    —"
        else:
            pct = lambda v: f"{v:.2f}".replace(".", ",")
            text = (
                f"[dim]System[/dim]  [red]{pct(snap.system)}%[/red]\n"
                f"[dim]User[/dim]    [cyan]{pct(snap.user)}%[/cyan]\n"
                f"[dim]Idle[/dim]    {pct(snap.idle)}%"
            )
        self.query_one("#cpu-stats", Static).update(text)

    def _draw_chart(self) -> None:
        if len(self._history_sys) < 2:
            return
        plot = self.query_one("#cpu-plot", BraillePlot)
        plot.set_series(
            [
                Series(self._history_sys, "red"),
                Series(self._history_user, "cyan"),
            ]
        )


class MemMetricsPane(Widget):
    BORDER_TITLE = "MEMORY"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pressure: deque[float] = deque(maxlen=SYSMETRICS_HISTORY)
        self._last: MemSnapshot | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="mem-pressure-col"):
                yield Static("[dim]MEMORY PRESSURE[/dim]", id="mem-pressure-label")
                yield BraillePlot(id="mem-pressure-plot")
            yield Static("", id="mem-summary")
            yield Static("", id="mem-detail")

    def on_mount(self) -> None:
        self._render_stats(None)
        self._poll()
        self.set_interval(SYSMETRICS_INTERVAL, self._poll)

    @work(exclusive=True, group="mem-metrics")
    async def _poll(self) -> None:
        snap = await asyncio.to_thread(collect_memory)
        if snap is None:
            return
        self._last = snap
        self._pressure.append(snap.pressure)
        self._render_stats(snap)
        self._draw_pressure()

    def _render_stats(self, snap: MemSnapshot | None) -> None:
        if snap is None:
            summary = (
                "[dim]Physical Memory[/dim]  —\n"
                "[dim]Memory Used[/dim]      —\n"
                "[dim]Cached Files[/dim]     —\n"
                "[dim]Swap Used[/dim]        —"
            )
            detail = (
                "[dim]App Memory[/dim]   —\n"
                "[dim]Wired Memory[/dim] —\n"
                "[dim]Compressed[/dim]    —"
            )
        else:
            summary = (
                f"[dim]Physical Memory[/dim]  {format_bytes(snap.physical)}\n"
                f"[dim]Memory Used[/dim]      {format_bytes(snap.used)}\n"
                f"[dim]Cached Files[/dim]     {format_bytes(snap.cached)}\n"
                f"[dim]Swap Used[/dim]        {format_bytes(snap.swap_used)}"
            )
            detail = (
                f"[dim]App Memory[/dim]   {format_bytes(snap.app)}\n"
                f"[dim]Wired Memory[/dim] {format_bytes(snap.wired)}\n"
                f"[dim]Compressed[/dim]    {format_bytes(snap.compressed)}"
            )
        self.query_one("#mem-summary", Static).update(summary)
        self.query_one("#mem-detail", Static).update(detail)

    def _draw_pressure(self) -> None:
        if len(self._pressure) < 2:
            return
        y = list(self._pressure)
        avg = sum(y) / len(y)
        color = "green" if avg < 40 else "yellow" if avg < 70 else "red"
        plot = self.query_one("#mem-pressure-plot", BraillePlot)
        plot.set_series([Series(self._pressure, color)])


class SysMetricsRow(Widget):
    """Compact Activity Monitor–style CPU + memory strip."""

    def compose(self) -> ComposeResult:
        if sys.platform != "darwin":
            yield Static(
                "[dim]System metrics available on macOS only[/dim]",
                id="sysmetrics-unavailable",
            )
            return
        yield CpuMetricsPane(id="cpu-metrics")
        yield MemMetricsPane(id="mem-metrics")
