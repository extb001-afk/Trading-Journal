import calcguard
import acct_norm, histmark, paths, statefile
import db as dbm
import json
import os
import re
import recon_adj
import sqlite3
import time
from core_common import CLASSIFIER_VER
from decimal import Decimal
from decimal import ROUND_HALF_EVEN
import logging

log = logging.getLogger('tj-core')


class ExfFutMixin:

    EXF_FUT_V = 1

    EXF_FUT_MIG_MIN = Decimal("1")

    EXF_FUT_REST_REL = Decimal("0.05")

    _EXF_ATOM_RE = re.compile(r"^(되돌림|확장 이중 계상 정리|대출 첫 편입 흡수)\(대사 (\d+) ")

    _EXF_DIFF_RE = re.compile(r"^되돌림\(대사 (\d+) 차이 (-?[0-9]+(?:\.[0-9]+)?)\)")

    def _exf_revert_rows(self) -> list:
        out = []
        try:
            fh = open(self.EXF_REVERT_LOG, "r", encoding="utf-8")
        except FileNotFoundError:
            return out
        except OSError as e9:
            raise ValueError(f"되돌림 감사 기록 읽기 실패: {e9}") from e9
        with fh:
            for i9, ln9 in enumerate(fh):
                if not ln9.strip():
                    continue
                try:
                    d9 = json.loads(ln9)
                except ValueError as e9:
                    raise ValueError(f"되돌림 감사 기록 손상: 줄 {i9 + 1}") from e9
                if not isinstance(d9, dict):
                    raise ValueError(f"되돌림 감사 기록 형식 오류: 줄 {i9 + 1}")
                self._exf_revert_row_ok(d9, i9 + 1)
                d9["_i"] = i9
                out.append(d9)
        return out

    _EXF_WHY_OK = (re.compile(r"^(되돌림|확장 이중 계상 정리)\(대사 \d+ 차이 -?[0-9]+(?:\.[0-9]+)?\)$"),
                   re.compile(r"^대출 첫 편입 흡수\(대사 \d+ 부채 차이 -?[0-9]+(?:\.[0-9]+)?\)$"),
                   re.compile(r"^전환 흡수 \S.*$"),
                   re.compile(r"^.+ (?:흡수|늦은 상쇄 되돌림)\(대사 \d+ 구간\)$"))

    @classmethod
    def _exf_revert_row_ok(cls, d9: dict, n9: int) -> None:
        def _int(k):
            v = d9.get(k)
            if isinstance(v, bool) or not re.fullmatch(r"-?[0-9]+", str(v if v is not None else "")):
                raise ValueError(f"되돌림 감사 기록 필드 손상: 줄 {n9} {k}")
            return int(v)
        for k9 in ("ts", "posting_id", "leg_seq", "event_ts", "asset_id"):
            _int(k9)
        old9, new9 = _int("old_qty_base"), _int("new_qty_base")
        loc9, sid9, why9 = d9.get("loc"), d9.get("source_id"), d9.get("why")
        if not isinstance(loc9, str) or not loc9.startswith("exchange:") or not isinstance(sid9, str) or not sid9:
            raise ValueError(f"되돌림 감사 기록 필드 손상: 줄 {n9} loc·source_id")
        if not isinstance(why9, str) or not any(r9.match(why9) for r9 in cls._EXF_WHY_OK):
            raise ValueError(f"되돌림 감사 기록 사유 손상: 줄 {n9}")
        if old9 == 0 or abs(new9) >= abs(old9) or (new9 != 0 and (new9 > 0) != (old9 > 0)):
            raise ValueError(f"되돌림 감사 기록 수량 손상: 줄 {n9} ({old9} → {new9})")

    @classmethod
    def _exf_atom(cls, e: dict):
        m9 = cls._EXF_ATOM_RE.match(str(e.get("why") or ""))
        return (m9.group(1), int(m9.group(2))) if m9 else (None, None)

    def _exf_first_bts(self, ex: str):
        b0 = None
        for r in self.conn.execute("SELECT source_id FROM postings WHERE source_ns=? AND event='EXF_ADJUST'", (f"{ex}:recon",)):
            b9 = self._exf_bts(r[0])
            if b9 is not None and (b0 is None or b9 < b0):
                b0 = b9
        try:
            t9 = self.conn.execute("SELECT min(bts) FROM exf_adj_tomb WHERE ex=?", (ex,)).fetchone()[0]
        except sqlite3.OperationalError:
            t9 = None
        if t9 is not None and (b0 is None or int(t9) < b0):
            b0 = int(t9)
        return b0

    def _exf_fut_plan_sym(self, ex: str, sym: str, evs: list, log9: list, done9: int, first9, fut_b=frozenset(), cur_ok=False):
        loc, ns, pfx = f"exchange:{ex}", f"{ex}:recon", f"exfrecon:{sym}:"
        rows = [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.source_id, p.leg_seq, p.event_ts, p.qty_base, p.asset_id, p.classifier_ver, a.decimals"
            " FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?", (ns, loc, sym)).fetchall()]
        rows = [r for r in rows if str(r["source_id"]).startswith(pfx) and self._exf_bts(r["source_id"]) is not None]
        lg = [e for e in log9 if e.get("loc") == loc and str(e.get("source_id") or "").startswith(pfx)
              and self._exf_bts(e.get("source_id")) is not None]
        recs = {self._exf_bts(r["source_id"]) for r in rows} | {self._exf_bts(e["source_id"]) for e in lg}
        recs |= {b9 for k9, b9 in map(self._exf_atom, lg) if k9}
        tomb9 = set()
        try:
            tomb9 = {int(t[0]) for t in self.conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex=? AND sym=?", (ex, sym))}
        except sqlite3.OperationalError:
            pass
        recs |= tomb9
        recs |= set(fut_b)
        recs = sorted(b9 for b9 in recs if b9 is not None and b9 <= done9)
        last9 = recs[-1] if recs else None
        if first9 is None or not evs:
            return None, last9
        if cur_ok and last9 is not None and last9 < done9:
            lo9 = max([last9] + [b9 for b9 in fut_b if b9 <= done9])
            tail9 = sum((a9 for _t9, tm9, a9 in evs if lo9 * 1000 < tm9 <= done9 * 1000), Decimal(0))
            if abs(tail9) >= self.EXF_FUT_MIG_MIN and done9 > first9 + self.EXF_INIT_PHASE:
                return {"ex": ex, "sym": sym, "hold": f"마지막 흔적 대사 뒤 정산 합 {tail9} — 대사 줄·감사 기록 없음(이미 반영 여부 근거 없음)",
                        "skip": []}, last9
        fwin, cands, prev = {}, [], None
        for b9 in recs:
            if prev is not None and b9 > first9 + self.EXF_INIT_PHASE and b9 not in fut_b:
                sel9 = [(t9, a9) for t9, tm9, a9 in evs if prev * 1000 < tm9 <= b9 * 1000]
                if abs(sum((a9 for _t, a9 in sel9), Decimal(0))) >= self.EXF_FUT_MIG_MIN:
                    cands.append(b9)
                    fwin[b9] = sel9
            prev = b9
        if not cands:
            return None, last9
        aid, dec = self._exf_main_inst(ex, sym)
        scale = Decimal(10) ** int(dec)
        live9 = {self._exf_bts(r["source_id"]) for r in rows}
        aud9 = {self._exf_bts(e["source_id"]) for e in lg}
        mv9 = self._exf_latefix_moved()
        miss9 = sorted(b9 for b9 in tomb9 if b9 <= done9 and b9 not in live9 and b9 not in aud9 and b9 not in fut_b and (ex, sym, b9) not in mv9)
        if miss9:
            log.error("선물 정산 재배치 불가: %s %s — 지운 대사 %d건의 되돌림 감사 기록 없음(%s)", ex, sym, len(miss9), miss9[:5])
            return {"ex": ex, "sym": sym, "hold": f"지운 대사 {len(miss9)}건의 되돌림 감사 기록 없음(대사 시각 {miss9[:5]})", "skip": []}, last9
        decs9 = {8 if r["decimals"] is None else int(r["decimals"]) for r in rows}
        if decs9 - {int(dec)}:
            log.warning("선물 정산 재배치 건너뜀: %s %s — 자리수 %s", ex, sym, sorted(decs9))
            return {"ex": ex, "sym": sym, "hold": f"자리수 여럿 {sorted(decs9)}", "skip": []}, last9
        base = {(str(r["source_id"]), int(r["leg_seq"])): r for r in rows}
        skip = {}
        repl = set(cands)
        while True:
            changed9 = True
            while changed9:
                changed9 = False
                for b9 in sorted(repl):
                    why9 = None
                    for e in lg:
                        k9, p9 = self._exf_atom(e)
                        if p9 == b9 and k9 != "되돌림":
                            why9 = f"되돌림 말고 다른 흡수({k9})"
                            break
                        if self._exf_bts(e["source_id"]) == b9 and (k9 != "되돌림" or p9 not in repl):
                            why9 = "만든 행을 후보 아닌 것이 줄임"
                            break
                    if why9 is None and any(int(base[k]["asset_id"]) != int(aid) for k in base if k[0] == f"{pfx}{b9}"):
                        why9 = "주 자산이 아닌 행"
                    if why9:
                        repl.discard(b9)
                        skip[b9] = why9
                        changed9 = True
            state = {k: {"ts": int(r["event_ts"]), "aid": int(r["asset_id"]), "qb": int(r["qty_base"])} for k, r in base.items()}
            undo, bad9 = {}, None
            for b9 in sorted(repl, reverse=True):
                atoms = sorted((e for e in lg if self._exf_atom(e)[1] == b9), key=lambda e: e["_i"])
                for e in reversed(atoms):
                    k = (str(e["source_id"]), int(e.get("leg_seq") or 0))
                    try:
                        old9, new9 = int(e["old_qty_base"]), int(e["new_qty_base"])
                    except (KeyError, TypeError, ValueError):
                        bad9 = (b9, "감사 기록 형식 오류")
                        break
                    if (state[k]["qb"] if k in state else 0) != new9 or int(e.get("asset_id") or 0) != int(aid):
                        bad9 = (b9, "되돌린 행이 그 뒤 바뀜")
                        break
                    state[k] = {"ts": state[k]["ts"] if k in state else int(e["event_ts"]), "aid": int(aid), "qb": old9}
                if bad9:
                    break
                mine = {k: v for k, v in state.items() if k[0] == f"{pfx}{b9}"}
                for k in mine:
                    del state[k]
                d9 = sum(v["qb"] for v in mine.values()) + sum(int(e["new_qty_base"]) - int(e["old_qty_base"]) for e in atoms)
                tol9 = len(mine) + len(atoms) + 1
                for e in atoms:
                    m9 = self._EXF_DIFF_RE.match(str(e.get("why") or ""))
                    if m9 and int(m9.group(1)) == b9 and abs(Decimal(m9.group(2)) * scale - d9) >= tol9:
                        bad9 = (b9, f"차이 기록 {m9.group(2)} ≠ 재구성 {Decimal(d9) / scale}")
                        break
                if bad9:
                    break
                undo[b9] = (d9, mine)
            if bad9:
                repl.discard(bad9[0])
                skip[bad9[0]] = bad9[1]
                continue
            break
        if not repl:
            return ({"ex": ex, "sym": sym, "skip": sorted(skip.items())} if skip else None), last9
        fut = []
        for b9 in sorted(repl):
            d9, mine = undo[b9]
            legs9 = self._exf_fut_legs(fwin[b9], scale)
            res9 = d9 - sum(q9 for _t, q9 in legs9)
            l2 = {k: v for k, v in mine.items() if k[1] == 2}
            l2s = sum(v["qb"] for v in l2.values())
            rest9 = res9
            if len(l2) == 1 and l2s != 0 and res9 != 0 and (l2s > 0) == (res9 > 0):
                (k2, v2), = l2.items()
                q2 = l2s if abs(l2s) <= abs(res9) else res9
                state[k2] = dict(v2, qb=int(q2))
                rest9 = res9 - q2
            f9 = sum(q9 for _t, q9 in legs9)
            if abs(rest9) > max(self.EXF_FUT_MIG_MIN * scale, abs(Decimal(f9)) * self.EXF_FUT_REST_REL):
                return {"ex": ex, "sym": sym, "hold": f"대사 {b9} 차이가 선물 정산으로 설명 안 됨(남는 몫 {Decimal(rest9) / scale} · 선물 "
                                                      f"{Decimal(f9) / scale}) — 근거 부족", "skip": []}, last9
            if rest9:
                k0 = (f"{pfx}{b9}", 0)
                state[k0] = {"ts": int(b9), "aid": int(aid), "qb": int(rest9)}
            fut += [{"sid": f"{pfx}{b9}", "leg": i9, "ts": int(t9), "qb": str(q9)} for i9, (t9, q9) in enumerate(legs9)]
        late_mv = self._exf_fut_late_place(ex, sym, base, state, repl, aid, scale)
        ops = {"del": [], "upd": [], "ins": []}
        for k in sorted(set(base) | set(state)):
            a9, s9 = base.get(k), state.get(k)
            if a9 is not None and (s9 is None or s9["qb"] == 0):
                ops["del"].append({"pid": int(a9["posting_id"]), "sid": k[0], "leg": k[1], "ts": int(a9["event_ts"]), "aid": int(a9["asset_id"]),
                                   "qb": str(a9["qty_base"]), "cv": int(a9["classifier_ver"] or CLASSIFIER_VER)})
            elif a9 is None and s9 is not None and s9["qb"] != 0:
                ops["ins"].append({"sid": k[0], "leg": k[1], "ts": int(s9["ts"]), "aid": int(s9["aid"]), "qb": str(s9["qb"])})
            elif a9 is not None and (int(a9["qty_base"]) != s9["qb"] or int(a9["event_ts"]) != s9["ts"]):
                ops["upd"].append({"pid": int(a9["posting_id"]), "sid": k[0], "leg": k[1], "ts": int(a9["event_ts"]), "qb": str(a9["qty_base"]),
                                   "ts_new": int(s9["ts"]), "qb_new": str(s9["qb"])})
        before9 = sum(int(r["qty_base"]) for r in rows)
        after9 = sum(v["qb"] for v in state.values()) + sum(int(f9["qb"]) for f9 in fut)
        if before9 != after9:
            log.error("선물 정산 재배치 건너뜀: %s %s — 합 불일치 %d ≠ %d", ex, sym, before9, after9)
            return {"ex": ex, "sym": sym, "err": f"합 불일치 {before9} ≠ {after9}", "skip": sorted(skip.items())}, last9
        ts9 = [o["ts"] for o in ops["del"] + ops["upd"] + ops["ins"]] + [o["ts_new"] for o in ops["upd"]] + [f9["ts"] for f9 in fut]
        return ({"ex": ex, "sym": sym, "loc": loc, "aid": int(aid), "dec": int(dec), "cands": sorted(repl), "skip": sorted(skip.items()),
                 "del": ops["del"], "upd": ops["upd"], "ins": ops["ins"], "fut": fut, "t_from": min(ts9) if ts9 else None,
                 "f_sum": str(sum(Decimal(int(f9["qb"])) for f9 in fut) / scale), "late": late_mv}, last9)

    def _exf_fut_late_place(self, ex: str, sym: str, base: dict, state: dict, repl: set, aid: int, scale: Decimal) -> list:
        if sym in acct_norm.ex_off_ledger(ex):
            return []
        out, bnds9 = [], None
        for k in sorted(list(state)):
            sid9, leg9 = k
            b9 = self._exf_bts(sid9)
            s9 = state[k]
            a9 = base.get(k)
            if (leg9 != 0 or b9 is None or not str(sid9).startswith("exfrecon:") or b9 in repl or s9["qb"] >= 0 or abs(int(s9["ts"]) - b9) > 60
                    or (a9 is not None and int(a9["qty_base"]) == s9["qb"])):
                continue
            q9 = Decimal(s9["qb"]) / scale
            hit9 = None
            for bt in self._exf_late_batches(ex):
                if not (bt["o1"] <= b9 <= bt["o1"] + self.EXF_LATE_RECON_WIN) or sym not in bt["dl"]:
                    continue
                if sym in bt["mixed"]:
                    hit9 = None
                    break
                dl9 = bt["dl"][sym]
                net9 = sum((a for _t, a in dl9), Decimal(0))
                if net9 <= 0 or abs(abs(q9) - net9) > net9 * self.EXF_LATE_REL:
                    continue
                if bnds9 is None:
                    bnds9 = self._exf_bounds_q(self.conn, ex, sym)
                grp9 = {}
                for t9, a9q in dl9:
                    grp9.setdefault(self._exf_bucket(bnds9, t9), []).append((t9, a9q))
                cl9 = sorted(((t0, t1, n9, bk9) for bk9, lst9 in grp9.items() for t0, t1, n9 in self._exf_late_clusters(lst9)), key=lambda c: (c[1], c[0]))
                if any(c[2] <= 0 for c in cl9):
                    hit9 = None
                    break
                dup9 = self.conn.execute(
                    "SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.location=? AND upper(a.symbol)=?"
                    " AND p.source_id LIKE ? AND p.event_ts BETWEEN ? AND ?", (f"{ex}:recon", f"exchange:{ex}", sym, f"{self.EXF_LATE_PFX}{sym}:%",
                                                                               int(cl9[0][0]), int(cl9[-1][1]) + self.EXF_LATE_DT)).fetchone()[0]
                if dup9:
                    hit9 = None
                    break
                hit9 = (net9, cl9)
                break
            if hit9 is None:
                continue
            net9, cl9 = hit9
            net_b = int((net9 * scale).to_integral_value())
            parts, used = [], 0
            for i9, (t0, t1, n9, bk9) in enumerate(cl9):
                qb9 = (net_b - used) if i9 == len(cl9) - 1 else int((n9 * scale).to_integral_value())
                used += qb9
                t_off = int(t1) + self.EXF_LATE_DT
                sid_l = self._exf_late_sid(sym, t_off, bk9)
                r9 = self.conn.execute("SELECT MAX(leg_seq) FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                                       (f"{ex}:recon", sid_l)).fetchone()
                leg_l = 0 if r9 is None or r9[0] is None else int(r9[0]) + 1
                while (sid_l, leg_l) in state:
                    leg_l += 1
                state[(sid_l, leg_l)] = {"ts": t_off, "aid": int(aid), "qb": -qb9}
                parts.append({"sid": sid_l, "leg": leg_l, "ts": t_off, "qb": str(-qb9)})
            rem9 = int(s9["qb"]) + net_b
            state[k] = dict(s9, qb=rem9)
            out.append({"sid": sid9, "bts": b9, "q": str(s9["qb"]), "net": str(net_b), "parts": parts, "rem": str(rem9)})
            log.info("선물 정산 재배치: %s %s 되살린 대사 %s 음수 %s 중 %s = 늦은 체결 묶음 상쇄 → 묶음 직후 %d줄(대사 시각 남는 몫 %s)", ex, sym, b9,
                     format(q9, "f"), format(net9, "f"), len(parts), format(Decimal(rem9) / scale, "f"))
        return out

    def _exf_fut_place_plan(self, only=None):
        plan, curs = [], {}
        self.__dict__.pop("_exf_late_bcache", None)
        self.__dict__.pop("_exf_lfm", None)
        try:
            lf9 = self._meta_get("exf_revert_log_fail")
            if lf9:
                raise ValueError(f"되돌림 감사 기록 쓰기 실패 이력(meta exf_revert_log_fail {lf9}) — 확인 뒤 표식을 지워야 이관")
            log9 = self._exf_revert_rows()
        except ValueError as e9:
            return [{"ex": ex9, "sym": "*", "err": str(e9), "skip": []} for ex9 in self.EXF_FUT_EX
                    if self._meta_get(f"recon_done_exf_{ex9}") and (only is None or ex9 in only)], {}
        for ex in self.EXF_FUT_EX:
            if only is not None and ex not in only:
                continue
            d9 = self._meta_get(f"recon_done_exf_{ex}")
            if not d9:
                continue
            if ex == "binance":
                try:
                    srcb9 = json.loads(self._meta_get("recon_src_exf_binance") or "null")
                except (TypeError, ValueError):
                    srcb9 = None
                if not isinstance(srcb9, list) or not self._exf_has_fut_src(srcb9):
                    continue
            done9 = int(float(d9))
            try:
                from9 = int(float(self._meta_get(f"exf_fut_from_{ex}")))
            except (TypeError, ValueError):
                from9 = None
            hi9 = done9 if from9 is None else min(done9, from9)
            _fts, evs9 = self._exf_fut_events(ex)
            if _fts is None and not os.path.exists(paths.state(f"futures_{ex}.json")):
                continue
            if not _fts or int(_fts) < hi9:
                plan.append({"ex": ex, "sym": "*", "err": f"선물 정산 파일이 없거나 손상·낡음(파일 {_fts} < 마지막 대사 {hi9})", "skip": []})
                continue
            first9 = self._exf_first_bts(ex) if evs9 else None
            for sym in sorted(evs9):
                fb9 = {b9 for (s9,) in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE source_ns=? AND event='EXF_ADJUST'"
                                                           " AND source_id LIKE ?", (f"{ex}:{histmark.EXF_FUT_NS}", f"exfrecon:{sym}:%"))
                       for b9 in (self._exf_bts(s9),) if b9 is not None}
                m9, last9 = self._exf_fut_plan_sym(ex, sym, evs9[sym], log9, hi9, first9, fb9, cur_ok=(hi9 == done9))
                if m9:
                    plan.append(m9)
                if last9 is not None and last9 < done9 and hi9 == done9 and not (m9 and m9.get("hold")):
                    curs.setdefault(ex, {})[sym] = int(last9)
        return plan, curs

    def _exf_fut_place_apply(self, plan: list) -> int:
        n = 0
        for m in plan:
            if not m.get("cands"):
                continue
            ex, loc, sym = m["ex"], m["loc"], m["sym"]
            for o in m["del"] + m["upd"]:
                r9 = self.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE posting_id=?", (o["pid"],)).fetchone()
                if (r9 is None or r9["source_ns"] != f"{ex}:recon" or r9["source_id"] != o["sid"] or int(r9["leg_seq"]) != o["leg"]
                        or int(r9["event_ts"]) != o["ts"] or str(r9["qty_base"]) != o["qb"]):
                    raise ValueError(f"재배치 대상이 계획 뒤 바뀜 {o['sid']} leg {o['leg']}")
            tot9 = 0
            for o in m["del"]:
                self._amend_leg(o["pid"], int(o["aid"]), loc, -int(o["qb"]))
                tot9 -= int(o["qb"])
            for o in m["upd"]:
                self._amend_leg(o["pid"], int(m["aid"]), loc, int(o["qb_new"]) - int(o["qb"]), qb_new=o["qb_new"], ts=int(o["ts_new"]))
                recon_adj.note_fix(self.conn, "K7f", o["pid"], "fut_replace")
                tot9 += int(o["qb_new"]) - int(o["qb"])
            for ns9, lst9 in ((f"{ex}:recon", m["ins"]), (f"{ex}:{histmark.EXF_FUT_NS}", m["fut"])):
                for o in lst9:
                    if not self._post_leg("exchange", ns9, o["sid"], int(o["leg"]), int(o["ts"]), int(o.get("aid") or m["aid"]), loc,
                                          o["qb"], None, None, "opening", "EXF_ADJUST"):
                        raise ValueError(f"재배치 줄 충돌 {ns9} {o['sid']} leg {o['leg']}")
                    tot9 += int(o["qb"])
                    recon_adj.note(self.conn, "K7f", ("exchange", ns9, o["sid"], int(o["leg"])), "fut_replace")
            if tot9 != 0:
                raise ValueError(f"재배치 합 불일치 {ex} {sym}: {tot9}")
            for b9 in m["cands"]:
                try:
                    self.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)", (ex, sym, int(b9)))
                except sqlite3.OperationalError:
                    pass
            n += 1
        return n

    EXF_FUT_WAIT_META = "exf_fut_place_wait"

    EXF_FUT_BACKUP_MAX_AGE = 36 * 3600

    def _exf_fut_place_scope(self):
        p9 = str(self._meta_get("exf_fut_place_v") or "").split(":")
        if p9[0] != str(self.EXF_FUT_V):
            return "todo", None
        if len(p9) >= 2 and p9[1] == "undone":
            return "undone", None
        try:
            w9 = json.loads(self._meta_get(self.EXF_FUT_WAIT_META) or "null")
        except (TypeError, ValueError):
            w9 = None
        if isinstance(w9, dict) and w9.get("v") == self.EXF_FUT_V and isinstance(w9.get("ex"), dict) and w9["ex"]:
            return "partial", {str(x) for x in w9["ex"]}
        return "done", None

    def _exf_fut_backup_ok(self):
        try:
            st9 = statefile.read_json(paths.state("backups", "backup_status.json"), {}) or {}
            p9 = str(st9.get("last_path") or "")
            if time.time() - float(st9.get("last_ok") or 0) <= self.EXF_FUT_BACKUP_MAX_AGE and p9 and os.path.isfile(p9):
                return p9
        except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [optional]
            calcguard.swallowed("core_exf:ExfMixin._exf_fut_backup_ok", _cg9)
            pass
        return None

    def _exf_fut_place_once(self, expect=None, redo=False, auto=False):
        sc, pend = self._exf_fut_place_scope()
        if sc == "done" or (sc == "undone" and not redo):
            return None
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            sc, pend = self._exf_fut_place_scope()
            if sc == "done" or (sc == "undone" and not redo):
                self.conn.rollback()
                return None
            plan, curs = self._exf_fut_place_plan(only=pend)
            if expect is not None and json.loads(json.dumps(plan)) != json.loads(json.dumps(expect)):
                self.conn.rollback()
                log.error("선물 정산 재배치 거부 — 잠금 안 계획(%d)이 검토한 계획(%d)과 다름(원장이 그 사이 바뀜)", len(plan), len(expect))
                return False
            errx = {}
            for m in plan:
                if m.get("err"):
                    errx.setdefault(m["ex"], f"{m['sym']}: {m['err']}" if m.get("sym") not in (None, "*") else str(m["err"]))
            scope9 = [ex9 for ex9 in self.EXF_FUT_EX if (pend is None or ex9 in pend) and self._meta_get(f"recon_done_exf_{ex9}")]
            act9 = [m for m in plan if m.get("cands") and m["ex"] not in errx]
            bk9 = None
            if auto and act9:
                bk9 = self._exf_fut_backup_ok()
                if bk9 is None:
                    for m in act9:
                        errx.setdefault(m["ex"], "적용 전 원장 백업 없음(36시간 안 정기 백업 — state/backups · 디스크 여유 확인)")
                    act9 = []
            okx9 = [ex9 for ex9 in scope9 if ex9 not in errx]
            if errx and not okx9:
                self.conn.rollback()
                self._exf_fut_place_wait_set(errx)
                if time.time() - float(self.__dict__.get("_exf_fut_err_log", 0) or 0) >= 3600:
                    self._exf_fut_err_log = time.time()
                    log.error("★선물 정산 재배치 보류 — 거래소 %d곳: %s★ (tools/exf_fut_place.py 로 확인)", len(errx),
                              "; ".join(f"{k} {v}" for k, v in sorted(errx.items())[:4]))
                return None
            for m in act9:
                m["tomb_new"] = [int(b9) for b9 in m["cands"] if self.conn.execute(
                    "SELECT 1 FROM exf_adj_tomb WHERE ex=? AND sym=? AND bts=?", (m["ex"], m["sym"], int(b9))).fetchone() is None]
            keep9 = [m for m in plan if m["ex"] not in errx]
            n_prev = 0
            undo_p9 = paths.state(f"exf_fut_place_v{self.EXF_FUT_V}.json")
            if sc == "partial":
                try:
                    n_prev = int(str(self._meta_get("exf_fut_place_v") or "").split(":")[2])
                except (IndexError, ValueError):
                    n_prev = 0
            if act9:
                prev9 = None
                if sc == "partial" and n_prev:
                    prev9 = statefile.read_json(undo_p9, None)
                    if not (isinstance(prev9, dict) and prev9.get("v") == self.EXF_FUT_V and isinstance(prev9.get("plan"), list)):
                        raise ValueError("앞 회차 되돌리기 자료가 없거나 다름 — 이어 붙일 수 없음")
                cu9 = {k9: v9 for k9, v9 in curs.items() if k9 not in errx}
                statefile.atomic_write_json(undo_p9, {"ts": int(time.time()), "v": self.EXF_FUT_V,
                                                   "plan": (prev9["plan"] if prev9 else []) + keep9,
                                                   "curs": dict((prev9 or {}).get("curs") or {}, **cu9)})
            n = self._exf_fut_place_apply(act9) if act9 else 0
            if n:
                self._exf_hist_touch(min((m["t_from"] for m in act9 if m.get("t_from") is not None), default=None))
            for ex9 in okx9:
                d9 = self._meta_get(f"recon_done_exf_{ex9}")
                if self._meta_get(f"exf_fut_cur_{ex9}") is None:
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                      (f"exf_fut_cur_{ex9}", json.dumps({"t": int(float(d9)), "s": curs.get(ex9) or {}}, sort_keys=True)))
                if self._meta_get(f"exf_fut_from_{ex9}") is None:
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_fut_from_{ex9}", str(int(float(d9)))))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', ?)", (f"{self.EXF_FUT_V}:{int(time.time())}:{n_prev + n}",))
            dbm.bump_data_rev(self.conn, 1)
            if errx:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (self.EXF_FUT_WAIT_META, json.dumps({"v": self.EXF_FUT_V, "ex": errx}, ensure_ascii=False, sort_keys=True)))
            else:
                self.conn.execute("DELETE FROM meta WHERE k=?", (self.EXF_FUT_WAIT_META,))
            self.conn.commit()
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_exf:ExfMixin._exf_fut_place_once", e)
            self.conn.rollback()
            log.error("선물 정산 재배치 보류(되돌림 · 다음 대사에 다시): %s", e)
            return None
        self._exf_fut_place_wait_set(errx)
        for m in plan:
            if m.get("err"):
                log.error("선물 정산 재배치: %s %s 통화 전체 건너뜀 — %s", m["ex"], m["sym"], m["err"])
            if m.get("hold"):
                log.warning("선물 정산 재배치: %s %s 보류(옛 배치 유지 — 근거 부족): %s", m["ex"], m["sym"], m["hold"])
            for b9, why9 in m.get("skip") or ():
                log.warning("선물 정산 재배치: %s %s 대사 %s 건너뜀 — %s", m["ex"], m["sym"], b9, why9)
        if errx:
            log.warning("★선물 정산 재배치 — 거래소 %s 는 대기(나머지는 옮김 · 다음 대사에 그 거래소만 다시): %s★", ",".join(sorted(errx)),
                        "; ".join(f"{k} {v}" for k, v in sorted(errx.items())[:4]))
        if n:
            log.warning("★선물 정산 재배치 %d개 통화(대사 %d건 — 지난날 소급·되돌림 → 정산 시각) — 원장 합 무변, 지난 곡선 무효화%s★", n,
                        sum(len(m["cands"]) for m in act9), f" · 적용 전 원장 백업 {bk9}" if bk9 else "")
            self._exf_hist_flush()
        return n

    def _exf_fut_place_wait_set(self, errx: dict) -> None:
        new9 = {str(k): str(v)[:200] for k, v in (errx or {}).items()}
        old9 = self.__dict__.get("_exf_fut_place_wait")
        if old9 == new9 and (not new9 or time.time() - float(self.__dict__.get("_exf_fut_place_wait_at") or 0) < 3600):
            return
        since9 = dict(self.__dict__.get("_exf_fut_place_since") or {})
        for k in new9:
            since9.setdefault(k, int(time.time()))
        self._exf_fut_place_since = {k: v for k, v in since9.items() if k in new9}
        self._exf_fut_place_wait = new9
        self._exf_fut_place_wait_at = time.time()
        self._exf_fut_wait_save()

    EXF_FUT_EX = ("binance", "bybit", "okx")

    EXF_FUT_KINDS = frozenset(("REALIZED", "FUNDING", "FEE"))

    EXF_FUT_GROUP_S = 60

    @staticmethod
    def _exf_fut_sym(ex: str, symbol) -> str:
        s9 = str(symbol or "").upper()
        if ex == "okx":
            p9 = s9.split("-")
            return p9[1] if len(p9) >= 3 and p9[1] in ("USDT", "USDC") else ""
        if s9.endswith("USDT"):
            return "USDT"
        if s9.endswith("USDC") or (ex == "bybit" and s9.endswith("PERP")):
            return "USDC"
        return ""

    @staticmethod
    def _exf_has_fut_src(src9) -> bool:
        return any(str(x9).rsplit(":", 1)[-1] == "futures" for x9 in (src9 or ()))

    def _exf_fut_events(self, ex: str):
        p9 = paths.state(f"futures_{ex}.json")
        try:
            mt9 = os.path.getmtime(p9)
        except OSError:
            return None, {}
        cache9 = self.__dict__.setdefault("_exf_fut_cache", {})
        c9 = cache9.get(ex)
        if c9 and c9[0] == mt9:
            return c9[1], c9[2]
        try:
            d9 = statefile.read_json(p9, {}) or {}
        except (Exception, SystemExit) as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_exf:ExfMixin._exf_fut_events", e9)
            log.warning("%s 선물 정산 파일 읽기 실패: %s", ex, e9)
            return 0, {}
        out9 = {}
        evs9 = d9.get("events") if isinstance(d9, dict) else None
        for r9 in (evs9 if isinstance(evs9, list) else ()):
            if not isinstance(r9, dict) or r9.get("kind") not in self.EXF_FUT_KINDS:
                continue
            s9 = self._exf_fut_sym(ex, r9.get("symbol"))
            a0 = r9.get("amount")
            if not s9 or isinstance(a0, bool) or isinstance(r9.get("t"), bool):
                continue
            as9 = r9.get("asset")
            if isinstance(as9, str) and as9.strip():
                as9 = as9.strip().upper()
                if not as9.isalnum() or len(as9) > 20:
                    continue
                s9 = as9
            try:
                t9 = int(r9.get("t") or 0)
                a9 = Decimal(str(a0 if a0 is not None else 0))
            except (TypeError, ValueError, ArithmeticError):
                continue
            if t9 <= 0 or not a9.is_finite() or a9 == 0:
                continue
            out9.setdefault(s9, []).append((t9 // 1000, t9, a9))
        for v9 in out9.values():
            v9.sort(key=lambda x: x[1])
        try:
            ts9 = int((d9.get("ts") if isinstance(d9, dict) else 0) or 0) or None
            cov9 = d9.get("inc_cov_ts") if isinstance(d9, dict) else None
            if ts9 and isinstance(cov9, (int, float)) and not isinstance(cov9, bool) and int(cov9) < ts9:
                ts9 = max(0, int(cov9))
        except (TypeError, ValueError):
            ts9 = None
        cache9[ex] = (mt9, ts9, out9)
        return ts9, out9

    def _exf_fut_cur(self, ex: str, done_ts) -> dict:
        try:
            c9 = json.loads(self._meta_get(f"exf_fut_cur_{ex}") or "null")
        except (ValueError, TypeError):
            c9 = None
        if not isinstance(c9, dict) or not isinstance(c9.get("t"), int) or isinstance(c9.get("t"), bool):
            return {"t": int(float(done_ts or 0)), "s": {}}
        s9 = c9.get("s") if isinstance(c9.get("s"), dict) else {}
        return {"t": int(c9["t"]), "s": {str(k): int(v) for k, v in s9.items() if isinstance(v, int) and not isinstance(v, bool)}}

    def _exf_fut_window(self, ex: str, bal: dict, bts: int, done_ts) -> dict:
        if ex not in self.EXF_FUT_EX or not done_ts:
            return {}
        src9 = bal.get("sources") if isinstance(bal, dict) else None
        if ex == "binance" and not (isinstance(src9, list) and self._exf_has_fut_src(src9)):
            return {}
        fts9, evs9 = self._exf_fut_events(ex)
        if not fts9 or not evs9:
            return {}
        hi9 = min(int(bts), int(fts9))
        cur9 = self._exf_fut_cur(ex, done_ts)
        out9 = {}
        for s9, lst9 in evs9.items():
            lo9 = cur9["s"].get(s9, cur9["t"])
            if hi9 <= lo9:
                continue
            sel9 = [(t9, a9) for t9, tm9, a9 in lst9 if lo9 * 1000 < tm9 <= hi9 * 1000]
            if sel9:
                out9[s9] = sel9
        return out9

    EXF_FUT_WAIT_S = 3 * 3600

    def _exf_fut_hold(self, ex: str, bal: dict, bts: int, done_ts, now: int) -> bool:
        if self._exf_fut_wait_boot():
            self._exf_fut_wait_save()
        w9 = self.__dict__.setdefault("_exf_fut_wait", {})
        if not done_ts or ex not in self.EXF_FUT_EX:
            self._exf_fut_wait_end(ex)
            return False
        src9 = bal.get("sources") if isinstance(bal, dict) else None
        if ex == "binance" and not (isinstance(src9, list) and self._exf_has_fut_src(src9)):
            self._exf_fut_wait_end(ex)
            return False
        fts9, _e9 = self._exf_fut_events(ex)
        if fts9 is None or int(fts9) >= int(bts):
            self._exf_fut_wait_end(ex)
            return False
        new9 = ex not in w9
        t0 = w9.setdefault(ex, [now, 0, False])
        if now - t0[0] < self.EXF_FUT_WAIT_S:
            if now - t0[1] >= 900:
                t0[1] = now
                log.info("%s 대사 대기: 선물 정산 파일(%s)이 잔고 시각(%d)을 아직 못 덮음 — 수집 뒤 다시(%.0f분째 · 상한 %d분)", ex, fts9, int(bts),
                         (now - t0[0]) / 60, self.EXF_FUT_WAIT_S // 60)
                self._exf_fut_wait_save()
            elif new9:
                self._exf_fut_wait_save()
            return True
        if not t0[2]:
            log.warning("★%s 선물 정산 파일이 %d분 넘게 잔고를 못 덮음 — 종전 규칙으로 대사(파일 뒤 정산은 지난날로 소급될 수 있음 · 이중 계상 없음)★",
                        ex, self.EXF_FUT_WAIT_S // 60)
            t0[1], t0[2] = now, True
            fb9 = self.__dict__.setdefault("_exf_fut_fb", [])
            fb9.append({"ex": ex, "at": int(now), "since": int(t0[0])})
            del fb9[:-10]
            self._exf_fut_wait_save()
        elif now - t0[1] >= 900:
            t0[1] = now
            self._exf_fut_wait_save()
        return False

    EXF_FUT_WAIT_PATH = paths.StatePath("exf_fut_wait.json")

    def _exf_fut_wait_boot(self) -> bool:
        if self.__dict__.get("_exf_fut_wait_init"):
            return False
        self._exf_fut_wait_init = True
        w9 = self.__dict__.setdefault("_exf_fut_wait", {})
        try:
            old9 = statefile.read_json(self.EXF_FUT_WAIT_PATH, {}) or {}
            for e9, it9 in ((old9.get("wait") if isinstance(old9.get("wait"), dict) else {}) or {}).items():
                if e9 in self.EXF_FUT_EX and isinstance(it9, dict) and isinstance(it9.get("since"), int) and not isinstance(it9.get("since"), bool):
                    w9.setdefault(e9, [int(it9["since"]), 0, bool(it9.get("fallback"))])
        except (Exception, SystemExit) as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("core_exf:ExfMixin._exf_fut_wait_boot", e9)
            log.warning("선물 대사 대기 표식 읽기 실패(처음부터): %s", e9)
        return True

    def _exf_fut_wait_end(self, ex: str) -> None:
        self._exf_fut_wait_boot()
        if self.__dict__.get("_exf_fut_wait", {}).pop(ex, None) is not None:
            self._exf_fut_wait_save()

    def _exf_fut_wait_save(self) -> None:
        try:
            self._exf_fut_wait_boot()
            w9 = self.__dict__.get("_exf_fut_wait") or {}
            fb9 = list(self.__dict__.get("_exf_fut_fb") or [])
            old9 = None
            if not fb9 or self.__dict__.get("_exf_fut_place_wait") is None:
                old9 = statefile.read_json(self.EXF_FUT_WAIT_PATH, {}) or {}
            if not fb9:
                fb9 = [x for x in (old9.get("fb") or []) if isinstance(x, dict)][-10:]
                self._exf_fut_fb = fb9
            pw9 = self.__dict__.get("_exf_fut_place_wait")
            if pw9 is None:
                pl9 = (old9 or {}).get("place") if isinstance((old9 or {}).get("place"), dict) else {}
            else:
                ps9 = self.__dict__.get("_exf_fut_place_since") or {}
                pl9 = {e9: {"why": why9, "since": int(ps9.get(e9) or time.time())} for e9, why9 in pw9.items()}
            statefile.atomic_write_json(self.EXF_FUT_WAIT_PATH, {"v": 1, "ts": int(time.time()), "fb": fb9, "place": pl9,
                                                             "wait": {e9: {"since": int(t9[0]), "fallback": bool(t9[2])} for e9, t9 in w9.items()}})
        except (Exception, SystemExit) as e9:   # noqa: BLE001 [optional]
            calcguard.swallowed("core_exf:ExfMixin._exf_fut_wait_save", e9)
            log.warning("선물 대사 대기 표식 쓰기 실패: %s", e9)

    @classmethod
    def _exf_fut_legs(cls, lst, scale: Decimal) -> list:
        g9 = {}
        for t9, a9 in lst:
            e9 = g9.setdefault(int(t9) // cls.EXF_FUT_GROUP_S, [0, Decimal(0)])
            e9[0] = max(e9[0], int(t9))
            e9[1] += a9
        out9 = []
        for k9 in sorted(g9):
            qb9 = int((g9[k9][1] * scale).to_integral_value(rounding=ROUND_HALF_EVEN))
            if qb9:
                out9.append((g9[k9][0], qb9))
        return out9

    def _exf_fut_post(self, ex: str, sym: str, bts: int, lst, aid: int, dec: int) -> Decimal:
        scale9 = Decimal(10) ** int(dec)
        loc9 = f"exchange:{ex}"
        today9 = acct_norm.iso_day(time.time())
        got9 = 0
        for seq9, (ts9, qb9) in enumerate(self._exf_fut_legs(lst, scale9)):
            if self._post_leg('exchange', f'{ex}:{histmark.EXF_FUT_NS}', f'exfrecon:{sym}:{int(bts)}', seq9, int(ts9), int(aid), loc9, qb9, None, None, 'opening', 'EXF_ADJUST'):
                got9 += qb9
                recon_adj.note(self.conn, "K8", ('exchange', f'{ex}:{histmark.EXF_FUT_NS}', f'exfrecon:{sym}:{int(bts)}', seq9), "futpnl")
                if acct_norm.iso_day(ts9) < today9:
                    self._exf_hist_touch(ts9)
        return Decimal(got9) / scale9
