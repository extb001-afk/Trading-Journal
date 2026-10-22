from __future__ import annotations
import threading
import time
from datetime import datetime
from timeutil import KST
import acct_norm
import websnap
import logging
import calcguard  # noqa: E402
log = logging.getLogger('tj-web')

_HERO_HTML = {}


_HERO_HTML_LOCK = threading.Lock()


def _hero_ok(b, snap) -> bool:
    try:
        if b is None or snap is None:
            return False
        lim = float(getattr(b, "SNAP_STALE_MAX", 120))
        if time.time() - float(snap.at) > lim:
            return False
        if snap.gen != b.__dict__.get("_inval", 0) or b.__dict__.get("_build_err") is not None:
            return False
        tk = (getattr(snap, "hero", None) or {}).get("todayKey")
        return tk == datetime.now(KST).strftime("%m-%d")
    except Exception as _cg9:   # noqa: BLE001 [probe]
        calcguard.swallowed("view_hero:_hero_ok", _cg9)
        return False


def _hero_summary(out):
    f = out.get("fields") or {}
    n = lambda v: float(v) if isinstance(v, (int, float)) and v == v else 0.0
    rate = n(f.get("rate")) or acct_norm.DEFAULT_KRW_USD
    total = sum(n(x.get("qty")) * n(x.get("price")) for x in (f.get("stables") or []))
    total += sum(n(x.get("qty")) * n(x.get("price")) for x in (f.get("coins") or []))
    total += sum(n(x.get("krw")) / rate for x in (f.get("fiats") or []))
    for lp in f.get("lps") or []:
        if isinstance(lp, dict) and not lp.get("closed"):
            total += n(lp.get("value")) + n(lp.get("fees")) + n(lp.get("rewards"))
    total += sum(n(x.get("usd")) for x in (f.get("rabbyDebts") or []) if isinstance(x, dict))
    tk = str(out.get("todayKey") or "")
    daily = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
    prev = daily[-2] if len(daily) > 1 and daily[-1].get("date") == tk else (daily[-1] if daily else None)
    mm = tk[:3]
    ym = str(out.get("todayIso") or "")[:8]
    inm = lambda k: str(k).startswith(ym) if (ym and len(str(k)) == 10) else str(k).startswith(mm)
    fut = (f.get("futures") or {}).get("realizedByDate") or {}
    month = sum(n(v) for k, v in (f.get("realizedByDate") or {}).items() if inm(k))
    month += sum(n(v) for k, v in fut.items() if inm(k))
    rk = f.get("realizedKrwByDate")
    month_krw, month_ap = None, False
    if isinstance(rk, dict):
        fk = (f.get("futures") or {}).get("realizedKrwByDate") or {}
        mk = 0.0
        for su, sk in (((f.get("realizedByDate") or {}), rk), (fut, fk)):
            for k, v in su.items():
                if not inm(k):
                    continue
                if isinstance(sk, dict) and sk.get(k) is not None:
                    mk += n(sk.get(k))
                else:
                    mk += n(v) * rate
                    month_ap = month_ap or abs(n(v)) >= 0.005
        month_krw = round(mk)
    tiso = str(out.get("todayIso") or "")[:10]
    ist = lambda k: (str(k) == tiso) if len(str(k)) == 10 else (str(k) == tk)
    today_r = sum(n(v) for k, v in (f.get("realizedByDate") or {}).items() if ist(k)) + sum(n(v) for k, v in fut.items() if ist(k))
    today_krw = None
    if isinstance(rk, dict):
        fk = (f.get("futures") or {}).get("realizedKrwByDate") or {}
        tkw = 0.0
        for su, sk in (((f.get("realizedByDate") or {}), rk), (fut, fk)):
            for k, v in su.items():
                if ist(k):
                    tkw += n(sk.get(k)) if isinstance(sk, dict) and sk.get(k) is not None else n(v) * rate
        today_krw = round(tkw)
    series = []
    for d in daily[-30:]:
        v9 = n(d.get("val"))
        ap9 = 1 if (d.get("date") != tk and n(d.get("est")) + n(d.get("xc")) >= max(50.0, 0.005 * abs(v9))) else 0
        series.append([d.get("date"), round(v9, 2), d.get("valKrw") if isinstance(d.get("valKrw"), (int, float)) else None, ap9])
    if series and series[-1][0] == tk:
        series[-1][1] = round(total, 2)
        series[-1][2] = None
        series[-1][3] = 0
    last = daily[-1] if daily and daily[-1].get("date") == tk else None
    return {"total": round(total, 2), "prev": round(n(prev.get("val")), 2) if prev else None,
            "prevKrw": prev.get("valKrw") if prev and isinstance(prev.get("valKrw"), (int, float)) else None,
            "flow": n(last.get("flow")) if last and last.get("flow") is not None else None,
            "month": round(month, 2), "monthKrw": month_krw, "monthAp": month_ap,
            "tr": round(today_r, 2), "trKrw": today_krw,
            "rate": rate, "todayKey": tk, "series": series}


def _ago_ko(sec) -> str:
    s9 = max(0, int(sec))
    if s9 < 7200:
        return f"{max(1, s9 // 60)}분"
    if s9 < 172800:
        return f"{s9 // 3600}시간"
    return f"{s9 // 86400}일"


def _publish_snap(pub, gen, out=None):
    snap9 = websnap.Snap(pub, gen)
    try:
        snap9.hero = _hero_summary(out if out is not None else pub)
    except Exception as e:   # noqa: BLE001 [optional]
        calcguard.swallowed("view_hero:_publish_snap[hero]", e)
        log.warning("hero 요약 실패(무시): %s", e)
    try:
        websnap.attach_slim(snap9, pub)
    except Exception as e:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_hero:_publish_snap[attach_slim]", e)
        snap9.slim_gz = snap9.parts_gz = None
        log.warning("가벼운 상태 만들기 실패(무시): %s", e)
    return snap9
