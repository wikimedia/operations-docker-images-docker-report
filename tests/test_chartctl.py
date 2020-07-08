import os
from pathlib import Path
from unittest import mock

from docker_report import chartctl


def test_parse_args_push():
    options = chartctl.parse_args(["--silent", "push", "/tmp/foo", "nowhere"])
    assert options.silent is True
    assert options.action == "push"
    assert options.repository == "nowhere"
    assert options.path == Path("/tmp/foo")
    assert options.cm_url == "https://helm-charts.wikimedia.org"


def test_parse_args_walk():
    options = chartctl.parse_args(["--debug", "--cm-url", "https://httpbin.org/foo", "walk", "/tmp/foo", "nowhere"])
    assert options.silent is False
    assert options.debug is True
    assert options.action == "walk"
    assert options.repository == "nowhere"
    assert options.path == Path("/tmp/foo")
    assert options.cm_url == "https://httpbin.org/foo"


def test_parse_args_auth():
    options = chartctl.parse_args(["--cm-user", "hru", "--cm-password", "hrp", "push", "/tmp/foo", "nowhere"])
    assert options.cm_user == "hru"
    assert options.cm_password == "hrp"


@mock.patch.dict(os.environ, {"HELM_REPO_USERNAME": "hru", "HELM_REPO_PASSWORD": "hrp"})
def test_parse_args_auth_environment():
    options = chartctl.parse_args(["push", "/tmp/foo", "nowhere"])
    assert options.cm_user == "hru"
    assert options.cm_password == "hrp"
