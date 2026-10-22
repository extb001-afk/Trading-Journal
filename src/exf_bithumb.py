from __future__ import annotations
import json
import time
import urllib.request
import uuid as uuidlib
from decimal import Decimal
from decimal import InvalidOperation
import ex_sign
from exf_net import PACE
from exf_net import _Bal
from exf_net import _balance_rows
from exf_net import _dstr
from exf_net import _gov_prepare
from exf_net import _srv_ms
from exf_net import http_json
from exf_net import norm_fill
from exf_net import norm_row
import logging

log = logging.getLogger('tj-exf')

def fetch_bithumb(env, t0: int, t1: int):
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]
    out_w, out_d = [], []

    def call(path, params):
        _gov_prepare("api.bithumb.com", path)
        payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
                   "timestamp": _srv_ms("api.bithumb.com")}
        if params:
            payload["query_hash"] = ex_sign.query_hash(params)
            payload["query_hash_alg"] = "SHA512"
        tok = ex_sign.jwt_hs256(payload, sec)
        qs = urllib.parse.urlencode(params) if params else ""
        url = f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else "")
        return http_json(url, {"Authorization": f"Bearer {tok}"})

    for path, bucket in (("/v1/withdraws", "w"), ("/v1/deposits", "d")):
        page = 1
        stop = False
        while not stop:
            if page > 200:
                raise RuntimeError(f"bithumb {path} 200페이지 초과 — 다음 주기 재시도")
            rows = call(path, {"limit": 100, "page": page, "order_by": "desc"})
            if not isinstance(rows, list):
                raise RuntimeError(f"bithumb {path} 응답이 목록이 아님 — 입출금 창 완료 보류: {str(rows)[:120]}")
            if not rows:
                break
            for row in rows:
                created = str(row.get("created_at") or "")
                try:
                    import datetime as _dt
                    cts = int(_dt.datetime.fromisoformat(created).timestamp())
                except (ValueError, TypeError):
                    cts = t1
                if cts < t0:
                    stop = True
                    break
                st_raw = str(row.get("state") or "").upper()
                nid = row.get("uuid") or f"{row.get('currency')}:{row.get('txid')}"
                if bucket == "w":
                    st = "DONE" if st_raw == "DONE" else (
                        {"CANCELED": "CANCELLED", "CANCELLED": "CANCELLED", "REJECTED": "REJECTED",
                         "FAILED": "FAILED"}.get(st_raw, "PENDING"))
                    out_w.append(norm_row("bithumb", nid, row.get("currency"),
                                          row.get("amount"), row.get("fee"), row.get("txid"),
                                          st, created, row.get("done_at"),
                                          row.get("address") or row.get("to_address"),
                                          row.get("secondary_address"), row.get("net_type")))
                else:
                    st = "ACCEPTED" if st_raw in ("ACCEPTED", "DONE", "DEPOSIT_ACCEPTED") \
                        else "PENDING"
                    out_d.append(norm_row("bithumb", nid, row.get("currency"),
                                          row.get("amount"), 0, row.get("txid"),
                                          st, created, row.get("done_at"), network=row.get("net_type")))
            time.sleep(PACE)
            page += 1
    w9, d9 = fetch_bithumb_krw(env, t0, t1, call=call)
    return out_w + w9, out_d + d9


BITHUMB_KRW_ST = {"ACCEPTED": "ACCEPTED", "DONE": "DONE", "CANCELLED": "CANCELLED", "CANCELED": "CANCELLED",
                  "REJECTED": "REJECTED", "FAILED": "FAILED"}


_BITHUMB_KRW_DENY = {"n": 0}


