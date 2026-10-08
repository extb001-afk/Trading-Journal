"""Dashboard state snapshot helpers."""
import gzip
import hashlib
import json
import threading
import time

GZ_LEVEL = 6
_KEYED = "key"
_KEY_NAMES = ("key", "address")


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode()


def gz(raw: bytes) -> bytes:
    return gzip.compress(raw, GZ_LEVEL, mtime=0)


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


class Snap:
    __slots__ = ("ver", "raw", "gz", "at", "gen", "built_at", "hero", "slim_gz", "parts_gz")

    def __init__(self, obj, gen=0, raw=None):
        self.raw = raw if raw is not None else dumps(obj)
        self.gz = gz(self.raw)
        self.ver = hashlib.sha1(self.raw).hexdigest()[:16]
        self.at = time.time()
        self.gen = gen
        self.built_at = (obj or {}).get("builtAt") if isinstance(obj, dict) else None
        self.hero = None
        self.slim_gz = None
        self.parts_gz = None


PARTS = ("ev", "oft")


def _ev_months(evs):
    best = {}
    for e in evs:
        t = e.get("t") if isinstance(e, dict) else None
        t = t if isinstance(t, str) else ""
        k = t[:2]
        if k not in best or t > best[k]:
            best[k] = t
    return sorted(best.values())


def split_slim(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("fields"), dict):
        return obj, {n: {} for n in PARTS}
    f = dict(obj["fields"])
    ev, oft = {}, {}
    pos = f.get("positions")
    if isinstance(pos, list):
        out = []
        for p in pos:
            if isinstance(p, dict) and "events" in p and isinstance(p.get("key"), (str, int)) and not isinstance(p.get("key"), bool):
                q = {k: v for k, v in p.items() if k != "events"}
                evs = p["events"]
                ev[str(p["key"])] = evs
                lst = evs if isinstance(evs, list) else []
                q["_evc"] = len(lst)
                q["_evt"] = _ev_months(lst)
                out.append(q)
            else:
                out.append(p)
        f["positions"] = out
    ofl = f.get("outflows")
    if isinstance(ofl, list):
        out = []
        for r in ofl:
            if not isinstance(r, dict) or not isinstance(r.get("address"), str):
                out.append(r)
                continue
            fl = r.get("flow")
            rc = fl.get("recips") if isinstance(fl, dict) else None
            has_rtx = isinstance(rc, list) and any(isinstance(x, dict) and "txs" in x for x in rc)
            if "txs" not in r and not has_rtx:
                out.append(r)
                continue
            q = {k: v for k, v in r.items() if k != "txs"}
            ent = [r["txs"] if "txs" in r else None, None]
            if "txs" in r:
                q["_txn"] = len(r["txs"]) if isinstance(r["txs"], list) else 0
            if has_rtx:
                ent[1] = [(x["txs"] if isinstance(x, dict) and "txs" in x else None) for x in rc]
                q["flow"] = dict(fl, recips=[(dict({k: v for k, v in x.items() if k != "txs"}, _rtn=len(x["txs"]) if isinstance(x["txs"], list) else 0)
                                              if isinstance(x, dict) and "txs" in x else x) for x in rc])
            oft[r["address"]] = ent
            out.append(q)
        f["outflows"] = out
    slim = dict(obj, fields=f)
    slim["slim"] = list(PARTS)
    return slim, {"ev": ev, "oft": oft}


def merge_slim(slim, parts):
    obj = json.loads(json.dumps(slim, ensure_ascii=False))
    obj.pop("slim", None)
    f = obj.get("fields") or {}
    ev, oft = (parts or {}).get("ev") or {}, (parts or {}).get("oft") or {}
    for p in f.get("positions") or []:
        if isinstance(p, dict) and "_evc" in p:
            p.pop("_evc", None)
            p.pop("_evt", None)
            p["events"] = ev.get(str(p.get("key")), [])
    for r in f.get("outflows") or []:
        if not isinstance(r, dict) or r.get("address") not in oft:
            continue
        t0, rtx = oft[r["address"]]
        r.pop("_txn", None)
        if t0 is not None:
            r["txs"] = t0
        if rtx is not None:
            for x, t in zip(r["flow"]["recips"], rtx):
                if isinstance(x, dict):
                    x.pop("_rtn", None)
                if t is not None and isinstance(x, dict):
                    x["txs"] = t
    return obj


