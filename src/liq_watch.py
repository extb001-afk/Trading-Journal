from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import common
import alert_prefs as AP

log = logging.getLogger("tj-exf")

STATE_NAME = "liq_watch.json"
UA = "Mozilla/5.0 (tj-bot liq watch, read-only)"
MAX_BYTES = 4 * 1024 * 1024

TICK = 0.5
DISC_SEC = 5.0
POS_SEC = 30.0
MARK_SEC = 5.0
MARK_NEAR_SEC = 2.0
KICK_GAP = 5.0
BIG_MOVE = 0.02
RISK_SEC = 60.0
RISK_PX_SEC = 5.0
RISK_PX_NEAR = 2.0
THR_SEC = 6 * 3600
COEFF_SEC = 600
THR_RETRY = 600
MARK_FRESH = 15
PX0_LAG = 10
POS_ALERT_AGE = 600
POS_RESOLVE_AGE = 90
RISK_ALERT_AGE = 600
RISK_RESOLVE_AGE = 120
SLOW_AGE = 1800
FILE_FORGET = 86400
RESOLVE_X = 1.5
WARN_X = 0.9
NEAR_X = 0.8
RESOLVE_RISK_X = 0.9 * 0.95
RESOLVE_HOLD = 60
CALM_GAP = 75
STABLES = frozenset({"USDT", "USDC", "FDUSD", "BUSD", "DAI", "TUSD", "USDP", "USD", "PYUSD", "USD1", "USDG"})
EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "hyperliquid": "하이퍼리퀴드", "dydx": "dYdX", "lighter": "라이터",
         "gmx": "GMX", "jupiter": "Jupiter", "pacifica": "Pacifica"}
FAST_EX = ("binance", "bybit", "okx")
NEED_KEYS = {"binance": ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"), "bybit": ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"),
             "okx": ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE")}
LEV_KEYS = dict(NEED_KEYS, kucoin=("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE"), gate=("TJ_GATE_KEY", "TJ_GATE_SECRET"))
TJ_DEFAULT = "tj:default-0.8"
THR_TAIL = {"doc": "기준: 거래소 공식 문서", "tj": "기준: tj-bot 기본(거래소가 마진콜 기준을 주지 않음)"}
DOC_BYBIT_LOAN = ("doc:https://www.bybit.com/en/help-center/article/Introduction-to-Crypto-Loans "
                  "(통합 담보대출 · 문서 기준: 초기 80% · 마진콜 85% · 지연 청산 93% · 청산 95%)")
BYBIT_LOAN_CALL, BYBIT_LOAN_LIQ = 0.85, 0.95
DEX_ACCT_DOC = {"dydx": "doc:https://docs.dydx.xyz/concepts/trading/liquidations (서브계정 가치 < 유지증거금 = 청산)",
                "lighter": "doc:https://docs.lighter.xyz/trading/liquidations-and-llp-insurance-fund (계정 가치 < 유지증거금 = 부분 청산)",
                "pacifica": "doc:https://docs.pacifica.fi/trading-on-pacifica/liquidations (교차 가치 < 유지증거금 = 청산)"}
DEX_PROD = "perp_account"

BUCKETS = {
    "bn_fapi": (60, 360),
    "bn_api": (60, 300),
    "bn_sapi": (60, 600),
    "bybit_ip": (5, 30),
    "okx_pos": (2, 2),
    "okx_loan": (2, 1),
    "okx_mark": (2, 2),
    "okx_tick": (2, 4),
    "hl": (60, 240),
}
BN_HDR = {"fapi.binance.com": ("x-mbx-used-weight-1m", 2400), "api.binance.com": ("x-mbx-used-weight-1m", 6000)}
BN_SAPI_HDR = ("x-sapi-used-ip-weight-1m", 12000)
HDR_HOLD_AT = 0.8
PERM_COOL = 6 * 3600
PERM_CODES = {"binance": {-2015, -2014, -1002, -1022, -2008}, "bybit": {10003, 10004, 10005, 10010, 33004},
              "okx": {50111, 50113, 50119, 50120, 50125, 50030, 58350}}
RL_CODES = {"binance": {-1003}, "bybit": {10006, 10018}, "okx": {50011, 50061}}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _num_req(row, field, signed=False, what=""):
    v = row.get(field) if isinstance(row, dict) else None
    n = None if isinstance(v, bool) else _f(v)
    if n is None or (not signed and n < 0):
        raise ValueError(f"{what} 응답 {field} 형식 오류")
    return n


def _list_req(obj, field, what=""):
    v = obj.get(field) if isinstance(obj, dict) else None
    if not isinstance(v, list) or any(not isinstance(x, dict) for x in v):
        raise ValueError(f"{what} 응답 {field} 목록 형식 오류")
    return v


def _str_req(row, field, what=""):
    v = row.get(field) if isinstance(row, dict) else None
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{what} 응답 {field} 형식 오류")
    return v.strip()


def px_txt(p) -> str:
    v = _f(p)
    if v is None:
        return "—"
    if v >= 100:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:,.4f}"
    return f"${v:.6g}"


def pct(v, d=1) -> str:
    s9 = f"{v:.{d}f}"
    if v > 0 and float(s9) == 0:
        return f"{v:.2g}%"
    return s9 + "%"


class HttpErr(Exception):
    def __init__(self, status, body="", headers=None):
        super().__init__(f"HTTP {status} {common.safe_err(body)[:160]}")
        self.status, self.body, self.headers = status, body or "", headers or {}


class ApiErr(Exception):

    def __init__(self, ex, code, msg=""):
        super().__init__(f"{ex} {code} {common.safe_err(str(msg))[:120]}")
        self.ex, self.code = ex, code


class Wait(Exception):
    pass


