from __future__ import annotations
import bf_engine
import logs, statefile
import time
from sol_base import HL_COST
from sol_base import SLOTS_PER_EPOCH
from sol_base import SLOT_SEC_EST
from sol_base import STAKE_PROGRAM
from sol_base import STAKE_RWD_EPOCHS_PER_CYCLE
from sol_base import STAKE_RWD_MARGIN_SLOTS
from sol_base import STAKE_RWD_POLL_SEC
from sol_base import STAKE_WITHDRAWER_OFFSET
from sol_base import TX_BATCH_SLEEP
from sol_base import _hl_paced
from sol_base import stake_state
import logging

log = logging.getLogger('tj-sol')

AUTH_HEAL_DAYS = 3
AUTH_HEAL_MAX = 10
AUTH_HEAL_TRIES = 5


def stake_auth_moves(outer: list, inner_groups: list, keys: list, post: list, owners: set, stake_of: dict, err: bool = False) -> tuple:
    inner = {g.get("index"): g.get("instructions") or [] for g in inner_groups or [] if isinstance(g, dict)}
    seq = []
    for i, ins in enumerate(outer or []):
        seq += [ins] + list(inner.get(i) or [])
    last = {}
    for ins in seq:
        p = ins.get("parsed") if isinstance(ins, dict) and (ins.get("programId") == STAKE_PROGRAM or ins.get("program") == "stake") else None
        info = p.get("info") if isinstance(p, dict) and p.get("type") in ("authorize", "authorizeChecked") else None
        if not isinstance(info, dict) or info.get("authorityType") != "Withdrawer":
            continue
        s, a, n = info.get("stakeAccount"), info.get("authority"), info.get("newAuthority")
        if not (isinstance(s, str) and isinstance(a, str) and isinstance(n, str) and s and a and n):
            continue
        if s in last:
            last[s] = (last[s][0], n)
        elif a in owners and s in stake_of:
            last[s] = (a, n)
    deltas, auth = [], {}
    for s, (a, n) in ([] if err else last.items()):
        try:
            lam = int(post[keys.index(s)]) if n != a else 0
        except (ValueError, IndexError, TypeError):
            lam = 0
        if lam <= 0:
            continue
        to_mine = n in owners
        deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(-lam), "owner": f"{a}:stake:{s}"})
        if to_mine:
            deltas.append({"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(lam), "owner": f"{n}:stake:{s}"})
        auth[s] = {"from": a, "to": n, "mine": to_mine, "lamports": lam}
    return deltas, auth


def stake_live(ent: dict, slot: object, sig: object = None) -> bool:
    a = ent.get("away")
    if not (isinstance(a, int) and isinstance(slot, int)) or slot < a:
        return True
    return slot == a and (sig is None or not ent.get("away_sig") or sig == ent.get("away_sig"))


def stake_emit_prep(w: "StakeMixin", rec: dict) -> None:
    slot, sig = rec.get("slot"), rec.get("txhash")
    if rec.get("stake_new"):
        w._stake_note_tx(rec)
    reg = w.stake_reg()
    off = {s for s, e in reg.items() if not stake_live(e, slot, sig)}
    if off:
        rec["deltas"] = [d for d in rec.get("deltas") or [] if str(d.get("owner") or "").partition(":stake:")[2] not in off]
        for k in ("stake_pre", "stake_new"):
            if isinstance(rec.get(k), dict):
                rec[k] = {s: v for s, v in rec[k].items() if s not in off}
    own_auth = rec.get("stake_auth") if isinstance(rec.get("stake_auth"), dict) else {}
    for d in rec.get("deltas") or []:
        holder, _sep, acct = str(d.get("owner") or "").partition(":stake:")
        mv = own_auth.get(acct) if acct else None
        if isinstance(mv, dict) and mv.get("from"):
            moved_in = mv.get("mine") and holder == mv.get("to") and str(d.get("delta")) == str(mv.get("lamports"))
            if holder != mv["from"] and not moved_in:
                d["owner"] = f"{mv['from']}:stake:{acct}"
            continue
        ent = reg.get(acct) if acct else None
        if isinstance(ent, dict) and holder != ent.get("w") and _after_mark(ent.get("mv"), slot, sig):
            d["owner"] = f"{ent['w']}:stake:{acct}"
    for acct, mv in (rec.get("stake_auth") or {}).items():
        ent = reg.get(acct)
        if acct in off or not isinstance(ent, dict) or not isinstance(mv, dict) or not mv.get("to") or not isinstance(slot, int):
            continue
        last_mv = ent.get("mv") if isinstance(ent.get("mv"), list) else None
        older = (isinstance(ent.get("away"), int) and slot < ent["away"]) or (last_mv is not None and slot < last_mv[0])
        if mv.get("mine") and older:
            if last_mv is None or slot < last_mv[0]:
                ent["w0"] = mv.get("from") or ent.get("w0") or ent.get("w")
            continue
        if mv.get("mine"):
            ent.setdefault("w0", mv.get("from") or ent.get("w"))
            ent.update(w=mv["to"], mv=[int(slot), sig])
            ent.pop("away", None)
            ent.pop("away_sig", None)
        elif not older:
            ent.update(away=int(slot), away_sig=sig)
        log.warning("★스테이크 계정 %s 출금 권한 넘김 → %s(%s · %.4f SOL)★", acct[:8], str(mv["to"])[:8],
                    "내 지갑" if mv.get("mine") else "남", int(mv.get("lamports") or 0) / 1e9)


def _after_mark(mark: object, slot: object, sig: object) -> bool:
    return (isinstance(mark, list) and len(mark) == 2 and isinstance(mark[0], int) and isinstance(slot, int)
            and (slot > mark[0] or (slot == mark[0] and sig is not None and sig != mark[1])))


def stake_open_w(ent: dict) -> str:
    return ent.get("w0") or ent["w"]


def stake_auth_heal(w: "StakeMixin") -> int:
    n = 0
    changed = False
    for s, ent in w.stake_reg().items():
        if not ent.get("gone") or ent.get("auth_chk") or ent.get("away") is not None:
            continue
        if not w._stake_hl_ok(1 + AUTH_HEAL_MAX, "권한 넘김 확인"):
            break
        changed = True
        try:
            rec = _auth_heal_find(w, s, ent)
        except Exception as e:  # noqa: BLE001 [fallback]
            ent["auth_try"] = int(ent.get("auth_try") or 0) + 1
            log.info("스테이크 %s 권한 넘김 확인 실패 %d회(다음 주기): %s", s[:8], ent["auth_try"], logs.safe_err(e)[:120])
            if ent["auth_try"] < AUTH_HEAL_TRIES:
                break
            log.error("★스테이크 %s 권한 넘김 확인 %d회 실패 — 포기(원장 스테이크 칸이 남으면 잔고 대조가 알림)★", s[:8], ent["auth_try"])
            rec = None
        if rec is not None:
            rec["repersp"] = True
            try:
                stake_emit_prep(w, rec)
                w.writer.append(rec)
            except OSError as e:
                ent.pop("away", None)
                ent.pop("away_sig", None)
                log.warning("스테이크 %s 권한 넘김 다시 보내기 쓰기 실패(다음 주기): %s", s[:8], logs.safe_err(e)[:120])
                break
            w._stake_note_tx(rec)
            n += 1
            log.warning("★스테이크 %s 출금 권한 넘김 tx %s 다시 보냄(새 관점 — 스테이크 칸에서 나감)★", s[:8], str(rec.get("txhash"))[:12])
        ent["auth_chk"] = 1
        ent.pop("auth_try", None)
    if changed:
        statefile.atomic_write_json(w.cursor_path, w.cursor)
    return n


def _auth_heal_find(w: "StakeMixin", s: str, ent: dict):
    hi = int(ent["gone"]) + 1
    sigs = w._stake_sigs_between(s, max(int(ent.get("t0") or 0), hi - AUTH_HEAL_DAYS * 86400), hi)
    for sig in list(reversed(sigs))[:AUTH_HEAL_MAX]:
        rec = w.parse_tx(sig)
        if not isinstance(rec, dict):
            raise RuntimeError(f"스테이크 tx 파싱 실패 {sig[:10]}")
        if s in (rec.get("stake_auth") or {}):
            return rec
        time.sleep(TX_BATCH_SLEEP)
    return None


class StakeMixin:

    def stake_reg(self) -> dict:
        return {k[5:]: v for k, v in self.cursor.items() if k.startswith("_stk:") and isinstance(v, dict)}

    def _stake_t0(self) -> int:
        vals = [v for v in (self.cutoff_ts, bf_engine.SINCE.target("sol")) if v]
        return int(min(vals)) if vals else 0

    def _stake_hl_ok(self, need: int, what: str) -> bool:
        if not _hl_paced(self.rpc):
            return True
        room9 = bf_engine.HELIUS.room("head", proc=self.rpc.proc)
        if room9 >= need:
            return True
        self._stake_paced_at = time.time()
        if time.time() - float(getattr(self, "_stake_paced_log", 0) or 0) >= 1800:
            self._stake_paced_log = time.time()
            log.info("스테이킹 %s — 헬리우스 실시간 몫 대기(필요 %d · 지금 여유 %d) · 다음 주기에(실패 아님)", what, need, room9)
        return False

    def _stake_discover(self, force: bool = False) -> bool:
        if not self.stake_on:
            return False
        now = time.time()
        if not force and self._stake_disc_at and now - self._stake_disc_at < self.stake_every:
            return True
        if not force and now < getattr(self, "_stake_retry_at", 0):
            return False
        if not self._stake_hl_ok(int(HL_COST.get("getProgramAccounts", 10)) * len(self.owners), "계정 발견"):
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
        except Exception as e:  # noqa: BLE001 [fallback]
            self._stake_err = logs.safe_err(e)[:160]
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
            else:
                ent.pop("gone", None)
                ent.pop("away", None)
                ent.pop("away_sig", None)
                if ent.get("w") != v["w"]:
                    log.warning("★스테이크 계정 %s 출금권자 바뀜 %s → %s(내 지갑끼리)★", s[:8], str(ent.get("w"))[:8], v["w"][:8])
                    ent.setdefault("w0", ent.get("w"))
                    ent["w"] = v["w"]
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
        statefile.atomic_write_json(self.stake_path, self.stake_snap)
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        self._stake_disc_at = now
        self._stake_err = None
        return True

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
            if not self._stake_hl_ok(1 + len(addrs), "보상 조회"):
                break
            res = self.rpc.call("getInflationReward", [addrs, {"epoch": e, "commitment": "finalized"}])
            if not isinstance(res, list) or len(res) != len(addrs):
                raise RuntimeError(f"getInflationReward 응답 형식 오류(epoch {e})")
            for s, r in zip(addrs, res):
                ent = reg[s]
                if r and int(r.get("amount") or 0) > 0:
                    slot9 = int(r["effectiveSlot"])
                    bt = self._block_time(slot9)
                    if bt >= int(ent.get("t0") or 0) and stake_live(ent, slot9):
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
            statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            statefile.atomic_write_json(self.cursor_path, self.cursor)
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
        if not caught_up or self.cursor.get("_quarantine"):
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
                                "owner": f"{stake_open_w(ent)}:stake:{s}"}],
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": stake_open_w(ent), "lamports": lam,
                                   "first_slot": f[0] if f else None}})
                self.emitted.add(txh)
                log.info("★스테이크 기초잔고 %s %.6f SOL (창 %s)★", s[:8], lam / 1e9,
                         time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("t0") or 0))))
            ent["open"] = True
            if s in acc:
                acc[s]["ledger_ready"] = True
        statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
        statefile.atomic_write_json(self.cursor_path, self.cursor)
        if self.stake_snap:
            statefile.atomic_write_json(self.stake_path, self.stake_snap)

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
            if stop:
                return list(reversed(out))
            if len(res) < 1000:
                if not self._end_ok(res):
                    raise RuntimeError(f"스테이크 {s[:8]} 서명 — 폴백 RPC 의 짧은 페이지(이력 끝 미확인) · 다음 주기")
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
                if not self._stake_hl_ok(1, "기초잔고 재산정"):
                    break
                old_t0 = int(ent.get("t0") or 0)
                first = ent.get("first") if isinstance(ent.get("first"), list) else None
                n_emit = 0
                for sig in self._stake_sigs_between(s, tgt, old_t0):
                    rec = self.parse_tx(sig)
                    if not isinstance(rec, dict):
                        raise RuntimeError(f"스테이크 tx 파싱 실패 {sig[:10]}")
                    stake_emit_prep(self, rec)
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
                                 "owner": f"{stake_open_w(ent)}:stake:{s}"}] if lam > 0 else []),
                    "counterparties": [], "has_program": True, "err": False,
                    "stake_open": {"acct": s, "wallet": stake_open_w(ent), "lamports": lam, "first_slot": first[0] if first else None,
                                   "reopen": True, "t0": new_t0, "prev_t0": int(ent.get("reopen_from") or 0)}})
                self.emitted.add(txh)
            log.warning("★스테이크 기초잔고 재산정 %s: 창 %s → %s · %.6f SOL(과거 창 확장)★", s[:8],
                        time.strftime("%Y-%m-%d", time.gmtime(int(ent.get("reopen_from") or 0))),
                        time.strftime("%Y-%m-%d", time.gmtime(new_t0)), lam / 1e9)
            ent.pop("reopen_pending", None)
            ent.pop("reopen_from", None)
            changed = True
        if changed:
            statefile.write_json_if_changed(self.emitted_path, sorted(self.emitted))
            statefile.atomic_write_json(self.cursor_path, self.cursor)

    def _stake_cycle(self) -> None:
        if not self.stake_on:
            return
        hb = bf_engine.health("sol")
        stake_auth_heal(self)
        try:
            self._stake_reopen()
            caught = self._stake_rewards()
            self._stake_reopen(caught_up=caught)
            self._stake_open(caught)
            self._stake_err = None if self._stake_disc_at else self._stake_err
        except Exception as e:  # noqa: BLE001 [fallback]
            caught = False
            self._stake_err = logs.safe_err(e)[:160]
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
        pz9 = float(getattr(self, "_stake_paced_at", 0) or 0)
        if pz9 and now - pz9 <= 600:
            facts["paced_at"] = int(pz9)
        if not self._stake_err and pz9 and now - pz9 <= 600:
            hb.ok("sol_stake", "stake", **facts)
        elif self._stake_err or disc_age is None or disc_age > 3 * self.stake_every:
            hb.fail("sol_stake", RuntimeError(self._stake_err or "스테이크 계정 발견 스냅샷 오래됨"), "stake", **facts)
        else:
            hb.ok("sol_stake", "stake", **facts)
        hb.flush()
