#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402

shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
json.dump({"wallets": [], "backfill_months": 3, "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import alert_prefs as AP  # noqa: E402
import alert_watch  # noqa: E402
import exf_net  # noqa: E402
import exhalt  # noqa: E402
import exwallet as W  # noqa: E402


ENV = {"UPBIT_ACCESS": "ua", "UPBIT_SECRET": "us", "TJ_BITHUMB_KEY": "bk", "TJ_BITHUMB_SECRET": "bs", "TJ_BINANCE_KEY": "nk", "TJ_BINANCE_SECRET": "ns",
       "TJ_BYBIT_KEY": "yk", "TJ_BYBIT_SECRET": "ys", "TJ_OKX_KEY": "ok", "TJ_OKX_SECRET": "os", "TJ_OKX_PASSPHRASE": "op",
       "TJ_KUCOIN_KEY": "kk", "TJ_KUCOIN_SECRET": "ks", "TJ_KUCOIN_PASSPHRASE": "kp", "TJ_GATE_KEY": "gk", "TJ_GATE_SECRET": "gs"}
NOW = 1_900_000_000.0


def resp(ex, tab):
    if ex == "upbit":
        st = {(True, True): "working", (True, False): "deposit_only", (False, True): "withdraw_only", (False, False): "paused"}
        return [{"currency": c, "net_type": n, "wallet_state": st[v], "block_state": "normal"} for c, ns in tab.items() for n, v in ns.items()]
    if ex == "bithumb":
        return {"status": "0000", "data": [{"currency": c, "net_type": n, "deposit_status": int(v[0]), "withdrawal_status": int(v[1])}
                                           for c, ns in tab.items() for n, v in ns.items()]}
    if ex == "binance":
        return [{"coin": c, "isLegalMoney": False, "networkList": [{"network": n, "depositEnable": v[0], "withdrawEnable": v[1]} for n, v in ns.items()]}
                for c, ns in tab.items()] + [{"coin": "KRW", "isLegalMoney": True, "networkList": []}]
    if ex == "bybit":
        return {"retCode": 0, "result": {"rows": [{"coin": c, "chains": [{"chain": n, "chainDeposit": str(int(v[0])), "chainWithdraw": str(int(v[1]))}
                                                                         for n, v in ns.items()]} for c, ns in tab.items()]}}
    if ex == "okx":
        return {"code": "0", "data": [{"ccy": c, "chain": f"{c}-{n}", "canDep": v[0], "canWd": v[1]} for c, ns in tab.items() for n, v in ns.items()]}
    if ex == "kucoin":
        return {"code": "200000", "data": [{"currency": c, "chains": [{"chainName": n, "isDepositEnabled": v[0], "isWithdrawEnabled": v[1]}
                                                                       for n, v in ns.items()]} for c, ns in tab.items()]}
    return [{"currency": c, "delisted": False, "chains": [{"name": n, "deposit_disabled": not v[0], "withdraw_disabled": not v[1]} for n, v in ns.items()]}
            for c, ns in tab.items()] + [{"currency": "OLD", "delisted": True, "chains": [{"name": "ETH", "deposit_disabled": True, "withdraw_disabled": True}]}]


HOST = {"api.upbit.com": "upbit", "api.bithumb.com": "bithumb", "api.binance.com": "binance", "api.bybit.com": "bybit", "www.okx.com": "okx",
        "api.kucoin.com": "kucoin", "api.gateio.ws": "gate"}
NET = {"tab": {}, "calls": [], "fail": {}}


class Resp:

    def __init__(self, body, enc=""):
        self.body, self.headers, self.length = body, {"Content-Encoding": enc} if enc else {}, None

    def read(self, n=-1):
        return self.body if n is None or n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_send(req, timeout=20):
    url = req.full_url
    ex = HOST[url.split("/")[2]]
    NET["calls"].append((ex, url, {k.lower(): v for k, v in req.header_items()}))
    f = NET["fail"].get(ex)
    if f:
        raise f
    return Resp(gzip.compress(json.dumps(resp(ex, NET["tab"].get(ex, BASE))).encode()), "gzip")


def http_err(code, body=b"x", hdrs=None):
    return urllib.error.HTTPError("https://x.example", code, "합성", hdrs or {}, io.BytesIO(body))


AUTH_HDR = ("authorization", "x-mbx-apikey", "x-bapi-api-key", "ok-access-key")
OPEN = {"BTC": {"MAIN": (True, True)}, "ETH": {"ETH": (True, True), "ARB": (True, True)}}
BASE = dict(OPEN, **{f"C{i:02d}": {"N": (True, True)} for i in range(40)})


def run(tab_by_ex=None, now=NOW, env=ENV):
    NET["tab"] = tab_by_ex or {}
    return W.round_once(env, now, None, fake_send)


def st_ex(ex):
    return W.load()["ex"].get(ex) or {}


print("[E] 거래소별 응답 → {코인: {네트워크: [입금, 출금]}}")
tab = {"AAA": {"X": (False, True), "Y": (True, True)}, "BBB": {"Z": (True, False)}}
for ex in W.EXCHANGES:
    p = W.parse(ex, resp(ex, tab))
    T.chk(p.get("AAA", {}).get("Y" if ex != "okx" else "AAA-Y") == [True, True] and [v for v in p["BBB"].values()] == [[True, False]]
          and any(v == [False, True] for v in p["AAA"].values()) and "KRW" not in p and "OLD" not in p, f"E1 {ex} 파싱(법정화폐·상장 폐지 뺌)", p)
T.chk(W.parse("upbit", [{"currency": "Q", "net_type": "Q", "wallet_state": "unsupported"}]) == {}, "E2 업비트 unsupported = 상장 안 됨(뺌)")
T.chk(W.parse("gate", [{"currency": "G", "delisted": False, "chains": [], "chain": "ETH", "deposit_disabled": True, "withdraw_disabled": False}])
      == {"G": {"ETH": [False, True]}}, "E3 게이트 네트워크 표 없음 = 코인 단위 값")
T.chk(W.parse("kucoin", {"code": "200000", "data": [{"currency": "T", "chains": [{"chainName": "TON", "isDepositEnabled": False, "isWithdrawEnabled": True},
                                                                               {"chainName": "TON", "isDepositEnabled": True, "isWithdrawEnabled": True}]}]})
      == {"T": {"TON": [True, True]}}, "E4 같은 이름 네트워크 둘 = 하나라도 열리면 열림")
T.chk(W.kind_of({"A": "01", "B": "01"}, 0) == ("full", ["A", "B"]) and W.kind_of({"A": "01", "B": "11"}, 0) == ("part", ["A"])
      and W.kind_of({"A": "10"}, 0) == (None, []) and W.kind_of({}, 0) == (None, []), "E5 방향별 종류(전부·일부·없음 · 네트워크 모름 = 없음)")

print("[K] 키 있는 거래소만 · 서명 요청 꼴")
NET["calls"].clear()
r = run(env={"UPBIT_ACCESS": "ua", "UPBIT_SECRET": "us", "TJ_GATE_KEY": "gk"})
T.chk(set(r) == {"upbit"} and [c[0] for c in NET["calls"]] == ["upbit"], "K1 키 없는(빠진) 거래소 건너뜀 · 부른 곳 = 업비트만", (r, NET["calls"]))
c0 = NET["calls"][0]
T.chk(c0[1] == "https://api.upbit.com/v1/status/wallet" and c0[2]["authorization"].startswith("Bearer ") and c0[2].get("accept-encoding") == "gzip",
      "K2 업비트 = JWT 서명 · gzip 요청", c0)
T.chk(set(W.load()["ex"]) == {"upbit"}, "K3 상태 파일 = 연결 거래소만")
os.remove(paths.state(W.FILE))
NET["calls"].clear()
r = run()
T.chk(set(r) == set(W.EXCHANGES) and all(v == "ok" for v in r.values()), "K4 7곳 모두 한 번씩(코인베이스 없음)", r)
bn = [c for c in NET["calls"] if c[0] == "binance"][0]
T.chk("/sapi/v1/capital/config/getall?timestamp=" in bn[1] and "&signature=" in bn[1] and bn[2].get("x-mbx-apikey") == "nk", "K5 바이낸스 = 서명 쿼리 · 키 헤더", bn[1][:80])
T.chk(all(not any(h in c[2] for h in AUTH_HDR) for c in NET["calls"] if c[0] in ("bithumb", "kucoin", "gate"))
      and all(any(h in c[2] for h in AUTH_HDR) for c in NET["calls"] if c[0] in ("upbit", "binance", "bybit", "okx")), "K6 빗썸·쿠코인·게이트 = 공개(키 헤더 없음) · 나머지 = 서명")
NET["calls"].clear()
run(now=NOW + 60)
T.chk(not NET["calls"], "K7 10분 안엔 다시 안 부름(주기당 거래소 1번)", NET["calls"])

print("[S] 연속 2주기 확정 · 처음부터 막힘 · 깜빡임")
os.remove(paths.state(W.FILE))
T0 = NOW
pre = dict(BASE, OLDX={"N": (False, True)}, USDT={"ETH": (True, True), "OMNI": (False, False)})
run({"upbit": pre}, T0)
u = st_ex("upbit")
T.chk(u["c"]["OLDX"]["d"].get("pre") == 1 and u["c"]["OLDX"]["d"].get("st") == "cand", "S1 첫 주기 막힘 = pre · 아직 확정 아님", u["c"]["OLDX"])
run({"upbit": pre}, T0 + 600)
u = st_ex("upbit")
T.chk(u["c"]["OLDX"]["d"].get("st") == "on" and u["b0"]["USDT"]["d"] == ["OMNI"] and "d" not in (u["c"].get("USDT") or {}),
      "S2 둘째 주기 = 확정 · 처음부터 닫힌 네트워크 = b0(표기 재료 아님)", (u["c"], u["b0"]))
blk = dict(pre, BTC={"MAIN": (False, True)})
run({"upbit": blk}, T0 + 1200)
T.chk(st_ex("upbit")["c"]["BTC"]["d"].get("st") == "cand" and not st_ex("upbit")["c"]["BTC"]["d"].get("pre"), "S3 새로 막힘 첫 주기 = 미확정(깜빡임 거름)")
run({"upbit": pre}, T0 + 1800)
T.chk("BTC" not in st_ex("upbit")["c"], "S4 한 주기 막혔다 풀림 = 확정 없이 지움")
run({"upbit": blk}, T0 + 2400)
run({"upbit": blk}, T0 + 3000)
T.chk(st_ex("upbit")["c"]["BTC"]["d"].get("st") == "on", "S5 두 주기 연속 = 확정")
run({"upbit": pre}, T0 + 3600)
b = st_ex("upbit")["c"]["BTC"]["d"]
T.chk(b.get("st") == "off" and b.get("end") == int(T0 + 3600), "S6 풀림 = off(30분 이어 보기)", b)
run({"upbit": blk}, T0 + 4200)
b = st_ex("upbit")["c"]["BTC"]["d"]
T.chk(b.get("st") == "on" and b["s"] == int(T0 + 2400), "S7 30분 안 다시 막힘 = 같은 사건(바로 확정 · 시작 시각 그대로)", b)
for i in range(4):
    run({"upbit": pre}, T0 + 4800 + 600 * i)
T.chk("BTC" not in st_ex("upbit")["c"], "S8 30분 넘게 열림 = 기록 지움")
part = dict(pre, ETH={"ETH": (True, True), "ARB": (False, True)})
run({"upbit": part}, T0 + 7800)
run({"upbit": part}, T0 + 8400)
e9 = st_ex("upbit")["c"]["ETH"]["d"]
T.chk(not e9.get("st") and e9["nb"] == ["ARB"] and e9["pn"] == 2, "S9 새로 닫힌 일부 네트워크 = part 2주기(b0 아님)", e9)

print("[M] 대부분 동시에 막힘 = 거래소 점검 한 줄")
mt = {k: {n: (False, False) for n in v} for k, v in BASE.items()}
run({"upbit": mt}, T0 + 9000)
m9 = st_ex("upbit").get("maint")
T.chk(isinstance(m9, dict) and "BTC|w" in m9["set"] and len(m9["set"]) >= 10, "M1 점검 시작(새로 다 막힌 (코인·방향) ≥ 10·열린 것의 25%)", m9)
run({"upbit": mt}, T0 + 9600)
T.chk(isinstance(st_ex("upbit").get("maint"), dict), "M2 이어지면 점검 유지")
run({"upbit": pre}, T0 + 10200)
T.chk(not st_ex("upbit").get("maint"), "M3 절반 넘게 풀리면 점검 끝")
W2 = dict(pre, **{f"C{i:02d}": {"N": (False, True)} for i in range(5)})
run({"upbit": W2}, T0 + 10800)
T.chk(not st_ex("upbit").get("maint"), "M4 몇 개만 막힘(5 < 10) = 점검 아님")

print("[R] 실패 = 다음 주기 다시 · 권한 없음 6시간 · 한도 늘려 쉼 · 키 바꾸면 바로")
os.remove(paths.state(W.FILE))
run(None, NOW)
c_before = dict(st_ex("bybit").get("c") or {})
NET["fail"] = {"bybit": http_err(500), "okx": http_err(403, b"no"), "gate": http_err(429, b"slow")}
r = run(None, NOW + 600)
T.chk(r.get("bybit", "").startswith("HTTP 500") and st_ex("bybit")["next"] == int(NOW + 1200) and st_ex("bybit")["at"] == int(NOW), "R1 일반 실패 = 다음 주기(10분) · 마지막 성공 유지", st_ex("bybit"))
T.chk(st_ex("okx")["next"] == int(NOW + 600 + exf_net.DENY_COOL_SEC), "R2 403 = 6시간 쉼", st_ex("okx")["next"] - NOW)
T.chk(st_ex("gate")["next"] == int(NOW + 600 + 1200), "R3 429 = 늘려 쉼(20분부터 · 최대 1시간)", st_ex("gate")["next"] - NOW)
NET["calls"].clear()
r = run(None, NOW + 1300, dict(ENV, TJ_OKX_KEY="ok2"))
T.chk("okx" in r and "bybit" in r and "gate" not in r, "R4 키 바꾸면 쉼 무시하고 바로 · 429 는 쉬는 중", r)
NET["fail"] = {"binance": W.ExwError("binance -2015 Invalid API-key", 200, "binance", -2015)}
run(None, NOW + 2000)
T.chk(st_ex("binance")["next"] == int(NOW + 2000 + exf_net.DENY_COOL_SEC), "R5 200 응답 안 '키·권한 없음' 코드 = 403 과 같은 쉼")
NET["fail"] = {}
NET["tab"] = {"kucoin": {"BTC": {"MAIN": (True, True)}}}
r = W.round_once(ENV, NOW + 2600, None, fake_send)
T.chk("절반" in r.get("kucoin", "") and len(st_ex("kucoin")["c"]) == len(st_ex("kucoin")["c"]), "R6 코인 수가 절반도 안 되는 응답 = 이번 주기 버림(가짜 풀림 없음)", r)
T.chk(c_before and c_before == (st_ex("bybit").get("c") or {}) or c_before == {}, "R8 실패 동안 막힘 기록 유지", st_ex("bybit"))
os.remove(paths.state(W.FILE))
NET["fail"] = {"bithumb": KeyError("data")}
r = run(None, NOW)
T.chk("KeyError" in r.get("bithumb", "") and r.get("upbit") == "ok" and r.get("gate") == "ok", "R7 응답 꼴 이상 = 그 거래소만 실패(다른 곳 계속)", r)
NET["fail"] = {}

print("[H] 보유 × 막힘 → 칸(방향 · 동명 거름 · 소액)")


def ex_doc(coins, at=NOW, maint=None, since=NOW - 1200):
    out = {"ex": {}}
    for ex, cs in coins.items():
        c = {s: {d9: ({"st": "on", "n": 2, "s": int(since), "bn": ["N1", "N2"]} if k == "all" else {"pn": 2, "nb": ["N1"], "bn": ["N1"]})
                 for d9, k in ds.items()} for s, ds in cs.items()}
        out["ex"][ex] = {"at": int(at), "c": c, **({"maint": maint} if maint else {})}
    return out


ROWS = [{"key": "g1", "sym": "XYZ", "qty": 100, "price": 10, "locs": [{"w": "바이낸스"}]},
        {"key": "g2", "sym": "XYZ", "qty": 50, "price": 10, "locs": [{"w": "베이스 지갑 A", "ch": "Base"}]},
        {"key": "g3", "sym": "FAKE", "qty": 1000, "price": 1, "locs": [{"w": "지갑 B", "ch": "Base"}]},
        {"key": "g4", "sym": "FAKE", "qty": 10, "price": 100, "locs": [{"w": "업비트"}]},
        {"key": "ub:DUST", "sym": "DUST", "qty": 1, "price": 3, "locs": [{"w": "업비트"}]},
        {"key": "g5", "sym": "ETH", "qty": 1, "price": 3000, "locs": [{"w": "이더리움 지갑", "ch": "Ethereum"}]}]
EXG = {1: "binance", 4: "upbit"}
KINDS = {2: {"native": False, "pairs": [("base", "0x" + "11" * 20)]}, 3: {"native": False, "pairs": [("base", "0x" + "22" * 20)]},
         5: {"native": True, "pairs": []}}
PROOF = {2: [("binance", "XYZ")]}
PX = {("binance", "FAKE"): 0.02, ("upbit", "FAKE"): 100.0, ("upbit", "XYZ"): 10.2, ("binance", "XYZ"): 10.0, ("binance", "ETH"): 3010.0}
px = lambda e, s: PX.get((e, s))   # noqa: E731
hold = exhalt.holdings(ROWS, EXG, KINDS, PROOF)
T.chk(hold["XYZ"]["ex"] == {"binance": [1000.0, "XYZ"]} and hold["XYZ"]["wp"] == [[500.0, ["binance"], ["베이스 지갑 A"], 10.0, False]] and not hold["FAKE"]["wp"]
      and hold["ETH"]["wp"] == [[3000.0, [], ["이더리움 지갑"], 3000.0, True]], "H1 지갑 = 네이티브·정품·입출금 증명 후보만(이름만 같은 FAKE 지갑 보유 뺌)", hold)
v = exhalt.view(ex_doc({"binance": {"XYZ": {"w": "all", "d": "all"}, "FAKE": {"d": "all"}, "NOPE": {"d": "all"}, "ETH": {"d": "all"}},
                        "upbit": {"XYZ": {"d": "all"}, "DUST": {"w": "all"}}}), hold, 50, px, NOW)
R = {r["key"]: r for r in v["rows"]}
T.chk(R.get("binance|XYZ|w", {}).get("usd") == 1000.0 and R["binance|XYZ|w"]["where"] == ["바이낸스"], "H2 출금 중지 = 그 거래소 보유(바이낸스 $1,000)", R)
T.chk(R.get("binance|XYZ|d", {}).get("usd") == 500.0, "H3 입금 중지 = 거래소 밖 보유(지갑 $500 · 바이낸스 자신의 보유는 안 셈)", R.get("binance|XYZ|d"))
T.chk(R.get("upbit|XYZ|d", {}).get("usd") == 1500.0 and "바이낸스" in R["upbit|XYZ|d"]["where"], "H4 다른 거래소 보유 = 두 거래소 시세가 맞으면 같은 코인(지갑 + 바이낸스)", R.get("upbit|XYZ|d"))
T.chk("binance|FAKE|d" not in R, "H5 동명 딴 코인 거름 — 바이낸스 FAKE $0.02 ≠ 업비트 FAKE $100 · 지갑 FAKE 미증명", R.get("binance|FAKE|d"))
T.chk("binance|NOPE|d" not in R and "upbit|DUST|w" not in R, "H6 보유 없는 코인·소액(기준 미만) = 칸 없음")
T.chk(R.get("binance|ETH|d", {}).get("usd") == 3000.0, "H7 네이티브 코인(지갑) = 같은 코인")
v7 = exhalt.view(ex_doc({"okx": {"XYZ": {"d": "all"}}, "gate": {"XYZ": {"d": "all"}}}), hold, 50, lambda e, s: {"okx": 10.1, "gate": 0.3, "binance": 10.0}.get(e), NOW)
R7 = {r["key"]: r for r in v7["rows"]}
T.chk(R7.get("okx|XYZ|d", {}).get("usd") == 1500.0 and "gate|XYZ|d" not in R7,
      "H7b 바이낸스로 증명된 지갑 토큰 = 다른 거래소엔 시세가 맞을 때만(OKX 맞음 · 게이트 $0.3 = 동명 딴 코인)", v7["rows"])
v2 = exhalt.view(ex_doc({"binance": {"XYZ": {"w": "part"}}}), hold, 50, px, NOW)
T.chk(v2["rows"] and v2["rows"][0]["part"] and v2["rows"][0]["nets"] == ["N1"], "H8 일부 네트워크 = part 칸(새로 닫힌 것)", v2["rows"])
d3 = ex_doc({"binance": {"XYZ": {"w": "part"}}})
d3["ex"]["binance"]["c"]["XYZ"]["w"]["nb"] = []
T.chk(not exhalt.view(d3, hold, 50, px, NOW)["rows"], "H9 처음부터 닫혀 있던 네트워크뿐 = 표기 안 함")
d4 = ex_doc({"binance": {"XYZ": {"w": "all"}}})
d4["ex"]["binance"]["c"]["XYZ"]["w"].update(st="off", end=int(NOW))
T.chk(not exhalt.view(d4, hold, 50, px, NOW)["rows"], "H10 풀림(off) = 칸 없음")
T.chk(not exhalt.view(ex_doc({"binance": {"XYZ": {"w": "all"}}}, at=NOW - 3 * 3600), hold, 50, px, NOW)["rows"], "H11 2시간 넘게 낡은 상태 = 칸 안 냄")
vm = exhalt.view(ex_doc({"binance": {"XYZ": {"w": "all", "d": "all"}, "ETH": {"d": "all"}}}, maint={"since": int(NOW - 600), "set": ["XYZ|w", "XYZ|d", "ETH|d", "BTC|d"]}),
                 hold, 50, px, NOW)
T.chk([r["key"] for r in vm["rows"]] == ["binance|*|m"] and vm["rows"][0]["n"] == 2 and vm["rows"][0]["usd"] == 4000.0,
      "H12 점검 = 코인별 줄 대신 한 줄(영향 코인 2 · 코인마다 큰 쪽 합)", vm["rows"])

print("[A] 첫 중지 1통 · 풀림 ✅(15분) · 깜빡임 이어 감 · 처음부터 막힘·끔 = 기억만 · 일부 = 알림 없음")
REC = AP.default_doc()
FMT = (alert_watch.money, alert_watch._link)


def write_doc(d):
    with open(paths.state(W.FILE), "w") as f:
        json.dump(d, f)
    os.utime(paths.state(W.FILE), None)
    exhalt._CACHE["v"] = (None, None)


def prod(d, st, now, on=True, pre=False):
    write_doc(d)
    v9 = exhalt.view(d, hold, 50, px, now)
    for r9 in v9["rows"]:
        r9["pre"] = r9["pre"] or pre
    inp = {"out": {"builtAt": now, "fields": {"exHalt": v9, "rate": 1400}}, "cur": "KRW", "pub": "https://tj.example"}
    return exhalt.prod_exhalt(inp, REC, st, now, None, on, FMT)


st = {}
D0 = ex_doc({"binance": {"XYZ": {"w": "all"}}}, at=NOW)
a0 = prod(D0, st, NOW)
T.chk(a0 == [] and "binance|XYZ|w" in st["exhalt"]["inc"], "A1 첫 판 = 기억만(배포 직후 몰아 보내기 없음)", a0)
st = {"exhalt": {"init": 1, "inc": {}}}
a1 = prod(D0, st, NOW)
T.chk(len(a1) == 1 and a1[0]["kind"] == "EX_HALT" and a1[0]["cat"] == "exhalt" and a1[0]["text"].startswith("🔴 바이낸스 XYZ 출금이 막혔어요")
      and "[보기] https://tj.example/v2/#dash" in a1[0]["text"], "A2 새 중지 = 한 통(🔴 소리 · 거래소·코인·방향 · 보기 링크)", a1)
T.chk(prod(D0, st, NOW + 60) == [], "A3 같은 사건 다음 판 = 알림 없음")
DB = ex_doc({"binance": {"XYZ": {"w": "all", "d": "all"}}, "upbit": {"XYZ": {"d": "all"}}}, at=NOW)
st2 = {"exhalt": {"init": 1, "inc": {}}}
a2 = prod(DB, st2, NOW)
T.chk(len(a2) == 2 and any("입출금이 모두 막혔어요" in x["text"] for x in a2) and any("업비트 XYZ 입금이 막혔어요" in x["text"] for x in a2),
      "A4 같은 거래소·코인 입금·출금 = 한 통 · 다른 거래소 = 따로", [x["text"].split("\n")[0] for x in a2])


def gone_doc(at):
    d9 = ex_doc({"binance": {"XYZ": {"w": "all"}}}, at=at)
    d9["ex"]["binance"]["c"]["XYZ"]["w"].update(st="off", end=int(at))
    return d9


T.chk(prod(gone_doc(NOW + 600), st, NOW + 600) == [] and "binance|XYZ|w" in st["exhalt"]["inc"], "A5 풀림 이어 보기(gone) 중 = ✅ 기다림")
DR = ex_doc({"binance": {"XYZ": {"w": "all"}}}, at=NOW + 1200)
T.chk(prod(DR, st, NOW + 1200) == [] and not st["exhalt"]["inc"]["binance|XYZ|w"].get("clr"), "A6 이어 보기 중 다시 막힘 = 같은 사건 이어 감(알림 없음)")
prod(gone_doc(NOW + 1800), st, NOW + 1800)
a7 = prod(ex_doc({"binance": {}}, at=NOW + 3600), st, NOW + 3600)
T.chk(len(a7) == 1 and a7[0]["text"].startswith("✅ 바이낸스 XYZ 출금이 다시 돼요") and a7[0].get("resolved") and "binance|XYZ|w" not in st["exhalt"]["inc"],
      "A7 일꾼이 기록을 지움(30분 넘게 열림) = ✅ 한 통(소리 없음 · 15·30 규칙 하나)", a7)
st3 = {"exhalt": {"init": 1, "inc": {}}}
T.chk(prod(D0, st3, NOW, pre=True) == [] and st3["exhalt"]["inc"]["binance|XYZ|w"]["at"] == 0, "A8 처음부터 막혀 있던 것(pre) = 기억만")
prod(ex_doc({"binance": {}}, at=NOW + 600), st3, NOW + 600)
T.chk(prod(ex_doc({"binance": {}}, at=NOW + 1600), st3, NOW + 1600) == [], "A9 알리지 않은 사건 풀림 = ✅ 도 없음")
st4 = {"exhalt": {"init": 1, "inc": {}}}
T.chk(prod(D0, st4, NOW, on=False) == [] and prod(D0, st4, NOW + 60, on=True) == [], "A10 꺼진 동안 생긴 것 = 다시 켜도 몰아 보내기 없음")
st5 = {"exhalt": {"init": 1, "inc": {}}}
T.chk(prod(ex_doc({"binance": {"XYZ": {"w": "part"}}}), st5, NOW) == [] and not st5["exhalt"]["inc"], "A11 일부 네트워크 = 알림 없음(표기만)")
st6 = {"exhalt": {"init": 1, "inc": {}}}
prod(D0, st6, NOW)
hold_sold = exhalt.holdings([r for r in ROWS if r["key"] != "g1"], EXG, KINDS, PROOF)
write_doc(D0)
inp9 = {"out": {"builtAt": NOW + 60, "fields": {"exHalt": exhalt.view(D0, hold_sold, 50, px, NOW + 60)}}, "cur": "KRW"}
T.chk(exhalt.prod_exhalt(inp9, REC, st6, NOW + 60, None, True, FMT) == [] and st6["exhalt"]["inc"]["binance|XYZ|w"].get("hid"),
      "A12 막힌 채 팔아서 보유가 빠짐 = 알림 없음 · 사건 기억은 둠(끝나도 ✅ 없음)")
st7 = {"exhalt": {"init": 1, "inc": {}}}
prod(D0, st7, NOW)
T.chk(prod(ex_doc({"binance": {}}, at=NOW - 3600), st7, NOW + 600) == [] and not st7["exhalt"]["inc"]["binance|XYZ|w"].get("clr"), "A13 상태가 낡음 = 풀림 판정 미룸")
DM = ex_doc({"binance": {"XYZ": {"w": "all", "d": "all"}}}, maint={"since": int(NOW), "set": ["XYZ|w", "XYZ|d"] + [f"Q{i}|d" for i in range(20)]})
st8 = {"exhalt": {"init": 1, "inc": {}}}
a14 = prod(DM, st8, NOW)
T.chk(len(a14) == 1 and a14[0]["text"].startswith("🔴 바이낸스 입출금 점검 중이에요"), "A14 거래소 점검 = 한 통(코인별로 쏟지 않음)", a14)
T.chk(all(j not in x["text"] for x in a1 + a2 + a7 + a14 for j in AP.JARGON), "A15 알림 문장에 봇 내부 용어 없음")
st9 = {"exhalt": {"init": 1, "inc": {}}}
write_doc(D0)
inp10 = {"out": {"builtAt": NOW, "fields": {"exHalt": exhalt.view(D0, hold, 50, px, NOW)}}, "cur": "KRW"}
got = alert_watch.step(inp10, REC, st9, NOW, None)
T.chk([x["kind"] for x in got] == ["EX_HALT"], "A16 alert_watch.step 이 생산자를 부름(PRODUCERS · 켬 = 추천 기본)", got)
T.chk(AP.decide(REC, "exhalt", NOW, None, "EX_HALT") == "send", "A17 발송 = 즉시(조용한 시간 무관)")

print("[B] 빌드 꼬리 칸")
os.remove(paths.state(W.FILE))
exhalt._CACHE["v"] = (None, None)


WANTED = set()


class SB:
    def __init__(self):
        self.spot = type("Sp", (), {"ex_price": staticmethod(px), "want_ex": lambda s9, exs: WANTED.update(exs)})()
        self._cex_proof_cache = ((0, 0), PROOF)


class Conn:
    def execute(self, q, args):
        return [(2, "token", "base", "0x" + "11" * 20), (5, "native", "eth", None)]


T.chk(exhalt.part(SB(), ROWS, EXG, Conn(), 50, NOW) == {}, "B1 상태 파일 없음 = 칸 없음(응답 무변)")
write_doc(ex_doc({"binance": {"XYZ": {"w": "all", "d": "all"}}}))
pb = exhalt.part(SB(), ROWS, EXG, Conn(), 50, NOW)
T.chk(set(pb) == {"exHalt"} and {r["key"] for r in pb["exHalt"]["rows"]} == {"binance|XYZ|w", "binance|XYZ|d"} and pb["exHalt"]["ex"]["binance"]["ok"],
      "B2 상태 파일 있음 = exHalt 칸(줄·거래소 신선도)", pb)


class BadConn:
    def execute(self, q, args):
        raise RuntimeError("db gone")


T.chk(exhalt.part(SB(), ROWS, EXG, BadConn(), 50, NOW) == {}, "B3 판정 실패 = 칸만 빠짐(빌드 계속)")

print("[P] 상태 API 를 오래 못 받음 = 주의(노랑)")
write_doc({"ex": {"okx": {"at": int(NOW - 7200), "try": int(NOW), "err": "HTTP 403: no", "err_at": int(NOW)},
                  "gate": {"at": int(NOW - 1200), "try": int(NOW), "err": "HTTP 500", "err_at": int(NOW)},
                  "upbit": {"at": int(NOW), "try": int(NOW), "err": "", "err_at": int(NOW - 600)},
                  "kucoin": {"at": int(NOW), "try": int(NOW), "err": ""}}})
hp = {x["cid"]: x for x in exhalt.health_items(NOW)}
T.chk(hp.get("exwallet:okx", {}).get("level") == "warn" and not hp["exwallet:okx"]["notify"] and "권한" in hp["exwallet:okx"]["action"],
      "P1 2시간 못 받음(403) = 주의 · 알림 없음 · 할 일 = 키 권한", hp.get("exwallet:okx"))
T.chk("exwallet:gate" not in hp and hp.get("exwallet:upbit", {}).get("level") == "ok" and "exwallet:kucoin" not in hp,
      "P2 짧은 실패 = 아직 조용 · 풀린 곳 = 정상 줄(사건 닫힘) · 실패 없던 곳 = 줄 없음", sorted(hp))

print("[C] 알림 설정 · 프리셋 · 견본")
T.chk(AP.CAT["exhalt"]["tier"] == "now" and AP.cat_of("EX_HALT") == "exhalt", "C1 카테고리 = 즉시 · EX_HALT → exhalt")
T.chk(all(AP._preset_cats(n)["exhalt"] == "on" for n in ("rec", "min", "all")), "C2 추천·최소·전부 모두 켬")
old_min = {"v": 2, "cats": {k: v for k, v in AP._preset_cats("min").items() if k != "exhalt"}}
old_cus = {"v": 2, "cats": {"pnl": "off", "health": "on"}}
T.chk(AP.normalize(old_min)["cats"]["exhalt"] == "on" and AP.match_preset(old_min) == "min" and AP.normalize(old_cus)["cats"]["exhalt"] == "on",
      "C3 저장값에 없는 옛 설정 = 켬으로 채움(프리셋 맞춤 유지)")
off = AP.apply_post(None, {"cats": {"exhalt": "off"}})[0]
T.chk(not AP.effective(off, "exhalt") and AP.decide(off, "exhalt", NOW, None, "EX_HALT") == "skip", "C4 끄면 안 보냄")
tl = alert_watch.test_line("exhalt")
T.chk(tl["cat"] == "exhalt" and "입금이 막혔어요" in tl["text"] and any(c["key"] == "exhalt" for c in AP.view({})["cats"]), "C5 설정 화면 줄 · 테스트 보내기 견본")

print("[G] gzip · 상한 · 오류")


SEEN = []


def fake_open(body, enc=""):
    def f(req, timeout=20):
        SEEN.append((req.full_url, {k.lower(): v for k, v in req.header_items()}))
        return Resp(body, enc)
    return f


g1 = W.http_get("https://api.gateio.ws/api/v4/spot/currencies", None, False, fake_open(gzip.compress(json.dumps([{"currency": "A"}]).encode()), "gzip"))
T.chk(g1 == [{"currency": "A"}] and SEEN[-1][1].get("accept-encoding") == "gzip" and SEEN[-1][1].get("user-agent", "").startswith("tj-bot/"), "G1 gzip 요청·해제", (g1, SEEN[-1]))
T.chk(W.http_get("https://api.upbit.com/v1/status/wallet", {"Authorization": "Bearer t"}, True, fake_open(b'{"x": 1}')) == {"x": 1}, "G2 평문 응답도")
big = io.BytesIO()
with gzip.GzipFile(fileobj=big, mode="wb") as gz:
    gz.write(b" " * (W.MAX_BYTES + 10))
try:
    W.http_get("https://api.kucoin.com/api/v3/currencies", None, False, fake_open(big.getvalue(), "gzip"))
    T.chk(False, "G3 압축 해제 상한 넘음 = 실패")
except W.ExwError as e:
    T.chk("network" in str(e), "G3 압축 해제 상한 넘음 = 그 요청 실패", str(e))


def raise_403(req, timeout=20):
    raise http_err(403, b'{"error": {"name": "no_authorization_ip"}}')


try:
    W.http_get("https://api.upbit.com/v1/status/wallet", {"Authorization": "Bearer t"}, True, raise_403)
    T.chk(False, "G4 HTTP 403 = ExwError(403)")
except W.ExwError as e:
    T.chk(e.status == 403 and "403" in str(e), "G4 HTTP 403 = ExwError(403 · 6시간 쉼 재료)", str(e))
T.chk(exhalt.FILE == W.FILE and exhalt.EVERY == W.EVERY, "G6 상태 파일 이름·주기 = 일꾼과 같음")
os.remove(paths.state(W.FILE))
W.round_once(dict(ENV, UPBIT_ACCESS="SYNTH_ACCESS_KEY_0123456789", UPBIT_SECRET="SYNTH_SECRET_9876543210"), NOW, None, fake_send)
raw9 = open(paths.state(W.FILE)).read()
T.chk("SYNTH_ACCESS" not in raw9 and "SYNTH_SECRET" not in raw9 and len(st_ex("upbit").get("kf") or "") == 12, "G5 상태 파일에 키 원문 없음(지문 12자만)")

print("[Q] 처음 볼 때부터 막혀 있던 보유 = 칩·알림 아님(접힘 줄) · 그 뒤 새 중지만 칩")
os.remove(paths.state(W.FILE))
QN = 30
QTAB = dict(BASE, XYZ={"MAIN": (True, True)}, **{f"P{i:02d}": {"MAIN": (True, False)} for i in range(QN)})
QROWS = [{"key": f"g{100 + i}", "sym": f"P{i:02d}", "qty": 10, "price": 10, "locs": [{"w": "바이낸스"}]} for i in range(QN)] \
    + [{"key": "g1", "sym": "XYZ", "qty": 100, "price": 10, "locs": [{"w": "바이낸스"}]}]
QEXG = {100 + i: "binance" for i in range(QN)}
QEXG[1] = "binance"
qhold = exhalt.holdings(QROWS, QEXG, {}, {})
run({"binance": QTAB}, NOW)
run({"binance": QTAB}, NOW + 600)
exhalt._CACHE["v"] = (None, None)
qv = exhalt.view(W.load(), qhold, 50, px, NOW + 600)
T.chk(qv["rows"] == [] and qv["preN"] == QN and len(qv["pre"]) == QN and qv["pre"][0].keys() == {"exN", "sym", "dir", "usd"},
      "Q1 첫 주기부터 막힌 출금 30개 = 칩 0 · 접힘 줄 30(짧은 꼴)", {"rows": qv["rows"][:2], "preN": qv.get("preN")})
qst = {"exhalt": {"init": 1, "inc": {}}}
inpq = {"out": {"builtAt": NOW + 600, "fields": {"exHalt": qv}}, "cur": "KRW"}
T.chk(exhalt.prod_exhalt(inpq, REC, qst, NOW + 600, None, True, FMT) == [] and not qst["exhalt"]["inc"], "Q2 처음부터 막힘 = 알림 0 · 사건 기억도 없음")
QTAB2 = dict(QTAB, XYZ={"MAIN": (True, False)})
run({"binance": QTAB2}, NOW + 1200)
run({"binance": QTAB2}, NOW + 1800)
exhalt._CACHE["v"] = (None, None)
qv2 = exhalt.view(W.load(), qhold, 50, px, NOW + 1800)
T.chk([r["key"] for r in qv2["rows"]] == ["binance|XYZ|w"] and qv2["preN"] == QN, "Q3 그 뒤 새로 막힌 XYZ = 칩 1 · 접힘 줄 그대로 30", qv2["rows"])
inpq2 = {"out": {"builtAt": NOW + 1800, "fields": {"exHalt": qv2}}, "cur": "KRW"}
qa = exhalt.prod_exhalt(inpq2, REC, qst, NOW + 1800, None, True, FMT)
T.chk(len(qa) == 1 and qa[0]["text"].startswith("🔴 바이낸스 XYZ 출금이 막혔어요"), "Q4 새 중지 = 알림 1통", qa)

QJS = r"""
const fs = require('fs');
const T = fs.readFileSync(process.argv[2], 'utf8');
const i = T.indexOf('  function haltHTML() {'), j = i < 0 ? -1 : T.indexOf('\n  }\n', i);   // 세션47 dash: 입출금 중지 = '거래소 상황' 카드(haltHTML)
if (i < 0 || j < 0) throw new Error('블록 못 찾음');
const esc = t => String(t).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';'), arr = x => Array.isArray(x) ? x : [], num = x => +x || 0;
const m = v => '$' + Math.round(v), IC = { info: '<svg></svg>' }, icon = () => '', venueLogo = () => '';
const run = D => new Function('S', 'arr', 'esc', 'num', 'm', 'IC', 'icon', 'venueLogo', T.slice(i, j + 4) + '\nreturn haltHTML();')({ D }, arr, esc, num, m, IC, icon, venueLogo);
const D = JSON.parse(process.argv[3]);
console.log(JSON.stringify([run({ exHalt: [], exHaltPre: D.pre }), run({ exHalt: D.rows, exHaltPre: D.pre }), run({ exHalt: [], exHaltPre: [] })]));
"""
nb = T.node_bin("Q5 대시보드 흐린 칩")
if nb:
    import subprocess  # noqa: E402
    jp = os.path.join(T.TMP, "q5.js")
    with open(jp, "w", encoding="utf-8") as f:
        f.write(QJS)
    pr = subprocess.run([nb, jp, os.path.join(T.ROOT, "web", "v2", "tab_dash.js"), json.dumps({"pre": qv["pre"], "rows": qv2["rows"]})],
                        capture_output=True, text=True, timeout=60)
    try:
        h0, h1, h2 = json.loads(pr.stdout)
    except ValueError:
        h0 = h1 = h2 = None
    T.chk(h0 is not None and h0.count('data-a="haltOld"') == 1 and "haltInfo" not in h0 and "처음부터 막힌 보유 30개" in h0
          and exhalt.prod_exhalt(inpq, REC, {"exhalt": {"init": 1, "inc": {}}}, NOW + 600, None, True, FMT) == [],
          "Q5 새 중지 0 · 처음부터 막힘 30 = 흐린 칩 1(누르면 haltOld) · 알림 0", (h0, pr.stderr[-300:]))
    T.chk(h1 is not None and h1.count("haltInfo") == 1 and "haltOld" not in h1 and h2 == "", "Q6 새 중지 있으면 칩만(흐린 칩 중복 없음 · 팝업 안 줄) · 둘 다 없으면 줄 없음", (h1, h2))

print("[N] 참고 칸 — OKX 재개 예정 · 업비트 블록 상태")
po = W.parse("okx", {"code": "0", "data": [{"ccy": "Z", "chain": "Z-A", "canDep": False, "canWd": True, "depEstOpenTime": str(int(NOW + 7200) * 1000), "wdEstOpenTime": ""}]})
pu = W.parse("upbit", [{"currency": "U", "net_type": "U", "wallet_state": "paused", "block_state": "delayed"},
                       {"currency": "V", "net_type": "V", "wallet_state": "paused", "block_state": "normal"}])
T.chk(po["Z"]["Z-A"] == [False, True, {"eo_d": int(NOW + 7200)}] and pu["U"]["U"] == [False, False, {"bs": "delayed"}] and pu["V"]["V"] == [False, False],
      "N1 파싱 = 재개 예정(초)·블록 상태(normal 아님)만 셋째 값", (po, pu))
rz = W.update({}, po, NOW)
rz = W.update(rz, po, NOW + 600)
T.chk(rz["c"]["Z"]["d"].get("eo") == int(NOW + 7200) and "eo" not in (rz["c"]["Z"].get("w") or {}), "N2 막힌 방향 기록에 재개 예정")
ru = W.update(W.update({}, pu, NOW), pu, NOW + 600)
T.chk(ru["c"]["U"]["d"].get("bs") == "delayed" and "bs" not in ru["c"]["V"]["d"], "N3 막힌 기록에 블록 상태(참고)")
rz2 = W.update(rz, po, NOW + 1200)
ru2 = W.update(ru, pu, NOW + 1200)
rz3 = dict(rz2)
rz3["c"] = {"Z": {"w": {k: v for k, v in rz2["c"]["Z"]["d"].items() if k != "pre"}}}
zrow = exhalt.view({"ex": {"okx": rz3}}, exhalt.holdings([{"key": "g7", "sym": "Z", "qty": 100, "price": 10, "locs": []}], {7: "okx"}, {}, {}),
                   50, px, NOW + 1200)["rows"]
T.chk(zrow and zrow[0].get("eo") == int(NOW + 7200), "N4 칸에 재개 예정(미래일 때만)", zrow)
ru3 = dict(ru2)
ru3["c"] = {"U": {"w": {k: v for k, v in ru2["c"]["U"]["d"].items() if k != "pre"}}}
urow = exhalt.view({"ex": {"upbit": ru3}}, exhalt.holdings([{"key": "g8", "sym": "U", "qty": 100, "price": 10, "locs": []}], {8: "upbit"}, {}, {}),
                   50, px, NOW + 1200)["rows"]
T.chk(urow and urow[0].get("bs") == "delayed", "N5 칸에 블록 상태 참고", urow)

print("[X] 호스트 쉼 공유 · 일부→전부 = 새 사건 · 필드 누락·빠진 항목 = 마지막 상태 · 점검(코인·방향) · 묶음 이어받기 · 키 교체 · 사건 식별 · 전체 목록 · 시세 확인")


def fresh():
    if os.path.exists(paths.state(W.FILE)):
        os.remove(paths.state(W.FILE))
    exhalt._CACHE["v"] = (None, None)


def wrun(tab, now, env=ENV, rl=None):
    NET["tab"] = tab
    r = W.round_once(env, now, None, fake_send, rl)
    exhalt._CACHE["v"] = (None, None)
    return r


fresh()
NET["calls"].clear()
wrun({}, NOW, rl={"api.binance.com": NOW + 86400})
T.chk("binance" not in {c[0] for c in NET["calls"]} and "upbit" in {c[0] for c in NET["calls"]}, "X1 기존 수집기가 바이낸스 호스트를 쉬는 중 = 안 부름(다른 거래소는 그대로)")
fresh()
rl1 = {}
NET["fail"] = {"binance": http_err(418, b"ban", {"Retry-After": "86400"})}
wrun({}, NOW, rl=rl1)
NET["fail"] = {}
T.chk(rl1.get("api.binance.com") == NOW + 86400 and st_ex("binance")["next"] >= NOW + 86400, "X2 418 Retry-After 86400 = 공유 쉼 지도·다음 시도 모두 하루(1,200초로 줄이지 않음)",
      (rl1, st_ex("binance").get("next")))

QH = exhalt.holdings(QROWS, QEXG, {}, {})
fresh()
P2 = dict(BASE, XYZ={"A": (True, False), "B": (True, True)})
F2 = dict(BASE, XYZ={"A": (True, False), "B": (True, False)})
for t, tb in ((0, P2), (600, P2), (1200, F2), (1800, F2)):
    wrun({"binance": tb}, NOW + t)
xr = st_ex("binance")["c"]["XYZ"]["w"]
xv = exhalt.view(W.load(), QH, 50, px, NOW + 1800)
xa = exhalt.prod_exhalt({"out": {"builtAt": NOW + 1800, "fields": {"exHalt": xv}}, "cur": "KRW"}, REC, {"exhalt": {"init": 1, "inc": {}}}, NOW + 1800, None, True, FMT)
T.chk(not xr.get("pre") and xr.get("st") == "on" and [r["key"] for r in xv["rows"]] == ["binance|XYZ|w"] and len(xa) == 1,
      "X3 처음엔 일부 네트워크만 닫힘(pre) → 나중에 전부 막힘 = 새 사건(칩 1·알림 1)", (xr, xv["rows"], xa))

good = W.parse("okx", resp("okx", BASE))
badj = resp("okx", BASE)
for x in badj["data"][:5]:
    x.pop("canWd")
bad = W.parse("okx", badj)
rec = W.update(W.update({}, good, NOW), good, NOW + 600)
rec = W.update(W.update(rec, bad, NOW + 1200), bad, NOW + 1800)
T.chk(len(bad) < len(good) and not any(isinstance(c.get("w"), dict) for c in rec["c"].values()), "X4 canWd 빠진 5개 = 미확인(가짜 출금 중지 0)", len(bad))
z1 = {"Z": {"A": [True, False], "B": [True, True]}}
zr = W.update(W.update({}, z1, NOW), z1, NOW + 600)
zr = W.update(W.update(zr, {"Z": {"A": [True, False]}}, NOW + 1200), {"Z": {"A": [True, False]}}, NOW + 1800)
T.chk(((zr["c"].get("Z") or {}).get("w") or {}).get("st") != "on" and isinstance(zr["nets"]["Z"]["B"], list), "X5 열린 네트워크가 응답에서 빠짐 = 마지막 상태(열림) — 가짜 '전부 막힘' 없음", zr["c"].get("Z"))
y1 = {"Y": {"A": [True, False]}, "K": {"A": [True, True]}}
yr = W.update(W.update({}, y1, NOW), y1, NOW + 600)
yr = W.update(yr, {"K": {"A": [True, True]}}, NOW + 1200)
T.chk(yr["c"]["Y"]["w"].get("st") == "on" and isinstance(yr["nets"]["Y"]["A"], list), "X6 막힌 코인이 응답에서 빠짐 = 막힘 그대로(가짜 풀림 없음)", yr["c"].get("Y"))

fresh()
PW = {100 + i: [("binance", f"P{i:02d}")] for i in range(QN)}
QW = [dict(r, locs=[{"w": "지갑", "ch": "Base"}]) for r in QROWS if r["key"] != "g1"]
WH = exhalt.holdings(QW, {}, {}, PW)
T1 = dict(BASE, XYZ={"MAIN": (True, True)}, **{f"P{i:02d}": {"MAIN": (True, False)} for i in range(QN)})
T2 = dict(T1, **{f"P{i:02d}": {"MAIN": (False, False)} for i in range(QN)})
T3 = dict(T1, **{f"P{i:02d}": {"MAIN": (False, False) if i < 14 else (True, False)} for i in range(QN)})
for t, tb in ((0, T1), (600, T1), (1200, T2), (1800, T2)):
    wrun({"binance": tb}, NOW + t)
mm = st_ex("binance").get("maint")
T.chk(isinstance(mm, dict) and len(mm["set"]) == QN and all(x.endswith("|d") for x in mm["set"]), "X7 출금이 처음부터 막힌 코인들의 입금이 한꺼번에 막힘 = 점검(코인·방향 기준)", mm)
mst = {"exhalt": {"init": 1, "inc": {}}}


def mprod(t):
    v9 = exhalt.view(W.load(), WH, 50, px, NOW + t)
    return v9, exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, mst, NOW + t, None, True, FMT)


_v, m1 = mprod(1800)
T.chk(len(m1) == 1 and "점검 중" in m1[0]["text"], "X8 점검 = 한 통", [x["text"][:30] for x in m1])
wrun({"binance": T3}, NOW + 2400)
v8, m2 = mprod(2400)
T.chk(not st_ex("binance").get("maint") and len(v8["rows"]) == 14 and all(r["mt"] for r in v8["rows"]) and m2 == [],
      "X9 점검 절반 넘게 풀림 = 끝 · 남은 14개 = 묶음 알림 이어받음(새 알림 0)", ([r["key"] for r in v8["rows"]][:3], [x["text"][:30] for x in m2]))
wrun({"binance": T3}, NOW + 3000)
wrun({"binance": T3}, NOW + 3600)
_v, m4 = mprod(3600)
T.chk([x["text"].split("\n")[0] for x in m4] == ["✅ 바이낸스 점검은 끝났지만 14개는 아직 막혀 있어요"] and "할 일은 없어요" not in m4[0]["text"],
      "X9b 점검 끝 = 한 통 · 아직 막힌 보유 14개 목록(남은 코인은 따로 안 알림 · '할 일 없음' 아님)", [x["text"][:60] for x in m4])

fresh()
K1 = dict(BASE, XYZ={"MAIN": (True, True)})
K2 = dict(BASE, XYZ={"MAIN": (True, False)})
KH = exhalt.holdings([{"key": "g1", "sym": "XYZ", "qty": 100, "price": 10, "locs": []}], {1: "upbit"}, {}, {})
kst = {"exhalt": {"init": 1, "inc": {}}}


def kprod(t):
    v9 = exhalt.view(W.load(), KH, 50, px, NOW + t)
    return v9, exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, kst, NOW + t, None, True, FMT)


