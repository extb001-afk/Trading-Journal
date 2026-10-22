from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import time
from typing import Callable, Optional

import calcguard
import logs
import num_parse
import paths
import statefile
import token_tables

log = logging.getLogger("tj-core")

__all__ = ["AMEND_SITES", "KIND", "SITES", "check", "classify", "compute", "coverage_gaps", "exf_dm", "exf_why", "load_rows",
           "note", "note_fix", "prices", "refresh", "summarize", "tick", "venue_values"]

KIND = "adj_why"
OBS_PFX = "adjwhy:"
STATE_NAME = "recon_adj.json"

SITES = {
    "K1": ("core_recon", "_recon_pass_scopes", "체인 대사(recon:<체인>) — 양수 = 창 시작 기초 잔고 · 음수 = 미추적 유출"),
    "K2": ("core_recon", "_wrecon_run", "새 지갑·나눠 대사(recon:<체인>:<지갑>)"),
    "K3": ("discopen", "write_anchor", "발견 시점 기초 잔고(등록 대사가 놓친 보유)"),
    "K4": ("core_snap", "_anchor_adjust", "대사 뒤 온 창 안 옛 거래 — 대사 앵커 재기장"),
    "K5": ("core_post", "_post_stake_open", "솔라나 스테이크 계정 기초 잔고"),
    "K7": ("core_exf", "exf_recon_pass", "해외 거래소 대사 차이"),
    "K7f": ("core_exf_fut", "_exf_fut_place_apply", "선물 정산 이관 — 대사 행 다시 놓기"),
    "K8": ("core_exf_fut", "_exf_fut_post", "선물 정산(futpnl)"),
    "K9": ("core_exf_late", "_exf_late_offset", "늦은 행 상쇄(exflate)"),
    "K10": ("core_upbit_recon", "exchange_recon_pass", "업비트 대사 차이"),
}
SITE_TOOL = "K6"
TOOL_SIDS = ("rebal20260901", "fix1004")
AMEND_SITES = {
    ("core_snap", "_anchor_adjust"): "note",
    ("core_exf", "_exf_shrink"): "note",
    ("core_exf", "_exf_ext_redate"): "note",
    ("core_exf_fut", "_exf_fut_place_apply"): "note",
    ("core_post", "_post_stake_open"): "지움만(과거 창 확장 — 옛 기초 잔고를 지우고 새 줄은 K5 가 기록)",
    ("core_exf", "_exf_fix_place_apply"): "1회 정리 도구(시각·수량 재배치 — tools/exf_fix_place.py)",
    ("core_exf", "_exf_ext_settle_repair"): "1회 정리 도구(시각만 — tools/repair_exf_settle.py)",
    ("core_exf_late", "_exf_redate_once"): "1회 이행(시각만)",
    ("core_exf_late", "_exf_debt_redate_once"): "1회 이행(부채 첫 반영 시각·이자 레그)",
}

CLS_KO = {"spam": "스팸·무가치(가격 없음)", "dust": "$1 미만 먼지", "interest": "부채 이자", "futpnl": "선물 정산", "exflate": "늦은 행 상쇄",
          "tool": "수리 도구 행", "pair": "±상쇄 쌍(14일 안)", "pre_window": "창 시작 기초 잔고(수집 이전 보유)", "new_source": "새 잔고 출처 첫 실림",
          "estimated": "추정 — 알려진 미수집", "unexplained": "설명 안 됨"}
RED_KO = {"prewin_rows": "창 이전 원장 행을 되받는 앵커", "mirror": "네이티브와 수량 같은 토큰 앵커", "flip3": "같은 칸 ±쌍 하루 3개 이상"}
RED_CAUSE = {"prewin_rows": "창 시작 앵커인데 그 칸에 창보다 이른 원장 행 있음", "mirror": "토큰 수량이 같은 지갑 네이티브 잔고와 같음",
             "flip3": "같은 칸에서 하루 3쌍 이상 ±뒤집힘"}
