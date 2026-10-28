from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import time
from decimal import Decimal
from typing import Callable

import autofix as AF
import db as dbm
import paths
import recon_adj
import statefile

log = logging.getLogger("tj-core")

RAWSKIP = "exf_rawskip:"


class Refused(RuntimeError):
    pass


def _cur(conn, pid):
    r = conn.execute("SELECT " + ", ".join(AF.COLS) + " FROM postings WHERE posting_id=?", (int(pid),)).fetchone()
    return None if r is None else tuple(r)


def _same(conn, r: dict) -> bool:
    return _cur(conn, r["posting_id"]) == tuple(r[k] for k in AF.COLS)


def _mark(conn, r: dict, on: bool) -> None:
    ex_s, _, kd = str(r["source_ns"]).partition(":")
    if r["source_kind"] != "exchange" or not str(r["location"]).startswith("exchange:"):
        return
    if kd in ("deposit", "withdraw"):
        mkey = f"{RAWSKIP}{ex_s}:{kd}:{r['source_id']}"
        if on:
            conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (mkey, "autofix_v1"))
        else:
            conn.execute("DELETE FROM meta WHERE k=?", (mkey,))
    elif kd == "recon" and on and AF.bts_of(r["source_id"]) is not None:
        sym_s = str(r["source_id"])[len("exfrecon:"):].rsplit(":", 1)[0]
        conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)", (ex_s, sym_s.upper(), AF.bts_of(r["source_id"])))


def _group_sum(conn, gid, loc) -> Decimal:
    tot = Decimal(0)
    for r in conn.execute("SELECT p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE a.group_id=? AND p.location=?",
                          (gid, loc)).fetchall():
        tot += AF.norm(r[0], r[1])
    return tot


def _ser(conn, loc, sym) -> list:
    return AF.series(AF.cell_rows(conn, loc, sym))


def _cum_points(ser):
    out, run = [], Decimal(0)
    for tsv, q in ser:
        run += q
        out.append((tsv, run))
    return out


def _at(points, t) -> Decimal:
    v = Decimal(0)
    for tsv, conn_ro in points:
        if tsv > t:
            break
        v = conn_ro
    return v


def check_i2(before: list, after: list, t0: int, tau: int, floor: "Callable[[int], Decimal]", b0: "int | None" = None) -> str:
    pb, pa = _cum_points(before), _cum_points(after)
    ts_all = sorted({t for t, _ in before} | {t for t, _ in after} | {t0, tau})
    for t in ts_all:
        if b0 is not None and t0 <= t <= b0 and _at(pa, t) < floor(t) - AF.TOL:
            return f"I2 위반: 첫 대사 구간 시각 {t} 궤적이 바닥 아래"
        if t >= tau and _at(pa, t) != _at(pb, t):
            return f"I2 위반: τ 뒤 시각 {t} 궤적이 바뀜"
    return ""


