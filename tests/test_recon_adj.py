#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402
import discopen  # noqa: E402
import recon_adj  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
DAY = 86400
NOW = 1_800_000_000
T0 = NOW - 150 * DAY
E8, E18 = 10 ** 8, 10 ** 18
W1 = "0x00000000000000000000000000000000000000a1"


def _calls(fn, attr):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def _const(n):
    return n.value if isinstance(n, ast.Constant) else None


post_sites, amend_sites, note_keys, fix_funcs = set(), set(), {}, set()
CORE_MODS = {"core_recon", "discopen", "core_snap", "core_post", "core_exf", "core_exf_fut", "core_exf_late", "core_upbit_recon"}
for f in sorted(glob.glob(os.path.join(T.SRC, "*.py"))):
    mod = os.path.basename(f)[:-3]
    tree = ast.parse(open(f, encoding="utf-8").read(), f)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(len(c.args) >= 11 and _const(c.args[10]) == "opening" for c in _calls(fn, "_post_leg") + _calls(fn, "_post_leg_strict")):
            post_sites.add((mod, fn.name))
        if mod in CORE_MODS and (_calls(fn, "_amend_leg") or _calls(fn, "_leg_sql")):
            amend_sites.add((mod, fn.name))
        for c in _calls(fn, "note"):
            if isinstance(c.func.value, ast.Name) and c.func.value.id == "recon_adj" and len(c.args) >= 2:
                note_keys.setdefault((mod, fn.name), set()).add(_const(c.args[1]))
        if any(isinstance(c.func.value, ast.Name) and c.func.value.id == "recon_adj" for c in _calls(fn, "note_fix")):
            fix_funcs.add((mod, fn.name))
want = {(m, f) for (m, f, _d) in recon_adj.SITES.values()}
chk(post_sites == want, "S1 보정 쓰는 자리(src) = SITES 표", (sorted(post_sites ^ want)))
bad = [(k, (m, f), note_keys.get((m, f))) for k, (m, f, _d) in recon_adj.SITES.items() if k not in (note_keys.get((m, f)) or set())]
chk(not bad, "S1 자리마다 recon_adj.note(연결, 그 키, …)", bad)
chk(all(k in recon_adj.SITES for ks in note_keys.values() for k in ks), "S1 note 첫 키 = SITES 키(글자 상수)", note_keys)
chk(amend_sites == set(recon_adj.AMEND_SITES), "S2 보정 고치는 자리 = AMEND_SITES 표", sorted(amend_sites ^ set(recon_adj.AMEND_SITES)))
miss = [k for k, v in recon_adj.AMEND_SITES.items() if v == "note" and k not in fix_funcs]
chk(not miss, "S2 'note' 자리 = recon_adj.note_fix 호출", miss)

c = core.Core(config.load_config())
cx = c.conn


def sums():
    return sorted((r[0], r[1], r[2]) for r in cx.execute("SELECT asset_id, location, sum(CAST(qty_base AS INTEGER)) FROM postings GROUP BY 1, 2"))


a_tok = c.asset_id("token", "polygon", "0x0000000000000000000000000000000000001010", "POL", 18)
sid = discopen.write_anchor(c, "polygon", W1, a_tok, "0x0000000000000000000000000000000000001010", 5 * E18, 100, NOW - DAY, NOW - DAY, 5 * E18, "rpc")
cx.commit()
r = cx.execute("SELECT kind, venue, payload FROM raw_observations WHERE obs_id=?", (f"adjwhy:opening|polygon|{sid}|0",)).fetchone()
chk(r is not None and r[0] == "adj_why" and json.loads(r[2])["site"] == "K3" and json.loads(r[2])["sid"] == sid, "B1 discopen.write_anchor → adj_why 기록(같은 source_id)",
    r and tuple(r))
