#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import sqlite3
import stat
import time as _real_time

os.environ["TJ_HEALTH"] = "0"
W1 = "0x" + "c1" * 20
W2 = "0x" + "c2" * 20
CFG0 = {
    "chains": {
        "eth": {"blockscout": "https://eth.invalid", "rpcs": ["https://eth-rpc.invalid"]},
        "scroll": {"blockscout": "https://scroll.invalid", "rpcs": ["https://scroll-rpc.invalid"], "enabled": True},
        "gnosis": {"blockscout": "https://gnosis.invalid", "rpcs": ["https://gnosis-rpc.invalid"]},
        "robinhood": {"rpcs": ["https://rh-rpc.invalid"]},
    },
    "wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "가"},
                {"type": "evm", "chain": "scroll", "address": W1, "label": "가"},
                {"type": "evm", "chain": "scroll", "address": W2, "label": "나"},
                {"type": "evm", "chain": "gnosis", "address": W1, "label": "가"},
                {"type": "evm", "chain": "robinhood", "address": W1, "label": "가"},
                {"type": "bsc_rpc", "address": W1, "label": "가"}],
    "bsc": {"logs_rpcs": ["https://bsc.invalid"]},
    "chain_sweep": {"enabled": True, "auto_enable": True, "ignore": ["manual-x"]},
}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG0, f)
import common

assert T.TMP in common.STATE_DIR and T.TMP in common.CONFIG_PATH
import chainoff as CO
import chaincatalog
import settings_store as ss

if (chaincatalog.CATALOG.get("megaeth") or {}).get("discovery", "explorer") == "rpc" or "megaeth" not in chaincatalog.CATALOG:
    T.chk(False, "시험 전제: 카탈로그에 탐색기 체인 megaeth 가 있어야 함(자동 체인 시험 대상)")
    T.finish()


class Clock:

    def __init__(self, t):
        self.t = float(t)

    def time(self):
        return self.t

    def __getattr__(self, name):
        return getattr(_real_time, name)


T0 = 1_900_000_000.0
DAY = 86400
U = int(T0 - 3600)
CLK = Clock(T0)
CO.time = CLK
S = common.STATE_DIR
EVM = ("eth", "scroll", "gnosis", "megaeth", "robinhood")
CW = {"eth": [W1], "scroll": [W1, W2], "gnosis": [W1], "megaeth": [W1], "robinhood": [W1]}


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


