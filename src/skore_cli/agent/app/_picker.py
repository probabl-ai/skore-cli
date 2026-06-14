"""The single-select picker backing interactive ``skore agent init``."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Label, RadioButton

from skore_cli.skills.app._widgets import AutoRadioSet

_INTRO = (
    "Choose the agent harness to configure.\n"
    "Detected harnesses are marked and pre-selected.\n"
    "[reverse] ↑/↓ [/] choose  [reverse] Enter [/] confirm"
)


class HarnessPicker(App[str | None]):
    """Pick a single harness name from a radio set."""

    CSS = """
    Screen {
        align: center middle;
    }
    #picker {
        width: 90%;
        height: 90%;
    }
    .picker-intro {
        margin: 1 1;
        color: $text-muted;
    }
    AutoRadioSet {
        margin: 1 1;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        harnesses: list[tuple[str, str, bool]],
        *,
        preselect: int = 0,
    ) -> None:
        super().__init__()
        self._harnesses = harnesses
        self._preselect = preselect
        self.result: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="picker"):
            yield Label(_INTRO, classes="picker-intro")
            with AutoRadioSet(id="harnesses"):
                for index, (_, label, detected) in enumerate(self._harnesses):
                    text = f"{label}  (detected)" if detected else label
                    yield RadioButton(text, value=index == self._preselect)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#harnesses", AutoRadioSet).select_index(self._preselect)

    def action_confirm(self) -> None:
        index = self.query_one("#harnesses", AutoRadioSet).pressed_index
        if index < 0:
            self.notify("Select a harness.", severity="warning")
            return
        self.result = self._harnesses[index][0]
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()


_WORKSPACE_INTRO = (
    "Choose the Skore Hub workspace to attach the agent to.\n"
    "The agent uses this workspace's LLM provider configuration.\n"
    "[reverse] ↑/↓ [/] choose  [reverse] Enter [/] confirm"
)


class WorkspacePicker(App[str | None]):
    """Pick a single workspace public id from a radio set."""

    CSS = """
    Screen {
        align: center middle;
    }
    #picker {
        width: 90%;
        height: 90%;
    }
    .picker-intro {
        margin: 1 1;
        color: $text-muted;
    }
    AutoRadioSet {
        margin: 1 1;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        workspaces: list[tuple[str, str]],
        *,
        preselect: int = 0,
    ) -> None:
        super().__init__()
        self._workspaces = workspaces
        self._preselect = preselect
        self.result: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="picker"):
            yield Label(_WORKSPACE_INTRO, classes="picker-intro")
            with AutoRadioSet(id="workspaces"):
                for index, (public_id, name) in enumerate(self._workspaces):
                    text = f"{name}  ({public_id})" if name != public_id else public_id
                    yield RadioButton(text, value=index == self._preselect)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspaces", AutoRadioSet).select_index(self._preselect)

    def action_confirm(self) -> None:
        index = self.query_one("#workspaces", AutoRadioSet).pressed_index
        if index < 0:
            self.notify("Select a workspace.", severity="warning")
            return
        self.result = self._workspaces[index][0]
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()
