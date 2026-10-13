import argparse
import fnmatch
import io
from datetime import date
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
        ops.get_tags_for_image.return_value = [
            "foo",
            "foobar",
            "boofar",
            "926952c71ed2b5a94c1b9d52adf70129dfcb4bar",
        ]
        registryctl.list_tags("httpbin.org", "test", "*bar")
    assert "  - foobar" in fake_stdout.getvalue()
    assert "boofar" not in fake_stdout.getvalue()
    assert "926952c71ed2b5a94c1b9d52adf70129dfcb4bar" not in fake_stdout.getvalue()


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_force(base_mocker):
    ops = base_mocker.return_value
    ops.delete_image.return_value = (["foo", "foobar"], ["foobar"], [])
    # Even if images fail, exit code is always 0 with force.
    registryctl.delete_tags("httpbin.org", "test", "foo*", True)
    assert ops.get_tags_for_image.call_count == 0
    ops.delete_image.assert_called_with("test", "foo*", None)


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags(base_mocker):
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["foo", "foobar", "boofar"]
    ops.delete_image.return_value = (["foo", "foobar"], ["foobar"], [])
    with mock.patch("builtins.input") as i:
        i.return_value = "y"
        with pytest.raises(registryctl.RegistryError):
            registryctl.delete_tags("httpbin.org", "test", "foo*", False)
    ops.get_tags_for_image.assert_called_with("test")
    ops.delete_image.assert_called_with("test", "foo*", None)


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
    ops.delete_image.return_value = (["foobar"], [], [])
    with mock.patch("builtins.input") as i:
        i.return_value = "n"
        registryctl.delete_tags("httpbin.org", "test", "*bar", False)
    assert i.call_count == 0
    ops.delete_image.assert_called_with("test", "*bar", None)


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("2021-03-04-123456-production", date(2021, 3, 4)),
        ("20210304", date(2021, 3, 4)),
        ("2021_03_04", date(2021, 3, 4)),
        ("1.2.3-20210304", date(2021, 3, 4)),
        ("latest", None),
        # Not a valid date, so it must not be mistaken for one.
        ("2021-13-04", None),
        # A longer run of digits is not a date.
        ("build-202103041", None),
        # The first match isn't a date, but the second one is.
        ("2021-99-99-20210304", date(2021, 3, 4)),
    ],
)
def test_date_from_tag(tag, expected):
    assert registryctl.date_from_tag(tag) == expected


def test_parse_date():
    assert registryctl.parse_date("2021-03-04") == date(2021, 3, 4)
    assert registryctl.parse_date("20210304") == date(2021, 3, 4)
    with pytest.raises(argparse.ArgumentTypeError):
        registryctl.parse_date("pink-unicorn")


def test_parse_args_delete_tags_older_than():
    options = registryctl.parse_args(["delete-tags", "--older-than", "2021-03-04", "httpbin.org/foo/bar:*"])
    assert options.older_than == date(2021, 3, 4)
    # Without the flag, no date filtering is performed.
    options = registryctl.parse_args(["delete-tags", "httpbin.org/foo/bar:*"])
    assert options.older_than is None


def test_older_than_filter():
    is_older = registryctl.OlderThanFilter(date(2021, 3, 4))
    assert is_older("2021-03-03-production")
    # The limit date itself is not older than itself.
    assert not is_older("2021-03-04-production")
    assert not is_older("2021-03-05-production")
    # Tags without a date are never selected.
    assert not is_older("latest")
    assert is_older.undated == {"latest"}
    assert is_older.too_recent == {"2021-03-04-production", "2021-03-05-production"}
    assert is_older.rejected == 3


def test_older_than_filter_counts_tags_once():
    """The filter runs twice per invocation, so rejections must not be counted twice."""
    is_older = registryctl.OlderThanFilter(date(2021, 3, 4))
    for _ in range(2):
        assert not is_older("latest")
        assert not is_older("2021-03-05-production")
    assert is_older.rejected == 2


def test_older_than_filter_explain():
    is_older = registryctl.OlderThanFilter(date(2021, 3, 4))
    assert is_older.explain() == ""
    is_older("latest")
    assert is_older.explain() == "1 with no date in the tag"
    is_older("2021-03-05-production")
    assert is_older.explain() == "1 with no date in the tag, 1 not old enough"


@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_older_than(base_mocker):
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = [
        "2021-03-03-aaaaaa",
        "2021-03-04-bbbbbb",
        "2021-03-05-cccccc",
        "latest",
    ]
    ops.delete_image.return_value = (["2021-03-03-aaaaaa"], [], [])
    registryctl.delete_tags("httpbin.org", "test", "*", True, older_than=date(2021, 3, 4))
    name, glob, tag_filter = ops.delete_image.call_args[0]
    assert (name, glob) == ("test", "*")
    assert [t for t in ops.get_tags_for_image.return_value if tag_filter(t)] == ["2021-03-03-aaaaaa"]


