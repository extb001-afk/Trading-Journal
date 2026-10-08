"""Verification gate for automatic ledger window rebuilds."""
import hashlib
import json
import os
import sqlite3
import sys
from decimal import Decimal


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import common


def _ro(p):
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(p), uri=True, timeout=30)
        c.execute("SELECT 1").fetchone()
        return c
    except sqlite3.OperationalError:
        return sqlite3.connect(common.sqlite_ro_uri(p, immutable=True), uri=True, timeout=30)


TABLES = {
    "postings": ("SELECT source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                 " cost_usd, cost_krw, leg_kind, event, classifier_ver FROM postings"
                 " ORDER BY source_kind, source_ns, source_id, leg_seq"),
    "positions": "SELECT group_id, location, qty_norm FROM positions ORDER BY group_id, location",
    "tx_class": "SELECT chain, txhash, event, detail, classifier_ver FROM tx_class ORDER BY chain, txhash",
    "transfers": ("SELECT state, asset_id, qty_base, src, dst, chain_txhash, ex_uuid FROM transfers"
                  " ORDER BY chain_txhash, asset_id, src, qty_base, state, ex_uuid"),
}


def table_hashes(db):
    c = _ro(db)
    out = {}
    try:
        for t, q in TABLES.items():
            h = hashlib.sha256()
            n = 0
            for row in c.execute(q):
                h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
                h.update(b"\n")
                n += 1
            out[t] = (n, h.hexdigest())
    finally:
        c.close()
    return out


def cmd_hash(db):
    for t, (n, h) in table_hashes(db).items():
        print(f"{t:10s} {n:>8d} {h}")
    return 0


def cmd_same(a, b):
    ha, hb = table_hashes(a), table_hashes(b)
    ok = True
    for t in TABLES:
        eq = ha[t] == hb[t]
        ok = ok and eq
        print(f"  {'PASS' if eq else '★FAIL'} {t:10s} {ha[t][0]:>8d} {ha[t][1][:16]} | {hb[t][0]:>8d} {hb[t][1][:16]}")
    print("게이트 e(결정성):", "PASS" if ok else "★FAIL★")
    return 0 if ok else 1


def _lp_kinds(db):
    c = _ro(db)
    try:
        return {r[0] for r in c.execute("SELECT DISTINCT event FROM tx_class WHERE event IN ('LP_ADD', 'LP_REMOVE')")}
    except sqlite3.Error:
        return set()
    finally:
        c.close()


def _has_lp(db):
    return bool(_lp_kinds(db))


