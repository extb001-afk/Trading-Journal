"""Producers for optional Telegram alerts (daily PnL, price moves, big flows, LP range, depeg, liquidation)."""
from __future__ import annotations

import logging
import os
import statistics
import time
from datetime import datetime, timedelta, timezone

import alert_prefs as AP
import common

KST = timezone(timedelta(hours=9))
log = logging.getLogger("tj-web")
STATE_PATH = os.path.join(common.STATE_DIR, "alert_watch.json")
COOL = 6 * 3600
LP_HYST = 600
LP_COOL = 3600
PX_EVERY = 300
PX_KEEP = 25 * 3600
PX_FLOOR_USD = 100.0
BUILD_MAX_AGE = 6 * 3600
LIVE_PX_AGE = 900
PNL_FRESH = 90 * 60
PNL_WAIT = 2 * 3600
EX_KEY = {"바이낸스": "binance", "업비트": "upbit", "바이빗": "bybit", "게이트": "gate", "빗썸": "bithumb", "쿠코인": "kucoin", "OKX": "okx"}
GLOBAL_EX = ("binance", "bybit", "okx", "gate", "kucoin")
EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "gate": "게이트", "kucoin": "쿠코인", "bithumb": "빗썸", "upbit": "업비트",
         "hyperliquid": "하이퍼리퀴드", "lighter": "라이터", "aster": "애스터"}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def money(usd, cur="KRW", rate=None, sign=False) -> str:
    v = _f(usd)
    if v is None:
        return "—"
    sg = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    a = abs(v)
    r = _f(rate)
    if cur != "USD" and r and r > 0:
        w = a * r
        if w >= 1e8:
            return f"{sg}₩{w / 1e8:,.2f}억"
        if w >= 1e4:
            return f"{sg}₩{w / 1e4:,.0f}만"
        return f"{sg}₩{w:,.0f}"
    if a >= 1000:
        return f"{sg}${a:,.0f}"
    return f"{sg}${a:,.2f}"


def px_txt(p) -> str:
    v = _f(p)
    if v is None:
        return "—"
    if v >= 100:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:,.4f}"
    return f"${v:.6g}"


def pct_txt(p, d=1) -> str:
    v = _f(p) or 0.0
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{d}f}%"


def _kst(now):
    return datetime.fromtimestamp(now, KST)


DOW = "월화수목금토일"


def _md(iso: str) -> str:
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.month:02d}-{d.day:02d}({DOW[d.weekday()]})"
    except (TypeError, ValueError):
        return str(iso)


def _alert(kind, text, **kw):
    d = {"ts": int(time.time()), "kind": kind, "cat": AP.cat_of(kind), "text": text}
    d.update(kw)
    return d


def load_state() -> dict:
    try:
        st = common.read_json(STATE_PATH, {}) or {}
    except (Exception, SystemExit):
        st = {}
    return st if isinstance(st, dict) else {}


def save_state(st: dict) -> None:
    common.atomic_write_json(STATE_PATH, st)