@mock.patch("sys.stdout", new_callable=io.StringIO)
@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_older_than_confirmation(base_mocker, fake_stdout):
    """Without --force, the confirmation prompt only lists the tags older than the limit."""
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = [
        "2021-03-02-aaaaaa",
        "2021-03-03-bbbbbb",
        "2021-03-05-cccccc",
        "latest",
    ]
    with mock.patch("builtins.input") as i:
        i.return_value = "n"
        registryctl.delete_tags("httpbin.org", "test", "*", False, older_than=date(2021, 3, 4))
    assert i.call_count == 1
    out = fake_stdout.getvalue()
    assert "2021-03-02-aaaaaa" in out
    assert "2021-03-03-bbbbbb" in out
    assert "2021-03-05-cccccc" not in out
    assert "latest" not in out
    assert ops.delete_image.call_count == 0


def fake_delete_image(tags):
    """Build a delete_image side effect that filters like the real implementation does."""

    def delete_image(name, tag_glob, tag_filter=None):
        selected = fnmatch.filter(tags, tag_glob)
        if tag_filter is not None:
            selected = [tag for tag in selected if tag_filter(tag)]
        return (selected, [], [])

    return delete_image


@mock.patch("sys.stdout", new_callable=io.StringIO)
@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_older_than_no_match(base_mocker, fake_stdout):
    """When the date filter rejects everything the glob matched, say so explicitly."""
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["latest", "stable", "2021-03-05-cccccc"]
    ops.delete_image.side_effect = fake_delete_image(["latest", "stable", "2021-03-05-cccccc"])
    registryctl.delete_tags("httpbin.org", "test", "*", True, older_than=date(2021, 3, 4))
    out = fake_stdout.getvalue()
    assert "No tags for image httpbin.org/test matching '*' are older than 2021-03-04" in out
    assert "2 with no date in the tag" in out
    assert "1 not old enough" in out


@mock.patch("sys.stdout", new_callable=io.StringIO)
@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_older_than_glob_matched_nothing(base_mocker, fake_stdout):
    """If the glob itself matched no tag, the date filter has nothing to report."""
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["latest"]
    ops.delete_image.side_effect = fake_delete_image(["latest"])
    registryctl.delete_tags("httpbin.org", "test", "nomatch*", True, older_than=date(2021, 3, 4))
    assert fake_stdout.getvalue() == ""


@mock.patch("sys.stdout", new_callable=io.StringIO)
@mock.patch("docker_report.registry.operations.RegistryOperations")
def test_delete_tags_no_message_without_older_than(base_mocker, fake_stdout):
    """Without --older-than, an empty selection stays silent, as it always did."""
    ops = base_mocker.return_value
    ops.get_tags_for_image.return_value = ["latest"]
    ops.delete_image.side_effect = fake_delete_image(["latest"])
    registryctl.delete_tags("httpbin.org", "test", "nomatch*", True)
    assert fake_stdout.getvalue() == ""


@mock.patch("docker_report.registryctl.list_images")
def test_main_list_images(m):
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["list-images", "--select", "*foobar*", "httpbin.org"])
    m.assert_called_with("httpbin.org", "*foobar*", configfile=None)
    assert exc_info.value.code == 0


@mock.patch("docker_report.registryctl.list_tags")
def test_main_list_tags(m):
    m.side_effect = registryctl.RegistryError("fail")
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["--silent", "list-tags", "httpbin.org/foo/bar:1.*"])
    m.assert_called_with("httpbin.org", "foo/bar", "1.*", configfile=None)
    assert exc_info.value.code == 2


@mock.patch("docker_report.registryctl.delete_tags")
def test_main_delete_tags(m):
    m.side_effect = Exception("unicorns!")
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["delete-tags", "--force", "httpbin.org/foo/bar:1.*"])
    m.assert_called_with("httpbin.org", "foo/bar", "1.*", True, configfile=None, older_than=None)
    assert exc_info.value.code == 1


@mock.patch("docker_report.registryctl.delete_tags")
def test_main_delete_tags_older_than(m):
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["delete-tags", "-f", "--older-than", "20210304", "httpbin.org/foo/bar:*"])
    m.assert_called_with("httpbin.org", "foo/bar", "*", True, configfile=None, older_than=date(2021, 3, 4))
    assert exc_info.value.code == 0


@mock.patch("docker_report.registryctl.delete_tags")
def test_main_delete_tags_bad_date(m):
    """An invalid --older-than value is rejected by argparse."""
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["delete-tags", "-f", "--older-than", "yesterday", "httpbin.org/foo/bar:*"])
    assert exc_info.value.code == 2
    assert m.call_count == 0


@mock.patch("docker_report.registryctl.delete_tags")
def test_main_credentials(m):
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main(["--credentials", "/nonexistent/config.json", "delete-tags", "-f", "httpbin.org/foo:1.*"])
    m.assert_called_with("httpbin.org", "foo", "1.*", True, configfile="/nonexistent/config.json", older_than=None)
    assert exc_info.value.code == 0


@mock.patch("docker_report.registryctl.parse_args")
def test_main_unimplemented_action(m):
    m.return_value = argparse.Namespace(action="pinkunicorn", debug=True, silent=False)
    with pytest.raises(SystemExit) as exc_info:
        registryctl.main()
    assert exc_info.value.code == 3
