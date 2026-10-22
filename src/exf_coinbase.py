from __future__ import annotations
import datetime
import hashlib
import uuid
import time
import urllib.parse
import ex_sign
import num_parse
from exf_net import PACE
from exf_net import _Bal
from exf_net import _PartialConvertRows
from exf_net import _add_to
from exf_net import _balance_rows
from exf_net import _clock_retry
from exf_net import _cv_fill
from exf_net import _gov_prepare
from exf_net import _recon_hold
from exf_net import _recon_hold_clear
from exf_net import _srv_ms
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
import logging

log = logging.getLogger('tj-exf')

HOST = "api.coinbase.com"
KEYS = ("TJ_COINBASE_KEY_NAME", "TJ_COINBASE_SECRET")
JWT_TTL = 120
OVERLAP = 3600
PAGE_MAX = 200
V2_LIMIT = 100
FILL_LIMIT = 100
_V2_TTL = 300
FIAT_LEDGER = ("USD",)
_SPOT_PLAT = ("", "ACCOUNT_PLATFORM_UNSPECIFIED", "ACCOUNT_PLATFORM_CONSUMER")
_BAL_TYPES = ("", "ACCOUNT_TYPE_UNSPECIFIED", "ACCOUNT_TYPE_CRYPTO", "ACCOUNT_TYPE_FIAT", "ACCOUNT_TYPE_VAULT")
_ST_DONE = {"completed"}
_ST_FAIL = {"canceled": "CANCELLED", "cancelled": "CANCELLED", "failed": "FAILED", "expired": "FAILED"}
_WD_TYPES = ("send", "fiat_withdrawal")
_DEP_TYPES = ("receive", "fiat_deposit")
_REWARD_TYPES = ("staking_reward", "inflation_reward", "interest", "earn_payout", "incentives_rewards_payout", "reward",
                 "subscription_rebate", "coinbase_one_rebate")
_CV_TYPES = ("buy", "sell", "trade")
_RAISE_DEP, _RAISE_POOL, _RAISE_DIST = "raise_offering_deposit", "raise_offering_pooling", "raise_offering_distribution"
RAISE_PAIR_SEC = 3600
_QUIET_TYPES = ("advanced_trade_fill", "transfer", "staking_transfer", "unstaking_transfer", "wrap_asset", "unwrap_asset",
                "vault_withdrawal", "pro_deposit", "pro_withdrawal", "exchange_deposit", "exchange_withdrawal", "request",
                "intx_deposit", "intx_withdrawal", "derivatives_settlement", "retail_simple_dust", "clawback",
                "incentives_shared_clawback", "subscription", "tx", "unsupported_asset_recovery",
                "fcm_futures_usdc_sell", "fcm_futures_usdc_sell_additional_encumberment_rollup")
_WARNED = set()
_V2 = {}
_KEY_D = {}


def _warn_once(key: str, msg: str, *a) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    log.warning(msg, *a)


def _key_d(sec: str) -> int:
    d = _KEY_D.get(sec)
    if d is None:
        d = _KEY_D[sec] = ex_sign.ec_p256_scalar(sec)
    return d


def jwt_for(env: dict, method: str, path: str, now_s: int) -> str:
    name = env[KEYS[0]]
    pl = {"sub": name, "iss": "cdp", "nbf": int(now_s), "exp": int(now_s) + JWT_TTL, "uri": f"{method} {HOST}{path}"}
    return ex_sign.jwt_es256(pl, _key_d(env[KEYS[1]]), name, uuid.uuid4().hex)


@_clock_retry
def _cb_get(env: dict, path: str, params: dict | None = None):
    _gov_prepare(HOST, path)
    tok = jwt_for(env, "GET", path, _srv_ms(HOST) // 1000)
    qs = urllib.parse.urlencode(params or {}, doseq=True)
    return http_json(f"https://{HOST}{path}" + (f"?{qs}" if qs else ""), {"Authorization": "Bearer " + tok})


def _ts_ms(s):
    v = str(s or "").strip()
    if len(v) < 19 or v[10] not in "Tt ":
        return None
    v = v[:10] + "T" + v[11:]
    if v[-1] in "Zz":
        v = v[:-1] + "+00:00"
    head, frac, tail = v[:19], "", v[19:]
    if tail.startswith("."):
        i = 1
        while i < len(tail) and tail[i].isdigit():
            i += 1
        frac, tail = tail[1:i][:6], tail[i:]
    if not tail:
        return None
    try:
        t = datetime.datetime.fromisoformat(head + ("." + frac.ljust(6, "0") if frac else "") + tail)
    except ValueError:
        return None
    return int(t.timestamp() * 1000)


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))


