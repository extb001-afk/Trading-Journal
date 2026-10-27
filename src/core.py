"""Ledger core: consumes collected events and writes double-entry postings."""
import os
import sqlite3
import sys
import time
from decimal import Decimal, localcontext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, histmark, logs, paths, runtime, seeds
if __name__ == "__main__":
    runtime.cpu_reserve_apply()
import db as dbm
import pricing, token_tables
import lpdec
import bf_engine
import ledger_backup
import recon_adj, autofix_apply
import ledger_lock
import chain_registry
import chain_event
from inbox import SegmentReader

log = logs.setup_logging("tj-core")


from core_common import (  # noqa: F401
    CLASSIFIER_VER,
    dm,
    DM_RECENT_SEC,
    KRW_FILL_CALLS,
    KRW_FILL_SEC,
    MissingDecimals,
    MissingTs,
    POS_PROVISIONAL_DEC,
    PRICE_BACKOFF_MAX,
    PRICE_BACKOFF_MIN,
    PRICE_BATCH,
    PRICE_BULK_BATCH,
    PRICE_BULK_BUDGET,
    PRICE_IDLE_SEC,
    PRICE_PREFETCH_CALLS,
)


from core_dec import DecMixin  # noqa: E402


from core_classify import ClassifyMixin  # noqa: E402


from core_outflow import OutflowMixin  # noqa: E402


from core_lp import LpMixin  # noqa: E402


from core_post import PostMixin  # noqa: E402


import core_svc  # noqa: E402


from core_snap import SnapMixin  # noqa: E402


from core_inbox import InboxMixin  # noqa: E402


from core_late import LateMixin  # noqa: E402


from core_ext import ExtMixin  # noqa: E402
import calcguard, migrate  # noqa: E402


