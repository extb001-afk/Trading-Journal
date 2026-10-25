import hashlib
import json
import os
import threading
import time
from decimal import Decimal as D

import _harness as T

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.environ["TJ_REPLAY_DEBUG"] = "1"
os.environ.setdefault("TJ_BUILD_PROC", "off")
WA = "0x" + "cd" * 20
WB = "0x" + "ce" * 20
CFG0 = {"chains": {}, "backfill_months": 5,
        "wallets": [{"type": "evm", "chain": "base", "address": WA, "label": "a"},
                    {"type": "evm", "chain": "arbitrum", "address": WA, "label": "a"},
                    {"type": "evm", "chain": "bsc", "address": WA, "label": "a"},
                    {"type": "evm", "chain": "base", "address": WB, "label": "b"}]}
CFG_PATH = os.path.join(T.TMP, "config.json")
json.dump(CFG0, open(CFG_PATH, "w"))
os.environ["TJ_CONFIG"] = CFG_PATH
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
import paths  # noqa: E402
import config  # noqa: E402
import statefile  # noqa: E402
import core  # noqa: E402
import db  # noqa: E402
import web  # noqa: E402
from exf_net import norm_fill, norm_row  # noqa: E402,F401

FX = [1400.0]
NOW = int(time.time())
PX = {"USDT": 1., "USDC": 1., "ETH": 2000., "BNB": 100., "BTC": 50000.}
PXF = [None]