def bal_coinbase(env: dict):
    out = _Bal()
    ids = set()
    cur, n = "", 0
    while True:
        d = _cb_get(env, "/api/v3/brokerage/accounts", dict({"limit": 250}, **({"cursor": cur} if cur else {})))
        if not isinstance(d, dict):
            raise RuntimeError("coinbase accounts 응답 형식 오류")
        for a in _balance_rows(d.get("accounts")):
            _bal_row(out, a)
            ids.add(str((a or {}).get("uuid") or ""))
        n += 1
        nxt = str(d.get("cursor") or "")
        if d.get("has_next") is not True:
            break
        if not nxt or nxt == cur or n >= PAGE_MAX:
            raise RuntimeError("coinbase accounts 다음 쪽 커서 이상 — 부분 잔고 발행 보류")
        cur = nxt
        time.sleep(PACE)
    for a in _v2_pages(env, "/v2/accounts"):
        if str(a.get("id") or "") in ids:
            continue
        bal_d = a.get("balance") if isinstance(a.get("balance"), dict) else {}
        q, ccy = num_parse.to_dec(bal_d.get("amount")), str(bal_d.get("currency") or "").upper()
        if q is None or not ccy:
            raise RuntimeError("coinbase v2 계정 잔고 필드 누락 — 부분 잔고 발행 보류")
        if str(a.get("type") or "") == "fiat" and ccy not in FIAT_LEDGER:
            continue
        if q:
            _add_to(out, ccy, float(q))
    return out


def _bal_row(out, a) -> None:
    if not isinstance(a, dict):
        raise RuntimeError("coinbase 계정 행 형식 오류")
    ccy = str(a.get("currency") or "").upper()
    av, hd = num_parse.to_dec((a.get("available_balance") or {}).get("value")), num_parse.to_dec((a.get("hold") or {}).get("value") or "0")
    if not ccy or av is None or hd is None:
        raise RuntimeError("coinbase 계정 잔고 필드 누락 — 부분 잔고 발행 보류")
    q = av + hd
    plat, typ = str(a.get("platform") or ""), str(a.get("type") or "")
    if plat not in _SPOT_PLAT or typ not in _BAL_TYPES:
        if q:
            _warn_once("bal:" + plat + typ, "coinbase %s·%s 계정 잔고는 아직 안 셈(현물 계정만 — 선물·국제 계정 미지원): %s", plat, typ, ccy)
        return
    if typ == "ACCOUNT_TYPE_FIAT" and ccy not in FIAT_LEDGER:
        if q:
            _warn_once("fiat:" + ccy, "coinbase %s 법정통화 잔고는 원장 밖(USD 만 원장 안 현금)", ccy)
        return
    if q:
        _add_to(out, ccy, float(q))


def perm_of(d: object):
    if not isinstance(d, dict) or any(not isinstance(d.get(k), bool) for k in ("can_view", "can_trade", "can_transfer")):
        return None
    out = []
    if d["can_trade"]:
        out.append(("trade", "거래 (Trade — 주문)"))
    if d["can_transfer"]:
        out.append(("withdraw", "이체·출금 (Transfer — 송금·출금)"))
    if not d["can_view"] and not out:
        return None
    return out


def _v2_pages(env, path: str, stop=None) -> list:
    out, after, n = [], "", 0
    while True:
        prm = {"limit": V2_LIMIT, "order": "desc"}
        if after:
            prm["starting_after"] = after
        d = _cb_get(env, path, prm)
        rows = d.get("data") if isinstance(d, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"coinbase v2 {path[:40]} 응답 형식 오류")
        out += [r for r in rows if isinstance(r, dict)]
        n += 1
        nu = str(((d.get("pagination") or {}) if isinstance(d.get("pagination"), dict) else {}).get("next_uri") or "")
        if not nu or not rows or (stop and stop(rows)):
            return out
        after_q = urllib.parse.parse_qs(urllib.parse.urlsplit(nu).query).get("starting_after") or [""]
        nxt = str(rows[-1].get("id") or "") if not after_q[0] else after_q[0]
        if not nxt or nxt == after or n >= PAGE_MAX:
            raise RuntimeError(f"coinbase v2 {path[:40]} 다음 쪽 이상(쪽 {n}) — 이번 주기 보류")
        after = nxt
        time.sleep(PACE)


