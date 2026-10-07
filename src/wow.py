from __future__ import annotations

import math
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import common

KST = timezone(timedelta(hours=9))
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_EX_ORDER = ("binance", "bybit", "upbit", "okx", "gate", "bithumb", "kucoin")
_LOCK = threading.Lock()
_PX = {"sig": None, "by_sym": None, "by_key": None}
_CACHE = {}


def _px_files():
    return (os.path.join(common.STATE_DIR, "curve_hist_px.json"), os.path.join(common.STATE_DIR, "daily_close_px.json"))


def _sig():
    out = []
    for p in _px_files():
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((p, None, None))
    return tuple(out)


def _clean(pmap) -> dict:
    out = {}
    if not isinstance(pmap, dict):
        return out
    for d, v in pmap.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if _ISO.fullmatch(str(d)) and math.isfinite(f) and f > 0:
            out[str(d)] = f
    return out


def px_by_sym() -> dict:
    sig = _sig()
    with _LOCK:
        if _PX["sig"] == sig and _PX["by_sym"] is not None:
            return _PX["by_sym"]
    specs = {}
    for i, p in enumerate(_px_files()):
        try:
            d = common.read_json(p, {}) if os.path.exists(p) else {}
        except (SystemExit, Exception):
            d = {}
        if not isinstance(d, dict):
            continue
        src = (d.get("specs") if i == 0 else d.get("s")) or {}
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            pm = _clean((v or {}).get("p") if isinstance(v, dict) else None)
            if pm:
                specs.setdefault(str(k), {}).update(pm)
    rank = {}
    by_sym = {}
    for k, pm in specs.items():
        parts = k.split(":")
        if parts[0] == "sym" and len(parts) == 2:
            sym, r = parts[1].upper(), 0
        elif parts[0] == "ex" and len(parts) == 3:
            sym = parts[2].upper()
            r = 1 + (_EX_ORDER.index(parts[1]) if parts[1] in _EX_ORDER else len(_EX_ORDER))
        else:
            continue
        if sym not in by_sym or r < rank[sym]:
            by_sym[sym], rank[sym] = dict(pm), r
        elif r == rank[sym]:
            by_sym[sym].update(pm)
    with _LOCK:
        _PX.update(sig=sig, by_sym=by_sym)
    return by_sym


def px_by_key() -> dict:
    sig = _sig()
    with _LOCK:
        if _PX.get("ksig") == sig and _PX.get("by_key") is not None:
            return _PX["by_key"]
    raw = []
    for i, p in enumerate(_px_files()):
        try:
            d = common.read_json(p, {}) if os.path.exists(p) else {}
        except (SystemExit, Exception):
            d = {}
        src = ((d.get("specs") if i == 0 else d.get("s")) or {}) if isinstance(d, dict) else {}
        raw.append(src if isinstance(src, dict) else {})
    try:
        import histcurve as hc
    except Exception:
        hc = None
    out = {}
    for sp in set(raw[0]) | set(raw[1] if len(raw) > 1 else {}):
        ents = [r.get(sp) for r in raw]
        ents = [e for e in ents if isinstance(e, dict)]
        if not ents:
            continue
        blk = set()
        if hc is not None:
            try:
                blk = hc.blocked_union(*ents) | hc.map_blocked(sp)
            except Exception:
                blk = hc.blocked_union(*ents)
        pm = {}
        for e in ents:
            v = hc.view(e, blk) if (hc is not None and blk) else e
            if not isinstance(v, dict):
                continue
            pend = set(v.get("pend") or ())
            pm.update({d9: x9 for d9, x9 in _clean(v.get("p")).items() if d9 not in pend})
        if pm:
            out[str(sp)] = pm
    with _LOCK:
        _PX.update(ksig=sig, by_key=out)
    return out


def _price_on(pm: dict, keys: list, iso: str):
    import bisect
    i = bisect.bisect_right(keys, iso) - 1
    if i < 0:
        return None
    d0 = keys[i]
    try:
        if (datetime.strptime(iso, "%Y-%m-%d") - datetime.strptime(d0, "%Y-%m-%d")).days > 7:
            return None
    except ValueError:
        return None
    return pm[d0]


_NOT_SALE_EX = ("유동성(DEX LP)", "스테이킹 보상")
STABLE = {"USDT", "USDC", "DAI", "BUSD", "USDG", "USDE", "CUSD", "USD1", "NUSD", "USDM", "FDUSD", "PYUSD", "TUSD", "RLUSD", "USDS"}
_SKIP_KINDS = ("gas", "lp", "stable", "quarantined")
_GID = re.compile(r"^g(\d+)")


