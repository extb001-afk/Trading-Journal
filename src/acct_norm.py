"""Account and ticker normalization helpers."""
import bisect
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
log = logging.getLogger("tj-web")
DEFAULT_KRW_USD = 1384.0
_DEFAULT_WARN = [0.0]


def _warn_default(why: str):
    now = time.time()
    if now - _DEFAULT_WARN[0] >= 3600:
        _DEFAULT_WARN[0] = now
        log.warning("환율 데이터 없음(%s) — 원화 환산에 고정값 %.0f 원/달러를 씀(원화 실현·세금 원화가 부정확할 수 있음)", why, DEFAULT_KRW_USD)
_SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed", "ticker_aliases.json")
_ALIAS = None


def _aliases() -> dict:
    global _ALIAS
    if _ALIAS is None:
        try:
            with open(_SEED, encoding="utf-8") as f:
                ex = (json.load(f) or {}).get("exchange") or {}
            _ALIAS = {str(k).lower(): {norm_ticker(a): norm_ticker(b) for a, b in (v or {}).items()}
                      for k, v in ex.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            _ALIAS = {}
    return _ALIAS


def _norm_ticker(sym) -> str:
    s = re.sub(r"#\d+$", "", str(sym or "").strip().upper())
    return s.lstrip("$") or s


_NT_MEMO = {}
_NT_MEMO_MAX = 200000


def norm_ticker(sym) -> str:
    if type(sym) is str:
        r = _NT_MEMO.get(sym)
        if r is None:
            r = _norm_ticker(sym)
            if len(_NT_MEMO) < _NT_MEMO_MAX:
                _NT_MEMO[sym] = r
        return r
    return _norm_ticker(sym)


def canon(sym, ex=None) -> str:
    s = norm_ticker(sym)
    al = _aliases()
    if ex:
        return al.get(str(ex).lower(), {}).get(s, s)
    return s


def same_asset(sym_a, ex_a, sym_b, ex_b) -> bool:
    a, b = canon(sym_a, ex_a), canon(sym_b, ex_b)
    return bool(a) and a == b


def qty_close(recv, sent, rel=0.02) -> bool:
    try:
        r, s = float(recv), float(sent)
    except (TypeError, ValueError):
        return False
    return s > 0 and r > 0 and s * (1 - rel) <= r <= s * (1 + rel)


_ISO_DAY = {}


def iso_day(ts) -> str:
    t = int(ts)
    d = (t + 32400) // 86400
    s = _ISO_DAY.get(d)
    if s is None:
        s = datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d")
        if len(_ISO_DAY) < 200000:
            _ISO_DAY[d] = s
    return s


def mmdd(key) -> str:
    k = str(key or "")
    return k[5:10] if len(k) >= 10 and k[4] == "-" else k[:5]


def month_of(key, today) -> str:
    k = str(key or "")
    if len(k) >= 10 and k[4] == "-":
        return k[:7]
    try:
        mm = int(k[:2])
    except ValueError:
        return ""
    y = today.year if mm <= today.month else today.year - 1
    return f"{y}-{mm:02d}"


class FxBook:

    def __init__(self, web_fx: dict, core_path: str = None, spot_rate: float = None, web_candle: dict = None):
        fx = {}
        cand = {}
        if core_path and os.path.exists(core_path):
            try:
                with open(core_path, encoding="utf-8") as f:
                    d = json.load(f) or {}
                fx.update({int(k): float(v) for k, v in (d.get("fx") or {}).items() if str(k).isdigit() and v})
                cand = dict(d.get("candle") or {})
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        for k, v in (web_fx or {}).items():
            if str(k).isdigit() and v:
                fx[int(k)] = float(v)
        cand.update(web_candle or {})
        self.keys = sorted(fx)
        self.fx = fx
        self.spot_default = not spot_rate
        self.spot = float(spot_rate or DEFAULT_KRW_USD)
        self._cand = cand
        self._csym = {}

    def _near(self, m, within_ms):
        j = bisect.bisect_left(self.keys, m)
        best = None
        for i in (j - 1, j):
            if 0 <= i < len(self.keys):
                d = abs(self.keys[i] - m)
                if d <= within_ms and (best is None or d < best[0]):
                    best = (d, self.keys[i])
        return self.fx[best[1]] if best else None

    def day_close(self, ts):
        d = datetime.fromtimestamp(int(ts), KST).replace(hour=23, minute=59, second=0, microsecond=0)
        return self.fx.get(int(d.timestamp()) * 1000)

    def rate_at(self, ts, row=None) -> float:
        if row is not None:
            try:
                ck, cu = row["cost_krw"], row["cost_usd"]
                if ck is not None and cu is not None and float(cu) > 0 and float(ck) > 0:
                    return float(ck) / float(cu)
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        m = (int(ts) * 1000 // 60_000) * 60_000
        j = bisect.bisect_right(self.keys, m) - 1
        if j >= 0 and m - self.keys[j] <= 3_600_000:
            return self.fx[self.keys[j]]
        dc = self.day_close(ts)
        if dc:
            return dc
        nr = self._near(m, 36 * 3_600_000) or self._near(m, 7 * 86_400_000)
        if nr:
            return nr
        if self.spot_default:
            _warn_default("그 시각 캐시·현재 환율 모두 없음")
        return self.spot

    def candle(self, sym, ts):
        s = str(sym or "").upper()
        if s not in self._csym:
            pts = {}
            pre = s + ":"
            for k, v in self._cand.items():
                if k.startswith(pre) and v:
                    try:
                        pts[int(k[len(pre):])] = float(v)
                    except ValueError:
                        pass
            self._csym[s] = (sorted(pts), pts)
        ks, pts = self._csym[s]
        if not ks:
            return None
        m = (int(ts) * 1000 // 60_000) * 60_000
        if m in pts:
            return pts[m]
        j = bisect.bisect_left(ks, m)
        best = None
        for i in (j - 1, j):
            if 0 <= i < len(ks):
                d = abs(ks[i] - m)
                if d <= 7 * 86_400_000 and (best is None or d < best[0]):
                    best = (d, ks[i])
        return pts[best[1]] if best else None


def fill_ts(order: dict):
    tr = (order or {}).get("trades") if isinstance(order, dict) else None
    if not isinstance(tr, list) or not tr:
        return None
    best = None
    for t in tr:
        if not isinstance(t, dict):
            continue
        v = t.get("created_at") or t.get("timestamp") or t.get("trade_time")
        ts = None
        try:
            if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                ts = float(v) / (1000.0 if float(v) > 1e11 else 1.0)
            elif v:
                ts = datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            ts = None
        if ts and (best is None or ts > best):
            best = ts
    return int(best) if best else None
