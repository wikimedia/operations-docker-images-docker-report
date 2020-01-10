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

import json

from datetime import datetime
from typing import Callable, Dict, List, Tuple

from docker_report.registry import Registry, RegistryError

# Functions that can act as a filter should accept the image name without tag as an input,
# and return True if the image is admissible.
ImageFilter = Callable[[str], bool]
# For tags, they should accept the image name and tag as arguments, in a tuple.
TagFilter = Callable[[Tuple[str, str]], bool]


class RegistryBrowserError(RegistryError):
    """Specific exception for the registry browser."""


class RegistryBrowser(Registry):
    """Allows to browse the catalog of a standard docker registry"""

    # Filters on the image names.
    name_filters = []  # type: List[ImageFilter]
    # Filters on image full names.
    tag_filters = []  # type: List[TagFilter]

    def _get_images_list(self) -> List[str]:
        """Gets a list of images, filtered via a list of functions."""
        self.logger.info("Fetching the image catalog for %s", self.registry_url)
        images = []

        for resp in self._get_all_pages("/v2/_catalog"):
            images_in_resp = resp.get("repositories", [])
            # Only select images that pass all the filters
            selected_images = [img for img in images_in_resp if all(fn(img) for fn in self.name_filters)]
            images.extend(selected_images)

        return images

    def get_image_tags(self, sort=False) -> Dict[str, List[str]]:
        """Get a dict of image data in the form image_name: tags."""
        image_data = {}
        for image_name in self._get_images_list():
            # Only select tags that pass all the filters
            tags = [
                tag
                for tag in self.get_tags_for_image(image_name)
                if all(fn((image_name, tag)) for fn in self.tag_filters)
            ]
            if sort:
                tags = self.sort_tags(image_name, tags)
            if tags:
                image_data[image_name] = tags

        return image_data

    def sort_tags(self, image: str, tags: List[str]) -> List[str]:
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
