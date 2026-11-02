"""The info message (docs/reference/6-protocol.md, "Server information"): what a client needs to know of this server."""
import adapters
import catalog
import constants
import languages
import settings
from variants import variants


def info(args, models=None):
    """What a client needs to know of this server: the protocol, the audio, the waits, the languages the menu's model
    names (with their notes and hesitation sounds) and the notes of every language, the adapters (with their context
    defaults), the menu's model (its catalog entry, prompt template and variants), and the settings it may show and
    change (settings.schema). The menu's model is the registry's (Models.selected); when the menu names no model of
    this server, the default (Models.name_for), so that the settings window shows a model's settings. No `models`
    (the tests): no model."""
    enabled = set(getattr(args, "adapters", None) or [])
    entries = models.entries if models else {}
    name = (models.selected or models.name_for(None)) if models else None
    entry = entries.get(name) if name else None
    folder = models.models_folder if models else None
    model = catalog.of(entry)
    codes = model.get("languages") or languages.codes()
    table = languages.table()
    return {"type": "info", "interface": constants.PROTOCOL_INTERFACE, "adapterInterface": adapters.registry.INTERFACE,
            "sampleRate": constants.RATE, "encoding": constants.ENCODING,
            "textWaitSeconds": constants.TEXT_WAIT_S, "maxRecordingSeconds": args.max_recording_seconds,
            "languages": sorted(({"code": c, "name": table[c]["name"], "notes": table[c].get("notes", []),
                                  "fillers": table[c].get("fillers", [])} for c in codes if c in table),
                                key=lambda l: l["name"]),
            "commonNotes": table.get(languages.ALL, {}).get("notes", []),
            "adapters": [p.info(enabled) for p in adapters.registry.packages().values()],
            "models": list(entries),
            "model": {"name": name, "catalog": (entry or {}).get("catalog", catalog.DEFAULT) if entry else None,
                      "title": model.get("name"),
                      "prompt": model.get("prompt"), "maxAudioSeconds": model.get("maxAudioSeconds"),
                      "tokenWeights": model.get("tokenWeights"),
                      **(variants(entry, folder) if entry else {})},
            "settings": settings.schema(args, entry, folder)}

