"""Telegram alert categories, presets, quiet hours and per-category switches."""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone

import common

KST = timezone(timedelta(hours=9))
PREFS_PATH = os.path.join(common.STATE_DIR, "ui_prefs.json")
SETTINGS_PATH = os.path.join(common.STATE_DIR, "settings.json")
STATS_PATH = os.path.join(common.STATE_DIR, "alert_stats.json")
HOLD_PATH = os.path.join(common.STATE_DIR, "alert_hold.json")
PREF_KEY = "alert_prefs"
FIRST_DAYS = 7
STATS_KEEP_DAYS = 9
HOLD_TEXT_MAX = 40

CATS = [
    {"key": "health", "n": 1, "grp": "base", "crit": True, "label": "봇 이상 경보",
     "desc": "수집기·원장·서버에 확실한 문제가 생기면 사건마다 알려요(발생 → 6시간마다 → 복구). 조용한 시간에도 바로 와요."},
    {"key": "digest", "n": 2, "grp": "base", "label": "09:00 일간 점검 요약",
     "desc": "아침 9시에 아직 열린 문제가 있을 때만 한 통으로 정리해요."},
    {"key": "price", "n": 3, "grp": "base", "label": "목표가·손절 도달",
     "desc": "매매일지에 저장한 목표가·손절선에 닿으면 알려요(1분 간격 감시 · 하루 한 번). 손절 도달은 조용한 시간에도 바로 와요."},
    {"key": "recon", "n": 4, "grp": "base", "first7": True, "label": "잔고 대사",
     "desc": "거래소·지갑 잔고 맞추기(대사) 결과와 온체인 잔고 불일치예요. 처음 연결해 동기화할 때 많이 와요."},
    {"key": "sync", "n": 5, "grp": "base", "first7": True, "label": "거래 분류·동기화",
     "desc": "새 스왑·전송·프로그램 수령·입금 확인·분류 바뀜·체결 보류·수집 경로 전환 소식이에요."},
    {"key": "backfill", "n": 6, "grp": "base", "first7": True, "label": "백필·재계산",
     "desc": "과거 데이터 가져오기 완료·재분류·새 체인 자동 추적 소식이에요."},
    {"key": "scam", "n": 7, "grp": "base", "label": "의심 토큰·분류 못 한 유입",
     "desc": "분류하지 못한 유입(검토 필요)을 알려요. 가짜 전송·주소 오염 같은 확실한 스캠은 이 설정과 상관없이 항상 걸러요."},
    {"key": "pnl", "n": 8, "grp": "new", "th": ["pnl_time"], "label": "일간 손익 요약",
     "desc": "하루 한 번 정한 시각에 오늘 실현 손익 · 총자산 변동(시세·입출금·환율) · 많이 움직인 코인 3개를 보내요."},
    {"key": "review", "n": 9, "grp": "new", "label": "AI 일간 복기 도착",
     "desc": "어제(또는 오늘) 일간 복기가 써지면 등급과 첫 두 줄을 보내요."},
    {"key": "weekly", "n": 10, "grp": "new", "label": "주간 복기 도착",
     "desc": "이번 주(또는 지난주) 주간 복기가 써지면 등급과 첫 두 줄을 보내요."},
    {"key": "move", "n": 11, "grp": "new", "th": ["move_1h", "move_24h", "move_min"], "label": "보유 코인 급등락",
     "desc": "들고 있는 코인이 1시간·24시간 안에 크게 움직이면 알려요 · 코인마다 6시간에 한 번 · 화면이 받는 시세로만 판정해요."},
    {"key": "bigflow", "n": 12, "grp": "new", "th": ["flow_min"], "label": "큰 입출금 감지",
     "desc": "외부로 보내거나 받은 금액(입출금 분해와 같은 기준)이 기준 이상이면 알려요."},
    {"key": "lprange", "n": 13, "grp": "new", "label": "LP 범위 이탈",
     "desc": "LP 포지션이 가격 범위를 벗어나거나 다시 들어오면 알려요."},
    {"key": "depeg", "n": 14, "grp": "new", "th": ["depeg_pct"], "label": "스테이블 디페그",
     "desc": "USDC·USD1·FDUSD 같은 스테이블이 1달러에서 기준 이상 벗어나면 알려요(해외 거래소 시세 · USDT 는 다른 스테이블과 비교해 판단)."},
    {"key": "liq", "n": 15, "grp": "new", "th": ["liq_pct"], "label": "선물 청산가 근접",
     "desc": "선물 포지션 현재가가 청산가에 기준 이내로 다가오면 알려요 · 청산가 정보가 있는 포지션만(없으면 조용히 건너뜀) · 조용한 시간에도 바로 와요."},
    {"key": "oa", "n": 16, "grp": "new", "label": "기타 자산·증권사",
     "desc": "증권사 동기화 실패와 주식·금 시세가 오래 멈춘 것, NFT 바닥가 조회가 무료 호출 제한에 걸려 늦어지는 것을 알려요(기타 자산 탭 기준)."},
    {"key": "other", "n": 17, "grp": "etc", "label": "기타",
     "desc": "위 분류에 없는 새 종류의 알림이에요."},
]
CAT_KEYS = [c["key"] for c in CATS]
CAT = {c["key"]: c for c in CATS}
FIRST7 = frozenset(c["key"] for c in CATS if c.get("first7"))
CRIT = frozenset(c["key"] for c in CATS if c.get("crit"))
MODES = ("on", "off", "auto")

