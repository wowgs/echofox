"""A model's variants for a client (docs/reference/6-protocol.md, "Download a model"): which are downloaded, and the
download and removal messages; the work is in downloads.py."""
import asyncio
import contextlib
import json
import os

from websockets.exceptions import ConnectionClosed

import catalog
import downloads

DOWNLOAD_PROGRESS_S = 0.5   # at most one "progress" message of a download per this long


async def download(ws, send, m, models, args):
    """One download of a model's variant (docs/reference/6-protocol.md) into the registry's models folder: its
    progress until it ends; a cancel message stops it. The download goes on when the client leaves."""
    try:
        job = downloads.start(str(m.get("catalog") or catalog.DEFAULT), str(m.get("variant") or ""),
                              models.models_folder)
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
    """Deletes a variant's own files from the registry's models folder. The variant of the model in memory goes too:
    after the running recording its llama-server ends first (Models.release), whichever model it is (the menu's, or
    another that a client asked for), and the model has no files until they are downloaded again."""
    cat, variant = str(m.get("catalog") or catalog.DEFAULT), str(m.get("variant") or "")
    try:
        freed = await models.release(cat, variant, lambda: downloads.remove(cat, variant, models.models_folder))
        await send(type="removed", bytes=freed)
    except (ValueError, OSError, RuntimeError) as e:
        await send(type="error", message=str(e))


def variants(entry, models_folder):
    """The variants of a registry entry's model, for the settings window: the one in force, and each with its name,
    the bytes of its files, whether it is the catalog's default and whether its files are all in the models folder."""
    vid, _ = catalog.variant(entry)
    default = catalog.of(entry).get("defaultVariant")
    running = downloads.running()
    out = []
    for v, spec in (catalog.of(entry).get("variants") or {}).items():
        paths = catalog.files({**entry, "variant": v}, models_folder)
        out.append({"id": v, "name": spec["name"], "bytes": sum(f["bytes"] for f in spec["files"].values()),
                    **({"default": True} if v == default else {}),
                    **({"memoryBytes": spec["memoryBytes"]} if "memoryBytes" in spec else {}),
                    "downloaded": all(os.path.isfile(p) for p in paths.values()),
                    **({"downloading": True} if (entry.get("catalog", catalog.DEFAULT), v) in running else {})})
    return {"variant": vid, "variants": out}

