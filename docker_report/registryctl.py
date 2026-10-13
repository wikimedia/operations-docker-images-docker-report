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
"""
Docker registry management utility.

This program allows to perform a series of actions on a registry:

* List the images present on the registry
* List tags for a given image
* Delete a specific version of an image.
"""

import argparse
import fnmatch
import logging
import re
import sys
from datetime import date, datetime
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse

from docker_report import CustomFormatter, setup_logging
from docker_report.registry import RegistryError, browser, operations

logger = logging.getLogger("docker-registryctl")


# A date embedded in a tag, as YYYY-MM-DD, YYYYMMDD or YYYY_MM_DD. The lookaround
# assertions avoid picking up a slice of a longer run of digits (say a build number).
DATE_IN_TAG_REGEX = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_]?(\d{2})[-_]?(\d{2})(?!\d)")

# The formats accepted for the --older-than argument.
DATE_INPUT_FORMATS = ("%Y-%m-%d", "%Y%m%d")


def parse_date(datestr: str) -> date:
    """Parse a date provided on the command line."""
    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(datestr, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("'{}' is not a valid date (expected YYYY-MM-DD or YYYYMMDD)".format(datestr))


def date_from_tag(tag: str) -> Optional[date]:
    """Extract the date embedded in a tag, or None if the tag doesn't contain one."""
    for match in DATE_IN_TAG_REGEX.finditer(tag):
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            # Looked like a date but isn't one (say, month 13); keep looking.
            continue
    return None


class OlderThanFilter:
    """Tag filter selecting the tags whose embedded date is strictly older than a limit.

    Tags that don't contain a recognizable date are never selected. The tags that get
    rejected are recorded, so that the caller can explain why nothing was selected.
    They're kept in sets as the same filter is applied more than once per run.
    """

    def __init__(self, limit: date):
        self.limit = limit
        self.undated: Set[str] = set()
        self.too_recent: Set[str] = set()

    def __call__(self, tag: str) -> bool:
        tag_date = date_from_tag(tag)
        if tag_date is None:
            if tag not in self.undated:
                logger.debug("Skipping tag '%s': no date found in it", tag)
                self.undated.add(tag)
            return False
        if tag_date >= self.limit:
            self.too_recent.add(tag)
            return False
        return True

    @property
    def rejected(self) -> int:
        """The number of distinct tags this filter has rejected."""
        return len(self.undated) + len(self.too_recent)

    def explain(self) -> str:
        """A human-readable summary of what was rejected and why."""
        reasons = []
        if self.undated:
            reasons.append("{} with no date in the tag".format(len(self.undated)))
        if self.too_recent:
            reasons.append("{} not old enough".format(len(self.too_recent)))
        return ", ".join(reasons)


def parse_args(args: Optional[List] = None) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    actions = parser.add_subparsers(dest="action", help="The action to perform")
    list_images = actions.add_parser("list-images")
    list_images.add_argument("--select", default="*", help="select a filter of images to show (glob syntax)")
    list_images.add_argument(
        "registry",
        metavar="REGISTRY_NAME",
        help="The url (without scheme) of the docker registry to scan",
    )
    list_tags = actions.add_parser("list-tags")
    list_tags.add_argument(
        "image",
        metavar="IMAGE_GLOB",
        help="The name (including the registry url) of the image. "
        "The tag can be indicated as a glob pattern, or not at all.",
    )
    delete_tags = actions.add_parser("delete-tags")
    delete_tags.add_argument(
        "image",
        metavar="IMAGE_GLOB",
        help="The name (including the registry url) of the image. "
        "The tags to remove can be indicated as a glob pattern, or not at all.",
    )
    delete_tags.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Do not ask for confirmation of the deletion.",
    )
    delete_tags.add_argument(
        "--older-than",
        metavar="DATE",
        type=parse_date,
        default=None,
        help="Only delete tags that contain a date (YYYY-MM-DD, YYYYMMDD or YYYY_MM_DD) "
        "strictly older than DATE, expressed as YYYY-MM-DD or YYYYMMDD. "
        "Tags with no recognizable date are never deleted. "
        "Please note: special tags like latest/stable/etc.. that point to the same manifest "
        "that is going to be deleted will also be deleted.",
    )
    parser.add_argument(
        "--credentials",
        "-c",
        metavar="CONFIG_JSON",
        default=None,
        help="path to a docker credentials config.json (default: ~/.docker/config.json)",
    )
    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument(
        "--silent",
        "-s",
        action="store_true",
        default=False,
        help="don't log to console",
    )
    options = parser.parse_args(args)
    # Separate registry, image name and tag glob
    if options.action in ["list-tags", "delete-tags"]:
        url = "https://{}".format(options.image)
        parsed = urlparse(url)
        options.registry = parsed.netloc
        if ":" in parsed.path:
            img, options.select = parsed.path.split(":")
            options.image_name = img[1:]
        else:
            options.image_name = parsed.path[1:]
            options.select = "*"
    return options


