"""Producers for optional Telegram alerts (daily PnL, price moves, big flows, LP range, depeg, liquidation)."""
from __future__ import annotations

import copy
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


def _link(inp, tab) -> str:
    pub = str((inp or {}).get("pub") or "").rstrip("/")
    return f"\n[보기] {pub}/v2/#{tab}" if pub.startswith("https://") else ""


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
    lines = [f"📋 {_md(iso)} 오늘 손익" + (f" ({_kst(bt).strftime('%H:%M')} 기준)" if bt else "")]
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
    return [_alert("PNL_DAILY", txt, day=iso, d=pnl_data(out, inp.get("cur") or "KRW"))] if txt else []


def pnl_data(out, cur="KRW") -> dict | None:
    try:
        f = (out or {}).get("fields") or {}
        iso, key = out.get("todayIso"), out.get("todayKey")
        ds = [r for r in (f.get("dailySeries") or []) if isinstance(r, dict) and _f(r.get("val")) is not None]
        rate = _f(f.get("rate"))
        krw = cur != "USD" and rate
        k = rate if krw else 1.0
        idx = next((i for i, r in enumerate(ds) if r.get("date") == key), None)
        if not iso or idx is None:
            return None
        row = ds[idx]
        prev = ds[idx - 1] if idx > 0 else None
        val = _f(row.get("val"))
        if krw:
            pk = _f((prev or {}).get("valKrw"))
            delta = (val * rate - (pk if pk is not None else _f(prev.get("val")) * rate)) if prev else None
        else:
            delta = (val - _f(prev.get("val"))) if prev else None
        rz = (_f((f.get("realizedByDate") or {}).get(iso)) or 0.0) + (_f(((f.get("futures") or {}).get("realizedByDate") or {}).get(iso)) or 0.0)
        curve = []
        for r in ds[max(0, idx - 30):idx + 1]:
            v = _f(r.get("valKrw")) if krw and r is not row and _f(r.get("valKrw")) is not None else (_f(r.get("val")) or 0.0) * k
            fl9 = _f(r.get("flow"))
            if fl9 is not None and krw:
                u9 = _f(r.get("usdt"))
                fl9 *= u9 if (r is not row and u9 and u9 > 0 and _f(r.get("valKrw")) is not None) else rate
            curve.append([str(r.get("date") or ""), round(v, 2), round(fl9, 2) if fl9 is not None else None])
        att = row.get("att") if isinstance(row.get("att"), dict) else {}
        top = [[str(t[0]), round(_f(t[1]), 1)] for t in (att.get("top") or []) if isinstance(t, (list, tuple)) and len(t) >= 2 and _f(t[1]) is not None][:3]
        sells = 0
        try:
            sells = int(((f.get("dayActs") or {}).get(iso) or {}).get("s") or 0)
        except (TypeError, ValueError, AttributeError):
            sells = 0
        return {"iso": iso, "cur": "KRW" if krw else "USD", "realized": round(rz * k, 2), "delta": round(delta, 2) if delta is not None else None,
                "sells": sells, "top": top, "curve": curve}
    except Exception:
        return None


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
        res.append(_alert("REVIEW_DAILY", "\n".join([f"📋 AI 복기가 도착했어요 · {_md(iso)} {g}"] + two[:1]) + _link(inp, "daily"), day=iso,
                          d={"iso": iso, "grade": g, "first": (two[0] if two else "")[:120]}))
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
        res.append(_alert("REVIEW_WEEKLY", "\n".join([f"📋 주간 복기가 도착했어요 · {rng} {g}"] + two[:1]) + _link(inp, "daily"), week=k,
                          d={"rng": rng, "grade": g, "first": (two[0] if two else "")[:120]}))
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


def _total_usd(f) -> float:
    try:
        ds = [r for r in (f.get("dailySeries") or []) if isinstance(r, dict)]
        if ds and _f(ds[-1].get("val")):
            return float(ds[-1]["val"])
    except Exception:
        pass
    t = 0.0
    for k9 in ("coins", "stables"):
        for c in f.get(k9) or []:
            if isinstance(c, dict):
                t += (_f(c.get("qty")) or 0.0) * (_f(c.get("price")) or 0.0)
    return t


