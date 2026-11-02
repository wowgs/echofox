"""Fixtures from live windows: real snapshots of the adapters' surfaces, taken of the owner's own conversations as they
are open on the screen, kept on this Mac only, and checked again when an app updates (docs/reference/8-fixtures.md).

Usage: server/.venv/bin/python server/tools/fixtures.py record [SURFACE ...]
       server/.venv/bin/python server/tools/fixtures.py accept SURFACE ...
       server/.venv/bin/python server/tools/fixtures.py check [SURFACE ...]
SURFACE is <adapter>/<id>, for example claude-chat/desktop.

record: for each running app of the surfaces (none named: every surface of every working adapter) and each of its
  windows, macos echofox-snapshot reads the identity. The server's matching (adapters.surfaces) tells the surfaces the
  window is on, and the tool builds the read request as the server does, with the budgets of the default config
  (resolve.budget), so that the owner's own settings do not change a fixture. echofox-snapshot reads the content, and
  the core runs the surface's adapter on it (adapters.context, with clean). The first window on the surface that gives
  a context, in the order of the surface's apps and of each app's windows, is recorded. The tool names the other
  windows with a context that it left. The fixture's "expected" is what of that context reaches the model: the terms,
  messages and documents that the budgets of the default config keep (prompt.held). The files that the adapter read
  go into the fixture too, so that a replay needs no live disk. Of a file over LIMIT, only its fewest last lines that
  the replay needs are kept, at most LIMIT bytes. record writes nothing for a surface whose replay from the kept files
  gives another expected value. Otherwise it writes fixtures/<adapter>/<id>/pending.json and prints it for review.
accept: the pending file of each surface becomes its fixture of that app version:
  fixtures/<adapter>/<id>/<version>.json.
check: the same snapshot, parse and expected value as record, compared with the fixture of the newest version of each
  surface (none named: every surface that has a fixture). It prints the app's version now and in the fixture, same or
  different, and the differences, and it writes nothing.

The fixtures are in $ECHOFOX_FIXTURES, else in fixtures/ at the repository's root, which git leaves out. A fixture
holds the conversation's text as the app shows it and the files that the adapter read: it never leaves this Mac.
echofox-snapshot is $ECHOFOX_SNAPSHOT, else the release or debug build in macos/.build. It needs the Accessibility
permission of the app that runs this tool (the terminal). The tool runs without questions: exit code 0 when all went
well, 1 when a surface was not recorded or check found a difference, 2 when check found no difference but could not
check a surface.
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
import shutil
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # the server's modules: a tool is in server/tools

import adapters  # noqa: E402
import catalog  # noqa: E402
import prompt  # noqa: E402
import resolve  # noqa: E402
import settings  # noqa: E402
from adapters import registry, screen, surfaces  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PENDING = "pending.json"
# A file that the adapter read and that is bigger keeps only a tail of at most this size in the fixture (cut). A
# fixture is one JSON file: the tests load it whole, and check diffs it. A Claude Code transcript is the log of a whole
# session, with tool output and images in base64 in it. Measured on 2026-11-02 on the transcript of a long session,
# 182 MB in 32,494 lines: its last three replies (3,677 characters, about the 1000 tokens of the chat budget) were in
# its last 0.26 MB. Its expected value needed more of it: the title, which the reader takes from the first
# "custom-title" line (the session was renamed at line 9,384), and the terms, which the core counts in every reply.
# Halving found 32,421 last lines (181.5 MB) as the fewest that gave the same expected value.
LIMIT = 1_000_000  # bytes
# A replay's home folder is the live one's path under a new folder REPLAY_ROOT/echofox-fixture-<pid>-<n>/=, so that
# the core reads the messages' paths as on the live disk. "~/notes.md" is "/Users/alex/notes.md" on the Mac, and
# ".../=/Users/alex/notes.md" in a replay. A term's word (adapters.WORD) does not run through "=", so both give the
# word "Users/alex/notes.md". The word before "=", "private/tmp/echofox-fixture-<pid>-<n>", has two slashes, and the
# terms leave out such a word. The path has no underscore, because Markdown's clean reads underscores as emphasis.
# Checked on 2026-11-02 in loops of 300 replays of a test: with a folder that tempfile made in $TMPDIR
# (/var/folders/d9/t_rp81w…/T/echofox-fixture-<random>), a random name such as "x__ab12" gave the replay the term
# "ab12", and the underscores of the two paths of one message became emphasis. With this folder, no replay differed.
REPLAY_ROOT = "/private/tmp"
WORD_BREAK = "="
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
        """The identities of the app's windows, in the order of the app's AXWindows attribute, which
        FocusSnapshot.windows keeps; None when the app does not run."""
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


def defaults():
    """The server's settings, the model's entry and the recording's options of the default config: the budgets and the
    token weights of the tool, so that the owner's own settings never change a fixture."""
    now = settings.in_force({})
    entry = next(iter(now["models"].values()))
    return settings.recording_settings(now), entry, resolve.model(entry)


