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
    {"key": "health", "n": 1, "tier": "now", "crit": True, "label": "봇이 멈춤(몇 분 이상)",
     "desc": "프로그램·장부 계산·서버·디스크·거래소·시세 수집이 몇 분 넘게 멈추거나 한 수집기의 체인이 모두 함께 멈추면 알려요 — 생겼을 때 한 번, 풀렸을 때 한 번(더 나빠지면 한 번 더). "
             "봇이 멈춘 걸 알려야 해서 끌 수 없어요. 체인 하나만 늦는 건 아래 '체인 수집 지연'이에요."},
    {"key": "stall", "n": 19, "tier": "now", "label": "체인 수집 지연",
     "desc": "체인 하나의 수집이 늦거나 멈춘 것(대부분 저절로 풀림) — 기본은 상태 패널에만. 켜면 생겼을 때·풀렸을 때 텔레그램으로도 알려요(한 시간 넘게 이어지면 한 번 더). "
             "한 수집기의 체인이 모두 함께 멈추면 이 칸과 상관없이 '봇이 멈춤'으로 와요."},
    {"key": "balmis", "n": 20, "tier": "now", "label": "잔고 불일치(하루 넘게)",
     "desc": "장부와 실제 잔고가 다른 곳이 — 수집·재계산처럼 진행 중인 일이 다 끝난 뒤에도 — 24시간 넘게 그대로면 한 번 알려요(어느 지갑·코인 · 장부와 실제 · 짐작되는 까닭 · 할 일). "
             "진행 중인 동안의 차이는 상태 패널·잔고 맞추기에만 보여요."},
    {"key": "price", "n": 3, "tier": "now", "label": "목표가·손절 도달",
     "desc": "매매일지에 걸어 둔 목표가·손절선에 닿으면 바로 알려요(1분 간격 감시 · 코인마다 하루 한 번)."},
    {"key": "bigflow", "n": 12, "tier": "now", "th": ["flow_min"], "label": "내가 안 한 큰 출금",
     "desc": "모르는 주소로 기준 이상 나가면 바로 알려요(밤에도) — 내 지갑·내 거래소·브릿지로 옮긴 건 빼고, 장부를 맞춘 기록(거래소 잔고 맞춤·차입 반영)도 빼요. "
             "내가 옮긴 돈이 제때(일반 30분·브릿지 2시간) 안 들어오거나 수수료보다 많이 줄어 들어와도 소리로 알려요. 큰 입금은 급하지 않아서 하루 요약에 넣어요."},
    {"key": "arrive", "n": 18, "tier": "now", "label": "내 이체 도착 확인",
     "desc": "내 지갑·내 거래소·브릿지로 옮긴 큰 금액(큰 출금 기준 이상)이 도착하면 소리 없이 한 통 — 걸린 시간·받은 수량·수수료로 줄어든 양. 보낼 때는 알리지 않아요."},
    {"key": "depeg", "n": 14, "tier": "now", "th": ["depeg_pct"], "label": "스테이블 가격 이탈",
     "desc": "USDC·USDT 같은 스테이블이 1달러에서 기준 이상 벗어나면 알려요(해외 거래소 시세). 벗어날 때 한 번, 돌아올 때 한 번."},
    {"key": "liq", "n": 15, "tier": "now", "th": ["liq_pct"], "label": "청산 근접(선물·대출·마진)",
     "desc": "열린 선물 포지션은 몇 초마다(가까우면 2초) 시세를 보고 청산가에 기준 이내로 다가오면 바로 알려요 — 처음 한 번, 거리가 절반으로 줄면 한 번 더, "
             "벗어나면 한 번(소리 없이). 담보대출 LTV·마진 레벨도 마진콜 90% → 마진콜 → 청산 직전 단계로 알려요. 끄면 빠른 감시도 같이 멈춰요."},
    {"key": "move", "n": 11, "tier": "now", "th": ["move_1h", "move_24h", "move_weight", "move_min"], "label": "보유 코인 급등락",
     "desc": "총자산에서 비중이 큰 코인이 1시간·24시간 안에 크게 움직이면 알려요 — 코인마다 하루 한 번 · 조용한 시간(밤)엔 모았다가. 기본은 꺼져 있어요."},
    {"key": "pnl", "n": 8, "tier": "daily", "th": ["pnl_time"], "label": "오늘 손익",
     "desc": "그날 실현 손익과 총자산이 왜 움직였는지(시세·입출금·환율), 많이 움직인 코인 3개를 요약에 넣어요. 총자산 30일 곡선 그림도 같이."},
    {"key": "recon", "n": 4, "tier": "daily", "label": "잔고 맞추기 결과",
     "desc": "거래소·지갑 잔고를 기록과 맞춘 결과예요. 기록과 실제 잔고가 크게 다른 곳이 있으면 요약 맨 위에 '할 일'로 올려요."},
    {"key": "scam", "n": 7, "tier": "daily", "label": "처음 보는 토큰",
     "desc": "어디서 왔는지 모르는 입금·토큰 수를 요약에 넣어요. 가짜 전송·주소 오염 같은 확실한 스캠은 늘 걸러서 보내지 않아요."},
    {"key": "lprange", "n": 13, "tier": "daily", "label": "LP 범위 이탈",
     "desc": "LP 포지션이 가격 범위를 벗어났거나 다시 들어온 것을 요약에 넣어요."},
    {"key": "review", "n": 9, "tier": "daily", "label": "AI 복기 도착",
     "desc": "일간 복기가 써지면 등급과 첫 줄을 요약에 넣어요."},
    {"key": "weekly", "n": 10, "tier": "daily", "label": "AI 주간 복기 도착",
     "desc": "주간 복기가 써지면 등급과 첫 줄을 요약에 넣어요."},
    {"key": "oa", "n": 16, "tier": "daily", "label": "기타 자산·증권사",
     "desc": "증권사 연결 실패, 주식·금 시세가 오래 멈춘 것, NFT 바닥가가 늦어지는 것을 요약에 넣어요."},
    {"key": "digest", "n": 2, "tier": "daily", "th": ["digest_time", "digest_chart", "digest_axis"], "label": "안 풀린 봇 문제",
     "desc": "요약을 보낼 때 아직 안 풀린 봇 문제가 있으면 한 줄로 넣어요(이미 '봇이 멈췄을 때'로 받은 건 제목만)."},
    {"key": "other", "n": 17, "tier": "daily", "label": "그 밖의 소식",
     "desc": "위 분류에 없는 새 종류의 소식이에요 — 놓치지 않게 요약에 건수와 최근 것만."},
    {"key": "sync", "n": 5, "tier": "web", "label": "거래 분류·동기화",
     "desc": "새 스왑·전송 분류, 분류 바뀜, 수집 경로 전환 같은 봇 내부 소식이에요. 할 일이 없어서 텔레그램으로 보내지 않고 상태 패널에만 남겨요."},
    {"key": "backfill", "n": 6, "tier": "web", "label": "과거 기록 가져오기·다시 계산",
     "desc": "과거 데이터 가져오기·다시 계산·새 체인 자동 추적 소식이에요. 텔레그램으로는 처음 다 가져왔을 때 한 통만 보내요."},
]
for _c in CATS:
    _c["grp"] = _c["tier"]
