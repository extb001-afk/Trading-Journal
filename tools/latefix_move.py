#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import common
from core import Core

KST = timezone(timedelta(hours=9))
TOL = Decimal("0.00000001")
REL = Decimal("0.01")
OBS_GAP = 600
RECON_WIN = 7200
PFX = common.EXF_LATE_PFX


def _t(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d %H:%M:%S")


def _ro():
    c = sqlite3.connect(f"file:{common.DB_PATH}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _sid(sym, t_off, b9):
    return Core._exf_late_sid(sym, t_off, b9)


def _fill_deltas(f):
    try:
        ts9 = int(int(f.get("ts") or 0) / 1000)
        qty = Decimal(str(f.get("qty") or "0"))
        gross = qty * Decimal(str(f.get("price") or "0"))
        fee9 = Decimal(str(f.get("fee") or "0"))
    except (ArithmeticError, TypeError, ValueError):
        return []
    if ts9 <= 0 or qty <= 0:
        return []
    sgn = 1 if str(f.get("side")) == "buy" else -1
    out = []
    for sym, amt in ((str(f.get("base") or "").upper(), sgn * qty), (str(f.get("quote") or "").upper(), -sgn * gross),
                     (str(f.get("fee_ccy") or "").upper(), -fee9)):
        if sym and amt != 0:
            out.append((sym, ts9, amt))
    return out


def _offset_clusters(bounds, dl):
    grp = {}
    for ts9, amt in dl:
        grp.setdefault(Core._exf_bucket(bounds, ts9), []).append((ts9, amt))
    out = [(t0, t1, net, b9) for b9, lst in grp.items() for t0, t1, net in Core._exf_late_clusters(lst)]
    return sorted(out, key=lambda c9: (c9[1], c9[0]))


def _series(conn, ex, sym):
    agg = {}
    for r in conn.execute("SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                          " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym)):
        dec = 8 if r["decimals"] is None else int(r["decimals"])
        agg[int(r["posting_id"])] = [int(r["event_ts"]), Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)]
    return agg


def _cum_points(ev):
    tot = {}
    for t9, q9 in ev.values():
        tot[t9] = tot.get(t9, Decimal(0)) + q9
    cum, out = Decimal(0), []
    for t9 in sorted(tot):
        cum += tot[t9]
        out.append((t9, cum))
    return out


def _bal_at(points, t):
    v = Decimal(0)
    for t9, c9 in points:
        if t9 > t:
            break
        v = c9
    return v


