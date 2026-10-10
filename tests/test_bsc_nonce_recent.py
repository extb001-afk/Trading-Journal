#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _bscchain as B

import os
import time

bw = B.bsc_watch
CH = B.CH
common = B.common
clk = [time.time()]
bw._now = lambda: clk[0]


def tick(sec, blocks):
    clk[0] += sec
    CH.head += blocks


def nonce_state():
    return common.read_json(os.path.join(common.STATE_DIR, "bsc_nonce.json"), {})


def caught_up():
    B.reset_state()
    B.exch_withdraw("0x" + "f" * 64, B.W2)
    common.atomic_write_json(B.CPATH, {"from_block": CH.head - 20 - 10, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK,
                                       "_wallets": sorted([B.W1, B.W2])})


def olds(n=20):
    return [CH.native(CH.head - 400_000 - k * 20_000, B.W1, B.OTHER, (k + 1) * 10 ** 15) for k in range(n)]


def arch_calls(w):
    return int((getattr(w, "_nonce_last", None) or {}).get("arch") or 0)


CH.tx.clear()
CH.mode, CH.old_below = None, None
CH.head = B.H0 + 300_000
old1 = olds()
caught_up()
wr = B.Wr()
w = B.mk(wr=wr)
B.cycle(w)
tick(100, 220)
B.cycle(w)
hr = CH.native(CH.head + 5, B.W1, B.OTHER, 7 * 10 ** 16)
got_at = None
for k in range(1, 7):
    tick(100, 220)
    B.cycle(w)
    if hr in B.emitted(wr):
        got_at = k
        break
T.chk(got_at == 1, "R1 새 순수 BNB 발신 = 확정 깊이를 지난 첫 주기에 방출(옛 누락 20건을 좁히는 중에도)",
      {"got_at_cycle": got_at, "missing": {k[:6]: v.get("missing") for k, v in (nonce_state().get("w") or {}).items()}})
rec = {r["txhash"]: r for r in wr.recs}
T.chk(hr in rec and rec[hr].get("via") == "nonce", "R1 방출 모양 = via nonce(종전 회수 규약)")

CH.tx.clear()
CH.head = B.H0 + 600_000
old2 = olds()
hr2 = CH.native(CH.head - 2_000, B.W1, B.OTHER, 3 * 10 ** 16)
caught_up()
wr2 = B.Wr()
w = B.mk(wr=wr2)
B.cycle(w)
T.chk(hr2 in B.emitted(wr2), "R2 처음 회수 때 최근(2시간 안) 발신이 옛 누락 20건보다 먼저 — 첫 주기에 방출",
      {"emitted": len(wr2.recs), "arch": arch_calls(w)})

runs, arch_sum = 0, 0
for k in range(120):
    tick(100, 220)
    w._nonce_last = None
    B.cycle(w)
    arch_sum += arch_calls(w)
    runs += 1
    if all(h in B.emitted(wr2) for h in old2):
        break
em = B.emitted(wr2)
print(f"정보 R3: 옛 누락 20건 회수 = 주기 {runs}번(가짜 시계 100초 간격) · 아카이브 {arch_sum}콜(건당 ≈{arch_sum / 20:.1f})")
T.chk(all(h in em for h in old2), "R3 옛 누락 20건도 남는 몫으로 끝까지 회수", {"left": sum(1 for h in old2 if h not in em), "cycles": runs})
T.chk(len(em) == len(set(em)), "R3 같은 tx 두 번 방출 0", len(em) - len(set(em)))
T.chk(all(int((v or {}).get("missing") or 0) == 0 for v in (nonce_state().get("w") or {}).values()), "R3 남은 누락 0",
      {k[:6]: (v or {}).get("missing") for k, v in (nonce_state().get("w") or {}).items()})
order = [em.index(h) for h in old2]
T.chk(order[0] < order[-1], "R3 옛 누락도 최근 것부터(가장 최근 옛 누락이 가장 옛 누락보다 먼저)", {"first": order[0], "last": order[-1]})
st0 = nonce_state()
tops0 = {k: (v or {}).get("top") for k, v in (st0.get("w") or {}).items()}
arch_quiet = []
for k in range(4):
    tick(100, 220)
    w._nonce_last = None
    B.cycle(w)
    arch_quiet.append(arch_calls(w))
