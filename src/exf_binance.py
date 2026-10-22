from __future__ import annotations
import json
import os
import time
import urllib.request
from decimal import Decimal
from decimal import InvalidOperation
import ex_sign, paths, statefile
from exf_net import BN_UNI_RETRY
from exf_net import BN_UNI_TTL
from exf_net import DAY
from exf_net import PACE
from exf_net import POLL_SEC
from exf_net import PX_BN_FAIL_MAX
from exf_net import PX_BN_REPLAN_MS
from exf_net import PX_CALLS_MAX
from exf_net import RECON_HOLD_CAP
from exf_net import RateLimited
from exf_net import SignatureExpired
from exf_net import _Bal
from exf_net import _DENY_SIGS
from exf_net import _POLL_HINT
from exf_net import _WD_TOUCH
from exf_net import _add_to
from exf_net import _ak
from exf_net import _balance_rows
from exf_net import _clock_retry
from exf_net import _cv_fill
from exf_net import _debt_add
from exf_net import _dstr
from exf_net import _earn_amount
from exf_net import _err_body
from exf_net import _fut_opt
from exf_net import _fut_path
from exf_net import _fut_req
from exf_net import _fut_write
from exf_net import _gov_prepare
from exf_net import _http_json_err
from exf_net import _int_or
from exf_net import _iso
from exf_net import _loan_add
from exf_net import _loan_amt
from exf_net import _px_safe
from exf_net import _recon_hold
from exf_net import _recon_hold_clear
from exf_net import _srv_ms
from exf_net import _sub_bal
from exf_net import _xm
from exf_net import fut_first_t0
from exf_net import fut_rcpt
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
from exf_net import split_pair
import logging

log = logging.getLogger('tj-exf')

_BN_WD_FAIL = {1: "CANCELLED", 3: "REJECTED", 5: "FAILED"}


_BN_DEP_FAIL = {2: "REJECTED", 7: "FAILED"}


