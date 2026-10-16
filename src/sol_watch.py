"""Solana wallet watcher."""
from __future__ import annotations

from collections import deque
import contextlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import addr_tier
import lpsol
import bf_engine
import tsfix
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
from sol_base import (
    _check_tx_result,
    _hl_paced,
    _host,
    _PnSkip,
    _retry_after_sec,
    ARCHIVE_METHOD_PER10S,
    ARCHIVE_PER10S,
    ARCHIVE_RPC_DEFAULT,
    BUDGET_WARN_PER_HOUR,
    HEAD_AUDIT_PER_CYCLE,
    HEAD_GAP_SEC,
    HEAD_HEALTH_MIN_N,
    HEAD_HEALTH_PCT,
    HEAD_HEALTH_SEC,
    HEAD_KEEP_HOURS,
    HEAD_LAG_MAX_SLOTS,
    HEAD_MARGIN_HOURS,
    HEAD_METHODS,
    HEAD_RPC_DEFAULT,
    HEAD_TIMEOUT_SEC,
    HEAD_TRIP_BASE,
    HEAD_TRIP_MAX,
    HEAD_TRIP_STREAK,
    HL_COST,
    PRIMARY_QUOTA_OPEN,
    PRIMARY_RL_OPEN,
    PRIMARY_TRIP_STREAK,
    RateLimited,
    RL_WAIT_MAX,
    Rpc,
    SLOT_SEC_EST,
    SLOTS_PER_EPOCH,
    STAKE_PROGRAM,
    STAKE_RWD_EPOCHS_PER_CYCLE,
    STAKE_RWD_MARGIN_SLOTS,
    STAKE_RWD_POLL_SEC,
    stake_state,
    STAKE_WITHDRAWER_OFFSET,
    TX_BATCH_SLEEP,
    U64_MAX,
)
RATE_LIMIT_MAX = 5
ADDR_PACE_SEC = 0.25
ADDR_PACE_MAX = 2.0
ATA_EVERY_CYCLES = 5
PARSE_BATCH = 1
SIG_SPOOL_PAGES = 30
LIVE_FIRST_HOURS = 24.0
LIVE_FIRST_N = 100
OLD_SLICE_SEC = 60.0

HEAD_AUDIT_PAGES = 5
HEAD_AUDIT_TRIP_SEC = 6 * 3600.0

JITO_TIP_DIST = "4R3gSG8BpU4t19KYj8CfnbtRpnT8gtk4dvTHxVRwc2r7"
STAKE_EVERY_SEC = 3600


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


def _token_owner_hints(instructions: list, mine=()) -> dict:
    out = {}
    mine = set(mine or ())
    for ins in instructions or []:
        p = ins.get("parsed") if isinstance(ins, dict) else None
        if not isinstance(p, dict) or not isinstance(p.get("info"), dict):
            continue
        info, t, prog = p["info"], str(p.get("type") or ""), str(ins.get("program") or "")
        if prog == "spl-associated-token-account" and t in ("create", "createIdempotent"):
            a, o = info.get("account"), info.get("wallet")
        elif prog in ("spl-token", "spl-token-2022") and t in ("initializeAccount", "initializeAccount2", "initializeAccount3", "closeAccount"):
            a, o = info.get("account"), info.get("owner")
        elif prog in ("spl-token", "spl-token-2022") and t in ("transfer", "transferChecked", "burn", "burnChecked") and info.get("authority") in mine:
            a, o = info.get("source") or info.get("account"), info.get("authority")
        else:
            continue
        if isinstance(a, str) and isinstance(o, str) and a and o:
            out.setdefault(a, o)
    return out


ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_ATA_MEMO = {}


def ata_address(owner: str, mint: str, token_program: str):
    k = (owner, mint, token_program)
    if k in _ATA_MEMO:
        return _ATA_MEMO[k]
    try:
        o9, m9, p9 = lpsol.b58decode(owner), lpsol.b58decode(mint), lpsol.b58decode(token_program)
        a = lpsol.find_pda([o9, p9, m9], ATA_PROGRAM)[0] if len(o9) == 32 and len(m9) == 32 and len(p9) == 32 else None
    except (KeyError, ValueError, TypeError):
        a = None
    if len(_ATA_MEMO) > 50_000:
        _ATA_MEMO.clear()
    _ATA_MEMO[k] = a
    return a


def ata_owner_of(acct: str, mint, owners, program=None):
    if not isinstance(acct, str) or not isinstance(mint, str) or not acct or not mint:
        return None
    progs = (program,) if program in TOKEN_PROGRAMS else TOKEN_PROGRAMS
    for o in sorted(owners or ()):
        for p9 in progs:
            if ata_address(o, mint, p9) == acct:
                return o
    return None


from sol_stake import StakeMixin


