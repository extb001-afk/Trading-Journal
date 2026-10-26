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
json.dump({"wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 3, "chains": {}},
          open(os.path.join(T.TMP, "config.json"), "w"))
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
                (a, "token", "eth", addr, sym, d, 100 + a))
    DEC[a], GID[a] = d, 100 + a
    return a


def leg(kind, sid, ts, a, qty, lk, ev, cost=None, seq=0):
    ST["pid"] += 1
    con.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                " cost_krw, leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,5)",
                (ST["pid"], kind, "eth", sid, seq, ts, a, f"wallet:eth:{W}", str(int(round(qty * 10 ** DEC[a]))),
                 None if cost is None else repr(float(cost)), lk, ev))


def opening(a, qty):
    leg("opening", f"recon:eth:{a}", NOW - 30 * DAY, a, qty, "opening", "OPENING")


CA = {k: "0x" + v * 20 for k, v in (("nocg", "d1"), ("cg", "d2"), ("thin", "d3"), ("unk", "d4"), ("buy", "d5"), ("user", "d6"))}
a_nocg = asset(CA["nocg"], "AIRX")
opening(a_nocg, 1000)
a_cg = asset(CA["cg"], "REALT")
opening(a_cg, 100)
a_thin = asset(CA["thin"], "THINT")
opening(a_thin, 10)
a_unk = asset(CA["unk"], "UNKT")
opening(a_unk, 50)
a_buy = asset(CA["buy"], "BUYT")
ub = asset("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "USDC", 6)
opening(ub, 1000)
leg("chain_tx", h("swap"), NOW - 5 * DAY, ub, -100, "disp", "SWAP", 100)
leg("chain_tx", h("swap"), NOW - 5 * DAY, a_buy, 40, "acq", "SWAP", 100, seq=1)
con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('eth',?,'SWAP','{}',5)", (h("swap"),))
a_user = asset(CA["user"], "USERT")
opening(a_user, 7)
X = "0x" + "b7" * 20
a_sent = asset("0x" + "d7" * 20, "SENTT")
opening(a_sent, 100)
leg("chain_tx", h("sent"), NOW - 3 * DAY, a_sent, -20, "move_out", "TRANSFER_OUT")
a_spf = asset("0x" + "d8" * 20, "SPOFT")
opening(a_spf, 100)
leg("chain_tx", h("spoof"), NOW - 3 * DAY, a_spf, -5, "move_out", "TRANSFER_OUT")
a_syn = asset("0x" + "d9" * 20, "SYNTT")
opening(a_syn, 100)
leg("chain_tx", h("synth"), NOW - 3 * DAY, a_syn, -5, "move_out", "TRANSFER_OUT")
a_mt = asset("0x" + "da" * 20, "MTHIN")
opening(a_mt, 10)
leg("chain_tx", h("mt"), NOW - 3 * DAY, a_mt, -2, "move_out", "TRANSFER_OUT")
for hx9, frm9, fee9, ri9 in ((h("sent"), W, "100", "0xa9059cbb"), (h("spoof"), X, "100", "0xa9059cbb"), (h("synth"), W, "0", "0x01"),
                             (h("mt"), W, "100", "0xa9059cbb")):
    con.execute("INSERT INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('eth',?,1,'0x1',?,?,?,?)",
                (hx9, NOW - 3 * DAY, json.dumps({"tx": {"hash": hx9, "from": frm9, "fee": {"value": fee9}, "raw_input": ri9}}),
                 json.dumps([W]), NOW))
    con.execute("INSERT OR IGNORE INTO tx_class (chain, txhash, event, detail, classifier_ver) VALUES ('eth',?,'TRANSFER_OUT','{}',5)", (hx9,))
pos = {}
for a, loc, qb in con.execute("SELECT asset_id, location, qty_base FROM postings"):
    pos[(GID[a], loc)] = pos.get((GID[a], loc), 0) + int(qb) / 10 ** DEC[a]
for (g, loc), q in pos.items():
    con.execute("INSERT OR REPLACE INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?, '0', '0')",
                (g, loc, format(q, ".12f")))
con.commit()
con.close()
json.dump({"eth": {CA["user"]: "USERT"}}, open(os.path.join(paths.STATE_DIR, "genuine_tokens.json"), "w"))
json.dump({"v": 1, "e": {f"eth:{CA['nocg']}": [NOW - 60, None], f"eth:{CA['cg']}": [NOW - 60, 2.05], f"eth:{CA['thin']}": [NOW - 60, 3.0],
                         f"eth:{CA['buy']}": [NOW - 60, None], f"eth:{CA['user']}": [NOW - 60, None],
                         "eth:0x" + "d7" * 20: [NOW - 60, None], "eth:0x" + "d8" * 20: [NOW - 60, None],
                         "eth:0x" + "d9" * 20: [NOW - 60, None], "eth:0x" + "da" * 20: [NOW - 60, 3.0]}},
          open(os.path.join(paths.STATE_DIR, "cg_ca.json"), "w"))

import pricing  # noqa: E402
import cgca  # noqa: E402
import web  # noqa: E402

cgca.reset_for_tests()
pricing._gj = lambda url, *a, **k: (_ for _ in ()).throw(OSError("시험: 시세 받기 없음"))
web.Spot.dex_pending = lambda self, c, ca: False
web.Spot.ex_pending = lambda self, ex: False
b = web.StateBuilder()
web.BUILDER = b
now = time.time()
DEXSET = ((CA["nocg"], 1.0, 50_000.0), (CA["cg"], 2.0, 50_000.0), (CA["thin"], 3.1, 500.0), (CA["unk"], 4.0, 50_000.0),
          (CA["buy"], 2.5, 50_000.0), (CA["user"], 1.0, 50_000.0), ("0x" + "d7" * 20, 1.0, 50_000.0), ("0x" + "d8" * 20, 1.0, 50_000.0),
          ("0x" + "d9" * 20, 1.0, 50_000.0), ("0x" + "da" * 20, 3.1, 500.0))
for k9, px9, rv9 in DEXSET:
    kk = f"eth:{k9}"
    b.spot.dex_usd[kk], b.spot.dex_ts[kk], b.spot.dex_res[kk], b.spot.dex_res_ts[kk] = px9, now, rv9, now
st = T.safe(b.build)
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
coins = {int(str(c["key"])[1:]): c for c in (f.get("coins") or []) if str(c.get("key", "")).startswith("g")}
quar = set(getattr(b, "_risk_quarantined", None) or ())
reasons = getattr(b, "_risk_reasons", {}) or {}


def usd_of(a):
    c = coins.get(GID[a]) or {}
    return float(c.get("qty") or 0) * float(c.get("price") or 0)


check("C1 기초잔고뿐·유동성 충분·코인게코 없음 = 평가 제외(격리 · 보유 목록에 없음)", GID[a_nocg] in quar and GID[a_nocg] not in coins,
      (GID[a_nocg] in quar, coins.get(GID[a_nocg])))
check("C1 사유 = '창 이전 수령(기초잔고) · 코인게코 시세 없음'", "코인게코 시세 없음" in str(reasons.get(GID[a_nocg]) or ""), reasons.get(GID[a_nocg]))
pend = f.get("pendings") or []
check("C1 검토 줄(스팸·에어드랍 의심 표시)에 있음", any(str(p.get("key") or "") == f"risk:g{GID[a_nocg]}" for p in pend),
      [p.get("key") for p in pend][:20])
check("C2 기초잔고뿐·코인게코 있음 = DEX 시세로 평가($200)", abs(usd_of(a_cg) - 200) < 0.01 and GID[a_cg] not in quar, coins.get(GID[a_cg]))
check("C3 유동성 가드로 DEX 0 · 코인게코 있음 = 코인게코 값으로 평가($30)", abs(usd_of(a_thin) - 30) < 0.01 and GID[a_thin] not in quar,
      coins.get(GID[a_thin]))
check("C4 코인게코 모름 = 종전 규칙(DEX 유동성 충분 → $200)", abs(usd_of(a_unk) - 200) < 0.01 and GID[a_unk] not in quar, coins.get(GID[a_unk]))
check("C5 창 안에서 산 토큰 = 코인게코 없어도 평가($100)", abs(usd_of(a_buy) - 100) < 0.01 and GID[a_buy] not in quar, coins.get(GID[a_buy]))
check("C6 사용자 정품 등록 = 코인게코 없어도 평가($7)", abs(usd_of(a_user) - 7) < 0.01 and GID[a_user] not in quar, coins.get(GID[a_user]))
tot = sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in coins.values()) + \
    sum(float(s.get("qty") or 0) * float(s.get("price") or 0) for s in (f.get("stables") or []))
