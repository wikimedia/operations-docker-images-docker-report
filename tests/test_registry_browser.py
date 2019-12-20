from unittest import mock

import pytest
import requests
import requests_mock

from docker_report.registry_browser import RegistryBrowser, RegistryBrowserError


@pytest.fixture
def browser():
    """A registry browser that will not perform requests"""
    rb = RegistryBrowser("httpbin.org")
    rb._get_all_pages = mock.MagicMock()
    return rb


def test_pagination():
    """Test pagination works."""
    browser = RegistryBrowser("httpbin.org")
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


def test_get_images_list(browser):
    """Test retreiving images works"""

    def nofoo(name):
        return name != "foo"

    def nons(name):
        return "/" not in name

    browser.name_filters = [nofoo, nons]
    browser._get_all_pages.return_value = [
        {"repositories": ["bar", "baz", "baz/foo", "foo"]},
        {"repositories": ["test/pinkunicorn"]},
    ]
    results = browser._get_images_list()
    assert results == ["bar", "baz"]


def test_get_image_tags(browser):
    """Test retreiving tags for an image works"""
    browser._get_images_list = mock.MagicMock(return_value=["foo", "foo/bar"])
    browser._get_all_pages.return_value = [{"name": "foo/bar", "tags": ["1", "foo1", "2"]}]

    def onlynumeric(data):
        return data[0] == "foo/bar" and data[1] in ["1", "2"]

    browser.tag_filters = [onlynumeric]
    res = browser.get_image_tags()
    assert res == {"foo/bar": ["1", "2"]}


def test_request_error():
    """If a request raises an error, raise a localized exception"""
    rb = RegistryBrowser("httpbin.org")
    rb._request = mock.MagicMock(side_effect=requests.RequestException("test"))
    with pytest.raises(RegistryBrowserError):
        rb.get_image_tags()


def test_get_image_tags_sorted(browser):
    """Test sorting is called."""
    browser.sort_tags = mock.MagicMock(return_value=["fool", "1", "2"])
    browser._get_images_list = mock.MagicMock(return_value=["foo/bar"])
    browser._get_all_pages.return_value = [{"name": "foo/bar", "tags": ["1", "foo1", "2"]}]
    # Sort is not called
    res = browser.get_image_tags()
    assert res["foo/bar"] == ["1", "foo1", "2"]
    res = browser.get_image_tags(sort=True)
    assert res["foo/bar"] == ["fool", "1", "2"]


def test_sort_tags(browser):
    """Test sorting works"""
    mock_responses = [
        [{"history": [{"v1Compatibility": '{"created": "2018-05-15T13:32:36.023166904Z"}'}]}],
        [{"history": [{"v1Compatibility": '{"created": "2018-04-15T13:32:36.023166904Z"}'}]}],
    ]
    browser._get_all_pages.side_effect = mock_responses
    assert browser.sort_tags("test", ["0.1", "0.2"]) == ["0.2", "0.1"]


@pytest.mark.parametrize(
    "response",
    [
        [""],  # empty response
        [{"test": "something"}],  # no history
        [{"history": []}],  # empty history
        [{"history": [{"a": "b"}]}],  # no v1Compatibility
        [{"history": [{"v1Compatibility": '{"test": "yes"}'}]}],  # no created
        [{"history": [{"v1Compatibility": "}"}]}],  # bad json
    ],
)
def test_sort_bad_response(browser, response):
    browser._get_all_pages.return_value = response
    with pytest.raises(RegistryBrowserError, match="Could not sort test"):
        browser.sort_tags("test", ["0.1", "0.2"])
