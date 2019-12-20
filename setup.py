#!/usr/bin/env python
"""Package configuration."""
import sys

from setuptools import find_packages, setup

long_description = """
docker-report is a collection of utilities with minimal dependencies that allow
to report metadata about image contents to various services.

Right now the only implemented reporter is for debmonitor.
"""

if sys.version_info < (3, 5):
    sys.exit("docker-report requires Python 3.5 or later")

# Required dependencies
setup_requires = [
    "setuptools_scm>=1.17.0",
]

setup(
    author="Giuseppe Lavagetto",
    author_email="joe@wikimedia.org",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: System :: Systems Administration",
    ],
    description="Tools collection to report data about docker images to (for now) debmonitor",
    install_requires=["requests"],
    keywords=["docker-report", "debmonitor", "docker", "apt", "deb"],
    license="GPLv3+",
    long_description=long_description,
    name="docker_report",
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*"]),
    platforms=["GNU/Linux"],
    setup_requires=setup_requires,
    use_scm_version=True,
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "docker-report-debmonitor = docker_report.debmonitor:main",
            "docker-report = docker_report.reporter:main",
        ]
    },
)
