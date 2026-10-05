"""BNB Smart Chain wallet watcher."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import bf_engine
from inbox import SegmentWriter

log = common.setup_logging("tj-bsc")

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEPOSIT_TOPIC = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
WITHDRAWAL_TOPIC = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
BLOCKS_PER_DAY = 28800
CALL_SLEEP = 0.25


_now = time.time
NONCE_EVERY = 3600
NONCE_MAX_FIND = 3
NONCE_CALL_CAP = 80


class _SentTap:

    def __init__(self, inner, owner):
        self.inner = inner
        self._owner = owner

    def append(self, rec):
        r = self.inner.append(rec)
        try:
            self._owner._nonce_note(rec)
        except Exception as e:
            log.debug("nonce 색인 기록 실패: %s", e)
        return r

    def __getattr__(self, k):
        return getattr(self.inner, k)


def _pad_topic(addr: str) -> str:
    return "0x" + addr.lower().replace("0x", "").rjust(64, "0")


class Rpc:
    def __init__(self, urls: list, rotate_each: bool = False):
        self.urls = urls
        self.i = 0
        self.rotate_each = rotate_each

    def call(self, method: str, params, timeout=25):
        last = None
        if self.rotate_each:
            self.i = (self.i + 1) % len(self.urls)
        order = [(self.i + k) % len(self.urls) for k in range(len(self.urls))]
        ready = [j for j in order if not bf_engine.gate(self.urls[j]).is_open()]
        for j in (ready or order):
            self.i = j
            url = self.urls[j]
            try:
                d = {"result": bf_engine.rpc_call(url, method, params, timeout=timeout, retries=1, allow_null=True)}
                if method == "eth_getLogs" and not isinstance(d.get("result"), list):
                    raise RuntimeError(f"getLogs 비정상 result: {type(d.get('result')).__name__}")
                if d.get("result") is None:
                    raise RuntimeError(f"{method}: result null")
                return d.get("result")
            except Exception as e:
                last = e
                self.i = (j + 1) % len(self.urls)
                time.sleep(0.2)
        raise last


    def batch(self, calls: list, timeout=30):
        last = None
        for _attempt in range(len(self.urls)):
            url = self.urls[self.i]
            try:
                res = bf_engine.rpc_batch(url, calls, timeout=timeout, retries=1)
                if res and all(isinstance(r, Exception) for r in res):
                    raise res[0]
                return res
            except Exception as e:
                last = e
                self.i = (self.i + 1) % len(self.urls)
        raise last if last else RuntimeError("batch: 노드 없음")


def _dec_string(hexdata: str) -> str | None:
    try:
        h = hexdata[2:] if hexdata.startswith("0x") else hexdata
        if not h:
            return None
        b = bytes.fromhex(h)
        if len(b) == 32:
            return b.rstrip(b"\x00").decode("utf-8", "ignore") or None
        if len(b) >= 64:
            ln = int.from_bytes(b[32:64], "big")
            return b[64:64 + ln].decode("utf-8", "ignore") or None
    except Exception:
        pass
    return None


class BscWatcher:
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        bc = cfg["bsc"]
        self.logs_rpc = Rpc(bc["logs_rpcs"], rotate_each=True)
        arch = [str(u) for u in (bc.get("archive_rpcs") or [u for u in bc.get("logs_rpcs") or [] if "nodereal" in str(u)])]
        self.rpc = Rpc(list(bc["detail_rpcs"]) + [u for u in arch if u not in bc["detail_rpcs"]])
        self.logs_sleep = float(bc.get("logs_sleep_sec", 1.2))
        self.span = int(bc.get("getlogs_span", 5000))
        self.logs_fb = {str(u): int(c) for u, c in (bc.get("logs_rpcs_fallback") or {}).items() if int(c) > 0}
        self.canary = None if bc.get("canary") is False else bf_engine.BSC_CANARY
        self.conf_depth = int(bc.get("conf_depth", 20))
        self.backfill_days = int(bc.get("backfill_days", 120))
        self.wallets = [w.lower() for w in wallets]
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get("bsc") or "").lower() or None
        self.discover_wrap = bc.get("discover_wrap") is not False and bool(self.wrapped_ca)
        self.wallet_since = bf_engine.wallet_since_map(cfg, "bsc")
        self.topics = [_pad_topic(w) for w in self.wallets]
        self.writer = _SentTap(writer, self)
        self.cursor_path = os.path.join(common.STATE_DIR, "cursor_bsc.json")
        self.cursor = common.read_json(self.cursor_path, {})
        self.meta_path = os.path.join(common.STATE_DIR, "bsc_token_meta.json")
        self.token_meta = common.read_json(self.meta_path, {})
        self.nodec = bf_engine.nodec_registry("bsc", log)
        self.emitted_path = os.path.join(common.STATE_DIR, "emitted_bsc.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        self.block_ts = {}
        self.span_caps = {str(u): int(c) for u, c in (bc.get("getlogs_span_caps") or {}).items()}
        self.scan_workers = int(bc.get("scan_workers", 1))
        self.span_max = int(bc.get("getlogs_span_max", 50000))
        self.detail_batch = max(1, int(bc.get("detail_batch", 8)))
        self.logs_head_guard = bc.get("logs_head_guard") is not False
        self.cycle_budget = float(bc.get("cycle_budget_sec", 600))
        self.progress = bf_engine.progress("bsc")
        self.last_scan_metrics = {}

    STALE_NODE_BLOCKS = 50

    def head(self) -> int:
        urls = self.rpc.urls
        heads = {}
        first = int(self.rpc.call("eth_blockNumber", []), 16)
        heads[self.rpc.urls[self.rpc.i]] = first
        if len(urls) > 1:
            other = urls[(self.rpc.i + 1) % len(urls)]
            try:
                heads[other] = int(bf_engine.rpc_call(other, "eth_blockNumber", [], timeout=10, retries=1), 16)
            except Exception:
                pass
        top = max(heads.values())
        for u, h9 in heads.items():
            if top - h9 > self.STALE_NODE_BLOCKS:
                g9 = bf_engine.gate(u)
                g9.open_until = max(g9.open_until, time.time() + 60)
                log.info("BSC 노드 %s 헤드 %d 가 %d블록 뒤처짐 — 60초 제외", common.redact_urls(u), h9, top - h9)
        self.node_heads = {common.redact_urls(u): h9 for u, h9 in heads.items()}
        return top

    def token_info(self, ca: str) -> tuple:
        ca = ca.lower()
        if ca in self.token_meta:
            m = self.token_meta[ca]
            return m[0], m[1]
        if self.nodec.perm(ca):
            raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}")
        sym, dec = None, 18
        try:
            r = self.rpc.call("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"])
            sym = _dec_string(r or "")
        except Exception:
            sym = None
        time.sleep(CALL_SLEEP)
        try:
            r = self.rpc.call("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
        except Exception as e:
            if bf_engine.revert_like(e) and self.nodec.bad(ca, "revert: " + common.safe_err(e)[:80]):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {common.safe_err(e)[:80]}") from e
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: {e}")
        dec, why = bf_engine.decimals_from_result(r)
        if dec is None:
            if self.nodec.bad(ca, why):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {why}")
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: decimals {why}")
        self.nodec.ok(ca)
        if isinstance(sym, str):
            sym = sym.strip()[:16] or None
        self.token_meta[ca] = [sym, dec]
        return sym, dec

    def _logs(self, frm: int, to: int, position: int):
        topics = [TRANSFER_TOPIC, None, None]
        topics[1 if position == 0 else 2] = self.topics
        params = [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": topics[:3]}]
        last = None
        for attempt in range(3):
            try:
                res = self.logs_rpc.call("eth_getLogs", params)
                if not isinstance(res, list):
                    raise RuntimeError(f"getLogs 비정상 result: {type(res).__name__}")
                return res
            except Exception as e:
                last = e
                msg = str(e)
                if "429" in msg or "Too Many" in msg:
                    log.info("getLogs 429 — %d초 대기 후 재시도", 30 * (attempt + 1))
                    time.sleep(30 * (attempt + 1))
                    continue
                break
        if self.logs_fb:
            log.warning("getLogs 주 풀 실패(%s) — 비상 폴백 청크 조회 %d-%d", str(last)[:60], frm, to)
            return self._logs_fallback(frm, to, topics[:3])
        raise last if last else RuntimeError("getLogs 429 지속")

    def _logs_fallback(self, frm: int, to: int, topics: list) -> list:
        last = None
        for url, cap in self.logs_fb.items():
            rows, cur, ok = [], frm, True
            one = Rpc([url])
            while cur <= to:
                end = min(cur + cap - 1, to)
                try:
                    chunk = one.call("eth_getLogs", [{"fromBlock": hex(cur), "toBlock": hex(end),
                                                      "topics": topics}])
                    if not isinstance(chunk, list):
                        raise RuntimeError(f"폴백 {common.redact_urls(url)} 청크 {cur}-{end} 비정상 result: {type(chunk).__name__}")
                    rows.extend(chunk)
                except Exception as e:
                    last = e; ok = False
                    log.warning("폴백 %s 청크 %d-%d 실패: %s", common.redact_urls(url), cur, end,
                                common.redact_urls(str(e))[:60])
                    break
                cur = end + 1
                time.sleep(0.3)
            if ok:
                return rows
        raise last if last else RuntimeError("getLogs 폴백 미구성")

    def discover(self, frm: int, to: int, budget_sec: float = 600, on_advance=None, topics=None) -> "tuple | None":
        if to < frm:
            return set(), frm - 1
        sc = bf_engine.LogScanner(
            list(self.logs_rpc.urls), TRANSFER_TOPIC, list(topics) if topics else self.topics,
            span=max(self.span, self.span_max),
            caps=self.span_caps, fallback=self.logs_fb, sleep=self.logs_sleep, timeout=25,
            per_ep_workers=self.scan_workers, log=log, name="bsc getLogs",
            canary=getattr(self, "canary", bf_engine.BSC_CANARY), head_guard=getattr(self, "logs_head_guard", True),
            positions=({1: [TRANSFER_TOPIC, DEPOSIT_TOPIC, WITHDRAWAL_TOPIC], 2: TRANSFER_TOPIC}
                       if getattr(self, "discover_wrap", False) else None))
        found, last_done = sc.scan(frm, to, deadline=time.time() + budget_sec,
                                   on_advance=on_advance)
        self.span_caps.update(sc.caps)
        self.last_scan_metrics = dict(sc.metrics, stop=sc.last_stop)
        if last_done < to:
            log.info("getLogs %d-%d 중 %d 까지 연속 완료 (%s) — 다음 사이클 계속", frm, to, last_done,
                     sc.last_stop or "예산 소진")
        return set(found), last_done

    def _block_time(self, block_hex: str) -> int:
        if block_hex in self.block_ts:
            return self.block_ts[block_hex]
        b = self.rpc.call("eth_getBlockByNumber", [block_hex, False])
        ts = int(b["timestamp"], 16)
        self.block_ts[block_hex] = ts
        if len(self.block_ts) > 5000:
            self.block_ts.clear()
        return ts

    def fetch_detail(self, txhash: str) -> dict:
        r = self.fetch_details([txhash]).get(txhash)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise RuntimeError(f"미확정 tx: {txhash}")
        return r

    def _fetch_detail_single(self, txhash: str) -> dict:
        tx = self.rpc.call("eth_getTransactionByHash", [txhash])
        time.sleep(CALL_SLEEP)
        rc = self.rpc.call("eth_getTransactionReceipt", [txhash])
        return self._build_snapshot(txhash, tx, rc)

    def _mine_logs(self, rc: dict):
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 3 or tp[0].lower() != TRANSFER_TOPIC:
                continue
            fr9, to9 = ("0x" + tp[1][-40:]).lower(), ("0x" + tp[2][-40:]).lower()
            if fr9 not in self.wallets and to9 not in self.wallets:
                continue
            try:
                val = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if not val:
                continue
            yield lg, tp, val

    def _wrap_moves(self, rc: dict, tts: list) -> tuple:
        wr = getattr(self, "wrapped_ca", None)
        if not wr:
            return [], []
        cover = {}
        for t in tts:
            if (t.get("token") or {}).get("address") == wr:
                k = (str(t.get("from") or "").lower(), str(t.get("to") or "").lower(), str((t.get("total") or {}).get("value")))
                cover[k] = cover.get(k, 0) + 1
        legs, ints = [], []
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tp[0] or "").lower()
            if t0 not in (DEPOSIT_TOPIC, WITHDRAWAL_TOPIC):
                continue
            who = ("0x" + str(tp[1])[-40:]).lower()
            if who not in self.wallets:
                continue
            try:
                v = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if not v:
                continue
            fr, to = (ZERO_ADDR, who) if t0 == DEPOSIT_TOPIC else (who, ZERO_ADDR)
            if t0 == WITHDRAWAL_TOPIC:
                ints.append({"from": wr, "to": who, "value": str(v), "success": True})
            k = (fr, to, str(v))
            if cover.get(k):
                cover[k] -= 1
                continue
            sym, dec = self.token_info(wr)
            legs.append({"from": fr, "to": to, "token": {"address": wr, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                         "total": {"value": str(v)}})
        return legs, ints

    def _token_info_batch(self, cas):
        cas = sorted(c for c in set(cas) if c not in self.token_meta and not self.nodec.perm(c))
        if not cas:
            return
        calls = []
        for ca in cas:
            calls += [("eth_call", [{"to": ca, "data": "0x95d89b41"}, "latest"]),
                      ("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])]
        try:
            res = self.rpc.batch(calls)
        except Exception:
            return
        for j, ca in enumerate(cas):
            sym_r, dec_r = res[2 * j], res[2 * j + 1]
            if isinstance(dec_r, Exception) or not dec_r or dec_r == "0x":
                continue
            try:
                dec = int(dec_r, 16)
            except (TypeError, ValueError):
                continue
            sym = None if isinstance(sym_r, Exception) else _dec_string(sym_r or "")
            if isinstance(sym, str):
                sym = sym.strip()[:16] or None
            self.token_meta[ca] = [sym, dec]

    def fetch_details(self, hashes, deadline: float = None) -> dict:
        out = {}
        hs = list(dict.fromkeys(h for h in hashes if h))
        B = self.detail_batch
        for i in range(0, len(hs), B):
            chunk = hs[i:i + B]
            if deadline is not None and time.time() > deadline:
                for h in hs[i:]:
                    out[h] = RuntimeError("detail 예산 소진 — 다음 사이클")
                break
            pairs = {}
            try:
                calls = []
                for h in chunk:
                    calls += [("eth_getTransactionByHash", [h]), ("eth_getTransactionReceipt", [h])]
                res = self.rpc.batch(calls)
                for j, h in enumerate(chunk):
                    tx, rc = res[2 * j], res[2 * j + 1]
                    if not isinstance(tx, Exception) and not isinstance(rc, Exception):
                        pairs[h] = (tx, rc)
            except Exception as e:
                log.info("상세 배치 실패 → 단건 경로: %s", str(e)[:100])
            try:
                need = sorted({tx["blockNumber"] for tx, rc in pairs.values()
                               if isinstance(tx, dict) and tx.get("blockNumber")
                               and tx["blockNumber"] not in self.block_ts})
                if need:
                    res = self.rpc.batch([("eth_getBlockByNumber", [b9, False]) for b9 in need])
                    for b9, r9 in zip(need, res):
                        if isinstance(r9, dict) and r9.get("timestamp"):
                            self.block_ts[b9] = int(r9["timestamp"], 16)
                cas = {lg.get("address", "").lower() for _tx, rc in pairs.values() if isinstance(rc, dict)
                       for lg, _tp, _v in self._mine_logs(rc)}
                self._token_info_batch(cas)
            except Exception as e:
                log.info("블록/메타 배치 실패 → 단건 경로: %s", str(e)[:100])
            for h in chunk:
                try:
                    if h in pairs:
                        out[h] = self._build_snapshot(h, *pairs[h])
                    else:
                        out[h] = self._fetch_detail_single(h)
                except Exception as e:
                    out[h] = e
            time.sleep(CALL_SLEEP)
        return out

    def _build_snapshot(self, txhash: str, tx: dict, rc: dict) -> dict:
        if not tx or not rc or tx.get("blockNumber") is None:
            raise RuntimeError(f"미확정 tx: {txhash}")
        gas_used = int(rc["gasUsed"], 16)
        gas_px = int(rc.get("effectiveGasPrice") or tx.get("gasPrice") or "0x0", 16)
        status = rc.get("status")
        ts = self._block_time(tx["blockNumber"])
        tts = []
        for lg, tp, val in self._mine_logs(rc):
            ca = lg.get("address", "").lower()
            try:
                sym, dec = self.token_info(ca)
            except bf_engine.TokenNoDecimals:
                self.nodec.skip(txhash, ca, "0x" + tp[1][-40:], "0x" + tp[2][-40:], val)
                continue
            tts.append({
                "from": "0x" + tp[1][-40:], "to": "0x" + tp[2][-40:],
                "token": {"address": ca, "symbol": sym, "decimals": dec, "type": "ERC-20"},
                "total": {"value": str(val)},
            })
        wl9, wi9 = self._wrap_moves(rc, tts) if status == "0x1" else ([], [])
        tts.extend(wl9)
        return {
            "tx": {
                "hash": tx["hash"], "from": tx.get("from"), "to": tx.get("to"),
                "value": str(int(tx.get("value") or "0x0", 16)),
                "fee": {"value": str(gas_used * gas_px)},
                "status": "ok" if status == "0x1" else "error",
                "raw_input": tx.get("input") or "0x",
                "timestamp": ts,
                "block_number": int(tx["blockNumber"], 16),
                "block_hash": tx.get("blockHash"),
            },
            "token_transfers": tts,
            "internal": wi9,
        }

    def block_at_ts(self, ts: int, hi: int) -> int:
        return bf_engine.block_at_ts(lambda b: self._block_time(hex(b)), int(ts), 0, int(hi))

    def _health(self, head: int, since: int, ok: bool, err=None):
        hb = bf_engine.health("bsc")
        now = time.time()
        prev = getattr(self, "_hb_prev", None)
        if prev and head > prev[0]:
            v = (now - prev[1]) / float(head - prev[0])
            self._hb_bsec = v if getattr(self, "_hb_bsec", None) is None else 0.7 * self._hb_bsec + 0.3 * v
        if not prev or head != prev[0]:
            self._hb_prev = (head, now)
        bsec = getattr(self, "_hb_bsec", None)
        safe = head - self.conf_depth
        sc = self.cursor.get("_scan")
        facts = dict(head=head, cursor=since, lag_blocks=safe - since,
                     lag_sec=int((safe - since) * bsec) if bsec else None,
                     block_sec_est=round(bsec, 3) if bsec else None,
                     head_unchanged_sec=int(now - self._hb_prev[1]) if getattr(self, "_hb_prev", None) else None,
                     node_heads=getattr(self, "node_heads", None),
                     current_source=common.redact_urls(self.rpc.urls[self.rpc.i]),
                     logs_sources=[common.redact_urls(u) for u in self.logs_rpc.urls],
                     scan_pending=len(sc.get("found") or []) if isinstance(sc, dict) else 0,
                     synced_at=self.cursor.get("_synced_at"), scan=self.last_scan_metrics or None)
        if ok:
            hb.ok("bsc", "bsc_rpc", **facts)
        else:
            hb.fail("bsc", err or RuntimeError("부분 진행"), "bsc_rpc", **facts)
        hb.flush()

    def _extend(self, head: int):
        target = bf_engine.SINCE.target("bsc")
        if not target:
            return
        ext = self.cursor.get("_ext")
        if not isinstance(ext, dict) or ext.get("target") != target:
            tblk = self.block_at_ts(target, head - self.conf_depth)
            cov = self.cursor.get("_cov")
            if not isinstance(cov, int):
                hint = bf_engine.SINCE.covered_hint("bsc")
                base9 = int(self.cursor.get("_bf_start") or self.cursor.get("from_block") or 0)
                cov = min(self.block_at_ts(hint, head - self.conf_depth), base9) if hint else base9
            if cov <= tblk + 1:
                return
            ext = {"target": int(target), "tblk": int(tblk), "to": int(cov), "done_to": int(tblk), "found": [],
                   "t0": int(time.time())}
            self.cursor["_ext"] = ext
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 과거 창 확장: 블록 %d → %d (%s~)★", tblk, cov, time.strftime("%Y-%m-%d", time.gmtime(target)))
        t0 = time.time()
        if ext["done_to"] < ext["to"]:
            found, last = self.discover(ext["done_to"] + 1, ext["to"], budget_sec=self.cycle_budget)
            if last > ext["done_to"]:
                ext["found"] = sorted(set(ext["found"]) | {h for h in found if h not in self.emitted})
                ext["done_to"] = last
                common.atomic_write_json(self.cursor_path, self.cursor)
        todo = [h for h in ext["found"] if h not in self.emitted]
        dets = self.fetch_details(todo, deadline=t0 + self.cycle_budget) if todo else {}
        order = sorted(todo, key=lambda h: (dets[h]["tx"]["block_number"], h) if isinstance(dets.get(h), dict)
                       else (1 << 62, h))
        n_emit = 0
        for h in order:
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.info("BSC 확장 상세 %s 보류(다음 사이클): %s", h[:12], str(snap)[:100])
                break
            self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
            self.emitted.add(h)
            n_emit += 1
        common.atomic_write_json(self.meta_path, self.token_meta)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        ext["found"] = [h for h in ext["found"] if h not in self.emitted]
        span = max(1, ext["to"] - ext["tblk"])
        self.progress.update("bsc:extend", phase="extend", unit="blocks", done=ext["done_to"] - ext["tblk"], total=span,
                             pending_detail=len(ext["found"]), target=time.strftime("%Y-%m-%d", time.gmtime(target)),
                             range=[ext["tblk"], ext["to"]], note=(self.last_scan_metrics or {}).get("stop"))
        if ext["done_to"] >= ext["to"] and not ext["found"]:
            self.cursor["_cov"] = ext["tblk"]
            self.cursor.pop("_ext", None)
            self.progress.finish("bsc:extend", note=f"확장 완료 {span}블록")
            log.info("★BSC 과거 창 확장 완료 — 하한 블록 %d (%.0f분)★", ext["tblk"], (time.time() - ext["t0"]) / 60)
        common.atomic_write_json(self.cursor_path, self.cursor)

    NEWW_KEY = "bsc:newwallet"

    def _seed_wallet_set(self):
        cur = sorted(set(self.wallets))
        known = self.cursor.get("_wallets")
        if not isinstance(known, list):
            self.cursor["_wallets"] = cur
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("BSC 추적 지갑 집합 시드: %d개 (재스캔 없음)", len(cur))
            return
        kept = sorted(set(known) & set(cur))
        dirty = kept != sorted(known)
        if dirty:
            self.cursor["_wallets"] = kept
        if set(cur) - set(kept) and not isinstance(self.cursor.get("_neww"), dict) and "_neww_top" not in self.cursor:
            sc = self.cursor.get("_scan")
            fb = int(self.cursor.get("from_block") or 0)
            self.cursor["_neww_top"] = max(fb, int(sc.get("to") or 0)) if isinstance(sc, dict) else fb
            dirty = True
        if dirty:
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _new_wallet_lo(self, head: int, new=None) -> int:
        cands = [self.block_at_ts(int(time.time()) - self.backfill_days * 86400, head - self.conf_depth)]
        ws9 = [self.wallet_since[w] for w in (new or ()) if (getattr(self, "wallet_since", None) or {}).get(w)]
        if ws9:
            cands.append(self.block_at_ts(min(ws9), head - self.conf_depth))
        for v in (self.cursor.get("_cov"), self.cursor.get("_bf_start")):
            if isinstance(v, int) and v > 0:
                cands.append(v)
        ext = self.cursor.get("_ext")
        if isinstance(ext, dict) and isinstance(ext.get("tblk"), int):
            cands.append(int(ext["tblk"]))
        return max(1, min(cands))

    def _new_wallet_pass(self, head: int):
        known = self.cursor.get("_wallets")
        if not isinstance(known, list):
            return
        cur = set(self.wallets)
        fb = int(self.cursor.get("from_block") or 0)
        sc = self.cursor.get("_scan")
        top = max(fb, int(sc.get("to") or 0)) if isinstance(sc, dict) else fb
        hint = self.cursor.get("_neww_top")
        if isinstance(hint, int) and 0 < hint <= top:
            top = hint
        job = self.cursor.get("_neww")
        if isinstance(job, dict):
            jw = sorted(set(job.get("wallets") or []) & cur)
            extra = sorted(cur - set(known) - set(jw))
            if extra:
                lo2 = min(int(job["lo"]), int(self._new_wallet_lo(head, extra)))
                jw = sorted(set(jw) | set(extra))
                job["lo"] = lo2
                job["done_to"] = lo2 - 1
                job["to"] = max(int(job["to"]), top)
            if not jw:
                self.cursor.pop("_neww", None)
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            job["wallets"] = jw
        else:
            new = sorted(cur - set(known))
            if not new:
                return
            if fb <= 0 or hint == 0:
                self.cursor.pop("_neww_top", None)
                self.cursor["_wallets"] = sorted(cur)
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            lo = self._new_wallet_lo(head, new)
            self.cursor.pop("_neww_top", None)
            if lo > top:
                self.cursor["_wallets"] = sorted(set(known) | set(new))
                common.atomic_write_json(self.cursor_path, self.cursor)
                return
            job = {"wallets": new, "lo": int(lo), "to": int(top), "done_to": int(lo) - 1, "found": [],
                   "t0": int(time.time())}
            self.cursor["_neww"] = job
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 나중 등록 지갑 %d개 이력 백필: 블록 %d → %d (새 지갑 토픽만)★", len(new), lo, top)
        t0 = time.time()
        if job["done_to"] < job["to"]:
            found, last = self.discover(job["done_to"] + 1, job["to"], budget_sec=self.cycle_budget,
                                        topics=[_pad_topic(w) for w in job["wallets"]])
            if last > job["done_to"]:
                job["found"] = sorted(set(job["found"]) | set(found))
                job["done_to"] = last
                common.atomic_write_json(self.cursor_path, self.cursor)
        todo = list(job["found"])
        dets = self.fetch_details(todo, deadline=t0 + self.cycle_budget) if todo else {}
        order = sorted(todo, key=lambda h: (dets[h]["tx"]["block_number"], h) if isinstance(dets.get(h), dict)
                       else (1 << 62, h))
        sent = set()
        for h in order:
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.info("BSC 새 지갑 백필 상세 %s 보류(다음 사이클): %s", h[:12], str(snap)[:100])
                break
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
            except Exception as e:
                log.error("inbox append 실패 — 새 지갑 백필 보류: %s", e)
                break
            self.emitted.add(h)
            sent.add(h)
        common.atomic_write_json(self.meta_path, self.token_meta)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        job["found"] = [h for h in job["found"] if h not in sent]
        span = max(1, job["to"] - job["lo"] + 1)
        self.progress.update(self.NEWW_KEY, phase="extend", unit="blocks", done=job["done_to"] - job["lo"] + 1,
                             total=span, pending_detail=len(job["found"]), range=[job["lo"], job["to"]],
                             note=f"새 지갑 {len(job['wallets'])}개")
        if job["done_to"] >= job["to"] and not job["found"]:
            self.cursor["_wallets"] = sorted((set(known) | set(job["wallets"])) & cur)
            self.cursor.pop("_neww", None)
            self.progress.finish(self.NEWW_KEY, note=f"새 지갑 {len(job['wallets'])}개 이력 백필 완료 {span}블록")
            log.info("★BSC 나중 등록 지갑 이력 백필 완료 — %d개, %.0f분★", len(job["wallets"]), (time.time() - job["t0"]) / 60)
        common.atomic_write_json(self.cursor_path, self.cursor)

    def _detail_fail_note(self, bad: list, dets: dict) -> list:
        return bf_engine.detail_fail_note(self.cursor, bad, dets, "bsc", "bsc_detail", log, self.__dict__.setdefault("_df_seen", set()))

    def _detail_fail_clear(self, ok_hashes):
        bf_engine.detail_fail_clear(self.cursor, ok_hashes)

    def _quarantine_retry(self, head: int):
        due = bf_engine.quarantine_due(self.cursor)
        if not due:
            return 0
        dets = self.fetch_details(due)
        n = 0
        for h in due:
            snap = dets.get(h)
            if isinstance(snap, dict):
                if h not in self.emitted:
                    self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                        "wallets": self.wallets, "observed_head": head, "ts": int(time.time())})
                    self.emitted.add(h)
                    n += 1
                bf_engine.quarantine_result(self.cursor, h, True, "bsc", "bsc_detail", log)
            else:
                bf_engine.quarantine_result(self.cursor, h, False, "bsc", "bsc_detail", log, err=snap)
        common.atomic_write_json(self.meta_path, self.token_meta)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        return n

    def _nonce_path(self) -> str:
        return os.path.join(common.STATE_DIR, "bsc_nonce.json")

    def _nonce_load(self) -> dict:
        d = getattr(self, "_nonce_st", None)
        if d is None:
            d = common.read_json(self._nonce_path(), {})
            if not isinstance(d, dict) or not isinstance(d.get("w"), dict):
                d = {"w": {}}
            self._nonce_st = d
        return d

    def _nonce_note(self, rec: dict):
        st = self._nonce_load()
        if not st.get("boot"):
            return
        tx = ((rec or {}).get("snapshot") or {}).get("tx") or {}
        fr = str(tx.get("from") or "").lower()
        if fr not in self.wallets:
            return
        try:
            b = int(tx.get("block_number"))
        except (TypeError, ValueError):
            return
        ws = st["w"].setdefault(fr, {})
        hs = ws.setdefault("hashes", {})
        h = str(rec.get("txhash") or tx.get("hash") or "").lower()
        if h and h not in hs:
            hs[h] = b
            ws["blocks"] = sorted(hs.values())
            common.atomic_write_json(self._nonce_path(), st)

    def _nonce_boot(self, st: dict) -> bool:
        if st.get("boot"):
            return True
        if not os.path.exists(common.DB_PATH):
            return False
        import sqlite3
        try:
            con = sqlite3.connect("file:" + common.DB_PATH + "?mode=ro", uri=True, timeout=10)
            try:
                rows = con.execute("SELECT txhash, block, json_extract(snapshot, '$.tx.from') FROM raw_txs WHERE chain='bsc'").fetchall()
            finally:
                con.close()
        except Exception as e:
            log.info("BSC nonce 색인 부트스트랩 실패(다음 기회): %s", str(e)[:120])
            return False
        mine = set(self.wallets)
        for h, b, fr in rows:
            fr = str(fr or "").lower()
            if fr in mine and b is not None:
                st["w"].setdefault(fr, {}).setdefault("hashes", {})[str(h).lower()] = int(b)
        for w, ws in st["w"].items():
            ws["blocks"] = sorted((ws.get("hashes") or {}).values())
        st["boot"] = int(_now())
        common.atomic_write_json(self._nonce_path(), st)
        log.info("BSC nonce 색인 부트스트랩: 원장 발신 tx %d건", sum(len(ws.get("hashes") or {}) for ws in st["w"].values()))
        return True

    def _nonce_pass(self, head: int) -> int:
        st = self._nonce_load()
        if _now() - float(st.get("at") or 0) < NONCE_EVERY:
            return 0
        st["at"] = int(_now())
        lo_blk = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        if not isinstance(lo_blk, int) or lo_blk <= 0:
            return 0
        safe = int(head) - self.conf_depth
        if safe <= lo_blk:
            return 0
        if not self._nonce_boot(st):
            return 0
        busy = set((self.cursor.get("_neww") or {}).get("wallets") or []) if isinstance(self.cursor.get("_neww"), dict) else set()
        known_set = self.cursor.get("_wallets")
        calls = [0]
        n_emit = 0
        n_found = 0
        base_rpc = self.rpc

        def charge(n):
            if calls[0] + n > NONCE_CALL_CAP:
                raise RuntimeError("nonce 확인 호출 상한")
            calls[0] += n

        class _Metered:

            def call(self, m, p, *a, **kw):
                charge(1)
                return base_rpc.call(m, p, *a, **kw)

            def batch(self, items, *a, **kw):
                charge(len(items))
                return base_rpc.batch(items, *a, **kw)

            def __getattr__(self, k):
                return getattr(base_rpc, k)

        def rpc(m, p):
            return self.rpc.call(m, p)

        nmemo = {}

        def nonce_at(w9, b9):
            k9 = (w9, int(b9))
            if k9 not in nmemo:
                nmemo[k9] = int(rpc("eth_getTransactionCount", [w9, hex(int(b9))]), 16)
            return nmemo[k9]

        wl = list(self.wallets)
        rr = int(st.get("rr") or 0) % len(wl) if wl else 0
        order = wl[rr:] + wl[:rr]
        self.rpc = _Metered()
        try:
            for wi, w in enumerate(order):
                if n_found >= NONCE_MAX_FIND:
                    break
                st["rr"] = (rr + wi + 1) % len(wl)
                if w in busy or (isinstance(known_set, list) and w not in known_set):
                    continue
                ws = st["w"].setdefault(w, {})
                if ws.get("kind") is None:
                    code = str(rpc("eth_getCode", [w, "latest"]) or "0x").lower()
                    ws["kind"] = "eoa" if code in ("0x", "0x0", "") or code.startswith("0xef0100") else "contract"
                if ws["kind"] != "eoa":
                    continue
                lo = ws.get("lo")
                if not (isinstance(lo, list) and len(lo) == 2 and lo[0] == lo_blk):
                    lo = ws["lo"] = [lo_blk, nonce_at(w, lo_blk)]
                nmemo[(w, lo_blk)] = lo[1]
                hs = ws.setdefault("hashes", {})
                extras = ws.setdefault("nonce_extra", {})

                def known_le(b9, blocks9, ex9=extras):
                    return sum(1 for b in blocks9 if b <= b9) + sum(int(n9) for k9, n9 in ex9.items() if lo_blk < int(k9) <= b9)

                blocks = sorted(b for b in hs.values() if lo_blk < b <= safe)
                missing = nonce_at(w, safe) - lo[1] - known_le(safe, blocks)
                ws["missing"] = missing
                if missing < 0:
                    log.info("BSC nonce 확인 %s: 색인 발신 %d > nonce 차 — 건너뜀(원장·색인 불일치)", w[:10], len(blocks))
                    continue
                lo_b = lo_blk
                while missing > 0 and n_found < NONCE_MAX_FIND:
                    a, z = lo_b, safe
                    while z - a > 1:
                        mid = (a + z) // 2
                        d = nonce_at(w, mid) - lo[1] - known_le(mid, blocks)
                        if d >= 1:
                            z = mid
                        else:
                            a = mid
                    blk = rpc("eth_getBlockByNumber", [hex(z), True]) or {}
                    txs9 = blk.get("transactions")
                    try:
                        num9 = int(str(blk.get("number") or "0x0"), 16)
                    except ValueError:
                        num9 = -1
                    if num9 != z or not isinstance(txs9, list) or any(not isinstance(t, dict) or not t.get("from") or not t.get("hash") for t in txs9):
                        raise RuntimeError(f"블록 {z} 전체 응답 불완전")
                    mine = [t for t in txs9 if str(t.get("from") or "").lower() == w]
                    n_found += 1
                    extra9 = nonce_at(w, z) - nonce_at(w, z - 1) - len(mine)
                    if extra9 < 0:
                        raise RuntimeError(f"블록 {z} nonce 증가량({nonce_at(w, z) - nonce_at(w, z - 1)}) < 내 발신 tx {len(mine)}")
                    if extra9 > 0:
                        extras[str(z)] = extra9
                        log.info("BSC nonce 확인 %s: 블록 %d nonce +%d 은 발신 tx 아님(7702 위임 등) — 기록하고 다음으로", w[:10], z, extra9)
                    if not mine and not extra9:
                        log.info("BSC nonce 확인 %s: 블록 %d 에 내 발신 tx 없음 — 이번엔 멈춤", w[:10], z)
                        break
                    todo = [str(t.get("hash") or "").lower() for t in mine]
                    new = [h for h in todo if h and h not in self.emitted]
                    dets = self.fetch_details(new) if new else {}
                    for h in todo:
                        if h in new:
                            snap = dets.get(h)
                            if not isinstance(snap, dict):
                                raise RuntimeError(f"상세 실패 {h[:12]}")
                            self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                                "wallets": self.wallets, "observed_head": head, "ts": int(time.time()), "via": "nonce"})
                            self.emitted.add(h)
                            n_emit += 1
                            log.info("★BSC 로그 없는 발신 tx 회수(nonce) %s 블록 %d★", h[:14], z)
                        hs[h] = z
                    blocks = sorted(b for b in hs.values() if lo_blk < b <= safe)
                    missing = nonce_at(w, safe) - lo[1] - known_le(safe, blocks)
                    ws["missing"] = missing
                    lo_b = z
        except Exception as e:
            log.info("BSC nonce 확인 중단(다음 기회): %s", str(e)[:120])
        finally:
            self.rpc = base_rpc
        for ws in st["w"].values():
            ws["blocks"] = sorted((ws.get("hashes") or {}).values())
        common.atomic_write_json(self._nonce_path(), st)
        if n_emit:
            common.atomic_write_json(self.meta_path, self.token_meta)
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        return n_emit

    def _report(self, head: int, since: int, phase: str, note: str = None, flush: bool = False):
        start = self.cursor.get("_bf_start")
        if isinstance(start, int) and head > start:
            self.progress.update("bsc", phase=phase, unit="blocks", done=max(0, since - start),
                                 total=max(1, head - self.conf_depth - start), note=note, flush=flush,
                                 lag=max(0, head - self.conf_depth - since), scan=self.last_scan_metrics or None)
        else:
            self.progress.update("bsc", phase=phase, unit="blocks", lag=max(0, head - self.conf_depth - since),
                                 note=note, flush=flush)

    def cycle(self):
        if self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        self._seed_wallet_set()
        self._df_seen = set()
        head = self.head()
        try:
            self._quarantine_retry(head)
        except Exception as e:
            log.info("BSC 격리 tx 재시도 실패(다음 사이클): %s", str(e)[:120])
        safe = head - self.conf_depth
        since = int(self.cursor.get("from_block", 0))
        if since == 0:
            cutoff = int(time.time()) - self.backfill_days * 86400
            lo = self.block_at_ts(cutoff, safe)
            since = max(1, lo)
            self.cursor["from_block"] = since
            self.cursor["_bf_start"] = since
            self.cursor["_cov"] = since
            common.atomic_write_json(self.cursor_path, self.cursor)
            log.info("백필 시작: 블록 %d → %d (%d일, timestamp 탐색)",
                     since, safe, self.backfill_days)
        if since >= safe:
            self._report(head, since, "live")
            self._health(head, since, True)
            self._extend(head)
            self._new_wallet_pass(head)
            self._nonce_pass(head)
            return
        safe0 = safe
        t_cycle = time.time()
        sc = self.cursor.get("_scan")
        if isinstance(sc, dict) and int(sc.get("frm", -1)) == since + 1 and int(sc.get("to", 0)) > since:
            found, last_done = set(sc.get("found") or []), int(sc["to"])
        else:
            def _adv(last, f):
                self._report(head, last, "scan")
            res = self.discover(since + 1, safe, budget_sec=self.cycle_budget, on_advance=_adv)
            if res is None:
                return
            found, last_done = res
            if last_done <= since:
                self._report(head, since, "scan", note="한 청크도 못 나감 — " + str(
                    (self.last_scan_metrics or {}).get("stop") or "노드 오류"), flush=True)
                return
            self.cursor["_scan"] = {"frm": since + 1, "to": last_done,
                                    "found": sorted(h for h in found if h not in self.emitted)}
            common.atomic_write_json(self.cursor_path, self.cursor)
        safe = last_done
        complete = last_done >= safe0
        ok = True
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        dets = self.fetch_details(todo, deadline=t_cycle + self.cycle_budget + 300) if todo else {}
        bad9 = [h for h in todo if not isinstance(dets.get(h), dict)]
        if bad9:
            gone9 = set(bad9) - set(self._detail_fail_note(bad9, dets))
            todo = [h for h in todo if h not in gone9]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])

        def _blk(h):
            v = dets.get(h)
            return (v["tx"]["block_number"], h) if isinstance(v, dict) else (1 << 62, h)
        n_ok = 0
        for h in sorted(todo, key=_blk):
            snap = dets.get(h)
            if isinstance(snap, Exception) or snap is None:
                log.warning("detail %s 실패 — 커서 유지(스캔 체크포인트로 다음 사이클 상세만 재시도): %s", h[:12], snap)
                ok = False
                break
            rec = {"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
                self.emitted.add(h)
                n_ok += 1
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                ok = False
                break
        common.atomic_write_json(self.meta_path, self.token_meta)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        if ok:
            self.cursor["from_block"] = safe
            self.cursor["head"] = head
            self.cursor.pop("_scan", None)
            if complete:
                self.cursor["_synced_at"] = int(time.time())
            else:
                self.cursor.pop("_synced_at", None)
                log.warning("부분 조회 %d→%d (확정 헤드 %d) — 커서 전진, 도장 보류", since, safe, safe0)
            common.atomic_write_json(self.cursor_path, self.cursor)
            if found:
                log.info("사이클 완료: %d tx (블록 %d→%d, %.0f초)", len(found), since, safe, time.time() - t_cycle)
            self._report(head, safe, "live" if complete else "scan")
            self._health(head, safe, True)
            if complete:
                self._extend(head)
                self._new_wallet_pass(head)
                self._nonce_pass(head)
        else:
            sc9 = self.cursor.get("_scan")
            if isinstance(sc9, dict):
                sc9["found"] = sorted(h for h in found if h not in self.emitted)
                common.atomic_write_json(self.cursor_path, self.cursor)
            self._report(head, since, "detail", note=f"상세 남음 {len(sc9.get('found') or []) if isinstance(sc9, dict) else '?'}건")
            self._health(head, since, False, RuntimeError("상세 실패 — 스캔 체크포인트로 재시도"))


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "bsc_rpc"]
    if not wallets:
        raise SystemExit("추적할 BSC 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("bsc", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "bsc"))
    w = BscWatcher(cfg, wallets, writer)
    log.info("가동: %d지갑, %d초 주기, 백필 %d일", len(wallets), poll, w.backfill_days)
    while True:
        t0 = time.time()
        try:
            w.cycle()
        except Exception as e:
            n9 = bf_engine.health("bsc").fail("bsc", e, "bsc_rpc")
            bf_engine.health("bsc").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    main()
