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

import logging
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class ChartmuseumError(Exception):
    """Generic error from interactions with chartmuseum."""


class Chartmuseum:
    """Base class for interactions with a chartmuseum"""

    def __init__(
        self,
        chartmuseum_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        logger: logging.Logger = logger,
    ):
        self.chartmuseum_url = chartmuseum_url
        self.username = username
        self.password = password
        self.logger = logger

    def _request(self, url_part: str, method: str = "GET", **kwargs) -> requests.Response:
        url = "/".join((self.chartmuseum_url.rstrip("/"), "api", url_part))

        if self.username and self.password:
            auth = (self.username, self.password)
            kwargs["auth"] = auth

        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def get_charts(self, repository: str) -> Dict[str, List[Dict]]:
        """Fetch all charts and versions (index) for repository."""
        url_part = "/".join((repository, "charts"))
        try:
            return self._request(url_part).json()
        except requests.RequestException as e:
            self.logger.exception("Error getting data from chartmuseum: %s", e)
            raise ChartmuseumError(url_part)

    def get_chart_versions(self, repository: str, chart_name: str) -> List[Dict]:
        """Fetch all versions of a specific chart"""
        url_part = "/".join((repository, "charts", chart_name))
        try:
            return self._request(url_part).json()
        except requests.RequestException as e:
            self.logger.exception("Error getting data from chartmuseum: %s", e)
            raise ChartmuseumError(url_part)

    def upload_chart(self, repository, tgz_path: Path) -> requests.Response:
        """Upload chart tgz to the given repository."""
        url_part = "/".join((repository, "charts"))

        with tgz_path.open("rb") as chart_tgz:
            try:
                res = self._request(url_part, "POST", files={"chart": chart_tgz})
                return res
            except requests.exceptions.HTTPError as e:
                # Don't raise on 409
                if e.response.status_code == 409:
                    return e.response
                self.logger.exception("Error getting data from chartmuseum: %s", e)
                raise ChartmuseumError(url_part)
            except requests.RequestException as e:
                self.logger.exception("Error getting data from chartmuseum: %s", e)
                raise ChartmuseumError(url_part)

    @staticmethod
    def is_version_in_repo(repo: Dict[str, List[Dict]], name: str, version: str) -> bool:
        """Returns True if the chart name and version exists in the given repo, else False"""
        for cv in repo.get(name, []):
            if cv.get("version") == version:
                return True
        return False