def plan(conn, since, only_ex=None):
    late = {}
    dw = {}
    for r in conn.execute("SELECT exchange, kind, payload, observed_at FROM raw_ex WHERE observed_at>=? AND kind IN ('trade','deposit','withdraw')",
                          (int(since),)):
        ex = r["exchange"]
        if ex == "upbit" or (only_ex and ex != only_ex):
            continue
        try:
            p = json.loads(r["payload"])
        except (ValueError, TypeError):
            continue
        if not isinstance(p, dict) or not p.get("late"):
            continue
        if r["kind"] == "trade":
            late.setdefault(ex, []).append((int(r["observed_at"]), p))
        else:
            dw.setdefault(ex, []).append((int(r["observed_at"]), {str(p.get("currency") or "").upper(), str(p.get("fee_ccy") or "").upper()}))
    moves, rejects = [], []
    for ex, lst in sorted(late.items()):
        lst.sort(key=lambda x: x[0])
        batches = []
        for o9, p in lst:
            if batches and o9 - batches[-1]["o1"] <= OBS_GAP:
                batches[-1]["o1"] = o9
                batches[-1]["f"].append(p)
            else:
                batches.append({"o0": o9, "o1": o9, "f": [p]})
        adj = {}
        for r in conn.execute("SELECT p.posting_id, p.source_id, p.leg_seq, p.event_ts, p.qty_base, p.asset_id, a.symbol, a.decimals FROM postings p"
                              " JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=?"
                              " AND p.source_id LIKE 'exfrecon:%' AND p.leg_seq=0", (f"{ex}:recon", f"exchange:{ex}")):
            try:
                sym9, b9 = str(r["source_id"])[len("exfrecon:"):].rsplit(":", 1)
                b9 = int(b9)
            except ValueError:
                continue
            if abs(int(r["event_ts"]) - b9) <= 60 and int(r["qty_base"]) != 0:
                adj[(sym9.upper(), b9)] = dict(r)
        for b in batches:
            per = {}
            for f in b["f"]:
                for sym, ts9, amt in _fill_deltas(f):
                    if ts9 < b["o0"] - 600:
                        per.setdefault(sym, []).append((ts9, amt))
            mixed = set()
            for o9, ccys in dw.get(ex, ()):
                if b["o0"] - OBS_GAP <= o9 <= b["o1"] + OBS_GAP:
                    mixed |= ccys
            for sym, dl in sorted(per.items()):
                if sym in Core.EXF_FIX_SKIP:
                    continue
                net = sum((a for _, a in dl), Decimal(0))
                if abs(net) <= TOL:
                    continue
                cands = sorted(k[1] for k in adj if k[0] == sym and b["o1"] <= k[1] <= b["o1"] + RECON_WIN)
                zb9 = sorted(int(t[0]) for t in conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex=? AND sym=? AND bts BETWEEN ? AND ?",
                                                             (ex, sym, int(b["o1"]), int(b["o1"]) + RECON_WIN)))
                if zb9 and (not cands or zb9[0] < cands[0]):
                    rejects.append(f"{ex} {sym} 대사 {_t(zb9[0])}: 대상 대사 줄이 되돌림으로 0(지워짐) — 수동 처리(늦은 순액 {net})")
                    continue
                if not cands:
                    continue
                bts = cands[0]
                r = adj[(sym, bts)]
                dec = 8 if r["decimals"] is None else int(r["decimals"])
                scale = Decimal(10) ** dec
                q_adj = Decimal(int(r["qty_base"])) / scale
                tag = f"{ex} {sym} 대사 {_t(bts)}"
                if sym in mixed:
                    rejects.append(f"{tag}: 같은 관측 창에 늦은 입출금 섞임 — 수동")
                    continue
                if (q_adj > 0) == (net > 0) or abs(abs(q_adj) - abs(net)) > abs(net) * REL:
                    rejects.append(f"{tag}: 보정/−순액 비율 {(-q_adj / net):.6f} — 대상 아님(±1% 밖·부호 다름)")
                    continue
                cl = _offset_clusters(Core._exf_bounds_q(conn, ex, sym), dl)
                if any((c9[2] > 0) != (net > 0) or abs(c9[2]) <= TOL for c9 in cl):
                    rejects.append(f"{tag}: 묶음 안 무리 부호가 섞임 — 수동")
                    continue
                move_b = min(abs(int(r["qty_base"])), int(abs(net) * scale))
                sg = 1 if int(r["qty_base"]) > 0 else -1
                parts, used = [], 0
                for i9, (t0, t1, cn, cb9) in enumerate(cl):
                    qb9 = (move_b - used) if i9 == len(cl) - 1 else min(move_b - used, int(abs(cn) * scale))
                    if qb9 > 0:
                        parts.append({"ts": int(t1) + Core.EXF_LATE_DT, "qb": sg * qb9, "b": int(cb9)})
                        used += qb9
                moves.append({"ex": ex, "sym": sym, "bts": bts, "pid": int(r["posting_id"]), "sid": str(r["source_id"]), "leg": 0,
                              "asset_id": int(r["asset_id"]), "dec": dec, "qb_old": str(r["qty_base"]), "ts_old": int(r["event_ts"]),
                              "keep_qb": str(int(r["qty_base"]) - sg * used), "parts": parts,
                              "ratio": f"{(-q_adj / net):.6f}", "n_fill": len(dl), "t_first": min(t for t, _ in dl)})
    ok_moves = []
    by = {}
    for m in moves:
        by.setdefault((m["ex"], m["sym"]), []).append(m)
    for (ex, sym), ms in sorted(by.items()):
        ev = _series(conn, ex, sym)
        before = _cum_points(ev)
        sc = {m["pid"]: Decimal(10) ** m["dec"] for m in ms}
        nid = -1
        for m in ms:
            if m["pid"] not in ev:
                continue
            ev[m["pid"]] = [m["ts_old"], Decimal(int(m["keep_qb"])) / sc[m["pid"]]]
            for p in m["parts"]:
                ev[nid] = [p["ts"], Decimal(int(p["qb"])) / sc[m["pid"]]]
                nid -= 1
        after = _cum_points(ev)
        lo = min(p["ts"] for m in ms for p in m["parts"])
        hi = max(m["bts"] for m in ms)
        bad = [(t9, c9) for t9, c9 in after if lo <= t9 <= hi and c9 < -TOL and c9 < _bal_at(before, t9) - TOL]
        if bad:
            rejects.append(f"{ex} {sym}: 옮기면 {_t(bad[0][0])} 등 {len(bad)}개 시점이 새로 음수 — 이 심볼 전부 거부")
            continue
        if sum((v for _, v in ev.values()), Decimal(0)) != _cum_points(_series(conn, ex, sym))[-1][1]:
            rejects.append(f"{ex} {sym}: 수량 합이 바뀜(내부 오류) — 거부")
            continue
        ok_moves.extend(ms)
    return ok_moves, rejects


