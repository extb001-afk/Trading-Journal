#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import shutil
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import common
import db as dbm
import search_index as si

chk, safe, SRC, TMP = T.chk, T.safe, T.SRC, T.TMP
NEW = hasattr(si, "ROWV")
KST = timezone(timedelta(hours=9))
TODAY = datetime(2026, 10, 6, 1, 0, tzinfo=KST)
CN = {"eth": "Ethereum", "base": "Base", "bsc": "BSC", "sol": "Solana", "optimism": "Optimism", "arbitrum": "Arbitrum"}


def ts_of(iso, hm="12:00"):
    return int(datetime.strptime(iso + " " + hm, "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp())


P = lambda q: safe(si.parse_query, q, TODAY)
p = P("ＢＴＣ")
chk(isinstance(p, dict) and p.get("ticker") == "BTC", "A NFKC: 전각 'ＢＴＣ' = 티커 BTC", p)
nfd = unicodedata.normalize("NFD", "비트코인")
p = P(nfd)
chk(isinstance(p, dict) and p.get("ticker") == "BTC", "A NFKC: 맥에서 복사한 한글(자모 분리형 '비트코인') = BTC", p if not isinstance(p, dict) else p.get("ticker"))
H64 = "5ea7" + "c" * 56 + "f00d"
p = P(H64)
chk(isinstance(p, dict) and ("tx", "0x" + H64) in (p.get("exact") or []), "A 0x 없는 64자리 해시 = 0x 붙인 꼴 정확 대조", p)
p = P("0x5ea7...f00d")
chk(isinstance(p, dict) and (p.get("short") or [None])[0] == ("0x5ea7", "f00d", True), "A '0x5ea7...f00d' = 앞·뒤 대조(줄임)", p)
p = P("0x5ea7…f00d")
chk(isinstance(p, dict) and (p.get("short") or [None])[0] == ("0x5ea7", "f00d", True), "A '0x5ea7…f00d'(말줄임표) = 앞·뒤 대조", p)
p = P("005930")
chk(isinstance(p, dict) and p.get("numtext") == ["005930"], "A 숫자만(005930) = 금액 근처 + 글자 둘 다", p)
p = P("9999-12")
chk(isinstance(p, dict) and "_exc" not in p and any(x.get("t") == "9999-12" for x in p.get("ignored") or []), "A 9999-12 = 예외 없음 · '날짜 범위 밖' 안내", p)
p = P("after:9999-12")
chk(isinstance(p, dict) and "_exc" not in p and "after" not in (p.get("filters") or {}) and p.get("ignored"), "A after:9999-12 = 예외 없음 · 조건 버리고 안내", p)
r9 = safe(si._month_end, 9999, 12)
chk(r9 == "9999-12-31", "A 월말 계산 경계(9999-12 → 9999-12-31 · 10000년 넘침 없음)", r9)
p = P("foo:bar ETH -type:gas wallet:콜드 ex:업비트 has:memo -chain:base type:hack")
ig = [x.get("t") for x in (p.get("ignored") or [])] if isinstance(p, dict) else p
chk(isinstance(p, dict) and "foo:bar" in ig and "type:hack" in ig and p["filters"].get("wallet") == "콜드" and p["filters"].get("ex") == "upbit"
    and p["filters"].get("has") == "memo" and p.get("neg", {}).get("type") == ["gas"] and p.get("neg", {}).get("chain") == ["base"],
    "A 7장 6 문법: -type:gas · wallet: · ex:업비트=upbit · has:memo · -chain: · 모르는 조건(foo:bar · type:hack) = ignored", p)
p = P("chain:op")
chk(isinstance(p, dict) and p["filters"].get("chain") == "optimism", "A chain:op = optimism 키(정해진 키로 정규화)", p)
p = P("ㅂㅌ")
chk(isinstance(p, dict) and p.get("ticker") == "BTC", "A 초성 'ㅂㅌ' = BTC(줄임말 '비트' 초성)", p)
p = P("비트")
chk(isinstance(p, dict) and p.get("ticker") == "BTC", "A '비트' = BTC(별칭 사전)", p)
p = P("7vHt")
chk(isinstance(p, dict) and p.get("b58p") == ["7vHt"], "A 솔라나 앞 4자리 '7vHt' = 대소문자 그대로 앞부분", p)

SP_WAL = "0x" + "a" * 40
EVM2 = "0x" + "b" * 40
MID = "Fp4Wn8Rd2Kx7Bq5Mz3Ht9Cv6Jy"
SOLA = "7vHtM3" + MID + "BzYc"
SOLA2 = "7vHtm3" + "zz" + MID[2:] + "AaAa"
SOLS = "3dPwkz" + MID * 3 + "R8Lt"
L = common.DB_PATH
conn = dbm.open_db(L)
assets = [("token", "eth", "0x" + "1" * 40, "USDC", 6), ("native", "sol", None, "SOL", 9), ("token", "base", "0x" + "2" * 40, "ETH", 18),
          ("token", "optimism", "0x" + "3" * 40, "OP", 18), ("token", "base", "0x" + "4" * 40, "BTC", 8)]
for k, ch, ad, sy, dc in assets:
    conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals) VALUES (?, ?, ?, ?, ?)", (k, ch, ad, sy, dc))


def post(ns, sid, seq, ts, aid, loc, leg, ev, cost):
    conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                 " VALUES ('chain_tx', ?, ?, ?, ?, ?, ?, '1', ?, NULL, ?, ?, 1)", (ns, sid, seq, ts, aid, loc, cost, leg, ev))


