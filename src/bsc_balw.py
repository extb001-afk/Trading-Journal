from __future__ import annotations
import bf_engine
import logs, paths, statefile
import db as dbm
import json
import os
import time
from bsc_base import BALW_BACK_MIN
from bsc_base import BALW_BO_BASE
from bsc_base import BALW_BO_MAX
from bsc_base import BALW_CALL_CAP
from bsc_base import BALW_DAY_CAP
from bsc_base import BALW_DUST
from bsc_base import BALW_EVERY
from bsc_base import BALW_EVERY_ARCH
from bsc_base import BALW_HIST_DAYS
from bsc_base import BALW_HIST_GAP
from bsc_base import BALW_HIST_RETRY
from bsc_base import BALW_JOBS_MAX
from bsc_base import BALW_JOB_CALLS
from bsc_base import BALW_JOB_DONE_MAX
from bsc_base import BALW_JOB_KEEP
from bsc_base import BALW_NONCE_STUCK
from bsc_base import BALW_NOSTATE_N
from bsc_base import BALW_PUB_NEAR
from bsc_base import BALW_PUB_SCAN
from bsc_base import BALW_REQ_WAIT
from bsc_base import BALW_RX_MAX_H
from bsc_base import BALW_RX_NAME
from bsc_base import BALW_SCAN_BATCH
from bsc_base import BALW_SCAN_RUN
from bsc_base import BALW_STALE
from bsc_base import BALW_TIME_CAP
from bsc_base import DISC_REQ_NAME
from bsc_base import NONCE_TOP_BATCH
from bsc_base import Rpc
from bsc_base import _BalwNoArch
from bsc_base import _BalwNoState
from bsc_base import _BalwStop
from bsc_base import _NONCE_STOP_KINDS
from bsc_base import _balw_nostate
from bsc_base import _native_delta
from bsc_base import _nonce_why
from bsc_base import _now
from bsc_base import _pad_topic
from bsc_base import _touches
import logging

log = logging.getLogger('tj-bsc')


