import json
import os
import random
import time
import re
import urllib.request
import logs, net_http, paths, statefile
import bf_engine
from evm_base import UA
from evm_synth import RpcSynthMixin
import logging

log = logging.getLogger('tj-evm')

class RpcLogDiscovery(RpcSynthMixin):

    DEGRADE_AFTER = 600
    SPAN_INIT = 2000
    SPAN_MIN = 250
    SPAN_MAX = 5000
    HEAD_TTL = 20
    EMIT_FAIL_MAX = 200
    NW_BUDGET = 45

    def __init__(self, cfg: dict, chain: str, wallets: list, writer, bs_watcher):
        cc = cfg["chains"][chain]
        self.chain = chain
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.mode = str(cc.get("rpc_log_discovery") or "shadow")
        self.chain_id = int(cc["chain_id"])
        self.conf_depth = int(cc.get("conf_depth", 12))
        self.bpd = int(cc.get("blocks_per_day", 43200))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.logs_rpcs = list(cc.get("rpc_logs") or [])
        if not self.logs_rpcs:
            raise SystemExit(f"{chain}: rpc_log_discovery 켰는데 rpc_logs 미구성")
        self.span_caps = dict(cc.get("rpc_log_span_caps") or {})
        self.logs_sleep = float(cc.get("rpc_logs_sleep_sec", 1.0))
        self.wallets = [w.lower() for w in wallets]
        self.pads = ["0x" + w[2:].rjust(64, "0") for w in self.wallets]
        self.writer = writer
        self.bs = bs_watcher
        self.cfg_rpcs = cc.get("rpcs")
        self.rpc_meta_path = paths.state(f"rpc_token_meta_{chain}.json")
        self.rpc_meta = statefile.read_json(self.rpc_meta_path, {})
        self.state_path = paths.state(f"cursor_rpc_{chain}.json")
        self.st = statefile.read_json(self.state_path, {})
        self.emitted_path = paths.state(f"emitted_rpc_{chain}.json")
        self.emitted = set(statefile.read_json(self.emitted_path, []))
        self.span = min(max(int(self.st.get("span") or self.SPAN_INIT), self.SPAN_MIN),
                        self.SPAN_MAX)
        self.ep = {}
        self.emit_fail = {}

    def _ep_state(self, url):
        return self.ep.setdefault(url, {"ok": False, "head": 0, "head_ts": 0.0,
                                        "fail_until": 0.0, "streak": 0})

    def _one(self, url: str, method: str, params: list, timeout: int = 25):
        d = bf_engine.http_json(
            url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
            headers={"User-Agent": net_http.ua_for(url, UA)}, timeout=timeout, retries=1, rpc_methods=(method,))
        if not isinstance(d, dict):
            raise RuntimeError(f"rpc-error None: 응답 형식 오류 ({type(d).__name__})")
        if "error" in d:
            err = d["error"] if isinstance(d["error"], dict) else {}
            raise RuntimeError(f"rpc-error {err.get('code')}: {str(err.get('message'))[:120]}")
        return d.get("result")

    def _trip(self, url: str, e: Exception):
        s = self._ep_state(url)
        msg = str(e)
        ratelike = ("429" in msg or "Too Many" in msg
                    or "rate limit" in msg.lower() or "-32016" in msg)
        base_wait = 30.0 if ratelike else 10.0
        s["fail_until"] = time.time() + base_wait * (1.0 + random.random())
        cap9 = re.search(r"up to a (\d+) block range", msg)
        if cap9 and int(cap9.group(1)) < self.SPAN_MIN:
            s["fail_until"] = time.time() + 6 * 3600
            if not s.get("capped"):
                s["capped"] = int(cap9.group(1))
                log.warning("%s rpclog 엔드포인트 %s: getLogs 범위 한도 %s블록 < 최소 %d — 6시간 제외(다른 엔드포인트 사용)", self.chain,
                            urllib.parse.urlsplit(url).hostname, cap9.group(1), self.SPAN_MIN)
            self._last_failed_log_ep = url
            return
        s["streak"] = 0
        self._last_failed_log_ep = url
        m = self.st.setdefault("metrics", {})
        key = "err_429" if base_wait == 30.0 else "err_ep"
        m[key] = m.get(key, 0) + 1
        log.warning("%s rpclog 엔드포인트 보류(%s): %s", self.chain,
                    urllib.parse.urlsplit(url).hostname, msg[:160])

    def _ready_ep(self, need_to: int):
        now = time.time()
        order = list(self.logs_rpcs)
        last = getattr(self, "_last_failed_log_ep", None)
        if last in order:
            start = order.index(last) + 1
            order = order[start:] + order[:start]
        for url in order:
            s = self._ep_state(url)
            if now < s["fail_until"]:
                continue
            try:
                if not s["ok"]:
                    cid = int(self._one(url, "eth_chainId", [], timeout=10), 16)
                    if cid != self.chain_id:
                        log.error("★%s rpclog %s chainId 불일치(%d≠%d) — 영구 제외★",
                                  self.chain, logs.redact_urls(url), cid, self.chain_id)
                        s["fail_until"] = now + 86400 * 365
                        continue
                    s["ok"] = True
                if now - s["head_ts"] > self.HEAD_TTL or s["head"] < need_to:
                    s["head"] = int(self._one(url, "eth_blockNumber", [], timeout=10), 16)
                    s["head_ts"] = time.time()
            except Exception as e:  # noqa: BLE001 [isolate]
                self._trip(url, e)
                continue
            if s["head"] >= need_to:
                return url
        return None

    def _chunk_logs(self, url: str, frm: int, to: int, pads: list) -> dict:
        found = {}
        for pos in (1, 2):
            topics = [self.TRANSFER_TOPIC, None, None]
            topics[pos] = pads
            rows = self._one(url, "eth_getLogs",
                             [{"fromBlock": hex(frm), "toBlock": hex(to),
                               "topics": topics}])
            if not isinstance(rows, list):
                raise RuntimeError(f"getLogs 비정상 result: {type(rows).__name__} (빈 배열 아님) — 무응답")
            if len(rows) in bf_engine.SILENT_ROW_CAPS:
                raise RuntimeError(f"getLogs {len(rows)}행 = 알려진 결과 상한 — 잘림 의심 range({frm}-{to})")
            for lg in rows:
                h = (lg.get("transactionHash") or "").lower()
                if not h:
                    continue
                try:
                    blk = int(lg.get("blockNumber"), 16)
                except (TypeError, ValueError):
                    blk = to
                found[h] = blk
            time.sleep(self.logs_sleep)
        return found

    def _on_logs_err(self, url: str, e: Exception):
        msg = str(e)
        if "rate limit" in msg.lower() or "-32016" in msg:
            self._trip(url, e)
            m = self.st.setdefault("metrics", {})
            m["err_logs"] = m.get("err_logs", 0) + 1
            return
        range_err = any(k in msg for k in ("-32005", "408", "timed out", "timeout",
                                           "too large", "range", "limit", "-32602"))
        if range_err and self.span > self.SPAN_MIN:
            self.span = max(self.SPAN_MIN, self.span // 2)
            log.info("%s rpclog span 반감 → %d (%s)", self.chain, self.span, msg[:80])
        else:
            self._trip(url, e)
        m = self.st.setdefault("metrics", {})
        m["err_logs"] = m.get("err_logs", 0) + 1

    def _bs_degraded(self) -> bool:
        ts = self.bs.cursor.get("_synced_at")
        try:
            if ts:
                self.st["bs_last_ok"] = max(float(self.st.get("bs_last_ok") or 0), float(ts))
        except (TypeError, ValueError):
            pass
        return time.time() - float(self.st.get("bs_last_ok") or 0) > self.DEGRADE_AFTER

    def _bs_min_cursor(self):
        vals = []
        for w in self.wallets:
            v = self.bs.cursor.get(w)
            if not isinstance(v, int):
                return None
            vals.append(v)
        return min(vals) if vals else None

    def _wallet_set_check(self):
        cur_set = sorted(self.wallets)
        prev = self.st.get("wallet_set")
        if prev is None or self.st.get("from_block") is None:
            self.st["wallet_set"] = cur_set
            return
        if prev == cur_set:
            return
        for w in cur_set:
            if w not in prev and ("_nw:" + w) not in self.st:
                fb = int(self.st["from_block"])
                start = max(0, fb - int(self.backfill_months * 30 * self.bpd))
                ws9 = (getattr(getattr(self, "bs", None), "wallet_since", None) or {}).get(w)
                if ws9:
                    start = min(start, max(0, fb - int((time.time() - ws9) / 86400.0 * self.bpd)))
                self.st["_nw:" + w] = {"from": start, "to": fb, "done": start - 1}
                log.info("★%s rpclog 신규 지갑 %s — 과거 구간 %d→%d 별도 백필 개시★",
                         self.chain, w[:10], start, fb)
        self.st["wallet_set"] = cur_set

    def _nw_progress(self):
        keys = [k for k in self.st if k.startswith("_nw:") and isinstance(self.st[k], dict)]
        if not keys:
            self.__dict__.pop("_nw_seen", None)
            return None
        tot = left = 0
        for k in keys:
            ck = self.st[k]
            try:
                frm, to, done = int(ck["from"]), int(ck["to"]), int(ck["done"])
            except (KeyError, TypeError, ValueError):
                continue
            tot += max(0, to - frm + 1)
            left += max(0, to - done)
        now = time.time()
        seen = self.__dict__.setdefault("_nw_seen", (now, left))
        eta = None
        if left < seen[1] and now > seen[0]:
            rate = (seen[1] - left) / (now - seen[0])
            eta = int(left / rate) if rate > 0 else None
        return {"n": len(keys), "done": tot - left, "to": tot, "pct": round((tot - left) * 100.0 / tot, 1) if tot else 100.0,
                "eta": eta}

    def _nw_walk(self):
        keys = [k for k in self.st if k.startswith("_nw:")]
        if not keys:
            return
        deadline = time.time() + self.NW_BUDGET
        for k in keys:
            w = k[4:]
            ck = self.st[k]
            pads = ["0x" + w[2:].rjust(64, "0")]
            while int(ck["done"]) < int(ck["to"]) and time.time() < deadline:
                frm = int(ck["done"]) + 1
                to = min(frm + self.span - 1, int(ck["to"]))
                url = self._ready_ep(to)
                if url is None:
                    return
                cap = int(self.span_caps.get(url) or self.SPAN_INIT)
                to = min(frm + min(self.span, cap) - 1, int(ck["to"]))
                try:
                    found = self._chunk_logs(url, frm, to, pads)
                except Exception as e:  # noqa: BLE001 [isolate]
                    self._on_logs_err(url, e)
                    continue
                self._ep_state(url)["streak"] += 1
                self._absorb(found)
                ck["done"] = to
            if int(ck["done"]) >= int(ck["to"]):
                del self.st[k]
                log.info("★%s rpclog 신규 지갑 %s 백필 완주 — 체인 커서 합류★", self.chain, w[:10])

    def _absorb(self, found: dict):
        m = self.st.setdefault("metrics", {})
        buf = self.st.setdefault("pending_emit", {})
        for h, blk in found.items():
            m["found"] = m.get("found", 0) + 1
            if h in self.emitted or h in buf:
                continue
            if h in self.bs.emitted:
                m["bs_covered"] = m.get("bs_covered", 0) + 1
                continue
            buf[h] = blk

    def _drain_buffer(self, head: int):
        m = self.st.setdefault("metrics", {})
        buf = self.st.get("pending_emit") or {}
        if not buf:
            return
        degraded = self._bs_degraded()
        bs_min = self._bs_min_cursor()
        for h in sorted(buf):
            if h in self.emitted:
                del buf[h]
                continue
            if h in self.bs.emitted:
                del buf[h]
                m["bs_covered"] = m.get("bs_covered", 0) + 1
                continue
            if h in self.bs.pending_detail and not (self.mode == "active" and degraded):
                continue
            blk = int(buf[h])
            silent = (bs_min is not None and blk <= bs_min
                      and h not in self.bs.pending_detail)
            if silent:
                m["silent_gap"] = m.get("silent_gap", 0) + 1
                log.error("★%s rpclog silent-200 실증 — blockscout 커서(%s)가 지났는데"
                          " 미방출: %s @%d★", self.chain, bs_min, h[:12], blk)
            if self.mode != "active":
                if silent:
                    lst = self.st.setdefault("rpc_only", [])
                    lst.append({"h": h, "blk": blk, "ts": int(time.time())})
                    del self.st["rpc_only"][:-200]
                    del buf[h]
                continue
            if not (degraded or silent):
                continue
            try:
                snap = self._rpc_synth_detail(h)
            except Exception as e:  # noqa: BLE001 [isolate]
                if self.synth_fail_count(self.emit_fail, h, e) is None:
                    log.debug("%s rpclog %s 합성 보류(게이트·장부 거절): %s", self.chain, h[:12], str(e)[:120])
                    continue
                if self.emit_fail[h] > self.EMIT_FAIL_MAX:
                    statefile.append_durable_jsonl(
                        paths.state("pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain, "txhash": h,
                         "src": "rpc_log", "err": logs.safe_err(e)[:200]})
                    del buf[h]
                    self.emit_fail.pop(h, None)
                    log.error("★%s rpclog %s 합성 %d회 초과 — 포이즌 격리★",
                              self.chain, h[:12], self.EMIT_FAIL_MAX)
                else:
                    log.warning("%s rpclog %s 합성 실패(%d회): %s",
                                self.chain, h[:12], self.emit_fail[h], e)
                continue
            rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("%s rpclog inbox append 실패(버퍼 유지): %s", self.chain, e)
                break
            self.emitted.add(h)
            self.emit_fail.pop(h, None)
            del buf[h]
            m["emitted"] = m.get("emitted", 0) + 1
            log.info("★%s rpclog 저하 방출 %s @%d (silent=%s)★", self.chain, h[:12], blk, silent)

    def cycle(self):
        url0 = self._ready_ep(1)
        if url0 is None:
            self.st.pop("rpc_synced_at", None)
            statefile.atomic_write_json(self.state_path, self.st)
            n9 = bf_engine.health("evm").fail(f"{self.chain}:rpclog", RuntimeError("가용 엔드포인트 없음"), "rpclog",
                                              cursor=self.st.get("from_block"))
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("%s rpclog 가용 엔드포인트 없음 %d회 연속 — 다음 주기", self.chain, n9)
            return
        head = self._ep_state(url0)["head"]
        safe = head - self.conf_depth
        self._wallet_set_check()
        if self.st.get("from_block") is None:
            bs_curs = [int(self.bs.cursor[w]) for w in self.wallets
                       if isinstance(self.bs.cursor.get(w), int)]
            if bs_curs and len(bs_curs) == len(self.wallets):
                self.st["from_block"] = min(bs_curs)
            else:
                self.st["from_block"] = max(0, safe - int(self.backfill_months * 30 * self.bpd))
            log.info("★%s rpclog 커서 초기화 → %d (safe %d)★",
                     self.chain, self.st["from_block"], safe)
            statefile.atomic_write_json(self.state_path, self.st)
        self._nw_walk()
        cur = int(self.st["from_block"])
        complete = True
        if cur < safe:
            budget = 40 if (safe - cur) <= 3 * self.span else 120
            deadline = time.time() + budget
            while cur < safe:
                if time.time() >= deadline:
                    complete = False
                    break
                url = self._ready_ep(min(cur + self.SPAN_MIN, safe))
                if url is None:
                    complete = False
                    break
                cap = int(self.span_caps.get(url) or self.SPAN_INIT)
                eff_head = self._ep_state(url)["head"]
                to = min(cur + min(self.span, cap), safe, eff_head)
                if to <= cur:
                    complete = False
                    break
                try:
                    found = self._chunk_logs(url, cur + 1, to, self.pads)
                except Exception as e:  # noqa: BLE001 [isolate]
                    self._on_logs_err(url, e)
                    continue
                s = self._ep_state(url)
                s["streak"] += 1
                if s["streak"] % 5 == 0:
                    self.span = min(self.SPAN_MAX, int(self.span * 1.25))
                self._absorb(found)
                cur = to
                self.st["from_block"] = cur
        self._drain_buffer(head)
        m = self.st.setdefault("metrics", {})
        m["cycles"] = m.get("cycles", 0) + 1
        cursor_ok = complete
        nw9 = self._nw_progress()
        if any(k.startswith("_nw:") for k in self.st):
            complete = False
        if complete:
            self.st["rpc_synced_at"] = int(time.time())
        else:
            self.st.pop("rpc_synced_at", None)
        self.st["mode"] = self.mode
        self.st["span"] = self.span
        bs_min = self._bs_min_cursor()
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        statefile.atomic_write_json(self.state_path, self.st)
        eps9 = {urllib.parse.urlsplit(u).hostname: {"head": st9.get("head"), "open": st9.get("fail_until", 0) > time.time()}
                for u, st9 in self.ep.items()}
        (bf_engine.health("evm").ok if cursor_ok else bf_engine.health("evm").fail)(
            f"{self.chain}:rpclog", *(() if cursor_ok else (RuntimeError("부분 진행(예산·노드)"),)), kind="rpclog",
            head=head, cursor=cur, lag_blocks=safe - cur, buf=len(self.st.get("pending_emit") or {}),
            mode=self.mode, degraded=self._bs_degraded(), span=self.span,
            current_source=urllib.parse.urlsplit(url0).hostname, endpoints=eps9,
            silent_gap=m.get("silent_gap", 0), err_429=m.get("err_429", 0), nw=nw9)
        sig9 = (self.mode, bool(self._bs_degraded()), bool(nw9), cursor_ok)
        if m.get("found", 0) != getattr(self, "_log_found", None) or m["cycles"] % 10 == 0 \
                or sig9 != getattr(self, "_log_sig", None):
            self._log_found, self._log_sig = m.get("found", 0), sig9
            log.info("%s rpclog cycle: cursor→%d lag=%d buf=%d bs_lag=%s mode=%s degraded=%s "
                     "span=%d found=%d emitted=%d bs_covered=%d silent=%d err429=%d%s",
                     self.chain, cur, safe - cur, len(self.st.get("pending_emit") or {}),
                     (safe - bs_min) if bs_min is not None else "?", self.mode,
                     self._bs_degraded(), self.span, m.get("found", 0), m.get("emitted", 0),
                     m.get("bs_covered", 0), m.get("silent_gap", 0), m.get("err_429", 0),
                     f" nw={nw9['pct']}%" if nw9 else "")
