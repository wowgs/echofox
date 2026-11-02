"""The registry of models (Models): the config's model entries by name, the models folder, the model chosen in the
menus, and the decision which one model is in memory. The config watcher (settings.ConfigWatcher) only tells it what
the config says (configure); the registry's own loop (run) keeps the menu's model in memory, and takes an idle one out.
A model on this Mac runs as its own llama-server (llama_process.py), which the registry starts and ends; a recording
asks it for the model (get) and talks to it through the model's client (llama_client.py)."""
import asyncio
import contextlib
import logging
import threading
import time
import urllib.parse

import catalog
import constants
import llama_process
from llama_client import LlamaModel

log = logging.getLogger("echofox-server")
UNKNOWN = object()  # Models.active before the first activation, and after the registry changed
RETRY_S = 2  # how often the menu's model is made the one in memory again while it is not: after a client's recording
             # on another model, or while it cannot start (its files are missing, for one)


class Models:
    """The models of the config's registry, by name; the first is the default. Only one is in memory at a time: the
    llama-server of the active model runs as this process's child, and none other (unless `manage` is off: the test
    server, whose llama-server test_server.sh starts). `make(name, entry)` makes the model object (tests put a stub
    here). `models_folder` and `chosen` are the config's modelsFolder and "model" (configure)."""

    def __init__(self, entries, make=LlamaModel, manage=True, models_folder=constants.MODELS_FOLDER, chosen=None):
        self.make, self.manage, self.models = make, manage, {}
        self.entries, self.models_folder = dict(entries), constants.path(models_folder)
        # The config's "model", the choice in the menus (None: the config names none); `selected` is the model it
        # names on this server
        self.chosen = chosen
        # The model that this server last made the only one in memory (None: no model); activating it again only
        # checks that its llama-server still runs and answers
        self.active = UNKNOWN
        # The menu's model that could not be made the one in memory, and why: logged once, until either changes
        self.failed = None
        # The running llama-server, its command and its registry entry; `closing` is set when the server ends
        self.proc, self.argv, self.entry, self.closing = None, None, None, threading.Event()
        # When the running llama-server started, until it answers: the log says how long its model took to load
        self.loading = None
        # When a recording last asked for a model (get), or was seen running: the idle time counts from here
        self.used = time.monotonic()
        # One recording at a time: its requests share the model's slots, and a cancel stops all requests of the
        # model; loading or switching a model waits for the running recording. A second recording waits.
        self.in_use = asyncio.Lock()
        # Set by configure: the registry's loop acts at once, not at its next look
        self.changed = asyncio.Event()

    def configure(self, entries, models_folder, chosen):
        """The config's model settings, after the running recording (the watcher holds `in_use`): the registry's
        entries, the models folder (the config's value) and the menu's choice. New entries or a new models folder:
        each model is made again, and its llama-server starts again if its command changed (another variant or
        folder). The registry's loop then makes the menu's model the one in memory."""
        entries, folder = dict(entries), constants.path(models_folder)
        if entries != self.entries or folder != self.models_folder:
            self.entries, self.models_folder, self.models, self.active, self.failed = entries, folder, {}, UNKNOWN, None
            log.info("models: %s", ", ".join(entries))
        self.chosen = chosen
        self.changed.set()

    def name_for(self, name):
        """The model of a name, a client's or the menu's: no name, the default (the registry's first); a name of the
        registry, that model; any other name, None."""
        if not name:
            return next(iter(self.entries), None)
        return name if name in self.entries else None

    @property
    def selected(self):
        """The model chosen in the menus, on this server (name_for): the one the registry keeps in memory."""
        return self.name_for(self.chosen)

    async def get(self, name):
        """The model, the only one in memory; loaded first if it left memory."""
        self.used = time.monotonic()
        await self.activate(name)
        if name not in self.models:
            self.models[name] = self.make(name, self.entries[name])
        return self.models[name]

    def _stop(self):
        if self.proc is not None:
            llama_process.end(self.proc)
        self.proc, self.argv, self.entry = None, None, None

    def _run(self, entry):
        """The entry's llama-server runs: started if none runs, if the one running ended, or if its command changed
        (another variant or models folder)."""
        argv = llama_process.command(entry, self.models_folder)
        if self.proc is not None and self.proc.poll() is None and argv == self.argv:
            return
        self._stop()
        llama_process.end_stale(urllib.parse.urlparse(entry["llamaServer"]).port or 80)
        self.proc, self.argv, self.entry = llama_process.spawn(argv), argv, entry
        self.loading = time.monotonic()

    async def activate(self, name):
        """Makes `name` the only model in memory; None: no model at all. When it already is, starts its llama-server
        again if it ended, and checks that it answers. Raises RuntimeError if it cannot start or does not answer."""
        entry = self.entries.get(name) if name else None
        if self.manage:
            if entry is not None and llama_process.local(entry):
                await asyncio.to_thread(self._run, entry)
            else:
                await asyncio.to_thread(self._stop)
            self.active = name
        if entry is not None and not await asyncio.to_thread(llama_process.wait_healthy,
                                                             entry["llamaServer"].rstrip("/"),
                                                             constants.MODEL_START_S, self.closing):
            raise RuntimeError(f"llama-server of {name} at {entry['llamaServer']} does not answer")
        if self.loading is not None:
            log.info("model %s: loaded in %.1f s", name, time.monotonic() - self.loading)
            self.loading = None

    async def follow_menu(self):
        """With `manage`, after the running recording, makes the menu's model the only one in memory; none if the menu
        names no model of this server. A model that cannot start is tried again at the next call (its files may
        come), and the reason is logged once for each model and reason."""
        if not self.manage or self.selected == self.active:
            return
        async with self.in_use:
            name = self.selected  # the choice may have changed during the recording
            if name == self.active:
                return
            if self.failed is None or self.failed[0] != name:
                log.info("the menu's model is %s: only it stays in memory", name or "not on this server")
            try:
                await self.activate(name)
                self.failed = None
            except Exception as e:
                if self.failed != (name, str(e)):
                    log.error("cannot make %s the model in memory: %s", name, e,
                              exc_info=not isinstance(e, RuntimeError))
                self.failed = (name, str(e))

    async def unload_when_idle(self, seconds):
        """Ends the llama-server when no recording asked for the model for `seconds()` (the setting
        modelIdleSeconds; 0: never), after the running recording. The model stays the active one, so the menu's
        choice does not load it again; the next recording's get() starts its llama-server first."""
        while True:
            await asyncio.sleep(constants.IDLE_POLL_S)
            if self.in_use.locked() or self.proc is None or self.proc.poll() is not None:
                self.used = max(self.used, time.monotonic()) if self.in_use.locked() else self.used
                continue
            idle = seconds()
            if not idle or time.monotonic() - self.used < idle:
                continue
            async with self.in_use:
                if self.proc is not None and time.monotonic() - self.used >= idle:
                    await asyncio.to_thread(self._stop)
                    log.info("model %s: left memory after %.0f s without a recording", self.active, idle)

    async def _follow_menu_always(self):
        while True:
            await self.follow_menu()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.changed.wait(), RETRY_S)
            self.changed.clear()

    async def run(self, idle_seconds):
        """The registry's own work while the server runs, with `manage`: the menu's model stays in memory (follow_menu,
        at once after configure, else every RETRY_S), and leaves it after `idle_seconds()` without a recording
        (unload_when_idle). Without `manage` (the test server), nothing."""
        if self.manage:
            await asyncio.gather(self._follow_menu_always(), self.unload_when_idle(idle_seconds))

    async def release(self, catalog_id, variant, delete):
        """Runs `delete` (in a thread) after the running recording, with no llama-server on the files of that variant
        of that catalog entry: the one that runs on them leaves memory first, so the registry's loop tries the menu's
        model again (follow_menu). The result of `delete`."""
        async with self.in_use:
            vid = catalog.variant({"catalog": catalog_id, "variant": variant})[0]
            if (self.entry is not None and (self.entry.get("catalog") or catalog.DEFAULT) == catalog_id
                    and catalog.variant(catalog.in_force(self.entry, self.models_folder))[0] == vid):
                await self.activate(None)
            return await asyncio.to_thread(delete)

    def close(self):
        """The server ends: its llama-server ends too, and the model leaves memory. A wait for a model that is loading
        ends at once."""
        self.closing.set()
        if self.manage:
            self._stop()
