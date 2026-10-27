from __future__ import annotations
import gzip
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
import paths
import db as dbm
import fsio
import websnap
from timeutil import KST
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


SNAPFILE_EVERY = 300


SNAPFILE_MAX_AGE = 1800


_SNAPFILE = {"at": 0.0, "ver": None, "lock": threading.Lock()}


_SNAPFILE_MAGIC = b"TJSNAP1\n"


_LASTSCAN_KEY = b'"lastScan": '


_LASTSCAN_RX = re.compile(r"(\d+)(초|분) 전 스캔")


def _code_sig() -> str:
    h = hashlib.sha1()
    d9 = os.path.dirname(os.path.abspath(__file__))
    for n9 in sorted(os.listdir(d9)):
        if n9.endswith(".py"):
            with open(os.path.join(d9, n9), "rb") as f9:
                h.update(n9.encode() + b"\0" + f9.read())
    seen9 = set()
    for sd in (os.path.join(os.path.dirname(d9), "seed"), os.path.join(paths.BASE_DIR, "seed")):
        rp = os.path.realpath(sd)
        if rp in seen9 or not os.path.isdir(rp):
            continue
        seen9.add(rp)
        for root9, dirs9, files9 in os.walk(rp):
            dirs9.sort()
            for n9 in sorted(files9):
                fp9 = os.path.join(root9, n9)
                with open(fp9, "rb") as f9:
                    h.update(b"seed:" + os.path.relpath(fp9, rp).encode() + b"\0" + f9.read())
    return h.hexdigest()[:16]


_SIG0 = {}


def _snapfile_sig() -> dict:
    if not _SIG0:
        with open(paths.CONFIG_PATH, "rb") as f9:
            cfg9 = hashlib.sha1(f9.read()).hexdigest()[:16]
        try:
            st9 = os.stat(paths.ENV_PATH)
            env9 = [st9.st_mtime_ns, st9.st_size]
        except OSError:
            env9 = None
        _SIG0.update(code=_code_sig(), cfg=cfg9, env=env9)
    out = dict(_SIG0)
    c9 = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        out["led"] = [list(r) for r in c9.execute("SELECT k, v FROM meta WHERE k IN ('schema_version', 'ext_rebuilt_at') ORDER BY k")]
    finally:
        c9.close()
    return out


def _snapfile_save(snap, force=False, still_ok=None):
    now = time.time()
    with _SNAPFILE["lock"]:
        if not force and (_SNAPFILE["ver"] == snap.ver or now - _SNAPFILE["at"] < SNAPFILE_EVERY):
            return False
        _SNAPFILE["at"], _SNAPFILE["ver"] = now, snap.ver
    try:
        parts = snap.parts_gz or {}
        blobs = [snap.gz, snap.slim_gz or b""] + [parts[n] for n in websnap.PARTS if n in parts]
        head = {"ver": snap.ver, "at": snap.at, "built_at": snap.built_at, "hero": snap.hero, "sig": _snapfile_sig(),
                "slim": snap.slim_gz is not None, "parts": [n for n in websnap.PARTS if n in parts], "lens": [len(b) for b in blobs],
                "h": hashlib.sha1(b"".join(blobs)).hexdigest()}
        hj = json.dumps(head, ensure_ascii=False).encode()
        with fsio.atomic_open(paths.state("web_snap_last.bin"), binary=True, dir_fsync=False, makedirs=False) as f9:
            f9.write(_SNAPFILE_MAGIC + str(len(hj)).encode() + b"\n" + hj)
            for b9 in blobs:
                f9.write(b9)
        if still_ok is not None and not still_ok():
            _snapfile_drop()
            return False
        return True
    except Exception as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_snapfile:_snapfile_save", e)
        log.warning("스냅샷 저장본 쓰기 실패(무시): %s", type(e).__name__)
        with _SNAPFILE["lock"]:
            _SNAPFILE["ver"] = None
        return False


def _snapfile_drop():
    try:
        os.unlink(paths.state("web_snap_last.bin"))
    except OSError:
        pass
    with _SNAPFILE["lock"]:
        _SNAPFILE["at"], _SNAPFILE["ver"] = 0.0, None