def _older(lo_ms: int):
    def stop(rows):
        stamps = [_ts_ms(r.get("created_at")) for r in rows]
        if any(t is None for t in stamps):
            raise RuntimeError("coinbase v2 거래 created_at 형식 오류")
        if any(a < b for a, b in zip(stamps, stamps[1:])):
            raise RuntimeError("coinbase v2 거래 쪽이 최신순이 아님 — 창 하한 판정 불가(이번 주기 보류)")
        return stamps[-1] < lo_ms
    return stop


def _scope(env: dict) -> str:
    return env[KEYS[0]] + "|" + hashlib.sha256(env[KEYS[1]].encode()).hexdigest()[:16]


def _v2_scan(env: dict, t0: int, t1: int) -> list:
    now = int(time.time())
    lo = int(t0) - OVERLAP
    c, scope = _V2, _scope(env)
    if c and c.get("scope") == scope and now - c["at"] <= _V2_TTL and c["lo"] <= lo and c["t1"] >= int(t1) - _V2_TTL:
        return c["txs"]
    got = []
    for a in _v2_pages(env, "/v2/accounts"):
        aid = str(a.get("id") or "")
        if not aid or "/" in aid or "?" in aid:
            raise RuntimeError("coinbase v2 계정 id 형식 오류")
        ccy = str((a.get("balance") or {}).get("currency") or (a.get("currency") or {}).get("code") or "").upper()
        got += [(aid, ccy, t) for t in _v2_pages(env, f"/v2/accounts/{urllib.parse.quote(aid, safe='-')}/transactions", _older(lo * 1000))]
    _V2.clear()
    _V2.update(at=now, lo=lo, t1=int(t1), txs=got, scope=scope)
    return got


def _state_of(t) -> str:
    s = str(t.get("status") or "").lower()
    return "DONE" if s in _ST_DONE else _ST_FAIL.get(s, "PENDING")


def _row_of(ccy: str, t, want_w: bool):
    typ = str(t.get("type") or "")
    amt = num_parse.to_dec((t.get("amount") or {}).get("amount"))
    cur = str((t.get("amount") or {}).get("currency") or ccy).upper()
    ts = _ts_ms(t.get("created_at"))
    if amt is None or not cur or not t.get("id"):
        return None
    if typ == "fiat_deposit" or typ == "fiat_withdrawal":
        if cur not in FIAT_LEDGER:
            _warn_once("fiatrow:" + cur, "coinbase %s 법정통화 입출금은 원장 밖(USD 만 원장 안 현금)", cur)
            return None
    net = t.get("network") if isinstance(t.get("network"), dict) else {}
    st = _state_of(t)
    if want_w:
        to = t.get("to") if isinstance(t.get("to"), dict) else {}
        fee = num_parse.to_dec((net.get("transaction_fee") or {}).get("amount")) if isinstance(net.get("transaction_fee"), dict) else None
        return norm_row("coinbase", t["id"], cur, format(abs(amt), "f"), format(abs(fee), "f") if fee else 0, net.get("hash"), st,
                        ts, ts, to.get("address"), to.get("destination_tag"), net.get("network_name") or net.get("name"))
    r = norm_row("coinbase", t["id"], cur, format(abs(amt), "f"), 0, net.get("hash"), "ACCEPTED" if st == "DONE" else st,
                 ts, ts, network=net.get("network_name") or net.get("name"))
    if typ in _REWARD_TYPES:
        r["reward"] = typ
    return r


def _in_win(t, t0: int, t1: int) -> bool:
    ts = _ts_ms(t.get("created_at"))
    return ts is not None and (int(t0) - OVERLAP) * 1000 <= ts <= (int(t1) + 60) * 1000