CAT_KEYS = [c["key"] for c in CATS]
CAT = {c["key"]: c for c in CATS}
TIER = {c["key"]: c["tier"] for c in CATS}
TIERS = ("now", "daily", "web")
TIER_LABEL = {"now": "즉시", "daily": "하루 요약", "web": "시스템"}
TIER_SUB = {"now": "지금 폰을 보고 해야 할 일 · 소리", "daily": "소리 없이 한 통",
            "web": "분류·동기화·과거 기록 가져오기·재계산 — 텔레그램 안 보내고 상태 패널에만"}
FIRST7 = frozenset()
CRIT = frozenset(c["key"] for c in CATS if c.get("crit"))
MODES = ("on", "off")
LEGACY_MODES = ("on", "off", "auto")
SCHEMA = 2


def tier(key) -> str:
    return TIER.get(key, "daily")


TH = {
    "pnl_time": {"cat": "pnl", "kind": "time", "rec": "23:55", "label": "손익 기준 시각"},
    "digest_time": {"cat": "digest", "kind": "time", "rec": "09:00", "label": "하루 요약 보내는 시각"},
    "digest_chart": {"cat": "digest", "kind": "bool", "rec": True, "label": "총자산 곡선 그림 붙이기"},
    "digest_axis": {"cat": "digest", "kind": "bool", "rec": True, "label": "그림에 금액 눈금"},
    "move_1h": {"cat": "move", "kind": "pct", "rec": 10, "lo": 1, "hi": 100, "label": "1시간 변동"},
    "move_24h": {"cat": "move", "kind": "pct", "rec": 20, "lo": 1, "hi": 100, "label": "24시간 변동"},
    "move_weight": {"cat": "move", "kind": "pct", "rec": 3, "lo": 0, "hi": 100, "label": "총자산 대비 비중 이상만"},
    "move_min": {"cat": "move", "kind": "usd", "rec": 1000, "lo": 0, "hi": 1e9, "label": "보유 금액 이상만"},
    "flow_min": {"cat": "bigflow", "kind": "usd", "rec": 10000, "lo": 1, "hi": 1e10, "label": "금액 이상"},
    "depeg_pct": {"cat": "depeg", "kind": "pct", "rec": 1, "lo": 0.1, "hi": 20, "label": "1달러에서 벗어난 정도"},
    "liq_pct": {"cat": "liq", "kind": "pct", "rec": 10, "lo": 1, "hi": 50, "label": "청산가까지 남은 거리"},
}
REC_TH = {k: v["rec"] for k, v in TH.items()}
QUIET_REC = {"on": True, "from": "01:00", "to": "08:00"}
_V1_REC_CATS = {"health": "on", "digest": "on", "price": "on", "recon": "auto", "sync": "auto", "backfill": "auto", "scam": "on", "pnl": "on",
                "review": "off", "weekly": "off", "move": "on", "bigflow": "on", "lprange": "on", "depeg": "on", "liq": "on", "oa": "on", "other": "on"}
