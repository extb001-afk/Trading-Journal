from __future__ import annotations
import collections
import json
import os
import re
import shutil
import subprocess
import time
from chk_base import BENIGN_DEFAULT
from chk_base import BUCKET
from chk_base import CHAIN_NAME
from chk_base import DEBT_RX
from chk_base import LINE_RX
from chk_base import NET_RX
from chk_base import PM2_TS_RX
from chk_base import QUIET_EXC
from chk_base import TRANSIENT_RX
from chk_base import _now
from chk_base import _sig

class LogWatch:

    KEEP_SEC = 3 * 3600
    FIRST_TAIL = 512 * 1024
    MAX_READ = 4 * 1024 * 1024

    def __init__(self, benign_extra=None, disabled_chains=None):
        pats = list(BENIGN_DEFAULT) + list(benign_extra or [])
        for c in disabled_chains or []:
            pats.append(r"\b" + re.escape(c) + r"\b")
        self.benign = re.compile("|".join(f"(?:{p})" for p in pats), re.I)
        self.files = {}
        self.units = {}

    def _u(self, unit):
        u = self.units.get(unit)
        if u is None:
            u = self.units[unit] = {"last_ts": None, "ev": collections.deque(), "review": None}
        return u

    def classify(self, level: str, msg: str) -> str:
        if DEBT_RX.search(msg):
            return "debt"
        if level in ("ERROR", "CRITICAL"):
            if self.benign.search(msg):
                return "benign"
            if NET_RX.search(msg):
                return "net"
            if TRANSIENT_RX.search(msg):
                return "transient"
            return "error"
        if level == "WARNING":
            if NET_RX.search(msg):
                return "net"
            return "warn"
        return "info"

    def feed(self, unit: str, line: str, ts_hint: float = None, fstate: dict = None):
        u = self._u(unit)
        fs = fstate if fstate is not None else {}
        line = PM2_TS_RX.sub("", line.rstrip("\n"), count=1)
        m = LINE_RX.match(line)
        if m:
            self._flush_tb(unit, fs)
            try:
                ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                ts = ts_hint or _now()
            fs["last_ts"] = ts
            level, msg = m.group(2), m.group(3)
            u["last_ts"] = max(u["last_ts"] or 0, ts)
            cls = self.classify(level, msg)
            if cls == "debt":
                m9 = DEBT_RX.search(msg)
                try:
                    u.setdefault("debt", {})[(m9.group(1), m9.group(2), m9.group(3))] = (ts, float(m9.group(4)))
                except (ValueError, AttributeError):
                    pass
            elif cls != "info":
                u["ev"].append((ts, cls, _sig(msg), msg[:300]))
            if unit == "tj-review":
                self._review(u, ts, msg)
            return
        if fs.get("incremental"):
            ts = ts_hint or _now()
        elif fs.get("hint_mtime"):
            ts = fs.get("last_ts")
        else:
            ts = fs.get("last_ts") or ts_hint or _now()
        if line.startswith("Traceback (most recent call last)"):
            self._flush_tb(unit, fs)
            fs["tb"] = {"ts": ts, "lines": []}
            return
        tb = fs.get("tb")
        if tb is not None:
            if line.startswith(" ") or not line.strip():
                tb["lines"].append(line)
                return
            fs["tb"] = None
            exc = line.strip()
            if tb["ts"] is not None and not exc.startswith(QUIET_EXC):
                u["ev"].append((tb["ts"], "crash", _sig(exc), exc[:300]))

    def _flush_tb(self, unit, fs):
        if fs.get("tb") is not None:
            fs["tb"] = None

    @staticmethod
    def _review(u, ts, msg):
        if "리뷰 생성 완료" in msg:
            u["review"] = (ts, "ok", msg)
        elif "claude CLI 없음" in msg:
            u["review"] = (ts, "off", msg)
        elif "리뷰" in msg and ("실패" in msg or "파싱" in msg):
            u["review"] = (ts, "fail", msg)

    def prune(self, now: float):
        cut = now - self.KEEP_SEC
        for u in self.units.values():
            ev = u["ev"]
            while ev and ev[0][0] < cut:
                ev.popleft()
            while len(ev) > 20000:
                ev.popleft()

    def poll(self, unit_files: dict, now: float):
        for unit, paths in unit_files.items():
            for p in paths:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                fs = self.files.get(p)
                hint = now if fs is not None else st.st_mtime
                seen = fs is not None
                if fs is not None:
                    fs["incremental"] = True
                if fs is None or fs.get("ino") != st.st_ino or st.st_size < fs.get("off", 0):
                    start = max(0, st.st_size - self.FIRST_TAIL) if fs is None else 0
                    fs = self.files[p] = {"ino": st.st_ino, "off": start, "unit": unit, "tb": None,
                                          "last_ts": None, "skip_partial": start > 0, "incremental": seen,
                                          "hint_mtime": not seen}
                if st.st_size <= fs["off"]:
                    continue
                if st.st_size - fs["off"] > self.MAX_READ:
                    fs["off"] = st.st_size - self.MAX_READ
                    fs["skip_partial"] = True
                try:
                    with open(p, "rb") as f:
                        f.seek(fs["off"])
                        data = f.read(st.st_size - fs["off"])
                except OSError:
                    continue
                cut = data.rfind(b"\n")
                if cut < 0:
                    continue
                chunk = data[:cut + 1]
                fs["off"] += cut + 1
                text = chunk.decode("utf-8", "replace")
                lines = text.split("\n")
                if fs.pop("skip_partial", False) and lines:
                    lines = lines[1:]
                for ln in lines:
                    if ln:
                        self.feed(unit, ln, ts_hint=hint, fstate=fs)
        self.prune(now)

    def summary(self, unit: str, now: float, t: dict) -> dict:
        u = self.units.get(unit) or {"last_ts": None, "ev": (), "review": None}
        w60 = now - 3600
        err_b, net_b = set(), set()
        n_err = n_warn = n_tr = n_net = n_crash = 0
        top = collections.Counter()
        sample = {}
        last_crash = None
        for ts, cls, sig, msg in u["ev"]:
            if ts < w60 or ts > now + 5:
                continue
            b = int(ts // BUCKET)
            if cls in ("error", "crash"):
                err_b.add(b)
                n_err += 1
                top[sig] += 1
                sample[sig] = msg
                if cls == "crash":
                    n_crash += 1
                    last_crash = (ts, msg)
            elif cls == "net":
                net_b.add(b)
                n_net += 1
            elif cls == "transient":
                n_tr += 1
            elif cls == "warn":
                n_warn += 1
        return {"last_ts": u["last_ts"], "err_buckets": sorted(err_b), "net_buckets": sorted(net_b),
                "n_err": n_err, "n_warn": n_warn, "n_transient": n_tr, "n_net": n_net, "n_crash": n_crash,
                "top": [(s, c, sample[s]) for s, c in top.most_common(3)], "last_crash": last_crash,
                "review": u.get("review")}


def _pm2_bin(h: dict):
    cands = [h.get("pm2_bin"), shutil.which("pm2"), "/opt/homebrew/bin/pm2", "/usr/local/bin/pm2",
             os.path.expanduser("~/.npm-global/bin/pm2"), os.path.expanduser("~/.local/bin/pm2")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def pm2_list(h: dict):
    b = _pm2_bin(h)
    if not b:
        return None
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(b) + os.pathsep + env.get("PATH", "")
    try:
        out = subprocess.run([b, "jlist"], capture_output=True, text=True, timeout=25, env=env)
        i = out.stdout.find("[")
        data = json.loads(out.stdout[i:]) if i >= 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    res = {}
    for p in data:
        e = p.get("pm2_env") or {}
        name = p.get("name") or e.get("name")
        if not name:
            continue
        res[name] = {"status": e.get("status"), "restarts": int(e.get("restart_time") or 0),
                     "pid": p.get("pid"), "uptime": (e.get("pm_uptime") or 0) / 1000.0,
                     "out": e.get("pm_out_log_path"), "err": e.get("pm_err_log_path"),
                     "mem": (p.get("monit") or {}).get("memory")}
    return res


def _mem_ts(st: dict, key: str, cur):
    mem = st.setdefault("mem", {})
    rec = mem.setdefault(key, {"last": None, "first": None})
    if cur:
        rec["last"] = max(float(cur), float(rec["last"] or 0))
    return rec


def _cname(c) -> str:
    if c in CHAIN_NAME:
        return CHAIN_NAME[c]
    try:
        import chainsweep as _cs9
        ent = _cs9.SWEEP_CHAINS.get(c)
        if ent:
            return ent[0]
    except Exception:
        pass
    return str(c)[:1].upper() + str(c)[1:]


def rss_track(st: dict, pm2, now: float, win: float) -> dict:
    rh = st.setdefault("rss_hist", {})
    out = {}
    for u, p in (pm2 or {}).items():
        mem = (p or {}).get("mem")
        if not mem:
            continue
        ent = rh.get(u) if isinstance(rh.get(u), dict) else None
        if ent is None or ent.get("pid") != (p or {}).get("pid"):
            ent = rh[u] = {"pid": (p or {}).get("pid"), "s": []}
        ent["s"] = [x for x in ent["s"] if isinstance(x, list) and len(x) == 2 and now - float(x[0]) <= win][-240:]
        ent["s"].append([round(now, 1), round(float(mem) / 1e6, 1)])
        out[u] = {"min": min(x[1] for x in ent["s"]), "span": now - float(ent["s"][0][0]), "n": len(ent["s"])}
    for u in [u for u in rh if u not in (pm2 or {})]:
        rh.pop(u, None)
    return out
