#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, logs, paths  # noqa: E402
import bf_engine  # noqa: E402
import btc_descriptor as bd  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state  # noqa: E402
import chain_watch  # noqa: E402

CHAIN = "btc"
PARSER_VERSION = 1
STATE_VERSION = 1
DEFAULT_ESPLORA = ("https://blockstream.info/api", "https://mempool.space/api")
DEFAULT_MIN_CONF = 6
DEFAULT_RPS = 2.0
DEFAULT_CALLS_PER_PAGE = 15
MAX_INDEX = 100000
TIME_SLACK = 86400
RING_KEEP = 12
PREVOUT_CACHE = 500
SAT_MAX = 21_000_000 * 10 ** 8
FAIL_SWITCH = 2
CYCLE_FAIL_CAP = 3
COOL_MIN, COOL_MAX = 300, 3600
SCOPE_KEEP, SCOPE_TTL = 256, 6 * 3600


class NotFound(chain_watch.Transient):
    pass


class _NotMine(chain_watch.Transient):
    pass


def _sk(text) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()[:12]


def _bad(what):
    return chain_watch.Transient(f"Esplora 응답 형식 오류: {what}")


def _int(v, what, lo=0, hi=None):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
        raise _bad(what)
    return v


def _txid(v, what="txid"):
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v.lower()):
        raise _bad(what)
    return v.lower()


def _spk(v, what):
    if not isinstance(v, str) or len(v) % 2 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise _bad(what)
    return v.lower()


class Esplora:

    def __init__(self, bases, rps=DEFAULT_RPS, transport=None):
        self.bases = [str(b).rstrip("/") for b in bases if str(b).strip()]
        if not self.bases:
            raise ValueError("Esplora 주소가 없어요")
        self.cur = 0
        self.bad = {}
        self.cool = {}
        self.strikes = {}
        self.cyc_bad = 0
        self.why = None
        self.on_trouble = None
        self._open = False
        self.switched = False
        self.calls = 0
        self.transport = transport
        if transport is None:
            for b in self.bases:
                bf_engine.set_call_rate(b, rps)

    @property
    def base(self) -> str:
        return self.bases[self.cur % len(self.bases)]

    @property
    def host(self) -> str:
        return (urllib.parse.urlsplit(self.base).hostname or "?").lower()

    def pick(self, host) -> bool:
        for i, b in enumerate(self.bases):
            if host and (urllib.parse.urlsplit(b).hostname or "").lower() == str(host).lower():
                self.cur = i
                return True
        return False

    def get(self, path: str):
        url = self.base + path
        self.calls += 1
        try:
            if self.transport is not None:
                d = self.transport(url)
            else:
                d, _h = bf_engine.http_request(url, timeout=20.0, retries=2, prio="bg", max_inline_wait=10.0)
        except bf_engine.NetError as e:
            if getattr(e, "code", None) == 404:
                raise NotFound(f"{self.host}: 404(없음)")
            raise chain_watch.Transient(f"{self.host}: {e.kind}{' ' + str(e.code) if e.code else ''}")
        except chain_watch.Transient:
            raise
        except (OSError, ValueError) as e:
            raise chain_watch.Transient(f"{self.host}: {type(e).__name__}")
        return d

    @contextlib.contextmanager
    def scope(self, key):
        if self._open:
            yield
            return
        self._open = True
        try:
            yield
        except (NotFound, _NotMine):
            raise
        except chain_watch.Transient:
            self._fail(key)
            raise
        else:
            self.bad.pop(key, None)
        finally:
            self._open = False

    def _fail(self, key):
        now = time.time()
        n, t = self.bad.pop(key, (0, now))
        n = (0 if now - t > SCOPE_TTL else int(n)) + 1
        self.bad[key] = (n, now)
        while len(self.bad) > SCOPE_KEEP:
            self.bad.pop(next(iter(self.bad)))
        self.cyc_bad += 1
        if n >= FAIL_SWITCH and self._switch(key, now):
            return
        if self.cyc_bad >= CYCLE_FAIL_CAP and self.on_trouble:
            self.on_trouble(False, None)

    def _switch(self, key, now) -> bool:
        if len(self.bases) < 2:
            return False
        for d in range(1, len(self.bases)):
            j = (self.cur + d) % len(self.bases)
            if self.cool.get(j, 0) <= now:
                break
        else:
            return False
        k = self.strikes[self.cur] = self.strikes.get(self.cur, 0) + 1
        self.cool[self.cur] = now + min(COOL_MAX, COOL_MIN * 2 ** (k - 1))
        old = self.host
        self.cur = j
        self.bad = {}
        self.switched = True
        self.why = str(key).split(":", 1)[0]
        if self.on_trouble:
            self.on_trouble(True, old)
        return True

    def blocks(self, height=None, role="bnd") -> list:
        with self.scope("tip" if height is None else ("ring" if role == "ring" else "bnd")):
            d = self.get("/blocks" + ("" if height is None else f"/{int(height)}"))
            if not isinstance(d, list) or not d:
                raise _bad("blocks")
            out = []
            for b in d:
                if not isinstance(b, dict):
                    raise _bad("blocks 줄")
                out.append((_int(b.get("height"), "block height"), _txid(b.get("id"), "block id"), _int(b.get("timestamp"), "block time")))
            if height is not None and out[0][0] != int(height):
                raise _bad("blocks 요청 높이와 첫 블록 높이가 다름")
            return out

    def addr_stats(self, addr: str):
        with self.scope("st:" + _sk(addr)):
            d = self.get(f"/address/{addr}")
            if not isinstance(d, dict) or not isinstance(d.get("chain_stats"), dict) or not isinstance(d.get("mempool_stats"), dict):
                raise _bad("address stats")
            cs = d["chain_stats"]
            f = _int(cs.get("funded_txo_sum"), "funded_txo_sum", 0, None)
            s = _int(cs.get("spent_txo_sum"), "spent_txo_sum", 0, None)
            if s > f:
                raise _bad("spent > funded")
            return _int(cs.get("tx_count"), "tx_count"), f - s, _int(d["mempool_stats"].get("tx_count"), "mempool tx_count")

    def addr_chain_txs(self, addr: str, last_seen: str = None, need: bool = False) -> list:
        with self.scope("ls:" + _sk(addr)):
            d = self.get(f"/address/{addr}/txs/chain" + (f"/{_txid(last_seen)}" if last_seen else ""))
            if not isinstance(d, list):
                raise _bad("address txs")
            for t in d:
                st = t.get("status") if isinstance(t, dict) else None
                if not isinstance(st, dict) or st.get("confirmed") is not True:
                    raise _bad("chain txs 에 미확정 거래")
                _txid(t.get("txid"))
                _int(st.get("block_height"), "block_height")
                _int(st.get("block_time"), "block_time")
            if not d and need:
                raise _bad("주소 거래 수와 빈 이력 응답이 맞지 않음")
            return d

    def tx(self, txid: str) -> dict:
        with self.scope("tx:" + _sk(txid)):
            d = self.get(f"/tx/{_txid(txid)}")
            if not isinstance(d, dict) or _txid(d.get("txid")) != txid.lower():
                raise _bad("tx")
            if not isinstance(d.get("vin"), list) or not isinstance(d.get("vout"), list) or not isinstance(d.get("status"), dict):
                raise _bad("tx vin/vout/status")
            if not isinstance(d["status"].get("confirmed"), bool):
                raise _bad("tx status confirmed")
            return d


