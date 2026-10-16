from __future__ import annotations
import hashlib
import os
import re
import threading
import common
import websnap

WEB_DIR = os.path.join(common.BASE_DIR, "web")


UI_DEFAULT = "v2"


V2_DIR = os.path.join(WEB_DIR, "v2")


_V2_FILES = {"index.html": "text/html; charset=utf-8",
             "app.js": "application/javascript; charset=utf-8",
             "health.js": "application/javascript; charset=utf-8",
             "search.js": "application/javascript; charset=utf-8",
             "salelink.js": "application/javascript; charset=utf-8",
             "wow.js": "application/javascript; charset=utf-8"}


_V2_TABS = ("tab_other.js", "tab_rcpt.js", "tab_dash.js", "tab_jrnl.js", "tab_daily.js", "tab_out.js", "tab_set.js")


_V2_FILES.update({n: "application/javascript; charset=utf-8" for n in _V2_TABS})


V2_FONT_DIR = os.path.join(V2_DIR, "fonts")


_V2_FONT_RE = re.compile(r"[a-z]{1,16}-[0-9]{3}-[0-9a-f]{12}\.woff2")


def _ui_route(path: str):
    if path in ("/v2", "/v2/", "/v2/index.html") or (UI_DEFAULT == "v2" and path in ("/", "/index.html")):
        return os.path.join(V2_DIR, "index.html"), _V2_FILES["index.html"]
    if path.startswith("/v2/") and path[4:] in _V2_FILES:
        return os.path.join(V2_DIR, path[4:]), _V2_FILES[path[4:]]
    if path.startswith("/v2/fonts/"):
        n9 = path[len("/v2/fonts/"):]
        ct9 = "text/css; charset=utf-8" if n9 == "plex.css" else "font/woff2" if _V2_FONT_RE.fullmatch(n9) else None
        f9 = os.path.join(V2_FONT_DIR, n9) if ct9 else None
        return (f9, ct9) if f9 and os.path.isfile(f9) else None
    if path == "/classic" and os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        return os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8"
    return None


_ASSETS = {}


_ASSETS_LOCK = threading.Lock()


_V2_JS_RE = re.compile(rb'<script src="/v2/app\.js"></script>')


_V2_VER_JS = ("health.js", "search.js", "wow.js", "setup.js") + _V2_TABS


def _asset(fpath: str) -> dict:
    deps = [fpath]
    v2_index = os.path.normpath(fpath) == os.path.normpath(os.path.join(V2_DIR, "index.html"))
    font_css = os.path.join(V2_FONT_DIR, "plex.css")
    if v2_index:
        deps.append(os.path.join(V2_DIR, "app.js"))
        deps += [os.path.join(V2_DIR, n) for n in _V2_VER_JS]
        if os.path.isfile(font_css):
            deps.append(font_css)
    key = tuple((os.stat(d).st_mtime_ns, os.stat(d).st_size) for d in deps)
    with _ASSETS_LOCK:
        ent = _ASSETS.get(fpath)
        if ent and ent[0] == key:
            return ent[1]
    with open(fpath, "rb") as f:
        raw = f.read()
    if v2_index:
        js = _asset(deps[1])
        raw = _V2_JS_RE.sub(b'<script src="/v2/app.js?v=' + js["hash"].encode() + b'"></script>', raw)
        for n9 in _V2_VER_JS:
            a9 = _asset(os.path.join(V2_DIR, n9))
            raw = raw.replace(b'<script src="/v2/' + n9.encode() + b'"></script>', b'<script src="/v2/' + n9.encode() + b'?v=' + a9["hash"].encode() + b'"></script>', 1)
        if deps[-1] == font_css:
            fv9 = _asset(font_css)["hash"].encode()
            raw = re.sub(rb"(['\"])/v2/fonts/plex\.css\1", lambda m9: m9.group(1) + b"/v2/fonts/plex.css?v=" + fv9 + m9.group(1), raw, count=1)
    h = hashlib.sha1(raw).hexdigest()[:16]
    a = {"raw": raw, "gz": websnap.gz(raw) if len(raw) >= 1024 else None, "etag": f'W/"{h}"', "hash": h}
    with _ASSETS_LOCK:
        _ASSETS[fpath] = (key, a)
    return a
