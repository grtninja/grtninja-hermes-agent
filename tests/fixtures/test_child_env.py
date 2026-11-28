"""hermes_child_env: a rebuilt child env always keeps the suite's opt-outs."""

import json
import subprocess
import sys

from tests.fixtures.child_env import hermes_child_env


def test_a_scrubbed_child_still_runs_with_lazy_installs_off(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    env = hermes_child_env(lambda k: not k.startswith("HERMES_"), HERMES_HOME=str(tmp_path))
    probe = ("import os, json; print(json.dumps([os.environ.get(k) for k in "
             "('HERMES_DISABLE_LAZY_INSTALLS', 'HERMES_HOME')]))")
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                         timeout=60, check=True).stdout
    assert json.loads(out) == ["1", str(tmp_path)]


def test_outside_the_suite_the_opt_out_still_holds(monkeypatch):
    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    env = hermes_child_env(("PATH",), HOME="/nonexistent")
    assert env["HERMES_DISABLE_LAZY_INSTALLS"] == "1"
    assert env["HOME"] == "/nonexistent"
