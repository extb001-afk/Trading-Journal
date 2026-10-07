from __future__ import annotations

import math
import re

EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "hyperliquid": "하이퍼리퀴드",
         "dydx": "dYdX", "lighter": "Lighter", "gmx": "GMX", "jupiter": "Jupiter", "pacifica": "Pacifica"}
PROD_KO = {"margin_cross": "교차마진", "margin_isolated": "격리마진", "loan": "담보대출", "futures_linear": "선물",
           "futures_inverse": "선물(코인 정산)", "unified": "통합계정"}
KIND_OF = {"margin_cross": "margin", "margin_isolated": "margin", "unified": "margin", "loan": "loan",
           "futures_linear": "fut", "futures_inverse": "fut"}
STATE_RANK = {"danger": 0, "warn": 1, "unknown": 2, "nothr": 3, "safe": 4}
UNCONF = ("no_permission", "error", "rate_limited", "stale", "not_collected")
REASON_KO = {"no_permission": "키 권한 없음", "error": "조회 실패", "rate_limited": "API 한도 대기", "stale": "값이 낡음",
             "not_collected": "아직 안 모음", "unsupported": "공개 API 없음", "not_opened": "계정 안 열림"}
PRIMARY = ("ltv", "margin_level", "debt_ratio", "risk_rate", "mgn_ratio", "mm_rate", "liq_dist")
ACCT_PRODS = {("binance", "futures_linear"), ("binance", "futures_inverse")}
FUT_FRESH = 1800
QUOTE_RX = re.compile(r"[-_/]?(USDT|USDC|USD|BUSD|FDUSD)(?:[-_]?(SWAP|PERP|M)|[-_]\d{6})?$", re.I)


