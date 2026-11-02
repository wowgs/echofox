"""Fixtures from live windows: real snapshots of the adapters' surfaces, taken of the apps on this Mac, kept on this Mac
only, and checked again when an app updates (docs/reference/8-fixtures.md has the test conversations and the steps).

Usage: server/.venv/bin/python server/tools/fixtures.py record [SURFACE ...]
       server/.venv/bin/python server/tools/fixtures.py accept SURFACE ...
       server/.venv/bin/python server/tools/fixtures.py check [SURFACE ...]
       server/.venv/bin/python server/tools/fixtures.py sandbox
SURFACE is <adapter>/<id>, for example claude-chat/desktop.

record: for each running app of the surfaces (none named: every surface of every working adapter) and each of its
  windows, macos echofox-snapshot reads the identity. The server's matching (adapters.surfaces) tells the surfaces the
  window is on, and the tool builds the read request as the server does, with the budgets of the default config
  (resolve.budget), so that the owner's own settings do not change a fixture. echofox-snapshot reads the content. Only
  a window that carries the MARKER in its window's or page's title or in the content's text goes on: a window without
  it is never written, so a real conversation never becomes a fixture. Then the core runs the surface's adapter
  (adapters.context, with clean) and the tool writes fixtures/<adapter>/<id>/pending.json and prints it for review.
  The files the adapter read that carry the marker go into the fixture too, so that a replay needs no live disk.
  record writes nothing for a surface whose replay from those files gives another parse.
accept: the pending file of each surface becomes its fixture of that app version:
  fixtures/<adapter>/<id>/<version>.json.
check: the same snapshot and parse as record, compared with the fixture of the newest version of each surface (none
  named: every surface that has a fixture). It prints the app's version now and in the fixture, same or different,
  and the differences, and it writes nothing.
sandbox: makes fixtures/sandbox/ with a Markdown file to open in Claude Desktop's Files panel.

The fixtures are in $ECHOFOX_FIXTURES, else in fixtures/ at the repository's root, which git leaves out. A fixture
holds the conversation's text as the app shows it: it never leaves this Mac. echofox-snapshot is $ECHOFOX_SNAPSHOT,
else the release or debug build in macos/.build. It needs the Accessibility permission of the app that runs this tool
(the terminal). The tool runs without questions: exit code 0 when all went well, 1 when a surface was not recorded or
check found a difference, 2 when check found no difference but could not check a surface.
"""
import contextlib
import dataclasses
import datetime
import difflib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # the server's modules: a tool is in server/tools

import adapters  # noqa: E402
import catalog  # noqa: E402
import resolve  # noqa: E402
import settings  # noqa: E402
from adapters import registry, screen, surfaces  # noqa: E402

MARKER = "EchoFox fixture"  # in a test conversation's title or text; a window without it is never recorded
REPO = pathlib.Path(__file__).resolve().parents[2]
PENDING = "pending.json"
SANDBOX = "sandbox"
# The variables of EchoFox that a replay keeps: the others move the places that adapters read (adapters.place), and a
# replay reads only the fixture's files
KEPT_VARIABLES = {"ECHOFOX_ADAPTERS", "ECHOFOX_FIXTURES", "ECHOFOX_SNAPSHOT", "ECHOFOX_CONFIG"}
ACCESSIBILITY = ("echofox-snapshot has no Accessibility permission, so it cannot read the windows. Give it to the app "
                 "that runs this tool (the terminal) in System Settings, Privacy & Security, Accessibility, and run "
                 "the tool again.")
DIFF_LINES = 80  # the most lines of a difference that check prints for one surface


class Problem(Exception):
    """What stops the tool, in words for the person who runs it."""


def folder():
    """The fixtures: $ECHOFOX_FIXTURES, else fixtures/ at the repository's root."""
    return pathlib.Path(os.environ.get("ECHOFOX_FIXTURES") or REPO / "fixtures")


# echofox-snapshot

