#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import time
from datetime import datetime, timedelta, timezone

import search_index as si
from _search_samples import SAMPLES

chk = T.chk

KST = timezone(timedelta(hours=9))
TODAY = datetime(2026, 10, 6, 1, 0, tzinfo=KST)


def tok_class(q):
    p = si.parse_query(q, TODAY)
    if p["exact"]:
        kd, v = p["exact"][0]
        return ("addr" if kd == "addr" else "tx") if v.startswith("0x") else "b58x"
    if p.get("short"):
        return "shorthex" if p["short"][0][2] else "shortb58"
    if p["hexp"]:
        return "hexp"
    if p.get("date"):
        return "date"
    if any("날짜" in str(x.get("why")) or "범위" in str(x.get("why")) for x in p["ignored"]):
        return "baddate"
    if p.get("numtext"):
        return "numtext"
    if p.get("amt_near") is not None:
        return "amount"
    if p.get("tickers"):
        return "ticker"
    if p.get("b58p"):
        return "b58p"
    if p.get("alias"):
        return "alias"
    return "text"


SM = SAMPLES
bad = [(x["q"], x["k"], tok_class(x["q"])) for x in SM["tokens"] if tok_class(x["q"]) != x["k"]]
chk(not bad, f"P 서버 낱말 판별 = 공용 표본 {len(SM['tokens'])}개 그대로(다른 것 {len(bad)})", bad)
badm = []
for x in SM["multi"]:
    p = si.parse_query(x["q"], TODAY)
    if list(p.get("tickers") or []) != x["ticks"] or list(p.get("b58p") or []) != x["b58p"]:
        badm.append((x["q"], p.get("tickers"), p.get("b58p")))
chk(not badm, f"P 서버 여러 낱말 질의의 티커·솔라나 앞부분 = 표본 {len(SM['multi'])}개 그대로", badm)

N = 21000
OP = os.path.join(T.TMP, "off_search.db")
IXO = si.Index(OP, sleep=lambda s: None)
IXO.replace_groups(["g:o"], [{"kind": "event", "key": f"ev:o:{i:05d}", "grp": "g:o", "title": "QQQ 거래소 매수", "sub": f"합성 체결 {i}", "sym": "QQQ",
                              "etype": "buy", "ts": 1_700_000_000 + i, "date": "2026-09-01", "tys": ["buy"]} for i in range(N)])
with IXO.tx() as c9:
    c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(getattr(si, "ROWV", 0)),))
    c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('built', '1')")


def SO(q, **kw):
    try:
        return si.search(q, today=TODAY, path=OP, budget_s=5, **kw)
    except Exception as e:
        return {"_exc": f"{type(e).__name__}: {e}"}


def g_of(r, k="event"):
    return next((g for g in (r.get("groups") or []) if g["kind"] == k), None) if isinstance(r, dict) else None


def meta(g):
    return g and {k: g[k] for k in g if k != "items"}


ga = g_of(SO("coin:QQQ", limit=50, offset=20000))
gb = g_of(SO("coin:QQQ", limit=50, offset=20030))
ida = [i["id"] for i in (ga or {}).get("items") or []]
idb = [i["id"] for i in (gb or {}).get("items") or []]
chk(gb and gb.get("offset") == 20030 and len(idb) == 50 and idb[:20] == ida[30:] and gb["more"] is True,
    "O offset 20,030 = 그 자리부터 50건(20,000 으로 잘려 같은 쪽 반복 아님) · 남았으니 more", [meta(gb), idb[:2], ida[30:32]])
seen, off, pages, rep = set(), 0, 0, 0
while pages < 1000:
    g9 = g_of(SO("coin:QQQ", limit=50, offset=off))
    if not g9:
        break
    ids = [i["id"] for i in g9["items"]]
    rep += len(set(ids) & seen)
    seen |= set(ids)
    pages += 1
    if not g9["more"]:
        break
    off += len(ids)
chk(len(seen) == N and rep == 0, f"O '더 보기' 끝까지 = {N:,}건 전부 · 겹침 0(쪽 {pages} · 받은 {len(seen):,} · 겹침 {rep})")
gl = g_of(SO("coin:QQQ", limit=50, offset=N - 10))
chk(gl and len(gl["items"]) == 10 and gl["more"] is False, "O 마지막 쪽(20,990) = 남은 10건 · more 없음", meta(gl))
for bad_off in (N + 5, 10 ** 30, "9" * 5000, "-5", "abc"):
    r9 = SO("coin:QQQ", limit=50, offset=bad_off)
    g9 = g_of(r9)
    ok9 = isinstance(r9, dict) and r9.get("ok") and "_exc" not in r9
    if g9 and str(bad_off) not in ("-5", "abc") and len(str(bad_off)) < 4300:
        ok9 = ok9 and not g9["items"] and g9["more"] is False
    elif g9:
        ok9 = ok9 and (g9["offset"] != bad_off or not g9["items"])
    chk(ok9, f"O 엉뚱한 offset({str(bad_off)[:12]}{'…' if len(str(bad_off)) > 12 else ''}) = 예외 없음 · 같은 쪽을 다음 쪽인 척 주지 않음", meta(g9) if g9 else r9)