def _late_pending(conn, ex: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM exf_late_pending WHERE ex=? AND substr(lb, 1, 5) != '@inc:' LIMIT 1", (ex,)).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def _receipt(cell: dict, now: int, undo_name) -> dict:
    add_row = (cell["setq"] or [r for r in cell["delete"] if r["source_ns"].endswith(":recon")] or [None])[0]
    anc = None if add_row is None else {"key": [add_row["source_ns"], add_row["source_id"], int(add_row["leg_seq"])], "qty0": str(add_row["qty_base"]),
                                   "row": {k: add_row[k] for k in AF.COLS}, "deleted": add_row not in cell["setq"]}
    add = cell["add"][0] if cell["add"] else None
    return {"v": AF.RECEIPT_V, "gid": cell["gid"], "kind": cell["kind"], "ex": cell["ex"], "sym": cell["sym"],
            "prewin": [{k: r[k] for k in AF.COLS} for r in cell["delete"] if not str(r["source_ns"]).endswith(":recon")],
            "anchor": anc, "auto": None if add is None else {"key": [add["source_ns"], add["source_id"], int(add["leg_seq"])], "qty": add["qty_base"]},
            "obs_b0": cell["obs_b0"], "t0": cell["t0"], "b0": cell["b0"], "tau": cell["tau"], "X": cell["X"], "U": cell["U"],
            "state": AF.ST_APPLIED if add is not None else AF.ST_RESOLVED, "at": int(now), "undo": undo_name}


def apply_cell(conn: "sqlite3.Connection", cell: dict, now: int, *, floor: "Callable | None" = None, undo_name: "str | None" = None,
               write_undo: "Callable | None" = None, touch: "Callable | None" = None) -> dict:
    if cell.get("kind") not in (AF.KIND_A, AF.KIND_A2):
        raise Refused(f"적용 대상 아님({cell.get('kind')} · {cell.get('why')})")
    if conn.in_transaction:
        raise Refused("열린 트랜잭션 위에서는 적용하지 않음")
    ex, sym = cell["ex"], cell["sym"]
    loc = f"exchange:{ex}"
    floor_fn = floor or (lambda t: Decimal(0))
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _late_pending(conn, ex):
            raise Refused("그 거래소 늦은 행 대기표가 남음(core 가 흡수한 뒤 다시)")
        if conn.execute("SELECT 1 FROM meta WHERE k=?", (f"autofix:{ex}:{sym}",)).fetchone() \
                or conn.execute("SELECT 1 FROM meta WHERE k=?", (AF.off_key(ex, sym),)).fetchone():
            raise Refused("이미 영수증·끄기 표식이 있는 칸")
        for r in cell["delete"] + cell["setq"]:
            if not _same(conn, r):
                raise Refused(f"pid {r['posting_id']}: 지금 행이 계획 때와 다름")
        for r in cell["add"]:
            if conn.execute("SELECT 1 FROM postings WHERE source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?",
                            (r["source_kind"], r["source_ns"], r["source_id"], int(r["leg_seq"]))).fetchone():
                raise Refused("같은 열쇠 자동 행이 이미 있음")
        sum0, ser0 = _group_sum(conn, cell["gid"], loc), _ser(conn, loc, sym)
        for r in cell["delete"]:
            if conn.execute("DELETE FROM postings WHERE posting_id=?", (int(r["posting_id"]),)).rowcount != 1:
                raise Refused(f"pid {r['posting_id']}: 지우기 실패")
            _mark(conn, r, True)
        for r in cell["setq"]:
            conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(int(r["set_qty"])), int(r["posting_id"])))
        for r in cell["add"]:
            conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                         " leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         tuple(r[k] for k in AF.COLS[1:]))
        if _group_sum(conn, cell["gid"], loc) != sum0:
            raise Refused("I1 위반: 그룹·위치 합이 바뀜")
        if cell["add"]:
            lim_ts, eq_ts = int(cell["b0"]), int(cell["add"][0]["event_ts"])
        elif int(cell["tau"]) > int(cell["t0"]):
            lim_ts, eq_ts = int(cell["tau"]) - 1, int(cell["tau"])
        else:
            lim_ts, eq_ts = None, int(cell["t0"])
        why_s = check_i2(ser0, _ser(conn, loc, sym), int(cell["t0"]), eq_ts, floor_fn, lim_ts)
        if why_s:
            raise Refused(why_s)
        rec = _receipt(cell, now, undo_name)
        conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (f"autofix:{ex}:{sym}", json.dumps(rec, ensure_ascii=False, sort_keys=True)))
        dbm.bump_data_rev(conn, 2)
        if cell["add"]:
            add_row = cell["add"][0]
            recon_adj.note(conn, "K11", (add_row["source_kind"], add_row["source_ns"], add_row["source_id"], int(add_row["leg_seq"])), why=str(cell["why"]),
                           ex=ex, sym=sym, tau=int(cell["tau"]), U=str(cell["U"]), gap=bool(cell.get("gap")))
        dbm.bump_daily_inval(conn)
        ts_min = min([int(r["event_ts"]) for r in cell["delete"] + cell["setq"] + cell["add"]])
        if touch is not None:
            touch(ts_min)
        if write_undo is not None:
            write_undo(rec)
        conn.commit()
        return rec
    except BaseException:
        conn.rollback()
        raise