HINTS = {"binance": "바이낸스 배당·에어드랍·Earn(assetDividend)·Pay/C2C 미수집일 수 있음", "gate": "게이트 account_book 미수집일 수 있음",
         "bybit": "바이비트 Earn·펀딩 계정(권한) 미수집일 수 있음", "okx": "OKX 체결 보존 기한(3개월) 밖 매수일 수 있음",
         "upbit": "업비트 스테이킹(API 없음)일 수 있음", "bithumb": "빗썸 이벤트 지급(API 없음)일 수 있음"}
STABLES = frozenset(("USDT", "USDC", "DAI", "USD", "FDUSD", "BUSD", "USDE", "USD1", "PYUSD", "RLUSD", "USDG", "TUSD"))
PAIR_DAYS = 14
PAIR_TOL = 0.005
DUST_USD = 1.0
ROW_WARN_USD = 500.0
ROW_WARN_PCT = 0.02
WEEK_TG_USD = 1000.0
FLIP_DAY_N = 3
DAY = 86400
WEEK = 7 * DAY
MIN_GAP_SEC = 60
REFRESH_SEC = 600
TOP_N = 5

T0Fn = Optional[Callable[[str, int], Optional[int]]]
PxFn = Optional[Callable[[str, int], object]]


def _oid(key: tuple) -> str:
    kind, ns, sid, seq = key
    return f"{OBS_PFX}{kind}|{ns}|{sid}|{int(seq)}"


def _put(conn: sqlite3.Connection, oid: str, venue: str, pay: dict, at: int) -> None:
    conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                 (oid, KIND, str(venue), json.dumps(pay, ensure_ascii=False, sort_keys=True), int(at)))


def _in_tx(conn: sqlite3.Connection) -> bool:
    try:
        return bool(conn.in_transaction)
    except sqlite3.Error:
        return False


def _swallow_or_raise(conn: sqlite3.Connection, in_tx: bool, e: sqlite3.Error, msg: str) -> None:
    if in_tx and not _in_tx(conn):
        raise e
    log.warning(msg, e)


def note(conn: sqlite3.Connection, site: str, key: tuple, why: str = "", **ctx: object) -> None:
    pay = {"site": str(site), "why": str(why), "sid": str(key[2]), "seq": int(key[3])}
    pay.update({k: v for k, v in ctx.items() if v is None or isinstance(v, (bool, int, float, str))})
    in_tx = _in_tx(conn)
    try:
        _put(conn, _oid(key), key[1], pay, time.time())
    except sqlite3.Error as e:
        _swallow_or_raise(conn, in_tx, e, "보정 갈래 기록 실패(원장은 그대로): %s")


def note_fix(conn: sqlite3.Connection, site: str, pid: int, why: str = "") -> None:
    in_tx = _in_tx(conn)
    try:
        r = conn.execute("SELECT source_kind, source_ns, source_id, leg_seq FROM postings WHERE posting_id=?", (int(pid),)).fetchone()
        if r is None:
            return
        oid = _oid(tuple(r))
        old = conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (oid,)).fetchone()
        try:
            pay = json.loads(old[0]) if old else {}
        except (TypeError, ValueError):
            pay = {}
        pay = pay if isinstance(pay, dict) else {}
        pay.setdefault("sid", str(r[2]))
        pay.setdefault("seq", int(r[3]))
        fixes = [x for x in (pay.get("fix") or []) if isinstance(x, dict)] + [{"site": str(site), "why": str(why), "at": int(time.time())}]
        pay["fix"] = fixes[-5:]
        _put(conn, oid, r[1], pay, int(old[1]) if old else time.time())
    except sqlite3.Error as e:
        _swallow_or_raise(conn, in_tx, e, "보정 고침 기록 실패(원장은 그대로): %s")


