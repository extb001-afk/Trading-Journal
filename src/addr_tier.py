from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import zlib

import common

log = logging.getLogger("tj-tier")

DEFAULT_STEPS = [[7, "x1"], [30, "x5"], [90, 3600], [180, 21600], [None, 86400]]
DEFAULTS = {
    "enabled": True,
    "steps": DEFAULT_STEPS,
    "backstop_sec": 21600,
    "t0_backstop_sec": 600,
    "probe_max_per_cycle": 60,
    "rest_max_per_cycle": 25,
    "code_ttl_sec": 7 * 86400,
    "budget_pct": 80,
    "period_max_sec": 900,
}
TIER_LABELS = ["지금 주기", "조금 느리게", "1시간마다", "6시간마다", "하루 1회"]
WAKE_EST_T0 = 12.0
WAKE_EST_REST = 0.5
STRETCH_MAX = 12.0
REQ_PATH_NAME = "addr_tier_req.json"
FILL_ONLY = frozenset({"extend", "extjob", "intfill", "enrich"})
FILL_PATHS = frozenset({"etherscan", "blockscout"})
FILL_TEXT = {"extend": "옛 기록 채우는 중", "extjob": "옛 기록 채우는 중", "intfill": "내부 이동 늦게 채우는 중", "enrich": "자세한 내역 보강 중"}
EMPTY_ACT_SEC = 86400
EMPTY_BACKSTOP_SEC = 7 * 86400
PERIOD_HEAD_SHARE = 0.8

PATH_SAFE = {
    "etherscan": (True, "이더스캔 거래 목록(txlist·tokentx·txlistinternal)이 커서부터 지금까지 통째로 — 과거 노드 상태 불필요"),
    "blockscout": (True, "블록스카웃 v2 주소 목록(transactions·token-transfers·internal-transactions)이 커서부터 통째로 — 과거 노드 상태 불필요"),
    "helius": (True, "getSignaturesForAddress 가 커서(마지막 서명)부터 통째로 — 헬리우스 전 이력 보관"),
    "solrpc": (False, "헬리우스 키 없는 공개 솔라나 RPC — 오래된 서명 보관·한도가 노드마다 달라 복구 보장 못 함 → 지금 주기 유지"),
    "rpc": (False, "RPC 전용 체인 — 로그 없는 네이티브 입금을 과거 nonce·잔고 이분 탐색으로 찾는다(비아카이브 노드 보관 범위 밖이면 영구 미수집) → 지금 주기 유지"),
    "bsc_rpc": (False, "BSC 공개 RPC 수집기 — 한 번의 getLogs 로 전 지갑을 같이 훑어 주소를 쉬게 해도 호출이 줄지 않고, 로그 없는 발신은 과거 nonce 이분 탐색 → 지금 주기 유지"),
}


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    raw = (cfg or {}).get("addr_tier")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in out and v is not None:
                out[k] = v
    out["steps"] = parse_steps(out.get("steps"))
    for k, lo, hi in (("backstop_sec", 600, 7 * 86400), ("t0_backstop_sec", 60, 86400), ("probe_max_per_cycle", 0, 2000), ("rest_max_per_cycle", 1, 5000),
                      ("code_ttl_sec", 3600, 90 * 86400), ("budget_pct", 1, 100), ("period_max_sec", 60, 3600)):
        try:
            out[k] = min(max(int(float(out[k])), lo), hi)
        except (TypeError, ValueError, OverflowError):
            out[k] = DEFAULTS[k]
    out["enabled"] = out.get("enabled") is not False
    return out


_STEPS_FALLBACK = [(7 * 86400, ("x", 1.0)), (30 * 86400, ("x", 5.0)), (90 * 86400, ("s", 3600.0)),
                   (180 * 86400, ("s", 21600.0)), (None, ("s", 86400.0))]


def parse_steps(v) -> list:
    try:
        rows = []
        for lim, iv in v:
            lim9 = None if lim is None else float(lim) * 86400
            if isinstance(iv, str) and iv.startswith("x"):
                m = float(iv[1:])
                if not (1 <= m <= 1000):
                    raise ValueError
                ivv = ("x", m)
            else:
                s = float(iv)
                if not (1 <= s <= 7 * 86400):
                    raise ValueError
                ivv = ("s", s)
            rows.append((lim9, ivv))
        if len(rows) < 2 or rows[-1][0] is not None or any(r[0] is None for r in rows[:-1]) or rows[0][1] != ("x", 1.0):
            raise ValueError
        lims = [r[0] for r in rows[:-1]]
        if lims != sorted(lims) or any(x <= 0 for x in lims):
            raise ValueError
        return rows
    except (TypeError, ValueError, OverflowError):
        return list(_STEPS_FALLBACK)


def tier_for_idle(steps: list, idle_sec: float) -> int:
    for i, (lim, _iv) in enumerate(steps):
        if lim is None or idle_sec <= lim:
            return i
    return len(steps) - 1


def interval_of(steps: list, tier: int, base_poll: float) -> float:
    kind, v = steps[min(max(tier, 0), len(steps) - 1)][1]
    return float(base_poll) * v if kind == "x" else float(v)


def recon_on(cfg: dict) -> bool:
    try:
        return not cfg.get("backfill_full_history") and float(cfg.get("backfill_months") or 0) > 0
    except (TypeError, ValueError):
        return True


def recon_done_sets(scope: str, db_path: str = None) -> tuple:
    db_path = db_path or common.DB_PATH
    init, added = set(), set()
    if not os.path.exists(db_path):
        return init, added, False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        try:
            done = conn.execute("SELECT v FROM meta WHERE k=?", (f"recon_done_{scope}",)).fetchone()
            if done and done[0]:
                row = conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{scope}",)).fetchone()
                d = json.loads(row[0]) if row and row[0] else {}
                if isinstance(d, dict):
                    init = {str(k).lower() for k, v in d.items() if isinstance(v, dict)}
            pre = f"wrecon_done:{scope}:"
            for k, v in conn.execute("SELECT k, v FROM meta WHERE k >= ? AND k < ?", (pre, pre + "\uffff")):
                if v and str(k).startswith(pre):
                    added.add(str(k)[len(pre):])
        finally:
            conn.close()
    except (sqlite3.Error, OSError, TypeError, ValueError) as e:
        log.debug("기초잔고 대사 표식 읽기 실패(%s — 대사 전으로 봄): %s", scope, e)
        return set(), set(), False
    return init, added, True


def req_path() -> str:
    return os.path.join(common.STATE_DIR, REQ_PATH_NAME)


def state_path(scope: str) -> str:
    return os.path.join(common.STATE_DIR, f"addr_tier_{scope}.json")


def code_kind(code) -> str | None:
    if not isinstance(code, str) or not code.startswith("0x"):
        return None
    body = code[2:]
    if not body:
        return "eoa"
    return "7702" if body.lower().startswith("ef0100") else "contract"


def _jitter(key: str) -> float:
    return (zlib.crc32(key.encode()) % 1000) / 1000.0 * 0.15


