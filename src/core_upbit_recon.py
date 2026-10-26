import config, paths, statefile
import json
import os
import recon_adj
import time
from core_common import dm
from decimal import Decimal
import logging

log = logging.getLogger('tj-core')


class UpbitReconMixin:

    def deposit_rematch_pass(self):
        if time.time() - getattr(self, "_last_rematch", 0) < 120:
            return
        self._last_rematch = time.time()
        now = int(time.time())
        rows = self.conn.execute(
            "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
            " AND uuid NOT IN (SELECT ex_uuid FROM transfers WHERE ex_uuid IS NOT NULL)"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall()
        n = 0
        for d in rows:
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            if str(p.get("state") or "").upper() != "ACCEPTED":
                continue
            txid = str(p.get("txid") or "")
            if not txid:
                continue
            linked = self._link_transfers(d["uuid"], txid, p.get("currency"), now)
            if not linked:
                continue
            dep_ts = self._iso_ts(p.get("done_at") or p.get("created_at")) or now
            self._post_ex_deposit(d["uuid"], p, dep_ts)
            n += linked
        for d in self.conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw' AND exchange='upbit'"
                " AND uuid NOT IN (SELECT source_id FROM postings WHERE source_ns='upbit:withdraw')"
                " GROUP BY uuid HAVING revision = MAX(revision) ORDER BY observed_at, uuid").fetchall():
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            if self._post_ex_withdraw(d["uuid"], p):
                n += 1
        for d in self.conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
                " AND uuid NOT IN (SELECT source_id FROM postings WHERE source_ns='upbit:deposit')"
                " GROUP BY uuid HAVING revision = MAX(revision) ORDER BY observed_at, uuid").fetchall():
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            dep_ts = self._iso_ts(p.get("done_at") or p.get("created_at")) or now
            if self._post_ex_deposit(d["uuid"], p, dep_ts):
                log.info("자가치유: posting 없던 업비트 입금 기장 uuid=%s", d["uuid"][:12])
                n += 1
        for exkind, st_need, poster in (("withdraw", "DONE", self._post_exf_withdraw),
                                        ("deposit", "ACCEPTED", self._post_exf_deposit_in)):
            for d in self.conn.execute(
                    "SELECT exchange, uuid, payload FROM raw_ex WHERE kind=?"
                    " AND exchange != 'upbit'"
                    " AND NOT EXISTS (SELECT 1 FROM postings p WHERE p.source_kind = 'exchange' AND p.source_ns ="
                    "   raw_ex.exchange || ':' || raw_ex.kind AND p.source_id = raw_ex.uuid)"
                    " GROUP BY exchange, uuid HAVING revision = MAX(revision)",
                    (exkind,)).fetchall():
                try:
                    p = json.loads(d["payload"])
                except json.JSONDecodeError:
                    continue
                if str(p.get("state") or "").upper() != st_need:
                    continue
                if poster(d["exchange"], d["uuid"], p):
                    n += 1
        self.conn.commit()
        if n:
            log.info("입금 재대사: %d건 추가 매칭", n)

    def exchange_recon_pass(self, drained=frozenset()):
        if self._meta_get("recon_done_upbit") or \
                time.time() - getattr(self, "_last_exrecon", 0) < 300:
            return
        self._last_exrecon = time.time()
        st_p = paths.state("upbit_orders_state.json")
        bal_p = paths.state("upbit_balances.json")
        st = statefile.read_json(st_p, {}) if os.path.exists(st_p) else {}
        bal = statefile.read_json(bal_p, {}) if os.path.exists(bal_p) else {}
        if not st.get("complete") or "ex" not in drained:
            return
        if time.time() - float(st.get("backfilled_until") or 0) > 8 * 86400:
            return
        if time.time() - (bal.get("ts") or 0) > config.upbit_fresh_sec(self.cfg):
            return
        inflight = set()
        last_obs = 0
        edge = 0
        for r_if in self.conn.execute(
                "SELECT r.kind, r.payload, r.observed_at FROM raw_ex r JOIN"
                " (SELECT exchange, kind, uuid, max(revision) AS revision FROM raw_ex WHERE exchange='upbit'"
                "  AND kind IN ('deposit','withdraw') GROUP BY exchange, kind, uuid) x"
                " ON x.exchange=r.exchange AND x.kind=r.kind AND x.uuid=r.uuid AND x.revision=r.revision"):
            last_obs = max(last_obs, int(r_if["observed_at"] or 0))
            try:
                p_if = json.loads(r_if["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            st_if = str(p_if.get("state") or "").upper()
            if st_if in self.EX_TERMINAL_STATES:
                edge = max([edge] + [min(self._iso_ts(p_if.get(k_if)) or 0, int(r_if["observed_at"] or 0)) for k_if in ("created_at", "done_at")])
            if st_if and st_if not in self.EX_TERMINAL_STATES:
                inflight.add(str(p_if.get("currency") or "").upper())
            elif st_if in ("DONE", "ACCEPTED") and not self._iso_ts(p_if.get("created_at") or p_if.get("done_at")):
                inflight.add(str(p_if.get("currency") or "").upper())
        if last_obs - int(bal.get("ts") or 0) > 120:
            log.info("거래소 잔고 대사 보류 — 잔고 스냅샷(%d)이 마지막 원본 동기화(%d)보다 오래됨", int(bal.get("ts") or 0), last_obs)
            return
        if edge and edge >= int(bal.get("ts") or 0) - 30:
            log.info("거래소 잔고 대사 보류 — 잔고 스냅샷(%d) 무렵·뒤에 끝난 입출금(%d) — 다음 스냅샷으로", int(bal.get("ts") or 0), int(edge))
            self._last_exrecon = time.time() - 240
            return
        actual = {}
        locked_now = set(inflight)
        accounts = bal.get("accounts")
        if not isinstance(accounts, list):
            raise ValueError("업비트 잔고 accounts 형식 오류 — 대사 보류")
        for a in accounts:
            if not isinstance(a, dict):
                raise ValueError("업비트 잔고 행 형식 오류 — 대사 보류")
            cur = str(a.get("currency") or "").strip().upper()
            if not cur:
                raise ValueError("업비트 잔고 currency 누락 — 대사 보류")
            if cur == "KRW":
                continue
            try:
                if a["locked"] is None or a["balance"] is None or isinstance(a["locked"], bool) or isinstance(a["balance"], bool):
                    raise TypeError("null")
                locked_v = Decimal(str(a["locked"]).strip())
                balance_v = Decimal(str(a["balance"]).strip())
            except (KeyError, TypeError, ValueError, ArithmeticError) as e:
                raise ValueError(f"업비트 잔고 파싱 실패 {cur}: {a.get('balance')!r}/{a.get('locked')!r}") from e
            if not (balance_v.is_finite() and locked_v.is_finite()):
                raise ValueError(f"업비트 잔고 비유한값 {cur}")
            actual[cur] = balance_v + locked_v
            if locked_v > 0:
                locked_now.add(cur)
        oo = bal.get("open_orders")
        pend_fill = {}
        if isinstance(oo, list):
            oo_ok = True
            oo_uuids = set()
            for o9 in oo:
                if not isinstance(o9, dict) or not o9.get("uuid"):
                    oo_ok = False
                    break
                oo_uuids.add(str(o9["uuid"]))
                p9 = self._upbit_open_partial(o9)
                if p9 is None:
                    oo_ok = False
                    break
                for sym9, dq in p9.items():
                    pend_fill[sym9] = pend_fill.get(sym9, Decimal(0)) + dq
            if oo_ok:
                locked_now = set(inflight)
                bts9 = int(bal.get("ts") or 0)
                in9 = (" OR uuid IN (%s)" % ",".join("?" * len(oo_uuids))) if oo_uuids else ""
                for r_o in self.conn.execute(
                        "SELECT uuid, payload, observed_at FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                        " AND (observed_at >= ?" + in9 + ")", (bts9 - 5, *sorted(oo_uuids))).fetchall():
                    try:
                        mk9 = str(json.loads(r_o["payload"]).get("market") or "")
                    except (json.JSONDecodeError, TypeError):
                        mk9 = ""
                    for s9 in (mk9.split("-", 1) if "-" in mk9 else []):
                        if s9.upper() != "KRW":
                            locked_now.add(s9.upper())
            else:
                pend_fill = {}
        for sym9, dq in pend_fill.items():
            if sym9 in actual:
                actual[sym9] = actual[sym9] - Decimal(str(dq))
        ledger = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, a.symbol, a.decimals FROM postings p"
                " JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location='exchange:upbit'").fetchall():
            sym = (r["symbol"] or "").upper()
            if not sym:
                continue
            ledger.setdefault(sym, {}).setdefault(r["asset_id"], [0, r["decimals"]])
            ledger[sym][r["asset_id"]][0] += int(r["qty_base"])
        now = int(time.time())
        anchor_ts = int(bal.get("ts") or now)
        n_adj = 0
        n_locked_skip = 0
        for sym, insts in ledger.items():
            total_norm = Decimal(0)
            for aid, (s, dec) in insts.items():
                dec = dec if dec is not None else 18
                total_norm += Decimal(s) / (Decimal(10) ** int(dec))
            tgt = Decimal(str(actual.get(sym, 0)))
            diff = tgt - total_norm
            if abs(diff) <= self.EX_RECON_TOL:
                continue
            if sym in locked_now:
                n_locked_skip += 1
                continue
            main_aid, main_dec = self._upbit_asset(sym), 8
            qb = int(diff * (Decimal(10) ** main_dec))
            if qb == 0:
                continue
            ev_ts9 = self._win_t0(anchor_ts, "upbit") if (qb > 0 and self.recon_months > 0) else anchor_ts
            if self._post_leg('exchange', 'upbit:recon', f'exrecon:{sym}:{anchor_ts}', 0, ev_ts9, main_aid, 'exchange:upbit', qb, None, None, 'opening', 'EX_ADJUST'):
                recon_adj.note(self.conn, "K10", ('exchange', 'upbit:recon', f'exrecon:{sym}:{anchor_ts}', 0), "pos_window_start" if ev_ts9 != anchor_ts else ("untracked_out" if qb < 0 else "later_in"))
                n_adj += 1
        if n_locked_skip:
            self.conn.commit()
            sig9 = (n_adj, n_locked_skip)
            if n_adj or sig9 != getattr(self, "_exr_partial_sig", None) \
                    or time.time() - getattr(self, "_exr_partial_log", 0) > 3600:
                self._exr_partial_sig = sig9
                self._exr_partial_log = time.time()
                log.info("거래소 잔고 대사 부분 완료: %d 보정, %d 통화는 주문 진행 중 — 재시도 예정",
                         n_adj, n_locked_skip)
            return
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_upbit', ?)",
                          (str(anchor_ts),))
        self.conn.commit()
        log.info("★거래소 잔고 대사 완료: %d개 통화 보정★", n_adj)
        dm("EX_RECON", f"업비트 잔고 대사 완료 — {n_adj}개 통화 보정")