def _aged_last_scan(raw: bytes, elapsed: float):
    if raw.count(_LASTSCAN_KEY) != 1:
        return None
    i = raw.index(_LASTSCAN_KEY) + len(_LASTSCAN_KEY)
    if raw[i:i + 1] != b'"':
        return None
    end = raw.find(b'"', i + 1, i + 202)
    if end < 0 or b"\\" in raw[i + 1:end]:
        return None
    m9 = _LASTSCAN_RX.fullmatch(raw[i + 1:end].decode("utf-8", "replace"))
    if not m9:
        return raw
    ago = int(m9.group(1)) * (1 if m9.group(2) == "초" else 60) + int(max(0.0, elapsed))
    new = f"{ago}초 전 스캔" if ago < 90 else f"{ago // 60}분 전 스캔"
    return raw[:i] + json.dumps(new, ensure_ascii=False).encode() + raw[end + 1:]


def _snapfile_load(gen: int, stale_max: float):
    if not os.path.exists(paths.state("web_snap_last.bin")):
        return None
    why = ""
    try:
        with open(paths.state("web_snap_last.bin"), "rb") as f9:
            data = f9.read()
        if not data.startswith(_SNAPFILE_MAGIC):
            raise ValueError("magic")
        rest = data[len(_SNAPFILE_MAGIC):]
        n9, _, rest = rest.partition(b"\n")
        head = json.loads(rest[:int(n9)])
        body = rest[int(n9):]
        lens = [int(x) for x in head["lens"]]
        if sum(lens) != len(body) or hashlib.sha1(body).hexdigest() != head.get("h"):
            raise ValueError("length/hash")
        blobs, o9 = [], 0
        for L9 in lens:
            blobs.append(body[o9:o9 + L9])
            o9 += L9
        at = float(head["at"])
        hero = head.get("hero") if isinstance(head.get("hero"), dict) else None
        age9 = time.time() - at
        if age9 > min(stale_max, SNAPFILE_MAX_AGE) or age9 < -60:
            why = "너무 오래됨(%d분)" % int(age9 // 60) if age9 > 0 else "시각이 미래"
        elif not hero or hero.get("todayKey") != datetime.now(KST).strftime("%m-%d"):
            why = "날짜 바뀜"
        else:
            sig0, sig1 = head.get("sig") or {}, _snapfile_sig()
            if sig0 != sig1:
                why = "바뀜: " + ",".join(k for k in ("code", "cfg", "env", "led") if sig0.get(k) != sig1.get(k))
        if why:
            log.info("스냅샷 저장본 안 씀(%s) — 첫 빌드를 기다림", why)
            return None
        raw = gzip.decompress(blobs[0])
        if hashlib.sha1(raw).hexdigest()[:16] != head["ver"]:
            raise ValueError("ver")
        names = head.get("parts") or []
        slim_ok = head.get("slim") and len(names) == len(websnap.PARTS) and len(blobs) == 2 + len(names)
        el9 = max(0.0, age9)
        raw2 = _aged_last_scan(raw, el9)
        slim2 = _aged_last_scan(gzip.decompress(blobs[1]), el9) if slim_ok else None
        if raw2 is None or (slim_ok and slim2 is None):
            log.info("스냅샷 저장본 안 씀(수집 시각 칸 없음) — 첫 빌드를 기다림")
            return None
        snap = websnap.Snap.__new__(websnap.Snap)
        snap.raw, snap.at, snap.gen = raw2, at, gen
        snap.gz = blobs[0] if raw2 == raw else websnap.gz(raw2)
        snap.ver = head["ver"] if raw2 == raw else hashlib.sha1(raw2).hexdigest()[:16]
        snap.built_at, snap.hero = head.get("built_at"), hero
        if slim_ok:
            snap.slim_gz = blobs[1] if slim2 == gzip.decompress(blobs[1]) else websnap.gz(slim2)
            snap.parts_gz = dict(zip(names, blobs[2:]))
        else:
            snap.slim_gz = snap.parts_gz = None
        return snap
    except Exception as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_snapfile:_snapfile_load", e, expected=True)
        log.warning("스냅샷 저장본 읽기 실패(지움): %s", type(e).__name__)
        _snapfile_drop()
        return None
