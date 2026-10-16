import bf_engine
import common
import time
from evm_base import BisectBudget
from evm_base import HoldError
from evm_base import StateUnavailable
import logging

log = logging.getLogger('tj-evm')


class RpcNativeMixin:

    NATIVE_LOG_MAX = 50

    MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"

    @staticmethod
    def _implied(snaps, w: str):
        own, nat = 0, 0
        for s in snaps:
            tx = s.get("tx") or {}
            fr, to = (tx.get("from") or "").lower(), (tx.get("to") or "").lower()
            if fr == w:
                own += 1
                nat -= int((tx.get("fee") or {}).get("value") or 0)
                if tx.get("type") == 126:
                    try:
                        nat += int(tx.get("op_mint") if tx.get("op_mint") is not None else (tx.get("value") or 0))
                    except (TypeError, ValueError):
                        pass
            if tx.get("status") != "ok":
                continue
            v = int(tx.get("value") or 0)
            if fr == w:
                nat -= v
            if to == w:
                nat += v
            for it in s.get("internal") or []:
                if it.get("success") is False or it.get("error"):
                    continue
                v2 = int(it.get("value") or 0)
                if (it.get("from") or "").lower() == w:
                    nat -= v2
                if (it.get("to") or "").lower() == w:
                    nat += v2
        return own, nat

    @staticmethod
    def _touches(s, w: str) -> bool:
        tx = s.get("tx") or {}
        if w in ((tx.get("from") or "").lower(), (tx.get("to") or "").lower()):
            return True
        return any(w in ((r.get("from") or "").lower(), (r.get("to") or "").lower())
                   for r in (s.get("token_transfers") or []) + (s.get("internal") or []))

    def _scan_blocks(self, lo: int, hi: int, w: str, deadline: float, reverse: bool = False, stop_nonces=None) -> tuple:
        found = {}
        want = stop_nonces
        b, top = (lo, hi)
        while b <= top:
            if want is not None and not want:
                return found, True
            if time.time() > deadline:
                return found, False
            if reverse:
                e, b0 = top, max(b, top - self.block_batch + 1)
                rng = (b0, e)
            else:
                rng = (b, min(top, b + self.block_batch - 1))
            calls = [("eth_getBlockByNumber", [hex(x), True]) for x in range(rng[0], rng[1] + 1)]
            for k9 in range(6):
                try:
                    res = self._batch(calls)
                    break
                except Exception as e9:
                    if k9 == 5 or time.time() + 20 > deadline:
                        raise
                    log.info("%s 블록 스캔 %d-%d 일시 실패(%s) — 20초 뒤 재시도", self.chain, rng[0], rng[1], str(e9)[:60])
                    time.sleep(20)
            for x, blk in zip(range(rng[0], rng[1] + 1), res):
                if isinstance(blk, Exception) or not isinstance(blk, dict):
                    raise RuntimeError(f"블록 {x} 조회 실패: {str(blk)[:80]}")
                for t in blk.get("transactions") or []:
                    if isinstance(t, dict) and w in ((t.get("from") or "").lower(), (t.get("to") or "").lower()):
                        found[(t.get("hash") or "").lower()] = x
                        if want is not None and (t.get("from") or "").lower() == w:
                            want.discard(int(t.get("nonce") or "0x0", 16))
            if want is not None and not want:
                return found, True
            if reverse:
                top = rng[0] - 1
            else:
                b = rng[1] + 1
        return found, True

    def _note(self, key: str, rec: dict):
        lst = self.cursor.setdefault(key, [])
        lst.append(dict(rec, ts=int(time.time())))
        del lst[:-self.NATIVE_LOG_MAX]

    def _bisect(self, w, a, b, sa, sb, pool, deadline):
        by_blk = {}
        for s in pool:
            by_blk.setdefault(s["tx"]["block_number"], []).append(s)

        def imp(x, y):
            return self._implied([s for k, v in by_blk.items() if x < k <= y for s in v], w)
        leaves, level = [], [(a, b, sa, sb)]
        while level:
            bad = []
            for (x, y, s1, s2) in level:
                o9, n9 = imp(x, y)
                if (s2[0] - s1[0], s2[1] - s1[1]) != (o9, n9):
                    bad.append((x, y, s1, s2))
            nxt = []
            mids = [((x + y) // 2) for (x, y, _s1, _s2) in bad if y - x > 1]
            memo9 = self.__dict__.setdefault("_st_memo", {})
            need9 = [m for m in mids if (w, m) not in memo9]
            if need9 and time.time() > deadline:
                raise BisectBudget("이분 탐색 예산 소진")
            st = self._states([(w, m) for m in mids]) if mids else {}
            if need9:
                self._bis_prog = int(self.__dict__.get("_bis_prog") or 0) + len(need9)
            for (x, y, s1, s2) in bad:
                if y - x <= 1:
                    leaves.append((x, y, s1, s2))
                    continue
                m = (x + y) // 2
                sm = st[(w, m)]
                nxt += [(x, m, s1, sm), (m, y, sm, s2)]
            level = nxt
        return leaves

    def _state_call(self, method: str, params: list):
        last = None
        for url in self._node_order(self.state_rpcs):
            try:
                return bf_engine.rpc_call(url, method, params, timeout=30, retries=1)
            except Exception as e:
                last = e
        raise last if last else RuntimeError("rpc 미구성")

    @staticmethod
    def _mc_encode(ws, target: str = None) -> str:
        tgt = int(target or RpcNativeMixin.MULTICALL3, 16)
        n = len(ws)
        out = ["252dba42", "%064x" % 32, "%064x" % n]
        out += ["%064x" % (32 * n + 160 * k) for k in range(n)]
        for w in ws:
            out += ["%064x" % tgt, "%064x" % 64, "%064x" % 36,
                    ("4d2301cc" + w[2:].lower().rjust(64, "0")).ljust(128, "0")]
        return "0x" + "".join(out)

    @staticmethod
    def _mc_decode(r: str, n: int, blk: int) -> list:
        b = bytes.fromhex(str(r or "0x")[2:])

        def word(o):
            if o + 32 > len(b):
                raise ValueError("multicall 응답 길이 부족")
            return int.from_bytes(b[o:o + 32], "big")
        if blk is not None and word(0) != int(blk):
            raise ValueError(f"multicall 블록 {word(0)} ≠ 요청 {blk}")
        arr = word(32)
        if word(arr) != n:
            raise ValueError("multicall 개수 불일치")
        base, out = arr + 32, []
        for k in range(n):
            o = base + word(base + 32 * k)
            if word(o) != 32:
                raise ValueError("multicall 항목 길이 ≠ 32")
            out.append(word(o + 32))
        return out

    @staticmethod
    def _rate_err(e) -> bool:
        return isinstance(e, bf_engine.NetError) and getattr(e, "kind", None) in ("http429", "quota", "budget", "circuit")

    def _mc_balances(self, ws, blk: int) -> int:
        bm9 = self.__dict__.setdefault("_bal_memo", {})
        sm9 = self.__dict__.setdefault("_st_memo", {})
        ws = [w for w in dict.fromkeys(ws) if (w, blk) not in sm9]
        if not self.multicall or not ws:
            return 0
        n9 = 0
        for i in range(0, len(ws), 150):
            part = ws[i:i + 150]
            try:
                r = self._state_call("eth_call", [{"to": self.multicall, "data": self._mc_encode(part, self.multicall)}, hex(int(blk))])
                bals = self._mc_decode(r, len(part), None if getattr(self, "mc_l1_block", False) else blk)
            except Exception as e:
                if (isinstance(e, ValueError) and "multicall 블록" not in str(e)) or bf_engine.revert_like(e):
                    log.warning("%s Multicall3 묶음 안 됨(%s) — 지갑별 nonce·잔고 조회로(config chains.%s.multicall3 로 주소 지정 가능)", self.chain,
                                common.safe_err(e)[:80], self.chain)
                    self.multicall = None
                elif self._rate_err(e):
                    self._mc_rate = e
                    log.info("%s Multicall3 잔고 묶음 한도 거절(다음 사이클): %s", self.chain, common.safe_err(e)[:100])
                else:
                    log.info("%s Multicall3 잔고 묶음 일시 실패(지갑별 조회로): %s", self.chain, common.safe_err(e)[:100])
                return n9
            try:
                nres = self._batch([("eth_getTransactionCount", [w, hex(int(blk))]) for w in part], self.state_rpcs)
            except Exception as e:
                nres = [e] * len(part)
            rl9 = next((x for x in nres if self._rate_err(x)), None)
            if rl9 is not None:
                self._mc_rate = rl9
            for w, v, nn in zip(part, bals, nres):
                bm9[(w, int(blk))] = int(v)
                if isinstance(nn, str):
                    try:
                        sm9[(w, int(blk))] = (int(nn, 16), int(v))
                        n9 += 1
                    except ValueError:
                        pass
        if len(bm9) > 50000:
            bm9.clear()
        return n9

    def _leaf_trace(self, w: str, y: int, pool: list, got) -> tuple:
        n_tr, added, failed = 0, [], False
        fail_h = set()
        for s9 in [s for s in pool if s["tx"]["block_number"] == y]:
            if s9["tx"].get("status") == "ok" and s9.get("internal_note") not in ("trace", "balance_delta"):
                try:
                    self._trace_internal(s9["tx"]["hash"].lower(), s9)
                    n_tr += 1
                    if s9["tx"]["hash"].lower() in self.emitted and s9.get("internal"):
                        self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
                except Exception as e:
                    if not self._trace_gone(e):
                        fail_h.add(s9["tx"]["hash"].lower())
                    log.info("%s 잎 블록 %d trace 실패: %s", self.chain, y, common.safe_err(e)[:80])
        if self.block_trace:
            unres9 = []
            try:
                frames, unres9 = self._trace_block(y)
                if unres9:
                    failed = True
                for s9 in [s for s in pool if s["tx"]["block_number"] == y and s["tx"]["hash"].lower() in fail_h]:
                    h9 = s9["tx"]["hash"].lower()
                    if h9 in unres9:
                        continue
                    s9["internal"] = list(frames.get(h9) or [])
                    s9["internal_note"] = "trace"
                    fail_h.discard(h9)
                    n_tr += 1
                    if h9 in self.emitted and s9["internal"]:
                        self.__dict__.setdefault("_reemit", set()).add(h9)
            except Exception as e:
                frames = {}
                failed = failed or not self._trace_gone(e)
                log.info("%s 잎 블록 %d 블록 trace 실패: %s", self.chain, y, common.safe_err(e)[:80])
            pool_h = {s["tx"]["hash"].lower() for s in pool}
            q9 = bf_engine.quarantine_map(self.cursor)
            cand = [h for h, rows in frames.items() if h not in pool_h and h not in q9 and h not in got
                    and any((r.get("to") or "").lower() == w and r.get("success") is not False for r in rows)]
            if cand:
                dets = self._details(cand, trace=False)
                bad9 = [h for h in cand if not isinstance(dets.get(h), dict)]
                self._detail_fail_clear([h for h in cand if isinstance(dets.get(h), dict)])
                if bad9 and self._detail_fail_note(bad9, dets, blocks={h: y for h in bad9}):
                    failed = True
                for h in cand:
                    s9 = dets.get(h)
                    if isinstance(s9, dict) and int(s9["tx"]["block_number"]) == int(y):
                        s9["internal"] = frames[h]
                        s9["internal_note"] = "trace"
                        pool.append(s9)
                        added.append(h)
                        if h in self.emitted:
                            self.__dict__.setdefault("_reemit", set()).add(h)
        failed = failed or bool(fail_h)
        rec = {"kind": "internal_traced", "w": w[:10], "blk": y, "traced": n_tr, "added": [h[:14] for h in added]} if (n_tr or added) else None
        return rec, failed

    STATE_LAG_N = 10

    STATE_LAG_SEC = 1800

    STATE_LAG_OFF_SEC = 21600

    @staticmethod
    def _st_lag_map(v) -> dict:
        return dict(v) if isinstance(v, dict) and all(isinstance(x, dict) for x in v.values()) else {}

    def _state_lag_hold(self, nk: str, blk: int, head, last: int = None, c: int = None) -> None:
        sl = self._st_lag_map(self.cursor.get("_st_lag"))
        now = int(time.time())
        if int((sl.get("*") or {}).get("off") or 0) > now:
            return
        k9 = str(c)
        g = sl.get(k9) or {}
        held9 = bool(g)
        if nk != "_ns" or head is None or (not held9 and int(head) - int(blk) > max(64, self.STATE_LAG_NEAR * max(1, int(self.conf_depth or 0)))):
            return
        n9, t9 = int(g.get("n") or 0) + 1, int(g.get("t") or now)
        if n9 < self.STATE_LAG_N or now - t9 < self.STATE_LAG_SEC:
            sl[k9] = {"n": n9, "t": t9, "blk": int(blk), "to": None if last is None else int(last)}
            self.cursor["_st_lag"] = sl
            cur9 = common.read_json(self.cursor_path, {})
            cur9["_st_lag"] = dict(self._st_lag_map(cur9.get("_st_lag")), **{k9: sl[k9]})
            common.atomic_write_json(self.cursor_path, cur9)
            raise HoldError(f"블록 {blk} 상태 없음 — 헤드 {head} 근처라 노드 뒤처짐으로 봄({n9}회) · 커서 유지(다음 사이클 재시도)")
        sl.pop(k9, None)
        sl["*"] = {"off": now + self.STATE_LAG_OFF_SEC, "n": n9}
        self.cursor["_st_lag"] = sl
        self._note("_native_notes", {"kind": "state_lag_giveup", "blk": int(blk), "n": n9})
        log.warning("%s 라이브 꼬리 상태 없음 %d회·%d분 — 종전 누적으로 넘김(%d시간 쉼 · 남는 차이는 _native_gaps → 대사 흡수)", self.chain, n9,
                    (now - t9) // 60, self.STATE_LAG_OFF_SEC // 3600)

    def _explorer_era(self, w: str, blk: int, nk: str) -> bool:
        ho = self.cursor.get("_handover")
        if isinstance(ho, dict) and ho.get("from") == "explorer":
            if nk == "_bkns":
                return True
            cs = ho.get("curs")
            cv = cs.get(w) if isinstance(cs, dict) else ho.get("src_max")
        else:
            cs = self.cursor.get("_xcurs")
            cv = cs.get(w) if isinstance(cs, dict) else None
        return isinstance(cv, int) and int(blk) <= cv

    def _sell_pick(self, cands: list, w: str, rb: int) -> tuple:
        def no_back(s):
            tx = s.get("tx") or {}
            inp = str(tx.get("raw_input") or "0x").lower()
            return (tx.get("from") or "").lower() == w and (tx.get("to") or "").lower() != w and (inp == "0x" or inp[:10] in self.TRACE_SKIP_SELECTORS)
        c2 = [s for s in cands if not no_back(s)]
        if len(c2) == 1:
            return c2, None
        hd9 = self.__dict__.get("_sell_wd") or {}
        hit = []
        for s in c2 or cands:
            hn = hd9.get(str((s.get("tx") or {}).get("hash") or "").lower())
            if hn and hn[0] == w and int(hn[2]) == int(rb):
                hit.append((s, hn[1]))
        if len(hit) == 1:
            return [hit[0][0]], hit[0][1]
        return cands, None

    def _sell_fill(self, pool: list, w: str, diff: int, nk: str) -> int:
        hd9 = self.__dict__.get("_sell_wd") or {}
        got = []
        for s in pool:
            tx = s.get("tx") or {}
            h9 = str(tx.get("hash") or "").lower()
            hn = hd9.get(h9)
            if not hn or hn[0] != w or tx.get("status") != "ok":
                continue
            if any((it.get("to") or "").lower() == w for it in s.get("internal") or []):
                continue
            if self._explorer_era(w, int(tx.get("block_number") or 0), nk):
                continue
            got.append((s, hn))
        if not got or sum(int(hn[2]) for _s, hn in got) != int(diff):
            return 0
        for s9, hn in got:
            s9.setdefault("internal", []).append({"from": hn[1], "to": w, "value": str(int(hn[2])), "success": True, "attr": "balance_delta"})
            s9["internal_note"] = "balance_delta"
            if s9["tx"]["hash"].lower() in self.emitted:
                self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
        return len(got)

    def _native(self, w: str, c: int, last: int, pool: list, deadline: float, nk: str = "_ns", head: int = None) -> dict:
        ns = (self.cursor.get(nk) or {}).get(w)
        own_i, nat_i = self._implied([s for s in pool if self._touches(s, w)], w)
        try:
            sl = self._states([(w, last)])[(w, last)]
        except StateUnavailable as e:
            if ns is None:
                return {"ns": None}
            self._state_lag_hold(nk, getattr(e, "blk", last), head, last, c)
            return {"ns": [ns[0], ns[1], ns[2], int(ns[3]) + own_i, str(int(ns[4]) + nat_i)]}
        if ns is None:
            self._note("_native_notes", {"w": w[:10], "kind": "baseline", "blk": last})
            return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        n0, b0 = int(ns[1]), int(ns[2])
        dn, db = sl[0] - n0, sl[1] - b0
        eo, en = int(ns[3]) + own_i, int(ns[4]) + nat_i
        if (dn, db) == (eo, en):
            return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        recs = []
        if int(ns[0]) == c:
            try:
                leaves = self._bisect(w, c, last, (n0, b0), sl, pool, deadline)
            except StateUnavailable as e:
                if nk == "_peek_ns":
                    raise
                self._state_lag_hold(nk, getattr(e, "blk", last), head, last, c)
                leaves = None
            if leaves is not None:
                ldl9 = max(deadline, time.time() + 60)
                pre9 = self._leaf_prefetch(w, leaves, pool, ldl9, deadline) if len(leaves) > 1 else ({}, {})
                for (x, y, s1, s2) in leaves:
                    with self._rpc_budget(ldl9):
                        got, done9 = (pre9[0][int(y)], True) if int(y) in pre9[0] else self._scan_blocks(y, y, w, ldl9)
                    if not done9:
                        raise RuntimeError(f"잎 블록 {y} 스캔 미완 — 다음 사이클 재시도")
                    q9 = bf_engine.quarantine_map(self.cursor)
                    new = [h for h in got if h not in {s["tx"]["hash"].lower() for s in pool} and h not in q9]
                    if new:
                        dets = {h9: pre9[1][h9] for h9 in new if h9 in pre9[1]}
                        if len(dets) < len(new):
                            with self._trace_budget(deadline):
                                dets.update(self._details([h9 for h9 in new if h9 not in dets], deadline=ldl9))
                        bad = [h for h in new if not isinstance(dets.get(h), dict) and not (h in self.emitted and dets.get(h) is None)]
                        self._detail_fail_clear([h for h in new if isinstance(dets.get(h), dict)])
                        left9 = self._detail_fail_note(bad, dets, blocks={h: y for h in bad}) if bad else []
                        if left9:
                            raise RuntimeError(f"잎 블록 {y} tx 상세 실패 {left9[0][:12]}: {dets.get(left9[0])}")
                        pool.extend(dets[h] for h in new if isinstance(dets.get(h), dict))
                        for h9 in new:
                            s8 = dets.get(h9)
                            if h9 in self.emitted and isinstance(s8, dict) and s8.get("internal_note") == "trace" and s8.get("internal"):
                                self.__dict__.setdefault("_reemit", set()).add(h9)
                            elif h9 in self.emitted and isinstance(s8, dict) and s8.get("internal_note") != "trace":
                                self._trace_later_mark(h9, s8)
                    here = [s for s in pool if s["tx"]["block_number"] == y and self._touches(s, w)]
                    o9, n9 = self._implied(here, w)
                    rn, rb = (s2[0] - s1[0]) - o9, (s2[1] - s1[1]) - n9
                    if rn == 0 and rb > 0 and self.trace_rpcs:
                        dfr9 = False
                        if nk == "_bkns" and (time.time() > deadline or self._trace_sick() or f"{w[:12]}:{int(y)}" in (self.cursor.get("_leaf_later") or {})):
                            rec9, fail9 = None, True
                        elif nk in ("_ns", "_peek_ns") and (time.time() > deadline or (
                                (nk == "_peek_ns" or self.__dict__.get("_late_ctx"))
                                and (self._trace_sick() or f"{w[:12]}:{int(y)}" in (self.cursor.get("_leaf_later") or {})))):
                            rec9, fail9 = None, True
                            dfr9 = nk == "_peek_ns" or bool(self.__dict__.get("_late_ctx"))
                        else:
                            with self._trace_budget(deadline), self._rpc_budget(ldl9):
                                rec9, fail9 = self._leaf_trace(w, y, pool, got)
                        if rec9:
                            recs.append(rec9)
                        here = [s for s in pool if s["tx"]["block_number"] == y and self._touches(s, w)]
                        o9, n9 = self._implied(here, w)
                        rn, rb = (s2[0] - s1[0]) - o9, (s2[1] - s1[1]) - n9
                        if rn == 0 and rb == 0:
                            self._leaf_retry(w, y, True, c=c, nk=nk)
                            continue
                        if fail9:
                            if dfr9:
                                self._leaf_defer(w, y)
                            else:
                                self._leaf_retry(w, y, False, c=c, nk=nk)
                            recs.append({"kind": "leaf_deferred", "w": w[:10], "blk": y, "native": str(rb)})
                            continue
                    held9 = self._held_block(y, {s["tx"]["hash"].lower() for s in pool}, got) if (rn == 0 and rb > 0) else []
                    if held9:
                        recs.append({"kind": "held", "w": w[:10], "blk": y, "native": str(rb), "txs": [h[:14] for h in held9[:5]]})
                        continue
                    if rn == 0 and rb > 0 and not self._explorer_era(w, y, nk):
                        cands = [s for s in here if s["tx"].get("status") == "ok"]
                        src9 = None
                        if len(cands) > 1:
                            cands, src9 = self._sell_pick(cands, w, rb)
                        if len(cands) == 1:
                            s9 = cands[0]
                            s9.setdefault("internal", []).append(
                                {"from": src9 or (s9["tx"].get("to") or s9["tx"].get("from") or "").lower(), "to": w,
                                 "value": str(rb), "success": True, "attr": "balance_delta"})
                            s9["internal_note"] = "balance_delta"
                            if s9["tx"]["hash"].lower() in self.emitted:
                                self.__dict__.setdefault("_reemit", set()).add(s9["tx"]["hash"].lower())
                            recs.append({"kind": "internal_attributed", "w": w[:10], "blk": y, "value": str(rb),
                                         "tx": s9["tx"]["hash"][:14]})
                            continue
                    if rn or rb:
                        recs.append(dict({"kind": "unexplained", "w": w[:10], "blk": y, "nonce": rn, "native": str(rb)},
                                         **({"era": "explorer"} if rn == 0 and rb > 0 and self._explorer_era(w, y, nk) else {})))
                for r in recs:
                    self._note("_native_notes", r)
                    getattr(log, "warning" if r["kind"] in ("unexplained", "held") else "info")(
                        "%s 네이티브 %s: %s", self.chain, r["kind"], r)
                return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}
        pool_own = sorted((self._txmeta[s["tx"]["hash"].lower()]["nonce"], s["tx"]["block_number"])
                          for s in pool if (s["tx"].get("from") or "").lower() == w
                          and s["tx"]["hash"].lower() in self._txmeta)
        known = {int(n): int(bk) for n, bk in ((self.cursor.get("_nonces") or {}).get(w) or {}).items()}
        known.update(pool_own)
        ranges = {}
        start = int(ns[0])
        for j in range(n0, sl[0]):
            if j in known:
                continue
            lower = [bk for n, bk in known.items() if n < j]
            upper = [bk for n, bk in known.items() if n > j]
            lo = max(lower) if lower else start + 1
            hi = min(upper) if upper else last
            ranges.setdefault((lo, hi, bool(lower), bool(upper)), []).append(j)
        added = 0
        gdl = max(deadline, time.time() + self.gap_budget)
        for (lo, hi, has_lo, has_hi), js in sorted(ranges.items()):
            wins = [(lo, hi, False)]
            stop = None
            if hi - lo + 1 > self.gap_scan_max:
                M = self.gap_scan_max
                stop = set(js)
                if has_hi and not has_lo:
                    wins = [(hi - M + 1, hi, True)]
                elif has_lo and not has_hi:
                    wins = [(lo, lo + M - 1, False)]
                elif has_lo and has_hi:
                    wins = [(lo, lo + M // 2 - 1, False), (hi - M // 2 + 1, hi, True)]
                else:
                    wins = []
                recs.append({"kind": "gap_window", "w": w[:10], "from": lo, "to": hi, "nonces": js[:10],
                             "windows": wins})
            got, done = {}, True
            for (a9, b9, rev9) in wins:
                g9, d9 = self._scan_blocks(a9, b9, w, gdl, reverse=rev9, stop_nonces=stop)
                got.update(g9)
                done = done and d9
            q9 = bf_engine.quarantine_map(self.cursor)
            new = [h for h in got if h not in {s["tx"]["hash"].lower() for s in pool} and h not in self.emitted and h not in q9]
            if new:
                dets = self._details(new)
                ok9 = [dets[h] for h in new if isinstance(dets.get(h), dict)]
                bad9 = [h for h in new if not isinstance(dets.get(h), dict)]
                self._detail_fail_clear([h for h in new if isinstance(dets.get(h), dict)])
                if bad9 and self._detail_fail_note(bad9, dets, blocks=got):
                    raise RuntimeError("nonce 틈 tx 상세 실패 — 다음 사이클 재시도")
                pool.extend(ok9)
                added += len(ok9)
            if not done:
                raise RuntimeError("nonce 틈 스캔 예산 소진 — 다음 사이클 재시도")
        own2, nat2 = self._implied([s for s in pool if self._touches(s, w)], w)
        eo2, en2 = int(ns[3]) + own2, int(ns[4]) + nat2
        if (dn, db) != (eo2, en2) and dn == eo2 and db > en2:
            n9 = self._sell_fill(pool, w, db - en2, nk)
            if n9:
                own2, nat2 = self._implied([s for s in pool if self._touches(s, w)], w)
                eo2, en2 = int(ns[3]) + own2, int(ns[4]) + nat2
                recs.append({"kind": "sell_filled", "w": w[:10], "from": int(ns[0]), "to": last, "txs": n9})
        if (dn, db) != (eo2, en2):
            rec = {"kind": "gap", "w": w[:10], "from": int(ns[0]), "to": last, "nonce_missing": dn - eo2,
                   "native_diff": str(db - en2), "added": added}
            cands = [(s["tx"]["block_number"], s["tx"]["hash"]) for s in pool if (s["tx"].get("from") or "").lower() == w]
            fo = (self.cursor.get("_first_own") or {}).get(w)
            if fo:
                cands.append((int(fo[0]), fo[1]))
            first = min(cands) if cands else None
            if first is not None and self.trace_rpcs:
                try:
                    pre = self._prestate(first[1], w)
                    rec["pre_first_own"] = {"blk": first[0], "nonce": pre[0], "balance": str(pre[1])}
                except Exception as e:
                    rec["pre_first_own"] = {"err": common.safe_err(e)[:80]}
            recs.append(rec)
        elif added:
            recs.append({"kind": "gap_resolved", "w": w[:10], "from": int(ns[0]), "to": last, "added": added})
        for r in recs:
            self._note("_native_gaps" if r["kind"] == "gap" else "_native_notes", r)
            getattr(log, "warning" if r["kind"] == "gap" else "info")(
                "%s 네이티브 %s: %s", self.chain, r["kind"], r)
        return {"ns": [last, sl[0], str(sl[1]), 0, "0"]}

    def _baselines(self, ws, blk: int) -> dict:
        out = {}
        if int(blk) == 0:
            return {w: [0, 0, "0", 0, "0"] for w in ws}
        for i in range(0, len(ws), 20):
            part = ws[i:i + 20]
            try:
                st = self._states([(w, int(blk)) for w in part])
            except StateUnavailable:
                st = {}
                for w in part:
                    try:
                        st.update(self._states([(w, int(blk))]))
                    except StateUnavailable:
                        pass
            for w in part:
                if (w, int(blk)) in st:
                    n9, b9 = st[(w, int(blk))]
                    out[w] = [int(blk), n9, str(b9), 0, "0"]
        return out
