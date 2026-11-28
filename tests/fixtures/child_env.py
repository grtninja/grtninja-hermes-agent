"""The environment for a Hermes process a test or eval spawns with a rebuilt env.

Harnesses that make a child "look like a real install" rebuild its env from a
short host allowlist (``PATH``/``LANG``/``TZ``) or strip every ``HERMES_*``
variable. Both shapes also drop the opt-outs ``tests/conftest.py`` sets for the
whole suite, and a Hermes boot in a fresh home without them spawns the detached
default-plugins installer: it outlives the child, provisions a PM runtime into
the temp home and races the test's cleanup (``Directory not empty``) while
loading the runner. Building the env here keeps those opt-outs in every child.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

#: Suite-wide guards a spawned Hermes child must keep, with the value used when
#: the parent does not carry one (an eval run outside pytest).
#: ``HERMES_DISABLE_LAZY_INSTALLS`` stops on-demand installs and the boot-time
#: default-plugins installer. ``HERMES_TEST_ISOLATION`` is deliberately not here:
#: it also turns on strict tui_gateway contract checks, which changes what the
#: child answers, and the state.db guard already finds a pytest ancestor.
SUITE_OPT_OUTS: dict[str, str] = {
    "HERMES_DISABLE_LAZY_INSTALLS": "1",
}


def hermes_child_env(keep: Iterable[str] | Callable[[str], bool], **overrides: str) -> dict[str, str]:
    """Host vars selected by ``keep``, then the suite opt-outs, then ``overrides``.

    ``keep`` is either the names to copy from ``os.environ`` (the allowlist
    shape) or a predicate over every name (the scrub shape, e.g.
    ``lambda k: not k.startswith("HERMES_")``). The opt-outs come after it so a
    scrub cannot drop them; ``overrides`` come last so a test of the installer
    itself can turn installs back on.
    """
    wanted = keep if callable(keep) else frozenset(keep).__contains__
    env = {name: value for name, value in os.environ.items() if wanted(name)}
    env.update({name: os.environ.get(name) or default for name, default in SUITE_OPT_OUTS.items()})
    env.update(overrides)
    return env