HB = "0x" + H64
post("base", HB, 0, ts_of("2026-09-12", "10:00"), 5, f"wallet:base:{SP_WAL}", "disp", "SWAP", "450.0")
post("base", HB, 1, ts_of("2026-09-12", "10:00"), 1, f"wallet:base:{SP_WAL}", "acq", "SWAP", "450.0")
post("optimism", "0x" + "e" * 64, 0, ts_of("2026-10-01"), 4, f"wallet:optimism:{SP_WAL}", "acq", "SWAP", "120.0")
post("sol", SOLS, 0, ts_of("2026-09-12", "11:00"), 2, f"wallet:sol:{SOLA}", "acq", "TRANSFER_IN", "15.0")
post("eth", "0x" + "9" * 64, 0, ts_of("2026-09-12", "09:00"), 3, f"wallet:eth:{SP_WAL}", "gas", "FAILED", "3.0")
conn.commit()
conn.close()


def ev(t, sym, k, d, a="—", tx="—", src="w:" + SP_WAL, q="1", **kw):
    e = {"t": "", "sym": sym, "k": k, "d": d, "q": q, "a": a, "tx": tx, "src": src, "_ts": t}
    e.update(kw)
    return e


def tax(acq, disp, fee=0.0):
    return {"acq": acq, "disp": disp, "fee": fee, "_acq": acq, "_disp": disp, "_fee": fee}


D1, D2, D3 = "2026-09-12", "2026-09-20", "2026-10-01"
IX = {
    D1: [(ts_of(D1, "10:00"), "pos", ev(ts_of(D1, "10:00"), "BTC", "온체인 매도", "Base · 스왑 매도 · Ethereum 경유 브릿지 자금", a="$450.00", tx="0x5ea7…f00d", _tax=tax(500, 450, 2)),
          ("gBTC", "BTC", "Ethereum · Base 외 2")),
         (ts_of(D1, "10:05"), "pos", ev(ts_of(D1, "10:05"), "ETH", "온체인 매도", "Base · 스왑 매도", a="$130.00", tx="0x6b2c…a4e8", _tax=tax(100, 130, 1)),
          ("gETH", "ETH", "Ethereum · Base 외 6")),
         (ts_of(D1, "10:10"), "pos", ev(ts_of(D1, "10:10"), "STOP", "거래소 매수", "바이낸스 · 현물 체결", a="$77.00", src="ex:binance"), ("gSTOP", "STOP", "바이낸스")),
         (ts_of(D1, "10:20"), "extra", ev(ts_of(D1, "10:20"), "SOL", "입금 확인", "업비트 입금 완료 · 원가 승계", a="$300.00", src="ex:upbit"), None),
         (ts_of(D1, "11:00"), "extra", ev(ts_of(D1, "11:00"), "SOL", "전송", "Solana · 스테이킹 보상", a="$15.00", tx=SOLS[:6] + "…" + SOLS[-4:], src="w:" + SOLA), None),
         (ts_of(D1, "09:00"), "extra", ev(ts_of(D1, "09:00"), "ETH", "가스", "Ethereum · 가스(실패 tx)", a="$3.00", src="w:" + SP_WAL), None),
         (ts_of(D1, "12:00"), "pos", ev(ts_of(D1, "12:00"), "SOLV", "온체인 매수", "BSC · 스왑 · 지불 10 USDT", a="$10.00", src="w:" + EVM2), ("gSOLV", "SOLV", "BSC")),
         (ts_of(D1, "13:00"), "pos", ev(ts_of(D1, "13:00"), "ETH", "온체인 매수", "Solana · 스왑 · 지불 1 SOL(브릿지 Wormhole)", a="$20.00", src="w:" + SOLA), ("gETHs", "ETH", "Solana"))],
    D2: [(ts_of(D2, "15:00"), "pos", ev(ts_of(D2, "15:00"), "ETH", "온체인 매도", "Ethereum · 스왑 매도", a="$90.00", _tax=tax(100, 90, 0)), ("gETH", "ETH", "Ethereum · Base 외 6")),
         (ts_of(D2, "16:00"), "pos", ev(ts_of(D2, "16:00"), "SOL", "온체인 매수", "Solana · 스왑 · 지불 50 USDC", a="$50.00", src="w:" + SOLA2), ("gSOL", "SOL", "Solana"))],
    D3: [(ts_of(D3, "09:00"), "pos", ev(ts_of(D3, "09:00"), "OP", "거래소 매수", "바이빗 · 현물 체결", a="$120.00", src="ex:bybit"), ("gOP", "OP", "바이빗")),
         (ts_of(D3, "10:00"), "pos", ev(ts_of(D3, "10:00"), "OP", "온체인 매수", "Optimism · 스왑 · 지불 120 USDC", a="$120.00"), ("gOPo", "OP", "Optimism"))],
}
ZD = "2026-08-15"
IX[ZD] = [(ts_of(ZD, "00:00") + i * 60, "pos", ev(ts_of(ZD, "00:00") + i * 60, "ZZZ", "거래소 매수", "업비트 · KRW 마켓 체결 " + str(i), a=f"${i + 1}.00", src="ex:upbit"),
           ("gZZZ", "ZZZ", "업비트")) for i in range(120)]
