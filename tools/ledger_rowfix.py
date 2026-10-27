#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import secrets
import time
from decimal import Decimal, localcontext

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import chaincatalog, histmark, paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import ledger_lock  # noqa: E402
from exf_fix_place import _core_stopped, _planner  # noqa: E402

COLS = ("posting_id", "source_kind", "source_ns", "source_id", "leg_seq", "event_ts", "asset_id", "location", "qty_base",
        "cost_usd", "cost_krw", "leg_kind", "event", "classifier_ver")
KIND = "ledger_rowfix_v1"


def _ro():
    c = sqlite3.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def plan_mirror_open(conn):
    rows = []
    aids = set()
    q = ("SELECT p.posting_id, p.source_kind, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.asset_id, p.location, p.qty_base,"
         " p.cost_usd, p.cost_krw, p.leg_kind, p.event, p.classifier_ver, a.chain AS a_chain, a.address AS a_ca"
         " FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
         " WHERE a.kind='token' AND a.address IS NOT NULL AND p.source_kind='opening' AND p.leg_kind='opening' ORDER BY p.posting_id")
    for r in conn.execute(q).fetchall():
        if str(r["a_ca"]).lower() in chaincatalog.not_token_cas(str(r["a_chain"] or "")):
            rows.append({k: r[k] for k in COLS} | {"chain": r["a_chain"], "ca": str(r["a_ca"]).lower()})
            aids.add(int(r["asset_id"]))
    other = {}
    for aid in sorted(aids):
        n = conn.execute("SELECT count(*) FROM postings WHERE asset_id=? AND NOT (source_kind='opening' AND leg_kind='opening')",
                         (aid,)).fetchone()[0]
        if n:
            other[aid] = int(n)
    return rows, other


def _exf_b(sid) -> int:
    s9 = str(sid or "")
    if not s9.startswith("exfrecon:"):
        return None
    try:
        return int(s9.rsplit(":", 1)[1])
    except ValueError:
        return None


PREWIN_WHY = {"anchor": "거래소 첫 대사의 이 칸 앵커 없음·여러 줄", "late_obs": "원본 관측이 첫 대사 뒤(그 대사가 되받지 않음)",
              "after_t0": "앵커가 창 시작 뒤(창 시작~첫 대사 잔고가 바뀜)", "sum": "창 이전 합 + 앵커 < 0(창 시작 음수 잔고 — 정정하면 음수 기초잔고)",
              "split": "한 원본의 레그가 남는 칸에 걸침"}


