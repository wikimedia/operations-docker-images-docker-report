from unittest import mock

import pytest
import requests_mock

from docker_report import reporter
from docker_report.k8s.browser import KubernetesBrowser


@pytest.fixture
def browser(request) -> KubernetesBrowser:
    KubernetesBrowser.tag_filters = []
    KubernetesBrowser.name_filters = []
    if not hasattr(request, "param"):
        opts = reporter.parse_args(["--kubernetes", "test-cluster"])
    else:
        opts = reporter.parse_args(request.param)
    br = reporter.setup_browser(opts)
    return br


@pytest.fixture
@mock.patch("docker_report.k8s.browser.ConfigParser")
def rep(mocked_config_parser) -> reporter.Reporter:
    mocked_config_parser.return_value.defaults.return_value = {"server": "debmonitor.example.com"}
    br = KubernetesBrowser("test-cluster", kubeconfig_path="tests/fixtures/kubeconfig-test-cluster.config")
    return reporter.Reporter(br, "/tmp", False, 10)


def test_get_images_existing(rep):
    rep._browser.get_running_images = mock.MagicMock()
    rep._browser.get_running_images.return_value = {
        "cluster": "test-cluster",
        "images": {
            "image-something:tag1": {"namespace1": 3, "namespace4": 100},
            "image-bla:tag13": {"namespace13": 3, "namespace43": 100},
        },
    }
    with requests_mock.Mocker() as m:
        m.get("https://debmonitor.example.com/images/image-something:tag1", json={"name": "image-something:tag1"})
        m.get("https://debmonitor.example.com/images/image-bla:tag13", json={"name": "image-bla:tag13"})
        assert list(rep.get_images()) == []

    assert rep.exitcode == 0


def test_get_images_missing(rep):
    rep._browser.get_running_images = mock.MagicMock()
    rep._browser.get_running_images.return_value = {
        "cluster": "test-cluster",
        "images": {
            "image-something:tag1": {"namespace1": 3, "namespace4": 100},
            "image-bla:tag13": {"namespace13": 3, "namespace43": 100},
        },
    }
    with requests_mock.Mocker() as m:
        m.get("https://debmonitor.example.com/images/image-something:tag1", status_code=404)
        m.get("https://debmonitor.example.com/images/image-bla:tag13", status_code=404)
        assert list(rep.get_images()) == ["image-something:tag1", "image-bla:tag13"]

    assert rep.exitcode == 0


def test_get_images_filtered(rep):
    def nofoobar(name):
        return name != "foo/bar"

    def nons(name):
        return name[0] != "/"

    rep._browser.name_filters = [nofoobar, nons]
    rep._browser.get_running_images = mock.MagicMock()
    fake_image1 = "docker-registry.discovery.wmnet/batman/robin:tag1"
    fake_image2 = "docker-registry.discovery.wmnet/foo/bar:tag13"
    rep._browser.get_running_images.return_value = {
        "cluster": "test-cluster",
        "images": {
            fake_image1: {"namespace1": 3, "namespace4": 100},
            fake_image2: {"namespace13": 3, "namespace43": 100},
        },
    }
    with requests_mock.Mocker() as m:
        m.get(
            f"https://debmonitor.example.com/images/{fake_image1}",
            json={"name": fake_image1},
        )
        m.get(
            f"https://debmonitor.example.com/images/{fake_image2}",
            json={"name": fake_image2},
        )
        assert list(rep.get_images()) == []

    with requests_mock.Mocker() as m:
        m.get(f"https://debmonitor.example.com/images/{fake_image1}", status_code=404)
        m.get(f"https://debmonitor.example.com/images/{fake_image2}", status_code=404)
        assert list(rep.get_images()) == [fake_image1]
