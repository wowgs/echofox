"""The language table (languages.json): for each language code, its name, the notes added to the prompt for it, and
its hesitation sounds (fillers.py). The config's "languages" changes them for a language: {"ru": {"notes": [...],
"fillers": [...]}}; an empty list turns them off. A language belongs to no model: a model's catalog entry says which
languages its prompt names."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "languages.json")


def table():
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def base(language):
    """"ru-RU" → "ru"."""
    return (language or "").split("-")[0].lower()


def name(language):
    return table().get(base(language), {}).get("name")


def _field(language, key, configured):
    code = base(language)
    own = ((configured or {}).get(code) or {}).get(key)
    return list(own) if isinstance(own, list) else list(table().get(code, {}).get(key, []))


def notes(language, configured=None):
    """The lines added to the prompt for the language: the config's, else the table's."""
    return _field(language, "notes", configured)


def fillers(language, configured=None):
    """The hesitation sounds of the language: the config's, else the table's."""
    return _field(language, "fillers", configured)
