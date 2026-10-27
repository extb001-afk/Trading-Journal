#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import os  # noqa: E402
os.environ["TJ_BUILD_PROC"] = "off"
import _ingest  # noqa: E402,F401
from _ingest import check, Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

import address_codec as ac  # noqa: E402
import btc_descriptor  # noqa: E402
import chain_registry as reg  # noqa: E402
import config  # noqa: E402
import core  # noqa: E402

TS = 1_700_000_000
TR1 = N.OWN["tron"][0]
TR1_D = ac.tron_display(TR1)
SUI1 = N.OWN["sui"][0]
TON1 = N.OWN["ton"][0]
TON1_F = ac.ton_friendly(TON1, bounceable=False)
DESC = btc_descriptor.descriptor_from_xpub(N.BTC_XPUB, "wpkh")
BTC_A = reg.btc_source({"mode": "address", "address": N.BTC_ADDR})["key"]
BTC_HD = reg.btc_source({"mode": "descriptor", "descriptor": DESC})["key"]
BTC_ADDR2 = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
BTC_A2 = reg.btc_source({"mode": "address", "address": BTC_ADDR2})["key"]
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["wallets"] = [dict(w, chain=w.get("chain") or ("sol" if w.get("type") == "sol" else "eth")) for w in cfg["wallets"]]
cfg["chain_wallets"] = [{"chain": "tron", "address": TR1_D},
                        {"chain": "sui", "address": SUI1, "label": "SuiOne"},
                        {"chain": "ton", "address": ac.ton_friendly(TON1)},
                        {"chain": "btc", "mode": "address", "address": N.BTC_ADDR, "label": "콜드"},
                        {"chain": "btc", "mode": "descriptor", "descriptor": DESC, "label": "HdOne"},
                        {"chain": "btc", "mode": "address", "address": BTC_ADDR2}]
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())


def feed(stream, recs):
    c._drain_stream(stream, Reader([json.loads(json.dumps(r)) for r in recs]), 0, 0)


feed("tron", [N.rec("tron", "d1" * 32, TS, [(TR1, "native", 3_000_000)])])
feed("sui", [N.rec("sui", "Sx9" + "b" * 40, TS + 100, [(SUI1, "native", 5_000_000_000)])])
H_TON = "e2" * 32
feed("ton", [N.rec("ton", TON1 + ".7." + H_TON, TS + 200, [(TON1, "native", 7_000_000_000)], txhash=H_TON)])
feed("btc", [N.rec("btc", "e3" * 32, TS + 300, [(BTC_A, "native", 10_000)]), N.rec("btc", "e4" * 32, TS + 400, [(BTC_HD, "native", 20_000)]),
                N.rec("btc", "e5" * 32, TS + 500, [(BTC_A2, "native", 30_000)])])
c.conn.commit()
c.conn.close()

import acct_norm  # noqa: E402
import pricing  # noqa: E402
import web  # noqa: E402


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c9, ca: False
web.Spot.ex_pending = lambda self, ex: False

check("H1 CHAIN_NAME 새 체인 표시명", all(web.CHAIN_NAME.get(k) == v for k, v in (("tron", "Tron"), ("sui", "Sui"), ("ton", "TON"), ("btc", "Bitcoin")))
      and web.CHAIN_NAME.get("eth") == "Ethereum" and web.CHAIN_NAME.get("sol") == "Solana", {k: web.CHAIN_NAME.get(k) for k in ("tron", "sui", "ton", "btc")})

VW = {}
_vf0 = web._venue_flows30


def _vf_spy(vflow, real_loc, venue_w, today_kst):
    VW["fn"] = venue_w
    return _vf0(vflow, real_loc, venue_w, today_kst)


for _mn9 in [m9 for m9 in sys.modules if m9.startswith(("view_", "http_", "accounting_"))]:
    if hasattr(sys.modules[_mn9], "_venue_flows30"):
        sys.modules[_mn9]._venue_flows30 = _vf_spy
web.BUILDER = b = web.StateBuilder()
try:
    st = b.build()
except Exception as e:   # noqa: BLE001
    import traceback
    traceback.print_exc()
    st = {"_exc": f"{type(e).__name__}: {e}"}
f = (st or {}).get("fields") or {} if isinstance(st, dict) else {}
check("빌드 성공", bool(f), st if isinstance(st, dict) and st.get("_exc") else "fields 없음")
locs = [lc for row in list(f.get("coins") or []) + list(f.get("stables") or []) for lc in (row.get("locs") or [])]
by_ch = {}
for lc in locs:
    by_ch.setdefault(lc.get("ch"), []).append(lc)
