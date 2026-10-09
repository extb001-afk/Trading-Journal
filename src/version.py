import os
import re

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(CODE_ROOT, "VERSION")
_RX = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,39}")
_cache = {"mt": None, "v": None}


def app_version() -> str:
    try:
        mt = os.path.getmtime(VERSION_FILE)
    except OSError:
        return "알 수 없음"
    if _cache["mt"] != mt:
        try:
            with open(VERSION_FILE, encoding="utf-8") as f:
                line = (f.readline() or "").strip()
        except (OSError, UnicodeDecodeError):
            line = ""
        _cache.update(mt=mt, v=line if _RX.fullmatch(line) else "알 수 없음")
    return _cache["v"]