tm = {}
for q9 in ("coin:QQQ", "QQQ", "QQQ 매수", "type:buy"):
    ms = []
    for _ in range(3):
        t1 = time.perf_counter()
        r9 = si.search(q9, today=TODAY, path=OP, limit=50, offset=N - 50)
        ms.append((time.perf_counter() - t1) * 1000)
    ms.sort()
    g9 = g_of(r9)
    tm[q9] = (round(ms[1], 1), bool(r9.get("partial")), len(g9["items"]) if g9 else None)
    print(f"     정보: 깊은 offset {N - 50:,} {q9!r:14} {ms[1]:7.1f} ms · partial {bool(r9.get('partial'))} · 항목 {tm[q9][2]}")
chk(all(not v[1] and v[2] == 50 and v[0] < 800 for v in tm.values()), "O 2만 건 깊은 offset = 기본 시간 예산(0.8초) 안 · 일부만 아님", tm)

WP = os.path.join(T.TMP, "wal_search.db")
IXW = si.Index(WP, sleep=lambda s: None)
WALS = [("콜드%02d" % i, "0x" + ("%02x" % i) * 20) for i in range(1, 26)] + [("따뜻", "0x" + "ee" * 20), ("핫", "0x" + "dd" * 20)]
docs = [{"kind": "wallet", "key": "w:" + a, "grp": "st:wallet", "title": al + " " + a[:6] + "…" + a[-4:], "sub": "Ethereum", "body": "지갑 " + al, "addr": a} for al, a in WALS]
docs += [{"kind": "event", "key": f"ev:w:{j}", "grp": "st:wallet", "title": "RRR 온체인 매수", "sub": "Ethereum · 스왑", "sym": "RRR", "etype": "buy", "addr": a,
          "ts": 1_700_000_000 + j, "date": "2026-09-01", "tys": ["buy"]} for j, (al, a) in enumerate(WALS)]
IXW.replace_groups(["st:wallet"], docs)
with IXW.tx() as c9:
    c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(getattr(si, "ROWV", 0)),))
    c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('built', '1')")


def SW(q, **kw):
    try:
        return si.search(q, today=TODAY, path=WP, budget_s=5, limit=50, **kw)
    except Exception as e:
        return {"_exc": f"{type(e).__name__}: {e}"}


def wal_checks(tag):
    r = SW("wallet:콜드")
    gw, ge = g_of(r, "wallet"), g_of(r, "event")
    chk(gw and gw["n"] == 25 and ge and ge["n"] == 25, f"W{tag} wallet:콜드 = 콜드01~25 지갑·그 기록 25건 전부(20개 컷 아님)", [meta(gw), meta(ge), r.get("ignored") if isinstance(r, dict) else r])
    r = SW("coin:RRR -wallet:콜드")
    ge = g_of(r, "event")
    ad = sorted(i["addr"] for i in (ge or {}).get("items") or [])
    chk(ge and ge["n"] == 2 and ad == sorted([WALS[-2][1], WALS[-1][1]]), f"W{tag} -wallet:콜드 = 콜드 25곳 기록 모두 빠지고 따뜻·핫 2건만", [meta(ge), ad])
    r = SW("coin:RRR -wallet:콜드 -wallet:따뜻 -wallet:콜드0 -wallet:콜드1 -wallet:콜드2")
    ge = g_of(r, "event")
    chk(ge and ge["n"] == 1 and ge["items"][0]["addr"] == WALS[-1][1], f"W{tag} 빼기 여러 개(겹치는 목록) = 핫 1건만", meta(ge))
    r = SW("wallet:콜드2")
    gw = g_of(r, "wallet")
    chk(gw and gw["n"] == 6, f"W{tag} wallet:콜드2 = 앞부분 일치 콜드20~25 6곳", meta(gw))


wal_checks("")
if hasattr(si, "WALLET_IN_MAX"):
    keep = si.WALLET_IN_MAX
    si.WALLET_IN_MAX = 3
    wal_checks("(json_each 경로)")
    si.WALLET_IN_MAX = keep
else:
    chk(False, "W 긴 지갑 목록(SQLite 변수 한도) 경로 없음 — 수정 전 코드")

T.finish()
