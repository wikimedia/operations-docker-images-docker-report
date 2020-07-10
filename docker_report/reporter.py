#!/usr/bin/env python3
# docker-report
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
Docker reporter utility.

This program browses the content of a docker registry, filters out images and tags based on rules (see below),
and performs some actions. Right now, it only reports the installed packages to debmonitor.

It's important to note that for each image, only the *last* tag will be considered and reported upon, with the idea
that older versions should be by now unused.

Image selection filtering
-------------------------

You can use the command-line switches --exclude-namespaces (to pick namespaces to exclude), exclude tags based on a
regexp with --exclude-tag-regexp.

This basic filtering is however quite limited - there is the possibility to declare more complex filters in an ini file
that you can pass to docker-report by declaring --filter-file as an option.

The format of this file is as follows:

[image_rule_name]
name = <filter_rule>
action = exclude|include

[tag_rule_name]
name_match = <filter_rule> # optional
tag = <filter_rule>
action = exclude|include

Every rule MUST have at least a name or a tag. If only the name is specified, the filter will be applied to the image
base name. If only tag is specified, likewise, the filter will only happen on the tag of the image. If a tag and a
name_match stanza are specified, the name will be used to apply the tag filter only to images that correspond to it.

Finally, the action stanza (action = include|exclude) tells if the filter is inclusive (so: only include images / tags
that match it) or exclusive. It's important to note that a filter that specifies both a name_match and a tag
will apply to selecting the tags only to the images that match.

Filter rules are in one of the following formats:

* regex:<some-regex-here> A regular expression to test the entity against
* contains:<some-text-here> Checks if the given substring is present in the entity
"""
import argparse
import configparser
import grp
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Generator, List, Optional, Tuple

from docker_report import CustomFormatter, setup_logging
from docker_report.debmonitor import DockerReport, DockerReportError
from docker_report.registry import RegistryError
from docker_report.registry.browser import ImageFilter, RegistryBrowser, TagFilter

logger = logging.getLogger("docker-report")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=CustomFormatter)
    parser.add_argument(
        "registry", metavar="REGISTRY_NAME", help="The url (without scheme) of the docker registry to scan"
    )
    parser.add_argument("--exclude-namespaces", nargs="*", help="namespaces to exclude from the run")
    parser.add_argument("--no-exclude-naked", action="store_true", help="include also 'naked' tags (i.e. sha1s)")
    parser.add_argument("--exclude-tag-regexp", nargs="*", help="regexes for excluding tags")
    parser.add_argument("--filter-file", help="file containing filter rules")
    parser.add_argument("--keep", action="store_true", help="keep docker images after downloading them.")
    log = parser.add_mutually_exclusive_group()
    log.add_argument("--debug", "-d", action="store_true", default=False, help="enable debugging")
    log.add_argument("--silent", "-s", action="store_true", default=False, help="don't log to console")
    parser.add_argument("--concurrency", type=int, default=1, help="Maximum concurrency in running debmonitor reports.")
    return parser.parse_args(args)


def setup_browser(options: argparse.Namespace) -> RegistryBrowser:
    """Sets up the repo browser with all filters."""
    br = RegistryBrowser(options.registry, logger=logger)
    if options.exclude_namespaces:

        def exclude_namespaces(name):
            for ns in options.exclude_namespaces:
                if name.startswith(ns):
                    return False
            return True

        br.name_filters.append(exclude_namespaces)

    if not options.no_exclude_naked:
        sha1regex = re.compile(r"^[a-zA-Z0-9]{40}$")

        def exclude_naked(data):
            return not sha1regex.search(data[1])

        br.tag_filters.append(exclude_naked)

    if options.exclude_tag_regexp:
        regexes = [re.compile(r) for r in options.exclude_tag_regexp]

        def exclude_tag_regexp(data):
            for r in regexes:
                if r.search(data[1]):
                    return False
            return True

        br.tag_filters.append(exclude_tag_regexp)

    if options.filter_file:
        img_filters, tag_filters = _filters_from_file(options.filter_file)
        br.name_filters.extend(img_filters)
        br.tag_filters.extend(tag_filters)
    return br


def _filters_from_file(filename: str) -> Tuple[List[ImageFilter], List[TagFilter]]:
    logger.debug("Processing file %s", filename)
    image_filters = []
    tag_filters = []
    config = configparser.ConfigParser()
    config.read(filename)
    for name, rules in config.items():
        logger.debug("Loading rule %s", name)
        if "tag" in rules:
            tag_rule = _tag(rules)
            if tag_rule is not None:
                tag_filters.append(tag_rule)
        elif "name" in rules:
            img_rule = _image(rules)
            if img_rule is not None:
                image_filters.append(img_rule)
        else:
            logger.warning("Discarding rule %s - it contains no conditions", name)
    return (image_filters, tag_filters)


def isTrue(x: str) -> bool:
    """Null rule."""
    return True


def _tag(rules: configparser.SectionProxy) -> Optional[TagFilter]:
    try:
        name_cond = _parse_rule(rules["name_match"])
    except ValueError as e:
        logger.warning("Error while evaluating tag rule - invalid name_match: %s", e)
        # Invalid rule for name match - we *ignore* the whole rule.
        return None
    except KeyError:
        # No image name match
        name_cond = isTrue

    try:
        tag_cond = _parse_rule(rules["tag"])
    except ValueError as e:
        # We ignore invalid tag rules.
        logger.warning("Error while evaluating tag rule - invalid tag: %s", e)
        return None

    def _condition(data):
        # If the name condition doesn't match, we do not apply filtering logic
        if not name_cond(data[0]):
            return True

        action = rules.get("action", "include")
        if action == "exclude":
            return not tag_cond(data[1])
        else:
            return tag_cond(data[1])

    return _condition


def _parse_rule(rule: str) -> ImageFilter:
    if rule.startswith("regex:"):
        regex = re.compile(rule[6:])
        return lambda x: bool(regex.search(x))
    elif rule.startswith("contains:"):
        return lambda x: (rule[9:] in x)
    else:
        # Invalid rule. We ignore it in the callers
        raise ValueError("Unrecognized rule %s", rule)


def _image(rules: configparser.SectionProxy) -> Optional[ImageFilter]:
    try:
        name_cond = _parse_rule(rules["name"])
    except ValueError as e:
        logger.warning(e)
        # Invalid rule - we ignore it
        return None
    if rules.get("action", "include") == "exclude":
        return lambda name: not name_cond(name)
    else:
        return name_cond


def _tempdir() -> str:
    """Create a tempdir, make it writable to debmonitor."""
    tempdir = tempfile.mkdtemp("-docker-report")
    group = grp.getgrnam("debmonitor").gr_gid
    os.chown(tempdir, os.getuid(), group)
    os.chmod(tempdir, stat.S_IRWXU | stat.S_IRWXG)
    return tempdir


class Reporter:
    def __init__(self, browser: RegistryBrowser, tempdir: str, keep_images: bool):
        self._browser = browser
        self.exitcode = 0
        self._tempdir = tempdir
        self._prune_images = not keep_images
        self._failed = []  # type: List[str]
        self._success = []  # type: List[str]

    def run_report(self, image: str):
        """Run the report on one image"""
        logger.info("Building debmonitor report for %s", image)
        try:
            debmonitor = DockerReport(image, self._tempdir)
            if not debmonitor.is_debian_image():
                logger.warning("Unable to create a report for non debian images")
                return

            debmonitor.generate_report()
            debmonitor.submit_report()
            if self._prune_images:
                debmonitor.prune_image()
            self._success.append(image)
        except DockerReportError:
            self._failed.append(image)
            logger.error("Debmonitor report for image %s failed", image)
            self.exitcode = 3

    def _image_full_name(self, name: str, tag: str) -> str:
        """Fully qualified name of the image"""
        return "{}/{}:{}".format(self._browser.registry_url, name, tag)

    def get_images(self) -> Generator[str, None, None]:
        """Gets all the image names, as a generator."""
        try:
            for name, tags in self._browser.get_image_tags(sort=True).items():
                tag = tags[-1]
                yield self._image_full_name(name, tag)
        except RegistryError:
            self.exitcode = 2

    def pprint(self):
        """Pretty-prints results"""
        if not self._failed:
            print("All images submitted correctly!")
        print("")
        print("Detailer results:")
        for img in self._success:
            print("%-70s[OK]" % img)
        for img in self._failed:
            print("%-68s[FAIL]" % img)


def main(args=None):
    options = parse_args(args)
    setup_logging(logger, options)
    try:
        tempdir = _tempdir()
        registry = setup_browser(options)
        report = Reporter(registry, tempdir, options.keep)
        with ThreadPoolExecutor(max_workers=options.concurrency) as executor:
            for _ in executor.map(report.run_report, report.get_images()):
                # Do nothing here, just catch exceptions.
                pass
        report.pprint()
    except Exception:
        logger.exception("Unexpected error during execution")
        report.exitcode = 1
    finally:
        shutil.rmtree(tempdir)

    sys.exit(report.exitcode)
