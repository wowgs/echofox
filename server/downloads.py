"""The downloads of model files (docs/reference/6-protocol.md, "Download a model"): the files of one variant of a
catalog entry, from its source (catalog.url), into the models folder. A download runs in a thread of its own and
goes on when the client leaves; a client that asks for the same variant joins it. Each file is written as
<file>.part and gets its own name only when its size and SHA-256 are right; a part that is there is continued with
an HTTP Range request (Hugging Face answers one with 206 through its CDN, checked 2026-10-25)."""
import hashlib
import logging
import os
import shutil
import threading
import urllib.request

import catalog

log = logging.getLogger("gemma_voice")
CHUNK = 1 << 20                 # bytes read at a time
FREE_MARGIN = 1_000_000_000     # the disk keeps this much free after a download
TIMEOUT_S = 60                  # one read of the connection

_jobs, _lock = {}, threading.Lock()


class Job:
    """The download of one variant's missing files. `done` counts the files already there too."""

    def __init__(self, catalog_id, variant, models_folder):
        entry = {"catalog": catalog_id, "variant": variant}
        vid, spec = catalog.variant(entry)
        if spec is None:
            raise ValueError(f"the catalog has no variant {variant!r} of {catalog_id!r}")
        folder = catalog.folder(entry, models_folder)
        self.files = [{**f, "path": os.path.join(folder, f["file"]), "url": catalog.url(entry, f["file"])}
                      for f in spec["files"].values()]
        self.total = sum(f["bytes"] for f in self.files)
        self.done, self.error, self.cancelled = 0, None, threading.Event()
        self.finished = threading.Event()
        self.key = (catalog_id, vid)

    def run(self):
        try:
            missing = [f for f in self.files if not os.path.isfile(f["path"])]
            self.done = self.total - sum(f["bytes"] for f in missing)
            os.makedirs(os.path.dirname(self.files[0]["path"]), exist_ok=True)
            need = sum(f["bytes"] - _size(f["path"] + ".part") for f in missing) + FREE_MARGIN
            free = shutil.disk_usage(os.path.dirname(self.files[0]["path"])).free
            if free < need:
                raise RuntimeError(f"not enough free disk: the download needs {need / 1e9:.1f} GB, "
                                   f"{free / 1e9:.1f} GB are free")
            for f in missing:
                self._file(f)
                if self.cancelled.is_set():
                    return
            log.info("downloaded %s %s: %.1f GB", *self.key, self.total / 1e9)
        except Exception as e:
            self.error = str(e)
            log.error("download of %s %s: %s", *self.key, e)
        finally:
            with _lock:
                _jobs.pop(self.key, None)
            self.finished.set()

    def _file(self, f):
        part = f["path"] + ".part"
        have = _size(part)
        digest = hashlib.sha256()
        if have:
            with open(part, "rb") as p:
                for block in iter(lambda: p.read(CHUNK), b""):
                    digest.update(block)
        request = urllib.request.Request(f["url"], headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as r:
            if have and r.status != 206:  # the source ignored the range: start the file again
                have, digest = 0, hashlib.sha256()
            self.done += have
            with open(part, "ab" if have else "wb") as out:
                for block in iter(lambda: r.read(CHUNK), b""):
                    if self.cancelled.is_set():
                        return
                    out.write(block)
                    digest.update(block)
                    self.done += len(block)
        size = _size(part)
        if size != f["bytes"]:
            raise RuntimeError(f"{f['file']}: {size} bytes, the catalog says {f['bytes']}")
        if digest.hexdigest() != f["sha256"]:
            os.remove(part)
            raise RuntimeError(f"{f['file']}: its SHA-256 is not the catalog's; the part is deleted")
        os.replace(part, f["path"])
        log.info("downloaded %s (%.1f GB)", f["file"], f["bytes"] / 1e9)


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def running():
    """The variants that download now: {(catalog id, variant)}."""
    with _lock:
        return set(_jobs)


def start(catalog_id, variant, models_folder):
    """The download of a variant: the one that runs, or a new one, started now."""
    job = Job(catalog_id, variant, models_folder)
    with _lock:
        if job.key in _jobs:
            return _jobs[job.key]
        _jobs[job.key] = job
    threading.Thread(target=job.run, name=f"download {job.key}", daemon=True).start()
    log.info("download of %s %s started", *job.key)
    return job


def remove(catalog_id, variant, models_folder, in_force=None):
    """Deletes the files of a variant that no other downloaded variant of the entry uses; the bytes freed. Refuses
    the variant `in_force` (the menu's model's) and one that downloads."""
    entry = {"catalog": catalog_id, "variant": variant}
    vid, spec = catalog.variant(entry)
    if spec is None:
        raise ValueError(f"the catalog has no variant {variant!r} of {catalog_id!r}")
    if vid == in_force:
        raise ValueError(f"{vid} is the variant in force of the menu's model")
    with _lock:
        if (catalog_id, vid) in _jobs:
            raise ValueError(f"{vid} is downloading")
    mine = catalog.files(entry, models_folder)
    shared = set()
    for other in (catalog.of(entry).get("variants") or {}):
        if other != vid:
            paths = catalog.files({**entry, "variant": other}, models_folder).values()
            if all(os.path.isfile(p) for p in paths):
                shared |= set(paths)
    freed = 0
    for path in mine.values():
        for p in (path, path + ".part"):
            if p not in shared and os.path.isfile(p):
                freed += _size(p)
                os.remove(p)
    log.info("removed %s %s: %.1f GB", catalog_id, vid, freed / 1e9)
    return freed
