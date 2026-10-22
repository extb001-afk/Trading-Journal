#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import os  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import types  # noqa: E402

import paths  # noqa: E402
import bf_engine  # noqa: E402
import sol_watch  # noqa: E402

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def ad(p8, n):
    h = hashlib.sha256((p8 + str(n)).encode()).digest()
    return (p8 + "".join(B58[b % 58] for b in h))[:44]


def setup(name):
    sd = os.path.join(T.TMP, name, "state")
    os.makedirs(sd, exist_ok=True)
    paths.rebase_state(sd)
    bf_engine._PROGRESS.clear()
    return sd


def rj(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wj(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def it(phase, upd=1_700_000_000, **kw):
    d = {"phase": phase, "updated": upd, "started": upd, "moved_at": upd}
    d.update(kw)
    return d


print("[1] Progress.prune — 지난 프로세스 몫만 · 다른 유닛·이 프로세스 항목 그대로 · 파일 없음/깨짐 = 손대지 않음")
sd = setup("p1")
bs = os.path.join(sd, "backfill_status.json")
p = bf_engine.Progress("sol")
T.chk(p.prune(lambda k, v: True) == 0 and not os.path.exists(bs), "파일 없음 = 0 · 새 파일 만들지 않음")
with open(bs, "w", encoding="utf-8") as f:
    f.write("{깨진")
T.chk(p.prune(lambda k, v: True) == 0 and open(bs, encoding="utf-8").read() == "{깨진", "깨진 파일 = 0 · 빈 파일로 덮지 않음")
p.items["sol:Mine1111"] = it("sigs")
EVM = {"base:0xaaaa": it("scan", done=5, total=10), "base:0xbbbb:extend": it("done")}
wj(bs, {"sol": {"sol:Mine1111": it("sigs"), "sol:Old11111": it("sigs"), "sol:Old22222": it("done")}, "evm": EVM, "_updated": 1})
n = p.prune(lambda k, v: True)
d = rj(bs)
T.chk(n == 2 and set(d["sol"]) == {"sol:Mine1111"} and d["evm"] == EVM, "지난 프로세스 몫 2개만 지움 · 이 프로세스 항목·다른 유닛(evm) 그대로", d)
T.chk(p.prune(lambda k, v: True) == 0, "다시 = 0(멱등)")
wj(bs, {"sol": "깨진 섹션", "evm": EVM})
T.chk(p.prune(lambda k, v: True) == 0 and rj(bs)["sol"] == "깨진 섹션", "섹션이 dict 아님 = 손대지 않음")
def boom(k, v):
    raise ValueError("x")
wj(bs, {"sol": {"sol:Old11111": it("sigs")}, "evm": EVM})
T.chk(p.prune(boom) == 0 and "sol:Old11111" in rj(bs)["sol"], "판정 함수 오류 = 0 · 파일 그대로(수집을 막지 않음)")
src = open(os.path.join(T.SRC, "bf_engine.py"), encoding="utf-8").read()
i9 = src.find("    def prune(self, pred)")
body = src[i9:src.find("    def flush(self):", i9)]
T.chk(i9 > 0 and 'open(self.path + ".lock", "a+")' in body and "fcntl.LOCK_EX" in body and "atomic_write_json" in body,
      "flush 와 같은 잠금 파일(.lock) · 원자 교체")

print("[2] SolWatcher.prune_progress — 끝난·첫 동기화 마친·버려진 표식만")
sd = setup("p2")
O1, O2, R1 = ad("Own1aaaa", 1), ad("Own2bbbb", 2), ad("Rem1cccc", 3)
A1, A2, A3 = ad("Ata1dddd", 4), ad("Ata2eeee", 5), ad("Ata3ffff", 6)
S1 = ad("Stk1gggg", 7)
P1, P2 = ad("Pfx1hhhh", 8), ad("Pfx1hhhh", 9)
Z = "Zzz1jjjj"
cur = {O1: "sigO1", A1: "sigA1", A3: "sigA3", S1: "sigS1", P1: "sigP1", R1: "sigR1",
       "_sigbf:" + A2: {"n": 1000, "off": 50, "before": "b", "done": False}, "_sigx:" + A3: {"target": 1, "n": 3, "off": 9, "before": None, "done": False},
       "_stk:" + S1: {"w": O1, "t0": 1, "open": True}, "_fb_wait:" + P2: O1, "_cov_ts:" + O1: 1, "_vat:" + A1: {"t": 1, "c": "sigA1"}}
cp = os.path.join(sd, "cursor_sol.json")
wj(cp, cur)
spool = os.path.join(sd, "solspool_" + A2 + ".jsonl")
with open(spool, "w", encoding="utf-8") as f:
    f.write('{"signature": "s1"}\n')
k8 = lambda a: "sol:" + a[:8]  # noqa: E731
SOL = {
    "sol": it("live", done=520, total=520),
    k8(O1): it("sigs", done=2), k8(O1) + ":extend": it("done"),
    k8(O2): it("wait"), k8(A1): it("parse"), k8(A2): it("sigs", done=1000), k8(A3): it("sigs", done=3), k8(A3) + ":extend": it("extend"),
    k8(S1): it("sigs"), k8(P1): it("sigs"), k8(R1): it("sigs"), "sol:" + Z: it("sigs"), "sol:" + Z + ":extend": it("extend"), "sol:odd": "x",
}
DROP = {"sol", k8(O1), k8(O1) + ":extend", k8(A1), k8(S1), k8(R1), "sol:" + Z, "sol:" + Z + ":extend"}
bs = os.path.join(sd, "backfill_status.json")
wj(bs, {"sol": SOL, "evm": EVM, "bsc": {"bsc": it("live")}, "_updated": 1})
h_cur, h_sp = sha(cp), sha(spool)
for _mn9 in [m9 for m9 in sys.modules if m9.startswith("sol_")]:
    if hasattr(sys.modules[_mn9], "Rpc"):
        sys.modules[_mn9].Rpc = lambda c9: types.SimpleNamespace()
cfg = {"wallets": [{"type": "sol", "chain": "sol", "address": o} for o in (O1, O2)], "backfill_months": 5,
       "sol": {"rpc": "https://sol-rpc.mock.invalid", "stake": False, "addr_pace_sec": 0}}
wt = sol_watch.SolWatcher(cfg, [O1, O2], types.SimpleNamespace(append=lambda r: None))
n = wt.prune_progress()
d = rj(bs)
left = set(d["sol"])
T.chk(left == set(SOL) - DROP and n == len(DROP), "지운 것 = 끝난(done·live) · 첫 동기화 마친 주소(소유자·토큰 계정·스테이크·뺀 소유자) · 어디에도 없는 주소",
      {"남음": sorted(left), "n": n})
T.chk(k8(O2) in left, "새 소유자(첫 동기화 전 · 커서 없음) 표식 = 그대로")
T.chk(k8(A2) in left, "첫 동기화 스풀 중(_sigbf) 표식 = 그대로")
T.chk(k8(A3) in left and k8(A3) + ":extend" in left, "확장 스풀 중(_sigx) 주소 표식·진행 중 확장(:extend) = 그대로(core 가 진행 중 확장을 기다림)")
T.chk(k8(P1) in left, "앞 8자가 같은 다른 주소(P2)가 차례 대기(미완) = 그 표식 그대로(한쪽이 끝났다고 지우지 않음)")
T.chk("sol:odd" in left, "모르는 꼴(값이 dict 아님) = 그대로")
T.chk(d["evm"] == EVM and d["bsc"] == {"bsc": it("live")}, "다른 유닛(evm·bsc) 그대로")
T.chk(sha(cp) == h_cur and sha(spool) == h_sp, "커서·스풀 파일 그대로(표시 전용)")
T.chk(wt.prune_progress() == 0 and set(rj(bs)["sol"]) == left, "두 번째 기동 = 0(멱등)")
cur2 = dict(cur)
cur2.pop("_sigbf:" + A2)
cur2[A2] = "sigA2"
wj(cp, cur2)
bf_engine._PROGRESS.clear()
wt2 = sol_watch.SolWatcher(cfg, [O1, O2], types.SimpleNamespace(append=lambda r: None))
T.chk(wt2.prune_progress() == 1 and k8(A2) not in rj(bs)["sol"], "스풀이 끝나 커서 확정 → 다음 기동에 그 표식 정리")
src = open(os.path.join(T.SRC, "sol_watch.py"), encoding="utf-8").read()
mi = src.find("def main():")
T.chk(mi > 0 and "w.prune_progress()" in src[mi:src.find("while True:", mi)], "수집기 기동(main) 때 1번 — 사이클 전")

print("[3] 확장 끝 = 확장 스풀이 남긴 주소 표식('sigs')도 정리")
sd = setup("p3")
E1, E2 = ad("Ext1kkkk", 10), ad("Ext2mmmm", 11)
cur3 = {E1: "sigE1", "_cov_ts:" + E1: 2_000_000_000, E2: "sigE2", "_cov_ts:" + E2: 2_000_000_000,
        "_sigbf:" + E2: {"n": 1000, "off": 5, "before": "b", "done": False}}
wj(os.path.join(sd, "cursor_sol.json"), cur3)
wt3 = sol_watch.SolWatcher(dict(cfg, wallets=[{"type": "sol", "chain": "sol", "address": o} for o in (E1, E2)]), [E1, E2],
                           types.SimpleNamespace(append=lambda r: None))
wt3._ext_more = lambda a: True


def spooled(addr, ck, cutoff=None, tag="", gate=None, first_rows=None):
    wt3.progress.update(f"sol:{addr[:8]}", phase="sigs", unit="sigs", done=0, note="서명 수집 중(총량 미상)")
    ck["done"] = True
    return []


wt3._sigs_spooled = spooled
wt3._extend_addrs([E1, E2], 1_000_000_000)
items = wt3.progress.items
T.chk(k8(E1) not in items and (items.get(k8(E1) + ":extend") or {}).get("phase") == "done", "E1 확장 끝 = 확장 표식 done · 주소 표식('sigs') 정리", sorted(items))
T.chk((items.get(k8(E2)) or {}).get("phase") == "sigs", "E2(첫 동기화 스풀 _sigbf 중) = 주소 표식 그대로", items.get(k8(E2)))
fs = rj(os.path.join(sd, "backfill_status.json"))["sol"]
T.chk(k8(E1) not in fs and k8(E2) in fs, "파일에도 같게", sorted(fs))
T.finish()