def wj(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def rm(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def book(ch, **kw):
    sm = {"scope": ch, "basePoll": 180, "tiers": [1, 0, 0, 0, 0], "filling": 0, "empty": 0, "holds": {}}
    sm.update(kw.pop("summary", {}))
    b = {"scope": ch, "path": "blockscout", "pairs": {a: {"code": "eoa"} for a in CW[ch]}, "updatedAt": int(T0 - 60), "summary": sm}
    b.update(kw)
    wj(os.path.join(S, f"addr_tier_{ch}.json"), b)


def gate(nonces=None, mega_days=45.0, chains_ok=None, extra=None):
    nn = {("eth", W1): 50, ("scroll", W1): 3, ("scroll", W2): 10, ("gnosis", W1): None, ("megaeth", W1): 1, ("robinhood", W1): 0}
    nn.update(nonces or {})
    pairs = {}
    for (c, a), n in nn.items():
        if n is None:
            continue
        pairs[f"{c}:{a}"] = {"active": True, "nonce": n, "lastChecked": U}
    if mega_days is not None:
        pairs[f"megaeth:{W1}"].update(activatedAt=int(T0 - mega_days * DAY), firstSeen=int(T0 - mega_days * DAY))
    pairs.update(extra or {})
    chs = {c: {"ok": True, "checkedAt": U, "addrs": list(CW[c])} for c in EVM}
    chs.update(chains_ok or {})
    wj(common.ACTIVITY_GATE_PATH, {"version": 1, "updatedAt": U, "pairs": pairs, "chains": chs})


def ledger(sends=(), recon=("eth", "scroll", "gnosis", "megaeth")):
    rm(common.DB_PATH)
    c = sqlite3.connect(common.DB_PATH)
    c.execute("CREATE TABLE postings (source_kind TEXT, source_ns TEXT, source_id TEXT, event_ts INTEGER, location TEXT, leg_kind TEXT)")
    c.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    c.execute("CREATE TABLE raw_observations (obs_id TEXT PRIMARY KEY, payload TEXT)")
    for i, (ch, a, ts) in enumerate(sends):
        c.execute("INSERT INTO postings VALUES ('chain_tx', ?, ?, ?, ?, 'gas')", (ch, "0x%064x" % (i + 1), int(ts), f"wallet:{ch}:{a}"))
    for ch in recon:
        c.execute("INSERT INTO meta VALUES (?, '1')", (f"recon_done_{ch}",))
        c.execute("INSERT INTO raw_observations VALUES (?, ?)", (f"recon:{ch}", json.dumps({a: {"bal": "0"} for a in CW[ch]})))
    c.commit()
    c.close()


def reset(cfg=None, **gkw):
    wj(CP, cfg if cfg is not None else CFG0)
    for ch in EVM:
        book(ch)
        wj(os.path.join(S, f"cursor_evm_{ch}.json"), {a: 1000 for a in CW[ch]})
    gate(**gkw)
    ledger()
    for fn in ("ui_prefs.json", CO.KEEP_ON_NAME, "runner_evm.json", "wallet_reload.json"):
        rm(os.path.join(S, fn))
    CO.BAL_FN = None
    CO.AUTO_INFO_FN = None
    CLK.t = T0
    fresh_cache()


def fresh_cache():
    CO._SENT_CACHE.update(at=0.0, db=None, v=None)


def rows(now=None):
    fresh_cache()
    s = CO.summary(now)
    return {r["key"]: r for r in s["rows"]}, s


def raw_cfg():
    with open(CP, encoding="utf-8") as f:
        return json.load(f)


def cfg_bytes():
    with open(CP, "rb") as f:
        return f.read()


reset()
G = {"updatedAt": U, "chains": {"x": {"ok": True, "checkedAt": U, "addrs": [W1, W2]}},
     "pairs": {f"x:{W1}": {"nonce": 4, "lastChecked": U}}}
TP = {W1: {"code": "eoa"}, W2: {"code": "eoa"}}
NO = CO._nonce_of
check("C1a EOA · 최근 점검 성공 · 그 점검 값 = nonce", NO("x", W1, G, TP, T0) == 4)
check("C1b 쌍 없음 + 그 점검이 읽은 비활성 목록(addrs) = 0", NO("x", W2, G, TP, T0) == 0)
check("C1c 쌍도 목록도 없음 = 모름", NO("x", "0x" + "c3" * 20, G, {"0x" + "c3" * 20: {"code": "eoa"}}, T0) is None)
for why, tp in (("장부 항목 없음", {}), ("계약", {W1: {"code": "contract"}}), ("위임(7702)", {W1: {"code": "delegated"}}), ("code 미확인", {W1: {}}),
                ("장부 꼴 아님", None)):
    check(f"C1d {why} = 모름(nonce ≠ 보낸 거래 수일 수 있음)", NO("x", W1, G, tp, T0) is None)
G2 = json.loads(json.dumps(G))
G2["chains"]["x"]["ok"] = False
check("C1e 그 체인 최근 점검 실패 = 모름", NO("x", W1, G2, TP, T0) is None)
G3 = json.loads(json.dumps(G))
G3["chains"]["x"]["checkedAt"] = U - 86400
check("C1f 그 체인 점검 시각 ≠ 게이트 최근 점검(그 체인만 지난 판) = 모름", NO("x", W1, G3, TP, T0) is None)
check("C1g 48시간 경계: 정확히 48시간 = 앎 · 1초 넘음 = 모름 · 미래 시각 = 모름",
      NO("x", W1, G, TP, U + 48 * 3600) == 4 and NO("x", W1, G, TP, U + 48 * 3600 + 1) is None and NO("x", W1, G, TP, U - 1) is None)
for why, ent in (("다른 판 값(lastChecked 다름)", {"nonce": 4, "lastChecked": U - 1}), ("음수", {"nonce": -1, "lastChecked": U}),
                 ("불리언", {"nonce": True, "lastChecked": U}), ("글자", {"nonce": "4", "lastChecked": U})):
    G4 = json.loads(json.dumps(G))
    G4["pairs"][f"x:{W1}"] = ent
    check(f"C1h 쌍 nonce {why} = 모름", NO("x", W1, G4, TP, T0) is None)
check("C1i Solana = 늘 모름", NO("sol", W1, G, TP, T0) is None)
check("C1j 게이트 꼴 이상 = 모름(예외 없음)", NO("x", W1, {"chains": [], "pairs": []}, TP, T0) is None and NO("x", W1, {}, TP, T0) is None)

reset()
r, s = rows()
check("C2a 바탕: scroll(지갑 2개 nonce 3·10 — 경계 10 포함) = 추천 · maxNonce 10 · 모름 0",
      r["scroll"]["recommend"] and r["scroll"]["maxNonce"] == 10 and r["scroll"]["unknown"] == 0 and r["scroll"]["nonces"] == [3, 10], r["scroll"])
check("C2b gnosis(쌍 없음 → 점검 목록 = nonce 0) = 추천", r["gnosis"]["recommend"] and r["gnosis"]["nonces"] == [0], r["gnosis"])
check("C2c eth(nonce 50) = 추천 안 함 · 요약 nonceMax 10", not r["eth"]["recommend"] and s["nonceMax"] == 10 == CO.NONCE_MAX, r["eth"])
check("C2d 요약 칸(켜짐 수 · 추천 수 · 지갑 수 · 시각 = 가짜 시계)", s["at"] == int(T0) and s["nRec"] == sum(1 for x in r.values() if x["recommend"])
      and s["nWallets"] == 2 and s["nOn"] == len(r), s)
gate(nonces={("scroll", W2): 11})
r, _ = rows()
check("C2e 지갑 하나라도 nonce 11 = 추천 안 함", not r["scroll"]["recommend"] and r["scroll"]["maxNonce"] == 11, r["scroll"])
gate(nonces={("eth", W1): 0})
r, _ = rows()
check("C2f 이더리움 같은 핵심 체인도 예외 없음(nonce 0 = 추천)", r["eth"]["recommend"], r["eth"])
gate()
book("scroll", pairs={W1: {"code": "eoa"}})
r, _ = rows()
check("C2g 지갑 하나 nonce 모름(장부 EOA 확인 없음) = 추천 안 함 · unknown 1", not r["scroll"]["recommend"] and r["scroll"]["unknown"] == 1, r["scroll"])
book("scroll")
gate(chains_ok={"scroll": {"ok": False, "checkedAt": U, "addrs": CW["scroll"]}})
r, _ = rows()
check("C2h 그 체인 최근 점검 실패 = 모름 = 추천 안 함", not r["scroll"]["recommend"] and r["scroll"]["unknown"] == 2, r["scroll"])
gate()
CLK.t = U + 48 * 3600 + 1
book("scroll", updatedAt=int(CLK.t - 60))
book("gnosis", updatedAt=int(CLK.t - 60))
r, _ = rows()
check("C2i 점검이 48시간 넘게 낡음 = 추천 안 함", not r["scroll"]["recommend"] and not r["gnosis"]["recommend"], r["scroll"])
reset()
ledger(sends=[("scroll", W2, T0 - 1 * DAY)])
r, _ = rows()
check("C2j 최근 30일 내가 보낸 거래 1건 = 추천 안 함 · sent30 1 · 막대 마지막 칸", not r["scroll"]["recommend"] and r["scroll"]["sent30"] == 1
      and r["scroll"]["spark"][-1] == 1 and sum(r["scroll"]["spark"]) == 1 and len(r["scroll"]["spark"]) == 15, r["scroll"])
check("C2k 다른 체인은 영향 없음(gnosis 추천 · sent30 0)", r["gnosis"]["recommend"] and r["gnosis"]["sent30"] == 0, r["gnosis"])
ledger(sends=[("scroll", W2, T0 - 31 * DAY), ("scroll", W1, T0 - 29 * DAY), ("scroll", W1, T0 - 29 * DAY)])
r, _ = rows()
check("C2l 31일 전 거래는 안 셈 · 같은 tx 의 가스 레그 중복은 1건", r["scroll"]["sent30"] == 2 and not r["scroll"]["recommend"], r["scroll"]["sent30"])
c9 = sqlite3.connect(common.DB_PATH)
c9.execute("DELETE FROM postings")
c9.execute("INSERT INTO postings VALUES ('chain_tx', 'scroll', '0xaa', ?, ?, 'gas')", (int(T0 - DAY), f"wallet:scroll:{W1}"))
c9.execute("INSERT INTO postings VALUES ('chain_tx', 'scroll', '0xaa', ?, ?, 'gas')", (int(T0 - DAY), f"wallet:scroll:{W2}"))
c9.execute("INSERT INTO postings VALUES ('chain_tx', 'gnosis', '0xbb', ?, ?, 'fee')", (int(T0 - DAY), f"wallet:gnosis:{W1}"))
c9.execute("INSERT INTO postings VALUES ('cex', 'x', '0xcc', ?, ?, 'gas')", (int(T0 - DAY), f"wallet:gnosis:{W1}"))
c9.commit()
c9.close()
r, _ = rows()
check("C2m 한 tx 를 두 지갑이 나눠 기록해도 1건 · 가스 레그·체인 tx 만 셈", r["scroll"]["sent30"] == 1 and r["gnosis"]["sent30"] == 0, (r["scroll"]["sent30"], r["gnosis"]["sent30"]))
rm(common.DB_PATH)
r, _ = rows()
check("C2n 원장 없음(보낸 거래 확인 못 함) = 아무 체인도 추천 안 함 · sent30·spark 없음",
      not any(x["recommend"] for x in r.values()) and r["scroll"]["sent30"] is None and r["scroll"]["spark"] is None, {k: x["recommend"] for k, x in r.items()})
with open(common.DB_PATH, "wb") as f:
    f.write(b"not a database" * 100)
r, _ = rows()
check("C2o 원장 읽기 실패 = 추천 안 함(예외 없음)", not any(x["recommend"] for x in r.values()), {k: x["recommend"] for k, x in r.items()})
reset()
for why, kw in (("옛 기록 채우는 중(filling)", {"summary": {"filling": 1}}), ("첫 이력 읽는 중(holds boot)", {"summary": {"holds": {"boot": 1}}}),
                ("이력 재시도(holds hist)", {"summary": {"holds": {"hist": 2}}}), ("장부 요약 없음", {"summary": {}})):
    book("scroll", **kw)
    if why == "장부 요약 없음":
        b9 = json.load(open(os.path.join(S, "addr_tier_scroll.json")))
        b9["summary"] = {}
        wj(os.path.join(S, "addr_tier_scroll.json"), b9)
    r, _ = rows()
    check(f"C2p {why} = 추천 안 함", not r["scroll"]["recommend"], r["scroll"])
book("scroll")
CO.BAL_FN = lambda: {"scroll": 150.0, "gnosis": 99.99, "eth": None}
r, _ = rows()
check("C2q 잔고 $100 이상 = 추천은 그대로 + big 표시 · $99.99 = big 아님 · 값 None = $0",
      r["scroll"]["recommend"] and r["scroll"]["big"] and r["scroll"]["usd"] == 150.0 and not r["gnosis"]["big"] and r["eth"]["usd"] == 0.0, r["scroll"])
CO.BAL_FN = lambda: 1 / 0
r, _ = rows()
check("C2r 잔고 함수 실패 = 잔고 칸 숨김(usd None) · 추천 판정은 그대로", r["scroll"]["usd"] is None and r["scroll"]["recommend"], r["scroll"])
CO.BAL_FN = None
c = raw_cfg()
c["chains"]["gnosis"]["enabled"] = False
wj(CP, c)
r, s = rows()
check("C2s 이미 꺼 둔 체인 = on 거짓 · 추천 아님 · 상태 off · 지갑 수는 원래 config 그대로", not r["gnosis"]["on"] and not r["gnosis"]["recommend"]
      and r["gnosis"]["status"] == "off" and r["gnosis"]["wallets"] == 1 and s["nOff"] == 1, r["gnosis"])

reset()
r, _ = rows()
check("C3a BSC = 잠금 'sep'(따로 도는 수집기) · 추천 아님", not r["bsc"]["can"] and r["bsc"]["lock"] == "sep" and r["bsc"]["why"] == CO.UNSUPPORTED["bsc"]
      and not r["bsc"]["recommend"], r["bsc"])
check("C3b RPC 전용 체인(robinhood — 기본 발견 경로 rpc) = 잠금 'rpc' · nonce 0 이어도 추천 아님",
      not r["robinhood"]["can"] and r["robinhood"]["lock"] == "rpc" and r["robinhood"]["why"] == CO.RPC_ONLY_WHY and not r["robinhood"]["recommend"], r["robinhood"])
c = raw_cfg()
c["chains"]["gnosis"]["discovery"] = "rpc"
wj(CP, c)
r, _ = rows()
check("C3c 설정에서 discovery=rpc 로 바꾼 체인도 잠금", r["gnosis"]["lock"] == "rpc" and not r["gnosis"]["recommend"], r["gnosis"])
ONE = {"chains": {"scroll": dict(CFG0["chains"]["scroll"])}, "wallets": [w for w in CFG0["wallets"] if w.get("chain") == "scroll"],
       "chain_sweep": {"enabled": True}}
reset(cfg=ONE)
r, _ = rows()
check("C3d 러너 없는 설치의 마지막 EVM 체인 = 잠금 'last'(끄면 수집기 재시작 반복)", not r["scroll"]["can"] and r["scroll"]["lock"] == "last"
      and not r["scroll"]["recommend"], r["scroll"])
wj(os.path.join(S, "runner_evm.json"), {"ts": _real_time.time()})
r, s = rows()
check("C3e EVM 유닛 러너가 있으면 마지막 체인도 끌 수 있음 · 적용 방법 runner", r["scroll"]["can"] and s["apply"]["mode"] == "runner" and s["apply"]["evmRunner"], s["apply"])
wj(os.path.join(S, "runner_evm.json"), {"ts": _real_time.time(), "by": "reload"})
r, s = rows()
check("C3f 재시작 감시기(by=reload)는 러너 아님 = 마지막 체인 잠금 · 적용 방법 reload", r["scroll"]["lock"] == "last" and s["apply"]["mode"] == "reload", s["apply"])
reset()
for why, setup in (("커서 파일에 그 지갑 없음", lambda: wj(os.path.join(S, "cursor_evm_scroll.json"), {W1: 1000})),
                   ("커서 음수", lambda: wj(os.path.join(S, "cursor_evm_scroll.json"), {W1: 1000, W2: -1})),
                   ("백필 잡 지갑 목록", lambda: wj(os.path.join(S, "cursor_evm_scroll.json"), {W1: 1000, W2: 1000, "_bfjob": {"wallets": [W2.upper()]}})),
                   ("진행 표식 _bfes:", lambda: wj(os.path.join(S, "cursor_evm_scroll.json"), {W1: 1000, W2: 1000, "_bfes:" + W2: 1})),
                   ("장부 쌍 hold hist:*", lambda: book("scroll", pairs={W1: {"code": "eoa"}, W2: {"code": "eoa", "hold": "hist:bf"}})),
                   ("장부 쌍 hold boot", lambda: book("scroll", pairs={W1: {"code": "eoa"}, W2: {"code": "eoa", "hold": "boot"}})),
                   ("장부 쌍 fill(옛 기록 채우기)", lambda: book("scroll", pairs={W1: {"code": "eoa"}, W2: {"code": "eoa", "fill": "int"}})),
                   ("장부 30분 넘게 낡음", lambda: book("scroll", updatedAt=int(T0 - 1800 - 1))),
                   ("장부 없음", lambda: rm(os.path.join(S, "addr_tier_scroll.json")))):
    reset()
    setup()
    r, _ = rows()
    check(f"C3g 첫 수집 시작점 확인 안 됨({why}) = 잠금 'boot' · 추천 아님", r["scroll"]["lock"] == "boot" and not r["scroll"]["can"] and not r["scroll"]["recommend"],
          (r["scroll"]["lock"], r["scroll"]["why"]))
reset()
book("scroll", updatedAt=int(T0 - 1800))
r, _ = rows()
check("C3h 장부 정확히 30분 = 아직 신선(잠금 아님)", r["scroll"]["can"] and r["scroll"]["recommend"], r["scroll"]["lock"])
check("C3i _first_scan_missing: 지갑 없음 = 잠금 아님 · 대소문자 무관",
      CO._first_scan_missing("scroll", [], {}, T0) is False and CO._first_scan_missing("scroll", [W2.upper()], json.load(open(os.path.join(S, "addr_tier_scroll.json"))), T0) is False)

for days, exp_rec, exp_new in ((45.0, True, None), (3.0, False, 3), (29.5, False, 29), (30.0, True, None), (None, True, None)):
    reset(mega_days=days)
    r, s = rows()
    m = r.get("megaeth") or {}
    check(f"C4a 활동 게이트가 자동으로 켠 megaeth · 켠 지 {days}일 = 추천 {exp_rec} · autoNewDays {exp_new}",
          m.get("auto") is True and m.get("recommend") is exp_rec and m.get("autoNewDays") == exp_new and s["autoGraceDays"] == 30, m)
reset(mega_days=3.0, extra={f"scroll:{W1}": {"active": True, "nonce": 3, "lastChecked": U, "activatedAt": int(T0 - DAY)}})
r, _ = rows()
check("C4b 명시(설정에 있는) 체인 = 최근 활성 쌍이 있어도 유예 없음", r["scroll"]["recommend"] and r["scroll"]["autoNewDays"] is None and not r["scroll"]["auto"], r["scroll"])
check("C4c _auto_since: activatedAt 없으면 firstSeen · 비활성 쌍·다른 체인 접두 무시 · 가장 이른 값",
      CO._auto_since("x", {"pairs": {f"x:{W1}": {"active": True, "firstSeen": 100}, f"x:{W2}": {"active": True, "activatedAt": 300, "firstSeen": 50},
                                     "x:z": {"active": False, "activatedAt": 5}, "xy:q": {"active": True, "activatedAt": 1},
                                     "x:b": {"active": True, "activatedAt": True}}}) == 100 and CO._auto_since("x", {}) is None and CO._auto_since("x", None) is None)
reset(mega_days=3.0)
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {}}
off = CO.auto_off()
check("C4d 유예 중인 자동 체인은 자동 끄기도 안 함(다른 추천 체인은 끔)", "megaeth" not in off and set(off) == {"scroll", "gnosis"}, off)

reset()
UP = os.path.join(S, "ui_prefs.json")
for why, body, exp in (("파일 없음", None, True), ("칸 없음", {"dust_usd": 50}, True), ("켬", {"chain_auto_off": {"on": True, "at": 1}}, True),
                       ("끔", {"chain_auto_off": {"on": False, "at": 1}}, False), ("on 글자 'true'", {"chain_auto_off": {"on": "true"}}, False),
                       ("on 1", {"chain_auto_off": {"on": 1}}, False), ("칸이 불리언", {"chain_auto_off": True}, False),
                       ("파일이 리스트", [1], False), ("손상된 JSON", "{깨짐", False)):
    rm(UP)
    if isinstance(body, str):
        with open(UP, "w", encoding="utf-8") as f:
            f.write(body)
    elif body is not None:
        wj(UP, body)
    check(f"C5a 스위치 {why} = {'켬' if exp else '끔'}", CO.auto_enabled() is exp)
wj(UP, {"chain_auto_off": {"on": False, "at": 1}})
CO.AUTO_INFO_FN = lambda: {"lim": 100.0, "chains": {}}
b0 = cfg_bytes()
off = CO.auto_off()
r, s = rows()
check("C5b 스위치 끔 = 자동 끄기 0 · 설정 무변 · 추천 표시는 그대로 · 화면 스위치 칸 끔", off == [] and cfg_bytes() == b0 and r["scroll"]["recommend"]
      and s["autoOffOn"] is False, (off, s["autoOffOn"]))
wj(UP, {"chain_auto_off": {"on": False}})
res = CO.set_enabled("scroll", False)
check("C5c 스위치 끔이어도 손으로 끄기는 됨", res["changed"] and raw_cfg()["chains"]["scroll"]["enabled"] is False, res)
wj(UP, {"chain_auto_off": {"on": True}})
reset()
CO.AUTO_INFO_FN = lambda: {"lim": 100.0, "chains": {}}
check("C5d 스위치 켬(또는 칸 없음) = 추천 체인을 끔", sorted(CO.auto_off()) == ["gnosis", "megaeth", "scroll"])

for why, fn in (("판정 정보 없음(빌드 전)", None), ("판정 함수 실패", lambda: 1 / 0), ("꼴 이상", lambda: {"lim": 50}),
                ("체인 표가 리스트", lambda: {"lim": 50, "chains": []}), ("기준 글자", lambda: {"lim": "x", "chains": {}}),
                ("기준 없음", lambda: {"chains": {}})):
    reset()
    CO.AUTO_INFO_FN = fn
    b0 = cfg_bytes()
    check(f"C6a {why} = 자동 끄기 안 함(안전 쪽) · 설정 무변", CO.auto_off() == [] and cfg_bytes() == b0)
reset()
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {"scroll": {"usd": 0.0, "unk": True}, "gnosis": {"usd": 0.0}, "megaeth": {"usd": 0.0, "unk": True}}}
off = CO.auto_off()
rc = raw_cfg()["chains"]
check("C6b 시세 장애(unk — 요즘 시세 있던 보유가 지금만 시세 없음) 체인 = 안 끔 · 값 아는 체인만 끔",
      off == ["gnosis"] and rc["scroll"].get("enabled") is True and rc["gnosis"]["enabled"] is False, (off, rc.get("scroll")))
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {"scroll": {"usd": 0.0}, "megaeth": {"usd": 0.0}}}
off2 = CO.auto_off()
check("C6c 시세가 돌아와 unk 풀리면 다음 판정에 끔", sorted(off2) == ["megaeth", "scroll"], off2)
for lim, usd, exp in ((50.0, 50.0, True), (50.0, 50.01, False), (500.0, 100.0, True), (500.0, 150.0, False), (-5.0, 0.0, True), (-5.0, 0.01, False)):
    reset()
    CO.AUTO_INFO_FN = lambda lim=lim, usd=usd: {"lim": lim, "chains": {"scroll": {"usd": usd}, "gnosis": {"usd": 10 ** 9}, "megaeth": {"usd": 10 ** 9}}}
    off = CO.auto_off()
    check(f"C6d 기준 {lim} · scroll 값 {usd} = {'끔' if exp else '안 끔'}(기준은 0~$100 로 자름 · 기준 이하만)", (off == ["scroll"]) is exp, off)
