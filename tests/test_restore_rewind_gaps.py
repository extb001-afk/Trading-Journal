#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import exf_net as N  # noqa: E402
import inbox  # noqa: E402
import ledger_restore as LR  # noqa: E402

S = paths.STATE_DIR
NOW = int(time.time())
T_BK = NOW - 3 * 86400
W1, W2 = "0x" + "a1" * 20, "0x" + "b2" * 20
SOLW = "So1Wallet1111111111111111111111111111111111"


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def wj(name, obj):
    statefile.atomic_write_json(os.path.join(S, name), obj)


def cfg(wallets):
    with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"chains": {}, "wallets": wallets}, f)


def clear_state():
    if os.path.isdir(S):
        shutil.rmtree(S)
    os.makedirs(os.path.join(S, "inbox"))
    os.makedirs(os.path.join(S, "backups"))


def make_backup(path, ex_rows=(), wallets=(), offs=(("evm", 9, 0), ("sol", 9, 0), ("bsc", 9, 0), ("ex", 9, 0))):
    c = dbm.open_db(path)
    for ch, a in wallets:
        c.execute("INSERT INTO wallets VALUES(?, ?, 'x', 0)", (ch, a))
    c.execute("INSERT INTO raw_txs VALUES('eth', '0xe1', 1000, NULL, NULL, '{}', '[]', ?)", (T_BK,))
    for e in ex_rows:
        c.execute("INSERT INTO raw_ex VALUES(?,?,?,?,?,?)", (e[0], e[1], e[2], 1, json.dumps(e[3] if len(e) > 3 else {}), T_BK))
    for s9, sg, off in offs:
        c.execute("INSERT INTO inbox_offsets VALUES(?, ?, ?)", (s9, sg, off))
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()
    os.utime(path, (T_BK, T_BK))


BK = os.path.join(S, "backups", "ledger_20261001.db")


def acct(extra=None):
    d = {"seen": {"bybit:d-old": "SUCCESS", "bybit:d-new": "SUCCESS"}, "seen_txids": {"bybit:d-old": True, "bybit:d-new": True},
         "backfilled_until": NOW, "int": {"lo": NOW - 200 * 86400, "until": NOW},
         "fills": {"backfilled_until": NOW, "seen": {"bybit:f-old": 1, "bybit:f-new": 2}, "cv": {"until": NOW}}}
    d.update(extra or {})
    return d


clear_state()
cfg([])
make_backup(BK, ex_rows=[("bybit", "deposit", "bybit:d-old", {"state": "PENDING"}), ("bybit", "deposit", "bybit:s1:d-old", {"state": "PENDING"}),
                         ("bybit", "trade", "bybit:f-old"), ("bybit", "trade", "bybit:s1:f-old"),
                         ("binance", "trade", "binance:BTCUSDT:500"), ("binance", "trade", "binance:s1:BTCUSDT:300"),
                         ("bithumb", "trade", "bithumb:A")])
wj("exf_state.json", {
    "bybit": dict(acct({"pend_scan": NOW, "pend_ts": {}}), accts={"s1": acct(), "s2": acct({"seen": {"bybit:d-x": "SUCCESS"}}), "s1@u777": acct({"uid": "777"})}),
    "binance": {"seen": {}, "backfilled_until": NOW,
                "fills": {"backfilled_until": NOW, "seen": {"binance:BTCUSDT:500": 1, "binance:BTCUSDT:510": 1},
                          "pair_cursor": {"BTCUSDT": 511}},
                "accts": {"s1": {"seen": {}, "backfilled_until": NOW,
                                 "fills": {"backfilled_until": NOW, "seen": {"binance:BTCUSDT:300": 1, "binance:BTCUSDT:320": 1},
                                           "pair_cursor": {"BTCUSDT": 321}, "margin_cursor": {"c:ETHUSDT": 9}}}}},
    "bithumb": {"seen": {}, "backfilled_until": NOW,
                "fills": {"backfilled_until": NOW, "seen": {"bithumb:A": 1, "bithumb:X": 1},
                          "open_track": {"Y": {"c": "2026-01-01T00:00:00+09:00", "m": "KRW-BTC"}}, "track_pending": 0}}})