c._post_stake_open({"stake_open": {"acct": "STK1"}, "deltas": [{"asset": "native", "delta": 7 * 10 ** 9, "owner": "W:stake:STK1"}]}, T0)
cx.commit()
r = cx.execute("SELECT payload FROM raw_observations WHERE obs_id=?", ("adjwhy:opening|sol|recon:sol:stake:STK1|0",)).fetchone()
chk(r is not None and json.loads(r[0])["site"] == "K5" and json.loads(r[0])["why"] == "stake_open", "B1 _post_stake_open → 기록 K5", r and r[0])
a_ex = c.svc_exf._exf_asset("okx", "USDT")
c._post_leg("exchange", "okx:recon", f"exfrecon:USDT:{NOW}", 0, NOW, a_ex, "exchange:okx", 50 * E8, None, None, "opening", "EXF_ADJUST")
cx.commit()
pr = dict(cx.execute("SELECT posting_id, source_id, leg_seq, event_ts, asset_id, qty_base FROM postings WHERE source_ns='okx:recon'").fetchone())
c.svc_exf._exf_shrink(pr, 10 * E8, "exchange:okx", "시험 되돌림")
cx.commit()
r = cx.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"adjwhy:exchange|okx:recon|exfrecon:USDT:{NOW}|0",)).fetchone()
chk(r is not None and json.loads(r[0])["fix"][-1]["site"] == "K7" and "시험 되돌림" in json.loads(r[0])["fix"][-1]["why"], "B1 _exf_shrink 수정 → fix 기록", r and r[0])
n_obs = cx.execute("SELECT count(*) FROM raw_observations WHERE kind='adj_why'").fetchone()[0]
rows = recon_adj.load_rows(cx, None, lambda s, a: 1.0)
chk({x["site"] for x in rows if x["sid"] == sid} == {"K3"} and {x["site"] for x in rows if x["sid"].startswith("recon:sol:stake:")} == {"K5"},
    "B1 load_rows 자리 = 기록", sorted({(x["site"], x["sid"][:20]) for x in rows}))
s_before = sums()
recon_adj.refresh(cx, NOW, lambda v, ref: T0, lambda s, a: 1.0)
chk(sums() == s_before and n_obs == cx.execute("SELECT count(*) FROM raw_observations WHERE kind='adj_why'").fetchone()[0],
    "B1 판정·상태 파일 = 원장·기록 무변(읽기만)")
chk(os.path.exists(paths.state("recon_adj.json")), "B1 state/recon_adj.json 씀")
cx.execute("DELETE FROM postings")
cx.execute("DELETE FROM raw_observations")
cx.commit()


def ins(kind, ns, sid9, seq, ts, aid, loc, qb, ev, lk="opening"):
    return cx.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                      " leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,?,1)", (kind, ns, sid9, seq, ts, aid, loc, str(qb), lk, ev)).lastrowid


def a_x(ex, sym):
    return c.svc_exf._exf_asset(ex, sym)


B0 = NOW - 100 * DAY
OX, BX, GX = "exchange:okx", "exchange:binance", "exchange:gate"
ins("exchange", "okx", "dep:old", 0, T0 - 400 * DAY, a_x("okx", "XRP"), OX, 1000 * E8, "EX_DEPOSIT", lk="move_in")
ins("exchange", "okx:recon", f"exfrecon:XRP:{B0}", 0, T0, a_x("okx", "XRP"), OX, 300 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:ETH:{B0}", 0, T0, a_x("binance", "ETH"), BX, 2 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:SCAM:{B0}", 0, T0, a_x("binance", "SCAM"), BX, 9 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:DOT:{NOW - DAY}", 0, NOW - DAY, a_x("binance", "DOT"), BX, 1 * 10 ** 7, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:USDC:{NOW - DAY}", 2, NOW - DAY, a_x("binance", "USDC"), BX, -3 * E8, "EXF_ADJUST")
ins("exchange", "binance:futpnl", f"exfrecon:USDT:{NOW - DAY}", 0, NOW - DAY, a_x("binance", "USDT"), BX, 700 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exflate:USDT:{NOW - DAY}:b0", 0, NOW - DAY, a_x("binance", "USDT"), BX, 800 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:SOL:{NOW - 9 * DAY}", 0, NOW - 9 * DAY, a_x("binance", "SOL"), BX, 40 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:SOL:{NOW - 4 * DAY}", 0, NOW - 4 * DAY, a_x("binance", "SOL"), BX, -40 * E8 + 10 ** 6, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:ADA:{NOW - 60 * DAY}", 0, NOW - 60 * DAY, a_x("binance", "ADA"), BX, 50 * E8, "EXF_ADJUST")
ins("exchange", "binance:recon", f"exfrecon:ADA:{NOW - 20 * DAY}", 0, NOW - 20 * DAY, a_x("binance", "ADA"), BX, -50 * E8, "EXF_ADJUST")
pid_big = ins("exchange", "binance:recon", f"exfrecon:BNB:{NOW - 2 * DAY}", 0, NOW - 2 * DAY, a_x("binance", "BNB"), BX, 600 * E8, "EXF_ADJUST")
pid_new = ins("exchange", "binance:recon", f"exfrecon:KAIA:{NOW - 2 * DAY}", 0, T0, a_x("binance", "KAIA"), BX, 900 * E8, "EXF_ADJUST")
recon_adj.note(cx, "K7", ("exchange", "binance:recon", f"exfrecon:KAIA:{NOW - 2 * DAY}", 0), "new_source")
ins("exchange", "gate:recon", f"exfrecon:GT:{B0}", 0, B0, a_x("gate", "GT"), GX, -20 * E8, "EXF_ADJUST")
for i in range(3):
    ins("exchange", "binance:recon", f"exfrecon:LINK:{NOW - 3 * DAY + i * 10}", 0, NOW - 3 * DAY + i * 10, a_x("binance", "LINK"), BX, 7 * E8, "EXF_ADJUST")
    ins("exchange", "binance:recon", f"exfrecon:LINK:{NOW - 3 * DAY + i * 10 + 5}", 0, NOW - 3 * DAY + i * 10 + 5, a_x("binance", "LINK"), BX, -7 * E8, "EXF_ADJUST")