def snapshot_tool():
    """The path of macos echofox-snapshot: $ECHOFOX_SNAPSHOT, else the release build, else the debug build."""
    if os.environ.get("ECHOFOX_SNAPSHOT"):
        return os.environ["ECHOFOX_SNAPSHOT"]
    for build in ("release", "debug"):
        path = REPO / "macos" / ".build" / build / "echofox-snapshot"
        if path.is_file():
            return str(path)
    raise Problem("echofox-snapshot is not built: run swift build -c release --package-path macos --product "
                  "echofox-snapshot")


class Snapshots:
    """The windows of the running apps, read by echofox-snapshot (its --list and --window)."""

    def windows(self, bundle, electron):
        """The identities of the app's windows, in the app's order; None when the app does not run."""
        got = self._run(["--app", bundle, "--list"] + (["--electron"] if electron else []))
        return None if got is None else got.get("windows") or []

    def read(self, bundle, index, request, electron):
        """{"identity", "content"} of the window at `index` of windows(), with the read message `request`."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as f:
            json.dump(request, f)
            f.flush()
            got = self._run(["--app", bundle, "--window", str(index), "--read", f.name]
                            + (["--electron"] if electron else []))
        if got is None:
            raise Problem(f"{bundle} quit while its windows were read")
        return got

    def _run(self, args):
        p = subprocess.run([snapshot_tool(), *args], capture_output=True, text=True)
        if p.returncode == 3:
            raise Problem(ACCESSIBILITY)
        if p.returncode == 4:
            return None
        if p.returncode != 0:
            raise Problem(f"echofox-snapshot {' '.join(args)}: exit code {p.returncode}: {p.stderr.strip()}")
        return json.loads(p.stdout)


# The surfaces and the read request, as the server makes them

def working_surfaces():
    """Every surface of every working adapter, enabled or not, in the order of the packages."""
    return [surfaces.Surface(p.name, s["id"], s, p.adapter) for p in registry.packages().values()
            if p.adapter is not None for s in p.surfaces]


def selected(names):
    """The working surfaces named <adapter>/<id> (none: all of them); raises Problem for a name that is none."""
    every = working_surfaces()
    if not names:
        return every
    by_name = {s.name: s for s in every}
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise Problem(f"no working surface {', '.join(unknown)}; the surfaces are {', '.join(by_name)}")
    return [by_name[n] for n in dict.fromkeys(names)]


def read_message(matched):
    """The read message for the matched surfaces, as the server sends it (session.Session.read_request), with the
    budgets and the token weights of the default config's model."""
    now = settings.in_force({})
    server, entry = settings.recording_settings(now), next(iter(now["models"].values()))
    options = resolve.model(entry)
    return {"type": "read", "surfaces": adapters.read(matched, lambda a, key: resolve.budget(a, key, options, server)),
            "tokenWeights": catalog.token_weights(entry)}


def texts(value):
    """Every text inside a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from texts(v)
    elif isinstance(value, list):
        for v in value:
            yield from texts(v)


def marked(identity, content):
    """Whether a window carries the MARKER: in its window's or page's title, or in the text of what was read there."""
    marker = MARKER.casefold()
    return any(marker in t.casefold() for t in
               [screen.window_title(identity), screen.web_title(identity), *texts(content)])


@dataclasses.dataclass
class Window:
    """A window on a surface that carries the marker: what the app sends for that surface."""
    surface: surfaces.Surface
    identity: dict
    request: dict  # the read message of this surface alone
    content: dict  # what was read for this surface


def scan(chosen, snapshots, say=print):
    """The windows of the running apps of the `chosen` surfaces that are on them and carry the marker: {surface name:
    [Window]}. The read request of a window is the server's for every chosen surface it is on."""
    names = list(registry.packages())
    wanted = {s.name for s in chosen}
    found = {s.name: [] for s in chosen}
    trees = {app for s in working_surfaces() if s.spec.get("treeOnRequest") for app in s.spec["apps"]}
    for bundle in dict.fromkeys(app for s in chosen for app in s.spec["apps"]):
        listed = snapshots.windows(bundle, bundle in trees)
        if listed is None:
            continue
        for i, identity in enumerate(listed):
            matched = [s for s in adapters.match(identity, names) if s.name in wanted]
            if not matched:
                continue
            request = read_message(matched)
            got = snapshots.read(bundle, i, request, bundle in trees)
            now = got.get("identity") or {}
            if [s.name for s in adapters.match(now, names) if s.name in wanted] != [s.name for s in matched]:
                raise Problem(f"window {i} of {bundle} changed between the list and the read: run the tool again")
            for s in matched:
                content = surfaces.recorded(got.get("content"), s.name)
                if not marked(now, content):
                    say(f"{s.name}: window {i} of {bundle} has no {MARKER!r}: not read further")
                    continue
                request_of_s = {**request, "surfaces": [r for r in request["surfaces"] if r["surface"] == s.name]}
                found[s.name].append(Window(s, now, request_of_s, content))
    return found


