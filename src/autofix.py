from __future__ import annotations

import calendar
import json
import time
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import sqlite3

import acct_norm
import config
import paths
import statefile

DATA_REV = 2

SOURCE_KIND = "exchange"
NS_SUFFIX = ":autofix"
SID_HEAD = "exfauto:"
EVENT = "EXF_ADJUST"
LEG_KIND = "opening"
LEG_SEQ = 0

RECEIPT = "autofix:"
OFF = "autofix_off:"
RECEIPT_V = 1
ST_APPLIED, ST_RESOLVED = "applied", "resolved"
STATES = (ST_APPLIED, ST_RESOLVED)
RECEIPT_KEYS = ("v", "gid", "prewin", "anchor", "auto", "obs_b0", "tau", "X", "U", "state", "at", "undo")

KIND_A, KIND_A2, KIND_B, KIND_SKIP = "A", "A'", "B", "skip"
PLAN_KEYS = ("ex", "sym", "gid", "kind", "why", "delete", "setq", "add", "tau", "X", "U", "gap")

CFG = "autofix"

COLS = ("posting_id", "source_kind", "source_ns", "source_id", "leg_seq", "event_ts", "asset_id", "location", "qty_base",
        "cost_usd", "cost_krw", "leg_kind", "event", "classifier_ver")
TOL = Decimal("0.00000001")

SKIP_WHY = {"anchor": "거래소 첫 대사의 이 칸 앵커 없음·여러 줄", "late_obs": "창 이전 행 원본 관측이 첫 대사 뒤",
            "after_t0": "첫 대사 앵커가 창 시작 뒤", "split": "한 원본의 레그가 남는 칸에 걸침", "group": "칸 안 자산 그룹·자산이 둘 이상",
            "floor_end": "바닥 아래로 첫 대사 구간이 끝남(관측 잔고와 어긋남)", "fut": "선물 정산 이관 미완료", "now_sym": "무기한 현금·원장 밖 통화",
            "off": "오너가 자동 처리를 끈 칸(autofix_off)", "done": "이미 자동 처리됨(영수증 있음)", "inwin": "창 이전 행 없음 · 창 안 바닥 아래(2-7 제외)"}
WHY_GAP = "기록 종류별 창 차이 구간(창 시작~그 종류 수집 시작)의 매수·수수료에 쓴 것으로 추정 — 미등록 출금·해킹일 수도 있음(거래소 출금·이체 기록 확인)"
WHY_UNKNOWN = "원인 모름 — 창 안 미확인 유출"


def auto_ns(ex: str) -> str:
    return f"{ex}{NS_SUFFIX}"


def is_auto_ns(ns: object) -> bool:
    return str(ns or "").endswith(NS_SUFFIX)


def auto_sid(sym: str, b0: int) -> str:
    return f"{SID_HEAD}{str(sym).upper()}:{int(b0)}"


def parse_sid(sid: object):
    sid_s = str(sid or "")
    if not sid_s.startswith(SID_HEAD):
        return None
    sym_s, _, bts_s = sid_s[len(SID_HEAD):].rpartition(":")
    try:
        return (sym_s.upper(), int(bts_s)) if sym_s else None
    except ValueError:
        return None


def receipt_key(ex: str, sym: str) -> str:
    return f"{RECEIPT}{ex}:{str(sym).upper()}"


def off_key(ex: str, sym: str) -> str:
    return f"{OFF}{ex}:{str(sym).upper()}"


def enabled(cfg: object) -> bool:
    return config.autofix_enabled(cfg)


def read_receipts(conn: "sqlite3.Connection") -> dict:
    out = {}
    for mkey, val in conn.execute("SELECT k, v FROM meta WHERE k >= ? AND k < ?", (RECEIPT, RECEIPT[:-1] + ";")).fetchall():
        ex_s, _, sym_s = str(mkey)[len(RECEIPT):].partition(":")
        try:
            obj = json.loads(val)
        except (TypeError, ValueError):
            obj = None
        out[(ex_s, sym_s.upper())] = obj if isinstance(obj, dict) else {"state": None}
    return out


def _ymd_ts(s):
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return int(s)
    try:
        return int(calendar.timegm(time.strptime(str(s)[:10], "%Y-%m-%d")))
    except (TypeError, ValueError):
        return None


