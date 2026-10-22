import json
import logging
import os

import paths
import statefile

__all__ = ["HIST_DIRTY", "HIST_DIRTY_KEEP", "mark_hist_dirty", "hist_dirty_update", "HIST_LATE_K", "HIST_LATE_PID_K", "HIST_LATE_KEEP",
           "HIST_LATE_JOIN_S", "HIST_LATE_TTL_S", "HIST_LATE_CLOSE_S", "HIST_LATE_EXCL_SQL", "hist_late_read", "hist_late_put", "hist_late_pw",
           "hist_late_after", "EXF_LATE_PFX", "exf_is_debt_int", "EXF_FUT_NS", "exf_is_fut"]


HIST_DIRTY = "hist_dirty.json"
HIST_DIRTY_KEEP = 200


def mark_hist_dirty(ts, state_dir: str = None) -> str:
    import fcntl
    import time as _time
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    sd = state_dir or paths.STATE_DIR
    iso = _dt.fromtimestamp(int(ts), _tz(_td(hours=9))).strftime("%Y-%m-%d")
    p = os.path.join(sd, HIST_DIRTY)
    os.makedirs(sd, exist_ok=True)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cur = statefile.read_json(p, None)
        except SystemExit:
            cur = None
            logging.getLogger("tj").warning("hist_dirty.json 손상 — 새로 씀")
        cur = cur if isinstance(cur, dict) else {}
        seq = int(cur.get("seq") or 0) + 1
        marks = [m for m in (cur.get("marks") or []) if isinstance(m, list) and len(m) >= 3] + [[seq, iso, int(_time.time())]]
        if len(marks) > HIST_DIRTY_KEEP:
            marks.sort(key=lambda m: int(m[0]))
            keep9, fold9 = marks[:HIST_DIRTY_KEEP - 1], marks[HIST_DIRTY_KEEP - 1:]
            marks = keep9 + [[seq, min(m[1] for m in fold9), int(_time.time())]]
        statefile.atomic_write_json(p, {"from": min(m[1] for m in marks), "seq": seq, "marks": marks})
    return iso


def hist_dirty_update(fn, state_dir: str = None):
    import fcntl
    sd = state_dir or paths.STATE_DIR
    p = os.path.join(sd, HIST_DIRTY)
    with open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cur = statefile.read_json(p, None)
        except SystemExit:
            cur = None
        new = fn(cur if isinstance(cur, dict) else None)
        if new is None:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        elif new is not cur:
            statefile.atomic_write_json(p, new)
        return new


HIST_LATE_K = "hist_late"
HIST_LATE_PID_K = "hist_late_pid"
HIST_LATE_KEEP = 32
HIST_LATE_JOIN_S = 120
HIST_LATE_TTL_S = 14 * 86400
HIST_LATE_CLOSE_S = 960
HIST_LATE_EXCL_SQL = ("NOT (p.source_kind='chain_tx' AND EXISTS (SELECT 1 FROM meta m WHERE m.k = 'ext_prewindow_tx:' || p.source_ns || ':' || p.source_id))")


def hist_late_read(conn) -> list:
    try:
        r = conn.execute("SELECT v FROM meta WHERE k=?", (HIST_LATE_K,)).fetchone()
    except Exception:   # noqa: BLE001 [fallback]
        return []
    try:
        d = json.loads(r[0]) if r and r[0] else None
    except (TypeError, ValueError):
        return []
    out = []
    for m in ((d or {}).get("m") or []) if isinstance(d, dict) else []:
        try:
            iso = str(m[1])
            if len(iso) != 10 or iso[4] != "-":
                continue
            out.append([int(m[0]), iso, int(m[2]), int(m[3])])
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out)


def hist_late_put(conn, ts, now: float = None) -> str:
    import time as _time
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    now = _time.time() if now is None else float(now)
    iso = _dt.fromtimestamp(int(ts), _tz(_td(hours=9))).strftime("%Y-%m-%d")
    ms = [m for m in hist_late_read(conn) if now - m[3] < HIST_LATE_TTL_S]
    nid = max((ms[-1][0] + 1) if ms else 0, int(now * 1000))
    if ms and now - ms[-1][2] < HIST_LATE_JOIN_S:
        last = ms[-1]
        ms[-1] = [nid, min(last[1], iso), last[2], int(now)]
    else:
        ms.append([nid, iso, int(now), int(now)])
    while len(ms) > HIST_LATE_KEEP:
        a, b = ms[0], ms[1]
        ms[:2] = [[b[0], min(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3])]]
    conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (HIST_LATE_K, json.dumps({"v": 1, "m": ms}, separators=(",", ":"))))
    return iso


def hist_late_pw(conn):
    try:
        r = conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()
        return int(r[0] or 0) if r else None
    except Exception:   # noqa: BLE001 [fallback]
        return None


def hist_late_after(conn, pw, t_end) -> bool:
    try:
        r = conn.execute("SELECT 1 FROM postings p WHERE p.posting_id > ? AND p.event_ts < ? AND " + HIST_LATE_EXCL_SQL + " LIMIT 1",
                         (int(pw), int(t_end))).fetchone()
    except Exception:   # noqa: BLE001 [fallback]
        return False
    return r is not None


EXF_LATE_PFX = "exflate:"


def exf_is_debt_int(event, leg_seq, source_ns, source_id) -> bool:
    try:
        seq9 = int(leg_seq or 0)
    except (TypeError, ValueError):
        return False
    return (event == "EXF_ADJUST" and seq9 == 2 and str(source_ns or "").endswith(":recon")
            and not str(source_id or "").startswith(EXF_LATE_PFX))


EXF_FUT_NS = "futpnl"


def exf_is_fut(event, source_ns) -> bool:
    return event == "EXF_ADJUST" and str(source_ns or "").endswith(":" + EXF_FUT_NS)