p = LR.plan(BK, now=NOW)
cut = p["cut"]
ck("R0 인박스 없음 = ex 되감기", "ex" in p["rewind"] and p["coverage"]["ex"]["state"] == "gap", p["coverage"]["ex"])
xs = p["files"].get("exf_state.json") or {}
mb = xs.get("bybit") or {}
s1 = (mb.get("accts") or {}).get("s1") or {}
s2 = (mb.get("accts") or {}).get("s2") or {}
ck("R1 메인 입출금 seen = 백업 마지막 상태(종전 그대로)", mb.get("seen") == {"bybit:d-old": "PENDING"}, mb.get("seen"))
ck("R1 서브 입출금 seen = 백업의 그 계정 행(ex:s1:id → ex:id)으로", s1.get("seen") == {"bybit:d-old": "PENDING"}, s1.get("seen"))
ck("R1 서브 txid 표시도 백업 기준", s1.get("seen_txids") == {}, s1.get("seen_txids"))
ck("R1 서브 백업에 그 계정 행이 없음 = seen 전부 지움(다시 받음)", s2.get("seen") == {}, s2.get("seen"))
s1a = (mb.get("accts") or {}).get("s1@u777") or {}
ck("R1 B1 보관 칸(s1@u<uid> · 키 바뀐 옛 계정) = 기록 id 딱지(s1) 행으로 대조(0건으로 seen 을 다 지우지 않음) · 창은 되감기 기준",
   s1a.get("seen") == {"bybit:d-old": "PENDING"} and (s1a.get("fills") or {}).get("seen") == {"bybit:f-old": 1} and s1a.get("backfilled_until") == cut
   and s1a.get("uid") == "777", {"seen": s1a.get("seen"), "fills": s1a.get("fills")})
ck("R1 서브 창·체결 창·간편전환 창 = 되감기 기준", s1.get("backfilled_until") == cut and (s1.get("fills") or {}).get("backfilled_until") == cut
   and ((s1.get("fills") or {}).get("cv") or {}).get("until") == cut, s1)
ck("R1 서브 체결 seen = 백업의 그 계정 체결만", (s1.get("fills") or {}).get("seen") == {"bybit:f-old": 1}, s1.get("fills"))
row = N.norm_row("bybit", "d-new", "USDT", 100, 0, "fake_tx", "SUCCESS", NOW - 86400, NOW - 86400)
ck("R1 서브의 백업 뒤 입금 = 실제 방출 필터가 다시 보냄(메인과 같이 1건)",
   len(N._rows_to_emit([dict(row)], s1.get("seen") or {}, s1.get("seen_txids") or {})) == 1
   and len(N._rows_to_emit([dict(row)], mb.get("seen") or {}, mb.get("seen_txids") or {})) == 1)
bs1 = ((xs.get("binance") or {}).get("accts") or {}).get("s1") or {}
ck("R1 바이낸스 서브 페어 커서 = 그 계정 백업 마지막 id + 1 · 체결 seen 그 계정 것만",
   (bs1.get("fills") or {}).get("pair_cursor") == {"BTCUSDT": 301} and (bs1.get("fills") or {}).get("seen") == {"binance:BTCUSDT:300": 1}
   and (bs1.get("fills") or {}).get("margin_cursor") == {"c:ETHUSDT": 0}, bs1.get("fills"))
bm = (xs.get("binance") or {}).get("fills") or {}
ck("R1 바이낸스 메인 페어 커서 = 메인 백업 마지막 id + 1(서브 행에 안 끌림)", bm.get("pair_cursor") == {"BTCUSDT": 501} and list(bm.get("seen")) == ["binance:BTCUSDT:500"], bm)
ck("R2 바이비트 내부이체 커서 int.until = 되감기 기준(메인·서브) · 이력 하한 lo 그대로",
   (mb.get("int") or {}).get("until") == cut and (s1.get("int") or {}).get("until") == cut and (mb.get("int") or {}).get("lo") == NOW - 200 * 86400,
   (mb.get("int"), s1.get("int")))
