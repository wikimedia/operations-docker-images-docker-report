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
from io import BytesIO
from tarfile import TarFile
from typing import List, Tuple

import docker  # type: ignore

from docker_report import CustomFormatter, setup_logging

logger = logging.getLogger(os.path.splitext(os.path.basename(sys.argv[0]))[0])


def parse_args(args: List[str]) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    parser.add_argument("image_name", metavar="IMAGE_NAME", help="The full name:tag of the image")
    parser.add_argument("report_dir", metavar="DIR", help="The directory where the report will be temporarily stored.")
    parser.add_argument("--keep", action="store_true", help="Keep the generated report even after submitting it.")
    parser.add_argument("--no-submit", "-n", action="store_true", help="Do not submit the report, just generate it.")
    parser.add_argument(
        "--minimum-debian-version", default=10, help="Minimum Debian major version that is considered supported."
    )
    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument("--silent", "-s", action="store_true", default=False, help="don't log to console")
    return parser.parse_args(args)


class DockerReportError(Exception):
    pass


class DockerReport:
    """Reports content of a docker image to debmonitor."""

    def __init__(self, image_name: str, report_dir: str, minimum_major: int):
        self.image = image_name
        self.report_dir = report_dir
        self.proxy = os.environ.get("http_proxy")
        self.file_basename = "{}.debmonitor.json".format(self.image.replace("/", "-"))
        self.filename = os.path.join(self.report_dir, self.file_basename)
        self.client = docker.from_env()
        self.minimum_version = (minimum_major, 0)

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

    def _extract_debian_version(self, dv_stream) -> Tuple[int, int]:
        """Extract the debian version number (tuple of two integers) from get_archive stream"""
        tar_bytes = BytesIO()
        try:
            for chunk in dv_stream:
                tar_bytes.write(chunk)
            tar_bytes.seek(0)
            dv_tar = TarFile(fileobj=tar_bytes)
            dv_bytes = dv_tar.extractfile("debian_version")
            if not dv_bytes:
                raise KeyError("debian_version is not a regular file")
            dv = dv_bytes.read().decode("utf-8")
        except (KeyError, OSError) as e:
            # Tarfile.extractfile raises KeyError in case the archive does not contain the requested file
            raise DockerReportError("Failed to extract debian_version from image") from e
        major, minor = map(int, (dv.split(".")))
        return (major, minor)

    def is_supported_image(self):
        """Check if self.image is a debian image which we can generate reports for."""

        try:
            # containers.create does not pull the image, so we need to pull manually
            self.client.images.pull(self.image)

            # The container is not actually run but docker daemon complains about missing command
            # sometimes (maybe if the image does not have an entrypoint defined.
            # To prevent this, "/false" is given as command.
            container = self.client.containers.create(self.image, command="/false")
        except Exception as e:
            logger.error("Failed to pull/create image %s: %s", self.image, e)
            return False

        try:
            dv_stream, _ = container.get_archive("/etc/debian_version")
            debian_version = self._extract_debian_version(dv_stream)
            logger.debug("Image %s is Debian version %s", self.image, debian_version)
        except docker.errors.NotFound:
            is_supported = False
        else:
            is_supported = debian_version >= self.minimum_version

        finally:
            container.remove(force=True)

        return is_supported

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
    report = DockerReport(options.image_name, options.report_dir, options.minimum_debian_version)
    if not report.is_supported_image():
        logger.warning("Unable to create a report for %s. The image is not supported.", options.image_name)
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
