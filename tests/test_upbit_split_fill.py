#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal as D  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import config  # noqa: E402
import core  # noqa: E402
import core_fills as CF  # noqa: E402
import db as dbm  # noqa: E402
import ledger_rowfix as LRF  # noqa: E402

chk = T.chk
DAY = 86400
T0 = 1767225600 - 30 * DAY
FX = {"f": lambda ms: 1000.0}

C = core.Core(config.load_config())
C.px.fx_at = lambda ms: FX["f"](ms)
S = C.svc_exf


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def order(uid, side, fills, fee="0", market="KRW-ETH", tuuid=True, **kw):
    tr = [dict({"market": market, "side": side, "created_at": iso(t), "volume": q, "funds": str(D(q) * D(p)), "price": p},
               **({"uuid": f"{uid}-t{i}"} if tuuid else {})) for i, (t, q, p) in enumerate(fills)]
    o = {"uuid": uid, "market": market, "side": side, "state": "done", "ord_type": "limit",
         "executed_volume": str(sum(D(q) for _t, q, _p in fills)), "executed_funds": str(sum(D(x["funds"]) for x in tr)),
         "paid_fee": fee, "created_at": iso(min(t for t, _q, _p in fills)), "trades": tr, "trades_count": len(tr)}
    o.update(kw)
    return o


def legs(u):
    return [tuple(r) for r in C.conn.execute("SELECT leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event"
                                             " FROM postings WHERE source_ns='upbit:order' AND source_id=? ORDER BY leg_seq", (u,))]


def pos():
    return sorted(tuple(r) for r in C.conn.execute("SELECT group_id, location, qty_norm FROM positions"))


def post(*os_, nosplit=False):
    S._consume_fills({"orders": list(os_)}, nosplit=nosplit)
    C.conn.commit()


def meta(k):
    r = C.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else None


E8 = 10 ** 8
rev0 = dbm.ledger_data_rev(C.conn)
o_one = order("one", "bid", [(T0, "1", "100000")])
o_same = order("same", "bid", [(T0 + 10, "0.4", "100000"), (T0 + 10, "0.6", "100000")])
post(o_one, o_same)
post(dict(o_one, uuid="one_old"), dict(o_same, uuid="same_old"), nosplit=True)
chk(legs("one") == legs("one_old") and legs("same") == legs("same_old") and len(legs("same")) == 1
    and legs("same")[0][1] == T0 + 10 and dbm.ledger_data_rev(C.conn) == rev0 and meta("upbit_split_v") is None,
    "L2 묶음 1개(단일 체결 · 같은 초 두 체결) = 종전 한 줄과 바이트 같음 · 데이터 개정·도장 그대로", (legs("same"), rev0))

