"""The adapter for Claude Code sessions that the client names (a client that knows its sessions sends their ids in
the start message). It reads the newest of them. It never guesses a session from the app alone: the newest session of
an app is often another one that runs in the background. Claude writes its replies in Markdown; clean makes them plain
prose."""
from adapters import Adapter, Claim, claude_transcripts as transcripts, markdown


class ClaudeCode(Adapter):
    def claim(self, snapshot, sessions):
        return Claim(self.name, 0.9, "the client named its Claude Code sessions") if sessions else None

    def context(self, snapshot, sessions):
        return transcripts.context_of(transcripts.session_file(sessions), "named sessions")

    def clean(self, text):
        return markdown.plain(text)
