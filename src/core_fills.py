import acct_norm
import histmark, logs, timeutil
import json
import pricing
import time
from decimal import Decimal
from decimal import InvalidOperation
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-core')


class FillsMixin:

    @staticmethod
    def _iso_ts(s):
        return timeutil.iso_epoch(s)

    def _fill_group_asset(self, base_sym: str, ts: int):
        return self._upbit_asset(base_sym)

    def _consume_fills(self, rec: dict):
        n = 0
        for o in rec.get("orders") or []:
            if not isinstance(o, dict) or not o.get("uuid"):
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload,"
                " observed_at) VALUES ('upbit', 'order', ?, 1, ?, ?)",
                (o["uuid"], json.dumps(o, ensure_ascii=False), int(time.time())))
            market = str(o.get("market") or "")
            if not market.startswith("KRW-"):
                if self._post_upbit_quote_fill(o):
                    n += 1
                continue
            base = market[4:]
            try:
                vol = Decimal(str(o.get("executed_volume") or "0"))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if not vol.is_finite() or vol <= 0:
                continue
            side = str(o.get("side") or "").lower()
            if side not in ("bid", "ask"):
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"주문 side 미상 보류: {market} {o.get('uuid')} side={side!r}")
                continue
            ts = acct_norm.fill_ts(o) or self._iso_ts(o.get("created_at"))
            if not ts:
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"주문 시각 없음 보류: {market} {o.get('uuid')}")
                continue
            try:
                fee_krw = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
                funds = o.get("executed_funds")
                krw = (Decimal(str(funds)) if funds is not None
                       else Decimal(str(o.get("price") or "0")) * vol)
            except (InvalidOperation, ValueError, TypeError):
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결금액 파싱 실패 보류: {market} {o.get('uuid')}")
                continue
            if not (krw.is_finite() and fee_krw.is_finite()) or krw <= 0 or fee_krw < 0:
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결금액 미상 보류: {market} {o.get('uuid')}")
                continue
            fx = self.px.fx_at(ts * 1000)
            net_krw = (krw - fee_krw) if side == "ask" else (krw + fee_krw)
            usd = (float(net_krw) / fx) if fx else None
            aid = self._fill_group_asset(base, ts)
            ar = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()
            dec = ar["decimals"] if ar and ar["decimals"] is not None else 8
            qv = vol * (Decimal(10) ** int(dec))
            if qv != qv.to_integral_value():
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결 수량 {dec}자리 초과 보류: {market} {o.get('uuid')} vol={vol}")
                continue
            qty_base = int(qv)
            if side == "ask":
                lk, ev2, qb = "disp", "EX_SELL", -qty_base
            else:
                lk, ev2, qb = "acq", "EX_BUY", qty_base
            if self._post_leg('exchange', 'upbit:order', o['uuid'], 0, ts, aid, 'exchange:upbit', qb, repr(usd) if usd is not None else None, str(net_krw), lk, ev2):
                n += 1
        if n:
            log.info("[ex] 업비트 체결 %d건 원장 반영", n)

    def _consume_order_trades(self, rec: dict):
        n_ok = n_moved = n_skip = 0
        t_min = None
        why_n = {}

        def legs(u9):
            return self.conn.execute(
                "SELECT leg_seq, asset_id, location, qty_base, leg_kind, event, event_ts, cost_usd FROM postings"
                " WHERE source_kind='exchange' AND source_ns='upbit:order' AND source_id=?", (u9,)).fetchall()

        def shape(rows):
            return sorted((int(r["leg_seq"]), int(r["asset_id"]), str(r["location"]), str(int(r["qty_base"])), str(r["leg_kind"]), str(r["event"]))
                          for r in rows)
        for it in rec.get("orders") or []:
            u = str((it or {}).get("uuid") or "") if isinstance(it, dict) else ""
            row = self.conn.execute("SELECT revision, payload, observed_at FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid=?"
                                    " ORDER BY revision DESC LIMIT 1", (u,)).fetchone() if u else None
            try:
                old = json.loads(row["payload"]) if row else None
            except json.JSONDecodeError:
                old = None
            merged, why = acct_norm.trades_fill_merge(old, it) if isinstance(old, dict) else (None, "원본 없음")
            if merged is None:
                why_n[why] = why_n.get(why, 0) + 1
                n_skip += 1
                if why != "이미 체결 목록 있음":
                    log.warning("업비트 옛 주문 체결 목록 채우기 건너뜀 %s: %s", u[:12], why)
                continue
            merged["_tj_trades_fill"] = {"at": int(rec.get("ts") or time.time()), "src": str(rec.get("src") or "")[:60]}
            new_ts = acct_norm.fill_ts(merged)
            self.conn.execute("SAVEPOINT order_trades")
            undo = None
            self.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit', 'order', ?, ?, ?, ?)",
                              (u, int(row["revision"]) + 1, json.dumps(merged, ensure_ascii=False), int(row["observed_at"])))
            olds = legs(u)
            if olds and any(int(o["event_ts"]) != new_ts for o in olds):
                self._unpost_source("exchange", "upbit:order", u)
                self._consume_fills({"orders": [merged]})
                news = legs(u)
                if shape(news) != shape(olds) or any(int(r9["event_ts"]) != new_ts for r9 in news):
                    undo = "다시 만든 레그가 다름"
                elif any(o["cost_usd"] is not None for o in olds) and any(r9["cost_usd"] is None for r9 in news):
                    undo = "새 시각 원가 USD 미확보(이번 적용 중 환율·쿼트 시세를 못 받음 — 조회 실패 또는 실패 뒤 60초 쉼 동안의 주문 · 다음 --apply 때 다시)"
                else:
                    n_moved += 1
                    t_min = min([t for t in [t_min, new_ts] + [int(o["event_ts"]) for o in olds] if t is not None])
            if undo:
                self.conn.execute("ROLLBACK TO order_trades")
                why_n[undo] = why_n.get(undo, 0) + 1
                n_skip += 1
                log.warning("업비트 옛 주문 %s 체결 시각 재기장 되돌림(원본 개정도 취소 — 다음 적용 때 재시도): %s", u[:12], undo)
            else:
                n_ok += 1
            self.conn.execute("RELEASE order_trades")
        if n_moved:
            self._inval_daily()
            try:
                log.info("장기 곡선 다시 계산 표식: %s 부터", histmark.mark_hist_dirty(t_min))
            except Exception as e:   # noqa: BLE001 [optional]
                calcguard.swallowed("core_fills:FillsMixin._consume_order_trades", e)
                log.warning("장기 곡선 다시 계산 표식 실패: %s", e)
        log.info("[ex] 업비트 옛 주문 체결 목록 채우기: 원본 개정 %d (시각 재기장 %d) · 건너뜀 %d %s", n_ok, n_moved, n_skip,
                 json.dumps(why_n, ensure_ascii=False) if why_n else "")
        return {"ok": n_ok, "moved": n_moved, "skip": n_skip, "why": why_n}

    EXF_RETIME_EX = ("bithumb",)

    def _consume_exf_retime(self, rec: dict):
        if not hasattr(self.px, "nb_begin"):
            return self._consume_exf_retime_cached(rec)
        self.px.nb_begin()
        try:
            return self._consume_exf_retime_cached(rec)
        finally:
            pend = self.px.nb_end()
            if pend:
                try:
                    q = self.__dict__.get("_exf_retime_pxq")
                    if q is None:
                        q = self._exf_retime_pxq = pricing.FxWarmQueue(self.px, name="tj-retime-px")
                    q.add(pend)
                    log.info("체결 시각 바로잡기: 캐시에 없는 환율·시세 %d개 = 배경에서 받는 중(원장 반영은 기다리지 않음 · 못 바로잡은 체결은 몇 분 뒤 --apply 다시)",
                             len(pend))
                except Exception as e:   # noqa: BLE001 [optional]
                    calcguard.swallowed("core_fills:FillsMixin._consume_exf_retime", e)
                    log.warning("체결 시각 바로잡기: 배경 조회 시작 실패: %s", logs.safe_err(e)[:120])

    def _consume_exf_retime_cached(self, rec: dict):
        ex = str(rec.get("exchange") or "")
        if ex not in self.EXF_RETIME_EX:
            log.warning("체결 시각 바로잡기: 받지 않는 거래소 %r — 레코드 무시", ex[:20])
            return {"ok": 0, "undo": 0, "skip": 0, "why": {}}
        ns = f"{ex}:trade"
        now = int(time.time())
        items = [it for it in (rec.get("fills") or []) if isinstance(it, dict)]
        n_ok = n_undo = n_skip = 0
        t_min = None
        why_n = {}

        def legs(fid9):
            return self.conn.execute(
                "SELECT leg_seq, asset_id, location, qty_base, leg_kind, event, event_ts, cost_usd, cost_krw FROM postings"
                " WHERE source_kind='exchange' AND source_ns=? AND source_id=?", (ns, fid9)).fetchall()

        def shape(rows):
            return sorted((int(r["leg_seq"]), int(r["asset_id"]), str(r["location"]), str(int(r["qty_base"])), str(r["leg_kind"]), str(r["event"]))
                          for r in rows)

        def skip(fid9, why, quiet=False):
            nonlocal n_skip
            n_skip += 1
            why_n[why] = why_n.get(why, 0) + 1
            if not quiet:
                log.warning("%s 체결 시각 바로잡기 건너뜀 %s: %s", ex, fid9[:24], why)
        for it in items:
            fid = str(it.get("id") or "")
            try:
                t_old, t_new = int(it.get("ts_old")), int(it.get("ts"))
            except (TypeError, ValueError):
                skip(fid, "형식")
                continue
            row = self.conn.execute("SELECT revision, payload, observed_at FROM raw_ex WHERE exchange=? AND kind='trade' AND uuid=?"
                                    " ORDER BY revision DESC LIMIT 1", (ex, fid)).fetchone() if fid.startswith(ex + ":") else None
            try:
                old = json.loads(row["payload"]) if row else None
            except (TypeError, ValueError):
                old = None
            if not isinstance(old, dict):
                skip(fid, "원본 없음")
                continue
            if isinstance(old.get("_tj_retime"), dict):
                skip(fid, "이미 바로잡음", quiet=True)
                continue
            if old.get("late") or old.get("src"):
                skip(fid, "늦은 체결·전환 표식")
                continue
            try:
                cur_ts = int(old.get("ts") or 0)
            except (TypeError, ValueError):
                cur_ts = 0
            if cur_ts != t_old:
                skip(fid, "원본 시각이 요청과 다름")
                continue
            if t_new <= t_old or t_new > (now + 300) * 1000:
                skip(fid, "새 시각 이상(옛 시각 이하·미래)")
                continue
            merged = dict(old, ts=t_new)
            merged["_tj_retime"] = {"old": t_old, "at": int(rec.get("ts") or now), "src": str(rec.get("src") or "")[:60]}
            self.conn.execute("SAVEPOINT exf_retime")
            undo = None
            self.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES (?, 'trade', ?, ?, ?, ?)",
                              (ex, fid, int(row["revision"]) + 1, json.dumps(merged, ensure_ascii=False), int(row["observed_at"])))
            olds = legs(fid)
            if olds:
                self._unpost_source("exchange", ns, fid)
                self._post_exf_fill(ex, merged)
                news = legs(fid)
                had = {int(o["leg_seq"]) for o in olds if o["cost_usd"] is not None}
                had_krw = {int(o["leg_seq"]) for o in olds if o["cost_krw"] is not None}
                if shape(news) != shape(olds) or any(int(r9["event_ts"]) != t_new // 1000 for r9 in news):
                    undo = "다시 만든 레그가 다름"
                elif any(int(r9["leg_seq"]) in had and r9["cost_usd"] is None for r9 in news):
                    undo = "새 시각 원가 USD 미확보(환율·쿼트 시세를 못 받음 — 다음 --apply 때 다시)"
                elif any(int(r9["leg_seq"]) in had_krw and r9["cost_krw"] is None for r9 in news):
                    undo = "새 시각 원가 KRW 미확보(환율을 못 받음 — 다음 --apply 때 다시)"
                else:
                    t_min = min([t for t in [t_min, t_old // 1000, t_new // 1000] if t is not None])
            if undo:
                self.conn.execute("ROLLBACK TO exf_retime")
                why_n[undo] = why_n.get(undo, 0) + 1
                n_undo += 1
                log.warning("%s 체결 %s 시각 바로잡기 되돌림(원본 개정도 취소 — 다음 적용 때 재시도): %s", ex, fid[:24], undo)
            else:
                n_ok += 1
            self.conn.execute("RELEASE exf_retime")
        if t_min is not None:
            self._inval_daily()
            try:
                log.info("장기 곡선 다시 계산 표식: %s 부터", histmark.mark_hist_dirty(t_min))
            except Exception as e:   # noqa: BLE001 [optional]
                calcguard.swallowed("core_fills:FillsMixin._consume_exf_retime_cached", e)
                log.warning("장기 곡선 다시 계산 표식 실패: %s", e)
        if n_ok or n_undo or n_skip:
            try:
                m9 = json.loads(self._meta_get(f"exf_retime:{ex}") or "{}")
            except (TypeError, ValueError):
                m9 = {}
            m9 = m9 if isinstance(m9, dict) else {}
            m9.update(n=int(m9.get("n") or 0) + n_ok, undo=int(m9.get("undo") or 0) + n_undo, skip=int(m9.get("skip") or 0) + n_skip, at=now)
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_retime:{ex}", json.dumps(m9)))
        log.info("[ex] %s 지난 체결 시각 바로잡기: 바로잡음 %d · 되돌림 %d · 건너뜀 %d %s", ex, n_ok, n_undo, n_skip,
                 json.dumps(why_n, ensure_ascii=False) if why_n else "")
        return {"ok": n_ok, "undo": n_undo, "skip": n_skip, "why": why_n}

    @staticmethod
    def _upbit_open_partial(o: dict):
        market = str(o.get("market") or "")
        if "-" not in market:
            return None
        quote, base = (s.upper() for s in market.split("-", 1))
        try:
            vol = Decimal(str(o.get("executed_volume") or "0"))
            funds = Decimal(str(o.get("executed_funds") if o.get("executed_funds") not in (None, "") else "0"))
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
        except (InvalidOperation, ValueError, TypeError):
            return None
        side = str(o.get("side") or "").lower()
        if side not in ("bid", "ask") or not (vol.is_finite() and funds.is_finite() and fee.is_finite()) or vol < 0:
            return None
        if vol == 0:
            return {}
        if side == "bid":
            return {base: vol, quote: -(funds + fee)}
        return {base: -vol, quote: funds - fee}

    @staticmethod
    def _q8(x: Decimal, up: bool) -> int:
        from decimal import ROUND_DOWN, ROUND_UP
        return int((x * (Decimal(10) ** 8)).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN))

    def _upbit_quote_fill_legs(self, o: dict):
        market = str(o.get("market") or "")
        if "-" not in market:
            return None
        quote, base = market.split("-", 1)
        quote, base = quote.upper(), base.upper()
        if not quote or not base:
            return None
        try:
            vol = Decimal(str(o.get("executed_volume") or "0"))
            funds = Decimal(str(o.get("executed_funds"))) if o.get("executed_funds") is not None \
                else Decimal(str(o.get("price") or "0")) * vol
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
        except (InvalidOperation, ValueError, TypeError):
            return None
        side = str(o.get("side") or "").lower()
        if side not in ("bid", "ask") or not (vol.is_finite() and funds.is_finite() and fee.is_finite()):
            return None
        if vol <= 0 or funds <= 0 or fee < 0:
            return None
        qv = vol * (Decimal(10) ** 8)
        if qv != qv.to_integral_value():
            return None
        ts = acct_norm.fill_ts(o) or self._iso_ts(o.get("created_at"))
        if not ts:
            return None
        if side == "ask":
            return base, quote, -int(qv), self._q8(funds - fee, up=False), ts, side
        return base, quote, int(qv), -self._q8(funds + fee, up=True), ts, side

    def _post_upbit_quote_fill(self, o: dict) -> bool:
        p = self._upbit_quote_fill_legs(o)
        if p is None:
            self._ex_skip_once("EX_FILL_SKIP", str(o.get("uuid")), f"비KRW 체결 검증 탈락 보류: {o.get('market')} {o.get('uuid')}")
            return False
        base, quote, bqb, qqb, ts, side = p
        qu = self._quote_usd(quote, ts)
        usd = float(Decimal(abs(qqb)) / (Decimal(10) ** 8) * qu) if qu is not None else None
        fx = self.px.fx_at(ts * 1000) if usd is not None else None
        krw = repr(usd * fx) if (usd is not None and fx) else None
        usd_s = repr(usd) if usd is not None else None
        n_ins = 0
        for seq, sym, qb in ((0, base, bqb), (1, quote, qqb)):
            lk, evn = ("acq", "EX_BUY") if qb > 0 else ("disp", "EX_SELL")
            aid = self._upbit_asset(sym)
            if self._post_leg('exchange', 'upbit:order', str(o['uuid']), seq, ts, aid, 'exchange:upbit', qb, usd_s, krw, lk, evn):
                n_ins += 1
        return n_ins > 0