def fetch_binance(env, t0: int, t1: int):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    out_w, out_d = [], []

    @_clock_retry
    def call(path, extra):
        _gov_prepare("api.binance.com", path)
        q = dict(extra)
        q["timestamp"] = _srv_ms("api.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = ex_sign.binance_sign(sec, qs)
        return http_json(f"https://api.binance.com{path}?{qs}&signature={sig}",
                         {"X-MBX-APIKEY": key})

    def paged(path, s, e):
        out, off, prev = [], 0, None
        while True:
            rows = call(path, {"startTime": s * 1000, "endTime": e * 1000, "limit": 1000, "offset": off}) or []
            if not isinstance(rows, list):
                raise RuntimeError(f"binance {path} 응답 형식 오류 — 다음 주기 재시도")
            sig = tuple(json.dumps(r, sort_keys=True) for r in rows[:3])
            if off and rows and sig == prev:
                raise RuntimeError(f"binance {path} offset 미전진(같은 페이지 반복) — 다음 주기 재시도")
            prev = sig
            out.extend(rows)
            time.sleep(PACE)
            if len(rows) < 1000:
                return out
            off += 1000
            if off >= 100000:
                raise RuntimeError(f"binance {path} 창 하나에 10만 건 초과 — 다음 주기 재시도")

    s = t0
    while s < t1:
        e = min(s + 89 * DAY, t1)
        rows_w = paged("/sapi/v1/capital/withdraw/history", s, e)
        for row in rows_w:
            st = "DONE" if _int_or(row.get("status")) == 6 else _BN_WD_FAIL.get(_int_or(row.get("status")), "PENDING")
            out_w.append(norm_row("binance", row.get("id") or row.get("txId") or "",
                                  row.get("coin"), row.get("amount"),
                                  row.get("transactionFee"), row.get("txId"), st,
                                  row.get("applyTime"), row.get("completeTime"),
                                  row.get("address"), row.get("addressTag"), row.get("network")))
        rows_d = paged("/sapi/v1/capital/deposit/hisrec", s, e)
        for row in rows_d:
            st = "ACCEPTED" if _int_or(row.get("status")) in (1, 6) else _BN_DEP_FAIL.get(_int_or(row.get("status")), "PENDING")
            nid = row.get("id") or f"{row.get('coin')}:{row.get('txId')}"
            out_d.append(norm_row("binance", nid, row.get("coin"), row.get("amount"),
                                  0, row.get("txId"), st,
                                  row.get("insertTime"), row.get("insertTime"),
                                  network=row.get("network")))
        s = e
    return out_w, out_d


def _binance_caller(env):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]

    @_clock_retry
    def call(path, extra):
        _gov_prepare("api.binance.com", path)
        q = dict(extra)
        q["timestamp"] = _srv_ms("api.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = ex_sign.binance_sign(sec, qs)
        return http_json(f"https://api.binance.com{path}?{qs}&signature={sig}",
                         {"X-MBX-APIKEY": key})
    return call


def fills_binance_replay(env, fst: dict, rp: dict, deadline: float, emit, save) -> bool:
    call = _binance_caller(env)
    lo_ms, hi_ms = int(rp["lo"]) * 1000, int(rp["hi"]) * 1000
    pos = rp.setdefault("pos", {})
    done = set(rp.get("done") or [])
    keys = [("s:" + p9, int(c9 or 0)) for p9, c9 in (fst.get("pair_cursor") or {}).items()]
    keys += [(ck, int(c9 or 0)) for ck, c9 in (fst.get("margin_cursor") or {}).items()]
    inv9 = {"s:" + p9 for p9 in (fst.get("invalid_pairs") or [])} | set(fst.get("margin_invalid") or [])
    unav = set(rp.get("unavailable") or [])
    for k9, lim in sorted(keys):
        if k9 in done:
            continue
        if k9 in inv9 or k9 in unav:
            unav.add(k9)
            done.add(k9)
            rp["unavailable"], rp["done"] = sorted(unav), sorted(done)
            continue
        kind, pair = k9.split(":", 1)
        spot = kind == "s"
        base9, quote9 = _bn_split(pair, fst.get("pair_bq") or {}, _BN_UNI.get("sym"))
        page = 1000 if spot else 500
        while True:
            from_id = int(pos.get(k9) or 0)
            if lim and from_id >= lim:
                break
            if time.time() >= deadline:
                rp["done"] = sorted(done)
                save()
                return False
            try:
                if spot:
                    rows = call("/api/v3/myTrades", {"symbol": pair, "fromId": from_id, "limit": page})
                else:
                    rows = call("/sapi/v1/margin/myTrades", {"symbol": pair, "isIsolated": "TRUE" if kind == "i" else "FALSE",
                                                             "fromId": from_id, "limit": page})
            except urllib.error.HTTPError as e:
                body9 = _err_body(e)[:120]
                if e.code == 400 and ("-1121" in body9 or (not spot and "-11001" in body9)):
                    log.warning("binance 재조회 %s: 무효 페어(%s) — 조회 불가로 건너뜀", k9, body9[:60])
                    unav.add(k9)
                    rp["unavailable"] = sorted(unav)
                    break
                raise
            if not rows:
                break
            out = []
            for r in rows:
                if lim and int(r["id"]) >= lim:
                    continue
                if not (lo_ms <= int(r["time"]) < hi_ms):
                    continue
                fid = f"{pair}:{r['id']}" if spot else f"m{'i' if kind == 'i' else ''}:{pair}:{r['id']}"
                out.append(norm_fill("binance", fid, r["time"], base9, quote9,
                                     "buy" if r.get("isBuyer") else "sell",
                                     r.get("price"), r.get("qty"), r.get("commission"), r.get("commissionAsset")))
            if out:
                emit(out)
            pos[k9] = int(rows[-1]["id"]) + 1
            save()
            time.sleep(0.25)
            if len(rows) < page or int(rows[-1]["time"]) >= hi_ms:
                break
        done.add(k9)
        rp["done"] = sorted(done)
        save()
    return True


def binance_fills_t0(st: dict, now: int, window: int) -> int:
    t0 = int(now - window)
    ext = (st or {}).get("ext")
    if isinstance(ext, dict) and isinstance(ext.get("fills_from"), (int, float)):
        t0 = min(t0, int(ext["fills_from"]))
    return t0


BINANCE_QUOTES = ("USDT", "USDC", "BTC", "BNB", "FDUSD")


BN_UNI_NAME = "exf_binance_symbols.json"


BN_IDLE_SEC = 6 * 3600


BN_SWEEP_SEC = 24 * 3600


BN_INVALID_RECHECK = 7 * DAY


BN_RECENT_SEC = 7 * DAY


BN_LATE_MARGIN = 120


BN_FIRST_SWEEP_SEC = 180


_BN_UNI = {"ts": 0.0, "fail": 0.0, "sym": None, "path": None}


def _bn_universe(now: float):
    u = _BN_UNI
    p = paths.state(BN_UNI_NAME)
    if u.get("path") != p:
        u.update(ts=0.0, fail=0.0, sym=None, path=p)
        try:
            d = statefile.read_json(p, {}) if os.path.exists(p) else {}
        except SystemExit:
            d = {}
        sy = d.get("symbols") if isinstance(d, dict) else None
        if isinstance(sy, dict) and sy:
            u["sym"] = {str(k): (str(v[0]), str(v[1]), str(v[2]), int(v[3] if len(v) > 3 else 0))
                        for k, v in sy.items() if isinstance(v, list) and len(v) >= 3}
            try:
                u["ts"] = float(d.get("ts") or 0)
            except (TypeError, ValueError):
                u["ts"] = 0.0
    if now - u["ts"] >= BN_UNI_TTL and now - u["fail"] >= BN_UNI_RETRY:
        try:
            d = http_json("https://api.binance.com/api/v3/exchangeInfo", timeout=60)
            rows = d.get("symbols") if isinstance(d, dict) else None
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("exchangeInfo symbols 누락/형식 오류")
            sym = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                s9 = str(r.get("symbol") or "").upper()
                b9 = str(r.get("baseAsset") or "").upper()
                q9 = str(r.get("quoteAsset") or "").upper()
                if s9 and b9 and q9:
                    sym[s9] = (b9, q9, str(r.get("status") or ""), 1 if r.get("isMarginTradingAllowed") else 0)
            if not sym:
                raise RuntimeError("exchangeInfo 심볼 0")
            u["sym"], u["ts"] = sym, float(now)
            statefile.atomic_write_json(p, {"ts": int(now), "symbols": {k: list(v) for k, v in sym.items()}})
            log.info("binance 심볼 목록 갱신: %d개(상장 폐지 포함)", len(sym))
        except Exception as e:   # noqa: BLE001 [fallback]
            u["fail"] = float(now)
            log.warning("binance exchangeInfo 갱신 실패(%s · 1시간 뒤 재시도): %s",
                        "직전 목록 사용" if u["sym"] else "종전 주요 쿼트 5종으로", _xm(repr(e))[:140])
    return u["sym"]


def _bn_split(pair: str, bq: dict, uni):
    v = bq.get(pair) if isinstance(bq, dict) else None
    if isinstance(v, (list, tuple)) and len(v) >= 2 and v[0] and v[1]:
        return str(v[0]), str(v[1])
    if uni and pair in uni:
        return uni[pair][0], uni[pair][1]
    b9 = next((pair[:-len(q)] for q in BINANCE_QUOTES if pair.endswith(q) and len(pair) > len(q)), None)
    if b9:
        return b9, pair[len(b9):]
    return split_pair(pair)


def _bn_inv_load(lst, at, uni, now):
    out = {}
    for p, t in (at.items() if isinstance(at, dict) else ()):
        try:
            out[str(p)] = float(t)
        except (TypeError, ValueError):
            continue
    for p in (lst or []):
        p = str(p)
        if p in out:
            continue
        if uni and p in uni:
            continue
        out[p] = float(now)
    return {p: t for p, t in out.items() if now - t < BN_INVALID_RECHECK}


def fills_binance(env, st, t0: int, t1: int):
    call = _binance_caller(env)
    now9 = int(time.time())
    late_before = int(st.get("bn_acct_at") or st.get("backfilled_until") or 0)
    if not st.get("backfilled_until") and not st.get("bn_sweep_full") and not isinstance(st.get("bn_first_sweep"), dict):
        st["bn_first_sweep"] = {"at": now9, "n": 0, "done": []}
    acct = call("/api/v3/account", {"omitZeroBalances": "true"})
    acct_at = int(time.time())
    cur = {}
    for b in acct.get("balances", []):
        try:
            fr, lk = Decimal(str(b.get("free") or 0)), Decimal(str(b.get("locked") or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if fr + lk > 0:
            cur[str(b["asset"]).upper()] = [_dstr(fr), _dstr(lk)]
    bases = set(cur)
    st["extra_bases"] = sorted(set(st.get("extra_bases") or []) | bases)
    bases |= set(st.get("extra_bases") or [])
    prev = st.get("bn_bal") if isinstance(st.get("bn_bal"), dict) else None
    touch = {str(x).upper() for x in (_WD_TOUCH.get(_ak("binance")) or ()) if x}
    dirty = {str(x).upper() for x in (st.get("bn_dirty") or [])} | touch
    lock_chg = False
    if prev is None:
        dirty |= set(cur)
        lock_chg = True
    else:
        for a in set(cur) | set(prev):
            p0, c0 = prev.get(a) or ["0", "0"], cur.get(a) or ["0", "0"]
            try:
                if Decimal(str(p0[0])) + Decimal(str(p0[1])) != Decimal(c0[0]) + Decimal(c0[1]):
                    dirty.add(a)
                elif str(p0[1]) != c0[1]:
                    lock_chg = True
            except (InvalidOperation, TypeError, ValueError, IndexError):
                dirty.add(a)
    st["bn_dirty"] = sorted(dirty)
    st["bn_last_dirty"] = sorted(dirty)
    uni = _bn_universe(now9)
    by_base, quotes_all = {}, set(BINANCE_QUOTES)
    if uni:
        for s9, v9 in uni.items():
            by_base.setdefault(v9[0], []).append(s9)
            quotes_all.add(v9[1])
    cursors = dict(st.get("pair_cursor") or {})
    bq = dict(st.get("pair_bq") or {})
    chk = {str(k): float(v) for k, v in (st.get("pair_chk") or {}).items() if isinstance(v, (int, float))}
    last = {str(k): float(v) for k, v in (st.get("pair_last") or {}).items() if isinstance(v, (int, float))}
    open_prev = set(st.get("bn_open") or [])
    inv = _bn_inv_load(st.get("invalid_pairs"), st.get("invalid_at"), uni, now9)
    bases |= {_bn_split(p9, bq, uni)[0] for p9 in cursors}
    bases |= {_bn_split(s9, bq, uni)[0] for s9 in open_prev}
    bases |= dirty

    def pairs_of(b):
        if uni:
            return [(s9, uni[s9][0], uni[s9][1]) for s9 in by_base.get(b, ())]
        return [(b + q, b, q) for q in BINANCE_QUOTES if b != q]

    cand = {}
    for b in bases:
        for p9, b9, q9 in pairs_of(b):
            cand[p9] = (b9, q9)
    for p9 in cursors:
        cand.setdefault(p9, _bn_split(p9, bq, uni))
    cand = {p9: v9 for p9, v9 in cand.items() if p9 not in inv and v9[0] != v9[1]}
    fills, polled, explained = [], set(), set()
    partial = None
    n_calls = [0]

    def poll(pair, b, q):
        from_id = int(cursors.get(pair) or 0)
        while True:
            try:
                n_calls[0] += 1
                rows = call("/api/v3/myTrades", {"symbol": pair, "fromId": from_id, "limit": 1000})
            except urllib.error.HTTPError as e:
                body = _err_body(e)[:120]
                if e.code == 400 and "-1121" in body:
                    inv[pair] = float(now9)
                    break
                if e.code == 400 and "-1021" in body:
                    raise SignatureExpired(f"binance myTrades {pair} -1021(타임스탬프 창 밖)") from None
                raise
            if not isinstance(rows, list):
                raise RuntimeError(f"binance myTrades {pair} 응답 형식 오류")
            if not rows:
                break
            for r in rows:
                fills.append(norm_fill("binance", f"{pair}:{r['id']}", r["time"], b, q,
                                       "buy" if r.get("isBuyer") else "sell",
                                       r.get("price"), r.get("qty"),
                                       r.get("commission"), r.get("commissionAsset")))
                explained.update({b, q, str(r.get("commissionAsset") or "").upper()})
            from_id = int(rows[-1]["id"]) + 1
            cursors[pair] = from_id
            bq[pair] = [b, q]
            last[pair] = max(last.get(pair, 0.0), int(rows[-1]["time"]) / 1000.0)
            time.sleep(0.25)
            if len(rows) < 1000:
                break
        chk[pair] = float(now9)
        polled.add(pair)
        time.sleep(0.15)

    n_dirty = n_tgt = n_safe = n_sweep = 0
    open_now = None
    try:
        if lock_chg or any(a in quotes_all or pairs_of(a) for a in dirty):
            try:
                oo = call("/api/v3/openOrders", {})
                if isinstance(oo, list):
                    open_now = sorted({str(o.get("symbol") or "").upper() for o in oo if isinstance(o, dict) and o.get("symbol")})
            except RateLimited:
                raise
            except Exception as e9:   # noqa: BLE001 [optional]
                log.warning("binance 미체결 주문 조회 실패(표적 조회 재료만 생략): %s", _xm(repr(e9))[:120])
        for p9 in sorted(p for p, v in cand.items() if v[0] in dirty):
            poll(p9, *cand[p9])
            n_dirty += 1
        unexpl = {a for a in dirty if a in quotes_all and a not in explained and a not in touch}
        if unexpl:
            recent = {_bn_split(p9, bq, uni)[0] for p9, t9 in last.items() if now9 - t9 < BN_RECENT_SEC}
            opn = {_bn_split(s9, bq, uni)[0] for s9 in (open_prev | set(open_now or ()))}
            tb = set(cur) | recent | opn
            tgt = set()
            for b9 in tb:
                for p9, bb9, qq9 in pairs_of(b9):
                    if qq9 in unexpl and p9 not in polled and p9 not in inv and bb9 != qq9:
                        tgt.add((p9, bb9, qq9))
            for p9, bb9, qq9 in sorted(tgt):
                poll(p9, bb9, qq9)
                n_tgt += 1
                cand.setdefault(p9, (bb9, qq9))
        poll9 = max(60, int(_POLL_HINT[0] or POLL_SEC))
        due = sorted((p for p in cand if p not in polled and now9 - chk.get(p, 0.0) >= BN_IDLE_SEC), key=lambda p: (chk.get(p, 0.0), p))
        cap1 = max(8, int(len(cand) * poll9 * 1.25 / BN_IDLE_SEC) + 1)
        for p9 in due[:cap1]:
            if p9 in inv:
                continue
            poll(p9, *cand[p9])
            n_safe += 1
        fs9 = st.get("bn_first_sweep") if isinstance(st.get("bn_first_sweep"), dict) else None
        if uni and fs9 is not None:
            done9 = {str(x) for x in (fs9.get("done") or [])} | polled
            need9 = {s9 for s9 in uni if s9 not in inv and uni[s9][0] != uni[s9][1]}
            todo9 = sorted(need9 - done9)
            fs9["done"], fs9["n"] = sorted(done9), len(done9 & need9)
            n2 = int(len(need9) * poll9 / BN_SWEEP_SEC) + 1
            t_end9 = time.time() + BN_FIRST_SWEEP_SEC
            for k9, p9 in enumerate(todo9):
                if k9 >= n2 and time.time() >= t_end9:
                    break
                poll(p9, uni[p9][0], uni[p9][1])
                n_sweep += 1
                fs9["done"].append(p9)
                done9.add(p9)
                fs9["n"] = len(done9 & need9)
            if not (need9 - done9 - set(inv)):
                st.pop("bn_first_sweep", None)
                st["bn_sweep_full"] = now9
                _recon_hold_clear(st, "first_sweep")
                fs9 = None
                log.info("binance 전 심볼 안전망 첫 바퀴 완료(%d개) — 이제 잔고 대사 시작", len(need9))
        elif uni:
            rest = sorted(s9 for s9 in uni if s9 not in cand and s9 not in inv and uni[s9][0] != uni[s9][1])
            if rest:
                n2 = int(len(rest) * poll9 / BN_SWEEP_SEC) + 1
                pos = int(st.get("bn_sweep_pos") or 0) % len(rest)
                for p9 in (rest[pos:] + rest[:pos])[:n2]:
                    poll(p9, uni[p9][0], uni[p9][1])
                    n_sweep += 1
                st["bn_sweep_pos"] = (pos + n2) % len(rest)
    except (RateLimited, SignatureExpired) as e:
        partial = _xm(str(e))[:160]
    if isinstance(st.get("bn_first_sweep"), dict) and polled:
        fsd9 = st["bn_first_sweep"]
        fsd9["done"] = sorted({str(x) for x in (fsd9.get("done") or [])} | polled)
    if open_now is not None:
        st["bn_open"] = open_now
    if isinstance(st.get("bn_first_sweep"), dict):
        if not _recon_hold(st, "first_sweep", now9, "후보 밖 전 심볼 첫 바퀴 진행 중(%d개 확인)" % int(st["bn_first_sweep"].get("n") or 0)):
            st.pop("bn_first_sweep", None)
            _recon_hold_clear(st, "first_sweep")
            log.warning("binance 전 심볼 첫 바퀴가 %d시간 넘게 못 끝남 — 잔고 대사 보류 해제(늦게 찾은 체결은 core 늦은 행 흡수)", RECON_HOLD_CAP // 3600)
    st["extra_bases"] = sorted(set(st["extra_bases"]) | {cand[p9][0] for p9 in polled if p9 in cursors and p9 in cand})
    st["invalid_at"] = {p9: int(t9) for p9, t9 in inv.items()}
    st["invalid_pairs"] = sorted(inv)
    st["pair_cursor"] = cursors
    st["pair_bq"] = {p9: v9 for p9, v9 in bq.items() if p9 in cursors}
    st["pair_chk"] = {p9: int(t9) for p9, t9 in chk.items() if p9 in cand or p9 in cursors}
    st["pair_last"] = {p9: int(t9) for p9, t9 in last.items() if p9 in cursors}

    m_cursors = dict(st.get("margin_cursor") or {})
    m_inv = _bn_inv_load(st.get("margin_invalid"), st.get("margin_invalid_at"), None, now9)
    m_chk = {str(k): float(v) for k, v in (st.get("margin_chk") or {}).items() if isinstance(v, (int, float))}
    n_margin = 0
    if partial is None:
        try:
            d2 = call("/sapi/v1/margin/account", {})
            mcur = {}
            for a in d2.get("userAssets") or []:
                vals = [_dstr(a.get(k) or 0) for k in ("free", "locked", "borrowed", "interest", "netAsset")]
                if any(v9 != "0" for v9 in vals):
                    mcur[str(a.get("asset") or "").upper()] = vals
            d3 = call("/sapi/v1/margin/isolated/account", {})
            icur = {}
            for p in d3.get("assets") or []:
                if not p.get("symbol"):
                    continue
                sig9 = []
                for side in ("baseAsset", "quoteAsset"):
                    a9 = p.get(side) or {}
                    sig9 += [str(a9.get("asset") or "").upper()] + [_dstr(a9.get(k) or 0) for k in ("free", "locked", "borrowed", "interest", "netAsset")]
                icur[str(p["symbol"]).upper()] = sig9
            mprev = st.get("m_bal") if isinstance(st.get("m_bal"), dict) else None
            iprev = st.get("m_iso") if isinstance(st.get("m_iso"), dict) else None
            mdirty = set(mcur) if mprev is None else {a for a in set(mcur) | set(mprev) if mprev.get(a) != mcur.get(a)}
            idirty = set(icur) if iprev is None else {s9 for s9 in set(icur) | set(iprev) if iprev.get(s9) != icur.get(s9)}
            mpairs = {}
            for ck in m_cursors:
                pr = ck[2:]
                b9, q9 = _bn_split(pr, bq, uni)
                mpairs[ck] = (pr, "TRUE" if ck.startswith("i:") else "FALSE", b9, q9)
            for b9 in sorted(mcur):
                for p9, bb9, q9 in pairs_of(b9):
                    if bb9 != q9 and (q9 in BINANCE_QUOTES or not uni or uni[p9][3]):
                        mpairs.setdefault(f"c:{p9}", (p9, "FALSE", bb9, q9))
            for s9 in icur:
                b9, q9 = _bn_split(s9, bq, uni)
                mpairs.setdefault(f"i:{s9}", (s9, "TRUE", b9, q9))
            for ck in sorted(mpairs):
                pair, iso_flag, b9, q9 = mpairs[ck]
                if ck in m_inv:
                    continue
                if not b9 or not q9 or b9 == q9:
                    log.warning("binance 마진 페어 쿼트 미상 %s — 스킵", pair)
                    m_inv[ck] = float(now9)
                    continue
                hit = (pair in idirty) if iso_flag == "TRUE" else (b9 in mdirty or q9 in mdirty)
                if not hit and now9 - m_chk.get(ck, 0.0) < BN_IDLE_SEC:
                    continue
                from_id = int(m_cursors.get(ck) or 0)
                while True:
                    try:
                        n_margin += 1
                        rows = call("/sapi/v1/margin/myTrades",
                                    {"symbol": pair, "isIsolated": iso_flag,
                                     "fromId": from_id, "limit": 500})
                    except urllib.error.HTTPError as e:
                        body = _err_body(e)[:120]
                        if e.code == 400 and ("-1121" in body or "-11001" in body):
                            m_inv[ck] = float(now9)
                            break
                        if e.code == 400 and "-1021" in body:
                            raise SignatureExpired(f"binance margin myTrades {pair} -1021(타임스탬프 창 밖)") from None
                        raise
                    if not rows:
                        break
                    for r in rows:
                        fills.append(norm_fill(
                            "binance", f"m{'i' if iso_flag == 'TRUE' else ''}:{pair}:{r['id']}",
                            r["time"], b9, q9,
                            "buy" if r.get("isBuyer") else "sell",
                            r.get("price"), r.get("qty"),
                            r.get("commission"), r.get("commissionAsset")))
                    from_id = int(rows[-1]["id"]) + 1
                    m_cursors[ck] = from_id
                    bq.setdefault(pair, [b9, q9])
                    time.sleep(0.25)
                    if len(rows) < 500:
                        break
                m_chk[ck] = float(now9)
                time.sleep(0.15)
            st["m_bal"], st["m_iso"] = mcur, icur
            st["margin_chk"] = {k9: int(v9) for k9, v9 in m_chk.items() if k9 in mpairs}
            _recon_hold_clear(st, "margin")
        except (RateLimited, SignatureExpired) as e9m:
            partial = _xm(str(e9m))[:160]
        except Exception as e9m:  # noqa: BLE001 [fallback]
            msg9m = _xm(repr(e9m))
            if isinstance(e9m, urllib.error.HTTPError):
                msg9m += " " + _xm(_err_body(e9m)[:200])
            if any(k9 in msg9m for k9 in _DENY_SIGS):
                _recon_hold_clear(st, "margin")
                log.warning("binance 마진 체결 수집 생략(권한 없음/마진 미개설 — 스팟은 정상): %s", msg9m[:140])
            else:
                held9 = _recon_hold(st, "margin", now9, "마진 체결 수집 실패")
                log.warning("binance 마진 체결 수집 생략(다음 주기 재시도 — 스팟은 정상 · %s): %s",
                            "이번 주기 잔고 승격 보류" if held9 else "보류 상한 지남 — 대사 계속", msg9m[:140])
    st["margin_invalid_at"] = {k9: int(v9) for k9, v9 in m_inv.items()}
    st["margin_invalid"] = sorted(m_inv)
    st["margin_cursor"] = m_cursors
    st["pair_bq"] = {p9: v9 for p9, v9 in bq.items() if p9 in cursors or any(ck[2:] == p9 for ck in m_cursors)}
    if partial is None:
        st["bn_bal"] = cur
        st["bn_dirty"] = []
        st["bn_acct_at"] = acct_at
    else:
        st["partial"] = partial
    st["bn_stats"] = {"calls": n_calls[0] + 1 + n_margin, "dirty": n_dirty, "target": n_tgt, "safety": n_safe, "sweep": n_sweep,
                      "margin": n_margin, "cand": len(cand), "at": now9}
    if late_before:
        lim9 = (late_before - BN_LATE_MARGIN) * 1000
        for f in fills:
            if f["ts"] < lim9:
                f["late"] = 1
    collected_until = int(time.time() * 1000) + 60000
    return [f for f in fills if t0 * 1000 <= f["ts"] <= collected_until]


def convert_binance(env, t0: int, t1: int):
    call = _binance_caller(env)
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 30 * DAY - 1, int(t1))
        start = s * 1000
        end_ms = min(e * 1000 + 999, int(t1) * 1000)
        for _pg in range(50):
            d = call("/sapi/v1/convert/tradeFlow", {"startTime": start, "endTime": end_ms, "limit": 1000})
            rows = d.get("list") if isinstance(d, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError(f"binance convert 응답 형식 오류: {str(d)[:100]}")
            for r in rows:
                if not isinstance(r, dict) or str(r.get("orderStatus") or "").upper() != "SUCCESS":
                    continue
                f9 = _cv_fill("binance", r.get("orderId") or r.get("quoteId"), r.get("createTime"), r.get("fromAsset"),
                              r.get("fromAmount"), r.get("toAsset"), r.get("toAmount"))
                if f9 is None:
                    raise RuntimeError("binance convert SUCCESS 필드 누락/형식 오류")
                out.append(f9)
            time.sleep(PACE)
            if not d.get("moreData") or not rows:
                break
            mx = max(int(float(r.get("createTime") or 0)) for r in rows if isinstance(r, dict))
            if mx < start:
                raise RuntimeError("binance convert 페이지 시각 미전진")
            start = mx + 1
        else:
            raise RuntimeError("binance convert 30일 창 50페이지 초과")
        s = e + 1
    return out


def convert_binance_dust(env, t0: int, t1: int):
    call = _binance_caller(env)
    out = []
    s = int(t0)
    while s < t1:
        e = min(s + 90 * DAY - 1, int(t1))
        d = call("/sapi/v1/asset/dribblet", {"startTime": s * 1000, "endTime": min(e * 1000 + 999, int(t1) * 1000)})
        if not isinstance(d, dict):
            raise RuntimeError("binance dribblet 응답 형식 오류")
        rows = d.get("userAssetDribblets")
        if rows is None and int(d.get("total") or 0) == 0:
            rows = []
        if not isinstance(rows, list):
            raise RuntimeError("binance dribblet 목록 누락/형식 오류")
        if int(d.get("total") or 0) > len(rows) and len(rows) >= 100:
            raise RuntimeError("binance dribblet 조각 하나에 100건 초과(목록 상한) — 조각 완료 보류")
        for g in rows:
            if not isinstance(g, dict):
                continue
            for det in g.get("userAssetDribbletDetails") or []:
                if not isinstance(det, dict):
                    continue
                fa = str(det.get("fromAsset") or "").upper()
                tid = det.get("transId") or g.get("transId")
                ta = str(det.get("targetAsset") or g.get("targetAsset") or "BNB").strip().upper() or "BNB"
                f9 = _cv_fill("binance", f"dust:{tid}:{fa}", det.get("operateTime") or g.get("operateTime"), fa, det.get("amount"),
                              ta, det.get("transferedAmount"))
                if f9 is None:
                    raise RuntimeError("binance dribblet 세부 필드 누락/형식 오류")
                f9["cv"]["kind"] = "dust"
                out.append(f9)
        time.sleep(PACE)
        s = e + 1
    return out


@_clock_retry
def _binance_signed(env, path, params=None, method="GET"):
    _gov_prepare("api.binance.com", path)
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    p = dict(params or {})
    p["timestamp"] = _srv_ms("api.binance.com")
    p["recvWindow"] = 10000
    qs = urllib.parse.urlencode(p)
    sig = ex_sign.binance_sign(sec, qs)
    url = f"https://api.binance.com{path}?{qs}&signature={sig}"
    return _http_json_err(url, {"X-MBX-APIKEY": key},
                          data=(b"" if method == "POST" else None),
                          method=(method if method != "GET" else None))


def _bn_amt(row, key, what):
    if not isinstance(row, dict):
        raise RuntimeError(f"{what} 행 형식 오류 — 부분 잔고 발행 보류")
    v = row.get(key)
    if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
        raise RuntimeError(f"{what} 금액 필드 누락({key}) — 부분 잔고 발행 보류")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise RuntimeError(f"{what} 금액 형식 오류({key}) — 부분 잔고 발행 보류") from None
    if f != f or f in (float("inf"), float("-inf")):
        raise RuntimeError(f"{what} 금액 형식 오류({key}) — 부분 잔고 발행 보류")
    return f


def _bn_sym(row, key, what):
    v = row.get(key) if isinstance(row, dict) else None
    if not isinstance(v, str) or not v.strip():
        raise RuntimeError(f"{what} 통화 필드 누락({key}) — 부분 잔고 발행 보류")
    return v.strip().upper()


_BN_TOTAL_WARNED = set()


def _bn_total_check(total, got, what):
    if total is None:
        if what not in _BN_TOTAL_WARNED:
            _BN_TOTAL_WARNED.add(what)
            log.warning("%s 응답에 total 없음 — 목록 완전성 검증 생략(명세와 다름 · 종전대로 진행)", what)
        return
    try:
        n = int(str(total).strip())
    except (TypeError, ValueError, AttributeError):
        raise RuntimeError(f"{what} total 형식 오류 — 부분 잔고 발행 보류") from None
    if n != int(got):
        raise RuntimeError(f"{what} 받은 행 {int(got)} ≠ total {n} — 부분 잔고 발행 보류(다음 주기 재조회)")


def _bal_binance(env):
    out = _Bal()
    d = _binance_signed(env, "/api/v3/account")
    spot_ld = {}
    if not isinstance(d, dict):
        raise RuntimeError("binance 스팟 잔고 응답 형식 오류 — 부분 잔고 발행 보류")
    for b in _balance_rows(d.get("balances")):
        a0 = _bn_sym(b, "asset", "binance 스팟")
        v0 = _bn_amt(b, "free", "binance 스팟") + _bn_amt(b, "locked", "binance 스팟")
        _add_to(out, a0, v0)
        if a0.startswith("LD") and len(a0) > 2 and v0 > 0:
            spot_ld[a0] = v0
    earn_flex = []
    earn_coll = {}

    def _cross(o):
        d2 = _binance_signed(env, "/sapi/v1/margin/account")
        if not isinstance(d2, dict):
            raise RuntimeError("binance 교차 마진 응답 형식 오류 — 부분 잔고 발행 보류")
        for a in _balance_rows(d2.get("userAssets")):
            sym = _bn_sym(a, "asset", "binance 교차 마진")
            v = _bn_amt(a, "netAsset", "binance 교차 마진")
            if v < 0:
                _debt_add(o, "binance", "margin", sym, v)
            else:
                _add_to(o, sym, v)

    def _iso(o):
        d2 = _binance_signed(env, "/sapi/v1/margin/isolated/account")
        if not isinstance(d2, dict):
            raise RuntimeError("binance 격리 마진 응답 형식 오류 — 부분 잔고 발행 보류")
        for pair in _balance_rows(d2.get("assets")):
            if not isinstance(pair, dict):
                raise RuntimeError("binance 격리 마진 행 형식 오류 — 부분 잔고 발행 보류")
            for side in ("baseAsset", "quoteAsset"):
                a = pair.get(side)
                if not isinstance(a, dict):
                    raise RuntimeError(f"binance 격리 마진 {side} 누락 — 부분 잔고 발행 보류")
                sym = _bn_sym(a, "asset", "binance 격리 마진")
                v = _bn_amt(a, "netAsset", "binance 격리 마진")
                if v < 0:
                    _debt_add(o, "binance", "isolated", sym, v)
                else:
                    _add_to(o, sym, v)

    def _fund(o):
        rows = _binance_signed(env, "/sapi/v1/asset/get-funding-asset", method="POST")
        for a in _balance_rows(rows):
            _add_to(o, _bn_sym(a, "asset", "binance 펀딩"),
                    sum(_bn_amt(a, k9, "binance 펀딩") for k9 in ("free", "locked", "freeze", "withdrawing")))

    def _futures(o):
        key2, sec2 = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
        _gov_prepare("fapi.binance.com", "/fapi/v2/balance")
        q2 = urllib.parse.urlencode({"timestamp": _srv_ms("fapi.binance.com"),
                                     "recvWindow": 10000})
        sig2 = ex_sign.binance_sign(sec2, q2)
        rows = _http_json_err(f"https://fapi.binance.com/fapi/v2/balance?{q2}&signature={sig2}",
                              {"X-MBX-APIKEY": key2})
        for a in _balance_rows(rows):
            _add_to(o, _bn_sym(a, "asset", "binance 선물"), _bn_amt(a, "balance", "binance 선물"))

    def _earn(o):
        flex9 = set()
        coll9 = {}
        for path, amt_key in (("/sapi/v1/simple-earn/flexible/position", "totalAmount"),
                              ("/sapi/v1/simple-earn/locked/position", "amount")):
            page, got9 = 1, 0
            while page <= 20:
                d2 = _binance_signed(env, path, {"current": page, "size": 100})
                if not isinstance(d2, dict):
                    raise RuntimeError("binance Earn 응답 형식 오류 — 부분 잔고 발행 보류")
                rows = _balance_rows(d2.get("rows"))
                for r2 in rows:
                    _earn_amount(o, r2, "asset", amt_key)
                    if amt_key == "totalAmount":
                        a9 = r2["asset"].strip().upper()
                        flex9.add(a9)
                        c9 = r2.get("collateralAmount")
                        if c9 not in (None, ""):
                            try:
                                cv9 = float(c9)
                            except (TypeError, ValueError):
                                raise RuntimeError("binance Earn 담보량 형식 오류 — 부분 잔고 발행 보류") from None
                            if cv9 > 0:
                                coll9[a9] = coll9.get(a9, 0.0) + cv9
                got9 += len(rows)
                if len(rows) < 100:
                    break
                page += 1
                time.sleep(PACE)
            else:
                raise RuntimeError("binance Earn 20페이지 초과 — 부분 잔고 폐기(상한 조정 필요)")
            _bn_total_check(d2.get("total"), got9, "binance Earn " + ("유동" if amt_key == "totalAmount" else "고정"))
        earn_flex[:] = sorted(flex9)
        earn_coll.clear()
        earn_coll.update(coll9)

    def _loan(o):
        page, got9 = 1, 0
        while page <= 20:
            d2 = _binance_signed(env, "/sapi/v2/loan/flexible/ongoing/orders", {"current": page, "limit": 100})
            if not isinstance(d2, dict):
                raise RuntimeError("binance flexible loan 응답 형식 오류")
            rows = _balance_rows(d2.get("rows"))
            got9 += len(rows)
            for r2 in rows:
                ck, cv = _loan_amt(r2, "collateralCoin", "collateralAmount", "binance 대출 담보")
                lk, lv = _loan_amt(r2, "loanCoin", "totalDebt", "binance 대출 차입")
                ex9 = {}
                try:
                    ex9["ltv"] = float(r2.get("currentLTV"))
                except (TypeError, ValueError):
                    pass
                _loan_add(o, "binance", "loan", "flexible-loan", "바이낸스 담보대출", {ck: cv}, {lk: lv}, extra=ex9)
            if len(rows) < 100:
                _bn_total_check(d2.get("total"), got9, "binance 담보대출")
                return
            page += 1
            time.sleep(PACE)
        raise RuntimeError("binance flexible loan 20페이지 초과 — 부분 잔고 폐기")

    for src, fn in (("margin", _cross), ("isolated", _iso),
                    ("funding", _fund), ("earn", _earn), ("futures", _futures)):
        time.sleep(PACE)
        _sub_bal("binance", src, fn, out)
    time.sleep(PACE)
    _sub_bal("binance", "loan", _loan, out, lenient=True)
    if "earn" in out.sources:
        for x9 in earn_flex:
            k9 = "LD" + x9
            if k9 in spot_ld and k9 in out:
                out[k9] -= spot_ld[k9]
                if out[k9] <= 1e-12:
                    del out[k9]
    if "earn" in out.sources and "loan" in out.sources and earn_coll:
        lc9 = {}
        for ln9 in out.loans:
            if isinstance(ln9, dict) and ln9.get("ex") == "binance":
                for k9, v9 in (ln9.get("collateral") or {}).items():
                    lc9[k9] = lc9.get(k9, 0.0) + float(v9)
        for k9, v9 in lc9.items():
            dup9 = min(v9, earn_coll.get(k9, 0.0))
            if dup9 > 0 and k9 in out:
                out[k9] -= dup9
                if out[k9] <= 1e-12:
                    del out[k9]
    return out


BN_INCOME_KEEP_DAYS = 364


BN_INCOME_MS_PAGES = 20


def _fut_binance(env):
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]

    @_clock_retry
    def fcall(path, extra=None):
        _gov_prepare("fapi.binance.com", path)
        q = dict(extra or {})
        q["timestamp"] = _srv_ms("fapi.binance.com")
        q["recvWindow"] = 10000
        qs = urllib.parse.urlencode(q)
        sig = ex_sign.binance_sign(sec, qs)
        return _http_json_err(f"https://fapi.binance.com{path}?{qs}&signature={sig}",
                              {"X-MBX-APIKEY": key})

    st = statefile.read_json(_fut_path("binance"), {})
    acct = fcall("/fapi/v2/account")
    poss = []
    rows9 = fcall("/fapi/v2/positionRisk")
    if not isinstance(rows9, list) or any(not isinstance(p, dict) for p in rows9):
        raise RuntimeError("binance positionRisk 형식 오류 — 스냅숏 보류")
    for p in rows9:
        amt = _fut_req(p.get("positionAmt"), "수량(positionAmt)")
        if amt == 0:
            continue
        poss.append({"symbol": p.get("symbol"), "side": "LONG" if amt > 0 else "SHORT",
                     "qty": abs(amt), "entry": float(p.get("entryPrice") or 0),
                     "mark": float(p.get("markPrice") or 0),
                     "upnl": _fut_opt(p.get("unRealizedProfit")),
                     "leverage": p.get("leverage"),
                     "margin_mode": (str(p.get("marginType")).lower() if str(p.get("marginType") or "").lower() in ("cross", "isolated") else None),
                     "liq": float(p.get("liquidationPrice") or 0)})
    cross_syms9 = {str(p9.get("symbol") or "") for p9 in poss if p9.get("margin_mode") != "isolated"}
    cur = (st.get("cursor") or {}).get("income")
    if not cur:
        first_t0 = fut_first_t0("binance", time.time())
        cur = (max(first_t0, int(time.time()) - BN_INCOME_KEEP_DAYS * 86400) if first_t0 is not None else int(time.time()) - 150 * 86400) * 1000
    cur = int(cur)
    ev = list(st.get("events") or [])
    seen = {(r.get("uid") or f"{r['t']}:{r['kind']}:{r['amount']}") for r in ev}
    kmap = {"REALIZED_PNL": "REALIZED", "FUNDING_FEE": "FUNDING",
            "COMMISSION": "FEE", "TRANSFER": "TRANSFER",
            "INSURANCE_CLEAR": "REALIZED", "DELIVERED_SETTELMENT": "REALIZED", "DELIVERED_SETTLEMENT": "REALIZED",
            "COMMISSION_REBATE": "FEE", "API_REBATE": "FEE", "REFERRAL_KICKBACK": "FEE"}
    pages = 0
    cov9 = None
    n_ev0 = len(ev)
    while pages < 5:
        time.sleep(PACE)
        rows = fcall("/fapi/v1/income", {"startTime": cur, "limit": 1000}) or []

        def _take(rows9):
            n9 = 0
            for r in rows9:
                uid = f"bn:{r.get('tranId')}:{r.get('incomeType')}:{r.get('time')}"
                if uid in seen:
                    continue
                seen.add(uid)
                n9 += 1
                e9 = {"t": int(r.get("time") or 0), "symbol": r.get("symbol") or "",
                      "kind": kmap.get(r.get("incomeType"), "OTHER"),
                      "amount": float(r.get("income") or 0), "uid": uid}
                if str(r.get("asset") or "").strip():
                    e9["asset"] = str(r.get("asset")).strip().upper()
                ev.append(e9)
            return n9
        _take(rows)
        if rows:
            nxt = max(int(r.get("time") or 0) for r in rows)
            if len(rows) >= 1000 and nxt <= cur:
                for pg9 in range(1, BN_INCOME_MS_PAGES + 1):
                    time.sleep(PACE)
                    rows_ms = fcall("/fapi/v1/income", {"startTime": cur, "endTime": cur, "page": pg9, "limit": 1000}) or []
                    if any(int(r.get("time") or 0) != cur for r in rows_ms):
                        raise RuntimeError("binance income 같은 ms 페이지 응답에 다른 시각 — 스냅샷 보류")
                    if _take(rows_ms) == 0 and pg9 > 1 and len(rows_ms) >= 1000:
                        raise RuntimeError("binance income 같은 ms 페이지가 새 줄을 안 줌(page 미지원?) — 스냅샷 보류")
                    if len(rows_ms) < 1000:
                        break
                else:
                    raise RuntimeError(f"binance income 같은 ms {BN_INCOME_MS_PAGES * 1000}건 초과 — 스냅샷 보류(다음 주기 다시)")
                nxt = cur + 1
            cur = max(cur, nxt)
        if len(rows) < 1000:
            break
        pages += 1
    else:
        cov9 = (int(cur) - 1) // 1000
        log.info("binance 선물 정산 따라잡는 중(5쪽 상한) — 파일 시각 = 확인된 정산 끝 %s", time.strftime("%m-%d %H:%M:%S", time.localtime(cov9)))
    _fnum9 = _fut_opt
    ap9, cmm9 = acct.get("positions"), None
    if (isinstance(ap9, list) and all(isinstance(a9, dict) and isinstance(a9.get("isolated"), bool) for a9 in ap9)
            and cross_syms9 <= {str(a9.get("symbol") or "") for a9 in ap9 if a9["isolated"] is False}):
        vals9 = [_fnum9(a9.get("maintMargin")) for a9 in ap9 if a9["isolated"] is False]
        if all(v9 is not None and v9 >= 0 for v9 in vals9):
            cmm9 = sum(vals9)
    cwb9, cup9 = _fnum9(acct.get("totalCrossWalletBalance")), _fnum9(acct.get("totalCrossUnPnl"))
    cmb9 = (cwb9 + cup9) if cwb9 is not None and cup9 is not None else None
    cross_ok9 = cmm9 is not None and cmb9 is not None
    _fut_write("binance",
               {"balance": float(acct.get("totalWalletBalance") or 0),
                "note": f"가용 증거금 {float(acct.get('availableBalance') or 0):,.2f} USDT",
                "maint_margin": cmm9 if cross_ok9 else None,
                "margin_balance": cmb9 if cross_ok9 else None,
                "init_margin": float(acct.get("totalInitialMargin") or 0),
                "mm_scope": "cross" if cross_ok9 else None},
               poss, ev, {"income": cur}, covered_through=cov9)
    _px_safe("binance", lambda: _px_binance(fcall, ev, ev[n_ev0:]))


def _px_binance(fcall, ev, new_ev):
    now_ms = int(time.time() * 1000)
    st = fut_rcpt.load("binance")
    cur = dict(st.get("cursor") or {})

    def ok_job(x):
        return (isinstance(x, (list, tuple)) and len(x) == 3 and isinstance(x[0], str) and x[0]
                and fut_rcpt.num(x[1]) is not None and fut_rcpt.num(x[2]) is not None and fut_rcpt.num(x[1]) <= fut_rcpt.num(x[2]))
    plan = [[x[0], int(x[1]), int(x[2])] for x in (cur.get("bf_plan") if isinstance(cur.get("bf_plan"), list) else []) if ok_job(x)]
    if not cur.get("bf_done") and not isinstance(cur.get("bf_plan"), list):
        plan = fut_rcpt.bn_plan(ev, now_ms)
        log.info("binance 선물 가격 과거 채움 계획 %d창", len(plan))
    elif cur.get("bf_done") and not plan and now_ms - (fut_rcpt.num(cur.get("rp_at")) or 0) >= PX_BN_REPLAN_MS:
        lo9 = now_ms - fut_rcpt.RETAIN_MS["binance"]
        tried = {u for u in (cur.get("rp_tried") if isinstance(cur.get("rp_tried"), list) else []) if isinstance(u, str)}
        miss = [e for e in fut_rcpt.bn_unmatched(ev, st.get("rows"), now_ms) if e.get("uid") not in tried]
        plan = fut_rcpt.bn_plan(miss, now_ms)
        live9 = {e.get("uid") for e in ev if isinstance(e, dict) and (fut_rcpt.num(e.get("t")) or 0) >= lo9}
        cur["rp_tried"] = sorted((tried & live9) | {e.get("uid") for e in miss if isinstance(e.get("uid"), str)})
        cur["rp_at"] = now_ms
        if plan:
            log.info("binance 선물 가격 다시 계획 — 가격 행 없는 정산 %d건 · %d창", len(miss), len(plan))
    jobs = fut_rcpt.bn_plan(new_ev, now_ms) + plan
    fails = {k: v for k, v in (cur.get("bf_fail") or {}).items() if isinstance(v, int)} if isinstance(cur.get("bf_fail"), dict) else {}
    rows, calls = [], 0
    try:
        while jobs and calls < PX_CALLS_MAX:
            sym, s9, e9 = jobs[0]
            start, end, finished = int(s9), int(e9), False
            try:
                while calls < PX_CALLS_MAX:
                    time.sleep(PACE)
                    got = fcall("/fapi/v1/userTrades", {"symbol": sym, "startTime": start, "endTime": end, "limit": 1000})
                    calls += 1
                    if not isinstance(got, list):
                        raise RuntimeError("binance userTrades 형식 오류")
                    rows += fut_rcpt.rows_binance(got)
                    if len(got) < 1000:
                        finished = True
                        break
                    nxt = max((int(fut_rcpt.num(t.get("time")) or 0) for t in got if isinstance(t, dict)), default=start)
                    if nxt >= end:
                        finished = True
                        break
                    if nxt <= start:
                        log.warning("binance userTrades %s 같은 ms 1,000건 넘음 — 그 창 나머지는 건너뜀(가격 일부 없음)", sym)
                        finished = True
                        break
                    start = nxt
                    jobs[0] = [sym, start, end]
            except RateLimited:
                raise
            except Exception as e9x:   # noqa: BLE001 [fallback]
                fk = f"{sym}:{end}"
                n9 = fails.get(fk, 0) + 1
                msg9 = _xm(repr(e9x))
                if n9 >= PX_BN_FAIL_MAX or '"code":-1121' in msg9:
                    jobs.pop(0)
                    fails.pop(fk, None)
                    log.warning("binance 선물 가격 창 버림(%s · %d번 실패 — 다른 창은 계속): %s", sym, n9, msg9[:160])
                else:
                    fails[fk] = n9
                    jobs.append(jobs.pop(0))
                    log.warning("binance 선물 가격 창 실패 %d/%d(%s — 맨 뒤로 · 다음 주기): %s", n9, PX_BN_FAIL_MAX, sym, msg9[:160])
                break
            if finished:
                jobs.pop(0)
                fails.pop(f"{sym}:{end}", None)
            else:
                jobs[0] = [sym, start, end]
    finally:
        cur["bf_plan"] = jobs
        live_f = {f"{x[0]}:{int(x[2])}" for x in jobs}
        cur["bf_fail"] = {k: v for k, v in fails.items() if k in live_f}
        if not cur["bf_fail"]:
            cur.pop("bf_fail", None)
        if not jobs:
            if not cur.get("bf_done"):
                log.info("binance 선물 가격 과거 채움 끝")
                cur["rp_at"] = now_ms
            cur["bf_done"] = True
            cur.pop("bf_plan", None)
        fut_rcpt.update("binance", rows, now_ms, cursor=cur)


@_clock_retry
def _bn_deriv_get(env, host, path, params=None):
    _gov_prepare(host, path)
    key, sec = env["TJ_BINANCE_KEY"], env["TJ_BINANCE_SECRET"]
    q = dict(params or {})
    q["timestamp"] = _srv_ms(host)
    q["recvWindow"] = 10000
    qs = urllib.parse.urlencode(q)
    sig = ex_sign.binance_sign(sec, qs)
    return _http_json_err(f"https://{host}{path}?{qs}&signature={sig}", {"X-MBX-APIKEY": key})


BN_DIV_PATH = "/sapi/v1/asset/assetDividend"
BN_DIV_LIMIT = 500
BN_DIV_SPAN = 89 * DAY
BN_DIV_MIN_SPLIT_MS = 1000
BN_DIV_MAX_CALLS = 300
BN_DIV_SKIP_WORDS = ("swap", "redenomination", "rebrand", "migration", "conversion", "convert", "token upgrade", "contract upgrade")


def dividend_binance(env: dict, t0: int, t1: int, call: "object" = None, pace: "float | None" = None) -> list:
    call = call or _binance_caller(env)
    pace = PACE if pace is None else pace
    got, n_call = {}, [0]

    def window(s_ms, e_ms):
        n_call[0] += 1
        if n_call[0] > BN_DIV_MAX_CALLS:
            raise RuntimeError(f"binance assetDividend 조회 {BN_DIV_MAX_CALLS}회 초과(창 나누기 과다) — 이번 주기 보류")
        d = call(BN_DIV_PATH, {"startTime": int(s_ms), "endTime": int(e_ms), "limit": BN_DIV_LIMIT})
        if not isinstance(d, dict) or d.get("total") is None:
            raise RuntimeError(f"binance assetDividend 응답 형식 오류(total 없음): {str(d)[:100]}")
        try:
            total_n = int(str(d.get("total")).strip())
        except (TypeError, ValueError):
            raise RuntimeError("binance assetDividend total 형식 오류") from None
        rows = d.get("rows")
        if rows is None and total_n == 0:
            rows = []
        if not isinstance(rows, list):
            raise RuntimeError(f"binance assetDividend 응답 형식 오류: {str(d)[:100]}")
        time.sleep(pace)
        if len(rows) >= BN_DIV_LIMIT or total_n > len(rows):
            if e_ms - s_ms < BN_DIV_MIN_SPLIT_MS:
                raise RuntimeError(f"binance assetDividend 1초 창에 {len(rows)}건 이상 — 나눌 수 없음(창 보류)")
            mid_ms = (int(s_ms) + int(e_ms)) // 2
            window(s_ms, mid_ms)
            window(mid_ms, e_ms)
            return
        for r in rows:
            if not isinstance(r, dict):
                raise RuntimeError("binance assetDividend 행 형식 오류")
            rid = r.get("id")
            asset = str(r.get("asset") or "").strip().upper()
            try:
                amt = Decimal(str(r.get("amount")))
                div_ms = int(float(r.get("divTime")))
            except (InvalidOperation, TypeError, ValueError):
                raise RuntimeError("binance assetDividend 수량·시각 형식 오류") from None
            if 0 < div_ms < 10 ** 12:
                div_ms *= 1000
            if rid in (None, "") or not asset or not amt.is_finite() or div_ms <= 0:
                raise RuntimeError("binance assetDividend 필드 누락(id·asset·amount·divTime)")
            info = r.get("enInfo")
            if amt <= 0 or not isinstance(info, str) or not info.strip() or any(w in info.lower() for w in BN_DIV_SKIP_WORDS):
                continue
            got[f"binance:div:{rid}"] = {"id": f"binance:div:{rid}", "ts": div_ms, "src": "income", "late": 1, "asset": asset, "base": asset,
                                         "amount": format(amt, "f"), "info": info[:80]}

    s = int(t0)
    if s >= int(t1):
        return []
    while True:
        e = min(s + BN_DIV_SPAN, int(t1))
        window(s * 1000, e * 1000)
        if e >= int(t1):
            break
        s = e
    return sorted(got.values(), key=lambda x: (x["ts"], x["id"]))