def plan_okx_prewin(conn, ex: str = "okx", late_anchor: bool = False):
    loc = f"exchange:{ex}"
    sel = "SELECT " + ", ".join(COLS) + " FROM postings"
    pl = _planner(conn)
    b0 = pl._exf_first_bts(ex)
    if b0 is None:
        print(f"{ex}: 대사 없음 — 할 일 없음")
        return [], {}
    if ex in pl.EXF_FUT_EX and pl._meta_get(f"recon_done_exf_{ex}"):
        fut_state, fut_scope = pl._exf_fut_place_scope()
        if fut_state != "done" and (fut_scope is None or ex in fut_scope):
            print(f"{ex}: 선물 정산 이관 미완료({fut_state}) — 이관 적용·검증 뒤 정리 · 할 일 없음")
            return [], {}
    t0 = int(pl._exf_open_ts(ex, b0))
    srcs = {(r["source_ns"], r["source_id"]) for r in conn.execute(
        "SELECT source_ns, source_id FROM postings WHERE source_kind='exchange' AND source_ns IN (?, ?) AND location=? AND event_ts < ?",
        (f"{ex}:deposit", f"{ex}:withdraw", loc, t0))}
    legs = [dict(r) for ns, sid in sorted(srcs) for r in conn.execute(sel + " WHERE source_kind='exchange' AND source_ns=? AND source_id=?", (ns, sid))]
    obs = {}
    for ns, sid in srcs:
        o = conn.execute("SELECT min(observed_at) FROM raw_ex WHERE exchange=? AND kind=? AND uuid=?", (ex, ns.split(":", 1)[1], sid)).fetchone()[0]
        obs[(ns, sid)] = int(o) if o is not None else None
    cells = {}
    for r in legs:
        cells.setdefault((r["location"], int(r["asset_id"])), []).append(r)
    why, take = {}, {}
    for (lc, aid), pre in sorted(cells.items()):
        anc = [dict(r) for r in conn.execute(sel + " WHERE source_kind='exchange' AND source_ns=? AND location=? AND asset_id=? AND leg_kind='opening'"
                                             " AND event='EXF_ADJUST'", (f"{ex}:recon", lc, aid)) if _exf_b(r["source_id"]) is not None]
        first = [a for a in anc if _exf_b(a["source_id"]) == b0]
        if lc != loc or len(first) != 1 or min(_exf_b(a["source_id"]) for a in anc) != b0:
            why[aid] = "anchor"
        elif any(obs.get((r["source_ns"], r["source_id"])) is None or obs[(r["source_ns"], r["source_id"])] >= b0 for r in pre):
            why[aid] = "late_obs"
        elif int(first[0]["event_ts"]) > t0:
            if late_anchor and sum(int(r["qty_base"]) for r in pre) + int(first[0]["qty_base"]) == 0:
                take[aid] = pre + first
            else:
                why[aid] = "after_t0"
        elif sum(int(r["qty_base"]) for r in pre) + int(first[0]["qty_base"]) < 0:
            why[aid] = "sum"
        elif sum(int(r["qty_base"]) for r in pre) + int(first[0]["qty_base"]) > 0:
            take[aid] = pre + [first[0] | {"set_qty": str(sum(int(r["qty_base"]) for r in pre) + int(first[0]["qty_base"]))}]
        else:
            take[aid] = pre + first
    while True:
        kept = {(r["source_ns"], r["source_id"]) for (_lc, aid), pre in cells.items() if aid not in take for r in pre}
        bad = [aid for aid, rows in take.items() if any((r["source_ns"], r["source_id"]) in kept for r in rows)]
        if not bad:
            break
        for aid in bad:
            why[aid] = "split"
            del take[aid]
    for (_lc, aid), pre in sorted(cells.items()):
        if aid in why:
            print(f"남김 자산 {aid}: 창 이전 {len(pre)}행 · 사유 {PREWIN_WHY[why[aid]]}")
    print(f"{ex} 창 시작 {t0} · 창 이전 입출금 칸 {len(cells)} · 쌍으로 지울 칸 {len(take)} · 남김 칸 {len(why)}")
    rows = [r | {"chain": None, "ca": None} for aid in sorted(take) for r in sorted(take[aid], key=lambda x: int(x["posting_id"]))]
    return rows, {aid: len(pre) for (_lc, aid), pre in cells.items() if aid in why}


