#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import W, Reader

import json
import os
import time
import types
from datetime import datetime, timedelta, timezone

json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                              "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}],
           "native_symbol": {"eth": "ETH"}, "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import acct_norm
import common
import core
import db as dbm
import histcurve
import netpace
import web

chk = T.chk
core.dm = lambda *a, **k: None
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
E18 = 10 ** 18
DAY = 86400
NOW = int(time.time())
X = "0x" + "b7" * 20
TKN = "0x" + "e1" * 20
TKS = "0x" + "e2" * 20
KST = timezone(timedelta(hours=9))
T0 = NOW - 20 * DAY
TA = NOW - 6 * DAY
TB = NOW - 3 * DAY


def h(n):
    return "0x" + ("%064x" % n)


def snap(hx, ts, blk, frm, to, value=0, toks=(), fee=0, data="0xa9059cbb"):
    return {"tx": {"hash": hx, "from": frm, "to": to, "value": str(value), "fee": {"value": str(fee)}, "status": "ok", "raw_input": data,
                   "timestamp": ts, "block_number": blk, "block_hash": "0x" + "d" * 64},
            "token_transfers": [{"from": f, "to": t, "token": {"address": ca, "symbol": sym, "decimals": 18, "type": "ERC-20"},
                                 "total": {"value": str(v)}} for f, t, ca, sym, v in toks], "internal": []}


def feed(c, hx, s):
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hx, "wallets": [W], "snapshot": s, "ts": 1}]), 0, 0)


open(os.path.join(common.STATE_DIR, "backfill_done"), "w").write("1")
os.environ["TJ_NEGABS"] = "0"
c = core.Core(common.load_config())
feed(c, h(1), snap(h(1), T0, 1500, X, W, value=2 * E18, data="0x"))
feed(c, h(2), snap(h(2), TA, 2000, W, TKN, toks=[(W, X, TKN, "TKN", 600 * E18)], fee=10 ** 15))
feed(c, h(3), snap(h(3), TB, 2500, W, TKS, toks=[(W, X, TKS, "TKS", 300 * E18)], fee=10 ** 15))
c.conn.commit()
ISO = acct_norm.iso_day


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    s9 = str(spec).lower()
    if "e2e2" in s9:
        return 3.0 + 0.1 * (int(iso[-2:]) % 3), "ok"
    if "e1e1" in s9 or str(spec).upper().endswith("TKN"):
        return (2.0 if iso >= ISO(TA) else 1.0 + 0.01 * (int(iso[-2:]) % 4)), "ok"
    if "ETH" in str(spec).upper():
        return 2000.0, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
k9, k9s = f"eth:{TKN}", f"eth:{TKS}"
json.dump({"usd": {"ETH": 2000.0}, "usd_ts": {"ETH": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {k9: 2.0, k9s: 3.0}, "dex_ts": {k9: NOW, k9s: NOW},
           "dex_res": {k9: 1e6, k9s: 1e6}, "dex_res_ts": {k9: NOW, k9s: NOW}, "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(web.SPOT_PATH, "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing._gj = lambda url, timeout=10.0: None
import discopen
aid = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKN,)).fetchone()[0]
discopen.write_anchor(c, "eth", W, aid, TKN, 1000 * E18, 1999, TA - 12, TA - 1, 1000 * E18, "neg_tx", {"_tx": h(2)})
aids = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TKS,)).fetchone()[0]
discopen.write_anchor(c, "eth", W, aids, TKS, 500 * E18, 2499, TB - 12, TB - 1, 500 * E18, "neg_tx", {"_tx": h(3)})
c.conn.commit()


def build():
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    global BB
    b = BB = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