reset()
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {"scroll": {"usd": "x"}, "gnosis": {"usd": None}, "megaeth": 5}}
off = CO.auto_off()
check("C6e 값이 글자 = 그 체인 건너뜀 · None·꼴 이상 = $0 취급", sorted(off) == ["gnosis", "megaeth"], off)
reset()
res = CO.set_enabled("scroll", True)
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {}}
off = CO.auto_off()
check("C6f 손으로 켠 체인(chainoff_keep_on) = 자동 끄기에서 영구 제외", res["changed"] is False and "scroll" not in off and "scroll" in CO._keep_on(), (res, off))
reset()
ledger(recon=("eth", "gnosis"))
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {}}
off = CO.auto_off()
check("C6g 기초잔고 대사 전(recon_done 없음) 체인 = 안 끔", off == ["gnosis"], off)
reset()
c9 = sqlite3.connect(common.DB_PATH)
c9.execute("UPDATE raw_observations SET payload=? WHERE obs_id='recon:scroll'", (json.dumps({W1: {"bal": "0"}}),))
c9.commit()
c9.close()
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {}}
off = CO.auto_off()
check("C6h 대사에 없는 새 지갑이 있는 체인 = 안 끔", "scroll" not in off, off)
c9 = sqlite3.connect(common.DB_PATH)
c9.execute("INSERT INTO meta VALUES (?, '1')", (f"wrecon_done:scroll:{W2}",))
c9.commit()
c9.close()
off = CO.auto_off()
check("C6i 그 지갑 지갑별 대사 도장(wrecon_done) 생기면 끔", off == ["scroll"], off)
reset()
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {"gnosis": {"usd": 10 ** 9}, "megaeth": {"usd": 10 ** 9}}}
r, _ = rows()
assert r["scroll"]["recommend"]
CO.summary()
c9 = sqlite3.connect(common.DB_PATH)
c9.execute("INSERT INTO postings VALUES ('chain_tx', 'scroll', '0xdd', ?, ?, 'gas')", (int(T0 - 60), f"wallet:scroll:{W1}"))
c9.commit()
c9.close()
off = CO.auto_off()
check("C6j 자동 끄기 판정 = 보낸 거래를 원장에서 새로 읽음(5분 캐시의 옛 0건으로 쓰는 체인을 끄지 않음)", off == [], off)
reset()
CO.AUTO_INFO_FN = lambda: {"lim": 50.0, "chains": {"gnosis": {"usd": 10 ** 9}, "megaeth": {"usd": 10 ** 9}}}
b0 = raw_cfg()
off = CO.auto_off()
rc = raw_cfg()
mk = rc["chains"]["scroll"].get("_chainoff") or {}
rq = json.load(open(os.path.join(S, "wallet_reload.json")))["requests"][-1]
check("C6k 자동으로 끔 = enabled false · 표식 {at, auto, had} · ignore 에 안 넣음(새 잔고·활동은 계속 알림) · 손으로 켬 기록 안 건드림",
      off == ["scroll"] and rc["chains"]["scroll"]["enabled"] is False and mk == {"at": int(T0), "auto": True, "had": True}
      and rc["chain_sweep"]["ignore"] == ["manual-x"] and not os.path.exists(os.path.join(S, CO.KEEP_ON_NAME)), (off, rc["chains"]["scroll"], rc["chain_sweep"]))
