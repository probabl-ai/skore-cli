"""Textual apps backing the interactive ``skore hub api-key`` commands.

``ApiKeyForm`` is a single-screen form (name, workspace, permissions, validity)
mirroring the hub UI's create modal; ``IdPicker`` is a generic single-select
picker over ``(id, label)`` rows. Both follow the package convention: set
``self.result`` then ``exit()``; the caller reads ``app.result`` after
``app.run()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    SelectionList,
)
from textual.widgets.selection_list import Selection

from skore_cli.skills.app._widgets import AutoRadioSet

# (value, label) validity choices, mirroring the hub UI (default: 3 months).
VALIDITY_CHOICES: list[tuple[str, str]] = [
    ("1", "1 month"),
    ("3", "3 months"),
    ("6", "6 months"),
    ("never", "Never"),
]
_DEFAULT_VALIDITY_INDEX = 1

_INTRO = (
    "Create a workspace-scoped API key.\n"
    "Pick the workspace, the permissions to grant, and a validity.\n"
    "[reverse] tab [/] next field  [reverse] ↑/↓ space [/] choose  "
    "[reverse] enter [/] create  [reverse] esc [/] cancel"
)


@dataclass(frozen=True)
class ApiKeyFormResult:
    """The choices captured by :class:`ApiKeyForm`."""

    name: str
    workspace_id: int
    workspace_public_id: str
    permissions: list[str]
    validity: str


class ApiKeyForm(App[ApiKeyFormResult | None]):
    """Interactive form to mint a workspace-scoped API key."""

    CSS = """
    Screen {
        align: center middle;
    }
    #form {
        width: 90%;
        height: 90%;
    }
    .form-intro {
        margin: 1 1;
        color: $text-muted;
    }
    .field-label {
        margin: 1 1 0 1;
        text-style: bold;
    }
    #name {
        margin: 0 1;
        width: 100%;
    }
    AutoRadioSet {
        margin: 0 1;
        width: 100%;
    }
    #permissions {
        margin: 0 1;
        height: auto;
        max-height: 9;
        border: round $surface-lighten-2;
    }
    #permissions:focus {
        border: thick $accent;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Create", priority=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Previous", show=False),
    ]

    def __init__(
        self,
        workspaces: list[tuple[int, str]],
        grantable: dict[int, list[str]],
        *,
        name: str = "",
        permissions: list[str] | None = None,
        validity: str = "3",
        preselect_workspace_id: int | None = None,
    ) -> None:
        super().__init__()
        self._workspaces = workspaces
        self._grantable = grantable
        self._name = name
        self._initial_permissions = list(permissions or [])
        self._validity_index = next(
            (i for i, (value, _) in enumerate(VALIDITY_CHOICES) if value == validity),
            _DEFAULT_VALIDITY_INDEX,
        )
        self._workspace_index = next(
            (
                i
                for i, (ws_id, _) in enumerate(workspaces)
                if ws_id == preselect_workspace_id
            ),
            0,
        )
        self.result: ApiKeyFormResult | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="form"):
            yield Label(_INTRO, classes="form-intro")

            yield Label("Name", classes="field-label")
            yield Input(value=self._name, placeholder="e.g. laptop", id="name")

            yield Label("Workspace", classes="field-label")
            with AutoRadioSet(id="workspaces"):
                for index, (_, public_id) in enumerate(self._workspaces):
                    yield RadioButton(public_id, value=index == self._workspace_index)

            yield Label("Permissions", classes="field-label")
            yield SelectionList[str](id="permissions")

            yield Label("Validity", classes="field-label")
            with AutoRadioSet(id="validity"):
                for index, (_, label) in enumerate(VALIDITY_CHOICES):
                    yield RadioButton(label, value=index == self._validity_index)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspaces", AutoRadioSet).select_index(self._workspace_index)
        self.query_one("#validity", AutoRadioSet).select_index(self._validity_index)
        self._populate_permissions(self._initial_permissions)
        self.query_one("#name", Input).focus()

    def _current_workspace_id(self) -> int:
        index = self.query_one("#workspaces", AutoRadioSet).pressed_index
        index = index if index >= 0 else self._workspace_index
        return self._workspaces[index][0]

    def _populate_permissions(self, preselect: list[str]) -> None:
        workspace_id = self._current_workspace_id()
        grantable = self._grantable.get(workspace_id, [])
        options = [
            Selection(permission, permission, permission in preselect)
            for permission in grantable
        ]
        permissions = self.query_one("#permissions", SelectionList)
        permissions.clear_options()
        if options:
            permissions.add_options(options)

    def on_radio_set_changed(self, event: AutoRadioSet.Changed) -> None:
        # Switching workspace changes which permissions are grantable; rebuild
        # the list (keeping any still-grantable selections).
        if event.radio_set.id == "workspaces":
            keep = list(self.query_one("#permissions", SelectionList).selected)
            self._populate_permissions(keep)

    def action_confirm(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.notify("Enter a name for the key.", severity="warning")
            return
        permissions = list(self.query_one("#permissions", SelectionList).selected)
        if not permissions:
            self.notify("Select at least one permission.", severity="warning")
            return

        workspace_index = self.query_one("#workspaces", AutoRadioSet).pressed_index
        if workspace_index < 0:
            self.notify("Select a workspace.", severity="warning")
            return
        validity_index = self.query_one("#validity", AutoRadioSet).pressed_index
        validity = VALIDITY_CHOICES[max(validity_index, 0)][0]

        workspace_id, workspace_public_id = self._workspaces[workspace_index]
        self.result = ApiKeyFormResult(
            name=name,
            workspace_id=workspace_id,
            workspace_public_id=workspace_public_id,
            permissions=permissions,
            validity=validity,
        )
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()


_PICKER_KEYS = (
    "[reverse] ↑/↓ [/] choose  [reverse] enter [/] confirm  [reverse] esc [/] cancel"
)


class IdPicker(App[int | None]):
    """Single-select picker over ``(id, label)`` rows; returns the chosen id.

    Used wherever a command needs the user to pick one of several hub objects
    (an API key to revoke, a provider to activate/remove, a workspace).
    """

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
        keys: list[tuple[int, str]],
        *,
        title: str = "Choose an item.",
        preselect: int = 0,
    ) -> None:
        super().__init__()
        self._keys = keys
        self._title = title
        self._preselect = preselect
        self.result: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="picker"):
            yield Label(f"{self._title}\n{_PICKER_KEYS}", classes="picker-intro")
            with AutoRadioSet(id="keys"):
                for index, (_, label) in enumerate(self._keys):
                    yield RadioButton(label, value=index == self._preselect)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#keys", AutoRadioSet).select_index(self._preselect)

    def action_confirm(self) -> None:
        index = self.query_one("#keys", AutoRadioSet).pressed_index
        if index < 0:
            self.notify("Select an item.", severity="warning")
            return
        self.result = self._keys[index][0]
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()
