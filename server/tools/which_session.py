"""Which surfaces a recorded snapshot is on, and which conversation their adapters find: for a check by hand, without
audio.

Usage: server/.venv/bin/python server/tools/which_session.py [SNAPSHOT.json]   (default: read the snapshot from stdin)
       macos/.build/release/echofox-snapshot | server/.venv/bin/python server/tools/which_session.py
The snapshot is {"identity", "content": {"surfaces": {…}}}, as macos echofox-snapshot prints it: the surfaces it was
asked to read (--read), or one named "snapshot" when its flags said what to read. The script matches the identity with
the surfaces of every working adapter (enabled or not), gives each surface the parts it declares of what was read for
it (or for "snapshot"), and
prints what was found: the surface, what it is, where it was read, the adapter's details, the number of messages, the
open files with their length, the first terms and the errors. It never prints the texts themselves.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # the server's modules: a tool is in server/tools

import adapters  # noqa: E402
from adapters import registry, screen, surfaces  # noqa: E402


def report(snapshot):
    """The lines that describe what the adapters find in the snapshot."""
    identity, content = snapshot.get("identity") or {}, snapshot.get("content") or {}
    app = identity.get("app") if isinstance(identity.get("app"), dict) else {}
    read = content.get("surfaces") if isinstance(content.get("surfaces"), dict) else {}
    lines = [f"app: {screen.bundle(identity)} ({app.get('name')}), window: {screen.window_title(identity)!r}",
             f"web area: {screen.web_area(identity) or '-'}",
             "content: " + (", ".join(f"{n} ({', '.join(sorted(p)) if isinstance(p, dict) else '-'})"
                                      for n, p in read.items()) or "none")]
    matched = adapters.match(identity, list(registry.packages()))
    if not matched:
        return lines + ["surfaces: none: the dictation runs without context"]
    lines.append("surfaces: " + ", ".join(f"{s.name} (reads {', '.join(s.screen()) or 'the identity only'})"
                                          for s in matched))
    found = adapters.context(identity, matched, {s.name: surfaces.recorded(content, s.name) for s in matched})
    if not found:
        return lines + ["no surface gave a context"]
    if found.get("adapter"):
        lines.append(f"{found['surface']} found {found.get('about')!r}: {found.get('source')}")
        lines.append(f"  details: {found.get('details')}")
        lines.append(f"  {len(found.get('messages') or [])} messages, terms: {', '.join((found.get('terms') or [])[:12])}")
        for d in found.get("documents") or []:
            lines.append(f"  open file: {d['name']}, {len(d['text'])} characters")
    for e in found.get("errors") or []:
        lines.append(f"error: {e}")
    return lines


def main():
    snapshot = json.load(open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else sys.stdin)
    print("\n".join(report(snapshot if isinstance(snapshot, dict) else {})))


if __name__ == "__main__":
    main()
