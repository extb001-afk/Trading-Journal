#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

import coverage_limits as cl  # noqa: E402
import recon_adj  # noqa: E402

chk = T.chk
DAY = 86400
NOW = 1_800_000_000
BASE = os.path.join(T.TMP, "covbase")
os.makedirs(os.path.join(BASE, "state"), exist_ok=True)
json.dump({"backfill_since": "2026-01-01", "backfill_months": 5}, open(os.path.join(BASE, "config.json"), "w"))
EXF = {"okx": {"ext": {"fills_from": NOW - 100 * DAY}}, "binance": {"ext": {}}}
json.dump(EXF, open(os.path.join(BASE, "state", "exf_state.json"), "w"))
EXL = os.path.join(T.TMP, "exl.json")
json.dump({"exchanges": {"okx": {"spot_fills": {"bot_uses": True, "reason_ko": "합성 OKX 체결"}, "bills": {"bot_uses": True, "reason_ko": "합성 정산"}},
                         "binance": {"futures_income": {"bot_uses": True, "reason_ko": "합성 seed 문구(기록 시작부터)"},
                                     "futures_fills": {"bot_uses": False, "reason_ko": "합성 선물 체결"}}}}, open(EXL, "w"))
SPD = os.path.join(T.TMP, "spd.json")
json.dump({}, open(SPD, "w"))


def ledger():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE wallets (chain TEXT, address TEXT, label TEXT)")
    db.execute("CREATE TABLE postings (location TEXT, event_ts INTEGER, leg_kind TEXT)")
    db.execute("INSERT INTO postings VALUES ('exchange:okx', ?, 'move_in')", (NOW - 400 * DAY,))
    db.execute("INSERT INTO postings VALUES ('exchange:okx', ?, 'trade')", (NOW - 30 * DAY,))
    return db


calls = []


def gap_none(db, ex, now, st_ex=None, t0=None):
    calls.append((ex, now, st_ex, t0, db.execute("SELECT count(*) FROM postings").fetchone()[0]))
    return []


def gap_okx(db, ex, now, st_ex=None, t0=None):
    return [{"kind": "spot_fills", "t0": int(t0), "full_t0": NOW - 140 * DAY, "why": "합성 커서"}] if ex == "okx" else []


def build(fn):
    return cl.build(BASE, exl_path=EXL, speed_path=SPD, now=NOW, conn=ledger(), gap_fn=fn)


d = build(gap_none)
vg = [u for u in d["unavailable"] if u.get("venue_gap")]
chk(vg == [], "G1 거래가 없던 기간(첫 체결 행 늦음) ≠ 빈 구간 — 원장 첫 행으로 짐작하지 않음(venue_gap 이 비면 줄 없음)", vg)
tgt = cl._ts(d["window_start"])
chk(sorted(c9[0] for c9 in calls) == ["binance", "okx"] and all(c9[1] == NOW and c9[2] == EXF[c9[0]] and c9[3] == tgt and c9[4] == 2 for c9 in calls),
    "G1 부르는 인자 = (원장 연결, 거래소, now, st_ex = exf_state[거래소], t0 = 수집 창 시작)", calls)
d = build(gap_okx)
vg = [u for u in d["unavailable"] if u.get("venue_gap")]
chk(len(vg) == 1 and vg[0]["source_id"] == "exchange:okx:spot_fills" and vg[0]["severity"] == "partial" and vg[0]["from"] == d["window_start"]
    and vg[0]["before"] == cl._d(NOW - 140 * DAY) and "빈 구간" in vg[0]["reason_ko"] and "합성 커서" in vg[0]["reason_ko"],
    "G1 빈 구간 = unavailable 일부 누락 가능 · 시작(창 시작)·끝(그 종류 수집 하한) 날짜", vg)


def boom(*a, **k):
    raise RuntimeError("합성 실패")


d2 = build(boom)
chk(not [u for u in d2["unavailable"] if u.get("venue_gap")] and d2["sources"], "G1 빈 구간 판정 실패 = 줄 없음(패널은 계속)")
d3 = build(lambda *a, **k: [{"kind": "spot_fills", "t0": NOW, "full_t0": NOW - DAY}, {"kind": "x"}, "깨짐"])
chk(not [u for u in d3["unavailable"] if u.get("venue_gap")], "G1 끝 ≤ 시작 · 칸 빠짐 · 꼴 다름 = 줄 없음")
json.dump(d, open(os.path.join(BASE, "state", "coverage_limits.json"), "w"))
cg = recon_adj.coverage_gaps(os.path.join(BASE, "state"))
chk("okx" in cg and "binance" in cg, "G1 보정 감시 coverage_gaps 가 빈 구간·한도 줄을 읽음(장소)", sorted(cg))

import exf_binance  # noqa: E402
src = {s9["id"]: s9 for s9 in d["sources"]}
un = {u["source_id"]: u for u in d["unavailable"] if not u.get("venue_gap")}
chk(cl.ROLLING_DAYS[("binance", "futures_income")] == exf_binance.BN_INCOME_KEEP_DAYS and src["exchange:binance:futures_income"].get("rolling_limit_days") == 364,
    "G2① 바이낸스 선물 손익 = 봇 하한 364일(BN_INCOME_KEEP_DAYS)", src["exchange:binance:futures_income"].get("rolling_limit_days"))
chk(un["exchange:binance:futures_income"]["reason_ko"] == cl.ROLLING_REASON[("binance", "futures_income")] and "364" in un["exchange:binance:futures_income"]["reason_ko"]
    and un["exchange:binance:futures_income"]["before"] == cl._d(NOW - 364 * DAY), "G2① 사유 = 봇 기준(seed '기록 시작부터' 아님) · 이전 날짜", un["exchange:binance:futures_income"])
chk(cl.ROLLING_DAYS[("binance", "futures_fills")] == 180 and un["exchange:binance:futures_fills"]["reason_ko"] == "합성 선물 체결", "G2② 바이낸스 선물 체결 180일 그대로(seed 문구)")
import ex_foreign  # noqa: E402
chk(all(ex_foreign.ext_fills_floor("okx", t9) == cl.okx_floor(t9) for t9 in (NOW, NOW + 40 * DAY, NOW + 200 * DAY)),
    "G2③ OKX 체결 하한 = 달력 규칙(표의 90일 값은 쓰이지 않음 · 수집 한계와 같은 함수 값)")
chk("89일" in (src["exchange:okx:bills"].get("bot_limit_ko") or ""), "G2④ OKX 정산 이어받기 89일 = bot_limit_ko", src["exchange:okx:bills"].get("bot_limit_ko"))
mg = [u for u in d["unavailable"] if u["source_id"] == "exchange:okx:margin_fills"]
chk(len(mg) == 1 and mg[0]["severity"] == "bot_cap" and "SPOT" in mg[0]["reason_ko"], "G2⑤ OKX 마진 체결 미수집 = 봇 한계 줄", mg)
chk(cl.CHAIN_TRACKS["robinhood"]["limit_kind"] == "state_recent" and "10분" in cl.CHAIN_TRACKS["robinhood"]["reason_ko"], "G2⑥ robinhood 과거 상태 10분 = limit_kind state_recent")

T.finish()
