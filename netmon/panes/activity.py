from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual_plotext import PlotextPlot

from netmon.panes.sessions import PROJECTS_DIR, _scan_sessions, _get_claude_cwds, _match_active_dirs

_POLL_INTERVAL = 10.0
_BUCKETS       = 24          # number of bars / points
_BUCKET_MIN    = 5           # minutes per bucket  → 2 h window
_COLORS        = [
    "green", "cyan", "yellow", "magenta",
    "blue", "red", "white", "orange",
]


class ActivityPane(Widget):
    BORDER_TITLE = "AGENT ACTIVITY  [dim](tool calls · 5-min buckets · 2 h)[/dim]"

    def compose(self) -> ComposeResult:
        yield PlotextPlot()

    def on_mount(self) -> None:
        self._init_plot()
        self._refresh()
        self.set_interval(_POLL_INTERVAL, self._refresh)

    def _init_plot(self) -> None:
        plt = self.query_one(PlotextPlot).plt
        plt.date_form("H:M")
        plt.title("")
        plt.theme("dark")

    @work(exclusive=True, group="activity-plot")
    async def _refresh(self) -> None:
        data = await asyncio.to_thread(_collect_activity)
        self._draw(data)

    def _draw(self, data: dict[str, list[int]]) -> None:
        widget = self.query_one(PlotextPlot)
        plt = widget.plt
        plt.clear_figure()
        plt.theme("dark")
        plt.xlabel("")
        plt.ylabel("tool calls")

        now = datetime.now(timezone.utc).timestamp()
        # X labels: times for each bucket (oldest → newest)
        x_labels = []
        for i in range(_BUCKETS):
            bucket_ts = now - (_BUCKETS - 1 - i) * _BUCKET_MIN * 60
            x_labels.append(datetime.fromtimestamp(bucket_ts).strftime("%H:%M"))

        x = list(range(_BUCKETS))

        if not data:
            plt.plot(x, [0] * _BUCKETS, color="dark", label="no active sessions")
        else:
            for idx, (label, counts) in enumerate(data.items()):
                color = _COLORS[idx % len(_COLORS)]
                plt.plot(x, counts, color=color, label=label[:18])

        # Sparse x-tick labels (every 4 buckets = 20 min)
        tick_pos   = list(range(0, _BUCKETS, 4))
        tick_labs  = [x_labels[i] for i in tick_pos]
        plt.xticks(tick_pos, tick_labs)

        widget.refresh()


# ── data collection ───────────────────────────────────────────────────────────

def _collect_activity() -> dict[str, list[int]]:
    """Return {project_label: [count_per_bucket]} for active/recent sessions."""
    cwds        = _get_claude_cwds()
    active_dirs = _match_active_dirs(cwds)
    now         = datetime.now(timezone.utc).timestamp()
    window_secs = _BUCKETS * _BUCKET_MIN * 60
    result: dict[str, list[int]] = {}

    if not PROJECTS_DIR.exists():
        return result

    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue

        proj_active = proj_dir.name in active_dirs
        label = Path(proj_dir.name.lstrip("-").replace("-", "/")).name or proj_dir.name

        # For non-active dirs only scan if recently modified
        if not proj_active:
            continue  # only plot active sessions for clarity

        # Find the most recent JSONL (the active session)
        jsonl_files = sorted(
            proj_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if not jsonl_files:
            continue

        counts = _bucket_tool_calls(jsonl_files[0], now, window_secs)
        if any(counts):
            result[label] = counts

    return result


def _bucket_tool_calls(path: Path, now: float, window_secs: float) -> list[int]:
    """Return list of tool-call counts per time bucket (oldest → newest)."""
    counts = [0] * _BUCKETS
    bucket_secs = _BUCKET_MIN * 60

    try:
        # Read the whole file — large sessions can have rich history
        content = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return counts

    for raw in content.splitlines():
        if '"tool_use"' not in raw:  # fast pre-filter
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue

        ts_str = entry.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue

        age = now - ts
        if age < 0 or age > window_secs:
            continue

        bucket = int(age / bucket_secs)
        if 0 <= bucket < _BUCKETS:
            # bucket 0 = most recent; reverse so oldest is index 0 in output
            counts[_BUCKETS - 1 - bucket] += 1

    return counts
