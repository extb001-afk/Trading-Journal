#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import sqlite3  # noqa: E402

import db  # noqa: E402
import recon_adj  # noqa: E402

chk = T.chk
NOW = 1_800_000_000
DAY = 86400
E8 = 10 ** 8
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
W1 = "0x00000000000000000000000000000000000000a1"


def fresh():
    c = sqlite3.connect(":memory:")
    for ddl in db.DDL:
        c.execute(ddl)
    return c


AID = [0]


def asset(c, kind, sym, chain=None, addr=None, dec=8):
    AID[0] += 1
    c.execute("INSERT INTO assets(asset_id, kind, chain, address, symbol, decimals, group_id) VALUES(?,?,?,?,?,?,?)",
              (AID[0], kind, chain, addr, sym, dec, AID[0]))
    return AID[0]


def exrow(c, ex, aid, ts, q, why="later_in"):
    sid = f"exfrecon:{aid}:{ts}"
    c.execute("INSERT INTO postings(source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
              " VALUES('exchange', ?, ?, 0, ?, ?, ?, ?, 'opening', 'EXF_ADJUST', 1)", (f"{ex}:recon", sid, ts, aid, f"exchange:{ex}", str(int(q * E8))))


def chainrow(c, chain, aid, ts, q, seq=0, why="untracked_out"):
    sid = f"recon:{chain}:{W1}"
    c.execute("INSERT INTO postings(source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
              " VALUES('opening', ?, ?, ?, ?, ?, ?, ?, 'opening', 'OPENING', 1)", (chain, sid, seq, ts, aid, f"wallet:{chain}:{W1}", str(int(q * E8))))


def run(c, px_fn=None, now=NOW):
    return recon_adj.compute(c, now=now, state_dir=T.TMP, px_fn=px_fn)


c = fresh()
btc = asset(c, "exchange_currency", "BTC")
exrow(c, "binance", btc, NOW - 60 * DAY, 1, "first")
exrow(c, "binance", btc, NOW - 1, 10, "later_in")
c.commit()
rows, doc = run(c)
late = [r for r in rows if r["ts"] == NOW - 1][0]
chk(late["cls"] == "unexplained" and late["usd"] is None, "U1 거래소 BTC 가격 모름 = 설명 안 됨(스팸 아님) · $ 없음(허구 값 없음)", (late["cls"], late["usd"]))
chk(all(r["cls"] != "spam" for r in rows), "U1 가격 없음만으로 spam 금지", [(r["cls"], r["q"]) for r in rows])
une = doc["unexplained"]
chk(une["n"] == 1 and une["n7"] == 1 and une.get("nopx") == 1 and une.get("nopx7") == 1 and une["usd"] == 0, "U1 건수 보존 · 평가 불가 건수 따로 · $ 합 0(허구 없음)", une)
ck = doc["check"]
chk(ck["level"] == "warn" and not ck["tg"], "U1 실자산 7일 평가 불가 = 주황(텔레그램 없음 — 금액 모름)", ck)
chk("평가 불가" in ck["title"] and "$0" not in ck["title"], "U1 제목 = 평가 불가 건수('$0' 아님)", ck["title"])
chk("BTC" in ck["detail"] and "10" in ck["detail"] and "평가 불가" in ck["detail"], "U1 상세 = 심볼·수량·평가 불가", ck["detail"])
chk("$0" not in ck["detail"], "U1 상세에 허구 $0 없음(금액 모름만 = $ 안 씀)", ck["detail"])
rows2, doc2 = run(c, px_fn=lambda sym, aid: 60000)
chk([(r["cls"], r["usd"]) for r in rows2 if r["ts"] == NOW - 1] == [("unexplained", 600000.0)] and doc2["check"]["level"] == "warn" and doc2["check"]["tg"]
    and doc2["unexplained"].get("nopx", 0) == 0, "U1 반대: 같은 원장 가격 있음 = $600,000 노랑 + 텔레그램(종전 경로 그대로)", (doc2["check"]["title"], doc2["unexplained"]))

c = fresh()
imp = asset(c, "token", "U5DТ", "eth", "0x00000000000000000000000000000000000000c1")
fake = asset(c, "token", "USDT", "eth", "0x00000000000000000000000000000000000000c2")
lure = asset(c, "token", "claim-reward.com", "eth", "0x00000000000000000000000000000000000000c3")
gen = asset(c, "token", "WBTC", "eth", WBTC)
for i, a in enumerate((imp, fake, lure, gen)):
    chainrow(c, "eth", a, NOW - DAY, -5, seq=i)
