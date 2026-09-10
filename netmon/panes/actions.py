from __future__ import annotations
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, Static


class PresetSelected(Message):
    def __init__(self, preset: str) -> None:
        super().__init__()
        self.preset = preset


class ActionsBar(Widget):
    BORDER_TITLE = ""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_preset = "All"
        self._paused = False

    def compose(self) -> ComposeResult:
        yield Label("Preset:", id="preset-label")
        yield Button("4xx",     id="btn-4xx",     variant="default")
        yield Button("8xx",     id="btn-8xx",     variant="default")
        yield Button("All",     id="btn-all",     variant="success")
        yield Static("", id="spacer")
        yield Static("⏵ live", id="status-label")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        presets = {
            "btn-4xx": "4xx",
            "btn-8xx": "8xx",
            "btn-all": "All",
        }
        btn_id = event.button.id or ""
        if btn_id not in presets:
            return
        self._active_preset = presets[btn_id]
        self._update_buttons()
        self.post_message(PresetSelected(self._active_preset))

    def _update_buttons(self) -> None:
        mapping = {
            "4xx": "btn-4xx",
            "8xx": "btn-8xx",
            "All": "btn-all",
        }
        for preset, btn_id in mapping.items():
            btn = self.query_one(f"#{btn_id}", Button)
            btn.variant = "success" if preset == self._active_preset else "default"

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        label = self.query_one("#status-label", Static)
        label.update("⏸ [yellow]paused[/yellow]" if paused else "⏵ [green]live[/green]")