ck("R4 해외 입출금 저장 창 재조회 도장(pend_scan) 지움", "pend_scan" not in mb, sorted(mb))
bt = ((xs.get("bithumb") or {}).get("fills") or {})
ck("R4 빗썸 백업에 없는 체결 = 단건 확정 추적(closed)으로 · 백업에 있는 것은 추적 안 함 · 미체결 추적은 그대로",
   (bt.get("open_track") or {}).get("X", {}).get("closed") is True and "A" not in (bt.get("open_track") or {})
   and (bt.get("open_track") or {}).get("Y") == {"c": "2026-01-01T00:00:00+09:00", "m": "KRW-BTC"}, bt.get("open_track"))
ck("R4 빗썸 체결 seen = 백업 것만", bt.get("seen") == {"bithumb:A": 1}, bt.get("seen"))

clear_state()
cfg([])
make_backup(BK, ex_rows=[("binance", "trade", "binance:s1:BTCUSDT:500")])
wj("exf_state.json", {"binance": {"seen": {}, "backfilled_until": NOW, "fills": {"backfilled_until": NOW, "seen": {}, "pair_cursor": {}},
                                  "accts": {"s1": {"seen": {}, "backfilled_until": NOW, "uid": "B", "fills": {"backfilled_until": NOW,
                                                   "seen": {"binance:BTCUSDT:300": 1}, "pair_cursor": {"BTCUSDT": 301}, "margin_cursor": {"c:ETHUSDT": 9}}},
                                            "s1@uA": {"seen": {}, "backfilled_until": NOW, "uid": "A", "fills": {"backfilled_until": NOW,
                                                      "seen": {"binance:BTCUSDT:500": 1}, "pair_cursor": {"BTCUSDT": 501}}}}}})
pb = LR.plan(BK, now=NOW)
ab = (((pb["files"].get("exf_state.json") or {}).get("binance") or {}).get("accts") or {})
fb1, fba = (ab.get("s1") or {}).get("fills") or {}, (ab.get("s1@uA") or {}).get("fills") or {}
ck("R1b 보관 칸 있는 딱지(s1) = 페어·마진 커서 0(새 계정 백업 뒤 체결 300 다시 받음) · seen 은 백업 대조 그대로(300 지움 · 보관 칸 500 남김)",
   fb1.get("pair_cursor") == {"BTCUSDT": 0} and fb1.get("margin_cursor") == {"c:ETHUSDT": 0} and fb1.get("seen") == {}
   and fba.get("pair_cursor") == {"BTCUSDT": 0} and fba.get("seen") == {"binance:BTCUSDT:500": 1}, (fb1, fba))

clear_state()
cfg([])
make_backup(BK, ex_rows=[("upbit", "order", "U1")])
cl9 = dbm.open_db(paths.DB_PATH)
cl9.execute("INSERT INTO raw_ex VALUES('upbit', 'order', 'X', 1, '{}', ?)", (NOW - 1700,))
cl9.commit()
cl9.close()
wj("upbit_orders_state.json", {"backfilled_until": NOW - 60, "complete": True, "uuids": ["U1", "X", "Z"],
                               "open_track": {"Y": {"c": "2026-01-01T00:00:00+09:00", "m": "KRW-ETH"}}, "resweep_i": 1, "track_pending": 0})
p = LR.plan(BK, now=NOW)
up = p["files"].get("upbit_orders_state.json") or {}
tr9 = up.get("open_track") or {}
ck("R3 업비트 uuid = 백업 것만", up.get("uuids") == ["U1"], up.get("uuids"))
ck("R3 백업에 없고 지금 원장에 방출 흔적 있는 주문 = 단건 확정 추적(closed) · 백업 것은 추적 안 함 · 미체결 추적 그대로",
   tr9.get("X") == {"closed": True} and "U1" not in tr9 and tr9.get("Y") == {"c": "2026-01-01T00:00:00+09:00", "m": "KRW-ETH"}, tr9)
