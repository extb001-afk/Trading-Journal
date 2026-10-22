#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check, Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import address_codec as ac  # noqa: E402
import btc_descriptor  # noqa: E402
import chain_registry as reg  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402

TS = 1_700_000_000
TR1, TR2 = N.OWN["tron"]
TR1_D = ac.tron_display(TR1)
SUI1 = N.OWN["sui"][0]
TON1 = N.OWN["ton"][0]
TON1_F = ac.ton_friendly(TON1)
DESC = btc_descriptor.descriptor_from_xpub(N.BTC_XPUB, "wpkh")
BTC_A = reg.btc_source({"mode": "address", "address": N.BTC_ADDR})["key"]
BTC_HD = reg.btc_source({"mode": "descriptor", "descriptor": DESC})["key"]
XPUB_BODY = N.BTC_XPUB[4:40]
W_EVM = _ingest.W
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["wallets"] = [dict(w, chain=w.get("chain") or ("sol" if w.get("type") == "sol" else "eth")) for w in cfg["wallets"]]
for w in cfg["wallets"]:
    w["label"] = "SameName" if w.get("type") == "sol" else "MainEvm"
CW = [{"chain": "tron", "address": TR1_D, "label": "AuditTronOne"},
      {"chain": "tron", "address": ac.tron_display(TR2), "label": "SameName"},
      {"chain": "sui", "address": SUI1, "label": "AuditSuiOne"},
      {"chain": "ton", "address": TON1_F, "label": "AuditTonOne"},
      {"chain": "btc", "mode": "address", "address": N.BTC_ADDR, "label": "AuditBtcAddr"},
      {"chain": "btc", "mode": "descriptor", "descriptor": DESC, "label": "AuditBtcHd"}]
cfg["chain_wallets"] = CW
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())


def feed(stream, recs):
    c._drain_stream(stream, Reader([json.loads(json.dumps(r)) for r in recs]), 0, 0)


U_TR = ["d1" * 32, "d2" * 32, "d3" * 32]
U_TR2 = "d4" * 32
feed("tron", [N.rec("tron", u, TS + i * 3600, [(TR1, "native", 1_000_000 * (i + 1))]) for i, u in enumerate(U_TR)]
     + [N.rec("tron", U_TR2, TS + 9000, [(TR2, "native", 2_000_000)])])
U_SUI = "Sx9" + "b" * 40
feed("sui", [N.rec("sui", U_SUI, TS + 100, [(SUI1, "native", 5_000_000_000)])])
H_TON = "e2" * 32
U_TON = TON1 + ".7." + H_TON
feed("ton", [N.rec("ton", U_TON, TS + 200, [(TON1, "native", 7_000_000_000)], txhash=H_TON)])
U_BA, U_BH = "e3" * 32, "e4" * 32
feed("btc", [N.rec("btc", U_BA, TS + 300, [(BTC_A, "native", 10_000)]), N.rec("btc", U_BH, TS + 400, [(BTC_HD, "native", 20_000)])])
c.conn.commit()
n_led = c.conn.execute("SELECT COUNT(DISTINCT source_id) FROM postings WHERE source_ns IN ('tron','sui','ton','btc')").fetchone()[0]
check("전제: 새 체인 원장 거래 8건", n_led == 8, n_led)
c.conn.close()

import acct_norm  # noqa: E402
import pricing  # noqa: E402
import search_index as si  # noqa: E402
import web  # noqa: E402


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c9, ca: False
web.Spot.ex_pending = lambda self, ex: False
SPATH = os.path.join(T.TMP, "search_wal.db")
H_EVM = "0x" + "e1" * 32
EVM_DOC = {"kind": "tx", "key": "tx:eth:" + H_EVM, "grp": "tx:eth", "title": "tx evm", "sub": "", "body": "ETH", "date": "2023-11-14",
           "ts": TS + 50, "chain": "eth", "etype": "transfer", "addr": W_EVM, "tx": H_EVM, "syms": ["ETH"], "chains": ["eth"], "wals": [W_EVM]}
IX = {}


def build_and_index():
    web.BUILDER = b = web.StateBuilder()
    try:
        st = b.build()
    except Exception as e:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        st = {"_exc": f"{type(e).__name__}: {e}"}
    if "ix" not in IX:
        IX["ix"] = si.Indexer(state_fn=None, chain_names=web.CHAIN_NAME, path=SPATH, ledger_path=paths.DB_PATH, sleep=lambda s9: None)
    ixr = IX["ix"]
    ixr.state_fn = lambda: (st, getattr(b, "_day_idx", None))
    ixr.tick()
    ixr.ix._insert([EVM_DOC])
    return b, st