def fetch_coinbase(env: dict, t0: int, t1: int):
    out_w, out_d = [], []
    for _aid, ccy, t in _v2_scan(env, t0, t1):
        if not _in_win(t, t0, t1):
            continue
        typ = str(t.get("type") or "")
        amt = num_parse.to_dec((t.get("amount") or {}).get("amount"))
        if amt is None:
            raise RuntimeError("coinbase v2 거래 amount 형식 오류")
        if typ in _WD_TYPES + _DEP_TYPES and amt != 0:
            r = _row_of(ccy, t, amt < 0)
            if r:
                (out_w if amt < 0 else out_d).append(r)
        elif typ in _REWARD_TYPES and amt > 0:
            r = _row_of(ccy, t, False)
            if r:
                out_d.append(r)
        elif typ.startswith("raise_offering_"):
            continue
        elif typ not in _CV_TYPES + _QUIET_TYPES + _WD_TYPES + _DEP_TYPES + _REWARD_TYPES:
            _warn_once("type:" + typ[:40], "coinbase 처음 보는 거래 종류 '%s' — 기장 안 함(잔고 대사가 흡수 · 종류 이름만 기록)", typ[:40])
    return out_w, out_d


def convert_coinbase(env: dict, t0: int, t1: int):
    grp, raise_rows = {}, {"pool": [], "dist": [], "odd": []}
    pair_pad = 2 * RAISE_PAIR_SEC
    for _aid, ccy, t in _v2_scan(env, t0 - pair_pad, t1):
        typ = str(t.get("type") or "")
        if _state_of(t) != "DONE":
            continue
        if typ.startswith("raise_offering_"):
            if not _in_win(t, t0 - pair_pad, t1 + pair_pad):
                continue
            kind = {_RAISE_POOL: "pool", _RAISE_DIST: "dist"}.get(typ, None if typ == _RAISE_DEP else "odd")
            if kind:
                raise_rows[kind].append(t)
            continue
        if typ not in _CV_TYPES or not _in_win(t, t0, t1):
            continue
        ref = (t.get(typ) or {}).get("id") if isinstance(t.get(typ), dict) else None
        grp.setdefault((typ, ref or "~" + str(t.get("id"))), []).append(t)
    out, bad = [], 0
    for (typ, ref), legs in sorted(grp.items()):
        fill = _cv_pair(typ, ref, legs)
        if fill is None:
            bad += 1
            continue
        out.append(fill)
    raise_fills, raise_bad = _raise_pairs(raise_rows, lambda t: _in_win(t, t0, t1))
    out += raise_fills
    bad += raise_bad
    if bad:
        _warn_once(f"cv:{bad}:{len(grp)}:{len(raise_fills)}", "coinbase 간편 매매·전환·토큰 세일 %d건 짝이 안 맞아 기장 안 함(잔고 대사 흡수)", bad)
        return _PartialConvertRows(out, f"coinbase 전환 짝 안 맞음 {bad}건")
    return out


def _raise_pairs(groups: dict, in_window: object = None):
    wanted = in_window or (lambda t: True)
    out, bad = [], sum(1 for t in groups["odd"] if wanted(t))
    for t in groups["odd"]:
        _warn_once("raise:" + str(t.get("type"))[:40], "coinbase 토큰 세일 처음 보는 종류 '%s' — 기장 안 함(잔고 대사 흡수)", str(t.get("type"))[:40])
    near = lambda a, b: abs((_ts_ms(a.get("created_at")) or 0) - (_ts_ms(b.get("created_at")) or 0)) <= RAISE_PAIR_SEC * 1000  # noqa: E731
    for d in groups["dist"]:
        if not wanted(d):
            continue
        ps = [p for p in groups["pool"] if near(p, d)]
        if len(ps) != 1 or len([x for x in groups["dist"] if near(ps[0], x)]) != 1:
            bad += 1
            continue
        p = ps[0]
        pa, pc = num_parse.to_dec((p.get("amount") or {}).get("amount")), str((p.get("amount") or {}).get("currency") or "").upper()
        da, dc = num_parse.to_dec((d.get("amount") or {}).get("amount")), str((d.get("amount") or {}).get("currency") or "").upper()
        fill = None
        if pa is not None and da is not None and pa < 0 < da and pc and dc and pc != dc:
            fill = _cv_fill("coinbase", f"raise:{d.get('id')}", _ts_ms(d.get("created_at")) or 0, pc, format(-pa, "f"), dc, format(da, "f"))
        if fill is None:
            bad += 1
            continue
        out.append(fill)
    bad += len([p for p in groups["pool"] if wanted(p) and not any(near(p, d) for d in groups["dist"])])
    return out, bad


