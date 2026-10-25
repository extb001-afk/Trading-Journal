from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

import calcguard
import fsio
import histcurve
import histmark
import paths
import rabby
import statefile
import xparts
from timeutil import KST

log = logging.getLogger("tj-web")

FILE = "att_frozen.json"
V = 1
WINDOW_DAYS = 30
PREV_KEYS = ("date", "val", "valKrw", "usdt", "kimp", "est", "xc")
WRITE_GAP_S = 900
READ_CACHE_N = 64
BF_V = 3
BF_TRIES = 3
BF_PEND_TRIES = 5
BF_PEND_GAP_S = 120
MARK_SLACK_S = 600
BUILD_SLACK_S = 120
BF_PX = "att_frozen_bfpx.json"
BF_CHUNK = 29
ROW_KEEP = ("date", "dow", "val", "valKrw", "usdt", "kimp", "est", "xc", "flow", "flowTop", "rb", "rbNew", "att")
_rlock = threading.Lock()
_rcache = {"sig": None, "days": {}}


def _sig(p):
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _empty():
    return {"_v": V, "d": {}, "dm": []}


def _load(p, keep_bad=False):
    try:
        cur = statefile.read_json(p, None)
    except SystemExit:
        cur = False
    if cur is None:
        return _empty(), False
    if isinstance(cur, dict) and isinstance(cur.get("d"), dict):
        cur.setdefault("dm", [])
        return cur, False
    if keep_bad:
        bad = p + ".bad_" + str(int(time.time()))
        try:
            with open(p, "rb") as f:
                fsio.create_exclusive(bad, f.read())
            log.warning("자산 변동 분해 동결 기록 손상 — 내용을 %s 에 남기고 새로 시작", os.path.basename(bad))
        except OSError as e:
            log.warning("자산 변동 분해 동결 기록 손상 — 남기기 실패(이번 빌드 쓰기 안 함): %s", e)
            return None, True
    return _empty(), True