a_nat = c.asset_id("native", "polygon", None, symbol="POL", decimals=18)
LW = f"wallet:polygon:{W1}"
ins("chain_tx", "polygon", "0xt1", 0, NOW - 30 * DAY, a_nat, LW, 5 * E18, "TRANSFER_IN", lk="move_in")
ins("opening", "polygon", discopen.sid_of("polygon", W1, "0xmirror", 9), 0, NOW - 20 * DAY, a_tok, LW, 5 * E18, "OPENING")
ins("opening", "polygon", f"recon:polygon:{W1}", 0, T0, c.asset_id("token", "polygon", "0xaa", "AAA", 18), LW, 3 * E18, "OPENING")
cx.commit()
ins("exchange", "binance:futpnl", f"exfrecon:ETH:{NOW - DAY}", 3, NOW - DAY, a_x("binance", "ETH"), BX, 1 * E8, "EXF_ADJUST")
recon_adj.note(cx, "K7f", ("exchange", "binance:futpnl", f"exfrecon:ETH:{NOW - DAY}", 3), "fut_replace")
cx.commit()
PX = {"SCAM": None}
for (aid_chain,) in cx.execute("SELECT asset_id FROM assets WHERE kind != 'exchange_currency'").fetchall():
    c._group_of(aid_chain)
cx.commit()
CHAIN_PX = {"grp": {int(g): 1.0 for (g,) in cx.execute("SELECT group_id FROM assets WHERE kind != 'exchange_currency' AND group_id IS NOT NULL")}, "leg": {}}
rows = recon_adj.classify(cx, recon_adj.load_rows(cx, CHAIN_PX, lambda s, a: PX.get(s, 1.0)), t0_fn=lambda v, ref: T0, gaps={"gate": (None, "게이트 계정 원장 미수집")})
by = {(x["sym"], x["seq"], x["ts"]): x for x in rows}


def cls_of(sym):
    return sorted({(x["cls"], x["red"]) for x in rows if x["sym"] == sym})


chk(cls_of("SCAM") == [("pre_window", None)] and [x["px"] for x in rows if x["sym"] == "SCAM"] == [None],
    "B2 가격 없는 거래소 통화 = 스팸 아님(평가 불가 · 다른 규칙 그대로 — 첫 대사 양수 = 창 시작)", cls_of("SCAM"))
chk(cls_of("DOT") == [("dust", None)], "B2 $1 미만 = 먼지", cls_of("DOT"))
chk(cls_of("USDC") == [("interest", None)], "B2 부채 이자(leg 2 음수)", cls_of("USDC"))
chk(sorted(x["cls"] for x in rows if x["sym"] == "USDT") == ["exflate", "futpnl"], "B2 선물 정산 · 늦은 행 상쇄", cls_of("USDT"))
chk(cls_of("SOL") == [("pair", None)], "B2 ±상쇄 쌍(0.5% · 14일 안)", cls_of("SOL"))
chk(cls_of("ADA") == [("unexplained", None)], "B2 쌍이라도 14일 넘으면 설명 안 됨", cls_of("ADA"))
chk([x["cls"] for x in rows if x["sym"] == "ETH" and x["ns"] == "binance:futpnl"] == ["futpnl"], "B2 이관(K7f)이 다시 놓은 정산 줄 = 선물 정산 규칙",
    [(x["site"], x["cls"]) for x in rows if x["sym"] == "ETH"])