for t, tb in ((0, K1), (600, K1), (1200, K2), (1800, K2)):
    wrun({"upbit": tb}, NOW + t)
_v, k1 = kprod(1800)
ENV2 = dict(ENV, UPBIT_ACCESS="ua-other-account")
g0 = st_ex("upbit")["gen"]
wrun({"upbit": K2}, NOW + 2400, ENV2)
wrun({"upbit": K2}, NOW + 3000, ENV2)
kv, k2 = kprod(3000)
T.chk(len(k1) == 1 and st_ex("upbit")["gen"] != g0 and st_ex("upbit")["c"]["XYZ"]["w"].get("pre") and k2 == [] and not kv["rows"] and not kst["exhalt"]["inc"],
      "X10 키 바꿈(다른 계정) = 기준 상태 새로(다시 pre) · 옛 사건 조용히 지움(가짜 ✅·🔴 없음)", (k1, k2, kst))

fresh()
A2 = dict(BASE, XYZ={"A": (True, True), "B": (True, True)})
B2 = dict(BASE, XYZ={"A": (True, False), "B": (True, False)})
C2 = dict(BASE, XYZ={"A": (True, True), "B": (True, False)})
seq9, outs = [(0, A2), (600, A2), (1200, B2), (1800, B2)] + [(2400 + 600 * i, C2) for i in range(7)] + [(6600, B2), (7200, B2)], []
cst = {"exhalt": {"init": 1, "inc": {}}}
for t, tb in seq9:
    wrun({"binance": tb}, NOW + t)
    v9 = exhalt.view(W.load(), QH, 50, px, NOW + t)
    outs += [x["text"].split("\n")[0] for x in exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, cst,
                                                                   NOW + t, None, True, FMT)]