def plan_div_absorb(conn, ex: str = "binance"):
    loc = f"exchange:{ex}"
    pl = _planner(conn)
    if conn.execute("SELECT 1 FROM meta WHERE k LIKE ? AND v='div_absorb' LIMIT 1", (RECEIPT + "%",)).fetchone():
        print(f"{ex}: div_absorb 적용 영수증 있음(한 번만 — 다시 하려면 되돌리기 먼저) · 할 일 없음")
        return [], {}
    if ex in pl.EXF_FUT_EX and pl._meta_get(f"recon_done_exf_{ex}"):
        fut_state, fut_scope = pl._exf_fut_place_scope()
        if fut_state != "done" and (fut_scope is None or ex in fut_scope):
            print(f"{ex}: 선물 정산 이관 미완료({fut_state}) — 이관 적용·검증 뒤 정리 · 할 일 없음")
            return [], {}
    if pl._meta_get("exf_revert_log_fail") or not os.path.isfile(pl.EXF_REVERT_LOG):
        print(f"{ex}: 대사 되돌림 감사 기록 없음·실패 표식 — 지급별 못 맞춘 몫을 알 수 없음 · 할 일 없음")
        return [], {}
    try:
        rv = pl._exf_revert_rows()
    except ValueError as e9:
        print(f"{ex}: 대사 되돌림 감사 기록 손상({e9}) · 할 일 없음")
        return [], {}
    took = {}
    for e9 in rv:
        sid9 = str(e9.get("source_id") or "")
        if e9.get("loc") != loc or not str(e9.get("why") or "").startswith("지급 내역 ") or pl._exf_bts(sid9) is None or not sid9.startswith("exfrecon:"):
            continue
        k9 = took.setdefault(sid9[len("exfrecon:"):].rsplit(":", 1)[0].upper(), {}).setdefault(
            (sid9, int(e9["leg_seq"])), [int(e9["event_ts"]), pl._exf_bts(sid9), 0, int(e9["posting_id"])])
        k9[2] += abs(int(e9["old_qty_base"])) - abs(int(e9["new_qty_base"]))
    pays = {}
    for r in conn.execute("SELECT p.event_ts, p.qty_base, upper(a.symbol) AS sym,"
                          " (SELECT min(o.observed_at) FROM raw_ex o WHERE o.exchange=? AND o.kind='income' AND o.uuid=p.source_id) AS obs"
                          " FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='exchange' AND p.source_ns=? AND p.location=?",
                          (ex, f"{ex}:income", loc)):
        if r["obs"] is not None:
            pays.setdefault(r["sym"], []).append([int(r["event_ts"]), int(r["qty_base"]), int(r["obs"])])
    late_obs = set()
    for r9 in conn.execute("SELECT payload, observed_at FROM raw_ex WHERE exchange=? AND kind='trade'", (ex,)):
        try:
            f9 = json.loads(r9["payload"])
        except (TypeError, ValueError):
            f9 = None
        if not isinstance(f9, dict):
            print(f"{ex}: 체결 원본 형식 이상 — 지급 순액 짝을 확인할 수 없음 · 할 일 없음")
            return [], {}
        if f9.get("late") or f9.get("src") == "convert":
            late_obs |= {(s9, int(r9["observed_at"])) for s9 in pl._late_fill_deltas([f9])}
    sel = "SELECT " + ", ".join(COLS) + " FROM postings WHERE posting_id=?"
    out, left = [], {}
    for sym in sorted(pays):
        rows = [r for r in pl._exf_adj_rows(ex, sym) if pl._exf_bts(r["source_id"]) is not None
                and not histmark.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id"))]
        bounds = pl._exf_bounds_q(conn, ex, sym)
        if any((sym, pay[2]) in late_obs for pay in pays[sym]):
            print(f"{ex} {sym}: 지급과 같은 레코드에 늦은 체결·전환 — 순액 짝 가능 · 남김")
            continue
        if len({pay[2] for pay in pays[sym]}) >= 2 and took.get(sym):
            print(f"{ex} {sym}: 지급 관측 회차 {len({pay[2] for pay in pays[sym]})}개 + 지급 내역 대체 감사 기록 — 감사 기록의 지급 배정이 모호 · 남김")
            continue
        tk = took.get(sym, {})
        for pay in sorted(pays[sym], key=lambda p9: (p9[2], p9[0])):
            b0 = pl._exf_bucket(bounds, pay[0])
            ordered9 = sorted(tk.items(), key=lambda kv: (0, kv[1][0], kv[1][3]) if pay[0] <= kv[1][0] <= b0 else (1, kv[1][1], -kv[1][0], kv[1][3]))
            for k9, (ev9, bt9, n9, _pid9) in ordered9:
                if n9 > 0 and pay[1] > 0 and bt9 <= pay[2] and ((pay[0] <= ev9 <= b0) or (bt9 >= pay[0] and ev9 < pay[0])):
                    use9 = min(pay[1], n9)
                    pay[1] -= use9
                    tk[k9][2] -= use9
        negs = sorted((r for r in rows if int(r["qty_base"]) < 0), key=lambda r: (pl._exf_bts(r["source_id"]), int(r["posting_id"])))
        poss = sorted((r for r in rows if int(r["qty_base"]) > 0), key=lambda r: (pl._exf_bts(r["source_id"]), -int(r["event_ts"]), int(r["posting_id"])))
        series = dict(pl._exf_series(ex, sym))
        rem = {int(r["posting_id"]): int(r["qty_base"]) for r in negs + poss}
        used_n = set()
        for p in poss:
            b9, t9 = pl._exf_bts(p["source_id"]), int(p["event_ts"])
            dec = 8 if p["decimals"] is None else int(p["decimals"])
            elig = [pay for pay in sorted(pays[sym]) if t9 < pay[0] <= b9 < pay[2] and pl._exf_bucket(bounds, pay[0]) != b9]
            for n in negs:
                tn, nb = int(n["event_ts"]), pl._exf_bts(n["source_id"])
                if rem[int(p["posting_id"])] <= 0:
                    break
                obs9 = [pay for pay in elig if pay[2] <= nb and pay[1] > 0]
                if rem[int(n["posting_id"])] >= 0 or tn <= t9 or int(n["asset_id"]) != int(p["asset_id"]) or not obs9:
                    continue
                room = pl._exf_room(sorted(series.items()), t9, t_end=tn)
                x = min(sum(pay[1] for pay in obs9), rem[int(p["posting_id"])], -rem[int(n["posting_id"])], int(room * (Decimal(10) ** dec)))
                if x <= 0:
                    continue
                rem[int(p["posting_id"])] -= x
                rem[int(n["posting_id"])] += x
                used_n.add(int(n["posting_id"]))
                series[t9] = series.get(t9, Decimal(0)) - Decimal(x) / (Decimal(10) ** dec)
                series[tn] = series.get(tn, Decimal(0)) + Decimal(x) / (Decimal(10) ** dec)
                for pay in obs9:
                    use9 = min(x, pay[1])
                    pay[1] -= use9
                    x -= use9
                    if x <= 0:
                        break
        changed = [r for r in negs + poss if rem[int(r["posting_id"])] != int(r["qty_base"])]
        for r in changed:
            full = dict(conn.execute(sel, (int(r["posting_id"]),)).fetchone()) | {"chain": None, "ca": None}
            if rem[int(r["posting_id"])] != 0:
                full["set_qty"] = str(rem[int(r["posting_id"])])
            out.append(full)
        un = sum(-rem[int(n["posting_id"])] for n in negs if int(n["posting_id"]) in used_n or int(n["event_ts"]) >= min(pay[2] for pay in pays[sym]))
        if un > 0:
            left[sym] = un
        if changed or un > 0:
            print(f"{ex} {sym}: 지급 {len(pays[sym])}건 · 고칠 줄 {len(changed)}"
                  + (f" · 지급 원본 관측 뒤 남는 음수 보정 자릿수 {len(str(un))}(대상 양수 보정 없음·여유 부족·이미 대체된 지급 — 남김)" if un > 0 else " · 음수 보정 해소"))
    print(f"{ex} 고칠 칸 {len({r['asset_id'] for r in out})} · 남김 칸 {len(left)}")
    return sorted(out, key=lambda r: int(r["posting_id"])), {}


PLANS = {"mirror_open": plan_mirror_open, "okx_prewin": plan_okx_prewin, "div_absorb": plan_div_absorb}
RAWSKIP = "exf_rawskip:"


def _raw_mark(rw, r, on: bool) -> None:
    if r["source_kind"] != "exchange" or not str(r["location"]).startswith("exchange:"):
        return
    ex9, _, kd = str(r["source_ns"]).partition(":")
    if kd in ("deposit", "withdraw"):
        k9 = f"{RAWSKIP}{ex9}:{kd}:{r['source_id']}"
        if on:
            rw.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k9, KIND))
        else:
            rw.execute("DELETE FROM meta WHERE k=?", (k9,))
    elif kd == "recon" and on and _exf_b(r["source_id"]) is not None:
        sym9 = str(r["source_id"])[len("exfrecon:"):].rsplit(":", 1)[0]
        rw.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)", (ex9, sym9.upper(), _exf_b(r["source_id"])))


