"""The ``skore hub agent-provider`` group: ``add``/``list``/``activate``/``remove``.

Manage a workspace's agent LLM provider configuration, mirroring the hub UI.
Every command requires a prior ``skore hub login`` (a stored OAuth token) and is
scoped to a single workspace (resolved from ``-w/--workspace`` or, in a
terminal, an interactive picker). Heavy ``httpx``/``textual`` imports stay
deferred inside the callbacks.
"""

from __future__ import annotations

import rich_click as click

from skore_cli._style import console
from skore_cli.hub import _client
from skore_cli.hub._api_keys import (
    _HUB_URL_OPTION,
    _is_interactive,
    _resolve_session,
)
from skore_cli.hub._client import AGENT_PROVIDERS

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub agent-provider": [
        {"name": "Manage", "commands": ["add", "list", "activate", "remove"]},
    ],
}


@click.group("agent-provider", invoke_without_command=True)
@click.pass_context
def agent_provider(ctx) -> None:
    """Add, list, activate and remove a workspace's agent LLM providers."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _resolve_target_workspace(
    memberships: list[_client.Membership],
    workspace: str | None,
    *,
    interactive: bool,
) -> _client.Membership:
    """Resolve the single workspace to act on.

    A ``-w/--workspace`` flag wins (validated against memberships). Otherwise a
    lone membership is used directly; with several, an interactive picker is
    shown when possible, else a usage error lists the available public ids.
    """
    if not memberships:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one first."
        )

    by_public = {m.public_id: m for m in memberships}
    if workspace is not None:
        if workspace not in by_public:
            raise click.UsageError(
                f"unknown workspace '{workspace}'; you belong to: "
                f"{', '.join(by_public) or 'none'}."
            )
        return by_public[workspace]

    if len(memberships) == 1:
        return memberships[0]

    if interactive:
        from skore_cli.hub.app import IdPicker

        labels = [(m.workspace_id, m.public_id) for m in memberships]
        app = IdPicker(labels, title="Choose the workspace.")
        app.run()
        if app.result is None:
            raise click.Abort()
        return next(m for m in memberships if m.workspace_id == app.result)

    raise click.UsageError(
        f"pass --workspace <public-id> (one of: {', '.join(by_public) or 'none'})."
    )


def _model_or_auto(provider: _client.ProviderEntry) -> str:
    return provider.selected_model or "auto"


def _secrets_summary(provider: _client.ProviderEntry) -> str:
    flags = []
    if provider.anthropic_api_key_set:
        flags.append("anthropic-key")
    if provider.bedrock_external_id_set:
        flags.append("bedrock-external-id")
    if provider.aws_access_key_id_set:
        flags.append("aws-access-key-id")
    if provider.aws_secret_access_key_set:
        flags.append("aws-secret-access-key")
    return ", ".join(flags) or "-"


def _build_payload(
    *,
    name: str,
    provider: str,
    model: str | None,
    anthropic_api_key: str | None,
    aws_region: str | None,
    bedrock_role_arn: str | None,
    bedrock_external_id: str | None,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
) -> dict[str, object]:
    """Build the create payload, mirroring the hub UI (drops irrelevant fields)."""
    payload: dict[str, object] = {"name": name, "provider": provider}
    if provider == "skore":
        return payload
    payload["selected_model"] = model
    if provider == "anthropic":
        payload["anthropic_api_key"] = anthropic_api_key
        return payload
    # bedrock: AWS fields are optional.
    payload.update(
        {
            key: value
            for key, value in (
                ("aws_region", aws_region),
                ("bedrock_role_arn", bedrock_role_arn),
                ("bedrock_external_id", bedrock_external_id),
                ("aws_access_key_id", aws_access_key_id),
                ("aws_secret_access_key", aws_secret_access_key),
            )
            if value
        }
    )
    return payload


@agent_provider.command("add")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to act on."
)
@click.option("--name", default=None, help="A label for the provider.")
@click.option(
    "--provider",
    type=click.Choice(AGENT_PROVIDERS),
    default=None,
    help="Provider type to register.",
)
@click.option("--model", default=None, help="Model to use (for anthropic/bedrock).")
@click.option("--anthropic-api-key", default=None, help="Anthropic API key.")
@click.option("--aws-region", default=None, help="AWS region (bedrock).")
@click.option("--bedrock-role-arn", default=None, help="Bedrock role ARN.")
@click.option("--bedrock-external-id", default=None, help="Bedrock external id.")
@click.option("--aws-access-key-id", default=None, help="AWS access key id (bedrock).")
@click.option(
    "--aws-secret-access-key", default=None, help="AWS secret access key (bedrock)."
)
@click.option(
    "--activate/--no-activate",
    default=False,
    help="Activate the provider right after adding it.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the interactive form even in a terminal (use the flags as given).",
)
def add(
    hub_url: str | None,
    workspace: str | None,
    name: str | None,
    provider: str | None,
    model: str | None,
    anthropic_api_key: str | None,
    aws_region: str | None,
    bedrock_role_arn: str | None,
    bedrock_external_id: str | None,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    activate: bool,
    yes: bool,
) -> None:
    """Add an agent LLM provider to a workspace.

    In a terminal, omitting ``--provider`` (or a field it requires) opens an
    interactive, provider-adaptive form. Non-interactively (or with ``--yes``),
    ``--workspace`` (unless you belong to one), ``--name`` and ``--provider`` are
    required; bring-your-own providers also need ``--model`` (and, for
    ``anthropic``, ``--anthropic-api-key``).
    """
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    interactive = _is_interactive()
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=interactive
    )
    providers = _client.agent_providers(uri, token, membership.workspace_id)

    def _missing_required() -> bool:
        if provider is None:
            return True
        if provider != "skore" and not model:
            return True
        return provider == "anthropic" and not anthropic_api_key

    if interactive and not yes and _missing_required():
        from skore_cli.hub.app import AgentProviderForm

        has_active = any(p.is_active for p in providers.providers)
        app = AgentProviderForm(
            providers.available_models,
            encryption_configured=providers.encryption_configured,
            name=name or "",
            activate_default=activate or not has_active,
        )
        app.run()
        if app.result is None:
            console.print("Nothing added.")
            return
        result = app.result
        chosen_name = result.name
        chosen_provider = result.provider
        model = result.selected_model
        anthropic_api_key = result.anthropic_api_key
        aws_region = result.aws_region
        bedrock_role_arn = result.bedrock_role_arn
        bedrock_external_id = result.bedrock_external_id
        aws_access_key_id = result.aws_access_key_id
        aws_secret_access_key = result.aws_secret_access_key
        activate = result.activate
    else:
        if provider is None:
            raise click.UsageError(
                f"pass --provider (one of: {', '.join(AGENT_PROVIDERS)})."
            )
        if not name:
            raise click.UsageError("pass --name <name> for the provider.")
        if provider != "skore":
            if not providers.encryption_configured:
                raise click.ClickException(
                    f"the '{membership.public_id}' workspace has no encryption "
                    "configured; bring-your-own providers are unavailable. Use "
                    "--provider skore or configure encryption in the hub."
                )
            available = providers.available_models.get(provider, [])
            if not model:
                raise click.UsageError(
                    f"pass --model for '{provider}' (one of: "
                    f"{', '.join(available) or 'none'})."
                )
            if model not in available:
                raise click.UsageError(
                    f"unknown model '{model}' for '{provider}'; available: "
                    f"{', '.join(available) or 'none'}."
                )
            if provider == "anthropic" and not anthropic_api_key:
                raise click.UsageError(
                    "pass --anthropic-api-key for the anthropic provider."
                )
        chosen_name = name
        chosen_provider = provider

    payload = _build_payload(
        name=chosen_name,
        provider=chosen_provider,
        model=model,
        anthropic_api_key=anthropic_api_key,
        aws_region=aws_region,
        bedrock_role_arn=bedrock_role_arn,
        bedrock_external_id=bedrock_external_id,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    created = _client.create_agent_provider(
        uri, token, membership.workspace_id, payload=payload
    )
    if activate:
        _client.activate_agent_provider(uri, token, membership.workspace_id, created.id)

    console.print(
        f"[skore.ok]+ added provider[/] "
        f"[skore.muted](id {created.id}, workspace {membership.public_id})[/]"
    )
    console.print(f"  name     : {created.name}")
    console.print(f"  provider : {created.provider}")
    console.print(f"  model    : {_model_or_auto(created)}")
    console.print(f"  active   : {'yes' if activate else 'no'}")


@agent_provider.command("list")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to act on."
)
def list_providers(hub_url: str | None, workspace: str | None) -> None:
    """List a workspace's agent LLM providers (secrets are never shown)."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=_is_interactive()
    )
    providers = _client.agent_providers(uri, token, membership.workspace_id)

    if not providers.providers:
        console.print("[skore.muted]No agent providers.[/]")
    else:
        from rich.table import Table

        table = Table(box=None, pad_edge=False)
        for column in ("id", "name", "provider", "model", "active", "secrets"):
            table.add_column(column)
        for entry in providers.providers:
            table.add_row(
                str(entry.id),
                entry.name,
                entry.provider,
                _model_or_auto(entry),
                "yes" if entry.is_active else "-",
                _secrets_summary(entry),
            )
        console.print(table)

    if not providers.encryption_configured:
        console.print(
            "[skore.muted]Encryption is not configured for this workspace; "
            "bring-your-own (anthropic/bedrock) providers are unavailable.[/]"
        )


