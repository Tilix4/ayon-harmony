"""Temporary debug instrumentation (session d7cc94, publish hang investigation).

Monkeypatches core AYON server functions at addon startup and appends
NDJSON lines to a log file ($AYON_DEBUG_LOG > /storage/ayon-debug-d7cc94.log
when present, i.e. inside the container, else ~/ayon-debug-d7cc94.log).

All logging failures are swallowed so request handling can never break.
Teardown: remove this addon version from the bundle and restart the server.
"""

import contextlib
import functools
import itertools
import json
import os
import time

_SESSION_ID = "d7cc94"
_counter = itertools.count()
_originals = {}
_installed = False


def _log_path():
    path = os.environ.get("AYON_DEBUG_LOG")
    if path:
        return path
    if os.path.isdir("/storage"):
        return "/storage/ayon-debug-d7cc94.log"
    return os.path.join(os.path.expanduser("~"), "ayon-debug-d7cc94.log")


def dbg(location, message, data=None, hypothesis=None):
    try:
        now = time.time()
        line = json.dumps(
            {
                "sessionId": _SESSION_ID,
                "runId": os.environ.get("AYON_DEBUG_RUN_ID", "run1"),
                "hypothesisId": hypothesis,
                "id": "log_{}_{}_{}".format(
                    int(now * 1000), os.getpid(), next(_counter)
                ),
                "timestamp": int(now * 1000),
                "location": location,
                "message": message,
                "data": data or {},
            }
        )
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


@contextlib.contextmanager
def dbgt(location, message, data=None, hypothesis=None):
    """Timed block: emits START, then END/ERROR with elapsed and any extras."""
    t0 = time.time()
    dbg(location, message + " START", data, hypothesis)
    extra = {}
    try:
        yield extra
    except BaseException as exc:
        payload = dict(data or {})
        payload.update(extra)
        payload["elapsed_s"] = round(time.time() - t0, 3)
        payload["error"] = repr(exc)
        dbg(location, message + " ERROR", payload, hypothesis)
        raise
    payload = dict(data or {})
    payload.update(extra)
    payload["elapsed_s"] = round(time.time() - t0, 3)
    dbg(location, message + " END", payload, hypothesis)


# region agent log


def _patch_upload():
    from ayon_server.files.project_storage import ProjectStorage

    orig = ProjectStorage.handle_upload
    _originals["ProjectStorage.handle_upload"] = orig

    @functools.wraps(orig)
    async def handle_upload_traced(self, request, file_id, *args, **kwargs):
        meta = {
            "file_id": file_id,
            "content_length": request.headers.get("content-length"),
            "client": request.client.host if request.client else None,
        }
        with dbgt(
            "project_storage.py:handle_upload",
            "server upload stream",
            meta,
            "H1/H2",
        ) as extra:
            result = await orig(self, request, file_id, *args, **kwargs)
            extra["bytes_written"] = result
        return result

    ProjectStorage.handle_upload = handle_upload_traced


def _patch_ffprobe():
    from ayon_server.helpers import ffprobe as ffprobe_mod

    orig = ffprobe_mod.ffprobe
    _originals["ffprobe"] = orig

    @functools.wraps(orig)
    async def ffprobe_traced(file_path):
        with dbgt(
            "ffprobe.py:ffprobe", "server ffprobe", {"file": file_path}, "H3"
        ):
            return await orig(file_path)

    ffprobe_mod.ffprobe = ffprobe_traced


def _patch_preview():
    from ayon_server.helpers import preview as preview_mod

    orig = preview_mod.create_video_thumbnail
    _originals["create_video_thumbnail"] = orig

    @functools.wraps(orig)
    async def create_video_thumbnail_traced(video_path, *args, **kwargs):
        meta = {
            "video": video_path,
            "semaphore_slots": getattr(
                preview_mod.PREVIEW_SEMAPHORE, "_value", None
            ),
        }
        with dbgt(
            "preview.py:create_video_thumbnail",
            "server preview (semaphore+ffmpeg)",
            meta,
            "H3",
        ):
            return await orig(video_path, *args, **kwargs)

    preview_mod.create_video_thumbnail = create_video_thumbnail_traced


def _patch_events():
    from ayon_server.events import EventStream

    orig = EventStream.dispatch
    _originals["EventStream.dispatch"] = orig

    @functools.wraps(orig)
    async def dispatch_traced(cls, topic, **kwargs):
        meta = {"topic": topic, "project": kwargs.get("project")}
        with dbgt(
            "eventstream.py:dispatch", "server event dispatch", meta, "H2/H4"
        ):
            return await orig(topic, **kwargs)

    EventStream.dispatch = classmethod(dispatch_traced)


def _patch_postgres():
    from ayon_server.lib.postgres import Postgres

    def make_wrapper(orig_fn, label):
        @functools.wraps(orig_fn)
        async def query_traced(cls, query, *args, **kwargs):
            op = query.strip().split(None, 1)[0].upper() if query else "?"
            meta = {"op": op, "method": label}
            with dbgt(
                "postgres.py:" + label, "server postgres query", meta, "H2/H4"
            ):
                return await orig_fn(query, *args, **kwargs)

        return query_traced

    for name in ("execute", "fetchrow"):
        orig = getattr(Postgres, name)
        _originals["Postgres." + name] = orig
        setattr(Postgres, name, classmethod(make_wrapper(orig, name)))


# endregion


def install_instrumentation():
    global _installed
    if _installed:
        return
    _installed = True

    patches = [
        ("ProjectStorage.handle_upload", _patch_upload),
        ("ffprobe", _patch_ffprobe),
        ("create_video_thumbnail", _patch_preview),
        ("EventStream.dispatch", _patch_events),
        ("Postgres.execute+fetchrow", _patch_postgres),
    ]
    patched = []
    for label, patch_fn in patches:
        try:
            patch_fn()
            patched.append(label)
        except Exception as exc:
            dbg(
                "debug_d7cc94",
                "patch FAILED",
                {"target": label, "error": repr(exc)},
            )
    dbg(
        "debug_d7cc94",
        "instrumentation installed",
        {"patched": patched, "pid": os.getpid()},
    )


def uninstall_instrumentation():
    global _installed
    for label, orig in _originals.items():
        try:
            if label == "ProjectStorage.handle_upload":
                from ayon_server.files.project_storage import ProjectStorage

                ProjectStorage.handle_upload = orig
            elif label == "ffprobe":
                from ayon_server.helpers import ffprobe as ffprobe_mod

                ffprobe_mod.ffprobe = orig
            elif label == "create_video_thumbnail":
                from ayon_server.helpers import preview as preview_mod

                preview_mod.create_video_thumbnail = orig
            elif label == "EventStream.dispatch":
                from ayon_server.events import EventStream

                EventStream.dispatch = orig
            elif label.startswith("Postgres."):
                from ayon_server.lib.postgres import Postgres

                setattr(Postgres, label.split(".", 1)[1], orig)
        except Exception:
            pass
    _originals.clear()
    _installed = False