tr = by_ch.get("Tron") or []
check("H2 Tron 줄 = 'Tron · T…' 줄임 · 이름도 표시 꼴(원장 키 41… 없음)",
      tr and all(lc.get("sub") == f"Tron · {TR1_D[:6]}…{TR1_D[-4:]}" and lc.get("w") == f"{TR1_D[:8]} 지갑" for lc in tr), tr)
to = by_ch.get("TON") or []
check("H3 TON 줄 = 'TON · UQ…' 줄임(0_… 없음)", to and all(lc.get("sub") == f"TON · {TON1_F[:6]}…{TON1_F[-4:]}" and "0_" not in lc.get("w", "") for lc in to), to)
su = by_ch.get("Sui") or []
check("H3 Sui 줄 = 'Sui · 0x…' · 별명", su and all(lc.get("sub") == f"Sui · {SUI1[:6]}…{SUI1[-4:]}" and lc.get("w") == "SuiOne 지갑" for lc in su), su)
bt = by_ch.get("Bitcoin") or []
ba = [lc for lc in bt if lc.get("w") == "콜드 지갑"]
bh = [lc for lc in bt if lc.get("w") == "HdOne 지갑"]
check("H4 BTC 단일 주소 = 'Bitcoin · bc1q…' 줄임(지갑 id 없음)", ba and all(lc.get("sub") == f"Bitcoin · {N.BTC_ADDR[:6]}…{N.BTC_ADDR[-4:]}" for lc in ba), bt)
check("H4 BTC HD = 'Bitcoin' 만(디스크립터·지갑 id 줄임 없음)", bh and all(lc.get("sub") == "Bitcoin" for lc in bh), bt)
keys9 = (TR1, TON1, BTC_A, BTC_HD, BTC_A2)
leak = [lc for lc in locs if any(k9[:6] in str(lc.get("sub")) or k9[:8] in str(lc.get("w")) for k9 in keys9)]
check("H2~H4 보유 줄 어디에도 원장 키 조각 없음", not leak, leak)
vw = VW.get("fn")
vn = [vw(f"wallet:{ch9}:{k9}") for ch9, k9 in (("tron", TR1), ("ton", TON1), ("btc", BTC_A), ("btc", BTC_HD), ("sui", SUI1))] if vw else []
check("H5 보관처 이름 = 보유 줄 이름(원장 키 조각 없음)", vn == [f"{TR1_D[:8]} 지갑", f"{TON1_F[:8]} 지갑", "콜드 지갑", "HdOne 지갑", "SuiOne 지갑"], vn)
b2 = [lc for lc in bt if lc.get("sub") == f"Bitcoin · {BTC_ADDR2[:6]}…{BTC_ADDR2[-4:]}"]
check("H5b 이름 없는 BTC 단일 주소 = 보관처 이름 = 보유 줄 이름(bc1… · 지갑 id 조각 없음)",
      bool(vw) and len(b2) == 1 and vw(f"wallet:btc:{BTC_A2}") == b2[0].get("w") == f"{BTC_ADDR2[:8]} 지갑", [vw(f"wallet:btc:{BTC_A2}") if vw else None, b2])
st_txt = json.dumps(st, ensure_ascii=False, default=str)
check("H4 디스크립터·xpub 원문이 화면 상태에 없음", N.BTC_XPUB[4:40] not in st_txt)

APP = T.app_js_path()
src = open(APP, encoding="utf-8").read()
m1 = re.search(r"^  const VN_FAM = .*$", src, re.M)
m2 = re.search(r"^    const fam9 = .*\n    const kindTxt = .*$", src, re.M)
check("H6 (정적) 칩 계열 표 · kindTxt 가 계열로", bool(m1 and m2))
node = T.node_bin("칩 실행 시험")
if node and m1 and m2:
    js = m1.group(0) + "\nconst out = [];\nfor (const [kind, chs, cash] of " + json.dumps([
        ["wallet", ["Ethereum"], False], ["wallet", ["Solana"], False], ["wallet", ["Base", "Solana"], False], ["wallet", [], False],
        ["wallet", ["Bitcoin"], False], ["wallet", ["Tron", "Ethereum"], False], ["wallet", ["Sui", "TON"], False], ["cex", ["x"], False], ["lp", [], False],
        ["cex", [], True]]) + ") {\n  const v = { kind }, chains = chs.map(ch => ({ ch })), allCash = cash;\n" \
        + m2.group(0) + "\n  out.push(kindTxt);\n}\nconsole.log(JSON.stringify(out));\n"
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = None
    want = ["지갑 · EVM", "지갑 · SOL", "지갑 · EVM · SOL", "지갑 · EVM", "지갑 · BTC", "지갑 · EVM · TRON", "지갑 · SUI · TON", "거래소", "LP", "현금"]
    check("H6 칩: 기존 EVM·SOL·EVM · SOL 그대로 · Bitcoin = BTC · 새 체인 계열", got == want, [got, r.stderr[-300:]])
T.finish()