def undo_cell(conn: "sqlite3.Connection", ex: str, sym: str, *, now: "int | None" = None, touch: "Callable | None" = None) -> dict:
    if conn.in_transaction:
        raise Refused("열린 트랜잭션 위에서는 되돌리지 않음")
    sym = str(sym).upper()
    loc = f"exchange:{ex}"
    conn.execute("BEGIN IMMEDIATE")
    try:
        meta_row = conn.execute("SELECT v FROM meta WHERE k=?", (AF.receipt_key(ex, sym),)).fetchone()
        if meta_row is None:
            raise Refused("이 칸 영수증 없음")
        try:
            rec = json.loads(meta_row[0])
            anc = rec.get("anchor") or {}
            prewin = list(rec.get("prewin") or [])
            obs_b0 = Decimal(str(rec["obs_b0"]))
            b0 = int(rec["b0"])
            gid = rec["gid"]
        except (TypeError, ValueError, KeyError, ArithmeticError) as e:
            raise Refused(f"영수증 해석 불가({type(e).__name__})") from e
        sum0 = _group_sum(conn, gid, loc)
        auto = rec.get("auto")
        if auto:
            conn.execute("DELETE FROM postings WHERE source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?",
                         (AF.SOURCE_KIND, auto["key"][0], auto["key"][1], int(auto["key"][2])))
        for r in prewin:
            if conn.execute("SELECT 1 FROM postings WHERE source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?",
                            (r["source_kind"], r["source_ns"], r["source_id"], int(r["leg_seq"]))).fetchone():
                raise Refused("같은 열쇠 행이 이미 있음(창 이전 행) — 되돌리기 전부 거부")
            pid_free = conn.execute("SELECT 1 FROM postings WHERE posting_id=?", (int(r["posting_id"]),)).fetchone() is None
            cols = AF.COLS if pid_free else AF.COLS[1:]
            conn.execute("INSERT INTO postings (" + ", ".join(cols) + ") VALUES (" + ",".join("?" * len(cols)) + ")", tuple(r[k] for k in cols))
            _mark(conn, r, False)
        s_b = sum(int(r["qty_base"]) for r in prewin)
        if anc:
            arow = anc["row"]
            dec = conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (int(arow["asset_id"]),)).fetchone()
            dec = None if dec is None else dec[0]
            mkey = (AF.SOURCE_KIND, anc["key"][0], anc["key"][1], int(anc["key"][2]))
            cur = conn.execute("SELECT posting_id FROM postings WHERE source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?", mkey).fetchone()
            rows = AF.cell_rows(conn, loc, sym)
            excl = frozenset({int(cur[0])} if cur else set()) | frozenset(int(r["posting_id"]) for r in rows if AF.is_auto_ns(r["source_ns"]))
            c_now = AF.cum_at(AF.series(rows, exclude=excl), b0) - AF.norm(s_b, dec)
            want = AF.to_base(obs_b0 - AF.norm(s_b, dec) - c_now, dec)
            if cur:
                conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(want), int(cur[0])))
            elif want != 0:
                cols = AF.COLS[1:]
                conn.execute("INSERT INTO postings (" + ", ".join(cols) + ") VALUES (" + ",".join("?" * len(cols)) + ")",
                             tuple(str(want) if k == "qty_base" else arow[k] for k in cols))
        if _group_sum(conn, gid, loc) != sum0:
            raise Refused("I1 위반: 되돌린 뒤 그룹·위치 합이 바뀜(지금 행과 영수증이 안 맞음) — 되돌리기 전부 거부")
        conn.execute("DELETE FROM meta WHERE k=?", (AF.receipt_key(ex, sym),))
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (AF.off_key(ex, sym), str(int(now or time.time()))))
        dbm.bump_daily_inval(conn)
        if touch is not None:
            touch(min([int(r["event_ts"]) for r in prewin] + [int(rec.get("t0") or b0)]))
        conn.commit()
        return rec
    except BaseException:
        conn.rollback()
        raise


def autofix_on(conn: "sqlite3.Connection", ex: str, sym: str) -> bool:
    n = conn.execute("DELETE FROM meta WHERE k=?", (AF.off_key(ex, sym),)).rowcount
    conn.commit()
    return n == 1


def data_rev_down(conn: "sqlite3.Connection", to: int = 1) -> str:
    if int(to) != 1:
        raise Refused("--data-rev-down 은 1 로만")
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = dbm.ledger_data_rev(conn)
        if cur != AF.DATA_REV:
            raise Refused(f"원장 data_rev {cur} — 2 일 때만 내림(3 이상 = 배포 롤백 도구 --ledger)")
        n_r = conn.execute("SELECT count(*) FROM meta WHERE k >= ? AND k < ?", (AF.RECEIPT, AF.RECEIPT[:-1] + ";")).fetchone()[0]
        n_a = conn.execute("SELECT count(*) FROM postings WHERE substr(source_ns, -8) = ':autofix'").fetchone()[0]
        if n_r or n_a:
            raise Refused(f"자동 처리 영수증 {n_r} · 자동 행 {n_a} — 먼저 --undo-autofix 전부")
        conn.execute("UPDATE meta SET v='1' WHERE k='data_rev'")
        conn.commit()
        return "data_rev 2 → 1"
    except BaseException:
        conn.rollback()
        raise


