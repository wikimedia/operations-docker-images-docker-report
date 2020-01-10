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
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from docker_report import CustomFormatter, setup_logging
from docker_report.registry import RegistryError, browser, operations

logger = logging.getLogger("docker-registryctl")


def parse_args(args: Optional[List] = None) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    actions = parser.add_subparsers(dest="action", help="The action to perform")
    list_images = actions.add_parser("list-images")
    list_images.add_argument("--select", default="*", help="select a filter of images to show (glob syntax)")
    list_images.add_argument(
        "registry", metavar="REGISTRY_NAME", help="The url (without scheme) of the docker registry to scan"
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
    delete_tags.add_argument("--force", "-f", action="store_true", help="Do not ask for confirmation of the deletion.")
    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument("--silent", "-s", action="store_true", default=False, help="don't log to console")
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


def list_images(registry: str, filterglob: str):
    """Implementation of the list-images action"""
    rb = browser.RegistryBrowser(registry, logger=logger)

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


def list_tags(registry_name: str, name: str, filterglob: str):
    """Implementation of the list-tags action"""
    registry = operations.RegistryOperations(registry_name, logger=logger)
    print("-- ")
    print("{}:".format(name))
    for tag in fnmatch.filter(registry.get_tags_for_image(name), filterglob):
        if exclude_naked(("", tag)):
            print("  - {}".format(tag))


def delete_tags(registry_name: str, name: str, filterglob: str, force: bool = False):
    registry = operations.RegistryOperations(registry_name, logger=logger)
    if not force:
        to_remove = fnmatch.filter(registry.get_tags_for_image(name), filterglob)
        if len(to_remove) > 1:
            print("We're about to delete the following tags for image {}/{}:".format(registry, name))
            for tag in to_remove:
                print(tag)
            resp = input("Ok to proceed? (y/n)")
            if resp.lower() != "y":
                print("Aborting.")
                return
    selected, failed = registry.delete_image(name, filterglob)
    for tag in selected:
        fullname = "{}/{}:{}".format(registry, name, tag)
        if tag in failed:
            res = "FAIL"
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
            list_images(options.registry, options.select)
        elif options.action == "list-tags":
            list_tags(options.registry, options.image_name, options.select)
        elif options.action == "delete-tags":
            delete_tags(options.registry, options.image_name, options.select, options.force)
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