POS = [{"key": "gBTC", "realizedByDay": {D1: 999.0}}, {"key": "gETH", "realizedByDay": {D1: 28.0, D2: -10.0}}]
DIX = {"builtAt": 1, "ix": IX, "pos": POS}
OUT = {"todayIso": "2026-10-06", "fields": {
    "coins": [{"sym": "BTC", "name": "BTC · Base", "qty": 1, "price": 60000}, {"sym": "ETH", "name": "ETH · Ethereum", "qty": 2, "price": 3000},
              {"sym": "ETHF", "name": "ETHF · 업비트", "qty": 5, "price": 1}, {"sym": "SOL", "name": "SOL · Solana", "qty": 10, "price": 150},
              {"sym": "SOLV", "name": "SOLV · BSC", "qty": 10, "price": 1}, {"sym": "OP", "name": "OP · Optimism", "qty": 10, "price": 2},
              {"sym": "STOP", "name": "STOP · 바이낸스", "qty": 1, "price": 1}, {"sym": "ZZZ", "name": "ZZZ · 업비트", "qty": 1, "price": 1},
              {"sym": "BCH", "name": "BCH · 업비트", "qty": 100, "price": 500}],
    "outflows": [{"address": EVM2, "chains": ["base"], "chainNames": ["Base"], "tokens": [{"sym": "USDT"}], "count": 2, "last": "2026-09-12", "lastTs": ts_of(D1),
                  "usdAtSend": 5000, "alias": "", "memo": "친구 대여", "exchange": ""}],
    "walletRows": [{"alias": "콜드 지갑", "addr": SP_WAL, "chains": "Ethereum · Base"}, {"alias": "hot7", "addr": SOLA, "chains": "Solana"}],
    "depositRows": [{"ex": "업비트", "net": "Solana", "addr": SOLA2, "memo": "—"}],
    "realizedByDate": {D1: 1027.0, D2: -10.0}}}
SD = common.STATE_DIR
json.dump({"v": 1, "memos": {f"{D1}|BTC": {"memo": "브릿지 자금 마련용 매도", "at": ts_of(D1)}}}, open(os.path.join(SD, "day_memos.json"), "w"), ensure_ascii=False)
json.dump({D2: {"iso": D2, "s": "보통", "sum": "ETH 비중을 줄였다", "note": "Ethereum 수수료가 비쌌음", "obs": [], "next": ""},
           D3: {"iso": D3, "s": "양호", "sum": "ETHF 상장 소식만 봤다", "note": "", "obs": [], "next": ""}},
          open(os.path.join(SD, "reviews_llm.json"), "w"), ensure_ascii=False)
json.dump({"v": 1, "items": [{"id": "oa1", "name": "삼성전자", "cat": "stock", "ticker": "005930", "value": 1, "cur": "KRW"}]}, open(os.path.join(SD, "other_assets.json"), "w"), ensure_ascii=False)

state = {"out": OUT, "dix": DIX}
IDX = si.Indexer(lambda: (state["out"], state["dix"]), nft_fn=lambda: {}, chain_names=CN, sleep=lambda s: None)
IDX.tick()
if NEW:
    IDX.tick()


def S(q, **kw):
    return safe(si.search, q, today=TODAY, **kw)


def grp(r, k):
    return next((g for g in (r.get("groups") or []) if g["kind"] == k), None) if isinstance(r, dict) else None


def titles(r, k):
    g = grp(r, k)
    return [i["title"] for i in g["items"]] if g else []


def subs(r, k):
    g = grp(r, k)
    return [i["sub"] for i in g["items"]] if g else []


r = S("chain:eth")
ev9 = subs(r, "event")
chk(ev9 and all("Ethereum ·" in s9 for s9 in ev9) and not any("Base ·" in s9 for s9 in ev9) and not any("업비트" in s9 for s9 in ev9),
    "B chain:eth = 이더리움 기록만(Base 스왑·업비트 기록 아님 — 외부 재검토 재현 'chain:eth 가 Base')", ev9)
r = S("chain:sol")
ev9 = subs(r, "event")
chk(ev9 and any("Solana · 스테이킹" in s9 for s9 in ev9) and not any("업비트 입금" in s9 for s9 in ev9),
    "B chain:sol = 솔라나 온체인 기록(업비트 SOL 입금 아님 — 외부 재검토 재현 'chain:sol 이 업비트 SOL 입금만')", ev9)
r = S("chain:op")
ts9 = titles(r, "event") + titles(r, "coin")
chk(any("OP" == t9.split()[0] for t9 in ts9) and not any("STOP" in t9 for t9 in ts9) and not any("거래소" in s9 for s9 in subs(r, "event")),
    "B chain:op = Optimism 기록만('STOP'·바이빗 OP 아님 — 외부 재검토 재현)", [ts9, subs(r, "event")])
r = S("chain:base")
chk(grp(r, "tx") and all(i["chain"] == "base" for i in grp(r, "tx")["items"]) and any("BTC" in t9 for t9 in titles(r, "event")), "B chain:base = Base tx·기록", r if not isinstance(r, dict) else titles(r, "event"))
r = S("ETH")
et9 = titles(r, "event")
chk(et9 and all(t9.startswith("ETH ") for t9 in et9), "B 'ETH' = 심볼 ETH 기록만(설명에 Ethereum 든 BTC 매도 아님)", et9)
chk("ETHF" not in titles(r, "coin") and "ETH" in titles(r, "coin"), "B 'ETH' 코인 = ETH 만(ETHF 아님)", titles(r, "coin"))
rv9 = titles(r, "review")
chk(rv9 and len(rv9) == 1 and "9월 20일" in rv9[0], "B 'ETH' 리뷰 = 낱말 ETH 든 리뷰만(ETHF 상장 리뷰 아님)", rv9)
r = S("OP")
chk(not any("STOP" in t9 for t9 in titles(r, "event") + titles(r, "coin")) and any(t9.startswith("OP ") for t9 in titles(r, "event")),
    "B 'OP' = 심볼 OP 만('STOP' 아님 — 외부 재검토 재현)", titles(r, "event") + titles(r, "coin"))
