#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

import paths, statefile  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import calcguard  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import netpace  # noqa: E402
import web  # noqa: E402

chk = T.chk
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
NOW = int(time.time())
DAY = 86400
W = NOW - 30 * DAY

c = dbm.open_db(paths.DB_PATH)
A = {}
for sym in ("AAA", "BBB", "CCC"):
    c.execute("INSERT INTO asset_groups (name) VALUES (?)", (sym,))
    gid = c.execute("SELECT group_id FROM asset_groups WHERE name=?", (sym,)).fetchone()[0]
    c.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed, group_id) VALUES ('exchange_currency',NULL,?,?,8,1,?)",
              ("upbit:" + sym, sym, gid))
    A[sym] = c.execute("SELECT last_insert_rowid()").fetchone()[0]


def post(ns, sid, t, sym, qty, usd, krw, lk, evk):
    c.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
              " classifier_ver) VALUES ('exchange',?,?,0,?,?,'exchange:upbit',?,?,?,?,?,4)",
              (ns, sid, t, A[sym], str(int(Decimal(str(qty)) * 10 ** 8)), None if usd is None else repr(float(usd)),
               None if krw is None else str(krw), lk, evk))


post("upbit:order", "B1", W + DAY, "AAA", 10, 100, 140000, "acq", "EX_BUY")
post("upbit:order", "B2", W + DAY, "BBB", 10, 100, "x", "acq", "EX_BUY")
post("upbit:deposit", "C1", W + 2 * DAY, "CCC", 5, None, None, "move_in", "EX_DEPOSIT")
post("upbit:order", "C2", W + 3 * DAY, "CCC", -5, 50, 70000, "disp", "EX_SELL")
c.commit()
c.close()

histcurve.DAYCLOSE.lookup = lambda spec, iso, now=None, w=0.0, ask=True, old=False: (None, "pending")
histcurve.DAYCLOSE.lookup._tj_test_mock = True
px = {"AAA": 10.0, "BBB": 10.0, "CCC": 10.0, "USDT": 1.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"upbit:{k}": v for k, v in px.items()}, "ex_ts": {f"upbit:{k}": NOW for k in px}}, open(paths.state("spot.json"), "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None

_OF_KEY = web.StateBuilder._of_key
INJECT = [True]


def bad_of_key(r9):
    if INJECT[0] and r9["source_id"] == "C1":
        raise RuntimeError("시험 주입 — 연결 후보 색인 실패")
    return _OF_KEY(r9)


web.StateBuilder._of_key = staticmethod(bad_of_key)


def build():
    statefile.atomic_write_json(paths.state("ui_prefs.json"), {"plans": {}, "ignored": []})
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def card(f, sym):
    return [p for p in f.get("positions") or [] if p.get("sym") == sym]


f = build()
a, b, cc = card(f, "AAA"), card(f, "BBB"), card(f, "CCC")
chk(len(b) == 1 and "krw_of" in str(b[0].get("calcErr") or ""), "E1 원화 원가 못 읽음 → BBB 카드 calcErr(krw_of 자리)", [{k: p.get(k) for k in ("sym", "calcErr", "costKrw")} for p in b])
chk(len(b) == 1 and b[0].get("costKrw") == 140000, "E1 숫자 무변 — 원화 원가 = 종전 폴백(그 시각 환율 $100 × ₩1,400)", [p.get("costKrw") for p in b])
chk(len(cc) == 1 and "of_cand" in str(cc[0].get("calcErr") or ""), "E2 연결 후보 색인 예외 → CCC 카드 calcErr(of_cand 자리)", [{k: p.get(k) for k in ("sym", "calcErr")} for p in cc])
chk(len(a) == 1 and "calcErr" not in a[0], "E3 정상 매수 카드 = calcErr 없음", [{k: p.get(k) for k in ("sym", "calcErr")} for p in a])
chk(len(a) == 1 and a[0].get("costKrw") == 140000, "E3 정상 카드 원화 원가 = 체결 원화 그대로", [p.get("costKrw") for p in a])

INJECT[0] = False
f2 = build()
cc2 = card(f2, "CCC")
chk(len(cc2) == 1 and "calcErr" not in cc2[0], "E3 예외 없는 다음 빌드 = 옛 표식 안 남음(CCC)", [{k: p.get(k) for k in ("sym", "calcErr")} for p in cc2])
chk(len(card(f2, "BBB")) == 1 and "krw_of" in str(card(f2, "BBB")[0].get("calcErr") or ""), "E3 손상 행은 다음 빌드에도 그대로 표식(BBB)")
chk(callable(getattr(calcguard, "row_err", None)), "calcguard.row_err 있음(계산 경로 삼킴 뒤 행 표식)")
chk("RuntimeError" in str((calcguard._SITES.get("view_b_replay:ReplayMixin._build_replay.of_cand") or {}).get("types")), "E2 of_cand 삼킴 = 주입한 예외(시험 함정 아님)")

jr = open(os.path.join(T.ROOT, "web", "v2", "tab_jrnl.js"), encoding="utf-8").read()
ap = open(os.path.join(T.ROOT, "web", "v2", "app.js"), encoding="utf-8").read()
chk("p.calcErr" in jr and "계산 오류" in jr, "E4 매매일지 카드 '계산 오류' 칩(calcErr)")
i9 = jr.find("계산 오류")
chk(i9 > 0 and 'kchip hi' in jr[max(0, i9 - 400):i9] and "pill e" not in jr[max(0, i9 - 400):i9], "E4 칩 = 노랑 kchip(빨강 pill e 아님)")
chk("ceLeg ? { calcErr: ceLeg.calcErr }" in ap, "E4 합친 카드(조각 여러 개)도 조각 calcErr 를 잇는다")
T.finish()
