from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone

PLANS = ("demo", "pro")
ROOT = {"demo": "https://api.coingecko.com/api/v3", "pro": "https://pro-api.coingecko.com/api/v3"}
HDR = {"demo": "x-cg-demo-api-key", "pro": "x-cg-pro-api-key"}
WRONG_ROOT_CODES = frozenset((10010, 10011))
ENV_KEY = "TJ_COINGECKO_KEY"
SETTINGS_KEY = "coingecko"
SHARE = 0.8
SHARES = (10, 25, 50, 80)
DEFAULT_SHARE = 10
SHARE_KEY = "coingecko_share"
DEMO_PUBLISHED = {"rpm": 30, "credit": 10000}
DEMO_BUDGET = (24, 260)
INFO_EVERY = 6 * 3600
INFO_RETRY = 3600
INFO_PER_DAY = 4
INFO_MAX_AGE = 24 * 3600
PLAN_KO = {"demo": "데모", "pro": "프로"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()\-]{0,29}$")


def endpoint(plan) -> tuple:
    p = plan if plan in PLANS else "demo"
    return ROOT[p], HDR[p]


def other(plan) -> str:
    return "demo" if plan == "pro" else "pro"


def kfp(key) -> str:
    return hashlib.sha256(str(key or "").encode()).hexdigest()[:8]


def _as_obj(body):
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        s = body.strip()
        if s[:1] in ("{", "["):
            try:
                return json.loads(s)
            except ValueError:
                return s
        return s
    return body


