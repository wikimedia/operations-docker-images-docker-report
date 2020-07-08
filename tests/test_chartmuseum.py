from pathlib import Path

import pytest
import cgi
import requests_mock
from unittest import mock
from base64 import b64encode
from io import BytesIO

from docker_report.helm.chartmuseum import Chartmuseum, ChartmuseumError


@pytest.fixture
def chartmuseum() -> Chartmuseum:
    c = Chartmuseum("https://httpbin.org")
    return c


@pytest.fixture
def req_mock() -> requests_mock.Mocker:
    blubberoid = [
        {
            "name": "blubberoid",
            "home": "https://wikitech.wikimedia.org/wiki/Blubber",
            "sources": ["https://gerrit.wikimedia.org/g/blubber"],
            "version": "0.0.26",
            "description": "Helm chart for Blubberoid on WMF Kubernetes infrastructure",
            "keywords": ["blubber", "blubberoid"],
            "maintainers": [{"name": "Jeena Huneidi", "email": "jhuneidi@wikimedia.org"}],
            "apiVersion": "v1",
            "kubeVersion": ">=1.8",
            "urls": ["charts/blubberoid-0.0.26.tgz"],
            "created": "2020-07-07T23:12:24.152835354+02:00",
            "digest": "bc01360ef6bb1484655a0fc5486e2e4c41ed57ecc0abb8657d864a21d103fd9b",
        },
        {
            "name": "blubberoid",
            "home": "https://wikitech.wikimedia.org/wiki/Blubber",
            "sources": ["https://gerrit.wikimedia.org/g/blubber"],
            "version": "0.0.23",
            "description": "Helm chart for Blubberoid on WMF Kubernetes infrastructure",
            "keywords": ["blubber", "blubberoid"],
            "maintainers": [{"name": "Jeena Huneidi", "email": "jhuneidi@wikimedia.org"}],
            "apiVersion": "v1",
            "kubeVersion": ">=1.8",
            "urls": ["charts/blubberoid-0.0.23.tgz"],
            "created": "2020-07-07T23:12:24.084841989+02:00",
            "digest": "9cf0b73a83db571b13b9fccc25ca0dd167c5cc5036466673125222a671c46f10",
        },
    ]
    raw = [
        {
            "name": "raw",
            "home": "https://github.com/helm/charts/blob/master/incubator/raw",
            "version": "0.2.0-wmf1",
            "description": "A place for all the Kubernetes resources which don't already have a home.",
            "maintainers": [
                {"name": "josdotso", "email": "josdotso@cisco.com"},
                {"name": "mumoshu", "email": "ykuoka@gmail.com"},
            ],
            "apiVersion": "v1",
            "appVersion": "0.2.0",
            "urls": ["charts/raw-0.2.0-wmf1.tgz"],
            "created": "2020-07-07T23:12:29.564308422+02:00",
            "digest": "ba4e18d296c23bafe37cb5110a0227faf049df2859197981d2553ef6d3c81374",
        }
    ]

    err_chartnotfound = {"error": "chart not found"}
    m = requests_mock.Mocker()

    # Create an empty repo
    m.get("https://httpbin.org/api/bar/charts", json={})

    # Create an existing repo with charts
    m.get("https://httpbin.org/api/foo/charts", json={"blubberoid": blubberoid, "raw": raw})
    m.get("https://httpbin.org/api/foo/charts/blubberoid", json=blubberoid)
    m.get("https://httpbin.org/api/foo/charts/raw", json=raw)
    m.get("https://httpbin.org/api/foo/charts/nonexistent", status_code=404, json=err_chartnotfound)

    m.post("https://httpbin.org/api/baz/charts", status_code=201, json={"saved": True})
    return m


def test_init():
    c = Chartmuseum("https://httpbin.org")
    assert c.chartmuseum_url == "https://httpbin.org"
    assert c.username is None
    assert c.password is None


def test_get_charts(chartmuseum, req_mock):
    with req_mock:
        assert chartmuseum.get_charts("bar") == {}
        res = chartmuseum.get_charts("foo")
        assert len(res) == 2
        assert len(res.get("blubberoid")) == 2
        for t in res.get("blubberoid"):
            assert t.get("name") == "blubberoid"


def test_get_chart_versions(chartmuseum, req_mock):
    with req_mock:
        with pytest.raises(ChartmuseumError):
            chartmuseum.get_chart_versions("foo", "nonexistent")

        res = chartmuseum.get_chart_versions("foo", "blubberoid")
        assert len(res) == 2
        for t in res:
            assert t.get("name") == "blubberoid"


@mock.patch.object(Path, "open", new_callable=mock.mock_open, read_data=b"aa\nbb")
def test_upload_chart(open_mock, chartmuseum, req_mock):
    with req_mock as r_mock:
        res = chartmuseum.upload_chart("baz", Path("some/chart-0.0.1.tgz"))
        # Ensure file is read
        open_mock.assert_called_once_with("rb")
        assert res.status_code == 201

        # Ensure the correct form field is used
        last_req = r_mock.last_request
        fs = cgi.FieldStorage(fp=BytesIO(last_req.body), headers=last_req.headers, environ={"REQUEST_METHOD": "POST"})
        item = fs["chart"]
        assert item.value == b"aa\nbb"

        # Next upload should cause a 409 but should not raise
        r_mock.post(
            "https://httpbin.org/api/baz/charts", status_code=409, json={"error": "baz/chart-0.0.1 already exists"}
        )
        res = chartmuseum.upload_chart("baz", Path("some/chart-0.0.1.tgz"))
        assert res.status_code == 409

        # Ensure 401 is raised
        chartmuseum.username = "u"
        chartmuseum.password = "p"
        encoded_auth = b64encode(b"u:p").decode("ascii")
        r_mock.post("https://httpbin.org/api/baz/charts", status_code=401, json={"error": "unauthorized"})
        with pytest.raises(ChartmuseumError):
            chartmuseum.upload_chart("baz", Path("some/chart-0.0.1.tgz"))
            assert r_mock.last_request.headers["Authorization"] == "Basic " + encoded_auth


def test_is_version_in_repo(chartmuseum, req_mock):
    with req_mock:
        repo = chartmuseum.get_charts("foo")
        assert Chartmuseum.is_version_in_repo(repo, "blubberoid", "0.0.23") is True
        assert Chartmuseum.is_version_in_repo(repo, "blubberoid", "0.1.23") is False
        assert Chartmuseum.is_version_in_repo(repo, "nonexistent", "0.1.23") is False