chk(sorted({(x["cls"], x["red"]) for x in rows if x["sym"] == "ETH" and x["ns"] != "binance:futpnl"}) == [("pre_window", None)] and cls_of("AAA") == [("pre_window", None)], "B2 창 시작 기초 잔고(창 이전 행 없음)", (cls_of("ETH"), cls_of("AAA")))
chk(cls_of("KAIA") == [("new_source", None)], "B2 새 잔고 출처 첫 실림(기록 갈래)", cls_of("KAIA"))
chk(cls_of("GT") == [("estimated", None)] and [x["cause"] for x in rows if x["sym"] == "GT"] == ["게이트 계정 원장 미수집"], "B2 알려진 미수집 = 추정(노랑)", cls_of("GT"))
chk(cls_of("BNB") == [("unexplained", None)] and "바이낸스" in [x["cause"] for x in rows if x["sym"] == "BNB"][0], "B2 나머지 = 설명 안 됨 + 추정 원인 글", cls_of("BNB"))
chk([x["red"] for x in rows if x["sym"] == "XRP"] == ["prewin_rows"], "B3 창 이전 원장 행 되받는 첫 대사 앵커 = 빨강", cls_of("XRP"))
chk([x["red"] for x in rows if x["sym"] == "POL"] == ["mirror"], "B3 네이티브와 수량 같은 토큰 앵커 = 빨강", cls_of("POL"))
chk({x["red"] for x in rows if x["sym"] == "LINK"} == {"flip3"} and len([x for x in rows if x["sym"] == "LINK"]) == 6, "B3 같은 칸 ±쌍 하루 3개 = 빨강", cls_of("LINK"))
doc = recon_adj.summarize(rows, NOW, {"binance": 1_000_000.0})
chk(doc["red_by"] == {"flip3": 6, "mirror": 1, "prewin_rows": 1} and doc["red_n"] == 8, "B3 요약 빨강 꼴별 건수", doc["red_by"])
chk(doc["unexplained"]["n"] == 5 and doc["venues"]["binance"]["n7"] == 1 and doc["venues"]["binance"]["usd7"] == 600.0, "B3 요약 장소별 7일·전체(설명 안 됨 = BNB · ADA 둘 · 빨강 XRP·POL)",
    (doc["unexplained"], doc["venues"].get("binance")))


GAP_TXT = "약 4개월 이전 OKX 체결은 API 가 주지 않음(합성 안내)"
rows8 = recon_adj.classify(cx, recon_adj.load_rows(cx, CHAIN_PX, lambda s, a: PX.get(s, 1.0)), t0_fn=lambda v, ref: T0,
                           gaps={"gate": (None, "게이트 계정 원장 미수집"), "okx": (None, GAP_TXT), "polygon": (None, "폴리곤 합성 미수집")})
x8 = [x for x in rows8 if x["sym"] == "XRP"]
chk([(x["cls"], x["red"]) for x in x8] == [("estimated", "prewin_rows")], "B8 재료: 미수집 장소 빨강 행 = cls estimated 그대로(분류 무변)", [(x["cls"], x["red"]) for x in x8])
chk(all(GAP_TXT not in x["cause"] and "창보다 이른 원장 행" in x["cause"] for x in x8), "B8 빨강(prewin_rows) 원인 글 = 버그 꼴 문구 · 미수집 안내 없음", [x["cause"] for x in x8])
p8 = [x for x in rows8 if x["sym"] == "POL"]
chk([x["red"] for x in p8] == ["mirror"] and all("폴리곤 합성 미수집" not in x["cause"] and "네이티브" in x["cause"] for x in p8), "B8 빨강(mirror) 원인 글 = 버그 꼴 문구",
    [(x["cls"], x["cause"]) for x in p8])
l8 = [x for x in rows8 if x["sym"] == "LINK"]
chk({x["red"] for x in l8} == {"flip3"} and all("하루" in x["cause"] for x in l8), "B8 빨강(flip3) 원인 글 = 버그 꼴 문구", sorted({x["cause"] for x in l8}))
g8 = [x for x in rows8 if x["sym"] == "GT"]
chk([(x["cls"], x["red"], x["cause"]) for x in g8] == [("estimated", None, "게이트 계정 원장 미수집")], "B8 반대: 빨강 아닌 추정 행 = 미수집 안내 그대로",
    [(x["cls"], x["red"], x["cause"]) for x in g8])
b8 = [x for x in rows8 if x["sym"] == "BNB"]
chk([x["cls"] for x in b8] == ["unexplained"] and "바이낸스" in b8[0]["cause"], "B8 반대: 빨강 아닌 설명 안 됨 행 = 추정 원인 글 그대로", [x["cause"] for x in b8])
doc8 = recon_adj.summarize(rows8, NOW, {"binance": 1_000_000.0})
ck8 = recon_adj.check(doc8, NOW)
chk(doc8["red_by"] == doc["red_by"] and ck8["level"] == "crit" and GAP_TXT not in ck8["detail"] and "폴리곤 합성 미수집" not in ck8["detail"],
    "B8 헬스 빨강 상세 줄 = 미수집 안내 안 섞임 · 꼴별 건수·레벨 무변", ck8["detail"])