T.chk(outs == ["🔴 바이낸스 XYZ 출금이 막혔어요", "✅ 바이낸스 XYZ 출금이 일부 네트워크로 다시 돼요", "🔴 바이낸스 XYZ 출금이 막혔어요"],
      "X11 전부 중지 → 일부 복구 1시간(✅) → 다시 전부 중지 = 새 사건 🔴", outs)
sid = {"exhalt": {"init": 1, "gen": {}, "inc": {"binance|XYZ|w": {"s": int(NOW - 99999), "at": int(NOW - 99999)}}}}
write_doc(ex_doc({"binance": {"XYZ": {"w": "all"}}}))
inq = {"out": {"builtAt": NOW, "fields": {"exHalt": exhalt.view(ex_doc({"binance": {"XYZ": {"w": "all"}}}), hold, 50, px, NOW)}}, "cur": "KRW"}
T.chk(len(exhalt.prod_exhalt(inq, REC, sid, NOW, None, True, FMT)) == 1, "X12 시작 시각이 다른 같은 키(웹이 쉬는 사이 풀렸다 다시 막힘) = 새 사건 알림")

BIG = {f"B{i:02d}": {"w": "all"} for i in range(61)}
BH = exhalt.holdings([{"key": f"g{300 + i}", "sym": f"B{i:02d}", "qty": 10, "price": 10 + i, "locs": []} for i in range(61)], {300 + i: "binance" for i in range(61)}, {}, {})
write_doc(ex_doc({"binance": BIG}))
bv = exhalt.view(ex_doc({"binance": BIG}), BH, 50, px, NOW)
bst = {"exhalt": {"init": 1, "inc": {}}}
ba = exhalt.prod_exhalt({"out": {"builtAt": NOW, "fields": {"exHalt": bv}}, "cur": "KRW"}, REC, bst, NOW, None, True, FMT)
T.chk(len(bv["rows"]) == 61 and len(bst["exhalt"]["inc"]) == 61 and len(ba) == 1 and "61개" in ba[0]["text"],
      "X13 중지 61건 = 사건 61건 모두 판정(화면 60행 제한 없음) · 같은 거래소 몰림 = 한 통", (len(bv["rows"]), len(ba)))
