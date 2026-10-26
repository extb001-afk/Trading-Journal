#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import calendar  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402

CFG = os.path.join(T.TMP, "config.json")


def _cfg(d):
    json.dump(dict({"chains": {}, "wallets": []}, **d), open(CFG, "w"))
    t9 = time.time() + len(SEEN_CFG)
    SEEN_CFG.append(t9)
    os.utime(CFG, (t9, t9))


SEEN_CFG = []
_cfg({"backfill_months": 5})
import paths  # noqa: E402
import config  # noqa: E402
import exf_okx, exf_bybit, exf_binance  # noqa: E402

chk = T.chk
DAY = 86400
SEEN = []


def http(url, headers=None, **_k):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    SEEN.append((u.netloc, u.path, q))
    if "okx" in u.netloc:
        return {"code": "0", "data": []}
    if "bybit" in u.netloc:
        return {"retCode": 0, "result": {"list": [], "nextPageCursor": ""}}
    return []


def herr(url, headers=None, **_k):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    SEEN.append((u.netloc, u.path, q))
    if u.path.endswith("/account"):
        return {"positions": [], "totalWalletBalance": "0", "availableBalance": "0", "totalInitialMargin": "0"}
    return []


T.patch_moved("http_json", http, ("exf_",))
T.patch_moved("_http_json_err", herr, ("exf_",))
T.patch_moved("_gov_prepare", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("_srv_ms", lambda *_a: int(time.time() * 1000), ("exf_",))
T.patch_moved("_px_safe", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("PACE", 0, ("exf_",))
ENV = {"TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s", "TJ_OKX_PASSPHRASE": "p", "TJ_BYBIT_KEY": "k", "TJ_BYBIT_SECRET": "s",
       "TJ_BINANCE_KEY": "k", "TJ_BINANCE_SECRET": "s"}


def _clear():
    for ex in ("okx", "bybit", "binance"):
        for nm in (f"futures_{ex}.json", f"futures_px_{ex}.json"):
            p9 = paths.state(nm)
            if os.path.exists(p9):
                os.remove(p9)


def okx_floor_ms(now):
    g = time.gmtime(now)
    y, m = g.tm_year, g.tm_mon - 3
    if m <= 0:
        y, m = y - 1, m + 12
    return (calendar.timegm((y, m, 1, 0, 0, 0)) + 3600) * 1000


def run(ex):
    SEEN.clear()
    {"okx": exf_okx._fut_okx, "bybit": exf_bybit._fut_bybit, "binance": exf_binance._fut_binance}[ex](ENV)
    return list(SEEN)


def okx_archive_begins():
    return [int(q["begin"]) for _n, p, q in run("okx") if p.endswith("bills-archive")]


def bybit_earliest_days():
    cp = [int(q["startTime"]) for _n, p, q in run("bybit") if p.endswith("closed-pnl")]
    return (time.time() * 1000 - min(cp)) / 86400000 if cp else None


def binance_start_days():
    inc = [int(q["startTime"]) for _n, p, q in run("binance") if p.endswith("/income")]
    return (time.time() * 1000 - min(inc)) / 86400000 if inc else None


def near(v, want, tol=0.01):
    return v is not None and abs(v - want) <= tol


print("[1] since 없음 · 창 5개월")
_clear()
NOW = time.time()
b = okx_archive_begins()
chk(b and abs(min(b) - max(okx_floor_ms(NOW), int((NOW - 150 * DAY) * 1000))) < 5000,
    "[1] OKX: 과거 정산 채움 = bills-archive 를 보존 한도(3개월 전 달 1일)부터(종전 = since 없으면 채움 없음)", b)
st9 = json.load(open(paths.state("futures_okx.json")))
chk(isinstance((st9.get("cursor") or {}).get("hist_lo"), int), "[1] OKX: 채움 뒤 hist_lo 기억(다시 안 받음)", st9.get("cursor"))
d9 = bybit_earliest_days()
chk(near(d9, 150), "[1] 바이비트: closed-pnl 첫 하한 = 창 시작 150일(종전 7일)", d9)
d9 = binance_start_days()
chk(near(d9, 150), "[1] 바이낸스: income 첫 startTime = 창 시작 150일", d9)

print("[2] 창 14개월")
_clear()
_cfg({"backfill_months": 14})
d9 = binance_start_days()
chk(near(d9, 364), "[2] 바이낸스: 보존 약 1년(364일)에서 자름(종전 150일 고정)", d9)
d9 = bybit_earliest_days()
chk(near(d9, 420), "[2] 바이비트: 창 시작 420일(2년 안)", d9)

print("[3] backfill_since")
_clear()
s9 = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 200 * DAY))
_cfg({"backfill_months": 2, "exchanges": {"bybit": {"backfill_since": s9}}})
d9 = bybit_earliest_days()
want9 = (time.time() - calendar.timegm(time.strptime(s9, "%Y-%m-%d"))) / DAY
chk(near(d9, want9), "[3] 바이비트: 거래소별 since(창보다 이름)부터", {"got": d9, "want": want9})
d9 = binance_start_days()
chk(near(d9, 60), "[3] 바이낸스: 다른 거래소 since 는 무관 — 창 시작 60일", d9)
_clear()
_cfg({"backfill_months": 2, "backfill_since": s9})
d9 = binance_start_days()
chk(near(d9, want9), "[3] 바이낸스: 전체 since(창보다 이름)부터(종전 = since 무시 150일)", {"got": d9, "want": want9})

print("[4] 커서·hist_lo·설정 실패")
_clear()
_cfg({"backfill_months": 14})
cur9 = int((time.time() - 3 * DAY) * 1000)
json.dump({"cursor": {"income": cur9}, "events": []}, open(paths.state("futures_binance.json"), "w"))
inc = [int(q["startTime"]) for _n, p, q in run("binance") if p.endswith("/income")]
chk(inc and inc[0] == cur9, "[4] 바이낸스: 커서가 있으면 커서 그대로(첫 하한 무관)", inc[:2])
_clear()
now_ms = int(time.time() * 1000)
json.dump({"cursor": {"closed_pnl": now_ms - DAY * 1000, "hist_lo": now_ms - 500 * DAY * 1000}, "events": []},
          open(paths.state("futures_bybit.json"), "w"))
d9 = bybit_earliest_days()
chk(d9 is not None and d9 < 10, "[4] 바이비트: hist_lo 가 이미 하한 이하 = 과거 채움 다시 안 함", d9)
_clear()
lc0 = config.load_config


def _boom():
    raise SystemExit("설정 손상(합성)")


config.load_config = _boom
try:
    d9 = binance_start_days()
    chk(near(d9, 150), "[4] 설정 읽기 실패: 바이낸스 = 종전 기본 150일(평시 수집은 계속)", d9)
    chk(not okx_archive_begins(), "[4] 설정 읽기 실패: OKX 과거 채움 없음(종전) · 평시 수집은 계속")
    d9 = bybit_earliest_days()
    chk(d9 is not None and d9 < 8, "[4] 설정 읽기 실패: 바이비트 = 최근 7일만(종전)", d9)
finally:
    config.load_config = lc0

T.finish()