def _pos_bump(rw, aid: int, qb: int, loc: str) -> None:
    a = rw.execute("SELECT group_id, decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()
    if a is None or not a[0]:
        raise RuntimeError(f"자산 {aid}: 그룹 없음(포지션 산식 불가)")
    dec = a[1] if a[1] is not None else 18
    row = rw.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (a[0], loc)).fetchone()
    if row is None:
        raise RuntimeError(f"자산 {aid}: 위치 {loc}의 포지션 없음 — 정정 거부")
    with localcontext() as ctx:
        ctx.prec = 100
        norm = Decimal(qb) / (Decimal(10) ** dec)
        new_qty = format(norm + (Decimal(row[0]) if row else Decimal(0)), "f")
    if row:
        rw.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?", (new_qty, a[0], loc))
    else:
        rw.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)", (a[0], loc, new_qty))


RECEIPT = "ledger_rowfix_receipt:"


def _digest(rows) -> str:
    body = sorted([[r[k] for k in COLS] + ([str(int(r["set_qty"]))] if r.get("set_qty") is not None else []) for r in rows], key=lambda x: int(x[0]))
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _apply(rows, kind, before_commit=None):
    rw = sqlite3.connect(paths.DB_PATH, timeout=30, isolation_level=None)
    try:
        rw.execute("BEGIN IMMEDIATE")
        for r in rows:
            cur = rw.execute("SELECT " + ", ".join(COLS) + " FROM postings WHERE posting_id=?", (int(r["posting_id"]),)).fetchone()
            if cur is None or tuple(cur) != tuple(r[k] for k in COLS):
                raise RuntimeError(f"pid {r['posting_id']}: 지금 행이 점검 때와 다름")
            if r.get("set_qty") is not None:
                if rw.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(int(r["set_qty"])), int(r["posting_id"]))).rowcount != 1:
                    raise RuntimeError(f"pid {r['posting_id']}: 수량 정정 실패")
                _pos_bump(rw, int(r["asset_id"]), int(r["set_qty"]) - int(r["qty_base"]), r["location"])
                continue
            if rw.execute("DELETE FROM postings WHERE posting_id=?", (int(r["posting_id"]),)).rowcount != 1:
                raise RuntimeError(f"pid {r['posting_id']}: 지우기 실패")
            _pos_bump(rw, int(r["asset_id"]), -int(r["qty_base"]), r["location"])
            _raw_mark(rw, r, True)
        dbm.bump_daily_inval(rw)
        rw.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (RECEIPT + _digest(rows), kind))
        if before_commit is not None:
            before_commit({"kind": KIND, "plan": kind, "applied": True, "rows": rows})
        _invalidate(min(int(r["event_ts"]) for r in rows))
        rw.execute("COMMIT")
    except BaseException:
        rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()