def q(text):
    return si.search(text, path=SPATH, budget_s=5)


def ids(r, kind=None):
    return sorted(i.get("id") for g in (r.get("groups") or []) if kind is None or g.get("kind") == kind for i in g.get("items") or [])


def wal_docs():
    return list(si.Index(SPATH, sleep=lambda s9: None).open().execute("SELECT key, title, sub, body, addr FROM docs WHERE kind = 'wallet'"))


b, st = build_and_index()
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
TXK = ["tx:tron:" + u for u in U_TR]

want = {"AuditTronOne": TR1, "AuditSuiOne": SUI1, "AuditTonOne": TON1, "AuditBtcAddr": BTC_A, "AuditBtcHd": BTC_HD}
got = {}
for nm, k9 in want.items():
    r = q(nm)
    got[nm] = [(i.get("addr")) for g in r.get("groups") or [] if g.get("kind") == "wallet" for i in g.get("items") or []]
check("W1 이름 검색 = 그 새 체인 지갑 문서(addr = 원장 키 · Tron·Sui·TON·BTC 주소·BTC HD)",
      all(got[nm] == [k9] for nm, k9 in want.items()), got)
wd = {r9[4]: r9 for r9 in wal_docs()}
check("W1 지갑 문서 제목 = 이름 + 줄인 표시 꼴(T…·UQ…·bc1…) · HD = 이름 + 줄인 지갑 id",
      TR1 in wd and wd[TR1][1] == "AuditTronOne " + si._short(TR1_D) and wd.get(TON1, ("",) * 5)[1] == "AuditTonOne " + si._short(TON1_F)
      and wd.get(BTC_A, ("",) * 5)[1] == "AuditBtcAddr " + si._short(N.BTC_ADDR) and wd.get(BTC_HD, ("",) * 5)[1] == "AuditBtcHd " + si._short(BTC_HD),
      {k[:8]: v[1] for k, v in wd.items()})
check("W1 신원 = (체인, 네트워크, 원장 키) 문서 키", TR1 in wd and wd[TR1][0] == "w:tron:mainnet:" + TR1 and wd.get(BTC_HD, ("",))[0] == "w:btc:mainnet:" + BTC_HD,
      {k[:8]: v[0] for k, v in wd.items()})
r = q(TR1_D)
check("W1 Tron 표시 주소(T…) 검색 = 지갑 문서 + 그 지갑 거래(종전 거래 대조 유지)",
      ids(r, "wallet") == ["w:tron:mainnet:" + TR1] and ids(r, "tx") == TXK, (ids(r, "wallet"), ids(r, "tx")))

r = q("wallet:AuditTronOne after:2020-01-01")
check("W2 wallet:AuditTronOne after:2020-01-01 = 조건 유지(ignored 없음)", not r.get("ignored"), r.get("ignored"))
check("W2 … 결과 = 그 지갑 거래 3건만(EVM 대조 거래·다른 Tron 지갑 없음)", ids(r, "tx") == TXK, ids(r, "tx"))
r = q("wallet:AuditTronOne before:2020-01-01")
check("W2 wallet: + 범위 밖 날짜 = 0건(조건 둘 다 적용)", ids(r, "tx") == [] and not r.get("ignored"), (ids(r, "tx"), r.get("ignored")))

r = q("-wallet:AuditTronOne after:2020-01-01")
t3 = ids(r, "tx")
check("W3 -wallet:AuditTronOne = 그 지갑 거래 빠짐 · 나머지(EVM·다른 체인) 남음",
      not r.get("ignored") and not set(TXK) & set(t3) and "tx:eth:" + H_EVM in t3 and "tx:tron:" + U_TR2 in t3, (t3, r.get("ignored")))
per = {nm: ids(q("wallet:" + nm), "tx") for nm in ("AuditSuiOne", "AuditTonOne", "AuditBtcAddr", "AuditBtcHd")}
check("W3 wallet: Sui·TON·BTC 주소·BTC HD = 각 지갑 거래 1건",
      per == {"AuditSuiOne": ["tx:sui:" + U_SUI], "AuditTonOne": ["tx:ton:" + U_TON], "AuditBtcAddr": ["tx:btc:" + U_BA],
              "AuditBtcHd": ["tx:btc:" + U_BH]}, per)
