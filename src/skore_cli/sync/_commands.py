"""The ``skore sync`` command."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import rich_click as click

from skore_cli._skore import URI_ENV, resolve_hub_uri

MODES = ("local", "hub", "mlflow")
API_KEY_ENV = "SKORE_HUB_API_KEY"


def _project_api():
    """Import the public project API only when synchronization runs."""
    try:
        skore = importlib.import_module("skore")
    except ImportError as error:  # pragma: no cover - exercised through the command
        raise click.ClickException(
            "this command needs the `skore` package (install it with `pip install "
            "skore-cli`)."
        ) from error
    if not hasattr(skore.Project, "sync"):
        raise click.ClickException(
            "synchronization requires `skore>=0.24.0`; upgrade it with "
            "`pip install --upgrade skore`."
        )
    return skore.Project, skore.login


def _endpoint_options(
    mode: str,
    *,
    workspace: str | None,
    tracking_uri: str | None,
    prefix: str,
) -> dict[str, Any]:
    """Validate one endpoint's mode-specific options."""
    workspace_option = f"--{prefix}-workspace"
    tracking_option = f"--{prefix}-tracking-uri"

    if mode == "local":
        if tracking_uri is not None:
            raise click.UsageError(f"{tracking_option} is only valid for MLflow.")
        return (
            {}
            if workspace is None
            else {"workspace": Path(workspace).expanduser().resolve()}
        )

    if mode == "hub":
        if workspace is None:
            raise click.UsageError(f"{workspace_option} is required for Hub.")
        if tracking_uri is not None:
            raise click.UsageError(f"{tracking_option} is only valid for MLflow.")
        return {"workspace": workspace}

    if workspace is not None:
        raise click.UsageError(f"{workspace_option} is not valid for MLflow.")
    return {} if tracking_uri is None else {"tracking_uri": tracking_uri}


def _render_result(result, *, dry_run: bool) -> None:
    """Render synchronization results."""
    if result.empty:
        click.echo("No reports to synchronize.")
    else:
        click.echo(result.to_string())
    if dry_run:
        click.echo("Dry run complete. No reports were transferred.")


@click.command()
@click.argument("source_project")
@click.option("--from", "from_mode", type=click.Choice(MODES), default=None)
@click.option("--from-workspace")
@click.option("--from-tracking-uri")
@click.option("--to", "to_mode", type=click.Choice(MODES), default=None)
@click.option("--to-project", default=None)
@click.option("--to-workspace")
@click.option("--to-tracking-uri")
@click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the Hub API. Defaults to the "
        f"{URI_ENV} environment variable or the public Hub."
    ),
)
@click.option(
    "--both", is_flag=True, help="Synchronize missing reports in both directions."
)
@click.option("--dry-run", is_flag=True, help="Show the synchronization plan only.")
def sync(
    source_project: str,
    from_mode: str | None,
    from_workspace: str | None,
    from_tracking_uri: str | None,
    to_mode: str | None,
    to_project: str | None,
    to_workspace: str | None,
    to_tracking_uri: str | None,
    hub_url: str | None,
    both: bool,
    dry_run: bool,
) -> None:
    """Synchronize report projects across local, Hub, and MLflow storage."""
    if from_mode is None and to_mode is None:
        raise click.UsageError("Pass --from or --to.")

    source_mode = from_mode or "local"
    destination_mode = to_mode or "local"
    destination_project = to_project or source_project

    if source_mode == destination_mode == "mlflow":
        if from_tracking_uri is None:
            from_tracking_uri = to_tracking_uri
        if to_tracking_uri is None:
            to_tracking_uri = from_tracking_uri

    source_options = _endpoint_options(
        source_mode,
        workspace=from_workspace,
        tracking_uri=from_tracking_uri,
        prefix="from",
    )
    destination_options = _endpoint_options(
        destination_mode,
        workspace=to_workspace,
        tracking_uri=to_tracking_uri,
        prefix="to",
    )
    if (
        source_mode == destination_mode == "mlflow"
        and source_options != destination_options
    ):
        raise click.UsageError("MLflow synchronization requires the same tracking URI.")
    if (
        source_mode == destination_mode
        and source_project == destination_project
        and source_options == destination_options
    ):
        raise click.UsageError("Source and destination identify the same project.")

    uses_hub = "hub" in (source_mode, destination_mode)
    if hub_url is not None and not uses_hub:
        raise click.UsageError("--hub-url requires a Hub endpoint.")
    if uses_hub and not os.environ.get(API_KEY_ENV):
        raise click.ClickException(f"Hub synchronization requires {API_KEY_ENV}.")

    try:
        Project, login = _project_api()
        if uses_hub:
            resolve_hub_uri(hub_url)
            login(mode="hub")
        source = Project(source_project, mode=source_mode, **source_options)
        destination = Project(
            destination_project,
            mode=destination_mode,
            **destination_options,
        )
        result = source.sync(destination, bidirectional=both, dry_run=dry_run)
    except click.ClickException:
        raise
    except Exception as error:
        raise click.ClickException(str(error)) from error

    _render_result(result, dry_run=dry_run)