ck = recon_adj.check(doc, NOW)
chk(ck["level"] == "crit" and ck["tg"] and "버그 꼴" in ck["title"], "B4 빨강 = crit · 텔레그램", ck)
doc2 = dict(doc, red=[], red_n=0, red_by={})
ck = recon_adj.check(doc2, NOW)
chk(ck["level"] == "warn" and not ck["tg"] and "$600" in ck["title"], "B4 한 줄 $500 = 노랑(텔레그램 없음)", ck)
doc3 = dict(doc2, unexplained=dict(doc2["unexplained"], usd7=1200.0, n7=2))
chk(recon_adj.check(doc3, NOW)["tg"] is True and recon_adj.check(doc3, NOW)["level"] == "warn", "B4 7일 $1,000 = 노랑 + 텔레그램 1회")
doc4 = dict(doc2, warn=[], warn_n=0, unexplained=dict(doc2["unexplained"], usd7=10.0, n7=1))
chk(recon_adj.check(doc4, NOW)["level"] == "ok", "B4 큰 것 없음 = ok", recon_adj.check(doc4, NOW))
chk(recon_adj.check(None) is None and recon_adj.check({"v": 0}) is None, "B4 파일 없음·옛 꼴 = None")
small = recon_adj.summarize([x for x in rows if x["sym"] == "BNB"], NOW, {"binance": 10_000.0})
chk(small["warn_n"] == 1, "B4 평가액 2% 문턱(그 장소)", small["warn_n"])
small = recon_adj.summarize([dict(x, usd=150.0) for x in rows if x["sym"] == "BNB"], NOW, {"binance": 5_000.0})
chk(small["warn_n"] == 1, "B4 $500 미만이어도 평가액 2% 넘으면 노랑", small["warn_n"])
small = recon_adj.summarize([dict(x, usd=150.0) for x in rows if x["sym"] == "BNB"], NOW, {"binance": 1_000_000.0})
chk(small["warn_n"] == 0, "B4 $500 미만 · 2% 미만 = 노랑 아님", small["warn_n"])

got = []
WT0 = lambda ref, sec: T0  # noqa: E731
recon_adj.exf_dm(cx, WT0, "binance", NOW - 2 * DAY, 2, lambda k, m: got.append((k, m)), px_fn=lambda s, a: 1.0)
chk(len(got) == 1 and got[0][0] == "EXF_RECON" and "설명 안 된 1개 통화 보정 $600" in got[0][1] and "BNB" in got[0][1], "B5 exf_dm = 설명 안 된 보정만 $ 와 함께", got)
got.clear()
recon_adj.exf_dm(cx, WT0, "binance", NOW - DAY, 3, lambda k, m: got.append((k, m)), px_fn=lambda s, a: 1.0)
chk(got == [], "B5 설명된 보정만 = 안 보냄", got)
recon_adj.exf_dm(cx, WT0, "binance", NOW - DAY, 0, lambda k, m: got.append((k, m)))
chk(got == [], "B5 보정 0 = 안 보냄")
recon_adj.exf_dm(None, WT0, "okx", NOW, 2, lambda k, m: got.append((k, m)))
chk(got == [("EXF_RECON", "okx 잔고 대사 완료 — 2개 통화 보정")], "B5 판정 실패 = 종전 문장", got)
TST = {}
d1 = recon_adj.tick(cx, WT0, None, NOW, TST)
chk(isinstance(d1, dict) and recon_adj.tick(cx, WT0, None, NOW + 30, TST) is None and recon_adj.tick(cx, WT0, None, NOW + 120, TST) is None, "B5 tick 최소 간격 · 지문 같으면 쉼")
ins("exchange", "binance:recon", f"exfrecon:XLM:{NOW}", 0, NOW, a_x("binance", "XLM"), BX, 1 * E8, "EXF_ADJUST")
cx.commit()
chk(isinstance(recon_adj.tick(cx, WT0, None, NOW + 200, TST), dict) and isinstance(recon_adj.tick(cx, WT0, None, NOW + 200 + recon_adj.REFRESH_SEC + 1, TST), dict),
    "B5 보정 줄 바뀜 · REFRESH_SEC 지남 = 다시 판정")
on_disk = json.load(open(paths.state("recon_adj.json")))
chk(on_disk.get("v") == 1 and on_disk["red_n"] >= 1, "B5 상태 파일 = 요약 문서", sorted(on_disk))
chk(isinstance(on_disk.get("check"), dict) and on_disk["check"]["level"] == "crit", "B5 상태 파일 check 칸 = 헬스 재료(빨강)", on_disk.get("check"))
import health  # noqa: E402
HS = health.settings({"health": {"units": ["tj-core"]}})


