#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import urllib.request  # noqa: E402

import _net_sites_table as NS  # noqa: E402

W = "0x" + "a1" * 20
W2 = "0x" + "b2" * 20
TOK = "0x" + "c3" * 20
TX = "0x" + "d4" * 32
NOW_MS = int(C.NOW * 1000)
SEC = {"tg_token": "123456:casNETtgToken0001", "api_key": "casNETapiKey0001", "api_secret": "casNETapiSecret0001",
       "cg_key": "CG-casNETdemoKey0001", "ton_key": "a" * 64, "internal": "casNETinternalToken0001casNETinternal01",
       "hb_ping": "casNEThbPing0001", "upbit_access": "casNETupbitAccess01", "upbit_secret": "casNETupbitSecret01",
       "okx_key": "casNETokxKey0001", "okx_secret": "casNETokxSecret0001", "okx_pass": "casNETokxPass01",
       "es_key": "casNETesKey0001"}
EXPECT = {k: 1 for k in NS.cassette_sites()}
EXPECT.update({"sol_base::Rpc.batch": 2})


def rpc_ok(rq, result):
    j = rq.json() or {}
    return {"jsonrpc": "2.0", "id": j.get("id", 1), "result": result}


def respond(rq):
    h, p, q = rq.host, rq.path, rq.query
    if h == "api.telegram.org":
        return {"ok": True, "result": {"message_id": 11 if p.endswith("/sendMessage") else 12}}
    if h == "data.net-sites.invalid":
        return {"ok": 1}
    if h == "api.coingecko.com" and p == "/api/v3/ping":
        return {"gecko_says": "pong"}
    if h == "open.net-sites.invalid":
        return {"ok": 2}
    if h == "broker.net-sites.invalid":
        return {"acct": "T-1"}
    if h == "127.0.0.1" and p == "/ready":
        return {"readyConnections": 4}
    if h == "127.0.0.1" and p == "/api/health":
        return {"ok": True, "internal": rq.headers.get("x-tj-internal") == SEC["internal"]}
    if h == "api.binance.com" and p == "/sapi/v1/capital/deposit/address":
        return {"address": W, "coin": q.get("coin"), "tag": ""}
    if h == "api.binance.com" and p == "/api/v3/time":
        return {"serverTime": NOW_MS}
    if h == "api.binance.com" and p == "/api/v3/ticker/price":
        return {"symbol": q.get("symbol"), "price": "2.5"}
    if h == "api.bybit.com":
        return {"retCode": 0, "retMsg": "OK", "result": {"list": []}}
    if h == "api.etherscan.io":
        return {"status": "1", "message": "OK", "result": []}
    if h == "hb.net-sites.invalid":
        return "OK"
    if h == "fapi.binance.com":
        return []
    if h == "base.blockscout.com" and p.endswith("/nft"):
        return {"items": [{"token": {"address": TOK}, "id": "7"}], "next_page_params": None}
    if h == "base.blockscout.com" and p.startswith("/api/v2/transactions/"):
        return {"hash": TX, "from": {"hash": W}, "to": {"hash": W2}}
    if h.startswith("solrpc") or h == "solmain.net-sites.invalid":
        m = (rq.json() or {}).get("method")
        return rpc_ok(rq, {"getSlot": 321, "getBalance": {"value": 5}, "getSignatureStatuses": {"value": [None]}}.get(m, 1))
    if h == "api.net-sites.invalid":
        return {"ok": True}
    if h == "query1.finance.yahoo.com":
        return {"chart": {"result": [{"meta": {"symbol": "TSTA", "regularMarketPrice": 3.25}}], "error": None}}
    if h == "api.hyperliquid.xyz":
        return {"universe": []}
    if h == "www.okx.com":
        return {"code": "0", "data": [{"chainIndex": "8453", "tokenContractAddress": W2, "price": "1.5"}]}
    if h == "api.rabby.io":
        return {"total_usd_value": 12.5}
    if h == "eth.blockscout.com" and p == "/api":
        return {"status": "1", "message": "OK", "result": []}
    if h == "eth.blockscout.com":
        return {"coin_balance": "1000"}
    if h == "toncenter.com":
        return {"ok": True, "last": {"seqno": 1}}
    if h == "api.upbit.com":
        return []
    if h == "api.gopluslabs.io":
        return {"code": 1, "message": "OK", "result": {}}
    if h == "api.wormholescan.io":
        return {"operations": []}
    raise AssertionError("모르는 요청 " + rq.url)


