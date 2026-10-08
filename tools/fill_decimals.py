#!/usr/bin/env python3
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import common


def meta_caches():
    out = {}
    for f in sorted(os.listdir(common.STATE_DIR)):
        if f.startswith("rpc_token_meta_") and f.endswith(".json"):
            ch, conv = f[len("rpc_token_meta_"):-5], lambda v: v
        elif f == "bsc_token_meta.json":
            ch, conv = "bsc", lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) >= 2 else v
        else:
            continue
        raw = common.read_json(os.path.join(common.STATE_DIR, f), {}) or {}
        m = out.setdefault(ch, {})
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            v = conv(v)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 77:
                m[str(k).lower()] = v
    return out


def main():
    if "--resolve" in sys.argv:
        import ops_requests
        try:
            aid = int(sys.argv[sys.argv.index("--resolve") + 1])
        except (IndexError, ValueError):
            raise SystemExit("--resolve <asset_id(정수)>")
        it = next((x for x in ops_requests.decimals_items() if x["aid"] == aid), None)
        if not it or it["kind"] != "conflict":
            print(f"#{aid} 은 지금 '자리수 다름' 목록에 없어요")
            return 2
        print(f"#{aid} {it.get('symbol')}({it.get('chain')}) 저장 {it.get('stored')} → 관측 {it.get('seen')}")
        ok, msg = ops_requests.decimals_request(aid, it.get("stored"), it.get("seen"), "tools/fill_decimals.py")
        print(msg)
        return 0 if ok else 2
    as_json = "--json" in sys.argv
    if not os.path.exists(common.DB_PATH):
        raise SystemExit("원장 없음: " + common.DB_PATH)
    c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    meta = meta_caches()
    posted = {int(r[0]): int(r[1]) for r in c.execute(
        "SELECT p.asset_id, count(*) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE a.kind='token' AND a.decimals IS NULL GROUP BY p.asset_id")}
    null_rows, conflicts = [], []
    for r in c.execute("SELECT asset_id, chain, address, symbol, decimals FROM assets WHERE kind='token' AND address IS NOT NULL"):
        m9 = meta.get(r["chain"] or "", {}).get(str(r["address"]).lower())
        if r["decimals"] is None:
            null_rows.append({"asset_id": r["asset_id"], "chain": r["chain"], "symbol": r["symbol"], "address": r["address"],
                              "postings": posted.get(int(r["asset_id"]), 0), "cache": m9})
        elif m9 is not None and int(r["decimals"]) != m9:
            conflicts.append({"asset_id": r["asset_id"], "chain": r["chain"], "symbol": r["symbol"], "stored": r["decimals"], "cache": m9})
    c.close()
    try:
        issues = json.load(open(os.path.join(common.STATE_DIR, "asset_decimals_issues.json"), encoding="utf-8")) or {}
    except (OSError, ValueError):
        issues = {}
    rep = {"null_total": len(null_rows), "null_posted": [x for x in null_rows if x["postings"]],
           "will_fill_now": sum(1 for x in null_rows if not x["postings"] and x["cache"] is not None),
           "will_fix_on_rebuild": [x for x in null_rows if x["postings"] and x["cache"] is not None and x["cache"] != 18],
           "conflicts": conflicts, "issues_file": issues.get("items") or {}}
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    print(f"decimals NULL 토큰 {rep['null_total']}개 · 기장된 것 {len(rep['null_posted'])}개 · 기동 때 바로 채울 것(캐시 있음·미기장) {rep['will_fill_now']}개")
    print("기장됐고 캐시 값이 18 이 아님(지금 수량 표시가 틀림 → 다음 재구축에서 바로잡힘):")
    for x in rep["will_fix_on_rebuild"] or [{"symbol": "(없음)"}]:
        print("  ", x)
    print("기장됐고 캐시 없음/18(표시는 18 로 읽어 같음 — 확인 불가 또는 무해):")
    for x in [y for y in rep["null_posted"] if y not in rep["will_fix_on_rebuild"]][:30]:
        print("  ", x)
    print(f"저장값 ≠ 캐시(덮지 않음 — 확인 필요 · 관측값으로 고치려면 --resolve <asset_id> 또는 상태 패널 '정리 요청') {len(conflicts)}개:")
    for x in conflicts[:30]:
        print("  ", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