def read_message(matched):
    """The read message for the matched surfaces, as the server sends it (session.Session.read_request), with the
    budgets and the token weights of the default config's model."""
    server, entry, options = defaults()
    return {"type": "read", "surfaces": adapters.read(matched, lambda a, key: resolve.budget(a, key, options, server)),
            "tokenWeights": catalog.token_weights(entry)}


@dataclasses.dataclass
class Window:
    """A window on a surface: what the app sends for that surface."""
    surface: surfaces.Surface
    bundle: str
    index: int  # in the app's list of its windows (Snapshots.windows)
    identity: dict
    request: dict  # the read message of this surface alone
    content: dict  # what was read for this surface

    def __str__(self):
        return f"window {self.index} of {self.bundle} ({screen.window_title(self.identity)!r})"


def scan(chosen, snapshots):
    """The windows of the running apps of the `chosen` surfaces that are on them: {surface name: [Window]}, in the order
    of the surface's apps in its manifest, then in the order of each app's windows (Snapshots.windows). The read
    request of a window is the server's for every chosen surface that the window is on."""
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
                request_of_s = {**request, "surfaces": [r for r in request["surfaces"] if r["surface"] == s.name]}
                found[s.name].append(Window(s, bundle, i, now, request_of_s,
                                            surfaces.recorded(got.get("content"), s.name)))
    for s in chosen:
        found[s.name].sort(key=lambda w: (s.spec["apps"].index(w.bundle), w.index))
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


def expected(found, home_dir, pids=()):
    """What of the core's context `found` reaches the model, as a fixture compares it: "about", "source", "details",
    and the "terms", "messages" and "documents" that the budgets of the default config keep (prompt.held), with no
    language (English speech would drop the terms). The home folder and the process ids are written alike first
    (normalized), so that a replay under another home folder takes the same items. A parse without a context gives
    what it gave: None, or its "errors"."""
    found = normalized(found, home_dir, pids)
    if not found or not found.get("adapter"):
        return found
    server, entry, options = defaults()
    out = {k: found[k] for k in ("about", "source", "details") if k in found}
    out.update(prompt.held(found, resolve.adapter(found["adapter"], options, server), server, "",
                           catalog.token_weights(entry)))
    if found.get("errors"):
        out["errors"] = found["errors"]
    return out


def sources(paths, home_dir):
    """The files of `paths` as a fixture keeps them: [{"path": from ~/ under the home folder, "mtime": in ns, "text": as
    it is}]; and the other paths, which are not files of UTF-8 text and are not kept. The text keeps the home folder's
    real path: a replay puts its own home folder in its place (replay), and a "~/" that the text itself holds stays."""
    kept, others = [], []
    for p in sorted(paths):
        if p.endswith((".py", ".pyc", ".so")):
            continue  # a module that Python imported while the adapter ran
        try:
            text, mtime = pathlib.Path(p).read_text(encoding="utf-8"), os.stat(p).st_mtime_ns
        except (OSError, UnicodeDecodeError):
            others.append(p)
            continue
        if os.path.isfile(p):
            kept.append({"path": tilde(p, home_dir), "mtime": mtime, "text": text})
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


def replay_home(parent, home_dir):
    """The replay's home folder in the new folder `parent`, for the recorded home folder `home_dir` (REPLAY_ROOT)."""
    return os.path.join(parent, WORD_BREAK) + home_dir.rstrip("/")