def _undo(rows):
    rw = sqlite3.connect(paths.DB_PATH, timeout=30, isolation_level=None)
    try:
        rw.execute("BEGIN IMMEDIATE")
        if rw.execute("DELETE FROM meta WHERE k=?", (RECEIPT + _digest(rows),)).rowcount != 1:
            raise RuntimeError("이 원장에 그 적용 영수증이 없음(다른 원장의 파일 · 이미 되돌림 · 손댄 파일) — 되돌리기 전부 거부")
        for r in rows:
            if r.get("set_qty") is not None:
                cur = rw.execute("SELECT " + ", ".join(COLS) + " FROM postings WHERE posting_id=?", (int(r["posting_id"]),)).fetchone()
                if cur is None or tuple(cur) != tuple(str(int(r["set_qty"])) if k == "qty_base" else r[k] for k in COLS):
                    raise RuntimeError(f"pid {r['posting_id']}: 정정한 행이 바뀜·없음 — 되돌리기 전부 거부")
                rw.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (r["qty_base"], int(r["posting_id"])))
                _pos_bump(rw, int(r["asset_id"]), int(r["qty_base"]) - int(r["set_qty"]), r["location"])
                continue
            if rw.execute("SELECT 1 FROM postings WHERE posting_id=? OR (source_kind=? AND source_ns=? AND source_id=? AND leg_seq=?)",
                          (int(r["posting_id"]), r["source_kind"], r["source_ns"], r["source_id"], int(r["leg_seq"]))).fetchone():
                raise RuntimeError(f"pid {r['posting_id']}: 같은 키 행이 이미 있음 — 되돌리기 전부 거부")
            rw.execute("INSERT INTO postings (" + ", ".join(COLS) + ") VALUES (" + ",".join("?" * len(COLS)) + ")",
                       tuple(r[k] for k in COLS))
            _pos_bump(rw, int(r["asset_id"]), int(r["qty_base"]), r["location"])
            _raw_mark(rw, r, False)
        dbm.bump_daily_inval(rw)
        _invalidate(min(int(r["event_ts"]) for r in rows))
        rw.execute("COMMIT")
    except BaseException:
        rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()


def _invalidate(t_min):
    print("장기 곡선 다시 계산 표식:", histmark.mark_hist_dirty(int(t_min)))


