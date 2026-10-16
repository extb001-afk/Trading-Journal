import bf_engine
import common
import json
import os
import time
from evm_base import HoldError
from evm_base import TraceDeferred
from evm_base import _int_or
from evm_base import leaf_overflow_path
from evm_base import leaf_overflow_read
import logging

log = logging.getLogger('tj-evm')


class RpcLaterMixin:

    def _trace_late_add(self, h: str) -> None:
        late9 = self.__dict__.get("_trace_late")
        if not isinstance(late9, dict):
            late9 = self._trace_late = dict.fromkeys(late9 or ())
        late9.pop(h, None)
        late9[h] = 1
        if len(late9) > 20000:
            memo9 = self.__dict__.get("_snap_memo") or {}
            for k9 in list(late9)[:len(late9) - 15000]:
                late9.pop(k9, None)
                memo9.pop(k9, None)

    TRACE_FIRST_SEC = 30

    LEAF_FIRST_SEC = 60

    LEAF_RETRY_N = 10

    LEAF_RETRY_SEC = 1800

    @staticmethod
    def _leaf_rng_key(nk: str, c) -> str:
        return f"@{nk}:{int(c)}"

    def _leaf_retry(self, w: str, y: int, ok: bool, c=None, nk: str = "_ns"):
        if nk == "_peek_ns":
            if not ok:
                self.__dict__.setdefault("_peek_fail_ws", set()).add(str(w).lower())
            return False
        lf = self.cursor.setdefault("_leaf_fail", {})
        k = f"{w[:12]}:{int(y)}"
        if ok:
            lf.pop(k, None)
            return False
        now = int(time.time())
        for k9 in [k9 for k9, v9 in lf.items() if now - int((v9 or [0, 0])[1]) > 86400]:
            lf.pop(k9, None)
        rk = self._leaf_rng_key(nk, c) if c is not None else k
        n9, t9 = (lf.get(rk) or [0, now])[:2]
        n9 += 1
        lf[rk] = [n9, t9]
        keep9 = n9 < self.LEAF_RETRY_N or now - int(t9) < self.LEAF_RETRY_SEC
        if nk == "_bkns" or (self.__dict__.get("_late_ctx") and not self.bk_mode):
            keep9 = False
        if keep9 and self.bk_mode and nk == "_ns":
            lh = self.cursor.get("_leaf_hold") if isinstance(self.cursor.get("_leaf_hold"), dict) else {}
            if now - int(lh.get("last") or 0) > self.LANES_LEAF_QUIET_SEC:
                lh = {"since": now}
            lh["last"] = now
            self.cursor["_leaf_hold"] = lh
            keep9 = now - int(lh.get("since") or now) < self.LANES_LEAF_HOLD_SEC
            lh["held"] = bool(keep9)
        if keep9:
            common.atomic_write_json(self.cursor_path, self.cursor)
            raise HoldError(f"잎 블록 {y} trace·상세 일시 실패 {n9}회 — 커서 유지(다음 사이클)")
        ll = self.cursor.setdefault("_leaf_later", {})
        ovf9 = k not in ll and len(ll) >= self.LEAF_LATER_MAX
        if ovf9:
            common.append_durable_jsonl(self._leaf_overflow_path(), {"k": k, "w": w, "blk": int(y), "at": now})
            no9 = int(self.cursor.get("_leaf_overflow") or 0) + 1
            self.cursor["_leaf_overflow"] = no9
            getattr(log, "warning" if no9 >= self.LEAF_OVERFLOW_WARN or no9 == 1 else "info")(
                "%s '나중에 다시' 잎 블록 큐 포화(%d) — 잎 %d 넘침 파일로(대기 %d · 커서 전진)", self.chain, len(ll), int(y), no9)
        if rk == k:
            lf.pop(k, None)
        self._note("_native_notes", {"kind": "leaf_giveup", "w": w[:10], "blk": int(y), "n": n9})
        if not ovf9:
            ll.setdefault(k, {"w": w, "blk": int(y), "at": now, "n": 0, "next": now + self.LEAF_LATER_SEC})
        return False

    def _leaf_prefetch(self, w: str, leaves: list, pool: list, sdl: float, deadline: float) -> tuple:
        ys = sorted({int(y) for (_x, y, _s1, _s2) in leaves})
        got = {}
        try:
            for i in range(0, len(ys), self.block_batch):
                if time.time() > sdl:
                    break
                part = ys[i:i + self.block_batch]
                with self._rpc_budget(sdl):
                    res = self._batch([("eth_getBlockByNumber", [hex(y), True]) for y in part])
                for y, blk in zip(part, res):
                    if isinstance(blk, dict) and isinstance(blk.get("transactions"), list):
                        got[y] = {str(t.get("hash") or "").lower(): y for t in blk["transactions"]
                                  if isinstance(t, dict) and w in ((t.get("from") or "").lower(), (t.get("to") or "").lower())}
        except Exception as e:
            log.info("%s 잎 블록 묶음 스캔 실패(잎마다 종전 경로): %s", self.chain, common.safe_err(e)[:100])
        if not got:
            return {}, {}
        pool_h = {s["tx"]["hash"].lower() for s in pool}
        q9 = bf_engine.quarantine_map(self.cursor)
        new = [h for y in ys for h in (got.get(y) or {}) if h and h not in pool_h and h not in q9]
        dets = {}
        if new:
            with self._trace_budget(deadline):
                dets = self._details(new, deadline=sdl, pref_only=True)
        return got, dets

    def _leaf_defer(self, w: str, y: int) -> None:
        ll = self.cursor.setdefault("_leaf_later", {})
        k = f"{w[:12]}:{int(y)}"
        if k in ll:
            return
        now = int(time.time())
        if len(ll) >= self.LEAF_LATER_MAX:
            common.append_durable_jsonl(self._leaf_overflow_path(), {"k": k, "w": w, "blk": int(y), "at": now})
            self.cursor["_leaf_overflow"] = int(self.cursor.get("_leaf_overflow") or 0) + 1
            log.info("%s '나중에 다시' 잎 블록 큐 포화(%d) — 잎 %d 넘침 파일로", self.chain, len(ll), int(y))
            return
        ll[k] = {"w": w, "blk": int(y), "at": now, "n": 0, "next": now + self.LEAF_LATER_SEC}

    LANES_LEAF_HOLD_SEC = 120

    LEAF_OVERFLOW_WARN = 100_000

    LEAF_OVERFLOW_BATCH = 50

    def _leaf_overflow_path(self) -> str:
        return leaf_overflow_path(self.chain)

    def _leaf_overflow_read(self) -> list:
        return leaf_overflow_read(self._leaf_overflow_path())

    def _leaf_overflow_write(self, rows: list) -> None:
        pth = self._leaf_overflow_path()
        if rows:
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pth), prefix=".tmp_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, pth)
            self.cursor["_leaf_overflow"] = len(rows)
        else:
            try:
                os.remove(pth)
            except OSError:
                pass
            self.cursor.pop("_leaf_overflow", None)

    def _leaf_overflow_refill(self, now: int) -> int:
        if not self.cursor.get("_leaf_overflow") and not os.path.exists(self._leaf_overflow_path()):
            return 0
        ll = self.cursor.setdefault("_leaf_later", {})
        rows = self._leaf_overflow_read()
        free = self.LEAF_LATER_MAX - len(ll)
        if rows and free < min(self.LEAF_OVERFLOW_BATCH, len(rows)):
            return 0
        rows = [r for r in rows if r["k"] not in ll]
        take, rest = rows[:max(0, free)], rows[max(0, free):]
        for r in take:
            ll[r["k"]] = {"w": r["w"], "blk": int(r["blk"]), "at": int(r.get("at") or now), "n": 0, "next": now}
        common.atomic_write_json(self.cursor_path, self.cursor)
        self._leaf_overflow_write(rest)
        common.atomic_write_json(self.cursor_path, self.cursor)
        if take:
            log.info("%s 넘침 파일 잎 %d개 → '나중에 다시' 큐(남은 넘침 %d)", self.chain, len(take), len(rest))
        return len(take)

    LEAF_LATER_SEC = 600

    LEAF_LATER_TTL = 30 * 86400

    LEAF_LATER_TTL_MIN_N = 5

    LEAF_LATER_STEP_SEC = 30

    LEAF_LATER_MAX = 500

    LEAF_LATER_PER_CYCLE = 3

    def _leaf_stg_get(self, e) -> dict:
        s9 = e.get("stg") if isinstance(e, dict) else None
        out = {"v": 1, "tb": [], "al": 0}
        if isinstance(s9, dict) and s9.get("v") == 1:
            if isinstance(s9.get("tb"), list):
                out["tb"] = [str(x)[:16] for x in s9["tb"] if isinstance(x, str)][:16]
            out["al"] = max(0, _int_or(s9.get("al"), 0))
            if s9.get("rc") is True or s9.get("rc") == 1:
                out["rc"] = 1
            if _int_or(s9.get("ri"), 0) > 0:
                out["ri"] = min(_int_or(s9.get("ri"), 0), 10 ** 6)
        return out

    def _leaf_stg_put(self, e: dict, st9: dict, lc9: dict, sent0: int) -> None:
        new = {"v": 1, "tb": sorted(set(st9["tb"]) | set(lc9.get("obs") or ()))[:16],
               "al": st9["al"] + max(0, int(self.__dict__.get("_alch_sent") or 0) - int(sent0))}
        if lc9.get("rc_next") or (st9.get("rc") and not lc9.get("rc_used")):
            new["rc"] = 1
        ri9 = int(st9.get("ri") or 0) + (1 if lc9.get("rc_used") else 0)
        if ri9:
            new["ri"] = ri9
        if "stg" in e or new["tb"] or new["al"]:
            e["stg"] = new

    def _leaf_later_expire_ok(self, k: str, e: dict, now: int) -> bool:
        why9 = None
        if self._leaf_stg_get(e)["al"] > 0:
            why9 = "expired_after_alchemy"
        else:
            ok9 = self.__dict__.get("_ll_alok")
            if ok9 is None:
                ok9 = self._ll_alok = bool(self._alch_url())
            if not ok9:
                why9 = "expired_no_alchemy"
            elif now - int(e.get("at") or now) <= self.LEAF_LATER_TTL * self.TRACE_LATER_ALCH_HOLD:
                return False
            else:
                why9 = "alchemy_never_tried"
        try:
            common.append_durable_jsonl(os.path.join(common.STATE_DIR, f"leaf_later_unresolved_{self.chain}.jsonl"),
                                        {"chain": self.chain, "k": k, "w": str(e.get("w") or "").lower(), "blk": _int_or(e.get("blk"), 0),
                                         "at": _int_or(e.get("at"), 0), "n": _int_or(e.get("n"), 0), "stg": self._leaf_stg_get(e),
                                         "err": str(e.get("err") or "")[:80], "why": why9, "ts": int(now)})
        except Exception as x9:
            log.warning("%s '나중에 다시' 잎 %s 보관 실패 — 큐 유지: %s", self.chain, k, common.safe_err(x9)[:80])
            return False
        self._note("_native_notes", {"kind": "leaf_later_archived", "w": str(e.get("w") or "")[:10], "blk": _int_or(e.get("blk"), 0)})
        return True

    def _leaf_later_step(self, head: int) -> int:
        if self.trace_rpcs:
            self._leaf_overflow_refill(int(time.time()))
        ll = self.cursor.get("_leaf_later")
        if not isinstance(ll, dict) or not ll or not self.trace_rpcs:
            return 0
        now = int(time.time())
        n_emit, done = 0, 0
        self._ll_alok = None
        gone9 = [k9 for k9, e9 in ll.items() if not isinstance(e9, dict)
                 or (now - int(e9.get("at") or now) > self.LEAF_LATER_TTL and int(e9.get("n") or 0) >= self.LEAF_LATER_TTL_MIN_N
                     and self._leaf_later_expire_ok(k9, e9, now))]
        for k9 in gone9:
            e9 = ll.pop(k9, None)
            e9 = e9 if isinstance(e9, dict) else {}
            self._note("_native_notes", {"kind": "leaf_later_giveup", "w": str(e9.get("w") or "")[:10], "blk": int(e9.get("blk") or 0), "n": int(e9.get("n") or 0)})
            log.warning("%s '나중에 다시' 잎 블록 %s — %d일 넘게 못 풂 · 뺌(그 입금 internal 미확인 · 대사 흡수)", self.chain,
                        e9.get("blk") or k9, self.LEAF_LATER_TTL // 86400)
        t9 = time.time()
        dl9 = t9 + self.LEAF_LATER_STEP_SEC
        per9 = 1 if self._trace_sick() else self.LEAF_LATER_PER_CYCLE
        for k in sorted(ll, key=lambda x: max(int(ll[x].get("next") or 0), min(_int_or(ll[x].get("dfr"), 0), now))):
            e = ll.get(k) or {}
            if done >= per9 or int(e.get("next") or 0) > now:
                break
            if done and time.time() >= dl9:
                break
            first9 = not done
            done += 1
            w, y = str(e.get("w") or "").lower(), int(e.get("blk") or 0)
            st9 = self._leaf_stg_get(e)
            ns9 = {self._trace_nid(u) for u in self.trace_rpcs}
            lc9 = {"tb": st9["tb"], "alch": bool(ns9) and ns9 <= set(st9["tb"]), "obs": set(), "rc": bool(st9.get("rc")), "ri": int(st9.get("ri") or 0)}
            sent9 = int(self.__dict__.get("_alch_sent") or 0)
            try:
                self._alch_ctx_n = int(e.get("n") or 0)
                self._leaf_ctx_stg = lc9
                with self._trace_budget(max(dl9, time.time() + self.LEAF_FIRST_SEC) if first9 else dl9):
                    frames, unres9 = self._trace_block(y)
                cand = [h for h, rows in frames.items() if any((r.get("to") or "").lower() == w and r.get("success") is not False for r in rows)]
                q9 = bf_engine.quarantine_map(self.cursor)
                cand = [h for h in cand if h not in q9]
                dets = self._details(cand, trace=False, deadline=time.time() + 30) if cand else {}
                bad = [h for h in cand if not isinstance(dets.get(h), dict)]
                if bad:
                    raise RuntimeError(f"상세 실패 {bad[0][:12]}: {common.safe_err(dets.get(bad[0]))[:80]}")
            except Exception as ex:
                self._leaf_stg_put(e, st9, lc9, sent9)
                if isinstance(ex, TraceDeferred) or "예산 소진" in str(ex):
                    e["dfr"] = now
                    break
                if self._trace_gone(ex):
                    ll.pop(k, None)
                    self._note("_native_notes", {"kind": "leaf_later_unsupported", "w": w[:10], "blk": y})
                else:
                    e["n"] = int(e.get("n") or 0) + 1
                    e["next"] = now + min(7200, self.LEAF_LATER_SEC * (2 ** min(e["n"], 4)))
                    e["err"] = common.safe_err(ex)[:80]
                continue
            for h in cand:
                s9 = dets[h]
                s9["internal"] = frames[h]
                s9["internal_note"] = "trace"
                if any(self._touches(s9, w9) for w9 in self.wallets):
                    self._emit(h, s9, head)
                    n_emit += 1
            if unres9:
                self._leaf_stg_put(e, st9, lc9, sent9)
                e["n"] = int(e.get("n") or 0) + 1
                e["next"] = now + min(7200, self.LEAF_LATER_SEC * (2 ** min(e["n"], 4)))
                e["err"] = f"블록 trace 항목 {len(unres9)}개 미해결"
                continue
            ll.pop(k, None)
            self._note("_native_notes", {"kind": "leaf_later_done", "w": w[:10], "blk": y, "found": len(cand)})
        if done or gone9:
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
        if n_emit:
            log.info("%s 나중에 다시 잎 블록 — internal 입금 tx %d건 방출", self.chain, n_emit)
        return n_emit

    TRACE_LATER_SEC = 120

    TRACE_LATER_MAX_SEC = 21600

    TRACE_LATER_TTL = 30 * 86400

    TRACE_LATER_MAX = 2000

    TRACE_LATER_PER_CYCLE = 3

    TRACE_LATER_TTL_MIN_N = 5

    TRACE_LATER_STEP_SEC = 30

    def _trace_later_mark(self, h: str, snap: dict) -> None:
        late9 = self.__dict__.get("_trace_late") or {}
        tl = self.cursor.get("_trace_later")
        if snap.get("internal_note") == "trace":
            late9.pop(h, None) if isinstance(late9, dict) else late9.discard(h)
            if isinstance(tl, dict):
                tl.pop(h, None)
            return
        if h not in late9:
            return
        late9.pop(h, None) if isinstance(late9, dict) else late9.discard(h)
        hq = self.cursor.get("_hq")
        if isinstance(hq, dict) and h in hq:
            return
        if not isinstance(tl, dict):
            tl = self.cursor["_trace_later"] = {}
        if not isinstance(tl.get(h), dict):
            if len(tl) >= int(self.TRACE_LATER_MAX):
                self._trace_later_spill(h, snap, True)
                return
            now = int(time.time())
            try:
                blk = int((snap.get("tx") or {}).get("block_number") or 0)
            except (TypeError, ValueError):
                blk = 0
            tl[h] = {"at": now, "n": 0, "next": now + self.TRACE_LATER_SEC, "blk": blk}
        tl[h]["sent"] = True

    TRACE_LATER_UNSENT_SEC = 3600

    TRACE_OVERFLOW_BATCH = 50

    def _trace_overflow_path(self) -> str:
        return os.path.join(common.STATE_DIR, f"trace_later_overflow_{self.chain}.jsonl")

    def _trace_overflow_read(self) -> list:
        out = {}
        try:
            with open(self._trace_overflow_path(), encoding="utf-8") as f:
                for ln in f:
                    try:
                        e = json.loads(ln)
                    except ValueError:
                        continue
                    h9 = str((e or {}).get("h") or "").lower() if isinstance(e, dict) else ""
                    if not h9.startswith("0x"):
                        continue
                    at9, n9, b9 = _int_or(e.get("at"), int(time.time())), _int_or(e.get("n"), 0), _int_or(e.get("blk"), 0)
                    o9 = out.get(h9)
                    if o9 is None:
                        out[h9] = {"h": h9, "at": at9, "n": n9, "blk": b9, "sent": bool(e.get("sent"))}
                    else:
                        o9["sent"] = o9["sent"] or bool(e.get("sent"))
                        o9["at"] = min(o9["at"], at9 or o9["at"])
                        o9["n"] = max(o9["n"], n9)
        except (OSError, TypeError, ValueError):
            pass
        return list(out.values())

    def _trace_later_spill(self, h: str, snap: dict, sent: bool) -> None:
        try:
            blk = int((snap.get("tx") or {}).get("block_number") or 0)
        except (TypeError, ValueError, AttributeError):
            blk = 0
        common.append_durable_jsonl(self._trace_overflow_path(), {"h": h, "at": int(time.time()), "n": 0, "blk": blk, "sent": bool(sent)})
        seen9 = self.__dict__.setdefault("_tovf_seen", set())
        n9 = int(self.cursor.get("_trace_later_overflow") or 0) + (0 if h in seen9 else 1)
        seen9.add(h)
        self.cursor["_trace_later_overflow"] = n9
        (log.warning if n9 == 1 or n9 % 1000 == 0 else log.info)("%s 늦은 채움 큐 포화(%d) — tx %s 넘침 파일로(대기 %d · 버리지 않음)", self.chain,
                                                                 len(self.cursor.get("_trace_later") or {}), h[:12], n9)

    def _trace_later_trim(self) -> int:
        tl = self.cursor.get("_trace_later")
        if not isinstance(tl, dict) or len(tl) <= int(self.TRACE_LATER_MAX):
            return 0
        order9 = sorted(tl, key=lambda x: (int((tl.get(x) or {}).get("at") or 0) if isinstance(tl.get(x), dict) else 0, x))
        out9 = order9[int(self.TRACE_LATER_MAX):]
        seen9 = self.__dict__.setdefault("_tovf_seen", set())
        n9 = int(self.cursor.get("_trace_later_overflow") or 0)
        for h9 in out9:
            e9 = tl.get(h9) if isinstance(tl.get(h9), dict) else {}
            common.append_durable_jsonl(self._trace_overflow_path(), {"h": h9, "at": int(e9.get("at") or time.time()), "n": int(e9.get("n") or 0),
                                                                     "blk": int(e9.get("blk") or 0), "sent": bool(e9.get("sent", True))})
            if h9 not in seen9:
                seen9.add(h9)
                n9 += 1
        for h9 in out9:
            tl.pop(h9, None)
        self.cursor["_trace_later_overflow"] = n9
        common.atomic_write_json(self.cursor_path, {k: v for k, v in self.cursor.items() if k != "_peek_ns"})
        log.info("%s 늦은 채움 큐 %d건 넘침 파일로(커서 상한 %d · 대기 %d)", self.chain, len(out9), int(self.TRACE_LATER_MAX), n9)
        return len(out9)

    def _trace_overflow_refill(self) -> int:
        pth = self._trace_overflow_path()
        if not self.cursor.get("_trace_later_overflow") and not os.path.exists(pth):
            return 0
        tl = self.cursor.get("_trace_later") if isinstance(self.cursor.get("_trace_later"), dict) else {}
        rows = self._trace_overflow_read()
        free = int(self.TRACE_LATER_MAX) - len(tl)
        if rows and free < min(self.TRACE_OVERFLOW_BATCH, len(rows)):
            return 0
        take, rest = rows[:max(0, free)], rows[max(0, free):]
        now = int(time.time())
        hq9 = self.cursor.get("_hq") if isinstance(self.cursor.get("_hq"), dict) else {}
        for r in take:
            if r["h"] in hq9:
                continue
            e9 = tl.get(r["h"])
            if isinstance(e9, dict):
                e9["sent"] = bool(e9.get("sent", True)) or r["sent"]
                continue
            tl[r["h"]] = {"at": int(r["at"] or now), "n": int(r["n"]), "next": now, "blk": int(r["blk"]), "sent": r["sent"]}
        if tl:
            self.cursor["_trace_later"] = tl
        common.atomic_write_json(self.cursor_path, self.cursor)
        if rest:
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pth), prefix=".tmp_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rest))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, pth)
            self.cursor["_trace_later_overflow"] = len(rest)
            self._tovf_seen = {r["h"] for r in rest}
        else:
            self._tovf_seen = set()
            try:
                os.remove(pth)
            except OSError:
                pass
            self.cursor.pop("_trace_later_overflow", None)
        common.atomic_write_json(self.cursor_path, self.cursor)
        if take:
            log.info("%s 넘침 파일 늦은 채움 tx %d건 → 큐(남은 넘침 %d)", self.chain, len(take), len(rest))
        return len(take)

    def _trace_later_pre(self, hashes, snaps: dict = None) -> int:
        late9 = self.__dict__.get("_trace_late") or {}
        if not late9:
            return 0
        hq9 = self.cursor.get("_hq") if isinstance(self.cursor.get("_hq"), dict) else {}
        tl = self.cursor.get("_trace_later") if isinstance(self.cursor.get("_trace_later"), dict) else None
        now = int(time.time())
        n9 = 0
        for h in dict.fromkeys(hashes):
            s9 = (snaps or {}).get(h)
            if h not in late9 or h in hq9 or (isinstance(s9, dict) and s9.get("internal_note") == "trace"):
                continue
            if tl is None:
                tl = self.cursor["_trace_later"] = {}
            if isinstance(tl.get(h), dict):
                if h in self.emitted:
                    tl[h]["sent"] = True
                continue
            if len(tl) >= int(self.TRACE_LATER_MAX):
                self._trace_later_spill(h, s9 if isinstance(s9, dict) else {}, h in self.emitted)
                continue
            try:
                blk = int(((s9 or {}).get("tx") or {}).get("block_number") or 0)
            except (TypeError, ValueError, AttributeError):
                blk = 0
            tl[h] = {"at": now, "n": 0, "next": now + self.TRACE_LATER_SEC, "blk": blk, "sent": h in self.emitted}
            n9 += 1
        if n9:
            common.atomic_write_json(self.cursor_path, {k: v for k, v in self.cursor.items() if k != "_peek_ns"})
        return n9

    def _trace_late_settle(self, hashes) -> None:
        late9 = self.__dict__.get("_trace_late")
        if not late9:
            return
        hs9 = [h for h in dict.fromkeys(hashes) if h in late9]
        if not hs9:
            return
        self._trace_later_pre(hs9)
        for h in hs9:
            late9.pop(h, None) if isinstance(late9, dict) else late9.discard(h)

    TRACE_LATER_ALCH_HOLD = 2

    def _trace_later_expire_ok(self, h: str, e: dict, now: int) -> bool:
        why9 = None
        if self._trace_stg_get(e)["al"] > 0:
            why9 = "expired_after_alchemy"
        else:
            ok9 = self.__dict__.get("_tl_alok")
            if ok9 is None:
                ok9 = self._tl_alok = bool(self._alch_url())
            if not ok9:
                why9 = "expired_no_alchemy"
            elif now - int(e.get("at") or now) <= self.TRACE_LATER_TTL * self.TRACE_LATER_ALCH_HOLD:
                return False
            else:
                why9 = "alchemy_never_tried"
        try:
            common.append_durable_jsonl(os.path.join(common.STATE_DIR, f"trace_later_unresolved_{self.chain}.jsonl"),
                                        {"chain": self.chain, "h": h, "blk": _int_or(e.get("blk"), 0), "at": _int_or(e.get("at"), 0), "n": _int_or(e.get("n"), 0),
                                         "stg": self._trace_stg_get(e), "err": str(e.get("err") or "")[:80], "why": why9, "ts": int(now)})
        except Exception as x9:
            log.warning("%s 늦은 채움 trace %s 보관 실패 — 큐 유지: %s", self.chain, h[:12], common.safe_err(x9)[:80])
            return False
        self._note("_native_notes", {"kind": "trace_later_archived", "tx": h[:14]})
        return True

    def _trace_later_step(self, head: int, per: int = None) -> int:
        self._trace_later_trim()
        self._tl_alok = None
        if self.trace_rpcs:
            self._trace_overflow_refill()
        tl = self.cursor.get("_trace_later")
        if not isinstance(tl, dict) or not tl or not self.trace_rpcs:
            return 0
        now = int(time.time())
        n_emit, done, touched = 0, 0, False

        def nxt(x):
            e9 = tl.get(x)
            return int(e9.get("next") or 0) if isinstance(e9, dict) else 0

        def pick(x):
            e9 = tl.get(x)
            return max(nxt(x), min(_int_or(e9.get("dfr"), 0), now)) if isinstance(e9, dict) else 0
        t9 = time.time()
        for h in sorted(tl, key=nxt):
            e = tl.get(h)
            if isinstance(e, dict) and now - int(e.get("at") or now) > self.TRACE_LATER_TTL and int(e.get("n") or 0) >= self.TRACE_LATER_TTL_MIN_N \
                    and self._trace_later_expire_ok(h, e, now):
                tl.pop(h, None)
                touched = True
                self._note("_native_notes", {"kind": "trace_later_giveup", "tx": h[:14], "n": int(e.get("n") or 0)})
                log.warning("%s 늦은 채움 trace %s — %d일 넘게 못 풂 · 뺌(internal 미확인 · 대사 흡수): %s", self.chain, h[:12],
                            self.TRACE_LATER_TTL // 86400, str(e.get("err") or "")[:80])
        for h in sorted(tl, key=pick):
            e = tl.get(h)
            if not isinstance(e, dict):
                tl.pop(h, None)
                touched = True
                continue
            if now - int(e.get("at") or now) > self.TRACE_LATER_TTL and int(e.get("n") or 0) >= self.TRACE_LATER_TTL_MIN_N \
                    and self._trace_later_expire_ok(h, e, now):
                tl.pop(h, None)
                touched = True
                self._note("_native_notes", {"kind": "trace_later_giveup", "tx": h[:14], "n": int(e.get("n") or 0)})
                log.warning("%s 늦은 채움 trace %s — %d일 넘게 못 풂 · 뺌(internal 미확인 · 대사 흡수): %s", self.chain, h[:12],
                            self.TRACE_LATER_TTL // 86400, str(e.get("err") or "")[:80])
                continue
            if done >= (1 if self._trace_sick() else int(per or self.TRACE_LATER_PER_CYCLE)) or int(e.get("next") or 0) > now:
                break
            if done and time.time() - t9 >= self.TRACE_LATER_STEP_SEC:
                break
            if not e.get("sent", True) and h not in self.emitted and now - int(e.get("at") or now) < self.TRACE_LATER_UNSENT_SEC:
                continue
            first9 = not done
            done += 1
            touched = True
            st9 = self._trace_stg_get(e)
            ns9 = {self._trace_nid(u) for u in self.trace_rpcs}
            ctd9, pad9 = bool(ns9) and ns9 <= set(st9["ct"]), bool(ns9) and ns9 <= set(st9["pa"])
            tmp9 = {"_trace_parity_first": bool(int(e.get("n") or 0) % 2) if ctd9 == pad9 else ctd9}
            tmp9.update(_alch_n=int(e.get("n") or 0), _alch_blk=int(e.get("blk") or 0))
            tmp9["_trace_stg"] = {"ct": st9["ct"], "pa": st9["pa"], "alch": ctd9 and pad9}
            sent9 = int(self.__dict__.get("_alch_sent") or 0)
            try:
                with self._trace_budget(max(t9 + self.TRACE_LATER_STEP_SEC, time.time() + self.TRACE_FIRST_SEC) if first9 else t9 + self.TRACE_LATER_STEP_SEC):
                    self._trace_internal(h, tmp9)
                rows9 = list(tmp9.get("internal") or [])
                s9 = None
                if rows9:
                    s9 = self._details([h], trace=False, deadline=time.time() + 30).get(h)
                    if not isinstance(s9, dict):
                        raise s9 if isinstance(s9, Exception) else RuntimeError("상세 없음")
            except Exception as ex:
                self._trace_stg_put(e, st9, sent9)
                if isinstance(ex, TraceDeferred) or "예산 소진" in str(ex):
                    e["dfr"] = now
                    break
                if self._trace_gone(ex):
                    tl.pop(h, None)
                    self._note("_native_notes", {"kind": "trace_later_unsupported", "tx": h[:14]})
                else:
                    e["n"] = int(e.get("n") or 0) + 1
                    e["next"] = now + min(self.TRACE_LATER_MAX_SEC, self.TRACE_LATER_SEC * (2 ** min(e["n"], 8)))
                    e["err"] = common.safe_err(ex)[:80]
                continue
            if s9 is not None:
                s9["internal"] = rows9
                s9["internal_note"] = "trace"
                if tmp9.get("internal_src"):
                    s9["internal_src"] = tmp9["internal_src"]
                if any(self._touches(s9, w) for w in self.wallets):
                    self._emit(h, s9, head)
                    n_emit += 1
            tl.pop(h, None)
            self._note("_native_notes", {"kind": "trace_later_done", "tx": h[:14], "rows": len(rows9)})
        if not tl:
            self.cursor.pop("_trace_later", None)
        if touched:
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
        if n_emit:
            log.info("%s 늦은 채움 trace — internal %d건 다시 방출(남은 %d)", self.chain, n_emit, len(tl))
        return n_emit

    HQ_DETAIL_CHUNK = 5

    HQ_FAIL_MAX = 5

    def _hq_to_later(self, h: str, snap=None) -> None:
        tl = self.cursor.get("_trace_later")
        if not isinstance(tl, dict):
            tl = self.cursor["_trace_later"] = {}
        if isinstance(tl.get(h), dict):
            tl[h]["sent"] = True
            return
        if len(tl) >= int(self.TRACE_LATER_MAX):
            self._trace_later_spill(h, snap if isinstance(snap, dict) else {}, True)
            return
        now = int(time.time())
        try:
            blk = int(((snap or {}).get("tx") or {}).get("block_number") or 0) if isinstance(snap, dict) else 0
        except (TypeError, ValueError, AttributeError):
            blk = 0
        tl[h] = {"at": now, "n": 0, "next": now + self.TRACE_LATER_SEC, "blk": blk, "sent": True}

    def _hq_step(self, head: int, deadline: float) -> int:
        hq = self.cursor.get("_hq")
        if not isinstance(hq, dict) or not hq:
            return 0
        n = 0
        keys = sorted(hq)
        pos9 = self.__dict__.get("_hq_pos")
        if isinstance(pos9, str):
            keys = [k for k in keys if k > pos9] + [k for k in keys if k <= pos9]
        tried9 = 0
        for i in range(0, len(keys), self.HQ_DETAIL_CHUNK):
            if tried9 and (time.time() >= deadline or self._trace_sick()):
                break
            part = [h for h in keys[i:i + self.HQ_DETAIL_CHUNK] if h in hq]
            if not part:
                continue
            dets = self._details(part, deadline=(deadline + 60) if tried9 else (max(deadline, time.time() + self.TRACE_FIRST_SEC) + 60), trace=False)
            for h in part:
                if tried9 and (time.time() >= deadline or self._trace_sick()):
                    break
                first9 = not tried9
                tried9 += 1
                self._hq_pos = h
                s9 = dets.get(h)
                err9 = None
                if isinstance(s9, dict):
                    st9 = hst9 = None
                    try:
                        ht9 = self.__dict__.setdefault("_hq_try", {})
                        hs9 = self.__dict__.setdefault("_hq_stg", {})
                        if len(hs9) > 20000:
                            hs9.clear()
                        hst9 = hs9.setdefault(h, {})
                        st9 = self._trace_stg_get(hst9)
                        ns9 = {self._trace_nid(u) for u in self.trace_rpcs}
                        ctd9, pad9 = bool(ns9) and ns9 <= set(st9["ct"]), bool(ns9) and ns9 <= set(st9["pa"])
                        s9["_trace_parity_first"] = bool(int(ht9.get(h) or 0) % 2) if ctd9 == pad9 else ctd9
                        s9["_trace_stg"] = {"ct": st9["ct"], "pa": st9["pa"], "alch": ctd9 and pad9}
                        sent9 = int(self.__dict__.get("_alch_sent") or 0)
                        with self._trace_budget(max(deadline, time.time() + self.TRACE_FIRST_SEC) if first9 else deadline):
                            self._trace_internal(h, s9)
                        s9.pop("_trace_parity_first", None)
                        ht9.pop(h, None)
                        hs9.pop(h, None)
                    except Exception as e:
                        err9 = e
                        s9.pop("_trace_parity_first", None)
                        s9.pop("_trace_stg", None)
                        if st9 is not None and isinstance(hst9, dict):
                            self._trace_stg_put(hst9, st9, sent9)
                        if not isinstance(e, TraceDeferred):
                            ht9 = self.__dict__.setdefault("_hq_try", {})
                            ht9[h] = int(ht9.get(h) or 0) + 1
                            if len(ht9) > 20000:
                                ht9.clear()
                        if self._trace_gone(e):
                            hq.pop(h, None)
                            self._note("_native_notes", {"kind": "hq_untraced", "tx": h[:14]})
                            continue
                    if err9 is None:
                        if s9.get("internal") and any(self._touches(s9, w) for w in self.wallets):
                            self._emit(h, s9, head)
                            n += 1
                        else:
                            hq.pop(h, None)
                        continue
                else:
                    err9 = s9
                mixed9 = isinstance(s9, dict) and bool(self.__dict__.get("_trace_mixed"))
                if "예산 소진" in str(err9) or mixed9 or not bf_engine.detail_err_deterministic(err9):
                    continue
                hq[h] = int(hq.get(h) or 0) + 1
                if hq[h] >= self.HQ_FAIL_MAX:
                    hq.pop(h, None)
                    self._hq_to_later(h, s9)
                    self._note("_native_notes", {"kind": "hq_to_later", "tx": h[:14], "err": common.safe_err(err9)[:80]})
                    log.warning("%s 인계 큐 %s 결정적 실패 %d회 — 늦은 채움으로 넘김(백오프 재시도 · internal 미확인 동안 대사 흡수): %s", self.chain, h[:12],
                                self.HQ_FAIL_MAX, common.safe_err(err9)[:100])
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
        if n:
            log.info("%s 인계 큐 internal 채움 %d건 방출(남은 %d)", self.chain, n, len(hq))
        return n
