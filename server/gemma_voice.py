"""The EchoFox dictation server: speech to text with Gemma 4 E4B in llama.cpp, for the menu bar app and try_wav.py.

It starts the parts and serves the WebSocket protocol (docs/reference/6-protocol.md): protocol.py takes each
connection, session.py a recording, dictation.py the model's requests. How a recording becomes text is in
docs/reference/1-server.md; the settings and the config file in docs/reference/2-config.md and settings.py.
"""
import argparse
import asyncio
import json
import logging
import os
import signal

from websockets.asyncio.server import serve

import constants
import protocol
import settings
import llama
import vad
from llama import Models

log = logging.getLogger("gemma_voice")


async def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                epilog="The settings are in the config file only. The server watches the file.")
    p.add_argument("--config", default=None, help=f"the config file (default {settings.config_file()})")
    p.add_argument("--ignore-selection", action="store_true",
                   help="do not follow the model chosen in the menus, and never start or stop llama-server agents "
                        "(for a test server)")
    cli = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = cli.config or settings.config_file()
    settings.migrate(path)
    current = settings.resolve(settings.file_settings(path) or {})
    st = settings.apply(current)
    models = Models(current["models"], manage=not cli.ignore_selection,
                    models_folder=constants.path(current["modelsFolder"]))
    await asyncio.to_thread(vad.shared)  # the speech detector loads now, not in the event loop at the first recording
    if cli.ignore_selection:
        await models.get(next(iter(current["models"])))  # the default model answers before the first recording
    log.info("settings: %s", json.dumps(current, ensure_ascii=False))
    if os.environ.get(llama.APP_VERSION):
        log.info("the bundled app's version: %s", os.environ[llama.APP_VERSION])
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))
    watcher = settings.ConfigWatcher(path, models, st, current, stop, follow=not cli.ignore_selection)
    watching = asyncio.create_task(watcher.run())
    async with serve(lambda ws: protocol.handle(ws, models, st), current["host"], current["port"],
                     max_size=None) as server:
        log.info("listening on ws://%s:%d, models: %s (default %s), config %s", current["host"], current["port"],
                 ", ".join(current["models"]), next(iter(current["models"])), path)
        await stop
        # A restart (launchd, a changed host or port) lets the running recordings end: no new connections, the open
        # ones go on until their text is sent. launchd waits for it (ExitTimeOut, LAUNCHD_EXIT_TIMEOUT_S).
        server.close(close_connections=False)
        try:
            await asyncio.wait_for(server.wait_closed(), constants.STOP_WAIT_S)
        except TimeoutError:
            log.warning("recordings still running after %d s: the server ends anyway", constants.STOP_WAIT_S)
        log.info("the server ends")
    watching.cancel()


if __name__ == "__main__":
    asyncio.run(main())