def _setq_ok(r) -> bool:
    q = r.get("set_qty")
    try:
        return q is None or str(int(q)) == str(q)
    except (TypeError, ValueError):
        return False


def _write_undo(path, obj):
    statefile.atomic_write_json(path, obj)


def _args(argv):
    ap = argparse.ArgumentParser(prog="ledger_rowfix.py", description="원장 행 1회 정정(지우기 · 되돌리기) — 점검 기본(쓰기 없음) · "
                                 "--apply 는 tj-core 정지 중에만.")
    ap.add_argument("--kind", choices=sorted(PLANS) + [AUTOFIX_KIND], help="정정 종류(" + " · ".join(sorted(PLANS) + [AUTOFIX_KIND]) + ")")
    ap.add_argument("--undo-autofix", metavar="EX:SYM", help="자동 처리 칸 되돌리기(영수증 기준 · 그 칸 autofix_off 를 넣음) — --apply 와 같이 써야 씀")
    ap.add_argument("--autofix-on", metavar="EX:SYM", help="되돌린 칸의 autofix_off 표식 지움(다시 켜기) — --apply 와 같이")
    ap.add_argument("--data-rev-down", type=int, metavar="N", help="원장 data_rev 2 → 1(자동 처리 영수증·행 0 일 때만 · 옛 판 코드 롤백 전) — --apply 와 같이")
    ap.add_argument("--undo", metavar="UNDO_JSON", help="되돌리기(state/ledger_rowfix_undo_….json) — --apply 와 같이 써야 실제로 씀")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(없으면 점검만)")
    ap.add_argument("--late-anchor", action="store_true", help="okx_prewin 만: 첫 대사 앵커가 창 시작 뒤인 칸도 합이 0 이면 쌍 삭제(기본 꺼짐 = 남김 · "
                    "켜면 그 칸 창 시작~첫 대사 잔고가 0 — 수집기가 처음부터 걸렀을 때와 같음 · 합<0 칸은 늘 남김)")
    return ap.parse_args(argv)


def main(argv=None):
    a = _args(sys.argv[1:] if argv is None else argv)
    if not a.undo and not a.kind and not a.undo_autofix and not a.autofix_on and a.data_rev_down is None:
        print("거부: --kind 또는 --undo 가 필요해요(종류: " + " · ".join(sorted(PLANS) + [AUTOFIX_KIND]) + ")")
        return 2
    if sum(bool(x) for x in (a.undo, a.kind, a.undo_autofix, a.autofix_on, a.data_rev_down is not None)) != 1:
        print("거부: --kind · --undo · --undo-autofix · --autofix-on · --data-rev-down 중 하나만")
        return 2
    if a.late_anchor and (a.undo or a.kind != "okx_prewin"):
        print("거부: --late-anchor 는 --kind okx_prewin 점검·적용에만")
        return 2
    assert os.path.abspath(paths.DB_PATH).startswith(os.path.abspath(paths.STATE_DIR)), "DB 경로가 state 밖"
    print(f"원장 {paths.DB_PATH}")
    if not os.path.isfile(paths.DB_PATH):
        print("거부: 원장 없음 — TJ_BASE 확인(빈 원장을 만들지 않음)")
        return 1
    if a.apply and not _core_stopped():
        print("거부: pm2 에 떠 있는 tj-core(src/core.py)가 있거나 확인하지 못함 — tj-core 를 멈춘 뒤(우회 옵션 없음)")
        return 1
    bar = _barrier(a.apply)
    if bar is False:
        print("거부: 배포·롤백이 배포 장벽(.deploy.lock)을 쥐고 있음 — 끝난 뒤 다시(원장 무변)")
        return 1
    try:
        with ledger_lock.hold_if(a.apply, paths.DB_PATH, who="ledger_rowfix --apply"):
            return _run(a)
    finally:
        if bar is not None:
            bar.close()


def _barrier(apply: bool):
    if not apply:
        return None
    import fcntl
    fh = open(os.path.join(paths.BASE_DIR, ".deploy.lock"), "a")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    return fh