class TierBook:

    def __init__(self, scope: str, cfg: dict, base_poll: float, path: str, wallets=(), incomplete=None):
        self.scope = scope
        self.path_kind = path
        self.safe, self.safe_note = PATH_SAFE.get(path, (False, f"알 수 없는 수집 경로({path}) — 지금 주기 유지"))
        self.base_poll = float(base_poll or 60)
        self.st = settings(cfg)
        self.cfg_on = self.st["enabled"]
        self.recon_on = recon_on(cfg)
        self._recon_cache = None
        self.lock = threading.RLock()
        self.file = state_path(scope)
        d = common.read_json(self.file, {})
        d = d if isinstance(d, dict) else {}
        p = d.get("pairs") if isinstance(d.get("pairs"), dict) else {}
        self.pairs = {k: {kk: vv for kk, vv in v.items() if kk not in ("hold", "tier")} for k, v in p.items() if isinstance(v, dict)}
        self.boot = d.get("boot") if isinstance(d.get("boot"), dict) else None
        self.ext_tb = d.get("extTb") if isinstance(d.get("extTb"), dict) else None
        if self.boot and not self.boot.get("at"):
            self.boot = None
        self.stretch = 1.0
        self.period = None
        self.pn_head = False
        self.pn_win = 0.0
        self.pn_audit = 0
        self.gate_t0 = False
        self.stretch_act = False
        self._rest_last = set()
        self.filling = {}
        self.incomplete = incomplete or (lambda w: None)
        self.wallets = list(dict.fromkeys(wallets))
        for w in self.wallets:
            self.pairs.setdefault(w, {})
        self.calls = {"rpc": 0, "since": int(time.time())}
        self._ep_cool, self._ep_fail = {}, {}
        self._dirty = True
        self._req_cache = (None, {})
        self._last_save = 0.0
        self.last_cycle = {}

    def reload_cfg(self, cfg: dict):
        with self.lock:
            self.st = settings(cfg)
            self.cfg_on = self.st["enabled"]
            self.recon_on = recon_on(cfg)
            self._recon_cache = None

    @property
    def active(self) -> bool:
        return bool(self.cfg_on and self.safe and self.boot and self.boot.get("at"))

    def _p(self, w: str) -> dict:
        return self.pairs.setdefault(w, {})

    @property
    def eff_poll(self) -> float:
        return max(self.base_poll, float(self.period or 0))

    @property
    def own_poll(self) -> float:
        return self.base_poll if (self.scope == "sol" and self.pn_head) else self.eff_poll

    def set_boot(self, sent: dict, src: str, err: str = None):
        with self.lock:
            for w, ts in (sent or {}).items():
                if w in self.pairs and isinstance(ts, (int, float)) and ts > 0:
                    p = self._p(w)
                    p["sent"] = max(int(ts), int(p.get("sent") or 0))
            self.boot = {"at": int(time.time()), "src": src, "n": len(sent or {})} if err is None else {"at": None, "err": str(err)[:200]}
            self._dirty = True

    def requests(self) -> dict:
        p = req_path()
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return {}
        if mt != self._req_cache[0]:
            d = common.read_json(p, {})
            r = d.get("reqs") if isinstance(d, dict) and isinstance(d.get("reqs"), dict) else {}
            self._req_cache = (mt, r)
        return self._req_cache[1]

    def _req_ts(self, w: str) -> int:
        r = self.requests()
        out = 0
        for k in (f"{self.scope}:{w}", f"*:{w}", "*"):
            try:
                out = max(out, int(r.get(k) or 0))
            except (TypeError, ValueError):
                continue
        return min(out, int(time.time()) + 60)

    def recon_pending(self, w: str) -> bool:
        if not self.recon_on:
            return False
        now = time.monotonic()
        c = self._recon_cache
        if c is None or now - c[0] >= (30.0 if c[3] else 10.0):
            c = (now,) + recon_done_sets(self.scope)
            self._recon_cache = c
        _t, init, added, ok = c
        if not ok:
            return True
        if self.scope == "sol":
            return w.lower() not in init and w not in added
        return w.lower() not in init and w.lower() not in added

    def idle_sec(self, w: str, now: float):
        p = self.pairs.get(w) or {}
        s = p.get("sent")
        c = p.get("cov")
        ref = (float(s) if isinstance(s, (int, float)) and s > 0 else
               float(c) if isinstance(c, (int, float)) and c > 0 else None)
        if self.scope == "sol":
            sc = p.get("signerCov")
            if isinstance(sc, (int, float)) and sc > 0 and ref is not None:
                ref = max(ref, float(sc))
        return None if ref is None else max(0.0, now - ref)

    def hold_reason(self, w: str, now: float = None):
        if not self.cfg_on:
            return "off"
        if not self.safe:
            return "path"
        if not (self.boot and self.boot.get("at")):
            return "boot"
        try:
            inc = self.incomplete(w)
        except Exception:
            inc = "unknown"
        if inc in FILL_ONLY and self.path_kind in FILL_PATHS:
            self.filling[w] = inc
            inc = None
        else:
            self.filling.pop(w, None)
        if inc:
            return "hist:" + str(inc)
        try:
            rp = self.recon_pending(w)
        except Exception:
            rp = True
        if rp:
            return "hist:recon"
        p = self.pairs.get(w) or {}
        ck = p.get("code")
        if ck != "eoa":
            return "code:" + (ck or "unknown")
        if self._req_ts(w) > int(p.get("full") or 0):
            return "req"
        if self.idle_sec(w, time.time() if now is None else now) is None:
            return "nosent"
        return None

    def tier(self, w: str, now: float = None):
        now = time.time() if now is None else now
        why = self.hold_reason(w, now)
        if why:
            return 0, 0.0, why
        if self.is_empty(w):
            return len(self.st["steps"]) - 1, float(EMPTY_ACT_SEC), None
        t = tier_for_idle(self.st["steps"], self.idle_sec(w, now))
        if t == 0:
            return 0, ((self.base_poll * (max(1.0, self.stretch) if self.stretch_act else 1.0)) if self.gate_t0 else 0.0), None
        return t, interval_of(self.st["steps"], t, self.eff_poll) * max(1.0, self.stretch), None

    def is_empty(self, w: str) -> bool:
        e = (self.pairs.get(w) or {}).get("empty")
        return isinstance(e, dict) and isinstance(e.get("blk"), int) and (self.pairs.get(w) or {}).get("code") == "eoa"

    def mark_empty(self, w: str, blk: int, now: float = None):
        now = time.time() if now is None else now
        with self.lock:
            p = self._p(w)
            p["empty"] = {"blk": int(blk), "at": int(now)}
            p["full"] = int(now)
            p["fullBlk"] = max(int(p.get("fullBlk") or 0), int(blk))
            a = p.get("act")
            if not (isinstance(a, dict) and isinstance(a.get("blk"), int) and a["blk"] >= int(blk)):
                p["act"] = {"n": 0, "b": "0", "blk": int(blk), "at": int(now)}
                p["actAt"] = int(now)
            p.pop("wake", None)
            p.pop("actFail", None)
            self._dirty = True

    def clear_empty(self, w: str, why: str):
        with self.lock:
            p = self.pairs.get(w)
            if isinstance(p, dict) and p.pop("empty", None) is not None:
                p["emptyOff"] = {"at": int(time.time()), "why": str(why)[:40]}
                self._dirty = True
                log.info("%s %s 빈 지갑 해제(%s) — 정상 수집으로", self.scope, w[:10], why)

    def backstop_of(self, iv: float, t: int = 1, w: str = None) -> float:
        f = max(1.0, self.stretch)
        if w is not None and self.is_empty(w):
            return max(float(iv), float(EMPTY_BACKSTOP_SEC))
        if t == 0:
            return float(self.st["t0_backstop_sec"]) * f
        return max(float(iv), float(self.st["backstop_sec"]) * f)

    def anchored(self, p: dict) -> bool:
        a = p.get("act")
        return isinstance(a, dict) and isinstance(a.get("blk"), int) and a["blk"] >= int(p.get("fullBlk") or 0)

    def due_list(self, ws, now: float = None) -> tuple:
        now = time.time() if now is None else now
        due, rest, cand = [], [], []
        with self.lock:
            for w in ws:
                t, iv, why = self.tier(w, now)
                p = self._p(w)
                p["tier"] = t
                if iv <= 0 and self.period_eligible(w, why, now) and self.period_rest(w, p, now):
                    rest.append(w)
                    continue
                if why or iv <= 0:
                    due.append(w)
                    continue
                if not p.get("full") or isinstance(p.get("wake"), dict):
                    due.append(w)
                    continue
                if not self.anchored(p) and not p.get("actFail"):
                    due.append(w)
                    continue
                over = now - float(p["full"]) - self.backstop_of(iv, t, w) * (1.0 - _jitter(f"{self.scope}:{w}"))
                if over >= 0:
                    cand.append((over, w))
                else:
                    rest.append(w)
            cand.sort(key=lambda x: -x[0])
            take = {w for _o, w in cand[: self.st["rest_max_per_cycle"]]}
            for _o, w in cand:
                (due if w in take else rest).append(w)
        order = {w: i for i, w in enumerate(ws)}
        due.sort(key=lambda w: order.get(w, 0))
        rest.sort(key=lambda w: order.get(w, 0))
        self._rest_last = set(rest)
        self.last_cycle = {"at": int(now), "due": len(due), "rest": len(rest), "gate": self.gate_t0, "stretch": self.stretch}
        return due, rest

    def period_eligible(self, w: str, why, now: float) -> bool:
        if not why:
            return True
        if self.scope != "sol" or why != "hist:extend":
            return False
        p = self.pairs.get(w) or {}
        if p.get("code") != "eoa" or self._req_ts(w) > int(p.get("full") or 0) or self.idle_sec(w, now) is None:
            return False
        try:
            return not self.recon_pending(w)
        except Exception:
            return False

    def period_rest(self, w: str, p: dict, now: float) -> bool:
        if not self.active or self.own_poll <= self.base_poll * 1.01 or isinstance(p.get("wake"), dict):
            return False
        last = float(p.get("full") or 0)
        if self.scope == "sol":
            last = max(last, float(p.get("actAt") or 0))
        if last <= 0 or self._req_ts(w) > int(p.get("full") or 0):
            return False
        return now - last < self.own_poll * (1.0 - _jitter(f"p:{self.scope}:{w}"))

    def is_resting(self, w: str) -> bool:
        return w in self._rest_last and self.active

    def activity_targets(self, now: float = None) -> list:
        now = time.time() if now is None else now
        if not self.active:
            return []
        out, t0 = [], []
        for w in self.wallets:
            t, iv, why = self.tier(w, now)
            p = self.pairs.get(w) or {}
            if why or iv <= 0 or isinstance(p.get("wake"), dict) or not self.anchored(p):
                continue
            last = float(p.get("actAt") or (p.get("act") or {}).get("at") or 0)
            if now - last >= iv * (1.0 - _jitter(f"a:{self.scope}:{w}")):
                (t0 if t == 0 else out).append((now - last, w))
        out.sort(key=lambda x: -x[0])
        t0.sort(key=lambda x: -x[0])
        return [w for _a, w in t0] + [w for _a, w in out[: self.st["probe_max_per_cycle"]]]

    def note_activity(self, w: str, nonce: int, bal: int, blk: int):
        with self.lock:
            p = self._p(w)
            a = p.get("act") if isinstance(p.get("act"), dict) else None
            p["actAt"] = int(time.time())
            if a is None:
                return
            if int(nonce) != int(a.get("n", -1)) or str(int(bal)) != str(a.get("b")):
                why = "nonce" if int(nonce) > int(a.get("n", -1)) else "balance"
                p["wake"] = {"at": int(time.time()), "blk": int(blk), "why": why}
                if p.pop("empty", None) is not None:
                    p["emptyOff"] = {"at": int(time.time()), "why": why}
            self._dirty = True

    def wake(self, w: str, blk, why: str):
        with self.lock:
            self._p(w)["wake"] = {"at": int(time.time()), "blk": None if blk is None else int(blk), "why": str(why)}
            self._dirty = True

    def note_baseline(self, w: str, nonce: int, bal: int, blk: int):
        with self.lock:
            p = self._p(w)
            p["act"] = {"n": int(nonce), "b": str(int(bal)), "blk": int(blk), "at": int(time.time())}
            p["actAt"] = int(time.time())
            p.pop("actFail", None)
            self._dirty = True

    def note_baseline_fail(self, w: str):
        with self.lock:
            self._p(w)["actFail"] = int(time.time())
            self._dirty = True

    def need_baseline(self, ws) -> list:
        out = []
        for w in ws:
            p = self.pairs.get(w) or {}
            if p.get("fullBlk") and not self.anchored(p) and self.tier(w)[1] > 0:
                out.append(w)
        return out

    def note_full(self, w: str, blk: int, now: float = None):
        now = time.time() if now is None else now
        with self.lock:
            p = self._p(w)
            p["full"] = int(now)
            p["fullBlk"] = int(blk)
            wk = p.get("wake")
            if isinstance(wk, dict) and (wk.get("blk") is None or int(blk) >= int(wk["blk"])):
                p.pop("wake", None)
            self._dirty = True

    def note_sent(self, w: str, ts):
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            return
        if ts <= 0 or w not in self.pairs:
            return
        with self.lock:
            p = self._p(w)
            if ts > int(p.get("sent") or 0):
                p["sent"] = ts
                self._dirty = True
            if p.pop("empty", None) is not None:
                p["emptyOff"] = {"at": int(time.time()), "why": "sent"}
                self._dirty = True

    def note_cov(self, w: str, ts, blk=None):
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            return
        if ts <= 0:
            return
        with self.lock:
            p = self._p(w)
            if not p.get("cov") or ts < int(p["cov"]):
                p["cov"] = ts
                if blk is not None:
                    p["covBlk"] = int(blk)
                self._dirty = True

    def need_code(self, now: float = None) -> list:
        now = time.time() if now is None else now
        ttl = self.st["code_ttl_sec"]
        return [w for w in self.wallets if now - float((self.pairs.get(w) or {}).get("codeAt") or 0) >= ttl]

    def set_code(self, w: str, kind):
        if kind is None:
            return
        with self.lock:
            p = self._p(w)
            if p.get("code") != kind and kind != "eoa":
                p.pop("act", None)
            p["code"] = kind
            p["codeAt"] = int(time.time())
            self._dirty = True

    def summary(self, now: float = None) -> dict:
        now = time.time() if now is None else now
        n = [0] * len(self.st["steps"])
        holds = {}
        full_day = 0.0
        act_day = 0.0
        for w in self.wallets:
            t, iv, why = self.tier(w, now)
            n[t] += 1
            if why:
                k = why.split(":")[0]
                holds[k] = holds.get(k, 0) + 1
            if iv <= 0:
                full_day += 86400.0 / (self.own_poll if self.period_eligible(w, why, now) else self.base_poll)
            else:
                full_day += 86400.0 / self.backstop_of(iv, t, w) + (WAKE_EST_T0 if t == 0 else WAKE_EST_REST)
                act_day += 86400.0 / max(iv, self.base_poll)
        out = {"scope": self.scope, "path": self.path_kind, "safe": self.safe, "active": self.active, "tiers": n,
               "holds": holds, "fullPerDay": round(full_day, 1), "actPerDay": round(act_day, 1), "stretch": self.stretch,
               "gate": self.gate_t0, "basePoll": self.base_poll, "pairs": len(self.wallets), "lastCycle": self.last_cycle,
               "period": round(self.own_poll), "t0": sum(1 for w in self.wallets if self.tier(w, now)[1] <= 0
                                                       and self.period_eligible(w, self.hold_reason(w, now), now)),
               "filling": sum(1 for w in self.wallets if w in self.filling), "empty": sum(1 for w in self.wallets if self.is_empty(w))}
        if self.path_kind in ("helius", "solrpc"):
            out["solCost"] = sol_cost_day(self, now)["helius"]
            out["actPerDay"] = 0.0
        return out

    def save(self, force: bool = False):
        with self.lock:
            if not (self._dirty or force) and time.time() - self._last_save < 300:
                return
            now = time.time()
            pairs = {}
            for w in self.wallets:
                p = dict(self.pairs.get(w) or {})
                t, iv, why = self.tier(w, now)
                p["tier"], p["hold"] = t, why
                p["iv"] = round(iv) if iv > 0 else None
                p["bs"] = round(self.backstop_of(iv, t, w)) if iv > 0 else None
                if w in self.filling:
                    p["fill"] = self.filling[w]
                else:
                    p.pop("fill", None)
                p["rest"] = w in self._rest_last
                pairs[w] = p
            out = {"v": 1, "scope": self.scope, "path": self.path_kind, "safe": self.safe, "safeNote": self.safe_note,
                   "enabled": self.cfg_on, "boot": self.boot, "extTb": self.ext_tb, "stretch": self.stretch, "gate": self.gate_t0, "basePoll": self.base_poll,
                   "backstopSec": self.st["backstop_sec"],
                   "steps": [[None if lim is None else round(lim / 86400, 3), (f"x{v:g}" if k == "x" else int(v))]
                             for lim, (k, v) in self.st["steps"]],
                   "lastCycle": self.last_cycle, "calls": self.calls, "summary": self.summary(now),
                   "updatedAt": int(now), "pairs": pairs}
            try:
                common.atomic_write_json(self.file, out)
                self._dirty = False
                self._last_save = time.time()
            except OSError as e:
                log.warning("주기 장부 저장 실패(%s): %s", self.scope, e)


