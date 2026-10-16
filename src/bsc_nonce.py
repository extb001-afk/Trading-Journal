from __future__ import annotations
import bf_engine
import common
import json
import os
import time
from bsc_base import NONCE_ARCH_GAP
from bsc_base import NONCE_BACKLOG_EVERY
from bsc_base import NONCE_BO_BASE
from bsc_base import NONCE_BO_MAX
from bsc_base import NONCE_CALL_CAP
from bsc_base import NONCE_EVERY
from bsc_base import NONCE_HEAD_EVERY
from bsc_base import NONCE_HINT_FAR
from bsc_base import NONCE_HINT_KEEP
from bsc_base import NONCE_HINT_NEAR
from bsc_base import NONCE_MAX_FIND
from bsc_base import NONCE_NARROW
from bsc_base import NONCE_OLD_BURST
from bsc_base import NONCE_PUB_CAP
from bsc_base import NONCE_RECENT_SEC
from bsc_base import NONCE_TOP_BATCH
from bsc_base import Rpc
from bsc_base import XIN_EVERY
from bsc_base import XIN_MAX_NEW
from bsc_base import XIN_NF_MAX
from bsc_base import _NONCE_NEXT_KINDS
from bsc_base import _NONCE_STOP_KINDS
from bsc_base import _NView
from bsc_base import _NonceBudget
from bsc_base import _PubDown
from bsc_base import _XIN_NET
from bsc_base import _XIN_TXID
from bsc_base import _nonce_why
from bsc_base import _now
from bsc_base import _xin_not_found
import logging

log = logging.getLogger('tj-bsc')