t1, t3 = T0 + DAY, T0 + 3 * DAY
o_split = order("split", "ask", [(t1, "0.5", "300000"), (t3, "0.5", "300000")])
post(o_split)
L1 = legs("split")
chk([(x[0], x[1], x[4], x[6], x[7], x[8]) for x in L1] == [(0, t1, str(-E8 // 2), "150000.0", "disp", "EX_SELL"), (1, t3, str(-E8 // 2), "150000.0", "disp", "EX_SELL")]
    and [float(x[5]) for x in L1] == [150.0, 150.0],
    "L1 두 날 체결 = 레그 2(leg 0·1 · 시각 각 체결 · 수량 각 0.5 · 원화 각 150,000 · USD 각 $150)", L1)
rev0_row = None if rev0 == 0 else rev0
chk(dbm.ledger_data_rev(C.conn) == 3 and json.loads(meta("upbit_split_v")) == {"v": 1, "prev": rev0_row},
    "L1 첫 분할 = 도장 upbit_split_v(prev = 분할 전 data_rev) · data_rev 3(같은 커밋)", (dbm.ledger_data_rev(C.conn), meta("upbit_split_v")))
chk(C.conn.execute("SELECT count(*) FROM raw_ex WHERE uuid='split'").fetchone()[0] == 1, "L1 원본(raw_ex) 한 줄 그대로")

o_rev = dict(o_split, uuid="split_rev", trades=list(reversed(o_split["trades"])))
o_b = order("ord_b", "bid", [(T0 + 5, "1", "1000")])
post(o_b, o_rev)
chk([x[:1] + x[1:] for x in legs("split_rev")] == L1, "L3 체결 역순 · 다른 주문 뒤에 수집 = 같은 레그(시각순)", legs("split_rev"))
o_sec = order("sec", "bid", [(T0 + 7, "0.25", "1000"), (T0 + 7, "0.25", "1000"), (T0 + 8, "0.5", "1000")])
chk(post(o_sec) is None and [(x[1], x[4]) for x in legs("sec")] == [(T0 + 7, str(E8 // 2)), (T0 + 8, str(E8 // 2))],
    "L3 같은 초 체결 = 한 묶음(다음 초 = 다음 레그)", legs("sec"))

o_fee = order("fee", "bid", [(T0 + 20, "1", "1000"), (T0 + 21, "1", "1000"), (T0 + 22, "1", "1000")], fee="1.0001")
post(o_fee)
fz = [D(x[6]) - D("1000") for x in legs("fee")]
chk(fz == [D("0.3333"), D("0.3333"), D("0.3335")] and sum(fz) == D("1.0001"),
    "L4 매수 수수료 배분 = 금액 비율 · paid_fee 소수 4자리 단위 · 앞 내림 · 남는 몫 마지막 → 합 = paid_fee 정확 · 원가 = 금액 + 수수료", fz)
o_fee2 = order("fee2", "ask", [(T0 + 30, "0.3", "1000"), (T0 + 31, "0.7", "1000")], fee="5")
post(o_fee2)
chk([x[6] for x in legs("fee2")] == ["298.50000000", "696.50000000"] and sum(D(x[6]) for x in legs("fee2")) == D("995"),
    "L4 소수 없는 paid_fee = 1e-8 단위 · 매도 = 금액 − 배분 수수료 · 순액 합 = 주문 순액", legs("fee2"))

FX["f"] = lambda ms: 1000.0 + (int(ms) // 1000 - T0) // DAY * 100
o_fx = order("fx", "ask", [(T0 + 2 * DAY, "1", "1000"), (T0 + 4 * DAY, "1", "1000")])
post(o_fx)
chk([float(x[5]) for x in legs("fx")] == [1000.0 / 1200.0, 1000.0 / 1400.0], "L5 묶음마다 그 시각 환율(마지막 체결 환율 하나 아님)", legs("fx"))
C.conn.execute("UPDATE postings SET cost_usd=NULL WHERE source_id='fx'")
C.conn.commit()
C.svc_price.price_pass()
chk([float(x[5]) for x in legs("fx")] == [1000.0 / 1200.0, 1000.0 / 1400.0], "L5 USD 비운 뒤 가격 패스 = 레그마다 그 시각 환율(같은 주문 다른 레그 값으로 안 덮음)", legs("fx"))
FX["f"] = lambda ms: 1000.0

p0, l0 = pos(), legs("split")
post(o_split)
post(o_rev)
chk(pos() == p0 and legs("split") == l0, "L6 같은 주문 두 번 = 원장·포지션 무변")
o_dup = order("dup", "bid", [(T0 + 40, "1", "1000"), (T0 + 41, "1", "1000")])
o_dup["trades"].append(dict(o_dup["trades"][0]))
post(o_dup)
chk([x[4] for x in legs("dup")] == [str(E8), str(E8)], "L6 같은 체결 uuid 완전 중복 = 한 번(수량 합 = 주문 체결량)", legs("dup"))
o_conf = order("conf", "bid", [(T0 + 50, "1", "1000"), (T0 + 51, "1", "1000")])
o_conf["trades"].append(dict(o_conf["trades"][0], price="999"))
post(o_conf)
chk([(x[0], x[1], x[4]) for x in legs("conf")] == [(0, T0 + 51, str(2 * E8))], "L6 같은 uuid 다른 내용 = 충돌 → 한 줄(종전 · 마지막 체결 · 잔고 그대로)", legs("conf"))
o_nou = order("nou", "bid", [(T0 + 60, "1", "1000"), (T0 + 60, "1", "1000"), (T0 + 61, "1", "1000")], tuuid=False)
post(o_nou)
chk([x[4] for x in legs("nou")] == [str(2 * E8), str(E8)], "L6 uuid 없는 같은 내용 체결 = 둘 다 실제 체결(합치되 수량 보존)", legs("nou"))

o_cx = order("cx", "bid", [(T0 + 70, "0.2", "1000"), (T0 + 71, "0.4", "1000")], state="cancel", volume="1.0")
post(o_cx)
chk([x[4] for x in legs("cx")] == [str(E8 // 5), str(2 * E8 // 5)], "L7 부분 체결 뒤 취소 = 체결분만(0.2 · 0.4)", legs("cx"))
o_bad = order("bad", "bid", [(T0 + 80, "1", "1000"), (T0 + 81, "1", "1000")], executed_volume="2.5")
post(o_bad)
o_nof = order("nof", "bid", [(T0 + 90, "1", "1000"), (T0 + 91, "1", "1000")], executed_funds=None, price="1000")
post(o_nof)
chk([(x[1], x[4]) for x in legs("bad")] == [(T0 + 81, str(250000000))] and [(x[1], x[4], x[6]) for x in legs("nof")] == [(T0 + 91, str(2 * E8), "2000")],
    "L7 수량 합 어긋남 · 주문 체결 금액 없음 = 한 줄(종전 · 지우지 않음 · 가짜 시각·균등 분할 없음)", (legs("bad"), legs("nof")))

o_old = order("old", "ask", [(T0 + 100, "0.5", "300000"), (T0 + 100 + 2 * DAY, "0.5", "300000")])
post(o_old, nosplit=True)
p1, l1 = pos(), legs("old")
post(o_old)
chk(legs("old") == l1 and len(l1) == 1 and pos() == p1, "L8 옛 합산 레그가 있으면 새 코드 재수집 = 무변(새 레그와 공존 없음)", legs("old"))
st, why, tmin = CF.resplit_order(C.conn, "old", o_old, S._unpost_source, S._consume_fills)
C.conn.commit()
chk(st == "moved" and why is None and tmin == T0 + 100 and [x[1] for x in legs("old")] == [T0 + 100, T0 + 100 + 2 * DAY] and pos() == p1,
    "L8 resplit_order = 옛 한 줄 → 묶음 레그(포지션 합 무변 · 가장 이른 영향 = 첫 체결)", (st, why, legs("old")))
chk(CF.resplit_order(C.conn, "old", o_old, S._unpost_source, S._consume_fills)[0] == "same", "L8 다시 = 'same'(무변)")

o_nt = order("nt", "ask", [(T0 + 200, "0.5", "300000"), (T0 + 200 + DAY, "0.5", "300000")])
bare = {k: v for k, v in o_nt.items() if k != "trades"}
post(bare)
chk([x[1] for x in legs("nt")] == [T0 + 200], "L9 체결 목록 없는 옛 원본 = 생성 시각 한 줄(종전)")
inv0 = meta(dbm.DAILY_INVAL_K)
res = S._consume_order_trades({"orders": [o_nt], "ts": T0, "src": "test"})
C.conn.commit()
post(dict(o_nt, uuid="nt_direct"))
chk(res["moved"] == 1 and legs("nt") == legs("nt_direct") and len(legs("nt")) == 2 and meta(dbm.DAILY_INVAL_K) != inv0,
    "L9 체결 목록 채우기 = 바로 기장한 것과 같은 분할 레그(재구축 경로와 같음) · 지난날 무효화 표식", (res, legs("nt")))

o_btc = order("btc", "bid", [(T0 + 300, "1", "0.01"), (T0 + 300 + DAY, "1", "0.01")], market="USDT-XYZ")
post(o_btc)
chk([(x[0], x[1]) for x in legs("btc")] == [(0, T0 + 300 + DAY), (1, T0 + 300 + DAY)], "L10 USDT 마켓 = 종전 두 레그(기준·쿼트 · 마지막 체결 · 분할 안 함)", legs("btc"))

o_c1 = order("c1", "ask", [(T0 + 400, "0.5", "300000"), (T0 + 400 + DAY, "0.5", "300000")])
o_c2 = order("c2", "bid", [(T0 + 500, "1", "200000"), (T0 + 500 + 3 * DAY, "1", "210000")], fee="200.5")
post(o_c1, o_c2, nosplit=True)
pl = LRF.split_plan(C.conn)
todo = sorted(t[0] for t in pl["todo"])
chk(todo == ["c1", "c2"] and sum(t[2] for t in pl["todo"]) == 4 and min(t[3] for t in pl["todo"]) == T0 + 400,
    "L11 점검 = 옛 합산 주문 2 · 묶음 4 · 가장 이른 영향 = 첫 체결", (todo, pl["n"], pl["why"]))
dump0, p2 = [legs(u) for u in ("c1", "c2")], pos()
cnt = {"n": 0}


def boom(*a, **k):
    cnt["n"] += 1
    if cnt["n"] == 3:
        raise RuntimeError("주입 실패")
    return C._post_leg(*a, **k)


S._post_leg = boom
try:
    LRF.split_apply(C, pl["todo"])
    r11 = "통과"
except RuntimeError as e:
    r11 = str(e)
finally:
    del S._post_leg
chk(r11 == "주입 실패" and [legs(u) for u in ("c1", "c2")] == dump0 and pos() == p2, "L11 중간 실패 주입 = 전부 취소(원장 레그·포지션 원복)", r11)
inv1 = meta(dbm.DAILY_INVAL_K)
n11, why11, t11 = LRF.split_apply(C, pl["todo"])
chk(n11 == 2 and not why11 and t11 == T0 + 400 and len(legs("c1")) == 2 and len(legs("c2")) == 2 and pos() == p2 and meta(dbm.DAILY_INVAL_K) != inv1
    and sum(D(x[6]) for x in legs("c2")) == D("410200.5"),
    "L11 적용 = 교체 2 · 포지션 무변 · 원화 합 보존 · 무효화 표식", (n11, why11, legs("c2")))
chk(not LRF.split_plan(C.conn)["todo"], "L11 두 번째 점검 = 대상 0(멱등)")
pd = LRF.split_plan(C.conn, down=True)
nd, whyd, _td = LRF.split_apply(C, pd["todo"], down=True)
chk(nd == len(pd["todo"]) and not whyd and dbm.ledger_data_rev(C.conn) == rev0 and meta("data_rev") == rev0_row and meta("upbit_split_v") is None
    and pos() == p2 and legs("c1") == [x for x in dump0[0]] and len(legs("split")) == 1 and not LRF.split_plan(C.conn, down=True)["todo"],
    "L11 내리기 = 분할 레그 전부 한 줄(종전과 같은 줄) · 도장 지움 · data_rev 3 → 분할 전 값(줄 없던 원장 = 줄 지움) · 포지션 무변", (nd, whyd, legs("c1")))

n12, _w, _t = LRF.split_apply(C, LRF.split_plan(C.conn)["todo"])
chk(dbm.ledger_data_rev(C.conn) == 3, "L12 다시 바꾸기 = data_rev 3", n12)
chk(dbm.DATA_REV == 3 and 3 in dbm.DATA_REVS and dbm.fence_why(C.conn) is None,
    "L12 개정 3 = 이 코드가 아는 번호(옛 코드 = DATA_REV 2 → 같은 펜스가 '원장이 코드보다 새' 로 거부 — test_data_rev [2] · 옛 판 실측은 보고)", dbm.DATA_REV)
import autofix_apply as AP  # noqa: E402
try:
    AP.data_rev_down(C.conn, 1)
    r12 = "내림"
except AP.Refused as e:
    r12 = str(e)
chk("data_rev 3" in r12 and dbm.ledger_data_rev(C.conn) == 3, "L12 ledger_rowfix --data-rev-down 1 = 개정 3 거부(먼저 --upbit-split-down)", r12)

import acct_norm  # noqa: E402
import ubfill  # noqa: E402
bk = ubfill.booked(C.conn, ["c1"], acct_norm.fill_ts)["c1"]
chk(bk.get("parts") == [(T0 + 400, D("150000.0")), (T0 + 400 + DAY, D("150000.0"))], "L13 booked = 분할 레그마다 (시각, 원화 +)", bk.get("parts"))
open9 = [dict(o_c1, state="wait", trades=None, executed_volume="0.5", executed_funds="150000")]
mid9 = ubfill.deltas(open9, {"c1": bk}, T0 + 400 + 100)
end9 = ubfill.deltas(open9, {"c1": bk}, T0 + 400 + 2 * DAY)
chk(mid9["ETH"]["krw"] == 0 and end9["ETH"]["krw"] == D("-150000.0"),
    "L13 스냅숏이 두 체결 사이 = 원화 몫 0(첫 레그가 이미 이력에 · 종전 규칙이면 +150,000 이중) · 두 체결 뒤 = 기장분 전부 뺌", (mid9, end9))

import sqlite3  # noqa: E402
import rebuild2  # noqa: E402
base14, shadow14 = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
for cx in (base14, shadow14):
    cx.execute("CREATE TABLE postings (source_kind, source_ns, source_id, leg_seq, leg_kind, event, cost_usd, asset_id)")
    cx.execute("CREATE TABLE assets (asset_id, symbol)")
base14.executemany("INSERT INTO postings VALUES (?,?,?,?,?,?,?,?)", [("exchange", "upbit:order", "k1", 0, "acq", "EX_BUY", "100.0", 1),
                                                                    ("exchange", "upbit:order", "q1", 0, "acq", "EX_BUY", "5.0", 1),
                                                                    ("exchange", "upbit:order", "q1", 1, "disp", "EX_SELL", "5.0", 2)])
shadow14.executemany("INSERT INTO postings VALUES (?,?,?,?,?,?,?,?)", [("exchange", "upbit:order", "k1", 0, "acq", "EX_BUY", "49.0", 1),
                                                                      ("exchange", "upbit:order", "k1", 1, "acq", "EX_BUY", None, 1),
                                                                      ("exchange", "upbit:order", "k1", 2, "acq", "EX_BUY", "50.0", 1),
                                                                      ("exchange", "upbit:order", "q1", 0, "acq", "EX_BUY", "5.0", 1),
                                                                      ("exchange", "upbit:order", "q1", 1, "disp", "EX_SELL", "5.0", 2)])
lost14 = rebuild2.cost_lost(base14, shadow14)
shadow14.execute("UPDATE postings SET cost_usd='1.0' WHERE source_id='k1' AND leg_seq=1")
ok14 = rebuild2.cost_lost(base14, shadow14)
chk(lost14["n"] == 1 and lost14["usd"] == 100.0 and lost14["top"][0]["key"] == ["exchange", "upbit:order", "k1", 0] and ok14["n"] == 0,
    "L14 기준선 한 줄 주문의 shadow 분할 레그 원가 빔 = 소실 1칸(그 주문 기준선 원가 전부 · 보수적) · 다 채우면 0 · 비KRW 두 레그 주문 무관", (lost14, ok14))

import export_beancount as EB  # noqa: E402
sf0 = EB.export(EB._load(C.conn))[1].get("shortfall", 0)
post(order("eb1", "bid", [(T0 + 700, "1", "100000")], market="KRW-BEAN"),
     order("eb2", "ask", [(T0 + 700 + DAY, "0.5", "300000"), (T0 + 700 + 3 * DAY, "1.5", "300000")], market="KRW-BEAN"),
     order("eb3", "bid", [(T0 + 700 + 2 * DAY, "1", "200000")], market="KRW-BEAN"))
txt15, st15 = EB.export(EB._load(C.conn))[:2]
chk(st15.get("shortfall", 0) == sf0 and txt15.count('src: "exchange/upbit:order/eb2"') == 2,
    "L15 내보내기 = 분할 매도 두 거래(체결 날짜마다 · 부모 주문 src 같음) · 사이 매수 뒤 두 번째 매도 = 로트 부족 늘지 않음", (sf0, st15.get("shortfall")))

import types  # noqa: E402
import view_krw  # noqa: E402
holder = types.SimpleNamespace(_upbit_krw_tl=None)
tl16 = view_krw.KrwMixin._upbit_krw_timeline(holder, C.conn)
n_split16 = sum(len(legs(u)) for u in {r[0] for r in C.conn.execute("SELECT source_id FROM postings WHERE source_ns='upbit:order' AND leg_seq > 0")}
                if len({x[8] for x in legs(u)}) == 1)
chk((t1, D("150000.0")) in tl16 and (t3, D("150000.0")) in tl16 and not any(t == T0 + 300 + DAY for t, _d in tl16)
    and len(holder._upbit_krw_tl[0]) == 3 and holder._upbit_krw_tl[0][2] == n_split16,
    "L16 원화 이력 = 분할 매도 두 체결 시각에 각 +150,000 · USDT 마켓 주문 = 원화 이력 밖(종전) · 캐시 키 셋째 칸 = KRW 분할 레그 수(쿼트 레그 안 셈)",
    (holder._upbit_krw_tl[0], n_split16))
import argparse  # noqa: E402
import pricing  # noqa: E402
NET = []
FAIL = {"to_lo": None}


class NetPx(pricing.PxCache):
    FX_WARM_GAP = 0

    def _net(self, kind, ms):
        NET.append((kind, C.conn.in_transaction))
        if FAIL["to_lo"] is not None and ms // 1000 >= FAIL["to_lo"]:
            self.d["neg_ts"]["_fx"] = int(time.time())
            return None
        return 1000.0

    def _resting(self):
        return time.time() - float(self.d["neg_ts"].get("_fx", 0) or 0) < self.FX_NEG_SEC

    def fx_at(self, ts_ms):
        key = str(int(ts_ms) // 60_000 * 60_000)
        if key in self.d["fx"]:
            return self.d["fx"][key]
        if self._resting() or self._nb() is not None:
            return None
        got = self._net("fx1", int(ts_ms))
        if got:
            self.d["fx"][key] = got
            self._dirty += 1
        return got

    def fx_warm(self, ts_ms_list, max_calls=None):
        mins = sorted({m for m in (int(t) // 60_000 * 60_000 for t in ts_ms_list)
                       if m > pricing.FX_USDT_FIRST_MS + 86_400_000 and str(m) not in self.d["fx"]})
        groups = []
        for m in mins:
            if groups and m - groups[-1][0] < (self.FX_WARM_SPAN - 1) * 60_000:
                groups[-1].append(m)
            else:
                groups.append([m])
        n = 0
        for g in groups:
            if self._resting():
                break
            got = self._net("gj", g[-1])
            if not got:
                break
            for m in g:
                self.d["fx"][str(m)] = got
            n += len(g)
            self._dirty += len(g)
        return n


def posn():
    return [(g, loc, D(str(q))) for g, loc, q in pos()]


px0 = C.px
PXF = os.path.join(T.TMP, "px_split_warm.json")
try:
    T17 = pricing.FX_USDT_FIRST_MS // 1000 + 10 * DAY
    T_PRE = pricing.FX_USDT_FIRST_MS // 1000 - 30 * DAY
    o_w1 = order("w1", "ask", [(T17, "0.5", "300000"), (T17 + 3 * DAY, "0.5", "300000")], market="KRW-WRM")
    o_w2 = order("w2", "bid", [(T_PRE, "1", "1000"), (T_PRE + DAY, "1", "1000")], market="KRW-WRM")
    o_w3 = order("w3", "bid", [(T17 + 20 * DAY, "1", "1000"), (T17 + 20 * DAY + 3600, "1", "1000")], market="KRW-WRM")
    o_w4 = order("w4", "bid", [(T17 + 40 * DAY, "1", "1000"), (T17 + 40 * DAY + 3600, "1", "1000")], market="KRW-WRM")
    post(o_w1, o_w2, o_w3, o_w4, nosplit=True)
    C.px = NetPx(PXF)
    p17, l17 = posn(), {u: legs(u) for u in ("w1", "w2", "w3", "w4")}
    rc17 = LRF._run_split(argparse.Namespace(upbit_split_down=False, apply=False, kind="upbit_split"))
    pl17 = LRF.split_plan(C.conn)
    chk(rc17 == 0 and not NET and sorted(t[0] for t in pl17["todo"]) == ["w1", "w2", "w3", "w4"], "L17 점검(--apply 없음)·계획 = 바깥 연결 0", (rc17, NET))
    n17, why17, _t = LRF.split_apply(C, [t for t in pl17["todo"] if t[0] in ("w1", "w2")])
    chk(n17 == 2 and not why17 and sorted(k for k, _tx in NET) == ["fx1", "fx1", "gj", "gj"] and not any(tx for _k, tx in NET),
        "L17 미리 받기 = 마켓 뒤 분 = fx_warm 묶음 1콜씩(w1 두 묶음) · 마켓 전 분 = fx_at 한 분씩(w2 두 분) · 전부 잠금 밖 · 잠금 안 바깥 연결 0", (n17, why17, NET))
    with open(PXF, encoding="utf-8") as f:
        fx17 = json.load(f).get("fx") or {}
    chk(all(str(t * 1000) in fx17 for t in (T17, T17 + 3 * DAY, T_PRE, T_PRE + DAY)), "L17 끝 = 받은 환율을 캐시 파일에(px.flush)", sorted(fx17)[:6])
    chk([float(x[5]) for x in legs("w1")] == [150.0, 150.0] and [float(x[5]) for x in legs("w2")] == [1.0, 1.0] and posn() == p17,
        "L17 잠금 안 = 미리 받은 캐시 환율로 레그마다 USD · 포지션 무변", (legs("w1"), legs("w2")))
    NET.clear()
    FAIL["to_lo"] = T17 + 40 * DAY - 3600
    pl18 = LRF.split_plan(C.conn)
    n18, why18, _t18 = LRF.split_apply(C, pl18["todo"])
    chk(sorted(t[0] for t in pl18["todo"]) == ["w3", "w4"] and n18 == 1 and list(why18.values()) == [1] and "원가 USD 미확보" in list(why18)[0]
        and legs("w4") == l17["w4"] and len(legs("w3")) == 2 and posn() == p17 and [k for k, _tx in NET] == ["gj", "gj"] and not any(tx for _k, tx in NET),
        "L18 미리 받기 일부 실패 = 그 주문(w4)만 되돌림(원장·포지션 그대로 · 사유 원가 USD 미확보 → rc 4 · 다시) · w3 바뀜 · 바깥 연결 2(잠금 밖 · 실패 뒤 더 안 부름)",
        (n18, why18, NET))
    NET.clear()
    FAIL["to_lo"] = None
    C.px.d["neg_ts"]["_fx"] = 0
    pl18b = LRF.split_plan(C.conn)
    n18b, why18b, _t = LRF.split_apply(C, pl18b["todo"])
    chk([t[0] for t in pl18b["todo"]] == ["w4"] and n18b == 1 and not why18b and len(legs("w4")) == 2 and posn() == p17
        and [k for k, _tx in NET] == ["gj"] and not any(tx for _k, tx in NET),
        "L18 다시 실행 = 남은 주문만 바뀜 · 미리 받기 1콜(잠금 밖) · 잠금 안 바깥 연결 0", ([t[0] for t in pl18b["todo"]], n18b, why18b, NET))
finally:
    C.px = px0

AF_KEY = "autofix:zz:WRM"


def set_rev(v):
    C.conn.execute("DELETE FROM meta WHERE k='data_rev'")
    if v is not None:
        C.conn.execute("INSERT INTO meta (k, v) VALUES ('data_rev', ?)", (str(v),))
    C.conn.commit()


def down_all():
    LRF.split_apply(C, LRF.split_plan(C.conn, down=True)["todo"], down=True)


down_all()
chk(meta("upbit_split_v") is None and meta("data_rev") == rev0_row, "L19 (전제) 내리기 = 도장 없음 · 분할 전 값", meta("data_rev"))
for i19, prev in enumerate((None, 0, 1, 2)):
    set_rev(prev)
    post(order(f"rt{i19}", "bid", [(T0 + 900 + i19 * 10, "1", "1000"), (T0 + 900 + DAY + i19 * 10, "1", "1000")]))
    st19 = json.loads(meta("upbit_split_v"))
    post(order(f"rt{i19}b", "bid", [(T0 + 905 + i19 * 10, "1", "1000"), (T0 + 905 + DAY + i19 * 10, "1", "1000")]))
    chk(st19 == {"v": 1, "prev": prev} and json.loads(meta("upbit_split_v")) == st19 and dbm.ledger_data_rev(C.conn) == 3,
        "L19 core 첫 분할 도장 prev = 분할 전 data_rev(%r) · 두 번째 분할 주문 = 도장 그대로 · data_rev 3" % (prev,), (st19, meta("upbit_split_v")))
    down_all()
    chk(meta("data_rev") == (None if prev is None else str(prev)) and meta("upbit_split_v") is None,
        "L19 내리기 = data_rev 원래 값(%r · None = 줄 지움) · 도장 지움" % (prev,), meta("data_rev"))
for why19, stamp, extra, want in (("prev 없는 옛 도장", {"v": 1}, None, "2"),
                                   ("자동 처리 영수증(개정 3 동안)", {"v": 1, "prev": 1}, ("meta", AF_KEY), "2"),
                                   ("선물 정산 재배치 도장(개정 3 동안)", {"v": 1, "prev": None}, ("meta", "exf_fut_place_v"), "1")):
    set_rev(None)
    post(order("fl" + str(len(why19)), "bid", [(T0 + 990, "1", "1000"), (T0 + 990 + DAY, "1", "1000")]))
    C.conn.execute("UPDATE meta SET v=? WHERE k='upbit_split_v'", (json.dumps(stamp),))
    if extra:
        C.conn.execute("INSERT INTO meta (k, v) VALUES (?, 'x')", (extra[1],))
    C.conn.commit()
    down_all()
    chk(meta("data_rev") == want and meta("upbit_split_v") is None, "L19 %s → 내리기 = data_rev %s" % (why19, want), meta("data_rev"))
    if extra:
        C.conn.execute("DELETE FROM meta WHERE k=?", (extra[1],))
        C.conn.commit()
T.finish()
