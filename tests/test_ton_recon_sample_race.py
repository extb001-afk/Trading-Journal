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
A, B, X = F.K("41"), F.K("42"), F.K("99")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
T.patch_moved("dm", lambda *a, **k: None)


def set_wallets(*keys):
    cfg9 = json.load(open(CFG_PATH))
    cfg9["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(k)} for k in keys]
    json.dump(cfg9, open(CFG_PATH, "w"))
    return config.load_config()


def uid_of(t):
    return tw.tx_uid(tw.akey(t["account"]), t["lt"], t["_hex"])


class HoldWriter:
    def __init__(self, w):
        self.w, self.hold, self.held = w, set(), []

    def append(self, rec):
        if rec.get("tx_uid") in self.hold:
            self.held.append(rec)
            return None
        return self.w.append(rec)

    def __getattr__(self, k):
        return getattr(self.w, k)


class RaceClient:
    def __init__(self, real, ch, to, val):
        self.real, self.ch, self.to, self.val, self.pay = real, ch, to, val, None

    def __getattr__(self, k):
        return getattr(self.real, k)

    def account_states(self, raws):
        rows = self.real.account_states(raws)
        if self.pay is None:
            self.pay = self.ch.tx(self.to, int(time.time()) - 2, in_msg={"src": X, "val": self.val}, tf=0)
        return rows


cfg = set_wallets(A)
ch = F.Chain()
srv = F.Server(ch).start()
ch.tx(A, NOW - 400 * DAY, in_msg={"src": X, "val": 100 * TON}, tf=0)
q = ch.tx(A, NOW - 2 * DAY, in_msg={"src": X, "val": 50 * TON}, tf=0)
Q_UID = uid_of(q)
W = SegmentWriter(INB)
HW = HoldWriter(W)
HW.hold.add(Q_UID)
st = cs.ChainState("ton")
ad = tw.TonAdapter(cfg, client=srv.client(), state=st)
col = cw.Collector(ad, HW, st, {A})
for _i in range(3):
    col.cycle()
c = core.Core(cfg)
c.conn.commit()


def drain(cc):
    rd = SegmentReader(INB)
    for _i in range(50):
        row = cc.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        cc._drain_stream("ton", rd, seg, off)
        row2 = cc.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    cc.conn.commit()


def native(cc, w):
    return sum(int(r[0]) for r in cc.conn.execute(
        "SELECT p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE a.chain='ton' AND a.kind='native' AND p.location=?",
        (reg.make_location("ton", w),)))


def openings(cc, sid):
    return [int(r[0]) for r in cc.conn.execute("SELECT qty_base FROM postings WHERE source_kind='opening' AND source_id=? ORDER BY leg_seq", (sid,))]


def payload(cc, sid):
    r = cc.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (sid,)).fetchone()
    return json.loads(r[0]) if r else {}


drain(c)
check("RR0 준비: 늦게 올 거래(Q)는 수집기만 봄(방출 기록) · 원장 네이티브 0", st.ready({A}) and st.emitted(Q_UID) and HW.held and native(c, A) == 0,
      (st.ready({A}), len(HW.held), native(c, A)))

rc = RaceClient(srv.client(), ch, A, 500 * TON)
c.svc_recon._nonevm_adapters = {"ton": tw.TonAdapter(cfg, client=rc)}
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
hw_ts = int(q["now"])
pay = payload(c, "recon:ton")
check("RR1 체인 대사 완료 · opening = 샘플 잔고 150 TON(입금 500 은 샘플 밖) · 관측 _ts_cut = 샘플 거래 시각 상한 + 1",
      bool(c._meta_get("recon_done_ton")) and rc.pay is not None and openings(c, "recon:ton") == [150 * TON]
      and pay.get("_ts_cut") == hw_ts + 1 and int(rc.pay["now"]) < int(c._meta_get("recon_done_ton")),
      (c._meta_get("recon_done_ton"), openings(c, "recon:ton"), pay.get("_ts_cut"), hw_ts, rc.pay and rc.pay["now"]))