def _px(sym, ts_ms):
    if PXF[0]:
        v = PXF[0](sym, int(ts_ms) // 1000 if ts_ms and ts_ms > 1e11 else ts_ms)
        if v is not None:
            return v
    return PX.get(sym)


def _fx_ms(ms=None):
    return float(FXF[0](int(ms) // 1000)) if (FXF[0] and ms) else FX[0]


def _noop(*a, **k):
    return None


def _cand_only(sym, ts_ms, chain, ca, cand=None):
    return cand


def _fake_px(px_cache):
    px_cache.candle_usd = _px
    px_cache.fx_at = _fx_ms
    px_cache.token_usd_checked = _cand_only
    return px_cache


FXF = [None]


def _seed_tables(px_cache, conn):
    mins = {int(r[0]) * 1000 // 60_000 * 60_000 for r in conn.execute("SELECT DISTINCT event_ts FROM postings")}
    syms = {str(r[0] or "").upper() for r in conn.execute("SELECT DISTINCT symbol FROM assets")} | set(PX)
    for m in mins:
        px_cache.d["fx"][str(m)] = _fx_ms(m)
        for sym in syms:
            v = _px(sym, m) if sym else None
            if v:
                px_cache.d["candle"][f"{sym}:{m}"] = float(v)


_C = [None]


def _join_bg_db():
    for t9 in threading.enumerate():
        if t9 is not threading.current_thread() and t9.name == "rawfrom-worker" and t9.is_alive():
            t9.join(120)
            if t9.is_alive():
                raise RuntimeError("배경 원장 읽기(rawfrom-worker)가 120초 안에 안 끝남 — 원장 파일을 지우지 않음")


def reset(cfg_extra=None, px=None, pxf=None):
    _join_bg_db()
    if _C[0] is not None:
        try:
            _C[0].conn.close()
        except Exception:  # noqa: BLE001
            pass
        _C[0] = None
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(paths.DB_PATH + suf):
            os.remove(paths.DB_PATH + suf)
    if os.path.isdir(paths.STATE_DIR):
        for fn in os.listdir(paths.STATE_DIR):
            p = os.path.join(paths.STATE_DIR, fn)
            if os.path.isfile(p) and fn.endswith(".json"):
                os.remove(p)
    json.dump(dict(CFG0, **(cfg_extra or {})), open(CFG_PATH, "w"))
    PX.clear()
    PX.update(px or {"USDT": 1., "USDC": 1., "ETH": 2000., "BNB": 100., "BTC": 50000.})
    PXF[0] = pxf
    FX[0] = 1400.0
    FXF[0] = None
    _C[0] = core.Core(config.load_config())
    _fake_px(_C[0].px)
    return _C[0]


def hx(tag):
    return "0x" + hashlib.sha256(str(tag).encode()).hexdigest()


class Ch:

    def __init__(self, c):
        self.c = c
        self.dec = {}

    def tok(self, chain, addr, sym, d, kind="token"):
        a = self.c.asset_id(kind, chain, addr, symbol=sym, decimals=d)
        self.c.conn.execute("UPDATE assets SET confirmed=1, decimals=? WHERE asset_id=?", (d, a))
        self.dec[a] = d
        return a

    def tx(self, chain, tag, ts, legs, ev, wallet=WA, txh=None):
        t = txh or hx(tag)
        for i, L in enumerate(legs):
            a, q, lk, cst = L[:4]
            loc = L[4] if len(L) > 4 and L[4] else f"wallet:{chain}:{wallet}"
            qb = int(round(D(str(q)) * D(10) ** self.dec[a]))
            self.c._post_leg("chain_tx", chain, t, i, ts, a, loc, qb, None if cst is None else repr(float(cst)), None, lk, ev)
        self.c.conn.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,'{}',5)", (chain, t, ev))
        return t


def ex(exchange, **kw):
    _C[0].svc_exf._consume_ex(dict({"exchange": exchange}, **kw))


def fills(exchange, fl):
    _C[0].svc_exf._consume_exf_fills({"exchange": exchange, "fills": fl})


def fills_upbit(*orders):
    _C[0].svc_exf._consume_fills({"orders": list(orders)})


def build(prefs=None):
    c = _C[0]
    c.conn.commit()
    c.conn.close()
    _C[0] = None
    statefile.atomic_write_json(paths.state("spot.json"), {
        "usd": PX, "usd_ts": {s: NOW for s in PX}, "rate": FX[0], "updated": NOW, "fx_basis": FX[0],
        "ex_usd": {f"{e}:{s}": p for s, p in PX.items() for e in ("binance", "okx", "bybit", "upbit", "bithumb")},
        "ex_ts": {f"{e}:{s}": NOW for s in PX for e in ("binance", "okx", "bybit", "upbit", "bithumb")}})
    statefile.atomic_write_json(paths.state("ui_prefs.json"), dict({"plans": {}, "ignored": []}, **(prefs or {})))
    b = web.StateBuilder()
    _fake_px(b.px)
    co = db.open_db(paths.DB_PATH, readonly=True)
    try:
        _seed_tables(b.px, co)
    finally:
        co.close()
    b._sale_worker = b._xchain_worker = b._lp_worker = b._origin_worker = b._flow_worker = _noop
    b.skip_gen_check = True
    cap = []
    o = b._build_replay

    def cb(conn):
        rr = o(conn)
        cap.append(rr)
        return rr
    b._build_replay = cb
    co = db.open_db(paths.DB_PATH, readonly=True)
    try:
        f = b._build(co)["fields"]
    finally:
        co.close()
    _join_bg_db()
    rr = cap[-1] if cap else None
    return f, (rr.G if rr is not None else {}), rr


def realized(f):
    return sum(float(v) for v in (f.get("realizedByDate") or {}).values())


def tax_sum(f):
    return sum(float(r.get("_disp", r.get("disp")) or 0) - float(r.get("_acq", r.get("acq")) or 0) - float(r.get("_fee", r.get("fee")) or 0)
               for r in (f.get("_taxRowsAll") or []))


def cost_end(G):
    return sum(float(g["cost"]) for g in G.values())


def stable_qty(G):
    return sum(float(g["qty_known"] + g["qty_unknown"]) for g in G.values() if g.get("is_stable"))


def unknown(G, eps=D("0.000001")):
    return {f"{g['sym']}#{gid}": float(g["qty_unknown"]) for gid, g in G.items() if g["qty_unknown"] > eps}


def gas_expense(f):
    return sum(float(v.get("usd", 0) if isinstance(v, dict) else 0) for v in (f.get("gasExpenseByDate") or {}).values())
