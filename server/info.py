"""The info message (docs/reference/6-protocol.md, "Server information"): what a client needs to know of this server."""
import adapters
import catalog
import constants
import languages
import settings
from variants import variants


def info(args, models=None):
    """What a client needs to know of this server: the protocol, the audio, the waits, the languages the menu's model
    names (with their notes and hesitation sounds), the adapters (with their context defaults), the menu's model (its
    catalog entry, prompt template and variants), and the settings it may show and change (settings.schema)."""
    enabled = set(getattr(args, "adapters", None) or [])
    entries = getattr(models, "entries", None) or {}
    name = getattr(models, "selected", None) or next(iter(entries), None)
    entry = entries.get(name) if name else None
    model = catalog.of(entry)
    codes = model.get("languages") or list(languages.table())
    table = languages.table()
    return {"type": "info", "interface": constants.PROTOCOL_INTERFACE, "adapterInterface": adapters.registry.INTERFACE,
            "sampleRate": constants.RATE, "encoding": constants.ENCODING,
            "textWaitSeconds": constants.TEXT_WAIT_S, "maxRecordingSeconds": args.max_recording_seconds,
            "languages": sorted(({"code": c, "name": table[c]["name"], "notes": table[c].get("notes", []),
                                  "fillers": table[c].get("fillers", [])} for c in codes if c in table),
                                key=lambda l: l["name"]),
            "adapters": [p.info(enabled) for p in adapters.registry.packages().values()],
            "models": list(entries),
            "model": {"name": name, "catalog": (entry or {}).get("catalog", catalog.DEFAULT) if entry else None,
                      "title": model.get("name"),
                      "prompt": model.get("prompt"), "maxAudioSeconds": model.get("maxAudioSeconds"),
                      **(variants(entry, getattr(args, "models_folder", None)) if entry else {})},
            "settings": settings.schema(args, entry)}