_V1_REC_TH = {"pnl_time": "23:55", "move_1h": 10, "move_24h": 20, "move_min": 1000, "flow_min": 10000, "depeg_pct": 1, "liq_pct": 10}

KIND_CAT = {
    "open": "health", "group": "health", "remind": "health", "resolve": "health", "flap": "health",
    "POISON": "health",
    "CHAIN_STALL": "stall",
    "BAL_LONG": "balmis",
    "digest": "digest",
    "TARGET_HIT": "price", "STOP_HIT": "price",
    "EXF_RECON": "recon", "RECON": "recon", "EX_RECON": "recon", "BALANCE_MISMATCH": "recon",
    "PROGRAM_IN": "sync", "SWAP": "sync", "TRANSFER_OUT": "sync", "TRANSFER_OUT_EX": "sync", "DEPOSIT_MATCHED": "sync",
    "PROMOTE": "sync", "NEW_ASSET": "sync", "EX_FILL_SKIP": "sync", "EX_DEPOSIT_SKIP": "sync", "EX_WITHDRAW_SKIP": "sync",
    "ES_FALLBACK": "sync", "ES_FALLBACK_NONE": "sync", "ES_DAILY_LIMIT": "sync",
    "RPC_FALLBACK": "sync",
    "LP_ADD": "sync", "LP_REMOVE": "sync", "LP_ADJUST": "sync", "SALE_CAND": "sync",
    "BACKFILL_DONE": "backfill", "REDERIVE": "backfill", "CHAIN_AUTO": "backfill",
    "UNKNOWN": "scam",
    "PNL_DAILY": "pnl", "REVIEW_DAILY": "review", "REVIEW_WEEKLY": "weekly", "PRICE_MOVE": "move", "BIG_FLOW": "bigflow",
    "MOVE_LATE": "bigflow", "MOVE_SHORT": "bigflow", "MOVE_ARRIVED": "arrive",
    "LP_RANGE": "lprange", "DEPEG": "depeg", "LIQ_NEAR": "liq", "OA_ALERT": "oa",
    "LOAN_RISK": "liq", "MARGIN_RISK": "liq",
    "NFT_CG_SLOW": "oa",
}
STALL_KIND = "CHAIN_STALL"
BAL_KIND_GATE = "BAL_LONG"
TEST_KIND = "ALERT_TEST"
FIRST_BACKFILL_KIND = "BACKFILL_DONE"
KIND_TIER = {"BIG_INFLOW": "daily"}
KIND_CAT["BIG_INFLOW"] = "bigflow"