@contextlib.contextmanager
def replay_folder():
    """A new empty folder for a replay, REPLAY_ROOT/echofox-fixture-<pid>-<n>, removed after the block."""
    n = 0
    while True:
        path = os.path.join(REPLAY_ROOT, f"echofox-fixture-{os.getpid()}-{n}")
        try:
            os.mkdir(path, 0o700)
            break
        except FileExistsError:
            n += 1
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def replay(fixture):
    """The expected value of a fixture's snapshot by the adapter as it is now, with the fixture's files under a new
    home folder in place of the live disk: the recorded home folder's path under a new folder (replay_home). A file
    outside the home folder is not moved, so the adapter reads it on the disk. Raises Problem when no working adapter
    has the surface."""
    surface = surface_of(fixture["surface"])
    if surface is None:
        raise Problem(f"no working adapter has the surface {fixture['surface']}")
    with replay_folder() as parent:
        root = replay_home(parent, fixture["home"])
        for s in fixture.get("sources") or []:
            if not s["path"].startswith("~/"):
                continue
            path = os.path.join(root, s["path"][2:])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                text = s["text"]
                for recorded in sorted({fixture["home"].rstrip("/"), os.path.realpath(fixture["home"]).rstrip("/")},
                                       key=len, reverse=True):
                    text = text.replace(recorded + "/", root + "/")
                f.write(text)
            os.utime(path, ns=(s["mtime"], s["mtime"]))
        with home_at(root):
            found, _ = parse(surface, fixture["identity"], fixture["content"])
        return expected(found, root, pids_of(fixture["identity"], fixture["content"]))


def fewest(total, works):
    """The fewest n of 0..total for which works(n), by halving, when works(total). It takes that a longer tail works
    when a shorter one does. When that does not hold, it gives an n that works, which is not always the fewest."""
    fails, works_at = -1, total
    while works_at - fails > 1:
        n = (fails + works_at) // 2
        if works(n):
            works_at = n
        else:
            fails = n
    return works_at


def cut(fixture):
    """Keeps only a tail of each of the fixture's files over LIMIT: its fewest last lines with which the replay still
    gives the fixture's "expected" (fewest), among the tails of at most LIMIT bytes, and the number of lines left out
    ("linesLeftOut"). The core knows no file's format, so the replay is the only judge. Raises Problem, with the
    difference, when the longest of those tails gives another expected value."""
    for s in fixture["sources"]:
        whole = s["text"]
        size = len(whole.encode("utf-8"))
        if size <= LIMIT:
            continue
        lines = whole.splitlines(keepends=True)
        most, used = 0, 0
        while most < len(lines) and used + len(lines[-1 - most].encode("utf-8")) <= LIMIT:
            used += len(lines[-1 - most].encode("utf-8"))
            most += 1
        again = None

        def works(n):
            nonlocal again
            s["text"] = "".join(lines[len(lines) - n:])
            again = replay(fixture)
            return again == fixture["expected"]

        if not works(most):
            s["text"] = whole
            raise Problem("\n".join([
                f"{fixture['surface']}: not written: {s['path']} has {size / 1e6:.1f} MB, over the {LIMIT / 1e6:g} MB "
                f"limit of a kept file, and its last {most} of {len(lines)} lines, the most within the limit, give "
                "another expected value:", *difference(fixture["expected"], again, "live", "replay")]))
        n = fewest(most, works)
        s["text"] = "".join(lines[len(lines) - n:])
        s["linesLeftOut"] = len(lines) - n


def context_of(window):
    """The core's context of a window and the files that the adapter opened; raises Problem when the adapter gave no
    context or an error."""
    found, opened = parse(window.surface, window.identity, window.content)
    if not found or not found.get("adapter"):
        errors = "; ".join((found or {}).get("errors") or []) or "the adapter did not find the conversation"
        raise Problem(f"{window}: no context: {errors}")
    if found.get("errors"):
        raise Problem(f"{window}: the adapter failed: {'; '.join(found['errors'])}")
    return found, opened


def pick(name, windows, say):
    """The first of a surface's windows (scan) that gives a context: (window, its context, the files the adapter
    opened); None, after saying why, when none does. It names the other windows with a context, which it leaves."""
    picked, why, left = None, [], []
    for w in windows:
        try:
            found, opened = context_of(w)
        except Problem as e:
            why.append(str(e))
            continue
        if picked is None:
            picked = (w, found, opened)
        else:
            left.append(str(w))
    if picked is None:
        say(f"{name}: no window on this surface gives a context: " + "; ".join(why))
    elif left:
        say(f"{name}: {picked[0]} is taken, the first with a context. Left: {', '.join(left)}")
    return picked