check("C6l 적용 요청 기록(state/wallet_reload.json · source chainoff · 수집기·원장·웹)", rq.get("source") == "chainoff" and rq.get("chains") == ["scroll"]
      and rq.get("on") is False and rq.get("units") == CO.UNITS, rq)
r, _ = rows()
check("C6m 화면 = 꺼짐 · autoOff 표시 · offAt = 끈 시각", not r["scroll"]["on"] and r["scroll"]["autoOff"] and r["scroll"]["offAt"] == int(T0), r["scroll"])
check("C6n 다음 판정에 다시 끄지 않음(이미 꺼짐)", CO.auto_off() == [])
try:
    CO.set_enabled("scroll", True, auto=True)
    m9 = "통과"
except ValueError as e:
    m9 = str(e)
check("C6o 자동은 끄기만(켜기 요청 = 거부)", "끄기만" in m9, m9)

reset()
b0 = cfg_bytes()
for why, args in (("이름 형식(대문자·하이픈)", ("Bad-Key", False)), ("on 이 글자", ("scroll", "false")), ("BSC", ("bsc", False)), ("Solana", ("sol", False)),
                  ("설정에 없는 체인", ("zzz", False)), ("RPC 전용 체인", ("robinhood", False)), ("이름 아님", (None, False))):
    try:
        CO.set_enabled(*args)
        m9 = "통과"
    except ValueError as e:
        m9 = str(e) or "ValueError"
    check(f"C7a 거부: {why} = ValueError · 설정 무변", m9 != "통과" and cfg_bytes() == b0, m9)
