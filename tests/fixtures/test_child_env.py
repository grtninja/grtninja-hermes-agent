"""hermes_child_env: a rebuilt child env always keeps the suite's opt-outs."""

import subprocess
import sys

from tests.fixtures.child_env import hermes_child_env


def test_a_scrubbed_child_still_runs_with_lazy_installs_off(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    monkeypatch.setenv("HERMES_TEST_ISOLATION", str(tmp_path))
    env = hermes_child_env(lambda k: not k.startswith("HERMES_"), HERMES_HOME=str(tmp_path))
    probe = ("import os, json; print(json.dumps([os.environ.get(k) for k in "
             "('HERMES_DISABLE_LAZY_INSTALLS', 'HERMES_TEST_ISOLATION', 'HERMES_HOME')]))")
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                         timeout=60, check=True).stdout
    assert out.strip() == f'["1", "{tmp_path}", "{tmp_path}"]'


def test_outside_the_suite_the_opt_out_holds_and_no_isolation_marker_is_invented(monkeypatch):
    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    monkeypatch.delenv("HERMES_TEST_ISOLATION", raising=False)
    env = hermes_child_env(("PATH",), HOME="/nonexistent")
    assert env["HERMES_DISABLE_LAZY_INSTALLS"] == "1"
    assert "HERMES_TEST_ISOLATION" not in env
    assert env["HOME"] == "/nonexistent"