def window_start(cfg: dict, now: float = None) -> int:
    months = 0.0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
    if months <= 0:
        return 0
    now = time.time() if now is None else float(now)
    vals = [v for v in (bf_engine.SINCE.target(None), bf_engine.SINCE.target(CHAIN)) if v]
    return int(min([int(now - months * 30 * 86400)] + vals))


def _settings(cfg: dict) -> dict:
    s = ((cfg or {}).get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) if isinstance((cfg or {}).get(reg.CFG_CHAIN_KEY), dict) else None
    s = s if isinstance(s, dict) else {}
    bases = s.get("esplora")
    if isinstance(bases, str):
        bases = [bases]
    ok = [b for b in (bases or []) if isinstance(b, str) and (b.startswith("https://") or b.startswith("http://127.0.0.1")
                                                                or b.startswith("http://localhost"))]
    mc = s.get("min_conf", DEFAULT_MIN_CONF)
    mc = mc if isinstance(mc, int) and not isinstance(mc, bool) and 1 <= mc <= 100 else DEFAULT_MIN_CONF
    rps = s.get("rps", DEFAULT_RPS)
    rps = float(rps) if isinstance(rps, (int, float)) and not isinstance(rps, bool) and 0 < rps <= 50 else DEFAULT_RPS
    cpp = s.get("calls_per_page", DEFAULT_CALLS_PER_PAGE)
    cpp = cpp if isinstance(cpp, int) and not isinstance(cpp, bool) and 2 <= cpp <= 500 else DEFAULT_CALLS_PER_PAGE
    ack = s.get("reorg_ack")
    return {"esplora": ok or list(DEFAULT_ESPLORA), "min_conf": mc, "rps": rps, "calls_per_page": cpp,
            "reorg_ack": ack if isinstance(ack, int) and not isinstance(ack, bool) else None}


def _bkey(b) -> str:
    return str(b)


def _addr_order(item):
    a = item[1]
    return (str(a.get("b")), int(a.get("i") or 0), item[0])


class _Budget(Exception):
    pass


