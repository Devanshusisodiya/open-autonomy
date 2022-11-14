# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Deploy CLI module."""

import shutil
from pathlib import Path
from typing import Optional, cast

import click
from aea.cli.registry.settings import REGISTRY_REMOTE
from aea.cli.utils.click_utils import password_option, registry_flag
from aea.cli.utils.context import Context
from aea.configurations.data_types import PublicId
from aea.helpers.base import cd

from autonomy.cli.fetch import fetch_service
from autonomy.cli.helpers.deployment import (
    build_deployment,
    run_deployment,
    update_multisig_address,
)
from autonomy.cli.utils.click_utils import chain_selection_flag
from autonomy.configurations.loader import load_service_config
from autonomy.constants import DEFAULT_BUILD_FOLDER, DEFAULT_KEYS_FILE
from autonomy.deploy.chain import ServiceRegistry
from autonomy.deploy.constants import INFO, LOGGING_LEVELS
from autonomy.deploy.generators.docker_compose.base import DockerComposeGenerator
from autonomy.deploy.generators.kubernetes.base import KubernetesGenerator
from autonomy.deploy.image import build_image


PACKAGES_DIR = "packages_dir"
OPEN_AEA_DIR = "open_aea_dir"
OPEN_AUTONOMY_DIR = "open_autonomy_dir"


@click.group(name="deploy")
@click.pass_context
def deploy_group(
    click_context: click.Context,  # pylint: disable=unused-argument
) -> None:
    """Deploy an agent service."""


@deploy_group.command(name="build")
@click.argument("keys_file", type=str, required=False)
@click.option(
    "--o",
    "output_dir",
    type=click.Path(exists=False, dir_okay=True),
    help="Path to output dir.",
)
@click.option(
    "--n",
    "number_of_agents",
    type=int,
    default=None,
    help="Number of agents.",
)
@click.option(
    "--docker",
    "deployment_type",
    flag_value=DockerComposeGenerator.deployment_type,
    default=True,
    help="Use docker as a backend.",
)
@click.option(
    "--kubernetes",
    "deployment_type",
    flag_value=KubernetesGenerator.deployment_type,
    help="Use kubernetes as a backend.",
)
@click.option(
    "--dev",
    "dev_mode",
    is_flag=True,
    default=False,
    help="Create development environment.",
)
@click.option(
    "--force",
    "force_overwrite",
    is_flag=True,
    default=False,
    help="Remove existing build and overwrite with new one.",
)
@click.option(
    "--log-level",
    type=click.Choice(choices=LOGGING_LEVELS, case_sensitive=True),
    help="Logging level for runtime.",
    default=INFO,
)
@click.option(
    "--packages-dir", type=click.Path(), help="Path to packages dir (Use with dev mode)"
)
@click.option(
    "--open-aea-dir",
    type=click.Path(),
    help="Path to open-aea repo (Use with dev mode)",
)
@click.option(
    "--open-autonomy-dir",
    type=click.Path(),
    help="Path to open-autonomy repo (Use with dev mode)",
)
@click.option(
    "--aev",
    is_flag=True,
    default=False,
    help="Apply environment variable when loading service config.",
)
@click.option(
    "--use-hardhat",
    is_flag=True,
    default=False,
    help="Include a hardhat node in the deployment setup.",
)
@click.option(
    "--use-acn",
    is_flag=True,
    default=False,
    help="Include an ACN node in the deployment setup.",
)
@click.option("--image-version", type=str, help="Define runtime image version.")
@registry_flag()
@password_option(confirmation_prompt=True)
@click.pass_context
def build_deployment_command(  # pylint: disable=too-many-arguments, too-many-locals
    click_context: click.Context,
    keys_file: Optional[Path],
    deployment_type: str,
    output_dir: Optional[Path],
    dev_mode: bool,
    force_overwrite: bool,
    registry: str,
    number_of_agents: Optional[int] = None,
    password: Optional[str] = None,
    open_aea_dir: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
    open_autonomy_dir: Optional[Path] = None,
    log_level: str = INFO,
    aev: bool = False,
    image_version: Optional[str] = None,
    use_hardhat: bool = False,
    use_acn: bool = False,
) -> None:
    """Build deployment setup for n agents."""

    keys_file = Path(keys_file or DEFAULT_KEYS_FILE).absolute()
    build_dir = Path(output_dir or DEFAULT_BUILD_FOLDER).absolute()

    packages_dir = Path(packages_dir or Path.cwd() / "packages").absolute()
    open_aea_dir = Path(open_aea_dir or Path.home() / "open-aea").absolute()
    open_autonomy_dir = Path(
        open_autonomy_dir or Path.home() / "open-autonomy"
    ).absolute()

    if dev_mode:
        for name, path in (
            (PACKAGES_DIR, packages_dir),
            (OPEN_AEA_DIR, open_aea_dir),
            (OPEN_AUTONOMY_DIR, open_autonomy_dir),
        ):
            if not path.exists():
                flag = "--" + "-".join(name.split("_"))
                raise click.ClickException(
                    f"Path does not exist @ {path} for {name}; Please provide proper value for {flag}"
                )

    ctx = cast(Context, click_context.obj)
    ctx.registry_type = registry

    try:
        build_deployment(
            keys_file,
            build_dir,
            deployment_type,
            dev_mode,
            force_overwrite,
            number_of_agents,
            password,
            packages_dir,
            open_aea_dir,
            open_autonomy_dir,
            log_level=log_level,
            substitute_env_vars=aev,
            image_version=image_version,
            use_hardhat=use_hardhat,
            use_acn=use_acn,
        )
    except Exception as e:  # pylint: disable=broad-except
        shutil.rmtree(build_dir)
        raise click.ClickException(str(e)) from e


