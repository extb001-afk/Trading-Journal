#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 2 and sys.argv[1] == "--case":
    import _harness as T  # noqa: E402
    import hashlib  # noqa: E402
    import shutil  # noqa: E402
    import time  # noqa: E402
    import types  # noqa: E402
    import urllib.parse  # noqa: E402
    from unittest.mock import patch  # noqa: E402

    CASE = sys.argv[2]
    for d in ("state", "seed"):
        os.makedirs(os.path.join(T.TMP, d), exist_ok=True)
    CFG = {"chains": {}, "wallets": [], "backfill_months": 5}
    json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
    json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
    json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
    os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
    sys.path.insert(0, os.path.join(T.ROOT, "tools"))
    import core  # noqa: E402
    import ex_foreign as X  # noqa: E402
    import exf_net as N  # noqa: E402
    import onboarding as O  # noqa: E402
    import paths as P  # noqa: E402
    import settings_store as S  # noqa: E402
    import statefile as ST  # noqa: E402

    NOW, DAY = int(time.time()), 86400
    KM, KA, KB, KC = "tk-main", "tk-acct-a", "tk-acct-b", "tk-acct-c"
    UID = {KM: "M1", KA: "A1", KB: "B1", KC: "C1"}
    PH = {"uid": "M1"}

    def kfp(k):
        return hashlib.sha256(k.encode()).hexdigest()[:8]

    def http(url, *a, **kw):
        if "/wallet-balance" in url:
            return 200, {"retCode": 0, "result": {"list": []}}
        if "/query-api" in url:
            return 200, {"retCode": 0, "result": {"readOnly": 1, "permissions": {}, "userID": PH["uid"], "ips": ["127.0.0.1"]}}
        raise AssertionError("시험: 예상 밖 거래소 호출 " + url)

    O._http = http
    O._limited = lambda *a: None

    def save(tag, key):
        PH["uid"] = UID[key]
        pre = "TJ_BYBIT" + ("_SUB" + tag[1:] if tag else "")
        return O._dispatch("keys/save", {"group": "bybit" + ("_sub" + tag[1:] if tag else ""), "values": {pre + "_KEY": key, pre + "_SECRET": "tk-secret"}})

    class Writer:
        def __init__(self, *a):
            self.rows = []

        def append(self, r):
            self.rows.append(json.loads(json.dumps(r)))

    WR, QUERIES, ROWS, BALS = [], [], {}, {}
    X.SegmentWriter = lambda *a: WR.append(Writer()) or WR[-1]
    X.runtime.cpu_reserve_apply = lambda: None
    X.unit_beat.start = lambda *a: None
    X._clock_restore = lambda: None
    X._cool_restore = lambda: None
    X.depaddr.start_background = lambda *a: None
    for mn in ("perp_dex", "liq_watch"):
        sys.modules[mn] = types.SimpleNamespace(start_background=lambda *a, **k: None)
    X.config.load_config = lambda *a, **k: CFG
    X.convert_rows = lambda *a: []
    for nm in ("dest_backfill_pass", "krw_backfill_pass", "bybit_internal_pass", "pending_recheck_pass", "sub_passes", "leverage_pass"):
        setattr(X, nm, lambda *a, **k: None)
    X.ext_trigger_target = lambda *a: None

    def acct(env):
        return UID.get(env.get("TJ_BYBIT_KEY"))

    def fetch(env, t0, t1):
        return [], [r for t, r in ROWS.get(acct(env), ([], []))[0] if t0 <= t <= t1]

    def fills(env, st, t0, t1):
        QUERIES.append({"acct": acct(env), "days": round((NOW - t0) / DAY, 3)})
        return [r for r in ROWS.get(acct(env), ([], []))[1] if t0 * 1000 <= r["ts"] <= t1 * 1000]

    def bal(env):
        b = N._Bal()
        b.sources = ["spot"]
        b.update(BALS.get(acct(env), {}))
        return b

    X.FETCHERS = {"bybit": (fetch, ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"))}
    X.FILL_FETCHERS = {"bybit": fills}
    X.BAL_FETCHERS = {"bybit": bal}

    class Stop(BaseException):
        pass

    def cycle(n=1):
        rows = []
        for _ in range(n):
            with patch.object(X.time, "sleep", lambda s: (_ for _ in ()).throw(Stop())), patch.object(X, "futures_snapshot_all", lambda *a: None):
                try:
                    X.main()
                except Stop:
                    pass
            rows += WR[-1].rows
        return rows

    def consume(c, rows):
        for r in rows:
            c._consume_record(r)
        c.conn.commit()

    def ledger(c):
        q = {r[0]: int(r[1]) / 1e8 for r in c.conn.execute(
            "SELECT a.symbol, SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
            " WHERE p.location='exchange:bybit' GROUP BY a.symbol")}
        return {"qty": {k: v for k, v in q.items() if v}, "raw": c.conn.execute("SELECT COUNT(*) FROM raw_ex").fetchone()[0],
                "postings": c.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0],
                "adjust": c.conn.execute("SELECT COUNT(*) FROM postings WHERE event='EXF_ADJUST'").fetchone()[0]}

    def mk_core():
        import config
        import pricing
        config.load_config = lambda *a, **k: CFG
        pricing.PxCache.fx_at = lambda self, ms: 1380.0
        pricing.PxCache.candle_usd = lambda self, sym, ms: 1.0 if str(sym).upper() in ("USDT", "USDC") else None
        c = core.Core(CFG)
        c.px.d["neg_ts"]["_fx"] = NOW + 3600
        return c

    def rj(name):
        return ST.read_json(P.state(name), None) if os.path.exists(P.state(name)) else None

    out = {"case": CASE}
    if CASE.startswith("r_"):
        import ledger_backup as L
        import ledger_restore as R
        dep = N.norm_row("bybit", "tk-dep", "USDC", "120", "0", "", "ACCEPTED", NOW - 7200, NOW - 7200)
        buy = N.norm_fill("bybit", "tk-buy", (NOW - 3600) * 1000, "USDT", "USDC", "buy", "1", "120", "0", "USDC")
        sell = N.norm_fill("bybit", "tk-sell", (NOW - 1800) * 1000, "USDT", "USDC", "sell", "1", "45", "0", "USDC")
        ROWS["A1"] = ([(NOW - 7200, dep)], [buy, sell])
        BALS["A1"] = {"USDT": 75, "USDC": 45}
        out["setup"] = [save("", KM).get("ok"), save("s1", KA).get("ok"), save("s2", KB).get("ok")]
        c = mk_core()
        consume(c, cycle(2))
        out["before"] = ledger(c)
        O._dispatch("keys/delete", {"group": "bybit_sub1"})
        consume(c, cycle())
        b = L.run_once()
        day = b["last_date"]
        out["map_backed_up"] = os.path.isfile(P.state("backups", "files_" + day, "exf_ident.json"))
        c.conn.close()
        for n in os.listdir(P.STATE_DIR):
            if n != "backups":
                p = os.path.join(P.STATE_DIR, n)
                shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
        if CASE == "r_oldbak":
            os.unlink(P.state("backups", "files_" + day, "exf_ident.json"))
        R.apply(R.plan(b["last_path"], streams=["ex"]), proc_check=False)
        fp = R.files_plan(day)
        out["hold"], out["warn"] = fp.get("hold"), fp.get("warn")
        out["restored"] = R.files_apply(fp, proc_check=False, log=lambda *a: None)["restored"]
        c = mk_core()
        out["after_restore"] = ledger(c)
        if CASE == "r_move":
            r = save("s2", KA)
            out["refused"] = not r.get("ok") and "서브1" in str(r.get("error"))
            S.write_env({"TJ_BYBIT_SUB2_KEY": KA})
            kp = dict(S.read_settings().get("key_perm") or {})
            kp["bybit_sub2"] = {"how": "api", "at": NOW, "uid": "A1", "kfp": kfp(KA)}
            S.update_settings(key_perm=kp)
        elif CASE == "r_same":
            out["saved"] = save("s1", KA).get("ok")
        elif CASE == "r_main":
            S.write_env({"TJ_BYBIT_KEY": KA})
        elif CASE == "r_oldbak":
            r = save("s2", KA)
            out["held"] = not r.get("ok") and "어느 계정인지 몰라요" in str(r.get("error"))
            out["saved"] = save("s1", KA).get("ok")
            consume(c, cycle(2))
            ROWS["C1"] = ([(NOW - 7200, dep)], [buy, sell])
            BALS["C1"] = {"USDT": 75, "USDC": 45}
            out["saved_c"] = save("s2", KC).get("ok")
        elif CASE == "r_other":
            ROWS["C1"] = ([(NOW - 7200, dep)], [buy, sell])
            BALS["C1"] = {"USDT": 75, "USDC": 45}
            out["saved"] = save("s2", KC).get("ok")
        consume(c, cycle(3))
        out["after"] = ledger(c)
        out["bad"] = sorted(t for e, t in X._IDENT_BAD if e == "bybit")
        out["mhold"] = ((rj("exf_state.json") or {}).get("bybit") or {}).get("main_hold")
        c.conn.close()
    elif CASE.startswith("m_"):
        import chk_collect as CC
        dep = N.norm_row("bybit", "tk-dep", "USDC", "120", "0", "", "ACCEPTED", NOW - 7200, NOW - 7200)
        buy = N.norm_fill("bybit", "tk-buy", (NOW - 3600) * 1000, "USDT", "USDC", "buy", "1", "120", "0", "USDC")
        sell = N.norm_fill("bybit", "tk-sell", (NOW - 1800) * 1000, "USDT", "USDC", "sell", "1", "45", "0", "USDC")
        ROWS["A1"] = ([(NOW - 7200, dep)], [buy, sell])
        BALS["A1"] = {"USDT": 75, "USDC": 45}
        out["setup"] = [save("", KM).get("ok"), save("s1", KA).get("ok"), save("s2", KB).get("ok")]
        c = mk_core()
        consume(c, cycle(2))
        out["before"] = ledger(c)
        out["main_id"] = ((rj("exf_state.json") or {}).get("bybit") or {}).get("main_id")
        if CASE != "m_dup":
            O._dispatch("keys/delete", {"group": "bybit_sub1"})
            consume(c, cycle())

        def mstate():
            stb = (rj("exf_state.json") or {}).get("bybit") or {}
            return stb.get("main_hold"), stb.get("main_id"), [[x["cid"], x["level"]] for x in CC.collect_exf_hold(time.time())]
        out["bal0"] = sorted(n for n in ("exf_balances_bybit.json", "exf_balances_bybit.json.pending") if os.path.exists(P.state(n)))
        if CASE in ("m_move", "m_dup"):
            out["refused"] = not save("", KA).get("ok")
            S.write_env({"TJ_BYBIT_KEY": KA})
        elif CASE == "m_first":
            st0 = rj("exf_state.json")
            st0["bybit"].pop("main_id", None)
            ST.atomic_write_json(P.state("exf_state.json"), st0)
        elif CASE == "m_other":
            ROWS["C1"] = ([], [N.norm_fill("bybit", "tk-c-buy", (NOW - 600) * 1000, "USDT", "USDC", "buy", "1", "10", "0", "USDC")])
            S.write_env({"TJ_BYBIT_KEY": KC})
        elif CASE == "m_rot":
            UID["tk-main-2"] = "M1"
            out["saved"] = save("", "tk-main-2").get("ok")
        consume(c, cycle(3))
        out["after"] = ledger(c)
        out["hold"], out["main_id2"], out["panel"] = mstate()
        out["bal"] = sorted(n for n in ("exf_balances_bybit.json", "exf_balances_bybit.json.pending") if os.path.exists(P.state(n)))
        if CASE in ("m_move", "m_dup"):
            S.write_env({"TJ_BYBIT_KEY": KM})
            consume(c, cycle(2))
            out["after2"] = ledger(c)
            out["hold2"], _m, out["panel2"] = mstate()
        c.conn.close()
    elif CASE.startswith("s_"):
        import ledger_restore as R
        save("", KM)
        S.write_env({"TJ_BYBIT_SUB1_KEY": KA, "TJ_BYBIT_SUB1_SECRET": "tk-secret"})
        kp = dict(S.read_settings().get("key_perm") or {})
        kp["bybit_sub1"] = {"how": "api", "at": NOW - DAY, "kkfp": kfp(KA), "kat": NOW - DAY}
        S.update_settings(key_perm=kp)
        old_settings = S.read_settings()
        hist = {"seen": {"bybit:tk-old": "ACCEPTED"}, "backfilled_until": NOW - 3600, "fills": {"seen": {}, "backfilled_until": NOW - 3600}}
        ST.atomic_write_json(P.state("exf_state.json"), {"bybit": {"seen": {}, "backfilled_until": NOW - 3600, "accts": {"s1": hist}}})
        ROWS["B1"] = ([], [N.norm_fill("bybit", "tk-b30", (NOW - 30 * DAY) * 1000, "USDT", "USDC", "buy", "1", "99", "0", "USDC")])
        out["saved"] = save("s1", KB).get("ok")
        if CASE == "s_restore":
            ST.atomic_write_json(P.state("backups", "files_20260105", "settings.json"), old_settings)
            out["restored"] = R.files_apply(R.files_plan("20260105"), proc_check=False, log=lambda *a: None)["restored"]
            kp9 = (S.read_settings().get("key_perm") or {}).get("bybit_sub1") or {}
            out["kp_kept"] = kp9.get("kkfp") == kfp(KB)
        rows = cycle(2)
        out["fills"] = sorted(f["id"] for r in rows for f in r.get("fills") or [])
        out["b_days"] = [q["days"] for q in QUERIES if q["acct"] == "B1"]
    elif CASE.startswith("f_"):
        import exf_binance as BN
        import ledger_backup as L
        import ledger_restore as R
        EX = "binance"
        A_EV = {"t": (NOW - 3600) * 1000, "uid": "bn:tk-a:REALIZED_PNL:1", "amount": 3.0, "symbol": "ETHUSDT", "kind": "REALIZED"}
        oldraw = {"ts": NOW - 3600, "events": [A_EV], "wallet": {"balance": 0}, "positions": [], "cursor": {"income": (NOW - 3600) * 1000}}
        hist = {"seen": {"binance:tk-old": "ACCEPTED"}, "backfilled_until": NOW - 3600}
        state = {EX: {"accts": {"s1": dict(hist)}, "seen": {}}}
        kperm = {EX + "_sub1": {"uid": "B1", "kfp": kfp(KB), "kkfp": kfp(KB), "kat": NOW, "at": NOW, "pkfp": kfp(KA), "pkat": NOW - DAY}}
        if CASE in ("f_changed", "f_same"):
            state[EX]["accts"]["s1"].update(uid="A1", kfp=kfp(KA))
            ST.atomic_write_json(P.state("futraw_binance_s1.json"), oldraw)
            ST.atomic_write_json(P.state("futures_binance.json"), dict(oldraw, events=[dict(A_EV, acct="s1")], accts=["main", "s1"]))
            ST.atomic_write_json(P.state("exf_state.json"), state)
            L.backup_files("20260105", P.STATE_DIR)
            if CASE == "f_same":
                kperm = {EX + "_sub1": {"uid": "A1", "kfp": kfp("tk-acct-a2"), "kkfp": kfp("tk-acct-a2"), "kat": NOW, "at": NOW}}
                X.acct_ident(state, EX, "s1", "tk-acct-a2", kperm, NOW)
            else:
                X.acct_ident(state, EX, "s1", KB, kperm, NOW)
            X._fut_retag_pending(state, EX)
            ST.atomic_write_json(P.state("exf_state.json"), state)
            for n in ("futures_binance.json", "futraw_binance_s1.json"):
                if os.path.exists(P.state(n)):
                    os.unlink(P.state(n))
            fp = R.files_plan("20260105")
            out["info"] = fp["info"]
            out["restored"] = R.files_apply(fp, proc_check=False, log=lambda *a: None)["restored"]
            out["canon"] = sorted((e.get("acct"), e["amount"]) for e in (rj("futures_binance.json") or {}).get("events") or [])
            out["arch"] = sorted(n for n in os.listdir(P.STATE_DIR) if n.startswith("futraw_binance_s1@"))
        elif CASE == "f_oldbak":
            state[EX]["accts"]["s1"].update(uid="B1", kfp=kfp(KB))
            ST.atomic_write_json(P.state("exf_state.json"), state)
            ST.atomic_write_json(P.state("backups", "files_20260105", "futraw_binance_s1.json"), oldraw)
            fp = R.files_plan("20260105")
            out["info"] = fp["info"]
            out["restored"] = R.files_apply(fp, proc_check=False, log=lambda *a: None)["restored"]
        elif CASE == "f_legacy":
            ST.atomic_write_json(P.state("futraw_binance_s1.json"), oldraw)
            ST.atomic_write_json(P.state("futures_binance.json"), dict(oldraw, events=[dict(A_EV, acct="s1")], accts=["main", "s1"]))
            X.acct_ident(state, EX, "s1", KB, kperm, NOW)
            X._fut_retag_pending(state, EX)
            out["canon"] = sorted((e.get("acct"), e["amount"]) for e in (rj("futures_binance.json") or {}).get("events") or [])
        if CASE == "f_same":
            kb_env = {"TJ_BINANCE_KEY": "tk-acct-a2", "TJ_BINANCE_SECRET": "tk-secret"}
        else:
            kb_env = {"TJ_BINANCE_KEY": KB, "TJ_BINANCE_SECRET": "tk-secret"}
        B_EV = {"tranId": "tk-b", "incomeType": "REALIZED_PNL", "time": (NOW - 30 * DAY) * 1000, "income": "17", "symbol": "BTCUSDT", "asset": "USDT"}
        calls = []

        def fake_http(url, *a, **kw):
            p = urllib.parse.urlparse(url)
            q = urllib.parse.parse_qs(p.query)
            if p.path.endswith("/account"):
                return {"positions": [], "totalWalletBalance": "0", "availableBalance": "0", "totalCrossWalletBalance": "0", "totalCrossUnPnl": "0"}
            if p.path.endswith("/positionRisk"):
                return []
            if p.path.endswith("/income"):
                start = int(q["startTime"][0])
                calls.append(start)
                return [B_EV] if start <= B_EV["time"] and CASE != "f_same" else []
            raise AssertionError(p.path)
        BN._http_json_err = fake_http
        BN._gov_prepare = lambda *a: None
        BN._srv_ms = lambda *a: NOW * 1000
        BN._px_safe = lambda *a: None
        X._FUT_MULTI[EX] = True
        with patch.object(time, "sleep", lambda *a: None), X._acct_ctx("s1"):
            X._fut_binance(kb_env)
        got = rj("futraw_binance_s1.json") or {}
        out["days"] = [round((NOW * 1000 - t) / 1000 / DAY, 3) for t in calls]
        out["raw"] = sorted(e["amount"] for e in got.get("events") or [])
    out["net"] = list(T.NET_TRIES)
    T.case_emit(out)
    sys.exit(0)

import _harness as T  # noqa: E402


def child(case):
    return T.case_run([sys.executable, os.path.abspath(__file__), "--case", case], cwd=HERE)


BASE = {"qty": {"USDT": 75.0, "USDC": 45.0}, "raw": 3, "postings": 5, "adjust": 0}
r = child("r_move")
T.chk(r.get("setup") == [True, True, True] and r.get("before") == BASE and r.get("after_restore") == BASE and r.get("map_backed_up") is True
      and "exf_ident.json" in (r.get("restored") or []),
      "R1 준비: A 입금·매수·매도(원본 3 · 분개 5 · USDT 75 · USDC 45) → 서브1 지움 → 정기 백업(계정 지도 포함) → state 잃음 → 원장 'ex'·원장 밖 사본 되돌림 = 원장 그대로", r)
T.chk(r.get("refused") is True, "R1a 전체 복구 뒤 지운 서브1 계정 A 를 서브2 에 저장 = 거부(되돌린 계정 지도 · 종전 = 저장됨)", r)
T.chk(r.get("after") == BASE and "s2" in (r.get("bad") or []) and not r.get("net"),
      "R1b 손으로 .env·저장 기록을 고쳐 넣어도 수집기가 서브2 를 뺌 — 원장 사건·분개·수량 그대로(종전 = 원본 6 · 분개 10 · USDT 150 · USDC 90) · 재시작 3주기", r)
r = child("r_oldbak")
T.chk(r.get("hold") == {"bybit": ["s1"]} and any("계정 지도" in w for w in r.get("warn") or []) and r.get("held") is True,
      "R4 계정 지도 없는 옛 사본으로 전체 복구 = 원장에 기록 있는 서브1 은 계정 모름 → 다른 칸(서브2) 새 수집 보류(저장 거부 · 안내)", r)
T.chk(r.get("saved") is True and r.get("saved_c") is True and (r.get("after") or {}).get("raw") == 6 and not r.get("bad"),
      "R4b 원래 칸(서브1)에 원래 키 → 받으면 보류 풀림 → 진짜 다른 계정을 서브2 에 = 허용 · 따로 기장(A 다시 받아도 그대로 3 + C 3)", r)
import envfile  # noqa: E402
m = envfile.ident_build({"tkx": {"accts": {"s1": {"seen": {"x": "ACCEPTED"}, "backfilled_until": 5},
                                           "s2": {"seen": {"y": "ACCEPTED"}, "uid": "U1", "kfp": "abcd1234"},
                                           "s1@k12345678": {"seen": {"z": "ACCEPTED"}}}}}, {"ex": {"tkx": {"hold": ["s2", "s3"]}}})["ex"]["tkx"]
T.chk(m.get("active") == {"s2": {"uid": "U1", "kfp": "abcd1234"}} and m.get("hist") == {"s1": [{"kfp": "12345678"}], "s2": [{"uid": "U1", "kfp": "abcd1234"}]}
      and m.get("hold") == ["s1", "s3"],
      "R5 계정 지도 = 지금 칸 계정 · 칸별 이력 계정(보관 딱지 이름 포함) · 이력은 있는데 계정 모르는 칸 = 보류 · 지난 보류는 그 칸이 계정과 이력을 다시 가지면 풀림", m)
r = child("r_same")
T.chk(r.get("saved") is True and r.get("after") == BASE and not r.get("bad"),
      "R2 전체 복구 뒤 같은 칸(서브1)에 A 다시 = 허용 · 처음부터 다시 받아도 같은 칸 이름이라 원장 그대로(멱등 · 대조)", r)
r = child("r_other")
T.chk(r.get("saved") is True and (r.get("after") or {}).get("raw") == 6 and (r.get("after") or {}).get("qty") == {"USDT": 150.0, "USDC": 90.0}
      and not r.get("bad"),
      "R3 전체 복구 뒤 진짜 다른 계정(같은 거래소 번호 · 다른 UID·키)을 서브2 에 = 허용 · 따로 기장(지도가 다른 계정을 막지 않음 · 대조)", r)
r = child("r_main")
T.chk(r.get("after_restore") == BASE and r.get("after") == BASE and (r.get("mhold") or {}).get("slot") == "s1",
      "M6 전체 복구(수집 상태 잃음) 뒤 지운 서브1 계정 A 를 .env 로 메인 칸에 = 되돌린 계정 지도의 메인 정체(사본 때 메인 = M)와 달라 보류 · 원장 그대로", r)
import hashlib  # noqa: E402
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import ledger_restore as R  # noqa: E402
MID = {"uid": "M1", "kfp": hashlib.sha256(b"tk-main").hexdigest()[:8]}
r = child("m_move")
T.chk(r.get("setup") == [True, True, True] and r.get("before") == BASE and r.get("main_id") == MID and r.get("refused") is True
      and r.get("after") == BASE and (r.get("hold") or {}).get("slot") == "s1" and r.get("main_id2") == MID and ["exfmain:bybit", "crit"] in (r.get("panel") or []) and r.get("bal") == [],
      "M1 지운 서브1 계정 A 를 .env 손편집으로 메인 칸에(화면 저장은 거부) = 바이빗 수집 전체 보류 · 원장 그대로(종전 = 원본 3→6 · 분개 5→10 · USDT 75→150)"
      " · 메인 정체 기록 그대로 · 상태 패널 빨강 · 대사용 잔고 후보(정식·pending)도 치움(tj-core 대사가 보류 중 보정을 쓰지 않게)", r)
T.chk(r.get("after2") == BASE and not r.get("hold2") and r.get("panel2") == [["exfmain:bybit", "ok"]],
      "M1b 원래 메인 키를 다시 넣으면 다음 주기에 풀림 · 이어 받아도 원장 그대로 · 상태 패널 정상 줄(사건 닫힘)", r)
r = child("m_dup")
T.chk(r.get("after") == BASE and (r.get("hold") or {}).get("slot") == "s1" and r.get("after2") == BASE and not r.get("hold2")
      and r.get("bal0") and r.get("bal") == [],
      "M2 지우지 않은 서브1(이력 있음) 계정을 메인 칸에도(같은 계정 두 칸 — 종전 = 서브1 을 빼고 메인에서 처음부터 = 두 번 기장) = 보류 · 되돌리면 풀림"
      " · 보류 전 있던 대사용 잔고 후보(정식·pending)를 치움(tj-core 대사가 env 를 안 보므로)", r)
r = child("m_first")
T.chk(r.get("after") == BASE and not r.get("hold") and r.get("main_id2") == MID and not r.get("panel"),
      "M3 옛 설치(메인 정체 기록 없음 · 이 고침 첫 기동) = 지금 메인 정체 기록만(보류·경보 없음 · 오탐 금지)", r)
r = child("m_other")
T.chk((r.get("after") or {}).get("raw") == 4 and not r.get("hold") and r.get("main_id2") == {"kfp": hashlib.sha256(b"tk-acct-c").hexdigest()[:8]},
      "M4 다른 칸 이력에 없는 계정을 메인 칸에(정체 모름) = 종전대로 받음(새 체결 1건) · 새 메인 정체 기록", r)
r = child("m_rot")
T.chk(r.get("saved") is True and r.get("after") == BASE and not r.get("hold") and r.get("main_id2") == {"uid": "M1", "kfp": hashlib.sha256(b"tk-main-2").hexdigest()[:8]},
      "M5 같은 메인 계정 키 회전(화면 저장 · UID 같음) = 보류 없음 · 메인 정체 키 지문 갱신", r)
import chk_collect as CC  # noqa: E402
mi = [envfile.main_ident({}, None, "aaaa1111", "tkx"), envfile.main_ident({"main_id": {"kfp": "aaaa1111"}}, "U9", "aaaa1111", "tkx"),
      envfile.main_ident({"main_id": {"kfp": "aaaa1111"}, "accts": {"s1": {"kfp": "bbbb2222", "seen": {"x": 1}}}}, None, "bbbb2222", "tkx"),
      envfile.main_ident({"main_id": {"kfp": "aaaa1111"}, "accts": {"s1": {"kfp": "bbbb2222"}}}, None, "bbbb2222", "tkx"),
      envfile.main_ident({"main_id": {"uid": "U1", "kfp": "aaaa1111"}, "accts": {"s1@uU1": {"uid": "U1", "seen": {"x": 1}}}}, "U1", "cccc3333", "tkx")]
T.chk([list(x) for x in mi] == [["first", {"kfp": "aaaa1111"}, None], ["same", {"kfp": "aaaa1111", "uid": "U9"}, None], ["hold", None, "s1"],
                                ["new", {"kfp": "bbbb2222"}, None], ["same", {"uid": "U1", "kfp": "cccc3333"}, None]],
      "M7 메인 칸 정체 판정: 처음 = 기록만 · 같은 키 = UID 채움 · 다른 칸 이력 계정 = 보류 · 이력 없는 칸 계정 = 새 정체 · UID 같은 키 회전 = 같음", mi)
mb = envfile.ident_build({"tkx": {"main_id": {"uid": "U0", "kfp": "dddd4444"}, "accts": {"s1": {"kfp": "bbbb2222", "seen": {"x": 1}}}}}, {})["ex"]["tkx"]
mu = R.ident_union({"v": 1, "ex": {}}, {"v": 1, "ex": {"tkx": dict(mb)}})["ex"]["tkx"]
T.chk(mb.get("main") == {"uid": "U0", "kfp": "dddd4444"} and mu.get("main") == mb["main"] and CC.collect_exf_hold(0, os.path.join(T.TMP, "none.json")) == [],
      "M8 계정 지도에 메인 칸 정체(사본 → 되돌린 지도 합집합에도) · 상태 파일 없음 = 상태 패널 항목 없음", {"build": mb, "union": mu})
r = child("s_restore")
T.chk(r.get("saved") is True and r.get("kp_kept") is True and "settings.json" in (r.get("restored") or [])
      and r.get("fills") == ["bybit:s1:tk-b30"] and (r.get("b_days") or [0])[0] >= 149,
      "S1 정체 없는 옛 상태 → B 키 저장 → 첫 주기 전 옛 settings.json 만 되돌림 = 키 저장 기록은 지금 것 유지 · B 처음 창(150일)에서 30일 전 체결 1건"
      "(종전 = 기록 후퇴 → 옛 상태 계정으로 이어 받아 3일 창 · 0건)", r)
r = child("s_plain")
T.chk(r.get("saved") is True and r.get("fills") == ["bybit:s1:tk-b30"] and (r.get("b_days") or [0])[0] >= 149,
      "S2 같은 꼴 되돌림 없음(대조) = B 처음 창 · 30일 전 체결 1건", r)
r = child("f_legacy")
T.chk(r.get("raw") == [17.0] and (r.get("days") or [0])[0] >= 149 and r.get("canon") == [["s1", 3.0]],
      "S3 정체 없는 옛 상태 분리 = 그 칸 선물 원본(A 의 최근 커서)을 B 가 물려받지 않음 — B 처음 창(150일) +17 · A 의 옛 정산 +3 은 정본에 한 번"
      "(종전 = 0.04일 창 · +17 누락)", r)
r = child("f_changed")
T.chk(r.get("raw") == [17.0] and (r.get("days") or [0])[0] >= 149 and r.get("canon") == [["s1@uA1", 3.0]] and r.get("arch") == ["futraw_binance_s1@uA1.json"]
      and "futraw_binance_s1.json" not in (r.get("restored") or []),
      "F1 사본 때 서브1 = A · 지금 B · 정본·B 원본 없음 = A 원본을 B 칸에 안 넣음 · 정본의 A 정산 +3 = 보관 딱지 s1@uA1 · B 처음 창 +17"
      "(종전 = A 원본·최근 커서를 B 칸에 → +3 표시 · +17 누락)", r)
r = child("f_oldbak")
T.chk(r.get("raw") == [17.0] and (r.get("days") or [0])[0] >= 149 and not r.get("restored")
      and any("futraw_binance_s1.json" in x and "손으로" in x for x in r.get("info") or []),
      "F2 계정 기록 없는 옛 사본 + 지금 칸 계정 B = 원본 자동 되돌림 안 함(안내) · B 처음 창 +17", r)
r = child("f_same")
T.chk("futraw_binance_s1.json" in (r.get("restored") or []) and r.get("raw") == [3.0] and (r.get("days") or [99])[0] < 1
      and r.get("canon") == [["s1", 3.0]],
      "F3 같은 계정(UID 같음 · 키 회전) = 원본·커서 그대로 되돌림(최근 커서부터 · 지난 정산 그대로 · 대조)", r)
T.finish()
