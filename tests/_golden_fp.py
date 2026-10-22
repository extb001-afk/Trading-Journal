from __future__ import annotations

import collections
import datetime as _dt
import decimal
import hashlib
import io
import json
import json.encoder
import socket
import sqlite3
import struct
import threading
import time
import types

MAX_DEPTH = 120
NORMALIZE = (
    ("hidden._dm_cache", ("ino",), "drop", "파일 inode — APFS 복제마다 다름(golden_diff 기본 무시와 같은 칸)"),
    ("hidden._flow_cache_hit", (0, 0), "drop", "파일 inode — APFS 복제마다 다름(golden_diff 기본 무시와 같은 칸)"),
    ("hidden._built_sig", (), "drop", "입력 파일 서명(실행 폴더 경로·inode) — golden_diff 기본 무시와 같은 칸"),
    ("hidden._sigc_memo", (), "drop", "입력 파일 서명 메모(inode·시각) — golden_diff 기본 무시와 같은 칸"),
    ("hidden._lpx_cache", (), "sortkeys", "빌드당 그룹 단가 메모(buildproc CHILD_ONLY) — 채우는 순서 = 부르는 순서(해시 순서 의존) · 열쇠별 값은 같음"),
)
NORMALIZE_ATTR = (
    ("_TopK", "th", "sort", "buychart CpPool 빠른 경로 힙(top 최소) — 배치는 집합(dirty·top) 반복 = 해시 순서 의존 · 원소 다중집합이 의미"),
    ("_TopK", "rh", "sort", "buychart CpPool 빠른 경로 힙(rest 최대) — 같은 이유"),
)
_LOCKS = (type(threading.Lock()), type(threading.RLock()))
_MARK = ((_LOCKS, "lock"), ((sqlite3.Connection,), "Connection"), ((sqlite3.Cursor,), "Cursor"),
         ((threading.Thread,), "Thread"), ((socket.socket,), "socket"), ((io.IOBase,), "file"), ((types.ModuleType,), "module"))
_PTR = struct.calcsize("P")


def _real(cls, name):
    for c in cls.__mro__:
        if c.__name__ == name and c.__module__ == "datetime":
            return c
    return cls


_DT, _DATE, _TIME = _real(_dt.datetime, "datetime"), _real(_dt.date, "date"), _real(_dt.time, "time")
_TD, _TZI = _real(_dt.timedelta, "timedelta"), _real(_dt.tzinfo, "tzinfo")
_STR = json.encoder.encode_basestring
_PURE = {}


class DumpFail(Exception):
    pass


def _pure_python(cls):
    v = _PURE.get(cls)
    if v is None:
        v, c = True, cls
        while c is not object:
            b = c.__base__
            s = c.__dict__.get("__slots__", ())
            s = [s] if isinstance(s, str) else list(s)
            own = sum(1 for x in s if x not in ("__dict__", "__weakref__"))
            add_d = c.__dictoffset__ > 0 and b.__dictoffset__ <= 0
            add_w = c.__weakrefoffset__ > 0 and b.__weakrefoffset__ <= 0
            if c.__basicsize__ - b.__basicsize__ != _PTR * (own + add_d + add_w):
                v = False
                break
            c = b
        _PURE[cls] = v
    return v


def _slot_names(cls):
    out = []
    for c in cls.__mro__:
        s = c.__dict__.get("__slots__")
        if s is not None:
            for x in ([s] if isinstance(s, str) else list(s)):
                if x in ("__dict__", "__weakref__"):
                    continue
                if x.startswith("__") and not x.endswith("__"):
                    x = "_%s%s" % (c.__name__.lstrip("_"), x)
                out.append(x)
    return out


def _tn(o):
    return type(o).__name__