JARGON = ("대사", "백필", "미매칭", "원가 미확인", "원가 미상", "정산", "rederive", "REDERIVE", "커서", "폴백", "블록스카웃", "blockscout", "보정")
SAMPLES = {
    "health": "🔴 프로세스 중지 · 장부 계산\n저절로 안 풀릴 수 있어요 — 상태 패널에서 원인과 조치를 확인하세요.\n5분째 · 프로그램이 꺼져 있어요",
    "stall": "🔴 Base 동기화 멈춤 · 이더리움 계열 수집\n대부분 저절로 풀려요 — 한 시간 넘게 이어지면 한 번 더 알려 드릴게요(원인과 조치는 상태 패널에).\n52분째 · 마지막 성공 52분 전",
    "digest": "안 풀린 봇 문제 1건 — 장부 계산 멈춤(1시간 12분째)",
    "balmis": "🔴 잔고가 장부와 하루 넘게 달라요 · 1곳\n할 일: 앱 › 잔고 맞추기에서 이 지갑·코인을 열어 빠진 입출금이 있는지 보세요(장부는 자동으로 고치지 않아요) — 수집·재계산은 다 끝났어요.\n"
              "BSC 지갑 0x1a2b…9f0e 의 BNB — 장부 1.2 · 실제 2.7 (차이 $921)\n  짐작: 실제가 더 많아요 — 장부에 없는 입금(로그 없는 입금·내부 이동 등)이 있는 듯해요",
    "price": "🔴 ETH 목표가에 닿았어요\n팔 계획이었다면 지금이에요.\n지금 $4,512 · 목표 $4,500",
    "recon": "잔고 맞춤: 2개 고침 (고친 게 없는 날은 '잔고는 모두 맞아요')",
    "sync": "(텔레그램으로 보내지 않아요 — 상태 패널에만)",
    "backfill": "📋 과거 기록을 다 가져왔어요\n할 일은 없어요 — 이제 손익·보유가 전체 기간 기준이에요.",
    "scam": "처음 보는 토큰 4",
    "pnl": "오늘 실현 +₩12만 · 매도 4건",
    "review": "AI 복기가 도착했어요 · 10-05(일) 양호",
    "weekly": "주간 복기가 도착했어요 · 09-29~10-05 양호",
    "move": "🔴 SOL 1시간 만에 11% 올랐어요\n급하지 않아요 — 목표가를 걸어 두면 거기서 알려 드려요.\n보유 ₩120만 · 총자산의 4%",
    "bigflow": "🔴 USDC 3,600개(−₩500만)가 밖으로 나갔어요 → 외부 0x3c7e…cd34\n내가 한 게 아니면 바로 거래소·지갑 보안을 확인하세요.\nBase 지갑 A · 13:05",
    "arrive": "✅ USDC 5,000개가 Base 지갑 A에 들어왔어요\n할 일은 없어요.\n이더리움 지갑 A에서 보낸 지 7분 · 수수료로 0.5개 줄었어요",
    "lprange": "LP 범위 벗어남 1",
    "depeg": "🔴 USDC 가격이 1달러에서 1.3% 벗어났어요\n많이 들고 있다면 다른 스테이블로 옮길지 살펴보세요.\n지금 $0.987 · 기준 ±1%",
    "liq": "🔴 ETH 선물 청산가까지 8% 남았어요\n증거금을 넣거나 포지션을 줄이세요.\n현재 2,410 · 청산 2,217 · 바이낸스",
    "oa": "기타 자산: 키움증권 연결이 끊겼어요",
    "other": "그 밖의 소식 1건",
}
DIGEST_SAMPLE = ("📋 하루 요약 · 10월 6일(화)\n어제 실현 +₩12만 · 매도 4건 · 총자산 +₩80만\n많이 움직인 코인 SOL +9% · ETH −3%\n"
                 "잔고 맞춤: 2개 고침 · AI 복기가 도착했어요(양호)\n살펴볼 것 2가지 — 처음 보는 토큰 1 · LP 범위 벗어남 1")


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