def venue_gap(conn: "sqlite3.Connection", ex: str, now: int, st_ex: "dict | None" = None, t0: "int | None" = None) -> list:
    if ex != "okx":
        return []
    if st_ex is None:
        st_ex = (statefile.read_json(paths.state("exf_state.json"), {}) or {}).get(ex) or {}
    ext_st = (st_ex or {}).get("ext") if isinstance(st_ex, dict) else None
    full_ts = _ymd_ts((ext_st or {}).get("fills_from")) if isinstance(ext_st, dict) else None
    if t0 is None and conn is not None:
        row = conn.execute("SELECT min(event_ts) FROM postings WHERE source_ns=? AND event=? AND leg_kind=?", (f"{ex}:recon", EVENT, LEG_KIND)).fetchone()
        t0 = int(row[0]) if row and row[0] is not None else None
    if full_ts is None or t0 is None or full_ts <= int(t0):
        return []
    return [{"kind": "fills", "t0": int(t0), "full_t0": int(full_ts), "why": "OKX 현물 체결 보존 기한(달력 3개월) — 창 시작~체결 수집 시작 구간은 체결 없음"}]


def debt_floor_fn(state_dir: "str | None" = None):
    cache = {}

    def _load(ex):
        if ex not in cache:
            path = paths.state(f"exf_balances_{ex}.json") if state_dir is None else f"{state_dir}/exf_balances_{ex}.json"
            bd = statefile.read_json(path, {}) or {}
            dd = bd.get("debts") if isinstance(bd.get("debts"), dict) else {}
            fl = {}
            for ln in (bd.get("loans") if isinstance(bd.get("loans"), list) else ()):
                if not isinstance(ln, dict) or not ln.get("since"):
                    continue
                for sid_s in (ln.get("debt") or ()):
                    try:
                        val = Decimal(str(dd.get(sid_s, dd.get(str(sid_s).upper()))))
                        since_ts = int(ln["since"])
                    except (ArithmeticError, TypeError, ValueError):
                        continue
                    if val < 0:
                        mkey = str(sid_s).upper()
                        fl[mkey] = (min(since_ts, fl[mkey][0]) if mkey in fl else since_ts, val)
            cache[ex] = fl
        return cache[ex]

    def floor(ex, sym, t):
        fl_v = _load(ex).get(str(sym).upper())
        return fl_v[1] if fl_v and int(t) >= fl_v[0] else Decimal(0)
    return floor


def norm(qb: object, dec: object) -> Decimal:
    return Decimal(int(qb)) / (Decimal(10) ** (8 if dec is None else int(dec)))


def series(rows: list, exclude: frozenset = frozenset()) -> list:
    agg = {}
    for r in rows:
        if int(r["posting_id"]) in exclude:
            continue
        tt = int(r["event_ts"])
        agg[tt] = agg.get(tt, Decimal(0)) + norm(r["qty_base"], r["decimals"])
    return sorted(agg.items())


def cum_at(ser: list, t: int) -> Decimal:
    return sum((q for tsv, q in ser if tsv <= t), Decimal(0))


def solve(O: Decimal, ser: list, t0: int, b0: int, floor: "Callable[[int], Decimal]") -> dict:
    pts = [t0] + sorted({tsv for tsv, _q in ser if t0 < tsv <= b0})
    cum = {}
    run = sum((q for tsv, q in ser if tsv <= t0), Decimal(0))
    cum[t0] = run
    for tsv, q in ser:
        if t0 < tsv <= b0:
            run += q
            cum[tsv] = run
    last = None
    for p in pts:
        if O + cum[p] < floor(p) - TOL:
            last = p
    obs_b0 = O + cum_at(ser, b0)
    if last is None:
        if O >= 0:
            return {"tau": t0, "X": O, "U": Decimal(0), "obs_b0": obs_b0}
        return {"tau": t0, "X": Decimal(0), "U": -O, "obs_b0": obs_b0}
    nxt = [p for p in pts if p > last]
    if not nxt:
        return {"why": "floor_end", "obs_b0": obs_b0}
    tau = nxt[0]
    X = max([Decimal(0), O] + [floor(p) - cum[p] for p in pts if p < tau])
    return {"tau": tau, "X": X, "U": X - O, "obs_b0": obs_b0}


AUTO_DT = 1


def row_ts(tau: int, b0: int) -> int:
    return int(tau) + AUTO_DT


def cell_rows(conn: "sqlite3.Connection", loc: str, sym: str) -> list:
    cur = conn.execute(
        "SELECT " + ", ".join("p." + c for c in COLS) + ", a.decimals, a.group_id FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
        " WHERE p.location=? AND upper(a.symbol)=?", (loc, str(sym).upper()))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, tuple(r))) for r in cur.fetchall()]