_ROWQ = ("SELECT event_ts, source_id, qty_base, asset_id, location, source_ns, event, leg_seq, leg_kind FROM postings WHERE posting_id=?")


def _sums(rw, keys):
    return {k: int(rw.execute("SELECT COALESCE(SUM(CAST(qty_base AS INTEGER)), 0) FROM postings WHERE location=? AND asset_id=?", k).fetchone()[0])
            for k in sorted(keys)}


def _apply(moves):
    rw = sqlite3.connect(common.DB_PATH, timeout=30, isolation_level=None)
    done = []
    try:
        rw.execute("BEGIN IMMEDIATE")
        keys = {(f"exchange:{m['ex']}", int(m["asset_id"])) for m in moves}
        sym_keys = sorted({(m["ex"], m["sym"]) for m in moves})
        s0 = _sums(rw, keys)
        b0 = {k: Core._exf_bounds_q(rw, *k) for k in sym_keys}
        for m in moves:
            cv = rw.execute("SELECT classifier_ver, leg_kind, source_kind, source_ns, location FROM postings WHERE posting_id=? AND source_id=? AND leg_seq=?"
                            " AND event_ts=? AND qty_base=?", (m["pid"], m["sid"], m["leg"], m["ts_old"], m["qb_old"])).fetchone()
            if cv is None:
                raise RuntimeError(f"pid {m['pid']}: 지금 행이 점검 때와 다름")
            new_ids, tomb = [], False
            parts = list(m["parts"])
            if int(m["keep_qb"]) == 0:
                p0 = parts.pop(0)
                sid0 = _sid(m["sym"], p0["ts"], p0["b"])
                if rw.execute("UPDATE postings SET event_ts=?, source_id=?, qty_base=? WHERE posting_id=? AND event_ts=? AND qty_base=?",
                              (p0["ts"], sid0, str(p0["qb"]), m["pid"], m["ts_old"], m["qb_old"])).rowcount != 1:
                    raise RuntimeError(f"pid {m['pid']}: 옮기기 실패")
                post = {"ts": int(p0["ts"]), "sid": sid0, "qb": str(p0["qb"])}
                if int(m["bts"]) not in Core._exf_bounds_q(rw, m["ex"], m["sym"]):
                    tomb = rw.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)", (m["ex"], m["sym"], int(m["bts"]))).rowcount == 1
            else:
                if rw.execute("UPDATE postings SET qty_base=? WHERE posting_id=? AND qty_base=?", (m["keep_qb"], m["pid"], m["qb_old"])).rowcount != 1:
                    raise RuntimeError(f"pid {m['pid']}: 남는 몫 줄이기 실패")
                post = {"ts": int(m["ts_old"]), "sid": m["sid"], "qb": str(m["keep_qb"])}
            new_rows = []
            for p in parts:
                sid9 = _sid(m["sym"], p["ts"], p["b"])
                mx = rw.execute("SELECT MAX(leg_seq) FROM postings WHERE source_kind=? AND source_ns=? AND source_id=?",
                                (cv[2], cv[3], sid9)).fetchone()[0]
                seq9 = 0 if mx is None else int(mx) + 1
                cur = rw.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                                 " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,'EXF_ADJUST',?)",
                                 (cv[2], cv[3], sid9, seq9, p["ts"], m["asset_id"], cv[4], str(p["qb"]), cv[1], cv[0]))
                new_ids.append(cur.lastrowid)
                new_rows.append({"id": int(cur.lastrowid), "ts": int(p["ts"]), "sid": sid9, "qb": str(p["qb"]), "leg": seq9})
            done.append(dict(m, new_ids=new_ids, tomb=tomb, post=post, new_rows=new_rows, leg_kind=cv[1]))
        if _sums(rw, keys) != s0:
            raise RuntimeError("수량 합이 바뀜(내부 오류)")
        for k in sym_keys:
            if Core._exf_bounds_q(rw, *k) != b0[k]:
                raise RuntimeError(f"{k[0]} {k[1]}: 구간 경계가 바뀜(내부 오류)")
        rw.execute("COMMIT")
        return done
    except BaseException:
        rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()