@deploy_group.command(name="run")
@click.option(
    "--build-dir",
    type=click.Path(),
)
@click.option(
    "--no-recreate",
    is_flag=True,
    default=False,
    help="If containers already exist, don't recreate them.",
)
@click.option(
    "--remove-orphans",
    is_flag=True,
    default=False,
    help="Remove containers for services not defined in the Compose file.",
)
def run(build_dir: Path, no_recreate: bool, remove_orphans: bool) -> None:
    """Run deployment."""
    build_dir = Path(build_dir or Path.cwd()).absolute()
    run_deployment(build_dir, no_recreate, remove_orphans)


@deploy_group.command(name="from-token")
@click.argument("token_id", type=int)
@click.argument("keys_file", type=click.Path())
@click.option("--rpc", "rpc_url", type=str, help="Custom RPC URL")
@click.option(
    "--sca",
    "service_contract_address",
    type=str,
    help="Service contract address for custom RPC URL.",
)
@click.option("--n", type=int, help="Number of agents to include in the build.")
@click.option("--skip-image", is_flag=True, default=False, help="Skip building images.")
@click.option(
    "--aev",
    is_flag=True,
    default=False,
    help="Apply environment variable when loading service config.",
)
@chain_selection_flag()
@click.pass_context
def run_deployment_from_token(  # pylint: disable=too-many-arguments, too-many-locals
    click_context: click.Context,
    token_id: int,
    keys_file: Path,
    chain_type: str,
    rpc_url: Optional[str],
    service_contract_address: Optional[str],
    skip_image: bool,
    n: Optional[int],
    aev: bool = False,
) -> None:
    """Run service deployment."""

    ctx = cast(Context, click_context.obj)
    ctx.registry_type = REGISTRY_REMOTE
    keys_file = Path(keys_file or DEFAULT_KEYS_FILE).absolute()
    service_registry = ServiceRegistry(chain_type, rpc_url, service_contract_address)

    click.echo(f"Building service deployment using token ID: {token_id}")
    metadata = service_registry.resolve_token_id(token_id)
    _, agent_instances = service_registry.get_agent_instances(token_id)
    click.echo("Service name: " + metadata["name"])

    _, multisig_address, *_ = service_registry.get_service_info(token_id)
    *_, service_hash = metadata["code_uri"].split("//")
    public_id = PublicId(author="valory", name="service", package_hash=service_hash)
    service_path = fetch_service(ctx, public_id)
    build_dir = service_path / DEFAULT_BUILD_FOLDER

    update_multisig_address(service_path, multisig_address)
    service = load_service_config(service_path, substitute_env_vars=aev)

    with cd(service_path):
        if not skip_image:
            click.echo("Building required images.")
            build_image(agent=service.agent)

        build_deployment(
            keys_file,
            build_dir=build_dir,
            deployment_type=DockerComposeGenerator.deployment_type,
            dev_mode=False,
            force_overwrite=True,
            number_of_agents=n,
            agent_instances=agent_instances,
            substitute_env_vars=aev,
        )

    click.echo("Service build successful.")
    run_deployment(build_dir)
