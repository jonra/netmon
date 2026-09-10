from __future__ import annotations
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

PROJECTS_DIR = Path.home() / ".claude" / "projects"
_ACTIVE_THRESHOLD = 600    # seconds — session file mtime for "active"
_RECENT_THRESHOLD = 3600   # 1 hour
_MAX_AGE          = 3600   # 1 hour — max age to show (active-process sessions always shown)
_POLL_INTERVAL    = 5.0


_SPARK_BUCKETS  = 12   # number of bars in mini sparkline
_SPARK_MIN      = 5    # minutes per bucket  → 1 h window
_SPARK_CHARS    = " ▁▂▃▄▅▆▇█"


@dataclass
class SessionInfo:
    session_id: str
    project:    str
    project_path: str
    slug:       str
    model:      str
    state:        str   # active | recent | idle
    file_active:  bool  # True if file mtime is recent (not just process-matched)
    tokens:     int
    tool_calls: int
    last_active: datetime | None
    git_branch: str = ""
    cwd:        str = ""
    permission_mode: str = ""
    spark: list[int] | None = None   # tool-call counts per bucket, newest last


class SessionsPane(Widget):
    BORDER_TITLE = "CLAUDE SESSIONS"

    class SessionSelected(Message):
        def __init__(self, session: SessionInfo) -> None:
            super().__init__()
            self.session = session

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: dict[str, SessionInfo] = {}
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("State",   key="state",   width=8)
        t.add_column("Project", key="project", width=22)
        t.add_column("Branch",  key="branch",  width=14)
        t.add_column("Model",   key="model",   width=14)
        t.add_column("Tokens",  key="tokens",  width=8)
        t.add_column("Tools",   key="tools",   width=6)
        t.add_column("Activity",key="spark",   width=14)
        t.add_column("Age",     key="age",     width=10)
        t.add_column("Session", key="session", width=10)
        self.set_interval(_POLL_INTERVAL, self._poll)

    async def _poll(self) -> None:
        sessions = await asyncio.to_thread(_scan_sessions)
        self._sessions = {s.session_id: s for s in sessions}
        self._refresh_table(sessions)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._refreshing and event.row_key:
            s = self._sessions.get(str(event.row_key.value))
            if s:
                self.post_message(SessionsPane.SessionSelected(s))

    def _refresh_table(self, sessions: list[SessionInfo]) -> None:
        self._refreshing = True
        t = self.query_one(DataTable)
        t.clear()
        for s in sessions:
            color = "green" if s.state == "active" else ("yellow" if s.state == "recent" else "dim")
            if s.state == "active" and not s.file_active:
                age_str = "[dim]live[/dim]"
            else:
                age_str = _time_ago(s.last_active)

            t.add_row(
                f"[{color}]{s.state}[/{color}]",
                s.project[-22:],
                s.git_branch[:14] or "—",
                s.model or "—",
                _fmt_tokens(s.tokens),
                str(s.tool_calls) if s.tool_calls else "—",
                _render_spark(s.spark, s.state),
                age_str,
                s.session_id[:8],
                key=s.session_id,
            )
        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False


# ── scanning ──────────────────────────────────────────────────────────────────

