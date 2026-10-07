from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import common
import sellchart
import xchain_match as xm

log = logging.getLogger("tj-web")
KST = timezone(timedelta(hours=9))

PV = "aiaddr-2"
STORE_NAME = "addr_ai.json"
MODEL_BUDGET = "addr_ai_budget.json"
CHAIN_BUDGET = "addr_ai_chain_budget.json"
STORE_KEEP = 2000
DAILY_CAP = 200
PER_ITEM_MAX = 6
DEFAULTS = {"daily_max": 0,
            "per_item_calls": 6,
            "chain_calls_day": None,
            "interval_sec": 180,
            "first_delay_sec": 300,
            "max_targets": 100,
            "retry_sec": 6 * 3600,
            "fail_max": 3,
            "regen_min_sec": 86400}

VERDICTS = {"exchange": "거래소 입금 주소 같음", "personal": "개인 지갑", "contract": "브릿지·라우터 컨트랙트",
            "burn": "소각 주소", "poison": "사칭·주소 오염 의심", "unknown": "모름"}
CONF = {"high": "높음", "mid": "보통", "low": "낮음"}
FLOW_WAIT = ("queued", "scanning")
SOL_SYSTEM = "11111111111111111111111111111111"
SOL_TOKEN_PROGS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOL = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

STATUS = {"cli": None, "cli_at": 0.0, "cli_bin": None, "limit_day": None, "last": "", "last_at": 0}
_ST_MU = threading.Lock()


def settings(cfg) -> dict:
    raw = (cfg or {}).get("addr_ai") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)

    def num(k, lo, hi):
        v = raw.get(k, DEFAULTS[k])
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = DEFAULTS[k] if DEFAULTS[k] is not None else lo
        return max(lo, min(hi, v))
    if raw.get("enabled") is False:
        out["daily_max"] = 0
    else:
        out["daily_max"] = num("daily_max", 0, DAILY_CAP)
    out["per_item_calls"] = num("per_item_calls", 0, PER_ITEM_MAX)
    cd = raw.get("chain_calls_day")
    try:
        cd = int(cd) if cd is not None else None
    except (TypeError, ValueError):
        cd = None
    out["chain_calls_day"] = max(0, min(DAILY_CAP * PER_ITEM_MAX, cd if cd is not None else out["daily_max"] * out["per_item_calls"]))
    out["interval_sec"] = num("interval_sec", 60, 86400)
    out["first_delay_sec"] = num("first_delay_sec", 0, 86400)
    out["max_targets"] = num("max_targets", 1, 500)
    out["retry_sec"] = num("retry_sec", 600, 7 * 86400)
    out["fail_max"] = num("fail_max", 1, 10)
    out["regen_min_sec"] = num("regen_min_sec", 0, 30 * 86400)
    return out


def _off_chains(cfg) -> set:
    off = set((cfg or {}).get("_disabled_chains") or ())
    off.update(c for c, cc in ((cfg or {}).get("chains") or {}).items() if isinstance(cc, dict) and not common.chain_enabled(c, cc))
    return off


def fam(addr) -> str | None:
    a = str(addr or "")
    if _EVM.match(a):
        return "evm"
    if _SOL.match(a) and not a.startswith("0x"):
        return "sol"
    return None


def akey(addr) -> str | None:
    f = fam(addr)
    if not f:
        return None
    a = str(addr)
    return f"{f}:{a.lower() if f == 'evm' else a}"


_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁠-⁯﻿]")
_URL = re.compile(r"(?:[a-z][a-z0-9+.\-]*://\S+|www\.\S+"
                  r"|(?<![A-Za-z0-9._\-])[A-Za-z0-9\-]+(?:[.。．｡][A-Za-z0-9\-]+)*[.。．｡](?:[A-Za-z]{2,63}|xn--[A-Za-z0-9\-]{1,59}|[^\W\d_]{2,63})"
                  r"(?![A-Za-z0-9\-])(?:[/?#:]\S*)?|@\w{2,})", re.I)
_ADDR_EVM = re.compile(r"0x[0-9a-fA-F]{6,}")
_ADDR_B58 = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{25,}(?![A-Za-z0-9])")
_AMT = re.compile(r"(?:[-+−]\s?)?[$₩€¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:[KMBkmb](?![a-zA-Z])|만|억|천))?"
                  r"|[-+−]?\d[\d,]*(?:\.\d+)?\s?(?:달러|불|원(?!가|화|래|인|칙)|USD[TC]?|KRW|만\s?원|억\s?원|만(?=\s|$|[^\w])|억|개(?=\s|$|[^\w])|"
                  r"ETH|SOL|BNB|BTC|POL|MATIC)(?![A-Za-z])")


