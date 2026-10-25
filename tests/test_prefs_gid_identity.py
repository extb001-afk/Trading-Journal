#!/usr/bin/env python3
import os
import sqlite3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _costsim as S  # noqa: E402

import config  # noqa: E402
import core  # noqa: E402
import paths  # noqa: E402
import prefs_ident as PI  # noqa: E402
import statefile  # noqa: E402
import view_load  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import ledger_restore as R  # noqa: E402

chk = T.chk
DAY = 86400
T0 = S.NOW - 10 * DAY


def _prefs():
    return statefile.read_json(paths.state("ui_prefs.json"), {}) or {}


def _backup(name):
    c = S._C[0]
    c.conn.commit()
    p = os.path.join(T.TMP, name)
    for suf in ("", "-journal"):
        if os.path.exists(p + suf):
            os.remove(p + suf)
    dst = sqlite3.connect(p)
    c.conn.backup(dst)
    dst.execute("PRAGMA journal_mode=DELETE")
    dst.close()
    return p


def _restore(backup, cli=False):
    if S._C[0] is not None:
        S._C[0].conn.commit()
        S._C[0].conn.close()
        S._C[0] = None
    if cli:
        rc = R.main(["restore", backup, "--apply", "--no-proc-check", "--rewind", "none", "--full-check"])
        chk(rc in (0, None), "복원 명령줄(restore --apply) 성공", rc)
        _restart()
        return None
    plan = R.plan(backup, streams=[], state_dir=paths.STATE_DIR, now=S.NOW)
    rec = R.apply(plan, full_check=True, proc_check=False, state_dir=paths.STATE_DIR, log=lambda *a: None)
    _restart()
    return rec


def _restart():
    if S._C[0] is not None:
        S._C[0].conn.commit()
        S._C[0].conn.close()
    c = core.Core(config.load_config())
    S._fake_px(c.px)
    S._C[0] = c
    return c


def _dep(exn, tag, sym, qty, ts):
    S.ex(exn, deposits=[S.norm_row(exn, tag, sym, str(qty), 0, tag, "ACCEPTED", ts, ts)])


def _gid(sym, exn="bybit"):
    return S._C[0].conn.execute("SELECT group_id FROM assets WHERE address=?", (f"{exn}:{sym}".lower(),)).fetchone()[0]


class _Saver(view_load.LoadMixin):
    pass


def _persist(prefs, bind, ep):
    b9 = _Saver()
    b9._prefid = {"bind": bind, "epoch": ep, "need": PI.needs_write(prefs, bind, ep)}
    return b9._prefid_persist()


def _b(prefs):
    f, G, _rr = S.build(prefs=prefs)
    return f, G


def _hold_rows(f):
    return [p for p in (f.get("pendings") or []) if str(p.get("key") or "").startswith("prefid:")]