def attach_slim(snap, obj):
    slim, parts = split_slim(obj)
    snap.slim_gz = gz(dumps(slim))
    snap.parts_gz = {n: gz(dumps(parts.get(n) or {})) for n in PARTS}
    return snap


def _keyed(lst, kn=_KEYED):
    keys = []
    seen = set()
    for e in lst:
        if not isinstance(e, dict):
            return None
        k = e.get(kn)
        if not isinstance(k, (str, int)) or isinstance(k, bool) or k in seen:
            return None
        seen.add(k)
        keys.append(k)
    return keys


def _diff_list(a, b):
    if not a:
        return None
    for kn in _KEY_NAMES:
        ka, kb = _keyed(a, kn), _keyed(b, kn)
        if ka is not None and kb is not None:
            break
    else:
        return None
    ma = dict(zip(ka, a))
    mb = dict(zip(kb, b))
    r = [k for k in ka if k not in mb]
    n = [e for e, k in zip(b, kb) if k not in ma]
    p = []
    for k in kb:
        if k in ma:
            sub = _diff_dict(ma[k], mb[k])
            if sub:
                p.append([k, sub])
    out = {"$L": 1, "k": kn}
    if n:
        out["n"] = n
    if p:
        out["p"] = p
    if r:
        out["r"] = r
    dflt = [k for k in ka if k in mb] + [e[kn] for e in n]
    if dflt != kb:
        out["o"] = kb
    return out


def _diff_val(av, bv):
    if isinstance(av, dict) and isinstance(bv, dict):
        d = _diff_dict(av, bv)
        return bool(d), d
    if isinstance(av, list) and isinstance(bv, list):
        lp = _diff_list(av, bv)
        if lp is not None:
            return len(lp) > 2, lp
    return _j(av) != _j(bv), None


def _diff_dict(a, b):
    s, rm, p = {}, [], {}
    for k in a:
        if k not in b:
            rm.append(k)
    for k, bv in b.items():
        if k not in a:
            s[k] = bv
            continue
        changed, sub = _diff_val(a[k], bv)
        if not changed:
            continue
        if sub is not None and len(_j(sub)) < len(_j(bv)):
            p[k] = sub
        else:
            s[k] = bv
    out = {}
    if s:
        out["$s"] = s
    if rm:
        out["$r"] = rm
    if p:
        out["$p"] = p
    dflt = [k for k in a if k in b] + [k for k in s if k not in a]
    if dflt != list(b):
        out["$o"] = list(b)
    return out


def diff(a, b):
    return _diff_dict(a, b)


def apply(a, d):
    if d.get("$L"):
        K = d.get("k", _KEYED)
        m = {e[K]: e for e in a}
        for k in d.get("r") or []:
            m.pop(k, None)
        for k, pp in d.get("p") or []:
            m[k] = apply(m[k], pp)
        order = d.get("o")
        if order is None:
            order = [e[K] for e in a if e[K] in m] + [e[K] for e in d.get("n") or []]
        for e in d.get("n") or []:
            m[e[K]] = e
        return [m[k] for k in order]
    o = dict(a)
    for k in d.get("$r") or []:
        o.pop(k, None)
    for k, v in (d.get("$s") or {}).items():
        o[k] = v
    for k, pp in (d.get("$p") or {}).items():
        o[k] = apply(o[k], pp)
    if "$o" in d:
        o = {k: o[k] for k in d["$o"]}
    return o


