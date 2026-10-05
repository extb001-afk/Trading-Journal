"""Solana wallet watcher."""
from __future__ import annotations

from collections import deque
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import lpsol
import bf_engine
from inbox import SegmentWriter

log = common.setup_logging("tj-sol")

TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
PLAIN_PROGRAMS = set(TOKEN_PROGRAMS) | {
    "11111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "ComputeBudget111111111111111111111111111111",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
}
SIG_PAGE = 1000
TX_BATCH_SLEEP = 0.12
RATE_LIMIT_MAX = 5
BUDGET_WARN_PER_HOUR = 20000
ADDR_PACE_SEC = 0.25
ADDR_PACE_MAX = 2.0
ATA_EVERY_CYCLES = 5
RL_WAIT_MAX = 30.0
PRIMARY_TRIP_STREAK = 3
PRIMARY_QUOTA_OPEN = 1800.0
PRIMARY_RL_OPEN = 60.0
PARSE_BATCH = 1
SIG_SPOOL_PAGES = 30

STAKE_PROGRAM = "Stake11111111111111111111111111111111111111"
JITO_TIP_DIST = "4R3gSG8BpU4t19KYj8CfnbtRpnT8gtk4dvTHxVRwc2r7"
STAKE_WITHDRAWER_OFFSET = 44
STAKE_EVERY_SEC = 3600
STAKE_RWD_POLL_SEC = 600
STAKE_RWD_MARGIN_SLOTS = 9000
STAKE_RWD_EPOCHS_PER_CYCLE = 8
SLOTS_PER_EPOCH = 432000
SLOT_SEC_EST = 0.4
U64_MAX = 18446744073709551615


class RateLimited(RuntimeError):

    def __init__(self, msg: str, retry_after=None, quota: bool = False):
        super().__init__(msg)
        self.retry_after = retry_after
        self.quota = quota


def _retry_after_sec(v):
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        return max(0.0, parsedate_to_datetime(v).timestamp() - time.time())
    except Exception:
        return None