nv = exhalt.view(ex_doc({"binance": {"ETH": {"d": "all"}}}), hold, 50, lambda e, s9: 0.5 if s9 == "ETH" else None, NOW)
T.chk(not nv["rows"], "X14 네이티브 ETH(지갑 $3,000) vs 거래소 ETH 시세 $0.5(다른 체인 동명) = 같은 코인 아님", nv["rows"])

fresh()
wrun({}, NOW)
NET["calls"].clear()
wrun({}, NOW + 60, {})
T.chk(W.load()["ex"] == {}, "X15 키를 모두 지움 = 파일에서도 지움(저장됨)")
fresh()
NET["fail"] = {"upbit": http_err(500)}
for i in range(31):
    wrun({}, NOW + 600 * i, {"UPBIT_ACCESS": "ua", "UPBIT_SECRET": "us"})
NET["fail"] = {}
hx = {x["cid"]: x for x in exhalt.health_items(NOW + 600 * 30)}
T.chk(hx.get("exwallet:upbit", {}).get("level") == "warn", "X16 첫 성공 전 5시간 연속 실패 = 노랑(첫 실패 시각 기준)", hx)
QJS2 = QJS.replace("run({ exHalt: [], exHaltPre: [] })", "run({ exHalt: D.rows.concat(D.rows, D.rows, D.rows, D.rows), exHaltPre: [] })")
if nb:
    with open(jp, "w", encoding="utf-8") as f:
        f.write(QJS2)
    pr = subprocess.run([nb, jp, os.path.join(T.ROOT, "web", "v2", "tab_dash.js"), json.dumps({"pre": qv["pre"], "rows": qv2["rows"]})],
                        capture_output=True, text=True, timeout=60)
    h5 = json.loads(pr.stdout)[2] if pr.stdout.strip() else ""
    T.chk('data-a="haltAll">외 1건' in h5, "X17 '외 N건' = 눌러 전체 목록(haltAll)", h5[-160:])