r = S("ＢＴＣ")
chk(grp(r, "coin") and titles(r, "coin")[0] == "BTC", "B 'ＢＴＣ'(전각) = BTC 찾음(외부 재검토 재현 0건)", r if not isinstance(r, dict) else r.get("groups"))
r = S(unicodedata.normalize("NFD", "브릿지 자금"))
chk(grp(r, "memo") or grp(r, "event"), "B 자모 분리형 '브릿지 자금' = 메모·기록 찾음(외부 재검토 재현 0건)", r if not isinstance(r, dict) else [g["kind"] for g in r.get("groups") or []])
r = S("7vHtM3")
w9 = grp(r, "wallet")
chk(w9 and [i["addr"] for i in w9["items"]] == [SOLA] and not grp(r, "deposit"), "B 솔라나 앞부분 '7vHtM3' = 그 지갑(·그 지갑 tx)만(대소문자 다른 7vHtm3… 입금 주소 아님)",
    r if not isinstance(r, dict) else [(g["kind"], [i.get("addr") for i in g["items"]]) for g in r.get("groups") or []])
r = S("7vHtm3")
chk(grp(r, "deposit") and [i["addr"] for i in grp(r, "deposit")["items"]] == [SOLA2], "B 솔라나 앞부분 '7vHtm3' = 그 입금 주소만", r if not isinstance(r, dict) else r.get("groups"))
r = S(SOLS[:8])
chk(grp(r, "tx") and grp(r, "tx")["items"][0]["tx"] == SOLS, "B 솔라나 서명 앞 8자 = 그 tx", r if not isinstance(r, dict) else r.get("groups"))
r = S(H64)
chk(grp(r, "tx") and grp(r, "tx")["items"][0]["tx"] == HB, "B 0x 없는 64자리 = 그 tx(외부 재검토 재현 못 찾음)", r if not isinstance(r, dict) else r.get("groups"))
r = S("0x5ea7...f00d")
chk(grp(r, "tx") and grp(r, "tx")["items"][0]["tx"] == HB and grp(r, "event"), "B '0x5ea7...f00d' = 그 tx + 줄인 해시 기록(외부 재검토 재현 못 찾음)", r if not isinstance(r, dict) else r.get("groups"))
r = S("005930")
chk(grp(r, "other") and titles(r, "other") == ["삼성전자"], "B '005930' = 종목코드 글자로도 찾음(외부 재검토 재현 0건)", r if not isinstance(r, dict) else r.get("groups"))
r = S("9999-12")
chk(isinstance(r, dict) and r.get("ok") and "_exc" not in r and any(x.get("t") == "9999-12" for x in r.get("ignored") or []), "B '9999-12' = 503 아님 · 결과 없음으로 숨기지 않고 '범위 밖' 안내", r)
r = S("x", before="9999-12")
chk(isinstance(r, dict) and r.get("ok") and r.get("ignored"), "B before=9999-12(요청 인자) = 예외 없음 · 안내", r)
for q9 in ("비트", "ㅂㅌ", "비트코"):
    r = S(q9)
    chk(grp(r, "coin") and titles(r, "coin")[0] == "BTC", f"B '{q9}' = BTC 코인 먼저(외부 재검토 재현 못 찾음 · BCH 는 뒤)", r if not isinstance(r, dict) else titles(r, "coin"))
r = S("coin:ZZZ", limit=30)
g9 = grp(r, "event")
chk(g9 and g9["n"] == 120 and len(g9["items"]) == 30 and g9.get("more") is True, "B 30건 잘림 = n 120(전체 건수) · more", g9 and {k: g9[k] for k in g9 if k != "items"})
r2 = S("coin:ZZZ", limit=30, offset=30)
g2 = grp(r2, "event")
k1 = {i["id"] for i in g9["items"]} if g9 else set()
chk(g2 and len(g2["items"]) == 30 and not (k1 & {i["id"] for i in g2["items"]}) and g2.get("offset") == 30, "B 다음 쪽(offset 30) = 겹치지 않는 30건", g2 and {k: g2[k] for k in g2 if k != "items"})
r3 = S("coin:ZZZ", limit=50, offset=100)
g3 = grp(r3, "event")
chk(g3 and len(g3["items"]) == 20 and g3.get("more") is False, "B 마지막 쪽 = 남은 20건 · more 없음", g3 and {k: g3[k] for k in g3 if k != "items"})
tk = {"t": 0.0}


def slow_clock():
    tk["t"] += 1.5
    return tk["t"]


r = safe(si.search, "coin:ZZZ", today=TODAY, budget_s=0.1, clock=slow_clock)
chk(isinstance(r, dict) and r.get("ok") and r.get("partial"), "B 시간 초과 = partial(화면 '일부만')", r)
r = S("sol")
c9 = titles(r, "coin")
chk(c9[:2] == ["SOL", "SOLV"], "B 순위 'sol' 코인 = SOL(정확) → SOLV(앞부분)", c9)
eg = grp(r, "event")


