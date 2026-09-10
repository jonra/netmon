from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, TabbedContent, TabPane

from netmon.panes.actions import ActionsBar, PresetSelected
from netmon.panes.agents import AgentsPane
from netmon.panes.cursor_sessions import CursorSessionsPane
from netmon.panes.detail import DetailPane
from netmon.panes.docker_pane import DockerPane
from netmon.panes.heroku_pane import HerokuPane
from netmon.panes.ports import PortsPane
from netmon.panes.sessions import SessionsPane
from netmon.panes.sysmetrics import SysMetricsRow


class SessionsRow(Widget):
    """Bottom row holding Claude + Cursor session tabs."""

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Claude", id="tab-claude"):
                yield SessionsPane(id="claude-sessions")
            with TabPane("Cursor", id="tab-cursor"):
                yield CursorSessionsPane(id="cursor-sessions")


class NetmonApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "netmon"
    SUB_TITLE = "network & agent monitor"

    BINDINGS = [
        Binding("q",             "quit",                   "Quit"),
        Binding("space",         "toggle_pause",           "Pause/Resume"),
        Binding("1",             "focus_pane('ports')",    "Ports",    show=False),
        Binding("2",             "focus_pane('detail')",   "Details",  show=False),
        Binding("3",             "focus_pane('docker')",   "Docker",   show=False),
        Binding("4",             "focus_pane('agents')",   "Agents",   show=False),
        Binding("5",             "focus_pane('sessions')", "Sessions", show=False),
        Binding("question_mark", "show_help",              "Help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ActionsBar(id="actions-bar")
        yield SysMetricsRow(id="sys-metrics")
        yield Vertical(
            Horizontal(
                PortsPane(id="ports"),
                DetailPane(id="detail"),
                id="top-row",
            ),
            Horizontal(
                DockerPane(id="docker"),
                HerokuPane(id="heroku"),
                AgentsPane(id="agents"),
                id="mid-row",
            ),
            SessionsRow(id="sessions"),
            id="main-layout",
        )
        yield Footer()

    # --- message handlers ------------------------------------------------

    def on_ports_pane_port_selected(self, event: PortsPane.PortSelected) -> None:
        self.query_one(DetailPane).show_port(event.port, event.pid, event.cmd, event.name)

    def on_docker_pane_docker_selected(self, event: DockerPane.DockerSelected) -> None:
        self.query_one(DetailPane).show_docker(event.name)

    def on_heroku_pane_heroku_selected(self, event: HerokuPane.HerokuSelected) -> None:
        self.query_one(DetailPane).show_heroku(event.name, event.web_url)

    def on_agents_pane_agent_selected(self, event: AgentsPane.AgentSelected) -> None:
        self.query_one(DetailPane).show_agent(event.name, event.pid)

    def on_sessions_pane_session_selected(self, event: SessionsPane.SessionSelected) -> None:
        self.query_one(DetailPane).show_session(event.session)

    def on_cursor_sessions_pane_session_selected(self, event: CursorSessionsPane.SessionSelected) -> None:
        self.query_one(DetailPane).show_cursor_session(event.session)

    def on_preset_selected(self, event: PresetSelected) -> None:
        self.query_one(PortsPane).set_preset(event.preset)

    # --- actions ---------------------------------------------------------

    def action_toggle_pause(self) -> None:
        paused = self.query_one(PortsPane).toggle_pause()
        self.query_one(ActionsBar).set_paused(paused)

    def action_focus_pane(self, pane: str) -> None:
        pane_map = {
            "ports":    "#ports",
            "detail":   "#detail",
            "docker":   "#docker",
            "agents":   "#agents",
            "sessions": "#sessions",
        }
        if selector := pane_map.get(pane):
            self.query_one(selector).focus()

    def action_show_help(self) -> None:
        self.notify(
            "1-5 jump panes  ·  Space pause/resume  ·  k kill port  ·  / filter  ·  "
            "r restart / l logs docker  ·  q quit  ·  select any row → details pane",
            title="netmon key bindings",
            timeout=8,
        )