print("[1] 전체 빌드 — 줄 상세 합 = 분해 값")
build()
fb = build()
ser = fb.get("dailySeries") or []
det = getattr(BB, "_att_det", None)
chk(isinstance(det, dict) and len(det) > 0, "빌드가 줄 상세(_att_det)를 남김 — 분해 있는 날마다", type(det).__name__)
today = datetime.now(KST)
iso_of = {(today - timedelta(days=i)).strftime("%m-%d"): (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)}
n_att = n_det = 0
bad = []
coins_seen, fl_days = set(), 0
for r in ser:
    a = r.get("att")
    if not isinstance(a, dict):
        continue
    n_att += 1
    iso = iso_of.get(r.get("date"))
    d = (det or {}).get(iso)
    if not isinstance(d, dict):
        bad.append((iso, "상세 없음"))
        continue
    n_det += 1
    mk = d.get("mk") or []
    tol = lambda n: 0.006 * (n + 1) + 1e-9
    s_mk = sum(x[1] for x in mk)
    if abs(s_mk - (float(a["mk"]) - float(a.get("kx") or 0))) > tol(len(mk)):
        bad.append((iso, "mk", s_mk, a["mk"], a.get("kx")))
    if d.get("mkN") != len(mk) or any(abs(x[1]) < 0.005 for x in mk) or [abs(x[1]) for x in mk] != sorted((abs(x[1]) for x in mk), reverse=True):
        bad.append((iso, "mk 정렬·개수", d.get("mkN"), len(mk)))
    top_syms = [t[0] for t in a.get("top") or []]
    if [x[0] for x in mk[:len(top_syms)]] != top_syms:
        bad.append((iso, "mk 앞 = 상위 5", top_syms, [x[0] for x in mk[:5]]))
    for x in mk:
        coins_seen.add(x[0])
        if len(x) >= 6 and abs(x[3] * (x[5] - x[4]) - x[1]) > max(0.02, 1e-6 * abs(x[1])):
            bad.append((iso, "수량 × 가격 차 ≠ 기여", x))
    kx = d.get("kx") or []
    if len(kx) != 3 or abs(sum(kx) - float(a.get("kx") or 0)) > 0.02:
        bad.append((iso, "kx", kx, a.get("kx")))
    for key, want in (("un", a.get("un")), ("op", a.get("op")), ("fb", a.get("fb")), ("unp", (a.get("unp") or [0, 0])[1])):
        lst = d.get(key) or []
        if abs(sum(x[1] for x in lst) - float(want or 0)) > tol(len(lst)):
            bad.append((iso, key, lst, want))
    if "fl" in d:
        fl = d["fl"]
        fl_days += 1 if fl else 0
        s_fl = sum(x[1] for x in fl) + float(d.get("rbNew") or 0) + float(d.get("pv") or 0)
        if abs(s_fl - float(r.get("flow") or 0)) > tol(len(fl) + 2):
            bad.append((iso, "fl", fl, r.get("flow")))
        if any(not isinstance(x[2], list) for x in fl):
            bad.append((iso, "fl 레그 모양", fl))
    elif abs(float(r.get("flow") or 0)) >= 0.005:
        bad.append((iso, "flow 있는데 fl 없음", r.get("flow")))
chk(n_att >= 5 and n_det == n_att and not bad, "분해 있는 날 %d일 전부: 시세 코인별·환율 몫·원가 미확인·기초 잔고·선물 반영·가격 한쪽 없음·입출금 합 = 그날 분해 값" % n_att, bad[:6])
chk("TKN" in coins_seen, "시세 코인별에 보유 코인(TKN)이 든다", sorted(coins_seen))
chk(fl_days >= 2, "입출금 있는 날(TKN·TKS 보냄)의 이동 건 상세", fl_days)
dTA = (det or {}).get(datetime.fromtimestamp(TA, KST).strftime("%Y-%m-%d")) or {}
rTA = next((r for r in ser if iso_of.get(r.get("date")) == datetime.fromtimestamp(TA, KST).strftime("%Y-%m-%d")), {})
fl9 = dTA.get("fl") or []
chk(len(fl9) == 1 and "TKN" in fl9[0][0] and abs(fl9[0][1] + 1200) < 0.5 and fl9[0][0] in [t[0] for t in rTA.get("flowTop") or []],
    "발견 날 입출금 = TKN 600 보냄 −$1,200 한 건(설명 = 그날 flowTop 과 같은 말)", (fl9, rTA.get("flowTop")))
