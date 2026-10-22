#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter  # noqa: E402

NOW = int(time.time())
A, B = N.OWN["tron"]
X = N.EXT["tron"]
SD = paths.STATE_DIR
INB = os.path.join(paths.INBOX_DIR, "tron")
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
json.dump(cfg, open(CFG_PATH, "w"))


class Crash(Exception):
    pass


class FakeAdapter(reg.ChainAdapter):
    chain = "tron"
    PAGE = 2

    def __init__(self, cfg, txs):
        super().__init__(cfg)
        self.txs = txs
        self.fp = "q1"
        self.fail = set()
        self.bad = set()
        self.pages = 0

    def discovery_query(self, owner, lane):
        return {"owner": owner, "lane": lane, "upper": NOW}, self.fp

    def discover_page(self, owner, query, cursor):
        self.pages += 1
        rows = [t for t in self.txs if owner in t[2] and (t[1] >= NOW - 86400) == (query["lane"] == "latest")]
        i = int(cursor or 0)
        page = rows[i:i + self.PAGE]
        nxt = i + self.PAGE if i + self.PAGE < len(rows) else None
        return [{"stable_id": t[0]} for t in page], (str(nxt) if nxt is not None else None)

    def fetch_and_normalize(self, ref, owners):
        uid = ref["stable_id"]
        if uid in self.fail:
            raise cw.Transient("429")
        t = [x for x in self.txs if x[0] == uid][0]
        mine = [o for o in sorted(t[2]) if o in owners]
        r = N.rec("tron", uid, t[1], [(o, "native", t[2][o]) for o in mine],
                  fees=[(t[3], 1000)] if t[3] in owners else [], owners=mine, moves=[("native", A, X, 1)])
        if uid in self.bad:
            r["deltas"][0]["delta_base"] = "1.5"
        return r


def uids_in_inbox():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln)["tx_uid"] for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


TXS = [("d%02d" % i + "0" * 61, NOW - 3 * 86400 - i * 100, {A: -(10 + i) * 1000 - 1000}, A) for i in range(5)]
TXS += [("e01" + "0" * 61, NOW - 600, {A: 7000}, None)]
ad = FakeAdapter(cfg, TXS)
w = SegmentWriter(INB)

st = cs.ChainState("tron")
col = cw.Collector(ad, w, st, {A})
orig_save_cursor = st.save_cursor
st.save_cursor = lambda *a, **k: (_ for _ in ()).throw(Crash())
try:
    col.discover("history")
except Crash:
    pass
st2 = cs.ChainState("tron")
check("W2 죽기 전 대기열은 디스크에 · 커서는 그대로(미전진)", len(st2.d["pending"]) == 2 and not st2.lane("history:" + A).get("cursor"),
      (list(st2.d["pending"]), st2.lane("history:" + A)))

col = cw.Collector(ad, w, st2, {A})
r = col.cycle()
check("W1 과거 5건 + 최신 1건 전부 방출 · 대기 0 · 동기화 도장", sorted(uids_in_inbox()) == sorted(t[0] for t in TXS) and r["left"] == 0
      and st2.d.get("synced_at"), (r, uids_in_inbox()))
check("W1 쪽 끝까지(2·2·1 + 최신 1)", st2.lane("history:" + A).get("cursor") is None)

ad.txs.append(("e02" + "0" * 61, NOW - 300, {A: 9000}, None))
st3 = cs.ChainState("tron")
col = cw.Collector(ad, w, st3, {A})
orig_me = st3.mark_emitted
st3.mark_emitted = lambda *a, **k: (_ for _ in ()).throw(Crash())
try:
    col.cycle()
except Crash:
    pass