class BalwMixin:

    def _balw_path(self) -> str:
        return paths.state("bsc_balw.json")

    def _balw_load(self) -> dict:
        d = self.__dict__.get("_balw_st")
        if d is None:
            try:
                d = statefile.read_json(self._balw_path(), {})
            except SystemExit as e:
                log.warning("BSC 잔고 감시 진행 파일 손상 — 새로 시작: %s", str(e)[:120])
                d = {}
            if not isinstance(d, dict) or not isinstance(d.get("w"), dict) or not isinstance(d.get("d"), dict):
                d = {"v": 1, "w": {}, "d": {}}
            self._balw_st = d
        return d

    def _balw_save(self):
        statefile.atomic_write_json(self._balw_path(), self._balw_load())

    @staticmethod
    def _balw_lo(ws) -> "int | None":
        if not isinstance(ws, dict):
            return None
        c = []
        cp = ws.get("cp")
        if isinstance(cp, list) and len(cp) == 3 and isinstance(cp[0], int):
            c.append(cp[0])
        c += [j["a"] for j in ws.get("jobs") or [] if isinstance(j, dict) and isinstance(j.get("a"), int)]
        c += [u["a"] for u in ws.get("ux") or [] if isinstance(u, dict) and isinstance(u.get("a"), int)]
        rs = ws.get("rs")
        if isinstance(rs, dict) and isinstance(rs.get("a"), int):
            c.append(rs["a"])
        return min(c) if c else None

    def _balw_put(self, st: dict, w: str, h: str, b: int, snap: dict) -> bool:
        cur = st["d"].setdefault(w, {})
        r = _native_delta(snap, w) if _touches(snap, w) else None
        if r is None:
            return cur.pop(h, None) is not None
        v = [int(b), str(r[0]), 1 if r[1] else 0]
        if cur.get(h) == v:
            return False
        cur[h] = v
        return True

    def _balw_note(self, rec: dict):
        snap = (rec or {}).get("snapshot") or {}
        tx = snap.get("tx") or {}
        try:
            b = int(tx.get("block_number"))
        except (TypeError, ValueError):
            return
        h = str((rec or {}).get("txhash") or tx.get("hash") or "").lower()
        if not h:
            return
        st = self._balw_load()
        ch = False
        for w in self.wallets:
            lo = self._balw_lo(st["w"].get(w))
            if lo is not None and b > lo:
                ch = self._balw_put(st, w, h, b, snap) or ch
        if ch:
            self._balw_save()

    @staticmethod
    def _balw_left(cnt: dict) -> int:
        return int(cnt.get("cap") or BALW_CALL_CAP) - int(cnt["n"])

    @staticmethod
    def _balw_stop_budget(cnt: dict, why: str):
        if cnt.get("cap") is not None:
            cnt["soft"] = True
        raise _BalwStop(why)

    def _balw_charge(self, cnt: dict, n: int):
        st = self._balw_load()
        if time.time() > cnt["t_end"]:
            raise _BalwStop("실행 시간 상한")
        if cnt["n"] + n > BALW_CALL_CAP:
            raise _BalwStop("실행당 호출 상한")
        if cnt["n"] + n > int(cnt.get("cap") or BALW_CALL_CAP):
            self._balw_stop_budget(cnt, "최신 작업 몫 호출 상한")
        if cnt.get("t_soft") and time.time() > float(cnt["t_soft"]):
            self._balw_stop_budget(cnt, "최신 작업 몫 시간")
        day = time.strftime("%Y-%m-%d", time.gmtime(_now()))
        if st.get("day") != day:
            st["day"], st["day_n"] = day, 0
        if int(st.get("day_n") or 0) + n > BALW_DAY_CAP:
            raise _BalwStop("하루 호출 상한")
        cnt["n"] += n
        st["day_n"] = int(st.get("day_n") or 0) + n

    def _balw_call(self, cnt: dict, m: str, p, recent: bool = False):
        self._balw_charge(cnt, 1)
        pub = getattr(self, "nonce_pub_rpc", None)
        arch = getattr(self, "arch_rpc", None)
        last = None
        if pub is not None and (recent or arch is None):
            try:
                return pub.call(m, p, timeout=15)
            except Exception as e:   # noqa: BLE001 [fallback]
                last = e
        if arch is None:
            raise _BalwNoArch(f"옛 블록 상태를 줄 아카이브 노드 없음({logs.safe_err(last)[:80] if last else '공개 노드 없음'})")
        if float(self._balw_load().get("bo_until") or 0) > _now():
            raise _BalwStop("아카이브 쉬는 중")
        try:
            return arch.call(m, p, timeout=20)
        except _BalwStop:
            raise
        except Exception as e:   # noqa: BLE001
            if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                cnt["halt"] = e
                raise _BalwStop(_nonce_why(e)) from e
            if _balw_nostate(e):
                if pub is not None and last is None:
                    try:
                        return pub.call(m, p, timeout=15)
                    except _BalwStop:
                        raise
                    except Exception as e2:   # noqa: BLE001 [fallback]
                        last = e2
                try:
                    age = int(cnt.get("head") or 0) - int(str(p[-1]), 16)
                except (TypeError, ValueError, IndexError):
                    age = None
                if age is not None and age > BALW_PUB_SCAN:
                    raise _BalwNoState("아카이브가 그 블록 상태를 못 줌(" + _nonce_why(e)[:100] + ")") from e
            raise

    def _balw_read(self, ws_list: list, S: int, cnt: dict) -> dict:
        out = {}
        bh = hex(int(S))
        pub = getattr(self, "nonce_pub_rpc", None)
        nw = (self._nonce_load().get("w") or {})
        known = {}
        for w in ws_list:
            ws9 = nw.get(w) or {}
            try:
                if ws9.get("top") == int(S):
                    known[w] = int((ws9.get("ns") or {})[str(int(S))])
            except (KeyError, TypeError, ValueError):
                pass
        if pub is not None:
            items, slots = [], []
            for w in ws_list:
                slots.append((w, len(items), None if w in known else len(items) + 1))
                items.append(("eth_getBalance", [w, bh]))
                if w not in known:
                    items.append(("eth_getTransactionCount", [w, bh]))
            res = []
            for i in range(0, len(items), NONCE_TOP_BATCH):
                try:
                    res += list(pub.batch(items[i:i + NONCE_TOP_BATCH], timeout=15))
                except _BalwStop:
                    break
                except Exception as e:   # noqa: BLE001 [fallback]
                    log.debug("BSC 잔고 감시 — 공개 노드 배치 실패: %s", logs.safe_err(e)[:120])
                    res += [None] * len(items[i:i + NONCE_TOP_BATCH])
            for w, jb, jn in slots:
                try:
                    out[w] = (int(res[jb], 16), known[w] if jn is None else int(res[jn], 16))
                except (TypeError, ValueError, IndexError, KeyError):
                    pass
        for w in ws_list:
            if w in out or pub is not None:
                continue
            if cnt["n"] + 2 > max(2, BALW_CALL_CAP // 2):
                break
            try:
                b9 = int(self._balw_call(cnt, "eth_getBalance", [w, bh], recent=True), 16)
                n9 = int(self._balw_call(cnt, "eth_getTransactionCount", [w, bh], recent=True), 16)
                out[w] = (b9, n9)
            except _BalwStop:
                break
            except Exception as e:   # noqa: BLE001 [isolate]
                log.debug("BSC 잔고 감시 %s 블록 %d 잔고 못 읽음: %s", w[:10], S, logs.safe_err(e)[:120])
        return out

    def _balw_f(self, st: dict, w: str, job: dict, b: int) -> int:
        s = job["s"]
        a = int(job["a"])
        ex, seen = 0, set()
        for h, v in (st["d"].get(w) or {}).items():
            if a < v[0] <= b:
                ex += int(v[1])
                seen.add(h)
        for h, v in (job.get("xd") or {}).items():
            if h not in seen and a < v[0] <= b:
                ex += int(v[1])
        return int(s[str(b)]) - int(s[str(a)]) - ex

    def _balw_emit(self, h: str, snap: dict, head: int, cnt: dict):
        self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                            "observed_head": head, "ts": int(time.time()), "via": "balw"})
        self.emitted.add(h)
        cnt["emit"] += 1
        try:
            b9 = int((snap.get("tx") or {}).get("block_number"))
        except (TypeError, ValueError):
            return
        rc9 = self.__dict__.setdefault("_balw_recent", {})
        now9 = _now()
        rc9[str(h).lower()] = (b9, now9, [w9 for w9 in self.wallets if _touches(snap, w9)])
        for k9 in [k9 for k9, v9 in rc9.items() if now9 - v9[1] > BALW_REQ_WAIT]:
            rc9.pop(k9, None)

    def _balw_disc_req(self, st: dict, w: str, blk: int, bal: int, ts: int, d: int, why: str, old: bool = False) -> bool:
        it = {"chain": "bsc", "wallet": w, "ca": None, "block": int(blk), "chain_bal_raw": str(int(bal)), "block_ts": int(ts),
              "diff_raw": str(max(1, int(d))), "spam": False, "symbol": "BNB", "decimals": 18,
              "sources": ["bsc_balance_watch_old" if old else "bsc_balance_watch"]}
        pq = st.get("rqp") if isinstance(st.get("rqp"), list) else []
        if any(isinstance(e, dict) and isinstance(e.get("it"), dict) and e["it"].get("wallet") == w and e["it"].get("block") == int(blk) for e in pq):
            return False
        now9 = _now()
        rc9 = (self.__dict__.get("_balw_recent") or {}) if self is not None else {}
        aft = sorted(h for h, v in rc9.items() if v[0] <= int(blk) and w in v[2] and now9 - v[1] <= BALW_REQ_WAIT)
        miss = []
        if aft:
            got = self._balw_ingested(aft)
            miss = [h for h in aft if got is None or h not in got]
        if miss:
            st.setdefault("rqp", []).append({"it": it, "aft": miss, "t": int(now9), "why": why})
        elif not BalwMixin._balw_req_write(self, [it]):
            return False
        rq = st.setdefault("reqs", [])
        rq.append([w[:10], int(blk), str(int(d)), why, int(_now())])
        del rq[:-20]
        log.warning("★BSC 받는 쪽 BNB %s… 블록 %d +%d wei — 어느 거래인지 못 가림(%s) · 원가 미상 기초 잔고 요청(core 가 그 블록 잔고로 다시 재고 기장)%s★",
                    w[:10], int(blk), int(d), why, f" — 방금 방출한 거래 {len(miss)}건이 원장에 들어온 뒤" if miss else "")
        return True

    def _balw_req_write(self, items: list) -> bool:
        p = paths.state(DISC_REQ_NAME)
        cur = statefile.read_control_json(p, None)
        have = list(cur.get("items") or []) if isinstance(cur, dict) and isinstance(cur.get("items"), list) else []
        add = []
        for it in items:
            if any(isinstance(x, dict) and x.get("chain") == "bsc" and str(x.get("wallet") or "").lower() == it["wallet"] and x.get("block") == it["block"]
                   and x.get("ca") in (None, "", "native") for x in have + add):
                continue
            add.append(it)
        if not add:
            return False
        statefile.atomic_write_json(p, {"items": have + add, "by": "tj-bsc 잔고 감시", "ts": int(time.time())})
        return True

    def _balw_ingested(self, hs: list):
        if not os.path.exists(paths.DB_PATH):
            return set(hs)
        try:
            con = dbm.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=2)
            try:
                return {h for h in hs if con.execute("SELECT 1 FROM raw_txs WHERE chain='bsc' AND txhash=?", (h,)).fetchone()}
            finally:
                con.close()
        except Exception as e:   # noqa: BLE001 [fallback]
            log.debug("BSC 잔고 감시 — 원장 확인 실패: %s", str(e)[:120])
            return None

    def _balw_req_flush(self, st: dict) -> bool:
        pq = st.get("rqp")
        if not isinstance(pq, list) or not pq:
            return st.pop("rqp", None) is not None
        got = self._balw_ingested(sorted({h for e in pq if isinstance(e, dict) for h in (e.get("aft") or [])}))
        now9 = _now()
        keep, out = [], []
        for e in pq:
            if not isinstance(e, dict) or not isinstance(e.get("it"), dict):
                continue
            if (got is not None and all(h in got for h in e.get("aft") or [])) or now9 - float(e.get("t") or 0) > BALW_REQ_WAIT:
                out.append(e["it"])
            else:
                keep.append(e)
        if out:
            self._balw_req_write(out)
            log.info("BSC 잔고 감시 — 보류한 기초 잔고 요청 %d건 씀(앞선 거래 원장 반영 확인 또는 %d초 지남)", len(out), BALW_REQ_WAIT)
        if keep:
            st["rqp"] = keep
        else:
            st.pop("rqp", None)
        return len(keep) != len(pq)

    def _balw_resolve(self, st: dict, w: str, job: dict, y: int, d: int, head: int, cnt: dict):
        self._balw_charge(cnt, 1)
        blk = self.rpc.call("eth_getBlockByNumber", [hex(y), True]) or {}
        txs = blk.get("transactions")
        try:
            num9, ts9 = int(str(blk.get("number")), 16), int(str(blk.get("timestamp")), 16)
        except (TypeError, ValueError):
            num9, ts9 = -1, 0
        if num9 != y or not isinstance(txs, list):
            raise RuntimeError(f"블록 {y} 전체 응답 불완전")
        self.block_ts[hex(y)] = ts9
        idx = st["d"].setdefault(w, {})
        direct = []
        intx = set()
        for t in txs:
            if not isinstance(t, dict):
                continue
            h = str(t.get("hash") or "").lower()
            if h and str(t.get("to") or "").lower() == w:
                intx.add(h)
            if h and h not in idx and h not in (job.get("xd") or {}) and w in (str(t.get("from") or "").lower(), str(t.get("to") or "").lower()):
                direct.append(h)
        if direct:
            k9 = min(5, max(0, self._balw_left(cnt) // 3))
            if k9 <= 0:
                self._balw_stop_budget(cnt, "직접 거래 상세 몫 없음 — 다음 실행")
            more9 = len(direct) > k9
            direct = direct[:k9]
            self._balw_charge(cnt, 3 * len(direct))
            dets = self.fetch_details(direct, deadline=cnt["t_end"])
            if time.time() > cnt["t_end"]:
                raise _BalwStop("직접 거래 상세 마감")
            for h in direct:
                snap = dets.get(h)
                if not isinstance(snap, dict):
                    raise RuntimeError(f"블록 {y} 상세 실패 {h[:12]}: {logs.safe_err(snap)[:80]}")
                if h in self.emitted:
                    self._balw_put(st, w, h, y, snap)
                    continue
                self._balw_emit(h, snap, head, cnt)
                log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · 직접 거래) %s 블록 %d★", h[:14], y)
            statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            statefile.write_json_if_changed(self.meta_path, self.token_meta)
            if more9:
                self._balw_stop_budget(cnt, "한 블록 직접 거래 남음 — 다음 실행")
            d = self._balw_f(st, w, job, y) - self._balw_f(st, w, job, y - 1)
            if d < BALW_DUST:
                job.setdefault("done", []).append(y)
                return
        cands = sorted(h for h, v in idx.items() if v[0] == y and h not in intx)
        pick = cands[0] if len(cands) == 1 else None
        via9 = "cand" if pick else "log"
        if pick is None:
            self._balw_charge(cnt, 1)
            try:
                rcs = self.rpc.call("eth_getBlockReceipts", [hex(y)])
            except Exception as e:   # noqa: BLE001 [fallback]
                log.debug("BSC 잔고 감시 블록 %d 영수증 묶음 실패: %s", y, logs.safe_err(e)[:80])
                rcs = None
            hits = set()
            pw, wh = _pad_topic(w), w[2:]
            for rc in rcs if isinstance(rcs, list) else []:
                if not isinstance(rc, dict) or rc.get("status") != "0x1":
                    continue
                for lg in rc.get("logs") or []:
                    tps = [str(x).lower() for x in (lg.get("topics") or [])] if isinstance(lg, dict) else []
                    if pw in tps[1:] or (isinstance(lg, dict) and wh in str(lg.get("data") or "").lower()):
                        hits.add(str(rc.get("transactionHash") or "").lower())
                        break
            hits.discard("")
            hits -= intx
            pool = (set(cands) & hits) if cands else hits
            pick = next(iter(pool)) if len(pool) == 1 else None
        why9 = "로그 없는 internal · 단서 거래 없음"
        if pick:
            self._balw_charge(cnt, 3)
            snap = self.fetch_details([pick], deadline=cnt["t_end"]).get(pick)
            if time.time() > cnt["t_end"]:
                raise _BalwStop("귀속 상세 마감")
            if not isinstance(snap, dict):
                raise RuntimeError(f"블록 {y} 귀속 상세 실패 {pick[:12]}: {logs.safe_err(snap)[:80]}")
            why9 = self._balw_attr_why(snap, w, d, via9, cnt)
            if not why9:
                tx9 = snap["tx"]
                snap = dict(snap, internal=list(snap.get("internal") or []) + [
                    {"from": str(tx9.get("to") or "").lower(), "to": w, "value": str(int(d)), "success": True, "attr": "balance_delta"}],
                    internal_note="balance_delta")
                self._balw_emit(pick, snap, head, cnt)
                statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
                statefile.write_json_if_changed(self.meta_path, self.token_meta)
                log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · internal 귀속) %s 블록 %d +%d wei★", pick[:14], y, int(d))
                d = self._balw_f(st, w, job, y) - self._balw_f(st, w, job, y - 1)
                if d < BALW_DUST:
                    job.setdefault("done", []).append(y)
                    return
                why9 = "귀속 뒤 남은 차액"
        self._balw_disc_req(st, w, y, int(job["s"][str(y)]), ts9, d, why9)
        job.setdefault("done", []).append(y)

    def _balw_attr_why(self, snap: dict, w: str, d: int, via: str, cnt: dict) -> str:
        tx9 = snap.get("tx") or {}
        if tx9.get("status") != "ok":
            return "단서 거래 실패"
        src9 = str(tx9.get("to") or "").lower()
        if not src9 or src9 in {str(x9).lower() for x9 in self.wallets}:
            return "단서 거래 받는 쪽이 내 지갑(또는 생성)"
        if via == "cand" and not snap.get("token_transfers") and not snap.get("internal"):
            memo = self.__dict__.setdefault("_balw_code", set())
            if src9 not in memo:
                try:
                    code9 = self._balw_call(cnt, "eth_getCode", [src9, "latest"], recent=True)
                except _BalwStop:
                    raise
                except Exception as e:   # noqa: BLE001
                    raise RuntimeError(f"단서 거래 받는 쪽 코드 확인 실패: {logs.safe_err(e)[:80]}") from None
                if str(code9 or "0x").lower() in ("0x", "0x0", ""):
                    return "단서 거래가 코드 없는 주소로 감(internal 불가)"
                memo.add(src9)
        r0 = _native_delta(snap, w) if _touches(snap, w) else (0, False)
        r1 = _native_delta(dict(snap, internal=list(snap.get("internal") or []) + [
            {"from": src9, "to": w, "value": str(int(d)), "success": True, "attr": "balance_delta"}]), w)
        if r0 is None or r1 is None or int(r1[0]) - int(r0[0]) != int(d):
            return "귀속해도 순증이 안 맞음"
        return ""

    def _balw_pubscan(self, st: dict, w: str, job: dict, head: int, cnt: dict):
        x, y, nxt = (int(v9) for v9 in job["scan"])
        pub = getattr(self, "nonce_pub_rpc", None)
        idx = st["d"].setdefault(w, {})
        while nxt <= y:
            self._balw_charge(cnt, 0)
            n9 = min(BALW_SCAN_BATCH, y - nxt + 1)
            if int(cnt.get("scan") or 0) + n9 > int(cnt.get("scan_cap") or BALW_SCAN_RUN):
                self._balw_stop_budget(cnt, "공개 블록 본문 훑기 실행 상한")
            cnt["scan"] = int(cnt.get("scan") or 0) + n9
            res = pub.batch([("eth_getBlockByNumber", [hex(b9), True]) for b9 in range(nxt, nxt + n9)], timeout=20)
            found = []
            for b9, blk in zip(range(nxt, nxt + n9), list(res) + [None] * n9):
                try:
                    ok9 = isinstance(blk, dict) and int(str(blk.get("number")), 16) == b9 and isinstance(blk.get("transactions"), list)
                    ts9 = int(str(blk.get("timestamp")), 16) if ok9 else None
                except (TypeError, ValueError):
                    ok9 = False
                if not ok9:
                    raise RuntimeError(f"공개 블록 {b9} 본문 응답 불완전")
                self.block_ts[hex(b9)] = ts9
                for t in blk["transactions"]:
                    if not isinstance(t, dict) or str(t.get("to") or "").lower() != w:
                        continue
                    h = str(t.get("hash") or "").lower()
                    try:
                        v9 = int(str(t.get("value") or "0x0"), 16)
                    except ValueError:
                        v9 = 0
                    if h and v9 >= BALW_DUST and h not in idx:
                        found.append((b9, h))
            more9 = False
            if found:
                k9 = max(0, self._balw_left(cnt) // 3)
                if k9 <= 0:
                    self._balw_stop_budget(cnt, "공개 블록 본문 훑기 — 실행당 호출 상한")
                more9 = len(found) > k9
                found = found[:k9]
                self._balw_charge(cnt, 3 * len(found))
                dets = self.fetch_details([h for _b9, h in found], deadline=cnt["t_end"])
                if time.time() > cnt["t_end"]:
                    raise _BalwStop("공개 블록 본문 훑기 — 상세 마감")
                for b9, h in found:
                    snap = dets.get(h)
                    if not isinstance(snap, dict):
                        raise RuntimeError(f"공개 블록 {b9} 입금 상세 실패 {h[:12]}: {logs.safe_err(snap)[:80]}")
                    if h in self.emitted:
                        self._balw_put(st, w, h, b9, snap)
                        continue
                    self._balw_emit(h, snap, head, cnt)
                    log.info("★BSC 받는 쪽 BNB 회수(잔고 감시 · 공개 블록 본문 — 아카이브 없음) %s 블록 %d★", h[:14], b9)
                statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
                statefile.write_json_if_changed(self.meta_path, self.token_meta)
            if more9:
                self._balw_stop_budget(cnt, "공개 블록 본문 훑기 — 이 묶음 남은 입금은 다음 실행")
            nxt += n9
            job["scan"][2] = nxt
        rest = self._balw_f(st, w, job, y) - self._balw_f(st, w, job, x)
        if rest >= BALW_DUST:
            ts9 = self.block_ts.get(hex(y))
            if ts9 is None:
                self._balw_charge(cnt, 1)
                ts9 = self._block_time(hex(y))
            self._balw_disc_req(st, w, y, int(job["s"][str(y)]), ts9, rest, "아카이브 없음 · 직접 거래 없음(internal)")
        job.setdefault("sd", []).append([x, y])
        job.pop("scan", None)

    def _balw_close(self, st: dict, w: str, job: dict, why: str, cnt: dict):
        z = int(job["z"])
        try:
            rest = self._balw_f(st, w, job, z) - sum(max(0, self._balw_f(st, w, job, y) - self._balw_f(st, w, job, y - 1))
                                                     for y in job.get("done") or [] if str(y - 1) in job["s"] and str(y) in job["s"])
        except (KeyError, TypeError, ValueError):
            rest = BALW_DUST
        if rest >= BALW_DUST:
            ts9 = self.block_ts.get(hex(z))
            if ts9 is None:
                try:
                    self._balw_charge(cnt, 1)
                    ts9 = self._block_time(hex(z))
                except _BalwStop:
                    raise
                except Exception:   # noqa: BLE001 [fallback]
                    return False
            self._balw_disc_req(st, w, z, int(job["s"][str(z)]), ts9, rest, why, old=job.get("k") == "hist")
        return True

    def _balw_hist_cands(self, st: dict, eoas: list, now: float) -> list:
        if isinstance(self.cursor.get("_live"), dict):
            return []
        try:
            chk = statefile.read_json(paths.state("onchain_check.json"), {})
        except SystemExit:
            return []
        out, seen, open9 = [], set(), set()
        for m in (chk.get("mismatches") or []) if isinstance(chk, dict) else []:
            if not isinstance(m, dict) or m.get("chain") != "bsc" or m.get("ca") or not m.get("confirmed"):
                continue
            w = str(m.get("wallet") or "").lower()
            if w not in eoas or w in seen:
                continue
            try:
                gap = float(m.get("onchain")) - float(m.get("ledger"))
            except (TypeError, ValueError):
                continue
            if gap > 0:
                open9.add(w)
            ws = st["w"].get(w) or {}
            cp = ws.get("cp")
            if (gap <= 0 or not (isinstance(cp, list) and len(cp) == 3) or self._balw_hist_busy(ws)
                    or now - float(ws.get("hist_at") or 0) < BALW_HIST_GAP):
                continue
            seen.add(w)
            out.append((float(ws.get("hist_at") or 0), eoas.index(w), w, gap))
        for w, ws in st["w"].items():
            if isinstance(ws, dict) and "hist_wait" in ws and w not in open9:
                ws.pop("hist_wait", None)
        return [(w, gap) for _h, _i, w, gap in sorted(out)]

    @staticmethod
    def _balw_hist_busy(ws: dict) -> bool:
        return any(isinstance(j, dict) and j.get("k") == "hist" for j in ws.get("jobs") or []) or isinstance(ws.get("rs"), dict)

    @staticmethod
    def _balw_hist_end(ws: dict):
        cp = ws.get("cp")
        try:
            out = (int(cp[0]), int(cp[1]))
            for j in ws.get("jobs") or []:
                if isinstance(j, dict) and isinstance(j.get("a"), int) and int(j["a"]) < out[0]:
                    out = (int(j["a"]), int((j.get("s") or {})[str(int(j["a"]))]))
            for u in ws.get("ux") or []:
                if isinstance(u, dict) and isinstance(u.get("a"), int) and int(u["a"]) < out[0]:
                    out = (int(u["a"]), int(u["ba"]))
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        return out

    def _balw_hist(self, st: dict, eoas: list, cnt: dict, cands: list = None):
        now = _now()
        lo = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        for w, gap in (cands if cands is not None else self._balw_hist_cands(st, eoas, now)):
            ws = st["w"].get(w) or {}
            cp = ws.get("cp")
            if not (isinstance(cp, list) and len(cp) == 3) or self._balw_hist_busy(ws):
                continue
            zb = self._balw_hist_end(ws)
            if zb is None:
                continue
            z, bz = zb
            a = max(int(lo) if isinstance(lo, int) and lo > 0 else 1, z - int(BALW_HIST_DAYS * 86400 / self._bsec()))
            if a >= z:
                ws["hist_at"] = int(now)
                continue
            ws.setdefault("hist_wait", int(now))
            retry = int(now - BALW_HIST_GAP + BALW_HIST_RETRY)
            try:
                xd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"])
                if xd is None:
                    if time.time() < cnt["t_end"]:
                        ws["hist_at"] = retry
                    return
                job = {"k": "hist", "a": a, "z": z, "s": {str(z): str(bz)}, "t0": int(now), "n": 0, "done": [], "xd": xd}
                try:
                    job["s"][str(a)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(a)]), 16))
                except _BalwNoArch as e:
                    if isinstance(e, _BalwNoState):
                        ws["hist_ns"] = int(ws.get("hist_ns") or 0) + 1
                        if ws["hist_ns"] < BALW_NOSTATE_N:
                            ws["hist_at"] = retry
                            return
                    ws.pop("hist_ns", None)
                    self._balw_charge(cnt, 1)
                    self._balw_disc_req(st, w, z, bz, self._block_time(hex(z)), int(gap * 10 ** 18), "지난 누락 · 아카이브 없음", old=True)
                    ws["hist_at"] = int(now)
                    ws.pop("hist_wait", None)
                    return
                ws.pop("hist_ns", None)
                r = self._balw_f(st, w, job, z)
                log.info("BSC 잔고 감시 %s: 잔고 대조 부족 %.6f BNB — 지난 %d일 창(블록 %d~%d) 설명 안 되는 증가 %d wei", w[:10], gap, BALW_HIST_DAYS, a, z, r)
                if r < BALW_DUST:
                    self._balw_charge(cnt, 1)
                    ts9 = self._block_time(hex(a))
                    self._balw_disc_req(st, w, a, int(job["s"][str(a)]), ts9, int(gap * 10 ** 18), "지난 누락 · 창 이전(또는 원장 쪽)", old=True)
                else:
                    ws.setdefault("jobs", []).append(job)
                ws["hist_at"] = int(now)
                ws.pop("hist_wait", None)
                return
            except _BalwStop:
                raise
            except Exception:
                ws["hist_at"] = retry
                raise

    def _balw_raw_deltas(self, w: str, a: int, z: int, deadline: float = None, cache: dict = None):
        if not os.path.exists(paths.DB_PATH):
            return {}
        rows = cache.get((int(a), int(z))) if cache is not None else None
        if rows is None:
            left = 10.0 if deadline is None else min(10.0, float(deadline) - time.time())
            if left <= 0:
                return None
            try:
                con = dbm.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=left)
                try:
                    if deadline is not None:
                        con.set_progress_handler(lambda: 1 if time.time() >= deadline else 0, 2000)
                    if cache is not None:
                        rows = [(h9, b9, sn9, str(sn9).lower()) for h9, b9, sn9 in con.execute(
                            "SELECT lower(txhash), block, snapshot FROM raw_txs WHERE chain='bsc' AND block > ? AND block <= ?", (int(a), int(z)))]
                        cache[(int(a), int(z))] = rows
                    else:
                        rows = con.execute("SELECT lower(txhash), block, snapshot FROM raw_txs WHERE chain='bsc' AND block > ? AND block <= ?"
                                           " AND instr(lower(snapshot), ?) > 0", (int(a), int(z), w[2:])).fetchall()
                finally:
                    con.close()
            except Exception as e:   # noqa: BLE001 [fallback]
                log.info("BSC 잔고 감시 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
                return None
        if cache is not None:
            rows = [(h9, b9, sn9) for h9, b9, sn9, low9 in rows if w[2:] in low9]
        out = {}
        for h, b, sn in rows:
            try:
                snap = json.loads(sn)
            except (TypeError, ValueError):
                continue
            if isinstance(snap, dict) and b is not None and _touches(snap, w):
                r = _native_delta(snap, w)
                if r is not None:
                    out[str(h)] = [int(b), str(r[0]), 1 if r[1] else 0]
        return out

    def _balw_win(self, st: dict, w: str, lo: list, hi: list, cnt: dict, raw: bool = False):
        a, ba, na = int(lo[0]), int(lo[1]), int(lo[2])
        z, bz, nz = int(hi[0]), int(hi[1]), int(hi[2])
        idx = {h: v for h, v in (st["d"].get(w) or {}).items() if a < v[0] <= z}
        sent = sum(int(v[2]) for v in idx.values())
        xd = {}
        if raw or nz - na > sent:
            rd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"], cache=cnt.setdefault("raw9", {}))
            if rd is None:
                return "noraw", 0, {}
            xd = {h: v for h, v in rd.items() if h not in idx}
            sent += sum(int(v[2]) for v in xd.values() if len(v) > 2)
        r = (bz - ba) - sum(int(v[1]) for v in idx.values()) - sum(int(v[1]) for v in xd.values())
        if nz - na == sent:
            return "ok", r, xd
        return ("miss" if nz - na > sent else "excess"), r, xd

    def _balw_job_add(self, st: dict, w: str, ws: dict, lo: list, hi: list, r: int, xd: dict, now: float, cnt: dict, why: str = "", back: bool = False):
        jobs = ws.setdefault("jobs", [])
        a, z = int(lo[0]), int(hi[0])
        job = {"k": "fwd", "a": a, "z": z, "s": {str(a): str(int(lo[1])), str(z): str(int(hi[1]))}, "t0": int(now), "n": 0, "done": []}
        if xd:
            job["xd"] = xd
        if back:
            job["back"] = True
            job["o"] = 1
        jobs.append(job)
        log.info("BSC 잔고 감시 %s: 블록 %d~%d 설명 안 되는 BNB 증가 %d wei — 이분 탐색%s", w[:10], a, z, r, (" · " + why) if why else "")
        try:
            while len(jobs) > BALW_JOBS_MAX:
                v9 = min(jobs, key=lambda j9: (int(j9.get("z") or 0), int(j9.get("a") or 0)))
                if not self._balw_close(st, w, v9, "작업 상한", cnt):
                    break
                jobs.remove(v9)
        except _BalwStop:
            pass

    def _balw_ux_add(self, w: str, ws: dict, lo: list, hi: list, now: float, why: str):
        ux = ws.setdefault("ux", [])
        a, z = int(lo[0]), int(hi[0])
        if ux and isinstance(ux[-1], dict) and ux[-1].get("z") == a:
            ux[-1].update(z=z, bz=str(int(hi[1])), nz=int(hi[2]))
        else:
            ux.append({"a": a, "ba": str(int(lo[1])), "na": int(lo[2]), "z": z, "bz": str(int(hi[1])), "nz": int(hi[2]), "t0": int(now), "why": why})
        log.info("BSC 잔고 감시 %s: 블록 %d~%d 미해결 구간(%s) — 색인·원장으로 다시 설명한 뒤 평가(체크포인트를 버리지 않음)", w[:10], a, z, why)

    def _balw_ux_step(self, st: dict, eoas: list, cnt: dict, now: float, nst: dict):
        lv = self.cursor.get("_live")
        holes = []
        for h9 in (lv.get("holes") or []) if isinstance(lv, dict) else []:
            try:
                holes.append((int(h9[0]), int(h9[1])))
            except (TypeError, ValueError, IndexError):
                pass
        for w in eoas:
            ws = st["w"].get(w)
            ux = ws.get("ux") if isinstance(ws, dict) else None
            if not isinstance(ux, list) or not ux:
                continue
            keep = []
            for k, sg in enumerate(ux):
                try:
                    lo, hi = [int(sg["a"]), int(sg["ba"]), int(sg["na"])], [int(sg["z"]), int(sg["bz"]), int(sg["nz"])]
                except (KeyError, TypeError, ValueError, AttributeError):
                    log.warning("BSC 잔고 감시 %s: 미해결 구간 항목 손상 — 버림: %s", w[:10], str(sg)[:120])
                    continue
                a, z = lo[0], hi[0]
                if time.time() > cnt["t_end"] or any(ha < z and hb > a for ha, hb in holes):
                    keep.append(sg)
                    continue
                v9, r, xd = self._balw_win(st, w, lo, hi, cnt, raw=True)
                if v9 in ("noraw", "miss"):
                    over = len(ux) - k > BALW_JOBS_MAX
                    aged = now - float(sg.get("t0") or now) > BALW_JOB_KEEP and (nst["w"].get(w) or {}).get("missing") == 0
                    if not (over or aged) or not self._balw_ux_close(st, w, hi, r, cnt, "미해결 구간 마감(" + ("상한" if over else "7일") + " · " + v9 + ")"):
                        keep.append(sg)
                    continue
                if v9 == "excess":
                    log.info("BSC 잔고 감시 %s: 미해결 구간 %d~%d 내 발신 과다(색인 불일치) — 구간 끝 기초 잔고 요청으로 마감", w[:10], a, z)
                    if not self._balw_ux_close(st, w, hi, r, cnt, "미해결 구간 · 색인 불일치"):
                        keep.append(sg)
                elif r >= BALW_DUST:
                    self._balw_job_add(st, w, ws, lo, hi, r, xd, now, cnt, "미해결 구간(" + str(sg.get("why") or "") + ")", back=True)
                elif r <= -BALW_DUST:
                    log.info("BSC 잔고 감시 %s: 미해결 구간 %d~%d 설명 안 되는 BNB 감소 %d wei(감수)", w[:10], a, z, -r)
            if keep:
                ws["ux"] = keep
            else:
                ws.pop("ux", None)

    def _balw_ux_close(self, st: dict, w: str, hi: list, r: int, cnt: dict, why: str) -> bool:
        z, bz = int(hi[0]), int(hi[1])
        ts9 = self.block_ts.get(hex(z))
        try:
            if ts9 is None:
                self._balw_charge(cnt, 1)
                ts9 = self._block_time(hex(z))
        except Exception as e:   # noqa: BLE001 [fallback]
            log.debug("BSC 잔고 감시 %s: 미해결 구간 끝 블록 시각 실패: %s", w[:10], logs.safe_err(e)[:80])
            return False
        log.warning("BSC 잔고 감시 %s: %s — 블록 %d 기초 잔고 요청(잔여 %d wei · core 가 잔고 − 원장으로 다시 잼)", w[:10], why, z, int(r))
        self._balw_disc_req(st, w, z, bz, ts9, max(1, int(r)), why)
        return True

    def _balw_rx(self, st: dict, eoas: list, cnt: dict, limit: int = None):
        p = paths.state(BALW_RX_NAME)
        req = statefile.read_control_json(p, None) if os.path.exists(p) and not cnt.get("rx_take") else None
        now = _now()
        if req is not None:
            since = None
            if isinstance(req, dict):
                v9 = req.get("since") if req.get("since") is not None else req.get("hours")
                try:
                    f9 = float(v9) if not isinstance(v9, bool) else float("nan")
                except (TypeError, ValueError, OverflowError):
                    f9 = float("nan")
                if req.get("since") is not None and 0 < f9 < now:
                    since = int(f9)
                elif req.get("since") is None and 0 < f9 <= BALW_RX_MAX_H:
                    since = int(now - f9 * 3600)
            if not since:
                bad9 = p + ".bad" if not os.path.exists(p + ".bad") else p + ".bad." + str(int(time.time()))
                try:
                    os.replace(p, bad9)
                except OSError:
                    pass
                log.warning("BSC 잔고 감시 — 지난 공백 다시 점검 요청 형식·범위 오류(%s 로 옮김): %s", os.path.basename(bad9), str(req)[:120])
                req = None
        if req is not None:
            want = {str(x).lower() for x in req["wallets"]} if isinstance(req.get("wallets"), list) else set()
            n9 = 0
            for w in eoas:
                ws = st["w"].get(w)
                if isinstance(ws, dict) and isinstance(ws.get("cp"), list) and (not want or w in want):
                    ws["rx"] = int(since)
                    n9 += 1
            log.warning("★BSC 잔고 감시 — 지난 공백 다시 점검 요청: %s 부터 · 지갑 %d개(원장 + 옛 블록 잔고로 다시 설명)★",
                        time.strftime("%Y-%m-%d %H:%M", time.gmtime(since)) + " UTC", n9)
            cnt["rx_take"] = p
        lo = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        for w in eoas:
            ws = st["w"].get(w)
            if not isinstance(ws, dict) or not ws.get("rx"):
                continue
            if limit is not None and int(cnt.get("rx_n") or 0) >= limit:
                return
            cp = ws.get("cp")
            if not (isinstance(cp, list) and len(cp) == 3):
                ws.pop("rx", None)
                continue
            if ws.get("jobs") or ws.get("ux") or isinstance(ws.get("rs"), dict):
                continue
            z, bz = int(cp[0]), int(cp[1])
            age = max(0.0, float(ws.get("cp_at") or now) - float(ws["rx"]))
            a = max(int(lo) if isinstance(lo, int) and lo > 0 else 1, z - int(age * 1.1 / self._bsec()) - 100)
            if a >= z:
                ws.pop("rx", None)
                continue
            xd = self._balw_raw_deltas(w, a, z, deadline=cnt["t_end"])
            if xd is None:
                return
            job = {"k": "fwd", "a": a, "z": z, "s": {str(z): str(bz)}, "t0": int(now), "n": 0, "done": [], "xd": xd, "back": True, "o": 1}
            cnt["rx_n"] = int(cnt.get("rx_n") or 0) + 1
            try:
                job["s"][str(a)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(a)]), 16))
            except _BalwNoArch as e:
                if isinstance(e, _BalwNoState):
                    ws["rx_ns"] = int(ws.get("rx_ns") or 0) + 1
                    if ws["rx_ns"] < BALW_NOSTATE_N:
                        continue
                log.warning("BSC 잔고 감시 %s: 지난 공백 다시 점검 못 함 — 블록 %d 잔고 모름(%s)", w[:10], a, str(e)[:80])
                ws.pop("rx", None)
                ws.pop("rx_ns", None)
                continue
            ws.pop("rx_ns", None)
            r = self._balw_f(st, w, job, z)
            ws.pop("rx", None)
            if r >= BALW_DUST:
                ws.setdefault("jobs", []).append(job)
                log.info("BSC 잔고 감시 %s: 지난 공백 다시 점검 — 블록 %d~%d 설명 안 되는 BNB 증가 %d wei — 이분 탐색", w[:10], a, z, r)
            else:
                log.info("BSC 잔고 감시 %s: 지난 공백 다시 점검 — 블록 %d~%d 원장으로 다 설명됨", w[:10], a, z)

    def _balw_rs(self, st: dict, eoas: list, cnt: dict):
        if isinstance(self.cursor.get("_live"), dict):
            return
        now = _now()
        for w in eoas:
            ws = st["w"].get(w)
            rs = ws.get("rs") if isinstance(ws, dict) else None
            if not isinstance(rs, dict):
                continue
            try:
                a, z, bz, nz = int(rs["a"]), int(rs["z"]), int(rs["bz"]), int(rs["nz"])
            except (KeyError, TypeError, ValueError):
                log.warning("BSC 잔고 감시 %s: 원장 복구 다시 점검 항목 손상 — 버림: %s", w[:10], str(rs)[:120])
                ws.pop("rs", None)
                continue
            if a >= z:
                ws.pop("rs", None)
                continue
            try:
                ba = int(self._balw_call(cnt, "eth_getBalance", [w, hex(a)]), 16)
                na = int(self._balw_call(cnt, "eth_getTransactionCount", [w, hex(a)]), 16)
            except _BalwNoArch as e:
                if isinstance(e, _BalwNoState):
                    ws["rs_ns"] = int(ws.get("rs_ns") or 0) + 1
                    if ws["rs_ns"] < BALW_NOSTATE_N:
                        continue
                ts9 = self.block_ts.get(hex(z))
                if ts9 is None:
                    self._balw_charge(cnt, 1)
                    ts9 = self._block_time(hex(z))
                why = f"원장 복구 다시 점검(블록 {a}~{z}) · 아카이브 없음"
                log.warning("BSC 잔고 감시 %s: %s — %s", w[:10], why, str(e)[:80])
                self._balw_disc_req(st, w, z, bz, ts9, 1, why, old=True)
                ws.pop("rs", None)
                ws.pop("rs_ns", None)
                continue
            ws.pop("rs_ns", None)
            ws.setdefault("ux", []).insert(0, {"a": a, "ba": str(ba), "na": na, "z": z, "bz": str(bz), "nz": nz, "t0": int(now), "why": "원장 복구"})
            ws.pop("rs", None)
            log.info("BSC 잔고 감시 %s: 원장 복구 다시 점검 — 블록 %d~%d 미해결 구간(복원 원장 + 다시 받은 거래로 설명)", w[:10], a, z)

    @staticmethod
    def _balw_old(job) -> bool:
        return isinstance(job, dict) and (job.get("k") == "hist" or bool(job.get("o")))

    @staticmethod
    def _balw_back(job) -> bool:
        return isinstance(job, dict) and (job.get("k") == "hist" or bool(job.get("back")))

    def _balw_jobs(self, st: dict, eoas: list, cnt: dict, head: int, now: float, back: bool):
        skip = cnt.setdefault("skip", {})
        while True:
            cand = [(w9, j9) for w9 in eoas for j9 in ((st["w"].get(w9) or {}).get("jobs") or [])
                    if isinstance(j9, dict) and self._balw_back(j9) == back and id(j9) not in skip]
            if not cand:
                break
            if back:
                old9 = [t9 for t9 in cand if self._balw_old(t9[1])]
                pool9 = old9 if old9 and len(old9) < len(cand) and cnt.get("bk_last") != "o" else cand
                w, job = min(pool9, key=lambda t9: (float(t9[1].get("lw") or t9[1].get("t0") or 0), int(t9[1].get("t0") or 0)))
                cnt["bk_last"] = "o" if self._balw_old(job) else "n"
            else:
                rot9, n9 = int(cnt.get("rot") or 0), max(1, len(eoas))
                w, job = max(cand, key=lambda t9: (int(t9[1].get("z") or 0), -((eoas.index(t9[0]) - rot9) % n9)))
            jobs = st["w"][w]["jobs"]
            n0 = cnt["n"]
            sc0 = int(cnt.get("scan") or 0)
            x = y = None
            try:
                if (now - float(job.get("t0") or now) > BALW_JOB_KEEP
                        or int(job.get("n") or 0) > BALW_JOB_CALLS + min(BALW_JOB_DONE_MAX, len(job.get("done") or [])) * BALW_CALL_CAP):
                    if self._balw_close(st, w, job, "탐색 상한(시간·호출)", cnt):
                        jobs.remove(job)
                        continue
                    skip[id(job)] = job
                    continue
                pts = sorted(int(k) for k in job["s"])
                fv = {b: self._balw_f(st, w, job, b) for b in pts}
                done = set(job.get("done") or [])
                sd9 = {tuple(v9) for v9 in job.get("sd") or [] if isinstance(v9, list) and len(v9) == 2}
                ivs = [(x, y) for x, y in zip(pts, pts[1:]) if fv[y] - fv[x] >= BALW_DUST and not (y - x == 1 and y in done)
                       and (x, y) not in sd9]
                if not ivs:
                    jobs.remove(job)
                    cnt["jobs"] += 1
                    continue
                x, y = min(ivs, key=lambda t: (t[1] - t[0], -t[1]))
                if isinstance(job.get("scan"), list):
                    self._balw_pubscan(st, w, job, head, cnt)
                    job.pop("ns", None)
                    continue
                if y - x == 1:
                    self._balw_resolve(st, w, job, y, fv[y] - fv[x], head, cnt)
                else:
                    mid = (x + y) // 2
                    job["s"][str(mid)] = str(int(self._balw_call(cnt, "eth_getBalance", [w, hex(mid)],
                                                                 recent=(head - mid) <= BALW_PUB_NEAR), 16))
                job.pop("ns", None)
            except _BalwNoArch as e:
                if (job.get("k") == "fwd" and x is not None and y is not None and not isinstance(job.get("scan"), list)
                        and y - x <= BALW_PUB_SCAN and getattr(self, "nonce_pub_rpc", None) is not None):
                    job["scan"] = [int(x), int(y), int(x) + 1]
                    continue
                if isinstance(e, _BalwNoState):
                    job["ns"] = int(job.get("ns") or 0) + 1
                    if job["ns"] < BALW_NOSTATE_N:
                        skip[id(job)] = job
                        continue
                if self._balw_close(st, w, job, "아카이브 상태 없음" if isinstance(e, _BalwNoState) else "아카이브 없음", cnt):
                    jobs.remove(job)
                    continue
                skip[id(job)] = job
                continue
            except _BalwStop:
                raise
            except Exception as e:   # noqa: BLE001 [isolate]
                skip[id(job)] = job
                cnt.setdefault("err", e)
                log.info("BSC 잔고 감시 %s: 작업 %d~%d 걸음 실패(이 작업만 다음 실행): %s", w[:10], int(job.get("a") or 0), int(job.get("z") or 0),
                         logs.safe_err(e)[:120])
                continue
            finally:
                job["n"] = int(job.get("n") or 0) + (cnt["n"] - n0)
                if cnt["n"] > n0 or int(cnt.get("scan") or 0) > sc0:
                    cnt["lwk"] = int(cnt.get("lwk") or 0) + 1
                    job["lw"] = round(float(now) + cnt["lwk"] * 1e-4, 4)
                if not jobs:
                    st["w"][w].pop("jobs", None)

    def _balw_safe(self, head: int, S: int) -> int:
        try:
            return self._balw_pass(head, S)
        except Exception as e:  # noqa: BLE001 [fallback]
            log.info("BSC 잔고 감시 실패(다음 기회): %s", logs.safe_err(e)[:120])
            return 0

    def _balw_pass(self, head: int, S: int) -> int:
        st = self._balw_load()
        if st.get("rqp") and self._balw_req_flush(st):
            self._balw_save()
        now = _now()
        every = BALW_EVERY if getattr(self, "nonce_pub_rpc", None) is not None else BALW_EVERY_ARCH
        if now - float(st.get("at") or 0) < every:
            return 0
        resting = float(st.get("bo_until") or 0) > now
        prev_at = float(st.get("at") or 0)
        st["at"] = int(now)
        cnt = {"n": 0, "emit": 0, "jobs": 0, "halt": None, "head": int(head),
               "t_end": time.time() + min(BALW_TIME_CAP, max(3.0, self._side_left() / 2.0))}
        st["lrr"] = cnt["rot"] = (int(st.get("lrr") or 0) + 1) % 1000003
        nst = self._nonce_load()
        eoas = [w for w in self.wallets if (nst["w"].get(w) or {}).get("kind") == "eoa"]
        stale = prev_at > 0 and now - prev_at > max(BALW_STALE, 2 * every)
        if stale:
            log.info("BSC 잔고 감시 — 지난 확인 뒤 %d분(봇 꺼짐·상류 장애·되돌림 — 그동안 방출이 색인에 없을 수 있음): 체크포인트 유지 · 공백 구간은 원장으로 다시 설명",
                     int((now - prev_at) / 60))
            for ws9 in st["w"].values():
                if isinstance(ws9, dict) and isinstance(ws9.get("cp"), list):
                    ws9["gap"] = int(prev_at)
        for w in list(st["w"]):
            if w not in self.wallets:
                st["w"].pop(w, None)
        for w in list(st["d"]):
            if w not in self.wallets:
                st["d"].pop(w, None)
        err = None
        dl_pools = []
        for pool9 in (getattr(self, "rpc", None), getattr(self, "nonce_pub_rpc", None), getattr(self, "arch_rpc", None)):
            if isinstance(pool9, Rpc) and not any(pool9 is p9 for p9, _o in dl_pools):
                dl_pools.append((pool9, pool9.__dict__.get("_dl")))
                pool9._dl = cnt["t_end"]
        for ws9 in st["w"].values():
            for j9 in (ws9.get("jobs") or []) if isinstance(ws9, dict) else []:
                if isinstance(j9, dict):
                    j9["back"] = True
        try:
            rr0 = int(st.get("read_rr") or 0) % len(eoas) if eoas else 0
            obs = self._balw_read(eoas[rr0:] + eoas[:rr0], S, cnt) if eoas else {}
            st["read_rr"] = (rr0 + max(1, len(obs))) % len(eoas) if eoas and len(obs) < len(eoas) else 0
            for w in eoas:
                o = obs.get(w)
                if o is None:
                    continue
                bal, non = o
                ws = st["w"].setdefault(w, {})
                cp = ws.get("cp")
                ok_cp = isinstance(cp, list) and len(cp) == 3 and all(isinstance(x, (int, str)) for x in cp)
                if not ok_cp or int(cp[0]) > S:
                    if ok_cp and isinstance(ws.get("rs"), dict):
                        continue
                    ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    ws.pop("gap", None)
                    continue
                B0, b0, n0 = int(cp[0]), int(cp[1]), int(cp[2])
                if B0 == S:
                    continue
                if ws.get("gap"):
                    self._balw_ux_add(w, ws, [B0, b0, n0], [int(S), bal, non], now, "공백")
                    ws.pop("gap", None)
                    ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    continue
                v9, r, xd = self._balw_win(st, w, [B0, b0, n0], [int(S), bal, non], cnt)
                if v9 != "ok":
                    m9 = (nst["w"].get(w) or {}).get("missing")
                    if v9 == "excess":
                        log.info("BSC 잔고 감시 %s: nonce 차 %d < 방출한 내 발신(색인 불일치 · 원장 복원 등) — 체크포인트 다시", w[:10], non - n0)
                        ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    elif now - float(ws.get("cp_at") or now) > BALW_NONCE_STUCK and m9 == 0:
                        self._balw_ux_add(w, ws, [B0, b0, n0], [int(S), bal, non], now, "nonce 정체")
                        ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
                    continue
                if r >= BALW_DUST:
                    self._balw_job_add(st, w, ws, [B0, b0, n0], [int(S), bal, non], r, xd, now, cnt)
                elif r <= -BALW_DUST:
                    log.info("BSC 잔고 감시 %s: 블록 %d~%d 설명 안 되는 BNB 감소 %d wei(감수 — 귀속 행 과대·위임 코드 등)", w[:10], B0, S, -r)
                ws["cp"], ws["cp_at"] = [int(S), str(bal), int(non)], int(now)
            hc9 = [] if resting else self._balw_hist_cands(st, eoas, now)
            if not resting:
                back9 = bool(hc9) or os.path.exists(paths.state(BALW_RX_NAME)) or any(
                    (st["w"].get(w9) or {}).get("ux") or (st["w"].get(w9) or {}).get("rx") or (st["w"].get(w9) or {}).get("rs")
                    or any(self._balw_back(j9) for j9 in (st["w"].get(w9) or {}).get("jobs") or []) for w9 in eoas)
                if back9:
                    cnt["cap"] = BALW_CALL_CAP - BALW_BACK_MIN
                    cnt["scan_cap"] = BALW_SCAN_RUN - max(BALW_SCAN_BATCH, BALW_SCAN_RUN // 4)
                    cnt["t_soft"] = time.time() + 0.75 * max(0.0, cnt["t_end"] - time.time())
                try:
                    self._balw_jobs(st, eoas, cnt, head, now, back=False)
                except _BalwStop as e:
                    if cnt["halt"] is not None:
                        raise
                    log.debug("BSC 잔고 감시 — 최신 작업 단계 끝(옛 몫 단계로): %s", e)
                finally:
                    cnt.pop("cap", None)
                    cnt.pop("scan_cap", None)
                    cnt.pop("t_soft", None)
                    cnt.pop("soft", None)
            self._balw_ux_step(st, eoas, cnt, now, nst)
            if resting:
                raise _BalwStop("아카이브 쉬는 중 — 공개 잔고 확인·창 평가만")
            for st9 in (lambda: self._balw_rs(st, eoas, cnt),
                        lambda: self._balw_rx(st, eoas, cnt, limit=1),
                        lambda: self._balw_hist(st, eoas, cnt, hc9),
                        lambda: self._balw_jobs(st, eoas, cnt, head, now, back=True),
                        lambda: self._balw_rx(st, eoas, cnt)):
                try:
                    st9()
                except _BalwStop as e:
                    if cnt["halt"] is not None:
                        raise
                    log.debug("BSC 잔고 감시 — 옛 몫 단계 멈춤(다음 단계로): %s", e)
                except Exception as e:   # noqa: BLE001 [isolate]
                    cnt.setdefault("err", e)
                    log.info("BSC 잔고 감시 — 옛 몫 단계 실패(다음 단계로): %s", logs.safe_err(e)[:120])
        except _BalwStop as e:
            log.debug("BSC 잔고 감시 — 이번 실행 멈춤: %s", e)
        except Exception as e:   # noqa: BLE001 [fallback]
            err = e
        finally:
            for pool9, old9 in dl_pools:
                if old9 is None:
                    pool9.__dict__.pop("_dl", None)
                else:
                    pool9._dl = old9
        if cnt["halt"] is not None:
            err = cnt["halt"]
        if err is None and cnt.get("err") is not None:
            err = cnt["err"]
        if err is not None:
            n9 = int(st.get("bo_n") or 0) + 1
            st["bo_n"] = n9
            if cnt["halt"] is not None:
                st["bo_until"] = int(_now() + min(BALW_BO_MAX, BALW_BO_BASE * (2 ** min(n9 - 1, 16))))
            log.info("BSC 잔고 감시 실패(다음 기회): %s", _nonce_why(err))
        elif not resting:
            st["bo_n"] = 0
            st.pop("bo_until", None)
        for w in list(st["d"]):
            lo = self._balw_lo(st["w"].get(w))
            st["d"][w] = {h: v for h, v in st["d"][w].items() if lo is not None and v[0] > lo}
        jobs_left = sum(len((st["w"].get(w) or {}).get("jobs") or []) for w in st["w"])
        ux_left = sum(len((st["w"].get(w) or {}).get("ux") or []) for w in st["w"])
        hw9 = [int(now) - int(v9["hist_wait"]) for v9 in st["w"].values() if isinstance(v9, dict) and isinstance(v9.get("hist_wait"), int)]
        self._balw_facts = {"wallets": len(eoas), "jobs": jobs_left, "calls": cnt["n"], "emit": cnt["emit"],
                            "noarch": getattr(self, "arch_rpc", None) is None, "at": int(now), "ux": ux_left,
                            "hist_wait": len(hw9), "hist_wait_s": max(hw9) if hw9 else 0,
                            "rs": sum(1 for v9 in st["w"].values() if isinstance(v9, dict) and isinstance(v9.get("rs"), dict))}
        st["last"] = self._balw_facts
        self._balw_save()
        if cnt.get("rx_take"):
            try:
                os.remove(cnt["rx_take"])
            except OSError:
                pass
        if cnt["n"] or cnt["emit"] or jobs_left or ux_left:
            log.info("BSC 잔고 감시: 지갑 %d · 옛 블록 호출 %d · 방출 %d · 끝난 작업 %d · 남은 작업 %d · 미해결 구간 %d", len(eoas), cnt["n"], cnt["emit"],
                     cnt["jobs"], jobs_left, ux_left)
        return cnt["emit"]
