#!/usr/bin/env python3
# docker-report
# Copyright (C) 2019 Giuseppe Lavagetto
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
import fnmatch
from typing import List, Tuple

import requests

from docker_report.registry import Registry


class RegistryOperations(Registry):
    """Class executing most common registry operations."""

    def _image_digest(self, name: str, tag: str) -> str:
        """Given an image name and tag, it returns the sha256 digest"""
        resp = self._request("/v2/{}/manifests/{}".format(name, tag), use_v2=True)
        return resp.headers.get("Docker-Content-Digest", "")

    def delete_image(self, name: str, tag_glob: str) -> Tuple[List[str], List[str], List[str]]:
        """Delete a specific tag (or tag glob) from an image.

        Two lists are returned, in a tuple: the list of all processed tags, and the list of tags
        that we failed to remove.
        """
        failed = []
        not_found = []
        # let's find all the tags corresponding to the glob
        tags = self.get_tags_for_image(name)
        selected_tags = fnmatch.filter(tags, tag_glob)
        for tag in selected_tags:
            try:
                digest = self._image_digest(name, tag)
                delete_url = "/v2/{}/manifests/{}".format(name, digest)
                self._request(delete_url, method="DELETE", use_v2=True)
            except requests.RequestException as e:
                if e.response is not None and e.response.status_code == 404:
                    not_found.append(tag)
                else:
                    self.logger.exception("Error deleting the image %s:%s from the registry", name, tag)
                    failed.append(tag)
        return (selected_tags, failed, not_found)
