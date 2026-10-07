#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import ast
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import common
import search_index as si
from _search_samples import SAMPLES

chk = T.chk

KST = timezone(timedelta(hours=9))
TODAY = datetime(2026, 10, 6, 1, 0, tzinfo=KST)
WSRC = open(os.path.join(T.SRC, "web.py"), encoding="utf-8").read()

m9 = re.search(r"^\s*_nopid9 = (lambda e9: .*?)(?:\s+#.*)?$", WSRC, re.M)
nopid = eval(m9.group(1)) if m9 else None
keys = set(re.findall(r'\["events"\]\[-1\]\["(_\w+)"\]', WSRC))
keys |= set(re.findall(r'"(_ts|_pid)": ', WSRC[WSRC.find("def ev(flow, ts, k, d, q, a, tx"):][:1500]))
keys |= set(re.findall(r'pos_hid9\.append\(dict\(e9, [^)]*?(_\w+)=', WSRC))
keys |= set(re.findall(r'e0\["(_\w+)"\] = ', WSRC))
ALLOW = {"_ts", "_gid", "_pay", "_conv"}
chk("_tax" in keys and "_cmp" in keys and "_pid" in keys, "H (전제) web.py 기록 '_' 재료 키 목록에 _tax·_cmp·_pid 가 잡힘", sorted(keys))
if nopid:
    tax_row = {"sold": "2026-09-01", "sym": "XQQ", "acq": "$1.00", "disp": "$2.00", "_acq": 1.0, "_disp": 2.0, "_fee": 0.1}
    e = {"t": "09-01 10:00", "k": "온체인 매도", "d": "Base · 스왑", "q": "1", "a": "$2.00", "tx": "0x3c7e…cd34", "src": "w:0x" + "ab" * 20, "hide": "격리(스팸) 자산", "hideKind": "scam"}
    for k9 in keys:
        e[k9] = tax_row if k9 == "_tax" else ("x" if k9 != "_ts" else 1)
    out = nopid(e)
    left = sorted(k9 for k9 in out if k9.startswith("_") and k9 not in ALLOW)
    chk(not left, "H 부가 기록 응답(extraEvents·extraEventsHidden — _nopid9) = 금액·손익·원장 재료 '_' 키 없음(_tax 포함 · 목록 전부)", left)
    chk(all(v is not tax_row for v in out.values()) and "_acq" not in json.dumps(out, ensure_ascii=False, default=str),
        "H 응답 기록이 세금 명세 행을 참조하지 않음(spamguard.annotate 가 응답을 고쳐도 세금 행 원본 그대로)")
else:
    chk(False, "H _nopid9 람다를 web.py 에서 못 찾음")
n_strip = len(re.findall(r'\{k9?: v9? for k9?, v9? in (?:e9?|r9?)\.items\(\) if not k9?\.startswith\("_"\)\}', WSRC))
chk(n_strip >= 8, f"H 같은 종류: 기록·세금 행을 내보내는 경로 = '_' 키 전부 떼는 꼴 {n_strip}곳(카드 events · day_events 3 · 영수증 2 · 전환 · taxRows · 세금 쪽)", n_strip)
D1 = "2026-09-01"
ts1 = int(datetime(2026, 9, 1, 10, 0, tzinfo=KST).timestamp())
tr = {"_disp": 300.0, "_acq": 100.0, "_fee": 0.0}
eh = {"k": "온체인 매도", "d": "Base · 스왑", "q": "1", "a": "$300.00", "tx": "0xaaaa…bbbb", "src": "w:0x" + "ab" * 20, "sym": "XQQ", "_tax": tr, "hide": "격리(스팸) 자산", "hideKind": "scam"}
ev = dict(eh)
ev.pop("hide")
ev.pop("hideKind")
CN0 = {"base": "Base", "eth": "Ethereum"}
dd = si.docs_events({D1: [(ts1, "hidden", eh, None), (ts1 + 60, "pos", ev, ("gX", "XQQ", "Base"))]}, {"gX": {D1: 55.0}}, CN0, D1)
pn = {d9["spam"]: d9["pnl"] for d9 in dd}
chk(pn.get(True) is None and pn.get(False) == 200.0, "H 같은 종류: 색인 숨긴 매도 = 손익 없음(pnl: 조건·손익 패싯에 안 걸림) · 보이는 매도 = 건별 200", pn)
s1 = si._day_sig([(ts1, "hidden", eh, None)], {}, D1)
s2 = si._day_sig([(ts1, "hidden", dict(eh, _tax={"_disp": 9.0, "_acq": 1.0, "_fee": 0.0}), None)], {}, D1)
chk(s1 == s2, "H 그날 서명 = 색인과 같은 규칙(숨긴 기록의 _tax 는 서명 재료 아님)")