def _not_sale(r) -> bool:
    return bool(r.get("fut") or r.get("ticker") == "LP" or str(r.get("ex") or "").startswith(_NOT_SALE_EX))


def _stable_syms(idx) -> set:
    out = set(STABLE)
    for p in (idx or {}).get("pos") or ():
        if isinstance(p, dict) and p.get("kind") == "stable":
            out.add(str(p.get("sym") or "").upper())
    return out


def _skip_card(p, st_syms) -> bool:
    return (p.get("kind") in _SKIP_KINDS or str(p.get("key", "")).startswith("lp:")
            or str(p.get("sym") or "").upper() in st_syms)


def _sells(idx, since_iso: str, excl=frozenset()) -> dict:
    out = {}
    for r in idx.get("tax") or ():
        if _not_sale(r):
            continue
        d = str(r.get("sold") or "")
        if not _ISO.fullmatch(d) or d < since_iso:
            continue
        sym = str(r.get("sym") or "?").upper()
        if sym in excl:
            continue
        try:
            q = float(r.get("_qty", r.get("qty")) or 0)
            disp = float(r.get("_disp", r.get("xd", r.get("disp"))) or 0)
            acq = float(r.get("_acq", r.get("xa", r.get("acq"))) or 0)
        except (TypeError, ValueError):
            continue
        if not (q > 0 and disp > 0):
            continue
        k = (d, sym)
        a = out.setdefault(k, [0.0, 0.0, 0.0])
        a[0] += q
        a[1] += disp
        a[2] += acq
    return out


_AMT = re.compile(r"[-−]?\$?([\d,]+(?:\.\d+)?)")


def _usd_of(e) -> float:
    m = _AMT.search(str(e.get("a") or ""))
    try:
        return float(m.group(1).replace(",", "")) if m else 0.0
    except ValueError:
        return 0.0


def _is_sell(kind, e) -> bool:
    k9 = str(e.get("k") or "")
    return kind == "pos" and "매도" in k9 and not k9.startswith("LP")


def _sale_index(idx, since_iso: str, quar_keys=frozenset(), skip_gids=frozenset()) -> dict:
    out = {}
    for d, rows in (idx.get("ix") or {}).items():
        if not _ISO.fullmatch(str(d)) or d < since_iso:
            continue
        for ts, kind, e, meta in rows:
            if not isinstance(e, dict):
                continue
            k9 = str(e.get("k") or "")
            if kind == "hidden":
                if "매도" not in k9 or k9.startswith("LP"):
                    continue
                hid9 = True
            elif _is_sell(kind, e):
                pk9 = str((meta[0] if meta else "") or "")
                m9 = _GID.match(pk9)
                hid9 = pk9 in quar_keys or bool(m9 and int(m9.group(1)) in skip_gids)
            else:
                continue
            sym = str((meta[1] if meta else None) or e.get("sym") or "?").upper()
            u = _usd_of(e)
            ent = out.setdefault((d, sym), {"when": None, "gids": {}, "keys": set(), "gq": {}, "gk": {}, "gku": {}, "qmiss": False,
                                            "hn": 0, "hq": 0.0, "hk": 0.0, "hku": 0.0, "hmiss": False})
            cm9 = e.get("_cmp") if isinstance(e.get("_cmp"), dict) else {}
            try:
                cq, cu = float(cm9.get("q")), float(cm9.get("unk") or 0.0)
            except (TypeError, ValueError):
                cq, cu = None, 0.0
            if hid9:
                ent["hn"] += 1
                if cq is not None and cq > 0:
                    kq9 = max(0.0, cq - max(0.0, cu))
                    ent["hq"] += cq
                    ent["hk"] += kq9
                    ent["hku"] += max(u, 0.0) * kq9 / cq
                else:
                    ent["hmiss"] = True
                continue
            if ent["when"] is None or u > ent["when"][1]:
                ent["when"] = (int(ts or 0), u)
            ent["keys"].add(str((meta[0] if meta else "") or ""))
            m = _GID.match(str((meta[0] if meta else "") or ""))
            if m:
                g = int(m.group(1))
                ent["gids"][g] = ent["gids"].get(g, 0.0) + max(u, 1e-9)
                if cq is not None and cq > 0:
                    ent["gq"][g] = ent["gq"].get(g, 0.0) + cq
                    kq9 = max(0.0, cq - max(0.0, cu))
                    ent["gk"][g] = ent["gk"].get(g, 0.0) + kq9
                    ent["gku"][g] = ent["gku"].get(g, 0.0) + max(u, 0.0) * kq9 / cq
                else:
                    ent["qmiss"] = True
    return out


