"""Moonlight Sync's decky entry point: wires ``decky`` to the backend package.

All logic lives in ``py_modules/moonlight_sync`` (spec 3.6.3); this file only
builds the :class:`~moonlight_sync.backend.Backend` from decky's constants and
delegates one line per callable. The frontend calls these by name through
``@decky/api``'s ``callable``; every one returns ``{"ok": ...}`` and never
raises.
"""

import asyncio

import decky

from moonlight_sync.backend import Backend


class Plugin:
    # Class attributes, not ``__init__`` state. decky-loader instantiates the
    # class only when ``plugin.json``'s ``api_version`` is > 0 (ours is 1):
    # ``sandboxed_plugin.py`` does ``self.Plugin = module.Plugin()`` there and
    # ``self.Plugin = module.Plugin`` -- the bare class -- for api_version 0,
    # where every method is then called as ``method(self.Plugin, ...)``. With
    # the state declared here the module is correct under both conventions
    # (``tests/test_main.py`` drives it both ways).
    _backend = None
    _startup = None

    # Classmethods so that ``self._ready()`` resolves whichever object the
    # loader put in ``self``: bound to the class from an instance and from the
    # class itself, so the delegating callables below read the same way under
    # both conventions.
    @classmethod
    def _get(cls):
        if cls._backend is None:
            cls._backend = Backend(
                settings_dir=decky.DECKY_PLUGIN_SETTINGS_DIR,
                log_dir=decky.DECKY_PLUGIN_LOG_DIR,
                plugin_dir=decky.DECKY_PLUGIN_DIR,
                home=decky.DECKY_USER_HOME,
                plugin_version=getattr(decky, "DECKY_PLUGIN_VERSION", ""),
                emit=decky.emit,
                logger=decky.logger,
            )
        return cls._backend

    @classmethod
    async def _ready(cls):
        """The backend, once its startup (install check, file seeding) has run."""
        backend = cls._get()
        if cls._startup is None:
            cls._startup = asyncio.ensure_future(backend.startup())
        await asyncio.shield(cls._startup)
        return backend

    async def _main(self):
        await self._ready()

    async def _unload(self):
        if self._backend is not None:
            await self._backend.unload()

    async def _uninstall(self):
        pass

    # -- versions, diagnostics -------------------------------------------
    async def cli_version(self):
        return await (await self._ready()).cli_version()

    async def cli_capabilities(self):
        return await (await self._ready()).cli_capabilities()

    async def doctor(self):
        return await (await self._ready()).doctor()

    async def log_tail(self, n=50):
        return await (await self._ready()).log_tail(n)

    # -- library, hosts --------------------------------------------------
    async def status(self):
        return await (await self._ready()).status()

    async def list_apps(self):
        return await (await self._ready()).list_apps()

    async def list_cached(self, host):
        return await (await self._ready()).list_cached(host)

    async def check_host(self, name, force=False):
        return await (await self._ready()).check_host(name, force)

    async def hosts(self):
        return await (await self._ready()).hosts()

    async def set_host(self, name):
        return await (await self._ready()).set_host(name)

    async def add_host(self, name):
        return await (await self._ready()).add_host(name)

    async def forget_host(self, name):
        return await (await self._ready()).forget_host(name)

    async def wake_host(self, name):
        return await (await self._ready()).wake_host(name)

    async def set_wake_mac(self, name, mac=None):
        return await (await self._ready()).set_wake_mac(name, mac)

    # -- plugin files ----------------------------------------------------
    async def get_settings(self):
        return await (await self._ready()).get_settings()

    async def set_settings(self, patch):
        return await (await self._ready()).set_settings(patch)

    async def set_default_layout(self, url=None, title=None):
        return await (await self._ready()).set_default_layout(url, title)

    async def get_ignored(self):
        return await (await self._ready()).get_ignored()

    async def set_ignored(self, name, ignored):
        return await (await self._ready()).set_ignored(name, ignored)

    async def reset_match_cache(self):
        return await (await self._ready()).reset_match_cache()

    async def write_owned_apps(self, steamid3, apps):
        return await (await self._ready()).write_owned_apps(steamid3, apps)

    async def pending(self):
        return await (await self._ready()).pending()

    async def clear_pending(self, key):
        return await (await self._ready()).clear_pending(key)

    async def layouts(self):
        return await (await self._ready()).layouts()

    async def record_layout(self, shortcut_appid, real_appid, result, url):
        return await (await self._ready()).record_layout(shortcut_appid, real_appid, result, url)

    # -- long runs -------------------------------------------------------
    async def start_sync(self, opts=None):
        return await (await self._ready()).start_sync(opts)

    async def start_art_refetch(self, opts=None):
        return await (await self._ready()).start_art_refetch(opts)

    async def start_remove_all(self, opts=None):
        return await (await self._ready()).start_remove_all(opts)

    async def stop_sync(self):
        return await (await self._ready()).stop_sync()

    async def sync_state(self):
        return await (await self._ready()).sync_state()

    # -- matching (the Titles page) -------------------------------------
    async def search(self, term):
        return await (await self._ready()).search(term)

    async def pin(self, name, steam=None, sgdb=None, none=False):
        return await (await self._ready()).pin(name, steam, sgdb, none)

    async def unpin(self, name):
        return await (await self._ready()).unpin(name)

    # -- SteamGridDB key -------------------------------------------------
    async def sgdb_key_state(self):
        return await (await self._ready()).sgdb_key_state()

    async def set_sgdb_key(self, key):
        return await (await self._ready()).set_sgdb_key(key)

    async def clear_sgdb_key(self):
        return await (await self._ready()).clear_sgdb_key()

    async def test_sgdb_key(self):
        return await (await self._ready()).test_sgdb_key()

    async def start_sgdb_key_fetch(self):
        return await (await self._ready()).start_sgdb_key_fetch()

    async def cancel_sgdb_key_fetch(self):
        return await (await self._ready()).cancel_sgdb_key_fetch()