def adj_check(doc):
    obs = {"now": NOW, "pm2": {"tj-core": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [], "recon_adj": doc}
    return {x["id"]: x for x in health.evaluate(obs, HS)}.get("ledger:adj")


hc = adj_check(on_disk)
chk(hc is not None and hc["level"] == "crit" and hc["notify"] and hc["unit"] == "tj-core", "B5 헬스 ledger:adj = 빨강 · 알림", hc and (hc["level"], hc["title"]))
hc = adj_check(dict(on_disk, check=recon_adj.check(doc3, NOW)))
chk(hc is not None and hc["level"] == "warn" and hc.get("tg_force") is True and hc["notify"], "B5 헬스 7일 $1,000 = 노랑 + 텔레그램 1회(notify + tg_force — 관문 eligible)",
    hc and (hc["level"], hc.get("tg_force"), hc["notify"]))
hc = adj_check(dict(on_disk, check=recon_adj.check(doc2, NOW)))
chk(hc is not None and hc["level"] == "warn" and not hc.get("tg_force") and not hc["notify"], "B5 헬스 한 줄 $500 = 노랑만", hc and (hc["level"], hc.get("tg_force")))
chk(adj_check(None) is None and adj_check({"v": 1}) is None, "B5 헬스 상태 파일 없음·check 칸 없음 = 항목 없음")
chk(recon_adj.tick(None, WT0, None, NOW, {}) is None, "B5 tick 실패 = None(삼킴 · 다음 주기)")

cx.execute("DELETE FROM postings")
cx.execute("DELETE FROM raw_observations")
OLDB = NOW - 40 * DAY
pid_old = ins("exchange", "bybit:recon", f"exfrecon:ETH:{OLDB}", 0, T0, a_x("bybit", "ETH"), "exchange:bybit", 2 * E8, "EXF_ADJUST")
cx.commit()
recon_adj.note_fix(cx, "K7", pid_old, "ext_redate")
ins("exchange", "upbit:recon", f"exrecon:BTC:{NOW - 90 * DAY}", 0, T0, a_x("upbit", "BTC"), "exchange:upbit", 1 * E8, "EX_ADJUST")
ins("exchange", "upbit:recon", f"exrecon:XRP:{NOW - 2 * DAY}", 0, T0, a_x("upbit", "XRP"), "exchange:upbit", 900 * E8, "EX_ADJUST")
recon_adj.note(cx, "K10", ("exchange", "upbit:recon", f"exrecon:XRP:{NOW - 2 * DAY}", 0), "pos_window_start")
ins("exchange", "binance:recon", f"exflate:DOGE:{NOW - DAY}:b1", 0, NOW - DAY, a_x("binance", "DOGE"), BX, 800 * E8, "EXF_ADJUST")
recon_adj.note(cx, "K7f", ("exchange", "binance:recon", f"exflate:DOGE:{NOW - DAY}:b1", 0), "fut_replace")
for i in range(3):
    ins("exchange", "binance:futpnl", f"exfrecon:USDT:{NOW - DAY + i}", 0, NOW - DAY + i, a_x("binance", "USDT"), BX, 10 * E8, "EXF_ADJUST")
    ins("exchange", "binance:futpnl", f"exfrecon:USDT:{NOW - DAY + i}", 1, NOW - DAY + i, a_x("binance", "USDT"), BX, -10 * E8, "EXF_ADJUST")
a_fake = c.asset_id("token", "eth", "0x00000000000000000000000000000000000000f1", "USDT", 6)
ins("opening", "eth", f"recon:eth:{W1}", 0, T0, a_fake, f"wallet:eth:{W1}", 10 ** 12, "OPENING")
cx.commit()
rows = recon_adj.classify(cx, recon_adj.load_rows(cx, None, lambda s, a: 1.0), t0_fn=lambda v, ref: T0)
old = [x for x in rows if x["pid"] == pid_old][0]
chk(old["made"] == OLDB and old["red"] is None, "B7 기록 없던 옛 줄 고침(note_fix) = 만든 시각은 대사 시각 그대로", (old["made"] - OLDB, old["red"]))
chk(cls_of("XRP") == [("pre_window", None)], "B7 업비트 후속 양수(창 시작) = 창 시작 기초 잔고", cls_of("XRP"))
chk(cls_of("DOGE") == [("exflate", None)], "B7 이관(K7f)이 다시 놓은 늦은 행 = 늦은 행 상쇄", cls_of("DOGE"))
chk({(x["cls"], x["red"]) for x in rows if x["sym"] == "USDT" and x["ns"] == "binance:futpnl"} == {("futpnl", None)}, "B7 정산 ±쌍 하루 3개 = flip3 아님",
    {(x["cls"], x["red"]) for x in rows if x["sym"] == "USDT"})
chk([x["cls"] for x in rows if x["aid"] == a_fake] == ["spam"], "B7 거래소 단가(px_fn)는 체인 토큰(기호만 USDT)에 안 씀", [x["px"] for x in rows if x["aid"] == a_fake])


calls = []
recon_adj.load_rows(cx, None, lambda sy, a: calls.append(a) or 1.0)
chk(len(calls) == len(set(calls)), "B7 대신 쓸 단가 = 자산마다 한 번", (len(calls), len(set(calls))))
a_krw = a_x("upbit", "KRW")
ins("exchange", "upbit:recon", f"exrecon:KRW:{NOW}", 0, NOW, a_krw, "exchange:upbit", -5 * E8, "EX_ADJUST")
cx.commit()
asked = []
recon_adj.load_rows(cx, None, lambda sy, a: asked.append(sy) or 1.0)
chk("KRW" not in asked, "B7 원화 = 대신 쓸 단가 안 부름(환율 조회 = 네트워크)", sorted(set(asked)))
chk(recon_adj.exf_why(-5, 100, 100, 0, {"first": True}) == "first", "B7 첫 대사 음수도 'first'(창 이전 행 검사 대상)")
pid_st = ins("exchange", "kucoin:recon", f"exfrecon:KCS:{NOW - 3 * DAY}", 0, T0, a_x("kucoin", "KCS"), "exchange:kucoin", 700 * E8, "EXF_ADJUST")
ins("exchange", "kucoin:recon", f"exfrecon:ATOM:{NOW - 30 * DAY}", 0, T0, a_x("kucoin", "ATOM"), "exchange:kucoin", 1 * E8, "EXF_ADJUST")
recon_adj.note(cx, "K7", ("exchange", "kucoin:recon", f"exfrecon:KCS:{NOW - 3 * DAY}", 0), "settle_pos")
cx.commit()
rows = recon_adj.classify(cx, recon_adj.load_rows(cx, None, lambda s, a: 1.0), t0_fn=lambda v, ref: T0)
chk(cls_of("KCS") == [("pre_window", None)], "B7 창 확장 정착 중 양수(settle_pos) = 창 시작 앵커", cls_of("KCS"))
CL = os.path.join(T.TMP, "cl")
os.makedirs(CL, exist_ok=True)
json.dump({"unavailable": [{"source_id": "exchange:binance:spot_fills", "before": "2026-01-01", "reason_ko": "보존 기한"},
                           {"source_id": "exchange:binance:dividend", "reason_ko": "배당 미수집"}]}, open(os.path.join(CL, "coverage_limits.json"), "w"))
chk(recon_adj.coverage_gaps(CL) == {"binance": (None, "배당 미수집")}, "B7 날짜 없는(지금도) 미수집이 보존 기한 항목을 이김", recon_adj.coverage_gaps(CL))
json.dump({"unavailable": [{"source_id": "exchange:binance:dividend", "reason_ko": "배당 미수집"},
                           {"source_id": "exchange:binance:spot_fills", "before": "2026-01-01", "reason_ko": "보존 기한"}]}, open(os.path.join(CL, "coverage_limits.json"), "w"))
chk(recon_adj.coverage_gaps(CL) == {"binance": (None, "배당 미수집")}, "B7 (순서 바꿔도) 날짜 없는 항목 유지")
sx = {}
recon_adj.tick(cx, WT0, None, NOW + 5000, sx)
q0 = sx.get("checked")
recon_adj.tick(cx, WT0, None, NOW + 5000 + recon_adj.MIN_GAP_SEC + 1, sx)
r0 = recon_adj.tick(cx, WT0, None, NOW + 5000 + recon_adj.MIN_GAP_SEC + 5, sx)
chk(r0 is None and sx["checked"] == NOW + 5000 + recon_adj.MIN_GAP_SEC + 1 and q0 == NOW + 5000, "B7 지문 확인도 최소 간격마다 한 번", sx)
import alert_bot  # noqa: E402
chk(alert_bot.recon_fixed("okx 잔고 대사 — 설명 안 된 4개 통화 보정 $2,000 (A +$1)") == 4, "B7 새 EXF_RECON 문장 = 하루 요약 'N개 고침' 집계 꼴")


cx.execute("DELETE FROM postings")
cx.execute("DELETE FROM raw_observations")
LW2 = f"wallet:eth:{W1}"
a_e = c.asset_id("token", "eth", "0x00000000000000000000000000000000000000e2", "EEE", 18)
c._group_of(a_e)
ins("chain_tx", "eth", "0xold", 0, T0 - 2 * DAY, a_e, LW2, 5 * E18, "TRANSFER_IN", lk="move_in")
ins("opening", "eth", f"recon:eth:{W1}", 0, T0 - 2 * DAY - 1, a_e, LW2, 1 * E18, "OPENING")
a_k4 = c.asset_id("token", "eth", "0x00000000000000000000000000000000000000e3", "KKK", 18)
c._group_of(a_k4)
ins("opening", "eth", f"recon:eth:{W1}", 1, T0, a_k4, LW2, 7 * E18, "OPENING")
recon_adj.note(cx, "K4", ("opening", "eth", f"recon:eth:{W1}", 1), "anchor_readjust")
B9 = NOW - 50 * DAY
ins("exchange", "okx", "dep:old2", 0, T0 - 400 * DAY, a_x("okx", "ETH"), OX, 3 * E8, "EX_DEPOSIT", lk="move_in")
ins("exchange", "okx:recon", f"exfrecon:ETH:{B9}", 0, B9, a_x("okx", "ETH"), OX, -3 * E8, "EXF_ADJUST")
recon_adj.note(cx, "K7f", ("exchange", "okx:recon", f"exfrecon:ETH:{B9}", 0), "fut_replace")
cx.commit()
for (aid_chain,) in cx.execute("SELECT asset_id FROM assets WHERE kind != 'exchange_currency'").fetchall():
    c._group_of(aid_chain)
cx.commit()
PX3 = {"grp": {int(g): 1.0 for (g,) in cx.execute("SELECT group_id FROM assets WHERE group_id IS NOT NULL")}, "leg": {}}
rows = recon_adj.classify(cx, recon_adj.load_rows(cx, PX3), t0_fn=lambda v, ref: T0)
chk(cls_of("EEE") == [("pre_window", None)], "B7 새 지갑 앵커가 창 이전 첫 기장 앞 = 정상(빨강 아님)", cls_of("EEE"))
chk(cls_of("KKK") == [("pre_window", None)], "B7 K4 재기장 새 양수 앵커 = 창 시작 기초 잔고", cls_of("KKK"))
chk([x["red"] for x in rows if x["sym"] == "ETH" and x["loc"] == OX] == ["prewin_rows"], "B7 이관이 되살린 첫 대사 = 창 이전 행 검사(빨강)", cls_of("ETH"))
got = []
before_doc = open(paths.state("recon_adj.json")).read()
recon_adj.exf_dm(cx, WT0, "okx", B9, 1, lambda k, m: got.append((k, m)))
chk(open(paths.state("recon_adj.json")).read() == before_doc, "B7 exf_dm 은 상태 파일을 안 씀(tick 만 — 가격 정책 하나)")


class TxGone:
    def __init__(self, drop):
        self.in_transaction, self.drop = True, drop

    def execute(self, *a):
        if self.drop:
            self.in_transaction = False
        raise sqlite3.OperationalError("database or disk is full")


try:
    recon_adj.note(TxGone(True), "K7", ("exchange", "x:recon", "exfrecon:A:1", 0), "first")
    raised = False
except sqlite3.OperationalError:
    raised = True
chk(raised, "B7 기록 실패가 부르는 쪽 트랜잭션을 되돌렸으면 다시 던짐(대사 완료 표식만 커밋되지 않게)")
recon_adj.note(TxGone(False), "K7", ("exchange", "x:recon", "exfrecon:A:1", 0), "first")
chk(True, "B7 트랜잭션이 남은 기록 실패 = 삼킴")
try:
    recon_adj.note_fix(TxGone(True), "K7", 1, "x")
    raised = False
except sqlite3.OperationalError:
    raised = True
chk(raised, "B7 note_fix 도 같은 규칙")

cz = sqlite3.connect(":memory:")
cz.close()
recon_adj.note(cz, "K7", ("exchange", "x:recon", "exfrecon:A:1", 0), "first")
recon_adj.note_fix(cz, "K7", 1, "x")
chk(True, "B6 닫힌 연결 note·note_fix = 예외 없음")
chk(recon_adj.exf_why(5, 100, 100, 0, {"first": True}) == "first" and recon_adj.exf_why(5, 100, 100, 0, {"cov": True}) == "new_source"
    and recon_adj.exf_why(-5, 100, 100, 2, {"debt": True}) == "debt_interest" and recon_adj.exf_why(5, 10, 100, 1, {}) == "deficit_back"
    and recon_adj.exf_why(-5, 100, 100, 0, {}) == "untracked_out" and recon_adj.exf_why(-5, 10, 100, 0, {"settle": True}) == "settle_neg",
    "B6 exf_why 갈래 = 그 자리 분기 순서")
T.finish()