TOT = 200 + 30 + 200 + 100 + 7 + 80 + 24
check("C11 서명자 모름(합성 스냅샷) '보냄' = 내 거래 아님 → 관문 그대로(코인게코 없음 → 제외)", GID[a_syn] in quar and GID[a_syn] not in coins,
      (GID[a_syn] in quar, coins.get(GID[a_syn]), reasons.get(GID[a_syn])))
check("C12 내 서명 보냄 + 유동성 가드 0 + 코인게코 있음 = 남은 8개 × $3 = $24", abs(usd_of(a_mt) - 24) < 0.01 and GID[a_mt] not in quar,
      (coins.get(GID[a_mt]), reasons.get(GID[a_mt])))
check("C8 기초잔고 + 내가 서명해 보낸 토큰 = 관문 대상 아님(남은 80 · $80 평가)", abs(usd_of(a_sent) - 80) < 0.01 and GID[a_sent] not in quar,
      (coins.get(GID[a_sent]), reasons.get(GID[a_sent])))
check("C8 남이 서명한 가짜 '보냄'만 있는 토큰 = 관문 그대로(코인게코 없음 → 제외)", GID[a_spf] in quar and GID[a_spf] not in coins,
      (GID[a_spf] in quar, reasons.get(GID[a_spf])))