def _quar_sets(idx, kit):
    keys = {str(p.get("key")) for p in (idx.get("pos") or ()) if isinstance(p, dict) and p.get("kind") == "quarantined"}
    gids = set()
    for g, v in ((kit or {}).get("groups") or {}).items():
        if isinstance(v, dict) and v.get("skip"):
            try:
                gids.add(int(g))
            except (TypeError, ValueError):
                pass
    return keys, gids


def _spec_of_gid(kit, gid):
    G = (kit or {}).get("groups") or {}
    g = G.get(gid) if gid in G else G.get(str(gid))
    if not isinstance(g, dict) or g.get("skip"):
        return None
    try:
        import histcurve
        sp = histcurve.spec_of(g)
    except Exception:
        return None
    if sp == "ov":
        try:
            return "ov:" + repr(float(g.get("ov")))
        except (TypeError, ValueError):
            return None
    return sp


class _Px:

    def __init__(self, by_key, today_iso):
        self.by_key, self.today, self._c = by_key or {}, today_iso, {}

    def series(self, sp):
        if sp in self._c:
            return self._c[sp]
        if sp is None:
            v = None
        elif sp == "stable":
            v = ("fix", 1.0)
        elif str(sp).startswith("ov:"):
            try:
                v = ("fix", float(str(sp)[3:]))
            except ValueError:
                v = None
            v = v if v and v[1] > 0 else None
        else:
            pm = self.by_key.get(sp) or {}
            keys = sorted(k for k in pm if k <= self.today)
            v = ("map", pm, keys) if keys else None
        self._c[sp] = v
        return v

    def last_day(self, sp):
        s = self.series(sp)
        if s is None:
            return None
        return self.today if s[0] == "fix" else s[2][-1]

    def live(self, sp) -> bool:
        ld = self.last_day(sp)
        if ld is None:
            return False
        try:
            return (datetime.strptime(self.today, "%Y-%m-%d") - datetime.strptime(ld, "%Y-%m-%d")).days <= 7
        except ValueError:
            return False

    def at(self, sp, iso):
        s = self.series(sp)
        if s is None:
            return None
        if s[0] == "fix":
            return s[1]
        import bisect
        i = bisect.bisect_right(s[2], iso) - 1
        return s[1][s[2][i]] if i >= 0 else None


def _lots(idx, since_iso, today_iso, excl):
    kit = None
    try:
        import histcurve
        kit = getattr(histcurve.HIST, "kit", None)
    except Exception:
        kit = None
    sells = _sells(idx, since_iso, excl)
    quar, skip9 = _quar_sets(idx, kit)
    sx = _sale_index(idx, since_iso, quar, skip9)
    HID = "\0hid"
    same = lambda a, b: abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))
    out = []
    for (d, sym), (q, disp, acq) in sells.items():
        ent9 = sx.get((d, sym)) or {}
        gids = ent9.get("gids") or {}
        hn9 = ent9.get("hn", 0) > 0
        if hn9:
            ent9["hmix"] = True
        if not gids and hn9:
            continue
        parts, pq, pk, pku = {}, {}, {}, {}
        for g, w in gids.items():
            sp = _spec_of_gid(kit, g)
            parts[sp] = parts.get(sp, 0.0) + w
            pq[sp] = pq.get(sp, 0.0) + float((ent9.get("gq") or {}).get(g) or 0.0)
            pk[sp] = pk.get(sp, 0.0) + float((ent9.get("gk") or {}).get(g) or 0.0)
            pku[sp] = pku.get(sp, 0.0) + float((ent9.get("gku") or {}).get(g) or 0.0)
        tot = sum(parts.values())
        if not parts or tot <= 0:
            out.append((d, sym, None, q, disp, acq))
            continue
        hk9 = float(ent9.get("hk") or 0.0)
        mixed9 = hn9 and (ent9.get("hmiss") or hk9 > 0)
        if len(parts) == 1 and not mixed9 and ent9.get("qmiss"):
            if hn9:
                ent9["hmix"] = False
            out.append((d, sym, next(iter(parts)), q, disp, acq))
            continue
        if mixed9 and not ent9.get("hmiss"):
            pk, pku, pq, parts = dict(pk), dict(pku), dict(pq), dict(parts)
            pk[HID], pku[HID] = float(ent9.get("hk") or 0.0), float(ent9.get("hku") or 0.0)
            pq[HID], parts[HID] = pk[HID], pku[HID]
        base9, wu9 = None, None
        if not ent9.get("qmiss"):
            if sum(pk.values()) > 0 and same(sum(pk.values()), q):
                base9, wu9 = pk, pku
            elif sum(pq.values()) > 0 and same(sum(pq.values()), q):
                base9, wu9 = pq, parts
        if hn9:
            ent9["hmix"] = base9 is None or base9.get(HID, 0.0) > 0
        live9 = [sp9 for sp9 in parts if base9 is not None and base9.get(sp9, 0.0) > 0]
        if base9 is None or not live9 or (len(live9) > 1 and sum(wu9.get(sp9, 0.0) for sp9 in live9) <= 0):
            out.append((d, sym, None, q, disp, acq))
            continue
        qt, ut = sum(base9[sp9] for sp9 in live9), sum(wu9.get(sp9, 0.0) for sp9 in live9)
        for sp in live9:
            if sp == HID:
                continue
            fq, fu = (1.0, 1.0) if len(live9) == 1 else (base9[sp] / qt, wu9.get(sp, 0.0) / ut)
            out.append((d, sym, sp, q * fq, disp * fu, acq * fq))
    return out, sx


