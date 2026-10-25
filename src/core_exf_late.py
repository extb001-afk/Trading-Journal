import bisect
import calcguard
import acct_norm, histmark, num_parse, paths, seeds, statefile
import json
import recon_adj
import os
import sqlite3
import time
from core_common import CLASSIFIER_VER
from decimal import Decimal
import logging

log = logging.getLogger('tj-core')


class ExfLateMixin:

    EXF_LATE_OBS_GAP = 600

    EXF_LATE_RECON_WIN = 7200

    EXF_LATE_REL = Decimal("0.01")

    def _exf_latefix_moved(self) -> set:
        if "_exf_lfm" in self.__dict__:
            return self._exf_lfm
        out = set()
        try:
            names = [n for n in os.listdir(paths.STATE_DIR) if n.startswith("latefix_move_undo_") and n.endswith(".json")]
        except OSError:
            names = []
        for n9 in names:
            try:
                for m9 in json.load(open(os.path.join(paths.STATE_DIR, n9), encoding="utf-8")) or []:
                    if isinstance(m9, dict) and m9.get("ex") and m9.get("sym") and m9.get("bts") is not None:
                        out.add((str(m9["ex"]), str(m9["sym"]).upper(), int(m9["bts"])))
            except (OSError, ValueError, TypeError):
                continue
        self._exf_lfm = out
        return out

    def _exf_late_batches(self, ex: str) -> list:
        c9 = self.__dict__.setdefault("_exf_late_bcache", {})
        if ex in c9:
            return c9[ex]
        tr9, dw9 = [], []
        for r in self.conn.execute("SELECT kind, payload, observed_at FROM raw_ex WHERE exchange=? AND kind IN ('trade','deposit','withdraw')"
                                   " AND payload LIKE '%late%'", (ex,)):
            try:
                p9 = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            if not isinstance(p9, dict) or not p9.get("late"):
                continue
            if r["kind"] == "trade":
                tr9.append((int(r["observed_at"]), p9))
            else:
                dw9.append((int(r["observed_at"]), {str(p9.get("currency") or "").upper(), str(p9.get("fee_ccy") or "").upper()}))
        out = []
        for o9, p9 in sorted(tr9, key=lambda x: x[0]):
            if out and o9 - out[-1]["o1"] <= self.EXF_LATE_OBS_GAP:
                out[-1]["o1"] = o9
                out[-1]["f"].append(p9)
            else:
                out.append({"o0": o9, "o1": o9, "f": [p9]})
        for b in out:
            dl9 = {}
            for sym9, lst9 in self._late_fill_deltas(b.pop("f")).items():
                old9 = [(t9, a9) for t9, a9 in lst9 if t9 < b["o0"] - self.EXF_LATE_OBS_GAP]
                if old9:
                    dl9[sym9] = old9
            b["dl"] = dl9
            b["mixed"] = set().union(*[c for o9, c in dw9 if b["o0"] - self.EXF_LATE_OBS_GAP <= o9 <= b["o1"] + self.EXF_LATE_OBS_GAP]) if dw9 else set()
        c9[ex] = out
        return out

    LATE_BATCH_WAIT = 3600

    EXF_LATE_INC = "inc:"
    EXF_LATE_KEEP = "@inc:"
    def _late_stage(self, ex: str, deltas: dict, rec: dict, incs: dict = None) -> None:
        lb = rec.get("lb")
        try:
            lbi, lbn = int(rec.get("lbi") or 0), max(1, int(rec.get("lbn") or 1))
        except (TypeError, ValueError):
            lb, lbi, lbn = None, 0, 1
        if not lb:
            if not deltas and not incs:
                return
            import uuid as _uuid
            lb, lbi, lbn = f"r:{_uuid.uuid4().hex}", 0, 1
        now9 = int(time.time())
        lc = str(rec.get("lc")) if rec.get("lc") else None
        self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,?,?,NULL,NULL,NULL,?,?)",
                          (ex, str(lb), lbi, lbn, now9, lc))
        staged = [(sym, lst, "") for sym, lst in (deltas or {}).items()] + [(sym, lst, self.EXF_LATE_INC) for sym, lst in (incs or {}).items()]
        for sym, lst, pfx in staged:
            for ts9, amt in lst:
                self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,?,?,?,?,?,?,?)",
                                  (ex, str(lb), lbi, lbn, sym, int(ts9), pfx + str(amt), now9, lc))

    def _late_cycle_done(self, rec: dict) -> None:
        ex, lc = str(rec.get("exchange") or ""), str(rec.get("lc") or "")
        if ex and lc:
            self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,0,1,NULL,NULL,NULL,?,?)",
                              (ex, "@done:" + lc, int(time.time()), lc))

    def _exf_late_pending(self, ex: str) -> bool:
        try:
            return self.conn.execute("SELECT 1 FROM exf_late_pending WHERE ex=? AND substr(lb, 1, 5) != ? LIMIT 1",
                                     (ex, self.EXF_LATE_KEEP)).fetchone() is not None
        except sqlite3.OperationalError:
            return False

    def _late_keep_load(self, keep: list, ready_ex: set, inc_ex: dict) -> None:
        for r in keep:
            if r["ex"] not in ready_ex or r["sym"] is None or str(r["lb"]) != self.EXF_LATE_KEEP + str(self._meta_get(f"recon_done_exf_{r['ex']}") or ""):
                continue
            try:
                amount = Decimal(str(r["amt"])[len(self.EXF_LATE_INC):])
            except (ArithmeticError, TypeError, ValueError):
                continue
            inc_ex.setdefault(r["ex"], {}).setdefault(str(r["sym"]), []).append((int(r["ts"]), amount))

    def _exf_income_unoffset(self, ex: str, left: dict, max_pid: int) -> dict:
        out = {}
        for sym, lst in sorted(left.items()):
            bounds = self._exf_bounds_q(self.conn, ex, sym)
            for ts_inc, amount in sorted(lst):
                bucket = self._exf_bucket(bounds, ts_inc)
                cands = [r for r in self._exf_adj_rows(ex, sym) if self._exf_late_b(r["source_id"]) is not None and int(r["qty_base"]) > 0
                         and int(r["posting_id"]) <= max_pid and self._exf_bucket(bounds, int(r["event_ts"]) - self.EXF_LATE_DT) == bucket]
                cands.sort(key=lambda r: (abs(int(r["event_ts"]) - int(ts_inc)), -int(r["posting_id"])))
                rest = self._exf_take(ex, sym, cands, amount, removing_positive=True, why=f"지급 짝 늦은 상쇄 되돌림(대사 {bucket} 구간)")
                if amount - rest > self.EXF_TOL:
                    log.info("%s %s: 지급 %s 중 %s 를 앞서 흡수된 늦은 변화의 상쇄 줄에서 되돌림(같은 사건 · 대사 %s 구간)", ex, sym,
                             format(amount, "f"), format(amount - rest, "f"), bucket or "없음")
                if rest > self.EXF_TOL:
                    out.setdefault(sym, []).append((ts_inc, rest))
        return out

    def _exf_late_flush(self) -> int:
        rows = self.conn.execute("SELECT ex, lb, lbi, lbn, sym, ts, amt, at, lc FROM exf_late_pending").fetchall()
        keep = [r for r in rows if str(r["lb"]).startswith(self.EXF_LATE_KEEP)]
        rows = [r for r in rows if not str(r["lb"]).startswith(self.EXF_LATE_KEEP)]
        if not rows:
            return 0
        now9 = int(time.time())
        info = {}
        done_lc = {(r["ex"], r["lc"]) for r in rows if str(r["lb"]).startswith("@done:")}
        for r in rows:
            b = info.setdefault((r["ex"], r["lb"]), {"n": int(r["lbn"] or 1), "seen": set(), "at": int(r["at"] or now9), "lc": r["lc"]})
            b["seen"].add(int(r["lbi"] or 0))
            b["at"] = min(b["at"], int(r["at"] or now9))
            if r["lc"] and not b["lc"]:
                b["lc"] = r["lc"]
        for k, b in info.items():
            if b["lc"] and not str(k[1]).startswith("@done:") and (k[0], b["lc"]) not in done_lc:
                b["n"] = len(b["seen"]) + 1
        ready = set()
        for ex9 in {k[0] for k in info}:
            mine = {k: b for k, b in info.items() if k[0] == ex9}
            inc = [b for b in mine.values() if len(b["seen"]) < b["n"]]
            if not inc or all(now9 - b["at"] > self.LATE_BATCH_WAIT for b in inc):
                ready |= set(mine)
        if not ready:
            return 0
        per_ex, inc_ex = {}, {}
        for r in rows:
            if (r["ex"], r["lb"]) not in ready or r["sym"] is None:
                continue
            amt_s = str(r["amt"])
            is_inc = amt_s.startswith(self.EXF_LATE_INC)
            try:
                amt = Decimal(amt_s[len(self.EXF_LATE_INC):] if is_inc else amt_s)
            except (ArithmeticError, TypeError, ValueError):
                continue
            (inc_ex if is_inc else per_ex).setdefault(r["ex"], {}).setdefault(str(r["sym"]), []).append((int(r["ts"]), amt))
        ready_ex = {k[0] for k in ready}
        self._late_keep_load(keep, ready_ex, inc_ex)
        cur_lb = {ex: self.EXF_LATE_KEEP + str(self._meta_get(f"recon_done_exf_{ex}") or "") for ex in ready_ex}
        comp_ex = late_comp_load(keep, cur_lb, self.EXF_LATE_KEEP, self.EXF_LATE_INC)
        n = 0
        try:
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN")
            left_ex = {ex: self._exf_income_pair(ex, per_ex.get(ex, {}), incs) for ex, incs in sorted(inc_ex.items())}
            max_pid = int(self.conn.execute("SELECT COALESCE(MAX(posting_id), 0) FROM postings").fetchone()[0])
            for ex, deltas in sorted(per_ex.items()):
                n += self._exf_absorb_deltas(ex, deltas, "늦은 체결·입출금", comp_ex.get(ex))
            left_ex = {ex: self._exf_income_unoffset(ex, left_pair, max_pid) for ex, left_pair in sorted(left_ex.items())}
            for ex, lb in sorted(ready):
                self.conn.execute("DELETE FROM exf_late_pending WHERE ex=? AND lb=?", (ex, lb))
            for ex in sorted(ready_ex):
                self.conn.execute("DELETE FROM exf_late_pending WHERE ex=? AND substr(lb, 1, 5) = ?", (ex, self.EXF_LATE_KEEP))
                for lb, incs in late_keep_plan(cur_lb[ex], left_ex.get(ex), comp_ex.get(ex), self.EXF_LATE_KEEP, self.EXF_TOL,
                                               lambda s, r_old: late_comp_rows(self._exf_adj_rows(ex, s), self._exf_bounds_q(self.conn, ex, s), r_old, ex)):
                    self._late_stage(ex, {}, {"lb": lb}, incs)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self._exf_hist_flush()
        return n

    def _late_fill_deltas(self, fills: list) -> dict:
        deltas = {}
        for f in fills or ():
            try:
                ts9 = int(int(f.get("ts") or 0) / 1000)
                qty = Decimal(str(f.get("qty") or "0"))
                gross = qty * Decimal(str(f.get("price") or "0"))
                fee9 = Decimal(str(f.get("fee") or "0"))
            except (ArithmeticError, TypeError, ValueError):
                continue
            if ts9 <= 0 or qty <= 0:
                continue
            sgn = 1 if str(f.get("side")) == "buy" else -1
            for sym, amt in ((str(f.get("base") or "").upper(), sgn * qty), (str(f.get("quote") or "").upper(), -sgn * gross),
                             (str(f.get("fee_ccy") or "").upper(), -fee9)):
                if sym and amt != 0:
                    deltas.setdefault(sym, []).append((ts9, amt))
        return deltas

    def _exf_absorb_late(self, ex: str, fills: list) -> int:
        return self._exf_absorb_deltas(ex, self._late_fill_deltas(fills), "늦은 체결")

    def _exf_absorb_deltas(self, ex: str, deltas: dict, what: str, comp: dict = None) -> int:
        last = self._meta_get(f"recon_done_exf_{ex}")
        if not last or not deltas:
            return 0
        try:
            last9 = int(float(last))
        except (TypeError, ValueError):
            return 0
        n = 0
        for sym, lst in sorted(deltas.items()):
            rows = [r for r in self._exf_adj_rows(ex, sym)
                    if not histmark.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id"))]
            bts_all = self._exf_bounds_q(self.conn, ex, sym)
            per, grp = {}, {}
            for ts9, amt in lst:
                if ts9 > last9:
                    continue
                k9 = self._exf_bucket(bts_all, ts9)
                per[k9] = per.get(k9, Decimal(0)) + amt
                grp.setdefault(k9, []).append((int(ts9), amt))
            for b9 in sorted(per, key=lambda b: (per[b] > 0, b)):
                amt = per[b9]
                if abs(amt) <= self.EXF_TOL:
                    continue
                cands = [r for r in rows if self._exf_bts(r["source_id"]) == b9 and int(r["qty_base"]) != 0
                         and (int(r["qty_base"]) > 0) == (amt > 0)]
                cands.sort(key=lambda r: (self._exf_bts(r["source_id"]), int(r["posting_id"])))
                rem = self._exf_take(ex, sym, cands, amt, removing_positive=(amt > 0), why=f"{what} 흡수(대사 {b9} 구간)")
                if abs(amt) - rem > 0:
                    n += 1
                    log.info("%s %s %s: 대사 %d 구간 순액 %s 중 %s 를 지난 대사 보정에서 되돌림(이중 계상 방지)", ex, what, sym, b9,
                             format(amt, "f"), format(abs(amt) - rem, "f"))
                rem = late_comp_take((comp or {}).get(sym) if amt < 0 else None, b9, bts_all, rem, self.EXF_TOL, lambda r_old, want: self._exf_take(
                    ex, sym, late_comp_rows(rows, bts_all, r_old, ex), want, removing_positive=False, why=f"늦은 변화 나머지 ↔ 지급 맞춘 대사 보정 흡수(대사 {b9} 구간)"))
                if rem > self.EXF_TOL:
                    rem_s = rem if amt > 0 else -rem
                    left9 = self._exf_late_offset(ex, sym, grp.get(b9) or [], amt, rem_s, b9, what)
                    if abs(rem_s - left9) > self.EXF_TOL:
                        n += 1
                    if abs(left9) > self.EXF_TOL:
                        log.info("%s %s %s: 대사 %s 구간 %s 는 되돌릴 보정·상쇄 조건이 없어 다음 대사로(차이 보정)", ex, what, sym,
                                 b9 or "없음(그 뒤 보정 대사 없음)", format(left9, "f"))
        return n

    EXF_LATE_PFX = histmark.EXF_LATE_PFX

    EXF_LATE_GAP_S = 6 * 3600

    EXF_LATE_DT = 1

    @classmethod
    def _exf_late_sid(cls, sym: str, t_off: int, b9) -> str:
        return f"{cls.EXF_LATE_PFX}{str(sym).upper()}:{int(t_off)}:b{int(b9 or 0)}"

    @classmethod
    def _exf_bounds_q(cls, conn, ex: str, sym: str) -> list:
        out = set()
        for r in conn.execute(
                "SELECT p.source_id, p.leg_seq FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?",
                (f"{ex}:recon", f"exchange:{ex}", str(sym).upper())).fetchall():
            if histmark.exf_is_debt_int("EXF_ADJUST", r[1], f"{ex}:recon", r[0]):
                continue
            b9 = cls._exf_bts(r[0])
            if b9 is not None:
                out.add(b9)
        try:
            out |= {int(t[0]) for t in conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex=? AND sym=?", (ex, str(sym).upper()))}
        except sqlite3.OperationalError:
            pass
        return sorted(out)

    @staticmethod
    def _exf_bucket(bounds: list, ts) -> int:
        i9 = bisect.bisect_left(bounds, int(ts))
        return int(bounds[i9]) if i9 < len(bounds) else 0

    @classmethod
    def _exf_late_b(cls, source_id):
        s9 = str(source_id or "")
        if not s9.startswith(cls.EXF_LATE_PFX):
            return None
        try:
            return int(s9.rsplit(":", 1)[1].lstrip("b"))
        except (IndexError, ValueError):
            return None

    @classmethod
    def _exf_late_clusters(cls, lst) -> list:
        out = []
        for ts9, amt in sorted(((int(t), Decimal(a)) for t, a in lst), key=lambda x: x[0]):
            if out and ts9 - out[-1][1] <= cls.EXF_LATE_GAP_S:
                out[-1][1] = ts9
                out[-1][2] += amt
            else:
                out.append([ts9, ts9, amt])
        return [tuple(c9) for c9 in out]

    def _exf_main_inst(self, ex: str, sym: str):
        tot = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            e9 = tot.setdefault(int(r["asset_id"]), [Decimal(0), dec])
            e9[0] += Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        if tot:
            aid = max(tot, key=lambda a: (abs(tot[a][0]), -a))
            return aid, tot[aid][1]
        return self._exf_asset(ex, sym), 8

    def _exf_new_neg(self, series: list, t0: int, t1: int) -> bool:
        cum, floor = Decimal(0), Decimal(0)
        for ts9, q9 in series:
            if ts9 >= t1:
                break
            cum += q9
            if ts9 < t0:
                floor = min(Decimal(0), cum)
            elif cum < floor - self.EXF_TOL:
                return True
        return False

    def _exf_late_offset(self, ex: str, sym: str, lst: list, amt: Decimal, rem_s: Decimal, b9, what: str) -> Decimal:
        sym = str(sym).upper()
        if sym in acct_norm.ex_off_ledger(ex) or abs(rem_s) <= self.EXF_TOL or not lst:
            return rem_s
        cl9 = self._exf_late_clusters(lst)
        if abs(abs(rem_s) - abs(amt)) <= self.EXF_TOL:
            targets = [(t0, t1, -net) for t0, t1, net in cl9 if abs(net) > self.EXF_TOL]
        else:
            targets = [(cl9[0][0], cl9[-1][1], -rem_s)]
        aid, dec = self._exf_main_inst(ex, sym)
        scale = Decimal(10) ** dec
        loc = f"exchange:{ex}"
        now9 = self._exf_now_sym(ex, sym)
        left = rem_s
        for t0, t1, q in targets:
            t_off = int(t1) + self.EXF_LATE_DT
            bnd9 = self._exf_bounds_q(self.conn, ex, sym)
            near = [r for r in self._exf_adj_rows(ex, sym) if self._exf_late_b(r["source_id"]) is not None and int(r["qty_base"]) != 0
                    and (int(r["qty_base"]) > 0) != (q > 0) and int(t0) - self.EXF_LATE_GAP_S <= int(r["event_ts"]) <= t_off + self.EXF_LATE_GAP_S
                    and (self._exf_bucket(bnd9, int(r["event_ts"]) - self.EXF_LATE_DT) == int(b9 or 0) or abs(int(r["event_ts"]) - t_off) <= self.EXF_LATE_GAP_S)]
            if near:
                near.sort(key=lambda r: (self._exf_bucket(bnd9, int(r["event_ts"]) - self.EXF_LATE_DT) != int(b9 or 0), abs(int(r["event_ts"]) - t_off), -int(r["posting_id"])))
                sg9, rq9 = (1 if q > 0 else -1), abs(q)
                for r in (r for r in near if rq9 > self.EXF_TOL):
                    want = rq9
                    if q > 0 and not now9 and int(r["event_ts"]) > t_off:
                        bal_ser = self._exf_series(ex, sym)
                        want = Decimal(0) if self._exf_new_neg(bal_ser, int(t0), t_off) else min(rq9, self._exf_room(sorted(bal_ser + [(t_off, rq9)]), t_off, t_end=int(r["event_ts"])))
                    rq9 -= want - self._exf_take(ex, sym, [r], want, removing_positive=(q < 0), why=f"{what} 늦은 상쇄 되돌림(대사 {b9 or 0} 구간)")
                left += sg9 * (abs(q) - rq9)
                q = sg9 * rq9
            qb = int(q * scale)
            if qb == 0:
                continue
            series = self._exf_series(ex, sym)
            if not now9 and q < 0:
                room = self._exf_room(sorted(series + [(t_off, Decimal(0))]), t_off)
                if room + self.EXF_TOL < -q:
                    log.info("%s %s %s: 늦은 변화 %s 상쇄 보류 — 그 뒤 잔고 여유 %s 부족(새 음수) → 다음 대사로", ex, what, sym,
                             format(-q, "f"), format(room, "f"))
                    continue
            if not now9 and q > 0 and self._exf_new_neg(series, int(t0), t_off):
                log.info("%s %s %s: 늦은 변화 %s 상쇄 보류 — 늦은 변화가 결손(보유 기록 없이 나감)을 만듦 → 다음 대사의 정정이 결손 직전에",
                         ex, what, sym, format(-q, "f"))
                continue
            sid = self._exf_late_sid(sym, t_off, b9)
            row9 =self.conn.execute("SELECT MAX(leg_seq) FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                                     (f"{ex}:recon", sid)).fetchone()
            seq9 = 0 if row9 is None or row9[0] is None else int(row9[0]) + 1
            self._post_leg_strict('exchange', f'{ex}:recon', sid, seq9, t_off, aid, loc, qb, None, None, 'opening', 'EXF_ADJUST')
            recon_adj.note(self.conn, "K9", ('exchange', f'{ex}:recon', sid, seq9), "exflate", what=str(what))
            self._exf_hist_touch(t_off)
            left += Decimal(qb) / scale
            log.info("%s %s %s: 대사 %s 구간 늦은 변화 %s 를 그 직후(%d)에 상쇄 %s — 되돌릴 보정이 없어(같은 돈 두 번 안 잡히게)", ex, what, sym,
                     b9 or "없음", format(-q, "f"), t_off, format(q, "f"))
        return left

    def _exf_hist_touch(self, ts):
        self._inval_seq()
        self._exf_hist_dirty = True
        t9 = num_parse.to_int(ts)
        if t9 is None:
            return
        cur9 = getattr(self, "_exf_hist_from", None)
        self._exf_hist_from = t9 if cur9 is None else min(cur9, t9)

    def _exf_hist_flush(self):
        if getattr(self, "_exf_hist_dirty", False):
            self._exf_hist_dirty = False
            try:
                os.remove(paths.state("daily_cache.json"))
            except FileNotFoundError:
                pass
            t9 = getattr(self, "_exf_hist_from", None)
            self._exf_hist_from = None
            if t9 is not None:
                try:
                    log.info("장기 곡선 다시 계산 표식: %s 부터", histmark.mark_hist_dirty(t9))
                except Exception as e:   # noqa: BLE001 [optional]
                    calcguard.swallowed("core_exf:ExfMixin._exf_hist_flush", e)
                    log.warning("장기 곡선 다시 계산 표식 실패: %s", e)

    def _exf_redate_once(self):
        if self._meta_get("exf_redate_m"):
            return
        moved, moves = 0, []
        firsts = {}
        for r in self.conn.execute("SELECT source_ns, source_id FROM postings WHERE event='EXF_ADJUST'").fetchall():
            b9 = self._exf_bts(r["source_id"])
            if b9 is not None:
                firsts[r["source_ns"]] = min(firsts.get(r["source_ns"], b9), b9)
        groups = {}
        for r in self.conn.execute(
                "SELECT p.posting_id, p.source_ns, p.source_id, p.event_ts, p.qty_base, p.location, a.symbol"
                " FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.event='EXF_ADJUST'").fetchall():
            b9 = self._exf_bts(r["source_id"])
            ns = r["source_ns"]
            if b9 is None or not ns.endswith(":recon") or int(r["qty_base"]) <= 0:
                continue
            if b9 <= firsts.get(ns, b9) + self.EXF_INIT_PHASE or int(r["event_ts"]) >= b9 - 60:
                continue
            groups.setdefault((ns.split(":", 1)[0], (r["symbol"] or "").upper()), []).append(dict(r, bts=b9))
        for (ex, sym), cands in sorted(groups.items()):
            if not sym:
                continue
            dec_rows = self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym)).fetchall()
            ev = {int(x["posting_id"]): [int(x["event_ts"]), Decimal(int(x["qty_base"])) / (Decimal(10) ** (8 if x["decimals"] is None else int(x["decimals"])))]
                  for x in dec_rows}
            for c in sorted(cands, key=lambda c: (-c["bts"], -c["posting_id"])):
                pid = int(c["posting_id"])
                if pid not in ev:
                    continue
                t_old, q = ev[pid]
                agg = {}
                for p9, (t9, v9) in ev.items():
                    agg[t9] = agg.get(t9, Decimal(0)) + v9
                cum, floor, t_new = Decimal(0), Decimal(0), c["bts"]
                for t9, v9 in sorted(agg.items()):
                    cum += v9
                    if t9 < t_old:
                        floor = min(Decimal(0), cum)
                    elif t9 < c["bts"] and cum >= floor - self.EXF_TOL and cum - q < floor - self.EXF_TOL:
                        t_new = t9 - 1
                        break
                if t_new <= t_old:
                    continue
                self._leg_sql("_exf_redate_once.1", (int(t_new), pid))
                ev[pid][0] = int(t_new)
                moves.append([pid, int(t_old), int(t_new)])
                moved += 1
        if moves:
            try:
                statefile.atomic_write_json(paths.state("exf_redate_m.json"),
                                         {"ts": int(time.time()), "moves": moves})
            except Exception as e:  # noqa: BLE001 [fallback]
                calcguard.swallowed("core_exf:ExfMixin._exf_redate_once", e)
                self.conn.rollback()
                log.error("해외 대사 보정 재배치 보류 — 되돌리기 자료 쓰기 실패: %s", e)
                return
        if moved:
            self._inval_seq()
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_redate_m', ?)", (f"{int(time.time())}:{moved}",))
        self.conn.commit()
        if moved:
            self._exf_hist_dirty = True
            log.warning("★해외 대사 지난 양수 보정 %d건 시각 재배치(창 시작 → 대사 시각·결손 직전) — 수량 무변, 지난 곡선 무효화★", moved)
            self._exf_hist_flush()

    def _exf_src_added(self, ex: str, bal: dict) -> set:
        cur = bal.get("sources")
        if not isinstance(cur, list):
            return set()
        prev = self._meta_get(f"recon_src_exf_{ex}")
        if prev is None:
            return set()
        try:
            return {str(x) for x in cur} - set(json.loads(prev))
        except (ValueError, TypeError):
            return set()

    def _exf_loan_absorb(self, ex: str, sym: str, diff: Decimal, bts: int, since: int):
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 >= bts or q9 <= 0:
                continue
            if int(r["event_ts"]) < b9 - 60 or int(r["event_ts"]) < int(since) - 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (int(r["event_ts"]), int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=True, why=f"대출 첫 편입 흡수(대사 {bts} 부채 차이 {format(diff, 'f')})")
        took = abs(diff) - rem
        n = sum(1 for r in cands if r.get("_t"))
        if took > 0:
            log.info("%s %s 대출 첫 편입 — 지난 양수 보정 %s 흡수(빌려 들어온 물량) · 남은 차이 %s", ex, sym, format(took, "f"), format(-rem, "f"))
        return -rem, (n if took > 0 else 0)

    def _exf_debt_redate_once(self):
        if self._meta_get("exf_debt_redate_t"):
            return
        try:
            seed = seeds.seed_json("debt_first_seen_t.json", {}, base_dir=paths.BASE_DIR, strict=True)
        except (Exception, SystemExit) as _cg9:  # noqa: BLE001 [fallback]
            calcguard.swallowed("core_exf:ExfMixin._exf_debt_redate_once[seed]", _cg9)
            seed = {}
        if not isinstance(seed, dict) or not any(isinstance(v9, dict) and v9 for v9 in seed.values()):
            return
        moves = []
        for ex, syms in (seed.items() if isinstance(seed, dict) else ()):
            for sym, ent in (syms.items() if isinstance(syms, dict) else ()):
                try:
                    t_first = int(ent["ts"])
                    q_first = Decimal(str(ent["qty"]))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue
                if q_first <= 0:
                    continue
                def _qn(r9):
                    return Decimal(int(r9["qty_base"])) / (Decimal(10) ** (8 if r9["decimals"] is None else int(r9["decimals"])))
                rows = [r for r in self._exf_adj_rows(ex, sym)
                        if int(r["qty_base"]) < 0 and int(r["leg_seq"]) == 0 and (self._exf_bts(r["source_id"]) or 0) > t_first
                        and int(r["event_ts"]) >= (self._exf_bts(r["source_id"]) or 0) - 60
                        and q_first * Decimal("0.9") <= -_qn(r) <= q_first * Decimal("1.2")]
                rows.sort(key=lambda r: (int(r["event_ts"]), int(r["posting_id"])))
                if not rows:
                    log.warning("기존 부채 소급 건너뜀: %s %s 첫 관측 %s 와 맞는 부채 첫 반영 보정 없음", ex, sym, format(q_first, "f"))
                    continue
                r = rows[0]
                dec = 8 if r["decimals"] is None else int(r["decimals"])
                scale = Decimal(10) ** dec
                q_old = _qn(r)
                q_move = min(q_first, -q_old)
                t_old = int(r["event_ts"])
                if t_first >= t_old:
                    continue
                cum, floor, ok = Decimal(0), Decimal(0), True
                ser9 = self._exf_series(ex, sym)
                for t9, v9 in ser9:
                    if t9 < t_first:
                        cum += v9
                        floor = min(Decimal(0), cum)
                if cum - q_move < floor - self.EXF_TOL:
                    ok = False
                for t9, v9 in ser9:
                    if not ok or t9 >= t_old:
                        break
                    if t9 < t_first:
                        continue
                    cum += v9
                    if cum >= floor - self.EXF_TOL and cum - q_move < floor - self.EXF_TOL:
                        ok = False
                if not ok:
                    log.warning("기존 부채 소급 건너뜀: %s %s — 옮기면 그 사이 원장 잔고가 음수", ex, sym)
                    continue
                qb_move = int(q_move * scale)
                qb_rest = int(r["qty_base"]) + qb_move
                moves.append({"posting_id": int(r["posting_id"]), "ex": ex, "sym": sym, "old_ts": t_old, "old_qty_base": str(r["qty_base"]),
                              "new_ts": t_first, "new_qty_base": str(-qb_move), "source_id": r["source_id"], "asset_id": int(r["asset_id"]),
                              "rest_qty_base": str(qb_rest)})
        if moves:
            try:
                statefile.atomic_write_json(paths.state("exf_debt_redate_t.json"), {"ts": int(time.time()), "moves": moves})
            except Exception as e:  # noqa: BLE001 [fallback]
                calcguard.swallowed("core_exf:ExfMixin._exf_debt_redate_once[atomic_write_json]", e)
                log.error("기존 부채 소급 보류 — 되돌리기 자료 쓰기 실패: %s", e)
                return
            for m in moves:
                self._leg_sql("_exf_debt_redate_once.1", (m["new_ts"], m["new_qty_base"], m["posting_id"]))
                if int(m["rest_qty_base"]) != 0:
                    self._leg_sql(
                        "_exf_debt_redate_once.2",
                        (f"{m['ex']}:recon", m["source_id"], m["old_ts"], m["asset_id"], f"exchange:{m['ex']}", m["rest_qty_base"], CLASSIFIER_VER))
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_debt_redate_t', ?)", (f"{int(time.time())}:{len(moves)}",))
        self.conn.commit()
        if moves:
            log.warning("★기존 부채 첫 반영 %d건 첫 관측 시각으로 소급(나머지 = 이자 레그) — 수량 무변, 지난 곡선은 web 이 해당 날만 조정★", len(moves))


def _bucket_at(bounds: list, ts: int) -> int:
    i = bisect.bisect_left(bounds, int(ts))
    return int(bounds[i]) if i < len(bounds) else 0


def _bts_of(source_id: object) -> int:
    try:
        return int(str(source_id).rsplit(":", 1)[1])
    except (IndexError, ValueError, TypeError):
        return None


def late_comp_load(keep: list, cur_lb: dict, keep_pfx: str, inc_pfx: str) -> dict:
    out = {}
    for r in keep:
        lb = str(r["lb"])
        if r["ex"] not in cur_lb or r["sym"] is None or lb == cur_lb[r["ex"]]:
            continue
        try:
            amount, r_old = Decimal(str(r["amt"])[len(inc_pfx):]), int(float(lb[len(keep_pfx):] or 0))
        except (ArithmeticError, TypeError, ValueError):
            continue
        if r_old > 0:
            out.setdefault(r["ex"], {}).setdefault(str(r["sym"]), []).append([int(r["ts"]), amount, r_old])
    return out


def late_comp_rows(rows: list, bounds: list, r_old: int, ex: str) -> list:
    nb = _bucket_at(bounds, int(r_old) + 1)
    return sorted((r for r in rows if nb and _bts_of(r["source_id"]) == nb
            and int(r["qty_base"]) < 0 and not histmark.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id"))),
                  key=lambda r: int(r["posting_id"]))


def late_comp_take(comp: list, bucket: int, bounds: list, rem: Decimal, tol: Decimal, take: "Callable[[int, Decimal], Decimal]") -> Decimal:
    for ent in sorted(comp or (), key=lambda e: (e[0], e[2])):
        if rem <= tol:
            break
        if ent[1] <= tol or _bucket_at(bounds, ent[0]) != int(bucket or 0):
            continue
        want = min(rem, ent[1])
        got = want - take(ent[2], want)
        if got > 0:
            log.info("늦은 변화 나머지 %s 를 먼저 기장된 지급(대사 %s 구간)을 맞춘 다음 대사 보정에서 되돌림", format(got, "f"), bucket)
        ent[1] -= got
        rem -= got
    return rem


def late_keep_plan(cur_lb: str, live: dict, comp: dict, keep_pfx: str, tol: Decimal, comp_rows: "Callable[[str, int], list]") -> list:
    out = [(cur_lb, live)] if live else []
    by_recon = {}
    for sym, lst in sorted((comp or {}).items()):
        for ts_inc, amount, r_old in lst:
            if amount > tol and comp_rows(sym, r_old):
                by_recon.setdefault(r_old, {}).setdefault(sym, []).append((ts_inc, amount))
    return out + [(keep_pfx + str(r_old), incs) for r_old, incs in sorted(by_recon.items())]