NEW_CATS = ("arrive",)
NEW_OFF_CATS = ("stall",)
QUIET_ONLY_SOUND = ("move", "arrive")
REC_OFF_NOW = ("move", "stall")


def _preset_cats(name: str) -> dict:
    if name == "rec":
        return {k: ("off" if TIER[k] == "web" or k in REC_OFF_NOW else "on") for k in CAT_KEYS}
    if name == "min":
        return {k: ("on" if TIER[k] == "now" and k not in QUIET_ONLY_SOUND and k not in REC_OFF_NOW else "off") for k in CAT_KEYS}
    if name == "all":
        return {k: ("off" if TIER[k] == "web" else "on") for k in CAT_KEYS}
    raise KeyError(name)


PRESETS = {
    "rec": {"label": "추천", "desc": "급한 것 6가지는 바로(소리) + 나머지는 하루 한 통 요약(무음) · 봇 내부 소식·체인 수집 지연은 안 보냄(상태 패널에서)"},
    "min": {"label": "최소", "desc": "급한 것 6가지만 바로 — 하루 요약도 안 받음"},
    "all": {"label": "전부", "desc": "추천 + 보유 코인 급등락(밤엔 모아서) · 체인 수집 지연까지"},
}
PRESET_ORDER = ("rec", "min", "all")


def preset_doc(name: str) -> dict:
    return {"v": SCHEMA, "cats": _preset_cats(name), "th": dict(REC_TH), "quiet": dict(QUIET_REC)}


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
    if spec["kind"] == "bool":
        return v if isinstance(v, bool) else None
    if not _num_ok(v):
        return None
    v = float(v)
    if not (spec["lo"] <= v <= spec["hi"]):
        return None
    return int(v) if v == int(v) else round(v, 4)


def _v1_was_rec(raw: dict) -> bool:
    cats = raw.get("cats") if isinstance(raw.get("cats"), dict) else {}
    if any((cats.get(k) if cats.get(k) in LEGACY_MODES else _V1_REC_CATS[k]) != _V1_REC_CATS[k] for k in _V1_REC_CATS):
        return False
    th = raw.get("th") if isinstance(raw.get("th"), dict) else {}
    if any(k in th and th[k] != v for k, v in _V1_REC_TH.items()):
        return False
    q = raw.get("quiet") if isinstance(raw.get("quiet"), dict) else {}
    return (q.get("on", True) is True and q.get("from", "01:00") == "01:00" and q.get("to", "08:00") == "08:00")


