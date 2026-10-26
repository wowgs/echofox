"""One client connection (docs/reference/6-protocol.md): its first message says what it is: an info request
(info.py), a download or removal of a model variant (variants.py), or the start of a recording (session.py)."""
import asyncio
import json

import info
import variants
from session import Session, parse_start


async def handle(ws, models, args, make_stream=None):
    """One connection. `args`: the recording settings (settings.recording_settings); `make_stream`: Session's."""
    async def send(**m):
        await ws.send(json.dumps(m, ensure_ascii=False))

    try:
        first = json.loads(await ws.recv())
    except (ValueError, TypeError):
        first = None
    if isinstance(first, dict) and first.get("type") == "info":
        await send(**await asyncio.to_thread(info.info, args, models))
        await ws.close()
        return
    if isinstance(first, dict) and first.get("type") in ("download", "remove"):
        await (variants.download if first["type"] == "download" else variants.remove)(ws, send, first, models, args)
        await ws.close()
        return
    try:
        start = parse_start(first, models, args)
    except ValueError as e:
        await send(type="error", message=str(e))
        await ws.close()
        return
    await Session(ws, send, models, args, start, make_stream).run()
