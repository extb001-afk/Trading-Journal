#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

W = "0x" + "ab" * 20
DAY = 86400
NOW = int(time.time())
shutil.copytree(os.path.join(T.ROOT, "seed"), os.path.join(T.TMP, "seed"), dirs_exist_ok=True)
CFG = {"wallets": [{"type": "evm", "chain": "bsc", "address": W, "label": "w"}], "backfill_months": 3, "chains": {},
       "bsc": {"detail_rpcs": ["https://rpc.invalid/a", "https://rpc.invalid/b"]}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import db as dbm  # noqa: E402


def check(name, ok, detail=""):
    T.chk(bool(ok), name, None if ok else str(detail)[:900])


def h(tag):
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


con = dbm.open_db(os.path.join(paths.STATE_DIR, "ledger.db"))
ST = {"aid": 0, "pid": 0}
DEC, GID = {}, {}


def asset(addr, sym, d=18):
    ST["aid"] += 1
    a = ST["aid"]
    con.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (?,?,18)", (100 + a, f"{sym}#{a}"))
    con.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (?,?,?,?,?,?,1,0,?)",
                (a, "token", "bsc", addr, sym, d, 100 + a))
    DEC[a], GID[a] = d, 100 + a
    return a


def leg(kind, sid, ts, a, qty, lk, ev, cost=None, seq=0):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, "bsc", sid, seq, ts, a, f"wallet:bsc:{W}", str(int(round(qty * 10 ** DEC[a]))),
                 None if cost is None else repr(float(cost)), lk, ev))


CA = {k: "0x" + v * 20 for k, v in (("good", "e1"), ("fake", "e2"), ("new", "e3"), ("stale", "e4"), ("old", "e5"))}
QTY = {"good": 10.0, "fake": 7.0, "new": 3.0, "stale": 2.0, "old": 4.0}
usd = asset("0x55d398326f99059ff775485246999027b3197955", "USDT")
leg("opening", "recon:bsc:usdt", NOW - 30 * DAY, usd, 10000, "opening", "OPENING")
AID = {}
for i9, k9 in enumerate(CA):
    AID[k9] = asset(CA[k9], f"stVal{k9.capitalize()}")
    leg("chain_tx", h(k9), NOW - 5 * DAY, usd, -QTY[k9] * 600, "disp", "SWAP", QTY[k9] * 600)
    leg("chain_tx", h(k9), NOW - 5 * DAY, AID[k9], QTY[k9], "acq", "SWAP", QTY[k9] * 600, seq=1)
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('bsc',?,'SWAP','{}',5)", (h(k9),))
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()

OP = {k: "0x" + v * 20 for k, v in (("good", "c1"), ("fake", "c2"), ("stale", "c4"), ("old", "c5"))}
RATE = {"good": 1.02, "stale": 1.05, "old": 1.01}
SC_FILE = os.path.join(paths.STATE_DIR, "stake_credit.json")


def write_sc(e):
    json.dump({"v": 1, "e": e}, open(SC_FILE, "w"))


BASE_E = {CA["good"]: {"ok": True, "at": NOW - 9000, "op": OP["good"], "r": RATE["good"], "rt": NOW - 1200},
          CA["fake"]: {"ok": False, "at": NOW - 9000, "why": "StakeHub 불일치"},
          CA["stale"]: {"ok": True, "at": NOW - 9 * DAY, "op": OP["stale"], "r": RATE["stale"], "rt": NOW - 30 * 3600},
          CA["old"]: {"ok": True, "at": NOW - 40 * DAY, "op": OP["old"], "r": RATE["old"], "rt": NOW - 31 * DAY}}
write_sc(BASE_E)

import lpchain  # noqa: E402
import stakecredit  # noqa: E402
import web  # noqa: E402

BNB = 600.0
RPCS = CFG["bsc"]["detail_rpcs"]


