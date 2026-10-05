"""Other assets tab (real estate, stocks, gold, cash, debt) and broker sync."""
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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import common

log = logging.getLogger("tj-web")
KST = timezone(timedelta(hours=9))
SCHEMA = 1
STORE_PATH = os.path.join(common.STATE_DIR, "other_assets.json")
PX_PATH = os.path.join(common.STATE_DIR, "other_assets_px.json")
STORE_LOCK = threading.RLock()

CATS = {"realestate": "부동산", "stock": "주식", "gold": "금", "car": "자동차", "cash": "현금", "etc": "기타", "debt": "부채"}
CURS = ("KRW", "USD")
OZT_G = 31.1034768
MAX_ITEMS = 300
MAX_HIST = 400
NAME_MAX = 60
MEMO_MAX = 300
VAL_MAX = 1e13
QTY_MAX = 1e12
ID_RE = re.compile(r"^(?:oa|brk)_[0-9a-f]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TICKER_RE = re.compile(r"^(?:[0-9][0-9A-Z]{5}(?:\.(?:KS|KQ))?|[A-Z]{1,6}(?:[.\-][A-Z]{1,2})?)$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


class StoreError(Exception):
    pass


def _now() -> float:
    return time.time()


def today_iso(now: float | None = None) -> str:
    return datetime.fromtimestamp(now if now is not None else _now(), KST).strftime("%Y-%m-%d")


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


PX_MIN, PX_MAX = 1e-6, 1e9


def _px(v):
    return float(v) if _fin(v) and PX_MIN <= v <= PX_MAX else None


def _jsafe(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _jsafe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsafe(v) for v in o]
    return o


def atomic_write(path: str, obj) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".tmp_oa_%s_%s" % (os.getpid(), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        try:
            dfd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def empty_store() -> dict:
    return {"v": SCHEMA, "items": [], "bst": {}, "updated": 0}


def load_store(path: str | None = None) -> dict:
    path = path or STORE_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return empty_store()
    except (OSError, ValueError) as e:
        raise StoreError("기타 자산 파일을 읽지 못했어요(손상) — 덮어쓰지 않았어요") from e
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        raise StoreError("기타 자산 파일 형식이 맞지 않아요 — 덮어쓰지 않았어요")
    v = d.get("v")
    if not isinstance(v, int) or v > SCHEMA:
        raise StoreError("기타 자산 파일 버전(%r)을 모르는 서버예요 — 덮어쓰지 않았어요" % (v,))
    d.setdefault("bst", {})
    for x in d["items"]:
        why = _item_bad(x)
        if why:
            raise StoreError("기타 자산 항목 일부가 손상됐어요(%s) — 덮어쓰지 않았어요" % why)
    return d


def _item_bad(x) -> str | None:
    if not isinstance(x, dict) or not isinstance(x.get("id"), str) or not ID_RE.fullmatch(x["id"]):
        return "id"
    if x.get("cat") not in CATS:
        return "cat"
    if x.get("cur") is not None and x.get("cur") not in CURS:
        return "cur"
    if x.get("auto") not in (None, "stock", "gold"):
        return "auto"
    for k in ("name", "memo", "ticker", "unit", "date", "ysym", "broker", "bname", "qerr", "gsrc"):
        if x.get(k) is not None and not isinstance(x.get(k), str):
            return k
    if x.get("liab") is not None and not isinstance(x.get("liab"), bool):
        return "liab"
    for k, hi in (("value", None), ("qty", QTY_MAX), ("avg", None), ("px", None)):
        v = x.get(k)
        if v is not None and (not _fin(v) or v < 0 or (hi is not None and v > hi)):
            return k
    if x.get("ticker") and norm_ticker(x["ticker"])[0] is None:
        return "ticker"
    if x.get("auto"):
        if not (_fin(x.get("qty")) and x["qty"] > 0):
            return "qty"
        if x["auto"] == "stock" and (x.get("cat") != "stock" or not norm_ticker(x.get("ticker") or "")[0]):
            return "ticker"
        if x["auto"] == "gold" and x.get("cat") != "gold":
            return "cat"
    h = x.get("hist")
    if h is not None and (not isinstance(h, list) or any(not isinstance(e, dict) or (e.get("value") is not None and not _fin(e.get("value"))) for e in h)):
        return "hist"
    return None


def save_store(d: dict, path: str | None = None) -> None:
    d["v"] = SCHEMA
    d["updated"] = int(_now())
    atomic_write(path or STORE_PATH, d)


def load_px(path: str | None = None) -> dict:
    try:
        with open(path or PX_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("q"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"v": 1, "q": {}, "host_until": 0, "host_back": 0}


def clean_text(v, lim: int, field: str, required=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        return None, f"{field} 는 문자열"
    v = CTRL_RE.sub("", v).strip()
    if required and not v:
        return None, f"{field} 를 입력하세요"
    if len(v) > lim:
        return None, f"{field} 는 {lim}자 이하"
    return v, None


def norm_ticker(t):
    if not isinstance(t, str):
        return None, "종목 코드는 문자열"
    s = t.strip().upper()
    if not s:
        return "", []
    if len(s) > 12 or not TICKER_RE.match(s):
        return None, "종목 코드 형식이 아니에요(미국 AAPL · 국내 005930 · 005930.KQ)"
    if re.match(r"^[0-9][0-9A-Z]{5}$", s):
        return s, [s + ".KS", s + ".KQ"]
    if re.match(r"^[0-9][0-9A-Z]{5}\.(KS|KQ)$", s):
        return s, [s]
    return s, [s.replace(".", "-")]


def _num(v, field, lo, hi, allow_none=True):
    if v is None or v == "":
        return (None, None) if allow_none else (None, f"{field} 를 입력하세요")
    if isinstance(v, bool):
        return None, f"{field} 는 숫자"
    if isinstance(v, str):
        try:
            v = float(v.replace(",", "").strip())
        except ValueError:
            return None, f"{field} 는 숫자"
    if not _fin(v):
        return None, f"{field} 는 유한한 숫자"
    if v < lo or v > hi:
        return None, f"{field} 범위 밖({lo:g}~{hi:g})"
    return float(v), None


def validate(body: dict, cur_item: dict | None, now: float | None = None):
    out = {}
    name, e = clean_text(body.get("name", (cur_item or {}).get("name")), NAME_MAX, "이름", required=True)
    if e:
        return None, e
    out["name"] = name
    cat = body.get("cat", (cur_item or {}).get("cat"))
    if cat not in CATS:
        return None, "종류는 " + "·".join(CATS.values()) + " 가운데 하나"
    out["cat"] = cat
    brk = (cur_item or {}).get("broker")
    if brk and cat != (cur_item or {}).get("cat"):
        return None, "증권사에서 가져온 항목은 종류를 바꿀 수 없어요"
    cur = body.get("cur", (cur_item or {}).get("cur") or "KRW")
    if cur not in CURS:
        return None, "통화는 KRW 또는 USD"
    out["cur"] = cur
    memo, e = clean_text(body.get("memo", (cur_item or {}).get("memo")), MEMO_MAX, "메모")
    if e:
        return None, e
    out["memo"] = memo
    liab = body.get("liab", False)
    if not isinstance(liab, bool):
        return None, "부채 표시는 true/false"
    out["liab"] = cat == "debt"
    qty, e = _num(body.get("qty", (cur_item or {}).get("qty")), "수량", 0, QTY_MAX)
    if e:
        return None, e
    out["qty"] = qty
    unit = body.get("unit", (cur_item or {}).get("unit") or "")
    if cat == "gold":
        unit = unit if unit in ("g", "ozt") else "g"
    elif cat == "stock":
        unit = "주"
    else:
        unit, e = clean_text(unit, 8, "단위")
        if e:
            return None, e
    out["unit"] = unit
    tk = body.get("ticker", (cur_item or {}).get("ticker") or "")
    if cat != "stock":
        tk = ""
    disp, cands = norm_ticker(tk)
    if disp is None:
        return None, cands
    if brk and disp != ((cur_item or {}).get("ticker") or ""):
        return None, "증권사에서 가져온 항목은 종목 코드를 바꿀 수 없어요"
    out["ticker"] = disp
    auto = None
    if cat == "stock" and disp:
        auto = "stock"
    elif cat == "gold" and qty:
        auto = "gold"
    out["auto"] = auto
    if auto and not qty:
        return None, "시세 자동 평가는 수량이 필요해요"
    if brk and qty != (cur_item or {}).get("qty"):
        return None, "증권사에서 가져온 항목은 수량을 바꿀 수 없어요(다음 동기화가 덮어써요)"
    raw = body.get("value") if auto else body.get("value", (cur_item or {}).get("value"))
    if cat == "gold" and qty == 0 and body.get("value") in (None, ""):
        raw = 0.0
    val, e = _num(raw, "평가액", 0, VAL_MAX)
    if e:
        return None, e
    if val is None and not auto:
        return None, "평가액을 입력하세요"
    out["value"] = val
    d = body.get("date") or (cur_item or {}).get("date") or today_iso(now)
    if not isinstance(d, str) or not DATE_RE.match(d):
        return None, "평가일은 YYYY-MM-DD"
    try:
        dd = datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return None, "평가일이 달력에 없는 날"
    t0 = datetime.fromtimestamp(now if now is not None else _now(), KST).date()
    if dd > t0 + timedelta(days=1) or dd.year < 1970:
        return None, "평가일이 미래예요"
    out["date"] = d
    return out, None


def _hist_add(it: dict, ent: dict) -> None:
    h = it.setdefault("hist", [])
    if ent.get("src") == "auto" and h and h[-1].get("src") == "auto" and h[-1].get("date") == ent.get("date"):
        h[-1] = ent
    else:
        h.append(ent)
    while len(h) > MAX_HIST:
        idx = next((i for i, x in enumerate(h) if x.get("src") == "auto"), 0)
        h.pop(idx)


def _new_id(prefix="oa") -> str:
    return prefix + "_" + secrets.token_hex(6)


def apply_save(d: dict, body: dict, now: float | None = None):
    now = now if now is not None else _now()
    iid = body.get("id")
    cur_item = None
    if iid not in (None, ""):
        if not isinstance(iid, str) or not ID_RE.match(iid):
            return None, (400, "id 형식 오류")
        cur_item = next((x for x in d["items"] if x.get("id") == iid), None)
        if cur_item is None:
            return None, (404, "없는 항목이에요(다른 화면에서 지웠을 수 있어요)")
    elif len(d["items"]) >= MAX_ITEMS:
        return None, (400, f"항목은 {MAX_ITEMS}개까지")
    f, e = validate(body, cur_item, now)
    if e:
        return None, (400, e)
    if cur_item is None:
        it = {"id": _new_id(), "created": int(now)}
        d["items"].append(it)
    else:
        it = cur_item
    old = {k: it.get(k) for k in ("value", "qty", "cur", "date", "ticker", "auto", "unit")}
    if f["auto"] and f["value"] is None:
        f["value"] = it.get("value") if (old["ticker"] == f["ticker"] and old["auto"] == f["auto"] and old["unit"] == f["unit"]) else None
    if old["ticker"] != f["ticker"]:
        it.pop("ysym", None)
        it.pop("qerr", None)
    if f["auto"] and body.get("value") in (None, "") and old["qty"] and f["qty"] and old["value"] and old["qty"] != f["qty"] and old["auto"] == f["auto"] and old["ticker"] == f["ticker"] and old["unit"] == f["unit"]:
        f["value"] = old["value"] / old["qty"] * f["qty"]
    it.update(f)
    it["updated"] = int(now)
    changed = cur_item is None or any(old[k] != it.get(k) for k in ("value", "qty", "cur", "date"))
    if changed and it.get("value") is not None:
        _hist_add(it, {"at": int(now), "date": it["date"], "value": it["value"], "qty": it.get("qty"), "cur": it["cur"], "src": "manual"})
    return it, None


def apply_delete(d: dict, iid) -> tuple:
    if not isinstance(iid, str) or not ID_RE.match(iid):
        return False, (400, "id 형식 오류")
    n0 = len(d["items"])
    d["items"] = [x for x in d["items"] if x.get("id") != iid]
    if len(d["items"]) == n0:
        return False, (404, "없는 항목이에요")
    return True, None


YH_HOST = "https://query1.finance.yahoo.com"
YH_UA = "Mozilla/5.0"
STALE_SEC = 6 * 3600
CLOSES_EVERY = 20 * 3600


def yh_url(sym: str, rng: str) -> str:
    return f"{YH_HOST}/v8/finance/chart/{urllib.parse.quote(sym, safe='')}?range={urllib.parse.quote(rng, safe='')}&interval=1d&includePrePost=false"


def default_http_get(url: str, timeout: float = 12.0):
    req = urllib.request.Request(url, headers={"User-Agent": YH_UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


TS_LO, TS_HI = 0, 4102444800


def _day(ts, off):
    if not _fin(ts) or not (TS_LO <= ts + off <= TS_HI):
        return None
    try:
        return datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def parse_chart(body: bytes):
    try:
        return _parse_chart(body)
    except Exception:
        return None


def _parse_chart(body: bytes):
    try:
        j = json.loads(body.decode("utf-8"))
        res = ((j.get("chart") or {}).get("result") or [None])[0]
        meta = res.get("meta") or {}
    except (ValueError, AttributeError, TypeError, IndexError, UnicodeDecodeError):
        return None
    if not isinstance(res, dict) or not isinstance(meta, dict):
        return None
    px = _px(meta.get("regularMarketPrice"))
    if px is None:
        return None
    off = meta.get("gmtoffset") if _fin(meta.get("gmtoffset")) and abs(meta.get("gmtoffset")) <= 86400 else 0
    ts = res.get("timestamp") if isinstance(res.get("timestamp"), list) else []
    try:
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    except (AttributeError, IndexError, TypeError):
        cl = []
    if not isinstance(cl, list):
        cl = []
    closes = []
    for t9, c9 in zip(ts, cl):
        if _px(c9) is not None:
            dk = _day(t9, off)
            if dk is None:
                continue
            if closes and closes[-1][0] == dk:
                closes[-1] = [dk, float(c9)]
            else:
                closes.append([dk, float(c9)])
    mt = meta.get("regularMarketTime") if _day(meta.get("regularMarketTime"), off) else None
    mday = _day(mt, off) if mt else None
    prev = None
    if closes:
        if mday and closes[-1][0] == mday:
            prev = closes[-2][1] if len(closes) > 1 else None
        else:
            prev = closes[-1][1]
    if prev is None and _px(meta.get("chartPreviousClose")) is not None and len(closes) <= 1:
        prev = float(meta["chartPreviousClose"])
    cur = str(meta.get("currency") or "").upper()[:6]
    name = str(meta.get("shortName") or meta.get("longName") or meta.get("symbol") or "")[:60]
    exch = str(meta.get("fullExchangeName") or meta.get("exchangeName") or "")[:30]
    return {"px": float(px), "cur": cur, "prev": prev, "t": int(mt) if mt else None, "mday": mday,
            "name": CTRL_RE.sub("", name), "exch": CTRL_RE.sub("", exch), "closes": closes,
            "tz": str(meta.get("exchangeTimezoneShortName") or meta.get("timezone") or "")[:8], "off": int(off)}


class Quoter:
    MIN_GAP = 2.0
    TRIES = 2
    RETRY_WAIT = 3.0
    MAX_PER_CYCLE = 40
    LOOKUP_BUDGET = 60
    LOOKUP_WAIT = 15.0

    def __init__(self, http_get=None, sleep=None, now=None, rate_fn=None, paxg_fn=None, cfg_fn=None,
                 store_path=None, px_path=None, http_json=None):
        self.http_get = http_get or default_http_get
        self.sleep = sleep or time.sleep
        self.now = now or _now
        self.rate_fn = rate_fn or (lambda: 0)
        self.paxg_fn = paxg_fn or (lambda: None)
        self.cfg_fn = cfg_fn or (lambda: {})
        self.http_json = http_json
        self.store_path = store_path or STORE_PATH
        self.px_path = px_path or PX_PATH
        self.px = load_px(self.px_path)
        self.px_lock = threading.RLock()
        self.call_lock = threading.Lock()
        self.lookup_lock = threading.Lock()
        self._last_call = 0.0
        self.wake = threading.Event()
        self.calls = 0
        self._lookups = []
        self.bst = {}
        self._brk_at = {}
        self._brk_empty = {}

    BLOCKED = -429

    def _paced_get(self, url):
        with self.call_lock:
            if self._host_blocked():
                return self.BLOCKED, b""
            gap = self.MIN_GAP - (self.now() - self._last_call)
            if gap > 0:
                self.sleep(gap)
                if self._host_blocked():
                    return self.BLOCKED, b""
            self._last_call = self.now()
            self.calls += 1
            st, body = self.http_get(url)
            if st == 429:
                with self.px_lock:
                    back = min(7200, max(900, float(self.px.get("host_back") or 0) * 2 or 900))
                    self.px["host_back"] = back
                    self.px["host_until"] = self.now() + back
            return st, body

    def _host_blocked(self):
        return self.now() < float(self.px.get("host_until") or 0)

    def fetch_sym(self, sym: str, rng: str = "5d"):
        if self._host_blocked():
            return None, "시세 서버가 잠시 막혀 쉬는 중", 429
        st, body = 0, b""
        for i in range(self.TRIES):
            st, body = self._paced_get(yh_url(sym, rng))
            if st == self.BLOCKED:
                return None, "시세 서버가 잠시 막혀 쉬는 중", 429
            if st == 200:
                q = parse_chart(body)
                if q:
                    with self.px_lock:
                        self.px["host_back"] = 0
                    return q, None, 200
                return None, "시세 응답 형식이 달라요", 200
            if st == 404:
                return None, "종목을 찾지 못했어요", 404
            if st == 429:
                return None, "시세 서버 요청 한도 — 잠시 쉬어요", 429
            if i + 1 < self.TRIES:
                self.sleep(self.RETRY_WAIT)
        return None, ("시세 서버 응답 %d" % st) if st else "시세 서버에 연결하지 못했어요", st

    def _rec(self, sym, q, err, rng):
        now = self.now()
        with self.px_lock:
            r = self.px["q"].setdefault(sym, {})
            if q:
                r.update({k: q[k] for k in ("px", "cur", "prev", "t", "mday", "name", "exch", "tz", "off")})
                r["at"] = int(now)
                r["fails"] = 0
                r["next"] = 0
                r.pop("err", None)
                if q["closes"]:
                    old = {c[0]: c[1] for c in (r.get("closes") or [])}
                    for dk, c in q["closes"]:
                        old[dk] = c
                    keep = sorted(old.items())[-400:]
                    r["closes"] = [[k, v] for k, v in keep]
                    if rng == "1y":
                        r["closes_at"] = int(now)
            else:
                f = int(r.get("fails") or 0) + 1
                r["fails"] = f
                r["err"] = err
                r["next"] = int(now + min(6 * 3600, 900 * 2 ** (f - 1)))
            r["seen"] = int(now)

    def quote_cached(self, sym):
        with self.px_lock:
            r = self.px["q"].get(sym)
            return dict(r) if r else None

    def _save_px(self):
        with self.px_lock:
            cut = self.now() - 30 * 86400
            self.px["q"] = {k: v for k, v in self.px["q"].items() if float(v.get("seen") or 0) >= cut}
            try:
                atomic_write(self.px_path, self.px)
            except OSError as e:
                _warn("시세 캐시 저장 실패: %s", type(e).__name__)

    def lookup(self, ticker: str):
        disp, cands = norm_ticker(ticker)
        if disp is None:
            return {"ok": False, "error": cands}, 400
        if not disp:
            return {"ok": False, "error": "종목 코드를 입력하세요"}, 400
        if not self.lookup_lock.acquire(timeout=self.LOOKUP_WAIT):
            return {"ok": False, "error": "종목 확인이 밀려 있어요 — 잠시 뒤 다시"}, 429
        try:
            return self._lookup(disp, cands)
        finally:
            self.lookup_lock.release()

    def _lookup(self, disp, cands):
        now = self.now()
        for sym in cands:
            c = self.quote_cached(sym)
            if c and c.get("px") and now - float(c.get("at") or 0) < 600:
                return _lookup_out(disp, sym, c), 200
        self._lookups = [t for t in self._lookups if now - t < 3600]
        if len(self._lookups) >= self.LOOKUP_BUDGET:
            return {"ok": False, "error": "종목 확인을 너무 자주 했어요 — 잠시 뒤 다시"}, 429
        self._lookups.append(now)
        last = None
        for sym in cands:
            try:
                q, err, st = self.fetch_sym(sym, "1y")
            except Exception as e:
                q, err, st = None, "시세 처리 실패(%s)" % type(e).__name__, 0
            if q:
                self._rec(sym, q, err, "1y")
                self._save_px()
                return _lookup_out(disp, sym, self.quote_cached(sym)), 200
            last = (err, st)
            if st not in (404, 200):
                break
        err, st = last or ("종목을 찾지 못했어요", 404)
        return {"ok": False, "error": err}, (429 if st == 429 else 404 if st in (404, 200) else 502)

    def gold_px(self):
        try:
            p = self.paxg_fn()
        except Exception:
            p = None
        if _px(p) is not None:
            return float(p), "PAXG", int(self.now())
        c = self.quote_cached("GC=F")
        if c and _px(c.get("px")) is not None:
            return float(c["px"]), "GC=F", int(c.get("at") or 0)
        return None, None, None

    def cycle(self):
        n0 = self.calls
        cfg = (self.cfg_fn() or {}).get("other_assets") or {}
        if cfg.get("quotes") is False:
            return 0
        try:
            with STORE_LOCK:
                d = load_store(self.store_path)
        except StoreError:
            return 0
        need = {}
        gold = False
        for it in d["items"]:
            if it.get("auto") == "stock" and it.get("ticker"):
                disp, cands = norm_ticker(it["ticker"])
                if not disp:
                    continue
                ys = it.get("ysym")
                need[ys or cands[0]] = [ys] if ys else cands
            elif it.get("auto") == "gold":
                gold = True
        if gold:
            need["GC=F"] = ["GC=F"]
        now = self.now()
        every = max(300.0, float(cfg.get("quote_every_sec") or 900))
        done = 0

        def last_try(kv):
            return min(float((self.quote_cached(s) or {}).get("seen") or 0) for s in kv[1])

        for key, cands in sorted(need.items(), key=lambda kv: (last_try(kv), kv[0])):
            if done >= self.MAX_PER_CYCLE or self._host_blocked():
                break
            for sym in cands:
                c = self.quote_cached(sym) or {}
                if float(c.get("next") or 0) > now:
                    continue
                fresh = now - float(c.get("closes_at") or 0) < CLOSES_EVERY and c.get("px")
                if sym == "GC=F" and fresh and now - float(c.get("at") or 0) < 3600:
                    break
                if sym != "GC=F" and fresh and not c.get("fails") and now - float(c.get("at") or 0) < every:
                    break
                rng = "1y" if now - float(c.get("closes_at") or 0) > CLOSES_EVERY else "5d"
                try:
                    q, err, st = self.fetch_sym(sym, rng)
                except Exception as e:
                    q, err, st = None, "시세 처리 실패(%s)" % type(e).__name__, 0
                done += 1
                self._rec(sym, q, err, rng)
                if q or st != 404 or sym == cands[-1]:
                    break
        self._save_px()
        self.apply_quotes()
        return self.calls - n0

    def apply_quotes(self):
        now = self.now()
        gpx, gsrc, gat = self.gold_px()
        with STORE_LOCK:
            try:
                d = load_store(self.store_path)
            except StoreError:
                return False
            ch = False
            for it in d["items"]:
                if it.get("auto") == "stock" and it.get("ticker"):
                    disp, cands = norm_ticker(it["ticker"])
                    if not disp:
                        continue
                    syms = [it["ysym"]] if it.get("ysym") else cands
                    c = None
                    for s in syms:
                        c9 = self.quote_cached(s)
                        if c9 and _px(c9.get("px")) is not None:
                            c, sym = c9, s
                            break
                    if not c:
                        last = self.quote_cached(syms[-1]) or {}
                        if last.get("err") and it.get("qerr") != last["err"]:
                            it["qerr"] = last["err"]
                            ch = True
                        continue
                    if it.get("ysym") != sym:
                        it["ysym"] = sym
                        ch = True
                    it.pop("qerr", None)
                    if c.get("cur") in CURS and it.get("cur") != c["cur"]:
                        it["cur"] = c["cur"]
                        ch = True
                    elif c.get("cur") not in CURS:
                        e9 = "지원하지 않는 통화(%s)" % (c.get("cur") or "?")
                        if it.get("qerr") != e9:
                            it["qerr"] = e9
                            ch = True
                        continue
                    v = float(it.get("qty") or 0) * float(c["px"])
                    if not _fin(v):
                        continue
                    dk = c.get("mday") or today_iso(now)
                    if it.get("value") != v or it.get("date") != dk or it.get("px") != c["px"]:
                        it["value"], it["date"], it["px"] = v, dk, c["px"]
                        _hist_add(it, {"at": int(now), "date": dk, "value": v, "qty": it.get("qty"), "cur": it["cur"], "src": "auto", "px": c["px"]})
                        ch = True
                elif it.get("auto") == "gold" and gpx:
                    oz = float(it.get("qty") or 0) / (OZT_G if it.get("unit") != "ozt" else 1.0)
                    v = oz * gpx
                    if not _fin(v):
                        continue
                    dk = today_iso(now)
                    if it.get("cur") != "USD":
                        it["cur"] = "USD"
                    if it.get("value") != v or it.get("date") != dk or it.get("gsrc") != gsrc:
                        it["value"], it["date"], it["px"], it["gsrc"], it["gat"] = v, dk, gpx, gsrc, gat
                        _hist_add(it, {"at": int(now), "date": dk, "value": v, "qty": it.get("qty"), "cur": "USD", "src": "auto", "px": gpx})
                        ch = True
            if ch:
                save_store(d, self.store_path)
            return ch

    def broker_cycle(self, force=False):
        cfg = self.cfg_fn() or {}
        bc = cfg.get("brokers") if isinstance(cfg.get("brokers"), dict) else {}
        every = float(((cfg.get("other_assets") or {}).get("broker_every_sec")) or 3600)
        from brokers import ADAPTERS, run_sync
        n = 0
        for key, b in bc.items():
            if key not in ADAPTERS or not isinstance(b, dict) or b.get("enabled") is not True:
                continue
            if not force and self.now() - self._brk_at.get(key, 0) < every:
                continue
            self._brk_at[key] = self.now()
            res = run_sync(key, b, self.http_json)
            self.bst[key] = {k: res[k] for k in ("at", "ok", "n", "err") if k in res}
            if res.get("ok"):
                self.merge_broker(key, res)
            n += 1
        return n

    def _brk_fail(self, key, now, err):
        st = dict(self.bst.get(key) or {})
        st.update({"at": int(now), "ok": False, "err": err})
        self.bst[key] = st

    def merge_broker(self, key: str, res: dict):
        now = self.now()
        acct = str(res.get("acct") or "")
        want = {}
        pxs = {}
        for p in res.get("positions") or []:
            disp, cands = norm_ticker(str(p.get("sym") or ""))
            q = p.get("qty")
            if not disp or not _fin(q) or q <= 0 or q > QTY_MAX:
                continue
            iid = "brk_" + hashlib.sha1(f"{key}|{acct}|{disp}".encode()).hexdigest()[:12]
            cur = p.get("cur") if p.get("cur") in CURS else ("KRW" if cands[0].endswith((".KS", ".KQ")) else "USD")
            px, avg = _px(p.get("px")), _px(p.get("avg"))
            w = want.get(iid)
            if w is None:
                want[iid] = {"cat": "stock", "ticker": disp, "qty": float(q), "unit": "주", "auto": "stock", "liab": False,
                             "name": (CTRL_RE.sub("", str(p.get("name") or disp)).strip() or disp)[:NAME_MAX],
                             "cur": cur, "avg": avg, "_avgq": float(q) if avg is not None else 0.0, "_avgs": avg * float(q) if avg is not None else 0.0}
            else:
                w["qty"] += float(q)
                if avg is not None:
                    w["_avgq"] += float(q)
                    w["_avgs"] += avg * float(q)
                    w["avg"] = w["_avgs"] / w["_avgq"]
                if cur != w["cur"]:
                    w["_curx"] = True
            if px is not None and iid not in pxs:
                pxs[iid] = px
        for iid, w in want.items():
            px = pxs.get(iid)
            w["value"] = w["qty"] * px if px is not None and not w.get("_curx") else None
            for k9 in ("_avgq", "_avgs", "_curx"):
                w.pop(k9, None)
        cash = {}
        for c in res.get("cash") or []:
            amt, cur = c.get("amount"), c.get("cur")
            if not _fin(amt) or abs(amt) > VAL_MAX or cur not in CURS:
                continue
            cash[cur] = cash.get(cur, 0.0) + float(amt)
        for cur, amt in cash.items():
            if amt >= 0:
                iid = "brk_" + hashlib.sha1(f"{key}|{acct}|cash|{cur}".encode()).hexdigest()[:12]
                want[iid] = {"cat": "cash", "ticker": "", "qty": None, "unit": "", "auto": None, "liab": False, "name": "예수금(%s)" % cur,
                             "cur": cur, "value": amt}
            else:
                iid = "brk_" + hashlib.sha1(f"{key}|{acct}|cashneg|{cur}".encode()).hexdigest()[:12]
                want[iid] = {"cat": "debt", "ticker": "", "qty": None, "unit": "", "auto": None, "liab": True, "name": "마이너스 예수금(%s)" % cur,
                             "cur": cur, "value": -amt}
        from brokers import ADAPTERS
        bname = ADAPTERS[key].NAME
        with STORE_LOCK:
            try:
                d = load_store(self.store_path)
            except StoreError:
                return False
            have = {x["id"]: x for x in d["items"] if x.get("broker") == key}
            kept = [x for x in d["items"] if x.get("broker") != key or x["id"] in want]
            if len(kept) + sum(1 for iid in want if iid not in have) > MAX_ITEMS:
                self._brk_fail(key, now, "기타 자산 항목 상한(%d개) 초과 — 이번 동기화를 반영하지 않았어요(합계 미확정)" % MAX_ITEMS)
                return False
            if not want and have:
                if not self._brk_empty.get(key):
                    self._brk_empty[key] = True
                    self._brk_fail(key, now, "보유·예수금이 하나도 없는 응답 — 기존 항목을 지우지 않고 유지했어요(다음 동기화에도 비면 반영)")
                    return False
            self._brk_empty.pop(key, None)
            d["items"] = kept
            for iid, w in want.items():
                it = have.get(iid)
                if it is None:
                    it = {"id": iid, "created": int(now), "memo": "", "liab": False, "broker": key, "bname": bname}
                    d["items"].append(it)
                prev_q, prev_v, prev_cur = it.get("qty"), it.get("value"), it.get("cur")
                for k9, v9 in w.items():
                    if k9 == "value":
                        continue
                    if k9 == "name" and it.get("name"):
                        continue
                    it[k9] = v9
                if w["value"] is not None:
                    it["value"] = w["value"]
                elif w["cat"] == "stock":
                    if prev_q != it["qty"]:
                        it["value"] = (prev_v / prev_q * it["qty"]) if (_fin(prev_v) and _fin(prev_q) and prev_q > 0 and prev_cur == it["cur"]) else None
                    else:
                        it["value"] = prev_v if prev_cur == it["cur"] else None
                it["date"] = today_iso(now)
                it["updated"] = int(now)
                if it.get("value") is not None and (prev_q != it.get("qty") or (w["cat"] != "stock" and prev_v != it.get("value")) or not it.get("hist")):
                    _hist_add(it, {"at": int(now), "date": it["date"], "value": it["value"], "qty": it.get("qty"), "cur": it["cur"], "src": "broker"})
            d.setdefault("bst", {})[key] = self.bst.get(key, {})
            save_store(d, self.store_path)
        try:
            self.apply_quotes()
        except Exception as e:
            _warn("증권사 동기화 뒤 평가 반영 실패: %s", type(e).__name__)
        return True

    def loop(self):
        self.sleep(20)
        while True:
            cfg = (self.cfg_fn() or {}).get("other_assets") or {}
            every = max(300.0, float(cfg.get("quote_every_sec") or 900))
            try:
                self.cycle()
            except Exception as e:
                _warn("기타 자산 시세 바퀴 실패: %s", type(e).__name__)
            try:
                self.broker_cycle()
            except Exception as e:
                _warn("증권사 동기화 바퀴 실패: %s", type(e).__name__)
            self.wake.wait(every)
            self.wake.clear()


def _warn(fmt, *a):
    try:
        if log:
            log.warning(fmt, *a)
    except Exception:
        pass


def _lookup_out(disp, sym, c):
    return _jsafe({"ok": True, "ticker": disp, "ysym": sym, "name": c.get("name") or disp, "exch": c.get("exch") or "",
            "cur": c.get("cur") or "", "px": c.get("px"), "prev": c.get("prev"), "t": c.get("t")})


def _krw_usd(v, cur, rate):
    if v is None:
        return None, None
    if cur == "KRW":
        return v, (v / rate if rate else None)
    return (v * rate if rate else None), v


def view(d: dict, q: Quoter | None, rate: float, brokers_cfg: dict | None = None, now: float | None = None) -> dict:
    now = now if now is not None else _now()
    rate = float(rate) if _fin(rate) and rate > 0 else 0.0
    out = []
    gpx, gsrc, gat = q.gold_px() if q else (None, None, None)
    for it in d.get("items") or []:
        v = it.get("value")
        cur = it.get("cur") or "KRW"
        krw, usd = _krw_usd(v, cur, rate)
        h = it.get("hist") or []
        prev = None
        for x in reversed(h[:-1] if h else []):
            if x.get("value") != v or x.get("qty") != it.get("qty"):
                prev = x
                break
        o = {k: it.get(k) for k in ("id", "name", "cat", "liab", "qty", "unit", "cur", "ticker", "ysym", "auto", "memo", "date", "broker", "bname", "avg", "px", "gsrc", "created", "updated")}
        o["value"], o["krw"], o["usd"] = v, krw, usd
        if prev and prev.get("value") is not None and v is not None:
            dv = v - prev["value"] if prev.get("cur", cur) == cur else None
            o["dprev"] = {"v": dv, "date": prev.get("date"), "src": prev.get("src"),
                          "krw": _krw_usd(dv, cur, rate)[0] if dv is not None else None, "usd": _krw_usd(dv, cur, rate)[1] if dv is not None else None}
        qs = None
        if it.get("auto") == "stock" and q:
            disp, cands = norm_ticker(it.get("ticker") or "")
            syms = [it["ysym"]] if it.get("ysym") else (cands or [])
            got = [c for c in (q.quote_cached(s) for s in syms) if c]
            qs = next((c for c in got if c.get("px")), got[0] if got else None)
            if qs:
                stale = (not qs.get("px")) or int(qs.get("fails") or 0) > 0 or now - float(qs.get("at") or 0) > STALE_SEC
                o["quote"] = {"px": qs.get("px"), "cur": qs.get("cur"), "prev": qs.get("prev"), "t": qs.get("t"), "tz": qs.get("tz"), "off": qs.get("off"),
                              "name": qs.get("name"), "exch": qs.get("exch"), "at": qs.get("at"), "stale": bool(stale), "err": qs.get("err")}
                if _px(qs.get("px")) is not None and _px(qs.get("prev")) is not None:
                    o["quote"]["chg"] = (qs["px"] / qs["prev"] - 1) * 100
                    dd = float(it.get("qty") or 0) * (qs["px"] - qs["prev"])
                    o["dday"] = {"v": dd, "krw": _krw_usd(dd, cur, rate)[0], "usd": _krw_usd(dd, cur, rate)[1]}
            else:
                o["quote"] = {"stale": True, "err": it.get("qerr") or "시세 받는 중"}
            if it.get("qerr"):
                o["quote"]["err"] = it["qerr"]
                o["quote"]["stale"] = True
        elif it.get("auto") == "gold":
            stale = not gpx or (gat and now - gat > STALE_SEC)
            o["quote"] = {"px": gpx, "cur": "USD", "src": gsrc, "at": gat, "stale": bool(stale), "unit": "ozt"}
            gc = q.quote_cached("GC=F") if q else None
            if gc and _px(gc.get("px")) is not None and _px(gc.get("prev")) is not None:
                o["quote"]["chg"] = (gc["px"] / gc["prev"] - 1) * 100
        ser = []
        if it.get("auto") in ("stock", "gold") and q:
            sym = "GC=F" if it["auto"] == "gold" else (it.get("ysym") or "")
            c = q.quote_cached(sym) if sym else None
            qh = [(x.get("date") or "", x.get("qty")) for x in h if x.get("qty") is not None]
            for dk, cl in (c or {}).get("closes") or []:
                if dk < (qh[0][0] if qh else "9999"):
                    continue
                qq = None
                for hd, hq in qh:
                    if hd <= dk:
                        qq = hq
                if qq is None:
                    continue
                if it["auto"] == "gold":
                    val = float(qq) / (OZT_G if it.get("unit") != "ozt" else 1.0) * cl
                    if gsrc == "PAXG" and gpx and c.get("px"):
                        val *= gpx / c["px"]
                else:
                    val = float(qq) * cl
                ser.append([dk, val])
            ser = ser[-366:]
        if not ser:
            for x in h:
                if x.get("value") is not None and x.get("cur", cur) == cur:
                    if ser and ser[-1][0] == x.get("date"):
                        ser[-1] = [x.get("date"), x["value"]]
                    else:
                        ser.append([x.get("date"), x["value"]])
        if v is not None and (not ser or ser[-1][0] != o["date"]):
            ser.append([o["date"], v])
        o["series"] = ser
        o["hist"] = [{k: x.get(k) for k in ("date", "value", "qty", "cur", "src", "px", "at")} for x in h[-30:]]
        out.append(o)
    tot = {"assets_krw": 0.0, "assets_usd": 0.0, "debt_krw": 0.0, "debt_usd": 0.0}
    for o in out:
        if o["krw"] is None and o["usd"] is None:
            continue
        k = "debt" if o.get("liab") else "assets"
        tot[k + "_krw"] += o["krw"] or 0.0
        tot[k + "_usd"] += o["usd"] or 0.0
    tot["net_krw"] = tot["assets_krw"] - tot["debt_krw"]
    tot["net_usd"] = tot["assets_usd"] - tot["debt_usd"]
    try:
        from brokers import broker_list
        bl = broker_list(brokers_cfg or {}, (q.bst if q else {}) or d.get("bst") or {})
    except Exception:
        bl = []
    ver = hashlib.sha1(json.dumps([d.get("updated"), rate, [(o["id"], o["value"], (o.get("quote") or {}).get("at")) for o in out]],
                                  default=str).encode()).hexdigest()[:12]
    return _jsafe({"ok": True, "v": SCHEMA, "ver": ver, "rate": rate or None, "items": out, "totals": tot, "cats": CATS,
                   "brokers": bl, "gold": {"px": gpx, "src": gsrc}, "at": int(now)})
