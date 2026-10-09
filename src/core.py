"""Ledger core: consumes collected events and writes double-entry postings."""
import bisect
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from decimal import Decimal, localcontext, InvalidOperation, ROUND_CEILING, ROUND_HALF_EVEN

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import db as dbm
import pricing
import acct_norm
import spamguard
import recon
import lpdec
import lpsol
import bf_engine
import ledger_backup
import ops_requests
from inbox import SegmentReader

log = common.setup_logging("tj-core")


class MissingTs(ValueError):
    pass

CLASSIFIER_VER = 5
DM_PATH = os.path.join(common.STATE_DIR, "pending_dm.jsonl")
DM_RECENT_SEC = 6 * 3600
PRICE_BATCH = 40
PRICE_IDLE_SEC = 20
PRICE_BACKOFF_MIN = 22
PRICE_BACKOFF_MAX = 86400
PRICE_BULK_BATCH = 400
PRICE_BULK_BUDGET = 12.0
PRICE_PREFETCH_CALLS = 40
KRW_FILL_SEC = 60
KRW_FILL_CALLS = 60


def dm(kind: str, text: str, payload=None, event_ts=None):
    if event_ts is not None and time.time() - event_ts > DM_RECENT_SEC:
        log.info("DM스킵(과거분)[%s] %s", kind, text)
        return
    fd = os.open(DM_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
    except OSError:
        pass
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": kind, "text": text,
                            "payload": payload}, ensure_ascii=False) + "\n")
    log.info("DM대기[%s] %s", kind, text)


class Core:
    LEDGER_GEN = 2

    def __init__(self, cfg: dict):
        self.cfg = cfg
        if dbm.SCHEMA_VERSION != self.LEDGER_GEN:
            raise SystemExit(f"★db.py 세대({dbm.SCHEMA_VERSION}) ≠ core 세대({self.LEDGER_GEN}) — 배포 파일 혼합, 기동 금지★")
        if not os.path.exists(common.DB_PATH):
            if os.environ.get("TJ_ALLOW_NEW_LEDGER") != "1":
                raise SystemExit(f"★원장 파일 없음: {common.DB_PATH} — 백업에서 되돌리기: python3 tools/ledger_restore.py list"
                                 f" (정말 새 원장이면 TJ_ALLOW_NEW_LEDGER=1 명시)★")
        else:
            _ro9 = None
            for _uri9 in (common.sqlite_ro_uri(common.DB_PATH), common.sqlite_ro_uri(common.DB_PATH, immutable=True), None):
                try:
                    _ro9 = (sqlite3.connect(_uri9, uri=True, timeout=10) if _uri9
                            else sqlite3.connect(common.DB_PATH, timeout=10))
                    _ro9.execute("SELECT 1").fetchone()
                    break
                except sqlite3.OperationalError:
                    if _ro9 is not None:
                        _ro9.close()
                    _ro9 = None
            if _ro9 is None:
                raise SystemExit(f"★원장 열기 실패(세대 검사 불가): {common.DB_PATH}★")
            try:
                _has = _ro9.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
                _v9 = _ro9.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone() if _has else None
            finally:
                _ro9.close()
            if _v9 is None and os.environ.get("TJ_ALLOW_NEW_LEDGER") != "1":
                raise SystemExit("★원장에 schema_version 없음 — 세대 미상 DB 로 기동 금지(TJ_ALLOW_NEW_LEDGER=1 로만 초기화)★")
            if _v9 is not None and int(_v9[0]) != self.LEDGER_GEN:
                raise SystemExit(f"★DB 세대({_v9[0]}) ≠ core 세대({self.LEDGER_GEN}) — canonical 마이그레이션"
                                 f"({self._cutover_hint()}) 없이 이 코드로 기동 금지★")
        self.conn = dbm.open_db(common.DB_PATH)
        if dbm.SCHEMA_VERSION != self.LEDGER_GEN:
            raise SystemExit(f"★db.py 세대({dbm.SCHEMA_VERSION}) ≠ core 세대({self.LEDGER_GEN}) — 배포 파일 혼합, 기동 금지★")
        ver = self.conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        if ver is None or int(ver["v"]) != self.LEDGER_GEN:
            raise SystemExit(f"★DB 세대({ver['v'] if ver else None}) ≠ core 세대({self.LEDGER_GEN}) — canonical 마이그레이션"
                             f"({self._cutover_hint()}) 없이 이 코드로 기동 금지★")
        self.conn.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('exf_wd_fee_since', ?)", (str(int(time.time())),))
        self.conn.commit()
        self.wd_fee_since = int(self.conn.execute("SELECT v FROM meta WHERE k='exf_wd_fee_since'").fetchone()["v"])
        self.native_sym = cfg.get("native_symbol", {})
        self.my_wallets = {}
        self.sol_wallets = set()
        now = int(time.time())
        for w in cfg["wallets"]:
            wtype = w.get("type", "evm")
            if wtype == "sol":
                self.sol_wallets.add(w["address"])
                self.conn.execute(
                    "INSERT OR IGNORE INTO wallets (chain, address, label, added_at) VALUES (?,?,?,?)",
                    ("sol", w["address"], w.get("label"), now))
                continue
            a = w["address"].lower()
            self.my_wallets.setdefault(w["chain"], set()).add(a)
            self.conn.execute(
                "INSERT OR IGNORE INTO wallets (chain, address, label, added_at) VALUES (?,?,?,?)",
                (w["chain"], a, w.get("label"), now))
        for w in cfg.get("_disabled_wallets") or []:
            if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain") and str(w.get("address") or "").startswith("0x"):
                self.my_wallets.setdefault(w["chain"], set()).add(str(w["address"]).lower())
        self.wrapped = {k.lower(): v.lower() for k, v in cfg.get("wrapped_native", {}).items()}
        self.bridges = self._load_seed("bridge_contracts.json")
        self.lp_mgrs = lpdec.lp_managers(common.BASE_DIR)
        self._load_exchange_addrs(cfg)
        self._dec_startup()
        self.conn.commit()
        self.reader = SegmentReader(os.path.join(common.INBOX_DIR, "evm"))
        self.sol_reader = SegmentReader(os.path.join(common.INBOX_DIR, "sol"))
        self.bsc_reader = SegmentReader(os.path.join(common.INBOX_DIR, "bsc"))
        self.ex_reader = SegmentReader(os.path.join(common.INBOX_DIR, "ex"))
        self.px = pricing.PxCache(os.path.join(common.STATE_DIR, "px_cache_core.json"), track_legacy=True)
        self._last_price_pass = 0.0
        self._px_skip = (None, "[]")
        self._last_recon = 0.0
        self.recon_months = 0.0 if cfg.get("backfill_full_history") \
            else float(cfg.get("backfill_months") or 0)
        self._last_ext_check = 0.0

    def _win_t0(self, ref_ts=None, section=None) -> int:
        if self.recon_months <= 0:
            return 0
        ref = time.time() if ref_ts is None else float(ref_ts)
        t = int(ref - self.recon_months * 30 * 86400)
        vals = [v for v in (bf_engine.SINCE.target(None), bf_engine.SINCE.target(section) if section else None) if v]
        return int(min([t] + vals))

    def _load_seed(self, name: str) -> set:
        data = common.seed_json(name, [], base_dir=common.BASE_DIR, strict=True)
        return {a.lower() for a in data}

    def _load_exchange_addrs(self, cfg: dict):
        for ex in cfg.get("exchange_addresses", []):
            addr = ex["address"] if ex["chain"] == "sol" else ex["address"].lower()
            self.conn.execute(
                "INSERT OR IGNORE INTO exchange_addresses (exchange, chain, address, currency, memo, sync_state)"
                " VALUES (?,?,?,?,?,'manual')",
                (ex["exchange"], ex["chain"], addr, ex.get("currency"), ex.get("memo")))

    def _ex_addr_set(self, chain: str) -> set:
        rows = self.conn.execute(
            "SELECT address FROM exchange_addresses WHERE chain=?", (chain,)).fetchall()
        return {r["address"] for r in rows}

    DEC_ISSUES_PATH = os.path.join(common.STATE_DIR, "asset_decimals_issues.json")

    def _meta_dec(self, chain, ca):
        if not chain or not ca:
            return None
        name = "bsc_token_meta.json" if chain == "bsc" else f"rpc_token_meta_{chain}.json"
        p = os.path.join(common.STATE_DIR, name)
        cache = self.__dict__.setdefault("_meta_dec_cache", {})
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return None
        ent = cache.get(name)
        if not ent or ent[0] != mt:
            raw = common.read_json(p, {}) or {}
            m9 = {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    v = v[1] if isinstance(v, (list, tuple)) and len(v) >= 2 else v
                    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 77:
                        m9[str(k).lower()] = v
            ent = cache[name] = (mt, m9)
        return ent[1].get(str(ca).lower())

    def _dec_issue(self, aid: int, kind: str, stored, seen) -> None:
        seen_k = (int(aid), kind, seen)
        logged = self.__dict__.setdefault("_dec_issue_seen", set())
        if kind == "pending":
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
        if seen_k in logged:
            return
        logged.add(seen_k)
        r = self.conn.execute("SELECT chain, address, symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        log.warning("자산 decimals %s: #%s %s %s 저장=%s 관측=%s%s", kind, aid, (r["chain"] if r else "?"), (r["symbol"] if r else "?"), stored, seen,
                    " — 이미 기장된 자산이라 다음 재구축에서 채움" if kind == "pending" else " — 덮지 않음(확인 필요)")
        try:
            d = common.read_json(self.DEC_ISSUES_PATH, {}) or {}
            it = d.setdefault("items", {})
            prev9 = it.get(str(aid)) if isinstance(it.get(str(aid)), dict) else {}
            if kind == "conflict" and prev9.get("kind") == "resolve" and prev9.get("stored") == stored and prev9.get("seen") == seen:
                return
            it[str(aid)] = {"kind": kind, "chain": r["chain"] if r else None, "address": r["address"] if r else None,
                            "symbol": r["symbol"] if r else None, "stored": stored, "seen": seen, "ts": int(time.time())}
            d["ts"] = int(time.time())
            common.atomic_write_json(self.DEC_ISSUES_PATH, d)
        except (OSError, ValueError, TypeError):
            pass

    def _dec_startup(self) -> None:
        self._dec_issues_prune()
        try:
            rows = self.conn.execute("SELECT asset_id, chain, address, decimals FROM assets WHERE kind='token' AND address IS NOT NULL").fetchall()
        except sqlite3.Error:
            return
        cand = {}
        for r in rows:
            m9 = self._meta_dec(r["chain"], r["address"])
            if m9 is None:
                continue
            if r["decimals"] is None:
                cand[int(r["asset_id"])] = m9
            elif int(r["decimals"]) != m9:
                self._dec_issue(int(r["asset_id"]), "conflict", int(r["decimals"]), m9)
        if not cand:
            return
        posted = set()
        ids = list(cand)
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            posted |= {int(x[0]) for x in self.conn.execute(
                "SELECT DISTINCT asset_id FROM postings WHERE asset_id IN (%s)" % ",".join("?" * len(ch)), ch).fetchall()}
        for aid, m9 in sorted(cand.items()):
            if aid in posted and m9 != 18:
                self._dec_issue(aid, "pending", None, m9)
            else:
                self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=?", (m9, aid))

    def _dec_issues_prune(self) -> None:
        try:
            d = common.read_json(self.DEC_ISSUES_PATH, None)
            if not isinstance(d, dict) or not isinstance(d.get("items"), dict):
                return
            keep = {}
            for k, it in d["items"].items():
                r = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (int(k),)).fetchone()
                if r is None or (r["decimals"] is not None and it.get("seen") is not None and int(r["decimals"]) == int(it["seen"])):
                    continue
                keep[k] = it
            if len(keep) != len(d["items"]):
                d["items"], d["ts"] = keep, int(time.time())
                common.atomic_write_json(self.DEC_ISSUES_PATH, d)
            if not any((it or {}).get("kind") in ("pending", "resolve") for it in keep.values()):
                self.conn.execute("DELETE FROM meta WHERE k='ext_prewindow:decimals_fix'")
            else:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pass

    def _dec_pending_pairs(self) -> set:
        out = set()
        d = common.read_json(self.DEC_ISSUES_PATH, None)
        if not isinstance(d, dict):
            return out
        for k, it in (d.get("items") or {}).items():
            if (it or {}).get("kind") not in ("pending", "resolve"):
                continue
            try:
                for g, loc in self.conn.execute("SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                                " WHERE p.asset_id=?", (int(k),)).fetchall():
                    if g is not None:
                        out.add((int(g), loc))
            except (sqlite3.Error, ValueError):
                continue
        return out

    DEC_REQ_PATH = os.path.join(common.STATE_DIR, "decimals_resolve_request.json")
    DEC_RES_PATH = os.path.join(common.STATE_DIR, "decimals_resolve_result.json")

    def decimals_resolve_pass(self) -> int:
        req = common.read_control_json(self.DEC_REQ_PATH, None)
        if req is None:
            return 0
        try:
            os.remove(self.DEC_REQ_PATH)
        except OSError:
            pass
        items = req.get("items") if isinstance(req, dict) and isinstance(req.get("items"), dict) else {}
        res = common.read_json(self.DEC_RES_PATH, {}) or {}
        res = res if isinstance(res, dict) else {}
        d = common.read_json(self.DEC_ISSUES_PATH, {}) or {}
        its = d.setdefault("items", {}) if isinstance(d, dict) else {}
        n = 0
        for k, v in items.items():
            try:
                aid, stored, seen = int(k), (v or {}).get("stored"), (v or {}).get("seen")
            except (TypeError, ValueError, AttributeError):
                continue
            err = ""
            it = its.get(str(aid)) if isinstance(its.get(str(aid)), dict) else None
            if any(isinstance(x, bool) or not isinstance(x, int) for x in (stored, seen)) or not 0 <= seen <= 77:
                err = "형식 오류"
            elif not it or it.get("kind") != "conflict" or it.get("stored") != stored or it.get("seen") != seen:
                err = "지금 '자리수 다름' 항목과 다름"
            else:
                r = self.conn.execute("SELECT decimals, chain, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                m9 = self._meta_dec(r["chain"], r["address"]) if r else None
                if r is None or r["decimals"] is None or int(r["decimals"]) != stored:
                    err = "원장 저장값이 요청과 다름"
                elif m9 is not None and m9 != seen:
                    err = f"수집기 관측값이 바뀜({m9})"
            if err:
                res[str(aid)] = {"ok": False, "err": err, "ts": int(time.time())}
                log.warning("자리수 해결 요청 거절 #%s: %s", aid, err)
                continue
            it.update(kind="resolve", req_at=int(time.time()), by=str((v or {}).get("by") or "")[:40])
            res[str(aid)] = {"ok": True, "ts": int(time.time())}
            n += 1
        if n:
            d["ts"] = int(time.time())
            common.atomic_write_json(self.DEC_ISSUES_PATH, d)
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
            self.conn.commit()
            log.warning("자리수 해결 요청 %d건 접수 — 다음 자동 재구축에서 관측값으로 다시 기장(손익 게이트 그대로)", n)
        try:
            common.atomic_write_json(self.DEC_RES_PATH, res)
        except OSError:
            pass
        return n

    def _asset_has_postings(self, aid: int) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM postings WHERE asset_id=? LIMIT 1", (aid,)).fetchone())

    def asset_id(self, kind: str, chain, address, symbol=None, decimals=None) -> int:
        addr = (address.lower() if chain != "sol" else address) if address else None
        row = self.conn.execute(
            "SELECT asset_id, symbol, decimals FROM assets WHERE kind=? AND chain IS ? AND address IS ?",
            (kind, chain, addr)).fetchone()
        if row:
            if symbol and not row["symbol"]:
                self.conn.execute("UPDATE assets SET symbol=? WHERE asset_id=?",
                                  (symbol, row["asset_id"]))
            if decimals is not None and kind == "token":
                st9 = row["decimals"]
                if st9 is None:
                    if int(decimals) != 18 and self._asset_has_postings(row["asset_id"]):
                        self._dec_issue(row["asset_id"], "pending", None, int(decimals))
                    else:
                        self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=?", (int(decimals), row["asset_id"]))
                elif int(st9) != int(decimals):
                    self._dec_issue(row["asset_id"], "conflict", int(st9), int(decimals))
            return row["asset_id"]
        cur = self.conn.execute(
            "INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed) VALUES (?,?,?,?,?,?)",
            (kind, chain, addr, symbol, decimals,
             1 if kind == "native" else 0))
        return cur.lastrowid

    def is_confirmed(self, aid: int) -> bool:
        r = self.conn.execute("SELECT confirmed FROM assets WHERE asset_id=?", (aid,)).fetchone()
        return bool(r and r["confirmed"])

    @staticmethod
    def op_deposit_mint(tx: dict):
        if tx.get("type") != 126:
            return 0, None
        m = tx.get("op_mint")
        if m is None:
            m = tx.get("value")
        try:
            m = int(m or 0)
        except (TypeError, ValueError):
            m = 0
        frm = tx.get("from")
        if isinstance(frm, dict):
            frm = frm.get("hash")
        return m, (frm or "").lower()

    def deltas(self, chain: str, snap: dict):
        mine = self.my_wallets.get(chain, set())
        tx = snap["tx"]
        perw = {}
        counterparties = set()

        def addr(x):
            if isinstance(x, dict):
                return (x.get("hash") or "").lower()
            return (x or "").lower()

        def add(w, aid, v):
            perw[(w, aid)] = perw.get((w, aid), 0) + v

        failed = (tx.get("status") != "ok")
        frm, to = addr(tx.get("from")), addr(tx.get("to"))
        is_contract_call = bool(tx.get("raw_input") and tx.get("raw_input") != "0x") or \
            bool((tx.get("to") or {}).get("is_contract") if isinstance(tx.get("to"), dict) else False)
        gas = 0
        gas_wallet = None
        if frm in mine:
            fee = tx.get("fee") or {}
            try:
                gas = int(fee.get("value") or 0)
            except (TypeError, ValueError):
                gas = 0
            gas_wallet = frm
        native_aid = self.asset_id("native", chain, None,
                                   symbol=self.native_sym.get(chain, chain.upper()),
                                   decimals=9 if chain == "sol" else 18)
        if not failed:
            try:
                val = int(tx.get("value") or 0)
            except (TypeError, ValueError):
                val = 0
            if val:
                if frm in mine:
                    add(frm, native_aid, -val)
                    counterparties.add(to)
                if to in mine:
                    add(to, native_aid, val)
                    counterparties.add(frm)
            for it in snap.get("internal", []):
                if it.get("success") is False or it.get("error"):
                    continue
                if str(it.get("type") or "").lower() in ("delegatecall", "staticcall", "callcode"):
                    continue
                f2, t2 = addr(it.get("from")), addr(it.get("to"))
                try:
                    v2 = int((it.get("value") or 0))
                except (TypeError, ValueError):
                    v2 = 0
                if not v2:
                    continue
                if f2 in mine:
                    add(f2, native_aid, -v2)
                    counterparties.add(t2)
                if t2 in mine:
                    add(t2, native_aid, v2)
                    counterparties.add(f2)
            for tt in snap.get("token_transfers", []):
                f3, t3 = addr(tt.get("from")), addr(tt.get("to"))
                tok = tt.get("token") or {}
                if (tok.get("type") or "ERC-20") != "ERC-20":
                    continue
                ca = tok.get("address") or tok.get("address_hash")
                if not ca:
                    continue
                total = tt.get("total") or {}
                try:
                    v3 = int(total.get("value") or 0)
                except (TypeError, ValueError):
                    continue
                if not v3 or (f3 not in mine and t3 not in mine):
                    continue
                try:
                    dec = None if tok.get("decimals") is None else int(tok.get("decimals"))
                except (TypeError, ValueError):
                    dec = None
                if dec is None:
                    dec = self._meta_dec(chain, ca)
                aid = self.asset_id("token", chain, ca,
                                    symbol=tok.get("symbol"), decimals=dec)
                if f3 in mine:
                    add(f3, aid, -v3)
                    counterparties.add(t3)
                if t3 in mine:
                    add(t3, aid, v3)
                    counterparties.add(f3)
        mint, mint_to = self.op_deposit_mint(tx)
        if mint and mint_to in mine:
            add(mint_to, native_aid, mint)
        ts = tx.get("timestamp")
        if isinstance(ts, str):
            ts = common.iso_epoch(ts)
        if ts is None or (isinstance(ts, (int, float)) and ts <= 0):
            log.warning("시각 없는 tx 거부: %s %s timestamp=%r", chain, (tx.get("hash") or "?")[:14], tx.get("timestamp"))
            raise MissingTs(f"{chain} tx 시각 없음: {tx.get('timestamp')!r}")
        counterparties.discard("")
        external_cps = counterparties - mine
        only_mine = bool(counterparties) and not external_cps
        return (perw, external_cps, gas, gas_wallet, int(ts), failed, is_contract_call,
                frm, to, only_mine)

    @staticmethod
    def _zk_norm(chain: str, snap: dict) -> dict:
        zk = common.ZK_STACK.get(chain)
        if not zk or not isinstance(snap, dict) or snap.get("internal_note") == "zk_base_token" or not snap.get("tx"):
            return snap
        base, boot = zk

        def addr(x):
            return ((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def ival(v):
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0
        tx = snap["tx"]
        f_tx = addr(tx.get("from"))
        t_top = addr(tx.get("to")) or addr(tx.get("created_contract"))
        v_top = ival(tx.get("value"))
        tts, nat = [], []
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
            if ca == base and (tok.get("type") or "ERC-20") == "ERC-20":
                nat.append((addr(tt.get("from")), addr(tt.get("to")), ival((tt.get("total") or {}).get("value"))))
            else:
                tts.append(tt)
        fee = None
        legs = []
        if nat:
            paid = back = 0
            seen = False
            for f0, t0, v0 in nat:
                if boot in (f0, t0):
                    seen = True
                    if f0 == f_tx and t0 == boot:
                        paid += v0
                        continue
                    if f0 == boot and t0 == f_tx:
                        back += v0
                        continue
                if v0:
                    legs.append((f0, t0, v0))
            if seen:
                if paid or back:
                    if paid >= back:
                        fee = paid - back
                else:
                    fee = 0
        else:
            traces = snap.get("internal") or []
            prepaid = any(it.get("success") is not False and not it.get("error") and addr(it.get("from")) == f_tx
                          and addr(it.get("to")) == boot and ival(it.get("value")) > 0 for it in traces)
            for it in traces:
                if it.get("success") is False or it.get("error"):
                    continue
                f0, t0, v0 = addr(it.get("from")), addr(it.get("to")), ival(it.get("value"))
                if not v0 or (f0 == f_tx and t0 == boot) or (prepaid and f0 == boot and t0 == f_tx):
                    continue
                legs.append((f0, t0, v0))
        internal = []
        skip = v_top > 0
        for f0, t0, v0 in legs:
            if skip and (f0, t0) == (f_tx, t_top) and v0 == v_top:
                skip = False
                continue
            internal.append({"from": f0, "to": t0, "value": str(v0), "success": True})
        out = dict(snap, token_transfers=tts, internal=internal, internal_note="zk_base_token")
        if fee is not None and fee != ival((tx.get("fee") or {}).get("value")):
            out["tx"] = dict(tx, fee=dict(tx.get("fee") or {}, value=str(fee)))
        return out

    def classify(self, chain: str, txhash: str, snap: dict):
        snap = self._zk_norm(chain, snap)
        (perw, cps, gas, gas_w, ts, failed, is_call,
         frm, to, only_mine) = self.deltas(chain, snap)
        mine = self.my_wallets.get(chain, set())
        perw = {k: v for k, v in perw.items() if v != 0}
        deltas = {}
        for (w, a), v in perw.items():
            deltas[a] = deltas.get(a, 0) + v
        deltas = {a: v for a, v in deltas.items() if v != 0}
        outs = {a: v for a, v in deltas.items() if v < 0}
        ins = {a: v for a, v in deltas.items() if v > 0}
        ex_addrs = self._ex_addr_set(chain)

        def R(event, hint=None):
            return (event, deltas, perw, gas, gas_w, ts, hint,
                    {"to": to, "cps": sorted(cps)[:4] if cps else []})

        if failed:
            if perw:
                return R("PROGRAM_IN")
            return R("FAILED")
        lp9 = self._lp_detect(chain, snap, to, frm, mine)
        if lp9 is not None and lp9.get("lp_token"):
            t_aid = self.asset_id("token", chain, lp9["lp_token"])
            perw = {k: v for k, v in perw.items() if k[1] != t_aid}
            deltas = {}
            for (_w, a), v in perw.items():
                deltas[a] = deltas.get(a, 0) + v
            deltas = {a: v for a, v in deltas.items() if v != 0}
            outs = {a: v for a, v in deltas.items() if v < 0}
            ins = {a: v for a, v in deltas.items() if v > 0}
        if lp9 is not None:
            if outs and ins:
                ev9 = "LP_ADJUST"
            elif outs:
                ev9 = "LP_ADD"
            elif ins or lp9.get("burn") or lp9.get("gone"):
                ev9 = "LP_REMOVE"
            elif perw or lp9.get("stake") or lp9.get("unstake"):
                ev9 = "LP_ADJUST"
            else:
                return R("NOOP")
            return (ev9, deltas, perw, gas, gas_w, ts, None,
                    {"to": to, "cps": sorted(cps)[:4] if cps else [], "lp": lp9})
        if len(outs) == 1 and len(ins) == 1:
            oa = self.conn.execute("SELECT * FROM assets WHERE asset_id=?", (next(iter(outs)),)).fetchone()
            ia = self.conn.execute("SELECT * FROM assets WHERE asset_id=?", (next(iter(ins)),)).fetchone()
            wrapped_ca = self.wrapped.get(chain)
            if wrapped_ca and {oa["kind"], ia["kind"]} == {"native", "token"}:
                tok = oa if oa["kind"] == "token" else ia
                if tok["address"] == wrapped_ca and abs(next(iter(outs.values()))) == next(iter(ins.values())):
                    return R("CONVERT")
        if only_mine or (not deltas and perw):
            return R("TRANSFER_SELF")
        if outs and cps and cps <= ex_addrs:
            return R("TRANSFER_OUT_EX", next(iter(cps)))
        if outs and ((frm in mine and to in self.bridges)
                     or (cps and all(c in self.bridges for c in cps))):
            hint = to if to in self.bridges else next(iter(cps))
            return R("BRIDGE", hint)
        if not cps and outs and ins:
            return R("UNKNOWN")
        if outs and not ins:
            if is_call and to and frm in mine:
                for a in outs:
                    ar = self.conn.execute(
                        "SELECT kind, address FROM assets WHERE asset_id=?", (a,)).fetchone()
                    if ar and ar["kind"] == "token" and ar["address"] == to and self._oft_like(snap, mine, to):
                        return R("BRIDGE", to)
            r9 = R("TRANSFER_OUT")
            r9[7]["out"] = self._out_dests(chain, snap, mine)
            return r9
        if outs and ins:
            if is_call and cps:
                unconfirmed = [a for a in ins if not self.is_confirmed(a)]
                if unconfirmed:
                    for a in unconfirmed:
                        self.conn.execute("UPDATE assets SET confirmed=1 WHERE asset_id=?", (a,))
                    dm("NEW_ASSET", f"[{chain}] 새 자산 자동 기록 tx {txhash} — LP/예치 토큰이면 검토",
                       {"chain": chain, "txhash": txhash,
                        "assets": [int(a) for a in unconfirmed]}, event_ts=ts)
                return R("SWAP")
            return R("UNKNOWN")
        if ins and not outs:
            if is_call:
                return R("PROGRAM_IN")
            return R("TRANSFER_IN")
        if not deltas:
            return R("NOOP")
        return R("UNKNOWN")

    ERC20_PLAIN_SELS = ("0xa9059cbb", "0x23b872dd")

    def _oft_like(self, snap: dict, mine: set, ca: str) -> bool:
        ca = (ca or "").lower()
        dests = set()
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            if str(tok.get("address") or tok.get("address_hash") or "").lower() != ca:
                continue
            f9, t9 = tt.get("from"), tt.get("to")
            f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
            t9 = str((t9.get("hash") if isinstance(t9, dict) else t9) or "").lower()
            if f9 in mine:
                dests.add(t9)
        if dests:
            return dests <= {self.ZERO_ADDR, ca}
        tx = snap.get("tx") or {}
        sel = str(tx.get("raw_input") or tx.get("input") or "")[:10].lower()
        return sel not in self.ERC20_PLAIN_SELS

    def _reclass_plain_xfer_once(self):
        if self._meta_get("reclass_q_plainxfer"):
            return 0
        n = 0
        done = []
        try:
            for r in self.conn.execute(
                    "SELECT t.chain, t.txhash, r.snapshot FROM tx_class t JOIN raw_txs r ON r.chain=t.chain AND r.txhash=t.txhash"
                    " WHERE t.event='BRIDGE' AND t.chain != 'sol' ORDER BY t.chain, t.txhash").fetchall():
                snap = json.loads(r["snapshot"])
                f9 = (snap.get("tx") or {}).get("from")
                f9 = str((f9.get("hash") if isinstance(f9, dict) else f9) or "").lower()
                if f9 not in self.my_wallets.get(r["chain"], set()):
                    continue
                if self.classify(r["chain"], r["txhash"], snap)[0] == "BRIDGE":
                    continue
                gas9 = {(p["asset_id"], p["location"], p["qty_base"]): (p["cost_usd"], p["cost_krw"]) for p in self.conn.execute(
                    "SELECT asset_id, location, qty_base, cost_usd, cost_krw FROM postings WHERE source_kind='chain_tx'"
                    " AND source_ns=? AND source_id=? AND leg_kind='gas' AND cost_usd IS NOT NULL", (r["chain"], r["txhash"])).fetchall()}
                ev = self._rederive_tx(r["chain"], r["txhash"])
                for (aid9, loc9, qb9), (cu9, ck9) in gas9.items():
                    self.conn.execute("UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_kind='chain_tx' AND source_ns=?"
                                      " AND source_id=? AND leg_kind='gas' AND asset_id=? AND location=? AND qty_base=?"
                                      " AND cost_usd IS NULL", (cu9, ck9, r["chain"], r["txhash"], aid9, loc9, qb9))
                done.append((r["chain"], r["txhash"], ev))
                n += 1
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('reclass_q_plainxfer', ?)", (f"{int(time.time())}:{n}",))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if n:
            ev_n = {}
            for _c, _h, e in done:
                ev_n[e] = ev_n.get(e, 0) + 1
            log.warning("★평범한 ERC-20 전송 오분류 BRIDGE %d건 재분류 %s★", n, ev_n)
        return n

    def _reclass_added_lp_mgrs_once(self) -> int:
        todo = []
        for ch, mg in (self.lp_mgrs or {}).items():
            if not isinstance(mg, dict):
                continue
            for addr, meta in mg.items():
                if isinstance(meta, dict) and meta.get("added") and meta.get("proto") in lpdec.NFT_PROTOS \
                        and not self._meta_get(f"reclass_lp_mgr:{ch}:{addr}"):
                    todo.append((ch, str(addr).lower()))
        if not todo:
            return 0
        n = 0
        changed = {}
        try:
            for ch, addr in todo:
                rows = self.conn.execute(
                    "SELECT r.txhash, r.ts, r.snapshot, t.event FROM raw_txs r LEFT JOIN tx_class t ON t.chain=r.chain AND t.txhash=r.txhash"
                    " WHERE r.chain=? AND instr(lower(r.snapshot), ?) > 0", (ch, addr)).fetchall()
                items = []
                miss9 = []
                for r in rows:
                    snap = json.loads(r["snapshot"])
                    tx9 = snap.get("tx") or {}
                    to9 = tx9.get("to")
                    to9 = str((to9.get("hash") if isinstance(to9, dict) else to9) or "").lower()
                    if to9 == addr and (self.lp_mgrs.get(ch) or {}).get(addr, {}).get("proto") in ("uni_v3", "slipstream") \
                            and any(a9 in ("MINT", "INCREASE") and l9 is None
                                    for a9, _t9, l9 in lpdec.decode_lp_calls(tx9.get("raw_input") or tx9.get("input"))) \
                            and not snap.get("_lp_liq"):
                        miss9.append(r["txhash"])
                    ts9 = r["ts"]
                    if ts9 is None:
                        try:
                            ts9 = self.deltas(ch, snap)[4]
                        except Exception:
                            ts9 = 0
                    items.append((int(ts9 or 0), r["txhash"], r["event"]))
                if miss9:
                    log.warning("새 LP 관리자 %s:%s — v3 예치 유동성 힌트 없는 tx %d건(%s…) · 재분류 보류(%s)",
                                ch, addr[:10], len(miss9), miss9[0][:12],
                                ((common.tool_ref("backfill_gap.py", "") + " nft-enrich/import 먼저") if common.tool_ref("backfill_gap.py", "")
                                 else "보강 도구가 이 설치엔 없음 — 보류 유지(장부는 그대로)"))
                    continue
                for _ts9, h, old_ev in sorted(items):
                    gas9 = {(p["asset_id"], p["location"], p["qty_base"]): (p["cost_usd"], p["cost_krw"]) for p in self.conn.execute(
                        "SELECT asset_id, location, qty_base, cost_usd, cost_krw FROM postings WHERE source_kind='chain_tx'"
                        " AND source_ns=? AND source_id=? AND leg_kind='gas' AND cost_usd IS NOT NULL", (ch, h)).fetchall()}
                    ev = self._rederive_tx(ch, h)
                    for (aid9, loc9, qb9), (cu9, ck9) in gas9.items():
                        self.conn.execute("UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_kind='chain_tx' AND source_ns=?"
                                          " AND source_id=? AND leg_kind='gas' AND asset_id=? AND location=? AND qty_base=?"
                                          " AND cost_usd IS NULL", (cu9, ck9, ch, h, aid9, loc9, qb9))
                    if ev != old_ev:
                        changed[f"{old_ev}→{ev}"] = changed.get(f"{old_ev}→{ev}", 0) + 1
                    n += 1
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"reclass_lp_mgr:{ch}:{addr}", f"{int(time.time())}:{len(items)}"))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if changed:
            try:
                os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
            except FileNotFoundError:
                pass
            log.warning("★새 LP 관리자 %s — 저장된 tx %d건 재분류 %s★", ", ".join(f"{c}:{a[:10]}" for c, a in todo), n, changed)
        return n

    def _out_dests(self, chain: str, snap: dict, mine: set) -> dict:
        def addr(x):
            return ((x.get("hash") if isinstance(x, dict) else x) or "").lower()
        acc = {}
        tx = snap.get("tx") or {}
        native_aid = self.asset_id("native", chain, None, symbol=self.native_sym.get(chain, chain.upper()),
                                   decimals=9 if chain == "sol" else 18)

        def add(w, aid, to9, v):
            if w in mine and to9 and to9 not in mine and v > 0:
                k = (w, aid)
                acc.setdefault(k, {})[to9] = acc.setdefault(k, {}).get(to9, 0) + v
        try:
            add(addr(tx.get("from")), native_aid, addr(tx.get("to")), int(tx.get("value") or 0))
        except (TypeError, ValueError):
            pass
        for it in snap.get("internal") or []:
            if it.get("success") is False or it.get("error"):
                continue
            try:
                add(addr(it.get("from")), native_aid, addr(it.get("to")), int(it.get("value") or 0))
            except (TypeError, ValueError):
                continue
        for tt in snap.get("token_transfers") or []:
            tok = tt.get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            ca = tok.get("address") or tok.get("address_hash")
            if not ca:
                continue
            try:
                v = int((tt.get("total") or {}).get("value") or 0)
            except (TypeError, ValueError):
                continue
            try:
                dec9 = None if tok.get("decimals") is None else int(tok.get("decimals"))
            except (TypeError, ValueError):
                dec9 = None
            aid = self.asset_id("token", chain, ca, symbol=tok.get("symbol"),
                                decimals=dec9 if dec9 is not None else self._meta_dec(chain, ca))
            add(addr(tt.get("from")), aid, addr(tt.get("to")), v)
        return {f"{w}|{aid}": max(d.items(), key=lambda kv: (kv[1], kv[0]))[0] for (w, aid), d in acc.items()}

    def _out_legs(self, chain: str, perw: dict, dest: dict, loc_of) -> list:
        dmap = dest.get("out") or {}
        cps = [c for c in (dest.get("cps") or []) if c]
        fallback = cps[0] if len(cps) == 1 else ("multi" if cps else "?")
        legs = []
        by_aid = {}
        for (w, aid), v in perw.items():
            by_aid.setdefault(aid, []).append((w, v))
        for aid in sorted(by_aid):
            ws = sorted(by_aid[aid], key=lambda x: x[0] or "")
            pos = [[w, v] for w, v in ws if v > 0]
            for w, v in ws:
                if v >= 0:
                    continue
                legs.append(("move_out", aid, v, loc_of(w)))
                left = -v
                for pw in pos:
                    take = min(left, pw[1])
                    if take > 0:
                        legs.append(("move_in", aid, take, loc_of(pw[0])))
                        pw[1] -= take
                        left -= take
                if left > 0:
                    to9 = dmap.get(f"{w}|{aid}") or fallback
                    legs.append(("move_in", aid, left, f"out:{chain}:{to9}"))
        return legs

    OUTFLOW_PATH = os.path.join(common.STATE_DIR, "outflow_decisions.json")

    def _outflow_decisions(self) -> dict:
        try:
            with open(self.OUTFLOW_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("보낸 내역 판정 파일 읽기 실패(건너뜀): %s", e)
            return {}
        dd = (d or {}).get("decisions") if isinstance(d, dict) else None
        return dd if isinstance(dd, dict) else {}

    def _outflow_chains(self, addr: str) -> list:
        return sorted({r["location"].split(":")[1] for r in self.conn.execute(
            "SELECT DISTINCT location FROM postings WHERE location LIKE 'out:%' AND location LIKE ?",
            ("%:" + addr,)).fetchall() if r["location"].split(":", 2)[2] == addr})

    def outflow_sync_exchange_rows(self) -> set:
        dec = self._outflow_decisions()
        want = {}
        for a, v in dec.items():
            if isinstance(v, dict) and v.get("verdict") == "exchange":
                for ch in (v.get("chains") or self._outflow_chains(a)):
                    want[(ch, a)] = str(v.get("exchange") or "unknown")[:32]
        have = {(r["chain"], r["address"]): r["exchange"] for r in self.conn.execute(
            "SELECT exchange, chain, address FROM exchange_addresses WHERE sync_state='outflow'").fetchall()}
        changed = set()
        for (ch, a), ex in want.items():
            if have.get((ch, a)) != ex:
                self.conn.execute("DELETE FROM exchange_addresses WHERE chain=? AND address=? AND sync_state='outflow'",
                                  (ch, a))
                self.conn.execute("INSERT OR IGNORE INTO exchange_addresses (exchange, chain, address, currency, memo,"
                                  " sync_state) VALUES (?,?,?,NULL,'보낸 내역 판정','outflow')", (ex, ch, a))
                changed.add(a)
        for (ch, a) in set(have) - set(want):
            self.conn.execute("DELETE FROM exchange_addresses WHERE chain=? AND address=? AND sync_state='outflow'", (ch, a))
            changed.add(a)
        return changed

    def _rederive_tx(self, chain: str, txhash: str) -> str:
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        if not row:
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        for p in self.conn.execute("SELECT asset_id, location, qty_base FROM postings WHERE source_kind='chain_tx'"
                                   " AND source_ns=? AND source_id=?", (chain, txhash)).fetchall():
            self._bump_position(p["asset_id"], -int(p["qty_base"]), p["location"])
        self.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?", (chain, txhash))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?", (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        snap = json.loads(row["snapshot"])
        if chain == "sol" and snap.get("kind") == "sol_tx":
            return self.apply_sol(snap, rederive=((oe["event"] if oe else None), frozenset(keep)))
        return self.apply(chain, txhash, "", snap, rederive=((oe["event"] if oe else None), frozenset(keep)))

    def outflow_pass(self, force: bool = False):
        if not force and time.time() - getattr(self, "_last_outflow", 0) < 60:
            return
        self._last_outflow = time.time()
        dec = self._outflow_decisions()
        changed = self.outflow_sync_exchange_rows()
        addrs = set(dec) | changed | {r["k"][len("outflow_applied:"):] for r in self.conn.execute(
            "SELECT k FROM meta WHERE k LIKE 'outflow_applied:%'").fetchall()}
        n_tx = 0
        for a in sorted(addrs):
            v = dec.get(a) if isinstance(dec.get(a), dict) else {}
            verdict = v.get("verdict") or "clear"
            reg = any(a in ws for ws in self.my_wallets.values()) or a in self.sol_wallets
            sig = f"{verdict}:{int(reg) if verdict == 'own' else ''}:{v.get('exchange') or ''}:{','.join(sorted(v.get('chains') or []))}"
            k = f"outflow_applied:{a}"
            cur = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            prev9 = cur["v"] if cur else "clear::"
            if prev9 == sig and a not in changed:
                continue
            _bk = lambda s9: "out" if s9.split(":", 1)[0] in ("clear", "external") else s9
            if _bk(prev9) == _bk(sig) and a not in changed:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
                continue
            if verdict == "own" and not reg:
                if cur is None or not str(cur["v"]).startswith("own:0"):
                    log.info("보낸 내역: %s '내 지갑' 판정 — config 등록 확인됨, tj-core·수집기 재기동 뒤 재분류", a[:12])
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
                continue
            txs = {(r["source_ns"], r["source_id"]) for r in self.conn.execute(
                "SELECT DISTINCT p.source_ns, p.source_id FROM postings p WHERE p.source_kind='chain_tx'"
                " AND p.location LIKE ?", ("out:%:" + a,)).fetchall()}
            for r in self.conn.execute("SELECT chain, txhash, detail FROM tx_class WHERE event IN ('TRANSFER_OUT_EX', 'TRANSFER_SELF')"
                                       " AND detail LIKE ?", ('%' + a + '%',)).fetchall():
                txs.add((r["chain"], r["txhash"]))
            for r in self.conn.execute("SELECT DISTINCT source_ns, source_id FROM postings WHERE source_kind='chain_tx'"
                                       " AND event IN ('TRANSFER_SELF', 'TRANSFER_OUT') AND leg_kind='move_in' AND location LIKE ?",
                                       ("wallet:%:" + a,)).fetchall():
                txs.add((r["source_ns"], r["source_id"]))
            try:
                for ch9, h9 in sorted(txs):
                    self._rederive_tx(ch9, h9)
                    n_tx += 1
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, sig))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            for ch9, h9 in sorted(txs):
                try:
                    self._price_tx(ch9, h9)
                except Exception as e:
                    self.conn.rollback()
                    log.warning("보낸 내역 재기장 가격 %s %s 실패(가격패스가 재시도): %s", ch9, h9[:12], e)
            log.info("★보낸 내역 판정 반영: %s → %s (tx %d건 재분류)★", a[:12], verdict, len(txs))
        if n_tx:
            try:
                os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
            except FileNotFoundError:
                pass

    ZERO_ADDR = "0x0000000000000000000000000000000000000000"

    def _lp_detect(self, chain: str, snap: dict, to, frm, mine: set):
        mgrs_all = self.lp_mgrs.get(chain) or {}
        stakers = {a9: m9 for a9, m9 in mgrs_all.items() if m9.get("proto") == "stake"}
        mgrs = {a9: m9 for a9, m9 in mgrs_all.items() if m9.get("proto") in lpdec.NFT_PROTOS}
        to_l = str(to or "").lower()
        tx = snap.get("tx") or {}
        sel9 = str(tx.get("raw_input") or tx.get("input") or "")[2:10].lower()
        dyn = self._lp_gauges(chain) if (to_l and to_l not in mgrs_all and str(frm or "").lower() in mine) else {}
        stk = stakers.get(to_l) or (dyn.get(to_l) if (dyn.get(to_l) or {}).get("npm") else None)
        if not mgrs:
            return self._lp_v2_detect(chain, snap, to_l, frm, mine, sel9, dyn) if mine else None
        mgr = to_l if to_l in mgrs else (str(stk.get("npm") or "").lower() or None if stk else None)
        moves = sorted({m for m in lpdec.nft_moves(snap, mgrs) if (m[2] in mine or m[3] in mine)})
        if mgr is None and moves:
            mgr = moves[0][0]
        if mgr is None:
            return self._lp_v2_detect(chain, snap, to_l, frm, mine, sel9, dyn)
        if str(frm or "").lower() not in mine and not moves:
            return None
        calls = lpdec.decode_lp_calls(tx.get("raw_input") or tx.get("input")) if (to_l == mgr or stk) else []
        mv = [m for m in moves if m[0] == mgr]
        mint = sorted({tid for _a, tid, f, t in mv if f == self.ZERO_ADDR and t in mine})
        burn = sorted({tid for _a, tid, f, t in mv if t == self.ZERO_ADDR and f in mine}
                      | {tid for act, tid, _ in calls if act == "BURN" and tid is not None})
        stake = {}
        for _a, tid, f, t in mv:
            if f in mine and t not in mine and t != self.ZERO_ADDR and (
                    t in stakers or (t == to_l and to_l not in mgrs_all and sel9 == lpdec.SEL_DEPOSIT_U256)):
                stake[str(tid)] = t
        unstake = {str(tid): f for _a, tid, f, t in mv if t in mine and f not in mine and f != self.ZERO_ADDR
                   and (f in stakers or f in dyn or f == to_l)}
        gone = sorted({tid for _a, tid, f, t in mv if f in mine and t not in mine and t != self.ZERO_ADDR
                       and str(tid) not in stake})
        hint = {}
        for h9 in snap.get("_lp_liq") or []:
            try:
                hint[int(h9[0])] = str(int(h9[1]))
            except (TypeError, ValueError, IndexError):
                continue
        if not mint and hint and any(a == "MINT" for a, _t, _l in calls):
            inc_ids = {t for a, t, _l in calls if a == "INCREASE" and t is not None}
            mint = sorted(set(hint) - inc_ids)
        liq = []
        for act, tid, l in calls:
            if act == "MINT" and tid is None and len(mint) == 1:
                tid = mint[0]
            if act in ("MINT", "INCREASE") and l is None and tid is not None and tid in hint:
                l = hint[tid]
            if act in ("MINT", "INCREASE", "DECREASE", "BURN"):
                liq.append([act, tid, (str(l) if l is not None else None)])
        dep_ids = sorted({tid for act, tid, _ in liq if act in ("MINT", "INCREASE") and tid is not None} | set(mint))
        wd_ids = sorted({tid for act, tid, _ in calls if act in ("DECREASE", "COLLECT", "BURN") and tid is not None}
                        | set(burn) | set(gone))
        ids = sorted(set(dep_ids) | set(wd_ids) | {tid for _a, tid, _f, _t in mv})
        mint_unk = any(act == "MINT" and tid is None for act, tid, _ in liq)
        who = str(frm or "").lower() if str(frm or "").lower() in mine else \
            next((t if t in mine else f for _a, _i, f, t in mv), "")
        unk_loc = f"lp:{chain}:{mgr}:?{who}"
        if len(dep_ids) == 1 and not mint_unk:
            dep_loc = lpdec.lp_location(chain, mgr, dep_ids)
        elif not dep_ids and not mint_unk and len(wd_ids) == 1:
            dep_loc = lpdec.lp_location(chain, mgr, wd_ids)
        elif not dep_ids:
            dep_loc = unk_loc
        else:
            dep_loc = f"lp:{chain}:{mgr}:multi"
        if stk and not ids:
            return None
        out9 = {"mgr": mgr, "proto": mgrs[mgr].get("proto"), "name": mgrs[mgr].get("name"),
                "ids": ids, "mint": mint, "burn": burn, "gone": gone,
                "dep_ids": dep_ids, "wd_ids": wd_ids,
                "actions": sorted({a for a, _, _ in calls}), "liq": liq, "who": who,
                "loc": lpdec.lp_location(chain, mgr, ids), "dep_loc": dep_loc, "unk_loc": unk_loc}
        if stake:
            out9["stake"] = stake
        if unstake:
            out9["unstake"] = unstake
        if stk:
            out9["via"] = to_l
        return out9

    def _lp_gauges(self, chain: str) -> dict:
        cache = self.__dict__.setdefault("_lp_learn_cache", {})
        if ("g", chain) in cache:
            return cache[("g", chain)]
        out = cache[("g", chain)] = {}
        for r in self.conn.execute("SELECT detail FROM tx_class WHERE chain=? AND event LIKE 'LP_%' AND detail LIKE '%stake%'",
                                   (chain,)).fetchall():
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            for _tid, g in (lp.get("stake") or {}).items():
                g = str(g or "").lower()
                if not g:
                    continue
                if lp.get("proto") == "v2":
                    out.setdefault(g, {"pair": lp.get("mgr")})
                else:
                    out.setdefault(g, {"npm": lp.get("mgr")})
        return out

    def _lp_v2_detect(self, chain: str, snap: dict, to_l: str, frm, mine: set, sel9: str, dyn: dict):
        who = str(frm or "").lower()
        if who not in mine:
            return None
        tts = []
        for tt in (snap.get("token_transfers") or []):
            tok = tt.get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
            f3, t3 = tt.get("from"), tt.get("to")
            f3 = str((f3.get("hash") if isinstance(f3, dict) else f3) or "").lower()
            t3 = str((t3.get("hash") if isinstance(t3, dict) else t3) or "").lower()
            try:
                v3 = int((tt.get("total") or {}).get("value") or 0)
            except (TypeError, ValueError):
                continue
            if ca and v3 > 0:
                tts.append((ca, f3, t3, v3, tok.get("symbol") or ""))
        if not tts:
            return None
        Z = self.ZERO_ADDR
        known = self._lp_v2_tokens(chain)
        names = (self.lp_mgrs.get(chain) or {})
        parties = set(mine)
        rt9 = names.get(to_l) or {}
        if rt9.get("proto") == "v2_router" and rt9.get("verified"):
            parties.add(to_l)
        for T in sorted({c for c, f, t, v, _s in tts if f == Z and t in mine}):
            und = {c for c, f, t, v, _s in tts if t == T and c != T and f in parties}
            if len(und) >= 2:
                minted = sum(v for c, f, t, v, _s in tts if c == T and f == Z and t in mine)
                return self._lp_v2_dict(chain, T, who, "add", minted, tts, to_l, names)
        for T in sorted({c for c, f, t, v, _s in tts if t == Z and f == c}):
            mine_out = sum(v for c, f, t, v, _s in tts if c == T and f in mine and t == T)
            und = {c for c, f, t, v, _s in tts if f == T and c != T and t in parties}
            if mine_out > 0 and len(und) >= 2:
                return self._lp_v2_dict(chain, T, who, "remove", mine_out, tts, to_l, names)
        for c, f, t, v, _s in tts:
            if c in known and f in mine and t == to_l and t not in mine and sel9 == lpdec.SEL_DEPOSIT_U256:
                d9 = self._lp_v2_dict(chain, c, f, "stake", 0, tts, to_l, names)
                d9["stake"] = {f: t}
                return d9
            if c in known and t in mine and f == to_l and f in dyn:
                d9 = self._lp_v2_dict(chain, c, t, "unstake", 0, tts, to_l, names)
                d9["unstake"] = {t: f}
                return d9
        g9 = dyn.get(to_l) or {}
        if g9.get("pair") and any(t in mine and f == to_l for c, f, t, v, _s in tts):
            d9 = self._lp_v2_dict(chain, str(g9["pair"]).lower(), who, "claim", 0, tts, to_l, names)
            d9["via"] = to_l
            return d9
        return None

    def _lp_v2_tokens(self, chain: str) -> dict:
        cache = self.__dict__.setdefault("_lp_learn_cache", {})
        if ("t", chain) in cache:
            return cache[("t", chain)]
        out = cache[("t", chain)] = {}
        for r in self.conn.execute("SELECT detail FROM tx_class WHERE chain=? AND event LIKE 'LP_%' AND detail LIKE '%\"v2\"%'",
                                   (chain,)).fetchall():
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if lp.get("proto") == "v2" and lp.get("mgr"):
                out[str(lp["mgr"]).lower()] = lp.get("name")
        return out

    @staticmethod
    def _lp_v2_name(sym: str, router_meta: dict) -> str:
        if router_meta.get("name"):
            return str(router_meta["name"])
        s9 = str(sym or "")
        if s9.startswith(("vAMM-", "sAMM-")):
            return "Aerodrome/Velodrome v2"
        if s9 == "Cake-LP":
            return "PancakeSwap v2"
        if s9 == "UNI-V2":
            return "Uniswap v2"
        if s9 == "SLP":
            return "SushiSwap v2"
        return "v2 LP"

    def _lp_v2_dict(self, chain, T, who, kind, amount, tts, to_l, names) -> dict:
        sym = next((s9 for c, f, t, v, s9 in tts if c == T and s9), "")
        rt = names.get(to_l) or {}
        name = self._lp_v2_name(sym, rt if rt.get("proto") == "v2_router" else {})
        liq = []
        if kind == "add":
            liq = [["MINT", who, str(int(amount))]]
        elif kind == "remove":
            liq = [["DECREASE", who, str(int(amount))]]
        loc = f"lp:{chain}:{T}:{who}"
        acts = {"add": ["MINT"], "remove": ["DECREASE"], "claim": ["COLLECT"], "stake": [], "unstake": []}[kind]
        return {"mgr": T, "proto": "v2", "name": name, "lpSym": sym, "lp_token": T, "ids": [who], "mint": [], "burn": [],
                "gone": [], "dep_ids": [who] if kind == "add" else [], "wd_ids": [who] if kind in ("remove", "claim") else [],
                "actions": acts, "liq": liq, "who": who, "loc": loc, "dep_loc": loc, "unk_loc": f"lp:{chain}:{T}:?{who}",
                "v2kind": kind}


    def _lp_held(self, loc_lp: str, before_ts=None) -> dict:
        held = {}
        q = "SELECT asset_id, qty_base FROM postings WHERE location=?" + (" AND event_ts <= ?" if before_ts is not None else "")
        args = (loc_lp, before_ts) if before_ts is not None else (loc_lp,)
        for r in self.conn.execute(q, args).fetchall():
            try:
                held[r["asset_id"]] = held.get(r["asset_id"], 0) + int(r["qty_base"])
            except (TypeError, ValueError):
                continue
        return {a: v for a, v in held.items() if v > 0}

    def _lp_liq_before(self, chain: str, mgr: str, tid, ts: int, txhash: str):
        tot = 0
        seen = False
        for r in self.conn.execute(
                "SELECT t.txhash, t.detail, (SELECT min(p.event_ts) FROM postings p WHERE p.source_kind='chain_tx'"
                "  AND p.source_ns=t.chain AND p.source_id=t.txhash) AS ets"
                " FROM tx_class t WHERE t.chain=? AND t.event LIKE 'LP_%' AND t.txhash != ?",
                (chain, txhash)).fetchall():
            if r["ets"] is None or int(r["ets"]) > ts:
                continue
            try:
                lp = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if str(lp.get("mgr") or "") != mgr:
                continue
            for act, t9, l9 in lp.get("liq") or []:
                if t9 is None or lpdec.lp_tid(t9) != tid or act not in ("MINT", "INCREASE", "DECREASE"):
                    continue
                if l9 is None:
                    return None
                seen = True
                tot += int(l9) if act != "DECREASE" else -int(l9)
        return tot if seen else None

    def _lp_legs(self, chain: str, txhash: str, perw: dict, lp: dict, loc_of, ts: int) -> list:
        mgr = lp.get("mgr") or ""
        prefix = f"lp:{chain}:{mgr}"
        loc_unk = lp.get("unk_loc") or f"{prefix}:?{lp.get('who') or ''}"
        dep_loc = lp.get("dep_loc") or lp.get("loc") or loc_unk
        items = sorted(perw.items(), key=lambda kv: (kv[1] > 0, kv[0][1], kv[0][0] or ""))
        legs = []
        held = {}

        def H(b):
            if b not in held:
                held[b] = self._lp_held(b, before_ts=ts)
            return held[b]
        for (w, aid), v in items:
            if v < 0:
                legs.append(("move_out", aid, v, loc_of(w)))
                legs.append(("move_in", aid, -v, dep_loc))
                H(dep_loc)[aid] = H(dep_loc).get(aid, 0) + (-v)
        srcs = [f"{prefix}:{t}" for t in (lpdec.lp_tid(i) for i in (lp.get("wd_ids") or [])) if t is not None]
        if loc_unk not in srcs:
            srcs.append(loc_unk)
        dec_by_id = {}
        dec_unknown = set()
        for act, t9, l9 in lp.get("liq") or []:
            if act == "DECREASE" and lpdec.lp_tid(t9) is not None:
                if l9 is None:
                    dec_unknown.add(lpdec.lp_tid(t9))
                else:
                    dec_by_id[lpdec.lp_tid(t9)] = dec_by_id.get(lpdec.lp_tid(t9), 0) + int(l9)
        burn_ids = {t for t in map(lpdec.lp_tid, lp.get("burn") or []) if t is not None}
        exit_ids = burn_ids | {t for t in map(lpdec.lp_tid, lp.get("gone") or []) if t is not None}
        frac_hint = {str(k): v for k, v in (lp.get("frac") or {}).items()
                     if isinstance(v, (list, tuple)) and len(v) == 2 and int(v[1]) > 0}
        frac = {}
        for b in srcs:
            tid = lpdec.lp_tid(b.rsplit(":", 1)[1])
            if tid is None:
                frac[b] = None
                continue
            if tid in burn_ids:
                frac[b] = (1, 1)
            elif str(tid) in frac_hint:
                n9, d9 = (int(x) for x in frac_hint[str(tid)])
                frac[b] = (max(0, min(n9, d9)), d9)
            elif tid in dec_unknown:
                frac[b] = None
            elif tid in dec_by_id:
                d9 = dec_by_id[tid]
                lb = self._lp_liq_before(chain, mgr, tid, ts, txhash) if d9 > 0 else None
                if d9 == 0:
                    frac[b] = (0, 1)
                elif lb is None or lb <= 0:
                    frac[b] = None
                else:
                    frac[b] = (min(d9, lb), lb)
            elif tid in exit_ids or "COLLECT" in (lp.get("actions") or []):
                frac[b] = (0, 1)
            else:
                frac[b] = None
        release = {}
        rent9 = {int(a) for a in (lp.get("rent_aids") or [])}
        for b in srcs:
            fb = frac.get(b)
            hb = H(b)
            if fb is None:
                release[b] = dict(hb)
            else:
                n9, d9 = fb
                release[b] = {a: ((q * n9) // d9 if (a not in rent9 or n9 >= d9) else 0) for a, q in hb.items()}
        backed = {b: {} for b in srcs}
        for (w, aid), v in items:
            if v <= 0:
                continue
            rem = v
            for b in srcs:
                cap = release[b].get(aid, 0) - backed[b].get(aid, 0)
                back = min(rem, cap)
                if back > 0:
                    legs.append(("move_out", aid, -back, b))
                    legs.append(("move_in", aid, back, loc_of(w)))
                    backed[b][aid] = backed[b].get(aid, 0) + back
                    rem -= back
                if rem <= 0:
                    break
            if rem > 0:
                legs.append(("acq", aid, rem, loc_of(w)))
        gone_q = {}
        for b in srcs:
            if frac.get(b) is None:
                continue
            for aid in sorted(release[b]):
                conv = release[b][aid] - backed[b].get(aid, 0)
                if conv > 0:
                    legs.append(("disp", aid, -conv, b))
                    gone_q[(b, aid)] = gone_q.get((b, aid), 0) + conv
        for tid in sorted(exit_ids):
            b = f"{prefix}:{tid}"
            hb = H(b)
            for aid in sorted(hb):
                left = hb[aid] - backed.get(b, {}).get(aid, 0) - gone_q.get((b, aid), 0)
                if left > 0:
                    legs.append(("disp", aid, -left, b))
        return legs

    @staticmethod
    def _unknown_legs(perw: dict, loc_of) -> list:
        by = {}
        for (w, aid), v in perw.items():
            if v:
                by.setdefault(aid, []).append((w or "", v))
        legs = []
        for aid in sorted(by):
            ws = sorted(by[aid])
            mo = mi = min(-sum(v for _w, v in ws if v < 0), sum(v for _w, v in ws if v > 0))
            for w, v in ws:
                if v < 0:
                    m = min(-v, mo)
                    mo -= m
                    if m:
                        legs.append(("move_out", aid, -m, loc_of(w)))
                    if -v > m:
                        legs.append(("disp", aid, v + m, loc_of(w)))
                else:
                    m = min(v, mi)
                    mi -= m
                    if m:
                        legs.append(("move_in", aid, m, loc_of(w)))
                    if v > m:
                        legs.append(("acq", aid, v - m, loc_of(w)))
        return legs

    LEG_BY_EVENT = {
        "SWAP": ("disp", "acq"), "CONVERT": ("move_out", "move_in"),
        "TRANSFER_SELF": ("move_out", "move_in"), "TRANSFER_OUT_EX": ("move_out", "move_in"),
        "BRIDGE": ("move_out", "move_in"), "TRANSFER_IN": (None, "acq"),
        "PROGRAM_IN": (None, "acq"),
        "STAKE_REWARD": (None, "acq"),
    }

    def apply(self, chain: str, txhash: str, wallets_json: str, snap: dict, rederive=None):
        event, deltas, perw, gas, gas_w, ts, ex_hint, dest = self.classify(chain, txhash, snap)
        return self._post_event(chain, txhash, event, deltas, perw, gas, gas_w, ts, ex_hint,
                                dest=dest, rederive=rederive)

    def _post_event(self, chain: str, txhash: str, event: str, deltas: dict, perw: dict,
                    gas: int, gas_w, ts: int, ex_hint, dest=None, rederive=None):
        quiet = rederive is not None
        keep_aids = rederive[1] if rederive else frozenset()
        self.conn.execute(
            "INSERT OR REPLACE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES (?,?,?,?,?)",
            (chain, txhash, event,
             json.dumps({"ex": ex_hint, "lp": (dest or {}).get("lp")} if (dest or {}).get("lp")
                        else ({"ex": ex_hint, "out": (dest or {}).get("out") or {}, "cps": (dest or {}).get("cps") or []}
                              if event == "TRANSFER_OUT" else {"ex": ex_hint})),
             CLASSIFIER_VER))

        def loc_of(w):
            return f"wallet:{chain}:{w}" if w else f"wallet:{chain}"

        legs = []
        if event in ("FAILED", "NOOP"):
            pass
        elif event.startswith("LP_"):
            lp9 = (dest or {}).get("lp") or {}
            self.__dict__.pop("_lp_learn_cache", None)
            legs = self._lp_legs(chain, txhash, perw, lp9, loc_of, ts)
            if not quiet:
                dm(event, f"[{chain}] {lp9.get('name') or 'LP'} {event} tx {txhash} · 포지션 {lp9.get('loc')}",
                   {"chain": chain, "txhash": txhash, "lp": lp9}, event_ts=ts)
        elif event == "TRANSFER_OUT":
            legs = self._out_legs(chain, perw, (dest or {}), loc_of)
            if not quiet:
                dm(event, f"[{chain}] {event} — 외부 전송(보낸 내역) tx {txhash}",
                   {"chain": chain, "txhash": txhash,
                    "to": (dest or {}).get("to"),
                    "counterparties": (dest or {}).get("cps") or [],
                    "deltas": {str(k): str(v) for k, v in deltas.items()}}, event_ts=ts)
        elif event in ("UNKNOWN", "NEW_ASSET"):
            if event == "UNKNOWN":
                legs = self._unknown_legs(perw, loc_of)
            if not quiet:
                dm(event, f"[{chain}] {event} — 검토 필요 tx {txhash}",
                   {"chain": chain, "txhash": txhash,
                    "to": (dest or {}).get("to"),
                    "counterparties": (dest or {}).get("cps") or [],
                    "deltas": {str(k): str(v) for k, v in deltas.items()}}, event_ts=ts)
        else:
            out_kind, in_kind = self.LEG_BY_EVENT.get(event, (None, None))
            self_in = {}
            if event in ("TRANSFER_IN", "PROGRAM_IN"):
                for (_w, aid), v in perw.items():
                    if v < 0:
                        self_in[aid] = self_in.get(aid, 0) - v
            for (w, aid), v in sorted(perw.items(), key=lambda kv: (kv[0][1], kv[0][0] or "")):
                if aid in self_in:
                    if v < 0:
                        legs.append(("move_out", aid, v, loc_of(w)))
                        continue
                    moved = min(v, self_in[aid])
                    if moved:
                        legs.append(("move_in", aid, moved, loc_of(w)))
                        self_in[aid] -= moved
                        v -= moved
                    if not v:
                        continue
                lk = out_kind if v < 0 else in_kind
                if lk is None:
                    continue
                legs.append((lk, aid, v, loc_of(w)))
            if event == "TRANSFER_OUT_EX":
                for (w, aid), v in perw.items():
                    if v < 0 and aid not in keep_aids:
                        self.conn.execute(
                            "INSERT INTO transfers (state, asset_id, qty_base, src, dst, chain_txhash, updated_at)"
                            " VALUES ('sent', ?, ?, ?, ?, ?, ?)",
                            (aid, str(-v), loc_of(w), f"exchange:{ex_hint}", txhash, int(time.time())))
                if not quiet:
                    dm("TRANSFER_OUT_EX", f"[{chain}] 거래소 전송 감지 tx {txhash}", None, event_ts=ts)
            elif event == "SWAP":
                if not quiet:
                    dm("SWAP", f"[{chain}] 스왑 감지 tx {txhash}", {"chain": chain, "txhash": txhash},
                       event_ts=ts)
            elif event == "PROGRAM_IN":
                if not quiet:
                    dm("PROGRAM_IN", f"[{chain}] 프로그램 경유 수령 tx {txhash} — 체결/에어드랍 검토",
                       {"chain": chain, "txhash": txhash}, event_ts=ts)
        if gas:
            native_aid = self.asset_id("native", chain, None,
                                       symbol=self.native_sym.get(chain, chain.upper()),
                                       decimals=9 if chain == "sol" else 18)
            legs.append(("gas", native_aid, -gas, loc_of(gas_w)))
        for seq, (lk, aid, v, l) in enumerate(legs):
            self.conn.execute(
                "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                " VALUES ('chain_tx', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (chain, txhash, seq, ts, aid, l, str(v), lk, event, CLASSIFIER_VER))
        for lk, aid, v, l in legs:
            self._bump_position(aid, v, l)
        if event.startswith("LP_") and not getattr(self, "_lp_reflowing", False):
            self._lp_reflow(chain, txhash, (dest or {}).get("lp") or {}, ts)
        return event

    @staticmethod
    def _lp_locs_of(chain: str, lp: dict) -> set:
        pre = f"lp:{chain}:{lp.get('mgr') or ''}"
        out = {f"{pre}:{t}" for t in (lpdec.lp_tid(i) for i in (lp.get("ids") or [])) if t is not None}
        for k in ("dep_loc", "unk_loc"):
            if lp.get(k):
                out.add(lp[k])
        return out

    def _lp_reflow(self, chain: str, txhash: str, lp: dict, ts: int) -> None:
        mgr = lp.get("mgr") or ""
        if not mgr:
            return
        cands = []
        for r in self.conn.execute(
                "SELECT t.txhash, t.event, t.detail, (SELECT min(p.event_ts) FROM postings p WHERE p.source_kind='chain_tx'"
                "  AND p.source_ns=t.chain AND p.source_id=t.txhash) AS ets"
                " FROM tx_class t WHERE t.chain=? AND t.event LIKE 'LP_%' AND t.txhash != ?", (chain, txhash)).fetchall():
            if r["ets"] is None or (int(r["ets"]), r["txhash"]) <= (int(ts), txhash):
                continue
            try:
                lp2 = (json.loads(r["detail"] or "{}") or {}).get("lp") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if (lp2.get("mgr") or "") != mgr:
                continue
            cands.append((int(r["ets"]), r["txhash"], r["event"], self._lp_locs_of(chain, lp2)))
        if not cands:
            return
        cands.sort(key=lambda x: (x[0], x[1]))
        locs = self._lp_locs_of(chain, lp)
        later = []
        for ets, h, ev, l2 in cands:
            if l2 & locs:
                later.append((ets, h, ev))
                locs |= l2
        if not later:
            return
        self._lp_reflowing = True
        try:
            for _e, h, _ev in later:
                for p in self.conn.execute(
                        "SELECT asset_id, location, qty_base FROM postings"
                        " WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?", (chain, h)).fetchall():
                    self._bump_position(p["asset_id"], -int(p["qty_base"]), p["location"])
                self.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
                                  (chain, h))
            for _e, h, ev in later:
                row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, h)).fetchone()
                if not row:
                    continue
                snap9 = json.loads(row["snapshot"])
                if chain == "sol" and snap9.get("kind") == "sol_tx":
                    self.apply_sol(snap9, rederive=(ev, frozenset()))
                    continue
                self.apply(chain, h, "", snap9, rederive=(ev, frozenset()))
        finally:
            self._lp_reflowing = False
        log.info("LP 재정렬: [%s] %s 도착으로 뒤 LP tx %d건 재기장", chain, txhash[:14], len(later))

    def _bump_position(self, aid: int, v: int, loc: str) -> None:
        grp = self._group_of(aid)
        norm = self._norm(aid, v)
        row = self.conn.execute(
            "SELECT qty_norm FROM positions WHERE group_id=? AND location=?",
            (grp, loc)).fetchone()
        with localcontext() as ctx:
            ctx.prec = 100
            qty = Decimal(norm) + (Decimal(row["qty_norm"]) if row else Decimal(0))
            new_qty = format(qty, "f")
        if row:
            self.conn.execute("UPDATE positions SET qty_norm=? WHERE group_id=? AND location=?",
                              (new_qty, grp, loc))
        else:
            self.conn.execute("INSERT INTO positions (group_id, location, qty_norm) VALUES (?,?,?)",
                              (grp, loc, new_qty))

    def apply_sol(self, rec: dict, rederive=None):
        txhash = rec["txhash"]
        try:
            ts = int(rec.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts <= 0:
            log.warning("시각 없는 sol tx 거부: %s ts=%r", str(rec.get("txhash") or "?")[:14], rec.get("ts"))
            raise MissingTs(f"sol tx 시각 없음: {rec.get('ts')!r}")
        if rec.get("stake_open"):
            return self._post_stake_open(rec, ts)
        perw = {}
        deltas = {}
        for d in rec.get("deltas", []):
            if d["asset"] == "native":
                aid = self.asset_id("native", "sol", None, symbol="SOL", decimals=9)
            else:
                aid = self.asset_id("token", "sol", d["asset"], symbol=d.get("symbol"),
                                    decimals=d.get("decimals"))
            v = int(d["delta"])
            if v:
                owner = d.get("owner")
                perw[(owner, aid)] = perw.get((owner, aid), 0) + v
                deltas[aid] = deltas.get(aid, 0) + v
        gas = int(rec.get("fee_lamports") or 0) if rec.get("fee_payer_mine") else 0
        gas_w = rec.get("fee_payer") if rec.get("fee_payer_mine") else None
        cps = set(rec.get("counterparties") or []) - self.sol_wallets
        only_mine = bool(rec.get("counterparties")) and not cps
        ex_rows = self.conn.execute(
            "SELECT address FROM exchange_addresses WHERE chain='sol'").fetchall()
        ex_addrs = {r["address"] for r in ex_rows}
        deltas = {a: v for a, v in deltas.items() if v != 0}
        outs = {a: v for a, v in deltas.items() if v < 0}
        ins = {a: v for a, v in deltas.items() if v > 0}
        self_move = (not deltas) and any(v for v in perw.values())
        lp9 = None if rec.get("err") else lpsol.lp_detect(rec, self.sol_wallets)
        if lp9 is not None and not any(lpsol.WSOL in (m or []) for m in (lp9.get("mints") or {}).values()):
            lp9["rent_aids"] = [self.asset_id("native", "sol", None, symbol="SOL", decimals=9)]
        if lp9 is not None:
            if outs and ins:
                ev9 = "LP_ADJUST"
            elif outs:
                ev9 = "LP_ADD"
            elif ins or lp9.get("burn"):
                ev9 = "LP_REMOVE"
            elif any(v for v in perw.values()):
                ev9 = "LP_ADJUST"
            else:
                ev9 = "NOOP"
            if ev9 != "NOOP":
                return self._post_event("sol", txhash, ev9, deltas, perw, gas, gas_w, ts, None,
                                        dest={"to": None, "cps": sorted(cps)[:4], "lp": lp9}, rederive=rederive)
        if rec.get("err"):
            event, ex_hint = "FAILED", None
        elif only_mine or self_move:
            event, ex_hint = "TRANSFER_SELF", None
        elif outs and cps and cps <= ex_addrs:
            event, ex_hint = "TRANSFER_OUT_EX", "upbit"
        elif outs and ins:
            if rec.get("has_program"):
                unconfirmed = [a for a in ins if not self.is_confirmed(a)]
                if unconfirmed:
                    for a in unconfirmed:
                        self.conn.execute("UPDATE assets SET confirmed=1 WHERE asset_id=?", (a,))
                    dm("NEW_ASSET", f"[sol] 새 자산 자동 기록 tx {txhash} — LP/예치 토큰이면 검토",
                       {"chain": "sol", "txhash": txhash,
                        "assets": [int(a) for a in unconfirmed]}, event_ts=ts)
                event, ex_hint = "SWAP", None
            else:
                event, ex_hint = "UNKNOWN", None
        elif outs:
            event, ex_hint = "TRANSFER_OUT", None
        elif ins and rec.get("stake_reward") and all(":stake:" in (w or "") for (w, _a), v in perw.items() if v):
            event, ex_hint = "STAKE_REWARD", None
        elif ins:
            event = "PROGRAM_IN" if rec.get("has_program") else "TRANSFER_IN"
            ex_hint = None
        else:
            event, ex_hint = "NOOP", None
        if event == "STAKE_REWARD" and ts < time.time() - 86400:
            self._drop_daily_cache()
        return self._post_event("sol", txhash, event, deltas, perw, gas, gas_w, ts, ex_hint,
                                dest={"to": None, "cps": sorted(cps)[:4]}, rederive=rederive)

    @staticmethod
    def _drop_daily_cache():
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass

    def _post_stake_open(self, rec: dict, ts: int) -> str:
        so = rec.get("stake_open") or {}
        acct = so.get("acct")
        sid = f"recon:sol:stake:{acct}"
        if not acct:
            return "NOOP"
        if so.get("reopen"):
            for r9 in self.conn.execute("SELECT posting_id, asset_id, location, qty_base FROM postings WHERE source_kind='opening'"
                                        " AND source_id=?", (sid,)).fetchall():
                self._bump_position(r9["asset_id"], -int(r9["qty_base"]), r9["location"])
                self.conn.execute("DELETE FROM postings WHERE posting_id=?", (r9["posting_id"],))
            self.conn.execute(
                "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                (sid + ":reopen", "opening_balance", "sol", json.dumps(so, ensure_ascii=False), int(time.time())))
        elif self.conn.execute("SELECT 1 FROM postings WHERE source_kind='opening' AND source_id=? LIMIT 1", (sid,)).fetchone() \
                or self.conn.execute("SELECT 1 FROM raw_observations WHERE obs_id=?", (sid + ":reopen",)).fetchone():
            return "NOOP"
        aid = self.asset_id("native", "sol", None, symbol="SOL", decimals=9)
        seq = 0
        for d in rec.get("deltas") or []:
            v = int(d.get("delta") or 0)
            if d.get("asset") != "native" or not v or ":stake:" not in (d.get("owner") or ""):
                continue
            loc = f"wallet:sol:{d['owner']}"
            self.conn.execute(
                "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                " VALUES ('opening', 'sol', ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening', 'OPENING', ?)",
                (sid, seq, ts, aid, loc, str(v), CLASSIFIER_VER))
            self._bump_position(aid, v, loc)
            seq += 1
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
            (sid, "opening_balance", "sol", json.dumps(so, ensure_ascii=False), int(time.time())))
        self._drop_daily_cache()
        if seq:
            dm("RECON", f"[sol] 스테이크 계정 기초잔고 {int(so.get('lamports') or 0) / 1e9:,.4f} SOL — {acct[:6]}…{acct[-4:]}"
                        f" (지갑 {str(so.get('wallet') or '')[:6]}…, 창 시작 기준)")
        return "OPENING"

    def _leg_px(self, aid: int, ts: int):
        r = self.conn.execute("SELECT kind, chain, address, symbol FROM assets WHERE asset_id=?",
                              (aid,)).fetchone()
        if not r:
            return None
        kind, chain, ca, sym = r["kind"], r["chain"], r["address"], (r["symbol"] or "").upper()
        if kind == "native":
            sym = sym or self.native_sym.get(chain, "")
            if sym in pricing.DOLLAR_NATIVES:
                return 1.0
            return self.px.candle_usd(sym, ts * 1000) if sym else None
        if kind == "token" and ca:
            st = pricing.STABLE_CAS.get(chain, {}).get(ca)
            if chain == "sol" and not st:
                st = pricing.STABLE_MINTS.get(ca)
            if st:
                return 1.0
            jst = pricing.JPY_STABLE_CAS.get(chain, {}).get(ca)
            if jst:
                return self.px.jpy_stable_usd(jst, ts * 1000)
            if ca == self.wrapped.get(chain):
                return self.px.candle_usd(self.native_sym.get(chain, "ETH"), ts * 1000)
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            sym = acct_norm.norm_ticker(sym)
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            cex9 = self.px.candle_usd(sym, ts * 1000) if sym else None
            vd9 = self._sym_px_verdict(aid, cex9, sym, ts * 1000) if cex9 else "unknown"
            if vd9 == "ok":
                return cex9
            cand9 = None if vd9 == "diff" else cex9
            chk9 = getattr(self.px, "token_usd_checked", None)
            return chk9(sym, ts * 1000, chain, ca, cand9) if chk9 else cand9
        return None

    def _is_stable_aid(self, aid: int) -> bool:
        r = self.conn.execute("SELECT kind, chain, address FROM assets WHERE asset_id=?",
                              (aid,)).fetchone()
        if not r or r["kind"] != "token" or not r["address"]:
            return False
        if pricing.STABLE_CAS.get(r["chain"], {}).get(r["address"]):
            return True
        return r["chain"] == "sol" and r["address"] in pricing.STABLE_MINTS

    OUT_PX_BAND = (Decimal("0.2"), Decimal("5"))

    def _sym_px_token(self, aid: int) -> bool:
        r = self.conn.execute("SELECT kind, chain, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not r or r["kind"] != "token" or not r["address"]:
            return False
        ch, ca = r["chain"], r["address"]
        if pricing.STABLE_CAS.get(ch, {}).get(ca) or (ch == "sol" and ca in pricing.STABLE_MINTS) \
                or pricing.JPY_STABLE_CAS.get(ch, {}).get(ca) or ca == self.wrapped.get(ch):
            return False
        return not spamguard.is_genuine(ch, ca)

    SYM_PX_BAND = (Decimal("0.5"), Decimal("2"))

    def _sym_px_proven(self, aid: int, px, sym: str = None, ts_ms: int = None) -> bool:
        return self._sym_px_verdict(aid, px, sym, ts_ms) == "ok"

    def _sym_px_verdict(self, aid: int, px, sym: str = None, ts_ms: int = None) -> str:
        try:
            if not self._sym_px_token(aid):
                return "ok"
            ven9 = None
            if sym and ts_ms is not None and hasattr(self.px, "candle_venue"):
                try:
                    ven9 = self.px.candle_venue(sym, ts_ms)
                except Exception:
                    ven9 = None
            vex9 = {"upbit_krw": "upbit"}.get(ven9, ven9)
            proof9 = self._ex_proven_venues(aid)
            coin9 = self._cg_coin_ids(sym, proof9)

            def venue_same(v9):
                if not coin9 or not v9:
                    return None
                ids9 = self._cg_venue_ids(v9, sym)
                if not ids9:
                    return None
                return bool(ids9 & coin9)
            known9 = vex9 not in (None, "coingecko", "legacy")
            same9 = venue_same(vex9) if known9 else None
            if same9 is False:
                return "diff"
            if proof9 and known9 and vex9 in proof9:
                return "ok"
            if same9 is True:
                return "ok"
            if vex9 == "legacy":
                if any(venue_same(v9) is False for v9 in ("binance", "bybit")):
                    return "diff"
                if proof9:
                    return "ok"
            elif proof9:
                return "unknown"
            if vex9 == "coingecko":
                return "unknown"
            u = self._own_unit_cost(aid)
            lo, hi = self.SYM_PX_BAND
            return "ok" if (bool(u) and lo <= Decimal(str(px)) / u <= hi) else "unknown"
        except (sqlite3.Error, InvalidOperation, ZeroDivisionError):
            return "unknown"

    @staticmethod
    def _cg_venue_ids(ex, sym):
        try:
            import candles as _cd
            return _cd.cg_ids(ex, sym, fetch=False) or set()
        except Exception:
            return set()

    def _cg_coin_ids(self, sym, proof):
        out9 = set()
        for ex9 in proof or ():
            out9 |= self._cg_venue_ids(ex9, sym)
        return out9

    def _ex_proven_venues(self, aid: int) -> set:
        cache = self.__dict__.setdefault("_ex_proven_v_cache", {})
        if aid in cache:
            return cache[aid]
        r = self.conn.execute("SELECT symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        sym = str((r["symbol"] if r else "") or "").strip().upper()
        out = set()
        if self.conn.execute("SELECT 1 FROM transfers WHERE asset_id=? AND ex_uuid IS NOT NULL LIMIT 1", (aid,)).fetchone():
            out.add("upbit")
        if sym:
            tx9 = self._ex_txid_venues()
            for p in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE asset_id=? AND source_kind='chain_tx'", (aid,)).fetchall():
                h = str(p["source_id"] or "")
                for ex9, cur9 in tx9.get(h.lower() if h.startswith("0x") else h, ()):
                    if cur9 == sym:
                        out.add(ex9)
        cache[aid] = out
        return out

    def _ex_txid_venues(self) -> dict:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(rowid) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone())
        except sqlite3.Error:
            return {}
        c9 = self.__dict__.get("_ex_txid_v_cache")
        if c9 and c9[0] == sig:
            return c9[1]
        m = {}
        for r in self.conn.execute("SELECT exchange, payload FROM raw_ex WHERE kind IN ('deposit','withdraw')"):
            try:
                p9 = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            t9 = str((p9 or {}).get("txid") or "").strip() if isinstance(p9, dict) else ""
            if t9:
                m.setdefault(t9.lower() if t9.startswith("0x") else t9, set()).add((str(r["exchange"] or "").lower(),
                                                                                  str(p9.get("currency") or "").upper()))
        self._ex_txid_v_cache = (sig, m)
        return m

    def _own_unit_cost(self, aid: int):
        tq, tc = Decimal(0), Decimal(0)
        with localcontext() as ctx:
            ctx.prec = 60
            for r in self.conn.execute(
                    "SELECT qty_base, cost_usd FROM postings WHERE asset_id=? AND leg_kind='acq' AND cost_usd IS NOT NULL"
                    " AND qty_base NOT LIKE '-%' AND qty_base != '0'", (aid,)).fetchall():
                try:
                    tq += Decimal(self._norm(aid, int(r["qty_base"])))
                    tc += Decimal(str(r["cost_usd"]))
                except (InvalidOperation, ValueError, TypeError):
                    continue
            return (tc / tq) if tq > 0 and tc > 0 else None

    def _ex_txids(self) -> dict:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(rowid) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone())
        except sqlite3.Error:
            return {}
        c9 = self.__dict__.get("_ex_txid_cache")
        if c9 and c9[0] == sig:
            return c9[1]
        m = {}
        for r in self.conn.execute("SELECT payload FROM raw_ex WHERE kind IN ('deposit','withdraw')"):
            try:
                p9 = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            t9 = str((p9 or {}).get("txid") or "").strip() if isinstance(p9, dict) else ""
            if not t9:
                continue
            m.setdefault(t9.lower() if t9.startswith("0x") else t9, set()).add(str(p9.get("currency") or "").upper())
        self._ex_txid_cache = (sig, m)
        return m

    def _ex_proven(self, aid: int) -> bool:
        cache = self.__dict__.setdefault("_ex_proven_cache", {})
        if aid in cache:
            return cache[aid]
        r = self.conn.execute("SELECT symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        sym = str((r["symbol"] if r else "") or "").strip().upper()
        ok = bool(self.conn.execute("SELECT 1 FROM transfers WHERE asset_id=? AND ex_uuid IS NOT NULL LIMIT 1", (aid,)).fetchone())
        if not ok and sym:
            tx9 = self._ex_txids()
            for p in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE asset_id=? AND source_kind='chain_tx'",
                                       (aid,)).fetchall():
                h = str(p["source_id"] or "")
                if sym in tx9.get(h.lower() if h.startswith("0x") else h, ()):
                    ok = True
                    break
        cache[aid] = ok
        return ok

    def _out_px(self, aid: int, px):
        if px and self._sym_px_token(aid) and not self._ex_proven(aid):
            u = self._own_unit_cost(aid)
            lo, hi = self.OUT_PX_BAND
            if not u or not (lo <= Decimal(str(px)) / u <= hi):
                return None
        return px

    def _out_px_band_fix_once(self) -> list:
        if self._meta_get("px_out_band_r"):
            return []
        lo, hi = self.OUT_PX_BAND
        changed = []
        try:
            for r in self.conn.execute(
                    "SELECT posting_id, asset_id, qty_base, cost_usd, source_ns, source_id FROM postings WHERE source_kind='chain_tx'"
                    " AND leg_kind='move_in' AND location LIKE 'out:%' AND cost_usd IS NOT NULL").fetchall():
                aid = r["asset_id"]
                if not self._sym_px_token(aid) or self._ex_proven(aid):
                    continue
                q9 = abs(Decimal(self._norm(aid, int(r["qty_base"]))))
                if q9 <= 0:
                    continue
                u = self._own_unit_cost(aid)
                if u and lo <= Decimal(str(r["cost_usd"])) / q9 / u <= hi:
                    continue
                self.conn.execute("UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE posting_id=?", (r["posting_id"],))
                changed.append((int(r["posting_id"]), r["source_ns"], r["source_id"], int(aid), str(r["cost_usd"])))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('px_out_band_r', ?)", (f"{int(time.time())}:{len(changed)}",))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        for pid, ns, sid, aid, usd in changed:
            log.warning("보낸 내역 시가 되돌림 posting %d %s %s asset %d $%s → NULL(새 규칙으로 재산정)", pid, ns, sid[:12], aid, usd)
        return changed

    def _price_tx(self, chain: str, txhash: str) -> int:
        legs = self.conn.execute(
            "SELECT posting_id, asset_id, qty_base, leg_kind, event, event_ts, cost_usd, location FROM postings"
            " WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
            (chain, txhash)).fetchall()
        if not legs:
            return 0
        ts = legs[0]["event_ts"]
        updates = {}
        with localcontext() as ctx:
            ctx.prec = 60

            def norm_abs(leg):
                return abs(Decimal(self._norm(leg["asset_id"], int(leg["qty_base"]))))

            for leg in legs:
                if leg["cost_usd"] is not None:
                    continue
                out9 = leg["leg_kind"] == "move_in" and str(leg["location"] or "").startswith("out:")
                if leg["leg_kind"] == "gas" or (str(leg["event"] or "").startswith("LP_")
                                                 and leg["leg_kind"] in ("disp", "acq")) or out9 \
                        or (leg["event"] == "STAKE_REWARD" and leg["leg_kind"] == "acq"):
                    px = self._leg_px(leg["asset_id"], ts)
                    if out9:
                        px = self._out_px(leg["asset_id"], px)
                    if px:
                        updates[leg["posting_id"]] = float(norm_abs(leg) * Decimal(str(px)))
            swap = [l for l in legs if l["event"] == "SWAP" and l["leg_kind"] in ("disp", "acq")]
            if swap and any(l["cost_usd"] is None for l in swap):
                outs = [l for l in swap if l["leg_kind"] == "disp"]
                ins = [l for l in swap if l["leg_kind"] == "acq"]

                def side_val(side):
                    vals = []
                    for l in side:
                        px = self._leg_px(l["asset_id"], ts)
                        vals.append(None if px is None else norm_abs(l) * Decimal(str(px)))
                    total = sum((v for v in vals if v is not None), Decimal(0))
                    return vals, total, all(v is not None for v in vals)

                out_vals, out_total, out_ok = side_val(outs)
                in_vals, in_total, in_ok = side_val(ins)
                stable_out = sum((v for l, v in zip(outs, out_vals)
                                  if v is not None and self._is_stable_aid(l["asset_id"])), Decimal(0))
                stable_in = sum((v for l, v in zip(ins, in_vals)
                                 if v is not None and self._is_stable_aid(l["asset_id"])), Decimal(0))
                if stable_out > 0 and all(self._is_stable_aid(l["asset_id"]) for l in outs):
                    V = stable_out
                elif stable_in > 0 and all(self._is_stable_aid(l["asset_id"]) for l in ins):
                    V = stable_in
                elif out_ok and out_total > 0:
                    V = out_total
                elif in_ok and in_total > 0:
                    V = in_total
                else:
                    V = None
                if V is not None:
                    def assign(side, vals, total, ok):
                        got = self._swap_split(V, vals, total, ok, [self._is_stable_aid(l["asset_id"]) for l in side])
                        if got is not None:
                            for l, v in zip(side, got):
                                updates[l["posting_id"]] = float(v)
                    assign(outs, out_vals, out_total, out_ok)
                    assign(ins, in_vals, in_total, in_ok)
                    if any(l["cost_usd"] is not None and l["posting_id"] not in updates for l in swap):
                        for l in swap:
                            updates.pop(l["posting_id"], None)
        if not updates:
            return 0
        fx = self.px.fx_at(ts * 1000)
        n9 = 0
        old9 = {l["posting_id"]: l["cost_usd"] for l in legs}
        for pid, usd in updates.items():
            try:
                if old9.get(pid) is not None and abs(float(old9[pid]) - usd) <= 1e-9 * max(1.0, abs(usd)):
                    continue
            except (TypeError, ValueError):
                pass
            cur9 = self.conn.execute(
                "UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=?"
                " AND (cost_usd IS NULL OR (event='SWAP' AND leg_kind IN ('disp','acq')))",
                (repr(usd), repr(usd * fx) if fx else None, pid))
            n9 += max(0, cur9.rowcount or 0)
        self.conn.commit()
        return n9

    @staticmethod
    def _swap_split(V, vals, total, ok, stable):
        n = len(vals)
        if n == 1:
            return [V]
        if ok and total > 0:
            return [V * v / total for v in vals]
        miss = [i for i, v in enumerate(vals) if v is None]
        if len(miss) == 1:
            known = sum((v for v in vals if v is not None), Decimal(0))
            if V - known > 0:
                return [(V - known) if i == miss[0] else vals[i] for i in range(n)]
        return None

    def _px_skip_json(self) -> str:
        try:
            sig = tuple(self.conn.execute("SELECT COUNT(*), MAX(asset_id) FROM assets").fetchone()) + (spamguard.user_sig(),)
        except sqlite3.Error:
            return self._px_skip[1]
        if sig != self._px_skip[0]:
            ids = []
            for r in self.conn.execute("SELECT asset_id, chain, address, symbol FROM assets WHERE kind='token' AND symbol IS NOT NULL"):
                s9 = r["symbol"] or ""
                if spamguard.impostor_of(s9) or spamguard.fake_major(s9, [(r["chain"], r["address"])]):
                    ids.append(int(r["asset_id"]))
            self._px_skip = (sig, json.dumps(ids))
        return self._px_skip[1]

    def _px_bulk_on(self) -> bool:
        return (self.cfg.get("backfill") or {}).get("px_prefetch") is not False

    def _leg_px_sym(self, aid: int):
        r = self.conn.execute("SELECT kind, chain, address, symbol FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not r:
            return None
        kind, chain, ca, sym = r["kind"], r["chain"], r["address"], (r["symbol"] or "").upper()
        if kind == "native":
            sym = sym or self.native_sym.get(chain, "")
            return None if sym in pricing.DOLLAR_NATIVES else (sym or None)
        if kind == "token" and ca:
            if pricing.STABLE_CAS.get(chain, {}).get(ca) or (chain == "sol" and pricing.STABLE_MINTS.get(ca)) \
                    or pricing.JPY_STABLE_CAS.get(chain, {}).get(ca):
                return None
            if ca == self.wrapped.get(chain):
                return self.native_sym.get(chain, "ETH")
            if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD"):
                return None
            sym = acct_norm.norm_ticker(sym)
            return None if sym in ("USDT", "USDC", "DAI", "USDG", "USDE", "CUSD", "USD1", "NUSD") else (sym or None)
        return None

    def _px_prefetch(self, rows, deadline: float):
        pairs, tss = [], []
        sym_of = {}
        for r in rows:
            for lg in self.conn.execute("SELECT asset_id, event_ts FROM postings WHERE source_kind='chain_tx'"
                                        " AND source_ns=? AND source_id=?", (r["chain"], r["txhash"])).fetchall():
                aid9 = int(lg["asset_id"])
                if aid9 not in sym_of:
                    sym_of[aid9] = self._leg_px_sym(aid9)
                ms9 = int(lg["event_ts"]) * 1000
                if sym_of[aid9]:
                    pairs.append((sym_of[aid9], ms9))
                tss.append(ms9)
        c9 = self.px.prefetch_candles(pairs, max_calls=PRICE_PREFETCH_CALLS, deadline=deadline) if pairs else {"calls": 0, "filled": 0}
        f9 = self.px.prefetch_fx(tss, max_calls=PRICE_PREFETCH_CALLS, deadline=deadline) if tss else {"calls": 0, "filled": 0}
        if c9["calls"] or f9["calls"]:
            log.info("가격 선조회: tx %d · 1분봉 %d콜 %d분 · 환율 %d콜 %d분", len(rows), c9["calls"], c9["filled"], f9["calls"], f9["filled"])

    def krw_fill_pass(self):
        if time.time() - getattr(self, "_last_krw_fill", 0) < KRW_FILL_SEC or not self._px_bulk_on():
            return
        self._last_krw_fill = time.time()
        fail = self.__dict__.setdefault("_krw_fill_fail", {})
        now9 = time.time()
        mins = [int(r[0]) for r in self.conn.execute(
            "SELECT DISTINCT (event_ts / 60) * 60 FROM postings WHERE cost_usd IS NOT NULL AND cost_krw IS NULL"
            " ORDER BY 1").fetchall() if now9 - fail.get(int(r[0]), 0) >= 3600]
        if not mins:
            return
        want = []
        for m9 in mins:
            if len(want) >= 4000:
                break
            want.append(m9)
        with self.px.lock:
            have0 = {m9 for m9 in want if str(m9 * 1000) in self.px.d["fx"]}
        st9 = self.px.prefetch_fx([m9 * 1000 for m9 in want if m9 not in have0], max_calls=KRW_FILL_CALLS,
                                  deadline=time.time() + 30) if len(have0) < len(want) else {"calls": 0, "filled": 0, "done": True}
        n9 = 0
        want9 = set(want)
        by_min = {}
        for r in self.conn.execute("SELECT posting_id, cost_usd, event_ts FROM postings WHERE cost_usd IS NOT NULL AND cost_krw IS NULL").fetchall():
            m9 = (int(r["event_ts"]) // 60) * 60
            if m9 in want9:
                by_min.setdefault(m9, []).append(r)
        for m9 in want:
            with self.px.lock:
                fx = self.px.d["fx"].get(str(m9 * 1000))
            if not fx:
                if st9.get("done"):
                    fail[m9] = now9
                continue
            for r in by_min.get(m9, ()):
                try:
                    krw9 = repr(float(r["cost_usd"]) * fx)
                except (TypeError, ValueError):
                    continue
                self.conn.execute("UPDATE postings SET cost_krw=? WHERE posting_id=? AND cost_krw IS NULL AND cost_usd=?",
                                  (krw9, r["posting_id"], r["cost_usd"]))
                n9 += 1
        self.conn.commit()
        if n9 or st9["calls"]:
            log.info("원화 원가 채움: %d레그 (환율 %d콜 · 남은 분 %d)", n9, st9["calls"], max(0, len(mins) - len(want)))

    def price_pass(self):
        if time.time() - self._last_price_pass < PRICE_IDLE_SEC:
            return
        self._last_price_pass = time.time()
        self._ex_proven_cache = {}
        self._ex_proven_v_cache = {}
        now9 = time.time()
        boff = self.__dict__.setdefault("_px_backoff", {})
        cand = [r for r in self.conn.execute(
            "SELECT source_ns AS chain, source_id AS txhash, MIN(event_ts) AS ts FROM postings"
            " WHERE source_kind='chain_tx' AND cost_usd IS NULL"
            " AND (leg_kind='gas' OR (event='SWAP' AND leg_kind IN ('disp','acq'))"
            "      OR (event LIKE 'LP\\_%' ESCAPE '\\' AND leg_kind IN ('disp','acq'))"
            "      OR (event='STAKE_REWARD' AND leg_kind='acq')"
            "      OR (leg_kind='move_in' AND location LIKE 'out:%'"
            "          AND asset_id NOT IN (SELECT value FROM json_each(?))))"
            " GROUP BY source_ns, source_id",
            (self._px_skip_json(),)).fetchall()
            if boff.get((r["chain"], r["txhash"]), (0, 0))[0] <= now9]
        bulk = len(cand) > PRICE_BATCH * 3 and self._px_bulk_on()
        if bulk:
            cand.sort(key=lambda r9: (int(r9["ts"] or 0), r9["chain"], r9["txhash"]))
            i9 = random.randrange(len(cand))
            rows = (cand[i9:] + cand[:i9])[:PRICE_BULK_BATCH]
            try:
                self._px_prefetch(rows, time.time() + PRICE_BULK_BUDGET)
            except Exception as e:
                log.warning("가격 선조회 실패(단건 조회로 계속): %s", e)
        else:
            rows = random.sample(cand, PRICE_BATCH) if len(cand) > PRICE_BATCH else cand
        t_end9 = time.time() + PRICE_BULK_BUDGET
        done = 0
        filled = 0
        for i9, r in enumerate(rows):
            if bulk and i9 >= PRICE_BATCH and time.time() > t_end9:
                break
            k9 = (r["chain"], r["txhash"])
            try:
                if self._price_tx(r["chain"], r["txhash"]):
                    filled += 1
                    boff.pop(k9, None)
                else:
                    d9 = min(PRICE_BACKOFF_MAX, max(PRICE_BACKOFF_MIN, boff.get(k9, (0, 0))[1] * 2))
                    boff[k9] = (time.time() + d9, d9)
                done += 1
            except Exception as e:
                self.conn.rollback()
                log.warning("가격패스 %s %s 실패(다음 주기 재시도): %s", r["chain"], r["txhash"][:12], e)
        if len(boff) > 50000:
            for k9 in [k for k, v in boff.items() if v[0] <= now9][:25000]:
                boff.pop(k9, None)
        ex_rows = self.conn.execute(
            "SELECT posting_id, event_ts, cost_krw FROM postings"
            " WHERE source_kind='exchange' AND cost_usd IS NULL AND cost_krw IS NOT NULL"
            " ORDER BY RANDOM() LIMIT ?", (PRICE_BATCH,)).fetchall()
        ex_done = 0
        for r in ex_rows:
            fx = self.px.fx_at(r["event_ts"] * 1000)
            time.sleep(0.2)
            if fx is None:
                break
            if fx:
                try:
                    usd = float(r["cost_krw"]) / fx
                except (TypeError, ValueError):
                    continue
                self.conn.execute("UPDATE postings SET cost_usd=? WHERE posting_id=?"
                                  " AND cost_usd IS NULL", (repr(usd), r["posting_id"]))
                ex_done += 1
        exf_rows = self.conn.execute(
            "SELECT DISTINCT source_ns, source_id, event_ts FROM postings"
            " WHERE source_kind='exchange' AND source_ns LIKE '%:trade'"
            " AND cost_usd IS NULL AND leg_seq=0"
            " ORDER BY RANDOM() LIMIT ?", (PRICE_BATCH,)).fetchall()
        exf_done = 0
        for r in exf_rows:
            ex9 = r["source_ns"].rsplit(":", 1)[0]
            raw9 = self.conn.execute(
                "SELECT payload FROM raw_ex WHERE exchange=? AND kind='trade' AND uuid=?"
                " ORDER BY revision DESC LIMIT 1", (ex9, r["source_id"])).fetchone()
            if not raw9:
                continue
            try:
                f9 = json.loads(raw9["payload"])
                qty9 = Decimal(str(f9.get("qty") or "0"))
                px99 = Decimal(str(f9.get("price") or "0"))
            except (json.JSONDecodeError, ArithmeticError):
                continue
            qu9 = self._quote_usd(str(f9.get("quote") or ""), int(r["event_ts"]))
            time.sleep(0.1)
            if qu9 is None or qty9 <= 0 or px99 <= 0:
                continue
            usd9 = float(qty9 * px99 * qu9)
            fx99 = self.px.fx_at(int(r["event_ts"]) * 1000)
            self.conn.execute(
                "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_ns=? AND source_id=?"
                " AND leg_seq IN (0, 1) AND cost_usd IS NULL",
                (repr(usd9), repr(usd9 * fx99) if fx99 else None,
                 r["source_ns"], r["source_id"]))
            exf_done += 1
        self._price_upbit_quote_fills(PRICE_BATCH)
        self.conn.commit()
        if ex_rows:
            log.info("가격패스(거래소): %d/%d 환산", ex_done, len(ex_rows))
        if exf_rows:
            log.info("가격패스(해외체결): %d/%d 환산", exf_done, len(exf_rows))
        if filled:
            log.info("가격패스: %d tx 원가 채움 (시도 %d)", filled, done)
        self.px.flush()

    def _price_upbit_quote_fills(self, limit: int) -> int:
        n9 = 0
        ubq_rows = self.conn.execute(
            "SELECT DISTINCT source_id FROM postings WHERE source_ns='upbit:order' AND leg_seq=0"
            " AND cost_usd IS NULL AND cost_krw IS NULL ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()
        for r in ubq_rows:
            raw9 = self.conn.execute(
                "SELECT payload FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid=?"
                " ORDER BY revision DESC LIMIT 1", (r["source_id"],)).fetchone()
            try:
                o9 = json.loads(raw9["payload"]) if raw9 else None
            except json.JSONDecodeError:
                o9 = None
            p9 = self._upbit_quote_fill_legs(o9) if isinstance(o9, dict) else None
            if p9 is None:
                continue
            qu9 = self._quote_usd(p9[1], p9[4])
            time.sleep(0.1)
            if qu9 is None:
                continue
            usd9 = float(Decimal(abs(p9[3])) / (Decimal(10) ** 8) * qu9)
            fx99 = self.px.fx_at(p9[4] * 1000)
            self.conn.execute(
                "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_ns='upbit:order' AND source_id=?"
                " AND leg_seq IN (0, 1) AND cost_usd IS NULL",
                (repr(usd9), repr(usd9 * fx99) if fx99 else None, r["source_id"]))
            n9 += 1
        return n9

    def deposit_rematch_pass(self):
        if time.time() - getattr(self, "_last_rematch", 0) < 120:
            return
        self._last_rematch = time.time()
        now = int(time.time())
        rows = self.conn.execute(
            "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
            " AND uuid NOT IN (SELECT ex_uuid FROM transfers WHERE ex_uuid IS NOT NULL)"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall()
        n = 0
        for d in rows:
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            if str(p.get("state") or "").upper() != "ACCEPTED":
                continue
            txid = str(p.get("txid") or "")
            if not txid:
                continue
            linked = self._link_transfers(d["uuid"], txid, p.get("currency"), now)
            if not linked:
                continue
            dep_ts = self._iso_ts(p.get("done_at") or p.get("created_at")) or now
            self._post_ex_deposit(d["uuid"], p, dep_ts)
            n += linked
        for d in self.conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='withdraw' AND exchange='upbit'"
                " AND uuid NOT IN (SELECT source_id FROM postings WHERE source_ns='upbit:withdraw')"
                " GROUP BY uuid HAVING revision = MAX(revision) ORDER BY observed_at, uuid").fetchall():
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            if self._post_ex_withdraw(d["uuid"], p):
                n += 1
        for d in self.conn.execute(
                "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
                " AND uuid NOT IN (SELECT source_id FROM postings WHERE source_ns='upbit:deposit')"
                " GROUP BY uuid HAVING revision = MAX(revision) ORDER BY observed_at, uuid").fetchall():
            try:
                p = json.loads(d["payload"])
            except json.JSONDecodeError:
                continue
            dep_ts = self._iso_ts(p.get("done_at") or p.get("created_at")) or now
            if self._post_ex_deposit(d["uuid"], p, dep_ts):
                log.info("자가치유: posting 없던 업비트 입금 기장 uuid=%s", d["uuid"][:12])
                n += 1
        for exkind, st_need, poster in (("withdraw", "DONE", self._post_exf_withdraw),
                                        ("deposit", "ACCEPTED", self._post_exf_deposit_in)):
            for d in self.conn.execute(
                    "SELECT exchange, uuid, payload FROM raw_ex WHERE kind=?"
                    " AND exchange != 'upbit'"
                    " AND NOT EXISTS (SELECT 1 FROM postings p WHERE p.source_kind = 'exchange' AND p.source_ns ="
                    "   raw_ex.exchange || ':' || raw_ex.kind AND p.source_id = raw_ex.uuid)"
                    " GROUP BY exchange, uuid HAVING revision = MAX(revision)",
                    (exkind,)).fetchall():
                try:
                    p = json.loads(d["payload"])
                except json.JSONDecodeError:
                    continue
                if str(p.get("state") or "").upper() != st_need:
                    continue
                if poster(d["exchange"], d["uuid"], p):
                    n += 1
        self.conn.commit()
        if n:
            log.info("입금 재대사: %d건 추가 매칭", n)

    def exchange_recon_pass(self, drained=frozenset()):
        if self._meta_get("recon_done_upbit") or \
                time.time() - getattr(self, "_last_exrecon", 0) < 300:
            return
        self._last_exrecon = time.time()
        st_p = os.path.join(common.STATE_DIR, "upbit_orders_state.json")
        bal_p = os.path.join(common.STATE_DIR, "upbit_balances.json")
        st = common.read_json(st_p, {}) if os.path.exists(st_p) else {}
        bal = common.read_json(bal_p, {}) if os.path.exists(bal_p) else {}
        if not st.get("complete") or "ex" not in drained:
            return
        if time.time() - float(st.get("backfilled_until") or 0) > 8 * 86400:
            return
        if time.time() - (bal.get("ts") or 0) > common.upbit_fresh_sec(self.cfg):
            return
        inflight = set()
        last_obs = 0
        for r_if in self.conn.execute(
                "SELECT r.kind, r.payload, r.observed_at FROM raw_ex r JOIN"
                " (SELECT exchange, kind, uuid, max(revision) AS revision FROM raw_ex WHERE exchange='upbit'"
                "  AND kind IN ('deposit','withdraw') GROUP BY exchange, kind, uuid) x"
                " ON x.exchange=r.exchange AND x.kind=r.kind AND x.uuid=r.uuid AND x.revision=r.revision"):
            last_obs = max(last_obs, int(r_if["observed_at"] or 0))
            try:
                p_if = json.loads(r_if["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            st_if = str(p_if.get("state") or "").upper()
            if st_if and st_if not in self.EX_TERMINAL_STATES:
                inflight.add(str(p_if.get("currency") or "").upper())
            elif st_if in ("DONE", "ACCEPTED") and not self._iso_ts(p_if.get("created_at") or p_if.get("done_at")):
                inflight.add(str(p_if.get("currency") or "").upper())
        if last_obs - int(bal.get("ts") or 0) > 120:
            log.info("거래소 잔고 대사 보류 — 잔고 스냅샷(%d)이 마지막 원본 동기화(%d)보다 오래됨", int(bal.get("ts") or 0), last_obs)
            return
        actual = {}
        locked_now = set(inflight)
        accounts = bal.get("accounts")
        if not isinstance(accounts, list):
            raise ValueError("업비트 잔고 accounts 형식 오류 — 대사 보류")
        for a in accounts:
            if not isinstance(a, dict):
                raise ValueError("업비트 잔고 행 형식 오류 — 대사 보류")
            cur = str(a.get("currency") or "").strip().upper()
            if not cur:
                raise ValueError("업비트 잔고 currency 누락 — 대사 보류")
            if cur == "KRW":
                continue
            try:
                if a["locked"] is None or a["balance"] is None or isinstance(a["locked"], bool) or isinstance(a["balance"], bool):
                    raise TypeError("null")
                locked_v = Decimal(str(a["locked"]).strip())
                balance_v = Decimal(str(a["balance"]).strip())
            except (KeyError, TypeError, ValueError, ArithmeticError) as e:
                raise ValueError(f"업비트 잔고 파싱 실패 {cur}: {a.get('balance')!r}/{a.get('locked')!r}") from e
            if not (balance_v.is_finite() and locked_v.is_finite()):
                raise ValueError(f"업비트 잔고 비유한값 {cur}")
            actual[cur] = balance_v + locked_v
            if locked_v > 0:
                locked_now.add(cur)
        oo = bal.get("open_orders")
        pend_fill = {}
        if isinstance(oo, list):
            oo_ok = True
            oo_uuids = set()
            for o9 in oo:
                if not isinstance(o9, dict) or not o9.get("uuid"):
                    oo_ok = False
                    break
                oo_uuids.add(str(o9["uuid"]))
                p9 = self._upbit_open_partial(o9)
                if p9 is None:
                    oo_ok = False
                    break
                for sym9, dq in p9.items():
                    pend_fill[sym9] = pend_fill.get(sym9, Decimal(0)) + dq
            if oo_ok:
                locked_now = set(inflight)
                bts9 = int(bal.get("ts") or 0)
                in9 = (" OR uuid IN (%s)" % ",".join("?" * len(oo_uuids))) if oo_uuids else ""
                for r_o in self.conn.execute(
                        "SELECT uuid, payload, observed_at FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                        " AND (observed_at >= ?" + in9 + ")", (bts9 - 5, *sorted(oo_uuids))).fetchall():
                    try:
                        mk9 = str(json.loads(r_o["payload"]).get("market") or "")
                    except (json.JSONDecodeError, TypeError):
                        mk9 = ""
                    for s9 in (mk9.split("-", 1) if "-" in mk9 else []):
                        if s9.upper() != "KRW":
                            locked_now.add(s9.upper())
            else:
                pend_fill = {}
        for sym9, dq in pend_fill.items():
            if sym9 in actual:
                actual[sym9] = actual[sym9] - Decimal(str(dq))
        ledger = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, a.symbol, a.decimals FROM postings p"
                " JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location='exchange:upbit'").fetchall():
            sym = (r["symbol"] or "").upper()
            if not sym:
                continue
            ledger.setdefault(sym, {}).setdefault(r["asset_id"], [0, r["decimals"]])
            ledger[sym][r["asset_id"]][0] += int(r["qty_base"])
        now = int(time.time())
        anchor_ts = int(bal.get("ts") or now)
        n_adj = 0
        n_locked_skip = 0
        for sym, insts in ledger.items():
            total_norm = Decimal(0)
            for aid, (s, dec) in insts.items():
                dec = dec if dec is not None else 18
                total_norm += Decimal(s) / (Decimal(10) ** int(dec))
            tgt = Decimal(str(actual.get(sym, 0)))
            diff = tgt - total_norm
            if abs(diff) <= self.EX_RECON_TOL:
                continue
            if sym in locked_now:
                n_locked_skip += 1
                continue
            main_aid, main_dec = self._upbit_asset(sym), 8
            qb = int(diff * (Decimal(10) ** main_dec))
            if qb == 0:
                continue
            ev_ts9 = self._win_t0(anchor_ts, "upbit") if (qb > 0 and self.recon_months > 0) else anchor_ts
            cur9 = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                " classifier_ver) VALUES ('exchange', 'upbit:recon', ?, 0, ?, ?,"
                " 'exchange:upbit', ?, NULL, NULL, 'opening', 'EX_ADJUST', ?)",
                (f"exrecon:{sym}:{anchor_ts}", ev_ts9, main_aid, str(qb), CLASSIFIER_VER))
            if cur9.rowcount:
                self._bump_position(main_aid, qb, "exchange:upbit")
                n_adj += 1
        if n_locked_skip:
            self.conn.commit()
            sig9 = (n_adj, n_locked_skip)
            if n_adj or sig9 != getattr(self, "_exr_partial_sig", None) \
                    or time.time() - getattr(self, "_exr_partial_log", 0) > 3600:
                self._exr_partial_sig = sig9
                self._exr_partial_log = time.time()
                log.info("거래소 잔고 대사 부분 완료: %d 보정, %d 통화는 주문 진행 중 — 재시도 예정",
                         n_adj, n_locked_skip)
            return
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_upbit', ?)",
                          (str(anchor_ts),))
        self.conn.commit()
        log.info("★거래소 잔고 대사 완료: %d개 통화 보정★", n_adj)
        dm("EX_RECON", f"업비트 잔고 대사 완료 — {n_adj}개 통화 보정")

    def _meta_get(self, k: str):
        r = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None

    def _sol_rpc_url(self):
        key = os.environ.get("TJ_HELIUS_KEY", "")
        if not key:
            key = common.read_env_file().get("TJ_HELIUS_KEY", "")
        sol = self.cfg.get("sol", {})
        if sol.get("rpc") == "helius" and key:
            return f"https://mainnet.helius-rpc.com/?api-key={key}"
        return sol.get("rpc") or sol.get("rpc_fallback")

    @staticmethod
    def _synced(cur: dict, max_age: float = 600, key: str = "_synced_at") -> bool:
        try:
            return time.time() - float(cur.get(key) or 0) < max_age
        except (TypeError, ValueError):
            return False

    def _scope_ready(self, scope: str) -> bool:
        sd = common.STATE_DIR
        if scope == "sol":
            cur = common.read_json(os.path.join(sd, "cursor_sol.json"), {})
            return self._synced(cur) and all(o in cur for o in self.sol_wallets)
        if scope == "bsc":
            cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            head, frm = int(cur.get("head") or 0), int(cur.get("from_block") or 0)
            return self._synced(cur) and head > 0 and frm > 0 and head - frm < 3000
        cur = common.read_json(os.path.join(sd, f"cursor_evm_{scope}.json"), {})
        pend = common.read_json(os.path.join(sd, f"pending_detail_{scope}.json"), {})
        enr = common.read_json(os.path.join(sd, f"enrich_{scope}.json"), {})
        return self._synced(cur) and not pend and not enr \
            and all(w in cur for w in self.my_wallets.get(scope, set()))

    def _scope_ready_tok(self, scope: str) -> bool:
        if scope in ("sol", "bsc"):
            return False
        if self._scope_ready(scope):
            return True
        sd = common.STATE_DIR
        cur = common.read_json(os.path.join(sd, f"cursor_evm_{scope}.json"), {})
        if not (isinstance(cur.get("_ext_internal_pending"), dict) or isinstance(cur.get("_ext_internal_lag"), dict)):
            return False
        pend = common.read_json(os.path.join(sd, f"pending_detail_{scope}.json"), {})
        return self._synced(cur, key="_synced_tok_at") and not pend \
            and all(w in cur for w in self.my_wallets.get(scope, set()))

    NATX_STALL_HOURS = 24.0

    def _scope_ready_natx(self, scope: str) -> bool:
        if scope in ("sol", "bsc"):
            return False
        cc = (self.cfg.get("chains") or {}).get(scope) or {}
        if common.chain_discovery(scope, cc) == "rpc":
            return False
        try:
            hrs = float(self.cfg.get("recon_native_stall_hours", self.NATX_STALL_HOURS))
        except (TypeError, ValueError):
            hrs = self.NATX_STALL_HOURS
        if hrs <= 0 or self._scope_ready(scope) or not self._scope_ready_tok(scope):
            return False
        cur = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{scope}.json"), {})
        since = cur.get("_int_lag_since")
        if not isinstance(cur.get("_ext_internal_lag"), dict) or not isinstance(since, int) or isinstance(since, bool):
            return False
        return time.time() - since >= hrs * 3600

    def _wrecon_times(self, chain: str) -> dict:
        out = {}
        done = {}
        for k, v in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE ?", (f"wrecon_done:{chain}:%",)).fetchall():
            try:
                done[k.split(":", 2)[2].lower()] = int(float(v))
            except (TypeError, ValueError, IndexError):
                continue
        for w, t in done.items():
            out[w] = (t, t, False)
        for k, v in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE ?", (f"wrecon_tok:{chain}:%",)).fetchall():
            if not k.startswith(f"wrecon_tok:{chain}:"):
                continue
            try:
                w = k.split(":", 2)[2].lower()
                out[w] = (int(float(v)), done.get(w), True)
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def _posted_sums(self, chain: str) -> dict:
        out = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, p.location FROM postings p JOIN assets a"
                " ON a.asset_id = p.asset_id WHERE a.chain=?"
                " AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            key = (w, r["asset_id"])
            out[key] = out.get(key, 0) + int(r["qty_base"])
        return out

    def _rpc_recon_reset(self):
        for c, cc in (self.cfg.get("chains") or {}).items():
            if common.chain_discovery(c, cc) != "rpc" or not self._meta_get(f"recon_done_{c}") \
                    or self._meta_get(f"recon_reset_rpc_{c}"):
                continue
            cur = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{c}.json"), {})
            if not cur.get("_rpc_v") or not self._scope_ready(c):
                continue
            n_open = self.conn.execute("SELECT count(*) FROM postings WHERE source_kind='opening' AND source_id=?",
                                       (f"recon:{c}",)).fetchone()[0]
            if n_open:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_reset_rpc_{c}", "skipped_existing_opening"))
                self.conn.commit()
                log.warning("%s RPC 재대사 건너뜀 — 기존 opening %d건(수동 확인)", c, n_open)
                continue
            self.conn.execute("DELETE FROM meta WHERE k=?", (f"recon_done_{c}",))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_reset_rpc_{c}", str(int(time.time()))))
            self.conn.commit()
            self.__dict__.get("_recon_cache", {}).pop(c, None)
            log.warning("★%s RPC 백필 완료 → 탐색기 시절 대사 도장 해제, 온체인 잔고로 재대사★", c)

    def _recon_fetch(self, chain: str, kind: str, wallets: list) -> dict:
        return self._recon_fetch_plan(chain, kind, wallets)()

    def _recon_fetch_plan(self, chain: str, kind: str, wallets: list, mode: str = None):
        wallets = list(wallets)
        if kind == "sol":
            url9 = self._sol_rpc_url()
            return lambda: recon.fetch_sol_balances(url9, wallets)
        if kind == "bsc":
            cas = {}
            for r in self.conn.execute(
                    "SELECT address, symbol, decimals FROM assets"
                    " WHERE chain='bsc' AND kind='token'").fetchall():
                if r["address"]:
                    cas[r["address"]] = (r["symbol"], r["decimals"] if r["decimals"] is not None else self._meta_dec("bsc", r["address"]))
            rpcs8 = list(self.cfg["bsc"]["detail_rpcs"])
            return lambda: recon.fetch_bsc_balances(rpcs8, wallets, cas)
        cc9 = self.cfg["chains"][chain]
        rpc_only9 = common.chain_discovery(chain, cc9) == "rpc"
        bsoff9 = common.bs_blocked(chain, cc9)
        base9 = None if (rpc_only9 or bsoff9 or not cc9.get("blockscout")) else str(cc9["blockscout"]).rstrip("/")
        from evm_watch import RpcSynthMixin as _RS
        rpcs9 = list(cc9.get("rpcs") or _RS.RPC_DEFAULT.get(chain) or [])
        if not rpcs9:
            log.error("recon %s 보류 — RPC 없음(chains.%s.rpcs 필요): 블록스카웃 잔고는 대사 정본으로 쓰지 않는다", chain, chain)

            def _no_rpc(chain=chain):
                raise RuntimeError(f"recon {chain} RPC 없음 — 대사 보류")
            return _no_rpc
        cas = {}
        for r in self.conn.execute("SELECT address, symbol, decimals FROM assets WHERE chain=? AND kind='token'", (chain,)).fetchall():
            if r["address"]:
                cas[str(r["address"]).lower()] = (r["symbol"], r["decimals"] if r["decimals"] is not None else self._meta_dec(chain, r["address"]))
        rt9 = set()
        for ca9, meta9 in ((cc9.get("recon_tokens") or {}).items()):
            ca9 = str(ca9).lower()
            if ca9 and isinstance(meta9, (list, tuple)) and len(meta9) == 2:
                try:
                    m9 = (str(meta9[0]), int(meta9[1]))
                except (TypeError, ValueError):
                    continue
                rt9.add(ca9)
                cas.setdefault(ca9, m9)
        must = {str(w).lower(): set(rt9) for w in wallets}
        strict9 = self._recon_strict_fn(chain)
        cur9 = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {})
        try:
            blk9 = min(int(cur9.get(w, cur9.get(str(w).lower()))) for w in wallets)
        except (TypeError, ValueError):
            blk9 = None
        if not blk9 or blk9 <= 0:
            def _no_cur(chain=chain):
                raise RuntimeError(f"recon {chain} 수집기 커서 블록 없음 — 대사 보류")
            return _no_cur
        wcas = {str(w).lower(): set(rt9) for w in wallets}
        for r in self.conn.execute("SELECT DISTINCT p.location, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                   " WHERE a.chain=? AND a.kind='token' AND p.location LIKE ?", (chain, f"wallet:{chain}:%")).fetchall():
            parts = str(r[0] or "").split(":")
            if len(parts) == 3 and parts[2].lower() in wcas and r[1]:
                wcas[parts[2].lower()].add(str(r[1]).lower())
        excl = {x[0] for x in (common.NATIVE_MIRROR.get(chain), common.ZK_STACK.get(chain)) if x}
        mc9 = recon.MULTICALL3_BY_CHAIN.get(chain, recon.MULTICALL3)
        nat9 = mode in ("nat", "natx")
        sweep9 = None
        if bsoff9 and not nat9:
            sweep9 = {str(k).lower(): str(v) for tab9 in (pricing.STABLE_CAS, pricing.JPY_STABLE_CAS) for k, v in (tab9.get(chain) or {}).items()}
        return lambda: recon.fetch_evm_rpc_balances(rpcs9, wallets, cas, discover_url=None if nat9 else base9, must=must,
                                                    exclude=excl, want_native=mode != "tok", want_tokens=not nat9,
                                                    multicall=mc9, wallet_cas=wcas, block=blk9, strict=strict9, sweep=sweep9)

    @staticmethod
    def _recon_src(bal: dict, wallets=None) -> dict:
        if isinstance(bal, dict) and bal.get("_source") == "rpc" and isinstance(bal.get("_block"), int):
            out = {"_source": "rpc", "_block": int(bal["_block"])}
            if wallets is None:
                wallets = list((bal.get("_unobs") or {}).keys())
            un = sorted(f"{str(w).lower()}:{str(ca).lower()}" for w in wallets for ca in ((bal.get("_unobs") or {}).get(w) or ()))
            if un:
                out["_unobs"] = un
            qd = bal.get("_queried")
            if isinstance(qd, dict):
                out["_q"] = sorted(f"{str(w).lower()}:{str(ca).lower()}" for w in wallets for ca in (qd.get(w) or qd.get(str(w).lower()) or ()))
            return out
        return {}

    def _recon_strict_fn(self, chain: str):
        spamguard.is_genuine(chain, "0x0")
        st9 = {str(k).lower() for k in (pricing.STABLE_CAS.get(chain) or {})}
        jp9 = {str(k).lower() for k in (pricing.JPY_STABLE_CAS.get(chain) or {})}
        wr9 = str(self.wrapped.get(chain) or "").lower()

        def strict(ca, chain=chain):
            ca = str(ca).lower()
            return ca in st9 or ca in jp9 or (wr9 and ca == wr9) or spamguard.is_genuine(chain, ca)
        return strict

    def _posted_sums_at(self, chain: str, blk: int):
        out, unknown = {}, set()
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, p.location, p.source_kind, r.block FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                " LEFT JOIN raw_txs r ON p.source_kind = 'chain_tx' AND r.chain = p.source_ns AND r.txhash = p.source_id"
                " WHERE a.chain=? AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            if r["source_kind"] == "chain_tx":
                try:
                    b9 = int(r["block"])
                except (TypeError, ValueError):
                    unknown.add(w)
                    continue
                if b9 > blk:
                    continue
            key = (w, r["asset_id"])
            out[key] = out.get(key, 0) + int(r["qty_base"])
        return out, unknown

    def _recon_at(self, chain: str, bal: dict):
        if isinstance(bal, dict) and bal.get("_source") == "rpc" and isinstance(bal.get("_block"), int) \
                and isinstance(bal.get("_block_ts"), int):
            sums, unk = self._posted_sums_at(chain, int(bal["_block"]))
            return sums, unk, int(bal["_block_ts"]) + 1
        return self._posted_sums(chain), set(), int(time.time())

    def _obs_block(self, sid: str):
        cache = self.__dict__.setdefault("_obs_block_cache", {})
        r = self.conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
        key = (sid, r[1] if r else None)
        if key not in cache:
            try:
                d = json.loads(r[0]) if r and r[0] else {}
            except (TypeError, ValueError):
                d = {}
            b = d.get("_block") if isinstance(d, dict) else None
            cache[key] = int(b) if isinstance(b, int) and not isinstance(b, bool) else None
        return cache[key]

    def _absorbed(self, sid: str, ts: int, T: int, blk) -> bool:
        B = self._obs_block(sid)
        if B is not None and blk is not None:
            try:
                return int(blk) <= B
            except (TypeError, ValueError):
                pass
        return ts < T

    def _tx_block(self, chain: str, txhash: str):
        r = self.conn.execute("SELECT block FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone() if txhash else None
        try:
            return int(r[0]) if r and r[0] is not None else None
        except (TypeError, ValueError):
            return None

    def _recon_q_aids(self, chain: str, bal: dict):
        qd = (bal or {}).get("_queried") if isinstance(bal, dict) and bal.get("_source") == "rpc" else None
        if not isinstance(qd, dict):
            return None
        out = {}
        for w, cas in qd.items():
            s9 = out.setdefault(w, set())
            for ca in cas or ():
                r = self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='token' AND lower(address)=?",
                                      (chain, str(ca).lower())).fetchone()
                if r:
                    s9.add(r[0])
        return out

    def _recon_unobs_aids(self, chain: str, bal: dict) -> dict:
        out = {}
        for w, cas in ((bal or {}).get("_unobs") or {}).items():
            for ca in cas or ():
                r = self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='token' AND lower(address)=?",
                                      (chain, str(ca).lower())).fetchone()
                if r:
                    out.setdefault(w, set()).add(r[0])
        return out

    def _obs_cov(self, sid: str):
        cache = self.__dict__.setdefault("_obs_cov_cache", {})
        r = self.conn.execute("SELECT payload, observed_at FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
        key = (sid, r[1] if r else None)
        if key not in cache:
            try:
                d = json.loads(r[0]) if r and r[0] else {}
            except (TypeError, ValueError):
                d = {}
            u = d.get("_unobs") if isinstance(d, dict) else None
            q = d.get("_q") if isinstance(d, dict) else None
            cache[key] = ({str(x).lower() for x in u} if isinstance(u, list) else set(),
                          {str(x).lower() for x in q} if isinstance(q, list) else None)
        return cache[key]

    @staticmethod
    def _obs_wallet_pay(wb: dict, zeros=None, keep=None) -> dict:
        out = {f"{k[0]}:{k[1]}": v for k, v in (wb or {}).items() if keep is None or keep(k)}
        for ca in zeros or ():
            if ca and (keep is None or keep(("token", ca))):
                out.setdefault(f"token:{ca}", 0)
        return out

    def _obs_tok_observed(self, sid: str, w: str, ca: str) -> bool:
        un, q = self._obs_cov(sid)
        k9 = f"{str(w).lower()}:{str(ca or '').lower()}"
        return k9 not in un and (q is None or k9 in q)

    def _recon_onchain(self, chain: str, bal: dict) -> dict:
        onchain = {}
        meta_hint = bal.get("_meta") or {}
        for w, wb in (bal.get("per_wallet") or {}).items():
            for (k2, addr), amount in wb.items():
                if k2 == "native":
                    aid = self.asset_id("native", chain, None,
                                        symbol=self.native_sym.get(chain, chain.upper()),
                                        decimals=9 if chain == "sol" else 18)
                else:
                    hint = meta_hint.get(addr, (None, None))
                    aid = self.asset_id("token", chain, addr, symbol=hint[0], decimals=hint[1])
                onchain[(w, aid)] = amount
        return onchain

    RECON_WAIT_SEC = 8.0
    RECON_MAX_JOBS = 4
    RECON_PENDING_SCAN = 2000
    RECON_DEFER_MAX_SEC = 900

    def _recon_pending_chains(self):
        out = set()
        for stream, reader in (("evm", self.reader), ("sol", self.sol_reader), ("bsc", self.bsc_reader)):
            row = self.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            seg, off = (row["seg"], row["off"]) if row else (1, 0)
            batch, _, _ = reader.read_batch(seg, off, max_records=self.RECON_PENDING_SCAN)
            if len(batch) >= self.RECON_PENDING_SCAN:
                return None
            for rec, _s, _o in batch:
                if not isinstance(rec, dict) or rec.get("chain") is None:
                    return None
                out.add(str(rec["chain"]).lower())
        return out

    def _recon_pending(self, chain: str) -> bool:
        pend = self._recon_pending_chains()
        return pend is None or str(chain).lower() in pend

    def _recon_quiet(self, chain: str, stream: str, drained: set) -> bool:
        if stream in drained:
            return True
        cache = self.__dict__.get("_recon_pend_pass")
        if cache is None or cache[0] is not True:
            cache = (True, self._recon_pending_chains())
            if "_recon_pend_pass" in self.__dict__:
                self._recon_pend_pass = cache
        pend = cache[1]
        return pend is not None and str(chain).lower() not in pend

    def _recon_fp(self, chain: str, wallets=None):
        n, mx, sums = 0, 0, {}
        wset = None if wallets is None else set(wallets)
        for r in self.conn.execute(
                "SELECT p.posting_id, p.asset_id, p.qty_base, p.location FROM postings p JOIN assets a"
                " ON a.asset_id = p.asset_id WHERE a.chain=? AND p.location LIKE 'wallet:%'", (chain,)).fetchall():
            parts = (r["location"] or "").split(":")
            if len(parts) > 3:
                continue
            w = parts[2] if len(parts) >= 3 and parts[2] else None
            if wset is not None and w not in wset:
                continue
            n += 1
            mx = max(mx, int(r["posting_id"]))
            key = (w, r["asset_id"])
            sums[key] = sums.get(key, 0) + int(r["qty_base"])
        return (n, mx, sums)

    def _recon_bal(self, chain: str, kind: str, mode: str, wallets: list):
        jobs = self.__dict__.setdefault("_recon_jobs", {})
        key = (chain, mode)
        wl = sorted(wallets)
        job = jobs.get(key)
        if job is None:
            if sum(1 for j in jobs.values() if not j["ev"].is_set()) >= self.RECON_MAX_JOBS:
                return None
            stub = self.__dict__.get("_recon_fetch")
            fn = (lambda: stub(chain, kind, list(wl))) if stub is not None \
                else self._recon_fetch_plan(chain, kind, wl, mode)
            job = {"wallets": wl, "t0": time.time(), "t1": None, "bal": None, "err": None,
                   "fp": self._recon_fp(chain, None if mode == "chain" else wl), "ev": threading.Event()}

            def _run(job=job, fn=fn):
                try:
                    job["bal"] = fn()
                except BaseException as e:
                    job["err"] = e
                finally:
                    job["t1"] = time.time()
                    job["ev"].set()
            jobs[key] = job
            if stub is not None:
                _run()
            else:
                try:
                    threading.Thread(target=_run, name=f"tj-recon-{chain}-{mode}", daemon=True).start()
                except Exception:
                    jobs.pop(key, None)
                    raise
                dl = self.__dict__.get("_recon_deadline")
                job["ev"].wait(self.RECON_WAIT_SEC if dl is None else max(0.0, dl - time.time()))
        if not job["ev"].is_set():
            return None
        label = f"recon {chain}" + {"new": " 새 지갑", "tok": " 새 지갑(토큰만)", "nat": " 새 지갑(네이티브)",
                                    "natx": " 새 지갑(네이티브 — 색인 정체 임시)"}.get(mode, "")
        if job["err"] is not None:
            jobs.pop(key, None)
            e = job["err"]
            raise e if isinstance(e, Exception) else RuntimeError(repr(e))
        if time.time() - job["t1"] > self.RECON_DEFER_MAX_SEC:
            jobs.pop(key, None)
            log.info("%s 보류 — 조회 결과가 %d초 넘게 반영 못 됨(폐기·재조회)", label, self.RECON_DEFER_MAX_SEC)
            return None
        if self._recon_pending(chain):
            return None
        jobs.pop(key, None)
        if job["wallets"] != wl:
            log.info("%s 보류 — 조회 중 지갑 목록 변경", label)
            return None
        if not (self._scope_ready_tok(chain) if mode == "tok" else
                self._scope_ready_natx(chain) if mode == "natx" else self._scope_ready(chain)):
            log.info("%s 보류 — 조회 중 수집기 준비 상태 해제(동기 도장·상세 큐)", label)
            return None
        if self._recon_fp(chain, None if mode == "chain" else wl) != job["fp"]:
            log.info("%s 보류 — 조회 중 신규 레코드 유입(이 체인 원장 변경)", label)
            return None
        if job["t1"] - job["t0"] > 30:
            log.info("%s 잔고조회 %.0f초 — 백그라운드 완료(소비 루프 비차단) · 반영", label, job["t1"] - job["t0"])
        b9 = job["bal"] if isinstance(job["bal"], dict) else {}
        if b9.get("_source") == "rpc":
            nd = len(b9.get("_bs_diff") or [])
            nu = sum(len(v) for v in (b9.get("_unobs") or {}).values())
            log.info("%s 잔고 = RPC 블록 %s (블록스카웃과 다른 칸 %d · 관측 불가로 뺀 칸 %d)", label, b9.get("_block"), nd, nu)
            for w9, ca9, bv9, rv9 in (b9.get("_bs_diff") or [])[:20]:
                log.info("  %s %s 블록스카웃 %s → RPC %s", str(w9)[:10], str(ca9)[:10], bv9, rv9)
        return job["bal"]

    def _wallet_backfilled(self, chain: str, kind: str, w: str) -> bool:
        sd = common.STATE_DIR
        if kind == "bsc":
            cur = common.read_json(os.path.join(sd, "cursor_bsc.json"), {})
            return w in {str(x).lower() for x in (cur.get("_wallets") or [])} and not cur.get("_neww")
        if kind == "sol":
            return w in common.read_json(os.path.join(sd, "cursor_sol.json"), {})
        return w in common.read_json(os.path.join(sd, f"cursor_evm_{chain}.json"), {})

    def _recon_new_wallets(self, chain: str, kind: str, stream: str, drained: set, cutoff_ts: int, start: bool = True):
        T, ws = self._recon_view(chain)
        pool = sorted(self.sol_wallets) if kind == "sol" else sorted(self.my_wallets.get(chain, set()))

        def cands():
            return [w for w in pool if w.lower() not in ws and not self._meta_get(f"wrecon_done:{chain}:{w}")]
        if not cands():
            return 0
        jobs = self.__dict__.get("_recon_jobs", {})
        full_ok = self._scope_ready(chain)
        done = 0
        for mode in ("new", "nat"):
            if not full_ok and (chain, mode) not in jobs:
                continue
            sel = [w for w in cands() if bool(self._meta_get(f"wrecon_tok:{chain}:{w}")) == (mode == "nat")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, mode, sel)
        if kind == "evm" and ((not full_ok and self._scope_ready_tok(chain)) or (chain, "tok") in jobs):
            sel = [w for w in cands() if not self._meta_get(f"wrecon_tok:{chain}:{w}")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, "tok", sel)
        if kind == "evm" and ((not full_ok and self._scope_ready_natx(chain)) or (chain, "natx") in jobs):
            sel = [w for w in cands() if self._meta_get(f"wrecon_tok:{chain}:{w}")]
            if sel:
                done += self._wrecon_run(chain, kind, stream, drained, cutoff_ts, start, "natx", sel)
        return done

    def _wrecon_run(self, chain: str, kind: str, stream: str, drained: set, cutoff_ts: int, start: bool, mode: str, wallets: list):
        new = [w for w in wallets if self._wallet_backfilled(chain, kind, w)]
        if not new:
            return 0
        if (chain, mode) not in self.__dict__.get("_recon_jobs", {}) \
                and (not start or not self._recon_quiet(chain, stream, drained)):
            return 0
        bal = self._recon_bal(chain, kind, mode, new)
        if bal is None:
            return 0
        per = bal.get("per_wallet") or {}
        onchain = self._recon_onchain(chain, bal)
        posted, unk9, t_obs = self._recon_at(chain, bal)
        nat_aids = {r[0] for r in self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='native'", (chain,)).fetchall()}

        natm = mode in ("nat", "natx")

        def in_scope(aid):
            return mode == "new" or ((aid in nat_aids) == natm)
        scope9 = {"tok": "token", "nat": "native", "natx": "native"}.get(mode)
        now9 = t_obs
        done = 0
        nlegs = 0
        try:
            hold9 = bal.get("_hold") or {}
            unobs_aids = self._recon_unobs_aids(chain, bal)
            q_aids = self._recon_q_aids(chain, bal)
            for w in new:
                if w in unk9 or str(w).lower() in unk9:
                    log.warning("recon %s 새 지갑 %s 보류 — 블록 모르는 체인 거래 기장", chain, w[:10])
                    continue
                if w in hold9:
                    log.warning("recon %s 새 지갑 %s 보류 — 관측 불가 토큰 %s", chain, w[:10], ",".join(str(x)[:10] for x in hold9[w][:5]))
                    continue
                if w not in per:
                    log.warning("recon %s 새 지갑 %s 잔고 응답 없음 — 다음 주기", chain, w[:10])
                    continue
                legs = []
                for key in {k for k in onchain if k[0] == w} | {k for k in posted if k[0] == w}:
                    if not in_scope(key[1]) or key[1] in unobs_aids.get(w, ()):
                        continue
                    if q_aids is not None and key[1] not in nat_aids and key[1] not in q_aids.get(w, ()):
                        continue
                    diff = onchain.get(key, 0) - posted.get(key, 0)
                    if diff:
                        legs.append((key[1], diff))
                loc = f"wallet:{chain}:{w}"
                if mode == "new":
                    f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=?", (loc,)).fetchone()[0]
                else:
                    f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'",
                                           (loc,)).fetchone()[0]
                pos_ts = min(int(cutoff_ts), int(f9) - 1) if f9 is not None else int(cutoff_ts)
                sid = f"recon:{chain}:{w}" + (":native" if natm else "")
                obs9 = self._obs_wallet_pay(per[w], (bal.get("_zero") or {}).get(w),
                                            keep=lambda k, natm=natm: mode == "new" or ((k[0] == "native") == natm))
                pay9 = {w: obs9}
                if scope9:
                    pay9["_scope"] = scope9
                if mode == "natx":
                    pay9["_basis"] = "internal_index_stalled"
                pay9.update(self._recon_src(bal, [w]))
                self.conn.execute(
                    "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
                    (sid, "opening_balance", chain, json.dumps(pay9, ensure_ascii=False), now9))
                for seq, (aid, diff) in enumerate(sorted(legs)):
                    self.conn.execute(
                        "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                        " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                        " VALUES ('opening', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening', 'OPENING', ?)",
                        (chain, sid, seq, pos_ts if diff > 0 else now9, aid, loc, str(diff), CLASSIFIER_VER))
                    self._bump_position(aid, diff, loc)
                mk9 = f"wrecon_tok:{chain}:{w}" if mode == "tok" else f"wrecon_done:{chain}:{w}"
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (mk9, str(now9)))
                if mode == "natx":
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"wrecon_natx:{chain}:{w}", str(now9)))
                done += 1
                nlegs += len(legs)
                log.info("★recon %s 새 지갑 %s 기초잔고%s %d개 자산 보정★", chain, w[:10],
                         {"tok": "(토큰만 — 네이티브는 내부 이동 색인 뒤)", "nat": "(네이티브)",
                          "natx": "(네이티브 — 탐색기 내부 이동 색인 장기 정체: RPC 블록 잔고로 임시 대사, 색인 완료 뒤 자동 보정)"}.get(mode, ""),
                         len(legs))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if done:
            self.__dict__.get("_recon_cache", {}).pop(chain, None)
        if nlegs:
            try:
                os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
            except FileNotFoundError:
                pass
            dm("RECON", f"[{chain}] 새 지갑 기초잔고 대사 완료" + {"tok": "(토큰만 — 네이티브는 내부 이동 색인 완료 뒤)",
                                                              "nat": "(네이티브)",
                                                              "natx": "(네이티브 — 탐색기 내부 이동 색인 장기 정체라 RPC 잔고로 임시 맞춤, "
                                                                      "색인 완료 뒤 늦게 오는 내부 이동은 자동 보정)"}.get(mode, "")
               + f" — {done}개 지갑 · 보정 {nlegs}건")
        return done

    GATE_RELOAD_SEC = 600

    def _gate_reload(self):
        now9 = time.time()
        if now9 - getattr(self, "_gate_at", 0) < self.GATE_RELOAD_SEC:
            return 0
        self._gate_at = now9
        if not os.path.exists(common.ACTIVITY_GATE_PATH):
            return 0
        cfg2 = common.load_config()
        added = []
        for w in cfg2.get("wallets") or []:
            if w.get("type", "evm") != "evm":
                continue
            c, a = w["chain"], str(w["address"]).lower()
            if a in self.my_wallets.get(c, set()):
                continue
            if c not in self.cfg["chains"]:
                self.cfg["chains"][c] = (cfg2.get("chains") or {}).get(c)
                if not self.cfg["chains"][c]:
                    self.cfg["chains"].pop(c, None)
                    continue
            ns9 = (cfg2.get("native_symbol") or {}).get(c)
            if ns9:
                self.native_sym.setdefault(c, ns9)
            wr9 = (cfg2.get("wrapped_native") or {}).get(c)
            if wr9:
                self.wrapped.setdefault(c.lower(), str(wr9).lower())
            self.my_wallets.setdefault(c, set()).add(a)
            self.cfg["wallets"].append(dict(w))
            self.conn.execute("INSERT OR IGNORE INTO wallets (chain, address, label, added_at) VALUES (?,?,?,?)",
                              (c, a, w.get("label"), int(now9)))
            added.append(f"{c}:{a[:10]}")
        if added:
            self.conn.commit()
            log.warning("★활동 게이트 합류 %d쌍: %s★", len(added), ", ".join(added[:12]))
        return len(added)

    def recon_pass(self, drained: set):
        jobs = self.__dict__.setdefault("_recon_jobs", {})
        start = time.time() - self._last_recon >= 300
        if self.recon_months <= 0 or (not start and not jobs):
            return
        if start:
            self._last_recon = time.time()
            try:
                self._rpc_recon_reset()
            except Exception as e:
                self.conn.rollback()
                log.warning("RPC 재대사 점검 실패(다음 주기): %s", e)
        self._recon_deadline = time.time() + self.RECON_WAIT_SEC
        self._recon_pend_pass = (False, None)
        try:
            self._recon_pass_scopes(drained, start, jobs)
        finally:
            self._recon_deadline = None
            self.__dict__.pop("_recon_pend_pass", None)

    def _recon_pass_scopes(self, drained: set, start: bool, jobs: dict):
        scopes = []
        for chain in self.cfg.get("chains", {}):
            if self.my_wallets.get(chain):
                scopes.append((chain, "evm"))
        if self.sol_wallets:
            scopes.append(("sol", "sol"))
        if any(w.get("type") == "bsc_rpc" for w in self.cfg["wallets"]):
            scopes.append(("bsc", "bsc"))
        if start and scopes:
            off9 = self.__dict__.get("_recon_scope_cursor", 0) % len(scopes)
            scopes = scopes[off9:] + scopes[:off9]
            self._recon_scope_cursor = (off9 + 1) % len(scopes)
        live = set()
        for c, _k in scopes:
            if self._meta_get(f"recon_done_{c}"):
                live |= {(c, "new"), (c, "tok"), (c, "nat"), (c, "natx")}
            else:
                live.add((c, "chain"))
        now9 = time.time()
        for k9 in [k for k, j in jobs.items() if j["ev"].is_set()
                   and (k not in live or now9 - (j["t1"] or now9) > self.RECON_DEFER_MAX_SEC)]:
            jobs.pop(k9, None)
        for chain, kind in scopes:
            cutoff_ts = self._win_t0(None, chain)
            stream = {"evm": "evm", "sol": "sol", "bsc": "bsc"}[kind]
            if self._meta_get(f"recon_done_{chain}"):
                if not start and not any((chain, m9) in jobs for m9 in ("new", "tok", "nat", "natx")):
                    continue
                try:
                    self._recon_new_wallets(chain, kind, stream, drained, cutoff_ts, start=start)
                except Exception as e:
                    self.conn.rollback()
                    log.warning("recon %s 새 지갑 대사 실패(다음 주기): %s", chain, e)
                continue
            if (chain, "chain") not in jobs:
                if not start or not self._scope_ready(chain) or not self._recon_quiet(chain, stream, drained):
                    continue
            try:
                bal = self._recon_bal(chain, kind, "chain", sorted(self.my_wallets.get(chain, set())) if kind != "sol"
                                      else sorted(self.sol_wallets))
            except Exception as e:
                log.warning("recon %s 잔고조회 실패(다음 주기 재시도): %s", chain, e)
                continue
            if bal is None:
                continue
            if bal.get("_hold"):
                log.warning("recon %s 보류 — 관측 불가 토큰 있는 지갑 %s", chain, ",".join(str(w)[:10] for w in bal["_hold"]))
                continue
            per = bal.get("per_wallet") or {}
            meta_hint = bal.get("_meta") or {}
            posted, unk9, t_obs = self._recon_at(chain, bal)
            if unk9:
                log.error("recon %s 보류 — 블록 모르는 체인 거래 기장(지갑 %s)", chain, ",".join(str(w)[:10] for w in unk9))
                continue
            if any(w is None for (w, _a) in posted):
                log.error("recon %s 보류 — 지갑 미상 레거시 posting 존재(재파생 필요)", chain)
                continue
            legs = []
            onchain = {}
            for w, wb in per.items():
                for (k2, addr), amount in wb.items():
                    if k2 == "native":
                        aid = self.asset_id("native", chain, None,
                                            symbol=self.native_sym.get(chain, chain.upper()),
                                            decimals=9 if chain == "sol" else 18)
                    else:
                        hint = meta_hint.get(addr, (None, None))
                        aid = self.asset_id("token", chain, addr, symbol=hint[0], decimals=hint[1])
                    onchain[(w, aid)] = amount
            unobs_aids = self._recon_unobs_aids(chain, bal)
            q_aids = self._recon_q_aids(chain, bal)
            nat9 = {r[0] for r in self.conn.execute("SELECT asset_id FROM assets WHERE chain=? AND kind='native'", (chain,)).fetchall()}
            for key in set(onchain) | set(posted):
                if key[1] in unobs_aids.get(key[0], ()):
                    continue
                if q_aids is not None and key[1] not in nat9 and key[1] not in q_aids.get(key[0], ()):
                    continue
                diff = onchain.get(key, 0) - posted.get(key, 0)
                if diff == 0:
                    continue
                legs.append((key[0], key[1], diff))
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at)"
                    " VALUES (?,?,?,?,?)",
                    (f"recon:{chain}", "opening_balance", chain,
                     json.dumps(dict({w: self._obs_wallet_pay(wb, (bal.get("_zero") or {}).get(w))
                                      for w, wb in per.items()}, **self._recon_src(bal, list(per))), ensure_ascii=False),
                     t_obs))
                for seq, (w, aid, diff) in enumerate(sorted(legs, key=lambda x: (x[1], x[0] or ""))):
                    ev_ts = cutoff_ts if diff > 0 else t_obs
                    loc = f"wallet:{chain}:{w}" if w else f"wallet:{chain}"
                    self.conn.execute(
                        "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
                        " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                        " VALUES ('opening', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening', 'OPENING', ?)",
                        (chain, f"recon:{chain}", seq, ev_ts, aid, loc,
                         str(diff), CLASSIFIER_VER))
                    self._bump_position(aid, diff, loc)
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"recon_done_{chain}", str(t_obs)))
                self.conn.commit()
                log.info("★recon %s 완료: 기초잔고 %d개 자산 보정★", chain, len(legs))
                dm("RECON", f"[{chain}] 기초잔고 대사 완료 — {len(legs)}개 자산 보정")
            except Exception:
                self.conn.rollback()
                raise
        marker = os.path.join(common.STATE_DIR, "backfill_done")
        if not os.path.exists(marker):
            all_done = all(self._meta_get(f"recon_done_{c}") for c, _ in scopes)
            all_done = all_done and bool(self._meta_get("recon_done_upbit"))
            if scopes and all_done:
                with open(marker, "w") as f:
                    f.write(str(int(time.time())))
                log.info("★백필 완료 마커 생성 — 일별 스냅샷 동결 시작★")
                dm("BACKFILL_DONE", "전 체인 백필+기초잔고 대사 완료 — 일별 스냅샷 동결 시작")

    def _streams_have_data(self) -> bool:
        for stream, reader in (("evm", self.reader), ("sol", self.sol_reader),
                               ("bsc", self.bsc_reader)):
            row = self.conn.execute(
                "SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            seg, off = (row["seg"], row["off"]) if row else (1, 0)
            batch, _, _ = reader.read_batch(seg, off, max_records=1)
            if batch:
                return True
        return False

    def _group_of(self, aid: int) -> int:
        r = self.conn.execute("SELECT group_id, symbol, kind, chain, address FROM assets WHERE asset_id=?",
                              (aid,)).fetchone()
        if r["group_id"]:
            return r["group_id"]
        sym = (r["symbol"] or "").upper()
        kind, chain, ca = r["kind"], r["chain"], r["address"]
        if kind == "native":
            name = sym or f"native:{chain}"
        elif kind == "token" and ca:
            st = pricing.STABLE_CAS.get(chain, {}).get(ca)
            if chain == "sol" and not st:
                st = pricing.STABLE_MINTS.get(ca)
            if st:
                name = st
            elif ca == self.wrapped.get(chain):
                name = self.native_sym.get(chain, "ETH")
            else:
                name = (sym or "TOKEN") + f"#{aid}"
        else:
            name = (sym or f"{kind}:{chain}") + f"#{aid}"
        self.conn.execute("INSERT OR IGNORE INTO asset_groups (name) VALUES (?)", (name,))
        gid = self.conn.execute(
            "SELECT group_id FROM asset_groups WHERE name=?", (name,)).fetchone()["group_id"]
        self.conn.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (gid, aid))
        return gid

    def _norm(self, aid: int, v: int) -> str:
        r = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()
        dec = r["decimals"] if r and r["decimals"] is not None else 18
        with localcontext() as ctx:
            ctx.prec = 100
            return format(Decimal(v) / (Decimal(10) ** dec), "f")

    EX_TERMINAL_STATES = ("ACCEPTED", "DONE", "CANCELLED", "CANCELED", "REJECTED", "FAILED", "REFUNDED")
    EX_RECON_TOL = Decimal("0.000001")

    def _late_wd_note(self, acc: dict, d: dict, sgn: int, ts_s) -> None:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            return
        ccy9 = str(d.get("currency") or "").upper()
        ts9 = self._iso_ts(ts_s)
        if amt9 > 0 and ccy9 and ccy9 != "KRW" and ts9:
            acc.setdefault(ccy9, []).append((int(ts9), sgn * amt9))

    def _consume_ex(self, rec: dict):
        ex = rec.get("exchange", "upbit")
        now = int(time.time())
        self._wd_fee_new_ex(ex)
        n_new = n_matched = 0
        late_wd = {}
        for kind, rows in (("deposit", rec.get("deposits") or []),
                           ("withdraw", rec.get("withdraws") or [])):
            for d in rows:
                if not isinstance(d, dict) or not d.get("uuid"):
                    continue
                uid = str(d["uuid"])
                state = str(d.get("state") or "")
                last = self.conn.execute(
                    "SELECT revision, payload FROM raw_ex WHERE exchange=? AND kind=? AND uuid=?"
                    " ORDER BY revision DESC LIMIT 1", (ex, kind, uid)).fetchone()
                if last:
                    try:
                        last_payload = json.loads(last["payload"])
                        last_state = str(last_payload.get("state") or "")
                    except (json.JSONDecodeError, TypeError):
                        last_payload, last_state = {}, ""
                    time_fix9 = (last_state == state and not self._iso_ts(last_payload.get("created_at") or last_payload.get("done_at"))
                                 and bool(self._iso_ts(d.get("created_at") or d.get("done_at"))))
                    if time_fix9:
                        d = dict(last_payload, **{k9: v9 for k9, v9 in d.items() if v9 not in (None, "")})
                        if ex != "upbit":
                            d["late"] = 1
                    if kind == "withdraw" and last_state == state and d.get("address") and not time_fix9:
                        dest9 = {k9: str(d[k9]) for k9 in ("address", "tag", "network") if d.get(k9) not in (None, "")}
                        if any(str(last_payload.get(k9) or "") != v9 for k9, v9 in dest9.items()):
                            merged9 = dict(last_payload, **dest9)
                            if not last_payload.get("txid") and d.get("txid"):
                                merged9["txid"] = d["txid"]
                            self.conn.execute(
                                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at)"
                                " VALUES (?,?,?,?,?,?)",
                                (ex, kind, uid, last["revision"] + 1, json.dumps(merged9, ensure_ascii=False), now))
                            n_new += 1
                            continue
                    if last_state == state and (last_payload.get("txid") or not d.get("txid")) and not time_fix9:
                        continue
                    if last_state.upper() in self.EX_TERMINAL_STATES and state.upper() != last_state.upper():
                        log.info("[ex] %s %s %s 종결(%s) 뒤 옛 상태(%s) 스냅샷 무시", ex, kind, uid[:12], last_state, state)
                        continue
                    rev = last["revision"] + 1
                else:
                    rev = 1
                self.conn.execute(
                    "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (ex, kind, uid, rev, json.dumps(d, ensure_ascii=False), now))
                n_new += 1
                if kind == "deposit" and state.upper() == "ACCEPTED":
                    txid = str(d.get("txid") or "")
                    if txid:
                        n_matched += self._link_transfers(uid, txid, d.get("currency"), now)
                    if ex == "upbit":
                        dep_ts = self._iso_ts(d.get("done_at") or d.get("created_at"))
                        if dep_ts:
                            self._post_ex_deposit(uid, d, dep_ts)
                        else:
                            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 시각 없음 보류: {d.get('currency')} {uid}")
                if kind == "withdraw" and ex != "upbit" and state.upper() == "DONE":
                    if self._post_exf_withdraw(ex, uid, d) and d.get("late"):
                        self._late_wd_note(late_wd, d, -1, d.get("created_at") or d.get("done_at"))
                        if self._wd_fee_leg_on(ex, self._iso_ts(d.get("created_at") or d.get("done_at"))):
                            self._late_wd_note(late_wd, {"amount": d.get("fee"), "currency": d.get("fee_ccy") or d.get("currency")}, -1,
                                               d.get("created_at") or d.get("done_at"))
                if kind == "withdraw" and ex == "upbit" and state.upper() == "DONE":
                    self._post_ex_withdraw(uid, d)
                if kind == "deposit" and ex != "upbit" and state.upper() == "ACCEPTED":
                    if self._post_exf_deposit_in(ex, uid, d) and d.get("late"):
                        self._late_wd_note(late_wd, d, 1, d.get("done_at") or d.get("created_at"))
        if ex != "upbit":
            self._late_stage(ex, late_wd, rec)
        if n_new or n_matched:
            log.info("[ex] %s 스냅샷: revision %d건, 입금 대사 %d건", ex, n_new, n_matched)
            if n_matched:
                dm("DEPOSIT_MATCHED", f"업비트 입금 확인 대사 {n_matched}건 완료")

    def _link_transfers(self, uid: str, txid: str, currency, now: int) -> int:
        cand = txid.lower() if txid.startswith("0x") else txid
        n_syms = self.conn.execute(
            "SELECT count(DISTINCT coalesce(upper(a.symbol), '')) FROM transfers t JOIN assets a ON a.asset_id=t.asset_id"
            " WHERE t.chain_txhash IN (?, ?)", (cand, txid)).fetchone()[0]
        if n_syms <= 1:
            cur = self.conn.execute(
                "UPDATE transfers SET state='credited', ex_uuid=?, updated_at=?"
                " WHERE state='sent' AND chain_txhash IN (?, ?)", (uid, now, cand, txid))
        else:
            cur = self.conn.execute(
                "UPDATE transfers SET state='credited', ex_uuid=?, updated_at=?"
                " WHERE state='sent' AND chain_txhash IN (?, ?)"
                " AND upper((SELECT symbol FROM assets a WHERE a.asset_id=transfers.asset_id)) = ?",
                (uid, now, cand, txid, str(currency or "").upper()))
        return int(cur.rowcount or 0)

    def _upbit_asset(self, sym: str) -> int:
        symu = (sym or "").upper()
        return self.asset_id("exchange_currency", None, f"upbit:{symu}", symbol=symu, decimals=8)

    @staticmethod
    def _upbit_q8(amount):
        try:
            a = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not a.is_finite() or a <= 0:
            return None
        q = a * (Decimal(10) ** 8)
        if q != q.to_integral_value():
            return None
        return int(q)

    def _ex_skip_once(self, kind: str, uid: str, text: str):
        sent = getattr(self, "_ex_skip_sent", None)
        if sent is None:
            sent = self._ex_skip_sent = set()
        if uid in sent:
            return
        sent.add(uid)
        log.warning("%s uuid=%s — %s", kind, uid[:12], text)
        dm(kind, text)

    def _upbit_window_t0(self) -> int:
        if self.recon_months <= 0:
            return 0
        return self._win_t0(None, "upbit")

    def _post_ex_deposit(self, uid: str, payload: dict, dep_ts: int,
                         force_comp: bool = False) -> bool:
        if not self._iso_ts((payload or {}).get("done_at") or (payload or {}).get("created_at")):
            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 시각 없음 보류: {(payload or {}).get('currency')} {uid}")
            return False
        if str(payload.get("state") or "").upper() != "ACCEPTED":
            return False
        sym = str(payload.get("currency") or "").upper()
        if not sym or sym == "KRW":
            return False
        if dep_ts < self._upbit_window_t0():
            return False
        try:
            if Decimal(str(payload.get("amount"))) <= 0:
                return False
        except (InvalidOperation, ValueError, TypeError):
            pass
        q8 = self._upbit_q8(payload.get("amount"))
        if q8 is None:
            self._ex_skip_once("EX_DEPOSIT_SKIP", uid, f"업비트 입금 수량 보류: {sym} {uid} amount={payload.get('amount')!r}")
            return False
        aid = self._upbit_asset(sym)
        c2 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
            " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
            " classifier_ver) VALUES ('exchange', 'upbit:deposit', ?, 0, ?, ?,"
            " 'exchange:upbit', ?, NULL, NULL, 'move_in', 'EX_DEPOSIT', ?)",
            (uid, dep_ts, aid, str(q8), CLASSIFIER_VER))
        if c2.rowcount:
            self._bump_position(aid, q8, "exchange:upbit")
            return True
        return False

    def _post_ex_withdraw(self, uid: str, d: dict) -> bool:
        if str(d.get("state") or "").upper() != "DONE":
            return False
        sym = str(d.get("currency") or "").upper()
        if not sym or sym == "KRW":
            return False
        wts0 = self._iso_ts(d.get("created_at") or d.get("done_at"))
        if not wts0:
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 시각 없음 보류: {sym} {uid}")
            return False
        if wts0 < self._upbit_window_t0():
            return False
        q8 = self._upbit_q8(d.get("amount"))
        if q8 is None:
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 수량 보류: {sym} {uid} amount={d.get('amount')!r}")
            return False
        try:
            fee = Decimal(str(d.get("fee") if d.get("fee") not in (None, "") else "0"))
            fq = fee * (Decimal(10) ** 8)
            if not fee.is_finite() or fee < 0 or fq != fq.to_integral_value():
                raise InvalidOperation
            f8 = int(fq)
        except (InvalidOperation, ValueError, TypeError):
            self._ex_skip_once("EX_WITHDRAW_SKIP", uid, f"업비트 출금 수수료 보류: {sym} {uid} fee={d.get('fee')!r}")
            return False
        wts = wts0
        aid = self._upbit_asset(sym)
        c9 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts,"
            " asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
            " VALUES ('exchange', 'upbit:withdraw', ?, 0, ?, ?, 'exchange:upbit', ?, NULL, NULL,"
            " 'move_out', 'EX_WITHDRAW', ?)",
            (uid, wts, aid, str(-(q8 + f8)), CLASSIFIER_VER))
        if c9.rowcount:
            self._bump_position(aid, -(q8 + f8), "exchange:upbit")
            return True
        return False

    EXF_STABLE_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "DAI", "USD")

    def _exf_asset(self, ex: str, sym: str) -> int:
        return self.asset_id("exchange_currency", None, f"{ex}:{sym.upper()}",
                             symbol=sym.upper(), decimals=8)

    def _quote_usd(self, quote: str, ts: int):
        q = (quote or "").upper()
        if q in self.EXF_STABLE_QUOTES:
            return Decimal(1)
        if q == "KRW":
            fx = self.px.fx_at(ts * 1000)
            return (Decimal(1) / Decimal(str(fx))) if fx else None
        v = self.px.candle_usd(q, ts * 1000)
        return Decimal(str(v)) if v else None

    def _consume_exf_fills(self, rec: dict):
        ex = str(rec.get("exchange") or "")
        if not ex or ex == "upbit":
            return
        self._wd_fee_new_ex(ex)
        now = int(time.time())
        n = 0
        late9 = []
        for f in rec.get("fills") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            fid = str(f["id"])
            cur9 = self.conn.execute(
                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload,"
                " observed_at) VALUES (?, 'trade', ?, 1, ?, ?)",
                (ex, fid, json.dumps(f, ensure_ascii=False), now))
            if not cur9.rowcount:
                continue
            if self._post_exf_fill(ex, f):
                n += 1
                if f.get("src") == "convert" or f.get("late"):
                    late9.append(f)
        self._late_stage(ex, self._late_fill_deltas(late9), rec)
        if n:
            log.info("%s 체결 반영: %d건", ex, n)

    EXF_TOL = Decimal("0.00000001")
    EXF_MICRO_USD = Decimal("1")
    EXF_MICRO_REL = Decimal("0.0001")
    EXF_INIT_PHASE = 72 * 3600
    EXF_NEW_SOURCES_M = {"okx": ("savings", "staking"), "bybit": ("earn",)}
    EXF_DEBT_MICRO_USD = Decimal("5")
    EXF_DEBT_ONLY_SOURCES = {"gate": ("cross",), "kucoin": ("margin",)}
    EXF_DEBT_FIRST_SEEN = os.path.join(common.BASE_DIR, "seed", "debt_first_seen_t.json")

    @staticmethod
    def _exf_bts(source_id):
        try:
            return int(str(source_id).rsplit(":", 1)[1])
        except (IndexError, ValueError, TypeError):
            return None

    def _exf_open_ts(self, ex: str, bts: int) -> int:
        if self.recon_months > 0:
            return self._win_t0(bts, ex)
        return bts - int(float(self.cfg.get("backfill_months") or 5) * 30 * 86400)

    def _exf_cov_new(self, ex: str, bal: dict) -> bool:
        cur = bal.get("sources")
        if not isinstance(cur, list):
            return False
        cur = {str(x) for x in cur}
        prev = self._meta_get(f"recon_src_exf_{ex}")
        if prev is None:
            return bool(cur & set(self.EXF_NEW_SOURCES_M.get(ex, ())))
        try:
            prev = set(json.loads(prev))
        except (ValueError, TypeError):
            return False
        new = cur - prev
        new -= set(self.EXF_DEBT_ONLY_SOURCES.get(ex, ()))
        loans9 = bal.get("loans") if isinstance(bal.get("loans"), list) else []
        if "loan" in new and not any(isinstance(l9, dict) and l9.get("collateral") for l9 in loans9):
            new.discard("loan")
        return bool(new)

    def _exf_adj_rows(self, ex: str, sym: str) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.asset_id, p.qty_base, p.event_ts, p.source_id, p.leg_seq, a.decimals"
            " FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?",
            (f"{ex}:recon", f"exchange:{ex}", sym.upper())).fetchall()]

    def _exf_series(self, ex: str, sym: str) -> list:
        agg = {}
        for r in self.conn.execute(
                "SELECT p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            agg[int(r["event_ts"])] = agg.get(int(r["event_ts"]), Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        return sorted(agg.items())

    @staticmethod
    def _exf_room(series: list, t: int, t_end=None) -> Decimal:
        cum, floor, mn = Decimal(0), Decimal(0), None
        for ts9, q9 in series:
            if ts9 < t:
                cum += q9
                floor = min(Decimal(0), cum)
                continue
            cum += q9
            if (t_end is None or ts9 < t_end) and cum >= floor - Decimal("0.00000001"):
                mn = (cum - floor) if mn is None else min(mn, cum - floor)
        if mn is None:
            return Decimal(0)
        return max(Decimal(0), mn)

    def _exf_deficit(self, ex: str, sym: str):
        cum, t_run, mn = Decimal(0), None, Decimal(0)
        for ts9, q9 in self._exf_series(ex, sym):
            cum += q9
            if cum < -self.EXF_TOL:
                if t_run is None:
                    t_run, mn = ts9, cum
                mn = min(mn, cum)
            else:
                t_run, mn = None, Decimal(0)
        return (t_run, -mn) if t_run is not None else (None, Decimal(0))

    EXF_FIX_V = 2
    EXF_RUN_MIN_S = 3600
    EXF_FIX_SKIP = frozenset(("KRW", "USD"))

    def _exf_agg(self, ex: str, sym: str, exclude=()):
        agg = {}
        ex9 = set(exclude or ())
        for r in self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            if ex9 and int(r["posting_id"]) in ex9:
                continue
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            t9 = int(r["event_ts"])
            agg[t9] = agg.get(t9, Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        return agg, sorted(agg)

    @classmethod
    def _exf_tranches(cls, agg: dict, keys: list, amount_b: int, scale: Decimal, bts: int, open_ts: int):
        tol = cls.EXF_TOL
        out, rem, lift = [], int(amount_b), Decimal(0)
        cum, i, n = Decimal(0), 0, len(keys)
        while i < n and keys[i] <= open_ts:
            cum += agg[keys[i]]
            i += 1
        start, mn = (open_ts, cum) if cum < -tol else (None, Decimal(0))

        def emit(st9, dfc9):
            nonlocal rem, lift
            take9 = min(rem, int((dfc9 * scale).to_integral_value(rounding=ROUND_CEILING)))
            if take9 > 0:
                out.append((int(open_ts) if st9 <= open_ts else int(st9) - 1, take9))
                rem -= take9
                lift += Decimal(take9) / scale
        while rem > 0 and i < n and keys[i] <= bts:
            t9 = keys[i]
            i += 1
            cum += agg[t9]
            v9 = cum + lift
            if v9 < -tol:
                if start is None:
                    start, mn = t9, v9
                elif v9 < mn:
                    mn = v9
            elif start is not None:
                if t9 - start >= cls.EXF_RUN_MIN_S:
                    emit(start, -mn)
                start, mn = None, Decimal(0)
        if rem > 0 and start is not None:
            emit(start, -mn)
        for t9, qb9 in out:
            if t9 not in agg:
                bisect.insort(keys, t9)
                agg[t9] = Decimal(0)
            agg[t9] += Decimal(qb9) / scale
        return out, rem

    @staticmethod
    def _exf_bound_old(pieces: list, old: list) -> list:
        olds = [[int(t9), int(q9)] for t9, q9 in sorted(old)]
        out, j = [], 0
        for t9, q9 in sorted(pieces):
            q9 = int(q9)
            while q9 > 0:
                take9 = min(q9, olds[j][1])
                out.append((min(int(t9), olds[j][0]), take9))
                q9 -= take9
                olds[j][1] -= take9
                if olds[j][1] == 0:
                    j += 1
        return out

    @staticmethod
    def _exf_tranche_legs(tranches, rem_b: int, bts: int, reserved=frozenset()) -> list:
        pcs = {}
        for t9, qb9 in list(tranches) + ([(bts, rem_b)] if rem_b > 0 else []):
            pcs[int(t9)] = pcs.get(int(t9), 0) + int(qb9)
        used = set(reserved) | {2}
        legs, nxt = [], 1
        for t9 in sorted(pcs):
            if t9 == int(bts) and 0 not in used:
                l9 = 0
            else:
                while nxt in used:
                    nxt += 1
                l9 = nxt
            used.add(l9)
            legs.append((l9, t9, pcs[t9]))
        return legs

    def _exf_fix_pool(self):
        pool, other = {}, {}
        span9 = int(float(self.cfg.get("backfill_months") or 5) * 30 * 86400)
        for r in self.conn.execute(
                "SELECT p.posting_id, p.source_ns, p.source_id, p.leg_seq, p.event_ts, p.qty_base, p.asset_id, p.location,"
                " p.classifier_ver, a.symbol, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.event='EXF_ADJUST' AND p.source_ns LIKE '%:recon'").fetchall():
            ns = str(r["source_ns"])
            ex = ns.split(":", 1)[0]
            sym = str(r["symbol"] or "").upper()
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or not sym or sym in self.EXF_FIX_SKIP or r["location"] != f"exchange:{ex}":
                continue
            if (int(r["leg_seq"]) == 2 or int(r["qty_base"]) <= 0
                    or (int(r["leg_seq"]) == 0 and int(r["event_ts"]) <= max(self._exf_open_ts(ex, b9), b9 - span9) + 60)):
                other.setdefault((ex, sym, str(r["source_id"])), set()).add(int(r["leg_seq"]))
                continue
            pool.setdefault((ex, sym), {}).setdefault(str(r["source_id"]), []).append(dict(r, bts=b9))
        return pool, other

    def _exf_fix_place_plan(self) -> list:
        out = []
        pool, other = self._exf_fix_pool()
        for (ex, sym), groups in sorted(pool.items()):
            if self._exf_now_sym(ex, sym):
                continue
            pids = {int(r["posting_id"]) for rows in groups.values() for r in rows}
            agg, keys = self._exf_agg(ex, sym, exclude=pids)
            for sid, rows in sorted(groups.items(), key=lambda kv: (kv[1][0]["bts"], kv[0])):
                b9 = rows[0]["bts"]
                aids = {int(r["asset_id"]) for r in rows}
                decs = {8 if r["decimals"] is None else int(r["decimals"]) for r in rows}
                tot = sum(int(r["qty_base"]) for r in rows)
                if len(aids) != 1 or len(decs) != 1:
                    log.warning("양수 정정 재배치 건너뜀: %s %s %s — 자산 %d개·자릿수 %d개", ex, sym, sid, len(aids), len(decs))
                    for r in rows:
                        t9 = int(r["event_ts"])
                        dec9 = 8 if r["decimals"] is None else int(r["decimals"])
                        agg[t9] = agg.get(t9, Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec9)
                    keys[:] = sorted(agg)
                    continue
                scale = Decimal(10) ** decs.pop()
                tr9, rem9 = self._exf_tranches(agg, keys, tot, scale, b9, self._exf_open_ts(ex, b9))
                bnd9 = self._exf_bound_old(list(tr9) + ([(b9, rem9)] if rem9 > 0 else []),
                                           [(int(r["event_ts"]), int(r["qty_base"])) for r in rows])
                new = sorted(self._exf_tranche_legs(bnd9, 0, b9, reserved=other.get((ex, sym, sid), ())))
                for t9, qb9 in tr9:
                    agg[t9] -= Decimal(qb9) / scale
                for _l9, t9, qb9 in new:
                    if t9 not in agg:
                        bisect.insort(keys, t9)
                        agg[t9] = Decimal(0)
                    agg[t9] += Decimal(qb9) / scale
                old = sorted((int(r["leg_seq"]), int(r["event_ts"]), int(r["qty_base"])) for r in rows)
                if new == old:
                    continue
                out.append({"ex": ex, "sym": sym, "sid": sid, "ns": rows[0]["source_ns"], "bts": b9, "asset_id": aids.pop(),
                            "loc": rows[0]["location"], "cv": min(int(r["classifier_ver"]) for r in rows),
                            "old": [{"pid": int(r["posting_id"]), "leg": int(r["leg_seq"]), "ts": int(r["event_ts"]), "qb": str(r["qty_base"])}
                                    for r in sorted(rows, key=lambda r: int(r["leg_seq"]))],
                            "new": [{"leg": l9, "ts": t9, "qb": str(q9)} for l9, t9, q9 in new]})
        return out

    def _exf_fix_place_apply(self, plan: list) -> int:
        n = 0
        for m in plan:
            if sum(int(o["qb"]) for o in m["old"]) != sum(int(x["qb"]) for x in m["new"]):
                raise ValueError(f"재배치 수량 불일치 {m['sid']}")
            cur = {int(r["leg_seq"]): r for r in self.conn.execute(
                "SELECT posting_id, leg_seq, event_ts, qty_base FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                (m["ns"], m["sid"])).fetchall()}
            for o in m["old"]:
                r9 = cur.get(o["leg"])
                if r9 is None or int(r9["posting_id"]) != o["pid"] or int(r9["event_ts"]) != o["ts"] or str(r9["qty_base"]) != o["qb"]:
                    raise ValueError(f"재배치 대상이 계획 뒤 바뀜 {m['sid']} leg {o['leg']}")
            want = {x["leg"]: x for x in m["new"]}
            for o in m["old"]:
                if o["leg"] not in want:
                    self.conn.execute("DELETE FROM postings WHERE posting_id=?", (o["pid"],))
            for l9, x in sorted(want.items()):
                if l9 in cur and int(cur[l9]["qty_base"]) > 0 and any(o["leg"] == l9 for o in m["old"]):
                    self.conn.execute("UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?",
                                      (int(x["ts"]), x["qb"], int(cur[l9]["posting_id"])))
                elif l9 in cur:
                    raise ValueError(f"재배치 레그 충돌 {m['sid']} leg {l9}")
                else:
                    self.conn.execute(
                        "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL,"
                        " 'opening', 'EXF_ADJUST', ?)",
                        (m["ns"], m["sid"], l9, int(x["ts"]), int(m["asset_id"]), m["loc"], x["qb"], int(m["cv"])))
            n += 1
        return n

    def _exf_fix_place_once(self, expect=None):
        if str(self._meta_get("exf_fix_place_v") or "").split(":", 1)[0] == str(self.EXF_FIX_V):
            return None
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if str(self._meta_get("exf_fix_place_v") or "").split(":", 1)[0] == str(self.EXF_FIX_V):
                self.conn.rollback()
                return None
            plan = self._exf_fix_place_plan()
            if expect is not None and json.loads(json.dumps(plan)) != json.loads(json.dumps(expect)):
                self.conn.rollback()
                log.error("양수 정정 재배치 거부 — 잠금 안 계획(%d묶음)이 검토한 계획(%d묶음)과 다름(원장이 그 사이 바뀜)", len(plan), len(expect))
                return False
            if plan:
                common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_fix_place_v{self.EXF_FIX_V}.json"),
                                         {"ts": int(time.time()), "v": self.EXF_FIX_V, "moves": plan})
            n = self._exf_fix_place_apply(plan) if plan else 0
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fix_place_v', ?)", (f"{self.EXF_FIX_V}:{int(time.time())}:{n}",))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            log.error("양수 정정 재배치 보류(되돌림 · 다음 대사에 다시): %s", e)
            return None
        if n:
            self._exf_hist_touch(min(min(int(o["ts"]) for o in m["old"] + m["new"]) for m in plan))
            log.warning("★해외 대사 양수 정정 %d묶음 재배치(원장이 처음 모자란 때부터 — 최소 필요량 분할) — 수량 무변, 지난 곡선 무효화★", n)
            self._exf_hist_flush()
        return n

    EXF_FUT_V = 1
    EXF_FUT_MIG_MIN = Decimal("1")
    EXF_FUT_REST_REL = Decimal("0.05")
    _EXF_ATOM_RE = re.compile(r"^(되돌림|확장 이중 계상 정리|대출 첫 편입 흡수)\(대사 (\d+) ")
    _EXF_DIFF_RE = re.compile(r"^되돌림\(대사 (\d+) 차이 (-?[0-9]+(?:\.[0-9]+)?)\)")

    def _exf_revert_rows(self) -> list:
        out = []
        try:
            fh = open(self.EXF_REVERT_LOG, "r", encoding="utf-8")
        except FileNotFoundError:
            return out
        except OSError as e9:
            raise ValueError(f"되돌림 감사 기록 읽기 실패: {e9}") from e9
        with fh:
            for i9, ln9 in enumerate(fh):
                if not ln9.strip():
                    continue
                try:
                    d9 = json.loads(ln9)
                except ValueError as e9:
                    raise ValueError(f"되돌림 감사 기록 손상: 줄 {i9 + 1}") from e9
                if not isinstance(d9, dict):
                    raise ValueError(f"되돌림 감사 기록 형식 오류: 줄 {i9 + 1}")
                self._exf_revert_row_ok(d9, i9 + 1)
                d9["_i"] = i9
                out.append(d9)
        return out

    _EXF_WHY_OK = (re.compile(r"^(되돌림|확장 이중 계상 정리)\(대사 \d+ 차이 -?[0-9]+(?:\.[0-9]+)?\)$"),
                   re.compile(r"^대출 첫 편입 흡수\(대사 \d+ 부채 차이 -?[0-9]+(?:\.[0-9]+)?\)$"),
                   re.compile(r"^전환 흡수 \S.*$"),
                   re.compile(r"^.+ (?:흡수|늦은 상쇄 되돌림)\(대사 \d+ 구간\)$"))

    @classmethod
    def _exf_revert_row_ok(cls, d9: dict, n9: int) -> None:
        def _int(k):
            v = d9.get(k)
            if isinstance(v, bool) or not re.fullmatch(r"-?[0-9]+", str(v if v is not None else "")):
                raise ValueError(f"되돌림 감사 기록 필드 손상: 줄 {n9} {k}")
            return int(v)
        for k9 in ("ts", "posting_id", "leg_seq", "event_ts", "asset_id"):
            _int(k9)
        old9, new9 = _int("old_qty_base"), _int("new_qty_base")
        loc9, sid9, why9 = d9.get("loc"), d9.get("source_id"), d9.get("why")
        if not isinstance(loc9, str) or not loc9.startswith("exchange:") or not isinstance(sid9, str) or not sid9:
            raise ValueError(f"되돌림 감사 기록 필드 손상: 줄 {n9} loc·source_id")
        if not isinstance(why9, str) or not any(r9.match(why9) for r9 in cls._EXF_WHY_OK):
            raise ValueError(f"되돌림 감사 기록 사유 손상: 줄 {n9}")
        if old9 == 0 or abs(new9) >= abs(old9) or (new9 != 0 and (new9 > 0) != (old9 > 0)):
            raise ValueError(f"되돌림 감사 기록 수량 손상: 줄 {n9} ({old9} → {new9})")

    @classmethod
    def _exf_atom(cls, e: dict):
        m9 = cls._EXF_ATOM_RE.match(str(e.get("why") or ""))
        return (m9.group(1), int(m9.group(2))) if m9 else (None, None)

    def _exf_first_bts(self, ex: str):
        b0 = None
        for r in self.conn.execute("SELECT source_id FROM postings WHERE source_ns=? AND event='EXF_ADJUST'", (f"{ex}:recon",)):
            b9 = self._exf_bts(r[0])
            if b9 is not None and (b0 is None or b9 < b0):
                b0 = b9
        try:
            t9 = self.conn.execute("SELECT min(bts) FROM exf_adj_tomb WHERE ex=?", (ex,)).fetchone()[0]
        except sqlite3.OperationalError:
            t9 = None
        if t9 is not None and (b0 is None or int(t9) < b0):
            b0 = int(t9)
        return b0

    def _exf_fut_plan_sym(self, ex: str, sym: str, evs: list, log9: list, done9: int, first9, fut_b=frozenset(), cur_ok=False):
        loc, ns, pfx = f"exchange:{ex}", f"{ex}:recon", f"exfrecon:{sym}:"
        rows = [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.source_id, p.leg_seq, p.event_ts, p.qty_base, p.asset_id, p.classifier_ver, a.decimals"
            " FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?", (ns, loc, sym)).fetchall()]
        rows = [r for r in rows if str(r["source_id"]).startswith(pfx) and self._exf_bts(r["source_id"]) is not None]
        lg = [e for e in log9 if e.get("loc") == loc and str(e.get("source_id") or "").startswith(pfx)
              and self._exf_bts(e.get("source_id")) is not None]
        recs = {self._exf_bts(r["source_id"]) for r in rows} | {self._exf_bts(e["source_id"]) for e in lg}
        recs |= {b9 for k9, b9 in map(self._exf_atom, lg) if k9}
        tomb9 = set()
        try:
            tomb9 = {int(t[0]) for t in self.conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex=? AND sym=?", (ex, sym))}
        except sqlite3.OperationalError:
            pass
        recs |= tomb9
        recs |= set(fut_b)
        recs = sorted(b9 for b9 in recs if b9 is not None and b9 <= done9)
        last9 = recs[-1] if recs else None
        if first9 is None or not evs:
            return None, last9
        if cur_ok and last9 is not None and last9 < done9:
            lo9 = max([last9] + [b9 for b9 in fut_b if b9 <= done9])
            tail9 = sum((a9 for _t9, tm9, a9 in evs if lo9 * 1000 < tm9 <= done9 * 1000), Decimal(0))
            if abs(tail9) >= self.EXF_FUT_MIG_MIN and done9 > first9 + self.EXF_INIT_PHASE:
                return {"ex": ex, "sym": sym, "hold": f"마지막 흔적 대사 뒤 정산 합 {tail9} — 대사 줄·감사 기록 없음(이미 반영 여부 근거 없음)",
                        "skip": []}, last9
        fwin, cands, prev = {}, [], None
        for b9 in recs:
            if prev is not None and b9 > first9 + self.EXF_INIT_PHASE and b9 not in fut_b:
                sel9 = [(t9, a9) for t9, tm9, a9 in evs if prev * 1000 < tm9 <= b9 * 1000]
                if abs(sum((a9 for _t, a9 in sel9), Decimal(0))) >= self.EXF_FUT_MIG_MIN:
                    cands.append(b9)
                    fwin[b9] = sel9
            prev = b9
        if not cands:
            return None, last9
        aid, dec = self._exf_main_inst(ex, sym)
        scale = Decimal(10) ** int(dec)
        live9 = {self._exf_bts(r["source_id"]) for r in rows}
        aud9 = {self._exf_bts(e["source_id"]) for e in lg}
        mv9 = self._exf_latefix_moved()
        miss9 = sorted(b9 for b9 in tomb9 if b9 <= done9 and b9 not in live9 and b9 not in aud9 and b9 not in fut_b and (ex, sym, b9) not in mv9)
        if miss9:
            log.error("선물 정산 재배치 불가: %s %s — 지운 대사 %d건의 되돌림 감사 기록 없음(%s)", ex, sym, len(miss9), miss9[:5])
            return {"ex": ex, "sym": sym, "hold": f"지운 대사 {len(miss9)}건의 되돌림 감사 기록 없음(대사 시각 {miss9[:5]})", "skip": []}, last9
        decs9 = {8 if r["decimals"] is None else int(r["decimals"]) for r in rows}
        if decs9 - {int(dec)}:
            log.warning("선물 정산 재배치 건너뜀: %s %s — 자리수 %s", ex, sym, sorted(decs9))
            return {"ex": ex, "sym": sym, "hold": f"자리수 여럿 {sorted(decs9)}", "skip": []}, last9
        base = {(str(r["source_id"]), int(r["leg_seq"])): r for r in rows}
        skip = {}
        repl = set(cands)
        while True:
            changed9 = True
            while changed9:
                changed9 = False
                for b9 in sorted(repl):
                    why9 = None
                    for e in lg:
                        k9, p9 = self._exf_atom(e)
                        if p9 == b9 and k9 != "되돌림":
                            why9 = f"되돌림 말고 다른 흡수({k9})"
                            break
                        if self._exf_bts(e["source_id"]) == b9 and (k9 != "되돌림" or p9 not in repl):
                            why9 = "만든 행을 후보 아닌 것이 줄임"
                            break
                    if why9 is None and any(int(base[k]["asset_id"]) != int(aid) for k in base if k[0] == f"{pfx}{b9}"):
                        why9 = "주 자산이 아닌 행"
                    if why9:
                        repl.discard(b9)
                        skip[b9] = why9
                        changed9 = True
            state = {k: {"ts": int(r["event_ts"]), "aid": int(r["asset_id"]), "qb": int(r["qty_base"])} for k, r in base.items()}
            undo, bad9 = {}, None
            for b9 in sorted(repl, reverse=True):
                atoms = sorted((e for e in lg if self._exf_atom(e)[1] == b9), key=lambda e: e["_i"])
                for e in reversed(atoms):
                    k = (str(e["source_id"]), int(e.get("leg_seq") or 0))
                    try:
                        old9, new9 = int(e["old_qty_base"]), int(e["new_qty_base"])
                    except (KeyError, TypeError, ValueError):
                        bad9 = (b9, "감사 기록 형식 오류")
                        break
                    if (state[k]["qb"] if k in state else 0) != new9 or int(e.get("asset_id") or 0) != int(aid):
                        bad9 = (b9, "되돌린 행이 그 뒤 바뀜")
                        break
                    state[k] = {"ts": state[k]["ts"] if k in state else int(e["event_ts"]), "aid": int(aid), "qb": old9}
                if bad9:
                    break
                mine = {k: v for k, v in state.items() if k[0] == f"{pfx}{b9}"}
                for k in mine:
                    del state[k]
                d9 = sum(v["qb"] for v in mine.values()) + sum(int(e["new_qty_base"]) - int(e["old_qty_base"]) for e in atoms)
                tol9 = len(mine) + len(atoms) + 1
                for e in atoms:
                    m9 = self._EXF_DIFF_RE.match(str(e.get("why") or ""))
                    if m9 and int(m9.group(1)) == b9 and abs(Decimal(m9.group(2)) * scale - d9) >= tol9:
                        bad9 = (b9, f"차이 기록 {m9.group(2)} ≠ 재구성 {Decimal(d9) / scale}")
                        break
                if bad9:
                    break
                undo[b9] = (d9, mine)
            if bad9:
                repl.discard(bad9[0])
                skip[bad9[0]] = bad9[1]
                continue
            break
        if not repl:
            return ({"ex": ex, "sym": sym, "skip": sorted(skip.items())} if skip else None), last9
        fut = []
        for b9 in sorted(repl):
            d9, mine = undo[b9]
            legs9 = self._exf_fut_legs(fwin[b9], scale)
            res9 = d9 - sum(q9 for _t, q9 in legs9)
            l2 = {k: v for k, v in mine.items() if k[1] == 2}
            l2s = sum(v["qb"] for v in l2.values())
            rest9 = res9
            if len(l2) == 1 and l2s != 0 and res9 != 0 and (l2s > 0) == (res9 > 0):
                (k2, v2), = l2.items()
                q2 = l2s if abs(l2s) <= abs(res9) else res9
                state[k2] = dict(v2, qb=int(q2))
                rest9 = res9 - q2
            f9 = sum(q9 for _t, q9 in legs9)
            if abs(rest9) > max(self.EXF_FUT_MIG_MIN * scale, abs(Decimal(f9)) * self.EXF_FUT_REST_REL):
                return {"ex": ex, "sym": sym, "hold": f"대사 {b9} 차이가 선물 정산으로 설명 안 됨(남는 몫 {Decimal(rest9) / scale} · 선물 "
                                                      f"{Decimal(f9) / scale}) — 근거 부족", "skip": []}, last9
            if rest9:
                k0 = (f"{pfx}{b9}", 0)
                state[k0] = {"ts": int(b9), "aid": int(aid), "qb": int(rest9)}
            fut += [{"sid": f"{pfx}{b9}", "leg": i9, "ts": int(t9), "qb": str(q9)} for i9, (t9, q9) in enumerate(legs9)]
        late_mv = self._exf_fut_late_place(ex, sym, base, state, repl, aid, scale)
        ops = {"del": [], "upd": [], "ins": []}
        for k in sorted(set(base) | set(state)):
            a9, s9 = base.get(k), state.get(k)
            if a9 is not None and (s9 is None or s9["qb"] == 0):
                ops["del"].append({"pid": int(a9["posting_id"]), "sid": k[0], "leg": k[1], "ts": int(a9["event_ts"]), "aid": int(a9["asset_id"]),
                                   "qb": str(a9["qty_base"]), "cv": int(a9["classifier_ver"] or CLASSIFIER_VER)})
            elif a9 is None and s9 is not None and s9["qb"] != 0:
                ops["ins"].append({"sid": k[0], "leg": k[1], "ts": int(s9["ts"]), "aid": int(s9["aid"]), "qb": str(s9["qb"])})
            elif a9 is not None and (int(a9["qty_base"]) != s9["qb"] or int(a9["event_ts"]) != s9["ts"]):
                ops["upd"].append({"pid": int(a9["posting_id"]), "sid": k[0], "leg": k[1], "ts": int(a9["event_ts"]), "qb": str(a9["qty_base"]),
                                   "ts_new": int(s9["ts"]), "qb_new": str(s9["qb"])})
        before9 = sum(int(r["qty_base"]) for r in rows)
        after9 = sum(v["qb"] for v in state.values()) + sum(int(f9["qb"]) for f9 in fut)
        if before9 != after9:
            log.error("선물 정산 재배치 건너뜀: %s %s — 합 불일치 %d ≠ %d", ex, sym, before9, after9)
            return {"ex": ex, "sym": sym, "err": f"합 불일치 {before9} ≠ {after9}", "skip": sorted(skip.items())}, last9
        ts9 = [o["ts"] for o in ops["del"] + ops["upd"] + ops["ins"]] + [o["ts_new"] for o in ops["upd"]] + [f9["ts"] for f9 in fut]
        return ({"ex": ex, "sym": sym, "loc": loc, "aid": int(aid), "dec": int(dec), "cands": sorted(repl), "skip": sorted(skip.items()),
                 "del": ops["del"], "upd": ops["upd"], "ins": ops["ins"], "fut": fut, "t_from": min(ts9) if ts9 else None,
                 "f_sum": str(sum(Decimal(int(f9["qb"])) for f9 in fut) / scale), "late": late_mv}, last9)

    EXF_LATE_OBS_GAP = 600
    EXF_LATE_RECON_WIN = 7200
    EXF_LATE_REL = Decimal("0.01")

    def _exf_latefix_moved(self) -> set:
        if "_exf_lfm" in self.__dict__:
            return self._exf_lfm
        out = set()
        try:
            names = [n for n in os.listdir(common.STATE_DIR) if n.startswith("latefix_move_undo_") and n.endswith(".json")]
        except OSError:
            names = []
        for n9 in names:
            try:
                for m9 in json.load(open(os.path.join(common.STATE_DIR, n9), encoding="utf-8")) or []:
                    if isinstance(m9, dict) and m9.get("ex") and m9.get("sym") and m9.get("bts") is not None:
                        out.add((str(m9["ex"]), str(m9["sym"]).upper(), int(m9["bts"])))
            except (OSError, ValueError, TypeError):
                continue
        self._exf_lfm = out
        return out

    def _exf_late_batches(self, ex: str) -> list:
        c9 = self.__dict__.setdefault("_exf_late_bcache", {})
        if ex in c9:
            return c9[ex]
        tr9, dw9 = [], []
        for r in self.conn.execute("SELECT kind, payload, observed_at FROM raw_ex WHERE exchange=? AND kind IN ('trade','deposit','withdraw')"
                                   " AND payload LIKE '%late%'", (ex,)):
            try:
                p9 = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            if not isinstance(p9, dict) or not p9.get("late"):
                continue
            if r["kind"] == "trade":
                tr9.append((int(r["observed_at"]), p9))
            else:
                dw9.append((int(r["observed_at"]), {str(p9.get("currency") or "").upper(), str(p9.get("fee_ccy") or "").upper()}))
        out = []
        for o9, p9 in sorted(tr9, key=lambda x: x[0]):
            if out and o9 - out[-1]["o1"] <= self.EXF_LATE_OBS_GAP:
                out[-1]["o1"] = o9
                out[-1]["f"].append(p9)
            else:
                out.append({"o0": o9, "o1": o9, "f": [p9]})
        for b in out:
            dl9 = {}
            for sym9, lst9 in self._late_fill_deltas(b.pop("f")).items():
                old9 = [(t9, a9) for t9, a9 in lst9 if t9 < b["o0"] - self.EXF_LATE_OBS_GAP]
                if old9:
                    dl9[sym9] = old9
            b["dl"] = dl9
            b["mixed"] = set().union(*[c for o9, c in dw9 if b["o0"] - self.EXF_LATE_OBS_GAP <= o9 <= b["o1"] + self.EXF_LATE_OBS_GAP]) if dw9 else set()
        c9[ex] = out
        return out

    def _exf_fut_late_place(self, ex: str, sym: str, base: dict, state: dict, repl: set, aid: int, scale: Decimal) -> list:
        if sym in self.EXF_FIX_SKIP:
            return []
        out, bnds9 = [], None
        for k in sorted(list(state)):
            sid9, leg9 = k
            b9 = self._exf_bts(sid9)
            s9 = state[k]
            a9 = base.get(k)
            if (leg9 != 0 or b9 is None or not str(sid9).startswith("exfrecon:") or b9 in repl or s9["qb"] >= 0 or abs(int(s9["ts"]) - b9) > 60
                    or (a9 is not None and int(a9["qty_base"]) == s9["qb"])):
                continue
            q9 = Decimal(s9["qb"]) / scale
            hit9 = None
            for bt in self._exf_late_batches(ex):
                if not (bt["o1"] <= b9 <= bt["o1"] + self.EXF_LATE_RECON_WIN) or sym not in bt["dl"]:
                    continue
                if sym in bt["mixed"]:
                    hit9 = None
                    break
                dl9 = bt["dl"][sym]
                net9 = sum((a for _t, a in dl9), Decimal(0))
                if net9 <= 0 or abs(abs(q9) - net9) > net9 * self.EXF_LATE_REL:
                    continue
                if bnds9 is None:
                    bnds9 = self._exf_bounds_q(self.conn, ex, sym)
                grp9 = {}
                for t9, a9q in dl9:
                    grp9.setdefault(self._exf_bucket(bnds9, t9), []).append((t9, a9q))
                cl9 = sorted(((t0, t1, n9, bk9) for bk9, lst9 in grp9.items() for t0, t1, n9 in self._exf_late_clusters(lst9)), key=lambda c: (c[1], c[0]))
                if any(c[2] <= 0 for c in cl9):
                    hit9 = None
                    break
                dup9 = self.conn.execute(
                    "SELECT count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.location=? AND upper(a.symbol)=?"
                    " AND p.source_id LIKE ? AND p.event_ts BETWEEN ? AND ?", (f"{ex}:recon", f"exchange:{ex}", sym, f"{self.EXF_LATE_PFX}{sym}:%",
                                                                               int(cl9[0][0]), int(cl9[-1][1]) + self.EXF_LATE_DT)).fetchone()[0]
                if dup9:
                    hit9 = None
                    break
                hit9 = (net9, cl9)
                break
            if hit9 is None:
                continue
            net9, cl9 = hit9
            net_b = int((net9 * scale).to_integral_value())
            parts, used = [], 0
            for i9, (t0, t1, n9, bk9) in enumerate(cl9):
                qb9 = (net_b - used) if i9 == len(cl9) - 1 else int((n9 * scale).to_integral_value())
                used += qb9
                t_off = int(t1) + self.EXF_LATE_DT
                sid_l = self._exf_late_sid(sym, t_off, bk9)
                r9 = self.conn.execute("SELECT MAX(leg_seq) FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                                       (f"{ex}:recon", sid_l)).fetchone()
                leg_l = 0 if r9 is None or r9[0] is None else int(r9[0]) + 1
                while (sid_l, leg_l) in state:
                    leg_l += 1
                state[(sid_l, leg_l)] = {"ts": t_off, "aid": int(aid), "qb": -qb9}
                parts.append({"sid": sid_l, "leg": leg_l, "ts": t_off, "qb": str(-qb9)})
            rem9 = int(s9["qb"]) + net_b
            state[k] = dict(s9, qb=rem9)
            out.append({"sid": sid9, "bts": b9, "q": str(s9["qb"]), "net": str(net_b), "parts": parts, "rem": str(rem9)})
            log.info("선물 정산 재배치: %s %s 되살린 대사 %s 음수 %s 중 %s = 늦은 체결 묶음 상쇄 → 묶음 직후 %d줄(대사 시각 남는 몫 %s)", ex, sym, b9,
                     format(q9, "f"), format(net9, "f"), len(parts), format(Decimal(rem9) / scale, "f"))
        return out

    def _exf_fut_place_plan(self, only=None):
        plan, curs = [], {}
        self.__dict__.pop("_exf_late_bcache", None)
        self.__dict__.pop("_exf_lfm", None)
        try:
            lf9 = self._meta_get("exf_revert_log_fail")
            if lf9:
                raise ValueError(f"되돌림 감사 기록 쓰기 실패 이력(meta exf_revert_log_fail {lf9}) — 확인 뒤 표식을 지워야 이관")
            log9 = self._exf_revert_rows()
        except ValueError as e9:
            return [{"ex": ex9, "sym": "*", "err": str(e9), "skip": []} for ex9 in self.EXF_FUT_EX
                    if self._meta_get(f"recon_done_exf_{ex9}") and (only is None or ex9 in only)], {}
        for ex in self.EXF_FUT_EX:
            if only is not None and ex not in only:
                continue
            d9 = self._meta_get(f"recon_done_exf_{ex}")
            if not d9:
                continue
            if ex == "binance":
                try:
                    srcb9 = json.loads(self._meta_get("recon_src_exf_binance") or "null")
                except (TypeError, ValueError):
                    srcb9 = None
                if not isinstance(srcb9, list) or "futures" not in srcb9:
                    continue
            done9 = int(float(d9))
            try:
                from9 = int(float(self._meta_get(f"exf_fut_from_{ex}")))
            except (TypeError, ValueError):
                from9 = None
            hi9 = done9 if from9 is None else min(done9, from9)
            _fts, evs9 = self._exf_fut_events(ex)
            if _fts is None and not os.path.exists(os.path.join(common.STATE_DIR, f"futures_{ex}.json")):
                continue
            if not _fts or int(_fts) < hi9:
                plan.append({"ex": ex, "sym": "*", "err": f"선물 정산 파일이 없거나 손상·낡음(파일 {_fts} < 마지막 대사 {hi9})", "skip": []})
                continue
            first9 = self._exf_first_bts(ex) if evs9 else None
            for sym in sorted(evs9):
                fb9 = {b9 for (s9,) in self.conn.execute("SELECT DISTINCT source_id FROM postings WHERE source_ns=? AND event='EXF_ADJUST'"
                                                           " AND source_id LIKE ?", (f"{ex}:{common.EXF_FUT_NS}", f"exfrecon:{sym}:%"))
                       for b9 in (self._exf_bts(s9),) if b9 is not None}
                m9, last9 = self._exf_fut_plan_sym(ex, sym, evs9[sym], log9, hi9, first9, fb9, cur_ok=(hi9 == done9))
                if m9:
                    plan.append(m9)
                if last9 is not None and last9 < done9 and hi9 == done9 and not (m9 and m9.get("hold")):
                    curs.setdefault(ex, {})[sym] = int(last9)
        return plan, curs

    def _exf_fut_place_apply(self, plan: list) -> int:
        n = 0
        for m in plan:
            if not m.get("cands"):
                continue
            ex, loc, sym = m["ex"], m["loc"], m["sym"]
            for o in m["del"] + m["upd"]:
                r9 = self.conn.execute("SELECT source_ns, source_id, leg_seq, event_ts, qty_base FROM postings WHERE posting_id=?", (o["pid"],)).fetchone()
                if (r9 is None or r9["source_ns"] != f"{ex}:recon" or r9["source_id"] != o["sid"] or int(r9["leg_seq"]) != o["leg"]
                        or int(r9["event_ts"]) != o["ts"] or str(r9["qty_base"]) != o["qb"]):
                    raise ValueError(f"재배치 대상이 계획 뒤 바뀜 {o['sid']} leg {o['leg']}")
            tot9 = 0
            for o in m["del"]:
                self.conn.execute("DELETE FROM postings WHERE posting_id=?", (o["pid"],))
                self._bump_position(int(o["aid"]), -int(o["qb"]), loc)
                tot9 -= int(o["qb"])
            for o in m["upd"]:
                self.conn.execute("UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?", (int(o["ts_new"]), o["qb_new"], o["pid"]))
                self._bump_position(int(m["aid"]), int(o["qb_new"]) - int(o["qb"]), loc)
                tot9 += int(o["qb_new"]) - int(o["qb"])
            for ns9, lst9 in ((f"{ex}:recon", m["ins"]), (f"{ex}:{common.EXF_FUT_NS}", m["fut"])):
                for o in lst9:
                    cur9 = self.conn.execute(
                        "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening',"
                        " 'EXF_ADJUST', ?)", (ns9, o["sid"], int(o["leg"]), int(o["ts"]), int(o.get("aid") or m["aid"]), loc, o["qb"], CLASSIFIER_VER))
                    if not cur9.rowcount:
                        raise ValueError(f"재배치 줄 충돌 {ns9} {o['sid']} leg {o['leg']}")
                    self._bump_position(int(o.get("aid") or m["aid"]), int(o["qb"]), loc)
                    tot9 += int(o["qb"])
            if tot9 != 0:
                raise ValueError(f"재배치 합 불일치 {ex} {sym}: {tot9}")
            for b9 in m["cands"]:
                try:
                    self.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)", (ex, sym, int(b9)))
                except sqlite3.OperationalError:
                    pass
            n += 1
        return n

    EXF_FUT_WAIT_META = "exf_fut_place_wait"
    EXF_FUT_BACKUP_MAX_AGE = 36 * 3600

    def _exf_fut_place_scope(self):
        p9 = str(self._meta_get("exf_fut_place_v") or "").split(":")
        if p9[0] != str(self.EXF_FUT_V):
            return "todo", None
        if len(p9) >= 2 and p9[1] == "undone":
            return "undone", None
        try:
            w9 = json.loads(self._meta_get(self.EXF_FUT_WAIT_META) or "null")
        except (TypeError, ValueError):
            w9 = None
        if isinstance(w9, dict) and w9.get("v") == self.EXF_FUT_V and isinstance(w9.get("ex"), dict) and w9["ex"]:
            return "partial", {str(x) for x in w9["ex"]}
        return "done", None

    def _exf_fut_backup_ok(self):
        try:
            st9 = common.read_json(os.path.join(common.STATE_DIR, "backups", "backup_status.json"), {}) or {}
            p9 = str(st9.get("last_path") or "")
            if time.time() - float(st9.get("last_ok") or 0) <= self.EXF_FUT_BACKUP_MAX_AGE and p9 and os.path.isfile(p9):
                return p9
        except (Exception, SystemExit):
            pass
        return None

    def _exf_fut_place_once(self, expect=None, redo=False, auto=False):
        sc, pend = self._exf_fut_place_scope()
        if sc == "done" or (sc == "undone" and not redo):
            return None
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            sc, pend = self._exf_fut_place_scope()
            if sc == "done" or (sc == "undone" and not redo):
                self.conn.rollback()
                return None
            plan, curs = self._exf_fut_place_plan(only=pend)
            if expect is not None and json.loads(json.dumps(plan)) != json.loads(json.dumps(expect)):
                self.conn.rollback()
                log.error("선물 정산 재배치 거부 — 잠금 안 계획(%d)이 검토한 계획(%d)과 다름(원장이 그 사이 바뀜)", len(plan), len(expect))
                return False
            errx = {}
            for m in plan:
                if m.get("err"):
                    errx.setdefault(m["ex"], f"{m['sym']}: {m['err']}" if m.get("sym") not in (None, "*") else str(m["err"]))
            scope9 = [ex9 for ex9 in self.EXF_FUT_EX if (pend is None or ex9 in pend) and self._meta_get(f"recon_done_exf_{ex9}")]
            act9 = [m for m in plan if m.get("cands") and m["ex"] not in errx]
            bk9 = None
            if auto and act9:
                bk9 = self._exf_fut_backup_ok()
                if bk9 is None:
                    for m in act9:
                        errx.setdefault(m["ex"], "적용 전 원장 백업 없음(36시간 안 정기 백업 — state/backups · 디스크 여유 확인)")
                    act9 = []
            okx9 = [ex9 for ex9 in scope9 if ex9 not in errx]
            if errx and not okx9:
                self.conn.rollback()
                self._exf_fut_place_wait_set(errx)
                if time.time() - float(self.__dict__.get("_exf_fut_err_log", 0) or 0) >= 3600:
                    self._exf_fut_err_log = time.time()
                    log.error("★선물 정산 재배치 보류 — 거래소 %d곳: %s★ (tools/exf_fut_place.py 로 확인)", len(errx),
                              "; ".join(f"{k} {v}" for k, v in sorted(errx.items())[:4]))
                return None
            for m in act9:
                m["tomb_new"] = [int(b9) for b9 in m["cands"] if self.conn.execute(
                    "SELECT 1 FROM exf_adj_tomb WHERE ex=? AND sym=? AND bts=?", (m["ex"], m["sym"], int(b9))).fetchone() is None]
            keep9 = [m for m in plan if m["ex"] not in errx]
            n_prev = 0
            undo_p9 = os.path.join(common.STATE_DIR, f"exf_fut_place_v{self.EXF_FUT_V}.json")
            if sc == "partial":
                try:
                    n_prev = int(str(self._meta_get("exf_fut_place_v") or "").split(":")[2])
                except (IndexError, ValueError):
                    n_prev = 0
            if act9:
                prev9 = None
                if sc == "partial" and n_prev:
                    prev9 = common.read_json(undo_p9, None)
                    if not (isinstance(prev9, dict) and prev9.get("v") == self.EXF_FUT_V and isinstance(prev9.get("plan"), list)):
                        raise ValueError("앞 회차 되돌리기 자료가 없거나 다름 — 이어 붙일 수 없음")
                cu9 = {k9: v9 for k9, v9 in curs.items() if k9 not in errx}
                common.atomic_write_json(undo_p9, {"ts": int(time.time()), "v": self.EXF_FUT_V,
                                                   "plan": (prev9["plan"] if prev9 else []) + keep9,
                                                   "curs": dict((prev9 or {}).get("curs") or {}, **cu9)})
            n = self._exf_fut_place_apply(act9) if act9 else 0
            for ex9 in okx9:
                d9 = self._meta_get(f"recon_done_exf_{ex9}")
                if self._meta_get(f"exf_fut_cur_{ex9}") is None:
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                      (f"exf_fut_cur_{ex9}", json.dumps({"t": int(float(d9)), "s": curs.get(ex9) or {}}, sort_keys=True)))
                if self._meta_get(f"exf_fut_from_{ex9}") is None:
                    self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_fut_from_{ex9}", str(int(float(d9)))))
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', ?)", (f"{self.EXF_FUT_V}:{int(time.time())}:{n_prev + n}",))
            dbm.bump_data_rev(self.conn, 1)
            if errx:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (self.EXF_FUT_WAIT_META, json.dumps({"v": self.EXF_FUT_V, "ex": errx}, ensure_ascii=False, sort_keys=True)))
            else:
                self.conn.execute("DELETE FROM meta WHERE k=?", (self.EXF_FUT_WAIT_META,))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            log.error("선물 정산 재배치 보류(되돌림 · 다음 대사에 다시): %s", e)
            return None
        self._exf_fut_place_wait_set(errx)
        for m in plan:
            if m.get("err"):
                log.error("선물 정산 재배치: %s %s 통화 전체 건너뜀 — %s", m["ex"], m["sym"], m["err"])
            if m.get("hold"):
                log.warning("선물 정산 재배치: %s %s 보류(옛 배치 유지 — 근거 부족): %s", m["ex"], m["sym"], m["hold"])
            for b9, why9 in m.get("skip") or ():
                log.warning("선물 정산 재배치: %s %s 대사 %s 건너뜀 — %s", m["ex"], m["sym"], b9, why9)
        if errx:
            log.warning("★선물 정산 재배치 — 거래소 %s 는 대기(나머지는 옮김 · 다음 대사에 그 거래소만 다시): %s★", ",".join(sorted(errx)),
                        "; ".join(f"{k} {v}" for k, v in sorted(errx.items())[:4]))
        if n:
            self._exf_hist_touch(min(m["t_from"] for m in act9 if m.get("t_from") is not None))
            log.warning("★선물 정산 재배치 %d개 통화(대사 %d건 — 지난날 소급·되돌림 → 정산 시각) — 원장 합 무변, 지난 곡선 무효화%s★", n,
                        sum(len(m["cands"]) for m in act9), f" · 적용 전 원장 백업 {bk9}" if bk9 else "")
            self._exf_hist_flush()
        return n

    def _exf_fut_place_wait_set(self, errx: dict) -> None:
        new9 = {str(k): str(v)[:200] for k, v in (errx or {}).items()}
        old9 = self.__dict__.get("_exf_fut_place_wait")
        if old9 == new9 and (not new9 or time.time() - float(self.__dict__.get("_exf_fut_place_wait_at") or 0) < 3600):
            return
        since9 = dict(self.__dict__.get("_exf_fut_place_since") or {})
        for k in new9:
            since9.setdefault(k, int(time.time()))
        self._exf_fut_place_since = {k: v for k, v in since9.items() if k in new9}
        self._exf_fut_place_wait = new9
        self._exf_fut_place_wait_at = time.time()
        self._exf_fut_wait_save()

    def _exf_unit_usd(self, ex: str, sym: str, insts: list):
        s9 = sym.upper()
        if s9 in self.EXF_STABLE_QUOTES or s9 in ("USDG", "USDE", "USD1", "TUSD"):
            return Decimal(1)
        if s9 == "KRW":
            try:
                fx = self.px.fx_at(int(time.time()) * 1000)
            except Exception:
                fx = None
            return (Decimal(1) / Decimal(str(fx))) if fx else None
        for where, args in ((("p.asset_id IN (%s)" % ",".join("?" * len(insts))), list(insts)) if insts else (None, None),
                            ("a.kind='exchange_currency' AND upper(a.symbol)=?", [s9])):
            if not where:
                continue
            r = self.conn.execute(
                "SELECT p.cost_usd, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE " + where + " AND p.cost_usd IS NOT NULL AND p.leg_seq=0"
                " AND p.event IN ('EXF_BUY', 'EXF_SELL') ORDER BY p.event_ts DESC LIMIT 1", args).fetchone()
            if r:
                try:
                    qn = abs(Decimal(int(r["qty_base"]))) / (Decimal(10) ** (8 if r["decimals"] is None else int(r["decimals"])))
                    c9 = abs(Decimal(str(r["cost_usd"])))
                    if qn > 0 and c9.is_finite():
                        return c9 / qn
                except (ArithmeticError, ValueError, TypeError):
                    pass
        return None

    def _exf_micro(self, ex, sym, insts, diff: Decimal, ledger: Decimal, actual) -> bool:
        px = self._exf_unit_usd(ex, sym, insts)
        if px is not None and px > 0:
            return abs(diff) * px < self.EXF_MICRO_USD
        big = max(abs(ledger), abs(Decimal(str(actual or 0))))
        return big > 0 and abs(diff) <= big * self.EXF_MICRO_REL

    EXF_REVERT_LOG = os.path.join(common.STATE_DIR, "exf_recon_revert.jsonl")

    def _exf_shrink(self, r: dict, take_base: int, loc: str, why: str = "") -> None:
        old = int(r["qty_base"])
        new = old + take_base if old < 0 else old - take_base
        if (old < 0 and new > 0) or (old > 0 and new < 0):
            new = 0
        try:
            with open(self.EXF_REVERT_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": int(time.time()), "loc": loc, "posting_id": int(r["posting_id"]), "source_id": r.get("source_id"),
                                     "leg_seq": r.get("leg_seq"), "event_ts": int(r["event_ts"]), "asset_id": int(r["asset_id"]),
                                     "old_qty_base": str(old), "new_qty_base": str(new), "why": why}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("대사 되돌림 감사 기록 실패(기장은 진행): %s", e)
            try:
                n9 = int(str(self._meta_get("exf_revert_log_fail") or "0").split(":", 1)[0] or 0)
            except ValueError:
                n9 = 0
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_revert_log_fail', ?)", (f"{n9 + 1}:{int(time.time())}",))
        if new == 0:
            self.conn.execute("DELETE FROM postings WHERE posting_id=?", (r["posting_id"],))
            try:
                sid9 = str(r.get("source_id") or "")
                if sid9.startswith("exfrecon:") and str(loc).startswith("exchange:"):
                    sym9, b9 = sid9[len("exfrecon:"):].rsplit(":", 1)
                    self.conn.execute("INSERT OR IGNORE INTO exf_adj_tomb (ex, sym, bts) VALUES (?,?,?)",
                                      (str(loc)[len("exchange:"):], sym9.upper(), int(b9)))
            except (ValueError, sqlite3.OperationalError) as e9:
                log.warning("대사 구간 경계 기록 실패(되돌림은 진행): %s", e9)
        else:
            self.conn.execute("UPDATE postings SET qty_base=? WHERE posting_id=?", (str(new), r["posting_id"]))
        self._bump_position(r["asset_id"], new - old, loc)
        r["qty_base"] = str(new)
        r["_t"] = True
        self._exf_hist_touch(r["event_ts"])

    EXF_NOW_EX = ("hyperliquid",)

    def _exf_now_sym(self, ex: str, sym: str) -> bool:
        if ex not in self.EXF_NOW_EX:
            return False
        p9 = os.path.join(common.STATE_DIR, "hl_cash_syms.json")
        try:
            mt9 = os.path.getmtime(p9)
        except OSError:
            mt9 = None
        c9 = self.__dict__.get("_hl_cash_cache")
        if not c9 or c9[0] != mt9:
            syms9 = {"USDC"}
            if mt9 is not None:
                try:
                    syms9 |= {str(x).upper() for x in ((common.read_json(p9, {}) or {}).get("syms") or []) if isinstance(x, str)}
                except (Exception, SystemExit):
                    pass
            c9 = (mt9, frozenset(syms9))
            self.__dict__["_hl_cash_cache"] = c9
        return str(sym or "").upper() in c9[1]

    EXF_FUT_EX = ("binance", "bybit", "okx")
    EXF_FUT_KINDS = frozenset(("REALIZED", "FUNDING", "FEE"))
    EXF_FUT_GROUP_S = 60

    @staticmethod
    def _exf_fut_sym(ex: str, symbol) -> str:
        s9 = str(symbol or "").upper()
        if ex == "okx":
            p9 = s9.split("-")
            return p9[1] if len(p9) >= 3 and p9[1] in ("USDT", "USDC") else ""
        if s9.endswith("USDT"):
            return "USDT"
        if s9.endswith("USDC") or (ex == "bybit" and s9.endswith("PERP")):
            return "USDC"
        return ""

    def _exf_fut_events(self, ex: str):
        p9 = os.path.join(common.STATE_DIR, f"futures_{ex}.json")
        try:
            mt9 = os.path.getmtime(p9)
        except OSError:
            return None, {}
        cache9 = self.__dict__.setdefault("_exf_fut_cache", {})
        c9 = cache9.get(ex)
        if c9 and c9[0] == mt9:
            return c9[1], c9[2]
        try:
            d9 = common.read_json(p9, {}) or {}
        except (Exception, SystemExit) as e9:
            log.warning("%s 선물 정산 파일 읽기 실패: %s", ex, e9)
            return 0, {}
        out9 = {}
        evs9 = d9.get("events") if isinstance(d9, dict) else None
        for r9 in (evs9 if isinstance(evs9, list) else ()):
            if not isinstance(r9, dict) or r9.get("kind") not in self.EXF_FUT_KINDS:
                continue
            s9 = self._exf_fut_sym(ex, r9.get("symbol"))
            a0 = r9.get("amount")
            if not s9 or isinstance(a0, bool) or isinstance(r9.get("t"), bool):
                continue
            as9 = r9.get("asset")
            if isinstance(as9, str) and as9.strip():
                as9 = as9.strip().upper()
                if not as9.isalnum() or len(as9) > 20:
                    continue
                s9 = as9
            try:
                t9 = int(r9.get("t") or 0)
                a9 = Decimal(str(a0 if a0 is not None else 0))
            except (TypeError, ValueError, ArithmeticError):
                continue
            if t9 <= 0 or not a9.is_finite() or a9 == 0:
                continue
            out9.setdefault(s9, []).append((t9 // 1000, t9, a9))
        for v9 in out9.values():
            v9.sort(key=lambda x: x[1])
        try:
            ts9 = int((d9.get("ts") if isinstance(d9, dict) else 0) or 0) or None
            cov9 = d9.get("inc_cov_ts") if isinstance(d9, dict) else None
            if ts9 and isinstance(cov9, (int, float)) and not isinstance(cov9, bool) and int(cov9) < ts9:
                ts9 = max(0, int(cov9))
        except (TypeError, ValueError):
            ts9 = None
        cache9[ex] = (mt9, ts9, out9)
        return ts9, out9

    def _exf_fut_cur(self, ex: str, done_ts) -> dict:
        try:
            c9 = json.loads(self._meta_get(f"exf_fut_cur_{ex}") or "null")
        except (ValueError, TypeError):
            c9 = None
        if not isinstance(c9, dict) or not isinstance(c9.get("t"), int) or isinstance(c9.get("t"), bool):
            return {"t": int(float(done_ts or 0)), "s": {}}
        s9 = c9.get("s") if isinstance(c9.get("s"), dict) else {}
        return {"t": int(c9["t"]), "s": {str(k): int(v) for k, v in s9.items() if isinstance(v, int) and not isinstance(v, bool)}}

    def _exf_fut_window(self, ex: str, bal: dict, bts: int, done_ts) -> dict:
        if ex not in self.EXF_FUT_EX or not done_ts:
            return {}
        src9 = bal.get("sources") if isinstance(bal, dict) else None
        if ex == "binance" and not (isinstance(src9, list) and "futures" in src9):
            return {}
        fts9, evs9 = self._exf_fut_events(ex)
        if not fts9 or not evs9:
            return {}
        hi9 = min(int(bts), int(fts9))
        cur9 = self._exf_fut_cur(ex, done_ts)
        out9 = {}
        for s9, lst9 in evs9.items():
            lo9 = cur9["s"].get(s9, cur9["t"])
            if hi9 <= lo9:
                continue
            sel9 = [(t9, a9) for t9, tm9, a9 in lst9 if lo9 * 1000 < tm9 <= hi9 * 1000]
            if sel9:
                out9[s9] = sel9
        return out9

    EXF_FUT_WAIT_S = 3 * 3600

    def _exf_fut_hold(self, ex: str, bal: dict, bts: int, done_ts, now: int) -> bool:
        if self._exf_fut_wait_boot():
            self._exf_fut_wait_save()
        w9 = self.__dict__.setdefault("_exf_fut_wait", {})
        if not done_ts or ex not in self.EXF_FUT_EX:
            self._exf_fut_wait_end(ex)
            return False
        src9 = bal.get("sources") if isinstance(bal, dict) else None
        if ex == "binance" and not (isinstance(src9, list) and "futures" in src9):
            self._exf_fut_wait_end(ex)
            return False
        fts9, _e9 = self._exf_fut_events(ex)
        if fts9 is None or int(fts9) >= int(bts):
            self._exf_fut_wait_end(ex)
            return False
        new9 = ex not in w9
        t0 = w9.setdefault(ex, [now, 0, False])
        if now - t0[0] < self.EXF_FUT_WAIT_S:
            if now - t0[1] >= 900:
                t0[1] = now
                log.info("%s 대사 대기: 선물 정산 파일(%s)이 잔고 시각(%d)을 아직 못 덮음 — 수집 뒤 다시(%.0f분째 · 상한 %d분)", ex, fts9, int(bts),
                         (now - t0[0]) / 60, self.EXF_FUT_WAIT_S // 60)
                self._exf_fut_wait_save()
            elif new9:
                self._exf_fut_wait_save()
            return True
        if not t0[2]:
            log.warning("★%s 선물 정산 파일이 %d분 넘게 잔고를 못 덮음 — 종전 규칙으로 대사(파일 뒤 정산은 지난날로 소급될 수 있음 · 이중 계상 없음)★",
                        ex, self.EXF_FUT_WAIT_S // 60)
            t0[1], t0[2] = now, True
            fb9 = self.__dict__.setdefault("_exf_fut_fb", [])
            fb9.append({"ex": ex, "at": int(now), "since": int(t0[0])})
            del fb9[:-10]
            self._exf_fut_wait_save()
        elif now - t0[1] >= 900:
            t0[1] = now
            self._exf_fut_wait_save()
        return False

    EXF_FUT_WAIT_PATH = os.path.join(common.STATE_DIR, "exf_fut_wait.json")

    def _exf_fut_wait_boot(self) -> bool:
        if self.__dict__.get("_exf_fut_wait_init"):
            return False
        self._exf_fut_wait_init = True
        w9 = self.__dict__.setdefault("_exf_fut_wait", {})
        try:
            old9 = common.read_json(self.EXF_FUT_WAIT_PATH, {}) or {}
            for e9, it9 in ((old9.get("wait") if isinstance(old9.get("wait"), dict) else {}) or {}).items():
                if e9 in self.EXF_FUT_EX and isinstance(it9, dict) and isinstance(it9.get("since"), int) and not isinstance(it9.get("since"), bool):
                    w9.setdefault(e9, [int(it9["since"]), 0, bool(it9.get("fallback"))])
        except (Exception, SystemExit) as e9:
            log.warning("선물 대사 대기 표식 읽기 실패(처음부터): %s", e9)
        return True

    def _exf_fut_wait_end(self, ex: str) -> None:
        self._exf_fut_wait_boot()
        if self.__dict__.get("_exf_fut_wait", {}).pop(ex, None) is not None:
            self._exf_fut_wait_save()

    def _exf_fut_wait_save(self) -> None:
        try:
            self._exf_fut_wait_boot()
            w9 = self.__dict__.get("_exf_fut_wait") or {}
            fb9 = list(self.__dict__.get("_exf_fut_fb") or [])
            old9 = None
            if not fb9 or self.__dict__.get("_exf_fut_place_wait") is None:
                old9 = common.read_json(self.EXF_FUT_WAIT_PATH, {}) or {}
            if not fb9:
                fb9 = [x for x in (old9.get("fb") or []) if isinstance(x, dict)][-10:]
                self._exf_fut_fb = fb9
            pw9 = self.__dict__.get("_exf_fut_place_wait")
            if pw9 is None:
                pl9 = (old9 or {}).get("place") if isinstance((old9 or {}).get("place"), dict) else {}
            else:
                ps9 = self.__dict__.get("_exf_fut_place_since") or {}
                pl9 = {e9: {"why": why9, "since": int(ps9.get(e9) or time.time())} for e9, why9 in pw9.items()}
            common.atomic_write_json(self.EXF_FUT_WAIT_PATH, {"v": 1, "ts": int(time.time()), "fb": fb9, "place": pl9,
                                                             "wait": {e9: {"since": int(t9[0]), "fallback": bool(t9[2])} for e9, t9 in w9.items()}})
        except (Exception, SystemExit) as e9:
            log.warning("선물 대사 대기 표식 쓰기 실패: %s", e9)

    @classmethod
    def _exf_fut_legs(cls, lst, scale: Decimal) -> list:
        g9 = {}
        for t9, a9 in lst:
            e9 = g9.setdefault(int(t9) // cls.EXF_FUT_GROUP_S, [0, Decimal(0)])
            e9[0] = max(e9[0], int(t9))
            e9[1] += a9
        out9 = []
        for k9 in sorted(g9):
            qb9 = int((g9[k9][1] * scale).to_integral_value(rounding=ROUND_HALF_EVEN))
            if qb9:
                out9.append((g9[k9][0], qb9))
        return out9

    def _exf_fut_post(self, ex: str, sym: str, bts: int, lst, aid: int, dec: int) -> Decimal:
        scale9 = Decimal(10) ** int(dec)
        loc9 = f"exchange:{ex}"
        today9 = acct_norm.iso_day(time.time())
        got9 = 0
        for seq9, (ts9, qb9) in enumerate(self._exf_fut_legs(lst, scale9)):
            cur9 = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening',"
                " 'EXF_ADJUST', ?)",
                (f"{ex}:{common.EXF_FUT_NS}", f"exfrecon:{sym}:{int(bts)}", seq9, int(ts9), int(aid), loc9, str(qb9), CLASSIFIER_VER))
            if cur9.rowcount:
                self._bump_position(int(aid), qb9, loc9)
                got9 += qb9
                if acct_norm.iso_day(ts9) < today9:
                    self._exf_hist_touch(ts9)
        return Decimal(got9) / scale9

    def _exf_take(self, ex: str, sym: str, cands: list, amount: Decimal, removing_positive: bool, why: str = "") -> Decimal:
        rem = abs(amount)
        loc = f"exchange:{ex}"
        for r in cands:
            if rem <= self.EXF_TOL:
                break
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            scale = Decimal(10) ** dec
            qn = abs(Decimal(int(r["qty_base"]))) / scale
            take = min(rem, qn)
            if removing_positive and not self._exf_now_sym(ex, sym):
                take = min(take, self._exf_room(self._exf_series(ex, sym), int(r["event_ts"])))
            tb = int(take * scale)
            if tb <= 0:
                continue
            self._exf_shrink(r, tb, loc, why)
            rem -= Decimal(tb) / scale
        return rem

    def _exf_reverse(self, ex: str, sym: str, diff: Decimal, bts: int):
        sign = 1 if diff > 0 else -1
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 >= bts or q9 == 0 or (q9 > 0) == (sign > 0):
                continue
            if common.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id")):
                continue
            if int(r["event_ts"]) < b9 - 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (-int(r["event_ts"]), -int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=(sign < 0), why=f"되돌림(대사 {bts} 차이 {format(diff, 'f')})")
        changed = sum(1 for r in cands if r.get("_t"))
        took = abs(diff) - rem
        if took > 0:
            log.info("%s %s 지난 보정 되돌림 %s (반대 부호 %d건 대상) — 남은 차이 %s", ex, sym, format(took, "f"), len(cands),
                     format(sign * rem, "f"))
        return sign * rem, (changed if took > 0 else 0)

    def _exf_ext_open_anchor(self, ex: str, r, st_ex) -> bool:
        if self.recon_months <= 0 or int(r["leg_seq"] or 0) != 0 or int(r["qty_base"]) <= 0:
            return False
        ext = st_ex.get("ext") if isinstance(st_ex, dict) else None
        if not isinstance(ext, dict) or not ext.get("target"):
            return False
        b9 = self._exf_bts(r["source_id"])
        if b9 is None:
            return False
        et9 = int(r["event_ts"])
        old_ws = int(b9 - self.recon_months * 30 * 86400)
        return abs(et9 - old_ws) <= 60 and int(ext["target"]) < et9 - 60

    def _exf_ext_open_shrink(self, ex: str, sym: str, diff: Decimal, bts: int, st_ex=None):
        if diff >= 0:
            return diff, 0
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or b9 >= bts or not self._exf_ext_open_anchor(ex, r, st_ex):
                continue
            if int(r["event_ts"]) <= self._win_t0(b9, ex) + 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (-int(r["event_ts"]), -int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=True, why=f"확장 이중 계상 정리(대사 {bts} 차이 {format(diff, 'f')})")
        took = abs(diff) - rem
        if took > 0:
            log.info("%s %s 옛 창 시작 보정 %s 줄임(과거 창 확장 이중 계상) — 남은 차이 %s", ex, sym, format(took, "f"), format(-rem, "f"))
        return -rem, (sum(1 for r in cands if r.get("_t")) if took > 0 else 0)

    @staticmethod
    def _exf_ext_done(ext) -> bool:
        if not isinstance(ext, dict) or not ext.get("target"):
            return False
        sig9 = ext.get("_psig")
        tgt = int(ext["target"])
        return (isinstance(sig9, list) and len(sig9) >= 5 and sig9[0] == "done" and sig9[1] == ext.get("wd_from")
                and sig9[2] == ext.get("fills_from") and int(sig9[4] or 0) == tgt and int(ext.get("wd_from") or 1 << 62) <= tgt + 60)

    @staticmethod
    def _exf_settle_key(ext) -> str:
        try:
            return f"{int(ext['target'])}:{int(float(ext.get('_pat') or 0))}"
        except (TypeError, ValueError, KeyError):
            return ""

    def _exf_ext_settling(self, ex: str, st_ex, done_ts=None):
        ext = (st_ex or {}).get("ext") if isinstance(st_ex, dict) else None
        if self.recon_months <= 0 or not isinstance(ext, dict) or not ext.get("target"):
            return None
        try:
            tgt9 = int(ext["target"])
        except (TypeError, ValueError):
            return None
        now9 = int(time.time())
        if tgt9 >= now9 - int(self.recon_months * 30 * 86400) or abs(self._win_t0(now9, ex) - tgt9) > 86400:
            return None
        if self._meta_get(f"exf_ext_settled:{ex}") == self._exf_settle_key(ext):
            return None
        if done_ts and self._exf_ext_done(ext):
            try:
                after9 = int(float(done_ts)) >= int(float(ext.get("_pat") or 1 << 62))
            except (TypeError, ValueError):
                after9 = False
            if after9:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_ext_settled:{ex}", self._exf_settle_key(ext)))
                self.conn.commit()
                return None
        return ext

    def _exf_surplus_start(self, ex: str, sym: str, amt: Decimal, lo: int, hi: int, exclude=()) -> int:
        agg = {}
        ex9 = set(exclude or ())
        for r in self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            if int(r["posting_id"]) in ex9 or int(r["event_ts"]) >= hi:
                continue
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            agg[int(r["event_ts"])] = agg.get(int(r["event_ts"]), Decimal(0)) + Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        tot9 = sum(agg.values(), Decimal(0))
        if tot9 <= self.EXF_TOL:
            return int(hi)
        need = min(amt, tot9) - self.EXF_TOL
        cum, t9 = Decimal(0), None
        pre = sorted((t, q) for t, q in agg.items() if t < lo)
        for _t, q in pre:
            cum += q
        t9 = lo if cum >= need else None
        for t, q in sorted((t, q) for t, q in agg.items() if t >= lo):
            cum += q
            if cum < need:
                t9 = None
            elif t9 is None:
                t9 = t
        return int(min(max(t9 if t9 is not None else hi, lo), hi))

    @classmethod
    def settle_planner(cls, cfg: dict, conn):
        c = object.__new__(cls)
        c.cfg = cfg
        c.conn = conn
        c.recon_months = 0.0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
        return c

    def _exf_ext_settle_plan(self, ex: str, bts_set) -> list:
        want9 = {int(b) for b in bts_set}
        if len(want9) > 1:
            raise ValueError(f"{ex}: 대사 시각은 거래소당 하나만(받음 {sorted(want9)})")
        rows = [dict(r) for r in self.conn.execute(
            "SELECT p.posting_id, p.source_id, p.event_ts, p.qty_base, p.leg_seq, a.symbol, a.decimals FROM postings p"
            " JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=?",
            (f"{ex}:recon", f"exchange:{ex}")).fetchall()]
        out = []
        for r in sorted(rows, key=lambda r: (str(r["symbol"]), int(r["event_ts"]))):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 not in want9 or q9 == 0 or int(r["leg_seq"] or 0) != 0 or abs(int(r["event_ts"]) - b9) > 60:
                continue
            dec9 = 8 if r["decimals"] is None else int(r["decimals"])
            amt9 = Decimal(q9) / (Decimal(10) ** dec9)
            if q9 > 0:
                t9 = self._exf_open_ts(ex, b9)
            else:
                t9 = self._exf_surplus_start(ex, str(r["symbol"] or "").upper(), -amt9, self._win_t0(b9, ex), b9,
                                             exclude=(int(r["posting_id"]),))
            if t9 < b9 - 60:
                out.append({"pid": int(r["posting_id"]), "sym": str(r["symbol"] or ""), "qty": str(amt9), "bts": b9,
                            "old": int(r["event_ts"]), "new": int(t9)})
        return out

    def _exf_ext_settle_repair(self, ex: str, bts_set) -> int:
        moved = 0
        t_min9 = None
        for m9 in self._exf_ext_settle_plan(ex, bts_set):
            self.conn.execute("UPDATE postings SET event_ts=? WHERE posting_id=? AND event_ts=?", (m9["new"], m9["pid"], m9["old"]))
            moved += 1
            t_min9 = m9["new"] if t_min9 is None else min(t_min9, m9["new"])
        if moved:
            self.conn.commit()
            self._exf_hist_touch(t_min9)
            log.warning("★%s 확장 직후 대사 보정 %d건 → 음수 = 잔고가 남던 구간 시작 · 양수 = 창 시작(시각만 — 지난날 유령·누락 보유 제거)★", ex, moved)
        return moved

    def _exf_ext_redate(self, ex: str, bts: int, st_ex) -> int:
        ext = (st_ex or {}).get("ext") if isinstance(st_ex, dict) else None
        if not isinstance(ext, dict) or not ext.get("target"):
            return 0
        tgt = int(ext["target"])
        sig9 = ext.get("_psig")
        if (not isinstance(sig9, list) or len(sig9) < 5 or sig9[0] != "done"
                or sig9[1] != ext.get("wd_from") or sig9[2] != ext.get("fills_from") or int(sig9[4] or 0) != tgt):
            return 0
        if int(ext.get("wd_from") or 1 << 62) > tgt + 60:
            return 0
        moved = 0
        for r in self.conn.execute(
                "SELECT posting_id, source_id, event_ts, qty_base, leg_seq FROM postings WHERE source_ns=? AND event='EXF_ADJUST'"
                " AND location=?", (f"{ex}:recon", f"exchange:{ex}")).fetchall():
            b9 = self._exf_bts(r["source_id"])
            if b9 is None or not self._exf_ext_open_anchor(ex, r, st_ex):
                continue
            et9 = int(r["event_ts"])
            w9 = self._win_t0(b9, ex)
            if et9 <= w9 + 60:
                continue
            self.conn.execute("UPDATE postings SET event_ts=? WHERE posting_id=?", (int(w9), r["posting_id"]))
            moved += 1
            self._exf_hist_touch(w9)
        if moved:
            self.conn.commit()
            log.info("%s 옛 창 시작 보정 %d건 → 넓힌 창 시작(과거 창 확장 완료 — 옛 흐름보다 앞에)", ex, moved)
        return moved

    def _exf_absorb(self, ex: str, f: dict) -> int:
        last = self._meta_get(f"recon_done_exf_{ex}")
        try:
            ts9 = int(int(f.get("ts") or 0) / 1000)
            qty = Decimal(str(f.get("qty") or "0"))
            gross = qty * Decimal(str(f.get("price") or "0"))
        except (ArithmeticError, TypeError, ValueError):
            return 0
        if not last or ts9 <= 0 or ts9 > int(float(last)):
            return 0
        sgn = 1 if str(f.get("side")) == "buy" else -1
        n = 0
        for sym, amt in ((str(f.get("base") or "").upper(), sgn * qty), (str(f.get("quote") or "").upper(), -sgn * gross)):
            if not sym or amt == 0:
                continue
            cands = []
            for r in self._exf_adj_rows(ex, sym):
                b9 = self._exf_bts(r["source_id"])
                q9 = int(r["qty_base"])
                if b9 is None or b9 < ts9 or q9 == 0 or (q9 > 0) != (amt > 0):
                    continue
                cands.append(r)
            cands.sort(key=lambda r: (self._exf_bts(r["source_id"]), int(r["posting_id"])))
            rem = self._exf_take(ex, sym, cands, amt, removing_positive=(amt > 0), why=f"전환 흡수 {f.get('id')}")
            if abs(amt) - rem > 0:
                n += 1
                log.info("%s 전환 %s: %s %s 중 %s 를 지난 대사 보정에서 되돌림(이중 계상 방지)", ex, f.get("id"), sym,
                         format(amt, "f"), format(abs(amt) - rem, "f"))
        return n

    LATE_BATCH_WAIT = 3600

    def _late_stage(self, ex: str, deltas: dict, rec: dict) -> None:
        lb = rec.get("lb")
        try:
            lbi, lbn = int(rec.get("lbi") or 0), max(1, int(rec.get("lbn") or 1))
        except (TypeError, ValueError):
            lb, lbi, lbn = None, 0, 1
        if not lb:
            if not deltas:
                return
            import uuid as _uuid
            lb, lbi, lbn = f"r:{_uuid.uuid4().hex}", 0, 1
        now9 = int(time.time())
        lc = str(rec.get("lc")) if rec.get("lc") else None
        self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,?,?,NULL,NULL,NULL,?,?)",
                          (ex, str(lb), lbi, lbn, now9, lc))
        for sym, lst in (deltas or {}).items():
            for ts9, amt in lst:
                self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,?,?,?,?,?,?,?)",
                                  (ex, str(lb), lbi, lbn, sym, int(ts9), str(amt), now9, lc))

    def _late_cycle_done(self, rec: dict) -> None:
        ex, lc = str(rec.get("exchange") or ""), str(rec.get("lc") or "")
        if ex and lc:
            self.conn.execute("INSERT INTO exf_late_pending (ex, lb, lbi, lbn, sym, ts, amt, at, lc) VALUES (?,?,0,1,NULL,NULL,NULL,?,?)",
                              (ex, "@done:" + lc, int(time.time()), lc))

    def _exf_late_pending(self, ex: str) -> bool:
        try:
            return self.conn.execute("SELECT 1 FROM exf_late_pending WHERE ex=? LIMIT 1", (ex,)).fetchone() is not None
        except sqlite3.OperationalError:
            return False

    def _exf_late_flush(self) -> int:
        rows = self.conn.execute("SELECT ex, lb, lbi, lbn, sym, ts, amt, at, lc FROM exf_late_pending").fetchall()
        if not rows:
            return 0
        now9 = int(time.time())
        info = {}
        done_lc = {(r["ex"], r["lc"]) for r in rows if str(r["lb"]).startswith("@done:")}
        for r in rows:
            b = info.setdefault((r["ex"], r["lb"]), {"n": int(r["lbn"] or 1), "seen": set(), "at": int(r["at"] or now9), "lc": r["lc"]})
            b["seen"].add(int(r["lbi"] or 0))
            b["at"] = min(b["at"], int(r["at"] or now9))
            if r["lc"] and not b["lc"]:
                b["lc"] = r["lc"]
        for k, b in info.items():
            if b["lc"] and not str(k[1]).startswith("@done:") and (k[0], b["lc"]) not in done_lc:
                b["n"] = len(b["seen"]) + 1
        ready = set()
        for ex9 in {k[0] for k in info}:
            mine = {k: b for k, b in info.items() if k[0] == ex9}
            inc = [b for b in mine.values() if len(b["seen"]) < b["n"]]
            if not inc or all(now9 - b["at"] > self.LATE_BATCH_WAIT for b in inc):
                ready |= set(mine)
        if not ready:
            return 0
        per_ex = {}
        for r in rows:
            if (r["ex"], r["lb"]) not in ready or r["sym"] is None:
                continue
            try:
                amt = Decimal(str(r["amt"]))
            except (ArithmeticError, TypeError, ValueError):
                continue
            per_ex.setdefault(r["ex"], {}).setdefault(str(r["sym"]), []).append((int(r["ts"]), amt))
        n = 0
        try:
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN")
            for ex, deltas in sorted(per_ex.items()):
                n += self._exf_absorb_deltas(ex, deltas, "늦은 체결·입출금")
            for ex, lb in sorted(ready):
                self.conn.execute("DELETE FROM exf_late_pending WHERE ex=? AND lb=?", (ex, lb))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self._exf_hist_flush()
        return n

    def _late_fill_deltas(self, fills: list) -> dict:
        deltas = {}
        for f in fills or ():
            try:
                ts9 = int(int(f.get("ts") or 0) / 1000)
                qty = Decimal(str(f.get("qty") or "0"))
                gross = qty * Decimal(str(f.get("price") or "0"))
                fee9 = Decimal(str(f.get("fee") or "0"))
            except (ArithmeticError, TypeError, ValueError):
                continue
            if ts9 <= 0 or qty <= 0:
                continue
            sgn = 1 if str(f.get("side")) == "buy" else -1
            for sym, amt in ((str(f.get("base") or "").upper(), sgn * qty), (str(f.get("quote") or "").upper(), -sgn * gross),
                             (str(f.get("fee_ccy") or "").upper(), -fee9)):
                if sym and amt != 0:
                    deltas.setdefault(sym, []).append((ts9, amt))
        return deltas

    def _exf_absorb_late(self, ex: str, fills: list) -> int:
        return self._exf_absorb_deltas(ex, self._late_fill_deltas(fills), "늦은 체결")

    def _exf_absorb_deltas(self, ex: str, deltas: dict, what: str) -> int:
        last = self._meta_get(f"recon_done_exf_{ex}")
        if not last or not deltas:
            return 0
        try:
            last9 = int(float(last))
        except (TypeError, ValueError):
            return 0
        n = 0
        for sym, lst in sorted(deltas.items()):
            rows = [r for r in self._exf_adj_rows(ex, sym)
                    if not common.exf_is_debt_int("EXF_ADJUST", r.get("leg_seq"), f"{ex}:recon", r.get("source_id"))]
            bts_all = self._exf_bounds_q(self.conn, ex, sym)
            per, grp = {}, {}
            for ts9, amt in lst:
                if ts9 > last9:
                    continue
                k9 = self._exf_bucket(bts_all, ts9)
                per[k9] = per.get(k9, Decimal(0)) + amt
                grp.setdefault(k9, []).append((int(ts9), amt))
            for b9 in sorted(per, key=lambda b: (per[b] > 0, b)):
                amt = per[b9]
                if abs(amt) <= self.EXF_TOL:
                    continue
                cands = [r for r in rows if self._exf_bts(r["source_id"]) == b9 and int(r["qty_base"]) != 0
                         and (int(r["qty_base"]) > 0) == (amt > 0)]
                cands.sort(key=lambda r: (self._exf_bts(r["source_id"]), int(r["posting_id"])))
                rem = self._exf_take(ex, sym, cands, amt, removing_positive=(amt > 0), why=f"{what} 흡수(대사 {b9} 구간)")
                if abs(amt) - rem > 0:
                    n += 1
                    log.info("%s %s %s: 대사 %d 구간 순액 %s 중 %s 를 지난 대사 보정에서 되돌림(이중 계상 방지)", ex, what, sym, b9,
                             format(amt, "f"), format(abs(amt) - rem, "f"))
                if rem > self.EXF_TOL:
                    rem_s = rem if amt > 0 else -rem
                    left9 = self._exf_late_offset(ex, sym, grp.get(b9) or [], amt, rem_s, b9, what)
                    if abs(rem_s - left9) > self.EXF_TOL:
                        n += 1
                    if abs(left9) > self.EXF_TOL:
                        log.info("%s %s %s: 대사 %s 구간 %s 는 되돌릴 보정·상쇄 조건이 없어 다음 대사로(차이 보정)", ex, what, sym,
                                 b9 or "없음(그 뒤 보정 대사 없음)", format(left9, "f"))
        return n

    EXF_LATE_PFX = common.EXF_LATE_PFX
    EXF_LATE_GAP_S = 6 * 3600
    EXF_LATE_DT = 1

    @classmethod
    def _exf_late_sid(cls, sym: str, t_off: int, b9) -> str:
        return f"{cls.EXF_LATE_PFX}{str(sym).upper()}:{int(t_off)}:b{int(b9 or 0)}"

    @classmethod
    def _exf_bounds_q(cls, conn, ex: str, sym: str) -> list:
        out = set()
        for r in conn.execute(
                "SELECT p.source_id, p.leg_seq FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.source_ns=? AND p.event='EXF_ADJUST' AND p.location=? AND upper(a.symbol)=?",
                (f"{ex}:recon", f"exchange:{ex}", str(sym).upper())).fetchall():
            if common.exf_is_debt_int("EXF_ADJUST", r[1], f"{ex}:recon", r[0]):
                continue
            b9 = cls._exf_bts(r[0])
            if b9 is not None:
                out.add(b9)
        try:
            out |= {int(t[0]) for t in conn.execute("SELECT bts FROM exf_adj_tomb WHERE ex=? AND sym=?", (ex, str(sym).upper()))}
        except sqlite3.OperationalError:
            pass
        return sorted(out)

    @staticmethod
    def _exf_bucket(bounds: list, ts) -> int:
        i9 = bisect.bisect_left(bounds, int(ts))
        return int(bounds[i9]) if i9 < len(bounds) else 0

    @classmethod
    def _exf_late_b(cls, source_id):
        s9 = str(source_id or "")
        if not s9.startswith(cls.EXF_LATE_PFX):
            return None
        try:
            return int(s9.rsplit(":", 1)[1].lstrip("b"))
        except (IndexError, ValueError):
            return None

    @classmethod
    def _exf_late_clusters(cls, lst) -> list:
        out = []
        for ts9, amt in sorted(((int(t), Decimal(a)) for t, a in lst), key=lambda x: x[0]):
            if out and ts9 - out[-1][1] <= cls.EXF_LATE_GAP_S:
                out[-1][1] = ts9
                out[-1][2] += amt
            else:
                out.append([ts9, ts9, amt])
        return [tuple(c9) for c9 in out]

    def _exf_main_inst(self, ex: str, sym: str):
        tot = {}
        for r in self.conn.execute(
                "SELECT p.asset_id, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym.upper())).fetchall():
            dec = 8 if r["decimals"] is None else int(r["decimals"])
            e9 = tot.setdefault(int(r["asset_id"]), [Decimal(0), dec])
            e9[0] += Decimal(int(r["qty_base"])) / (Decimal(10) ** dec)
        if tot:
            aid = max(tot, key=lambda a: (abs(tot[a][0]), -a))
            return aid, tot[aid][1]
        return self._exf_asset(ex, sym), 8

    def _exf_new_neg(self, series: list, t0: int, t1: int) -> bool:
        cum, floor = Decimal(0), Decimal(0)
        for ts9, q9 in series:
            if ts9 >= t1:
                break
            cum += q9
            if ts9 < t0:
                floor = min(Decimal(0), cum)
            elif cum < floor - self.EXF_TOL:
                return True
        return False

    def _exf_late_offset(self, ex: str, sym: str, lst: list, amt: Decimal, rem_s: Decimal, b9, what: str) -> Decimal:
        sym = str(sym).upper()
        if sym in self.EXF_FIX_SKIP or abs(rem_s) <= self.EXF_TOL or not lst:
            return rem_s
        cl9 = self._exf_late_clusters(lst)
        if abs(abs(rem_s) - abs(amt)) <= self.EXF_TOL:
            targets = [(t0, t1, -net) for t0, t1, net in cl9 if abs(net) > self.EXF_TOL]
        else:
            targets = [(cl9[0][0], cl9[-1][1], -rem_s)]
        aid, dec = self._exf_main_inst(ex, sym)
        scale = Decimal(10) ** dec
        loc = f"exchange:{ex}"
        now9 = self._exf_now_sym(ex, sym)
        left = rem_s
        for t0, t1, q in targets:
            t_off = int(t1) + self.EXF_LATE_DT
            bnd9 = self._exf_bounds_q(self.conn, ex, sym)
            near = [r for r in self._exf_adj_rows(ex, sym) if self._exf_late_b(r["source_id"]) is not None and int(r["qty_base"]) != 0
                    and self._exf_bucket(bnd9, int(r["event_ts"]) - self.EXF_LATE_DT) == int(b9 or 0)
                    and (int(r["qty_base"]) > 0) != (q > 0) and int(t0) - self.EXF_LATE_GAP_S <= int(r["event_ts"]) <= t_off]
            if near:
                near.sort(key=lambda r: (-int(r["event_ts"]), -int(r["posting_id"])))
                sg9 = 1 if q > 0 else -1
                rq9 = self._exf_take(ex, sym, near, q, removing_positive=(q < 0), why=f"{what} 늦은 상쇄 되돌림(대사 {b9 or 0} 구간)")
                left += sg9 * (abs(q) - rq9)
                q = sg9 * rq9
            qb = int(q * scale)
            if qb == 0:
                continue
            series = self._exf_series(ex, sym)
            if not now9 and q < 0:
                room = self._exf_room(sorted(series + [(t_off, Decimal(0))]), t_off)
                if room + self.EXF_TOL < -q:
                    log.info("%s %s %s: 늦은 변화 %s 상쇄 보류 — 그 뒤 잔고 여유 %s 부족(새 음수) → 다음 대사로", ex, what, sym,
                             format(-q, "f"), format(room, "f"))
                    continue
            if not now9 and q > 0 and self._exf_new_neg(series, int(t0), t_off):
                log.info("%s %s %s: 늦은 변화 %s 상쇄 보류 — 늦은 변화가 결손(보유 기록 없이 나감)을 만듦 → 다음 대사의 정정이 결손 직전에",
                         ex, what, sym, format(-q, "f"))
                continue
            sid = self._exf_late_sid(sym, t_off, b9)
            row9 =self.conn.execute("SELECT MAX(leg_seq) FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                                     (f"{ex}:recon", sid)).fetchone()
            seq9 = 0 if row9 is None or row9[0] is None else int(row9[0]) + 1
            self.conn.execute(
                "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                " leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening', 'EXF_ADJUST', ?)",
                (f"{ex}:recon", sid, seq9, t_off, aid, loc, str(qb), CLASSIFIER_VER))
            self._bump_position(aid, qb, loc)
            self._exf_hist_touch(t_off)
            left += Decimal(qb) / scale
            log.info("%s %s %s: 대사 %s 구간 늦은 변화 %s 를 그 직후(%d)에 상쇄 %s — 되돌릴 보정이 없어(같은 돈 두 번 안 잡히게)", ex, what, sym,
                     b9 or "없음", format(-q, "f"), t_off, format(q, "f"))
        return left

    def _exf_hist_touch(self, ts):
        self._exf_hist_dirty = True
        try:
            t9 = int(ts)
        except (TypeError, ValueError):
            return
        cur9 = getattr(self, "_exf_hist_from", None)
        self._exf_hist_from = t9 if cur9 is None else min(cur9, t9)

    def _exf_hist_flush(self):
        if getattr(self, "_exf_hist_dirty", False):
            self._exf_hist_dirty = False
            try:
                os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
            except FileNotFoundError:
                pass
            t9 = getattr(self, "_exf_hist_from", None)
            self._exf_hist_from = None
            if t9 is not None:
                try:
                    log.info("장기 곡선 다시 계산 표식: %s 부터", common.mark_hist_dirty(t9))
                except Exception as e:
                    log.warning("장기 곡선 다시 계산 표식 실패: %s", e)

    def _exf_redate_once(self):
        if self._meta_get("exf_redate_m"):
            return
        moved, moves = 0, []
        firsts = {}
        for r in self.conn.execute("SELECT source_ns, source_id FROM postings WHERE event='EXF_ADJUST'").fetchall():
            b9 = self._exf_bts(r["source_id"])
            if b9 is not None:
                firsts[r["source_ns"]] = min(firsts.get(r["source_ns"], b9), b9)
        groups = {}
        for r in self.conn.execute(
                "SELECT p.posting_id, p.source_ns, p.source_id, p.event_ts, p.qty_base, p.location, a.symbol"
                " FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.event='EXF_ADJUST'").fetchall():
            b9 = self._exf_bts(r["source_id"])
            ns = r["source_ns"]
            if b9 is None or not ns.endswith(":recon") or int(r["qty_base"]) <= 0:
                continue
            if b9 <= firsts.get(ns, b9) + self.EXF_INIT_PHASE or int(r["event_ts"]) >= b9 - 60:
                continue
            groups.setdefault((ns.split(":", 1)[0], (r["symbol"] or "").upper()), []).append(dict(r, bts=b9))
        for (ex, sym), cands in sorted(groups.items()):
            if not sym:
                continue
            dec_rows = self.conn.execute(
                "SELECT p.posting_id, p.event_ts, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                " WHERE p.location=? AND upper(a.symbol)=?", (f"exchange:{ex}", sym)).fetchall()
            ev = {int(x["posting_id"]): [int(x["event_ts"]), Decimal(int(x["qty_base"])) / (Decimal(10) ** (8 if x["decimals"] is None else int(x["decimals"])))]
                  for x in dec_rows}
            for c in sorted(cands, key=lambda c: (-c["bts"], -c["posting_id"])):
                pid = int(c["posting_id"])
                if pid not in ev:
                    continue
                t_old, q = ev[pid]
                agg = {}
                for p9, (t9, v9) in ev.items():
                    agg[t9] = agg.get(t9, Decimal(0)) + v9
                cum, floor, t_new = Decimal(0), Decimal(0), c["bts"]
                for t9, v9 in sorted(agg.items()):
                    cum += v9
                    if t9 < t_old:
                        floor = min(Decimal(0), cum)
                    elif t9 < c["bts"] and cum >= floor - self.EXF_TOL and cum - q < floor - self.EXF_TOL:
                        t_new = t9 - 1
                        break
                if t_new <= t_old:
                    continue
                self.conn.execute("UPDATE postings SET event_ts=? WHERE posting_id=?", (int(t_new), pid))
                ev[pid][0] = int(t_new)
                moves.append([pid, int(t_old), int(t_new)])
                moved += 1
        if moves:
            try:
                common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_redate_m.json"),
                                         {"ts": int(time.time()), "moves": moves})
            except Exception as e:
                self.conn.rollback()
                log.error("해외 대사 보정 재배치 보류 — 되돌리기 자료 쓰기 실패: %s", e)
                return
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_redate_m', ?)", (f"{int(time.time())}:{moved}",))
        self.conn.commit()
        if moved:
            self._exf_hist_dirty = True
            log.warning("★해외 대사 지난 양수 보정 %d건 시각 재배치(창 시작 → 대사 시각·결손 직전) — 수량 무변, 지난 곡선 무효화★", moved)
            self._exf_hist_flush()

    def _exf_src_added(self, ex: str, bal: dict) -> set:
        cur = bal.get("sources")
        if not isinstance(cur, list):
            return set()
        prev = self._meta_get(f"recon_src_exf_{ex}")
        if prev is None:
            return set()
        try:
            return {str(x) for x in cur} - set(json.loads(prev))
        except (ValueError, TypeError):
            return set()

    def _exf_loan_absorb(self, ex: str, sym: str, diff: Decimal, bts: int, since: int):
        cands = []
        for r in self._exf_adj_rows(ex, sym):
            b9 = self._exf_bts(r["source_id"])
            q9 = int(r["qty_base"])
            if b9 is None or b9 >= bts or q9 <= 0:
                continue
            if int(r["event_ts"]) < b9 - 60 or int(r["event_ts"]) < int(since) - 60:
                continue
            cands.append(r)
        if not cands:
            return diff, 0
        cands.sort(key=lambda r: (int(r["event_ts"]), int(r["posting_id"])))
        rem = self._exf_take(ex, sym, cands, diff, removing_positive=True, why=f"대출 첫 편입 흡수(대사 {bts} 부채 차이 {format(diff, 'f')})")
        took = abs(diff) - rem
        n = sum(1 for r in cands if r.get("_t"))
        if took > 0:
            log.info("%s %s 대출 첫 편입 — 지난 양수 보정 %s 흡수(빌려 들어온 물량) · 남은 차이 %s", ex, sym, format(took, "f"), format(-rem, "f"))
        return -rem, (n if took > 0 else 0)

    def _exf_debt_redate_once(self):
        if self._meta_get("exf_debt_redate_t"):
            return
        try:
            seed = common.seed_json("debt_first_seen_t.json", {}, base_dir=common.BASE_DIR, strict=True)
        except (Exception, SystemExit):
            seed = {}
        if not isinstance(seed, dict) or not any(isinstance(v9, dict) and v9 for v9 in seed.values()):
            return
        moves = []
        for ex, syms in (seed.items() if isinstance(seed, dict) else ()):
            for sym, ent in (syms.items() if isinstance(syms, dict) else ()):
                try:
                    t_first = int(ent["ts"])
                    q_first = Decimal(str(ent["qty"]))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue
                if q_first <= 0:
                    continue
                def _qn(r9):
                    return Decimal(int(r9["qty_base"])) / (Decimal(10) ** (8 if r9["decimals"] is None else int(r9["decimals"])))
                rows = [r for r in self._exf_adj_rows(ex, sym)
                        if int(r["qty_base"]) < 0 and int(r["leg_seq"]) == 0 and (self._exf_bts(r["source_id"]) or 0) > t_first
                        and int(r["event_ts"]) >= (self._exf_bts(r["source_id"]) or 0) - 60
                        and q_first * Decimal("0.9") <= -_qn(r) <= q_first * Decimal("1.2")]
                rows.sort(key=lambda r: (int(r["event_ts"]), int(r["posting_id"])))
                if not rows:
                    log.warning("기존 부채 소급 건너뜀: %s %s 첫 관측 %s 와 맞는 부채 첫 반영 보정 없음", ex, sym, format(q_first, "f"))
                    continue
                r = rows[0]
                dec = 8 if r["decimals"] is None else int(r["decimals"])
                scale = Decimal(10) ** dec
                q_old = _qn(r)
                q_move = min(q_first, -q_old)
                t_old = int(r["event_ts"])
                if t_first >= t_old:
                    continue
                cum, floor, ok = Decimal(0), Decimal(0), True
                ser9 = self._exf_series(ex, sym)
                for t9, v9 in ser9:
                    if t9 < t_first:
                        cum += v9
                        floor = min(Decimal(0), cum)
                if cum - q_move < floor - self.EXF_TOL:
                    ok = False
                for t9, v9 in ser9:
                    if not ok or t9 >= t_old:
                        break
                    if t9 < t_first:
                        continue
                    cum += v9
                    if cum >= floor - self.EXF_TOL and cum - q_move < floor - self.EXF_TOL:
                        ok = False
                if not ok:
                    log.warning("기존 부채 소급 건너뜀: %s %s — 옮기면 그 사이 원장 잔고가 음수", ex, sym)
                    continue
                qb_move = int(q_move * scale)
                qb_rest = int(r["qty_base"]) + qb_move
                moves.append({"posting_id": int(r["posting_id"]), "ex": ex, "sym": sym, "old_ts": t_old, "old_qty_base": str(r["qty_base"]),
                              "new_ts": t_first, "new_qty_base": str(-qb_move), "source_id": r["source_id"], "asset_id": int(r["asset_id"]),
                              "rest_qty_base": str(qb_rest)})
        if moves:
            try:
                common.atomic_write_json(os.path.join(common.STATE_DIR, "exf_debt_redate_t.json"), {"ts": int(time.time()), "moves": moves})
            except Exception as e:
                log.error("기존 부채 소급 보류 — 되돌리기 자료 쓰기 실패: %s", e)
                return
            for m in moves:
                self.conn.execute("UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?",
                                  (m["new_ts"], m["new_qty_base"], m["posting_id"]))
                if int(m["rest_qty_base"]) != 0:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, 2, ?, ?, ?, ?, NULL, NULL, 'opening',"
                        " 'EXF_ADJUST', ?)",
                        (f"{m['ex']}:recon", m["source_id"], m["old_ts"], m["asset_id"], f"exchange:{m['ex']}", m["rest_qty_base"], CLASSIFIER_VER))
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_debt_redate_t', ?)", (f"{int(time.time())}:{len(moves)}",))
        self.conn.commit()
        if moves:
            log.warning("★기존 부채 첫 반영 %d건 첫 관측 시각으로 소급(나머지 = 이자 레그) — 수량 무변, 지난 곡선은 web 이 해당 날만 조정★", len(moves))

    def exf_recon_pass(self, drained=frozenset()):
        if "ex" not in drained or time.time() - getattr(self, "_last_exfrecon", 0) < 300:
            return
        self._last_exfrecon = time.time()
        self._exf_redate_once()
        self._exf_debt_redate_once()
        self._exf_fix_place_once()
        self._exf_fut_place_once(auto=True)
        st_all = common.read_json(os.path.join(common.STATE_DIR, "exf_state.json"), {})
        now = int(time.time())
        for ex, st in (st_all or {}).items():
            done_ts = self._meta_get(f"recon_done_exf_{ex}")
            fst = st.get("fills") or {}
            if not fst.get("backfilled_until"):
                continue
            if self._exf_late_pending(ex):
                continue
            bal = common.read_json(
                os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json"), {})
            bts = int(bal.get("ts") or 0)
            balances = bal.get("balances")
            if now - bts > common.exf_fresh_sec(self.cfg) or not isinstance(balances, dict):
                continue
            if done_ts and int(float(done_ts)) >= bts:
                continue
            if self._exf_fut_hold(ex, bal, bts, done_ts, now):
                continue
            if bts + 1 > getattr(self, "_drain_at", 0):
                if now - getattr(self, "_exf_skip_log", 0) > 900:
                    self._exf_skip_log = now
                    log.info("해외대사 대기: %s 잔고ts=%d drain_at=%d (잔고가 드레인 이후)",
                             ex, bts, int(getattr(self, "_drain_at", 0)))
                continue
            actual = {str(k).upper(): float(v) for k, v in balances.items()
                      if str(k).upper() not in ("KRW", "USD")}
            debts9 = bal.get("debts") if isinstance(bal.get("debts"), dict) else {}
            for k9, v9 in debts9.items():
                ku9 = str(k9).upper()
                try:
                    fv9 = float(v9)
                except (TypeError, ValueError):
                    continue
                if ku9 not in ("KRW", "USD") and fv9 < 0:
                    actual[ku9] = actual.get(ku9, 0.0) + fv9
            first9 = not done_ts
            settle9 = self._exf_ext_settling(ex, st, done_ts)
            cov_new9 = self._exf_cov_new(ex, bal)
            debt_now9 = {str(k9).upper(): Decimal(str(-float(v9))) for k9, v9 in debts9.items()
                         if isinstance(v9, (int, float)) and v9 < 0 and str(k9).upper() not in ("KRW", "USD")}
            added9 = self._exf_src_added(ex, bal)
            loan_since9, loan_prin9 = {}, {}
            for ln9 in (bal.get("loans") if isinstance(bal.get("loans"), list) else ()):
                if not isinstance(ln9, dict) or str(ln9.get("src") or "loan") not in added9 or not ln9.get("since"):
                    continue
                for k9 in (ln9.get("debt") or {}):
                    try:
                        loan_since9[str(k9).upper()] = min(loan_since9.get(str(k9).upper(), int(ln9["since"])), int(ln9["since"]))
                        pr9 = (ln9.get("principal") or {}).get(k9)
                        if pr9 is not None:
                            loan_prin9[str(k9).upper()] = loan_prin9.get(str(k9).upper(), Decimal(0)) + Decimal(str(pr9))
                    except (TypeError, ValueError, ArithmeticError, AttributeError):
                        pass
            try:
                debt_base9 = {k9: Decimal(str(v9)) for k9, v9 in json.loads(self._meta_get(f"recon_debt_exf_{ex}") or "{}").items()}
            except (ValueError, TypeError, ArithmeticError):
                debt_base9 = {}
            debt_keep9 = set()
            ledger = {}
            for r in self.conn.execute(
                    "SELECT p.asset_id, p.qty_base, a.symbol, a.decimals FROM postings p"
                    " JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=?",
                    (f"exchange:{ex}",)).fetchall():
                sym = (r["symbol"] or "").upper()
                if not sym:
                    continue
                ledger.setdefault(sym, {}).setdefault(r["asset_id"], [0, r["decimals"]])
                ledger[sym][r["asset_id"]][0] += int(r["qty_base"])
            n_adj = n_defer = n_rev = n_fut = 0
            fut9 = {} if first9 else self._exf_fut_window(ex, bal, bts, done_ts)
            if ex in self.EXF_FUT_EX and self._meta_get(f"exf_fut_from_{ex}") is None:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"exf_fut_from_{ex}", str(int(float(done_ts)) if done_ts else int(bts))))
            for sym in set(ledger) | set(actual) | set(fut9):
                insts = ledger.get(sym) or {}
                total_norm = Decimal(0)
                main_aid, main_abs, main_dec = None, Decimal(-1), 8
                for aid, (s, dec) in insts.items():
                    dec = 8 if dec is None else int(dec)
                    nv = Decimal(s) / (Decimal(10) ** dec)
                    total_norm += nv
                    if abs(nv) > main_abs:
                        main_aid, main_abs, main_dec = aid, abs(nv), dec
                diff = Decimal(str(actual.get(sym, 0))) - total_norm
                if fut9.get(sym):
                    if main_aid is None:
                        main_aid, main_dec = self._exf_asset(ex, sym), 8
                    fq9 = self._exf_fut_post(ex, sym, bts, fut9[sym], main_aid, main_dec)
                    if fq9:
                        diff -= fq9
                        total_norm += fq9
                        n_fut += 1
                if abs(diff) <= Decimal("0.00000001"):
                    continue
                if not first9 and self._exf_micro(ex, sym, list(insts), diff, total_norm, actual.get(sym, 0)):
                    n_defer += 1
                    debt_keep9.add(sym)
                    continue
                if (not first9 and diff < 0 and sym in debt_now9 and sym in debt_base9 and sym not in loan_since9
                        and -diff <= max(Decimal(0), debt_now9[sym] - debt_base9[sym]) + self.EXF_TOL):
                    px9 = self._exf_unit_usd(ex, sym, list(insts))
                    if px9 is not None and px9 > 0 and -diff * px9 < self.EXF_DEBT_MICRO_USD:
                        n_defer += 1
                        debt_keep9.add(sym)
                        continue
                if main_aid is None:
                    main_aid, main_dec = self._exf_asset(ex, sym), 8
                now9 = self._exf_now_sym(ex, sym)
                if not first9 and diff > 0 and not now9:
                    diff, nr9 = self._exf_reverse(ex, sym, diff, bts)
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                if not first9 and diff < 0 and not now9:
                    diff, nr9 = self._exf_ext_open_shrink(ex, sym, diff, bts, st)
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                if not first9 and diff < 0 and sym in loan_since9:
                    cap9 = min(-diff, loan_prin9[sym]) if loan_prin9.get(sym, 0) > 0 else -diff
                    rest9, nr9 = self._exf_loan_absorb(ex, sym, -cap9, bts, loan_since9[sym])
                    diff = diff + cap9 + rest9
                    n_rev += nr9
                    if abs(diff) <= Decimal("0.00000001"):
                        continue
                loc9 = f"exchange:{ex}"
                legs9 = []
                if diff < 0 and sym in debt_now9 and not first9:
                    base9 = debt_base9.get(sym)
                    if base9 is None:
                        ip9 = -diff if -diff < debt_now9[sym] * Decimal("0.5") else Decimal(0)
                    else:
                        ip9 = min(-diff, max(Decimal(0), debt_now9[sym] - base9))
                    if ip9 > 0:
                        legs9.append((2, bts, -int(ip9 * (Decimal(10) ** main_dec))))
                    if -diff - ip9 > 0:
                        legs9.append((0, bts, int((diff + ip9) * (Decimal(10) ** main_dec))))
                elif diff > 0 and (first9 or cov_new9 or settle9 is not None):
                    legs9.append((0, self._exf_open_ts(ex, bts), int(diff * (Decimal(10) ** main_dec))))
                elif diff > 0 and now9:
                    legs9.append((0, bts, int(diff * (Decimal(10) ** main_dec))))
                elif diff > 0 and sym not in self.EXF_FIX_SKIP:
                    agg9, keys9 = self._exf_agg(ex, sym)
                    sc9 = Decimal(10) ** main_dec
                    tr9, rem9 = self._exf_tranches(agg9, keys9, int(diff * sc9), sc9, bts, self._exf_open_ts(ex, bts))
                    legs9.extend(self._exf_tranche_legs(tr9, rem9, bts))
                elif diff > 0:
                    t_neg9, deficit9 = self._exf_deficit(ex, sym)
                    part9 = min(diff, deficit9) if (t_neg9 is not None and deficit9 > 0) else Decimal(0)
                    if part9 > 0:
                        legs9.append((1, max(self._exf_open_ts(ex, bts), int(t_neg9) - 1),
                                      int(part9 * (Decimal(10) ** main_dec))))
                    if diff - part9 > 0:
                        legs9.append((0, bts, int((diff - part9) * (Decimal(10) ** main_dec))))
                elif settle9 is not None:
                    legs9.append((0, self._exf_surplus_start(ex, sym, -diff, self._win_t0(bts, ex), bts),
                                  int(diff * (Decimal(10) ** main_dec))))
                else:
                    legs9.append((0, bts, int(diff * (Decimal(10) ** main_dec))))
                hit9 = False
                for seq9, ev9, qb in legs9:
                    if qb == 0:
                        continue
                    cur9 = self.conn.execute(
                        "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                        " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind,"
                        " event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL,"
                        " NULL, 'opening', 'EXF_ADJUST', ?)",
                        (f"{ex}:recon", f"exfrecon:{sym}:{bts}", seq9, int(ev9), main_aid,
                         loc9, str(qb), CLASSIFIER_VER))
                    if cur9.rowcount:
                        self._bump_position(main_aid, qb, loc9)
                        hit9 = True
                        if ev9 < bts - 60:
                            self._exf_hist_touch(ev9)
                if hit9:
                    n_adj += 1
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                              (f"recon_done_exf_{ex}", str(bts)))
            if ex in self.EXF_FUT_EX:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"exf_fut_cur_{ex}", json.dumps({"t": int(bts)})))
            if settle9 is not None and self._exf_ext_done(settle9):
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"exf_ext_settled:{ex}", self._exf_settle_key(settle9)))
            nb9 = {}
            for k9, v9 in debt_now9.items():
                if k9 not in debt_keep9:
                    nb9[k9] = str(v9)
                elif k9 in debt_base9:
                    nb9[k9] = str(debt_base9[k9])
            if nb9 or debt_base9:
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"recon_debt_exf_{ex}", json.dumps(nb9, sort_keys=True)))
            if isinstance(bal.get("sources"), list):
                self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                  (f"recon_src_exf_{ex}", json.dumps(sorted(set(map(str, bal["sources"]))))))
            self.conn.commit()
            if n_fut:
                log.info("%s 선물 정산 %d개 통화 — 정산 시각에 기장(대사 차이에서 먼저 뗌)", ex, n_fut)
            if n_adj or n_rev:
                log.info("★%s 잔고 대사 완료: %d개 통화 보정 · 지난 보정 되돌림 %d건 · 소액 보류 %d★", ex, n_adj, n_rev, n_defer)
            elif n_defer:
                log.info("%s 잔고 대사: 소액 차이 %d개 통화 보류(누적 뒤 일괄)", ex, n_defer)
            if n_rev:
                self._exf_hist_dirty = True
            try:
                if not first9 and self._exf_ext_redate(ex, bts, st_all.get(ex) if isinstance(st_all, dict) else None):
                    self._exf_hist_dirty = True
            except Exception as e9:
                self.conn.rollback()
                log.warning("%s 옛 창 시작 보정 시각 이동 실패(다음 대사): %s", ex, e9)
            if n_adj > 0:
                dm("EXF_RECON", f"{ex} 잔고 대사 완료 — {n_adj}개 통화 보정")
        self._exf_hist_flush()

    def _post_exf_deposit_in(self, ex: str, uid: str, d: dict) -> bool:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            amt9 = Decimal(0)
        ccy9 = str(d.get("currency") or "").upper()
        if amt9 <= 0 or not ccy9:
            return False
        if ccy9 == "KRW":
            return False
        dts = self._iso_ts(d.get("done_at") or d.get("created_at"))
        if not dts:
            self._ex_skip_once("EX_DEPOSIT_SKIP", f"{ex}:{uid}", f"{ex} 입금 시각 없음 보류: {ccy9} {uid}")
            return False
        aid9 = self._exf_asset(ex, ccy9)
        qb9 = int(amt9 * (Decimal(10) ** 8))
        c9 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id,"
            " leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
            " cost_krw, leg_kind, event, classifier_ver) VALUES"
            " ('exchange', ?, ?, 0, ?, ?, ?, ?, NULL, NULL, 'move_in',"
            " 'EXF_DEPOSIT', ?)",
            (f"{ex}:deposit", uid, dts, aid9, f"exchange:{ex}",
             str(qb9), CLASSIFIER_VER))
        if c9.rowcount:
            self._bump_position(aid9, qb9, f"exchange:{ex}")
            return True
        return False

    EXF_WD_FEE_SEPARATE = frozenset(("binance", "bybit", "kucoin", "okx"))

    def _wd_fee_leg_on(self, ex: str, wts) -> bool:
        try:
            return ex in self.EXF_WD_FEE_SEPARATE and wts is not None and int(wts) >= self._wd_fee_since_of(ex)
        except (TypeError, ValueError):
            return False

    def _wd_fee_since_of(self, ex: str) -> int:
        r9 = self.conn.execute("SELECT v FROM meta WHERE k=?", (f"exf_wd_fee_since:{ex}",)).fetchone()
        if r9 is not None:
            try:
                return int(r9[0])
            except (TypeError, ValueError):
                pass
        return int(getattr(self, "wd_fee_since", 0) or 0)

    def _wd_fee_new_ex(self, ex: str) -> None:
        if ex not in self.EXF_WD_FEE_SEPARATE:
            return
        if self.conn.execute("SELECT 1 FROM meta WHERE k=?", (f"exf_wd_fee_since:{ex}",)).fetchone():
            return
        if self.conn.execute("SELECT 1 FROM raw_ex WHERE exchange=? LIMIT 1", (ex,)).fetchone():
            return
        self.conn.execute("INSERT OR IGNORE INTO meta (k, v) VALUES (?, '0')", (f"exf_wd_fee_since:{ex}",))
        log.info("%s 처음 연결 — 출금 수수료 레그 = 모든 출금(기준 시각 0 · X9)", ex)

    def _post_exf_withdraw(self, ex: str, uid: str, d: dict) -> bool:
        try:
            amt9 = Decimal(str(d.get("amount") or "0"))
        except ArithmeticError:
            amt9 = Decimal(0)
        ccy9 = str(d.get("currency") or "").upper()
        if amt9 <= 0 or not ccy9:
            return False
        if ccy9 == "KRW":
            return False
        wts = self._iso_ts(d.get("created_at") or d.get("done_at"))
        if not wts:
            self._ex_skip_once("EX_WITHDRAW_SKIP", f"{ex}:{uid}", f"{ex} 출금 시각 없음 보류: {ccy9} {uid}")
            return False
        aid9 = self._exf_asset(ex, ccy9)
        qb9 = int(amt9 * (Decimal(10) ** 8))
        c9 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id,"
            " leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
            " cost_krw, leg_kind, event, classifier_ver) VALUES"
            " ('exchange', ?, ?, 0, ?, ?, ?, ?, NULL, NULL, 'move_out',"
            " 'EXF_WITHDRAW', ?)",
            (f"{ex}:withdraw", uid, wts, aid9, f"exchange:{ex}",
             str(-qb9), CLASSIFIER_VER))
        if c9.rowcount:
            self._bump_position(aid9, -qb9, f"exchange:{ex}")
            if self._wd_fee_leg_on(ex, wts):
                try:
                    fee9 = Decimal(str(d.get("fee") or "0"))
                except ArithmeticError:
                    fee9 = Decimal(0)
                fccy9 = str(d.get("fee_ccy") or ccy9).upper()
                if fee9.is_finite() and fee9 > 0 and fccy9 and fccy9 != "KRW":
                    faid9 = self._exf_asset(ex, fccy9)
                    fqb9 = int(fee9 * (Decimal(10) ** 8))
                    if fqb9 > 0:
                        cf9 = self.conn.execute(
                            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id,"
                            " leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                            " cost_krw, leg_kind, event, classifier_ver) VALUES"
                            " ('exchange', ?, ?, 1, ?, ?, ?, ?, NULL, NULL, 'gas',"
                            " 'EXF_WD_FEE', ?)",
                            (f"{ex}:withdraw", uid, wts, faid9, f"exchange:{ex}", str(-fqb9), CLASSIFIER_VER))
                        if cf9.rowcount:
                            self._bump_position(faid9, -fqb9, f"exchange:{ex}")
            return True
        return False

    def _post_exf_fill(self, ex: str, f: dict) -> bool:
        fid = str(f.get("id") or "")
        try:
            qty = Decimal(str(f.get("qty") or "0"))
            px9 = Decimal(str(f.get("price") or "0"))
            ts9 = int(int(f.get("ts") or 0) / 1000)
        except (ArithmeticError, TypeError, ValueError):
            return False
        base = str(f.get("base") or "").upper()
        quote = str(f.get("quote") or "").upper()
        side = str(f.get("side") or "")
        if not fid or qty <= 0 or not base or side not in ("buy", "sell") or ts9 <= 0:
            return False
        aid = self._exf_asset(ex, base)
        qb = int(qty * (Decimal(10) ** 8))
        qu = self._quote_usd(quote, ts9)
        gross = qty * px9
        cost_usd = repr(float(gross * qu)) if (qu is not None and gross > 0) else None
        if quote == "KRW" and gross > 0:
            cost_krw = repr(float(gross))
        elif cost_usd is not None:
            fx9 = self.px.fx_at(ts9 * 1000)
            cost_krw = repr(float(gross * qu) * fx9) if fx9 else None
        else:
            cost_krw = None
        leg, evn, sgn = (("acq", "EXF_BUY", 1) if side == "buy"
                         else ("disp", "EXF_SELL", -1))
        c2 = self.conn.execute(
            "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
            " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
            " classifier_ver) VALUES ('exchange', ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{ex}:trade", fid, ts9, aid, f"exchange:{ex}", str(sgn * qb),
             cost_usd, cost_krw, leg, evn, CLASSIFIER_VER))
        if not c2.rowcount:
            return False
        self._bump_position(aid, sgn * qb, f"exchange:{ex}")
        if quote and gross > 0:
            qaid = self._exf_asset(ex, quote)
            qqb = int(gross * (Decimal(10) ** 8))
            cq = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                " classifier_ver) VALUES ('exchange', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{ex}:trade", fid, ts9, qaid, f"exchange:{ex}", str(-sgn * qqb),
                 cost_usd, cost_krw,
                 "disp" if side == "buy" else "acq",
                 "EXF_SELL" if side == "buy" else "EXF_BUY", CLASSIFIER_VER))
            if cq.rowcount:
                self._bump_position(qaid, -sgn * qqb, f"exchange:{ex}")
        try:
            fee9 = Decimal(str(f.get("fee") or "0"))
        except ArithmeticError:
            fee9 = Decimal(0)
        fee_ccy = str(f.get("fee_ccy") or "").upper()
        if fee9 != 0 and fee_ccy:
            faid = self._exf_asset(ex, fee_ccy)
            fqb = int(fee9 * (Decimal(10) ** 8))
            cf = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                " classifier_ver) VALUES ('exchange', ?, ?, 2, ?, ?, ?, ?, NULL, NULL,"
                " 'gas', 'EXF_FEE', ?)",
                (f"{ex}:trade", fid, ts9, faid, f"exchange:{ex}", str(-fqb), CLASSIFIER_VER))
            if cf.rowcount:
                self._bump_position(faid, -fqb, f"exchange:{ex}")
        return True

    @staticmethod
    def _iso_ts(s):
        return common.iso_epoch(s)

    def _fill_group_asset(self, base_sym: str, ts: int):
        return self._upbit_asset(base_sym)

    def _consume_fills(self, rec: dict):
        n = 0
        for o in rec.get("orders") or []:
            if not isinstance(o, dict) or not o.get("uuid"):
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO raw_ex (exchange, kind, uuid, revision, payload,"
                " observed_at) VALUES ('upbit', 'order', ?, 1, ?, ?)",
                (o["uuid"], json.dumps(o, ensure_ascii=False), int(time.time())))
            market = str(o.get("market") or "")
            if not market.startswith("KRW-"):
                if self._post_upbit_quote_fill(o):
                    n += 1
                continue
            base = market[4:]
            try:
                vol = Decimal(str(o.get("executed_volume") or "0"))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if not vol.is_finite() or vol <= 0:
                continue
            side = str(o.get("side") or "").lower()
            if side not in ("bid", "ask"):
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"주문 side 미상 보류: {market} {o.get('uuid')} side={side!r}")
                continue
            ts = acct_norm.fill_ts(o) or self._iso_ts(o.get("created_at"))
            if not ts:
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"주문 시각 없음 보류: {market} {o.get('uuid')}")
                continue
            try:
                fee_krw = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
                funds = o.get("executed_funds")
                krw = (Decimal(str(funds)) if funds is not None
                       else Decimal(str(o.get("price") or "0")) * vol)
            except (InvalidOperation, ValueError, TypeError):
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결금액 파싱 실패 보류: {market} {o.get('uuid')}")
                continue
            if not (krw.is_finite() and fee_krw.is_finite()) or krw <= 0 or fee_krw < 0:
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결금액 미상 보류: {market} {o.get('uuid')}")
                continue
            fx = self.px.fx_at(ts * 1000)
            net_krw = (krw - fee_krw) if side == "ask" else (krw + fee_krw)
            usd = (float(net_krw) / fx) if fx else None
            aid = self._fill_group_asset(base, ts)
            ar = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()
            dec = ar["decimals"] if ar and ar["decimals"] is not None else 8
            qv = vol * (Decimal(10) ** int(dec))
            if qv != qv.to_integral_value():
                self._ex_skip_once("EX_FILL_SKIP", str(o["uuid"]), f"체결 수량 {dec}자리 초과 보류: {market} {o.get('uuid')} vol={vol}")
                continue
            qty_base = int(qv)
            if side == "ask":
                lk, ev2, qb = "disp", "EX_SELL", -qty_base
            else:
                lk, ev2, qb = "acq", "EX_BUY", qty_base
            c3 = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                " classifier_ver) VALUES ('exchange', 'upbit:order', ?, 0, ?, ?,"
                " 'exchange:upbit', ?, ?, ?, ?, ?, ?)",
                (o["uuid"], ts, aid, str(qb),
                 repr(usd) if usd is not None else None, str(net_krw), lk, ev2, CLASSIFIER_VER))
            if c3.rowcount:
                self._bump_position(aid, qb, "exchange:upbit")
                n += 1
        if n:
            log.info("[ex] 업비트 체결 %d건 원장 반영", n)

    def _consume_order_trades(self, rec: dict):
        n_ok = n_moved = n_skip = 0
        t_min = None
        why_n = {}

        def legs(u9):
            return self.conn.execute(
                "SELECT leg_seq, asset_id, location, qty_base, leg_kind, event, event_ts, cost_usd FROM postings"
                " WHERE source_kind='exchange' AND source_ns='upbit:order' AND source_id=?", (u9,)).fetchall()

        def shape(rows):
            return sorted((int(r["leg_seq"]), int(r["asset_id"]), str(r["location"]), str(int(r["qty_base"])), str(r["leg_kind"]), str(r["event"]))
                          for r in rows)
        for it in rec.get("orders") or []:
            u = str((it or {}).get("uuid") or "") if isinstance(it, dict) else ""
            row = self.conn.execute("SELECT revision, payload, observed_at FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid=?"
                                    " ORDER BY revision DESC LIMIT 1", (u,)).fetchone() if u else None
            try:
                old = json.loads(row["payload"]) if row else None
            except json.JSONDecodeError:
                old = None
            merged, why = acct_norm.trades_fill_merge(old, it) if isinstance(old, dict) else (None, "원본 없음")
            if merged is None:
                why_n[why] = why_n.get(why, 0) + 1
                n_skip += 1
                if why != "이미 체결 목록 있음":
                    log.warning("업비트 옛 주문 체결 목록 채우기 건너뜀 %s: %s", u[:12], why)
                continue
            merged["_tj_trades_fill"] = {"at": int(rec.get("ts") or time.time()), "src": str(rec.get("src") or "")[:60]}
            new_ts = acct_norm.fill_ts(merged)
            self.conn.execute("SAVEPOINT order_trades")
            undo = None
            self.conn.execute("INSERT INTO raw_ex (exchange, kind, uuid, revision, payload, observed_at) VALUES ('upbit', 'order', ?, ?, ?, ?)",
                              (u, int(row["revision"]) + 1, json.dumps(merged, ensure_ascii=False), int(row["observed_at"])))
            olds = legs(u)
            if olds and any(int(o["event_ts"]) != new_ts for o in olds):
                for o in olds:
                    self._bump_position(o["asset_id"], -int(o["qty_base"]), o["location"])
                self.conn.execute("DELETE FROM postings WHERE source_kind='exchange' AND source_ns='upbit:order' AND source_id=?", (u,))
                self._consume_fills({"orders": [merged]})
                news = legs(u)
                if shape(news) != shape(olds) or any(int(r9["event_ts"]) != new_ts for r9 in news):
                    undo = "다시 만든 레그가 다름"
                elif any(o["cost_usd"] is not None for o in olds) and any(r9["cost_usd"] is None for r9 in news):
                    undo = "새 시각 원가 USD 미확보(이번 적용 중 환율·쿼트 시세를 못 받음 — 조회 실패 또는 실패 뒤 60초 쉼 동안의 주문 · 다음 --apply 때 다시)"
                else:
                    n_moved += 1
                    t_min = min([t for t in [t_min, new_ts] + [int(o["event_ts"]) for o in olds] if t is not None])
            if undo:
                self.conn.execute("ROLLBACK TO order_trades")
                why_n[undo] = why_n.get(undo, 0) + 1
                n_skip += 1
                log.warning("업비트 옛 주문 %s 체결 시각 재기장 되돌림(원본 개정도 취소 — 다음 적용 때 재시도): %s", u[:12], undo)
            else:
                n_ok += 1
            self.conn.execute("RELEASE order_trades")
        if n_moved:
            self._drop_daily_cache()
            try:
                log.info("장기 곡선 다시 계산 표식: %s 부터", common.mark_hist_dirty(t_min))
            except Exception as e:
                log.warning("장기 곡선 다시 계산 표식 실패: %s", e)
        log.info("[ex] 업비트 옛 주문 체결 목록 채우기: 원본 개정 %d (시각 재기장 %d) · 건너뜀 %d %s", n_ok, n_moved, n_skip,
                 json.dumps(why_n, ensure_ascii=False) if why_n else "")
        return {"ok": n_ok, "moved": n_moved, "skip": n_skip, "why": why_n}

    @staticmethod
    def _upbit_open_partial(o: dict):
        market = str(o.get("market") or "")
        if "-" not in market:
            return None
        quote, base = (s.upper() for s in market.split("-", 1))
        try:
            vol = Decimal(str(o.get("executed_volume") or "0"))
            funds = Decimal(str(o.get("executed_funds") if o.get("executed_funds") not in (None, "") else "0"))
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
        except (InvalidOperation, ValueError, TypeError):
            return None
        side = str(o.get("side") or "").lower()
        if side not in ("bid", "ask") or not (vol.is_finite() and funds.is_finite() and fee.is_finite()) or vol < 0:
            return None
        if vol == 0:
            return {}
        if side == "bid":
            return {base: vol, quote: -(funds + fee)}
        return {base: -vol, quote: funds - fee}

    @staticmethod
    def _q8(x: Decimal, up: bool) -> int:
        from decimal import ROUND_DOWN, ROUND_UP
        return int((x * (Decimal(10) ** 8)).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN))

    def _upbit_quote_fill_legs(self, o: dict):
        market = str(o.get("market") or "")
        if "-" not in market:
            return None
        quote, base = market.split("-", 1)
        quote, base = quote.upper(), base.upper()
        if not quote or not base:
            return None
        try:
            vol = Decimal(str(o.get("executed_volume") or "0"))
            funds = Decimal(str(o.get("executed_funds"))) if o.get("executed_funds") is not None \
                else Decimal(str(o.get("price") or "0")) * vol
            fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
        except (InvalidOperation, ValueError, TypeError):
            return None
        side = str(o.get("side") or "").lower()
        if side not in ("bid", "ask") or not (vol.is_finite() and funds.is_finite() and fee.is_finite()):
            return None
        if vol <= 0 or funds <= 0 or fee < 0:
            return None
        qv = vol * (Decimal(10) ** 8)
        if qv != qv.to_integral_value():
            return None
        ts = acct_norm.fill_ts(o) or self._iso_ts(o.get("created_at"))
        if not ts:
            return None
        if side == "ask":
            return base, quote, -int(qv), self._q8(funds - fee, up=False), ts, side
        return base, quote, int(qv), -self._q8(funds + fee, up=True), ts, side

    def _post_upbit_quote_fill(self, o: dict) -> bool:
        p = self._upbit_quote_fill_legs(o)
        if p is None:
            self._ex_skip_once("EX_FILL_SKIP", str(o.get("uuid")), f"비KRW 체결 검증 탈락 보류: {o.get('market')} {o.get('uuid')}")
            return False
        base, quote, bqb, qqb, ts, side = p
        qu = self._quote_usd(quote, ts)
        usd = float(Decimal(abs(qqb)) / (Decimal(10) ** 8) * qu) if qu is not None else None
        fx = self.px.fx_at(ts * 1000) if usd is not None else None
        krw = repr(usd * fx) if (usd is not None and fx) else None
        usd_s = repr(usd) if usd is not None else None
        n_ins = 0
        for seq, sym, qb in ((0, base, bqb), (1, quote, qqb)):
            lk, evn = ("acq", "EX_BUY") if qb > 0 else ("disp", "EX_SELL")
            aid = self._upbit_asset(sym)
            c9 = self.conn.execute(
                "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq,"
                " event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
                " classifier_ver) VALUES ('exchange', 'upbit:order', ?, ?, ?, ?, 'exchange:upbit', ?, ?, ?, ?, ?, ?)",
                (str(o["uuid"]), seq, ts, aid, str(qb), usd_s, krw, lk, evn, CLASSIFIER_VER))
            if c9.rowcount:
                self._bump_position(aid, qb, "exchange:upbit")
                n_ins += 1
        return n_ins > 0

    @staticmethod
    def _snap_quality(snap: dict) -> str:
        syn = (snap.get("tx") or {}).get("synth")
        if syn == "rpc":
            return "rpc_basic"
        if syn == "bs_list" or snap.get("src") == "bs_list":
            return "bs_list"
        return "blockscout_full"

    _ES_TT_KEYS = frozenset(("from", "to", "token", "total", "via"))
    _ES_IT_KEYS = frozenset(("from", "to", "value", "success", "error", "attr", "via"))

    @classmethod
    def _es_shape(cls, snap: dict) -> bool:
        tx = snap.get("tx") or {}
        if not tx or tx.get("synth") or snap.get("src"):
            return False
        return all(isinstance(r, dict) and set(r) <= cls._ES_TT_KEYS for r in snap.get("token_transfers") or []) \
            and all(isinstance(r, dict) and set(r) <= cls._ES_IT_KEYS for r in snap.get("internal") or [])

    @classmethod
    def _es_list(cls, snap: dict) -> bool:
        return cls._es_shape(snap) and not isinstance((snap.get("tx") or {}).get("from"), dict)

    @staticmethod
    def _leg_row_key(kind: str, r) -> str:
        if not isinstance(r, dict):
            return "raw:" + json.dumps(r, sort_keys=True, default=str)

        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def n9(v):
            try:
                return str(int(str(v)))
            except (TypeError, ValueError):
                return "" if v is None else str(v)
        if kind == "internal":
            ok9 = not (r.get("success") is False or r.get("error"))
            return json.dumps(["it", a9(r.get("from")), a9(r.get("to")), n9(r.get("value")), ok9])
        tok = r.get("token") if isinstance(r.get("token"), dict) else {}
        tot = r.get("total") if isinstance(r.get("total"), dict) else {}
        typ = str(tok.get("type") or r.get("token_type") or "ERC-20").upper()
        ca = str(tok.get("address") or tok.get("address_hash") or "").lower()
        if typ == "ERC-721":
            q9 = ["id", n9(tot.get("token_id"))]
        elif typ == "ERC-20":
            q9 = ["v", n9(tot.get("value"))]
        else:
            q9 = ["v", n9(tot.get("value")), "id", n9(tot.get("token_id"))]
        return json.dumps(["tt", a9(r.get("from")), a9(r.get("to")), ca, typ] + q9)

    BD_ATTR = "balance_delta"
    VIA_RPC = "rpc"

    @classmethod
    def _via_mark(cls, snap: dict, keys=None) -> dict:
        out = dict(snap)
        for key in ("token_transfers", "internal"):
            rows = snap.get(key)
            if isinstance(rows, list):
                out[key] = [dict(r, via=cls.VIA_RPC) if (isinstance(r, dict) and r.get("via") != cls.VIA_RPC
                                                         and (keys is None or cls._leg_row_key(key, r) in keys)) else r for r in rows]
        return out

    RPC_SEEN = "_rpc_seen"

    @classmethod
    def _rpc_hist(cls, snap: dict) -> bool:
        if snap.get(cls.RPC_SEEN) or (snap.get("tx") or {}).get("synth") == "rpc" or cls._bd_rows(snap):
            return True
        return any(isinstance(r, dict) and r.get("via") == cls.VIA_RPC for key in ("token_transfers", "internal") for r in snap.get(key) or [])

    @classmethod
    def _bd_rows(cls, snap: dict) -> list:
        rows = [r for r in snap.get("internal") or [] if isinstance(r, dict)]
        if any(r.get("attr") == cls.BD_ATTR for r in rows):
            return [r for r in rows if r.get("attr") == cls.BD_ATTR]
        return rows if snap.get("internal_note") == cls.BD_ATTR else []

    @classmethod
    def _bd_mark(cls, snap: dict) -> dict:
        bd = cls._bd_rows(snap)
        if not bd or all(r.get("attr") == cls.BD_ATTR for r in bd):
            return snap
        ids = {id(r) for r in bd}
        return dict(snap, internal=[dict(r, attr=cls.BD_ATTR) if (isinstance(r, dict) and id(r) in ids) else r
                                    for r in snap.get("internal") or []])

    @classmethod
    def _bd_union(cls, base: dict, other: dict) -> list:
        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def ok9(r):
            return isinstance(r, dict) and r.get("success") is not False and not r.get("error")
        base, other = cls._bd_mark(base), cls._bd_mark(other)
        tot, proto = {}, {}
        for snap in (base, other):
            bdw = {a9(r.get("to")) for r in cls._bd_rows(snap)}
            t9 = {}
            for r in snap.get("internal") or []:
                if ok9(r) and a9(r.get("to")) in bdw:
                    try:
                        t9[a9(r.get("to"))] = t9.get(a9(r.get("to")), 0) + int(str(r.get("value") or "0"))
                    except ValueError:
                        continue
            for w9, v9 in t9.items():
                tot[w9] = max(tot.get(w9, 0), v9)
            for r in cls._bd_rows(snap):
                proto.setdefault(a9(r.get("to")), r)
        bdids = {id(r) for r in cls._bd_rows(base)} | {id(r) for r in cls._bd_rows(other)}
        real = cls._merge_list_snaps({"internal": [r for r in base.get("internal") or [] if id(r) not in bdids]},
                                     {"internal": [r for r in other.get("internal") or [] if id(r) not in bdids]})["internal"]
        out = list(real)
        for w9, t9 in tot.items():
            r9 = 0
            for r in real:
                if ok9(r) and a9(r.get("to")) == w9:
                    try:
                        r9 += int(str(r.get("value") or "0"))
                    except ValueError:
                        pass
            if t9 > r9:
                out.append(dict(json.loads(json.dumps(proto[w9])), value=str(t9 - r9), success=True, attr=cls.BD_ATTR))
        return out

    @classmethod
    def _snap_merge(cls, old: dict, new: dict) -> dict:
        out = cls._merge_list_snaps(old, new)
        if cls._bd_rows(old) or cls._bd_rows(new):
            out["internal"] = cls._bd_union(old, new)
        cls._bd_note_fix(out)
        return out

    @classmethod
    def _bd_note_fix(cls, out: dict):
        if out.get("internal_note") == cls.BD_ATTR and not any(isinstance(r, dict) and r.get("attr") == cls.BD_ATTR
                                                               for r in out.get("internal") or []):
            out.pop("internal_note", None)

    @staticmethod
    def _merge_list_snaps(old: dict, new: dict) -> dict:
        out = json.loads(json.dumps(old))
        for key in ("token_transfers", "internal"):
            co, cn, rows = {}, {}, {}
            for r in old.get(key) or []:
                k = Core._leg_row_key(key, r)
                co[k] = co.get(k, 0) + 1
            for r in new.get(key) or []:
                k = Core._leg_row_key(key, r)
                cn[k] = cn.get(k, 0) + 1
                rows.setdefault(k, r)
            lst = out.setdefault(key, [])
            for k, n in cn.items():
                lst.extend(json.loads(json.dumps(rows[k])) for _ in range(max(0, n - co.get(k, 0))))
        ot, nt = old.get("tx") or {}, new.get("tx") or {}
        if (ot.get("raw_input") == "0x01" and str((ot.get("fee") or {}).get("value") or "0") == "0"
                and nt and nt.get("raw_input") != "0x01"):
            out["tx"] = json.loads(json.dumps(nt))
        elif isinstance(out.get("tx"), dict) and nt.get("type") == 126 and out["tx"].get("type") is None:
            out["tx"]["type"] = 126
            if nt.get("op_mint") is not None and out["tx"].get("op_mint") is None:
                out["tx"]["op_mint"] = nt.get("op_mint")
        return out

    @classmethod
    def _promote_keep(cls, old: dict, new: dict) -> dict:
        out = json.loads(json.dumps(new))
        if (old.get("tx") or {}).get("synth") == "rpc":
            old = cls._via_mark(old)
        cn = {}
        for r in new.get("token_transfers") or []:
            k = cls._leg_row_key("token_transfers", r)
            cn[k] = cn.get(k, 0) + 1
        seen = {}
        for r in old.get("token_transfers") or []:
            k = cls._leg_row_key("token_transfers", r)
            seen[k] = seen.get(k, 0) + 1
            if seen[k] > cn.get(k, 0):
                out.setdefault("token_transfers", []).append(json.loads(json.dumps(r)))
        if old.get("internal") or cls._bd_rows(new):
            out["internal"] = cls._bd_union(new, old)
            cls._bd_note_fix(out)
        via9 = {cls._leg_row_key(k9, r) for k9 in ("token_transfers", "internal") for r in old.get(k9) or []
                if isinstance(r, dict) and r.get("via") == cls.VIA_RPC}
        if via9:
            out = cls._via_mark(out, via9)
        return out

    @staticmethod
    def _legs_grow(old: dict, new: dict) -> bool:
        for key in ("token_transfers", "internal"):
            co, cn = {}, {}
            for r in old.get(key) or []:
                k = Core._leg_row_key(key, r)
                co[k] = co.get(k, 0) + 1
            for r in new.get(key) or []:
                k = Core._leg_row_key(key, r)
                cn[k] = cn.get(k, 0) + 1
            if any(n > co.get(k, 0) for k, n in cn.items()):
                return True
        return False

    @staticmethod
    def _internal_grows(old: dict, new: dict) -> bool:
        co, cn = {}, {}
        for r in old.get("internal") or []:
            k = Core._leg_row_key("internal", r)
            co[k] = co.get(k, 0) + 1
        for r in new.get("internal") or []:
            k = Core._leg_row_key("internal", r)
            cn[k] = cn.get(k, 0) + 1
        return any(n > co.get(k, 0) for k, n in cn.items())

    @staticmethod
    def _legs_cover(big: dict, small: dict) -> bool:
        for key in ("token_transfers", "internal"):
            cb = {}
            for r in big.get(key) or []:
                k = Core._leg_row_key(key, r)
                cb[k] = cb.get(k, 0) + 1
            for r in small.get(key) or []:
                k = Core._leg_row_key(key, r)
                if cb.get(k, 0) <= 0:
                    return False
                cb[k] -= 1
        return True

    def _tsfix_plan(self, old_snap: dict, new_u: dict) -> str:
        def is_list(s):
            return self._es_list(s) or self._snap_quality(s) in ("rpc_basic", "bs_list")
        old_l, new_l = is_list(old_snap), is_list(new_u)
        if old_l and new_l:
            act, out = "union", self._snap_merge(old_snap, new_u)
        elif old_l and self._legs_cover(new_u, old_snap):
            act, out = "promote", new_u
        elif not old_l and self._legs_cover(old_snap, new_u):
            act, out = "keep", old_snap
        elif not old_l and not new_l and self._legs_cover(new_u, old_snap):
            act, out = "promote", new_u
        elif not old_l and self._legs_cover(old_snap, dict(new_u, internal=[])):
            act, out = "union", self._snap_merge(old_snap, new_u)
        else:
            act, out = None, None
        if act == "keep" and not self._tx_legs(old_snap) >= self._tx_legs(new_u):
            act, out = "union", self._snap_merge(old_snap, new_u)
        if act is None or not (self._legs_cover(out, old_snap) and self._legs_cover(out, new_u)
                               and self._tx_legs(out) >= self._tx_legs(old_snap) | self._tx_legs(new_u)):
            raise RuntimeError("시각 보강본 레그 유실 위험 — 저장본(%s)·보강본(%s) 레그(가스·tx 값·실패 여부 포함)가 서로 모순이라 격리 유지(replay_poison 으로 재시도)"
                               % ("목록" if old_l else "완전 상세", "목록" if new_l else "완전 상세"))
        return act

    @staticmethod
    def _tx_legs(snap: dict) -> set:
        tx = snap.get("tx") if isinstance(snap.get("tx"), dict) else {}

        def a9(x):
            return str((x.get("hash") if isinstance(x, dict) else x) or "").lower()

        def i9(v):
            return 0 if v is None or v == "" else int(str(v))
        fee = i9((tx.get("fee") or {}).get("value") if isinstance(tx.get("fee"), dict) else None)
        mint9 = set()
        if tx.get("type") == 126:
            m9 = i9(tx.get("op_mint") if tx.get("op_mint") is not None else tx.get("value"))
            if m9:
                mint9.add(("mint", a9(tx.get("from")), m9))
        if not tx or (tx.get("raw_input") == "0x01" and not fee):
            return ({("st", "ok")} if (snap.get("token_transfers") or snap.get("internal")) else set()) | mint9
        out = {("st", "ok" if tx.get("status") == "ok" else "fail")} | mint9
        if fee > 0:
            out.add(("fee", a9(tx.get("from"))))
        val = i9(tx.get("value"))
        if val:
            out.add(("val", a9(tx.get("from")), a9(tx.get("to")), val))
        return out

    def _tx_wallet_sums(self, chain: str, txhash: str) -> dict:
        out = {}
        for p in self.conn.execute("SELECT asset_id, location, qty_base FROM postings WHERE source_kind='chain_tx'"
                                   " AND source_ns=? AND source_id=? AND location LIKE ?",
                                   (chain, txhash, f"wallet:{chain}:%")).fetchall():
            if p["location"].count(":") != 2:
                continue
            k = (p["asset_id"], p["location"])
            out[k] = out.get(k, 0) + int(p["qty_base"])
        return out

    def _rederive_anchor_safe(self, chain: str, txhash: str, rec: dict):
        lu9 = rec.get("repair") == "leg_union"
        t_before = self._tx_hist_ts(chain, txhash) if lu9 else None
        self._anchor_touch = [] if lu9 else None
        try:
            before = self._tx_wallet_sums(chain, txhash)
            ev = self._maybe_rederive(chain, txhash, rec)
            self._anchor_absorb(chain, txhash, before)
            touched = list(self._anchor_touch or [])
        finally:
            self._anchor_touch = None
        if lu9 and ev is not None:
            ts9 = [t for t in [t_before, self._tx_hist_ts(chain, txhash)] + touched if t is not None]
            if ts9:
                try:
                    log.info("장기 곡선 다시 계산 표식(leg 합집합 재기장 %s): %s 부터", txhash[:14], common.mark_hist_dirty(min(ts9)))
                except Exception as e:
                    log.warning("장기 곡선 다시 계산 표식 실패: %s", e)
        return ev

    def _tx_hist_ts(self, chain: str, txhash: str):
        r = self.conn.execute("SELECT MIN(event_ts) FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
                              (chain, txhash)).fetchone()
        if r and r[0] is not None:
            return int(r[0])
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        try:
            snap9 = json.loads(row["snapshot"]) if row else {}
            return self._ts_of((snap9.get("tx") or {}).get("timestamp")) if isinstance(snap9, dict) else None
        except (TypeError, ValueError, AttributeError):
            return None

    def _anchor_absorb(self, chain: str, txhash: str, before: dict):
        after = self._tx_wallet_sums(chain, txhash)
        if after == before or self._meta_get(f"ext_prewindow_tx:{chain}:{txhash}"):
            return 0
        n9 = 0
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (chain, txhash)).fetchone()
        try:
            snap9 = json.loads(row["snapshot"]) if row else {}
            ts = self._ts_of(snap9.get("ts") if chain == "sol" else (snap9.get("tx") or {}).get("timestamp")) if isinstance(snap9, dict) else None
        except (TypeError, ValueError, AttributeError):
            ts = None
        if ts is None:
            return 0
        blk9 = self._tx_block(chain, txhash)
        T, ws = self._recon_view(chain)
        pay = None
        wtimes = None
        for (aid, loc) in sorted(set(before) | set(after)):
            d = after.get((aid, loc), 0) - before.get((aid, loc), 0)
            if not d:
                continue
            w = loc.split(":", 2)[2].lower()
            sid = t9 = None
            if T and w in ws and self._absorbed(f"recon:{chain}", ts, T, blk9):
                if chain == "bsc":
                    if pay is None:
                        r9 = self.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{chain}",)).fetchone()
                        try:
                            pay = {str(k).lower(): {str(x).lower() for x in (v or {})}
                                   for k, v in (json.loads(r9[0]) if r9 and r9[0] else {}).items() if isinstance(v, dict)}
                        except (TypeError, ValueError):
                            pay = {}
                    a9 = self.conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                    k9 = "native:none" if (a9 and a9[0] == "native") else f"token:{str((a9 or [None, ''])[1] or '').lower()}"
                    if k9 not in pay.get(w, set()):
                        continue
                sid, t9 = f"recon:{chain}", int(T)
            else:
                if wtimes is None:
                    wtimes = self._wrecon_times(chain)
                wt3 = wtimes.get(w)
                if wt3:
                    is_nat = bool(self.conn.execute("SELECT 1 FROM assets WHERE asset_id=? AND kind='native'", (aid,)).fetchone())
                    wt = wt3[1] if is_nat else wt3[0]
                    w_sid = loc.split(":", 2)[2] if chain == "sol" else w
                    sid9 = f"recon:{chain}:{w_sid}" + (":native" if (is_nat and wt3[2]) else "")
                    if wt and self._absorbed(sid9, ts, wt, blk9):
                        sid, t9 = sid9, wt
            if sid:
                a9 = self.conn.execute("SELECT kind, address FROM assets WHERE asset_id=?", (aid,)).fetchone()
                if a9 and a9[0] == "token" and not self._obs_tok_observed(sid, w, a9[1]):
                    continue
                self._anchor_adjust(chain, sid, t9, aid, loc, -d, txhash)
                n9 += 1
        return n9

    def _anchor_adjust(self, chain: str, sid: str, T: int, aid: int, loc: str, comp: int, txhash: str):
        r = self.conn.execute("SELECT posting_id, qty_base, event_ts FROM postings WHERE source_kind='opening' AND source_ns=? AND source_id=?"
                              " AND asset_id=? AND location=? ORDER BY leg_seq LIMIT 1", (chain, sid, aid, loc)).fetchone()
        f9 = self.conn.execute("SELECT min(event_ts) FROM postings WHERE location=? AND source_kind='chain_tx'", (loc,)).fetchone()[0]
        pos_ts = self._win_t0(T, chain)
        if sid != f"recon:{chain}" and f9 is not None:
            pos_ts = min(pos_ts, int(f9) - 1)
        touch9 = getattr(self, "_anchor_touch", None)
        if r:
            q0 = int(r["qty_base"])
            nq = q0 + comp
            if isinstance(touch9, list):
                touch9.append(int(r["event_ts"]))
            if nq == 0:
                self.conn.execute("DELETE FROM postings WHERE posting_id=?", (r["posting_id"],))
            else:
                ets = int(r["event_ts"]) if (nq > 0) == (q0 > 0) else (pos_ts if nq > 0 else int(T))
                self.conn.execute("UPDATE postings SET qty_base=?, event_ts=? WHERE posting_id=?", (str(nq), ets, r["posting_id"]))
                if isinstance(touch9, list):
                    touch9.append(int(ets))
        else:
            q0, nq = 0, comp
            if isinstance(touch9, list):
                touch9.append(int(pos_ts if comp > 0 else int(T)))
            seq = self.conn.execute("SELECT coalesce(max(leg_seq), -1) FROM postings WHERE source_kind='opening' AND source_ns=?"
                                    " AND source_id=?", (chain, sid)).fetchone()[0] + 1
            self.conn.execute(
                "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('opening', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening', 'OPENING', ?)",
                (chain, sid, seq, pos_ts if comp > 0 else int(T), aid, loc, str(comp), CLASSIFIER_VER))
        self._bump_position(aid, comp, loc)
        log.info("★[%s] %s 재기장 — 대사 앵커(%s) %s 칸 보정 %d → %d (앵커가 흡수한 T 이전 흐름과 이중 계상 방지)★",
                 chain, txhash[:14], sid, loc.split(":", 2)[2][:10], q0, nq)

    def _rpc_touch(self, chain: str, txhash: str, old_snap: dict, new_u: dict, q_new: str, rpc_old: bool):
        if q_new != "rpc_basic" or rpc_old or common.ZK_STACK.get(chain):
            return
        keys = {self._leg_row_key(k9, r) for k9 in ("token_transfers", "internal") for r in new_u.get(k9) or [] if isinstance(r, dict)}
        marked = dict(self._via_mark(old_snap, keys) if keys else old_snap, **{self.RPC_SEEN: True})
        if marked != old_snap:
            self.conn.execute("UPDATE raw_txs SET snapshot=? WHERE chain=? AND txhash=?",
                              (json.dumps(marked, ensure_ascii=False), chain, txhash))

    def _maybe_rederive(self, chain: str, txhash: str, rec: dict):
        new_snap = rec.get("snapshot") or {}
        row = self.conn.execute("SELECT snapshot, wallets FROM raw_txs WHERE chain=? AND txhash=?",
                                (chain, txhash)).fetchone()
        if not row:
            return None
        try:
            old_snap = json.loads(row["snapshot"])
        except json.JSONDecodeError:
            old_snap = {}
        try:
            old_w = {str(w).lower() for w in (json.loads(row["wallets"] or "[]") or [])}
        except (json.JSONDecodeError, TypeError):
            old_w = set()
        new_w = {str(w).lower() for w in (rec.get("wallets") or [])}
        add_w = (new_w - old_w) & self.my_wallets.get(chain, set())
        q_old, q_new = self._snap_quality(old_snap), self._snap_quality(new_snap)
        es_list_new = self._es_list(new_snap)
        new_u = new_snap
        if common.ZK_STACK.get(chain) and old_snap.get("internal_note") == "zk_base_token" \
                and new_snap.get("internal_note") != "zk_base_token" and new_snap.get("tx"):
            ctx9 = (old_snap.get("tx") or new_snap.get("tx")) if es_list_new else new_snap.get("tx")
            new_u = dict(self._zk_norm(chain, dict(new_snap, tx=ctx9)), tx=new_snap.get("tx"))
        old_snap = self._bd_mark(old_snap)
        new_u = self._bd_mark(new_u)
        bd_any = bool(self._bd_rows(old_snap) or self._bd_rows(new_u))
        if q_new == "rpc_basic":
            new_u = self._via_mark(new_u)
        rpc_old = self._rpc_hist(old_snap)
        rpc9 = q_old == "rpc_basic" or q_new == "rpc_basic" or bd_any or rpc_old
        rpc_es_union = (q_old == "rpc_basic" and es_list_new)
        promote = (q_new == "blockscout_full" and q_old == "rpc_basic" and not rpc_es_union)
        merge_list = False
        tsf9 = isinstance(rec.get("ts_fix"), dict)
        if tsf9:
            act9 = self._tsfix_plan(old_snap, new_u)
            if common.ZK_STACK.get(chain):
                cand9 = new_snap if act9 == "promote" else (self._snap_merge(old_snap, new_u) if act9 == "union" else old_snap)
                zo9, zn9, zc9 = self._zk_norm(chain, old_snap), self._zk_norm(chain, new_u), self._zk_norm(chain, cand9)
                if not (self._legs_cover(zc9, zo9) and self._legs_cover(zc9, zn9) and self._tx_legs(zc9) >= self._tx_legs(zo9) | self._tx_legs(zn9)):
                    raise RuntimeError("시각 보강본 레그 유실 위험 — ZK 기장 정규화 뒤 결과가 저장본·보강본 레그를 다 담지 못해 격리 유지(replay_poison 으로 재시도)")
            promote, merge_list = act9 == "promote", act9 == "union"
            if merge_list and not add_w and self._snap_merge(old_snap, new_u) == old_snap:
                self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
                return None
        elif add_w and not promote and q_new == "blockscout_full" and not self._es_shape(new_snap) \
                and (q_old == "bs_list" or self._es_shape(old_snap)):
            promote = True
        elif add_w and ((self._es_shape(old_snap) and self._es_shape(new_snap)) or (q_old == q_new == "bs_list")
                        or (q_old == q_new == "rpc_basic") or (q_old == "bs_list" and es_list_new)
                        or (q_new == "rpc_basic" and (q_old == "bs_list" or self._es_list(old_snap)))):
            merge_list = True
        elif (rec.get("repair") == "leg_union" or rpc_es_union) and not promote and ((self._es_shape(old_snap) and self._es_shape(new_snap))
                                                                                    or (q_old == q_new == "rpc_basic") or rpc_es_union
                                                                                    or (q_old == "bs_list" and es_list_new)):
            if not add_w and self._snap_merge(old_snap, new_u) == old_snap:
                return None
            merge_list = True
        if (not tsf9 and not promote and not merge_list and q_new == "blockscout_full" and q_old != "rpc_basic"
                and (old_snap.get("internal") or []) and self._internal_grows(old_snap, new_u)):
            merge_list = True
        if (not tsf9 and rec.get("repair") == "int_fill" and not promote and not merge_list and q_new == "blockscout_full"
                and not (old_snap.get("internal") or []) and (new_snap.get("internal") or [])):
            if es_list_new:
                merge_list = True
            else:
                promote = True
        if (not tsf9 and rec.get("repair") == "int_fill" and not promote and not merge_list and q_new == "rpc_basic"
                and new_snap.get("internal_note") in ("trace", "balance_delta") and (new_u.get("internal") or [])
                and self._internal_grows(old_snap, new_u)):
            merge_list = True
        if (not tsf9 and not promote and not merge_list and rpc9 and not common.ZK_STACK.get(chain)) and self._legs_grow(old_snap, new_u):
            merge_list = True
        if rpc9 and merge_list and not promote and not add_w and not tsf9 and self._snap_merge(old_snap, new_u) == old_snap:
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
            return None
        if not promote and not add_w and not merge_list:
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?",
                               (chain, txhash)).fetchone()
        old_ev = oe["event"] if oe else None
        n_old = 0
        for p in self.conn.execute(
                "SELECT asset_id, location, qty_base FROM postings"
                " WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
                (chain, txhash)).fetchall():
            self._bump_position(p["asset_id"], -int(p["qty_base"]), p["location"])
            n_old += 1
        self.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx'"
                          " AND source_ns=? AND source_id=?", (chain, txhash))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers"
                                   " WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?",
                                  (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        merged_w = json.dumps(sorted(old_w | (new_w & self.my_wallets.get(chain, set()))))
        if promote:
            if "_lp_liq" in old_snap and "_lp_liq" not in new_snap:
                new_snap = dict(new_snap, _lp_liq=old_snap["_lp_liq"])
            if not tsf9 and not common.ZK_STACK.get(chain) and (q_old == "rpc_basic" or bd_any or rpc_old):
                new_snap = self._promote_keep(old_snap, new_snap)
            if rpc9:
                new_snap = dict(new_snap, **{self.RPC_SEEN: True})
            ntx = new_snap.get("tx") or {}
            self.conn.execute(
                "UPDATE raw_txs SET snapshot=?, block=?, blockhash=?, wallets=?, ingested_at=?"
                " WHERE chain=? AND txhash=?",
                (json.dumps(new_snap, ensure_ascii=False),
                 ntx.get("block_number") or ntx.get("block"), ntx.get("block_hash"),
                 merged_w, int(time.time()), chain, txhash))
            snap_use = new_snap
        elif merge_list:
            snap_use = self._snap_merge(old_snap, new_u)
            if q_new == "rpc_basic":
                snap_use = self._via_mark(snap_use, {self._leg_row_key(k9, r) for k9 in ("token_transfers", "internal")
                                                     for r in new_u.get(k9) or [] if isinstance(r, dict)})
            if rpc9:
                snap_use[self.RPC_SEEN] = True
            self.conn.execute("UPDATE raw_txs SET snapshot=?, wallets=?, ingested_at=? WHERE chain=? AND txhash=?",
                              (json.dumps(snap_use, ensure_ascii=False), merged_w, int(time.time()), chain, txhash))
        else:
            self.conn.execute("UPDATE raw_txs SET wallets=?, ingested_at=? WHERE chain=? AND txhash=?",
                              (merged_w, int(time.time()), chain, txhash))
            snap_use = old_snap
            self._rpc_touch(chain, txhash, old_snap, new_u, q_new, rpc_old)
        ev = self.apply(chain, txhash, "", snap_use, rederive=(old_ev, keep))
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass
        why = ("상세 승격" if promote else ("새 관점 " + ",".join(a[:10] for a in sorted(add_w))) if add_w
               else "누락 leg 복구") + (" · leg 합집합" if merge_list else "")
        log.info("★[%s] %s 재파생(%s): %s→%s (기존 legs %d 역적용)★",
                 chain, txhash[:14], why, old_ev, ev, n_old)
        if ev != old_ev:
            dm("PROMOTE" if promote else "REDERIVE",
               f"[{chain}] {why}으로 분류 변경 {old_ev}→{ev} tx {txhash}",
               {"chain": chain, "txhash": txhash})
        return ev

    @staticmethod
    def _sol_legs(snap: dict) -> set:
        legs = {(str(d.get("owner")), str(d.get("asset")), str(d.get("delta"))) for d in (snap.get("deltas") or [])}
        gas = int(snap.get("fee_lamports") or 0) if snap.get("fee_payer_mine") else 0
        if gas:
            legs.add((str(snap.get("fee_payer")), "__gas__", str(-gas)))
        return legs

    def _rederive_sol_anchor_safe(self, rec: dict):
        before = self._tx_wallet_sums("sol", rec["txhash"])
        ev = self._maybe_rederive_sol(rec)
        self._anchor_absorb("sol", rec["txhash"], before)
        return ev

    def _maybe_rederive_sol(self, rec: dict):
        txhash = rec["txhash"]
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='sol' AND txhash=?", (txhash,)).fetchone()
        if not row:
            return None
        try:
            old = json.loads(row["snapshot"])
        except json.JSONDecodeError:
            return None
        lo, ln = self._sol_legs(old), self._sol_legs(rec)
        if ln == lo or not lo <= ln or bool(old.get("err")) != bool(rec.get("err")):
            return None
        oe = self.conn.execute("SELECT event FROM tx_class WHERE chain='sol' AND txhash=?", (txhash,)).fetchone()
        old_ev = oe["event"] if oe else None
        n_old = 0
        for p in self.conn.execute("SELECT asset_id, location, qty_base FROM postings WHERE source_kind='chain_tx'"
                                   " AND source_ns='sol' AND source_id=?", (txhash,)).fetchall():
            self._bump_position(p["asset_id"], -int(p["qty_base"]), p["location"])
            n_old += 1
        self.conn.execute("DELETE FROM postings WHERE source_kind='chain_tx' AND source_ns='sol' AND source_id=?", (txhash,))
        keep = set()
        for t in self.conn.execute("SELECT transfer_id, state, asset_id FROM transfers WHERE chain_txhash=?", (txhash,)).fetchall():
            if t["state"] == "sent":
                self.conn.execute("DELETE FROM transfers WHERE transfer_id=?", (t["transfer_id"],))
            else:
                keep.add(t["asset_id"])
        rec2 = dict(rec)
        rec2.pop("repersp", None)
        self.conn.execute("UPDATE raw_txs SET snapshot=?, wallets=?, ingested_at=? WHERE chain='sol' AND txhash=?",
                          (json.dumps(rec2, ensure_ascii=False), json.dumps(rec2.get("wallets", [])), int(time.time()), txhash))
        ev = self.apply_sol(rec2, rederive=(old_ev, frozenset(keep)))
        self._drop_daily_cache()
        new_o = sorted({o for o, _a, _d in ln - lo})
        log.info("★[sol] %s 재파생(새 관점 %s): %s→%s (기존 legs %d 역적용)★", txhash[:14],
                 ",".join(o[:10] for o in new_o), old_ev, ev, n_old)
        if ev != old_ev:
            dm("REDERIVE", f"[sol] 새 관점 {','.join(o[:10] for o in new_o)}으로 분류 변경 {old_ev}→{ev} tx {txhash}",
               {"chain": "sol", "txhash": txhash})
        return ev

    def _tsfix_sol(self, rec: dict):
        row = self.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='sol' AND txhash=?", (rec["txhash"],)).fetchone()
        if not row:
            return None
        try:
            old = json.loads(row["snapshot"])
        except (json.JSONDecodeError, TypeError):
            old = None
        if not isinstance(old, dict):
            raise RuntimeError("솔라나 시각 보강본 — 저장본 해석 불가라 격리 유지(replay_poison 으로 재시도)")
        lo, ln = self._sol_legs(old), self._sol_legs(rec)
        if bool(old.get("err")) != bool(rec.get("err")) or not (ln <= lo or lo <= ln):
            raise RuntimeError("솔라나 시각 보강본 레그 유실 위험 — 저장본·보강본 델타(또는 실패 여부)가 서로 모순이라 격리 유지(replay_poison 으로 재시도)")
        if ln <= lo:
            return None
        return self._rederive_sol_anchor_safe(rec)

    def _consume_record(self, rec: dict):
        if rec.get("kind") == "evm_tx":
            chain, txhash = rec["chain"], rec["txhash"].lower()
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO raw_txs (chain, txhash, block, blockhash, ts,"
                " snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
                (chain, txhash,
                 (rec["snapshot"]["tx"].get("block_number")
                  or rec["snapshot"]["tx"].get("block")),
                 rec["snapshot"]["tx"].get("block_hash"),
                 None, json.dumps(rec["snapshot"], ensure_ascii=False),
                 json.dumps(rec.get("wallets", [])), int(time.time())))
            if cur.rowcount:
                if isinstance(rec.get("ts_fix"), dict):
                    self._tx_legs(rec["snapshot"])
                ev = self.apply(chain, txhash, "", rec["snapshot"])
                log.info("[%s] %s → %s", chain, txhash[:14], ev)
                self._note_pre_window(chain, (rec["snapshot"].get("tx") or {}).get("timestamp"), txhash)
            else:
                self._rederive_anchor_safe(chain, txhash, rec)
        elif rec.get("kind") == "sol_tx":
            txhash = rec["txhash"]
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO raw_txs (chain, txhash, block, blockhash, ts,"
                " snapshot, wallets, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
                ("sol", txhash, rec.get("slot"), None, rec.get("ts"),
                 json.dumps(rec, ensure_ascii=False),
                 json.dumps(rec.get("wallets", [])), int(time.time())))
            if cur.rowcount:
                ev = self.apply_sol(rec)
                log.info("[sol] %s → %s", txhash[:14], ev)
                self._note_pre_window("sol", rec.get("ts"), txhash)
            elif isinstance(rec.get("ts_fix"), dict):
                self._tsfix_sol(rec)
            elif rec.get("repersp"):
                self._rederive_sol_anchor_safe(rec)
        elif rec.get("kind") == "ex_snapshot":
            self._consume_ex(rec)
        elif rec.get("kind") == "ex_fills":
            self._consume_fills(rec)
        elif rec.get("kind") == "ex_order_trades":
            self._consume_order_trades(rec)
        elif rec.get("kind") == "exf_fills":
            self._consume_exf_fills(rec)
        elif rec.get("kind") == "exf_late_cycle":
            self._late_cycle_done(rec)
        elif rec.get("kind") == "_corrupt":
            common.append_durable_jsonl(
                os.path.join(common.STATE_DIR, "poison.jsonl"),
                {"ts": int(time.time()), "err": "_corrupt_inbox_line", "rec": rec})
            log.error("inbox 손상 레코드 격리(poison.jsonl): %s", (rec.get("raw") or "")[:120])

    POISON_PATH = os.path.join(common.STATE_DIR, "poison.jsonl")
    POISON_REQ_PATH = os.path.join(common.STATE_DIR, "poison_replay_request.json")
    POISON_DONE_PATH = os.path.join(common.STATE_DIR, "poison_replayed.json")

    @staticmethod
    def poison_id(entry: dict) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(entry.get("rec"), ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def poison_replay_pass(self) -> int:
        req = common.read_control_json(self.POISON_REQ_PATH, None)
        if not isinstance(req, dict):
            if req is not None:
                try:
                    os.replace(self.POISON_REQ_PATH, self.POISON_REQ_PATH + ".bad")
                except OSError:
                    pass
            return 0
        try:
            chk9 = common.read_json(self.POISON_DONE_PATH, {}) or {}
            if not isinstance(chk9, dict):
                raise ValueError("격리 재처리 성공 기록 형식 오류(객체 아님)")
        except (Exception, SystemExit) as e:
            k9 = repr(e)[:200]
            if getattr(self, "_poison_done_bad", None) != k9:
                self._poison_done_bad = k9
                log.error("격리 레코드 재처리 보류(요청 유지 — poison_replayed.json 을 고치면 다음 주기 처리): %s", common.safe_err(e)[:160])
            return 0
        self._poison_done_bad = None
        try:
            os.remove(self.POISON_REQ_PATH)
        except OSError:
            pass
        want = set(str(x) for x in (req.get("ids") or []))
        all9 = req.get("all") is True
        done9 = common.read_json(self.POISON_DONE_PATH, {}) or {}
        ok_n = fail_n = 0
        try:
            lines = open(self.POISON_PATH, encoding="utf-8").read().splitlines()
        except OSError:
            lines = []
        if self.conn.in_transaction:
            self.conn.commit()
        for ln in lines:
            try:
                ent = json.loads(ln)
            except ValueError:
                continue
            rec = ent.get("rec") if isinstance(ent, dict) else None
            if not isinstance(rec, dict) or rec.get("kind") == "_corrupt":
                continue
            pid = self.poison_id(ent)
            if (not all9 and pid not in want) or (done9.get(pid) or {}).get("ok"):
                continue
            try:
                self.conn.execute("BEGIN")
                self._consume_record(rec)
                self.conn.commit()
                done9[pid] = {"ok": True, "ts": int(time.time())}
                ok_n += 1
                for p9 in (((rec.get("ts_fix") or {}).get("poison_ids") or []) if isinstance(rec.get("ts_fix"), dict) else []):
                    done9[str(p9)] = {"ok": True, "ts": int(time.time()), "via": "ts_fix"}
            except (sqlite3.OperationalError, OSError):
                self.conn.rollback()
                raise
            except Exception as e:
                self.conn.rollback()
                done9[pid] = {"ok": False, "ts": int(time.time()), "err": common.safe_err(repr(e))[:300]}
                fail_n += 1
        try:
            common.atomic_write_json(self.POISON_DONE_PATH, done9)
        except OSError as e:
            log.error("격리 재처리 결과 기록 실패(원장은 커밋됨 · 성공 표시만 빠짐): %s", common.safe_err(e)[:160])
        log.warning("격리 레코드 재처리: 성공 %d · 여전히 실패 %d (poison_replayed.json)", ok_n, fail_n)
        return ok_n

    def _drain_stream(self, stream: str, reader: SegmentReader, seg: int, off: int):
        batch, nseg, noff = reader.read_batch(seg, off)
        for rec, rseg, roff in batch:
            ok9 = False
            try:
                self.conn.execute("BEGIN")
                self._consume_record(rec)
                ok9 = True
            except (sqlite3.OperationalError, OSError):
                self.conn.rollback()
                raise
            except Exception as e:
                if ledger_backup.corrupt_error(e):
                    self.conn.rollback()
                    raise
                self.conn.rollback()
                common.append_durable_jsonl(
                    os.path.join(common.STATE_DIR, "poison.jsonl"),
                    {"ts": int(time.time()), "err": common.safe_err(repr(e)), "rec": rec})
                try:
                    dm("POISON", "🔴 거래 기록 1건을 처리하지 못해 따로 보관했어요\n원본은 그대로 있어요 — 같은 일이 계속되면 상태 패널에서 원인을 보세요.\n"
                       + common.safe_err(repr(e))[:140],
                       {"txhash": rec.get("txhash") if isinstance(rec, dict) else None})
                except Exception as dm_err:
                    log.error("포이즌 DM 적재 실패(격리는 완료, offset 전진 계속): %s", dm_err)
                self.conn.execute("BEGIN")
            try:
                self.conn.execute(
                    "INSERT INTO inbox_offsets (stream, seg, off) VALUES (?, ?, ?)"
                    " ON CONFLICT(stream) DO UPDATE SET seg=excluded.seg, off=excluded.off",
                    (stream, rseg, roff))
                self.conn.commit()
                seg, off = rseg, roff
            except Exception:
                self.conn.rollback()
                raise
            if ok9 and isinstance(rec, dict) and rec.get("ts_fix"):
                self._ts_fix_done(rec)
        reader.gc(seg, off)
        return seg, off, len(batch)

    def _ts_fix_done(self, rec: dict):
        ids = [str(x) for x in ((rec.get("ts_fix") or {}).get("poison_ids") or []) if x] if isinstance(rec.get("ts_fix"), dict) else []
        if not ids:
            return
        try:
            done9 = common.read_json(self.POISON_DONE_PATH, {}) or {}
            if not isinstance(done9, dict):
                done9 = {}
            for pid in ids:
                done9[pid] = {"ok": True, "ts": int(time.time()), "via": "ts_fix", "block_ts": (rec.get("snapshot") or {}).get("tx", {}).get("timestamp")
                              if rec.get("kind") == "evm_tx" else rec.get("ts")}
            common.atomic_write_json(self.POISON_DONE_PATH, done9)
            log.warning("격리됐던 시각 없는 tx %s — 블록 시각으로 보강돼 기장(격리 %d건 해소)", str(rec.get("txhash") or "")[:14], len(ids))
        except (Exception, SystemExit) as e:
            log.error("시각 보강 재처리 성공 표시 실패(원장은 기장됨): %s", e)

    @staticmethod
    def _ts_of(v):
        if v is None or v == "":
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            pass
        return common.iso_epoch(v)

    def _recon_view(self, chain: str):
        cache = self.__dict__.setdefault("_recon_cache", {})
        T = self._meta_get(f"recon_done_{chain}")
        if chain not in cache or cache[chain][2] != T:
            ws = set()
            r = self.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:{chain}",)).fetchone()
            try:
                d9 = json.loads(r[0]) if r and r[0] else {}
                ws = {str(w).lower() for w, v in d9.items() if isinstance(v, dict)} if isinstance(d9, dict) else set()
            except (TypeError, ValueError):
                ws = set()
            cache[chain] = (int(float(T)) if T else None, ws, T)
        return cache[chain][:2]

    def _note_pre_window(self, chain: str, ts_raw, txhash: str = None):
        ts = self._ts_of(ts_raw)
        if ts is None:
            return
        T, ws = self._recon_view(chain)
        wT = self._wrecon_times(chain)
        if (not T or ts >= T) and not any(ts < t9 for t3 in wT.values() for t9 in t3[:2] if t9):
            return
        if txhash:
            hit = False
            blk9 = self._tx_block(chain, txhash)
            for r in self.conn.execute("SELECT DISTINCT p.location, a.kind, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                                       " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=? AND p.location LIKE ?",
                                       (chain, txhash, f"wallet:{chain}:%")).fetchall():
                w = r[0].split(":", 2)[2].lower()
                w = w.split(":stake:", 1)[0]
                wt3 = wT.get(w)
                wt9 = (wt3[1] if r[1] == "native" else wt3[0]) if wt3 else None
                sid9 = f"recon:{chain}:{w}" + (":native" if (wt3 and r[1] == "native" and wt3[2]) else "")
                tok9 = r[1] != "native"
                if (T and w in ws and self._absorbed(f"recon:{chain}", ts, T, blk9)
                        and (not tok9 or self._obs_tok_observed(f"recon:{chain}", w, r[2]))) \
                        or (wt9 and self._absorbed(sid9, ts, wt9, blk9) and (not tok9 or self._obs_tok_observed(sid9, w, r[2]))):
                    hit = True
                    break
            if not hit:
                return
        elif not T or ts >= T:
            return
        k = f"ext_prewindow:{chain}"
        n = int(self._meta_get(k) or 0) + 1
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(n)))
        if txhash:
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"ext_prewindow_tx:{chain}:{txhash}", str(ts)))

    EXT_STREAMS = frozenset(("evm", "sol", "bsc", "ex"))
    EXT_STALL_SEC = 3600
    EXT_RETRY_MAX = 24 * 3600

    def _ext_items(self, now: float):
        bcfg = self.cfg.get("backfill") or {}
        stall = float(bcfg.get("stall_sec") or self.EXT_STALL_SEC)
        running, stalled, ex_done = [], [], []
        for unit, items in bf_engine.read_status().items():
            if not isinstance(items, dict) or unit.startswith("_"):
                continue
            for key, it in items.items():
                if not isinstance(it, dict) or not (key.endswith(":extend") or it.get("phase") == "extend"):
                    continue
                name = f"{unit}/{key}"
                upd = float(it.get("updated") or 0)
                if it.get("phase") != "done":
                    moved = float(it.get("moved_at") or it.get("started") or upd or 0)
                    if now - upd >= 3 * 3600:
                        continue
                    (stalled if now - moved > stall else running).append(name)
                elif unit in ("ex", "exf") and int(it.get("emitted", 1) or 0) > 0:
                    ex_done.append((name, float(it.get("done_at") or upd)))
        return running, stalled, ex_done

    def ext_rebuild_pass(self, drained: set):
        bcfg = self.cfg.get("backfill") or {}
        if bcfg.get("auto_rebuild") is False or os.environ.get("TJ_EXT_REBUILD") == "0":
            if self._meta_get("ext_rebuild_started_at"):
                self.conn.execute("DELETE FROM meta WHERE k='ext_rebuild_started_at'")
                self.conn.commit()
                self._ext_status()
            return
        now = time.time()
        if now - self._last_ext_check < float(bcfg.get("rebuild_check_sec") or 60):
            return
        self._last_ext_check = now
        need = {}
        for r in self.conn.execute("SELECT k, v FROM meta WHERE k LIKE 'ext_prewindow:%'").fetchall():
            try:
                if int(r["v"]) > 0:
                    need[r["k"][len("ext_prewindow:"):]] = int(r["v"])
            except (TypeError, ValueError):
                continue
        running, stalled, ex_all = self._ext_items(now)
        last_rb = float(self._meta_get("ext_rebuilt_at") or 0)
        ex_done = [n for n, t in ex_all if t >= last_rb]
        if not need and not ex_done:
            return
        try:
            gap = float(bcfg.get("rebuild_min_gap_sec") or 1800)
        except (TypeError, ValueError, OverflowError):
            gap = 1800.0
        gap = min(6 * 3600.0, max(0.0, gap)) if gap == gap else 1800.0
        if not ex_done and last_rb and now - last_rb < gap and not self._meta_get("ext_rebuild_started_at"):
            return
        if running:
            if not getattr(self, "_ext_wait_logged", False):
                log.info("과거 창 확장 진행 중(%s) — 끝난 뒤 원장 재구축", ", ".join(running[:4]))
                self._ext_wait_logged = True
            return
        if stalled and not getattr(self, "_ext_stall_logged", False):
            log.warning("과거 창 확장 멈춤(%s) — 기다리지 않고 원장 재구축 진행", ", ".join(stalled[:4]))
            self._ext_stall_logged = True
        if not self.EXT_STREAMS <= set(drained):
            return
        nb = float(self._meta_get("rebuild_not_before") or 0)
        if now < nb:
            return
        if self._meta_get("ext_rebuild_started_at"):
            self._ext_record_fail("중단됨(재구축 도중 프로세스 종료)")
            return
        fail = float(self._meta_get("ext_rebuild_fail_at") or 0)
        nfail = int(self._meta_get("ext_rebuild_fails") or 0)
        wait = min(self.EXT_RETRY_MAX, float(bcfg.get("rebuild_retry_sec") or 6 * 3600) * (2 ** max(0, nfail - 1)))
        if fail and now - fail < wait:
            ap9 = common.read_control_json(self.PNL_APPROVE_PATH, None)
            at9 = ops_requests._fin(ap9.get("at")) if isinstance(ap9, dict) else None
            un9 = ops_requests._fin(ap9.get("until")) if isinstance(ap9, dict) else None
            fresh9 = (at9 is not None and un9 is not None and fail < at9 <= now + 60 and now < un9 <= now + ops_requests.APPROVE_TTL + 600
                      and ap9.get("report_sha") == (ops_requests.gate_record() or {}).get("report_sha"))
            if not fresh9 or now - fail < 600:
                return
            log.warning("재구축: 보류된 결과를 승인함 — 백오프를 기다리지 않고 다시 재계산(승인한 결과와 같을 때만 교체)")
        self._ext_rebuild(need, ex_done)

    def _ext_touched(self, ex_done: list):
        pairs = set()
        for r in self.conn.execute("SELECT k FROM meta WHERE k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'").fetchall():
            _, ch, h = r[0].split(":", 2)
            for g, loc in self.conn.execute(
                    "SELECT DISTINCT a.group_id, p.location FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                    " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (ch, h)).fetchall():
                if g is None:
                    continue
                pairs.add((int(g), loc))
        pairs |= self._dec_pending_pairs()
        prefixes = set()
        for name in ex_done:
            unit, key = name.split("/", 1)
            ex = key.split(":", 1)[0]
            prefixes.add(f"exchange:{'upbit' if unit == 'ex' else ex}")
        return pairs, prefixes

    @staticmethod
    def _positions(conn) -> dict:
        return {(int(r[0]), r[1]): tuple(r[2:]) for r in conn.execute(
            "SELECT group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions")}

    QTY_TOL = Decimal("1e-8")

    def _ext_position_gate(self, new_db: str, pairs: set, prefixes: set, locked=()):
        live = self._positions(self.conn)
        c = sqlite3.connect(common.sqlite_ro_uri(new_db, immutable=True), uri=True)
        try:
            new = self._positions(c)
            return self._ext_position_gate_cmp(live, new, c, pairs, prefixes, locked)
        finally:
            c.close()

    def _ext_persp_exempt(self, c, k, qa: Decimal, qb: Decimal):
        loc = str(k[1] or "")
        if loc.count(":") != 2 or not loc.startswith("wallet:"):
            return 0
        ch, w = loc.split(":", 2)[1], loc.split(":", 2)[2]
        sql = ("SELECT p.source_kind, p.source_ns, p.source_id, p.qty_base, a.decimals FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
               " WHERE p.location=? AND a.group_id=?")

        def sums(conn9):
            out9 = {}
            with localcontext() as ctx:
                ctx.prec = 100
                for sk, ns, sid, qb9, dec in conn9.execute(sql, (loc, int(k[0]))).fetchall():
                    kk = (sk, ns, sid)
                    out9[kk] = out9.get(kk, Decimal(0)) + Decimal(int(qb9)) / (Decimal(10) ** int(18 if dec is None else dec))
            return out9
        sl, sn = sums(self.conn), sums(c)
        diff = {kk: sn.get(kk, Decimal(0)) - sl.get(kk, Decimal(0)) for kk in set(sl) | set(sn)}
        diff = {kk: d for kk, d in diff.items() if d != 0}
        if not diff:
            return 0
        tol = self.QTY_TOL + abs(qa) * Decimal("1e-12")
        if abs(sum(diff.values(), Decimal(0)) - (qb - qa)) > tol:
            return 0
        r9 = self.conn.execute("SELECT added_at FROM wallets WHERE chain=? AND address=?", (ch, w)).fetchone() or \
            self.conn.execute("SELECT added_at FROM wallets WHERE chain=? AND lower(address)=lower(?)", (ch, w)).fetchone()
        if not r9 or r9[0] is None:
            return 0
        added = int(r9[0])
        for sk, ns, sid in diff:
            if sk != "chain_tx" or ns != ch:
                return 0
            if self.conn.execute("SELECT 1 FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=? AND location=? LIMIT 1",
                                 (ns, sid, loc)).fetchone():
                return 0
            if not c.execute("SELECT 1 FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=? AND location=? LIMIT 1",
                             (ns, sid, loc)).fetchone():
                return 0
            ing = self.conn.execute("SELECT ingested_at FROM raw_txs WHERE chain=? AND txhash=?", (ns, sid)).fetchone()
            if not ing or ing[0] is None or int(ing[0]) >= added:
                return 0
        return len(diff)

    def _ext_position_gate_cmp(self, live: dict, new: dict, c, pairs: set, prefixes: set, locked=()):
        lk_groups = set()
        if locked:
            for r in self.conn.execute("SELECT DISTINCT group_id FROM assets WHERE upper(symbol) IN (%s)"
                                       % ",".join("?" * len(locked)), [str(x).upper() for x in locked]).fetchall():
                if r[0] is None:
                    continue
                lk_groups.add(int(r[0]))
        spam_groups = self._ext_spam_groups()
        bad, cost_diff, skipped = [], 0, 0
        exempt, exempt_tx = [], 0
        for k in set(live) | set(new):
            a, b = live.get(k), new.get(k)
            if k[0] in lk_groups and k[1] == "exchange:upbit":
                continue
            if str(k[1] or "").startswith("out:") or k[0] in spam_groups:
                skipped += 1
                continue
            touched = k in pairs or k[1] in prefixes
            qa = Decimal(a[0]) if a else Decimal(0)
            qb = Decimal(b[0]) if b else Decimal(0)
            tol = self.QTY_TOL + abs(qa) * Decimal("1e-12")
            if k[1] == "exchange:upbit":
                tol = max(tol, self.EX_RECON_TOL)
            if not touched and abs(qa - qb) > tol:
                n9 = self._ext_persp_exempt(c, k, qa, qb)
                if n9:
                    touched = True
                    exempt.append(f"{k} {qa}→{qb}")
                    exempt_tx += n9
            if touched:
                if qb < -tol and qb < qa - tol:
                    bad.append(f"{k} 음수 {qa}→{qb}")
            elif abs(qa - qb) > tol:
                bad.append(f"{k} 수량 {qa}→{qb}")
            elif (a or ("0", "0", "0"))[1:] != (b or ("0", "0", "0"))[1:]:
                cost_diff += 1
        if cost_diff:
            log.info("재구축 포지션 게이트: 수량 동일, 원가/미상 수량만 다른 칸 %d개(허용)", cost_diff)
        if skipped:
            log.info("재구축 포지션 게이트: 판정 제외 %d칸(out:* 외부 주머니 · 사칭 토큰 그룹)", skipped)
        if exempt:
            log.warning("★재구축 포지션 게이트: 등록 뒤 관점 변화 면제 %d칸(근거 tx %d건 — 등록 전에 저장된 tx 의 새 지갑 레그 · 새 음수만 검사): %s★",
                        len(exempt), exempt_tx, " · ".join(exempt[:5]))
        self._ext_gate_exempt = exempt
        return bad

    def _ext_spam_groups(self) -> set:
        per = {}
        for r in self.conn.execute("SELECT group_id, kind, chain, address, symbol FROM assets WHERE group_id IS NOT NULL").fetchall():
            g = int(r[0])
            s9 = r[4] or ""
            fake = r[1] == "token" and bool(r[3]) and bool(s9) and bool(spamguard.impostor_of(s9))
            per[g] = per.get(g, True) and fake
        return {g for g, f in per.items() if f}

    @staticmethod
    def _ext_wal_settle(path: str) -> bool:
        wal = path + "-wal"
        if not (os.path.exists(wal) and os.path.getsize(wal) > 0):
            return True
        c9 = None
        try:
            c9 = sqlite3.connect(path, timeout=10)
            busy, nlog, ncp = c9.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy or (nlog >= 0 and ncp != nlog):
                log.warning("재구축 shadow WAL 체크포인트 미완(busy=%s log=%s done=%s)", busy, nlog, ncp)
                return False
        except sqlite3.Error as e:
            log.warning("재구축 shadow WAL 정리 실패: %s", common.safe_err(e))
            return False
        finally:
            if c9 is not None:
                c9.close()
        ok = not (os.path.exists(wal) and os.path.getsize(wal) > 0)
        if ok:
            log.info("재구축 shadow WAL 을 본문에 합침(단일 파일)")
        return ok

    def _ext_rebuild(self, need: dict, ex_done: list):
        import shutil
        import subprocess
        bcfg = self.cfg.get("backfill") or {}
        ts = time.strftime("%Y%m%d_%H%M%S")
        home = os.path.expanduser(str(bcfg.get("rebuild_dir") or "~"))
        shadow = os.path.join(home, f"tj_shadow_extrebuild_{ts}")
        root = common.BASE_DIR
        live = common.DB_PATH
        tmp = live + f".extnew_{ts}"
        why = ", ".join([("토큰 자리수(decimals) 채움" if c == "decimals_fix" else f"{c} 창 밖 {n}건") for c, n in sorted(need.items())] + ex_done) or "?"
        if self.conn.in_transaction:
            self.conn.commit()
        t_start = int(time.time())
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_started_at', ?)", (str(t_start),))
        self.conn.commit()
        self._ext_status(running=True)

        def fail(msg):
            n9 = self._ext_record_fail(msg)
            log.error("★과거 창 확장 재구축 실패 %d회째(원장 무변, 백오프 뒤 재시도): %s★", n9, msg)
            self._ext_merge_px(os.path.join(shadow, "px_cache_core.json"))
            shutil.rmtree(shadow, ignore_errors=True)
            for p9 in (shadow + ".report.json", tmp):
                try:
                    os.remove(p9)
                except OSError:
                    pass

        try:
            size = os.path.getsize(live) + (os.path.getsize(live + "-wal") if os.path.exists(live + "-wal") else 0)
            os.makedirs(home, exist_ok=True)
            free_home = shutil.disk_usage(home).free
            free_state = shutil.disk_usage(os.path.dirname(live)).free
            same_fs = os.stat(home).st_dev == os.stat(os.path.dirname(live)).st_dev
            need_home = 3 * size + (size if same_fs else 0) + (2 << 30)
            if free_home < need_home or free_state < 1.5 * size:
                return fail(f"디스크 부족: 여유 {free_home >> 30}GB / 필요 ≈{need_home >> 30}GB (원장 {size >> 20}MB)")
            os.makedirs(shadow, mode=0o700, exist_ok=True)
            os.chmod(shadow, 0o700)
            log.warning("★과거 창 확장 반영 — 원장 재구축 시작(core 소비 일시 정지 ≈4분): %s★", why)
            pairs, prefixes = self._ext_touched(ex_done)
            self._ext_wait_upbit_complete()
            py = sys.executable or "/usr/bin/python3"
            args = [py, os.path.join(root, "tools", "rebuild2.py"), "--shadow-dir", shadow, "--report", shadow + ".report.json",
                    "--price-online-lp"] + ([] if bcfg.get("rebuild_allow_locked") is False else ["--allow-locked"]) \
                + ([] if bcfg.get("rebuild_pnl_gate") is False else ["--web-compare"])
            try:
                r = subprocess.run(args, env=dict(os.environ, TJ_BASE=root), cwd=root, capture_output=True, text=True,
                                   timeout=float(bcfg.get("rebuild_timeout_sec") or 5400))
            except subprocess.TimeoutExpired:
                return fail("rebuild2 시간 초과")
            if r.returncode:
                return fail("rebuild2 rc=%d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[-300:]))
            new_db = os.path.join(shadow, "ledger.db")
            try:
                g = subprocess.run([py, os.path.join(root, "tools", "verify_fixc.py"), "gates", new_db,
                                    "--balances", os.path.join(shadow, "upbit_balances.json"), "--live", live], capture_output=True, text=True,
                                   timeout=float(bcfg.get("verify_timeout_sec") or self.EXT_VERIFY_TIMEOUT_SEC))
            except subprocess.TimeoutExpired:
                return fail("verify_fixc 게이트 시간 초과")
            if g.returncode:
                return fail("게이트 b·c: " + g.stdout.strip()[-300:])
            self._ext_wal_settle(new_db)
            if os.path.exists(new_db + "-wal") and os.path.getsize(new_db + "-wal") > 0:
                return fail("shadow WAL 미체크포인트")
            locked = []
            try:
                rep9 = json.load(open(shadow + ".report.json", encoding="utf-8"))
                locked = list(((rep9.get("anchors") or {}).get("upbit_reanchor") or {}).get("locked") or [])
            except (OSError, ValueError):
                pass
            bad = self._ext_position_gate(new_db, pairs, prefixes, locked=locked)
            if bad:
                return fail(f"포지션 게이트 {len(bad)}칸: " + " · ".join(bad[:5]))
            if bcfg.get("rebuild_pnl_gate") is not False:
                pg9 = self._ext_pnl_gate(shadow + ".report.json", bcfg, why)
                if not pg9["ok"] and not pg9.get("approved"):
                    return fail("손익 게이트: " + pg9["reason"])
            c2 = sqlite3.connect(new_db)
            try:
                if c2.execute("PRAGMA quick_check").fetchone()[0] != "ok" or \
                        c2.execute("SELECT 1 FROM meta WHERE k='rebuild_incomplete'").fetchone():
                    return fail("새 원장 무결성/마커")
                c2.execute("DELETE FROM meta WHERE k LIKE 'ext_prewindow:%' OR k LIKE 'ext\\_prewindow\\_tx:%' ESCAPE '\\'"
                           " OR k IN ('ext_rebuild_fail_at', 'ext_rebuild_fails', 'ext_rebuild_last_error', 'ext_rebuild_started_at')")
                c2.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuilt_at', ?)", (str(t_start),))
                c2.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuilt_why', ?)", (why[:500],))
                c2.commit()
            finally:
                c2.close()
            self._ext_merge_px(os.path.join(shadow, "px_cache_core.json"))
            shutil.copyfile(new_db, tmp)
            c3 = sqlite3.connect(common.sqlite_ro_uri(tmp, immutable=True), uri=True)
            try:
                ok3 = c3.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                c3.close()
            if not ok3:
                return fail("복사본 무결성")
        except Exception as e:
            return fail(f"예외 {type(e).__name__}: {common.safe_err(e)}")
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.conn.close()
        try:
            kr9, ko9 = self._ext_keep_cfg(bcfg)
            self._ext_swap(live, tmp, ts, keep_recent=kr9, keep_oldest=ko9)
        except Exception as e:
            log.critical("★재구축 원장 교체 중 오류 — core 재기동(원장 파일 확인: %s*): %s★", live, e)
            raise SystemExit(1)
        shutil.rmtree(shadow, ignore_errors=True)
        self._ext_prune_reports(home)
        try:
            os.remove(self.PNL_APPROVE_PATH)
        except OSError:
            pass
        log.warning("★과거 창 확장 반영 완료 — 원장 교체(이전 원장 %s), core 재기동★", os.path.basename(live) + f".pre_extrebuild_{ts}")
        self._ext_status(rebuilt_at=t_start)
        try:
            common.atomic_write_json(os.path.join(common.STATE_DIR, "intentional_restart.json"),
                                     {"unit": "tj-core", "ts": int(time.time()), "reason": "ext_rebuild"})
        except OSError:
            pass
        import logging
        try:
            keep = sqlite3.connect(live)
            keep.execute("SELECT count(*) FROM meta").fetchone()
        except sqlite3.Error:
            pass
        logging.shutdown()
        os._exit(0)

    def _ext_merge_px(self, path: str) -> int:
        d9 = common.read_json(path, None)
        if not isinstance(d9, dict):
            return 0
        n = 0
        try:
            with self.px.lock:
                for sect in ("candle", "fx", "cven", "cgday"):
                    src9 = d9.get(sect)
                    if not isinstance(src9, dict):
                        continue
                    dst9 = self.px.d.setdefault(sect, {})
                    for k9, v9 in src9.items():
                        if k9 not in dst9 and v9 not in (None, 0, 0.0, "", [], {}):
                            dst9[k9] = v9
                            n += 1
                if n:
                    self.px._dirty = int(getattr(self.px, "_dirty", 0) or 0) + n
            if n:
                self.px.flush()
                log.info("재구축 shadow 시세 %d개를 라이브 원가 캐시에 합침(px_cache_core.json)", n)
        except Exception as e:
            log.warning("재구축 shadow 시세 합치기 실패: %s", common.safe_err(e))
        return n

    PNL_GATE_PATH = os.path.join(common.STATE_DIR, "rebuild_pnl_gate.json")
    PNL_APPROVE_PATH = os.path.join(common.STATE_DIR, "rebuild_pnl_approve.json")

    def _ext_pnl_gate(self, report_path: str, bcfg: dict, why: str) -> dict:
        tol_usd, tol_pct = ops_requests.tol_of(bcfg)
        try:
            rep9 = json.load(open(report_path, encoding="utf-8"))
        except (OSError, ValueError):
            rep9 = {}
        ev = ops_requests.gate_eval(rep9, tol_usd, tol_pct)
        out = {"ok": ev["ok"], "approved": False, "reason": ev["reason"], "months": ev["months"][:5], "n_months": len(ev["months"]),
               "unv": ev["unv"], "cost_lost": ev["cost_lost"], "decimals_unresolved": ev["decimals_unresolved"],
               "open_cost": ev["open_cost"][:5], "n_open_cost": len(ev["open_cost"]), "missing": ev["missing"],
               "why": why[:200], "ts": int(time.time()),
               "tol": [tol_usd, tol_pct]}
        if not out["ok"]:
            try:
                sha9, name9 = ops_requests.preserve_report(report_path)
            except OSError as e:
                sha9, name9 = None, None
                log.warning("재구축 손익 게이트: 거부 보고서 보존 실패(승인 불가 — 다음 재계산에서 다시): %s", common.safe_err(e))
            out["report_sha"], out["report_file"] = sha9, name9
            if sha9:
                ok9, note9, asha9 = ops_requests.approval_check(ev, tol_usd, tol_pct)
                if ok9:
                    out["approved"], out["approved_sha"] = True, asha9
                    log.warning("재구축 손익 게이트: 차이 있음(%s) — 승인한 보고서(%s…)와 같은 결과라 통과", out["reason"], str(asha9)[:12])
                elif note9:
                    out["approve_note"] = note9
                    log.warning("재구축 손익 게이트: 승인이 있지만 이번 결과에 맞지 않음 — %s", note9)
            else:
                out["approve_note"] = "보고서가 없어 승인할 수 없어요 — 다음 재계산 결과로"
        elif out["months"] == [] and not out["reason"]:
            log.info("재구축 손익 게이트 통과 — 월별 실현·원가미상·열린 원가 차이 임계 이내")
        try:
            common.atomic_write_json(self.PNL_GATE_PATH, out)
        except OSError:
            pass
        return out

    EXT_VERIFY_TIMEOUT_SEC = 1800
    EXT_UPBIT_WAIT_SEC = 120
    EXT_UPBIT_FRESH_SEC = 30

    def _ext_wait_upbit_complete(self):
        p = os.path.join(common.STATE_DIR, "upbit_orders_state.json")
        if not os.path.exists(p):
            return
        t0 = time.time()
        while time.time() - t0 < self.EXT_UPBIT_WAIT_SEC:
            try:
                fresh = time.time() - os.path.getmtime(p) <= self.EXT_UPBIT_FRESH_SEC
                if fresh and (common.read_json(p, {}) or {}).get("complete"):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        log.info("재구축: 업비트 체결 완주 도장을 %d초 안에 못 봄 — 그대로 진행(rebuild2 가 판정)", self.EXT_UPBIT_WAIT_SEC)

    EXT_STATUS_PATH = os.path.join(common.STATE_DIR, "ext_rebuild_status.json")

    def _ext_record_fail(self, msg: str) -> int:
        n9 = int(self._meta_get("ext_rebuild_fails") or 0) + 1
        for k9, v9 in (("ext_rebuild_fail_at", str(int(time.time()))), ("ext_rebuild_fails", str(n9)),
                       ("ext_rebuild_last_error", str(msg)[:500])):
            self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k9, v9))
        self.conn.execute("DELETE FROM meta WHERE k='ext_rebuild_started_at'")
        self.conn.commit()
        self._ext_status()
        return n9

    def _ext_status(self, running: bool = False, rebuilt_at: int = None):
        try:
            if rebuilt_at:
                common.atomic_write_json(self.EXT_STATUS_PATH, {"running": False, "started_at": None, "fails": 0, "fail_at": None,
                                                                "last_error": None, "rebuilt_at": int(rebuilt_at), "ts": int(time.time())})
                return
            d = {"running": bool(running), "started_at": int(float(self._meta_get("ext_rebuild_started_at") or 0)) or None,
                 "fails": int(self._meta_get("ext_rebuild_fails") or 0),
                 "fail_at": int(float(self._meta_get("ext_rebuild_fail_at") or 0)) or None,
                 "last_error": self._meta_get("ext_rebuild_last_error"),
                 "rebuilt_at": int(float(self._meta_get("ext_rebuilt_at") or 0)) or None,
                 "ts": int(time.time())}
            common.atomic_write_json(self.EXT_STATUS_PATH, d)
        except Exception:
            pass

    EXT_KEEP_RECENT = 1
    EXT_KEEP_REPORTS = 3

    @classmethod
    def _ext_keep_cfg(cls, bcfg: dict):
        kr = bcfg.get("rebuild_keep_recent") if isinstance(bcfg, dict) else None
        ko = bcfg.get("rebuild_keep_oldest") if isinstance(bcfg, dict) else None
        kr = kr if isinstance(kr, int) and not isinstance(kr, bool) and kr >= 0 else cls.EXT_KEEP_RECENT
        ko = ko if isinstance(ko, bool) else True
        return kr, ko

    @classmethod
    def _ext_prune_reports(cls, home: str, keep: int = None):
        keep = cls.EXT_KEEP_REPORTS if keep is None else keep
        try:
            rs = sorted(f9 for f9 in os.listdir(home) if f9.startswith("tj_shadow_extrebuild_") and f9.endswith(".report.json"))
        except OSError:
            return []
        gone = []
        for f9 in rs[:max(0, len(rs) - keep)]:
            try:
                os.remove(os.path.join(home, f9))
                gone.append(f9)
            except OSError:
                pass
        return gone

    @classmethod
    def _ext_swap(cls, live: str, tmp: str, ts: str, keep_recent: int = None, keep_oldest: bool = True):
        d = os.path.dirname(live)
        base = os.path.basename(live) + ".pre_extrebuild_"
        olds = sorted(f9 for f9 in os.listdir(d) if f9.startswith(base) and not f9.endswith(("-wal", "-shm")))
        kr = cls.EXT_KEEP_RECENT if keep_recent is None else max(0, int(keep_recent))
        keep9 = set(olds[:1] if keep_oldest else []) | set(olds[len(olds) - kr:] if kr else [])
        drop = [f9 for f9 in olds if f9 not in keep9]
        for f9 in drop:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.remove(os.path.join(d, f9 + sfx))
                except OSError:
                    pass
        ledger_backup.swap_in(live, tmp, live + f".pre_extrebuild_{ts}", log=log)
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass

    def _stable_regroup(self):
        moved = []
        for r in self.conn.execute(
                "SELECT a.asset_id, a.chain, a.address, a.group_id, g.name FROM assets a LEFT JOIN asset_groups g"
                " ON g.group_id=a.group_id WHERE a.kind='token' AND a.address IS NOT NULL").fetchall():
            ca = r["address"]
            want = pricing.STABLE_CAS.get(r["chain"], {}).get(ca) or (pricing.STABLE_MINTS.get(ca) if r["chain"] == "sol" else None)
            if not want or r["name"] == want or r["group_id"] is None:
                continue
            others = self.conn.execute("SELECT count(*) FROM assets WHERE group_id=? AND asset_id!=?",
                                       (r["group_id"], r["asset_id"])).fetchone()[0]
            if others:
                log.warning("스테이블 재그룹 건너뜀: asset %s(%s) — 그룹 %s 에 다른 자산 %d개", r["asset_id"], want, r["name"], others)
                continue
            self.conn.execute("INSERT OR IGNORE INTO asset_groups (name) VALUES (?)", (want,))
            tgt = self.conn.execute("SELECT group_id FROM asset_groups WHERE name=?", (want,)).fetchone()["group_id"]
            old = r["group_id"]
            self.conn.execute("UPDATE assets SET group_id=? WHERE asset_id=?", (tgt, r["asset_id"]))
            for p in self.conn.execute("SELECT location, qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions WHERE group_id=?",
                                       (old,)).fetchall():
                cur = self.conn.execute("SELECT qty_norm, qty_unknown_norm, cost_alloc_usd FROM positions WHERE group_id=? AND location=?",
                                        (tgt, p["location"])).fetchone()
                if cur:
                    with localcontext() as ctx:
                        ctx.prec = 100
                        vals = [format(Decimal(cur[i]) + Decimal(p[i + 1]), "f") for i in range(3)]
                    self.conn.execute("UPDATE positions SET qty_norm=?, qty_unknown_norm=?, cost_alloc_usd=? WHERE group_id=? AND location=?",
                                      (*vals, tgt, p["location"]))
                else:
                    self.conn.execute("INSERT INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?,?,?)",
                                      (tgt, p["location"], p["qty_norm"], p["qty_unknown_norm"], p["cost_alloc_usd"]))
            self.conn.execute("DELETE FROM positions WHERE group_id=?", (old,))
            moved.append(f"{r['chain']}:{ca[:10]} {r['name']}→{want}(g{old}→g{tgt})")
        if moved:
            self.conn.commit()
            log.warning("★스테이블 화이트리스트 반영 — 재그룹 %d: %s★", len(moved), ", ".join(moved))
        return moved

    @staticmethod
    def _cutover_hint() -> str:
        return common.tool_ref("cutover_c.sh", "이 설치엔 컷오버 도구가 없어요 — 같은 세대 코드로 되돌리거나 원장 백업 state/backups/ledger_YYYYMMDD.db 사용")

    def run(self):
        _mk = self._meta_get("rebuild_incomplete")
        if _mk and str(_mk).startswith("cutover_c_ex_drain:"):
            raise SystemExit("★컷오버 drain 마커 감지(%s) — 세대 1 복귀라면 %s 를 rc 0 으로 완주한 뒤 기동,"
                             " 세대 2 라면 컷오버가 미완(%s)★" % (_mk, common.tool_ref("repost_orders_gen1.py", "주문 재기장 도구(운영자 전용 — 이 설치에 없음)"),
                                                          common.tool_ref("rollback_c.sh", "원장 백업 state/backups/ledger_YYYYMMDD.db 로 되돌리기")))
        if _mk:
            raise SystemExit("★rebuild_incomplete 마커 감지 — 재파생이 완료되지 않은 원장."
                             " 백업(state/backups/ledger_YYYYMMDD.db)으로 되돌리거나 tools/rebuild2.py 로 다시 계산해 교체한 뒤 기동하라★")
        streams = (("evm", self.reader), ("sol", self.sol_reader), ("bsc", self.bsc_reader),
                   ("ex", self.ex_reader))
        offs = {}
        for stream, _ in streams:
            row = self.conn.execute(
                "SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            offs[stream] = (row["seg"], row["off"]) if row else (1, 0)
        log.info("가동: inbox %s", {s: offs[s] for s, _ in streams})
        try:
            self._stable_regroup()
        except Exception as e:
            self.conn.rollback()
            log.error("스테이블 재그룹 실패(원장 무변, 다음 기동 재시도): %s", e)
        try:
            self._reclass_plain_xfer_once()
        except Exception as e:
            self.conn.rollback()
            log.error("평범한 전송 재분류 실패(원장 무변, 다음 기동 재시도): %s", e)
        try:
            self._reclass_added_lp_mgrs_once()
        except Exception as e:
            self.conn.rollback()
            log.error("새 LP 관리자 재분류 실패(원장 무변, 다음 기동 재시도): %s", e)
        try:
            self._out_px_band_fix_once()
        except Exception as e:
            self.conn.rollback()
            log.error("보낸 내역 시가 되돌림 실패(원장 무변, 다음 기동 재시도): %s", e)
        while True:
            n = 0
            drained = set()
            for stream, reader in streams:
                seg, off = offs[stream]
                seg, off, got = self._drain_stream(stream, reader, seg, off)
                offs[stream] = (seg, off)
                n += got
                if not got:
                    drained.add(stream)
            if "ex" in drained:
                self._drain_at = time.time()
                try:
                    self._exf_late_flush()
                except Exception as e:
                    self.conn.rollback()
                    log.error("늦은 행 순액 흡수 실패(대기표 유지 · 다음 주기): %s", common.safe_err(e)[:200])
            try:
                self.price_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("가격패스 실패(다음 주기): %s", e)
            try:
                self.krw_fill_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("원화 원가 채움 실패(다음 주기): %s", e)
            try:
                self.deposit_rematch_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("입금 재대사 실패(다음 주기): %s", e)
            try:
                self.exchange_recon_pass(drained)
            except Exception as e:
                self.conn.rollback()
                log.error("거래소 대사 실패(다음 주기): %s", e)
            try:
                self.exf_recon_pass(drained)
            except Exception as e:
                self.conn.rollback()
                log.error("해외거래소 대사 실패(다음 주기): %s", e)
            try:
                self.outflow_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("보낸 내역 판정 반영 실패(다음 주기): %s", e)
            try:
                self.poison_replay_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("격리 레코드 재처리 실패(다음 주기): %s", e)
            try:
                self.decimals_resolve_pass()
            except Exception as e:
                self.conn.rollback()
                log.error("자리수 해결 요청 처리 실패(다음 주기): %s", e)
            try:
                self.ext_rebuild_pass(drained)
            except SystemExit:
                raise
            except Exception as e:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                log.error("과거 창 확장 재구축 점검 실패(다음 주기): %s", e)
            try:
                self._gate_reload()
            except Exception as e:
                self.conn.rollback()
                log.error("활동 게이트 반영 실패(다음 주기): %s", e)
            try:
                self.recon_pass(drained)
            except Exception as e:
                self.conn.rollback()
                log.error("recon_pass 실패(다음 주기 재시도): %s", e)
            ledger_backup.tick(log)
            if self.conn.in_transaction:
                log.error("★패스 종료 후 트랜잭션 잔류 — 방어 롤백 (누수 경로 추적 필요)★")
                self.conn.rollback()
            if not n:
                time.sleep(3)


def main():
    common.ensure_dirs()
    cfg = common.load_config()
    Core(cfg).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
    except sqlite3.DatabaseError as e:
        if not ledger_backup.corrupt_error(e):
            raise
        log.critical("★%s — %s · 백업에서 되돌리기: python3 tools/ledger_restore.py list → restore <백업> --apply★",
                     ledger_backup.CORRUPT_WHY, common.safe_err(e)[:160])
        sys.exit(3)
