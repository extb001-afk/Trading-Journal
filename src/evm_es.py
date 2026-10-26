import hashlib
import json
import time
import re
import urllib.request
import evm_reorg, logs, paths, statefile
import lpdec
import bf_engine
import tsfix
import addr_tier
from evm_base import ChainDisabled
from evm_base import ES_FAIL_ISOLATE_SEC
from evm_base import ES_Q_TTL
from evm_base import EtherscanDailyLimit
from evm_base import EtherscanKeyError
from evm_base import EtherscanPaced
from evm_base import _ES_Q
from evm_base import _ES_Q_LOCK
from evm_base import _ES_WMEM
from evm_base import _revoke_stamp_disk
from evm_base import es_daily_left
from evm_base import es_daily_trip
from evm_base import es_is_daily_limit
from evm_base import http_json
from evm_base import new_view_wallets
from evm_base import rpc_handback
from evm_synth import RpcSynthMixin
import logging

log = logging.getLogger('tj-evm')

class EtherscanWatcher(RpcSynthMixin):

    ES_API = "https://api.etherscan.io/v2/api"
    PAGE = 1000
    ES_ROW_FLOOR = 1000

    def __init__(self, cfg: dict, chain: str, wallets: list, writer, chainid: int, key: str):
        self.chain = chain
        self.cid = chainid
        self.key = key
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.cfg_rpcs = cfg["chains"][chain].get("rpcs")
        self.rpc_meta_path = paths.state(f"rpc_token_meta_{chain}.json")
        self.rpc_meta = statefile.read_json(self.rpc_meta_path, {})
        chain_cc = cfg["chains"][chain]
        self.conf_depth = int(chain_cc.get("conf_depth", 12))
        self.backfill = bool(cfg.get("backfill_full_history"))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.bpd = int(cfg["chains"][chain].get("blocks_per_day", 7200))
        try:
            self.page = max(100, int(((cfg.get("etherscan") or {}).get("page_rows")) or self.PAGE))
        except (TypeError, ValueError):
            self.page = self.PAGE
        try:
            self.INT_LAG_SEC = max(60, int(((cfg.get("etherscan") or {}).get("int_lag_sec")) or EtherscanWatcher.INT_LAG_SEC))
        except (TypeError, ValueError):
            pass
        self.wallets = [w.lower() for w in wallets]
        self.wallet_since = bf_engine.wallet_since_map(cfg, chain)
        self.writer = writer
        self.cursor_path = paths.state(f"cursor_evm_{chain}.json")
        self.cursor = statefile.read_json(self.cursor_path, {})
        if self.cursor.get("_rpc_v") is not None:
            rpc_handback(self, "etherscan")
        evm_reorg.ack_start(self, chain_cc)
        self.emitted_path = paths.state(f"emitted_evm_{chain}.json")
        self.emitted = set(statefile.read_json(self.emitted_path, []))
        new_view_wallets(self)
        self.pending_detail = {}
        self.progress = bf_engine.progress("evm")
        self._tier = addr_tier.evm_book(self, cfg, "etherscan")

    ES_RETRY = 4
    INT_LAG_SEC = 21600

    def _es_get(self, params: dict):
        left = es_daily_left()
        if left > 0:
            raise EtherscanDailyLimit(f"etherscan 하루 한도 쉼 창 — {left / 60:.0f}분 뒤 재시도")
        k9 = getattr(self, "_es_kind", "head")
        if not bf_engine.es_budget_take("evm", kind=k9):
            if bf_engine.es_budget_why() == "pace":
                raise EtherscanPaced(f"이더스캔 하루 예산 페이싱({getattr(self, '_es_kind', 'head')}) — 잠시 쉬고 다음 주기에 이어 받음")
            used9, cap9 = bf_engine.es_budget_used()
            msg9 = f"로컬 하루 예산 도달 {used9}/{cap9} (공표 한도 80% 규칙) — day/limit"
            es_daily_trip(msg9)
            raise EtherscanDailyLimit(f"etherscan {msg9}")
        if k9 == "head":
            self._es_hspent = getattr(self, "_es_hspent", 0) + 1
        try:
            d = http_json(self.ES_API + "?" + urllib.parse.urlencode(params), retries=1)
        except bf_engine.NetError as e:
            if es_is_daily_limit(e):
                es_daily_trip(str(e))
                raise EtherscanDailyLimit(f"etherscan 하루 한도: {str(e)[:120]}") from e
            raise
        if isinstance(d, dict):
            res9 = d.get("result")
            if (isinstance(res9, str) and es_is_daily_limit(res9)) or \
                    (d.get("status") == "0" and es_is_daily_limit(d.get("message"))):
                es_daily_trip(res9 if isinstance(res9, str) else d.get("message"))
                raise EtherscanDailyLimit(f"etherscan 하루 한도: {str(res9)[:120]}")
        return d

    ES_NET_RETRY = 2

    def _es_get_retry(self, params: dict):
        for i in range(self.ES_NET_RETRY):
            try:
                return self._es_get(params)
            except bf_engine.NetError as e:
                if isinstance(e, bf_engine.CircuitOpen) or e.kind not in bf_engine.RETRYABLE or e.kind == "quota" \
                        or i + 1 >= self.ES_NET_RETRY:
                    raise
                wait = e.retry_after if (e.kind == "http429" and e.retry_after is not None) else bf_engine._backoff(i)
                time.sleep(min(float(wait), 20.0))

    def _es(self, params: dict):
        params = dict(params, chainid=self.cid, apikey=self.key)
        last = None
        for i in range(self.ES_RETRY):
            d = self._es_get_retry(params)
            if not isinstance(d, dict):
                raise RuntimeError("etherscan 응답 형식 오류")
            if str(d.get("status")) not in ("0", "1"):
                raise RuntimeError("etherscan 응답 상태 오류")
            if d.get("status") == "0" and d.get("message") not in ("No transactions found",
                                                                  "No records found"):
                res = d.get("result")
                if "api key" in str(res).lower():
                    raise EtherscanKeyError(f"etherscan 키 거부: {res}")
                low = str(res).lower()
                if res is None or "rate limit" in low or "max calls" in low or "timeout" in low \
                        or "busy" in low or "try again" in low:
                    last = RuntimeError(f"etherscan 오류: {res}")
                    bf_engine._stat("api.etherscan.io", "es_retry")
                    time.sleep(bf_engine._backoff(i, base=1.5, cap=12.0) + 0.5)
                    continue
                raise RuntimeError(f"etherscan 오류: {res}")
            if str(d.get("status")) == "0":
                return []
            return d.get("result")
        raise last if last else RuntimeError("etherscan 재시도 소진")

    def head_block(self) -> int:
        d = self._es_get_retry({"chainid": self.cid, "module": "proxy", "action": "eth_blockNumber",
                                "apikey": self.key})
        if not isinstance(d, dict) or not isinstance(d.get("result"), str) or not d["result"].startswith("0x"):
            res9 = (d or {}).get("result") if isinstance(d, dict) else d
            if "api key" in str(res9).lower():
                raise EtherscanKeyError(f"etherscan 키 거부: {res9}")
            raise RuntimeError(f"etherscan head 응답 오류: {str(res9)[:80]}")
        head = int(d["result"], 16)
        mx = getattr(self, "_max_head", 0)
        if mx and head < mx - max(64, self.conf_depth):
            raise bf_engine.NetError(f"etherscan 헤드 역행 {head} < 관측 최대 {mx}", "stale_head")
        self._max_head = max(mx, head)
        return head

    def window_start_block(self, safe_now: int, months: float, bpd: int) -> int:
        target = int(time.time() - months * 30 * 86400)
        try:
            r = self._es({"module": "block", "action": "getblocknobytime", "timestamp": target,
                          "closest": "before"})
            b = int(r)
            if 0 <= b <= safe_now:
                log.info("%s 백필 창 시작 = 블록 %d (이더스캔 getblocknobytime, bpd 가정치 대비 %+d블록)", self.chain,
                         b, b - max(0, safe_now - int(months * 30 * bpd)))
                return b
        except (EtherscanKeyError, EtherscanPaced):
            raise
        except Exception as e:  # noqa: BLE001 [optional]
            log.warning("%s getblocknobytime 실패 → RPC 탐색: %s", self.chain, str(e)[:100])
        return RpcSynthMixin.window_start_block(self, safe_now, months, bpd)

    def _block_by_ts(self, ts: int) -> int:
        try:
            b = int(self._es({"module": "block", "action": "getblocknobytime", "timestamp": int(ts), "closest": "before"}))
            if b >= 0:
                return b
        except (EtherscanKeyError, EtherscanPaced):
            raise
        except Exception:  # noqa: BLE001 [optional]
            pass
        return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(getattr(self, "_max_head", 0) or self.head_block()))

    def _ext_block_at(self, ts: int, head: int) -> int:
        try:
            return self._block_by_ts(ts)
        except EtherscanPaced as e:
            try:
                return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(head))
            except Exception as e9:   # noqa: BLE001
                bf_engine.es_pace_room("fill")
                raise EtherscanPaced(f"확장 목표 블록 — 이더스캔 몫 막힘 · RPC 탐색 실패({str(e9)[:80]}) — 옛 기록 수요만 등록") from e

    ES_EXT_SLICES = 4
    ES_EXT_WORKERS = 3

    def _es_extend(self, head: int):
        target = bf_engine.SINCE.target(self.chain)
        if not target:
            return
        self._es_kind = "aux"
        tb = getattr(self, "_ext_tb", None)
        if not tb or tb[0] != target:
            b9 = addr_tier._ext_tb_of(self, "etherscan", target)
            tb = self._ext_tb = (target, b9 if b9 is not None else self._ext_block_at(target, head))
        tblk = tb[1]
        need = {}
        hint = bf_engine.SINCE.covered_hint(self.chain)
        hb9 = getattr(self, "_ext_hint", None)
        if hint and (not hb9 or hb9[0] != hint):
            hb9 = self._ext_hint = (hint, self._ext_block_at(hint, head))
        hint_blk = hb9[1] if hint else None
        for w in self.wallets:
            if not isinstance(self.cursor.get(w), int):
                continue
            c = self.cursor.get("_cov:" + w)
            if not isinstance(c, int):
                c = min(hint_blk, int(self.cursor[w])) if hint_blk else int(self.cursor[w])
            if c > tblk + 1:
                need[w] = c
        if not need:
            return
        t0 = time.time()
        tasks = []
        _mg9 = lpdec.lp_managers(paths.BASE_DIR).get(self.chain) or {}
        acts9 = ("txlist", "tokentx", "txlistinternal") + (("tokennfttx",) if _mg9 else ())
        for w, c in need.items():
            lo, hi = tblk + 1, c
            step = max(1, (hi - lo + 1) // self.ES_EXT_SLICES + 1)
            for a in range(lo, hi + 1, step):
                for act in acts9:
                    tasks.append((w, act, a, min(hi, a + step - 1)))
        room9 = bf_engine.es_pace_room("fill")
        if room9 < len(tasks) * 2:
            if time.time() - getattr(self, "_ext_room_log", 0) >= 1800:
                self._ext_room_log = time.time()
                log.info("%s 과거 창 확장 대기 — 하루 예산 페이싱(채우기 몫 %d < 필요 %d) · 몫이 차면 이어서", self.chain, max(0, room9), len(tasks) * 2)
            self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=0, total=len(tasks),
                                 target=time.strftime("%Y-%m-%d", time.gmtime(target)), since_block=tblk, wallets=len(need), paced=True,
                                 paced_at=int(time.time()))
            return
        self._es_kind = "fill"
        res = {}
        self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=0, total=len(tasks),
                             target=time.strftime("%Y-%m-%d", time.gmtime(target)), since_block=tblk, wallets=len(need), flush=True)
        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=self.ES_EXT_WORKERS) as ex9:
            futs = {ex9.submit(self._list_all, act, w, a, b): (w, act, a) for (w, act, a, b) in tasks}
            for fu, key in futs.items():
                try:
                    res[key] = fu.result()
                except EtherscanKeyError:
                    raise
                except EtherscanPaced as e:
                    res[key] = e
                except Exception as e:  # noqa: BLE001 [fallback]
                    res[key] = e
        errs = [k for k, v in res.items() if isinstance(v, Exception)]
        self.progress.update(f"{self.chain}:extend", phase="extend", unit="tasks", done=len(tasks) - len(errs),
                             total=len(tasks), target=time.strftime("%Y-%m-%d", time.gmtime(target)),
                             since_block=tblk, wallets=len(need), errors={"task_fail": len(errs)} if errs else None)
        if errs:
            log.info("%s 확장 조회 %d/%d 조각 실패 — 다음 사이클 재시도: %s", self.chain, len(errs), len(tasks),
                     str(res[errs[0]])[:120])
            return
        per_wallet = {}
        for w in need:
            parts = {act: [] for act in acts9}
            for (w2, act, a), rows in sorted(res.items(), key=lambda kv: kv[0][2]):
                if w2 == w:
                    parts[act].extend(rows)
            nft9 = [r9 for r9 in parts.get("tokennfttx", []) if str(r9.get("contractAddress") or "").lower() in _mg9]
            per_wallet[w] = (parts["txlist"], parts["tokentx"] + nft9, parts["txlistinternal"])
        merged = self.merge_wallet_rows(per_wallet)
        n_emit = 0
        for h in sorted(merged, key=lambda x: (self._ent_block(merged[x]) or 0, x)):
            ent = merged[h]
            snap = self._snapshot(ent)
            if snap is None or not self._ent_block(ent):
                log.warning("%s 확장 %s 파싱 불능 — 커버 하한 보류", self.chain, h[:12])
                statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
                return
            rec9 = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap,
                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time())}
            if h in self.emitted:
                rec9["repair"] = "leg_union"
            self.writer.append(rec9)
            self.emitted.add(h)
            n_emit += 1
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        for w in need:
            self.cursor["_cov:" + w] = int(tblk)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        self.progress.finish(f"{self.chain}:extend", note=f"확장 {len(need)}지갑 {n_emit}tx {time.time() - t0:.0f}초")
        log.info("★%s 과거 창 확장 완료 [etherscan]: 지갑 %d, 방출 %d, 조각 %d, %.0f초 → 하한 블록 %d★", self.chain,
                 len(need), n_emit, len(tasks), time.time() - t0, tblk)

    def _list_all(self, action: str, wallet: str, frm: int, to: int) -> list:
        out = []
        seen = {}
        start = frm
        while True:
            page9 = int(getattr(self, "page", self.PAGE) or self.PAGE)
            rows = self._es({"module": "account", "action": action, "address": wallet,
                             "startblock": start, "endblock": to, "page": 1,
                             "offset": page9, "sort": "asc"})
            if not isinstance(rows, list):
                raise RuntimeError(f"{action} 형식 오류")
            page_counts = {}
            for row in rows:
                key = self._row_key(row)
                page_counts[key] = page_counts.get(key, 0) + 1
                if page_counts[key] <= seen.get(key, 0):
                    continue
                seen[key] = page_counts[key]
                out.append(row)
            if len(rows) < min(page9, self.ES_ROW_FLOOR):
                return out
            last_blk = int(rows[-1].get("blockNumber") or 0)
            if last_blk <= start:
                raise RuntimeError(f"{action} 페이지 전진 불가 (단일 블록 {len(rows)}건 이상)")
            start = last_blk

    @staticmethod
    def _ent_block(ent: dict):
        for src in ([ent["tx"]] if ent.get("tx") else []) + list(ent.get("tt") or []) + list(ent.get("it") or []):
            try:
                return int(src.get("blockNumber") or 0) or None
            except (TypeError, ValueError, AttributeError):
                continue
        return None

    @staticmethod
    def _row_key(row) -> str:
        return json.dumps({k: v for k, v in row.items() if k != "confirmations"} if isinstance(row, dict) else row,
                          sort_keys=True, separators=(",", ":"))

    @classmethod
    def merge_wallet_rows(cls, per_wallet: dict) -> dict:
        out = {}
        for w, (txs, tts, its) in per_wallet.items():
            for row in txs:
                h = (row.get("hash") or "").lower()
                if h:
                    e = out.setdefault(h, {"tx": None, "tt": {}, "it": {}, "ws": set()})
                    e["ws"].add(w)
                    if e["tx"] is None:
                        e["tx"] = row
            for kind, rows in (("tt", tts), ("it", its)):
                cnt = {}
                for row in rows:
                    h = (row.get("hash") or "").lower()
                    if not h:
                        continue
                    k = cls._row_key(row)
                    cnt.setdefault(h, {}).setdefault(k, [0, row])[0] += 1
                for h, per in cnt.items():
                    e = out.setdefault(h, {"tx": None, "tt": {}, "it": {}, "ws": set()})
                    e["ws"].add(w)
                    for k, (n, row) in per.items():
                        cur = e[kind].get(k)
                        if cur is None or cur[0] < n:
                            e[kind][k] = [n, row]
        for e in out.values():
            for kind in ("tt", "it"):
                e[kind] = [row for n, row in e[kind].values() for _ in range(n)]
        return out

    @classmethod
    def _leg_marks(cls, ent: dict) -> dict:
        out = {}
        if ent.get("tx"):
            out["tx"] = 1
        for kind in ("tt", "it"):
            for row in ent.get(kind) or []:
                k = kind + ":" + hashlib.sha1(cls._row_key(row).encode()).hexdigest()[:16]
                out[k] = out.get(k, 0) + 1
        return out

    @staticmethod
    def _marks_new(prev, cur: dict) -> bool:
        if not isinstance(prev, dict):
            return bool(cur)
        return any(n > int(prev.get(k, 0) or 0) for k, n in cur.items())

    @staticmethod
    def _marks_merge(prev, cur: dict) -> dict:
        out = dict(prev) if isinstance(prev, dict) else {}
        for k, n in cur.items():
            out[k] = max(int(out.get(k, 0) or 0), n)
        return out

    def _lag_blocks(self) -> int:
        bpd9 = int(getattr(self, "bpd", 0) or 7200)
        return max(int(getattr(self, "conf_depth", 12) or 12), -(-bpd9 * self.INT_LAG_SEC // 86400))

    def _lag_from(self, w: str, since: int) -> int:
        floor9 = self.cursor.get("_cov:" + w)
        if not isinstance(floor9, int):
            floor9 = ((self.cursor.get("_es_int") or {}).get("floor") or {}).get(w)
        floor9 = int(floor9) if isinstance(floor9, int) else 0
        return max(floor9 + 1, since + 1 - self._lag_blocks(), 1)

    def _es_mem(self) -> dict:
        return _ES_WMEM.setdefault(self.chain, {"cost": {}, "next": None})

    def _es_wneed(self, w) -> int:
        n9 = int(addr_tier.per_check_calls("etherscan", bool(lpdec.lp_managers(paths.BASE_DIR).get(self.chain))))
        return max(n9, int(self._es_mem()["cost"].get(w, 0)))

    def _es_q_room(self, own: int, start: bool) -> bool:
        if bf_engine.ES_PACE_BURST_FRAC >= 1.0 or es_daily_left() > 0:
            return True
        used9, cap9 = bf_engine.es_budget_used()
        if used9 >= cap9:
            return True
        now = time.time()
        keep9 = max(1, int(cap9 * max(bf_engine.ES_FILL_KEEP_FRAC, bf_engine.ES_FILL_KEEP_MIN)))
        with _ES_Q_LOCK:
            me = _ES_Q.setdefault(self.chain, {"went": 0.0})
            if start:
                me.update(need=int(own), seen=now)
            k0 = (float(me.get("went") or 0), self.chain)
            ahead = 0
            for c9, v9 in _ES_Q.items():
                if c9 == self.chain or not (v9.get("busy") or now - float(v9.get("seen") or 0) <= ES_Q_TTL):
                    continue
                if not start or v9.get("busy") or (float(v9.get("went") or 0), c9) < k0:
                    ahead += int(v9.get("need") or 0)
            ok9 = bf_engine.es_pace_room("head", now) >= min(ahead + int(own), keep9)
            if ok9 and start:
                me["busy"] = True
                self._es_q_go = True
        return ok9

    def _es_q_done(self):
        if getattr(self, "_es_q_go", False):
            self._es_q_go = False
            with _ES_Q_LOCK:
                me = _ES_Q.get(self.chain)
                if me is not None:
                    me.update(went=time.time(), busy=False)

    def _legacy_pending(self, pend9: dict, safe: int, tb=None):
        for h9 in list(pend9.keys())[:30]:
            try:
                if h9 not in self.emitted and h9.lower() not in self.emitted:
                    snap9 = self._rpc_synth_detail(h9)
                    rec9 = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h9,
                            "snapshot": snap9, "wallets": self.wallets,
                            "observed_head": safe + self.conf_depth,
                            "ts": int(time.time())}
                    self.writer.append(rec9)
                    self.emitted.add(h9.lower())
                    if tb is not None:
                        tb.note_sent(addr_tier.sent_from(snap9), addr_tier.snap_ts(snap9))
                del pend9[h9]
                log.info("%s 구 pending %s RPC 합성 해소", self.chain, h9[:12])
            except Exception as e9:  # noqa: BLE001 [fallback]
                failures9 = self.synth_fail_count(pend9, h9, e9)
                if failures9 is None:
                    log.debug("%s 구 pending %s 보류(게이트·장부 거절 — 횟수 안 셈): %s", self.chain, h9[:12], str(e9)[:120])
                    continue
                if failures9 > 200:
                    statefile.append_durable_jsonl(
                        paths.state("pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain,
                         "txhash": h9, "err": logs.safe_err(e9)[:200]})
                    del pend9[h9]
                    log.error("★%s 구 pending %s 200회 초과 — 포이즌 격리★",
                              self.chain, h9[:12])
                else:
                    log.warning("%s 구 pending %s 합성 실패(%d회): %s",
                                self.chain, h9[:12], failures9, e9)

    def cycle(self):
        if not self.key:
            raise ChainDisabled(f"{self.chain}: 이더스캔 무료 키가 있어야 추적해요(이 체인은 블록스카웃·RPC 대체 없음) — 설정 › 연결·키 › Etherscan")
        try:
            self._es_cycle()
        finally:
            self._es_q_done()

    def _es_cycle(self):
        self._es_kind = "head"
        tb = getattr(self, "_tier", None)
        rest_set = set()
        if tb is not None:
            lp9 = statefile.read_json(paths.state(f"pending_detail_{self.chain}.json"), {})
            self._tier_legacy_pend = lp9 if isinstance(lp9, dict) else {}
            addr_tier.tier_prune(self)
            addr_tier.evm_activity(self, tb)
            due9, rest9 = tb.due_list(self.wallets)
            rest_set = set(rest9)
            if not due9 and not self._tier_legacy_pend:
                if self._ext_maybe_needed():
                    try:
                        hd9 = int(getattr(self, "_max_head", 0) or 0) or self.head_block()
                    except EtherscanPaced:
                        hd9 = 0
                    if hd9:
                        self._es_extend_safe(hd9)
                addr_tier.evm_empty_probe(self, tb, self._es_has_rows)
                addr_tier.idle_cycle(self, tb, "etherscan", "api.etherscan.io")
                return
        mem9 = self._es_mem()
        order9 = list(self.wallets)
        nx9 = mem9.get("next")
        if nx9 in order9:
            i9 = order9.index(nx9)
            order9 = order9[i9:] + order9[:i9]
        w09 = next((w for w in order9 if w in self.cursor and w not in rest_set), None)
        own9 = 1 + (self._es_wneed(w09) if w09 else 0)
        if not self._es_q_room(own9, True):
            raise EtherscanPaced(f"이더스캔 지갑 목록 묶음({own9}콜)이 실시간 몫에 쌓일 때까지 대기 — 다음 주기에 이어 받음")
        head = self.head_block()
        safe = head - self.conf_depth
        cycle_ok = True
        failed_w = 0
        tried_w = 0
        per_wallet = {}
        since_of = {}
        from_of = {}
        int_rec = self.cursor.get("_es_int") if isinstance(self.cursor.get("_es_int"), dict) else {}
        int_seen = int_rec.get("seen") if isinstance(int_rec.get("seen"), dict) else {}
        fail_since = {}
        paced_w = 0
        self._es_paced_next = mem9["next"] = None
        hw9 = 0
        wcost9 = mem9["cost"]
        for w9 in [w9 for w9 in wcost9 if w9 not in self.wallets]:
            wcost9.pop(w9, None)
        ft9 = mem9.setdefault("fail_t0", {})
        for w9 in [w9 for w9 in ft9 if w9 not in self.wallets]:
            ft9.pop(w9, None)
        for w in order9:
            first = w not in self.cursor
            since = int(self.cursor.get(w, 0))
            self._es_kind = "fill" if first else "head"
            if first:
                if self.backfill:
                    since = 0
                elif self.backfill_months > 0:
                    ck = self.cursor.get("_bfes:" + w)
                    if isinstance(ck, dict) and "since" in ck:
                        since = int(ck["since"])
                    else:
                        try:
                            since = self.window_start_block(safe, self.backfill_months, self.bpd)
                            ws9 = self.wallet_since.get(w)
                            if ws9:
                                since = min(since, self._block_by_ts(ws9))
                        except EtherscanPaced:
                            paced_w += 1
                            continue
                        self.cursor["_bfes:" + w] = {"since": since, "t0": int(time.time())}
                        statefile.atomic_write_json(self.cursor_path, self.cursor)
                    log.info("%s %g개월 한도 백필 시작 [etherscan] (%d → %d)",
                             w[:10], float(self.backfill_months), since, safe)
                else:
                    self.cursor[w] = safe
                    int_rec.setdefault("floor", {})[w] = safe
                    self.cursor["_es_int"] = int_rec
                    continue
            if w in rest_set:
                continue
            if since >= safe:
                if tb is not None:
                    addr_tier.tier_partial(self, w, False)
                if tb is not None and not addr_tier.tier_pending(self, w, enrich=False):
                    tb.note_full(w, since)
                continue
            if self._es_kind == "head":
                if hw9 and not self._es_q_room(self._es_wneed(w), False):
                    paced_w += 1
                    self._es_paced_next = mem9["next"] = w
                    break
                hw9 += 1
            hs9 = getattr(self, "_es_hspent", 0)
            tried_w += 1
            frm = since + 1 if first else self._lag_from(w, since)
            try:
                txs = self._list_all("txlist", w, frm, safe)
                tts = self._list_all("tokentx", w, frm, safe)
                its = self._list_all("txlistinternal", w, frm, safe)
                _mg9 = lpdec.lp_managers(paths.BASE_DIR).get(self.chain) or {}
                if _mg9:
                    tts = tts + [r9 for r9 in self._list_all("tokennfttx", w, frm, safe)
                                 if str(r9.get("contractAddress") or "").lower() in _mg9]
            except EtherscanPaced:
                tried_w -= 1
                paced_w += 1
                if self._es_kind == "head":
                    self._es_paced_next = mem9["next"] = w
                    sp9 = getattr(self, "_es_hspent", 0) - hs9
                    wcost9[w] = max(int(wcost9.get(w, 0)), sp9 + 1, 2 * sp9)
                    break
                continue
            except EtherscanKeyError:
                raise
            except Exception as e:  # noqa: BLE001 [isolate]
                log.warning("%s etherscan 수집 실패(다음 사이클): %s", w[:10], e)
                cycle_ok = False
                failed_w += 1
                fail_since[w] = since
                t9, f9 = time.time(), ft9.get(w)
                if isinstance(f9, list) and len(f9) == 2 and t9 - float(f9[1]) <= ES_FAIL_ISOLATE_SEC:
                    f9[1] = t9
                else:
                    ft9[w] = [t9, t9]
                _revoke_stamp_disk(self.cursor_path)
                continue
            ft9.pop(w, None)
            per_wallet[w] = (txs, tts, its)
            since_of[w] = since
            from_of[w] = frm
            if self._es_kind == "head":
                wcost9[w] = getattr(self, "_es_hspent", 0) - hs9
            if tb is not None and (txs or tts or its):
                tb.clear_empty(w, "rows")
        self._es_kind = "head"
        merged = self.merge_wallet_rows(per_wallet)
        now9 = time.time()
        iso9 = {w for w in fail_since if now9 - float((ft9.get(w) or [now9])[0]) >= ES_FAIL_ISOLATE_SEC}
        note9 = mem9.setdefault("iso_note", set())
        note9.intersection_update(ft9)
        if iso9 - note9:
            log.warning("%s etherscan 목록 조회 %d분 넘게 실패한 지갑 %s — 그 지갑만 보류(커서 유지), 다른 지갑은 진행(겹친 tx 는 회복 때 레그 합집합)",
                        self.chain, ES_FAIL_ISOLATE_SEC // 60, [w9[:10] for w9 in sorted(iso9 - note9)])
        note9.update(iso9)
        eff_safe = min([safe] + [int(v) for w, v in fail_since.items() if w not in iso9])
        bad_w = set()
        n_emit = 0
        relist = []
        for h in sorted(merged, key=lambda x: (self._ent_block(merged[x]) or 0, x)):
            ent = merged[h]
            if h in self.emitted:
                blk9 = self._ent_block(ent)
                if blk9 and (ent["tx"] or ent["it"] or ent["tt"]) and any(from_of[w] <= blk9 <= eff_safe for w in ent["ws"]):
                    prev9 = int_seen.get(h)
                    if self._marks_new(prev9[1] if isinstance(prev9, list) and len(prev9) == 2 else None, self._leg_marks(ent)):
                        relist.append(h)
                continue
            blk = self._ent_block(ent)
            if not blk:
                log.warning("etherscan %s 블록 번호 파싱 불능 — 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            if not any(from_of[w] <= blk <= eff_safe for w in ent["ws"]):
                continue
            snap = self._snapshot(ent)
            if snap is None:
                log.warning("etherscan %s 상세 수치 파싱 불능 — 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            rec = {"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h,
                   "snapshot": snap, "wallets": self.wallets,
                   "observed_head": head, "ts": int(time.time())}
            try:
                self.writer.append(rec)
                self.emitted.add(h)
                n_emit += 1
                int_seen[h] = [blk, self._leg_marks(ent)]
                if tb is not None and ent["tx"]:
                    tb.note_sent(str(ent["tx"].get("from") or "").lower(), snap["tx"].get("timestamp"))
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                bad_w |= set(per_wallet)
                cycle_ok = False
                _revoke_stamp_disk(self.cursor_path)
                break
        for h in relist:
            ent = merged[h]
            blk = self._ent_block(ent)
            if not any(w not in bad_w and from_of[w] <= blk <= eff_safe for w in ent["ws"]):
                continue
            snap = self._snapshot(ent)
            if snap is None:
                log.warning("etherscan %s internal 늦은 색인 재방출 — 상세 수치 파싱 불능, 관련 지갑 커서 유지", h[:12])
                bad_w |= ent["ws"]
                continue
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time()), "repair": "leg_union"})
                if tb is not None and ent["tx"]:
                    tb.note_sent(str(ent["tx"].get("from") or "").lower(), snap["tx"].get("timestamp"))
            except Exception as e:  # noqa: BLE001 [fallback]
                log.error("inbox append 실패(internal 늦은 색인 재방출) — 커서 미전진: %s", e)
                bad_w |= set(per_wallet)
                cycle_ok = False
                _revoke_stamp_disk(self.cursor_path)
                break
            prev9 = int_seen.get(h)
            int_seen[h] = [blk, self._marks_merge(prev9[1] if isinstance(prev9, list) and len(prev9) == 2 else None, self._leg_marks(ent))]
            log.info("%s %s 늦은 색인 레그 — leg 합집합 재방출(토큰 %d · internal %d행)", self.chain, h[:12], len(ent["tt"]), len(ent["it"]))
        if int_seen or int_rec.get("floor"):
            lo_all9 = list(from_of.values()) + [self._lag_from(w, int(self.cursor[w])) for w in rest_set if isinstance(self.cursor.get(w), int)]
            lo9 = min(lo_all9) if lo_all9 else None
            if lo9 is not None:
                int_seen = {h9: v9 for h9, v9 in int_seen.items() if isinstance(v9, list) and len(v9) == 2 and int(v9[0]) >= lo9}
            int_rec["seen"] = int_seen
            self.cursor["_es_int"] = int_rec
        if bad_w:
            cycle_ok = False
            failed_w += len(bad_w & set(per_wallet))
            _revoke_stamp_disk(self.cursor_path)
        for w in per_wallet:
            if w not in bad_w:
                if w not in self.cursor:
                    ck = self.cursor.pop("_bfes:" + w, None)
                    if isinstance(ck, dict) and "since" in ck:
                        self.cursor["_cov:" + w] = int(ck["since"])
                    if isinstance(ck, dict):
                        log.info("★%s 백필 완주 [etherscan] %d tx 방출, %.0f초★", w[:10], n_emit,
                                 time.time() - float(ck.get("t0") or time.time()))
                self.cursor[w] = max(int(self.cursor.get(w, 0)), eff_safe)
                if tb is not None:
                    addr_tier.tier_partial(self, w, int(self.cursor[w]) < safe)
                    if int(self.cursor[w]) >= safe and not addr_tier.tier_pending(self, w, enrich=False):
                        tb.note_full(w, int(self.cursor[w]))
        if tb is not None:
            self._tier_fail = (getattr(self, "_tier_fail", set()) - (set(per_wallet) - bad_w)) | set(fail_since) | (bad_w & set(per_wallet))
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        pp9 = paths.state(f"pending_detail_{self.chain}.json")
        pend9 = statefile.read_json(pp9, {})
        if pend9:
            self._legacy_pending(pend9, safe, tb)
            statefile.atomic_write_json(pp9, pend9)
            if tb is not None:
                self._tier_legacy_pend = dict(pend9)
        if tried_w and failed_w == tried_w:
            raise RuntimeError(f"etherscan 수집 전 지갑 실패 ({failed_w}/{tried_w})")
        if cycle_ok and not pend9 and \
                all(int(self.cursor.get(w, 0)) >= safe for w in self.wallets if w not in rest_set):
            self.cursor["_synced_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_at", None)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        if tb is not None:
            addr_tier.evm_baselines(self, tb, list(per_wallet))
            if cycle_ok:
                addr_tier.evm_empty_probe(self, tb, self._es_has_rows)
            tb.save()
        if cycle_ok:
            self._es_extend_safe(head)
        if self._es_paced_next is not None and not per_wallet:
            raise EtherscanPaced("이더스캔 지갑 조회 페이싱 — 이번 주기 목록 조회를 끝낸 지갑 없음")
        self._health_cycle("etherscan", head, safe, ok=cycle_ok,
                           err=RuntimeError(f"지갑 실패 {failed_w}/{tried_w}"), current_source="api.etherscan.io",
                           wallets_failing=failed_w, pending_detail=len(pend9), wallets_paced=paced_w)

    def _es_has_rows(self, w: str, blk: int):
        self._es_kind = "aux"
        try:
            acts = ["tokentx"] + (["tokennfttx"] if lpdec.lp_managers(paths.BASE_DIR).get(self.chain) else [])
            for act in acts:
                rows = self._es({"module": "account", "action": act, "address": w, "startblock": 0, "endblock": int(blk),
                                 "page": 1, "offset": 1, "sort": "asc"})
                if not isinstance(rows, list):
                    return None
                if rows:
                    return True
            return False
        finally:
            self._es_kind = "head"

    def _es_extend_safe(self, head: int):
        try:
            self._es_extend(head)
        except EtherscanKeyError:
            raise
        except EtherscanPaced as e:
            log.debug("%s 과거 창 확장 — 페이싱으로 다음 주기: %s", self.chain, e)
        except Exception as e:  # noqa: BLE001 [optional]
            log.info("%s 과거 창 확장 예외(다음 사이클): %s", self.chain, e)
        finally:
            self._es_kind = "head"

    def _ext_maybe_needed(self) -> bool:
        if not bf_engine.SINCE.target(self.chain):
            return False
        return any(isinstance(self.cursor.get(w), int) and addr_tier._evm_ext_need(self, "etherscan", w) for w in self.wallets)

    def _ent_ts(self, ent: dict):
        for r in ([ent["tx"]] if ent.get("tx") else []) + list(ent.get("tt") or []) + list(ent.get("it") or []):
            try:
                v = int(r.get("timeStamp") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if v > 0:
                return v
        if self is None:
            return None
        src9 = ent.get("tx") or next(iter(list(ent.get("tt") or []) + list(ent.get("it") or [])), None) or {}
        h9 = str(src9.get("hash") or "")
        hold = getattr(self, "_ts_hold", None)
        if hold is None:
            hold = self._ts_hold = tsfix.TsHold()
        try:
            v = tsfix.block_ts(self, self._ent_block(ent) or 0)
            hold.clear(h9)
            return v
        except Exception as e:   # noqa: BLE001 [fallback]
            if hold.hold(h9):
                log.warning("etherscan %s 시각 없음 · 블록 시각 조회 실패 — 보류(커서 유지 · 다음 사이클): %s", h9[:12], str(e)[:100])
                return None
            log.error("★etherscan %s 시각 없음 %d회 연속 — 내보냄(core 격리 → 블록 시각 구하는 대로 자동 재방출 · 상태 패널 '격리된 거래 기록')★",
                      h9[:12], hold.limit)
            return 0

    ES_WRAP_DEPOSIT_SEL = "0xd0e30db0"
    ES_WRAP_WITHDRAW_SEL = "0x2e1a7d4d"
    ES_NONVALUE_INTERNAL = frozenset(("delegatecall", "staticcall", "callcode"))

    def _es_wrap_legs(self, t: dict, status: str, ent: dict, tts: list):
        wr = str(getattr(self, "wrapped_ca", None) or "").lower()
        if not wr or not t or status != "ok" or str(t.get("to") or "").lower() != wr:
            return []
        fr = str(t.get("from") or "").lower()
        ws9 = getattr(self, "wallets", None)
        if not fr or (ws9 is not None and fr not in ws9):
            return []
        inp = str(t.get("input") or "").lower()
        mid = str(t.get("methodId") or "").lower()
        sel = inp[:10] if inp.startswith("0x") and len(inp) >= 10 else (mid[:10] if len(mid) >= 10 else "")
        empty9 = inp == "0x" or (inp == "" and mid == "0x")
        z9 = RpcSynthMixin.ZERO_ADDR
        try:
            if sel == EtherscanWatcher.ES_WRAP_DEPOSIT_SEL or empty9:
                v, a, b = int(t.get("value") or 0), z9, fr
            elif sel == EtherscanWatcher.ES_WRAP_WITHDRAW_SEL:
                a, b = fr, z9
                if len(inp) >= 74 and re.fullmatch(r"[0-9a-f]{64}", inp[10:74]):
                    v = int(inp[10:74], 16)
                else:
                    v = sum(int(r.get("value") or 0) for r in ent.get("it") or []
                            if str(r.get("from") or "").lower() == wr and str(r.get("to") or "").lower() == fr
                            and str(r.get("isError") or "0") == "0"
                            and str(r.get("type") or "").lower() not in EtherscanWatcher.ES_NONVALUE_INTERNAL)
            else:
                return []
        except (TypeError, ValueError):
            return []
        if v <= 0:
            return []
        for r in tts:
            tok9 = r.get("token") or {}
            if str(tok9.get("address") or "").lower() == wr and str(r.get("from") or "").lower() == a \
                    and str(r.get("to") or "").lower() == b and str((r.get("total") or {}).get("value")) == str(v):
                return []
        dec9 = sym9 = None
        for r in ent.get("tt") or []:
            if str(r.get("contractAddress") or "").lower() == wr and r.get("tokenDecimal") not in (None, ""):
                dec9, sym9 = int(r.get("tokenDecimal")), r.get("tokenSymbol")
                break
        if dec9 is None:
            try:
                dec9 = self._rpc_token_dec(wr)
            except bf_engine.TokenNoDecimals:
                return []
            except Exception as e9:   # noqa: BLE001 [fallback]
                log.warning("etherscan %s 랩드 네이티브 %s 자릿수 조회 실패 — 보류: %s", str(t.get("hash"))[:12], wr[:10], str(e9)[:100])
                return None
        return [{"from": a, "to": b, "token": {"address": wr, "symbol": sym9, "decimals": dec9, "type": "ERC-20"},
                 "total": {"value": str(v)}}]

    def _snapshot(self, ent: dict):
        t = ent["tx"]
        ts9 = EtherscanWatcher._ent_ts(self, ent)
        if ts9 is None:
            return None
        if t:
            try:
                fee = int(t.get("gasUsed") or 0) * int(t.get("gasPrice") or 0)
                status = "ok" if str(t.get("txreceipt_status") or "1") == "1" else "error"
                tx = {"hash": t["hash"], "from": t.get("from"), "to": t.get("to"),
                      "value": str(int(t.get("value") or 0)),
                      "fee": {"value": str(fee)}, "status": status,
                      "raw_input": t.get("input") or "0x",
                      "timestamp": ts9,
                      "block_number": int(t.get("blockNumber") or 0),
                      "block_hash": t.get("blockHash")}
            except (TypeError, ValueError, KeyError):
                return None
        else:
            src = (ent["tt"] or ent["it"])[0]
            try:
                tx = {"hash": src["hash"], "from": src.get("from"), "to": src.get("to"),
                      "value": "0", "fee": {"value": "0"}, "status": "ok",
                      "raw_input": "0x01",
                      "timestamp": ts9,
                      "block_number": int(src.get("blockNumber") or 0),
                      "block_hash": src.get("blockHash")}
            except (TypeError, ValueError, KeyError):
                return None
        pos9 = {bf_engine.ord_index(r.get("transactionIndex")) for r in ([t] if t else []) + list(ent["tt"] or []) + list(ent["it"] or [])
                if isinstance(r, dict) and r.get("transactionIndex") not in (None, "")}
        if len(pos9) == 1 and None not in pos9:
            tx["position"] = pos9.pop()
        tts = []
        for r in ent["tt"]:
            try:
                if r.get("tokenID") is not None and r.get("tokenDecimal") in (None, "", "0") and r.get("value") is None:
                    tts.append({"from": r.get("from"), "to": r.get("to"),
                                "token": {"address": (r.get("contractAddress") or "").lower(),
                                          "symbol": r.get("tokenSymbol"), "name": r.get("tokenName"),
                                          "type": "ERC-721"},
                                "total": {"token_id": str(int(r.get("tokenID")))}})
                    RpcSynthMixin._ord_li(tts[-1], r)
                    continue
                ca9 = (r.get("contractAddress") or "").lower()
                v9 = int(r.get("value") or 0)
                td9 = r.get("tokenDecimal")
                if td9 not in (None, ""):
                    dec9 = int(td9)
                elif not v9:
                    dec9 = None
                else:
                    try:
                        dec9 = self._rpc_token_dec(ca9)
                    except bf_engine.TokenNoDecimals:
                        self._nodec_reg().skip(tx["hash"], ca9, r.get("from"), r.get("to"), v9)
                        continue
                    except Exception as e9:   # noqa: BLE001 [fallback]
                        log.warning("etherscan %s 토큰 %s 자릿수 미상(빈 tokenDecimal) · RPC 조회 실패 — 보류: %s", str(tx.get("hash"))[:12],
                                    ca9[:10], str(e9)[:100])
                        return None
                tts.append({"from": r.get("from"), "to": r.get("to"),
                            "token": {"address": ca9,
                                      "symbol": r.get("tokenSymbol"),
                                      "decimals": dec9,
                                      "type": "ERC-20"},
                            "total": {"value": str(v9)}})
                RpcSynthMixin._ord_li(tts[-1], r)
            except (TypeError, ValueError):
                return None
        wl9 = EtherscanWatcher._es_wrap_legs(self, t, tx["status"], ent, []) if t else []
        if wl9 is None:
            return None
        for r9 in wl9:
            if not any(str(t9.get("from") or "").lower() == r9["from"] and str(t9.get("to") or "").lower() == r9["to"]
                       and str((t9.get("token") or {}).get("address") or "").lower() == r9["token"]["address"]
                       and str((t9.get("total") or {}).get("value")) == r9["total"]["value"] for t9 in tts):
                tts.append(r9)
        its = []
        for r in ent["it"]:
            if str(r.get("type") or "").lower() in EtherscanWatcher.ES_NONVALUE_INTERNAL:
                continue
            try:
                its.append({"from": r.get("from"), "to": r.get("to"),
                            "value": str(int(r.get("value") or 0)),
                            "success": str(r.get("isError") or "0") == "0",
                            "error": None if str(r.get("isError") or "0") == "0" else "err"})
            except (TypeError, ValueError):
                return None
        for r9 in wl9:
            a9, b9 = str(r9.get("from") or "").lower(), str(r9.get("to") or "").lower()
            wr9 = str((r9.get("token") or {}).get("address") or "").lower()
            if b9 != RpcSynthMixin.ZERO_ADDR or not a9 or a9 != str((t or {}).get("from") or "").lower():
                continue
            if not any(str(i.get("from") or "").lower() == wr9 and str(i.get("to") or "").lower() == a9 and i.get("success") for i in its):
                its.append({"from": wr9, "to": a9, "value": str((r9.get("total") or {}).get("value")), "success": True, "error": None})
        return {"tx": tx, "token_transfers": tts, "internal": its}