tops1 = {k: (v or {}).get("top") for k, v in (nonce_state().get("w") or {}).items()}
T.chk(sum(arch_quiet) == 0, "R4 새 누락이 없으면 주기마다 아카이브 0콜", arch_quiet)
T.chk(all(tops1[k] and tops0.get(k) and tops1[k] > tops0[k] for k in tops1), "R4 헤드 nonce 확인은 주기마다(공개 노드 — 새 발신을 바로 봄)", (tops0, tops1))

ARCH = "http://bsc-mainnet.nodereal.io.invalid/v1/x"
WS = ["0x" + format(0xB5000 + i, "040x") for i in range(60)]
CH.tx.clear()
CH.head = B.H0 + 900_000
for x in WS:
    CH.native(B.WIN_BLK - 100, x, B.OTHER, 1)
miss5 = CH.native(CH.head - 50_000, WS[0], B.OTHER, 9 * 10 ** 15)
B.reset_state()
B.exch_withdraw("0x" + "f" * 64, B.W2)
common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK, "_wallets": sorted(WS)})
c5 = B.cfg(detail_rpcs=[ARCH])
c5["wallets"] = [{"type": "bsc_rpc", "address": x} for x in WS]
wr5 = B.Wr()
w5 = bw.BscWatcher(c5, WS, wr5)
T.chk(w5.nonce_pub_rpc is None and w5.arch_rpc is not None, "R5 전제: 공개 노드 없음 · 아카이브만", (w5.nonce_pub_rpc, w5.arch_rpc and w5.arch_rpc.urls))
got5, archs5 = None, []
for k in range(40):
    tick(100, 220)
    w5._nonce_last = None
    B.cycle(w5)
    archs5.append(arch_calls(w5))
    if miss5 in B.emitted(wr5):
        got5 = k + 1
        break
T.chk(got5 is not None and got5 <= 15, "R5 아카이브 전용 · EOA 60개 — 로그 없는 발신 회수(헤드 확인이 회수 몫을 다 먹지 않음)",
      {"got_at_cycle": got5, "arch_per_run": archs5[:15]})
T.chk(max(archs5 or [0]) <= bw.NONCE_CALL_CAP, "R5 실행당 아카이브 상한 지킴", archs5)

DOWN = "http://bsc-dataseed-down.invalid/"
_hj = B.bf_engine.http_json


def http_down(url, data=None, **kw):
    if "dataseed-down" in str(url):
        raise B.bf_engine.NetError("시험: 연결 거부", "conn", host="bsc-dataseed-down.invalid")
    return _hj(url, data=data, **kw)


http_down._tj_test_mock = True
B.bf_engine.http_json = http_down
miss6 = CH.native(CH.head - 30_000, WS[1], B.OTHER, 8 * 10 ** 15)
B.reset_state()
B.exch_withdraw("0x" + "f" * 64, B.W2)
common.atomic_write_json(B.CPATH, {"from_block": CH.head - 30, "head": CH.head - 10, "_cov": B.WIN_BLK, "_bf_start": B.WIN_BLK, "_wallets": sorted(WS)})
c6 = B.cfg(detail_rpcs=[DOWN, ARCH])
c6["wallets"] = [{"type": "bsc_rpc", "address": x} for x in WS]
wr6 = B.Wr()
w6 = bw.BscWatcher(c6, WS, wr6)
T.chk(w6.nonce_pub_rpc is not None and w6.nonce_pub_rpc.urls == [DOWN], "R6 전제: 공개 노드 = 실패하는 1곳 · 아카이브 따로", w6.nonce_pub_rpc and w6.nonce_pub_rpc.urls)
got6, archs6 = None, []
for k in range(40):
    tick(100, 220)
    w6._nonce_last = None
    B.cycle(w6)
    archs6.append(arch_calls(w6))
    if miss6 in B.emitted(wr6):
        got6 = k + 1
        break
B.bf_engine.http_json = _hj
T.chk(got6 is not None and got6 <= 15, "R6 공개 노드 계속 실패 · EOA 60개 — 로그 없는 발신 회수(아카이브 헤드 폴백이 회수 몫을 다 먹지 않음)",
      {"got_at_cycle": got6, "arch_per_run": archs6[:15]})

bw._now = time.time
T.finish()
