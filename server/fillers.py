"""Hesitation sounds out of the transcription: "э", "а-а", "мм" and the like, by a list for each language.

The model writes what it hears, and a speaker's hesitations come back as words: in 450 recordings of Russian speech
(2026-10-14 to 2026-10-18, Gemma 4 E4B), "э" and "э-э" 124 times, "а-а" 10, "м", "мм", "хм", "ам" and the like 28; in
every one read in its context it was a hesitation. A list holds only such sounds, never a word that is also a word
of the language: a lone "а" is mostly the conjunction, and "ну", "вот", "типа" often carry the phrase, so they stay.

A sound matches in any length: letters said longer ("ээ", "ммм", "хмм") and repeats ("э-э-э") count as the listed
form ("э", "м", "хм", "э-э"). One right after a number stays, since "м" and "мм" are also metres and millimetres.
With the sound go the marks right after it, and a comma before it stays ("возникает, а-а, у меня" →
"возникает, у меня"); a capital that opened a sentence passes to the next
word ("Э, ну это" → "Ну это"), and a sentence that ended with the sound ends where it stops ("сделай, э." →
"сделай.").

The lists are in the language table (languages.json, "fillers"); the config's "languages" changes a language's list,
{"ru": {"fillers": [...]}}, and an empty list turns the removal off for it.
"""
import re

import languages

WORD = re.compile(r"(?<![\w-])([^\W\d_]+(?:-[^\W\d_]+)*)(?![\w-])")
AFTER = re.compile(r"[,;:]*([.!?…]*)[,;:]*\s*")  # the marks right after a sound: they belonged to it
SENTENCE_END = re.compile(r"[.!?…]\s*$")


def form(word):
    """The listed form of a sound: lower case, a letter said longer once, a repeat once ("Э-э-э" → "э-э")."""
    w = re.sub(r"(.)\1+", r"\1", word.lower())
    return re.sub(r"^(\w+)(?:-\1)+$", r"\1-\1", w)


def words(language, configured=None):
    """The sounds for `language` ("ru", "ru-RU"; "" for the speech's own: none): the config's list for it if it
    has one (`configured`: the config's "languages"), else the table's."""
    return {form(w) for w in languages.fillers(language, configured)} if language else set()


def _next(rest, sounds, done):
    """The next sound in `rest`; `done` is the text before it, to tell a unit after a number."""
    for m in WORD.finditer(rest):
        if form(m.group(1)) in sounds and not re.search(r"\d\s*$", done + rest[:m.start()]):
            return m
    return None


def remove(text, sounds):
    """`text` without the `sounds` (forms, see words())."""
    if not sounds or not text:
        return text
    done, rest = "", text
    while m := _next(rest, sounds, done):
        kept = (done + rest[:m.start()]).rstrip()
        tail = AFTER.match(rest, m.end())
        if tail.group(1) and kept and not SENTENCE_END.search(kept):
            kept = kept.rstrip(",;:") + tail.group(1)[0]  # the sentence ended with the sound
        after = rest[tail.end():]
        if m.group(1)[0].isupper() and (not kept or SENTENCE_END.search(kept)) and after[:1].islower():
            after = after[0].upper() + after[1:]  # the sound opened the sentence
        done, rest = kept + (" " if kept and after else ""), after
    return re.sub(r"\s{2,}", " ", done + rest).strip()
