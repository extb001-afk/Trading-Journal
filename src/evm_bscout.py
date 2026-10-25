import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
import urllib.request
import evm_reorg, logs, paths, statefile
import bf_engine
import tsfix
import addr_tier
from inbox import SegmentWriter
from evm_base import BACKFILL_PAGES_MAX
from evm_base import BsDetailCap
from evm_base import DISCOVERY_PAGES_MAX
from evm_base import EXPLORER_FROZEN_GAP
from evm_base import EXPLORER_FROZEN_SEC
from evm_base import _is_http_5xx
from evm_base import _revoke_stamp_disk
from evm_base import http_json
from evm_base import new_view_wallets
from evm_base import rpc_handback
from evm_synth import RpcSynthMixin, bs_dec_fill
import logging

log = logging.getLogger('tj-evm')

class ChainWatcher(RpcSynthMixin):
    def __init__(self, cfg: dict, chain: str, wallets: list, writer: SegmentWriter):
        self.chain = chain
        self.wrapped_ca = str((cfg.get("wrapped_native") or {}).get(chain) or "").lower() or None
        self.base = cfg["chains"][chain]["blockscout"].rstrip("/")
        chain_cc = cfg["chains"][chain]
        self.conf_depth = int(chain_cc.get("conf_depth", 12))
        self.backfill = bool(cfg.get("backfill_full_history"))
        self.backfill_months = float(cfg.get("backfill_months") or 0)
        self.bpd = int(cfg["chains"][chain].get("blocks_per_day", 43200))
        self.wallets = [w.lower() for w in wallets]
        self.wallet_since = bf_engine.wallet_since_map(cfg, chain)
        self.writer = writer
        self.cursor_path = paths.state(f"cursor_evm_{chain}.json")
        self.cursor = statefile.read_json(self.cursor_path, {})
        if self.cursor.get("_rpc_v") is not None:
            self._rpc_handback()
        evm_reorg.ack_start(self, chain_cc)
        self.pending_detail = statefile.read_json(
            paths.state(f"pending_detail_{chain}.json"), {})
        self.fail_streak = {}
        self.cfg_rpcs = cfg["chains"][chain].get("rpcs")
        self.rpc_meta_path = paths.state(f"rpc_token_meta_{chain}.json")
        self.rpc_meta = statefile.read_json(self.rpc_meta_path, {})
        self.emitted_path = paths.state(f"emitted_evm_{chain}.json")
        self.emitted = set(statefile.read_json(self.emitted_path, []))
        emitted_before = set(self.emitted)
        new_view_wallets(self)
        self.rescan_overlap = int(cfg["chains"][chain].get("rescan_overlap_blocks", 0))
        self.idx_guard = bool(cfg["chains"][chain].get("indexing_status_guard"))
        self.idx_guard_scope = str(cfg["chains"][chain].get("indexing_guard_scope") or "head")
        self.enrich_path = paths.state(f"enrich_{chain}.json")
        self.enrich = statefile.read_json(self.enrich_path, {})
        self._enrich_5xx = {}
        bfc = cfg.get("backfill") or {}
        self.bf_mode = str(bfc.get("engine") or "v2")
        self.bf2_budget = float(bfc.get("evm_cycle_budget_sec") or self.BF2_TIME_BUDGET)
        self.progress = bf_engine.progress("evm")
        self._prev_emitted = emitted_before
        self._tier = addr_tier.evm_book(self, cfg, "blockscout")

    def _rpc_handback(self):
        rpc_handback(self, "blockscout")

    def _idx_note(self, idx_ok: bool, state: str = None, head_ok: bool = None):
        now9 = time.time()
        prev9 = getattr(self, "_idx_prev", True)
        kind9 = "ok" if idx_ok else ("partial" if head_ok else "hold")
        if not idx_ok:
            if prev9 is True:
                self._idx_bad_since = now9
            if prev9 is True or prev9 != kind9 or now9 - getattr(self, "_idx_warn_at", 0) >= 3600:
                unk9 = getattr(self, "_idx_unknown", None)
                if kind9 == "partial":
                    log.warning("%s blockscout indexing-status internal 색인만 미완(%s%s) — tx·토큰 목록으로 발견 진행(커서 전진), 내부 이동은 "
                                "'나중에 채우기' 표식(색인 완료 뒤 자동 재훑기) · 동기화 도장 보류(%.0f분째 — 다음 안내는 1시간 뒤/복구 시)",
                                self.chain, getattr(self, "_idx_ratio", None), f", 조회 실패 — 마지막 관측 유지: {unk9}" if unk9 else "",
                                (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
                else:
                    log.warning("%s blockscout indexing-status 미완(%s%s) — discovery 보류(커서 유지, %.0f분째 — 다음 경고는 1시간 뒤/복구 시)",
                                self.chain, state, f", 조회 실패 — 마지막 관측 유지: {unk9}" if unk9 else "",
                                (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
                self._idx_warn_at = now9
        elif prev9 is not True:
            log.info("%s blockscout indexing-status 복구 — discovery 재개(전면 · %.0f분 만에)",
                     self.chain, (now9 - getattr(self, "_idx_bad_since", now9)) / 60)
        self._idx_prev = True if idx_ok else kind9

    def _indexing_ok(self) -> bool:
        return self._indexing_state() == "ok"

    def _indexing_state(self) -> str:
        self._idx_ratio = None
        try:
            d = http_json(f"{self.base}/api/v2/main-page/indexing-status")
        except Exception as e:  # noqa: BLE001 [fallback]
            return self._idx_sticky(e)
        if not isinstance(d, dict):
            return self._idx_sticky(RuntimeError("indexing-status 응답 형식 오류"))
        fb, fi = d.get("finished_indexing_blocks"), d.get("finished_indexing")
        if fb is False:
            st = "blocks"
        elif fi is True:
            st = "ok"
        elif fi is False:
            st = "internal" if fb is True else "blocks"
        else:
            return self._idx_sticky(RuntimeError("indexing-status 응답에 finished_indexing 없음"))
        self._idx_ratio = d.get("indexed_internal_transactions_ratio")
        self._idx_unknown = None
        self._idx_seen = (st, time.time(), self._idx_ratio)
        self._idx_streak_note(st, self._idx_ratio)
        return st

    IDX_BLOCKS_STICKY_SEC = 3600
    IDX_OK_FRESH_SEC = 1800
    IDX_STABLE_SEC = int(os.environ.get("TJ_INT_RESCAN_STABLE_SEC") or 3600)
    IDX_STREAK_GAP_SEC = 900
    IDX_RECHECK_SEC = 30
    IDX_RATIO_FULL = 0.99

    @classmethod
    def _ratio_full(cls, ratio) -> bool:
        if ratio is None:
            return True
        try:
            return float(str(ratio)) >= cls.IDX_RATIO_FULL
        except (TypeError, ValueError):
            return True

    def _idx_streak_note(self, st: str, ratio):
        now = int(time.time())
        if st == "ok" and self._ratio_full(ratio):
            s = self.cursor.get("_idx_ok_streak")
            if isinstance(s, dict) and now - int(s.get("last") or 0) <= self.IDX_STREAK_GAP_SEC:
                s["last"] = now
            else:
                self.cursor["_idx_ok_streak"] = {"since": now, "last": now}
            return
        self.cursor.pop("_idx_ok_streak", None)
        prev_bad = int(self.cursor.get("_idx_bad_at") or 0)
        self._int_reopen(prev_bad, st, ratio)
        self.cursor["_idx_bad_at"] = now

    def _int_reopen(self, prev_bad: int, st: str, ratio) -> int:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            return 0
        n = 0
        for r in m.get("ranges") or []:
            if not isinstance(r, dict):
                continue
            if r.get("done"):
                hit = r.get("done_at") is not None and int(r["done_at"]) >= int(prev_bad)
            else:
                prog = int(r.get("pages") or 0) > 0 or r.get("npp") is not None
                hit = prog and (r.get("read_at") is None or int(r["read_at"]) >= int(prev_bad))
            if hit:
                r["done"], r["npp"], r["pages"] = False, None, 0
                r.pop("done_at", None)
                r.pop("read_at", None)
                n += 1
        if n:
            m.pop("started", None)
            m["reopened"] = int(m.get("reopened") or 0) + n
            m["emit_i"] = 0
            log.warning("★%s 탐색기 색인 회귀(%s · 비율 %s) — 그 전 '완료' 관측 뒤 끝내거나 읽던 internal 재훑기 구간 %d개를 처음부터 다시(1시간 연속 완료 뒤 재개)★",
                        self.chain, st, ratio, n)
        return n

    def _int_lag_track(self, idx_state: str):
        if idx_state in ("internal", "blocks") and not isinstance(self.cursor.get("_int_lag_since"), int):
            m9 = self.cursor.get("_ext_internal_pending")
            c9 = int(m9.get("created") or 0) if isinstance(m9, dict) else 0
            self.cursor["_int_lag_since"] = min(int(time.time()), c9) if c9 > 0 else int(time.time())
        elif idx_state == "ok" and not isinstance(self.cursor.get("_ext_internal_pending"), dict):
            self.cursor.pop("_int_lag_since", None)

    def _idx_stable(self) -> bool:
        if not self.idx_guard:
            return True
        s = self.cursor.get("_idx_ok_streak")
        if not isinstance(s, dict) or getattr(self, "_idx_unknown", None):
            return False
        now = time.time()
        return now - int(s.get("since") or now) >= self.IDX_STABLE_SEC and now - int(s.get("last") or 0) <= self.IDX_STREAK_GAP_SEC

    def _idx_recheck(self) -> bool:
        if not self.idx_guard:
            return True
        seen = getattr(self, "_idx_seen", None)
        if not (seen and seen[0] == "ok" and self._ratio_full(seen[2]) and time.time() - seen[1] < self.IDX_RECHECK_SEC
                and not getattr(self, "_idx_unknown", None)):
            if self._indexing_state() != "ok" or getattr(self, "_idx_unknown", None):
                return False
        return self._idx_stable()

    def _idx_sticky(self, err) -> str:
        self._idx_unknown = logs.safe_err(err)[:120]
        seen = getattr(self, "_idx_seen", None)
        now9 = time.time()
        if seen and seen[0] == "blocks" and now9 - seen[1] < self.IDX_BLOCKS_STICKY_SEC:
            return "blocks"
        lag = self.cursor.get("_ext_internal_lag")
        pend = isinstance(self.cursor.get("_ext_internal_pending"), dict)
        job = self.cursor.get("_bfjob")
        if isinstance(job, dict) and job.get("int_lag"):
            pend = True
        if seen and seen[0] == "ok":
            if not pend and now9 - seen[1] < self.IDX_OK_FRESH_SEC:
                return "ok"
            self._idx_ratio = seen[2]
            return "internal"
        if seen or isinstance(lag, dict):
            self._idx_ratio = (seen[2] if seen else None) or (lag.get("ratio") if isinstance(lag, dict) else None)
            return "internal"
        return "internal" if pend else "ok"

    def head_block(self):
        d = http_json(f"{self.base}/api/v2/blocks?type=block")
        items = d.get("items") or []
        if not items:
            raise RuntimeError("blocks 응답 비어있음")
        head = int(items[0]["height"])
        ts9 = items[0].get("timestamp")
        if isinstance(ts9, str):
            try:
                import datetime as _dt
                self._head_ts = int(_dt.datetime.fromisoformat(ts9.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
        mx = getattr(self, "_max_head", 0)
        if mx and head < mx - max(64, self.conf_depth):
            raise bf_engine.NetError(f"blockscout 헤드 역행 {head} < 관측 최대 {mx} (뒤처진 복제본)", "stale_head")
        self._max_head = max(mx, head)
        self._explorer_frozen_check(head)
        return head

    def _explorer_frozen_check(self, head: int):
        hts = getattr(self, "_head_ts", None)
        if not isinstance(hts, int) or time.time() - hts <= EXPLORER_FROZEN_SEC:
            return
        ref = self._ref_head()
        if ref is None or ref - int(head) <= max(EXPLORER_FROZEN_GAP, 10 * int(self.conf_depth)):
            return
        hrs = (time.time() - hts) / 3600.0
        raise bf_engine.NetError(
            f"blockscout 색인 정지 — 최신 블록 {int(head)} 이 {hrs:.0f}시간째 그대로(노드 헤드 {ref} · {ref - int(head)}블록 뒤) — "
            "그 뒤 새 거래를 받지 못함", "stale_head")

    def _page_json(self, url: str, tries: int = 5):
        for i in range(tries):
            try:
                return http_json(url)
            except bf_engine.NetError as e:
                if i == tries - 1 or e.kind in ("circuit", "quota", "budget"):
                    raise
                time.sleep(1.0 + 1.5 * i)
            except Exception:  # noqa: BLE001 [fallback]
                if i == tries - 1:
                    raise
                time.sleep(1.0 + 1.5 * i)

    def discover(self, wallet: str, since_block: int, safe_block: int, first_sync: bool = False, skip_internal: bool = False):
        hashes = {}
        ck = None if first_sync else self.cursor.get("_disc:" + wallet)
        if not (isinstance(ck, dict) and isinstance(ck.get("safe"), int) and ck.get("since") == since_block
                and isinstance(ck.get("ep"), int) and 0 <= ck["ep"] < 3 and ck["safe"] > since_block):
            ck = None
        if ck:
            safe_block = int(ck["safe"])
        self._disc_safe = safe_block
        self._disc_ck_next = None
        eps9 = (("transactions", "hash"),
                ("token-transfers", "transaction_hash"),
                ("internal-transactions", "transaction_hash"))
        for ep_i, (ep, hash_key) in enumerate(eps9[:2] if skip_internal else eps9):
            if ck and ep_i < int(ck["ep"]):
                continue
            url = f"{self.base}/api/v2/addresses/{wallet}/{ep}"
            if ck and ep_i == int(ck["ep"]) and isinstance(ck.get("npp"), dict):
                url += "?" + urllib.parse.urlencode(ck["npp"])
            pages = 0
            pages_max = BACKFILL_PAGES_MAX if first_sync else DISCOVERY_PAGES_MAX
            while url and pages < pages_max:
                try:
                    d = self._page_json(url)
                except Exception as e:  # noqa: BLE001 [fallback]
                    self._disc_err = f"{ep}: {logs.safe_err(e)[:160]}"
                    self._rpcfb_disc_error = e
                    return None
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    log.warning("%s %s 응답 형식 오류 — 커서 유지", wallet[:10], ep)
                    return None
                oldest = None
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hash_key)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    if raw_blk is None:
                        hashes.setdefault(h, None)
                        continue
                    try:
                        blk = int(raw_blk)
                    except (TypeError, ValueError):
                        hashes.setdefault(h, None)
                        continue
                    oldest = blk if oldest is None else min(oldest, blk)
                    if since_block < blk <= safe_block:
                        hashes[h] = blk
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                if oldest is not None and oldest <= since_block:
                    break
                if not npp:
                    break
                if not isinstance(npp, dict):
                    log.warning("%s %s next_page_params 형식 오류 — 커서 유지", wallet[:10], ep)
                    return None
                url = f"{self.base}/api/v2/addresses/{wallet}/{ep}?" + urllib.parse.urlencode(npp)
                pages += 1
                time.sleep(0.3)
            else:
                if pages >= pages_max:
                    if first_sync:
                        log.warning("%s %s 페이지 상한 도달 — 놓친 구간은 커서 유지로 다음 사이클 재시도",
                                    wallet[:10], ep)
                        return None
                    self._disc_ck_next = {"since": since_block, "safe": safe_block, "ep": ep_i, "npp": npp}
                    log.warning("%s %s 증분 페이지 상한(%d) — 체크포인트 저장, 다음 사이클 이어받기(창 %d~%d)",
                                wallet[:10], ep, pages_max, since_block, safe_block)
                    return hashes
        return hashes

    BF_PAGE_BUDGET = 150
    BF_TIME_BUDGET = 600
    BF_FLUSH_EVERY = 10

    def _first_sync_walk(self, w: str, head: int, safe_now: int) -> bool:
        ck = self.cursor.get("_bf:" + w)
        if not isinstance(ck, dict) or "safe" not in ck:
            since0 = 0 if self.backfill else self.window_start_block(safe_now, self.backfill_months, self.bpd)
            ws9 = (getattr(self, "wallet_since", None) or {}).get(w)
            if ws9 and since0 > 0:
                since0 = min(since0, self.window_start_block_ts(ws9))
            ck = {"since": since0, "safe": safe_now, "ep": 0, "npp": None, "pages": 0}
            self.cursor["_bf:" + w] = ck
            statefile.atomic_write_json(self.enrich_path, self.enrich)
            statefile.atomic_write_json(
                paths.state(f"pending_detail_{self.chain}.json"),
                self.pending_detail)
            statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
            statefile.atomic_write_json(self.cursor_path, self.cursor)
            log.info("%s 재개형 백필 시작 (%d → %d)", w[:10], since0, safe_now)
        since0, safe0 = int(ck["since"]), int(ck["safe"])
        eps = (("transactions", "hash"),
               ("token-transfers", "transaction_hash"),
               ("internal-transactions", "transaction_hash"))
        budget = self.BF_PAGE_BUDGET
        deadline = time.time() + self.BF_TIME_BUDGET
        try:
            while int(ck["ep"]) < len(eps) and budget > 0 and time.time() < deadline:
                ep, hash_key = eps[int(ck["ep"])]
                url = f"{self.base}/api/v2/addresses/{w}/{ep}"
                if isinstance(ck.get("npp"), dict):
                    url += "?" + urllib.parse.urlencode(ck["npp"])
                try:
                    d = self._page_json(url)
                except Exception as e:  # noqa: BLE001 [fallback]
                    log.warning("%s %s 백필 페이지 실패 — 체크포인트 유지(p%d): %s",
                                w[:10], ep, int(ck.get("pages", 0)), e)
                    return False
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    log.warning("%s %s 백필 응답 형식 오류 — 체크포인트 유지", w[:10], ep)
                    return False
                oldest = None
                cands = []
                seen_pg = set()
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hash_key)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    blk = None
                    if raw_blk is not None:
                        try:
                            blk = int(raw_blk)
                        except (TypeError, ValueError):
                            blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (since0 < blk <= safe0):
                            continue
                    addr_tier.tier_mark_if_live(self, h, [w])
                    if h.lower() in self.emitted or h.lower() in seen_pg:
                        continue
                    seen_pg.add(h.lower())
                    cands.append((h, blk))
                results = {}
                if cands:
                    ex9 = ThreadPoolExecutor(max_workers=5)
                    try:
                        futs = {ex9.submit(self.fetch_detail, h): h for h, _ in cands}
                        page_deadline = time.time() + 300
                        for fu in futs:
                            remain9 = max(0.05, page_deadline - time.time())
                            try:
                                results[futs[fu]] = fu.result(timeout=remain9)
                            except FutTimeout:
                                results[futs[fu]] = RuntimeError("페이지 상세 예산 초과")
                            except Exception as e9:  # noqa: BLE001 [fallback]
                                results[futs[fu]] = e9
                    finally:
                        ex9.shutdown(wait=False, cancel_futures=True)
                for h, blk in cands:
                    snap = results.get(h)
                    if isinstance(snap, Exception) or snap is None:
                        if blk is None:
                            log.warning("%s 백필 detail %s 블록 확인 실패 — 체크포인트 유지: %s",
                                        w[:10], h[:12], snap)
                            return False
                        log.warning("%s 백필 detail %s 실패 → pending 큐: %s", w[:10], h[:12], snap)
                        addr_tier.tier_mark(self, h, [w])
                        self.pending_detail[h] = 0
                        continue
                    try:
                        detail_blk = int(snap["tx"]["block_number"])
                    except (KeyError, TypeError, ValueError):
                        if blk is None:
                            return False
                        addr_tier.tier_mark(self, h, [w])
                        self.pending_detail[h] = 0
                        continue
                    if not (since0 < detail_blk <= safe0):
                        continue
                    try:
                        self.emit(h, snap, head)
                    except Exception as e:  # noqa: BLE001 [fallback]
                        log.error("inbox append 실패 — 체크포인트 유지: %s", e)
                        return False
                    self.emitted.add(h.lower())
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                ck["pages"] = int(ck.get("pages", 0)) + 1
                budget -= 1
                if (oldest is not None and oldest <= since0) or not npp:
                    ck["ep"] = int(ck["ep"]) + 1
                    ck["npp"] = None
                elif not isinstance(npp, dict):
                    log.warning("%s %s next_page_params 형식 오류 — 체크포인트 유지", w[:10], ep)
                    return False
                else:
                    ck["npp"] = npp
                if int(ck["pages"]) % self.BF_FLUSH_EVERY == 0:
                    statefile.atomic_write_json(self.enrich_path, self.enrich)
                    statefile.atomic_write_json(
                        paths.state(f"pending_detail_{self.chain}.json"),
                        self.pending_detail)
                    statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
                    statefile.atomic_write_json(self.cursor_path, self.cursor)
                if int(ck["pages"]) % 50 == 0:
                    log.info("%s 백필 진행: %d페이지 누적, endpoint %d/3",
                             w[:10], int(ck["pages"]), int(ck["ep"]))
                time.sleep(0.3)
            if int(ck["ep"]) >= len(eps):
                self.cursor[w] = safe0
                self.cursor.pop("_bf:" + w, None)
                log.info("★%s 백필 완주 (%d페이지) — 커서 %d★", w[:10], int(ck.get("pages", 0)), safe0)
                return True
            why = "시간" if time.time() >= deadline else "페이지"
            log.info("%s 백필 %s예산 소진 (%d페이지 누적, endpoint %d/3) — 다음 사이클 계속",
                     w[:10], why, int(ck.get("pages", 0)), int(ck["ep"]))
            return False
        finally:
            statefile.atomic_write_json(self.enrich_path, self.enrich)
            statefile.atomic_write_json(
                paths.state(f"pending_detail_{self.chain}.json"),
                self.pending_detail)
            statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
            statefile.atomic_write_json(self.cursor_path, self.cursor)

    BF2_TIME_BUDGET = 240
    BF2_EPS = (("transactions", "hash"), ("token-transfers", "transaction_hash"),
               ("internal-transactions", "transaction_hash"))
    BF2_FLUSH_EMITS = 50

    def _bf2_spool_path(self, job: dict) -> str:
        return paths.state(f"bfspool_{self.chain}_{int(job['id'])}.jsonl")

    def _bf2_persist(self):
        statefile.atomic_write_json(self.enrich_path, self.enrich)
        statefile.atomic_write_json(paths.state(f"pending_detail_{self.chain}.json"),
                                 self.pending_detail)
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        statefile.atomic_write_json(self.cursor_path, self.cursor)

    def _bf2_new_job(self, first_ws: list, safe_now: int):
        groups = {}
        wsm = getattr(self, "wallet_since", None) or {}
        for w in first_ws:
            ck = self.cursor.get("_bf:" + w)
            if isinstance(ck, dict) and "safe" in ck and "since" in ck:
                key = (int(ck["since"]), int(ck["safe"]))
            else:
                key = ("new", wsm.get(w))
            groups.setdefault(key, []).append(w)
        key = next((k for k in groups if not isinstance(k[0], str)), None)
        if key is None:
            nk = sorted(groups, key=lambda k9: (k9[1] is None, k9[1] or 0))[0]
            since0 = 0 if self.backfill else self.window_start_block(safe_now, self.backfill_months, self.bpd)
            if nk[1] and since0 > 0:
                since0 = min(since0, self.window_start_block_ts(nk[1]))
            key = (since0, safe_now)
            wallets = sorted(groups[nk])
        else:
            wallets = sorted(groups[key])
        job = {"v": 2, "id": int(time.time() * 1000), "wallets": wallets, "since": int(key[0]),
               "safe": int(key[1]), "phase": "collect", "spool_off": 0, "rows": 0, "emit_i": 0,
               "t0": int(time.time()), "streams": {}}
        for w in wallets:
            for ep, _hk in self.BF2_EPS:
                job["streams"][f"{w}|{ep}"] = {"npp": None, "done": False, "pages": 0, "oldest": None}
            self.cursor["_bf:" + w] = {"since": job["since"], "safe": job["safe"], "ep": 0, "npp": None,
                                       "pages": 0, "v2": True}
        self.cursor["_bfjob"] = job
        self._bf2_persist()
        log.info("★%s 백필 v2 잡 시작: 지갑 %d (%s) 창 %d → %d★", self.chain, len(wallets),
                 ",".join(w[:10] for w in wallets), job["since"], job["safe"])
        return job

    def _cov_block(self, w: str, target_blk: int):
        v = self.cursor.get("_cov:" + w)
        if isinstance(v, int):
            return v
        hint = bf_engine.SINCE.covered_hint(self.chain)
        if hint:
            hb = getattr(self, "_hint_blk", None)
            if not hb or hb[0] != hint:
                hb = self._hint_blk = (hint, self.window_start_block_ts(hint))
            return min(hb[1], int(self.cursor.get(w, 0) or 0))
        return int(self.cursor.get(w, 0) or 0)

    def window_start_block_ts(self, ts: int) -> int:
        safe = getattr(self, "_max_head", 0) or self.head_block()
        return bf_engine.block_at_ts(self._block_ts, int(ts), 0, int(safe))

    def _bs_has_rows(self, w: str, blk: int):
        if self.idx_guard:
            seen9 = getattr(self, "_idx_seen", None)
            if not seen9 or seen9[0] not in ("ok", "internal") or getattr(self, "_idx_unknown", None):
                return None
        d = http_json(f"{self.base}/api/v2/addresses/{w}/token-transfers", prio="bg", retries=1)
        if not isinstance(d, dict) or not isinstance(d.get("items"), list):
            return None
        return bool(d["items"])

    def _ext_maybe_needed(self) -> bool:
        if str(getattr(self, "bf_mode", "v2")) == "legacy" or not bf_engine.SINCE.target(self.chain):
            return False
        return any(isinstance(self.cursor.get(w), int) and addr_tier._evm_ext_need(self, "blockscout", w) for w in self.wallets)

    def _maybe_extend(self, head: int, safe: int):
        target = bf_engine.SINCE.target(self.chain)
        if not target:
            return None
        if isinstance(self.cursor.get("_bfjob"), dict):
            return None
        tb = getattr(self, "_ext_tb", None)
        if not tb or tb[0] != target:
            try:
                tb = self._ext_tb = (target, self.window_start_block_ts(target))
            except Exception as e:  # noqa: BLE001 [fallback]
                log.info("%s 확장 목표 블록 탐색 실패(다음 사이클): %s", self.chain, e)
                return None
        tblk = tb[1]
        need = {w: self._cov_block(w, tblk) for w in self.wallets if isinstance(self.cursor.get(w), int)}
        need = {w: c for w, c in need.items() if c > tblk + 1}
        if not need:
            return None
        job = {"v": 2, "kind": "extend", "id": int(time.time() * 1000), "wallets": sorted(need), "since": int(tblk),
               "safe": int(max(need.values())), "phase": "collect", "spool_off": 0, "rows": 0, "emit_i": 0,
               "t0": int(time.time()), "streams": {}, "target_ts": int(target)}
        for w, c in need.items():
            for ep, _hk in self.BF2_EPS:
                job["streams"][f"{w}|{ep}"] = {"npp": None, "done": False, "pages": 0, "oldest": None, "seek": int(c)}
        self.cursor["_bfjob"] = job
        self._bf2_persist()
        log.info("★%s 과거 창 확장 잡: 지갑 %d, 블록 %d → 지갑별 커버 하한(최대 %d) — 목표 %s★", self.chain, len(need),
                 tblk, job["safe"], time.strftime("%Y-%m-%d", time.gmtime(target)))
        return job

    @staticmethod
    def _bf2_int_deferred(job: dict, key: str) -> bool:
        return bool(job.get("int_lag")) and job.get("kind") != "extend" and key.endswith("|internal-transactions")

    def _bf2_frac(self, job: dict) -> float:
        tot = 0.0
        for key9, st in job["streams"].items():
            top = int(st.get("seek") if st.get("seek") is not None else job["safe"])
            span = max(1, top - job["since"])
            if st.get("done") or self._bf2_int_deferred(job, key9):
                tot += 1.0
            elif st.get("oldest") is not None:
                tot += min(1.0, max(0.0, (top - int(st["oldest"])) / span))
        return tot / max(1, len(job["streams"]))

    def _bf2_collect(self, job: dict, deadline: float) -> bool:
        path = self._bf2_spool_path(job)
        if os.path.exists(path) and os.path.getsize(path) > int(job["spool_off"]):
            with open(path, "r+b") as f:
                f.truncate(int(job["spool_off"]))
        errs = {}
        while time.time() < deadline:
            todo = [k for k, st in job["streams"].items() if not st.get("done") and not self._bf2_int_deferred(job, k)]
            if not todo:
                return True
            progressed = False
            for key in todo:
                if time.time() >= deadline:
                    break
                st = job["streams"][key]
                w, ep = key.split("|", 1)
                hk = dict(self.BF2_EPS)[ep]
                url = f"{self.base}/api/v2/addresses/{w}/{ep}"
                npp0 = st.get("npp")
                if not isinstance(npp0, dict) and st.get("seek") is not None and int(st.get("pages", 0)) == 0:
                    npp0 = {"block_number": int(st["seek"]) + 1, "index": 0}
                    if ep == "internal-transactions":
                        npp0["transaction_index"] = 0
                if isinstance(npp0, dict):
                    url += "?" + urllib.parse.urlencode(npp0)
                try:
                    d = http_json(url, prio="bg", deadline=deadline)
                except bf_engine.NetError as e:
                    errs[e.kind] = errs.get(e.kind, 0) + 1
                    st["errs"] = int(st.get("errs", 0)) + 1
                    if e.kind in ("circuit", "budget", "quota"):
                        log.info("%s v2 수집 보류(%s) — 다음 사이클 같은 페이지부터", self.chain, str(e)[:100])
                        self.progress.update(f"{self.chain}:job", errors=errs, note=str(e)[:120])
                        return False
                    log.warning("%s v2 %s %s 페이지 실패(p%d, 누계 %d) — 체크포인트 유지: %s", self.chain, w[:10],
                                ep, int(st["pages"]), int(st["errs"]), str(e)[:120])
                    continue
                if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                    errs["payload"] = errs.get("payload", 0) + 1
                    log.warning("%s v2 %s %s 응답 형식 오류 — 체크포인트 유지", self.chain, w[:10], ep)
                    continue
                rows, oldest = [], None
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    h = it.get(hk)
                    if not isinstance(h, str) or not h:
                        continue
                    raw_blk = it.get("block_number")
                    if raw_blk is None:
                        raw_blk = it.get("block")
                    blk = None
                    if raw_blk is not None:
                        try:
                            blk = int(raw_blk)
                        except (TypeError, ValueError):
                            blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (job["since"] < blk <= job["safe"]):
                            continue
                    rows.append({"k": key, "h": h.lower(), "b": blk, "it": it})
                npp = d.get("next_page_params")
                if oldest is None and isinstance(npp, dict) and npp.get("block_number") is not None:
                    try:
                        oldest = int(npp["block_number"])
                    except (TypeError, ValueError):
                        pass
                if npp is not None and not isinstance(npp, dict):
                    log.warning("%s v2 %s %s next_page_params 형식 오류 — 체크포인트 유지", self.chain, w[:10], ep)
                    continue
                if rows:
                    with open(path, "ab") as f:
                        f.write(b"".join((json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
                                         .encode("utf-8") for r in rows))
                        f.flush()
                        os.fsync(f.fileno())
                        job["spool_off"] = f.tell()
                    job["rows"] = int(job["rows"]) + len(rows)
                st["pages"] = int(st["pages"]) + 1
                if oldest is not None:
                    st["oldest"] = oldest
                if (oldest is not None and oldest <= job["since"]) or not npp:
                    st["done"], st["npp"] = True, None
                else:
                    st["npp"] = npp
                mir = self.cursor.get("_bf:" + w)
                if isinstance(mir, dict):
                    mir["pages"] = int(mir.get("pages", 0)) + 1
                statefile.atomic_write_json(self.cursor_path, self.cursor)
                progressed = True
                self.progress.update(f"{self.chain}:job", phase="collect" if job.get("kind") != "extend" else "extend",
                                     unit="frac", since_block=job["since"], safe_block=job["safe"],
                                     done=round(self._bf2_frac(job), 4), total=1.0,
                                     pages=sum(int(s["pages"]) for s in job["streams"].values()),
                                     rows=int(job["rows"]), wallets=len(job["wallets"]), errors=errs or None)
                errs = {}
            if not progressed:
                time.sleep(2.0)
        return not [k for k, st in job["streams"].items() if not st.get("done") and not self._bf2_int_deferred(job, k)]

    @staticmethod
    def _bf2_tx_ok(tx: dict) -> bool:
        try:
            int(tx["block_number"])
            int(tx["value"] or 0)
            fee = tx["fee"]
            if not isinstance(fee, dict) or fee.get("value") is None:
                return False
            int(fee["value"])
        except (KeyError, TypeError, ValueError):
            return False
        return tx.get("status") in ("ok", "error") and tx.get("is_pending_update") is not True \
            and tsfix.ts_valid(tx.get("timestamp"))

    def _bf2_groups(self, job: dict):
        groups = {}
        path = self._bf2_spool_path(job)
        if not os.path.exists(path):
            return groups
        with open(path, "rb") as f:
            data = f.read(int(job["spool_off"]))
        for line in data.splitlines():
            if not line.strip():
                continue
            r = json.loads(line.decode("utf-8"))
            h, it, ep = r["h"], r["it"], r["k"].split("|", 1)[1]
            g = groups.setdefault(h, {"tx": None, "tt": {}, "it": {}, "b": None, "nob": False})
            g.setdefault("ws", set()).add(str(r["k"]).split("|", 1)[0].lower())
            if r.get("b") is None:
                g["nob"] = True
            elif g["b"] is None:
                g["b"] = int(r["b"])
            if ep == "transactions":
                if g["tx"] is None:
                    g["tx"] = it
            elif ep == "token-transfers":
                k = (it.get("log_index"), it.get("block_hash") or it.get("block_number"))
                if k[0] is None:
                    k = json.dumps(it, sort_keys=True)
                g["tt"].setdefault(json.dumps(k, sort_keys=True, default=str), it)
            else:
                def _a(x):
                    return (x.get("hash") if isinstance(x, dict) else x) or ""
                k = (it.get("index"), it.get("block_number"), _a(it.get("from")).lower(), _a(it.get("to")).lower(),
                     str(it.get("value")))
                g["it"].setdefault(json.dumps(k, default=str), it)
        return groups

    def _bf2_snapshot(self, h: str, g: dict):
        tts = list(g["tt"].values())
        its = list(g["it"].values())
        if g["tx"] is not None:
            tx = dict(g["tx"])
            if not self._bf2_tx_ok(tx):
                return None
        else:
            if its:
                return None
            if not tts:
                return None
            src = tts[0]
            if not tsfix.ts_valid(src.get("timestamp")):
                return None
            tx = {"hash": src.get("transaction_hash") or h, "from": src.get("from"), "to": src.get("to"),
                  "value": "0", "fee": {"value": "0"}, "status": "ok",
                  "raw_input": "0x01",
                  "timestamp": src.get("timestamp"), "block_number": int(src.get("block_number")),
                  "block_hash": src.get("block_hash"), "synth": "bs_list"}
        return {"tx": tx, "token_transfers": tts, "internal": its, "src": "bs_list"}

    def _bf2_emit(self, job: dict, head: int, deadline: float) -> bool:
        groups = self._bf2_groups(job)
        order = sorted(groups, key=lambda x: (groups[x]["b"] if groups[x]["b"] is not None else -1, x))
        n = len(order)
        i = int(job.get("emit_i", 0))
        since0, safe0 = int(job["since"]), int(job["safe"])
        n_detail = n_list = 0
        since_flush = 0
        other_pending = any(w not in job["wallets"] and not isinstance(self.cursor.get(w), int) for w in self.wallets)
        try:
            while i < n:
                if time.time() >= deadline:
                    return False
                h = order[i]
                g = groups[h]
                ws9 = sorted(g.get("ws") or ()) or list(job["wallets"])
                addr_tier.tier_mark_if_live(self, h, ws9)
                if h in self.emitted or h in self.pending_detail:
                    i += 1
                    continue
                snap = None
                b9 = g["b"] if g["b"] is not None else int(job.get("safe") or 0)
                behind_pending = any(w not in job["wallets"] and isinstance(self.cursor.get(w), int) and int(self.cursor[w]) < b9
                                     for w in self.wallets)
                need_detail = g["nob"] or (h in self._prev_emitted) or other_pending or behind_pending
                if not need_detail:
                    snap = self._bf2_snapshot(h, g)
                    need_detail = snap is None
                if need_detail:
                    try:
                        snap = self.fetch_detail(h)
                        n_detail += 1
                    except Exception as e:  # noqa: BLE001 [isolate]
                        if g["b"] is None:
                            nf = job.setdefault("nob_fail", {})
                            nf[h] = int(nf.get(h, 0)) + 1
                            if nf[h] < 3:
                                log.warning("%s v2 %s 블록 미상·상세 실패(%d) — 잡 보류(다음 사이클): %s", self.chain,
                                            h[:12], nf[h], str(e)[:100])
                                return False
                            log.warning("%s v2 %s 블록 미상 항목 3회 상세 실패 — 건너뜀(미채굴 추정)", self.chain, h[:12])
                            i += 1
                            job["emit_i"] = i
                            continue
                        log.warning("%s v2 detail %s 실패 → pending 큐: %s", self.chain, h[:12], str(e)[:100])
                        addr_tier.tier_mark(self, h, ws9)
                        self.pending_detail[h] = 0
                        i += 1
                        job["emit_i"] = i
                        continue
                else:
                    n_list += 1
                try:
                    blk = int(snap["tx"]["block_number"])
                except (KeyError, TypeError, ValueError):
                    addr_tier.tier_mark(self, h, ws9)
                    self.pending_detail[h] = 0
                    i += 1
                    continue
                part_int = (not need_detail and job.get("kind") != "extend")
                if job.get("int_lag") and (not (snap.get("internal") or []) or part_int) and not (h in self._prev_emitted or other_pending or behind_pending):
                    snap = self._int_mark(snap)
                if since0 < blk <= safe0:
                    self.emit(h, snap, head)
                    self.emitted.add(h)
                    since_flush += 1
                i += 1
                job["emit_i"] = i
                if since_flush >= self.BF2_FLUSH_EMITS:
                    since_flush = 0
                    self._bf2_persist()
                    self.progress.update(f"{self.chain}:job", phase="emit", unit="tx", done=i, total=n)
        finally:
            job["emit_i"] = i
            self._bf2_persist()
            self.progress.update(f"{self.chain}:job", phase="emit", unit="tx", done=i, total=n)
            if n_detail or n_list:
                log.info("%s v2 방출 %d/%d (리스트 합성 %d · 상세 %d)", self.chain, i, n, n_list, n_detail)
        return True

    def _bf2_step(self, first_ws: list, head: int, safe_now: int) -> bool:
        deadline = time.time() + self.bf2_budget
        self._bf2_persist()
        job = self.cursor.get("_bfjob")
        if not isinstance(job, dict) or job.get("v") != 2:
            job = self._bf2_new_job(first_ws, safe_now)
        if getattr(self, "_int_lag_now", False) and not job.get("int_lag"):
            job["int_lag"] = True
            self._bf2_persist()
        if job["phase"] == "collect":
            if not self._bf2_collect(job, deadline):
                self._bf2_persist()
                fr = self._bf2_frac(job)
                log.info("%s v2 수집 %.0f%% (페이지 %d, 행 %d) — 다음 사이클 계속", self.chain, fr * 100,
                         sum(int(s["pages"]) for s in job["streams"].values()), int(job["rows"]))
                return False
            job["phase"] = "emit"
            self._bf2_persist()
            log.info("%s v2 수집 완주 (페이지 %d, 행 %d, %.0f초) — 방출 단계", self.chain,
                     sum(int(s["pages"]) for s in job["streams"].values()), int(job["rows"]),
                     time.time() - int(job["t0"]))
        if not self._bf2_emit(job, head, deadline):
            return False
        if job.get("int_lag"):
            self._int_pending_add(job)
        for w in job["wallets"]:
            if job.get("kind") == "extend":
                self.cursor["_cov:" + w] = int(job["since"])
                continue
            self.cursor[w] = max(int(self.cursor.get(w, 0) or 0), int(job["safe"]))
            self.cursor["_cov:" + w] = int(job["since"])
            self.cursor.pop("_bf:" + w, None)
        self.cursor.pop("_bfjob", None)
        self._bf2_persist()
        try:
            os.remove(self._bf2_spool_path(job))
        except OSError:
            pass
        took = time.time() - int(job["t0"])
        log.info("★%s 백필 v2 완주: 지갑 %d, 커서 %d, %.1f분★", self.chain, len(job["wallets"]), job["safe"],
                 took / 60)
        self.progress.finish(f"{self.chain}:job", note=f"완주 {len(job['wallets'])}지갑 {took / 60:.1f}분")
        return True

    INT_EMPTY_RETRY = 5

    @staticmethod
    def _int_mark(snap: dict) -> dict:
        s = dict(snap)
        tx = dict(s.get("tx") or {})
        if tx.get("synth") != "rpc":
            tx["synth_was"] = tx.get("synth")
        tx["synth"] = "rpc"
        s["tx"] = tx
        s["int_pending"] = True
        return s

    def _int_pending_add(self, job: dict):
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            m = {"v": 1, "ranges": [], "hashes": [], "emit_i": 0, "created": int(time.time())}
        lo = int(job["since"])
        hi_max = lo
        for w in job["wallets"]:
            st = job["streams"].get(f"{w}|transactions") or {}
            hi = int(st.get("seek") if st.get("seek") is not None else job["safe"])
            if hi <= lo:
                continue
            hi_max = max(hi_max, hi)
            m["ranges"].append({"wallet": w, "from_block": lo, "to_block": hi, "since": job.get("target_ts"),
                                "job": job.get("id"), "npp": None, "done": False, "pages": 0})
        if job.get("target_ts"):
            m["from_ts"] = min(int(m.get("from_ts") or job["target_ts"]), int(job["target_ts"]))
        else:
            f9 = self._int_est_ts(lo)
            if f9:
                m["from_ts"] = min(int(m.get("from_ts") or f9), f9)
        try:
            hts = self._block_ts(hi_max)
            m["to_ts"] = max(int(m.get("to_ts") or 0), int(hts))
        except Exception as e:  # noqa: BLE001 [optional]
            log.info("%s internal 대기 구간 끝 시각 미확보(표시만 영향): %s", self.chain, e)
        m["ratio"] = getattr(self, "_idx_ratio", None)
        self.cursor["_ext_internal_pending"] = m
        log.warning("★%s %s 완료(tx·토큰) — internal(내부 ETH 이동)은 탐색기 색인 미완(%s)이라 블록 %d → %d 를 "
                    "'나중에 채우기'로 표시(색인 완료 시 자동 재훑기)★", self.chain,
                    "과거 창 확장" if job.get("kind") == "extend" else "새 지갑 첫 백필", m.get("ratio"), lo, hi_max)

    def _int_est_ts(self, blk: int):
        hts, hb = getattr(self, "_head_ts", None), getattr(self, "_max_head", 0)
        if not hts or not hb:
            return None
        bsec = getattr(self, "_hb_bsec", None) or (86400.0 / max(1, self.bpd))
        return int(hts - max(0, hb - int(blk)) * bsec)

    def _int_head_pending(self, w: str, lo: int, hi: int):
        if hi <= lo:
            return
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            m = {"v": 1, "ranges": [], "hashes": [], "emit_i": 0, "created": int(time.time())}
            self.cursor["_ext_internal_pending"] = m
        rs = m.setdefault("ranges", [])
        for r in reversed(rs):
            if (isinstance(r, dict) and r.get("wallet") == w and r.get("kind") == "head" and not r.get("done")
                    and r.get("npp") is None and not int(r.get("pages", 0) or 0)
                    and int(r["from_block"]) <= lo <= int(r["to_block"])):
                r["to_block"] = max(int(r["to_block"]), int(hi))
                break
        else:
            rs.append({"wallet": w, "from_block": int(lo), "to_block": int(hi), "kind": "head", "since": None, "job": None,
                       "npp": None, "done": False, "pages": 0})
            log.info("%s %s 증분 발견(tx·토큰) 블록 %d → %d — internal 은 '나중에 채우기' 표식(색인 %s)", self.chain, w[:10], lo, hi,
                     getattr(self, "_idx_ratio", None))
        f9, t9 = self._int_est_ts(lo), self._int_est_ts(hi)
        if f9:
            m["from_ts"] = min(int(m.get("from_ts") or f9), f9)
        if t9:
            m["to_ts"] = max(int(m.get("to_ts") or 0), t9)
        m["ratio"] = getattr(self, "_idx_ratio", None)
        m.pop("started", None)

    def _int_rescan_step(self, head: int, deadline: float) -> bool:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict):
            return True
        self._bf2_persist()
        ranges = [r for r in (m.get("ranges") or []) if isinstance(r, dict)]
        hashes = m.setdefault("hashes", [])
        seen = set(hashes)
        if not m.get("started"):
            m["started"] = int(time.time())
            log.info("★%s 탐색기 internal 색인 완료 — internal 늦은 채움 재훑기 시작(구간 %d: 과거 창·첫 백필·증분)★", self.chain, len(ranges))
        wl = set(self.wallets)
        for r in ranges:
            while not r.get("done"):
                if r.get("wallet") not in wl:
                    r["done"], r["npp"] = True, None
                    break
                if time.time() >= deadline:
                    statefile.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                w, lo, hi = r["wallet"], int(r["from_block"]), int(r["to_block"])
                npp = r.get("npp") if isinstance(r.get("npp"), dict) else \
                    {"block_number": hi + 1, "index": 0, "transaction_index": 0}
                url = f"{self.base}/api/v2/addresses/{w}/internal-transactions?" + urllib.parse.urlencode(npp)
                try:
                    d = http_json(url, prio="bg", deadline=deadline)
                except bf_engine.NetError as e:
                    log.info("%s internal 재훑기 %s 보류(다음 사이클 같은 페이지부터): %s", self.chain, w[:10], str(e)[:120])
                    statefile.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                if not isinstance(d, dict) or not isinstance(d.get("items"), list) or \
                        (d.get("next_page_params") is not None and not isinstance(d.get("next_page_params"), dict)):
                    log.warning("%s internal 재훑기 %s 응답 형식 오류 — 체크포인트 유지", self.chain, w[:10])
                    statefile.atomic_write_json(self.cursor_path, self.cursor)
                    return False
                oldest = None
                for it in d["items"]:
                    if not isinstance(it, dict) or not isinstance(it.get("transaction_hash"), str):
                        continue
                    blk = it.get("block_number", it.get("block"))
                    try:
                        blk = int(blk) if blk is not None else None
                    except (TypeError, ValueError):
                        blk = None
                    if blk is not None:
                        oldest = blk if oldest is None else min(oldest, blk)
                        if not (lo < blk <= hi):
                            continue
                    h = it["transaction_hash"].lower()
                    if h not in seen:
                        seen.add(h)
                        hashes.append(h)
                    fa, ta = it.get("from"), it.get("to")
                    k9 = json.dumps((it.get("index"), it.get("block_number"),
                                     str((fa.get("hash") if isinstance(fa, dict) else fa) or "").lower(),
                                     str((ta.get("hash") if isinstance(ta, dict) else ta) or "").lower(), str(it.get("value"))), default=str)
                    m.setdefault("items", {}).setdefault(h, {}).setdefault(k9, it)
                nxt = d.get("next_page_params")
                if oldest is None and isinstance(nxt, dict) and nxt.get("block_number") is not None:
                    try:
                        oldest = int(nxt["block_number"])
                    except (TypeError, ValueError):
                        pass
                r["pages"] = int(r.get("pages", 0)) + 1
                r["read_at"] = int(time.time())
                if (oldest is not None and oldest <= lo) or not nxt:
                    if not self._idx_recheck():
                        log.info("%s internal 재훑기 %s 완료 표시 보류 — 색인 재확인 실패(다음 사이클 같은 페이지부터)", self.chain, w[:10])
                        statefile.atomic_write_json(self.cursor_path, self.cursor)
                        return False
                    r["done"], r["npp"] = True, None
                    r["done_at"] = int(time.time())
                else:
                    r["npp"] = nxt
                statefile.atomic_write_json(self.cursor_path, self.cursor)
        i = int(m.get("emit_i", 0))
        n_full = n_retry = 0
        span = [(int(r["from_block"]), int(r["to_block"])) for r in ranges]
        try:
            while i < len(hashes):
                if time.time() >= deadline:
                    return False
                r9 = self._int_emit_one(hashes[i], m, span, head)
                if r9 == "wait":
                    return False
                if r9 == "fail":
                    if hashes[i] not in m.setdefault("retry", []):
                        m["retry"].append(hashes[i])
                    n_retry += 1
                elif r9 == "ok":
                    n_full += 1
                    if n_full % self.BF2_FLUSH_EMITS == 0:
                        m["emit_i"] = i + 1
                        self._bf2_persist()
                    time.sleep(0.12)
                i += 1
                m["emit_i"] = i
            left = []
            for h in list(m.get("retry") or []):
                if time.time() >= deadline:
                    left.append(h)
                    continue
                r9 = self._int_emit_one(h, m, span, head)
                if r9 in ("fail", "wait"):
                    left.append(h)
                elif r9 == "ok":
                    n_full += 1
            m["retry"] = left
            if left:
                return False
        finally:
            m["emit_i"] = i
            self._bf2_persist()
            if n_full or n_retry:
                log.info("%s internal 재훑기 방출 %d/%d (완전 상세 %d · 상세 실패 재시도 대기 %d)", self.chain, i, len(hashes), n_full,
                         len(m.get("retry") or []))
        if not self._idx_recheck():
            log.info("%s internal 늦은 채움 마무리 보류 — 색인 재확인 실패(다음 사이클)", self.chain)
            self._bf2_persist()
            return False
        self.cursor.pop("_ext_internal_pending", None)
        self.cursor.pop("_int_lag_since", None)
        self._bf2_persist()
        log.info("★%s internal 늦은 채움 완료 — tx %d건 재확인, 표식 제거★", self.chain, len(hashes))
        return True

    def _pending_fail(self, h: str, err, snap=None) -> bool:
        snap = err if snap is None else snap
        n9 = self.synth_fail_count(self.pending_detail, h, err)
        if n9 is None:
            log.debug("pending %s 보류(게이트·장부 거절 — 횟수 안 셈): %s", h[:12], str(err)[:120])
            return False
        if n9 > 200:
            statefile.append_durable_jsonl(
                paths.state("pending_poison.jsonl"),
                {"ts": int(time.time()), "chain": self.chain,
                 "txhash": h, "err": str(snap)[:200]})
            del self.pending_detail[h]
            log.error("★pending %s %d회 초과 — 포이즌 격리(pending_poison.jsonl)★",
                      h[:12], 200)
            return True
        log.warning("pending detail %s 재시도 실패(%d회): %s",
                    h[:12], n9, snap)
        return False

    def _int_emit_one(self, h: str, m: dict, span: list, head: int) -> str:
        rows9 = list(((m.get("items") or {}).get(h) or {}).values())

        def poison(src, err=None, n=None):
            statefile.append_durable_jsonl(paths.state("pending_poison.jsonl"),
                                        {"ts": int(time.time()), "chain": self.chain, "txhash": h, "src": src, "n": n,
                                         "err": (logs.safe_err(err)[:200] if err else None), "internal": rows9})
        try:
            snap = self.fetch_detail(h)
            blk = int(snap["tx"]["block_number"])
        except Exception as e:  # noqa: BLE001 [fallback]
            rt = m.setdefault("detail_retry", {})
            rt[h] = int(rt.get(h, 0)) + 1
            if rt[h] > self.ENRICH_FAIL_MAX:
                log.error("★%s internal 재훑기 상세 %s %d회 실패 — 격리(pending_poison.jsonl, 목록 행 보존)★", self.chain, h[:12], rt[h])
                poison("int_rescan_detail", e, rt[h])
                return "skip"
            log.warning("%s internal 재훑기 상세 %s 실패(%d회) — 표식에 남겨 다음 사이클 재시도: %s", self.chain, h[:12], rt[h], str(e)[:100])
            return "fail"
        if not any(a < blk <= b for a, b in span):
            return "skip"
        if not (snap.get("internal") or []):
            rt = m.setdefault("empty_retry", {})
            rt[h] = int(rt.get(h, 0)) + 1
            if rt[h] < self.INT_EMPTY_RETRY:
                log.info("%s internal 재훑기 %s — 목록엔 있는데 상세 internal 이 비어 있음(%d회) — 다음 사이클 재시도",
                         self.chain, h[:12], rt[h])
                return "wait"
            if not rows9:
                log.error("★%s internal 재훑기 %s — 상세 internal 이 %d회 비었고 목록 행도 없음: 방출 보류·격리(pending_poison.jsonl)★",
                          self.chain, h[:12], rt[h])
                poison("int_rescan_empty", n=rt[h])
                return "skip"
            log.warning("%s internal 재훑기 %s — 상세 internal 이 %d회 비어 있음 → 주소 목록 internal %d행으로 방출",
                        self.chain, h[:12], rt[h], len(rows9))
            snap = dict(snap, internal=rows9, internal_note="bs_addr_list")
        self.emit(h, snap, head, repair="int_fill")
        self.emitted.add(h)
        for k9 in ("empty_retry", "detail_retry", "items"):
            (m.get(k9) or {}).pop(h, None)
        self.enrich.pop(h, None)
        self.pending_detail.pop(h, None)
        return "ok"

    BS_DETAIL_MAX_PAGES = 200
    BS_DETAIL_MAX_ITEMS = 20_000
    BS_DETAIL_MAX_BYTES = 32 * 1024 * 1024

    def _fetch_all_items(self, path: str):
        base_url = f"{self.base}{path}"
        url = base_url
        out = []
        seen = set()
        n_pg = n_b = 0
        while True:
            d = http_json(url, breaker_5xx=False)
            if not isinstance(d, dict) or not isinstance(d.get("items"), list):
                raise RuntimeError(f"상세 목록 응답 형식 오류: {path}")
            pg9 = [x for x in d["items"] if isinstance(x, dict)]
            n_pg += 1
            try:
                n_b += len(json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError):
                raise RuntimeError(f"상세 목록 쪽 직렬화 불가: {path}")
            out.extend(pg9)
            if len(out) > self.BS_DETAIL_MAX_ITEMS or n_b > self.BS_DETAIL_MAX_BYTES:
                raise BsDetailCap(f"상세 목록 상한 초과({n_pg}쪽 · {len(out):,}개 · {n_b:,}바이트 > {self.BS_DETAIL_MAX_ITEMS:,}개·"
                                  f"{self.BS_DETAIL_MAX_BYTES:,}바이트) — 부분 목록은 완전 상세로 쓰지 않음: {path}")
            npp = d.get("next_page_params")
            if not npp:
                return out
            if n_pg >= self.BS_DETAIL_MAX_PAGES:
                raise BsDetailCap(f"상세 목록 쪽 상한 {self.BS_DETAIL_MAX_PAGES}쪽 초과(다음 쪽 커서 남음 · {len(out):,}개) — "
                                  f"부분 목록은 완전 상세로 쓰지 않음: {path}")
            if not isinstance(npp, dict):
                raise RuntimeError(f"상세 페이지 커서 형식 오류: {path}")
            marker = json.dumps(npp, sort_keys=True, separators=(",", ":"))
            if marker in seen:
                raise RuntimeError(f"상세 페이지 커서 반복: {path}")
            seen.add(marker)
            url = base_url + "?" + urllib.parse.urlencode(npp)

    def fetch_detail(self, txhash: str, accept_pending: bool = False):
        tx = http_json(f"{self.base}/api/v2/transactions/{txhash}", breaker_5xx=False)
        if not isinstance(tx, dict) or str(tx.get("hash") or "").lower() != txhash.lower():
            raise RuntimeError(f"tx 상세 응답 불일치: {txhash}")
        try:
            int(tx["block_number"])
            int(tx["value"] or 0)
            fee = tx["fee"]
            if not isinstance(fee, dict) or fee.get("value") is None:
                raise ValueError("fee 형식/누락")
            int(fee["value"])
        except (KeyError, TypeError, ValueError) as e:
            raise RuntimeError(f"tx 상세 필수 수치 오류: {txhash}") from e
        if tx.get("status") not in ("ok", "error"):
            raise RuntimeError(f"tx status 미확정: {txhash}")
        if tx.get("is_pending_update") is True and not accept_pending:
            raise RuntimeError(f"tx 상세가 아직 갱신 중: {txhash}")
        if not tsfix.ts_valid(tx.get("timestamp")):
            try:
                tx["timestamp"] = tsfix.block_ts(self, int(tx["block_number"]))
            except Exception as e:   # noqa: BLE001
                raise RuntimeError(f"tx 상세 시각 없음 · 블록 시각 조회 실패: {txhash}") from e
        tt = self._fetch_all_items(f"/api/v2/transactions/{txhash}/token-transfers")
        it = self._fetch_all_items(f"/api/v2/transactions/{txhash}/internal-transactions")
        return {"tx": tx, "token_transfers": tt, "internal": it}

    def emit(self, txhash: str, snapshot: dict, head: int, repair: str = None):
        rec = {
            "v": 1, "kind": "evm_tx", "chain": self.chain, "txhash": txhash,
            "snapshot": bs_dec_fill(self, snapshot),
            "wallets": self.wallets,
            "observed_head": head, "ts": int(time.time()),
        }
        if repair:
            rec["repair"] = repair
        self.writer.append(rec)
        tb9 = getattr(self, "_tier", None)
        if tb9 is not None and not repair:
            tb9.note_sent(addr_tier.sent_from(snapshot), addr_tier.snap_ts(snapshot))

    def _detail_probe_ok(self) -> bool:
        cand = [h for h in self.emitted if h not in self.enrich]
        if not cand:
            return False
        h9 = max(cand)
        try:
            snap = self.fetch_detail(h9, accept_pending=True)
            return isinstance(snap, dict) and bool(snap.get("tx"))
        except Exception as e:  # noqa: BLE001 [probe]
            log.info("enrich 5xx 판정용 상세 프로브 실패 → 포기 보류: %s", str(e)[:120])
            return False

    ENRICH_BATCH = 5
    ENRICH_FAIL_MAX = 200
    ENRICH_5XX_MAX = 5

    def _int_window_hold(self, snap: dict) -> bool:
        m = self.cursor.get("_ext_internal_pending")
        if not isinstance(m, dict) or (snap.get("internal") or []):
            return False
        try:
            blk = int((snap.get("tx") or {}).get("block_number"))
        except (TypeError, ValueError):
            return True
        return any(int(r["from_block"]) < blk <= int(r["to_block"]) for r in (m.get("ranges") or []) if isinstance(r, dict))

    def _enrich_pass(self, head: int, healthy: bool = False):
        probe = None
        for h in list(self.enrich)[:self.ENRICH_BATCH]:
            try:
                snap = self.fetch_detail(h)
            except Exception as e:  # noqa: BLE001 [isolate]
                self.enrich[h] = int(self.enrich.get(h, 0)) + 1
                giveup, src9 = self.enrich[h] > self.ENRICH_FAIL_MAX, "enrich_giveup"
                if isinstance(e, BsDetailCap):
                    giveup, src9 = True, "enrich_giveup_cap"
                elif _is_http_5xx(e):
                    if healthy:
                        if probe is None:
                            probe = self._detail_probe_ok()
                        if probe:
                            self._enrich_5xx[h] = self._enrich_5xx.get(h, 0) + 1
                            if self._enrich_5xx[h] >= self.ENRICH_5XX_MAX:
                                giveup, src9 = True, "enrich_giveup_5xx"
                else:
                    self._enrich_5xx.pop(h, None)
                if giveup:
                    n9, n5xx9 = self.enrich[h], self._enrich_5xx.get(h, 0)
                    statefile.append_durable_jsonl(
                        paths.state("pending_poison.jsonl"),
                        {"ts": int(time.time()), "chain": self.chain, "txhash": h,
                         "src": src9, "n": n9, "n5xx": n5xx9, "err": logs.safe_err(e)[:200]})
                    del self.enrich[h]
                    self._enrich_5xx.pop(h, None)
                    log.error("★enrich %s 포기(%s, 실패 누계 %d회·연속 5xx %d회) — rpc_basic 영구 확정"
                              "(잔차는 대사 흡수)★", h[:12], src9, n9, n5xx9)
                continue
            self._enrich_5xx.pop(h, None)
            if self._int_window_hold(snap):
                continue
            try:
                self.emit(h, snap, head)
                del self.enrich[h]
                log.info("★enrich %s 완전 상세 재방출 — core 승격 대상★", h[:12])
            except Exception as e:  # noqa: BLE001 [isolate]
                log.warning("enrich %s emit 실패(카운트 유지, 재시도): %s", h[:12], e)

    def cycle(self):
        tb = getattr(self, "_tier", None)
        rest_set = set()
        if tb is not None:
            addr_tier.tier_prune(self)
            addr_tier.evm_activity(self, tb)
            due9, rest9 = tb.due_list(self.wallets)
            rest_set = set(rest9)
            if not due9 and not self.pending_detail and not self.enrich and not isinstance(self.cursor.get("_bfjob"), dict) \
                    and not isinstance(self.cursor.get("_ext_internal_pending"), dict) and not self._ext_maybe_needed():
                addr_tier.idle_cycle(self, tb, "blockscout", urllib.parse.urlsplit(self.base).hostname)
                return
        head = self.head_block()
        safe = head - self.conf_depth
        all_ok = True
        tok_ok = True
        pend_deadline = time.time() + (300 if len(self.pending_detail) > 200 else 120)
        p_items = list(self.pending_detail.items())
        p_idx = 0
        while p_idx < len(p_items) and time.time() < pend_deadline:
            batch = p_items[p_idx:p_idx + 10]
            p_idx += len(batch)
            accepts = {h: cnt > 120 for h, cnt in batch}
            res_p = {}
            ex8 = ThreadPoolExecutor(max_workers=5)
            try:
                futs8 = {}
                direct8 = set()
                for h, cnt in batch:
                    if not accepts[h]:
                        futs8[ex8.submit(self._rpc_synth_detail, h)] = h
                        direct8.add(h)
                    else:
                        futs8[ex8.submit(self.fetch_detail, h, accepts[h])] = h
                for fu8 in futs8:
                    remain8 = max(0.05, pend_deadline - time.time())
                    try:
                        res_p[futs8[fu8]] = fu8.result(timeout=remain8)
                    except FutTimeout:
                        res_p[futs8[fu8]] = RuntimeError("pending 시간예산 초과 — 다음 사이클")
                    except Exception as e8:  # noqa: BLE001 [fallback]
                        res_p[futs8[fu8]] = e8
            finally:
                ex8.shutdown(wait=False, cancel_futures=True)
            for h, _ in batch:
                snap = res_p.get(h)
                if isinstance(snap, Exception) or snap is None:
                    fail9 = snap
                    if h not in direct8:
                        emitted_ok = False
                        try:
                            snap2 = self._rpc_synth_detail(h)
                            self.emit(h, snap2, head)
                            emitted_ok = True
                            self.emitted.add(h.lower())
                            del self.pending_detail[h]
                            self.enrich[h.lower()] = 0
                            log.info("pending %s RPC 합성 확정 (블록스카웃 상세 불능 대체)", h[:12])
                            continue
                        except Exception as e9r:  # noqa: BLE001 [isolate]
                            if emitted_ok:
                                log.warning("pending %s 합성 emit 후 정리 실패(카운트 유지): %s",
                                            h[:12], e9r)
                                continue
                            log.debug("rpc 합성 실패 %s: %s", h[:12], e9r)
                            fail9 = e9r
                    self._pending_fail(h, fail9, snap)
                    continue
                if accepts[h]:
                    log.warning("pending %s 120회 초과 — is_pending_update 수용 확정", h[:12])
                try:
                    self.emit(h, snap, head)
                    self.emitted.add(h.lower())
                    del self.pending_detail[h]
                    if not accepts[h]:
                        self.enrich[h.lower()] = 0
                except Exception as e:  # noqa: BLE001 [isolate]
                    log.warning("pending %s emit 실패(카운트 유지 %d): %s",
                                h[:12], self.pending_detail.get(h, 0), e)
        idx_state = self._indexing_state() if self.idx_guard else "ok"
        idx_known9 = idx_state
        if self.idx_guard and getattr(self, "_idx_unknown", None):
            idx_known9 = None
            idx_state = "blocks"
        idx_ok = idx_state == "ok"
        ext_idx_ok = idx_ok or (idx_state == "internal" and self.idx_guard_scope != "all")
        head_idx_ok = ext_idx_ok
        int_lag_now = self._int_lag_now = (not idx_ok) or not self._idx_stable()
        self._idx_note(idx_ok, idx_state, head_idx_ok)
        if idx_known9 == "internal":
            self.cursor["_ext_internal_lag"] = {"ts": int(time.time()), "ratio": getattr(self, "_idx_ratio", None)}
        elif idx_ok:
            self.cursor.pop("_ext_internal_lag", None)
        self._int_lag_track(idx_known9)
        ipm = self.cursor.get("_ext_internal_pending")
        if isinstance(ipm, dict):
            ipm["ratio"] = getattr(self, "_idx_ratio", None) if idx_state != "ok" else None
        if not idx_ok:
            all_ok = False
        if not idx_ok or isinstance(self.cursor.get("_ext_internal_pending"), dict):
            self.cursor.pop("_synced_at", None)
            _revoke_stamp_disk(self.cursor_path, tok=False)
        if getattr(self, "_idx_unknown", None) or not head_idx_ok:
            self.cursor.pop("_synced_tok_at", None)
            _revoke_stamp_disk(self.cursor_path, tok=True)
        first_ws = []
        for w in (self.wallets if head_idx_ok else []):
            first = w not in self.cursor
            since = int(self.cursor.get(w, 0))
            eff_since = max(0, since - self.rescan_overlap) if (self.rescan_overlap and
                                                                not first) else since
            if first:
                if not self.backfill and self.backfill_months <= 0:
                    self.cursor[w] = safe
                    log.info("%s 첫 가동 — 커서를 %d 로 초기화(등록 시점부터 추적)", w[:10], safe)
                    continue
                all_ok = tok_ok = False
                if self.bf_mode == "legacy":
                    if idx_ok and self._idx_stable():
                        self._first_sync_walk(w, head, safe)
                else:
                    first_ws.append(w)
                continue
            if w in rest_set:
                continue
            found = self.discover(w, eff_since, safe, skip_internal=int_lag_now)
            if found and tb is not None:
                tb.clear_empty(w, "rows")
            if found is None:
                all_ok = tok_ok = False
                _revoke_stamp_disk(self.cursor_path)
                self.fail_streak[w] = self.fail_streak.get(w, 0) + 1
                n9 = self.fail_streak[w]
                lv = bf_engine.LogDebounce.level(n9)
                if n9 in (20, 100):
                    log.error("★%s discovery %d회 연속 실패 — 이 지갑 추적이 멈춰 있음(커서 %d): %s",
                              w[:10], n9, since, getattr(self, "_disc_err", ""))
                elif lv:
                    getattr(log, lv)("%s discovery 실패 %d회 연속(커서 유지, 다음 사이클 재시도): %s", w[:10], n9,
                                     getattr(self, "_disc_err", ""))
                continue
            self.fail_streak[w] = 0
            ok = True
            safe_w = int(getattr(self, "_disc_safe", safe))
            ck_next = getattr(self, "_disc_ck_next", None)
            if ck_next:
                _revoke_stamp_disk(self.cursor_path)
            for h in sorted(found):
                addr_tier.tier_mark_if_live(self, h, [w])
                if h.lower() in self.emitted:
                    continue
                hinted_blk = found[h]
                try:
                    snap = self.fetch_detail(h)
                    detail_blk = int(snap["tx"]["block_number"])
                except Exception as e:  # noqa: BLE001 [fallback]
                    if hinted_blk is None:
                        log.warning("detail %s 블록 확인 실패 — 커서 유지: %s", h[:12], e)
                        ok = False
                        _revoke_stamp_disk(self.cursor_path)
                        break
                    log.warning("detail %s 실패 → pending 큐: %s", h[:12], e)
                    _revoke_stamp_disk(self.cursor_path)
                    addr_tier.tier_mark(self, h, [w])
                    self.pending_detail[h] = 0
                    continue
                if not (eff_since < detail_blk <= safe_w):
                    continue
                try:
                    self.emit(h, snap, head)
                    self.emitted.add(h.lower())
                except Exception as e:  # noqa: BLE001 [fallback]
                    log.error("inbox append 실패 — 커서 미전진: %s", e)
                    ok = False
                    _revoke_stamp_disk(self.cursor_path)
                    break
                time.sleep(0.12)
            if ok and ck_next:
                self.cursor["_disc:" + w] = ck_next
                all_ok = tok_ok = False
            elif ok:
                if int_lag_now:
                    self._int_head_pending(w, since, safe_w)
                self.cursor[w] = max(int(self.cursor.get(w, 0)), safe_w)
                self.cursor.pop("_disc:" + w, None)
                if tb is not None:
                    addr_tier.tier_partial(self, w, int(self.cursor[w]) < safe)
                    if (int(self.cursor[w]) >= safe and not getattr(self, "_idx_unknown", None)
                            and not addr_tier.tier_pending(self, w, enrich=False)):
                        tb.note_full(w, int(self.cursor[w]))
                if safe_w < safe:
                    all_ok = tok_ok = False
                    _revoke_stamp_disk(self.cursor_path)
            else:
                all_ok = tok_ok = False
                if tb is not None:
                    addr_tier.tier_partial(self, w, True)
        if not all_ok or self.pending_detail or self.enrich:
            self.cursor.pop("_synced_at", None)
        if not tok_ok or self.pending_detail:
            self.cursor.pop("_synced_tok_at", None)
        ext_job = isinstance(self.cursor.get("_bfjob"), dict) and self.cursor["_bfjob"].get("kind") == "extend"
        ext_job = ext_job and ext_idx_ok
        if first_ws or ext_job or (ext_idx_ok and self.bf_mode != "legacy" and self._maybe_extend(head, safe)):
            try:
                self._bf2_step(first_ws, head, safe)
            except Exception as e:  # noqa: BLE001 [boundary]
                log.error("%s v2 백필 스텝 예외(다음 사이클 재개): %s", self.chain, e)
                self._bf2_persist()
        if idx_ok and isinstance(self.cursor.get("_ext_internal_pending"), dict) and not self._idx_stable():
            s9 = self.cursor.get("_idx_ok_streak") if isinstance(self.cursor.get("_idx_ok_streak"), dict) else {}
            if time.time() - getattr(self, "_idx_wait_log", 0) >= 1800:
                self._idx_wait_log = time.time()
                log.info("%s 탐색기 색인 완료 관측 — internal 재훑기는 %d분 연속 완료 확인 뒤 시작(지금 %.0f분째)", self.chain,
                         self.IDX_STABLE_SEC // 60, (time.time() - int(s9.get("since") or time.time())) / 60)
        elif idx_ok and isinstance(self.cursor.get("_ext_internal_pending"), dict):
            try:
                self._int_rescan_step(head, time.time() + max(30.0, self.bf2_budget / 2))
            except Exception as e:  # noqa: BLE001 [boundary]
                log.error("%s internal 재훑기 예외(다음 사이클 재개): %s", self.chain, e)
                self._bf2_persist()
        if idx_ok and self._idx_stable():
            self._enrich_pass(head, healthy=all_ok)
        statefile.atomic_write_json(self.enrich_path, self.enrich)
        statefile.atomic_write_json(
            paths.state(f"pending_detail_{self.chain}.json"), self.pending_detail)
        statefile.atomic_write_json(self.emitted_path, sorted(self.emitted))
        if all_ok and not self.pending_detail and not self.enrich and "_ext_internal_pending" not in self.cursor:
            self.cursor["_synced_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_at", None)
        int_wait9 = idx_state == "internal" or isinstance(self.cursor.get("_ext_internal_pending"), dict)
        if tok_ok and head_idx_ok and int_wait9 and not self.pending_detail and not getattr(self, "_idx_unknown", None):
            self.cursor["_synced_tok_at"] = int(time.time())
        else:
            self.cursor.pop("_synced_tok_at", None)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        if tb is not None:
            addr_tier.evm_baselines(self, tb, [w for w in self.wallets if w not in rest_set])
            if head_idx_ok and not getattr(self, "_idx_unknown", None):
                addr_tier.evm_empty_probe(self, tb, self._bs_has_rows)
            tb.save()
        failed_ws = [w[:10] for w, n9 in self.fail_streak.items() if n9]
        job = self.cursor.get("_bfjob")
        ipm9 = self.cursor.get("_ext_internal_pending") if isinstance(self.cursor.get("_ext_internal_pending"), dict) else None
        int_fill9 = None
        if ipm9 and ipm9.get("ranges"):
            int_fill9 = {"state": "filling" if idx_ok else "waiting", "ratio": getattr(self, "_idx_ratio", None) if not idx_ok else None,
                         "ranges": len(ipm9["ranges"]), "from_ts": ipm9.get("from_ts"), "to_ts": ipm9.get("to_ts"),
                         "wallets": sorted({str(r.get("wallet")) for r in ipm9["ranges"] if isinstance(r, dict) and r.get("wallet")})}
        self._health_cycle("blockscout", head, safe, ok=head_idx_ok and not failed_ws,
                           err=RuntimeError("indexing-status 조회 실패(색인 상태 모름 — 발견 보류 · 커서 유지)" if getattr(self, "_idx_unknown", None)
                                            else "indexing-status 미완(발견 보류)") if not head_idx_ok else
                           RuntimeError(f"discovery 실패 지갑 {failed_ws}: {getattr(self, '_disc_err', '')}"),
                           current_source=urllib.parse.urlsplit(self.base).hostname, indexing_ok=idx_ok,
                           indexing_state=idx_state, internal_ratio=getattr(self, "_idx_ratio", None),
                           indexing_unknown=getattr(self, "_idx_unknown", None), int_fill=int_fill9,
                           wallets_failing=failed_ws, pending_detail=len(self.pending_detail), enrich=len(self.enrich),
                           backfill=({"phase": job.get("phase"), "wallets": len(job.get("wallets") or []),
                                      "rows": job.get("rows"), "emit_i": job.get("emit_i")}
                                     if isinstance(job, dict) else None))