def pnl_text(out, cur="KRW") -> str | None:
    f = (out or {}).get("fields") or {}
    iso, key = out.get("todayIso"), out.get("todayKey")
    ds = [r for r in (f.get("dailySeries") or []) if isinstance(r, dict)]
    rate = _f(f.get("rate"))
    if not iso or not ds:
        return None
    idx = next((i for i, r in enumerate(ds) if r.get("date") == key), None)
    if idx is None or idx == 0:
        return None
    row, prev = ds[idx], ds[idx - 1]
    val, pval = _f(row.get("val")), _f(prev.get("val"))
    if val is None or pval is None:
        return None
    att = row.get("att") if isinstance(row.get("att"), dict) else {}
    flow = _f(row.get("flow")) or 0.0
    kx = _f(att.get("kx")) or 0.0
    mk = _f(att.get("ev")) if att.get("ev") is not None else ((_f(att.get("mk")) or 0.0) - kx)
    krw = cur != "USD" and rate
    if krw:
        pk = _f(prev.get("valKrw"))
        delta = val * rate - (pk if pk is not None else pval * rate)
        fx = (pval * rate - pk if pk is not None else 0.0) + kx * rate
        parts = [("시세", (mk or 0.0) * rate), ("입출금", flow * rate), ("환율", fx)]
        to_txt = lambda w, s=True: money(w / rate, cur, rate, s)
    else:
        delta = val - pval
        parts = [("시세", mk or 0.0), ("입출금", flow), ("환율", kx)]
        to_txt = lambda u, s=True: money(u, "USD", None, s)
    etc = delta - sum(p[1] for p in parts)
    rz = _f((f.get("realizedByDate") or {}).get(iso)) or 0.0
    fut = _f(((f.get("futures") or {}).get("realizedByDate") or {}).get(iso)) or 0.0
    rz_k = rz * rate if krw else rz
    fut_k = fut * rate if krw else fut
    bt = _f(out.get("builtAt"))
    lines = [f"📊 {_md(iso)} 일간 손익" + (f" ({_kst(bt).strftime('%H:%M')} 기준)" if bt else "")]
    lines.append(f"실현 {to_txt(rz_k + fut_k)}" + (f" (현물 {to_txt(rz_k)} · 선물 {to_txt(fut_k)})" if abs(fut) >= 0.005 else ""))
    seg = [f"{n} {to_txt(v)}" for n, v in parts if abs(v) >= (1 if not krw else 1000)]
    if abs(etc) >= (1 if not krw else 1000):
        seg.append(f"그 밖 {to_txt(etc)}")
    lines.append(f"총자산 {to_txt(delta)}" + (" — " + " · ".join(seg) if seg else ""))
    top = [t for t in (att.get("top") or []) if isinstance(t, (list, tuple)) and len(t) >= 3 and _f(t[2]) is not None]
    top = sorted(top, key=lambda t: -abs(_f(t[2])))[:3]
    if top:
        lines.append("많이 움직인 코인: " + " · ".join(
            f"{t[0]} {pct_txt(t[1]) if _f(t[1]) is not None else ''} ({to_txt(_f(t[2]) * (rate if krw else 1))})".replace("  ", " ")
            for t in top))
    return "\n".join(lines)


def _pnl_target(doc, p, now):
    hh, mm = (int(x) for x in str(doc["th"]["pnl_time"]).split(":"))
    t = _kst(now)
    for back in (0, 1):
        d = t - timedelta(days=back)
        iso = d.strftime("%Y-%m-%d")
        sched = d.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
        if sched <= now < sched + PNL_WAIT and iso not in (p.get("sent"), p.get("skip")):
            return iso, sched
    return None