def case_restore_other_coin():
    S.reset(px={"USDT": 1., "TKJA": 10., "TKJB": 100.})
    _dep("bybit", "seed", "USDT", 1000, T0)
    bk = _backup("ac01_before_A.db")
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gA = _gid("TKJA")
    _f, GA = _b(prefs={"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 2.}}})
    chk(abs(float(GA[gA]["cost"]) - 20) < 1e-6, "대조: 복원 전 A 에는 수동 단가가 먹음(원가 20)", GA[gA].get("cost"))
    rec1 = _restore(bk)
    after = _prefs()
    chk(after.get("cost_overrides") == {f"g{gA}": {"mode": "unit", "unit": 2.}}, "복원은 설정 값을 지우지 않음(모양 그대로 — 옛 코드도 그대로 읽음)", after)
    chk(isinstance((after.get(PI.SIDE_K) or {}).get(f"cost_overrides:g{gA}"), str) and "TKJA" in after[PI.SIDE_K][f"cost_overrides:g{gA}"],
        "복원 도구가 교체 전에 지금 원장(A)으로 정체성을 묶음", after.get(PI.SIDE_K))
    _dep("bybit", "tokenB", "TKJB", 10, T0 + 200)
    gB = _gid("TKJB")
    chk(gA == gB, "반례 성립: 새 B 가 같은 gid 를 받음", (gA, gB))
    S.fills("bybit", [S.norm_fill("bybit", "sellB", (T0 + 300) * 1000, "TKJB", "USDT", "sell", "100", "10", "0", "")])
    fW, _G = _b(prefs=after)
    pk = _prefs()
    _restart()
    fC, _G = _b(prefs={})
    statefile.atomic_write_json(paths.state("ui_prefs.json"), pk)
    chk(abs(S.realized(fW) - S.realized(fC)) < .011 and abs(S.tax_sum(fW) - S.tax_sum(fC)) < .011,
        "A 의 수동 단가가 무관한 B 의 실현·명세에 안 붙음(정상 대조와 같음)", (S.realized(fW), S.realized(fC), S.tax_sum(fW), S.tax_sum(fC)))
    hr = _hold_rows(fW)
    chk(len(hr) == 1 and hr[0].get("gkey") == f"g{gB}" and "TKJA" in str(hr[0].get("onchain") or "") + str(hr[0].get("gap") or ""),
        "격리된 설정 = 확인 필요 1줄(지금 번호·이전 자산 이름)", hr)
    chk(hr and not hr[0].get("hide"), "확인 필요 줄은 소액 숨김에 안 걸림(늘 보임)", hr and hr[0].get("hide"))
    chk(not _hold_rows(fC), "대조(설정 없음) = 확인 필요 없음", _hold_rows(fC))
    _restore(bk)
    _dep("bybit", "tokenB", "TKJB", 10, T0 + 200)
    S.fills("bybit", [S.norm_fill("bybit", "sellB", (T0 + 300) * 1000, "TKJB", "USDT", "sell", "100", "10", "0", "")])
    fR, _G = _b(prefs=_prefs())
    chk(abs(S.realized(fR) - S.realized(fC)) < .011, "반복 복원·재시작 뒤에도 B 에 안 붙음", (S.realized(fR), S.realized(fC)))
    _restore(rec1["kept"])
    fU, GU = _b(prefs=_prefs())
    chk(abs(float(GU[gA]["cost"]) - 20) < 1e-6 and not _hold_rows(fU), "복원 되돌리기 = A 에 설정 다시 적용(확인 필요 없음)", (GU[gA].get("cost"), _hold_rows(fU)))


def case_same_asset_restore():
    S.reset(px={"USDT": 1., "TKJA": 10., "TKJB": 100.})
    _dep("bybit", "seed", "USDT", 1000, T0)
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gA = _gid("TKJA")
    bk = _backup("ac01_with_A.db")
    _b(prefs={"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 2.}}})
    _restart()
    _dep("bybit", "tokenC", "TKJB", 5, T0 + 150)
    _restore(bk)
    S.fills("bybit", [S.norm_fill("bybit", "sellA", (T0 + 300) * 1000, "TKJA", "USDT", "sell", "100", "10", "0", "")])
    f, _G = _b(prefs=_prefs())
    chk(abs(S.realized(f) - 980) < .011 and abs(S.tax_sum(f) - 980) < .011, "같은 자산 복원 = 수동 단가 유지(실현 = 1000 − 20)", (S.realized(f), S.tax_sum(f)))
    chk(not _hold_rows(f), "같은 자산 = 확인 필요 없음", _hold_rows(f))


def case_same_ticker_other_venue():
    S.reset(px={"USDT": 1., "TKJA": 10.})
    _dep("bybit", "seed", "USDT", 1000, T0)
    bk = _backup("ac01_before_A2.db")
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gA = _gid("TKJA")
    _b(prefs={"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 2.}}})
    _restore(bk, cli=True)
    _dep("okx", "tokenA2", "TKJA", 10, T0 + 200)
    gA2 = _gid("TKJA", "okx")
    nm = S._C[0].conn.execute("SELECT name FROM asset_groups WHERE group_id=?", (gA2,)).fetchone()[0]
    chk(gA2 == gA and nm.startswith("TKJA#"), "반례 성립: 같은 gid · 같은 티커 그룹 이름", (gA, gA2, nm))
    S.fills("okx", [S.norm_fill("okx", "sellA2", (T0 + 300) * 1000, "TKJA", "USDT", "sell", "10", "10", "0", "")])
    f, _G = _b(prefs=_prefs())
    _restart()
    fC, _G = _b(prefs={})
    chk(abs(S.realized(f) - S.realized(fC)) < .011, "다른 자산 키의 같은 티커에 안 붙음", (S.realized(f), S.realized(fC)))


def case_order_change():
    S.reset(px={"USDT": 1., "TKJA": 10., "TKJB": 100.})
    _dep("bybit", "seed", "USDT", 1000, T0)
    bk = _backup("ac01_before_A3.db")
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gA = _gid("TKJA")
    _b(prefs={"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 2.}}, "risk_overrides": {f"g{gA}": "spam"},
                   "ignored": [f"unv:{gA}"], "plans": {f"g{gA}": {"target": 20., "stop": 5.}}})
    _restore(bk)
    _dep("bybit", "tokenB", "TKJB", 10, T0 + 200)
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gB, gA3 = _gid("TKJB"), _gid("TKJA")
    chk(gB == gA and gA3 != gA, "반례 성립: 순서가 바뀌어 B 가 옛 A 번호", (gA, gB, gA3))
    pk = _prefs()
    f, G = _b(prefs=pk)
    _restart()
    _fC, GC = _b(prefs={})
    statefile.atomic_write_json(paths.state("ui_prefs.json"), pk)
    chk(G[gB].get("cost") == GC[gB].get("cost") and abs(float(G[gB]["cost"]) - 20) > 1e-6, "B 원가 = 정상 대조와 같음(옛 A 단가 아님)",
        (G[gB].get("cost"), GC[gB].get("cost")))
    chk(f"g{gB}" not in (f.get("plans") or {}), "옛 A 의 목표가가 B 카드에 안 붙음", f.get("plans"))
    chk(gB in G and not G[gB].get("quarantined") and any(c.get("key") == f"g{gB}" for c in f.get("coins") or []),
        "옛 A 의 스캠 지정이 B 를 격리하지 않음", [c.get("key") for c in f.get("coins") or []])
    secs = sorted(h["key"].split(":")[1] for h in _hold_rows(f))
    chk(secs == ["cost_overrides", "ignored", "plans", "risk_overrides"], "칸마다 확인 필요(원가 지정·무시·계획·스캠 지정)", secs)


def case_legacy_migration():
    S.reset(px={"USDT": 1., "TKJA": 10., "TKJB": 100.})
    _dep("bybit", "seed", "USDT", 1000, T0)
    bk = _backup("ac01_before_A4.db")
    _dep("bybit", "tokenA", "TKJA", 10, T0 + 100)
    gA = _gid("TKJA")
    legacy = {"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 2.}}}
    _f, G = _b(prefs=legacy)
    chk(abs(float(G[gA]["cost"]) - 20) < 1e-6, "옛 설정은 첫 빌드에 그대로 적용", G[gA].get("cost"))
    co = sqlite3.connect(paths.DB_PATH)
    try:
        eff, hold, bind = PI.resolve(_prefs(), PI.ident_map(co), PI.ledger_epoch(co))
        ep = PI.ledger_epoch(co)
    finally:
        co.close()
    chk(eff.get("cost_overrides") and not hold and list(bind) == [f"cost_overrides:g{gA}"], "옛 설정 = 지금 정체성으로 묶을 것 1개", (hold, bind))
    chk(_persist(_prefs(), bind, ep) and _prefs().get(PI.MARK_K) == ep, "빌드 뒤 묶음 저장(표식 = 지금 원장 신원)", _prefs())
    chk(not _persist(_prefs(), bind, ep), "두 번째 저장 = 바꿀 것 없음(쓰지 않음)", _prefs())
    with PI.write_lock():
        chk(not _persist(legacy, bind, "otherepoch"), "설정 잠금이 쥐어져 있으면 저장 건너뜀", None)
    p2 = dict(_prefs(), **{"risk_overrides": {f"g{gA}": "visible"}})
    eff2, hold2, bind2 = PI.resolve(dict(p2, **{PI.MARK_K: "otherledger"}), {gA: "TKJA#2|x"}, ep)
    chk(not eff2.get("risk_overrides") and bind2 == {f"risk_overrides:g{gA}": PI.UNKNOWN}, "표식 ≠ 원장 신원 → 정체성 없는 설정 = '?' 격리", (eff2, bind2))
    p3 = _prefs()
    PI.touch(p3, "cost_overrides", f"g{gA}")
    chk(f"cost_overrides:g{gA}" not in p3.get(PI.SIDE_K, {}), "POST 저장 = 그 칸 정체성 지움", p3.get(PI.SIDE_K))
    chk(PI.needs_write({PI.SIDE_K: {}, PI.MARK_K: "e1"}, {}, "e2") and PI.bind_doc({PI.SIDE_K: {}, PI.MARK_K: "e1"}, {}, "e2")[PI.MARK_K] == "e2",
        "gid 설정이 하나도 없어도 표식 = 지금 원장 신원으로 갱신", None)
    p4 = {"cost_overrides": {f"g{gA}": {"mode": "unit", "unit": 3.}}, PI.SIDE_K: {}, PI.MARK_K: "staleepoch"}
    PI.bind_now(p4, "cost_overrides", f"g{gA}")
    co = sqlite3.connect(paths.DB_PATH)
    try:
        eff4, hold4, _b4 = PI.resolve(p4, PI.ident_map(co), PI.ledger_epoch(co))
    finally:
        co.close()
    chk("TKJA" in p4[PI.SIDE_K].get(f"cost_overrides:g{gA}", "") and eff4.get("cost_overrides") and not hold4,
        "POST 저장 = 바로 묶음 · 낡은 표식이어도 새 설정 적용", (p4, hold4))
    p5 = {"cost_overrides": {}, PI.SIDE_K: {f"cost_overrides:g{gA}": "old"}}
    PI.bind_now(p5, "cost_overrides", f"g{gA}")
    chk(p5[PI.SIDE_K] == {}, "지운 칸 = 옛 정체성만 지움", p5)
    _restore(bk)
    _dep("bybit", "tokenB", "TKJB", 10, T0 + 200)
    gB = _gid("TKJB")
    f, G = _b(prefs=_prefs())
    chk(abs(float(G[gB]["cost"]) - 20) > 1e-6 and len(_hold_rows(f)) == 1, "묶은 옛 설정 → 복원 뒤 B 에 안 붙음 + 확인 필요", (G[gB].get("cost"), _hold_rows(f)))


def case_restore_bind_rules():
    S.reset(px={"USDT": 1.})
    statefile.atomic_write_json(paths.state("ui_prefs.json"), {"cost_overrides": {"g2": {"mode": "unit", "unit": 2.}, "g3": {"mode": "market"}},
                                                               PI.SIDE_K: {"cost_overrides:g3": "TKJC#3|x"}})
    pf = R.prefs_bind(paths.STATE_DIR, paths.DB_PATH + ".absent")
    chk(pf[PI.SIDE_K] == {"cost_overrides:g2": PI.UNKNOWN, "cost_overrides:g3": "TKJC#3|x"} and pf[PI.MARK_K] == PI.NO_MARK,
        "지금 원장 없음 = 정체성 없는 칸 '?' · 묶인 칸 그대로 · 표식 NO_MARK", pf)
    bk = _backup("ac01_plan.db")
    plan = R.plan(bk, streams=[], state_dir=paths.STATE_DIR, now=S.NOW)
    chk("ui_prefs.json" in plan["files"] and plan["files"]["ui_prefs.json"][PI.MARK_K] == PI.NO_MARK, "복원 미리보기 = 설정 묶음 파일 보임", list(plan["files"]))
    eff, hold, bind = PI.resolve(plan["files"]["ui_prefs.json"], {}, "newepoch")
    chk(not bind and not hold and PI.needs_write(plan["files"]["ui_prefs.json"], bind, "newepoch"),
        "복원 뒤 = 정체성 없는 칸 없음 · 첫 웹 빌드가 표식만 새 원장 신원으로", (bind, hold))


def case_ident_units():
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE asset_groups(group_id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE assets(asset_id INTEGER, kind TEXT, chain TEXT,"
                     " address TEXT, group_id INTEGER); CREATE TABLE meta(k TEXT, v TEXT);"
                     "INSERT INTO asset_groups VALUES (1,'ETH'),(2,'TKX#2');"
                     "INSERT INTO assets VALUES (1,'native','eth',NULL,1),(3,'native','base',NULL,1),(2,'token','base','0xaa',2);")
    m1 = PI.ident_map(db)
    db.execute("UPDATE assets SET address='0xbb' WHERE asset_id=2")
    m2 = PI.ident_map(db)
    chk(m1[1] == m2[1] == "ETH", "합친 그룹 = 이름(체인이 늘어도 같은 정체성)", m1)
    chk(m1[2] != m2[2], "인스턴스 그룹 = 계약 주소가 다르면 다른 정체성", (m1[2], m2[2]))
    chk(PI.gid_of("plans", "g12f0") == 12 and PI.gid_of("ignored", "risk:g7") == 7 and PI.gid_of("ignored", "unkh:TKX") is None
        and PI.gid_of("cost_overrides", "TKX") is None, "gid 든 키만 대상", None)
    p = {"risk_overrides": {"g2": "spam"}, PI.SIDE_K: {"risk_overrides:g2": m1[2]}, PI.MARK_K: ""}
    chk(PI.applies(p, "risk_overrides", "g2", db) is False and PI.applies(dict(p, **{PI.SIDE_K: {"risk_overrides:g2": m2[2]}}), "risk_overrides", "g2", db),
        "빌드 밖 한 칸 판정(core 발견 가드) = 같은 규칙", None)
    chk(PI.applies({"risk_overrides": {"g2": "spam"}}, "risk_overrides", "g2", db), "옛 설정(표식 없음) = 지금 자산에 적용", None)


def case_health():
    import time
    import health
    units = ["tj-core", "tj-web"]
    hs = health.settings({"health": {"units": units}})
    now = time.time()
    hold = [{"sec": "cost_overrides", "key": "g2", "gid": 2, "was": "TKJA#2|x", "now": "TKJB#2|y"}]

    def ev(wd):
        ob = {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in units}, "bal_mem": {}, "prev_inc": {},
              "sources": [], "webdiag": dict({"ts": now, "unpriced_held": [], "ex_dead_held": [], "proof_div": []}, **wd)}
        return {c["id"]: c for c in health.evaluate(ob, hs) if c.get("id") == "prefs:ident"}
    c1 = ev({"prefid": PI.diag({"hold": hold})}).get("prefs:ident") or {}
    chk(c1.get("level") == "warn" and "TKJA" in str(c1.get("detail")), "격리 칸 있음 = 주황 · 이전 자산 이름", c1)
    c0 = ev({"prefid": PI.diag({"hold": []})}).get("prefs:ident") or {}
    chk(c0.get("level") == "ok", "격리 칸 없음 = 초록", c0)
    chk(not ev({}), "옛 웹 진단(칸 없음) = 항목 없음", None)


for fn in (case_health, case_ident_units, case_restore_other_coin, case_same_asset_restore, case_same_ticker_other_venue, case_order_change,
           case_legacy_migration, case_restore_bind_rules):
    fn()
T.finish()