def build(bnb=BNB, bnb_age=30.0):
    b9 = web.StateBuilder()
    b9.spot.dex_pending = lambda c, ca: False
    b9.spot.ex_pending = lambda ex: False
    b9.spot.rate, b9.spot.rate_ts = 1400.0, time.time()
    b9._pxq.add = lambda items: None
    n9 = time.time()
    b9.spot.usd.pop("BNB", None)
    if bnb:
        b9.spot.usd["BNB"], b9.spot.usd_ts["BNB"] = bnb, int(n9 - bnb_age)
    st9 = T.safe(b9.build)
    f9 = (st9 or {}).get("fields") or {} if isinstance(st9, dict) else {}
    c9 = {int(str(c["key"])[1:]): c for c in (f9.get("coins") or []) if str(c.get("key", "")).startswith("g")}
    return b9, f9, c9, st9


b, f, coins, st = build()
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")


def webdiag():
    p9 = paths.state("web_diag.json")
    return json.load(open(p9, encoding="utf-8")) if os.path.exists(p9) else {}


def judge_unpriced(uph):
    import health
    obs = {"now": NOW, "pm2": {"tj-web": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "webdiag": {"ts": NOW, "unpriced_held": uph, "ex_dead_held": [], "proof_div": []}}
    return next((c for c in health.evaluate(obs, health.settings({"health": {"units": ["tj-web"]}})) if c["id"] == "price:unpriced"), {})


def row(c9, k9):
    return c9.get(GID[AID[k9]]) or {}


def val(c9, k9):
    r9 = row(c9, k9)
    return float(r9.get("qty") or 0) * float(r9.get("price") or 0)


unp = set(f.get("unpricedSyms") or [])
g = row(coins, "good")
check("S1 진짜 증서 = 10 × 교환비 1.02 × BNB $600 = $6,120", abs(val(coins, "good") - 6120) < 0.01, g)
check("S1 출처 derived:bnbstake · 나이 = BNB 시세 나이(신선 · 30초 근처)", g.get("pxSrc") == "derived:bnbstake"
      and g.get("pxAge") is not None and 0 <= float(g["pxAge"]) < 600, (g.get("pxSrc"), g.get("pxAge")))
check("S1 시세 없음 목록 밖(헬스 price:unpriced 재료)", "stValGood" not in unp, sorted(unp))
check("S1 원가·손익은 그대로(평단 = 산 값 $600)", abs(float(g.get("avg") or 0) - 600) < 0.01, g.get("avg"))
check("S2 가짜(StakeHub 불일치) = 시세 없음 그대로", val(coins, "fake") == 0 and "stValFake" in unp, (row(coins, "fake"), sorted(unp)))
check("S2 아직 확인 전 = 시세 없음 그대로", val(coins, "new") == 0 and "stValNew" in unp, row(coins, "new"))
sw = set(getattr(b, "_stake_want", None) or ())
check("S2 확인 대상(_stake_want) = 다른 시세가 없는 BSC 보유 컨트랙트 5개 그대로", sw == {CA[k] for k in CA}, sorted(sw))
s3 = row(coins, "stale")
check("S3 낡은 교환비(30시간) = 마지막 값으로 평가 2 × 1.05 × $600 = $1,260", abs(val(coins, "stale") - 1260) < 0.01, s3)
check("S3 낡은 교환비 = 나이(pxAge) 30시간 표식", abs(float(s3.get("pxAge") or 0) - 30 * 3600) < 600, s3.get("pxAge"))
check("S4 교환비 31일 묵음 = 평가 안 함(시세 없음)", val(coins, "old") == 0 and "stValOld" in unp, row(coins, "old"))
stb = sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in (f.get("stables") or []))
tot = sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in coins.values()) + stb
check("S1 총자산 = 스테이블 + 진짜 증서 둘($6,120 + $1,260)", abs(tot - (stb + 6120 + 1260)) < 0.01, (tot, stb))
ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
check("S1 오늘 일별 값에도 들어감", bool(ds) and abs(float(ds[-1].get("val") or 0) - tot) < 1, ds[-1:] if ds else None)

