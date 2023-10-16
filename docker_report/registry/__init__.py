#!/usr/bin/env python3
# docker-report
# Copyright (C) 2019 Giuseppe Lavagetto, Tyler Cipriani
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

import json
import logging
import os

# Parts of the code below are taken from https://github.com/thcipriani/dockerregistry/
import re
from typing import Dict, List, Optional

import requests

from wmflib.requests import http_session

REGISTRY_PAGINATION_RE = re.compile(r"<([^>]*)>")

logger = logging.getLogger(__name__)


def requests_session(retries: int = 3, backoff: int = 10) -> requests.sessions.Session:
    """
    Returns a requests session with the designated retry strategy
    """
    # Use a 10 minute timeout by default.
    return http_session(name="registry", tries=retries, backoff=float(backoff), timeout=600)


class RegistryError(Exception):
    """Generic error from interactions with the registry."""


class Registry:
    """Base class for interactions with a docker registry"""

    def __init__(
        self, registry: str, logger: logging.Logger = logger, configfile: Optional[str] = None, protocol: str = "https"
    ):
        self.registry_url = registry
        self.logger = logger
        self.auth = self._get_auth_token(configfile)
        self.protocol = protocol

    def _get_auth_token(self, filename: Optional[str] = None) -> Optional[str]:
        if filename is None:
            filename = os.path.expanduser("~/.docker/config.json")
        try:
            with open(filename, "r") as fh:
                config = json.load(fh)
            auths = config["auths"]
            for reg in [self.registry_url, "https://{}".format(self.registry_url)]:
                if reg in auths:
                    return auths[reg]["auth"]
        except (KeyError, TypeError):
            # The config has nothing about our registry.
            pass
        except (FileNotFoundError, PermissionError):
            # No config file present, or it's not readable, we move on
            pass
        except json.decoder.JSONDecodeError:
            # Config file is malformed. log it and move on
            self.logger.warning("Could not read the settings file.")
        return None

    def _request(self, url_part: str, method: str = "GET", use_v2: bool = False) -> requests.Response:
        """Perform a request to the registry"""
        headers = {}
        if self.auth is not None:
            headers["Authorization"] = "Basic {}".format(self.auth)
        if use_v2:
            headers["Accept"] = "application/vnd.docker.distribution.manifest.v2+json"
        else:
            headers["Accept"] = "application/vnd.docker.distribution.manifest.v1+json"
        url = "{}://{}{}".format(self.protocol, self.registry_url, url_part)
        # We experience sporadic 504 responses from the registry, in those cases, retry
        # with an exponential backoff
        response = requests_session().request(method, url, headers=headers)
        response.raise_for_status()
        return response

    def _get_all_pages(self, url_part: str) -> List[Dict]:
        """Get all pages relative to a query."""
        responses = []
        try:
            while True:
                # If this fails, an exception is raised.
                self.logger.debug("Fetching: %s", url_part)
                resp = self._request(url_part)
                responses.append(resp.json())
                if "next" not in resp.links:
                    return responses
                # now let's inject the pagination in the query
                url_part = resp.links["next"]["url"]
        except requests.exceptions.HTTPError as e:
            # Workaround for https://github.com/docker/distribution/issues/2747
            # When using a swift backend, we get a 404 response if no tags are present
            if e.response.status_code == 404 and url_part.endswith("/tags/list"):
                self.logger.info(
                    "Got a 404 not found for %s: possibly a case of https://github.com/docker/distribution/issues/2747",
                    url_part,
                )
                return responses
            else:
                self.logger.exception("Error getting data from the registry")
                raise RegistryError(url_part)
        except requests.RequestException:
            self.logger.exception("Error getting data from the registry")
            raise RegistryError(url_part)

    def get_tags_for_image(self, image_name: str) -> List[str]:
        """Given an image name, get the corresponding tags"""
        self.logger.info("Fetching tags for %s", image_name)
        tags = []  # type: List[str]
        url = "/v2/{}/tags/list".format(image_name)
        for resp in self._get_all_pages(url):
            tags.extend(resp.get("tags", []))
        return tags