mkA = dTA.get("mk") or []
chk(mkA and mkA[0][0] == "TKN" and abs(mkA[0][1] - 1000) < 0.5 and len(mkA[0]) == 6 and abs(mkA[0][3] - 1000) < 1e-6 and (mkA[0][4], mkA[0][5]) == (1.0 + 0.01 * (int(datetime.fromtimestamp(TA - DAY, KST).strftime("%d")) % 4), 2.0),
    "발견 날 시세 = TKN 1,000개 × ($1 → $2) = +$1,000(수량·전일가·그날가)", mkA)
att0 = {r.get("date"): json.dumps(r.get("att"), sort_keys=True) for r in ser if r.get("att")}
BB0 = BB
fb2 = build()
att1 = {r.get("date"): json.dumps(r.get("att"), sort_keys=True) for r in fb2.get("dailySeries") or [] if r.get("att")}
chk(att0 == att1 and getattr(BB, "_att_det", None) is not getattr(BB0, "_att_det", None), "다시 빌드 = 같은 분해 값(상세는 표시 전용 · 빌드마다 새 dict)", len(att0))

print("[2] att_detail — 창 안 날만 · 선물 정산 거래소·종목별")
lo = (today - timedelta(days=40)).strftime("%Y-%m-%d")
hi = today.strftime("%Y-%m-%d")
body = BB.att_detail(lo, hi)
chk(isinstance(body, dict) and body.get("ok") and set(body["days"]) == set(BB._att_det), "기간 안 분해 있는 날 전부(창 밖 날은 없음)", (sorted(body.get("days") or {})[:3], len(BB._att_det)))
one = BB.att_detail(hi, hi)
chk(set(one["days"]) <= {hi}, "하루 요청 = 그날만", sorted(one["days"]))
lt = BB.att_detail(lo, hi, lite=True)
chk(all(len(x) == 3 for v in lt["days"].values() for x in v["mk"]) and any(len(x) == 6 for v in body["days"].values() for x in v["mk"])
    and all(len(x) == 6 for v in BB._att_det.values() for x in v["mk"] if len(x) > 3) and any(len(x) == 6 for v in BB._att_det.values() for x in v["mk"]),
    "lite(그 달) = 시세 코인 줄 [심볼, USD, %] 만 · 빌드 재료는 그대로(수량·가격 유지)", [v["mk"][:1] for v in lt["days"].values()][:2])
sb = web.StateBuilder.__new__(web.StateBuilder)
d1, d2 = "2026-10-08", "2026-10-09"
sb._att_det = {d1: {"mk": [], "mkN": 0}, d2: {"mk": [], "mkN": 0}}
ev = [(d1, 1, 50.25, 70000.0, {"ex": "binance", "symbol": "ETHUSDT", "kind": "REALIZED"}),
      (d1, 2, -1.10, -1540.0, {"ex": "binance", "symbol": "ETHUSDT", "kind": "FEE"}),
      (d1, 3, -0.40, -560.0, {"ex": "binance", "symbol": "ETHUSDT", "kind": "FUNDING"}),
      (d1, 4, -12.0, -16800.0, {"ex": "bybit", "symbol": "SOLUSDT", "kind": "REALIZED"}),
      (d1, 5, 7.5, 10500.0, {"ex": "binance", "symbol": "BTCUSDT", "kind": "REALIZED"}),
      (d2, 6, 3.0, 4200.0, {"ex": "okx", "symbol": "BTC-USDT-SWAP", "kind": "REALIZED"}),
      ("2026-10-01", 7, 99.0, 1.0, {"ex": "okx", "symbol": "X", "kind": "REALIZED"})]
