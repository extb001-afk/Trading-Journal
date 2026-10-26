#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

sys.path.insert(0, T.SRC)
import brokers  # noqa: E402
from brokers import base as bb  # noqa: E402
import _brokerfake as BF  # noqa: E402

chk = T.chk
CFG = {
    "kis": {"enabled": True, "app_key": "SYN-KIS-AK-q1w2", "app_secret": "SYN-KIS-AS-e3r4", "account": "00000000-01"},
    "kiwoom": {"enabled": True, "app_key": "SYN-KW-AK-t5y6", "secret_key": "SYN-KW-SK-u7i8", "us": True},
    "ls": {"enabled": True, "app_key": "SYN-LS-AK-o9p0", "app_secret": "SYN-LS-AS-a1s2", "overseas": True},
    "dbsec": {"enabled": True, "app_key": "SYN-DB-AK-d3f4", "app_secret": "SYN-DB-AS-g5h6", "overseas": True},
    "toss": {"enabled": True, "client_id": "SYN-TS-CI-j7k8", "client_secret": "SYN-TS-CS-l9z0", "cash": True},
    "alpaca": {"enabled": True, "key_id": "SYN-AP-KI-x1c2", "secret_key": "SYN-AP-SK-v3b4"},
    "ibkr": {"enabled": True},
    "schwab": {"enabled": True, "app_key": "SYN-SW-AK-n5m6", "app_secret": "SYN-SW-AS-q7w8", "refresh_token": "SYN-SW-RT-e9r0"},
}
HOST = {"kis": "https://openapi.koreainvestment.com:9443", "kiwoom": "https://api.kiwoom.com", "ls": "https://openapi.ls-sec.co.kr:8080",
        "dbsec": "https://openapi.dbsec.co.kr:8443", "toss": "https://openapi.tossinvest.com", "alpaca": "https://api.alpaca.markets",
        "ibkr": "https://localhost:5000", "schwab": "https://api.schwabapi.com"}
PAGED = {"kis": ("domestic-stock", "q:CTX_AREA_FK100"), "kiwoom": ("/api/dostk/acnt", "h:next-key"), "ls": ("/stock/accno", "b:cts"),
         "dbsec": ("kr-stock/inquiry/balance", "h:cont_key"), "ibkr": ("/positions/", "path")}
TOKEN = ("kis", "kiwoom", "ls", "dbsec", "toss", "schwab")
TABLE = {k: {} for k in CFG}


def run(fk, key, cfg=None):
    return brokers.run_sync(key, dict(cfg or CFG[key]), fk.http, now=lambda: fk.now)


def fresh(key, **kw):
    bb.Adapter._tokens.clear()
    return BF.Fake(key, **kw)


def no_secret(txt, fk, key):
    s = str(txt)
    return not any(v in s for v in list(fk.issued) + [x for x in CFG[key].values() if isinstance(x, str)])


def mark(key, case, ok):
    TABLE[key][case] = "PASS" if ok else "FAIL"


def carry(rq, where):
    if where.startswith("q:"):
        return rq["q"].get(where[2:])
    if where.startswith("h:"):
        return rq["h"].get(where[2:])
    if where == "b:cts":
        return ((rq["b"] or {}).get("t0424InBlock") or {}).get("cts_expcode")
    return rq["path"].rsplit("/", 1)[1]


for key in CFG:
    fk = fresh(key)
    try:
        r = run(fk, key)
        syms = {p["sym"] for p in r.get("positions", [])}
        ok = r.get("ok") is True and syms == fk.served and r["n"] == len(fk.served) and len(r.get("cash") or []) >= 1
        ok = ok and set(fk.hosts) == {HOST[key]} and len(fk.issued) == (1 if key in TOKEN else 0)
        if key == "kis":
            ok = ok and any(p["sym"] == BF.kr(0) and p["qty"] == 100 and p["cur"] == "KRW" for p in r["positions"]) \
                and any(p["sym"] == BF.us(0) and p["cur"] == "USD" for p in r["positions"])
        if key == "alpaca":
            ok = ok and syms == {BF.us(0)}
        if key in TOKEN:
            ok = ok and all(x["h"].get("authorization") == "Bearer " + fk.issued[0] for x in fk.data())
        chk(ok, "[1] %s 잔고 1쪽 — 보유 %d · 예수금 · 호스트 · 토큰 %d번" % (key, len(syms), len(fk.issued)), [r, sorted(fk.served), fk.hosts])
        mark(key, "1쪽", ok)
    finally:
        fk.close()

for key in CFG:
    if key not in PAGED:
        TABLE[key]["2쪽"] = "해당 없음(코드에 연속 조회 없음 · 문서 예시 미확인)"
        continue
    sub, where = PAGED[key]
    fk = fresh(key, pages=2)
    try:
        r = run(fk, key)
        reqs = [x for x in fk.data(sub) if key != "kiwoom" or x["h"].get("api-id") == "kt00018"]
        syms = {p["sym"] for p in r.get("positions", [])}
        want_n = 101 if key == "ibkr" else len(fk.served)
        ok = r.get("ok") is True and fk.served <= syms and r["n"] == want_n and len(reqs) == 2
        ok = ok and str(carry(reqs[0], where) or "0") in ("", "0") and str(carry(reqs[1], where)) in ("K1", "1")
        if key in TOKEN:
            ok = ok and len(fk.issued) == 1
        chk(ok, "[2] %s 2쪽 이어받기 — 두 쪽 보유 · 이어받기 표식 · 요청 2번(%s)" % (key, where), [r, [carry(x, where) for x in reqs], sorted(fk.served)])
        mark(key, "2쪽", ok)
    finally:
        fk.close()
    fk = fresh(key, endless=True)
    try:
        r = run(fk, key)
        n = len(fk.data(sub))
        A = brokers.ADAPTERS[key]
        ok2 = r.get("ok") is False and "연속 조회 상한" in r.get("err", "") and n == A.MAX_PAGES
        chk(ok2, "[2] %s 끝나지 않는 다음 쪽 = 상한 %d쪽에서 멈추고 실패(불완전 목록 반영 안 함)" % (key, A.MAX_PAGES), [r, n])
        TABLE[key]["2쪽"] += "" if ok2 else " · 상한 FAIL"
    finally:
        fk.close()