class Encoder:

    def __init__(self, builder_cls=None, full=False, base=()):
        self.builder_cls = builder_cls
        self.full = full
        self.base = tuple(b for b in base if b)
        self.opaque = []
        self.fails = []
        self._attr_norm = {(t, a): m for t, a, m, _r in NORMALIZE_ATTR}

    def fingerprint(self, path, o, norm=None):
        self._seen, self._root = {}, path
        self._norm = {tuple(p): m for p, m, _r in (norm or ())}
        buf = []
        try:
            self._e(o, None, () if self._norm else None, 0, buf.append)
        except DumpFail as e:
            self.fails.append("%s: %s" % (path, e))
            return {"t": _tn(o), "fail": str(e)}
        except Exception as e:  # noqa: BLE001
            self.fails.append("%s: 직렬화 예외 %r" % (path, e))
            return {"t": _tn(o), "fail": "직렬화 예외 %s" % type(e).__name__}
        text = "".join(buf)
        out = {"t": _tn(o), "d": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()}
        for base in _SIZED:
            if isinstance(o, base):
                out["n"] = base.__len__(o)
                break
        if self.full is True or (self.full and path.split(".", 1)[-1] in self.full):
            out["v"] = json.loads(text)
        return out

    @staticmethod
    def _rel(node):
        parts = []
        while node is not None:
            node, kind, v = node
            parts.append(_PIECE[kind](v))
        return "".join(reversed(parts))

    def _abs(self, node):
        return self._root + self._rel(node)

    def _mark(self, node, label, o, w):
        self.opaque.append([self._abs(node), _tn(o)])
        w(json.dumps("<%s>" % label))

    def _leaf(self, v):
        t = type(v)
        if t is str:
            if self.base:
                for b in self.base:
                    if b in v:
                        v = v.replace(b, "<BASE>")
            return _STR(v)
        if t is int:
            return int.__repr__(v)
        if t is float:
            return repr(v) if v == v and v not in _INF else '["f","%r"]' % v
        if v is None:
            return "null"
        if t is bool:
            return "true" if v else "false"
        if t is _DEC:
            return '["D","%s"]' % v
        return None

    def _e(self, o, node, rel, depth, w):
        how = self._norm.get(rel) if (self._norm and rel is not None) else None
        if how == "drop":
            w('"<norm>"')
            return
        if depth > MAX_DEPTH:
            self.opaque.append([self._abs(node), "<deep>"])
            raise DumpFail("깊이 상한 %d 초과 %s" % (MAX_DEPTH, self._abs(node)))
        s = self._leaf(o)
        if s is not None:
            w(s)
            return
        t = type(o)
        if isinstance(o, bool):
            w('["bool","%s",%s]' % (_tn(o), "true" if o else "false"))
            return
        if isinstance(o, int):
            w('["int",%s,%d]' % (json.dumps(_tn(o)), int(o)))
            return
        if isinstance(o, str):
            w('["str",%s,%s]' % (json.dumps(_tn(o)), json.dumps(str(o), ensure_ascii=False)))
            return
        if isinstance(o, float):
            w('["float",%s,"%r"]' % (json.dumps(_tn(o)), float(o)))
            return
        if isinstance(o, (bytes, bytearray)):
            w('["b",%s,%d,"%s"]' % (json.dumps(_tn(o)), len(o), hashlib.sha256(bytes(o)).hexdigest()))
            return
        if isinstance(o, decimal.Decimal):
            w(json.dumps(["D", str(o), _tn(o)]))
            return
        if isinstance(o, _DT):
            w(json.dumps(["dt", o.isoformat(), _off(o.utcoffset()), o.tzname()], ensure_ascii=False))
            return
        if isinstance(o, _DATE):
            w(json.dumps(["date", o.isoformat()]))
            return
        if isinstance(o, _TIME):
            w(json.dumps(["time", o.isoformat(), _off(o.utcoffset()), o.tzname()], ensure_ascii=False))
            return
        if isinstance(o, _TD):
            w(json.dumps(["td", o.days, o.seconds, o.microseconds]))
            return
        if isinstance(o, _TZI):
            w(json.dumps(["tz", _tn(o), _off(o.utcoffset(None)), o.tzname(None)], ensure_ascii=False))
            return
        d1 = depth + 1
        fast = d1 <= MAX_DEPTH
        leaf = self._leaf
        nobase = not self.base
        if isinstance(o, dict):
            if self._ref(o, node, w):
                return
            fac = None
            if hasattr(o, "default_factory"):
                f = o.default_factory
                fac = None if f is None else getattr(f, "__qualname__", _tn(f))
            w('["{",null,null,[' if (t is dict and fac is None) else '["{",%s,%s,[' % (json.dumps(None if t is dict else _tn(o)), json.dumps(fac)))
            parts = [] if how == "sortkeys" else None
            items = o.items() if isinstance(o, collections.OrderedDict) else dict.items(o)
            for i, (k, v) in enumerate(items):
                ww = w
                if parts is not None:
                    sub = []
                    ww = sub.append
                elif i:
                    w(",")
                ww("[")
                tk = type(k)
                if tk is str and not nobase:
                    s = leaf(k) if fast else None
                elif tk is str:
                    s = _STR(k)
                elif tk is int:
                    s = int.__repr__(k)
                else:
                    s = leaf(k) if fast else None
                if s is not None:
                    ww(s)
                else:
                    self._e(k, (node, "k", i), None, d1, ww)
                ww(",")
                kp = k if (tk is str or tk is int or (isinstance(k, (str, int)) and not isinstance(k, bool))) else None
                crel = (rel + (kp,)) if (rel is not None and kp is not None) else None
                if crel is None and fast:
                    tv = type(v)
                    if tv is int:
                        ww(int.__repr__(v))
                        ww("]")
                        if parts is not None:
                            parts.append("".join(sub))
                        continue
                    if tv is str and nobase:
                        ww(_STR(v))
                        ww("]")
                        if parts is not None:
                            parts.append("".join(sub))
                        continue
                    s = leaf(v)
                else:
                    s = None
                if s is not None:
                    ww(s)
                else:
                    self._e(v, (node, ".", k) if kp is not None else (node, "{}", i), crel, d1, ww)
                ww("]")
                if parts is not None:
                    parts.append("".join(sub))
            if parts is not None:
                w(",".join(sorted(parts)))
            w("]]")
            return
        if isinstance(o, (list, tuple)):
            mutable = isinstance(o, list)
            if mutable and self._ref(o, node, w):
                return
            base = list if mutable else tuple
            if t is base:
                w('["[",null,[' if mutable else '["(",null,[')
            else:
                w('["%s",%s,[' % ("[" if mutable else "(", json.dumps(_tn(o))))
            quick = fast and rel is None
            for i, v in enumerate(base.__iter__(o)):
                if i:
                    w(",")
                if quick:
                    tv = type(v)
                    if tv is int:
                        w(int.__repr__(v))
                        continue
                    if tv is str and nobase:
                        w(_STR(v))
                        continue
                    s = leaf(v)
                    if s is not None:
                        w(s)
                        continue
                self._e(v, (node, "[]", i), (rel + (i,)) if rel is not None else None, d1, w)
            w("]]")
            return
        if isinstance(o, (set, frozenset)):
            if isinstance(o, set) and self._ref(o, node, w):
                return
            parts = []
            for v in o:
                s = leaf(v) if fast else None
                if s is None:
                    sub = []
                    self._e(v, (node, "set", None), None, d1, sub.append)
                    s = "".join(sub)
                parts.append(s)
            w('["%s",%s,[%s]]' % ("set" if isinstance(o, set) else "fset", json.dumps(None if t in (set, frozenset) else _tn(o)),
                                  ",".join(sorted(parts))))
            return
        if isinstance(o, sqlite3.Row):
            w('["row",[')
            for i, v in enumerate(tuple(o)):
                if i:
                    w(",")
                if fast:
                    tv = type(v)
                    if tv is int:
                        w(int.__repr__(v))
                        continue
                    if tv is str and nobase:
                        w(_STR(v))
                        continue
                    s = leaf(v)
                    if s is not None:
                        w(s)
                        continue
                self._e(v, (node, "[]", i), None, d1, w)
            w("]]")
            return
        if self.builder_cls is not None and isinstance(o, self.builder_cls):
            self._mark(node, "builder", o, w)
            return
        for types_, label in _MARK:
            if isinstance(o, types_):
                self._mark(node, label, o, w)
                return
        if callable(o):
            w('"<callable>"')
            return
        if not _pure_python(t):
            self.opaque.append([self._abs(node), _tn(o)])
            raise DumpFail("닫힌 형 표 밖(C 상태) %s %s" % (_tn(o), self._abs(node)))
        if self._ref(o, node, w):
            return
        attrs = []
        if t.__dictoffset__:
            attrs += list(dict.items(object.__getattribute__(o, "__dict__")))
        for sl in _slot_names(t):
            try:
                attrs.append((sl, object.__getattribute__(o, sl)))
            except AttributeError:
                attrs.append((sl, _UNSET))
        tn = _tn(o)
        w('["obj",%s,[' % _STR(tn))
        for i, (k, v) in enumerate(sorted(attrs, key=lambda kv: kv[0])):
            if i:
                w(",")
            w("[%s," % _STR(k))
            if v is _UNSET:
                w('"<unset>"')
            elif self._attr_norm.get((tn, k)) == "sort" and isinstance(v, list):
                parts = []
                for j, x in enumerate(v):
                    s = leaf(x) if fast else None
                    if s is None:
                        sub = []
                        self._e(x, (node, "s", (k, j)), None, d1, sub.append)
                        s = "".join(sub)
                    parts.append(s)
                w('["[sorted",[%s]]' % ",".join(sorted(parts)))
            else:
                crel = (rel + (k,)) if rel is not None else None
                s = leaf(v) if (fast and crel is None) else None
                if s is not None:
                    w(s)
                else:
                    self._e(v, (node, ".", k), crel, d1, w)
            w("]")
        w("]]")

    def _ref(self, o, node, w):
        p = self._seen.get(id(o), _UNSET)
        if p is not _UNSET:
            w(json.dumps(["ref", self._rel(p)], ensure_ascii=False))
            return True
        self._seen[id(o)] = node
        return False


