"""Textual pilot tests for the interactive harness/workspace pickers."""

from __future__ import annotations

from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import SelectionList

from skore_cli.agent.app import HarnessPicker, WorkspacePicker
from skore_cli.app._banner import SkoreBanner
from skore_cli.app._help import HELP_BINDING, HelpInput, HelpScreen
from skore_cli.skills.app import (
    InstalledSkillsPicker,
    ProbablSkillsInstaller,
)

HARNESSES = [
    ("opencode", "OpenCode", True),
    ("claude", "Claude", False),
    ("pi", "Pi", False),
]

WORKSPACES = [("ws-1", "First"), ("ws-2", "Second")]


async def test_textual_apps_show_banner():
    catalog = {"workflows": [], "skills": []}
    apps = [
        HarnessPicker(HARNESSES),
        WorkspacePicker(WORKSPACES),
        InstalledSkillsPicker(["alpha"], title="Update skills"),
        ProbablSkillsInstaller(catalog, agent=(), default_global=False),
    ]

    for app in apps:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(SkoreBanner)


# --------------------------------------------------------------------------- #
# HarnessPicker
# --------------------------------------------------------------------------- #


async def test_harness_picker_confirms_preselected():
    app = HarnessPicker(HARNESSES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == "opencode"


async def test_harness_picker_honors_preselect():
    app = HarnessPicker(HARNESSES, preselect=1)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == "claude"


async def test_harness_picker_cancel_returns_none():
    app = HarnessPicker(HARNESSES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


def test_harness_picker_requires_selection(monkeypatch):
    app = HarnessPicker(HARNESSES)
    notifications = []
    radio = SimpleNamespace(pressed_index=-1)

    monkeypatch.setattr(app, "query_one", lambda *_: radio)
    monkeypatch.setattr(
        app, "notify", lambda message, **_: notifications.append(message)
    )

    app.action_confirm()

    assert notifications == ["Select a harness."]


async def test_harness_picker_help_screen():
    app = HarnessPicker(HARNESSES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running is True


# --------------------------------------------------------------------------- #
# WorkspacePicker
# --------------------------------------------------------------------------- #


async def test_workspace_picker_confirms_selection():
    app = WorkspacePicker(WORKSPACES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == "ws-1"


async def test_workspace_picker_honors_preselect():
    app = WorkspacePicker(WORKSPACES, preselect=1)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == "ws-2"


async def test_workspace_picker_cancel_returns_none():
    app = WorkspacePicker(WORKSPACES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


def test_workspace_picker_requires_selection(monkeypatch):
    app = WorkspacePicker(WORKSPACES)
    notifications = []
    radio = SimpleNamespace(pressed_index=-1)

    monkeypatch.setattr(app, "query_one", lambda *_: radio)
    monkeypatch.setattr(
        app, "notify", lambda message, **_: notifications.append(message)
    )

    app.action_confirm()

    assert notifications == ["Select a workspace."]


async def test_workspace_picker_help_screen():
    app = WorkspacePicker(WORKSPACES, preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)


# --------------------------------------------------------------------------- #
# InstalledSkillsPicker
# --------------------------------------------------------------------------- #


async def test_installed_picker_confirms_selection():
    app = InstalledSkillsPicker(["alpha", "beta"], title="Update skills")
    async with app.run_test() as pilot:
        app.query_one("#sel-installed", SelectionList).select_all()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert set(app.result) == {"alpha", "beta"}


async def test_installed_picker_requires_selection():
    app = InstalledSkillsPicker(["alpha", "beta"], title="Remove skills")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


async def test_installed_picker_cancel_returns_none():
    app = InstalledSkillsPicker(["alpha"], title="Remove skills")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


async def test_installed_picker_help_screen():
    app = InstalledSkillsPicker(["alpha"], title="Update skills")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running is True


# --------------------------------------------------------------------------- #
# HelpInput
# --------------------------------------------------------------------------- #


class _HelpInputApp(App[None]):
    BINDINGS = [HELP_BINDING]

    def __init__(self) -> None:
        super().__init__()
        self.help_shown = 0

    def compose(self) -> ComposeResult:
        yield HelpInput(id="field")

    def action_show_help(self) -> None:
        self.help_shown += 1


async def test_help_input_opens_help_on_question_mark():
    app = _HelpInputApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#field", HelpInput).focus()
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()

        assert app.help_shown == 1
        # The `?` must not be inserted into the input.
        assert app.query_one("#field", HelpInput).value == ""


async def test_help_input_inserts_normal_characters():
    app = _HelpInputApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#field", HelpInput).focus()
        await pilot.pause()
        await pilot.press("a", "b")
        await pilot.pause()

        assert app.help_shown == 0
        assert app.query_one("#field", HelpInput).value == "ab"