for key in CFG:
    if key == "alpaca":
        fk = fresh(key)
        try:
            fk.reject_new = True
            r = run(fk, key)
            ok = r.get("ok") is False and "인증 실패" in r.get("err", "") and fk.n401 == 1 and len(fk.log) == 1 and no_secret(r, fk, key)
            chk(ok, "[3] alpaca 고정 키 401 = 실패 · 재시도 0 · 오류 글자에 키 없음", [r, fk.n401])
            mark(key, "토큰", ok)
            TABLE[key]["토큰"] += "(토큰 없음 — 키 401)"
        finally:
            fk.close()
        continue
    if key == "ibkr":
        fk = fresh(key)
        try:
            fk.ib_auth = False
            r = run(fk, key)
            ok = r.get("ok") is False and "로그인" in r.get("err", "") and not fk.data("/positions/")
            chk(ok, "[3] ibkr 게이트웨이 로그인 안 됨 = 실패 · 보유 호출 0", [r, [x["path"] for x in fk.log]])
            mark(key, "토큰", ok)
            TABLE[key]["토큰"] += "(토큰 없음 — 세션 인증)"
        finally:
            fk.close()
        continue
    fk = fresh(key)
    try:
        r1 = run(fk, key)
        d1 = len(fk.data())
        fk.now += 2 * 86400
        r2 = run(fk, key)
        later = fk.data()[d1:]
        oka = r1.get("ok") is True and r2.get("ok") is True and len(fk.issued) == 2 and later \
            and all(x["h"].get("authorization") == "Bearer " + fk.issued[1] for x in later)
        chk(oka, "[3a] %s 시계상 만료 → 다음 동기화에 1번 새로 발급 · 그 동기화 전부 새 토큰" % key, [r2, len(fk.issued)])
    finally:
        fk.close()
    fk = fresh(key)
    try:
        r1 = run(fk, key)
        fk.revoke()
        r2 = run(fk, key)
        okb = r1.get("ok") is True and r2.get("ok") is True and len(fk.issued) == 2 and fk.n401 == 1 \
            and {p["sym"] for p in r2.get("positions", [])} == fk.served
        chk(okb, "[3b] %s 캐시 토큰 401(서버 쪽 만료·무효) → 버리고 1번 재발급 · 같은 동기화에서 성공" % key, [r2, len(fk.issued), fk.n401])
    finally:
        fk.close()
    fk = fresh(key)
    try:
        fk.reject_new = True
        r1 = run(fk, key)
        n1 = (len(fk.issued), fk.n401)
        r2 = run(fk, key)
        okc = r1.get("ok") is False and "인증 실패" in r1.get("err", "") and n1 == (1, 1) and r2.get("ok") is False \
            and len(fk.issued) == 1 and fk.n401 == 2 and no_secret(r1, fk, key) and no_secret(r2, fk, key)
        chk(okc, "[3c] %s 새 토큰도 401 = 실패 · 재시도 루프 없음 · 다음 동기화도 재발급 없음 · 오류에 토큰·비밀 없음" % key, [r1, r2, n1, len(fk.issued), fk.n401])
    finally:
        fk.close()
    TABLE[key]["토큰"] = "만료 %s · 거부 재발급 %s · 거부 루프 없음 %s" % tuple("PASS" if x else "FAIL" for x in (oka, okb, okc))

for key in ("kis", "kiwoom", "ls", "dbsec", "toss"):
    fk = fresh(key)
    try:
        warm = run(fk, key)
        fk.revoke()
        app0, seen = fk.app, set()

        def once(rq, fk=fk, app0=app0, seen=seen):
            t = fk.bearer(rq)
            if t in fk.valid:
                if t in seen:
                    fk.valid.discard(t)
                seen.add(t)
            return app0(rq)

        fk.app = once
        r1 = run(fk, key)
        n1 = (len(fk.issued), fk.n401)
        r2 = run(fk, key)
        ok = warm.get("ok") is True and r1.get("ok") is False and r2.get("ok") is False and n1 == (2, 2) \
            and (len(fk.issued), fk.n401) == (2, 3) and no_secret(r1, fk, key) and no_secret(r2, fk, key)
        chk(ok, "[3d] %s 새 토큰 첫 조회만 되고 다음 401 = 실패 · 다음 동기화 재발급 없음" % key, [r1, r2, n1, len(fk.issued), fk.n401])
        TABLE[key]["토큰"] += " · 부분 401 %s" % ("PASS" if ok else "FAIL")
    finally:
        fk.close()

bb.Adapter._tokens.clear()
for key, row in TABLE.items():
    print("표 %-7s | 1쪽 %s | 2쪽 %s | 토큰 %s" % (key, row.get("1쪽"), row.get("2쪽"), row.get("토큰")))
T.finish()