_UNSET = object()
_SIZED = (dict, list, tuple, set, frozenset, str, bytes, bytearray)
_DEC = decimal.Decimal
_INF = (float("inf"), float("-inf"))
_PIECE = {"k": lambda i: "{k%d}" % i, ".": lambda k: "." + str(k), "{}": lambda i: "{%d}" % i, "[]": lambda i: "[%d]" % i,
          "set": lambda _v: "{set}", "s": lambda kj: ".%s[%d]" % kj}


def _off(td):
    return None if td is None else td.days * 86400 + td.seconds + td.microseconds / 1e6


def norm_for(top):
    return [(p, m, r) for t, p, m, r in NORMALIZE if t == top]


def capture_scope(enc, scope, names, books_fields, ctx_fields, prefix="boundary"):
    if hasattr(scope, "as_old_names"):
        scope = scope.as_old_names()
    out, memo = {}, {}
    enc.cost = {}

    def one(key, val):
        hit = memo.get(id(val))
        if hit is not None:
            fp, ops, src = hit
            enc.opaque.extend([[prefix + "." + key + p[len(prefix + "." + src):], tn] for p, tn in ops])
            out[key] = dict(fp)
            return
        start, t0 = len(enc.opaque), time.monotonic()
        fp = enc.fingerprint(prefix + "." + key, val)
        enc.cost[key] = time.monotonic() - t0
        memo[id(val)] = (fp, list(enc.opaque[start:]), key)
        out[key] = fp

    for n in names:
        if n in scope:
            one(n, scope[n])
        else:
            out[n] = {"t": "<missing>"}
    for owner, fields in (("books", books_fields), ("ctx", ctx_fields)):
        obj = scope.get(owner)
        for f in fields:
            key = "%s.%s" % (owner, f)
            if obj is None or not hasattr(obj, f):
                out[key] = {"t": "<missing>"}
            else:
                one(key, getattr(obj, f))
    return out