def tier_of(it):
    s9 = (it.get("sym") or "").upper()
    return 0 if s9 == "SOL" else (1 if s9.startswith("SOL") or it["title"].lower().startswith("sol") else 2)


tiers = [(tier_of(i), -(i.get("ts") or 0)) for i in (eg["items"] if eg else [])]
chk(eg and tiers == sorted(tiers) and tiers[0][0] == 0 and any(t9[0] == 2 for t9 in tiers), "B 순위 'sol' 기록 = 심볼 SOL → 앞부분 SOLV → 부분(설명의 Solana) · 묶음 안 최신순", tiers)
r = S("coin:ETH -type:gas")
chk(grp(r, "event") and not any("가스" in t9 for t9 in titles(r, "event")) and any("가스" in t9 for t9 in titles(S("coin:ETH"), "event")),
    "B -type:gas = 가스 기록 빼기", titles(r, "event"))
r = S("wallet:hot7")
chk(grp(r, "event") and all(i.get("addr") == SOLA for i in grp(r, "event")["items"]), "B wallet:hot7 = 그 지갑 기록만", r if not isinstance(r, dict) else [(g["kind"], g["n"]) for g in r.get("groups") or []])
r = S("wallet:없는별명")
chk(isinstance(r, dict) and any("wallet" in x.get("t", "") for x in r.get("ignored") or []), "B 없는 지갑 별명 = '이 조건은 무시했어요'", r)
r = S("ex:upbit")
chk(grp(r, "event") and all("업비트" in s9 for s9 in subs(r, "event")) and grp(r, "deposit"), "B ex:upbit = 업비트 기록·입금 주소", r if not isinstance(r, dict) else [(g["kind"], g["n"]) for g in r.get("groups") or []])
r = S("has:memo")
chk(grp(r, "memo") and grp(r, "event") and titles(r, "event") == ["BTC 온체인 매도"] and grp(r, "outflow"), "B has:memo = 메모 · 그날 그 코인 기록 · 메모 있는 보낸 내역", r if not isinstance(r, dict) else [(g["kind"], g["n"]) for g in r.get("groups") or []])
r = S("foo:bar ETH")
chk(isinstance(r, dict) and any(x.get("t") == "foo:bar" for x in r.get("ignored") or []) and grp(r, "event"), "B 모르는 조건 foo:bar = 버리고 안내 · 나머지(ETH)로 찾음", r if not isinstance(r, dict) else r.get("ignored"))
r = S("after:2026-09-01 before:2026-09-30 chain:base type:sell pnl:<0")
chk(titles(r, "event") == ["BTC 온체인 매도"] and grp(r, "event")["items"][0].get("usd") == 450.0, "B 9월 Base 손해 본 매도 = 그 건(건별 손익 −52 — 종전 0건)", r if not isinstance(r, dict) else r.get("groups"))
r = S("after:2026-09-01 before:2026-09-30 chain:base type:sell pnl:>0")
chk(titles(r, "event") == ["ETH 온체인 매도"], "B 9월 Base 이익 본 매도 = ETH(+29) 만", titles(r, "event"))
c9 = sqlite3.connect(IDX.ix.path)
pn = c9.execute("SELECT pnl FROM docs WHERE kind='event' AND title='BTC 온체인 매도'").fetchone()
c9.close()
chk(pn and pn[0] == -52.0, "B 건별 손익 = 양도 450 − 취득 500 − 수수료 2 = −52(그 사이클 그날 실현 999 아님)", pn)

N_TX = 2600
conn = sqlite3.connect(L)
for i in range(N_TX):
    hx = "0x" + format(i, "064x")
    conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event, classifier_ver)"
                 " VALUES ('chain_tx', 'base', ?, 0, ?, 1, ?, '1', '5.0', NULL, 'acq', 'TRANSFER_IN', 1)", (hx, ts_of("2026-07-01") + i, f"wallet:base:{SP_WAL}"))
conn.commit()
conn.close()
IDX.tick()
c9 = sqlite3.connect(IDX.ix.path)
n_tx0 = c9.execute("SELECT count(*) FROM docs WHERE kind='tx'").fetchone()[0]
c9.close()
probe = {"min": None, "n": 0}


def count_tx():
    c = sqlite3.connect(f"file:{IDX.ix.path}?mode=ro", uri=True, timeout=5)
    try:
        return c.execute("SELECT count(*) FROM docs WHERE kind='tx'").fetchone()[0]
    finally:
        c.close()


def probe_sleep(s):
    n = count_tx()
    probe["n"] += 1
    probe["min"] = n if probe["min"] is None else min(probe["min"], n)


conn = sqlite3.connect(L)
conn.execute("DELETE FROM postings WHERE source_id = ?", ("0x" + format(5, "064x"),))
conn.execute("UPDATE postings SET cost_usd = '6.0' WHERE cost_usd = '5.0'")
conn.commit()
conn.close()
IDX.ix.sleep = probe_sleep
IDX.sleep = probe_sleep
IDX.tick()
IDX.ix.sleep = IDX.sleep = (lambda s: None)
n_tx1 = count_tx()
chk(n_tx1 == n_tx0 - 1, f"C 옛 거래 재계산(행 줄어듦) 뒤 tx {n_tx0} → {n_tx1}(하나만 빠짐)")
chk(probe["min"] is None or probe["min"] >= n_tx0 - 1, f"C 재계산 중 다른 연결이 본 tx 최소 {probe['min']}건(탐침 {probe['n']}회) — 0건·일부만 없음(외부 재검토 재현 22초 빔)", probe)
stop = {"v": False}
seen = []


