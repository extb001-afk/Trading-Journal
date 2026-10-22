"""BNB Smart Chain wallet watcher."""
from __future__ import annotations

import bisect
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, logs, paths, runtime, statefile, textutil
if __name__ == "__main__":
    runtime.cpu_reserve_apply()
import bf_engine
from inbox import SegmentWriter

log = logs.setup_logging("tj-bsc")

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEPOSIT_TOPIC = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
WITHDRAWAL_TOPIC = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
BLOCKS_PER_DAY = 28800
CALL_SLEEP = 0.25


from bsc_base import (  # noqa: F401
    _BalwStop,
    _native_delta,
    _now,
    _pad_topic,
    _touches,
    BALW_CALL_CAP,
    BALW_DAY_CAP,
    BALW_HIST_GAP,
    BALW_HIST_RETRY,
    BALW_JOBS_MAX,
    BALW_REQ_WAIT,
    BALW_RX_NAME,
    BALW_STALE,
    BALW_TIME_CAP,
    DISC_REQ_NAME,
    LANE_SPLIT_SEC,
    NONCE_CALL_CAP,
    NONCE_HEAD_EVERY,
    NONCE_MAX_FIND,
    NONCE_PUB_CAP,
    Rpc,
    XIN_MAX_NEW,
    XIN_NF_MAX,
)
LIVE_SEED_SEC = 3600
BSC_BLOCK_SEC = 0.45


def _ord_li(leg: dict, lg: dict) -> None:
    li9 = bf_engine.ord_index(lg.get("logIndex"))
    if li9 is not None:
        leg["log_index"] = li9


class _SentTap:

    def __init__(self, inner, owner):
        self.inner = inner
        self._owner = owner

    def append(self, rec):
        r = self.inner.append(rec)
        try:
            self._owner._nonce_note(rec)
        except Exception as e:   # noqa: BLE001 [optional]
            log.debug("nonce 색인 기록 실패: %s", e)
        try:
            self._owner._balw_note(rec)
        except Exception as e:   # noqa: BLE001 [optional]
            log.debug("잔고 감시 색인 기록 실패: %s", e)
        return r

    def __getattr__(self, k):
        return getattr(self.inner, k)


_ARCHIVE_HOST_HINTS = ("nodereal", "ankr.com", "quiknode.pro")


