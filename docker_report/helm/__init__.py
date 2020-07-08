#!/usr/bin/env python3
# docker-report
# Copyright (C) 2020 Janis Meybohm
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import shutil
import yaml
import logging
import subprocess
import tempfile
from typing import Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class HelmError(Exception):
    """Generic error from interactions with helm"""


class ChartError(Exception):
    """Generic error from parsing charts"""


def get_chart_name_version(chart_yaml: Path) -> Tuple[str, str]:
    """Return the version of the chart in chart_path"""
    try:
        with chart_yaml.open() as f:
            chart = yaml.safe_load(f)
        return chart["name"], chart["version"]
    except (TypeError, KeyError) as e:
        logger.exception("Error parsing Chart.yaml: %s", e)
        raise ChartError(chart_yaml)


def package_chart(chart_path: Path) -> Path:
    """Package the chart in chart_path, return the path to chart tgz"""
    output_dir = Path(tempfile.mkdtemp())
    cmd = ["helm", "package", "--save=false", "--destination", str(output_dir.absolute()), str(chart_path.absolute())]
    try:
        logger.info("Running helm package for: %s", chart_path.absolute())
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8").strip()
        logger.debug(out)
    except subprocess.CalledProcessError as e:
        logger.error("helm package exited with exit code %d. Output:", e.returncode)
        logger.error(e.stdout.decode("utf-8"))
        raise HelmError(chart_path)

    # Helm returns the generated file on success, parse it from the output
    # black will add a whitespace before ':', so it's impossinble to pass flake8 and black here
    output_file = Path(out[out.find(str(output_dir.absolute())) :])  # noqa: E203
    if not output_file.is_file():
        logger.error("No output file generated. Helm output was:")
        logger.error(out)
        shutil.rmtree(output_dir.absolute())
        raise HelmError(chart_path)

    return output_file