ck("R3 방출 흔적 없는 주문(대사 가드로 안 보낸 것) = 대사 가드 표식(rs) 달고 추적(대사 앞 체결은 다시 안 보냄)", tr9.get("Z") == {"closed": True, "rs": 1}, tr9)
wj("upbit_orders_state.json", up)
os.remove(paths.DB_PATH)
shutil.copyfile(BK, paths.DB_PATH)
cl9 = dbm.open_db(paths.DB_PATH)
cl9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_upbit', ?)", (str(NOW - 3600),))
cl9.commit()
cl9.close()
import upbit_link  # noqa: E402

iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")   # noqa: E731
XC = NOW - 60 * 86400
ORD = {u9: {"uuid": u9, "state": "done", "market": "KRW-BTC", "side": "bid", "executed_volume": "1", "created_at": iso(XC), "ord_type": "limit",
            "price": "100", "executed_funds": "100", "trades": [{"created_at": iso(ft9), "volume": "1", "funds": "100", "price": "100"}]}
       for u9, ft9 in (("X", NOW - 1800), ("Z", NOW - 7200))}


class Up:
    remaining_min = 999

    def get(self, path, q):
        if path == "/v1/orders/closed":
            s9 = datetime.fromisoformat(q["start_time"]).timestamp()
            e9 = datetime.fromisoformat(q["end_time"]).timestamp()
            return list(ORD.values()) if q.get("state") == "done" and s9 <= XC < e9 else []
        if path == "/v1/order":
            return ORD.get(q.get("uuid"))
        return []


orders, ok9, st9 = upbit_link.fetch_orders(Up(), 5, open_now=[{"uuid": "Y", "created_at": "2026-01-01T00:00:00+09:00", "market": "KRW-ETH"}])
ck("R3 복구 뒤 실제 fetch_orders = 생성 60일 지난 주문의 백업 뒤 체결(X)만 다시 보냄 · 대사가 흡수한 Z 는 안 보냄(이중 계상 0)",
   [o.get("uuid") for o in orders] == ["X"] and "Z" in (st9.get("uuids") or []) and "Z" not in (st9.get("open_track") or {}),
   ([o.get("uuid") for o in orders], st9.get("uuids"), st9.get("open_track")))

for mode in ("replay", "gap"):
    clear_state()
    cfg([])
    make_backup(BK, offs=(("evm", 1, 0),) if mode == "replay" else (("evm", 9, 0),))
    if mode == "replay":
        d9 = os.path.join(S, "inbox", "evm")
        os.makedirs(d9)
        open(os.path.join(d9, "000000001.jsonl"), "w").close()
    cut9 = T_BK - 12 * 3600
    wj("poison_replayed.json", {"aa": {"ok": True, "ts": cut9 + 600}, "bb": {"ok": True, "ts": cut9 - 600}, "cc": {"ok": False, "ts": NOW, "err": "x"}})
    wj("poison_replay_request.json", {"all": False, "ids": ["zz"], "ts": NOW, "by": "web"})
    wj("cursor_evm_eth.json", {W1: 5000, "_cov:" + W1: 10, "_es_int": {"seen": {"0xe1": [1000, {"i": 1}], "0xe9": [4000, {"i": 1}]}, "floor": {W1: 7}}})
    p = LR.plan(BK, now=NOW)
    ck(f"R5 ({mode}) 기준 시각 = 백업 데이터 시각", p["cut"] == cut9, (p["cut"], cut9))
    pr = p["files"].get("poison_replayed.json")
    ck(f"R5 ({mode}) 격리 재처리 기록 = 되감기 기준 이전 것만(그 뒤 성공은 복원 원장에 없음 — 다시 처리)", pr == {"bb": {"ok": True, "ts": cut9 - 600}}, pr)
    rq = p["files"].get("poison_replay_request.json") or {}
    ck(f"R5 ({mode}) 지운 성공 기록만 재처리 요청(앞 요청과 합침 · 실패 기록·기준 앞 성공은 안 넣음)",
       rq.get("all") is False and rq.get("ids") == ["zz", "aa"], rq)
    if mode == "gap":
        ce = p["files"].get("cursor_evm_eth.json") or {}
        ck("R6 EVM 늦은 색인 방출 기록(_es_int.seen) 비움 · 창 하한(floor) 유지", ce.get("_es_int") == {"seen": {}, "floor": {W1: 7}}, ce.get("_es_int"))
    else:
        ck("R5 (replay) 수집기 커서는 안 건드림", "cursor_evm_eth.json" not in p["files"], sorted(p["files"]))

