"""Moonlight Sync's Python backend.

decky-loader puts ``<plugin>/py_modules`` on ``sys.path``, so ``main.py``
imports this package as ``moonlight_sync``. Nothing in here imports
``decky``: ``main.py`` hands every loader value (directories, ``emit``, the
logger) to :class:`moonlight_sync.backend.Backend`, which is what lets the
whole backend run under plain pytest against ``tests/fake_cli.py``.

Modules:

- ``backend``  the callables, the subprocess runner and the NDJSON relay
- ``install``  bundled-CLI version reading and the atomic install/upgrade
- ``settings`` the plugin's own JSON files (settings, ignore, owned apps,
  pending, layouts), all written atomically
- ``keys``     the SteamGridDB key sources, mirroring the CLI's precedence
- ``events``   NDJSON parsing and the restart decision table (spec 3.9)
"""