res = CO.set_enabled("eth", False)
rc = raw_cfg()
bk = os.path.join(S, "backups", "config_chainoff", res.get("backup") or "?")
check("C7b 손으로 끔 = enabled false · 표식 {at, had 거짓(원래 enabled 칸 없음), ign} · ignore 에 추가",
      res["changed"] and res["on"] is False and rc["chains"]["eth"]["enabled"] is False
      and rc["chains"]["eth"]["_chainoff"] == {"at": int(T0), "had": False, "ign": True} and rc["chain_sweep"]["ignore"] == ["manual-x", "eth"], rc["chains"]["eth"])
check("C7c 백업 = 바꾸기 전 바이트 그대로 · 0600", os.path.exists(bk) and open(bk, "rb").read() == b0 and stat.S_IMODE(os.stat(bk).st_mode) == 0o600, bk)
check("C7d config.json 권한 0600 유지(그룹·다른 사용자 비트 없음)", stat.S_IMODE(os.stat(CP).st_mode) & 0o077 == 0, oct(os.stat(CP).st_mode))
lq = ss.load_config_quiet()
check("C7e 끈 체인 = 설정 읽기에서 체인·지갑 통째로 빠짐(_disabled_chains)", "eth" not in lq["chains"] and "eth" in lq["_disabled_chains"]
      and not any(w.get("chain") == "eth" for w in lq["wallets"]), lq.get("_disabled_chains"))
