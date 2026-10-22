#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, envfile, logs, paths  # noqa: E402
import bf_engine  # noqa: E402
import address_codec as ac  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state  # noqa: E402
import chain_watch  # noqa: E402

CHAIN = "tron"
PARSER_VERSION = 1
API_DEFAULT = "https://api.trongrid.io"
PROVIDER = "trongrid"
PAGE_LIMIT = 200
CONST_REJECT_CODES = ("CONTRACT_VALIDATE_ERROR", "CONTRACT_EXE_ERROR", "REVERT")
META_NEG_SEC = 6 * 3600
LAG_MS = 3 * 60 * 1000
OVERLAP_MS = 10 * 60 * 1000
QUIET_MS = 60 * 1000
FP_FAIL_MAX = 3
HINT_TOKEN_CAP = 30
KEYLESS_RPS = 0.8
KEYED_RPS = 4.0
KEYED_DAY = 100_000
DAY_PCT = 80
HEAD_RESERVE_PCT = 25
LISTS = ("tx", "trc20", "internal")
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
NAT = {"kind": "native"}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_KEY = re.compile(r"41[0-9a-f]{40}")
OFFICIAL_SYMBOL = {"USDT": {"41a614f803b6fd780986a42c78ec9c7f77e6ded13c"}, "TRX": set()}
STAKE_OUT = {"FreezeBalanceV2Contract": "frozen_balance", "FreezeBalanceContract": "frozen_balance"}
STAKE_IN = {"UnfreezeBalanceContract": "unfreeze_amount", "UnfreezeBalanceV2Contract": "withdraw_expire_amount",
            "WithdrawExpireUnfreezeContract": "withdraw_expire_amount", "CancelAllUnfreezeV2Contract": "withdraw_expire_amount",
            "WithdrawBalanceContract": "withdraw_amount"}
NO_BALANCE = {"DelegateResourceContract", "UnDelegateResourceContract", "VoteWitnessContract", "AccountUpdateContract",
              "AccountPermissionUpdateContract", "AccountCreateContract", "SetAccountIdContract", "UpdateSettingContract",
              "UpdateEnergyLimitContract", "ClearABIContract", "UpdateBrokerageContract"}
STAKE_NOOP = {"DelegateResourceContract", "UnDelegateResourceContract", "VoteWitnessContract"}