def fetch_bithumb_krw(env, t0: int, t1: int, call=None, require_complete: bool = False):
    call = call or _bithumb_caller(env)
    out_w, out_d = [], []
    for path, bucket in (("/v1/withdraws/krw", "w"), ("/v1/deposits/krw", "d")):
        page = 1
        stop = False
        while not stop:
            if page > 200:
                raise RuntimeError(f"bithumb {path} 200페이지 초과 — 다음 주기 재시도")
            try:
                rows = call(path, {"limit": 100, "page": page, "order_by": "desc"})
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    _BITHUMB_KRW_DENY["n"] += 1
                    if _BITHUMB_KRW_DENY["n"] % 144 == 1:
                        log.warning("bithumb 원화 입출금 조회 권한 없음(HTTP %s) — 원화 목록 생략(코인 입출금은 계속)", e.code)
                    if require_complete:
                        raise
                    return [], []
                raise
            if not isinstance(rows, list):
                raise RuntimeError(f"bithumb {path} 응답이 목록이 아님 — 원화 입출금 창 완료 보류: {str(rows)[:120]}")
            if not rows:
                break
            for row in rows:
                created = str(row.get("created_at") or "")
                try:
                    import datetime as _dt
                    cts = int(_dt.datetime.fromisoformat(created).timestamp())
                except (ValueError, TypeError):
                    cts = t1
                if cts < t0:
                    stop = True
                    break
                st_raw = str(row.get("state") or "").upper()
                st = BITHUMB_KRW_ST.get(st_raw, "PENDING")
                if bucket == "w" and st == "ACCEPTED":
                    st = "PENDING"
                if bucket == "d" and st == "DONE":
                    st = "ACCEPTED"
                nid = row.get("uuid") or f"KRW:{row.get('txid')}"
                r9 = norm_row("bithumb", nid, "KRW", row.get("amount"), row.get("fee") if bucket == "w" else 0,
                              row.get("txid"), st, created, row.get("done_at"))
                if row.get("transaction_type"):
                    r9["transaction_type"] = str(row["transaction_type"])
                (out_w if bucket == "w" else out_d).append(r9)
            if len(rows) < 100:
                break
            time.sleep(PACE)
            page += 1
    return out_w, out_d


def _bithumb_caller(env):
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]

    def call(path, params):
        _gov_prepare("api.bithumb.com", path)
        payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
                   "timestamp": _srv_ms("api.bithumb.com")}
        if params:
            payload["query_hash"] = ex_sign.query_hash(params)
            payload["query_hash_alg"] = "SHA512"
        tok = ex_sign.jwt_hs256(payload, sec)
        qs = urllib.parse.urlencode(params) if params else ""
        return http_json(f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else ""),
                         {"Authorization": f"Bearer {tok}"})

    return call


def fills_bithumb(env, st, t0: int, t1: int):
    call = _bithumb_caller(env)
    fills = []
    raw = {}
    regular = t1 >= time.time() - 3600
    pend = []
    reg9 = st.get("bt_reg") or {}
    order9 = sorted(("done", "cancel"), key=lambda q: 0 if (regular and isinstance(reg9.get(q), dict)) else 1)
    for st_q in order9:
        if regular and isinstance((st.get("bt_reg") or {}).get(st_q), dict):
            f9, ok9 = _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, time.time() + BITHUMB_REG_BUDGET)
        else:
            try:
                f9, ok9 = _bithumb_orders_state(call, st_q, t0, t1, raw), True
            except _BithumbDeep as e:
                if not regular:
                    raise
                log.warning("bithumb 체결(%s) 정규 창 200페이지 초과 — 오름차순 재개형 따라잡기로 전환", st_q)
                st.setdefault("bt_reg", {})[st_q] = {"t0": int(t0)}
                f9b, ok9 = _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, time.time() + BITHUMB_REG_BUDGET)
                f9 = e.fills + f9b
        fills.extend(f9)
        if not ok9:
            pend.append(st_q)
    if pend:
        st["partial"] = f"bithumb 체결 따라잡기 진행 중({', '.join(pend)} — 오름차순 재개형)"
    if t1 < time.time() - 3600:
        track = st.get("open_track")
        tracked = {f"bithumb:{u}" for u in track} if isinstance(track, dict) else set()
        return [f for f in fills if f["id"] not in tracked]
    return _bithumb_track(call, st, fills, raw, time.time())


BITHUMB_TRACK_MIN_AGE = 1800


BITHUMB_RESOLVE_MAX = 40


