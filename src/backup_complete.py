import json
import os
import re
import time

import fsio

FILES_STATUS = "files_status.json"
FAILED_MAX = 50
FD_RX = re.compile(r"^files_(\d{8})$")


def _is_err(v) -> bool:
    return isinstance(v, str) and v.startswith("err")


def files_state_of(out: dict, day: str, extra_failed: dict = None, candles: str = "candles") -> dict:
    keys = [k for k in out if "#" not in k]
    failed = {k: str(out[k])[:200] for k in keys if _is_err(out[k])}
    for k, v in (extra_failed or {}).items():
        failed[k] = str(v)[:200]
    nf = len(failed) + max(0, int(out.get(candles + "/#failed") or 0) - FAILED_MAX)
    return {"v": 1, "day": day, "ts": int(time.time()), "ok": nf == 0,
            "expected": sorted(k for k in keys if not (k.startswith(candles + "/") and k != candles + "/")) + sorted(extra_failed or ()),
            "copied": sorted(k for k in keys if not _is_err(out[k])), "failed": dict(sorted(failed.items())[:FAILED_MAX]), "n_failed": nf}


def write_dir_state(path: str, fs: dict):
    try:
        fsio.atomic_write_bytes(os.path.join(path, FILES_STATUS), json.dumps(fs, ensure_ascii=False, indent=1).encode("utf-8"),
                                fsync=False, dir_fsync=False, makedirs=False)
        return None
    except OSError as e:
        return f"{type(e).__name__}: {e}"[:160]


def mark_pending(path: str, day: str) -> bool:
    return write_dir_state(path, {"v": 1, "day": day, "ts": int(time.time()), "ok": False, "expected": [], "copied": [],
                                  "failed": {FILES_STATUS: "작성 중(끝나지 않음)"}, "n_failed": 1}) is None


def files_dir_state(path: str):
    p = os.path.join(path, FILES_STATUS)
    if not os.path.lexists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("ok"), bool):
            return d
    except (OSError, ValueError):
        pass
    return {"ok": False, "failed": {FILES_STATUS: "완전성 기록을 못 읽음"}, "n_failed": 1}


def last_complete_dir(bdir: str, before: str = None):
    try:
        names = sorted((n for n in os.listdir(bdir) if FD_RX.match(n) and os.path.isdir(os.path.join(bdir, n))), reverse=True)
    except OSError:
        return None
    for n in names:
        if before and n >= before:
            continue
        s = files_dir_state(os.path.join(bdir, n))
        if s is None or s.get("ok") is True:
            return n
    return None


def files_brief(fs: dict) -> str:
    names = sorted((fs.get("failed") or {}))
    n = int(fs.get("n_failed") or len(names))
    return f"원장 밖 사본 일부 실패 {n}개: " + ", ".join(names[:5]) + (" …" if n > 5 else "")
