#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402, F401
from _ingest import W, Reader, Writer  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
os.environ["TJ_NEGABS"] = "0"
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import evm_watch  # noqa: E402
import health  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
X, Y = "0x" + "b8" * 20, "0x" + "b9" * 20
TK6, TKP, TKN = "0x" + "d6" * 20, "0x" + "d7" * 20, "0x" + "d8" * 20
E6 = 10 ** 6
NOW = int(time.time())


def leg(f, t, ca, v, dec=None):
    return {"from": {"hash": f}, "to": {"hash": t}, "token": {"address": ca, "symbol": "T" + ca[2:4], "decimals": dec, "type": "ERC-20"},
            "total": {"value": str(v)}}


def snap(hx, ts, blk, frm, to, legs):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": "0", "fee": {"value": "0"}, "status": "ok", "raw_input": "0xa9059cbb",
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": legs, "internal": []}


def h(n):
    return "0x" + ("%064x" % n)


statefile.atomic_write_json(paths.state("token_nodec_eth.json"), {TKN: {"n": 9, "first": NOW - 99999, "perm": NOW - 9999, "last": NOW, "why": "빈 반환(0x)", "skips": []}})
w = evm_watch.ChainWatcher.__new__(evm_watch.ChainWatcher)
w.chain, w.wallets, w.writer = "eth", [W.lower()], Writer()
w.rpc_meta, w.rpc_meta_path = {}, paths.state("rpc_token_meta_eth.json")
CALLS = []
MODE = {"m": "ok"}


def fake_rpc(method, params):
    CALLS.append((method, params[0].get("to")))
    if MODE["m"] == "down":
        raise RuntimeError("rpc 일시 장애(합성)")
    return "0x" + "%064x" % 6


w._rpc_call = fake_rpc
s1 = snap(h(1), NOW - 3 * 86400, 100, X, W, [leg(X, W, TK6, 10 * E6)])
w.emit(h(1), s1, 200)
r1 = w.writer.recs[-1]["snapshot"]["token_transfers"][0]["token"]
chk(r1.get("decimals") == 6 and len(CALLS) == 1, "A1 내 지갑 레그 null 자릿수 = 보내기 전 RPC 로 6 채움(종전 null)", (r1, CALLS))
chk((statefile.read_json(w.rpc_meta_path, {}) or {}).get(TK6) == 6, "A1 자릿수 캐시(rpc_token_meta_eth.json)에 남김")
w.emit(h(2), snap(h(2), NOW - 3 * 86400, 101, X, W, [leg(X, W, TK6, E6)]), 200)
chk(len(CALLS) == 1 and w.writer.recs[-1]["snapshot"]["token_transfers"][0]["token"]["decimals"] == 6, "A1 같은 토큰 두 번째 = 캐시(RPC 0회)", CALLS)
CALLS.clear()
s2 = snap(h(3), NOW, 102, X, Y, [leg(X, Y, TKP, 5 * E6), leg(X, W, TKP, 0), leg(X, W, TKN, 7, dec="9")])
w.emit(h(3), s2, 200)
t2 = [x["token"]["decimals"] for x in w.writer.recs[-1]["snapshot"]["token_transfers"]]
chk(t2 == [None, None, "9"] and not CALLS, "A2 남의 레그·0 수량·자릿수 있는 레그 = 그대로 · RPC 0회", (t2, CALLS))
MODE["m"] = "down"
ok9 = True
try:
    w.emit(h(4), snap(h(4), NOW, 103, X, W, [leg(X, W, TKP, 5 * E6)]), 200)
except Exception as e:  # noqa: BLE001
    ok9 = repr(e)
chk(ok9 is True and w.writer.recs[-1]["snapshot"]["token_transfers"][0]["token"]["decimals"] is None,
    "A3 RPC 일시 실패 = 예외 없이 null 그대로 보냄(종전 동작 · 보류·커서 정지 없음)", ok9)
n9 = len(CALLS)
w.emit(h(7), snap(h(7), NOW, 103, X, W, [leg(X, W, TKP, E6)]), 200)
chk(len(CALLS) == n9, "A3 실패한 토큰 = 10분 동안 다시 안 물음(장애 때 방출마다 타임아웃 금지)", CALLS)
w.writer.recs.pop()
MODE["m"] = "ok"
n9 = len(CALLS)
w.emit(h(5), snap(h(5), NOW, 104, X, W, [leg(X, W, TKN, 3)]), 200)
chk(w.writer.recs[-1]["snapshot"]["token_transfers"][0]["token"]["decimals"] is None and len(CALLS) == n9,
    "A3 decimals() 영구 불능 확정 토큰(token_nodec perm) = RPC 없이 null 그대로(18 가정 · 종전)", CALLS)

c = core.Core(config.load_config())
c.conn.commit()
HS = health.settings({"health": {"units": ["tj-core"]}})