def reader():
    while not stop["v"]:
        r9 = si.search("coin:ZZZ", today=TODAY, path=IDX.ix.path, budget_s=5)
        g9 = grp(r9, "event")
        seen.append(g9["n"] if g9 else 0)


th = threading.Thread(target=reader, daemon=True)
th.start()
time.sleep(0.2)
IDX.last_full = time.time() - si.FULL_EVERY_S - 10
for _ in range(3):
    IDX.last_full = time.time() - si.FULL_EVERY_S - 10
    IDX.tick()
time.sleep(0.2)
stop["v"] = True
th.join(10)
chk(seen and min(seen) == 120, f"C 6시간 대조 3회 중 동시 조회 {len(seen)}번 = 늘 120건(최소 {min(seen) if seen else None})", sorted(set(seen))[:10])
wal = os.path.getsize(IDX.ix.path + "-wal") if os.path.exists(IDX.ix.path + "-wal") else 0
print(f"     정보: 6시간 대조 뒤 WAL {wal / 1e6:.2f}MB · 본체 {os.path.getsize(IDX.ix.path) / 1e6:.2f}MB")
shutil.copy2(L, L + ".new")
os.replace(L + ".new", L)
probe.update(min=None, n=0)
IDX.ix.sleep = probe_sleep
IDX.tick()
IDX.ix.sleep = lambda s: None
chk(count_tx() == n_tx1 and (probe["min"] is None or probe["min"] >= n_tx1), "C 원장 교체(새 inode) = 대조만 · 빔 없음", probe)

if NEW:
    OLD = os.path.join(TMP, "old_search.db")
    oc = sqlite3.connect(OLD)
    oc.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    oc.execute("""CREATE TABLE docs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE, grp TEXT NOT NULL, title TEXT NOT NULL, sub TEXT, body TEXT,
               date TEXT, ts INTEGER, usd REAL, pnl REAL, sym TEXT, sym_u TEXT, chain TEXT, chain_l TEXT, etype TEXT, addr TEXT, addr_l TEXT, tx TEXT, tx_l TEXT,
               anc TEXT, spam INTEGER NOT NULL DEFAULT 0, syms TEXT, chains TEXT)""")
    oc.execute("CREATE VIRTUAL TABLE fts USING fts5(title, sub, body, tokenize='trigram')")
    for i in range(50):
        cur = oc.execute("INSERT INTO docs (kind, key, grp, title, sub, body, date, ts, sym, sym_u, chain, chain_l, etype, spam, syms, chains) "
                         "VALUES ('event', ?, ?, ?, ?, '', ?, ?, 'ZZZ', 'ZZZ', '업비트', '업비트', 'buy', 0, ' ZZZ ', ' 업비트 ')",
                         (f"ev:old:{i}", "ev:" + ZD, "ZZZ 거래소 매수", "옛 형식 행", ZD, ts_of(ZD) + i))
        oc.execute("INSERT INTO fts (rowid, title, sub, body) VALUES (?, 'ZZZ 거래소 매수', '옛 형식 행', '')", (cur.lastrowid,))
    oc.executemany("INSERT INTO meta VALUES (?, ?)", [("schema", "2"), ("fts", "1"), ("built", "1")])
    oc.commit()
    oc.close()
    r = si.search("coin:ZZZ", today=TODAY, path=OLD, budget_s=5)
    chk(grp(r, "event") and grp(r, "event")["n"] == 50 and r.get("upgrading"), "D 옛 형식(패싯 표 없음) = 종전 열로 50건 · upgrading 표시", r)
    IX2 = si.Indexer(lambda: (state["out"], state["dix"]), nft_fn=lambda: {}, chain_names=CN, path=OLD, ledger_path=L, sleep=lambda s: None)
    IX2.ix.open()
    oc = sqlite3.connect(OLD)
    cols = [r9[1] for r9 in oc.execute("PRAGMA table_info(docs)")]
    has_tg = bool(oc.execute("SELECT 1 FROM sqlite_master WHERE name='tg'").fetchone())
    oc.close()
    chk("h" in cols and has_tg and str(IX2.ix.rowv) != str(si.ROWV), "D 열기 = 열 더하기(h)·패싯 표 만들기(파일 지우지 않음) · 아직 옛 형식", [cols[-3:], has_tg, IX2.ix.rowv])
    r = si.search("coin:ZZZ", today=TODAY, path=OLD, budget_s=5)
    chk(grp(r, "event") and grp(r, "event")["n"] == 50, "D 바꾸기 전 = 옛 행도 종전 조건으로 찾음(빈 결과 없음)", r)
    IX2.tick()
    oc = sqlite3.connect(OLD)
    nul = oc.execute("SELECT count(*) FROM docs WHERE h IS NULL").fetchone()[0]
    rv = oc.execute("SELECT v FROM meta WHERE k='rowv'").fetchone()
    oc.close()
    r = si.search("coin:ZZZ", today=TODAY, path=OLD, budget_s=5)
    chk(nul == 0 and rv and rv[0] == str(si.ROWV) and grp(r, "event")["n"] == 120 and not r.get("upgrading"),
        "D 한 회차 뒤 = 새 형식 완료(옛 행 정리 · rowv) · 새 규칙으로 120건", [nul, rv, grp(r, "event") and grp(r, "event")["n"], r.get("upgrading")])