def _scan_sessions() -> list[SessionInfo]:
    if not PROJECTS_DIR.exists():
        return []

    active_cwds = _get_claude_cwds()
    active_dirs = _match_active_dirs(active_cwds)  # set of project dir names
    now = datetime.now(timezone.utc).timestamp()
    sessions: list[SessionInfo] = []

    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue

        proj_active = proj_dir.name in active_dirs
        project_path = _decode_dir(proj_dir.name)
        project_short = Path(project_path).name or project_path

        # Collect all qualifying JSONL files with their mtimes
        jsonl_files: list[tuple[Path, float]] = []
        for jsonl in proj_dir.glob("*.jsonl"):
            if len(jsonl.stem) < 10:
                continue
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            age = now - mtime
            if not proj_active and age > _MAX_AGE:
                continue
            jsonl_files.append((jsonl, mtime))

        if not jsonl_files:
            continue

        # Most recent mtime in this project dir — used to promote to "active"
        newest_mtime = max(m for _, m in jsonl_files)

        for jsonl, mtime in jsonl_files:
            age = now - mtime
            is_newest = mtime == newest_mtime

            file_recently_modified = age < _ACTIVE_THRESHOLD

            if proj_active and is_newest:
                state = "active"
            elif proj_active and age < _RECENT_THRESHOLD:
                state = "recent"
            elif age < _ACTIVE_THRESHOLD:
                state = "recent"
            elif age < _RECENT_THRESHOLD:
                state = "recent"
            else:
                state = "idle"

            info = _parse_jsonl(jsonl)
            sessions.append(SessionInfo(
                session_id      = jsonl.stem,
                project         = project_short,
                project_path    = project_path,
                slug            = info.get("slug", ""),
                model           = _short_model(info.get("model", "")),
                state           = state,
                file_active     = file_recently_modified,
                tokens          = info.get("tokens", 0),
                tool_calls      = info.get("tool_calls", 0),
                last_active     = datetime.fromtimestamp(mtime, tz=timezone.utc),
                git_branch      = info.get("git_branch", ""),
                cwd             = info.get("cwd", ""),
                permission_mode = info.get("permission_mode", ""),
                spark           = info.get("spark"),
            ))

    sessions.sort(key=lambda s: (
        {"active": 0, "recent": 1, "idle": 2}[s.state],
        -(s.last_active.timestamp() if s.last_active else 0),
    ))
    return sessions


def _match_active_dirs(cwds: list[str]) -> set[str]:
    """Return project dir names that match any running claude process CWD.

    Handles the common case where the filesystem uses underscores (my_project)
    but the Claude project dir was created with hyphens (my-project), by
    normalising both sides before comparing.
    """
    if not cwds or not PROJECTS_DIR.exists():
        return set()

    active: set[str] = set()
    proj_dirs = [d for d in PROJECTS_DIR.iterdir() if d.is_dir()]

    for cwd in cwds:
        encoded       = _encode_path(cwd)           # -Users-alice-projects-my_project
        encoded_norm  = encoded.replace("_", "-")    # -Users-alice-projects-my-project

        for proj_dir in proj_dirs:
            name      = proj_dir.name
            name_norm = name.replace("_", "-")

            # Exact match, normalised match, or CWD is inside the project dir
            if (name == encoded
                    or name_norm == encoded_norm
                    or encoded.startswith(name + "-")
                    or encoded_norm.startswith(name_norm + "-")):
                active.add(proj_dir.name)

    return active


