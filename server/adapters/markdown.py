"""Markdown → plain text, for replies that an assistant wrote in Markdown (Claude Code, Claude Desktop).

The model that transcribes reads the chat context before the audio. With Markdown in it (lists, **bold**, `code`,
tables), the model wrote the transcription without punctuation and capital letters: one recording, five runs each,
text with punctuation in 1 of 5 runs with this session's Markdown replies, 5 of 5 without context, 5 of 5 with a
session whose replies had little Markdown (2026-10-15, Gemma 4 E4B Q8_0 in llama.cpp). So the context gets plain
prose: the words stay, the marks go, and each heading, list item and table row becomes a sentence.

Code blocks go (code is not speech); inline code keeps its text (identifiers are the terms the speaker says). Links
keep their text, bare URLs go.
"""
import re

FENCE = re.compile(r"^\s*(```|~~~)")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
QUOTE = re.compile(r"^\s*(?:>\s?)+")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL = re.compile(r"<?\bhttps?://[^\s<>()]*[^\s<>().,;:!?]>?")
CODE = re.compile(r"`+([^`]*)`+")
STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
EM = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
STRIKE = re.compile(r"~~(.+?)~~")
HTML = re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
END = re.compile(r"[.!?…:;,]$")


def inline(s):
    s = IMAGE.sub(r"\1", s)
    s = LINK.sub(r"\1", s)
    s = URL.sub("", s)
    s = CODE.sub(r"\1", s)
    s = STRONG.sub(r"\2", s)
    s = EM.sub(r"\2", s)
    s = STRIKE.sub(r"\1", s)
    s = HTML.sub("", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)  # the space left where a URL was
    s = re.sub(r"[,;:]+([.!?])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def sentence(s):
    """A heading, list item or table row as a sentence: with a full stop if it has no ending of its own."""
    return s if not s or END.search(s) else s + "."


def plain(text):
    """Markdown text → paragraphs of plain prose, one per line."""
    paragraphs, current, in_code = [], [], False

    def flush():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw in text.splitlines():
        if FENCE.match(raw):
            in_code = not in_code
            flush()
            continue
        if in_code:
            continue
        if not raw.strip() or RULE.match(raw) or TABLE_RULE.match(raw):
            flush()
            continue
        line = QUOTE.sub("", raw)
        if HEADING.match(line):
            flush()
            current.append(sentence(inline(HEADING.sub("", line))))
            flush()
        elif line.strip().startswith("|"):
            flush()
            cells = [inline(c) for c in line.strip().strip("|").split("|")]
            current.append(sentence(", ".join(c for c in cells if c)))
            flush()
        elif ITEM.match(line):
            flush()
            current.append(sentence(inline(ITEM.sub("", line))))
        else:
            current.append(inline(line))
    flush()
    return "\n".join(p for p in paragraphs if p.strip(" ."))
