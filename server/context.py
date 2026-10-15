"""The chat context of a recording: Claude's final replies in the Claude Code session that the dictation goes into, so
the model knows the names and terms of the conversation. gemma_voice.py puts what fits its token budget before the
audio (options chatHistoryTokenBudget and chatTermsTokenBudget).

The session: a client that knows it names its session ids, and
the newest transcript ~/.claude/projects/<project>/<session id>.jsonl among them is read. A client that knows only
the app with the input box (the menu bar app) names the app's bundle id; then the newest transcript whose last line
came from that app (its "entrypoint") is read. That is a guess: the newest session of the app need not be the one on
the screen.

Kept: only Claude's final replies, the text of each turn's last answer (stop_reason "end_turn"). Dropped: the user's
own messages (the model copied the user's previous dictation into the next transcription instead of transcribing it,
2026-10-14), Claude's texts between tool calls (stop_reason "tool_use"), tool calls and their results, thinking,
attachments, meta messages (isMeta), subagents (isSidechain), and tags that Claude Code adds (<system-reminder>,
<ide_…>, <command-…>, <task-notification>).
"""
import glob
import json
import os
import re

PROJECTS = os.environ.get("LOCAL_VOICE_PROJECTS") or os.path.expanduser("~/.claude/projects")
# The app with the input box → the "entrypoint" Claude Code writes into the transcript lines of that app's sessions.
APP_ENTRYPOINTS = {"com.anthropic.claudefordesktop": "claude-desktop", "com.microsoft.VSCode": "claude-vscode",
                   "com.apple.Terminal": "cli", "com.googlecode.iterm2": "cli"}
# How many of the newest transcripts are looked at for an app's session, and how much of each one's end.
NEWEST_FILES = 50
TAIL_BYTES = 65536

_TAG_NAMES = r"system-reminder|ide_[\w-]+|command-[\w-]+|local-command-[\w-]+|task-notification"
TAGS = re.compile(rf"<({_TAG_NAMES}|user-prompt-submit-hook)\b[^>]*>[\s\S]*?</\1>")
LONE_TAG = re.compile(rf"</?({_TAG_NAMES})\b[^>]*>")
ENTRYPOINT = re.compile(r'"entrypoint":\s*"([^"]*)"')
MAX_TERMS = 500
# Latin-script words: product names, identifiers, file names. A word joined by . _ + # - / stays one term.
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._+#/-][A-Za-z0-9]+)*\+*")
STOP = set(("a an and are as at be but by can do for from has have he i if in is it its me my no not of on "
            "or our so that the their them then there they this to too up us was we what when which who will with would "
            "you your ok okay yes just like also all any one two how why get got go see let use").split())


def session_file(session_ids, projects=None):
    """The transcript of the newest of these sessions: {"file", "session"}, or None."""
    best = None
    for sid in set(session_ids or []):
        if not isinstance(sid, str) or not re.fullmatch(r"[\w-]+", sid):
            continue
        for f in glob.glob(os.path.join(glob.escape(projects or PROJECTS), "*", f"{sid}.jsonl")):
            try:
                mtime = os.stat(f).st_mtime
            except OSError:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, f, sid)
    return {"file": best[1], "session": best[2]} if best else None


def app_session(entrypoint, projects=None):
    """The newest transcript whose last line came from `entrypoint`: {"file", "session"}, or None."""
    files = []
    for f in glob.glob(os.path.join(glob.escape(projects or PROJECTS), "*", "*.jsonl")):
        try:
            files.append((os.stat(f).st_mtime, f))
        except OSError:
            pass
    for _, f in sorted(files, reverse=True)[:NEWEST_FILES]:
        try:
            with open(f, "rb") as fh:
                fh.seek(max(0, os.path.getsize(f) - TAIL_BYTES))
                found = ENTRYPOINT.findall(fh.read().decode("utf-8", "replace"))
        except OSError:
            continue
        if found and found[-1] == entrypoint:
            return {"file": f, "session": os.path.basename(f)[:-len(".jsonl")]}
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


def terms(texts):
    """Latin-script terms of the texts, the most frequent first (ties: the later one first)."""
    seen, i = {}, 0
    for t in texts:
        for w in WORD.findall(t):
            i += 1
            w = re.sub(r"[.\-/]+$", "", w)
            if len(w) < 2 or len(w) > 40 or w.count("/") > 1 or w.lower() in STOP:
                continue
            n, _ = seen.get(w, (0, 0))
            seen[w] = (n + 1, i)
    return [w for w, _ in sorted(seen.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))][:MAX_TERMS]


def chat_context(session_ids=None, app=None, projects=None):
    """{"session", "file", "messages": [{"role", "text"}] newest first, "terms"} of the session that the dictation
    goes into (see the module's text), or None without a transcript. The terms come from the whole session."""
    found = session_file(session_ids, projects) if session_ids else None
    if found is None and app in APP_ENTRYPOINTS:
        found = app_session(APP_ENTRYPOINTS[app], projects)
    if found is None:
        return None
    replies = []
    with open(found["file"], encoding="utf-8", errors="replace") as f:
        for line in f:
            m = message(line)
            if m is None:
                continue
            if replies and m["id"] and replies[-1]["id"] == m["id"]:  # one reply in several lines
                replies[-1]["text"] += "\n\n" + m["text"]
            else:
                replies.append(m)
    messages = [{"role": m["role"], "text": m["text"]} for m in reversed(replies)]
    return {**found, "messages": messages, "terms": terms(m["text"] for m in replies)}