def _parse_jsonl(path: Path) -> dict:
    """Read session JSONL and extract key fields + sparkline timestamps.

    Streams the full file to count tokens accurately (usage is per-turn),
    but only fully parses assistant lines for speed on large files.
    Metadata and sparkline data come from head/tail slices.
    """
    result: dict = {
        "slug": "", "model": "", "cwd": "", "git_branch": "",
        "permission_mode": "", "tokens": 0, "tool_calls": 0,
        "spark": [],
    }
    now = datetime.now(timezone.utc).timestamp()
    spark_window = _SPARK_BUCKETS * _SPARK_MIN * 60
    spark_counts = [0] * _SPARK_BUCKETS

    # ── Pass 1: metadata + sparkline from head + tail only ────────────────
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            tail = f.read().decode("utf-8", errors="replace")
        with open(path, "rb") as f:
            head = f.read(2048).decode("utf-8", errors="replace")
    except OSError:
        return result

    for raw in (head + "\n" + tail).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("slug"):
            result["slug"] = entry["slug"]
        if entry.get("cwd"):
            result["cwd"] = entry["cwd"]
        if entry.get("gitBranch"):
            result["git_branch"] = entry["gitBranch"]
        if entry.get("permissionMode"):
            result["permission_mode"] = entry["permissionMode"]

        msg = entry.get("message", {})
        if entry.get("type") == "assistant" and msg:
            model = msg.get("model", "")
            if model and not model.startswith("claude-3-5"):
                result["model"] = model
            elif model and not result["model"]:
                result["model"] = model

            ts_str = entry.get("timestamp", "")
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            ).timestamp()
                            age = now - ts
                            if 0 <= age <= spark_window:
                                bucket = int(age / (_SPARK_MIN * 60))
                                if 0 <= bucket < _SPARK_BUCKETS:
                                    spark_counts[bucket] += 1
                        except ValueError:
                            pass

    result["spark"] = list(reversed(spark_counts))

    # ── Pass 2: stream full file for accurate token + tool_call counts ────
    # Only JSON-parse lines containing "assistant" to keep large files fast.
    input_tokens = output_tokens = 0
    tool_calls = 0
    try:
        with open(path, "rb") as f:
            for raw_bytes in f:
                if b'"assistant"' not in raw_bytes:
                    continue
                try:
                    entry = json.loads(raw_bytes)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                msg = entry.get("message", {})
                usage = msg.get("usage", {})
                input_tokens  += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls += 1
    except OSError:
        pass

    result["tokens"] = input_tokens + output_tokens
    result["tool_calls"] = tool_calls
    return result


# ── process detection ─────────────────────────────────────────────────────────

def _get_claude_cwds() -> list[str]:
    """Return working directories of running claude processes."""
    cwds: list[str] = []
    try:
        import subprocess
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in ps.stdout.splitlines():
            if "claude" not in line or "Claude.app" in line or "grep" in line:
                continue
            if any(x in line for x in ("Helper", "GPU", "Renderer")):
                continue
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            pid = parts[1]
            cmd = parts[10]
            if "/claude" not in cmd and not cmd.strip().startswith("claude"):
                continue
            try:
                lsof = subprocess.run(
                    ["lsof", "-p", pid], capture_output=True, text=True, timeout=3
                )
                for lline in lsof.stdout.splitlines():
                    if "cwd" in lline:
                        m = lline.rsplit(None, 1)
                        if m:
                            cwds.append(m[-1])
                        break
            except Exception:
                pass
    except Exception:
        pass
    return cwds


# ── helpers ───────────────────────────────────────────────────────────────────

def _decode_dir(name: str) -> str:
    naive = "/" + name.lstrip("-").replace("-", "/")
    if os.path.exists(naive):
        return naive
    parts = name.lstrip("-").split("-")
    for i in range(len(parts) - 1, 0, -1):
        prefix = "/" + "/".join(parts[:i])
        suffix = "-".join(parts[i:])
        candidate = f"{prefix}/{suffix}"
        if os.path.exists(candidate):
            return candidate
    return naive


def _encode_path(path: str) -> str:
    return path.replace("/", "-")


def _short_model(model: str) -> str:
    model = model.replace("claude-", "").replace("-20", " ")
    # "sonnet-4-6 25" → too long; keep first two segments
    parts = model.split("-")
    return "-".join(parts[:3])[:14] if parts else model


def _render_spark(counts: list[int] | None, state: str) -> str:
    """Render an 80s-equalizer style sparkline using Unicode block chars."""
    if not counts or not any(counts):
        if state == "active":
            return "[dim]────────────[/dim]"
        return ""

    peak = max(counts)
    # Pick color based on state
    color = "bright_green" if state == "active" else ("yellow" if state == "recent" else "dim")

    bars = []
    for v in counts:
        if peak == 0:
            level = 0
        else:
            level = round(v / peak * 8)
        bars.append(_SPARK_CHARS[level])

    return f"[{color}]{''.join(bars)}[/{color}]"


def _fmt_tokens(n: int) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}k"
    return str(n)


def _time_ago(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"
