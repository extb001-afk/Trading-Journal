#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config  # noqa: E402
import core  # noqa: E402
import autofix  # noqa: E402
import recon_adj  # noqa: E402
import recon_auto  # noqa: E402

chk = T.chk
DAY = 86400
NOW = 1_800_000_000
T0 = NOW - 150 * DAY
E8 = 10 ** 8
c = core.Core(config.load_config())
cx = c.conn
OX = "exchange:okx"


def ins(kind, ns, sid9, seq, ts, aid, loc, qb, ev, lk="opening"):
    return cx.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                      " leg_kind, event, classifier_ver) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?,?,1)", (kind, ns, sid9, seq, ts, aid, loc, str(qb), lk, ev)).lastrowid


def a_x(ex, sym):
    return c.svc_exf._exf_asset(ex, sym)


def meta(k, v):
    cx.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, v))


def reset():
    cx.execute("DELETE FROM postings")
    cx.execute("DELETE FROM raw_observations")
    cx.execute("DELETE FROM meta WHERE k >= 'autofix' AND k < 'autofiy'")
    cx.commit()


def run(values=None, auto_on=False, vgap=None, now=NOW, px=None):
    rows = recon_adj.classify(cx, recon_adj.load_rows(cx, None, lambda s, a: (px or {}).get(s, 1.0)), t0_fn=lambda v, ref: T0,
                              ctx={"values": values or {}, "vgap": vgap, "auto_on": auto_on, "now": now})
    return rows, recon_adj.summarize(rows, now, values or {})


def of(rows, sym, site=None):
    return [x for x in rows if x["sym"] == sym and (site is None or x["site"] == site)]


B0 = NOW - 100 * DAY
TAU = NOW - 120 * DAY
RCPT = json.dumps({"v": 1, "gid": 1, "prewin": [], "anchor": {}, "auto": {}, "obs_b0": "0", "tau": TAU, "X": "0", "U": "100", "state": autofix.ST_APPLIED,
                   "at": NOW - DAY, "undo": "x.json"})


ins("exchange", "okx", "dep:old", 0, T0 - 400 * DAY, a_x("okx", "TKJ"), OX, -50 * E8, "EX_WITHDRAW", lk="move_out")
ins("exchange", "okx:recon", f"exfrecon:TKJ:{B0}", 0, T0, a_x("okx", "TKJ"), OX, 30 * E8, "EXF_ADJUST")
cx.commit()
rows, doc = run()
chk([x["red"] for x in of(rows, "TKJ")] == ["prewin_rows"] and doc["check"]["level"] == "crit", "C2 적용 전 = prewin_rows 빨강(자동 처리 꺼짐 = 종전)",
    [(x["red"], x["cls"]) for x in of(rows, "TKJ")])
rows, doc = run(auto_on=True)
r1 = of(rows, "TKJ")[0]
chk(r1["red"] == "prewin_rows" and r1["r1"] and "R1" in r1["cause"] and doc["check"]["level"] == "crit", "C2 켜짐 + 첫 대사 72시간 넘음 = 빨강 + 원인 글 R1", (r1["red"], r1["cause"]))
rows, doc = run(auto_on=True, now=B0 + 3600)
w1 = of(rows, "TKJ")[0]
chk(w1["red"] is None and w1["cls"] == "auto_wait" and doc["red_n"] == 0 and doc["gray"]["wait_n"] == 1
    and any("자동 처리 대기" in x for x in doc["check"]["info"]), "C2 켜짐 + 첫 대사 72시간 안 = 대기(회색 · 빨강 아님)", (w1["red"], w1["cls"], doc["check"]))
dr_on, dr_off = recon_adj.refresh(cx, B0 + 3600, lambda v, ref: T0, lambda s, a: 1.0, True), recon_adj.refresh(cx, B0 + 3600, lambda v, ref: T0, lambda s, a: 1.0)
chk(dr_on["gray"]["wait_n"] == 1 and dr_on["red_n"] == 0 and dr_off["red_n"] == 1 and dr_off["check"]["level"] == "crit",
    "C2 refresh(auto_on) 배선 = 켜짐만 대기 · 기본(꺼짐) = 종전 빨강", (dr_on["gray"], dr_off["red_by"]))
