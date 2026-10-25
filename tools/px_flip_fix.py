#!/usr/bin/env python3
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import fsio, paths, statefile  # noqa: E402
import histcurve  # noqa: E402
import hl_spot  # noqa: E402
import spamguard  # noqa: E402
from view_common import EX_CANDLE_SYMS  # noqa: E402
from view_pxfix import PXB_KEYS  # noqa: E402


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _read(path: str, default):
    return statefile.read_json(path, default) if os.path.exists(path) else default


def _same(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 1e-9 * max(abs(float(a)), abs(float(b)), 1e-300)


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def store_entries(dcs: dict, hp: dict) -> list:
    out = []
    for group in ((dcs or {}).get("s"), (dcs or {}).get("o"), (hp or {}).get("specs")):
        out += [dict(e, _k=k) for k, e in (group or {}).items() if isinstance(e, dict) and isinstance(e.get("p"), dict)]
    return out


def ident_keys(db: str):
    if not db or not os.path.isfile(db):
        return None
    try:
        c = sqlite3.connect(paths.sqlite_ro_uri(db), uri=True, timeout=30)
        try:
            names = {r[0]: r[1] for r in c.execute("SELECT group_id, name FROM asset_groups")}
            rows = c.execute("SELECT group_id, kind, chain, address, symbol FROM assets WHERE group_id IS NOT NULL").fetchall()
        finally:
            c.close()
    except sqlite3.Error:
        return None
    out, has_ca, nat, has_ex = {}, set(), set(), set()
    for gid, kind, chain, addr, sym in rows:
        ks, bs = out.setdefault(str(gid), set()), {b for b in (histcurve.base_sym(sym), histcurve.base_sym(names.get(gid))) if b}
        if kind == "token" and chain and addr:
            ks.add(f"ca:{chain}:{addr if chain == 'sol' else str(addr).lower()}")
            has_ca.add(gid)
        elif kind == "exchange_currency" and ":" in str(addr or ""):
            ex9 = str(addr).split(":", 1)[0]
            has_ex.add(gid)
            m9 = {b for b in bs if b in EX_CANDLE_SYMS or (spamguard.major_of(b) == b and "USD" not in b and b != "DAI")}
            ks.update(f"sym:{b}" for b in m9 if ex9 != "hyperliquid")
            raw9 = {str(x or "").split("#", 1)[0].upper() for x in (sym, names.get(gid))} - {""}
            ks.update(f"ex:{ex9}:{b}" for b in bs | raw9 | {str(names.get(gid) or "").upper()})
            if ex9 == "hyperliquid":
                ks.update(f"sym:{hl_spot.SAME_COIN[k9][0]}" for k9 in raw9 if k9 in hl_spot.SAME_COIN)
        elif kind == "native":
            nat.add(gid)
    for gid, kind, chain, addr, sym in rows:
        if gid in nat or (gid not in has_ca and gid not in has_ex):
            out[str(gid)].update(f"sym:{b}" for b in (histcurve.base_sym(sym), histcurve.base_sym(names.get(gid))) if b)
    return out


def judge(entries: list, day: str, price: float, keys=None, hit: set = None) -> str:
    found = set()
    for e in entries:
        if keys is not None and e.get("_k") not in keys:
            continue
        if not (str(e.get("lo") or "9999") <= day <= str(e.get("hi") or "")):
            continue
        own = e["p"].get(day)
        if own:
            if _same(own, price):
                if histcurve.entry_venue(e, day) not in histcurve.DC_WEAK_VENUES:
                    return "strong"
                found.add(e.get("_k", id(e)))
            continue
        prev = max((d for d, v in e["p"].items() if v and d < day), default=None)
        if prev and len(histcurve.days_between(prev, day)) - 1 <= histcurve.FFILL_DAYS and _same(e["p"][prev], price):
            found.add(e.get("_k", id(e)))
    if hit is not None and len(found) == 1:
        hit.update(found)
    return "weak" if len(found) == 1 else ""


def plan(dpx: dict, dcache: dict, entries: list, ids=None, why: dict = None) -> list:
    out = []
    why = why if why is not None else {}
    for day in sorted(set(k for k in dpx if not str(k).startswith("_")) | set(k for k in dcache if not str(k).startswith("_"))):
        ent = dcache.get(day) if isinstance(dcache.get(day), dict) else {}
        blk = ent.get("px") if isinstance(ent.get("px"), dict) else dpx.get(day)
        if not isinstance(blk, dict):
            continue
        for sid, kind in (blk.get("k") or {}).items():
            price = (blk.get("p") or {}).get(sid)
            ref = (blk.get("fp") or {}).get(sid) or (blk.get("lp") or {}).get(sid)
            if kind != "d" or not price or not ref or float(price) <= 0 or float(ref) <= 0:
                continue
            if 1.0 / histcurve.DC_SPIKE_X <= float(price) / float(ref) <= histcurve.DC_SPIKE_X:
                continue
            keys = (ids or {}).get(str(sid))
            if not keys:
                why["noid"] = why.get("noid", 0) + 1
                continue
            hit = set()
            if judge(entries, day, float(price), keys, hit) == "weak":
                out.append((day, sid, float(price), float(ref), min(hit)))
    return out


def fix_cell(blk: dict, ent: dict, sid: str, price: float, ref: float, skip: set) -> float:
    done = ent.get("dcp") if isinstance(ent.get("dcp"), dict) else {}
    already_ref = not isinstance(ent.get("px"), dict) and bool((blk.get("fp") or {}).get(sid)) and sid not in done
    blk["p"][sid] = ref
    blk["k"].pop(sid, None)
    if isinstance(blk.get("fp"), dict):
        blk["fp"].pop(sid, None)
    blk["dcn"] = sorted(set(blk.get("dcn") or ()) | {sid}, key=lambda x: (len(x), x))
    g = ent.get("g") if isinstance(ent.get("g"), dict) else {}
    if sid not in g or already_ref:
        return 0.0
    old = float(g[sid])
    new = old * ref / price
    g[sid] = round(new, 4)
    if isinstance(ent.get("dcp"), dict):
        ent["dcp"].pop(sid, None)
    if sid in skip:
        return 0.0
    ent["val"] = round(float(ent.get("val") or 0) + new - old, 2)
    ent["est"] = round(float(ent.get("est") or 0) + abs(new), 2)
    return new - old


def apply_plan(dpx: dict, dcache: dict, cells: list) -> dict:
    skip = {x for x in str(dcache.get("_risk_rev") or "").split(",") if x}
    rep, days = {}, set()
    for day, sid, price, ref, *_k in cells:
        ent = dcache.get(day) if isinstance(dcache.get(day), dict) else {}
        src = ent.get("px") if isinstance(ent.get("px"), dict) else dpx.get(day)
        blk = json.loads(json.dumps(src))
        blk.setdefault("p", {})
        blk.setdefault("k", {})
        dv = fix_cell(blk, ent, sid, price, ref, skip)
        row = dpx.setdefault(day, {})
        for key in PXB_KEYS:
            if key in blk:
                row[key] = json.loads(json.dumps(blk[key]))
            else:
                row.pop(key, None)
        if isinstance(ent.get("px"), dict):
            ent["px"] = {key: json.loads(json.dumps(blk[key])) for key in PXB_KEYS if key in blk}
        r = rep.setdefault(sid, [0, 0.0])
        r[0] += 1
        r[1] = max(r[1], abs(dv))
        days.add(day)
    return {"groups": rep, "days": sorted(days)}


def _digits(usd: float) -> str:
    return "0" if usd < 1 else f"10^{int(math.log10(usd))}"


def _stamp(*files: str) -> tuple:
    return tuple(os.stat(f).st_mtime_ns if os.path.exists(f) else None for f in files)


@contextlib.contextmanager
def _flock(path: str):
    with open(fsio.lock_path(path), "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def _write(f_dpx: str, f_dc: str, dpx: dict, dcache: dict, stamp: tuple) -> None:
    if _stamp(f_dpx, f_dc) != stamp:
        raise SystemExit("읽은 뒤 daily_px.json·daily_cache.json 이 바뀜 — tj-web 을 멈춘 뒤 다시")
    statefile.atomic_write_json(f_dpx, dpx)
    if os.path.exists(f_dc):
        statefile.atomic_write_json(f_dc, dcache)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="날별 가격 출처 뒤집힘 1회 정정(점검 기본)")
    ap.add_argument("--state", default=None)
    ap.add_argument("--db", default=None, help="원장(읽기만 · 그룹 정체) — 기본 = state 의 ledger.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo-out", default=None)
    ap.add_argument("--undo", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.undo_out and os.path.lexists(a.undo_out):
        ap.error("--undo-out 파일이 이미 있음 — 새 경로로(덮어쓰지 않음)")
    sd = a.state or paths.STATE_DIR
    f_dpx, f_dc = os.path.join(sd, "daily_px.json"), os.path.join(sd, "daily_cache.json")
    stamp = _stamp(f_dpx, f_dc)
    dpx, dcache = _read(f_dpx, {}), _read(f_dc, {})
    if a.undo:
        return undo(a.undo, (f_dpx, f_dc, stamp), dpx, dcache, a.force)
    entries = store_entries(_read(os.path.join(sd, "daily_close_px.json"), {}), _read(os.path.join(sd, "curve_hist_px.json"), {}))
    why = {}
    cells = plan(dpx, dcache, entries, ident_keys(a.db or os.path.join(sd, "ledger.db")), why)
    before = {d: (json.loads(json.dumps(dpx.get(d))), json.loads(json.dumps(dcache.get(d)))) for d in {c[0] for c in cells}}
    rep = apply_plan(dpx, dcache, cells)
    srcs = {}
    for c9 in cells:
        srcs.setdefault(c9[1], set()).add(c9[4])
    out = {"cells": len(cells), "days": len(rep["days"]),
           "groups": {g: {"days": n, "usd_digits": _digits(u), "src": sorted(srcs.get(g) or ())}
                      for g, (n, u) in sorted(rep["groups"].items(), key=lambda kv: -kv[1][1])},
           "noid": why.get("noid", 0), "daily_cache": os.path.exists(f_dc), "applied": False}
    if a.apply and cells:
        if not a.undo_out:
            ap.error("--apply 는 --undo-out FILE 과 함께")
        undo_doc = {"v": 1, "at": int(time.time()), "days": {d: {"dpx": b[0], "dc": b[1], "dpx_h": _h(dpx.get(d)), "dc_h": _h(dcache.get(d))}
                                                             for d, b in before.items()}}
        if not fsio.create_exclusive(a.undo_out, json.dumps(undo_doc, ensure_ascii=False).encode("utf-8")):
            raise SystemExit("되돌리기 파일을 못 만듦(이미 있음) — 아무것도 안 바꿈")
        with _flock(f_dpx):
            try:
                _write(f_dpx, f_dc, dpx, dcache, stamp)
            except OSError as e:
                raise SystemExit(f"쓰기 실패({e.__class__.__name__}) — 한 파일만 바뀌었을 수 있어요. 되돌리기: --undo {a.undo_out}") from None
        out["applied"] = True
    _show(out, a.json)
    return 0


def undo(path: str, files: tuple, dpx: dict, dcache: dict, force: bool) -> int:
    doc = _read(path, None)
    days = doc.get("days") if isinstance(doc, dict) else None
    if (not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(days, dict)
            or not all(isinstance(d, str) and _DAY.fullmatch(d) and isinstance(r, dict) for d, r in days.items())):
        print("되돌림 파일 형식 이상(날 키는 YYYY-MM-DD 만):", path)
        return 1
    done, kept = 0, []
    for day, rec in sorted(days.items()):
        if not force and (_h(dpx.get(day)) not in (rec.get("dpx_h"), _h(rec.get("dpx"))) or _h(dcache.get(day)) not in (rec.get("dc_h"), _h(rec.get("dc")))):
            kept.append(day)
            continue
        for store, key in ((dpx, "dpx"), (dcache, "dc")):
            if rec.get(key) is None:
                store.pop(day, None)
            else:
                store[day] = rec[key]
        done += 1
    if done:
        with _flock(files[0]):
            _write(files[0], files[1], dpx, dcache, files[2])
    print(f"되돌림 {done}일" + (f" · 그 뒤 바뀌어 건너뜀 {len(kept)}일 {kept[:5]}(--force = 그래도)" if kept else ""))
    return 0 if not kept else 2


def _show(out: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(("고침" if out["applied"] else "점검(쓰기 없음)") + f" — 칸 {out['cells']} · 날 {out['days']} · 그룹 {len(out['groups'])}"
          + ("" if out["daily_cache"] else " · daily_cache.json 없음(daily_px 만)")
          + (f" · 그룹 정체(원장) 모름 {out['noid']}칸 = 안 고침" if out.get("noid") else ""))
    for g, r in out["groups"].items():
        print(f"  #{g} 날 {r['days']} · 하루 최대 금액 자릿수 {r['usd_digits']} · 출처 키 {', '.join(r.get('src') or ())}")


if __name__ == "__main__":
    sys.exit(main())
