from __future__ import annotations
import asyncio
import json
import subprocess

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, RichLog
from textual.screen import ModalScreen

from netmon.config import HEROKU_POLL_INTERVAL


class HerokuLogsModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, name: str) -> None:
        super().__init__()
        self._app_name = name

    def compose(self) -> ComposeResult:
        yield RichLog(id="heroku-logs-output", markup=False, highlight=False)

    def on_mount(self) -> None:
        self.border_title = f"logs: {self._app_name}"
        self._load_logs()

    def _load_logs(self) -> None:
        log = self.query_one(RichLog)
        try:
            result = subprocess.run(
                ["heroku", "logs", "--app", self._app_name, "--num", "100"],
                capture_output=True, text=True, timeout=15,
            )
            for line in (result.stdout + result.stderr).splitlines():
                log.write(line)
        except Exception as e:
            log.write(f"Error: {e}")


class HerokuPane(Widget):
    BORDER_TITLE = "HEROKU  [dim](r restart  s scale-0  l logs  o open)[/dim]"

    BINDINGS = [
        ("r", "restart_selected", "Restart"),
        ("s", "scale_zero",       "Scale→0"),
        ("l", "show_logs",        "Logs"),
        ("o", "open_browser",     "Open"),
    ]

    class HerokuSelected(Message):
        def __init__(self, name: str, web_url: str) -> None:
            super().__init__()
            self.name    = name
            self.web_url = web_url

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._apps: list[dict] = []
        self._available  = True
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield DataTable(id="heroku-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("Team",   key="team",   width=10)
        t.add_column("App",    key="name",   width=22)
        t.add_column("Dynos",  key="dynos",  width=14)
        t.add_column("Updated",key="updated",width=10)
        self.set_interval(HEROKU_POLL_INTERVAL, self._poll)
        self.call_after_refresh(self._poll)

    async def _poll(self) -> None:
        apps = await asyncio.to_thread(_fetch_apps)
        if apps is None:
            self._available = False
            return
        self._available = True
        self._apps = apps
        self._refresh_table()

    def _refresh_table(self) -> None:
        self._refreshing = True
        t = self.query_one(DataTable)
        t.clear()

        # Group by team, personal apps first then alphabetical teams
        by_team: dict[str, list[dict]] = {}
        for app in self._apps:
            team = app.get("_team", "personal")
            by_team.setdefault(team, []).append(app)

        team_colors = ["cyan", "magenta", "yellow", "blue", "green", "red"]
        team_list   = sorted(by_team.keys(), key=lambda t: ("" if t == "personal" else t))

        for ti, team in enumerate(team_list):
            tcolor = team_colors[ti % len(team_colors)]
            for app in by_team[team]:
                name    = app.get("name", "?")
                updated = _short_date(app.get("updated_at", ""))
                dynos   = app.get("_dynos", "—")
                dcolor  = "green" if "up" in dynos.lower() else ("red" if dynos != "—" else "dim")
                t.add_row(
                    f"[{tcolor}]{team}[/{tcolor}]",
                    name,
                    f"[{dcolor}]{dynos}[/{dcolor}]",
                    updated,
                    key=name,
                )
        self.call_after_refresh(self._clear_refreshing)

    def _clear_refreshing(self) -> None:
        self._refreshing = False

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._refreshing and event.row_key:
            name = str(event.row_key.value)
            app  = next((a for a in self._apps if a.get("name") == name), {})
            self.post_message(HerokuPane.HerokuSelected(name, app.get("web_url", "")))

    def _selected_name(self) -> str | None:
        t = self.query_one(DataTable)
        try:
            rows = list(t.ordered_rows)
            if t.cursor_row < len(rows):
                return str(rows[t.cursor_row].key.value)
        except Exception:
            pass
        return None

    def action_restart_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            subprocess.run(["heroku", "ps:restart", "--app", name], timeout=20)
            self.app.notify(f"Restarted {name}", severity="information")
        except Exception as e:
            self.app.notify(f"Restart failed: {e}", severity="error")

    def action_scale_zero(self) -> None:
        name = self._selected_name()
        if not name:
            return
        from netmon.panes.docker_pane import _ConfirmModal
        self.app.push_screen(
            _ConfirmModal(f"Scale {name} web→0?", "This will take the app offline."),
            lambda ok: self._do_scale_zero(name) if ok else None,
        )

    def _do_scale_zero(self, name: str) -> None:
        try:
            subprocess.run(["heroku", "ps:scale", "web=0", "--app", name], timeout=20)
            self.app.notify(f"Scaled {name} web→0", severity="warning")
        except Exception as e:
            self.app.notify(f"Scale failed: {e}", severity="error")

    def action_show_logs(self) -> None:
        name = self._selected_name()
        if name:
            self.app.push_screen(HerokuLogsModal(name))

    def action_open_browser(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            subprocess.run(["heroku", "open", "--app", name], timeout=5)
        except Exception as e:
            self.app.notify(f"Open failed: {e}", severity="error")


# ── data fetching ─────────────────────────────────────────────────────────────

def _fetch_apps() -> list[dict] | None:
    """Fetch all Heroku apps across personal account and all orgs/teams."""
    import concurrent.futures

    all_apps: list[dict] = []

    # Personal apps
    try:
        r = subprocess.run(
            ["heroku", "apps", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        personal = json.loads(r.stdout) if r.stdout.strip() else []
        for a in personal:
            a["_team"] = "personal"
        all_apps.extend(personal)
    except Exception:
        pass

    # Orgs / teams
    try:
        r = subprocess.run(
            ["heroku", "orgs", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        orgs: list[dict] = json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        orgs = []

    for org in orgs:
        team_name = org.get("name", "")
        if not team_name:
            continue
        try:
            r = subprocess.run(
                ["heroku", "apps", "--team", team_name, "--json"],
                capture_output=True, text=True, timeout=10,
            )
            team_apps: list[dict] = json.loads(r.stdout) if r.stdout.strip() else []
            for a in team_apps:
                a["_team"] = team_name
            all_apps.extend(team_apps)
        except Exception:
            pass

    if not all_apps:
        return []

    # Fetch dyno status in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_dynos, a["name"]): a for a in all_apps}
        for future, app in futures.items():
            try:
                app["_dynos"] = future.result(timeout=10)
            except Exception:
                app["_dynos"] = "—"

    # Sort within each team: running first, then alphabetical
    all_apps.sort(key=lambda a: (
        a.get("_team", ""),
        "up" not in a.get("_dynos", "").lower(),
        a.get("name", ""),
    ))
    return all_apps


def _fetch_dynos(app_name: str) -> str:
    """Return a short dyno status string, e.g. 'web:1 up'."""
    try:
        r = subprocess.run(
            ["heroku", "ps", "--app", app_name, "--json"],
            capture_output=True, text=True, timeout=8,
        )
        dynos: list[dict] = json.loads(r.stdout)
        if not dynos:
            return "no dynos"
        parts = []
        seen: dict[str, list[str]] = {}
        for d in dynos:
            t     = d.get("type", "?")
            state = d.get("state", "?")
            seen.setdefault(t, []).append(state)
        for dtype, states in seen.items():
            dominant = max(set(states), key=states.count)
            parts.append(f"{dtype}:{len(states)} {dominant}")
        return "  ".join(parts)
    except Exception:
        return "—"


# ── helpers ───────────────────────────────────────────────────────────────────

def _short_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        from datetime import datetime, timezone
        dt  = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        secs = (now - dt).total_seconds()
        if secs < 3600:
            return f"{int(secs // 60)}m ago"
        if secs < 86400:
            return f"{int(secs // 3600)}h ago"
        return f"{int(secs // 86400)}d ago"
    except Exception:
        return iso[:10]
