#!/usr/bin/env python
"""Package configuration."""
import sys

from setuptools import find_packages, setup

long_description = """
docker-report is a collection of utilities with minimal dependencies that allow
to report metadata about image contents to various services.

Right now the only implemented reporter is for debmonitor.
"""

if sys.version_info < (3, 6):
    sys.exit("docker-report requires Python 3.6 or later")

# Required dependencies
setup_requires = ["setuptools_scm>=1.17.0"]
install_requires = ["requests", "pyyaml", "docker", "wmflib"]

setup(
    author="Giuseppe Lavagetto",
    author_email="joe@wikimedia.org",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: System :: Systems Administration",
    ],
    description="Tools collection to report data about docker images to (for now) debmonitor",
    install_requires=install_requires,
    keywords=["docker-report", "debmonitor", "docker", "apt", "deb"],
    license="GPLv3+",
    long_description=long_description,
    name="docker_report",
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*"]),
    platforms=["GNU/Linux"],
    setup_requires=setup_requires,
    # In order to support tags of the form upstream/1.2.3 modify the default DEFAULT_TAG_REGEX
    # modifying (?:[\w-]+-)? with (?:[\w-]+[-/])?
    # See also: https://github.com/pypa/setuptools_scm/blob/main/src/setuptools_scm/config.py#L8
    use_scm_version={"tag_regex": r"^(?:[\w-]+[-/])?(?P<version>[vV]?\d+(?:\.\d+){0,2}[^\+]*)(?:\+.*)?$"},
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "docker-report-debmonitor = docker_report.debmonitor:main",
            "docker-report = docker_report.reporter:main",
            "docker-registryctl = docker_report.registryctl:main",
            "helm-chartctl = docker_report.chartctl:main",
        ]
    },
)