BITHUMB_NOTFOUND_DROP = 3
BITHUMB_TRACK_ROW_KEYS = ("uuid", "market", "side", "ord_type", "state", "price", "avg_price", "executed_volume", "executed_funds", "paid_fee", "created_at")


def _bithumb_open(call, max_pages: int = 20):
    out = []
    try:
        for page in range(1, max_pages + 1):
            rows = call("/v1/orders", {"limit": 100, "order_by": "desc", "page": page, "state": "wait"})
            if not isinstance(rows, list):
                return None
            out.extend(rows)
            if len(rows) < 100:
                return out
            time.sleep(PACE)
    except Exception as e:  # noqa: BLE001 [fallback]
        log.warning("bithumb 미체결 주문 조회 실패(이번 추적 판정 보류): %s", repr(e)[:140])
        return None
    return None


def _bithumb_track(call, st, fills, raw, now):
    import acct_norm
    track = st.get("open_track") if isinstance(st.get("open_track"), dict) else {}
    track = {str(k): dict(v) if isinstance(v, dict) else {} for k, v in track.items()}
    fseen = st.get("seen") or {}
    keep = []
    for f in fills:
        u = f["id"].split(":", 1)[1]
        if f["id"] in fseen:
            keep.append(f)
            continue
        if u in track or (f["ts"] / 1000.0 < now - BITHUMB_TRACK_MIN_AGE and (fseen or st.get("backfilled_until"))):
            r9 = raw.get(u) or {}
            ent = track.setdefault(u, {"c": r9.get("created_at"), "m": r9.get("market")})
            ent["row"] = {k: r9[k] for k in BITHUMB_TRACK_ROW_KEYS if r9.get(k) is not None} or ent.get("row")
            ent["closed"] = True
        else:
            keep.append(f)
    oo = _bithumb_open(call)
    if oo is not None:
        ids = set()
        for o in oo:
            if isinstance(o, dict) and o.get("uuid"):
                u = str(o["uuid"])
                ids.add(u)
                if u not in track and f"bithumb:{u}" not in fseen:
                    track[u] = {"c": o.get("created_at"), "m": o.get("market")}
        for u, ent in track.items():
            if u not in ids:
                ent["closed"] = True
    out = []
    n = 0
    for u in sorted(track, key=lambda k: str((track[k] or {}).get("c") or "")):
        ent = track[u]
        if f"bithumb:{u}" in fseen:
            del track[u]
            continue
        if not ent.get("closed"):
            continue
        if n >= BITHUMB_RESOLVE_MAX:
            break
        n += 1
        try:
            o = call("/v1/order", {"uuid": u})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                ent["nf"] = int(ent.get("nf") or 0) + 1
                if ent["nf"] >= BITHUMB_NOTFOUND_DROP:
                    r9 = raw.get(u) or ent.get("row")
                    if r9:
                        try:
                            out.append(_bithumb_fill(r9, None))
                        except RuntimeError as e9:
                            log.warning("bithumb 추적 주문 %s 목록 행 방출 실패: %s", u, e9)
                            continue
                    log.warning("bithumb 추적 주문 %s 단건 404 %d회 — 추적 종료%s", u, ent["nf"],
                                "(목록 행 방출)" if r9 else "(수동 확인 필요)")
                    del track[u]
                continue
            log.warning("bithumb 추적 주문 %s 단건 조회 실패(다음 주기 재시도): %s", u, repr(e)[:120])
            continue
        except Exception as e:  # noqa: BLE001 [isolate]
            log.warning("bithumb 추적 주문 %s 단건 조회 실패(다음 주기 재시도): %s", u, repr(e)[:120])
            continue
        finally:
            time.sleep(PACE)
        if not isinstance(o, dict) or str(o.get("uuid") or "") != u:
            log.warning("bithumb 추적 주문 %s 단건 응답 형식 오류 — 다음 주기 재시도", u)
            continue
        ent.pop("nf", None)
        state9 = str(o.get("state") or "")
        if state9 in ("wait", "watch"):
            ent["closed"] = False
            continue
        if state9 not in ("done", "cancel"):
            log.warning("bithumb 추적 주문 %s 상태 미상(%s) — 다음 주기 재시도", u, state9)
            continue
        try:
            ev = float(o.get("executed_volume"))
        except (TypeError, ValueError):
            log.warning("bithumb 추적 주문 %s 체결수량 파싱 실패 — 다음 주기 재시도", u)
            continue
        if ev > 0:
            merged = dict(raw.get(u) or ent.get("row") or {})
            merged.update(o)
            if merged.get("executed_funds") in (None, "") and isinstance(o.get("trades"), list) and o["trades"]:
                try:
                    if o.get("trades_count") is None or int(o["trades_count"]) == len(o["trades"]):
                        merged["executed_funds"] = str(sum(float(t["funds"]) for t in o["trades"]))
                except (KeyError, TypeError, ValueError):
                    pass
            fts = acct_norm.fill_ts(merged)
            try:
                out.append(_bithumb_fill(merged, fts * 1000 if fts else None))
            except RuntimeError as e9:
                log.warning("bithumb 추적 주문 %s 기장 보류(다음 주기 재시도): %s", u, e9)
                continue
        del track[u]
    st["open_track"] = track
    st["track_pending"] = sum(1 for e in track.values() if e.get("closed"))
    st["open_unknown"] = oo is None
    if out:
        log.info("bithumb 오래 걸린 주문 체결 확정 %d건 (추적 %d · 확정 대기 %d)", len(out), len(track), st["track_pending"])
    return keep + out