meta(autofix.off_key("okx", "TKJ"), "1")
cx.commit()
rows, doc = run()
k1 = of(rows, "TKJ")[0]
chk(k1["red"] is None and k1["cls"] == "owner_kept" and doc["red_n"] == 0 and doc["gray"]["kept_n"] == 1 and any("그대로 둔 칸 1" in x for x in doc["check"]["info"]),
    "C2 끄기 칸(autofix_off) = owner_kept 회색 · 빨강 끔", (k1["red"], k1["cls"], doc["check"]["info"]))
reset()
ins("exchange", "okx", "dep:old", 0, T0 - 400 * DAY, a_x("okx", "TKJ"), OX, -50 * E8, "EX_WITHDRAW", lk="move_out")
ins("exchange", "okx:recon", f"exfrecon:TKJ:{B0}", 0, T0, a_x("okx", "TKJ"), OX, 30 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKJ"), RCPT)
cx.commit()
rows, doc = run()
chk([x["red"] for x in of(rows, "TKJ")] == ["prewin_rows"] and doc["check"]["level"] == "crit", "C2 영수증 있어도 창 이전 행 남음 = 빨강 그대로", [x["red"] for x in of(rows, "TKJ")])
reset()

a_t = a_x("okx", "TKJ")
ins("exchange", "okx", "trade:1", 0, B0 - 10 * DAY, a_t, OX, 20 * E8, "EX_TRADE", lk="trade")
ins("exchange", "okx:recon", f"exfrecon:TKJ:{B0}", 0, T0, a_t, OX, 10 * E8, "EXF_ADJUST")
pid_auto = ins("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKJ", B0), 0, TAU, a_t, OX, -100 * E8, "EXF_ADJUST")
ins("exchange", "okx:recon", f"exfrecon:TKJ:{B0 + 5 * DAY}", 0, TAU + 5, a_t, OX, 100 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKJ"), RCPT)
cx.commit()
rows, doc = run(values={"okx": 1_000_000.0})
au = of(rows, "TKJ", recon_auto.SITE_AUTO)
an = [x for x in of(rows, "TKJ", "K7") if x["bts"] == B0]
chk(len(au) == 1 and au[0]["cls"] == "auto" and au[0]["bts"] == B0 and au[0]["made"] == B0 and au[0]["pair"] is None,
    "C1 기록 없는 자동 행 = 자리 K11 · 분류 auto · 대사 시각 = 첫 대사 · ±쌍 아님", au and (au[0]["site"], au[0]["cls"], au[0]["pair"]))
chk(len(an) == 1 and an[0]["cls"] == "auto" and an[0]["red"] is None and doc["red_n"] == 0, "C1·C2 영수증 칸 첫 대사 앵커 = auto · 적용 뒤 빨강 사라짐",
    an and (an[0]["cls"], an[0]["red"], doc["red_by"]))
chk(doc["auto"]["n"] == 1 and doc["auto"]["usd"] == 100.0 and doc["gray"]["auto_n"] == 0, "C1 자동 처리 집계 = 자동 행만(앵커 X 이중 집계 안 함)", doc["auto"])
chk(doc["check"]["level"] == "ok" and not doc["check"]["info"], "C3 재료: 자동 행 시각 = 첫 대사(100일 전 · 기록 없음) = 7일 창 밖", doc["check"])
recon_adj.note(cx, recon_auto.SITE_AUTO, ("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKJ", B0), 0), "auto_out")
cx.execute("UPDATE raw_observations SET observed_at=? WHERE kind='adj_why'", (NOW - DAY,))
cx.commit()


def with_usd(rows, usd):
    for x in rows:
        if x["site"] == recon_auto.SITE_AUTO:
            x["usd"] = -usd
    return rows


rows, _ = run(values={"okx": 1_000_000.0})
au = of(rows, "TKJ", recon_auto.SITE_AUTO)
chk(au[0]["site"] == recon_auto.SITE_AUTO and au[0]["made"] == NOW - DAY and au[0]["why"] == "auto_out", "C1 K11 기록 있는 자동 행 = 만든 시각 = 기록 시각", (au[0]["site"], au[0]["made"]))