sb._day_idx = {"builtAt": 123, "futEv": ev}
sb._day_idx["attFut"] = sb._att_fut_pack(ev, sb._att_det)


class _NoIter(list):
    def __iter__(self):
        raise AssertionError("요청 때 futEv 순회")


sb._day_idx["futEv"] = _NoIter(ev)
r9 = sb.att_detail(d1, d2)
f1 = r9["days"][d1].get("fut") or []
rbd1 = sum(e[2] for e in ev if e[0] == d1)
chk([x[2] for x in f1] == ["ETHUSDT", "SOLUSDT", "BTCUSDT"] and abs(sum(x[3] for x in f1) - rbd1) < 0.011
    and f1[0][:2] == ["binance", "바이낸스"] and f1[0][5] == 1 and abs(f1[0][6] + 1.5) < 1e-9 and abs(f1[0][3] - 48.75) < 1e-9,
    "선물 = 거래소·종목별(|USD| 큰 순 · 정산 건수 · 수수료·펀딩) · 합 = 그날 선물 실현", f1)
chk(abs(sum(x[4] for x in f1) - sum(e[3] for e in ev if e[0] == d1)) <= 2 and r9["days"][d2]["fut"][0][1] == "OKX" and "2026-10-01" not in r9["days"],
    "원화 = 정산 시각 원화 합 · 분해 없는 날(창 밖)의 선물은 안 실음", r9["days"][d2].get("fut"))
chk(r9["days"][d1] is not sb._att_det[d1] and "fut" not in sb._att_det[d1], "응답은 사본(빌드 재료에 선물 칸을 덧붙이지 않음)", sb._att_det[d1])
sb2 = web.StateBuilder.__new__(web.StateBuilder)
chk(sb2.att_detail(d1, d2) is None, "빌드 색인 전 = None(호출부 503)")
chk(isinstance(BB._day_idx.get("attFut"), dict), "실제 빌드 = 색인에 선물 분해 상세(attFut — 요청 때 정산 이력 순회 없음)", list(BB._day_idx)[:30])
G9 = {i: {"sym": "S%d" % i} for i in range(1000)}
by9 = {"S%d" % i: (i + 1) * 0.37 * (-1) ** i for i in range(450)}
det9 = {k: [(str(i), 100.0, 1.0, 1.0 + 0.001 * (i + 1))] for i, k in enumerate(by9)}
sb3 = web.StateBuilder.__new__(web.StateBuilder)
sb3._flow_det = {d1: [["이동 %d" % i, round(0.11 * (i + 1), 2), []] for i in range(260)]}
rd9 = {"flow": round(sum(round(0.11 * (i + 1), 2) for i in range(260)), 2)}
unv9 = {i: (1.0, 2.0 + i) for i in range(150)}
pk = sb3._att_det_pack(rd9, by9, {k: 100.0 for k in by9}, det9, [("U%d" % i, -1.0 - i, "cut") for i in range(130)], (0.0, 0.0, 0.0), {}, {},
                       unv9, {}, {}, {i: 1.0 for i in range(1000)}, G9, frozenset(), d1)
mo9 = pk.get("more") or {}
cap_ok = (len(pk["mk"]) == 400 and mo9.get("mk", [0])[0] == 50 and abs(sum(x[1] for x in pk["mk"]) + mo9["mk"][1] - sum(round(v, 2) for v in by9.values())) < 0.02
          and len(pk["un"]) == 100 and mo9.get("un", [0])[0] == 50 and abs(sum(x[1] for x in pk["un"]) + mo9["un"][1] - sum(1.0 + i for i in range(150))) < 0.02
          and len(pk["unp"]) == 100 and mo9.get("unp", [0])[0] == 30
          and len(pk.get("fl") or []) == 200 and mo9.get("fl", [0])[0] == 60 and abs(sum(x[1] for x in pk["fl"]) + mo9["fl"][1] - rd9["flow"]) < 0.02)
