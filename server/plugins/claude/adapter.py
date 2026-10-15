"""The Claude plugin: the conversation a dictation goes into, in Anthropic's Claude apps.

- Claude Desktop's Code tab, the session in focus (confidence 1.0). Ways to the session: the web area's URL → Desktop's
  record of the session → its Claude Code transcript ("desktop store"); without a record, the web area's title → the
  one transcript with that title ("title"); several transcripts with that title: no context.
- Claude Code sessions that the client names in the start message (confidence 0.9): the newest of them.
It never guesses a session from the app alone: without the Code tab's URL in the snapshot (no Accessibility
permission, the Chat tab, another window) it does not claim Desktop, and the newest session of an app is often another
one that runs in the background. The Chat tab (claude.ai conversations) has no local transcript; it is not read yet.
Claude writes its replies in Markdown; clean makes them plain prose.
"""
from adapters import Adapter, Claim, bundle, markdown

from . import desktop, transcripts


class Claude(Adapter):
    def claim(self, snapshot, sessions):
        m = desktop.code_tab(snapshot)
        if m:
            return Claim(self.name, 1.0, f"the Code tab of Claude Desktop session {m}")
        if sessions:
            return Claim(self.name, 0.9, "the client named its Claude Code sessions")
        return None

    def context(self, snapshot, sessions):
        local = desktop.code_tab(snapshot)
        if not local:
            return transcripts.context_of(transcripts.session_file(sessions), "named sessions")
        cli = (desktop.record(local) or {}).get("cliSessionId")
        where = transcripts.session_file([cli]) if cli else None
        if where:
            return {**transcripts.context_of(where, "desktop store"), "details": {"desktopSession": local}}
        title = str(desktop.web_area(snapshot).get("title") or "")
        if title.endswith(desktop.TITLE_SUFFIX):
            return transcripts.context_of(transcripts.titled_session(title[:-len(desktop.TITLE_SUFFIX)]), "title")
        return None

    def clean(self, text):
        return markdown.plain(text)