check("C1 총자산 = 기초잔고 코인게코 없음(AIRX $1,000) 제외", abs(tot - TOT) < 0.01, tot)
ds = [d for d in (f.get("dailySeries") or []) if isinstance(d, dict)]
check("C1 오늘 일별 값도 제외", bool(ds) and abs(float(ds[-1].get("val") or 0) - TOT) < 1, ds[-1:] if ds else None)
w9 = dict(cgca._ST["want"])
check("C7 확인 대상 = 기초잔고뿐인 CA(nocg·cg·thin·unk) · 산 토큰·사용자 정품 제외",
      {("eth", CA[k]) for k in ("nocg", "cg", "thin", "unk")} <= set(w9) and ("eth", CA["buy"]) not in w9 and ("eth", CA["user"]) not in w9, sorted(w9))
check("C7 값이 필요한 쌍 = 유동성 가드로 DEX 0 인 thin · MTHIN(C12)", cgca._ST["px_want"] == {("eth", CA["thin"]), ("eth", "0x" + "da" * 20)},
      cgca._ST["px_want"])

OFF_AT = NOW - 25 * 3600
d9 = json.load(open(os.path.join(paths.STATE_DIR, "cg_ca.json")))
d9["e"][f"eth:{CA['thin']}"] = [OFF_AT - 60, 3.0]
json.dump(d9, open(os.path.join(paths.STATE_DIR, "cg_ca.json"), "w"))
cgca.reset_for_tests()
b2 = web.StateBuilder()
web.BUILDER = b2
for k9, px9, rv9 in DEXSET:
    kk = f"eth:{k9}"
    b2.spot.dex_usd[kk], b2.spot.dex_ts[kk], b2.spot.dex_res[kk], b2.spot.dex_res_ts[kk] = px9, OFF_AT, rv9, OFF_AT
b2.spot.off_chains = {"eth"}
b2.spot.off_at = {"eth": float(OFF_AT)}
st2 = T.safe(b2.build)
f2 = (st2 or {}).get("fields") or {} if isinstance(st2, dict) else {}
coins2 = {int(str(c["key"])[1:]): c for c in (f2.get("coins") or []) if str(c.get("key", "")).startswith("g")}
c9t = coins2.get(GID[a_thin]) or {}
check("C9 끈 체인 코인게코 값 = 끈 시각 기준 유지($30 — 지금 기준 24시간 만료로 0 이 되지 않음)",
      abs(float(c9t.get("qty") or 0) * float(c9t.get("price") or 0) - 30) < 0.01, c9t)
check("C9 끈 체인 = 코인게코 확인 대상 아님(want·px_want 비어 있음)", not cgca._ST["want"] and not cgca._ST["px_want"], (cgca._ST["want"], cgca._ST["px_want"]))
import buildproc  # noqa: E402
cgca.want({}, set())
WANT10 = ({("eth", "0x" + "f1" * 20): 5.0}, {("eth", "0x" + "f1" * 20)})
orig9 = (buildproc.usable, buildproc.qsnap_of, buildproc.run, buildproc.apply)
buildproc.usable = lambda: True
buildproc.qsnap_of = lambda b9: {}
buildproc.run = lambda b9: ("ok", {"fields": {}}, {"st": {"_cgca_want": WANT10}})
buildproc.apply = lambda b9, pay, q9: b9.__dict__.update(pay["st"])
out10 = b2._build_child()
buildproc.usable, buildproc.qsnap_of, buildproc.run, buildproc.apply = orig9
check("C10 자식 빌드가 정한 확인 대상이 부모 cgca 에 등록", cgca._ST["want"] == WANT10[0] and cgca._ST["px_want"] == WANT10[1], cgca._ST["want"])