def error_of(body) -> tuple:
    b = _as_obj(body)
    code, msg = None, ""

    def _code(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit() and len(v.strip()) <= 9:
            return int(v.strip())
        return None
    if isinstance(b, dict):
        for d in (b.get("status") if isinstance(b.get("status"), dict) else None, b,
                  b.get("error") if isinstance(b.get("error"), dict) else None):
            if not isinstance(d, dict):
                continue
            if code is None:
                code = _code(d.get("error_code")) if "error_code" in d else _code(d.get("code"))
            if not msg:
                for k in ("error_message", "message", "error"):
                    if isinstance(d.get(k), str) and d.get(k).strip():
                        msg = d[k].strip()
                        break
    elif isinstance(b, str):
        msg = b
    return code, msg[:300]


def wrong_root(body) -> bool:
    try:
        code, msg = error_of(body)
    except Exception:
        return False
    if code in WRONG_ROOT_CODES:
        return True
    m = msg.lower()
    if "root url" in m and "coingecko.com" in m:
        return True
    return "pro-api.coingecko.com" in m and ("pro api key" in m or "demo api key" in m)


def hinted_plan(body):
    _c, msg = error_of(body)
    m = msg.lower()
    if "pro api key" in m:
        return "pro"
    if "demo api key" in m:
        return "demo"
    return None


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", "")
        if not re.fullmatch(r"\d{1,13}(\.\d+)?", v):
            return None
    if not isinstance(v, (int, float, str)):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0 or x >= 1e13:
        return None
    return x


def parse_key_info(d):
    if isinstance(d, dict) and isinstance(d.get("data"), dict) and "monthly_call_credit" not in d:
        d = d["data"]
    if not isinstance(d, dict):
        return None
    rpm = _num(d.get("rate_limit_request_per_minute"))
    credit = _num(d.get("monthly_call_credit"))
    krpm = _num(d.get("api_key_rate_limit_request_per_minute"))
    kcred = _num(d.get("api_key_monthly_call_credit"))
    if krpm and krpm >= 1 and (not rpm or krpm < rpm):
        rpm = krpm
    if kcred and kcred >= 1 and (not credit or kcred < credit):
        credit = kcred
    if not rpm or rpm < 1 or not credit or credit < 1:
        return None
    used = _num(d.get("current_total_monthly_calls"))
    rem = _num(d.get("current_remaining_monthly_calls"))
    cands = [x for x in (used, (credit - rem) if rem is not None else None) if x is not None]
    u = max(0.0, max(cands)) if cands else None
    name = d.get("plan")
    name = name.strip() if isinstance(name, str) else ""
    if not _NAME_RE.match(name):
        name = ""
    return {"name": name, "rpm": int(rpm), "credit": int(credit), "used": int(u) if u is not None else None,
            "remaining": int(rem) if rem is not None else None}


def days_left_in_month(t: float) -> int:
    d = datetime.fromtimestamp(float(t), timezone.utc)
    nm = datetime(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1, tzinfo=timezone.utc)
    return max(1, int(math.ceil((nm.timestamp() - float(t)) / 86400.0)))


def _ym(t: float) -> tuple:
    d = datetime.fromtimestamp(float(t), timezone.utc)
    return d.year, d.month


def info_state(rec, now=None) -> str:
    now = time.time() if now is None else float(now)
    if not isinstance(rec, dict) or rec.get("plan") != "pro":
        return "none"
    info = rec.get("info")
    ia, ta = _num(rec.get("info_at")), _num(rec.get("info_try_at"))
    if not (isinstance(info, dict) and _num(info.get("rpm")) and _num(info.get("credit")) and ia):
        return "failed" if ta else "none"
    if ta and ta > ia:
        return "failed"
    if ia > now + 3600 or now - ia > INFO_MAX_AGE:
        return "stale"
    if _ym(ia) != _ym(now):
        return "month"
    return "ok"


def valid_share(v) -> bool:
    return type(v) is int and v in SHARES


def norm_share(v) -> int:
    return v if valid_share(v) else DEFAULT_SHARE


def budget(rec, now=None, share=None, ours=None) -> dict:
    now = time.time() if now is None else float(now)
    info = (rec or {}).get("info") if isinstance(rec, dict) else None
    if isinstance(rec, dict) and rec.get("plan") == "pro":
        ist = info_state(rec, now)
        if ist == "ok":
            pct = norm_share(share)
            s = pct / 100.0
            rpm, credit = int(info["rpm"]), int(info["credit"])
            per_min = max(1, int(rpm * s))
            month = int(credit * s)
            left = float(month - max(0, int(_num(ours) or 0)))
            used = _num(info.get("used"))
            if used is not None:
                left = min(left, (credit * SHARE - used) * s / SHARE)
            t0 = _num(rec.get("info_at")) or now
            per_day = int(min(max(0.0, left) / days_left_in_month(min(t0, now)), month / 30.0))
            return {"basis": "pro", "per_min": per_min, "per_day": max(0, per_day), "share": pct, "month": month}
        return {"basis": "pro_pending", "per_min": DEMO_BUDGET[0], "per_day": DEMO_BUDGET[1]}
    return {"basis": "demo", "per_min": DEMO_BUDGET[0], "per_day": DEMO_BUDGET[1]}


def man(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 10000:
        v = n / 10000.0
        s = f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}"
        return s + "만"
    return f"{n:,}"


def approx(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1000:
        p = 10 ** (len(str(n)) - 2)
        n = n // p * p
    return man(n)


_INFO_WHY = {"failed": "(마지막 확인 실패) ", "stale": "(마지막 확인이 24시간 넘음) ", "month": "(새 달 — 이번 달 사용량 확인 중) "}


def plan_text(rec, now=None, share=None, ours=None) -> str:
    plan = rec.get("plan") if isinstance(rec, dict) else None
    if plan == "pro":
        info = rec.get("info") if isinstance(rec.get("info"), dict) else None
        ist = info_state(rec, now)
        if ist == "ok":
            nm = f"프로({info['name']})" if info.get("name") else "프로"
            b = budget(rec, now, share, ours)
            return (f"{nm} · 분당 {man(info['rpm'])} · 월 {man(info['credit'])} — {b['share']}% 사용 → "
                    f"분당 {man(b['per_min'])} · 하루 ~{approx(b['per_day'])}")
        return (f"프로 · 한도 확인 전 {_INFO_WHY.get(ist, '')}— 확인될 때까지 데모 수준(분당 {DEMO_BUDGET[0]} · 하루 {DEMO_BUDGET[1]})으로만 사용")
    if plan == "demo":
        return f"데모(무료) · 분당 {DEMO_PUBLISHED['rpm']} · 월 {man(DEMO_PUBLISHED['credit'])} — 80% 사용"
    return "등급 확인 전 — 처음 조회할 때 데모·프로를 자동으로 판별해요"


def budget_text(rec, now=None, share=None, ours=None) -> str:
    b = budget(rec, now, share, ours)
    s = f"지금 쓰는 몫: 분당 {man(b['per_min'])} · 하루 {man(b['per_day'])}"
    if b["basis"] == "pro":
        info = rec.get("info") or {}
        parts = [f"이번 달 우리 몫 {man(b['month'])}"]
        if ours:
            parts.append(f"우리 사용 {man(ours)}")
        if info.get("used") is not None:
            parts.append(f"계정 전체 사용 {man(info['used'])}(다른 곳 포함)")
        s += " (" + " · ".join(parts) + " — 남은 몫을 남은 날에 고르게)"
    return s


def status(rec, now=None, share=None, ours=None) -> dict:
    pct = norm_share(share)
    if not isinstance(rec, dict) or rec.get("plan") not in PLANS:
        return {"plan": None, "text": plan_text(None), "budgetText": "", "at": None, "infoAt": None, "how": None,
                "share": pct, "shares": list(SHARES)}
    return {"plan": rec["plan"], "text": plan_text(rec, now, pct, ours), "budgetText": budget_text(rec, now, pct, ours),
            "at": rec.get("at"), "infoAt": rec.get("info_at"), "how": rec.get("how"), "share": pct, "shares": list(SHARES)}


def probe(key: str, http, base=None, prefer=None, want_info: bool = True, reserve=None) -> dict:
    base = base or (lambda p: ROOT[p])
    order = [prefer, other(prefer)] if prefer in PLANS else ["demo", "pro"]
    tries, calls = [], 0
    for i, plan in enumerate(order):
        root, hdr = base(plan), HDR[plan]
        why = reserve() if reserve else ""
        if why:
            return {"ok": False, "rejected": False, "budget": why, "detail": "", "code": 0, "calls": calls,
                    "wrong_root": any(t["wrong_root"] for t in tries)}
        try:
            code, d = http(root + "/ping", {hdr: key})
        except Exception:
            code, d = 0, None
        calls += 1
        if code == 200 and isinstance(d, dict) and "gecko_says" in d and not wrong_root(d):
            out = {"ok": True, "plan": plan, "calls": calls}
            if plan == "pro" and want_info and reserve and reserve():
                out["info_skipped"] = "budget"
            elif plan == "pro" and want_info:
                try:
                    c2, d2 = http(root + "/key", {hdr: key})
                except Exception:
                    c2, d2 = 0, None
                out["calls"] = calls + 1
                info = parse_key_info(d2) if c2 == 200 else None
                out["info"] = info
                out["info_ok"] = bool(info)
            return out
        wr = wrong_root(d)
        _c, msg = error_of(d)
        tries.append({"plan": plan, "code": code if isinstance(code, int) else 0, "wrong_root": wr, "msg": msg})
        if i == 0 and not (wr or code in (400, 401, 403)):
            break
    rejected = (len(tries) == 2 and all(t["code"] in (400, 401, 403) or t["wrong_root"] for t in tries)
                and not all(t["wrong_root"] for t in tries))
    pick = next((t for t in tries if t["msg"] and not t["wrong_root"]), None) or next((t for t in tries if t["msg"]), None) or tries[0]
    detail = pick["msg"][:160] if pick.get("msg") else (f"HTTP {pick['code']}" if pick["code"] else "연결 실패")
    return {"ok": False, "rejected": rejected, "detail": detail, "code": tries[0]["code"], "calls": calls,
            "wrong_root": any(t["wrong_root"] for t in tries)}


class Store:

    def load(self, key):
        if not key:
            return None
        import settings_store as ss
        rec = ss.read_settings().get(SETTINGS_KEY)
        if not isinstance(rec, dict) or rec.get("fp") != kfp(key) or rec.get("plan") not in PLANS:
            return None
        return dict(rec)

    def save(self, key, **fields) -> dict:
        import settings_store as ss
        with ss.LOCK:
            cur = self.load(key) or {}
            if "plan" in fields and fields["plan"] != cur.get("plan"):
                cur = {k: v for k, v in cur.items() if k not in ("info", "info_at", "info_try_at")}
            new = dict(cur, **{k: v for k, v in fields.items()})
            if new.get("plan") not in PLANS:
                return cur
            new["fp"] = kfp(key)
            ss.update_settings(**{SETTINGS_KEY: new})
            return new

    def clear(self):
        import settings_store as ss
        with ss.LOCK:
            if ss.read_settings().get(SETTINGS_KEY) is not None:
                ss.update_settings(**{SETTINGS_KEY: None})

    def share(self) -> int:
        import settings_store as ss
        try:
            return norm_share(ss.read_settings().get(SHARE_KEY))
        except Exception:
            return DEFAULT_SHARE

    def set_share(self, v) -> int:
        if not valid_share(v):
            raise ValueError("사용 비율은 10·25·50·80(%) 중 하나만 됩니다")
        import settings_store as ss
        ss.update_settings(**{SHARE_KEY: v})
        return v


class MemStore(Store):

    def __init__(self, share=DEFAULT_SHARE):
        self.rec = None
        self.share_v = share

    def share(self) -> int:
        return norm_share(self.share_v)

    def set_share(self, v) -> int:
        if not valid_share(v):
            raise ValueError("사용 비율은 10·25·50·80(%) 중 하나만 됩니다")
        self.share_v = v
        return v

    def load(self, key):
        r = self.rec
        if not key or not isinstance(r, dict) or r.get("fp") != kfp(key) or r.get("plan") not in PLANS:
            return None
        return dict(r)

    def save(self, key, **fields):
        cur = self.load(key) or {}
        if "plan" in fields and fields["plan"] != cur.get("plan"):
            cur = {k: v for k, v in cur.items() if k not in ("info", "info_at", "info_try_at")}
        new = dict(cur, **fields)
        if new.get("plan") not in PLANS:
            return cur
        new["fp"] = kfp(key)
        self.rec = new
        return new

    def clear(self):
        self.rec = None