TH = {
    "pnl_time": {"cat": "pnl", "kind": "time", "rec": "23:55", "label": "보내는 시각"},
    "move_1h": {"cat": "move", "kind": "pct", "rec": 10, "lo": 1, "hi": 100, "label": "1시간 변동"},
    "move_24h": {"cat": "move", "kind": "pct", "rec": 20, "lo": 1, "hi": 100, "label": "24시간 변동"},
    "move_min": {"cat": "move", "kind": "usd", "rec": 1000, "lo": 0, "hi": 1e9, "label": "보유 금액 이상만"},
    "flow_min": {"cat": "bigflow", "kind": "usd", "rec": 10000, "lo": 1, "hi": 1e10, "label": "금액 이상"},
    "depeg_pct": {"cat": "depeg", "kind": "pct", "rec": 1, "lo": 0.1, "hi": 20, "label": "1달러에서 벗어난 정도"},
    "liq_pct": {"cat": "liq", "kind": "pct", "rec": 10, "lo": 1, "hi": 50, "label": "청산가까지 남은 거리"},
}
REC_TH = {k: v["rec"] for k, v in TH.items()}
QUIET_REC = {"on": True, "from": "01:00", "to": "08:00"}

KIND_CAT = {
    "open": "health", "group": "health", "remind": "health", "resolve": "health", "flap": "health",
    "POISON": "health",
    "digest": "digest",
    "TARGET_HIT": "price", "STOP_HIT": "price",
    "EXF_RECON": "recon", "RECON": "recon", "EX_RECON": "recon", "BALANCE_MISMATCH": "recon",
    "PROGRAM_IN": "sync", "SWAP": "sync", "TRANSFER_OUT": "sync", "TRANSFER_OUT_EX": "sync", "DEPOSIT_MATCHED": "sync",
    "PROMOTE": "sync", "NEW_ASSET": "sync", "EX_FILL_SKIP": "sync", "EX_DEPOSIT_SKIP": "sync", "EX_WITHDRAW_SKIP": "sync",
    "ES_FALLBACK": "sync", "ES_FALLBACK_NONE": "sync", "ES_DAILY_LIMIT": "sync",
    "LP_ADD": "sync", "LP_REMOVE": "sync", "LP_ADJUST": "sync", "SALE_CAND": "sync",
    "BACKFILL_DONE": "backfill", "REDERIVE": "backfill", "CHAIN_AUTO": "backfill",
    "UNKNOWN": "scam",
    "PNL_DAILY": "pnl", "REVIEW_DAILY": "review", "REVIEW_WEEKLY": "weekly", "PRICE_MOVE": "move", "BIG_FLOW": "bigflow",
    "LP_RANGE": "lprange", "DEPEG": "depeg", "LIQ_NEAR": "liq", "OA_ALERT": "oa",
    "NFT_CG_SLOW": "oa",
}
TEST_KIND = "ALERT_TEST"


