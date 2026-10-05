from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("tj")

FILE = "web_rawtx_cache.json"
FMT_V = 1
LOGIC_V = {"signer": 1, "infl": 1, "from": 1}
LOG_TABLE = "raw_rewrites"
LOG_OBJS = (LOG_TABLE, "raw_txs_rewrite_upd", "raw_txs_rewrite_del")
SAVE_EVERY = 300
BIG = 8_000_000
INFLOW_EVENTS = ("TRANSFER_IN", "PROGRAM_IN")
_HEX40 = re.compile(r"0x[0-9a-f]{40}")
_SIGNER_SOL = "json_extract(snapshot, '$.fee_payer'), NULL, NULL"
_SIGNER_EVM = ("COALESCE(json_extract(snapshot, '$.tx.from.hash'), json_extract(snapshot, '$.tx.from')),"
               " json_extract(snapshot, '$.tx.fee.value'), substr(json_extract(snapshot, '$.tx.raw_input'), 1, 10)")
_FROM_SEL = "lower(coalesce(json_extract(snapshot,'$.tx.from.hash'), json_extract(snapshot,'$.tx.from')))"
_LEGS_SQL = ("CASE WHEN json_type(snapshot, '$.{0}') = 'array' THEN"
             " (SELECT json_group_array(json_array(j.value -> '$.from', j.value -> '$.to')) FROM json_each(snapshot, '$.{0}') j"
             " WHERE j.type = 'object') END")
_BIG_SQL = ("SELECT json_valid(snapshot), CASE WHEN json_valid(snapshot) THEN json_extract(snapshot, '$.kind') END,"
            " CASE WHEN json_valid(snapshot) THEN json_array(snapshot -> '$.tx.from', snapshot -> '$.tx.to', snapshot -> '$.tx.value') END,"
            " CASE WHEN json_valid(snapshot) THEN " + _LEGS_SQL.format("token_transfers") + " END,"
            " CASE WHEN json_valid(snapshot) THEN " + _LEGS_SQL.format("internal") + " END"
            " FROM raw_txs WHERE chain=? AND txhash=?")


def signer_cols(chain: str) -> str:
    return _SIGNER_SOL if chain == "sol" else _SIGNER_EVM


def _k(chain, txh) -> str:
    return f"{chain}|{txh}"


def _ad(x) -> str:
    if isinstance(x, dict):
        x = x.get("hash") or x.get("address") or ""
    return x.lower() if isinstance(x, str) else ""


def inflow_ok_set(sn: dict, chain: str, mine: set) -> set:
    if chain == "sol" or sn.get("kind") == "sol_tx":
        try:
            ds = [int(d.get("delta") or 0) for d in sn.get("deltas") or []]
        except (TypeError, ValueError):
            ds = []
        if bool(ds) and min(ds) >= 0 and max(ds) > 0 and not sn.get("fee_payer_mine"):
            return set(sn.get("counterparties") or []) | {sn.get("fee_payer")}
        return set()
    tx = sn.get("tx") or {}
    if not isinstance(tx, dict):
        tx = {}
    fr, to = _ad(tx.get("from")), _ad(tx.get("to"))
    if fr in mine:
        return set()
    legs = [t for k9 in ("token_transfers", "internal") if isinstance(sn.get(k9), list) for t in sn[k9] if isinstance(t, dict)]
    s = {_ad(t.get("from")) for t in legs if _ad(t.get("to")) in mine}
    if fr not in s:
        rx = any(_ad(t.get("to")) in mine for t in legs)
        if not rx and to in mine:
            try:
                rx = int(tx.get("value") or 0) > 0
            except (TypeError, ValueError):
                rx = False
        if rx:
            s.add(fr)
    return s


def inflow_senders_of(sn: dict, chain: str, mine: set) -> list:
    ok = inflow_ok_set(sn, chain, mine)
    if not ok:
        return []
    if chain == "sol":
        found = set(sn.get("counterparties") or []) | ({sn["fee_payer"]} if sn.get("fee_payer") else set())
        return sorted(a for a in (found - mine) & ok if isinstance(a, str))
    return sorted(a for a in ok if isinstance(a, str) and a not in mine and _HEX40.fullmatch(a))