else:
    chk(False, "D 옛 형식 → 새 형식(수정 전 코드엔 없음)")

def old_db(path, rows):
    oc = sqlite3.connect(path)
    oc.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    oc.execute("""CREATE TABLE docs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE, grp TEXT NOT NULL, title TEXT NOT NULL, sub TEXT, body TEXT,
               date TEXT, ts INTEGER, usd REAL, pnl REAL, sym TEXT, sym_u TEXT, chain TEXT, chain_l TEXT, etype TEXT, addr TEXT, addr_l TEXT, tx TEXT, tx_l TEXT,
               anc TEXT, spam INTEGER NOT NULL DEFAULT 0, syms TEXT, chains TEXT)""")
    oc.execute("CREATE VIRTUAL TABLE fts USING fts5(title, sub, body, tokenize='trigram')")
    for kind, key, grp, title, sub, sym, chain, etype, ts in rows:
        cur = oc.execute("INSERT INTO docs (kind, key, grp, title, sub, body, date, ts, sym, sym_u, chain, chain_l, etype, spam, syms, chains) "
                         "VALUES (?, ?, ?, ?, ?, '', '2026-09-01', ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                         (kind, key, grp, title, sub, ts, sym, (sym or "").upper() or None, chain, (chain or "").lower() or None, etype,
                          (" " + sym.upper() + " ") if sym else None, (" " + chain.lower() + " ") if chain else None))
        oc.execute("INSERT INTO fts (rowid, title, sub, body) VALUES (?, ?, ?, '')", (cur.lastrowid, title, sub))
    oc.executemany("INSERT INTO meta VALUES (?, ?)", [("schema", "2"), ("fts", "1"), ("built", "1")])
    oc.commit()
    oc.close()


if NEW:
    OLD2 = os.path.join(TMP, "old2_search.db")
    old_db(OLD2, [("event", f"ev:o:{i}", "ev:2026-09-01", "ZZZ 거래소 매수", "업비트", "ZZZ", "업비트", "buy", ts_of("2026-09-01") + i) for i in range(3)]
           + [("wallet", "w:o", "st:wallet", "콜드 0xaaaa", "Ethereum", None, None, None, None), ("nft", "nft:o", "nft", "SolBear", "Solana", None, "Solana", None, None)])
    IX3 = si.Indexer(None, None, chain_names=CN, path=OLD2, ledger_path=os.path.join(TMP, "no_ledger.db"), sleep=lambda s: None)
    IX3.tick()
    oc = sqlite3.connect(OLD2)
    left = dict(oc.execute("SELECT kind, count(*) FROM docs GROUP BY kind").fetchall())
    rv3 = oc.execute("SELECT v FROM meta WHERE k='rowv'").fetchone()
    oc.close()
    chk(left.get("event") == 3 and left.get("wallet") == 1 and left.get("nft") == 1 and not rv3,
        "D2 n4 원천 없는 색인기(상태·NFT·원장 없음) = 옛 이벤트·지갑·NFT 행 그대로 · 형식 완료 표시 안 함", [left, rv3])
    r = si.search("coin:ZZZ", today=TODAY, path=OLD2, budget_s=5)
    chk(grp(r, "event") and grp(r, "event")["n"] == 3 and r.get("upgrading"), "D2 n4 남은 옛 행 = 종전 조건으로 계속 찾음(upgrading)", r if not isinstance(r, dict) else r.get("groups"))
    OLD3 = os.path.join(TMP, "old3_search.db")
    old_db(OLD3, [("tx", "tx:robinhood:0x1", "tx:robinhood", "tx 0x1", "받음 · Robinhood", "USDG", "robinhood", "deposit", ts_of("2026-09-01"))])
    r = si.search("chain:robinhood", today=TODAY, path=OLD3, budget_s=5)
    chk(isinstance(r, dict) and r.get("ok") and grp(r, "tx") and grp(r, "tx")["n"] == 1, "D2 n7 tg 없는 옛 색인 chain:robinhood = 오류 없이 1건", r)
    SNP = os.path.join(TMP, "snap_search.db")
    IX4 = si.Index(SNP, sleep=lambda s: None)
    IX4.replace_groups(["g:s"], [{"kind": "event", "key": "ev:s:0", "grp": "g:s", "title": "QQQ 거래소 매수", "sym": "QQQ", "etype": "buy", "ts": 1, "tys": ["buy"]}])
    with IX4.tx() as c9:
        c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(si.ROWV),))
        c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('built', '1')")
    calls = {"n": 0, "w": False}

    def snap_clock():
        calls["n"] += 1
        if calls["n"] == 2 and not calls["w"]:
            calls["w"] = True
            IX4.replace_groups(["g:s"], [{"kind": "event", "key": f"ev:s:{i}", "grp": "g:s", "title": "QQQ 거래소 매수", "sym": "QQQ", "etype": "buy", "ts": 1 + i,
                                          "tys": ["buy"]} for i in range(3)])
        return 0.0
    r = si.search("coin:QQQ type:buy", today=TODAY, path=SNP, budget_s=5, clock=snap_clock)
    g9 = grp(r, "event")
    chk(calls["w"] and g9 and g9["n"] == len(g9["items"]), f"D2 n6 검색 도중 교체가 끼어도 n·항목 = 같은 스냅숏(n {g9 and g9['n']} · 항목 {g9 and len(g9['items'])})", g9 and {k: g9[k] for k in g9 if k != 'items'})
    ix5 = {D1: [(ts_of(D1, "15:00"), "pos", ev(ts_of(D1, "15:00"), "ETH", "온체인 매도", "Base · 정산액 산정 중", a="—", _tax=None), ("gETH", "ETH", "Base"))]}
    dd = si.docs_events(ix5, {"gETH": {D1: 28.0}}, CN, D1)
    chk(dd and dd[0]["pnl"] is None, "D2 n5 정산액 미상 매도(_tax None) = 손익 없음(그날 실현 28 붙이지 않음)", dd and dd[0]["pnl"])
    wsrc = open(os.path.join(SRC, "web.py"), encoding="utf-8").read()
    i9 = wsrc.find('· 정산액 산정 중"')
    chk(i9 > 0 and '["_tax"] = None' in wsrc[i9:i9 + 600], "D2 n5 web.py 정산액 산정 중 매도 기록에 _tax=None", i9)
