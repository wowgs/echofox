"""Markdown → plain text, for plugins of chat apps whose assistants write their replies in Markdown.

The model that transcribes reads the chat context before the audio. With Markdown in it (lists, **bold**, `code`,
tables), the model wrote the transcription without punctuation and capital letters: one recording, five runs each,
text with punctuation in 1 of 5 runs with this session's Markdown replies, 5 of 5 without context, 5 of 5 with a
session whose replies had little Markdown (2026-10-15, Claude Code transcripts, Gemma 4 E4B Q8_0 in llama.cpp). So the
context gets plain prose: the words stay, the marks go, and each heading, list item and table row becomes a sentence.

markdown-it-py parses the text (CommonMark with GitHub's tables, strikethrough and bare links), so what is code, a
link or a mark is the parser's answer, escapes included. Code blocks and HTML go (code is not speech). Inline code
keeps its text when it is a term: an identifier, a file, a flag, a short command (the terms the speaker says). It goes
when it is code: a URL, more than CODE_WORDS words, any of CODE_CHARS (JSON, calls, assignments, shell pipes), or
no letter or digit at all (`**`). Links keep their text, bare URLs (with their scheme) and e-mail addresses go, images keep their alt text. A table's header
row goes; each other row becomes "first cell: the other cells." Each sentence made from a heading, list item or table
row starts with a capital letter, as prose does, unless its first word is written with a small one on purpose
(iPhone, macOS, a.py, snake_case).
"""
import re

from markdown_it import MarkdownIt

MD = MarkdownIt("gfm-like")
MD.linkify.set({"fuzzy_link": False})  # a link needs its scheme: a.py, github.com are words a speaker says
CODE_CHARS = set("{}[]();=<>\"'|\\$`")
CODE_WORDS = 3
BARE_LINKS = {"linkify", "autolink"}  # the markup of a link the text did not name
END = re.compile(r"[.!?…:;,]$")


def code_text(content):
    """An inline code span's text: kept if it is a term, "" if it is code."""
    t = content.strip()
    if ("://" in t or MD.linkify.test(t) or CODE_CHARS & set(t) or len(t.split()) > CODE_WORDS
            or not any(c.isalnum() for c in t)):
        return ""
    return t


def tidy(s):
    """The prose around what went: no brackets left empty, no space before a stop."""
    s = re.sub(r"\(\s*(?:[,;]\s*)*\)", "", s)
    s = re.sub(r"\(\s*[,;]\s*", "(", s)
    s = re.sub(r"(?:\s*[,;])+\s*\)", ")", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    s = re.sub(r"[,;:]+([.!?])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def text_of(inline):
    """The words of an inline token."""
    out, in_bare_link = [], False
    for c in inline.children or []:
        if c.type == "link_open":
            in_bare_link = c.markup in BARE_LINKS
        elif c.type == "link_close":
            in_bare_link = False
        elif in_bare_link:
            continue
        elif c.type == "text":
            out.append(c.content)
        elif c.type == "code_inline":
            out.append(code_text(c.content))
        elif c.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif c.type == "image":
            out.append(c.content)  # its alt text
    return tidy("".join(out))


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
    paragraphs, row, header, items, parent = [], None, False, 0, None
    for t in MD.parse(text):
        if t.type == "list_item_open":
            items += 1
        elif t.type == "list_item_close":
            items -= 1
        elif t.type == "thead_open":
            header = True
        elif t.type == "thead_close":
            header = False
        elif t.type == "tr_open":
            row = []
        elif t.type == "tr_close":
            cells = [c for c in row if c]
            if cells and not header:
                paragraphs.append(sentence(cells[0] + (": " + ", ".join(cells[1:]) if len(cells) > 1 else "")))
            row = None
        elif t.type == "inline":
            s = text_of(t)
            if row is not None:
                row.append(s)
            elif parent == "heading_open" or items:
                paragraphs.append(sentence(s))
            else:
                paragraphs.append(s)
        if t.type != "inline":
            parent = t.type
    return "\n".join(p for p in paragraphs if p.strip(" ."))