print("[F] 교차 검수 시나리오 — 공백 뒤 점검 · 점검 끝 · 풀림 뒤 일부 재막힘 · 몰림 한 통 · 심볼 escape")
fresh()
G1 = dict(BASE, XYZ={"MAIN": (True, True)}, **{f"P{i:02d}": {"MAIN": (True, True)} for i in range(QN)})
G2 = dict(G1, **{f"P{i:02d}": {"MAIN": (False, False)} for i in range(QN)})
wrun({"binance": G1}, NOW)
wrun({"binance": G1}, NOW + 600)
wrun({"binance": G2}, NOW + 600 + 7200)
T.chk(isinstance(st_ex("binance").get("maint"), dict), "F1 수집 공백 뒤 한꺼번에 막힘도 점검(마지막 성공 스냅숏과 비교)", st_ex("binance").get("maint"))
fresh()
wrun({"binance": BASE}, NOW)
wrun({"binance": BASE}, NOW + 600)
B6 = dict(BASE, **{f"C{i:02d}": {"N": (True, False)} for i in range(6)})
wrun({"binance": B6}, NOW + 1200)
wrun({"binance": B6}, NOW + 1800)
H6 = exhalt.holdings([{"key": f"g{400 + i}", "sym": f"C{i:02d}", "qty": 10, "price": 10, "locs": []} for i in range(6)], {400 + i: "binance" for i in range(6)}, {}, {})
f6 = exhalt.prod_exhalt({"out": {"builtAt": NOW + 1800, "fields": {"exHalt": exhalt.view(W.load(), H6, 50, px, NOW + 1800)}}, "cur": "KRW"}, REC,
                        {"exhalt": {"init": 1, "inc": {}}}, NOW + 1800, None, True, FMT)