def feed(rec_snap, hx):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": rec_snap, "ts": 1}]), 0, 0)


def dec_of(ca):
    r = c.conn.execute("SELECT decimals FROM assets WHERE address=?", (ca,)).fetchone()
    return r[0] if r else "없음"


def wallet_qty(ca):
    r = c.conn.execute("SELECT p.qty_norm FROM positions p JOIN assets a ON a.group_id=p.group_id WHERE a.address=? AND p.location=?",
                       (ca, f"wallet:eth:{W.lower()}")).fetchone()
    return r[0] if r else None


def wait_items():
    return (statefile.read_json(c.DEC_WAIT_PATH, {}) or {}).get("items") or {}


def ev(open_ids=(), now=None):
    obs = {"now": now or time.time(), "pm2": {"tj-core": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {},
           "sources": [], "hb": {"core": {"ts": now or time.time(), "ok": True}},
           "decwait": statefile.read_json(c.DEC_WAIT_PATH, None), "decis": statefile.read_json(c.DEC_ISSUES_PATH, None)}
    return {x["id"]: x for x in health.evaluate(obs, HS, open_ids)}.get("ledger:decimals_wait")


feed(w.writer.recs[0]["snapshot"], h(1))
chk(c.decimals_pass() == 0 and os.path.exists(c.DEC_WAIT_PATH), "B0 소비 루프 자릿수 패스(decimals_pass) = 해결 요청 처리 + 대기 세기(파일 생성)")
chk(dec_of(TK6) == 6 and wallet_qty(TK6) is not None and float(wallet_qty(TK6)) == 10.0, "B1 채워진 레코드 = 6 자리 저장 · 정확한 수량 10", (dec_of(TK6), wallet_qty(TK6)))
chk(not wait_items() and ev() is None, "B1 자릿수 대기 0 · 상태 패널 줄 없음(평소)", (wait_items(), ev()))

feed(w.writer.recs[-2]["snapshot"], h(4))
c._dec_wait_scan(force=True)
aidp = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKP,)).fetchone()[0]
wi = wait_items()
chk(dec_of(TKP) is None and list(wi) == [str(aidp)] and wi[str(aidp)]["est"] is False, "B2 남은 창 = NULL 자산 기장 · 대기 1개 기록", (dec_of(TKP), wi))
e2 = ev()
chk(e2 and e2["level"] == "warn" and "1개" in e2["title"] and not e2.get("chip"), "B2 상태 패널 ledger:decimals_wait 노랑(주의) 1개", e2)
since0 = wi[str(aidp)]["since"]
c._dec_wait_scan(force=True)
chk(wait_items()[str(aidp)]["since"] == since0, "B2 다시 세도 처음 본 시각 유지", wait_items())
e2b = ev(now=since0 + 86400 + 60)
chk(e2b and e2b["level"] == "warn" and e2b.get("chip") == "24시간 넘음", "B2 24시간 넘음 = 칩", e2b)

q_before = float(wallet_qty(TKP))
feed(snap(h(6), NOW + 60, 105, W, X, [leg(W, X, TKP, 5 * E6, dec="6")]), h(6))
chk(float(wallet_qty(TKP)) == 0.0 and q_before > 0, "B3 뒤 출금이 와도 앞 입금이 이미 기장 — 지갑 음수 없음(순서 그대로)", (q_before, wallet_qty(TKP)))
iss = (statefile.read_json(c.DEC_ISSUES_PATH, {}) or {}).get("items") or {}
c._dec_wait_scan(force=True)
chk(dec_of(TKP) == 6 and not iss.get(str(aidp)) and str(aidp) not in wait_items(),
    "B3 자릿수 6 관측 = 바로 채움 + 재정규화(세션31 #1 · 종전 '채움 대기' 없음) — 대기 줄에서 빠짐", (dec_of(TKP), iss.get(str(aidp)), wait_items()))
c.conn.execute("UPDATE assets SET decimals=6 WHERE asset_id=?", (aidp,))
c.conn.commit()
statefile.atomic_write_json(c.DEC_ISSUES_PATH, {"items": {}})
c._dec_wait_scan(force=True)
e3 = ev(open_ids=("ledger:decimals_wait",))
chk(not wait_items() and e3 and e3["level"] == "ok", "B3 채워지면 0개 · 열린 사건 = 정상으로 닫힘", (wait_items(), e3))

feed(w.writer.recs[-1]["snapshot"], h(5))
c._dec_wait_scan(force=True)
aidn = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKN,)).fetchone()[0]
e4 = ev()
chk(wait_items().get(str(aidn), {}).get("est") is True and e4 and e4["level"] == "ok" and "추정" in e4["detail"],
    "B4 decimals() 영구 불능 확정 토큰 = 18 가정 '추정' 정보(주의 아님)", (wait_items(), e4))
c.conn.close()
T.finish()
