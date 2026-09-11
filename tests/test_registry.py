import json
import os
from unittest import mock

import pytest
import requests_mock

from docker_report.registry import Registry, RegistryError


@pytest.fixture
def registry() -> Registry:
    r = Registry("httpbin.org")
    return r


def test_initialize():
    """Test basic initialization - no auth"""
    with mock.patch("docker_report.registry.open", mock.mock_open(read_data="{}")):
        rb = Registry("httpbin.org")
    assert rb.registry_url == "httpbin.org"
    assert rb.auth is None


def test_missing_default_config_file():
    """A missing default config file is not an error: we just go on anonymously."""
    with mock.patch("docker_report.registry.open") as m:
        m.side_effect = FileNotFoundError(2, "No such file or directory")
        rb = Registry("httpbin.org")
    assert rb.auth is None


@pytest.mark.parametrize(
    "error", [FileNotFoundError(2, "No such file or directory"), PermissionError(13, "Permission denied")]
)
def test_explicit_config_file_unreadable(error):
    """An unreadable config file the user explicitly asked for is fatal."""
    with mock.patch("docker_report.registry.open") as m:
        m.side_effect = error
        with pytest.raises(RegistryError, match="Could not use the credentials file 'test'"):
            Registry("httpbin.org", configfile="test")


def test_explicit_config_file_malformed():
    """A malformed config file the user explicitly asked for is fatal."""
    with mock.patch("json.load") as jl:
        jl.side_effect = json.decoder.JSONDecodeError("test", doc="some error", pos=10)
        with pytest.raises(RegistryError, match="not valid JSON"):
            Registry("httpbin.org", configfile=os.path.abspath(__file__))


def test_explicit_config_file_no_credentials():
    """A config file without credentials for our registry is fatal too, if explicit."""
    with mock.patch("json.load") as jl:
        jl.return_value = {"auths": {"example.org": {"auth": "abcd"}}}
        with pytest.raises(RegistryError, match="no credentials for registry 'httpbin.org'"):
            Registry("httpbin.org", configfile=os.path.abspath(__file__))


def test_explicit_config_file_no_auths_section():
    """Ditto for a config file with no 'auths' section at all."""
    with mock.patch("json.load") as jl:
        jl.return_value = {}
        with pytest.raises(RegistryError, match="no 'auths' entry for registry 'httpbin.org'"):
            Registry("httpbin.org", configfile=os.path.abspath(__file__))


@pytest.mark.parametrize("authkey", ["httpbin.org", "https://httpbin.org"])
def test_auth_token(authkey):
    with mock.patch("json.load") as jl:
        jl.return_value = {"auths": {authkey: {"auth": "abcd"}}}
        # This is a trick to ensure the file is present and readable.
        filename = os.path.abspath(__file__)
        r = Registry("httpbin.org", configfile=filename)
        assert r.auth == "abcd"


def test_auth_token_invalid(registry):
    """A malformed default config file is logged, but not fatal."""
    with mock.patch("json.load") as jl:
        jl.side_effect = json.decoder.JSONDecodeError("test", doc="some error", pos=10)
        with mock.patch("docker_report.registry.open", mock.mock_open(read_data="not json")):
            assert registry._get_auth_token() is None


def test_default_config_file():
    with mock.patch("docker_report.registry.open", mock.mock_open(read_data="{}")) as m:
        Registry("httpbin.org")
        m.assert_called_with(os.path.expanduser("~/.docker/config.json"), "r")


def test_pagination():
    """Test pagination works."""
    browser = Registry("httpbin.org")
    with requests_mock.Mocker() as m:
        first_resp = {"repositories": ["bar", "baz", "baz/foo", "foo"]}
        m.get(
            "https://httpbin.org/v2/_catalog",
            headers={"link": '</v2/_catalog?last=foo&n=100>; rel="next"'},
            json=first_resp,
        )
        second_resp = {"repositories": ["test/pinkunicorn"]}
        m.get("https://httpbin.org/v2/_catalog?last=foo&n=100", json=second_resp)
        results = browser._get_all_pages("/v2/_catalog")
        assert {"repositories": ["test/pinkunicorn"]} in results


def test_request_auth(registry):
    registry.auth = "abcd"
    with requests_mock.Mocker() as m:
        m.get("https://httpbin.org/v2/_catalog", headers={}, text="fail")
        m.get(
            "https://httpbin.org/v2/_catalog",
            headers={"Authentication": "Basic abcd"},
            text="ok",
        )
        assert registry._request("/v2/_catalog").text == "ok"


def test_request_no_image_tag(registry):
    """
    Due to https://github.com/docker/distribution/issues/2747, we get images from the catalog
    that return 404 when queried.

    So we need to correctly handle that case when getting the tags for an image
    """
    with requests_mock.Mocker() as m:
        m.get(
            "https://httpbin.org/v2/bar/tags/list",
            status_code=404,
            json={
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "message": "repository name not known to registry",
                        "detail": {"name": "bar"},
                    }
                ]
            },
        )
        assert registry.get_tags_for_image("bar") == []
