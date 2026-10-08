#!/usr/bin/env python3
"""Plan, apply or undo re-dating of exchange reconciliation corrections (stop tj-core first)."""
import json
import os
import shlex
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import common
import core

KST = timezone(timedelta(hours=9))


def _t(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d %H:%M:%S")


def _is_core_proc(p) -> bool:
    if not isinstance(p, dict):
        return True
    if "core" in str(p.get("name") or "").lower():
        return True
    env = p.get("pm2_env") if isinstance(p.get("pm2_env"), dict) else {}
    args = env.get("args")
    if isinstance(args, str):
        try:
            args = shlex.split(args)
        except ValueError:
            return True
    elif not isinstance(args, list):
        args = []
    toks = [str(x) for x in args]
    paths = [str(x).replace("\\", "/") for x in [env.get("pm_exec_path"), *toks] if x]
    names = [os.path.basename(x.rstrip("/")).lower() for x in paths]
    if "core.py" in names:
        return True
    if "unit_runner.py" in names and any(t.strip().lower() == "core" for t in toks):
        return True
    return False


def _core_stopped() -> bool:
    try:
        r = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=20)
        lst = json.loads(r.stdout) if r.returncode == 0 and (r.stdout or "").strip() else None
    except Exception:
        return False
    if not isinstance(lst, list):
        return False
    for p in lst:
        if not isinstance(p, dict):
            return False
        env = p.get("pm2_env") if isinstance(p.get("pm2_env"), dict) else {}
        if _is_core_proc(p) and env.get("status") != "stopped":
            return False
    return True


def _planner(conn):
    cfg = common.read_json(common.CONFIG_PATH, {}) or {}
    c = core.Core.settle_planner(cfg, conn)
    return c


def _ro():
    p = common.DB_PATH
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(p), uri=True, timeout=30)
        c.execute("SELECT 1 FROM postings LIMIT 1").fetchall()
    except sqlite3.OperationalError:
        assert not os.path.exists(p + "-wal") or os.path.getsize(p + "-wal") == 0, "WAL 이 남아 있는데 읽기 전용 열기 실패"
        c = sqlite3.connect(common.sqlite_ro_uri(p, immutable=True), uri=True)
    c.row_factory = sqlite3.Row
    return c


def _summary(plan):
    rows = []
    for m in plan:
        dec = 8
        old = {(o["leg"], o["ts"]): int(o["qb"]) for o in m["old"]}
        new = {(x["leg"], x["ts"]): int(x["qb"]) for x in m["new"]}
        rows.append({"ex": m["ex"], "sym": m["sym"], "bts": _t(m["bts"]), "sid": m["sid"],
                     "amount": sum(old.values()) / 10 ** dec,
                     "old": [[_t(t), l, q / 10 ** dec] for (l, t), q in sorted(old.items(), key=lambda kv: kv[0][1])],
                     "new": [[_t(t), l, q / 10 ** dec] for (l, t), q in sorted(new.items(), key=lambda kv: kv[0][1])]})
    return rows


def main():
    a = sys.argv[1:]
    out = a[a.index("--json") + 1] if "--json" in a else None
    if "--undo" in a:
        path = a[a.index("--undo") + 1]
        if not _core_stopped():
            print("거부: pm2 에 떠 있는 tj-core(src/core.py)가 있거나 확인하지 못함(우회 옵션 없음)")
            return 1
        moves = (json.load(open(path)) or {}).get("moves") or []
        conn = sqlite3.connect(common.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        try:
            for m in moves:
                cur = {int(r["leg_seq"]): r for r in conn.execute(
                    "SELECT posting_id, leg_seq, event_ts, qty_base FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=?",
                    (m["ns"], m["sid"])).fetchall()}
                ok = all(x["leg"] in cur and int(cur[x["leg"]]["event_ts"]) == int(x["ts"]) and str(cur[x["leg"]]["qty_base"]) == x["qb"]
                         for x in m["new"])
                if not ok:
                    raise ValueError(f"지금 원장이 재배치 뒤 모양과 다름: {m['sid']}")
                for x in m["new"]:
                    conn.execute("DELETE FROM postings WHERE posting_id=?", (int(cur[x["leg"]]["posting_id"]),))
                for o in m["old"]:
                    conn.execute(
                        "INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES (?, 'exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening',"
                        " 'EXF_ADJUST', ?)",
                        (o["pid"], m["ns"], m["sid"], o["leg"], o["ts"], m["asset_id"], m["loc"], o["qb"], m["cv"]))
            conn.execute("DELETE FROM meta WHERE k='exf_fix_place_v'")
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"거부: 되돌림 전체 취소(원장·표식 무변) — {e} · 정본 롤백 = 원장 백업 복원")
            return 1
        try:
            os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
        except FileNotFoundError:
            pass
        hd = None
        if moves:
            hd = common.mark_hist_dirty(min(min(int(o["ts"]) for o in m["old"] + m["new"]) for m in moves))
        print(f"되돌림 {len(moves)}/{len(moves)} 묶음 · meta exf_fix_place_v 삭제 · daily_cache 무효화 · 장기 곡선 표식 {hd}")
        return 0
    if "--apply" in a:
        if not _core_stopped():
            print("거부: pm2 에 떠 있는 tj-core(src/core.py)가 있거나 확인하지 못함(우회 옵션 없음)")
            return 1
        expect = None
        if "--expect" in a:
            expect = (json.load(open(a[a.index("--expect") + 1])) or {}).get("plan")
            if not isinstance(expect, list):
                print("거부: --expect 파일에 plan 없음")
                return 1
        conn = sqlite3.connect(common.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        c = _planner(conn)
        before = c._meta_get("exf_fix_place_v")
        res = c._exf_fix_place_once(expect=expect)
        after = c._meta_get("exf_fix_place_v")
        if res is False:
            print("거부: 잠금 안에서 다시 세운 계획이 --expect 와 다름(원장이 그 사이 바뀜) — 원장 무변")
            return 1
        if res is None and str(after or "").split(":", 1)[0] != str(core.Core.EXF_FIX_V):
            print("실패: 적용 안 됨(로그 참고) — 원장 무변")
            return 1
        print(f"적용: meta exf_fix_place_v {before} → {after}")
        return 0
    conn = _ro()
    plan = _planner(conn)._exf_fix_place_plan()
    rows = _summary(plan)
    for r in rows:
        print(f"{r['ex']:8s} {r['sym']:10s} {r['amount']:>20,.8f}  대사 {r['bts']}")
        print(f"    전: " + " | ".join(f"{t} L{l} {q:,.8f}" for t, l, q in r["old"]))
        print(f"    후: " + " | ".join(f"{t} L{l} {q:,.8f}" for t, l, q in r["new"]))
    print(f"바뀌는 묶음 {len(rows)} · 최대 분할 {max((len(m['new']) for m in plan), default=0)}레그/묶음")
    if out:
        json.dump({"plan": plan, "rows": rows}, open(out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