T.chk(not st_ex("binance").get("maint") and len(f6) == 1 and "6개" in f6[0]["text"], "F2 점검 문턱 밑 6개 동시 = 한 통(몰림 안전판)", [x["text"][:40] for x in f6])
fresh()
H1a, H1b, H1c = dict(BASE, XYZ={"A": (True, True), "B": (True, True)}), dict(BASE, XYZ={"A": (True, False), "B": (True, False)}), dict(BASE, XYZ={"A": (True, True), "B": (True, False)})
hst, hout = {"exhalt": {"init": 1, "inc": {}}}, []
for t, tb in [(0, H1a), (600, H1a), (1200, H1b), (1800, H1b), (2400, H1a)] + [(3000 + 600 * i, H1a) for i in range(5)] + [(6000, H1c), (6600, H1c), (7200, H1c)]:
    wrun({"binance": tb}, NOW + t)
    v9 = exhalt.view(W.load(), QH, 50, px, NOW + t)
    hout += [x["text"].split("\n")[0] for x in exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, hst,
                                                                   NOW + t, None, True, FMT)]
T.chk(hout == ["🔴 바이낸스 XYZ 출금이 막혔어요", "✅ 바이낸스 XYZ 출금이 다시 돼요"] and v9["rows"] and v9["rows"][0]["part"],
      "F4 전부 막힘 → 풀림 ✅ → 일부만 다시 막힘 = '일부' 표기만(🔴 없음)", (hout, v9["rows"][:1]))
