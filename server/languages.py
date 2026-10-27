"""The language table (languages.json): for each language code, its name, the notes added to the prompt for it, and
its hesitation sounds (fillers.py); under ALL, the notes of every language. A note may name the language as
{LANGUAGE}. The config's "languages" changes them: {"*": {"notes": [...]}, "ru": {"notes": [...], "fillers": [...]}};
an empty list turns them off. A language belongs to no model: a model's catalog entry says which languages its prompt
names."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "languages.json")
ALL = "*"  # the entry of the notes of every language
# The language of the terms (the common notes say that the speech mixes in English terms): its speech gets neither the
# common notes nor the terms of the context
TERMS = "en"


_read = {}  # the table as last read, and its file's change time


def table():
    """The table as in the file, ALL among the codes: read again only when the file changed. The callers do not change
    what it gives."""
    mtime = os.stat(PATH).st_mtime_ns
    if _read.get("mtime") != mtime:
        with open(PATH, encoding="utf-8") as f:
            _read.update(mtime=mtime, table=json.load(f))
    return _read["table"]


def codes():
    """The codes of the languages, without ALL."""
    return [c for c in table() if c != ALL]


def base(language):
    """"ru-RU" → "ru"."""
    return (language or "").split("-")[0].lower()


def name(language):
    code = base(language)
    return table().get(code, {}).get("name") if code != ALL else None


def _field(code, key, configured):
    own = ((configured or {}).get(code) or {}).get(key)
    return list(own) if isinstance(own, list) else list(table().get(code, {}).get(key, []))


def notes(language, configured=None):
    """The lines added to the prompt for the language, {LANGUAGE} filled in: the notes of every language (none for an
    unnamed language and for TERMS), then the language's own; each the config's, else the table's."""
    code, called = base(language), name(language)
    common = _field(ALL, "notes", configured) if called and code != TERMS else []
    return [n.replace("{LANGUAGE}", called or "its original language")
            for n in common + (_field(code, "notes", configured) if code != ALL else [])]


def fillers(language, configured=None):
    """The hesitation sounds of the language: the config's, else the table's."""
    code = base(language)
    return _field(code, "fillers", configured) if code != ALL else []