res = CO.set_enabled("eth", True)
rc = raw_cfg()
check("C7f 다시 켬 = 원래 모양(enabled·표식 칸 없음) · 내가 넣은 ignore 만 뺌(손으로 넣은 manual-x 유지) · 손으로 켬 기록",
      res["changed"] and rc["chains"]["eth"] == CFG0["chains"]["eth"] and rc["chain_sweep"]["ignore"] == ["manual-x"] and "eth" in CO._keep_on(), rc)
check("C7g 끄고 켜면 설정 = 처음과 같은 값", rc == json.loads(b0), rc)
res = CO.set_enabled("scroll", False)
CO.set_enabled("scroll", True)
check("C7h 원래 enabled:true 였던 체인 = 다시 켜면 enabled true 그대로", raw_cfg()["chains"]["scroll"] == CFG0["chains"]["scroll"], raw_cfg()["chains"]["scroll"])
c = raw_cfg()
c["chain_sweep"]["ignore"].append("GNOSIS")
wj(CP, c)
CO.set_enabled("gnosis", False)
rc = raw_cfg()
check("C7i 이미 ignore 에 있으면(대소문자 무관) 더 넣지 않고 표식 ign 없음", rc["chain_sweep"]["ignore"] == ["manual-x", "GNOSIS"] and "ign" not in rc["chains"]["gnosis"]["_chainoff"], rc)
CO.set_enabled("gnosis", True)
check("C7j 그 항목은 다시 켜도 그대로(이용자가 넣은 것)", raw_cfg()["chain_sweep"]["ignore"] == ["manual-x", "GNOSIS"], raw_cfg()["chain_sweep"])
reset()
lq = ss.load_config_quiet()
check("C7k 바탕: 활동 게이트가 megaeth 를 자동으로 켬(설정 파일엔 블록 없음)", "megaeth" in lq["chains"] and "megaeth" not in raw_cfg()["chains"], list(lq["chains"]))
res = CO.set_enabled("megaeth", False)
rc = raw_cfg()
check("C7l 자동 체인 끄기 = 끔 표식 블록만 새로({enabled false, _chainoff created})",
      rc["chains"]["megaeth"] == {"enabled": False, "_chainoff": {"at": int(T0), "created": True, "ign": True}} and "megaeth" in rc["chain_sweep"]["ignore"], rc["chains"].get("megaeth"))