SHA1REGEX = re.compile(r"^[a-zA-Z0-9]{40}$")


def exclude_naked(img_tag: Tuple[str, str]) -> bool:
    return not SHA1REGEX.search(img_tag[1])


def list_images(registry: str, filterglob: str, configfile: Optional[str] = None):
    """Implementation of the list-images action"""
    rb = browser.RegistryBrowser(registry, logger=logger, configfile=configfile)

    def filter_glob(name):
        return fnmatch.fnmatch(name, filterglob)

    rb.name_filters.append(filter_glob)
    rb.tag_filters.append(exclude_naked)

    # We're trying to avoid using pyyaml here. Maybe not worth it?
    print("-- ")
    for name, tags in rb.get_image_tags(sort=True).items():
        print("{}:".format(name))
        for tag in tags:
            print("  - {}".format(tag))


def list_tags(registry_name: str, name: str, filterglob: str, configfile: Optional[str] = None):
    """Implementation of the list-tags action"""
    registry = operations.RegistryOperations(registry_name, logger=logger, configfile=configfile)
    print("-- ")
    print("{}:".format(name))
    for tag in fnmatch.filter(registry.get_tags_for_image(name), filterglob):
        if exclude_naked(("", tag)):
            print("  - {}".format(tag))


def delete_tags(
    registry_name: str,
    name: str,
    filterglob: str,
    force: bool = False,
    configfile: Optional[str] = None,
    older_than: Optional[date] = None,
):
    registry = operations.RegistryOperations(registry_name, logger=logger, configfile=configfile)
    tag_filter = None if older_than is None else OlderThanFilter(older_than)
    if not force:
        to_remove = fnmatch.filter(registry.get_tags_for_image(name), filterglob)
        if tag_filter is not None:
            to_remove = [tag for tag in to_remove if tag_filter(tag)]
        if len(to_remove) > 1:
            print("We're about to delete the following tags for image {}/{}:".format(registry_name, name))
            for tag in to_remove:
                print(tag)
            resp = input("Ok to proceed? (y/n)")
            if resp.lower() != "y":
                print("Aborting.")
                return
    selected, failed, not_found = registry.delete_image(name, filterglob, tag_filter)
    if tag_filter is not None and not selected and tag_filter.rejected:
        # The glob matched something, but the date filter rejected all of it. Say so,
        # otherwise the run looks identical to one that matched no tags at all.
        print(
            "No tags for image {}/{} matching '{}' are older than {}: skipped {}.".format(
                registry_name, name, filterglob, tag_filter.limit.isoformat(), tag_filter.explain()
            )
        )
    for tag in selected:
        fullname = "{}/{}:{}".format(registry_name, name, tag)
        if tag in failed:
            res = "FAIL"
        elif tag in not_found:
            res = "GONE"
        else:
            res = "DONE"
        print("{0:74s}[{1}]".format(fullname, res))
    if failed and not force:
        raise RegistryError("Could not remove the following tags for image '{}': {}".format(name, ",".join(failed)))


def main(args=None):
    options = parse_args(args)
    setup_logging(logger, options, logging.ERROR)
    retcode = 0
    try:
        if options.action == "list-images":
            list_images(options.registry, options.select, configfile=options.credentials)
        elif options.action == "list-tags":
            list_tags(options.registry, options.image_name, options.select, configfile=options.credentials)
        elif options.action == "delete-tags":
            delete_tags(
                options.registry,
                options.image_name,
                options.select,
                options.force,
                configfile=options.credentials,
                older_than=options.older_than,
            )
        else:
            logger.error("non-implemented action")
            retcode = 3
    except RegistryError:
        logger.exception("Error interacting with the registry")
        retcode = 2
    except Exception:
        logger.exception("Generic unhandled error")
        retcode = 1
    sys.exit(retcode)