d1 = recon_adj.summarize(with_usd(rows, 15_000.0), NOW, {"okx": 1_000_000.0})
ck1 = recon_adj.check(d1, NOW)
chk(d1["warn_n"] == 1 and ck1["level"] == "warn" and ck1["tg"] is True and "자동 처리" in ck1["title"], "C3 장소 $10^6 · 자동 −$1.5×10^4 = 노랑 + 텔레그램", ck1)
d2 = recon_adj.summarize(with_usd(rows, 900.0), NOW, {"okx": 10_000.0})
ck2 = recon_adj.check(d2, NOW)
chk(d2["warn_n"] == 1 and ck2["level"] == "warn" and ck2["tg"] is False, "C3 장소 $10^4 · 자동 −$900 = 노랑(텔레그램 없음)", ck2)
d3 = recon_adj.summarize(with_usd(rows, 100.0), NOW, {"okx": 100_000.0})
ck3 = recon_adj.check(d3, NOW)
chk(d3["warn_n"] == 0 and ck3["level"] == "ok" and d3["gray"]["auto_n"] == 1 and any(x.startswith("자동 처리 1칸") for x in ck3["info"]),
    "C3 장소 $10^5 · 자동 −$100 = 회색 줄(노랑 아님)", (ck3["level"], ck3["info"]))
d4 = recon_adj.summarize(with_usd(rows, 400.0) + [dict(of(rows, "TKJ", recon_auto.SITE_AUTO)[0], pid=-1, usd=-700.0)], NOW, {"okx": 1_000_000.0})
chk(d4["warn_n"] == 1 and recon_adj.check(d4, NOW)["tg"] is True, "C3 텔레그램 $1,000 = 자동 행 합(작은 줄 둘 합 $1,100)", (d4["warn_n"], d4["auto"]))
ux = [dict(x, usd=None, px=None, nopx=True, real=True) if x["site"] == recon_auto.SITE_AUTO else x for x in rows]
d5 = recon_adj.summarize(ux, NOW, {"okx": 1_000_000.0})
chk(d5["warn_n"] == 1 and "평가 불가" in recon_adj.check(d5, NOW)["title"], "C3 평가 불가 자동 행 = 노랑(금액 모름)", recon_adj.check(d5, NOW)["title"])
cx.execute("UPDATE raw_observations SET observed_at=? WHERE kind='adj_why'", (NOW - 14 * DAY,))
cx.commit()
rows, _ = run(values={"okx": 1_000_000.0})
d6 = recon_adj.summarize(with_usd(rows, 15_000.0), NOW, {"okx": 1_000_000.0})
chk(d6["warn_n"] == 0 and recon_adj.check(d6, NOW)["level"] == "ok", "C3 경고 시각 = K11 기록 시각(14일 전 = 7일 창 밖)", recon_adj.check(d6, NOW))
recon_adj.note(cx, recon_auto.SITE_AUTO, ("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKJ", B0), 0), "auto_out_grow")
cx.execute("UPDATE raw_observations SET observed_at=? WHERE kind='adj_why'", (NOW - 3600,))
cx.commit()
rows, _ = run(values={"okx": 1_000_000.0})
d7 = recon_adj.summarize(with_usd(rows, 15_000.0), NOW, {"okx": 1_000_000.0})
chk(d7["warn_n"] == 1 and recon_adj.check(d7, NOW)["tg"] is True, "C3 재계획 새 기록 = 오늘 노랑·텔레그램", recon_adj.check(d7, NOW))
an_big = [dict(x, usd=50_000.0) if x["site"] == "K7" and x["bts"] == B0 else x for x in with_usd(rows, 100.0)]
d8 = recon_adj.summarize(an_big, NOW, {"okx": 100_000.0})
chk(d8["warn_n"] == 0 and recon_adj.check(d8, NOW)["tg"] is False, "C3 앵커 X(auto) 는 노랑·텔레그램 집계 안 함", (d8["warn_n"], d8["auto"]))
reset()

