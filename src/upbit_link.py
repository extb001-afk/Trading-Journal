"""Upbit / Bithumb exchange collectors."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuid_mod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acct_norm
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import unit_beat
import bf_engine
from inbox import SegmentWriter

log = common.setup_logging("tj-ex")

API = "https://api.upbit.com"
POLL_SEC = 60
BAL_PATH = os.path.join(common.STATE_DIR, "upbit_balances.json")


def _env():
    return common.read_env_file()


def _b64url(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt(access: str, secret: str, query: dict | None) -> str:
    import hmac
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = {"access_key": access, "nonce": str(uuid_mod.uuid4())}
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        payload["query_hash"] = hashlib.sha512(qs.encode()).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    body = _b64url(json.dumps(payload).encode())
    sig = _b64url(hmac.new(secret.encode(), f"{header}.{body}".encode(),
                           hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


_BACKOFF_CODES = (401, 403, 429)


def _note_backoff(up, e) -> bool:
    if getattr(e, "code", None) in _BACKOFF_CODES:
        try:
            up._backoff_err = e
        except Exception:
            pass
        return True
    return False


class Upbit:
    def __init__(self, access: str, secret: str):
        self.access, self.secret = access, secret
        self.remaining_min = 999
        self._backoff_err = None

    def get(self, path: str, query: dict | None = None):
        url = API + path + (("?" + urllib.parse.urlencode(query, doseq=True)) if query else "")
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {_jwt(self.access, self.secret, query)}",
            "Accept": "application/json", "User-Agent": "tj-bot/0.1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rem = r.headers.get("Remaining-Req") or ""
            for part in rem.split(";"):
                part = part.strip()
                if part.startswith("min="):
                    try:
                        self.remaining_min = int(part[4:])
                    except ValueError:
                        pass
            return json.loads(r.read().decode())


def _paged(up: "Upbit", path: str, months: float = 5, max_pages: int = 60, stop=None) -> list:
    from datetime import datetime
    cutoff = time.time() - months * 30 * 86400
    out = []
    prev_ids = None
    for p in range(1, max_pages + 1):
        rows = up.get(path, {"limit": 100, "page": p, "order_by": "desc"})
        if not isinstance(rows, list) or not rows:
            break
        ids = tuple(str((r or {}).get("uuid")) for r in rows)
        if ids == prev_ids:
            log.warning("%s 페이지 %d 가 직전과 동일 — 페이징 중단", path, p)
            break
        prev_ids = ids
        out.extend(rows)
        if len(rows) < 100:
            break
        if stop is not None and stop(rows):
            break
        try:
            oldest = min(datetime.fromisoformat(str((r or {}).get("created_at")).replace("Z", "+00:00")).timestamp()
                         for r in rows)
        except (ValueError, TypeError):
            oldest = None
        if oldest is not None and oldest < cutoff:
            break
        time.sleep(0.15)
    else:
        raise RuntimeError(f"{path} {max_pages}페이지 상한 도달(창 하한 미도달) — 상한 조정 필요, 이번 동기화 보류")
    return out


ORDERS_STATE = os.path.join(common.STATE_DIR, "upbit_orders_state.json")


def _iso(ts: float) -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _sweep(up: "Upbit", start: float, stop: float, seen: set):
    out = []
    win = 7 * 86400 - 60
    cur = start
    sweep_ok = True
    span = win
    while cur < stop:
        end = min(stop, cur + span)
        window_ok = True
        saturated = False
        for state in ("done", "cancel"):
            try:
                rows = up.get("/v1/orders/closed",
                              {"state": state, "start_time": _iso(cur), "end_time": _iso(end),
                               "limit": 1000})
                if not isinstance(rows, list):
                    raise ValueError(f"orders/closed 응답 형식 오류({type(rows).__name__}) — 창 진행 보류")
            except Exception as e:
                if not _note_backoff(up, e):
                    log.warning("orders %s %s 실패(다음 사이클 재시도): %s", state, _iso(cur)[:10], e)
                window_ok = False
                sweep_ok = False
                break
            if isinstance(rows, list) and len(rows) >= 1000:
                saturated = True
                break
            for o in rows or []:
                try:
                    ev = float(o.get("executed_volume") or 0)
                except (TypeError, ValueError):
                    ev = 0
                if ev <= 0 or not o.get("uuid") or o["uuid"] in seen:
                    continue
                seen.add(o["uuid"])
                out.append(o)
            time.sleep(0.25)
        if saturated:
            if end - cur <= 60:
                log.error("orders 60초 창도 1000건 포화 — 커서 보류: %s", _iso(cur))
                sweep_ok = False
                break
            span = max(60, int((end - cur) / 2))
            continue
        if not window_ok:
            break
        cur = end
        span = win
    return out, sweep_ok, cur


TRACK_MIN_AGE = 1800
RESOLVE_MAX = 40
NOTFOUND_DROP = 3


def _iso_ts(v):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _with_funds(o: dict) -> dict:
    if o.get("executed_funds") not in (None, ""):
        return o
    tr = o.get("trades")
    if not isinstance(tr, list) or not tr:
        return o
    try:
        if o.get("trades_count") is not None and int(o["trades_count"]) != len(tr):
            return o
        from decimal import Decimal
        tot = sum((Decimal(str(t["funds"])) for t in tr), Decimal(0))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return o
    if tot > 0:
        o = dict(o)
        o["executed_funds"] = str(tot)
    return o


def _recon_marker():
    import sqlite3
    if not os.path.exists(common.DB_PATH):
        return 0
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=5)
        try:
            r = c.execute("SELECT v FROM meta WHERE k='recon_done_upbit'").fetchone()
        finally:
            c.close()
        return int(float(r[0])) if r and r[0] else 0
    except Exception as e:
        log.warning("대사 도장 읽기 실패(재스윕 회수분 판단 보류): %s", e)
        return None


def _resolve_tracked(up: "Upbit", track: dict, seen: set, rows: dict) -> list:
    out = []
    n = 0
    marker = None
    marker_read = False
    for u in sorted(track, key=lambda k: str((track[k] or {}).get("c") or "")):
        ent = track[u]
        if u in seen:
            del track[u]
            continue
        if not ent.get("closed"):
            continue
        if n >= RESOLVE_MAX:
            break
        n += 1
        try:
            o = up.get("/v1/order", {"uuid": u})
        except urllib.error.HTTPError as e:
            if _note_backoff(up, e):
                break
            if e.code == 404:
                ent["nf"] = int(ent.get("nf") or 0) + 1
                if ent["nf"] >= NOTFOUND_DROP:
                    log.warning("추적 주문 %s 단건 조회 404 %d회 — 추적 종료(수동 확인 필요)", u, ent["nf"])
                    del track[u]
                continue
            log.warning("추적 주문 %s 단건 조회 실패(다음 사이클 재시도): %s", u, e)
            continue
        except Exception as e:
            log.warning("추적 주문 %s 단건 조회 실패(다음 사이클 재시도): %s", u, e)
            continue
        finally:
            time.sleep(0.15)
        if not isinstance(o, dict) or str(o.get("uuid") or "") != u:
            log.warning("추적 주문 %s 단건 응답 형식 오류 — 다음 사이클 재시도", u)
            continue
        ent.pop("nf", None)
        state = str(o.get("state") or "")
        if state in ("wait", "watch"):
            ent["closed"] = False
            continue
        if state not in ("done", "cancel"):
            log.warning("추적 주문 %s 상태 미상(%s) — 다음 사이클 재시도", u, state)
            continue
        try:
            ev = float(o.get("executed_volume"))
        except (TypeError, ValueError):
            log.warning("추적 주문 %s 체결수량 파싱 실패 — 다음 사이클 재시도", u)
            continue
        if ev > 0:
            merged = dict(rows.get(u) or {})
            merged.update(o)
            if ent.get("rs"):
                if not marker_read:
                    marker, marker_read = _recon_marker(), True
                if marker is None:
                    continue
                fts = acct_norm.fill_ts(merged)
                if marker and fts is None:
                    created = _iso_ts(merged.get("created_at"))
                    if created is not None and created > marker:
                        fts = int(created)
                    elif int(ent.get("nt") or 0) + 1 < NOTFOUND_DROP:
                        ent["nt"] = int(ent.get("nt") or 0) + 1
                        log.warning("재스윕 주문 %s 체결 시각 미상 — 대사 전후 판단 보류(%d회), 다음 사이클 재시도", u, ent["nt"])
                        continue
                if marker and (fts is None or fts <= marker):
                    log.warning("★재스윕 회수 주문 %s %s %s %s state=%s — 체결(%s)이 잔고 대사(%s) 이전: 대사 앵커가 흡수한 수량으로 보고 "
                                "이중 계상 방지로 미방출(done=원가·손익만 누락 / cancel=대사 때 미체결이었다면 수량도 누락 — 수동 확인)★",
                                u, merged.get("market"), merged.get("side"), merged.get("executed_volume"), merged.get("state"),
                                _iso(fts) if fts else "시각 미상", _iso(marker))
                    seen.add(u)
                    del track[u]
                    continue
            merged = _with_funds(merged)
            if merged.get("executed_funds") in (None, "") and str(merged.get("ord_type") or "") != "limit":
                log.warning("추적 주문 %s 정산총액 미상(시장가) — 다음 사이클 재시도", u)
                continue
            out.append(merged)
            seen.add(u)
        del track[u]
    return out


def fetch_orders(up: "Upbit", months: float, open_now: list | None = None):
    st = common.read_json(ORDERS_STATE, {}) if os.path.exists(ORDERS_STATE) else {}
    seen = set(st.get("uuids") or [])
    track = st.get("open_track") if isinstance(st.get("open_track"), dict) else {}
    track = {str(k): dict(v) if isinstance(v, dict) else {} for k, v in track.items()}
    now = time.time()
    start = st.get("backfilled_until") or (now - months * 30 * 86400)
    resweep = bool(st) and not st.get("resweep_i")
    if resweep:
        start = min(float(start), now - months * 30 * 86400, float(st.get("ext_from") or now))
    win = 7 * 86400 - 60
    out, sweep_ok, cur = _sweep(up, start, now, seen)
    rows = {}
    keep = []
    for o in out:
        u = o["uuid"]
        c9 = _iso_ts(o.get("created_at"))
        if u in track or (c9 is not None and c9 < now - TRACK_MIN_AGE):
            seen.discard(u)
            if u not in track:
                track[u] = {"c": o.get("created_at"), "m": o.get("market"), "rs": 1}
            ent = track.setdefault(u, {"c": o.get("created_at"), "m": o.get("market")})
            ent["closed"] = True
            rows[u] = o
        else:
            keep.append(o)
    if open_now is not None:
        open_ids = set()
        for o in open_now:
            if isinstance(o, dict) and o.get("uuid"):
                u = str(o["uuid"])
                open_ids.add(u)
                if u not in track and u not in seen:
                    track[u] = {"c": o.get("created_at"), "m": o.get("market")}
        for u, ent in track.items():
            if u not in open_ids:
                ent["closed"] = True
    resolved = _resolve_tracked(up, track, seen, rows)
    pending = sum(1 for e in track.values() if e.get("closed"))
    next_state = {"backfilled_until": (max(start, now - win) if sweep_ok else cur),
                  "complete": False, "uuids": sorted(seen)[-20000:],
                  "open_track": track, "resweep_i": 1, "track_pending": pending}
    for k9 in ("ext_from", "ext_target", "ext_start", "ext_emit", "tfill"):
        if k9 in st:
            next_state[k9] = st[k9]
    _tfill_add(next_state, [o for o in keep if _kst_day(_iso_ts(o.get("created_at"))) != _kst_day(now)])
    if resolved:
        log.info("오래 걸린 주문 체결 확정 %d건 (추적 %d · 확정 대기 %d)", len(resolved), len(track), pending)
    return keep + resolved, sweep_ok, next_state


def _open_orders(up: "Upbit", max_pages: int = 20):
    out = []
    try:
        for p in range(1, max_pages + 1):
            rows = up.get("/v1/orders/open", {"page": p, "limit": 100, "order_by": "desc"})
            if not isinstance(rows, list):
                return None
            out.extend(rows)
            if len(rows) < 100:
                return out
            time.sleep(0.15)
    except Exception as e:
        if not _note_backoff(up, e):
            log.warning("미체결 주문 조회 실패(이번 잔고 스냅샷엔 생략): %s", e)
        return None
    return None


def _oo_sig(rows: list) -> list:
    return sorted((str((r or {}).get("uuid")), str((r or {}).get("executed_volume")), str((r or {}).get("state")))
                  for r in rows)


EXT_CHUNK = 30 * 86400


TFILL_MAX = 20
TFILL_RESEND = 600
TFILL_SENDS = 5
TFILL_TRIES = 10
TFILL_QMAX = 20000
_TFILL_KEEP = ("uuid", "market", "side", "state", "ord_type", "executed_volume", "paid_fee", "executed_funds", "trades_count", "trades")


def _kst_day(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts) + 9 * 3600))
    except (TypeError, ValueError):
        return None


def _tfill_add(state: dict, orders) -> int:
    q = state.get("tfill") if isinstance(state.get("tfill"), dict) else {}
    n = 0
    for o in orders or ():
        if not isinstance(o, dict) or str(o.get("ord_type") or "") != "limit" or acct_norm.fill_ts(o) is not None:
            continue
        u = str(o.get("uuid") or "")
        if not u or u in q or len(q) >= TFILL_QMAX:
            continue
        q[u] = {k: o.get(k) for k in ("market", "side", "state", "ord_type", "executed_volume", "paid_fee", "executed_funds",
                                      "trades_count", "created_at") if o.get(k) is not None}
        n += 1
    if q:
        state["tfill"] = q
    return n


def _tfill_done(uuids):
    import sqlite3
    if not os.path.exists(common.DB_PATH):
        return None
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=5)
        try:
            out = {}
            for u in uuids:
                r = c.execute("SELECT payload FROM raw_ex WHERE exchange='upbit' AND kind='order' AND uuid=? ORDER BY revision DESC LIMIT 1",
                              (u,)).fetchone()
                try:
                    out[u] = bool(r) and acct_norm.fill_ts(json.loads(r[0])) is not None
                except (TypeError, ValueError):
                    out[u] = False
            return out
        finally:
            c.close()
    except Exception as e:
        log.warning("체결 시각 채우기 확인(원장 읽기) 실패 — 다음 주기: %s", e)
        return None


def _tfill_pass(up: "Upbit", writer, state: dict) -> int:
    q = state.get("tfill") if isinstance(state.get("tfill"), dict) else {}
    if not q:
        return 0
    now9 = int(time.time())
    sent9 = [u for u, v in q.items() if isinstance(v, dict) and v.get("sent")]
    dn9 = _tfill_done(sent9) if sent9 else None
    if dn9 is not None:
        for u in sent9:
            ent = q[u]
            if dn9.get(u):
                q.pop(u, None)
            elif now9 - int(ent.get("sent") or 0) >= TFILL_RESEND:
                ent.pop("sent", None)
                ent["ns"] = int(ent.get("ns") or 0) + 1
                if ent["ns"] >= TFILL_SENDS:
                    log.warning("체결 시각 채우기 %s %d번 보냈으나 원장 반영 없음(새 시각 환율·시세 실패 등) — 생성 시각 그대로(대기열에서 뺌)", u[:12], ent["ns"])
                    q.pop(u, None)
    items, drop, n = [], [], 0
    for u in sorted(q, key=lambda k: (str((q[k] or {}).get("created_at") or ""), k)):
        if n >= TFILL_MAX:
            break
        ent = q[u] if isinstance(q[u], dict) else {}
        if ent.get("sent"):
            continue
        n += 1
        try:
            o = up.get("/v1/order", {"uuid": u})
        except urllib.error.HTTPError as e:
            if _note_backoff(up, e):
                break
            if e.code == 404:
                ent["nf"] = int(ent.get("nf") or 0) + 1
                if ent["nf"] >= NOTFOUND_DROP:
                    log.warning("체결 시각 채우기 %s 단건 404 %d회 — 생성 시각 그대로(대기열에서 뺌)", u[:12], ent["nf"])
                    drop.append(u)
                continue
            ent["n"] = int(ent.get("n") or 0) + 1
            continue
        except Exception as e:
            ent["n"] = int(ent.get("n") or 0) + 1
            log.warning("체결 시각 채우기 %s 단건 조회 실패(다음 주기 재시도): %s", u[:12], repr(e)[:120])
            continue
        finally:
            time.sleep(0.15)
        resp = {k: o.get(k) for k in _TFILL_KEEP if isinstance(o, dict) and k in o}
        stored = dict({k: v for k, v in ent.items() if k not in ("n", "nf", "sent", "ns")}, uuid=u)
        merged, why = acct_norm.trades_fill_merge(stored, resp)
        if merged is not None:
            items.append(dict(resp, uuid=u))
            continue
        ent["n"] = int(ent.get("n") or 0) + 1
        if ent["n"] >= TFILL_TRIES or why not in ("체결 목록 없음", "체결 수 다름", "형식"):
            log.warning("체결 시각 채우기 %s 검사 실패(%s) — 생성 시각 그대로(대기열에서 뺌)", u[:12], why)
            drop.append(u)
    for u in drop:
        q.pop(u, None)
    for u in [k for k, v in q.items() if isinstance(v, dict) and not v.get("sent") and int(v.get("n") or 0) >= TFILL_TRIES]:
        log.warning("체결 시각 채우기 %s 일시 실패 %d회 — 생성 시각 그대로(대기열에서 뺌)", u[:12], TFILL_TRIES)
        q.pop(u, None)
    if items:
        writer.append({"v": 1, "kind": "ex_order_trades", "exchange": "upbit", "ts": int(time.time()), "src": "upbit_link", "orders": items})
        for it in items:
            if isinstance(q.get(it["uuid"]), dict):
                q[it["uuid"]]["sent"] = now9
        log.info("체결 시각 채우기 %d건 보냄(대기열 %d — 원장 반영 확인 뒤 뺌)", len(items), len(q))
    if q:
        state["tfill"] = q
    else:
        state.pop("tfill", None)
    return len(items)


def extend_orders(up: "Upbit", months: float, target: float, next_state: dict, seen_extra: set):
    now = time.time()
    if next_state.get("ext_target") != int(target):
        next_state["ext_target"] = int(target)
        next_state.setdefault("ext_from", int(now - months * 30 * 86400))
        next_state["ext_start"] = int(next_state["ext_from"])
        next_state["ext_emit"] = 0
    frm = float(next_state.get("ext_from") or (now - months * 30 * 86400))
    start = int(next_state.get("ext_start") or frm)
    if frm <= target:
        return []
    a = max(float(target), frm - EXT_CHUNK)
    seen = set(next_state.get("uuids") or []) | seen_extra | set(next_state.get("open_track") or {})
    out, ok, cur = _sweep(up, a, frm, seen)
    _tfill_add(next_state, out)
    if ok:
        next_state["ext_from"] = int(a)
        next_state["ext_emit"] = int(next_state.get("ext_emit") or 0) + len(out)
    log.info("업비트 과거 창 확장: %s~%s 체결 %d (%s)", _iso(a)[:10], _iso(frm)[:10], len(out), "완료" if ok else "보류")
    bf_engine.progress("ex").update("upbit:extend", phase="extend" if next_state["ext_from"] > target else "done",
                                    unit="sec", done=int(start - next_state["ext_from"]),
                                    total=int(max(1, start - target)), emitted=int(next_state.get("ext_emit") or 0),
                                    target=time.strftime("%Y-%m-%d", time.gmtime(target)))
    return out


_TERMINAL = ("ACCEPTED", "DONE", "CANCELLED", "CANCELED", "REJECTED", "FAILED", "REFUNDED")


class _RowFilter:
    FULL_SEC = 6 * 3600

    def __init__(self):
        self.fp = {}
        self.full_at = 0.0
        self.open = {}
        self._nopen = {}

    @staticmethod
    def _h(r) -> str:
        return hashlib.sha1(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def need_full(self, now=None) -> bool:
        now = time.time() if now is None else now
        return not self.fp or now - self.full_at >= self.FULL_SEC

    def stopper(self, kind: str):
        def stop(rows) -> bool:
            oldest = None
            for r in rows:
                if not isinstance(r, dict) or not r.get("uuid"):
                    return False
                k = kind + ":" + str(r["uuid"])
                if self.fp.get(k) != self._h(r) or str(r.get("state") or "").upper() not in _TERMINAL:
                    return False
                t = _iso_ts(r.get("created_at"))
                if t is None:
                    return False
                oldest = t if oldest is None else min(oldest, t)
            for k, t in self.open.items():
                if k.startswith(kind + ":") and (t is None or oldest is None or t <= oldest):
                    return False
            return oldest is not None
        return stop

    def pick(self, deposits, withdraws, now=None, full=None):
        now = time.time() if now is None else now
        if full is None:
            full = self.need_full(now)
        out = []
        nfp = {}
        self._nopen = {}
        for kind, rows in (("d", deposits or []), ("w", withdraws or [])):
            keep = []
            for r in rows:
                if not isinstance(r, dict):
                    keep.append(r)
                    continue
                k = kind + ":" + str(r.get("uuid") or "")
                h = self._h(r)
                nfp[k] = h
                self._nopen[k] = None if str(r.get("state") or "").upper() in _TERMINAL else (_iso_ts(r.get("created_at")) or 0.0)
                if full or self.fp.get(k) != h:
                    keep.append(r)
            out.append(keep)
        return out[0], out[1], nfp, full

    def commit(self, nfp: dict, full: bool, now=None):
        self.fp.update(nfp)
        for k, t in (self._nopen or {}).items():
            if k not in nfp:
                continue
            if t is None:
                self.open.pop(k, None)
            else:
                self.open[k] = t or None
        if full:
            self.full_at = time.time() if now is None else now
            self.open = {k: t for k, t in self.open.items() if k in nfp}


class _Backoff:
    CAP = {401: 1800, 403: 1800, 429: 600}

    def __init__(self):
        self.n = 0
        self.last_wait = None

    def reset(self):
        self.n = 0
        self.last_wait = None

    def ok(self, poll: int) -> int:
        self.reset()
        return int(poll)

    def fail(self, err, poll: int):
        code = getattr(err, "code", None)
        cap = self.CAP.get(code)
        if cap is None:
            self.n = 0
            return int(poll), True
        wait = min(cap, int(poll) * (2 ** self.n))
        self.n += 1
        loud = wait != self.last_wait
        self.last_wait = wait
        return wait, loud


_ROWS = _RowFilter()


def cycle(up: Upbit, writer: SegmentWriter, months: float):
    if up.remaining_min < 5:
        log.warning("레이트리밋 잔여 %d — 이번 사이클 건너뜀(계정 공유 보호)", up.remaining_min)
        time.sleep(10)
        up.remaining_min = 999
        return
    oo1 = _open_orders(up)
    time.sleep(0.2)
    accounts = up.get("/v1/accounts")
    time.sleep(0.2)
    oo2 = _open_orders(up) if oo1 is not None else None
    open_ok = oo1 is not None and oo2 is not None
    prev9 = common.read_json(ORDERS_STATE, {}) if os.path.exists(ORDERS_STATE) else {}
    if prev9.get("complete"):
        prev9["complete"] = False
        common.atomic_write_json(ORDERS_STATE, prev9)
    snap = {"ts": int(time.time()), "accounts": accounts}
    if oo1 is not None and oo2 is not None and _oo_sig(oo1) == _oo_sig(oo2):
        snap["open_orders"] = oo2
    common.atomic_write_json(BAL_PATH, snap)
    time.sleep(0.2)
    target = bf_engine.SINCE.target("upbit")
    m_eff = max(months, (time.time() - target) / (30 * 86400)) if target else months
    pages = int(60 * max(1.0, m_eff / 5.0))
    full0 = _ROWS.need_full()
    deposits = _paged(up, "/v1/deposits", m_eff, pages, stop=None if full0 else _ROWS.stopper("d"))
    time.sleep(0.2)
    withdraws = _paged(up, "/v1/withdraws", m_eff, pages, stop=None if full0 else _ROWS.stopper("w"))
    nd9, nw9, nfp9, full9 = _ROWS.pick(deposits, withdraws, full=full0)
    if nd9 or nw9 or full9:
        writer.append({"v": 1, "kind": "ex_snapshot", "exchange": "upbit",
                       "ts": int(time.time()),
                       "deposits": nd9, "withdraws": nw9})
    _ROWS.commit(nfp9, full9)
    orders, sweep_ok, next_state = fetch_orders(up, months, oo2 if oo2 is not None else oo1)
    if target and target < time.time() - months * 30 * 86400:
        orders = orders + extend_orders(up, months, target, next_state, {o["uuid"] for o in orders})
        next_state["uuids"] = sorted(set(next_state.get("uuids") or []) | {o["uuid"] for o in orders})[-20000:]
    if orders:
        writer.append({"v": 1, "kind": "ex_fills", "exchange": "upbit",
                       "ts": int(time.time()), "orders": orders})
    try:
        _tfill_pass(up, writer, next_state)
    except Exception as e:
        log.warning("체결 시각 채우기 실패(다음 주기 재시도): %s", repr(e)[:140])
    next_state["complete"] = bool(open_ok and sweep_ok and not next_state.get("track_pending"))
    common.atomic_write_json(ORDERS_STATE, next_state)
    pend = int(next_state.get("track_pending") or 0)
    now9 = int(time.time())
    try:
        prev9 = common.read_json(SYNC_PATH, {}) if os.path.exists(SYNC_PATH) else {}
        ps9 = int(prev9.get("pending_since") or 0) if isinstance(prev9, dict) else 0
    except (Exception, SystemExit):
        ps9 = 0
    ps9 = (ps9 or now9) if pend else None
    stuck = bool(pend and now9 - ps9 >= PENDING_MAX)
    if not sweep_ok:
        err, kind = "체결 조회(orders/closed) 실패 — 다음 주기 재시도", "sweep"
    elif not open_ok:
        err, kind = "미체결 주문 조회 실패 — 오래 걸린 체결 추적 보류(다음 주기 재시도)", "open"
    elif stuck:
        err, kind = f"체결 확정 대기 {pend}건이 {(now9 - ps9) // 3600}시간 넘게 — 단건 조회(/v1/order) 실패 반복", "pending"
    else:
        err, kind = None, None
    _sync_note(ok=err is None, err=err, kind=kind, track_pending=pend, pending_since=ps9, complete=bool(next_state["complete"]))
    _SYNC_N[0] += 1
    if orders or _SYNC_N[0] % 10 == 1:
        log.info("동기화: 잔고 %d종, 입금 %d, 출금 %d, 신규체결주문 %d",
                 len(accounts or []), len(deposits or []), len(withdraws or []), len(orders))


_SYNC_N = [0]
SYNC_PATH = os.path.join(common.STATE_DIR, "upbit_sync.json")


PENDING_MAX = 7200


def _sync_note(ok: bool, err=None, kind=None, **extra) -> None:
    try:
        d = common.read_json(SYNC_PATH, {}) if os.path.exists(SYNC_PATH) else {}
        if not isinstance(d, dict):
            d = {}
    except (Exception, SystemExit):
        d = {}
    try:
        now = int(time.time())
        d["v"], d["ts"] = 1, now
        if ok:
            d["last_ok"] = now
        if err:
            d["last_err"] = {"ts": now, "msg": common.safe_err(err)[:200], "kind": kind or "cycle"}
        for k, v in extra.items():
            d[k] = v
        common.atomic_write_json(SYNC_PATH, d)
    except Exception as e:
        log.warning("업비트 동기화 상태 기록 실패(무시): %s", common.safe_err(e)[:120])


def _ensure_client(up, a, s):
    if up is None or up.access != a or up.secret != s:
        return Upbit(a, s)
    return up


def _cycle_once(up, writer, months: float, bo: "_Backoff", poll: int) -> int:
    up._backoff_err = None
    try:
        cycle(up, writer, months)
        if up._backoff_err is not None:
            raise up._backoff_err
        return bo.ok(poll)
    except Exception as e:
        wait9, loud9 = bo.fail(e, poll)
        if loud9:
            log.warning("동기화 실패(%s초 뒤 재시도): %s", wait9, e)
        _sync_note(ok=False, err=f"동기화 실패: {common.safe_err(e)[:160]}")
        return wait9


def main():
    common.ensure_dirs()
    unit_beat.start("ex")
    writer = SegmentWriter(os.path.join(common.INBOX_DIR, "ex"))
    warned = False
    up = None
    bo = _Backoff()
    while True:
        env = _env()
        a, s = env.get("UPBIT_ACCESS"), env.get("UPBIT_SECRET")
        if not a or not s:
            if not warned:
                log.info("UPBIT_ACCESS/UPBIT_SECRET 대기 중 — .env 에 조회전용 키를 넣으면 즉시 동기화")
                warned = True
            time.sleep(60)
            continue
        warned = False
        up9 = _ensure_client(up, a, s)
        if up9 is not up:
            bo.reset()
        up = up9
        poll9 = POLL_SEC
        months = 5
        try:
            cfg = common.load_config()
            poll9 = common.upbit_poll_sec(cfg)
            months = (0 if cfg.get("backfill_full_history") else float(cfg.get("backfill_months") or 5)) or 5
            wait9 = _cycle_once(up, writer, months, bo, poll9)
        except Exception as e:
            wait9, _l9 = bo.fail(e, poll9)
            log.warning("동기화 실패(다음 주기 재시도): %s", e)
            _sync_note(ok=False, err=f"동기화 실패: {common.safe_err(e)[:160]}")
        end9 = time.time() + (wait9 if wait9 is not None else poll9)
        while True:
            left9 = end9 - time.time()
            if left9 <= 0:
                break
            time.sleep(min(60.0, left9))
            if left9 > 60:
                e9 = _env()
                if (e9.get("UPBIT_ACCESS"), e9.get("UPBIT_SECRET")) != (a, s):
                    break


if __name__ == "__main__":
    main()