def prod_pnl(inp, doc, st, now, conn, on):
    p = st.setdefault("pnl", {})
    if not on:
        p.pop("wait", None)
        return []
    tgt = _pnl_target(doc, p, now)
    w = p.get("wait")
    if w and (not tgt or tgt[0] != w):
        if w not in (p.get("sent"), p.get("skip")):
            p["skip"] = w
            log.info("일간 손익 요약 %s 건너뜀 — 보낼 시각부터 %d시간 안에 그날 게시 결과가 새로 나오지 않았어요", w, PNL_WAIT // 3600)
        p.pop("wait", None)
    if not tgt:
        return []
    iso, sched = tgt
    out = inp.get("out")
    bt = _f((out or {}).get("builtAt")) or 0.0
    if not out or out.get("todayIso") != iso or bt < sched - PNL_FRESH:
        if p.get("wait") != iso:
            p["wait"] = iso
            log.info("일간 손익 요약 %s 대기 — 게시 결과가 %s(90분 넘게 낡음/다른 날) · 2시간까지 매분 다시 봐요", iso,
                     _kst(bt).strftime("%m-%d %H:%M") if bt else "없음")
        return []
    txt = pnl_text(out, inp.get("cur") or "KRW")
    p["sent"] = iso
    p.pop("wait", None)
    return [_alert("PNL_DAILY", txt, day=iso)] if txt else []


def _rev_lines(r, cur):
    s = str(r.get("s") or "—")
    note = str(r.get("note") or "").strip()
    body = str((r.get("sumKrw") if cur != "USD" and r.get("sumKrw") else r.get("sum")) or "").strip()
    two = [x for x in (note, body) if x][:2]
    return s, [x[:220] + ("…" if len(x) > 220 else "") for x in two]


def prod_review(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    revs = f.get("reviews") if isinstance(f.get("reviews"), dict) else None
    if revs is None or not out.get("todayIso"):
        return []
    today = datetime.strptime(out["todayIso"], "%Y-%m-%d")
    want = {(today - timedelta(days=i)).strftime("%m-%d"): (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in (0, 1)}
    r9 = st.setdefault("review", {})
    seen = r9.setdefault("seen", [])
    first = not r9.get("init")
    res = []
    for k, iso in sorted(want.items(), key=lambda x: x[1]):
        r = revs.get(k)
        if not isinstance(r, dict) or r.get("auto") or not (r.get("note") or r.get("sum")):
            continue
        if iso in seen:
            continue
        seen.append(iso)
        at = _f(r.get("at"))
        if first or not on or (at and now - at > 86400):
            continue
        g, two = _rev_lines(r, inp.get("cur") or "KRW")
        res.append(_alert("REVIEW_DAILY", "\n".join([f"📝 AI 일간 복기 도착 · {_md(iso)} · {g}"] + two + [inp.get("link_daily") or "보기: 일별 기록 탭"]), day=iso))
    r9["seen"] = seen[-20:]
    r9["init"] = 1
    return res


def prod_weekly(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    ws = f.get("reviewsWeekly") if isinstance(f.get("reviewsWeekly"), dict) else None
    if ws is None or not out.get("todayIso"):
        return []
    lo = (datetime.strptime(out["todayIso"], "%Y-%m-%d") - timedelta(days=8)).strftime("%Y-%m-%d")
    w9 = st.setdefault("weekly", {})
    seen = w9.setdefault("seen", [])
    first = not w9.get("init")
    res = []
    for k in sorted(ws):
        r = ws[k]
        if not isinstance(r, dict) or r.get("auto") or not (r.get("note") or r.get("sum")) or str(r.get("to") or "") < lo:
            continue
        if k in seen:
            continue
        seen.append(k)
        at = _f(r.get("at"))
        if first or not on or (at and now - at > 2 * 86400):
            continue
        g, two = _rev_lines(r, inp.get("cur") or "KRW")
        rng = f"{_md(r.get('from'))}~{_md(r.get('to'))}" if r.get("from") and r.get("to") else k
        res.append(_alert("REVIEW_WEEKLY", "\n".join([f"📘 주간 복기 도착 · {rng} · {g}"] + two + [inp.get("link_daily") or "보기: 일별 기록 탭"]), week=k))
    w9["seen"] = seen[-20:]
    w9["init"] = 1
    return res


def live_px(c, spot, now):
    if not spot:
        return None
    src, sym = str(c.get("pxSrc") or ""), str(c.get("sym") or "")
    p = ts = None
    if src == "cex:글로벌":
        p, ts = (spot.get("usd") or {}).get(sym), (spot.get("usd_ts") or {}).get(sym)
    elif src.startswith("cex:") and EX_KEY.get(src[4:]):
        k = f"{EX_KEY[src[4:]]}:{sym}"
        p, ts = (spot.get("ex_usd") or {}).get(k), (spot.get("ex_ts") or {}).get(k)
    elif src.startswith("dex") and c.get("ck") and c.get("ca"):
        k = f"{c['ck']}:{c['ca']}"
        p, ts = (spot.get("dex_usd") or {}).get(k), (spot.get("dex_ts") or {}).get(k)
    p, ts = _f(p), _f(ts)
    if not p or p <= 0 or not ts or now - ts > LIVE_PX_AGE:
        return None
    return p


def _thin(s, now):
    out, last = [], None
    for x in s:
        if now - x[0] <= 7200 or last is None or x[0] - last >= 1500:
            out.append(x)
            if now - x[0] > 7200:
                last = x[0]
    return out


def _near(samples, t, tol):
    best = None
    for ts, p in samples:
        d = abs(ts - t)
        if d <= tol and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def prod_move(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    if not out or now - float(out.get("builtAt") or 0) > BUILD_MAX_AGE:
        return []
    th = doc["th"]
    t1, t24, vmin = float(th["move_1h"]), float(th["move_24h"]), float(th["move_min"])
    mv = st.setdefault("move", {})
    hist = mv.setdefault("px", {})
    last = mv.setdefault("last", {})
    spot = inp.get("spot") or {}
    build_fresh = now - float(out.get("builtAt") or 0) <= LIVE_PX_AGE
    res, alive = [], set()
    for c in f.get("coins") or []:
        if not isinstance(c, dict) or not c.get("key"):
            continue
        qty, bp = _f(c.get("qty")) or 0.0, _f(c.get("price")) or 0.0
        if qty <= 0 or bp <= 0:
            continue
        p = live_px(c, spot, now)
        if p is not None and not (0.2 <= p / bp <= 5):
            p = None
        if p is None:
            if not build_fresh:
                continue
            p = bp
        val = qty * p
        if val < PX_FLOOR_USD:
            continue
        k = c["key"]
        alive.add(k)
        s = [x for x in (hist.get(k) or []) if isinstance(x, list) and len(x) == 2 and now - x[0] <= PX_KEEP]
        if not s or now - s[-1][0] >= PX_EVERY:
            s.append([int(now), p])
        hist[k] = _thin(s, now)
        if not on or val < vmin:
            continue
        p1, p24 = _near(s, now - 3600, 900), _near(s, now - 86400, 2700)
        c1 = (p / p1 - 1) * 100 if p1 else None
        c24 = (p / p24 - 1) * 100 if p24 else None
        hit = (c1 is not None and abs(c1) >= t1) or (c24 is not None and abs(c24) >= t24)
        if not hit or now - float(last.get(k) or 0) < COOL:
            continue
        last[k] = int(now)
        up = (c1 if c1 is not None and abs(c1) >= t1 else c24) > 0
        bits = ([f"1시간 {pct_txt(c1)}"] if c1 is not None else []) + ([f"24시간 {pct_txt(c24)}"] if c24 is not None else [])
        cur, rate = inp.get("cur") or "KRW", _f(f.get("rate"))
        res.append(_alert("PRICE_MOVE", f"{'📈' if up else '📉'} {c.get('sym')} {' · '.join(bits)} — 지금 {px_txt(p)} · 보유 {money(val, cur, rate)}",
                          sym=c.get("sym"), key=k))
    for k in list(hist):
        if k not in alive:
            del hist[k]
    for k in list(last):
        if now - float(last[k] or 0) > PX_KEEP:
            del last[k]
    return res


def prod_bigflow(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    if not out or now - float(out.get("builtAt") or 0) > BUILD_MAX_AGE:
        return []
    key, iso = out.get("todayKey"), out.get("todayIso")
    row = next((r for r in (f.get("dailySeries") or []) if isinstance(r, dict) and r.get("date") == key), None)
    bf = st.setdefault("bigflow", {})
    first = not bf.get("init")
    bf["init"] = 1
    seen = bf.setdefault("seen", {})
    for k9 in [k9 for k9 in seen if not str(k9).startswith(str(iso) + "|")]:
        del seen[k9]
    if not row:
        return []
    nmin = float(doc["th"]["flow_min"])
    cur, rate = inp.get("cur") or "KRW", _f(f.get("rate"))
    res = []
    for it in row.get("flowTop") or []:
        if not isinstance(it, (list, tuple)) or len(it) < 2 or _f(it[1]) is None:
            continue
        desc, usd = str(it[0]), _f(it[1])
        k = f"{iso}|{desc}"
        prev = _f(seen.get(k))
        if abs(usd) < nmin or (prev is not None and abs(usd - prev) < nmin):
            continue
        seen[k] = usd
        if first or not on:
            continue
        res.append(_alert("BIG_FLOW", f"{'💰 큰 입금' if usd > 0 else '💸 큰 출금'} 감지 · {desc} {money(usd, cur, rate, True)}"
                                      f" (오늘 입출금 합계 {money(_f(row.get('flow')) or 0, cur, rate, True)})", day=iso))
    return res


def prod_lprange(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    if not out or now - float(out.get("builtAt") or 0) > BUILD_MAX_AGE or not isinstance(f.get("lps"), list):
        return []
    mem = st.setdefault("lp", {})
    xm = st.setdefault("lp_x", {})
    cur, rate = inp.get("cur") or "KRW", _f(f.get("rate"))
    res, alive = [], set()
    ok_st = ("범위 내", "범위 이탈")
    for lp in f["lps"]:
        if not isinstance(lp, dict) or lp.get("closed") or not lp.get("key") or lp.get("status") not in ok_st:
            continue
        k, s = lp["key"], lp["status"]
        alive.add(k)
        a = mem.get(k)
        x = xm.get(k) if isinstance(xm.get(k), dict) else {}
        if a not in ok_st:
            mem[k], xm[k] = s, {"s": s, "at": 0}
            continue
        conf = x.get("s") if x.get("s") in ok_st else a
        if s == conf:
            x.pop("c", None)
            x.pop("cs", None)
        elif x.get("c") != s:
            x["c"], x["cs"] = s, int(now)
        if x.get("c") == s and now - float(x.get("cs") or now) >= LP_HYST:
            conf = s
            x.pop("c", None)
            x.pop("cs", None)
        x["s"] = conf
        xm[k] = x
        if conf == a:
            continue
        if not on:
            mem[k] = conf
            continue
        if now - float(x.get("at") or 0) < LP_COOL:
            continue
        s = conf
        mem[k], x["at"] = s, int(now)
        name = f"{lp.get('dex') or 'LP'} {lp.get('pool') or ''} ({lp.get('chain') or ''} #{lp.get('id') or ''})".replace("  ", " ")
        val = _f(lp.get("value"))
        res.append(_alert("LP_RANGE", (f"⚠️ LP 범위 이탈 · {name}" if s == "범위 이탈" else f"✅ LP 범위 복귀 · {name}")
                          + (f" — 범위 {lp.get('range')}" if lp.get("range") else "") + (f" · 평가 {money(val, cur, rate)}" if val is not None else ""),
                          key=k, status=s))
    for k in list(mem):
        if k not in alive:
            del mem[k]
    for k in list(xm):
        if k not in alive:
            del xm[k]
    return res


def stable_quotes(spot, syms, now, max_age=1800) -> dict:
    ex, ts = (spot or {}).get("ex_usd") or {}, (spot or {}).get("ex_ts") or {}
    out = {}
    for s in syms:
        v = [_f(ex.get(f"{e}:{s}")) for e in GLOBAL_EX if now - (_f(ts.get(f"{e}:{s}")) or 0) <= max_age]
        v = [x for x in v if x and 0.5 < x < 1.5]
        if v:
            out[s] = statistics.median(v)
    return out


def prod_depeg(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    spot = inp.get("spot")
    if not spot:
        return []
    th = float(doc["th"]["depeg_pct"])
    held = {str(c.get("sym") or "").upper() for c in (f.get("stables") or []) if isinstance(c, dict)
            and (_f(c.get("qty")) or 0) * (_f(c.get("price")) or 1) >= 100}
    syms = (held | {"USDC", "USD1", "FDUSD", "USDE", "PYUSD"}) - {"USDT", ""}
    q = stable_quotes(spot, sorted(syms), now)
    devs = {}
    if len(q) >= 3:
        m = statistics.median(q.values())
        if abs(m - 1) * 100 >= th:
            devs["USDT"] = 1 / m
    if "USDT" not in devs:
        for s, p in q.items():
            if abs(p - 1) * 100 >= th:
                devs[s] = p
    mem = st.setdefault("depeg", {})
    res = []
    for s, p in devs.items():
        e = mem.get(s) or {}
        if now - float(e.get("at") or 0) >= COOL:
            mem[s] = {"at": int(now), "px": p}
            if on:
                note = " (다른 스테이블들이 함께 벗어나 USDT 쪽으로 판단)" if s == "USDT" else ""
                res.append(_alert("DEPEG", f"🟠 스테이블 디페그 · {s} {px_txt(p)} ({pct_txt((p - 1) * 100, 2)} · 기준 ±{th:g}%){note}"
                                           + (" · 보유 중" if s in held or s == "USDT" else ""), sym=s))
    for s in list(mem):
        if s in devs:
            continue
        p = q.get(s) if s != "USDT" else None
        rec = (p is not None and abs(p - 1) * 100 < th / 2) or (s == "USDT" and len(q) >= 3)
        if rec:
            del mem[s]
            if on:
                res.append(_alert("DEPEG", f"✅ 스테이블 회복 · {s}" + (f" {px_txt(p)}" if p else ""), sym=s))
    return res


def prod_liq(inp, doc, st, now, conn, on):
    fu = inp.get("futures")
    if not isinstance(fu, dict):
        return []
    th = float(doc["th"]["liq_pct"])
    mem = st.setdefault("liq", {})
    cur, rate = inp.get("cur") or "KRW", _f(((inp.get("out") or {}).get("fields") or {}).get("rate"))
    res, alive = [], set()
    for ex, d in fu.items():
        if not isinstance(d, dict):
            continue
        ts = _f(d.get("ts")) or 0
        if ts > 1e11:
            ts /= 1000
        if now - ts > 1800:
            continue
        for p in d.get("positions") or []:
            if not isinstance(p, dict):
                continue
            liq, mark = _f(p.get("liq")), _f(p.get("mark"))
            if not liq or not mark or liq <= 0 or mark <= 0:
                continue
            dist = abs(liq - mark) / mark * 100
            k = f"{ex}:{p.get('symbol')}:{p.get('side')}:{p.get('acct') or ''}"
            alive.add(k)
            if dist > th or now - float(mem.get(k) or 0) < COOL:
                continue
            mem[k] = int(now)
            if not on:
                continue
            side = {"long": "롱", "short": "숏", "LONG": "롱", "SHORT": "숏", "Buy": "롱", "Sell": "숏"}.get(str(p.get("side")), str(p.get("side") or ""))
            upnl = _f(p.get("upnl"))
            res.append(_alert("LIQ_NEAR", f"🚨 선물 청산가 근접 · {EX_KO.get(ex, ex)} {p.get('symbol')} {side}"
                                          f" — 현재 {px_txt(mark)} · 청산가 {px_txt(liq)} ({dist:.1f}% 남음 · 기준 {th:g}%)"
                                          + (f" · 레버리지 {p.get('leverage')}x" if p.get("leverage") else "")
                                          + (f" · 미실현 {money(upnl, cur, rate, True)}" if upnl is not None else ""), key=k))
    for k in list(mem):
        if k not in alive and now - float(mem[k] or 0) > COOL:
            del mem[k]
    return res


def prod_oa(inp, doc, st, now, conn, on):
    v = inp.get("oa")
    if not isinstance(v, dict) or not v.get("ok"):
        return []
    mem = st.setdefault("oa", {})
    brk = mem.setdefault("brk", {})
    stl = mem.setdefault("stale", {})
    res = []
    for b in v.get("brokers") or []:
        if not isinstance(b, dict) or not b.get("enabled"):
            continue
        s = b.get("status") or {}
        k = str(b.get("key"))
        e = brk.get(k) or {}
        if s.get("ok") is False:
            if not e.get("fail") or now - float(e.get("at") or 0) >= 86400:
                brk[k] = {"fail": 1, "at": int(now)}
                if on:
                    res.append(_alert("OA_ALERT", f"🏦 증권사 동기화 실패 · {b.get('name') or k}"
                                                  + (f" — {str(s.get('err'))[:120]}" if s.get("err") else "") + " (기타 자산 탭에서 확인)", key=k))
        elif s.get("ok") is True and e.get("fail"):
            brk[k] = {"fail": 0, "at": int(now)}
            if on:
                res.append(_alert("OA_ALERT", f"✅ 증권사 동기화 복구 · {b.get('name') or k}", key=k))
    alive = set()
    for it in v.get("items") or []:
        if not isinstance(it, dict) or it.get("auto") not in ("stock", "gold"):
            continue
        q = it.get("quote") or {}
        k = str(it.get("id"))
        if not q.get("stale"):
            stl.pop(k, None)
            continue
        alive.add(k)
        e = stl.setdefault(k, {"since": int(now)})
        if now - float(e.get("since") or now) < 3600 or now - float(e.get("sent") or 0) < 86400:
            continue
        e["sent"] = int(now)
        if on:
            res.append(_alert("OA_ALERT", f"⏳ 시세 오래됨 · {it.get('name') or it.get('ticker') or k}"
                                          + (f" ({it.get('ticker')})" if it.get("ticker") else "")
                                          + (f" — {str(q.get('err'))[:100]}" if q.get("err") else "") + " · 평가액은 마지막 시세 그대로예요", key=k))
    for k in list(stl):
        if k not in alive:
            del stl[k]
    return res


PRODUCERS = [("pnl", prod_pnl), ("review", prod_review), ("weekly", prod_weekly), ("move", prod_move), ("bigflow", prod_bigflow),
             ("lprange", prod_lprange), ("depeg", prod_depeg), ("liq", prod_liq), ("oa", prod_oa)]


def step(inp: dict, doc: dict, st: dict, now: float = None, conn=None, log=None) -> list:
    now = time.time() if now is None else now
    out = []
    for key, fn in PRODUCERS:
        try:
            out += fn(inp, doc, st, now, conn, AP.effective(doc, key, now, conn))
        except Exception as e:
            if log:
                log.warning("알림 생산자 %s 실패(다음 판): %s", key, e)
    return out


SAMPLES = {
    "health": "🔴 tj-evm · 수집 멈춤\nBase 지갑 0xAbC0…0dEf 마지막 동기화 52분 전\n조치: 대시보드 설정 › 상태 에서 확인",
    "digest": "📋 09:00 상태 · 열린 문제 1건: tj-exf 바이낸스 이력 수집 지연(1시간 12분)",
    "price": "🎯 ETH 목표가 도달 — 현재 $4,512.3000 ≥ 목표 $4,500.0000",
    "recon": "바이낸스 잔고 대사 완료 — 2개 통화 보정",
    "sync": "[base] 스왑 감지 tx 0xabc…123",
    "backfill": "전 체인 백필+기초잔고 대사 완료 — 일별 스냅샷 동결 시작",
    "scam": "[base] UNKNOWN — 검토 필요 tx 0xdef…456",
    "pnl": "📊 01-15(수) 일간 손익 (23:50 기준)\n실현 +₩12만\n총자산 +₩34만 — 시세 +₩30만 · 입출금 +₩0 · 환율 +₩1만 · 그 밖 +₩3만\n많이 움직인 코인: ETH +3.1% (+₩15만) · SOL +2.4% (+₩9만) · LINK +1.2% (+₩4만)",
    "review": "📝 AI 일간 복기 도착 · 01-14(화) · 양호\n매수 타이밍은 좋았지만 매도가 일렀다.\n총자산 변동 +₩12만은 시세 +₩10만 …\n보기: 일별 기록 탭",
    "weekly": "📘 주간 복기 도착 · 01-06(월)~01-12(일) · 양호\nETH 한 사이클이 주간 수익 대부분을 만들었다.\n…\n보기: 일별 기록 탭",
    "move": "📈 SOL 1시간 +11.2% · 24시간 +14.0% — 지금 $134.50 · 보유 ₩120만",
    "bigflow": "💸 큰 출금 감지 · 외부 전송 USDC −₩500만 (오늘 입출금 합계 −₩500만)",
    "lprange": "⚠️ LP 범위 이탈 · Uniswap V3 WETH / USDC (Arbitrum #123456) — 범위 2,400 – 2,900 (USDC/WETH)",
    "depeg": "🟠 스테이블 디페그 · USDC $0.9870 (−1.30% · 기준 ±1%) · 보유 중",
    "liq": "🚨 선물 청산가 근접 · 바이낸스 BTCUSDT 롱 — 현재 $60,000.00 · 청산가 $55,000.00 (8.3% 남음 · 기준 10%)",
    "oa": "🏦 증권사 동기화 실패 · 키움증권 — 인증 만료 (기타 자산 탭에서 확인)",
    "other": "[NEW_KIND] 새 종류의 알림 예시",
}


def test_line(cat: str) -> dict:
    c = AP.CAT[cat]
    return {"ts": int(time.time()), "kind": AP.TEST_KIND, "cat": cat, "test": True,
            "text": f"🔔 [테스트 · {c['label']}] 이런 모양으로 와요 — 예시(실제 값 아님):\n{SAMPLES.get(cat, '')}"}