TOT13 = TOT
for age13, want13 in ((23 * 3600, 30.0), (25 * 3600, 0.0)):
    d13 = json.load(open(os.path.join(paths.STATE_DIR, "cg_ca.json")))
    d13["e"][f"eth:{CA['thin']}"] = [float(NOW - age13), 3.0]
    json.dump(d13, open(os.path.join(paths.STATE_DIR, "cg_ca.json"), "w"))
    cgca.reset_for_tests()
    b3 = web.StateBuilder()
    n13 = time.time()
    for k9, px9, rv9 in DEXSET:
        kk = f"eth:{k9}"
        b3.spot.dex_usd[kk], b3.spot.dex_ts[kk], b3.spot.dex_res[kk], b3.spot.dex_res_ts[kk] = px9, n13, rv9, n13
    st3 = T.safe(b3.build)
    f3 = (st3 or {}).get("fields") or {} if isinstance(st3, dict) else {}
    coins3 = {int(str(c["key"])[1:]): c for c in (f3.get("coins") or []) if str(c.get("key", "")).startswith("g")}
    c3 = coins3.get(GID[a_thin]) or {}
    u13 = float(c3.get("qty") or 0) * float(c3.get("price") or 0)
    tot3 = sum(float(c.get("qty") or 0) * float(c.get("price") or 0) for c in coins3.values()) + \
        sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in (f3.get("stables") or []))
    ds3 = [d for d in (f3.get("dailySeries") or []) if isinstance(d, dict)]
    h13 = age13 // 3600
    check(f"C13 코인게코 값 {h13}시간 전(갱신 밀림) = 보유 평가 ${want13:,.0f}", abs(u13 - want13) < 0.01, c3)
    if want13:
        check(f"C13 (세션20 A6-04) {h13}시간 전 값 = 출처 coingecko · 나이(pxAge) = 받은 지 {h13}시간", c3.get("pxSrc") == "coingecko"
              and abs(float(c3.get("pxAge") or 0) - age13) < 600, (c3.get("pxSrc"), c3.get("pxAge")))
    check(f"C13 {h13}시간 전 = 총자산·오늘 일별 값 {'포함' if want13 else '제외'}",
          abs(tot3 - (TOT13 - 30 + want13)) < 0.01 and bool(ds3) and abs(float(ds3[-1].get("val") or 0) - (TOT13 - 30 + want13)) < 1,
          (tot3, ds3[-1:] if ds3 else None))
    e13 = json.load(open(os.path.join(paths.STATE_DIR, "cg_ca.json")))["e"].get(f"eth:{CA['thin']}")
    check(f"C13 {h13}시간 전 = 받은 시각 그대로(빌드가 시각을 꾸미지 않음)", e13 == [float(NOW - age13), 3.0], e13)
d13 = json.load(open(os.path.join(paths.STATE_DIR, "cg_ca.json")))
d13["e"][f"eth:{CA['thin']}"] = [float(NOW - 60), 3.0]
json.dump(d13, open(os.path.join(paths.STATE_DIR, "cg_ca.json"), "w"))
cgca.reset_for_tests()

import candles  # noqa: E402
calls = []
RESP = {}


def fake_get(url, deadline=None, inline_wait=10.0, **k):
    calls.append(url)
    r = RESP.get(url.split("contract_addresses=")[1].split("&")[0])
    if isinstance(r, BaseException):
        raise r
    return r