# The adapter's parse, and the files it read

_reading = None  # (thread, the paths opened) while an adapter runs under reads()
_hooked = False


def _audit(event, args):
    if event != "open" or _reading is None or _reading[0] != threading.get_ident():
        return
    path, mode, flags = (list(args) + [None, None, None])[:3]
    if isinstance(mode, str):
        writes = any(c in mode for c in "wax+")
    else:
        writes = isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR))
    if isinstance(path, (str, bytes, os.PathLike)) and not writes:
        _reading[1].add(os.path.abspath(os.fsdecode(path)))


@contextlib.contextmanager
def reads():
    """The set of the files that this thread opens for reading inside the block, through Python's audit hook "open":
    the core knows no adapter's places, so it watches what the adapter opens."""
    global _reading, _hooked
    if not _hooked:
        sys.addaudithook(_audit)  # a hook stays for the life of the process: it does nothing outside this block
        _hooked = True
    _reading = (threading.get_ident(), set())
    try:
        yield _reading[1]
    finally:
        _reading = None


def home():
    return os.path.expanduser("~")


def tilde(path, home_dir):
    """A path under the home folder written from ~/."""
    return "~" + path[len(home_dir):] if path.startswith(home_dir.rstrip("/") + "/") else path


def normalized(value, home_dir, pids=()):
    """A parse as a fixture keeps it: the home folder written ~ (in every text, followed by /, and a text that is the
    home folder), and the process ids of the snapshot written <pid>: they change with every run of a program."""
    roots = sorted({home_dir.rstrip("/"), os.path.realpath(home_dir).rstrip("/")}, key=len, reverse=True)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return "<pid>" if value in pids else value
    if isinstance(value, str):
        if value in roots:
            return "~"
        for r in roots:
            value = value.replace(r + "/", "~/")
        return value
    if isinstance(value, dict):
        return {k: normalized(v, home_dir, pids) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v, home_dir, pids) for v in value]
    return value


def pids_of(identity, content):
    """The process ids of a snapshot: the app's and its child processes'."""
    app = identity.get("app") if isinstance(identity.get("app"), dict) else {}
    return {p for p in [app.get("pid"), *screen.pids(content)] if isinstance(p, int) and not isinstance(p, bool)}


def parse(surface, identity, content):
    """The core's context of the window on `surface` (adapters.context, with the adapter's clean), and the files the
    adapter opened for reading."""
    with reads() as opened:
        found = adapters.context(identity, [surface], {surface.name: content})
    return found, set(opened)


def sources(paths, home_dir):
    """The files of `paths` that carry the marker, as a fixture keeps them: [{"path": from ~/ under the home folder,
    "mtime": in ns, "text": with the home folder written ~}]; and the other paths, which are not kept."""
    kept, others = [], []
    for p in sorted(paths):
        if p.endswith((".py", ".pyc", ".so")):
            continue  # a module that Python imported while the adapter ran
        try:
            text, mtime = pathlib.Path(p).read_text(encoding="utf-8"), os.stat(p).st_mtime_ns
        except (OSError, UnicodeDecodeError):
            others.append(p)
            continue
        if os.path.isfile(p) and MARKER.casefold() in text.casefold():
            kept.append({"path": tilde(p, home_dir), "mtime": mtime, "text": normalized(text, home_dir)})
        else:
            others.append(p)
    return kept, others


