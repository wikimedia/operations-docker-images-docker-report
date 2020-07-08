import pytest
import subprocess
from pathlib import Path
from unittest import mock

from docker_report import helm

chart_yaml_data = b"""
apiVersion: v1
description: Helm chart for Blubberoid on WMF Kubernetes infrastructure
kubeVersion: ">=1.8"
name: blubberoid
version: 0.0.26
keywords:
- blubber
- blubberoid
home: https://wikitech.wikimedia.org/wiki/Blubber
sources:
- https://gerrit.wikimedia.org/g/blubber
maintainers:
- name: Jeena Huneidi
  email: jhuneidi@wikimedia.org
tillerVersion: ">=2.8"
"""


@mock.patch.object(Path, "open", new_callable=mock.mock_open, read_data=chart_yaml_data)
def test_get_chart_name_version(open_mock):
    assert helm.get_chart_name_version(Path("foo/path/Chart.yaml")) == ("blubberoid", "0.0.26")
    open_mock.assert_called_once_with()


@mock.patch.object(Path, "open", new_callable=mock.mock_open, read_data=b"aa:1")
def test_get_chart_name_version_error(open_mock):
    with pytest.raises(helm.ChartError):
        helm.get_chart_name_version(Path("foo/path/Chart.yaml"))


@mock.patch("tempfile.mkdtemp", return_value="/nonexistent")
@mock.patch.object(Path, "is_file")
@mock.patch("subprocess.check_output")
def test_package_cmd_ok(subprocess_mock, isfile_mock, mkdtemp_mock):
    """Test that a normal command will report its results"""
    subprocess_mock.return_value = b"Successfully packaged chart and saved it to: /nonexistent/zotero-0.0.16.tgz\n"
    isfile_mock.return_value = True
    helm.package_chart(Path("foo_ok"))


@mock.patch("tempfile.mkdtemp", return_value="/nonexistent")
@mock.patch("subprocess.check_output")
def test_package_cmd_error(subprocess_mock, mkdtemp_mock):
    """Test that errors in commands are correctly handled"""
    with pytest.raises(helm.HelmError):
        subprocess_mock.side_effect = subprocess.CalledProcessError(
            1, "foobar", b"Error: chart metadata (Chart.yaml) missing"
        )
        helm.package_chart(Path("foo_err"))