candles._get = fake_get
candles._keyed = lambda url, lane, allow, valid, dl: ("skip", "nokey")
cgca.GAP = 0.0
cgca.reset_for_tests()
os.remove(os.path.join(paths.STATE_DIR, "cg_ca.json"))
A1, A2, A3, A4 = ("0x" + c * 20 for c in ("e1", "e2", "e3", "e4"))
RESP.update({A1: {A1: {"usd": 1.5}}, A2: {}, A3: {"status": {"error_code": 429, "error_message": "rate"}}})
cgca.want({("eth", A1): 10.0, ("eth", A2): 5.0, ("eth", A3): 1.0, ("eth", A4): 0.5, ("nochain", A1): 99.0})
check("U5 플랫폼 없는 체인 = 확인 대상 아님", ("nochain", A1) not in cgca._ST["want"], cgca._ST["want"])
n = cgca.tick(now=time.time())
check("U1 응답 해석: 있음 = True·값 · 없음({}) = False", cgca.status("eth", A1) is True and cgca.price("eth", A1) == 1.5 and cgca.status("eth", A2) is False,
      (cgca.status("eth", A1), cgca.price("eth", A1), cgca.status("eth", A2)))
check("U2 오류 응답(429 본문) = 모름 그대로 · 쉼 · 이번 tick 멈춤", cgca.status("eth", A3) is None and cgca._ST["backoff"] > time.time() and n == 2
      and len(calls) == 3, (n, calls, cgca._ST["backoff"]))
check("U2 쉼 동안 tick = 호출 0", cgca.tick() == 0 and len(calls) == 3, calls)
d9 = json.load(open(os.path.join(paths.STATE_DIR, "cg_ca.json")))
check("U3 캐시 파일 = 확인한 2개(있음·없음)", set(d9.get("e") or {}) == {f"eth:{A1}", f"eth:{A2}"}, d9)
cgca._ST["backoff"] = 0
RESP[A3] = {A3: {"usd": 2.0}}
calls.clear()
cgca.PER_TICK = 1
check("U4 tick 상한(PER_TICK) · 남은 것 = 평가 큰 것부터", cgca.tick() == 1 and calls and A3 in calls[0], calls)
cgca.PER_TICK = 3
cgca.reset_for_tests()
check("U3 재시작(새 프로세스) = 파일에서 판정 이어받음", cgca.status("eth", A1) is True and cgca.status("eth", A3) is True and cgca.status("eth", A4) is None)
check("U1 시세는 24시간 안 값만(낡으면 None)", cgca.price("eth", A1, now=time.time() + 7 * 3600) == 1.5
      and cgca.price("eth", A1, now=time.time() + 25 * 3600) is None)
import cgkey  # noqa: E402
cgkey.key = lambda: "synthetic-key"
lanes, calls = [], []
KMODE = {"m": "ok"}


def fake_keyed(url, lane, allow, valid, dl):
    lanes.append((lane, allow))
    if KMODE["m"] == "skip":
        return "skip", "day"
    ca9 = url.split("contract_addresses=")[1].split("&")[0]
    return "ok", {ca9: {"usd": 1.0}}


candles._keyed = fake_keyed
cgca.reset_for_tests()
os.remove(os.path.join(paths.STATE_DIR, "cg_ca.json"))
B1, B2 = "0x" + "b1" * 20, "0x" + "b2" * 20
cgca.want({("eth", B1): 3.0, ("eth", B2): 1.0}, {("eth", B1)})
cgca.tick()
check("U6 처음 확인 = 배경 칸('past')(평가 값 필요한 쌍도 처음은 유무 확인)", lanes[:2] == [("past", True), ("past", True)] and not calls, (lanes, calls))
lanes.clear()
cgca._ST["e"][cgca.key_of("eth", B1)][0] -= cgca.PX_EVERY + 1
cgca.tick()
check("U6 평가에 쓰는 값 갱신 = 'live' 칸", lanes == [("live", True)], lanes)
lanes.clear()
KMODE["m"] = "skip"
cgca._ST["e"][cgca.key_of("eth", B1)][0] -= cgca.PX_EVERY + 1
cgca.tick()
check("U6 키 몫 없음(skip) = 무키로 안 감 · 그 칸만 쉼", calls == [] and cgca._ST["kwait"]["live"] > time.time() and "키 몫" in str(cgca._ST["err"]),
      (calls, cgca._ST["err"]))
