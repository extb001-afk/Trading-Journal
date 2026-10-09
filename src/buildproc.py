from __future__ import annotations

import gc
import io
import zlib
import logging
import mmap
import os
import pickle
import platform
import select
import signal
import struct
import sys
import threading
import time
import traceback

log = logging.getLogger("tj")

TIMEOUT_S = 900
STALL_S = 180
DEADLOCK_S = 3.0
DEADLOCK_UNK_S = 20.0
FORK_TRIES = 3
FAIL_MAX = 3
FAIL_PAUSE_S = 3600
MEM_MIN_MB = 1200
CHUNK = 1 << 20

PARENT_ONLY = frozenset((
    "_cache", "cache", "cache_at", "_inval", "_mp_n", "_mp_kinds", "_last_out", "_last_out_at", "_last_out_gen",
    "_built_sig", "_build_err", "_soft_dirty", "_refreshing", "_last_client", "_ph_gen0", "_ph_cur", "_ph_t",
    "_build_hist", "_build_warm", "_build_cold_ms", "_ph_hist", "_ph_last", "build_ms", "_pub_lock", "_bp_shm",
    "spot", "px", "_pxq", "snaps", "cfg", "_snapfile_on", "_bp_threads",
    "_build_ex", "_rb_gen",
))
CHILD_ONLY = frozenset(("_lpx_cache", "_wd_cls_fn"))
INPLACE = ("daily", "daily_px", "_flow_nf", "_px_bf_seen", "_of_deps_origin", "_offc_addrs", "_proof_div_seen",
           "_cex_proof_cache", "_perp_on_last")
REBOUND = frozenset(("_day_idx",))
QUEUES = {"_xc_pending": ("_xc_lock", "key"), "_flow_pending": ("_flow_lock", "dest")}
SETQ = {"_origin_pending": "_origin_lock"}
OBJ_SKIP = {"_rtx": frozenset(("bg", "_from_lock", "_from_thread", "path", "db_path"))}
SPOT_REPLACE = ("_tp_slots", "token_pairs", "token_prio", "token_skip", "token_slow", "meta_want", "okx_pairs", "proof_div")
SPOT_UNION = ("syms", "ex_want")
SPOT_KEYED = ("guarded", "_guard_seen", "_guard_logged")

MODSET = (("web", "_PERP_BAD_WARNED"), ("__main__", "_PERP_BAD_WARNED"))
MODDICT = (("web", "_GSYM_MEMO", 200000), ("__main__", "_GSYM_MEMO", 200000),
           ("spamguard", "_IMP_MEMO", 100000), ("spamguard", "_CS_MEMO", 200000))
HASH_MAX_N = 20000

_LOCK_T = type(threading.Lock())
_RLOCK_T = type(threading.RLock())

_ST = {"fails": 0, "pause_until": 0.0, "n_fork": 0, "n_inproc": 0, "last": None, "last_err": None, "skipped": {},
       "why_in": None, "inproc_last": None, "pause_why": None}


def plan() -> dict:
    import common
    return common.cpu_plan()


def status() -> dict:
    p = plan()
    return {"on": bool(p.get("on")), "core": p.get("core"), "cores": p.get("cores"), "why": p.get("why"),
            "fork": _ST["n_fork"], "inproc": _ST["n_inproc"], "fails": _ST["fails"],
            "paused": max(0, int(_ST["pause_until"] - time.time())), "last": _ST["last"], "last_err": _ST["last_err"],
            "inproc_last": dict(_ST["inproc_last"]) if isinstance(_ST.get("inproc_last"), dict) else None,
            "fail_max": FAIL_MAX, "pause_min": FAIL_PAUSE_S // 60,
            "mb": round(float(_ST.get("bytes") or 0) / 1e6, 1), "child_mb": _ST.get("child_mb"), "child_s": _ST.get("child_s"),
            "recv_s": _ST.get("recv_s"),
            "skipped": dict(_ST["skipped"])}


def usable() -> bool:
    p = plan()
    if not p.get("on"):
        _ST["why_in"] = None
        return False
    left = _ST["pause_until"] - time.time()
    if left > 0:
        _ST["why_in"] = f"연속 실패 {FAIL_MAX}번 뒤 쉼(약 {max(1, int(left // 60))}분 남음) — 직전 실패: {_ST.get('pause_why') or '?'}"
        return False
    av = _mem_avail_mb()
    if av is not None and av < MEM_MIN_MB:
        _ST["last"] = f"램 여유 {av}MB < {MEM_MIN_MB}MB — 이번은 웹 안에서"
        _ST["why_in"] = f"램 여유 {av}MB < {MEM_MIN_MB}MB"
        return False
    return True


