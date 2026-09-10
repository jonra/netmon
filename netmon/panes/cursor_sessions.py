from __future__ import annotations
import asyncio
import json
import sqlite3
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

_WORKSPACE_STORAGE = Path.home() / "Library/Application Support/Cursor/User/workspaceStorage"
_POLL_INTERVAL = 30.0
_MAX_AGE_DAYS = 14


@dataclass
class CursorSession:
    composer_id: str
    project: str
    project_path: str
    name: str
    branch: str
    context_pct: float
    lines_added: int
    lines_removed: int
    files_changed: int
    last_updated: datetime | None
    created_at: datetime | None
    is_archived: bool
    mode: str  # "agent" or "chat"


class CursorSessionsPane(Widget):
    BORDER_TITLE = "CURSOR SESSIONS"

    class SessionSelected(Message):
        def __init__(self, session: CursorSession) -> None:
            super().__init__()
            self.session = session

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: dict[str, CursorSession] = {}
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="cursor-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("Project",  key="project",  width=20)
        t.add_column("Session",  key="name",     width=28)
        t.add_column("Branch",   key="branch",   width=14)
        t.add_column("Mode",     key="mode",     width=7)
        t.add_column("Ctx%",     key="ctx",      width=5)
        t.add_column("+Lines",   key="added",    width=7)
        t.add_column("Files",    key="files",    width=5)
        t.add_column("Age",      key="age",      width=10)
        self.set_interval(_POLL_INTERVAL, self._poll)
        self.call_after_refresh(self._poll)

    async def _poll(self) -> None:
        sessions = await asyncio.to_thread(_scan_cursor_sessions)
        self._sessions = {s.composer_id: s for s in sessions}
        self._refresh_table(sessions)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._refreshing and event.row_key:
            s = self._sessions.get(str(event.row_key.value))
            if s:
                self.post_message(CursorSessionsPane.SessionSelected(s))

    def _refresh_table(self, sessions: list[CursorSession]) -> None:
        self._refreshing = True
        t = self.query_one(DataTable)
        t.clear()
        for s in sessions:
            if s.is_archived:
                continue
            age = _time_ago(s.last_updated)
            ctx_color = "red" if s.context_pct > 80 else ("yellow" if s.context_pct > 50 else "green")
            mode_color = "cyan" if s.mode == "agent" else "dim"
            t.add_row(
                s.project[-20:],
                s.name[:28],
                s.branch[:14] or "—",
                f"[{mode_color}]{s.mode}[/{mode_color}]",
                f"[{ctx_color}]{s.context_pct:.0f}[/{ctx_color}]",
                f"[green]+{s.lines_added}[/green]" if s.lines_added else "—",
                str(s.files_changed) if s.files_changed else "—",
                age,
                key=s.composer_id,
            )
        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False


# ── scanning ──────────────────────────────────────────────────────────────────

def _scan_cursor_sessions() -> list[CursorSession]:
    if not _WORKSPACE_STORAGE.exists():
        return []

    sessions: list[CursorSession] = []
    cutoff = datetime.now(timezone.utc).timestamp() - (_MAX_AGE_DAYS * 86400)

    for ws_dir in _WORKSPACE_STORAGE.iterdir():
        ws_json = ws_dir / "workspace.json"
        db_path = ws_dir / "state.vscdb"
        if not ws_json.exists() or not db_path.exists():
            continue

        try:
            folder_uri = json.loads(ws_json.read_text()).get("folder", "")
            project_path = urllib.parse.unquote(folder_uri.removeprefix("file://"))
            project = Path(project_path).name
        except Exception:
            continue

        try:
            composers = _read_composers(db_path)
        except Exception:
            continue

        for c in composers:
            last_ms = c.get("lastUpdatedAt", 0)
            last_dt = datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc) if last_ms else None
            if last_dt and last_dt.timestamp() < cutoff:
                continue

            created_ms = c.get("createdAt", 0)
            created_dt = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc) if created_ms else None

            mode = c.get("unifiedMode", "chat")
            if mode == "normal":
                mode = "agent"

            sessions.append(CursorSession(
                composer_id=c.get("composerId", ""),
                project=project,
                project_path=project_path,
                name=c.get("name", "") or c.get("subtitle", "") or "untitled",
                branch=c.get("createdOnBranch", "") or "",
                context_pct=float(c.get("contextUsagePercent", 0) or 0),
                lines_added=int(c.get("totalLinesAdded", 0) or 0),
                lines_removed=int(c.get("totalLinesRemoved", 0) or 0),
                files_changed=int(c.get("filesChangedCount", 0) or 0),
                last_updated=last_dt,
                created_at=created_dt,
                is_archived=bool(c.get("isArchived", False)),
                mode=mode,
            ))

    sessions.sort(key=lambda s: (s.last_updated or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return sessions


def _read_composers(db_path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    try:
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key='composer.composerData'"
        ).fetchone()
        if not row:
            return []
        data = json.loads(row[0])
        return data.get("allComposers", [])
    finally:
        con.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _time_ago(dt: datetime | None) -> str:
    if not dt:
        return "—"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"