per2 = {a9: ids(q("wallet:" + a9), "tx") for a9 in (TR1_D, TON1_F, N.BTC_ADDR)}
check("W3 wallet:<표시 꼴 주소>(T…·UQ…·bc1…) = 원장 키로 풀어 그 지갑 거래",
      per2 == {TR1_D: TXK, TON1_F: ["tx:ton:" + U_TON], N.BTC_ADDR: ["tx:btc:" + U_BA]}, per2)

blob = json.dumps(wal_docs(), ensure_ascii=False) + json.dumps([f.get("chainWalletRows"), f.get("walletAlias"), f.get("walletRows")], ensure_ascii=False)
with open(SPATH, "rb") as f9:
    raw9 = f9.read()
check("W4 디스크립터·xpub 원문(가린 꼴 포함) = 검색 문서·지갑 목록·별명에 없음",
      XPUB_BODY not in blob and "xpub" not in blob and "wpkh(" not in blob and ac.btc_mask(DESC) not in blob and XPUB_BODY.encode() not in raw9,
      [x for x in ("xpub", "wpkh(", XPUB_BODY) if x in blob])

r = q("wallet:SameName")
check("W5 같은 별명(솔라나 + Tron) = 둘 다 대상(ignored 없음) · Tron 둘째 지갑 거래", not r.get("ignored") and ids(r, "tx") == ["tx:tron:" + U_TR2],
      (ids(r, "tx"), r.get("ignored")))
check("W5 같은 별명 이름 검색 = 지갑 문서 2개(솔라나 · Tron)", sorted(x for x in (i.get("addr") for g in q("SameName").get("groups") or []
                                                                         if g.get("kind") == "wallet" for i in g.get("items") or [])) == sorted([_ingest.SOLW, TR2]),
      ids(q("SameName"), "wallet"))

wr = f.get("walletRows") or []
check("W6 walletRows(설정 지갑 목록 재료) = EVM·솔라나 2줄 그대로(새 체인 = 설정 목록이 따로 그림 — 두 번 안 나옴)",
      sorted(w9.get("key") for w9 in wr) == sorted([W_EVM, _ingest.SOLW]), [w9.get("key") for w9 in wr])
r = q("MainEvm")
check("W6 EVM 지갑 이름 검색 그대로(문서 키 w:<주소>)", ids(r, "wallet") == ["w:" + W_EVM], ids(r, "wallet"))
check("W6 wallet:MainEvm = EVM 대조 거래만", ids(q("wallet:MainEvm"), "tx") == ["tx:eth:" + H_EVM], ids(q("wallet:MainEvm"), "tx"))
wa = f.get("walletAlias") or {}
check("W6 walletAlias: EVM·솔라나 그대로 + 새 체인 원장 키 → 이름(HD = 이름 · 원문 없음)",
      wa.get(W_EVM) == "MainEvm" and wa.get(_ingest.SOLW) == "SameName" and wa.get(TR1) == "AuditTronOne" and wa.get(TON1) == "AuditTonOne"
      and wa.get(BTC_HD) == "AuditBtcHd" and wa.get(BTC_A) == "AuditBtcAddr", wa)
check("W6 addr_label(원장 위치 → 내 지갑 이름) = 새 체인 원장 키도", b.addr_label.get(TR1) == "AuditTronOne" and b.addr_label.get(SUI1) == "AuditSuiOne"
      and b.addr_label.get(W_EVM) == "MainEvm", {k[:8]: v for k, v in b.addr_label.items()})

cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"][0]["label"] = "AuditTronRen"
json.dump(cfg, open(CFG_PATH, "w"))
b, st = build_and_index()
r_old, r_new = q("wallet:AuditTronOne"), q("wallet:AuditTronRen after:2020-01-01")
check("W5 이름 바꾸기 = 새 이름으로 거래 3건 · 옛 이름은 지갑 없음(ignored)",
      ids(r_new, "tx") == TXK and not r_new.get("ignored") and r_old.get("ignored") and ids(q("AuditTronOne"), "wallet") == [],
      (ids(r_new, "tx"), r_old.get("ignored"), ids(q("AuditTronOne"), "wallet")))
cfg["chain_wallets"] = [w9 for w9 in cfg["chain_wallets"] if w9.get("label") != "AuditTronRen"]
json.dump(cfg, open(CFG_PATH, "w"))
b, st = build_and_index()
check("W5 지우기 = 지갑 문서 사라짐 · 다른 새 체인 지갑 그대로",
      ids(q("AuditTronRen"), "wallet") == [] and ids(q("AuditSuiOne"), "wallet") == ["w:sui:mainnet:" + SUI1], (ids(q("AuditTronRen"), "wallet"),))
check("바깥 연결 0", not T.NET_TRIES, T.NET_TRIES)
T.finish()
