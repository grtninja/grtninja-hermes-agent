"""Tests for container-aware CLI routing (NixOS container mode).

When container.enable = true in the NixOS module, the activation script
writes a .container-mode metadata file. The host CLI detects this and
execs into the container instead of running locally.
"""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.config import (
    _is_inside_container,
    get_container_exec_info,
)


# =============================================================================
# _is_inside_container
# =============================================================================


def test_is_inside_container_dockerenv():
    """Detects /.dockerenv marker file."""
    with patch("os.path.exists") as mock_exists:
        mock_exists.side_effect = lambda p: p == "/.dockerenv"
        assert _is_inside_container() is True


def test_is_inside_container_containerenv():
    """Detects Podman's /run/.containerenv marker."""
    with patch("os.path.exists") as mock_exists:
        mock_exists.side_effect = lambda p: p == "/run/.containerenv"
        assert _is_inside_container() is True


def test_is_inside_container_cgroup_docker():
    """Detects 'docker' in /proc/1/cgroup."""
    with patch("os.path.exists", return_value=False), \
         patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(
            return_value="12:memory:/docker/abc123\n"
        )
        assert _is_inside_container() is True


def test_is_inside_container_false_on_host():
    """Returns False when none of the container indicators are present."""
    with patch("os.path.exists", return_value=False), \
         patch("builtins.open", side_effect=OSError("no such file")):
        assert _is_inside_container() is False


# =============================================================================
# get_container_exec_info
# =============================================================================


@pytest.fixture
def container_env(tmp_path, monkeypatch):
    """Set up a fake HERMES_HOME with .container-mode file."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("HERMES_DEV", raising=False)

    container_mode = hermes_home / ".container-mode"
    container_mode.write_text(
        "# Written by NixOS activation script. Do not edit manually.\n"
        "backend=podman\n"
        "container_name=hermes-agent\n"
        "exec_user=hermes\n"
        "hermes_bin=/data/current-package/bin/hermes\n"
    )
    return hermes_home


def test_get_container_exec_info_returns_metadata(container_env):
    """Reads .container-mode and returns all fields including exec_user."""
    with patch("hermes_cli.config._is_inside_container", return_value=False):
        info = get_container_exec_info()

    assert info is not None
    assert info["backend"] == "podman"
    assert info["container_name"] == "hermes-agent"
    assert info["exec_user"] == "hermes"
    assert info["hermes_bin"] == "/data/current-package/bin/hermes"


def test_get_container_exec_info_none_inside_container(container_env):
    """Returns None when we're already inside a container."""
    with patch("hermes_cli.config._is_inside_container", return_value=True):
        info = get_container_exec_info()

    assert info is None


def test_get_container_exec_info_none_without_file(tmp_path, monkeypatch):
    """Returns None when .container-mode doesn't exist (native mode)."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("HERMES_DEV", raising=False)

    with patch("hermes_cli.config._is_inside_container", return_value=False):
        info = get_container_exec_info()

    assert info is None


def test_get_container_exec_info_skipped_when_hermes_dev(container_env, monkeypatch):
    """Returns None when HERMES_DEV=1 is set (dev mode bypass)."""
    monkeypatch.setenv("HERMES_DEV", "1")

    with patch("hermes_cli.config._is_inside_container", return_value=False):
        info = get_container_exec_info()

    assert info is None


def test_get_container_exec_info_not_skipped_when_hermes_dev_zero(container_env, monkeypatch):
    """HERMES_DEV=0 does NOT trigger bypass — only '1' does."""
    monkeypatch.setenv("HERMES_DEV", "0")

    with patch("hermes_cli.config._is_inside_container", return_value=False):
        info = get_container_exec_info()

    assert info is not None


def test_get_container_exec_info_defaults():
    """Falls back to defaults for missing keys."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        hermes_home = Path(tmpdir) / ".hermes"
        hermes_home.mkdir()
        (hermes_home / ".container-mode").write_text(
            "# minimal file with no keys\n"
        )

        with patch("hermes_cli.config._is_inside_container", return_value=False), \
             patch("hermes_cli.config.get_hermes_home", return_value=hermes_home), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_DEV", None)
            info = get_container_exec_info()

        assert info is not None
        assert info["backend"] == "docker"
        assert info["container_name"] == "hermes-agent"
        assert info["exec_user"] == "hermes"
        assert info["hermes_bin"] == "/data/current-package/bin/hermes"


