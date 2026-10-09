"""Daily and weekly trade review generator."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import review_prompt as rp
import review_progress as rprog
import salelink as _salelink
import day_memo

log = common.setup_logging("tj-review")

KST = timezone(timedelta(hours=9))
OUT_PATH = os.path.join(common.STATE_DIR, "reviews_llm.json")
WEEKLY_PATH = os.path.join(common.STATE_DIR, "reviews_llm_weekly.json")
CLAUDE_BINS = ("claude", os.path.expanduser("~/.local/bin/claude"),
               "/opt/homebrew/bin/claude", "/usr/local/bin/claude")

PROMPT = rp.DAILY_PROMPT
PROMPT_VERSION = rp.PROMPT_VERSION
REVIEW_MODEL = "claude-sonnet-5-5"
CATCHUP_PACE_S = 20
CATCHUP_DAYS = 3
REALIZED_MIN_USD = 0.5
DCA_MAX_USD = 10.0
DCA_GAP_S = 180
DCA_MIN_VENUES = 3
NOTE_MAX = 60
OBS_HARD = 200
STABLES = {"USDT", "USDC", "USDG", "DAI", "FDUSD", "USD1", "PYUSD", "TUSD", "USDE", "KRW"}
EX_NAME = {"upbit": "업비트", "binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인",
           "gate": "게이트", "bithumb": "빗썸"}
_EX_KO = set(EX_NAME.values())
KRW_MARKETS = {"업비트", "빗썸"}
GAS_KIND_KO = {"FAILED": "실패 tx", "LP_ADD": "LP 예치", "LP_REMOVE": "LP 회수", "NOOP": "승인·기타", "TRANSFER_OUT_EX": "거래소 입금 전송",
               "BRIDGE": "브릿지", "TRANSFER_SELF": "내 지갑 간 이동", "TRANSFER_OUT": "외부 전송", "PROGRAM_IN": "프로그램 수령",
               "SWAP": "매매 미연결 스왑"}
GAS_KIND_KO["BRIDGE_FEE"] = "브릿지 수수료"
GAS_MENTION_MIN = 5.0
GAS_MENTION_PCT = 0.05
FAILED_GAS_MUST = 50.0
PAIR_WINDOW_S = 600
HEDGE_S = 60
REENTRY_MIN_USD = 100.0
REENTRY_SOLD_RATIO = 0.2
DCA_SINGLE_MIN_N = 10
DCA_LOOKBACK_D = 30
MINOR_USD = 100.0
MINOR_REALIZED = 20.0
CATCHUP_OLD_MAX = 5
GRADE_WARN_USD = -1000.0
GRADE_CAUTION_USD = -100.0
GRADE_IDLE_USD = 20.0
CYCLE_MIN_SELL = 100.0
WEEKLY_PROMPT_VERSION = rp.WEEKLY_PROMPT_VERSION
STABLE_LIKE = STABLES | {"USDS", "USDP", "USD", "RLUSD", "BUSD", "USDD", "FRAX", "LUSD", "GUSD", "CUSD", "USD0", "USDF", "EURC"}
OPEN_SLOT_MIN = 10
SPLIT_REF_MIN_USD = 5000.0
SPLIT_REF_N = 10
GRADE_LOSS_USD = -20.0
REVIEW_LEN_MAX = rp.len_preset("daily")["max"]
WEEKLY_LEN_MAX = rp.len_preset("weekly")["max"]
WEEKLY_PATTERNS_MAX = rp.len_preset("weekly")["pat_max"]
WEEKLY_FIELD_HARD = 320
OBS_MAX = rp.len_preset("daily")["obs"]
PREFS_PATH = os.path.join(common.STATE_DIR, "ui_prefs.json")
PROGRESS_PATH = os.path.join(common.STATE_DIR, "review_progress.json")
CLI_START_GAP_S = 3.0
_CLI_PACE = threading.Lock()
_CLI_LAST = [0.0]
_GS = threading.local()
_FILL_OVERRIDE = {}


def claude_bin():
    for b in CLAUDE_BINS:
        try:
            subprocess.run([b, "--version"], capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
            _cli_probe(b)
            return b
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _hosts(cfg):
    port = int((cfg.get("web") or {}).get("port", 8023))
    hosts = ["127.0.0.1"]
    for b in ("tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
              "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        try:
            out = subprocess.run([b, "ip", "-4"], capture_output=True, text=True, timeout=10)
            cand = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
            if cand.startswith("100."):
                hosts.append(cand)
                break
        except (OSError, subprocess.SubprocessError):
            continue
    return port, hosts


STATE_TIMEOUT = 300
STATE_MAX_AGE = 300


def _get_json(cfg, path, timeout=STATE_TIMEOUT):
    import urllib.error
    import urllib.request
    port, hosts = _hosts(cfg)
    last_err = None
    for ip in hosts:
        try:
            url = f"http://{ip}:{port}{path}"
            hdr = {}
            if ip == "127.0.0.1":
                try:
                    import login_auth
                    hdr = login_auth.internal_headers()
                except Exception:
                    hdr = {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr) if hdr else url, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last_err = e
        except Exception as e:
            last_err = e
        log.warning("%s 조회 실패(%s) — 다음 후보: %s", path.split("?")[0], ip, last_err)
    raise RuntimeError(f"{path.split('?')[0]} 조회 전부 실패({', '.join(hosts)}): {last_err}")


def fetch_state(cfg, max_age=STATE_MAX_AGE) -> dict:
    if not max_age:
        return _get_json(cfg, "/api/state")
    import urllib.error
    try:
        return _get_json(cfg, f"/api/state?max_age={int(max_age)}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return _get_json(cfg, "/api/state")


class DayEvents(dict):
    hidden = None


def fetch_day_events(cfg, d_from, d_to=None):
    import urllib.error
    q = f"date={d_from}" if not d_to or d_to == d_from else f"from={d_from}&to={d_to}"
    try:
        body = _get_json(cfg, "/api/day_events?" + q, timeout=STATE_TIMEOUT)
    except urllib.error.HTTPError as e:
        log.warning("/api/day_events 없음(HTTP %s, 구 tj-web) — /api/state 이벤트(카드 최근 60건·부가 최신 150건)로 폴백", e.code)
        return None
    except Exception as e:
        log.warning("/api/day_events 조회 실패 — /api/state 이벤트로 폴백: %s", e)
        return None
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        log.warning("/api/day_events 응답 형식 이상 — /api/state 이벤트로 폴백")
        return None
    out = DayEvents()
    out.hidden = {}
    for e in body["events"]:
        if isinstance(e, dict) and e.get("iso"):
            out.setdefault(e["iso"], []).append(e)
    for e in body.get("hidden") or []:
        if isinstance(e, dict) and e.get("iso"):
            out.hidden.setdefault(e["iso"], []).append(e)
    return out


def _today_iso(st) -> str:
    return st.get("todayIso") or datetime.now(KST).strftime("%Y-%m-%d")


STATE_DAY_WAIT_S = 30
STATE_DAY_TRIES = 20


def _state_for_today(cfg, sleep=time.sleep, now=None):
    def built_day(st9):
        try:
            return datetime.fromtimestamp(float(st9.get("builtAt")), KST).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None
    st = fetch_state(cfg)
    for i in range(STATE_DAY_TRIES + 1):
        real = (now() if now else datetime.now(KST)).strftime("%Y-%m-%d")
        bd = built_day(st)
        if bd is None or bd >= real:
            return st
        if i == STATE_DAY_TRIES:
            break
        log.info("상태 스냅샷이 %s 빌드(오늘 %s 전) — 새 빌드 기다림(%d초)", bd, real, STATE_DAY_WAIT_S)
        sleep(STATE_DAY_WAIT_S)
        st = fetch_state(cfg)
    raise RuntimeError("상태 스냅샷이 오늘 전 빌드 — 보충 보류(%s < %s)" % (built_day(st), real))


def _realized(f, day_iso):
    mm = day_iso[5:10]
    rbd, fbd = (f.get("realizedByDate") or {}), ((f.get("futures") or {}).get("realizedByDate") or {})
    spot = (rbd.get(day_iso) if day_iso in rbd else rbd.get(mm, 0)) or 0
    fut = (fbd.get(day_iso) if day_iso in fbd else fbd.get(mm, 0)) or 0
    return float(spot), float(fut)


def realized_days(st) -> list:
    f = st["fields"]
    days = set()
    for src in (f.get("realizedByDate") or {}, (f.get("futures") or {}).get("realizedByDate") or {}):
        for k, v in src.items():
            try:
                if len(k) == 10 and abs(float(v or 0)) >= REALIZED_MIN_USD:
                    days.add(k)
            except (TypeError, ValueError):
                continue
    return sorted(days)


_NUM_RX = re.compile(r"-?[\d,]*\.?\d+(?:[eE][-+]?\d+)?")
_UNK_PART = re.compile(r"일부 원가미상 ([\d,\.]+(?:[eE][-+]?\d+)?)개 \$([\d,\.]+)")
_UNK_ALL = re.compile(r"(?<!일부 )원가미상 \$([\d,\.]+)")


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RX.search(str(v or "").replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _r(x, nd=2):
    if x is None:
        return None
    x = float(x)
    if x == 0:
        return 0
    if abs(x) >= 1:
        v = round(x, nd)
        return int(v) if v == int(v) and abs(v) >= 1000 else v
    return float(f"{x:.6g}")


def _hm(ts) -> str:
    return datetime.fromtimestamp(int(ts), KST).strftime("%H:%M")


def _side(k: str):
    k = str(k or "")
    if "매도" in k:
        return "sell"
    if "매수" in k:
        return "buy"
    return None


def _venue(e) -> str:
    k, d = str(e.get("k") or ""), str(e.get("d") or "")
    head = d.split(" · ", 1)[0].strip() if d else ""
    if (k.startswith("거래소") or k.startswith("온체인")) and head:
        return head
    if e.get("lp") or k.startswith("LP") or "유동성" in k:
        return "LP"
    m = re.match(r"(\S+) (?:입금 완료|출금)", d)
    if m and m.group(1) in _EX_KO:
        return m.group(1)
    src = str(e.get("src") or "")
    if src.startswith("ex:") and not k.startswith("온체인"):
        return EX_NAME.get(src[3:], src[3:])
    if e.get("chain") and e.get("chain") != "?":
        return str(e["chain"])
    return head.split(" ", 1)[0] if head else "?"


def _norm_events(evs, day_iso) -> list:
    out = []
    base = datetime.strptime(day_iso, "%Y-%m-%d").replace(tzinfo=KST)
    for e in evs:
        try:
            ts = int(e.get("ts") or e.get("_ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if not ts:
            m = re.search(r"(\d\d):(\d\d)", str(e.get("t") or ""))
            ts = int((base + timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))).timestamp()) if m else int(base.timestamp())
        k = str(e.get("k") or "")
        is_lp = bool(e.get("lp")) or e.get("kind") == "lp"
        o = {"ts": ts, "k": k, "d": str(e.get("d") or ""), "sym": str(e.get("sym") or "?"), "v": _venue(e),
             "side": None if is_lp else _side(k), "q": _num(e.get("q")), "usd": _num(e.get("a")), "lp": is_lp}
        if e.get("imp"):
            o["imp"] = e.get("imp")
        k9 = e.get("aK")
        if isinstance(k9, (int, float)) and not isinstance(k9, bool) and k9 > 0:
            o["krw"] = float(k9)
        out.append(o)
    out.sort(key=lambda o: o["ts"])
    return out


def _unknown_of(e):
    d = e["d"]
    m = _UNK_PART.search(d)
    if m:
        return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    m = _UNK_ALL.search(d)
    if m:
        return float(e["q"] or 0), float(m.group(1).replace(",", ""))
    return 0.0, 0.0


DCA_NOTE = "같은 몇 분 안 여러 곳 소액 매수 묶음"
_DCA_NOTE_HASH = "정기 소액 분산 매수(known_patterns) — 지적 대상 아님"


def _hash_core_dca(core: dict) -> dict:
    d9 = core.get("small_dca")
    if isinstance(d9, dict) and "note" in d9:
        core["small_dca"] = dict(d9, note=_DCA_NOTE_HASH)
    return core


def _mark_dca(norm) -> dict:
    small = [o for o in norm if o["side"] and o["usd"] is not None and o["usd"] <= DCA_MAX_USD]
    clusters, cur = [], []
    for o in small:
        if cur and o["ts"] - cur[-1]["ts"] > DCA_GAP_S:
            clusters.append(cur)
            cur = []
        cur.append(o)
    if cur:
        clusters.append(cur)
    big = {o["sym"] for o in norm if o["side"] == "buy" and (o["usd"] or 0) > DCA_MAX_USD}
    single = {}
    for o in small:
        if o["side"] == "buy" and o["sym"] not in big:
            single.setdefault((o["sym"], o["v"]), []).append(o)
    for c in single.values():
        if len(c) >= DCA_SINGLE_MIN_N:
            clusters.append(c)
    n = usd_b = usd_s = 0.0
    syms, venues, bursts = {}, set(), 0
    for c in clusters:
        c = [o for o in c if not o.get("dca")]
        if not c or (len({o["v"] for o in c}) < DCA_MIN_VENUES and not (len(c) >= DCA_SINGLE_MIN_N and len({o["v"] for o in c}) == 1
                                                                          and all(o["side"] == "buy" and o["sym"] not in big for o in c))):
            continue
        bursts += 1
        for o in c:
            o["dca"] = True
            n += 1
            venues.add(o["v"])
            if o["side"] == "buy":
                usd_b += o["usd"] or 0
                syms[o["sym"]] = syms.get(o["sym"], 0) + (o["usd"] or 0)
            else:
                usd_s += o["usd"] or 0
    if not n:
        return {}
    return {"n": int(n), "bursts": bursts, "buy_usd": _r(usd_b), "fee_sell_usd": _r(usd_s), "venues": len(venues),
            "by_sym": {k: _r(v) for k, v in sorted(syms.items(), key=lambda kv: -kv[1])[:8]},
            "note": DCA_NOTE}


def _agg(fl):
    q = sum(o["q"] or 0 for o in fl)
    usd = sum(o["usd"] or 0 for o in fl)
    px = [(o["usd"] / o["q"]) for o in fl if o["q"] and o["usd"]]
    return q, usd, (usd / q if q else None), (px[0] if px else None), (px[-1] if px else None)


def _first1m(fl):
    t0 = fl[0]["ts"]
    w = [o for o in fl if o["ts"] - t0 < 60 and o["q"] and o["usd"]]
    q = sum(o["q"] for o in w)
    u = sum(o["usd"] for o in w)
    return q, u, (u / q if q else None)


def _split_stats(sells):
    if not sells:
        return None, None
    t0 = sells[0]["ts"]
    q_all = sum(o["q"] or 0 for o in sells)
    q2 = sum(o["q"] or 0 for o in sells if o["ts"] - t0 < 120)
    share = round(100.0 * q2 / q_all, 1) if q_all else None
    _, _, v1 = _first1m(sells)
    later = [o for o in sells if o["ts"] - t0 >= 60 and o["q"] and o["usd"]]
    lq = sum(o["q"] for o in later)
    lv = sum(o["usd"] for o in later) / lq if lq else None
    chg = round((lv / v1 - 1) * 100, 2) if (lv and v1) else None
    return share, chg


def fills_agg(norm) -> list:
    groups = {}
    for o in norm:
        if o["side"] and not o.get("dca") and str(o["sym"]).upper() not in STABLE_LIKE:
            groups.setdefault((o["sym"], o["v"], o["side"]), []).append(o)
    out = []
    for (sym, v, side), fl in groups.items():
        q, usd, vwap, p0, p1 = _agg(fl)
        row = {"sym": sym, "venue": v, "side": side, "n": len(fl), "qty": _r(q), "usd": _r(usd), "vwap": _r(vwap),
               "px_first": _r(p0), "px_last": _r(p1), "t_first": _hm(fl[0]["ts"]), "t_last": _hm(fl[-1]["ts"])}
        if side == "sell":
            uq = sum(_unknown_of(o)[0] for o in fl)
            uu = sum(_unknown_of(o)[1] for o in fl)
            row["unknown_qty"] = _r(uq)
            row["unknown_pct"] = round(100.0 * uq / q, 1) if q else 0
            if uu:
                row["unknown_usd"] = _r(uu)
            _, _, v1 = _first1m(fl)
            if vwap and v1 and len(fl) > 1 and any(o["ts"] - fl[0]["ts"] >= 60 for o in fl):
                row["vwap_1m"] = _r(v1)
                row["slip_pct"] = round((vwap / v1 - 1) * 100, 2)
        out.append(row)
    out.sort(key=lambda r: -(r["usd"] or 0))
    return out


def _krw_px(norm, skip_syms=()) -> dict:
    groups = {}
    for o in norm:
        if (o["side"] == "sell" and not o.get("dca") and o["v"] in KRW_MARKETS and o["sym"] not in skip_syms
                and o.get("krw") and o.get("q") and str(o["sym"]).upper() not in STABLE_LIKE):
            groups.setdefault((o["sym"], o["v"]), []).append(o)
    out = {}
    for (sym, v), fl in groups.items():
        q = sum(o["q"] for o in fl)
        if not q:
            continue
        out.setdefault(sym, {})[v] = {"vwap_krw": _r(sum(o["krw"] for o in fl) / q),
                                      "px_first_krw": _r(fl[0]["krw"] / fl[0]["q"]), "px_last_krw": _r(fl[-1]["krw"] / fl[-1]["q"])}
    return out


def _open_slot(ts):
    dt = datetime.fromtimestamp(int(ts), KST)
    m = dt.minute % 30
    if m > OPEN_SLOT_MIN:
        return None
    return int(dt.replace(minute=dt.minute - m, second=0, microsecond=0).timestamp())


def _listing_open(evs_sym, seen):
    if seen is None:
        return None
    sells = [o for o in evs_sym if o["side"] == "sell" and not o.get("dca")]
    if not sells:
        return None
    s0 = sells[0]
    if s0["v"] not in KRW_MARKETS:
        return None
    if any((x, s0["v"]) in seen for x in {s0["sym"], s0.get("sym_raw") or s0["sym"]}):
        return None
    t0 = _open_slot(s0["ts"])
    if not t0:
        return None
    if any(o["side"] and o["v"] == s0["v"] and o["ts"] < s0["ts"] for o in evs_sym):
        return None
    pre = [o for o in evs_sym if o["k"] == "입금 확인" and o["v"] == s0["v"] and o["ts"] < t0]
    return (t0, pre[0]) if pre else None


def _timeline(evs_sym, seen=None) -> dict:
    tl = {}
    buys = [o for o in evs_sym if o["side"] == "buy" and not o.get("dca")]
    sells = [o for o in evs_sym if o["side"] == "sell" and not o.get("dca")]
    wd = [o for o in evs_sym if o["k"] == "전송" and ("출금" in o["d"] or "입금 주소" in o["d"])]
    dep = [o for o in evs_sym if o["k"] == "입금 확인"]
    if buys:
        tl["first_buy"] = _hm(buys[0]["ts"])
    if wd:
        tl["withdraw"] = _hm(wd[0]["ts"])
    dep_same = [o for o in dep if sells and o["v"] == sells[0]["v"] and o["ts"] <= sells[0]["ts"]]
    d0 = dep_same[0] if dep_same else (dep[0] if dep else None)
    if d0:
        tl["deposit"] = _hm(d0["ts"])
        tl["deposit_venue"] = d0["v"]
    if sells:
        tl["first_sell"] = _hm(sells[0]["ts"])
        tl["first_sell_venue"] = sells[0]["v"]
        tl["last_sell"] = _hm(sells[-1]["ts"])
        lo = _listing_open(evs_sym, seen)
        if lo:
            tl["open"] = _hm(lo[0])
            tl["open_to_sell_min"] = int((sells[0]["ts"] - lo[0]) // 60)
            tl["deposit_before_open"] = True
        elif dep_same:
            tl["dep_to_sell_min"] = int((sells[0]["ts"] - dep_same[0]["ts"]) // 60)
        if buys and buys[0]["ts"] <= sells[-1]["ts"]:
            tl["hold_min"] = int((sells[-1]["ts"] - buys[0]["ts"]) // 60)
    return tl


def _reentry(evs_sym) -> list:
    fl = [o for o in evs_sym if o["side"] and not o.get("dca") and o["q"] and o["usd"]]
    sells_all = [o for o in fl if o["side"] == "sell"]
    groups, cur = [], None
    for o in fl:
        if o["side"] == "buy":
            if cur is not None and cur[0] == o["v"]:
                cur[1].append(o)
            else:
                cur = (o["v"], [o])
                groups.append(("buy", cur))
        else:
            cur = None
            groups.append(("sell", o))
    out, sold, entered = [], [], False
    for kind, g in groups:
        if kind == "sell":
            sold.append(g)
            continue
        v, grp = g
        bq, bu = sum(x["q"] for x in grp), sum(x["usd"] for x in grp)
        if bu < REENTRY_MIN_USD:
            continue
        prev, sold = sold, []
        if not entered:
            entered = True
            continue
        if any(abs(x["ts"] - y["ts"]) <= HEDGE_S for x in grp for y in sells_all):
            continue
        sq, su = sum(x["q"] for x in prev), sum(x["usd"] for x in prev)
        if sq and bq and su >= REENTRY_SOLD_RATIO * bu:
            out.append({"t": _hm(grp[0]["ts"]), "venue": v, "n": len(grp), "usd": _r(bu), "px": _r(bu / bq),
                        "chase_pct": round(((bu / bq) / (su / sq) - 1) * 100, 2)})
    return out[:5]


def _premium(buys, sells):
    if not buys or not sells:
        return None, None
    def paired(b, x):
        return -HEDGE_S <= x["ts"] - b["ts"] <= PAIR_WINDOW_S
    pb = [b for b in buys if any(paired(b, x) for x in sells)]
    ps = [x for x in sells if any(paired(b, x) for b in buys)]
    sq_all = sum(x["q"] or 0 for x in sells)
    if pb and ps and sum(x["q"] or 0 for x in ps) >= 0.5 * sq_all:
        bq, _, bv, _, _ = _agg(pb)
        sq, _, sv, _, _ = _agg(ps)
        if bv and sv and bq >= 0.5 * sq:
            return round((sv / bv - 1) * 100, 2), len(ps)
    pre = [b for b in buys if b["ts"] <= sells[-1]["ts"]]
    bq, _, bv, _, _ = _agg(pre) if pre else (0, 0, None, None, None)
    _, _, sv, _, _ = _agg(sells)
    if bv and sv and bq >= 0.5 * sq_all:
        return round((sv / bv - 1) * 100, 2), None
    return None, None


def _canon_map(syms) -> dict:
    syms = {s for s in syms if s}
    out = {}
    for s in syms:
        b = s[1:] if s.startswith("$") and len(s) > 1 else s
        if b != s and b in syms:
            out[s] = b
            continue
        m = re.match(r"^(.*[A-Za-z])\d$", b)
        if m and m.group(1) in syms and m.group(1) != s:
            out[s] = m.group(1)
    return out


def _carry_src_keys(raw, sym_set) -> set:
    out = set()
    for e in raw or ():
        if e.get("sym") in sym_set and e.get("pkey") and str(e.get("k") or "") in ("외부 전송", "전송") and "이관" in str(e.get("d") or ""):
            out.add(e["pkey"])
    return out


def _carry(f, sym_set, day_iso, sold=None, src_keys=None):
    pos = [p for p in f.get("positions", []) if p.get("kind") != "gas"]
    ps = [p for p in pos if p.get("sym") in sym_set and (p.get("realizedByDay") or {}).get(day_iso)]
    if not ps:
        return None
    src = [p for p in pos if src_keys and p.get("key") in src_keys and p.get("sym") in sym_set]
    try:
        ots_l = [int(p.get("_ots") or 0) for p in ps + src if p.get("_ots")]
    except (TypeError, ValueError):
        ots_l = []
    ots = min(ots_l) if ots_l else 0
    if not ots:
        return None
    d0 = datetime.fromtimestamp(ots, KST)
    if d0.strftime("%Y-%m-%d") >= day_iso:
        return None
    prior = sum(float(v or 0) for p in ps for k, v in (p.get("realizedByDay") or {}).items() if len(str(k)) == 10 and k < day_iso)
    out = {"first_buy_date": d0.strftime("%Y-%m-%d"),
           "held_days": (datetime.strptime(day_iso, "%Y-%m-%d") - datetime.strptime(d0.strftime("%Y-%m-%d"), "%Y-%m-%d")).days}
    if sold:
        sq, su, rz, known = sold
        if sq and su and known is not None and known >= 80 and su - rz > 0:
            out["avg_cost"] = _r((su - rz) / sq)
    if abs(prior) >= 0.005:
        out["prior_realized"] = _r(prior)
    return out


def _is_stable(sym, p=None) -> bool:
    return str(sym or "").upper() in STABLE_LIKE or (p is not None and p.get("kind") == "stable")


def _coin_rows(norm, f, day_iso, canon=None, dca_inv=None, seen=None, src_keys=None) -> list:
    canon = canon or {}
    by_sym = {}
    for o in norm:
        if not o["lp"] and not _is_stable(o["sym"]):
            by_sym.setdefault(o["sym"], []).append(o)
    real, raw_syms = {}, {}
    for p in f.get("positions", []):
        if p.get("kind") == "gas" or _is_stable(p.get("sym"), p):
            continue
        v = (p.get("realizedByDay") or {}).get(day_iso)
        if v:
            s9 = canon.get(p["sym"], p["sym"])
            raw_syms.setdefault(s9, set()).add(p["sym"])
            r0 = real.setdefault(s9, {"usd": 0.0, "fb_avg": 0.0})
            r0["usd"] += float(v)
            r0["fb_avg"] = r0["fb_avg"] or float(p.get("fbAvg") or 0)
    rows = []
    for sym in set(by_sym) | set(real):
        ev = by_sym.get(sym, [])
        buys = [o for o in ev if o["side"] == "buy" and not o.get("dca")]
        sells = [o for o in ev if o["side"] == "sell" and not o.get("dca")]
        rz = real.get(sym)
        if not buys and not sells and not rz:
            continue
        row = {"sym": sym}
        al = sorted({o.get("sym_raw") for o in ev if o.get("sym_raw")} | (raw_syms.get(sym, set()) - {sym}))
        if al:
            row["aliases"] = al
        if rz:
            row["realized"] = _r(rz["usd"]) if abs(rz["usd"]) >= 0.005 else 0
        bq, bu, bv, _, _ = _agg(buys) if buys else (0, 0, None, None, None)
        sq, su, sv, _, _ = _agg(sells) if sells else (0, 0, None, None, None)
        if buys:
            row["buy"] = {"n": len(buys), "qty": _r(bq), "usd": _r(bu), "vwap": _r(bv)}
        if sells:
            row["sell"] = {"n": len(sells), "qty": _r(sq), "usd": _r(su), "vwap": _r(sv)}
            if su >= SPLIT_REF_MIN_USD and len(sells) > 1:
                sh, _c = _split_stats(sells)
                if sh is not None:
                    row["sell"]["first2m_pct"] = sh
            uq = sum(_unknown_of(o)[0] for o in sells)
            uu = sum(_unknown_of(o)[1] for o in sells)
            row["cost_known_pct"] = round(100.0 * (1 - uq / sq), 1) if sq else 100.0
            if rz and uq > 0 and rz.get("fb_avg"):
                row["est_usd"] = _r(uu - uq * rz["fb_avg"])
            if rz and su - rz["usd"] > 0 and uq / max(sq, 1e-12) <= 0.2:
                row["margin_pct"] = round(100.0 * rz["usd"] / (su - rz["usd"]), 2)
        pm, pairs = _premium(buys, sells)
        if pm is not None and not (row.get("margin_pct") is not None and abs(pm - row["margin_pct"]) < 0.5):
            row["premium_pct"] = pm
            if pairs:
                row["premium_pairs"] = pairs
        tl = _timeline(ev, seen)
        if tl:
            row["path"] = tl
        re9 = _reentry(ev)
        if re9:
            row["reentry"] = re9
        if dca_inv and sym in dca_inv:
            row["dca_inventory"] = True
        if rz:
            sold = (sq, su, rz["usd"], row.get("cost_known_pct")) if sells else None
            cr = _carry(f, raw_syms.get(sym) or {sym}, day_iso, sold, src_keys)
            if cr:
                row["carry"] = cr
        rows.append(row)
    rows.sort(key=lambda r: (-abs(r.get("realized") or 0), -((r.get("sell") or {}).get("usd") or 0),
                             -((r.get("buy") or {}).get("usd") or 0)))
    return rows


def _lp_pair(lp) -> str:
    if lp.get("pool"):
        return str(lp["pool"])
    st9 = set((lp.get("returned") or {}).keys()) | set((lp.get("converted") or {}).keys()) | set((lp.get("principalUnits") or {}).keys())
    tok = [k for k in (lp.get("acquired") or {}) if k not in st9 and k.upper() not in STABLES]
    base = sorted(st9 & STABLES) or sorted(st9)
    if not tok:
        return (base[0] + "/?") if base else "?"
    return "/".join(tok[:1] + base[:1])


def _lp_rows(f, day_iso, now_ts=None, limit=12):
    now_ts = now_ts or time.time()
    rows = []
    for lp in (f.get("lps") or []) + (f.get("lpsPending") or []) + (f.get("lpsClosed") or []):
        try:
            o_ts, l_ts = int(lp.get("openedTs") or 0), int(lp.get("lastTs") or 0)
        except (TypeError, ValueError):
            o_ts = l_ts = 0
        closed = bool(lp.get("closed"))
        rz = (lp.get("realizedByDay") or {}).get(day_iso)
        opened_d = datetime.fromtimestamp(o_ts, KST).strftime("%Y-%m-%d") if o_ts else None
        closed_d = datetime.fromtimestamp(l_ts, KST).strftime("%Y-%m-%d") if (closed and l_ts) else None
        if not (rz or opened_d == day_iso or closed_d == day_iso):
            continue
        end = l_ts if closed else now_ts
        mins = int((end - o_ts) // 60) if o_ts and end > o_ts else None
        fees = float(lp.get("income") or 0) + (0 if closed else float(lp.get("fees") or 0))
        conv = sum(float(v or 0) for k, v in (lp.get("converted") or {}).items() if k.upper() in STABLES and float(v or 0) >= 1)
        row = {"id": str(lp.get("id") or ""), "pair": _lp_pair(lp), "dex": lp.get("dex"), "deposited": _r(float(lp.get("deposited") or 0)),
               "mins": mins, "fees": _r(fees), "closed": closed}
        if mins and mins >= 1 and fees:
            row["per_hour"] = _r(fees / (mins / 60.0))
        if conv:
            row["converted_usd"] = _r(conv)
            tok9 = {k: float(v or 0) for k, v in (lp.get("acquired") or {}).items()
                    if str(k).upper() not in STABLES and float(v or 0) > 0}
            if len(tok9) == 1:
                k9, q9 = next(iter(tok9.items()))
                row["buy_qty"] = _r(q9)
                row["buy_avg_px"] = _r(conv / q9)
        if rz:
            row["realized"] = _r(float(rz))
        rows.append(row)
    rows.sort(key=lambda r: (-abs(r.get("realized") or 0), -(r.get("fees") or 0), -(r.get("deposited") or 0)))
    tot = {"n": len(rows), "deposited": _r(sum(r["deposited"] or 0 for r in rows)), "fees": _r(sum(r["fees"] or 0 for r in rows)),
           "converted_usd": _r(sum(r.get("converted_usd") or 0 for r in rows))}
    return (rows[:limit] if limit else rows), tot


def _compact(norm, skip_syms=()) -> list:
    out, idx = [], {}
    for o in norm:
        if o.get("dca") or o["lp"] or (o["side"] and o["sym"] in skip_syms):
            continue
        key = (o["ts"] // 60, o["sym"], o["v"], o["k"], "" if o["side"] else re.sub(r"[\d,\.\$]+", "#", o["d"]))
        g = idx.get(key)
        if g is None:
            g = idx[key] = {"t": _hm(o["ts"]), "sym": o["sym"], "v": o["v"], "k": o["k"], "n": 0, "q": 0.0, "usd": 0.0}
            if not o["side"] and o["d"]:
                g["d"] = o["d"][:140]
            if o.get("imp"):
                g["imp"] = o["imp"]
            out.append(g)
        g["n"] += 1
        g["q"] += o["q"] or 0
        g["usd"] += o["usd"] or 0
    for g in out:
        g["q"] = _r(g["q"]) if g["q"] else None
        g["usd"] = _r(g["usd"]) if g["usd"] else None
        for k in ("q", "usd"):
            if g[k] is None:
                del g[k]
        if g["n"] == 1:
            del g["n"]
    return out


def _risk_sends(f, day_iso) -> list:
    out = []
    for r in f.get("outflows") or []:
        if not isinstance(r, dict) or r.get("status") == "spam" or r.get("dust"):
            continue
        fl = {x.get("kind") for x in (r.get("flags") or []) if isinstance(x, dict)}
        if "lookalike" not in fl or "spoof_token" in fl:
            continue
        look = next(x for x in r["flags"] if x.get("kind") == "lookalike")
        for tx in r.get("txs") or []:
            if not isinstance(tx, dict) or tx.get("signed") is not True:
                continue
            try:
                d = datetime.fromtimestamp(int(tx.get("ts") or 0), KST).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                continue
            if d == day_iso:
                a = str(r.get("address") or "")
                out.append({"t": _hm(tx["ts"]), "sym": tx.get("sym"), "qty": _r(tx.get("qty")), "usd": _r(tx.get("usdAtSend")),
                            "to": a[:6] + "…" + a[-4:], "looks_like": (look.get("label") or "등록 지갑")})
    return out[:10]


def _hidden_summary(hid) -> dict:
    if not hid:
        return {}
    kinds = {}
    for e in hid:
        k = str(e.get("hideKind") or "기타")
        kinds[k] = kinds.get(k, 0) + 1
    return {"n": len(hid), "by_kind": kinds}


def _fx(f, day_iso) -> dict:
    mm = day_iso[5:10]
    snap = next((d for d in (f.get("dailySeries") or []) if d.get("date") == mm), None) or {}
    u = (f.get("usdtByDate") or {}).get(mm) or (f.get("usdtByDate") or {}).get(day_iso) or {}
    out = {}
    usdt = snap.get("usdt") if snap.get("usdt") is not None else u.get("usdt")
    kimp = snap.get("kimp") if snap.get("kimp") is not None else u.get("kimp")
    if usdt:
        out["usdt_krw"] = usdt
    if kimp is not None:
        out["kimp_pct"] = kimp
    return out


def _att_v2(a) -> bool:
    try:
        return isinstance(a, dict) and int(a.get("v") or 1) >= 2 and all(k in a for k in ("ev", "rz", "rest"))
    except (TypeError, ValueError):
        return False


def _asset_moves(f, day_iso) -> dict:
    mm = day_iso[5:10]
    ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
    i = next((j for j, d in enumerate(ds) if d.get("date") == mm), None)
    if not i:
        return {}
    d, p = ds[i], ds[i - 1]
    a = d.get("att")
    if not isinstance(a, dict):
        return {}
    try:
        u = float(d.get("usdt") or 0)
        out = {"change_usd": _r(float(d["val"]) - float(p["val"])), "market_usd": _r(a.get("mk") or 0),
               "flow_usd": _r(d.get("flow") or 0), "trade_usd": _r(a.get("tr") or 0), "other_usd": _r(a.get("rs") or 0)}
        if _att_v2(a):
            out = {"change_usd": out["change_usd"], "market_usd": _r(a.get("ev") or 0),
                   "realized_usd": _r(a.get("rz") or 0), "flow_usd": out["flow_usd"], "other_usd": _r(a.get("rest") or 0)}
            for k9, a9 in (("lp_fee_usd", "lpf"), ("fx_usd", "kx"), ("unknown_usd", "un")):
                if abs(float(a.get(a9) or 0)) >= 0.005:
                    out[k9] = _r(a[a9])
        if d.get("valKrw") is not None and p.get("valKrw") is not None:
            out["change_krw"] = int(round(float(d["valKrw"]) - float(p["valKrw"])))
        mv = []
        for t in (a.get("top") or [])[:5]:
            r9 = {"sym": str(t[0]), "pct": round(float(t[1]), 1) if t[1] is not None else None, "usd": _r(t[2])}
            if u and d.get("valKrw") is not None:
                r9["krw"] = int(round(float(t[2]) * u))
            mv.append(r9)
        if mv:
            out["movers"] = mv
        et = a.get("etc") or [0, 0]
        if et and et[0]:
            out["movers_rest"] = {"n": int(et[0]), "usd": _r(et[1])}
        a0 = lambda x: float(x.get("est") or 0) + float(x.get("xc") or 0) >= max(50.0, 0.005 * abs(float(x.get("val") or 0)))
        if (a0(p) and p is not ds[-1]) or (a0(d) and d is not ds[-1]):
            out["approx"] = True
    except (TypeError, ValueError, KeyError, IndexError):
        return {}
    return out


def _day_closed(f, day_iso, today_iso=None) -> bool:
    mm = day_iso[5:10]
    ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
    if today_iso and day_iso < today_iso:
        first = _series_first_iso(ds, today_iso)
        if first and day_iso < first:
            return True
    row = next((d for d in ds if d.get("date") == mm), None)
    if row:
        return row.get("valKrw") is not None
    if not today_iso or day_iso >= today_iso:
        return False
    first = _series_first_iso(ds, today_iso)
    if first:
        return day_iso < first
    try:
        return (datetime.strptime(today_iso, "%Y-%m-%d") - datetime.strptime(day_iso, "%Y-%m-%d")).days > 31
    except ValueError:
        return False


def _series_first_iso(ds, today_iso):
    try:
        mmdd = str(ds[0].get("date") or "")
        if not re.match(r"^\d{2}-\d{2}$", mmdd):
            return None
        y = int(today_iso[:4])
        iso = f"{y}-{mmdd}"
        return iso if iso <= today_iso else f"{y - 1}-{mmdd}"
    except (IndexError, ValueError, AttributeError):
        return None


def _asset_moves_krw(f, day_iso) -> dict:
    mm = day_iso[5:10]
    ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
    i = next((j for j, d in enumerate(ds) if d.get("date") == mm), None)
    if not i:
        return {}
    d, p = ds[i], ds[i - 1]
    a = d.get("att")
    try:
        u = float(d.get("usdt") or 0)
        if not isinstance(a, dict) or u <= 0 or d.get("valKrw") is None or p.get("valKrw") is None:
            return {}
        kx = float(a.get("kx") or 0) * u
        out = {"change": int(round(float(d["valKrw"]) - float(p["valKrw"]))), "market": int(round(float(a.get("mk") or 0) * u - kx)),
               "fx": int(round(float(p["val"]) * u - float(p["valKrw"]) + kx)), "flow": int(round(float(d.get("flow") or 0) * u)),
               "trade": int(round(float(a.get("tr") or 0) * u)), "u": u,
               "movers": [{"sym": str(t[0]), "pct": round(float(t[1]), 1) if t[1] is not None else None, "krw": int(round(float(t[2]) * u))}
                          for t in (a.get("top") or [])[:3] if abs(float(t[2] or 0)) >= 0.005]}
        if _att_v2(a):
            out.pop("trade", None)
            out["market"] = int(round(float(a.get("ev") or 0) * u))
            for k9, a9 in (("realized", "rz"), ("lp_fee", "lpf"), ("unknown", "un")):
                out[k9] = int(round(float(a.get(a9) or 0) * u))
    except (TypeError, ValueError, KeyError, IndexError):
        return {}
    return out


def _plans_for(f, syms) -> list:
    plans = f.get("plans") or {}
    if not plans:
        return []
    key_sym = {}
    for c in (f.get("coins") or []) + (f.get("positions") or []):
        if isinstance(c, dict) and c.get("key"):
            key_sym[c["key"]] = c.get("sym")
    out = []
    for k, p in plans.items():
        sym = key_sym.get(k) or k
        if sym not in syms or not isinstance(p, dict):
            continue
        row = {"sym": sym, "target": p.get("target"), "stop": p.get("stop")}
        if p.get("memo"):
            row["memo"] = str(p["memo"])[:300]
        out.append(row)
    return out


DAY_MEMOS_MAX = 20


def _day_memos_for(day_iso) -> list:
    try:
        mm = day_memo.Store().for_date(day_iso)
    except Exception as e:
        log.warning("근거 메모 읽기 실패(무시): %s", e)
        return []
    return [{"sym": s9, "memo": mm[s9]} for s9 in sorted(mm)][:DAY_MEMOS_MAX]


def known_patterns(cfg) -> list:
    kp = ((cfg or {}).get("review") or {}).get("known_patterns")
    if isinstance(kp, list) and kp:
        return [str(x)[:200] for x in kp][:10]
    return list(rp.DEFAULT_KNOWN_PATTERNS)


def _read_reviews(path=None) -> dict:
    path = path or OUT_PATH
    try:
        return common.read_json(path, {}) if os.path.exists(path) else {}
    except (Exception, SystemExit):
        return {}


def _store_put(path, key, rec, drop=None) -> bool:
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            if os.path.exists(path):
                try:
                    cur = common.read_json(path, None)
                except (Exception, SystemExit):
                    cur = None
                if not isinstance(cur, dict):
                    log.error("리뷰 파일 읽기 실패 — 덮어쓰기 보류(%s): %s", key, path)
                    return False
            else:
                cur = {}
            cur[key] = rec
            if drop and isinstance(cur.get(drop), dict) and isinstance(cur[drop].get("fp"), dict):
                cur.pop(drop, None)
            common.atomic_write_json(path, cur)
            return True
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def _store_template(path, day_iso, rec) -> bool:
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        try:
            if not os.path.exists(path):
                return False
            try:
                cur = common.read_json(path, None)
            except (Exception, SystemExit):
                cur = None
            if not isinstance(cur, dict):
                log.error("리뷰 파일 읽기 실패 — 템플릿 다시 쓰기 보류(%s): %s", day_iso, path)
                return False
            vals = [cur[k9] for k9 in (day_iso, day_iso[5:10]) if k9 in cur]
            if not vals or any(not isinstance(v9, dict) or v9.get("model") != "template" for v9 in vals):
                return False
            cur[day_iso] = rec
            common.atomic_write_json(path, cur)
            return True
        finally:
            fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def _rv_for(reviews, day_iso):
    return reviews.get(day_iso) or reviews.get(day_iso[5:10])


def _rv_shown(reviews, day_iso):
    rv = _rv_for(reviews, day_iso)
    return rv if isinstance(rv, dict) and isinstance(rv.get("fp"), dict) else None


def prior_next(reviews, day_iso, days=7) -> list:
    out = []
    d0 = datetime.strptime(day_iso, "%Y-%m-%d")
    for i in range(1, days + 1):
        rv = _rv_shown(reviews, (d0 - timedelta(days=i)).strftime("%Y-%m-%d"))
        nx = str((rv or {}).get("next") or "").strip()
        if nx and nx not in ("없음.", "없음", "—") and nx not in out:
            out.append(nx[:160])
    return out


def prior_obs(reviews, day_iso, days=7) -> list:
    out = []
    d0 = datetime.strptime(day_iso, "%Y-%m-%d")
    for i in range(1, days + 1):
        rv = _rv_shown(reviews, (d0 - timedelta(days=i)).strftime("%Y-%m-%d"))
        for o in (rv or {}).get("obs") or []:
            t = re.sub(r"^\[[^\]]*\]\s*", "", str(o or "")).strip()[:40]
            if t and t not in out:
                out.append(t)
    return out[:16]


_CHAIN_KO = {"eth": "Ethereum", "base": "Base", "bsc": "BSC", "sol": "Solana", "arbitrum": "Arbitrum", "optimism": "Optimism",
             "polygon": "Polygon", "zksync": "zkSync", "scroll": "Scroll", "gnosis": "Gnosis", "robinhood": "Robinhood",
             "arc": "Arc"}
common.fill_chain_table(_CHAIN_KO)


def _day_summary(day_ev, d) -> dict:
    cache = getattr(day_ev, "_sum_cache", None)
    if cache is None:
        cache = {}
        try:
            day_ev._sum_cache = cache
        except AttributeError:
            pass
    if d in cache:
        return cache[d]
    out = {"dca": set(), "fills": set(), "splits": []}
    evs = day_ev.get(d) if day_ev else None
    if evs:
        n9 = _norm_events(evs, d)
        _mark_dca(n9)
        out["dca"] = {o["sym"] for o in n9 if o.get("dca") and o["side"] == "buy"}
        out["fills"] = {(o["sym"], o["v"]) for o in n9 if o["side"]}
        grp = {}
        for o in n9:
            if o["side"] == "sell" and not o.get("dca") and not _is_stable(o["sym"]) and o["q"] and o["usd"]:
                grp.setdefault((o["sym"], o["v"]), []).append(o)
        for fl in grp.values():
            if len(fl) > 1 and sum(o["usd"] for o in fl) >= SPLIT_REF_MIN_USD:
                sh, chg = _split_stats(fl)
                if sh is not None:
                    out["splits"].append((fl[0]["ts"], sh, chg))
    cache[d] = out
    return out


def _dca_syms_recent(day_ev, day_iso) -> set:
    if not day_ev:
        return set()
    d0 = datetime.strptime(day_iso, "%Y-%m-%d")
    out = set()
    for i in range(DCA_LOOKBACK_D + 1):
        out |= _day_summary(day_ev, (d0 - timedelta(days=i)).strftime("%Y-%m-%d"))["dca"]
    return out


def _seen_fills(day_ev, day_iso):
    if day_ev is None:
        return None
    d0 = datetime.strptime(day_iso, "%Y-%m-%d")
    out = set()
    for i in range(1, DCA_LOOKBACK_D + 1):
        out |= _day_summary(day_ev, (d0 - timedelta(days=i)).strftime("%Y-%m-%d"))["fills"]
    return out


def _split_ref(day_ev, day_iso):
    if not day_ev:
        return None
    d0 = datetime.strptime(day_iso, "%Y-%m-%d")
    sp = []
    for i in range(1, DCA_LOOKBACK_D + 1):
        sp += _day_summary(day_ev, (d0 - timedelta(days=i)).strftime("%Y-%m-%d"))["splits"]
    sp = sorted(sp, key=lambda x: -x[0])[:SPLIT_REF_N]
    if len(sp) < 3:
        return None
    chg = [x[2] for x in sp if x[2] is not None]
    out = {"n": len(sp), "first2m_share_med_pct": round(statistics.median([x[1] for x in sp]), 1)}
    if len(chg) >= 3:
        out["later_vs_first1m_med_pct"] = round(statistics.median(chg), 2)
        out["n_later"] = len(chg)
    return out


def _gas_input(f, day_iso, realized_total, norm):
    gx = (f.get("gasExpenseByDate") or {}).get(day_iso)
    if not (isinstance(gx, (list, tuple)) and gx):
        return None
    usd = float(gx[0] or 0)
    kinds = gx[2] if len(gx) > 2 and isinstance(gx[2], dict) else {}
    failed = float((kinds.get("FAILED") or {}).get("usd") or 0)
    if usd < 0.005 or (usd < max(GAS_MENTION_MIN, GAS_MENTION_PCT * abs(realized_total)) and failed < FAILED_GAS_MUST):
        return None
    out = {"usd": round(usd, 2), "tx": int(gx[1] if len(gx) > 1 else 0)}
    bk = {GAS_KIND_KO.get(k, k): {"usd": _r(float(v.get("usd") or 0)), "n": int(v.get("n") or 0)}
          for k, v in sorted(kinds.items(), key=lambda kv: -float(kv[1].get("usd") or 0)) if float(v.get("usd") or 0) >= 0.01}
    if bk:
        out["by_kind"] = bk
    t3 = []
    for k, v in sorted(kinds.items(), key=lambda kv: -float((kv[1].get("top") or {}).get("usd") or 0))[:3]:
        tp = v.get("top") or {}
        if float(tp.get("usd") or 0) < 1.0:
            continue
        row = {"kind": GAS_KIND_KO.get(k, k), "usd": _r(float(tp["usd"])), "t": tp.get("t") or "",
               "chain": _CHAIN_KO.get(str(tp.get("chain") or ""), tp.get("chain") or "?")}
        try:
            ts9 = int(tp.get("ts") or 0)
        except (TypeError, ValueError):
            ts9 = 0
        if k == "FAILED" and ts9:
            near = {}
            for o in norm:
                if o["side"] == "buy" and not o.get("dca") and abs(o["ts"] - ts9) <= PAIR_WINDOW_S:
                    g = near.setdefault((o["sym"], o["v"]), {"sym": o["sym"], "v": o["v"], "t": _hm(o["ts"]), "usd": 0.0})
                    g["usd"] += o["usd"] or 0
            if near:
                nb = max(near.values(), key=lambda x9: x9["usd"])
                nb["usd"] = _r(nb["usd"])
                row["near_buy"] = nb
        t3.append(row)
    if t3:
        out["top3"] = t3
    return out


def grade(data) -> str:
    rt = float(data.get("realized_total") or 0)
    if data.get("risk_sends") or rt <= GRADE_WARN_USD:
        return "경고"
    if rt <= GRADE_LOSS_USD:
        return "주의"
    if data.get("no_fills") and not data.get("lp") and abs(rt) < GRADE_IDLE_USD:
        return "관망"
    return "양호"


def loss_coins(data) -> list:
    rt = float(data.get("realized_total") or 0)
    per = {}
    for r in data.get("realized_by_coin") or []:
        per[r["sym"]] = per.get(r["sym"], 0.0) + float(r.get("usd") or 0)
    for r in data.get("realized_by_lp") or []:
        per["LP " + str(r.get("pool") or r.get("id"))] = per.get("LP " + str(r.get("pool") or r.get("id")), 0.0) + float(r.get("usd") or 0)
    for r in data.get("cycles") or []:
        per[r["sym"]] = per.get(r["sym"], 0.0) + float(r.get("realized") or 0)
    lim = max(abs(rt) * 0.1, 100.0)
    out = [{"sym": k, "usd": _r(v)} for k, v in per.items() if -v >= lim]
    return sorted(out, key=lambda x: x["usd"])[:3]


def _impact_top3(data) -> list:
    c = []
    for r in data.get("coins") or []:
        if r.get("realized"):
            c.append({"what": f"{r['sym']} 실현", "usd": r["realized"]})
    for r in data.get("realized_by_lp") or []:
        c.append({"what": f"LP {r.get('pool')} 실현", "usd": r["usd"]})
    g = data.get("gas_expense") or {}
    fk = (g.get("by_kind") or {}).get(GAS_KIND_KO["FAILED"])
    if fk:
        c.append({"what": "실패 tx 가스", "usd": -float(fk["usd"] or 0)})
    other = float(g.get("usd") or 0) - float((fk or {}).get("usd") or 0)
    if other >= GAS_MENTION_MIN:
        c.append({"what": "매매 외 가스(실패 tx 제외)", "usd": -round(other, 2)})
    for r in (data.get("lp") or {}).get("rows") or []:
        if r.get("converted_usd"):
            c.append({"what": f"LP {r['pair']} 전환 매수(지정가 매수 — 손익 아님)", "usd": r["converted_usd"]})
    for r in data.get("risk_sends") or []:
        c.append({"what": f"위험 전송 {r.get('sym')}", "usd": -float(r.get("usd") or 0)})
    c.sort(key=lambda x: -abs(float(x["usd"] or 0)))
    return c[:3]


def _krw_total(f, day_iso, spot, fut):
    rk = f.get("realizedKrwByDate")
    if not isinstance(rk, dict):
        return None
    fk = ((f.get("futures") or {}).get("realizedKrwByDate") or {})
    sk, fv = rk.get(day_iso), fk.get(day_iso)
    if (sk is None and abs(spot) >= 0.005) or (fv is None and abs(fut) >= 0.005):
        return None
    return int(round(float(sk or 0) + float(fv or 0)))


def gather(st, day_iso=None, day_ev=None, cfg=None, reviews=None) -> dict:
    f = st["fields"]
    today_iso = _today_iso(st)
    day_iso = day_iso or today_iso
    past = day_iso < today_iso
    mm = day_iso[5:10]
    year = int(day_iso[:4])
    raw = []
    for p in (f.get("positions", []) if day_ev is None else ()):
        for e in p.get("events", []):
            if e.get("t", "").startswith(mm):
                raw.append({"sym": p["sym"], "chain": p.get("chain"), **e})
    for e in (f.get("extraEvents", []) if day_ev is None else ()):
        if not e.get("t", "").startswith(mm):
            continue
        try:
            ts9 = int(e.get("_ts") or 0)
        except (TypeError, ValueError):
            ts9 = 0
        if ts9 and datetime.fromtimestamp(ts9, KST).year != year:
            continue
        raw.append(e)
    hid = []
    if day_ev is not None:
        raw = list(day_ev.get(day_iso) or [])
        hid = list((getattr(day_ev, "hidden", None) or {}).get(day_iso) or [])
    norm = _norm_events(raw, day_iso)
    syms9 = {o["sym"] for o in norm if not o["lp"]} | {p["sym"] for p in f.get("positions", [])
                                                      if p.get("kind") != "gas" and (p.get("realizedByDay") or {}).get(day_iso)}
    canon = _canon_map(syms9)
    for o in norm:
        if o["sym"] in canon:
            o["sym_raw"], o["sym"] = o["sym"], canon[o["sym"]]
    dca = _mark_dca(norm)
    dca_inv = _dca_syms_recent(day_ev, day_iso) | {o["sym"] for o in norm if o.get("dca") and o["side"] == "buy"}
    realized_spot, realized_fut = _realized(f, day_iso)
    coins = _coin_rows(norm, f, day_iso, canon, dca_inv, _seen_fills(day_ev, day_iso), _carry_src_keys(raw, syms9 | set(canon.values())))
    minor = {r["sym"] for r in coins
             if ((r.get("buy") or {}).get("usd") or 0) + ((r.get("sell") or {}).get("usd") or 0) < MINOR_USD
             and abs(r.get("realized") or 0) < MINOR_REALIZED}
    coins = [r for r in coins if r["sym"] not in minor]
    by_coin = []
    st_usd, st_krw, st_krw_ok = 0.0, 0.0, True
    for p in f.get("positions", []):
        v = (p.get("realizedByDay") or {}).get(day_iso)
        if v and p.get("kind") == "gas":
            continue
        if v and _is_stable(p.get("sym"), p):
            st_usd += float(v)
            k9 = (p.get("realizedKrwByDay") or {}).get(day_iso)
            if k9 is None:
                st_krw_ok = False
            else:
                st_krw += float(k9)
            continue
        if v:
            by_coin.append({"sym": canon.get(p["sym"], p["sym"]),
                            "chain": (p.get("realizedChainByDay") or {}).get(day_iso) or p.get("chain"),
                            "usd": round(float(v), 2),
                            "krw": (p.get("realizedKrwByDay") or {}).get(day_iso)})
    by_coin.sort(key=lambda r: -abs(r["usd"]))
    by_lp = []
    for lp in (f.get("lps") or []) + (f.get("lpsPending") or []) + (f.get("lpsClosed") or []):
        v = (lp.get("realizedByDay") or {}).get(day_iso)
        if v:
            by_lp.append({"pool": lp.get("pool") or _lp_pair(lp), "dex": lp.get("dex"), "chain": lp.get("chain"), "id": lp.get("id"),
                          "closed": lp.get("closed"), "usd": round(float(v), 2),
                          "krw": (lp.get("realizedKrwByDay") or {}).get(day_iso)})
    by_lp.sort(key=lambda r: -abs(r["usd"]))
    lp_rows, lp_tot = _lp_rows(f, day_iso)
    counts = {}
    for o in norm:
        counts[o["k"] or "?"] = counts.get(o["k"] or "?", 0) + 1
    coin_sum = sum(float((p.get("realizedByDay") or {}).get(day_iso) or 0) for p in f.get("positions", []))
    lp_sum = sum(r["usd"] for r in by_lp)
    diff = realized_spot - coin_sum - lp_sum
    realized_total = round(realized_spot + realized_fut, 2)
    gas_exp = _gas_input(f, day_iso, realized_total, norm)
    fills = [x for x in fills_agg(norm) if x["sym"] not in minor]
    has_fills = any(o["side"] and not o.get("dca") and o["sym"] not in minor and not _is_stable(o["sym"]) for o in norm)
    data = {
        "date": day_iso,
        "past_day": past,
        "realized_total": realized_total,
        "realized_spot": round(realized_spot, 2),
        "realized_futures": round(realized_fut, 2),
        "recon": {"ok": abs(diff) <= max(1.0, 0.005 * abs(realized_spot)), "diff": round(diff, 2)},
        "realized_by_coin": by_coin,
        "coins": coins,
        "fills_agg": fills,
        "event_counts": counts,
        "events": _compact(norm, minor),
    }
    rk = _krw_total(f, day_iso, realized_spot, realized_fut)
    if rk is not None:
        data["realized_total_krw"] = rk
    if gas_exp:
        data["gas_expense"] = gas_exp
    if abs(st_usd) >= 0.005:
        data["stable_fx"] = {"usd": _r(st_usd)}
        if st_krw_ok:
            data["stable_fx"]["krw"] = int(round(st_krw))
    if any((c.get("sell") or {}).get("first2m_pct") is not None for c in coins):
        sr = _split_ref(day_ev, day_iso)
        if sr:
            data["split_sell_ref"] = sr
    if not has_fills:
        data["no_fills"] = True
    if dca:
        data["small_dca"] = dca
        data["_dca_nb"] = sum(1 for o in norm if o.get("dca") and o["side"] == "buy")
    if by_lp:
        data["realized_by_lp"] = by_lp
    if lp_rows:
        data["lp"] = {"rows": lp_rows, "total": lp_tot}
    if any(o["side"] == "sell" and not o.get("dca") and o["v"] in KRW_MARKETS for o in norm):
        fx = _fx(f, day_iso)
        if fx:
            data["fx"] = fx
        kp = _krw_px(norm, minor)
        if kp:
            data["krw_px"] = kp
    hs = _hidden_summary(hid)
    if hs:
        data["hidden_summary"] = hs
    rs = _risk_sends(f, day_iso)
    if rs:
        data["risk_sends"] = rs
    pl = _plans_for(f, {c["sym"] for c in coins})
    if pl:
        data["plans"] = pl
    tn = _salelink.review_notes(raw)
    if tn:
        data["transfer_notes"] = tn
    dm = _day_memos_for(day_iso)
    if dm:
        data["day_memos"] = dm
    data["known_patterns"] = known_patterns(cfg)
    if reviews is not None:
        pn = prior_next(reviews, day_iso)
        if pn:
            data["prior_next"] = pn
        po = prior_obs(reviews, day_iso)
        if po:
            data["prior_obs"] = po
    it = _impact_top3(data)
    if it:
        data["impact_top3"] = it
    series_first = _series_first_iso(f.get("dailySeries") or [], today_iso)
    series_f = f if not series_first or day_iso >= series_first else dict(f, dailySeries=[])
    snap = next((d for d in (series_f.get("dailySeries") or []) if d.get("date") == mm), None)
    tot9 = (snap or {}).get("val") if past else (f.get("dailySeries") or [{}])[-1].get("val")
    if tot9 is not None:
        data["total_usd"] = _r(tot9)
    am = _asset_moves(series_f, day_iso)
    if am:
        data["asset_moves"] = am
    amk = _asset_moves_krw(series_f, day_iso) if past else {}
    if amk:
        data["_am_krw"] = amk
    data["_pre"] = not (past and _day_closed(f, day_iso, today_iso))
    if not past:
        data["pending_review"] = sum(1 for p in f.get("pendings", []) if not (isinstance(p, dict) and p.get("hide")))
        data["open_positions"] = [
            {"sym": p["sym"], "held": _r(p["held"]), "avg": _r(p["avg"]), "unreal": _r(p["unreal"]), "status": p["status"]}
            for p in f.get("positions", []) if p.get("held", 0) > 0 and not p.get("dust")]
    data["grade"] = grade(data)
    if data["grade"] == "양호":
        lc = loss_coins(data)
        if lc:
            data["loss_coins"] = lc
    data["_n"] = len(raw)
    data["_hid"] = len(hid)
    return data


_HASH_SKIP = ("prior_next", "prior_obs", "total_usd", "open_positions", "pending_review", "past_day",
              "asset_moves",
              "krw_px",
              "transfer_notes",
              "day_memos")


def _input_hash(data) -> str:
    core = _hash_core_dca({k: v for k, v in data.items() if not k.startswith("_") and k not in _HASH_SKIP})
    lp = core.get("lp")
    if isinstance(lp, dict):
        rows = [{k: v for k, v in r.items() if r.get("closed") or k not in ("mins", "fees", "per_hour")} for r in lp.get("rows") or []]
        core["lp"] = {"rows": sorted(rows, key=lambda r: str(r.get("id"))),
                      "total": {k: v for k, v in (lp.get("total") or {}).items() if k != "fees"}}
    return hashlib.sha1(json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


_MONEY_AMT = re.compile(r"[-−]?\$-?[\d,]+(?:\.\d+)?|[-−]?[\d,]+(?:\.\d+)?\s?원")


_QUANT_AMOUNT_KEYS = frozenset({"realized", "prior_realized", "qty", "q", "vwap", "vwap_1m", "px", "px_first", "px_last", "fees",
                                "deposited", "per_hour", "lp_per_hour", "lp_fees", "unreal", "held", "avg", "avg_cost", "buy_avg_px",
                                "buy_qty", "unknown_qty", "vwap_krw", "px_first_krw", "px_last_krw"})


def _quant_amount_key(k) -> bool:
    k = str(k or "").lower()
    return k in _QUANT_AMOUNT_KEYS or k.endswith("usd")


def _quant(v, key=""):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float) or (isinstance(v, int) and _quant_amount_key(key)):
        return "#"
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return _MONEY_AMT.sub("#", v)
    if isinstance(v, dict):
        return {k: _quant(x, "usd" if key == "by_sym" else k) for k, x in v.items() if "krw" not in str(k).lower()}
    if isinstance(v, (list, tuple)):
        return [_quant(x, key) for x in v]
    return v


def _qhash(core) -> str:
    return hashlib.sha1(json.dumps(_quant(core), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def _input_hash_q(data) -> str:
    core = _hash_core_dca({k: v for k, v in data.items() if not k.startswith("_") and k not in _HASH_SKIP and k != "hidden_summary"})
    lp = core.get("lp")
    if isinstance(lp, dict):
        rows = [{k: v for k, v in r.items() if r.get("closed") or k not in ("mins", "fees", "per_hour")} for r in lp.get("rows") or []]
        core["lp"] = {"rows": sorted(rows, key=lambda r: str(r.get("id"))),
                      "total": {k: v for k, v in (lp.get("total") or {}).items() if k != "fees"}}
    return _qhash(core)


def _ih_changed(old, fp) -> bool:
    if old.get("ihq") and fp.get("ihq"):
        return old["ihq"] != fp["ihq"]
    return bool("ih" in old and "ih" in fp and old.get("ih") != fp.get("ih"))


def _fp(data) -> dict:
    fp = {"rs": data["realized_spot"], "rf": data["realized_futures"], "n": int(data.get("_n", len(data.get("events") or []))),
          "hid": int(data.get("_hid") or 0), "pv": PROMPT_VERSION, "ih": _input_hash(data), "ihq": _input_hash_q(data),
          "len": rp.len_key("daily", data.get("_len"))}
    if data.get("realized_total_krw") is not None:
        fp["rk"] = data["realized_total_krw"]
    return fp


def _stale_data(rv, fp) -> bool:
    old = (rv or {}).get("fp")
    if not isinstance(old, dict):
        return False
    for k in ("rs", "rf"):
        a, b = float(old.get(k) or 0), float(fp.get(k) or 0)
        if abs(a - b) > max(1.0, 0.01 * max(abs(a), abs(b))):
            return True
    if old.get("n") != fp.get("n"):
        return True
    if old.get("rk") is not None and fp.get("rk") is not None:
        a, b = float(old["rk"]), float(fp["rk"])
        if abs(a - b) > max(1500.0, 0.005 * max(abs(a), abs(b))):
            return True
    return False


def _stale(rv, fp) -> bool:
    old = (rv or {}).get("fp")
    if not isinstance(old, dict):
        return True
    if _stale_data(rv, fp):
        return True
    if old.get("pv") != fp.get("pv"):
        return True
    if _ih_changed(old, fp):
        return True
    return False


def payload(data) -> str:
    return json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, ensure_ascii=False, separators=(",", ":"))


_SENT_END = re.compile(r"(?:[\.\!\?。…]|다\.|요\.)(?=\s|$)")


def clip_sentence(s: str, hard: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= hard:
        return s
    cut = None
    for m in _SENT_END.finditer(s):
        if m.end() > hard:
            break
        cut = m.end()
    if cut and cut >= hard // 3:
        return s[:cut].strip()
    return s


def _sentences(s: str) -> list:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if not s:
        return []
    out, i = [], 0
    for m in _SENT_END.finditer(s):
        out.append(s[i:m.end()].strip())
        i = m.end()
    if s[i:].strip():
        out.append(s[i:].strip())
    return [x for x in out if x]


_FIELD_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in rp.GLOSSARY if "_" in k), key=len, reverse=True)) + r")\b")


def screen_terms(s: str) -> str:
    return _FIELD_RX.sub(lambda m: rp.GLOSSARY.get(m.group(1), m.group(1)), str(s or ""))


def _parse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        rv = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return rv if isinstance(rv, dict) else None


_USD_RX = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_PCT_RX = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?%")
_KRW_WON = re.compile(r"₩\s?(\d[\d,]*(?:\.\d+)?)\s?(억|만)?")
_KRW_CMP = re.compile(r"(?<![\d,.:])((?:\d[\d,]*(?:\.\d+)?\s?(?:억|천만|만|천)\s?)+(?:\d[\d,]*(?:\.\d+)?)?)\s?원(?!가(?!량)|화)")
_KRW_PART = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(억|천만|만|천)?")
_KRW_UNIT = {"억": 1e8, "천만": 1e7, "만": 1e4, "천": 1e3, "": 1.0}
_KRW_MAN = re.compile(r"(?<![\d,.:])(\d[\d,]*(?:\.\d+)?)\s?(만)?\s?원(?!가(?!량)|화)")
_GAS_RX = re.compile(r"가스")
_KIMP_RX = re.compile(r"김프|김치 ?프리미엄|역프|역김프")
_REENTRY_RX = re.compile(r"재진입")
_FILL_NONE_RX = re.compile(r"(LP|선물|메모|계획|위험 전송|숨김)(?:\s*(?:거래|체결|정산|포지션|기록))?"
                          r"\s*(?:은|는|이|가|도)?\s*(?:따로\s*)?(없었다|없다|없음|없어|없고|없이|않았다)")
_BOOK_RX = re.compile(r"원가(?:를|가)?\s?(?:연결|확인|채우|메우|입력|확정)|장부|기록(?:을)?\s?(?:정리|보완|확인)|분류(?:를|해|하)|원가미상")


def _nums_of(o, acc):
    if isinstance(o, bool) or o is None:
        return
    if isinstance(o, (int, float)):
        acc.append(abs(float(o)))
    elif isinstance(o, dict):
        for v in o.values():
            _nums_of(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _nums_of(v, acc)
    elif isinstance(o, str):
        for m in re.finditer(r"\d[\d,]*\.?\d*", o):
            try:
                acc.append(abs(float(m.group(0).replace(",", "").rstrip("."))))
            except ValueError:
                pass


def _krw_vals(o, acc, key=""):
    if isinstance(o, dict):
        for k, v in o.items():
            _krw_vals(v, acc, str(k))
    elif isinstance(o, (list, tuple)):
        for v in o:
            _krw_vals(v, acc, key)
    elif isinstance(o, (int, float)) and not isinstance(o, bool) and (key == "krw" or key.endswith("_krw")):
        acc.append(abs(float(o)))


def _tol(tok, v):
    dec = len(tok.split(".", 1)[1]) if "." in tok else 0
    return max(0.5 * 10 ** (-dec), 0.005 * v, 0.011)


def _match(v, pool, tol):
    return any(abs(x - v) <= tol for x in pool)


def _krw_amounts(s):
    out, rest = [], s
    for m in _KRW_CMP.finditer(s):
        parts, tol = [], 0.5
        for pm in _KRW_PART.finditer(m.group(1)):
            u = _KRW_UNIT[pm.group(2) or ""]
            tok = pm.group(1)
            v = float(tok.replace(",", ""))
            while parts and parts[-1][1] < u:
                v += parts.pop()[0]
            parts.append((v * u, u))
            tol = 0.5 * u * 10 ** (-(len(tok.split(".", 1)[1]) if "." in tok else 0))
        out.append((m.group(0), sum(v for v, _ in parts), tol))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in list(_KRW_WON.finditer(rest)):
        u = {"억": 1e8, "만": 1e4}.get(m.group(2) or "", 1)
        tok = m.group(1)
        out.append((m.group(0), float(tok.replace(",", "")) * u, 0.5 * u * 10 ** (-(len(tok.split(".", 1)[1]) if "." in tok else 0))))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in _KRW_MAN.finditer(rest):
        u = 1e4 if m.group(2) else 1
        tok = m.group(1)
        out.append((m.group(0), float(tok.replace(",", "")) * u, 0.5 * u * 10 ** (-(len(tok.split(".", 1)[1]) if "." in tok else 0))))
    return out


_TIME_RX = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
_DATE_KO_RX = re.compile(r"(\d{1,2})월\s?(\d{1,2})일")
_UNIT_NUM_RX = re.compile(r"(?<![\d,.$₩:])(\d[\d,]*(?:\.\d+)?)\s?(개|분|일|건|시간|곳|배)(?!월|부|할|째)")
_DEC_RX = re.compile(r"(?<![\d,.$₩:])(\d[\d,]*\.\d+)(?![\d.]|\s?(?:%|개|분|일|건|시간|곳|배|만|억|천|원|달러))")
_META_GRADE_RX = re.compile(r"(?:등급|평가)(?:은|는|이|가|도)?\s*['‘\"“]?(?:양호|주의|경고|관망)")
_JIM_RX = re.compile(r"(?:니다|세요|해요|어요|아요|네요|예요|이에요|군요)[.!]?$")
_PRESENT_RX = re.compile(r"(?:는다|린다|인다|긴다|진다|친다|한다|된다|난다|낸다|간다|온다|판다|산다|탄다|준다|운다|(?<!수 )있다|(?<!수 )없다)\.?$")
_PRESENT_OK_RX = re.compile(r"(?:야 한다|수 있다|수 없다|필요하다|좋다)\.?$")


def _times_of(o, acc):
    if isinstance(o, dict):
        for v in o.values():
            _times_of(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _times_of(v, acc)
    elif isinstance(o, str):
        for m in _TIME_RX.finditer(o):
            acc.add((int(m.group(1)), int(m.group(2))))


def _dates_of(o, acc):
    if isinstance(o, dict):
        for v in o.values():
            _dates_of(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _dates_of(v, acc)
    elif isinstance(o, str):
        for m in re.finditer(r"(?:\d{4}-)?(\d{2})-(\d{2})", o):
            acc.add((int(m.group(1)), int(m.group(2))))


_PX_KEYS = frozenset({"vwap", "vwap_1m", "px_first", "px_last", "avg_cost", "buy_avg_px", "px"})


def _px_vals(o, acc, key=""):
    if isinstance(o, dict):
        for k, v in o.items():
            _px_vals(v, acc, str(k))
    elif isinstance(o, (list, tuple)):
        for v in o:
            _px_vals(v, acc, key)
    elif isinstance(o, (int, float)) and not isinstance(o, bool) and key in _PX_KEYS and o:
        acc.append(abs(float(o)))


def _ctx(data):
    acc, krw, tms, dts, pxs = [], [], set(), set(), []
    data = {k: v for k, v in data.items() if k != "day_memos"}
    core = {k: v for k, v in data.items() if not k.startswith("_")}
    _nums_of(core, acc)
    _krw_vals(data, krw)
    _px_vals(core, pxs)
    _times_of(core, tms)
    _dates_of(core, dts)
    re9 = any(c.get("reentry") for c in data.get("coins") or []) or any(c.get("reentry") for c in data.get("cycles") or [])
    return {"nums": acc, "krw": krw, "gas": bool(data.get("gas_expense")), "kimp": bool(data.get("fx")),
            "reentry": re9, "times": tms, "dates": dts, "px": pxs}


def _sent_problems(sent, ctx) -> list:
    out = []
    for m in _USD_RX.finditer(sent):
        tok = m.group(1)
        v = float(tok.replace(",", ""))
        if not _match(v, ctx["nums"], _tol(tok, v)):
            out.append(f"입력에 없는 금액 ${tok}")
    for m in _PCT_RX.finditer(sent):
        tok = m.group(1)
        v = float(tok.replace(",", ""))
        if not _match(v, ctx["nums"], _tol(tok, v)):
            out.append(f"입력에 없는 비율 {tok}%")
    for tok, v, t in _krw_amounts(sent):
        if not _match(v, ctx["krw"], max(t, 0.005 * v)):
            out.append(f"입력 원화 값이 아닌 원화 {tok.strip()}(원화는 realized_total_krw·krw 만 인용)")
    if not ctx["gas"] and _GAS_RX.search(sent):
        out.append("가스 입력(gas_expense)이 없는데 가스 언급")
    if not ctx["kimp"] and _KIMP_RX.search(sent):
        out.append("김프 입력(fx)이 없는데 김프 언급")
    if not ctx["reentry"] and _REENTRY_RX.search(sent):
        out.append("재진입 입력(reentry)이 없는데 재진입 언급")
    if _FILL_NONE_RX.search(sent):
        out.append("없는 것 채우기 문장")
    if "times" in ctx:
        for m in _TIME_RX.finditer(sent):
            if (int(m.group(1)), int(m.group(2))) not in ctx["times"]:
                out.append(f"입력에 없는 시각 {m.group(0)}")
        rest = sent
        for m in _DATE_KO_RX.finditer(sent):
            if (int(m.group(1)), int(m.group(2))) not in ctx["dates"]:
                out.append(f"입력에 없는 날짜 {m.group(0)}")
            rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
        rest = _TIME_RX.sub(lambda m9: " " * len(m9.group(0)), rest)
        rest = _USD_RX.sub(lambda m9: " " * len(m9.group(0)), rest)
        for m in _UNIT_NUM_RX.finditer(rest):
            tok = m.group(1)
            v = float(tok.replace(",", ""))
            if v <= 2 and "." not in tok:
                continue
            if not _match(v, ctx["nums"], _tol(tok, v)):
                out.append(f"입력에 없는 수 {m.group(0).strip()}")
        for m in _DEC_RX.finditer(rest):
            tok = m.group(1)
            v = float(tok.replace(",", ""))
            if not _match(v, ctx["nums"], _tol(tok, v)):
                out.append(f"입력에 없는 값 {tok}")
            elif ctx.get("px") and _match(v, ctx["px"], _tol(tok, v)):
                out.append(f"통화 기호 없는 가격 {tok}($ 또는 ₩ 를 붙인다)")
    if _META_GRADE_RX.search(sent):
        out.append("등급 되풀이 문장(등급은 칩으로 보인다)")
    return out


def _fields(rv):
    yield "note", rv.get("note")
    yield "sum", rv.get("sum")
    for i, o in enumerate(rv.get("obs") or []):
        yield f"obs{i + 1}", o
    for i, o in enumerate(rv.get("patterns") or []):
        yield f"pattern{i + 1}", o
    if "rule" in rv:
        yield "rule", rv.get("rule")
    yield "next", rv.get("next")
    yield "dq", rv.get("dq")


def review_len_pref(kind: str) -> str:
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f9:
            p = json.load(f9)
        v = ((p if isinstance(p, dict) else {}).get("review_len") or {}).get(kind)
    except (OSError, ValueError, AttributeError):
        v = None
    return rp.len_key(kind, v if isinstance(v, str) else None)


def review_paused() -> bool:
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f9:
            p = json.load(f9)
        v = (p if isinstance(p, dict) else {}).get("review_pause")
        return isinstance(v, dict) and v.get("on") is True
    except (OSError, ValueError, AttributeError):
        return False


_PAUSE_LOGGED = {"on": False}


def _paused_skip(what: str) -> bool:
    p = review_paused()
    if p and not _PAUSE_LOGGED["on"]:
        log.info("AI 리뷰 자동 생성 멈춤(설정 › AI 리뷰) — %s 등 모델 호출 작업을 건너뜀(풀면 다음 회차부터 이어서)", what)
    elif not p and _PAUSE_LOGGED["on"]:
        log.info("AI 리뷰 자동 생성 멈춤 풀림 — 이어서")
    _PAUSE_LOGGED["on"] = p
    return p


def review_fill_pref() -> dict:
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f9:
            p = json.load(f9)
        v = (p if isinstance(p, dict) else {}).get("review_fill")
    except (OSError, ValueError, AttributeError):
        v = None
    return rprog.fill_eff(dict(rprog.fill_eff(v), **_FILL_OVERRIDE))


def _len_off(rv, cur: str, kind: str) -> bool:
    if not isinstance(rv, dict) or not isinstance(rv.get("fp"), dict) or rv.get("model") == "template":
        return False
    return (rv["fp"].get("len") or rp.LEGACY_LEN.get(kind, "normal")) != cur


def _is_weekly(rv=None, data=None) -> bool:
    if data is not None:
        return bool(data.get("week"))
    return isinstance(rv, dict) and ("patterns" in rv or "rule" in rv)


def _pr(rv=None, data=None) -> dict:
    return rp.len_preset("weekly" if _is_weekly(rv, data) else "daily", (data or {}).get("_len"))


def _len_max(rv=None, data=None) -> int:
    return _pr(rv, data)["max"]


def _rv_len(rv) -> int:
    n = 0
    for name, t in _fields(rv or {}):
        if name == "dq":
            continue
        t = re.sub(r"\s+", " ", str(t or "")).strip()
        if name == "next" and t in ("없음.", "없음", "—"):
            continue
        n += len(t)
    return n


def _repeats_total(sent, data) -> bool:
    rt = abs(float(data.get("realized_total") or 0))
    rk = data.get("realized_total_krw")
    sm = screen_terms(sent)
    return bool((rt >= 1 and any(abs(float(m.group(1).replace(",", "")) - rt) <= _tol(m.group(1), rt) for m in _USD_RX.finditer(sm)))
                or (rk is not None and abs(rk) >= 1 and any(abs(v - abs(rk)) <= max(t9, 0.005 * abs(rk)) for _, v, t9 in _krw_amounts(sm))))


def _trim_sum_total(rv, data):
    if not isinstance(rv, dict) or not isinstance(rv.get("sum"), str):
        return rv
    ss = _sentences(rv["sum"])
    keep = [x for x in ss if not _repeats_total(x, data)]
    if keep and len(keep) < len(ss):
        rv = dict(rv, sum=" ".join(keep))
    return rv


def _style_probs(rv, data) -> list:
    out = []
    past = bool(data.get("past_day")) or bool(data.get("week"))
    for name, t in _fields(rv or {}):
        for sent in _sentences(t):
            if _JIM_RX.search(sent):
                out.append(f"{name}: 문체 혼재('~다.' 체로)")
                break
            if past and name not in ("next", "rule", "dq") and _PRESENT_RX.search(sent) and not _PRESENT_OK_RX.search(sent):
                out.append(f"{name}: 지난 날인데 현재형('~했다·~였다' 과거형으로)")
                break
    n = _rv_len(rv)
    pr = _pr(rv, data)
    if n > pr["max"]:
        out.append(f"너무 김 {n}자(합계 {pr['target']}·최대 {pr['max']:,}자)")
    if _repeats_total(rv.get("sum") or "", data):
        out.append("sum 이 제목의 실현손익 합계를 되풀이(원인 한 문장으로)")
    return out


def validate(rv: dict, data: dict) -> list:
    ctx = _ctx(data)
    probs = []
    for name, txt in _fields(rv):
        for sent in _sentences(screen_terms(txt)):
            for p in _sent_problems(sent, ctx):
                probs.append(f"{name}: {p}")
    note = re.sub(r"\s+", " ", str(rv.get("note") or "")).strip()
    if len(note) > NOTE_MAX:
        probs.append(f"note {len(note)}자(60자 이내 한 문장)")
    if any("…" in str(t or "") for _, t in _fields(rv)):
        probs.append("말줄임(…) 금지 — 완결 문장")
    if _BOOK_RX.search(str(rv.get("next") or "")):
        probs.append("next 가 장부 정리(원가 연결·기록 정리는 dq 로, next 는 impact_top3[0] 겨냥)")
    if data.get("grade") and rv.get("s") != data["grade"]:
        probs.append(f"평가 s 는 입력 grade({data['grade']}) 그대로")
    fk = ((data.get("gas_expense") or {}).get("by_kind") or {}).get(GAS_KIND_KO["FAILED"]) or {}
    if float(fk.get("usd") or 0) >= FAILED_GAS_MUST and not any("실패" in str(o or "") for o in rv.get("obs") or []):
        probs.append(f"실패 tx 가스 ${float(fk['usd']):,.2f} 를 다루는 [실행] 관찰 누락(top3 시각·체인·near_buy)")
    om = rp.len_preset("daily", data.get("_len"))["obs"]
    if len(rv.get("obs") or []) > om:
        probs.append(f"관찰 {len(rv.get('obs') or [])}개(최대 {om}개)")
    probs += _style_probs(rv, data)
    return probs


def _scrub(rv: dict, data: dict, label="") -> dict:
    ctx = _ctx(data)
    out = dict(rv)
    dropped = []

    def clean(txt, name):
        keep = []
        for sent in _sentences(screen_terms(txt)):
            p = _sent_problems(sent, ctx)
            if p:
                dropped.append(f"{name}: {sent[:60]} ({'; '.join(p)[:120]})")
            else:
                keep.append(sent)
        return " ".join(keep)

    out["sum"] = clean(rv.get("sum") or "", "sum")
    obs = []
    for i, o in enumerate(rv.get("obs") or []):
        c = clean(o, f"obs{i + 1}")
        if re.sub(r"^\[[^\]]*\]\s*", "", c).strip():
            obs.append(c)
    out["obs"] = obs
    if "patterns" in rv or "rule" in rv:
        out["patterns"] = [c for c in (clean(o, f"pattern{i + 1}") for i, o in enumerate(rv.get("patterns") or [])) if c.strip()]
        out["rule"] = clean(rv.get("rule") or "", "rule")
    nx = clean(rv.get("next") or "", "next")
    dq = clean(rv.get("dq") or "", "dq")
    if nx and _BOOK_RX.search(nx):
        dropped.append(f"next→dq: {nx[:60]}")
        dq = dq or nx
        nx = ""
    out["next"] = nx or "없음."
    out["dq"] = dq
    out["note"] = clean(rv.get("note") or "", "note")
    if dropped:
        log.warning("리뷰 검증 위반 문장 제거(%s) %d건: %s", label or data.get("date"), len(dropped), " | ".join(dropped)[:900])
    return out


def _first_sentence(s):
    ss = _sentences(s)
    return ss[0] if ss else ""


_LINK_FIELDS = ("note", "sum", "next", "dq", "rule", "obs", "patterns")


def _delink(rv: dict) -> dict:
    out = dict(rv or {})
    for k in _LINK_FIELDS:
        v = out.get(k)
        if isinstance(v, str):
            out[k] = common.strip_links(v)
        elif isinstance(v, list):
            out[k] = [y for y in (common.strip_links(x) if isinstance(x, str) else x for x in v) if not (isinstance(y, str) and not y.strip())]
    return out


def normalize(rv: dict, data: dict) -> dict:
    s = rv.get("s") if rv.get("s") in ("양호", "주의", "경고", "관망") else "관망"
    if data.get("grade") in ("양호", "주의", "경고", "관망"):
        s = data["grade"]
    elif data.get("no_fills") and abs(data.get("realized_total") or 0) < REALIZED_MIN_USD and not data.get("risk_sends"):
        s = "관망"
    rv = _scrub(_delink(rv), data)
    pr = rp.len_preset("daily", data.get("_len"))
    obs = [clip_sentence(screen_terms(x), OBS_HARD) for x in (rv.get("obs") or []) if str(x or "").strip()][:pr["obs"]]
    sm = screen_terms(rv.get("sum") or "")
    note = clip_sentence(screen_terms(rv.get("note")), NOTE_MAX)
    if not note or len(note) > NOTE_MAX or note.endswith("…"):
        note = _first_sentence(sm) or note
    out = {"s": s, "note": note, "sum": sm, "obs": obs,
           "next": clip_sentence(screen_terms(rv.get("next") or "없음."), OBS_HARD if pr["next"] == "1문장" else WEEKLY_FIELD_HARD) or "없음."}
    dq = clip_sentence(screen_terms(rv.get("dq") or ""), OBS_HARD)
    if dq:
        out["dq"] = dq
    if data.get("loss_coins"):
        out["lossCoins"] = data["loss_coins"]
    out = _fit_len(out, pr["max"])
    out["fp"] = _fp(data)
    out["model"] = REVIEW_MODEL
    out["at"] = int(time.time())
    return out


CLI_ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
                "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy",
                "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "XDG_CONFIG_HOME")
CLI_ENV_AUTH = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR",
                "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                "CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS")


def _cli_env(src=None) -> dict:
    src = os.environ if src is None else src
    return {k: v for k, v in src.items()
            if k in CLI_ENV_KEEP or k in CLI_ENV_AUTH or k == "LC_ALL" or k.startswith("LC_")}


_CLI_FLAGS = {}


def _cli_probe(b) -> list:
    if b not in _CLI_FLAGS:
        try:
            h = subprocess.run([b, "--help"], capture_output=True, text=True, timeout=20, env=_cli_env(), stdin=subprocess.DEVNULL).stdout or ""
        except Exception:
            h = ""
        _CLI_FLAGS[b] = ["--no-session-persistence"] if "--no-session-persistence" in h else []
    return _CLI_FLAGS[b]


def _cli_extra(b) -> list:
    return list(_CLI_FLAGS.get(b) or [])


def _cli_cwd():
    import tempfile
    base = os.path.join(tempfile.gettempdir(), f"tj-review-cli-{os.getuid()}")
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        st = os.lstat(base)
        import stat as _st9
        if _st9.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not os.listdir(base):
            if st.st_mode & 0o077:
                os.chmod(base, 0o700)
            return base, False
    except OSError:
        pass
    return tempfile.mkdtemp(prefix="tj-review-cli-"), True


def _run_cli(b, prompt, data, label, body=None):
    with _CLI_PACE:
        wait = _CLI_LAST[0] + CLI_START_GAP_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _CLI_LAST[0] = time.time()
    _GS.calls = getattr(_GS, "calls", 0) + 1
    if body is None:
        import secrets
        nonce = secrets.token_hex(8)
        prompt = rp.with_data_fence(prompt, nonce)
        body = f"<<<DATA {nonce}>>>\n" + payload(data) + f"\n<<<END {nonce}>>>"
    cwd9, rm9 = _cli_cwd()
    try:
        out = subprocess.run(
            [b, "-p", "--strict-mcp-config", "--model", REVIEW_MODEL, "--tools", ""] + _cli_extra(b),
            input=prompt + body,
            capture_output=True, text=True, timeout=600, cwd=cwd9, env=dict(_cli_env(), CLAUDE_CODE_SAFE_MODE="1"))
    finally:
        if rm9:
            import shutil
            shutil.rmtree(cwd9, ignore_errors=True)
    if out.returncode != 0:
        log.warning("리뷰 CLI 실패(%s, rc=%s): %s", label, out.returncode, (out.stderr or "").strip()[:200])
        return None
    rv = _parse((out.stdout or "").strip())
    if rv is None:
        log.warning("리뷰 응답 파싱 실패(%s): %s", label, (out.stdout or "").strip()[:200])
    return rv


def _idle_day(data) -> bool:
    return bool(data.get("no_fills") and abs(data.get("realized_total") or 0) < GRADE_IDLE_USD and not data.get("risk_sends")
                and not data.get("lp") and not data.get("gas_expense"))


def _usd_txt(v):
    return ("−" if v < 0 else "+" if v > 0 else "") + f"${abs(v):,.2f}"


def _krw_txt(v):
    return ("-" if v < 0 else "+" if v > 0 else "") + f"₩{abs(int(v)):,}"


def _krw_c(v) -> str:
    w = abs(float(v))
    sg = "" if w < 0.5 else ("+" if v > 0 else "−")
    if w >= 1e8:
        t = f"{w / 1e8:,.2f}억"
    elif w >= 1e4:
        t = f"{int(round(w / 1e4)):,}만"
    else:
        t = f"{int(round(w)):,}"
    return f"{sg}₩{t}"


def _template_krw(data) -> str:
    k = data.get("_am_krw") or {}
    if not k or abs(int(k.get("change") or 0)) < max(1.0, float(k.get("u") or 0)):
        return ""
    sig = lambda v: abs(v) >= max(float(k.get("u") or 0), 0.01 * abs(float(k["change"])))
    pc = lambda p: ("+" if p > 0 else "−" if p < 0 else "") + f"{abs(p):.1f}%"
    mv = [f"{t['sym']} {pc(float(t['pct']))} {_krw_c(t['krw'])}" if t.get("pct") is not None else f"{t['sym']} {_krw_c(t['krw'])}"
          for t in k.get("movers") or [] if t.get("krw")]
    chg, mk = int(k["change"]), int(k.get("market") or 0)
    s9 = f"총자산 변동 {_krw_c(chg)}은 시세 {_krw_c(mk)}" + (f"({', '.join(mv)})" if mv else "")
    shown = mk
    for k9, l9 in (("realized", "실현 매매"), ("lp_fee", "LP 수수료"), ("flow", "입출금"), ("trade", "매매"), ("fx", "환율"),
                   ("unknown", "원가 모름")):
        if sig(float(k.get(k9) or 0)):
            s9 += f", {l9} {_krw_c(int(k[k9]))}"
            shown += int(k[k9])
    rest = chg - shown
    if abs(rest) >= max(float(k.get("u") or 0), 5000.0 if abs(chg) >= 1e4 else 0.5):
        s9 += f", 나머지 {_krw_c(rest)}"
    am = data.get("asset_moves") or {}
    return s9 + (" 때문이다(근사 평가 포함)." if am.get("approx") else " 때문이다.")


TEMPLATE_V = 5
TEMPLATE_REFRESH_DAYS = 7
TEMPLATE_OLD_MAX = 30


def _template_rec(data) -> dict:
    t = _template(data)
    rec = normalize(dict(t, note="", sum=""), data)
    if t.get("sum"):
        rec["sum"] = screen_terms(t["sum"])
    rec["note"] = screen_terms(t["note"]) if t.get("note") else ""
    rec["model"] = "template"
    rec["tv"] = TEMPLATE_V
    sk = _template_krw(data)
    if sk:
        rec["sumKrw"] = screen_terms(sk)
    if data.get("_pre"):
        rec["pre"] = True
    return rec


def _template(data) -> dict:
    dca = data.get("small_dca") or {}
    nb = data.get("_dca_nb")
    n9 = nb if isinstance(nb, int) and nb > 0 else dca.get("n")
    note = (f"정기 소액 분산 매수 {n9}건 외 매매가 없던 날이다." if dca and n9 else "매매가 없던 날이다.")
    sm = ""
    am = data.get("asset_moves") or {}
    if am and abs(float(am.get("change_usd") or 0)) >= 1:
        pc = lambda p: ("+" if p > 0 else "−" if p < 0 else "") + f"{abs(p):.1f}%"
        mv = [f"{t['sym']} {pc(float(t['pct']))} {_usd_txt(float(t['usd']))}" if t.get("pct") is not None else f"{t['sym']} {_usd_txt(float(t['usd']))}"
              for t in (am.get("movers") or [])[:3] if abs(float(t.get("usd") or 0)) >= 0.005]
        chg, mk = float(am["change_usd"]), float(am.get("market_usd") or 0)
        s9 = f"총자산 변동 {_usd_txt(chg)}은 시세 {_usd_txt(mk)}" + (f"({', '.join(mv)})" if mv else "")
        shown = mk
        for k9, l9 in (("realized_usd", "실현 매매"), ("lp_fee_usd", "LP 수수료"), ("flow_usd", "입출금"), ("trade_usd", "매매"),
                       ("fx_usd", "환율"), ("unknown_usd", "원가 모름")):
            if abs(float(am.get(k9) or 0)) >= 1:
                s9 += f", {l9} {_usd_txt(float(am[k9]))}"
                shown += float(am[k9])
        if abs(chg - shown) >= 1:
            s9 += f", 나머지 {_usd_txt(chg - shown)}"
        sm = s9 + (" 때문이다(근사 평가 포함)." if am.get("approx") else " 때문이다.")
    return {"s": "관망", "note": note, "sum": sm, "obs": [], "next": "없음.", "dq": ""}


_ELL_END_OK = re.compile(r"(?:다|요|음|함|됨|임|없음|있음|필요|주의|확인)$")


def _fix_ellipsis(txt):
    if not txt or "…" not in str(txt):
        return txt
    out = []
    for sent in _sentences(txt):
        if "…" not in sent:
            out.append(sent)
            continue
        base = sent.rstrip("…").rstrip()
        if sent.endswith("…") and "…" not in base:
            if base and _ELL_END_OK.search(base):
                out.append(base + ".")
            continue
        out.append(sent)
    res = " ".join(out).strip()
    return res if re.sub(r"^\[[^\]]*\]\s*", "", res).strip() else txt


_LAST_DATE_RX = re.compile(r"(?:지난|이번|올해)\s+(?=\d{1,2}월\s?\d{1,2}일)")


def _fit_len(out: dict, lim=None) -> dict:
    lim = lim or _len_max(out)
    for k in ("obs", "patterns"):
        while isinstance(out.get(k), list) and len(out[k]) > 1 and _rv_len(out) > lim:
            out[k] = out[k][:-1]
    return out


def _postfix(rv: dict, data=None) -> dict:
    if not isinstance(rv, dict):
        return rv
    out = dict(rv)
    for k in ("note", "sum", "next", "dq", "rule"):
        if isinstance(out.get(k), str):
            out[k] = _fix_ellipsis(out[k])
    if isinstance(out.get("obs"), list):
        out["obs"] = [_fix_ellipsis(o) if isinstance(o, str) else o for o in out["obs"]][:rp.len_preset("daily", (data or {}).get("_len"))["obs"]]
    if isinstance(out.get("patterns"), list):
        out["patterns"] = [_fix_ellipsis(o) if isinstance(o, str) else o for o in out["patterns"]][:rp.len_preset("weekly", (data or {}).get("_len"))["pat_max"]]
    for k in ("note", "sum", "next", "dq", "rule"):
        if isinstance(out.get(k), str):
            out[k] = _LAST_DATE_RX.sub("", out[k])
    for k in ("obs", "patterns"):
        if isinstance(out.get(k), list):
            out[k] = [_LAST_DATE_RX.sub("", o) if isinstance(o, str) else o for o in out[k]]
    note = re.sub(r"\s+", " ", str(out.get("note") or "")).strip()
    if len(note) > NOTE_MAX:
        n2 = clip_sentence(note, NOTE_MAX)
        if len(n2) > NOTE_MAX or "…" in n2:
            fs = _first_sentence(screen_terms(out.get("sum") or ""))
            n2 = fs if fs and len(fs) <= NOTE_MAX and "…" not in fs else note
        out["note"] = n2
    return out


def _hard_probs(probs, rv) -> list:
    ell_else = any("…" in str(t or "") for n9, t in _fields(rv or {}) if n9 != "note")
    return [p9 for p9 in probs if not ((p9.startswith("note ") and "자(60자" in p9)
                                       or (p9.startswith("말줄임") and not ell_else)
                                       or p9.startswith("sum 이 제목의"))]


def _retry_prompt(probs, prompt=None) -> str:
    return (prompt or PROMPT).replace("\n데이터:\n", "\n직전 답의 문제 — 고쳐서 같은 JSON 형식으로 다시 답하라: " + "; ".join(probs)[:1200] + "\n데이터:\n")


def generate(b, data) -> bool:
    day = data["date"]
    data = dict(data, _len=data.get("_len") or review_len_pref("daily"))
    prompt = rp.daily_prompt(data["_len"])
    if data.get("day_memos"):
        prompt = rp.with_day_memo_rule(prompt, "daily")
    _GS.llm, _GS.regen = False, False
    if _idle_day(data):
        rec = _template_rec(data)
    else:
        _GS.llm = True
        rv = _run_cli(b, prompt, data, day)
        if rv is None:
            return False
        rv = _fit_len(_trim_sum_total(_postfix(rv, data), data), _len_max(None, data))
        probs = validate(rv, data)
        hard = _hard_probs(probs, rv)
        if hard:
            log.info("리뷰 검증 위반(%s) %d건 → 1회 재생성: %s", day, len(hard), " | ".join(hard)[:600])
            _GS.regen = True
            rv2 = _run_cli(b, _retry_prompt(hard, prompt), data, day + " 재생성")
            if rv2 is not None:
                rv2 = _fit_len(_trim_sum_total(_postfix(rv2, data), data), _len_max(None, data))
                probs2 = validate(rv2, data)
                if len(_hard_probs(probs2, rv2)) <= len(hard):
                    rv, probs = rv2, probs2
        note = re.sub(r"\s+", " ", str(rv.get("note") or "")).strip()
        if len(note) > NOTE_MAX or "…" in note:
            nv = _run_cli(b, rp.NOTE_PROMPT, data, day + " note", body=note)
            n2 = re.sub(r"\s+", " ", str((nv or {}).get("note") or "")).strip()
            if n2 and len(n2) <= NOTE_MAX and "…" not in n2:
                rv = dict(rv, note=n2)
        rec = normalize(rv, data)
    if not _store_put(OUT_PATH, day, rec, drop=day[5:10]):
        return False
    log.info("리뷰 생성 완료: %s [%s] 기록 %d건 · 입력 %d자%s", day, rec["s"], rec["fp"]["n"], len(payload(data)),
             " · 템플릿(체결 없음)" if rec.get("model") == "template" else "")
    return True


def _ev_from(day_iso):
    return (datetime.strptime(day_iso, "%Y-%m-%d") - timedelta(days=DCA_LOOKBACK_D)).strftime("%Y-%m-%d")


def _seg_label(seg) -> str:
    return f"{int(seg[1][5:7])}/{int(seg[1][8:10])}~{int(seg[2][5:7])}/{int(seg[2][8:10])}"


def _run_items(run, items, work, parallel=1, pace_s=None, stop_check=None):
    pace_s = CATCHUP_PACE_S if pace_s is None else pace_s
    lock = threading.Lock()
    it = iter(list(items))
    stop = {"why": None}

    def worker():
        rest = False
        while True:
            if rest and pace_s:
                time.sleep(pace_s)
            with lock:
                if stop["why"]:
                    return
                w9 = stop_check() if stop_check else None
                if not w9 and str(getattr(run, "mode", "")).startswith("daemon") and review_paused():
                    w9 = "자동 생성 멈춤(설정)"
                if w9:
                    stop["why"] = w9
                    return
                nxt = next(it, None)
            if nxt is None:
                return
            kind, key, label = nxt
            run.start(kind, key, label)
            _GS.calls, _GS.llm, _GS.regen = 0, False, False
            t0, err = time.time(), None
            try:
                res = work(kind, key)
            except Exception as e:
                log.warning("리뷰 생성 오류(%s %s): %s", kind, key, e)
                res, err = False, e
            secs = time.time() - t0
            if res is None:
                run.end(kind, key, True, skipped=True)
                rest = False
                continue
            run.end(kind, key, bool(res), llm=bool(getattr(_GS, "llm", False)), secs=secs, regen=bool(getattr(_GS, "regen", False)),
                    err=err if err is not None else (None if res else f"{key} 생성 실패(CLI)"))
            rest = True
            if not res:
                with lock:
                    stop["why"] = stop["why"] or "실패"
                return

    n = max(1, min(int(parallel or 1), len(items)))
    if n == 1:
        worker()
    else:
        ths = [threading.Thread(target=worker, name=f"tj-review-{i + 1}", daemon=True) for i in range(n)]
        for t9 in ths:
            t9.start()
        for t9 in ths:
            t9.join()
    if stop["why"]:
        run.drop_queue()
    return stop["why"]


def _new_run(mode, queue, fill):
    return rprog.Run(PROGRESS_PATH, mode, queue, fill["order"], fill["parallel"], CATCHUP_PACE_S)


def run_today(cfg):
    if _paused_skip("오늘 일간 리뷰"):
        return
    b = claude_bin()
    if not b:
        log.info("claude CLI 없음 — 자동요약 폴백 유지")
        return
    st = fetch_state(cfg)
    d = _today_iso(st)
    run = _new_run("daemon-today", {"daily": [d]}, {"order": "recent", "parallel": 1})
    why = None
    try:
        why = _run_items(run, [("daily", d, "")], lambda k9, d9: generate(b, gather(st, d9, fetch_day_events(cfg, _ev_from(d9), d9), cfg, _read_reviews())),
                         1, pace_s=0)
    finally:
        run.close(why)


EVAL_CHART_TRIES = 40
EVAL_GET_GAP_S = 2.0
EVAL_PACE_S = 8
EVAL_SLOTS = (1, 2, 3)
EVAL_PARALLEL_MAX = 3
_EVAL_GET_LOCK = threading.Lock()
_EVAL_GET_LAST = [0.0]


def receipt_items(cfg, d_from, d_to, get=None):
    g = get or (lambda p9: _get_json(cfg, p9, timeout=120))
    r = g(f"/api/receipt_list?from={d_from}&to={d_to}") or {}
    return [(str(x["date"]), str(x["sym"])) for x in (r.get("items") or []) if x.get("date") and x.get("sym")]


def _eval_chart(cfg, date, sym, side, get, sleep):
    import urllib.parse as up9
    path = (f"/api/receipt_chart?date={date}&sym={up9.quote(sym, safe='')}&iv=5m&after=1h&inp=1" + ("&side=buy" if side == "buy" else ""))
    for _ in range(EVAL_CHART_TRIES):
        with _EVAL_GET_LOCK:
            w9 = EVAL_GET_GAP_S - (time.time() - _EVAL_GET_LAST[0])
            if w9 > 0:
                sleep(w9)
            _EVAL_GET_LAST[0] = time.time()
        try:
            r = get(path)
        except Exception as e:
            log.warning("AI 평가 차트 조회 실패(%s %s %s): %s", date, sym, side, e)
            return None
        if isinstance(r, dict) and r.get("ok") and r.get("status") in ("preparing", "busy"):
            try:
                ra = float(r.get("retryAfter") or 3)
            except (TypeError, ValueError):
                ra = 3.0
            sleep(min(10.0, max(1.0, ra)))
            continue
        return r if isinstance(r, dict) else None
    return None


def eval_one(cfg, date, sym, side, get=None, sleep=time.sleep, runner=None, binfn=None, stores=None):
    import sellchart
    get = get or (lambda p9: _get_json(cfg, p9, timeout=120))
    r = _eval_chart(cfg, date, sym, side, get, sleep)
    if not r or not r.get("ok") or r.get("empty") or (side == "buy" and r.get("side") != "buy"):
        return "nochart"
    fp, inp = r.get("evalFp"), r.get("evalInput")
    if not fp or not isinstance(inp, dict):
        return "nochart"
    sym2 = str(r.get("sym") or sym)
    st = (stores or {}).get(side) or sellchart.EvalStore(kind=side)
    pv = rp.BUY_EVAL_VERSION if side == "buy" else rp.SELL_EVAL_VERSION
    old = st.find(date, sym2, fp)
    if old and old.get("pv") == pv:
        return "fresh"
    lab = f"{'매수' if side == 'buy' else '매도'}평가 {date}|{sym2}"
    run = runner or (lambda b9, p9, body9: _run_cli(b9, p9, None, lab, body=body9))
    rec, err = sellchart.run_eval(st, cfg, date, sym2, fp, inp, runner=run, binfn=binfn or claude_bin, slots=EVAL_SLOTS, model=REVIEW_MODEL)
    if rec:
        return "made"
    e9 = str(err or "")
    if "한도" in e9 or "꺼져 있어요" in e9:
        return "budget"
    if "진행 중" in e9:
        return "busy"
    log.warning("AI %s 평가 실패(%s %s): %s", side, date, sym2, e9)
    return "fail"


EVAL_SIDES = ("sell", "buy")


def eval_sides_on(cfg) -> list:
    import sellchart
    return [s9 for s9 in EVAL_SIDES if sellchart.daily_max(cfg, s9) > 0]


def receipt_evals(cfg, items, parallel=1, pace_s=None, get=None, sleep=time.sleep, runner=None, binfn=None, stores=None, stop_check=None, side_check=None):
    pace_s = EVAL_PACE_S if pace_s is None else pace_s
    lock = threading.Lock()
    it = iter(list(items))
    cnt = {"items": len(items), "made": 0, "fresh": 0, "nochart": 0, "budget": 0, "busy": 0, "fail": 0, "skip": 0, "stopped": None,
           "stopped_sides": {}}
    on9 = eval_sides_on(cfg)
    for side in EVAL_SIDES:
        if side not in on9:
            cnt["stopped_sides"][side] = "꺼짐"

    def all_stopped():
        if len(cnt["stopped_sides"]) >= len(EVAL_SIDES) and not cnt["stopped"]:
            cnt["stopped"] = "·".join(sorted(set(cnt["stopped_sides"].values())))
        return bool(cnt["stopped"])

    def worker():
        while True:
            with lock:
                if all_stopped():
                    return
                w9 = stop_check() if stop_check else None
                if w9:
                    cnt["stopped"] = w9
                    return
                nxt = next(it, None)
            if nxt is None:
                return
            d9, s9 = nxt
            for side in EVAL_SIDES:
                with lock:
                    if side in cnt["stopped_sides"]:
                        cnt["skip"] += 1
                        continue
                    w8 = side_check() if side_check else None
                    if w8:
                        cnt["stopped"] = w8
                        return
                try:
                    res = eval_one(cfg, d9, s9, side, get=get, sleep=sleep, runner=runner, binfn=binfn, stores=stores)
                except Exception as e:
                    log.warning("AI 평가 오류(%s %s %s): %s", d9, s9, side, e)
                    res = "fail"
                with lock:
                    cnt[res] = cnt.get(res, 0) + 1
                    if res == "budget":
                        cnt["stopped_sides"].setdefault(side, "하루 상한")
                if res == "made" and pace_s:
                    sleep(pace_s)

    with lock:
        stop0 = all_stopped()
    if stop0:
        log.info("AI 매도·매수 평가 꺼짐(config review.sell_eval_daily_max·buy_eval_daily_max = 0) — 영수증 %d 건너뜀", cnt["items"])
        return cnt
    n = max(1, min(int(parallel or 1), EVAL_PARALLEL_MAX, len(items) or 1))
    if n == 1:
        worker()
    else:
        ths = [threading.Thread(target=worker, name=f"tj-eval-{i + 1}", daemon=True) for i in range(n)]
        for t9 in ths:
            t9.start()
        for t9 in ths:
            t9.join()
    with lock:
        all_stopped()
    side_ko = {"sell": "매도", "buy": "매수"}
    part9 = "" if cnt["stopped"] else "".join(f" · {side_ko[k9]} 멈춤({v9})" for k9, v9 in sorted(cnt["stopped_sides"].items()))
    log.info("AI 매도·매수 평가: 영수증 %d · 새로 %d · 최신 %d · 봉 없음 %d · 실패 %d%s%s", cnt["items"], cnt["made"], cnt["fresh"], cnt["nochart"],
             cnt["fail"], f" · 멈춤({cnt['stopped']})" if cnt["stopped"] else "", part9)
    return cnt


def receipt_evals_recent(cfg, today_iso=None, days=None, get=None, **kw):
    if not eval_sides_on(cfg):
        log.info("AI 매도·매수 평가 꺼짐(config review.sell_eval_daily_max·buy_eval_daily_max = 0) — 자동 생성 건너뜀")
        return None
    if _manual_lock_live():
        log.info("AI 평가 자동 생성 건너뜀 — 수동 보충 진행 중")
        return None
    kw.setdefault("stop_check", lambda: "수동 보충 시작" if _manual_lock_live() else ("자동 생성 멈춤(설정)" if review_paused() else None))
    kw.setdefault("side_check", lambda: "자동 생성 멈춤(설정)" if review_paused() else None)
    t9 = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    f9 = (datetime.strptime(t9, "%Y-%m-%d") - timedelta(days=(CATCHUP_DAYS if days is None else days) - 1)).strftime("%Y-%m-%d")
    items = receipt_items(cfg, f9, t9, get=get)
    return receipt_evals(cfg, items, parallel=1, get=get, **kw)


def sell_evals_plan(cfg, since_iso, today_iso=None, get=None) -> dict:
    t9 = today_iso or datetime.now(KST).strftime("%Y-%m-%d")
    items = receipt_items(cfg, since_iso, t9, get=get)
    days9 = sorted({d for d, _ in items})
    return {"since": since_iso, "to": t9, "receipts": len(items), "days": len(days9), "first": days9[0] if days9 else None,
            "last": days9[-1] if days9 else None, "evals_max": 2 * len(items)}


def _receipt_evals_safe(cfg):
    if _paused_skip("영수증 AI 평가"):
        return
    try:
        receipt_evals_recent(cfg)
    except Exception as e:
        log.warning("AI 매도·매수 평가 자동 생성 실패(다음 회차 재시도): %s", e)


MANUAL_LOCK = os.path.join(common.STATE_DIR, "review_catchup_manual.lock")
MANUAL_LOCK_MAX_S = 12 * 3600


def _manual_lock_live(now=None) -> bool:
    try:
        d = json.load(open(MANUAL_LOCK, encoding="utf-8"))
        pid, ts = int(d.get("pid") or 0), float(d.get("ts") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if pid <= 0 or (now or time.time()) - ts > MANUAL_LOCK_MAX_S:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class _ManualLock:

    def __enter__(self):
        try:
            common.atomic_write_json(MANUAL_LOCK, {"pid": os.getpid(), "ts": int(time.time())})
        except OSError as e:
            log.warning("수동 보충 잠금 쓰기 실패(보충은 진행): %s", e)
        return self

    def __exit__(self, *a):
        try:
            if int((json.load(open(MANUAL_LOCK, encoding="utf-8")) or {}).get("pid") or 0) == os.getpid():
                os.remove(MANUAL_LOCK)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return False


OLD_BUDGET_PATH = os.path.join(common.STATE_DIR, "review_old_budget.json")
_OB_LOCK = threading.Lock()


_OB_WARNED = [False]


def _old_budget_read(day_iso: str) -> dict:
    fresh = {"day": day_iso, "used": 0, "days": []}
    exhausted = {"day": day_iso, "used": CATCHUP_OLD_MAX, "days": [], "_bad": True}

    def bad(why):
        if not _OB_WARNED[0]:
            _OB_WARNED[0] = True
            log.warning("옛 날 리뷰 예산 파일 이상(%s) — 오늘 자동 모델 보충 보류(%s)", why, OLD_BUDGET_PATH)
        return exhausted
    if not os.path.exists(OLD_BUDGET_PATH):
        return fresh
    try:
        with open(OLD_BUDGET_PATH, "r", encoding="utf-8") as f9:
            b = json.load(f9)
    except (OSError, ValueError) as e:
        return bad(f"읽기 실패 {type(e).__name__}")
    if not isinstance(b, dict) or not isinstance(b.get("day"), str) or type(b.get("used")) is not int or b["used"] < 0 \
            or not isinstance(b.get("days"), list):
        return bad("형식")
    try:
        if datetime.strptime(b["day"], "%Y-%m-%d").strftime("%Y-%m-%d") != b["day"]:
            return bad("날짜 형식")
    except ValueError:
        return bad("날짜 형식")
    if b["day"] < day_iso:
        return fresh
    if b["day"] > day_iso:
        return bad("미래 날짜")
    return {"day": b["day"], "used": b["used"], "days": [str(x) for x in b["days"] if x][:50]}


def old_budget_left(day_iso: str) -> int:
    with _OB_LOCK:
        return max(0, CATCHUP_OLD_MAX - _old_budget_read(day_iso)["used"])


def _old_budget_take(day_iso: str, d: str) -> bool:
    with _OB_LOCK:
        b = _old_budget_read(day_iso)
        if b.get("_bad") or b["used"] >= CATCHUP_OLD_MAX:
            return False
        b["used"] += 1
        b["days"].append(d)
        b["at"] = int(time.time())
        try:
            common.atomic_write_json(OLD_BUDGET_PATH, b)
        except (Exception, SystemExit) as e:
            log.warning("옛 날 리뷰 예산 기록 실패 — %s 보충 보류: %s", d, e)
            return False
        return True


def catch_up(cfg, since_iso=None, dry=False):
    b = None
    if not dry:
        b = claude_bin()
        if not b:
            return
    auto = not since_iso
    if auto and not dry and _paused_skip("일간 리뷰 보충"):
        return
    if auto and _manual_lock_live():
        log.info("리뷰 보충 건너뜀 — 수동 보충 진행 중(%s)", MANUAL_LOCK)
        return
    st = _state_for_today(cfg)
    today_iso = _today_iso(st)
    reviews = _read_reviews()
    todo = []
    if auto:
        since_iso = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=CATCHUP_DAYS)).strftime("%Y-%m-%d")
    all_days = [d for d in realized_days(st) if d < today_iso]
    days = [d for d in all_days if since_iso <= d]
    old_days = [d for d in all_days if d < since_iso and isinstance((_rv_for(reviews, d) or {}).get("fp"), dict)] if auto else []
    span = days + old_days
    day_ev = fetch_day_events(cfg, _ev_from(min(span)), max(span)) if span else None
    cur_len = None if auto else review_len_pref("daily")

    def need(rv9, fp9):
        return _stale(rv9, fp9) or (cur_len is not None and _len_off(rv9, cur_len, "daily"))
    for d in days:
        data = gather(st, d, day_ev, cfg, reviews)
        if need(_rv_for(reviews, d), _fp(data)):
            todo.append(d)
    extra = []
    ob_left = old_budget_left(today_iso) if auto else 0
    n_model = 0
    for d in sorted(old_days, reverse=True):
        if len(extra) >= CATCHUP_OLD_MAX:
            break
        data = gather(st, d, day_ev, cfg, reviews)
        if _stale_data(_rv_for(reviews, d), _fp(data)):
            if not _idle_day(data):
                if n_model >= ob_left:
                    continue
                n_model += 1
            extra.append(d)
    fill = review_fill_pref()
    todo = rprog.order_keys(extra + todo, fill["order"])
    if dry:
        return todo
    if not todo:
        return
    log.info("리뷰 보충 %d일 (%s ~ %s)%s · %s · 동시 %d건", len(todo), todo[0], todo[-1], f" · 옛 날 화면 낡음 {len(extra)}일" if extra else "",
             "최근부터" if fill["order"] == "recent" else "오래된 날부터", fill["parallel"])
    extra_set = set(extra)

    def work(kind9, d):
        rv_now = _read_reviews()
        data = gather(st, d, day_ev, cfg, rv_now)
        if not ((_stale_data if d in extra_set else need)(_rv_for(rv_now, d), _fp(data))):
            log.info("리뷰 보충 %s 건너뜀 — 이미 최신(다른 실행이 생성)", d)
            return None
        if d in extra_set and not _idle_day(data) and not _old_budget_take(today_iso, d):
            log.info("리뷰 보충 %s 건너뜀 — 옛 날 화면 낡음 오늘 예산(%d일) 소진(내일 이어서)", d, CATCHUP_OLD_MAX)
            return None
        return generate(b, data)

    stop_check = (lambda: "수동 보충 시작" if _manual_lock_live() else None) if auto else None
    run = _new_run("daemon-catchup" if auto else "manual-catchup", {"daily": todo}, fill)
    why = None
    try:
        why = _run_items(run, [("daily", d, "") for d in todo], work, fill["parallel"], stop_check=stop_check)
    finally:
        run.close(why)
    if why:
        log.warning("리뷰 보충 중단(%s) — 남은 날은 %s", why, "수동·다음 회차 몫" if why == "수동 보충 시작" else "다음 회차")


def refresh_templates(cfg, dry=False, st=None) -> list:
    st = st or fetch_state(cfg)
    today_iso = _today_iso(st)
    reviews = _read_reviews()
    t0 = datetime.strptime(today_iso, "%Y-%m-%d")
    cand = []
    for i in range(1, TEMPLATE_REFRESH_DAYS + 1):
        d = (t0 - timedelta(days=i)).strftime("%Y-%m-%d")
        rv = _rv_for(reviews, d)
        alt = reviews.get(d[5:10])
        if isinstance(alt, dict) and alt.get("model") != "template":
            continue
        if isinstance(rv, dict) and rv.get("model") == "template" and (rv.get("pre") or rv.get("tv") != TEMPLATE_V):
            cand.append(d)
    lim = (t0 - timedelta(days=TEMPLATE_REFRESH_DAYS)).strftime("%Y-%m-%d")
    old = []
    for k9, rv in reviews.items():
        if not isinstance(rv, dict) or rv.get("model") != "template" or not (rv.get("pre") or not rv.get("tv")):
            continue
        d = k9 if re.match(r"^\d{4}-\d{2}-\d{2}$", str(k9)) else None
        if not d or d >= lim or d in cand:
            continue
        alt = reviews.get(d[5:10])
        if isinstance(alt, dict) and alt.get("model") != "template":
            continue
        old.append(d)
    cand += sorted(set(old), reverse=True)[:TEMPLATE_OLD_MAX]
    if not cand:
        return []
    day_ev = fetch_day_events(cfg, _ev_from(min(cand)), max(cand))
    done = []
    for d in sorted(cand):
        data = gather(st, d, day_ev, cfg, reviews)
        data["_len"] = data.get("_len") or review_len_pref("daily")
        if data.get("_pre") or not _idle_day(data):
            continue
        if dry:
            done.append(d)
            continue
        if _store_template(OUT_PATH, d, _template_rec(data)):
            done.append(d)
        else:
            log.info("템플릿 다시 쓰기 %s 건너뜀 — 그날 모델 리뷰가 있거나 템플릿이 없음(보존)", d)
    if done and not dry:
        log.info("템플릿(체결 없는 날) 다시 쓰기 %d일 — 마감 뒤 값·원화 문장 (%s) · 모델 호출 없음", len(done), ", ".join(done))
    return done


WEEKLY_AUTO_DAYS = 35
WEEKLY_AUTO_MAX = 2
WEEKLY_STALE_USD = 5.0
NATIVE_FEE = {"ETH", "WETH", "BNB", "WBNB", "SOL", "WSOL", "POL", "MATIC", "AVAX", "TRX"}
_SEG_RX = re.compile(r"^(\d{4})-W(\d{2})([ab]?)$")


def week_key(day_iso: str) -> str:
    y, w, _ = datetime.strptime(day_iso, "%Y-%m-%d").isocalendar()
    return f"{y}-W{w:02d}"


def week_range(day_iso: str):
    d = datetime.strptime(day_iso, "%Y-%m-%d")
    mon = d - timedelta(days=d.weekday())
    return [(mon + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def week_segment(day_iso: str):
    d = datetime.strptime(day_iso, "%Y-%m-%d")
    mon = d - timedelta(days=d.weekday())
    sun = mon + timedelta(days=6)
    m1 = d.replace(day=1)
    mend = (m1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    lo, hi = max(mon, m1), min(sun, mend)
    wk = week_key(mon.strftime("%Y-%m-%d"))
    key = wk if (lo == mon and hi == sun) else wk + ("a" if lo == mon else "b")
    return key, lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")


def segment_days(seg) -> list:
    a, b = datetime.strptime(seg[1], "%Y-%m-%d"), datetime.strptime(seg[2], "%Y-%m-%d")
    return [(a + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((b - a).days + 1)]


def seg_iso_week(key: str) -> str:
    m = _SEG_RX.match(str(key or ""))
    return f"{m.group(1)}-W{m.group(2)}" if m else str(key or "")


def _prev_segment(seg):
    return week_segment((datetime.strptime(seg[1], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"))


def ended_segments(today_iso, since_iso=None, limit=None) -> list:
    out = []
    lo = since_iso or "2000-01-01"
    limit = limit or (None if since_iso else 1)
    d = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    while True:
        seg = week_segment(d)
        if seg[2] < lo:
            break
        if seg[2] < today_iso:
            out.append(seg)
            if limit and len(out) >= limit:
                break
        d = (datetime.strptime(seg[1], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return out


def _wk_rv_for(weekly, seg):
    rv = (weekly or {}).get(seg[0])
    return rv if isinstance(rv, dict) else None


def _wk_legacy(weekly, seg):
    iso = seg_iso_week(seg[0])
    if iso == seg[0]:
        return None
    rv = (weekly or {}).get(iso)
    return rv if isinstance(rv, dict) else None


def _seg_realized_total(f, days) -> float:
    return round(sum(sum(_realized(f, d)) for d in days), 2)


def _seg_has_realized(rdays, seg) -> bool:
    return any(seg[1] <= d <= seg[2] for d in rdays)


def gather_week(st, day_iso=None, day_ev=None, cfg=None, weekly=None) -> dict:
    f = st["fields"]
    day_iso = day_iso or _today_iso(st)
    seg = week_segment(day_iso)
    days = segment_days(seg)
    daily = []
    cyc = {}
    krw_tot, krw_ok = 0, True
    for d in days:
        rs, rf = _realized(f, d)
        if abs(rs) >= 0.005 or abs(rf) >= 0.005:
            k9 = _krw_total(f, d, rs, rf)
            if k9 is None:
                krw_ok = False
            else:
                krw_tot += k9
        raw = list((day_ev or {}).get(d) or []) if day_ev is not None else []
        norm = _norm_events(raw, d)
        syms_d = {o["sym"] for o in norm if not o["lp"]} | {p["sym"] for p in f.get("positions", [])
                                                           if p.get("kind") != "gas" and (p.get("realizedByDay") or {}).get(d)}
        canon = _canon_map(syms_d)
        for o in norm:
            if o["sym"] in canon:
                o["sym_raw"], o["sym"] = o["sym"], canon[o["sym"]]
        _mark_dca(norm)
        dca_inv = _dca_syms_recent(day_ev, d) | {o["sym"] for o in norm if o.get("dca") and o["side"] == "buy"}
        n_b = sum(1 for o in norm if o["side"] == "buy")
        n_bs = sum(1 for o in norm if o["side"] == "buy" and o.get("dca"))
        n_s = sum(1 for o in norm if o["side"] == "sell" and not o.get("dca") and not _is_stable(o["sym"]))
        if rs or rf or n_b or n_s:
            row9 = {"date": d, "realized": round(rs + rf, 2), "buys": n_b, "sells": n_s}
            if n_bs:
                row9["buys_small"] = n_bs
            daily.append(row9)
        first_buy_v = {}
        for o in norm:
            if o["side"] == "buy" and not o.get("dca") and o["sym"] not in first_buy_v:
                first_buy_v[o["sym"]] = o["v"]
        for row in _coin_rows(norm, f, d, canon, dca_inv, _seen_fills(day_ev, d), _carry_src_keys(raw, syms_d | set(canon.values()))):
            c = cyc.setdefault(row["sym"], {"sym": row["sym"], "realized": 0.0, "days": [], "buy_q": 0.0, "buy_u": 0.0,
                                            "sell_q": 0.0, "sell_u": 0.0, "known_u": 0.0, "dep_delay": [], "open_sell": [], "hold": [],
                                            "rounds": 0, "reentry": 0, "venues": set(), "route": None, "route_u": -1.0, "dca": False})
            c["days"].append(d[5:])
            c["realized"] += float(row.get("realized") or 0)
            for side, qk, uk in (("buy", "buy_q", "buy_u"), ("sell", "sell_q", "sell_u")):
                s9 = row.get(side) or {}
                c[qk] += float(s9.get("qty") or 0)
                c[uk] += float(s9.get("usd") or 0)
            p = row.get("path") or {}
            if p.get("dep_to_sell_min") is not None:
                c["dep_delay"].append(p["dep_to_sell_min"])
            if p.get("open_to_sell_min") is not None:
                c["open_sell"].append(p["open_to_sell_min"])
            if p.get("hold_min") is not None:
                c["hold"].append(p["hold_min"])
            su9 = float((row.get("sell") or {}).get("usd") or 0)
            if row.get("sell"):
                c["rounds"] += 1
                c["known_u"] += su9 * float(row.get("cost_known_pct") if row.get("cost_known_pct") is not None else 100.0) / 100.0
            if row.get("dca_inventory"):
                c["dca"] = True
            c["reentry"] += len(row.get("reentry") or [])
            hops = [first_buy_v.get(row["sym"]), p.get("first_sell_venue")]
            rt9 = []
            for h in hops:
                if h and (not rt9 or rt9[-1] != h):
                    rt9.append(h)
            if rt9 and su9 > c["route_u"]:
                c["route"], c["route_u"] = rt9, su9
        for fa in fills_agg(norm):
            c = cyc.get(fa["sym"])
            if c is not None:
                c["venues"].add(fa["venue"])
    rows, dca_rows = [], []
    for c in cyc.values():
        if _is_stable(c["sym"]) or (c["sell_u"] < CYCLE_MIN_SELL and c["buy_u"] < CYCLE_MIN_SELL):
            continue
        if (c["dca"] or c["sym"].upper() in NATIVE_FEE) and c["buy_u"] < CYCLE_MIN_SELL and c["sell_u"] < 1000:
            dca_rows.append(c)
            continue
        bv = c["buy_u"] / c["buy_q"] if c["buy_q"] else None
        sv = c["sell_u"] / c["sell_q"] if c["sell_q"] else None
        r = {"sym": c["sym"], "days": c["days"], "route": "→".join(c["route"] or []), "venues": sorted(c["venues"]),
             "realized": _r(c["realized"]), "buy_usd": _r(c["buy_u"]), "sell_usd": _r(c["sell_u"]), "rounds": c["rounds"], "reentry": c["reentry"]}
        if not r["route"]:
            del r["route"]
        if bv and sv:
            r["premium_pct"] = round((sv / bv - 1) * 100, 2)
        if c["sell_u"] > 0 and c["sell_u"] - c["realized"] > 0 and c["realized"]:
            r["margin_pct"] = round(100 * c["realized"] / (c["sell_u"] - c["realized"]), 2)
        if r.get("premium_pct") is not None and r.get("margin_pct") is not None and abs(r["premium_pct"] - r["margin_pct"]) < 0.5:
            del r["premium_pct"]
        if c["hold"]:
            r["hold_h"] = round(max(c["hold"]) / 60.0, 1)
        if c["dep_delay"]:
            r["dep_to_sell_min"] = int(statistics.median(c["dep_delay"]))
        if c["open_sell"]:
            r["open_to_sell_min"] = int(statistics.median(c["open_sell"]))
        if c["sell_u"] > 0 and c["known_u"] < c["sell_u"] - 0.005:
            r["cost_known_pct"] = round(100.0 * c["known_u"] / c["sell_u"], 1)
        rows.append(r)
    rows.sort(key=lambda r: -abs(r["realized"] or 0))
    closed = [r for r in rows if (r["sell_usd"] or 0) >= CYCLE_MIN_SELL]
    unk_c = [r for r in closed if abs(r["realized"] or 0) < 0.005 and r.get("cost_known_pct") is not None and r["cost_known_pct"] < 100]
    wins = [r for r in closed if (r["realized"] or 0) > 0]
    losses = [r for r in closed if (r["realized"] or 0) < 0]
    delays = [r["dep_to_sell_min"] for r in rows if r.get("dep_to_sell_min") is not None]
    lp_all = []
    for d in days:
        lr, _t = _lp_rows(f, d, limit=None)
        for x in lr:
            if x["id"] not in {y["id"] for y in lp_all}:
                lp_all.append(x)
    lp_fees = sum(x.get("fees") or 0 for x in lp_all)
    lp_mins = sum(x.get("mins") or 0 for x in lp_all if x.get("closed"))
    rs_w = sum(x["realized"] for x in daily)
    data = {"week": seg[0], "iso_week": seg_iso_week(seg[0]), "from": seg[1], "to": seg[2], "realized_total": round(rs_w, 2),
            "daily": daily, "cycles": rows[:20],
            "stats": {"cycles": len(closed), "win_rate_pct": round(100.0 * len(wins) / (len(wins) + len(losses)), 1) if (wins or losses) else None,
                      "wins": len(wins), "losses": len(losses), "cost_unknown": len(unk_c),
                      "buys": sum(x["buys"] for x in daily), "buys_small": sum(x.get("buys_small", 0) for x in daily),
                      "sells": sum(x["sells"] for x in daily),
                      "dep_to_sell_min_median": int(statistics.median(delays)) if delays else None,
                      "lp_n": len(lp_all), "lp_fees": _r(lp_fees),
                      "lp_per_hour": _r(lp_fees / (lp_mins / 60.0)) if lp_mins >= 60 and lp_fees else None}}
    if seg[0] != data["iso_week"]:
        data["partial"] = True
    if krw_ok and any(abs(x["realized"]) >= 0.005 for x in daily):
        data["realized_total_krw"] = int(krw_tot)
    if dca_rows:
        data["dca_sells"] = {"n": len(dca_rows), "sell_usd": _r(sum(c["sell_u"] for c in dca_rows)),
                             "realized": _r(sum(c["realized"] for c in dca_rows)), "syms": sorted(c["sym"] for c in dca_rows)[:8],
                             "note": "정기 분산 매수 물량·수수료용 네이티브 매도 — 사이클·승률 제외, 지적 대상 아님"}
    if lp_all:
        data["lp"] = sorted(lp_all, key=lambda x: -(x.get("fees") or 0))[:8]
    pl = _plans_for(f, {r["sym"] for r in rows})
    if pl:
        data["plans"] = pl
    if any(x.get("memo") for x in pl) and closed and not any(x.get("memo") and x["sym"] == closed[0]["sym"] for x in pl):
        data["memo_nag"] = True
    data["known_patterns"] = known_patterns(cfg)
    if weekly:
        prev = _prev_segment(seg)
        pv9 = _wk_rv_for(weekly, prev) or _wk_legacy(weekly, prev)
        nx = str((pv9 or {}).get("next") or "").strip()
        if nx and nx not in ("없음.", "없음"):
            data["prior_next"] = [nx]
        pp, s9 = [], prev
        for _i in range(2):
            r9 = _wk_rv_for(weekly, s9) or _wk_legacy(weekly, s9)
            for x9 in (r9 or {}).get("patterns") or []:
                t9 = str(x9 or "").strip()[:40]
                if t9 and t9 not in pp:
                    pp.append(t9)
            s9 = _prev_segment(s9)
        if pp:
            data["prior_patterns"] = pp[:6]
    data["no_fills"] = not closed and not any(x["sells"] for x in daily) and not any((x["buys"] - x.get("buys_small", 0)) for x in daily)
    data["grade"] = grade(data)
    if not data["no_fills"]:
        del data["no_fills"]
    if data["grade"] == "양호":
        lc = loss_coins(data)
        if lc:
            data["loss_coins"] = lc
    return data


_HASH_SKIP_WEEK = ("prior_next", "prior_patterns", "lp")


def _input_hash_week(data) -> str:
    core = {k: v for k, v in data.items() if not k.startswith("_") and k not in _HASH_SKIP_WEEK}
    st9 = dict(core.get("stats") or {})
    for k in ("lp_fees", "lp_per_hour"):
        st9.pop(k, None)
    core["stats"] = st9
    return hashlib.sha1(json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def _input_hash_week_q(data) -> str:
    core = {k: v for k, v in data.items() if not k.startswith("_") and k not in _HASH_SKIP_WEEK}
    st9 = dict(core.get("stats") or {})
    for k in ("lp_fees", "lp_per_hour"):
        st9.pop(k, None)
    core["stats"] = st9
    return _qhash(core)


def _fp_week(data) -> dict:
    return {"pv": WEEKLY_PROMPT_VERSION, "rs": data["realized_total"], "ih": _input_hash_week(data), "ihq": _input_hash_week_q(data),
            "from": data["from"], "to": data["to"], "rk": data.get("realized_total_krw"),
            "len": rp.len_key("weekly", data.get("_len"))}


def _stale_week_data(rv, fp) -> bool:
    old = (rv or {}).get("fp")
    if not isinstance(old, dict):
        return False
    a, b = float(old.get("rs") or 0), float(fp.get("rs") or 0)
    if abs(a - b) > max(WEEKLY_STALE_USD, 0.01 * max(abs(a), abs(b))):
        return True
    if old.get("rk") is not None and fp.get("rk") is not None:
        a, b = float(old["rk"]), float(fp["rk"])
        if abs(a - b) > max(1500.0, 0.005 * max(abs(a), abs(b))):
            return True
    elif old.get("rk") is None and fp.get("rk") is not None and old.get("ihq"):
        return True
    if old.get("pv") == fp.get("pv") and (old.get("ihq") or old.get("ih")) and _ih_changed(old, fp):
        return True
    if (rv.get("from") and rv.get("from") != fp.get("from")) or (rv.get("to") and rv.get("to") != fp.get("to")):
        return True
    return False


def _stale_week(rv, fp) -> bool:
    if not isinstance(rv, dict) or not isinstance(rv.get("fp"), dict):
        return True
    return rv["fp"].get("pv") != fp.get("pv") or _stale_week_data(rv, fp)


def normalize_week(rv: dict, data: dict) -> dict:
    pr = rp.len_preset("weekly", data.get("_len"))
    rv = _scrub(_delink(rv), data, data["week"])
    sm = screen_terms(rv.get("sum") or "")
    note = clip_sentence(screen_terms(rv.get("note")), NOTE_MAX)
    if not note or len(note) > NOTE_MAX or note.endswith("…"):
        note = _first_sentence(sm) or note
    rec = {"s": data.get("grade") or "관망", "note": note, "sum": sm,
           "patterns": [clip_sentence(screen_terms(x), WEEKLY_FIELD_HARD) for x in (rv.get("patterns") or [])
                        if str(x or "").strip()][:pr["pat_max"]],
           "rule": clip_sentence(screen_terms(rv.get("rule") or ""), WEEKLY_FIELD_HARD),
           "next": clip_sentence(screen_terms(rv.get("next") or "없음."), WEEKLY_FIELD_HARD) or "없음.",
           "from": data["from"], "to": data["to"], "isoWeek": data["iso_week"], "stats": data["stats"]}
    if data.get("partial"):
        rec["partial"] = True
    if data.get("loss_coins"):
        rec["lossCoins"] = data["loss_coins"]
    rec = _fit_len(rec, pr["max"])
    rec.update(fp=_fp_week(data), model=REVIEW_MODEL, at=int(time.time()))
    return rec


def generate_week(b, data) -> bool:
    key = data["week"]
    data = dict(data, _len=data.get("_len") or review_len_pref("weekly"))
    prompt = rp.weekly_prompt(data["_len"])
    _GS.llm, _GS.regen = True, False
    rv = _run_cli(b, prompt, data, key)
    if rv is None:
        return False
    rv = _fit_len(_trim_sum_total(_postfix(rv, data), data), _len_max(None, data))
    probs = validate(rv, data)
    hard = _hard_probs(probs, rv)
    if hard:
        log.info("주간 리뷰 검증 위반(%s) %d건 → 1회 재생성: %s", key, len(hard), " | ".join(hard)[:600])
        _GS.regen = True
        rv2 = _run_cli(b, _retry_prompt(hard, prompt), data, key + " 재생성")
        if rv2 is not None:
            rv2 = _fit_len(_trim_sum_total(_postfix(rv2, data), data), _len_max(None, data))
            if len(_hard_probs(validate(rv2, data), rv2)) <= len(hard):
                rv = rv2
    note = re.sub(r"\s+", " ", str(rv.get("note") or "")).strip()
    if len(note) > NOTE_MAX or "…" in note:
        nv = _run_cli(b, rp.NOTE_PROMPT, data, key + " note", body=note)
        n2 = re.sub(r"\s+", " ", str((nv or {}).get("note") or "")).strip()
        if n2 and len(n2) <= NOTE_MAX and "…" not in n2:
            rv = dict(rv, note=n2)
    rec = normalize_week(rv, data)
    if not _store_put(WEEKLY_PATH, key, rec):
        return False
    log.info("주간 리뷰 생성 완료: %s(%s~%s) [%s] 사이클 %d개 · 입력 %d자", key, data["from"], data["to"], rec["s"], len(data["cycles"]),
             len(payload(data)))
    return True


def _gather_seg(st, cfg, seg, weekly=None, day_ev=None):
    if day_ev is None:
        day_ev = fetch_day_events(cfg, _ev_from(seg[1]), seg[2])
    return gather_week(st, seg[1], day_ev, cfg, weekly if weekly is not None else _read_reviews(WEEKLY_PATH))


def run_week(cfg, day_iso=None, mode="daemon-week"):
    b = claude_bin()
    if not b:
        log.info("claude CLI 없음 — 주간 리뷰 생략")
        return
    st = fetch_state(cfg)
    seg = week_segment(day_iso or _today_iso(st))
    run = _new_run(mode, {"weekly": [seg[0]]}, {"order": "recent", "parallel": 1})
    why = None
    try:
        why = _run_items(run, [("weekly", seg[0], _seg_label(seg))], lambda k9, key9: generate_week(b, _gather_seg(st, cfg, seg)), 1, pace_s=0)
    finally:
        run.close(why)


def weekly_plan(st, cfg, today_iso, since_iso=None, weekly=None, day_ev=None) -> list:
    weekly = weekly if weekly is not None else _read_reviews(WEEKLY_PATH)
    rdays = realized_days(st)
    auto = not since_iso
    lo = since_iso or (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=WEEKLY_AUTO_DAYS)).strftime("%Y-%m-%d")
    segs = ended_segments(today_iso, lo)
    cur_len = None if auto else review_len_pref("weekly")
    out = []
    for i, seg in enumerate(segs):
        if not _seg_has_realized(rdays, seg):
            continue
        rv = _wk_rv_for(weekly, seg)
        if rv is None:
            if auto and i > 0 and _wk_legacy(weekly, seg) is not None:
                continue
            out.append((seg, "없음"))
            continue
        old = rv.get("fp") if isinstance(rv.get("fp"), dict) else {}
        if old.get("pv") != WEEKLY_PROMPT_VERSION:
            if not auto or i == 0:
                out.append((seg, "리뷰 방식 변경"))
            continue
        if cur_len is not None and _len_off(rv, cur_len, "weekly"):
            out.append((seg, "분량 변경"))
            continue
        if _stale_week_data(rv, _fp_week(_gather_seg(st, cfg, seg, weekly, day_ev))):
            out.append((seg, "데이터 낡음"))
    out = sorted(out, key=lambda x: x[0][1])
    if auto:
        out = out[-WEEKLY_AUTO_MAX:]
    return out


def weekly_refresh(cfg):
    if _paused_skip("주간 리뷰 보충"):
        return
    b = claude_bin()
    if not b:
        return
    if _manual_lock_live():
        log.info("주간 보충 건너뜀 — 수동 보충 진행 중")
        return
    st = fetch_state(cfg)
    todo = weekly_plan(st, cfg, _today_iso(st))
    if not todo:
        return
    fill = review_fill_pref()
    segs = {s9[0]: (s9, w9) for s9, w9 in todo}
    keys = rprog.order_keys(list(segs), fill["order"])

    def work(kind9, key9):
        seg, why9 = segs[key9]
        log.info("주간 리뷰 보충: %s(%s~%s) — %s", seg[0], seg[1], seg[2], why9)
        return generate_week(b, _gather_seg(st, cfg, seg))

    run = _new_run("daemon-weekly", {"weekly": keys}, fill)
    why = None
    try:
        why = _run_items(run, [("weekly", k9, _seg_label(segs[k9][0])) for k9 in keys], work, fill["parallel"],
                         stop_check=lambda: "수동 보충 시작" if _manual_lock_live() else None)
    finally:
        run.close(why)
    if why:
        log.warning("주간 보충 중단(%s)", why)


weekly_catch_up = weekly_refresh


def weekly_since(cfg, since_iso, dry=False):
    b = None
    if not dry:
        b = claude_bin()
        if not b:
            log.info("claude CLI 없음 — 주간 보충 생략")
            return []
    st = fetch_state(cfg)
    today = _today_iso(st)
    segs = ended_segments(today, since_iso)
    day_ev = fetch_day_events(cfg, _ev_from(min(s[1] for s in segs)), max(s[2] for s in segs)) if segs else None
    todo = weekly_plan(st, cfg, today, since_iso, day_ev=day_ev)
    if dry or not todo:
        log.info("주간 보충 %s: %d개%s", "계획" if dry else "대상", len(todo), (" (" + todo[0][0][0] + " ~ " + todo[-1][0][0] + ")") if todo else "")
        return todo
    fill = review_fill_pref()
    segs = {s9[0]: (s9, w9) for s9, w9 in todo}
    keys = rprog.order_keys(list(segs), fill["order"])
    log.info("주간 보충 %d개 (%s ~ %s) · %s · 동시 %d건", len(todo), todo[0][0][0], todo[-1][0][0],
             "최근부터" if fill["order"] == "recent" else "오래된 것부터", fill["parallel"])
    done = set()

    def work(kind9, key9):
        ok9 = generate_week(b, _gather_seg(st, cfg, segs[key9][0], None, day_ev))
        if ok9:
            done.add(key9)
        return ok9

    run = _new_run("manual-weekly", {"weekly": keys}, fill)
    why = None
    try:
        why = _run_items(run, [("weekly", k9, _seg_label(segs[k9][0])) for k9 in keys], work, fill["parallel"])
    finally:
        run.close(why)
    if why:
        log.warning("주간 보충 중단(%s) — 남은 %d개", why, len(todo) - len(done))
        return [x for x in todo if x[0][0] not in done]
    return []


def _refresh_templates_safe(cfg):
    try:
        refresh_templates(cfg)
    except Exception as e:
        log.warning("템플릿 다시 쓰기 실패(다음 회차 재시도): %s", e)


def _weekly_due(day: datetime) -> bool:
    return day.weekday() == 6 or (day + timedelta(days=1)).day == 1


def _pop_fill_override(argv) -> dict:
    ov, out, i = {}, [argv[0]], 1
    while i < len(argv):
        a = argv[i]
        if a in ("--order", "--parallel"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{a} 값이 필요합니다")
            v = argv[i + 1]
            if a == "--order":
                if v not in rprog.FILL_ORDERS:
                    raise SystemExit("--order 는 recent|oldest")
                ov["order"] = v
            else:
                if v not in ("1", "3"):
                    raise SystemExit("--parallel 은 1|3")
                ov["parallel"] = int(v)
            i += 2
            continue
        out.append(a)
        i += 1
    argv[:] = out
    return ov


def main():
    common.ensure_dirs()
    _FILL_OVERRIDE.update(_pop_fill_override(sys.argv))
    if _FILL_OVERRIDE and len(sys.argv) == 1:
        raise SystemExit("--order·--parallel 은 --catchup-since·--weekly-since·--days·--sell-evals-since 와 함께만 씁니다")
    cfg = common.load_config()
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        st = fetch_state(cfg, max_age=None)
        d = sys.argv[2] if len(sys.argv) > 2 else _today_iso(st)
        data = gather(st, d, fetch_day_events(cfg, _ev_from(d), d), cfg, _read_reviews())
        print(json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, ensure_ascii=False, indent=1))
        print(f"# 입력 {len(payload(data))}자 · 지문 {_fp(data)}", file=sys.stderr)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--weekly-dry-run":
        st = fetch_state(cfg, max_age=None)
        seg = week_segment(sys.argv[2] if len(sys.argv) > 2 else _today_iso(st))
        data = _gather_seg(st, cfg, seg)
        print(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"# 구간 {seg[0]}({seg[1]}~{seg[2]}) · 입력 {len(payload(data))}자 · 지문 {_fp_week(data)}", file=sys.stderr)
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--plan-since":
        days = catch_up(cfg, sys.argv[2], dry=True) or []
        weeks = weekly_since(cfg, sys.argv[2], dry=True) or []
        print(json.dumps({"daily": days, "weekly": [{"key": s9[0], "from": s9[1], "to": s9[2], "why": w9} for s9, w9 in weeks]},
                         ensure_ascii=False, indent=1))
        print(f"# 일간 {len(days)}일 · 주간 {len(weeks)}구간", file=sys.stderr)
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--refresh-templates", "--refresh-templates-plan"):
        print(json.dumps(refresh_templates(cfg, dry=sys.argv[1].endswith("-plan")), ensure_ascii=False))
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--weekly":
        run_week(cfg, sys.argv[2] if len(sys.argv) > 2 else None, mode="manual-week")
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--days":
        b = claude_bin()
        st = fetch_state(cfg)
        days9 = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
        fill9 = review_fill_pref()
        run = _new_run("manual-days", {"daily": days9}, fill9)
        why9 = None
        try:
            why9 = _run_items(run, [("daily", d, "") for d in days9],
                              lambda k9, d: generate(b, gather(st, d, fetch_day_events(cfg, _ev_from(d), d), cfg, _read_reviews())), fill9["parallel"])
        finally:
            run.close(why9)
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--weekly-since":
        with _ManualLock():
            weekly_since(cfg, sys.argv[2])
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--sell-evals-plan":
        print(json.dumps(sell_evals_plan(cfg, sys.argv[2]), ensure_ascii=False))
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--sell-evals-since":
        if not eval_sides_on(cfg):
            log.warning("AI 매도·매수 평가가 꺼져 있어요 — 켜려면 config.json 의 review.sell_eval_daily_max · buy_eval_daily_max 를 1 이상으로")
            return
        with _ManualLock():
            items = receipt_items(cfg, sys.argv[2], datetime.now(KST).strftime("%Y-%m-%d"))
            receipt_evals(cfg, items, parallel=min(EVAL_PARALLEL_MAX, int(_FILL_OVERRIDE.get("parallel") or 1)))
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--catchup-since":
        with _ManualLock():
            catch_up(cfg, sys.argv[2])
        return
    log.info("가동: 매일 23:50 KST 리뷰 생성 + 최근 %d일 실현(손익 절댓값) 있던 날 보충 · 일요일·말일 23:55 주간 리뷰(월 경계 구간) "
             "(프롬프트 %s · 주간 %s)", CATCHUP_DAYS, PROMPT_VERSION, WEEKLY_PROMPT_VERSION)
    boot = datetime.now(KST)
    try:
        catch_up(cfg)
    except Exception as e:
        log.warning("리뷰 보충 실패(다음 회차 재시도): %s", e)
    try:
        weekly_refresh(cfg)
    except Exception as e:
        log.warning("주간 리뷰 보충 실패(다음 회차 재시도): %s", e)
    _refresh_templates_safe(cfg)
    _receipt_evals_safe(cfg)
    ref = boot
    while True:
        now = datetime.now(KST)
        ref = ref or now
        target = ref.replace(hour=23, minute=50, second=0, microsecond=0)
        if ref >= target:
            target += timedelta(days=1)
        tfix = ref.replace(hour=0, minute=15, second=0, microsecond=0)
        if ref >= tfix:
            tfix += timedelta(days=1)
        ref = None
        if tfix < target:
            time.sleep(max(30, (tfix - now).total_seconds()))
            _refresh_templates_safe(cfg)
            continue
        time.sleep(max(30, (target - now).total_seconds()))
        try:
            run_today(cfg)
        except Exception as e:
            log.warning("리뷰 생성 실패(내일 재시도): %s", e)
        try:
            catch_up(cfg)
        except Exception as e:
            log.warning("리뷰 보충 실패(다음 회차 재시도): %s", e)
        _receipt_evals_safe(cfg)
        if _weekly_due(target):
            wait = (target.replace(minute=55) - datetime.now(KST)).total_seconds()
            if wait > 0:
                time.sleep(wait)
            try:
                if not _paused_skip("주간 리뷰"):
                    run_week(cfg, target.strftime("%Y-%m-%d"))
            except Exception as e:
                log.warning("주간 리뷰 생성 실패(기동 시·다음 회차 재시도 · 수동 --weekly): %s", e)
        try:
            weekly_refresh(cfg)
        except Exception as e:
            log.warning("주간 리뷰 보충 실패(다음 회차 재시도): %s", e)
        _refresh_templates_safe(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