def _hash(rec):
    return hashlib.sha1(json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def _copy(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def _marks():
    try:
        cur = statefile.read_json(paths.state(histmark.HIST_DIRTY), None)
    except SystemExit:
        return []
    if not isinstance(cur, dict):
        return []
    return [[int(m[0]), str(m[1]), int(m[2])] for m in (cur.get("marks") or [])
            if isinstance(m, list) and len(m) >= 3 and isinstance(m[1], str)]


def _row_isos(rows, today_iso):
    day0 = datetime.strptime(today_iso, "%Y-%m-%d")
    n = len(rows)
    out = []
    for i, row in enumerate(rows):
        iso = (day0 - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d")
        out.append(iso if isinstance(row, dict) and row.get("date") == iso[5:] else None)
    return out


def records(rows: list, det: dict | None, fut: dict | None, today_iso: str, rzd: object = None) -> tuple:
    isos = _row_isos(rows, today_iso)
    det = det if isinstance(det, dict) else {}
    fut = fut if isinstance(fut, dict) else {}
    out = {}
    for i in range(1, len(rows)):
        iso, row, prev = isos[i], rows[i], rows[i - 1]
        if not iso or iso >= today_iso or not isinstance(row.get("att"), dict) or not isinstance(prev, dict):
            continue
        rec = {"r": _copy(row), "p": {k: prev.get(k) for k in PREV_KEYS if prev.get(k) is not None}}
        if isinstance(det.get(iso), dict):
            rec["det"] = _copy(det[iso])
        if isinstance(fut.get(iso), dict):
            rec["fut"] = _copy(fut[iso])
        if rzd is not None:
            rec["rzd"] = rzd(iso)
        out[iso] = rec
    return out, {i for i in isos if i}


def _index(owner, p):
    ix = owner.__dict__.get("_att_frz_ix")
    sig = _sig(p)
    if isinstance(ix, dict) and sig is not None and ix.get("sig") == sig:
        return ix
    cur, bad = _load(p)
    return {"sig": sig, "h": {k: v.get("h") for k, v in cur["d"].items() if isinstance(v, dict)},
            "dm": [list(m[:3]) for m in cur.get("dm") or [] if isinstance(m, list)], "bad": bad,
            "norzd": sorted(k for k, v in cur["d"].items() if isinstance(v, dict) and "rzd" not in v)}


def _at_s(v):
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return 0


def _mark_stale(store, new_marks, fresh, built=None, t_build=0):
    n = 0
    built = built or ()
    for mark in new_marks:
        tm = int(mark[2])
        for iso, rec in store["d"].items():
            if not isinstance(rec, dict) or iso in fresh or iso < mark[1]:
                continue
            if (t_build - tm > BUILD_SLACK_S) if iso in built else (_at_s(rec.get("at")) - tm > MARK_SLACK_S):
                continue
            if rec.get("st") != "s":
                if rec.get("st"):
                    rec["st0"] = rec["st"]
                rec["st"] = "s"
                n += 1
            rec["sx"] = min(str(rec.get("sx") or mark[1]), mark[1])
            rec["sxt"] = max(_at_s(rec.get("sxt")), tm)
    return n


def update(owner: object, rows: list, det: dict | None, fut: dict | None, today_iso: str, now: float | None = None, rzd: object = None) -> dict:
    now = int(time.time() if now is None else now)
    rep = {"new": 0, "upd": 0, "stale": 0, "wrote": False}
    if not isinstance(rows, list) or len(rows) < 2:
        return rep
    p = paths.state(FILE)
    recs, _win = records(rows, det, fut, today_iso, rzd)
    hashes = {iso: _hash(rec) for iso, rec in recs.items()}
    marks = _marks()
    snap = [m for m in (owner.__dict__.get("_att_frz_mk") or []) if (m[0], m[2]) not in {(x[0], x[2]) for x in marks}]
    owner._att_frz_mk = None
    ix = _index(owner, p)
    seen = {(int(m[0]), int(m[2])) for m in ix.get("dm") or [] if len(m) >= 3}
    new_marks = [m for m in marks + snap if (m[0], m[2]) not in seen]
    changed = [iso for iso, h in hashes.items() if ix["h"].get(iso) != h]
    fill = [d for d in ix.get("norzd") or () if d not in recs] if rzd is not None else []
    urgent = bool(new_marks or fill or ix.get("bad") or sorted((m[0], m[2]) for m in marks) != sorted(seen)
                  or any(iso not in ix["h"] for iso in changed))
    if not urgent and (not changed or now - int(ix.get("wt") or 0) < WRITE_GAP_S):
        owner._att_frz_ix = ix
        rep["held"] = len(changed)
        return rep
    with fsio.locked(p):
        store, _bad = _load(p, keep_bad=True)
        if store is None:
            return rep
        for iso in changed:
            rep["upd" if isinstance(store["d"].get(iso), dict) else "new"] += 1
            store["d"][iso] = dict(recs[iso], at=now, h=hashes[iso])
        for iso in fill:
            if isinstance(store["d"].get(iso), dict) and "rzd" not in store["d"][iso]:
                store["d"][iso]["rzd"] = rzd(iso)
        t_bf, bfd = owner.__dict__.get("_att_frz_bfd") or (0, ())
        owner._att_frz_bfd = None
        rep["stale"] = _mark_stale(store, new_marks, set(recs), {d for d in bfd if isinstance(store["d"].get(d), dict) and store["d"][d].get("st") == "b"}, t_bf)
        store["_v"], store["dm"] = V, [list(m) for m in marks]
        statefile.atomic_write_json(p, store)
    rep["wrote"] = True
    owner._att_frz_ix = {"sig": _sig(p), "h": {k: v.get("h") for k, v in store["d"].items() if isinstance(v, dict)},
                         "dm": [list(m) for m in marks], "bad": False, "wt": now, "norzd": []}
    if rep["new"] or rep["stale"]:
        log.info("자산 변동 분해 동결 기록: 새 날 %d · 갱신 %d · 정정 전 값 표식 %d", rep["new"], rep["upd"], rep["stale"])
    return rep


def note_marks(owner: object) -> None:
    try:
        owner._att_frz_bfd = None
        owner._att_frz_mk = _marks()
    except Exception as e:  # noqa: BLE001 [optional]
        calcguard.swallowed("attfreeze:note_marks", e)


def hook(owner: object, fields: dict, today_iso: str, now: float) -> None:
    try:
        idx = owner.__dict__.get("_day_idx") or {}
        fu = fields.get("futures") if isinstance(fields.get("futures"), dict) else {}
        maps = {"s": fields.get("realizedByDate"), "sk": fields.get("realizedKrwByDate"), "f": fu.get("realizedByDate"), "fk": fu.get("realizedKrwByDate")}

        def rzd(iso):
            return {k: m.get(iso, m.get(iso[5:])) for k, m in maps.items() if isinstance(m, dict) and m.get(iso, m.get(iso[5:])) is not None}
        update(owner, fields.get("dailySeries"), idx.get("attDet"), idx.get("attFut"), today_iso, now=now, rzd=rzd)
    except Exception as e:  # noqa: BLE001 [optional]
        calcguard.swallowed("attfreeze:hook", e)
        log.warning("자산 변동 분해 동결 기록 실패(화면 무관): %s", e)


def read(isos: list) -> dict:
    isos = [i for i in isos if isinstance(i, str)]
    if not isos:
        return {}
    p = paths.state(FILE)
    with _rlock:
        sig = _sig(p)
        if sig is None:
            return {}
        if _rcache["sig"] != sig:
            _rcache["sig"], _rcache["days"] = sig, {}
        miss = [i for i in isos if i not in _rcache["days"]]
        if miss:
            cur, bad = _load(p)
            days = {} if bad else cur["d"]
            if len(_rcache["days"]) + len(miss) > READ_CACHE_N:
                _rcache["days"], miss = {}, isos
            for i in miss:
                v = days.get(i)
                _rcache["days"][i] = v if isinstance(v, dict) and isinstance(v.get("r"), dict) else None
        return {i: _rcache["days"][i] for i in isos if _rcache["days"].get(i)}


def serve(days: dict, fut: dict, d_from: str, d_to: str, built_at: int | None) -> dict:
    if not built_at:
        return {}
    lo_win = (datetime.fromtimestamp(int(built_at), KST) - timedelta(days=WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
    want = []
    day = datetime.strptime(d_from, "%Y-%m-%d")
    end = min(datetime.strptime(d_to, "%Y-%m-%d"), datetime.strptime(lo_win, "%Y-%m-%d") - timedelta(days=1))
    while day <= end and len(want) <= 41:
        want.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    frz = {}
    for iso, rec in read(want).items():
        frz[iso] = {k: rec[k] for k in ("r", "p", "at", "st", "sx", "rzd") if k in rec}
        if isinstance(rec.get("det"), dict):
            days[iso] = dict(rec["det"])
        if isinstance(rec.get("fut"), dict):
            fut[iso] = rec["fut"]
    return frz


def _bf_px(dpx):
    out = {k: v for k, v in (dpx or {}).items() if str(k)[:1].isdigit() and isinstance(v, dict)}
    try:
        extra = statefile.read_json(paths.state(BF_PX), None)
    except SystemExit:
        extra = None
    for k, v in (extra if isinstance(extra, dict) else {}).items():
        if str(k)[:1].isdigit() and isinstance(v, dict) and k not in out:
            out[k] = v
    return out


def _fx_of(dpx, iso):
    try:
        return float(((dpx.get(iso) or {}).get("xv") or {}).get("fx")) or None
    except (TypeError, ValueError):
        return None


def _bf_fx(owner, dpx):
    fx_at = getattr(getattr(owner, "px", None), "fx_at", None)
    memo = {}

    def fx(ms):
        m = int(ms) // 60_000 * 60_000
        if m in memo:
            return memo[m]
        v = fx_at(int(ms)) if callable(fx_at) else None
        try:
            v = float(v or 0)
        except (TypeError, ValueError):
            v = 0.0
        if not v > 0:
            iso = datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%Y-%m-%d")
            if callable(fx_at):
                fx.miss.add(iso)
            v = _fx_of(dpx, iso)
        memo[m] = v
        return v
    fx.miss = set()
    return fx


def _bf_rows(days, G, skip, kit, dpx, flow_fn, fx_tx=None):
    days = [d for d in days if isinstance((dpx.get(d) or {}).get("p"), dict)]
    qd = histcurve.rewind(kit, days)
    sym_tl = (kit.get("xk") or {}).get("sym_tl") or {}
    src, rows = {}, {}
    for d in days:
        ent = dpx[d]
        prices = ent["p"]
        g = {}
        for gid, by_day in qd.items():
            q, grp = by_day.get(d), G.get(gid) or {}
            if q is None or grp.get("is_fiat"):
                continue
            px = 1.0 if grp.get("is_stable") else float(prices.get(str(gid)) or 0)
            if px:
                g[str(gid)] = round(q * px, 4)
        cut, rest = xparts.ub_cut(ent.get("xu") or {}, histcurve.day_end(d) - 1, sym_tl, lambda gid, _d=d: (qd.get(gid) or {}).get(_d, 0.0))
        src[d] = (g, prices, rest)
        row = {"val": round(sum(float(v) for k, v in g.items() if k not in skip) + float(ent.get("x") or 0) - cut, 2), "usdt": _fx_of(dpx, d)}
        if ent.get("xc"):
            row["xc"] = ent["xc"]
        rows[d] = row
    tabs = {d: {"p": dict(v.get("p") or {})} for d, v in dpx.items()}
    kw = {"fx_tx": fx_tx} if fx_tx is not None else {}
    flows = flow_fn(kit.get("fk") or {}, days, tabs, lambda iso: _fx_of(dpx, iso), **kw) if days else {}
    for d in days:
        fv = flows.get(d)
        rows[d]["flow"] = round(float(fv[0]), 2) if fv else 0.0
        if fv and fv[1]:
            rows[d]["flowTop"] = [list(t) for t in fv[1]][:3]
    return src, rows


def _bf_rabby(rows):
    if not rows or not os.path.exists(paths.state("rabby_daily.json")):
        return
    have = sorted(rows)
    t_ov = (datetime.strptime(have[-1], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    ov = [dict(rows[d], date=d[5:]) for d in have]
    rabby.daily_overlay(ov, rabby.load_state(paths.state("rabby_daily.json")), t_ov, 0.0)
    for d, r in zip(have, ov):
        if r.get("rbNew"):
            r["flow"] = round(float(r.get("flow") or 0) + float(r["rbNew"]), 2)
            r["flowTop"] = [["Rabby 기준 첫 반영(봇 미추적 보유)", round(float(r["rbNew"]), 2)]] + list(r.get("flowTop") or [])[:2]
        rows[d] = {k: v for k, v in r.items() if k != "date"}


def _bf_seqs(have):
    runs, cur = [], []
    for d in have:
        if cur and (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(cur[-1], "%Y-%m-%d")).days != 1:
            runs.append(cur)
            cur = []
        cur.append(d)
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        i = 1
        while i < len(run):
            out.append(run[i - 1:i + BF_CHUNK - 1])
            i += BF_CHUNK - 1
    return out


def _bf_call(owner, conn, ctx, seq, src, rows, fx_tx=None):
    G, today_kst, live_px, skip_gids, extra, real, px_src = ctx
    last = datetime.strptime(seq[-1], "%Y-%m-%d") + timedelta(days=1)
    t_shift = today_kst.replace(year=last.year, month=last.month, day=last.day, hour=12, minute=0, second=0, microsecond=0)
    keep = {k: owner.__dict__.get(k) for k in ("_att_by_today", "_att_det_new", "_daily_att_src", "_flow_px_delta", "_daily_lpc", "_flow_det", "_att_fx_at",
                                               "_flow_att_px", "_flow_att_rep")}
    try:
        owner._daily_att_src, owner._flow_px_delta, owner._daily_lpc, owner._flow_det = src, {}, {}, None
        owner._flow_att_px, owner._flow_att_rep = {}, {}
        owner._att_fx_at = fx_tx
        att = owner._daily_attrib(conn, [dict(rows[d], date=d[5:]) for d in seq], G, t_shift, live_px, skip_gids, extra, real=real, px_src=px_src)
        det = dict(owner.__dict__.get("_att_det_new") or {})
    finally:
        for k, v in keep.items():
            owner.__dict__[k] = v
        if keep["_att_fx_at"] is None:
            owner.__dict__.pop("_att_fx_at", None)
    md = {d[5:]: d for d in seq}
    return {md[k]: v for k, v in att.items() if k in md}, det


def bf_records(owner: object, conn: object, ctx: tuple, mats: tuple, days: list, now: float) -> dict:
    kit, dpx, flow_fn = mats
    days = sorted(set(days))
    if not days:
        return {}
    skip = {str(x) for x in (ctx[3] or ())}
    prevs = {(datetime.strptime(d, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d") for d in days}
    fx_tx = _bf_fx(owner, dpx)
    src, rows = _bf_rows(sorted(set(days) | prevs), ctx[0], skip, kit, dpx, flow_fn, fx_tx)
    _bf_rabby(rows)
    out = {}
    for seq in _bf_seqs(sorted(rows)):
        att, det = _bf_call(owner, conn, ctx, seq, src, rows, fx_tx)
        for j in range(1, len(seq)):
            d, pd = seq[j], seq[j - 1]
            if d not in att or d not in days:
                continue
            r = dict(rows[d], date=d[5:], dow="일월화수목금토"[int(datetime.strptime(d, "%Y-%m-%d").strftime("%w"))], att=att[d])
            pv = dict(rows[pd], date=pd[5:])
            for x in (r, pv):
                if x.get("usdt"):
                    x["valKrw"] = round(float(x["val"]) * float(x["usdt"]))
            rec = {"r": _copy({k: r[k] for k in ROW_KEEP if k in r}), "p": {k: pv[k] for k in PREV_KEYS if pv.get(k) is not None},
                   "det": _copy(det.get(d) or {}), "st": "b"}
            if d in fx_tx.miss:
                rec["fxp"] = 1
            out[d] = dict(rec, at=int(now), h=_hash(rec))
    return out


def _bf_want(rec):
    return rec is None or (isinstance(rec, dict) and rec.get("st") == "b")


def backfill(owner: object, conn: object, kit_fn: object, ctx: tuple | None, now: float | None = None, *,
             records_fn: object = None, flow_fn: object = None) -> dict:
    now = int(time.time() if now is None else now)
    rep = {"n": 0}
    if owner.__dict__.get("_att_frz_bf") == BF_V:
        return rep
    try:
        p = paths.state(FILE)
        store, bad = _load(p)
        if isinstance(store.get("bf"), dict) and store["bf"].get("v") == BF_V:
            owner._att_frz_bf = BF_V
            return rep
        bf = store.get("bf") if isinstance(store.get("bf"), dict) else {}
        flow_fn = flow_fn or histcurve.HIST.flow_fn
        if (ctx is None or bad or flow_fn is None or bf.get("v") == BF_V or int(bf.get("tries") or 0) >= BF_TRIES
                or not os.path.exists(paths.state("backfill_done"))
                or (bf.get("pw") and now - int(bf.get("at") or 0) < BF_PEND_GAP_S)):
            return rep
        lo_win = (ctx[1] - timedelta(days=WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
        dpx = _bf_px(owner.__dict__.get("daily_px"))
        days = [d for d in dpx if d <= lo_win and _bf_want(store["d"].get(d)) and isinstance(dpx[d].get("p"), dict)]
        recs = (records_fn or bf_records)(owner, conn, ctx, (kit_fn(), dpx, flow_fn), days, now) if days else {}
        with fsio.locked(p):
            store, _bad = _load(p, keep_bad=True)
            if store is None:
                return rep
            bf = store.get("bf") if isinstance(store.get("bf"), dict) else {}
            rep["re"] = 0
            done = set()
            for d, rec in recs.items():
                if _bf_want(store["d"].get(d)):
                    rep["re"] += d in store["d"]
                    store["d"][d] = rec
                    rep["n"] += 1
                    done.add(d)
            pend = sorted(d for d in done if store["d"][d].get("fxp"))
            pw = int(bf.get("pw") or 0) + 1 if pend else 0
            if pend and pw <= BF_PEND_TRIES:
                store["bf"] = {"v": 0, "pw": pw, "at": now, "n": rep["n"], "want": len(days), "re": rep["re"], "pend": len(pend),
                               "tries": int(bf.get("tries") or 0)}
                rep["pend"] = len(pend)
            else:
                store["bf"] = {"v": BF_V, "at": now, "n": rep["n"], "want": len(days), "re": rep["re"]}
                if pend:
                    store["bf"]["fb"] = len(pend)
            statefile.atomic_write_json(p, store)
        if not rep.get("pend"):
            owner._att_frz_bf = BF_V
        owner._att_frz_bfd = (int(ctx[1].timestamp()), done)
        log.info("자산 변동 분해 동결 기록 복원: %d일(옛 세대 다시 계산 %d일 · 후보 %d일 — 30일 창 밖 · 일별 가격 보관 안)%s", rep["n"], rep["re"], len(days),
                 " · 그 시각 환율 대기 %d일 — 미완(다음 빌드 다시 %d/%d)" % (rep["pend"], pw, BF_PEND_TRIES) if rep.get("pend") else "")
    except Exception as e:  # noqa: BLE001 [optional]
        calcguard.swallowed("attfreeze:backfill", e)
        log.warning("자산 변동 분해 동결 기록 복원 실패(화면 무관): %s", e)
        try:
            with fsio.locked(paths.state(FILE)):
                store, _bad = _load(paths.state(FILE), keep_bad=True)
                if store is not None:
                    bf = store.get("bf") if isinstance(store.get("bf"), dict) else {}
                    store["bf"] = dict(bf, v=0, tries=int(bf.get("tries") or 0) + 1, err=str(e)[:200], at=now)
                    statefile.atomic_write_json(paths.state(FILE), store)
        except Exception as e2:  # noqa: BLE001 [optional]
            calcguard.swallowed("attfreeze:backfill[tries]", e2)
    return rep
