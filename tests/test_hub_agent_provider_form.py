"""Textual pilot tests for the interactive ``skore hub agent-provider add`` form."""

from __future__ import annotations

from textual.widgets import Input

from skore_cli.hub.app import AgentProviderForm

MODELS = {"anthropic": ["claude-x"], "bedrock": ["nova"]}


def _form(**kwargs):
    kwargs.setdefault("encryption_configured", True)
    kwargs.setdefault("name", "team")
    return AgentProviderForm(MODELS, **kwargs)


async def test_provider_switch_toggles_field_groups():
    app = _form()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#skore-fields").display is True
        assert app.query_one("#anthropic-fields").display is False

        app.query_one("#provider").action_next_button()
        await pilot.pause()
        assert app.query_one("#skore-fields").display is False
        assert app.query_one("#anthropic-fields").display is True
        assert app.query_one("#bedrock-fields").display is False


async def test_skore_confirm_returns_result():
    app = _form()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result is not None
    assert app.result.provider == "skore"
    assert app.result.selected_model is None
    assert app.result.activate is True


async def test_anthropic_requires_key_then_confirms():
    app = _form()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#provider").action_next_button()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
        assert app.result is None

        app.query_one("#anthropic-api-key", Input).value = "secret"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result is not None
    assert app.result.provider == "anthropic"
    assert app.result.selected_model == "claude-x"
    assert app.result.anthropic_api_key == "secret"


async def test_bedrock_confirms_with_optional_fields():
    app = _form()
    async with app.run_test() as pilot:
        await pilot.pause()
        provider = app.query_one("#provider")
        provider.action_next_button()
        provider.action_next_button()
        await pilot.pause()
        assert app.query_one("#bedrock-fields").display is True

        app.query_one("#aws-region", Input).value = "us-east-1"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result is not None
    assert app.result.provider == "bedrock"
    assert app.result.selected_model == "nova"
    assert app.result.aws_region == "us-east-1"
    assert app.result.bedrock_role_arn is None


async def test_activate_default_off_reflected():
    app = _form(activate_default=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert app.result is not None
    assert app.result.activate is False


async def test_escape_returns_none():
    app = _form()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


async def test_byo_disabled_without_encryption():
    app = _form(encryption_configured=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#provider-anthropic").disabled is True
        assert app.query_one("#provider-bedrock").disabled is True
        assert app.query_one("#provider-skore").disabled is False
