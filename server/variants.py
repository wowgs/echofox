"""A model's variants for a client (docs/reference/6-protocol.md, "Download a model"): which are downloaded, and the
download and removal messages; the work is in downloads.py."""
import asyncio
import contextlib
import json
import os

from websockets.exceptions import ConnectionClosed

import catalog
import constants
import downloads

DOWNLOAD_PROGRESS_S = 0.5   # at most one "progress" message of a download per this long


def models_folder(args):
    return getattr(args, "models_folder", None) or constants.path(constants.MODELS_FOLDER)


async def download(ws, send, m, models, args):
    """One download of a model's variant (docs/reference/6-protocol.md): its progress until it ends; a cancel
    message stops it. The download goes on when the client leaves."""
    try:
        job = downloads.start(str(m.get("catalog") or catalog.DEFAULT), str(m.get("variant") or ""), models_folder(args))
    except ValueError as e:
        await send(type="error", message=str(e))
        return

    async def cancels():
        async for message in ws:
            with contextlib.suppress(ValueError, TypeError, AttributeError):
                if json.loads(message).get("type") == "cancel":
                    job.cancelled.set()
                    return

    listening = asyncio.ensure_future(cancels())
    try:
        while not await asyncio.to_thread(job.finished.wait, DOWNLOAD_PROGRESS_S):
            await send(type="progress", bytes=job.done, total=job.total)
        if job.error:
            await send(type="error", message=job.error)
        elif job.cancelled.is_set():
            await send(type="error", message="the download was cancelled")
        else:
            await send(type="progress", bytes=job.total, total=job.total)
            await send(type="downloaded")
    except ConnectionClosed:
        pass  # the client left; the download goes on
    finally:
        listening.cancel()


async def remove(ws, send, m, models, args):
    """Deletes a variant's own files. The one in force of the menu's model goes too: after the running recording the
    model leaves memory (its llama-server ends), and the next dictation has no model until one is downloaded."""
    entries = getattr(models, "entries", None) or {}
    name = getattr(models, "selected", None)
    entry = entries.get(name) if name else None
    cat = str(m.get("catalog") or catalog.DEFAULT)
    in_force = catalog.variant(entry)[0] if entry and entry.get("catalog", catalog.DEFAULT) == cat else None
    variant = str(m.get("variant") or "")
    try:
        if in_force is not None and catalog.variant({"catalog": cat, "variant": variant})[0] == in_force:
            async with models.recording:
                await models.activate(None)
                freed = await asyncio.to_thread(downloads.remove, cat, variant, models_folder(args))
        else:
            freed = await asyncio.to_thread(downloads.remove, cat, variant, models_folder(args), in_force)
        await send(type="removed", bytes=freed)
    except (ValueError, OSError, RuntimeError) as e:
        await send(type="error", message=str(e))


def variants(entry, models_folder):
    """The variants of a registry entry's model, for the settings window: the one in force, and each with its name,
    the bytes of its files and whether they are all in the models folder."""
    vid, _ = catalog.variant(entry)
    folder = models_folder or constants.path(constants.MODELS_FOLDER)
    running = downloads.running()
    out = []
    for v, spec in (catalog.of(entry).get("variants") or {}).items():
        paths = catalog.files({**entry, "variant": v}, folder)
        out.append({"id": v, "name": spec["name"], "bytes": sum(f["bytes"] for f in spec["files"].values()),
                    **({"memoryBytes": spec["memoryBytes"]} if "memoryBytes" in spec else {}),
                    "downloaded": all(os.path.isfile(p) for p in paths.values()),
                    **({"downloading": True} if (entry.get("catalog", catalog.DEFAULT), v) in running else {})})
    return {"variant": vid, "variants": out}