c.commit()
rows, doc = run(c)
by = {r["aid"]: r for r in rows}
chk([by[a]["cls"] for a in (imp, fake, lure)] == ["spam"] * 3, "U2 사칭 글자·대표 심볼 흉내·낚시 이름(가격 없음) = 스팸", [(by[a]["sym"], by[a]["cls"]) for a in (imp, fake, lure)])
chk(by[gen]["cls"] == "unexplained" and by[gen]["usd"] is None, "U2 정품 토큰 가격 모름 = 스팸 아님 · 설명 안 됨", (by[gen]["cls"], by[gen]["usd"]))
chk(doc["check"]["level"] == "warn" and doc["unexplained"].get("nopx7") == 1, "U2 정품 토큰 7일 평가 불가 = 주황(스팸 3건은 빠짐)", (doc["check"], doc["unexplained"]))

c = fresh()
wsol = asset(c, "token", "WSOL", "sol", "So11111111111111111111111111111111111111112", dec=9)
chainrow(c, "sol", wsol, NOW - DAY, -3)
c.commit()
rows, doc = run(c)
chk([(r["cls"], r["usd"]) for r in rows] == [("unexplained", None)] and doc["check"]["level"] == "warn",
    "U2b 솔라나 정품 민트(대소문자 그대로) = 스팸 아님 · 실자산 평가 불가 주황", ([(r["cls"], r.get("spam")) for r in rows], doc["check"]["level"]))

c = fresh()
plain = asset(c, "token", "ZZQ", "eth", "0x00000000000000000000000000000000000000d1")
chainrow(c, "eth", plain, NOW - DAY, -7)
c.commit()
rows, doc = run(c)
chk([r["cls"] for r in rows] == ["unexplained"] and doc["unexplained"]["n"] == 1 and doc["unexplained"].get("nopx") == 1, "U3 평범한 이름 체인 토큰 가격 모름 = 설명 안 됨 건수 유지(평가 불가)",
    ([r["cls"] for r in rows], doc["unexplained"]))
chk(doc["check"]["level"] == "ok" and "평가 불가 1건" in doc["check"]["detail"], "U3 레벨 ok(정품 목록 밖 토큰 = 소음 없음) · 상세에 평가 불가 건수", doc["check"])

c = fresh()
eth = asset(c, "exchange_currency", "ETH")
exrow(c, "okx", eth, NOW - 30 * DAY, 2, "first")
dot = asset(c, "exchange_currency", "DOT")
exrow(c, "okx", dot, NOW - 3 * DAY, 4, "later_in")
exrow(c, "okx", dot, NOW - 2 * DAY, -4, "untracked_out")
tiny = asset(c, "exchange_currency", "TNY")
exrow(c, "okx", tiny, NOW - DAY, 0.00000001, "later_in")
c.commit()
rows, doc = run(c)
cl = {s: sorted({r["cls"] for r in rows if r["sym"] == s}) for s in ("ETH", "DOT", "TNY")}
chk(cl["ETH"] == ["pre_window"] and cl["DOT"] == ["pair"], "U4 평가 불가 줄도 창 시작·±쌍 규칙 그대로", cl)
chk(cl["TNY"] == ["unexplained"], "U4 가격 모르면 먼지 판정 안 함(평가 불가 · 설명 안 됨)", cl["TNY"])
rows, doc = run(c, px_fn=lambda sym, aid: 1.0)
chk(sorted({r["cls"] for r in rows if r["sym"] == "TNY"}) == ["dust"], "U4 반대: 가격 있으면 $1 미만 = 먼지", [r["cls"] for r in rows if r["sym"] == "TNY"])

c = fresh()
xrp = asset(c, "exchange_currency", "XRP")
exrow(c, "bybit", xrp, NOW - 90 * DAY, 1, "first")
exrow(c, "bybit", xrp, NOW - 20 * DAY, 900, "later_in")
c.commit()
rows, doc = run(c)
chk(doc["unexplained"].get("nopx") == 1 and doc["unexplained"].get("nopx7", 0) == 0 and doc["check"]["level"] == "ok" and "평가 불가 1건" in doc["check"]["detail"],
    "U5 7일 밖 평가 불가 = ok · 건수만 보임", (doc["unexplained"], doc["check"]))
rows, doc = run(c, px_fn=lambda sym, aid: 2.0)
chk(doc["unexplained"].get("nopx", 0) == 0 and doc["unexplained"]["usd"] == 1800.0 and "평가 불가" not in doc["check"]["detail"], "U5 가격 복구 뒤 = $ 로 전환(평가 불가 0)",
    (doc["unexplained"], doc["check"]["detail"]))
chk(doc["by_class"].get("unexplained", {}).get("n") == 1, "U5 갈래 건수 그대로", doc["by_class"])

c = fresh()
btc = asset(c, "exchange_currency", "BTC")
exrow(c, "binance", btc, NOW - 60 * DAY, 1, "first")
exrow(c, "binance", btc, NOW - 100, 10, "later_in")
c.commit()
got = []
recon_adj.exf_dm(c, lambda ref, sec: NOW - 90 * DAY, "binance", NOW - 100, 1, lambda k, m: got.append((k, m)), px_fn=lambda s, a: None)
chk(len(got) == 1 and "BTC" in got[0][1] and "평가 불가" in got[0][1] and "$0" not in got[0][1] and "1개 통화 보정" in got[0][1],
    "U6 exf_dm 평가 불가 통화 = 알림(평가 불가 · $0 없음 · 'N개 통화 보정' 집계 꼴 유지)", got)