@contextlib.contextmanager
def home_at(path):
    """The home folder at `path` inside the block, without the variables that move an adapter's places; the user's
    adapters stay where they are."""
    user = registry.user_dir()
    saved = dict(os.environ)
    for k in [k for k in os.environ if k.startswith("ECHOFOX_") and k not in KEPT_VARIABLES]:
        del os.environ[k]
    os.environ.update(HOME=path, ECHOFOX_ADAPTERS=user)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def surface_of(name):
    return next((s for s in working_surfaces() if s.name == name), None)


def replay(fixture):
    """The parse of a fixture's snapshot by the adapter as it is now, with the fixture's files under a new home folder
    in place of the live disk: normalized as the fixture's "expected". A file outside the home folder is not moved,
    so the adapter reads it on the disk. Raises Problem when no working adapter has the surface."""
    surface = surface_of(fixture["surface"])
    if surface is None:
        raise Problem(f"no working adapter has the surface {fixture['surface']}")
    with tempfile.TemporaryDirectory(prefix="echofox-fixture-") as tmp:
        root = os.path.realpath(tmp)
        for s in fixture.get("sources") or []:
            if not s["path"].startswith("~/"):
                continue
            path = os.path.join(root, s["path"][2:])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(s["text"].replace("~/", root + "/"))
            os.utime(path, ns=(s["mtime"], s["mtime"]))
        with home_at(root):
            found, _ = parse(surface, fixture["identity"], fixture["content"])
        return normalized(found, root, pids_of(fixture["identity"], fixture["content"]))


def make(window, home_dir=None):
    """The fixture of a window: {"surface", "app": {bundleId, version}, "macos", "date", "marker", "identity", "read",
    "content", "sources", "expected"}, and the paths that the adapter read without the marker. Raises Problem when the
    adapter gave no context or an error."""
    home_dir = home_dir or home()
    found, opened = parse(window.surface, window.identity, window.content)
    if not found or not found.get("adapter"):
        errors = "; ".join((found or {}).get("errors") or []) or "it did not find the conversation"
        raise Problem(f"{window.surface.name}: no context: {errors}")
    if found.get("errors"):
        raise Problem(f"{window.surface.name}: the adapter failed: {'; '.join(found['errors'])}")
    kept, others = sources(opened, home_dir)
    app = window.identity.get("app") or {}
    return {"surface": window.surface.name, "app": {"bundleId": app.get("bundleId"), "version": app.get("version")},
            "macos": platform.mac_ver()[0], "date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "marker": MARKER, "identity": window.identity, "read": window.request, "content": window.content,
            "sources": kept, "expected": normalized(found, home_dir, pids_of(window.identity, window.content))}, others


# The fixtures on the disk

def place(name, root=None):
    adapter, sid = name.split("/", 1)
    return (root or folder()) / adapter / sid


def file_name(version):
    """A fixture's file for an app version."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", version or "unknown") + ".json"


def version_key(version):
    """The order of versions: by their numbers, "4.10.0" after "4.9.1"."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.findall(r"\d+|[^\d.]+", version or "")]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, fixture):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def accepted(root=None):
    """Every accepted fixture: [(surface name, app version, path)], by surface, the oldest version first. The sandbox,
    the pending files and folders that are no adapter's are left out."""
    root = root or folder()
    out = []
    if not root.is_dir():
        return out
    for a in sorted(root.iterdir()):
        if a.name == SANDBOX or not a.is_dir() or not registry.NAME.fullmatch(a.name) or a.name.startswith("."):
            continue
        for s in sorted(a.iterdir()):
            if not s.is_dir() or not registry.SURFACE_ID.fullmatch(s.name):
                continue
            for f in s.glob("*.json"):
                if f.name != PENDING:
                    with contextlib.suppress(OSError, ValueError):
                        out.append((f"{a.name}/{s.name}", str(load(f)["app"].get("version") or ""), f))
    return sorted(out, key=lambda x: (x[0], version_key(x[1])))


