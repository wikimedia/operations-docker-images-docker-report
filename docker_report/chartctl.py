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

"""
Helm Chart to Chartmuseum CLI

This program packages helm charts and pushes them to ChartMuseum.
"""
import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from docker_report import setup_logging, CustomFormatter
from docker_report.helm import HelmError, get_chart_name_version, package_chart
from docker_report.helm.chartmuseum import Chartmuseum, ChartmuseumError

logger = logging.getLogger("helm-chartctl")


def parse_args(args: Optional[List] = None) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    actions = parser.add_subparsers(dest="action", help="The action to perform")
    push = actions.add_parser("push")
    push.add_argument("path", metavar="PATH", type=Path, help="Path to the chart to package and push")
    walk = actions.add_parser("walk")
    walk.add_argument("path", metavar="PATH", type=Path, help="Path to walk for charts")

    cm = parser.add_argument_group()
    cm.add_argument(
        "repository",
        metavar="CHARTMUSEUM_REPOSITORY",
        help='The Chartmuseum repository to push the chart(s) to ("production", "testing", ...)',
    )
    cm.add_argument(
        "--cm-url",
        metavar="CHARTMUSEUM_URL",
        help="The URL of the Chartmuseum",
        default="https://helm-charts.wikimedia.org",
    )
    cm.add_argument(
        "--cm-user",
        metavar="CHARTMUSEUM_USER",
        default=os.environ.get("HELM_REPO_USERNAME"),
        help="Username for repository basic auth (env: $HELM_REPO_USERNAME)",
    )
    cm.add_argument(
        "--cm-password",
        metavar="CHARTMUSEUM_PASSWORD",
        default=os.environ.get("HELM_REPO_PASSWORD"),
        help="Password for chartmuseum basic auth (env: $HELM_REPO_PASSWORD)",
    )

    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument("--silent", "-s", action="store_true", default=False, help="don't log to console")
    options = parser.parse_args(args)

    return options


def push(cm: Chartmuseum, repository: str, path: Path):
    """Package and push a single chart"""
    chart_tgz = package_chart(path)
    res = cm.upload_chart(repository, chart_tgz)
    if res.status_code == 201:
        logger.info("Chart uploaded: %s", chart_tgz.name)
    elif res.status_code == 409:
        logger.info("Chart already exists in repository: %s", chart_tgz.name)
    shutil.rmtree(chart_tgz.parent)


def walk(cm: Chartmuseum, repository: str, path: Path):
    """Walk a directory for charts to package and push"""
    repo = cm.get_charts(repository)
    for chart_yaml in Path(path).rglob("Chart.yaml"):
        name, version = get_chart_name_version(chart_yaml)
        if not cm.is_version_in_repo(repo, name, version):
            # Package and push the new chart version
            push(cm, repository, chart_yaml.parent)
        else:
            logger.info("%s-%s already exists in repo: %s", name, version, repository)


def main(args=None):
    options = parse_args(args)
    setup_logging(logger, options, logging.ERROR)
    retcode = 0

    if options.action not in ("push", "walk"):
        logger.error("non-implemented action")
        retcode = 3

    try:
        cm = Chartmuseum(options.cm_url, options.cm_user, options.cm_password, logger=logger)
        if options.action == "push":
            push(cm, options.repository, options.path)
        elif options.action == "walk":
            walk(cm, options.repository, options.path)
    except ChartmuseumError:
        logger.exception("Error interacting with the repository")
        retcode = 2
    except HelmError:
        logger.exception("Error running helm")
        retcode = 2
    except Exception:
        logger.exception("Generic unhandled error")
        retcode = 1
    sys.exit(retcode)


if __name__ == "__main__":
    main(sys.argv[1:])