def bts_of(sid: object):
    sid_s = str(sid or "")
    if not sid_s.startswith("exfrecon:"):
        return None
    try:
        return int(sid_s.rsplit(":", 1)[1])
    except ValueError:
        return None


def to_base(x: Decimal, dec: object) -> int:
    return int((x * (Decimal(10) ** (8 if dec is None else int(dec)))).to_integral_value(rounding=ROUND_CEILING))


def _fut_hold(win, ex) -> bool:
    if win._meta_get(f"recon_done_exf_{ex}"):
        place_st, scope = win._exf_fut_place_scope()
        return place_st != "done" and (scope is None or ex in scope)
    return False


def _strip(r: dict) -> dict:
    return {k: r[k] for k in COLS}


def plan_ex(conn: "sqlite3.Connection", ex: str, venue_gap: "Callable | None", debt_floor: "Callable | None", now: int, win: object,
            receipts: "dict | None" = None) -> list:
    b0 = win._exf_first_bts(ex)
    if b0 is None:
        return []
    t0 = int(win._exf_open_ts(ex, b0))
    loc = f"exchange:{ex}"
    rec = read_receipts(conn) if receipts is None else receipts
    gaps = venue_gap(conn, ex, now, t0=t0) if venue_gap else []
    pre = [dict(r) for r in conn.execute(
        "SELECT " + ", ".join("p." + c for c in COLS) + ", upper(a.symbol) AS sym FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
        " WHERE p.source_kind='exchange' AND p.source_ns IN (?, ?) AND p.location=? AND p.event_ts < ?",
        (f"{ex}:deposit", f"{ex}:withdraw", loc, t0)).fetchall()]
    by = {}
    for r in pre:
        by.setdefault(r["sym"], []).append(r)
    fut = _fut_hold(win, ex)
    out = []
    multi = set()
    for r in pre:
        for leg in conn.execute("SELECT p.location, upper(a.symbol) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind=? AND p.source_ns=?"
                                " AND p.source_id=?", ("exchange", r["source_ns"], r["source_id"])).fetchall():
            if tuple(leg) != (loc, r["sym"]):
                multi.add(r["sym"])
    for sym in sorted(by):
        if sym in multi:
            out.append(_skip(ex, sym, None, "split"))
            continue
        out.append(_plan_cell(conn, {"ex": ex, "b0": b0, "t0": t0, "gaps": gaps, "floor": debt_floor, "win": win, "rec": rec, "fut": fut}, sym, by[sym]))
    while True:
        kept = {(r["source_ns"], r["source_id"]) for c in out if c["kind"] == KIND_SKIP for r in by.get(c["sym"], ())}
        bad = [c for c in out if c["kind"] != KIND_SKIP and any((r["source_ns"], r["source_id"]) in kept for r in c["delete"])]
        if not bad:
            break
        for c in bad:
            c.update(kind=KIND_SKIP, why="split", delete=[], setq=[], add=[])
    return out


def _skip(ex, sym, gid, why, **kw):
    d = {"ex": ex, "sym": sym, "gid": gid, "kind": KIND_SKIP, "why": why, "delete": [], "setq": [], "add": [], "tau": None, "X": None, "U": None, "gap": None}
    d.update(kw)
    return d


