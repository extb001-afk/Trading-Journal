#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import types  # noqa: E402

import perp_dex as P  # noqa: E402


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


ctx = types.SimpleNamespace(dex="gmx", t0=1_700_000_000_000)
pos, tof = (lambda x: x["p"]), (lambda x: x["t"])
for name in ("desc_pages", "page_pages"):
    data, calls, got, st = [], [], [], {}
    if name == "desc_pages":
        def run():
            P.desc_pages(ctx, st, "k", lambda before: calls.append(before) or [x for x in sorted(data, key=pos, reverse=True)
                                                                               if before is None or x["p"] < before], pos, tof, got.append, 100)
    else:
        def run():
            P.page_pages(ctx, st, "k", lambda pg: calls.append(pg) or (sorted(data, key=pos, reverse=True) if pg == 1 else []), pos, tof,
                         got.append, 100)
    run()
    data.append({"p": 5, "t": ctx.t0 + 1000})
    calls.clear()
    run()
    tag = "E1" if name == "desc_pages" else "E2"
    chk(f"{tag} {name}: 빈 첫 조회 뒤 새 기록 = 다음 주기에 처리 · top 확정", len(got) == 1 and st["k"].get("top") == 5 and len(calls) >= 1,
        {"got": got, "st": st, "calls": calls})
    data.append({"p": 9, "t": ctx.t0 + 2000})
    calls.clear()
    run()
    chk(f"{tag}/E3 {name}: top 있음 = 증분만(새 기록 처리 · 1콜 · 과거 재순회 없음 — top 경계 1건 겹침은 종전대로 uid 가 흡수)",
        9 in {g["p"] for g in got} and len(calls) == 1 and st["k"].get("top") == 9, {"got": got, "calls": calls})
T.finish()