cgca._ST["kwait"] = {"past": 0.0, "live": 0.0}
KMODE["m"] = "ok"
cgca._ST["kd"] = [int(time.time() // 86400), cgca.KEY_DAY_MAX]
lanes.clear()
cgca.tick()
check("U6 하루 상한 = 키·무키 둘 다 안 부름 · 쉼", lanes == [] and calls == [] and cgca._ST["kwait"]["live"] > time.time(), (lanes, calls))
cgca.reset_for_tests()
cgca._ST["kd"] = [int(time.time() // 86400), 0]
B3 = "0x" + "b3" * 20
cgca.want({("eth", B3): 9.0, ("eth", B1): 1.0}, {("eth", B1)})
cgca._entries()[cgca.key_of("eth", B1)] = [time.time() - cgca.PX_EVERY - 5, 1.0]
LMODE = {}


def fake_keyed2(url, lane, allow, valid, dl):
    lanes.append((lane, allow))
    if lane == "past":
        return "skip", "share"
    if LMODE.get("err"):
        return "err", LMODE["err"]
    ca9 = url.split("contract_addresses=")[1].split("&")[0]
    return "ok", {ca9: {"usd": LMODE.get("usd", 2.0)}}


candles._keyed = fake_keyed2
lanes.clear()
cgca.tick()
check("U7 평가 값 갱신(live)이 먼저 · 배경 확인 몫 대기와 무관하게 갱신됨", lanes[:1] == [("live", True)] and cgca.price("eth", B1) == 2.0
      and cgca.status("eth", B3) is None and cgca._ST["kwait"]["past"] > time.time() and not cgca._ST["kwait"]["live"], (lanes, cgca._ST["kwait"]))
lanes.clear()
cgca._ST["e"][cgca.key_of("eth", B1)][0] -= cgca.PX_EVERY + 1
cgca.tick()
check("U7 배경 칸 대기 중에도 다음 바퀴 평가 값 갱신은 계속", lanes == [("live", True)], lanes)
cgca.reset_for_tests()
os.remove(os.path.join(paths.STATE_DIR, "cg_ca.json"))
cgca._entries()
cgca._ST["kd"] = [int(time.time() // 86400), 0]
t8 = float(int(time.time()))
P8 = {0: "0x" + "80" * 20, 5: "0x" + "85" * 20, 7: "0x" + "87" * 20, 23: "0x" + "83" * 20, 25: "0x" + "8f" * 20, 100: "0x" + "8a" * 20}
for h8, a8 in P8.items():
    cgca._entries()[cgca.key_of("eth", a8)] = [t8 - (0.5 if h8 == 0 else h8) * 3600, 1.25]
check("U8 평가 = 5h·7h·23h 있음 · 25h 없음", [cgca.price("eth", P8[h8], now=t8) for h8 in (5, 7, 23, 25)] == [1.25, 1.25, 1.25, None],
      [cgca.price("eth", P8[h8], now=t8) for h8 in (5, 7, 23, 25)])
cgca.want({("eth", a8): 1.0 for a8 in P8.values()}, {("eth", P8[h8]) for h8 in (0, 5, 7, 23, 25)})
due8 = cgca._due(t8)
check("U8 갱신 판단 그대로: 값 필요한 쌍 = PX_EVERY(1시간) 넘은 5h·7h·23h·25h 갱신 · 30분 = 아직 · 값 필요 없는 쌍(7h 아닌 100h 확인) = TTL_POS 전이라 아님",
      {("eth", P8[h8]) for h8 in (5, 7, 23, 25)} <= set(due8) and ("eth", P8[0]) not in due8 and ("eth", P8[100]) not in due8, due8)
check("U8 갱신 순서 = 오래된 값부터(25h 먼저)", due8[:1] == [("eth", P8[25])], due8)
cgca.want({("eth", P8[23]): 1.0}, {("eth", P8[23])})
LMODE["err"] = OSError("시험: 코인게코 429")
calls.clear()
cgca.tick(now=t8)
check("U8 갱신 실패 = 직전 값·받은 시각 그대로(23h 값 계속 평가) · 쉼", cgca._entries()[cgca.key_of("eth", P8[23])] == [t8 - 23 * 3600, 1.25]
      and cgca.price("eth", P8[23], now=t8) == 1.25 and cgca._ST["backoff"] > time.time(), (cgca._entries()[cgca.key_of("eth", P8[23])], cgca._ST["err"]))
cgca._ST["backoff"] = 0
LMODE.pop("err")
LMODE["usd"] = 4.0
cgca.tick(now=t8)
v8 = cgca._entries()[cgca.key_of("eth", P8[23])]
check("U8 새로 받으면 바로 교체(값·받은 시각)", v8[1] == 4.0 and v8[0] >= t8 - 1 and cgca.price("eth", P8[23]) == 4.0, v8)
T.finish()
