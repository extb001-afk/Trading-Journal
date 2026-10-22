from __future__ import annotations
import bisect
import os
import re
import time
import num_parse, paths
import histcurve
import acct_norm
from view_common import DAYCLOSE_ON
from view_common import STABLE_GROUPS
from view_common import _ex_stable_sym
from view_common import _px_tables
import logging

log = logging.getLogger('tj-web')
from datetime import datetime
from timeutil import KST
import calcguard  # noqa: E402

try:
    import perp_dex
    PERP_NAMES = dict(perp_dex.NAMES)
except Exception as e_cg:   # noqa: BLE001 [fallback]
    calcguard.swallowed("view_fut:<module>[perp_dex]", e_cg)
    perp_dex, PERP_NAMES = None, {}

FUT_CEX = ("binance", "bybit", "okx")

PERP_KEYS = tuple(PERP_NAMES)

FUT_FEE_SYM = "선물 수수료·펀딩"

_FUT_SYM_RE = re.compile(r"[-_/]?(USDT|USDC|USD)([-_]?(SWAP|PERP|M))?$", re.I)


def fut_sym(s) -> str:
    s = str(s or "")
    b = _FUT_SYM_RE.sub("", s, count=1)
    return (b or s) + " 무기한"

FUT_T_MIN_MS = 1420070400000


def _fin(v):
    return num_parse.to_float(v, catch_overflow=True)


def _fut_notional(p):
    n9 = _fin(p.get("notional"))
    if n9 is not None and n9 > 0:
        return n9
    if str(p.get("ex") or "") == "okx":
        return None
    return float(p.get("qty") or 0) * float(p.get("mark") or 0)


def _fut_notional_sum(poss):
    v9 = [_fut_notional(p) for p in poss]
    return None if any(x is None for x in v9) else sum(v9)

_FUT_USD_SETTLE = frozenset({"USDT", "USDC", "USDG", "USD", "BUSD", "FDUSD", "USDE", "DAI", "TUSD", "PYUSD", "USD1"})


def _fut_settle(p) -> str:
    s9 = str(p.get("settle") or "").strip().upper()
    if s9:
        return s9
    if p.get("ex") == "okx":
        pt9 = str(p.get("symbol") or "").upper().split("-")
        if len(pt9) >= 3 and pt9[1] == "USD" and pt9[0] and (pt9[2] == "SWAP" or pt9[2].isdigit()):
            return pt9[0]
    return ""


def _fut_upnl_usd(p, price_fn):
    u9 = _fin(p.get("upnl") or 0)
    if u9 is None:
        return None, "미실현 값이 숫자가 아님"
    s9 = _fut_settle(p)
    if not s9 or s9 in _FUT_USD_SETTLE:
        return u9, None
    try:
        px9 = _fin(price_fn(s9)) if price_fn else None
    except Exception as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_fut:_fut_upnl_usd", _cg9)
        px9 = None
    if not px9 or px9 <= 0:
        return None, f"{s9} 정산 — {s9} 시세가 없어 달러로 못 바꿈"
    return u9 * px9, None


def perp_active():
    if perp_dex is None:
        return {}
    cfg9 = perp_dex._read_cfg()
    if cfg9 is None:
        return None
    return {k9: {a9["address"] for a9 in v9} for k9, v9 in perp_dex.configured(cfg9).items()}

PERP_AMT_MAX, PERP_NUM_MAX = 1e13, 1e15

_PERP_BAD_WARNED = set()


def _pnum(v, cap=PERP_NUM_MAX):
    x = _fin(v if v is not None else 0)
    return x if x is not None and abs(x) <= cap else None


def perp_filter(d9, on9, now9=None, ex9="?"):
    ac9 = d9.get("accts") or {}
    t_hi9 = (time.time() + 86400) * 1000
    bad9 = 0
    out = {k9: v9 for k9, v9 in d9.items() if k9 not in ("events", "positions", "accts", "cursor", "wallet")}
    evs9 = []
    for r9 in d9.get("events") or []:
        if not isinstance(r9, dict) or r9.get("acct") not in on9:
            continue
        a9, t9 = _pnum(r9.get("amount"), PERP_AMT_MAX), _fin(r9.get("t"))
        if a9 is None or t9 is None or not (FUT_T_MIN_MS <= t9 <= t_hi9):
            bad9 += 1
            continue
        evs9.append(r9)
    out["events"] = evs9
    pos9 = []
    for p9 in d9.get("positions") or []:
        if not isinstance(p9, dict) or p9.get("acct") not in on9:
            continue
        if now9 is not None and now9 - int(_fin((ac9.get(p9.get("acct")) or {}).get("ts")) or 0) > 1800:
            continue
        if any(_pnum(p9.get(k9)) is None for k9 in ("qty", "entry", "mark", "upnl", "liq")):
            bad9 += 1
            continue
        pos9.append(p9)
    out["positions"] = pos9
    w9 = {}
    for k9, v9 in (d9.get("wallet") or {}).items():
        if k9 in ("balance", "equity", "maint_margin", "margin_balance"):
            if v9 is None:
                w9[k9] = None
            elif _pnum(v9) is not None:
                w9[k9] = v9
            else:
                bad9 += 1
        elif k9 == "note" and isinstance(v9, str):
            w9[k9] = v9
    out["wallet"] = w9
    out["accts"] = {a9: m9 for a9, m9 in ac9.items() if a9 in on9}
    if bad9 and ex9 not in _PERP_BAD_WARNED:
        _PERP_BAD_WARNED.add(ex9)
        log.warning("퍼프 스냅숏 %s: 범위 밖 숫자·시각 %d건 건너뜀(표시·합류 제외)", ex9, bad9)
    return out