def _bithumb_fill(r, ts_ms):
    created = str(r.get("created_at") or "")
    if ts_ms is None:
        import datetime as _dt
        try:
            ts_ms = int(_dt.datetime.fromisoformat(created).timestamp()) * 1000
        except (ValueError, TypeError):
            ts_ms = int(time.time()) * 1000
    ev = r.get("executed_volume")
    mk = str(r.get("market") or "")
    q, _, b = mk.partition("-")
    funds = r.get("executed_funds")
    try:
        if funds is not None and float(funds) > 0:
            px = str(float(funds) / float(ev))
        else:
            avg = r.get("avg_price")
            if avg is not None and float(avg) > 0:
                px = str(float(avg))
            elif str(r.get("ord_type") or "") == "limit" and float(r.get("price") or 0) > 0:
                px = str(float(r.get("price")))
            else:
                raise RuntimeError(f"bithumb 주문 {r.get('uuid')} 단가 미상(정산총액·평균가 없음, ord_type="
                                   f"{r.get('ord_type')}) — 체결 창 완료 보류, 다음 주기 재조회")
    except (TypeError, ValueError, ZeroDivisionError) as e:
        raise RuntimeError(f"bithumb 주문 {r.get('uuid')} 단가 파싱 실패({e!r}) — 체결 창 완료 보류") from None
    side = "buy" if str(r.get("side")) == "bid" else "sell"
    f9 = norm_fill("bithumb", r.get("uuid"), ts_ms, b, q, side,
                   px, ev, r.get("paid_fee"), q)
    f9["funds"] = str(funds or "")
    legs9 = _bithumb_cashlegs(r, funds)
    if legs9:
        f9["cashlegs"] = legs9
    return f9


def _bithumb_cashlegs(r, funds):
    import acct_norm
    from decimal import Decimal, InvalidOperation
    tr = r.get("trades")
    if not isinstance(tr, list) or not tr or funds in (None, ""):
        return None
    try:
        if r.get("trades_count") is not None and int(r["trades_count"]) != len(tr):
            return None
        legs = []
        for t in tr:
            ts = acct_norm.fill_ts({"trades": [t]}) if isinstance(t, dict) else None
            if not ts or t.get("funds") in (None, ""):
                return None
            v9 = t.get("volume")
            legs.append((int(ts), Decimal(str(t["funds"])), Decimal(str(v9)) if v9 not in (None, "") else None))
        if abs(sum(d for _t, d, _v in legs) - Decimal(str(funds))) > Decimal("0.5"):
            return None
        ev9 = r.get("executed_volume")
        vol_ok = all(v is not None and v > 0 for _t, _d, v in legs) and ev9 not in (None, "") \
            and abs(sum(v for _t, _d, v in legs) - Decimal(str(ev9))) <= Decimal("0.00000001")
    except (TypeError, ValueError, InvalidOperation):
        return None
    legs.sort(key=lambda x: x[0])
    return [[t, str(d), str(v)] if vol_ok else [t, str(d)] for t, d, v in legs]