st4 = cs.ChainState("tron")
col = cw.Collector(ad, w, st4, {A})
col.cycle()
n_e02 = uids_in_inbox().count("e02" + "0" * 61)
check("W3 append 뒤 죽음 → 다시 보냄(인박스 2번)", n_e02 == 2, n_e02)
reg.FORCE_AVAILABLE.add("tron")
c = core.Core(config.load_config())
c.conn.commit()
rd = dict(c.chain_readers)["tron"]
c._drain_stream("tron", rd, 1, 0)
nn = c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='tron'").fetchone()[0]
qa = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE location=?", (reg.make_location("tron", A),)).fetchone()[0]
expect = sum(t[2][A] for t in ad.txs)
check("W3 원장은 한 번(거래 7건 · 지갑 합 = 순변화 합)", nn == 7 and qa == expect, (nn, qa, expect))

ad.txs.append(("e03" + "0" * 61, NOW - 200, {A: 1000}, None))
ad.txs.append(("e04" + "0" * 61, NOW - 100, {A: 2000}, None))
ad.fail.add("e03" + "0" * 61)
st5 = cs.ChainState("tron")
st5.d.pop("synced_at", None)
col = cw.Collector(ad, w, st5, {A})
r = col.cycle()
check("W4 실패 1건 대기 · 다른 최신 거래는 나감 · 동기화 도장 없음", "e04" + "0" * 61 in uids_in_inbox() and "e03" + "0" * 61 in st5.d["pending"]
      and not st5.d.get("synced_at"), r)
for _i in range(cs.MAX_TRIES + 1):
    st5.d["pending"].get("e03" + "0" * 61, {})["next"] = 0
    col.details("latest")
check("W4 상한 넘으면 gap(사유 내구)", any(g["id"] == "e03" + "0" * 61 and "429" in g["why"] for g in cs.ChainState("tron").d["gaps"]))

many = [("f%02d" % i + "0" * 61, NOW - 5 * 86400 - i, {A: 1}, None) for i in range(30)]
ad.txs += many
ad.txs.append(("e05" + "0" * 61, NOW - 50, {A: 3000}, None))
st6 = cs.ChainState("tron")
col = cw.Collector(ad, w, st6, {A}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 50, "history": 3})
col.cycle()
check("W5 과거 대기가 남아도(예산 3) 최신 거래는 이번 주기에 나감", "e05" + "0" * 61 in uids_in_inbox() and
      sum(1 for p in st6.d["pending"].values() if p["ref"].get("lane") == "history") > 0)

