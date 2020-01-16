from unittest import mock

import pytest
import requests
import requests_mock

from docker_report.registry.operations import RegistryOperations


@pytest.fixture
def operations() -> RegistryOperations:
    r = RegistryOperations("httpbin.org")
    return r


def test_image_digest(operations):
    """Getting the digest of an image/tag couple works."""
    with requests_mock.Mocker() as m:
        m.get(
            "https://httpbin.org/v2/foobar/manifests/latest",
            headers={"Docker-Content-Digest": "ok"},
            request_headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        )
        assert operations._image_digest("foobar", "latest") == "ok"


def test_image_digest_not_found(operations):
    """Getting the digest for a not existent image raises an exception"""
    with requests_mock.Mocker() as m:
        m.get("https://httpbin.org/v2/foobar/manifests/latest", status_code=404)
        with pytest.raises(requests.exceptions.HTTPError):
            operations._image_digest("foobar", "latest")


def test_delete_image(operations):
    """Deleting a single image works as expected"""
    operations.get_tags_for_image = mock.MagicMock(return_value=["a", "b", "atest", "latest"])
    with requests_mock.Mocker() as m:
        m.get("https://httpbin.org/v2/foobar/manifests/latest", headers={"Docker-Content-Digest": "ok"})
        m.delete("https://httpbin.org/v2/foobar/manifests/ok", status_code=202)
        assert operations.delete_image("foobar", "l*") == (["latest"], [])
        assert m.call_count == 2
        assert m.request_history[1].method == "DELETE"


def test_delete_image_no_match(operations):
    """If no match is found, nothing happens"""
    operations.get_tags_for_image = mock.MagicMock(return_value=["a", "b", "atest", "latest"])
    with requests_mock.Mocker() as m:
        assert operations.delete_image("foobar", "0.*") == ([], [])
        assert m.call_count == 0


def test_delete_image_no_auth(operations):
    """If an image can't be deleted, it ends up in the failed list"""
    operations.get_tags_for_image = mock.MagicMock(return_value=["a", "b", "atest", "latest"])
    with requests_mock.Mocker() as m:
        m.get("https://httpbin.org/v2/foobar/manifests/latest", headers={"Docker-Content-Digest": "ok"})
        m.get("https://httpbin.org/v2/foobar/manifests/atest", headers={"Docker-Content-Digest": "ko"})
        m.delete("https://httpbin.org/v2/foobar/manifests/ok", status_code=202)
        m.delete("https://httpbin.org/v2/foobar/manifests/ko", status_code=401)
        selected, failed = operations.delete_image("foobar", "*test")
    assert set(selected) == set(["atest", "latest"])
    assert failed == ["atest"]
