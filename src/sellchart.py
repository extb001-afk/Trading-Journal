"""Sell receipt chart summary and AI evaluation storage."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import logging
import re
import secrets
import statistics
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import common

log = logging.getLogger("tj-web")

KST = timezone(timedelta(hours=9))
CUR_SYM = {"KRW": "₩", "USD": "$"}
USD_LIKE = {"USDT", "USDC", "USD", "FDUSD", "USD1", "BUSD", "TUSD", "DAI", "USDE", "PYUSD", "USDG"}
EX_NS = {"upbit", "bithumb", "binance", "bybit", "okx", "gate", "kucoin"}
PRE_S = 3600
POST_S = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600}
SPIKE_MULT = 2.0
SPIKE_TOP = 0.8
EVAL_DAILY_MAX = 0
EVAL_DAILY_CAP = 5000
EVAL_KEEP = 12000
EVAL_KEEP_PER = 3
_ADDR_RX = re.compile(r"0x[0-9a-fA-F]{40}|0x[0-9a-fA-F]{64}|[1-9A-HJ-NP-Za-km-z]{32,44}")


def _f(x):
    try:
        v = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x, nd=None):
    if x is None:
        return None
    x = float(x)
    if x == 0:
        return 0
    if nd is not None:
        return round(x, nd)
    if abs(x) >= 1000:
        return round(x, 2) if abs(x) < 1e5 else round(x)
    if abs(x) >= 1:
        return round(x, 4)
    return float(f"{x:.6g}")


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if (a is not None and b) else None


def tx_addrs(snapshot) -> list:
    if snapshot is None:
        return []
    s = snapshot if isinstance(snapshot, str) else json.dumps(snapshot)
    return sorted(set(_ADDR_RX.findall(s)))[:400]


def spec_of(source_ns, payload, a_chain, a_addr, a_sym, snapshot=None):
    ns = str(source_ns or "")
    ex = ns.split(":", 1)[0]
    if ex in EX_NS and ":" in ns:
        p = payload if isinstance(payload, dict) else {}
        base = quote = None
        px = None
        if ex == "upbit":
            mk = str(p.get("market") or "")
            if "-" in mk:
                quote, base = mk.split("-", 1)
            ev, ef = _f(p.get("executed_volume")), _f(p.get("executed_funds"))
            px = (ef / ev) if (ev and ef) else _f(p.get("price"))
        else:
            base, quote = p.get("base"), p.get("quote")
            px = _f(p.get("price"))
        if not base or not quote:
            return None, None, "USD"
        base, quote = str(base).upper(), str(quote).upper()
        cur = "KRW" if quote == "KRW" else "USD"
        if quote != "KRW" and quote not in USD_LIKE:
            px = None
            quote = "USDT"
        return {"venue": ex, "base": base, "quote": quote}, (px if px and px > 0 else None), cur
    chain = str(a_chain or ns or "")
    if not chain:
        return None, None, "USD"
    if a_addr:
        return {"venue": "dex", "chain": chain, "token": str(a_addr), "tx_addrs": tx_addrs(snapshot)}, None, "USD"
    sym = str(a_sym or "").upper()
    if not sym:
        return None, None, "USD"
    if sym.startswith("W") and sym[1:] in ("ETH", "BNB", "SOL", "AVAX", "POL", "MATIC"):
        sym = sym[1:]
    return {"venue": "binance", "base": sym, "quote": "USDT", "native": chain}, None, "USD"


def window(fills, after="1h"):
    ts = [int(f["ts"]) for f in fills]
    t_first, t_last = min(ts), max(ts)
    return t_first - PRE_S, t_last + POST_S.get(after, 3600), t_first, t_last


def _typ(c):
    return (c[2] + c[3] + c[4]) / 3.0


def summarize(candles, fills, iv_s, req_end=None, deposit_ts=None, cur="KRW", now=None):
    out = _summarize(candles, fills, iv_s, req_end=req_end, deposit_ts=deposit_ts, cur=cur, now=now)
    sc = sell_score(out)
    if sc is not None:
        out["score"] = sc
    return out


def _clamp(x, a, b):
    return max(a, min(b, x))


def _score_total(comps):
    have = [c for c in comps if c["pts"] is not None]
    if not have:
        return None, False
    mx = sum(c["max"] for c in have)
    got = sum(c["pts"] for c in have)
    if len(have) == len(comps):
        return int(round(got)), False
    return int(round(got / mx * 100)) if mx > 0 else None, True


def sell_score(sm):
    if not isinstance(sm, dict):
        return None
    comps = []
    tp = sm.get("topPct")
    comps.append({"k": "pos", "label": "평균 매도가 위치", "max": 40, "in": tp,
                  "pts": round(_clamp(40 * (1 - float(tp) / 100), 0, 40), 1) if tp is not None else None,
                  "why": "40 × (1 − 고가에서 내려온 % / 100)" if tp is not None else "구간 봉 없음 — 빼고 환산"})
    vw = sm.get("vsVwapPct")
    comps.append({"k": "vwap", "label": "시장 평균가 대비", "max": 20, "in": vw,
                  "pts": round(_clamp(10 + float(vw), 0, 20), 1) if vw is not None else None,
                  "why": "10 + 시장 평균가 대비 %" if vw is not None else "매도 기간 거래량 없음 — 빼고 환산"})
    a1 = (sm.get("after") or {}).get("1h") if isinstance(sm.get("after"), dict) else None
    cp = a1.get("closePct") if isinstance(a1, dict) else None
    comps.append({"k": "after", "label": "판 뒤 1시간", "max": 25, "in": cp,
                  "pts": round(_clamp(12.5 - float(cp) * 0.625, 0, 25), 1) if cp is not None else None,
                  "why": "12.5 − 판 뒤 1시간 종가 % × 0.625" if cp is not None else "판 뒤 봉 없음 — 빼고 환산"})
    sp = sm.get("spike") if isinstance(sm.get("spike"), dict) else None
    vs = sp.get("volSharePct") if sp else None
    ok_sp = sp is not None and vs is not None and float(vs) > 0 and sp.get("sharePct") is not None
    comps.append({"k": "spike", "label": "거래량 급증 때 매도", "max": 15, "in": sp.get("sharePct") if sp else None,
                  "pts": round(_clamp(15 * min(1.0, float(sp["sharePct"]) / float(vs)), 0, 15), 1) if ok_sp else None,
                  "why": "15 × min(1, 급증 때 판 비중 / 급증 구간 거래량 비중)" if ok_sp else "뚜렷한 급증 구간 없음 — 나머지로 100점 환산"})
    tot, scaled = _score_total(comps)
    if tot is None:
        return None
    return {"total": tot, "verdict": verdict_of(tot, "sell"), "scaled": scaled, "components": comps}


def _summarize(candles, fills, iv_s, req_end=None, deposit_ts=None, cur="KRW", now=None):
    fl = [f for f in fills if f.get("px") and f.get("q")]
    q = sum(float(f["q"]) for f in fl)
    amt = sum(float(f["px"]) * float(f["q"]) for f in fl)
    out = {"cur": cur, "curSym": CUR_SYM.get(cur, ""), "n": len(fl), "qty": _r(q), "amt": _r(amt),
           "avgPx": _r(amt / q) if q else None}
    if not fl:
        return out
    t_first, t_last = min(int(f["ts"]) for f in fl), max(int(f["ts"]) for f in fl)
    out.update(firstTs=t_first, lastTs=t_last, sellSpanMin=round((t_last - t_first) / 60, 1),
               pxFirst=_r(min(fl, key=lambda f: f["ts"])["px"]), pxMin=_r(min(f["px"] for f in fl)), pxMax=_r(max(f["px"] for f in fl)))
    if deposit_ts:
        out["firstFromDepositMin"] = round((t_first - int(deposit_ts)) / 60, 1)
    cs = sorted(candles or (), key=lambda c: c[0])
    if not cs:
        return out
    avg = amt / q
    w0, w1 = t_first - PRE_S, t_last + 3600
    win = [c for c in cs if w0 - iv_s < c[0] < w1]
    if not win:
        return out
    hi_c = max(win, key=lambda c: c[2])
    lo_c = min(win, key=lambda c: c[3])
    hi, lo = hi_c[2], lo_c[3]
    out.update(hi=_r(hi), hiTs=hi_c[0], lo=_r(lo), loTs=lo_c[0], nCandles=len(win))
    rng = hi - lo
    pos = max(0.0, min(100.0, (avg - lo) / rng * 100)) if rng > 0 else 50.0
    out["posPct"] = round(pos, 1)
    out["topPct"] = round(100 - pos, 1)
    out["fromHighPct"] = _pct(avg, hi)
    out["fromLowPct"] = _pct(avg, lo)
    vt = sum(c[5] for c in win)
    if vt > 0:
        out["volPctile"] = round(100.0 * sum(c[5] for c in win if _typ(c) <= avg) / vt, 1)
    span = [c for c in win if t_first - iv_s < c[0] <= t_last]
    sv = sum(c[5] for c in span)
    if sv > 0:
        mv = sum(_typ(c) * c[5] for c in span) / sv
        out["mktVwap"] = _r(mv)
        out["vsVwapPct"] = _pct(avg, mv)
    t_now = int(now if now is not None else time.time())
    req9 = int(req_end) if req_end else (cs[-1][0] + iv_s)
    end = min(req9, t_now)
    aft, pending = {}, False
    for k, h in POST_S.items():
        if end < t_last + h:
            aft[k] = None
            if t_now < t_last + h <= req9:
                pending = True
            continue
        seg = [c for c in cs if t_last < c[0] + iv_s and c[0] < t_last + h]
        if not seg:
            aft[k] = None
            continue
        a_hi = max(seg, key=lambda c: c[2])
        a_lo = min(seg, key=lambda c: c[3])
        aft[k] = {"hi": _r(a_hi[2]), "hiTs": a_hi[0], "hiPct": _pct(a_hi[2], avg),
                  "lo": _r(a_lo[3]), "loTs": a_lo[0], "loPct": _pct(a_lo[3], avg), "close": _r(seg[-1][4]),
                  "closePct": _pct(seg[-1][4], avg)}
    out["after"] = aft
    if pending:
        out["afterPending"] = True
    far = next((aft[k] for k in ("24h", "6h", "1h") if aft.get(k)), None)
    if far:
        up = far["hi"] - avg
        out["missed"] = {"px": far["hi"], "pct": far["hiPct"] if up > 0 else 0.0,
                         "amt": _r(up * q) if up > 0 else 0, "horizon": next(k for k in ("24h", "6h", "1h") if aft.get(k))}
    vols = [c[5] for c in win]
    if len(win) >= 5 and max(vols) > 0:
        med = statistics.median(vols)
        q80 = sorted(vols)[int(SPIKE_TOP * (len(vols) - 1))]
        thr = max(med * SPIKE_MULT, q80)
        i_pk = max(range(len(win)), key=lambda i: win[i][5])
        a = b = i_pk
        while a - 1 >= 0 and win[a - 1][5] >= thr and win[a][0] - win[a - 1][0] <= iv_s:
            a -= 1
        while b + 1 < len(win) and win[b + 1][5] >= thr and win[b + 1][0] - win[b][0] <= iv_s:
            b += 1
        s_from, s_to = win[a][0], win[b][0] + iv_s
        in_q = sum(float(f["q"]) for f in fl if s_from <= f["ts"] < s_to)
        spike_c = [c for c in win if c[5] >= thr]
        top_q = sum(float(f["q"]) for f in fl if any(c[0] <= f["ts"] < c[0] + iv_s for c in spike_c))
        out["spike"] = {"from": s_from, "to": s_to, "sharePct": round(100.0 * in_q / q, 1),
                        "volSharePct": round(100.0 * sum(win[i][5] for i in range(a, b + 1)) / vt, 1) if vt else None,
                        "allSpikeSharePct": round(100.0 * top_q / q, 1), "peakTs": win[i_pk][0]}
    first_tr = next((c for c in cs if c[5] > 0), None)
    if first_tr and first_tr[0] > w0 + iv_s:
        out["openTs"] = first_tr[0]
        out["firstFromOpenMin"] = round((t_first - first_tr[0]) / 60, 1)
        out["openPx"] = _r(first_tr[1])
    return out


def downsample(candles, n=48):
    cs = sorted(candles or (), key=lambda c: c[0])
    if len(cs) <= n:
        return [list(c) for c in cs]
    k = math.ceil(len(cs) / n)
    out = []
    for i in range(0, len(cs), k):
        g = cs[i:i + k]
        out.append([g[0][0], g[0][1], max(c[2] for c in g), min(c[3] for c in g), g[-1][4], sum(c[5] for c in g)])
    return out


def _hm(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%H:%M")


_SYM_OK = re.compile(r"[^A-Za-z0-9._-]")
_LABEL_OK = re.compile(r"[^0-9A-Za-z가-힣 ./()·:_+-]")


def clean_sym(s) -> str:
    w = str(s or "").split()
    return (_SYM_OK.sub("", w[0]) if w else "")[:24] or "?"


def clean_label(s, n=60) -> str:
    return re.sub(r"\s+", " ", _LABEL_OK.sub(" ", str(s or ""))).strip()[:n]


def eval_input(date, sym, venue_label, src, summary, fills, candles, fills_max=30):
    cur = summary.get("cur") or "USD"
    sm = {k: v for k, v in summary.items() if k not in ("firstTs", "lastTs", "hiTs", "loTs", "openTs")}
    for k in ("firstTs", "lastTs", "hiTs", "loTs", "openTs"):
        if summary.get(k):
            sm[k.replace("Ts", "_t")] = _hm(summary[k])
    if isinstance(sm.get("spike"), dict):
        sp = dict(sm["spike"])
        sp["from"], sp["to"] = _hm(sp["from"]), _hm(sp["to"])
        sp.pop("peakTs", None)
        sm["spike"] = sp
    if isinstance(sm.get("after"), dict):
        sm["after"] = {k: ({kk: (_hm(vv) if kk.endswith("Ts") else vv) for kk, vv in v.items()} if v else None)
                       for k, v in sm["after"].items()}
    fl = sorted(fills, key=lambda f: -float(f.get("amt") or 0))[:fills_max]
    fl = sorted(fl, key=lambda f: f["ts"])
    return {"date": date, "sym": clean_sym(sym), "venue": clean_label(venue_label), "cur": cur, "cur_sym": CUR_SYM.get(cur, ""),
            "chart_src": clean_label((src or {}).get("label")) or None, "chart_fallback": bool((src or {}).get("fallback")),
            "chart_iv": (src or {}).get("iv"), "fx_converted": bool((src or {}).get("fx")),
            "summary": sm,
            "fills": [{"t": _hm(f["ts"]), "px": _r(f["px"]), "q": _r(f["q"]), "amt": _r(f.get("amt"))} for f in fl],
            "fills_total": len(fills),
            "candles": [[_hm(c[0]), _r(c[1]), _r(c[2]), _r(c[3]), _r(c[4]), _r(c[5])] for c in downsample(candles, 48)]}


def eval_fp(inp) -> str:
    return hashlib.sha1(json.dumps(inp, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


VERDICTS = ("잘 팔았음", "보통", "아쉬움")
BUY_VERDICTS = ("잘 샀음", "보통", "아쉬움")
_NUM_NOUNIT = re.compile(r"(?<![\d.,₩$%:])(\d+\.\d{3,})(?![\d%]|\s?%|\s?배|\s?분|\s?시간)")


def verdict_of(score, kind="sell"):
    return ("잘 샀음" if kind == "buy" else "잘 팔았음") if score >= 70 else ("보통" if score >= 40 else "아쉬움")


def normalize_eval(rv, cur="KRW", kind="sell", score=None):
    probs = []
    if not isinstance(rv, dict):
        return None, ["json"]
    fixed = score is not None
    try:
        score = int(round(float(score if fixed else rv.get("score"))))
    except (TypeError, ValueError):
        return None, ["json"]
    score = max(0, min(100, score))
    lines = rv.get("lines")
    if isinstance(lines, str):
        lines = [lines]
    lines = [common.strip_links(str(x)).strip() for x in (lines or []) if str(x).strip()]
    lines = [x for x in lines if x][:4]
    nxt = common.strip_links(str(rv.get("next") or "")).strip()
    if len(lines) < 2:
        return None, ["json"]
    lines = [x if len(x) <= 160 else x[:159].rstrip() + "…" for x in lines]
    if nxt.startswith("다음엔"):
        nxt = nxt[3:].lstrip(" :·")
    nxt = nxt[:140]
    v = "" if fixed else str(rv.get("verdict") or "").strip()
    v_score = verdict_of(score, kind)
    if v not in (BUY_VERDICTS if kind == "buy" else VERDICTS) or v != v_score:
        v = v_score
    for t in lines + [nxt]:
        if _NUM_NOUNIT.search(t):
            probs.append("unit")
            break
    return {"score": score, "verdict": v, "lines": lines, "next": nxt}, probs


class EvalStore:

    def __init__(self, state_dir=None, kind="sell"):
        sd = state_dir or common.STATE_DIR
        self.kind = "buy" if kind == "buy" else "sell"
        self.path = os.path.join(sd, f"{self.kind}_evals.json")
        self.budget_path = os.path.join(sd, f"{self.kind}_eval_budget.json")
        self.lock_path = os.path.join(sd, f"{self.kind}_eval.lock")
        self.mu = threading.Lock()
        self.running = {}
        self.errors = {}

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return None

    def get(self, date, sym):
        d = self._read() or {}
        pre = f"{date}|{sym}|"
        recs = sorted((dict(v, key=k) for k, v in d.items() if k.startswith(pre) and isinstance(v, dict)),
                      key=lambda r: -int(r.get("at") or 0))
        return recs

    def find(self, date, sym, fp):
        d = self._read() or {}
        r = d.get(f"{date}|{sym}|{fp}")
        return dict(r, key=f"{date}|{sym}|{fp}") if isinstance(r, dict) else None

    def put(self, date, sym, fp, rec) -> bool:
        with self.mu:
            fd = os.open(self.lock_path + ".w", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                d = self._read()
                if d is None:
                    return False
                new9 = f"{date}|{sym}|{fp}"
                d[new9] = rec
                pre9 = f"{date}|{sym}|"
                same9 = sorted((k for k in d if k.startswith(pre9)), key=lambda k: (-int((d[k] or {}).get("at") or 0), 0 if k == new9 else 1))
                for k in same9[EVAL_KEEP_PER:]:
                    d.pop(k, None)
                if len(d) > EVAL_KEEP:
                    for k in sorted(d, key=lambda k: int((d[k] or {}).get("at") or 0))[:len(d) - EVAL_KEEP]:
                        d.pop(k, None)
                common.atomic_write_json(self.path, d)
                return True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _budget_read(self, day):
        fresh = {"day": day, "used": 0, "keys": []}
        if not os.path.exists(self.budget_path):
            return fresh
        try:
            with open(self.budget_path, "r", encoding="utf-8") as f:
                b = json.load(f)
        except (OSError, ValueError):
            return {"day": day, "used": 10 ** 6, "keys": [], "_bad": True}
        if not isinstance(b, dict) or not isinstance(b.get("day"), str) or type(b.get("used")) is not int or b["used"] < 0:
            log.warning("AI 매도 평가 예산 파일 형식 이상 — 오늘 평가 보류(%s)", self.budget_path)
            return {"day": day, "used": 10 ** 6, "keys": [], "_bad": True}
        try:
            ok9 = datetime.strptime(b["day"], "%Y-%m-%d").strftime("%Y-%m-%d") == b["day"]
        except ValueError:
            ok9 = False
        if not ok9:
            log.warning("AI 매도 평가 예산 파일 날짜 이상(%r) — 오늘 평가 보류(%s)", b["day"][:20], self.budget_path)
            return {"day": day, "used": 10 ** 6, "keys": [], "_bad": True}
        if b["day"] < day:
            return fresh
        if b["day"] > day:
            return {"day": day, "used": 10 ** 6, "keys": [], "_bad": True}
        return {"day": day, "used": b["used"], "keys": [str(x) for x in (b.get("keys") or [])][-100:]}

    def budget(self, day, cap):
        with self.mu:
            b = self._budget_read(day)
        return {"used": min(b["used"], cap), "max": cap, "left": max(0, cap - b["used"]), "bad": bool(b.get("_bad"))}

    def budget_take(self, day, cap, key) -> bool:
        with self.mu:
            try:
                fd = os.open(self.lock_path + ".w", os.O_CREAT | os.O_RDWR, 0o600)
            except OSError:
                return False
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                b = self._budget_read(day)
                if b.get("_bad") or b["used"] >= cap:
                    return False
                b["used"] += 1
                b["keys"].append(key)
                b["at"] = int(time.time())
                try:
                    common.atomic_write_json(self.budget_path, b)
                except Exception:
                    return False
                return True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def slot_path(self, i):
        return self.lock_path if not i else f"{self.lock_path}.{int(i)}"

    def try_lock(self, slots=(0,)):
        for i in slots:
            try:
                os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
                fd = os.open(self.slot_path(i), os.O_CREAT | os.O_RDWR, 0o600)
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                os.close(fd)
        return None

    RECEIPT_STRIPES = 64
    RECEIPT_WAIT_S = 900

    def lock_receipt(self, key, wait_s=None):
        i9 = int(hashlib.sha1(key.encode()).hexdigest(), 16) % self.RECEIPT_STRIPES
        try:
            os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
            fd = os.open(f"{self.lock_path}.r{i9:02d}", os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            return None
        end = time.time() + (self.RECEIPT_WAIT_S if wait_s is None else wait_s)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.time() >= end:
                    os.close(fd)
                    return None
                time.sleep(0.2)

    @staticmethod
    def unlock(fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def daily_max(cfg, kind="sell") -> int:
    try:
        v = int(((cfg or {}).get("review") or {}).get("buy_eval_daily_max" if kind == "buy" else "sell_eval_daily_max", EVAL_DAILY_MAX))
    except (TypeError, ValueError, AttributeError):
        return EVAL_DAILY_MAX
    return max(0, min(EVAL_DAILY_CAP, v))


def budget_msg(cap, kind="sell") -> str:
    side_ko = "매수" if kind == "buy" else "매도"
    try:
        n = int(cap or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        key = "buy_eval_daily_max" if kind == "buy" else "sell_eval_daily_max"
        return f"AI {side_ko} 평가가 꺼져 있어요 — 켜려면 config.json 의 review.{key} 를 1 이상(하루 최대 횟수)으로"
    return f"오늘 AI {side_ko} 평가 한도({n}회)를 다 썼어요"


def run_eval(store, cfg, date, sym, fp, inp, runner=None, binfn=None, now=None, slots=(0,), model=None, skip_if_fresh=True):
    rd = None
    if runner is None or binfn is None or model is None:
        import review_daily as rd
    import review_prompt as rp
    kind = getattr(store, "kind", "sell")
    side_ko = "매수" if kind == "buy" else "매도"
    key = f"{date}|{sym}"
    fd = store.try_lock(slots)
    if fd is None:
        return None, f"다른 {side_ko} 평가가 진행 중이에요"
    rfd = None
    try:
        rfd = store.lock_receipt(key)
        if rfd is None:
            return None, f"다른 {side_ko} 평가가 진행 중이에요"
        if skip_if_fresh:
            old9 = store.find(date, sym, fp)
            if old9 and old9.get("pv") == (rp.BUY_EVAL_VERSION if kind == "buy" else rp.SELL_EVAL_VERSION):
                return old9, None
        cap = daily_max(cfg, kind)
        if cap <= 0:
            return None, budget_msg(0, kind)
        b = (binfn or rd.claude_bin)()
        if not b:
            return None, "claude CLI 를 찾지 못했어요"
        day = datetime.fromtimestamp(now or time.time(), KST).strftime("%Y-%m-%d")
        nonce = secrets.token_hex(8)
        prompt = rp.buy_eval_prompt(nonce) if kind == "buy" else rp.sell_eval_prompt(nonce)
        if inp.get("memo"):
            prompt = rp.with_day_memo_rule(prompt, "eval")
        body = f"<<<DATA {nonce}>>>\n" + json.dumps(inp, ensure_ascii=False, separators=(",", ":")) + f"\n<<<END {nonce}>>>"
        run = runner or (lambda b9, p9, body9: rd._run_cli(b9, p9, None, f"{side_ko}평가 {key}", body=body9))
        sc9 = (inp.get("summary") or {}).get("score") if isinstance(inp.get("summary"), dict) else None
        fixed9 = sc9.get("total") if isinstance(sc9, dict) else None
        if fixed9 is None:
            return None, "점수를 계산할 시세 숫자가 없어요"
        out, probs, calls = None, [], 0
        for attempt in range(2):
            if not store.budget_take(day, cap, f"{key}|{fp}"):
                if calls:
                    break
                return None, budget_msg(cap, kind)
            calls += 1
            rv = run(b, prompt if attempt == 0 else prompt.replace("\n데이터:\n", rp.SELL_EVAL_RETRY.format(probs="·".join(probs or ["json"])) + "데이터:\n"), body)
            res, probs = normalize_eval(rv, inp.get("cur") or "USD", kind, score=fixed9)
            if res is not None and (not probs or attempt == 1):
                out = res
                break
            if res is not None:
                out = res
        if out is None:
            rd9 = rd or sys.modules.get("review_daily") or sys.modules.get("__main__")
            msg9 = "모델 응답을 읽지 못했어요(형식)"
            if rd9 is not None and hasattr(rd9, "cli_error_text"):
                try:
                    msg9 = rd9.cli_error_text(msg9)
                except Exception:
                    pass
            return None, msg9
        rec = dict(out, date=date, sym=sym, fp=fp, at=int(now or time.time()), model=model if model is not None else getattr(rd, "REVIEW_MODEL", ""),
                   pv=rp.BUY_EVAL_VERSION if kind == "buy" else rp.SELL_EVAL_VERSION, calls=calls, venue=inp.get("venue"), src=inp.get("chart_src"),
                   iv=inp.get("chart_iv"), cur=inp.get("cur"), nFills=inp.get("fills_total"),
                   warn=["unit"] if "unit" in (probs or []) else [],
                   components=sc9.get("components"), scaled=bool(sc9.get("scaled")), scoreBy="calc",
                   **({"memoUsed": True} if inp.get("memo") else {}))
        if not store.put(date, sym, fp, rec):
            return None, f"평가 저장 실패({kind}_evals.json 손상?)"
        return dict(rec, key=f"{key}|{fp}"), None
    finally:
        try:
            if rfd is not None:
                EvalStore.unlock(rfd)
        finally:
            EvalStore.unlock(fd)