def _http_default(method, url, headers=None, body=None, timeout=6.0):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    h = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("응답 크기 초과")
            return r.status, {k.lower(): v for k, v in r.headers.items()}, json.loads(raw.decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        hd = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        try:
            txt = e.read(2048).decode("utf-8", "replace")
        except Exception:
            txt = ""
        raise HttpErr(e.code, txt[:400], hd) from None


HTTP = _http_default


class _Lim:

    def __init__(self):
        self.q, self.hold, self.lock = {}, {}, threading.Lock()

    def take(self, bucket, kind, w, now) -> bool:
        win, cap = BUCKETS[kind]
        with self.lock:
            if now < self.hold.get(bucket, 0):
                return False
            q = self.q.setdefault(bucket, deque())
            while q and q[0][0] <= now - win:
                q.popleft()
            if sum(x[1] for x in q) + w > cap:
                return False
            q.append((now, w))
            return True

    def hold_until(self, bucket, until):
        with self.lock:
            self.hold[bucket] = max(self.hold.get(bucket, 0), until)

    def used(self, bucket, now) -> int:
        win = BUCKETS.get(bucket.split(":", 1)[0], (60, 0))[0]
        with self.lock:
            return int(sum(w for t, w in self.q.get(bucket, ()) if t > now - win))


class _FileCache:

    def __init__(self, path_fn, default):
        self.path_fn, self.default, self.sig, self.val = path_fn, default, None, default

    def get(self):
        p = self.path_fn()
        try:
            st = os.stat(p)
            sig = (p, st.st_mtime_ns, st.st_size)
        except OSError:
            sig = (p, None, None)
        if sig != self.sig:
            self.sig = sig
            if sig[1] is None:
                self.val = self.default
                return self.val
            try:
                with open(p, "r", encoding="utf-8") as f:
                    v = json.load(f)
                if not isinstance(v, dict):
                    raise ValueError("JSON 객체 아님")
                self.val = v
            except (OSError, ValueError) as e:
                log.warning("청산 감시 설정 파일 읽기 실패(마지막 정상 값 유지): %s · %s", os.path.basename(p), common.safe_err(e)[:80])
        return self.val


def fut_dist(liq, mark, side=None):
    liq, mark = _f(liq), _f(mark)
    if not liq or not mark or liq <= 0 or mark <= 0:
        return None
    sd = str(side or "").upper()
    if (sd == "LONG" and mark <= liq) or (sd == "SHORT" and mark >= liq):
        return 0.0
    return abs(liq - mark) / mark * 100


def side_ok(side) -> bool:
    return str(side or "").upper() in ("LONG", "SHORT")


def _side_ko(side) -> str:
    return {"LONG": "롱", "SHORT": "숏"}.get(str(side or "").upper(), str(side or ""))


def _alert(kind, text, meta):
    return kind, text, meta


def judge_futures(mem: dict, rows: list, gone: list, th: float, now: float, link: str = "") -> list:
    out = []
    for r in rows:
        k, d = r["key"], r.get("dist")
        if d is None:
            continue
        e = mem.get(k) if isinstance(mem.get(k), dict) else None
        ex9 = EX_KO.get(r.get("ex"), r.get("ex") or "")
        nums = f"현재 {px_txt(r.get('mark'))} · 청산 {px_txt(r.get('liq'))} · {ex9}" + (f" · 레버리지 {r['lev']}x" if r.get("lev") else "")
        nopct = "side" in r and not side_ok(r.get("side"))
        cross = d <= 0
        if r.get("stale_liq"):
            nums += f" · 청산가는 {int(r['stale_liq'] // 60)}분 전 값"
        if e is None:
            if d <= th and r.get("alert_ok"):
                mem[k] = {"st": 1, "d1": round(d, 3), "at": int(now), "name": r["name"], "ex": r.get("ex")}
                if r.get("levsrc"):
                    mem[k]["levsrc"] = list(r["levsrc"])
                h1 = (f"🔴 {r['name']} 선물 가격이 청산가에 닿았거나 지났어요" if cross else
                      f"🔴 {r['name']} 선물 청산가에 가까워요" if nopct else f"🔴 {r['name']} 선물 청산가까지 {pct(d)} 남았어요")
                out.append(_alert("LIQ_NEAR", f"{h1}\n증거금을 넣거나 포지션을 줄이세요.\n{nums}{link}",
                            {"k": k, "g": "fut", "st": 1, "d1": round(d, 3), "n": r["name"]}))
            continue
        st, d1 = int(e.get("st") or 1), _f(e.get("d1")) or th
        if st < 2 and d <= d1 / 2 and r.get("alert_ok"):
            e.update(st=2, at=int(now))
            h2 = (f"🔴 {r['name']} 가격이 청산가에 닿았거나 지났어요" if cross else
                  f"🔴 {r['name']} 청산가에 더 가까워졌어요" if nopct else f"🔴 {r['name']} 청산가까지 {pct(d)}로 더 가까워졌어요")
            out.append(_alert("LIQ_NEAR", f"{h2}\n지금 증거금을 넣거나 포지션을 줄이세요.\n{nums}{link}",
                        {"k": k, "g": "fut", "st": 2, "d1": d1, "n": r["name"]}))
        elif d > th * RESOLVE_X and r.get("resolve_ok"):
            del mem[k]
            out.append(_alert("LIQ_NEAR", f"✅ {r['name']} 청산 위험에서 벗어났어요\n할 일은 없어요.\n" + (ex9 if nopct else f"청산가까지 {pct(d)} · {ex9}"),
                        {"k": k, "g": "fut", "st": 0}))
    for k in gone:
        e = mem.pop(k, None)
        if isinstance(e, dict):
            out.append(_alert("LIQ_NEAR", f"✅ {e.get('name') or k} 포지션이 닫혀 청산 감시를 끝내요\n할 일은 없어요 — 손익은 앱 선물 기록에서 보세요.",
                        {"k": k, "g": "fut", "st": 0}))
    return out


def risk_stage(r, call, liq) -> int:
    if r is None or not call or call <= 0:
        return 0
    if liq and liq > call and r >= (call + liq) / 2:
        return 3
    if r >= call:
        return 2
    return 1 if r >= call * WARN_X else 0


def drop_to_liq(r, liq):
    if r is None or not liq or liq <= 0:
        return None
    return max(0.0, (1 - r / liq) * 100)


def iso_side(debt_ccys, base, quote):
    d = {str(c or "").upper() for c in debt_ccys or () if c}
    b, q = str(base or "").upper(), str(quote or "").upper()
    if not b or not q or b == q:
        return None
    return "SHORT" if d == {b} else "LONG" if d == {q} else None


def _item_pair_side(it):
    ps = it.get("_pside")
    if ps in ("LONG", "SHORT"):
        return ps
    if it.get("product") != "margin_isolated":
        return None
    sym = str(it.get("key") or "").upper()
    d = {str(x.get("ccy") or "").upper() for x in it.get("debt") or () if isinstance(x, dict) and x.get("ccy")}
    if len(d) != 1 or not sym:
        return None
    c = next(iter(d))
    if len(sym) <= len(c):
        return None
    if sym.endswith(c) and not sym.startswith(c):
        return iso_side(d, sym[:-len(c)], c)
    if sym.startswith(c) and not sym.endswith(c):
        return iso_side(d, c, sym[len(c):])
    return None


def px_gap(index_px, liq_px, side):
    ip, lp = _f(index_px), _f(liq_px)
    if not ip or not lp or ip <= 0 or lp <= 0 or side not in ("LONG", "SHORT"):
        return None, False
    g = ((ip - lp) if side == "LONG" else (lp - ip)) / ip * 100
    return (None, True) if g <= 0 else (g, False)


METRIC_ORDER = ("ltv", "margin_level", "mgn_ratio", "mm_rate", "debt_ratio", "risk_rate")
METRIC_KO = {"ltv": "LTV", "margin_level": "마진 레벨", "mgn_ratio": "증거금 비율", "mm_rate": "유지증거금률", "debt_ratio": "부채 비율",
             "risk_rate": "위험률"}
METRIC_SUBJ = {"ltv": "LTV가", "margin_level": "마진 레벨이", "mgn_ratio": "증거금 비율이", "mm_rate": "유지증거금률이", "debt_ratio": "부채 비율이",
               "risk_rate": "위험률이"}
OFFICIAL_STAGE = {0: 0, 1: 2, 2: 3, 3: 3}


def _has_thr(m) -> bool:
    return (isinstance(m, dict) and (m.get("v") is not None or m.get("inf")) and str(m.get("thr_src") or "unknown") != "unknown"
            and bool(_f(m.get("call")) or _f(m.get("liq"))))


def pick_metric(it):
    ms = it.get("metrics") if isinstance(it.get("metrics"), dict) else {}
    first = None
    for name in METRIC_ORDER:
        m = ms.get(name)
        if isinstance(m, dict) and (m.get("v") is not None or m.get("inf")):
            if _has_thr(m):
                return name, m
            first = first or (name, m)
    return first or (None, None)


def thr_kind(m) -> str:
    t = str((m or {}).get("thr_src") or "")
    return ("api" if t.startswith("api:") else "doc" if t.startswith("doc:") else "tj" if t.startswith("tj:")
            else "config" if t.startswith("config:") else "unknown")


def bybit_loan_thr(cfg):
    al = cfg.get("alerts") if isinstance(cfg, dict) else None
    lt = al.get("loan_ltv") if isinstance(al, dict) else None
    b = lt.get("bybit") if isinstance(lt, dict) else None
    if isinstance(b, dict):
        c, lq = _f(b.get("call")), _f(b.get("liq"))
        if c is not None and 0 < c < 1 and (lq is None or c < lq <= 1.5):
            return c, lq, "config:alerts.loan_ltv.bybit"
    return BYBIT_LOAN_CALL, BYBIT_LOAN_LIQ, DOC_BYBIT_LOAN


def norm_metric(m):
    up = m.get("risk") != "down"

    def inv(x):
        x = _f(x)
        return (1.0 / x) if (x and x > 0) else None
    r = 0.0 if m.get("inf") else (_f(m.get("v")) if up else inv(m.get("v")))
    call = _f(m.get("call")) if up else inv(m.get("call"))
    liq = _f(m.get("liq")) if up else inv(m.get("liq"))
    if m.get("thr_src") == "unknown":
        call = liq = None
    return r, call, liq


def _asset_ratio_model(it) -> bool:
    if pick_metric(it)[0] == "mgn_ratio":
        return False
    if it.get("ex") == "binance" and it.get("product") == "margin_cross":
        raw = it.get("raw") if isinstance(it.get("raw"), dict) else {}
        return raw.get("accountType") == "MARGIN_1"
    return True


def _disp(name, m, x):
    if x is None:
        return "—"
    v = x if (m or {}).get("risk") != "down" else ((1.0 / x) if x > 0 else None)
    if v is None:
        return "—"
    return f"{v * 100:.1f}%" if (m or {}).get("unit") == "frac" else f"{v:.2f}"


def risk_row(it, now, prices=None, fast=False):
    name, m = pick_metric(it)
    off = it.get("official_state") if isinstance(it.get("official_state"), dict) else {}
    lv = off.get("level")
    st_off = OFFICIAL_STAGE.get(lv) if isinstance(lv, int) and not isinstance(lv, bool) else None
    r0, call, liq = norm_metric(m) if m else (None, None, None)
    if call is None and st_off is None:
        return None
    r, moved, pfresh = r0, False, False
    if fast and r0 is not None and name in ("ltv", "margin_level"):
        r, moved, pfresh = estimate_ratio(it, prices or {}, now, r0)
    coll = "/".join(sorted({c.get("ccy") for c in (it.get("collateral") or []) if isinstance(c, dict) and c.get("ccy") not in STABLES})[:3]) or "담보"
    raw = it.get("raw") if isinstance(it.get("raw"), dict) else {}
    lp, ip = _f(raw.get("liquidatePrice")), _f(raw.get("indexPrice"))
    pside = _item_pair_side(it) if (lp and ip) else None
    gap, cross = px_gap(ip, lp, pside)
    return {"key": it.get("id"), "ex": it.get("ex"), "product": it.get("product"), "label": it.get("label") or it.get("id"),
            "kind": "loan" if it.get("product") == "loan" else "margin", "metric": name, "m": m, "r": r, "call": call, "liq": liq,
            "st_off": st_off, "off_level": lv if st_off is not None else None, "off_v": off.get("v"), "est": moved, "pfresh": pfresh, "coll": coll,
            "drop_px": gap, "px_cross": cross, "px_side": pside, "drop_unknown": not _asset_ratio_model(it)}


def _risk_nums(x) -> str:
    name, m = x.get("metric"), x.get("m") or {}
    bits = []
    if name:
        s = f"{METRIC_KO.get(name, name)} {_disp(name, m, x.get('r'))}"
        if x.get("call"):
            s += f" · 마진콜 {_disp(name, m, x['call'])}"
        if x.get("liq"):
            s += f" · 청산 {_disp(name, m, x['liq'])}"
        bits.append(s)
    if x.get("off_v"):
        bits.append(f"거래소 상태 {x['off_v']}")
    s = " · ".join(bits) or "—"
    if x.get("est"):
        s += f" (시세로 추정 · 거래소 값 {int(x.get('age') or 0)}초 전)"
    tail = THR_TAIL.get(thr_kind(m)) if (name and x.get("call")) else None
    if tail:
        s += f"\n{tail}"
    return s


def judge_risk(mem: dict, rows: list, gone: list, now: float, link: str = "") -> list:
    out = []
    for x in rows:
        k = x["key"]
        s_r = risk_stage(x.get("r"), x.get("call"), x.get("liq")) if x.get("call") else 0
        s = max(s_r, x.get("st_off") or 0)
        e = mem.get(k) if isinstance(mem.get(k), dict) else None
        told = int((e or {}).get("st") or 0)
        drop = drop_to_liq(x.get("r"), x.get("liq")) if x.get("liq") else _f(x.get("drop_px"))
        if x.get("drop_unknown") and drop is not None and drop > 0:
            drop = None
        if not x.get("liq") and (x.get("px_cross") or (drop is not None and drop <= 0)):
            dtxt = "가격이 이미 청산가에 닿았거나 지났어요"
        elif drop is None:
            dtxt = "청산까지 남은 폭은 계산할 수 없어요"
        elif x.get("liq") and drop <= 0:
            dtxt = "이미 청산 기준에 닿았어요"
        elif x.get("liq") and x.get("metric") == "mm_rate":
            dtxt = f"청산까지 계정 가치가 {pct(drop)} 더 줄면 청산돼요"
        elif x.get("liq") and x.get("kind") == "loan":
            dtxt = f"청산까지 {x.get('coll') or '담보'} 가치가 {pct(drop)} 더 떨어지면 청산돼요"
        elif x.get("liq"):
            dtxt = f"청산까지 자산 가치가 {pct(drop)} 더 줄면(빌린 코인 값이 오르면 더 빨리) 청산돼요"
        else:
            way = {"LONG": "내리면", "SHORT": "오르면"}.get(x.get("px_side"))
            dtxt = f"청산가까지 {pct(drop)} 남았어요" + (f"(가격이 그만큼 더 {way} 청산)" if way else "")
        what = x.get("label") or k
        loan = x.get("kind") == "loan"
        if s > told and x.get("alert_ok"):
            mem[k] = {"st": s, "at": int(now), "label": what}
            subj = METRIC_SUBJ.get(x.get("metric") or "", "위험 지표가")
            head = {1: f"🔴 {what}: {subj} 마진콜 문턱의 90%에 닿았어요",
                    2: f"🔴 {what}: 마진콜에 닿았어요(긴급)",
                    3: f"🔴 {what}: 청산이 진행 중이에요(긴급)" if x.get("off_level") == 3 else f"🔴 {what}: 청산 직전이에요(긴급)"}[s]
            if x.get("metric") == "mm_rate" or x.get("product") == DEX_PROD:
                todo = {1: "증거금을 더 넣거나 포지션을 줄여 두세요.", 2: "지금 증거금을 넣거나 포지션을 줄이세요.",
                        3: "지금 바로 증거금을 넣거나 포지션을 줄이세요."}[s]
            else:
                todo = {1: "담보를 더 넣거나 일부 갚아 두세요.", 2: "지금 담보를 넣거나 갚으세요.", 3: "지금 바로 담보를 넣거나 갚으세요."}[s]
            txt9, meta9 = f"{head}\n{todo} {dtxt}.\n{_risk_nums(x)}{link}", {"k": k, "g": "risk", "st": s, "n": what}
            out.append(_alert("LOAN_RISK", txt9, meta9) if loan else _alert("MARGIN_RISK", txt9, meta9))
            continue
        if e is not None:
            if not x.get("resolve_ok"):
                continue
            calm_r = x.get("r") is not None and (x["r"] < x["call"] * RESOLVE_RISK_X if x.get("call") else True)
            calm_o = (x.get("st_off") or 0) == 0
            if not (calm_r and calm_o):
                e.pop("calm", None)
                e.pop("calm_last", None)
                continue
            if e.get("calm") is None or now - float(e.get("calm_last") or 0) > float(x.get("gap") or CALM_GAP):
                e["calm"] = int(now)
            e["calm_last"] = int(now)
            if now - float(e["calm"]) >= RESOLVE_HOLD:
                del mem[k]
                txt9, meta9 = f"✅ {what}: 위험 구간에서 벗어났어요\n할 일은 없어요.\n{_risk_nums(x)}", {"k": k, "g": "risk", "st": 0}
                out.append(_alert("LOAN_RISK", txt9, meta9) if loan else _alert("MARGIN_RISK", txt9, meta9))
    for k in gone:
        e = mem.pop(k, None)
        if isinstance(e, dict):
            why9 = "빚이 없어져" if ":loan:" in k else "빚·포지션이 정리돼"
            txt9, meta9 = f"✅ {e.get('label') or k}: {why9} 감시를 끝내요\n할 일은 없어요.", {"k": k, "g": "risk", "st": 0}
            out.append(_alert("LOAN_RISK", txt9, meta9) if ":loan:" in k else _alert("MARGIN_RISK", txt9, meta9))
    return out


def estimate_ratio(it: dict, prices: dict, now: float, r0=None):
    if r0 is None:
        return None, False, False
    if not _asset_ratio_model(it):
        return r0, False, False
    px0 = it.get("_px0") or {}
    a0 = a1 = l0 = l1 = 0.0
    moved = False
    hair = bool(it.get("_haircut"))
    rows_a = [c for c in it.get("collateral") or () if isinstance(c, dict) and (_f(c.get("qty")) or 0) > 0]
    if hair and len(rows_a) > 1 and any(_f(c.get("_value0")) is None or _f(c.get("_value0")) < 0 for c in rows_a):
        return r0, False, False
    fresh_ok = True
    for side, rows in (("a", it.get("collateral")), ("l", it.get("debt"))):
        for c in rows or ():
            if not isinstance(c, dict):
                return r0, False, False
            sym, q = c.get("ccy"), _f(c.get("qty") if "qty" in c else c.get("total"))
            if q is None:
                return r0, False, False
            if q <= 0:
                continue
            if sym in STABLES:
                p0 = p1 = 1.0
            else:
                p0, pn = _f(px0.get(sym)), prices.get(sym)
                if not p0 or not pn or now - pn[1] > MARK_FRESH or not _f(pn[0]):
                    return r0, False, False
                p1, moved = float(pn[0]), True
            if side == "a":
                if hair:
                    v0 = _f(c.get("_value0"))
                    v0 = v0 if (v0 is not None and v0 >= 0 and len(rows_a) > 1) else q * p0
                    a0, a1 = a0 + v0, a1 + v0 * (p1 / p0)
                    if p1 > p0:
                        fresh_ok = False
                else:
                    a0, a1 = a0 + q * p0, a1 + q * p1
            else:
                l0, l1 = l0 + q * p0, l1 + q * p1
    if a0 <= 0 or a1 <= 0 or l0 <= 0 or l1 <= 0:
        return r0, False, False
    return r0 * (l1 / l0) / (a1 / a0), moved, fresh_ok


def lev_item(ex, product, scope, key, label, now, metrics=None, debt=None, collateral=None, raw=None, state=None):
    it = {"id": f"{ex}:{product}:{scope}:{key}", "ex": ex, "product": product, "scope": scope, "key": str(key), "label": label,
          "measured_at": int(now), "stale": False,
          "metrics": {k: v for k, v in (metrics or {}).items() if v and (v.get("v") is not None or v.get("inf"))}}
    if debt:
        it["debt"] = [x for x in debt if x]
    if collateral:
        it["collateral"] = [x for x in collateral if x]
    if raw:
        it["raw"] = {k: v for k, v in raw.items() if v not in (None, "")}
    if state:
        it["official_state"] = state
    return it


def lev_metric(v, unit, risk, call=None, liq=None, warn=None, thr_src="unknown", src="", inf=False):
    return {"v": v, "unit": unit, "risk": risk, "warn": warn, "call": call, "liq": liq, "thr_src": thr_src, "src": src, **({"inf": True} if inf else {})}


LEV_STATE_LEVEL = {"EXCESSIVE": 0, "NORMAL": 0, "MARGIN_CALL": 1, "PRE_LIQUIDATION": 2, "FORCE_LIQUIDATION": 3}


def lev_fresh(doc, now):
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return {"v": 1, "missing": True, "products": [], "items": []}
    d = json.loads(json.dumps(doc))
    try:
        fs = int(d.get("fresh_sec") or 1800)
    except (TypeError, ValueError):
        fs = 1800
    for pr in d.get("products") or []:
        if isinstance(pr, dict):
            ma, st = pr.get("measured_at"), pr.get("status")
            pr["status_eff"] = "stale" if st == "ok" and (not isinstance(ma, (int, float)) or now - ma > fs) else st
    for it in d.get("items") or []:
        if isinstance(it, dict):
            ma = it.get("measured_at")
            it["fresh"] = bool(not it.get("stale") and isinstance(ma, (int, float)) and now - ma <= fs)
    return d


def _absent(mem, k, now) -> bool:
    e = mem.get(k)
    if not isinstance(e, dict):
        return False
    a = e.setdefault("absent", int(now))
    return now - float(a) >= FILE_FORGET


def _slow_rows_ok(positions, want) -> bool:
    for p in positions:
        if not isinstance(p, dict) or not isinstance(p.get("acct"), str):
            return False
        if p["acct"] not in want:
            continue
        q = None if isinstance(p.get("qty"), bool) else _f(p.get("qty"))
        if not isinstance(p.get("symbol"), str) or not p["symbol"].strip() or not side_ok(p.get("side")) or q is None or q <= 0:
            return False
    return True


def _lev_ok(lev) -> bool:
    items = lev.get("items")
    if not isinstance(items, list):
        return False
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not it["id"] or not isinstance(it.get("scope"), str):
            return False
        if it["scope"] == "position":
            p = it.get("position")
            q = None if not isinstance(p, dict) or isinstance(p.get("qty"), bool) else _f(p.get("qty"))
            if not isinstance(p, dict) or not isinstance(p.get("symbol"), str) or not p["symbol"].strip() or not side_ok(p.get("side")) or q is None:
                return False
    return True


class Watcher:

    def __init__(self, env_fn=None, rl_map=None, clock=time.time, workers=12, sync=False):
        self.env_fn = env_fn or (lambda: {})
        self.rl = rl_map if rl_map is not None else {}
        self.clock = clock
        self.sync = sync
        self.pool = None if sync else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="liqw")
        self.lim = _Lim()
        self.cfg_c = _FileCache(lambda: common.CONFIG_PATH, {})
        self.prefs_c = _FileCache(lambda: AP.PREFS_PATH, {})
        self.jobs = {}
        self.v = {}
        self.risk = {}
        self.px = {}
        self.thr = {}
        self.calls = 0
        self.gate = (False, "시작 전")
        self.env_sig = None
        self.t0 = float(self.clock())
        self.kchg = {}
        self.gen = 0
        self.kgen = {}
        self.agen = {}
        self.st = self._load()
        self.dirty = False
        self.last_save = 0.0
        self.qpath = os.path.join(common.STATE_DIR, AP.FAST_QUEUE)
        self._reconcile()

    def _load(self):
        try:
            d = common.read_json(os.path.join(common.STATE_DIR, STATE_NAME), {}) or {}
        except (Exception, SystemExit):
            log.warning("청산 감시 기억 파일 손상 — 새로 시작(알림 줄 기록으로 되살림)")
            d = {}
        d = d if isinstance(d, dict) else {}
        mv = d.get("moved") if isinstance(d.get("moved"), dict) else {}
        self.__dict__["_saved_ts"] = float(_f(d.get("ts")) or 0)
        return {"v": 1, "fut": d.get("fut") if isinstance(d.get("fut"), dict) else {},
                "risk": d.get("risk") if isinstance(d.get("risk"), dict) else {},
                "moved": {str(a): str(b) for a, b in mv.items() if isinstance(b, str)}}

    def _reconcile(self):
        try:
            with open(self.qpath, "rb") as f:
                f.seek(0, os.SEEK_END)
                n = f.tell()
                f.seek(max(0, n - 256 * 1024))
                tail = f.read().split(b"\n")
        except OSError:
            return
        for raw in tail:
            try:
                d = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            lw = d.get("lw") if isinstance(d, dict) else None
            if not isinstance(lw, dict) or lw.get("g") not in ("fut", "risk") or not lw.get("k"):
                continue
            mem = self.st[lw["g"]]
            k, ts, s = str(lw["k"]), int(d.get("ts") or 0), int(lw.get("st") or 0)
            if ts < float(self.__dict__.get("_saved_ts") or 0) - 1:
                continue
            k = (self.st.get("moved") or {}).get(k, k)
            cur = mem.get(k) if isinstance(mem.get(k), dict) else None
            if cur is not None and int(cur.get("at") or 0) > ts:
                continue
            if s <= 0:
                mem.pop(k, None)
            elif cur is None or int(cur.get("st") or 0) < s or int(cur.get("at") or 0) < ts:
                m = dict(cur or {}, st=s, at=ts)
                if lw.get("d1") is not None:
                    m["d1"] = lw["d1"]
                if lw.get("n"):
                    m["name" if lw["g"] == "fut" else "label"] = lw["n"]
                mem[k] = m

    def save(self, now, force=False):
        if not (force or self.dirty or now - self.last_save >= 30):
            return
        st = dict(self.st, ts=int(now), status=self.status(now))
        try:
            common.atomic_write_json(os.path.join(common.STATE_DIR, STATE_NAME), st)
            self.dirty, self.last_save = False, now
        except Exception as e:
            log.warning("청산 감시 기억 저장 실패(다음 판): %s", common.safe_err(e)[:120])

    def status(self, now) -> dict:
        ven = {}
        for k, s in self.v.items():
            ven[k] = {"ok": s.get("ok"), "err": s.get("err"), "kind": s.get("ekind"), "n": len(s.get("pos") or {}),
                      "read": int(s.get("pos_ts") or 0) or None, "every": s.get("every")}
        rk = {}
        for src, s in self.risk.items():
            rk[src] = {"ok": s.get("ok"), "err": s.get("err"), "n": len(s.get("recs") or {}), "read": int(s.get("ts") or 0) or None}
        return {"on": self.gate[0], "why": self.gate[1], "venues": ven, "risk": rk, "calls": self.calls}

    def env(self):
        e = self.env_fn() or {}
        sig = hashlib.sha256(json.dumps({k: e.get(k) for k in sorted(e) if k.startswith("TJ_")}, sort_keys=True).encode()).hexdigest()
        if sig != self.env_sig:
            if self.env_sig is not None:
                for j in self.jobs.values():
                    j.update(until=0, fails=0)
                for s in list(self.v.values()) + list(self.risk.values()):
                    if s.get("ekind") == "perm":
                        s["ekind"] = None
            self.env_sig = sig
            ks0 = self.__dict__.get("_ksig")
            ks1 = {ex: _key_sig(e, ex) for ex in LEV_KEYS}
            for ex in LEV_KEYS:
                if ks0 is not None and ks1[ex] != ks0.get(ex):
                    self.kgen[ex] = int(self.kgen.get(ex, 0)) + 1
                if ks0 is not None and ks0.get(ex) is not None and ks1[ex] != ks0.get(ex):
                    if ex in FAST_EX:
                        self._forget_ex(ex)
                    self._forget_lev(ex)
            self.__dict__["_ksig"] = ks1
        self.__dict__["_env_last"] = e
        return e

    def _forget_ex(self, ex):
        for k in [k for k in self.st["fut"] if _vk_of(k) == ex]:
            del self.st["fut"][k]
        for k in [k for k in self.st["risk"] if _risk_src(k) != "lev" and _risk_ex(_risk_src(k)) == ex]:
            del self.st["risk"][k]
        self.v.pop(ex, None)
        for src in [s9 for s9 in self.risk if _risk_ex(s9) == ex]:
            self.risk.pop(src, None)
        if ex == "binance":
            self.thr.clear()
        self.dirty = True
        log.info("청산 감시 %s 키가 바뀜 — 그 곳 기억·마지막 값을 조용히 잊음(새 키로 처음부터)", ex)

    def _forget_lev(self, ex):
        for k in [k for k, e in self.st["fut"].items() if k.endswith(":lev") and isinstance(e, dict) and (e.get("levsrc") or [None])[0] == ex]:
            del self.st["fut"][k]
        for k in [k for k in self.st["risk"] if _risk_src(k) == "lev" and k.split(":", 1)[0] == ex]:
            del self.st["risk"][k]
        self.kchg[ex] = float(self.clock())
        self.dirty = True

    def _lev_gone_ok(self, e, pair, prod_ok, prod_at, now, age_cap):
        if pair not in prod_ok or not isinstance(e, dict):
            return False
        pa = float(prod_at.get(pair, 0) or 0)
        at = float(_f(e.get("at")) or 0)
        return (-60 <= now - pa <= age_cap and pa > at and at >= int(self.t0) and pa > float(self.kchg.get(pair[0], 0) or 0))

    def compute_gate(self, now):
        cfg = self.cfg_c.get()
        if not AP.liq_switch_on(cfg):
            return False, "꺼짐(config alerts.liq_fast)"
        try:
            doc = AP.load(self.prefs_c.get())
        except Exception:
            doc = AP.default_doc()
        if not AP.effective(doc, "liq", now):
            return False, "꺼짐(알림 설정 '청산 근접')"
        e = self.env()
        tok = os.environ.get("TJ_TG_TOKEN") or e.get("TJ_TG_TOKEN")
        chat = os.environ.get("TJ_TG_CHAT") or e.get("TJ_TG_CHAT")
        if not (tok and chat):
            return False, "텔레그램 미연결"
        return True, ""

    def th(self):
        try:
            return float(AP.load(self.prefs_c.get())["th"]["liq_pct"])
        except Exception:
            return float(AP.REC_TH["liq_pct"])

    def call(self, ex, kind, bucket, method, url, headers=None, body=None, w=1, timeout=6.0):
        now = self.clock()
        u9 = urllib.parse.urlsplit(url)
        host, path9 = u9.hostname or "", u9.path
        if not self.gate[0]:
            raise Wait("청산 빠른 감시 꺼짐")
        if now < float(self.rl.get(host, 0) or 0):
            raise Wait(f"{host} 레이트 제한 대기")
        if now < float(self.lim.hold.get(f"path:{host}{path9}", 0) or 0):
            raise Wait(f"{host}{path9} 한도 코드 대기")
        if not self.lim.take(bucket, kind, w, now):
            raise Wait(f"{bucket} 예산 대기")
        self.calls += 1
        try:
            status, hd, data = HTTP(method, url, headers, body, timeout)
        except HttpErr as e:
            if e.status in (429, 418) or (ex == "bybit" and e.status == 403 and "too frequent" in e.body.lower()):
                try:
                    ra = float(str(e.headers.get("retry-after") or "").strip())
                except ValueError:
                    ra = 0.0
                ra = ra if ra > 0 else (600.0 if e.status == 403 else 120.0 if e.status == 418 else 60.0)
                self.rl[host] = max(float(self.rl.get(host, 0) or 0), self.clock() + min(ra, 3 * 86400))
                log.warning("%s HTTP %s(레이트 한도) — %d초 이 호스트 쉼(tj-exf 이력 수집도 같이)", host, e.status, int(ra))
            self._hdr(host, url, e.headers)
            raise
        self._hdr(host, url, hd)
        code9 = data.get("retCode" if ex == "bybit" else "code") if (isinstance(data, dict) and ex in ("bybit", "okx")) else None
        if code9 is not None and _int(code9) in RL_CODES.get(ex, ()):
            self.lim.hold_until(f"path:{host}{path9}", self.clock() + 30)
            log.warning("%s%s 한도 코드 %s — 30초 이 경로 쉼", host, path9, code9)
            raise ApiErr(ex, code9, "레이트 한도")
        return data

    def _hdr(self, host, url, hd):
        if not hd or not host.endswith("binance.com"):
            return
        path = urllib.parse.urlsplit(url).path
        name, cap = (BN_SAPI_HDR if path.startswith("/sapi/") else BN_HDR.get(host, (None, 0)))
        if not name:
            return
        try:
            used = int(str(hd.get(name) or "").strip() or -1)
        except ValueError:
            return
        if used >= cap * HDR_HOLD_AT:
            now = self.clock()
            until = (int(now // 60) + 1) * 60 + 1.0
            for b in ([f"bn_sapi:{path}"] if path.startswith("/sapi/") else ["bn_fapi"] if host.startswith("fapi") else ["bn_api"]):
                self.lim.hold_until(b, until)
            log.warning("바이낸스 IP 사용량 %d/%d(80%% 이상 — 다른 수집 포함) — 이 분 끝까지 청산 감시 조회 쉼", used, cap)

    def bn_get(self, env, host, path, params=None, kind="bn_fapi", bucket=None, w=5):
        q = dict(params or {})
        q["timestamp"] = int(time.time() * 1000)
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = hmac.new(env["TJ_BINANCE_SECRET"].encode(), qs.encode(), hashlib.sha256).hexdigest()
        return self.call("binance", kind, bucket or kind, "GET", f"https://{host}{path}?{qs}&signature={sig}",
                         {"X-MBX-APIKEY": env["TJ_BINANCE_KEY"]}, w=w)

    def bybit_get(self, env, path, params):
        qs = urllib.parse.urlencode(params)
        ts = str(int(time.time() * 1000))
        key, sec = env["TJ_BYBIT_KEY"], env["TJ_BYBIT_SECRET"]
        sig = hmac.new(sec.encode(), (ts + key + "10000" + qs).encode(), hashlib.sha256).hexdigest()
        d = self.call("bybit", "bybit_ip", "bybit_ip", "GET", f"https://api.bybit.com{path}?{qs}",
                      {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": "10000", "X-BAPI-SIGN": sig})
        if not isinstance(d, dict) or d.get("retCode") != 0:
            raise ApiErr("bybit", (d or {}).get("retCode") if isinstance(d, dict) else None, (d or {}).get("retMsg") if isinstance(d, dict) else "")
        return d.get("result") or {}

    def okx_get(self, env, path, params, kind, bucket=None):
        qs = urllib.parse.urlencode(params or {})
        full = path + ("?" + qs if qs else "")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
        sig = base64.b64encode(hmac.new(env["TJ_OKX_SECRET"].encode(), (ts + "GET" + full).encode(), hashlib.sha256).digest()).decode()
        d = self.call("okx", kind, bucket or kind, "GET", "https://www.okx.com" + full,
                      {"OK-ACCESS-KEY": env["TJ_OKX_KEY"], "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": ts,
                       "OK-ACCESS-PASSPHRASE": env["TJ_OKX_PASSPHRASE"]})
        return self._okx_data(d)

    def _okx_data(self, d):
        if not isinstance(d, dict) or str(d.get("code")) != "0":
            raise ApiErr("okx", (d or {}).get("code") if isinstance(d, dict) else None, (d or {}).get("msg") if isinstance(d, dict) else "")
        data = d.get("data")
        if not isinstance(data, list):
            raise ValueError("okx data 형식 오류")
        return data

    def fetch_positions(self, ex, env):
        out = []
        if ex == "binance":
            rows = self.bn_get(env, "fapi.binance.com", "/fapi/v3/positionRisk", kind="bn_fapi", w=5)
            if not isinstance(rows, list) or any(not isinstance(p, dict) for p in rows):
                raise ValueError("binance positionRisk 형식 오류")
            for p in rows:
                _str_req(p, "symbol", "binance positionRisk")
                amt = _num_req(p, "positionAmt", True, "binance positionRisk")
                if amt == 0:
                    continue
                side = str(p.get("positionSide") or "BOTH").upper()
                if side not in ("LONG", "SHORT", "BOTH"):
                    raise ValueError("binance positionSide 형식 오류")
                side = side if side != "BOTH" else ("LONG" if amt > 0 else "SHORT")
                out.append({"sym": str(p.get("symbol") or ""), "side": side, "qty": abs(amt), "mark": _f(p.get("markPrice")),
                            "liq": _f(p.get("liquidationPrice")), "lev": None, "acct": ""})
        elif ex == "bybit":
            cur = None
            for _i in range(10):
                prm = {"category": "linear", "settleCoin": "USDT", "limit": 200}
                if cur:
                    prm["cursor"] = cur
                res = self.bybit_get(env, "/v5/position/list", prm)
                rows = _list_req(res, "list", "bybit position/list")
                for p in rows:
                    _str_req(p, "symbol", "bybit position/list")
                    sz = _num_req(p, "size", False, "bybit position/list")
                    if sz == 0:
                        continue
                    if p.get("side") not in ("Buy", "Sell"):
                        raise ValueError("bybit position side 형식 오류")
                    out.append({"sym": str(p.get("symbol") or ""), "side": "LONG" if p.get("side") == "Buy" else "SHORT", "qty": sz,
                                "mark": _f(p.get("markPrice")), "liq": _f(p.get("liqPrice")), "lev": p.get("leverage"), "acct": ""})
                cur = res.get("nextPageCursor") or None
                if not cur or not rows:
                    break
            else:
                raise ValueError("bybit 포지션 페이지 상한")
        elif ex == "okx":
            rows = self.okx_get(env, "/api/v5/account/positions", {}, "okx_pos")
            if any(not isinstance(p, dict) for p in rows):
                raise ValueError("okx positions 행 형식 오류")
            for p in rows:
                _str_req(p, "instId", "okx positions")
                pos = _num_req(p, "pos", True, "okx positions")
                if pos == 0:
                    continue
                ps9, inst9 = p.get("posSide"), str(p.get("instType") or "")
                if ps9 in ("long", "short"):
                    side = ps9.upper()
                elif ps9 == "net" and inst9 == "MARGIN":
                    base9, _, quote9 = str(p.get("instId") or "").partition("-")
                    pc9 = str(p.get("posCcy") or "")
                    if pc9 and pc9 == base9:
                        side = "LONG"
                    elif pc9 and pc9 == quote9.split("-")[0]:
                        side = "SHORT"
                    else:
                        raise ValueError("okx MARGIN posCcy 방향 모름")
                elif ps9 == "net":
                    side = "LONG" if pos > 0 else "SHORT"
                else:
                    raise ValueError("okx posSide 형식 오류")
                out.append({"sym": str(p.get("instId") or ""), "side": side, "qty": abs(pos), "mark": _f(p.get("markPx")),
                            "liq": _f(p.get("liqPx")), "lev": p.get("lever"), "acct": "", "inst": str(p.get("instType") or "SWAP")})
        return out

    def fetch_marks(self, ex, syms):
        out = {}
        if ex == "binance":
            if len(syms) > 10:
                rows = self.call("binance", "bn_fapi", "bn_fapi", "GET", "https://fapi.binance.com/fapi/v1/premiumIndex", w=10, timeout=4)
                want = {s for s, _t in syms}
                for r in rows if isinstance(rows, list) else ():
                    if r.get("symbol") in want and _f(r.get("markPrice")):
                        out[r["symbol"]] = float(r["markPrice"])
            else:
                for s, _t in syms:
                    r = self.call("binance", "bn_fapi", "bn_fapi", "GET", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol="
                                  + urllib.parse.quote(s), w=1, timeout=4)
                    if isinstance(r, dict) and _f(r.get("markPrice")):
                        out[s] = float(r["markPrice"])
        elif ex == "bybit":
            for s, _t in syms:
                d = self.call("bybit", "bybit_ip", "bybit_ip", "GET",
                              "https://api.bybit.com/v5/market/tickers?category=linear&symbol=" + urllib.parse.quote(s), timeout=4)
                lst = ((d or {}).get("result") or {}).get("list") if isinstance(d, dict) and d.get("retCode") == 0 else None
                for r in lst or ():
                    if r.get("symbol") == s and _f(r.get("markPrice")):
                        out[s] = float(r["markPrice"])
        elif ex == "okx":
            for s, t in syms:
                d = self.call("okx", "okx_mark", f"okx_mark:{s}", "GET", "https://www.okx.com/api/v5/public/mark-price?"
                              + urllib.parse.urlencode({"instType": t or "SWAP", "instId": s}), timeout=4)
                for r in self._okx_data(d):
                    if r.get("instId") == s and _f(r.get("markPx")):
                        out[s] = float(r["markPx"])
        return out

    def fetch_hl(self, addr):
        d = self.call("hyperliquid", "hl", "hl", "POST", "https://api.hyperliquid.xyz/info", body={"type": "clearinghouseState", "user": addr},
                      w=2, timeout=5)
        if not isinstance(d, dict) or not isinstance(d.get("assetPositions"), list):
            raise ValueError("hyperliquid clearinghouseState 형식 오류")
        out = []
        for ap in d["assetPositions"]:
            p = ap.get("position") if isinstance(ap, dict) else None
            if not isinstance(p, dict):
                raise ValueError("hyperliquid assetPositions 행 형식 오류")
            _str_req(p, "coin", "hyperliquid")
            szi = _num_req(p, "szi", True, "hyperliquid")
            if szi == 0:
                continue
            pv = _f(p.get("positionValue"))
            out.append({"sym": str(p.get("coin") or "")[:40], "side": "LONG" if szi > 0 else "SHORT", "qty": abs(szi),
                        "mark": abs(pv / szi) if pv else None, "liq": _f(p.get("liquidationPx")),
                        "lev": (p.get("leverage") or {}).get("value") if isinstance(p.get("leverage"), dict) else None, "acct": addr})
        return out

    def fetch_risk(self, src, env, cfg):
        now = self.clock()
        items = []
        ksig9 = _key_sig(env, "binance") if src in ("bn_loan", "bn_margin") else None
        if src == "okx_loan":
            rows = self.okx_get(env, "/api/v5/finance/flexible-loan/loan-info", {}, "okx_loan")
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    raise ValueError("okx loan-info 행 형식 오류")
                coll = [{"ccy": _str_req(c, "ccy", "okx 대출 담보").upper(), "qty": _num_req(c, "amt", False, "okx 대출 담보")}
                        for c in _list_req(r, "collateralData", "okx loan-info")]
                debt = [{"ccy": _str_req(c, "ccy", "okx 대출 차입").upper(), "principal": None, "interest": None, "total": _num_req(c, "amt", False, "okx 대출 차입")}
                        for c in _list_req(r, "loanData", "okx loan-info")]
                if not any(d["total"] > 0 for d in debt):
                    continue
                rw = r.get("riskWarningData") if isinstance(r.get("riskWarningData"), dict) else {}
                m = {"ltv": lev_metric(_f(r.get("curLTV")), "frac", "up", call=_f(r.get("marginCallLTV")), liq=_f(r.get("liqLTV")),
                                       thr_src="api:GET /api/v5/finance/flexible-loan/loan-info", src="curLTV@GET /api/v5/finance/flexible-loan/loan-info")}
                items.append(lev_item("okx", "loan", "loan", str(r.get("ordId") or i), "OKX 담보대출", now, m, debt, coll,
                                      raw={"liqPx": _f(rw.get("liqPx")), "liqPair": rw.get("instId")}))
                items[-1]["_haircut"] = True
        elif src == "bn_loan":
            page, rows = 1, []
            while True:
                d = self.bn_get(env, "api.binance.com", "/sapi/v2/loan/flexible/ongoing/orders", {"current": page, "limit": 100},
                                kind="bn_sapi", bucket="bn_sapi:/sapi/v2/loan/flexible/ongoing/orders", w=300)
                part = _list_req(d, "rows", "binance flexible loan")
                rows += part
                if len(part) < 100:
                    break
                if page >= 5:
                    raise ValueError("binance flexible loan 페이지 상한")
                page += 1
            for r in rows:
                cc, lc = _str_req(r, "collateralCoin", "binance 대출").upper(), _str_req(r, "loanCoin", "binance 대출").upper()
                td9 = _num_req(r, "totalDebt", False, "binance 대출")
                ca9 = _num_req(r, "collateralAmount", False, "binance 대출")
                if not td9 > 0:
                    continue
                th = self.thr.get(cc)
                if not th or len(th) < 4 or th[3] != ksig9 or now - th[2] > (THR_SEC if th[0] else THR_RETRY):
                    d2 = self.bn_get(env, "api.binance.com", "/sapi/v2/loan/flexible/collateral/data", {"collateralCoin": cc},
                                     kind="bn_sapi", bucket="bn_sapi:/sapi/v2/loan/flexible/collateral/data", w=400)
                    row = next((x for x in ((d2 or {}).get("rows") or []) if str(x.get("collateralCoin") or "").upper() == cc), None)
                    th = (_f((row or {}).get("marginCallLTV")), _f((row or {}).get("liquidationLTV")), now, ksig9)
                    self.thr[cc] = th
                m = {"ltv": lev_metric(_f(r.get("currentLTV")), "frac", "up", call=th[0], liq=th[1],
                                       thr_src="api:GET /sapi/v2/loan/flexible/collateral/data" if th[0] else "unknown",
                                       src="currentLTV@GET /sapi/v2/loan/flexible/ongoing/orders")}
                items.append(lev_item("binance", "loan", "loan", f"{lc}-{cc}", f"바이낸스 담보대출 {lc}←{cc}", now, m,
                                      [{"ccy": lc, "principal": None, "interest": None, "total": td9}], [{"ccy": cc, "qty": ca9}]))
        elif src == "bn_margin":
            d = self.bn_get(env, "api.binance.com", "/sapi/v1/margin/account", kind="bn_sapi", bucket="bn_sapi:/sapi/v1/margin/account", w=10)
            debt, coll = [], []
            for a in _list_req(d, "userAssets", "binance margin account"):
                s9 = _str_req(a, "asset", "binance margin").upper()
                pb, it9 = _num_req(a, "borrowed", False, "binance margin"), _num_req(a, "interest", False, "binance margin")
                h = _num_req(a, "free", False, "binance margin") + _num_req(a, "locked", False, "binance margin")
                if pb + it9 > 0:
                    debt.append({"ccy": s9, "principal": pb, "interest": it9, "total": pb + it9})
                if h > 0:
                    coll.append({"ccy": s9, "qty": h})
            ml = _f(d.get("marginLevel"))
            ml = ml if (ml is not None and ml > 0) else None
            if debt:
                co = self.thr.get("_coeff")
                if not co or len(co) < 5 or co[4] != ksig9 or now - co[2] > COEFF_SEC:
                    c2 = self.bn_get(env, "api.binance.com", "/sapi/v1/margin/tradeCoeff", kind="bn_sapi", bucket="bn_sapi:/sapi/v1/margin/tradeCoeff",
                                     w=10)
                    co = (_f((c2 or {}).get("marginCallBar")), _f((c2 or {}).get("forceLiquidationBar")), now, _f((c2 or {}).get("normalBar")), ksig9)
                    self.thr["_coeff"] = co
                m = {"margin_level": lev_metric(ml, "x", "down", call=co[0], liq=co[1], warn=co[3] if len(co) > 3 else None,
                                                thr_src="api:GET /sapi/v1/margin/tradeCoeff" if co[0] else "unknown",
                                                src="marginLevel@GET /sapi/v1/margin/account")}
                items.append(lev_item("binance", "margin_cross", "account", "-", "바이낸스 교차마진", now, m, debt, coll,
                                      raw={"accountType": d.get("accountType")}))
            d3 = self.bn_get(env, "api.binance.com", "/sapi/v1/margin/isolated/account", kind="bn_sapi",
                             bucket="bn_sapi:/sapi/v1/margin/isolated/account", w=10)
            for a in _list_req(d3, "assets", "binance isolated account"):
                debt9 = []
                for side in ("baseAsset", "quoteAsset"):
                    x = a.get(side)
                    if not isinstance(x, dict):
                        raise ValueError(f"binance isolated {side} 형식 오류")
                    t9 = _num_req(x, "borrowed", False, "binance isolated") + _num_req(x, "interest", False, "binance isolated")
                    if t9 > 0:
                        debt9.append({"ccy": str(x.get("asset") or "").upper(), "principal": _f(x.get("borrowed")), "interest": _f(x.get("interest")), "total": t9})
                if not debt9:
                    continue
                sym = _str_req(a, "symbol", "binance isolated")
                stt = str(a.get("marginLevelStatus") or "")
                m = {"margin_level": lev_metric(_f(a.get("marginLevel")), "x", "down", thr_src="unknown", src="marginLevel@GET /sapi/v1/margin/isolated/account")}
                items.append(lev_item("binance", "margin_isolated", "pair", sym, f"바이낸스 격리마진 {sym}", now, m, debt9, None,
                                      raw={"liquidatePrice": _f(a.get("liquidatePrice")), "indexPrice": _f(a.get("indexPrice"))},
                                      state={"v": stt, "level": LEV_STATE_LEVEL.get(stt), "src": "marginLevelStatus@GET /sapi/v1/margin/isolated/account"}
                                      if stt else None))
                items[-1]["_pside"] = iso_side([x["ccy"] for x in debt9], (a.get("baseAsset") or {}).get("asset"), (a.get("quoteAsset") or {}).get("asset"))
        elif src == "bybit_loan":
            c9, l9, s9t = bybit_loan_thr(cfg)
            res = self.bybit_get(env, "/v5/crypto-loan-common/position", {})
            coll, debt, cval = {}, {}, {}
            for r in _list_req(res, "supplyList", "bybit 대출"):
                _str_req(r, "currency", "bybit 대출")
                _num_req(r, "amount", False, "bybit 대출")
            for r in _list_req(res, "collateralList", "bybit 대출"):
                s9 = _str_req(r, "currency", "bybit 대출").upper()
                q9 = _num_req(r, "amount", False, "bybit 대출")
                coll[s9] = coll.get(s9, 0.0) + q9
                v9 = None if isinstance(r.get("amountUSD"), bool) else _f(r.get("amountUSD"))
                if v9 is None or v9 < 0:
                    cval[s9] = None
                elif s9 not in cval:
                    cval[s9] = v9
                elif cval[s9] is not None:
                    cval[s9] += v9
            for r in _list_req(res, "borrowList", "bybit 대출"):
                s9 = _str_req(r, "loanCurrency", "bybit 대출").upper()
                debt[s9] = debt.get(s9, 0.0) + _num_req(r, "fixedTotalDebt", False, "bybit 대출") + _num_req(r, "flexibleTotalDebt", False, "bybit 대출")
            if any(v > 0 for v in debt.values()):
                m = {"ltv": lev_metric(_f(res.get("ltv")), "frac", "up", call=c9, liq=l9, thr_src=s9t,
                                       src="ltv@GET /v5/crypto-loan-common/position")}
                items.append(lev_item("bybit", "loan", "loan", "-", "바이빗 담보대출", now, m,
                                      [{"ccy": k, "principal": None, "interest": None, "total": v} for k, v in debt.items() if v > 0],
                                      [{"ccy": k, "qty": v, "_value0": cval.get(k)} for k, v in coll.items() if v > 0]))
                items[-1]["_haircut"] = True
        ex9 = _risk_ex(src)
        syms = sorted({c.get("ccy") for it in items for c in (it.get("collateral") or []) + (it.get("debt") or []) if c.get("ccy") not in STABLES})
        got = {}
        if syms:
            try:
                got = self.fetch_spot(ex9, syms)
            except Exception as e:
                log.info("청산 감시 %s 담보 시세 실패(거래소 값만 씀): %s", src, common.safe_err(e)[:120])
        for it in items:
            it["_px0"] = {c["ccy"]: got[c["ccy"]][0] for c in (it.get("collateral") or []) + (it.get("debt") or [])
                          if c.get("ccy") in got and got[c["ccy"]][1] - now <= PX0_LAG}
        return {it["id"]: it for it in items}, dict(got)

    def fetch_spot(self, ex, syms) -> dict:
        out = {}
        if ex == "binance":
            want = [s + "USDT" for s in syms]
            rows = None
            t9 = self.clock()
            if t9 >= float(self.__dict__.get("_bn_all_until") or 0):
                try:
                    rows = self.call("binance", "bn_api", "bn_api", "GET", "https://api.binance.com/api/v3/ticker/price?symbols="
                                     + urllib.parse.quote(json.dumps(want, separators=(",", ":"))), w=4, timeout=4)
                except HttpErr as e:
                    if e.status != 400:
                        raise
                    self.__dict__["_bn_all_until"] = self.clock() + 600
            if rows is None:
                t9 = self.clock()
                rows = self.call("binance", "bn_api", "bn_api", "GET", "https://api.binance.com/api/v3/ticker/price", w=4, timeout=6)
            idx = {r.get("symbol"): r.get("price") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            for s in syms:
                if _f(idx.get(s + "USDT")):
                    out[s] = (float(idx[s + "USDT"]), t9)
        elif ex == "okx":
            for s in syms:
                t9 = self.clock()
                d = self.call("okx", "okx_tick", "okx_tick", "GET", "https://www.okx.com/api/v5/market/ticker?instId=" + urllib.parse.quote(s + "-USDT"), timeout=4)
                try:
                    for r in self._okx_data(d):
                        if _f(r.get("last")):
                            out[s] = (float(r["last"]), t9)
                except ApiErr:
                    continue
        elif ex == "bybit":
            for s in syms:
                t9 = self.clock()
                d = self.call("bybit", "bybit_ip", "bybit_ip", "GET", "https://api.bybit.com/v5/market/tickers?category=spot&symbol=" + urllib.parse.quote(s + "USDT"), timeout=4)
                for r in (((d or {}).get("result") or {}).get("list") or []) if isinstance(d, dict) and d.get("retCode") == 0 else ():
                    if _f(r.get("lastPrice")):
                        out[s] = (float(r["lastPrice"]), t9)
        return out

    def _put_px(self, pk, v, t0):
        p, t = v if isinstance(v, tuple) else (v, t0)
        if (self.px.get(pk) or (0, 0))[1] <= t:
            self.px[pk] = (p, t)

    def _job(self, name):
        return self.jobs.setdefault(name, {"due": 0.0, "fut": None, "fails": 0, "until": 0.0})

    def _tok(self, name):
        kind, _, rest = str(name).partition(":")
        if kind == "hl":
            return (self.gen, "a", int(self.agen.get(rest, 0)))
        ex = _risk_ex(rest) if kind == "risk" else rest
        return (self.gen, "k", int(self.kgen.get(ex, 0)))

    def _submit(self, name, fn, now):
        j = self._job(name)
        if j["fut"] is not None or now < j["due"] or now < j["until"]:
            return False
        j["tok"] = self._tok(name)
        if self.sync:
            j["fut"] = _Done(fn)
        else:
            j["fut"] = self.pool.submit(fn)
        j["started"] = now
        return True

    def _err(self, name, e, now, ex):
        j = self._job(name)
        code = getattr(e, "code", None)
        if isinstance(e, HttpErr):
            try:
                code = json.loads(e.body).get("code") if e.body.strip().startswith("{") else None
            except (ValueError, AttributeError):
                code = None
        kind = "other"
        if isinstance(e, HttpErr) and e.status in (401, 403) and not (ex == "bybit" and "too frequent" in e.body.lower()):
            kind = "perm"
        elif code is not None and _int(code) in PERM_CODES.get(ex, ()):
            kind = "perm"
        elif (isinstance(e, HttpErr) and e.status in (429, 418)) or (code is not None and _int(code) in RL_CODES.get(ex, ())):
            kind = "rl"
        elif isinstance(e, (OSError, TimeoutError)):
            kind = "net"
        j["fails"] = int(j.get("fails") or 0) + 1
        if kind == "perm":
            j["until"] = now + PERM_COOL
        elif kind == "rl":
            j["until"] = now + 30
        elif name.startswith(("mark:", "rpx:", "hl:")):
            j["until"] = now + min(10.0, 2.0 * 2 ** min(3, j["fails"] - 1))
        else:
            j["until"] = now + min(60.0, 5.0 * 2 ** min(4, j["fails"] - 1))
        msg = common.safe_err(e)[:160]
        if j["fails"] in (1, 5) or kind == "perm":
            log.warning("청산 감시 %s 조회 실패(%s — 마지막 값 유지, 없음으로 보지 않음): %s", name, kind, msg)
        return kind, msg

    def _due(self, name, sec, now):
        j = self._job(name)
        j["due"] = now + sec

    def step(self, now=None):
        now = self.clock() if now is None else now
        on, why = self.compute_gate(now)
        if (on, why) != self.gate:
            self.gen += 1
            log.info("청산 빠른 감시 %s%s", "켜짐" if on else "멈춤 — ", why)
            if on and not self.gate[0] and self.gate[1] != "시작 전":
                self.v.clear()
                self.risk.clear()
                self.px.clear()
                for j in self.jobs.values():
                    j["due"] = 0.0
            self.gate = (on, why)
            self.dirty = True
        self._collect(now)
        if not on:
            if self.st["fut"] or self.st["risk"]:
                self.st["fut"].clear()
                self.st["risk"].clear()
                self.dirty = True
                log.info("청산 빠른 감시 꺼짐 — 알림 기억을 비움(다시 켜면 지금 위험을 처음처럼 알림)")
            self.save(now)
            return []
        cfg = self.cfg_c.get()
        env = self.env()
        hl = self._hl_conf(cfg)
        out = self._judge(now, cfg)
        self._schedule(now, env, cfg, hl)
        if self.sync:
            self._collect(now)
        self.save(now, force=bool(out))
        return out

    def _collect(self, now):
        for name, j in self.jobs.items():
            f = j.get("fut")
            if f is None or not f.done():
                continue
            j["fut"] = None
            if j.get("tok") != self._tok(name):
                j["due"] = min(j["due"], now)
                continue
            kx = name.split(":", 1)
            ex9 = kx[1] if kx[0] == "acct" else _risk_ex(kx[1]) if kx[0] == "risk" else None
            if ex9 in FAST_EX and j.get("ksig") != (self.__dict__.get("_ksig") or {}).get(ex9):
                j["due"] = min(j["due"], now)
                continue
            try:
                res = f.result()
            except Wait:
                j["due"] = now + 1.0
                continue
            except Exception as e:
                self._apply_err(name, e, now)
                continue
            j["fails"] = 0
            self._apply(name, res, now)

    def _apply_err(self, name, e, now):
        kind, ex = name.split(":", 1)[0], name.split(":", 1)[1] if ":" in name else name
        if kind in ("acct", "mark", "hl"):
            vk = ex if kind != "hl" else f"hl:{ex}"
            s = self.v.setdefault(vk, {"pos": {}})
            ek, msg = self._err(name, e, now, "hyperliquid" if kind == "hl" else ex)
            if kind != "mark":
                s.update(ok=False, err=msg, ekind=ek)
            else:
                s["mark_err"] = msg
        elif kind == "risk":
            s = self.risk.setdefault(ex, {"recs": {}})
            ek, msg = self._err(name, e, now, {"okx_loan": "okx", "bn_loan": "binance", "bn_margin": "binance", "bybit_loan": "bybit"}.get(ex, ex))
            s.update(ok=False, err=msg, ekind=ek)
        else:
            self._err(name, e, now, ex)

    def _apply(self, name, res, now):
        kind, ex = name.split(":", 1)
        if kind in ("acct", "hl"):
            vk = ex if kind == "acct" else f"hl:{ex}"
            s = self.v.setdefault(vk, {"pos": {}})
            t = self.jobs[name].get("started") or now
            pos = {}
            exn = "hyperliquid" if kind == "hl" else ex
            for p in res:
                k = f"{exn}:{p['sym']}:{p['side']}:{p.get('acct') or ''}"
                pos[k] = dict(p, key=k, ex=exn, ts=t, mark_ts=t if p.get("mark") else 0, mark_at_pos=p.get("mark"))
            if set(pos) != set(s.get("pos") or {}) or not s.get("ok"):
                self.dirty = True
            s.update(pos=pos, pos_ts=t, ok=True, err=None, ekind=None)
            if not pos:
                j9 = self.jobs[name]
                j9["due"] = min(j9["due"], t + DISC_SEC)
            mk9 = s.setdefault("marks", {})
            for k, p in pos.items():
                if p.get("mark") and (mk9.get(p["sym"]) or (0, 0))[1] <= t:
                    mk9[p["sym"]] = (p["mark"], t)
        elif kind == "mark":
            s = self.v.setdefault(ex, {"pos": {}})
            t = self.jobs[name].get("started") or now
            mk9 = s.setdefault("marks", {})
            for sym, px in res.items():
                if (mk9.get(sym) or (0, 0))[1] <= t:
                    mk9[sym] = (px, t)
            s.pop("mark_err", None)
        elif kind == "risk":
            recs, pxs = res
            s = self.risk.setdefault(ex, {"recs": {}})
            if set(recs) != set(s.get("recs") or {}) or not s.get("ok"):
                self.dirty = True
            s.update(recs=recs, ts=self.jobs[name].get("started") or now, ok=True, err=None, ekind=None)
            for sym, v in pxs.items():
                self._put_px(f"{_risk_ex(ex)}:{sym}", v, self.jobs[name].get("started") or now)
        elif kind == "rpx":
            for sym, v in res.items():
                self._put_px(f"{ex}:{sym}", v, self.jobs[name].get("started") or now)

    def _rows_futures(self, now, th):
        rows, gone = [], []
        for vk, s in self.v.items():
            ok_fresh = bool(s.get("ok")) and now - float(s.get("pos_ts") or 0) <= POS_RESOLVE_AGE
            for k, p in (s.get("pos") or {}).items():
                m = (s.get("marks") or {}).get(p["sym"])
                mark, mts = (m[0], m[1]) if m else (p.get("mark"), p.get("mark_ts") or 0)
                if p.get("mark_ts") and m and p["mark_ts"] > m[1]:
                    mark, mts = p["mark"], p["mark_ts"]
                d = fut_dist(p.get("liq"), mark, p.get("side"))
                lage = now - float(p.get("ts") or 0)
                rows.append({"key": k, "vk": vk, "name": f"{p['sym']} {_side_ko(p['side'])}".strip()
                             + (f" ({p['acct'][:6]}…{p['acct'][-4:]})" if p.get("acct") else ""),
                             "ex": p["ex"], "dist": d, "mark": mark, "liq": p.get("liq"), "lev": p.get("lev"), "side": p.get("side"),
                             "alert_ok": now - mts <= MARK_FRESH and lage <= POS_ALERT_AGE,
                             "resolve_ok": now - mts <= MARK_FRESH and lage <= POS_RESOLVE_AGE and bool(s.get("ok")) and side_ok(p.get("side")),
                             "stale_liq": lage if lage > 120 else 0})
            if ok_fresh:
                gone += [k for k in self.st["fut"] if _vk_of(k) == vk and k not in (s.get("pos") or {})]
        srows, sgone = self._rows_slow(now)
        lrows, lgone = self._rows_lev_pos(now)
        return rows + srows + lrows, gone + sgone + lgone

    def _rows_slow(self, now):
        out, gone = [], []
        conf = self._slow_conf()
        for dex, accts in (conf or {}).items():
            want = {a["address"] for a in accts}
            for k in [k for k in self.st["fut"] if _vk_of(k) == dex and k.rsplit(":", 1)[-1] not in want]:
                del self.st["fut"][k]
                self.dirty = True
            d = self._slow_file(dex)
            meta = d.get("accts")
            if not isinstance(d.get("positions"), list) or not isinstance(meta, dict) or not _slow_rows_ok(d["positions"], want):
                continue
            seen = set()
            for p in d.get("positions") or []:
                if not isinstance(p, dict) or p.get("acct") not in want:
                    continue
                age = now - float(_f((meta.get(p["acct"]) or {}).get("ts")) or 0)
                k = f"{dex}:{p.get('symbol')}:{p.get('side')}:{p.get('acct') or ''}"
                seen.add(k)
                out.append({"key": k, "vk": dex, "name": f"{p.get('symbol')} {_side_ko(p.get('side'))}".strip(), "ex": dex,
                            "dist": fut_dist(p.get("liq"), p.get("mark"), p.get("side")), "mark": p.get("mark"), "liq": p.get("liq"),
                            "lev": p.get("leverage"), "side": p.get("side"), "alert_ok": -60 <= age <= SLOW_AGE,
                            "resolve_ok": -60 <= age <= MARK_FRESH and side_ok(p.get("side")), "slow": True})
            for k in list(self.st["fut"]):
                if _vk_of(k) != dex:
                    continue
                if k in seen:
                    self.st["fut"][k].pop("absent", None)
                    continue
                acct = k.rsplit(":", 1)[-1]
                ts9 = float(_f((meta.get(acct) or {}).get("ts")) or 0)
                if acct in want and -60 <= now - ts9 <= POS_RESOLVE_AGE and ts9 > float(_f(self.st["fut"][k].get("at")) or 0):
                    gone.append(k)
                    continue
                if acct in want and -60 <= now - ts9 <= POS_RESOLVE_AGE and _absent(self.st["fut"], k, now):
                    del self.st["fut"][k]
                    self.dirty = True
        return out, gone

    def _rows_dex_acct(self, now):
        rows, gone = [], []
        conf = self._slow_conf()
        if conf is None:
            return rows, gone
        live = set()
        for dex, accts in conf.items():
            if dex not in DEX_ACCT_DOC:
                continue
            want = {a["address"]: a for a in accts}
            d = self._slow_file(dex)
            meta = d.get("accts")
            if not isinstance(d.get("positions"), list) or not isinstance(meta, dict) or not _slow_rows_ok(d["positions"], set(want)):
                live |= {f"{dex}:{DEX_PROD}:account:{a}" for a in want}
                continue
            npos = {}
            for p in d["positions"]:
                if isinstance(p, dict) and p.get("acct") in want:
                    npos[p["acct"]] = npos.get(p["acct"], 0) + 1
            for addr, a in want.items():
                k = f"{dex}:{DEX_PROD}:account:{addr}"
                live.add(k)
                mt = meta.get(addr) if isinstance(meta.get(addr), dict) else {}
                ts9 = float(_f(mt.get("ts")) or 0)
                age = now - ts9
                mmr = mt.get("mmr")
                mmr = None if isinstance(mmr, bool) else _f(mmr)
                if mmr is None or mmr < 0:
                    continue
                e = self.st["risk"].get(k)
                if mmr <= 0 and not npos.get(addr):
                    if isinstance(e, dict) and -60 <= age <= POS_RESOLVE_AGE and ts9 > float(_f(e.get("at")) or 0):
                        gone.append(k)
                    continue
                lbl = str(a.get("label") or "").strip() or (f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr)
                it = lev_item(dex, DEX_PROD, "account", addr, f"{EX_KO.get(dex, dex)} 교차 계정({lbl[:24]})", ts9,
                              {"mm_rate": lev_metric(round(mmr, 6), "frac", "up", call=0.8, liq=1.0, thr_src=TJ_DEFAULT,
                                                     src="accts.mmr@futures_" + dex + ".json")})
                it["metrics"]["mm_rate"]["liq_src"] = DEX_ACCT_DOC[dex]
                x = risk_row(it, now)
                if x is None:
                    continue
                x.update(age=age, alert_ok=-60 <= age <= SLOW_AGE, resolve_ok=-60 <= age <= MARK_FRESH, slow=True, gap=float(SLOW_AGE))
                rows.append(x)
        for k in [k for k in self.st["risk"] if _risk_src(k) == "dex" and k not in live]:
            del self.st["risk"][k]
            self.dirty = True
        return rows, gone

    def _slow_conf(self):
        try:
            import perp_dex
            return {d: a for d, a in perp_dex.configured(self.cfg_c.get()).items() if d != "hyperliquid"}
        except Exception as e:
            log.warning("청산 감시 퍼프 덱스 설정 읽기 실패(이번 판 느린 감시·정리 건너뜀): %s", common.safe_err(e)[:100])
            return None

    def _slow_file(self, dex):
        c = self.__dict__.setdefault("_slow_c", {})
        if dex not in c:
            c[dex] = _FileCache(lambda dex=dex: os.path.join(common.STATE_DIR, f"futures_{dex}.json"), {})
        return c[dex].get()

    def _rows_risk(self, now):
        rows, gone, fast_ids = [], [], set()
        for src, s in self.risk.items():
            ex9 = _risk_ex(src)
            fresh_read = bool(s.get("ok")) and now - float(s.get("ts") or 0) <= RISK_RESOLVE_AGE
            for k, it in (s.get("recs") or {}).items():
                age = now - float(it.get("measured_at") or 0)
                if age <= RISK_ALERT_AGE:
                    fast_ids.add(k)
                prices = {}
                for c in (it.get("collateral") or []) + (it.get("debt") or []):
                    pv = self.px.get(f"{ex9}:{c.get('ccy')}")
                    if pv:
                        prices[c.get("ccy")] = pv
                x = risk_row(it, now, prices, fast=True)
                if x is None:
                    continue
                x.update(age=age, alert_ok=age <= RISK_ALERT_AGE,
                         resolve_ok=age <= RISK_RESOLVE_AGE and (x["pfresh"] or age <= 15) and bool(s.get("ok")))
                rows.append(x)
            if fresh_read:
                gone += [k for k in self.st["risk"] if _risk_src(k) == src and k not in (s.get("recs") or {})]
        drows, dgone = self._rows_dex_acct(now)
        rows, gone = rows + drows, gone + dgone
        lev = self._lev(now)
        if not _lev_ok(lev):
            return rows, gone
        prod_ok, prod_at = self._lev_prod(lev)
        seen = set()
        for it in lev.get("items") or []:
            if not isinstance(it, dict) or it.get("scope") == "position" or not it.get("id") or it["id"] in fast_ids:
                continue
            if _risk_src(it["id"]) != "lev":
                continue
            seen.add(it["id"])
            age = now - float(_f(it.get("measured_at")) or 0)
            ok9 = (it.get("ex"), it.get("product")) in prod_ok and bool(it.get("fresh")) and self._after_kchg(it.get("ex"), it)
            x = risk_row(it, now)
            if x is None:
                continue
            x.update(age=age, alert_ok=ok9, resolve_ok=ok9 and -60 <= age <= MARK_FRESH, slow=True, gap=float(lev.get("fresh_sec") or SLOW_AGE))
            rows.append(x)
        for k in list(self.st["risk"]):
            if _risk_src(k) != "lev":
                continue
            if k in seen:
                self.st["risk"][k].pop("absent", None)
                continue
            pair = tuple(k.split(":", 2)[:2])
            if self._lev_gone_ok(self.st["risk"][k], pair, prod_ok, prod_at, now, RISK_RESOLVE_AGE):
                gone.append(k)
                continue
            if pair in prod_ok and -60 <= now - prod_at.get(pair, 0) <= RISK_RESOLVE_AGE and _absent(self.st["risk"], k, now):
                del self.st["risk"][k]
                self.dirty = True
        return rows, gone

    def _after_kchg(self, ex, it) -> bool:
        return float(_f((it or {}).get("measured_at")) or 0) > float(self.kchg.get(ex, 0) or 0)

    @staticmethod
    def _lev_prod(lev):
        prod_ok, prod_at = set(), {}
        for p in lev.get("products") or []:
            if isinstance(p, dict) and p.get("status_eff") == "ok":
                prod_ok.add((p.get("ex"), p.get("product")))
                prod_at[(p.get("ex"), p.get("product"))] = float(_f(p.get("measured_at")) or 0)
        return prod_ok, prod_at

    def _lev(self, now):
        c = self.__dict__.setdefault("_lev_c", _FileCache(lambda: os.path.join(common.STATE_DIR, "leverage.json"), {}))
        return lev_fresh(c.get(), now)

    def _rows_lev_pos(self, now):
        lev = self._lev(now)
        self._lev_migrate()
        if not _lev_ok(lev):
            return [], []
        prod_ok, prod_at = self._lev_prod(lev)
        out, gone, seen = [], [], set()
        for it in lev.get("items") or []:
            if not isinstance(it, dict) or it.get("scope") != "position" or not isinstance(it.get("position"), dict):
                continue
            p = it["position"]
            ex = str(it.get("ex") or "")
            k = f"{ex}:{p.get('symbol')}:{p.get('side')}:lev"
            seen.add(k)
            if self._fast_capable(ex, it.get("product"), p):
                continue
            age = now - float(_f(it.get("measured_at")) or 0)
            ok9 = (ex, it.get("product")) in prod_ok and bool(it.get("fresh")) and self._after_kchg(ex, it)
            out.append({"key": k, "vk": f"lev:{ex}:{it.get('product')}", "name": f"{p.get('symbol')} {_side_ko(p.get('side'))}".strip(), "ex": ex,
                        "dist": fut_dist(p.get("liq"), p.get("mark"), p.get("side")), "mark": p.get("mark"), "liq": p.get("liq"), "lev": p.get("leverage"),
                        "side": p.get("side"), "alert_ok": ok9, "resolve_ok": ok9 and -60 <= age <= MARK_FRESH and side_ok(p.get("side")), "slow": True,
                        "levsrc": [ex, it.get("product"), str(p.get("settle") or "")]})
        for k in list(self.st["fut"]):
            e = self.st["fut"][k]
            if not k.endswith(":lev") or not isinstance(e, dict):
                continue
            if k in seen:
                e.pop("absent", None)
                continue
            pair = tuple((e.get("levsrc") or [])[:2])
            if self._lev_gone_ok(e, pair, prod_ok, prod_at, now, POS_RESOLVE_AGE):
                gone.append(k)
                continue
            if pair in prod_ok and -60 <= now - prod_at.get(pair, 0) <= POS_RESOLVE_AGE and _absent(self.st["fut"], k, now):
                del self.st["fut"][k]
                self.dirty = True
        return out, gone

    def _lev_migrate(self):
        moved = self.st.setdefault("moved", {})
        for k in [k for k in self.st["fut"] if k.endswith(":lev")]:
            e = self.st["fut"][k]
            src9 = list(e.get("levsrc") or []) if isinstance(e, dict) else []
            if len(src9) < 2:
                continue
            pair = (src9[0], src9[1])
            sym, side = (k.rsplit(":", 3) + ["", "", ""])[1:3]
            if not self._fast_capable(pair[0], pair[1], {"symbol": sym, "side": side, "settle": src9[2] if len(src9) > 2 and src9[2] else None}):
                continue
            fk = f"{pair[0]}:{sym}:{side}:"
            del self.st["fut"][k]
            if fk not in self.st["fut"]:
                e.pop("levsrc", None)
                e.pop("absent", None)
                self.st["fut"][fk] = e
            moved[k] = fk
            while len(moved) > 200:
                moved.pop(next(iter(moved)))
            self.dirty = True

    @staticmethod
    def _fast_capable(ex, product, p) -> bool:
        if ex not in FAST_EX:
            return False
        if ex == "okx":
            return True
        if ex == "binance":
            return product == "futures_linear"
        if ex == "bybit":
            return product == "futures_linear" and str(p.get("settle") or "USDT").upper() == "USDT"
        return False

    def _judge(self, now, cfg):
        th = self.th()
        link = ""
        pub = AP.public_link("dash", cfg)
        if pub:
            link = f"\n[보기] {pub}"
        frows, fgone = self._rows_futures(now, th)
        rrows, rgone = self._rows_risk(now)
        snap = json.loads(json.dumps(self.st))
        self._cadence(frows, rrows, th, now)
        lines = judge_futures(self.st["fut"], frows, fgone, th, now, link) + judge_risk(self.st["risk"], rrows, rgone, now, link)
        if not lines:
            return []
        out = []
        try:
            for kind, text, meta in lines:
                d = {"ts": int(now), "kind": kind, "cat": AP.cat_of(kind), "text": text, "key": meta["k"], "lw": meta}
                if meta.get("st") == 0:
                    d["resolved"] = True
                common.append_durable_jsonl(self.qpath, d)
                out.append(d)
        except Exception as e:
            self.st.clear()
            self.st.update(snap)
            log.warning("청산 감시 긴급 줄 적재 실패(다음 판 다시): %s", common.safe_err(e)[:120])
            return out
        self.dirty = True
        log.info("청산 감시 알림 %d건: %s", len(out), ", ".join(f"{d['kind']}:{d['lw'].get('st')}" for d in out))
        return out

    def _cadence(self, frows, rrows, th, now):
        near = {}
        kick = set()
        for r in frows:
            if r.get("slow"):
                continue
            vk = r["vk"]
            s = self.v.get(vk) or {}
            if r.get("dist") is not None and r["dist"] <= th * 2:
                near[vk] = True
            p = (s.get("pos") or {}).get(r["key"]) or {}
            m0, m1 = _f(p.get("mark_at_pos")), _f(r.get("mark"))
            zk = s.setdefault("zk", set())
            if r.get("dist") is not None and r["dist"] <= th and r["key"] not in zk:
                zk.add(r["key"])
                kick.add(vk)
            elif r.get("dist") is not None and r["dist"] > th * RESOLVE_X:
                zk.discard(r["key"])
            if m0 and m1 and abs(m1 / m0 - 1) >= BIG_MOVE:
                kick.add(vk)
        for vk, s in self.v.items():
            s["every"] = MARK_NEAR_SEC if near.get(vk) else MARK_SEC
            s["near"] = bool(near.get(vk))
            if vk in kick and now - float(s.get("kicked") or 0) >= KICK_GAP and s.get("pos"):
                jn = f"hl:{vk[3:]}" if vk.startswith("hl:") else f"acct:{vk}"
                j = self._job(jn)
                if j["fut"] is None and now - float(s.get("pos_ts") or 0) >= 1.0:
                    j["due"] = min(j["due"], now)
                    s["kicked"] = now
        self.__dict__["_risk_near"] = {r["key"] for r in rrows if r.get("r") is not None and r.get("call") and r["r"] >= r["call"] * NEAR_X}
        for r in rrows:
            if not r.get("slow") and r.get("call") and risk_stage(r.get("r"), r.get("call"), r.get("liq")) > int((self.st["risk"].get(r["key"]) or {}).get("st") or 0) \
                    and r.get("est") and r.get("age", 0) > 10:
                j = self._job(f"risk:{_risk_src(r['key'])}")
                if j["fut"] is None:
                    j["due"] = min(j["due"], now)

    def _hl_conf(self, cfg):
        try:
            import perp_dex
            hl = [a["address"] for a in perp_dex.configured(cfg).get("hyperliquid") or []]
        except Exception as e:
            log.warning("청산 감시 하이퍼리퀴드 설정 읽기 실패(이번 판 건너뜀): %s", common.safe_err(e)[:100])
            return None
        for vk in [k for k in self.v if k.startswith("hl:") and k[3:] not in hl]:
            self.v.pop(vk, None)
            self.agen[vk[3:]] = int(self.agen.get(vk[3:], 0)) + 1
        return hl

    def _schedule(self, now, env, cfg, hl=None):
        for ex in FAST_EX:
            if not all(env.get(k) for k in NEED_KEYS[ex]):
                self.v.pop(ex, None)
                continue
            s = self.v.setdefault(ex, {"pos": {}})
            has = bool(s.get("pos"))
            if self._submit(f"acct:{ex}", lambda ex=ex, env=dict(env): self.fetch_positions(ex, env), now):
                self._due(f"acct:{ex}", POS_SEC if has else DISC_SEC, now)
                self.jobs[f"acct:{ex}"]["ksig"] = _key_sig(env, ex)
            if has:
                syms = sorted({(p["sym"], p.get("inst")) for p in s["pos"].values()})
                if self._submit(f"mark:{ex}", lambda ex=ex, syms=syms: self.fetch_marks(ex, syms), now):
                    self._due(f"mark:{ex}", s.get("every") or MARK_SEC, now)
        for addr in hl or ():
            s = self.v.setdefault(f"hl:{addr}", {"pos": {}})
            if self._submit(f"hl:{addr}", lambda a=addr: self.fetch_hl(a), now):
                self._due(f"hl:{addr}", MARK_NEAR_SEC if s.get("near") else DISC_SEC, now)
        srcs = []
        if all(env.get(k) for k in NEED_KEYS["okx"]):
            srcs.append("okx_loan")
        if all(env.get(k) for k in NEED_KEYS["binance"]):
            srcs += ["bn_loan", "bn_margin"]
        if all(env.get(k) for k in NEED_KEYS["bybit"]):
            srcs.append("bybit_loan")
        for src in [k for k in self.risk if k not in srcs]:
            self.risk.pop(src, None)
        for src in srcs:
            if self._submit(f"risk:{src}", lambda src=src, env=dict(env), cfg=cfg: self.fetch_risk(src, env, cfg), now):
                self._due(f"risk:{src}", RISK_SEC, now)
                self.jobs[f"risk:{src}"]["ksig"] = _key_sig(env, _risk_ex(src))
        need = {}
        near_ex = set()
        for src in srcs:
            for it in ((self.risk.get(src) or {}).get("recs") or {}).values():
                name, m = pick_metric(it)
                if name not in ("ltv", "margin_level") or norm_metric(m)[1] is None:
                    continue
                ex9 = _risk_ex(src)
                for c in (it.get("collateral") or []) + (it.get("debt") or []):
                    if c.get("ccy") and c["ccy"] not in STABLES:
                        need.setdefault(ex9, set()).add(c["ccy"])
                if it["id"] in (self.__dict__.get("_risk_near") or ()):
                    near_ex.add(ex9)
        for ex9, syms in need.items():
            if self._submit(f"rpx:{ex9}", lambda ex9=ex9, syms=sorted(syms): self.fetch_spot(ex9, syms), now):
                self._due(f"rpx:{ex9}", RISK_PX_NEAR if ex9 in near_ex else RISK_PX_SEC, now)
        conf9 = self._slow_conf()
        live = set(self.v) | set(conf9 or ())
        unknown9 = hl is None or conf9 is None
        for k in [k for k in self.st["fut"] if not unknown9 and not _vk_of(k).startswith("lev:") and _vk_of(k) not in live]:
            del self.st["fut"][k]
            self.dirty = True
        for k in [k for k in self.st["risk"] if _risk_src(k) not in ("lev", "dex") and _risk_src(k) not in srcs]:
            del self.st["risk"][k]
            self.dirty = True
        lev = self._lev(now)
        nokey = {(p.get("ex"), p.get("product")) for p in lev.get("products") or [] if isinstance(p, dict) and p.get("status") == "no_key"}
        for g9, ks in (("fut", [k for k in self.st["fut"] if _vk_of(k).startswith("lev:")]), ("risk", [k for k in self.st["risk"] if _risk_src(k) == "lev"])):
            for k in ks:
                e = self.st[g9][k]
                pair = tuple((e.get("levsrc") or [])[:2]) if g9 == "fut" else tuple(k.split(":", 2)[:2])
                if pair in nokey:
                    del self.st[g9][k]
                    self.dirty = True


def _vk_of(key) -> str:
    ex = str(key).split(":", 1)[0]
    if str(key).endswith(":lev"):
        return "lev:" + ex
    return ("hl:" + str(key).rsplit(":", 1)[-1]) if ex == "hyperliquid" else ex


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _key_sig(env, ex):
    vals = [str((env or {}).get(k) or "") for k in LEV_KEYS.get(ex, ())]
    if not vals or not all(vals):
        return None
    return hashlib.sha256("\x00".join(vals).encode()).hexdigest()


def _risk_ex(src) -> str:
    return {"okx_loan": "okx", "bn_loan": "binance", "bn_margin": "binance", "bybit_loan": "bybit"}.get(src, src)


def _risk_src(key) -> str:
    ex, prod = (str(key).split(":", 2) + ["", ""])[:2]
    if prod == DEX_PROD:
        return "dex"
    return {("okx", "loan"): "okx_loan", ("binance", "loan"): "bn_loan", ("binance", "margin_cross"): "bn_margin",
            ("binance", "margin_isolated"): "bn_margin", ("bybit", "loan"): "bybit_loan"}.get((ex, prod), "lev")


class _Done:

    def __init__(self, fn):
        try:
            self._r, self._e = fn(), None
        except BaseException as e:
            self._r, self._e = None, e

    def done(self):
        return True

    def result(self):
        if self._e is not None:
            raise self._e
        return self._r


_BG = {"started": False}
HL_HOST = "api.hyperliquid.xyz"


def _share_hl_rl(rl_map, clock=time.time):
    if rl_map is None:
        return False
    try:
        import perp_dex
    except Exception:
        return False
    orig = perp_dex._http_default
    if getattr(orig, "_liq_shared", False):
        return True

    def guarded(url, body=None, timeout=15):
        host = urllib.parse.urlsplit(url).hostname or ""
        if host != HL_HOST:
            return orig(url, body, timeout)
        until = float(rl_map.get(host, 0) or 0)
        if clock() < until:
            raise perp_dex.PerpHTTPError(429, "공유 레이트 제한 대기(청산 감시·수집기 공용)", str(int(until - clock()) + 1))
        try:
            return orig(url, body, timeout)
        except perp_dex.PerpHTTPError as e:
            if e.code == 429:
                try:
                    ra = float(e.retry_after or 0)
                except (TypeError, ValueError):
                    ra = 0.0
                rl_map[host] = max(float(rl_map.get(host, 0) or 0), clock() + min(max(ra, 60.0), 3 * 86400))
            raise
    guarded._liq_shared = True
    if perp_dex.HTTP is orig:
        perp_dex.HTTP = guarded
    perp_dex._http_default = guarded
    return True


def start_background(env_fn, rl_map=None):
    if _BG["started"]:
        return None
    _BG["started"] = True
    w = Watcher(env_fn=env_fn, rl_map=rl_map)
    try:
        _share_hl_rl(rl_map)
    except Exception as e:
        log.warning("하이퍼리퀴드 백오프 공유 설정 실패: %s", common.safe_err(e)[:120])

    pause = threading.Event()

    def loop():
        while True:
            t0 = time.time()
            try:
                w.step(t0)
            except Exception as e:
                log.warning("청산 빠른 감시 판 실패(다음 판): %s", common.safe_err(e)[:160])
            pause.wait(max(0.05, TICK - (time.time() - t0)))
    threading.Thread(target=loop, name="liq-watch", daemon=True).start()
    return w