_BITHUMB_ASC_CACHE = {}


BITHUMB_ASC_CACHE_SEC = 3600


BITHUMB_ASC_SCAN_MAX = 200


def _bithumb_row_ts(r, dflt):
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(str(r.get("created_at") or "")).timestamp())
    except (ValueError, TypeError):
        return dflt


def _bithumb_asc_pager(call, st_q):
    cache = _BITHUMB_ASC_CACHE.setdefault(st_q, {})
    now9 = time.time()
    for p9 in [p for p, v in cache.items() if now9 - v[3] > BITHUMB_ASC_CACHE_SEC]:
        cache.pop(p9, None)
    got = {}

    def page_rows(p):
        if p in got:
            return got[p]
        rows = call("/v1/orders", {"limit": 100, "order_by": "asc", "page": p, "state": st_q})
        if not isinstance(rows, list):
            raise RuntimeError(f"bithumb orders({st_q}, asc p{p}) 응답이 목록이 아님: {str(rows)[:120]}")
        time.sleep(PACE)
        got[p] = rows
        if rows:
            cache[p] = (_bithumb_row_ts(rows[0], 0), _bithumb_row_ts(rows[-1], 0), len(rows), time.time())
        else:
            cache[p] = (None, None, 0, time.time())
        return rows

    def meta(p):
        v = cache.get(p)
        if v is None:
            page_rows(p)
            v = cache[p]
        return v

    return page_rows, meta


def _bithumb_asc_start(meta, st_q, t0, deadline=None):
    lo, hi = 0, 1
    while True:
        if deadline is not None and time.time() >= deadline:
            return None
        m = meta(hi)
        if m[2] == 0 or (m[1] is not None and m[1] >= t0):
            break
        lo, hi = hi, hi * 2
        if hi > 1 << 20:
            raise RuntimeError(f"bithumb orders({st_q}) 오름차순 탐색 상한 초과")
    while hi - lo > 1:
        if deadline is not None and time.time() >= deadline:
            return None
        mid = (lo + hi) // 2
        m = meta(mid)
        if m[2] == 0 or (m[1] is not None and m[1] >= t0):
            hi = mid
        else:
            lo = mid
    return max(1, hi - 1)


def _bithumb_asc_page(rows, t0, t1, raw=None):
    fills, past = [], False
    for r in rows:
        cts = _bithumb_row_ts(r, None)
        if cts is None:
            continue
        if cts > t1:
            past = True
            continue
        if cts < t0:
            continue
        ev = r.get("executed_volume")
        if not ev or float(ev) <= 0:
            continue
        fills.append(_bithumb_fill(r, cts * 1000))
        if raw is not None and r.get("uuid"):
            raw[str(r["uuid"])] = r
    return fills, past


def _bithumb_orders_asc(call, st_q, t0, t1, raw=None):
    page_rows, meta = _bithumb_asc_pager(call, st_q)
    fills, page, n = [], _bithumb_asc_start(meta, st_q, t0), 0
    while True:
        if n >= BITHUMB_ASC_SCAN_MAX:
            raise RuntimeError(f"bithumb orders({st_q}) 창 안 {BITHUMB_ASC_SCAN_MAX}페이지 초과 — 다음 주기 재시도")
        rows = page_rows(page)
        n += 1
        if not rows:
            break
        f9, past = _bithumb_asc_page(rows, t0, t1, raw)
        fills.extend(f9)
        if past or len(rows) < 100:
            break
        page += 1
    return fills


BITHUMB_EXT_STATES = ("done", "cancel")


