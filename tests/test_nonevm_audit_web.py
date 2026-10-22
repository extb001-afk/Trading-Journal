#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import http.client  # noqa: E402

import address_codec as ac  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402

chk = T.chk
NOW = int(time.time())
A = N.OWN["tron"][0]
X = N.EXT["tron"]
X2 = "41" + "98" * 20
EVM_D = "0x" + "9c" * 20
SOL_D = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["wallets"] = [dict(w, chain=w.get("chain") or ("sol" if w.get("type") == "sol" else "eth")) for w in cfg["wallets"]]
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
cfg["exchange_addresses"] = [{"exchange": "binance", "chain": "tron", "address": ac.tron_display(X2)},
                             {"exchange": "upbit", "chain": "eth", "address": "0x" + "9d" * 20}]
cfg["web"] = {"login": {"enabled": False}}
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())
c._drain_stream("tron", Reader([N.rec("tron", "c3" * 32, NOW - 20 * 86400, [(A, "native", 10_000_000)])]), 0, 0)
c._drain_stream("tron", Reader([N.rec("tron", "c4" * 32, NOW - 10 * 86400, [(A, "native", -1_001_000)], fees=[(A, 1_000)],
                                      moves=[("native", A, X, 1_000_000)])]), 0, 0)
c._drain_stream("tron", Reader([N.rec("tron", "c5" * 32, NOW - 5 * 86400, [(A, ("token", N.TOK["tron"], "USDT", 6), 5_000_000_000)])]), 0, 0)
c.conn.commit()
FAKE_AID = c.conn.execute("SELECT asset_id, group_id FROM assets WHERE kind='token' AND chain='tron'").fetchone()
c.conn.close()
json.dump({"version": 1, "decisions": {N.EXT["sui"]: {"verdict": "exchange", "exchange": "okx", "chains": ["sui"], "ts": 1},
                                       EVM_D: {"verdict": "exchange", "exchange": "bybit", "chains": ["eth"], "ts": 1},
                                       SOL_D: {"verdict": "exchange", "exchange": "gate", "chains": ["sol"], "ts": 1}}},
          open(os.path.join(paths.STATE_DIR, "outflow_decisions.json"), "w"))

import acct_norm  # noqa: E402
import pricing  # noqa: E402
import web  # noqa: E402


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c9, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
try:
    st = b.build()
except Exception as e:   # noqa: BLE001
    import traceback
    traceback.print_exc()
    st = {"_exc": f"{type(e).__name__}: {e}"}
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
chk(bool(f), "전제: 빌드 성공", st if isinstance(st, dict) and st.get("_exc") else "fields 없음")

net = {r.get("addr"): r.get("net") for r in f.get("depositRows") or []}
chk(net.get(N.EXT["sui"]) == "Sui" and net.get(ac.tron_display(X2)) == "Tron",
    "E 새 체인 입금 주소 = 체인 이름(보낸 내역 판정 Sui 0x+64 · 설정 Tron T…)", net)
chk(net.get(EVM_D) == "EVM" and net.get(SOL_D) == "SOL" and net.get("0x" + "9d" * 20) == "EVM", "E EVM·솔라나 라벨 종전 그대로", net)

chk(FAKE_AID is not None and FAKE_AID["group_id"] in (getattr(b, "_risk_quarantined", None) or set()),
    "Q Tron 가짜 'USDT'(비공식 계약 · 무상 유입) = 기존 격리 루프가 격리(보유·총자산 밖)", (dict(FAKE_AID) if FAKE_AID else None, getattr(b, "_risk_quarantined", None)))

sc = f.get("srcChips") or []
chk([x.get("label", "")[:3] for x in sc[:3]] == ["EVM", "Sol", "BSC"] and len(sc) == 4
    and sc[3].get("label") == "Tron · TronGrid" and sc[3].get("short") == "Tron 1지갑" and ("스캔" in str(sc[3].get("addr")) or "대기" in str(sc[3].get("addr"))),
    "S 수집원 칩: 종전 3줄 + Tron 한 줄(지갑 1 · 마지막 스캔)", sc)

import settings_store  # noqa: E402

srv = web.QuietHTTPServer(("127.0.0.1", 0), web.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
TOK = settings_store.csrf_token()


def post(path, body):
    cn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    try:
        cn.request("POST", path, body=json.dumps(body).encode(),
                   headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{PORT}", "X-TJ-CSRF": TOK})
        r = cn.getresponse()
        raw = r.read().decode() or "{}"
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, {"_raw": raw[:200]}
    finally:
        cn.close()


def chain_wallets():
    return [(w.get("chain"), w.get("address"), w.get("label")) for w in (json.load(open(CFG_PATH)).get("chain_wallets") or [])]


dests = getattr(b, "_outflow_dests", None) or {}
chk(X in dests and dests.get(X) == ["tron"], "전제: Tron 목적지가 보낸 내역에 있음(체인 tron)", dests)
cw0 = json.load(open(CFG_PATH)).get("wallets")
s1, r1 = post("/api/outflow_resolve", {"address": X, "verdict": "own", "alias": "트론 둘째"})
cw = chain_wallets()
chk(s1 == 200 and ("tron", ac.tron_display(X), "트론 둘째") in cw and json.load(open(CFG_PATH)).get("wallets") == cw0,
    "D Tron 목적지 '내 지갑' = chain_wallets 등록(T… 표시 꼴 · 이름) · EVM·솔라나 wallets 무변", (s1, r1, cw))
chk(((r1.get("decision") or {}).get("verdict"), (r1.get("decision") or {}).get("chains")) == ("own", ["tron"]), "D 판정 기록 own · chains [tron]", r1)
s2, r2 = post("/api/outflow_resolve", {"address": X, "verdict": "own", "alias": "트론 둘째"})
chk(s2 == 200 and len([w for w in chain_wallets() if w[0] == "tron"]) == 2, "D 같은 요청 반복 = 200 · 지갑 중복 없음(멱등)", (s2, r2, chain_wallets()))

s3, r3 = post("/api/wallet_alias", {"address": N.OWN["sui"][1], "alias": "수이 둘째"})
s4, r4 = post("/api/wallet_alias", {"address": "41" + "0a" * 20, "alias": "트론 키"})
s7, r7 = post("/api/wallet_alias", {"address": N.OWN["ton"][1], "alias": "톤 둘째"})
s5, r5 = post("/api/wallet_alias", {"address": "hello-world", "alias": "x"})
s6, r6 = post("/api/wallet_alias", {"address": EVM_D, "alias": "evm"})
chk(s3 == 200 and s4 == 200 and s7 == 200, "F 새 체인 주소(Sui 0x+64 · Tron 41… · TON 0_…)에 이름 저장", (s3, r3, s4, r4, s7, r7))
chk(s5 == 400 and s6 == 200, "F 주소 아닌 값 = 거부 · EVM 주소 = 종전 그대로", (s5, r5, s6, r6))
srv.shutdown()
srv.server_close()
T.finish()