chk(cap_ok, "목록 상한: 시세 400 · 원가 미확인·가격 한쪽 없음 100 · 입출금 200 — 넘는 몫 = more[키] [개수, USD 합] · 합 보존",
    {k: (len(pk.get(k) or []), mo9.get(k)) for k in ("mk", "un", "unp", "fl")})
evb = [(d1, i, 0.5 + i, (0.5 + i) * 1400, {"ex": "binance", "symbol": "C%dUSDT" % i, "kind": "REALIZED"}) for i in range(130)]
fp = sb._att_fut_pack(evb, {d1: {}})
chk(len(fp[d1]["rows"]) == 100 and fp[d1]["more"][0] == 30 and abs(sum(x[3] for x in fp[d1]["rows"]) + fp[d1]["more"][1] - sum(e[2] for e in evb)) < 0.02
    and len(fp[d1]["more"]) == 3 and abs(sum(x[4] for x in fp[d1]["rows"]) + fp[d1]["more"][2] - sum(e[3] for e in evb)) <= 101,
    "선물 종목 상한 100 · 넘는 몫 = more [개수, USD 합, 원화 합(정산 시각)]", (len(fp[d1]["rows"]), fp[d1].get("more")))

print("[3] GET /api/att_detail")


class FakeH:
    _DAY_RE = web.Handler._DAY_RE

    def __init__(self):
        self.out = None

    def _send(self, code, body, *a, **k):
        self.out = (code, body)


def call(q, builder):
    old = web.BUILDER
    web.BUILDER = builder
    try:
        hh = FakeH()
        web.Handler._send_att_detail(hh, q)
        return hh.out
    finally:
        web.BUILDER = old


class _B:
    def __init__(self, inner):
        self.i = inner
        self.kicked = 0

    def snapshot(self):
        return None

    def kick_refresh(self):
        self.kicked += 1

    def att_detail(self, a, b, lite=False):
        return self.i.att_detail(a, b, lite=lite)


bw = _B(sb)
for q, want in (("from=2026-10-08&to=2026-10-09", 200), ("date=2026-10-08", 200), ("from=2026-10-09&to=2026-10-08", 400), ("from=2026-1-08&to=2026-10-09", 400),
                ("from=2026-02-30&to=2026-03-01", 400), ("from=2026-08-01&to=2026-10-09", 400), ("", 400), ("from=2026-09-01&to=2026-10-11", 200)):
    o9 = call(q, bw)
    chk(o9 and o9[0] == want, "검사 %r → %d" % (q, want), o9 and (o9[0], str(o9[1])[:120]))
o9 = call("date=2026-10-08", bw)
o9 = (o9[0], json.loads(o9[1].decode()) if isinstance(o9[1], bytes) else o9[1])
chk(o9[1]["days"].get(d1, {}).get("fut"), "200 본문 = att_detail 그대로(그날 선물 칸 포함)", o9)
sb._att_det[d1]["mk"] = [["AAA", 1.0, 2.0, 3.0, 4.0, 5.0]]
o9 = call("from=2026-10-08&to=2026-10-09&lite=1", bw)
o9 = (o9[0], json.loads(o9[1].decode()) if isinstance(o9[1], bytes) else o9[1])
chk(o9[1]["days"][d1]["mk"] == [["AAA", 1.0, 2.0]] and sb._att_det[d1]["mk"] == [["AAA", 1.0, 2.0, 3.0, 4.0, 5.0]], "lite=1 → 가벼운 코인 줄 · 빌드 재료 무변", o9[1]["days"][d1]["mk"])
bn = _B(sb2)
o9 = call("date=2026-10-08", bn)
chk(o9[0] == 503 and bn.kicked == 1, "빌드 전 = 503 + 다시 빌드 깨우기", o9)