if nb:
    XS = [{"key": "binance|<img src=x onerror=1>|w", "ex": "binance", "exN": "바이낸스", "sym": "<img src=x onerror=1>", "dir": "w", "part": False, "nets": [], "since": 1,
           "usd": 100, "where": [], "pre": False, "age": 1}]
    with open(jp, "w", encoding="utf-8") as f:
        f.write(QJS)
    pr = subprocess.run([nb, jp, os.path.join(T.ROOT, "web", "v2", "tab_dash.js"), json.dumps({"pre": XS, "rows": XS})], capture_output=True, text=True, timeout=60)
    hx5 = "".join(json.loads(pr.stdout)) if pr.stdout.strip() else ""
    T.chk(hx5 and "<img" not in hx5 and "&#60;img" in hx5, "F5 심볼에 '<' = 칩 글자 escape", hx5[:200])

print("[Y] 검수 2차 시나리오 — 정상 코인 네트워크 보존 · 지갑에만 있는 코인 · 미발송 점검 · 공백 뒤 재중지 · pre 해제 · TON→GRAM · 오래 빠짐 · 멈춤 노랑")
y1n = {"Z": {"A": [True, True], "B": [True, True]}}
y1c = {"Z": {"A": [True, False]}}
yz = W.update(W.update({}, y1n, NOW), y1n, NOW + 600)
yz = W.update(W.update(yz, y1c, NOW + 1200), y1c, NOW + 1800)
T.chk(((yz["c"].get("Z") or {}).get("w") or {}).get("st") != "on" and yz["nets"]["Z"]["B"][0] == "11", "Y1 정상 코인의 열린 네트워크가 응답에서 빠짐 = 열림 유지(가짜 전부 중지 없음)", yz.get("c"))
WANTED.clear()
write_doc(ex_doc({"binance": {"ETH": {"d": "all"}}}))


class SBN(SB):
    def __init__(self):
        super().__init__()
        self.spot = type("Sp", (), {"ex_price": staticmethod(lambda e, s9: None), "want_ex": lambda s9, exs: WANTED.update(exs)})()


class ConnN:
    def execute(self, q, args):
        return [(5, "native", "eth", None)]


y2 = exhalt.part(SBN(), [ROWS[5]], {}, ConnN(), 50, NOW)
T.chk([r["key"] for r in (y2.get("exHalt") or {}).get("rows", [])] == ["binance|ETH|d"] and "binance" in WANTED,
      "Y2 거래소 보유 0 · 지갑 네이티브 ETH 만 · 거래소 시세 아직 없음 = 입금 중지 칸 나옴 · 감시 거래소 시세 등록(want_ex)", (y2, WANTED))
fresh()
RT0 = dict({f"R{i:02d}": {"N": (True, True)} for i in range(20)}, BTC={"MAIN": (True, True)})
RT1 = dict(RT0, **{f"R{i:02d}": {"N": (True, False)} for i in range(20)})
RT2 = dict(RT0, **{f"R{i:02d}": {"N": (True, False)} for i in range(9)})
RH = exhalt.holdings([{"key": f"g{500 + i}", "sym": f"R{i:02d}", "qty": 10, "price": 10, "locs": []} for i in range(20)], {500 + i: "binance" for i in range(20)}, {}, {})
rst, rout = {"exhalt": {"init": 1, "inc": {}}}, []
for t, tb in ((0, RT0), (600, RT0), (1200, RT1), (1800, RT2)):
    wrun({"binance": tb}, NOW + t)
    v9 = exhalt.view(W.load(), RH, 50, px, NOW + t)
    rout += exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, rst, NOW + t, None, True, FMT)
T.chk(len(rout) == 1 and "9개" in rout[0]["text"] and not st_ex("binance").get("maint"), "Y3 점검이 알리기 전에 끝남 = 남은 9개는 새로 알림(묶음 한 통)", [x["text"][:40] for x in rout])
fresh()
y4h = exhalt.holdings([{"key": "g1", "sym": "XYZ", "qty": 100, "price": 10, "locs": []}], {1: "binance"}, {}, {})
y4s, y4o = {"exhalt": {"init": 1, "inc": {}}}, []
for t, tb in ((0, K1), (600, K1), (1200, K2), (1800, K2), (2400, K1), (2400 + 4200, K2), (2400 + 4800, K2)):
    wrun({"binance": tb}, NOW + t)
    v9 = exhalt.view(W.load(), y4h, 50, px, NOW + t)
    y4o += [x["text"].split("\n")[0] for x in exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, y4s,
                                                                 NOW + t, None, True, FMT)]
T.chk(y4o.count("🔴 바이낸스 XYZ 출금이 막혔어요") == 2, "Y4 알림 → 정상 1번 → 수집 1시간 멈춤 → 다시 막힘 = 새 사건(30분 넘음 · 공백도 경과)", y4o)
fresh()
P5a = dict(BASE, XYZ={"A": (True, False), "B": (True, False)})
P5b = dict(BASE, XYZ={"A": (True, True), "B": (True, False)})
y5s, y5o = {"exhalt": {"init": 1, "inc": {}}}, []
for t, tb in [(0, P5a), (600, P5a)] + [(1200 + 600 * i, P5b) for i in range(6)] + [(4800, P5a), (5400, P5a)]:
    wrun({"binance": tb}, NOW + t)
    v9 = exhalt.view(W.load(), QH, 50, px, NOW + t)
    y5o += [x["text"].split("\n")[0] for x in exhalt.prod_exhalt({"out": {"builtAt": NOW + t, "fields": {"exHalt": v9}}, "cur": "KRW"}, REC, y5s,
                                                                 NOW + t, None, True, FMT)]
T.chk(y5o == ["🔴 바이낸스 XYZ 출금이 막혔어요"] and not st_ex("binance")["c"]["XYZ"]["w"].get("pre"),
      "Y5 처음부터 전부 막힘(pre) → 일부 1시간 열림 → 다시 전부 막힘 = pre 해제 · 새 사건(칩·알림)", y5o)
y6 = exhalt.view(ex_doc({"binance": {"GRAM": {"d": "all"}}}), exhalt.holdings([{"key": "g9", "sym": "TON", "qty": 100, "price": 5.0, "locs": [{"w": "TON 지갑", "ch": "TON"}]}],
                                                                          {}, {9: {"native": True, "pairs": []}}, {}), 50, lambda e, s9: 5.1 if s9 == "GRAM" else None, NOW)
T.chk([r["key"] for r in y6["rows"]] == ["binance|GRAM|d"] and y6["rows"][0]["usd"] == 500.0, "Y6 지갑 네이티브 TON = 거래소 GRAM(기존 티커 매핑 재사용)", y6["rows"])
import pricing  # noqa: E402
T.chk(exhalt.NATIVE_EX_TICKER == pricing.NATIVE_EX_TICKER, "Y6b 네이티브 → 거래소 티커 표 = pricing 과 같음")
y7 = {"Q": {"A": [True, False]}, "K": {"A": [True, True]}}
y7r = W.update(W.update({}, y7, NOW), y7, NOW + 600)
y7r["c"]["Q"]["w"].pop("pre", None)
y7r = W.update(y7r, {"K": {"A": [True, True]}}, NOW + 1200)
y7r = W.update(y7r, {"K": {"A": [True, True]}}, NOW + 1200 + W.MISS_KEEP + 60)
T.chk(y7r["c"]["Q"]["w"].get("st") == "unk", "R7a 막힌 코인이 하루 넘게 응답에서 빠짐 = 미확인(unk)", y7r["c"].get("Q"))
write_doc({"ex": {"binance": dict(y7r, at=int(NOW))}})
y7s = {"exhalt": {"init": 1, "gen": {}, "inc": {"binance|Q|w": {"s": int(NOW), "at": int(NOW)}}}}
y7v = exhalt.view({"ex": {"binance": dict(y7r, at=int(NOW))}}, exhalt.holdings([{"key": "g2", "sym": "Q", "qty": 100, "price": 10, "locs": []}], {2: "binance"}, {}, {}), 50, px, NOW)
y7o = exhalt.prod_exhalt({"out": {"builtAt": NOW, "fields": {"exHalt": y7v}}, "cur": "KRW"}, REC, y7s, NOW, None, True, FMT)
T.chk(y7o == [] and not y7s["exhalt"]["inc"], "R7b 미확인 = 조용히 지움(가짜 ✅ 없음)", y7o)
write_doc({"ex": {"gate": {"at": int(NOW - 7300), "try": int(NOW - 7300), "err": ""}}})
T.chk(any(x["cid"] == "exwallet:gate" and x["level"] == "warn" for x in exhalt.health_items(NOW)), "R8 오류 글 없이 2시간 넘게 성공 없음(쉼 등) = 노랑")

print("[Z] 검수 3차 시나리오 — 정상 이력 코인 복귀 · 소액 기준 오감 · 만료 네트워크 = 미확인 · 미확인 동안 pre 보존")
MK = W.MISS_KEEP + 60
z1n = dict({f"K{i}": {"A": [True, True]} for i in range(5)}, Q={"A": [True, True]})
z1o = {k: v for k, v in z1n.items() if k != "Q"}
z1b = dict(z1o, Q={"A": [True, False]})
zr1 = W.update(W.update({}, z1n, NOW), z1n, NOW + 600)
zr1 = W.update(W.update(zr1, z1o, NOW + 1200), z1o, NOW + 1200 + MK)
zr1 = W.update(W.update(zr1, z1b, NOW + 1800 + MK), z1b, NOW + 2400 + MK)
T.chk(zr1["c"]["Q"]["w"].get("st") == "on" and not zr1["c"]["Q"]["w"].get("pre"), "Z1 정상으로 본 코인이 하루 넘게 빠졌다 막힌 채 돌아옴 = 새 사건(pre 아님 · 알림 대상)", zr1["c"].get("Q"))
zst, zout = {"exhalt": {"init": 1, "inc": {}}}, []
ZD = ex_doc({"binance": {"XYZ": {"w": "all"}}})
write_doc(ZD)
for i, q9 in enumerate((10, 4, 10, 4, 10, 4, 10, 4, 10)):
    zh = exhalt.holdings([{"key": "g1", "sym": "XYZ", "qty": q9, "price": 10, "locs": []}], {1: "binance"}, {}, {})
    zv = exhalt.view(ZD, zh, 50, px, NOW + 60 * i)
    zout += exhalt.prod_exhalt({"out": {"builtAt": NOW + 60 * i, "fields": {"exHalt": zv}}, "cur": "KRW"}, REC, zst, NOW + 60 * i, None, True, FMT)