WD1 = webdiag()

_b5, f5, coins5, _st5 = build(bnb=None)
check("S5 BNB 시세 없음 = 평가 없음(시세 없음 그대로)", val(coins5, "good") == 0 and "stValGood" in set(f5.get("unpricedSyms") or []),
      row(coins5, "good"))

WD5 = webdiag()
uph1, uph5 = ({x.get("sym"): x for x in (w9.get("unpriced_held") or [])} for w9 in (WD1, WD5))
check("X1 평가된 진짜 증서 = 헬스 재료(unpriced_held)에 없음 · 가짜·확인 전은 그대로", "stValGood" not in uph1 and {"stValFake", "stValNew"} <= set(uph1),
      sorted(uph1))
check("X2 BNB 시세 없을 땐 같은 증서가 재료에 들어감(원가 = 10 × $600 = $6,000)", abs(float((uph5.get("stValGood") or {}).get("cost") or 0) - 6000) < 0.01,
      uph5.get("stValGood"))
x1, x5 = (judge_unpriced([x for x in (w9.get("unpriced_held") or []) if x.get("sym") == "stValGood"]) for w9 in (WD1, WD5))
check("X3 그 증서 한 건 기준 헬스 price:unpriced = 평가됨 → ok · 평가 못 함 → warn 1건(무게 = 원가 $6,000)",
      x1.get("level") == "ok" and x5.get("level") == "warn" and x5.get("title") == "시세 없는 실보유 1건" and list((x5.get("ack") or {}).values()) == [6000.0],
      ((x1.get("level"), x1.get("title")), (x5.get("level"), x5.get("title"), x5.get("ack"))))

CALLS = []
NODE = {}


def word(x):
    return "0x" + (x[2:] if isinstance(x, str) else hex(x)[2:]).rjust(64, "0")


def fake_post(url, body, **kw):
    to, data = body["params"][0]["to"].lower(), body["params"][0]["data"]
    CALLS.append((url, to, data[:10], data))
    key = (to, data[:10]) if data[:10] != stakecredit.SEL_CREDIT_OF else (to, data)
    r = NODE.get(key)
    if r is None:
        r = {"jsonrpc": "2.0", "id": 1, "result": "0x"}
    if isinstance(r, Exception):
        raise r
    return r


def ok(x):
    return {"jsonrpc": "2.0", "id": 1, "result": x}


def hub_q(op):
    return stakecredit.SEL_CREDIT_OF + op[2:].rjust(64, "0")


