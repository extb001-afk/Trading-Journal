from __future__ import annotations
import acct_norm
import paths, statefile
import json
import os
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from timeutil import KST
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


class KrwMixin:

    @staticmethod
    def _upbit_led_timeline(conn):
        out = {}
        try:
            for r in conn.execute("SELECT a.group_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                  " WHERE p.location='exchange:upbit' AND a.group_id IS NOT NULL AND a.kind!='fiat'"):
                q9 = Decimal(int(r[2])) / (Decimal(10) ** int(r[3] if r[3] is not None else 18))
                if q9:
                    out.setdefault(int(r[0]), []).append((int(r[1]), q9))
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_krw:KrwMixin._upbit_led_timeline", e9)
            log.warning("원장 업비트 위치 이력 조회 실패(지난날 업비트 미매칭 몫 빼기 생략): %s", e9)
            return {}
        for v9 in out.values():
            v9.sort()
        return out

    def _upbit_krw_timeline(self, conn):
        try:
            key9 = tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM raw_ex WHERE exchange='upbit'"
                                      " AND kind IN ('order', 'deposit', 'withdraw')").fetchone())
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_krw:KrwMixin._upbit_krw_timeline", e9, expected=calcguard.db_env(e9))
            log.warning("업비트 원화 타임라인 조회 실패(과거일 이월 유지): %s", e9)
            return None
        if self._upbit_krw_tl and self._upbit_krw_tl[0] == key9:
            return self._upbit_krw_tl[1]
        latest = {}
        for kind9, uid9, rev9, pl9 in conn.execute(
                "SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange='upbit' AND kind IN ('order', 'deposit', 'withdraw')"):
            k9 = (kind9, uid9)
            if k9 not in latest or int(rev9) > latest[k9][0]:
                latest[k9] = (int(rev9), pl9)
        tl = []
        tlo = []
        for (kind9, _u9), (_r9, pl9) in latest.items():
            try:
                o = json.loads(pl9)
                if kind9 == "order":
                    if not str(o.get("market") or "").upper().startswith("KRW-"):
                        continue
                    side = str(o.get("side") or "").lower()
                    funds9 = o.get("executed_funds")
                    funds = (Decimal(str(funds9)) if funds9 is not None
                             else Decimal(str(o.get("price") or "0")) * Decimal(str(o.get("executed_volume") or "0")))
                    fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
                    if side not in ("bid", "ask") or (funds == 0 and fee == 0):
                        continue
                    d9 = (funds - fee) if side == "ask" else -(funds + fee)
                    ts9 = acct_norm.fill_ts(o) or datetime.fromisoformat(str(o["created_at"])).timestamp()
                elif str(o.get("currency") or "").upper() == "KRW":
                    st9 = str(o.get("state") or "").upper()
                    amt = Decimal(str(o.get("amount") or "0"))
                    if kind9 == "deposit" and st9 == "ACCEPTED":
                        d9 = amt
                    elif kind9 == "withdraw" and st9 == "DONE":
                        d9 = -(amt + Decimal(str(o.get("fee") or "0")))
                    else:
                        continue
                    ts9 = datetime.fromisoformat(str(o.get("done_at") or o["created_at"])).timestamp()
                else:
                    continue
            except (ValueError, TypeError, KeyError, InvalidOperation):
                continue
            tl.append((int(ts9), d9))
            if kind9 == "order":
                tlo.append((int(ts9), d9))
        tl.sort(key=lambda x: x[0])
        self._upbit_krw_tl = (key9, tl, tlo)
        return tl

    KRW_ROLL_MARGIN = 5

    @staticmethod
    def _krw_roll(tl, ts, margin=None) -> tuple:
        m9 = KrwMixin.KRW_ROLL_MARGIN if margin is None else margin
        tot, last = 0.0, float(ts)
        for t9, d9 in tl or ():
            if float(t9) > float(ts) + m9:
                tot += float(d9)
                last = max(last, float(t9))
        return tot, last

    @staticmethod
    def _cash_legs(legs, d9):
        if not isinstance(legs, list) or len(legs) < 2:
            return None
        try:
            lg = [(int(l9[0]), Decimal(str(l9[1]))) for l9 in legs]
        except (TypeError, ValueError, InvalidOperation, IndexError):
            return None
        tot = sum(f for _t, f in lg)
        if tot <= 0 or any(f < 0 or t <= 0 for t, f in lg):
            return None
        out, acc = [], Decimal(0)
        for i, (t, f) in enumerate(lg):
            p9 = (d9 - acc) if i == len(lg) - 1 else (d9 * f / tot)
            acc += p9
            if p9:
                out.append((t, p9))
        return out

    def _bithumb_krw_timeline(self, conn, *, split=True):
        try:
            key9 = tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM raw_ex WHERE exchange='bithumb'"
                                      " AND kind IN ('trade', 'deposit', 'withdraw')").fetchone())
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_krw:KrwMixin._bithumb_krw_timeline", e9)
            log.warning("빗썸 원화 타임라인 조회 실패(지난날 빗썸 원화 = 이월): %s", e9)
            return None
        cache9 = "_bt_krw_tl" if split else "_bt_krw_order_tl"
        c9 = self.__dict__.get(cache9)
        if c9 and c9[0] == key9:
            return c9[1]
        latest = {}
        for kind9, uid9, rev9, pl9 in conn.execute(
                "SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange='bithumb' AND kind IN ('trade', 'deposit', 'withdraw')"):
            k9 = (kind9, uid9)
            if k9 not in latest or int(rev9) > latest[k9][0]:
                latest[k9] = (int(rev9), pl9)
        tl = []
        for (kind9, _u9), (_r9, pl9) in latest.items():
            try:
                o = json.loads(pl9)
                if kind9 == "trade":
                    side9 = str(o.get("side") or "").lower()
                    if str(o.get("quote") or "").upper() != "KRW" or side9 not in ("buy", "sell"):
                        continue
                    f9 = o.get("funds")
                    amt = Decimal(str(f9)) if f9 not in (None, "") else Decimal(str(o.get("price") or "0")) * Decimal(str(o.get("qty") or "0"))
                    fee = Decimal(str(o.get("fee") or "0")) if str(o.get("fee_ccy") or "").upper() == "KRW" else Decimal(0)
                    d9 = (amt - fee) if side9 == "sell" else -(amt + fee)
                    ts9 = int(o["ts"]) / 1000.0
                    legs9 = type(self)._cash_legs(o.get("cashlegs"), d9) if split else None
                    if legs9:
                        tl.extend(legs9)
                        continue
                elif str(o.get("currency") or "").upper() == "KRW":
                    st9 = str(o.get("state") or "").upper()
                    amt = Decimal(str(o.get("amount") or "0"))
                    if kind9 == "deposit" and st9 == "ACCEPTED":
                        d9 = amt
                    elif kind9 == "withdraw" and st9 == "DONE":
                        d9 = -(amt + Decimal(str(o.get("fee") or "0")))
                    else:
                        continue
                    ts9 = datetime.fromisoformat(str(o.get("done_at") or o["created_at"])).timestamp()
                else:
                    continue
            except (ValueError, TypeError, KeyError, InvalidOperation):
                continue
            if d9:
                tl.append((int(ts9), d9))
        tl.sort(key=lambda x: x[0])
        self.__dict__[cache9] = (key9, tl)
        return tl

    def _x_src(self, conn, ub2, krw_obs, ubs_seen, lp_total, rate_fx, now):
        up_ts9 = float((ub2 or {}).get("ts") or 0)
        up_krw9 = None
        if ub2 and up_ts9:
            up_krw9 = 0.0
            for acc in ub2.get("accounts") or []:
                if acc.get("currency") == "KRW":
                    try:
                        up_krw9 += max(float(acc.get("balance") or 0) + float(acc.get("locked") or 0), 0.0)
                    except (TypeError, ValueError):
                        pass
        bt9 = (krw_obs or {}).get("bithumb")
        tl_u9 = self._upbit_krw_timeline(conn)
        tl_b9 = self._bithumb_krw_timeline(conn, split=False)
        tl_u9 = [(int(t9), float(d9)) for t9, d9 in tl_u9] if tl_u9 is not None else None
        tl_b9 = [(int(t9), float(d9)) for t9, d9 in tl_b9] if tl_b9 is not None else None
        first9 = {"ub": None, "rest": None}
        try:
            r9 = conn.execute("SELECT MIN(event_ts) FROM postings WHERE location = 'exchange:upbit'").fetchone()
            f9 = [int(r9[0])] if r9 and r9[0] is not None else []
            if tl_u9:
                f9.append(int(tl_u9[0][0]))
            first9["ub"] = min(f9) if f9 else None
            r9 = conn.execute("SELECT MIN(event_ts) FROM postings WHERE location >= 'lp:' AND location < 'lp;'").fetchone()
            first9["rest"] = int(r9[0]) if r9 and r9[0] is not None else None
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_krw:KrwMixin._x_src", e9)
            first9.pop("rest", None)
            log.warning("원장 밖 금액 첫 활동 시각 조회 실패(자르지 않음): %s", e9)
        oth9 = sum(v9[0] for e9, v9 in (krw_obs or {}).items() if e9 != "bithumb")
        return {"now": {"ts": float(now), "ku": up_krw9, "kb": float(bt9[0]) if bt9 else None,
                        "ub": {s9: [a9[0], a9[1]] for s9, a9 in ubs_seen.items()} if ubs_seen is not None else None,
                        "rest": round(float(lp_total) + oth9 / float(rate_fx), 2)},
                "base": {"ku": [up_krw9, up_ts9] if up_krw9 is not None else None,
                         "kb": [float(bt9[0]), float(bt9[1])] if bt9 and bt9[1] else None},
                "tl": {"ku": tl_u9, "kb": tl_b9}, "first": first9}

    KRW_FAIL_ST = frozenset(("REJECTED", "FAILED", "CANCELLED", "CANCELED", "REFUNDED"))

    @staticmethod
    def _krw_bank_moves(conn, exs):
        exs = tuple(exs)
        if not exs:
            return []
        latest9 = {}
        for ex9, kind9, uid9, rev9, pl9 in conn.execute(
                "SELECT exchange, kind, uuid, revision, payload FROM raw_ex WHERE exchange IN (" + ",".join("?" * len(exs)) + ")"
                " AND kind IN ('deposit', 'withdraw')", exs):
            k9 = (ex9, kind9, uid9)
            if k9 not in latest9 or int(rev9) > latest9[k9][0]:
                latest9[k9] = (int(rev9), pl9)
        out = []
        for (ex9, kind9, _u9), (_r9, pl9) in latest9.items():
            try:
                o9 = json.loads(pl9)
                if str(o9.get("currency") or "").upper() != "KRW":
                    continue
                st9 = str(o9.get("state") or "").upper()
                amt9 = float(o9.get("amount") or 0)
                if kind9 == "deposit" and st9 == "ACCEPTED":
                    k9 = amt9
                elif kind9 == "withdraw" and st9 == "DONE":
                    k9 = -(amt9 + float(o9.get("fee") or 0))
                else:
                    continue
                ts9 = datetime.fromisoformat(str(o9.get("done_at") or o9["created_at"])).timestamp()
                int9 = kind9 == "deposit" and (str(o9.get("transaction_type") or "").lower() == "internal"
                                               or str(o9.get("txid") or "").startswith(("quarterly_payment", "quick_payment")))
            except (ValueError, TypeError, KeyError):
                continue
            out.append((ex9, ts9, k9, int9))
        return out

    @staticmethod
    def _krw_flow_row(ex9, exn9, kind9, uid9, o):
        if str(o.get("currency") or "").upper() != "KRW":
            return None
        st9 = str(o.get("state") or "").upper()
        amt9 = Decimal(str(o.get("amount") or "0"))
        fee9 = Decimal(str(o.get("fee") or "0")) if kind9 == "withdraw" else Decimal(0)
        if not amt9.is_finite() or not fee9.is_finite() or amt9 <= 0:
            return None
        done9 = (st9 == "ACCEPTED") if kind9 == "deposit" else (st9 == "DONE")
        stx9 = "done" if done9 else ("fail" if st9 in KrwMixin.KRW_FAIL_ST else "wait")
        tsr9 = (o.get("done_at") if done9 else None) or o.get("created_at")
        ts9 = int(datetime.fromisoformat(str(tsr9)).timestamp())
        txid9 = str(o.get("txid") or "")
        internal9 = kind9 == "deposit" and (str(o.get("transaction_type") or "").lower() == "internal"
                                           or txid9.startswith(("quarterly_payment", "quick_payment")))
        note9 = ("예치금 이용료(분기 지급)" if txid9.startswith("quarterly_payment") else "거래소 내부 지급") if internal9 else ""
        return {"key": f"{ex9}:{kind9}:{uid9}", "t": ts9, "d": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"),
                "ex": exn9, "dir": "in" if kind9 == "deposit" else "out", "amt": int(amt9.to_integral_value()),
                "fee": int(fee9.to_integral_value()), "st": stx9, "stRaw": st9, "src": "int" if internal9 else "bank", "note": note9}

    def _krw_flows(self, conn):
        try:
            key9 = tuple(tuple(r9) for r9 in conn.execute(
                "SELECT exchange, COUNT(*), MAX(observed_at) FROM raw_ex WHERE exchange IN ('upbit', 'bithumb')"
                " GROUP BY exchange ORDER BY exchange").fetchall())
        except Exception as e9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_krw:KrwMixin._krw_flows", e9)
            log.warning("원화 입출금 조회 실패: %s", e9)
            return None
        c9 = self.__dict__.get("_krw_fl_c")
        if c9 and c9[0] == key9:
            return c9[1]
        conn9 = {ex9 for ex9, _n9, _m9 in key9}
        rows, cov = [], {}
        for ex9, exn9 in self.KRW_FLOW_EX:
            latest9 = {}
            for kind9, uid9, rev9, pl9 in conn.execute(
                    "SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange=? AND kind IN ('deposit', 'withdraw')", (ex9,)):
                if (kind9, uid9) not in latest9 or int(rev9) > latest9[(kind9, uid9)][0]:
                    latest9[(kind9, uid9)] = (int(rev9), pl9)
            n9 = 0
            for (kind9, uid9), (_r9, pl9) in latest9.items():
                try:
                    r9 = self._krw_flow_row(ex9, exn9, kind9, uid9, json.loads(pl9))
                except (ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
                    continue
                if r9:
                    rows.append(r9)
                    n9 += 1
            cov[ex9] = {"name": exn9, "on": ex9 in conn9, "n": n9}
        rows.sort(key=lambda r9: (-r9["t"], r9["key"]))
        mon, tot = {}, {"in": 0, "out": 0, "fee": 0, "net": 0, "intIn": 0, "n": 0, "fail": 0, "wait": 0, "first": None, "last": None}
        for r9 in rows:
            ym9 = r9["d"][:7]
            b9 = mon.setdefault(ym9, {"ym": ym9, "in": 0, "out": 0, "fee": 0, "net": 0, "intIn": 0, "n": 0, "fail": 0, "wait": 0})
            for a9 in (b9, tot):
                if r9["st"] != "done":
                    a9[r9["st"]] += 1
                    continue
                a9["n"] += 1
                if r9["src"] == "int":
                    a9["intIn"] += r9["amt"]
                elif r9["dir"] == "in":
                    a9["in"] += r9["amt"]
                else:
                    a9["out"] += r9["amt"]
                    a9["fee"] += r9["fee"]
                a9["net"] = a9["in"] - a9["out"]
            if r9["st"] == "done":
                d9 = r9["d"][:10]
                tot["first"] = d9 if not tot["first"] or d9 < tot["first"] else tot["first"]
                tot["last"] = d9 if not tot["last"] or d9 > tot["last"] else tot["last"]
        out = {"rows": rows, "byMonth": [mon[k9] for k9 in sorted(mon, reverse=True)], "total": tot, "cov": cov}
        self._krw_fl_c = (key9, out)
        return out

    @staticmethod
    def _exf_bal_view() -> dict:
        out = {}
        for ex9 in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb", "coinbase"):
            bp0 = paths.state(f"exf_balances_{ex9}.json")
            for c9 in (bp0, bp0 + ".pending", bp0 + ".view"):
                try:
                    d9 = statefile.read_json(c9, {}) if os.path.exists(c9) else {}
                except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
                    calcguard.swallowed("view_krw:KrwMixin._exf_bal_view", _cg9)
                    d9 = {}
                if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                    out[ex9] = (c9, d9)
                    break
        return out

    @staticmethod
    def _flow_debts() -> dict:
        out = {}
        for ex9 in ("binance", "bybit", "okx", "kucoin", "gate", "bithumb", "coinbase"):
            bp9 = paths.state(f"exf_balances_{ex9}.json")
            if not os.path.exists(bp9):
                continue
            try:
                dd9 = (statefile.read_json(bp9, {}) or {}).get("debts")
            except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [isolate]
                calcguard.swallowed("view_krw:KrwMixin._flow_debts", _cg9)
                continue
            for s9, v9 in (dd9.items() if isinstance(dd9, dict) else ()):
                try:
                    fv9 = Decimal(str(v9))
                except (InvalidOperation, ValueError, TypeError):
                    continue
                if fv9.is_finite() and fv9 < 0:
                    out.setdefault(f"{ex9}:recon", {})[str(s9).upper()] = fv9
        return out