def exf_why(qb: int, ev: int, bts: int, seq: int, flags: dict) -> str:
    f = {k: bool(flags.get(k)) for k in ("first", "cov", "settle", "now", "debt", "skip")}
    qb, ev, bts = int(qb), int(ev), int(bts)
    if qb < 0 and f["debt"] and not f["first"]:
        return "debt_interest" if int(seq) == 2 else "debt_first"
    if qb > 0 and (f["first"] or f["cov"] or f["settle"]):
        return "first" if f["first"] else "new_source" if f["cov"] else "settle_pos"
    if qb > 0 and f["now"]:
        return "hl_cash"
    if qb > 0:
        return ("deficit_back" if ev < bts - 60 else "later_in") + (":krw" if f["skip"] else "")
    return "first" if f["first"] else "settle_neg" if f["settle"] else "untracked_out"


def _rj(path: str, default: object = None) -> object:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _pos_float(v: object) -> Optional[float]:
    f = num_parse.to_float(v, catch_overflow=True)
    return f if f is not None and f > 0 and math.isfinite(f) else None


def prices(state_dir: Optional[str] = None) -> dict:
    daily = _rj((os.path.join(state_dir, "daily_px.json") if state_dir else paths.state("daily_px.json")), {}) or {}
    grp = {}
    for day in sorted(x for x in daily if str(x)[:2] == "20"):
        for g, v in ((daily.get(day) or {}).get("p") or {}).items():
            px = _pos_float(v)
            if px is not None and str(g).lstrip("-").isdigit():
                grp[int(g)] = px
    seen = (_rj((os.path.join(state_dir, "first_seen_px.json") if state_dir else paths.state("first_seen_px.json")), {}) or {}).get("p") or {}
    leg = {}
    for k, v in seen.items():
        px = _pos_float(v[0]) if isinstance(v, list) and v else None
        if px is not None:
            leg[str(k)] = px
    return {"grp": grp, "leg": leg}


def coverage_gaps(state_dir: Optional[str] = None) -> dict:
    doc = _rj((os.path.join(state_dir, "coverage_limits.json") if state_dir else paths.state("coverage_limits.json")), {}) or {}
    out = {}
    for u in doc.get("unavailable") or []:
        p = str(u.get("source_id") or "").split(":") if isinstance(u, dict) else []
        if len(p) < 2 or p[0] not in ("exchange", "chain"):
            continue
        try:
            before = int(time.mktime(time.strptime(str(u["before"])[:10], "%Y-%m-%d"))) if u.get("before") else None
        except (TypeError, ValueError, OverflowError):
            before = None
        prev = out.get(p[1])
        if prev is None or before is None or (prev[0] is not None and before > prev[0]):
            out[p[1]] = (before, str(u.get("reason_ko") or u.get("label") or ""))
    return out


def _venue(loc: str) -> str:
    p = str(loc or "").split(":")
    return p[1] if len(p) >= 2 else str(loc or "")


def _site_of(r: dict) -> str:
    sid, ns = r["sid"], r["ns"]
    if r["kind"] == "opening":
        p = sid.split(":")
        if p[0] in TOOL_SIDS or not sid.startswith("recon:"):
            return SITE_TOOL
        if ":disc:" in sid:
            return "K3"
        if sid.startswith("recon:sol:stake:"):
            return "K5"
        return "K1" if len(p) == 2 else "K2"
    if r["event"] == "EX_ADJUST":
        return "K10"
    if ns.endswith(":futpnl"):
        return "K8"
    return "K9" if sid.startswith("exflate:") else "K7"


