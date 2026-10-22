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
A, J, M, X = F.K("52"), F.K("d3"), F.K("e3"), F.K("98")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(A)}]
json.dump(cfg, open(CFG_PATH, "w"))
T.patch_moved("dm", lambda *a, **k: None)

ch = F.Chain()
srv = F.Server(ch).start()
ch.tx(A, NOW - 399 * DAY, in_msg={"src": X, "val": 3 * TON}, tf=1000)
ch.add_jetton(A, J, M, symbol="JF", decimals="6")
ch.tx(J, NOW - 399 * DAY, in_msg={"src": F.K("d9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5_000_000, X)}, tf=0)
ch.jbal[J] = 5_000_000
JW_ROWS = list(ch.jw)
ch.jw = []

st = cs.ChainState("ton")
ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
ad.page = 3
col = cw.Collector(ad, SegmentWriter(INB), st, {A})
for _i in range(3):
    col.cycle()
st = cs.ChainState("ton")
check("JF2 준비: 수집기 ready · J 모름", st.ready({A}) and J not in ((st.d.get("ton") or {}).get("jw") or {}), st.status_view())

FP = getattr(tw, "jw_fingerprint", None) or (lambda o, t: {})
f0 = FP({A}, {"jw": {}})
f1 = FP({A}, {"jw": {J: {"owner": A, "master": M, "ok": True}, F.K("d4"): {"owner": A, "master": M, "ok": False}}})
f1b = FP({A}, {"jw": {F.K("d5"): {"owner": X, "master": M, "ok": True}, J: {"owner": A, "master": M, "ok": True, "at": 1}}})
f2 = FP({A}, {"jw": {J: {"owner": A, "master": M, "ok": True}, F.K("d6"): {"owner": A, "master": M, "ok": True}}})
check("JF1 지문 결정적 · 검증 JW 추가 = 달라짐 · 가짜·다른 owner·부가 칸 무관", f0 != f1 and f1 == f1b and f1 != f2 and set(f0) == {A},
      (f0, f1, f1b, f2))


class SlowEmpty:
    def __init__(self, real):
        self.real = real
        self.armed = True

    def __getattr__(self, k):
        return getattr(self.real, k)

    def jetton_wallets(self, **kw):
        out = self.real.jetton_wallets(**kw)
        if self.armed and kw.get("owner_raw"):
            self.armed = False
            ch.jw = list(JW_ROWS)
            for _i in range(3):
                col.cycle()
        return out


def mk_core(client=None):
    c9 = core.Core(config.load_config())
    c9.conn.commit()
    c9.svc_recon._nonevm_adapters = {"ton": tw.TonAdapter(config.load_config(), client=client or srv.client())}
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


def jet(c9):
    r = c9.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) s, COUNT(*) n FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                        " WHERE a.chain='ton' AND a.kind='token' AND lower(a.address)=lower(?) AND p.source_kind='opening'", (M,)).fetchone()
    return int(r["s"] or 0), int(r["n"] or 0)


def recon(c9):
    c9.svc_recon._last_recon = 0
    c9.svc_recon.recon_pass({"ton"})


slow = SlowEmpty(srv.client())
c = mk_core(slow)
drain(c)
recon(c)
for _i in range(3):
    if not c.svc_recon.__dict__.get("_recon_jobs"):
        break
    drain(c)
    if c._meta_get("recon_done_ton"):
        break
    recon(c)
st = cs.ChainState("ton")
jwJ = ((st.d.get("ton") or {}).get("jw") or {}).get(J) or {}
check("JF2 조회 중 수집기가 J 검증(ok) · ready 유지 · 지연된 빈 목록 응답 사용", not slow.armed and jwJ.get("ok") is True and st.ready({A}),
      (slow.armed, jwJ, st.ready({A})))
check("JF2 옛 집합 결과 = 폐기(recon_done_ton 없음 · 제톤 opening 0)", not c._meta_get("recon_done_ton") and jet(c) == (0, 0),
      (c._meta_get("recon_done_ton"), jet(c)))

for _i in range(3):
    if c._meta_get("recon_done_ton"):
        break
    drain(c)
    recon(c)
st = cs.ChainState("ton")
check("JF3 재조회 = 제톤 opening 정확히 5,000,000 한 번 · 완료 도장", jet(c) == (5_000_000, 1) and bool(c._meta_get("recon_done_ton")),
      (jet(c), c._meta_get("recon_done_ton")))
check("JF3 수집기 J 상태 그대로(core 가 덮어쓰지 않음)", (((st.d.get("ton") or {}).get("jw") or {}).get(J) or {}) == jwJ,
      (((st.d.get("ton") or {}).get("jw") or {}).get(J), jwJ))
c.conn.close()
c = mk_core()
drain(c)
recon(c)
recon(c)
check("JF4 core 재시작 · 재실행 멱등 = 여전히 5,000,000(이중 opening 없음)", jet(c) == (5_000_000, 1), jet(c))
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