class NonceMixin:

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
            con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
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

    def _nonce_hint(self, w: str, blk) -> bool:
        w = str(w or "").lower()
        if w not in self.wallets:
            return False
        try:
            b = int(blk)
        except (TypeError, ValueError):
            return False
        st = self._nonce_load()
        hl = st["w"].setdefault(w, {}).setdefault("hint", [])
        if any(isinstance(h9, list) and h9 and h9[0] == b for h9 in hl):
            return False
        hl.append([b, int(_now())])
        common.atomic_write_json(self._nonce_path(), st)
        return True

    def _nonce_due(self, st: dict, now: float, lo_blk: int, busy: set, known_set) -> bool:
        for w in self.wallets:
            if w in busy or (isinstance(known_set, list) and w not in known_set):
                continue
            ws = st["w"].get(w) or {}
            kind = ws.get("kind")
            if kind is None:
                return True
            if kind != "eoa":
                continue
            lo = ws.get("lo")
            if not (isinstance(lo, list) and len(lo) == 2 and lo[0] == lo_blk):
                return True
            ta = ws.get("top_at")
            if not isinstance(ws.get("top"), int) or not isinstance(ta, (int, float)) or now - float(ta) >= NONCE_HEAD_EVERY:
                return True
            try:
                if int(ws.get("missing") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                pass
            if ws.get("hint"):
                return True
        return False

    def _nonce_tops(self, batch_fn, ws_list: list, safe: int, put, one, can_one=None) -> None:
        if not ws_list:
            return
        bh = hex(int(safe))

        def put_one(w9):
            if can_one is not None and not can_one():
                return False
            r9 = one(w9, bh)
            if r9 is not None:
                put(w9, int(r9, 16))
            return True
        rest = list(ws_list)
        if batch_fn is not None and len(rest) > 1:
            rest = []
            down = False
            for i in range(0, len(ws_list), NONCE_TOP_BATCH):
                chunk = ws_list[i:i + NONCE_TOP_BATCH]
                res = []
                if not down:
                    try:
                        res = batch_fn([("eth_getTransactionCount", [w9, bh]) for w9 in chunk])
                    except _NonceBudget:
                        raise
                    except _PubDown:
                        down = True
                    except Exception as e:
                        if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                            raise
                failed = []
                for j, w9 in enumerate(chunk):
                    r9 = res[j] if isinstance(res, list) and j < len(res) else None
                    if isinstance(r9, bf_engine.NetError) and r9.kind in _NONCE_STOP_KINDS:
                        raise r9
                    try:
                        n9 = int(r9, 16)
                    except (TypeError, ValueError):
                        failed.append(w9)
                        continue
                    put(w9, n9)
                for w9 in failed:
                    if not put_one(w9):
                        return
        for w9 in rest:
            if not put_one(w9):
                return

    def _nonce_pass(self, head: int, lo_blk: int = None) -> int:
        st = self._nonce_load()
        now = _now()
        if float(st.get("bo_until") or 0) > now:
            return 0
        if now - float(st.get("at_w") or 0) < NONCE_HEAD_EVERY:
            return 0
        if lo_blk is None:
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
        if not self._nonce_due(st, now, lo_blk, busy, known_set):
            return 0
        st["at_w"] = int(now)
        base_rpc = self.rpc
        base_i = getattr(base_rpc, "i", None)
        arch = getattr(self, "arch_rpc", None) or base_rpc
        own_arch = arch is base_rpc and isinstance(base_rpc, Rpc) and bool(base_rpc.urls)
        if own_arch:
            arch = Rpc(list(base_rpc.urls))
            try:
                arch.i = int(st.get("arch_i") or 0) % len(arch.urls)
            except (TypeError, ValueError):
                arch.i = 0
        pub_rpc = getattr(self, "nonce_pub_rpc", base_rpc)
        cnt = {"arch": 0, "pub": 0, "found": 0, "emit": 0}
        self._nonce_last = cnt
        try:
            tok0 = float(st["old_tok"]) if st.get("old_tok") is not None else float(NONCE_OLD_BURST)
            tat0 = float(st.get("old_tok_at") or now)
        except (TypeError, ValueError):
            tok0, tat0 = float(NONCE_OLD_BURST), now
        old_tok = [min(float(NONCE_OLD_BURST), tok0 + max(0.0, now - tat0) * NONCE_CALL_CAP / float(NONCE_BACKLOG_EVERY))]
        old_a0 = [None]
        nxt = [0.0]
        blk = [False]
        halt = [None]

        def halt_on(e):
            if halt[0] is None and (isinstance(e, _NonceBudget) or (isinstance(e, bf_engine.NetError) and e.kind not in ("null", "rpc", "range"))):
                halt[0] = e

        def charge(n):
            if halt[0] is not None:
                raise halt[0]
            if cnt["arch"] + n > NONCE_CALL_CAP:
                e9 = _NonceBudget("nonce 확인 아카이브 호출 상한")
                halt_on(e9)
                raise e9
            cnt["arch"] += n
            w9 = nxt[0] - time.monotonic()
            if w9 > 0:
                time.sleep(w9)
            nxt[0] = time.monotonic() + NONCE_ARCH_GAP * n

        def pub_charge(n):
            if cnt["pub"] + n > NONCE_PUB_CAP:
                raise _NonceBudget("nonce 확인 공개 노드 호출 상한")
            cnt["pub"] += n

        class _Metered:

            def call(self_, m, p, *a, **kw):
                if not isinstance(arch, Rpc) or not arch.urls:
                    charge(1)
                    try:
                        return arch.call(m, p, *a, **kw)
                    except Exception as e:
                        halt_on(e)
                        raise
                if halt[0] is not None:
                    raise halt[0]
                tries9 = len(arch.urls)
                for k9 in range(tries9):
                    j9 = self_._pick()
                    charge(1)
                    try:
                        return self_._one(j9, m, p, kw.get("timeout", a[0] if a else 25))
                    except Exception as e:
                        if k9 + 1 < tries9 and isinstance(e, bf_engine.NetError) and e.kind in _NONCE_NEXT_KINDS:
                            continue
                        halt_on(e)
                        raise

            def _pick(self_):
                urls9 = arch.urls
                t9 = time.time()
                for k9 in range(len(urls9)):
                    j9 = (arch.i + k9) % len(urls9)
                    g9 = bf_engine.gate(urls9[j9])
                    if not (g9.open_until > t9 or g9.pause_until > t9):
                        return j9
                blk[0] = True
                e9 = _NonceBudget(bf_engine._url_host(urls9[arch.i % len(urls9)]) + " 쉬는 중(429·서킷)")
                halt_on(e9)
                raise e9

            def _one(self_, j9, m, p, timeout):
                urls9 = arch.urls
                u9 = urls9[j9]
                arch.i = j9
                host9 = bf_engine._url_host(u9)
                g9 = bf_engine.gate(u9)
                try:
                    d9 = bf_engine.http_json(u9, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                                             timeout=timeout, retries=1)
                    if not isinstance(d9, dict):
                        raise bf_engine.NetError(f"rpc {m}: 응답 형식 오류 ({type(d9).__name__})", "payload", host=host9)
                    if d9.get("error"):
                        e9 = bf_engine.classify_rpc_error(d9["error"])
                        e9.host = host9
                        if e9.kind in ("http429", "quota"):
                            g9.failure(e9)
                        raise e9
                    if d9.get("result") is None:
                        raise bf_engine.NetError(f"rpc {m}: result null", "null", host=host9)
                    return d9["result"]
                except Exception:
                    arch.i = (j9 + 1) % len(urls9)
                    raise

            def batch(self_, items, *a, **kw):
                out = []
                for m, p in items:
                    if halt[0] is not None:
                        out.append(halt[0])
                        continue
                    try:
                        out.append(self_.call(m, p, *a, **kw))
                    except Exception as e:
                        out.append(halt[0] if halt[0] is not None else e)
                return out

            def __getattr__(self_, k):
                return getattr(arch, k)

        pub_real = isinstance(pub_rpc, Rpc) and bool(pub_rpc.urls)

        def pub_req(body, n):
            urls9 = pub_rpc.urls
            last9 = None
            t9 = time.time()
            for k9 in range(len(urls9)):
                j9 = (pub_rpc.i + k9) % len(urls9)
                u9 = urls9[j9]
                g9 = bf_engine.gate(u9)
                if g9.open_until > t9 or g9.pause_until > t9:
                    continue
                if halt[0] is not None:
                    raise halt[0]
                pub_charge(n)
                try:
                    d9 = bf_engine.http_json(u9, data=json.dumps(body).encode(), timeout=25, retries=1, cost=n)
                    pub_rpc.i = j9
                    return d9, bf_engine._url_host(u9), g9
                except Exception as e:
                    if isinstance(e, bf_engine.NetError) and e.kind in _NONCE_STOP_KINDS:
                        halt_on(e)
                        raise
                    last9 = e
            if last9 is None:
                raise _PubDown("공개 노드 전부 쉬는 중(서킷·쉼)")
            raise last9

        def pub_err(d9, host9, g9):
            e9 = bf_engine.classify_rpc_error(d9["error"])
            e9.host = host9
            if e9.kind in ("http429", "quota"):
                g9.failure(e9)
            if e9.kind in _NONCE_STOP_KINDS:
                halt_on(e9)
            return e9

        def pub_single(m, p):
            d9, host9, g9 = pub_req({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, 1)
            if not isinstance(d9, dict):
                raise bf_engine.NetError(f"rpc {m}: 응답 형식 오류", "payload", host=host9)
            if d9.get("error"):
                raise pub_err(d9, host9, g9)
            if d9.get("result") is None:
                raise bf_engine.NetError(f"rpc {m}: result null", "null", host=host9)
            return d9["result"]

        def pub_batch(items):
            d9, host9, g9 = pub_req([{"jsonrpc": "2.0", "id": i9, "method": m, "params": p} for i9, (m, p) in enumerate(items)], len(items))
            if isinstance(d9, dict) and d9.get("error"):
                raise pub_err(d9, host9, g9)
            if not isinstance(d9, list):
                raise bf_engine.NetError("rpc batch: 응답 형식 오류", "payload", host=host9)
            out = [bf_engine.NetError("rpc batch: 응답 누락", "null", host=host9) for _ in items]
            for it in d9:
                try:
                    i9 = int(it.get("id"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not 0 <= i9 < len(items):
                    continue
                if it.get("error"):
                    out[i9] = pub_err(it, host9, g9)
                elif it.get("result") is not None:
                    out[i9] = it["result"]
            return out

        def pub_one(m, p, archive_ok=True):
            if pub_rpc is None:
                return self.rpc.call(m, p) if archive_ok else None
            if not pub_real:
                pub_charge(1)
                return pub_rpc.call(m, p)
            try:
                return pub_single(m, p)
            except _NonceBudget:
                raise
            except Exception as e:
                if halt[0] is not None:
                    raise
                if not archive_ok:
                    return None
                log.debug("BSC nonce 확인 — 공개 노드 실패 → 아카이브(계량): %s", _nonce_why(e))
                return self.rpc.call(m, p)

        def arch_blocked():
            urls9 = getattr(arch, "urls", None) or []
            if arch is base_rpc or not urls9:
                return None
            t9 = time.time()
            for u9 in urls9:
                g9 = bf_engine.gate(u9)
                if not (g9.open_until > t9 or g9.pause_until > t9):
                    return None
            return bf_engine._url_host(urls9[0]) + " 쉬는 중(429·서킷)"

        def sample(v, b):
            n9 = int(self.rpc.call("eth_getTransactionCount", [v.w, hex(int(b))]), 16)
            lo9 = max((x for x in v.smp if x < b), default=None)
            hi9 = min((x for x in v.smp if x > b), default=None)
            if (lo9 is not None and n9 < v.smp[lo9]) or (hi9 is not None and n9 > v.smp[hi9]):
                raise RuntimeError(f"블록 {b} nonce {n9} 가 이웃 표본과 순서 어긋남(노드 불일치)")
            v.smp[int(b)] = n9

        def pend_of(v, z):
            pd = v.ws.get("pend")
            return pd if isinstance(pd, dict) and pd.get("z") == z and isinstance(pd.get("h"), list) else None

        def resolve(v, z):
            w = v.w
            ws = v.ws
            hs = ws.setdefault("hashes", {})
            pd = pend_of(v, z)
            if pd is None:
                blk = self.rpc.call("eth_getBlockByNumber", [hex(z), True]) or {}
                txs9 = blk.get("transactions")
                try:
                    num9 = int(str(blk.get("number") or "0x0"), 16)
                except ValueError:
                    num9 = -1
                if num9 != z or not isinstance(txs9, list) or any(not isinstance(t, dict) or not t.get("from") or not t.get("hash") for t in txs9):
                    raise RuntimeError(f"블록 {z} 전체 응답 불완전")
                try:
                    ts9 = int(str(blk.get("timestamp")), 16)
                except (TypeError, ValueError, AttributeError):
                    ts9 = None
                mine = [t for t in txs9 if str(t.get("from") or "").lower() == w]
                diff9 = v.smp[z] - v.smp[z - 1]
                extra9 = diff9 - len(mine)
                if diff9 <= 0:
                    raise RuntimeError(f"블록 {z} nonce 증가 없음 — 표본 불일치")
                if extra9 < 0:
                    raise RuntimeError(f"블록 {z} nonce 증가량({diff9}) < 내 발신 tx {len(mine)}")
                if extra9 > 0:
                    ws.setdefault("nonce_extra", {})[str(z)] = extra9
                    log.info("BSC nonce 확인 %s: 블록 %d nonce +%d 은 발신 tx 아님(7702 위임 등) — 기록하고 다음으로", w[:10], z, extra9)
                pd = {"z": z, "h": [str(t.get("hash") or "").lower() for t in mine], "ts": ts9}
                ws["pend"] = pd
            cnt["found"] += 1
            if isinstance(pd.get("ts"), int):
                self.block_ts[hex(z)] = pd["ts"]
            stop9 = None
            for h in pd["h"]:
                if not h:
                    continue
                if h in hs or h in self.emitted:
                    hs[h] = z
                    continue
                if halt[0] is not None:
                    stop9 = halt[0]
                    break
                if NONCE_CALL_CAP - cnt["arch"] < 2:
                    stop9 = _NonceBudget("nonce 확인 아카이브 호출 상한(발신 하나 몫 부족 — 다음 실행)")
                    halt_on(stop9)
                    break
                snap = self.fetch_details([h]).get(h)
                if not isinstance(snap, dict):
                    if halt[0] is not None:
                        stop9 = halt[0]
                        break
                    raise RuntimeError(f"상세 실패 {h[:12]}: {_nonce_why(snap)}")
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap,
                                    "wallets": self.wallets, "observed_head": head, "ts": int(time.time()), "via": "nonce"})
                self.emitted.add(h)
                cnt["emit"] += 1
                log.info("★BSC 로그 없는 발신 tx 회수(nonce) %s 블록 %d★", h[:14], z)
                hs[h] = z
            v.reindex()
            if stop9 is not None:
                raise stop9
            ws.pop("pend", None)
            if any(a9 == z - 1 and z9 == z for a9, z9, _d9 in v.intervals()[0]):
                log.info("BSC nonce 확인 %s: 블록 %d 해결 뒤에도 nonce 증가가 남음 — 표본 초기화", w[:10], z)
                v.reset()
                v.skip = True

        wl = list(self.wallets)
        rr = int(st.get("rr") or 0) % len(wl) if wl else 0
        order = wl[rr:] + wl[:rr]
        views = {}
        err = None
        blocked = False
        last_w = None
        self.rpc = _Metered()
        try:
            why0 = arch_blocked()
            if why0:
                blocked = True
                halt[0] = _NonceBudget(why0)
                log.info("BSC nonce 확인 — 아카이브 %s: 이번엔 헤드 확인만", why0)
            for w in order:
                if w in busy or (isinstance(known_set, list) and w not in known_set):
                    continue
                ws = st["w"].setdefault(w, {})
                if ws.get("kind") is None:
                    code = str(pub_one("eth_getCode", [w, "latest"]) or "0x").lower()
                    ws["kind"] = "eoa" if code in ("0x", "0x0", "") or code.startswith("0xef0100") else "contract"
                if ws["kind"] != "eoa":
                    ws.pop("hint", None)
                    continue
                views[w] = _NView(w, ws, lo_blk)

            def hints(v):
                return [h9 for h9 in (v.ws.get("hint") or []) if isinstance(h9, list) and len(h9) == 2 and isinstance(h9[0], int)]
            def head_due(v):
                return v.top is None or now - v.top_at >= NONCE_HEAD_EVERY or any(h9[0] + NONCE_HINT_FAR > v.top for h9 in hints(v))
            need = []
            for w, v in views.items():
                if head_due(v):
                    if v.top is None or v.top < safe:
                        need.append(w)
                    else:
                        v.top_at = now

            def put_top(w, n9):
                v = views[w]
                if v.top is not None and n9 < v.smp.get(v.top, 0):
                    log.info("BSC nonce 확인 %s: 헤드 nonce %d < 지난 확인 %d — 이번엔 헤드 확인 건너뜀(노드 뒤처짐)", w[:10], n9, v.smp.get(v.top, 0))
                    return
                v.smp[safe] = n9
                v.top = safe
                v.top_at = now
                if n9 == 0 and v.lo_n is None:
                    v.set_lo(0)
                v.reindex()
            bfn = pub_batch if pub_real else (None if pub_rpc is None or not callable(getattr(pub_rpc, "batch", None))
                                              else (lambda it9: (pub_charge(len(it9)), pub_rpc.batch(it9))[1]))
            need.sort(key=lambda w9: (views[w9].top is not None, views[w9].top_at))
            self._nonce_tops(bfn, need, safe, put_top,
                             lambda w9, bh9: pub_one("eth_getTransactionCount", [w9, bh9],
                                                     archive_ok=views[w9].top is None or now - views[w9].top_at >= NONCE_EVERY),
                             can_one=lambda: cnt["arch"] < NONCE_CALL_CAP // 2)
            if halt[0] is not None:
                raise halt[0]
            for w, v in views.items():
                if v.lo_n is None and v.top is not None:
                    v.set_lo(int(self.rpc.call("eth_getTransactionCount", [w, hex(lo_blk)]), 16))
                    v.reindex()
            for w, v in views.items():
                if not v.ready():
                    continue
                _iv, bad = v.intervals()
                if bad:
                    log.info("BSC nonce 확인 %s: 표본·색인이 서로 안 맞음 — 표본 초기화(다시 좁힘)", w[:10])
                    v.reset()
                m9 = v.missing()
                v.ws["missing"] = m9
                if m9 < 0:
                    log.info("BSC nonce 확인 %s: 색인 발신 %d > nonce 차 — 건너뜀(원장·색인 불일치)", w[:10], len(v.blocks))
                    v.skip = True
            act = [w for w in order if w in views and views[w].ready() and not views[w].skip]
            for w in act:
                v = views[w]
                hl = hints(v)
                if not hl:
                    v.ws.pop("hint", None)
                    continue
                keep = []
                for b9, t9 in hl:
                    if now - float(t9) > NONCE_HINT_KEEP or b9 <= lo_blk:
                        continue
                    for p9 in (b9 - 1, b9 + NONCE_HINT_NEAR, b9 + NONCE_HINT_FAR):
                        if lo_blk < p9 < v.top and p9 not in v.smp and v.open_at(p9):
                            sample(v, p9)
                    if b9 + NONCE_HINT_FAR > v.top:
                        keep.append([b9, t9])
                if keep:
                    v.ws["hint"] = keep
                else:
                    v.ws.pop("hint", None)
            rlo = safe - max(1, int(NONCE_RECENT_SEC / self._bsec()))
            old_ok = old_tok[0] >= NONCE_CALL_CAP / 2.0
            pos = 0
            while act and cnt["found"] < NONCE_MAX_FIND:
                ivs = {w9: (views[w9].intervals()[0] if not views[w9].skip else []) for w9 in act}
                live = [w9 for w9 in act if ivs[w9]]
                if not live:
                    break
                rec = {w9: [t9 for t9 in ivs[w9] if t9[1] > rlo] for w9 in live}
                rec = {w9: r9 for w9, r9 in rec.items() if r9}
                if rec:
                    pool9, cand = rec, set(rec)
                elif old_ok:
                    if old_a0[0] is None:
                        old_a0[0] = cnt["arch"]
                    pool9 = ivs
                    cand = {w9 for w9 in live if min(z9 - a9 for a9, z9, _d9 in ivs[w9]) <= NONCE_NARROW} or set(live)
                else:
                    break
                w = next(act[(pos + j) % len(act)] for j in range(len(act)) if act[(pos + j) % len(act)] in cand)
                pos = (act.index(w) + 1) % len(act)
                a9, z9, _d9 = min(pool9[w], key=lambda t9: (t9[1] - t9[0], -t9[0]))
                last_w = w
                v = views[w]
                if z9 - a9 == 1:
                    if NONCE_CALL_CAP - cnt["arch"] < (2 if pend_of(v, z9) else 3):
                        raise _NonceBudget("nonce 확인 아카이브 호출 상한(블록 해결 몫 부족 — 다음 실행)")
                    resolve(v, z9)
                elif w in rec and a9 < rlo < z9 and rlo not in v.smp:
                    sample(v, rlo)
                else:
                    sample(v, (a9 + z9) // 2)
        except _NonceBudget as e:
            log.debug("BSC nonce 확인 — 이번 실행 상한: %s", e)
        except Exception as e:
            err = e
        finally:
            if own_arch:
                st["arch_i"] = arch.i
            self.rpc = base_rpc
            if base_i is not None:
                try:
                    base_rpc.i = base_i
                except AttributeError:
                    pass
        st["old_tok"] = round(old_tok[0] - (cnt["arch"] - old_a0[0] if old_a0[0] is not None else 0), 2)
        st["old_tok_at"] = int(now)
        if blk[0]:
            blocked = True
        if halt[0] is not None:
            err = None if isinstance(halt[0], _NonceBudget) else halt[0]
        left = 0
        n_left = 0
        for v in views.values():
            if v.ready():
                try:
                    if not v.skip:
                        v.prune()
                        v.ws["missing"] = v.missing()
                        if v.ws["missing"] <= 0:
                            v.ws.pop("pend", None)
                except Exception as e:
                    log.debug("BSC nonce 표본 정리 실패 %s: %s", v.w[:10], e)
            v.save()
            m9 = v.ws.get("missing")
            if isinstance(m9, int) and m9 > 0:
                left += m9
                n_left += 1
        for ws in st["w"].values():
            ws["blocks"] = sorted((ws.get("hashes") or {}).values())
        if wl:
            st["rr"] = (wl.index(last_w) + 1) % len(wl) if last_w in wl else (rr + 1) % len(wl)
        if err is None:
            if not blocked:
                st.pop("bo_until", None)
                st["bo_n"] = 0
        else:
            n9 = int(st.get("bo_n") or 0) + 1
            st["bo_n"] = n9
            wait9 = int(min(NONCE_BO_MAX, NONCE_BO_BASE * (2 ** min(n9 - 1, 16))))
            st["bo_until"] = int(_now() + wait9)
            log.info("BSC nonce 확인 중단(%d초 쉼 뒤 다음 기회): %s", wait9, _nonce_why(err))
        common.atomic_write_json(self._nonce_path(), st)
        common.write_json_if_changed(self.meta_path, self.token_meta)
        if cnt["emit"]:
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if cnt["arch"] or cnt["emit"] or err is not None:
            log.info("BSC nonce 회수: 아카이브 %d콜 · 공개 %d콜 · 찾은 블록 %d · 방출 %d · 남은 누락 %d건(지갑 %d개)",
                     cnt["arch"], cnt["pub"], cnt["found"], cnt["emit"], left, n_left)
        return cnt["emit"]

    def _xin_hints(self, memo: dict) -> int:
        need = [h for h, m9 in memo.items() if isinstance(m9, dict) and m9.get("r") == "emit" and not m9.get("hint")
                and isinstance(m9.get("blk"), int)]
        if not need:
            return 0
        tos = {}
        if any(not memo[h].get("to") for h in need) and os.path.exists(common.DB_PATH):
            import sqlite3
            try:
                con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
                try:
                    q9 = [h for h in need if not memo[h].get("to")]
                    rows = []
                    for i9 in range(0, len(q9), 500):
                        c9 = q9[i9:i9 + 500]
                        rows += con.execute("SELECT lower(txhash), lower(json_extract(snapshot, '$.tx.to')) FROM raw_txs WHERE chain='bsc'"
                                            " AND lower(txhash) IN (" + ",".join("?" * len(c9)) + ")", c9).fetchall()
                finally:
                    con.close()
                tos = {str(h9): str(t9 or "") for h9, t9 in rows}
            except Exception as e:
                log.debug("BSC 거래소 출금 힌트 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
        n = 0
        for h in need:
            m9 = memo[h]
            to9 = str(m9.get("to") or tos.get(h) or "").lower()
            if to9 in self.wallets:
                try:
                    n += 1 if self._nonce_hint(to9, m9["blk"]) else 0
                    m9["hint"] = 1
                except Exception as e:
                    log.debug("BSC nonce 힌트 기록 실패: %s", str(e)[:120])
            else:
                m9["hint_n"] = int(m9.get("hint_n") or 0) + 1
                if m9["hint_n"] >= self.XIN_HINT_TRIES:
                    m9["hint"] = -1
        return n

    def _xin_path(self) -> str:
        return os.path.join(common.STATE_DIR, "bsc_xin.json")

    def _xin_cands(self) -> list:
        if not os.path.exists(common.DB_PATH):
            return []
        import sqlite3
        con = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
        try:
            rows = con.execute(
                "SELECT r.payload FROM raw_ex r JOIN (SELECT exchange, uuid, max(revision) AS rv FROM raw_ex WHERE kind='withdraw'"
                " GROUP BY exchange, uuid) x ON x.exchange=r.exchange AND x.uuid=r.uuid AND x.rv=r.revision"
                " WHERE r.kind='withdraw' AND upper(json_extract(r.payload, '$.currency'))='BNB'").fetchall()
        finally:
            con.close()
        mine = set(self.wallets)
        out = {}
        for (pl,) in rows:
            try:
                p = json.loads(pl)
            except (TypeError, ValueError):
                continue
            if not isinstance(p, dict) or str(p.get("state") or "").upper() not in ("DONE", "ACCEPTED"):
                continue
            tx = str(p.get("txid") or "").strip().lower()
            if len(tx) == 64 and not tx.startswith("0x"):
                tx = "0x" + tx
            if not _XIN_TXID.match(tx):
                continue
            net = str(p.get("network") or p.get("net_type") or "").strip()
            if net and not _XIN_NET.search(net):
                continue
            addr = str(p.get("address") or "").strip().lower()
            if addr and addr not in mine:
                continue
            t9 = common.iso_epoch(p.get("done_at")) or common.iso_epoch(p.get("created_at")) or 0
            out[tx] = max(out.get(tx, 0), t9)
        return sorted(out, key=lambda h: (-out[h], h))

    def _xin_pass(self, head: int) -> int:
        try:
            st = common.read_json(self._xin_path(), {})
        except SystemExit as e:
            log.warning("BSC 거래소 출금 txid 진행 파일 손상 — 새로 시작: %s", str(e)[:120])
            st = {}
        if not isinstance(st, dict) or not isinstance(st.get("tx"), dict):
            st = {"tx": {}}
        if _now() - float(st.get("at") or 0) < XIN_EVERY:
            return 0
        st["at"] = int(_now())
        lo_blk = self.cursor.get("_cov") if isinstance(self.cursor.get("_cov"), int) else self.cursor.get("_bf_start")
        safe = int(head) - self.conf_depth
        n_emit = 0
        try:
            cands = self._xin_cands()
        except Exception as e:
            log.info("BSC 거래소 출금 txid 확인 — 원장 읽기 실패(다음 기회): %s", str(e)[:120])
            common.atomic_write_json(self._xin_path(), st)
            return 0
        memo = st["tx"]
        w9 = sorted(set(self.wallets))
        if st.get("wallets") != w9:
            for m9 in memo.values():
                if isinstance(m9, dict) and m9.get("r") == "not_direct":
                    m9["r"] = "retry"
            st["wallets"] = w9
        if isinstance(lo_blk, int):
            for h in cands:
                m9 = memo.get(h) or {}
                if m9.get("r") == "old" and isinstance(m9.get("blk"), int) and m9["blk"] > lo_blk:
                    m9["r"] = "retry"
        todo = [h for h in cands if h not in self.emitted and (memo.get(h) or {}).get("r") in (None, "retry", "ahead", "nf")
                and not ((memo.get(h) or {}).get("r") == "nf" and int((memo.get(h) or {}).get("nf_n") or 0) >= XIN_NF_MAX)]
        todo.sort(key=lambda h: int((memo.get(h) or {}).get("tried_at") or 0))
        n_new = 0
        for h in todo:
            if n_new >= XIN_MAX_NEW:
                break
            m = memo.setdefault(h, {})
            n_new += 1
            m["tried_at"] = int(_now())
            try:
                snap = self.fetch_details([h]).get(h)
            except Exception as e:
                snap = e
            if not isinstance(snap, dict):
                nf = _xin_not_found(snap)
                m.update(r="nf" if nf else "retry", n=int(m.get("n") or 0) + 1,
                         nf_n=(int(m.get("nf_n") or 0) + 1 if m.get("r") == "nf" else 1) if nf else 0, err=common.safe_err(snap)[:120])
                continue
            tx = snap.get("tx") or {}
            try:
                blk = int(tx.get("block_number"))
                val = int(str(tx.get("value") or "0"))
            except (TypeError, ValueError):
                m.update(r="retry", n=int(m.get("n") or 0) + 1)
                continue
            to = str(tx.get("to") or "").lower()
            if to not in self.wallets or val <= 0 or tx.get("status") != "ok":
                m.update(r="not_direct", blk=blk)
                continue
            if isinstance(lo_blk, int) and blk <= lo_blk:
                m.update(r="old", blk=blk)
                continue
            if blk > safe:
                m.update(r="ahead", blk=blk)
                continue
            try:
                self.writer.append({"v": 1, "kind": "evm_tx", "chain": "bsc", "txhash": h, "snapshot": snap, "wallets": self.wallets,
                                    "observed_head": head, "ts": int(time.time()), "via": "exchange_txid"})
            except Exception as e:
                log.error("BSC 거래소 출금 txid 회수 — inbox 쓰기 실패(다음 기회): %s", e)
                break
            self.emitted.add(h)
            m.update(r="emit", blk=blk, to=to)
            n_emit += 1
            log.info("★BSC 받는 쪽 순수 BNB 회수(거래소 출금 txid) %s 블록 %d★", h[:14], blk)
        self._xin_hints(memo)
        st["tx"] = {h: v for h, v in memo.items() if h in set(cands)}
        common.atomic_write_json(self._xin_path(), st)
        if n_emit:
            common.write_json_if_changed(self.meta_path, self.token_meta)
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        return n_emit