def bench(idx, today_iso: str = None, since: str = None) -> dict:
    if not idx or idx.get("tax") is None:
        return {"hold": {}, "holdCov": None, "nSell": 0, "rows": [], "since": since}
    today_iso = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    if not (since and _ISO.fullmatch(str(since))):
        since = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
    since = min(since, today_iso)
    key = ("bench", idx.get("builtAt"), _sig(), today_iso, since, id(getattr(_hist_mod(), "kit", None)))
    with _LOCK:
        hit = _CACHE.get("bench")
        if hit and hit[0] == key:
            return hit[1]
    lots, _sx = _lots(idx, since, today_iso, _stable_syms(idx))
    P = _Px(px_by_key(), today_iso)
    tot = cov = 0.0
    rows, use, last = [], [], []
    for d, sym, sp, q, disp, acq in lots:
        tot += disp
        ok = sp is not None and P.live(sp)
        now = P.at(sp, today_iso) if ok else None
        if ok and now is not None:
            cov += disp
            use.append((d, sp, q, disp))
            last.append(P.last_day(sp))
        rows.append({"d": d, "sym": sym, "q": round(q, 10), "sp": round(disp / q, 12) if q > 0 else None,
                     "now": round(now, 12) if now is not None else None, "usd": round(disp, 2),
                     "diff": round(q * now - disp, 2) if now is not None else None,
                     "st": "ok" if now is not None else ("nogrp" if sp is None else "nopx"),
                     "lastPx": None if (now is not None or sp is None) else P.last_day(sp)})
    hold = {}
    if use:
        d0 = min(u[0] for u in use)
        x = datetime.strptime(d0, "%Y-%m-%d")
        end = datetime.strptime(today_iso, "%Y-%m-%d")
        days = []
        while x <= end:
            days.append(x.strftime("%Y-%m-%d"))
            x += timedelta(days=1)
        acc = dict.fromkeys(days, 0.0)
        by_sp = {}
        for d, sp, q, disp in use:
            by_sp.setdefault(sp, []).append((d, q, disp))
        for sp, rs in by_sp.items():
            rs.sort()
            j, cq, cp, pend = 0, 0.0, 0.0, 0.0
            for dd in days:
                while j < len(rs) and rs[j][0] <= dd:
                    cq += rs[j][1]
                    cp += rs[j][2]
                    j += 1
                if cq <= 0:
                    continue
                p = P.at(sp, dd)
                if p is None:
                    continue
                acc[dd] += cq * p - cp
        hold = {k: round(v, 2) for k, v in acc.items() if v}
    rows.sort(key=lambda r: (r["d"], r["usd"]), reverse=True)
    out = {"hold": hold, "holdCov": round(cov / tot, 4) if tot > 0 else None, "nSell": len({(r["d"], r["sym"]) for r in rows}),
           "since": since, "basis": "group", "pxAt": max(last) if last else None,
           "rows": rows[:300], "nRows": len(rows)}
    with _LOCK:
        _CACHE["bench"] = (key, out)
    return out


def _hist_mod():
    try:
        import histcurve
        return histcurve.HIST
    except Exception:
        return None