SM = SAMPLES
m9 = re.search(r"^CHAIN_NAME = (\{.*?\})\n", WSRC, re.M | re.S)
CN = ast.literal_eval(m9.group(1)) if m9 else {}
common.fill_chain_table(CN)
NM = si.Names(CN)


def canon(q):
    p = si.parse_query(q, TODAY, names=NM)
    out = set()
    for k9, v9 in p["filters"].items():
        out.add(f"{k9}:{si._addr_norm(v9) if k9 in ('addr', 'tx') else v9}")
    for k9, vs in (p.get("neg") or {}).items():
        for v9 in vs:
            out.add(f"-{k9}:{v9}")
    return out


bad = [(x["q"], sorted(x["srv"]), sorted(canon(x["q"]))) for x in SM["conds"] if set(x["srv"]) != canon(x["q"])]
chk(not bad, f"C 조건 해석(서버 parse_query) = 공용 표본 {len(SM['conds'])}개(화면 srvParamsOf 와 같은 정해진 꼴)", bad)
al = [a for a in si.CHAIN_ALIAS if not any(re.search(r"(?i)(^|\s|-)chain:" + re.escape(a) + r"(\s|$)", x["q"]) for x in SM["conds"])]
one = [a for a in al if " " not in a]
chk(not one, "C 서버 체인 별칭(한 낱말) 전부 표본에 있음", one)
JS = open(os.path.join(T.ROOT, "web", "v2", "search.js"), encoding="utf-8").read()
mj = re.search(r"const CHAIN_ALIAS = \{(.*?)\};", JS, re.S)
jsal = dict(re.findall(r"'?([^\s',:{}]+(?: [^\s',:{}]+)*)'?: '([a-z0-9_]+)'", mj.group(1))) if mj else {}
miss = {a: k for a, k in si.CHAIN_ALIAS.items() if jsal.get(a) != k}
chk(not miss, "C 화면 CHAIN_ALIAS = 서버 CHAIN_ALIAS 별칭 전부(여러 낱말 포함 · 같은 키)", miss)


def ev_types(k, d):
    et = si._ev_type(k, d)
    return [et] + (["sell"] if et == "swap" and "매도" in k else ["buy"] if et == "swap" and "매수" in k else [])


bad = [(x["k"], x["d"], x["t"], ev_types(x["k"], x["d"])) for x in SM["evtypes"] if ev_types(x["k"], x["d"]) != x["t"]]
chk(not bad, f"E 기록 종류(서버 _ev_type + 스왑 매도·매수) = 공용 표본 {len(SM['evtypes'])}개", bad)
bad = []
for i, x in enumerate(SM["evchains"]):
    e9 = {"k": "기록", "d": x["d"], "q": "", "a": "—", "tx": "—", "src": x["src"], "sym": "XQQ"}
    d9 = si.docs_events({D1: [(ts1 + i, "pos", e9, ("gX", "XQQ", x["card"]) if x["card"] else None)]}, {}, CN, D1)
    if d9[0]["cks"] != x["cks"]:
        bad.append((x["d"], x["src"][:8], x["card"], x["cks"], d9[0]["cks"]))
chk(not bad, f"EC 기록 체인(서버 docs_events cks) = 공용 표본 {len(SM['evchains'])}개(출처 w:<주소> 는 체인 아님)", bad)

A, B, C9 = "0x" + "a1" * 20, "0x" + "b2" * 20, "0x" + "c3" * 20
SA, SB = "Zq7Kp2" * 6 + "Aa", "Hb3Cx9" * 6 + "Bb"
LP = os.path.join(T.TMP, "ledger.db")