class SolWatcher(StakeMixin):
    def __init__(self, cfg: dict, wallets: list, writer: SegmentWriter):
        self.cfg = cfg
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
        for k9 in [k9 for k9 in self.cursor if k9.startswith("_fb_wait:")]:
            if self.cursor[k9] in self.owners:
                self.ata_owner[k9[9:]] = self.cursor[k9]
            else:
                self.cursor.pop(k9, None)
        sol9 = cfg.get("sol") or {}
        self.ata_every = max(1, int(sol9.get("ata_every_cycles", ATA_EVERY_CYCLES)))
        self.addr_pace = float(sol9.get("addr_pace_sec", ADDR_PACE_SEC))
        self._n_cycle = 0
        self.parse_batch = max(1, int(sol9.get("parse_batch", PARSE_BATCH)))
        self.batch_sleep = float(sol9.get("batch_sleep_sec", 1.0))
        self.batch_sleep_min = self.batch_sleep
        self.sig_spool_pages = max(1, int(sol9.get("sig_spool_pages", SIG_SPOOL_PAGES)))
        def _num9(k, d, lo, hi):
            try:
                x = float(sol9.get(k, d))
            except (TypeError, ValueError):
                x = float(d)
            return min(hi, max(lo, x)) if x == x else float(d)
        self.live_first_h = _num9("live_first_hours", LIVE_FIRST_HOURS, 0, 24 * 30)
        self.live_first_n = int(_num9("live_first_n", LIVE_FIRST_N, 1, SIG_PAGE))
        self.old_slice = _num9("old_slice_sec", OLD_SLICE_SEC, 0, 86400)
        self._emit_cur = {}
        self._emit_seq = 0
        self._stk_t = {}
        for k9 in [k9 for k9 in self.cursor if isinstance(k9, str) and k9.startswith(("_hl:", "_fbw:"))]:
            v9 = self.cursor.get(k9)
            if not isinstance(v9, dict) or k9.split(":", 1)[1] in self.cursor or v9.get("o") not in self.owners:
                self.cursor.pop(k9, None)
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
        self._fb_est = {}
        self._fb_waiting = set()
        self._vat = {}
        self._vat_load()
        self._audit_i = 0
        self._retiring = set()
        self._tier = addr_tier.sol_book(self, cfg)

    def _vat_load(self):
        now9 = time.time()
        for k9 in [k9 for k9 in self.cursor if isinstance(k9, str) and k9.startswith("_vat:")]:
            a9, v9 = k9[5:], self.cursor.get(k9)
            if a9 not in self.cursor:
                self.cursor.pop(k9, None)
                continue
            t9 = v9.get("t") if isinstance(v9, dict) else None
            if isinstance(t9, (int, float)) and not isinstance(t9, bool) and t9 == t9 and v9.get("c") == (self.cursor.get(a9) or ""):
                self._vat[a9] = float(min(t9, now9))

    def _vat_save(self, a: str):
        t9 = self._vat.get(a)
        if t9 is None:
            self.cursor.pop("_vat:" + a, None)
            return
        self.cursor["_vat:" + a] = {"t": int(t9), "c": self.cursor.get(a) or ""}


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

    class FillPaced(SpoolPending):
        pass

    def _spool_path(self, addr: str, tag: str = "") -> str:
        return os.path.join(common.STATE_DIR, f"solspool{tag}_{addr}.jsonl")

    def _sigs_spooled(self, addr: str, ck: dict, first_rows: list = None, cutoff: int = None, tag: str = "", gate=None):
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
            if gate is not None and not gate():
                common.atomic_write_json(self.cursor_path, self.cursor)
                raise self.FillPaced(f"{addr[:8]} 서명 {ck['n']}건 — 오늘 옛 기록 몫을 다 써서 멈춤(몫이 나면 이어서)")
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if ck.get("before"):
                opt["before"] = ck["before"]
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            rows = res
            short = len(rows) < SIG_PAGE
            cut_stop = False
            if cutoff:
                kept = [r for r in rows
                        if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= cutoff]
                cut_stop = len(kept) < len(rows)
                rows = kept
            if rows:
                _append(rows)
            if cut_stop or (short and self._end_ok(res)):
                ck["done"] = True
            elif short:
                common.atomic_write_json(self.cursor_path, self.cursor)
                raise self.SpoolPending(f"{addr[:8]} 서명 {ck['n']}건 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 주 RPC 로 끝 확인 대기")
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

    def _end_ok(self, rows=None) -> bool:
        return getattr(self.rpc, "last_src", "primary") != "fallback"

    FB_MIN_SLOT_TTL = 600

    def _fb_min_slot(self, url):
        if not url:
            return None
        memo = self.__dict__.setdefault("_fb_min_memo", {})
        ent = memo.get(url)
        if ent and time.time() - ent[1] < self.FB_MIN_SLOT_TTL:
            return ent[0]
        fn = getattr(self.rpc, "_call", None)
        try:
            v = fn(url, "minimumLedgerSlot", []) if fn else None
            v = int(v) if isinstance(v, int) and not isinstance(v, bool) else None
        except Exception:
            v = None
        memo[url] = (v, time.time())
        return v

    def _cursor_set(self, addr: str, rows: list):
        self.cursor[addr] = rows[0]["signature"]
        sl = rows[0].get("slot")
        if isinstance(sl, int) and not isinstance(sl, bool):
            self.cursor["_slot:" + addr] = sl

    def new_sigs(self, addr: str, cutoff: int = None, gate=None, _bridge=None):
        cut = self.cutoff_ts if cutoff is None else cutoff
        until = self.cursor.get(addr) if _bridge is None else _bridge[0]
        ck = self.cursor.get("_sigbf:" + addr)
        if _bridge is None and not until and isinstance(ck, dict):
            rows9 = self._sigs_spooled(addr, ck, cutoff=cut, gate=gate)
            if not rows9:
                return rows9
            br9 = (rows9[0]["signature"], rows9[0].get("slot"))
            h9 = getattr(self.rpc, "hint", None)
            w9 = float(getattr(self.rpc, "head_window", 0) or 0) if getattr(self.rpc, "head_url", None) else 0.0
            t09 = ck.get("t0")
            pn9 = (w9 > 0 and isinstance(br9[1], int) and not isinstance(br9[1], bool) and isinstance(t09, (int, float))
                   and time.time() - (float(t09) - 60) <= w9)
            with (h9(pn=pn9, slot=br9[1]) if callable(h9) else contextlib.nullcontext()):
                newer9 = self.new_sigs(addr, cutoff=cut, gate=gate, _bridge=br9)
            return newer9 + rows9
        sigs = []
        before = None
        pages = 0
        while pages < 200:
            if _bridge is not None and gate is not None and not gate():
                raise self.FillPaced(f"{addr[:8]} 스풀 뒤 새 서명 — 오늘 옛 기록 몫을 다 써서 멈춤(몫이 나면 이어서)")
            opt = {"limit": SIG_PAGE, "commitment": "finalized"}
            if until:
                opt["until"] = until
            if before:
                opt["before"] = before
            t_call9 = time.time()
            res = self.rpc.call("getSignaturesForAddress", [addr, opt])
            if res is None:
                raise RuntimeError(f"getSignaturesForAddress None ({addr[:8]})")
            if getattr(self.rpc, "last_src", None) == "head":
                self._pnv_mark(addr, until or "", (_bridge[1] if _bridge is not None else self.cursor.get("_slot:" + addr)), t_call9)
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
                if not until and not self._end_ok(rows):
                    raise RuntimeError(f"{addr[:8]} 신규 주소 서명 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 주 RPC 로 다시")
                if until and not self._end_ok(rows):
                    us9 = self.cursor.get("_slot:" + addr) if _bridge is None else _bridge[1]
                    ms9 = self._fb_min_slot(getattr(self.rpc, "last_url", None))
                    if not (isinstance(us9, int) and isinstance(ms9, int) and ms9 <= us9):
                        raise RuntimeError(f"{addr[:8]} 서명 — 폴백 RPC 의 짧은 페이지(커서까지 이력 보유 미확인 · 노드 최저 슬롯 {ms9} · 커서 슬롯 {us9})"
                                           " · 주 RPC 로 다시")
                break
            if not until and pages == 0:
                ck = self.cursor["_sigbf:" + addr] = {"n": 0, "off": 0, "before": None, "done": False,
                                                      "t0": int(time.time())}
                log.info("%s 대형 신규 주소 — 재개형 서명 수집(스풀) 시작", addr[:8])
                return self._sigs_spooled(addr, ck, first_rows=sigs, cutoff=cut, gate=gate)
            before = rows[-1]["signature"]
            pages += 1
            time.sleep(TX_BATCH_SLEEP)
        else:
            raise RuntimeError(f"getSignaturesForAddress {pages}페이지 상한 도달 ({addr[:8]}) — 부분 결과 거부")
        return sigs

    def _pnv_mark(self, addr: str, sig: str, slot, t: float):
        k = "_pnv:" + addr
        e = self.cursor.get(k)
        if not isinstance(e, dict):
            self.cursor[k] = {"sig": sig or "", "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
                              "pn": float(t), "since": float(t)}
        else:
            e["pn"] = max(float(e.get("pn") or 0), float(t))

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

    TX_OPTS = {"encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 1}

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
        if getattr(self, "_tier", None) is not None:
            sg9 = self.__dict__.setdefault("_tier_signers", {})
            if len(sg9) > 5000:
                sg9.clear()
            sg9[sig] = [k.get("pubkey") for k in msg.get("accountKeys", []) if isinstance(k, dict) and k.get("signer")]
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
        pre_tb, post_tb = list(meta.get("preTokenBalances") or []), list(meta.get("postTokenBalances") or [])
        idx_owner = {r9.get("accountIndex"): r9.get("owner") for r9 in pre_tb + post_tb
                     if isinstance(r9, dict) and r9.get("owner") and isinstance(r9.get("accountIndex"), int)}
        hint9 = None

        def owner_of(row):
            nonlocal hint9
            o9 = row.get("owner")
            ix9 = row.get("accountIndex")
            if o9 or not isinstance(ix9, int):
                return o9
            if ix9 in idx_owner:
                return idx_owner[ix9]
            acct9 = keys[ix9] if 0 <= ix9 < len(keys) else None
            if not acct9:
                return f"?{ix9}"
            if hint9 is None:
                hint9 = _token_owner_hints(all_ins, mine)
            return ((getattr(self, "ata_owner", None) or {}).get(acct9) or hint9.get(acct9)
                    or ata_owner_of(acct9, row.get("mint"), mine, row.get("programId")) or f"?{ix9}")
        tb = {}
        for row in pre_tb:
            key = (owner_of(row), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[0] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        for row in post_tb:
            key = (owner_of(row), row.get("mint"))
            ent = tb.setdefault(key, [0, 0, (row.get("uiTokenAmount") or {}).get("decimals")])
            ent[1] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        unres9 = [{"acct": keys[int(o9[1:])] if int(o9[1:]) < len(keys) else None, "mint": m9, "delta": str(b1 - b0)}
                  for (o9, m9), (b0, b1, _d9) in tb.items() if isinstance(o9, str) and o9.startswith("?") and m9 and b1 != b0]
        hold9o = self.__dict__.setdefault("_own_hold", tsfix.TsHold())
        if unres9:
            old9 = not any(isinstance(r9, dict) and r9.get("owner") for r9 in pre_tb + post_tb)
            if not old9 and hold9o.hold(sig):
                raise RuntimeError(f"tx {sig[:12]} 토큰 잔고 {len(unres9)}줄 소유자 모름 — 보류(커서 유지 · 다음 사이클 다시)")
            now9 = time.time()
            if now9 - float(self.__dict__.get("_own_warn_at", 0) or 0) >= 600:
                self._own_warn_at = now9
                log.error("★tx %s 토큰 잔고 %d줄 소유자를 못 찾음(%s) — 그 줄 빼고 내보냄 · 목록 state/sol_owner_unknown.jsonl(내 계정이면 입출금이 빠짐)★",
                          sig[:12], len(unres9), "owner 칸 없는 옛 응답" if old9 else f"{hold9o.limit}회 연속")
            try:
                common.append_durable_jsonl(os.path.join(common.STATE_DIR, "sol_owner_unknown.jsonl"),
                                            {"ts": int(now9), "sig": sig, "old": old9, "rows": unres9})
            except OSError as e9:
                log.warning("sol_owner_unknown.jsonl 기록 실패: %s", e9)
        else:
            hold9o.clear(sig)
        for (owner, mint), (b0, b1, dec) in tb.items():
            d = b1 - b0
            if not d or not owner or not mint or str(owner).startswith("?"):
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
        bt9 = tx.get("blockTime")
        if not (isinstance(bt9, int) and not isinstance(bt9, bool) and bt9 > 0):
            hold9 = getattr(self, "_ts_hold", None)
            if hold9 is None:
                hold9 = self._ts_hold = tsfix.TsHold()
            try:
                bt9 = tsfix.block_ts(self, tx.get("slot") or 0, fn=self._block_time)
                hold9.clear(sig)
            except Exception as e:
                if hold9.hold(sig):
                    raise RuntimeError(f"tx {sig[:12]} 시각 없음 · 슬롯 시각 조회 실패 — 보류: {str(e)[:80]}") from e
                log.error("★tx %s 시각 없음 %d회 연속 — 내보냄(core 격리 → 슬롯 시각 구하는 대로 자동 재방출)★", sig[:12], hold9.limit)
                bt9 = tx.get("blockTime")
        out = {
            "v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig,
            "slot": tx.get("slot"), "ts": bt9,
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


    def _block_time(self, slot: int) -> int:
        if slot in self._bt_cache:
            return self._bt_cache[slot]
        bt = int(self.rpc.call("getBlockTime", [int(slot)]))
        if len(self._bt_cache) > 512:
            self._bt_cache.clear()
        self._bt_cache[slot] = bt
        return bt


    def _rl_summary(self):
        now = time.time()
        if now - self._rl_log_at >= 3600:
            n = self.rpc.rl_seen - self._rl_log_base
            log.info("헬리우스/폴백 429 응답: 최근 %.0f분 %d회 (재시도 흡수 포함, 주소 간격 %.2fs, ATA %d사이클마다)",
                     (now - self._rl_log_at) / 60, n, self.addr_pace, self.ata_every)
            self._rl_log_at = now
            self._rl_log_base = self.rpc.rl_seen

    def full_due(self, now: float = None) -> bool:
        now = time.time() if now is None else now
        tb0 = getattr(self, "_tier", None)
        pf9 = (tb0.eff_poll / tb0.base_poll) if tb0 is not None and tb0.base_poll else 1.0
        if pf9 > 1.0:
            return self._n_cycle == 0 or now - float(getattr(self, "_full_at", 0) or 0) >= tb0.eff_poll * self.ata_every * 0.98
        return self._n_cycle % self.ata_every == 0

    def hl_full_est(self) -> int:
        return 2 * len(self.owners) + int(getattr(self.rpc, "head_audit_n", 0) or 0) + 1

    def _fb_paced(self) -> bool:
        m9 = bf_engine.HELIUS
        return bool(getattr(self.rpc, "metered", False)) and callable(getattr(self.rpc, "fill_room", None)) \
            and getattr(m9, "fill_first", False) and m9.burst < 1.0

    def _fb_fits(self, est: int, left: int) -> bool:
        m9 = bf_engine.HELIUS
        fresh, keep = m9.fill_cap_fresh(), m9.keep_credits()
        if est <= left:
            return True
        if est <= fresh - keep:
            return False
        return left >= min(est, fresh) - keep

    def _own_of(self, a: str):
        return a if a in self.owners else self.ata_owner.get(a)

    def _persp_done(self, a: str, r: dict, stake: bool = False) -> bool:
        q9 = self._emit_cur.get(r["signature"])
        if q9 is not None and (not stake or q9 > self._stk_t.get(a, 1 << 62)):
            return True
        if stake:
            return False
        w9 = self.cursor.get("_fbw:" + a)
        if not isinstance(w9, dict) or w9.get("o") != self._own_of(a):
            return False
        s9, sl9 = w9.get("s"), r.get("slot")
        if isinstance(s9, int) and isinstance(sl9, int) and not isinstance(sl9, bool) and sl9 <= s9:
            return True
        c9 = self.__dict__.setdefault("_fbe", {})
        if a not in c9:
            c9[a] = set(x for x in (w9.get("e") or ()) if isinstance(x, str))
        return r["signature"] in c9[a]

    def _live_part(self, a: str, rows: list, now: float) -> set:
        if self.live_first_h <= 0:
            return {r["signature"] for r in rows}
        floor9 = now - self.live_first_h * 3600
        if a in self.cursor:
            return {r["signature"] for r in rows if not isinstance(r.get("blockTime"), int) or r["blockTime"] >= floor9}
        out = set()
        for r in rows:
            bt9 = r.get("blockTime")
            if len(out) >= self.live_first_n or not isinstance(bt9, int) or bt9 < floor9:
                break
            out.add(r["signature"])
        return out

    def _fb_left(self, a: str, rows: list, now: float) -> int:
        live9 = self._live_part(a, rows, now) if self.live_first_h > 0 else set()
        return sum(1 for r in rows if r["signature"] not in live9 and not (r["signature"] in self.emitted and self._persp_done(a, r)))

    def _row_done(self, r: dict, re_sigs, cut_all, emit9) -> bool:
        s9, bt9 = r["signature"], r.get("blockTime")
        if cut_all and isinstance(bt9, int) and bt9 < cut_all:
            return True
        return s9 in self.emitted and (s9 not in re_sigs or s9 in emit9)

    FBW_E_MAX = 500

    def _fbw_note(self, a: str, rows: list, re_sigs, cut_all, emit9, extra=()):
        o9 = self._own_of(a)
        if not o9:
            return
        done9, unh9 = [], []
        for r in rows:
            (done9 if self._row_done(r, re_sigs, cut_all, emit9) else unh9).append(r)
        w9 = self.cursor.get("_fbw:" + a)
        w9 = w9 if isinstance(w9, dict) and w9.get("o") == o9 else {}
        old9 = w9.get("s") if isinstance(w9.get("s"), int) else None
        s9 = old9
        if unh9:
            m9 = min((r.get("slot") if isinstance(r.get("slot"), int) and not isinstance(r.get("slot"), bool) else 0) for r in unh9) - 1
            if m9 > 0 and (old9 is None or m9 > old9):
                s9 = m9
        e9 = [x for x in (w9.get("e") or ()) if isinstance(x, str)]
        have9 = set(e9)
        for x in [r["signature"] for r in done9 if r["signature"] in self.emitted and not (isinstance(s9, int) and isinstance(r.get("slot"), int)
                                                                                        and r["slot"] <= s9)] + [x for x in extra if x in self.emitted]:
            if x not in have9:
                have9.add(x)
                e9.append(x)
        ent9 = {"o": o9, "s": s9, "e": e9[-self.FBW_E_MAX:]}
        if ent9 != {"o": o9, "s": old9, "e": [x for x in (w9.get("e") or ()) if isinstance(x, str)]}:
            self.cursor["_fbw:" + a] = ent9
            self.__dict__.setdefault("_fbe", {}).pop(a, None)

    def _live_peek(self, a: str, cut, now: float) -> list:
        hl9 = self.cursor.get("_hl:" + a)
        hl9 = hl9 if isinstance(hl9, dict) else {}
        sl9 = hl9.get("slot") if isinstance(hl9.get("slot"), int) and not isinstance(hl9.get("slot"), bool) else None
        opt = {"limit": self.live_first_n, "commitment": "finalized"}
        if hl9.get("sig"):
            opt["until"] = hl9["sig"]
        h9 = getattr(self.rpc, "hint", None)
        with (self.rpc.as_kind("head") if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                (h9(pn=bool(hl9.get("sig")), slot=sl9) if callable(h9) else contextlib.nullcontext()):
            res = self.rpc.call("getSignaturesForAddress", [a, opt])
        if not isinstance(res, list):
            raise RuntimeError(f"getSignaturesForAddress 형식 ({a[:8]})")
        res = [r for r in res if isinstance(r, dict) and isinstance(r.get("signature"), str)]
        if hl9.get("sig"):
            rows = [r for r in res if not (cut and isinstance(r.get("blockTime"), int) and r["blockTime"] < cut)]
        else:
            floor9 = max(int(cut or 0), now - self.live_first_h * 3600)
            rows = [r for r in res if isinstance(r.get("blockTime"), int) and r["blockTime"] >= floor9]
        top9 = res[0] if res else None
        self._hl_next[a] = {"o": self._own_of(a), "sig": top9["signature"] if top9 else (hl9.get("sig") or ""),
                            "slot": top9.get("slot") if top9 else sl9}
        return rows

    def _fb_hold(self, a: str, est):
        self._fb_wait_note(a)
        self._fb_waiting.add(a)
        self.progress.update(f"sol:{a[:8]}", phase="wait", unit="tx", done=0, total=est if est else None, eta_sec=0, rate=0,
                             paced_at=int(time.time()), note="오늘 옛 기록 몫을 다 써서 차례 대기 — UTC 0시(한국 오전 9시)에 이어 받아요")

    def _fb_wait_note(self, a: str):
        o9 = self.ata_owner.get(a)
        if o9 and a not in self.owners and self.cursor.get("_fb_wait:" + a) != o9:
            self.cursor["_fb_wait:" + a] = o9
            common.atomic_write_json(self.cursor_path, self.cursor)

    def cycle(self):
        full = self.full_due() and not self.__dict__.pop("_own_only", False)
        if full:
            self._full_at = time.time()
            self._pn_lag_check()
        self._n_cycle += 1
        self._rl_summary()
        if full and self.cursor.pop("_synced_at", None) is not None:
            common.atomic_write_json(self.cursor_path, self.cursor)
        if full or not self._stake_disc_at:
            self._stake_discover()
        own9 = tuple(self.owners)
        if own9 != getattr(self, "_own_snap", own9):
            self._emit_cur.clear()
        self._own_snap = own9
        newp = {o for o in self.owners if o not in self.cursor}
        newp |= {k[7:] for k in self.cursor if k.startswith("_persp:")}
        for o in newp:
            self.cursor["_persp:" + o] = 1
        stake_reg = self.stake_reg()
        for s9 in stake_reg:
            self._stk_t.setdefault(s9, self._emit_seq)
        tb = getattr(self, "_tier", None)
        own_set = full_set = set(self.owners)
        if tb is not None:
            addr_tier.sol_activity(self, tb)
            addr_tier.sol_period_tick(self, tb)
            due9, _rest9 = tb.due_list(self.owners)
            full_set = set(due9)
            if full:
                full_set |= {o for o in self.owners if tb.tier(o)[1] <= 0}
            now_set = full_set if full else {o for o in due9 if tb.tier(o)[1] <= 0 or isinstance((tb.pairs.get(o) or {}).get("wake"), dict)}
            own_set = now_set | set(tb.activity_targets())
        addrs = []
        for o in self.owners:
            if o not in own_set:
                continue
            addrs.append(o)
            if full and o in full_set:
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
        else:
            in9 = set(addrs)
            addrs.extend(a for a in sorted(getattr(self, "_unc_prev", ()) or ()) if a not in in9
                         and ((a in stake_reg and not stake_reg[a].get("gone")) or self._own_of(a) in own_set))
        active_addrs = set(addrs)
        if not full:
            addrs.extend(a for a in sorted(getattr(self, "_unc_ret", ()) or ()) if a not in active_addrs and self._own_of(a) in own_set)
        if full:
            addrs.extend(k9[9:] for k9, o9 in list(self.cursor.items())
                         if k9.startswith("_fb_wait:") and o9 in full_set and k9[9:] not in active_addrs and k9[9:] not in self.cursor)
        repersp_addrs = {a for a in addrs if a not in self.cursor and
                         (a in newp or self.ata_owner.get(a) in newp or a in stake_reg)}
        if full:
            addrs.extend(a for a in self.cursor
                         if not a.startswith("_") and a not in active_addrs
                         and not (tb is not None and (a in self.owners or self.ata_owner.get(a) in set(self.owners) - full_set)))
        addr_sigs = {}
        all_new = {}
        fail_list = []
        rl_hits = 0
        rl_sleep = 1.0
        pace = self.addr_pace
        failed_addr = False
        fb_set = {a for a in dict.fromkeys(addrs) if a not in self.cursor and a not in stake_reg
                  and (a in newp or self.ata_owner.get(a) in newp)}
        fb_pace = bool(fb_set) and self._fb_paced()
        slice_fb9 = self.old_slice > 0 and self.live_first_h > 0
        fb_resv = 0
        held = []
        hint9 = getattr(self.rpc, "hint", None)
        win9 = float(getattr(self.rpc, "head_window", 0) or 0) if getattr(self.rpc, "head_url", None) else 0.0
        hl_shut9 = callable(getattr(self.rpc, "hl_closed", None)) and self.rpc.hl_closed()
        t_list = {}
        self._retiring = {a for a in dict.fromkeys(addrs) if a not in active_addrs}
        gate9 = _pn_ok(self.rpc) and _hl_paced(self.rpc)
        defer9 = set()
        have9 = {}
        for a in dict.fromkeys(addrs):
            if rl_hits >= RATE_LIMIT_MAX:
                log.warning("429 %d회 — 이번 사이클 나머지 주소 건너뜀(커서 유지)", rl_hits)
                failed_addr = True
                break
            fb9 = a in fb_set
            if fb9 and fb_pace:
                left9 = self.rpc.fill_room() - fb_resv
                est9 = self._fb_est.get(a)
                if left9 <= 0 or (est9 and not slice_fb9 and not self._fb_fits(est9, left9)):
                    self._fb_hold(a, est9)
                    held.append(a)
                    failed_addr = True
                    continue
            retire9 = a not in active_addrs
            if retire9 and hl_shut9:
                held.append(a)
                continue
            now9 = time.time()
            pn9 = (win9 > 0 and not fb9 and not retire9 and a in self.cursor and now9 - float(self._vat.get(a, -1e18)) <= win9)
            if gate9 and not pn9 and not fb9 and bf_engine.HELIUS.room("head", proc=self.rpc.proc) < 1:
                defer9.add(a)
                held.append(a)
                failed_addr = True
                continue
            if pn9 and self.cursor.get(a) and not isinstance(self.cursor.get("_slot:" + a), int):
                self._cursor_slot_fill(a)
            hk9 = {"pn": pn9, "slot": self.cursor.get("_slot:" + a)} if not retire9 else {"only": "primary"}
            t_list[a] = now9
            try:
                kw9 = {"gate": (lambda: self.rpc.fill_room() > 0)} if fb9 and fb_pace else {}
                with (self.rpc.as_kind("fill" if fb9 else "head") if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                        (hint9(**hk9) if callable(hint9) else contextlib.nullcontext()):
                    rows = self.new_sigs(a, cutoff=(int(stake_reg[a].get("t0") or 0) if a in stake_reg else None), **kw9)
            except self.FillPaced as e:
                log.info("%s", e)
                self._fb_hold(a, None)
                held.append(a)
                failed_addr = True
                continue
            except self.SpoolPending as e:
                log.info("%s", e)
                self._fb_wait_note(a)
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
            if fb9 and fb_pace:
                left9 = self.rpc.fill_room() - fb_resv
                n9 = self._fb_left(a, rows, time.time())
                if not (left9 > 0 if slice_fb9 else self._fb_fits(n9, left9)):
                    log.info("%s 첫 백필 서명 %d건 — 오늘 남은 옛 기록 몫 %d 보다 커서 다음 차례(UTC 0시에 몰아서)", a[:8], n9, max(0, left9))
                    self._fb_est[a] = n9
                    self._fb_hold(a, n9)
                    held.append(a)
                    failed_addr = True
                    have9[a] = rows
                    continue
                if not slice_fb9:
                    fb_resv += n9
                self._fb_est.pop(a, None)
                if a in self._fb_waiting:
                    self.progress.update(f"sol:{a[:8]}", phase="parse", unit="tx", done=0, total=n9, note="옛 기록 받는 중")
            miss9 = self.cursor.get("_pnmiss:" + a)
            if isinstance(miss9, list) and miss9:
                seen9 = {r["signature"] for r in rows}
                rows = list(rows) + [dict(r, _miss=True) for r in miss9
                                     if isinstance(r, dict) and isinstance(r.get("signature"), str) and r["signature"] not in seen9]
            addr_sigs[a] = rows
            for r in rows:
                all_new.setdefault(r["signature"], a)
        if defer9 and time.time() - float(getattr(self, "_defer_log", 0) or 0) >= 1800:
            self._defer_log = time.time()
            log.info("헬리우스 새 거래 확인 몫 대기 — publicnode 창 밖 주소 %d개(오래 쉰 계단·받침 복구 등)는 다음 주기에(창 안 주소는 그대로 확인)", len(defer9))
        peek9 = {}
        self._hl_next = {}
        if self.live_first_h > 0 and rl_hits < RATE_LIMIT_MAX:
            for a in dict.fromkeys(addrs):
                if a in addr_sigs or a in self.cursor or a in stake_reg or a not in active_addrs:
                    continue
                if a in have9:
                    rows9 = have9[a]
                    live9 = self._live_part(a, rows9, time.time())
                    peek9[a] = [r for r in rows9 if r["signature"] in live9]
                    self._hl_next[a] = {"o": self._own_of(a), "sig": rows9[0]["signature"] if rows9 else "",
                                        "slot": rows9[0].get("slot") if rows9 else None}
                    continue
                try:
                    peek9[a] = self._live_peek(a, self.cutoff_ts, time.time())
                except Exception as e:
                    log.debug("%s 최근 서명 엿보기 실패(다음 주기 다시): %s", a[:8], e)
                time.sleep(pace)
        ordered = []
        seen = set()
        for a, rows in list(addr_sigs.items()) + list(peek9.items()):
            for r in reversed(rows):
                s = r["signature"]
                if s not in seen:
                    seen.add(s)
                    ordered.append(r)
        ordered.sort(key=lambda r: r.get("slot") or 0)
        now_l9 = time.time()
        live_s9 = set()
        for a, rows in addr_sigs.items():
            live_s9 |= self._live_part(a, rows, now_l9)
        for rows in peek9.values():
            live_s9 |= {r["signature"] for r in rows}
        live_rows9 = [r for r in ordered if r["signature"] in live_s9]
        old_rows9 = [r for r in ordered if r["signature"] not in live_s9]
        backlog9 = self.live_first_h > 0 and bool(old_rows9 or len(live_rows9) > self.live_first_n
                                                   or any(a not in self.cursor for a in list(addr_sigs) + list(peek9)))
        if backlog9:
            tops9 = {rows9[0]["signature"] for rows9 in list(addr_sigs.values()) + list(peek9.values()) if rows9}
            live_rows9.sort(key=lambda r: (r["signature"] not in tops9, -(r.get("slot") or 0)))
        ordered = live_rows9 + old_rows9
        re_sigs = {r["signature"] for a in repersp_addrs for r in list(addr_sigs.get(a, ())) + list(peek9.get(a, ()))
                   if r["signature"] in self.emitted and not ((a in fb_set and self._persp_done(a, r))
                                                               or (a in stake_reg and self._persp_done(a, r, stake=True)))}
        cut_all = min([self.cutoff_ts] + [int(v.get("t0") or 0) for v in stake_reg.values()]) if self.cutoff_ts else 0
        done_ok = True
        todo = [r["signature"] for r in ordered if (r["signature"] not in self.emitted or r["signature"] in re_sigs) and not (
            cut_all and isinstance(r.get("blockTime"), int) and r["blockTime"] < cut_all)]
        head_sigs9 = {r["signature"] for a9, rows9 in addr_sigs.items() if a9 not in fb_set for r in rows9}
        bt_of = {r["signature"]: r.get("blockTime") for r in ordered}
        fb_sigs9 = {r["signature"] for a9, rows9 in addr_sigs.items() if a9 in fb_set for r in rows9} - head_sigs9
        pre = {}
        pos = 0
        n_done = 0
        big = len(todo) > 50
        n_lt9 = sum(1 for s9 in todo if s9 in live_s9)
        t_det9 = time.time()
        sliced9 = False
        emit9 = set()
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
                old9 = pos >= n_lt9
                if self.old_slice > 0 and (old9 or backlog9) and time.time() - t_det9 >= self.old_slice:
                    sliced9 = True
                    break
                chunk = todo[pos:min(pos + self.parse_batch, len(todo) if old9 else n_lt9)]
                pos += len(chunk)
                k9 = "fill" if chunk and (old9 or self.live_first_h <= 0) and all(s9 in fb_sigs9 for s9 in chunk) else "head"
                if k9 == "fill" and fb_pace and slice_fb9 and self.rpc.fill_room() <= 0:
                    sliced9 = True
                    break
                tnow9 = time.time()
                ptx9 = (k9 == "head" and win9 > 0 and bool(chunk)
                        and all(isinstance(bt_of.get(s9), int) and tnow9 - bt_of[s9] <= win9 for s9 in chunk))
                with (self.rpc.as_kind(k9) if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                        (hint9(pn_tx=ptx9) if callable(hint9) else contextlib.nullcontext()):
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
                self._emit_seq += 1
                self._emit_cur[sig] = self._emit_seq
                emit9.add(sig)
                self._stake_note_tx(rec)
                if tb is not None:
                    for o9 in {rec.get("fee_payer")} | set(self.__dict__.get("_tier_signers", {}).pop(sig, None) or []):
                        tb.note_sent(o9, rec.get("ts"))
            except Exception as e:
                log.error("inbox append 실패 — 커서 미전진: %s", e)
                done_ok = False
                break
            n_done += 1
            if big and n_done % 50 == 0:
                self.progress.update("sol", phase="parse", unit="tx", done=n_done, total=len(todo))
                common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        if big or (self.progress.items.get("sol") or {}).get("phase") == "parse":
            self.progress.update("sol", phase="parse" if (not done_ok or sliced9) else "live", unit="tx", done=n_done,
                                 total=len(todo), flush=True)
        whole9 = done_ok and not sliced9
        unc9 = set()
        if addr_sigs or done_ok:
            for a, rows in addr_sigs.items():
                if not whole9 and not all(self._row_done(r, re_sigs, cut_all, emit9) for r in rows):
                    unc9.add(a)
                    if a not in self.cursor and a not in stake_reg:
                        self._fb_wait_note(a)
                    if a in fb_set:
                        self._fbw_note(a, rows, re_sigs, cut_all, emit9)
                    continue
                self.cursor.pop("_hl:" + a, None)
                self.cursor.pop("_fbw:" + a, None)
                self.__dict__.setdefault("_fbe", {}).pop(a, None)
                wait9 = self.cursor.pop("_fb_wait:" + a, None)
                if self.cursor.pop("_sigbf:" + a, None) is not None:
                    try:
                        os.remove(self._spool_path(a))
                    except OSError:
                        pass
                    self.progress.finish(f"sol:{a[:8]}", note=f"서명 {len(rows)}건 처리")
                    self._fb_waiting.discard(a)
                elif a in self._fb_waiting:
                    self._fb_waiting.discard(a)
                    self.progress.finish(f"sol:{a[:8]}", note=f"서명 {len(rows)}건 처리")
                self.cursor.pop("_pnmiss:" + a, None)
                rows = [r for r in rows if not r.get("_miss")]
                if a not in active_addrs and not isinstance(self.cursor.get("_pnv:" + a), dict):
                    self.cursor.pop(a, None)
                    self.cursor.pop("_slot:" + a, None)
                    self._vat.pop(a, None)
                    self.cursor.pop("_vat:" + a, None)
                    if wait9:
                        self.ata_owner.pop(a, None)
                    continue
                if a in t_list:
                    self._vat[a] = t_list[a]
                if not self.cursor.get(a) and "_cov_ts:" + a not in self.cursor:
                    self.cursor["_cov_ts:" + a] = int(self.cutoff_ts or 0)
                    if rows:
                        self.cursor["_cov_sig:" + a] = rows[-1]["signature"]
                if rows:
                    self._cursor_set(a, rows)
                else:
                    self.cursor.setdefault(a, "")
                if a in t_list:
                    self._vat_save(a)
            if full and whole9 and len(addr_sigs) == len(dict.fromkeys(addrs)):
                self.cursor["_synced_at"] = int(time.time())
        self._unc_prev = unc9 & active_addrs
        self._unc_ret = unc9 - active_addrs
        for a, nx9 in self._hl_next.items():
            if a not in self.cursor and all(self._row_done(r, re_sigs, cut_all, emit9) for r in peek9.get(a, ())):
                self.cursor["_hl:" + a] = nx9
                if a in fb_set and peek9.get(a):
                    self._fbw_note(a, [], re_sigs, cut_all, emit9, extra=[r["signature"] for r in peek9[a]])
        if not full and (failed_addr or not done_ok or sliced9):
            self.cursor.pop("_synced_at", None)
        if tb is not None:
            unq9 = (set(dict.fromkeys(addrs)) - set(addr_sigs) - defer9) | unc9
            failed_own = {o for o in own_set if o in unq9 or any(self.ata_owner.get(a) == o for a in unq9)}
            defer_own9 = {o for o in own_set if o in defer9 or any(self.ata_owner.get(a) == o for a in defer9)} - failed_own
            if not done_ok:
                failed_own |= set(own_set)
            scope_full9 = {o for o in own_set if full and o in full_set}
            ok9 = set(own_set) - failed_own - defer_own9
            fail_full9 = set(getattr(self, "_tier_fail_full", set())) & set(getattr(self, "_tier_fail", set()))
            self._tier_fail = (getattr(self, "_tier_fail", set()) - (ok9 & scope_full9) - (ok9 - fail_full9)) | failed_own
            self._tier_fail_full = (fail_full9 - (ok9 & scope_full9)) | (failed_own & scope_full9)
            now9 = int(time.time())
            for o in own_set - failed_own:
                if o not in addr_sigs or o in defer_own9:
                    continue
                if full and o in full_set:
                    tb.note_full(o, now9)
                    tb.note_baseline(o, 0, 0, now9)
                    tb.pairs[o]["atas"] = sorted(a for a, o9 in self.ata_owner.items() if o9 == o)
                else:
                    tb.pairs[o]["actAt"] = now9
            tb.save()
        if full and done_ok:
            for o in newp:
                if o in self.cursor and all(a9 in self.cursor for a9, o9 in self.ata_owner.items() if o9 == o):
                    self.cursor.pop("_persp:" + o, None)
        common.write_json_if_changed(self.meta_path, self.mint_meta)
        common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        common.atomic_write_json(self.cursor_path, self.cursor)
        if full and done_ok and not sliced9:
            self._pn_audit()
        self._health_cycle(full, addrs, addr_sigs, fail_list, done_ok, held)
        self._stake_cycle()
        if full and done_ok and not sliced9 and not fail_list:
            try:
                self._extend([a for a in dict.fromkeys(addrs) if a in active_addrs and a not in stake_reg])
            except Exception as e:
                log.info("과거 창 확장 예외(다음 전체 사이클): %s", e)

    EXT_BUDGET = 300

    def _extend(self, addrs: list):
        target = bf_engine.SINCE.target("sol")
        if not target:
            return
        pend = []
        for a in addrs:
            cov9 = self.cursor.get("_cov_ts:" + a)
            if self._first_synced(a) and (not isinstance(cov9, int) or cov9 > int(target)):
                pend.append(a)
        if not pend:
            return
        if callable(getattr(self.rpc, "fill_ok", None)) and not self.rpc.fill_ok():
            for a in pend:
                self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", paced_at=int(time.time()))
            return
        with (self.rpc.as_kind("fill") if callable(getattr(self.rpc, "as_kind", None)) else contextlib.nullcontext()), \
                (self.rpc.fill_scope() if callable(getattr(self.rpc, "fill_scope", None)) else contextlib.nullcontext()):
            self._extend_addrs(pend, target)

    _PROG_UNFIN = ("_sigbf:", "_fb_wait:", "_fbw:", "_hl:", "_sigx:")

    def prune_progress(self) -> int:
        known, unfin = set(self.owners), set()
        for k in list(self.cursor):
            if not isinstance(k, str) or not k:
                continue
            if not k.startswith("_"):
                known.add(k)
                continue
            p9, sep, a9 = k.partition(":")
            if sep and a9:
                known.add(a9)
                if p9 + ":" in self._PROG_UNFIN:
                    unfin.add(a9)
        settled = {a for a in known if a in self.cursor and a not in unfin}

        def pred(key, it):
            if not isinstance(it, dict):
                return False
            if it.get("phase") in ("done", "live"):
                return True
            parts = str(key).split(":")
            if len(parts) < 2 or parts[0] != "sol" or not parts[1]:
                return False
            m = [a for a in known if a.startswith(parts[1])]
            if not m:
                return True
            return len(parts) == 2 and all(a in settled for a in m)
        try:
            n = self.progress.prune(pred)
        except Exception as e:
            log.warning("지난 진행 표식 정리 건너뜀: %s", type(e).__name__)
            return 0
        if n:
            log.info("지난 진행 표식 %d개 정리(끝났거나 첫 동기화를 마친 주소 · 표시 전용)", n)
        return n

    def _first_synced(self, a: str) -> bool:
        return a in self.cursor or ("_cov_ts:" + a) in self.cursor

    def _ext_more(self, a: str) -> bool:
        fr9 = getattr(self.rpc, "fill_route", None)
        if callable(fr9):
            via9 = fr9()
            if via9 is not None:
                if callable(getattr(self.rpc, "set_fill_via", None)):
                    self.rpc.set_fill_via(via9)
                return True
        elif not callable(getattr(self.rpc, "fill_room", None)) or self.rpc.fill_room() > 0:
            return True
        self.progress.update(f"sol:{a[:8]}:extend", phase="extend", unit="tx", paced_at=int(time.time()))
        return False

    def _extend_addrs(self, addrs: list, target):
        deadline = time.time() + self.EXT_BUDGET
        for a in addrs:
            if time.time() > deadline:
                break
            if not self._first_synced(a):
                continue
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
            if not self._ext_more(a):
                break
            via9 = getattr(getattr(self.rpc, "_fill", None), "via", None)
            wait9 = self.__dict__.setdefault("_ext_hl_wait", set())
            if via9 == "archive" and a in wait9:
                continue
            if via9 != "archive":
                wait9.discard(a)
            try:
                sigs = self._sigs_spooled(a, ck, cutoff=int(target), tag="x", gate=lambda a=a: self._ext_more(a))
            except self.SpoolPending as e:
                log.info("확장 %s", e)
                if (not isinstance(e, self.FillPaced) and getattr(getattr(self.rpc, "_fill", None), "via", None) == "archive"
                        and getattr(self.rpc, "last_src", None) == "fallback"):
                    wait9.add(a)
                continue
            todo = [r["signature"] for r in reversed(sigs) if r["signature"] not in self.emitted]
            n_ok = 0
            for i in range(0, len(todo), max(1, self.parse_batch)):
                if time.time() > deadline or not self._ext_more(a):
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
            common.write_json_if_changed(self.emitted_path, sorted(self.emitted))
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
                if not isinstance(self.cursor.get("_sigbf:" + a), dict) and (self.progress.items.get(f"sol:{a[:8]}") or {}).get("phase") == "sigs":
                    self.progress.drop(f"sol:{a[:8]}")
                self.progress.finish(f"sol:{a[:8]}:extend", note=f"{len(todo)}건")
            common.atomic_write_json(self.cursor_path, self.cursor)

    def _cursor_slot_fill(self, a: str):
        rpc, sig = self.rpc, self.cursor.get(a)
        tried9 = self.__dict__.setdefault("_slot_try", {})
        if time.time() - tried9.get(a, 0) < 3600:
            return False
        tried9[a] = time.time()
        for u in (getattr(rpc, "archive_url", None), None if (rpc.primary_open() or rpc.hl_closed()) else rpc.url):
            if not u:
                continue
            try:
                with rpc.as_kind("head"):
                    r = rpc._call(u, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
                v = ((r or {}).get("value") or [None])[0] if isinstance(r, dict) else None
                sl = (v or {}).get("slot")
                if isinstance(sl, int) and not isinstance(sl, bool) and sl > 0:
                    self.cursor["_slot:" + a] = sl
                    return True
            except Exception:
                continue
        return False

    def _pn_lag_check(self):
        rpc = self.rpc
        hu = getattr(rpc, "head_url", None)
        if not hu or not callable(getattr(rpc, "pn_open", None)) or rpc.pn_open():
            return
        ref = rpc.url if not (rpc.primary_open() or rpc.hl_closed()) else getattr(rpc, "archive_url", None)
        if not ref:
            return
        try:
            pn = rpc._call(hu, "getSlot", [{"commitment": "finalized"}], timeout=rpc.head_timeout)
            if not isinstance(pn, int) or isinstance(pn, bool):
                raise RuntimeError("getSlot 형식")
        except Exception as e:
            rpc._pn_note(False, f"getSlot: {e}")
            return
        try:
            with rpc.as_kind("head"):
                rs = int(rpc._call(ref, "getSlot", [{"commitment": "finalized"}]))
        except Exception:
            return
        rpc.pn_lag = rs - int(pn)
        if rpc.pn_lag > rpc.head_lag_max:
            rpc.pn_fault(f"최신 슬롯이 {rpc.pn_lag}슬롯 뒤(기준 {common.redact_urls(ref)})", HEAD_TRIP_BASE * 5)
        else:
            rpc._pn_note(True)

    PN_SEEN_LAG = 120

    def _pn_audit(self):
        rpc = self.rpc
        n_aud = int(getattr(rpc, "head_audit_n", 0) or 0)
        if n_aud <= 0 or not callable(getattr(rpc, "hint", None)):
            return
        if rpc.primary_open() or rpc.hl_closed():
            return
        ents = {k[5:]: v for k, v in self.cursor.items() if k.startswith("_pnv:") and isinstance(v, dict)}
        cands = [x for x in ents if x in self.cursor and not self.cursor.get("_pnmiss:" + x)]
        if not cands:
            return
        first = sorted(x for x in cands if x in self._retiring)
        rest = sorted(x for x in cands if x not in self._retiring)
        picked = first[:n_aud]
        k_rest = min(len(rest), n_aud - len(picked))
        picked += [rest[(self._audit_i + k) % len(rest)] for k in range(k_rest)]
        self._audit_i += k_rest
        stake9 = self.stake_reg()
        fault = 0
        for a in picked:
            e = ents[a]
            cut = int(stake9[a].get("t0") or 0) if a in stake9 else int(self.cutoff_ts or 0)
            chk = e.get("chk") if isinstance(e.get("chk"), dict) else None
            if chk is None:
                ts9 = self.cursor.get("_slot:" + a)
                chk = {"at": time.time(), "top": self.cursor.get(a) or "", "tslot": ts9 if isinstance(ts9, int) and not isinstance(ts9, bool) else None,
                       "pn": float(e.get("pn") or 0), "before": None}
            anc = e.get("sig") or ""
            miss = list(self.cursor.get("_pnmiss:" + a) or [])
            have = {m.get("signature") for m in miss if isinstance(m, dict)}
            reached, pages, bad = False, 0, 0
            try:
                while pages < HEAD_AUDIT_PAGES:
                    opt = {"limit": SIG_PAGE, "commitment": "finalized"}
                    if anc:
                        opt["until"] = anc
                    if chk.get("before"):
                        opt["before"] = chk["before"]
                    with rpc.as_kind("head"), rpc.hint(only="primary"):
                        res = rpc.call("getSignaturesForAddress", [a, opt])
                    if not isinstance(res, list):
                        raise RuntimeError("형식")
                    pages += 1
                    past_cut = False
                    for r in res:
                        if not isinstance(r, dict) or not isinstance(r.get("signature"), str):
                            continue
                        s9, sl9, bt9 = r["signature"], r.get("slot"), r.get("blockTime")
                        if cut and isinstance(bt9, int) and bt9 < cut:
                            past_cut = True
                            continue
                        if s9 in self.emitted or s9 in have:
                            continue
                        due9 = ((chk["tslot"] is not None and isinstance(sl9, int) and sl9 <= chk["tslot"]) or s9 == chk["top"]
                                or (isinstance(bt9, int) and chk["pn"] > 0 and bt9 <= chk["pn"] - self.PN_SEEN_LAG))
                        if due9:
                            miss.append({"signature": s9, "slot": sl9, "blockTime": bt9})
                            have.add(s9)
                            bad += 1
                    if res:
                        chk["before"] = res[-1]["signature"]
                    if len(res) < SIG_PAGE or past_cut:
                        reached = True
                        break
            except Exception as e9:
                log.debug("publicnode 대조 %s 실패(다음 차례에 이어서): %s", a[:8], e9)
            if miss:
                self.cursor["_pnmiss:" + a] = miss
            if bad:
                fault += bad
                rpc.pn_n["audit_miss"] += 1
                log.error("★publicnode 대조: %s 받았어야 할 서명 %d건을 못 받았음(공개 노드 목록 누락) — 다음 사이클에 헬리우스로 받음★", a[:8], bad)
            if reached:
                rpc.pn_n["audit_ok"] += 1
                if chk["top"]:
                    e["sig"], e["slot"] = chk["top"], chk["tslot"]
                e.pop("chk", None)
                if float(e.get("pn") or 0) < float(chk["at"]) and not miss:
                    self.cursor.pop("_pnv:" + a, None)
            else:
                e["chk"] = chk
        common.atomic_write_json(self.cursor_path, self.cursor)
        if fault:
            rpc.pn_fault(f"대조 누락 {fault}건", HEAD_AUDIT_TRIP_SEC)

    def _health_cycle(self, full, addrs, addr_sigs, fail_list, done_ok, held=()):
        hb = bf_engine.health("sol")
        n_addr = len(dict.fromkeys(addrs)) - len(set(held))
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
                     spooling=[k[7:15] for k in self.cursor if k.startswith("_sigbf:")],
                     helius_used=bf_engine.HELIUS.used()[0] if getattr(self.rpc, "metered", False) else None,
                     helius_budget=bf_engine.HELIUS.budget if getattr(self.rpc, "metered", False) else None,
                     helius_daycap_until=None,
                     fill_wait=len(set(held)))
        if callable(getattr(self.rpc, "pn_state", None)):
            pn9 = self.rpc.pn_state()
            facts.update(head_rpc=pn9["host"], head_rpc_on=pn9["on"], head_rpc_ok=pn9["healthy"],
                         head_rpc_rate=(round(pn9["rate"], 4) if pn9["rate"] is not None else None), head_rpc_n=pn9["n"],
                         head_rpc_open_until=int(pn9["open_until"]) if pn9["open_until"] else None, head_rpc_why=pn9["why"], head_rpc_lag=pn9["lag"],
                         head_rpc_audit=dict(self.rpc.pn_n),
                         archive_rpc=common.redact_urls(self.rpc.archive_url) if getattr(self.rpc, "archive_url", None) else None,
                         helius_closed_until=int(self.rpc.hl_closed_until) if self.rpc.hl_closed() else None,
                         pn_unverified=sum(1 for k9 in self.cursor if k9.startswith("_pnv:")),
                         helius_head_min=round(float(getattr(bf_engine.HELIUS, "head_min", 0.1)), 4) if getattr(self.rpc, "metered", False) else None)
            if self.rpc.hl_closed() and pn9["on"]:
                facts["current_source"] = pn9["host"]
            if self.rpc.hl_closed():
                facts["helius_daycap_until"] = int(self.rpc.hl_closed_until)
                facts["helius_continue"] = bool(self.rpc.can_continue_capped())
        if ok:
            hb.ok("sol", "sol_rpc", **facts)
        else:
            hb.fail("sol", RuntimeError("; ".join(f"{a}: {e}" for a, e in fail_list[:3]) or
                                        ("tx 파싱/방출 실패" if not done_ok else "부분 조회")), "sol_rpc", **facts)
        hb.flush()


def _pn_ok(rpc) -> bool:
    try:
        return bool(callable(getattr(rpc, "pn_ok", None)) and rpc.pn_ok())
    except Exception:
        return False


def rest_if_capped(w) -> bool:
    if not w.rpc.day_capped():
        if callable(getattr(w.rpc, "hl_open", None)) and getattr(w.rpc, "hl_closed_until", 0):
            w.rpc.hl_open()
        return True
    until9 = (int(time.time()) // 86400 + 1) * 86400 + 60
    cont9 = callable(getattr(w.rpc, "can_continue_capped", None)) and w.rpc.can_continue_capped()
    hb9 = bf_engine.health("sol")
    hb9.facts("sol", helius_daycap_until=until9, helius_used=bf_engine.HELIUS.used()[0], helius_budget=bf_engine.HELIUS.budget,
              helius_continue=bool(cont9))
    hb9.flush()
    if cont9:
        w.rpc.hl_close_until(until9)
        if time.time() - getattr(w, "_cap_log", 0) >= 1800:
            w._cap_log = time.time()
            log.warning("헬리우스 하루 예산 %d 크레딧 소진 — %s 까지 헬리우스 없이 이어 감(새 거래 확인 = 공개 노드 · 옛 기록 = 아카이브 공개 노드)",
                        bf_engine.HELIUS.budget, time.strftime("%H:%M", time.localtime(until9)))
        return True
    if time.time() - getattr(w, "_cap_log", 0) >= 1800:
        w._cap_log = time.time()
        log.warning("헬리우스 하루 예산 %d 크레딧 소진 — %s 까지 솔라나 수집 쉼(기록은 그대로, 풀리면 커서부터 이어 받음)", bf_engine.HELIUS.budget,
                    time.strftime("%H:%M", time.localtime(until9)))
    return False


def rest_if_paced(w) -> bool:
    if not getattr(w.rpc, "metered", False):
        return True
    if callable(getattr(w.rpc, "hl_closed", None)) and w.rpc.hl_closed():
        return True
    m9 = bf_engine.HELIUS
    if not getattr(m9, "fill_first", False) or m9.burst >= 1.0:
        return True
    full9 = w.full_due()
    pn9 = _pn_ok(w.rpc)
    costs9 = getattr(w, "_hl_cost", None) or {}

    def _need(k):
        if pn9:
            if k == "own":
                return 0
            c = costs9.get(k + "_pn")
            c = w.hl_full_est() if c is None else int(c)
            return 0 if c <= 0 else max(1, min(c, m9.keep_credits()))
        c = costs9.get(k)
        c = 1 if c is None else int(c)
        if c <= 0:
            return 1
        return max(1, min(c, m9.keep_credits()))
    need = _need("full" if full9 else "own")
    room = m9.room("head", proc=w.rpc.proc)
    if need <= 0 or room >= need:
        return True
    if full9 and _need("own") <= 0:
        w._own_only = True
        return True
    now9 = int(time.time())
    hb9 = bf_engine.health("sol")
    hb9.facts("sol", paced_at=now9, helius_used=m9.used()[0], helius_budget=m9.budget)
    hb9.flush()
    if time.time() - getattr(w, "_paced_log", 0) >= 1800:
        w._paced_log = time.time()
        log.info("헬리우스 새 거래 확인 몫 대기(옛 기록 먼저 채우는 중이면 하루 예산 %.0f%% 안에서) — %s 사이클 %d 크레딧 · 지금 여유 %d(기록은 그대로, 다음 주기에 이어 받음)",
                 float(getattr(m9, "head_min", 0.1)) * 100, "전체" if full9 else "소유자", need, room)
    return False


def _floor_tick(w):
    rpc = w.rpc
    m9 = bf_engine.HELIUS
    if not getattr(rpc, "metered", False) or not getattr(m9, "fill_first", False) or not getattr(rpc, "head_url", None):
        return
    cfg9 = getattr(w, "cfg", None) or {}
    hi9 = bf_engine.helius_head_min(cfg9)
    now9 = time.time()
    if rpc.pn_state()["healthy"]:
        with m9.lock:
            hu9 = int(m9.st.get("nh") or 0) + int(m9.st.get("others_h") or 0)
            yd9 = m9.st.get("yday_h")
        hm9 = bf_engine.helius_head_min_pn(cfg9, hu9, yd9, now9, m9.budget)
    else:
        hm9 = hi9
    with m9.lock:
        m9.hm_pub = True
        m9.head_min = hm9


def run_cycle(w) -> bool:
    if not rest_if_capped(w):
        return False
    try:
        _floor_tick(w)
    except Exception as e:
        log.debug("실시간 하한 조정 실패: %s", e)
    try:
        paced_ok = rest_if_paced(w)
    except Exception as e:
        log.warning("헬리우스 새 거래 확인 몫 판정 실패(이번 사이클은 그대로 돌림): %s", str(e)[:160])
        paced_ok = True
    if not paced_ok:
        return False
    full9 = w.full_due() and not getattr(w, "_own_only", False)
    m9 = bf_engine.HELIUS
    d0, h0 = m9.st.get("day"), int(m9.st.get("nh") or 0)
    pn0 = _pn_ok(w.rpc)
    g0 = int(getattr(w.rpc, "_pn_gen", 0) or 0)
    try:
        w.cycle()
        tsfix.repair("sol", lambda s9: tsfix.block_ts(w, s9, fn=w._block_time), w.writer)
    except Exception as e:
        n9 = bf_engine.health("sol").fail("sol", e, "sol_rpc")
        bf_engine.health("sol").flush()
        lv = bf_engine.LogDebounce.level(n9)
        if lv:
            getattr(log, lv)("cycle 실패 %d회 연속(다음 주기 재시도): %s", n9, e)
    finally:
        if getattr(w.rpc, "metered", False) and m9.st.get("day") == d0 and d0 is not None:
            pn1 = _pn_ok(w.rpc)
            if pn1 == pn0 and int(getattr(w.rpc, "_pn_gen", 0) or 0) == g0:
                w.__dict__.setdefault("_hl_cost", {})[("full" if full9 else "own") + ("_pn" if pn0 else "")] = max(0, int(m9.st.get("nh") or 0) - h0)
    return True


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    bf_engine.configure(cfg)
    addr_tier.ACTIVE_PROC = True
    bf_engine.es_budget_install_sigterm()
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "sol"]
    if not wallets:
        raise SystemExit("추적할 SOL 지갑이 없음 — config.wallets 확인")
    poll = int(cfg.get("sol", {}).get("poll_sec", 60))
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "sol"))
    w = SolWatcher(cfg, wallets, writer)
    w.prune_progress()
    log.info("가동: %d지갑, %d초 주기", len(wallets), poll)
    while True:
        t0 = time.time()
        run_cycle(w)
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