def _plan_cell(conn, cx: dict, sym: str, pre: list) -> dict:
    ex, b0, t0, gaps, debt_floor, win, rec, fut = (cx[k] for k in ("ex", "b0", "t0", "gaps", "floor", "win", "rec", "fut"))
    loc = f"exchange:{ex}"
    if (ex, sym) in rec:
        return _skip(ex, sym, None, "done")
    if conn.execute("SELECT 1 FROM meta WHERE k=?", (off_key(ex, sym),)).fetchone():
        return _skip(ex, sym, None, "off")
    if sym in acct_norm.ex_off_ledger(ex) or win._exf_now_sym(ex, sym):
        return _skip(ex, sym, None, "now_sym")
    if fut:
        return _skip(ex, sym, None, "fut")
    rows = cell_rows(conn, loc, sym)
    gids = {r["group_id"] for r in rows}
    gid = next(iter(gids)) if len(gids) == 1 else None
    anc = [r for r in rows if r["source_ns"] == f"{ex}:recon" and r["leg_kind"] == LEG_KIND and r["event"] == EVENT and bts_of(r["source_id"]) is not None]
    first = [r for r in anc if bts_of(r["source_id"]) == b0]
    if len(first) != 1 or min(bts_of(r["source_id"]) for r in anc) != b0:
        return _skip(ex, sym, gid, "anchor")
    a = first[0]
    if gid is None or not gid or any(int(r["asset_id"]) != int(a["asset_id"]) for r in pre):
        return _skip(ex, sym, gid, "group")
    for r in pre:
        obs_at = conn.execute("SELECT min(observed_at) FROM raw_ex WHERE exchange=? AND kind=? AND uuid=?",
                          (ex, str(r["source_ns"]).split(":", 1)[1], r["source_id"])).fetchone()[0]
        if obs_at is None or int(obs_at) >= b0:
            return _skip(ex, sym, gid, "late_obs")
    dec = a["decimals"]
    s_b = sum(int(r["qty_base"]) for r in pre)
    O_b = s_b + int(a["qty_base"])
    olds = {int(r["posting_id"]) for r in pre} | {int(a["posting_id"])} | {int(r["posting_id"]) for r in rows if is_auto_ns(r["source_ns"])}
    ser = series(rows, exclude=frozenset(olds))
    deln = [_strip(r) for r in sorted(pre, key=lambda x: int(x["posting_id"]))]
    if int(a["event_ts"]) > t0:
        if O_b == 0:
            return {"ex": ex, "sym": sym, "gid": gid, "kind": KIND_A2, "why": "pair", "delete": deln + [_strip(a)], "setq": [], "add": [],
                    "tau": int(a["event_ts"]), "X": "0", "U": "0", "gap": None, "t0": t0, "b0": b0, "s": str(s_b), "a": str(a["qty_base"]),
                    "obs_b0": str(norm(O_b, dec) + cum_at(ser, b0))}
        return _skip(ex, sym, gid, "after_t0")
    base = {"ex": ex, "sym": sym, "gid": gid, "t0": t0, "b0": b0, "s": str(s_b), "a": str(a["qty_base"]),
            "obs_b0": str(norm(O_b, dec) + cum_at(ser, b0)), "gap": None}
    if O_b >= 0:
        if O_b == 0:
            return base | {"kind": KIND_A2, "why": "pair", "delete": deln + [_strip(a)], "setq": [], "add": [], "tau": t0, "X": "0", "U": "0"}
        return base | {"kind": KIND_A2, "why": "setq", "delete": deln, "setq": [_strip(a) | {"set_qty": str(O_b)}], "add": [],
                       "tau": t0, "X": str(O_b), "U": "0"}
    floor = (lambda t: debt_floor(ex, sym, t)) if debt_floor else (lambda t: Decimal(0))
    sol = solve(norm(O_b, dec), ser, t0, b0, floor)
    if "why" in sol:
        return _skip(ex, sym, gid, sol["why"])
    X_b = to_base(sol["X"], dec)
    U_b = X_b - O_b
    if U_b <= 0:
        return _skip(ex, sym, gid, "floor_end")
    base |= {"tau": int(sol["tau"]), "X": str(X_b), "U": str(U_b), "obs_b0": str(sol["obs_b0"])}
    gap = next((g for g in gaps if g["t0"] <= int(sol["tau"]) < g["full_t0"]), None)
    add = {"source_kind": SOURCE_KIND, "source_ns": auto_ns(ex), "source_id": auto_sid(sym, b0), "leg_seq": LEG_SEQ,
           "event_ts": row_ts(int(sol["tau"]), b0), "asset_id": int(a["asset_id"]), "location": loc, "qty_base": str(-U_b), "cost_usd": None,
           "cost_krw": None, "leg_kind": LEG_KIND, "event": EVENT, "classifier_ver": a["classifier_ver"]}
    if X_b == 0:
        dl, sq = deln + [_strip(a)], []
    else:
        dl, sq = deln, [_strip(a) | {"set_qty": str(X_b)}]
    return base | {"kind": KIND_A, "why": WHY_GAP if gap else WHY_UNKNOWN, "delete": dl, "setq": sq, "add": [add],
                   "gap": dict(gap) if gap else None}


def plan_cells(conn: "sqlite3.Connection", venue_gap: "Callable | None", debt_floor: "Callable | None", now: int, *, win: object = None,
               exs: "list | None" = None) -> list:
    if win is None:
        raise ValueError("plan_cells: win(core 창 규칙) 필요")
    if exs is None:
        exs = sorted({str(r[0]).rsplit(":", 1)[0] for r in conn.execute(
            "SELECT DISTINCT source_ns FROM postings WHERE source_kind='exchange' AND source_ns LIKE '%:recon' AND event=?", (EVENT,))})
    rec = read_receipts(conn)
    out = []
    for ex in exs:
        out.extend(plan_ex(conn, ex, venue_gap, debt_floor, now, win, rec))
    return out
