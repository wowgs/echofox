"""The llama-server process of a model on this Mac: where llama.cpp's server is, its command (the files of the model's
variant in the models folder, catalog.py; its address; its catalog entry's arguments), its start as this process's
child, its end, the end of one left by a server that was killed, the wait until it answers, and its memory. The model
registry (model_registry.py) decides when; the tests' sandbox and fakes replace spawn, end, end_stale, command and
wait_healthy here, so their callers reach them through this module (llama_process.spawn), never by a name of their
own."""
import contextlib
import ctypes
import ctypes.util
import logging
import os
import signal
import subprocess
import time
import urllib.parse
import urllib.request

import catalog
import constants

log = logging.getLogger("echofox-server")
SHORT_TIMEOUT_S = 10  # /health, lsof, ps
HEALTH_POLL_S = 1
TERM_WAIT_S = 30      # a llama-server has this long to end after SIGTERM, then it is killed
BUNDLED_LLAMA_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llama", "llama-server")
LOCAL_HOSTS = (constants.HOST, "localhost")


def llama_server():
    """llama.cpp's server: the app bundle's (Contents/Resources/llama, next to the server's folder), else the installed
    app's (constants.LLAMA_SERVER), for a server that runs from the repository; None if neither is there."""
    for path in (BUNDLED_LLAMA_SERVER, constants.LLAMA_SERVER):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def local(entry):
    """Whether the entry's llama-server is on this Mac, so that the server starts it; one on another computer is
    only asked."""
    return urllib.parse.urlparse(entry["llamaServer"]).hostname in LOCAL_HOSTS


def command(entry, models_folder):
    """The command of a registry entry's llama-server: the files of the entry's variant, the address of its
    llamaServer, its catalog entry's arguments. Raises RuntimeError if a file of the variant or llama-server is
    missing."""
    vid, spec = catalog.variant(entry)
    if spec is None:
        raise RuntimeError(f"the catalog has no variant {vid!r} of {entry.get('catalog') or catalog.DEFAULT}")
    files = catalog.files(entry, models_folder)
    missing = [p for p in files.values() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(f"the files of variant {vid} are missing: {', '.join(missing)}")
    binary = llama_server()
    if not binary:
        raise RuntimeError(f"no llama-server, neither in the app nor at {constants.LLAMA_SERVER}")
    url = urllib.parse.urlparse(entry["llamaServer"])
    return [binary, "-m", files["model"], "--mmproj", files["mmproj"], "--host", url.hostname,
            "--port", str(url.port or 80), *catalog.of(entry)["llamaServer"]["args"]]


def spawn(argv):
    """Starts a llama-server as this process's child, its output appended to its log (constants.LOGS)."""
    log_file = constants.path(f"{constants.LOGS}/llama-server.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "ab") as out:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    log.info("started llama-server, pid %d: %s", proc.pid, " ".join(argv[:5]))
    return proc


def end(proc):
    """Ends a llama-server that this process started: SIGTERM, then SIGKILL after TERM_WAIT_S."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(TERM_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log.info("stopped llama-server, pid %d", proc.pid)


def end_stale(port):
    """Ends a llama-server that listens on this port but is not this process's child: one left by a server that was
    killed before it could stop it. Another program on the port is left alone (the start then fails and says so)."""
    pid = listening_pid(port)
    if not pid:
        return
    try:
        name = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True,
                              timeout=SHORT_TIMEOUT_S).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if os.path.basename(name) != "llama-server":
        return
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)
    end_at = time.monotonic() + TERM_WAIT_S
    while listening_pid(port) == pid and time.monotonic() < end_at:
        time.sleep(HEALTH_POLL_S / 10)
    log.info("stopped a llama-server left on port %d, pid %d", port, pid)


def wait_healthy(url, seconds=constants.MODEL_START_S, stop=None):
    """Waits until a llama-server answers /health with 200 (it loads its model first); False at once when `stop` (a
    threading.Event) is set: the server ends, and its end must not wait for a model that will not come."""
    end_at = time.monotonic() + seconds
    while time.monotonic() < end_at and not (stop and stop.is_set()):
        try:
            with urllib.request.urlopen(url + "/health", timeout=SHORT_TIMEOUT_S) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        if stop:
            stop.wait(HEALTH_POLL_S)
        else:
            time.sleep(HEALTH_POLL_S)
    return False


_libproc = ctypes.CDLL(ctypes.util.find_library("proc")) if ctypes.util.find_library("proc") else None


def footprint_mb(pid):
    """A process's physical footprint in MB, as macOS counts it (proc_pid_rusage, rusage_info_v0: ri_phys_footprint
    is the 8th 64-bit field after the 16-byte uuid; the same number as `footprint <pid>`). None if unknown."""
    if not _libproc or not pid:
        return None
    buf = (ctypes.c_uint64 * 12)()
    if _libproc.proc_pid_rusage(int(pid), 0, ctypes.byref(buf)) != 0:
        return None
    return round(buf[2 + 7] / 2**20)


def listening_pid(port):
    """The process listening on this TCP port of this Mac, or None (lsof)."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                             timeout=SHORT_TIMEOUT_S).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
