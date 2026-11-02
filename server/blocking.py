"""A blocking call in a thread that its caller can cancel: the model's requests of a recording (dictation.py)."""
import asyncio
import contextlib


async def run(fn, *args, cancel=None):
    """fn(*args) in a thread. If the caller is cancelled, cancel() stops fn, and this waits until fn has returned,
    then raises: the next recording starts only when the model is free. asyncio.wait, not asyncio.shield: a shielded
    task logs its exception as an error when the caller is cancelled (Python 3.14), and fn raises when it is stopped."""
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    try:
        await asyncio.wait({task})
    except asyncio.CancelledError:
        if cancel:
            cancel()
        with contextlib.suppress(Exception):
            await task
        raise
    return task.result()