def _bts(sid: str) -> Optional[int]:
    if not str(sid).startswith(("exfrecon:", "exrecon:")):
        return None
    try:
        return int(str(sid).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _stable_cas(chain: Optional[str]) -> frozenset:
    return frozenset(str(k).lower() for k in (token_tables.STABLE_CAS.get(chain) or {}))


def _px_of(r: dict, px: dict, px_fn: PxFn) -> Optional[float]:
    if (r["akind"] == "exchange_currency" and r["sym"].upper() in STABLES) or r["addr"] in _stable_cas(r["chain"]):
        return 1.0
    got = px["leg"].get(f"{r['ns']}|{r['sid']}|{r['seq']}|{r['aid']}")
    if got is None and r["gid"] is not None:
        got = px["grp"].get(int(r["gid"]))
    if got is None and px_fn is not None and r["akind"] == "exchange_currency" and r["sym"].upper() != "KRW":
        try:
            got = _pos_float(px_fn(r["sym"], int(r["aid"])))
        except (TypeError, ValueError, ArithmeticError):
            got = None
    return got


def _notes(conn: sqlite3.Connection) -> dict:
    out = {}
    for oid, pl, at in conn.execute("SELECT obs_id, payload, observed_at FROM raw_observations WHERE obs_id >= ? AND obs_id < ?",
                                    (OBS_PFX, OBS_PFX[:-1] + ";")):
        try:
            pay = json.loads(pl)
        except (TypeError, ValueError):
            continue
        if isinstance(pay, dict):
            out[oid] = (pay, int(at))
    return out


_ROW_SQL = ("SELECT p.posting_id, p.source_kind, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.asset_id, p.location, p.qty_base, p.event,"
            " a.kind, a.chain, a.symbol, a.decimals, a.group_id, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
            " WHERE p.leg_kind='opening'")
_ROW_KEYS = ("pid", "kind", "ns", "sid", "seq", "ts", "aid", "loc", "qb", "event", "akind", "chain", "sym", "dec", "gid", "addr")


def _per_asset(px_fn: Callable[[str, int], object]) -> Callable[[str, int], object]:
    memo = {}

    def f(sym: str, aid: int) -> object:
        if aid not in memo:
            memo[aid] = px_fn(sym, aid)
        return memo[aid]
    return f


def load_rows(conn: sqlite3.Connection, px: Optional[dict] = None, px_fn: PxFn = None) -> list:
    px = px or {"grp": {}, "leg": {}}
    if px_fn is not None:
        px_fn = _per_asset(px_fn)
    notes = _notes(conn)
    obs_at = {str(o): int(t) for o, t in conn.execute("SELECT obs_id, observed_at FROM raw_observations WHERE obs_id >= 'recon:' AND obs_id < 'recon;'")}
    out = []
    for row in conn.execute(_ROW_SQL):
        r = dict(zip(_ROW_KEYS, row))
        try:
            r["q"] = int(r["qb"]) / 10 ** int(r["dec"] if r["dec"] is not None else 8)
        except (TypeError, ValueError):
            continue
        r.update(sid=str(r["sid"]), sym=str(r["sym"] or ""), addr=str(r["addr"] or "").lower(), venue=_venue(r["loc"]), bts=_bts(r["sid"]))
        nt = notes.get(_oid((r["kind"], r["ns"], r["sid"], r["seq"])))
        r["note"] = nt[0] if nt else None
        r["site"] = (nt[0].get("site") if nt and nt[0].get("site") in SITES else None) or _site_of(r)
        if r["site"] == "K7f":
            r["site"] = "K8" if str(r["ns"]).endswith(":futpnl") else "K7"
        r["why"] = str(nt[0].get("why") or "") if nt else ""
        by_note = nt is not None and nt[0].get("site") in SITES
        r["made"] = nt[1] if by_note else r["bts"] if r["bts"] else obs_at.get(r["sid"], int(r["ts"]))
        r["t0_ref"] = obs_at.get(r["sid"], r["made"]) if r["site"] == "K4" else r["made"]
        r["px"] = _px_of(r, px, px_fn)
        r["usd"] = r["q"] * r["px"] if r["px"] is not None else None
        out.append(r)
    return out


def _cells_before(conn: sqlite3.Connection, cells: set) -> dict:
    out = {}
    for loc, aid, t in conn.execute("SELECT location, asset_id, min(event_ts) FROM postings WHERE leg_kind != 'opening' GROUP BY location, asset_id"):
        if (loc, aid) in cells:
            out[(loc, aid)] = int(t)
    return out


def _native_bal(conn: sqlite3.Connection, r: dict, cache: dict) -> list:
    rows = cache.get(r["loc"])
    if rows is None:
        rows = cache[r["loc"]] = [(int(qb) / 10 ** int(dec if dec is not None else 18), int(t), lk) for qb, t, lk, dec in conn.execute(
            "SELECT p.qty_base, p.event_ts, p.leg_kind, a.decimals FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
            " WHERE p.location=? AND a.kind='native' AND a.chain=?", (r["loc"], r["chain"]))]
    at = sum(v for v, t, _lk in rows if t <= int(r["ts"]))
    return [abs(at), abs(sum(v for v, _t, _lk in rows))] + [abs(v) for v, _t, lk in rows if lk == "opening"]


def _same(a: float, b: float) -> bool:
    return a >= 1e-6 and b >= 1e-6 and abs(a - b) <= 1e-9 * max(a, b)


def _mark_first(rows: list) -> dict:
    first_b = {}
    for r in rows:
        if r["site"] in ("K7", "K10") and r["bts"] is not None:
            first_b[r["venue"]] = min(first_b.get(r["venue"], r["bts"]), r["bts"])
    guess = {}
    for r in rows:
        by_ts = r["site"] in ("K7", "K10") and r["bts"] is not None and r["bts"] == first_b.get(r["venue"])
        known = r["why"] and r["site"] == "K7" and r["why"] != "fut_replace"
        r["first"] = (r["why"] == "first") if known else by_ts
        up_ws = r["site"] == "K10" and (r["why"] == "pos_window_start" or (r["bts"] is not None and r["ts"] < r["bts"] - 60))
        settle_ws = r["site"] == "K7" and r["why"] == "settle_pos"
        r["ws"] = r["q"] > 0 and (r["site"] in ("K1", "K2", "K4", "K5") or (r["site"] in ("K7", "K10") and r["first"]) or up_ws or settle_ws)
        r["red"], r["pair"] = None, None
        if r["ws"]:
            guess[r["venue"]] = min(guess.get(r["venue"], r["ts"]), r["ts"])
    return guess


def _pair_cell(lst: list) -> None:
    lst = [r for r in lst if r["site"] not in ("K8", "K9") and not r["ns"].endswith(":futpnl") and not r["sid"].startswith("exflate:")]
    neg = sorted((r for r in lst if r["q"] < 0), key=lambda r: r["made"])
    used, by_day = set(), {}
    for p in sorted((r for r in lst if r["q"] > 0), key=lambda r: r["made"]):
        n = next((n for n in neg if n["pid"] not in used and abs(p["made"] - n["made"]) <= PAIR_DAYS * DAY
                  and abs(p["q"] + n["q"]) <= PAIR_TOL * abs(p["q"])), None)
        if n is None:
            continue
        used.add(n["pid"])
        p["pair"], n["pair"] = n["pid"], p["pid"]
        if p["px"] is not None:
            by_day.setdefault(max(p["made"], n["made"]) // DAY, []).extend((p, n))
    for day_rows in by_day.values():
        if len(day_rows) >= 2 * FLIP_DAY_N:
            for r in day_rows:
                r["red"] = "flip3"


def _t0_of_row(r: dict, t0_fn: T0Fn, guess: dict) -> Optional[int]:
    got = None
    if t0_fn is not None:
        try:
            got = t0_fn(r["venue"], r["t0_ref"])
        except Exception as e:  # noqa: BLE001 [fallback]
            calcguard.swallowed("recon_adj:_t0_of_row", e)
            got = None
    return int(got) if got else guess.get(r["venue"])


def _red_shape(conn: sqlite3.Connection, r: dict, early: dict, cache: dict) -> None:
    first_like = r["ws"] or r["first"] or r["site"] in ("K1", "K2")
    e = early.get((r["loc"], r["aid"]))
    precedes = r["q"] > 0 and e is not None and int(r["ts"]) < e
    if r["red"] is None and first_like and r["t0"] and e is not None and e < r["t0"] - DAY and not precedes:
        r["red"] = "prewin_rows"
        return
    wallet_tok = r["akind"] == "token" and r["kind"] == "opening" and r["px"] is not None and str(r["loc"]).count(":") == 2 and r["chain"]
    if r["red"] is None and wallet_tok and any(_same(abs(r["q"]), b) for b in _native_bal(conn, r, cache)):
        r["red"] = "mirror"


def _cls_of(r: dict, gaps: dict) -> str:
    s, q = r["site"], r["q"]
    rules = (("spam", r["px"] is None), ("dust", r["usd"] is not None and abs(r["usd"]) < DUST_USD), ("futpnl", s == "K8" or r["ns"].endswith(":futpnl")),
             ("exflate", s == "K9" or r["sid"].startswith("exflate:")),
             ("tool", s == SITE_TOOL), ("interest", s == "K7" and r["seq"] == 2 and q < 0), ("pair", bool(r["pair"])),
             ("pre_window", r["ws"] and r["red"] != "prewin_rows"), ("new_source", r["why"] == "new_source"))
    hit = next((c for c, ok in rules if ok), None)
    if hit:
        return hit
    gap = gaps.get(r["venue"])
    return "estimated" if gap and (gap[0] is None or r["ts"] <= gap[0] + DAY) else "unexplained"


def classify(conn: sqlite3.Connection, rows: list, t0_fn: T0Fn = None, gaps: Optional[dict] = None) -> list:
    gaps = gaps or {}
    guess = _mark_first(rows)
    by_cell = {}
    for r in rows:
        by_cell.setdefault((r["loc"], r["aid"]), []).append(r)
    for lst in by_cell.values():
        _pair_cell(lst)
    early, cache = _cells_before(conn, set(by_cell)), {}
    for r in rows:
        r["t0"] = _t0_of_row(r, t0_fn, guess)
        _red_shape(conn, r, early, cache)
        r["cls"] = _cls_of(r, gaps)
        r["cause"] = (RED_CAUSE.get(r["red"], RED_KO.get(r["red"], str(r["red"]))) if r["red"] else gaps[r["venue"]][1] if r["cls"] == "estimated"
                      else HINTS.get(r["venue"], "") if r["cls"] == "unexplained" else CLS_KO[r["cls"]])
    return rows


def venue_values(conn: sqlite3.Connection, px: dict) -> dict:
    out = {}
    try:
        cur = conn.execute("SELECT group_id, location, qty_norm FROM positions").fetchall()
    except sqlite3.Error:
        return out
    for g, loc, qn in cur:
        unit = px["grp"].get(int(g)) if g is not None else None
        qty = _pos_float(qn)
        val = _pos_float(qty * unit) if unit is not None and qty is not None else None
        if val is not None:
            out[_venue(loc)] = out.get(_venue(loc), 0.0) + val
    return out


def _row_view(r: dict) -> dict:
    return {"venue": r["venue"], "loc": r["loc"], "sym": r["sym"], "q": r["q"], "usd": None if r["usd"] is None else round(r["usd"], 2),
            "ts": r["ts"], "made": r["made"], "site": r["site"], "why": r["why"], "cls": r["cls"], "red": r["red"], "cause": r.get("cause") or ""}


def _venue_table(rows: list, now: float, values: dict) -> dict:
    venues = {}
    for r in (x for x in rows if x["cls"] in ("unexplained", "estimated")):
        v = venues.setdefault(r["venue"], {"n": 0, "usd": 0.0, "n7": 0, "usd7": 0.0, "est_n": 0, "est_usd": 0.0,
                                           "value": round(values.get(r["venue"], 0.0), 2)})
        u = abs(r["usd"] or 0.0)
        pre = "est_" if r["cls"] == "estimated" else ""
        v[pre + "n"] += 1
        v[pre + "usd"] += u
        if not pre and now - r["made"] <= WEEK:
            v["n7"] += 1
            v["usd7"] += u
    for v in venues.values():
        for k in ("usd", "usd7", "est_usd"):
            v[k] = round(v[k], 2)
    return dict(sorted(venues.items(), key=lambda kv: -kv[1]["usd"]))


def _is_warn(r: dict, values: dict) -> bool:
    big = abs(r["usd"]) >= ROW_WARN_USD
    share = values.get(r["venue"], 0) > 0 and abs(r["usd"]) >= ROW_WARN_PCT * values[r["venue"]]
    return r["cls"] in ("unexplained", "estimated") and (big or share)


def summarize(rows: list, now: Optional[float] = None, values: Optional[dict] = None) -> dict:
    now = time.time() if now is None else now
    values = values or {}
    by_cls = {}
    for r in rows:
        b = by_cls.setdefault(r["cls"], {"n": 0, "usd": 0.0})
        b["n"] += 1
        b["usd"] = round(b["usd"] + abs(r["usd"] or 0.0), 2)
    une = [r for r in rows if r["cls"] == "unexplained"]
    une7 = [r for r in une if now - r["made"] <= WEEK]
    warn = [r for r in rows if now - r["made"] <= WEEK and r["usd"] is not None and _is_warn(r, values)]
    red = [r for r in rows if r["red"]]
    red_by = {}
    for r in red:
        red_by[r["red"]] = red_by.get(r["red"], 0) + 1

    def key(r):
        return -abs(r["usd"] or 0.0)
    doc = {"v": 1, "ts": int(now), "n_rows": len(rows),
            "unexplained": {"n": len(une), "usd": round(sum(abs(r["usd"] or 0) for r in une), 2),
                            "n7": len(une7), "usd7": round(sum(abs(r["usd"] or 0) for r in une7), 2)},
            "by_class": dict(sorted(by_cls.items())), "venues": _venue_table(rows, now, values),
            "top": [_row_view(r) for r in sorted(une, key=key)[:TOP_N]],
            "warn": [_row_view(r) for r in sorted(warn, key=key)[:20]], "warn_n": len(warn),
            "red": [_row_view(r) for r in sorted(red, key=key)[:20]], "red_n": len(red), "red_by": dict(sorted(red_by.items()))}
    doc["check"] = check(doc, now)
    return doc


def compute(conn: sqlite3.Connection, now: Optional[float] = None, t0_fn: T0Fn = None, state_dir: Optional[str] = None,
            px_fn: PxFn = None) -> tuple:
    px = prices(state_dir)
    rows = classify(conn, load_rows(conn, px, px_fn), t0_fn=t0_fn, gaps=coverage_gaps(state_dir))
    return rows, summarize(rows, now, venue_values(conn, px))


def refresh(conn: sqlite3.Connection, now: Optional[float] = None, t0_fn: T0Fn = None, px_fn: PxFn = None) -> dict:
    doc = compute(conn, now, t0_fn, None, px_fn)[1]
    statefile.atomic_write_json(paths.state(STATE_NAME), doc)
    return doc


def _t0_fn(win_t0: Callable[[int, str], int]) -> Callable[[str, int], int]:
    def f(venue: str, ref: int) -> int:
        return win_t0(ref, venue)
    return f


_TICK = {"t": 0.0, "fp": None, "checked": 0.0}


def tick(conn: sqlite3.Connection, win_t0: Callable[[int, str], int], log_: Optional[logging.Logger] = None, now: Optional[float] = None,
         st: Optional[dict] = None) -> Optional[dict]:
    now = time.time() if now is None else now
    st = _TICK if st is None else st
    if now - float(st.get("checked") or 0.0) < MIN_GAP_SEC:
        return None
    st["checked"] = now
    try:
        fp = tuple(conn.execute("SELECT count(*), coalesce(max(posting_id), 0) FROM postings WHERE leg_kind='opening'").fetchone())
        if fp == st.get("fp") and now - float(st.get("t") or 0.0) < REFRESH_SEC:
            return None
        doc = refresh(conn, now, _t0_fn(win_t0))
        st.update(t=now, fp=fp)
        return doc
    except Exception as e:  # noqa: BLE001 [boundary]
        calcguard.swallowed("recon_adj:tick", e)
        (log_ or log).warning("보정 감시 갱신 실패(다음 주기): %s", logs.safe_err(str(e))[:200])
        return None


def _fmt_row(r: dict) -> str:
    u = r.get("usd")
    head = f"{r.get('sym')} {r.get('venue')}" + (f" {'+' if (r.get('q') or 0) > 0 else '−'}${abs(u):,.0f}" if u is not None else "")
    where = SITES.get(r.get("site"), ("", "", "수리 도구 행"))[2].split("(")[0].split(" —")[0]
    return head + f"({where}{' · ' + r['cause'] if r.get('cause') else ''})"


def check(doc: object, now: Optional[float] = None) -> Optional[dict]:
    if not isinstance(doc, dict) or doc.get("v") != 1:
        return None
    une = doc.get("unexplained") or {}
    red_n, warn_n = int(doc.get("red_n") or 0), int(doc.get("warn_n") or 0)
    usd7, n7 = float(une.get("usd7") or 0), int(une.get("n7") or 0)
    ven = " · ".join(f"{k} {int(v.get('n7') or 0)}건 ${float(v.get('usd7') or 0):,.0f}" for k, v in (doc.get("venues") or {}).items() if v.get("n7"))
    tot = f"전체 설명 안 된 보정 {int(une.get('n') or 0)}건 ${float(une.get('usd') or 0):,.0f}"
    if red_n:
        kinds = " · ".join(f"{RED_KO.get(k, k)} {n}" for k, n in (doc.get("red_by") or {}).items())
        return {"title": f"보정 버그 꼴 {red_n}건", "level": "crit", "tg": True,
                "detail": f"{kinds} — " + " · ".join(_fmt_row(r) for r in (doc.get("red") or [])[:3]) + f" · {tot}",
                "action": "실잔고 대사가 넣은 보정 중 버그 모양(창 이전 행 되받기·네이티브 거울·하루 여러 번 뒤집기)이 있어요 — 그 칸의 수집 기록을 점검하세요"}
    if warn_n or usd7 >= WEEK_TG_USD:
        week = (f"7일 {n7}건 ${usd7:,.0f}" + (f" ({ven})" if ven else "") + " · ") if n7 else ""
        return {"title": f"설명 안 된 보정 7일 ${usd7:,.0f}" if n7 else f"보정 확인 {warn_n}건(추정)", "level": "warn", "tg": usd7 >= WEEK_TG_USD,
                "detail": week + " · ".join(_fmt_row(r) for r in (doc.get("warn") or doc.get("top") or [])[:3]) + f" · {tot}",
                "action": "원장이 모르는 입출금이 실잔고 대사로 메워졌어요 — 그 거래소·체인의 수집 범위(입출금·Earn·배당)와 지갑 등록을 확인하세요"}
    return {"title": "보정 감시", "level": "ok", "tg": False, "action": "",
            "detail": (f"7일 설명 안 된 보정 {n7}건 ${usd7:,.0f} · " if n7 else "7일 설명 안 된 큰 보정 없음 · ") + tot}


def exf_dm(conn: sqlite3.Connection, win_t0: Callable[[int, str], int], ex: str, bts: int, n_adj: int, dm_fn: Callable[[str, str], object],
           px_fn: PxFn = None) -> None:
    if n_adj <= 0:
        return
    try:
        rows = compute(conn, None, _t0_fn(win_t0), None, px_fn)[0]
    except Exception as e:  # noqa: BLE001 [fallback]
        calcguard.swallowed("recon_adj:exf_dm", e)
        dm_fn("EXF_RECON", f"{ex} 잔고 대사 완료 — {n_adj}개 통화 보정")
        return
    mine = [r for r in rows if r["venue"] == ex and r["bts"] == int(bts) and r["site"] == "K7" and (r["cls"] == "unexplained" or r["red"])]
    if not mine:
        return
    syms = {}
    for r in mine:
        syms[r["sym"]] = syms.get(r["sym"], 0.0) + (r["usd"] or 0.0)
    top = " · ".join(f"{s} {'+' if v >= 0 else '−'}${abs(v):,.0f}" for s, v in sorted(syms.items(), key=lambda kv: -abs(kv[1]))[:3])
    red_n = sum(1 for r in mine if r["red"])
    dm_fn("EXF_RECON", f"{ex} 잔고 대사 — 설명 안 된 {len(syms)}개 통화 보정 ${sum(abs(v) for v in syms.values()):,.0f}"
          + (f" · 버그 꼴 {red_n}건" if red_n else "") + f" ({top})")