def _cv_pair(typ: str, ref: str, legs: list):
    if ref.startswith("~") or len(legs) != 2:
        return None
    legs_amt = [(num_parse.to_dec((t.get("amount") or {}).get("amount")), str((t.get("amount") or {}).get("currency") or "").upper(), t) for t in legs]
    neg = [x for x in legs_amt if x[0] is not None and x[0] < 0]
    pos = [x for x in legs_amt if x[0] is not None and x[0] > 0]
    if len(neg) != 1 or len(pos) != 1 or neg[0][1] == pos[0][1]:
        return None
    ts = max(_ts_ms(neg[0][2].get("created_at")) or 0, _ts_ms(pos[0][2].get("created_at")) or 0)
    return _cv_fill("coinbase", f"{typ}:{ref}", ts, neg[0][1], format(-neg[0][0], "f"), pos[0][1], format(pos[0][0], "f"))


def fills_coinbase(env: dict, st: dict, t0: int, t1: int):
    out, held, ids = [], [], set()
    _fills_window(env, int(t0) - OVERLAP, int(t1) + 60, out, held, ids)
    if held:
        _recon_hold(st, "cb_fill", int(time.time()), f"coinbase 기장 보류 체결 {len(held)}건(조정·쿼트 단위·현물 아님)")
    else:
        _recon_hold_clear(st, "cb_fill")
    return out


def _fills_window(env: dict, s: int, e: int, out: list, held: list, ids: set, page_max: int = PAGE_MAX) -> None:
    prm = {"start_sequence_timestamp": _iso(s), "end_sequence_timestamp": _iso(e), "limit": FILL_LIMIT}
    cur, n, seen_c = "", 0, set()
    while True:
        d = _cb_get(env, "/api/v3/brokerage/orders/historical/fills", dict(prm, **({"cursor": cur} if cur else {})))
        rows = d.get("fills") if isinstance(d, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("coinbase fills 응답 형식 오류")
        for r in rows:
            fill = _fill_of(r, held)
            if fill and fill["id"] not in ids:
                ids.add(fill["id"])
                out.append(fill)
        n += 1
        nxt = str(d.get("cursor") or "")
        if not rows or not nxt:
            return
        if nxt in seen_c:
            raise RuntimeError(f"coinbase fills 커서 반복(쪽 {n}) — 이번 주기 체결 보류")
        if n >= page_max:
            if e - s <= 3600:
                raise RuntimeError(f"coinbase fills 1시간 창이 쪽 상한({page_max})을 넘음 — 이번 주기 체결 보류")
            m = (s + e) // 2
            _fills_window(env, s, m + 1, out, held, ids, page_max)
            _fills_window(env, m, e, out, held, ids, page_max)
            return
        seen_c.add(nxt)
        cur = nxt
        time.sleep(PACE)


def _fill_of(r, held: list):
    if not isinstance(r, dict):
        raise RuntimeError("coinbase fill 행 형식 오류")
    fid = str(r.get("entry_id") or "")
    parts = str(r.get("product_id") or "").upper().split("-")
    ptype = str(r.get("product_type") or "SPOT").upper()
    spot = len(parts) == 2 and all(parts) and parts[1] not in ("PERP", "PERPETUAL") and ptype == "SPOT"
    why = ("id 없음" if not fid else f"trade_type {r.get('trade_type')}" if str(r.get("trade_type") or "") != "FILL"
           else "size_in_quote" if r.get("size_in_quote") is True else "현물 아님" if not spot else "")
    side = str(r.get("side") or "").lower()
    ts = _ts_ms(r.get("trade_time"))
    px, sz, fee = num_parse.to_dec(r.get("price")), num_parse.to_dec(r.get("size")), num_parse.to_dec(r.get("commission") or "0")
    if not why and (side not in ("buy", "sell") or ts is None or px is None or sz is None or fee is None or px <= 0 or sz <= 0):
        why = "필드 형식"
    if why:
        held.append(fid)
        _warn_once("fill:" + fid + why, "coinbase 체결 %s 기장 보류(%s — 실측 전 보수 규칙 · 잔고 대사가 흡수)", fid[:40] or "?", why)
        return None
    return norm_fill("coinbase", fid, ts, parts[0], parts[1], side, format(px, "f"), format(sz, "f"), format(fee, "f"), parts[1])