def prod_move(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    if not out or now - float(out.get("builtAt") or 0) > BUILD_MAX_AGE:
        return []
    th = doc["th"]
    t1, t24, vmin = float(th["move_1h"]), float(th["move_24h"]), float(th["move_min"])
    wmin = float(th.get("move_weight", 3) or 0)
    tot = _total_usd(f)
    mv = st.setdefault("move", {})
    hist = mv.setdefault("px", {})
    last = mv.setdefault("day", {})
    mv.pop("last", None)
    spot = inp.get("spot") or {}
    build_fresh = now - float(out.get("builtAt") or 0) <= LIVE_PX_AGE
    today = _kst(now).strftime("%Y-%m-%d")
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
        s9 = [x for x in (hist.get(k) or []) if isinstance(x, list) and len(x) == 2 and now - x[0] <= PX_KEEP]
        if not s9 or now - s9[-1][0] >= PX_EVERY:
            s9.append([int(now), p])
        hist[k] = _thin(s9, now)
        w = (val / tot * 100) if tot > 0 else 0.0
        if not on or val < vmin or w < wmin:
            continue
        p1, p24 = _near(s9, now - 3600, 900), _near(s9, now - 86400, 2700)
        c1 = (p / p1 - 1) * 100 if p1 else None
        c24 = (p / p24 - 1) * 100 if p24 else None
        hit1 = c1 is not None and abs(c1) >= t1
        hit24 = c24 is not None and abs(c24) >= t24
        if not (hit1 or hit24) or last.get(k) == today:
            continue
        last[k] = today
        ch, span = (c1, "1시간") if hit1 else (c24, "24시간")
        up = ch > 0
        cur, rate = inp.get("cur") or "KRW", _f(f.get("rate"))
        res.append(_alert("PRICE_MOVE", f"🔴 {c.get('sym')} {span} 만에 {abs(ch):.0f}% {'올랐어요' if up else '떨어졌어요'}\n"
                                        + ("급하지 않아요 — 목표가를 걸어 두면 거기서 알려 드려요." if up else "손절선을 걸어 두지 않았다면 지금 정해 두세요.")
                                        + f"\n지금 {px_txt(p)} · 보유 {money(val, cur, rate)} · 총자산의 {w:.0f}%" + _link(inp, "dash"),
                          sym=c.get("sym"), key=k))
    for k in list(hist):
        if k not in alive:
            del hist[k]
    for k in list(last):
        if last[k] != today and str(last[k]) < (_kst(now - 2 * 86400).strftime("%Y-%m-%d")):
            del last[k]
    return res


FLOW_KEEP = 3 * 86400
FLOW_LIST_MAX = 20
DAY = 86400


def q_txt(q) -> str:
    v = _f(q)
    if v is None:
        return "?"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if a >= 1:
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return f"{v:.6g}"


def dur_txt(sec) -> str:
    s = max(0, int(sec or 0))
    if s < 3600:
        return f"{max(1, s // 60)}분"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}시간" + (f" {m}분" if m else "")


def _hm(ts, now) -> str:
    t = _kst(ts)
    return t.strftime("%H:%M") if t.date() == _kst(now).date() else t.strftime("%m-%d %H:%M")


def _flow_item(e, cur, rate, now) -> str:
    usd = _f(e.get("usd"))
    amt = money(-usd, cur, rate, True) if usd is not None else "금액 모름"
    src = str(e.get("src") or "")
    return f"{e.get('sym')} {q_txt(e.get('qty'))}개 {amt} → {e.get('dst') or '?'} ({(src + ' · ') if src else ''}{_hm(e['ts'], now)})"


def prod_bigflow(inp, doc, st, now, conn, on):
    mem = st.get("flow2")
    if not isinstance(mem, dict) or not isinstance(mem.get("seen", {}), dict):
        st["flow2"] = {}
    snap = copy.deepcopy(st.get("flow2"))
    try:
        return _prod_bigflow(inp, doc, st, now, conn, on)
    except Exception:
        st["flow2"] = snap
        raise


