import bf_engine
import common
import hashlib
import time
from evm_base import TRACE_DEPTH_MAX
from evm_base import TraceDeferred
from evm_base import TraceStaged
from evm_base import _TraceBudget
from evm_base import _WALK_END
from evm_base import _int_or
from evm_base import trace_fail_index
from evm_base import trace_path_failed
import logging

log = logging.getLogger('tj-evm')


class RpcTraceMixin:

    TRACE_SICK_SEC = 300

    TRACE_MIN_LEFT = 1.0

    def _trace_budget(self, dl):
        return _TraceBudget(self, dl)

    def _trace_kw(self, cap: float):
        dl = self.__dict__.get("_tdl")
        if dl is None:
            return {"timeout": cap, "retries": 1}
        left = float(dl) - time.time()
        if left < self.TRACE_MIN_LEFT:
            return None
        return {"timeout": min(float(cap), left), "retries": 1, "deadline": bf_engine.time.time() + left, "sem_timeout": left}

    def _trace_sick(self) -> bool:
        return time.time() < float(self.__dict__.get("_trace_sick_until") or 0)

    @staticmethod
    def _trace_untried(e) -> bool:
        return isinstance(e, TraceDeferred) or (isinstance(e, bf_engine.NetError) and (
            getattr(e, "kind", None) in ("budget", "circuit") or bool(getattr(e, "local", False))))

    def _trace_note(self, ok: bool) -> None:
        if ok:
            self._trace_nf = 0
            if float(self.__dict__.get("_trace_sick_until") or 0):
                self._trace_sick_until = 0.0
                log.info("%s trace 노드 회복 — 늦은 채움·엿보기 trace 다시 켬", self.chain)
            return
        n9 = self._trace_nf = int(self.__dict__.get("_trace_nf") or 0) + 1
        if n9 >= self.TRACE_SICK_N:
            if not self._trace_sick():
                log.info("%s trace 노드 연속 %d회 실패 — %d초 동안 따라잡기·엿보기 trace 는 바로 늦은 채움(꼬리·보완 작업이 회복 확인)",
                         self.chain, n9, self.TRACE_SICK_SEC)
                self._trace_sick_until = time.time() + self.TRACE_SICK_SEC

    TRACE_CUT_MIN = 1.0

    def _trace_order(self) -> list:
        order9 = self._order(self.trace_rpcs)
        sl9 = self.__dict__.get("_trace_slow_until") or {}
        if not sl9 or len(order9) < 2:
            return self._sel_trace(order9)
        now = time.time()
        return self._sel_trace([u for u in order9 if float(sl9.get(u) or 0) <= now]) + [u for u in order9 if float(sl9.get(u) or 0) > now]

    def _sel_trace(self, order9) -> list:
        if len(order9) < 2:
            return order9
        try:
            import nodesel
            if not nodesel.enabled():
                return order9
            return nodesel.demote_public(self.chain, "trace", order9)
        except Exception:
            return order9

    @staticmethod
    def _trace_nid(url: str) -> str:
        return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:10]

    def _trace_pref(self, order: list, done) -> list:
        d9 = {str(x) for x in done} if isinstance(done, (list, tuple, set)) else set()
        if not d9:
            return order
        return [u for u in order if self._trace_nid(u) not in d9] + [u for u in order if self._trace_nid(u) in d9]

    def _trace_obs(self, k: str, url: str, e) -> None:
        o9 = self.__dict__.get("_trace_stage_obs")
        if isinstance(o9, dict) and isinstance(o9.get(k), set) and not self._trace_untried(e) and getattr(e, "kind", None) not in ("http429", "quota"):
            o9[k].add(self._trace_nid(url))

    def _trace_fail_one(self, url: str, e, kw: dict, cap: float):
        try:
            t9 = float((kw or {}).get("timeout") or cap)
        except (TypeError, ValueError):
            t9 = float(cap)
        if t9 < float(cap) - self.TRACE_CUT_MIN and getattr(e, "kind", None) in ("timeout", "conn") and not getattr(e, "code", None):
            return TraceDeferred(f"budget: trace 남은 시간({t9:.0f}초)이 노드 상한보다 짧아 끊김 — 다음 차례")
        if self._trace_slow(e):
            sl9 = self.__dict__.setdefault("_trace_slow_until", {})
            sl9[url] = time.time() + self.TRACE_SICK_SEC
        return e

    @staticmethod
    def _trace_slow(e) -> bool:
        m = str(e).lower()
        return getattr(e, "kind", None) == "timeout" or getattr(e, "code", None) == 408 or "timeout" in m or "timed out" in m

    def _prestate(self, h: str, w: str) -> tuple:
        last = None
        for url in self._order(self.trace_rpcs):
            try:
                r = bf_engine.rpc_call(url, "debug_traceTransaction", [h, {"tracer": "prestateTracer"}], timeout=30, retries=1)
                e = {k.lower(): v for k, v in (r or {}).items()}.get(w) or {}
                return int(e.get("nonce") or 0), int(e.get("balance") or "0x0", 16)
            except Exception as e9:
                last = e9
        raise last if last else RuntimeError("trace 미구성")

    _VALUE_OPS = ("CALL", "CREATE", "CREATE2", "SELFDESTRUCT")

    def _trace_internal(self, h: str, snap: dict):
        last = None
        errs9 = []
        tr = None
        pf9 = bool(snap.pop("_trace_parity_first", False))
        an9, ab9 = snap.pop("_alch_n", 0), snap.pop("_alch_blk", None)
        st9 = snap.pop("_trace_stg", None)
        st9 = st9 if isinstance(st9, dict) else {}
        self._trace_stage_obs = {"ct": set(), "pa": set()}
        self._trace_mixed = False
        if st9.get("alch"):
            al9 = self._alch_tx(h, snap, [TraceStaged()], an9, ab9)
            if al9 is not None:
                snap["internal"] = al9
                snap["internal_note"] = "trace"
                snap["internal_src"] = "alchemy_transfers"
                self._trace_fail.pop(h, None)
                return
        if pf9:
            rows9 = self._trace_parity(h, errs9, done=st9.get("pa"))
            if rows9 is not None:
                snap["internal"] = rows9
                snap["internal_note"] = "trace"
                self._trace_fail.pop(h, None)
                self._trace_note(True)
                return
        slow9 = set()
        for url in self._trace_pref(self._trace_nodes(errs9), st9.get("ct")):
            kw9 = self._trace_kw(30)
            if kw9 is None:
                errs9.append(TraceDeferred())
                break
            try:
                tr = bf_engine.rpc_call(url, "debug_traceTransaction", [h, {"tracer": "callTracer"}], **kw9)
                break
            except Exception as e:
                e = self._trace_fail_one(url, e, kw9, 30)
                last = e
                errs9.append(e)
                self._trace_obs("ct", url, e)
                if self._trace_slow(e):
                    slow9.add(url)
        if not isinstance(tr, dict) or not tr.get("type"):
            if tr is not None:
                errs9.append(RuntimeError("trace 응답 형식 오류"))
                self._trace_obs("ct", url, errs9[-1])
            rows9 = None if pf9 else self._trace_parity(h, errs9, skip=slow9 if self._trace_sick() else (), done=st9.get("pa"))
            if rows9 is None:
                e9 = self._trace_err(errs9, last) or RuntimeError("trace 응답 형식 오류")
                tried9 = tr is not None or any(not self._trace_untried(x) for x in errs9)
                if not tried9 and errs9:
                    raise TraceDeferred(f"budget: trace 전송 전 보류 — 다음 차례({common.safe_err(e9)[:60]})")
                try:
                    al9, ae9 = self._alch_tx(h, snap, errs9, an9, ab9), None
                except Exception as x9:
                    al9, ae9 = None, x9
                if al9 is not None:
                    snap["internal"] = al9
                    snap["internal_note"] = "trace"
                    snap["internal_src"] = "alchemy_transfers"
                    self._trace_fail.pop(h, None)
                    return
                if tried9 and not self._trace_gone(e9):
                    self._trace_note(False)
                self._trace_mixed = any(self._trace_untried(x) for x in errs9)
                raise ae9 if ae9 is not None else e9
            snap["internal"] = rows9
            snap["internal_note"] = "trace"
            self._trace_fail.pop(h, None)
            self._trace_note(True)
            return
        myset = set(self.wallets)
        out = []

        def walk(fr, failed):
            st9 = [(iter(fr.get("calls") or []), failed)]
            while st9:
                ch = next(st9[-1][0], _WALK_END)
                if ch is _WALK_END:
                    st9.pop()
                    continue
                bad = st9[-1][1] or bool(ch.get("error"))
                try:
                    v = int(ch.get("value") or "0x0", 16)
                except (TypeError, ValueError):
                    v = 0
                f9, t9 = (ch.get("from") or "").lower(), (ch.get("to") or "").lower()
                if v and str(ch.get("type") or "").upper() in self._VALUE_OPS and (f9 in myset or t9 in myset):
                    out.append({"from": f9, "to": t9, "value": str(v), "success": not bad})
                st9.append((iter(ch.get("calls") or []), bad))
        walk(tr, bool(tr.get("error")))
        snap["internal"] = out
        snap["internal_note"] = "trace"
        self._trace_fail.pop(h, None)
        self._trace_note(True)

    def _trace_parity(self, h: str, errs: list = None, skip=(), done=()):
        res = None
        got9 = False
        for url in self._trace_pref(self._trace_order(), done):
            if url in skip:
                continue
            kw9 = self._trace_kw(30)
            if kw9 is None:
                if errs is not None:
                    errs.append(TraceDeferred())
                break
            try:
                res = bf_engine.rpc_call(url, "trace_transaction", [h], **kw9)
                got9 = True
                break
            except Exception as e:
                e = self._trace_fail_one(url, e, kw9, 30)
                if errs is not None:
                    errs.append(e)
                self._trace_obs("pa", url, e)
                continue
        if not isinstance(res, list):
            if got9 and errs is not None:
                errs.append(RuntimeError("trace_transaction 응답 형식 오류"))
            if got9:
                self._trace_obs("pa", url, RuntimeError("trace_transaction 응답 형식 오류"))
            return None
        myset = set(self.wallets)
        try:
            bad = trace_fail_index(res)
        except (TypeError, ValueError):
            if errs is not None:
                errs.append(RuntimeError("trace_transaction 응답 형식 오류"))
            return None
        out = []
        for t in res:
            if not isinstance(t, dict):
                if errs is not None:
                    errs.append(RuntimeError("trace_transaction 응답 형식 오류"))
                return None
            ta = tuple(t.get("traceAddress") or [])
            if not ta:
                continue
            ac = t.get("action") or {}
            typ = str(t.get("type") or "").lower()
            if typ == "call":
                if str(ac.get("callType") or "call").lower() != "call":
                    continue
                f9, t9, v9 = ac.get("from"), ac.get("to"), ac.get("value")
            elif typ == "create":
                f9, t9, v9 = ac.get("from"), (t.get("result") or {}).get("address"), ac.get("value")
            elif typ in ("suicide", "selfdestruct"):
                f9, t9, v9 = ac.get("address"), ac.get("refundAddress"), ac.get("balance")
            else:
                continue
            try:
                v = int(v9 or "0x0", 16)
            except (TypeError, ValueError):
                if errs is not None:
                    errs.append(RuntimeError("trace_transaction 응답 형식 오류"))
                return None
            f9, t9 = str(f9 or "").lower(), str(t9 or "").lower()
            if v and (f9 in myset or t9 in myset):
                try:
                    if len(ta) > TRACE_DEPTH_MAX:
                        raise ValueError("traceAddress 깊이 상한 초과")
                    failed = trace_path_failed(bad, ta)
                except (TypeError, ValueError):
                    if errs is not None:
                        errs.append(RuntimeError("trace_transaction 응답 형식 오류"))
                    return None
                out.append({"from": f9, "to": t9, "value": str(v), "success": not failed})
        return out

    def _trace_block(self, blk: int) -> tuple:
        last = None
        errs9 = []
        res = None
        got9 = False
        sent9 = 0
        an9 = self.__dict__.pop("_alch_ctx_n", 0)
        lc9 = self.__dict__.pop("_leaf_ctx_stg", None)
        rc9 = isinstance(lc9, dict) and bool(lc9.get("alch")) and bool(lc9.get("rc"))
        if isinstance(lc9, dict) and lc9.get("alch") and not rc9:
            a9 = int(self.__dict__.get("_alch_sent") or 0)
            try:
                fr9 = self._alch_frames(blk, [TraceStaged()], an9)
            except Exception as x9:
                if int(self.__dict__.get("_alch_sent") or 0) > a9 and getattr(x9, "kind", None) not in ("budget", "receipt"):
                    lc9["rc_next"] = True
                raise
            if fr9 is not None:
                return fr9, []
        nodes9 = self._trace_nodes(errs9)
        if isinstance(lc9, dict):
            nodes9 = self._trace_pref(nodes9, lc9.get("tb"))
            if rc9 and nodes9:
                nodes9 = [sorted(nodes9, key=self._trace_nid)[int(lc9.get("ri") or 0) % len(nodes9)]]
        for url in nodes9:
            kw9 = self._trace_kw(60)
            if kw9 is None:
                errs9.append(TraceDeferred())
                break
            try:
                res = bf_engine.rpc_call(url, "debug_traceBlockByNumber", [hex(int(blk)), {"tracer": "callTracer"}], **kw9)
                sent9 += 1
                got9 = True
                break
            except Exception as e:
                e = self._trace_fail_one(url, e, kw9, 60)
                last = e
                errs9.append(e)
                if not self._trace_untried(e):
                    sent9 += 1
                    if isinstance(lc9, dict) and getattr(e, "kind", None) not in ("http429", "quota"):
                        lc9.setdefault("obs", set()).add(self._trace_nid(url))
        if rc9 and sent9:
            lc9["rc_used"] = True
        if not isinstance(res, list):
            if got9:
                errs9.append(RuntimeError("블록 trace 응답 형식 오류"))
                if isinstance(lc9, dict):
                    lc9.setdefault("obs", set()).add(self._trace_nid(url))
            if not sent9 and errs9 and all(self._trace_untried(x) for x in errs9):
                raise TraceDeferred(f"budget: 블록 trace 전송 전 보류 — 다음 차례({common.safe_err(errs9[-1])[:60]})")
            e9 = self._trace_err(errs9, last) or RuntimeError("블록 trace 응답 형식 오류")
            try:
                fr9, ae9 = self._alch_frames(blk, errs9, an9), None
            except Exception as x9:
                fr9, ae9 = None, x9
            if fr9 is not None:
                return fr9, []
            if rc9 and ae9 is None and self._trace_gone(e9) and len({self._trace_nid(u) for u in self.trace_rpcs}) > 1:
                lc9["rc_next"] = True
                e9 = RuntimeError("block trace recheck incomplete; another provider remains unverified")
            if sent9 and not self._trace_gone(e9):
                self._trace_note(False)
            raise ae9 if ae9 is not None else e9
        self._trace_note(True)
        myset = set(self.wallets)
        out, unres, nfb9 = {}, [], 0
        hs9 = None
        if not res or any(not (isinstance(it, dict) and it.get("txHash")) for it in res):
            try:
                hs9 = [str(x if isinstance(x, str) else (x or {}).get("hash") or "").lower()
                       for x in (self._rpc_call("eth_getBlockByNumber", [hex(int(blk)), False]) or {}).get("transactions") or []]
            except Exception as e:
                raise RuntimeError(f"블록 trace 항목 txHash 없음 — 블록 tx 목록 실패: {common.safe_err(e)[:80]}")
            if len(hs9) != len(res) or not all(hs9):
                raise RuntimeError(f"블록 trace 항목 txHash 없음 — 개수 불일치 {len(res)} ≠ {len(hs9)}")
        for k9, it in enumerate(res):
            h9 = str((it.get("txHash") if isinstance(it, dict) else None) or (hs9[k9] if hs9 else "")).lower()
            r9 = it.get("result") if isinstance(it, dict) else None
            if (isinstance(it, dict) and it.get("error")) or not isinstance(r9, dict) or not r9.get("type"):
                tmp9 = {}
                if nfb9 >= self.BTRACE_ITEM_FALLBACK:
                    unres.append(h9)
                    continue
                nfb9 += 1
                try:
                    self._trace_internal(h9, tmp9)
                    if tmp9.get("internal"):
                        out[h9] = tmp9["internal"]
                except Exception as e:
                    unres.append(h9)
                    log.info("%s 블록 %d trace 항목 %s 실패(단건도 실패 — 재시도): %s", self.chain, blk, h9[:12], common.safe_err(e)[:80])
                continue
            rows = []

            def walk(fr, failed):
                st9 = [(iter(fr.get("calls") or []), failed)]
                while st9:
                    ch = next(st9[-1][0], _WALK_END)
                    if ch is _WALK_END:
                        st9.pop()
                        continue
                    bad = st9[-1][1] or bool(ch.get("error"))
                    try:
                        v = int(ch.get("value") or "0x0", 16)
                    except (TypeError, ValueError):
                        v = 0
                    f9, t9 = (ch.get("from") or "").lower(), (ch.get("to") or "").lower()
                    if v and str(ch.get("type") or "").upper() in self._VALUE_OPS and (f9 in myset or t9 in myset):
                        rows.append({"from": f9, "to": t9, "value": str(v), "success": not bad})
                    st9.append((iter(ch.get("calls") or []), bad))
            walk(r9, bool(r9.get("error")))
            if rows:
                out[h9] = rows
        return out, unres

    BTRACE_ITEM_FALLBACK = 5

    @staticmethod
    def _unsupported(e) -> bool:
        m = str(e).lower()
        return "-32601" in m or "does not exist" in m or "method not found" in m or "not supported" in m \
            or ("not available" in m and "method" in m)

    @classmethod
    def _trace_gone(cls, e) -> bool:
        if cls._unsupported(e):
            return True
        m = str(e).lower()
        if "historical state" in m and ("unavailable" in m or "not available" in m):
            return True
        return getattr(e, "kind", None) == "pruned" and any(k9 in m for k9 in (
            "missing trie node", "history has been pruned", "historical version not found", "failed to load state at height"))

    def _trace_nodes(self, errs: list) -> list:
        order9 = self._trace_order()
        if any(u not in order9 for u in self.trace_rpcs):
            errs.append(bf_engine.NetError("trace 노드 일부 서킷으로 미확인(다음에 다시)", "circuit"))
        return order9

    @classmethod
    def _trace_err(cls, errs: list, last=None):
        tr9 = [e for e in errs or () if not cls._trace_gone(e)]
        for e in tr9:
            if not cls._trace_untried(e):
                return e
        if tr9:
            return tr9[0]
        return last if last is not None else ((errs or [None])[-1])

    ALCH_MIN_AGE_SEC = 3600

    ALCH_OLD_DAYS = 30

    ALCH_LATE_N = 2

    ALCH_CALL_SEC = 20.0

    ALCH_MIN_SEC = 8.0

    ALCH_MEMO_SEC = 900

    ALCH_MEMO_N = 256

    def _alch_url(self):
        try:
            import alch_internal
            return alch_internal.url_for(self.chain)
        except Exception:
            return None

    def _alch_eligible(self, errs, blk, n=0) -> bool:
        try:
            blk = int(blk or 0)
            head = int(getattr(self, "_log_head", 0) or 0)
            bpd = float(getattr(self, "bpd", 0) or 43200)
        except (TypeError, ValueError):
            return False
        if blk <= 0 or head <= blk or not errs:
            return False
        age = (head - blk) * 86400.0 / max(1.0, bpd)
        if age < self.ALCH_MIN_AGE_SEC:
            return False
        for e in errs:
            if self._trace_untried(e) or getattr(e, "kind", None) in ("http429", "quota"):
                return False
        if all(self._trace_gone(e) for e in errs):
            return True
        return age >= self.ALCH_OLD_DAYS * 86400 or int(n or 0) >= self.ALCH_LATE_N

    def _alch_kw(self) -> dict:
        t9 = float(self.ALCH_CALL_SEC)
        dl = self.__dict__.get("_tdl")
        if dl is not None:
            t9 = min(t9, max(float(dl) - time.time(), float(self.ALCH_MIN_SEC)))
        return {"timeout": t9, "retries": 1, "deadline": bf_engine.time.time() + t9, "sem_timeout": t9}

    def _alch_raw(self, blk: int) -> dict:
        import alch_internal
        url = self._alch_url()
        if not url:
            raise alch_internal.AlchSkip("키 없음")
        ws = tuple(sorted(str(w).lower() for w in self.wallets))
        memo = self.__dict__.get("_alch_memo")
        if not isinstance(memo, dict) or self.__dict__.get("_alch_memo_ws") != ws:
            memo = self._alch_memo = {}
            self._alch_memo_ws = ws
        now = time.time()
        m9 = memo.get(int(blk))
        if m9 and now - m9[0] < self.ALCH_MEMO_SEC:
            return m9[1]
        try:
            trs, info = alch_internal.fetch_range(url, int(blk), int(blk), self._alch_kw())
        except alch_internal.AlchFail as x9:
            if x9.kind != "budget":
                self._alch_sent = int(self.__dict__.get("_alch_sent") or 0) + 1
            raise
        self._alch_sent = int(self.__dict__.get("_alch_sent") or 0) + 1
        rows = alch_internal.rows_for(trs, set(ws))
        memo[int(blk)] = (now, rows)
        if len(memo) > self.ALCH_MEMO_N:
            for k9 in sorted(memo, key=lambda x: memo[x][0])[:len(memo) - self.ALCH_MEMO_N]:
                memo.pop(k9, None)
        log.info("%s 블록 %d 내부 이동 — Alchemy 목록 %d건 · 내 지갑 tx %d(쪽 %d%s)", self.chain, int(blk), len(trs), len(rows), info["pages"],
                 f" · 처음부터 다시 {info['restarts']}" if info.get("restarts") else "")
        return rows

    def _alch_status(self, hashes) -> dict:
        import alch_internal
        hs = list(dict.fromkeys(hashes))
        if not hs:
            return {}
        try:
            with self._rpc_budget(time.time() + self._alch_kw()["timeout"]):
                res = self._batch([("eth_getTransactionReceipt", [h]) for h in hs])
        except Exception as e:
            if self._trace_untried(e) or "예산 소진" in str(e):
                raise TraceDeferred("budget: Alchemy 보완 영수증 — 마감(다음 차례)")
            raise alch_internal.AlchFail("receipt", common.safe_err(e)[:80])
        out = {}
        for h, r in zip(hs, res):
            try:
                if not isinstance(r, dict) or r.get("status") not in ("0x0", "0x1"):
                    raise ValueError("영수증 없음·상태 없음")
                out[h] = (int(r["blockNumber"], 16), r["status"] == "0x1")
            except (KeyError, TypeError, ValueError) as e:
                raise alch_internal.AlchFail("receipt", str(e)[:60])
        return out

    def _alch_tx(self, h: str, snap: dict, errs, n=0, blk_hint=None):
        tx = snap.get("tx") if isinstance(snap.get("tx"), dict) else {}
        try:
            blk = int(tx.get("block_number") or blk_hint or 0)
        except (TypeError, ValueError):
            blk = 0
        if not self._alch_eligible(errs, blk, n) or not self._alch_url():
            return None
        import alch_internal
        if tx.get("status") in ("ok", "error") and tx.get("block_number"):
            ok9 = tx.get("status") == "ok"
        else:
            b9, ok9 = self._alch_status([h])[h]
            if b9 != blk:
                if not self._alch_eligible(errs, b9, n):
                    return None
                blk = b9
        try:
            raw = self._alch_raw(blk)
        except alch_internal.AlchSkip:
            return None
        rows = [dict(r, success=bool(ok9)) for r in raw.get(h) or []]
        self._note("_native_notes", {"kind": "alch_fill", "tx": h[:14], "blk": blk, "rows": len(rows), "src": alch_internal.SRC})
        log.info("%s trace 노드가 못 준 tx %s — Alchemy 내부 이동 목록으로 보완(내 지갑 행 %d%s)", self.chain, h[:12], len(rows), "" if ok9 else " · 실패 tx")
        return rows

    def _alch_frames(self, blk: int, errs, n=0):
        if not self._alch_eligible(errs, blk, n) or not self._alch_url():
            return None
        import alch_internal
        try:
            raw = self._alch_raw(int(blk))
        except alch_internal.AlchSkip:
            return None
        out = {}
        if raw:
            st = self._alch_status(list(raw))
            for h, rows in raw.items():
                b9, ok9 = st[h]
                if b9 != int(blk):
                    raise alch_internal.AlchFail("receipt", "블록 불일치")
                out[h] = [dict(r, success=bool(ok9)) for r in rows]
        self._note("_native_notes", {"kind": "alch_block", "blk": int(blk), "txs": len(out), "src": alch_internal.SRC})
        log.info("%s trace 노드가 못 준 블록 %d — Alchemy 내부 이동 목록으로 보완(내 지갑 tx %d)", self.chain, int(blk), len(out))
        return out

    def _trace_stg_get(self, e) -> dict:
        s9 = e.get("stg") if isinstance(e, dict) else None
        out = {"v": 1, "ct": [], "pa": [], "al": 0}
        if isinstance(s9, dict) and s9.get("v") == 1:
            for k9 in ("ct", "pa"):
                if isinstance(s9.get(k9), list):
                    out[k9] = [str(x)[:16] for x in s9[k9] if isinstance(x, str)][:16]
            out["al"] = max(0, _int_or(s9.get("al"), 0))
        return out

    def _trace_stg_put(self, e: dict, st9: dict, sent0: int) -> None:
        o9 = self.__dict__.get("_trace_stage_obs") or {}
        new = {"v": 1, "ct": sorted(set(st9["ct"]) | set(o9.get("ct") or ()))[:16], "pa": sorted(set(st9["pa"]) | set(o9.get("pa") or ()))[:16],
               "al": st9["al"] + max(0, int(self.__dict__.get("_alch_sent") or 0) - int(sent0))}
        if "stg" in e or new["ct"] or new["pa"] or new["al"]:
            e["stg"] = new