HUB = stakecredit.STAKE_HUB.lower()
CW = {k: "0x" + v * 20 for k, v in (("g", "a1"), ("m", "a2"), ("n", "a3"), ("r", "a4"), ("f", "a5"), ("x", "a6"))}
OPW = "0x" + "b1" * 20
NODE[(CW["g"], stakecredit.SEL_VALIDATOR)] = ok(word(OPW))
NODE[(HUB, hub_q(OPW))] = ok(word(CW["g"]))
NODE[(CW["g"], stakecredit.SEL_BNB_BY_SHARES)] = ok(word(1020700000000000000))
OPM = "0x" + "b2" * 20
NODE[(CW["m"], stakecredit.SEL_VALIDATOR)] = ok(word(OPM))
NODE[(HUB, hub_q(OPM))] = ok(word("0x" + "99" * 20))
NODE[(CW["m"], stakecredit.SEL_BNB_BY_SHARES)] = ok(word(10 ** 18))
NODE[(CW["r"], stakecredit.SEL_VALIDATOR)] = {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
os.remove(SC_FILE)
stakecredit.reset_for_tests()
T0 = float(NOW)
n1 = stakecredit.refresh(RPCS, {CW["g"], CW["m"], CW["n"], CW["r"]}, now=T0, post=fake_post)
e1 = stakecredit.load()
check("W1 진짜 = ok · operator · 교환비 1.0207 · 받은 시각", e1.get(CW["g"], {}).get("ok") is True and e1[CW["g"]].get("op") == OPW
      and abs(float(e1[CW["g"]].get("r") or 0) - 1.0207) < 1e-9 and e1[CW["g"]].get("rt") == int(T0), e1.get(CW["g"]))
check("W1 진짜 확인 = 호출 3(validator·StakeHub(operator)·교환비)", [c[2] for c in CALLS if c[1] == CW["g"]] == [stakecredit.SEL_VALIDATOR, stakecredit.SEL_BNB_BY_SHARES]
      and sum(1 for c in CALLS if c[1] == HUB and c[3] == hub_q(OPW)) == 1, CALLS)
check("W1 StakeHub 다른 주소 = 아님(교환비 안 부름)", e1.get(CW["m"], {}).get("ok") is False
      and not any(c[1] == CW["m"] and c[2] == stakecredit.SEL_BNB_BY_SHARES for c in CALLS), (e1.get(CW["m"]), CALLS))
check("W1 함수 없음('0x') = 아님 · 되돌림 = 아님", e1.get(CW["n"], {}).get("ok") is False and e1.get(CW["r"], {}).get("ok") is False,
      (e1.get(CW["n"]), e1.get(CW["r"])))
check("W1 바뀐 항목 수 = 진짜 2(판정·교환비) + 아님 3", n1 == 5, n1)
check("W1 아님 항목엔 교환비 없음 → 평가에 안 씀", stakecredit.rate_of(e1[CW["m"]], T0) is None and stakecredit.rate_of(e1[CW["g"]], T0) == (1.0207, T0),
      (stakecredit.rate_of(e1[CW["m"]], T0), stakecredit.rate_of(e1[CW["g"]], T0)))

CALLS.clear()
NODE[(CW["f"], stakecredit.SEL_VALIDATOR)] = OSError("시험: 연결 끊김")
n2 = stakecredit.refresh(RPCS, {CW["f"]}, now=T0, post=fake_post)
check("W2 전송 실패 = 저장 안 함('아님'으로 안 박음) · 노드 둘 다 시도", n2 == 0 and CW["f"] not in stakecredit.load()
      and len({c[0] for c in CALLS}) == 2, (n2, CALLS))
CALLS.clear()
stakecredit.refresh(RPCS, {CW["f"]}, now=T0 + 60, post=fake_post)
check("W2 FAIL_GAP 안 = 안 부름", not CALLS, CALLS)
NODE[(CW["f"], stakecredit.SEL_VALIDATOR)] = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "limit exceeded"}}
stakecredit.refresh(RPCS, {CW["f"]}, now=T0 + stakecredit.FAIL_GAP + 1, post=fake_post)
check("W2 FAIL_GAP 지나면 다시 · 한도 오류 응답도 실패(저장 안 함)", len(CALLS) == 2 and CW["f"] not in stakecredit.load(), CALLS)
NODE[(CW["x"], stakecredit.SEL_VALIDATOR)] = ok(word("0x" + "b3" * 20))
NODE[(HUB, hub_q("0x" + "b3" * 20))] = {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
stakecredit.refresh(RPCS, {CW["x"]}, now=T0, post=fake_post)
check("W2 StakeHub 되돌림·이상 = 노드 사정(아님으로 안 박음)", CW["x"] not in stakecredit.load(), stakecredit.load().get(CW["x"]))

CS = "0x" + "a8" * 20
NODE[(CS, stakecredit.SEL_VALIDATOR)] = ok("0x01")
stakecredit.refresh(RPCS, {CS}, now=T0, post=fake_post)
check("W2 validator() 짧은 비정상 답('0x01') = 노드 사정(아님으로 30일 안 박음)", CS not in stakecredit.load(), stakecredit.load().get(CS))
CE = "0x" + "a9" * 20
CALLS.clear()
NODE[(CE, stakecredit.SEL_VALIDATOR)] = NameError("시험: 노드 길 코드 실수")
r2e = T.safe(stakecredit.refresh, RPCS, {CE}, now=T0, post=fake_post)
strict2 = os.environ.get("TJ_TEST_STRICT") == "1"
check("W2 노드 길 코드 실수 꼴 예외 = 라이브 저장 안 함·계속 · 엄격 모드 = 다시 던짐(calcguard)",
      (isinstance(r2e, dict) and "_exc" in r2e) if strict2 else (r2e == 0 and CE not in stakecredit.load()), r2e)

def _bad_read(*_a, **_k):
    raise NameError("시험: 읽기 길 코드 실수")


r2l = T.safe(stakecredit.load, _bad_read)
check("W2 load() 코드 실수 꼴 예외 = 라이브 빈 표 · 엄격 모드 = 다시 던짐(calcguard)",
      (isinstance(r2l, dict) and "_exc" in r2l) if strict2 else r2l == {}, r2l)

CALLS.clear()
stakecredit.refresh(RPCS, {CW["g"], CW["m"]}, now=T0 + 600, post=fake_post)
check("W3 교환비 RATE_EVERY 안 · 아님 NEG_TTL 안 = 0콜", not CALLS, CALLS)
NODE[(CW["g"], stakecredit.SEL_BNB_BY_SHARES)] = ok(word(1021000000000000000))
stakecredit.refresh(RPCS, {CW["g"], CW["m"]}, now=T0 + stakecredit.RATE_EVERY, post=fake_post)
e3 = stakecredit.load()
check("W3 진짜 = 교환비만 1콜 · 새 값 1.021", [c[2] for c in CALLS] == [stakecredit.SEL_BNB_BY_SHARES]
      and abs(float(e3[CW["g"]]["r"]) - 1.021) < 1e-9 and e3[CW["g"]]["rt"] == int(T0 + stakecredit.RATE_EVERY), (CALLS, e3.get(CW["g"])))
CALLS.clear()
stakecredit.refresh(RPCS, {CW["m"]}, now=T0 + stakecredit.NEG_TTL + 1, post=fake_post)
check("W3 아님 = NEG_TTL 뒤 재확인(validator·StakeHub)", [c[2] for c in CALLS] == [stakecredit.SEL_VALIDATOR, stakecredit.SEL_CREDIT_OF],
      CALLS)
CQ = "0x" + "a7" * 20
OPQ = "0x" + "b7" * 20
NODE[(CQ, stakecredit.SEL_VALIDATOR)] = ok(word(OPQ))
NODE[(HUB, hub_q(OPQ))] = ok(word(CQ))
NODE[(CQ, stakecredit.SEL_BNB_BY_SHARES)] = OSError("시험: 교환비만 실패")
stakecredit.refresh(RPCS, {CQ}, now=T0, post=fake_post)
eq = stakecredit.load().get(CQ) or {}
check("W3 진짜 판정 뒤 교환비만 실패 = 판정은 남김(교환비 없음 → 아직 평가 안 함)", eq.get("ok") is True and "r" not in eq
      and stakecredit.rate_of(eq, T0) is None, eq)
NODE[(CQ, stakecredit.SEL_BNB_BY_SHARES)] = ok(word(1030000000000000000))
CALLS.clear()
stakecredit.refresh(RPCS, {CQ}, now=T0 + stakecredit.FAIL_GAP + 1, post=fake_post)
check("W3 다음엔 교환비만(1콜)", [c[2] for c in CALLS] == [stakecredit.SEL_BNB_BY_SHARES] and abs(float(stakecredit.load()[CQ]["r"]) - 1.03) < 1e-9,
      CALLS)

NODE[(CW["g"], stakecredit.SEL_BNB_BY_SHARES)] = ok(word(50 * 10 ** 18))
stakecredit.refresh(RPCS, {CW["g"]}, now=T0 + 3 * stakecredit.RATE_EVERY, post=fake_post)
check("W4 교환비 50(범위 밖) = 실패 · 마지막 값 1.021 유지", abs(float(stakecredit.load()[CW["g"]]["r"]) - 1.021) < 1e-9, stakecredit.load().get(CW["g"]))
many = {"0x" + format(i9, "040x") for i9 in range(1, 30)}
CALLS.clear()
stakecredit.refresh(RPCS, many, now=T0, post=fake_post)
check("W4 한 주기 상한 PER_ROUND(함수 없음 판정 1콜씩)", len(CALLS) == stakecredit.PER_ROUND, len(CALLS))
CALLS.clear()
stakecredit.refresh([], {"0x" + "a8" * 20}, now=T0, post=fake_post)
check("W4 노드 설정 없음 = 0콜", not CALLS, CALLS)

os.remove(SC_FILE)
stakecredit.reset_for_tests()
NODE[(CA["good"], stakecredit.SEL_VALIDATOR)] = ok(word(OP["good"]))
NODE[(HUB, hub_q(OP["good"]))] = ok(word(CA["good"]))
NODE[(CA["good"], stakecredit.SEL_BNB_BY_SHARES)] = ok(word(1020000000000000000))
CALLS.clear()
b.spot.off_chains = {"bsc"}
n5o = stakecredit.worker_round(b, lpchain.rpc_urls, post=fake_post)
check("W5 BSC 끈 설치 = 안 부름", n5o == 0 and not CALLS, CALLS)
sw5 = b.__dict__.pop("_stake_want")
n5e = stakecredit.worker_round(b, lpchain.rpc_urls, post=fake_post)
check("W5 빌드 전(대상 칸 없음) = 0콜", n5e == 0 and not CALLS, CALLS)
b._stake_want = sw5
b.spot.off_chains = set()
n5 = stakecredit.worker_round(b, lpchain.rpc_urls, post=fake_post)
e5 = stakecredit.load()
check("W5 노드 = LP 평가와 같은 설정 노드(bsc.detail_rpcs)", {c[0] for c in CALLS} <= set(RPCS) and CALLS, CALLS[:3])
check("W5 worker_round = 빌드가 적은 대상 확인 → 파일(진짜 good · 나머지 아님)", n5 > 0 and e5.get(CA["good"], {}).get("ok") is True
      and all(e5.get(CA[k], {}).get("ok") is False for k in ("fake", "new", "stale", "old")), (n5, e5))
_b6, _f6, coins6, _st6 = build()
check("W5 다음 빌드 = 일꾼이 받은 교환비로 평가($6,120)", abs(val(coins6, "good") - 6120) < 0.01, row(coins6, "good"))


class _BadWant:

    def __iter__(self):
        raise NameError("시험: 대상 칸 꼴 이상")


b._stake_want = _BadWant()
r5 = T.safe(stakecredit.worker_round, b, lpchain.rpc_urls, post=fake_post)
strict = os.environ.get("TJ_TEST_STRICT") == "1"
check("W5 일꾼 예외 = 삼키고 0(라이브 · LP 일꾼 계속) · 엄격 모드 = 코드 실수 꼴은 던짐", (isinstance(r5, dict) and "_exc" in r5) if strict else r5 == 0, r5)

import buildproc  # noqa: E402
check("W6 _stake_want = 부모로 넘어가는 칸(PARENT_ONLY·CHILD_ONLY 아님)", "_stake_want" not in buildproc.PARENT_ONLY and "_stake_want" not in buildproc.CHILD_ONLY)
b.__dict__.pop("_stake_want", None)
buildproc.apply(b, {"st": {"_stake_want": {CA["new"]}}}, {})
check("W6 apply = 자식 값이 부모 빌더에", b.__dict__.get("_stake_want") == {CA["new"]}, b.__dict__.get("_stake_want"))
T.finish()