a_g = a_x("okx", "TKB")
ins("exchange", "okx:recon", f"exfrecon:TKB:{NOW - 2 * DAY}", 1, NOW - 130 * DAY, a_g, OX, -100 * E8, "EXF_ADJUST")
ins("exchange", "okx:recon", f"exfrecon:TKC:{NOW - 2 * DAY}", 1, NOW - 130 * DAY, a_x("okx", "TKC"), OX, -15_000 * E8, "EXF_ADJUST")
ins("exchange", "bybit:recon", f"exfrecon:TKD:{NOW - 2 * DAY}", 1, NOW - 130 * DAY, a_x("bybit", "TKD"), "exchange:bybit", -15_000 * E8, "EXF_ADJUST")
cx.commit()
VG = {"okx": [{"kind": "spot_fills", "t0": T0, "full_t0": NOW - 110 * DAY, "why": "합성"}]}
rows, doc = run(values={"okx": 1_000_000.0, "bybit": 1_000_000.0}, vgap=VG)
chk([x["cls"] for x in of(rows, "TKB")] == ["gap"] and doc["gray"]["gap_n"] == 1 and any("빈 구간 보정 1건 $100" in x for x in doc["check"]["info"]),
    "C4 빈 구간 안 작은 보정 = gap 회색(정보 줄)", ([x["cls"] for x in of(rows, "TKB")], doc["check"]["info"]))
chk([x["cls"] for x in of(rows, "TKC")] == ["unexplained"] and any(r["sym"] == "TKC" for r in doc["warn"]), "C4 빈 구간 안이라도 $500 이상 = 노랑 그대로",
    [x["cls"] for x in of(rows, "TKC")])
chk([x["cls"] for x in of(rows, "TKD")] == ["unexplained"] and recon_adj.HINTS["bybit"] in of(rows, "TKD")[0]["cause"] and any(r["sym"] == "TKD" for r in doc["warn"]),
    "C4 HINTS 만(빈 구간 없음) 큰 보정 = 노랑", of(rows, "TKD")[0]["cause"])
chk(doc["unexplained"]["n"] == 2, "C4 gap 회색 = 설명 안 됨 집계 밖", doc["unexplained"])
got = []
r9, d9 = recon_adj.compute(cx, NOW, lambda v, ref: T0, None, lambda s, a: 1.0, {"gap_fn": lambda *a, **k: got.append(a[1]) or VG.get(a[1], [])})
chk(got == ["bybit", "okx"] and [x["cls"] for x in r9 if x["sym"] == "TKB"] == ["gap"], "C4 compute = 장소마다 venue_gap 한 번(K7 장소)", got)


def boom(*a, **k):
    raise RuntimeError("합성 실패")


r9, d9 = recon_adj.compute(cx, NOW, lambda v, ref: T0, None, lambda s, a: 1.0, {"gap_fn": boom})
chk([x["cls"] for x in r9 if x["sym"] == "TKB"] == ["unexplained"] and isinstance(d9.get("check"), dict), "C4 빈 구간 판정 실패 = 삼킴(종전 규칙 · 판정 계속)",
    [x["cls"] for x in r9 if x["sym"] == "TKB"])
reset()