def undo_file(ex: str, sym: str, now: int) -> str:
    return f"autofix_undo_{_safe(ex)}_{_safe(str(sym).upper())}_{time.strftime('%Y%m%d%H%M%S', time.gmtime(now))}_{secrets.token_hex(4)}.json"


def _safe(v: object) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", str(v))[:40] or "-"


def write_undo_fn(path: str):
    def _w(rec):
        statefile.atomic_write_json(path, {"kind": UNDO_KIND, "applied": True, "receipt": rec})
    return _w


UNDO_KIND = "autofix_undo_v1"
CORE_WAIT_S = 72 * 3600
ACK = "ack"


def big_why(conn: "sqlite3.Connection", cell: dict, px: "dict | None" = None, values: "dict | None" = None) -> str:
    if not cell.get("add"):
        return ""
    px = recon_adj.prices() if px is None else px
    values = recon_adj.venue_values(conn, px, strict=True) if values is None else values
    add = cell["add"][0]
    a_row = conn.execute("SELECT kind, symbol, decimals, group_id FROM assets WHERE asset_id=?", (int(add["asset_id"]),)).fetchone()
    if a_row is None:
        return "큰 칸 판정 불가(자산 없음)"
    unit = 1.0 if (a_row[0] == "exchange_currency" and str(a_row[1] or "").upper() in recon_adj.STABLES) else \
        px["grp"].get(int(a_row[3])) if a_row[3] is not None else None
    u_norm = AF.norm(cell["U"], a_row[2])
    if unit is None:
        return f"큰 칸(U {u_norm:f} {cell['sym']} 단가 모름 = 평가 불가) — 사람이 확인(해킹·미등록 출금일 수 있음)"
    usd = float(u_norm) * float(unit)
    val = float(values.get(cell["ex"], 0.0) or 0.0)
    if usd >= recon_adj.ROW_WARN_USD or (val > 0 and usd >= recon_adj.ROW_WARN_PCT * val):
        return (f"큰 칸(U 평가액 ${usd:,.0f} ≥ ${recon_adj.ROW_WARN_USD:,.0f} 또는 {cell['ex']} 평가액 ${val:,.0f} 의 {recon_adj.ROW_WARN_PCT:.0%})"
                " — 사람이 확인(해킹·미등록 출금일 수 있음)")
    return ""


def core_guard(svc: object, ex: str, st_ex: dict, now: int) -> str:
    if not ((st_ex.get("fills") or {}).get("backfilled_until")):
        return "체결 백필 미완료"
    if svc._exf_late_pending(ex):
        return "늦은 행 대기 중"
    ext_st = st_ex.get("ext")
    if isinstance(ext_st, dict) and ext_st.get("target") and not svc._exf_ext_done(ext_st):
        return "과거 창 확장 진행 중"
    if svc._exf_ext_settling(ex, st_ex, svc._meta_get(f"recon_done_exf_{ex}")) is not None:
        return "과거 창 확장 정착 중"
    b0 = svc._exf_first_bts(ex)
    if b0 is None or now - int(b0) < CORE_WAIT_S:
        return "첫 대사 뒤 72시간 전"
    return ""