class TronAdapter(reg.ChainAdapter):
    chain = CHAIN
    RATE_PAUSE = 6.0

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        t = ((cfg or {}).get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) if isinstance((cfg or {}).get(reg.CFG_CHAIN_KEY), dict) else None
        self.opts = t if isinstance(t, dict) else {}
        base = str(self.opts.get("api") or API_DEFAULT).strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", base):
            raise ValueError("nonevm.tron.api 는 http(s)://호스트[:포트] 꼴이어야 해요")
        self.base = base
        self.key = os.environ.get(self.spec.key_env or "", "") or envfile.read_env_file().get(self.spec.key_env or "", "")
        rps = self.opts.get("rps")
        try:
            rps = float(rps) if rps is not None else (KEYED_RPS if self.key else KEYLESS_RPS)
        except (TypeError, ValueError):
            rps = KEYED_RPS if self.key else KEYLESS_RPS
        self.rps = min(1000.0, max(0.05, rps))
        self.timeout = float(self.opts.get("timeout_sec") or 25)
        self.meter, self.day_budget = None, None
        if self.key:
            try:
                lim = int(self.opts.get("daily_limit") or KEYED_DAY)
            except (TypeError, ValueError):
                lim = KEYED_DAY
            self.day_budget = max(1, lim * DAY_PCT // 100)
            self.meter = bf_engine.DayMeter("rpc_day_trongrid", self.day_budget, burst=1.0, keep=0.0)
        self._lock = threading.Lock()
        self._next_ok = 0.0
        self._pause_until = 0.0
        self.meta = {}
        self._meta_neg = {}
        self._dec_bad = {}
        self.state = None
        self._fp_fail = {}
        self.calls = 0

    def _pace(self):
        with self._lock:
            now = time.monotonic()
            wait = max(self._next_ok - now, self._pause_until - now, 0.0)
            self._next_ok = max(now, self._next_ok, self._pause_until) + 1.0 / self.rps
        if wait > 0:
            time.sleep(wait)

    def _call(self, path: str, payload=None, params=None, kind: str = "head"):
        if self.meter is not None:
            lim = self.day_budget - self.day_budget * HEAD_RESERVE_PCT // 100 if kind == "history" else self.day_budget
            if not self.meter.take("tj-" + CHAIN, 1, kind=("fill" if kind == "history" else "head"), limit=lim):
                raise chain_watch.Transient("TronGrid 하루 몫(공표 한도 80%) 소진 또는 장부 오류 — UTC 자정 뒤 이어서"
                                            + (" · 과거 백필 몫 끝(최신 몫은 남김)" if kind == "history" else ""))
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        hdr = {"TRON-PRO-API-KEY": self.key} if self.key else {}
        self._pace()
        self.calls += 1
        try:
            d, _h = bf_engine.http_request(url, data=None if payload is None else json.dumps(payload).encode(), headers=hdr,
                                           timeout=self.timeout, retries=1, prio=("bg" if kind == "history" else "fg"),
                                           max_inline_wait=8.0)
        except bf_engine.NetError as e:
            if e.kind in ("http429", "quota"):
                self._pause(self.RATE_PAUSE if e.retry_after is None else min(60.0, float(e.retry_after) + 1))
            raise chain_watch.Transient(f"TronGrid {e.kind}: {logs.safe_err(e)[:120]}") from None
        if not isinstance(d, dict):
            raise chain_watch.Transient("TronGrid 응답이 객체가 아님")
        err = d.get("Error") if "Error" in d else d.get("error")
        if err:
            s = logs.redact_secret_text(str(err))
            if "exceeded" in s or "suspend" in s:
                self._pause(self.RATE_PAUSE)
            raise chain_watch.Transient("TronGrid 거절: " + s[:120])
        return d

    def _pause(self, sec: float):
        with self._lock:
            self._pause_until = max(self._pause_until, time.monotonic() + float(sec))

    def canonical_txid(self, text):
        t = str(text or "").strip().lower()
        if not _HEX64.fullmatch(t):
            raise ValueError("Tron txid 는 16진수 64자예요")
        return t

    @staticmethod
    def _k(v):
        s = str(v or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", s):
            s = "41" + s
        try:
            return ac.tron_key(s)
        except ValueError:
            return None

    @staticmethod
    def _int(v, what):
        if isinstance(v, bool):
            raise chain_watch.Transient(f"{what} 형식 오류")
        if isinstance(v, int):
            return v
        if isinstance(v, str) and re.fullmatch(r"\d{1,80}", v):
            return int(v)
        raise chain_watch.Transient(f"{what} 형식 오류")

    def requested_from_ms(self, now: float = None) -> int:
        cfg = self.cfg or {}
        months = 0.0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 0)
        if months <= 0:
            return 0
        now = time.time() if now is None else now
        vals = [int(now - months * 30 * 86400)]
        for sec in (None, CHAIN):
            try:
                v = bf_engine.SINCE.target(sec)
            except Exception:   # noqa: BLE001 [fallback]
                v = None
            if v:
                vals.append(int(v))
        return max(0, min(vals)) * 1000

    def _lane_safe(self, owner: str, lane: str) -> dict:
        if self.state is None:
            return {}
        s = (self.state.d["lanes"].get(f"{lane}:{owner}") or {}).get("safe")
        return dict(s) if isinstance(s, dict) else {}

    def _set_safe(self, owner: str, lane: str, safe: dict) -> None:
        if self.state is not None:
            self.state.d["lanes"].setdefault(f"{lane}:{owner}", {})["safe"] = dict(safe)

    def _ensure_init(self, owner: str, now_ms: int):
        if self._lane_safe(owner, "latest").get("t") is None:
            t0 = int(now_ms - LAG_MS)
            self._set_safe(owner, "latest", {"t": t0})
            if self._lane_safe(owner, "history").get("t0") is None:
                self._set_safe(owner, "history", {"t0": t0})

    def discovery_query(self, owner, lane):
        now_ms = int(time.time() * 1000)
        self._ensure_init(owner, now_ms)
        if lane == "latest":
            t = self._lane_safe(owner, "latest").get("t")
            lo = int(t - OVERLAP_MS) if t is not None else int(now_ms - 3600_000)
            q = {"lane": "latest", "lo": max(0, lo), "hi": None}
        else:
            hs = self._lane_safe(owner, "history")
            req = self.requested_from_ms()
            t0 = int(hs.get("t0") or now_ms)
            act = hs.get("q") if isinstance(hs.get("q"), dict) else None
            if act is not None and act.get("lo") is not None and req >= int(act["lo"]):
                q = {"lane": "history", "lo": int(act["lo"]), "hi": act.get("hi")}
            elif hs.get("done") and req >= int(hs.get("from", req)):
                q = {"lane": "history", "done": True}
            elif hs.get("done"):
                q = {"lane": "history", "lo": req, "hi": int(hs["from"]) + OVERLAP_MS}
            else:
                q = {"lane": "history", "lo": req, "hi": t0 + OVERLAP_MS}
            if not q.get("done") and self.state is not None:
                hs["q"] = {"lo": q["lo"], "hi": q["hi"]}
                self._set_safe(owner, "history", hs)
        q.update({"limit": PAGE_LIMIT, "order": "block_timestamp,asc", "confirmed": True, "v": PARSER_VERSION})
        fp = hashlib.sha256(json.dumps([PROVIDER, self.base, owner, q], sort_keys=True).encode()).hexdigest()[:16]
        return q, fp

    def _list_path(self, owner: str, lst: str) -> str:
        a = ac.tron_display(owner)
        return {"tx": f"/v1/accounts/{a}/transactions", "trc20": f"/v1/accounts/{a}/transactions/trc20",
                "internal": f"/v1/accounts/{a}/internal-transactions"}[lst]

    def _list_params(self, lo, hi, fp=None, confirmed=True, limit=PAGE_LIMIT, order="block_timestamp,asc"):
        p = {"only_confirmed": "true" if confirmed else "false", "limit": str(limit), "order_by": order, "min_timestamp": str(int(lo))}
        if hi is not None:
            p["max_timestamp"] = str(int(hi))
        if fp:
            p["fingerprint"] = fp
        return p

    def discover_page(self, owner, query, cursor):
        if query.get("done"):
            return [], None
        cur = dict(cursor) if isinstance(cursor, dict) else {}
        li = int(cur.get("l") or 0)
        if not 0 <= li < len(LISTS):
            li, cur = 0, {}
        start = int(cur.get("start") or time.time() * 1000)
        lo = int(cur["lo"]) if cur.get("lo") is not None else int(query["lo"])
        tfp = cur.get("fp")
        mx = int(cur.get("mx") or lo)
        lane = query.get("lane") or "latest"
        fkey = (owner, lane, li, tfp)
        if tfp and self._fp_fail.get(fkey, 0) >= FP_FAIL_MAX:
            self._fp_fail.pop(fkey, None)
            tfp, lo = None, mx
        lst = LISTS[li]
        try:
            d = self._call(self._list_path(owner, lst), params=self._list_params(lo, query.get("hi"), tfp), kind=lane)
        except chain_watch.Transient:
            if tfp:
                self._fp_fail[fkey] = self._fp_fail.get(fkey, 0) + 1
            raise
        self._fp_fail.pop(fkey, None)
        rows, meta = d.get("data"), d.get("meta")
        if d.get("success") is not True or not isinstance(rows, list) or not isinstance(meta, dict):
            raise chain_watch.Transient(f"TronGrid {lst} 목록 응답 형식 오류(success·data·meta)")
        items = []
        for r in rows:
            it, ts = self._row(owner, lst, r)
            mx = max(mx, ts)
            if it:
                items.append(it)
        nfp = meta.get("fingerprint")
        if nfp:
            nxt = {"l": li, "fp": str(nfp), "lo": lo, "mx": mx, "start": start}
        elif len(rows) >= PAGE_LIMIT:
            if mx <= lo:
                raise chain_watch.Transient(f"TronGrid {lst}: 같은 시각 {PAGE_LIMIT}건 넘음 — 다음 쪽 없이 진행 불가(다시 시도)")
            nxt = {"l": li, "fp": None, "lo": mx, "mx": mx, "start": start}
        elif li + 1 < len(LISTS):
            nxt = {"l": li + 1, "fp": None, "lo": None, "mx": None, "start": start}
        else:
            nxt = None
            self._pass_done(owner, query, start)
        return items, nxt

    def _row(self, owner: str, lst: str, r) -> tuple:
        if not isinstance(r, dict):
            raise chain_watch.Transient("TronGrid 목록 행 형식 오류")
        if lst == "tx":
            txid, ts = r.get("txID"), r.get("block_timestamp")
        elif lst == "trc20":
            txid, ts = r.get("transaction_id"), r.get("block_timestamp")
        else:
            txid, ts = r.get("tx_id"), r.get("block_timestamp")
        if not isinstance(txid, str) or not _HEX64.fullmatch(txid.lower()) or isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
            raise chain_watch.Transient("TronGrid 목록 행에 txid·시각 없음")
        txid = txid.lower()
        keep = False
        if lst == "tx":
            try:
                c0 = r["raw_data"]["contract"][0]
                v = c0["parameter"]["value"]
                typ = c0.get("type")
            except (KeyError, IndexError, TypeError):
                raise chain_watch.Transient("TronGrid 거래 행 본문(raw_data) 없음") from None
            sender = self._k(v.get("owner_address"))
            if sender == owner:
                keep = True
            elif typ == "TransferContract" and self._k(v.get("to_address")) == owner and self._int(v.get("amount") or 0, "amount") > 0:
                keep = True
            else:
                self._note(owner, "skip_in:" + str(typ)[:40], ts)
        elif lst == "trc20":
            ti = r.get("token_info") if isinstance(r.get("token_info"), dict) else {}
            tk = self._k(ti.get("address"))
            if tk and tk not in self.meta:
                dec = ti.get("decimals")
                dec = dec if isinstance(dec, int) and not isinstance(dec, bool) and 0 <= dec <= 77 else None
                if dec is not None:
                    self.meta[tk] = (_clean_sym(ti.get("symbol")), dec)
            val = str(r.get("value") or "0")
            if r.get("type") == "Transfer" and val.isdigit() and int(val) > 0 and owner in (self._k(r.get("from")), self._k(r.get("to"))):
                keep = True
        else:
            dat = r.get("data") if isinstance(r.get("data"), dict) else {}
            cv = dat.get("call_value") if isinstance(dat.get("call_value"), dict) else {}
            trx = cv.get("_")
            if not dat.get("rejected") and owner in (self._k(r.get("from_address")), self._k(r.get("to_address"))):
                if isinstance(trx, int) and not isinstance(trx, bool) and trx > 0:
                    keep = True
                elif any(k != "_" for k in cv):
                    self._note(owner, "trc10_internal", ts)
        return ({"stable_id": txid, "ts": ts // 1000, "src": lst} if keep else None), ts

    def _note(self, owner: str, what: str, ts: int):
        if self.state is None:
            return
        sc = self.state.d.setdefault("tron_scope", {}).setdefault(owner, {})
        e = sc.get(what) if isinstance(sc.get(what), dict) else {"n": 0, "t": 0}
        if ts > int(e.get("t") or 0):
            sc[what] = {"n": int(e.get("n") or 0) + 1, "t": int(ts)}

    def _pass_done(self, owner: str, query: dict, start: int):
        if self.state is None:
            return
        if query.get("lane") == "latest":
            t = int(start - LAG_MS)
            old = self._lane_safe(owner, "latest").get("t")
            self._set_safe(owner, "latest", {"t": max(t, int(old)) if old is not None else t})
            hs = self._lane_safe(owner, "history")
            st = {"scanned_through": t // 1000}
            if hs.get("done"):
                st["details_complete_through"] = t // 1000
            self.state.set_status(owner, **st)
        else:
            hs = self._lane_safe(owner, "history")
            frm = int(query.get("lo") or 0)
            hs.pop("q", None)
            hs.update({"done": True, "from": frm})
            self._set_safe(owner, "history", hs)
            lt = self._lane_safe(owner, "latest").get("t")
            self.state.set_status(owner, requested_from=frm // 1000, available_from=frm // 1000,
                                  details_complete_through=(int(lt) if lt is not None else int(hs.get("t0") or start)) // 1000)

    def token_meta(self, tk: str, kind: str = "head"):
        if tk in self.meta:
            m9 = self.meta[tk]
            if m9[1] is not None or time.time() - self._meta_neg.get(tk, 0) < META_NEG_SEC:
                return m9
        dec = self._const(tk, "decimals()", "", kind=kind)
        sym = self._const(tk, "symbol()", "", kind=kind)
        d = None
        if dec is not None and len(dec) == 64:
            v = int(dec, 16)
            d = v if v <= 77 else None
        s = _abi_str(sym) if sym is not None else None
        self.meta[tk] = (_clean_sym(s), d)
        if d is None:
            self._meta_neg[tk] = time.time()
            self._dec_bad[tk] = self._dec_bad.get(tk, 0) + 1
        else:
            self._dec_bad.pop(tk, None)
        return self.meta[tk]

    def dec_invalid(self, tk: str) -> bool:
        return self._dec_bad.get(tk, 0) >= 2 and (self.meta.get(tk) or (None, None))[1] is None

    def _const(self, contract: str, selector: str, param: str, owner: str = None, kind: str = "head"):
        d = self._call("/walletsolidity/triggerconstantcontract",
                       {"owner_address": owner or "41" + "0" * 40, "contract_address": contract, "function_selector": selector,
                        "parameter": param}, kind=kind)
        res = d.get("result")
        if not isinstance(res, dict):
            raise chain_watch.Transient("상수 호출 result 없음 — 다시 조회")
        if res.get("result") is not True:
            if res.get("code") in CONST_REJECT_CODES:
                return None
            raise chain_watch.Transient("상수 호출 거부 원인 미확인 — 다시 조회")
        cr = d.get("constant_result")
        if not isinstance(cr, list) or (cr and (not isinstance(cr[0], str) or not re.fullmatch(r"[0-9a-fA-F]*", cr[0]))):
            raise chain_watch.Transient("상수 호출 constant_result 형식 오류 — 다시 조회")
        return cr[0].lower() if cr else None

    def fetch_and_normalize(self, ref, owners):
        txid = self.canonical_txid((ref or {}).get("stable_id"))
        mine = set(owners or ())
        kind = "history" if (ref or {}).get("lane") == "history" else "latest"
        body = self._call("/walletsolidity/gettransactionbyid", {"value": txid}, kind=kind)
        if not body:
            return None
        if str(body.get("txID") or "").lower() != txid:
            raise chain_watch.Transient("본문 응답의 txID 가 다름")
        info = self._call("/walletsolidity/gettransactioninfobyid", {"value": txid}, kind=kind)
        if not info:
            return None
        if str(info.get("id") or "").lower() != txid:
            raise chain_watch.Transient("영수증 응답의 id 가 다름")
        blk, bts = info.get("blockNumber"), info.get("blockTimeStamp")
        if isinstance(blk, bool) or not isinstance(blk, int) or blk <= 0 or isinstance(bts, bool) or not isinstance(bts, int) or bts <= 0:
            return None
        try:
            cons = body["raw_data"]["contract"]
            c0 = cons[0]
            ctype = str(c0.get("type") or "")
            val = c0["parameter"]["value"]
        except (KeyError, IndexError, TypeError):
            raise chain_watch.Transient("본문 raw_data.contract 형식 오류") from None
        if not isinstance(val, dict):
            raise chain_watch.Transient("본문 계약 값 형식 오류")
        sender = self._k(val.get("owner_address"))
        if sender is None:
            raise chain_watch.Transient("보낸 주소(owner_address) 해석 불가")
        ret = (body.get("ret") or [{}])
        cret = (ret[0] or {}).get("contractRet") if isinstance(ret, list) and ret and isinstance(ret[0], dict) else None
        rres = (info.get("receipt") or {}).get("result") if isinstance(info.get("receipt"), dict) else None
        failed = (cret not in (None, "SUCCESS", "DEFAULT")) or info.get("result") == "FAILED" or (rres not in (None, "SUCCESS", "DEFAULT"))
        fee = self._int(info.get("fee") or 0, "fee")
        D = {}
        moves, reasons, spam = [], [], []
        hint = "transfer"
        stake = None

        def add(o, ak, v):
            if o in mine and v:
                D[(o, ak)] = D.get((o, ak), 0) + v

        def mv(mid, ak, f, t, amt):
            if amt > 0 and (f in mine or t in mine):
                moves.append({"id": mid, "asset": _asset_dict(ak, self), "from": f, "to": t, "amount_base": str(amt)})

        NATK = ("native", None)
        fees = []
        if sender in mine and fee:
            add(sender, NATK, -fee)
            fees.append({"payer": sender, "asset": dict(NAT), "amount_base": str(fee), "component": "network_fee", "included_in_deltas": True})
        if len(cons) > 1:
            reasons.append("multi_contract")
        if not failed:
            if ctype == "TransferContract":
                amt = self._int(val.get("amount") or 0, "amount")
                to = self._k(val.get("to_address"))
                if to is None:
                    raise chain_watch.Transient("받는 주소 해석 불가")
                add(sender, NATK, -amt)
                add(to, NATK, amt)
                mv("c0", NATK, sender, to, amt)
            elif ctype in ("TriggerSmartContract", "CreateSmartContract"):
                if ctype == "CreateSmartContract":
                    nc = val.get("new_contract") if isinstance(val.get("new_contract"), dict) else {}
                    cv = self._int(nc.get("call_value") or 0, "call_value")
                    target = self._k(info.get("contract_address"))
                else:
                    cv = self._int(val.get("call_value") or 0, "call_value")
                    target = self._k(val.get("contract_address"))
                if cv:
                    if target is None:
                        raise chain_watch.Transient("컨트랙트 주소 해석 불가")
                    add(sender, NATK, -cv)
                    add(target, NATK, cv)
                    mv("c0", NATK, sender, target, cv)
                if val.get("call_token_value") and val.get("token_id"):
                    reasons.append("trc10_call_value")
                for i, it in enumerate(info.get("internal_transactions") or []):
                    if not isinstance(it, dict):
                        raise chain_watch.Transient("내부 이동 형식 오류")
                    if it.get("rejected"):
                        continue
                    f, t = self._k(it.get("caller_address")), self._k(it.get("transferTo_address"))
                    for cvi in it.get("callValueInfo") or []:
                        if not isinstance(cvi, dict) or not cvi.get("callValue"):
                            continue
                        if cvi.get("tokenId") is not None:
                            reasons.append("trc10_internal")
                            continue
                        amt = self._int(cvi.get("callValue"), "callValue")
                        if f is None or t is None:
                            raise chain_watch.Transient("내부 이동 주소 해석 불가")
                        if f == sender:
                            continue
                        add(f, NATK, -amt)
                        add(t, NATK, amt)
                        mv(f"i{i}", NATK, f, t, amt)
                for i, lg in enumerate(info.get("log") or []):
                    if not isinstance(lg, dict):
                        raise chain_watch.Transient("로그 형식 오류")
                    tp = lg.get("topics") or []
                    dat = str(lg.get("data") or "")
                    if len(tp) != 3 or str(tp[0]).lower() != TRANSFER_TOPIC or not re.fullmatch(r"[0-9a-fA-F]{64}", dat):
                        continue
                    tok = self._k(lg.get("address"))
                    f, t = self._k(str(tp[1])[-40:]), self._k(str(tp[2])[-40:])
                    amt = int(dat, 16)
                    if tok is None or f is None or t is None or not amt:
                        continue
                    akt = ("token", tok)
                    if f in mine or t in mine:
                        self.token_meta(tok, kind=kind)
                    add(f, akt, -amt)
                    add(t, akt, amt)
                    mv(f"l{i}", akt, f, t, amt)
                    if f in mine and sender not in mine:
                        spam.append("unsigned_outflow")
            elif ctype in STAKE_OUT:
                amt = self._int(val.get(STAKE_OUT[ctype]) or 0, STAKE_OUT[ctype])
                add(sender, NATK, -amt)
                hint = "stake"
                stake = {"op": "freeze", "resource": str(val.get("resource") or "BANDWIDTH")[:20], "amount": str(amt)}
            elif ctype in STAKE_IN:
                amt = self._int(info.get(STAKE_IN[ctype]) or 0, STAKE_IN[ctype])
                add(sender, NATK, amt)
                hint = "stake"
                stake = {"op": "reward_withdraw" if ctype == "WithdrawBalanceContract" else "unstake", "amount": str(amt)}
            elif ctype in NO_BALANCE:
                if ctype in STAKE_NOOP:
                    hint = "stake"
                    stake = {"op": {"DelegateResourceContract": "delegate", "UnDelegateResourceContract": "undelegate"}.get(ctype, "vote")}
            elif ctype == "TransferAssetContract" or ctype == "ParticipateAssetIssueContract":
                reasons.append("trc10_unsupported")
                hint = "unknown"
                if ctype == "ParticipateAssetIssueContract":
                    amt = self._int(val.get("amount") or 0, "amount")
                    to = self._k(val.get("to_address"))
                    add(sender, NATK, -amt)
                    add(to, NATK, amt)
            else:
                reasons.append("unsupported_contract:" + ctype[:48])
                hint = "unknown"
        D = {k: v for k, v in D.items() if v}
        bad_tokens = {ak[1] for (_o, ak) in D if ak[0] == "token" and self.dec_invalid(ak[1])}
        if bad_tokens:
            D = {k: v for k, v in D.items() if not (k[1][0] == "token" and k[1][1] in bad_tokens)}
            moves = [mv_ for mv_ in moves if not ((mv_.get("asset") or {}).get("kind") == "token" and (mv_.get("asset") or {}).get("id") in bad_tokens)]
            reasons.append("token_decimals_invalid_skipped")
        if hint == "transfer" and not failed and sender in mine and ctype in ("TriggerSmartContract", "CreateSmartContract"):
            tot = {}
            for (o, ak), v in D.items():
                tot[ak] = tot.get(ak, 0) + v
            if fee:
                tot[NATK] = tot.get(NATK, 0) + fee
            outs = {ak for ak, v in tot.items() if v < 0}
            ins = {ak for ak, v in tot.items() if v > 0}
            if outs and ins:
                hint = "unknown"
            elif ins:
                hint = "program_in"
        for (o, ak), v in D.items():
            if ak[0] == "token" and _impersonates((self.meta.get(ak[1]) or (None, None))[0], ak[1]):
                spam.append("symbol_impersonation")
        involved = {o for (o, _a) in D} | ({sender} if sender in mine else set())
        own = (ref or {}).get("owner")
        if own in mine:
            involved.add(own)
        if not involved:
            involved = {sorted(mine)[0]} if mine else set()
        rec = {
            "v": chain_event.VERSION, "kind": chain_event.KIND, "chain": CHAIN, "network": "mainnet",
            "tx_uid": txid, "txhash": txid, "ts": bts // 1000,
            "order": {"height": blk, "checkpoint": None, "lt": None, "index": 0},
            "finality": {"state": "finalized", "blockhash": None, "evidence": "solidified"},
            "execution": {"state": "failed" if failed else "success", "trace_complete": True},
            "owners": sorted(involved), "ownership_version": _ov(mine),
            "deltas": [{"owner": o, "asset": _asset_dict(ak, self), "delta_base": str(v)}
                       for (o, ak), v in sorted(D.items(), key=lambda kv: (kv[0][0], kv[0][1][0], kv[0][1][1] or ""))],
            "fees": fees, "movements": moves,
            "classification": dict({"hint": hint, "trusted": False, "evidence": "trongrid:" + ctype[:48]},
                                   **({"spam": {"suspect": True, "why": sorted(set(spam))}} if spam else {})),
            "completeness": {"history": True, "details": True, "balances": True, "reasons": sorted(set(reasons))},
            "source": {"provider": PROVIDER, "parser_version": PARSER_VERSION, "observed_at": int(time.time()),
                       "payload_digest": chain_event.payload_digest({"raw": body.get("raw_data_hex") or body.get("raw_data"), "info": info})},
            "tron": {"type": ctype[:48], "sender": sender, "fee_sun": str(fee), "contract_ret": cret,
                     "resource": {k: info["receipt"].get(k) for k in ("energy_usage_total", "energy_fee", "net_usage", "net_fee",
                                                                     "origin_energy_usage", "energy_usage")
                                  if isinstance(info.get("receipt"), dict) and isinstance(info["receipt"].get(k), int)},
                     **({"stake": stake} if stake else {})},
        }
        return rec

    def _head(self):
        d = self._call("/walletsolidity/getblock", {"detail": False})
        try:
            rd = d["block_header"]["raw_data"]
            num, ts, bid = rd["number"], rd["timestamp"], str(d["blockID"])
        except (KeyError, TypeError):
            raise chain_watch.Transient("확정 머리(getblock) 응답 형식 오류") from None
        if isinstance(num, bool) or not isinstance(num, int) or num <= 0 or isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
            raise chain_watch.Transient("확정 머리 높이·시각 형식 오류")
        return num, ts, bid

    def _busy_since(self, owner: str, since_ms: int) -> bool:
        n = 20
        for lst in LISTS:
            d = self._call(self._list_path(owner, lst), params=self._list_params(since_ms, None, confirmed=False, limit=n))
            rows = d.get("data")
            if d.get("success") is not True or not isinstance(rows, list):
                raise chain_watch.Transient("조용함 확인 목록 응답 형식 오류")
            if len(rows) >= n or any(self._row(owner, lst, r)[0] for r in rows):
                return True
        return False

    def fetch_balances(self, owners, boundary, tokens=None):
        if boundary is not None:
            raise ValueError("TronGrid 는 과거 블록 잔고를 주지 않아요 — 최신 잔고를 과거 경계처럼 쓰지 않음")
        owners = set(owners or ())
        tokens = tokens or {}
        h1 = self._head()
        per, unobs, locked, meta = {}, {}, {}, {}
        dec_unknown = False
        for o in sorted(owners):
            acct = self._call("/walletsolidity/getaccount", {"address": o})
            hints = []
            v1 = self._call(f"/v1/accounts/{ac.tron_display(o)}", params={"only_confirmed": "true"})
            if v1.get("success") is not True or not isinstance(v1.get("data"), list):
                raise chain_watch.Transient("계정 목록(v1) 응답 형식 오류")
            if not acct:
                if v1["data"]:
                    raise chain_watch.Transient("확정 계정 응답이 비었는데 계정 목록엔 있음 — 다시")
                native = 0
            else:
                if self._k(acct.get("address")) != o:
                    raise chain_watch.Transient("확정 계정 응답 주소가 다름")
                native = self._int(acct.get("balance") or 0, "balance")
                fz = sum(self._int((x or {}).get("amount") or 0, "frozenV2") for x in acct.get("frozenV2") or [] if isinstance(x, dict))
                fz += sum(self._int((x or {}).get("frozen_balance") or 0, "frozen") for x in acct.get("frozen") or [] if isinstance(x, dict))
                uf = sum(self._int((x or {}).get("unfreeze_amount") or 0, "unfrozenV2") for x in acct.get("unfrozenV2") or [] if isinstance(x, dict))
                if fz or uf:
                    locked[o] = {"frozen": str(fz), "unfreezing": str(uf)}
            if v1["data"]:
                for m in (v1["data"][0] or {}).get("trc20") or []:
                    if isinstance(m, dict):
                        for ca, amt in m.items():
                            k9 = self._k(ca)
                            if k9 and k9 not in hints and str(amt).isdigit() and int(str(amt)) > 0:
                                hints.append(k9)
            ledger = list(dict.fromkeys(list(tokens.get(o) or [])))
            extra = [t for t in hints if t not in ledger]
            unobs[o] = [t for t in extra[HINT_TOKEN_CAP:]]
            want = ledger + extra[:HINT_TOKEN_CAP]
            wb = {("native", None): native}
            for tk in want:
                if not _KEY.fullmatch(str(tk)):
                    unobs[o].append(str(tk))
                    continue
                r = self._const(tk, "balanceOf(address)", "0" * 24 + o[2:], owner=o)
                if r is None or len(r) != 64:
                    unobs[o].append(tk)
                    continue
                if tk not in ledger:
                    m9 = self.token_meta(tk)
                    if m9[1] is None:
                        if int(r, 16) > 0:
                            unobs[o].append(tk)
                            dec_unknown = dec_unknown or not self.dec_invalid(tk)
                        continue
                    meta[tk] = (m9[0], m9[1])
                elif tk in self.meta:
                    m9 = self.token_meta(tk)
                    meta[tk] = (m9[0], m9[1])
                wb[("token", tk)] = int(r, 16)
            per[o] = wb
        h2 = self._head()
        busy = any(self._busy_since(o, h1[1] - QUIET_MS) for o in sorted(owners))
        why = (["읽는 동안 내 거래가 있음 — 같은 시점이 아닐 수 있어 자동 보정 보류"] if busy else []) \
            + (["새 토큰 자릿수 미확인(decimals 거부) — 기초 잔고 보류(18 로 짐작하지 않음)"] if dec_unknown else [])
        return {"per_wallet": per, "_meta": meta,
                "_boundary": {"kind": "height", "value": str(h2[0]), "hash": h2[2], "ts": h2[1] // 1000},
                "_complete": not busy and not dec_unknown, "_unobserved": {o: v for o, v in unobs.items() if v}, "_source": PROVIDER,
                "_ownership_version": _ov(owners), "_locked": locked, "_why": why}


def _ov(owners) -> str:
    return hashlib.sha256(("|".join(sorted(owners or ()))).encode()).hexdigest()[:16]


def _asset_dict(ak, ad) -> dict:
    if ak[0] == "native":
        return {"kind": "native"}
    sym, dec = ad.meta.get(ak[1]) or (None, None)
    return {"kind": "token", "id": ak[1], "symbol": sym, "decimals": dec}


def _clean_sym(s):
    if not isinstance(s, str):
        return None
    t = "".join(ch for ch in s if ch.isprintable() and ch not in "​‌‍⁠﻿").strip()
    return t[:32] or None


def _abi_str(h: str):
    try:
        b = bytes.fromhex(h)
    except ValueError:
        return None
    if len(b) >= 64:
        off = int.from_bytes(b[:32], "big")
        if off + 32 <= len(b):
            ln = int.from_bytes(b[off:off + 32], "big")
            if off + 32 + ln <= len(b) and ln <= 256:
                return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    if len(b) == 32:
        return b.rstrip(b"\0").decode("utf-8", "replace")
    return None


def _impersonates(sym, tk) -> bool:
    if not sym:
        return False
    s = re.sub(r"[^A-Z0-9]", "", sym.upper())
    return s in OFFICIAL_SYMBOL and tk not in OFFICIAL_SYMBOL[s]


def make_adapter(cfg):
    return TronAdapter(cfg)


def budgets(ad: TronAdapter, cfg: dict):
    o = ad.opts
    hist = max(5, int(ad.rps * 40 / 2))
    pb = {"latest": int(o.get("latest_pages", 5)), "history": int(o.get("history_pages", max(3, int(ad.rps * 10))))}
    db = {"latest": int(o.get("latest_details", 50)), "history": int(o.get("history_details", hist))}
    return pb, db


def main(poll_default: int = 60):
    from inbox import SegmentWriter
    log = logs.setup_logging("tj-" + CHAIN)
    paths.ensure_dirs()
    cfg = config.load_config()
    owners = reg.owners(cfg, CHAIN)
    if not owners:
        raise SystemExit("추적할 Tron 지갑이 없음 — config chain_wallets 확인")
    sp = reg.spec(CHAIN)
    st = chain_state.ChainState(CHAIN)
    st.drop_owner(owners)
    st.save()
    ad = make_adapter(cfg)
    ad.state = st
    pb, db = budgets(ad, cfg)
    col = chain_watch.Collector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, sp.stream)), st, owners, log=log,
                                page_budget=pb, detail_budget=db)
    try:
        poll = int(ad.opts.get("poll_sec", poll_default))
    except (TypeError, ValueError):
        poll = poll_default
    log.info("가동: Tron %d지갑, %d초 주기 · %s · 초당 %.2f콜", len(owners), poll, "키" if ad.key else "무키(운영 보장 아님 — 키 권장)", ad.rps)
    while True:
        t0 = time.time()
        try:
            r = col.cycle()
            log.info("[tron] 주기: %s · 호출 %d", r, ad.calls)
        except Exception as e:   # noqa: BLE001 [boundary]
            log.warning("[tron] 주기 실패(다음 주기): %s", logs.safe_err(e)[:200])
        time.sleep(max(5.0, poll - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logs.setup_logging("tj-" + CHAIN).info("정지 신호(SIGINT) — 종료")
