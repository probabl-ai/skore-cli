"""Textual pilot tests for the interactive harness/workspace pickers."""

from __future__ import annotations

from skore_cli.agent.app import HarnessPicker, WorkspacePicker
from skore_cli.app._help import HelpScreen

HARNESSES = [
    ("opencode", "OpenCode", True),
    ("claude", "Claude", False),
    ("pi", "Pi", False),
]

WORKSPACES = [("ws-1", "First"), ("ws-2", "Second")]


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