def normalize(raw) -> dict:
    d = default_doc()
    if not isinstance(raw, dict):
        return d
    legacy = raw.get("v") != SCHEMA
    if legacy and _v1_was_rec(raw):
        u = raw.get("updated")
        if _num_ok(u) and 0 <= u < TS_MAX:
            d["updated"] = int(u)
        d["migrated"] = "v1-rec"
        return d
    cats = raw.get("cats") if isinstance(raw.get("cats"), dict) else {}
    for k in CAT_KEYS:
        try:
            m = cats.get(k)
            if k in CRIT or TIER[k] == "web":
                continue
            if legacy and m == "auto":
                m = "on"
            if isinstance(m, str) and m in MODES:
                d["cats"][k] = m
        except Exception:
            pass
    for k in NEW_OFF_CATS:
        if not (isinstance(cats.get(k), str) and cats.get(k) in MODES):
            d["cats"][k] = "off"
    miss = [k for k in NEW_CATS if not (isinstance(cats.get(k), str) and cats.get(k) in MODES)]
    if miss:
        for name in PRESET_ORDER:
            pc = _preset_cats(name)
            if all(d["cats"][k] == pc[k] for k in CAT_KEYS if k not in NEW_CATS and k not in NEW_OFF_CATS and k not in CRIT and TIER[k] != "web"):
                for k in miss:
                    d["cats"][k] = pc[k]
                break
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
    if legacy:
        d["migrated"] = "v1-custom"
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
        cur9 = normalize(cur_raw)
        for k9 in ("digest_time", "digest_chart", "digest_axis", "pnl_time"):
            d["th"][k9] = cur9["th"][k9]
        d["updated"] = int(time.time())
        return d, None
    d = normalize(cur_raw)
    d.pop("migrated", None)
    if "cats" in body:
        c = body["cats"]
        if not isinstance(c, dict) or not c:
            return None, "cats 는 {카테고리: on|off}"
        for k, m in c.items():
            if k not in CAT:
                return None, f"모르는 카테고리: {str(k)[:40]}"
            if not isinstance(m, str) or m not in MODES:
                return None, f"{k}: on|off 중 하나"
            if k in CRIT and m != "on":
                return None, "'봇이 멈췄을 때'는 끌 수 없어요 — 봇이 멈춘 걸 알려야 해서 늘 켜 둬요"
            if TIER[k] == "web" and m != "off":
                return None, f"{CAT[k]['label']}: 봇 내부 소식이라 텔레그램으로 보내지 않아요(상태 패널에서 봐요)"
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
                return None, (f"{k}: HH:MM 형식" if spec["kind"] == "time" else f"{k}: true|false" if spec["kind"] == "bool"
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
    SKIP = ("digest_time", "digest_chart", "digest_axis", "pnl_time")
    for name in PRESET_ORDER:
        p = preset_doc(name)
        if any(d["cats"][k] != p["cats"][k] for k in CAT_KEYS if TIER[k] != "web"):
            continue
        if p["cats"].get("move") == "on" or d["cats"].get("move") == "on":
            if d["quiet"]["on"] != p["quiet"]["on"]:
                continue
            if p["quiet"]["on"] and (d["quiet"]["from"], d["quiet"]["to"]) != (p["quiet"]["from"], p["quiet"]["to"]):
                continue
        if any(d["th"][k] != p["th"][k] for k, spec in TH.items() if k not in SKIP and p["cats"].get(spec["cat"]) != "off"):
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


_SW = {"sig": None, "on": True}
_SW_OFF = (False, 0, "false", "off", "0", "no")


def liq_switch_on(cfg=None) -> bool:
    if cfg is None:
        p = common.CONFIG_PATH
        try:
            st = os.stat(p)
            sig = (p, st.st_mtime_ns, st.st_size)
        except OSError:
            sig = (p, None, None)
        if sig != _SW["sig"]:
            _SW["sig"] = sig
            try:
                cfg = common.read_json(p, {})
            except (Exception, SystemExit):
                return _SW["on"]
            if not isinstance(cfg, dict):
                return _SW["on"]
            _SW["on"] = liq_switch_on(cfg)
        return _SW["on"]
    al = cfg.get("alerts") if isinstance(cfg, dict) else None
    v = al.get("liq_fast", True) if isinstance(al, dict) else True
    return not (v in _SW_OFF or (isinstance(v, str) and v.strip().lower() in _SW_OFF))


def effective(doc, key, now=None, conn=None) -> bool:
    if key in CRIT:
        return True
    if TIER.get(key) == "web":
        return False
    if key == "liq" and not liq_switch_on():
        return False
    m = doc["cats"].get(key, "on")
    if m == "auto":
        return True
    return m != "off"


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


URGENT_KINDS = frozenset({"LIQ_NEAR", "STOP_HIT", "BIG_FLOW"})
QUIET_CATS = frozenset({"move"})

FAST_KINDS = frozenset({"LIQ_NEAR", "LOAN_RISK", "MARGIN_RISK"})
FAST_QUEUE = "alerts_fast.jsonl"
URGENT_KINDS = URGENT_KINDS | FAST_KINDS


def digest_on(doc, now=None, conn=None) -> bool:
    return any(effective(doc, k, now, conn) for k in CAT_KEYS if TIER.get(k) == "daily")


def decide(doc, key, now=None, conn=None, kind=None) -> str:
    t = KIND_TIER.get(kind) or TIER.get(key, "daily")
    if t == "web" and key not in CRIT:
        return "web"
    if not effective(doc, key, now, conn):
        return "skip"
    if kind in FAST_KINDS:
        return "send"
    if t == "daily":
        return "daily" if TIER.get(key) == "daily" or digest_on(doc, now, conn) else "skip"
    if key in QUIET_CATS and kind not in URGENT_KINDS and in_quiet(doc, now):
        return "hold"
    return "send"


def digest_due(doc, last_day, now=None):
    now = time.time() if now is None else now
    t = datetime.fromtimestamp(now, KST)
    hm = str((doc.get("th") or {}).get("digest_time") or REC_TH["digest_time"])
    if not _HM.match(hm):
        hm = REC_TH["digest_time"]
    if t.hour * 60 + t.minute < _mins(hm):
        return None
    dk = t.strftime("%Y-%m-%d")
    return None if last_day == dk else dk


_PUB_RE = re.compile(r"https://[a-z0-9.-]+(?::\d{1,5})?")


def public_link(tab: str = "dash", cfg: dict = None) -> str:
    try:
        c = cfg if cfg is not None else (common.read_json(common.CONFIG_PATH, {}) or {})
        u = str(((c or {}).get("web") or {}).get("public_url") or "").strip().rstrip("/")
    except (Exception, SystemExit):
        return ""
    if not u or len(u) > 300 or not _PUB_RE.fullmatch(u):
        return ""
    return f"{u}/v2/#{re.sub(r'[^a-z0-9/_-]', '', str(tab))[:40]}"


def day_key(now=None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, KST).strftime("%Y-%m-%d")


def counts7(stats=None, now=None) -> dict:
    now = time.time() if now is None else now
    s = stats if stats is not None else (_read(STATS_PATH, {}) or {})
    days = (s or {}).get("days") if isinstance(s, dict) else None
    keep = {day_key(now - i * 86400) for i in range(7)}
    out = {k: {"sent": 0, "skip": 0, "held": 0, "daily": 0, "web": 0} for k in CAT_KEYS}
    for dk, row in (days.items() if isinstance(days, dict) else ()):
        if dk not in keep or not isinstance(row, dict):
            continue
        for k, c in row.items():
            if k in out and isinstance(c, dict):
                for f in ("sent", "skip", "held", "daily", "web"):
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
           "cats": [{k: c[k] for k in ("key", "n", "grp", "tier", "label", "desc") if k in c} | {"first7": False, "crit": bool(c.get("crit")),
                                                                                               "th": list(c.get("th") or []), "sample": SAMPLES.get(c["key"], "")} for c in CATS],
           "tiers": [{"key": t, "label": TIER_LABEL[t], "sub": TIER_SUB[t]} for t in TIERS], "digestSample": DIGEST_SAMPLE, "schema": SCHEMA, "migrated": doc.get("migrated"),
           "th": {k: {f: v for f, v in spec.items()} for k, spec in TH.items()},
           "effective": eff, "firstWeek": fw, "quietNow": in_quiet(doc, now), "held": hn,
           "counts7": counts7(stats, now), "tg": {"connected": bool(tg_connected)} if tg_connected is not None else None,
           "updated": doc.get("updated")}
    if extra:
        out.update(extra)
    return out


def json_line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
