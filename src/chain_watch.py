from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, logs, paths  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state  # noqa: E402

LANES = ("latest", "history")


class Transient(Exception):
    pass


class Collector:
    def __init__(self, adapter: reg.ChainAdapter, writer, state: chain_state.ChainState, owners, log=None,
                 page_budget=None, detail_budget=None):
        self.ad, self.writer, self.st = adapter, writer, state
        self.owners = set(owners)
        self.log = log
        cfg9 = ((adapter.cfg or {}).get(reg.CFG_CHAIN_KEY) or {}).get(adapter.chain) if isinstance(adapter.cfg, dict) else None
        cfg9 = cfg9 if isinstance(cfg9, dict) else {}
        self.page_budget = page_budget or {"latest": int(cfg9.get("latest_pages", 5)), "history": int(cfg9.get("history_pages", 20))}
        self.detail_budget = detail_budget or {"latest": int(cfg9.get("latest_details", 50)), "history": int(cfg9.get("history_details", 200))}
        self.errors = 0
        if getattr(adapter, "state", None) is None:
            try:
                adapter.state = state
            except AttributeError:
                pass

    def _say(self, msg, *a):
        if self.log:
            self.log.info(msg, *a)

    def discover(self, lane: str) -> int:
        added = 0
        for o in sorted(self.owners):
            key = f"{lane}:{o}"
            q, fp = self.ad.discovery_query(o, lane)
            if q is None:
                continue
            ln = self.st.lane(key)
            if ln.get("fp") and ln.get("fp") != fp:
                self.st.reset_lane(key, "질의 지문 바뀜")
                ln = self.st.lane(key)
            cur = ln.get("cursor")
            for _i in range(max(0, int(self.page_budget.get(lane, 1)))):
                try:
                    items, nxt = self.ad.discover_page(o, q, cur)
                except Transient as e:
                    self.errors += 1
                    self._say("[%s] %s 발견 일시 실패(다음 주기): %s", self.ad.chain, key, logs.safe_err(e)[:120])
                    break
                added += self.st.pending_upsert([(it["stable_id"], dict(it, owner=o, lane=lane)) for it in items or ()])
                if nxt is None:
                    sf = getattr(self.ad, "lane_done", lambda *_a: None)(o, lane, q)
                    if isinstance(sf, dict):
                        self.st.d["lanes"].setdefault(key, {})["safe"] = dict(sf)
                self.st.save()
                self.st.save_cursor(key, nxt, fp)
                if nxt is None:
                    break
                cur = nxt
        return added

    def details(self, lane: str = None) -> int:
        n = 0
        for sid, p in self.st.due(limit=self.detail_budget.get(lane or "history", 50), lane=lane):
            ref = p.get("ref") or {}
            try:
                rec = self.ad.fetch_and_normalize(ref, set(self.owners))
            except Transient as e:
                self.errors += 1
                self.st.reschedule(sid, "일시 실패: " + logs.safe_err(e)[:100])
                continue
            if rec is None:
                self.st.reschedule(sid, "미확정·상세 미완")
                continue
            try:
                chain_event.validate(rec)
                if chain_event.unknown_decimals(rec):
                    self.st.reschedule(sid, "자릿수 미확인 토큰 — 보류(18 로 짐작하지 않음)")
                    continue
            except chain_event.ContractError as e:
                self.errors += 1
                for _k in range(chain_state.MAX_TRIES):
                    if self.st.reschedule(sid, "계약 위반: " + str(e)[:100]) != "retry":
                        break
                continue
            self.writer.append(rec)
            cov9 = getattr(self.ad, "covered_sids", None)
            self.st.mark_emitted(sid, rec["tx_uid"], rec.get("owners"), covered=cov9(rec) if callable(cov9) else ())
            self.st.save()
            n += 1
        return n

    def cycle(self) -> dict:
        self.errors = 0
        out = {}
        self.st.requeue_gaps(self.owners)
        for lane in LANES:
            out[lane] = (self.discover(lane), self.details(lane))
        out["left"] = len(self.st.d["pending"])
        if not self.errors and not out["left"]:
            self.st.mark_synced()
        return out


def main(chain: str, make_adapter, poll_default: int = 60):
    from inbox import SegmentWriter
    log = logs.setup_logging("tj-" + chain)
    paths.ensure_dirs()
    cfg = config.load_config()
    owners = reg.owners(cfg, chain)
    if not owners:
        raise SystemExit(f"추적할 {reg.display_name(chain)} 지갑이 없음 — config chain_wallets 확인")
    sp = reg.spec(chain)
    st = chain_state.ChainState(chain)
    st.drop_owner(owners)
    st.save()
    col = Collector(make_adapter(cfg), SegmentWriter(os.path.join(paths.INBOX_DIR, sp.stream)), st, owners, log=log)
    poll = int(((cfg.get(reg.CFG_CHAIN_KEY) or {}).get(chain) or {}).get("poll_sec", poll_default)) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else poll_default
    log.info("가동: %s %d지갑, %d초 주기", sp.name, len(owners), poll)
    try:
        while True:
            t0 = time.time()
            try:
                r = col.cycle()
                log.info("[%s] 주기: %s", chain, r)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("[%s] 주기 실패(다음 주기): %s", chain, logs.safe_err(e)[:200])
            time.sleep(max(5.0, poll - (time.time() - t0)))
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