class _Big(_B):
    def att_detail(self, a, b, lite=False):
        return {"ok": True, "days": {"2026-10-08": {"mk": [["X" * 40, 1.0, 1.0]] * 200000}}}


o9 = call("date=2026-10-08", _Big(sb))
chk(o9[0] == 413 and not o9[1].get("ok"), "본문 상한 넘으면 413(화면 = 큰 항목 · 다시 시도)", o9 and o9[0])


class _BigKo(_B):
    def att_detail(self, a, b, lite=False):
        return {"ok": True, "days": {"2026-10-08": {"mk": [["가" * 40, 1.0, 1.0]] * 50000}}}


bk9 = _BigKo(sb).att_detail("", "")
nch9, nby9 = len(json.dumps(bk9, ensure_ascii=False)), len(json.dumps(bk9, ensure_ascii=False).encode())
o9 = call("date=2026-10-08", _BigKo(sb))
chk(nch9 < 6_000_000 < nby9 and o9[0] == 413, "한글 심볼: 글자 %d < 6MB < 바이트 %d → 413(바이트로 검사)" % (nch9, nby9), o9 and o9[0])
o9 = call("date=2026-10-08", bw)
chk(o9[0] == 200 and isinstance(o9[1], bytes) and json.loads(o9[1].decode())["days"].get(d1), "200 = 검사한 UTF-8 바이트 그대로 전송(다시 직렬화 없음)", type(o9[1]).__name__)
import onboarding
import demo_data
db9 = onboarding.DemoBuilder(web)
dd = demo_data.build()["fields"]["dailySeries"]
t9 = datetime.now(KST)
iso9 = {(t9 - timedelta(days=len(dd) - 1 - i)).strftime("%Y-%m-%d"): r for i, r in enumerate(dd)}
o9 = call("from=%s&to=%s" % ((t9 - timedelta(days=29)).strftime("%Y-%m-%d"), t9.strftime("%Y-%m-%d")), db9)
dz = (json.loads(o9[1].decode()) if o9 and isinstance(o9[1], bytes) else (o9 or (0, {}))[1]).get("days") or {}
bad9 = [k for k, v in dz.items() if abs(sum(x[1] for x in v["mk"]) - float(iso9[k]["att"]["mk"])) > 0.006 * (len(v["mk"]) + 1)
        or abs(sum(x[1] for x in v["fl"]) - float(iso9[k].get("flow") or 0)) > 0.011]
chk(o9 and o9[0] == 200 and len(dz) == sum(1 for r in dd if r.get("att")) and not bad9 and any(len(v["mk"]) > 5 for v in dz.values()),
    "데모 빌더: 분해 있는 날 전부 · 코인별 시세 합 = 그날 mk(상위 5 밖 코인 포함) · 원화 출금 = 그날 flow", (o9 and o9[0], len(dz), bad9[:3]))

print("[4] ui17 — 상세·builtAt 원자 게시 · 9999-12-31 · 원화만 남는 선물 행")
BX = web.StateBuilder()
BX.skip_gen_check = True


def bx_build():
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    try:
        return BX._build(conn)["fields"]
    finally:
        conn.close()


bx_build()
BX._day_idx = dict(BX._day_idx, builtAt=111)
old_days = json.dumps((BX.att_detail(lo, hi) or {}).get("days"), sort_keys=True)
mid = []
pack0 = web.StateBuilder._att_det_pack


def spy(self, *a, **k):
    if not mid:
        mid.append(self.att_detail(lo, hi))
    return pack0(self, *a, **k)


BX._att_det_pack = types.MethodType(spy, BX)
try:
    bx_build()
finally:
    del BX._att_det_pack
m0 = mid[0] if mid else None
chk(isinstance(m0, dict) and m0.get("builtAt") == 111 and json.dumps(m0.get("days"), sort_keys=True) == old_days and len(json.loads(old_days)) >= 5,
    "빌드 도중 요청 = 지난 빌드 builtAt + 그 빌드 상세 전부(종전 = 지난 builtAt + 빈·일부 상세 200)",
    m0 and (m0.get("builtAt"), len(m0.get("days") or {}), len(json.loads(old_days))))