BOOKS = {}
ACTIVE_PROC = False
RPC_IMPL = None


def rpc(wt, tb: "TierBook", method: str, params: list):
    tb.calls["rpc"] = tb.calls.get("rpc", 0) + 1
    if RPC_IMPL is not None:
        return RPC_IMPL(wt, method, params)
    import bf_engine
    urls = list(getattr(wt, "cfg_rpcs", None) or (getattr(wt, "RPC_DEFAULT", None) or {}).get(wt.chain) or [])
    now = time.time()
    last = None
    for u in urls:
        if tb._ep_cool.get(u, 0) > now:
            continue
        try:
            r = bf_engine.rpc_call(u, method, params, timeout=15, retries=1, prio="bg")
            tb._ep_fail[u] = 0
            return r
        except Exception as e:
            n = tb._ep_fail.get(u, 0) + 1
            tb._ep_fail[u] = n
            tb._ep_cool[u] = now + min(900.0, 30.0 * (2 ** min(n - 1, 5)))
            last = e
    raise last if last else RuntimeError("활동 점검 RPC 없음")
_BOOKS_LOCK = threading.Lock()


def chain_poll(cfg: dict, chain: str) -> float:
    try:
        v = float(((cfg.get("chains") or {}).get(chain) or {}).get("poll_sec") or cfg.get("evm_poll_sec") or 45)
    except (TypeError, ValueError):
        v = 45.0
    return min(max(v, 5.0), 300.0)