def newest(name, root=None):
    """The fixture of the newest app version of a surface: (version, path), or None."""
    mine = [(v, p) for n, v, p in accepted(root) if n == name]
    return mine[-1] if mine else None


# What the tool prints

def indented(text, prefix="      "):
    return "\n".join(prefix + line for line in str(text).splitlines() or [""])


def review(fixture, others=()):
    """A fixture for a person to read before accepting it."""
    i, e, app = fixture["identity"], fixture["expected"], fixture["app"]
    name = (i.get("app") or {}).get("name")
    lines = [f"{fixture['surface']}: " + (f"{name} {app['version']} ({app['bundleId']})" if name else
                                          f"{app['bundleId']} {app['version']}") + f", macOS {fixture['macos']}",
             f"  window {screen.window_title(i)!r}" + (f", page {screen.web_title(i)!r} ({screen.web_url(i)})"
                                                      if screen.web_area(i) else "")]
    for r in fixture["read"]["surfaces"]:
        lines.append("  read: " + (", ".join(f"{part} {how}" for part, how in r.items() if part != "surface")
                                   or "the identity only"))
    c = fixture["content"]
    if "outline" in c:
        o = c["outline"]
        lines.append(f"  outline: {len(o.get('nodes') or [])} elements, {'complete' if o.get('complete') else 'cut'}")
    for n, l in enumerate(c.get("lists") or []):
        lines.append(f"  list {n}: {len(l.get('rows') or [])} of {l.get('rowCount')} rows")
    if "processes" in c:
        lines.append(f"  processes: {', '.join(str(p.get('name')) for p in c['processes'])}")
    lines += [f"  about: {e.get('about')}", f"  source: {e.get('source')}",
              f"  details: {json.dumps(e.get('details'), ensure_ascii=False)}",
              f"  terms ({len(e.get('terms') or [])}): {', '.join(e.get('terms') or [])}",
              f"  messages ({len(e.get('messages') or [])}, the newest first):"]
    for n, m in enumerate(e.get("messages") or [], 1):
        lines += [f"    {n}. {m['from']}:", indented(m["text"])]
    lines.append(f"  documents ({len(e.get('documents') or [])}):")
    for d in e.get("documents") or []:
        lines += [f"    {d['name']}, {len(d['text'])} characters:", indented(d["text"])]
    lines.append("  files kept: " + (", ".join(s["path"] for s in fixture["sources"]) or "none"))
    if others:
        lines.append(f"  files read without {MARKER!r}, not kept: {', '.join(others)}")
    return "\n".join(lines)


def difference(old, new, old_name, new_name):
    """The lines that differ between two parses, as a unified diff of their JSON, at most DIFF_LINES."""
    def lines(v):
        return json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    diff = list(difflib.unified_diff(lines(old), lines(new), old_name, new_name, n=2, lineterm=""))
    return diff[:DIFF_LINES] + ([f"… {len(diff) - DIFF_LINES} more lines"] if len(diff) > DIFF_LINES else [])


def one_window(name, found, say):
    """The one window with the marker on a surface, or None after saying why there is none."""
    wins = found.get(name) or []
    if len(wins) == 1:
        return wins[0]
    say(f"{name}: no window with {MARKER!r} is on this surface" if not wins else
        f"{name}: {len(wins)} windows with {MARKER!r} are on this surface; close all of them but one")
    return None


# The subcommands