class BtcAdapter(reg.ChainAdapter):

    chain = CHAIN

    def __init__(self, cfg: dict, transport=None):
        super().__init__(cfg)
        self.set = _settings(cfg)
        self.min_conf = self.set["min_conf"]
        self.es = Esplora(self.set["esplora"], self.set["rps"], transport)
        self.st = None
        self.log = None
        self.tipc = None
        self.soft_errors = 0
        self.stopped = False
        self.calls_left = 0
        self._plans = {}
        self._own = None
        self._prevouts = {}
        self.rows = {r["key"]: r for r in reg.wallets(cfg, CHAIN)}

    def bind(self, state: chain_state.ChainState, log=None):
        self.st, self.log = state, log
        b = state.d.get("btc")
        if not isinstance(b, dict) or b.get("v") != STATE_VERSION:
            state.d["btc"] = {"v": STATE_VERSION, "wallets": {}, "ring": [], "hold": None}
        self.es.pick((state.d["btc"].get("provider") or {}).get("host"))
        self.es.on_trouble = self._trouble
        return self

    def _trouble(self, switched, old=None):
        self.tipc = None
        self.stopped = True
        if not switched:
            return
        for w in self.sb["wallets"].values():
            if isinstance(w.get("pass"), dict) and w["pass"].get("c") is not None:
                w["pass"]["c"] = None
            if isinstance(w.get("sweep"), dict):
                w["sweep"]["c"] = None
        self.sb["provider"] = {"host": self.es.host, "at": int(time.time()), "why": self.es.why}
        self._warn("[btc] Esplora 제공자 전환 %s → %s(같은 요청 연속 실패: %s) — 다음 주기에 새 제공자 tip·확정 경계부터", old, self.es.host, self.es.why)

    @property
    def sb(self) -> dict:
        return self.st.d["btc"]

    def prune_wallets(self, keep: set) -> int:
        gone = [w for w in self.sb["wallets"] if w not in keep]
        for w in gone:
            self.sb["wallets"].pop(w, None)
        self._own = None
        return len(gone)

    def _say(self, msg, *a):
        if self.log:
            self.log.info(msg, *a)

    def _warn(self, msg, *a):
        if self.log:
            self.log.warning(msg, *a)

    def _plan(self, wid):
        if wid not in self._plans:
            row = self.rows.get(wid)
            if row is None:
                raise ValueError("설정에 없는 BTC 지갑")
            e = row["entry"]
            if row["mode"] == "descriptor":
                self._plans[wid] = bd.plan_from_descriptor(str(e.get("descriptor") or ""), row["network"])
            else:
                self._plans[wid] = None
        return self._plans[wid]

    def _wcfg(self, wid) -> dict:
        row = self.rows[wid]
        e = row["entry"]
        if row["mode"] == "descriptor":
            p = self._plan(wid)
            gap = int(e.get("gap_limit", 20))
            re_ = e.get("range_end")
            re_ = re_ if isinstance(re_, int) and not isinstance(re_, bool) and 0 <= re_ < MAX_INDEX else None
            return {"mode": "descriptor", "branches": [_bkey(b) for b in p.branches], "gap": gap, "range_end": re_}
        src = reg.btc_source(e, row["network"])
        return {"mode": "address", "branches": ["a"], "gap": 0, "range_end": None, "address": src["address"], "script": src["script"]}

    def _fp(self, wid, lane) -> str:
        import hashlib
        c = self._wcfg(wid)
        return hashlib.sha256(f"btc|v{STATE_VERSION}|{wid}|{c['gap']}|{c['range_end']}|{lane}".encode()).hexdigest()[:16]

    def _w(self, wid) -> dict:
        c = self._wcfg(wid)
        fp = self._fp(wid, "state")
        w = self.sb["wallets"].get(wid)
        notes = []
        if c["mode"] == "address":
            notes.append("single_address")
        elif c["branches"] == ["0"]:
            notes.append("single_branch_receive")
        elif c["branches"] == ["1"]:
            notes.append("single_branch_change")
        if not isinstance(w, dict):
            w = {"mode": c["mode"], "fp": fp, "from_ts": None, "hist_done": False, "br": {b: {"used": -1} for b in c["branches"]},
                 "addrs": {}, "pass": {"phase": "scan", "bi": 0, "i": 0, "q": [], "c": None}, "sweep": None, "swept": -1, "notes": notes,
                 "own_F": None}
            self.sb["wallets"][wid] = w
            self._own = None
        elif w.get("fp") != fp:
            w["fp"] = fp
            w["hist_done"] = False
            w["pass"] = {"phase": "scan", "bi": 0, "i": 0, "q": [], "c": None}
            w["sweep"] = None
            w["own_F"] = None
            self._own = None
        w["notes"] = sorted(set(notes) | {n for n in (w.get("notes") or []) if n.startswith("dup:")})
        return w

    def _end(self, wid, w, b) -> int:
        c = self._wcfg(wid)
        if c["mode"] == "address":
            return 0
        e = int(w["br"].get(b, {}).get("used", -1)) + c["gap"]
        if c["range_end"] is not None:
            e = max(e, c["range_end"])
        return min(e, MAX_INDEX - 1)

    def _derive(self, wid, b, i):
        c = self._wcfg(wid)
        if c["mode"] == "address":
            return c["script"], c["address"]
        return self._plan(wid).derive(int(b), int(i))

    def ownership(self, wallets=None) -> dict:
        ws = sorted(wallets if wallets is not None else self.rows,
                    key=lambda x: (self.rows.get(x, {}).get("mode") != "descriptor", x))
        own = {}
        for wid in ws:
            if wid not in self.rows:
                continue
            w = self._w(wid)
            dups = set()
            for b in self._wcfg(wid)["branches"]:
                for i in range(0, self._end(wid, w, b) + 1):
                    s, a = self._derive(wid, b, i)
                    if s in own and own[s][0] != wid:
                        dups.add(own[s][0])
                        continue
                    own.setdefault(s, (wid, a))
            w["notes"] = sorted({n for n in w["notes"] if not n.startswith("dup:")} | {"dup:" + d for d in dups})
        return own

    def owned_addrs(self, wid, own) -> list:
        return sorted((a, s) for s, (w9, a) in own.items() if w9 == wid)

    def begin_cycle(self):
        self.soft_errors = 0
        self.stopped = False
        self.tipc = None
        self.es.switched = False
        self.es.cyc_bad = 0
        self._own = None
        try:
            tip = self.es.blocks()[0]
        except chain_watch.Transient as e:
            self.soft_errors += 1
            self.stopped = True
            self._warn("[btc] tip 조회 실패(다음 주기): %s", logs.safe_err(e)[:120])
            return
        F = tip[0] - self.min_conf + 1
        ring = self.sb.setdefault("ring", [])
        last = ring[-1][0] if ring else None
        if last is None or F > last:
            try:
                blk = self.es.blocks(F)
            except chain_watch.Transient as e:
                self.soft_errors += 1
                self.stopped = True
                self._warn("[btc] 확정 블록 조회 실패(다음 주기): %s", logs.safe_err(e)[:120])
                return
            seen = {h: hs for h, hs, _t in blk}
            if blk[0][0] != F:
                self.soft_errors += 1
                self.stopped = True
                return
            if not self._reorg_check(seen):
                self.stopped = True
                self.soft_errors += 1
                return
            ring.append([F, blk[0][1], blk[0][2]])
            del ring[:-RING_KEEP]
        self.tipc = (tip[0], tip[1], F)
        self._ack_hold()

    def _reorg_check(self, seen: dict) -> bool:
        ring = self.sb.get("ring") or []
        if not ring:
            return True
        bad = [r for r in ring if r[0] in seen and seen[r[0]] != r[1]]
        unseen = [r for r in ring if r[0] not in seen]
        if not bad and unseen and ring[-1][0] not in seen:
            try:
                more = {h: hs for h, hs, _t in self.es.blocks(ring[-1][0], role="ring")}
            except chain_watch.Transient:
                return False
            seen = {**seen, **more}
            bad = [r for r in ring if r[0] in seen and seen[r[0]] != r[1]]
        if not bad:
            return True
        good = [r[0] for r in ring if r[0] in seen and seen[r[0]] == r[1]]
        low_bad = min(r[0] for r in bad)
        anc = max([g for g in good if g < low_bad], default=None)
        self._deep_reorg(anc, max(r[0] for r in bad))
        return True

    def _deep_reorg(self, anc, top):
        now = int(time.time())
        frm = (anc + 1) if anc is not None else None
        self.sb["hold"] = {"at": now, "from_height": frm, "top": top,
                           "why": "깊은 재편(reorg) — 확정 깊이보다 깊은 블록이 바뀜: 그 높이 이후 이미 기장한 BTC 거래가 옛 갈래일 수 있음(재구축·검토 필요)"}
        self.sb["ring"] = [r for r in self.sb.get("ring") or [] if anc is not None and r[0] <= anc]
        for wid, w in self.sb["wallets"].items():
            for a in w.get("addrs", {}).values():
                if a.get("h") is not None and (anc is None or a["h"] > anc):
                    a["h"] = anc
                    a["up"] = max(1, int(a.get("up") or 0))
                if a.get("lt") is not None and (anc is None or a["lt"] > anc):
                    a["lt"] = anc
                    a["up"] = max(1, int(a.get("up") or 0))
            w["sweep"] = None
            w["swept"] = -1
            if w.get("own_F") is not None:
                w["own_F"] = None if anc is None else min(int(w["own_F"]), anc)
            self.st.d["gaps"].append({"id": f"reorg:{top}", "ref": {"owner": wid, "lane": "reorg"}, "why": self.sb["hold"]["why"][:160],
                                      "tries": 0, "at": now})
        self._warn("[btc] ★깊은 재편 감지 — 공통 조상 %s · 영향 최고 %s · 보류(대사 준비 안 함)★", anc, top)

    def _ack_hold(self):
        h = self.sb.get("hold")
        if h and self.set["reorg_ack"] is not None and h.get("from_height") is not None and self.set["reorg_ack"] >= h["from_height"]:
            self._say("[btc] 깊은 재편 보류 해제(설정 reorg_ack)")
            self.sb["hold"] = None
            self.st.d["gaps"] = [g for g in self.st.d["gaps"] if not str(g.get("id", "")).startswith("reorg:")]

    def owned_through(self, owners):
        vals = []
        for wid in owners:
            w9 = (self.sb.get("wallets") or {}).get(wid) or {}
            if w9.get("own_F") is None:
                return None
            vals.append(int(w9["own_F"]))
        return min(vals) if vals else None

    def _spend(self, n=1):
        if self.calls_left < n:
            raise _Budget()
        self.calls_left -= n

    def canonical_txid(self, text):
        return _txid(str(text or "").strip())

    def discovery_query(self, owner, lane):
        return {"lane": lane, "owner": owner}, self._fp(owner, lane)

    def discover_page(self, owner, query, cursor):
        if self.st is None:
            raise RuntimeError("btc 어댑터에 상태가 묶이지 않음(bind)")
        if self.tipc is None and not self.stopped:
            self.begin_cycle()
        if self.stopped or self.tipc is None:
            return [], None
        self.calls_left = self.set["calls_per_page"]
        w = self._w(owner)
        frm = window_start(self.cfg)
        if w.get("from_ts") is None:
            w["from_ts"] = frm
        elif frm < int(w["from_ts"]) - TIME_SLACK:
            w["from_ts"] = frm
            for a in w["addrs"].values():
                if a.get("u"):
                    a["h"] = None
            w["hist_done"] = False
            w["pass"] = {"phase": "scan", "bi": 0, "i": 0, "q": [], "c": None}
            w["sweep"] = None
        items = []
        more = False
        try:
            if query["lane"] == "history":
                more = self._history(owner, w, items)
            else:
                more = self._latest(owner, w, items)
        except _Budget:
            more = True
        except chain_watch.Transient as e:
            self.soft_errors += 1
            self.stopped = True
            self._warn("[btc] %s 발견 일시 실패(여기까지 저장 · 다음 주기): %s", owner[:10], logs.safe_err(e)[:120])
            more = False
        if self.es.switched:
            self.stopped = True
            self.soft_errors += 1
        return items, ("more" if more and not self.stopped else None)

    def _stats(self, addr):
        self._spend()
        return self.es.addr_stats(addr)

    def _history(self, wid, w, items) -> bool:
        if w.get("hist_done"):
            return False
        F = self.tipc[2]
        ps = w["pass"]
        brs = self._wcfg(wid)["branches"]
        if ps["phase"] == "scan":
            ps["F0"] = min(int(ps.get("F0", F)), F)
        while ps["phase"] == "scan":
            if ps["bi"] >= len(brs):
                ps["phase"] = "list"
                F0 = int(ps["F0"])
                ps["q"] = [a for a, _x in sorted(((a, x) for a, x in w["addrs"].items() if x.get("h") is None), key=_addr_order)]
                for a9 in ps["q"]:
                    w["addrs"][a9]["lh"] = F0
                w["own_F"] = F0
                w["swept"] = max(int(w.get("swept", -1)), F0)
                break
            b = brs[ps["bi"]]
            i = int(ps["i"])
            if i > self._end(wid, w, b):
                ps["bi"] += 1
                ps["i"] = 0
                continue
            s, addr = self._derive(wid, b, i)
            tc, _bal, mem = self._stats(addr)
            a = w["addrs"].get(addr)
            if a is None:
                a = w["addrs"][addr] = {"b": b, "i": i, "s": s, "h": None if tc else F, "tc": None if tc else 0, "up": 0, "u": 0}
            a["n"] = tc
            if tc or mem:
                a["u"] = 1
                if b in w["br"]:
                    w["br"][b]["used"] = max(int(w["br"][b].get("used", -1)), i)
            if tc and a.get("h") is None:
                a["tc"] = None
            ps["i"] = i + 1
            self._own = None
        while ps["phase"] == "list":
            if not ps["q"]:
                ps["phase"] = "done"
                w["hist_done"] = True
                done_F = int(w.get("own_F") if w.get("own_F") is not None else ps.get("F0", F))
                self.st.set_status(wid, requested_from=w.get("from_ts") or 0, available_from=w.get("from_ts") or 0,
                                   scanned_through=done_F, details_complete_through=done_F)
                self._say("[btc] %s 과거 훑기 끝 — 주소 %d개(사용 %d)", wid[:10], len(w["addrs"]),
                          sum(1 for a in w["addrs"].values() if a.get("u")))
                return False
            addr = ps["q"][0]
            a = w["addrs"].get(addr)
            if a is None:
                ps["q"].pop(0)
                continue
            c = ps.get("c")
            if c is None or c.get("a") != addr:
                n9 = self._stats(addr)[0]
                lh = a.get("lh")
                c = ps["c"] = {"a": addr, "ls": None, "hm": F if lh is None else min(F, int(lh)), "up": 0, "full": True, "tc": None,
                               "n": n9, "seen": 0}
            done = self._page(addr, a, c, F, int(w.get("from_ts") or 0), items, wid)
            if done:
                lt, lh = a.pop("lt", None), a.pop("lh", None)
                if lt is not None and lh is not None and int(c["hm"]) >= int(lh):
                    a["h"] = max(int(c["hm"]), int(lt))
                else:
                    a["h"], a["tc"], a["up"] = c["hm"], None, c["up"]
                ps["q"].pop(0)
                ps["c"] = None
        return False

    def _page(self, addr, a, c, F, from_ts, items, wid) -> bool:
        if self._own is None:
            self._own = self.ownership()
        if self._own.get(a.get("s"), (wid,))[0] != wid:
            c["hm"] = min(int(c.get("hm", F)), F)
            return True
        self._spend()
        first = c.get("ls") is None
        n9 = c.get("n", a.get("n"))
        need = isinstance(n9, int) and n9 > 0 and (first or (c.get("full") and "seen" in c and int(c["seen"]) < n9))
        txs = self.es.addr_chain_txs(addr, c.get("ls"), need)
        if "seen" in c:
            c["seen"] = int(c["seen"]) + len(txs)
        hm = min(int(c.get("hm", F)), F)
        stop_h = None if c.get("full") else c.get("stop", a.get("h"))
        done = not txs
        for t in txs:
            st = t["status"]
            hgt, bt = st["block_height"], st["block_time"]
            if stop_h is not None and hgt <= stop_h:
                done = True
                break
            if stop_h is None and from_ts and bt < from_ts - TIME_SLACK:
                done = True
                break
            if hgt > hm:
                c["up"] = int(c.get("up") or 0) + 1
                continue
            if bt < from_ts:
                continue
            items.append({"stable_id": t["txid"].lower(), "h": hgt})
        if txs:
            c["ls"] = txs[-1]["txid"].lower()
        c["hm"] = hm
        return done

    def _latest(self, wid, w, items) -> bool:
        if not w.get("hist_done") and (w.get("pass") or {}).get("phase") == "scan":
            return False
        F = self.tipc[2]
        sw = w.get("sweep")
        if sw is None:
            if F <= int(w.get("swept", -1)):
                return False
            sw = w["sweep"] = {"F": F, "last": None, "c": None}
        F = sw["F"] = min(F, int(sw["F"]))
        brs = self._wcfg(wid)["branches"]
        ends, order, k = None, [], 0
        while True:
            e9 = {b: self._end(wid, w, b) for b in brs}
            if e9 != ends:
                ends = e9
                for b in brs:
                    for i in range(0, ends[b] + 1):
                        s, addr = self._derive(wid, b, i)
                        if addr not in w["addrs"]:
                            w["addrs"][addr] = {"b": b, "i": i, "s": s, "h": None, "tc": None, "up": 0, "u": 0, "new": 1}
                            self._own = None
                order = sorted(((a, x) for a, x in w["addrs"].items()
                                if sw["last"] is None or _addr_order((a, x)) > tuple(sw["last"])), key=_addr_order)
                k = 0
            if k >= len(order):
                break
            addr, a = order[k]
            if sw["last"] is not None and _addr_order((addr, a)) <= tuple(sw["last"]):
                k += 1
                continue
            c = sw.get("c")
            if c is None or c.get("a") != addr:
                tc, _bal, mem = self._stats(addr)
                a["n"] = tc
                if tc or mem:
                    a["u"] = 1
                    if a["b"] in w["br"]:
                        w["br"][a["b"]]["used"] = max(int(w["br"][a["b"]].get("used", -1)), int(a["i"]))
                fresh = bool(a.pop("new", 0))
                if fresh and not tc:
                    a["h"], a["tc"], a["up"] = F, 0, 0
                    sw["last"] = list(_addr_order((addr, a)))
                    k += 1
                    continue
                base = a["h"] if a.get("h") is not None else (a.get("lt") if a.get("lt") is not None else a.get("lh"))
                if base is not None and tc == a.get("tc") and not int(a.get("up") or 0):
                    if a.get("h") is not None:
                        a["h"] = max(int(a["h"]), F)
                    else:
                        a["lt"] = max(int(base), F)
                    sw["last"] = list(_addr_order((addr, a)))
                    k += 1
                    continue
                c = sw["c"] = {"a": addr, "ls": None, "hm": F, "up": 0, "full": base is None, "tc": tc, "stop": base, "n": tc, "seen": 0}
            done = self._page(addr, a, c, F, int(w.get("from_ts") or 0), items, wid)
            if done:
                if a.get("h") is None and c.get("stop") is not None:
                    a["lt"] = c["hm"]
                else:
                    a["h"] = c["hm"]
                a["tc"], a["up"] = c["tc"], c["up"]
                sw["c"] = None
                sw["last"] = list(_addr_order((addr, a)))
                k += 1
        w["sweep"] = None
        w["swept"] = int(sw["F"])
        w["own_F"] = int(sw["F"])
        if w.get("hist_done"):
            self.st.set_status(wid, scanned_through=int(sw["F"]), details_complete_through=int(sw["F"]))
        return False

    def _prevout(self, txid, vout):
        k = (txid, vout)
        if k not in self._prevouts:
            t = self.es.tx(txid)
            outs = t["vout"]
            if not isinstance(vout, int) or isinstance(vout, bool) or not 0 <= vout < len(outs) or not isinstance(outs[vout], dict):
                raise _bad("prevout 번호")
            o = outs[vout]
            if len(self._prevouts) >= PREVOUT_CACHE:
                self._prevouts.pop(next(iter(self._prevouts)))
            self._prevouts[k] = {"scriptpubkey": _spk(o.get("scriptpubkey"), "prevout scriptpubkey"),
                                 "scriptpubkey_address": o.get("scriptpubkey_address"), "value": _int(o.get("value"), "prevout value", 0, SAT_MAX)}
        return self._prevouts[k]

    def fetch_and_normalize(self, ref, owners):
        if self.tipc is None:
            if self.stopped:
                raise chain_watch.Transient("tip 모름(이번 주기 멈춤)")
            self.begin_cycle()
            if self.tipc is None:
                raise chain_watch.Transient("tip 모름")
        txid = self.canonical_txid(ref.get("stable_id"))
        with self.es.scope("tx:" + _sk(txid)):
            return self._normalize(txid, owners)

    def _normalize(self, txid, owners):
        t = self.es.tx(txid)
        st = t["status"]
        if st.get("confirmed") is not True:
            return None
        hgt = _int(st.get("block_height"), "block_height")
        bt = _int(st.get("block_time"), "block_time", 1)
        bh = _txid(st.get("block_hash"), "block_hash")
        conf = self.tipc[0] - hgt + 1
        if conf < self.min_conf:
            return None
        if self._own is None:
            self._own = self.ownership()
        own = {s: v for s, v in self._own.items() if v[0] in owners}
        ins, outs, ext_in_addrs = {}, {}, []
        tot_in = tot_out = 0
        ext_in = 0
        coinbase = False
        for v in t["vin"]:
            if not isinstance(v, dict):
                raise _bad("vin")
            if v.get("is_coinbase") is True:
                coinbase = True
                continue
            po = v.get("prevout")
            if not isinstance(po, dict) or po.get("value") is None or not isinstance(po.get("scriptpubkey"), str):
                po = self._prevout(_txid(v.get("txid"), "vin txid"), v.get("vout"))
            val = _int(po.get("value"), "prevout value", 0, SAT_MAX)
            spk = _spk(po.get("scriptpubkey"), "prevout scriptpubkey")
            tot_in += val
            w9 = own.get(spk)
            if w9:
                ins[w9[0]] = ins.get(w9[0], 0) + val
            else:
                ext_in += val
                if po.get("scriptpubkey_address") and po["scriptpubkey_address"] not in ext_in_addrs:
                    ext_in_addrs.append(po["scriptpubkey_address"])
        ext_outs = []
        my_outs = []
        for o in t["vout"]:
            if not isinstance(o, dict):
                raise _bad("vout")
            val = _int(o.get("value"), "vout value", 0, SAT_MAX)
            spk = _spk(o.get("scriptpubkey"), "vout scriptpubkey")
            tot_out += val
            w9 = own.get(spk)
            if w9:
                outs[w9[0]] = outs.get(w9[0], 0) + val
                my_outs.append((w9[0], val))
            elif val > 0:
                ext_outs.append((o.get("scriptpubkey_address") or "", val))
        fee = 0 if coinbase else tot_in - tot_out
        if fee < 0:
            raise _bad("입력 합 < 출력 합")
        if not coinbase and t.get("fee") is not None and _int(t.get("fee"), "fee") != fee:
            raise _bad("fee 불일치")
        involved = sorted(set(ins) | set(outs))
        reasons = []
        hint = "program_in" if coinbase else "transfer"
        fees = []
        my_in = sum(ins.values())
        if my_in and fee > 0:
            if ext_in:
                hint = "unknown"
                reasons.append("fee_attribution_unknown")
            elif len(ins) == 1:
                fees.append((next(iter(ins)), fee))
            else:
                reasons.append("fee_split_proportional")
                order = sorted(ins, key=lambda x: (-ins[x], x))
                parts = {x: fee * ins[x] // my_in for x in order}
                parts[order[0]] += fee - sum(parts.values())
                fees += [(x, parts[x]) for x in order if parts[x]]
        if coinbase:
            reasons.append("coinbase")
        if not involved:
            raise _NotMine("내 스크립트가 tx 에 안 보임 — 소유 지도 미완(다시 예약)")
        net = {x: outs.get(x, 0) - ins.get(x, 0) for x in involved}
        moves = []
        payer = fees[0][0] if len(fees) == 1 else (max(ins, key=lambda x: (ins[x], x)) if ins else None)
        for k, (addr, val) in enumerate(ext_outs):
            if payer and addr:
                moves.append({"id": f"o{k}", "asset": {"kind": "native"}, "from": payer, "to": addr, "amount_base": str(val)})
        if ext_in_addrs:
            for k, (w9, val) in enumerate(my_outs):
                moves.append({"id": f"i{k}", "asset": {"kind": "native"}, "from": ext_in_addrs[0], "to": w9, "amount_base": str(val)})
        rec = {"v": 1, "kind": chain_event.KIND, "chain": CHAIN, "network": "mainnet", "tx_uid": txid, "txhash": txid, "ts": bt,
               "order": {"height": hgt, "checkpoint": None, "lt": None, "index": 0},
               "finality": {"state": "finalized", "blockhash": bh, "evidence": f"confirmations:{conf}"},
               "execution": {"state": "success", "trace_complete": True},
               "owners": involved, "ownership_version": reg.ownership_version(self.cfg, CHAIN),
               "deltas": [{"owner": x, "asset": {"kind": "native", "symbol": "BTC", "decimals": 8}, "delta_base": str(net[x])}
                          for x in involved if net[x]],
               "fees": [{"payer": p, "asset": {"kind": "native"}, "amount_base": str(a), "component": "network_fee", "included_in_deltas": True}
                        for p, a in fees],
               "movements": moves,
               "classification": {"hint": hint, "trusted": False, "evidence": ",".join(reasons) or "utxo"},
               "completeness": {"history": True, "details": True, "balances": True, "reasons": reasons},
               "source": {"provider": "esplora:" + self.es.host, "parser_version": PARSER_VERSION, "observed_at": int(time.time()),
                          "payload_digest": chain_event.payload_digest(t)}}
        return rec

    def fetch_balances(self, owners, boundary, tokens=None, latest=False):
        st = chain_state.ChainState(CHAIN)
        sb = st.d.get("btc") if isinstance(st.d.get("btc"), dict) else None
        if not sb or sb.get("v") != STATE_VERSION:
            raise RuntimeError("[btc] 수집 상태 없음 — 대사 보류")
        if sb.get("hold"):
            raise RuntimeError("[btc] 깊은 재편 보류 중 — 대사 보류")
        self.es.pick((sb.get("provider") or {}).get("host"))
        owners = set(owners)
        cap = []
        for wid in owners:
            w9 = (sb.get("wallets") or {}).get(wid) or {}
            if latest:
                continue
            if not w9.get("hist_done") or w9.get("own_F") is None:
                raise RuntimeError("[btc] 지갑 과거 훑기·소유 범위 확인 미완 — 대사 보류")
            cap.append(int(w9["own_F"]))
        self.st = st
        own = self.ownership(None if latest else sorted(set(sb["wallets"]) & set(self.rows)))
        for wid in owners:
            aw = (sb["wallets"].get(wid) or {}).get("addrs") or {}
            for addr, _spk9 in self.owned_addrs(wid, own):
                a9 = aw.get(addr)
                h9 = None if a9 is None else (a9.get("h") if a9.get("h") is not None else None)
                if latest:
                    continue
                if h9 is None:
                    raise RuntimeError("[btc] 아직 이력을 다 본 적 없는 소유 주소(훑기 진행 중) — 대사 보류")
                cap.append(int(h9))
        for _try in range(2):
            tip = self.es.blocks()[0]
            F = min([tip[0] - self.min_conf + 1] + cap)
            blk = self.es.blocks(F)[0]
            if blk[0] != F:
                raise RuntimeError("[btc] 확정 블록 높이가 맞지 않음")
            per = {}
            for wid in sorted(owners):
                tot = 0
                for addr, spk in self.owned_addrs(wid, own):
                    tc, bal, _mem = self.es.addr_stats(addr)
                    if tc:
                        bal -= self._above(addr, spk, F, tc)
                    if bal < 0:
                        raise RuntimeError("[btc] 주소 잔고 계산이 음수 — 응답 불일치")
                    tot += bal
                per[wid] = {("native", None): tot}
            if self.es.blocks()[0][1] == tip[1]:
                return {"per_wallet": per, "_meta": {}, "_boundary": {"kind": "height", "value": F, "hash": blk[1], "ts": blk[2]},
                        "_complete": True, "_unobserved": {}, "_source": "esplora:" + self.es.host,
                        "_ownership_version": reg.ownership_version(self.cfg, CHAIN)}
        raise RuntimeError("[btc] 잔고를 읽는 동안 새 블록이 두 번 들어옴 — 다음 주기")

    def _above(self, addr, spk, F, n=None) -> int:
        d = 0
        ls = None
        while True:
            txs = self.es.addr_chain_txs(addr, ls, ls is None and bool(n))
            if not txs:
                return d
            for t in txs:
                if t["status"]["block_height"] <= F:
                    return d
                if not isinstance(t.get("vout"), list) or not isinstance(t.get("vin"), list):
                    raise _bad("잔고 계산 tx vin/vout")
                for o in t["vout"]:
                    if not isinstance(o, dict):
                        raise _bad("잔고 계산 vout")
                    val = _int(o.get("value"), "vout value", 0, SAT_MAX)
                    if _spk(o.get("scriptpubkey"), "vout scriptpubkey") == spk:
                        d += val
                for v in t["vin"]:
                    if not isinstance(v, dict):
                        raise _bad("잔고 계산 vin")
                    if v.get("is_coinbase") is True:
                        continue
                    po = v.get("prevout")
                    if not isinstance(po, dict):
                        raise RuntimeError("[btc] prevout 없는 입력 — 잔고 계산 보류")
                    val = _int(po.get("value"), "prevout value", 0, SAT_MAX)
                    if _spk(po.get("scriptpubkey"), "prevout scriptpubkey") == spk:
                        d -= val
            ls = txs[-1]["txid"]


def make_adapter(cfg):
    return BtcAdapter(cfg)


def status_view(state: chain_state.ChainState = None) -> dict:
    st = state or chain_state.ChainState(CHAIN)
    sb = st.d.get("btc") if isinstance(st.d.get("btc"), dict) else {}
    out = {"hold": sb.get("hold"), "provider": sb.get("provider"), "wallets": {}}
    for wid, w in (sb.get("wallets") or {}).items():
        out["wallets"][wid] = {"mode": w.get("mode"), "addresses": len(w.get("addrs") or {}),
                               "used": sum(1 for a in (w.get("addrs") or {}).values() if a.get("u")),
                               "hist_done": bool(w.get("hist_done")), "phase": (w.get("pass") or {}).get("phase"),
                               "notes": list(w.get("notes") or [])}
    return out


class BtcCollector(chain_watch.Collector):

    def cycle(self) -> dict:
        self.ad.begin_cycle()
        return super().cycle()

    def details(self, lane: str = None) -> int:
        lim = self.ad.owned_through(self.owners)
        due0 = self.st.due

        def due(now=None, limit=50, lane=None):
            rows = due0(now, 1 << 30, lane)
            rows = [r for r in rows if lim is not None and isinstance((r[1].get("ref") or {}).get("h"), int)
                    and r[1]["ref"]["h"] <= lim][:max(0, int(limit))]
            for r in rows:
                if self.ad.tipc is None:
                    return
                yield r
        self.st.due = due
        try:
            return super().details(lane)
        finally:
            del self.st.due

    def discover(self, lane: str) -> int:
        n = super().discover(lane)
        self.errors += self.ad.soft_errors + (1 if self.ad.sb.get("hold") else 0)
        self.ad.soft_errors = 0
        return n


def main(poll_default: int = 60):
    from inbox import SegmentWriter
    log = logs.setup_logging("tj-btc")
    paths.ensure_dirs()
    cfg = config.load_config()
    owners = reg.owners(cfg, CHAIN)
    if not owners:
        raise SystemExit("추적할 Bitcoin 지갑이 없음 — config chain_wallets 확인")
    sp = reg.spec(CHAIN)
    st = chain_state.ChainState(CHAIN)
    st.drop_owner(owners)
    ad = make_adapter(cfg).bind(st, log)
    ad.prune_wallets(owners)
    st.save()
    col = BtcCollector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, sp.stream)), st, owners, log=log)
    s9 = ((cfg.get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) or {}) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else {}
    poll = s9.get("poll_sec", poll_default) if isinstance(s9, dict) else poll_default
    poll = int(poll) if isinstance(poll, int) and not isinstance(poll, bool) and 10 <= poll <= 3600 else poll_default
    log.info("가동: %s %d지갑, %d초 주기, 확정 깊이 %d", sp.name, len(owners), poll, ad.min_conf)
    try:
        while True:
            t0 = time.time()
            try:
                r = col.cycle()
                log.info("[btc] 주기: %s · 콜 %d", r, ad.es.calls)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("[btc] 주기 실패(다음 주기): %s", logs.safe_err(e)[:200])
            time.sleep(max(5.0, poll - (time.time() - t0)))
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