import alert_bot  # noqa: E402
chk(not got or alert_bot.recon_fixed(got[0][1]) == 1, "U6 하루 요약 집계 꼴 그대로", got)

import json as _j  # noqa: E402
import os as _o  # noqa: E402
SPOT = _o.path.join(T.TMP, "spot.json")
c = fresh()
krw = asset(c, "exchange_currency", "KRW")
exrow(c, "bithumb", krw, NOW - 60 * DAY, 1_000_000, "first")
exrow(c, "bithumb", krw, NOW - 1, 1_500_000, "later_in")
c.commit()
rows, doc = run(c, px_fn=lambda sym, aid: 60000)
late = [r for r in rows if r["ts"] == NOW - 1][0]
chk(late["usd"] is None and late.get("nopx"), "U8 환율 없음 = 원화 평가 불가 그대로(px_fn 단가로 원화 평가 안 함)", (late["usd"], late.get("nopx")))
for bad in (1.0, "x", 0):
    _j.dump({"rate": bad}, open(SPOT, "w"))
    rows, doc = run(c)
    late = [r for r in rows if r["ts"] == NOW - 1][0]
    chk(late["usd"] is None and late.get("nopx"), "U8 환율 범위 밖·숫자 아님 = 평가 불가 그대로", (bad, late["usd"]))
_j.dump({"rate": 1500.0, "rate_ts": NOW - 60}, open(SPOT, "w"))
rows, doc = run(c)
late = [r for r in rows if r["ts"] == NOW - 1][0]
chk(late["usd"] == 1000.0 and not late.get("nopx") and late["cls"] == "unexplained", "U8 환율 있음 = 원화 1,500,000 / 1,500 = $1,000 · 평가 불가 아님", (late["usd"], late.get("nopx"), late["cls"]))
chk(doc["unexplained"].get("nopx", 0) == 0 and "평가 불가" not in doc["check"]["detail"], "U8 요약·상세에 원화 평가 불가 없음", (doc["unexplained"], doc["check"]["detail"]))
_o.remove(SPOT)

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
CP = os.path.join(T.TMP, "adj_copy")
os.makedirs(CP, exist_ok=True)
cf = sqlite3.connect(os.path.join(CP, "ledger.db"))
for ddl in db.DDL:
    cf.execute(ddl)
AID[0] = 0
ub = asset(cf, "token", "WBTC", "eth", "0x00000000000000000000000000000000000000b7")
chainrow(cf, "eth", ub, NOW - DAY, -2)
bx = asset(cf, "exchange_currency", "BTC")
exrow(cf, "binance", bx, NOW - 60 * DAY, 1, "first")
exrow(cf, "binance", bx, NOW - 1, 10, "later_in")
cf.commit()
cf.close()
json.dump({"eth": {"0x00000000000000000000000000000000000000b7": "WBTC"}}, open(os.path.join(CP, "genuine_tokens.json"), "w"))
tool = os.path.join(T.ROOT, "tools", "refactor", "adj_report.py")
if not os.path.isfile(tool):
    public_layout = os.path.realpath(os.path.join(T.HERE, "..")) == os.path.realpath(T.ROOT)
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/refactor/adj_report.py) 없음 · U7 건너뜀" if public_layout
        else "저장소 배치인데 tools/refactor/adj_report.py 없음(건너뛰지 않고 실패)")
    T.finish()
pr = subprocess.run([sys.executable, "-I", tool, "--state", CP, "--now", str(NOW), "--json", os.path.join(CP, "out.json")], capture_output=True, text=True, timeout=120)
outd = json.load(open(os.path.join(CP, "out.json"))) if pr.returncode == 0 else {}
chk(pr.returncode == 0 and (outd.get("by_class") or {}).get("spam") is None and (outd.get("unexplained") or {}).get("nopx") == 2,
    "U7 adj_report = 사본의 사용자 정품 목록(정품 WBTC 가격 없음 = 스팸 아님 · 평가 불가 2)", (pr.returncode, pr.stderr[-300:], outd.get("by_class"), outd.get("unexplained")))
top = [ln for ln in pr.stdout.splitlines() if "BTC" in ln and "K7" in ln]
chk(top and all("$0" not in ln and "평가 불가" in ln for ln in top), "U7 adj_report 상위 줄 평가 불가 = '$0' 아님", pr.stdout[-600:])
chk("평가 불가" in pr.stdout.splitlines()[0], "U7 adj_report 첫 줄에 평가 불가 건수", pr.stdout.splitlines()[:1])
T.finish()