class Rpc:
    def __init__(self, cfg: dict):
        key = os.environ.get("TJ_HELIUS_KEY", "")
        if not key:
            envp = os.path.join(common.BASE_DIR, ".env")
            try:
                with open(envp, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("TJ_HELIUS_KEY="):
                            key = line.strip().split("=", 1)[1]
            except OSError:
                pass
        sol = cfg.get("sol", {})
        if sol.get("rpc") == "helius":
            if not key:
                raise SystemExit("TJ_HELIUS_KEY 없음 (.env) — fail-closed")
            self.url = f"https://mainnet.helius-rpc.com/?api-key={key}"
        else:
            self.url = sol.get("rpc") or sol.get("rpc_fallback")
        self.fallback = sol.get("rpc_fallback")
        self.fallbacks = []
        for u in [self.fallback] + list(sol.get("rpc_fallbacks") or []):
            if u and u != self.url and u not in self.fallbacks:
                self.fallbacks.append(u)
        self.calls = deque()
        self.rl_streak = 0
        self.rl_seen = 0
        self.rl_last = False
        self.primary_open_until = 0.0
        self.primary_open_n = 0
        self.quota_open = float(sol.get("quota_open_sec", PRIMARY_QUOTA_OPEN))

    def _trip_primary(self, e: "RateLimited"):
        dur = self.quota_open if e.quota else min(PRIMARY_RL_OPEN * (2 ** self.primary_open_n), self.quota_open)
        self.primary_open_until = time.time() + dur
        self.primary_open_n += 1
        log.warning("주 RPC %s — %.0f분간 폴백 RPC 직행 (%s)", "쿼터 소진(max usage)" if e.quota else
                    f"연속 429 {self.rl_streak}회", dur / 60, str(e)[:80])

    def primary_open(self) -> bool:
        return self.primary_open_until > time.time()

    def _rl_wait(self, e: "RateLimited") -> float:
        ra = e.retry_after
        if ra is None:
            ra = min(2.0 ** self.rl_streak, RL_WAIT_MAX)
        return min(max(ra, 0.5), RL_WAIT_MAX)

    def call(self, method: str, params, timeout=25):
        self.rl_last = False
        if self.primary_open():
            first = RuntimeError(f"주 RPC 차단 중(쿼터/429) — {self.primary_open_until - time.time():.0f}s 남음")
        else:
            try:
                return self._call(self.url, method, params, timeout)
            except RateLimited as e:
                self.rl_streak += 1
                if e.quota or self.rl_streak >= PRIMARY_TRIP_STREAK:
                    self._trip_primary(e)
                    first = e
                else:
                    time.sleep(self._rl_wait(e))
                    try:
                        return self._call(self.url, method, params, timeout)
                    except RateLimited as e2:
                        self.rl_streak += 1
                        if e2.quota or self.rl_streak >= PRIMARY_TRIP_STREAK:
                            self._trip_primary(e2)
                        first = e2
                    except Exception as e2:
                        first = e2
            except Exception as e:
                first = e
        if not self.fallbacks or method == "getAsset":
            raise first
        last = first
        for u in self.fallbacks:
            try:
                return self._call(u, method, params, timeout)
            except Exception as e:
                last = e
        raise last

    def _call(self, url: str, method: str, params, timeout=25):
        now = time.monotonic()
        self.calls.append(now)
        hour_ago = now - 3600
        while self.calls and self.calls[0] <= hour_ago:
            self.calls.popleft()
        n_hour = len(self.calls)
        if n_hour == BUDGET_WARN_PER_HOUR:
            log.error("★RPC 예산 경보: 최근 1시간 %d콜 — 한도 소진 위험", n_hour)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "tj-bot/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.rl_seen += 1
                self.rl_last = True
                try:
                    body = (e.read() or b"")[:200].decode("utf-8", "replace").lower()
                except Exception:
                    body = ""
                raise RateLimited(f"HTTP Error 429: Too Many Requests ({method})",
                                  _retry_after_sec(e.headers.get("Retry-After") if e.headers else None),
                                  quota=("max usage" in body or "quota" in body or "credits" in body)) from e
            raise
        if url == self.url:
            self.rl_streak = 0
        if "error" in d:
            raise RuntimeError(f"rpc {method}: {common.redact_secret_text(str(d['error']))}")
        if d.get("result") is None:
            raise RuntimeError(f"rpc {method}: result null")
        if method == "getTransaction":
            _check_tx_result(d["result"])
        return d.get("result")

    def batch(self, method: str, params_list: list, timeout=30) -> list:
        body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": method, "params": p}
                           for i, p in enumerate(params_list)]).encode()
        urls = ([] if self.primary_open() else [self.url]) + list(self.fallbacks)
        last = None
        for url in urls:
            now = time.monotonic()
            self.calls.append(now)
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                   "User-Agent": "tj-bot/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and url == self.url:
                    try:
                        b9 = (e.read() or b"")[:200].decode("utf-8", "replace").lower()
                    except Exception:
                        b9 = ""
                    self.rl_seen += 1
                    self._trip_primary(RateLimited("HTTP Error 429 (batch)", quota="max usage" in b9 or "quota" in b9))
                last = e
                continue
            except Exception as e:
                last = e
                continue
            if not isinstance(d, list):
                last = RuntimeError(f"batch 응답 형식 오류: {str(d)[:100]}")
                continue
            out = [RuntimeError("batch 항목 누락") for _ in params_list]
            for it in d:
                try:
                    i = int(it.get("id"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not 0 <= i < len(params_list):
                    continue
                if it.get("error"):
                    out[i] = RuntimeError(f"rpc {method}: {common.redact_secret_text(str(it['error']))}")
                elif it.get("result") is None:
                    out[i] = RuntimeError(f"rpc {method}: result null")
                else:
                    try:
                        if method == "getTransaction":
                            _check_tx_result(it["result"])
                        out[i] = it["result"]
                    except Exception as e9:
                        out[i] = e9
            return out
        raise last if last else RuntimeError("batch: RPC 없음")


def _check_tx_result(result):
    tx9 = result if isinstance(result, dict) else {}
    meta9 = tx9.get("meta")
    keys9 = ((tx9.get("transaction") or {}).get("message") or {}).get("accountKeys")
    if (not isinstance(meta9, dict) or meta9.get("fee") is None or "err" not in meta9
            or not isinstance(keys9, list) or not keys9
            or any(not isinstance(meta9.get(k), list) or len(meta9[k]) != len(keys9)
                   for k in ("preBalances", "postBalances"))):
        raise RuntimeError("rpc getTransaction: 실행 메타/잔고 불완전 — 부분 결과 거부")


_STAKE_IX_KEYS = {
    "initialize": (("stakeAccount",), ("authorized.withdrawer",)),
    "initializeChecked": (("stakeAccount",), ("withdrawer",)),
    "split": (("stakeAccount", "newSplitAccount"), ("stakeAuthority",)),
    "merge": (("destination", "source"), ("stakeAuthority",)),
    "withdraw": (("stakeAccount",), ("withdrawAuthority",)),
    "delegate": (("stakeAccount",), ("stakeAuthority",)),
    "deactivate": (("stakeAccount",), ("stakeAuthority",)),
    "moveStake": (("source", "destination"), ("stakeAuthority",)),
    "moveLamports": (("source", "destination"), ("stakeAuthority",)),
}


def _stake_ix_accounts(instructions: list, owners) -> list:
    out = []
    for ins in instructions or []:
        if ins.get("programId") != STAKE_PROGRAM and ins.get("program") != "stake":
            continue
        p = ins.get("parsed")
        if not isinstance(p, dict):
            continue
        spec = _STAKE_IX_KEYS.get(p.get("type"))
        info = p.get("info") or {}
        if not spec or not isinstance(info, dict):
            continue
        w = None
        for f in spec[1]:
            v = info
            for part in f.split("."):
                v = v.get(part) if isinstance(v, dict) else None
            if isinstance(v, str) and v in owners:
                w = v
                break
        if not w:
            continue
        for f in spec[0]:
            a = info.get(f)
            if isinstance(a, str) and a and a not in owners:
                out.append((a, w))
    return out


def stake_state(act, deact, epoch) -> str:
    try:
        act, deact, epoch = int(act), int(deact), int(epoch)
    except (TypeError, ValueError):
        return "undelegated"
    if deact != U64_MAX and deact < epoch:
        return "inactive"
    if deact != U64_MAX:
        return "deactivating"
    return "activating" if act >= epoch else "active"


class SolWatcher:
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        self.rpc = Rpc(cfg)
        self.owners = wallets
        months = 0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
        self.cutoff_ts = int(time.time() - months * 30 * 86400) if months > 0 else 0
        self.writer = writer
        self.cursor_path = os.path.join(common.STATE_DIR, "cursor_sol.json")
        self.cursor = common.read_json(self.cursor_path, {})
        self.meta_path = os.path.join(common.STATE_DIR, "sol_mint_meta.json")
        self.mint_meta = common.read_json(self.meta_path, {})
        self.emitted_path = os.path.join(common.STATE_DIR, "emitted_sol.json")
        self.emitted = set(common.read_json(self.emitted_path, []))
        self.ata_owner = {}
        sol9 = cfg.get("sol") or {}
        self.ata_every = max(1, int(sol9.get("ata_every_cycles", ATA_EVERY_CYCLES)))
        self.addr_pace = float(sol9.get("addr_pace_sec", ADDR_PACE_SEC))
        self._n_cycle = 0
        self.parse_batch = max(1, int(sol9.get("parse_batch", PARSE_BATCH)))
        self.batch_sleep = float(sol9.get("batch_sleep_sec", 1.0))
        self.batch_sleep_min = self.batch_sleep
        self.sig_spool_pages = max(1, int(sol9.get("sig_spool_pages", SIG_SPOOL_PAGES)))
        self.progress = bf_engine.progress("sol")
        self._rl_log_at = time.time()
        self._rl_log_base = 0
        self.stake_on = bool(sol9.get("stake", True))
        self.stake_every = float(sol9.get("stake_every_sec", STAKE_EVERY_SEC))
        self.stake_path = os.path.join(common.STATE_DIR, "sol_stake.json")
        self.stake_snap = common.read_json(self.stake_path, {}) or {}
        self._stake_disc_at = 0.0
        self._stake_rwd_at = 0.0
        self._epoch = None
        self._stake_err = None
        self._bt_cache = {}

    def stake_reg(self) -> dict:
        return {k[5:]: v for k, v in self.cursor.items() if k.startswith("_stk:") and isinstance(v, dict)}

    def _stake_t0(self) -> int:
        vals = [v for v in (self.cutoff_ts, bf_engine.SINCE.target("sol")) if v]
        return int(min(vals)) if vals else 0

    def list_atas(self, owner: str) -> list:
        out = []
        for prog in TOKEN_PROGRAMS:
            res = self.rpc.call("getTokenAccountsByOwner",
                                [owner, {"programId": prog}, {"encoding": "jsonParsed"}])
            time.sleep(TX_BATCH_SLEEP)
            if res is None:
                raise RuntimeError(f"ATA 열거 응답 None ({owner[:8]}/{prog[:8]})")
            for it in (res or {}).get("value", []):
                pk = it.get("pubkey")
                if pk:
                    out.append(pk)
                    self.ata_owner[pk] = owner
        return out

    class SpoolPending(RuntimeError):
        pass

    def _spool_path(self, addr: str, tag: str = "") -> str:
        return os.path.join(common.STATE_DIR, f"solspool{tag}_{addr}.jsonl")

    def _sigs_spooled(self, addr: str, ck: dict, first_rows: list = None, cutoff: int = None, tag: str = ""):
        path = self._spool_path(addr, tag)
        cutoff = self.cutoff_ts if cutoff is None else cutoff
        if os.path.exists(path) and os.path.getsize(path) > int(ck.get("off", 0)):
            with open(path, "r+b") as f:
                f.truncate(int(ck.get("off", 0)))
        pages = 0

        def _append(rows):
            with open(path, "ab") as f:
                f.write(b"".join((json.dumps({"signature": r["signature"], "slot": r.get("slot"),
                                              "blockTime": r.get("blockTime")}) + "\n").encode() for r in rows))
                f.flush()
                os.fsync(f.fileno())
                ck["off"] = f.tell()
            ck["n"] = int(ck.get("n", 0)) + len(rows)
            ck["before"] = rows[-1]["signature"] if rows else ck.get("before")

        if first_rows is not None:
            _append(first_rows)
            common.atomic_write_json(self.cursor_path, self.cursor)
        while not ck.get("done") and pages < self.sig_spool_pages:
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if ck.get("before"):
                opt["before"] = ck["before"]
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            rows = res
            stop = len(rows) < SIG_PAGE
            if cutoff:
                kept = [r for r in rows
                        if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= cutoff]
                stop = stop or len(kept) < len(rows)
                rows = kept
            if rows:
                _append(rows)
            if stop:
                ck["done"] = True
            common.atomic_write_json(self.cursor_path, self.cursor)
            pages += 1
            self.progress.update(f"sol:{addr[:8]}", phase="sigs", unit="sigs", done=int(ck["n"]),
                                 note="서명 수집 중(총량 미상)")
            time.sleep(TX_BATCH_SLEEP)
        if not ck.get("done"):
            raise self.SpoolPending(f"{addr[:8]} 서명 {ck['n']}건 수집 — 다음 사이클 계속")
        if int(ck.get("off", 0)) == 0:
            return []
        out = []
        with open(path, "rb") as f:
            for line in f.read(int(ck["off"])).splitlines():
                if line.strip():
                    out.append(json.loads(line.decode()))
        return out

    def new_sigs(self, addr: str, cutoff: int = None):
        cut = self.cutoff_ts if cutoff is None else cutoff
        until = self.cursor.get(addr)
        ck = self.cursor.get("_sigbf:" + addr)
        if not until and isinstance(ck, dict):
            return self._sigs_spooled(addr, ck, cutoff=cut)
        sigs = []
        before = None
        pages = 0
        while pages < 200:
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if until:
                opt["until"] = until
            if before:
                opt["before"] = before
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            rows = res
            if cut:
                kept = [r for r in rows
                        if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= cut]
                sigs.extend(kept)
                if len(kept) < len(rows):
                    break
            else:
                sigs.extend(rows)
            if len(rows) < SIG_PAGE:
                break
            if not until and pages == 0:
                ck = self.cursor["_sigbf:" + addr] = {"n": 0, "off": 0, "before": None, "done": False,
                                                      "t0": int(time.time())}
                log.info("%s 대형 신규 주소 — 재개형 서명 수집(스풀) 시작", addr[:8])
                return self._sigs_spooled(addr, ck, first_rows=sigs, cutoff=cut)
            before = rows[-1]["signature"]
            pages += 1
            time.sleep(TX_BATCH_SLEEP)
        else:
            raise RuntimeError(f"getSignaturesForAddress {pages}페이지 상한 도달 ({addr[:8]}) — 부분 결과 거부")
        return sigs

    def mint_info(self, mint: str, fallback_dec) -> tuple:
        if mint in self.mint_meta:
            m = self.mint_meta[mint]
            return m[0], m[1]
        sym, dec = None, fallback_dec
        ok = True
        try:
            res = self.rpc.call("getAsset", {"id": mint})
            sym = (((res or {}).get("content") or {}).get("metadata") or {}).get("symbol")
            ti = (res or {}).get("token_info") or {}
            if isinstance(ti.get("decimals"), int):
                dec = ti["decimals"]
            if isinstance(ti.get("symbol"), str) and not sym:
                sym = ti["symbol"]
        except Exception:
            ok = False
        if isinstance(sym, str):
            sym = sym.strip()[:16] or None
        if ok:
            self.mint_meta[mint] = [sym, dec]
        return sym, dec

    TX_OPTS = {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}

    def parse_tx(self, sig: str):
        tx = self.rpc.call("getTransaction", [sig, dict(self.TX_OPTS)])
        return self._parse_result(sig, tx)

    def parse_txs(self, sigs: list) -> dict:
        out = {}
        if self.parse_batch > 1 and len(sigs) > 1:
            try:
                res = self.rpc.batch("getTransaction", [[s9, dict(self.TX_OPTS)] for s9 in sigs])
                n_rl = 0
                for s9, r9 in zip(sigs, res):
                    if not isinstance(r9, Exception):
                        try:
                            out[s9] = self._parse_result(s9, r9)
                        except Exception as e:
                            out[s9] = e
                    elif "429" in str(r9) or "too many" in str(r9).lower():
                        n_rl += 1
                if n_rl:
                    self.batch_sleep = min(30.0, max(self.batch_sleep * 2, float(len(sigs))))
                    time.sleep(self.batch_sleep)
                else:
                    self.batch_sleep = max(self.batch_sleep_min, self.batch_sleep * 0.8)
            except Exception as e:
                log.info("getTransaction 배치 실패 → 단건: %s", str(e)[:100])
        for s9 in sigs:
            if s9 not in out or isinstance(out[s9], Exception):
                try:
                    out[s9] = self.parse_tx(s9)
                except Exception as e:
                    out[s9] = e
                time.sleep(TX_BATCH_SLEEP)
        return out

    def _parse_result(self, sig: str, tx):
        if not tx:
            return None
        meta = tx.get("meta") or {}
        msg = (tx.get("transaction") or {}).get("message") or {}
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys", [])]
        mine = set(self.owners)
        stake_of = {s: (v.get("w") or "") for s, v in self.stake_reg().items() if v.get("w")} if self.stake_on else {}
        all_ins = list(msg.get("instructions") or [])
        for inn in (meta.get("innerInstructions") or []):
            all_ins.extend(inn.get("instructions") or [])
        stake_new = {}
        if self.stake_on:
            for s9, w9 in _stake_ix_accounts(all_ins, mine):
                if s9 not in stake_of and s9 not in mine:
                    stake_of[s9] = w9
                    stake_new[s9] = w9
        err = meta.get("err") is not None
        fee = int(meta.get("fee") or 0)
        fee_payer = keys[0] if keys else None
        fee_payer_mine = fee_payer in mine

        deltas = []
        counterparties = set()
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        stake_pre = {}
        for i, k in enumerate(keys):
            if i >= len(pre) or i >= len(post):
                break
            d = int(post[i]) - int(pre[i])
            if k in mine:
                adj = d + fee if (k == fee_payer and fee_payer_mine) else d
                if adj:
                    deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9,
                                   "delta": str(adj), "owner": k})
            elif k in stake_of:
                stake_pre[k] = int(pre[i])
                if d:
                    deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9,
                                   "delta": str(d), "owner": f"{stake_of[k]}:stake:{k}"})
            elif abs(d) > 1_000_000:
                counterparties.add(k)
        tb = {}
        for row in (meta.get("preTokenBalances") or []):
            key = (row.get("owner"), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[0] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        for row in (meta.get("postTokenBalances") or []):
            key = (row.get("owner"), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[1] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        for (owner, mint), (b0, b1, dec) in tb.items():
            d = b1 - b0
            if not d or not owner or not mint:
                continue
            if owner in mine:
                sym, dec2 = self.mint_info(mint, dec if isinstance(dec, int) else 0)
                deltas.append({"asset": mint, "symbol": sym,
                               "decimals": dec2 if isinstance(dec2, int) else 0,
                               "delta": str(d), "owner": owner})
            else:
                counterparties.add(owner)
        progs = set()
        for ins in (msg.get("instructions") or []):
            pid = ins.get("programId")
            if pid:
                progs.add(pid)
        has_program = any(p not in PLAIN_PROGRAMS for p in progs)
        out = {
            "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig,
            "slot": tx.get("slot"), "ts": tx.get("blockTime"),
            "fee_lamports": fee, "fee_payer_mine": fee_payer_mine,
            "fee_payer": fee_payer,
            "wallets": self.owners,
            "deltas": deltas, "counterparties": sorted(counterparties),
            "has_program": has_program, "err": err,
        }
        if stake_pre:
            out["stake_pre"] = stake_pre
        if stake_new:
            out["stake_new"] = stake_new
        if (not err and deltas and JITO_TIP_DIST in {i9.get("programId") for i9 in all_ins}
                and all(":stake:" in (d9.get("owner") or "") and int(d9["delta"]) > 0 for d9 in deltas)):
            out["stake_reward"] = {"kind": "mev"}
        lp9 = lpsol.extract(tx, mine)
        if lp9:
            out["lp"] = lp9
        return out

    def _stake_discover(self, force: bool = False) -> bool:
        if not self.stake_on:
            return False
        now = time.time()
        if not force and self._stake_disc_at and now - self._stake_disc_at < self.stake_every:
            return True
        if not force and now < getattr(self, "_stake_retry_at", 0):
            return False
        try:
            ei = self.rpc.call("getEpochInfo", [{"commitment": "finalized"}])
            self._epoch = {"epoch": int(ei["epoch"]), "slotIndex": int(ei["slotIndex"]),
                           "absoluteSlot": int(ei["absoluteSlot"]), "ts": int(now)}
            found = {}
            for w in self.owners:
                res = self.rpc.call("getProgramAccounts", [STAKE_PROGRAM, {
                    "encoding": "jsonParsed", "commitment": "finalized",
                    "filters": [{"memcmp": {"offset": STAKE_WITHDRAWER_OFFSET, "bytes": w}}]}])
                time.sleep(TX_BATCH_SLEEP)
                for it in res or []:
                    pk = it.get("pubkey")
                    acc = it.get("account") or {}
                    info = (((acc.get("data") or {}).get("parsed") or {}).get("info") or {})
                    auth = ((info.get("meta") or {}).get("authorized") or {})
                    if not pk or auth.get("withdrawer") != w:
                        continue
                    dl = ((info.get("stake") or {}).get("delegation") or {})
                    found[pk] = {"w": w, "lamports": int(acc.get("lamports") or 0),
                                 "stake": int(dl.get("stake") or 0), "voter": dl.get("voter"),
                                 "act": dl.get("activationEpoch"), "deact": dl.get("deactivationEpoch"),
                                 "rent": int((info.get("meta") or {}).get("rentExemptReserve") or 0),
                                 "staker": auth.get("staker"),
                                 "state": stake_state(dl.get("activationEpoch"), dl.get("deactivationEpoch"),
                                                      self._epoch["epoch"])}
        except Exception as e:
            self._stake_err = common.safe_err(e)[:160]
            self._stake_retry_at = now + 300
            log.info("스테이크 계정 발견 실패(5분 뒤 재시도): %s", e)
            return False
        t0 = self._stake_t0()
        for s, v in found.items():
            k = "_stk:" + s
            ent = self.cursor.get(k)
            if not isinstance(ent, dict):
                self.cursor[k] = {"w": v["w"], "t0": t0, "rwd_next": None, "first": None, "open": False}
                log.info("★스테이크 계정 발견 %s (지갑 %s, %.4f SOL, 검증인 %s) — 창 %s 부터 추적★", s[:8], v["w"][:8],
                         v["lamports"] / 1e9, (v["voter"] or "?")[:8], time.strftime("%Y-%m-%d", time.gmtime(t0)))
            elif ent.pop("gone", None) is not None:
                pass
        for s, ent in self.stake_reg().items():
            if s not in found and not ent.get("gone"):
                ent["gone"] = int(now)
        prev = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if s not in found and s in prev:
                found[s] = dict(prev[s], lamports=0, stake=0, state="closed", w=ent.get("w"))
        for s, v in found.items():
            v["ledger_ready"] = bool((self.cursor.get("_stk:" + s) or {}).get("open"))
        self.stake_snap = {"ts": int(now), "epoch": self._epoch, "accounts": found}
        common.atomic_write_json(self.stake_path, self.stake_snap)
        common.atomic_write_json(self.cursor_path, self.cursor)
        self._stake_disc_at = now
        self._stake_err = None
        return True

    def _block_time(self, slot: int) -> int:
        if slot in self._bt_cache:
            return self._bt_cache[slot]
        bt = int(self.rpc.call("getBlockTime", [int(slot)]))
        if len(self._bt_cache) > 512:
            self._bt_cache.clear()
        self._bt_cache[slot] = bt
        return bt

    def _stake_note_first(self, s: str, slot, pre) -> None:
        ent = self.cursor.get("_stk:" + s)
        if not isinstance(ent, dict) or (ent.get("open") and not ent.get("reopen_pending")) or slot is None or pre is None:
            return
        f = ent.get("first")
        if not f or int(slot) < int(f[0]):
            ent["first"] = [int(slot), int(pre)]

    def _stake_rewards(self) -> bool:
        reg = self.stake_reg()
        if not self.stake_on or not reg:
            return True
        now = time.time()
        if not self._epoch or now - self._epoch["ts"] >= STAKE_RWD_POLL_SEC:
            ei = self.rpc.call("getEpochInfo", [{"commitment": "finalized"}])
            self._epoch = {"epoch": int(ei["epoch"]), "slotIndex": int(ei["slotIndex"]),
                           "absoluteSlot": int(ei["absoluteSlot"]), "ts": int(now)}
        cur = self._epoch["epoch"]
        last = cur - 1 if self._epoch["slotIndex"] >= STAKE_RWD_MARGIN_SLOTS else cur - 2
        acc = (self.stake_snap.get("accounts") or {})
        for s, ent in reg.items():
            if ent.get("rwd_next") is None:
                t0 = int(ent.get("t0") or 0)
                act = (acc.get(s) or {}).get("act")
                try:
                    act = int(act)
                except (TypeError, ValueError):
                    act = None
                if t0:
                    lag = int((now - t0) / (SLOTS_PER_EPOCH * SLOT_SEC_EST)) + 3
                    e0 = max(cur - lag, act if act is not None else 0)
                else:
                    e0 = act if act is not None else cur - 1
                ent["rwd_next"] = int(e0)
        n = 0
        while n < STAKE_RWD_EPOCHS_PER_CYCLE:
            todo = {s: e for s, e in ((s, int(v.get("rwd_next"))) for s, v in reg.items()
                                      if not (v.get("gone") and v.get("open") and not v.get("reopen_pending"))) if e <= last}
            if not todo:
                break
            e = min(todo.values())
            addrs = sorted(s for s, e9 in todo.items() if e9 == e)
            res = self.rpc.call("getInflationReward", [addrs, {"epoch": e, "commitment": "finalized"}])
            if not isinstance(res, list) or len(res) != len(addrs):
                raise RuntimeError(f"getInflationReward 응답 형식 오류(epoch {e})")
            for s, r in zip(addrs, res):
                ent = reg[s]
                if r and int(r.get("amount") or 0) > 0:
                    slot9 = int(r["effectiveSlot"])
                    bt = self._block_time(slot9)
                    if bt >= int(ent.get("t0") or 0):
                        txh = f"stakerwd:{s}:{e}"
                        if txh not in self.emitted:
                            amt = int(r["amount"])
                            self.writer.append({
                                "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": slot9, "ts": bt,
                                "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                                "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(amt),
                                            "owner": f"{ent['w']}:stake:{s}"}],
                                "counterparties": [], "has_program": True, "err": False,
                                "stake_reward": {"kind": "epoch", "epoch": e, "commission": r.get("commission"),
                                                 "post_balance": int(r.get("postBalance") or 0),
                                                 "voter": (acc.get(s) or {}).get("voter")}})
                            self.emitted.add(txh)
                        self._stake_note_first(s, slot9, int(r.get("postBalance") or 0) - int(r["amount"]))
                ent["rwd_next"] = e + 1
            n += 1
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)
            time.sleep(TX_BATCH_SLEEP)
        return all(int(v.get("rwd_next")) > last for v in reg.values()
                   if not (v.get("gone") and v.get("open") and not v.get("reopen_pending")))

    def _stake_note_tx(self, rec: dict) -> None:
        for s9, w9 in (rec.get("stake_new") or {}).items():
            if not isinstance(self.cursor.get("_stk:" + s9), dict):
                self.cursor["_stk:" + s9] = {"w": w9, "t0": self._stake_t0(), "rwd_next": None, "first": None, "open": False}
                log.info("★스테이크 계정 발견(tx) %s (지갑 %s)★", s9[:8], w9[:8])
        for s9, pre9 in (rec.get("stake_pre") or {}).items():
            self._stake_note_first(s9, rec.get("slot"), pre9)

    def _stake_open(self, caught_up: bool) -> None:
        if not caught_up:
            return
        acc = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if ent.get("open") or s not in self.cursor:
                continue
            f = ent.get("first")
            if f:
                lam = int(f[1])
            elif s in acc and acc[s].get("state") != "closed":
                lam = int(acc[s].get("lamports") or 0)
            else:
                continue
            txh = f"stakeopen:{s}"
            if lam > 0 and txh not in self.emitted:
                self.writer.append({
                    "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": None,
                    "ts": int(ent.get("t0") or 0) or int(time.time()),
                    "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                    "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lam),
                                "owner": f"{ent['w']}:stake:{s}"}],
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": ent["w"], "lamports": lam,
                                   "first_slot": f[0] if f else None}})
                self.emitted.add(txh)
                log.info("★스테이크 기초잔고 %s %.6f SOL (창 %s)★", s[:8], lam / 1e9,
                         time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("t0") or 0))))
            ent["open"] = True
            if s in acc:
                acc[s]["ledger_ready"] = True
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        if self.stake_snap:
            common.atomic_write_json(self.stake_path, self.stake_snap)

    def _stake_sigs_between(self, s: str, lo: int, hi: int):
        out, before = [], None
        for _p in range(50):
            opt = {"limit": 1000, "commitment": "finalized"}
            if before:
                opt["before"] = before
            res = self.rpc.call("getSignaturesForAddress", [s, opt])
            if not isinstance(res, list):
                raise RuntimeError(f"getSignaturesForAddress 형식 오류({s[:8]})")
            stop = False
            for r in res:
                bt = r.get("blockTime")
                if bt is None:
                    raise RuntimeError(f"서명 blockTime 없음({s[:8]})")
                if int(bt) < lo:
                    stop = True
                    break
                if int(bt) < hi and not r.get("err"):
                    out.append(r["signature"])
            if stop or len(res) < 1000:
                return list(reversed(out))
            before = res[-1]["signature"]
        raise RuntimeError(f"스테이크 서명 50쪽 상한({s[:8]})")

    def _stake_reopen(self, caught_up=None) -> None:
        tgt = bf_engine.SINCE.target("sol")
        if not tgt:
            return
        tgt = int(tgt)
        changed = False
        acc = self.stake_snap.get("accounts") or {}
        for s, ent in self.stake_reg().items():
            if caught_up is None:
                if not ent.get("open") or ent.get("reopen_pending") or int(ent.get("t0") or 0) <= tgt + 60:
                    continue
                old_t0 = int(ent.get("t0") or 0)
                first = ent.get("first") if isinstance(ent.get("first"), list) else None
                n_emit = 0
                for sig in self._stake_sigs_between(s, tgt, old_t0):
                    rec = self.parse_tx(sig)
                    if not isinstance(rec, dict):
                        raise RuntimeError(f"스테이크 tx 파싱 실패 {sig[:10]}")
                    pre9 = (rec.get("stake_pre") or {}).get(s)
                    if pre9 is not None and rec.get("slot") is not None and (not first or int(rec["slot"]) < int(first[0])):
                        first = [int(rec["slot"]), int(pre9)]
                    if sig not in self.emitted:
                        self.writer.append(rec)
                        self.emitted.add(sig)
                        n_emit += 1
                    time.sleep(TX_BATCH_SLEEP)
                ent.update(t0=tgt, rwd_next=None, first=first, reopen_pending=True, reopen_from=old_t0)
                changed = True
                log.warning("★스테이크 기초잔고 재산정 시작 %s: 창 %s → %s · 옛 구간 tx 방출 %d(보상 따라잡은 뒤 기초잔고 확정)★", s[:8],
                            time.strftime("%Y-%m-%d", time.gmtime(old_t0)), time.strftime("%Y-%m-%d", time.gmtime(tgt)), n_emit)
                continue
            if not caught_up or not ent.get("reopen_pending"):
                continue
            first = ent.get("first")
            if first:
                lam = int(first[1])
            elif s in acc and acc[s].get("state") != "closed":
                lam = int(acc[s].get("lamports") or 0)
            else:
                continue
            new_t0 = int(ent["t0"])
            txh = f"stakeopen:{s}:{new_t0}"
            if txh not in self.emitted:
                self.writer.append({
                    "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": txh, "slot": None, "ts": new_t0,
                    "fee_lamports": 0, "fee_payer_mine": False, "fee_payer": None, "wallets": self.owners,
                    "deltas": ([{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lam),
                                 "owner": f"{ent['w']}:stake:{s}"}] if lam > 0 else []),
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": ent["w"], "lamports": lam, "first_slot": first[0] if first else None,
                                   "reopen": True, "t0": new_t0, "prev_t0": int(ent.get("reopen_from") or 0)}})
                self.emitted.add(txh)
            log.warning("★스테이크 기초잔고 재산정 %s: 창 %s → %s · %.6f SOL(과거 창 확장)★", s[:8],
                        time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("reopen_from") or 0))),
                        time.strftime("%Y-%m-%d", time.gmtime(new_t0)), lam / 1e9)
            ent.pop("reopen_pending", None)
            ent.pop("reopen_from", None)
            changed = True
        if changed:
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _stake_cycle(self) -> None:
        if not self.stake_on:
            return
        hb = bf_engine.health("sol")
        try:
            self._stake_reopen()
            caught = self._stake_rewards()
            self._stake_reopen(caught_up=caught)
            self._stake_open(caught)
            self._stake_err = None if self._stake_disc_at else self._stake_err
        except Exception as e:
            caught = False
            self._stake_err = common.safe_err(e)[:160]
            log.info("스테이킹 보상 단계 실패(다음 주기): %s", e)
        reg = self.stake_reg()
        now = time.time()
        disc_age = now - self._stake_disc_at if self._stake_disc_at else None
        facts = dict(accounts=len([1 for v in reg.values() if not v.get("gone")]),
                     discovered_at=int(self._stake_disc_at) or None, snapshot_ts=self.stake_snap.get("ts"),
                     epoch=(self._epoch or {}).get("epoch"),
                     rewards_next_epoch=min((int(v["rwd_next"]) for v in reg.values() if v.get("rwd_next") is not None),
                                            default=None),
                     rewards_caught_up=bool(caught), opened=sum(1 for v in reg.values() if v.get("open")),
                     staked_sol=round(sum(int(v.get("lamports") or 0) for v in (self.stake_snap.get("accounts") or {}).values()) / 1e9, 6))
        if self._stake_err or disc_age is None or disc_age > 3 * self.stake_every:
            hb.fail("sol_stake", RuntimeError(self._stake_err or "스테이크 계정 발견 스냅샷 오래됨"), "stake", **facts)
        else:
            hb.ok("sol_stake", "stake", **facts)
        hb.flush()

    def _rl_summary(self):
        now = time.time()
        if now - self._rl_log_at >= 3600:
            n = self.rpc.rl_seen - self._rl_log_base
            log.info("헬리우스/폴백 429 응답: 최근 %.0f분 %d회 (재시도 흡수 포함, 주소 간격 %.2fs, ATA %d사이클마다)",
                     (now - self._rl_log_at) / 60, n, self.addr_pace, self.ata_every)
            self._rl_log_at = now
            self._rl_log_base = self.rpc.rl_seen

    def cycle(self):
        full = (self._n_cycle % self.ata_every == 0)
        self._n_cycle += 1
        self._rl_summary()
        if full and self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        if full or not self._stake_disc_at:
            self._stake_discover()
        newp = {o for o in self.owners if o not in self.cursor}
        newp |= {k[7:] for k in self.cursor if k.startswith("_persp:")}
        for o in newp:
            self.cursor["_persp:" + o] = 1
        stake_reg = self.stake_reg()
        addrs = []
        for o in self.owners:
            addrs.append(o)
            if full:
                try:
                    addrs.extend(self.list_atas(o))
                except Exception:
                    self._n_cycle = 0
                    raise
                time.sleep(TX_BATCH_SLEEP)
        if full:
            for s9, v9 in stake_reg.items():
                if not v9.get("gone"):
                    addrs.append(s9)
        active_addrs = set(addrs)
        repersp_addrs = {a for a in addrs if a not in self.cursor and
                         (a in newp or self.ata_owner.get(a) in newp or a in stake_reg)}
        if full:
            addrs.extend(a for a in self.cursor
                         if not a.startswith("_") and a not in active_addrs)
        addr_sigs = {}
        all_new = {}
        fail_list = []
        rl_hits = 0
        rl_sleep = 1.0
        pace = self.addr_pace
        failed_addr = False
        for a in dict.fromkeys(addrs):
            if rl_hits >= RATE_LIMIT_MAX:
                log.warning("429 %d회 — 이번 사이클 나머지 주소 건너뜀(커서 유지)", rl_hits)
                failed_addr = True
                break
            try:
                rows = self.new_sigs(a, cutoff=(int(stake_reg[a].get("t0") or 0) if a in stake_reg else None))
            except self.SpoolPending as e:
                log.info("%s", e)
                failed_addr = True
                continue
            except Exception as e:
                log.debug("%s 서명 조회 실패 — 이 주소 커서 유지: %s", a[:8], e)
                fail_list.append((a[:8], common.safe_err(e)[:120]))
                failed_addr = True
                if "429" in str(e):
                    rl_hits += 1
                    time.sleep(rl_sleep)
                    rl_sleep = min(rl_sleep * 2, 8.0)
                continue
            finally:
                if self.rpc.rl_last:
                    pace = min(max(pace, 0.05) * 2, ADDR_PACE_MAX)
                time.sleep(pace)
            addr_sigs[a] = rows
            for r in rows:
                all_new.setdefault(r["signature"], a)
        ordered = []
        seen = set()
        for a, rows in addr_sigs.items():
            for r in reversed(rows):
                s = r["signature"]
                if s not in seen:
                    seen.add(s)
                    ordered.append(r)
        ordered.sort(key=lambda r: r.get("slot") or 0)
        re_sigs = {r["signature"] for a in repersp_addrs for r in addr_sigs.get(a, ()) if r["signature"] in self.emitted}
        cut_all = min([self.cutoff_ts] + [int(v.get("t0") or 0) for v in stake_reg.values()]) if self.cutoff_ts else 0
        done_ok = True
        todo = [r["signature"] for r in ordered if (r["signature"] not in self.emitted or r["signature"] in re_sigs) and not (
            cut_all and isinstance(r.get("blockTime"), int) and r["blockTime"] < cut_all)]
        pre = {}
        pos = 0
        n_done = 0
        big = len(todo) > 50
        for r in ordered:
            sig = r["signature"]
            if sig in self.emitted and sig not in re_sigs:
                continue
            bt = r.get("blockTime")
            if cut_all and isinstance(bt, int) and bt < cut_all:
                continue
            if sig not in pre:
                while pos < len(todo) and todo[pos] != sig:
                    pos += 1
                chunk = todo[pos:pos + self.parse_batch]
                pos += len(chunk)
                pre = self.parse_txs(chunk) if chunk else {}
                time.sleep(TX_BATCH_SLEEP if len(chunk) <= 1 else self.batch_sleep)
            rec = pre.pop(sig, None)
            if isinstance(rec, Exception):
                log.warning("tx %s 파싱 실패 — 커서 미전진, 다음 사이클: %s", sig[:12], rec)
                done_ok = False
                break
            if rec is None:
                log.warning("tx %s 응답 None — 커서 보류, 다음 사이클 재조회", sig[:12])
                done_ok = False
                break
            if sig in re_sigs:
                rec["repersp"] = True
            try:
                self.writer.append(rec)
                self.emitted.add(sig)
                self._stake_note_tx(rec)
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                done_ok = False
                break
            n_done += 1
            if big and n_done % 50 == 0:
                self.progress.update("sol", phase="parse", unit="tx", done=n_done, total=len(todo))
                common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        if big:
            self.progress.update("sol", phase="parse" if not done_ok else "live", unit="tx", done=n_done,
                                 total=len(todo), flush=True)
        if done_ok:
            for a, rows in addr_sigs.items():
                if self.cursor.pop("_sigbf:" + a, None) is not None:
                    try:
                        os.remove(self._spool_path(a))
                    except OSError:
                        pass
                    self.progress.finish(f"sol:{a[:8]}", note=f"서명 {len(rows)}건 처리")
                if a not in active_addrs:
                    self.cursor.pop(a, None)
                    continue
                if not self.cursor.get(a) and "_cov_ts:" + a not in self.cursor:
                    self.cursor["_cov_ts:" + a] = int(self.cutoff_ts or 0)
                    if rows:
                        self.cursor["_cov_sig:" + a] = rows[-1]["signature"]
                if rows:
                    self.cursor[a] = rows[0]["signature"]
                else:
                    self.cursor.setdefault(a, "")
            if full and len(addr_sigs) == len(dict.fromkeys(addrs)):
                self.cursor["_synced_at"] = int(time.time())
        if not full and (failed_addr or not done_ok):
            self.cursor.pop("_synced_at", None)
        if full and done_ok:
            for o in newp:
                if o in self.cursor and all(a9 in self.cursor for a9, o9 in self.ata_owner.items() if o9 == o):
                    self.cursor.pop("_persp:" + o, None)
        common.atomic_write_json(self.meta_path, self.mint_meta)
        common.atomic_write_json(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        self._health_cycle(full, addrs, addr_sigs, fail_list, done_ok)
        self._stake_cycle()
        if full and done_ok and not fail_list:
            try:
                self._extend([a for a in dict.fromkeys(addrs) if a in active_addrs and a not in stake_reg])
            except Exception as e:
                log.info("과거 창 확장 예외(다음 전체 사이클): %s", e)

    EXT_BUDGET = 300

    def _extend(self, addrs: list):
        target = bf_engine.SINCE.target("sol")
        if not target:
            return
        deadline = time.time() + self.EXT_BUDGET
        for a in addrs:
            if time.time() > deadline:
                break
            cov = self.cursor.get("_cov_ts:" + a)
            if not isinstance(cov, int):
                cov = int(time.time())
            if cov <= target:
                continue
            ck = self.cursor.get("_sigx:" + a)
            if not isinstance(ck, dict) or ck.get("target") != target:
                ck = self.cursor["_sigx:" + a] = {"target": int(target), "n": 0, "off": 0,
                                                  "before": self.cursor.get("_cov_sig:" + a) or None, "done": False}
                try:
                    os.remove(self._spool_path(a, "x"))
                except OSError:
                    pass
            try:
                sigs = self._sigs_spooled(a, ck, cutoff=int(target), tag="x")
            except self.SpoolPending as e:
                log.info("확장 %s", e)
                continue
            todo = [r["signature"] for r in reversed(sigs) if r["signature"] not in self.emitted]
            n_ok = 0
            for i in range(0, len(todo), max(1, self.parse_batch)):
                if time.time() > deadline:
                    break
                chunk = todo[i:i + max(1, self.parse_batch)]
                res = self.parse_txs(chunk) if len(chunk) > 1 else {chunk[0]: self.parse_tx(chunk[0])}
                bad = False
                for sg in chunk:
                    rec = res.get(sg)
                    if not isinstance(rec, dict):
                        bad = True
                        break
                    self.writer.append(rec)
                    self.emitted.add(sg)
                    n_ok += 1
                time.sleep(TX_BATCH_SLEEP if len(chunk) <= 1 else self.batch_sleep)
                if bad:
                    break
            common.atomic_write_json(self.emitted_path, sorted(self.emitted))
            left = [sg for sg in todo if sg not in self.emitted]
            self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", done=len(todo) - len(left),
                                 total=len(todo), target=time.strftime("%Y-%m-%d", time.gmtime(target)))
            if not left:
                self.cursor["_cov_ts:" + a] = int(target)
                if sigs:
                    self.cursor["_cov_sig:" + a] = sigs[-1]["signature"]
                self.cursor.pop("_sigx:" + a, None)
                try:
                    os.remove(self._spool_path(a, "x"))
                except OSError:
                    pass
                self.progress.finish(f"sol:{a[:8]}:extend", note=f"{len(todo)}건")
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _health_cycle(self, full, addrs, addr_sigs, fail_list, done_ok):
        hb = bf_engine.health("sol")
        n_addr = len(dict.fromkeys(addrs))
        ok = done_ok and not fail_list and len(addr_sigs) == n_addr
        self._fail_cycles = 0 if ok else getattr(self, "_fail_cycles", 0) + 1
        if fail_list:
            lv = bf_engine.LogDebounce.level(self._fail_cycles) or "debug"
            getattr(log, lv)("서명 조회 실패 %d/%d 주소 (연속 %d사이클, 커서 유지·다음 주기 재시도) — 예: %s", len(fail_list),
                             n_addr, self._fail_cycles, "; ".join(f"{a}: {e}" for a, e in fail_list[:2]))
        slot = None
        if full:
            try:
                slot = int(self.rpc.call("getSlot", [{"commitment": "finalized"}]))
            except Exception:
                slot = None
        newest = max((r[0].get("blockTime") or 0 for r in addr_sigs.values() if r), default=0) or None
        facts = dict(addresses=n_addr, addresses_failed=len(fail_list), full_cycle=full,
                     head=slot if slot is not None else hb.src.get("sol", {}).get("head"),
                     newest_sig_block_time=newest, synced_at=self.cursor.get("_synced_at"),
                     primary=("open" if self.rpc.primary_open() else "ok"),
                     primary_open_until=int(self.rpc.primary_open_until) if self.rpc.primary_open() else None,
                     current_source=common.redact_urls(self.rpc.fallbacks[0] if (self.rpc.primary_open() and self.rpc.fallbacks)
                                                       else self.rpc.url),
                     rl_429_total=self.rpc.rl_seen, consecutive_failed_cycles=self._fail_cycles,
                     spooling=[k[7:15] for k in self.cursor if k.startswith("_sigbf:")])
        if ok:
            hb.ok("sol", "sol_rpc", **facts)
        else:
            hb.fail("sol", RuntimeError("; ".join(f"{a}: {e}" for a, e in fail_list[:3]) or
                                        ("tx 파싱/방출 실패" if not done_ok else "부분 조회")), "sol_rpc", **facts)
        hb.flush()


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "sol"]
    if not wallets:
        raise SystemExit("추적할 SOL 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("sol", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "sol"))
    w = SolWatcher(cfg, wallets, writer)
    log.info("가동: %d지갑, %d초 주기", len(wallets), poll)
    while True:
        t0 = time.time()
        try:
            w.cycle()
        except Exception as e:
            n9 = bf_engine.health("sol").fail("sol", e, "sol_rpc")
            bf_engine.health("sol").flush()
            lv = bf_engine.LogDebounce.level(n9)
            if lv:
                getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    main()