ins("exchange", "okx:recon", f"exfrecon:TKR:{B0}", 0, T0, a_x("okx", "TKR"), OX, 10 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKR"), json.dumps(dict(json.loads(RCPT), state=autofix.ST_RESOLVED)))
ins("exchange", "okx:recon", f"exfrecon:TKS:{B0}", 0, T0, a_x("okx", "TKS"), OX, 10 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKS"), "{깨짐")
cx.commit()
rows, doc = run()
chk([x["cls"] for x in of(rows, "TKR")] == ["pre_window"] and doc["auto"]["n"] == 0 and doc["gray"]["auto_n"] == 0 and not doc["check"]["info"],
    "C5 resolved 칸(자동 행 없음) = 앵커 종전 규칙(창 시작 기초 잔고) · 회색 줄 없음", ([x["cls"] for x in of(rows, "TKR")], doc["auto"], doc["check"]["info"]))
chk([x["cls"] for x in of(rows, "TKS")] == ["pre_window"], "C5 깨진 영수증 = 판단 불가(종전 규칙 — 창 시작 기초 잔고)", [x["cls"] for x in of(rows, "TKS")])

reset()

a_z = a_x("okx", "TKZ")
ins("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKZ", B0), 0, TAU, a_z, OX, -100 * E8, "EXF_ADJUST")
ins("exchange", "okx:recon", f"exfrecon:TKZ:{NOW - 2 * DAY}", 0, NOW - 2 * DAY, a_z, OX, -15_000 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKZ"), RCPT)
meta(autofix.off_key("okx", "TKY"), "1")
ins("exchange", "okx:recon", f"exfrecon:TKY:{NOW - 2 * DAY}", 0, NOW - 2 * DAY, a_x("okx", "TKY"), OX, -15_000 * E8, "EXF_ADJUST")
cx.commit()
rows, doc = run(values={"okx": 1_000_000.0})
z = [x for x in of(rows, "TKZ", "K7")]
chk(len(z) == 1 and z[0]["first"] and z[0]["cls"] == "unexplained" and any(r["sym"] == "TKZ" and r["site"] == "K7" for r in doc["warn"]),
    "C6 X=0 칸: 후속 큰 음수(남은 가장 이른 대사 줄) = auto 아님 · 노랑 그대로", [(x["first"], x["cls"]) for x in z])
y = of(rows, "TKY", "K7")
chk([x["cls"] for x in y] == ["unexplained"] and any(r["sym"] == "TKY" for r in doc["warn"]), "C6 끄기 칸의 빨강 아닌 대사 보정 = owner_kept 아님 · 노랑 그대로", [x["cls"] for x in y])
many = [dict(of(rows, "TKZ", recon_auto.SITE_AUTO)[0], pid=-i, made=NOW - DAY, usd=-600.0) for i in range(21)]
d21 = recon_adj.summarize(many, NOW, {"okx": 1_000_000.0})
ck21 = recon_adj.check(d21, NOW)
chk(d21["warn_n"] == 21 and d21["warn_auto_n"] == 21 and "자동 처리" in ck21["title"], "C6 (s32w4_1 LOW) 자동 행 노랑 21건(상세 20건 자름) = 자동 처리 제목", ck21["title"])

reset()
pair_b0 = NOW - 12 * DAY
a_pair = a_x("okx", "TKP")
ins("exchange", "okx:recon", f"exfrecon:TKP:{pair_b0}", 0, T0, a_pair, OX, 20 * E8, "EXF_ADJUST")
ins("exchange", "okx:trade", "tkp:sell", 0, T0 + 5 * DAY, a_pair, OX, -20 * E8, "EXF_SELL", lk="disp")
ins("exchange", "okx:trade", "tkp:buy", 0, T0 + 10 * DAY, a_pair, OX, 100 * E8, "EXF_BUY", lk="acq")
ins("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKP", pair_b0), 0, T0 + 10 * DAY + 1, a_pair, OX, -70 * E8, "EXF_ADJUST")
ins("exchange", "okx:recon", f"exfrecon:TKP:{NOW - DAY}", 0, NOW - DAY, a_pair, OX, -20 * E8, "EXF_ADJUST")
meta(autofix.receipt_key("okx", "TKP"), json.dumps(dict(json.loads(RCPT), b0=pair_b0, X=str(20 * E8), U=str(70 * E8), at=NOW - 9 * DAY)))
recon_adj.note(cx, recon_auto.SITE_AUTO, ("exchange", autofix.auto_ns("okx"), autofix.auto_sid("TKP", pair_b0), 0), "auto_out")
cx.execute("UPDATE raw_observations SET observed_at=? WHERE kind='adj_why'", (NOW - 9 * DAY,))
cx.commit()
rows, doc = run(values={"okx": 1_000_000.0}, px={"TKP": 100.0})
tail = [r for r in of(rows, "TKP", "K7") if r["bts"] == NOW - DAY]
chk(len(tail) == 1 and tail[0]["pair"] is None and tail[0]["cls"] == "unexplained"
    and doc["warn_n"] == 1 and doc["auto"]["usd7"] == 0.0 and doc["check"]["tg"] is True,
    "C7 자동 경고 만료 뒤 후속 -$2,000은 별도 노랑·텔레그램 대상", (tail, doc["auto"], doc["warn_n"]))

T.finish()