CFG = {"chains": {"base": {"blockscout": "https://base.blockscout.com", "discovery": "explorer"}}, "wallets": [],
       "sol": {"rpc": "https://solmain.net-sites.invalid"}, "web": {"port": 8090}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import paths  # noqa: E402
import alert_bot  # noqa: E402
import bf_engine  # noqa: E402
import cgkey  # noqa: E402
import chk_collect  # noqa: E402
import depaddr  # noqa: E402
import exf_net  # noqa: E402
import flow_trace  # noqa: E402
import health  # noqa: E402
import liq_watch  # noqa: E402
import login_auth  # noqa: E402
import lpchain  # noqa: E402
import lpsol  # noqa: E402
import onboarding  # noqa: E402
import other_assets  # noqa: E402
import perp_dex  # noqa: E402
import pricing  # noqa: E402
import rabby  # noqa: E402
import recon  # noqa: E402
import review_daily  # noqa: E402
import sale_match  # noqa: E402
import sol_base  # noqa: E402
import ton_watch  # noqa: E402
import upbit_link  # noqa: E402
import view_workers  # noqa: E402
import web  # noqa: E402
import xchain_match  # noqa: E402
from brokers import base as broker_base  # noqa: E402

with open(login_auth.INTERNAL_PATH, "w", encoding="ascii") as f:
    f.write(SEC["internal"] + "\n")
os.makedirs(paths.state("seed_local"), exist_ok=True)
with open(paths.state("seed_local", "lp_managers.json"), "w", encoding="utf-8") as f:
    json.dump({"base": {TOK: {"proto": "uni_v3"}}}, f)


class _OneLap(BaseException):
    pass


class OriginOnce(view_workers.WorkersMixin):

    def __init__(self, cfg):
        self.cfg = cfg
        self._origin_pending = {TX}
        self._origin_lock = threading.Lock()

    def _origin_net_hints(self, txs):
        return {}

    def soft_invalidate(self, kick=True):
        raise _OneLap()


def _origin_worker():
    try:
        OriginOnce(CFG)._origin_worker()
    except _OneLap:
        pass
    return C.read_any(paths.state("tx_origin_cache.json"))


def _heartbeat():
    mon = health.Monitor(CFG)
    sent = mon.heartbeat({"heartbeat_url": "https://hb.net-sites.invalid/ping/" + SEC["hb_ping"], "heartbeat_sec": 300}, C.NOW)
    for th in threading.enumerate():
        if th.name == "tj-health-hb":
            th.join(10)
    return {"sent": sent, "busy": mon.hb_busy}


def _sol_open():
    with bf_engine.sol_open(urllib.request.Request("https://open.net-sites.invalid/v1/sol_open", headers={"Accept": "application/json"}), 10) as r:
        return json.loads(r.read().decode())


def _es_http():
    sc = flow_trace.Scanner(CFG, {}, sleep=0)
    return sc._es_http("https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist&address=%s&apikey=%s" % (W, SEC["es_key"]))


def _ton(key):
    tc = ton_watch.TonClient({}, base="https://toncenter.com/api/v3", key=key, min_interval=0)
    return tc.req("GET", "/addressInformation" if key else "/masterchainInfo", {"address": W} if key else None)


def _sol_rpc():
    return sol_base.Rpc(CFG)


def _tracer():
    return xchain_match.Tracer(CFG, {}, None, None, sleep=0)


SIG = "%d" % NOW_MS
RUN = {
    "alert_bot::send_message": lambda: alert_bot.send_message(SEC["tg_token"], "1001", "시험 메시지", silent=True),
    "alert_bot::send_photo": lambda: alert_bot.send_photo(SEC["tg_token"], "1001", b"fakepng", caption="시험 그림"),
    "bf_engine::http_request": lambda: bf_engine.http_json("https://data.net-sites.invalid/v1/plain", timeout=7, retries=1),
    "bf_engine::sol_open": _sol_open,
    "brokers.base::default_http": lambda: broker_base.default_http("GET", "https://broker.net-sites.invalid/v1/account",
                                                                   headers={"Authorization": "Bearer " + SEC["api_key"]}),
    "chk_collect::collect_tunnel": lambda: chk_collect.collect_tunnel({"tunnel": {"unit": "tj-tunnel", "ready_url": "http://127.0.0.1:20241/ready"}}, None),
    "depaddr::http_get": lambda: depaddr.http_get("https://api.binance.com/sapi/v1/capital/deposit/address?coin=TSTA&timestamp=%s&signature=%s"
                                                  % (SIG, "ab" * 32), {"X-MBX-APIKEY": SEC["api_key"]}, ex="binance"),
    "exf_net::_clock_fetch": lambda: exf_net._clock_fetch("binance"),
    "exf_net::http_json": lambda: exf_net.http_json("https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED",
                                                    headers={"X-BAPI-API-KEY": SEC["api_key"], "X-BAPI-TIMESTAMP": SIG, "X-BAPI-SIGN": "cd" * 32}),
    "flow_trace::Scanner._es_http": _es_http,
    "health::Monitor.heartbeat._go": _heartbeat,
    "liq_watch::_http_default": lambda: liq_watch._http_default("GET", "https://fapi.binance.com/fapi/v2/positionRisk?timestamp=%s&signature=%s"
                                                                % (SIG, "ef" * 32), headers={"X-MBX-APIKEY": SEC["api_key"]}),
    "lpchain::list_wallet_positions": lambda: lpchain.list_wallet_positions(CFG, "base", W),
    "lpsol::_rpc": lambda: lpsol._rpc(["https://solrpc1.net-sites.invalid"], "getSlot", []),
    "onboarding::_http": lambda: onboarding._http("https://api.net-sites.invalid/check", headers={"X-API-KEY": SEC["api_key"]}),
    "other_assets::default_http_get": lambda: other_assets.default_http_get("https://query1.finance.yahoo.com/v8/finance/chart/TSTA"),
    "perp_dex::_http_default": lambda: perp_dex._http_default("https://api.hyperliquid.xyz/info", body={"type": "meta"}),
    "pricing::_gj": lambda: pricing._gj("https://api.binance.com/api/v3/ticker/price?symbol=TSTAUSDT"),
    "pricing::okx_dex_prices": lambda: pricing.okx_dex_prices({"key": SEC["okx_key"], "secret": SEC["okx_secret"], "passphrase": SEC["okx_pass"]},
                                                              [("base", W2)]),
    "rabby::http_get": lambda: rabby.http_get("https://api.rabby.io/v1/user/total_balance?id=" + W),
    "recon::_gj": lambda: recon._gj("https://eth.blockscout.com/api/v2/addresses/" + W, tries=1),
    "recon::_rpc": lambda: recon._rpc("https://solrpc2.net-sites.invalid", "getBalance", ["TestWallet1"]),
    "review_daily::_get_json": lambda: review_daily._get_json(CFG, "/api/health", hosts=(8090, ["127.0.0.1"])),
    "sale_match::http_get_json": lambda: sale_match.http_get_json("https://eth.blockscout.com/api?module=account&action=tokentx&address=" + W),
    "sol_base::Rpc._call": lambda: _sol_rpc()._call("https://solmain.net-sites.invalid", "getSlot", []),
    "sol_base::Rpc.batch": lambda: _sol_rpc().batch("getBalance", [["TestWallet1"], ["TestWallet2"]]),
    "ton_watch::TonClient.req": lambda: _ton(""),
    "upbit_link::Upbit.get": lambda: upbit_link.Upbit(SEC["upbit_access"], SEC["upbit_secret"]).get("/v1/accounts"),
    "view_workers::WorkersMixin._origin_worker": _origin_worker,
    "web::_goplus_fetch": lambda: web._goplus_fetch("1", W),
    "xchain_match::Tracer._get": lambda: _tracer()._get("https://api.wormholescan.io/api/v1/operations?txHash=" + TX),
    "xchain_match::Tracer._post": lambda: _tracer()._post("https://solrpc3.net-sites.invalid", "getSignatureStatuses", [["TestSig1"]]),
    "bf_engine::http_request[key]": lambda: cgkey.bf_via(timeout=9)("https://api.coingecko.com/api/v3/ping", {"x-cg-demo-api-key": SEC["cg_key"]},
                                                                    "api.coingecko.com#key"),
    "recon::_rpc[direct]": lambda: recon._rpc("https://solrpc2.net-sites.invalid", "getBalance", ["TestWallet1"], gap=False),
    "ton_watch::TonClient.req[key]": lambda: _ton(SEC["ton_key"]),
}


def plain(o):
    if isinstance(o, (bytes, bytearray)):
        return bytes(o).decode("utf-8", "replace")
    if isinstance(o, (list, tuple)):
        return [plain(x) for x in o]
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else json.dumps(plain(k))): plain(v) for k, v in o.items()}
    if isinstance(o, set):
        return sorted(plain(x) for x in o)
    return o