for rec in HW.held:
    W.append(rec)
HW.held = []
HW.hold.clear()
for _i in range(3):
    col.cycle()
drain(c)
check("RR2 샘플 뒤 입금 = +500 그대로(흡수 안 함) · 샘플 안 늦은 거래(Q) = 흡수(opening 150 → 100) · 원장 = 체인 잔고 650",
      native(c, A) == ch.bal[A] == 650 * TON and openings(c, "recon:ton") == [100 * TON] and st.ready({A}),
      (native(c, A), ch.bal[A], openings(c, "recon:ton")))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
check("RR2 다음 대사 주기 뒤에도 그대로", native(c, A) == ch.bal[A] and openings(c, "recon:ton") == [100 * TON], (native(c, A), openings(c, "recon:ton")))

c._drain_stream("ton", SegmentReader(INB), 1, 0)
c.conn.commit()
check("RR3 같은 레코드 재수신 = 원장 그대로", native(c, A) == ch.bal[A] and openings(c, "recon:ton") == [100 * TON], (native(c, A), openings(c, "recon:ton")))
c.conn.close()
c2 = core.Core(cfg)
c2.conn.commit()
c2.svc_recon._nonevm_adapters = {"ton": tw.TonAdapter(cfg, client=srv.client())}
drain(c2)
c2.svc_recon._last_recon = 0
c2.svc_recon.recon_pass({"ton"})
T2 = int(c2._meta_get("recon_done_ton"))
check("RR3 core 재시작 뒤 = 원장 그대로 · 같은 흡수 판정(샘플 뒤 입금 = 아님 · Q = 흡수)",
      native(c2, A) == ch.bal[A] and openings(c2, "recon:ton") == [100 * TON]
      and c2.svc_recon._absorbed("recon:ton", int(rc.pay["now"]), T2, None) is False and c2.svc_recon._absorbed("recon:ton", int(q["now"]), T2, None) is True,
      (native(c2, A), openings(c2, "recon:ton")))

ch.tx(B, NOW - 400 * DAY, in_msg={"src": X, "val": 30 * TON}, tf=0)
cfg = set_wallets(A, B)
c2.chain_owners["ton"] = {A, B}
st = cs.ChainState("ton")
ad.bind_state(st)
col = cw.Collector(ad, W, st, {A, B})
for _i in range(3):
    col.cycle()
drain(c2)
rc2 = RaceClient(srv.client(), ch, B, 7 * TON)
c2.svc_recon._nonevm_adapters = {"ton": tw.TonAdapter(cfg, client=rc2)}
c2.svc_recon._last_recon = 0
c2.svc_recon.recon_pass({"ton"})
SB = f"recon:ton:{B}"
check("RR4 새 지갑 B 대사 완료 · opening 30 TON · 관측 _ts_cut 있음", bool(c2._meta_get(f"wrecon_done:ton:{B}")) and openings(c2, SB) == [30 * TON]
      and isinstance(payload(c2, SB).get("_ts_cut"), int) and rc2.pay is not None,
      (c2._meta_get(f"wrecon_done:ton:{B}"), openings(c2, SB), payload(c2, SB)))
for _i in range(3):
    col.cycle()
drain(c2)
check("RR4 샘플 뒤 입금 +7 = 그대로 · B 원장 = 체인 잔고 37", native(c2, B) == ch.bal[B] == 37 * TON and openings(c2, SB) == [30 * TON],
      (native(c2, B), ch.bal[B], openings(c2, SB)))

c2.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES ('recon:zz', 'opening_balance', 'zz', ?, 1000)",
                (json.dumps({"w": {"native:None": 1}}),))
check("RR5 _ts_cut 없는 옛 관측 = 대사 시각 T 기준(종전)", c2.svc_recon._absorbed("recon:zz", 999, 1000, None) is True and c2.svc_recon._absorbed("recon:zz", 1000, 1000, None) is False)
c2.conn.rollback()
c2.conn.close()
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