def _prod_bigflow(inp, doc, st, now, conn, on):
    mem = st.setdefault("flow2", {})
    if not on:
        mem["boff"] = 1
    elif mem.pop("boff", None):
        mem["on_at"] = int(now)
    on_arr = AP.effective(doc, "arrive", now, conn)
    if not on_arr:
        mem["aoff"] = 1
    elif mem.pop("aoff", None):
        mem["a_on_at"] = int(now)
    fl = inp.get("flows")
    if not isinstance(fl, dict) or now - float(fl.get("builtAt") or 0) > BUILD_MAX_AGE:
        return []
    import flowev
    f = ((inp.get("out") or {}).get("fields")) or {}
    cur, rate = inp.get("cur") or "KRW", _f(f.get("rate"))
    nmin = float(doc["th"]["flow_min"])
    first = not mem.get("init")
    mem["init"] = 1
    st.pop("bigflow", None)
    seen = mem.setdefault("seen", {})
    on_at = _f(mem.get("on_at")) or 0
    a_on_at = _f(mem.get("a_on_at")) or 0
    win = float(fl.get("window") or flowev.WINDOW)
    res, new_ext, alive, carry = [], [], set(), []
    ext_24 = 0.0
    for e in fl.get("ev") or []:
        if not isinstance(e, dict) or not e.get("id") or not isinstance(e.get("ts"), (int, float)) or now - e["ts"] > win:
            continue
        eid = str(e["id"])
        alive.add(eid)
        m = seen.get(eid)
        new = not isinstance(m, dict)
        if new:
            m = seen[eid] = {"t": int(now), "x": 0, "n": 0}
        usd = _f(e.get("usd"))
        cls, dr = e.get("cls"), e.get("dir")
        if cls == "external" and dr == "out":
            if e["ts"] < on_at:
                m["x"] = m["n"] = 1
                continue
            if usd and now - e["ts"] <= DAY:
                ext_24 += usd
            if first or not on:
                m["x"] = m["n"] = 1
                continue
            if not m.get("x", 1):
                m["x"] = 1
                new_ext.append(e)
            elif m.get("p") and not m.get("n", 1):
                carry.append(e)
            continue
        if cls == "external" and dr == "in":
            if new and not first and on and usd is not None and usd >= nmin and e["ts"] >= on_at:
                desc = f"{e.get('sym')} {q_txt(e.get('qty'))}개 → {e.get('dst') or '?'}"
                res.append(_alert("BIG_INFLOW", f"📋 큰 입금 {money(usd, cur, rate, True)} · {desc}", key=eid,
                                  d={"desc": desc[:60], "amt": money(usd, cur, rate, True)}))
            continue
        arr = e.get("arr")
        if cls != "internal" or dr != "out" or not isinstance(arr, dict) or arr.get("st") not in ("pending", "arrived"):
            continue
        exp = float(arr.get("exp") or flowev.EXP_NORMAL)
        t_from = float(arr.get("from") or e["ts"])
        if first:
            if arr["st"] == "arrived":
                m["a"] = 1
            elif now - t_from >= exp:
                m["l"] = 1
            continue
        big = usd is not None and usd >= nmin
        where = arr.get("where") or e.get("dst") or "내 지갑"
        if arr["st"] == "arrived" and not m.get("a"):
            m["a"] = 1
            if not big:
                continue
            at9 = float(arr["ts"]) if isinstance(arr.get("ts"), (int, float)) and arr["ts"] > 0 else float(e["ts"])
            aq = _f(arr.get("qty"))
            same = aq is not None and (not arr.get("sym") or flowev.OM.family(arr.get("sym")) == flowev.OM.family(e.get("sym")))
            lack = flowev.short_of(e.get("qty"), aq, arr.get("fee"), e.get("sym"), bridge=e.get("kind") == "bridge") if same else None
            took = (f"보낸 지 {dur_txt(arr['ts'] - e['ts'])}" if arr.get("ts") and arr["ts"] >= e["ts"] else "")
            if lack is not None and on and at9 >= on_at:
                lu = usd * float(lack) / float(e["qty"]) if e.get("qty") else None
                res.append(_alert("MOVE_SHORT", f"🔴 보낸 것보다 적게 들어왔어요 — {e.get('sym')} {q_txt(e.get('qty'))}개 보냄 · {q_txt(aq)}개 받음\n"
                                                f"수수료보다 {q_txt(lack)}개 더 줄었어요 — {e.get('src') or '보낸 곳'} → {where} 내역을 확인하세요.\n"
                                                + " · ".join(x for x in (took, money(-lu, cur, rate, True) if lu else "") if x) + _link(inp, "outflows"),
                                  key=eid))
            elif on_arr and at9 >= a_on_at and not (lack is not None and on):
                lost = (_f(e.get("qty")) or 0) - aq if same else None
                lost_t = f" · 수수료로 {q_txt(lost)}개 줄었어요" if lost is not None and lost > abs(_f(e.get("qty")) or 0) * 1e-6 else ""
                if lack is not None:
                    lost_t = f" · {q_txt(lost)}개 줄었어요(수수료보다 {q_txt(lack)}개 더)"
                fr = e.get("src") or ""
                act9 = ("보낸 것보다 적게 들어왔어요 — 내역을 확인하세요." if lack is not None else "받은 수량은 앱에서 확인하세요." if not same
                        else "할 일은 없어요.")
                res.append(_alert("MOVE_ARRIVED", (f"✅ 늦었지만 {e.get('sym')} {q_txt(aq if same else e.get('qty'))}개가 {where}에 들어왔어요\n" if m.get("l")
                                                   else f"✅ {e.get('sym')} {q_txt(aq if same else e.get('qty'))}개가 {where}에 들어왔어요\n")
                                  + act9 + "\n" + (f"{fr}에서 " if fr else "") + (took or "도착 확인") + lost_t,
                                  key=eid))
            continue
        if arr["st"] == "pending" and not m.get("l") and now - t_from >= exp:
            m["l"] = 1
            if not (big and on) or t_from + exp < on_at:
                continue
            ago, sym, qt, src, dst = dur_txt(now - e["ts"]), e.get("sym"), q_txt(e.get("qty")), e.get("src") or "", e.get("dst") or "내 지갑"
            k = e.get("kind")
            if k == "bridge":
                txt = (f"🔴 {ago} 전 브릿지로 보낸 {sym} {qt}개가 아직 내 지갑에 안 들어왔어요\n브릿지 상태를 확인하세요"
                       + (" — 추적하지 않는 체인으로 보냈다면 괜찮아요" if arr.get("untracked") else "") + ".")
            elif k == "exchange":
                txt = f"🔴 {ago} 전 {dst} 입금 주소로 보낸 {sym} {qt}개가 아직 {dst}에 안 들어왔어요\n{dst} 입금 내역을 확인하세요(네트워크가 붐비면 늦을 수 있어요)."
            elif k == "exchange_wd_noaddr":
                txt = (f"🔴 {ago} 전 {src}에서 출금한 {sym} {qt}개가 아직 내 지갑·거래소에 안 들어왔어요\n"
                       f"추적하지 않는 곳으로 보낸 게 아니면 바로 {src} 출금 내역과 보안을 확인하세요.")
            else:
                txt = f"🔴 {ago} 전 {src}에서 출금한 {sym} {qt}개가 아직 {dst}에 안 들어왔어요\n{src} 출금 상태를 확인하세요(거래소가 처리 중일 수 있어요)."
            res.append(_alert("MOVE_LATE", txt + f"\n{src + ' → ' if src else ''}{dst} · {money(-usd, cur, rate, True)}" + _link(inp, "outflows"), key=eid))
    k24 = int(ext_24 // nmin) if nmin > 0 else 0
    told = int(_f(mem.get("k24")) or 0)
    old24 = ext_24 - sum(_f(e.get("usd")) for e in new_ext if _f(e.get("usd")) and now - e["ts"] <= DAY)
    told_n = min(told, int(max(0.0, old24) // nmin)) if nmin > 0 else told
    if first or not on:
        mem["k24"] = k24
    elif new_ext or carry:
        hit = [e for e in new_ext if (_f(e.get("usd")) or 0) >= nmin]
        if hit or k24 > told_n or carry:
            pool = new_ext if hit else [e for e in fl.get("ev") or [] if isinstance(e, dict) and e.get("cls") == "external" and e.get("dir") == "out"
                                        and isinstance(e.get("ts"), (int, float)) and now - e["ts"] <= DAY and e["ts"] >= on_at
                                        and not (seen.get(str(e.get("id"))) or {}).get("n", 1)] if (hit or k24 > told_n) else []
            ids9 = {str(e["id"]) for e in pool}
            pool = pool + [e for e in carry if str(e["id"]) not in ids9]
            lst = sorted(pool, key=lambda e: -(_f(e.get("usd")) or 0))
            shown = lst[:FLOW_LIST_MAX]
            rest = len(lst) - len(shown)
            tot = sum(_f(e.get("usd")) or 0 for e in lst)
            link = _link(inp, "outflows")
            act = "내가 한 게 아니면 바로 거래소·지갑 보안을 확인하세요."
            tail = f"24시간 동안 밖으로 나간 돈 {money(-ext_24, cur, rate, True)}"
            if hit and len(shown) == 1 and not rest:
                e = shown[0]
                usd = _f(e.get("usd"))
                txt = (f"🔴 {e.get('sym')} {q_txt(e.get('qty'))}개" + (f"({money(-usd, cur, rate, True)})" if usd is not None else "")
                       + f"가 밖으로 나갔어요 → {e.get('dst') or '?'}\n{act}\n{(e.get('src') or '') + ' · ' if e.get('src') else ''}{_hm(e['ts'], now)}"
                       + (f" · {tail}" if ext_24 > (usd or 0) + 1 else ""))
            else:
                head = (f"🔴 밖으로 {len(lst)}건 {money(-tot, cur, rate, True)}이 나갔어요" if hit
                        else f"🔴 작은 출금이 모여 24시간 동안 {money(-ext_24, cur, rate, True)}이 나갔어요" if k24 > told_n
                        else f"🔴 앞 알림에 다 못 실은 출금 {len(lst)}건 {money(-tot, cur, rate, True)}이에요")
                txt = (head + f"\n{act}\n" + "\n".join("- " + _flow_item(e, cur, rate, now) for e in shown)
                       + (f"\n- 외 {rest}건(줄 수 제한 — 다음 알림·앱 보낸 내역)" if rest else "") + f"\n{tail}")
            res.append(_alert("BIG_FLOW", txt + link, n=len(lst), ids=[str(e["id"]) for e in lst][:50]))
            for e in lst:
                m9 = seen.get(str(e["id"]))
                if isinstance(m9, dict):
                    if any(e is x for x in shown):
                        m9["n"] = 1
                        m9.pop("p", None)
                    else:
                        m9["p"] = 1
            mem["k24"] = max(k24, told_n)
    if k24 < told:
        mem["k24"] = k24
    for k9, v9 in list(seen.items()):
        if k9 not in alive and (not isinstance(v9, dict) or now - (_f(v9.get("t")) or 0) > FLOW_KEEP):
            del seen[k9]
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
        res.append(_alert("LP_RANGE", (f"📋 LP 범위를 벗어났어요 · {name}" if s == "범위 이탈" else f"📋 LP 범위로 돌아왔어요 · {name}")
                          + (f" — 범위 {lp.get('range')}" if lp.get("range") else "") + (f" · 평가 {money(val, cur, rate)}" if val is not None else ""),
                          key=k, status=s, d={"name": name[:80], "out": s == "범위 이탈"}))
    for k in list(mem):
        if k not in alive:
            del mem[k]
    for k in list(xm):
        if k not in alive:
            del xm[k]
    return res


DEPEG_FRESH = 600
DEPEG_MIN_EX = 2
DEPEG_HELD_USD = 100


def stable_quotes(spot, syms, now, max_age=DEPEG_FRESH, min_n=1) -> dict:
    ex, ts = (spot or {}).get("ex_usd") or {}, (spot or {}).get("ex_ts") or {}
    out = {}
    for s in syms:
        v = [_f(ex.get(f"{e}:{s}")) for e in GLOBAL_EX if now - (_f(ts.get(f"{e}:{s}")) or 0) <= max_age]
        v = [x for x in v if x and 0.5 < x < 1.5]
        if len(v) >= max(1, min_n):
            out[s] = statistics.median(v)
    return out


def prod_depeg(inp, doc, st, now, conn, on):
    out = inp.get("out") or {}
    f = out.get("fields") or {}
    spot = inp.get("spot")
    if not spot:
        return []
    th = float(doc["th"]["depeg_pct"])
    if not isinstance(f.get("stables"), list):
        return []
    held = {str(c.get("sym") or "").upper() for c in (f.get("stables") or []) if isinstance(c, dict)
            and (_f(c.get("qty")) or 0) * (_f(c.get("price")) or 1) >= DEPEG_HELD_USD}
    syms = (held | {"USDC", "USD1", "FDUSD", "USDE", "PYUSD"}) - {"USDT", ""}
    q = stable_quotes(spot, sorted(syms), now, DEPEG_FRESH, DEPEG_MIN_EX)
    qh = stable_quotes(spot, sorted(held - {"USDT"}), now, DEPEG_FRESH, DEPEG_MIN_EX)
    devs = {}
    if len(q) >= 3 and "USDT" in held:
        m = statistics.median(q.values())
        if abs(m - 1) * 100 >= th:
            devs["USDT"] = 1 / m
    if not (len(q) >= 3 and abs(statistics.median(q.values()) - 1) * 100 >= th):
        for s9, p in qh.items():
            if abs(p - 1) * 100 >= th:
                devs[s9] = p
    mem = st.setdefault("depeg", {})
    for s9 in [s9 for s9 in mem if s9 not in held]:
        del mem[s9]
    res = []
    for s9, p in devs.items():
        e = mem.get(s9) if isinstance(mem.get(s9), dict) else {}
        dev = abs(p - 1) * 100
        told = _f(e.get("dev"))
        if told is not None and dev < told * 2:
            continue
        mem[s9] = {"at": int(now), "px": p, "dev": round(dev, 3)}
        if on:
            worse = told is not None
            res.append(_alert("DEPEG", (f"🔴 {s9} 이탈이 더 커졌어요 — 1달러에서 {dev:.1f}%\n" if worse else f"🔴 {s9} 가격이 1달러에서 {dev:.1f}% 벗어났어요\n")
                                       + "많이 들고 있다면 다른 스테이블로 옮길지 살펴보세요.\n"
                                       + f"지금 {px_txt(p)} · 기준 ±{th:g}% · 들고 있음"
                                       + (" · 다른 스테이블들이 함께 벗어나 USDT 쪽으로 판단" if s9 == "USDT" else ""), sym=s9))
    for s9 in list(mem):
        if s9 in devs:
            continue
        p = qh.get(s9) if s9 != "USDT" else None
        rec = (p is not None and abs(p - 1) * 100 < th / 2) or (s9 == "USDT" and len(q) >= 3 and abs(1 / statistics.median(q.values()) - 1) * 100 < th / 2)
        if rec:
            del mem[s9]
            if on:
                res.append(_alert("DEPEG", f"✅ {s9} 1달러로 돌아왔어요\n할 일은 없어요." + (f"\n지금 {px_txt(p)}" if p else ""), sym=s9, resolved=True))
    return res


def prod_liq(inp, doc, st, now, conn, on):
    return []


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
                    res.append(_alert("OA_ALERT", f"📋 {b.get('name') or k} 연결이 끊겼어요 — 기타 자산 탭에서 다시 연결해 주세요"
                                                  + (f" ({str(s.get('err'))[:80]})" if s.get("err") else ""), key=k,
                                      d={"msg": f"{b.get('name') or k} 연결 끊김"}))
        elif s.get("ok") is True and e.get("fail"):
            brk[k] = {"fail": 0, "at": int(now)}
            if on:
                res.append(_alert("OA_ALERT", f"📋 {b.get('name') or k} 다시 연결됐어요", key=k, d={"msg": f"{b.get('name') or k} 다시 연결됨"}))
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
            res.append(_alert("OA_ALERT", f"📋 {it.get('name') or it.get('ticker') or k} 시세가 한 시간 넘게 멈췄어요 — 평가액은 마지막 시세 그대로예요"
                                          + (f" ({str(q.get('err'))[:80]})" if q.get("err") else ""), key=k,
                              d={"msg": f"{it.get('name') or it.get('ticker') or k} 시세 멈춤"}))
    for k in list(stl):
        if k not in alive:
            del stl[k]
    return res


PRODUCERS = [("pnl", prod_pnl), ("review", prod_review), ("weekly", prod_weekly), ("move", prod_move), ("bigflow", prod_bigflow),
             ("lprange", prod_lprange), ("depeg", prod_depeg), ("liq", prod_liq), ("oa", prod_oa)]
WATCH_CATS = tuple(k for k, _fn in PRODUCERS) + ("arrive",)


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


SAMPLES = AP.SAMPLES


def test_line(cat: str) -> dict:
    c = AP.CAT[cat]
    return {"ts": int(time.time()), "kind": AP.TEST_KIND, "cat": cat, "test": True,
            "text": f"🔔 테스트 · {'하루 요약' if cat == 'digest' else c['label']} — 이런 모양으로 와요(예시 · 실제 값 아님)\n{AP.DIGEST_SAMPLE if cat == 'digest' else SAMPLES.get(cat, '')}"}