clear_state()
cfg([])
for n9 in ("bsc_balw.json", "bsc_nonce.json", "exf_state.json"):
    wj(n9, {"w": {}})
out9 = io.StringIO()
with redirect_stdout(out9):
    rc9 = LR.new_ledger(True, True, proc_check=False, log=print)
ck("R7 new --fresh-collect = 잔고 감시 상태(bsc_balw.json)도 옆으로", rc9 == 0 and not os.path.exists(os.path.join(S, "bsc_balw.json"))
   and not os.path.exists(os.path.join(S, "bsc_nonce.json")), out9.getvalue()[-300:])

clear_state()
d9 = os.path.join(S, "inbox", "evm")
os.makedirs(d9)
for sg in (1, 2, 3, 4):
    with open(os.path.join(d9, f"{sg:09d}.jsonl"), "w") as f:
        f.write(json.dumps({"kind": "x", "seg": sg}) + "\n")
old9 = time.time() - 30 * 86400
os.utime(os.path.join(d9, "000000002.jsonl"), (old9, old9))
inbox.SegmentReader(d9).gc(4, 0)
segs9 = sorted(int(n[:9]) for n in os.listdir(d9) if n.endswith(".jsonl"))
ck("R8 다 읽은 세그먼트 정리 = 뒤쪽만 이어지게(2 를 지우면 그보다 오래된 1 도)", segs9 == [3, 4], segs9)
for sg in (5, 6):
    with open(os.path.join(d9, f"{sg:09d}.jsonl"), "w") as f:
        f.write("{}\n")
inbox.SegmentReader(d9).gc(6, 0)
segs9 = sorted(int(n[:9]) for n in os.listdir(d9) if n.endswith(".jsonl"))
ck("R8 보존 기간 안 세그먼트는 그대로 남김(반대 방향)", segs9 == [3, 4, 5, 6], segs9)
os.remove(os.path.join(d9, "000000005.jsonl"))
cv9 = LR.coverage({"evm": (3, 0)}, os.path.join(S, "inbox"))
ck("R8 백업 세그먼트부터 끝까지 번호에 구멍 = gap(이어읽기면 5 를 조용히 건너뜀)", cv9["evm"]["state"] == "gap", cv9["evm"])
an9 = {"evm": inbox.anchor(d9, 4, os.path.getsize(os.path.join(d9, "000000004.jsonl")))}
cv9 = LR.coverage({"evm": (6, 0)}, os.path.join(S, "inbox"), an9)
ck("R8 구멍이 백업 위치보다 앞이면 이어읽기(반대 방향)", cv9["evm"]["state"] == "replay", cv9["evm"])

SOLQ = "So1Quiet11111111111111111111111111111111111"
SIGA = "5" + "Kx9mQ" * 17 + "1"
STK1, STK2 = "Stk1111111111111111111111111111111111111111", "Stk2222222222222222222222222222222222222222"
clear_state()
cfg([{"type": "sol", "address": SOLW}, {"type": "sol", "address": SOLQ}])
make_backup(BK, wallets=[("sol", SOLW), ("sol", SOLQ)])
c9 = dbm.open_db(BK)
c9.execute("INSERT INTO raw_txs VALUES('sol', ?, 900, NULL, ?, ?, '[]', ?)", (SIGA, T_BK - 20 * 3600, json.dumps({"fee_payer": SOLW, "deltas": []}), T_BK))
c9.execute("INSERT INTO raw_txs VALUES('sol', ?, NULL, NULL, ?, '{}', '[]', ?)", (f"stakeopen:{STK1}", T_BK - 40 * 86400, T_BK))
c9.commit()
c9.execute("PRAGMA journal_mode=DELETE")
c9.close()
os.utime(BK, (T_BK, T_BK))
wj("cursor_sol.json", {SOLW: "sigW9", "_slot:" + SOLW: 2000, SOLQ: "sigQ9", "_slot:" + SOLQ: 2100, "_pnv:" + SOLQ: {"sig": ""}, "_cov_ts:" + SOLQ: 5,
                       STK1: "stk1sig", STK2: "stk2sig",
                       "_stk:" + STK1: {"w": SOLW, "t0": 1, "rwd_next": 900, "first": None, "open": True},
                       "_stk:" + STK2: {"w": SOLW, "t0": 1, "rwd_next": 900, "first": [800, 5], "open": True}})