def core_pass(svc: object, now: "int | None" = None) -> int:
    if not AF.enabled(svc.cfg):
        return 0
    now = int(now or time.time())
    if svc.conn.in_transaction:
        log.warning("자동 처리 건너뜀(이번 주기): core 연결에 열린 트랜잭션이 있음 — 남의 변경을 커밋하지 않음 · 다음 주기에 다시")
        return 0
    st_all = statefile.read_json(paths.state("exf_state.json"), {}) or {}
    floor = AF.debt_floor_fn()
    px = recon_adj.prices()
    try:
        values = recon_adj.venue_values(svc.conn, px, strict=True)
    except sqlite3.Error as e:
        log.warning("자동 처리 건너뜀(이번 주기): 장소 평가액(positions) 읽기 실패 — 큰 칸 판정 불가 · 다음 주기에 다시: %s", e)
        return 0
    n = 0
    for ex in sorted(k for k in st_all if isinstance(st_all.get(k), dict)):
        why = core_guard(svc, ex, st_all[ex], now)
        if why:
            continue
        for cell in AF.plan_ex(svc.conn, ex, AF.venue_gap, floor, now, svc):
            if cell["kind"] not in (AF.KIND_A, AF.KIND_A2):
                continue
            why_big = big_why(svc.conn, cell, px, values)
            if why_big:
                log.warning("자동 처리 %s %s 건너뜀(원장 무변): %s · 처리하려면 tj-core 정지 뒤 tools/ledger_rowfix.py --kind autofix_ws --apply --allow-big",
                            ex, cell["sym"], why_big)
                continue
            stamp, tag = time.strftime("%Y%m%d%H%M%S", time.gmtime(now)), secrets.token_hex(4)
            path = paths.state(f"autofix_undo_{_safe(ex)}_{_safe(str(cell['sym']).upper())}_{stamp}_{tag}.json")
            name = os.path.basename(path)
            try:
                apply_cell(svc.conn, cell, now, floor=lambda t, _e=ex, _s=cell["sym"]: floor(_e, _s, t), undo_name=name,
                           write_undo=write_undo_fn(path), touch=svc._exf_hist_touch)
                n += 1
                log.warning("자동 처리 %s %s(%s) 적용 — 되돌리기 = tools/ledger_rowfix.py --undo-autofix %s:%s", ex, cell["sym"], cell["kind"], ex, cell["sym"])
            except Refused as e:
                log.error("자동 처리 %s %s 거부(원장 무변): %s", ex, cell["sym"], e)
            except BaseException:
                if os.path.exists(path):
                    statefile.atomic_write_json(path, {"kind": UNDO_KIND, "applied": False, "plan": {k: cell[k] for k in ("ex", "sym", "kind")}})
                raise
        svc._exf_hist_flush()
    return n


def _pos_add(conn, gid, loc: str, delta: Decimal) -> None:
    from decimal import localcontext
    row = conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (gid, loc)).fetchone()
    if row is None:
        raise Refused(f"그룹 {gid} 위치 {loc} 포지션 없음")
    with localcontext() as ctx:
        ctx.prec = 100
        conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", (format(Decimal(row[0]) + delta, "f"), gid, loc))


def _key_row(conn, key):
    return conn.execute("SELECT posting_id, qty_base, event_ts FROM postings WHERE source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?",
                        (AF.SOURCE_KIND, key[0], key[1], int(key[2]))).fetchone() if key else None