def _f(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def base_of(sym) -> str:
    s = str(sym or "").strip()
    b = QUOTE_RX.sub("", s)
    b = b.split("-")[0] if "-" in b else b
    return (b or s).upper()


def _pct1(x) -> str:
    v = abs(x) * 100
    return f"{v:.1f}%" if v < 20 else f"{v:.0f}%"


def _ratio_txt(v, unit) -> str:
    if v is None:
        return "—"
    if unit == "frac":
        return f"{v * 100:.1f}%"
    return f"{v:.2f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}"


def _day_rate(rate, period):
    if rate is None or period not in ("hour", "day", "year"):
        return None
    return rate * 24 if period == "hour" else rate if period == "day" else rate / 365.0


def _year_rate(rate, period):
    if rate is None or period not in ("hour", "day", "year"):
        return None
    return rate * 24 * 365 if period == "hour" else rate * 365 if period == "day" else rate


def _risk_space(m):
    v, call, liq, warn = _f(m.get("v")), _f(m.get("call")), _f(m.get("liq")), _f(m.get("warn"))
    inv = lambda x: (1.0 / x) if x and x > 0 else None
    if m.get("inf"):
        return (0.0, inv(call), inv(liq), inv(warn)) if m.get("risk") == "down" else (0.0, call, liq, warn)
    if v is None:
        return None, None, None, None
    if m.get("risk") == "down":
        return inv(v), inv(call), inv(liq), inv(warn)
    return v, call, liq, warn


def judge_metric(m):
    r, call_r, liq_r, warn_r = _risk_space(m)
    if r is None:
        return "nothr", None
    if m.get("thr_src") == "unknown" or not (call_r or liq_r):
        return "nothr", None
    c = call_r or (warn_r if m.get("risk") == "up" and warn_r else None)
    if c:
        st = "danger" if r >= c else "warn" if r >= 0.9 * c else "safe"
    else:
        st = "danger" if r >= 0.9 * liq_r else "warn" if r >= 0.8 * liq_r else "safe"
    scale = liq_r or (c * 1.1)
    g = {"fill": max(0.0, min(1.0, r / scale)) if scale else 0.0}
    if c:
        g["at"], g["atKind"] = max(0.0, min(1.0, c / scale)), "call"
    elif liq_r:
        g["at"], g["atKind"] = 0.8, "warn"
    return st, g


def _side_of(v):
    s9 = str(v or "").strip().upper()
    return s9 if s9 in ("LONG", "SHORT") else None


def pos_dist(mark, liq, side):
    mark, liq = _f(mark), _f(liq)
    if mark is None or liq is None or mark <= 0 or liq <= 0 or side not in ("LONG", "SHORT"):
        return None
    return max(0.0, ((mark - liq) if side == "LONG" else (liq - mark)) / mark)


def judge_fut(d, th):
    if d is None:
        return "nothr", None
    warn_d = 2 * th
    span = max(0.5, 2.5 * warn_d)
    st = "danger" if d <= th else "warn" if d <= warn_d else "safe"
    return st, {"fill": max(0.0, min(1.0, 1 - d / span)), "at": max(0.0, min(1.0, 1 - warn_d / span)), "atKind": "warn",
                "warnD": warn_d}


def _bump(st, off):
    lv = (off or {}).get("level") if isinstance(off, dict) else None
    if not isinstance(lv, int) or st == "unknown":
        return st
    want = "danger" if lv >= 2 else "warn" if lv >= 1 else None
    if want and STATE_RANK[want] < STATE_RANK.get(st, 9):
        return want
    return st


def _liq_key(row):
    ex, kind = row["ex"], row["kind"]
    if kind == "fut":
        return ("fut", f"{ex}:{row.get('sym')}:{row.get('side')}:{row.get('acct') or ''}")
    p, key = row.get("product"), row.get("key") or ""
    if ex == "binance" and p == "margin_cross":
        return ("risk", "binance:margin:cross")
    if ex == "binance" and p == "margin_isolated":
        return ("risk", f"binance:iso:{key}")
    if ex == "binance" and p == "loan" and "-" in key:
        lc, cc = key.split("-", 1)
        return ("risk", f"binance:loan:{lc}:{cc}")
    if ex == "okx" and p == "loan":
        return ("risk", f"okx:loan:{key}")
    if ex == "bybit" and p == "loan":
        return ("risk", "bybit:loan:all")
    return (None, None)


SENT_KO = {("fut", 1): "소리 알림 보냄", ("fut", 2): "더 가까워져 한 번 더 보냄",
           ("risk", 1): "소리 알림 보냄", ("risk", 2): "긴급 알림 보냄(마진콜)", ("risk", 3): "긴급 알림 보냄(청산 임박)"}


def _sent(row, liq_mem):
    if not isinstance(liq_mem, dict):
        return None
    g, k = _liq_key(row)
    if row.get("kind") == "fut":
        g, keys = "fut", [k, f"{row['ex']}:{row.get('sym')}:{row.get('side')}:lev"]
    else:
        g, keys = "risk", [row.get("id"), k]
    mem = liq_mem.get(g)
    e = next((mem[x] for x in keys if x and isinstance(mem.get(x), dict)), None) if isinstance(mem, dict) else None
    if not isinstance(e, dict):
        return None
    st = int(_f(e.get("st")) or 0)
    if st <= 0:
        return None
    return {"st": st, "at": int(_f(e.get("at")) or 0), "label": SENT_KO.get((g, min(st, 3 if g == "risk" else 2)), "알림 보냄")}


def _debt_rows(it, price):
    out, usd, day, part = [], 0.0, 0.0, False
    for d in it.get("debt") or []:
        ccy, tot = str(d.get("ccy") or ""), _f(d.get("total"))
        if not ccy or tot is None:
            part = True
            continue
        p = price(ccy)
        dr = _day_rate(_f(d.get("rate")), d.get("rate_period"))
        yr = _year_rate(_f(d.get("rate")), d.get("rate_period"))
        row = {"ccy": ccy, "total": tot, "principal": _f(d.get("principal")), "interest": _f(d.get("interest")),
               "usd": tot * p if p else None, "yr": yr, "dayUsd": (tot * p * dr) if (p and dr is not None) else None}
        if p:
            usd += tot * p
        else:
            part = True
        if row["dayUsd"] is not None:
            day += row["dayUsd"]
        else:
            part = True
        out.append(row)
    return out, usd, day, part


def _gauge_lbls(m, g, st):
    name = {"ltv": "LTV", "margin_level": "마진 레벨", "debt_ratio": "부채 비율", "risk_rate": "위험률", "mgn_ratio": "증거금 비율",
            "mm_rate": "유지증거금률"}.get(m.get("_name"), "")
    now = f"{name} {_ratio_txt(_f(m.get('v')), m.get('unit'))}".strip() if not m.get("inf") else f"{name} 부채 없음"
    call, liq, warn = _f(m.get("call")), _f(m.get("liq")), _f(m.get("warn"))
    ck = f"콜 {_ratio_txt(call, m.get('unit'))}" if call is not None else (f"경고 {_ratio_txt(warn, m.get('unit'))}" if warn is not None and m.get("risk") == "up" else "")
    lq = f"청산 {_ratio_txt(liq, m.get('unit'))}" if liq is not None else ""
    return {"now": now, "mark": ck, "end": lq}


def _drop_txt(m, coll):
    v, call, liq, warn = _f(m.get("v")), _f(m.get("call")), _f(m.get("liq")), _f(m.get("warn"))
    if v is None or v <= 0:
        return None, None, None
    who = f"{coll} 가" if coll else "담보가"
    if m.get("risk") == "up" and m.get("_name") in ("ltv", "debt_ratio"):
        c = call if call is not None else (warn if m.get("_name") == "debt_ratio" else None)
        dc = (1 - v / c) if c else None
        dl = (1 - v / liq) if liq else None
    elif m.get("risk") == "down" and m.get("_name") in ("margin_level", "mgn_ratio", "risk_rate"):
        dc = (1 - call / v) if call else None
        dl = (1 - liq / v) if liq else None
    else:
        return None, None, None
    if dl is not None and dl <= 0:
        return "청산 기준에 닿았어요", dc, dl
    if dc is not None and dc <= 0:
        return ("마진콜 도달 · " + (f"{who} {_pct1(dl)} 더 내리면 청산이에요" if dl is not None else "청산 기준은 거래소가 주지 않아요")), dc, dl
    parts = []
    if dc is not None:
        parts.append(f"{who} {_pct1(dc)} 내리면 마진콜")
    if dl is not None:
        parts.append(f"{_pct1(dl)} 내리면 청산" if parts else f"{who} {_pct1(dl)} 내리면 청산")
    if not parts:
        return None, dc, dl
    return ", ".join(parts) + "이에요", dc, dl


def _metric_of(it):
    ms = it.get("metrics") or {}
    for k in PRIMARY:
        if isinstance(ms.get(k), dict):
            return dict(ms[k], _name=k)
    return None


def _risk_row(it, prod_ok, price, now, th=0.1):
    ex, p = it.get("ex"), it.get("product")
    kind = KIND_OF.get(p, "margin")
    m = _metric_of(it)
    fresh = bool(it.get("fresh")) and prod_ok
    debts, dusd, dday, part = _debt_rows(it, price)
    coll = [c for c in (it.get("collateral") or []) if isinstance(c, dict) and c.get("ccy")]
    coll_name = coll[0]["ccy"] if kind == "loan" and len(coll) == 1 else None
    if not fresh:
        st, g = "unknown", None
    elif m is None:
        st, g = "nothr", None
    else:
        st, g = judge_metric(m)
    ldm = (it.get("metrics") or {}).get("liq_dist")
    pair_dist = _f(ldm.get("v")) if isinstance(ldm, dict) else None
    pp9 = it.get("position") if isinstance(it.get("position"), dict) else None
    if pp9 is not None and pair_dist is not None:
        pair_dist = pos_dist(pp9.get("mark"), pp9.get("liq"), _side_of(pp9.get("side")))
    if fresh and pair_dist is not None:
        sd, gd = judge_fut(pair_dist, th)
        if st == "nothr" or STATE_RANK.get(sd, 9) < STATE_RANK.get(st, 9):
            st, g = sd, gd
    if fresh:
        st = _bump(st, it.get("official_state"))
    lbl = _gauge_lbls(m, g, st) if m else {"now": "", "mark": "", "end": ""}
    drop, dc, dl = _drop_txt(m, coll_name) if m else (None, None, None)
    if ex == "binance" and p == "margin_cross" and (it.get("raw") or {}).get("accountType") != "MARGIN_1" and m and m.get("_name") == "margin_level":
        dc = dc if (dc is not None and dc <= 0) else None
        dl = dl if (dl is not None and dl <= 0) else None
        drop = ("청산 기준에 닿았어요" if dl is not None else
                "마진콜 도달 · 청산까지 남은 폭은 계산하지 않아요(계정 종류별 식)" if dc is not None else None)
    elif m and m.get("_name") == "mgn_ratio":
        dc = dc if (dc is not None and dc <= 0) else None
        dl = dl if (dl is not None and dl <= 0) else None
        v9, l9 = _f(m.get("v")), _f(m.get("liq"))
        drop = ("청산 기준에 닿았어요" if dl is not None else
                "마진콜 도달 · 청산까지 남은 폭은 계산하지 않아요(증거금 비율 기준)" if dc is not None else
                (f"증거금 비율 {_ratio_txt(v9, 'x')}배" + (f" — {_ratio_txt(l9, 'x')}배 이하면 청산돼요" if l9 is not None else "")) if v9 is not None else None)
    if m and m.get("_name") == "mm_rate":
        drop = f"유지증거금률 {_ratio_txt(_f(m.get('v')), 'frac')} — 100%에 닿으면 청산돼요" if _f(m.get("v")) is not None else None
    who = f"{coll_name} " if coll_name else "담보 "
    if m and m.get("_name") == "mm_rate":
        short = "100%면 청산" if _f(m.get("v")) is not None else None
    elif m and m.get("_name") == "mgn_ratio" and dc is None and dl is None:
        short = f"증거금 비율 {_ratio_txt(_f(m.get('v')), 'x')}배" if _f(m.get("v")) is not None else None
    elif dl is not None and dl <= 0:
        short = "청산 기준 도달"
    elif dc is not None and dc <= 0:
        short = "마진콜 도달" + (f" · {_pct1(dl)} 더 내리면 청산" if dl is not None else "")
    elif dc is not None:
        short = f"{who}{_pct1(dc)} 내리면 마진콜"
    elif dl is not None:
        short = f"{who}{_pct1(dl)} 내리면 청산"
    else:
        short = None
    title_k = PROD_KO.get(p, p)
    if p == "margin_isolated":
        title_k = f"격리마진 {it.get('key') or ''}".strip()
    elif it.get("scope") == "ccy":
        title_k = f"교차 증거금 {it.get('key') or ''}".strip()
    thr = m.get("thr_src") if m else "unknown"
    row = {"id": it.get("id"), "kind": kind, "ex": ex, "exKo": EX_KO.get(ex, ex), "product": p, "kindKo": title_k,
           "key": it.get("key"), "measuredAt": it.get("measured_at"), "fresh": fresh, "state": st, "gauge": g, "lbl": lbl,
           "metric": ({"name": m.get("_name"), "v": _f(m.get("v")), "inf": bool(m.get("inf")), "unit": m.get("unit"), "risk": m.get("risk"),
                       "warn": _f(m.get("warn")), "call": _f(m.get("call")), "liq": _f(m.get("liq")), "txt": lbl["now"]} if m else None),
           "thr": thr_kind(thr),
           "drop": drop, "dropShort": short, "dropCall": dc, "dropLiq": dl, "debts": debts, "debtUsd": dusd if debts else 0.0, "dayUsd": dday if debts else 0.0,
           "dayPartial": part, "coll": [{"ccy": c["ccy"], "qty": _f(c.get("qty"))} for c in coll],
           "official": it.get("official_state"), "note": it.get("note"),
           "liqPx": _f((it.get("raw") or {}).get("liqPx")), "liqPair": (it.get("raw") or {}).get("liqPair")}
    if p == "margin_isolated" and isinstance((it.get("metrics") or {}).get("liq_dist"), dict):
        row["pairDist"] = pair_dist
    return row


def thr_kind(thr) -> str:
    t = str(thr or "")
    return ("api" if t.startswith("api:") else "doc" if t.startswith("doc:") else "tj" if t.startswith("tj:")
            else "config" if t.startswith("config:") else "unknown")


def _acct_of(acct_mm, ex, prod, sym):
    if prod == "futures_inverse":
        return acct_mm.get((ex, prod, base_of(sym)))
    return acct_mm.get((ex, prod))


def _okx_file_prod(sym):
    parts = str(sym or "").split("-")
    if len(parts) == 3 and (parts[2] == "SWAP" or parts[2].isdigit()):
        return "futures_linear" if parts[1] in ("USDT", "USDC", "USDG") else "futures_inverse" if parts[1] == "USD" else None
    return None


def _fut_row(ex, prod, pos, measured, fresh, extra, th, price, now, acct_mm=None):
    side = _side_of(pos.get("side"))
    mark, liq = _f(pos.get("mark")), _f(pos.get("liq"))
    liq = liq if liq and liq > 0 else None
    d = pos_dist(mark, liq, side)
    mode = extra.get("mode") or pos.get("margin_mode")
    acct_used, mgn_used, acct_miss, mode_miss = False, None, False, False
    if side is None or _f(pos.get("qty")) is None:
        fresh = False
    if not fresh:
        st, g = "unknown", None
    else:
        st, g = judge_fut(d, th)
        if mode != "isolated" and (ex, prod) in ACCT_PRODS:
            if isinstance(acct_mm, dict):
                sa, ga = judge_metric(dict(acct_mm, _name="mm_rate"))
                if STATE_RANK.get(sa, 9) < STATE_RANK.get(st, 9):
                    st, g, acct_used = sa, ga, True
            elif STATE_RANK.get(st, 9) > STATE_RANK["unknown"]:
                st, g, acct_miss = "unknown", None, True
        elif isinstance(acct_mm, dict) and mode == "cross":
            sa, ga = judge_metric(dict(acct_mm, _name="mm_rate"))
            if STATE_RANK.get(sa, 9) < STATE_RANK.get(st, 9):
                st, g, acct_used = sa, ga, True
        pm9 = (extra.get("metrics") or {}).get("mgn_ratio") if isinstance(extra.get("metrics"), dict) else None
        if isinstance(pm9, dict) and _f(pm9.get("v")) is not None:
            sp9, gp9 = judge_metric(dict(pm9, _name="mgn_ratio"))
            if STATE_RANK.get(sp9, 9) < STATE_RANK.get(st, 9):
                st, g, mgn_used = sp9, gp9, _f(pm9.get("v"))
        if extra.get("mode_conflict") and STATE_RANK.get(st, 9) > STATE_RANK["unknown"]:
            st, g, mode_miss = "unknown", None, True
        st = _bump(st, extra.get("official"))
    base = base_of(pos.get("symbol"))
    settle = str(pos.get("settle") or extra.get("settle") or ("USDT" if ex in ("binance", "bybit", "kucoin", "gate") and prod == "futures_linear" else "")).upper()
    upnl = _f(pos.get("upnl"))
    if upnl is not None and prod == "futures_inverse":
        p9 = price(settle or base)
        upnl_usd = upnl * p9 if p9 else None
    else:
        upnl_usd = upnl
    lev = _f(pos.get("leverage"))
    if side is None:
        drop = "포지션 방향을 모름 — 청산까지 거리를 계산하지 않아요"
    elif d is None:
        drop = ("교차 포지션 — 청산은 선물 계정 위험률 기준이라 청산가가 없어요" if mode == "cross" and ex == "kucoin"
                else "거래소가 청산가를 주지 않아요(낮은 레버리지·교차 증거금이면 0 으로 와요)")
    elif d <= 0:
        drop = f"{base} 가 청산가를 지났어요 — 청산이 진행 중일 수 있어요"
    else:
        drop = f"{base} 가 {_pct1(d)} 더 {'내리면' if side == 'LONG' else '오르면'} 청산돼요"
    short = (("청산가 지남" if d <= 0 else f"{base} {_pct1(d)} 더 {'내리면' if side == 'LONG' else '오르면'} 청산") if d is not None
             else "방향 모름" if side is None else ("청산가 없음(교차)" if mode == "cross" else "청산가 없음"))
    sgn = "−" if side == "LONG" else "+"
    lbl = {"now": ("청산가 지남" if d <= 0 else f"청산까지 {sgn}{_pct1(d)}") if d is not None else "청산가 없음",
           "mark": f"주의 {sgn}{_pct1(g['warnD'])}" if g and "warnD" in g else "", "end": "청산"}
    am = _f(acct_mm.get("v")) if isinstance(acct_mm, dict) else None
    if mgn_used is not None:
        drop = f"증거금 비율 {mgn_used:.2f}배 — 1배 이하면 청산돼요(거래소 기준)"
        short = f"증거금 비율 {mgn_used:.2f}배"
        mc9 = _f((((extra.get("metrics") or {}).get("mgn_ratio")) or {}).get("call"))
        lbl = {"now": f"증거금 비율 {mgn_used:.2f}", "mark": f"경고 {mc9:g}" if mc9 else "", "end": "청산 1"}
    if acct_used and am is not None:
        drop = f"계정 유지증거금률 {am * 100:.1f}% — 100%면 이 계정의 교차 포지션이 청산돼요"
        short = f"계정 유지증거금률 {am * 100:.0f}%"
        c9 = _f(acct_mm.get("call"))
        lbl = {"now": f"유지증거금률 {am * 100:.1f}%", "mark": f"콜 {c9 * 100:.0f}%" if c9 else "", "end": "청산 100%"}
    if acct_miss:
        drop = "교차 포지션 — 계정 유지증거금률을 확인 못 해 판정을 보류해요(청산가 거리만으로 안전이라 하지 않아요)"
        short = "계정 위험률 모름(교차)"
    if mode_miss:
        drop = "증거금 방식(교차·격리)이 조회마다 달라 확인 못 해 판정을 보류해요(청산가 거리만으로 안전이라 하지 않아요)"
        short = "증거금 방식 확인 못 함"
    return {"id": f"{ex}:{prod}:position:{pos.get('symbol')}:{side}:{extra.get('acct') or ''}", "kind": "fut", "ex": ex,
            "exKo": EX_KO.get(ex, ex), "product": prod, "kindKo": PROD_KO.get(prod, "선물"), "sym": pos.get("symbol"), "base": base,
            "side": side, "acct": extra.get("acct") or "", "measuredAt": int(measured or 0), "fresh": fresh, "state": st, "gauge": g,
            "lbl": lbl, "dist": d, "drop": drop, "dropShort": short, "qty": _f(pos.get("qty")), "qtyUnit": pos.get("qty_unit") or extra.get("qty_unit") or ("contract" if ex == "okx" else "coin"),
            "entry": _f(pos.get("entry")), "mark": mark, "liq": liq, "lev": lev, "mode": mode, "upnlUsd": upnl_usd,
            "official": extra.get("official"), "acctMm": am, "metric": None, "thr": (thr_kind((acct_mm or {}).get("thr_src")) if acct_used else thr_kind((((extra.get("metrics") or {}).get("mgn_ratio")) or {}).get("thr_src"))
                    if mgn_used is not None else "doc" if d is not None else "unknown"),
            "debts": [], "debtUsd": 0.0, "dayUsd": 0.0, "dayPartial": False, "coll": [], "note": extra.get("note")}


def build(lev: dict, futs: dict, price, th_liq_pct: float = 10.0, liq_mem: dict | None = None, now: float = 0.0) -> dict:
    lev = lev if isinstance(lev, dict) else {"missing": True, "products": [], "items": []}
    futs = futs if isinstance(futs, dict) else {}
    th = max(0.001, float(th_liq_pct or 10.0) / 100.0)
    prods = [p for p in (lev.get("products") or []) if isinstance(p, dict)]
    pmap = {(p.get("ex"), p.get("product")): p for p in prods}
    ok = lambda ex, pr: (pmap.get((ex, pr)) or {}).get("status_eff") == "ok"
    rows = []
    acct_mm, acct_mm_at = {}, {}
    lev_pos = {}
    for it in lev.get("items") or []:
        if not isinstance(it, dict):
            continue
        p = it.get("product")
        if it.get("scope") == "position":
            pos = it.get("position") or {}
            lev_pos[(it.get("ex"), str(pos.get("symbol")), str(pos.get("side")))] = it
            continue
        if p in ("futures_linear", "futures_inverse") and it.get("scope") == "account":
            mm9 = (it.get("metrics") or {}).get("mm_rate")
            if isinstance(mm9, dict) and _f(mm9.get("v")) is not None and it.get("fresh") and ok(it.get("ex"), p):
                ak9 = (it.get("ex"), p, str(it.get("key") or "").upper()) if p == "futures_inverse" else (it.get("ex"), p)
                acct_mm[ak9] = dict(mm9)
                acct_mm_at[ak9] = _f(it.get("measured_at")) or 0.0
            continue
        rows.append(_risk_row(it, ok(it.get("ex"), p), price, now, th))
    used = set()
    for ex, doc in futs.items():
        if not isinstance(doc, dict):
            continue
        dex = isinstance(doc.get("accts"), dict) or ex not in ("binance", "bybit", "okx")
        fts = _f(doc.get("ts")) or 0.0
        if fts > 1e11:
            fts /= 1000.0
        w9 = doc.get("wallet") if isinstance(doc.get("wallet"), dict) else {}
        if ex == "binance" and w9.get("mm_scope") == "cross" and now - fts <= FUT_FRESH:
            mt9, mb9 = _f(w9.get("maint_margin")), _f(w9.get("margin_balance"))
            if mt9 is not None and mt9 >= 0 and mb9 is not None and fts > acct_mm_at.get((ex, "futures_linear"), 0.0):
                mr9 = 0.0 if mt9 <= 1e-12 else round(mt9 / mb9, 6) if mb9 > 1e-12 else 10.0
                acct_mm[(ex, "futures_linear")] = {"v": mr9, "unit": "frac", "risk": "up", "call": 0.8, "liq": 1.0,
                                                   "thr_src": "doc:바이낸스 교차 Margin Ratio(100% = 청산 · 80% 아래 유지 권장)",
                                                   "src": "futures_binance.json wallet(교차)"}
                acct_mm_at[(ex, "futures_linear")] = fts
        for pos in doc.get("positions") or []:
            if not isinstance(pos, dict) or _f(pos.get("qty")) == 0:
                continue
            side = _side_of(pos.get("side")) or "?"
            if dex:
                acct = str(pos.get("acct") or "")
                mts = _f(((doc.get("accts") or {}).get(acct) or {}).get("ts")) or 0.0
                rows.append(_fut_row(ex, "futures_linear", pos, mts, now - mts <= FUT_FRESH, {"acct": acct}, th, price, now))
                continue
            fprod = _okx_file_prod(pos.get("symbol")) if ex == "okx" else "futures_linear"
            if fprod is None:
                continue
            k = (ex, str(pos.get("symbol")), side)
            li = lev_pos.get(k)
            lprod = li.get("product") if li else fprod
            lpp = pmap.get((ex, lprod)) or {}
            lmeas = _f(lpp.get("measured_at")) or 0.0
            if li is not None:
                used.add(k)
                lmeas_i = _f(li.get("measured_at")) or 0.0
                lpos = dict(li.get("position") or {})
                extra = {"official": li.get("official_state"), "mode": lpos.get("margin_mode"), "note": li.get("note"),
                         "qty_unit": lpos.get("qty_unit"), "settle": lpos.get("settle"), "metrics": li.get("metrics")}
                fmode = pos.get("margin_mode") if "margin_mode" in pos else lpos.get("margin_mode")
                if (now - fts <= FUT_FRESH and fmode in ("cross", "isolated") and lpos.get("margin_mode") in ("cross", "isolated")
                        and fmode != lpos.get("margin_mode")):
                    extra["mode_conflict"] = True
                if fts > lmeas_i and now - fts <= FUT_FRESH:
                    if not li.get("fresh") or lpp.get("status_eff") != "ok":
                        extra = dict(extra, official=None, metrics=None)
                    extra = dict(extra, mode=fmode)
                    rows.append(_fut_row(ex, lprod, dict(lpos, **{k9: pos.get(k9) for k9 in ("qty", "entry", "mark", "upnl", "leverage", "liq")}, margin_mode=fmode),
                                         fts, True, extra, th, price, now, _acct_of(acct_mm, ex, lprod, pos.get("symbol"))))
                else:
                    rows.append(_fut_row(ex, lprod, lpos, lmeas_i, bool(li.get("fresh")) and lpp.get("status_eff") == "ok", extra, th, price, now,
                                         _acct_of(acct_mm, ex, lprod, lpos.get("symbol"))))
                continue
            if lpp.get("status_eff") == "ok" and lmeas >= fts:
                continue
            rows.append(_fut_row(ex, fprod, pos, fts, now - fts <= FUT_FRESH, {}, th, price, now, _acct_of(acct_mm, ex, fprod, pos.get("symbol"))))
    for k, li in lev_pos.items():
        if k in used:
            continue
        lpos = li.get("position") or {}
        pr = li.get("product")
        lpp = pmap.get((li.get("ex"), pr)) or {}
        rows.append(_fut_row(li.get("ex"), pr, lpos, _f(li.get("measured_at")) or 0, bool(li.get("fresh")) and lpp.get("status_eff") == "ok",
                             {"official": li.get("official_state"), "mode": lpos.get("margin_mode"), "note": li.get("note"),
                              "qty_unit": lpos.get("qty_unit"), "settle": lpos.get("settle"), "metrics": li.get("metrics")}, th, price, now,
                             _acct_of(acct_mm, li.get("ex"), pr, lpos.get("symbol"))))
    for r in rows:
        r["sent"] = _sent(r, liq_mem)
    rows.sort(key=lambda r: (STATE_RANK.get(r["state"], 9), -((r.get("gauge") or {}).get("fill") or 0.0), r.get("exKo") or "", str(r.get("id"))))
    unconf, unsup = [], []

    def reason(p, st):
        nt = str(p.get("note") or "").split(" — ")[0].strip()
        if nt and (st in ("unsupported", "not_collected") or (st == "no_permission" and not nt.startswith("키 권한"))):
            return re.sub(r"\((?:일반|선물 조회|공개)[^)]*\)?$", "", nt).strip()[:60]
        return REASON_KO.get(st, st)
    for p in prods:
        st = p.get("status_eff") or p.get("status")
        if st in UNCONF:
            unconf.append({"ex": p.get("ex"), "exKo": EX_KO.get(p.get("ex"), p.get("ex")), "product": p.get("product"),
                           "productKo": PROD_KO.get(p.get("product"), p.get("product")), "status": st, "reason": reason(p, st),
                           "at": p.get("measured_at")})
        elif st in ("unsupported", "not_opened"):
            unsup.append({"ex": p.get("ex"), "exKo": EX_KO.get(p.get("ex"), p.get("ex")), "product": p.get("product"),
                          "productKo": PROD_KO.get(p.get("product"), p.get("product")), "status": st, "reason": reason(p, st)})
    exs = sorted({p.get("ex") for p in prods if p.get("status") != "no_key"})
    cnt = {s: sum(1 for r in rows if r["state"] == s) for s in STATE_RANK}
    tabs = {"all": len(rows), "fut": sum(1 for r in rows if r["kind"] == "fut"), "margin": sum(1 for r in rows if r["kind"] == "margin"),
            "loan": sum(1 for r in rows if r["kind"] == "loan")}
    debt_rows = [r for r in rows if r["debts"] and r["state"] != "unknown"]
    day_rows = [r for r in rows if r["debts"]]
    fut_rows = [r for r in rows if r["kind"] == "fut"]
    return {"v": 1, "ts": int(now), "missing": bool(lev.get("missing")), "levTs": lev.get("ts"), "exchanges": len(exs),
            "thLiq": th, "rows": rows, "counts": dict(cnt, open=len(rows), unconfirmed=len(unconf), unsupported=len(unsup)), "tabs": tabs,
            "debtUsd": sum(r["debtUsd"] for r in day_rows) if day_rows else None,
            "dayUsd": sum(r["dayUsd"] for r in day_rows) if day_rows else None,
            "dayPartial": any(r["dayPartial"] for r in day_rows),
            "debtStale": len(debt_rows) != len(day_rows),
            "upnlUsd": (sum(r["upnlUsd"] for r in fut_rows if r.get("upnlUsd") is not None)
                        if any(r.get("upnlUsd") is not None for r in fut_rows) else None),
            "upnlPartial": any(r.get("upnlUsd") is None for r in fut_rows),
            "unconfirmed": unconf, "unsupported": unsup}