def fut_ev_usd(r9, price_fn):
    a9 = str((r9 or {}).get("asset") or "").strip().upper()
    if not a9 or a9 in STABLE_GROUPS or a9 in ("USD", "FDUSD", "TUSD", "USDP") or _ex_stable_sym(a9):
        return r9
    est9 = False
    try:
        px9 = price_fn(a9) if price_fn else None
        if isinstance(px9, tuple):
            px9, est9 = px9
        q9 = float(r9.get("amount") or 0)
        px9 = float(px9) if px9 is not None else None
    except (TypeError, ValueError):
        return None
    if not px9 or px9 <= 0 or px9 != px9 or q9 != q9:
        return None
    out9 = dict(r9, amount=q9 * px9, amt_native=q9)
    if est9:
        out9["px_est"] = True
    return out9

FUT_PX_NEAR_S = 86400

FUT_PX_FAR_S = 7 * 86400


def _fut_candle_past(fxb, sym, t_ms, within_s):
    if fxb is None or not fxb.candle(sym, int(t_ms) // 1000):
        return None
    ks, pts = fxb._csym[str(sym or "").upper()]
    m = (int(t_ms) // 60_000) * 60_000
    if m in pts:
        return pts[m]
    j = bisect.bisect_right(ks, m) - 1
    return pts[ks[j]] if j >= 0 and m - ks[j] <= int(within_s) * 1000 else None


def _fut_fxb(px, spot):
    fx9, c9 = _px_tables(px)
    return acct_norm.FxBook(fx9, paths.state("px_cache_core.json"), getattr(spot, "rate", None) or None, web_candle=c9)


def fut_px_at(fxb, spot_fn, now=None):
    memo9 = {}
    now = time.time() if now is None else now

    def f9(sym, t_ms):
        s9 = str(sym or "").strip().upper()
        try:
            t9 = int(t_ms or 0)
        except (TypeError, ValueError):
            t9 = 0
        k9 = (s9, t9 // 60_000)
        if k9 in memo9:
            return memo9[k9]
        p9 = None
        if t9 > 0:
            p9 = _fut_candle_past(fxb, s9, t9, FUT_PX_NEAR_S)
            if not p9 and DAYCLOSE_ON:
                try:
                    p9 = histcurve.DAYCLOSE.lookup("sym:" + histcurve.base_sym(s9), acct_norm.iso_day(t9 // 1000), now, 0.0, ask=False)[0]
                except Exception as _cg9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_fut:fut_px_at.f9", _cg9)
                    p9 = None
            if not p9:
                p9 = _fut_candle_past(fxb, s9, t9, FUT_PX_FAR_S)
        r9 = None
        try:
            if p9 and float(p9) > 0:
                r9 = (float(p9), False)
            else:
                sp9 = spot_fn(s9) if spot_fn else None
                r9 = (float(sp9), True) if sp9 and float(sp9) > 0 else (None, False)
        except (TypeError, ValueError):
            r9 = (None, False)
        memo9[k9] = r9
        return r9
    return f9


def _fut_by_date_ex(by_date_ex, exn):
    out = {}
    for (dk9, ex9), v9 in by_date_ex.items():
        if abs(v9[0]) < 0.005:
            continue
        r9 = {"ex": exn.get(ex9, ex9), "exKey": ex9, "usd": round(v9[0], 2), "krw": round(v9[1]),
              "n": v9[2], "t": datetime.fromtimestamp(v9[3] / 1000, KST).strftime("%H:%M") if v9[3] else ""}
        if v9[3]:
            r9["ts"] = int(v9[3] // 1000)
        out.setdefault(dk9, []).append(r9)
    for l9 in out.values():
        l9.sort(key=lambda x: (-abs(x["usd"]), str(x["exKey"])))
    return out