def _archive_like(url) -> bool:
    try:
        host = (urllib.parse.urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return False
    return any(k in host for k in _ARCHIVE_HOST_HINTS)


def _bsc_via() -> str:
    try:
        import nodesel
        return nodesel.via("bsc")
    except Exception:   # noqa: BLE001 [fallback]
        return ""


def _valid_meta(m) -> dict:
    out = {}
    bad = []
    for ca, v in (m.items() if isinstance(m, dict) else ()):
        d = v[1] if isinstance(v, list) and len(v) >= 2 else None
        if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 77:
            out[str(ca).lower()] = [v[0], d]
        else:
            bad.append(str(ca)[:10])
    if bad:
        log.warning("BSC 토큰 메타 캐시 이상 자리수 %d개 버림(다시 조회): %s", len(bad), ", ".join(bad[:5]))
    return out


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
    except Exception:  # noqa: BLE001 [optional]
        pass
    return None


from bsc_balw import BalwMixin  # noqa: E402


from bsc_nonce import NonceMixin  # noqa: E402


class BscWatcher(NonceMixin, BalwMixin):
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        bc = cfg["bsc"]
        self.logs_rpc = Rpc(bc["logs_rpcs"], rotate_each=True)
        arch = [str(u) for u in (bc.get("archive_rpcs") or [u for u in bc.get("logs_rpcs") or [] if "nodereal" in str(u)])]
        self.rpc = Rpc(list(bc["detail_rpcs"]) + [u for u in arch if u not in bc["detail_rpcs"]])
        self._arch_urls = list(dict.fromkeys(arch + [str(u) for u in list(bc["detail_rpcs"]) + list(bc.get("logs_rpcs") or []) if _archive_like(u)]))
        self.arch_rpc = Rpc(list(self._arch_urls)) if self._arch_urls else None
        pub9 = [u for u in bc["detail_rpcs"] if u not in self._arch_urls]
        self.nonce_pub_rpc = Rpc(pub9) if pub9 else None
        try:
            import nodesel
            nodesel.register("bsc", self.logs_rpc.urls, self.rpc.urls, self._arch_urls)
        except Exception:   # noqa: BLE001 [optional]
            pass
        self.logs_sleep = float(bc.get("logs_sleep_sec", 1.2))
        self.span = int(bc.get("getlogs_span", 5000))
        self.logs_fb = {str(u): int(c) for u, c in (bc.get("logs_rpcs_fallback") or {}).items() if int(c) > 0}
        self.canary = None if bc.get("canary") is False else bf_engine.BSC_CANARY
        self.conf_depth = int(bc.get("conf_depth", 20))
        self.backfill_days = bf_engine.bsc_backfill_days(cfg)
        self.poll_sec = float(bc.get("poll_sec", 60))
        self.lanes_cfg = bc.get("lanes")
        try:
            self.lane_budget = float(bc["lane_budget_sec"]) if bc.get("lane_budget_sec") is not None else None
        except (TypeError, ValueError):
            self.lane_budget = None
        self.wallets = [w.lower() for w in wallets]
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get("bsc") or "").lower() or None
        self.discover_wrap = bc.get("discover_wrap") is not False and bool(self.wrapped_ca)
        try:
            self.sell_verify_blocks = max(0, int(bc.get("sell_verify_blocks", self.SELL_WD_RECENT)))
        except (TypeError, ValueError):
            self.sell_verify_blocks = self.SELL_WD_RECENT
        self.wallet_since = bf_engine.wallet_since_map(cfg, "bsc")
        self.topics = [_pad_topic(w) for w in self.wallets]
        self.writer = _SentTap(writer, self)
        self.cursor_path = paths.state("cursor_bsc.json")
        self.cursor = statefile.read_json(self.cursor_path, {})
        self.meta_path = paths.state("bsc_token_meta.json")
        self.token_meta = _valid_meta(statefile.read_json(self.meta_path, {}))
        self.nodec = bf_engine.nodec_registry("bsc", log)
        self.emitted_path = paths.state("emitted_bsc.json")
        self.emitted = set(statefile.read_json(self.emitted_path, []))
        self.block_ts = {}
        self.span_caps = {str(u): int(c) for u, c in (bc.get("getlogs_span_caps") or {}).items()}
        self.scan_workers = int(bc.get("scan_workers", 1))
        self.span_max = int(bc.get("getlogs_span_max", 50000))
        self.detail_batch = max(1, int(bc.get("detail_batch", 8)))
        self.logs_head_guard = bc.get("logs_head_guard") is not False
        self.cycle_budget = float(bc.get("cycle_budget_sec", 600))
        self.progress = bf_engine.progress("bsc")
        self.last_scan_metrics = {}

    def _detail_home(self):
        arch9 = set(getattr(self, "_arch_urls", None) or ())
        rpc9 = getattr(self, "rpc", None)
        urls9 = getattr(rpc9, "urls", None)
        try:
            if arch9 and urls9 and urls9[rpc9.i] in arch9:
                self.rpc.i = next((j for j, u in enumerate(urls9) if u not in arch9), rpc9.i)
        except (IndexError, TypeError, AttributeError):
            pass

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
            except Exception:  # noqa: BLE001 [optional]
                pass
        top = max(heads.values())
        for u, h9 in heads.items():
            if top - h9 > self.STALE_NODE_BLOCKS:
                g9 = bf_engine.gate(u)
                g9.open_until = max(g9.open_until, time.time() + 60)
                log.info("BSC 노드 %s 헤드 %d 가 %d블록 뒤처짐 — 60초 제외", logs.redact_urls(u), h9, top - h9)
        self.node_heads = {logs.redact_urls(u): h9 for u, h9 in heads.items()}
        self._log_head = top
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
        except Exception:  # noqa: BLE001 [fallback]
            sym = None
        time.sleep(CALL_SLEEP)
        try:
            r = self.rpc.call("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
        except Exception as e:
            if bf_engine.revert_like(e) and self.nodec.bad(ca, "revert: " + logs.safe_err(e)[:80]):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {logs.safe_err(e)[:80]}") from e
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
            except Exception as e:  # noqa: BLE001 [fallback]
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
                        raise RuntimeError(f"폴백 {logs.redact_urls(url)} 청크 {cur}-{end} 비정상 result: {type(chunk).__name__}")
                    rows.extend(chunk)
                except Exception as e:  # noqa: BLE001 [fallback]
                    last = e; ok = False
                    log.warning("폴백 %s 청크 %d-%d 실패: %s", logs.redact_urls(url), cur, end,
                                logs.redact_urls(str(e))[:60])
                    break
                cur = end + 1
                time.sleep(0.3)
            if ok:
                return rows
        raise last if last else RuntimeError("getLogs 폴백 미구성")

    def discover(self, frm: int, to: int, budget_sec: float = 600, on_advance=None, topics=None) -> "tuple | None":
        if to < frm:
            return set(), frm - 1
        eps9, fb9 = list(self.logs_rpc.urls), dict(self.logs_fb or {})
        head9 = self.__dict__.get("_log_head")
        if isinstance(head9, int) and frm >= head9 - bf_engine.RPC_NEAR_HEAD:
            try:
                import nodekeys
                key9 = [u9 for u9 in eps9 if nodekeys.is_key_node(u9)]
            except Exception:   # noqa: BLE001 [fallback]
                key9 = []
            if key9 and len(key9) < len(eps9):
                eps9 = [u9 for u9 in eps9 if u9 not in key9]
                for u9 in key9:
                    fb9.setdefault(u9, int(self.span_caps.get(u9) or self.span))
        sc = bf_engine.LogScanner(
            eps9, TRANSFER_TOPIC, list(topics) if topics else self.topics,
            span=max(self.span, self.span_max),
            caps=self.span_caps, fallback=fb9, sleep=self.logs_sleep, timeout=25,
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
                val = textutil.log_word0(lg.get("data") or "0x0")
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
            _ord_li(legs[-1], lg)
        return legs, ints

    SELL_WD_RECENT = 100

    def _sell_unwrap(self, tx: dict, rc: dict, tts: list, ints: list) -> list:
        wr = getattr(self, "wrapped_ca", None)
        f = str(tx.get("from") or "").lower()
        my = set(self.wallets)
        if not wr or f not in my:
            return []
        try:
            if int(tx.get("value") or "0x0", 16):
                return []
        except (TypeError, ValueError):
            return []
        if any(str(t.get("to") or "").lower() in my for t in tts) or any(str(i.get("to") or "").lower() in my for i in ints):
            return []
        if not any(str(t.get("from") or "").lower() == f for t in tts):
            return []
        wd = dep = 0
        src = None
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if len(tp) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tp[0] or "").lower()
            who = ("0x" + str(tp[1])[-40:]).lower()
            if who in my or t0 not in (DEPOSIT_TOPIC, WITHDRAWAL_TOPIC):
                continue
            try:
                v = int(lg.get("data") or "0x0", 16)
            except ValueError:
                continue
            if t0 == WITHDRAWAL_TOPIC:
                wd += v
                src = src or who
            else:
                dep += v
        x = wd - dep
        if x <= 0 or not src:
            return []
        amt = self._sell_unwrap_check(f, tx, rc, x)
        if amt <= 0:
            log.info("BSC %s 매도 받은 BNB 추정 %d — 잔고 변화로는 안 받음(받는 사람 다름) · 행 안 만듦", str(tx.get("hash"))[:12], x)
            return []
        return [{"from": src, "to": f, "value": str(amt), "success": True, "attr": "balance_delta"}]

    def _sell_unwrap_check(self, f: str, tx: dict, rc: dict, x: int) -> int:
        pub = getattr(self, "nonce_pub_rpc", None)
        head = getattr(self, "_log_head", None)
        try:
            blk = int(tx["blockNumber"], 16)
            fee = int(rc["gasUsed"], 16) * int(rc.get("effectiveGasPrice") or tx.get("gasPrice") or "0x0", 16)
        except (KeyError, TypeError, ValueError):
            return x
        lim = getattr(self, "sell_verify_blocks", self.SELL_WD_RECENT)
        if pub is None or not isinstance(head, int) or blk < 1 or not lim or head - blk > lim:
            return x
        try:
            res = pub.batch([("eth_getBalance", [f, hex(blk - 1)]), ("eth_getBalance", [f, hex(blk)]),
                             ("eth_getTransactionCount", [f, hex(blk - 1)]), ("eth_getTransactionCount", [f, hex(blk)])], timeout=15)
            b0, b1, n0, n1 = (int(r, 16) for r in res)
        except Exception as e:   # noqa: BLE001 [fallback]
            log.info("BSC %s 매도 받은 BNB 잔고 확인 실패(로그 값 사용): %s", str(tx.get("hash"))[:12], logs.safe_err(e)[:80])
            return x
        if n1 - n0 != 1:
            return x
        r = b1 - b0 + fee
        if r <= 0:
            return 0
        return min(r, x)

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
        except Exception:  # noqa: BLE001 [optional]
            return
        for j, ca in enumerate(cas):
            sym_r, dec_r = res[2 * j], res[2 * j + 1]
            if isinstance(dec_r, Exception) or not dec_r or dec_r == "0x":
                continue
            dec, _why9 = bf_engine.decimals_from_result(dec_r)
            if dec is None:
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
            except _BalwStop:
                raise
            except Exception as e:  # noqa: BLE001 [isolate]
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
            except _BalwStop:
                raise
            except Exception as e:  # noqa: BLE001 [isolate]
                log.info("블록/메타 배치 실패 → 단건 경로: %s", str(e)[:100])
            for h in chunk:
                try:
                    if h in pairs:
                        out[h] = self._build_snapshot(h, *pairs[h])
                    else:
                        out[h] = self._fetch_detail_single(h)
                except _BalwStop:
                    raise
                except Exception as e:  # noqa: BLE001 [fallback]
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
            _ord_li(tts[-1], lg)
        wl9, wi9 = self._wrap_moves(rc, tts) if status == "0x1" else ([], [])
        tts.extend(wl9)
        if status == "0x1":
            wi9 = wi9 + self._sell_unwrap(tx, rc, tts, wi9)
        stx = {
            "hash": tx["hash"], "from": tx.get("from"), "to": tx.get("to"),
            "value": str(int(tx.get("value") or "0x0", 16)),
            "fee": {"value": str(gas_used * gas_px)},
            "status": "ok" if status == "0x1" else "error",
            "raw_input": tx.get("input") or "0x",
            "timestamp": ts,
            "block_number": int(tx["blockNumber"], 16),
            "block_hash": tx.get("blockHash"),
        }
        pos9 = bf_engine.tx_position(tx, rc)
        if pos9 is not None:
            stx["position"] = pos9
        return {
            "tx": stx,
            "token_transfers": tts,
            "internal": wi9,
        }

    def block_at_ts(self, ts: int, hi: int) -> int:
        return bf_engine.block_at_ts(lambda b: self._block_time(hex(b)), int(ts), 0, int(hi))

    def _health(self, head: int, since: int, ok: bool, err=None, extra=None):
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
                     current_source=logs.redact_urls(self.rpc.urls[self.rpc.i]),
                     logs_sources=[logs.redact_urls(u) for u in self.logs_rpc.urls],
                     scan_pending=len(sc.get("found") or []) if isinstance(sc, dict) else 0,
                     synced_at=self.cursor.get("_synced_at"), scan=self.last_scan_metrics or None,
                     lanes=(extra or {}).get("lanes"),
                     balw=self.__dict__.get("_balw_facts"))
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
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 과거 창 확장: 블록 %d → %d (%s~)★", tblk, cov, time.strftime("%Y-%m-%d", time.gmtime(target)))
        t0 = time.time()
        bud = self._side_left()
        if ext["done_to"] < ext["to"]:
            found, last = self.discover(ext["done_to"] + 1, ext["to"], budget_sec=bud)
            if last > ext["done_to"]:
                ext["found"] = sorted(set(ext["found"]) | {h for h in found if h not in self.emitted})
                ext["done_to"] = last
                statefile.atomic_write_json(self.cursor_path, self.cursor)
        todo = [h for h in ext["found"] if h not in self.emitted]
        dets = self.fetch_details(todo, deadline=t0 + bud) if todo else {}
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
        statefile.write_json_if_changed(self.meta_path, self.token_meta)
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        ext["found"] = [h for h in ext["found"] if h not in self.emitted]
        span = max(1, ext["to"] - ext["tblk"])
        self.progress.update("bsc:extend", phase="extend", unit="blocks", done=ext["done_to"] - ext["tblk"], total=span,
                             pending_detail=len(ext["found"]), target=time.strftime("%Y-%m-%d", time.gmtime(target)),
                             range=[ext["tblk"], ext["to"]], note=(self.last_scan_metrics or {}).get("stop"), via=_bsc_via())
        if ext["done_to"] >= ext["to"] and not ext["found"]:
            self.cursor["_cov"] = ext["tblk"]
            self.cursor.pop("_ext", None)
            self.progress.finish("bsc:extend", note=f"확장 완료 {span}블록")
            log.info("★BSC 과거 창 확장 완료 — 하한 블록 %d (%.0f분)★", ext["tblk"], (time.time() - ext["t0"]) / 60)
        statefile.atomic_write_json(self.cursor_path, self.cursor)

    NEWW_KEY = "bsc:newwallet"

    def _seed_wallet_set(self):
        cur = sorted(set(self.wallets))
        known = self.cursor.get("_wallets")
        if not isinstance(known, list):
            self.cursor["_wallets"] = cur
            statefile.atomic_write_json(self.cursor_path, self.cursor)
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
            lv9, ls9 = self.cursor.get("_live"), self.cursor.get("_lscan")
            if isinstance(lv9, dict) and fb > 0:
                try:
                    self.cursor["_neww_top"] = max(int(self.cursor["_neww_top"]), int(lv9.get("done") or 0),
                                                   int(ls9.get("to") or 0) if isinstance(ls9, dict) else 0)
                except (TypeError, ValueError):
                    pass
            dirty = True
        if dirty:
            statefile.atomic_write_json(self.cursor_path, self.cursor)

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
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                return
            job["wallets"] = jw
        else:
            new = sorted(cur - set(known))
            if not new:
                return
            if fb <= 0 or hint == 0:
                self.cursor.pop("_neww_top", None)
                self.cursor["_wallets"] = sorted(cur)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                return
            lo = self._new_wallet_lo(head, new)
            self.cursor.pop("_neww_top", None)
            if lo > top:
                self.cursor["_wallets"] = sorted(set(known) | set(new))
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                return
            job = {"wallets": new, "lo": int(lo), "to": int(top), "done_to": int(lo) - 1, "found": [],
                   "t0": int(time.time())}
            self.cursor["_neww"] = job
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.info("★BSC 나중 등록 지갑 %d개 이력 백필: 블록 %d → %d (새 지갑 토픽만)★", len(new), lo, top)
        t0 = time.time()
        bud = self._side_left()
        if job["done_to"] < job["to"]:
            found, last = self.discover(job["done_to"] + 1, job["to"], budget_sec=bud,
                                        topics=[_pad_topic(w) for w in job["wallets"]])
            if last > job["done_to"]:
                job["found"] = sorted(set(job["found"]) | set(found))
                job["done_to"] = last
                statefile.atomic_write_json(self.cursor_path, self.cursor)
        todo = list(job["found"])
        dets = self.fetch_details(todo, deadline=t0 + bud) if todo else {}
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
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("inbox append 실패 — 새 지갑 백필 보류: %s", e)
                break
            self.emitted.add(h)
            sent.add(h)
        statefile.write_json_if_changed(self.meta_path, self.token_meta)
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        job["found"] = [h for h in job["found"] if h not in sent]
        span = max(1, job["to"] - job["lo"] + 1)
        self.progress.update(self.NEWW_KEY, phase="extend", unit="blocks", done=job["done_to"] - job["lo"] + 1,
                             total=span, pending_detail=len(job["found"]), range=[job["lo"], job["to"]],
                             note=f"새 지갑 {len(job['wallets'])}개", via=_bsc_via())
        if job["done_to"] >= job["to"] and not job["found"]:
            self.cursor["_wallets"] = sorted((set(known) | set(job["wallets"])) & cur)
            self.cursor.pop("_neww", None)
            self.progress.finish(self.NEWW_KEY, note=f"새 지갑 {len(job['wallets'])}개 이력 백필 완료 {span}블록")
            log.info("★BSC 나중 등록 지갑 이력 백필 완료 — %d개, %.0f분★", len(job["wallets"]), (time.time() - job["t0"]) / 60)
        statefile.atomic_write_json(self.cursor_path, self.cursor)

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
        statefile.write_json_if_changed(self.meta_path, self.token_meta)
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        return n


    XIN_HINT_TRIES = 24


    def _report(self, head: int, since: int, phase: str, note: str = None, flush: bool = False):
        start = self.cursor.get("_bf_start")
        if isinstance(start, int) and head > start:
            self.progress.update("bsc", phase=phase, unit="blocks", done=max(0, since - start),
                                 total=max(1, head - self.conf_depth - start), note=note, flush=flush,
                                 lag=max(0, head - self.conf_depth - since), scan=self.last_scan_metrics or None, lanes=None)
        else:
            self.progress.update("bsc", phase=phase, unit="blocks", lag=max(0, head - self.conf_depth - since),
                                 note=note, flush=flush, lanes=None)

    def _bsec(self) -> float:
        v = self.__dict__.get("_hb_bsec")
        try:
            v = float(v) if v else BSC_BLOCK_SEC
        except (TypeError, ValueError):
            v = BSC_BLOCK_SEC
        return min(10.0, max(0.05, v))

    def _seed_blocks(self) -> int:
        return max(100, int(LIVE_SEED_SEC / self._bsec()))

    def _lanes_on(self) -> bool:
        return getattr(self, "lanes_cfg", None) is not False

    def _side_budget(self, tc0: float) -> float:
        v = getattr(self, "lane_budget", None)
        if v is not None:
            return max(0.1, float(v))
        return max(10.0, min(float(getattr(self, "cycle_budget", 600)), float(getattr(self, "poll_sec", 60)) - (time.time() - tc0) - 5.0))

    def _side_left(self) -> float:
        tc0 = self.__dict__.get("_tc0")
        return self._side_budget(tc0) if tc0 else float(getattr(self, "cycle_budget", 600))

    def _set_fb(self, v: int):
        self.cursor["from_block"] = int(v)
        lv = self.cursor.get("_live")
        if isinstance(lv, dict):
            lv["fb"] = int(v)

    def _lane_open(self, safe: int, why: str) -> bool:
        if not self._lanes_on():
            return False
        fb = int(self.cursor.get("from_block") or 0)
        seed = self._seed_blocks()
        l0 = int(safe) - seed
        if fb <= 0 or l0 <= fb + seed:
            return False
        self.cursor["_live"] = {"done": l0, "holes": [[fb, l0]], "why": why, "at": int(time.time()), "start": fb, "fb": fb}
        self.cursor.pop("_lscan", None)
        log.info("★BSC 차선 시작(%s): 라이브 = 블록 %d 부터(확정 헤드 %d) · 옛 기록 = %d → %d 옆 차선(남는 예산)★", why, l0 + 1, safe, fb, l0)
        return True

    def _lane_norm(self) -> bool:
        lv = self.cursor.get("_live")
        if not isinstance(lv, dict):
            if self.cursor.pop("_lscan", None) is not None:
                statefile.atomic_write_json(self.cursor_path, self.cursor)
            return False
        fb = int(self.cursor.get("from_block") or 0)
        try:
            L = int(lv.get("done"))
            holes = sorted([int(a), int(b)] for a, b in (lv.get("holes") or []))
            fb_mine = int(lv.get("fb", fb))
        except (TypeError, ValueError):
            L, holes, fb_mine = None, [], fb
        if L is None or fb <= 0 or fb < fb_mine or not self._lanes_on():
            log.info("BSC 차선 기록 버림(%s) — from_block %d 부터 한 차선", "차선 끔" if not self._lanes_on() else "커서 되감김·기록 이상", fb)
            self.cursor.pop("_live", None)
            self.cursor["_lanes_seen"] = int(time.time())
            self.cursor.pop("_lscan", None)
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            return False
        out = []
        for a, b in holes:
            b = min(b, L)
            a = max(a, fb)
            if a < b:
                out.append([a, b])
        if not out or fb >= L:
            self._set_fb(max(fb, L))
            self.cursor.pop("_live", None)
            self.cursor["_lanes_seen"] = int(time.time())
            self.cursor.pop("_lscan", None)
            log.info("★BSC 옆 차선(옛 기록) 끝 — 한 차선으로 합침(from_block %d)★", int(self.cursor["from_block"]))
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            return False
        if out[0][0] > fb:
            self._set_fb(out[0][0])
        if out != holes or lv.get("fb") != int(self.cursor["from_block"]):
            lv["holes"] = out
            lv["fb"] = int(self.cursor["from_block"])
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        return True

    def _lane_scan(self, frm: int, to: int, ckey: str, head: int, budget: float, detail_deadline: float) -> tuple:
        sc = self.cursor.get(ckey)
        if isinstance(sc, dict) and int(sc.get("frm", -1)) == frm and int(sc.get("to", 0)) >= frm:
            found, last_done = set(sc.get("found") or []), int(sc["to"])
        else:
            res = self.discover(frm, to, budget_sec=budget)
            if res is None:
                return "none", frm - 1
            found, last_done = res
            if last_done < frm:
                return "none", frm - 1
            self.cursor[ckey] = {"frm": frm, "to": last_done, "found": sorted(h for h in found if h not in self.emitted)}
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        qset = bf_engine.quarantine_map(self.cursor)
        todo = [h for h in found if h not in self.emitted and h not in qset]
        dets = self.fetch_details(todo, deadline=detail_deadline) if todo else {}
        bad9 = [h for h in todo if not isinstance(dets.get(h), dict)]
        if bad9:
            gone9 = set(bad9) - set(self._detail_fail_note(bad9, dets))
            todo = [h for h in todo if h not in gone9]
        self._detail_fail_clear([h for h in todo if isinstance(dets.get(h), dict)])

        def _blk(h):
            v = dets.get(h)
            return (v["tx"]["block_number"], h) if isinstance(v, dict) else (1 << 62, h)
        ok = True
        for h in sorted(todo, key=_blk):
            snap = dets.get(h)
            if not isinstance(snap, dict):
                log.warning("detail %s 실패 — %s 체크포인트로 다음 사이클 상세만 재시도: %s", h[:12], ckey, str(snap)[:120])
                ok = False
                break
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time())})
                self.emitted.add(h)
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                ok = False
                break
        statefile.write_json_if_changed(self.meta_path, self.token_meta)
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if not ok:
            sc9 = self.cursor.get(ckey)
            if isinstance(sc9, dict):
                sc9["found"] = sorted(h for h in found if h not in self.emitted)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
            return "detail", frm - 1
        self.cursor.pop(ckey, None)
        return ("done" if last_done >= to else "part"), last_done

    def _lanes_cycle(self, head: int, safe: int, tc0: float):
        lv = self.cursor["_live"]
        L = int(lv["done"])
        if (safe - L) * self._bsec() > LANE_SPLIT_SEC:
            nl = int(safe) - self._seed_blocks()
            if nl > L:
                lv["holes"] = list(lv.get("holes") or []) + [[L, nl]]
                lv["done"] = L = nl
                self.cursor.pop("_lscan", None)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                log.info("BSC 라이브 차선이 크게 뒤 — 블록 %d 부터 다시(그 앞 %d블록은 옆 차선)", nl + 1, nl - int(lv["holes"][-1][0]))
        live_st, live_err = "done", None
        if L < safe:
            t0 = time.time()
            try:
                live_st, last = self._lane_scan(L + 1, safe, "_lscan", head, self.cycle_budget, t0 + self.cycle_budget + 300)
            except Exception as e:   # noqa: BLE001 [fallback]
                live_st, last, live_err = "none", L, e
            if last > L:
                lv["done"] = L = int(last)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
            if live_st in ("none", "detail") and live_err is None:
                live_err = RuntimeError("라이브 차선 " + ("상세 실패 — 체크포인트로 재시도" if live_st == "detail" else
                                                       "한 청크도 못 나감 — " + str((self.last_scan_metrics or {}).get("stop") or "노드 오류")))
        live_ok = live_st in ("done", "part")
        if live_ok:
            self.cursor["head"] = head
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        try:
            self._xin_pass(head)
        except Exception as e:  # noqa: BLE001 [optional]
            log.info("BSC 거래소 출금 txid 확인 실패(다음 기회): %s", logs.safe_err(e)[:120])
        if live_st == "done" and L >= safe:
            try:
                hl9 = [int(b9) for _a9, b9 in (self.cursor["_live"].get("holes") or [])]
                if hl9:
                    self._nonce_pass(head, lo_blk=max(hl9))
            except Exception as e:  # noqa: BLE001 [optional]
                log.info("BSC nonce 확인(라이브 범위) 실패(다음 기회): %s", logs.safe_err(e)[:120])
            try:
                self._balw_pass(head, L)
            except Exception as e:  # noqa: BLE001 [optional]
                log.info("BSC 잔고 감시 실패(다음 기회): %s", logs.safe_err(e)[:120])
        live_metrics = dict(self.last_scan_metrics or {})
        bk_st, bk_err, bk_adv = None, None, 0
        if self._lane_norm():
            fb = int(self.cursor["from_block"])
            hole_end = int(self.cursor["_live"]["holes"][0][1])
            bud = self._side_budget(tc0)
            try:
                bk_st, last = self._lane_scan(fb + 1, hole_end, "_scan", head, bud, time.time() + bud + 60)
                if last > fb:
                    bk_adv = int(last) - fb
                    self._set_fb(last)
                    statefile.atomic_write_json(self.cursor_path, self.cursor)
            except Exception as e:  # noqa: BLE001 [fallback]
                bk_st, bk_err = "none", e
                log.warning("BSC 옆 차선 실패(다음 사이클 이어서): %s", logs.redact_urls(logs.safe_err(e))[:160])
            self._lane_norm()
        lv = self.cursor.get("_live") if isinstance(self.cursor.get("_live"), dict) else None
        lanes = None
        if lv:
            holes = lv.get("holes") or []
            start = int(lv.get("start") or self.cursor.get("_bf_start") or self.cursor.get("from_block") or 0)
            miss = sum(max(0, int(b) - int(a)) for a, b in holes) + max(0, safe - int(lv["done"]))
            total = max(1, safe - start)
            stop = (self.last_scan_metrics or {}).get("stop") if bk_st != "done" else None
            lanes = {"why": lv.get("why"), "back_from": int(self.cursor.get("from_block") or 0), "back_to": int(holes[-1][1]) if holes else None,
                     "holes": len(holes), "live": int(lv["done"]), "advanced": bk_adv,
                     "stalled": bool(bk_st in ("none", "detail") or bk_err is not None),
                     "err": (logs.redact_urls(logs.safe_err(bk_err))[:160] if bk_err is not None else
                             (str(stop)[:160] if stop and bk_st in ("none", "detail") else None))}
            note = None if not lanes["stalled"] else "옛 기록 차선 멈춤 — " + str(lanes["err"] or "노드 오류")[:120]
            self.progress.update("bsc", phase="scan", unit="blocks", done=max(0, total - miss), total=total, note=note,
                                 lag=max(0, safe - int(lv["done"])), scan=live_metrics or None, lanes=lanes)
        else:
            self._report(head, int(self.cursor.get("from_block") or 0), "live" if live_st == "done" else "scan")
        self._health(head, L, live_ok, None if live_ok else live_err, extra={"lanes": lanes})

    def cycle(self):
        tc0 = self._tc0 = time.time()
        if self.cursor.pop("_synced_at", None) is not None:
            statefile.atomic_write_json(self.cursor_path, self.cursor)
        self._seed_wallet_set()
        self._df_seen = set()
        self._detail_home()
        head = self.head()
        try:
            self._quarantine_retry(head)
        except Exception as e:  # noqa: BLE001 [boundary]
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
            self._lane_open(safe, "new")
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.info("백필 시작: 블록 %d → %d (%d일, timestamp 탐색)",
                     since, safe, self.backfill_days)
        lanes9 = self._lane_norm()
        if not lanes9 and self._lanes_on() and (safe - int(self.cursor.get("from_block") or 0)) * self._bsec() > LANE_SPLIT_SEC:
            lanes9 = self._lane_open(safe, "lag")
            if lanes9:
                statefile.atomic_write_json(self.cursor_path, self.cursor)
        if lanes9:
            self._lanes_cycle(head, safe, tc0)
            return
        since = int(self.cursor.get("from_block", 0))
        if since >= safe:
            self._report(head, since, "live")
            self._health(head, since, True)
            self._extend(head)
            self._new_wallet_pass(head)
            self._nonce_pass(head)
            self._xin_pass(head)
            self._balw_safe(head, since)
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
            statefile.atomic_write_json(self.cursor_path, self.cursor)
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
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                ok = False
                break
        statefile.write_json_if_changed(self.meta_path, self.token_meta)
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if ok:
            self.cursor["from_block"] = safe
            self.cursor["head"] = head
            self.cursor.pop("_scan", None)
            if complete:
                self.cursor["_synced_at"] = int(time.time())
            else:
                self.cursor.pop("_synced_at", None)
                log.warning("부분 조회 %d→%d (확정 헤드 %d) — 커서 전진, 도장 보류", since, safe, safe0)
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            if found:
                log.info("사이클 완료: %d tx (블록 %d→%d, %.0f초)", len(found), since, safe, time.time() - t_cycle)
            self._report(head, safe, "live" if complete else "scan")
            self._health(head, safe, True)
            if complete:
                self._extend(head)
                self._new_wallet_pass(head)
                self._nonce_pass(head)
                self._xin_pass(head)
                self._balw_safe(head, safe)
        else:
            sc9 = self.cursor.get("_scan")
            if isinstance(sc9, dict):
                sc9["found"] = sorted(h for h in found if h not in self.emitted)
                statefile.atomic_write_json(self.cursor_path, self.cursor)
            self._report(head, since, "detail", note=f"상세 남음 {len(sc9.get('found') or []) if isinstance(sc9, dict) else '?'}건")
            self._health(head, since, False, RuntimeError("상세 실패 — 스캔 체크포인트로 재시도"))


def main():
    paths.ensure_dirs()
    cfg = config.load_config()
    bf_engine.configure(cfg)
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "bsc_rpc"]
    if not wallets:
        raise SystemExit("추적할 BSC 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("bsc", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(paths.INBOX_DIR, "bsc"))
    w = BscWatcher(cfg, wallets, writer)
    log.info("가동: %d지갑, %d초 주기, 백필 %d일", len(wallets), poll, w.backfill_days)
    while True:
        t0 = time.time()
        try:
            w.cycle()
        except Exception as e:  # noqa: BLE001 [fallback]
            n9 = bf_engine.health("bsc").fail("bsc", e, "bsc_rpc")
            bf_engine.health("bsc").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