T.chk(len(zout) == 1, "Z2 평가액이 소액 기준($50) 위아래로 8분 오감 = 같은 사건 알림 1통", [x["text"][:30] for x in zout])
z3a = {"Z": {"A": [True, True], "B": [True, True]}}
z3b = {"Z": {"A": [True, False]}}
zr3 = W.update(W.update({}, z3a, NOW), z3a, NOW + 600)
zr3 = W.update(W.update(zr3, z3b, NOW + 1200), z3b, NOW + 1800)
T.chk("B" in zr3["nets"]["Z"] and ((zr3["c"].get("Z") or {}).get("w") or {}).get("st") != "on", "Z3 B 가 2주기 빠짐(3주기 안) = 마지막 상태(열림) — 전부 막힘 아님", zr3["nets"]["Z"])
z4p = dict({f"K{i}": {"A": [True, True]} for i in range(5)}, **{f"P{i}": {"A": [True, False]} for i in range(8)})
z4o = {k: v for k, v in z4p.items() if not k.startswith("P")}
zr4 = W.update(W.update({}, z4p, NOW), z4p, NOW + 600)
zr4 = W.update(W.update(zr4, z4o, NOW + 1200), z4o, NOW + 1200 + MK)
mid = all(zr4["c"][f"P{i}"]["w"].get("st") == "unk" and zr4["c"][f"P{i}"]["w"].get("pre") for i in range(8))
zr4 = W.update(W.update(zr4, z4p, NOW + 1800 + MK), z4p, NOW + 2400 + MK)
zh4 = exhalt.holdings([{"key": f"g{600 + i}", "sym": f"P{i}", "qty": 10, "price": 10, "locs": []} for i in range(8)], {600 + i: "binance" for i in range(8)}, {}, {})
zd4 = {"ex": {"binance": dict(zr4, at=int(NOW + 2400 + MK))}}
write_doc(zd4)
zv4 = exhalt.view(zd4, zh4, 50, px, NOW + 2400 + MK)
za4 = exhalt.prod_exhalt({"out": {"builtAt": NOW + 2400 + MK, "fields": {"exHalt": zv4}}, "cur": "KRW"}, REC, {"exhalt": {"init": 1, "inc": {}}},
                         NOW + 2400 + MK, None, True, FMT)
T.chk(mid and all(zr4["c"][f"P{i}"]["w"].get("pre") for i in range(8)) and za4 == [] and zv4["preN"] == 8,
      "Z4 처음부터 막힌 8개가 하루 넘게 빠졌다 막힌 채 돌아옴 = pre 그대로(알림 0 · 접힘 줄 8)", (mid, za4, zv4.get("preN")))

zr5 = W.update(W.update({}, z3a, NOW), z3a, NOW + 600)
for k9 in range(5):
    zr5 = W.update(zr5, z3b, NOW + 1200 + 600 * k9)
z5on = zr5["c"]["Z"]["w"].get("st") == "on" and "B" not in zr5["nets"]["Z"] and not zr5["c"]["Z"]["w"].get("pre")
zr5 = W.update(zr5, {"Z": {"A": [True, False], "B": [True, True]}}, NOW + 4200)
zr5 = W.update(zr5, {"Z": {"A": [True, False], "B": [True, True]}}, NOW + 4800)
T.chk(z5on and zr5["c"]["Z"]["w"].get("st") == "off" and zr5["c"]["Z"]["w"].get("pn") == 2,
      "Z5 A·B 열림 → B 빠짐·A 막힘 → 3주기 뒤 B 판정에서 뺌 + 2주기 = 전부 막힘 사건 · B 다시 열림으로 나타남 = 일부", zr5["c"].get("Z"))

print("[V] 교차 검수 — 빌드 한 박자 늦음 · 시세 오감 · 점검 이어받기(알림 꺼짐 중 시작) · 손상 읽기 = 낡음")
write_doc(D0)
vst, vout = {"exhalt": {"init": 1, "inc": {}}}, []
VR = exhalt.view(D0, hold, 50, px, NOW)
for i, rows9 in enumerate((VR, dict(VR, rows=[]), VR, dict(VR, rows=[]), VR)):
    vout += exhalt.prod_exhalt({"out": {"builtAt": NOW + 60 * i, "fields": {"exHalt": rows9}}, "cur": "KRW"}, REC, vst, NOW + 60 * i, None, True, FMT)
T.chk(len(vout) == 1, "V1 파일은 막힘인데 빌드 줄이 한 박자 늦게 빠졌다 돌아옴 = 같은 사건 알림 정확히 1번", [x["text"][:30] for x in vout])
VD = ex_doc({"binance": {"XYZ": {"d": "all"}}})
write_doc(VD)
vh = exhalt.holdings([{"key": "g4", "sym": "XYZ", "qty": 100, "price": 10, "locs": []}], {4: "upbit"}, {}, {})
vst2, vout2 = {"exhalt": {"init": 1, "inc": {}}}, []
for i in range(6):
    pxv = (lambda e, s9: 10.0) if i % 2 == 0 else (lambda e, s9: None if e == "binance" else 10.0)
    vv = exhalt.view(VD, vh, 50, pxv, NOW + 60 * i)
    vout2 += exhalt.prod_exhalt({"out": {"builtAt": NOW + 60 * i, "fields": {"exHalt": vv}}, "cur": "KRW"}, REC, vst2, NOW + 60 * i, None, True, FMT)
T.chk(len(vout2) == 1, "V2 시세가 None(낡음)으로 오가 칸이 나왔다 빠짐 = 알림 1번", [x["text"][:30] for x in vout2])
fresh()
for t, tb in ((0, T1), (600, T1), (1200, T2), (1800, T2)):
    wrun({"binance": tb}, NOW + t)
mst = {"exhalt": {"init": 1, "inc": {}}}
_v, m5 = exhalt.view(W.load(), WH, 50, px, NOW + 1800), None
exhalt.prod_exhalt({"out": {"builtAt": NOW + 1800, "fields": {"exHalt": _v}}, "cur": "KRW"}, REC, mst, NOW + 1800, None, False, FMT)
wrun({"binance": T3}, NOW + 2400)
v10 = exhalt.view(W.load(), WH, 50, px, NOW + 2400)
m6 = exhalt.prod_exhalt({"out": {"builtAt": NOW + 2400, "fields": {"exHalt": v10}}, "cur": "KRW"}, REC, mst, NOW + 2400, None, True, FMT)
T.chk(m6 == [] and len(v10["rows"]) == 14, "V3 알림 꺼진 동안 시작된 점검이 끝남 = 남은 14개 몰아 보내기 없음(점검 사건 기억으로 이어받음)", [x["text"][:30] for x in m6])
write_doc(D0)
vst3 = {"exhalt": {"init": 1, "inc": {}}}
exhalt.prod_exhalt({"out": {"builtAt": NOW, "fields": {"exHalt": exhalt.view(D0, hold, 50, px, NOW)}}, "cur": "KRW"}, REC, vst3, NOW, None, True, FMT)
exhalt.load()
with open(paths.state(W.FILE), "w") as f:
    f.write("{깨짐")
os.utime(paths.state(W.FILE), (NOW + 5, NOW + 5))
bad9 = exhalt.load()
vb = exhalt.prod_exhalt({"out": {"builtAt": NOW + 60, "fields": {"exHalt": exhalt.part(SB(), ROWS, EXG, Conn(), 50, NOW + 60).get("exHalt")}}, "cur": "KRW"},
                        REC, vst3, NOW + 60, None, True, FMT)
T.chk(bad9.get("ex") and vb == [] and "binance|XYZ|w" in vst3["exhalt"]["inc"], "V4 상태 파일 손상 읽기 = 마지막 정상 문서(칩 유지 · 알림 기억 안 지움)", (sorted(bad9), vb))

T.chk(W.start_background(lambda: ENV) is None and W._THREAD["t"] is None, "T1 입금주소 스레드(tj-depaddr) 없는 실행(시험·부분 기동) = 입출금 상태 스레드 안 띄움")

print("[BI] 실제 빌드 꼬리에 exHalt 칸")
import db as dbm  # noqa: E402

con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (1,'XYZ#1',18)")
con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (1,'exchange_currency',NULL,'binance:xyz','XYZ',8,1,0,1)")
con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw, leg_kind, event,"
            " classifier_ver) VALUES (1,'exchange','binance:deposit','d-1',0,?,1,'exchange:binance',?,NULL,NULL,'move_in','EXF_DEPOSIT',5)",
            (int(time.time()) - 5 * 86400, str(100 * 10 ** 8)))
con.execute("INSERT INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (1,'exchange:binance','100.000000000000','0','0')")
con.commit()
con.close()
import web  # noqa: E402

TN = time.time()


def build_fields():
    b9 = web.StateBuilder()
    sp9 = b9.spot
    sp9.rate, sp9.rate_ts = 1400.0, TN
    sp9._ex_done = {"upbit", "binance", "bybit", "okx", "gate", "kucoin", "bithumb"}
    sp9.ex_usd["binance:XYZ"], sp9.ex_ts["binance:XYZ"] = 12.0, TN
    sp9.upbit_krw, sp9.upbit_alt = set(), {}
    b9.px.d["neg_ts"]["_fx"] = TN
    out9 = T.safe(b9.build)
    return (out9 or {}).get("fields") or {} if isinstance(out9, dict) else {}


if os.path.exists(paths.state(W.FILE)):
    os.remove(paths.state(W.FILE))
exhalt._CACHE["v"] = (None, None)
f0 = build_fields()
T.chk(bool(f0.get("coins")) and "exHalt" not in f0, "BI1 상태 파일 없음 = 빌드 응답에 칸 없음(종전과 같음)", sorted(f0)[:5])
write_doc(ex_doc({"binance": {"XYZ": {"w": "all"}}}, at=TN))
f1 = build_fields()
rows1 = ((f1.get("exHalt") or {}).get("rows")) or []
T.chk([r["key"] for r in rows1] == ["binance|XYZ|w"] and abs(rows1[0]["usd"] - 1200.0) < 1e-6 and rows1[0]["exN"] == "바이낸스",
      "BI2 상태 파일 있음 = 바이낸스 XYZ 출금 중지 · 내 보유 $1,200(100 × $12)", f1.get("exHalt"))
T.chk({k: v for k, v in f0.items() if k != "exHalt"}.keys() == {k: v for k, v in f1.items() if k != "exHalt"}.keys(), "BI3 다른 칸 이름 그대로(새 칸 하나만)")
T.finish()
