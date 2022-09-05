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

"""Test 'scaffold fsm' subcommand."""

import os
from pathlib import Path
from typing import Tuple

import pytest

from aea.configurations.constants import PACKAGES, SKILLS
from aea.test_tools.test_cases import AEATestCaseEmpty

# trigger population of autonomy commands
import autonomy.cli.core  # noqa
from packages.valory import skills

from tests.conftest import ROOT_DIR


VALORY_SKILLS_PATH = Path(os.path.join(*skills.__package__.split("."))).absolute()
fsm_specifications = VALORY_SKILLS_PATH.glob("**/fsm_specification.yaml")


class TestScaffoldFSM(AEATestCaseEmpty):
    """Test `scaffold fsm` subcommand."""

    cli_options: Tuple[str, ...] = (
        "--registry-path",
        str(Path(ROOT_DIR) / Path(PACKAGES)),
        "scaffold",
        "fsm",
        "myskill",
        "--local",
        "--spec",
    )
    packages_dir: Path

    @pytest.mark.parametrize("fsm_spec_file", fsm_specifications)
    def test_run(self, fsm_spec_file: Path) -> None:
        """Test run."""
        self.set_agent_context(self.agent_name)
        path_to_spec_file = Path(ROOT_DIR) / fsm_spec_file
        args = [*self.cli_options, path_to_spec_file]
        result = self.run_cli_command(*args, cwd=self._get_cwd())
        assert result.exit_code == 0
