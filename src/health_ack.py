from __future__ import annotations

import hashlib
import json
import os
import threading

import paths, statefile

NAME = "health_ack.json"
V = 1
ACKABLE = frozenset(("price:unpriced", "price:proof", "debt:margin", "rabby:gap", "balcheck:disc", "chainsweep:untracked"))
GROW_PCT = 0.5
GROW_USD = 200.0
MAX_ENTS = 2000
ID_MAX = 200
ID_V = "~id1:"
LEGACY = "~old:"
_LOCK = threading.Lock()


def path() -> str:
    return paths.state(NAME)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()


def ent_id(raw) -> str:
    s = str(raw or "")
    return s if len(s) < ID_MAX else ID_V + _sha(s)


def _canon(k) -> str:
    s = str(k or "")
    return s if len(s) < ID_MAX else LEGACY + _sha(s)


def _amt(v):
    try:
        f9 = float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        f9 = None
    if f9 is not None and not (f9 == f9 and abs(f9) != float("inf")):
        f9 = None
    return round(abs(f9), 2) if f9 is not None else None


def _norm(ents, keyf) -> dict:
    grp = {}
    for k, v in (ents or {}).items() if isinstance(ents, dict) else ():
        r9 = str(k or "")
        k9 = keyf(r9)
        if not k9:
            continue
        g9 = grp.setdefault(k9, {})
        a9, f9 = g9.get(r9), _amt(v)
        g9[r9] = f9 if a9 is None else (a9 if f9 is None else max(a9, f9))
    out = {}
    for k9, g9 in grp.items():
        vs9 = [x for x in g9.values() if x is not None]
        key9 = k9 if len(g9) == 1 else ID_V + "x" + _sha(json.dumps(sorted(g9), ensure_ascii=False))
        out[key9] = max(vs9) if vs9 else None
    if len(out) > MAX_ENTS:
        out = dict(sorted(out.items(), key=lambda kv: (-(kv[1] or 0), kv[0]))[:MAX_ENTS])
    return out


def ent_ids(ents) -> dict:
    return _norm(ents, ent_id)


def norm_ents(ents) -> dict:
    return _norm(ents, _canon)


def _stored(ents) -> dict:
    return {k: v for k, v in ents.items() if isinstance(k, str) and k and len(k) < ID_MAX and not k.startswith(LEGACY)} if isinstance(ents, dict) else {}


def fp(check: str, level: str, ents) -> str:
    raw = json.dumps([str(check or ""), str(level or ""), sorted(norm_ents(ents))], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load():
    try:
        with open(path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {"v": V, "items": {}}, None
    except (OSError, ValueError) as e:
        return None, f"닫은 주의 기록을 못 읽어요({type(e).__name__}) — 닫은 주의도 모두 보여 줘요"
    if not isinstance(d, dict) or d.get("v") != V or not isinstance(d.get("items"), dict):
        return None, "닫은 주의 기록의 형식을 몰라요 — 닫은 주의도 모두 보여 줘요(파일은 그대로 둠)"
    return d, None


def covered(entry, level: str, ents) -> bool:
    if level != "warn" or not isinstance(entry, dict) or not isinstance(entry.get("ents"), dict):
        return False
    cur = norm_ents(ents)
    if not cur or any(k.startswith(LEGACY) for k in cur):
        return False
    old = _stored(entry["ents"])
    for k, v in cur.items():
        if k not in old:
            return False
        a = old.get(k)
        if a is None and v is not None and v >= GROW_USD:
            return False
        if v is not None and isinstance(a, (int, float)) and not isinstance(a, bool) and v > a and v - a >= max(GROW_USD, GROW_PCT * a):
            return False
    return True


def state(doc, check: str, level: str, ents):
    if not isinstance(doc, dict) or check not in ACKABLE:
        return None
    e = (doc.get("items") or {}).get(check)
    if not isinstance(e, dict):
        return None
    return "acked" if covered(e, level, ents) else "changed"


def _locked(fn):
    import fcntl
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with _LOCK, open(p + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        doc, err = load()
        if doc is None:
            return False, err
        ok, msg, new = fn(doc)
        if ok and new is not None:
            statefile.atomic_write_json(p, new)
        return ok, msg


def ack(check: str, level: str, ents, title: str = "", detail: str = "", now: float = 0.0):
    cur = norm_ents(ents)
    if check not in ACKABLE or level != "warn" or not cur:
        return False, "이 항목은 닫을 수 없어요(오류·정리 대상은 닫기 없음)"
    if any(k.startswith(LEGACY) for k in cur):
        return False, "옛 형식 항목이 섞여 있어요 — 다음 점검(약 1분) 뒤 새로고침해서 다시 닫아 주세요"

    def fn(doc):
        items = dict(doc.get("items") or {})
        old = items.get(check) if isinstance(items.get(check), dict) else {}
        ents9 = _stored(old.get("ents"))
        ents9.update(cur)
        items[check] = {"at": int(now), "level": "warn", "ents": norm_ents(ents9),
                        "title": str(title or "")[:160], "detail": str(detail or "")[:400]}
        return True, "닫았어요 — 같은 내용이면 다시 안 띄워요", {"v": V, "items": items}
    return _locked(fn)


def restore(check: str):
    def fn(doc):
        items = dict(doc.get("items") or {})
        if check not in items:
            return False, "닫은 기록이 없어요", None
        items.pop(check, None)
        return True, "되살렸어요", {"v": V, "items": items}
    return _locked(fn)


def entries(doc) -> list:
    out = []
    for c9, e9 in ((doc or {}).get("items") or {}).items() if isinstance(doc, dict) else ():
        if isinstance(e9, dict) and c9 in ACKABLE:
            out.append({"check": c9, "at": e9.get("at"), "title": str(e9.get("title") or c9), "detail": str(e9.get("detail") or ""),
                        "n": len(_stored(e9.get("ents")))})
    out.sort(key=lambda x: -float(x.get("at") or 0))
    return out