def _undo(undo):
    rw = sqlite3.connect(common.DB_PATH, timeout=30, isolation_level=None)
    try:
        rw.execute("BEGIN IMMEDIATE")
        keys = set()
        for m in undo:
            if not isinstance(m, dict) or not isinstance(m.get("post"), dict) or not isinstance(m.get("new_rows"), list):
                raise RuntimeError("적용 완료 기록이 아님(점검 때 쓴 미사용 파일·옛 형식) — 되돌릴 것 없음")
            loc9, ns9 = f"exchange:{m['ex']}", f"{m['ex']}:recon"
            keys.add((loc9, int(m["asset_id"])))
            want = [(int(m["pid"]), m["post"]["ts"], m["post"]["sid"], m["post"]["qb"], int(m["leg"]))]
            want += [(int(n["id"]), n["ts"], n["sid"], n["qb"], int(n["leg"])) for n in m["new_rows"]]
            for pid9, ts9, sid9, qb9, leg9 in want:
                r9 = rw.execute(_ROWQ, (pid9,)).fetchone()
                if r9 is None or (int(r9[0]), str(r9[1]), str(r9[2]), int(r9[3]), r9[4], r9[5], r9[6], int(r9[7])) != (
                        int(ts9), str(sid9), str(qb9), int(m["asset_id"]), loc9, ns9, "EXF_ADJUST", leg9):
                    raise RuntimeError(f"pid {pid9}: 적용 뒤 행이 바뀜(수량·시각·출처 — 수집 재개 뒤 core 가 상쇄를 줄였거나 지움 등) — 되돌리기 전부 거부")
        s0 = _sums(rw, keys)
        for m in undo:
            for n in m["new_rows"]:
                if rw.execute("DELETE FROM postings WHERE posting_id=? AND source_id=? AND qty_base=? AND event_ts=?",
                              (int(n["id"]), n["sid"], n["qb"], int(n["ts"]))).rowcount != 1:
                    raise RuntimeError(f"새 행 {n['id']} 지우기 실패")
            if rw.execute("UPDATE postings SET event_ts=?, source_id=?, qty_base=? WHERE posting_id=? AND event_ts=? AND source_id=? AND qty_base=?",
                          (m["ts_old"], m["sid"], m["qb_old"], int(m["pid"]), int(m["post"]["ts"]), m["post"]["sid"], m["post"]["qb"])).rowcount != 1:
                raise RuntimeError(f"pid {m['pid']} 되돌리기 실패")
            if m.get("tomb"):
                rw.execute("DELETE FROM exf_adj_tomb WHERE ex=? AND sym=? AND bts=?", (m["ex"], m["sym"], int(m["bts"])))
        if _sums(rw, keys) != s0:
            raise RuntimeError("수량 합이 바뀜(내부 오류)")
        rw.execute("COMMIT")
    except BaseException:
        rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()


