"""Reading Claude Code transcripts, for the claude-code adapter: Claude Code clients (Claude Desktop's Code tab, the
VS Code extension, the CLI) write each session to ~/.claude/projects/<project>/<session id>.jsonl.

Kept from a transcript: only Claude's final replies, the text of each turn's last answer (stop_reason "end_turn").
Dropped: the user's own messages (the model copied the user's previous dictation into the next transcription instead
of transcribing it, 2026-10-14), Claude's texts between tool calls (stop_reason "tool_use"), tool calls and their
results, thinking, attachments, meta messages (isMeta) and subagents (isSidechain). The replies are read as they are
written; the adapter's clean takes out the tags that Claude Code adds (strip_tags: <system-reminder>, <ide_…>,
<command-…>, <task-notification>).
"""
import glob
import json
import os
import re

from adapters import place

_TAG_NAMES = r"system-reminder|ide_[\w-]+|command-[\w-]+|local-command-[\w-]+|task-notification"
TAGS = re.compile(rf"<({_TAG_NAMES}|user-prompt-submit-hook)\b[^>]*>[\s\S]*?</\1>")
LONE_TAG = re.compile(rf"</?({_TAG_NAMES})\b[^>]*>")


def projects():
    return place("~/.claude/projects", "ECHOFOX_PROJECTS")


def session_file(session_id, root=None):
    """The transcript of this session: {"file", "session"}, the newest file if it is in several projects, or None."""
    if not isinstance(session_id, str) or not re.fullmatch(r"[\w-]+", session_id):
        return None
    best = None
    for f in glob.glob(os.path.join(glob.escape(root or projects()), "*", f"{session_id}.jsonl")):
        try:
            mtime = os.stat(f).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, f)
    return found(best[1]) if best else None


def found(f):
    return {"file": f, "session": os.path.basename(f)[:-len(".jsonl")]}


_titles = {}  # transcript → (its size and change time, its title or None): a title is read once per change


def title_of(f):
    """A transcript's title, from its "custom-title" line, or None. Cached until the file changes."""
    try:
        st = os.stat(f)
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    if f in _titles and _titles[f][0] == key:
        return _titles[f][1]
    title = None
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"custom-title"' in line:
                    title = json.loads(line).get("customTitle")
    except (OSError, ValueError):
        pass
    _titles[f] = (key, title)
    return title


def titled_session(title, root=None):
    """The one transcript whose title (its last "custom-title" line) is `title`: {"file", "session"}; None if there
    is no such transcript or more than one."""
    hits = [f for f in glob.glob(os.path.join(glob.escape(root or projects()), "*", "*.jsonl")) if title_of(f) == title]
    return found(hits[0]) if len(hits) == 1 else None


def strip_tags(text):
    """The text without the tags that Claude Code adds, and without what is inside a pair of them."""
    return LONE_TAG.sub("", TAGS.sub("", text)).strip()


def message(line):
    """One transcript line → {"role": "assistant", "text", "id"} for the text of a final reply, or None."""
    if '"assistant"' not in line or '"end_turn"' not in line:  # a quick look before parsing
        return None
    try:
        e = json.loads(line)
    except ValueError:
        return None
    m = e.get("message") if isinstance(e, dict) else None
    if e.get("type") != "assistant" or e.get("isMeta") or e.get("isSidechain") or not isinstance(m, dict) \
            or m.get("stop_reason") != "end_turn" or not isinstance(m.get("content"), list):
        return None
    text = "\n\n".join(b["text"] for b in m["content"]
                       if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return {"role": "assistant", "text": text, "id": m.get("id")} if text.strip() else None


def read(f):
    """A transcript's context: {"title", "messages": [{"role", "text"}] newest first}, the whole session."""
    replies, title = [], None
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if title is None and '"custom-title"' in line:
                try:
                    title = json.loads(line).get("customTitle")
                except ValueError:
                    pass
            m = message(line)
            if m is None:
                continue
            if replies and m["id"] and replies[-1]["id"] == m["id"]:  # one reply in several lines
                replies[-1]["text"] += "\n\n" + m["text"]
            else:
                replies.append(m)
    return {"title": title, "messages": [{"role": m["role"], "text": m["text"]} for m in reversed(replies)]}


def context_of(where, how):
    """found (or None) → the adapter's context: {"session", "file", "how", "title", "messages"}."""
    if not where:
        return None
    return {**where, "how": how, **read(where["file"])}
