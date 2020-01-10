import io
import os
import shutil
import stat
import tempfile
from unittest import mock

import pytest

from docker_report import reporter
from docker_report.registry.browser import RegistryBrowser


@pytest.fixture
def browser(request) -> RegistryBrowser:
    RegistryBrowser.tag_filters = []
    RegistryBrowser.name_filters = []
    if not hasattr(request, "param"):
        opts = reporter.parse_args(["httpbin.org"])
    else:
        opts = reporter.parse_args(request.param)
    br = reporter.setup_browser(opts)
    return br


@pytest.fixture
def rep() -> reporter.Reporter:
    br = mock.MagicMock()
    br.registry_url = "example.org"
    return reporter.Reporter(br, "/tmp", False)


def test_args_basic():
    """Test a basic invokation creates the right flags"""
    opts = reporter.parse_args(["httpbin.org"])
    assert opts.registry == "httpbin.org"
    assert opts.keep is False
    assert opts.exclude_namespaces is None
    assert opts.filter_file is None
    assert opts.exclude_tag_regexp is None
    assert opts.concurrency == 1


def test_args_complex():
    """Test an invokation with namespaces to exclude."""
    opts = reporter.parse_args(["--exclude-namespaces", "debug", "pinkunicorn", "--", "httpbin.org"])
    assert opts.exclude_namespaces == ["debug", "pinkunicorn"]


@pytest.mark.parametrize(
    "browser", [["--exclude-namespaces", "debug", "pinkunicorn", "--", "httpbin.org"]], indirect=True
)
def test_setup_exclude_ns(browser):
    assert len(browser.name_filters) == 1
    # Now let's look that said name filter does what we expect it to
    assert browser.name_filters[0]("foo")
    assert browser.name_filters[0]("debug/foo") is False
    # Check the only tag filter filters out sha1s
    assert len(browser.tag_filters) == 1
    assert browser.tag_filters[0](("dummy", "0adab19a3f4d37e2d0487d984273e31595629855")) is False


@pytest.mark.parametrize(
    "browser", [["--exclude-tag-regexp", "latest", "--no-exclude-naked", "httpbin.org"]], indirect=True
)
def test_setup_tag_regexp_allow_sha1(browser):
    """Test basic setup of a browser, with tag regexes."""
    assert len(browser.tag_filters) == 1
    assert browser.tag_filters[0](("dummy", "0adab19a3f4d37e2d0487d984273e31595629855"))
    assert browser.tag_filters[0](("dummy", "latest")) is False


@mock.patch("docker_report.reporter._filters_from_file")
def test_setup_filters_from_file(mocker):
    mocker.return_value = ([lambda x: "foo/" not in x], [lambda data: data[1] != "latest"])
    RegistryBrowser.tag_filters = []
    RegistryBrowser.name_filters = []
    opts = reporter.parse_args(["--filter-file", "test.ini", "httpbin.org"])
    br = reporter.setup_browser(opts)
    mocker.assert_called_with("test.ini")
    assert len(br.tag_filters) == 2
    assert br.name_filters[0]("foo/bar") is False
    assert br.tag_filters[1](("foo", "latest")) is False


# Workaround: in order to keep the data near the tests, we monkey-patch
# configparser.ConfigParser.read to actually use read_string, so we can pass the
# content of the file as a string.
# We use this approach as patching builtins.open does not work in python < 3.7
def monkey_patch_read(self, filename, encoding="utf-8"):
    return self.read_string(filename.decode(encoding))


def test_filters_from_file():
    configfile = b"""
[no_devel_ns]

name = contains:devel/
action = exclude

[no_variable_tags]
tag = regex:(latest|stable)
action = exclude

[only_production_for_pinkunicorn]
name_match = contains:pinkunicorn/
tag = regex:.*production$
action = include
"""

    with mock.patch("configparser.ConfigParser.read", monkey_patch_read):
        name, tag = reporter._filters_from_file(configfile)
    assert len(name) == 1
    assert len(tag) == 2
    arg = ("pinkunicorn/foo", "3-production")
    assert tag[0](arg) and tag[1](arg)
    arg = ("pinkunicorn/foo", "10")
    assert (tag[0](arg) and tag[1](arg)) is False
    assert (name[0]("devel/foo")) is False
    arg = ("devel/foo", "10")
    assert tag[0](arg) and tag[1](arg)


def test_filters_from_file_invalid():
    """An invalid rule gets ignored"""
    configfile = b"""
[fake_rule]
action = exclude
banana = bread
"""
    with mock.patch("configparser.ConfigParser.read", monkey_patch_read):
        name, tag = reporter._filters_from_file(configfile)
    assert name == []
    assert tag == []


