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
            import common
            ex = (common.seed_json("ticker_aliases.json", {}, base_dir=os.path.dirname(os.path.dirname(_SEED))) or {}).get("exchange") or {}
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

    RATE_SRC_KO = {"leg": "체결 원화(그 체결)", "minute": "그 분(직전 60분)", "close": "그날 마감", "near36h": "가까운 시각(±36시간)",
                   "near7d": "가까운 시각(±7일)", "spot": "현재 환율(그 시각 기록 없음)", "default": "기본값(환율 기록 없음)"}

    def rate_src(self, ts, row=None):
        if row is not None:
            try:
                ck, cu = row["cost_krw"], row["cost_usd"]
                if ck is not None and cu is not None and float(cu) > 0 and float(ck) > 0:
                    return float(ck) / float(cu), "leg"
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        m = (int(ts) * 1000 // 60_000) * 60_000
        j = bisect.bisect_right(self.keys, m) - 1
        if j >= 0 and m - self.keys[j] <= 3_600_000:
            return self.fx[self.keys[j]], "minute"
        dc = self.day_close(ts)
        if dc:
            return dc, "close"
        nr = self._near(m, 36 * 3_600_000)
        if nr:
            return nr, "near36h"
        nr = self._near(m, 7 * 86_400_000)
        if nr:
            return nr, "near7d"
        if self.spot_default:
            _warn_default("그 시각 캐시·현재 환율 모두 없음")
            return self.spot, "default"
        return self.spot, "spot"

    def rate_at(self, ts, row=None) -> float:
        return self.rate_src(ts, row)[0]

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
                import common
                ts = common.iso_epoch(v)
        except (TypeError, ValueError):
            ts = None
        if ts and (best is None or ts > best):
            best = ts
    return int(best) if best else None


UPBIT_TERMINAL = ("done", "cancel")


def _dec(v):
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def trades_fill_merge(stored: dict, resp: dict):
    if not isinstance(stored, dict) or not isinstance(resp, dict):
        return None, "형식"
    if fill_ts(stored) is not None:
        return None, "이미 체결 목록 있음"
    for k in ("uuid", "market", "side", "state"):
        if str(stored.get(k) or "").lower() != str(resp.get(k) or "").lower():
            return None, f"{k} 다름"
    if str(stored.get("state") or "").lower() not in UPBIT_TERMINAL:
        return None, "종결 아님"
    tr = resp.get("trades")
    if not isinstance(tr, list) or not tr or not all(isinstance(t, dict) for t in tr):
        return None, "체결 목록 없음"
    from decimal import Decimal
    sv, sf = Decimal(0), Decimal(0)
    for t in tr:
        v9, f9 = _dec(t.get("volume")), _dec(t.get("funds"))
        if v9 is None or f9 is None or v9 < 0 or f9 < 0 or fill_ts({"trades": [t]}) is None:
            return None, "체결 행 읽기 실패"
        sv += v9
        sf += f9
    ev = _dec(stored.get("executed_volume"))
    if ev is None or ev <= 0 or sv != ev:
        return None, "체결 수량 합 다름"
    if stored.get("executed_funds") not in (None, ""):
        ef = _dec(stored.get("executed_funds"))
        if ef is None or sf != ef:
            return None, "체결 금액 합 다름"
    if stored.get("trades_count") is not None:
        try:
            if int(stored["trades_count"]) != len(tr):
                return None, "체결 수 다름"
        except (TypeError, ValueError):
            return None, "체결 수 읽기 실패"
    for k in ("executed_volume", "paid_fee", "executed_funds"):
        if resp.get(k) not in (None, "") and stored.get(k) not in (None, "") and _dec(resp.get(k)) != _dec(stored.get(k)):
            return None, f"{k} 다름"
    out = dict(stored)
    out["trades"] = tr
    return out, None