def _bithumb_ext_fills(call, st, ext, a, b, deadline, emit, save):
    sc = ext.get("bt_scan")
    if not isinstance(sc, dict) or int(sc.get("a") or -1) != int(a) or int(sc.get("b") or -1) != int(b) \
            or not isinstance(sc.get("st"), dict):
        sc = ext["bt_scan"] = {"a": int(a), "b": int(b), "st": {}}
        save()
    track = st.get("open_track")
    tracked = {f"bithumb:{u}" for u in track} if isinstance(track, dict) else set()
    for st_q in BITHUMB_EXT_STATES:
        cur = sc["st"].setdefault(st_q, {})
        if cur.get("fin"):
            continue
        page_rows, meta = _bithumb_asc_pager(call, st_q)
        if not cur.get("page"):
            p0 = _bithumb_asc_start(meta, st_q, int(a), deadline)
            if p0 is None:
                return False
            cur.update(page=int(p0), p0=int(p0), n=0)
            save()
            page = int(p0)
        else:
            page = max(int(cur.get("p0") or 1), int(cur["page"]) - 1)
        while True:
            if time.time() >= deadline:
                return False
            rows = page_rows(page)
            if not rows:
                cur["fin"] = True
                save()
                break
            raw9 = {}
            f9, past = _bithumb_asc_page(rows, int(a), int(b), raw9)
            f9 = [f for f in f9 if f["id"] not in tracked]
            rt9 = ext.setdefault("bt_rt", {})
            try:
                f9 = _bithumb_retime(call, f9, raw9, rt9, deadline)
            except _BithumbBudget:
                save()
                return False
            if f9:
                emit(f9)
            if len(rt9) > BITHUMB_RT_KEEP:
                ext["bt_rt"] = dict(list(rt9.items())[-BITHUMB_RT_KEEP:])
            ts9 = [t for t in (_bithumb_row_ts(r, None) for r in rows) if t is not None]
            cur["page"] = page + 1
            cur["n"] = int(cur.get("n") or 0) + 1
            if ts9:
                cur["ts"] = max(int(cur.get("ts") or 0), max(ts9))
            if past or len(rows) < 100:
                cur["fin"] = True
                save()
                break
            save()
            page += 1
    return all((sc["st"].get(q) or {}).get("fin") for q in BITHUMB_EXT_STATES)


BITHUMB_RT_KEEP = 400


class _BithumbBudget(RuntimeError):
    pass


def _bithumb_retime(call, fills, raw, cache=None, deadline=None):
    import acct_norm
    cache = {} if cache is None else cache
    out = []
    for f in fills:
        u = f["id"].split(":", 1)[1]
        r = raw.get(u) or {}
        if str(r.get("ord_type") or "") != "limit":
            out.append(f)
            continue
        if u not in cache:
            if deadline is not None and time.time() >= deadline:
                raise _BithumbBudget("bithumb 과거 창 체결 시각 확인 — 시간 예산 소진")
            try:
                o = call("/v1/order", {"uuid": u})
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                o = None
            finally:
                time.sleep(PACE)
            fts = None
            if isinstance(o, dict) and str(o.get("uuid") or "") == u and str(o.get("state") or "") in ("done", "cancel"):
                merged = dict(r)
                merged.update(o)
                fts = acct_norm.fill_ts(merged)
                if fts and int(fts) * 1000 != int(f["ts"]):
                    try:
                        f2 = _bithumb_fill(merged, int(fts) * 1000)
                    except RuntimeError:
                        f2 = None
                    if f2 is None or _dstr(f2["qty"]) != _dstr(f["qty"]):
                        fts = None
            cache[u] = int(fts) * 1000 if fts else 0
        if cache[u] and int(cache[u]) != int(f["ts"]):
            f = dict(f, ts=int(cache[u]))
        out.append(f)
    return out