def _ext_tb_of(wt, path: str, target: int):
    tb = getattr(wt, "_tier", None)
    xt = getattr(wt, "_ext_tb", None)
    if isinstance(xt, (tuple, list)) and len(xt) == 2 and xt[0] == target and isinstance(xt[1], int):
        if tb is not None and getattr(tb, "ext_tb", None) != {"path": path, "t": int(target), "b": int(xt[1])}:
            tb.ext_tb = {"path": path, "t": int(target), "b": int(xt[1])}
            tb._dirty = True
        return int(xt[1])
    e = getattr(tb, "ext_tb", None) if tb is not None else None
    if isinstance(e, dict) and e.get("path") == path and e.get("t") == target and isinstance(e.get("b"), int):
        return int(e["b"])
    return None


def _evm_ext_need(wt, path: str, w: str) -> bool:
    import bf_engine
    target = bf_engine.SINCE.target(wt.chain)
    if not target:
        return False
    if path == "blockscout" and str(getattr(wt, "bf_mode", "v2")) == "legacy":
        return False
    tblk = _ext_tb_of(wt, path, target)
    if tblk is None:
        return True
    c = wt.cursor
    cov = c.get("_cov:" + w)
    if not isinstance(cov, int):
        hint = bf_engine.SINCE.covered_hint(wt.chain)
        cur = int(c.get(w) or 0)
        if hint:
            hb = getattr(wt, "_ext_hint" if path == "etherscan" else "_hint_blk", None)
            if not (isinstance(hb, (tuple, list)) and len(hb) == 2 and hb[0] == hint and isinstance(hb[1], int)):
                return True
            cov = min(int(hb[1]), cur)
        else:
            cov = cur
    return cov > tblk + 1


def _evm_incomplete(wt, path: str):
    def inc(w):
        c = wt.cursor
        if not isinstance(c.get(w), int):
            return "cursor"
        if w in getattr(wt, "_tier_fail", ()):
            return "fail"
        if w in getattr(wt, "_tier_partial", ()):
            return "partial"
        if path == "etherscan":
            if ("_bfes:" + w) in c:
                return "backfill"
            if tier_pending(wt, w, enrich=False):
                return "pending"
            if _evm_ext_need(wt, path, w):
                return "extend"
            return None
        if ("_disc:" + w) in c:
            return "checkpoint"
        if tier_pending(wt, w, enrich=False):
            return "pending"
        if (getattr(wt, "fail_streak", None) or {}).get(w):
            return "fail"
        if ("_bf:" + w) in c:
            return "backfill"
        job = c.get("_bfjob")
        if isinstance(job, dict) and w in (job.get("wallets") or []):
            return "extjob" if job.get("kind") == "extend" else "backfill"
        ipm = c.get("_ext_internal_pending")
        if isinstance(ipm, dict) and any(not isinstance(r, dict) or not isinstance(r.get("wallet"), str) or not r.get("wallet")
                                         or str(r.get("wallet")).lower() == w for r in ipm.get("ranges") or []):
            return "intfill"
        if _evm_ext_need(wt, path, w):
            return "extend"
        if tier_pending(wt, w):
            return "enrich"
        return None
    return inc


def evm_book(wt, cfg: dict, path: str) -> TierBook:
    if not ACTIVE_PROC:
        return None
    with _BOOKS_LOCK:
        b = BOOKS.get(wt.chain)
        if b is not None:
            b.save(force=True)
        if b is None or b.path_kind != path:
            b = TierBook(wt.chain, cfg, chain_poll(cfg, wt.chain), path, wt.wallets, incomplete=_evm_incomplete(wt, path))
        else:
            b.reload_cfg(cfg)
            b.base_poll = chain_poll(cfg, wt.chain)
            b.wallets = list(dict.fromkeys(wt.wallets))
            for w in b.wallets:
                b.pairs.setdefault(w, {})
            b.incomplete = _evm_incomplete(wt, path)
        b.lp = bool(path == "etherscan" and _lp_chain(wt.chain))
        BOOKS[wt.chain] = b
    start_boot([b])
    return b


def _lp_chain(chain: str) -> bool:
    try:
        import lpdec
        return bool(lpdec.lp_managers(common.BASE_DIR).get(chain))
    except Exception:
        return False


def idle_cycle(wt, tb: TierBook, kind: str, source: str):
    try:
        ch = False
        for k in ("_synced_at", "_synced_tok_at"):
            if wt.cursor.get(k):
                wt.cursor[k] = int(time.time())
                ch = True
        if ch:
            common.atomic_write_json(wt.cursor_path, wt.cursor)
    except OSError as e:
        log.warning("%s 쉼 주기 도장 갱신 실패: %s", tb.scope, e)
    tb.save()
    head = int(getattr(wt, "_max_head", 0) or 0)
    try:
        wt._health_cycle(kind, head, max(0, head - int(getattr(wt, "conf_depth", 0) or 0)), ok=True, current_source=source,
                         wallets_failing=0, pending_detail=0, tier_idle=True)
    except Exception as e:
        log.debug("%s 쉼 주기 헬스 기록 실패: %s", tb.scope, e)


def evm_activity(wt, tb: TierBook, deadline: float = None) -> int:
    if not (tb.cfg_on and tb.safe):
        return 0
    n = 0
    deadline = deadline or (time.time() + 60)

    def call(m, params):
        nonlocal n
        n += 1
        return rpc(wt, tb, m, params)
    try:
        for w in tb.need_code()[:40]:
            if time.time() > deadline:
                break
            try:
                tb.set_code(w, code_kind(call("eth_getCode", [w, "latest"])))
            except Exception:
                continue
        ts_cache = {}
        for w in tb.wallets:
            p = tb.pairs.get(w) or {}
            if p.get("sent") or p.get("cov") or time.time() > deadline:
                continue
            blk = wt.cursor.get("_cov:" + w)
            if not isinstance(blk, int):
                blk = ((wt.cursor.get("_es_int") or {}).get("floor") or {}).get(w)
            if not isinstance(blk, int) or blk <= 0:
                continue
            try:
                if blk not in ts_cache:
                    b9 = call("eth_getBlockByNumber", [hex(int(blk)), False]) or {}
                    ts_cache[blk] = int(b9["timestamp"], 16)
                tb.note_cov(w, ts_cache[blk], blk)
            except Exception:
                continue
        targets = tb.activity_targets()
        if targets and time.time() < deadline:
            head = int(call("eth_blockNumber", []), 16) - int(getattr(wt, "conf_depth", 0) or 0)
            for w in targets:
                if time.time() > deadline:
                    break
                try:
                    nc = int(call("eth_getTransactionCount", [w, hex(head)]), 16)
                    bl = int(call("eth_getBalance", [w, hex(head)]), 16)
                except Exception:
                    continue
                tb.note_activity(w, nc, bl, head)
    except Exception as e:
        log.debug("%s 활동 점검 중단(다음 주기): %s", tb.scope, e)
    return n


def evm_baselines(wt, tb: TierBook, ws, deadline: float = None) -> int:
    n = 0
    deadline = deadline or (time.time() + 30)
    for w in tb.need_baseline(ws):
        if time.time() > deadline:
            break
        blk = int((tb.pairs.get(w) or {}).get("fullBlk") or 0)
        try:
            n += 2
            nc = int(rpc(wt, tb, "eth_getTransactionCount", [w, hex(blk)]), 16)
            bl = int(rpc(wt, tb, "eth_getBalance", [w, hex(blk)]), 16)
            tb.note_baseline(w, nc, bl, blk)
        except Exception:
            tb.note_baseline_fail(w)
    return n


