"""Compatibility launcher for the local browser-based experiment studio.

The project previously exposed a Tkinter desktop window through this module.
`python gui.py` now starts the loopback-only Python backend and Web UI.
"""

from __future__ import absolute_import

from relay_controller import DemoRelayController
from web_app import LocalWebApplication, create_server, main, parse_args


__all__ = (
    "DemoRelayController",
    "LocalWebApplication",
    "create_server",
    "main",
    "parse_args",
)


if __name__ == "__main__":
    raise SystemExit(main())