def make(window, found, opened, home_dir=None):
    """The fixture of a window with its context `found`: {"surface", "app": {bundleId, version}, "macos", "date",
    "home", "identity", "read", "content", "sources", "expected"}, and the paths that the adapter read and that are not
    kept."""
    home_dir = home_dir or home()
    kept, others = sources(opened, home_dir)
    app = window.identity.get("app") or {}
    return {"surface": window.surface.name, "app": {"bundleId": app.get("bundleId"), "version": app.get("version")},
            "macos": platform.mac_ver()[0], "date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "home": home_dir, "identity": window.identity, "read": window.request, "content": window.content, "sources": kept,
            "expected": expected(found, home_dir, pids_of(window.identity, window.content))}, others


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
    """Every accepted fixture: [(surface name, app version, path)], by surface, the oldest version first. The pending
    files and the folders that are no adapter's are left out."""
    root = root or folder()
    out = []
    if not root.is_dir():
        return out
    for a in sorted(root.iterdir()):
        if not a.is_dir() or not registry.NAME.fullmatch(a.name) or a.name.startswith("."):
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
              "  what the budgets keep:",
              f"  terms ({len(e.get('terms') or [])}): {', '.join(e.get('terms') or [])}",
              f"  messages ({len(e.get('messages') or [])}, the newest first):"]
    for n, m in enumerate(e.get("messages") or [], 1):
        lines += [f"    {n}. {m['from']}:", indented(m["text"])]
    lines.append(f"  documents ({len(e.get('documents') or [])}):")
    for d in e.get("documents") or []:
        lines += [f"    {d['name']}, {len(d['text'])} characters:", indented(d["text"])]
    lines.append("  files kept: " + (", ".join(s["path"] + (f" (its last lines, {s['linesLeftOut']} left out)"
                                                            if s.get("linesLeftOut") else "")
                                               for s in fixture["sources"]) or "none"))
    if others:
        lines.append(f"  files read and not kept: {', '.join(others)}")
    return "\n".join(lines)


def difference(old, new, old_name, new_name):
    """The lines that differ between two expected values, as a unified diff of their JSON, at most DIFF_LINES."""
    def lines(v):
        return json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    diff = list(difflib.unified_diff(lines(old), lines(new), old_name, new_name, n=2, lineterm=""))
    return diff[:DIFF_LINES] + ([f"… {len(diff) - DIFF_LINES} more lines"] if len(diff) > DIFF_LINES else [])


# The subcommands

def record(names, snapshots, say=print):
    """Writes the pending fixture of each surface that a window with a context is on; the exit code."""
    chosen = selected(names)
    found = scan(chosen, snapshots)
    written = 0
    for s in chosen:
        if not found[s.name]:
            say(f"{s.name}: no window is on this surface")
            continue
        picked = pick(s.name, found[s.name], say)
        if picked is None:
            continue
        fixture, others = make(*picked)
        again = replay(fixture)
        if again != fixture["expected"]:
            say(f"{s.name}: not written: a replay from the kept files gives another expected value. The adapter read "
                f"files that are not kept: {', '.join(others) or 'none'}")
            say("\n".join(difference(fixture["expected"], again, "live", "replay")))
            continue
        try:
            cut(fixture)
        except Problem as e:
            say(str(e))
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
    """Compares the expected value of each surface's first window with a context with its newest fixture; writes
    nothing; the exit code. Windows on the surface without a context count as a difference."""
    names = list(names) or list(dict.fromkeys(n for n, _, _ in accepted()))
    if not names:
        raise Problem(f"no fixture in {folder()}: record and accept them first")
    chosen = selected(names)
    found = scan(chosen, snapshots)
    differ, unchecked = False, False
    for s in chosen:
        stored = newest(s.name)
        if stored is None:
            say(f"{s.name}: not checked: it has no fixture")
            unchecked = True
            continue
        version, path = stored
        if not found[s.name]:
            say(f"{s.name}: not checked: no window is on this surface")
            unchecked = True
            continue
        fixture = load(path)
        picked = pick(s.name, found[s.name], say)
        if picked is None:
            say(f"{s.name}: {(found[s.name][0].identity.get('app') or {}).get('version')} now, {version} in "
                f"{path.name}: different: no context")
            differ = True
            continue
        window, context, _ = picked
        now = expected(context, home(), pids_of(window.identity, window.content))
        same = now == fixture["expected"]
        differ = differ or not same
        say(f"{s.name}: {(window.identity.get('app') or {}).get('version')} now, {version} in {path.name}: "
            f"{'same' if same else 'different'}")
        if window.request != fixture["read"]:
            say("  the read request is not the fixture's")
        say(f"  the content read: {'the same' if window.content == fixture['content'] else 'not the same'}")
        if not same:
            say("\n".join("  " + line for line in difference(fixture["expected"], now, f"fixture {version}", "now")))
    return 1 if differ else 2 if unchecked else 0


def main(argv):
    if not argv or argv[0] not in ("record", "accept", "check"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 1
    command, names = argv[0], argv[1:]
    try:
        if command == "record":
            return record(names, Snapshots())
        if command == "accept":
            return accept(names)
        return check(names, Snapshots())
    except Problem as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