def _mem_avail_mb():
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _priv_mb():
    try:
        n9 = 0
        with open("/proc/self/smaps_rollup", "r", encoding="ascii") as f:
            for ln in f:
                if ln.startswith(("Private_Clean:", "Private_Dirty:")):
                    n9 += int(ln.split()[1])
        return n9 // 1024
    except (OSError, ValueError, IndexError):
        return None


def _proc_cpu(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            s = f.read().decode("ascii", "replace")
        rest = s[s.rindex(")") + 2:].split()
        return int(rest[11]) + int(rest[12])
    except (OSError, ValueError, IndexError):
        return None


def _proc_read_bytes(pid):
    try:
        with open(f"/proc/{pid}/io", "r", encoding="ascii") as f:
            for ln in f:
                if ln.startswith("read_bytes:"):
                    return int(ln.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


_FUTEX_NR = {"x86_64": 202, "amd64": 202, "aarch64": 98, "arm64": 98, "riscv64": 98}.get(platform.machine().lower())
_FUTEX_WAIT_OPS = frozenset((0, 6, 9, 11, 13))


def lock_obs(status_txt, wchan_txt, syscall_txt, futex_nr=None) -> dict:
    th = stt = None
    csw = None
    for ln in (status_txt or "").splitlines():
        try:
            if ln.startswith("State:"):
                stt = ln.split()[1]
            elif ln.startswith("Threads:"):
                th = int(ln.split()[1])
            elif ln.startswith(("voluntary_ctxt_switches:", "nonvoluntary_ctxt_switches:")):
                csw = (csw or 0) + int(ln.split()[1])
        except (ValueError, IndexError):
            continue
    cand = th == 1 and stt == "S" and str(wchan_txt or "").strip().startswith("futex")
    untimed = None
    nr9 = _FUTEX_NR if futex_nr is None else futex_nr
    parts = str(syscall_txt or "").split()
    if cand and nr9 is not None and len(parts) >= 5:
        try:
            if int(parts[0]) == nr9 and (int(parts[2], 16) & 0x7F) in _FUTEX_WAIT_OPS:
                untimed = int(parts[4], 16) == 0
        except ValueError:
            untimed = None
    return {"cand": bool(cand), "untimed": untimed, "csw": csw}


def lock_step(prev, obs, now):
    if not isinstance(obs, dict) or not obs.get("cand") or obs.get("untimed") is False:
        return None, False
    csw = obs.get("csw")
    if prev is None or csw != prev[1]:
        prev = (now, csw)
    lim = DEADLOCK_S if obs.get("untimed") else DEADLOCK_UNK_S
    return prev, now - prev[0] >= lim


def _read_txt(path):
    try:
        with open(path, "r", encoding="ascii", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _proc_lockwait(pid):
    st9 = _read_txt(f"/proc/{pid}/status")
    wc9 = _read_txt(f"/proc/{pid}/wchan")
    if st9 is None or wc9 is None:
        return None
    obs = lock_obs(st9, wc9, None)
    if obs["cand"]:
        obs = lock_obs(st9, wc9, _read_txt(f"/proc/{pid}/syscall"))
    return obs


def note_inproc():
    _ST["n_inproc"] += 1
    if plan().get("on"):
        _ST["inproc_last"] = {"at": int(time.time()), "why": str(_ST.get("why_in") or _ST.get("last_err") or "?")[:200]}
    _ST["why_in"] = None


class nogc:

    def __enter__(self):
        self.on = gc.isenabled()
        gc.disable()
        return self

    def __exit__(self, *_a):
        if self.on:
            gc.enable()
        return False


def _none():
    return None


class _Pickler(pickle.Pickler):

    def reducer_override(self, obj):
        t = type(obj)
        if t is _LOCK_T:
            return (threading.Lock, ())
        if t is _RLOCK_T:
            return (threading.RLock, ())
        if isinstance(obj, (threading.Thread, threading.Event, threading.Condition)):
            return (_none, ())
        if t.__module__ == "sqlite3":
            return (_none, ())
        return NotImplemented


def _dumps(obj) -> bytes:
    bio = io.BytesIO()
    _Pickler(bio, protocol=pickle.HIGHEST_PROTOCOL).dump(obj)
    return bio.getvalue()


def _picklable(v) -> bool:
    try:
        _dumps(v)
        return True
    except Exception:
        return False


def _src_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _proj_obj(v) -> bool:
    m = sys.modules.get(type(v).__module__)
    f = getattr(m, "__file__", None) if m is not None else None
    return bool(f) and os.path.dirname(os.path.abspath(f)) == _src_dir() and hasattr(v, "__dict__") and not isinstance(v, type)


def _fresh_locks(o):
    d = getattr(o, "__dict__", None)
    if not isinstance(d, dict):
        return
    for k, v in list(d.items()):
        t = type(v)
        if t is _LOCK_T:
            d[k] = threading.Lock()
        elif t is _RLOCK_T:
            d[k] = threading.RLock()


def _child_reinit(b):
    _fresh_locks(b)
    for v in list(b.__dict__.values()):
        if _proj_obj(v):
            _fresh_locks(v)
            for v2 in list(v.__dict__.values()):
                if _proj_obj(v2):
                    _fresh_locks(v2)
    src = _src_dir()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f or os.path.dirname(os.path.abspath(f)) != src:
            continue
        g = vars(m)
        for k, v in list(g.items()):
            t = type(v)
            if t is _LOCK_T:
                g[k] = threading.Lock()
            elif t is _RLOCK_T:
                g[k] = threading.RLock()
            elif _proj_obj(v):
                _fresh_locks(v)


def _ln(v):
    try:
        return len(v) if isinstance(v, (dict, list, set, frozenset, tuple)) else None
    except Exception:
        return None


def _snap_obj(o, skip=frozenset()):
    d = {k: v for k, v in o.__dict__.items() if k not in skip}
    return d, {k: _ln(v) for k, v in d.items()}


def _small(v):
    n9 = _ln(v)
    return n9 is not None and n9 < HASH_MAX_N


def _fp(v):
    try:
        b9 = pickle.dumps(v, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        return None
    return (len(b9), zlib.crc32(b9))


def _diff_obj(o, before, lens, skip=frozenset()):
    ch, now = {}, o.__dict__
    for k, v in now.items():
        if k in skip:
            continue
        if k not in before or before[k] is not v or _ln(v) != lens.get(k):
            ch[k] = v
    gone = [k for k in before if k not in now and k not in skip]
    return ch, gone


def _keyed_diff(before: dict, after: dict):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    st = {k: v for k, v in after.items() if k not in before or before[k] is not v and before[k] != v}
    return st, [k for k in before if k not in after]


def _warn_new_sqlite():
    import sqlite3
    real, seen = sqlite3.connect, set()

    def connect(*a, **k):
        try:
            f9 = sys._getframe(1)
            while f9.f_back is not None and os.path.basename(f9.f_code.co_filename) == "db.py":
                f9 = f9.f_back
            site = f"{os.path.basename(f9.f_code.co_filename)}:{f9.f_lineno}"
            if site not in seen:
                seen.add(site)
                log.warning("빌드 자식: 새 SQLite 연결(%s) — 빌드 연결을 넘겨 쓰게 고칠 자리", site)
        except Exception:
            pass
        return real(*a, **k)
    sqlite3.connect = connect


def _close_inherited(keep):
    import stat
    n9 = 0
    try:
        fds = [int(x) for x in os.listdir("/proc/self/fd")]
    except (OSError, ValueError):
        return None
    try:
        nul = os.open(os.devnull, os.O_RDWR)
    except OSError:
        nul = None
    for fd in fds:
        if fd in keep or fd == nul:
            continue
        try:
            m9 = os.fstat(fd).st_mode
        except OSError:
            continue
        if stat.S_ISSOCK(m9) or stat.S_ISFIFO(m9):
            try:
                if nul is not None:
                    os.dup2(nul, fd)
                else:
                    os.close(fd)
                n9 += 1
            except OSError:
                pass
    if nul is not None:
        try:
            os.close(nul)
        except OSError:
            pass
    return n9


def _hist_begin():
    hc = sys.modules.get("histcurve")
    if hc is None or not hasattr(hc, "HIST") or not hasattr(hc, "DAYCLOSE"):
        return None
    import common
    H, DC = hc.HIST, hc.DAYCLOSE
    notes = []
    real_note = DC.note_change

    def note(spec, days, ts=None, invalidate=False):
        ts9 = time.time() if ts is None else ts
        n9 = real_note(spec, days, ts=ts9, invalidate=invalidate)
        if n9:
            notes.append((spec, sorted(d for d in (days or ()) if d), ts9, bool(invalidate)))
        return n9
    DC.note_change = note
    dcp = os.path.abspath(str(getattr(DC, "path", "") or ""))
    real_w = common.atomic_write_json

    def write(path, obj, *a, **k):
        if dcp and os.path.abspath(str(path)) == dcp:
            return None
        return real_w(path, obj, *a, **k)
    common.atomic_write_json = write
    want0 = {sp: (set((v or {}).get("days") or ()), float((v or {}).get("w") or 0)) for sp, v in dict(DC.want).items()}
    wold0 = {sp: (set((v or {}).get("days") or ()), float((v or {}).get("w") or 0)) for sp, v in dict(getattr(DC, "want_old", None) or {}).items()}
    return {"H": H, "DC": DC, "kit0": H.kit, "lo0": H.last_offer, "want0": want0, "wold0": wold0, "notes": notes}


def _hist_end(hs):
    if hs is None:
        return None
    H, DC = hs["H"], hs["DC"]
    add = {}
    for sp, v in dict(DC.want).items():
        d0, w0 = hs["want0"].get(sp, (set(), 0.0))
        dn = set((v or {}).get("days") or ()) - d0
        w9 = float((v or {}).get("w") or 0)
        if dn or w9 > w0:
            add[sp] = (dn, w9, (v or {}).get("t0"))
    add_old = {}
    for sp, v in dict(getattr(DC, "want_old", None) or {}).items():
        d0, w0 = hs.get("wold0", {}).get(sp, (set(), 0.0))
        dn = set((v or {}).get("days") or ()) - d0
        w9 = float((v or {}).get("w") or 0)
        if dn or w9 > w0:
            add_old[sp] = (dn, (v or {}).get("t0"), w9)
    kit_set = H.kit is not hs["kit0"]
    return {"kit": H.kit if kit_set else None, "kit_set": kit_set, "offered": H.last_offer != hs["lo0"], "last_offer": H.last_offer,
            "want_add": add, "want_old_add": add_old, "notes": list(hs["notes"])}


def _modset_begin():
    out = {}
    for mn, nm in MODSET:
        m = sys.modules.get(mn)
        v = getattr(m, nm, None) if m is not None else None
        if isinstance(v, set):
            out[(mn, nm)] = set(v)
    return out


def _modset_end(before):
    out = {}
    for (mn, nm), b9 in before.items():
        v = getattr(sys.modules.get(mn), nm, None)
        if isinstance(v, set) and v - b9:
            out[f"{mn}.{nm}"] = v - b9
    return out


def _moddict_begin():
    out = {}
    for mn, nm, _cap in MODDICT:
        v = getattr(sys.modules.get(mn), nm, None) if sys.modules.get(mn) is not None else None
        if isinstance(v, dict) and (mn, nm) not in out:
            out[(mn, nm)] = (v, len(v))
    return out


def _moddict_end(before):
    out = {}
    for (mn, nm), (v0, n0) in before.items():
        v = getattr(sys.modules.get(mn), nm, None)
        if v is not v0 or not isinstance(v, dict) or len(v) <= n0:
            continue
        try:
            import itertools
            out[f"{mn}.{nm}"] = dict(itertools.islice(v.items(), n0, None))
        except (RuntimeError, TypeError):
            continue
    return out


def _child_run(b, conn, shm, wfd):
    code = 0
    t_c0 = time.time()
    try:
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
        core = plan().get("core")
        if core is not None and hasattr(os, "sched_setaffinity"):
            try:
                os.sched_setaffinity(0, {core})
            except OSError:
                pass
        try:
            with open("/proc/self/oom_score_adj", "w", encoding="ascii") as f:
                f.write("1000")
        except OSError:
            pass
        if hasattr(gc, "freeze"):
            gc.freeze()
        gc.disable()
        socks9 = _close_inherited({0, 1, 2, wfd})
        _child_reinit(b)
        _warn_new_sqlite()
        b.__dict__["_bp_shm"] = shm
        px = b.px
        px._save = lambda: None
        rtx = b.__dict__.get("_rtx")
        if rtx is not None and hasattr(rtx, "bg"):
            rtx.bg = False
        before = dict(b.__dict__)
        lens = {k: _ln(v) for k, v in before.items()}
        objs, dirty0 = {}, {}
        for k, v in before.items():
            if k in PARENT_ONLY or k in CHILD_ONLY or not _proj_obj(v):
                continue
            if isinstance(v.__dict__.get("dirty"), bool):
                dirty0[k] = v.__dict__["dirty"]
                v.__dict__["dirty"] = False
            objs[k] = (v,) + _snap_obj(v, OBJ_SKIP.get(k, frozenset()))
        hs9 = _hist_begin()
        ms9 = _modset_begin()
        md9 = _moddict_begin()
        fp0 = {k: _fp(v) for k, v in before.items()
               if k not in PARENT_ONLY and k not in CHILD_ONLY and k not in objs and k not in INPLACE and k not in REBOUND and _small(v)}
        sp = b.spot
        sp_before = {k: (set(getattr(sp, k, ()) or ())) for k in SPOT_UNION}
        sp_keyed = {k: dict(getattr(sp, k, {}) or {}) for k in SPOT_KEYED}
        px_before = {k: (dict(v) if isinstance(v, dict) else v) for k, v in px.d.items()}
        q_before = set(b.__dict__.get("_origin_pending") or ())
        px.nb_begin()
        try:
            out = b._build(conn)
        finally:
            miss = px.nb_end()
        st, gone = {}, []
        for k, v in b.__dict__.items():
            if k in PARENT_ONLY or k in CHILD_ONLY or k in objs:
                continue
            if k in INPLACE or k in REBOUND or k not in before or before[k] is not v or _ln(v) != lens.get(k):
                st[k] = v
            elif k in fp0 and fp0[k] is not None and _fp(v) != fp0[k]:
                st[k] = v
        for k in before:
            if k not in b.__dict__ and k not in PARENT_ONLY and k not in CHILD_ONLY:
                gone.append(k)
        obj_ch = {}
        for k, (o, ob, ol) in objs.items():
            if b.__dict__.get(k) is not o:
                continue
            sk9 = OBJ_SKIP.get(k, frozenset())
            if k in dirty0 and o.__dict__.get("dirty"):
                obj_ch[k] = ({f9: v9 for f9, v9 in o.__dict__.items() if f9 not in sk9 and f9 != "dirty"}, [], True)
                continue
            if k in dirty0:
                o.__dict__["dirty"] = dirty0[k]
            ch, og = _diff_obj(o, ob, ol, sk9)
            if ch or og:
                obj_ch[k] = (ch, og, False)
        for k, (o, _ob, _ol) in objs.items():
            if b.__dict__.get(k) is not o and k in b.__dict__:
                st[k] = b.__dict__[k]
        orig_add = None
        if "_origin_pending" in b.__dict__:
            orig_add = set(b.__dict__["_origin_pending"] or ()) - q_before
            st.pop("_origin_pending", None)
        spot = {"replace": {k: getattr(sp, k) for k in SPOT_REPLACE if hasattr(sp, k)},
                "union": {k: set(getattr(sp, k, ()) or ()) - sp_before[k] for k in SPOT_UNION},
                "keyed": {k: _keyed_diff(sp_keyed[k], getattr(sp, k, {}) or {}) for k in SPOT_KEYED}}
        pxd = {}
        for k, v in px.d.items():
            b9 = px_before.get(k)
            if isinstance(v, dict) and isinstance(b9, dict):
                kd = _keyed_diff(b9, v)
                if kd and (kd[0] or kd[1]):
                    pxd[k] = ("keyed", kd)
            elif k not in px_before or b9 is not v:
                pxd[k] = ("set", v)
        pay = {"priv_mb": _priv_mb(), "child_s": time.time() - t_c0, "socks": socks9,
               "hist": _hist_end(hs9), "modset": _modset_end(ms9), "moddict": _moddict_end(md9),
               "st": st, "gone": gone, "obj": obj_ch, "orig_add": orig_add, "spot": spot, "pxd": pxd,
               "miss": miss, "ph": list(b.__dict__.get("_ph_cur") or []), "ph_t": b.__dict__.get("_ph_t"),
               "threads": threading.active_count()}
        try:
            data = _dumps(("ok", out, pay))
        except Exception:
            bad = [k for k, v in st.items() if not _picklable(v)]
            for k in bad:
                st.pop(k, None)
            for k, (ch, _og, _full) in list(obj_ch.items()):
                for f9 in [f9 for f9, v9 in ch.items() if not _picklable(v9)]:
                    ch.pop(f9, None)
                    bad.append(f"{k}.{f9}")
            hv9 = pay.get("hist") or {}
            if hv9.get("kit_set") and not _picklable(hv9.get("kit")):
                hv9["kit_set"], hv9["kit"] = False, None
                bad.append("histcurve.HIST.kit")
            pay["skipped"] = bad
            data = _dumps(("ok", out, pay))
    except BaseException as e:
        name = type(e).__name__
        if name == "_BuildObsolete":
            data = _dumps(("obsolete", str(e)))
        else:
            try:
                import common
                msg = common.safe_err(e)
            except Exception:
                msg = str(e)[:300]
            data = _dumps(("err", name, msg, traceback.format_exc()[-4000:]))
        code = 3
    try:
        mv = memoryview(data)
        while mv:
            n = os.write(wfd, mv[:CHUNK])
            mv = mv[n:]
    except OSError:
        code = 4
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


class ChildBuildError(RuntimeError):
    pass


def _prctl():
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes
        f9 = ctypes.CDLL(None, use_errno=True).prctl
        f9.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        f9.restype = ctypes.c_int
        return f9
    except Exception:
        return None


def shm_get(shm) -> int:
    return struct.unpack_from("q", shm, 0)[0]


_DEADLOCK = object()


def run(b):
    for i in range(FORK_TRIES):
        r = _run_once(b)
        if r is not _DEADLOCK:
            return r
        _ST["deadlocks"] = _ST.get("deadlocks", 0) + 1
        log.warning("빌드 자식이 fork 순간 물려받은 잠금에 걸림(스레드 하나 · 시간 제한 없는 futex 대기 %.0f초 — 대기 종류를 못 읽으면 %.0f초) — %s",
                    DEADLOCK_S, DEADLOCK_UNK_S,
                    "곧바로 다시 fork(%d/%d)" % (i + 2, FORK_TRIES) if i + 1 < FORK_TRIES else "이번 빌드는 웹 안에서")
    _fail(f"자식 잠금 멈춤 {FORK_TRIES}번 연속(fork 순간 다른 스레드가 쥔 잠금)")
    return None


def _run_once(b):
    import db as dbm
    import common
    t0 = time.time()
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    pid = None
    rfd = wfd = None
    shm = None
    try:
        conn.execute("BEGIN")
        conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchall()
        try:
            shm = mmap.mmap(-1, 8)
            struct.pack_into("q", shm, 0, int(b.__dict__.get("_inval", 0)))
            rfd, wfd = os.pipe()
        except (OSError, MemoryError, ValueError) as e:
            _fail(f"자식 준비 실패({type(e).__name__})")
            return None
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        ppid9, prctl9 = os.getpid(), _prctl()
        b.__dict__["_bp_threads"] = sorted(t9.name for t9 in threading.enumerate())
        try:
            pid = os.fork()
        except (OSError, MemoryError) as e:
            pid = None
            _fail(f"fork 실패({type(e).__name__})")
            return None
        if pid == 0:
            if prctl9 is not None:
                try:
                    prctl9(1, int(signal.SIGKILL), 0, 0, 0)
                except Exception:
                    pass
            if os.getppid() != ppid9:
                os._exit(4)
            os.close(rfd)
            _child_run(b, conn, shm, wfd)
        os.close(wfd)
        wfd = None
        buf = bytearray()
        last_cpu, last_prog, why = None, time.time(), None
        last_rb = None
        lock9 = None
        killed9 = False
        deadlock9 = False
        while True:
            try:
                struct.pack_into("q", shm, 0, int(b.__dict__.get("_inval", 0)))
            except (ValueError, TypeError):
                pass
            r, _w, _x = select.select([rfd], [], [], 0.25)
            now = time.time()
            if r:
                ch = os.read(rfd, CHUNK)
                if not ch:
                    break
                buf += ch
                last_prog = now
                continue
            c9 = _proc_cpu(pid)
            rb9 = _proc_read_bytes(pid)
            moved9 = False
            if c9 is None:
                last_prog = now
            elif c9 != last_cpu:
                last_cpu, last_prog, moved9 = c9, now, True
            if rb9 is not None and rb9 != last_rb:
                if last_rb is not None:
                    last_prog, moved9 = now, True
                last_rb = rb9
            if moved9:
                lock9, dl9 = None, False
            else:
                lock9, dl9 = lock_step(lock9, _proc_lockwait(pid), now)
            if dl9:
                why, deadlock9 = "교착", True
            elif now - last_prog > STALL_S:
                why = f"멈춤({STALL_S}초 진행 없음)"
            elif now - t0 > TIMEOUT_S:
                why = f"시간 초과({TIMEOUT_S}초)"
            if why:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed9 = True
                except OSError:
                    pass
                break
        try:
            _p, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = None
        pid = None
        if killed9:
            sweep_tmp(min_age=KILL_TMP_MIN_AGE, since=t0)
        if deadlock9:
            return _DEADLOCK
        if why is None and not buf:
            why = f"자식 종료({_status_text(status)}) — 결과 없음"
        res = None
        if why is None:
            try:
                with nogc():
                    res = pickle.loads(bytes(buf))
            except Exception as e:
                why = f"결과 읽기 실패({type(e).__name__})"
        _ST["bytes"] = len(buf)
        del buf
        if why is not None:
            _fail(why)
            return None
        if res[0] == "err":
            _ST["fails"] = 0
            _ST["last"] = f"자식 빌드 예외 {res[1]}"
            _raise_child_err(res)
        _ST["fails"] = 0
        _ST["n_fork"] += 1
        _ST["last"] = f"{'완료' if res[0] == 'ok' else '사용자 변경으로 그만둠'} {time.time() - t0:.1f}초"
        if res[0] == "ok":
            cs9 = float(res[2].get("child_s") or 0)
            _ST["child_mb"] = res[2].get("priv_mb")
            _ST["child_s"] = round(cs9, 1)
            _ST["recv_s"] = round(max(0.0, time.time() - t0 - cs9), 2)
        _ST["last_err"] = None
        if res[0] == "ok" and res[2].get("skipped"):
            for k in res[2]["skipped"]:
                if k not in _ST["skipped"]:
                    log.warning("빌드 자식: 돌려받지 못한 칸 %s(전송 불가 — 다음 빌드가 다시 계산)", k)
                _ST["skipped"][k] = _ST["skipped"].get(k, 0) + 1
        return res
    finally:
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        for fd in (rfd, wfd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if shm is not None:
            try:
                shm.close()
            except (BufferError, ValueError):
                pass
        conn.close()


def _raise_child_err(res):
    if res[1] == "SystemExit":
        raise SystemExit(res[2])
    tb9 = res[3] if len(res) > 3 and isinstance(res[3], str) else ""
    try:
        import common
        tb9 = common.redact_secret_text(tb9, generic=False)
    except Exception:
        tb9 = ""
    log.warning("빌드 예외(자식): %s: %s%s", res[1], res[2], ("\n자식 빌드 traceback(끝 4000자):\n" + tb9.rstrip()) if tb9 else "")
    raise ChildBuildError(f"{res[1]}: {res[2]}")


def _status_text(status) -> str:
    if status is None:
        return "상태 모름"
    try:
        code = os.waitstatus_to_exitcode(status)
    except (AttributeError, ValueError):
        return f"상태 {status}"
    if code < 0:
        try:
            nm = signal.Signals(-code).name
        except ValueError:
            nm = "?"
        return f"신호 {-code}({nm})"
    return f"종료 코드 {code}"


TMP_PREFIX = ".tmp_"
TMP_KEEP_S = 3600
KILL_TMP_MIN_AGE = 30


def sweep_tmp(min_age: float = TMP_KEEP_S, since: float = None, root: str = None, now: float = None) -> int:
    import common
    root = root or common.STATE_DIR
    now = time.time() if now is None else now
    n = 0
    try:
        tops = [root] + [e.path for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return 0
    for d in tops:
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            if not e.name.startswith(TMP_PREFIX):
                continue
            try:
                if not e.is_file(follow_symlinks=False):
                    continue
                mt = e.stat(follow_symlinks=False).st_mtime
                if now - mt < min_age or (since is not None and mt < since):
                    continue
                os.unlink(e.path)
                n += 1
            except OSError:
                continue
    if n:
        log.info("쓰다 만 임시 파일 %d개 정리(state/.tmp_*)", n)
    return n


def _fail(why):
    _ST["fails"] += 1
    _ST["last"] = f"실패: {why} — 이번 빌드는 웹 안에서"
    _ST["last_err"] = why
    _ST["why_in"] = why
    if _ST["fails"] >= FAIL_MAX:
        _ST["pause_until"] = time.time() + FAIL_PAUSE_S
        _ST["pause_why"] = why
        log.warning("빌드 자식 연속 실패 %d번(%s) — %d분 동안 웹 안에서 빌드", _ST["fails"], why, FAIL_PAUSE_S // 60)
        _ST["fails"] = 0
    else:
        log.warning("빌드 자식 실패(%s) — 이번 빌드는 웹 안에서", why)


def apply(b, pay, qsnap):
    st = pay.get("st") or {}
    for k, v in st.items():
        if k in PARENT_ONLY or k in CHILD_ONLY:
            continue
        if k in QUEUES:
            lk, key = QUEUES[k]
            lock = b.__dict__.get(lk)
            with (lock if lock is not None else _NullCtx()):
                done = qsnap.get(k, set()) - {c.get(key) for c in (b.__dict__.get(k) or []) if isinstance(c, dict)}
                b.__dict__[k] = [c for c in (v or []) if not (isinstance(c, dict) and c.get(key) in done)]
        else:
            b.__dict__[k] = v
    for k in pay.get("gone") or ():
        if k not in PARENT_ONLY:
            b.__dict__.pop(k, None)
    for k, v9 in (pay.get("obj") or {}).items():
        ch, og, full = v9[0], v9[1], bool(v9[2]) if len(v9) > 2 else False
        o = b.__dict__.get(k)
        if o is None:
            continue
        for f9, x9 in ch.items():
            o.__dict__[f9] = x9
        for f9 in og:
            o.__dict__.pop(f9, None)
        if full:
            o.__dict__["dirty"] = True
    _apply_hist(pay.get("hist"))
    for nm, add in (pay.get("modset") or {}).items():
        mn, _d, an = nm.partition(".")
        v = getattr(sys.modules.get(mn), an, None)
        if isinstance(v, set):
            v |= set(add)
    caps9 = {f"{mn}.{nm}": cap for mn, nm, cap in MODDICT}
    for nm, add in (pay.get("moddict") or {}).items():
        mn, _d, an = nm.partition(".")
        v = getattr(sys.modules.get(mn), an, None) if sys.modules.get(mn) is not None else None
        if not isinstance(v, dict) or not isinstance(add, dict) or nm not in caps9:
            continue
        room = caps9[nm] - len(v)
        for k, x in add.items():
            if room <= 0:
                break
            if k not in v:
                v[k] = x
                room -= 1
    add = pay.get("orig_add")
    if add:
        lk = b.__dict__.get(SETQ["_origin_pending"])
        with (lk if lk is not None else _NullCtx()):
            cur = b.__dict__.get("_origin_pending")
            done = qsnap.get("_origin_pending", set()) - set(cur or ())
            if cur is None:
                b.__dict__["_origin_pending"] = set(add) - done
            else:
                cur |= set(add) - done
    sp = b.spot
    s9 = pay.get("spot") or {}
    with sp.lock:
        for k, v in (s9.get("replace") or {}).items():
            setattr(sp, k, v)
        for k, v in (s9.get("union") or {}).items():
            if v:
                getattr(sp, k).update(v)
        for k, kd in (s9.get("keyed") or {}).items():
            if not kd:
                continue
            d9 = getattr(sp, k)
            d9.update(kd[0])
            for x in kd[1]:
                d9.pop(x, None)
    px = b.px
    pxd = pay.get("pxd") or {}
    if pxd:
        with px.lock:
            n9 = 0
            for k, (how, v) in pxd.items():
                if how == "set":
                    px.d[k] = v
                    n9 += 1
                else:
                    d9 = px.d.setdefault(k, {})
                    d9.update(v[0])
                    for x in v[1]:
                        d9.pop(x, None)
                    n9 += len(v[0]) + len(v[1])
            if n9:
                px._dirty += n9
    px.flush()
    if pay.get("miss"):
        b._pxq.add(pay["miss"])


def _apply_hist(hs):
    hc = sys.modules.get("histcurve")
    if not hs or hc is None:
        return
    H, DC = hc.HIST, hc.DAYCLOSE
    for spec, days, ts, inv in hs.get("notes") or ():
        try:
            DC.note_change(spec, days, ts=ts, invalidate=inv)
        except Exception as e:
            log.warning("그날 마감가 변경 기록 반영 실패(다음 빌드에 다시): %s", type(e).__name__)
    add = hs.get("want_add") or {}
    if add:
        with DC.lock:
            for sp, (dn, w9, t0) in add.items():
                r = DC.want.setdefault(sp, {"days": set(), "w": 0.0, "t0": t0 or time.time()})
                r["days"] |= set(dn)
                r["w"] = max(float(r.get("w") or 0), float(w9 or 0))
    add_old = hs.get("want_old_add") or {}
    if add_old and hasattr(DC, "want_old"):
        with DC.lock:
            for sp, (dn, t0, *w9) in add_old.items():
                r = DC.want_old.setdefault(sp, {"days": set(), "w": 0.0, "t0": t0 or time.time()})
                r["days"] |= set(dn)
                r["w"] = max(float(r.get("w") or 0), float(w9[0] if w9 else 0))
    if hs.get("kit_set"):
        with H.lock:
            H.kit = hs.get("kit")
    if hs.get("offered"):
        H.last_offer = hs.get("last_offer") or time.time()
        H.ev.set()
    try:
        DC.kick()
    except Exception:
        pass


def qsnap_of(b) -> dict:
    out = {}
    for k, (lk, key) in QUEUES.items():
        lock = b.__dict__.get(lk)
        with (lock if lock is not None else _NullCtx()):
            out[k] = {c.get(key) for c in (b.__dict__.get(k) or []) if isinstance(c, dict)}
    lk = b.__dict__.get(SETQ["_origin_pending"])
    with (lk if lk is not None else _NullCtx()):
        out["_origin_pending"] = set(b.__dict__.get("_origin_pending") or ())
    return out


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
