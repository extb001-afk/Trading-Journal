#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402

DAY = 86400
NOW = int(time.time())
TON = 10 ** 9
A, J, M, X = F.K("51"), F.K("d1"), F.K("e1"), F.K("99")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(A)}]
json.dump(cfg, open(CFG_PATH, "w"))

ch = F.Chain()
srv = F.Server(ch).start()
ch.tx(A, NOW - 399 * DAY, in_msg={"src": X, "val": 3 * TON}, tf=1000)
ch.add_jetton(A, J, M, symbol="JM", decimals="6")
ch.tx(J, NOW - 399 * DAY, in_msg={"src": F.K("d9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5_000_000, X)}, tf=0)
ch.jbal[J] = 5_000_000

st = cs.ChainState("ton")
ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
ad.page = 3
col = cw.Collector(ad, SegmentWriter(INB), st, {A})
for _i in range(3):
    col.cycle()
st = cs.ChainState("ton")
jw = ((st.d.get("ton") or {}).get("jw") or {}).get(J) or {}
check("JM1 수집기가 J 검증(ok · master M) · ready", jw.get("ok") is True and jw.get("master") == M and st.ready({A}), (jw, st.ready({A})))


def mk_core():
    c9 = core.Core(config.load_config())
    c9.conn.commit()
    c9.svc_recon._nonevm_adapters = {"ton": tw.TonAdapter(config.load_config(), client=srv.client())}
    return c9


def drain(c9):
    rd = SegmentReader(INB)
    for _i in range(50):
        row = c9.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c9._drain_stream("ton", rd, seg, off)
        row2 = c9.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c9.conn.commit()


def jet(c9, kind="opening"):
    r = c9.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) s, COUNT(*) n FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                        " WHERE a.chain='ton' AND a.kind='token' AND lower(a.address)=lower(?) AND p.source_kind" + ("='opening'" if kind == "opening" else "!='opening'"),
                        (M,)).fetchone()
    return int(r["s"] or 0)


def recon(c9):
    c9.svc_recon._last_recon = 0
    c9.svc_recon.recon_pass({"ton"})


c = mk_core()
drain(c)
has_asset = c.conn.execute("SELECT COUNT(*) n FROM assets WHERE chain='ton' AND kind='token' AND lower(address)=lower(?)", (M,)).fetchone()["n"]
check("JM1 원장에 그 제톤 token 칸 없음(창 이전 보유만)", has_asset == 0 and jet(c, "chain") == 0, has_asset)

jw0 = list(ch.jw)
ch.jw = []
rb = tw.TonAdapter(config.load_config(), client=srv.client())
b = rb.fetch_balances({A}, None, tokens={})
check("JM2 원장 token 없음 + 검증된 J 가 목록에 없음 = 미관측 + 보류(jetton_wallet_missing)",
      b["_complete"] is False and "jetton_wallet_missing" in (b.get("_why") or []) and M in (b["_unobserved"].get(A) or []),
      (b["_complete"], b.get("_why"), b["_unobserved"]))
recon(c)
check("JM2 대사 = 보류(recon_done_ton 없음 · 제톤 opening 0)", not c._meta_get("recon_done_ton") and jet(c) == 0,
      (c._meta_get("recon_done_ton"), jet(c)))

ch.jw = jw0
recon(c)
check("JM3 목록 회복 뒤 대사 = 제톤 opening 정확히 5,000,000 · 완료 도장", jet(c) == 5_000_000 and bool(c._meta_get("recon_done_ton")),
      (jet(c), c._meta_get("recon_done_ton")))
c.conn.close()
c = mk_core()
drain(c)
recon(c)
recon(c)
check("JM3 core 재시작 · 재실행 멱등 = 여전히 5,000,000(이중 opening 없음)", jet(c) == 5_000_000, jet(c))

J2 = F.K("d2")
T9 = st.d.setdefault("ton", {})
T9.setdefault("jw", {})[J2] = {"owner": A, "master": M, "ok": True, "at": NOW, "why": ""}
st.save()
b4 = rb.fetch_balances({A}, None, tokens={A: [M]})
check("JM4 같은 master 검증 지갑 둘 중 하나만 목록 = 부분 합으로 안 셈 + 보류",
      b4["_complete"] is False and "jetton_wallet_missing" in (b4.get("_why") or []) and ("token", M) not in b4["per_wallet"][A],
      (b4["_complete"], b4.get("_why"), b4["per_wallet"]))
T9["jw"].pop(J2)
st.save()

b5 = rb.fetch_balances({A}, None, tokens={})
check("JM5 대조: 목록 정상 = 완전 · 제톤 5,000,000", b5["_complete"] is True and b5["per_wallet"][A].get(("token", M)) == 5_000_000,
      (b5["_complete"], b5.get("_why"), b5["per_wallet"]))
ch.jbal[J] = 0
b6 = rb.fetch_balances({A}, None, tokens={})
check("JM5 대조: 검증 지갑 잔고 0 행이 목록에 있음 = 완전(0 칸 · 보류 아님)", b6["_complete"] is True and b6["per_wallet"][A].get(("token", M)) == 0,
      (b6["_complete"], b6.get("_why"), b6["per_wallet"]))
ch.jbal[J] = 5_000_000
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
