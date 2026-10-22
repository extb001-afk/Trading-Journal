#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config, paths  # noqa: E402
import ledger_lock  # noqa: E402


USAGE = """사용(독스트링이 지워진 공개판에서도 보이게 — 상수):
  python3 tools/repair_own_overlap.py              점검(쓰기 0 · 칸 목록: fix = 고칠 칸 · ok = 정상 · skip = 설명 안 되는 차이 — 안 건드림)
  python3 tools/repair_own_overlap.py --apply      고칠 칸이 있으면 원장 백업(state/ledger.db.pre_ownfix_<시각>) 뒤 한 트랜잭션으로 고침(두 번째 = 무변)
가드: tj-core 정지(pm2 판정 · 판정 불가 = 중단 · --force 는 정지를 직접 확인한 뒤) · 재구축 진행 중 = 중단 · 백업 실패 = 중단.
되돌리기: tj-core·tj-web 정지 상태에서 state/ledger.db 를 출력된 백업으로 교체(-wal·-shm 삭제) 뒤 재기동."""


def _core_running():
    try:
        r = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        lst = json.loads(r.stdout)
        if not isinstance(lst, list):
            return None
        apps = [p for p in lst if isinstance(p, dict) and p.get("name") == "tj-core"]
        if not apps:
            return None
        return any((p.get("pm2_env") or {}).get("status") != "stopped" for p in apps)
    except Exception:   # noqa: BLE001
        return None


def _fmt(q, dec):
    try:
        return f"{int(q) / (10 ** int(dec if dec is not None else 18)):,.6f}"
    except (TypeError, ValueError):
        return str(q)


def _backup(conn) -> str:
    dst = os.path.join(paths.STATE_DIR, "ledger.db.pre_ownfix_" + time.strftime("%Y%m%d_%H%M%S"))
    need = os.path.getsize(paths.DB_PATH) + (os.path.getsize(paths.DB_PATH + "-wal") if os.path.exists(paths.DB_PATH + "-wal") else 0)
    if shutil.disk_usage(paths.STATE_DIR).free < need * 1.2 + 64 * 1024 * 1024:
        raise SystemExit(f"★백업 공간 부족(필요 ≈{need / 1e9:.2f}GB) — 중단(원장 무변)★")
    d9 = sqlite3.connect(dst)
    try:
        conn.backup(d9)
        d9.execute("PRAGMA journal_mode=DELETE")
    finally:
        d9.close()
    if os.path.exists(dst + "-shm"):
        os.remove(dst + "-shm")
    return dst


def _ro_core(core_mod, cfg):
    conn = None
    for imm in (False, True):
        try:
            conn = sqlite3.connect(paths.sqlite_ro_uri(paths.DB_PATH, immutable=imm), uri=True, timeout=30)
            conn.execute("SELECT 1 FROM meta LIMIT 1").fetchall()
            break
        except sqlite3.Error:
            if conn is not None:
                conn.close()
            conn = None
    if conn is None:
        raise SystemExit("★원장을 읽기 전용으로 열 수 없음 — 중단(원장 무변)★")
    conn.row_factory = sqlite3.Row
    c = core_mod.Core.__new__(core_mod.Core)
    c.conn = conn
    c.my_wallets = {}
    for w in cfg.get("wallets") or []:
        if isinstance(w, dict) and w.get("type", "evm") != "sol" and w.get("chain") and w.get("address"):
            c.my_wallets.setdefault(w["chain"], set()).add(str(w["address"]).lower())
    for w in cfg.get("_disabled_wallets") or []:
        if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain") and str(w.get("address") or "").startswith("0x"):
            c.my_wallets.setdefault(w["chain"], set()).add(str(w["address"]).lower())
    import core_svc
    core_svc.attach(c)
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="'내 지갑' 재분류 보유 중복(받는 지갑 기초 잔고 + 받은 레그) 점검·복구 — 대사 관측 잔고 기준",
                                 epilog=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="고칠 칸(fix)이 있으면 백업 뒤 고침")
    ap.add_argument("--chain", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="tj-core 가동 여부 판정 불가일 때만(정지를 직접 확인한 뒤)")
    a = ap.parse_args(argv)
    if not os.path.exists(paths.DB_PATH):
        print("원장 없음: " + paths.DB_PATH)
        return 1
    running = _core_running()
    if running or (running is None and not a.force):
        print("★tj-core 가 가동 중이거나 판정 불가 — 정지 뒤 실행(판정 불가면 정지 확인 후 --force)★")
        return 1
    with ledger_lock.hold_if(a.apply, paths.DB_PATH, who="repair_own_overlap --apply"):
        return _run(a)


def _run(a) -> int:
    import core as core_mod
    cfg = config.load_config()
    c = _ro_core(core_mod, cfg)
    try:
        if c._meta_get("ext_rebuild_started_at"):
            print("★원장 재구축 진행 중(ext_rebuild_started_at) — 끝난 뒤 실행★")
            return 1
        rows = c.own_overlap_repair(apply=False, chain=a.chain)
        dec = {r[0]: r[1] for r in c.conn.execute("SELECT asset_id, decimals FROM assets").fetchall()}
        fixes = [r for r in rows if r["action"] == "fix"]
        if a.json:
            print(json.dumps({"rows": rows, "apply": bool(a.apply and fixes)}, ensure_ascii=False))
        else:
            print(f"점검 칸 {len(rows)} · 고칠 칸(fix) {len(fixes)} · 정상(ok) {sum(1 for r in rows if r['action'] == 'ok')}"
                  f" · 설명 안 됨(skip — 안 건드림) {sum(1 for r in rows if r['action'] == 'skip')}")
            for r in rows:
                d9 = dec.get(r["asset_id"], 18)
                print(f"  {r['action']:4s} [{r['chain']}] {r['wallet'][:10]}… {r['symbol'] or r['asset_id']} · 관측 {_fmt(r['observed'], d9)}"
                      f" · 기초 잔고 {_fmt(r['anchor'], d9)} → 기대 {_fmt(r['expected'], d9)} · 차이 {_fmt(r['extra'], d9)}"
                      f" · 받은 레그 {_fmt(r['recv'], d9)}" + (" · 다른 기초 잔고 행 있음(재정렬 등 — 수동 확인)" if r.get("other_anchor") else ""))
        if not a.apply or not fixes:
            if a.apply and not a.json:
                print("고칠 칸 없음 — 원장 무변")
            return 0
        bk = _backup(c.conn)
        print(f"백업: {bk}")
        c.conn.close()
        c = core_mod.Core(cfg)
        done = c.own_overlap_repair(apply=True, chain=a.chain)
        print(f"★고침 {sum(1 for r in done if r['action'] == 'fix')}칸 — tj-core 재기동 뒤 화면 곡선은 고친 날부터 다시 계산됩니다★")
        return 0
    finally:
        c.conn.close()


if __name__ == "__main__":
    sys.exit(main())