lq = ss.load_config_quiet()
check("C7m 끈 자동 체인 = 설정 읽기에서 빠짐", "megaeth" not in lq["chains"] and "megaeth" in lq["_disabled_chains"], list(lq["chains"]))
r, _ = rows()
check("C7n 꺼진 자동 체인도 화면 줄에 남음(지갑 = 게이트 쌍)", "megaeth" in r and not r["megaeth"]["on"] and r["megaeth"]["wallets"] == 1, r.get("megaeth"))
CO.set_enabled("megaeth", True)
rc = raw_cfg()
check("C7o 다시 켬 = 블록 통째로 지움(게이트가 자동 정의로 다시 켬 — rpcs 없는 빈 블록 안 남김) · ignore 원래대로",
      "megaeth" not in rc["chains"] and rc["chain_sweep"]["ignore"] == ["manual-x"] and "megaeth" in ss.load_config_quiet()["chains"], rc)
reset()
r0 = CO.set_enabled("scroll", True)
check("C7p 이미 그 상태 = changed 거짓 · 설정 무변", r0["changed"] is False and r0["on"] is True and json.loads(cfg_bytes()) == CFG0, r0)
reset()
for i in range(20 + 3):
    CO.set_enabled("eth", i % 2 == 1)
bks = os.listdir(os.path.join(S, "backups", "config_chainoff"))
check("C7q 백업은 최근 20개만 남김(같은 초에 여러 번 저장해도 덮지 않음)", len(bks) == 20 and len(set(bks)) == len(bks), len(bks))
c = raw_cfg()
c["chain_sweep"] = ["깨짐"]
wj(CP, c)
b0 = cfg_bytes()
try:
    CO.set_enabled("gnosis", False)
    m9 = "통과"