p = LR.plan(BK, now=NOW)
cs = p["files"].get("cursor_sol.json") or {}
ck("R10 기준 서명 있는 지갑 = 그 서명(반대 방향)", cs.get(SOLW) == SIGA and cs.get("_slot:" + SOLW) == 900, {k: cs.get(k) for k in (SOLW, "_slot:" + SOLW)})
ck("R10 기준 서명 없는 지갑 = 커서 빈 글자(처음부터 · 새 관점 아님 — 지운 열쇠면 새 지갑으로 보고 옛 서명 상세를 다시 받음) · 슬롯·대조 장부 지움 · 창 하한 유지",
   cs.get(SOLQ) == "" and "_slot:" + SOLQ not in cs and "_pnv:" + SOLQ not in cs and cs.get("_cov_ts:" + SOLQ) == 5, sorted(cs))
ck("R10 스테이크 기초잔고 표식: 백업에 stakeopen 있음 = 그대로 · 없음 = 내림(다시 냄)",
   (cs.get("_stk:" + STK1) or {}).get("open") is True and (cs.get("_stk:" + STK2) or {}).get("open") is False,
   (cs.get("_stk:" + STK1), cs.get("_stk:" + STK2)))

clear_state()
make_backup(BK, wallets=[("eth", W1), ("eth", W2), ("sol", SOLW)], offs=(("evm", 1, 0), ("sol", 1, 0), ("bsc", 1, 0), ("ex", 1, 0)))
cfg([{"type": "evm", "chain": "eth", "address": W1.upper().replace("0X", "0x")}, {"type": "sol", "address": SOLW}])
p = LR.plan(BK, now=NOW)
ck("R9 백업 지갑 중 지금 설정에 없는 것 = 계획에 목록(주소 대소문자 무관 · 솔라나 그대로)", p.get("wallets_missing") == [f"eth:{W2}"], p.get("wallets_missing"))
out9 = io.StringIO()
with redirect_stdout(out9):
    LR._print_plan(p)
ck("R9 미리보기에 모자란 지갑 안내", W2 in out9.getvalue() and "--force" in out9.getvalue(), out9.getvalue()[-400:])
had_live = os.path.exists(paths.DB_PATH)
err9 = None
out9 = io.StringIO()
try:
    with redirect_stdout(out9):
        LR.main(["restore", BK, "--apply", "--no-proc-check"])
except SystemExit as e:
    err9 = str(e)
ck("R9 적용 거부(--force 없으면) · 모자란 지갑 출력 · 원장 무변", err9 is not None and W2 in err9 and "--force" in err9
   and os.path.exists(paths.DB_PATH) == had_live, (err9, had_live))
out9 = io.StringIO()
with redirect_stdout(out9):
    rc9 = LR.main(["restore", BK, "--apply", "--no-proc-check", "--force"])
ck("R9 --force 면 적용", rc9 == 0 and os.path.exists(paths.DB_PATH), out9.getvalue()[-300:])
cfg([{"type": "evm", "chain": "eth", "address": W1}, {"type": "evm", "chain": "eth", "address": W2}, {"type": "sol", "address": SOLW}])
p = LR.plan(BK, now=NOW)
ck("R9 지갑이 다 있으면 목록 비어 거부 없음(반대 방향)", p.get("wallets_missing") == [], p.get("wallets_missing"))
T.finish()