class SnapStore:
    RECENT = 16
    ANCHOR_SEC = 1800
    ANCHOR_KEEP = 86400
    MEMO_MAX = 64

    def __init__(self):
        self.lock = threading.Lock()
        self.cur = None
        self._cur_obj = None
        self.old = {}
        self.order = []
        self.memo = {}
        self.wanted = {}
        self.parts_old = {}
        self.pins = {}
    PARTS_KEEP = 4
    PARTS_KEEP_SEC = 600
    PARTS_KEEP_MAX = 16
    PIN_SEC = 86400
    PIN_MAX = 6

    def pin(self, ver: str, now=None):
        if not ver:
            return
        with self.lock:
            self.pins[ver] = time.time() if now is None else now

    def hold(self, ver: str, now=None):
        if not ver:
            return
        with self.lock:
            if ver in self.pins:
                self.pins[ver] = time.time() if now is None else now

    def _pins_live(self, now):
        live = sorted(((t, v) for v, t in self.pins.items() if now - t <= self.PIN_SEC), reverse=True)[:self.PIN_MAX]
        keep = {v for _t, v in live}
        for v in [v for v in self.pins if v not in keep]:
            self.pins.pop(v, None)
        return keep

    def part_gz(self, ver: str, name: str):
        with self.lock:
            cur = self.cur
            if cur is not None and cur.ver == ver and cur.parts_gz:
                return cur.parts_gz.get(name)
            ent = self.parts_old.get(ver)
            return ent[1].get(name) if ent else None

    def _evict_parts(self, now=None):
        now = time.time() if now is None else now
        vs = list(self.parts_old)
        keep = set(vs[-self.PARTS_KEEP:]) | {v for v in vs if now - self.parts_old[v][0] <= self.PARTS_KEEP_SEC}
        keep = set([v for v in vs if v in keep][-self.PARTS_KEEP_MAX:])
        for v in vs:
            if v not in keep:
                self.parts_old.pop(v, None)

    def publish(self, snap: Snap):
        with self.lock:
            prev = self.cur
            if prev is not None and prev.ver == snap.ver:
                self.cur = snap
                return
            if prev is not None:
                self.old[prev.ver] = (prev.at, prev.gz)
                self.order.append(prev.ver)
                if prev.parts_gz:
                    self.parts_old.pop(prev.ver, None)
                    self.parts_old[prev.ver] = (time.time(), prev.parts_gz)
                    self._evict_parts()
            self.cur = snap
            self._cur_obj = None
            self.memo = {k: v for k, v in self.memo.items() if k[1] == snap.ver}
            self._evict()

    def _evict(self, now=None):
        now = time.time() if now is None else now
        recent = set(self.order[-self.RECENT:])
        pinned = self._pins_live(now)
        keep, last_anchor = [], None
        for v in self.order:
            at = self.old[v][0]
            if v in recent or v in pinned:
                keep.append(v)
            elif now - at <= self.ANCHOR_KEEP and (last_anchor is None or at - last_anchor >= self.ANCHOR_SEC):
                keep.append(v)
                last_anchor = at
        for v in self.order:
            if v not in keep:
                self.old.pop(v, None)
        self.order = keep
        cur9 = self.cur.ver if self.cur is not None else None
        for v in [v for v in self.pins if v not in self.old and v != cur9]:
            self.pins.pop(v, None)

    def _cur_parsed(self):
        if self._cur_obj is None:
            self._cur_obj = json.loads(self.cur.raw)
        return self._cur_obj

    def delta_gz(self, since: str, compute=True, target=None):
        with self.lock:
            cur = self.cur
            if cur is None or (target is not None and cur.ver != target.ver):
                return None
            if since == cur.ver:
                return b""
            self.wanted[since] = time.time()
            key = (since, cur.ver)
            if key in self.memo:
                return self.memo[key]
            ent = self.old.get(since)
            if ent is None or not compute:
                return None
            old_gz = ent[1]
            cur_obj = self._cur_parsed()
        try:
            a = json.loads(gzip.decompress(old_gz))
            d = diff(a, cur_obj)
            body = dumps({"v": cur.ver, "b": since, "d": d})
            out = gz(body) if len(body) < len(cur.raw) else None
        except Exception:
            out = None
        with self.lock:
            if self.cur is cur:
                self.memo[key] = out
                if len(self.memo) > self.MEMO_MAX:
                    self.memo.pop(next(iter(self.memo)))
        return out

    def precompute(self):
        now = time.time()
        with self.lock:
            self.wanted = {v: t for v, t in self.wanted.items() if now - t < 120}
            todo = [v for v in self.wanted if self.cur and v != self.cur.ver]
        for v in todo:
            self.delta_gz(v)

    def note_served(self, ver):
        with self.lock:
            self.wanted[ver] = time.time()
