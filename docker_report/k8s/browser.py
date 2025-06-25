#!/usr/bin/env python3
# docker-report
# Copyright (C) 2025 Luca Toscano
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
# Parts of the code below are taken from https://github.com/thcipriani/dockerregistry/

import logging
from collections import Counter, defaultdict
from configparser import ConfigParser
from kubernetes import client, config
from typing import Any, Generator, Optional

from wmflib.requests import http_session

from docker_report.browser import Browser


logger = logging.getLogger(__name__)
DEBMONITOR_CONFIG_FILE = "/etc/debmonitor.conf"


class KubernetesBrowserError(Exception):
    """Generic error from interactions with the Kubernetes API."""


class DebmonitorAPIError(Exception):
    """Generic error from interactions with the Debmonitor API."""


class DebmonitorAPI:
    """Retrieve info to be able to contact the Debmonitor API"""

    def __init__(self):
        debmonitor_configuration = ConfigParser()
        debmonitor_configuration.read(DEBMONITOR_CONFIG_FILE)
        debmonitor_config = debmonitor_configuration.defaults()
        debmonitor_cert: Any = None
        if debmonitor_config.get("key") is not None and debmonitor_config.get("cert") is not None:
            debmonitor_cert = (debmonitor_config["cert"], debmonitor_config["key"])
        elif debmonitor_config.get("cert") is not None:
            debmonitor_cert = debmonitor_config["cert"]

        self.servers: list[str] = debmonitor_config["server"].split(",")
        self.client_tls_config = {"cert": debmonitor_cert, "verify": True}
        self.short_timeout_session = http_session(name="docker-report", tries=3, backoff=2.0, timeout=10)
        self.long_timeout_session = http_session(name="docker-report", tries=3, backoff=10.0, timeout=120)
        self.short_timeout_session.headers.update({"Accept": "application/json"})
        self.long_timeout_session.headers.update({"Accept": "application/json"})

    def is_image_in_debmonitor(self, image_name: str):
        known: int = 0
        for server in self.servers:
            response = self.short_timeout_session.get(f"https://{server}/images/{image_name}", **self.client_tls_config)
            if response.status_code == 200:
                known += 1
        if known == len(self.servers):
            return True
        else:
            return False

    def send_k8s_report(self, report):
        """Submit the report to Debmonitor."""
        for server in self.servers:
            logger.info("Sending a report to %s", server)
            response = self.long_timeout_session.post(
                f"https://{server}/kubernetes/update", json=report, **self.client_tls_config
            )

            if response.status_code not in [201, 202]:
                raise DebmonitorAPIError(
                    f"Failed to update Debmonitor server {server}, got {response.status_code}:\n{response.text}"
                )
            elif response.status_code == 202:
                payload = response.json()
                logger.error(
                    "Partial update, some images have been rejected!\n\nImages that were rejected "
                    "because unknown to Debmonitor:\n%s\n\n"
                    "Images that failed to be persisted in Debmonitor:\n%s",
                    payload["missing"],
                    payload["errors"],
                )
            elif response.status_code == 201:
                logger.info("The report has been delivered to %s.", server)


class KubernetesBrowser(Browser):
    def __init__(self, cluster_name: str, kubeconfig_path: Optional[str] = None):
        config.load_kube_config(config_file=kubeconfig_path)
        self.v1_api = client.CoreV1Api()
        self.cluster_name = cluster_name
        self._running_images: dict = {}  # cache the running images to avoid race conditions
        self.debmonitor_api = DebmonitorAPI()

    def get_images(self) -> Generator[str, None, None]:
        """Gets all the image names, as a generator."""
        for image_name in self.get_running_images()["images"].keys():
            if self.debmonitor_api.is_image_in_debmonitor(image_name):
                logger.debug("Skipping push of image %s to Debmonitor, already present", image_name)
                continue
            yield image_name

    def get_running_images(self) -> dict:
        if not self._running_images:
            try:
                self._running_images = self._get_running_images()
            except Exception as e:
                raise KubernetesBrowserError(
                    f"Failed to get the list of running images on cluster {self.cluster_name}"
                ) from e

        return self._running_images

    def _get_running_images(self) -> dict:
        ret = self.v1_api.list_pod_for_all_namespaces(watch=False)
        images: defaultdict[str, Counter] = defaultdict(Counter)

        for pod in ret.items:
            namespace = pod.metadata.namespace
            if not pod.status.container_statuses:
                continue

            for container in pod.status.container_statuses:
                # If an image is deployed with its sha256-digest,
                # we'll get something like the following from the Kube API:
                # image = 'sha256:123456...'
                # image_id = 'docker-registry.wikimedia.org/something@sha256:123456...'
                # We chose to use image_id as substitute of the more canonical
                # image:tag combination.
                if "sha256:" in container.image:
                    image_ref = container.image_id
                else:
                    image_ref = container.image

                images[image_ref][namespace] += 1

        return {"cluster": self.cluster_name, "images": images}

    def submit_report(self):
        self.debmonitor_api.send_k8s_report(self.get_running_images())