def test_filters_from_file_bad_rule_action():
    """An invalid rule action gets ignored"""
    configfile = b"""
[invalid_image_rule]
action = exclude
name = bread:slice

[invalid_name_match]
action = include
name_match = gibberish!
tag = regex:test

[invalid_tag]
action = include
tag = invalid
"""
    with mock.patch("configparser.ConfigParser.read", monkey_patch_read):
        name, tag = reporter._filters_from_file(configfile)
    assert name == []
    assert tag == []


def test_filters_from_file_include():
    """Inclusion rules are whitelists"""
    configfile = b"""
[only_foobar_ns]
name = contains:foobar/
action = include

[only_latest_in_foobar]
name_match = contains:foobar/
tag = regex:^latest$
"""
    with mock.patch("configparser.ConfigParser.read", monkey_patch_read):
        name, tag = reporter._filters_from_file(configfile)
    assert name[0]("foobar/test")
    assert name[0]("foo/test") is False
    # Shows the behaviour of tag filters: they only use the image name for selection purposes.
    assert tag[0](("foo/test", "late"))
    assert tag[0](("foobar/test", "late")) is False


@mock.patch("grp.getgrnam")
def test_tempdir(gr):
    """Test tempdir creation works."""
    # Intercept the chown to go to our user.
    gr.return_value.gr_gid = os.getgid()
    tmpdir = reporter._tempdir()
    assert os.path.isdir(tmpdir)
    assert stat.S_IMODE(os.stat(tmpdir).st_mode) == 0o770
    shutil.rmtree(tmpdir)


def test_reporter_init(rep):
    """Initialize the reporter"""
    assert rep._prune_images
    assert rep.exitcode == 0


@mock.patch("docker_report.reporter.DockerReport")
def test_run_report(dr, rep):
    rep.run_report("example.org/test:latest")
    dr.assert_called_with("example.org/test:latest", "/tmp")
    debmonitor = dr.return_value
    debmonitor.generate_report.assert_called_with()
    debmonitor.submit_report.assert_called_with()
    debmonitor.prune_image.assert_called_with()
    assert rep.exitcode == 0


@mock.patch("docker_report.reporter.DockerReport")
def test_run_report_keep(dr, rep):
    rep._prune_images = False
    rep.run_report("example.org/test:latest")
    assert dr.return_value.prune_image.call_count == 0


@mock.patch("docker_report.reporter.DockerReport")
def test_run_report_exception(dr, rep):
    dr.return_value.generate_report.side_effect = reporter.DockerReportError("")
    rep.run_report("example.org/test:latest")
    assert rep.exitcode == 3


def test_get_images(rep):
    rep._browser.get_image_tags.return_value = {"test": ["1", "3", "latest"]}
    assert list(rep.get_images()) == ["example.org/test:latest"]
    assert rep.exitcode == 0


def test_get_images_error(rep):
    rep._browser.get_image_tags.side_effect = reporter.RegistryError("fail!")
    assert list(rep.get_images()) == []
    assert rep.exitcode == 2


@mock.patch("sys.stdout", new_callable=io.StringIO)
def test_pprint(stdout, rep):
    rep._failed = []
    rep._success = ["abc"]
    rep.pprint()
    assert "All images submitted correctly!" in stdout.getvalue()


@mock.patch("sys.stdout", new_callable=io.StringIO)
def test_pprint_fail(stdout, rep):
    rep._failed = ["cde"]
    rep._success = ["abc"]
    rep.pprint()
    assert "All images submitted correctly!" not in stdout.getvalue()


@mock.patch("docker_report.reporter.Reporter")
def test_main_happy_path(rep):
    instance = rep.return_value
    instance.get_images.return_value = ["example.org/pinkunicorn:production", "example.org/test:latest"]
    with mock.patch("docker_report.reporter._tempdir") as td:
        # This file will be removed
        td.return_value = tempfile.mkdtemp()
        with pytest.raises(SystemExit):
            reporter.main(["example.org"])
    assert not os.path.isdir(td.return_value)
    assert instance.run_report.call_count == 2
    instance.run_report.assert_called_with("example.org/test:latest")


@mock.patch("docker_report.reporter.Reporter")
def test_main_exception(rep):
    instance = rep.return_value
    instance.get_images.return_value = ["example.org/pinkunicorn:production", "example.org/test:latest"]
    instance.run_report.side_effect = ValueError("I don't trust pink unicorns")
    with mock.patch("docker_report.reporter._tempdir") as td:
        # This file will be removed
        td.return_value = tempfile.mkdtemp()
        with pytest.raises(SystemExit) as exc_info:
            reporter.main(["example.org"])
    assert not os.path.isdir(td.return_value)
    assert instance.run_report.call_count == 1
    assert exc_info.value.code == 1
