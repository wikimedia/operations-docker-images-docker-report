import json
import os
from unittest import mock

import pytest
import requests_mock

from docker_report.registry import Registry


@pytest.fixture
def registry() -> Registry:
    r = Registry("httpbin.org")
    return r


def test_initialize():
    """Test basic initialization - no auth"""
    rb = Registry("httpbin.org", configfile="test")
    assert rb.registry_url == "httpbin.org"
    assert rb.auth is None


def test_auth_token():
    with mock.patch("json.load") as jl:
        jl.return_value = {"auths": {"httpbin.org": {"auth": "abcd"}}}
        # This is a trick to ensure the file is present and readable.
        filename = os.path.abspath(__file__)
        r = Registry("httpbin.org", configfile=filename)
        assert r.auth == "abcd"


def test_auth_token_invalid(registry):
    with mock.patch("json.load") as jl:
        jl.side_effect = json.decoder.JSONDecodeError("test", doc="some error", pos=10)
        assert registry._get_auth_token(__file__) is None


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
        m.get("https://httpbin.org/v2/_catalog", headers={"Authentication": "Basic abcd"}, text="ok")
        assert registry._request("/v2/_catalog").text == "ok"
