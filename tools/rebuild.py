"""Rebuilds the ledger from collected events."""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import common
import core as core_mod

DERIVED_TABLES = ("postings", "tx_class", "transfers", "positions")


def guard_core_stopped():
    if "--no-pm2-guard" in sys.argv:
        print("경고: --no-pm2-guard — pm2 확인 생략 (tj-core·tj-ex 정지는 운영자 책임)")
        return
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            raise RuntimeError(f"pm2 jlist rc={out.returncode}")
        apps = json.loads(out.stdout or "[]")
    except Exception as e:
        raise SystemExit(f"★pm2 상태 확인 실패({e!r}) — core 정지 여부를 보증할 수 없어 중단."
                         " pm2 없는 호스트면 --no-pm2-guard 로 명시하라★")
    for a in apps:
        if a.get("name") not in ("tj-core", "tj-ex"):
            continue
        st = (a.get("pm2_env") or {}).get("status")
        if st != "stopped":
            raise SystemExit(f"★{a['name']} 상태={st} — 'stopped' 확인 전 실행 금지"
                             " (pm2 stop 후 재시도)★")


def main():
    dry = "--dry-run" in sys.argv
    common.ensure_dirs()
    cfg = common.load_config()

    import db as dbm
    ro = dbm.open_db(common.DB_PATH, readonly=True)
    n_raw = ro.execute("SELECT count(*) FROM raw_txs").fetchone()[0]
    n_ord = ro.execute(
        "SELECT count(DISTINCT uuid) FROM raw_ex WHERE kind='order'").fetchone()[0]
    n_dep = ro.execute(
        "SELECT count(DISTINCT uuid) FROM raw_ex WHERE kind='deposit'").fetchone()[0]
    ro.close()
    print(f"원본: 온체인 {n_raw}건 / 주문 {n_ord}건 / 입금 {n_dep}건")
    if dry:
        print("--dry-run: 여기서 종료 (파생·마스터 미변경)")
        return
    guard_core_stopped()
    if hasattr(core_mod.Core, "_upbit_asset"):
        raise SystemExit("★canonical C 원장에서는 tools/rebuild.py 사용 금지 — tools/rebuild2.py(shadow 재파생·게이트·"
                         "컷오버 절차)를 사용하라★")
    c = core_mod.Core(cfg)
    conn = c.conn

    conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rebuild_incomplete', ?)",
                 (str(int(time.time())),))
    for t in DERIVED_TABLES:
        conn.execute(f"DELETE FROM {t}")
    conn.execute("DELETE FROM meta WHERE k LIKE 'recon_done_%'")
    marker = os.path.join(common.STATE_DIR, "backfill_done")
    if os.path.exists(marker):
        os.remove(marker)
    dc = os.path.join(common.STATE_DIR, "daily_cache.json")
    if os.path.exists(dc):
        os.remove(dc)
    conn.commit()
    print("파생 삭제 완료 (rebuild_incomplete 마커 설정)")

    ok = err = 0
    rows = conn.execute(
        "SELECT chain, txhash, snapshot FROM raw_txs"
        " ORDER BY ingested_at, chain, txhash").fetchall()
    for r in rows:
        try:
            conn.execute("BEGIN")
            snap = json.loads(r["snapshot"])
            if r["chain"] == "sol" and snap.get("kind") == "sol_tx":
                c.apply_sol(snap)
            else:
                c.apply(r["chain"], r["txhash"], "", snap)
            conn.commit()
            ok += 1
        except Exception as e:
            conn.rollback()
            err += 1
            print("재파생 실패:", r["chain"], r["txhash"][:14], repr(e)[:80])
    print(f"온체인 재파생: {ok}건 성공 / {err}건 실패")

    now = int(time.time())
    m = 0
    for d in conn.execute(
            "SELECT uuid, payload FROM raw_ex WHERE kind='deposit' AND exchange='upbit'"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
        try:
            p = json.loads(d["payload"])
        except json.JSONDecodeError:
            continue
        if str(p.get("state") or "").upper() != "ACCEPTED":
            continue
        txid = str(p.get("txid") or "")
        if not txid:
            continue
        cand = txid.lower() if txid.startswith("0x") else txid
        cur = conn.execute(
            "UPDATE transfers SET state='credited', ex_uuid=?, updated_at=?"
            " WHERE state='sent' AND chain_txhash IN (?, ?)",
            (d["uuid"], now, cand, txid))
        if cur.rowcount:
            dep_ts = c._iso_ts(p.get("done_at") or p.get("created_at")) or now
            c._post_ex_deposit(d["uuid"], p, dep_ts)
            m += cur.rowcount
    conn.commit()
    print(f"입금 대사: {m}건")

    nf = 0
    for t in conn.execute(
            "SELECT exchange, payload FROM raw_ex WHERE kind='trade'"
            " AND exchange != 'upbit'").fetchall():
        try:
            if c._post_exf_fill(t["exchange"], json.loads(t["payload"])):
                nf += 1
        except json.JSONDecodeError:
            continue
    for t in conn.execute(
            "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='withdraw'"
            " AND exchange != 'upbit' GROUP BY exchange, uuid"
            " HAVING revision = MAX(revision)").fetchall():
        try:
            d9 = json.loads(t["payload"])
        except json.JSONDecodeError:
            continue
        if str(d9.get("state") or "").upper() != "DONE":
            continue
        c._post_exf_withdraw(t["exchange"], t["uuid"], d9)
    for t in conn.execute(
            "SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
            " AND exchange != 'upbit' GROUP BY exchange, uuid"
            " HAVING revision = MAX(revision)").fetchall():
        try:
            d9 = json.loads(t["payload"])
        except json.JSONDecodeError:
            continue
        if str(d9.get("state") or "").upper() != "ACCEPTED":
            continue
        c._post_exf_deposit_in(t["exchange"], t["uuid"], d9)
    conn.commit()
    print(f"해외거래소 체결 재파생: {nf}건")

    orders = []
    for o in conn.execute(
            "SELECT payload FROM raw_ex WHERE kind='order'"
            " GROUP BY uuid HAVING revision = MAX(revision)").fetchall():
        try:
            orders.append(json.loads(o["payload"]))
        except json.JSONDecodeError:
            continue
    if orders:
        c._consume_fills({"orders": orders})
        conn.commit()
    print(f"체결 재파생: {len(orders)}건 투입")

    legacy = conn.execute(
        "SELECT count(*) FROM postings WHERE location LIKE 'wallet:%'"
        " AND location NOT LIKE 'wallet:%:%'").fetchone()[0]
    ev = dict(conn.execute(
        "SELECT event, count(*) FROM tx_class GROUP BY event ORDER BY 2 DESC").fetchall())
    print("지갑미상(레거시) posting:", legacy, "— 0 이어야 정상(구형 sol 레코드 제외)")
    print("분류 분포:", ev)
    if err:
        print(f"★재파생 실패 {err}건 — rebuild_incomplete 마커 유지, core 기동 차단됨."
              " 원인 해결 후 rebuild 재실행하라★")
        raise SystemExit(2)
    conn.execute("DELETE FROM meta WHERE k='rebuild_incomplete'")
    conn.commit()
    print("완료(마커 해제). recon(기초잔고 대사)은 core 재기동 후 각 체인이 따라잡히면 자동 재실행된다.")


if __name__ == "__main__":
    main()