def _replan(conn, ex: str, sym: str, rec: dict, late: tuple, now: int, floor) -> dict:
    loc = f"exchange:{ex}"
    w, n_legs = late
    t0, b0, gid = int(rec["t0"]), int(rec["b0"]), rec["gid"]
    anc, auto = rec.get("anchor") or {}, rec.get("auto") or {}
    akey = anc.get("key")
    ukey = auto.get("key") or [AF.auto_ns(ex), AF.auto_sid(sym, b0), AF.LEG_SEQ]
    arow, urow = _key_row(conn, akey), _key_row(conn, ukey)
    dec = conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (int(anc["row"]["asset_id"]),)).fetchone()[0]
    rows = AF.cell_rows(conn, loc, sym)
    if {r["group_id"] for r in rows} != {gid}:
        raise Refused("재계획 거부(칸 안 자산 그룹이 영수증 그룹 하나가 아님)")
    excl = frozenset(int(r[0]) for r in (arow, urow) if r is not None)
    ser = AF.series(rows, exclude=excl)
    O2 = Decimal(str(rec["obs_b0"])) - AF.cum_at(ser, b0)
    sol = AF.solve(O2, ser, t0, b0, floor)
    if "why" in sol:
        raise Refused(f"재계획 거부({sol['why']})")
    O2b, X_b = AF.to_base(O2, dec), AF.to_base(sol["X"], dec)
    if AF.norm(O2b, dec) != O2:
        raise Refused("재계획 거부(관측 잔고가 자리수에 안 맞음)")
    U_b = X_b - O2b
    if U_b < 0:
        raise Refused("재계획 거부(U < 0)")
    sum0, ser0 = _group_sum(conn, gid, loc), AF.series(rows)
    if X_b > 0 and arow is not None:
        conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(X_b), int(arow[0])))
    elif X_b > 0:
        conn.execute("INSERT INTO postings (" + ", ".join(AF.COLS[1:]) + ") VALUES (" + ",".join("?" * (len(AF.COLS) - 1)) + ")",
                     tuple(str(X_b) if k == "qty_base" else anc["row"][k] for k in AF.COLS[1:]))
    elif arow is not None:
        conn.execute("DELETE FROM postings WHERE posting_id=?", (int(arow[0]),))
        _mark(conn, dict(anc["row"]), True)
    if U_b > 0 and urow is not None:
        conn.execute("UPDATE postings SET qty_base=?, event_ts=? WHERE posting_id=?", (str(-U_b), AF.row_ts(int(sol["tau"]), b0), int(urow[0])))
    elif U_b > 0:
        conn.execute("INSERT INTO postings (" + ", ".join(AF.COLS[1:]) + ") VALUES (" + ",".join("?" * (len(AF.COLS) - 1)) + ")",
                     (AF.SOURCE_KIND, ukey[0], ukey[1], int(ukey[2]), AF.row_ts(int(sol["tau"]), b0), int(anc["row"]["asset_id"]), loc, str(-U_b), None, None,
                      AF.LEG_KIND, AF.EVENT, anc["row"]["classifier_ver"]))
    elif urow is not None:
        conn.execute("DELETE FROM postings WHERE posting_id=?", (int(urow[0]),))
    delta = _group_sum(conn, gid, loc) - sum0
    if abs(delta + w) > Decimal(n_legs * 2) / (Decimal(10) ** (8 if dec is None else int(dec))):
        raise Refused("I1-late 위반: 그룹 합 ≠ 늦은 행 직전")
    _pos_add(conn, gid, loc, delta)
    ser1 = _ser(conn, loc, sym)
    pb, pa = _cum_points(ser0), _cum_points(ser1)
    for t in sorted({t for t, _ in ser0} | {t for t, _ in ser1} | {t0, b0}):
        if t0 <= t <= b0 and _at(pa, t) < floor(t) - AF.TOL:
            raise Refused(f"I2 위반(재계획): 시각 {t}")
        if t > b0 and _at(pa, t) != _at(pb, t) + delta:
            raise Refused(f"I1-late 위반: 첫 대사 뒤 시각 {t} 궤적")
    old_u = int(str(rec.get("U") or "0"))
    rec = dict(rec, X=str(X_b), U=str(U_b), tau=int(sol["tau"]), state=AF.ST_APPLIED if U_b > 0 else AF.ST_RESOLVED, late_at=int(now),
               auto={"key": list(ukey), "qty": str(-U_b)} if U_b > 0 else None,
               anchor=dict(anc, deleted=X_b == 0))
    if U_b > old_u:
        rec.pop(ACK, None)
    conn.execute("UPDATE meta SET v=? WHERE k=?", (json.dumps(rec, ensure_ascii=False, sort_keys=True), AF.receipt_key(ex, sym)))
    if U_b > old_u:
        recon_adj.note(conn, "K11", (AF.SOURCE_KIND, ukey[0], ukey[1], int(ukey[2])), why="늦은 행 재계획 — 미확인 유출 커짐",
                       ex=ex, sym=sym, tau=int(sol["tau"]), U=str(U_b), gap=False)
    dbm.bump_daily_inval(conn)
    return rec


def late_take(conn: "sqlite3.Connection", ex: str, sym: str, lst: list, touch: "Callable | None" = None, now: "int | None" = None) -> list:
    meta_row = conn.execute("SELECT v FROM meta WHERE k=?", (AF.receipt_key(ex, sym),)).fetchone()
    if meta_row is None:
        return lst
    try:
        rec = json.loads(meta_row[0])
        t0, b0 = int(rec["t0"]), int(rec["b0"])
    except (TypeError, ValueError, KeyError):
        return lst
    inwin = [(t, a) for t, a in lst if t0 <= int(t) <= b0]
    if not inwin or rec.get("state") not in AF.STATES or not rec.get("anchor"):
        return lst
    fl = AF.debt_floor_fn()
    conn.execute("SAVEPOINT autofix_late")
    try:
        _replan(conn, ex, sym.upper(), rec, (sum((Decimal(a) for _t, a in inwin), Decimal(0)), len(inwin)), int(now or time.time()),
                lambda t: fl(ex, sym, t))
    except (Refused, ArithmeticError, KeyError, TypeError, ValueError) as e:
        conn.execute("ROLLBACK TO autofix_late")
        conn.execute("RELEASE autofix_late")
        log.warning("자동 처리 칸 %s %s 늦은 행 재계획 못 함(종전 흡수로 · 원장 그 칸 무변): %s", ex, sym, e)
        return lst
    conn.execute("RELEASE autofix_late")
    if touch is not None:
        touch(min([int(rec["t0"])] + [int(t) for t, _a in inwin]))
    log.warning("자동 처리 칸 %s %s 늦은 행 %d건 = 칸 재계획(앵커·자동 행 고쳐 씀)", ex, sym, len(inwin))
    return [(t, a) for t, a in lst if not (t0 <= int(t) <= b0)]