def _pick_provider(providers: list[_client.ProviderEntry], *, title: str) -> int | None:
    from skore_cli.hub.app import IdPicker

    labels = [
        (
            entry.id,
            f"{entry.id}  {entry.name}  ({entry.provider}/"
            f"{_model_or_auto(entry)})" + ("  *active" if entry.is_active else ""),
        )
        for entry in providers
    ]
    app = IdPicker(labels, title=title)
    app.run()
    return app.result


@agent_provider.command("activate")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to act on."
)
@click.option("--id", "config_id", type=int, default=None, help="Provider id.")
def activate(hub_url: str | None, workspace: str | None, config_id: int | None) -> None:
    """Activate one provider for the workspace (deactivates the others)."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    interactive = _is_interactive()
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=interactive
    )

    if config_id is None:
        providers = _client.agent_providers(uri, token, membership.workspace_id)
        if not providers.providers:
            console.print("[skore.muted]No agent providers to activate.[/]")
            return
        if not interactive:
            raise click.UsageError(
                "pass --id <id> to activate non-interactively (ids: "
                f"{', '.join(str(p.id) for p in providers.providers)})."
            )
        config_id = _pick_provider(
            providers.providers, title="Choose the provider to activate."
        )
        if config_id is None:
            console.print("Nothing activated.")
            return

    _client.activate_agent_provider(uri, token, membership.workspace_id, config_id)
    console.print(f"[skore.ok]+[/] activated provider {config_id}.")


@agent_provider.command("remove")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to act on."
)
@click.option("--id", "config_id", type=int, default=None, help="Provider id.")
@click.option(
    "--yes", is_flag=True, default=False, help="Skip the confirmation prompt."
)
def remove(
    hub_url: str | None, workspace: str | None, config_id: int | None, yes: bool
) -> None:
    """Remove a provider from the workspace, or pick one interactively."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    interactive = _is_interactive()
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=interactive
    )

    if config_id is None:
        providers = _client.agent_providers(uri, token, membership.workspace_id)
        if not providers.providers:
            console.print("[skore.muted]No agent providers to remove.[/]")
            return
        if not interactive:
            raise click.UsageError(
                "pass --id <id> to remove non-interactively (ids: "
                f"{', '.join(str(p.id) for p in providers.providers)})."
            )
        config_id = _pick_provider(
            providers.providers, title="Choose the provider to remove."
        )
        if config_id is None:
            console.print("Nothing removed.")
            return

    if not yes:
        click.confirm(f"Remove provider {config_id}?", abort=True)
    _client.delete_agent_provider(uri, token, membership.workspace_id, config_id)
    console.print(f"[skore.ok]-[/] removed provider {config_id}.")
