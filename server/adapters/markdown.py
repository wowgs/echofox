"""Markdown → plain text, for plugins of chat apps whose assistants write their replies in Markdown.

The model that transcribes reads the chat context before the audio. With Markdown in it (lists, **bold**, `code`,
tables), the model wrote the transcription without punctuation and capital letters: one recording, five runs each,
text with punctuation in 1 of 5 runs with this session's Markdown replies, 5 of 5 without context, 5 of 5 with a
session whose replies had little Markdown (2026-10-15, Claude Code transcripts, Gemma 4 E4B Q8_0 in llama.cpp). So the context gets plain
prose: the words stay, the marks go, and each heading, list item and table row becomes a sentence.

Code blocks go (code is not speech). Inline code keeps its text when it is a term: an identifier, a file, a flag, a
short command (the terms the speaker says). It goes when it is code: a URL, more than CODE_WORDS words, or any of
CODE_CHARS (JSON, calls, assignments, shell pipes), or only marks such as `**`. Its content is set aside before the
other rules, so a URL or a mark in it never eats the backticks around it. Links keep their text, bare URLs go.
Backslash escapes give their character. A table's header row goes; each other row becomes "first cell: the other
cells." (a pipe escaped as \\| stays in its cell). Each sentence made from a heading, list item or table row starts
with a capital letter, as prose does, unless its first word is written with a small one on purpose (iPhone, macOS,
a.py, snake_case).
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
URL = re.compile(r"<?\bhttps?://[^\s()`]*[^\s().,;:!?`*>]>?")  # a backtick or a mark after it is not the URL's
CODE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")  # a code span ends with as many backticks as it began
CODE_CHARS = re.compile(r"[{}\[\]();=<>\"'|\\$`]")
CODE_WORDS = 3
WORDLESS = re.compile(r"[^\w]*")
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")  # a backslash before ASCII punctuation (CommonMark)
CELL = re.compile(r"(?<!\\)\|")
KEPT = re.compile("\ue000(\\d+)\ue001")  # a set-aside piece; private-use characters, not in chat text
STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
EM = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
STRIKE = re.compile(r"~~(.+?)~~")
MARKS = re.compile(r"(?<![\w*_~])(?:\*+|_+|~~)(?![\w*_~])")  # marks left without a pair
HTML = re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
END = re.compile(r"[.!?…:;,]$")


def code_text(content):
    """An inline code span's text: kept if it is a term, "" if it is code."""
    t = content.strip()
    if URL.search(t) or CODE_CHARS.search(t) or len(t.split()) > CODE_WORDS or WORDLESS.fullmatch(t):
        return ""
    return t


def inline(s):
    kept = []

    def keep(text):
        kept.append(text)
        return f"\ue000{len(kept) - 1}\ue001"

    s = CODE.sub(lambda m: keep(code_text(m.group(2))), s)
    s = ESCAPE.sub(lambda m: keep(m.group(1)), s)
    s = s.replace("`", "")  # a backtick without a pair
    s = IMAGE.sub(r"\1", s)
    s = LINK.sub(r"\1", s)
    s = URL.sub("", s)
    s = STRONG.sub(r"\2", s)
    s = EM.sub(r"\2", s)
    s = STRIKE.sub(r"\1", s)
    s = HTML.sub("", s)
    s = MARKS.sub("", s)
    s = KEPT.sub(lambda m: kept[int(m.group(1))], s)
    s = re.sub(r"\(\s*(?:[,;]\s*)*\)", "", s)  # brackets left empty
    s = re.sub(r"\(\s*[,;]\s*", "(", s)
    s = re.sub(r"(?:\s*[,;])+\s*\)", ")", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)  # the space left where a URL was
    s = re.sub(r"[,;:]+([.!?])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def sentence(s):
    """A heading, list item or table row as a sentence: a capital letter first, and a full stop if it has no ending of
    its own. A first word written with a small letter on purpose (iPhone, macOS, a.py, snake_case) stays as it is."""
    if not s:
        return s
    word = re.match(r"\S*", s).group().rstrip(".,;:!?…»)\"'")
    if not (word[:1].islower() and (not word.isalpha() or any(c.isupper() for c in word[1:]))):
        s = s[0].upper() + s[1:]
    return s if END.search(s) else s + "."


def plain(text):
    """Markdown text → paragraphs of plain prose, one per line."""
    paragraphs, current, in_code = [], [], False

    def flush():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    lines = text.splitlines()
    for i, raw in enumerate(lines):
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
            if i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
                continue  # the header row
            row = line.strip()[1:]
            row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
            cells = [c for c in (inline(c.replace("\\|", "|")) for c in CELL.split(row)) if c]
            row = cells[0] + (": " + ", ".join(cells[1:]) if len(cells) > 1 else "") if cells else ""
            current.append(sentence(row))
            flush()
        elif ITEM.match(line):
            flush()
            current.append(sentence(inline(ITEM.sub("", line))))
        else:
            current.append(inline(line))
    flush()
    return "\n".join(p for p in paragraphs if p.strip(" ."))
