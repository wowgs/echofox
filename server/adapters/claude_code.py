"""The adapter for Claude Code sessions, and the reading of Claude Code transcripts that other adapters use too.

A Claude Code client (Claude Desktop's Code tab, the VS Code extension, the CLI) writes each session to
~/.claude/projects/<project>/<session id>.jsonl; each line's "entrypoint" says which client wrote it. This adapter
claims a snapshot when the client named its sessions (the newest of them is read), and, less surely, when the app is
one that may host Claude Code (VS Code, a terminal); then the newest session that app wrote is read. That is a guess:
the newest session of an app need not be the one on the screen.

Kept from a transcript: only Claude's final replies, the text of each turn's last answer (stop_reason "end_turn").
Dropped: the user's own messages (the model copied the user's previous dictation into the next transcription instead
of transcribing it, 2026-10-14), Claude's texts between tool calls (stop_reason "tool_use"), tool calls and their
results, thinking, attachments, meta messages (isMeta), subagents (isSidechain), and tags that Claude Code adds
(<system-reminder>, <ide_…>, <command-…>, <task-notification>).
"""
import glob
import json
import os
import re

from . import Claim, bundle, terms

PROJECTS = os.environ.get("LOCAL_VOICE_PROJECTS") or os.path.expanduser("~/.claude/projects")
# Apps that may host a Claude Code client → the "entrypoint" of its transcript lines.
HOSTS = {"com.microsoft.VSCode": "claude-vscode", "com.apple.Terminal": "cli", "com.googlecode.iterm2": "cli",
         "com.mitchellh.ghostty": "cli"}
# How many of the newest transcripts are looked at for an app's or a title's session, and how much of each one's end.
NEWEST_FILES = 50
TAIL_BYTES = 65536

_TAG_NAMES = r"system-reminder|ide_[\w-]+|command-[\w-]+|local-command-[\w-]+|task-notification"
TAGS = re.compile(rf"<({_TAG_NAMES}|user-prompt-submit-hook)\b[^>]*>[\s\S]*?</\1>")
LONE_TAG = re.compile(rf"</?({_TAG_NAMES})\b[^>]*>")
ENTRYPOINT = re.compile(r'"entrypoint":\s*"([^"]*)"')


def projects():
    return PROJECTS


def session_file(session_ids, root=None):
    """The transcript of the newest of these sessions: {"file", "session"}, or None."""
    best = None
    for sid in set(session_ids or []):
        if not isinstance(sid, str) or not re.fullmatch(r"[\w-]+", sid):
            continue
        for f in glob.glob(os.path.join(glob.escape(root or projects()), "*", f"{sid}.jsonl")):
            try:
                mtime = os.stat(f).st_mtime
            except OSError:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, f, sid)
    return {"file": best[1], "session": best[2]} if best else None


def newest(root=None):
    """The newest transcripts, newest first: [path]."""
    files = []
    for f in glob.glob(os.path.join(glob.escape(root or projects()), "*", "*.jsonl")):
        try:
            files.append((os.stat(f).st_mtime, f))
        except OSError:
            pass
    return [f for _, f in sorted(files, reverse=True)[:NEWEST_FILES]]


def found(f):
    return {"file": f, "session": os.path.basename(f)[:-len(".jsonl")]}


def entrypoint_session(entrypoint, root=None):
    """The newest transcript whose last line came from `entrypoint`: {"file", "session"}, or None."""
    for f in newest(root):
        try:
            with open(f, "rb") as fh:
                fh.seek(max(0, os.path.getsize(f) - TAIL_BYTES))
                seen = ENTRYPOINT.findall(fh.read().decode("utf-8", "replace"))
        except OSError:
            continue
        if seen and seen[-1] == entrypoint:
            return found(f)
    return None


def titled_session(title, root=None):
    """The newest transcript whose title (a "custom-title" line) is `title`: {"file", "session"}, or None."""
    for f in newest(root):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"custom-title"' in line:
                        e = json.loads(line)
                        if e.get("customTitle") == title:
                            return found(f)
                        break
        except (OSError, ValueError):
            continue
    return None


def clean(text):
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
    text = clean("\n\n".join(b["text"] for b in m["content"]
                             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)))
    return {"role": "assistant", "text": text, "id": m.get("id")} if text else None


def read(f):
    """A transcript's context: {"title", "messages": [{"role", "text"}] newest first, "terms"} (the terms come from
    the whole session)."""
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
    return {"title": title, "messages": [{"role": m["role"], "text": m["text"]} for m in reversed(replies)],
            "terms": terms(m["text"] for m in replies)}


def context_of(where, how):
    """found (or None) → the adapter's context: {"session", "file", "how", "title", "messages", "terms"}."""
    if not where:
        return None
    return {**where, "how": how, **read(where["file"])}


class ClaudeCode:
    name = "claude-code"

    def claim(self, snapshot, sessions):
        if sessions:
            return Claim(self.name, 0.9, "the client named its Claude Code sessions")
        if bundle(snapshot) in HOSTS:
            return Claim(self.name, 0.3, f"{bundle(snapshot)} may host Claude Code")
        return None

    def context(self, snapshot, sessions):
        if sessions:
            return context_of(session_file(sessions), "named sessions")
        return context_of(entrypoint_session(HOSTS[bundle(snapshot)]), "newest session of the app")
