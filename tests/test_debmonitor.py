import logging
import subprocess
from unittest import mock

import pytest

from docker_report import debmonitor


def test_args_valid():
    """Test the happy path for parsing args"""
    args = ["--debug", "image_name", "directory"]
    options = debmonitor.parse_args(args)
    assert options.debug
    assert options.image_name == "image_name"
    assert options.report_dir == "directory"
    assert options.silent is False
    assert options.no_submit is False
    assert options.keep is False


def test_setup_logging():
    """Test that logging gets set up"""
    args = ["--debug", "image_name", "directory"]
    options = debmonitor.parse_args(args)
    debmonitor.setup_logging(debmonitor.logger, options)
    assert debmonitor.logger.level == logging.DEBUG
    options = debmonitor.parse_args(["image", "dir"])
    debmonitor.setup_logging(debmonitor.logger, options)
    assert debmonitor.logger.level == logging.INFO


@pytest.fixture
def report(name: str = "docker-registry.wikimedia.org/envoy-tls-local-proxy:1.12.2-1", report_dir: str = "/tmp"):
    return debmonitor.DockerReport(name, report_dir)


def test_report_init(report):
    """Test initialization is correct"""
    assert report.proxy is None
    assert report.filename == "/tmp/docker-registry.wikimedia.org-envoy-tls-local-proxy:1.12.2-1.debmonitor.json"


def test_generate_report(report):
    """Test report generation does the right thing."""
    report._cmd = mock.MagicMock()
    report.generate_report()
    report._cmd.assert_called_with("Report generation", report._docker_cmd())


def test_submit_report(report):
    report._cmd = mock.MagicMock()
    report.submit_report()
    report._cmd.assert_called_with(
        "Submit report",
        [
            "debmonitor-client-unpriv",
            "-f",
            "/tmp/docker-registry.wikimedia.org-envoy-tls-local-proxy:1.12.2-1.debmonitor.json",
        ],
    )


def test_docker_cmd(report):
    """Test the docker invokation."""
    res = report._docker_cmd()
    assert res[-1].startswith("echo 'No proxy configured'")
    report.proxy = "pinkunicorn"
    res = report._docker_cmd()
    assert res[-1].startswith("echo 'Acquire::http::Proxy \"pinkunicorn\";'")
    assert "/tmp:/mnt:rw" in res
    bash = res[-1].split(" && ")
    assert (
        "/usr/bin/debmonitor-client -n -i 'docker-registry.wikimedia.org/envoy-tls-local-proxy:1.12.2-1' > "
        "'/mnt/docker-registry.wikimedia.org-envoy-tls-local-proxy:1.12.2-1.debmonitor.json'" in bash
    )


@mock.patch("subprocess.check_output")
def test_cmd_error(mocker, report):
    """Test that errors in commands are correctly handled"""
    with pytest.raises(debmonitor.DockerReportError):
        mocker.side_effect = subprocess.CalledProcessError(1, "foobar", b"nope")
        report._cmd("test", ["some", "command"])


@mock.patch("subprocess.check_output")
def test_cmd_ok(mocker, report):
    """Test that a normal command will report its results"""
    debmonitor.logger.debug = mock.MagicMock()
    mocker.return_value = b"success!"
    report._cmd("test", ["cowsay", "pinkunicorn"])
    debmonitor.logger.debug.assert_called_with("success!")


def test_prune_image(report):
    report._cmd = mock.MagicMock()
    report.prune_image()
    report._cmd.assert_called_with(
        "Image pruning", ["docker", "rmi", "-f", "docker-registry.wikimedia.org/envoy-tls-local-proxy:1.12.2-1"]
    )


@mock.patch("docker_report.debmonitor.DockerReport")
def test_main(mocker):
    with pytest.raises(SystemExit) as se:
        debmonitor.main(["--keep", "image", "dir"])
        assert se.code == 0
    mocker.assert_called_with("image", "dir")
    mocker.return_value.generate_report.assert_called_with()
    mocker.return_value.submit_report.assert_called_with()


@mock.patch("docker_report.debmonitor.DockerReport._cmd")
def test_main_not_ok(mocker):
    # Case 1: expected exception
    mocker.side_effect = debmonitor.DockerReportError("fail")
    with pytest.raises(SystemExit) as se:
        debmonitor.main(["--keep", "image", "dir"])
        assert se.code == 1


@mock.patch("docker_report.debmonitor.DockerReport._cmd")
def test_main_unexpected(mocker):
    # Case 2: unexpected exception
    mocker.side_effect = Exception("fail")
    with pytest.raises(SystemExit) as se:
        debmonitor.main(["--keep", "image", "dir"])
        assert se.code == 2


@mock.patch("shutil.rmtree")
@mock.patch("docker_report.debmonitor.DockerReport._cmd")
def test_main_removal(cmd, rmtree):
    """Test the file is removed with the right cli options"""
    with pytest.raises(SystemExit):
        debmonitor.main(["image", "/dir"])
        rmtree.assert_called_with("/dir/image.debmonitor.json", ignore_errors=True)


@mock.patch("shutil.rmtree")
@mock.patch("docker_report.debmonitor.DockerReport._cmd")
def test_main_keep(cmd, rmtree):
    """Test the file is removed with the right cli options"""
    with pytest.raises(SystemExit):
        debmonitor.main(["--keep", "image", "/dir"])
        assert rmtree.call_count == 0


@mock.patch("shutil.rmtree")
@mock.patch("docker_report.debmonitor.DockerReport._cmd")
def test_main_no_submit(cmd, rmtree):
    """Test no submission"""
    report = debmonitor.DockerReport("image", "/dir")
    with pytest.raises(SystemExit):
        debmonitor.main(["--no-submit", "image", "/dir"])
        assert rmtree.call_count == 0
    cmd.assert_called_with("Report generation", report._docker_cmd())