EMPTY_RECHECK_SEC = 7 * 86400
EMPTY_PROBE_MAX = 10


def empty_candidates(tb: "TierBook", ws, now: float = None) -> list:
    now = time.time() if now is None else now
    out = []
    for w in ws:
        p = tb.pairs.get(w) or {}
        if p.get("code") != "eoa" or tb.is_empty(w) or p.get("sent") or isinstance(p.get("wake"), dict):
            continue
        a = p.get("act")
        if not (isinstance(a, dict) and isinstance(a.get("blk"), int) and str(a.get("n")) == "0" and str(a.get("b")) == "0"):
            continue
        ck = p.get("emptyChk")
        if isinstance(ck, dict) and now - float(ck.get("at") or 0) < EMPTY_RECHECK_SEC:
            continue
        try:
            if tb.hold_reason(w, now):
                continue
        except Exception:
            continue
        out.append(w)
    return out[:EMPTY_PROBE_MAX]


def evm_empty_probe(wt, tb: "TierBook", has_rows, ws=None, now: float = None) -> int:
    now = time.time() if now is None else now
    n = 0
    for w in empty_candidates(tb, wt.wallets if ws is None else ws, now):
        blk = int((tb.pairs.get(w) or {}).get("act", {}).get("blk"))
        try:
            r = has_rows(w, blk)
        except Exception as e:
            log.debug("%s %s 빈 지갑 판정 보류: %s", tb.scope, w[:10], str(e)[:80])
            break
        n += 1
        with tb.lock:
            tb._p(w)["emptyChk"] = {"at": int(now), "blk": blk, "rows": None if r is None else bool(r)}
            tb._dirty = True
        if r is False:
            tb.mark_empty(w, blk, now)
            job = wt.cursor.get("_bfjob") if isinstance(wt.cursor.get("_bfjob"), dict) else None
            if not (job and w in (job.get("wallets") or [])) and isinstance(wt.cursor.get(w), int):
                cv = wt.cursor.get("_cov:" + w)
                if not isinstance(cv, int) or cv > 0:
                    wt.cursor["_cov:" + w] = 0
                    try:
                        common.atomic_write_json(wt.cursor_path, wt.cursor)
                    except OSError as e:
                        log.warning("%s 빈 지갑 커버 하한 기록 실패(다음 주기): %s", tb.scope, e)
            log.info("%s %s 빈 지갑(블록 %d 까지 nonce·잔고 0 · 토큰 기록 0) — 하루 1회만 확인", tb.scope, w[:10], blk)
    return n


def snap_from(snap) -> str:
    try:
        f = (snap or {}).get("tx", {}).get("from")
        if isinstance(f, dict):
            f = f.get("hash")
        return str(f or "").lower()
    except AttributeError:
        return ""


def sent_from(snap) -> str:
    tx = (snap or {}).get("tx") or {}
    if not isinstance(tx, dict) or str(tx.get("raw_input") or "") == "0x01" or "bs_list" in (tx.get("synth"), tx.get("synth_was")):
        return ""
    return snap_from(snap)


TIER_PEND_KEY = "_tier_pend"


def _live_pend(wt, enrich: bool = True) -> list:
    out = []
    for q in (getattr(wt, "pending_detail", None), getattr(wt, "enrich", None) if enrich else None, getattr(wt, "_tier_legacy_pend", None)):
        if q:
            out.extend(str(h).lower() for h in list(q))
    return out


def tier_mark(wt, h: str, wallets):
    if getattr(wt, "_tier", None) is None or not h:
        return
    m = wt.cursor.get(TIER_PEND_KEY)
    if not isinstance(m, dict):
        m = wt.cursor[TIER_PEND_KEY] = {}
    hl = str(h).lower()
    ws = m.get(hl)
    if (not isinstance(ws, list) or not ws) and _is_live(wt, h):
        return
    if not isinstance(ws, list):
        ws = m[hl] = []
    for w in wallets or ():
        w = str(w).lower()
        if w not in ws:
            ws.append(w)


def _is_live(wt, h: str) -> bool:
    hl = str(h).lower()
    for q in (getattr(wt, "pending_detail", None), getattr(wt, "enrich", None), getattr(wt, "_tier_legacy_pend", None)):
        if q and (h in q or hl in q):
            return True
    return False


def tier_mark_if_live(wt, h: str, wallets):
    if getattr(wt, "_tier", None) is None or not h:
        return
    if _is_live(wt, h):
        tier_mark(wt, h, wallets)


def tier_prune(wt):
    m = wt.cursor.get(TIER_PEND_KEY)
    if not isinstance(m, dict):
        if m is not None:
            wt.cursor.pop(TIER_PEND_KEY, None)
        return
    live = set(_live_pend(wt))
    for h in [h for h in m if h not in live or not isinstance(m.get(h), list)]:
        m.pop(h, None)
    if not m:
        wt.cursor.pop(TIER_PEND_KEY, None)


def tier_partial(wt, w: str, on: bool):
    s = getattr(wt, "_tier_partial", None)
    if not isinstance(s, set):
        s = wt._tier_partial = set()
    if on:
        s.add(w)
    else:
        s.discard(w)


def tier_pending(wt, w: str, enrich: bool = True) -> bool:
    live = _live_pend(wt, enrich=enrich)
    if not live:
        return False
    m = (getattr(wt, "cursor", None) or {}).get(TIER_PEND_KEY)
    m = m if isinstance(m, dict) else {}
    w = str(w).lower()
    for h in live:
        ws = m.get(h)
        if not isinstance(ws, list) or not ws or w in ws:
            return True
    return False