def cat_of(kind, hint=None) -> str:
    k = str(kind or "")
    c = KIND_CAT.get(k)
    if c:
        return c
    if k.startswith("LP_"):
        return "sync"
    if isinstance(hint, str) and hint in CAT and hint != "health":
        return hint
    return "other"


def _preset_cats(name: str) -> dict:
    if name == "rec":
        off = {"review", "weekly"}
        return {k: ("auto" if k in FIRST7 else "off" if k in off else "on") for k in CAT_KEYS}
    if name == "min":
        keep = {"health", "price", "scam", "liq"}
        return {k: ("on" if k in keep else "off") for k in CAT_KEYS}
    if name == "all":
        return {k: "on" for k in CAT_KEYS}
    raise KeyError(name)


PRESETS = {
    "rec": {"label": "추천", "desc": "처음 7일은 동기화·대사·백필까지, 그 뒤엔 꼭 필요한 것만 · 밤 1시~8시는 모아서"},
    "min": {"label": "최소", "desc": "봇 이상·목표가·의심 토큰·청산 근접만 · 밤 1시~8시는 모아서"},
    "all": {"label": "전부", "desc": "모든 알림을 추천 기준값으로 · 조용한 시간 없음"},
}
PRESET_ORDER = ("rec", "min", "all")


def preset_doc(name: str) -> dict:
    return {"v": 1, "cats": _preset_cats(name), "th": dict(REC_TH),
            "quiet": dict(QUIET_REC, on=(name != "all"))}


def default_doc() -> dict:
    return preset_doc("rec")


