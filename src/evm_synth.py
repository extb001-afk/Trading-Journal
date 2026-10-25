import json
import random
import time
import chaincatalog, logs, net_http, statefile, textutil
import bf_engine, evm_reorg
from evm_base import UA
import logging

log = logging.getLogger('tj-evm')

class RpcSynthMixin:

    TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    WETH_DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
    WETH_WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
    ZERO_ADDR = "0x0000000000000000000000000000000000000000"
    RPC_DEFAULT = {
        "base": ["https://mainnet.base.org", "https://base.drpc.org", "https://gateway.tenderly.co/public/base"],
        "optimism": ["https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "eth": ["https://eth.drpc.org", "https://ethereum-rpc.publicnode.com"],
        "arbitrum": ["https://arb1.arbitrum.io/rpc"],
        "polygon": ["https://polygon.drpc.org", "https://polygon-bor-rpc.publicnode.com", "https://gateway.tenderly.co/public/polygon"],
        "gnosis": ["https://rpc.gnosischain.com"],
        "scroll": ["https://rpc.scroll.io"],
        "zksync": ["https://mainnet.era.zksync.io"],
        "robinhood": ["https://rpc.mainnet.chain.robinhood.com"],
        "arc": ["https://rpc.mainnet.arc.io", "https://rpc.quicknode.mainnet.arc.io"],
    }

    NATIVE_EMITTER = {"arc": "0xfffffffffffffffffffffffffffffffffffffffe",
                      **{c9: z9[0] for c9, z9 in chaincatalog.ZK_STACK.items()}}
    NATIVE_FEE_SINK = {c9: z9[1] for c9, z9 in chaincatalog.ZK_STACK.items()}
    NATIVE_MIRROR = {c9: frozenset(({chaincatalog.NATIVE_MIRROR[c9][0]} if c9 in chaincatalog.NATIVE_MIRROR else set())
                                   | ({chaincatalog.NATIVE_ALIAS_TOKEN[c9]} if c9 in chaincatalog.NATIVE_ALIAS_TOKEN else set()))
                     for c9 in sorted(set(chaincatalog.NATIVE_MIRROR) | set(chaincatalog.NATIVE_ALIAS_TOKEN))}
    NATIVE_MIRROR_SRC = {k9: v9 for k9, v9 in chaincatalog.NATIVE_MIRROR.items() if k9 != "arc"}

    SYNTH_TRIP_BASE = 15.0
    SYNTH_TRIP_RATE = 60.0
    SYNTH_TRIP_MAX = 900.0

    def _synth_ep(self, url: str) -> dict:
        eps = getattr(self, "_synth_eps", None)
        if eps is None:
            eps = self._synth_eps = {}
        return eps.setdefault(url, {"fail_until": 0.0, "streak": 0})

    @staticmethod
    def rpc_deferred(e) -> bool:
        seen = set()
        while isinstance(e, BaseException) and id(e) not in seen:
            seen.add(id(e))
            if isinstance(e, bf_engine.NetError) and getattr(e, "kind", None) in ("quota", "budget", "circuit"):
                return True
            e = e.__cause__
        return False

    def synth_fail_count(self, counts: dict, h: str, err):
        if self.rpc_deferred(err):
            return None
        counts[h] = int(counts.get(h, 0)) + 1
        return counts[h]

    def _synth_trip(self, url: str, e: Exception):
        st = self._synth_ep(url)
        st["deferred"] = e if self.rpc_deferred(e) else None
        msg = str(e)
        ratelike = ("429" in msg or "Too Many" in msg or "rate limit" in msg.lower()
                    or "-32016" in msg or "403" in msg)
        base = self.SYNTH_TRIP_RATE if ratelike else self.SYNTH_TRIP_BASE
        wait = min(base * (2 ** min(st["streak"], 5)), self.SYNTH_TRIP_MAX) * (1.0 + random.random() * 0.5)
        st["fail_until"] = time.time() + wait
        st["streak"] += 1
        log.warning("%s rpc 엔드포인트 쿨다운 %.0fs (%d연속): %s — %s", self.chain, wait, st["streak"],
                    logs.redact_urls(url), logs.redact_urls(msg)[:80])

    def _rpc_call(self, method: str, params: list):
        rpcs = self.cfg_rpcs or self.RPC_DEFAULT.get(self.chain) or []
        now = time.time()
        ready = [u for u in rpcs if self._synth_ep(u)["fail_until"] <= now]
        order = ready if ready else list(rpcs)
        last = None
        for url in order:
            try:
                d = bf_engine.http_json(
                    url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                    headers={"User-Agent": net_http.ua_for(url, UA)}, timeout=15, retries=1, rpc_methods=(method,))
                if not isinstance(d, dict):
                    raise RuntimeError(f"rpc {method}: 응답 형식 오류 ({type(d).__name__})")
                if d.get("error"):
                    raise RuntimeError(f"rpc {method}: {logs.redact_secret_text(str(d['error']))[:160]}")
                self._synth_ep(url)["streak"] = 0
                self._synth_ep(url)["deferred"] = None
                if d.get("result") is not None:
                    return d["result"]
                last = RuntimeError("result null")
            except Exception as e:  # noqa: BLE001 [fallback]
                last = e
                self._synth_trip(url, e)
        for url in rpcs:
            d9 = self._synth_ep(url).get("deferred")
            if d9 is not None:
                raise bf_engine.NetError(f"보류(게이트·장부): {logs.redact_urls(str(d9))[:160]}", getattr(d9, "kind", None) or "circuit",
                                         host=getattr(d9, "host", None))
        raise last if last else RuntimeError("rpc 미구성")

    def _ref_head(self):
        try:
            return int(self._rpc_call("eth_blockNumber", []), 16)
        except Exception:  # noqa: BLE001 [fallback]
            return None

    def _block_sec_est(self, head: int) -> float:
        now = time.time()
        prev = getattr(self, "_hb_prev", None)
        est = getattr(self, "_hb_bsec", None)
        if prev and head > prev[0] and now > prev[1]:
            v = (now - prev[1]) / float(head - prev[0])
            est = v if est is None else 0.7 * est + 0.3 * v
            self._hb_bsec = est
        if not prev or head != prev[0]:
            self._hb_prev = (head, now)
            self._hb_head_changed = now
        return est

    def _health_cycle(self, kind: str, head: int, safe: int, ok: bool, err=None, **extra):
        hb = bf_engine.health("evm")
        tb9 = getattr(self, "_tier", None)
        curs = [v for k, v in self.cursor.items() if not k.startswith("_") and isinstance(v, int)
                and not (tb9 is not None and tb9.is_resting(k))]
        cmin = min(curs) if curs else None
        bsec = self._block_sec_est(head) if head else None
        ref = None if extra.get("tier_idle") else self._ref_head()
        facts = dict(head=head, head_ts=getattr(self, "_head_ts", None), ref_head=ref,
                     ref_gap_blocks=(ref - head) if (ref is not None and head) else None,
                     head_unchanged_sec=int(time.time() - getattr(self, "_hb_head_changed", time.time())),
                     cursor=cmin, lag_blocks=(safe - cmin) if (cmin is not None and safe) else None,
                     block_sec_est=round(bsec, 3) if bsec else None,
                     lag_sec=int((safe - cmin) * bsec) if (cmin is not None and safe and bsec) else None,
                     synced_at=self.cursor.get("_synced_at"), wallets=len(self.wallets),
                     wallets_backfilling=sum(1 for w in self.wallets if not isinstance(self.cursor.get(w), int)),
                     backfilling_ids=[w[:6] for w in self.wallets if not isinstance(self.cursor.get(w), int)][:3],
                     wallets_resting=sum(1 for w in self.wallets if tb9 is not None and tb9.is_resting(w)),
                     **evm_reorg.hb_fact(self.cursor),
                     **extra)
        if ok:
            hb.ok(self.chain, kind, **facts)
        else:
            hb.fail(self.chain, err or RuntimeError("부분 실패"), kind, **facts)
        hb.flush()

    def _block_ts(self, blk: int) -> int:
        b = self._rpc_call("eth_getBlockByNumber", [hex(int(blk)), False]) or {}
        if not b.get("timestamp"):
            raise RuntimeError(f"블록 {blk} 시각 미확보")
        return int(b["timestamp"], 16)

    def window_start_block(self, safe_now: int, months: float, bpd: int) -> int:
        target = int(time.time() - months * 30 * 86400)
        try:
            b = bf_engine.block_at_ts(self._block_ts, target, 0, int(safe_now))
            log.info("%s 백필 창 시작 = 블록 %d (타임스탬프 탐색, bpd 가정치 %d 대비 %+d블록)", self.chain, b,
                     max(0, safe_now - int(months * 30 * bpd)), b - max(0, safe_now - int(months * 30 * bpd)))
            return b
        except Exception as e:  # noqa: BLE001 [fallback]
            b = max(0, safe_now - int(months * 30 * bpd))
            log.warning("%s 창 시작 타임스탬프 탐색 실패 → blocks_per_day 환산 %d 로 폴백: %s", self.chain, b, e)
            return b

    def _nodec_reg(self):
        return bf_engine.nodec_registry(self.chain, log)

    def _rpc_token_dec(self, ca: str) -> int:
        m = self.rpc_meta.get(ca)
        if m is not None:
            return int(m)
        reg = self._nodec_reg()
        if reg.perm(ca):
            raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}")
        try:
            r = self._rpc_call("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
        except Exception as e:
            if bf_engine.revert_like(e) and reg.bad(ca, "revert: " + logs.safe_err(e)[:80]):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {logs.safe_err(e)[:80]}") from e
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: {e}") from e
        dec, why = bf_engine.decimals_from_result(r)
        if dec is None:
            if reg.bad(ca, why):
                raise bf_engine.TokenNoDecimals(f"token decimals 영구 불능 {ca[:10]}: {why}")
            raise RuntimeError(f"token decimals 조회 실패 {ca[:10]}: decimals() {why}")
        reg.ok(ca)
        self.rpc_meta[ca] = dec
        statefile.atomic_write_json(self.rpc_meta_path, self.rpc_meta)
        return dec

    @staticmethod
    def opstack_normalize(tx: dict, rc: dict):
        fee = int(rc["gasUsed"], 16) * int(rc.get("effectiveGasPrice") or
                                           tx.get("gasPrice") or "0x0", 16)
        fee += int(rc.get("l1Fee") or "0x0", 16)
        typ_raw = tx.get("type")
        try:
            typ = int(typ_raw, 16) if isinstance(typ_raw, str) else (
                int(typ_raw) if typ_raw is not None else None)
        except (TypeError, ValueError):
            typ = None
        if typ == 3:
            if rc.get("blobGasUsed") is None or rc.get("blobGasPrice") is None:
                raise ValueError("blob tx(type 3) 영수증에 blobGasUsed·blobGasPrice 없음 — 수수료 추정 안 함(결정적 상세 실패 규약)")
            fee += int(rc["blobGasUsed"], 16) * int(rc["blobGasPrice"], 16)
        if rc.get("operatorFee") is not None:
            fee += int(rc["operatorFee"], 16)
        elif rc.get("operatorFeeScalar") is not None or rc.get("operatorFeeConstant") is not None:
            g9 = int(rc["gasUsed"], 16) * int(rc.get("operatorFeeScalar") or "0x0", 16)
            fee += (g9 * 100 if rc.get("daFootprintGasScalar") is not None else g9 // 1_000_000) + int(rc.get("operatorFeeConstant") or "0x0", 16)
        mint = None
        if typ == 126:
            try:
                m = int(tx.get("mint") or "0x0", 16)
            except (TypeError, ValueError):
                m = 0
            if m > 0:
                mint = str(m)
        return fee, typ, mint

    @staticmethod
    def _ord_li(leg: dict, lg: dict) -> None:
        li9 = bf_engine.ord_index(lg.get("logIndex"))
        if li9 is not None:
            leg["log_index"] = li9

    def _wrap_legs(self, logs: list, tts: list, myset: set) -> list:
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        if not wr:
            return []
        cover = {}
        for t in tts:
            if str(((t.get("token") or {}).get("address")) or "").lower() == wr and (t.get("token") or {}).get("type", "ERC-20") == "ERC-20":
                k = (str(t.get("from") or "").lower(), str(t.get("to") or "").lower(), str((t.get("total") or {}).get("value")))
                cover[k] = cover.get(k, 0) + 1
        out = []
        for lg in logs:
            tps = lg.get("topics") or []
            if len(tps) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tps[0] or "").lower()
            if t0 not in (self.WETH_DEPOSIT, self.WETH_WITHDRAWAL):
                continue
            who = ("0x" + str(tps[1])[-40:]).lower()
            if who not in myset:
                continue
            try:
                v = int(lg.get("data") or "0x", 16)
            except ValueError:
                continue
            if not v:
                continue
            fr, to = (self.ZERO_ADDR, who) if t0 == self.WETH_DEPOSIT else (who, self.ZERO_ADDR)
            k = (fr, to, str(v))
            if cover.get(k):
                cover[k] -= 1
                continue
            out.append({"from": fr, "to": to,
                        "token": {"address": wr, "symbol": None, "type": "ERC-20", "decimals": self._rpc_token_dec(wr)},
                        "total": {"value": str(v)}})
            self._ord_li(out[-1], lg)
        return out

    SELL_HINTS = False

    def _sell_wd_hint(self, tx: dict, rc: dict, tts: list, myset: set):
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        f = str(tx.get("from") or "").lower()
        if not wr or f not in myset or rc.get("status") != "0x1":
            return None
        try:
            if int(tx.get("value") or "0x0", 16):
                return None
        except (TypeError, ValueError):
            return None
        if any(str(t.get("to") or "").lower() in myset for t in tts) or not any(str(t.get("from") or "").lower() == f for t in tts):
            return None
        wd = dep = 0
        src = None
        for lg in rc.get("logs") or []:
            tps = lg.get("topics") or []
            if len(tps) != 2 or (lg.get("address") or "").lower() != wr:
                continue
            t0 = (tps[0] or "").lower()
            who = ("0x" + str(tps[1])[-40:]).lower()
            if who in myset or t0 not in (self.WETH_DEPOSIT, self.WETH_WITHDRAWAL):
                continue
            try:
                v = int(lg.get("data") or "0x", 16)
            except ValueError:
                continue
            if t0 == self.WETH_WITHDRAWAL:
                wd += v
                src = src or who
            else:
                dep += v
        return (f, src, wd - dep) if src and wd - dep > 0 else None

    def _rpc_synth_detail(self, h: str) -> dict:
        tx = self._rpc_call("eth_getTransactionByHash", [h])
        rc = self._rpc_call("eth_getTransactionReceipt", [h])
        if not tx or not rc or rc.get("blockNumber") is None:
            raise RuntimeError("rpc 미확정 tx")
        blk = int(rc["blockNumber"], 16)
        blkinfo = self._rpc_call("eth_getBlockByNumber", [rc["blockNumber"], False]) or {}
        if not blkinfo.get("timestamp"):
            raise RuntimeError("블록 시각 미확보")
        ts9 = int(blkinfo["timestamp"], 16)
        if rc.get("gasUsed") is None:
            raise RuntimeError("영수증 gasUsed 미확보")
        fee, typ, mint = self.opstack_normalize(tx, rc)
        myset = set(self.wallets)
        tts = []
        emitter = self.NATIVE_EMITTER.get(self.chain)
        mirror = self.NATIVE_MIRROR.get(self.chain) or frozenset()
        msrc = None if emitter else self.NATIVE_MIRROR_SRC.get(self.chain)
        sink = self.NATIVE_FEE_SINK.get(self.chain) if emitter else None
        f_tx = (tx.get("from") or "").lower()
        fee_paid = fee_back = 0
        fee_seen = False
        nat_logs = []
        for lg in rc.get("logs") or []:
            tps = lg.get("topics") or []
            if len(tps) == 4 and (tps[0] or "").lower() == self.TRANSFER_TOPIC:
                fr7, to7 = ("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower()
                if fr7 in myset or to7 in myset:
                    try:
                        tid7 = int(tps[3], 16)
                    except (TypeError, ValueError):
                        continue
                    tts.append({"from": fr7, "to": to7, "token": {"address": (lg.get("address") or "").lower(), "symbol": None,
                                                                   "type": "ERC-721", "decimals": None},
                                "total": {"token_id": str(tid7), "decimals": None, "value": None}})
                    self._ord_li(tts[-1], lg)
                continue
            if len(tps) != 3 or (tps[0] or "").lower() != self.TRANSFER_TOPIC:
                continue
            ca0 = (lg.get("address") or "").lower()
            if ca0 in mirror:
                if msrc and ca0 == msrc[0]:
                    try:
                        v0 = int(lg.get("data") or "0x", 16)
                    except ValueError:
                        continue
                    if v0:
                        nat_logs.append((("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower(), v0 * int(msrc[1])))
                continue
            if emitter and ca0 == emitter:
                try:
                    v0 = int(lg.get("data") or "0x", 16)
                except ValueError:
                    continue
                f0, t0 = ("0x" + tps[1][-40:]).lower(), ("0x" + tps[2][-40:]).lower()
                if sink and sink in (f0, t0):
                    fee_seen = True
                    if f0 == f_tx and t0 == sink:
                        fee_paid += v0
                        continue
                    if f0 == sink and t0 == f_tx:
                        fee_back += v0
                        continue
                if v0:
                    nat_logs.append((f0, t0, v0))
                continue
            data = lg.get("data") or "0x"
            try:
                v = textutil.log_word0(data)
            except ValueError:
                continue
            if not v:
                continue
            fr = ("0x" + tps[1][-40:]).lower()
            to = ("0x" + tps[2][-40:]).lower()
            if fr not in myset and to not in myset:
                continue
            ca = (lg.get("address") or "").lower()
            try:
                dec9 = self._rpc_token_dec(ca)
            except bf_engine.TokenNoDecimals:
                self._nodec_reg().skip(h, ca, fr, to, v)
                continue
            tts.append({"from": fr, "to": to,
                        "token": {"address": ca, "symbol": None, "type": "ERC-20",
                                  "decimals": dec9},
                        "total": {"value": str(v)}})
            self._ord_li(tts[-1], lg)
        tts.extend(self._wrap_legs(rc.get("logs") or [], tts, myset))
        if getattr(self, "SELL_HINTS", False) and not emitter and not msrc:
            hint9 = self._sell_wd_hint(tx, rc, tts, myset)
            hd9 = self.__dict__.setdefault("_sell_wd", {})
            if hint9:
                if len(hd9) > 20000:
                    hd9.clear()
                hd9[h.lower()] = hint9
            else:
                hd9.pop(h.lower(), None)
        internal = []
        if emitter or msrc:
            v_top = int(tx.get("value", "0x0"), 16)
            f_top = (tx.get("from") or "").lower()
            t_top = (tx.get("to") or rc.get("contractAddress") or "").lower()
            skip = v_top > 0
            sc9 = int(msrc[1]) if msrc else 1
            for f0, t0, v0 in nat_logs:
                if skip and (f0, t0) == (f_top, t_top) and (v0 == v_top or (msrc and v0 == (v_top // sc9) * sc9)):
                    skip = False
                    continue
                if f0 in myset or t0 in myset:
                    internal.append({"from": f0, "to": t0, "value": str(v0), "success": True})
        if sink and fee_seen:
            if fee_paid or fee_back:
                if fee_paid >= fee_back:
                    fee = fee_paid - fee_back
            else:
                fee = 0
        snap_tx = {"hash": h, "from": tx.get("from"), "to": tx.get("to"),
                   "value": str(int(tx.get("value", "0x0"), 16)),
                   "fee": {"value": str(fee)},
                   "status": "ok" if rc.get("status") == "0x1" else "error",
                   "raw_input": tx.get("input") or "0x",
                   "timestamp": ts9, "block_number": blk,
                   "block_hash": rc.get("blockHash"), "synth": "rpc"}
        pos9 = bf_engine.tx_position(tx, rc)
        if pos9 is not None:
            snap_tx["position"] = pos9
        if typ is not None:
            snap_tx["type"] = typ
        if typ == 126:
            snap_tx["op_mint"] = mint or "0"
        if emitter:
            return {"tx": snap_tx, "token_transfers": tts, "internal": internal, "internal_note": "zk_base_token" if sink else "eip7708"}
        if msrc:
            return {"tx": snap_tx, "token_transfers": tts, "internal": internal, "internal_note": "native_mirror"}
        return {"tx": snap_tx, "token_transfers": tts, "internal": []}


BS_DEC_RETRY_SEC = 600


def _leg_addr(x) -> str:
    return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()


def bs_dec_fill(w: "RpcSynthMixin", snapshot: dict) -> dict:
    my = set(w.wallets)
    missed = w.__dict__.setdefault("_bs_dec_missed", {})
    for tt in (snapshot.get("token_transfers") or []) if isinstance(snapshot, dict) else ():
        tok = tt.get("token") if isinstance(tt, dict) else None
        if not isinstance(tok, dict) or tok.get("decimals") is not None or (tok.get("type") or "ERC-20") != "ERC-20":
            continue
        if _leg_addr(tt.get("from")) not in my and _leg_addr(tt.get("to")) not in my:
            continue
        try:
            if not int((tt.get("total") or {}).get("value") or 0):
                continue
        except (TypeError, ValueError):
            continue
        ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
        if not ca or time.time() - missed.get(ca, 0) < BS_DEC_RETRY_SEC:
            continue
        try:
            tok["decimals"] = w._rpc_token_dec(ca)
        except Exception as e:  # noqa: BLE001 [fallback]
            missed[ca] = time.time()
            log.info("%s 토큰 %s 자릿수 미상(블록스카웃 null · RPC %s) — 그대로 보냄", w.chain, ca[:10], logs.safe_err(e)[:80])
    return snapshot
