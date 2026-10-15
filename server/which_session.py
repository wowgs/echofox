"""Which adapter claims a focus snapshot, and which conversation it finds: for a check by hand, without audio.

Usage: server/.venv/bin/python server/which_session.py [SNAPSHOT.json]   (default: read the snapshot from stdin)
       macos/.build/release/lv-snapshot | server/.venv/bin/python server/which_session.py
Prints the claim of every adapter plugin (enabled or not), the surest first, then what the surest one found: how, session, title, transcript,
the number of the assistant's replies and the first terms. It never prints the replies themselves.
"""
import json
import sys

import adapters


def main():
    snapshot = json.load(open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else sys.stdin)
    app = snapshot.get("app") or {}
    print(f"app: {app.get('bundleId')} ({app.get('name')}), window: {(snapshot.get('window') or {}).get('title')!r}")
    if snapshot.get("trusted") is False:
        print("the process that took the snapshot has no Accessibility permission: only the app is known")
    print(f"web area: {snapshot.get('webArea') or '-'}")
    print(f"focused: {(snapshot.get('focused') or {}).get('role')} {(snapshot.get('focused') or {}).get('description') or ''}"
          f", {len(snapshot.get('ancestors') or [])} ancestors, {len(snapshot.get('processes') or [])} processes,"
          f" snapshot took {snapshot.get('tookMs')} ms")
    ranked = adapters.claims(snapshot)
    print("claims:" if ranked else "claims: none: the dictation runs without context")
    for _, c in ranked:
        print(f"  {c.adapter}: {c.confidence} ({c.reason})")
    found = adapters.context(snapshot)
    if not found:
        return
    if "messages" not in found:
        print(f"{found['adapter']} found no conversation")
        return
    print(f"{found['adapter']} found, by {found['how']}: session {found['session']}, title {found.get('title')!r}")
    print(f"  transcript: {found['file']}")
    print(f"  {len(found['messages'])} replies, terms: {', '.join(found['terms'][:12])}")


if __name__ == "__main__":
    main()