def scenario(cas):
    out = {}
    for name in NS.cassette_sites():
        n0 = cas.served
        try:
            r = {"ret": plain(RUN[name]())}
        except Exception as e:   # noqa: BLE001
            r = {"exc": type(e).__name__}
        r["n"] = cas.served - n0
        out[name] = r
    return out


cas = C.Cassette("net_sites", secrets=SEC, responder=respond)
if cas.ready(T):
    out, why = cas.run(scenario, cas)
    T.chk(why is None and isinstance(out, dict), "자리 전부 한 바퀴(새 요청·깨진 전송 없음)", why)
    out = out or {}
    T.chk(sorted(out) == sorted(RUN) == sorted(EXPECT), "부른 자리 = 덮음 표의 카세트 자리(+ 덧갈래)", sorted(set(RUN) ^ set(EXPECT)))
    bad_n = {k: [EXPECT.get(k), (out.get(k) or {}).get("n")] for k in EXPECT if (out.get(k) or {}).get("n") != EXPECT[k]}
    T.chk(not bad_n, "[1] 자리마다 요청 수 = 기대 수(안 나간 길 · 늘어난 길 0)", bad_n)
    bad_x = {k: v.get("exc") for k, v in out.items() if "exc" in v}
    T.chk(not bad_x, "[1] 자리마다 예외 없이 결과", bad_x)
    T.chk((out.get("review_daily::_get_json") or {}).get("ret") == {"ok": True, "internal": True},
          "루프백 tj-web 조회 = 내부 토큰 헤더(X-TJ-Internal) 실림", out.get("review_daily::_get_json"))
    T.chk((out.get("health::Monitor.heartbeat._go") or {}).get("ret") == {"sent": True, "busy": False},
          "하트비트 스레드 = 보냄 · 끝남(join)", out.get("health::Monitor.heartbeat._go"))
    T.chk((out.get("view_workers::WorkersMixin._origin_worker") or {}).get("ret", {}).get(TX, {}).get("chain") == "base",
          "발신 조회 워커 한 바퀴 = 캐시에 출처 기록", out.get("view_workers::WorkersMixin._origin_worker"))
    cas.golden(T, {"sites": out})
    cas.check(T)
T.finish()
