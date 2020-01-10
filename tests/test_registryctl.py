import argparse
import io
from unittest import mock

import pytest

from docker_report import registryctl


def test_parse_args_list_images():
    options = registryctl.parse_args(["--silent", "list-images", "httpbin.org"])
    assert options.registry == "httpbin.org"
    assert options.silent
    assert options.select == "*"


def test_parse_args_list_tags():
    options = registryctl.parse_args(["list-tags", "httpbin.org/foobar"])
    assert options.registry == "httpbin.org"
    assert options.select == "*"
    assert options.image_name == "foobar"


def test_parse_args_delete_tags():
    options = registryctl.parse_args(["delete-tags", "httpbin.org:666/foo/bar:2018*"])
    assert options.registry == "httpbin.org:666"
    assert options.select == "2018*"
    assert options.image_name == "foo/bar"


@mock.patch("docker_report.registry.browser.RegistryBrowser")
def test_list_images(base_mocker):
    browser = base_mocker.return_value
    browser.name_filters = []
    browser.image_filters = []
    browser.get_image_tags.return_value = {"a": ["b", "c"]}
    registryctl.list_images("httpbin.org", "b*")
    assert len(browser.name_filters) == 1
    assert browser.name_filters[0]("b")
    assert not browser.name_filters[0]("c")
    assert browser.tag_filters[0]("b")


@mock.patch("sys.stdout", new_callable=io.StringIO)
def test_list_tags(fake_stdout):
    with mock.patch("docker_report.registry.operations.RegistryOperations") as base_mocker:
        ops = base_mocker.return_value
        # Last tag is a fake sha1 to check it doesn't appear in the output.
        ops.get_tags_for_image.return_value = ["foo", "foobar", "boofar", "926952c71ed2b5a94c1b9d52adf70129dfcb4bar"]
        registryctl.list_tags("httpbin.org", "test", "*bar")
    assert "  - foobar" in fake_stdout.getvalue()
    assert "boofar" not in fake_stdout.getvalue()
    assert "926952c71ed2b5a94c1b9d52adf70129dfcb4bar" not in fake_stdout.getvalue()


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_force(base_mocker):
    ops = base_mocker.return_value
    ops.delete_image.return_value = (["foo", "foobar"], ["foobar"])
    # Even if images fail, exit code is always 0 with force.
    registryctl.delete_tags("httpbin.org", "test", "foo*", True)
    assert ops.get_tags_for_image.call_count == 0
    ops.delete_image.assert_called_with("test", "foo*")


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags(base_mocker):
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["foo", "foobar", "boofar"]
    ops.delete_image.return_value = (["foo", "foobar"], ["foobar"])
    with mock.patch("builtins.input") as i:
        i.return_value = "y"
        with pytest.raises(registryctl.RegistryError):
            registryctl.delete_tags("httpbin.org", "test", "foo*", False)
    ops.get_tags_for_image.assert_called_with("test")
    ops.delete_image.assert_called_with("test", "foo*")


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_abort(base_mocker):
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["foo", "foobar", "boofar"]
    with mock.patch("builtins.input") as i:
        i.return_value = "n"
        registryctl.delete_tags("httpbin.org", "test", "foo*", False)
    assert ops.delete_image.call_count == 0


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_single(base_mocker):
    """Test deleting a single image doesn't require confirmation"""
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["foo", "foobar", "boofar"]
    ops.delete_image.return_value = (["foobar"], [])
    with mock.patch("builtins.input") as i:
        i.return_value = "n"
        registryctl.delete_tags("httpbin.org", "test", "*bar", False)
    assert i.call_count == 0
    ops.delete_image.assert_called_with("test", "*bar")


@mock.patch("docker_report.registryctl.list_images")
def test_main_list_images(m):
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["list-images", "--select", "*foobar*", "httpbin.org"])
        m.assert_called_with("httpbin.org", "*foobar*")
    assert exc_info.value.code == 0


@mock.patch("docker_report.registryctl.list_tags")
def test_main_list_tags(m):
    m.side_effect = registryctl.RegistryError("fail")
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["--silent", "list-tags", "httpbin.org/foo/bar:1.*"])
    m.assert_called_with("httpbin.org", "foo/bar", "1.*")
    assert exc_info.value.code == 2


@mock.patch("docker_report.registryctl.delete_tags")
def test_main_delete_tags(m):
    m.side_effect = Exception("unicorns!")
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["delete-tags", "--force", "httpbin.org/foo/bar:1.*"])
    m.assert_called_with("httpbin.org", "foo/bar", "1.*", True)
    assert exc_info.value.code == 1


@mock.patch("docker_report.registryctl.parse_args")
def test_main_unimplemented_action(m):
    m.return_value = argparse.Namespace(action="pinkunicorn", debug=True, silent=False)
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main()
    assert exc_info.value.code == 3
