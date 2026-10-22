#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import ex_foreign as XF  # noqa: E402
import exf_okx as O  # noqa: E402
import depaddr as DA  # noqa: E402

chk = T.chk
T.patch_moved("PACE", 0, ("exf_", "ex_foreign"))
T.patch_moved("_gov_prepare", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("_srv_ms", lambda *_a, **_k: 1700000000000, ("exf_",))
HTTP = [None]
T.patch_moved("http_json", lambda url, headers=None, **k: HTTP[0](url, headers), ("exf_",))
T0 = 1700000000
ENV = {"TJ_OKX_KEY": "k", "TJ_OKX_SECRET": "s", "TJ_OKX_PASSPHRASE": "p"}


def _ts_list(kind):
    if kind == "b":
        return [(T0 + 5 + (99 - i)) * 1000 for i in range(99)] + [T0 * 1000 + 900, T0 * 1000 + 100]
    if kind == "a":
        return [T0 * 1000 + 999 - i for i in range(101)]
    return [(T0 + 50 - i) * 1000 for i in range(100)] + [(T0 - 60) * 1000]


def _fill_rows(kind):
    return [{"billId": str(9000 - i), "ts": str(ts), "instId": "BTC-USDT", "side": "buy", "fillPx": "100", "fillSz": "1",
             "fee": "0", "feeCcy": "USDT"} for i, ts in enumerate(_ts_list(kind))]


def _bill_pager(rows, calls):
    def fake(url, headers=None, **_k):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        calls.append(q)
        aft = q.get("after", [None])[0]
        start = 0 if aft is None else next(i + 1 for i, r in enumerate(rows) if r["billId"] == aft)
        return {"code": "0", "data": rows[start:start + 100]}
    return fake


def _ts_pager(rows, calls):
    def fake(url, headers=None, **_k):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        calls.append(q)
        aft = q.get("after", [None])[0]
        sel = [r for r in rows if aft is None or int(r["ts"]) < int(aft)]
        return {"code": "0", "data": sel[:100]}
    return fake


print("[1] fills_okx 경계 초")
for kind, want in (("b", 101), ("a", 101)):
    calls = []
    rows = _fill_rows(kind)
    HTTP[0] = _bill_pager(rows, calls)
    got = O.fills_okx(ENV, {}, T0, T0 + 300)
    chk(len(got) == want, f"[1] fills_okx {kind}: 창 안 {want}건 전부 받음(경계 초 안에서 끊긴 페이지도 다음 쪽)", {"got": len(got), "calls": len(calls)})

print("[2] ts 커서 3곳")


def _wd_rows(kind, bucket):
    out = []
    for i, ts in enumerate(_ts_list(kind)):
        if bucket == "w":
            out.append({"wdId": str(5000 - i), "ccy": "USDT", "amt": "1", "fee": "0", "txId": "0x%d" % i, "state": "2", "ts": str(ts),
                        "to": "0xabc", "chain": "USDT-ERC20"})
        else:
            out.append({"depId": str(5000 - i), "ccy": "USDT", "amt": "1", "txId": "0x%d" % i, "state": "2", "ts": str(ts),
                        "chain": "USDT-ERC20", "to": "0xdef"})
    return out


for kind in ("b", "a"):
    W, D = _wd_rows(kind, "w"), _wd_rows(kind, "d")
    calls = []
    pw, pd = _ts_pager(W, calls), _ts_pager(D, calls)
    HTTP[0] = lambda url, headers=None, **k: (pw if "withdrawal" in url else pd)(url, headers)
    w, d = O.fetch_okx(ENV, T0, T0 + 300)
    chk(len(w) == 101 and len(d) == 101, f"[2] fetch_okx {kind}: 출금·입금 101건씩", {"w": len(w), "d": len(d)})
    CV = [{"tradeId": str(7000 - i), "state": "fullyFilled", "ts": str(ts), "side": "buy", "baseCcy": "ETH", "quoteCcy": "USDT",
           "fillBaseSz": "1", "fillQuoteSz": "100"} for i, ts in enumerate(_ts_list(kind))]
    HTTP[0] = _ts_pager(CV, [])
    cv = O.convert_okx(ENV, T0, T0 + 300)
    chk(len(cv) == 101, f"[2] convert_okx {kind}: 101건", {"got": len(cv)})

    class _Cl:
        def __init__(self, rows):
            self.rows, self.calls = rows, []

        def get(self, path, p):
            self.calls.append(dict(p))
            aft = p.get("after")
            return [r for r in self.rows if not aft or int(r["ts"]) < int(aft)][:100]
    cl = _Cl(_wd_rows(kind, "d"))
    addrs = [r for _e, part in DA.hist_okx(cl, T0, T0 + 300) for r in part]
    chk(len(addrs) == 101, f"[2] depaddr.hist_okx {kind}: 이력 101건", {"got": len(addrs), "calls": len(cl.calls)})

print("[3] 멈춤 조건")
calls = []
HTTP[0] = _bill_pager(_fill_rows("deep"), calls)
got = O.fills_okx(ENV, {}, T0, T0 + 300)
chk(len(calls) == 1 and len(got) == 51, "[3] fills_okx: 페이지 끝이 t0 보다 이르면 1쪽에서 멈춤 · t0 이전 체결 제외", {"calls": len(calls), "got": len(got)})
calls = []
W = _wd_rows("deep", "w")
HTTP[0] = _ts_pager(W, calls)
w, d = O.fetch_okx(ENV, T0, T0 + 300)
chk(len(calls) == 2, "[3] fetch_okx: 출금·입금 각 1쪽에서 멈춤(가장 옛 기록 < t0)", {"calls": len(calls)})
calls = []
HTTP[0] = _ts_pager(_wd_rows("b", "w")[:50], calls)
O.fetch_okx(ENV, T0, T0 + 300)
chk(len(calls) == 2, "[3] fetch_okx: 100건 미만 쪽 = 끝", {"calls": len(calls)})
SAME = [{"tradeId": str(100 + i), "state": "fullyFilled", "ts": str(T0 * 1000 + 500), "side": "buy", "baseCcy": "ETH",
         "quoteCcy": "USDT", "fillBaseSz": "1", "fillQuoteSz": "100"} for i in range(150)]
HTTP[0] = _ts_pager(SAME, [])
try:
    O.convert_okx(ENV, T0, T0 + 300)
    chk(False, "[3] convert_okx: 같은 ms 100건 초과 = 미전진 예외(조용한 유실 대신 보류)")
except RuntimeError as e:
    chk("미전진" in str(e), "[3] convert_okx: 같은 ms 100건 초과 = 미전진 예외(조용한 유실 대신 보류)", str(e))

print("[5] fetch_okx 창 이전 행")
PRE = [{"wdId": "w3", "ccy": "BTC", "amt": "0.1", "fee": "0", "txId": "t3", "state": "2", "ts": str((T0 + 30 * 86400) * 1000), "to": "x",
        "chain": "BTC-Bitcoin"},
       {"wdId": "w1", "ccy": "BTC", "amt": "0.2", "fee": "0", "txId": "t1", "state": "2", "ts": str(T0 * 1000), "to": "x", "chain": "BTC-Bitcoin"},
       {"wdId": "w2", "ccy": "BTC", "amt": "5", "fee": "0", "txId": "t2", "state": "2", "ts": str((T0 - 5 * 365 * 86400) * 1000), "to": "x",
        "chain": "BTC-Bitcoin"}]
PRE_D = [{"depId": "d1", "ccy": "XRP", "amt": "16000", "txId": "t9", "state": "2", "ts": str((T0 - 700 * 86400) * 1000), "chain": "XRP-Ripple"}]
pw5, pd5 = _ts_pager(PRE, []), _ts_pager(PRE_D, [])
HTTP[0] = lambda url, headers=None, **k: (pw5 if "withdrawal" in url else pd5)(url, headers)
w, d = O.fetch_okx(ENV, T0, T0 + 300 * 86400)
chk(len(w) == 2 and not d,
    "[5] 창(t0) 이전 출금·입금 = 버림 · t0 ms 정각 행은 받음(창 안 2건 · 입금 0)", {"w": [r.get("created_at") for r in w], "d": len(d)})

print("[4] extension_pass 조각 경계 겹침")
NOW = int(time.time())
WIN = 10 * 86400
B = NOW - WIN - XF.EXT_CHUNK
TOP = NOW - WIN
POOL = [{"id": "gate:X", "ts": B * 1000 + 500}, {"id": "gate:Y", "ts": B * 1000}, {"id": "gate:Z", "ts": B * 1000 + 700},
        {"id": "gate:W", "ts": TOP * 1000 + 300}, {"id": "gate:M", "ts": (B - 86400) * 1000}]


class _Writer:
    def __init__(self):
        self.recs = []

    def append(self, rec):
        self.recs.append(rec)


def _run_ext(lower_bug):
    seen_calls = []

    def fills(env, st, t0, t1):
        seen_calls.append((t0, t1))
        lo = (t0 + 1) * 1000 if lower_bug else t0 * 1000
        return [dict(f) for f in POOL if lo <= f["ts"] <= t1 * 1000 + 999]
    fe0, ff0 = dict(XF.FETCHERS), dict(XF.FILL_FETCHERS)
    XF.FETCHERS.clear()
    XF.FETCHERS["gate"] = (lambda env, a, b: ([], []), ("K",))
    XF.FILL_FETCHERS["gate"] = fills
    try:
        st = {"gate": {"seen": {}}}
        wr = _Writer()
        XF.extension_pass({"K": "1"}, st, wr, NOW - WIN - 2 * XF.EXT_CHUNK - 86400, NOW, WIN)
    finally:
        XF.FETCHERS.clear()
        XF.FETCHERS.update(fe0)
        XF.FILL_FETCHERS.clear()
        XF.FILL_FETCHERS.update(ff0)
    ids = [f["id"] for r in wr.recs if r.get("kind") == "exf_fills" for f in r["fills"]]
    return ids, seen_calls, st


ids, cl4, st4 = _run_ext(True)
chk({"gate:X", "gate:Y", "gate:Z"} <= set(ids), "[4] 위 조각이 경계 초를 놓쳐도 아래 조각이 b*1000~+999 를 다시 봐 회수", {"ids": ids})
chk("gate:W" not in ids, "[4] 첫 조각 위(정규 창 하한 초)는 겹치지 않음(정규 수집 몫)", {"ids": ids})
ids, cl4, st4 = _run_ext(False)
chk(sorted(ids) == ["gate:M", "gate:X", "gate:Y", "gate:Z"], "[4] 바른 수집기: 경계 초 체결 한 번씩만 방출(겹침분은 fills_edge 로 거름)", {"ids": ids})
chk(st4["gate"]["ext"]["fills_from"] <= NOW - WIN - 2 * XF.EXT_CHUNK - 86400, "[4] 확장 완주(하한 = 목표)", st4["gate"]["ext"].get("fills_from"))
chk(cl4 and cl4[0][1] == TOP and all(t1 == t0b + 1 for (_a, t1), (t0b, _b) in zip(cl4[1:], cl4[:-1])),
    "[4] 수집기 호출 = 첫 조각 상한 그대로 · 이후 조각 상한 = 위 조각 하한 + 1초", cl4)

T.finish()
