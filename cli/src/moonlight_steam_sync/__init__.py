"""moonlight-steam-sync: sync a Moonlight host's game list into Steam shortcuts."""

#: The CLI shares the Decky plugin's version (``package.json``'s ``"version"``
#: at the repo root): every plugin release is a CLI release too. The two are
#: bumped together, and ``scripts/build_cli.py`` refuses to build when they
#: differ.
__version__ = "0.10.0"


def version() -> str:
    """The version string ``--version`` and every ``--json`` ``start`` event print.

    Always the literal :data:`__version__`, never installed package metadata:
    ``importlib.metadata`` would answer for whatever distribution is
    installed in the running interpreter -- an editable checkout whose
    ``dist-info`` predates a version bump, or a stray pip install beside the
    zipapp -- rather than for the code that is actually running, and the
    plugin reads this number to decide whether its bundled zipapp is newer
    than the installed CLI.
    """
    return __version__
