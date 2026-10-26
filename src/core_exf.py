import acct_norm
import bisect
import config, histmark, logs, paths, statefile
import json
import os
import re
import recon_adj
import sqlite3
import time
from core_common import dm
from decimal import Decimal
from decimal import ROUND_CEILING
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


from core_exf_fut import ExfFutMixin  # noqa: E402


from core_exf_late import ExfLateMixin  # noqa: E402


class ExfMixin(ExfLateMixin, ExfFutMixin):

    EXF_STABLE_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "DAI", "USD")

    def _exf_asset(self, ex: str, sym: str) -> int:
        return self.asset_id("exchange_currency", None, f"{ex}:{sym.upper()}",
                             symbol=sym.upper(), decimals=8)

    def _quote_usd(self, quote: str, ts: int):
        q = (quote or "").upper()
        if q in self.EXF_STABLE_QUOTES:
            return Decimal(1)
        if q == "KRW":
            fx = self.px.fx_at(ts * 1000)
            return (Decimal(1) / Decimal(str(fx))) if fx else None
        v = self.px.candle_usd(q, ts * 1000)
        return Decimal(str(v)) if v else None

    def _consume_exf_fills(self, rec: dict):
        ex = str(rec.get("exchange") or "")
        if not ex or ex == "upbit":
            return
        self._wd_fee_new_ex(ex)
        now = int(time.time())
        n = 0
        late9, new_income = [], {}
        for f in rec.get("fills") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            fid = str(f["id"])
            if f.get("src") == "income":
                ins_cur = self.conn.execute(
                    "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?, 'income', ?, 1, ?, ?)",
                    (ex, fid, json.dumps(f, ensure_ascii=False), now))
                if ins_cur.rowcount and self._consume_exf_income(ex, fid, f, new_income):
                    n += 1
                continue
            cur9 = self.conn.execute(
                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload,"
                " observed_at) VALUES (?, 'trade', ?, 1, ?, ?)",
                (ex, fid, json.dumps(f, ensure_ascii=False), now))
            if not cur9.rowcount:
                continue
            if not self._post_exf_fill(ex, f):
                self._exf_fill_skipped(ex, fid, f)
            else:
                n += 1
                if f.get("src") == "convert" or f.get("late"):
                    late9.append(f)
        late_dl = self._late_fill_deltas(late9)
        left = {}
        if new_income:
            self._exf_income_absorb(ex, new_income, left)
        self._late_stage(ex, late_dl, rec, left)
        if n:
            log.info("%s 체결 반영: %d건", ex, n)

    def _exf_income_pair(self, ex: str, deltas: dict, incs: dict) -> dict:
        try:
            last_l = int(float(self._meta_get(f"recon_done_exf_{ex}") or 0))
        except (TypeError, ValueError):
            last_l = 0
        left_l = {}
        for sym_l, rows_l in sorted(incs.items()):
            if sym_l not in deltas:
                left_l[sym_l] = sorted(rows_l)
                continue
            bounds_l = self._exf_bounds_q(self.conn, ex, sym_l)
            net_l = {}
            for ts_l, amt_l in deltas[sym_l]:
                if ts_l <= last_l:
                    b_l = self._exf_bucket(bounds_l, ts_l)
                    net_l[b_l] = net_l.get(b_l, Decimal(0)) + amt_l
            paired_l = []
            for ts_l, amt_l in sorted(rows_l):
                b_l = self._exf_bucket(bounds_l, ts_l)
                take_l = min(amt_l, max(Decimal(0), -net_l.get(b_l, Decimal(0)))) if ts_l <= last_l else Decimal(0)
                if take_l > self.EXF_TOL:
                    paired_l.append((ts_l, take_l))
                    net_l[b_l] += take_l
                else:
                    take_l = Decimal(0)
                if amt_l - take_l > self.EXF_TOL:
                    left_l.setdefault(sym_l, []).append((ts_l, amt_l - take_l))
            deltas[sym_l].extend(paired_l)
        return left_l

    def _consume_exf_income(self, ex: str, fid: str, f: dict, new_income: dict) -> bool:
        if not self._post_exf_income(ex, f):
            if not self.conn.execute("SELECT 1 FROM postings WHERE source_ns=? AND source_id=? LIMIT 1", (f"{ex}:income", fid)).fetchone():
                ex_name = ex if re.fullmatch(r"[a-z0-9_]{1,20}", ex) else "?"
                log.warning("%s 지급 내역 기장 안 됨(원본만 보존 — 형식 이상)", ex_name)
                calcguard.swallowed("core_exf:ExfMixin._consume_exf_income:skip", ValueError("지급 내역 기장 누락 %s" % ex_name))
            return False
        new_income.setdefault(str(f.get("asset") or "").strip().upper(), []).append(
            (int(int(f.get("ts") or 0) / 1000), Decimal(str(f.get("amount")))))
        return True

    def _exf_income_absorb(self, ex: str, items: dict, left: dict = None) -> int:
        try:
            last_ts = int(float(self._meta_get(f"recon_done_exf_{ex}") or 0))
        except (TypeError, ValueError):
            last_ts = 0
        if last_ts <= 0:
            return 0
        loc, n = f"exchange:{ex}", 0
        for sym, lst in sorted(items.items()):
            rows = [r for r in self._exf_adj_rows(ex, sym) if int(r["qty_base"]) > 0 and self._exf_bts(r["source_id"]) is not None
                    and not histmark.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id"))]
            bounds = self._exf_bounds_q(self.conn, ex, sym)
            for ts_s, amt in sorted(lst):
                if ts_s > last_ts:
                    continue
                rem, bucket = amt, self._exf_bucket(bounds, ts_s)
                for r in sorted((r for r in rows if int(r["qty_base"]) > 0 and ts_s <= int(r["event_ts"]) <= bucket),
                                key=lambda r: (int(r["event_ts"]), int(r["posting_id"]))):
                    rem -= self._exf_income_take(ex, r, rem, loc, f"지급 내역 대체 흡수(대사 {bucket} 구간)")
                    if rem <= self.EXF_TOL:
                        break
                for r in sorted((r for r in rows if self._exf_bts(r["source_id"]) >= ts_s and int(r["qty_base"]) > 0 and int(r["event_ts"]) < ts_s),
                                key=lambda r: (self._exf_bts(r["source_id"]), -int(r["event_ts"]), int(r["posting_id"]))):
                    if rem <= self.EXF_TOL or not bucket:
                        break
                    room = self._exf_room(self._exf_series(ex, sym), int(r["event_ts"]), t_end=ts_s)
                    rem -= self._exf_income_take(ex, r, min(rem, room), loc, f"지급 내역 앞 보정 대체 흡수(대사 {bucket} 구간)")
                if left is not None and rem > self.EXF_TOL:
                    left.setdefault(sym, []).append((ts_s, rem))
                if amt - rem > self.EXF_TOL:
                    n += 1
                    log.info("%s %s: 지급 %s 중 %s 를 지난 대사 보정에서 수입 행으로 대체", ex, sym, format(amt, "f"), format(amt - rem, "f"))
        return n

    def _exf_income_take(self, ex: str, r: dict, want: Decimal, loc: str, why: str) -> Decimal:
        if want <= self.EXF_TOL:
            return Decimal(0)
        scale = Decimal(10) ** (8 if r["decimals"] is None else int(r["decimals"]))
        take_base = int(min(want, Decimal(int(r["qty_base"])) / scale) * scale)
        if take_base <= 0:
            return Decimal(0)
        self._exf_shrink(r, take_base, loc, why)
        return Decimal(take_base) / scale

    def _post_exf_income(self, ex: str, f: dict) -> bool:
        fid = str(f.get("id") or "")
        sym = str(f.get("asset") or "").strip().upper()
        try:
            amt = Decimal(str(f.get("amount") or "0"))
            ts_s = int(int(f.get("ts") or 0) / 1000)
        except (ArithmeticError, TypeError, ValueError):
            return False
        qb = int(amt * (Decimal(10) ** 8)) if amt.is_finite() else 0
        if not fid or not sym or qb <= 0 or ts_s <= 0:
            return False
        unit_usd = self._quote_usd(sym, ts_s) if sym != "KRW" else None
        cost_usd = amt * unit_usd if unit_usd is not None else None
        fx_rate = self.px.fx_at(ts_s * 1000) if cost_usd is not None else None
        return self._post_leg("exchange", f"{ex}:income", fid, 0, ts_s, self._exf_asset(ex, sym), f"exchange:{ex}", qb,
                              repr(float(cost_usd)) if cost_usd is not None else None,
                              repr(float(cost_usd) * fx_rate) if (cost_usd is not None and fx_rate) else None, "acq", "STAKE_REWARD")

    def _exf_fill_skipped(self, ex: str, fid: str, f: dict) -> None:
        try:
            if self.conn.execute("SELECT 1 FROM postings WHERE source_ns=? AND source_id=? LIMIT 1",
                                 (f"{ex}:trade", fid)).fetchone():
                return
            why = self._exf_fill_bad(f)
            ex9 = ex if re.fullmatch(r"[a-z0-9_]{1,20}", ex) else "?"
            log.warning("%s 체결 기장 안 됨(원본만 보존 — 형식 이상): %s", ex9, why)
            calcguard.swallowed("core_exf:ExfMixin._consume_exf_fills:skip", ValueError("체결 기장 누락 %s %s" % (ex9, why)))
        except sqlite3.Error as e9:
            log.warning("체결 누락 확인 실패: %s", logs.safe_err(e9))

    @staticmethod
    def _exf_fill_bad(f: dict) -> str:
        out = []
        for k9 in ("qty", "price", "ts"):
            v9 = f.get(k9)
            try:
                if k9 == "ts":
                    int(int(v9 or 0) / 1000)
                else:
                    Decimal(str(v9 or "0"))
            except (ArithmeticError, TypeError, ValueError):
                out.append("%s 숫자 아님(%s)" % (k9, type(v9).__name__))
        try:
            if Decimal(str(f.get("qty") or "0")) <= 0:
                out.append("qty ≤ 0")
        except (ArithmeticError, TypeError, ValueError):
            pass
        try:
            if int(int(f.get("ts") or 0) / 1000) <= 0:
                out.append("ts 없음·0 이하")
        except (ArithmeticError, TypeError, ValueError):
            pass
        if not str(f.get("base") or ""):
            out.append("base 없음")
        if str(f.get("side") or "") not in ("buy", "sell"):
            out.append("side 가 buy/sell 아님")
        return " · ".join(out) or "기장 거절(사유 미상)"

    EXF_TOL = Decimal("0.00000001")

    EXF_MICRO_USD = Decimal("1")

    EXF_MICRO_REL = Decimal("0.0001")

    EXF_INIT_PHASE = 72 * 3600

    EXF_NEW_SOURCES_M = {"okx": ("savings", "staking"), "bybit": ("earn",)}

    EXF_DEBT_MICRO_USD = Decimal("5")

    EXF_DEBT_ONLY_SOURCES = {"gate": ("cross",), "kucoin": ("margin",)}

    EXF_DEBT_FIRST_SEEN = os.path.join(paths.BASE_DIR, "seed", "debt_first_seen_t.json")

    @staticmethod
    def _exf_bts(source_id):
        try:
            return int(str(source_id).rsplit(":", 1)[1])
        except (IndexError, ValueError, TypeError):
            return None

    def _exf_open_ts(self, ex: str, bts: int) -> int:
        if self.recon_months > 0:
            return self._win_t0(bts, ex)
        return bts - int(float(self.cfg.get("backfill_months") or 5) * 30 * 86400)

    def _exf_cov_new(self, ex: str, bal: dict) -> bool:
        cur = bal.get("sources")
        if not isinstance(cur, list):
            return False
        cur = {str(x) for x in cur}
        prev = self._meta_get(f"recon_src_exf_{ex}")
        if prev is None:
            return bool(cur & set(self.EXF_NEW_SOURCES_M.get(ex, ())))
        try:
            prev = set(json.loads(prev))
        except (ValueError, TypeError):
            return False
        new = cur - prev
        new -= set(self.EXF_DEBT_ONLY_SOURCES.get(ex, ()))
        loans9 = bal.get("loans") if isinstance(bal.get("loans"), list) else []
        if "loan" in new and not any(isinstance(l9, dict) and l9.get("collateral") for l9 in loans9):
            new.discard("loan")
        return bool(new)

    def _exf_adj_rows(self, ex: str, sym: str) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.asset_id, p.qty_base, p.event_ts, p.source_id, p.leg_seq, a.decimals"
            " FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?",
            (f"{ex}:recon", f"exchange:{ex}", sym.upper())).fetchall()]

    def _exf_series(self, ex: str, sym: str) -> list:
        agg = {}
        for r in self.conn.execute(
                "SELECT p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            agg[int(r["event_ts"])] = agg.get(int(r["event_ts"]), Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        return sorted(agg.items())

    @staticmethod
    def _exf_room(series: list, t: int, t_end=None) -> Decimal:
        cum, floor, mn = Decimal(0), Decimal(0), None
        for ts9, q9 in series:
            if ts9 < t:
                cum += q9
                floor = min(Decimal(0), cum)
                continue
            cum += q9
            if (t_end is None or ts9 < t_end) and cum >= floor - Decimal("0.00000001"):
                mn = (cum - floor) if mn is None else min(mn, cum - floor)
        if mn is None:
            return Decimal(0)
        return max(Decimal(0), mn)

    def _exf_deficit(self, ex: str, sym: str):
        cum, t_run, mn = Decimal(0), None, Decimal(0)
        for ts9, q9 in self._exf_series(ex, sym):
            cum += q9
            if cum < -self.EXF_TOL:
                if t_run is None:
                    t_run, mn = ts9, cum
                mn = min(mn, cum)
            else:
                t_run, mn = None, Decimal(0)
        return (t_run, -mn) if t_run is not None else (None, Decimal(0))

    EXF_FIX_V = 2

    EXF_RUN_MIN_S = 3600

    EXF_FIX_SKIP = frozenset(("KRW", "USD"))

    def _exf_agg(self, ex: str, sym: str, exclude=()):
        agg = {}
        ex9 = set(exclude or ())
        for r in self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            if ex9 and int(r["posting_id"]) in ex9:
                continue
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            t9 = int(r["event_ts"])
            agg[t9] = agg.get(t9, Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        return agg, sorted(agg)

    @classmethod
    def _exf_tranches(cls, agg: dict, keys: list, amount_b: int, scale: Decimal, bts: int, open_ts: int):
        tol = cls.EXF_TOL
        out, rem, lift = [], int(amount_b), Decimal(0)
        cum, i, n = Decimal(0), 0, len(keys)
        while i < n and keys[i] <= open_ts:
            cum += agg[keys[i]]
            i += 1
        start, mn = (open_ts, cum) if cum < -tol else (None, Decimal(0))

        def emit(st9, dfc9):
            nonlocal rem, lift
            take9 = min(rem, int((dfc9 * scale).to_integral_value(rounding=ROUND_CEILING)))
            if take9 > 0:
                out.append((int(open_ts) if st9 <= open_ts else int(st9) - 1, take9))
                rem -= take9
                lift += Decimal(take9) / scale
        while rem > 0 and i < n and keys[i] <= bts:
            t9 = keys[i]
            i += 1
            cum += agg[t9]
            v9 = cum + lift
            if v9 < -tol:
                if start is None:
                    start, mn = t9, v9
                elif v9 < mn:
                    mn = v9
            elif start is not None:
                if t9 - start >= cls.EXF_RUN_MIN_S:
                    emit(start, -mn)
                start, mn = None, Decimal(0)
        if rem > 0 and start is not None:
            emit(start, -mn)
        for t9, qb9 in out:
            if t9 not in agg:
                bisect.insort(keys, t9)
                agg[t9] = Decimal(0)
            agg[t9] += Decimal(qb9) / scale
        return out, rem

    @staticmethod
    def _exf_bound_old(pieces: list, old: list) -> list:
        olds = [[int(t9), int(q9)] for t9, q9 in sorted(old)]
        out, j = [], 0
        for t9, q9 in sorted(pieces):
            q9 = int(q9)
            while q9 > 0:
                take9 = min(q9, olds[j][1])
                out.append((min(int(t9), olds[j][0]), take9))
                q9 -= take9
                olds[j][1] -= take9
                if olds[j][1] == 0:
                    j += 1
        return out

    @staticmethod
    def _exf_tranche_legs(tranches, rem_b: int, bts: int, reserved=frozenset()) -> list:
        pcs = {}
        for t9, qb9 in list(tranches) + ([(bts, rem_b)] if rem_b > 0 else []):
            pcs[int(t9)] = pcs.get(int(t9), 0) + int(qb9)
        used = set(reserved) | {2}
        legs, nxt = [], 1
        for t9 in sorted(pcs):
            if t9 == int(bts) and 0 not in used:
                l9 = 0
            else:
                while nxt in used:
                    nxt += 1
                l9 = nxt
            used.add(l9)
            legs.append((l9, t9, pcs[t9]))
        return legs

    def _exf_fix_pool(self):
        pool, other = {}, {}
        span9 = int(float(self.cfg.get("backfill_months") or 5) * 30 * 86400)
        for r in self.conn.execute(
                "SELECT p.posting_id, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.qty_base, p.asset_id, p.location,"
                " p.classifier_ver, a.symbol, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.event='EXF_ADJUST' AND p.source_ns LIKE '%:recon'").fetchall():
            ns = str(r["source_ns"])
            ex = ns.split(":", 1)[0]
            sym = str(r["symbol"] or "").upper()
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or not sym or sym in acct_norm.ex_off_ledger(ex) or r["location"] != f"exchange:{ex}":
                continue
            if (int(r["leg_seq"]) == 2 or int(r["qty_base"]) <= 0
                    or (int(r["leg_seq"]) == 0 and int(r["event_ts"]) <= max(self._exf_open_ts(ex, b9), b9 - span9) + 60)):
                other.setdefault((ex, sym, str(r["source_id"])), set()).add(int(r["leg_seq"]))
                continue
            pool.setdefault((ex, sym), {}).setdefault(str(r["source_id"]), []).append(dict(r, bts=b9))
        return pool, other

    def _exf_fix_place_plan(self) -> list:
        out = []
        pool, other = self._exf_fix_pool()
        for (ex, sym), groups in sorted(pool.items()):
            if self._exf_now_sym(ex, sym):
                continue
            pids = {int(r["posting_id"]) for rows in groups.values() for r in rows}
            agg, keys = self._exf_agg(ex, sym, exclude=pids)
            for sid, rows in sorted(groups.items(), key=lambda kv: (kv[1][0]["bts"], kv[0])):
                b9 = rows[0]["bts"]
                aids = {int(r["asset_id"]) for r in rows}
                decs = {8 if r["decimals"] is None else int(r["decimals"]) for r in rows}
                tot = sum(int(r["qty_base"]) for r in rows)
                if len(aids) != 1 or len(decs) != 1:
                    log.warning("양수 정정 재배치 건너뜀: %s %s %s — 자산 %d개·자릿수 %d개", ex, sym, sid, len(aids), len(decs))
                    for r in rows:
                        t9 = int(r["event_ts"])
                        dec9 = 8 if r["decimals"] is None else int(r["decimals"])
                        agg[t9] = agg.get(t9, Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec9)
                    keys[:] = sorted(agg)
                    continue
                scale = Decimal(10) ** decs.pop()
                tr9, rem9 = self._exf_tranches(agg, keys, tot, scale, b9, self._exf_open_ts(ex, b9))
                bnd9 = self._exf_bound_old(list(tr9) + ([(b9, rem9)] if rem9 > 0 else []),
                                           [(int(r["event_ts"]), int(r["qty_base"])) for r in rows])
                new = sorted(self._exf_tranche_legs(bnd9, 0, b9, reserved=other.get((ex, sym, sid), ())))
                for t9, qb9 in tr9:
                    agg[t9] -= Decimal(qb9) / scale
                for _l9, t9, qb9 in new:
                    if t9 not in agg:
                        bisect.insort(keys, t9)
                        agg[t9] = Decimal(0)
                    agg[t9] += Decimal(qb9) / scale
                old = sorted((int(r["leg_seq"]), int(r["event_ts"]), int(r["qty_base"])) for r in rows)
                if new == old:
                    continue
                out.append({"ex": ex, "sym": sym, "sid": sid, "ns": rows[0]["source_ns"], "bts": b9, "asset_id": aids.pop(),
                            "loc": rows[0]["location"], "cv": min(int(r["classifier_ver"]) for r in rows),
                            "old": [{"pid": int(r["posting_id"]), "leg": int(r["leg_seq"]), "ts": int(r["event_ts"]), "qb": str(r["qty_base"])}
                                    for r in sorted(rows, key=lambda r: int(r["leg_seq"]))],
                            "new": [{"leg": l9, "ts": t9, "qb": str(q9)} for l9, t9, q9 in new]})
        return out

    def _exf_fix_place_apply(self, plan: list) -> int:
        n = 0
        for m in plan:
            if sum(int(o["qb"]) for o in m["old"]) != sum(int(x["qb"]) for x in m["new"]):
                raise ValueError(f"재배치 수량 불일치 {m['sid']}")
            cur = {int(r["leg_seq"]): r for r in self.conn.execute(
                "SELECT posting_id, leg_seq, event_ts, qty_base FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                (m["ns"], m["sid"])).fetchall()}
            for o in m["old"]:
                r9 = cur.get(o["leg"])
                if r9 is None or int(r9["posting_id"]) != o["pid"] or int(r9["event_ts"]) != o["ts"] or str(r9["qty_base"]) != o["qb"]:
                    raise ValueError(f"재배치 대상이 계획 뒤 바뀜 {m['sid']} leg {o['leg']}")
            want = {x["leg"]: x for x in m["new"]}
            for o in m["old"]:
                if o["leg"] not in want:
                    self._leg_sql("_exf_fix_place_apply.1", (o["pid"],))
            for l9, x in sorted(want.items()):
                if l9 in cur and int(cur[l9]["qty_base"]) > 0 and any(o["leg"] == l9 for o in m["old"]):
                    self._leg_sql("_exf_fix_place_apply.2", (int(x["ts"]), x["qb"], int(cur[l9]["posting_id"])))
                elif l9 in cur:
                    raise ValueError(f"재배치 레그 충돌 {m['sid']} leg {l9}")
                else:
                    self._leg_sql(
                        "_exf_fix_place_apply.3",
                        (m["ns"], m["sid"], l9, int(x["ts"]), int(m["asset_id"]), m["loc"], x["qb"], int(m["cv"])))
            n += 1
        return n

    def _exf_fix_place_once(self, expect=None):
        if str(self._meta_get("exf_fix_place_v") or "").split(":", 1)[0] == str(self.EXF_FIX_V):
            return None
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if str(self._meta_get("exf_fix_place_v") or "").split(":", 1)[0] == str(self.EXF_FIX_V):
                self.conn.rollback()
                return None
            plan = self._exf_fix_place_plan()
            if expect is not None and json.loads(json.dumps(plan)) != json.loads(json.dumps(expect)):
                self.conn.rollback()
                log.error("양수 정정 재배치 거부 — 잠금 안 계획(%d묶음)이 검토한 계획(%d묶음)과 다름(원장이 그 사이 바뀜)", len(plan), len(expect))
                return False
            if plan:
                statefile.atomic_write_json(paths.state(f"exf_fix_place_v{self.EXF_FIX_V}.json"),
                                         {"ts": int(time.time()), "v": self.EXF_FIX_V, "moves": plan})
            n = self._exf_fix_place_apply(plan) if plan else 0
            if n:
                self._exf_hist_touch(min(min(int(o["ts"]) for o in m["old"] + m["new"]) for m in plan))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fix_place_v', ?)", (f"{self.EXF_FIX_V}:{int(time.time())}:{n}",))
            self.conn.commit()
        except Exception as e:   # noqa: BLE001 [fallback]
            calcguard.swallowed("core_exf:ExfMixin._exf_fix_place_once", e)
            self.conn.rollback()
            log.error("양수 정정 재배치 보류(되돌림 · 다음 대사에 다시): %s", e)
            return None
        if n:
            log.warning("★해외 대사 양수 정정 %d묶음 재배치(원장이 처음 모자란 때부터 — 최소 필요량 분할) — 수량 무변, 지난 곡선 무효화★", n)
            self._exf_hist_flush()
        return n


    def _exf_unit_usd(self, ex: str, sym: str, insts: list):
        s9 = sym.upper()
        if s9 in self.EXF_STABLE_QUOTES or s9 in ("USDG", "USDE", "USD1", "TUSD"):
            return Decimal(1)
        if s9 == "KRW":
            try:
                fx = self.px.fx_at(int(time.time()) * 1000)
            except Exception as _cg9:  # noqa: BLE001 [fallback]
                calcguard.swallowed("core_exf:ExfMixin._exf_unit_usd", _cg9)
                fx = None
            return (Decimal(1) / Decimal(str(fx))) if fx else None
        for where, args in ((("p.asset_id IN (%s)" % ",".join("?" * len(insts))), list(insts)) if insts else (None, None),
                            ("a.kind='exchange_currency' AND upper(a.symbol)=?", [s9])):
            if not where:
                continue
            r = self.conn.execute(
                "SELECT p.cost_usd, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE " + where + " AND p.cost_usd IS NOT NULL AND p.leg_seq=0"
                " AND p.event IN ('EXF_BUY', 'EXF_SELL') ORDER BY p.event_ts DESC LIMIT 1", args).fetchone()
            if r:
                try:
                    qn = abs(Decimal(int(r["qty_base"]))) / (Decimal(10) ** (8 if r["decimals"] is None else int(r["decimals"])))
                    c9 = abs(Decimal(str(r["cost_usd"])))
                    if qn > 0 and c9.is_finite():
                        return c9 / qn
                except (ArithmeticError, ValueError, TypeError):
                    pass
        return None

    def _exf_micro(self, ex, sym, insts, diff: Decimal, ledger: Decimal, actual) -> bool:
        px = self._exf_unit_usd(ex, sym, insts)
        if px is not None and px > 0:
            return abs(diff) * px < self.EXF_MICRO_USD
        big = max(abs(ledger), abs(Decimal(str(actual or 0))))
        return big > 0 and abs(diff) <= big * self.EXF_MICRO_REL

    EXF_REVERT_LOG = paths.StatePath("exf_recon_revert.jsonl")

    def _exf_shrink(self, r: dict, take_base: int, loc: str, why: str = "") -> None:
        old = int(r["qty_base"])
        new = old + take_base if old < 0 else old - take_base
        if (old < 0 and new > 0) or (old > 0 and new < 0):
            new = 0
        try:
            with open(self.EXF_REVERT_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": int(time.time()), "loc": loc, "posting_id": int(r["posting_id"]), "source_id": r.get("source_id"),
                                     "leg_seq": r.get("leg_seq"), "event_ts": int(r["event_ts"]), "asset_id": int(r["asset_id"]),
                                     "old_qty_base": str(old), "new_qty_base": str(new), "why": why}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("대사 되돌림 감사 기록 실패(기장은 진행): %s", e)
            try:
                n9 = int(str(self._meta_get("exf_revert_log_fail") or "0").split(":", 1)[0] or 0)
            except ValueError:
                n9 = 0
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_revert_log_fail', ?)", (f"{n9 + 1}:{int(time.time())}",))
        if new == 0:
            self._amend_leg(r["posting_id"], r["asset_id"], loc, new - old)
            try:
                sid9 = str(r.get("source_id") or "")
                if sid9.startswith("exfrecon:") and str(loc).startswith("exchange:"):
                    sym9, b9 = sid9[len("exfrecon:"):].rsplit(":", 1)
                    self.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)",
                                      (str(loc)[len("exchange:"):], sym9.upper(), int(b9)))
            except (ValueError, sqlite3.OperationalError) as e9:
                log.warning("대사 구간 경계 기록 실패(되돌림은 진행): %s", e9)
        else:
            self._amend_leg(r["posting_id"], r["asset_id"], loc, new - old, qb_new=new)
            recon_adj.note_fix(self.conn, "K7", r["posting_id"], "shrink:" + str(why)[:40])
        r["qty_base"] = str(new)
        r["_t"] = True
        self._exf_hist_touch(r["event_ts"])

    EXF_NOW_EX = ("hyperliquid",)

    def _exf_now_sym(self, ex: str, sym: str) -> bool:
        if ex not in self.EXF_NOW_EX:
            return False
        p9 = paths.state("hl_cash_syms.json")
        try:
            mt9 = os.path.getmtime(p9)
        except OSError:
            mt9 = None
        c9 = self.__dict__.get("_hl_cash_cache")
        if not c9 or c9[0] != mt9:
            syms9 = {"USDC"}
            if mt9 is not None:
                try:
                    syms9 |= {str(x).upper() for x in ((statefile.read_json(p9, {}) or {}).get("syms") or []) if isinstance(x, str)}
                except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [optional]
                    calcguard.swallowed("core_exf:ExfMixin._exf_now_sym", _cg9)
                    pass
            c9 = (mt9, frozenset(syms9))
            self.__dict__["_hl_cash_cache"] = c9
        return str(sym or "").upper() in c9[1]


    def _exf_take(self, ex: str, sym: str, cands: list, amount: Decimal, removing_positive: bool, why: str = "") -> Decimal:
        rem = abs(amount)
        loc = f"exchange:{ex}"
        for r in cands:
            if rem <= self.EXF_TOL:
                break
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            scale = Decimal(10) ** dec
            qn = abs(Decimal(int(r["qty_base"]))) / scale
            take = min(rem, qn)
            if removing_positive and not self._exf_now_sym(ex, sym):
                take = min(take, self._exf_room(self._exf_series(ex, sym), int(r["event_ts"])))
            tb = int(take * scale)
            if tb <= 0:
                continue
            self._exf_shrink(r, tb, loc, why)
            rem -= Decimal(tb) / scale
        return rem

    def _exf_reverse(self, ex: str, sym: str, diff: Decimal, bts: int):
        sign = 1 if diff > 0 else -1
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 >= bts or q9 == 0 or (q9 > 0) == (sign > 0):
                continue
            if histmark.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id")):
                continue
            if int(r["event_ts"]) < b9 - 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (-int(r["event_ts"]), -int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=(sign < 0), why=f"되돌림(대사 {bts} 차이 {format(diff, 'f')})")
        changed = sum(1 for r in cands if r.get("_t"))
        took = abs(diff) - rem
        if took > 0:
            log.info("%s %s 지난 보정 되돌림 %s (반대 부호 %d건 대상) — 남은 차이 %s", ex, sym, format(took, "f"), len(cands),
                     format(sign * rem, "f"))
        return sign * rem, (changed if took > 0 else 0)

    def _exf_ext_open_anchor(self, ex: str, r, st_ex) -> bool:
        if self.recon_months <= 0 or int(r["leg_seq"] or 0) != 0 or int(r["qty_base"]) <= 0:
            return False
        ext = st_ex.get("ext") if isinstance(st_ex, dict) else None
        if not isinstance(ext, dict) or not ext.get("target"):
            return False
        b9 = self._exf_bts(r["source_id"])
        if b9 is None:
            return False
        et9 = int(r["event_ts"])
        old_ws = int(b9 - self.recon_months * 30 * 86400)
        return abs(et9 - old_ws) <= 60 and int(ext["target"]) < et9 - 60

    def _exf_ext_open_shrink(self, ex: str, sym: str, diff: Decimal, bts: int, st_ex=None):
        if diff >= 0:
            return diff, 0
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or b9 >= bts or not self._exf_ext_open_anchor(ex, r, st_ex):
                continue
            if int(r["event_ts"]) <= self._win_t0(b9, ex) + 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (-int(r["event_ts"]), -int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=True, why=f"확장 이중 계상 정리(대사 {bts} 차이 {format(diff, 'f')})")
        took = abs(diff) - rem
        if took > 0:
            log.info("%s %s 옛 창 시작 보정 %s 줄임(과거 창 확장 이중 계상) — 남은 차이 %s", ex, sym, format(took, "f"), format(-rem, "f"))
        return -rem, (sum(1 for r in cands if r.get("_t")) if took > 0 else 0)

    @staticmethod
    def _exf_ext_done(ext) -> bool:
        if not isinstance(ext, dict) or not ext.get("target"):
            return False
        sig9 = ext.get("_psig")
        tgt = int(ext["target"])
        return (isinstance(sig9, list) and len(sig9) >= 5 and sig9[0] == "done" and sig9[1] == ext.get("wd_from")
                and sig9[2] == ext.get("fills_from") and int(sig9[4] or 0) == tgt and int(ext.get("wd_from") or 1 << 62) <= tgt + 60)

    @staticmethod
    def _exf_settle_key(ext) -> str:
        try:
            return f"{int(ext['target'])}:{int(float(ext.get('_pat') or 0))}"
        except (TypeError, ValueError, KeyError):
            return ""

    def _exf_ext_settling(self, ex: str, st_ex, done_ts=None):
        ext = (st_ex or {}).get("ext") if isinstance(st_ex, dict) else None
        if self.recon_months <= 0 or not isinstance(ext, dict) or not ext.get("target"):
            return None
        try:
            tgt9 = int(ext["target"])
        except (TypeError, ValueError):
            return None
        now9 = int(time.time())
        if tgt9 >= now9 - int(self.recon_months * 30 * 86400) or abs(self._win_t0(now9, ex) - tgt9) > 86400:
            return None
        if self._meta_get(f"exf_ext_settled:{ex}") == self._exf_settle_key(ext):
            return None
        if done_ts and self._exf_ext_done(ext):
            try:
                after9 = int(float(done_ts)) >= int(float(ext.get("_pat") or 1 << 62))
            except (TypeError, ValueError):
                after9 = False
            if after9:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_ext_settled:{ex}", self._exf_settle_key(ext)))
                self.conn.commit()
                return None
        return ext

    def _exf_surplus_start(self, ex: str, sym: str, amt: Decimal, lo: int, hi: int, exclude=()) -> int:
        agg = {}
        ex9 = set(exclude or ())
        for r in self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            if int(r["posting_id"]) in ex9 or int(r["event_ts"]) >= hi:
                continue
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            agg[int(r["event_ts"])] = agg.get(int(r["event_ts"]), Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        tot9 = sum(agg.values(), Decimal(0))
        if tot9 <= self.EXF_TOL:
            return int(hi)
        need = min(amt, tot9) - self.EXF_TOL
        cum, t9 = Decimal(0), None
        pre = sorted((t, q) for t, q in agg.items() if t < lo)
        for _t, q in pre:
            cum += q
        t9 = lo if cum >= need else None
        for t, q in sorted((t, q) for t, q in agg.items() if t >= lo):
            cum += q
            if cum < need:
                t9 = None
            elif t9 is None:
                t9 = t
        return int(min(max(t9 if t9 is not None else hi, lo), hi))

    def _exf_ext_settle_plan(self, ex: str, bts_set) -> list:
        want9 = {int(b) for b in bts_set}
        if len(want9) > 1:
            raise ValueError(f"{ex}: 대사 시각은 거래소당 하나만(받음 {sorted(want9)})")
        rows = [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.source_id, p.event_ts, p.qty_base, p.leg_seq, a.symbol, a.decimals FROM postings p"
            " JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=?",
            (f"{ex}:recon", f"exchange:{ex}")).fetchall()]
        out = []
        for r in sorted(rows, key=lambda r: (str(r["symbol"]), int(r["event_ts"]))):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 not in want9 or q9 == 0 or int(r["leg_seq"] or 0) != 0 or abs(int(r["event_ts"]) - b9) > 60:
                continue
            dec9 = 8 if r["decimals"] is None else int(r["decimals"])
            amt9 = Decimal(q9) / (Decimal(10) ** dec9)
            if q9 > 0:
                t9 = self._exf_open_ts(ex, b9)
            else:
                t9 = self._exf_surplus_start(ex, str(r["symbol"] or "").upper(), -amt9, self._win_t0(b9, ex), b9,
                                             exclude=(int(r["posting_id"]),))
            if t9 < b9 - 60:
                out.append({"pid": int(r["posting_id"]), "sym": str(r["symbol"] or ""), "qty": str(amt9), "bts": b9,
                            "old": int(r["event_ts"]), "new": int(t9)})
        return out

    def _exf_ext_settle_repair(self, ex: str, bts_set) -> int:
        moved = 0
        t_min9 = None
        for m9 in self._exf_ext_settle_plan(ex, bts_set):
            self._leg_sql("_exf_ext_settle_repair.1", (m9["new"], m9["pid"], m9["old"]))
            moved += 1
            t_min9 = m9["new"] if t_min9 is None else min(t_min9, m9["new"])
        if moved:
            self._exf_hist_touch(t_min9)
            self.conn.commit()
            log.warning("★%s 확장 직후 대사 보정 %d건 → 음수 = 잔고가 남던 구간 시작 · 양수 = 창 시작(시각만 — 지난날 유령·누락 보유 제거)★", ex, moved)
        return moved

    def _exf_ext_redate(self, ex: str, bts: int, st_ex) -> int:
        ext = (st_ex or {}).get("ext") if isinstance(st_ex, dict) else None
        if not isinstance(ext, dict) or not ext.get("target"):
            return 0
        tgt = int(ext["target"])
        sig9 = ext.get("_psig")
        if (not isinstance(sig9, list) or len(sig9) < 5 or sig9[0] != "done"
                or sig9[1] != ext.get("wd_from") or sig9[2] != ext.get("fills_from") or int(sig9[4] or 0) != tgt):
            return 0
        if int(ext.get("wd_from") or 1 << 62) > tgt + 60:
            return 0
        moved = 0
        for r in self.conn.execute(
                "SELECT posting_id, source_id, event_ts, qty_base, leg_seq FROM postings WHERE source_ns=? AND event='EXF_ADJUST'"
                " AND location=?", (f"{ex}:recon", f"exchange:{ex}")).fetchall():
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or not self._exf_ext_open_anchor(ex, r, st_ex):
                continue
            et9 = int(r["event_ts"])
            w9 = self._win_t0(b9, ex)
            if et9 <= w9 + 60:
                continue
            self._leg_sql("_exf_ext_redate.1", (int(w9), r["posting_id"]))
            recon_adj.note_fix(self.conn, "K7", r["posting_id"], "ext_redate")
            moved += 1
            self._exf_hist_touch(w9)
        if moved:
            self.conn.commit()
            log.info("%s 옛 창 시작 보정 %d건 → 넓힌 창 시작(과거 창 확장 완료 — 옛 흐름보다 앞에)", ex, moved)
        return moved

    def _exf_absorb(self, ex: str, f: dict) -> int:
        last = self._meta_get(f"recon_done_exf_{ex}")
        try:
            ts9 = int(int(f.get("ts") or 0) / 1000)
            qty = Decimal(str(f.get("qty") or "0"))
            gross = qty * Decimal(str(f.get("price") or "0"))
        except (ArithmeticError, TypeError, ValueError):
            return 0
        if not last or ts9 <= 0 or ts9 > int(float(last)):
            return 0
        sgn = 1 if str(f.get("side")) == "buy" else -1
        n = 0
        for sym, amt in ((str(f.get("base") or "").upper(), sgn * qty), (str(f.get("quote") or "").upper(), -sgn * gross)):
            if not sym or amt == 0:
                continue
            cands = []
            for r in self._exf_adj_rows(ex, sym):
                b9 = self._exf_bts(r["source_id"])
                q9 = int(r["qty_base"])
                if b9 is None or b9 < ts9 or q9 == 0 or (q9 > 0) != (amt > 0):
                    continue
                cands.append(r)
            cands.sort(key=lambda r: (self._exf_bts(r["source_id"]), int(r["posting_id"])))
            rem = self._exf_take(ex, sym, cands, amt, removing_positive=(amt > 0), why=f"전환 흡수 {f.get('id')}")
            if abs(amt) - rem > 0:
                n += 1
                log.info("%s 전환 %s: %s %s 중 %s 를 지난 대사 보정에서 되돌림(이중 계상 방지)", ex, f.get("id"), sym,
                         format(amt, "f"), format(abs(amt) - rem, "f"))
        return n


    def exf_recon_pass(self, drained=frozenset()):
        if "ex" not in drained or time.time() - getattr(self, "_last_exfrecon", 0) < 300:
            return
        self._last_exfrecon = time.time()
        self._exf_redate_once()
        self._exf_debt_redate_once()
        self._exf_fix_place_once()
        self._exf_fut_place_once(auto=True)
        st_all = statefile.read_json(paths.state("exf_state.json"), {})
        now = int(time.time())
        for ex, st in (st_all or {}).items():
            done_ts = self._meta_get(f"recon_done_exf_{ex}")
            fst = st.get("fills") or {}
            if not fst.get("backfilled_until"):
                continue
            if self._exf_late_pending(ex):
                continue
            bal = statefile.read_json(
                paths.state(f"exf_balances_{ex}.json"), {})
            bts = int(bal.get("ts") or 0)
            balances = bal.get("balances")
            if now - bts > config.exf_fresh_sec(self.cfg) or not isinstance(balances, dict):
                continue
            if done_ts and int(float(done_ts)) >= bts:
                continue
            if self._exf_fut_hold(ex, bal, bts, done_ts, now):
                continue
            if bts + 1 > getattr(self, "_drain_at", 0):
                if now - getattr(self, "_exf_skip_log", 0) > 900:
                    self._exf_skip_log = now
                    log.info("해외대사 대기: %s 잔고ts=%d drain_at=%d (잔고가 드레인 이후)",
                             ex, bts, int(getattr(self, "_drain_at", 0)))
                continue
            actual = {str(k).upper(): float(v) for k, v in balances.items()
                      if str(k).upper() not in acct_norm.ex_off_ledger(ex)}
            debts9 = bal.get("debts") if isinstance(bal.get("debts"), dict) else {}
            for k9, v9 in debts9.items():
                ku9 = str(k9).upper()
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    continue
                if ku9 not in acct_norm.ex_off_ledger(ex) and fv9 < 0:
                    actual[ku9] = actual.get(ku9, 0.0) + fv9
            first9 = not done_ts
            settle9 = self._exf_ext_settling(ex, st, done_ts)
            cov_new9 = self._exf_cov_new(ex, bal)
            debt_now9 = {str(k9).upper(): Decimal(str(-float(v9))) for k9, v9 in debts9.items()
                         if isinstance(v9, (int, float)) and v9 < 0 and str(k9).upper() not in acct_norm.ex_off_ledger(ex)}
            added9 = self._exf_src_added(ex, bal)
            loan_since9, loan_prin9 = {}, {}
            for ln9 in (bal.get("loans") if isinstance(bal.get("loans"), list) else ()):
                if not isinstance(ln9, dict) or str(ln9.get("src") or "loan") not in added9 or not ln9.get("since"):
                    continue
                for k9 in (ln9.get("debt") or {}):
                    try:
                        loan_since9[str(k9).upper()] = min(loan_since9.get(str(k9).upper(), int(ln9["since"])), int(ln9["since"]))
                        pr9 = (ln9.get("principal") or {}).get(k9)
                        if pr9 is not None:
                            loan_prin9[str(k9).upper()] = loan_prin9.get(str(k9).upper(), Decimal(0)) + Decimal(str(pr9))
                    except (TypeError, ValueError, ArithmeticError, AttributeError):
                        pass
            try:
                debt_base9 = {k9: Decimal(str(v9)) for k9, v9 in json.loads(self._meta_get(f"recon_debt_exf_{ex}") or "{}").items()}
            except (ValueError, TypeError, ArithmeticError):
                debt_base9 = {}
            debt_keep9 = set()
            ledger = {}
            for r in self.conn.execute(
                    "SELECT p.asset_id, p.qty_base, a.symbol, a.decimals FROM postings p"
                    " JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=?",
                    (f"exchange:{ex}",)).fetchall():
                sym = (r["symbol"] or "").upper()
                if not sym:
                    continue
                ledger.setdefault(sym, {}).setdefault(r["asset_id"], [0, r["decimals"]])
                ledger[sym][r["asset_id"]][0] += int(r["qty_base"])
            n_adj = n_defer = n_rev = n_fut = 0
            fut9 = {} if first9 else self._exf_fut_window(ex, bal, bts, done_ts)
            if ex in self.EXF_FUT_EX and self._meta_get(f"exf_fut_from_{ex}") is None:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"exf_fut_from_{ex}", str(int(float(done_ts)) if done_ts else int(bts))))
            for sym in set(ledger) | set(actual) | set(fut9):
                insts = ledger.get(sym) or {}
                total_norm = Decimal(0)
                main_aid, main_abs, main_dec = None, Decimal(-1), 8
                for aid, (s, dec) in insts.items():
                    dec = 8 if dec is None else int(dec)
                    nv = Decimal(s) / (Decimal(10) ** dec)
                    total_norm += nv
                    if abs(nv) > main_abs:
                        main_aid, main_abs, main_dec = aid, abs(nv), dec
                diff = Decimal(str(actual.get(sym, 0))) - total_norm
                if fut9.get(sym):
                    if main_aid is None:
                        main_aid, main_dec = self._exf_asset(ex, sym), 8
                    fq9 = self._exf_fut_post(ex, sym, bts, fut9[sym], main_aid, main_dec)
                    if fq9:
                        diff -= fq9
                        total_norm += fq9
                        n_fut += 1
                if abs(diff) <= Decimal("0.00000001"):
                    continue
                if not first9 and self._exf_micro(ex, sym, list(insts), diff, total_norm, actual.get(sym, 0)):
                    n_defer += 1
                    debt_keep9.add(sym)
                    continue
                if (not first9 and diff < 0 and sym in debt_now9 and sym in debt_base9 and sym not in loan_since9
                        and -diff <= max(Decimal(0), debt_now9[sym] - debt_base9[sym]) + self.EXF_TOL):
                    px9 = self._exf_unit_usd(ex, sym, list(insts))
                    if px9 is not None and px9 > 0 and -diff * px9 < self.EXF_DEBT_MICRO_USD:
                        n_defer += 1
                        debt_keep9.add(sym)
                        continue
                if main_aid is None:
                    main_aid, main_dec = self._exf_asset(ex, sym), 8
                now9 = self._exf_now_sym(ex, sym)
                if not first9 and diff > 0 and not now9:
                    diff, nr9 = self._exf_reverse(ex, sym, diff, bts)
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                if not first9 and diff < 0 and not now9:
                    diff, nr9 = self._exf_ext_open_shrink(ex, sym, diff, bts, st)
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                if not first9 and diff < 0 and sym in loan_since9:
                    cap9 = min(-diff, loan_prin9[sym]) if loan_prin9.get(sym, 0) > 0 else -diff
                    rest9, nr9 = self._exf_loan_absorb(ex, sym, -cap9, bts, loan_since9[sym])
                    diff = diff + cap9 + rest9
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                loc9 = f"exchange:{ex}"
                legs9 = []
                if diff < 0 and sym in debt_now9 and not first9:
                    base9 = debt_base9.get(sym)
                    if base9 is None:
                        ip9 = -diff if -diff < debt_now9[sym] * Decimal("0.5") else Decimal(0)
                    else:
                        ip9 = min(-diff, max(Decimal(0), debt_now9[sym] - base9))
                    if ip9 > 0:
                        legs9.append((2, bts, -int(ip9 * (Decimal(10) ** main_dec))))
                    if -diff - ip9 > 0:
                        legs9.append((0, bts, int((diff + ip9) * (Decimal(10) ** main_dec))))
                elif diff > 0 and (first9 or cov_new9 or settle9 is not None):
                    legs9.append((0, self._exf_open_ts(ex, bts), int(diff * (Decimal(10) ** main_dec))))
                elif diff > 0 and now9:
                    legs9.append((0, bts, int(diff * (Decimal(10) ** main_dec))))
                elif diff > 0 and sym not in acct_norm.ex_off_ledger(ex):
                    agg9, keys9 = self._exf_agg(ex, sym)
                    sc9 = Decimal(10) ** main_dec
                    tr9, rem9 = self._exf_tranches(agg9, keys9, int(diff * sc9), sc9, bts, self._exf_open_ts(ex, bts))
                    legs9.extend(self._exf_tranche_legs(tr9, rem9, bts))
                elif diff > 0:
                    t_neg9, deficit9 = self._exf_deficit(ex, sym)
                    part9 = min(diff, deficit9) if (t_neg9 is not None and deficit9 > 0) else Decimal(0)
                    if part9 > 0:
                        legs9.append((1, max(self._exf_open_ts(ex, bts), int(t_neg9) - 1),
                                      int(part9 * (Decimal(10) ** main_dec))))
                    if diff - part9 > 0:
                        legs9.append((0, bts, int((diff - part9) * (Decimal(10) ** main_dec))))
                elif settle9 is not None:
                    legs9.append((0, self._exf_surplus_start(ex, sym, -diff, self._win_t0(bts, ex), bts),
                                  int(diff * (Decimal(10) ** main_dec))))
                else:
                    legs9.append((0, bts, int(diff * (Decimal(10) ** main_dec))))
                hit9 = False
                for seq9, ev9, qb in legs9:
                    if qb == 0:
                        continue
                    if self._post_leg('exchange', f'{ex}:recon', f'exfrecon:{sym}:{bts}', seq9, int(ev9), main_aid, loc9, qb, None, None, 'opening', 'EXF_ADJUST'):
                        recon_adj.note(self.conn, "K7", ('exchange', f'{ex}:recon', f'exfrecon:{sym}:{bts}', seq9), recon_adj.exf_why(qb, ev9, bts, seq9, {"first": first9, "cov": cov_new9, "settle": settle9 is not None, "now": now9, "debt": sym in debt_now9, "skip": sym in self.EXF_FIX_SKIP}))
                        hit9 = True
                        if ev9 < bts - 60:
                            self._exf_hist_touch(ev9)
                if hit9:
                    n_adj += 1
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                              (f"recon_done_exf_{ex}", str(bts)))
            if ex in self.EXF_FUT_EX:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_fut_cur_{ex}", json.dumps({"t": int(bts)})))
            if settle9 is not None and self._exf_ext_done(settle9):
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"exf_ext_settled:{ex}", self._exf_settle_key(settle9)))
            nb9 = {}
            for k9, v9 in debt_now9.items():
                if k9 not in debt_keep9:
                    nb9[k9] = str(v9)
                elif k9 in debt_base9:
                    nb9[k9] = str(debt_base9[k9])
            if nb9 or debt_base9:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_debt_exf_{ex}", json.dumps(nb9, sort_keys=True)))
            if isinstance(bal.get("sources"), list):
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"recon_src_exf_{ex}", json.dumps(sorted(set(map(str, bal["sources"]))))))
            self.conn.commit()
            if n_fut:
                log.info("%s 선물 정산 %d개 통화 — 정산 시각에 기장(대사 차이에서 먼저 뗌)", ex, n_fut)
            if n_adj or n_rev:
                log.info("★%s 잔고 대사 완료: %d개 통화 보정 · 지난 보정 되돌림 %d건 · 소액 보류 %d★", ex, n_adj, n_rev, n_defer)
            elif n_defer:
                log.info("%s 잔고 대사: 소액 차이 %d개 통화 보류(누적 뒤 일괄)", ex, n_defer)
            if n_rev:
                self._exf_hist_dirty = True
            try:
                if not first9 and self._exf_ext_redate(ex, bts, st_all.get(ex) if isinstance(st_all, dict) else None):
                    self._exf_hist_dirty = True
            except Exception as e9:   # noqa: BLE001 [isolate]
                calcguard.swallowed("core_exf:ExfMixin.exf_recon_pass", e9)
                self.conn.rollback()
                log.warning("%s 옛 창 시작 보정 시각 이동 실패(다음 대사): %s", ex, e9)
            if n_adj > 0:
                recon_adj.exf_dm(self.conn, self._win_t0, ex, bts, n_adj, dm, px_fn=lambda sym_, aid_: self._exf_unit_usd(ex, sym_, [aid_]))
        self._exf_hist_flush()

    def _post_exf_deposit_in(self, ex: str, uid: str, d: dict) -> bool:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            amt9 = Decimal(0)
        ccy9 = str(d.get("currency") or "").upper()
        if amt9 <= 0 or not ccy9 or self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{ex}:deposit:{uid}",)).fetchone():
            return False
        if ccy9 == "KRW":
            return False
        dts = self._iso_ts(d.get("done_at") or d.get("created_at"))
        if not dts:
            self._ex_skip_once("EX_DEPOSIT_SKIP", f"{ex}:{uid}", f"{ex} 입금 시각 없음 보류: {ccy9} {uid}")
            return False
        aid9 = self._exf_asset(ex, ccy9)
        qb9 = int(amt9 * (Decimal(10) ** 8))
        if d.get("reward") and ccy9 in self.EXF_STABLE_QUOTES:
            fx_rate = self.px.fx_at(dts * 1000)
            if self._post_leg('exchange', f'{ex}:deposit', uid, 0, dts, aid9, f'exchange:{ex}', qb9, repr(float(amt9)),
                              repr(float(amt9) * fx_rate) if fx_rate else None, 'acq', 'STAKE_REWARD'):
                return True
            return False
        if self._post_leg('exchange', f'{ex}:deposit', uid, 0, dts, aid9, f'exchange:{ex}', qb9, None, None, 'move_in', 'EXF_DEPOSIT'):
            return True
        return False

    EXF_WD_FEE_SEPARATE = frozenset(("binance", "bybit", "kucoin", "okx"))

    def _wd_fee_leg_on(self, ex: str, wts) -> bool:
        try:
            return ex in self.EXF_WD_FEE_SEPARATE and wts is not None and int(wts) >= self._wd_fee_since_of(ex)
        except (TypeError, ValueError):
            return False

    def _wd_fee_since_of(self, ex: str) -> int:
        r9 = self.conn.execute("SELECT v FROM meta WHERE k=?", (f"exf_wd_fee_since:{ex}",)).fetchone()
        if r9 is not None:
            try:
                return int(r9[0])
            except (TypeError, ValueError):
                pass
        return int(getattr(self, "wd_fee_since", 0) or 0)

    def _wd_fee_new_ex(self, ex: str) -> None:
        if ex not in self.EXF_WD_FEE_SEPARATE:
            return
        if self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_wd_fee_since:{ex}",)).fetchone():
            return
        if self.conn.execute("SELECT 1 FROM raw_ex WHERE exchange=? LIMIT 1", (ex,)).fetchone():
            return
        self.conn.execute("INSERT OR IGNORE INTO meta (k, v) VALUES (?, '0')", (f"exf_wd_fee_since:{ex}",))
        log.info("%s 처음 연결 — 출금 수수료 레그 = 모든 출금(기준 시각 0 · X9)", ex)

    def _post_exf_withdraw(self, ex: str, uid: str, d: dict) -> bool:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            amt9 = Decimal(0)
        ccy9 = str(d.get("currency") or "").upper()
        if amt9 <= 0 or not ccy9 or self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_rawskip:{ex}:withdraw:{uid}",)).fetchone():
            return False
        if ccy9 == "KRW":
            return False
        wts = self._iso_ts(d.get("created_at") or d.get("done_at"))
        if not wts:
            self._ex_skip_once("EX_WITHDRAW_SKIP", f"{ex}:{uid}", f"{ex} 출금 시각 없음 보류: {ccy9} {uid}")
            return False
        aid9 = self._exf_asset(ex, ccy9)
        qb9 = int(amt9 * (Decimal(10) ** 8))
        if self._post_leg('exchange', f'{ex}:withdraw', uid, 0, wts, aid9, f'exchange:{ex}', -qb9, None, None, 'move_out', 'EXF_WITHDRAW'):
            if self._wd_fee_leg_on(ex, wts):
                try:
                    fee9 = Decimal(str(d.get("fee") or "0"))
                except ArithmeticError:
                    fee9 = Decimal(0)
                fccy9 = str(d.get("fee_ccy") or ccy9).upper()
                if fee9.is_finite() and fee9 > 0 and fccy9 and fccy9 != "KRW":
                    faid9 = self._exf_asset(ex, fccy9)
                    fqb9 = int(fee9 * (Decimal(10) ** 8))
                    if fqb9 > 0:
                        self._post_leg('exchange', f'{ex}:withdraw', uid, 1, wts, faid9, f'exchange:{ex}', -fqb9, None, None, 'gas', 'EXF_WD_FEE')
            return True
        return False

    def _post_exf_fill(self, ex: str, f: dict) -> bool:
        fid = str(f.get("id") or "")
        try:
            qty = Decimal(str(f.get("qty") or "0"))
            px9 = Decimal(str(f.get("price") or "0"))
            ts9 = int(int(f.get("ts") or 0) / 1000)
        except (ArithmeticError, TypeError, ValueError):
            return False
        base = str(f.get("base") or "").upper()
        quote = str(f.get("quote") or "").upper()
        side = str(f.get("side") or "")
        if not fid or qty <= 0 or not base or side not in ("buy", "sell") or ts9 <= 0:
            return False
        aid = self._exf_asset(ex, base)
        qb = int(qty * (Decimal(10) ** 8))
        qu = self._quote_usd(quote, ts9)
        gross = qty * px9
        cost_usd = repr(float(gross * qu)) if (qu is not None and gross > 0) else None
        if quote == "KRW" and gross > 0:
            cost_krw = repr(float(gross))
        elif cost_usd is not None:
            fx9 = self.px.fx_at(ts9 * 1000)
            cost_krw = repr(float(gross * qu) * fx9) if fx9 else None
        else:
            cost_krw = None
        leg, evn, sgn = (("acq", "EXF_BUY", 1) if side == "buy"
                         else ("disp", "EXF_SELL", -1))
        if not self._post_leg("exchange", f"{ex}:trade", fid, 0, ts9, aid, f"exchange:{ex}", sgn * qb,
                              cost_usd, cost_krw, leg, evn):
            return False
        if quote and gross > 0:
            qaid = self._exf_asset(ex, quote)
            qqb = int(gross * (Decimal(10) ** 8))
            self._post_leg('exchange', f'{ex}:trade', fid, 1, ts9, qaid, f'exchange:{ex}', -sgn * qqb, cost_usd, cost_krw, 'disp' if side == 'buy' else 'acq', 'EXF_SELL' if side == 'buy' else 'EXF_BUY')
        try:
            fee9 = Decimal(str(f.get("fee") or "0"))
        except ArithmeticError:
            fee9 = Decimal(0)
        fee_ccy = str(f.get("fee_ccy") or "").upper()
        if fee9 != 0 and fee_ccy:
            faid = self._exf_asset(ex, fee_ccy)
            fqb = int(fee9 * (Decimal(10) ** 8))
            self._post_leg('exchange', f'{ex}:trade', fid, 2, ts9, faid, f'exchange:{ex}', -fqb, None, None, 'gas', 'EXF_FEE')
        return True