def clean(s, n=120) -> str:
    t = _CTRL.sub(" ", str(s if s is not None else ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


_SHORTADDR = re.compile(r"[0-9A-Za-z]{2,}(?:…|\.{2,3})[0-9A-Za-z]{2,}")
_HEXRUN = re.compile(r"0x[0-9a-fA-F]{2,}")
_HEX16 = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{16,}(?![0-9A-Za-z])")
_MIXED = re.compile(r"(?<![0-9A-Za-z])(?=[0-9A-Za-z]*\d)(?=[0-9A-Za-z]*[A-Z])(?=[0-9A-Za-z]*[a-z])[0-9A-Za-z]{10,}(?![0-9A-Za-z])")
_NUM_ALL = re.compile(r"[-+−]?\d[\d,._]*(?:[eE][-+]?\d+)?")
_PH_RUN = re.compile(r"\((?:수|금액)\)(?:[\s:/~.,·\-]*\((?:수|금액)\))+")
_NUM_OUT = re.compile(r"\d{4}-\d{2}(?:-\d{2})?(?![\d.,])|[-+−]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?:\s?(?:건|곳|번|회|일|시간|분|달|월|주|명|쪽|가지|%|~))?")
_KEEP_OUT = re.compile(r"\d{4}-\d{2}(?:-\d{2})?|\d{1,3}\s?(?:건|곳|번|회|일|시간|분|달|월|주|명|쪽|가지|%|~)")


def _strip_ids(t: str) -> str:
    t = _URL.sub("", t)
    t = _SHORTADDR.sub("(주소)", t)
    t = _HEXRUN.sub("(주소)", t)
    t = _ADDR_B58.sub("(주소)", t)
    t = _HEX16.sub("(해시)", t)
    t = _MIXED.sub("(주소)", t)
    return _AMT.sub("(금액)", t)


def _tidy(t: str, n: int) -> str:
    t = _PH_RUN.sub("(수)", t)
    t = re.sub(r"(\(주소\)\s*){2,}", "(주소) ", t)
    t = re.sub(r"\s+", " ", t).strip(" ·,;")
    return t[:n]


def free(s, n=120) -> str:
    t = clean(s, 2000)
    t = _NUM_ALL.sub("(수)", _strip_ids(t))
    return _tidy(t, n)


_TAG = re.compile(r"[A-Za-z0-9$가-힣][A-Za-z0-9._\-+$가-힣]*")
_TAG_SP = re.compile(r"[A-Za-z0-9$가-힣][A-Za-z0-9._\-+$가-힣 ()]*")


def tag(s, n=24, sp=False) -> str:
    t = clean(s, 200)
    if not t:
        return ""
    if (len(t) > n or not (_TAG_SP if sp else _TAG).fullmatch(t) or len(re.findall(r"\d", t)) > 2
            or t.lower().startswith("0x") or not re.search(r"[A-Za-z가-힣]", t) or _URL.search(t)):
        return "(기타)"
    return t


def _ymd(s) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(s or ""))
    return m.group(0) if m else ""


def scrub(s, n=120) -> str:
    t = _strip_ids(clean(s, 2000))
    t = _NUM_OUT.sub(lambda m: m.group(0) if _KEEP_OUT.fullmatch(m.group(0)) else "(수)", t)
    return _tidy(t, n)


def _num(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


BANDS = ("1달러 미만", "100달러 미만", "100~1천 달러", "1천~1만 달러", "1만~10만 달러", "10만 달러 이상")
SHARES = ("없음", "일부", "절반 이상", "전액 이상")
QBANDS = ("0", "아주 적음", "적음", "보통", "많음")
CBANDS = ("0", "1~9", "10~99", "100~999", "1천~9999", "1만 이상")
BAND_VALUES = frozenset(BANDS + SHARES + QBANDS + CBANDS + ("모름",))


def band(usd) -> str:
    v = _num(usd)
    if v is None:
        return "모름"
    v = abs(v)
    if v < 1:
        return "1달러 미만"
    if v < 100:
        return "100달러 미만"
    if v < 1000:
        return "100~1천 달러"
    if v < 10000:
        return "1천~1만 달러"
    if v < 100000:
        return "1만~10만 달러"
    return "10만 달러 이상"


def share(part, whole) -> str:
    p, w = _num(part), _num(whole)
    if p is None or w is None:
        return "모름"
    if w <= 0:
        return "모름" if p > 0 else "없음"
    r = p / w
    return "없음" if r < 0.01 else "일부" if r < 0.5 else "절반 이상" if r < 0.98 else "전액 이상"


def qband(x) -> str:
    v = _num(x)
    if v is None:
        return "모름"
    return "0" if v <= 0 else "아주 적음" if v < 0.01 else "적음" if v < 1 else "보통" if v < 100 else "많음"


def cband(n) -> str | None:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return None
    return "0" if v <= 0 else "1~9" if v < 10 else "10~99" if v < 100 else "100~999" if v < 1000 else "1천~9999" if v < 10000 else "1만 이상"


def _visible_pending(r) -> bool:
    if not isinstance(r, dict) or r.get("status") != "pending" or r.get("dust"):
        return False
    try:
        mx = max(float(r.get("usdAtSend") or 0), float(r.get("usdNow") or 0))
    except (TypeError, ValueError):
        mx = 0.0
    if mx < 1 and any(isinstance(f, dict) and f.get("kind") == "lookalike" for f in r.get("flags") or []):
        return False
    return True


NOW_KEY = "current_price_based"


def facts_of(r) -> dict:
    toks = sorted({tag(t.get("sym"), 24) or "(기타)" for t in r.get("tokens") or [] if isinstance(t, dict) and not t.get("phantom")})[:8]
    phantom = any(isinstance(t, dict) and t.get("phantom") for t in r.get("tokens") or [])
    sent_at = _num(r.get("usdAtSend"))
    sent_ok = sent_at is not None and sent_at > 0
    partly = r.get("usdAtSendKnown") is False
    sugg = []
    for s in (r.get("suggestions") or [])[:3]:
        if isinstance(s, dict):
            sugg.append({"kind": tag(s.get("kind"), 24), "label": free(s.get("label"), 60), "evidence": free(s.get("evidence"), 120)})
    hints = sorted({free(h.get("label"), 60) for h in r.get("hints") or [] if isinstance(h, dict) and h.get("label")} - {""})[:4]
    exwd = []
    for x in r.get("exwd") or []:
        if isinstance(x, dict):
            e9 = {"from_exchange": tag(x.get("exName") or x.get("ex"), 24, sp=True), "network": tag(x.get("net"), 24, sp=True)}
            if e9 not in exwd:
                exwd.append(e9)
    now9 = {}
    if not sent_ok:
        now9["sent_size_at_current_price"] = band(r.get("usdNow"))
        now9["returned_directly_vs_current_value"] = share(r.get("returnedUsd"), r.get("usdNow"))
    f = r.get("flow") if isinstance(r.get("flow"), dict) else None
    flow = None
    if f:
        st = str(f.get("status") or "")
        flow = {"status": "done" if st in ("ok", "partial") else ("wait" if st in FLOW_WAIT else "failed")}
        if st in ("ok", "partial"):
            kinds = {}
            for x in f.get("recips") or []:
                if isinstance(x, dict):
                    k9 = tag(x.get("kind") or "eoa", 24) or "(기타)"
                    kinds[k9] = kinds.get(k9, 0) + 1
            fr, fs = f.get("returned") or {}, f.get("still") or {}
            sw9 = _num((f.get("swaps") or {}).get("n")) if isinstance(f.get("swaps"), dict) else None
            flow.update({"partial": st == "partial", "sent_onward_to": dict(sorted(kinds.items())),
                         "swaps": cband(int(sw9)) if sw9 is not None else "모름",
                         "my_wallet_score": tag((f.get("score") or {}).get("level") if isinstance(f.get("score"), dict) else None, 10) or "none"})
            now9["flow_came_back_to_me"] = share((fr or {}).get("usd") if isinstance(fr, dict) else None, f.get("sent"))
            now9["flow_still_there"] = share((fs or {}).get("usd") if isinstance(fs, dict) else None, f.get("sent"))
            now9["flow_mixed_with_others_money"] = bool(f.get("capped") or f.get("held"))
    try:
        sends = int(r.get("count"))
    except (TypeError, ValueError):
        sends = None
    out = {"chains": sorted({tag(c, 24) or "(기타)" for c in r.get("chains") or []}), "tokens": toks, "fake_token_logs": phantom,
           "sends": sends, "first": _ymd(r.get("first")), "last": _ymd(r.get("last")),
           "sent_size": band(sent_at) if sent_ok else "모름", "sent_value_partly_unknown": partly,
           "returned_directly": share(r.get("returnedUsd"), sent_at) if sent_ok else "모름",
           "flags": sorted({tag(x.get("kind"), 24) for x in r.get("flags") or [] if isinstance(x, dict) and x.get("kind")} - {""}),
           "bot_suggestions": sugg, "known_labels": hints,
           "with_my_wallets": bool(int(_num(r.get("returnedN")) or 0) > 0 or (f and int(_num(f.get("mineN")) or 0) > 0)
                                   or any(s.get("kind") in ("own", "roundtrip") for s in sugg)),
           "received_before_send": bool(_num((r.get("priorIn") or {}).get("n") if isinstance(r.get("priorIn"), dict) else None) or 0),
           "bridge_label": free((r.get("bridge") or {}).get("name"), 40) if isinstance(r.get("bridge"), dict) else "",
           "auto_match": [tag(b, 24) for b in ((r.get("autoMatch") or {}).get("basis") or [])][:4] if isinstance(r.get("autoMatch"), dict) else [],
           "exchange_withdrawals": exwd[:4], "flow": flow,
           "my_memo": free(r.get("memo"), 120), "my_alias": free(r.get("alias"), 40),
           NOW_KEY: now9}
    return out


FP_SKIP = (NOW_KEY, "returned_directly")


def fingerprint(facts) -> str:
    stable = {k: v for k, v in (facts or {}).items() if k not in FP_SKIP}
    return hashlib.sha1((PV + json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()[:16]


def targets(rows, max_n=100) -> list:
    by = {}
    for r in rows or []:
        if not _visible_pending(r):
            continue
        k = akey(r.get("address"))
        if not k:
            continue
        try:
            usd = max(float(r.get("usdAtSend") or 0), float(r.get("usdNow") or 0))
        except (TypeError, ValueError):
            usd = 0.0
        if k in by:
            by[k]["usd"] = max(by[k]["usd"], usd)
            by[k]["rows"].append(r)
            continue
        fa = facts_of(r)
        by[k] = {"key": k, "addr": str(r["address"]), "fam": k.split(":", 1)[0], "chains": list(fa["chains"]),
                 "facts": fa, "fp": fingerprint(fa), "usd": usd, "rows": [r],
                 "wait": bool(isinstance(r.get("flow"), dict) and r["flow"].get("status") in FLOW_WAIT)}
    out = sorted(by.values(), key=lambda t: (-t["usd"], t["key"]))
    return out[:max_n]


class Store:

    def __init__(self, state_dir=None):
        sd = state_dir or common.STATE_DIR
        self.path = os.path.join(sd, STORE_NAME)
        self.mu = threading.Lock()
        self.model = sellchart.EvalStore(sd)
        self.model.budget_path, self.model.lock_path = os.path.join(sd, MODEL_BUDGET), os.path.join(sd, "addr_ai.lock")
        self.model.path = self.path
        self.chain = sellchart.EvalStore(sd)
        self.chain.budget_path, self.chain.lock_path = os.path.join(sd, CHAIN_BUDGET), os.path.join(sd, "addr_ai_chain.lock")
        self.chain.path = self.path

    def read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            return {"v": 1, "items": {}, "err": {}}
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict) or not isinstance(d.get("items", {}), dict) or not isinstance(d.get("err", {}), dict):
            return None
        d.setdefault("items", {})
        d.setdefault("err", {})
        return d

    def _write(self, fn) -> bool:
        with self.mu:
            d = self.read()
            if d is None:
                log.warning("AI 주소 의견 저장 파일 손상 — 쓰지 않음(%s)", self.path)
                return False
            fn(d)
            if len(d["items"]) > STORE_KEEP:
                for k in sorted(d["items"], key=lambda k: int((d["items"][k] or {}).get("at") or 0))[:len(d["items"]) - STORE_KEEP]:
                    d["items"].pop(k, None)
            if len(d["err"]) > STORE_KEEP:
                for k in sorted(d["err"], key=lambda k: int((d["err"][k] or {}).get("at") or 0))[:len(d["err"]) - STORE_KEEP]:
                    d["err"].pop(k, None)
            try:
                common.atomic_write_json(self.path, d)
            except Exception as e:
                log.warning("AI 주소 의견 저장 실패: %s", type(e).__name__)
                return False
            return True

    def put(self, key, rec) -> bool:
        def fn(d):
            d["items"][key] = rec
            d["err"].pop(key, None)
        return self._write(fn)

    def note_err(self, key, fp, msg, now=None) -> bool:
        def fn(d):
            e = d["err"].get(key) if isinstance(d["err"].get(key), dict) else {}
            n = int(e.get("n") or 0) + 1 if e.get("fp") == fp else 1
            d["err"][key] = {"at": int(now or time.time()), "n": n, "fp": fp, "msg": clean(msg, 80)}
        return self._write(fn)


def _day(now=None) -> str:
    return datetime.fromtimestamp(now or time.time(), KST).strftime("%Y-%m-%d")


class _Tracer(xm.Tracer):

    def __init__(self, cfg, budget, take):
        super().__init__(cfg, {"stx": {}, "sigs": {}, "ws": {}, "etx": {}, "blk": {}, "dec": {}, "inflows": {}, "outflows": {}},
                         None, {}, budget=budget, sleep=0.35)
        self._take = take

    def _gate(self):
        if self.calls >= self.budget or not self._take():
            raise xm.Budget()

    def _post(self, url, method, params, timeout=30):
        self._gate()
        return super()._post(url, method, params, timeout=timeout)

    def _get(self, url, timeout=30):
        self._gate()
        return super()._get(url, timeout=timeout)


def _bs_hash(o):
    return str((o or {}).get("hash") or "").lower() if isinstance(o, dict) else ""


def _bs_name(o):
    if not isinstance(o, dict):
        return ""
    tg9 = (o.get("metadata") or {}).get("tags") if isinstance(o.get("metadata"), dict) else None
    nm = o.get("name") or ", ".join(str(t.get("name")) for t in (tg9 or [])[:2] if isinstance(t, dict) and t.get("name"))
    return free(nm, 40)


def _date(ts):
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), KST).strftime("%Y-%m-%d")
        return str(ts)[:10] if ts else ""
    except (ValueError, OSError, OverflowError):
        return ""


def probe_evm(t, cfg, chain, addr, known):
    a = addr.lower()
    cc = ((cfg.get("chains") or {}).get(chain) or {}) if chain != "bsc" else {}
    bs = t._bs(chain) if (chain != "bsc" and common.chain_discovery(chain, cc) != "rpc") else ""
    res = {"chain": tag(chain, 24) or "(기타)"}
    try:
        if bs:
            d = t._get(f"{bs}/api/v2/addresses/{a}")
            if not isinstance(d, dict):
                d = {}
            res["kind"] = ("contract" if d.get("is_contract") else "eoa") if isinstance(d.get("is_contract"), bool) else "모름"
            if res["kind"] == "모름":
                res["partial"] = "조회 실패"
            if d.get("is_contract"):
                res["verified"] = bool(d.get("is_verified"))
                if d.get("implementations"):
                    res["proxy"] = True
            nm = _bs_name(d)
            if nm:
                res["public_name"] = nm
            md9 = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
            tags = [free(x.get("name"), 30) for x in (md9.get("tags") or []) if isinstance(x, dict) and x.get("name")]
            tags += [free(x.get("label") or x.get("display_name"), 30) for x in (d.get("public_tags") or []) if isinstance(x, dict)]
            tags = [x for x in dict.fromkeys(tags) if x][:4]
            if tags:
                res["public_tags"] = tags
            if d.get("ens_domain_name"):
                res["ens"] = True
            if isinstance(d.get("token"), dict):
                res["is_token_contract"] = True
            if d.get("coin_balance") is not None:
                try:
                    res["native_balance"] = qband(int(str(d.get("coin_balance"))) / 1e18)
                except (TypeError, ValueError):
                    res["partial"] = "조회 실패"
            c = t._get(f"{bs}/api/v2/addresses/{a}/counters")
            tc9 = cband(c.get("transactions_count")) if isinstance(c, dict) else None
            if tc9 is None:
                res["partial"] = "조회 실패"
            else:
                res["tx_count"] = tc9
            txs = t._get(f"{bs}/api/v2/addresses/{a}/transactions")
            items = txs.get("items") if isinstance(txs, dict) else None
            if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                res["partial"] = "조회 실패"
                items = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
                txs = txs if isinstance(txs, dict) else {}
            if items:
                out_n = sum(1 for x in items if _bs_hash(x.get("from")) == a)
                cps, names, meth, cpc = {}, {}, {}, 0
                for x in items:
                    cp = x.get("to") if _bs_hash(x.get("from")) == a else x.get("from")
                    h = _bs_hash(cp)
                    if not h:
                        continue
                    if h not in cps:
                        cps[h] = cp
                        if isinstance(cp, dict) and cp.get("is_contract"):
                            cpc += 1
                    nm9 = _bs_name(cp)
                    if nm9:
                        names[nm9] = names.get(nm9, 0) + 1
                    m9 = free(x.get("method"), 32)
                    if m9:
                        meth[m9] = meth.get(m9, 0) + 1
                kinds = {str(k9) for h in cps for k9, _n in (known.get(h) or ())}
                tss = [x.get("timestamp") for x in items if x.get("timestamp")]
                res["recent"] = {"n": len(items), "sent": out_n, "received": len(items) - out_n, "distinct_counterparties": len(cps),
                                 "counterparty_contracts": cpc,
                                 "counterparty_names": [k9 for k9, _v in sorted(names.items(), key=lambda kv: -kv[1])[:3]],
                                 "methods": [k9 for k9, _v in sorted(meth.items(), key=lambda kv: -kv[1])[:3]],
                                 "with_my_wallet": "my_wallet" in kinds, "with_my_exchange_deposit": "exchange_deposit" in kinds,
                                 "with_known_bridge": "bridge" in kinds,
                                 "newest": _date(max(tss)) if tss else "", "oldest_in_page": _date(min(tss)) if tss else "",
                                 "more_pages": bool(txs.get("next_page_params"))}
        else:
            code = t._evm(chain, "eth_getCode", [a, "latest"])
            if not isinstance(code, str) or not code.startswith("0x"):
                raise ValueError("getCode 응답 없음")
            code = code.lower()
            if code.startswith("0xef0100") and len(code) == 48:
                res["kind"], res["delegated_7702"] = "eoa", True
            else:
                res["kind"] = "contract" if code not in ("0x", "0x0", "") else "eoa"
            try:
                res["nonce"] = cband(int(str(t._evm(chain, "eth_getTransactionCount", [a, "latest"])), 16))
                res["native_balance"] = qband(int(str(t._evm(chain, "eth_getBalance", [a, "latest"])), 16) / 1e18)
            except (TypeError, ValueError):
                res["partial"] = "조회 실패"
    except xm.Paused:
        res["partial"] = "탐색기 쉼"
    except xm.Budget:
        res["partial"] = "조회 한도"
    except Exception as e:
        res["partial"] = "조회 실패"
        log.info("AI 주소 의견 온체인 조회 일부 실패(%s): %s", chain, type(e).__name__)
    return res


def probe_sol(t, addr, known):
    res = {"chain": "sol"}
    try:
        ai = t._sol("getAccountInfo", [addr, {"encoding": "jsonParsed"}])
        if not isinstance(ai, dict) or "value" not in ai:
            raise ValueError("getAccountInfo 응답 없음")
        v = ai.get("value")
        if not v:
            res["kind"] = "empty"
        else:
            owner = str(v.get("owner") or "")
            lp9 = _num(v.get("lamports"))
            if lp9 is not None:
                res["native_balance"] = qband(lp9 / 1e9)
            else:
                res["partial"] = "조회 실패"
            if v.get("executable"):
                res["kind"] = "program"
            elif owner == SOL_SYSTEM:
                res["kind"] = "wallet"
            elif owner in SOL_TOKEN_PROGS:
                res["kind"] = "token_account"
                info = (((v.get("data") or {}).get("parsed") or {}).get("info") or {}) if isinstance(v.get("data"), dict) else {}
                res["token_account_owner_is_my_wallet"] = "my_wallet" in {k9 for k9, _n in (known.get(str(info.get("owner") or "")) or ())}
            else:
                res["kind"] = "program_owned"
        sigs = t._sol("getSignaturesForAddress", [addr, {"limit": 20}])
        if not isinstance(sigs, list):
            res["partial"] = "조회 실패"
        else:
            if any(not isinstance(s9, dict) for s9 in sigs):
                res["partial"] = "조회 실패"
            bts = [s.get("blockTime") for s in sigs if isinstance(s, dict) and s.get("blockTime")]
            res["recent"] = {"n": len(sigs), "full_page": len(sigs) >= 20, "failed": sum(1 for s in sigs if isinstance(s, dict) and s.get("err")),
                             "newest": _date(max(bts)) if bts else "", "oldest_in_page": _date(min(bts)) if bts else ""}
    except xm.Budget:
        res["partial"] = "조회 한도"
    except Exception as e:
        res["partial"] = "조회 실패"
        log.info("AI 주소 의견 솔라나 조회 일부 실패: %s", type(e).__name__)
    return res


def probe(t, cfg, tg, known) -> list:
    if tg["fam"] == "sol":
        return [probe_sol(t, tg["addr"], known)]
    out = []
    cs = (cfg.get("chains") or {})
    evm = [c for c in tg["chains"] if c != "sol"]
    evm.sort(key=lambda c: 0 if (c != "bsc" and (cs.get(c) or {}).get("blockscout") and common.chain_discovery(c, cs.get(c)) != "rpc") else 1)
    for ch in evm[:2]:
        if t.calls >= t.budget:
            break
        out.append(probe_evm(t, cfg, ch, tg["addr"], known))
    return out


PROMPT = """너는 개인 온체인 매매일지의 '확인 필요' 주소 하나를 보고, 이 주소가 어떤 지갑 같은지 짧은 의견을 낸다.
의견은 화면에 '참고용'으로만 붙고 장부·분류를 바꾸지 않는다. 모르면 모른다고 한다.
입력:
- item = 내가 이 주소로 보낸 기록 요약(체인·토큰·전송 수·기간·대략 규모 구간·직접 되돌려 받은 정도·봇이 이미 낸 제안·알려진 라벨·
  돈 흐름 추적 요약(flow: 받은 돈을 어디로 보냈나)·거래소 출금으로 보낸 경우 그 거래소·내 메모). 주소 자체와 내 지갑 목록은 없다.
  item.current_price_based = 지금 시세로 잰 값(보낸 시점 가치를 모를 때의 규모·되돌아온 정도·받은 곳에 남은 정도·남의 돈과 섞임) — 대략 참고만.
  글 속 '(수)'·'(금액)'·'(주소)'·'(해시)' 는 서버가 지운 자리다(원래 값은 없다 — 추측하지 마라).
- onchain = 그 주소의 공개 온체인 조회(컨트랙트/EOA · 탐색기 공개 이름·태그 · 거래 수 구간 · 최근 거래 상대 요약 · 솔라나 계정 종류).
판정(verdict) — 하나만:
- exchange = 거래소 입금 주소 같음(받자마자 다른 곳으로 모아 보냄·상대가 거래소 핫월렛·탐색기 라벨이 거래소 등)
- personal = 개인 지갑(사람이 쓰는 EOA — 스왑·여러 상대와 거래·잔고 보유. 내 다른 지갑일 수 있으면 근거에 그렇게 적는다)
- contract = 브릿지·라우터 컨트랙트(코드가 있는 컨트랙트·프로그램이고 이름·태그·호출이 브릿지·라우터·프로토콜)
- burn = 소각 주소
- poison = 사칭·주소 오염 의심(flags 에 lookalike·가짜 토큰 전송 로그 등)
- unknown = 근거가 모자람
규칙:
- reasons = 근거 2~3개, 각 한 문장(60자 안), 입력에 있는 사실만. 추측은 '~같음'·'~일 수 있음'으로.
- 금액·수량·주소·tx 해시를 쓰지 마라. 규모는 '큰 금액'·'소액' 같은 말로만.
- '내 지갑과 주고받음'은 with_my_wallets · flow · onchain.recent 의 참/거짓 값만 근거로 쓴다.
- confidence = high | mid | low (onchain 조회가 비었거나 partial 이면 낮게).
- 출력은 JSON 하나만, 다른 글 없이: {"verdict": "...", "reasons": ["...", "..."], "confidence": "..."}
데이터:
"""


_INPUT_KEYS_OK = re.compile(r"[a-z][a-z0-9_]{0,40}")


def guard_input(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            k9 = str(k)
            if not _INPUT_KEYS_OK.fullmatch(k9):
                k9 = tag(k9, 24) or "(기타)"
            if isinstance(v, float):
                continue
            out[k9] = guard_input(v)
        return out
    if isinstance(o, (list, tuple)):
        return [guard_input(v) for v in o if not isinstance(v, float)]
    if isinstance(o, str):
        if o in BAND_VALUES or (o and _ymd(o) == o) or tag(o, 24, sp=True) == o:
            return o
        return free(o, 120)
    if o is None or isinstance(o, (bool, int)):
        return o
    return free(o, 60)


def build_prompt(inp, nonce) -> tuple:
    import review_prompt as rp
    body = f"<<<DATA {nonce}>>>\n" + json.dumps(inp, ensure_ascii=False, separators=(",", ":")) + f"\n<<<END {nonce}>>>"
    return rp.with_data_fence(PROMPT, nonce), body


def normalize(rv):
    if not isinstance(rv, dict):
        return None
    v = str(rv.get("verdict") or "").strip().lower()
    if v not in VERDICTS:
        return None
    rs = rv.get("reasons")
    if isinstance(rs, str):
        rs = [rs]
    rs = [scrub(x, 120) for x in (rs if isinstance(rs, list) else []) if isinstance(x, str)]
    rs = [x for x in rs if len(x) >= 2][:3]
    if not rs:
        return None
    c = str(rv.get("confidence") or "").strip().lower()
    return {"verdict": v, "reasons": rs, "conf": c if c in CONF else "low"}


def model_label(model) -> str:
    m = str(model or "")
    if m == "rule":
        return "규칙"
    mm = re.match(r"claude-(sonnet|opus|haiku)-(\d+)-(\d+)", m)
    if mm:
        return {"sonnet": "소넷", "opus": "오퍼스", "haiku": "하이쿠"}[mm.group(1)] + f" {mm.group(2)}.{mm.group(3)}"
    return clean(m, 24) or "AI"


def rule_rec(tg, now):
    try:
        import flow_trace
        burn = flow_trace.is_burn(tg["addr"])
    except Exception:
        burn = False
    if not burn:
        return None
    return {"verdict": "burn", "reasons": ["발행·소각·시스템 주소 꼴이에요(누구의 지갑도 아님)"], "conf": "high",
            "fp": tg["fp"], "pv": PV, "at": int(now), "model": "rule", "calls": 0}


def _by_default() -> str:
    try:
        import review_daily as rd
        return model_label(getattr(rd, "REVIEW_MODEL", ""))
    except Exception:
        return "AI"


def view(tg, rec, err, on, today, s, by=None) -> dict | None:
    if isinstance(rec, dict) and rec.get("verdict") in VERDICTS:
        o = {"st": "ok", "v": rec["verdict"], "label": VERDICTS[rec["verdict"]],
             "why": [scrub(x, 120) for x in (rec.get("reasons") or [])][:3], "conf": CONF.get(rec.get("conf"), "낮음"),
             "at": int(rec.get("at") or 0), "by": model_label(rec.get("model"))}
        if rec.get("fp") != tg["fp"] or rec.get("pv") != PV:
            o["old"] = True
        return o
    if not on or STATUS.get("cli") is False:
        return None
    if isinstance(err, dict) and err.get("fp") == tg["fp"] and int(err.get("n") or 0) >= s["fail_max"]:
        return {"st": "fail", "by": by or "AI"}
    if STATUS.get("limit_day") == today:
        return {"st": "limit", "by": by or "AI"}
    return {"st": "wait", "by": by or "AI"}


def attach(rows, pendings, cfg, store=None, now=None) -> list:
    s = settings(cfg)
    st = store or STORE
    rows = list(rows or [])
    tg = targets(rows, len(rows))
    off9 = _off_chains(cfg)
    queue = [t for t in tg if not off9.intersection(t.get("chains") or ())][:max(0, s["max_targets"])]
    queued = {t["key"] for t in queue}
    d = st.read()
    today = _day(now)
    on = s["daily_max"] > 0 and d is not None
    d = d if d is not None else {"items": {}, "err": {}}
    by, lab = {}, (_by_default() if on else "AI")
    for t in tg:
        op = view(t, d["items"].get(t["key"]), d["err"].get(t["key"]), on and t["key"] in queued, today, s, lab)
        if op is not None:
            for r in t["rows"]:
                r["aiOp"] = op
            by[t["key"]] = op
    for p in pendings or []:
        if isinstance(p, dict) and str(p.get("key") or "").startswith("TRANSFER_OUT:") and p.get("to"):
            op = by.get(akey(p.get("to")))
            if op is not None:
                p["aiOp"] = op
    return [{k: v for k, v in t.items() if k != "rows"} for t in queue]


def _needs(t, d, now, s) -> bool:
    if t.get("wait"):
        return False
    rec = d["items"].get(t["key"])
    if isinstance(rec, dict) and rec.get("verdict") in VERDICTS:
        if rec.get("fp") == t["fp"] and rec.get("pv") == PV:
            return False
        if now - int(rec.get("at") or 0) < s["regen_min_sec"]:
            return False
    e = d["err"].get(t["key"])
    if isinstance(e, dict) and e.get("fp") == t["fp"]:
        if int(e.get("n") or 0) >= s["fail_max"] or now - int(e.get("at") or 0) < s["retry_sec"]:
            return False
    return True


def cli_bin(binfn=None, now=None):
    now = time.time() if now is None else now
    with _ST_MU:
        if STATUS["cli"] is not None and now - STATUS["cli_at"] < 3600:
            return STATUS["cli_bin"]
    if binfn is None:
        import review_daily as rd
        binfn = rd.claude_bin
    b = binfn()
    with _ST_MU:
        STATUS.update(cli=bool(b), cli_at=now, cli_bin=b)
    return b


EVAL_LOCK_SLOTS = (0, 1, 2, 3)
EVAL_LOCK_KINDS = ("sell", "buy")


def _eval_release(fds):
    for fd in reversed(fds or []):
        try:
            sellchart.EvalStore.unlock(fd)
        except OSError:
            pass


def eval_gate(state_dir):
    fds = []
    for kind in EVAL_LOCK_KINDS:
        es = sellchart.EvalStore(state_dir, kind=kind)
        for i in EVAL_LOCK_SLOTS:
            fd = es.try_lock((i,))
            if fd is None:
                _eval_release(fds)
                return None
            fds.append(fd)
    return fds


def run_once(b, store=None, now=None, runner=None, binfn=None, tracer=None, model=None) -> str:
    st = store or STORE
    now = time.time() if now is None else now
    s = settings(b.cfg)
    if s["daily_max"] <= 0:
        return "off"
    pz = getattr(b, "_addr_ai_paused", None)
    if callable(pz) and pz():
        return "paused"
    bz = getattr(b, "_addr_ai_busy", None)
    if callable(bz) and bz():
        return "busy"
    sd = os.path.dirname(st.path)
    g0 = eval_gate(sd)
    if g0 is None:
        return "busy"
    _eval_release(g0)
    tg = list(getattr(b, "_addr_ai_targets", None) or [])
    off9 = _off_chains(getattr(b, "cfg", None))
    tg = [t for t in tg if not off9.intersection(t.get("chains") or ())]
    d = st.read()
    if d is None:
        return "corrupt"
    pick = next((t for t in tg if _needs(t, d, now, s)), None)
    if pick is None:
        return "idle"
    day = _day(now)
    rr = rule_rec(pick, now)
    if rr is not None:
        st.put(pick["key"], rr)
        b.soft_invalidate(kick=False)
        return "rule"
    if st.model.budget(day, s["daily_max"])["left"] <= 0:
        with _ST_MU:
            STATUS["limit_day"] = day
        return "limit"
    bp = cli_bin(binfn, now)
    if not bp:
        return "nocli"
    try:
        known = b._known_addrs()
    except Exception:
        return "noknown"
    known = dict(known or {})
    try:
        for w in common.history_wallets(b.cfg):
            a9 = str((w or {}).get("address") or "")
            if a9:
                known.setdefault(a9.lower() if a9.startswith("0x") else a9, []).append(("my_wallet", ""))
    except Exception:
        pass
    ccap = s["chain_calls_day"]
    take = (lambda: st.chain.budget_take(day, ccap, "c")) if ccap > 0 else (lambda: False)
    if s["per_item_calls"] > 0 and (ccap <= 0 or st.chain.budget(day, ccap)["left"] <= 0):
        with _ST_MU:
            STATUS["limit_day"] = day
        return "chain_limit"
    t = tracer(b.cfg, s["per_item_calls"], take) if tracer is not None else _Tracer(b.cfg, s["per_item_calls"], take)
    oc = probe(t, b.cfg, pick, known) if s["per_item_calls"] > 0 else []
    inp = guard_input({"item": pick["facts"], "onchain": oc, "address_type": "Solana" if pick["fam"] == "sol" else "EVM"})
    nonce = secrets.token_hex(8)
    prompt, body = build_prompt(inp, nonce)
    rd = None
    if runner is None or model is None:
        import review_daily as rd
    run = runner or (lambda b9, p9, body9: rd._run_cli(b9, p9, None, "주소 의견", body=body9))
    gate = eval_gate(sd)
    if gate is None:
        return "busy"
    try:
        if callable(pz) and pz():
            return "paused"
        if callable(bz) and bz():
            return "busy"
        if not st.model.budget_take(day, s["daily_max"], f"{pick['key'][:16]}|{pick['fp']}"):
            with _ST_MU:
                STATUS["limit_day"] = day
            return "limit"
        try:
            rv = run(bp, prompt, body)
        except Exception as e:
            rv = None
            log.warning("AI 주소 의견 실행 실패: %s", type(e).__name__)
    finally:
        _eval_release(gate)
    res = normalize(rv)
    if res is None:
        st.note_err(pick["key"], pick["fp"], "모델 응답 형식", now)
        b.soft_invalidate(kick=False)
        return "fail"
    rec = dict(res, fp=pick["fp"], pv=PV, at=int(now), model=model if model is not None else getattr(rd, "REVIEW_MODEL", ""),
               calls=int(t.calls), chains=[x.get("chain") for x in oc])
    if not st.put(pick["key"], rec):
        return "fail"
    b.soft_invalidate(kick=False)
    return "made"


def worker_loop(b, sleep=time.sleep):
    sleep(settings(b.cfg)["first_delay_sec"])
    while True:
        try:
            r = run_once(b)
            with _ST_MU:
                STATUS["last"], STATUS["last_at"] = r, int(time.time())
            if r in ("made", "fail"):
                log.info("AI 주소 의견: %s", r)
        except (Exception, SystemExit) as e:
            log.warning("addr-ai-worker 실패(다음 주기): %s", type(e).__name__)
        sleep(settings(b.cfg)["interval_sec"])


STORE = Store()
