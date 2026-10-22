import json
import time
from core_common import CLASSIFIER_VER
from core_common import dm
from decimal import Decimal
from decimal import InvalidOperation
import num_parse
import logging

log = logging.getLogger('tj-core')


class UpbitMixin:

    EX_TERMINAL_STATES = ("ACCEPTED", "DONE", "CANCELLED", "CANCELED", "REJECTED", "FAILED", "REFUNDED")

    EX_RECON_TOL = Decimal("0.000001")

    def _late_wd_note(self, acc: dict, d: dict, sgn: int, ts_s) -> None:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            return
        ccy9 = str(d.get("currency") or "").upper()
        ts9 = self._iso_ts(ts_s)
        if amt9 > 0 and ccy9 and ccy9 != "KRW" and ts9:
            acc.setdefault(ccy9, []).append((int(ts9), sgn * amt9))

    def _consume_ex(self, rec: dict):
        ex = rec.get("exchange", "upbit")
        now = int(time.time())
        self._wd_fee_new_ex(ex)
        n_new = n_matched = 0
        late_wd = {}
        for kind, rows in (("deposit", rec.get("deposits") or []),
                           ("withdraw", rec.get("withdraws") or [])):
            for d in rows:
                if not isinstance(d, dict) or not d.get("uuid"):
                    continue
                uid = str(d["uuid"])
                state = str(d.get("state") or "")
                last = self.conn.execute(
                    "SELECT revision, payload FROM raw_ex WHERE exchange=? AND kind=? AND uuid=?"
                    " ORDER BY revision DESC LIMIT 1", (ex, kind, uid)).fetchone()
                if last:
                    try:
                        last_payload = json.loads(last["payload"])
                        last_state = str(last_payload.get("state") or "")
                    except (json.JSONDecodeError, TypeError):
                        last_payload, last_state = {}, ""
                    time_fix9 = (last_state == state and not self._iso_ts(last_payload.get("created_at") or last_payload.get("done_at"))
                                 and bool(self._iso_ts(d.get("created_at") or d.get("done_at"))))
                    if time_fix9:
                        d = dict(last_payload, **{k9: v9 for k9, v9 in d.items() if v9 not in (None, "")})
                        if ex != "upbit":
                            d["late"] = 1
                    if kind == "withdraw" and last_state == state and d.get("address") and not time_fix9:
                        dest9 = {k9: str(d[k9]) for k9 in ("address", "tag", "network") if d.get(k9) not in (None, "")}
                        if any(str(last_payload.get(k9) or "") != v9 for k9, v9 in dest9.items()):
                            merged9 = dict(last_payload, **dest9)
                            if not last_payload.get("txid") and d.get("txid"):
                                merged9["txid"] = d["txid"]
                            self.conn.execute(
                                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at)"
                                " VALUES (?,?,?,?,?,?)",
                                (ex, kind, uid, last["revision"] + 1, json.dumps(merged9, ensure_ascii=False), now))
                            n_new += 1
                            continue
                    if last_state == state and (last_payload.get("txid") or not d.get("txid")) and not time_fix9:
                        continue
                    if last_state.upper() in self.EX_TERMINAL_STATES and state.upper() != last_state.upper():
                        log.info("[ex] %s %s %s 종결(%s) 뒤 옛 상태(%s) 스냅샷 무시", ex, kind, uid[:12], last_state, state)
                        continue
                    rev = last["revision"] + 1
                else:
                    rev = 1
                self.conn.execute(
                    "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (ex, kind, uid, rev, json.dumps(d, ensure_ascii=False), now))
                n_new += 1
                if kind == "deposit" and state.upper() == "ACCEPTED":
                    txid = str(d.get("txid") or "")
                    if txid:
                        n_matched += self._link_transfers(uid, txid, d.get("currency"), now)
                    if ex == "upbit":
                        dep_ts = self._iso_ts(d.get("done_at") or d.get("created_at"))
                        if dep_ts:
                            self._post_ex_deposit(uid, d, dep_ts)
                        else:
                            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 시각 없음 보류: {d.get('currency')} {uid}")
                if kind == "withdraw" and ex != "upbit" and state.upper() == "DONE":
                    if self._post_exf_withdraw(ex, uid, d) and d.get("late"):
                        self._late_wd_note(late_wd, d, -1, d.get("created_at") or d.get("done_at"))
                        if self._wd_fee_leg_on(ex, self._iso_ts(d.get("created_at") or d.get("done_at"))):
                            self._late_wd_note(late_wd, {"amount": d.get("fee"), "currency": d.get("fee_ccy") or d.get("currency")}, -1,
                                               d.get("created_at") or d.get("done_at"))
                if kind == "withdraw" and ex == "upbit" and state.upper() == "DONE":
                    self._post_ex_withdraw(uid, d)
                if kind == "deposit" and ex != "upbit" and state.upper() == "ACCEPTED":
                    if self._post_exf_deposit_in(ex, uid, d) and d.get("late"):
                        self._late_wd_note(late_wd, d, 1, d.get("done_at") or d.get("created_at"))
        if ex != "upbit":
            self._late_stage(ex, late_wd, rec)
        if n_new or n_matched:
            log.info("[ex] %s 스냅샷: revision %d건, 입금 대사 %d건", ex, n_new, n_matched)
            if n_matched:
                dm("DEPOSIT_MATCHED", f"업비트 입금 확인 대사 {n_matched}건 완료")

    def _link_transfers(self, uid: str, txid: str, currency, now: int) -> int:
        cand = txid.lower() if txid.startswith("0x") else txid
        n_syms = self.conn.execute(
            "SELECT count(DISTINCT coalesce(upper(a.symbol), '')) FROM transfers t JOIN assets a ON a.asset_id=t.asset_id"
            " WHERE t.chain_txhash IN (?, ?)", (cand, txid)).fetchone()[0]
        if n_syms <= 1:
            cur = self.conn.execute(
                "UPDATE transfers SET state='credited', ex_uuid=?, updated_at=?"
                " WHERE state='sent' AND chain_txhash IN (?, ?)", (uid, now, cand, txid))
        else:
            cur = self.conn.execute(
                "UPDATE transfers SET state='credited', ex_uuid=?, updated_at=?"
                " WHERE state='sent' AND chain_txhash IN (?, ?)"
                " AND upper((SELECT symbol FROM assets a WHERE a.asset_id=transfers.asset_id)) = ?",
                (uid, now, cand, txid, str(currency or "").upper()))
        return int(cur.rowcount or 0)

    def _upbit_asset(self, sym: str) -> int:
        symu = (sym or "").upper()
        return self.asset_id("exchange_currency", None, f"upbit:{symu}", symbol=symu, decimals=8)

    @staticmethod
    def _upbit_q8(amount):
        a = num_parse.to_dec(amount)
        if a is None or a <= 0:
            return None
        q = a * (Decimal(10) ** 8)
        if q != q.to_integral_value():
            return None
        return int(q)

    def _ex_skip_once(self, kind: str, uid: str, text: str):
        sent = getattr(self, "_ex_skip_sent", None)
        if sent is None:
            sent = self._ex_skip_sent = set()
        if uid in sent:
            return
        sent.add(uid)
        log.warning("%s uuid=%s — %s", kind, uid[:12], text)
        dm(kind, text)

    def _upbit_window_t0(self) -> int:
        if self.recon_months <= 0:
            return 0
        return self._win_t0(None, "upbit")

    def _post_ex_deposit(self, uid: str, payload: dict, dep_ts: int,
                         force_comp: bool = False) -> bool:
        if not self._iso_ts((payload or {}).get("done_at") or (payload or {}).get("created_at")):
            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 시각 없음 보류: {(payload or {}).get('currency')} {uid}")
            return False
        if str(payload.get("state") or "").upper() != "ACCEPTED":
            return False
        sym = str(payload.get("currency") or "").upper()
        if not sym or sym == "KRW":
            return False
        if dep_ts < self._upbit_window_t0():
            return False
        try:
            if Decimal(str(payload.get("amount"))) <= 0:
                return False
        except (InvalidOperation, ValueError, TypeError):
            pass
        q8 = self._upbit_q8(payload.get("amount"))
        if q8 is None:
            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 수량 보류: {sym} {uid} amount={payload.get('amount')!r}")
            return False
        aid = self._upbit_asset(sym)
        if self._post_leg('exchange', 'upbit:deposit', uid, 0, dep_ts, aid, 'exchange:upbit', q8, None, None, 'move_in', 'EX_DEPOSIT'):
            return True
        return False

    def _post_ex_withdraw(self, uid: str, d: dict) -> bool:
        if str(d.get("state") or "").upper() != "DONE":
            return False
        sym = str(d.get("currency") or "").upper()
        if not sym or sym == "KRW":
            return False
        wts0 = self._iso_ts(d.get("created_at") or d.get("done_at"))
        if not wts0:
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 시각 없음 보류: {sym} {uid}")
            return False
        if wts0 < self._upbit_window_t0():
            return False
        q8 = self._upbit_q8(d.get("amount"))
        if q8 is None:
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 수량 보류: {sym} {uid} amount={d.get('amount')!r}")
            return False
        try:
            fee = Decimal(str(d.get("fee") if d.get("fee") not in (None, "") else "0"))
            fq = fee * (Decimal(10) ** 8)
            if not fee.is_finite() or fee < 0 or fq != fq.to_integral_value():
                raise InvalidOperation
            f8 = int(fq)
        except (InvalidOperation, ValueError, TypeError):
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 수수료 보류: {sym} {uid} fee={d.get('fee')!r}")
            return False
        wts = wts0
        aid = self._upbit_asset(sym)
        if self._post_leg('exchange', 'upbit:withdraw', uid, 0, wts, aid, 'exchange:upbit', -(q8 + f8), None, None, 'move_out', 'EX_WITHDRAW'):
            return True
        return False