def mine_wallets(cfg: dict) -> set:
    return {((w.get("address") or "").lower() if str(w.get("address") or "").startswith("0x") else (w.get("address") or ""))
            for w in (cfg or {}).get("wallets") or []}


class RawTxCache:

    def __init__(self, state_dir: str, db_path: str = None, bg: bool = True):
        self.path = os.path.join(state_dir, FILE)
        self.db_path = db_path
        self.bg = bg
        self.started = False
        self.persist = False
        self.tracking = False
        self.signer = {}
        self.sig_seq = 0
        self.infl = {}
        self.infl_mine = None
        self._infl_sig = None
        self.infl_seq = 0
        self.infl_by = {}
        self.from_by = None
        self.from_rid = {}
        self.from_cnt = {}
        self.from_seq = 0
        self.dirty = False
        self.saved_at = 0.0
        self._fp = {}
        self._from_new = None
        self.gen = 0
        self._from_lock = threading.Lock()
        self._from_thread = None
        self.stats = {"load": None, "log_n": 0}

    @staticmethod
    def log_present(conn) -> bool:
        try:
            n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN (?, ?, ?)", LOG_OBJS).fetchone()[0]
        except Exception:
            return False
        return int(n) == len(LOG_OBJS)

    @staticmethod
    def _log_max(conn) -> int:
        return int(conn.execute(f"SELECT COALESCE(MAX(seq), 0) FROM {LOG_TABLE}").fetchone()[0])

    def _reset_all(self, seq=0):
        with self._from_lock:
            self.gen += 1
            self._from_new = None
        self.signer, self.infl, self.infl_by, self.infl_mine, self._infl_sig = {}, {}, {}, None, None
        self.from_by, self.from_rid, self.from_cnt = None, {}, {}
        self.sig_seq = self.infl_seq = self.from_seq = seq
        self.dirty = True

    def sync(self, conn):
        if not self.started:
            self.started = True
            self.persist = self.tracking = self.log_present(conn)
            if self.persist:
                self._load(conn)
            else:
                log.info("raw_txs 교체 기록 표 없음(tj-core 가 아직 옛 코드) — 웹 raw_txs 캐시는 이번 실행 메모리만(저장 안 함)")
        if not self.tracking:
            if not self.log_present(conn):
                return
            mx = self._log_max(conn)
            log.info("raw_txs 교체 기록 표 생김 — 웹 raw_txs 캐시 처음부터 다시(seq %d부터 추적)", mx)
            self._reset_all(mx)
            self.tracking = self.persist = True
            return
        try:
            mx = self._log_max(conn)
            r = conn.execute("SELECT rowid, chain, txhash FROM raw_txs ORDER BY rowid DESC LIMIT 1").fetchone()
            self._fp = {"rid": int(r[0]), "key": _k(r[1], r[2])} if r else {}
        except Exception as e:
            log.warning("raw_txs 교체 기록 조회 실패 — 캐시 처음부터: %s", e)
            self._reset_all()
            self.tracking = self.persist = False
            return
        if mx < max(self.sig_seq, self.infl_seq, self.from_seq if self.from_by is not None else 0):
            log.info("raw_txs 교체 기록이 캐시보다 짧다(원장 교체·복원) — 캐시 처음부터")
            self._reset_all(mx)
            return
        lo = min(self.sig_seq, self.infl_seq, self.from_seq if self.from_by is not None else mx)
        if mx <= lo:
            return
        n = 0
        for seq, ch, txh in conn.execute(f"SELECT seq, chain, txhash FROM {LOG_TABLE} WHERE seq > ? AND seq <= ? ORDER BY seq", (lo, mx)):
            n += 1
            key = (ch, txh)
            if seq > self.sig_seq:
                self.signer.pop(key, None)
            if seq > self.infl_seq:
                self._infl_drop(key)
            if self.from_by is not None and seq > self.from_seq:
                self._from_redo(conn, key)
        self.sig_seq = self.infl_seq = mx
        if self.from_by is not None:
            self.from_seq = max(self.from_seq, mx)
        if n:
            self.dirty = True
            self.stats["log_n"] += n

    def signer_fill(self, conn, want: dict) -> dict:
        cache = self.signer
        for ch, txs in want.items():
            txs = sorted(txs)
            q9 = "SELECT txhash, " + signer_cols(ch)
            for i in range(0, len(txs), 400):
                part = txs[i:i + 400]
                try:
                    for r9 in conn.execute(q9 + " FROM raw_txs WHERE chain=? AND txhash IN (" + ",".join("?" * len(part)) + ") AND json_valid(snapshot)",
                                           (ch, *part)).fetchall():
                        cache[(ch, r9[0])] = (r9[1], r9[2], r9[3])
                        self.dirty = True
                except Exception as e9:
                    log.warning("서명자 조회 실패(가짜 전송 판정 생략): %s", e9)
        return cache

    def _infl_drop(self, key):
        old = self.infl.pop(key, None)
        for a in old or ():
            s = self.infl_by.get(a)
            if s is not None:
                s.discard(key)
                if not s:
                    self.infl_by.pop(a, None)

    def _infl_put(self, key, senders):
        self._infl_drop(key)
        self.infl[key] = senders
        for a in senders:
            self.infl_by.setdefault(a, set()).add(key)

    def _infl_rows(self, conn, ch, part):
        try:
            return conn.execute("SELECT txhash, CASE WHEN octet_length(snapshot) <= ? THEN snapshot END, octet_length(snapshot)"
                                " FROM raw_txs WHERE chain=? AND txhash IN (" + ",".join("?" * len(part)) + ")", (BIG, ch, *part)).fetchall()
        except Exception:
            return [(r[0], r[1], None) for r in conn.execute(
                "SELECT txhash, snapshot FROM raw_txs WHERE chain=? AND txhash IN (" + ",".join("?" * len(part)) + ")", (ch, *part))]

    def _infl_compute(self, conn, keys, mine) -> int:
        by_ch = {}
        for ch, txh in keys:
            by_ch.setdefault(ch, []).append(txh)
        n = 0
        for ch, txs in by_ch.items():
            txs.sort()
            for i in range(0, len(txs), 100):
                for txh, sn9, ln9 in self._infl_rows(conn, ch, txs[i:i + 100]):
                    if sn9 is None and ln9 is not None and ch != "sol":
                        sn = self._big_shape(conn, ch, txh)
                    else:
                        if sn9 is None and ln9 is not None:
                            r9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ch, txh)).fetchone()
                            sn9 = r9[0] if r9 else None
                        try:
                            sn = json.loads(sn9 or "{}")
                        except (ValueError, TypeError):
                            sn = None
                    self._infl_put((ch, txh), inflow_senders_of(sn, ch, mine) if isinstance(sn, dict) else [])
                    n += 1
        return n

    @staticmethod
    def _big_shape(conn, ch, txh):
        r = conn.execute(_BIG_SQL, (ch, txh)).fetchone()
        if r is None:
            return None
        ok, kind, txf, tt, it = r
        if not ok or kind == "sol_tx":
            raw = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ch, txh)).fetchone()
            try:
                return json.loads((raw[0] if raw else None) or "{}")
            except (ValueError, TypeError):
                return None
        fr, to, val = json.loads(txf)
        legs = [{"from": a, "to": b} for a, b in json.loads(tt or "[]") + json.loads(it or "[]")]
        out = {"token_transfers": legs, "tx": {"from": fr, "to": to, "value": val}}
        if kind is not None:
            out["kind"] = kind
        return out

    def inflow_senders(self, conn, dests, mine: set) -> dict:
        fm = frozenset(mine)
        if self._infl_sig is not None:
            if self._infl_sig == self._mine_sig(fm):
                self.infl_mine = fm
            self._infl_sig = None
        if self.infl_mine != fm:
            if self.infl:
                log.info("내 지갑 목록 변경 — 유입 발신자 색인 다시 계산")
            self.infl, self.infl_by, self.infl_mine = {}, {}, fm
            self.dirty = True
        now9 = {(r9[0], r9[1]) for r9 in conn.execute("SELECT t.chain, t.txhash FROM tx_class t JOIN raw_txs r ON r.chain=t.chain AND r.txhash=t.txhash"
                                                      " WHERE t.event IN (?, ?)", INFLOW_EVENTS)}
        miss = [k for k in now9 if k not in self.infl]
        if miss:
            t0 = time.time()
            n = self._infl_compute(conn, miss, mine)
            self.dirty = True
            if n > 200:
                log.info("유입 발신자 색인: %d건 %.1f초", n, time.time() - t0)
        out = {}
        for a in dests:
            s = self.infl_by.get(a)
            if s:
                s2 = {k for k in s if k in now9}
                if s2:
                    out[a] = s2
        return out

    def _from_redo(self, conn, key):
        ks = _k(*key)
        rid0 = self.from_rid.get(ks)
        if rid0 is not None and rid0 in self.from_by:
            self._from_dec(rid0)
        r = conn.execute(f"SELECT rowid, {_FROM_SEL} FROM raw_txs WHERE chain=? AND txhash=?", key).fetchone()
        if r is not None:
            self._from_inc(r[0], r[1] or "", ks)

    def _from_inc(self, rid, f, ks):
        if rid in self.from_by:
            self._from_dec(rid)
        r0 = self.from_rid.get(ks)
        if r0 is not None and r0 != rid and r0 in self.from_by:
            self._from_dec(r0)
        self.from_by[rid] = (f, ks)
        self.from_rid[ks] = rid
        self.from_cnt[f] = self.from_cnt.get(f, 0) + 1

    def _from_dec(self, rid):
        f, ks = self.from_by.pop(rid)
        if self.from_rid.get(ks) == rid:
            self.from_rid.pop(ks, None)
        n = self.from_cnt.get(f, 1) - 1
        if n <= 0:
            self.from_cnt.pop(f, None)
        else:
            self.from_cnt[f] = n

    @staticmethod
    def _from_scan(conn):
        return {r[0]: (r[1] or "", _k(r[2], r[3])) for r in conn.execute(f"SELECT rowid, {_FROM_SEL}, chain, txhash FROM raw_txs")}

    def _from_bg(self, gen=None):
        gen = self.gen if gen is None else gen
        try:
            import db as dbm
            t0 = time.time()
            c = dbm.open_db(self.db_path, readonly=True)
            try:
                c.execute("BEGIN")
                seq = self._log_max(c) if self.log_present(c) else 0
                by = self._from_scan(c)
            finally:
                c.close()
            with self._from_lock:
                if gen == self.gen:
                    self._from_new = (gen, seq, by)
            log.info("발신자 건수 첫 계산(배경): %d행 %.1f초", len(by), time.time() - t0)
        except Exception as e:
            log.warning("발신자 건수 첫 계산 실패(다음 빌드에 다시): %s", e)
        finally:
            with self._from_lock:
                self._from_thread = None

    def _from_install(self, seq, by):
        self.from_by, self.from_rid, self.from_cnt = {}, {}, {}
        for rid, (f, ks) in by.items():
            self._from_inc(rid, f, ks)
        self.from_seq = seq
        self.dirty = True

    def from_counts(self, conn) -> dict:
        if self.from_by is None:
            with self._from_lock:
                got, self._from_new = self._from_new, None
            if got is not None and got[0] != self.gen:
                got = None
            if got is None and not self.bg:
                got = (self.gen, self._log_max(conn) if self.tracking else 0, self._from_scan(conn))
            if got is None:
                with self._from_lock:
                    if self._from_thread is None:
                        self._from_thread = threading.Thread(target=self._from_bg, args=(self.gen,), daemon=True, name="rawfrom-worker")
                        self._from_thread.start()
                return {}
            self._from_install(got[1], got[2])
            self.sync(conn)
        by = self.from_by
        rids = {r[0] for r in conn.execute("SELECT rowid FROM raw_txs")}
        gone = [rid for rid in by if rid not in rids]
        for rid in gone:
            self._from_dec(rid)
        new = rids.difference(by)
        if new:
            for r in conn.execute(f"SELECT rowid, {_FROM_SEL}, chain, txhash FROM raw_txs WHERE rowid >= ?", (min(new),)):
                if r[0] in by or r[0] not in new:
                    continue
                self._from_inc(r[0], r[1] or "", _k(r[2], r[3]))
        if gone or new:
            self.dirty = True
        return self.from_cnt

    def drain(self):
        if self.from_by is None and self._from_new is None:
            self._from_bg(self.gen)

    @staticmethod
    def _mine_sig(fm) -> str:
        return hashlib.sha256("\n".join(sorted(str(a) for a in fm)).encode()).hexdigest()[:24]

    def _load(self, conn):
        t0 = time.time()
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            self.stats["load"] = "none"
            return
        except (OSError, ValueError) as e:
            log.warning("웹 raw_txs 캐시 파일 손상 — 무시하고 다시 계산: %s", e)
            self.stats["load"] = "corrupt"
            return
        if not isinstance(d, dict) or d.get("v") != FMT_V:
            self.stats["load"] = "version"
            return
        try:
            mx = self._log_max(conn)
            lv = d.get("logic") or {}
            seqs = [int(d.get(k9) or 0) for k9 in ("sig_seq", "infl_seq", "from_seq")]
            if max(seqs) > mx:
                log.info("웹 raw_txs 캐시가 원장 교체 기록보다 앞선다(원장 교체·복원) — 버림")
                self.stats["load"] = "ahead"
                return
            fp = d.get("db") or {}
            if fp.get("rid") is not None:
                r = conn.execute("SELECT chain, txhash FROM raw_txs WHERE rowid=?", (int(fp["rid"]),)).fetchone()
                if r is None or _k(r[0], r[1]) != fp.get("key"):
                    log.info("웹 raw_txs 캐시의 원장 지문 불일치 — 버림")
                    self.stats["load"] = "fingerprint"
                    return
            if lv.get("signer") == LOGIC_V["signer"] and isinstance(d.get("signer"), dict):
                self.signer = {tuple(k.split("|", 1)): (v[0], v[1], v[2]) for k, v in d["signer"].items()}
                self.sig_seq = seqs[0]
            else:
                self.sig_seq = mx
            if lv.get("infl") == LOGIC_V["infl"] and isinstance(d.get("infl"), dict) and d.get("infl_mine"):
                for k, v in d["infl"].items():
                    self._infl_put(tuple(k.split("|", 1)), list(v))
                self._infl_sig = d["infl_mine"]
                self.infl_seq = seqs[1]
            else:
                self.infl_seq = mx
            if lv.get("from") == LOGIC_V["from"] and isinstance(d.get("from"), dict):
                self._from_install(seqs[2], {int(rid): (v[0], v[1]) for rid, v in d["from"].items()})
            self.dirty = False
            self.saved_at = time.time()
            self.stats["load"] = f"ok {time.time() - t0:.2f}s"
            log.info("웹 raw_txs 캐시 불러옴: 서명자 %d · 유입 %d · 발신자 %s행 (%.2f초)", len(self.signer), len(self.infl),
                     len(self.from_by) if self.from_by is not None else "-", time.time() - t0)
        except Exception as e:
            log.warning("웹 raw_txs 캐시 불러오기 실패 — 다시 계산: %s", e)
            self._reset_all()
            self.stats["load"] = "error"

    def maybe_save(self, force=False) -> bool:
        if not (self.persist and self.tracking) or not self.dirty:
            return False
        if not force and self.saved_at and time.time() - self.saved_at < SAVE_EVERY:
            return False
        d = {"v": FMT_V, "logic": dict(LOGIC_V), "at": int(time.time()),
             "sig_seq": self.sig_seq, "infl_seq": self.infl_seq, "from_seq": self.from_seq if self.from_by is not None else 0,
             "db": dict(self._fp),
             "signer": {_k(*k): list(v) for k, v in self.signer.items()}}
        if self.infl_mine is not None:
            d["infl"] = {_k(*k): v for k, v in self.infl.items()}
            d["infl_mine"] = self._mine_sig(self.infl_mine)
        if self.from_by is not None:
            d["from"] = {str(rid): [f, ks] for rid, (f, ks) in self.from_by.items()}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError) as e:
            log.warning("웹 raw_txs 캐시 저장 실패(다음에 다시): %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        self.dirty = False
        self.saved_at = time.time()
        return True
