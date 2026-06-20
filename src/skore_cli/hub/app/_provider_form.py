"""Textual app backing the interactive ``skore hub agent-provider add`` command.

``AgentProviderForm`` is a single-screen, provider-adaptive form mirroring the
hub UI's agent provider modal: picking ``skore`` needs nothing else, while the
bring-your-own ``anthropic``/``bedrock`` providers reveal a model picker and the
relevant secret fields (only offered when the workspace has encryption
configured and the hub advertises models for them). It follows the package
convention: set ``self.result`` then ``exit()``; the caller reads ``app.result``
after ``app.run()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import (
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
)

from skore_cli.skills.app._widgets import AutoRadioSet

_PROVIDER_ORDER = ["skore", "anthropic", "bedrock"]

_INTRO = (
    "Add an agent LLM provider for the workspace.\n"
    "Pick a provider; bring-your-own providers need a model (and secrets).\n"
    "[reverse] tab [/] next field  [reverse] ↑/↓ [/] choose  "
    "[reverse] enter [/] add  [reverse] esc [/] cancel"
)


@dataclass(frozen=True)
class AgentProviderFormResult:
    """The choices captured by :class:`AgentProviderForm`."""

    name: str
    provider: str
    selected_model: str | None
    anthropic_api_key: str | None
    aws_region: str | None
    bedrock_role_arn: str | None
    bedrock_external_id: str | None
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    activate: bool


class AgentProviderForm(App[AgentProviderFormResult | None]):
    """Interactive, provider-adaptive form to register an agent provider."""

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
    .field-hint {
        margin: 0 1;
        color: $text-muted;
    }
    Input {
        margin: 0 1;
        width: 100%;
    }
    AutoRadioSet {
        margin: 0 1;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Add", priority=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Previous", show=False),
    ]

    def __init__(
        self,
        available_models: dict[str, list[str]],
        *,
        encryption_configured: bool,
        name: str = "",
        activate_default: bool = True,
    ) -> None:
        super().__init__()
        self._available_models = available_models
        self._encryption_configured = encryption_configured
        self._name = name
        self._activate_default = activate_default
        self._selectable = {
            provider: self._is_selectable(provider) for provider in _PROVIDER_ORDER
        }
        self._initial_provider = next(
            (p for p in _PROVIDER_ORDER if self._selectable[p]), "skore"
        )
        self.result: AgentProviderFormResult | None = None

    def _is_selectable(self, provider: str) -> bool:
        if provider == "skore":
            return True
        return self._encryption_configured and bool(
            self._available_models.get(provider)
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="form"):
            yield Label(_INTRO, classes="form-intro")

            yield Label("Name", classes="field-label")
            yield Input(value=self._name, placeholder="e.g. team-anthropic", id="name")

            yield Label("Provider", classes="field-label")
            with AutoRadioSet(id="provider"):
                for provider in _PROVIDER_ORDER:
                    yield RadioButton(
                        provider,
                        value=provider == self._initial_provider,
                        disabled=not self._selectable[provider],
                        id=f"provider-{provider}",
                    )

            with Vertical(id="skore-fields"):
                yield Label(
                    "Uses skore's managed LLM -- no extra configuration needed.",
                    classes="field-hint",
                )

            with Vertical(id="anthropic-fields"):
                yield Label("Model", classes="field-label")
                with AutoRadioSet(id="anthropic-model"):
                    for index, model in enumerate(
                        self._available_models.get("anthropic", [])
                    ):
                        yield RadioButton(model, value=index == 0)
                yield Label("Anthropic API key", classes="field-label")
                yield Input(password=True, id="anthropic-api-key")

            with Vertical(id="bedrock-fields"):
                yield Label("Model", classes="field-label")
                with AutoRadioSet(id="bedrock-model"):
                    for index, model in enumerate(
                        self._available_models.get("bedrock", [])
                    ):
                        yield RadioButton(model, value=index == 0)
                yield Label("AWS region", classes="field-label")
                yield Input(id="aws-region", placeholder="e.g. us-east-1")
                yield Label("Bedrock role ARN", classes="field-label")
                yield Input(id="bedrock-role-arn")
                yield Label("Bedrock external id", classes="field-label")
                yield Input(id="bedrock-external-id")
                yield Label("AWS access key id", classes="field-label")
                yield Input(id="aws-access-key-id")
                yield Label("AWS secret access key", classes="field-label")
                yield Input(password=True, id="aws-secret-access-key")

            yield Checkbox("Activate now", value=self._activate_default, id="activate")
        yield Footer()

    def on_mount(self) -> None:
        index = _PROVIDER_ORDER.index(self._initial_provider)
        self.query_one("#provider", AutoRadioSet).select_index(index)
        self._show_fields(self._initial_provider)
        self.query_one("#name", Input).focus()

    def _current_provider(self) -> str:
        index = self.query_one("#provider", AutoRadioSet).pressed_index
        if index < 0:
            return self._initial_provider
        return _PROVIDER_ORDER[index]

    def _show_fields(self, provider: str) -> None:
        for name in _PROVIDER_ORDER:
            self.query_one(f"#{name}-fields", Vertical).display = name == provider

    def on_radio_set_changed(self, event: AutoRadioSet.Changed) -> None:
        if event.radio_set.id == "provider":
            self._show_fields(self._current_provider())

    def _selected_model(self, provider: str) -> str | None:
        radio = self.query_one(f"#{provider}-model", AutoRadioSet)
        index = radio.pressed_index
        models = self._available_models.get(provider, [])
        if 0 <= index < len(models):
            return models[index]
        return None

    def action_confirm(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.notify("Enter a name for the provider.", severity="warning")
            return
        provider = self._current_provider()

        selected_model: str | None = None
        anthropic_api_key: str | None = None
        aws_region: str | None = None
        bedrock_role_arn: str | None = None
        bedrock_external_id: str | None = None
        aws_access_key_id: str | None = None
        aws_secret_access_key: str | None = None

        if provider != "skore":
            selected_model = self._selected_model(provider)
            if not selected_model:
                self.notify("Select a model.", severity="warning")
                return
        if provider == "anthropic":
            anthropic_api_key = (
                self.query_one("#anthropic-api-key", Input).value.strip() or None
            )
            if not anthropic_api_key:
                self.notify("Enter the Anthropic API key.", severity="warning")
                return
        if provider == "bedrock":
            aws_region = self.query_one("#aws-region", Input).value.strip() or None
            bedrock_role_arn = (
                self.query_one("#bedrock-role-arn", Input).value.strip() or None
            )
            bedrock_external_id = (
                self.query_one("#bedrock-external-id", Input).value.strip() or None
            )
            aws_access_key_id = (
                self.query_one("#aws-access-key-id", Input).value.strip() or None
            )
            aws_secret_access_key = (
                self.query_one("#aws-secret-access-key", Input).value.strip() or None
            )

        self.result = AgentProviderFormResult(
            name=name,
            provider=provider,
            selected_model=selected_model,
            anthropic_api_key=anthropic_api_key,
            aws_region=aws_region,
            bedrock_role_arn=bedrock_role_arn,
            bedrock_external_id=bedrock_external_id,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            activate=self.query_one("#activate", Checkbox).value,
        )
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()
