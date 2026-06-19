"""Textual pilot tests for the interactive ``skore hub api-key`` form/picker."""

from __future__ import annotations

from textual.widgets import SelectionList

from skore_cli.hub.app import ApiKeyForm, ApiKeyPicker

WORKSPACES = [(7, "ws-a"), (8, "ws-b")]
GRANTABLE = {7: ["create:project", "read:project"], 8: ["read:project"]}


# --------------------------------------------------------------------------- #
# ApiKeyForm
# --------------------------------------------------------------------------- #


async def test_form_confirm_returns_result():
    app = ApiKeyForm(
        WORKSPACES, GRANTABLE, name="laptop", validity="never", preselect_workspace_id=7
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#permissions", SelectionList).select_all()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result is not None
    assert app.result.name == "laptop"
    assert app.result.workspace_id == 7
    assert app.result.workspace_public_id == "ws-a"
    assert set(app.result.permissions) == {"create:project", "read:project"}
    assert app.result.validity == "never"


async def test_form_requires_name_stays_open():
    app = ApiKeyForm(WORKSPACES, GRANTABLE, name="", preselect_workspace_id=7)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#permissions", SelectionList).select_all()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
        assert app.result is None
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


async def test_form_requires_permission_stays_open():
    app = ApiKeyForm(WORKSPACES, GRANTABLE, name="x", preselect_workspace_id=7)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
        assert app.result is None
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


async def test_form_cancel_returns_none():
    app = ApiKeyForm(WORKSPACES, GRANTABLE, name="x", preselect_workspace_id=7)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


def _permission_values(app):
    return [
        option.value for option in app.query_one("#permissions", SelectionList).options
    ]


async def test_form_permissions_track_workspace():
    # ws-b grants only read:project; switching to it should drop create:project.
    app = ApiKeyForm(WORKSPACES, GRANTABLE, name="x", preselect_workspace_id=7)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert sorted(_permission_values(app)) == ["create:project", "read:project"]

        app.query_one("#workspaces").action_next_button()
        await pilot.pause()
        values = _permission_values(app)

    assert values == ["read:project"]


# --------------------------------------------------------------------------- #
# ApiKeyPicker
# --------------------------------------------------------------------------- #


async def test_picker_confirms_selection():
    app = ApiKeyPicker([(5, "5  laptop"), (6, "6  ci")], preselect=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == 5


async def test_picker_cancel_returns_none():
    app = ApiKeyPicker([(5, "5  laptop")])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None