def cmd_gates(db, bal_path=None, live=None):
    import os
    c = _ro(db)
    ok = True
    want_kinds = _lp_kinds(live) if live else {"LP_ADD", "LP_REMOVE"}
    want_lp = bool(want_kinds)

    def chk(cond, msg):
        nonlocal ok
        print(("  PASS " if cond else "  ★FAIL ") + msg)
        ok = ok and bool(cond)
    try:
        ev = dict(c.execute("SELECT event, count(*) FROM tx_class WHERE event LIKE 'LP%' GROUP BY event").fetchall())
        if want_lp:
            chk(all(ev.get(k, 0) > 0 for k in want_kinds), f"b1 LP 분류 존재(기존 원장 종류 {sorted(want_kinds)} 보존) {ev}")
        else:
            print(f"  info b1 기존 원장에 LP 기록 없음 — LP 분류 존재 검사 건너뜀 {ev}")
        dec = {r[0]: (r[1] if r[1] is not None else 18) for r in c.execute("SELECT asset_id, decimals FROM assets")}
        sym = {r[0]: r[1] for r in c.execute("SELECT asset_id, symbol FROM assets")}
        lp = {}
        for aid, loc, qb in c.execute("SELECT asset_id, location, qty_base FROM postings WHERE location LIKE 'lp:%'"):
            lp[(loc, aid)] = lp.get((loc, aid), 0) + int(qb)
        neg = [(l, sym.get(a), v) for (l, a), v in lp.items() if v < 0]
        chk(not neg, f"b1 LP 원금 음수 없음 — {neg[:5]}")
        unk = [(l, sym.get(a), str(Decimal(v) / (Decimal(10) ** dec[a]))) for (l, a), v in lp.items()
               if v and l.rsplit(":", 1)[1].startswith("?")]
        chk(not unk, f"b1 mint id 미상('?') 위치 잔여 없음 — {unk[:5]}")
        rest = sorted((l, sym.get(a), str(Decimal(v) / (Decimal(10) ** dec[a]))) for (l, a), v in lp.items() if v > 0)
        print(f"  info b2 LP 원금 잔여 위치 {len(rest)}건 (열린 포지션이어야 함):")
        for x in rest[:20]:
            print("       ", x)
        n_lp = c.execute("SELECT count(DISTINCT location) FROM postings WHERE location LIKE 'lp:%'").fetchone()[0]
        if want_lp:
            chk(n_lp > 0, f"b1 LP 포지션 위치 {n_lp}개 기장")
        if bal_path and not os.path.exists(bal_path):
            print("  info c 업비트 잔고 스냅샷 없음(업비트 미연결) — 게이트 c 건너뜀")
        elif bal_path:
            bal = json.load(open(bal_path, encoding="utf-8"))
            actual = {}
            for a in bal.get("accounts") or []:
                cur = str(a.get("currency") or "").upper()
                if cur and cur != "KRW":
                    actual[cur] = Decimal(str(a.get("balance") or 0)) + Decimal(str(a.get("locked") or 0))
            led = {}
            for s, d, qb in c.execute("SELECT upper(a.symbol), a.decimals, p.qty_base FROM postings p JOIN assets a"
                                      " ON a.asset_id=p.asset_id WHERE p.location='exchange:upbit'"):
                led[s] = led.get(s, Decimal(0)) + Decimal(int(qb)) / (Decimal(10) ** int(d if d is not None else 8))
            locked = {str(a.get("currency") or "").upper() for a in bal.get("accounts") or [] if float(a.get("locked") or 0) > 0}
            led_live = set()
            if live and os.path.exists(live):
                try:
                    c9 = sqlite3.connect(common.sqlite_ro_uri(live), uri=True)
                    try:
                        led_live = {r[0] for r in c9.execute("SELECT DISTINCT upper(a.symbol) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                                                             " WHERE p.location='exchange:upbit'")}
                    finally:
                        c9.close()
                except sqlite3.Error:
                    led_live = set()
            syms9 = set(led) | led_live
            bad = sorted((s, str(led.get(s, Decimal(0))), str(actual.get(s, 0))) for s in syms9
                         if abs(led.get(s, Decimal(0)) - actual.get(s, Decimal(0))) > Decimal("0.000001"))
            outside9 = sorted(s for s in set(actual) - syms9 if actual.get(s))
            if outside9:
                print(f"  info c 두 원장 모두에 없는 업비트 잔고 {len(outside9)}종(재구축 전후 같음 — 막지 않음): {outside9[:10]}")
            unl = [b for b in bad if b[0] not in locked]
            chk(not unl, f"c 업비트 전 통화 원장=잔고(미체결 locked 통화 제외) — 불일치 {unl[:8]}")
            if bad:
                print(f"  info c locked 통화 차이(라이브 core 가 미체결 동봉 스냅샷으로 대사 완성): {[b for b in bad if b[0] in locked][:12]}")
    finally:
        c.close()
    print("게이트 b·c:", "PASS" if ok else "★FAIL★")
    return 0 if ok else 1


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "hash":
        sys.exit(cmd_hash(a[1]))
    if a[0] == "same":
        sys.exit(cmd_same(a[1], a[2]))
    if a[0] == "gates":
        bal = a[a.index("--balances") + 1] if "--balances" in a else None
        live = a[a.index("--live") + 1] if "--live" in a else None
        sys.exit(cmd_gates(a[1], bal, live))
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
