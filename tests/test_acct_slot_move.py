#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 2 and sys.argv[1] == "--case":
    import _harness as T  # noqa: E402
    import hashlib  # noqa: E402
    import time  # noqa: E402
    import types  # noqa: E402

    CASE = sys.argv[2]
    os.makedirs(os.path.join(T.TMP, "state"), exist_ok=True)
    os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
    CFG = {"chains": {}, "wallets": [], "backfill_months": 5}
    json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
    json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
    json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
    import core  # noqa: E402
    import ex_foreign as X  # noqa: E402
    import exf_net as N  # noqa: E402
    import onboarding as O  # noqa: E402
    import paths as P  # noqa: E402
    import settings_store as S  # noqa: E402
    import statefile as ST  # noqa: E402

    NOW = int(time.time())
    KM, KA, KAX, KB, KC = "tk-main", "tk-acct-a", "tk-acct-a-rot", "tk-acct-b", "tk-acct-c"
    UID = {KM: "M1", KA: "A1", KAX: "A1", KB: "B1", KC: "C1"}
    PH = {"uid": "M1"}

    def kfp(k):
        return hashlib.sha256(k.encode()).hexdigest()[:8]

    def http(url, headers=None, **kw):
        if "/wallet-balance" in url:
            return 200, {"retCode": 0, "result": {"list": []}}
        if "/query-api" in url:
            return 200, {"retCode": 0, "result": {"readOnly": 1, "permissions": {}, "userID": PH["uid"], "ips": ["127.0.0.1"]}}
        raise AssertionError("시험: 예상 밖 거래소 호출 " + url)

    O._http = http
    O._limited = lambda *a: None

    def grp(tag):
        return "bybit" + ("_sub" + tag[1:] if tag else "")

    def pre(tag):
        return "TJ_BYBIT" + ("_SUB" + tag[1:] if tag else "")

    def save(tag, key):
        PH["uid"] = UID[key]
        return O._dispatch("keys/save", {"group": grp(tag), "values": {pre(tag) + "_KEY": key, pre(tag) + "_SECRET": "tk-secret"}})

    def delete(tag):
        return O._dispatch("keys/delete", {"group": grp(tag)})

    class Writer:
        def __init__(self, *a):
            self.rows = []

        def append(self, r):
            self.rows.append(json.loads(json.dumps(r)))

    WR = []
    X.SegmentWriter = lambda *a: WR.append(Writer()) or WR[-1]
    X.runtime.cpu_reserve_apply = lambda: None
    X.unit_beat.start = lambda *a: None
    X._clock_restore = lambda: None
    X._cool_restore = lambda: None
    X.depaddr.start_background = lambda *a: None
    for mn in ("perp_dex", "liq_watch"):
        sys.modules[mn] = types.SimpleNamespace(start_background=lambda *a, **k: None)
    X.config.load_config = lambda: CFG
    X.convert_rows = lambda *a: []
    for nm in ("dest_backfill_pass", "krw_backfill_pass", "bybit_internal_pass", "pending_recheck_pass", "sub_passes", "futures_snapshot_all", "leverage_pass"):
        setattr(X, nm, lambda *a, **k: None)
    X.ext_trigger_target = lambda *a: None
    QUERIES = []
    ACCT_ROWS = {}

    def acct_of(env):
        return UID.get(env.get("TJ_BYBIT_KEY"))

    def fetch(env, t0, t1):
        return [], [r for t, r in ACCT_ROWS.get(acct_of(env), ([], []))[0] if t0 <= t <= t1]

    def fills(env, st, t0, t1):
        if acct_of(env) != "M1":
            QUERIES.append({"acct": acct_of(env), "days": round((NOW - t0) / 86400, 3)})
        return [f for f in ACCT_ROWS.get(acct_of(env), ([], []))[1] if t0 * 1000 <= int(f["ts"]) <= t1 * 1000]

    BALS = {}

    def bal(env):
        b = N._Bal()
        b.sources = ["spot"]
        b.update(BALS.get(acct_of(env), {}))
        return b

    X.FETCHERS = {"bybit": (fetch, ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"))}
    X.FILL_FETCHERS = {"bybit": fills}
    X.BAL_FETCHERS = {"bybit": bal}

    class Stop(BaseException):
        pass

    def cycle(n=1):
        out = []
        for _ in range(n):
            X.time.sleep = lambda s: (_ for _ in ()).throw(Stop())
            try:
                X.main()
            except Stop:
                pass
            finally:
                X.time.sleep = time.sleep
            out += WR[-1].rows
        return out

    def emitted(rows):
        return sorted({x.get("uuid") or x.get("id") for r in rows for x in (r.get("deposits") or []) + (r.get("fills") or [])})

    def core_prep():
        os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
        for mn in ("perp_dex", "liq_watch"):
            sys.modules.pop(mn, None)
            import importlib
            importlib.import_module(mn).start_background = lambda *a, **k: None
        import config
        import pricing
        config.load_config = lambda *a, **k: CFG
        pricing.PxCache.fx_at = lambda self, ms: 1380.0
        pricing.PxCache.candle_usd = lambda self, sym, ms: 1.0 if str(sym).upper() in ("USDT", "USDC") else None

    def consume(c, rows):
        for rec in rows:
            c._consume_record(rec)
        c.conn.commit()

    def ledger(c):
        q = {r[0]: int(r[1]) / 10 ** 8 for r in c.conn.execute(
            "SELECT a.symbol, SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.location='exchange:bybit' GROUP BY a.symbol")}
        return {"qty": {k: v for k, v in q.items() if v}, "raw": c.conn.execute("SELECT COUNT(*) FROM raw_ex").fetchone()[0],
                "postings": c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0],
                "adjust": c.conn.execute("SELECT COUNT(*) FROM postings WHERE event='EXF_ADJUST'").fetchone()[0]}

    def accts():
        return (((ST.read_json(P.state("exf_state.json"), {}) or {}).get("bybit") or {}).get("accts")) or {}

    out = {"case": CASE}
    if CASE.startswith("n01"):
        dep = (NOW - 7200, N.norm_row("bybit", "p-dep-1", "USDC", "100", "0", "", "ACCEPTED", NOW - 7200, NOW - 7200))
        fb = N.norm_fill("bybit", "p-fill-1", (NOW - 3600) * 1000, "USDT", "USDC", "buy", "1", "100", "0", "USDC")
        fs = N.norm_fill("bybit", "p-fill-2", (NOW - 1800) * 1000, "USDT", "USDC", "sell", "1", "40", "0", "USDC")
        ACCT_ROWS["A1"] = ([dep], [fb, fs])
        BALS["A1"] = {"USDT": 60, "USDC": 40}
        if CASE == "n01_frontlive":
            out["setup"] = [save("", KM).get("ok"), save("s2", KA).get("ok"), save("s3", KB).get("ok")]
        else:
            out["setup"] = [save("", KM).get("ok"), save("s1", KA).get("ok"), save("s2", KB).get("ok")]
        core_prep()
        C = core.Core(CFG)
        C.px.d["neg_ts"]["_fx"] = NOW + 3600
        consume(C, cycle(3))
        out["before"] = ledger(C)
        if CASE == "n01_dupdel":
            S.write_env({"TJ_BYBIT_SUB3_KEY": KA, "TJ_BYBIT_SUB3_SECRET": "tk-secret"})
            kp = dict(S.read_settings().get("key_perm") or {})
            kp["bybit_sub3"] = dict(kp["bybit_sub1"])
            S.update_settings(key_perm=kp)
            consume(C, cycle(2))
            out["dup_first"] = sorted(t for e, t in X._DUP if e == "bybit")
            delete("s1")
            consume(C, cycle(3))
            out["bad"] = sorted(t for e, t in X._IDENT_BAD if e == "bybit")
        elif CASE == "n01_frontlive":
            S.write_env({"TJ_BYBIT_SUB1_KEY": KA, "TJ_BYBIT_SUB1_SECRET": "tk-secret"})
            kp = dict(S.read_settings().get("key_perm") or {})
            kp["bybit_sub1"] = dict(kp["bybit_sub2"])
            S.update_settings(key_perm=kp)
            consume(C, cycle(3))
            out["bad"] = sorted(t for e, t in X._IDENT_BAD if e == "bybit")
        elif CASE == "n01_swap":
            kp = dict(S.read_settings().get("key_perm") or {})
            kp["bybit_sub1"], kp["bybit_sub2"] = kp["bybit_sub2"], kp["bybit_sub1"]
            S.update_settings(key_perm=kp)
            S.write_env({"TJ_BYBIT_SUB1_KEY": KB, "TJ_BYBIT_SUB2_KEY": KA})
            consume(C, cycle(3))
            out["bad"] = sorted(t for e, t in X._IDENT_BAD if e == "bybit")
            out["tags"] = sorted(accts())
        else:
            delete("s1")
            consume(C, cycle(1))
        env0, set0 = S.read_env(), S.read_settings()
        move_key = KAX if CASE == "n01_rot" else KA
        if CASE in ("n01_swap", "n01_dupdel", "n01_frontlive"):
            pass
        elif CASE in ("n01_same", "n01_rot"):
            r = save("s2", move_key)
            out["refused"] = not r.get("ok") and "서브1" in str(r.get("error"))
            out["unchanged"] = S.read_env() == env0 and S.read_settings() == set0
            S.write_env({"TJ_BYBIT_SUB2_KEY": move_key})
            kp = dict(S.read_settings().get("key_perm") or {})
            kp["bybit_sub2"] = {"how": "api", "at": NOW, "uid": "A1", "kfp": kfp(move_key)}
            S.update_settings(key_perm=kp)
            def ident(v):
                return {k: v.get(k) for k in ("uid", "kfp", "seen", "backfilled_until", "fills")} if isinstance(v, dict) else v
            s2_before = ident(accts().get("s2"))
            consume(C, cycle(3))
            out["s2_kept"] = ident(accts().get("s2")) == s2_before and s2_before.get("uid") == "B1"
            out["s2_bad"] = ("bybit", "s2") in X._IDENT_BAD
        elif CASE == "n01_restore":
            out["saved"] = save("s1", KA).get("ok")
            consume(C, cycle(3))
        elif CASE == "n01_other":
            ACCT_ROWS["C1"] = ([dep], [fb, fs])
            BALS["C1"] = {"USDT": 60, "USDC": 40}
            out["saved"] = save("s2", KC).get("ok")
            consume(C, cycle(3))
        elif CASE == "n01_main":
            r = save("", KA)
            out["refused"] = not r.get("ok") and "서브1" in str(r.get("error"))
            out["unchanged"] = S.read_env() == env0 and S.read_settings() == set0
        C._drain_at = NOW + 10
        C.svc_exf._last_exfrecon = 0
        C.svc_exf.exf_recon_pass({"ex"})
        C.conn.commit()
        out["after"] = ledger(C)
        C.conn.close()
    elif CASE.startswith("n02"):
        ACCT_ROWS["B1"] = ([], [N.norm_fill("bybit", "p-fill-b30", (NOW - 30 * 86400) * 1000, "USDT", "USDC", "buy", "1", "100", "0", "USDC")])
        fa = N.norm_fill("bybit", "p-fill-a30", (NOW - 30 * 86400) * 1000, "USDT", "USDC", "buy", "1", "50", "0", "USDC")
        ACCT_ROWS["A1"] = ([], [fa])
        save("", KM)
        S.write_env({"TJ_BYBIT_SUB1_KEY": KA, "TJ_BYBIT_SUB1_SECRET": "tk-secret"})
        kp = dict(S.read_settings().get("key_perm") or {})
        if CASE not in ("n02_noperm", "n02_envsame"):
            kp["bybit_sub1"] = {"how": "api", "at": NOW - 86400}
        S.update_settings(key_perm=kp)
        prog = NOW - 3600
        old = {"seen": {"bybit:p-old-dep": "ACCEPTED"}, "backfilled_until": prog, "added": NOW - 86000,
               "fills": {"seen": {}, "backfilled_until": prog}, "last_bal": {"ts": prog, "b": {"USDT": 50}, "d": {}}}
        ST.atomic_write_json(P.state("exf_state.json"), {"bybit": {"seen": {}, "backfilled_until": prog, "accts": {"s1": old}}})
        led = None
        if CASE == "n02_rot":
            core_prep()
            led = core.Core(CFG)
            led.px.d["neg_ts"]["_fx"] = NOW + 3600
            consume(led, [{"v": 1, "kind": "exf_fills", "exchange": "bybit", "ts": prog, "fills": [dict(fa, id="bybit:s1:p-fill-a30", acct="s1")]}])
            out["before"] = ledger(led)
        if CASE == "n02_delre":
            out["deleted"] = delete("s1").get("ok")
        key = {"n02_delre": KA, "n02_diff": KB, "n02_restore": KB, "n02_resave": KA, "n02_rot": KAX, "n02_envsame": KA}.get(CASE)
        if key:
            out["saved"] = save("s1", key).get("ok")
        rows = cycle(2)
        out["emitted"] = emitted(rows)
        out["queries"] = [q["days"] for q in QUERIES]
        a = accts()
        out["tags"] = sorted(a)
        out["s1_uid"], out["s1_kfp_is"] = a.get("s1", {}).get("uid"), {kfp(k): k for k in (KA, KAX, KB)}.get(a.get("s1", {}).get("kfp"))
        out["kept_seen"] = "bybit:p-old-dep" in (a.get("s1", {}).get("seen") or {})
        if CASE == "n02_restore":
            del QUERIES[:]
            out["saved2"] = save("s1", KA).get("ok")
            rows2 = cycle(2)
            a = accts()
            out["emitted2"], out["queries2"], out["tags2"] = emitted(rows2), [q["days"] for q in QUERIES], sorted(a)
            out["kept_seen2"] = "bybit:p-old-dep" in (a.get("s1", {}).get("seen") or {})
        if led is not None:
            consume(led, rows)
            out["after"] = ledger(led)
            led.conn.close()
    elif CASE == "keytimes":
        save("", KM)
        r1 = save("s1", KA)
        k1 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        kp = dict(S.read_settings().get("key_perm") or {})
        kp["bybit_sub1"] = dict(k1, at=NOW - 500, kat=NOW - 500)
        S.update_settings(key_perm=kp)
        save("s1", KA)
        k2 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        save("s1", KB)
        k3 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        save("s1", KB)
        k4 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        S.write_env({"TJ_BYBIT_SUB1_KEY": KC})
        save("s1", KC)
        k5 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        kp = dict(S.read_settings().get("key_perm") or {})
        kp.pop("bybit_sub1", None)
        S.update_settings(key_perm=kp or None)
        save("s1", KC)
        k6 = dict((S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {})
        out.update(k5_handedit=k5.get("kat", 0) >= NOW and k5.get("pkfp") == kfp(KB) and k5.get("pkat") == k4.get("kat") and k5.get("kkfp") == kfp(KC),
                   k6_envonly=k6.get("kat") == 0 and "pkfp" not in k6)
        out.update(ok=r1.get("ok"), k1_kat_eq_at=k1.get("kat") == k1.get("at") and "pkfp" not in k1,
                   k2_kat_kept=k2.get("kat") == NOW - 500 and k2.get("at", 0) >= NOW,
                   k3_changed=k3.get("kat", 0) >= NOW and k3.get("pkfp") == kfp(KA) and k3.get("pkat") == NOW - 500,
                   k4_carry=k4.get("kat") == k3.get("kat") and k4.get("pkfp") == kfp(KA) and k4.get("pkat") == NOW - 500)
    elif CASE == "units":
        hist = {"seen": {"bybit:x": "ACCEPTED"}, "backfilled_until": NOW - 3600, "fills": {"seen": {}, "backfilled_until": NOW - 3600}}
        out["mismatch"] = list(X._legacy_same(dict(hist), {"how": "api", "at": NOW, "kat": NOW, "kkfp": "0" * 8}, kfp(KB)))
        out["late_save"] = list(X._legacy_same(dict(hist), {"how": "api", "at": NOW, "kat": NOW, "kkfp": kfp(KB), "pkfp": kfp(KA), "pkat": NOW - 86400}, kfp(KB)))
        st = {"bybit": {"seen": {}, "accts": {"s1": dict(hist)}}}
        kp = {"bybit_sub1": {"how": "api", "at": NOW, "kat": NOW, "kkfp": kfp(KB), "uid": "B1", "kfp": kfp(KB), "pkfp": kfp(KA), "pkat": NOW - 86400}}
        X.acct_ident(st, "bybit", "s1", KB, kp, NOW)
        a = st["bybit"]["accts"]
        out["split"] = {"tags": sorted(a), "retag": list(st["bybit"].get("fut_retag") or []), "keep": sorted(t for t, v in a.items() if v.get("fut_keep"))}
        kp2 = {"bybit_sub1": {"how": "api", "at": NOW, "kat": NOW, "kkfp": kfp(KA), "pkfp": kfp(KB), "pkat": NOW}}
        X.acct_ident(st, "bybit", "s1", KA, kp2, NOW)
        a = st["bybit"]["accts"]
        out["restore"] = {"tags": sorted(a), "retag": st["bybit"].get("fut_retag"), "seen": a["s1"].get("seen")}
    out["net"] = list(T.NET_TRIES)
    T.case_emit(out)
    sys.exit(0)

import _harness as T  # noqa: E402


def child(case):
    return T.case_run([sys.executable, os.path.abspath(__file__), "--case", case], cwd=HERE)


BASE = {"qty": {"USDT": 60.0, "USDC": 40.0}, "raw": 3}
for case, what in (("n01_same", "같은 키"), ("n01_rot", "같은 UID 다른 키")):
    r = child(case)
    b, a = r.get("before") or {}, r.get("after") or {}
    T.chk(r.get("setup") == [True, True, True] and {k: b.get(k) for k in BASE} == BASE, f"N01 준비({what}): A 입금 1·매수·매도 = USDT 60 · USDC 40 · 원본 3", r)
    T.chk(r.get("refused") is True and r.get("unchanged") is True,
          f"N01a/b {what}: 지운 서브1 계정 A 를 서브2 에 저장 = 거부(원래 칸 안내 · .env·설정 그대로 — 종전: 서브2 에서 처음부터 다시 받아 두 번 기장)", r)
    T.chk(a == b and a.get("adjust") == 0 and r.get("s2_kept") is True and r.get("s2_bad") is True and not r.get("net"),
          f"N01a/b {what}: 손으로 .env 를 고쳐 넣어도 수집기가 서브2 를 뺌 — 원장 사건·분개·수량 그대로(USDT 60 · 보정 0) · 서브2 옛 상태 그대로 · 재시작 3주기", r)
r = child("n01_restore")
T.chk(r.get("saved") is True and r.get("after") == r.get("before") and (r.get("after") or {}).get("adjust") == 0,
      "N01c 원래 칸(서브1)에 다시 = 저장 됨 · 되살림(다시 안 받음 · 원장 그대로)", r)
r = child("n01_other")
T.chk(r.get("saved") is True and (r.get("after") or {}).get("qty") == {"USDT": 120.0, "USDC": 80.0} and (r.get("after") or {}).get("raw") == 6,
      "N01d 진짜 다른 계정 C(같은 거래소 번호) = 서브2 에 저장 됨 · 따로 기장(번호만으로 합치지 않음)", r)
r = child("n01_dupdel")
T.chk(r.get("dup_first") == ["s3"] and r.get("after") == r.get("before") and "s3" in (r.get("bad") or ()),
      "N01g 같은 계정 두 칸(뒤 칸 빼고 셈) → 앞 칸 키 지움 = 뒤 칸(이력 없는 상태)도 처음부터 안 받음 · 원장 그대로", r)
r = child("n01_frontlive")
T.chk(r.get("setup") == [True, True, True] and r.get("after") == r.get("before") and (r.get("after") or {}).get("adjust") == 0 and "s1" in (r.get("bad") or ()),
      "N01h 이력 있는 뒤 칸(서브2) 계정을 손으로 앞 빈 칸(서브1)에도 넣음 = 앞 칸이 처음부터 받지 않음(같은 계정 두 칸은 앞 칸이 남고 뒤 칸이 빠지므로"
      " 뒤 칸 이력 = 다른 칸 이력) · 원장 그대로", r)
r = child("n01_swap")
T.chk(r.get("after") == r.get("before") and r.get("bad") == ["s1", "s2"] and r.get("tags") == ["s1", "s2"],
      "N01f 두 칸 키를 손으로 맞바꿈 = 두 칸 모두 뺌(앞 칸이 뒤 칸의 묵은 상태를 못 보고 처음부터 받던 구멍) · 원장 그대로 · 보관본 안 만듦", r)
r = child("n01_main")
T.chk(r.get("refused") is True and r.get("unchanged") is True, "N01e 지운 서브1 계정 A 를 메인 칸에 저장 = 거부", r)

r = child("n02_diff")
T.chk(r.get("saved") is True and r.get("emitted") == ["bybit:s1:p-fill-b30"] and r.get("queries", [0])[0] == 150.0
      and r.get("s1_uid") == "B1" and r.get("tags") == ["s1", "s1@k" + __import__("hashlib").sha256(b"tk-acct-a").hexdigest()[:8]] and not r.get("kept_seen"),
      "N02a 정체 없는 옛 상태 + 마지막 주기 뒤 다른 계정 키 저장 = 채택 안 함 — 옛 상태 's1@k<옛 키 지문>' · B 처음부터(150일 · 30일 전 체결 1건) · 재시작 둘째 주기 다시 안 받음"
      "(종전: B 가 A 커서 이어받아 3일만 조회 · 0건)", r)
r = child("n02_resave")
T.chk(r.get("saved") is True and r.get("emitted") == [] and r.get("queries", [0])[0] == 3.0 and r.get("tags") == ["s1"]
      and r.get("s1_uid") == "A1" and r.get("s1_kfp_is") == "tk-acct-a" and r.get("kept_seen"),
      "N02b 같은 키 다시 저장(첫 UID 확보) = 이어 감(UID·지문만 채움 · 다시 안 받음)", r)
r = child("n02_live")
T.chk(r.get("emitted") == [] and r.get("queries", [0])[0] == 3.0 and r.get("tags") == ["s1"] and r.get("s1_kfp_is") == "tk-acct-a" and r.get("kept_seen"),
      "N02c 저장 없음(키 저장 = 마지막 주기보다 앞 · 라이브 꼴) = 이어 감(지문만 채움 · 이행 0)", r)
r = child("n02_noperm")
T.chk(r.get("emitted") == [] and r.get("tags") == ["s1"] and r.get("kept_seen"), "N02d 저장 기록 없음(.env 로 넣은 키) = 근거 없음 → 종전대로 이어 감", r)
r = child("n02_restore")
T.chk(r.get("saved2") is True and r.get("emitted2") == [] and r.get("queries2", [0])[0] == 3.0 and r.get("kept_seen2")
      and len(r.get("tags2") or ()) == 2 and any(t.startswith("s1@u") for t in r.get("tags2") or ()),
      "N02e 옛 키 A 를 다시 넣음 = 지문 단 보관본 되살림(다시 안 받음) · B 는 's1@u<UID>' 로 물림", r)
r = child("n02_rot")
T.chk(r.get("saved") is True and r.get("emitted") == ["bybit:s1:p-fill-a30"] and r.get("after") == r.get("before") and (r.get("after") or {}).get("adjust") == 0,
      "N02f 같은 계정 다른 키(UID 모르던 옛 상태 = 가릴 수 없음) = 새로 받지만 같은 칸 이름 = 원장 멱등(이중 기장 0)", r)
r = child("n02_delre")
T.chk(r.get("deleted") is True and r.get("saved") is True and r.get("emitted") == [] and r.get("tags") == ["s1"] and r.get("kept_seen"),
      "N02j 옛 상태 칸 키를 지웠다 같은 키를 다시 넣음 = 이어 감(지우기 묘비가 키 시각을 이어 줌)", r)
r = child("n02_envsame")
T.chk(r.get("saved") is True and r.get("emitted") == [] and r.get("tags") == ["s1"] and r.get("kept_seen"),
      "N02g .env 로만 넣은 키(기록 없음)를 화면에서 같은 값으로 저장 = 이어 감(넣은 때 모름 = 0)", r)
r = child("units")
ka8 = __import__("hashlib").sha256(b"tk-acct-a").hexdigest()[:8]
T.chk(r.get("mismatch") == [True, None] and r.get("late_save") == [False, ka8],
      "N02h 기록 키 지문 ≠ 이번 주기 키(.env 읽은 직후 저장이 겹침 · 손편집) = 이 키의 시각 근거 없음 → 채택(종전) · 늦은 저장 = 분리 + 바뀌기 전 키 지문", r)
T.chk((r.get("split") or {}).get("tags") == ["s1", "s1@k" + ka8] and (r.get("split") or {}).get("retag") == [["s1", "s1", "unraw"]]
      and (r.get("split") or {}).get("keep") == ["s1", "s1@k" + ka8],
      "N02i 정체 모르는 옛 상태 분리 = 선물 정산 딱지 안 옮김(fut_keep · 같은 계정이면 다시 받아 두 번 셈) · 그 칸 원본(커서)만 치움 일지"
      "(정산은 정본에 같은 딱지로 · 새 계정은 처음 창부터)", r)
T.chk((r.get("restore") or {}).get("retag") == [["s1", "s1", "unraw"], ["s1", "s1", "unraw"]] and (r.get("restore") or {}).get("seen") == {"bybit:x": "ACCEPTED"}
      and any(t.startswith("s1@u") for t in (r.get("restore") or {}).get("tags") or ()),
      "N02i 그 줄기의 되살림·다른 계정 물림도 선물 딱지 안 옮김(옛 상태 seen 되살림) · 다른 계정으로 바뀔 때마다 그 칸 원본(커서)만 치움 일지", r)
r = child("keytimes")
T.chk(r.get("ok") is True and r.get("k1_kat_eq_at") and r.get("k2_kat_kept") and r.get("k3_changed") and r.get("k4_carry") and r.get("k5_handedit") and r.get("k6_envonly"),
      "K 키 저장 기록 — 첫 저장 kat=at · 같은 키 다시 저장 = kat 그대로 · 바뀐 키 = pkfp·pkat(바뀌기 전 키) · 다시 저장해도 이어 받음 ·"
      " .env 손편집 뒤 같은 값 저장 = 바뀐 것(pkfp = 기록 키) · 기록 없는 .env 키 같은 값 저장 = kat 0", r)
T.finish()