def _invalidate(t_min):
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    print("장기 곡선 다시 계산 표식:", common.mark_hist_dirty(int(t_min)))


def _since(a):
    if "--since" not in a:
        return int(time.time()) - 7 * 86400
    v = a[a.index("--since") + 1]
    if v.isdigit():
        return int(v)
    return int(datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=KST).timestamp())


def main():
    a = sys.argv[1:]
    apply = "--apply" in a
    assert os.path.abspath(common.DB_PATH).startswith(os.path.abspath(common.STATE_DIR)), "DB 경로가 state 밖"
    print(f"원장 {common.DB_PATH}")
    if "--undo" in a:
        f = a[a.index("--undo") + 1]
        undo = json.load(open(f))
        print(f"되돌리기 {len(undo)}건 ({f})")
        if not apply:
            print("(점검만 — 쓰려면 --apply)")
            return 0
        try:
            _undo(undo)
        except RuntimeError as e:
            print(f"★되돌리기 전부 취소(원장 무변)★ {e}")
            return 4
        _invalidate(min([m["ts_old"] for m in undo] + [p["ts"] for m in undo for p in m["parts"]]))
        print(f"되돌림 {len(undo)}건")
        return 0
    only_ex = a[a.index("--ex") + 1] if "--ex" in a else None
    only_sym = {x.strip().upper() for x in a[a.index("--sym") + 1].split(",")} if "--sym" in a else None
    conn = _ro()
    moves, rejects = plan(conn, _since(a), only_ex)
    conn.close()
    if only_sym:
        moves = [m for m in moves if m["sym"] in only_sym]
    for m in moves:
        tgt = " + ".join(f"{_t(p['ts'])}" for p in m["parts"])
        print(f"{m['pid']:>9} {m['ex']} {m['sym']:<8} 대사 {_t(m['bts'])} → {tgt} (체결 {m['n_fill']}건 · 보정/−순액 {m['ratio']}"
              f"{' · 남는 몫 대사 시각에' if int(m['keep_qb']) != 0 else ''})")
    for r9 in rejects:
        print("★거부★ " + r9)
    print(f"옮길 행 {len(moves)}건 · 거부 {len(rejects)}건")
    if not apply or not moves:
        print("(점검만 — 쓰려면 --apply)" if not apply else "할 일 없음")
        return 0
    fd, undo = tempfile.mkstemp(prefix=f"latefix_move_undo_{time.strftime('%Y%m%d_%H%M%S')}_", suffix=".json", dir=common.STATE_DIR)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(moves, f)
        f.flush()
        os.fsync(f.fileno())
    try:
        done = _apply(moves)
    except RuntimeError as e:
        print(f"★적용 전부 취소(원장 무변)★ {e} · 되돌리기 파일(미사용) {undo}")
        return 4
    with open(undo, "w") as f:
        json.dump(done, f)
        f.flush()
        os.fsync(f.fileno())
    _invalidate(min(p["ts"] for m in done for p in m["parts"]))
    print(f"적용 {len(done)}건 · 되돌리기 파일 {undo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
