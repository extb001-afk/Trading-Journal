#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ton_watch as tw  # noqa: E402


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


A, X, JW = "0:" + "a1" * 32, "0:" + "c3" * 32, "0:" + "e5" * 32
V, TF = 30_000_000, 300


def ct(src, tr):
    return {"a": A, "h": "h1", "lt": 10, "now": 1760000000, "tr": tr, "in": {"src": src, "val": V, "op": tw.OP_EXCESS, "b": False},
            "out": [], "tf": TF, "bb": 1_000_000_000, "ba": 1_000_000_000 + V - TF}


e1 = tw.wallet_effect(ct(X, "t9"), frozenset(), roots={"root1": 1})
chk("X1 남이 보낸 excess(내 trace 아님) = 환급 아님 · 받은 TON 이동 · 수수료 = tf", e1["fee"] == TF and (X, A, V) in e1["moves"] and ":refund" not in e1["ev"], e1)
e2 = tw.wallet_effect(ct(X, "root1"), frozenset(), roots={"root1": 1})
chk("X2 내 trace 안 excess = 환급(음수 수수료 · 이동 없음)", e2["fee"] == TF - V and not e2["moves"] and ":refund" in e2["ev"], e2)
e3 = tw.wallet_effect(ct(JW, "t9"), frozenset({JW}), roots={"root1": 1})
chk("X2 내 제톤 지갑이 보낸 excess = 환급", e3["fee"] == TF - V and not e3["moves"], e3)
e4 = tw.wallet_effect(ct(X, "t9"), frozenset())
chk("X3 roots 없음 = 종전(환급)", e4["fee"] == TF - V, e4)
T.finish()