def mk_ledger(path):
    lc = sqlite3.connect(path)
    lc.executescript("""CREATE TABLE assets (asset_id INTEGER PRIMARY KEY, symbol TEXT);
    CREATE TABLE postings (posting_id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT, source_ns TEXT, source_id TEXT, event_ts INTEGER, asset_id INTEGER,
      location TEXT, event TEXT, leg_kind TEXT, cost_usd TEXT);""")
    lc.executemany("INSERT INTO assets VALUES (?, ?)", [(1, "ETH"), (2, "SOL")])
    t0 = int(datetime(2026, 9, 2, 9, 0, tzinfo=KST).timestamp())
    rows = [
        ("base", "0x" + "11" * 32, t0, 1, f"wallet:base:{A}", "TRANSFER_SELF", "move_out"),
        ("base", "0x" + "11" * 32, t0, 1, f"wallet:base:{B.upper().replace('0X', '0x')}", "TRANSFER_SELF", "move_in"),
        ("base", "0x" + "22" * 32, t0 + 60, 1, f"wallet:base:{A}", "TRANSFER_OUT", "move_out"),
        ("base", "0x" + "33" * 32, t0 + 120, 1, f"wallet:base:{B}", "TRANSFER_IN", "acq"),
        ("base", "0x" + "44" * 32, t0 + 180, 1, f"wallet:base:{C9}", "TRANSFER_IN", "acq"),
        ("sol", "5Sig" + "x" * 80, t0 + 240, 2, f"wallet:sol:{SA}", "TRANSFER_SELF", "move_out"),
        ("sol", "5Sig" + "x" * 80, t0 + 240, 2, f"wallet:sol:{SB}", "TRANSFER_SELF", "move_in"),
    ]
    lc.executemany("INSERT INTO postings (source_kind, source_ns, source_id, event_ts, asset_id, location, event, leg_kind, cost_usd) VALUES ('chain_tx', ?, ?, ?, ?, ?, ?, ?, '10')", rows)
    lc.commit()
    lc.close()


mk_ledger(LP)
WALDOCS = [{"kind": "wallet", "key": "w:" + si._addr_norm(a), "grp": "st:wallet", "title": al, "sub": "Base", "body": "지갑 " + al, "addr": a}
           for al, a in (("에이", A), ("비지갑", B), ("씨지갑", C9), ("솔에이", SA), ("솔비", SB))]


def build_ix(path):
    ix = si.Index(path, sleep=lambda s: None)
    ix.replace_groups(["st:wallet"], WALDOCS)
    with ix.tx() as c9:
        c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(si.ROWV),))
        c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('built', '1')")
    return ix


WP = os.path.join(T.TMP, "w106.db")
IXW = build_ix(WP)
lc = sqlite3.connect(f"file:{LP}?mode=ro", uri=True)
IXW.replace("kind = 'tx'", (), si.ledger_tx_docs(lc, NM))
lc.close()


def S(q, path=WP):
    try:
        return si.search(q, today=TODAY, path=path, budget_s=5, limit=50, kinds=["tx"])
    except Exception as e:
        return {"_exc": f"{type(e).__name__}: {e}"}


def txs(r):
    g = next((g for g in (r.get("groups") or []) if g["kind"] == "tx"), None) if isinstance(r, dict) else None
    return sorted(str(i["tx"])[:4] for i in (g or {}).get("items") or [])


def wal_suite(tag):
    r = S("wallet:비지갑")
    chk(txs(r) == ["0x11", "0x33"], f"W{tag} wallet:B = A→B 이동(B 가 둘째 지갑) + B 만 tx", [txs(r), r.get("ignored") if isinstance(r, dict) else r])
    r = S("coin:ETH -wallet:비지갑")
    chk(txs(r) == ["0x22", "0x44"], f"W{tag} -wallet:B = A→B 이동도 빠짐(남은 것 A 만·C 만)", txs(r))
    r = S("wallet:에이")
    chk(txs(r) == ["0x11", "0x22"], f"W{tag} wallet:A(첫 지갑) = 종전처럼", txs(r))
    r = S("coin:ETH -wallet:에이 -wallet:비지갑")
    chk(txs(r) == ["0x44"], f"W{tag} 빼기 둘 = C 만", txs(r))
    r = S("wallet:솔비")
    chk(txs(r) == ["5Sig"], f"W{tag} 솔라나 wallet:SB(둘째 지갑) = SA→SB 이동", txs(r))


wal_suite("")
if hasattr(si, "WALLET_IN_MAX"):
    keep = si.WALLET_IN_MAX
    si.WALLET_IN_MAX = 0
    wal_suite("(json_each)")
    si.WALLET_IN_MAX = keep
else:
    chk(False, "W 긴 지갑 목록(json_each) 경로 없음 — 건너뜀 = 통과 아님")