af = BX.att_detail(lo, hi)
chk(af["builtAt"] != 111 and af["builtAt"] == BX._day_idx["builtAt"] and set(af["days"]) == set(BX._day_idx.get("attDet") or {}) and af["days"]
    and BX._day_idx.get("attDet") is BX._att_det and isinstance(BX._day_idx.get("attFut"), dict),
    "빌드 끝 = 새 builtAt · 새 상세 · 선물 분해가 한 색인 객체로 함께 게시", (af["builtAt"], len(af["days"]), sorted(BX._day_idx)[:6]))
attr0 = web.StateBuilder._daily_attrib


def attr_fail(self, *a, **k):
    attr0(self, *a, **k)
    raise RuntimeError("합성: 분해 끝에서 실패")


BX._daily_attrib = types.MethodType(attr_fail, BX)
try:
    fz9 = bx_build()
finally:
    del BX._daily_attrib
chk(BX._day_idx.get("attDet") == {} and BX.att_detail(lo, hi)["days"] == {} and not any(r.get("att") for r in fz9.get("dailySeries") or []),
    "분해가 실패한 빌드 = 빈 상세 게시(곡선 att 없음과 같게 — 실패한 계산의 상세를 내지 않음)", len(BX.att_detail(lo, hi)["days"]))
bx_build()
o9 = call("date=9999-12-31", _B(BX))
chk(o9 and o9[0] == 400, "date=9999-12-31 → 400(500 아님)", o9 and (o9[0], str(o9[1])[:100]))
try:
    r9 = BX.att_detail("9999-12-30", "9999-12-31")
    ok9 = isinstance(r9, dict) and r9.get("days") == {}
except OverflowError as e9:
    ok9, r9 = False, repr(e9)
chk(ok9, "att_detail 직접 9999-12-30~31 = 넘침 없이 빈 날(끝 날 다음 날을 더하지 않음)", r9)
evz = [(d1, 1, 10000.0, 14_000_000.0, {"ex": "binance", "symbol": "ETHUSDT", "kind": "REALIZED"}),
       (d1, 2, -10000.0, -13_900_000.0, {"ex": "binance", "symbol": "ETHUSDT", "kind": "REALIZED"}),
       (d1, 3, 5.0, 7000.0, {"ex": "bybit", "symbol": "SOLUSDT", "kind": "REALIZED"})]
fz = sb._att_fut_pack(evz, {d1: {}})
rz9 = (fz.get(d1) or {}).get("rows") or []
eth9 = [x for x in rz9 if x[2] == "ETHUSDT"]
chk(eth9 and eth9[0][3] == 0 and eth9[0][4] == 100000 and eth9[0][5] == 2 and abs(sum(x[4] for x in rz9) - sum(e[3] for e in evz)) < 1
    and [x[2] for x in rz9] == ["SOLUSDT", "ETHUSDT"],
    "USD 상쇄 0 · 원화 +₩100,000 선물 행 보존(원화 합 = 정산 시각 원화 합 · 큰 USD 순 뒤)", rz9)
evc = [(d1, i, 1.0 + i, (1.0 + i) * 1400, {"ex": "binance", "symbol": "C%dUSDT" % i, "kind": "REALIZED"}) for i in range(100)] + evz[:2]
fc = sb._att_fut_pack(evc, {d1: {}})
mo9 = (fc.get(d1) or {}).get("more")
chk(len(fc[d1]["rows"]) == 100 and mo9 and mo9[0] == 1 and mo9[1] == 0 and mo9[2] == 100000,
    "상한 넘는 몫이 원화만 남는 행이어도 more = [1, $0, ₩100,000](화면 '그 밖 1종목' 원화)", mo9)
T.finish()