def test_get_container_exec_info_docker_backend(container_env):
    """Correctly reads docker backend with custom exec_user."""
    (container_env / ".container-mode").write_text(
        "backend=docker\n"
        "container_name=hermes-custom\n"
        "exec_user=myuser\n"
        "hermes_bin=/opt/hermes/bin/hermes\n"
    )

    with patch("hermes_cli.config._is_inside_container", return_value=False):
        info = get_container_exec_info()

    assert info["backend"] == "docker"
    assert info["container_name"] == "hermes-custom"
    assert info["exec_user"] == "myuser"
    assert info["hermes_bin"] == "/opt/hermes/bin/hermes"


# =============================================================================
# _exec_in_container
# =============================================================================


def test_exec_in_container_constructs_correct_command():
    """Exec command includes -u exec_user, -e env vars, TTY flags."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "docker",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         patch.dict(os.environ, {"TERM": "xterm-256color", "LANG": "en_US.UTF-8"},
                    clear=False), \
         pytest.raises(SystemExit) as exc_info:
        mock_stdin.isatty.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        _exec_in_container(container_info, ["chat", "-m", "opus"])

    assert exc_info.value.code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    # Runtime and exec
    assert cmd[0] == "/usr/bin/docker"
    assert cmd[1] == "exec"
    # TTY flags
    assert "-it" in cmd
    # User flag
    idx_u = cmd.index("-u")
    assert cmd[idx_u + 1] == "hermes"
    # Env passthrough
    e_indices = [i for i, v in enumerate(cmd) if v == "-e"]
    e_values = [cmd[i + 1] for i in e_indices]
    assert "TERM=xterm-256color" in e_values
    assert "LANG=en_US.UTF-8" in e_values
    # Container + binary + args
    assert "hermes-agent" in cmd
    assert "/data/current-package/bin/hermes" in cmd
    assert "chat" in cmd


def test_exec_in_container_non_tty_uses_i_only():
    """Non-TTY mode uses -i instead of -it."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "docker",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         pytest.raises(SystemExit):
        mock_stdin.isatty.return_value = False
        mock_run.return_value = MagicMock(returncode=0)

        _exec_in_container(container_info, ["sessions", "list"])

    cmd = mock_run.call_args[0][0]
    # Should have -i but NOT -it
    assert "-i" in cmd
    assert "-it" not in cmd


def test_exec_in_container_no_runtime_hard_fails():
    """Hard fails when runtime not found (no fallback)."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "podman",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         pytest.raises(SystemExit) as exc_info:
        mock_stdin.isatty.return_value = True
        _exec_in_container(container_info, ["chat"])

    mock_run.assert_not_called()
    assert exc_info.value.code != 0


def test_exec_in_container_tty_retries_on_container_failure():
    """TTY mode retries on docker exit codes 125-127, then hard fails."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "docker",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         patch("sys.stderr"), \
         patch("time.sleep") as mock_sleep, \
         pytest.raises(SystemExit) as exc_info:
        mock_stdin.isatty.return_value = True
        # Docker returns 125 = container not running
        mock_run.return_value = MagicMock(returncode=125)
        _exec_in_container(container_info, ["chat"])

    assert mock_sleep.call_count == 4  # 5 attempts, 4 sleeps
    assert exc_info.value.code == 1


def test_exec_in_container_non_tty_retries_silently_exits_126():
    """Non-TTY mode retries on container failures then exits 126."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "docker",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         patch("sys.stderr"), \
         patch("time.sleep") as mock_sleep, \
         pytest.raises(SystemExit) as exc_info:
        mock_stdin.isatty.return_value = False
        mock_run.return_value = MagicMock(returncode=126)
        _exec_in_container(container_info, ["sessions", "list"])

    assert mock_sleep.call_count == 9  # 10 attempts, 9 sleeps
    assert exc_info.value.code == 126


def test_exec_in_container_propagates_hermes_exit_code():
    """Non-zero exit from hermes inside container is propagated, not retried."""
    from hermes_cli.main import _exec_in_container

    container_info = {
        "backend": "docker",
        "container_name": "hermes-agent",
        "exec_user": "hermes",
        "hermes_bin": "/data/current-package/bin/hermes",
    }

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         patch("time.sleep") as mock_sleep, \
         pytest.raises(SystemExit) as exc_info:
        mock_stdin.isatty.return_value = True
        # Exit code 1 = hermes error (not a docker failure), should not retry
        mock_run.return_value = MagicMock(returncode=1)
        _exec_in_container(container_info, ["chat"])

    mock_sleep.assert_not_called()  # No retries
    mock_run.assert_called_once()   # Only one attempt
    assert exc_info.value.code == 1
