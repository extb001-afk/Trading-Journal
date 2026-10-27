#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import sqlite3  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import health  # noqa: E402
import health_ack  # noqa: E402
import recon_adj  # noqa: E402
import recon_auto  # noqa: E402

chk = T.chk
NOW = 1_800_000_000
DAY = 86400
HS = health.settings({"health": {"units": ["tj-core"]}})


def ev(doc):
    obs = {"now": NOW, "pm2": {"tj-core": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "hb": {"core": {"ts": NOW, "ok": True}}, "recon_adj": doc}
    return {x["id"]: x for x in health.evaluate(obs, HS)}.get("ledger:adj")


AUTO_ROW = {"venue": "okx", "loc": "exchange:okx", "sym": "TKJ", "q": -100.0, "usd": -100.0, "ts": NOW - 50 * DAY, "made": NOW - DAY, "site": recon_auto.SITE_AUTO,
            "why": "", "cls": "auto", "red": None, "cause": ""}
NEG = {"cells": 3, "runs": 4, "max_days": 41.0, "min_days": 7, "venues": {"okx": 3}}
base = recon_adj.summarize([], now=NOW)
plain = ev(base)
doc = recon_adj.summarize([], now=NOW, neg=NEG)
doc["gray"] = dict(doc["gray"], auto=[AUTO_ROW], auto_n=1)
doc["check"] = recon_adj.check(doc, NOW)
h1 = ev(doc)
chk(h1["level"] == "ok" and not h1["notify"] and h1["detail"].startswith(plain["detail"] + " · 참고: ") and "자동 처리 1칸(TKJ okx −$100" in h1["detail"]
    and "창 안 음수 구간 3칸(7일 넘게 · 가장 긴 41일)" in h1["detail"], "H1 정상 + 회색 줄 = ok · 상세 뒤 참고 · 알림 없음", h1)
chk(plain["detail"] == base["check"]["detail"] and "참고" not in plain["detail"], "H2 회색 줄 없으면 상세 무변(종전 글자)", plain["detail"])
red = dict(doc, red_n=1, red_by={"prewin_rows": 1}, red=[dict(AUTO_ROW, site="K7", cls="estimated", red="prewin_rows", cause="합성")])
red["check"] = recon_adj.check(red, NOW)
h2 = ev(red)
chk(h2["level"] == "crit" and h2["notify"] and "참고: " in h2["detail"] and h2["title"] == red["check"]["title"], "H2 빨강 + 회색 줄 = 빨강·알림 그대로 · 참고 붙음", h2)
wn = dict(doc, warn_n=1, warn_auto_n=1, warn=[dict(AUTO_ROW, usd=-15000.0)], auto=dict(doc["auto"], n=1, n7=1, usd=15000.0, usd7=15000.0))
wn["check"] = recon_adj.check(wn, NOW)
h3 = ev(wn)
chk(h3["level"] == "warn" and h3.get("tg_force") is True and "참고: " in h3["detail"], "H2 큰 자동 처리 노랑 + 회색 줄 = 노랑·텔레그램 그대로", (h3["level"], h3.get("tg_force")))
chk("ledger:adj" not in health_ack.ACKABLE, "H3 ledger:adj 는 닫기 대상 아님(큰 자동 처리 노랑도)")
bad = dict(doc, check=dict(doc["check"], info="글자"))
bad2 = dict(doc, check=dict(doc["check"], info=[3, None, ""]))
chk(ev(bad)["detail"] == plain["detail"] and ev(bad2)["detail"] == plain["detail"], "H5 info 칸 손상 = 무시", (ev(bad)["detail"], ev(bad2)["detail"]))

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE assets (asset_id INTEGER, symbol TEXT, decimals INTEGER)")
db.execute("CREATE TABLE postings (location TEXT, asset_id INTEGER, event_ts INTEGER, qty_base TEXT)")
db.executemany("INSERT INTO assets VALUES (?,?,?)", [(1, "TKA", 8), (2, "TKB", 8), (3, "TKC", 8), (4, "KRW", 0), (5, "TKD", 8), (6, "tka", 6)])
W0 = NOW - 150 * DAY
P = [("exchange:okx", 1, W0 + 10 * DAY, -5 * 10 ** 8), ("exchange:okx", 1, W0 + 25 * DAY, 3 * 10 ** 8), ("exchange:okx", 6, W0 + 25 * DAY, 2 * 10 ** 6),
     ("exchange:okx", 2, W0 + 10 * DAY, -10 ** 8), ("exchange:okx", 2, W0 + 12 * DAY, 10 ** 8),
     ("exchange:okx", 3, W0 - 30 * DAY, -10 ** 8), ("exchange:okx", 3, W0 + 20 * DAY, 10 ** 8),
     ("exchange:okx", 5, W0 + 30 * DAY, -10 ** 8),
     ("exchange:upbit", 4, W0 + 10 * DAY, -10 ** 6), ("exchange:upbit", 4, W0 + 60 * DAY, 10 ** 6),
     ("exchange:bybit", 1, W0 + 40 * DAY, -10 ** 8), ("exchange:bybit", 1, W0 + 40 * DAY + 3600, 10 ** 7), ("exchange:bybit", 1, W0 + 90 * DAY, 9 * 10 ** 7)]
db.executemany("INSERT INTO postings VALUES (?,?,?,?)", [(a, b, c9, str(d9)) for a, b, c9, d9 in P])
before = db.execute("SELECT count(*), group_concat(qty_base) FROM postings").fetchone()
nr = recon_auto.neg_runs(db, {"okx": W0, "bybit": W0, "upbit": W0})
chk(nr["cells"] == 2 and nr["runs"] == 2 and nr["venues"] == {"bybit": 1, "okx": 1} and nr["max_days"] == 50.0,
    "H4 7일 넘는 회복 구간만(같은 심볼 자산 합 · 창 앞 시작·지금 음수·원화 뺌)", nr)
chk(recon_auto.neg_runs(db)["cells"] == 3, "H4 창 시작 모름 = 창 앞 시작 구간도 셈(t0 없음)", recon_auto.neg_runs(db))
def _t0_boom(v):
    raise RuntimeError("합성 창 시작 실패")


nr2 = recon_auto.neg_runs(db, {"bybit": W0, "upbit": W0}, t0_of=lambda v: W0)
chk(nr2 == nr, "H4 (s32w4_2 HIGH) 보정 줄 없는 장소 = 창 시작 함수로 보완(창 앞 시작 구간 뺌)", nr2)
chk(recon_auto.neg_runs(db, {"bybit": W0, "upbit": W0}, t0_of=_t0_boom)["cells"] == 3, "H4 창 시작 함수 실패(바깥 오류) = 비교 없음(삼킴)")
chk(db.execute("SELECT count(*), group_concat(qty_base) FROM postings").fetchone() == before, "H4 원장 무변(읽기만)")

T.finish()
