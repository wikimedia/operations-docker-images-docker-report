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

# Parts of the code below are taken from https://github.com/thcipriani/dockerregistry/
import logging
import re
from datetime import datetime
from typing import Callable, Dict, List, Tuple

import json
import requests

REGISTRY_PAGINATION_RE = re.compile(r"<([^>]*)>")


# Functions that can act as a filter should accept the image name without tag as an input,
# and return True if the image is admissible.
ImageFilter = Callable[[str], bool]
# For tags, they should accept the image name and tag as arguments, in a tuple.
TagFilter = Callable[[Tuple[str, str]], bool]

logger = logging.getLogger(__name__)


class RegistryBrowserError(Exception):
    """Specific exception for the registry browser."""


class RegistryBrowser:
    """Allows to browse the catalog of a standar docker registry"""

    # TODO: Add type declarations once possible
    # Filters on the image names.
    name_filters = []
    # Filters on image full names.
    tag_filters = []

    def __init__(self, registry: str, logger: logging.Logger = logger):
        self.registry_url = registry
        self.logger = logger

    def _request(self, url_part: str) -> requests.Response:
        """Perform a request to the registry"""
        url = "https://{}{}".format(self.registry_url, url_part)
        response = requests.get(url)
        response.raise_for_status()
        return response

    def _get_all_pages(self, url_part: str) -> List[Dict]:
        """Get all pages relative to a query."""
        responses = []
        try:
            while True:
                # If this fails, an exception is raised.
                resp = self._request(url_part)
                next_link = resp.headers.get("link")
                responses.append(resp.json())
                if next_link is None:
                    break
                # now let's inject the pagination in the query
                url_part = REGISTRY_PAGINATION_RE.search(next_link).group(1)
        except requests.RequestException:
            self.logger.exception("Error getting data from the registry")
            raise RegistryBrowserError(url_part)
        return responses

    def _get_images_list(self) -> List[str]:
        """Gets a list of images, filtered via a list of functions."""
        logger.info("Fetching the image catalog for %s", self.registry_url)
        images = []

        def filterfn(names: List[str]) -> List[str]:
            for f in self.name_filters:
                names = list(filter(f, names))
            return names

        for resp in self._get_all_pages("/v2/_catalog"):
            images.extend(filterfn(resp.get("repositories")))

        return images

    def get_image_tags(self, sort=False) -> Dict[str, List[str]]:
        """Get a dict of image data in the form image_name: tags."""
        image_data = {}

        def filterfn(name: str, tags: List[str]) -> List[str]:
            args = [(name, t) for t in tags]
            for f in self.tag_filters:
                args = list(filter(f, args))
            return [el[1] for el in args]

        for image_name in self._get_images_list():
            self.logger.info("Fetching tags for %s", image_name)
            tags = []
            url = "/v2/{}/tags/list".format(image_name)
            for resp in self._get_all_pages(url):
                tags.extend(filterfn(image_name, resp.get("tags")))
            if sort:
                tags = self.sort_tags(image_name, tags)
            if tags:
                image_data[image_name] = tags

        return image_data

    def sort_tags(self, image: str, tags: str) -> List[str]:
        """
        Given a list of tags for an image, sort them from the oldest to
        the newest.
        """

        def get_tag_date(tag):
            try:
                data = self._get_all_pages("/v2/{}/manifests/{}?cache=busted".format(image, tag))[0]["history"][0][
                    "v1Compatibility"
                ]
                date_str, _ = json.loads(data)["created"].split(".")
                # TODO: fromisoformat
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                # We're going to ignore this later if we want
                self.logger.exception("Malformed response for %s:%s", image, tag)
                raise RegistryBrowserError("Could not sort {}".format(image))

        return sorted(tags, key=get_tag_date)