_HM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _num_ok(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (OverflowError, ValueError):
        return False


TS_MAX = 1e11


def _th_clean(key, v):
    spec = TH[key]
    if spec["kind"] == "time":
        return v if isinstance(v, str) and _HM.match(v) else None
    if not _num_ok(v):
        return None
    v = float(v)
    if not (spec["lo"] <= v <= spec["hi"]):
        return None
    return int(v) if v == int(v) else round(v, 4)


def normalize(raw) -> dict:
    d = default_doc()
    if not isinstance(raw, dict):
        return d
    cats = raw.get("cats") if isinstance(raw.get("cats"), dict) else {}
    for k in CAT_KEYS:
        try:
            m = cats.get(k)
            if k not in CRIT and isinstance(m, str) and m in MODES and (m != "auto" or k in FIRST7):
                d["cats"][k] = m
        except Exception:
            pass
    th = raw.get("th") if isinstance(raw.get("th"), dict) else {}
    for k in TH:
        try:
            if k in th:
                v = _th_clean(k, th[k])
                if v is not None:
                    d["th"][k] = v
        except Exception:
            pass
    q = raw.get("quiet") if isinstance(raw.get("quiet"), dict) else {}
    if isinstance(q.get("on"), bool):
        d["quiet"]["on"] = q["on"]
    for k in ("from", "to"):
        if isinstance(q.get(k), str) and _HM.match(q[k]):
            d["quiet"][k] = q[k]
    if d["quiet"]["from"] == d["quiet"]["to"]:
        d["quiet"].update({"from": QUIET_REC["from"], "to": QUIET_REC["to"]})
    u = raw.get("updated")
    if _num_ok(u) and 0 <= u < TS_MAX:
        d["updated"] = int(u)
    return d


def apply_post(cur_raw, body):
    if not isinstance(body, dict) or not body:
        return None, "본문 필요"
    allowed = {"preset", "cats", "th", "quiet"}
    bad = [k for k in body if k not in allowed]
    if bad:
        return None, "모르는 항목: " + ", ".join(sorted(str(x) for x in bad))[:120]
    if "preset" in body:
        if len(body) != 1:
            return None, "preset 은 단독으로만 보낼 수 있어요"
        if body["preset"] not in PRESETS:
            return None, "preset 은 rec|min|all"
        d = preset_doc(body["preset"])
        d["updated"] = int(time.time())
        return d, None
    d = normalize(cur_raw)
    if "cats" in body:
        c = body["cats"]
        if not isinstance(c, dict) or not c:
            return None, "cats 는 {카테고리: on|off|auto}"
        for k, m in c.items():
            if k not in CAT:
                return None, f"모르는 카테고리: {str(k)[:40]}"
            if not isinstance(m, str) or m not in MODES:
                return None, f"{k}: on|off|auto 중 하나"
            if k in CRIT and m != "on":
                return None, "봇 이상 경보는 끌 수 없어요 — 봇이 멈춘 걸 알려야 해서 늘 켜 둬요"
            if m == "auto" and k not in FIRST7:
                return None, f"{k}: '연결 후 7일만'은 잔고 대사·거래 분류·백필에만 있어요"
            d["cats"][k] = m
    if "th" in body:
        t = body["th"]
        if not isinstance(t, dict) or not t:
            return None, "th 는 {기준값 키: 값}"
        for k, v in t.items():
            if k not in TH:
                return None, f"모르는 기준값: {str(k)[:40]}"
            cv = _th_clean(k, v)
            if cv is None:
                spec = TH[k]
                return None, (f"{k}: HH:MM 형식" if spec["kind"] == "time"
                              else f"{k}: {spec['lo']:g}~{spec['hi']:g} 사이 숫자")
            d["th"][k] = cv
    if "quiet" in body:
        q = body["quiet"]
        if not isinstance(q, dict) or not q or any(k not in ("on", "from", "to") for k in q):
            return None, "quiet 는 {on: true|false, from: HH:MM, to: HH:MM}"
        if "on" in q:
            if not isinstance(q["on"], bool):
                return None, "quiet.on 은 true|false"
            d["quiet"]["on"] = q["on"]
        for k in ("from", "to"):
            if k in q:
                if not isinstance(q[k], str) or not _HM.match(q[k]):
                    return None, f"quiet.{k}: HH:MM 형식"
                d["quiet"][k] = q[k]
        if d["quiet"]["on"] and d["quiet"]["from"] == d["quiet"]["to"]:
            return None, "조용한 시간 시작과 끝이 같아요"
    d["updated"] = int(time.time())
    return d, None


def match_preset(doc) -> str:
    d = normalize(doc)
    for name in PRESET_ORDER:
        p = preset_doc(name)
        if d["cats"] != p["cats"]:
            continue
        if d["quiet"]["on"] != p["quiet"]["on"]:
            continue
        if p["quiet"]["on"] and (d["quiet"]["from"], d["quiet"]["to"]) != (p["quiet"]["from"], p["quiet"]["to"]):
            continue
        if any(d["th"][k] != p["th"][k] for k, spec in TH.items() if p["cats"].get(spec["cat"]) != "off"):
            continue
        return name
    return "custom"


def _read(path, default):
    try:
        return common.read_json(path, default)
    except (Exception, SystemExit):
        return default


def load(prefs: dict | None = None) -> dict:
    try:
        if prefs is None:
            prefs = _read(PREFS_PATH, {}) or {}
        return normalize(prefs.get(PREF_KEY) if isinstance(prefs, dict) else None)
    except Exception:
        return default_doc()


def connect_ts(stats: dict | None = None):
    vals = []
    try:
        st = _read(SETTINGS_PATH, {}) or {}
        tg = st.get("telegram") if isinstance(st, dict) else None
        v = tg.get("connected_at") if isinstance(tg, dict) else None
        if _num_ok(v) and 0 < v < TS_MAX:
            vals.append(float(v))
    except Exception:
        pass
    try:
        s = stats if stats is not None else (_read(STATS_PATH, {}) or {})
        v = s.get("first_seen") if isinstance(s, dict) else None
        if _num_ok(v) and 0 < v < TS_MAX:
            vals.append(float(v))
    except Exception:
        pass
    return min(vals) if vals else None


def first_week(conn, now=None) -> dict:
    now = time.time() if now is None else now
    if conn is None:
        return {"connectedAt": None, "until": None, "active": True}
    until = conn + FIRST_DAYS * 86400
    return {"connectedAt": int(conn), "until": int(until), "active": now < until}


def effective(doc, key, now=None, conn=None) -> bool:
    if key in CRIT:
        return True
    m = doc["cats"].get(key, "on")
    if m == "on":
        return True
    if m == "off":
        return False
    return first_week(conn, now)["active"]


def _mins(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def in_quiet(doc, now=None) -> bool:
    q = doc.get("quiet") or {}
    if not q.get("on"):
        return False
    t = datetime.fromtimestamp(time.time() if now is None else now, KST)
    cur, a, b = t.hour * 60 + t.minute, _mins(q["from"]), _mins(q["to"])
    if a == b:
        return False
    return a <= cur < b if a < b else (cur >= a or cur < b)


def quiet_until(doc, now=None):
    now = time.time() if now is None else now
    if not in_quiet(doc, now):
        return None
    b = _mins(doc["quiet"]["to"])
    t = datetime.fromtimestamp(now, KST)
    end = t.replace(hour=b // 60, minute=b % 60, second=0, microsecond=0)
    if end <= t:
        end += timedelta(days=1)
    return end.timestamp()


URGENT_KINDS = frozenset({"LIQ_NEAR", "STOP_HIT"})


def decide(doc, key, now=None, conn=None, kind=None) -> str:
    if not effective(doc, key, now, conn):
        return "skip"
    if key not in CRIT and kind not in URGENT_KINDS and in_quiet(doc, now):
        return "hold"
    return "send"


def day_key(now=None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, KST).strftime("%Y-%m-%d")


def counts7(stats=None, now=None) -> dict:
    now = time.time() if now is None else now
    s = stats if stats is not None else (_read(STATS_PATH, {}) or {})
    days = (s or {}).get("days") if isinstance(s, dict) else None
    keep = {day_key(now - i * 86400) for i in range(7)}
    out = {k: {"sent": 0, "skip": 0, "held": 0} for k in CAT_KEYS}
    for dk, row in (days.items() if isinstance(days, dict) else ()):
        if dk not in keep or not isinstance(row, dict):
            continue
        for k, c in row.items():
            if k in out and isinstance(c, dict):
                for f in ("sent", "skip", "held"):
                    v = c.get(f)
                    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                        out[k][f] += v
    return out


def view(prefs=None, now=None, tg_connected=None, extra=None) -> dict:
    now = time.time() if now is None else now
    doc = load(prefs)
    stats = _read(STATS_PATH, {}) or {}
    conn = connect_ts(stats)
    fw = first_week(conn, now)
    eff = {k: effective(doc, k, now, conn) for k in CAT_KEYS}
    hold = _read(HOLD_PATH, {}) or {}
    hn = hold.get("n") if isinstance(hold, dict) else None
    hn = sum(v for v in (hn.values() if isinstance(hn, dict) else ()) if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 10 ** 9)
    out = {"ok": True, "v": 1, "prefs": {k: doc[k] for k in ("cats", "th", "quiet")}, "preset": match_preset(doc),
           "presets": [{"key": k, **PRESETS[k], "doc": {kk: vv for kk, vv in preset_doc(k).items() if kk != "v"}} for k in PRESET_ORDER],
           "cats": [{k: c[k] for k in ("key", "n", "grp", "label", "desc") if k in c} | {"first7": bool(c.get("first7")), "crit": bool(c.get("crit")),
                                                                                       "th": list(c.get("th") or [])} for c in CATS],
           "th": {k: {f: v for f, v in spec.items()} for k, spec in TH.items()},
           "effective": eff, "firstWeek": fw, "quietNow": in_quiet(doc, now), "held": hn,
           "counts7": counts7(stats, now), "tg": {"connected": bool(tg_connected)} if tg_connected is not None else None,
           "updated": doc.get("updated")}
    if extra:
        out.update(extra)
    return out


def json_line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
