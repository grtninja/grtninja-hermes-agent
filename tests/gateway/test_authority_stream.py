"""Canonical execution stream through production API binding and real model SSE."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tests.fixtures.child_env import hermes_child_env


@pytest.mark.parametrize("mode", ["ordinary", pytest.param("blocked", marks=pytest.mark.platforms("linux"))])
def test_authority_stream_has_one_order_and_rejects_retired_callbacks(tmp_path, mode):
    repo = Path(__file__).resolve().parents[2]
    home, state = tmp_path / 'home', tmp_path / 'state'
    home.mkdir()
    state.mkdir()
    env = hermes_child_env(('PATH', 'SYSTEMROOT', 'LANG', 'TZ'))
    env.update(HOME=str(home), USERPROFILE=str(home), HERMES_HOME=str(state), PYTHONPATH=str(repo), STREAM_PROBE_MODE=mode)
    result = subprocess.run([sys.executable, str(Path(__file__).parent / 'fixtures' / 'authority_stream_peer.py')],
                            cwd=tmp_path, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=100, check=False)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    receipt = json.loads((state / 'receipt.json').read_text())
    print(json.dumps(receipt))
    assert receipt['real_terminal_effect'] and receipt['same_stamps'] and receipt['stale_callback_inert']
