import chain_event
import common
import json
import ledger_backup
import os
import sqlite3
import time
from core_common import dm
from inbox import SegmentReader
import logging
import calcguard

log = logging.getLogger('tj-core')


class InboxMixin:

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
                self._negabs_note(chain, txhash)
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
        elif rec.get("kind") == chain_event.KIND:
            self._consume_chain_delta(rec)
        elif rec.get("kind") == "ex_snapshot":
            self._consume_ex(rec)
        elif rec.get("kind") == "ex_fills":
            self._consume_fills(rec)
        elif rec.get("kind") == "ex_order_trades":
            self._consume_order_trades(rec)
        elif rec.get("kind") == "exf_fill_retime":
            self._consume_exf_retime(rec)
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
            calcguard.swallowed("core_inbox:InboxMixin.poison_replay_pass", e)
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
                calcguard.swallowed("core_inbox:InboxMixin.poison_replay_pass", e)
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
                    calcguard.swallowed("core_inbox:InboxMixin._drain_stream", dm_err)
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
            calcguard.swallowed("core_inbox:InboxMixin._ts_fix_done", e)
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