U6 = "g01" + "0" * 61
ad.txs.append((U6, NOW - 2 * 86400, {A: -5000, B: 4000}, A))
st7 = cs.ChainState("tron")
col = cw.Collector(ad, w, st7, {A}, detail_budget={"latest": 50, "history": 500})
col.cycle()
c.chain_owners["tron"] = {A, B}
col = cw.Collector(ad, w, cs.ChainState("tron"), {A, B}, detail_budget={"latest": 50, "history": 500})
col.cycle()
c._drain_stream("tron", rd, *[(r9["seg"], r9["off"]) for r9 in c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='tron'")][0])
ev6 = c.conn.execute("SELECT event FROM tx_class WHERE chain='tron' AND txhash=?", (U6,)).fetchone()["event"]
lb = c.conn.execute("SELECT SUM(CAST(qty_base AS INTEGER)) FROM postings WHERE source_id=? AND location=?", (U6, reg.make_location("tron", B))).fetchone()[0]
check("W6 B 등록 뒤 같은 거래 넓은 관점 재방출 → core TRANSFER_SELF 로 교체 · B +4000 한 번", ev6 == "TRANSFER_SELF" and lb == 4000,
      (ev6, lb, uids_in_inbox().count(U6)))

before = len(uids_in_inbox())
ad.fp = "q2"
st8 = cs.ChainState("tron")
col = cw.Collector(ad, w, st8, {A, B}, detail_budget={"latest": 50, "history": 500})
col.cycle()
check("W7 지문 바뀜 = 처음부터 겹쳐 다시 읽음 · 이미 보낸 거래 다시 안 보냄", st8.lane("history:" + A).get("fp") == "q2"
      and len(uids_in_inbox()) == before, (before, len(uids_in_inbox())))

U8 = "h01" + "0" * 61
ad.txs.append((U8, NOW - 20, {A: 1}, None))
ad.bad.add(U8)
st9 = cs.ChainState("tron")
col = cw.Collector(ad, w, st9, {A, B})
col.cycle()
check("W8 계약 위반 = 안 보냄 · gap 사유", U8 not in uids_in_inbox() and any(g["id"] == U8 and "계약 위반" in g["why"] for g in st9.d["gaps"]))

class ResumeAdapter(FakeAdapter):
    win = NOW - 30 * 86400

    def discovery_query(self, owner, lane):
        sf = self.lane_safe(owner, lane)
        if lane == "history":
            if sf.get("done") and self.win >= int(sf.get("win", 0)):
                return None, self.fp
            return {"owner": owner, "lane": lane, "upper": NOW, "win": self.win}, self.fp + ":h"
        return {"owner": owner, "lane": lane, "upper": NOW, "lo": int(sf.get("t", 0)) - 60}, self.fp + ":l"

    def discover_page(self, owner, query, cursor):
        self.pages += 1
        if query["lane"] == "history":
            rows = [t for t in self.txs if owner in t[2] and query["win"] <= t[1] < NOW - 86400]
        else:
            rows = [t for t in self.txs if owner in t[2] and t[1] >= max(NOW - 86400, query["lo"])]
        i = int(cursor or 0)
        page = rows[i:i + self.PAGE]
        nxt = i + self.PAGE if i + self.PAGE < len(rows) else None
        self._seen = max([getattr(self, "_seen", 0)] + [t[1] for t in page])
        return [{"stable_id": t[0]} for t in page], (str(nxt) if nxt is not None else None)

    def lane_done(self, owner, lane, query):
        if lane == "history":
            return {"done": True, "win": query["win"]}
        return {"t": max(int(self.lane_safe(owner, lane).get("t", 0)), getattr(self, "_seen", 0))}


import shutil  # noqa: E402
for f9 in ("cursor_tron.json", "emitted_tron.json"):
    if os.path.exists(os.path.join(SD, f9)):
        os.remove(os.path.join(SD, f9))
shutil.rmtree(INB, ignore_errors=True)
ra = ResumeAdapter(cfg, [t for t in ad.txs if A in t[2] and t[0] not in (U8,)])
ra.bad = set()
w9 = SegmentWriter(INB)
s9 = cs.ChainState("tron")
col = cw.Collector(ra, w9, s9, {A}, detail_budget={"latest": 50, "history": 500})
check("W9 Collector 가 훅 없는 상태를 어댑터에 붙임(lane_safe 가 같은 상태를 읽음)", ra.state is s9)
col.cycle()
n1 = len(uids_in_inbox())
p_hist = ra.pages
check("W9 첫 주기 = 과거·최신 전부 방출 · history 끝 경계 · latest 경계", n1 == len(ra.txs) and s9.lane("history:" + A).get("safe", {}).get("done")
      and int(s9.lane("latest:" + A).get("safe", {}).get("t", 0)) > 0, (n1, len(ra.txs), s9.lane("history:" + A), s9.lane("latest:" + A)))
ra.pages = 0
col.cycle()
check("W9 새 활동 없는 다음 주기 = history 호출 0 · latest 1쪽만 · 새 방출 0", ra.pages == 1 and len(uids_in_inbox()) == n1, (ra.pages, len(uids_in_inbox())))
disk = json.load(open(os.path.join(SD, "cursor_tron.json")))
check("W9 안전 경계가 디스크에(재시작해도 이어 읽기)", ((disk.get("lanes") or {}).get("history:" + A) or {}).get("safe", {}).get("done") is True,
      (disk.get("lanes") or {}).get("history:" + A))
s9b = cs.ChainState("tron")
ra.pages = 0
cw.Collector(ra, w9, s9b, {A}).cycle()
check("W9 재시작(새 상태 객체) 뒤에도 history 호출 0", ra.pages == 1 and len(uids_in_inbox()) == n1, ra.pages)
U9 = "k01" + "0" * 61
ra.txs.append((U9, NOW - 30, {A: 4242}, None))
s9c = cs.ChainState("tron")
_sc9 = s9c.save_cursor
s9c.save_cursor = lambda lane, cursor, *a, **k: (_ for _ in ()).throw(Crash()) if cursor is None else _sc9(lane, cursor, *a, **k)
ra.state = s9c
try:
    cw.Collector(ra, w9, s9c, {A}).discover("latest")
except Crash:
    pass
d9 = json.load(open(os.path.join(SD, "cursor_tron.json")))
lt9 = int((((d9.get("lanes") or {}).get("latest:" + A) or {}).get("safe") or {}).get("t", 0))
check("W9 경계 전진은 그 쪽 대기 후보와 함께 디스크에(경계만 앞서 가지 않음)", U9 in (d9.get("pending") or {}) and lt9 >= NOW - 30, (lt9, list(d9.get("pending") or {})))
s9d = cs.ChainState("tron")
ra.state = s9d
cw.Collector(ra, w9, s9d, {A}).cycle()
check("W9 재시작 뒤 그 거래 방출 1번", uids_in_inbox().count(U9) == 1, uids_in_inbox().count(U9))
U10 = "k02" + "0" * 61
ra.txs.append((U10, NOW - 40 * 86400, {A: 77}, None))
ra.win = NOW - 60 * 86400
ra.pages = 0
cw.Collector(ra, w9, s9d, {A}).cycle()
check("W9 창 넓힘 → history 다시 읽어 옛 거래 방출 · 기존 재방출 0", uids_in_inbox().count(U10) == 1 and uids_in_inbox().count(U9) == 1 and ra.pages >= 2,
      (ra.pages, uids_in_inbox().count(U10)))
ad.pages = 0
os.remove(os.path.join(SD, "cursor_tron.json"))
s9e = cs.ChainState("tron")
cw.Collector(ad, w9, s9e, {A}).discover("history")
p1 = ad.pages
cw.Collector(ad, w9, s9e, {A}).discover("history")
check("W9 훅 없는 어댑터 = 종전(매 주기 처음부터 · 안전 경계 없음)", ad.pages == 2 * p1 and p1 > 0 and not s9e.lane("history:" + A).get("safe"), (p1, ad.pages))

class DecAdapter(FakeAdapter):
    dec = None

    def fetch_and_normalize(self, ref, owners):
        uid = ref["stable_id"]
        t = [x for x in self.txs if x[0] == uid][0]
        return N.rec("tron", uid, t[1], [(A, ("token", "41" + "e9" * 20, "NOM", self.dec), 5)], owners=[A])


U12 = "m01" + "0" * 61
da = DecAdapter(cfg, [(U12, NOW - 20, {A: 5}, None)])
os.remove(os.path.join(SD, "cursor_tron.json"))
s10 = cs.ChainState("tron")
c10 = cw.Collector(da, w9, s10, {A})
r10 = c10.cycle()
p10 = s10.d["pending"].get(U12) or {}
check("W10 자릿수 None 토큰 레코드 = 인박스에 안 보냄 · 대기 사유 · 동기화 도장 없음", U12 not in uids_in_inbox() and "자릿수 미확인" in p10.get("why", "")
      and r10["left"] == 1 and not s10.d.get("synced_at"), (r10, p10))
da.dec = 6
p10["next"] = 0
c10.cycle()
check("W10 자릿수를 알게 되면 방출 1번", uids_in_inbox().count(U12) == 1)
U13 = "m02" + "0" * 61
da.txs.append((U13, NOW - 10, {A: 5}, None))
da.dec = None
c10.discover("latest")
for _i in range(cs.MAX_TRIES + 1):
    if U13 in s10.d["pending"]:
        s10.d["pending"][U13]["next"] = 0
    c10.details("latest")
check("W10 끝내 모르면 상한 뒤 gap(사유 내구 기록) · 방출 0", U13 not in uids_in_inbox() and any(g["id"] == U13 and "자릿수 미확인" in g["why"] for g in s10.d["gaps"]))
reg.FORCE_AVAILABLE.clear()
T.finish()