def snap_ts(snap) -> int:
    t = ((snap or {}).get("tx") or {}).get("timestamp")
    if isinstance(t, (int, float)):
        return int(t)
    if isinstance(t, str) and t:
        try:
            import datetime as _dt
            return int(_dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
        except ValueError:
            try:
                return int(float(t))
            except ValueError:
                return 0
    return 0


SYSTEM_PROGRAM = "11111111111111111111111111111111"


def _sol_ext_need(c: dict, a: str, target) -> bool:
    if not target:
        return False
    if ("_sigx:" + a) in c:
        return True
    cov = c.get("_cov_ts:" + a)
    return not isinstance(cov, int) or cov > int(target)


def _sol_incomplete(wt):
    def inc(o):
        c = wt.cursor
        if o not in c:
            return "cursor"
        if ("_sigbf:" + o) in c or ("_persp:" + o) in c:
            return "backfill"
        if o in getattr(wt, "_tier_fail", ()):
            return "fail"
        atas = [a for a, o9 in list(getattr(wt, "ata_owner", {}).items()) if o9 == o]
        for a in atas:
            if ("_sigbf:" + a) in c:
                return "backfill"
        import bf_engine
        target = bf_engine.SINCE.target("sol")
        if target and (_sol_ext_need(c, o, target) or any(a in c and _sol_ext_need(c, a, target) for a in atas)):
            return "extend"
        return None
    return inc


def sol_book(wt, cfg: dict) -> TierBook:
    if not ACTIVE_PROC:
        return None
    sol9 = cfg.get("sol") or {}
    import bf_engine
    path = "helius" if bf_engine.is_helius_rpc(sol9) else "solrpc"
    try:
        poll = float(sol9.get("poll_sec", 60))
    except (TypeError, ValueError):
        poll = 60.0
    with _BOOKS_LOCK:
        b = TierBook("sol", cfg, max(5.0, poll), path, wt.owners, incomplete=_sol_incomplete(wt))
        b.stretch_act = True
        try:
            b.ata_every = max(1, int(sol9.get("ata_every_cycles", 5)))
        except (TypeError, ValueError):
            b.ata_every = 5
        BOOKS["sol"] = b
    for o in b.wallets:
        p9 = b._p(o)
        if o in (getattr(wt, "cursor", None) or {}) and not p9.get("signerCov"):
            with b.lock:
                p9["signerCov"] = int(time.time())
                b._dirty = True
        for a in p9.get("atas") or []:
            wt.ata_owner.setdefault(a, o)
    start_boot([b])
    return b


def sol_activity(wt, tb: TierBook, deadline: float = None) -> int:
    if not (tb.cfg_on and tb.safe):
        return 0
    n = 0
    deadline = deadline or (time.time() + 30)
    for o in tb.wallets:
        p = tb.pairs.get(o) or {}
        c9 = wt.cursor.get("_cov_ts:" + o)
        if not p.get("sent") and not p.get("cov") and isinstance(c9, int) and not isinstance(c9, bool) and o in wt.cursor:
            tb.note_cov(o, c9 if c9 > 0 else 1)
    for o in tb.need_code()[:20]:
        if time.time() > deadline:
            break
        try:
            n += 1
            tb.calls["rpc"] = tb.calls.get("rpc", 0) + 1
            r = (RPC_IMPL(wt, "getAccountInfo", [o, {"encoding": "base64"}]) if RPC_IMPL is not None
                 else wt.rpc.call("getAccountInfo", [o, {"encoding": "base64"}]))
            v = (r or {}).get("value") if isinstance(r, dict) else None
            tb.set_code(o, "eoa" if v is None or v.get("owner") == SYSTEM_PROGRAM else "contract")
        except Exception:
            continue
    return n


def sol_cost_day(tb: TierBook, now: float = None, period: float = None) -> dict:
    now = time.time() if now is None else now
    every = getattr(tb, "ata_every", 5)
    enum = 2
    win = float(getattr(tb, "pn_win", 0) or 0) if getattr(tb, "pn_head", False) else 0.0

    def lst(iv):
        return 0.0 if win > 0 and iv <= win else 1.0
    old = tb.period
    if period is not None:
        tb.period = period
    try:
        P = tb.eff_poll
        Po = tb.own_poll
        head = 0.0
        for o in tb.wallets:
            t, iv, why = tb.tier(o, now)
            n_at = len((tb.pairs.get(o) or {}).get("atas") or [])
            if why and not tb.period_eligible(o, why, now):
                bp = tb.base_poll
                head += 86400.0 / bp * lst(bp) + 86400.0 / (bp * every) * (n_at * lst(bp * every) + enum)
            elif iv <= 0:
                head += 86400.0 / Po * lst(Po) + 86400.0 / (P * every) * (n_at * lst(P * every) + enum)
            else:
                bs = tb.backstop_of(iv, t, o)
                head += 86400.0 / max(iv, P) * lst(max(iv, P)) + (86400.0 / bs + WAKE_EST_REST) * (n_at * lst(bs) + enum)
        nst = int(getattr(tb, "stake_n", 0) or 0)
        head += 86400.0 / (P * every) * nst * lst(P * every)
        if win > 0:
            head += 86400.0 / (P * every) * (int(getattr(tb, "pn_audit", 0) or 0) + 1)
        se9 = max(60.0, float(getattr(tb, "stake_every", 3600) or 3600))
        fixed = SOL_FIXED_DAY + (86400.0 / se9 * 10.0 * len(tb.wallets) if (nst or getattr(tb, "stake_on", False)) else 0.0)
    finally:
        tb.period = old
    return {"helius": round(head + fixed), "head": round(head), "fixed": round(fixed)}


SOL_FIXED_DAY = 600.0


def fit_period(cost_at, base_poll: float, cap: float, pmax: float, step: float = 15.0) -> tuple:
    lo = float(base_poll)
    c = cost_at(lo)
    if c <= cap or cap <= 0:
        return lo, c, c <= cap
    c_hi = cost_at(pmax)
    if c_hi > cap:
        return float(pmax), c_hi, False
    hi = float(pmax)
    for _ in range(30):
        mid = (lo + hi) / 2.0
        if cost_at(mid) <= cap:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1.0:
            break
    P = min(float(pmax), -(-hi // step) * step)
    return P, cost_at(P), True


def plan_period_sol(tb: TierBook, cfg: dict, now: float = None) -> dict:
    import bf_engine
    now = time.time() if now is None else now
    if not (tb.active and tb.path_kind == "helius"):
        tb.period, tb.stretch = None, 1.0
        return {"period": tb.base_poll, "fits": True}
    cap = bf_engine.helius_day_budget(cfg) * PERIOD_HEAD_SHARE - sol_cost_day(tb, now)["fixed"]
    tb.stretch = 1.0
    P, c, ok = fit_period(lambda x: sol_cost_day(tb, now, period=x)["head"], tb.base_poll, cap, tb.st["period_max_sec"])
    tb.period = P if P > tb.base_poll else None
    f = 1.0
    while not ok and f < STRETCH_MAX:
        f = min(STRETCH_MAX, f * 1.5)
        tb.stretch = f
        c = sol_cost_day(tb, now)["head"]
        ok = c <= cap
    if P > tb.base_poll or f > 1:
        log.info("솔라나 기본 주기: 지갑 %d개 · 지금 주기 %d개라 %d초마다 확인(헬리우스 하루 예산 %d 중 새 거래 확인 %d 추정)%s%s", len(tb.wallets),
                 sum(1 for o in tb.wallets if tb.tier(o, now)[1] <= 0), int(tb.eff_poll), bf_engine.helius_day_budget(cfg), c,
                 f" · 쉬는 간격 ×{f:.2f}" if f > 1 else "",
                 f" · 소유자 확인은 공개 노드(publicnode)라 {int(tb.own_poll)}초마다(헬리우스 0) — 이 주기는 ATA 확인(헬리우스 열거)" if tb.pn_head else "")
    tb._dirty = True
    return {"period": tb.eff_poll, "perDay": round(c), "cap": round(cap), "fits": ok, "stretch": f}


SOL_PERIOD_EVERY = 600.0


def sol_period_tick(wt, tb: TierBook, now: float = None):
    now = time.time() if now is None else now
    rpc9 = getattr(wt, "rpc", None)
    try:
        pnh9 = bool(callable(getattr(rpc9, "pn_ok", None)) and rpc9.pn_ok())
    except Exception:
        pnh9 = False
    if now - float(getattr(tb, "_period_at", 0) or 0) < SOL_PERIOD_EVERY and pnh9 == bool(getattr(tb, "pn_head", False)):
        return
    tb._period_at = now
    tb.pn_head = pnh9
    tb.pn_win = float(getattr(rpc9, "head_window", 0) or 0) if pnh9 else 0.0
    tb.pn_audit = int(getattr(rpc9, "head_audit_n", 0) or 0) if pnh9 else 0
    try:
        tb.stake_n = sum(1 for k, v in (wt.cursor or {}).items() if str(k).startswith("_stk:") and isinstance(v, dict) and not v.get("gone"))
        tb.stake_on = bool(getattr(wt, "stake_on", False))
        tb.stake_every = float(getattr(wt, "stake_every", 3600) or 3600)
        plan_period_sol(tb, getattr(wt, "cfg", None) or common.load_config(), now)
    except Exception as e:
        log.warning("솔라나 기본 주기 계산 실패(종전 주기): %s", e)
        tb.period, tb.stretch = None, 1.0


_SOL_Q = "SELECT json_extract(snapshot, '$.fee_payer'), max(coalesce(ts, json_extract(snapshot, '$.ts'))) FROM raw_txs WHERE chain = 'sol' GROUP BY 1"
_PREFIX = 65536


def _tx_fields(tx) -> tuple:
    if not isinstance(tx, dict):
        return "", 0, ""
    return sent_from({"tx": tx}), snap_ts({"tx": tx}), str(tx.get("raw_input") or "")


def boot_from_ledger(scope: str, wallets, db_path: str = None) -> dict:
    db_path = db_path or common.DB_PATH
    if not os.path.exists(db_path):
        return {}
    want = {(w if scope == "sol" else str(w).lower()): w for w in wallets}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    out = {}

    def put(f, t):
        k = f if scope == "sol" else str(f or "").lower()
        if k in want and t:
            try:
                out[want[k]] = max(int(t), out.get(want[k], 0))
            except (TypeError, ValueError):
                pass
    try:
        conn.execute("PRAGMA query_only = 1")
        if scope == "sol":
            for f, t in conn.execute(_SOL_Q).fetchall():
                if f is not None and t is not None:
                    put(f, t)
            return out
        import json as _json
        dec = _json.JSONDecoder()
        left = []
        for rid, ts, pre in conn.execute("SELECT rowid, ts, substr(snapshot, 1, ?) FROM raw_txs WHERE chain = ?", (_PREFIX, scope)):
            tx = None
            if isinstance(pre, str) and pre.startswith('{"tx": {'):
                try:
                    tx, _e = dec.raw_decode(pre, 7)
                except ValueError:
                    tx = None
            if tx is None:
                left.append((rid, ts))
                continue
            f, t, raw = _tx_fields(tx)
            if f and raw != "0x01":
                put(f, ts if isinstance(ts, int) and ts > 0 else t)
        for rid, ts in left:
            r = conn.execute("SELECT json_extract(snapshot, '$.tx') FROM raw_txs WHERE rowid = ?", (rid,)).fetchone()
            try:
                tx = _json.loads(r[0]) if r and r[0] else None
            except ValueError:
                tx = None
            f, t, raw = _tx_fields(tx)
            if f and raw != "0x01":
                put(f, ts if isinstance(ts, int) and ts > 0 else t)
    finally:
        conn.close()
    return out


_BOOT_LOCK = threading.Lock()


def start_boot(books: list, db_path: str = None, gap: float = 2.0):
    todo = [b for b in books if b.cfg_on and b.safe and not (b.boot and b.boot.get("at"))]
    if not todo:
        return None

    def run():
        with _BOOT_LOCK:
            for b in todo:
                t0 = time.time()
                try:
                    sent = boot_from_ledger(b.scope, b.wallets, db_path)
                    b.set_boot(sent, "ledger")
                    log.info("주기 장부 %s: 원장에서 내 발신 시각 %d쌍 / %d쌍 (%.1f초)", b.scope, len(sent), len(b.wallets), time.time() - t0)
                except Exception as e:
                    b.set_boot({}, "ledger", err=common.safe_err(e))
                    log.warning("주기 장부 %s 부트스트랩 실패(지금 주기 유지 · 다음 기동 재시도): %s", b.scope, common.safe_err(e))
                b.save(force=True)
                time.sleep(gap)
    t = threading.Thread(target=run, daemon=True, name="tier-boot")
    t.start()
    return t


ES_LIMIT_DAY = 100000
HELIUS_LIMIT_DAY = 1000000 / 30.0


def per_check_calls(path: str, lp: bool = False) -> float:
    return {"etherscan": 3.0 + (1.0 if lp else 0.0), "blockscout": 3.0, "helius": 1.0}.get(path, 2.0)


def estimate(summaries: list, cfg: dict, es_other_day: float = 0.0, extra: list = None) -> dict:
    st = settings(cfg)
    out = {}

    def add(prov, nday, limit=None):
        e = out.setdefault(prov, {"perDay": 0.0, "limit": limit})
        e["perDay"] += nday
        if limit:
            e["limit"] = limit
    for s in summaries or []:
        path, scope = s.get("path"), s.get("scope")
        poll = max(1.0, float(s.get("basePoll") or 60))
        per = per_check_calls(path, bool(s.get("lp")))
        fulls = float(s.get("fullPerDay") or 0)
        if path == "etherscan":
            heads = min(86400.0 / poll, fulls) if fulls else 0.0
            add("etherscan", fulls * per + heads, ES_LIMIT_DAY)
        elif path == "helius":
            add("helius", float(s["solCost"]) if s.get("solCost") is not None else fulls * per, HELIUS_LIMIT_DAY)
        else:
            add(f"{path}:{scope}", fulls * per + 86400.0 / poll)
        if s.get("actPerDay"):
            add(f"rpc:{scope}", float(s["actPerDay"]) * 2.0)
    for scope, path, poll, npairs in extra or []:
        per = per_check_calls(path)
        prov = "etherscan" if path == "etherscan" else "helius" if path == "helius" else f"{path}:{scope}"
        add(prov, 86400.0 / max(1.0, float(poll or 60)) * per * int(npairs),
            ES_LIMIT_DAY if path == "etherscan" else HELIUS_LIMIT_DAY if path == "helius" else None)
    if es_other_day:
        add("etherscan", es_other_day, ES_LIMIT_DAY)
    pct = st["budget_pct"] / 100.0
    for prov, e in out.items():
        e["perDay"] = round(e["perDay"])
        lim = e.get("limit")
        e["cap"] = round(lim * pct) if lim else None
        e["pct"] = round(100.0 * e["perDay"] / lim, 1) if lim else None
        e["over"] = bool(lim and e["perDay"] > lim * pct)
    return out


def plan_stretch(books: list, cfg: dict, es_other_day: float = 0.0) -> dict:
    es = [b for b in books if b.path_kind == "etherscan" and b.active]
    out = {"gate": False, "stretch": 1.0, "perDay": 0, "cap": None, "fits": True}
    if not es:
        return out

    def est():
        sm = []
        for b in es:
            s9 = b.summary()
            s9["lp"] = getattr(b, "lp", False)
            sm.append(s9)
        return estimate(sm, cfg, es_other_day).get("etherscan") or {}
    for b in es:
        b.stretch, b.gate_t0, b.period = 1.0, False, None
    e = est()
    out.update(perDay=e.get("perDay", 0), cap=e.get("cap"))
    cap = e.get("cap") or 0
    if cap and e.get("perDay", 0) > cap * PERIOD_HEAD_SHARE:
        pmax = float(settings(cfg)["period_max_sec"])

        def est_f(f):
            for b in es:
                b.period = min(pmax, b.base_poll * f) if f > 1.0 else None
            return est().get("perDay", 0)
        fmax = max(1.0, max(pmax / b.base_poll for b in es))
        f, _c, _ok = fit_period(est_f, 1.0, cap * PERIOD_HEAD_SHARE, fmax, step=0.25)
        est_f(f)
        e = est()
        out.update(period=f, perDay=e.get("perDay", 0))
        log.info("이더스캔 기본 주기: 지금 주기 쌍 %d개(체인 %d곳)라 수집 주기 ×%.2f 마다 확인(예상 하루 %d콜 · 상한 %d)",
                 sum(b.summary().get("t0", 0) for b in es), len(es), f, out["perDay"], cap)
    if not cap or e.get("perDay", 0) <= cap:
        return out
    for b in es:
        b.gate_t0 = True
    e = est()
    out.update(gate=True, perDay=e.get("perDay", 0))
    f = 1.0
    while e.get("perDay", 0) > cap and f < STRETCH_MAX:
        f = min(STRETCH_MAX, max(f * 1.25, -(-e["perDay"] / cap * 4 // 1) / 4.0 if f == 1.0 else 0))
        f = -(-f * 4 // 1) / 4.0
        for b in es:
            b.stretch = f
        e = est()
        out.update(stretch=f, perDay=e.get("perDay", 0))
    out["fits"] = e.get("perDay", 0) <= cap
    log.warning("이더스캔 예상 하루 %d콜 (상한 %d · %d%%) — 지금 주기 쌍도 RPC 점검 후 변화 때만 복구%s%s", out["perDay"], cap,
                settings(cfg)["budget_pct"], f" + 간격 ×{out['stretch']:.2f}" if out["stretch"] > 1 else "",
                "" if out["fits"] else " · ★상한 안에 못 맞춤 — 활동 주소가 너무 많음(유료 키 또는 주소 줄이기)★")
    return out


HOLD_TEXT = {"off": "꺼짐(설정)", "path": "이 체인은 수집 방식상 늘 지금 주기", "boot": "내 발신 기록 읽는 중", "hist": "이력 받는 중·재시도 중",
             "code": "계약·위임 주소(늘 지금 주기)", "req": "지금 확인 요청됨", "nosent": "활동 기록 확인 중", "unknown": "확인 중"}


def _es_today(now: float = None) -> dict:
    now = time.time() if now is None else now
    day = int(now // 86400)
    d = os.path.join(common.quota_dir(), "es_budget")
    n = 0
    try:
        for f in os.listdir(d):
            if f.endswith(".json"):
                j = common.read_json(os.path.join(d, f), {})
                if isinstance(j, dict) and j.get("day") == day:
                    n += int(j.get("n") or 0)
    except (OSError, ValueError, TypeError):
        pass
    el = max(600.0, now - day * 86400)
    out = {"n": n, "since": day * 86400, "projDay": round(n / el * 86400)}
    try:
        import bf_engine
        r9 = bf_engine.es_ledger_rooms(now)
        if not r9.get("off"):
            out.update(head=r9["nh"], rt=r9["rt"], fillLeft=max(0, int(r9["fill"])), fillFirst=bool(r9["fillFirst"]))
    except Exception:
        pass
    return out


def web_view(cfg: dict, add_n: int = 0, add_chains=None, now: float = None) -> dict:
    import glob
    now = time.time() if now is None else now
    st = settings(cfg)
    scopes, addrs, sums = {}, {}, []
    for f in sorted(glob.glob(os.path.join(common.STATE_DIR, "addr_tier_*.json"))):
        if os.path.basename(f) == REQ_PATH_NAME:
            continue
        d = common.read_json(f, {})
        if not isinstance(d, dict) or not d.get("scope") or not isinstance(d.get("pairs"), dict):
            continue
        sc = str(d["scope"])
        cc9 = ((cfg or {}).get("chains") or {}).get(sc)
        if sc != "sol" and (sc in ((cfg or {}).get("_disabled_chains") or ()) or not common.chain_enabled(sc, cc9)
                            or common.chain_discovery(sc, cc9) == "rpc"):
            continue
        sm = d.get("summary") if isinstance(d.get("summary"), dict) else {}
        if sm:
            sm = dict(sm, scope=sc, lp=bool(d.get("path") == "etherscan"))
            sums.append(sm)
        scopes[sc] = {"path": d.get("path"), "safe": d.get("safe"), "safeNote": d.get("safeNote"), "gate": d.get("gate"),
                      "stretch": d.get("stretch"), "boot": bool((d.get("boot") or {}).get("at")), "tiers": sm.get("tiers"),
                      "updatedAt": d.get("updatedAt"), "stale": now - float(d.get("updatedAt") or 0) > 1800,
                      "pairs": sm.get("pairs"), "t0": sm.get("t0"), "period": sm.get("period") or sm.get("basePoll"), "basePoll": sm.get("basePoll"),
                      "empty": sm.get("empty"), "filling": sm.get("filling"),
                      "perDay": (sm.get("solCost") if d.get("path") in ("helius", "solrpc") else
                                 round(float(sm.get("fullPerDay") or 0) * per_check_calls(str(d.get("path")), d.get("path") == "etherscan"))),
                      "prov": ("helius" if d.get("path") == "helius" else "etherscan" if d.get("path") == "etherscan" else f"{d.get('path')}:{sc}")}
        for w, p in d["pairs"].items():
            if not isinstance(p, dict):
                continue
            k = w if sc == "sol" else str(w).lower()
            iv, bs = p.get("iv"), p.get("bs")
            act = float(p.get("actAt") or 0)
            full = float(p.get("full") or 0)
            hold = p.get("hold")
            addrs.setdefault(k, []).append({
                "c": sc, "t": int(p.get("tier") or 0), "h": (str(hold).split(":")[0] if hold else None),
                "full": int(full) or None, "sent": p.get("sent"),
                "nextAct": int(act + iv) if iv and act else None, "nextFull": int(full + bs) if bs and full else None,
                "wake": bool(p.get("wake")),
                "f": p.get("fill") if p.get("fill") in FILL_ONLY else None,
                "e": bool(isinstance(p.get("empty"), dict) and p.get("code") == "eoa")})
    extra = []
    if add_n and add_chains:
        for c in add_chains:
            sc = scopes.get(c)
            path = (sc or {}).get("path") or ("etherscan" if ((cfg.get("chains") or {}).get(c) or {}).get("etherscan_chainid") else "blockscout")
            extra.append((c, path, chain_poll(cfg, c) if c != "sol" else 60, int(add_n)))
    es9 = _es_today(now)
    pair_cost = {}
    for c, cc in (cfg.get("chains") or {}).items():
        if not isinstance(cc, dict) or str(c).startswith("_"):
            continue
        path = (scopes.get(c) or {}).get("path") or ("rpc" if common.chain_discovery(c, cc) == "rpc" else "etherscan" if cc.get("etherscan_chainid") else "blockscout")
        pair_cost[c] = {"prov": "etherscan" if path == "etherscan" else f"{path}:{c}",
                        "day": round(86400.0 / chain_poll(cfg, c) * per_check_calls(path, path == "etherscan" and _lp_chain(c)))}
    budget = estimate(sums, cfg, extra=extra)
    base = estimate(sums, cfg)
    for k, v in budget.items():
        v["now"] = (base.get(k) or {}).get("perDay")
    rpcfb = []
    fbd = common.read_json(os.path.join(common.STATE_DIR, "rpc_fallback.json"), {})
    chains9 = cfg.get("chains") or {}
    for c, rec in sorted((fbd if isinstance(fbd, dict) else {}).items()):
        if c in chains9 and isinstance(rec, dict) and rec.get("active") and isinstance(rec.get("text"), str):
            rpcfb.append({"c": c, "text": rec["text"][:200], "since": rec.get("since")})
            if c in scopes:
                scopes[c]["stale"] = False
    return {"ok": True, "enabled": st["enabled"], "steps": [{"label": TIER_LABELS[i] if i < len(TIER_LABELS) else f"{i}",
                                                               "upToDays": None if lim is None else round(lim / 86400),
                                                               "every": (f"x{v:g}" if k == "x" else int(v))}
                                                              for i, (lim, (k, v)) in enumerate(st["steps"])],
            "backstopSec": st["backstop_sec"], "budgetPct": st["budget_pct"], "scopes": scopes, "addrs": addrs, "budget": budget,
            "esToday": es9, "holdText": HOLD_TEXT, "fillText": FILL_TEXT, "pairCost": pair_cost, "at": int(now), "rpcFb": rpcfb,
            "helToday": _hl_today(now)}


def _hl_today(now: float = None) -> dict:
    import bf_engine
    now = time.time() if now is None else now
    day = int(now // 86400)
    n = 0
    try:
        d = os.path.join(common.quota_dir(), "helius_budget")
        for f in os.listdir(d):
            if f.endswith(".json"):
                j = common.read_json(os.path.join(d, f), {})
                if isinstance(j, dict) and j.get("day") == day:
                    n += int(j.get("n") or 0)
    except (OSError, ValueError, TypeError):
        pass
    cfg9 = {}
    try:
        cfg9 = common.load_config()
        b = bf_engine.helius_day_budget(cfg9)
    except (Exception, SystemExit):
        cfg9 = {}
        b = bf_engine.helius_day_budget({})
    out = {"n": n, "budget": b, "since": day * 86400}
    try:
        es9 = (cfg9 or {}).get("etherscan") or {}
        burst9 = max(0.0, float(es9.get("pace_burst_pct", 4))) / 100.0
        keep9 = min(50.0, max(0.0, float(es9.get("fill_keep_pct", 2)))) / 100.0
        r9 = bf_engine.ledger_rooms("helius_budget", b, burst9, keep9, now, floor=bf_engine.helius_head_min(cfg9))
        if not r9.get("off"):
            out.update(head=r9["nh"], rt=r9["rt"], fillLeft=max(0, int(r9["fill"])), fillFirst=bool(r9["fillFirst"]))
    except Exception:
        pass
    try:
        hb9 = common.read_json(os.path.join(common.STATE_DIR, "health", "sol.json"), {}) or {}
        s9 = ((hb9.get("sources") or {}).get("sol") or {}) if isinstance(hb9, dict) else {}
        if s9.get("head_rpc_on"):
            fresh9 = now - float(hb9.get("ts") or 0) <= 1800
            cu9 = s9.get("helius_closed_until")
            out["pn"] = {"host": s9.get("head_rpc"), "ok": bool(s9.get("head_rpc_ok")) and fresh9, "rate": s9.get("head_rpc_rate"),
                         "n": s9.get("head_rpc_n"), "openUntil": s9.get("head_rpc_open_until"), "fresh": fresh9,
                         "hlClosedUntil": cu9 if isinstance(cu9, (int, float)) and cu9 > now else None,
                         "floorPct": round(float(s9.get("helius_head_min")) * 100, 1) if isinstance(s9.get("helius_head_min"), (int, float)) else None}
    except Exception:
        pass
    return out


_REQ_LOCK = threading.Lock()


def request_check(address: str = None) -> dict:
    with _REQ_LOCK:
        return _request_check_locked(address)


def _request_check_locked(address: str = None) -> dict:
    now = int(time.time())
    p = req_path()
    d = common.read_json(p, {})
    reqs = dict(d.get("reqs") or {}) if isinstance(d, dict) and isinstance(d.get("reqs"), dict) else {}
    reqs = {k: v for k, v in reqs.items() if isinstance(v, (int, float)) and now - v < 2 * 86400}
    key = "*" if not address else f"*:{address}"
    if now - int(reqs.get(key) or 0) < 30:
        return {"ok": True, "same": True, "key": key}
    reqs[key] = now
    if len(reqs) > 2000:
        reqs = dict(sorted(reqs.items(), key=lambda kv: -kv[1])[:2000])
    common.atomic_write_json(p, {"v": 1, "reqs": reqs, "updatedAt": now})
    return {"ok": True, "key": key, "at": now}