def record(names, snapshots, say=print):
    """Writes the pending fixture of each surface that a marked window is on; the exit code."""
    chosen = selected(names)
    found = scan(chosen, snapshots, say)
    written = 0
    for s in chosen:
        window = one_window(s.name, found, say)
        if window is None:
            continue
        try:
            fixture, others = make(window)
        except Problem as e:
            say(str(e))
            continue
        again = replay(fixture)
        if again != fixture["expected"]:
            say(f"{s.name}: not written: a replay from the kept files gives another parse. The adapter read files "
                f"without {MARKER!r}: {', '.join(others) or 'none'}")
            say("\n".join(difference(fixture["expected"], again, "live", "replay")))
            continue
        path = place(s.name) / PENDING
        save(path, fixture)
        say(review(fixture, others))
        say(f"  written: {path}\n")
        written += 1
    return 0 if written and (written == len(chosen) or not names) else 1


def accept(names, say=print):
    """Each surface's pending fixture becomes its fixture of that app version; the exit code."""
    if not names:
        raise Problem("accept needs the surfaces, for example: accept claude-chat/desktop")
    for name in names:
        pending = place(name) / PENDING
        if not pending.is_file():
            raise Problem(f"{name}: no pending fixture ({pending}): record it first")
        fixture = load(pending)
        path = place(name) / file_name(fixture["app"].get("version"))
        replaced = path.is_file()
        pending.replace(path)
        say(f"{name}: accepted as {path}" + (", in place of the fixture of the same version" if replaced else ""))
    return 0


def check(names, snapshots, say=print):
    """Compares each surface's live parse with its newest fixture; writes nothing; the exit code."""
    names = list(names) or list(dict.fromkeys(n for n, _, _ in accepted()))
    if not names:
        raise Problem(f"no fixture in {folder()}: record and accept them first")
    chosen = selected(names)
    found = scan(chosen, snapshots, say)
    differ, unchecked = False, False
    for s in chosen:
        stored = newest(s.name)
        if stored is None:
            say(f"{s.name}: not checked: it has no fixture")
            unchecked = True
            continue
        version, path = stored
        window = one_window(s.name, found, say)
        if window is None:
            say(f"{s.name}: not checked")
            unchecked = True
            continue
        try:
            now, _ = make(window)
        except Problem as e:
            now = {"expected": {"problem": str(e)}, "app": window.identity.get("app") or {}, "read": window.request,
                   "content": window.content}
        fixture = load(path)
        same = now["expected"] == fixture["expected"]
        differ = differ or not same
        say(f"{s.name}: {now['app'].get('version')} now, {version} in {path.name}: {'same' if same else 'different'}")
        if now["read"] != fixture["read"]:
            say("  the read request is not the fixture's")
        say(f"  the content read: {'the same' if now['content'] == fixture['content'] else 'not the same'}")
        if not same:
            say("\n".join("  " + line for line in difference(fixture["expected"], now["expected"],
                                                                f"fixture {version}", "now")))
    return 1 if differ else 2 if unchecked else 0


SANDBOX_NOTES = f"""# {MARKER}: notes

The Markdown file of the fixtures' sandbox. Open it in the Files panel of the Code tab.

## Что здесь проверяется

Адаптер читает этот файл с диска, когда он открыт в панели Files. Термины на английском: `pyproject.toml`,
Kubernetes, `git rebase`.

- Первый пункт списка с `inline code`.
- Второй пункт со [ссылкой](https://example.com/docs).

```python
print("a code block, which clean leaves out")
```
"""


def sandbox(say=print):
    """Makes the sandbox folder with its Markdown file, if it is not there; the exit code."""
    path = folder() / SANDBOX / "notes.md"
    if path.exists():
        say(f"the sandbox is there: {path.parent}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SANDBOX_NOTES, encoding="utf-8")
    say(f"made the sandbox: {path.parent}")
    return 0


def main(argv):
    if not argv or argv[0] not in ("record", "accept", "check", "sandbox"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 1
    command, names = argv[0], argv[1:]
    try:
        if command == "record":
            return record(names, Snapshots())
        if command == "accept":
            return accept(names)
        if command == "check":
            return check(names, Snapshots())
        return sandbox()
    except Problem as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