def _run(a):
    if a.kind == AUTOFIX_KIND or a.undo_autofix or a.autofix_on or a.data_rev_down is not None:
        return _run_autofix(a)
    if a.undo:
        try:
            with open(a.undo) as fh:
                undo = json.load(fh)
        except (OSError, ValueError) as e:
            print(f"거부: 되돌리기 파일 읽기 실패 — {e}")
            return 1
        if not isinstance(undo, dict) or undo.get("kind") != KIND or undo.get("applied") is not True or not isinstance(undo.get("rows"), list) \
                or undo.get("plan") not in PLANS or not undo["rows"] or not all(isinstance(r, dict) and all(k in r for k in COLS) and _setq_ok(r) for r in undo["rows"]):
            print("거부: 적용 완료 기록이 아님(점검 때 쓴 미사용 파일·다른 도구 파일) — 되돌릴 것 없음")
            return 1
        rows = undo["rows"]
        print(f"되돌리기 {len(rows)}행 · 종류 {undo.get('plan')} ({a.undo})")
        if not a.apply:
            print("(점검만 — 쓰려면 --apply)")
            return 0
        try:
            _undo(rows)
        except (RuntimeError, sqlite3.Error) as e:
            print(f"★되돌리기 전부 취소(원장 무변)★ {e}")
            return 4
        print(f"되돌림 {len(rows)}행")
        return 0
    conn = _ro()
    try:
        rows, other = PLANS[a.kind](conn, late_anchor=True) if a.late_anchor else PLANS[a.kind](conn)
    finally:
        conn.close()
    for r in rows:
        w = str(r["location"]).split(":")[-1]
        print(f"{r['posting_id']:>9} {str(r.get('chain') or r['source_ns']):<9} CA …{str(r.get('ca') or '-')[-4:]} 위치 {w[:6]}…{w[-4:]} "
              f"출처 {r['source_kind']}:{str(r['source_id']).split(':')[0]} 순번 {r['leg_seq']} 수량 자릿수 {len(str(abs(int(r['qty_base']))))}"
              + (f" → 수량 정정(지우지 않음 · 새 자릿수 {len(str(abs(int(r['set_qty']))))})" if r.get("set_qty") is not None else ""))
    for aid, n in sorted(other.items()):
        print(f"★주의★ 자산 {aid}: 대상 밖 같은 자산 행 {n}개 — 이 도구는 건드리지 않음(수동 확인)")
    print(f"지울 행 {len([r for r in rows if r.get('set_qty') is None])}개 · 수량 정정 행 {len([r for r in rows if r.get('set_qty') is not None])}개")
    if not a.apply or not rows:
        print("(점검만 — 쓰려면 --apply)" if not a.apply else "할 일 없음")
        return 0
    undo = os.path.join(paths.STATE_DIR, f"ledger_rowfix_undo_{a.kind}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.json")
    if os.path.exists(undo):
        print("거부: 되돌리기 파일 이름 충돌 — 다시 실행")
        return 4
    _write_undo(undo, {"kind": KIND, "plan": a.kind, "applied": False, "rows": rows})
    try:
        _apply(rows, a.kind, before_commit=lambda done_rec: _write_undo(undo, done_rec))
    except (RuntimeError, OSError, sqlite3.Error) as e:
        try:
            _write_undo(undo, {"kind": KIND, "plan": a.kind, "applied": False, "rows": rows})
        except OSError:
            pass
        print(f"★적용 전부 취소(원장 무변)★ {e} · 되돌리기 파일(미사용) {undo}")
        return 4
    n_set = len([r for r in rows if r.get("set_qty") is not None])
    print(f"적용 {len(rows) - n_set}행 삭제 · {n_set}행 수량 정정 · 되돌리기 파일 {undo}")
    return 0


AUTOFIX_KIND = "autofix_ws"


def _rw():
    return sqlite3.connect(paths.DB_PATH, timeout=30, isolation_level=None)


def _cell_arg(v):
    ex9, _, sym9 = str(v or "").partition(":")
    return (ex9, sym9.upper()) if ex9 and sym9 else (None, None)


def _digits(v) -> int:
    try:
        return len(str(abs(int(v))))
    except (TypeError, ValueError):
        return 0