def habits(idx, today_iso: str = None) -> dict:
    if not idx or idx.get("pos") is None or idx.get("tax") is None:
        return {"ok": False, "why": "building"}
    today_iso = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    key = ("habits", idx.get("builtAt"), _sig(), today_iso, id(getattr(_hist_mod(), "kit", None)))
    with _LOCK:
        hit = _CACHE.get("habits")
        if hit and hit[0] == key:
            return hit[1]
    since = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    st_syms = _stable_syms(idx)
    real, opened = {}, {}
    excl = {"stable": 0, "quar": 0}
    for p in idx["pos"]:
        skip = _skip_card(p, st_syms)
        sym = str(p.get("sym") or "?").upper()
        ots = p.get("_ots")
        for d, v in (p.get("realizedByDay") or {}).items():
            if not _ISO.fullmatch(str(d)) or d < since:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if skip:
                if abs(f) >= 1.0 and p.get("kind") == "quarantined":
                    excl["quar"] += 1
                elif abs(f) >= 1.0 and p.get("kind") not in ("gas", "lp"):
                    excl["stable"] += 1
                continue
            k = (d, sym)
            real[k] = real.get(k, 0.0) + f
            if isinstance(ots, (int, float)) and ots > 0:
                prev = opened.get(k)
                if prev is None or abs(f) > prev[1]:
                    opened[k] = (float(ots), abs(f))
    lots, sx = _lots(idx, since, today_iso, st_syms)
    grid = [[[0, 0, 0.0] for _ in range(12)] for _ in range(7)]
    n = w = 0
    for k, r in real.items():
        wh = (sx.get(k) or {}).get("when")
        if abs(r) < 1.0 or not wh or not wh[0]:
            continue
        dt = datetime.fromtimestamp(wh[0], KST)
        c = grid[dt.weekday()][dt.hour // 2]
        c[0] += 1
        c[2] += r
        n += 1
        if r > 0:
            c[1] += 1
            w += 1
    for row in grid:
        for c in row:
            c[2] = round(c[2], 2)
    BK = [(1, "하루 안"), (7, "1주 안"), (30, "1달 안"), (90, "3달 안"), (100000, "3달 넘게")]
    hold = [[lab, 0.0, 0.0, 0] for _d, lab in BK]
    sells = _sells(idx, since, st_syms)
    for (d, sym), (q, disp, acq) in sells.items():
        o = opened.get((d, sym))
        if not o or acq <= 0:
            continue
        if (sx.get((d, sym)) or {}).get("hmix"):
            excl["mix"] = excl.get("mix", 0) + 1
            continue
        wh = (sx.get((d, sym)) or {}).get("when")
        try:
            t_sell = wh[0] if wh and wh[0] else (datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=1)).timestamp() - 1
            days = (t_sell - o[0]) / 86400
        except (ValueError, OSError):
            continue
        for i, (lim, _lab) in enumerate(BK):
            if days < lim:
                hold[i][1] += acq
                hold[i][2] += disp - acq
                hold[i][3] += 1
                break
    P = _Px(px_by_key(), today_iso)
    up = seen = elig = 0
    chg, last = [], []
    big = {}
    for lt in lots:
        if lt[3] > 0 and lt[4] > 0 and ((lt[0], lt[1]) not in big or lt[4] > big[(lt[0], lt[1])][4]):
            big[(lt[0], lt[1])] = lt
    for d, sym, sp, q, disp, _acq in big.values():
        nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if nd >= today_iso:
            continue
        elig += 1
        s9 = P.series(sp) if sp is not None else None
        if not s9 or (s9[0] == "map" and nd not in s9[1]):
            continue
        p9 = s9[1] if s9[0] == "fix" else s9[1][nd]
        r = p9 / (disp / q) - 1
        if abs(r) > 5:
            continue
        seen += 1
        chg.append(r)
        last.append(nd)
        if r > 0.01:
            up += 1
    out = {"ok": True, "since": since, "n": n, "win": w, "grid": grid,
           "hold": [{"k": h[0], "cost": round(h[1], 2), "pnl": round(h[2], 2), "n": h[3]} for h in hold],
           "next": [up, seen], "nextAvg": round(sum(chg) / len(chg) * 100, 2) if chg else None,
           "cov": {"next": round(seen / elig, 4) if elig else None, "pxAt": max(last) if last else None}, "excl": excl}
    with _LOCK:
        _CACHE["habits"] = (key, out)
    return out
