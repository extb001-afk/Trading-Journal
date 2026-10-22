from __future__ import annotations

import hashlib
import json
import os
import re

from _cassette_clock import uuid_n

_HEXRUN = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{40,})(?![0-9A-Fa-f])")
_B58LONG = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{45,}(?![A-Za-z0-9])")
_TOKEN = re.compile(r"«([0-9A-Fa-f*+]+)»")
_UUIDRUN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_UTOKEN = re.compile(r"«u:(\d+)»")
KNOWN_HEX64 = {"ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
               "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"}
LIT_MAX = 16


def _rle(h: str):
    parts, lit, i = [], 0, 0
    while i < len(h):
        best = None
        for L in (1, 2, 4):
            u = h[i:i + L]
            if len(u) < L:
                break
            n = 1
            while h[i + n * L:i + (n + 1) * L] == u:
                n += 1
            if n * L >= 8 and (best is None or n * L > len(best[0]) * best[1]):
                best = (u, n)
        if best:
            parts.append("%s*%d" % best)
            i += len(best[0]) * best[1]
            continue
        if parts and "*" not in parts[-1]:
            parts[-1] += h[i]
        else:
            parts.append(h[i])
        lit += 1
        i += 1
    return None if lit > LIT_MAX else "«" + "+".join(parts) + "»"


def _unrle(m) -> str:
    out = []
    for p in m.group(1).split("+"):
        if "*" in p:
            u, n = p.rsplit("*", 1)
            out.append(u * int(n))
        else:
            out.append(p)
    return "".join(out)


def _fp(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:12]


def _words(h: str) -> list:
    if len(h) > 64 and (len(h) - 8) % 64 == 0:
        return [h[:8]] + [h[i:i + 64] for i in range(8, len(h), 64)]
    return [h[i:i + 64] for i in range(0, len(h), 64)]


def _enc_str(s: str, lossy: bool, where: str) -> str:
    if "«" in s or "»" in s:
        raise ValueError(f"카세트: 값에 표기 글자(«»)가 들어 있음 — {where}")

    def bad(v, what):
        if lossy:
            return "«~" + _fp(v) + "»"
        raise ValueError(f"카세트: 합성 꼴이 아닌 {what}(실값 의심) — {where}")

    def rep(m):
        h = m.group(1)
        if len(h) in (40, 64):
            if h.lower() in KNOWN_HEX64:
                return h
            t = _rle(h)
            return t if t is not None else bad(h, f"{len(h)}자리 16진수")
        return h if all(_rle(w) is not None for w in _words(h)) else bad(h, f"긴 16진수({len(h)}자리)")

    def brep(m):
        v = m.group(0)
        mixed = any(c.isdigit() for c in v) and any(c.islower() for c in v) and any(c.isupper() for c in v)
        return bad(v, f"긴 base58 꼴({len(v)}자)") if mixed else v

    def urep(m):
        u = m.group(0)
        try:
            n = int(u[:8], 16)
        except ValueError:
            n = -1
        if n > 0 and str(uuid_n(n)) == u.lower():
            return "«u:%d»" % n
        return bad(u, "UUID(응답기는 UUID 모양이 아닌 id 를 쓸 것)")
    return _B58LONG.sub(brep, _UUIDRUN.sub(urep, _HEXRUN.sub(rep, s)))


def enc(o, lossy: bool = False, where: str = "?"):
    if isinstance(o, str):
        return _enc_str(o, lossy, where)
    if isinstance(o, dict):
        return {enc(k, lossy, where): enc(v, lossy, where) for k, v in o.items()}
    if isinstance(o, list):
        return [enc(v, lossy, where) for v in o]
    return o


def dec(o):
    if isinstance(o, str):
        return _UTOKEN.sub(lambda m: str(uuid_n(int(m.group(1)))), _TOKEN.sub(_unrle, o)) if "«" in o else o
    if isinstance(o, dict):
        return {dec(k): dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [dec(v) for v in o]
    return o


def canon(o):
    return json.loads(json.dumps(o, sort_keys=True, ensure_ascii=False, default=str))


PID_FILES = re.compile(r"(^|/)(health/[^/]+|runner_[^/]+)\.json$")


def scrub(o, key: str = ""):
    if isinstance(o, dict):
        return {k: ("<pid>" if k == "pid" and PID_FILES.search(key) else scrub(v, k)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v, key) for v in o]
    return o


def diff(a, b, path: str = "$"):
    if type(a) != type(b):   # noqa: E721
        yield {"자리": path, "골든": _short(a), "지금": _short(b)}
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                yield {"자리": f"{path}.{k}", "골든": "(없음)", "지금": _short(b[k])}
            elif k not in b:
                yield {"자리": f"{path}.{k}", "골든": _short(a[k]), "지금": "(없음)"}
            else:
                yield from diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            yield {"자리": path, "골든": f"{len(a)}개", "지금": f"{len(b)}개"}
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, f"{path}[{i}]")
    elif a != b:
        yield {"자리": path, "골든": _short(a), "지금": _short(b)}


def _short(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "…"


SNAP_SKIP = (r"(^|/)\.[^/]*lock$", r"\.lock$", r"\.log$", r"\.pid$", r"\.tmp$", r"(^|/)__pycache__/",
             r"(^|/)node_stats/")


def read_any(p: str):
    raw = open(p, "rb").read()
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]
    if p.endswith(".jsonl"):
        out = []
        for ln in s.splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                out.append(ln)
        return out
    if p.endswith(".json"):
        try:
            return json.loads(s)
        except ValueError:
            return s
    return s.splitlines()


def snap_tree(root: str, skip=SNAP_SKIP, only=None) -> dict:
    out = {}
    for dp, dn, fns in os.walk(root):
        dn.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if any(re.search(rx, rel) for rx in skip):
                continue
            if only is not None and not any(re.search(rx, rel) for rx in only):
                continue
            out[rel] = read_any(p)
    return out