class Core(ExtMixin, LateMixin, InboxMixin, SnapMixin, PostMixin, LpMixin, OutflowMixin, ClassifyMixin, DecMixin):
    LEDGER_GEN = 2

    def __init__(self, cfg: dict):
        self.cfg = cfg
        if dbm.SCHEMA_VERSION != self.LEDGER_GEN:
            raise SystemExit(f"★db.py 세대({dbm.SCHEMA_VERSION}) ≠ core 세대({self.LEDGER_GEN}) — 배포 파일 혼합, 기동 금지★")
        if not os.path.exists(paths.DB_PATH):
            if os.environ.get("TJ_ALLOW_NEW_LEDGER") != "1":
                raise SystemExit(f"★원장 파일 없음: {paths.DB_PATH} — 백업에서 되돌리기: python3 tools/ledger_restore.py list"
                                 f" (정말 새 원장이면 TJ_ALLOW_NEW_LEDGER=1 명시)★")
        else:
            _ro9 = None
            for _uri9 in (paths.sqlite_ro_uri(paths.DB_PATH), paths.sqlite_ro_uri(paths.DB_PATH, immutable=True), None):
                try:
                    _ro9 = (dbm.connect(_uri9, uri=True, timeout=10) if _uri9
                            else dbm.connect(paths.DB_PATH, timeout=10))
                    _ro9.execute("SELECT 1").fetchone()
                    break
                except sqlite3.OperationalError:
                    if _ro9 is not None:
                        _ro9.close()
                    _ro9 = None
            if _ro9 is None:
                raise SystemExit(f"★원장 열기 실패(세대 검사 불가): {paths.DB_PATH}★")
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
        self.conn = dbm.open_db(paths.DB_PATH)
        if dbm.SCHEMA_VERSION != self.LEDGER_GEN:
            raise SystemExit(f"★db.py 세대({dbm.SCHEMA_VERSION}) ≠ core 세대({self.LEDGER_GEN}) — 배포 파일 혼합, 기동 금지★")
        ver = self.conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        if ver is None or int(ver["v"]) != self.LEDGER_GEN:
            raise SystemExit(f"★DB 세대({ver['v'] if ver else None}) ≠ core 세대({self.LEDGER_GEN}) — canonical 마이그레이션"
                             f"({self._cutover_hint()}) 없이 이 코드로 기동 금지★")
        self.conn.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('exf_wd_fee_since', ?)", (str(int(time.time())),))
        self.conn.commit()
        self.svc_exf = core_svc.ExfService(self, int(self.conn.execute("SELECT v FROM meta WHERE k='exf_wd_fee_since'").fetchone()["v"]))
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
        self.chain_owners = {}
        for r9 in chain_registry.wallets(cfg):
            self.chain_owners.setdefault(r9["chain"], set()).add(r9["key"])
            self.conn.execute("INSERT OR IGNORE INTO wallets (chain, address, label, added_at) VALUES (?,?,?,?)",
                              (r9["chain"], r9["key"], r9["label"] or None, now))
        for w in cfg.get("_disabled_wallets") or []:
            if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain") and str(w.get("address") or "").startswith("0x"):
                self.my_wallets.setdefault(w["chain"], set()).add(str(w["address"]).lower())
        self.wrapped = {k.lower(): v.lower() for k, v in cfg.get("wrapped_native", {}).items()}
        self.bridges = self._load_seed("bridge_contracts.json")
        self.lp_mgrs = lpdec.lp_managers(paths.BASE_DIR)
        self._load_exchange_addrs(cfg)
        self._dec_startup()
        self.conn.commit()
        self.reader = SegmentReader(os.path.join(paths.INBOX_DIR, "evm"))
        self.sol_reader = SegmentReader(os.path.join(paths.INBOX_DIR, "sol"))
        self.bsc_reader = SegmentReader(os.path.join(paths.INBOX_DIR, "bsc"))
        self.ex_reader = SegmentReader(os.path.join(paths.INBOX_DIR, "ex"))
        self.chain_readers = [(c9, SegmentReader(os.path.join(paths.INBOX_DIR, chain_registry.spec(c9).stream)))
                              for c9 in sorted(set(self.chain_owners) | set(chain_registry.present_streams(paths.INBOX_DIR, paths.STATE_DIR)))]
        self.px = pricing.PxCache(paths.state("px_cache_core.json"), track_legacy=True)
        self.svc_price = core_svc.PriceService(self)
        self.svc_recon = core_svc.ReconService(self)
        self.recon_months = 0.0 if cfg.get("backfill_full_history") \
            else float(cfg.get("backfill_months") or 0)
        self._last_ext_check = 0.0
        self._ext_born = time.time()

    def _win_t0(self, ref_ts=None, section=None) -> int:
        if self.recon_months <= 0:
            return 0
        ref = time.time() if ref_ts is None else float(ref_ts)
        t = int(ref - self.recon_months * 30 * 86400)
        vals = [v for v in (bf_engine.SINCE.target(None), bf_engine.SINCE.target(section) if section else None) if v]
        return int(min([t] + vals))

    def _load_seed(self, name: str) -> set:
        data = seeds.seed_json(name, [], base_dir=paths.BASE_DIR, strict=True)
        return {a.lower() for a in data}

    def _load_exchange_addrs(self, cfg: dict):
        for ex in cfg.get("exchange_addresses", []):
            addr = ex["address"] if ex["chain"] == "sol" else ex["address"].lower()
            if chain_registry.is_nonevm(ex["chain"]):
                try:
                    addr = chain_event.norm_counterparty(ex["chain"], ex["address"])
                except ValueError:
                    log.warning("거래소 주소 형식 오류(%s) — 건너뜀", ex["chain"])
                    continue
            self.conn.execute(
                "INSERT OR IGNORE INTO exchange_addresses (exchange, chain, address, currency, memo, sync_state)"
                " VALUES (?,?,?,?,?,'manual')",
                (ex["exchange"], ex["chain"], addr, ex.get("currency"), ex.get("memo")))

    def _ex_addr_set(self, chain: str) -> set:
        rows = self.conn.execute(
            "SELECT address FROM exchange_addresses WHERE chain=?", (chain,)).fetchall()
        return {r["address"] for r in rows}


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
                    self.conn.execute("UPDATE assets SET decimals=? WHERE asset_id=?", (int(decimals), row["asset_id"]))
                    if self._asset_has_postings(row["asset_id"]):
                        self._renorm_asset(row["asset_id"])
                elif int(st9) != int(decimals):
                    self._dec_issue(row["asset_id"], "conflict", int(st9), int(decimals))
            return row["asset_id"]
        cur = self.conn.execute(
            "INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed) VALUES (?,?,?,?,?,?)",
            (kind, chain, addr, symbol, decimals,
             1 if kind == "native" else 0))
        return cur.lastrowid


    def _meta_get(self, k: str):
        r = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None


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
            st = token_tables.STABLE_CAS.get(chain, {}).get(ca)
            if chain == "sol" and not st:
                st = token_tables.STABLE_MINTS.get(ca)
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

    def _norm(self, aid: int, v: int, provisional: bool = False) -> str:
        r = self.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if r is None or r["decimals"] is None:
            if not provisional:
                raise MissingDecimals(aid)
            dec = POS_PROVISIONAL_DEC
        else:
            dec = int(r["decimals"])
        with localcontext() as ctx:
            ctx.prec = 100
            return format(Decimal(v) / (Decimal(10) ** dec), "f")


    @classmethod
    def _ext_swap(cls, live: str, tmp: str, ts: str, keep_recent: int = None, keep_oldest: bool = False):
        d = os.path.dirname(live)
        base = os.path.basename(live) + ".pre_extrebuild_"
        olds = sorted(f9 for f9 in os.listdir(d) if f9.startswith(base) and not f9.endswith(("-wal", "-shm", "-journal")))
        kr = cls.EXT_KEEP_RECENT if keep_recent is None else max(0, int(keep_recent))
        keep9 = set(olds[:1] if keep_oldest else []) | set(olds[len(olds) - kr:] if kr else [])
        drop = [f9 for f9 in olds if f9 not in keep9]
        res9 = ledger_backup.swap_in(live, tmp, live + f".pre_extrebuild_{ts}", log=log)
        kept9 = (res9 or {}).get("kept")
        st9, why9 = ledger_backup.restore_state(kept9, deep=False) if kept9 and os.path.isfile(kept9) else ("invalid", "이번 보존본 없음")
        ok9 = st9 == "valid"
        if ok9:
            for f9 in drop:
                for sfx in ("", "-wal", "-shm", "-journal"):
                    try:
                        os.remove(os.path.join(d, f9 + sfx))
                    except OSError:
                        pass
        elif drop:
            log.warning("재구축 교체: 이번 보존본 확인 실패(%s) — 옛 보존본 %d개 그대로 둠", why9, len(drop))
        try:
            os.remove(paths.state("daily_cache.json"))
        except FileNotFoundError:
            pass

    def _stable_regroup(self):
        moved = []
        for r in self.conn.execute(
                "SELECT a.asset_id, a.chain, a.address, a.group_id, g.name FROM assets a LEFT JOIN asset_groups g"
                " ON g.group_id=a.group_id WHERE a.kind='token' AND a.address IS NOT NULL").fetchall():
            ca = r["address"]
            want = token_tables.STABLE_CAS.get(r["chain"], {}).get(ca) or (token_tables.STABLE_MINTS.get(ca) if r["chain"] == "sol" else None)
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
                    self._leg_sql("_stable_regroup.1", (*vals, tgt, p["location"]))
                else:
                    self._leg_sql("_stable_regroup.2", (tgt, p["location"], p["qty_norm"], p["qty_unknown_norm"], p["cost_alloc_usd"]))
            self._leg_sql("_stable_regroup.3", (old,))
            moved.append(f"{r['chain']}:{ca[:10]} {r['name']}→{want}(g{old}→g{tgt})")
        if moved:
            self.conn.commit()
            log.warning("★스테이블 화이트리스트 반영 — 재그룹 %d: %s★", len(moved), ", ".join(moved))
        return moved

    @staticmethod
    def _cutover_hint() -> str:
        return paths.tool_ref("cutover_c.sh", "이 설치엔 컷오버 도구가 없어요 — 같은 세대 코드로 되돌리거나 원장 백업 state/backups/ledger_YYYYMMDD.db 사용")

    def run(self):
        _mk = self._meta_get("rebuild_incomplete")
        if _mk and str(_mk).startswith("cutover_c_ex_drain:"):
            raise SystemExit("★컷오버 drain 마커 감지(%s) — 세대 1 복귀라면 %s 를 rc 0 으로 완주한 뒤 기동,"
                             " 세대 2 라면 컷오버가 미완(%s)★" % (_mk, paths.tool_ref("repost_orders_gen1.py", "주문 재기장 도구(운영자 전용 — 이 설치에 없음)"),
                                                          paths.tool_ref("rollback_c.sh", "원장 백업 state/backups/ledger_YYYYMMDD.db 로 되돌리기")))
        if _mk:
            raise SystemExit("★rebuild_incomplete 마커 감지 — 재파생이 완료되지 않은 원장."
                             " 백업(state/backups/ledger_YYYYMMDD.db)으로 되돌리거나 tools/rebuild2.py 로 다시 계산해 교체한 뒤 기동하라★")
        for i9 in range(max(1, int(self.HL_FENCE_TRIES))):
            try:
                self._hist_late_fence()
                break
            except Exception as e:   # noqa: BLE001 [boundary]
                try:
                    self.conn.rollback()
                except Exception as _cg9:   # noqa: BLE001 [cleanup]
                    calcguard.swallowed("core:Core.run[rollback#1]", _cg9)
                    pass
                if i9 + 1 >= max(1, int(self.HL_FENCE_TRIES)):
                    raise SystemExit("★늦은 원장 행 커서 울타리(meta %s) 초기화 실패 — 수집 소비를 시작하지 않음(원장 쓰기 가능 여부 확인 뒤 다시 기동): %s★"
                                     % (histmark.HIST_LATE_PID_K, logs.safe_err(str(e))[:200])) from e
                log.warning("늦은 원장 행 커서 울타리 초기화 실패(%d/%d — 잠시 뒤 다시): %s", i9 + 1, self.HL_FENCE_TRIES, logs.safe_err(str(e))[:200])
                time.sleep(float(self.HL_FENCE_SLEEP))
        streams = (("evm", self.reader), ("sol", self.sol_reader), ("bsc", self.bsc_reader),
                   ("ex", self.ex_reader)) + tuple(self.chain_readers)
        offs = {}
        for stream, _ in streams:
            row = self.conn.execute(
                "SELECT seg, off FROM inbox_offsets WHERE stream=?", (stream,)).fetchone()
            offs[stream] = (row["seg"], row["off"]) if row else (1, 0)
        log.info("가동: inbox %s", {s: offs[s] for s, _ in streams})
        try:
            self._stable_regroup()
        except Exception as e:  # noqa: BLE001 [boundary]
            calcguard.swallowed("core:Core.run[_stable_regroup]", e)
            self.conn.rollback()
            log.error("스테이블 재그룹 실패(원장 무변, 다음 기동 재시도): %s", e)
        migrate.startup(self)
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
                    self.svc_exf._exf_late_flush()
                except Exception as e:  # noqa: BLE001 [boundary]
                    calcguard.swallowed("core:Core.run[_exf_late_flush]", e)
                    self.conn.rollback()
                    log.error("늦은 행 순액 흡수 실패(대기표 유지 · 다음 주기): %s", logs.safe_err(e)[:200])
            try:
                self.svc_price.price_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[price_pass]", e)
                self.conn.rollback()
                log.error("가격패스 실패(다음 주기): %s", e)
            try:
                self.svc_price.krw_fill_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[krw_fill_pass]", e)
                self.conn.rollback()
                log.error("원화 원가 채움 실패(다음 주기): %s", e)
            try:
                self.svc_exf.deposit_rematch_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[deposit_rematch_pass]", e)
                self.conn.rollback()
                log.error("입금 재대사 실패(다음 주기): %s", e)
            try:
                self.svc_exf.exchange_recon_pass(drained)
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[exchange_recon_pass]", e)
                self.conn.rollback()
                log.error("거래소 대사 실패(다음 주기): %s", e)
            try:
                self.svc_exf.exf_recon_pass(drained)
                autofix_apply.core_pass(self.svc_exf)
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[exf_recon_pass]", e)
                self.conn.rollback()
                log.error("해외거래소 대사 실패(다음 주기): %s", e)
            try:
                self.outflow_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[outflow_pass]", e)
                self.conn.rollback()
                log.error("보낸 내역 판정 반영 실패(다음 주기): %s", e)
            try:
                self.poison_replay_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[poison_replay_pass]", e)
                self.conn.rollback()
                log.error("격리 레코드 재처리 실패(다음 주기): %s", e)
            try:
                self.decimals_pass()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[decimals_resolve_pass]", e)
                self.conn.rollback()
                log.error("자리수 해결 요청 처리 실패(다음 주기): %s", e)
            try:
                self.ext_rebuild_pass(drained)
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[ext_rebuild_pass]", e)
                try:
                    self.conn.rollback()
                except Exception as _cg9:  # noqa: BLE001 [cleanup]
                    calcguard.swallowed("core:Core.run[rollback#2]", _cg9)
                    pass
                log.error("과거 창 확장 재구축 점검 실패(다음 주기): %s", e)
            try:
                self.svc_recon._gate_reload()
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[_gate_reload]", e)
                self.conn.rollback()
                log.error("활동 게이트 반영 실패(다음 주기): %s", e)
            try:
                self.svc_recon.recon_pass(drained)
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[recon_pass]", e)
                self.conn.rollback()
                log.error("recon_pass 실패(다음 주기 재시도): %s", e)
            try:
                self.svc_recon.prov_pass()
            except Exception as e:   # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[prov_pass]", e)
                self.conn.rollback()
                log.warning("임시 잔고 처리 실패(다음 주기): %s", logs.safe_err(str(e))[:200])
            try:
                self.svc_recon.negabs_pass(drained)
            except Exception as e:  # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[negabs_pass]", e)
                self.conn.rollback()
                log.error("발견 시점 기초 잔고 처리 실패(다음 주기): %s", logs.safe_err(str(e))[:200])
            try:
                self._hist_late_scan()
            except Exception as e:   # noqa: BLE001 [boundary]
                calcguard.swallowed("core:Core.run[_hist_late_scan]", e)
                try:
                    self.conn.rollback()
                except Exception as _cg9:  # noqa: BLE001 [cleanup]
                    calcguard.swallowed("core:Core.run[rollback#3]", _cg9)
                    pass
                log.warning("늦은 원장 행 표식 실패(다음 주기): %s", logs.safe_err(str(e))[:200])
            ledger_backup.tick(log)
            recon_adj.tick(self.conn, self._win_t0, log, auto_on=config.autofix_enabled(self.cfg))
            if self.conn.in_transaction:
                log.error("★패스 종료 후 트랜잭션 잔류 — 방어 롤백 (누수 경로 추적 필요)★")
                self.conn.rollback()
            if not n:
                time.sleep(3)


_WRITER_LOCK = {}


def writer_lock(db_path):
    try:
        fd = ledger_lock.acquire(db_path, who="tj-core")
    except ledger_lock.LedgerBusy:
        log.warning("★다른 원장 작성자(tj-core·원장 도구·복원)가 쓰는 중(%s 잠김) — 그쪽이 끝날 때까지 대기(원장 작성자는 하나만)★", ledger_lock.LOCK_NAME)
        fd = ledger_lock.acquire(db_path, who="tj-core", wait=True)
        log.info("원장 잠금 획득 — 시작")
    _WRITER_LOCK["fd"] = fd
    return fd


def main():
    paths.ensure_dirs()
    runtime.parent_watch_start()
    writer_lock(paths.DB_PATH)
    cfg = config.load_config()
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
                     ledger_backup.CORRUPT_WHY, logs.safe_err(e)[:160])
        sys.exit(3)