else:
    chk(False, "D2(수정 전 코드엔 없음)")

W = ['"', "'", "`", "\\", "(", ")", "((", "))", "[", "]", "{", "}", "*", "-", "+", "^", ":", "::", "NEAR(", "NEAR(a b)", "a NEAR b", "AND", "OR", "NOT",
     "a AND", "OR b", '" * NEAR(', "'; DROP TABLE docs; --", "1' OR '1'='1", "%", "_", "%_%", "\\%", "\x00", "\x00abc", "abc\x00def", "😀", "🐱‍👤", "ETH🚀",
     "👨‍👩‍👧‍👦" * 50, "x" * 5000, "가" * 5000, "ᄇᄐ", "ＢＴＣ", "Ｅ Ｔ Ｈ", "\u200b", "e\u0301", "\u202eRTL", "<script>alert(1)</script>", "<mark>x</mark>",
     "</mark><script>", "&lt;", "${7*7}", "{{7*7}}", "../../etc/passwd", "C:\\Windows", "\r\n", "\t", "   ", "", "coin:", "coin:'", "chain:%", "chain:'--",
     "type:", "type:'", "type:sell'", "after:", "after:'", "after:9999-99-99", "after:0000-00", "after:-1", "before:99999", "pnl:", "pnl:<<0", "pnl:abc",
     "amt:>", "amt:1e309", "amt:-0", "amt:999999999999999999999", "addr:", "addr:%", "addr:0x%", "tx:'", "wallet:", "wallet:%", "wallet:'", "ex:", "ex:%",
     "has:", "has:'", "-", "-type:", "-:", "--type:gas", "-foo:bar", "foo:bar", "http://x.y/z", "a:b:c", "0x", "0x...", "...", "…", "0x3c7e...cd34",
     "0x3c7e…", "…cd34", "0xZZZZ", "0x" + "f" * 200, "f" * 64, "F" * 64, "1" * 64, "9999-12", "10000-01", "2026-13", "2026-02-30", "0-0", "00-00", "13/40",
     "99월 99일", "어제어제", "지난주 지난주", "005930", "0", "00000", "1e10", "-1000", "$", "$$", "₩", "₩500만", "1,2,3", "1..2", "NaN", "Infinity",
     "null", "undefined", "true", "ㅂ", "ㅂㅌ", "ㅂㅌㅋㅇㅂㅌㅋㅇ", "비트" * 100, "SOL" * 100, " ".join(["sol"] * 40), " ".join(["a"] * 100),
     "type:sell " * 30, "coin:ETH " * 30, "-type:gas " * 30, "chain:" + "x" * 300, "wallet:" + "가" * 300, "has:memo has:memo -has:memo",
     "after:2026-10-01 before:2026-09-01", "pnl:>0 pnl:<0", "amt:~0", "-wallet:hot7", "-ex:upbit -chain:base -coin:ETH", "ex:업비트 ex:빗썸",
     "7vHt" * 20, "1" * 31, "I0Ol", "0x" + "g" * 40, "0X" + "A" * 40, "SOL…", "…SOL", "a…b…c", "0x1...2...3", "ㄱ" * 200, "ᅡ" * 50, "\U0010ffff", "\ud7a3",
     "%00", "%27", "\u0000" * 20, "' OR 1=1 --", "UNION SELECT", "fts MATCH '*'", "ORDER BY 1", "LIMIT 1", "kind:coin", "in:보낸", "on:어제", "sym:ETH"]
errs, slow = [], []
for w in W:
    t0 = time.time()
    rr = S(w)
    dt = time.time() - t0
    bad = None
    if not isinstance(rr, dict) or "_exc" in rr:
        bad = rr
    elif not rr.get("ok"):
        bad = rr.get("error")
    else:
        try:
            json.dumps(rr, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            bad = repr(e)
        for g in rr.get("groups") or []:
            for it in g["items"]:
                hl = str(it.get("hl") or "")
                rest = hl.replace("<mark>", "").replace("</mark>", "")
                if "<mark" in rest or "</mark" in rest:
                    bad = ("hl", hl[:80])
    if bad is not None:
        errs.append((repr(w[:30]), str(bad)[:120]))
    if dt > si.QUERY_BUDGET_S + 1.5:
        slow.append((repr(w[:30]), round(dt, 2)))
chk(len(W) >= 150 and not errs, f"E 악의적 입력 {len(W)}종 = 오류·예외·주입 없음 · JSON 직렬화", errs[:10])
chk(not slow, "E 모든 입력 = 시간 제한 안(예산 + 1.5초)", slow[:10])

T.finish()