except ValueError as e:
    m9 = str(e)
check("C7r config chain_sweep 꼴 이상 = 저장 전 거부 · 설정 무변", "chain_sweep" in m9 and cfg_bytes() == b0, m9)

reset()
try:
    import web
except Exception as e9:
    web = None
    check("C8 web 가져오기", False, e9)
if web is not None:
    web.time = CLK
    CLK.t = T0

    def dkst(days):
        return _real_time.strftime("%Y-%m-%d", _real_time.gmtime(T0 + 9 * 3600 - days * DAY))

    class FB:
        def __init__(self, out, dpx, live=None):
            self._last_out, self.daily_px = out, dpx
            self.daily = {"_live": live} if live else {}
            self._built_sig = "S"

        def _input_sig(self):
            return "S"

        def latest(self, max_age):
            return self._last_out

        def prefs(self):
            return {"dust_usd": 30}

    class FN:
        def view(self):
            return {"tracked": [{"chain": "gnosis", "value": {"usd": 4.0}}, {"chain": "eth", "value": {"usd": 999.0}, "hidden": True}]}

    web._nft_tracker = lambda: FN()
    CN = web.CHAIN_NAME
    OUT = {"fields": {"coins": [
        {"key": "g11", "price": 0, "locs": [{"ch": CN["gnosis"], "qty": 500}]},
        {"key": "g12", "price": 0, "locs": [{"ch": CN["scroll"], "qty": 1e9}]},
        {"key": "g13", "price": None, "locs": [{"ch": CN["eth"], "qty": 10}]},
        {"key": "g14", "price": 0, "locs": [{"ch": CN["base"], "qty": 10}]},
        {"key": "g15", "price": 2.0, "locs": [{"ch": CN["eth"], "qty": 3}]},
        {"key": "g16", "price": 0, "locs": [{"ch": CN["optimism"], "qty": 0}]}],
        "stables": [{"key": "g20", "price": 1.0, "locs": [{"ch": CN["scroll"], "qty": 7}]}],
        "lps": [{"chainKey": "gnosis", "value": 10.0, "fees": 1.0, "rewards": None}, {"chainKey": "eth", "value": 50.0, "closed": True}]}}
    DPX = {"_v": 1, dkst(1): {"p": {"11": 4.2, "12": 0, "16": 1.0}}, dkst(9): {"p": {"14": 1.0}}}
    web.BUILDER = FB(OUT, DPX, live={"date": dkst(0), "p": {"13": 7.0}})
    info = web._chain_auto_off_info()
    ch = (info or {}).get("chains") or {}
    check("C8a 어제 그날 고정가가 있던 코인이 지금만 시세 없음 = gnosis 값 모름(unk) · LP·NFT 값은 합산(11+4)",
          (ch.get("gnosis") or {}).get("unk") is True and abs(ch["gnosis"]["usd"] - 15.0) < 1e-9, ch.get("gnosis"))
    check("C8b 처음부터 시세 없던 코인 = 판정에서 뺌(unk 아님 · 스테이블 $7 만)", ch.get("scroll") == {"usd": 7.0}, ch.get("scroll"))
    check("C8c 오늘 실시간 스냅샷 값도 '요즘 시세' = eth unk · 값 있는 코인 $6 · 닫힌 LP·숨긴 NFT 제외", ch["eth"].get("unk") is True and abs(ch["eth"]["usd"] - 6.0) < 1e-9, ch.get("eth"))
    check("C8d 7일 창 밖(9일 전)에만 값 = 종전(뺌) · 수량 0 = 모름 아님", "base" not in ch and "optimism" not in ch, ch)
    check("C8e 기준 = 소액 기준(설정 $30 — 최대 $100)", info["lim"] == 30.0, info.get("lim"))
    web.BUILDER = FB(OUT, {"_v": 1})
    i2 = web._chain_auto_off_info()
    check("C8f 그날 고정가 기록 없음 = unk 없음(종전 판정)", not any(v.get("unk") for v in i2["chains"].values()), i2)
    web.BUILDER = None
    check("C8g 빌드 전 = None(자동 끄기 안 함)", web._chain_auto_off_info() is None)
    web.BUILDER = FB(OUT, DPX, live={"date": dkst(0), "p": {"13": 7.0}})
    CO.AUTO_INFO_FN = web._chain_auto_off_info
    off = CO.auto_off()
    check("C8h 끝까지: gnosis(시세 장애 unk) 안 끔 · scroll($7 ≤ $30) 끔 · megaeth(값 없음 = $0) 끔", sorted(off) == ["megaeth", "scroll"], off)
    web.BUILDER = None

T.finish()