def _run_autofix(a):
    import autofix as AF
    import autofix_apply as AP
    if a.data_rev_down is not None or a.undo_autofix or a.autofix_on:
        ex9, sym9 = _cell_arg(a.undo_autofix or a.autofix_on)
        if (a.undo_autofix or a.autofix_on) and not ex9:
            print("거부: 칸은 <거래소>:<심볼> 꼴(예 okx:USDT)")
            return 2
        if not a.apply:
            c = _ro()
            try:
                rec = AF.read_receipts(c).get((ex9, sym9)) if ex9 else None
                print(f"(점검만 — 쓰려면 --apply) 영수증 {'있음 · 상태 ' + str(rec.get('state')) if rec else '없음'} · data_rev {dbm.ledger_data_rev(c)}")
            finally:
                c.close()
            return 0
        rw = _rw()
        try:
            if a.data_rev_down is not None:
                print(AP.data_rev_down(rw, a.data_rev_down))
            elif a.undo_autofix:
                rec = AP.undo_cell(rw, ex9, sym9, touch=_invalidate)
                print(f"되돌림 {ex9}:{sym9} — 창 이전 행 {len(rec.get('prewin') or [])}개 복원 · 자동 행 {'지움' if rec.get('auto') else '없음'} · autofix_off 넣음")
            else:
                print("켬(autofix_off 지움)" if AP.autofix_on(rw, ex9, sym9) else "할 일 없음(끄기 표식 없음)")
        except (AP.Refused, sqlite3.Error, ValueError) as e:
            print(f"★전부 취소(원장 무변)★ {e}")
            return 4
        finally:
            rw.close()
        return 0
    conn = _ro()
    try:
        cells = AF.plan_cells(conn, AF.venue_gap, AF.debt_floor_fn(), int(time.time()), win=_planner(conn))
    finally:
        conn.close()
    for c in cells:
        print(f"{c['ex']:<10} {c['sym']:<8} 꼴 {c['kind']:<4} 사유 {AF.SKIP_WHY.get(c['why'], c['why'])}"
              + ("" if c["kind"] == AF.KIND_SKIP else f" · 지움 {len(c['delete'])} · 정정 {len(c['setq'])} · 새 행 {len(c['add'])}"
                 f" · τ {time.strftime('%Y-%m-%d', time.gmtime(int(c['tau'])))} · X 자릿수 {_digits(c['X'])} · U 자릿수 {_digits(c['U'])}"
                 + (" · 빈 구간 안" if c.get("gap") else "")))
    todo = [c for c in cells if c["kind"] in (AF.KIND_A, AF.KIND_A2)]
    print(f"칸 {len(cells)} · A {sum(c['kind'] == AF.KIND_A for c in cells)} · A' {sum(c['kind'] == AF.KIND_A2 for c in cells)} · 남김 {len(cells) - len(todo)}")
    if not a.apply or not todo:
        print("(점검만 — 쓰려면 --apply)" if a.apply is False else "할 일 없음")
        return 0
    floor, now, bad = AF.debt_floor_fn(), int(time.time()), 0
    for c in todo:
        name = AP.undo_file(c["ex"], c["sym"], now)
        path = os.path.join(paths.STATE_DIR, name)
        if os.path.exists(path):
            print(f"거부: 되돌리기 파일 이름 충돌 {name}")
            return 4
        _write_undo(path, {"kind": AP.UNDO_KIND, "applied": False, "plan": {k: c[k] for k in ("ex", "sym", "kind")}})
        rw = _rw()
        try:
            AP.apply_cell(rw, c, now, floor=lambda t, _c=c: floor(_c["ex"], _c["sym"], t), undo_name=name,
                          write_undo=AP.write_undo_fn(path), touch=_invalidate)
            print(f"적용 {c['ex']}:{c['sym']}({c['kind']}) · 되돌리기 = --undo-autofix {c['ex']}:{c['sym']} --apply · 영수증 사본 {path}")
        except (AP.Refused, OSError, sqlite3.Error, ValueError) as e:
            bad += 1
            try:
                _write_undo(path, {"kind": AP.UNDO_KIND, "applied": False, "plan": {k: c[k] for k in ("ex", "sym", "kind")}})
            except OSError:
                pass
            print(f"★{c['ex']}:{c['sym']} 적용 취소(그 칸 원장 무변)★ {e}")
        finally:
            rw.close()
    return 4 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
