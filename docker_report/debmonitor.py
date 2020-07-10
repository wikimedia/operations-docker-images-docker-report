#!/usr/bin/env python3
# docker-report-debmonitor
# Copyright (C) 2019 Giuseppe Lavagetto
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
docker-report-debmonitor - Submits data about packages present in a docker image
    to the debmonitor server.

Takes 2 arguments - the image full name and the directory where to store the
report.
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys
import docker  # type: ignore
from typing import List

from docker_report import CustomFormatter, setup_logging

logger = logging.getLogger(os.path.splitext(os.path.basename(sys.argv[0]))[0])


def parse_args(args: List[str]) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    parser.add_argument("image_name", metavar="IMAGE_NAME", help="The full name:tag of the image")
    parser.add_argument("report_dir", metavar="DIR", help="The directory where the report will be temporarily stored.")
    parser.add_argument("--keep", action="store_true", help="Keep the generated report even after submitting it.")
    parser.add_argument("--no-submit", "-n", action="store_true", help="Do not submit the report, just generate it.")
    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument("--silent", "-s", action="store_true", default=False, help="don't log to console")
    return parser.parse_args(args)


class DockerReportError(Exception):
    pass


class DockerReport:
    """Reports content of a docker image to debmonitor."""

    def __init__(self, image_name: str, report_dir: str):
        self.image = image_name
        self.report_dir = report_dir
        self.proxy = os.environ.get("http_proxy")
        self.file_basename = "{}.debmonitor.json".format(self.image.replace("/", "-"))
        self.filename = os.path.join(self.report_dir, self.file_basename)
        self.client = docker.from_env()

    @staticmethod
    def _cmd_run(cmd: List) -> bytes:
        # TODO: use subprocess.run when we're past python 3.5
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def _cmd(self, label: str, cmd: List) -> bytes:
        """Simplistic wrapper around subprocess."""
        try:
            logger.info("Running: %s", label.lower())
            out = self._cmd_run(cmd)
            logger.debug(out.decode("utf-8"))
            return out
        except subprocess.CalledProcessError as e:
            logger.error("%s exited with exit code %d. Output:", label, e.returncode)
            logger.error(e.stdout.decode("utf-8"))
            raise DockerReportError(label)

    def _docker_cmd(self) -> List[str]:
        """Generates the docker command to run."""
        container_filename = os.path.join("/mnt", self.file_basename)
        if self.proxy is not None:
            logger.debug("proxy set to: %s", self.proxy)
            proxy_inject = "echo 'Acquire::http::Proxy \"{}\";' > /etc/apt/apt.conf.d/80_proxy".format(self.proxy)
        else:
            proxy_inject = "echo 'No proxy configured'"

        # This is the command to run inside the docker image
        bash_incantation = [
            proxy_inject,
            "apt-get update",
            "apt-get install --yes --no-install-recommends debmonitor-client",
            "/usr/bin/debmonitor-client -n -i '{img}' > '{fname}'".format(img=self.image, fname=container_filename),
        ]

        return [
            "docker",
            "run",
            "--user",
            "root",
            "--rm",
            "-v",
            "{}:/mnt:rw".format(self.report_dir),
            "--entrypoint",
            "/bin/bash",
            "{}".format(self.image),
            "-c",
            " && ".join(bash_incantation),
        ]

    def is_debian_image(self):
        """Check if self.image is a debian image we can generate reports for."""

        # The container is not actually run but docker daemon complains about missing command
        # sometimes (maybe if the image does not have an entrypoint defined.
        # To prevent this, "/false" is given as command.
        container = self.client.containers.create(self.image, command="/false")

        try:
            _ = container.get_archive("/etc/debian_version")
        except docker.errors.NotFound:
            is_debian = False
        else:
            is_debian = True
        finally:
            container.remove(force=True)

        return is_debian

    def generate_report(self):
        """Generate the report."""
        self._cmd("Report generation", self._docker_cmd())

    def submit_report(self):
        """Submit the report"""
        self._cmd("Submit report", ["debmonitor-client-unpriv", "-f", self.filename])

    def prune_image(self):
        """Remove the image"""
        self._cmd("Image pruning", ["docker", "rmi", "-f", self.image])


def main(args=None):
    exitcode = 0
    options = parse_args(args)
    setup_logging(logger, options)
    report = DockerReport(options.image_name, options.report_dir)
    if not report.is_debian_image():
        logger.warning("Unable to create a report for non debian images")
        sys.exit(exitcode)

    try:
        report.generate_report()
        if not options.no_submit:
            report.submit_report()
            logger.info("Report submitted")
    except DockerReportError:
        exitcode = 1
    except Exception:
        logger.exception("An unexpected error occurred")
        exitcode = 2
    finally:
        if not options.no_submit and not options.keep:
            shutil.rmtree(report.filename, ignore_errors=True)
        elif exitcode == 0:
            logger.info("Report saved at %s", report.filename)
        sys.exit(exitcode)