def _bithumb_ext_part(ext):
    sc = ext.get("bt_scan")
    if not isinstance(sc, dict) or int(sc.get("b") or -1) != int(ext.get("fills_from") or 0):
        return 0
    a9, b9 = int(sc.get("a") or 0), int(sc.get("b") or 0)
    tot = 0
    for q in BITHUMB_EXT_STATES:
        c9 = (sc.get("st") or {}).get(q) or {}
        tot += (b9 - a9) if c9.get("fin") else max(0, min(b9, int(c9.get("ts") or 0)) - a9)
    return tot // len(BITHUMB_EXT_STATES)


BITHUMB_REG_BUDGET = 120


class _BithumbDeep(RuntimeError):

    def __init__(self, msg, fills):
        super().__init__(msg)
        self.fills = fills


def _bithumb_reg_catchup(call, st, st_q, t0, t1, raw, deadline):
    reg = st.setdefault("bt_reg", {})
    cur = reg.get(st_q)
    if not isinstance(cur, dict) or not cur.get("t0") or int(t0) < int(cur.get("t0") or 0) - 60:
        cur = reg[st_q] = {"t0": int(t0)}
    page_rows, meta = _bithumb_asc_pager(call, st_q)
    lo9 = int(cur["t0"])
    if not cur.get("page"):
        p0 = _bithumb_asc_start(meta, st_q, lo9, deadline)
        if p0 is None:
            return [], False
        cur.update(page=int(p0), p0=int(p0))
        page = int(p0)
    else:
        page = max(int(cur.get("p0") or 1), int(cur["page"]) - 1)
    out = []
    while True:
        if time.time() >= deadline:
            return out, False
        rows = page_rows(page)
        if not rows:
            reg.pop(st_q, None)
            return out, True
        f9, past = _bithumb_asc_page(rows, lo9, int(t1), raw)
        out.extend(f9)
        cur["page"] = page + 1
        if past or len(rows) < 100:
            reg.pop(st_q, None)
            return out, True
        page += 1


def _bithumb_orders_state(call, st_q, t0, t1, raw=None):
    if t1 < time.time() - 3600:
        return _bithumb_orders_asc(call, st_q, t0, t1, raw)
    fills = []
    page = 1
    while page <= 200:
        rows = call("/v1/orders", {"limit": 100, "order_by": "desc", "page": page,
                                   "state": st_q})
        if not isinstance(rows, list):
            raise RuntimeError(f"bithumb orders({st_q}) 응답이 목록이 아님: {str(rows)[:120]}")
        if not rows:
            break
        stop = False
        for r in rows:
            created = str(r.get("created_at") or "")
            try:
                import datetime as _dt
                cts = int(_dt.datetime.fromisoformat(created).timestamp())
            except (ValueError, TypeError):
                cts = t1
            if cts < t0:
                stop = True
                break
            ev = r.get("executed_volume")
            if not ev or float(ev) <= 0:
                continue
            fills.append(_bithumb_fill(r, cts * 1000))
            if raw is not None and r.get("uuid"):
                raw[str(r["uuid"])] = r
        if stop:
            break
        time.sleep(PACE)
        page += 1
    else:
        raise _BithumbDeep(f"bithumb orders({st_q}) 200페이지 초과 — 다음 주기 재시도", fills)
    return fills


def _bithumb_get(env, path, params=None):
    _gov_prepare("api.bithumb.com", path)
    key, sec = env["TJ_BITHUMB_KEY"], env["TJ_BITHUMB_SECRET"]
    payload = {"access_key": key, "nonce": str(uuidlib.uuid4()),
               "timestamp": _srv_ms("api.bithumb.com")}
    if params:
        payload["query_hash"] = ex_sign.query_hash(params)
        payload["query_hash_alg"] = "SHA512"
    tok = ex_sign.jwt_hs256(payload, sec)
    qs = urllib.parse.urlencode(params) if params else ""
    return http_json(f"https://api.bithumb.com{path}" + (f"?{qs}" if qs else ""),
                     {"Authorization": f"Bearer {tok}"})


def _bal_bithumb(env):
    out = _Bal()
    for a in _balance_rows(_bithumb_get(env, "/v1/accounts")):
        v = float(a.get("balance") or 0) + float(a.get("locked") or 0)
        if v > 0:
            out[str(a["currency"]).upper()] = v
    return out