for q, want, lab in ((f"addr:{B[:10]}", ["0x11", "0x33"], "addr:B 앞부분"), (B, ["0x11", "0x33"], "전체 주소 B(정확)"), (B.upper().replace("0X", "0x"), ["0x11", "0x33"], "전체 주소 B 대문자"),
                     (B[:8], ["0x11", "0x33"], "0x 앞부분 B"), (B[2:10], ["0x11", "0x33"], "0x 없는 16진 앞부분 B"), (B[:6] + "..." + B[-4:], ["0x11", "0x33"], "줄인 주소 B(앞…뒤)"),
                     (SB[:8], ["5Sig"], "솔라나 앞부분 SB"), (SB, ["5Sig"], "솔라나 전체 주소 SB"), (SB[:6] + "…" + SB[-4:], ["5Sig"], "솔라나 줄인 주소 SB"),
                     (f"addr:{A[:10]}", ["0x11", "0x22"], "addr:A 앞부분(종전처럼)")):
    r = S(q)
    chk(txs(r) == want, f"W 같은 종류 {lab} = 그 지갑이 참여한 tx 전부(첫 지갑 아니어도)", [q, txs(r)])
IXW.replace_groups(["ev:" + D1], [{"kind": "event", "key": "ev:x1", "grp": "ev:" + D1, "title": "ETH 전송", "sub": "", "sym": "ETH", "addr": A, "ts": ts1, "date": D1, "etype": "transfer", "tys": ["transfer"]},
                                  {"kind": "event", "key": "ev:x2", "grp": "ev:" + D1, "title": "ETH 전송", "sub": "", "sym": "ETH", "addr": B, "ts": ts1 + 1, "date": D1, "etype": "transfer", "tys": ["transfer"]}])
r = si.search("wallet:비지갑", today=TODAY, path=WP, budget_s=5, limit=50, kinds=["event"])
ge = next((g for g in r.get("groups") or [] if g["kind"] == "event"), None)
chk(ge and [i["id"] for i in ge["items"]] == ["ev:x2"], "W 기록 종류 wallet:B = 그 지갑 기록만(지갑 칸 하나)", ge and [i["id"] for i in ge["items"]])
OP = os.path.join(T.TMP, "old106.db")
IXO = build_ix(OP)
lc = sqlite3.connect(f"file:{LP}?mode=ro", uri=True)
IXO.replace("kind = 'tx'", (), si.ledger_tx_docs(lc, NM))
lc.close()
with IXO.tx() as c9:
    c9.execute("DROP TABLE tg")
r = S("wallet:비지갑", OP)
chk(isinstance(r, dict) and r.get("ok") and txs(r) == ["0x33"], "W 패싯 표 없는 옛 색인 = 종전 addr 칸 조건(오류 없음 · 첫 지갑만)", txs(r) if isinstance(r, dict) else r)

MP = os.path.join(T.TMP, "m106.db")
build_ix(MP)
real_docs, real_v = si.ledger_tx_docs, si.TX_AGG_V


def old_docs(lc9, names, only=None):
    for d9 in real_docs(lc9, names, only):
        d9.pop("wals", None)
        yield d9


si.ledger_tx_docs, si.TX_AGG_V = old_docs, 2
I1 = si.Indexer(path=MP, ledger_path=LP, chain_names=CN, sleep=lambda s: None)
I1.feed_ledger()
si.ledger_tx_docs, si.TX_AGG_V = real_docs, real_v
r0 = S("wallet:비지갑", MP)
chk(txs(r0) == ["0x33"], "M (전제) 옛 행만(패싯 없음) = 종전처럼 addr 칸(첫 지갑)으로만 — B 만 tx · 새 조건이 옛 행에서 오류 없음", txs(r0))
c9 = sqlite3.connect(MP)
n_w0 = c9.execute("SELECT count(*) FROM tg WHERE t LIKE 'w:%'").fetchone()[0]
c9.close()
I2 = si.Indexer(path=MP, ledger_path=LP, chain_names=CN, sleep=lambda s: None)
I2.feed_ledger()
c9 = sqlite3.connect(MP)
n_w1 = c9.execute("SELECT count(*) FROM tg WHERE t LIKE 'w:%'").fetchone()[0]
agg = json.loads(c9.execute("SELECT v FROM meta WHERE k = 'tx:agg'").fetchone()[0])
c9.close()
chk(n_w0 == 0 and n_w1 == 7 and agg.get("v") == real_v, f"M 배포 뒤 첫 회차 = 집계 규칙 번호가 달라 tx 전부 다시 대조 → 참여 지갑 패싯 {n_w0} → {n_w1}", [n_w0, n_w1, agg.get("v")])
r1 = S("coin:ETH -wallet:비지갑", MP)
chk(txs(r1) == ["0x22", "0x44"], "M 다시 대조 뒤 -wallet:B = A→B 이동도 빠짐", txs(r1))

T.finish()
