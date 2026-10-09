#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
import time
from types import SimpleNamespace

USAGE_HEAD = "repair_wrap_legs — 이더스캔 경로로 이미 기장된 '직접 감싸기·풀기'에 빠진 랩드 토큰 레그 1회 복구 (외부 검토 K2 · fxcollect1009)."

HERE = os.path.dirname(os.path.abspath(__file__))


def find(conn, cfg, chains=None) -> list:
    import core
    import evm_watch
    wn = {str(k).lower(): str(v).lower() for k, v in (cfg.get("wrapped_native") or {}).items() if v}
    mine = {}
    for w in cfg.get("wallets") or []:
        if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain"):
            mine.setdefault(str(w["chain"]).lower(), []).append(str(w.get("address") or "").lower())
    out = []
    for ch in sorted(wn):
        if chains and ch not in chains:
            continue
        wr = wn[ch]
        dr = conn.execute("SELECT decimals FROM assets WHERE kind='token' AND chain=? AND address=?", (ch, wr)).fetchone()
        dec = dr[0] if dr and dr[0] is not None else None
        for h, snap_s, w_s in conn.execute(
                "SELECT txhash, snapshot, wallets FROM raw_txs WHERE chain=? AND lower(json_extract(snapshot, '$.tx.to'))=?", (ch, wr)):
            try:
                snap = json.loads(snap_s)
            except (TypeError, ValueError):
                continue
            if not core.Core._es_list(snap):
                continue
            tx = snap.get("tx") or {}
            if str(tx.get("status") or "") != "ok":
                continue
            trow = {"hash": h, "from": tx.get("from"), "to": tx.get("to"), "value": tx.get("value"), "input": tx.get("raw_input")}
            ent = {"tt": [], "it": [{"from": r.get("from"), "to": r.get("to"), "value": r.get("value"),
                                     "isError": "0" if r.get("success", True) and not r.get("error") else "1"}
                                    for r in snap.get("internal") or [] if isinstance(r, dict)]}
            def _dec(ca, dec=dec):
                if dec is None:
                    raise RuntimeError("랩드 토큰 자릿수 모름(원장 자산 표)")
                return int(dec)
            stub = SimpleNamespace(wrapped_ca=wr, wallets=mine.get(ch) or [], _rpc_token_dec=_dec)
            legs = evm_watch.EtherscanWatcher._es_wrap_legs(stub, trow, "ok", ent, list(snap.get("token_transfers") or []))
            if not legs:
                if legs is None:
                    print(f"  [건너뜀] {ch} {h[:12]}… 랩드 토큰 자릿수를 원장에서 못 찾음", file=sys.stderr)
                continue
            new = dict(snap)
            new["token_transfers"] = list(snap.get("token_transfers") or []) + legs
            try:
                ws = json.loads(w_s or "[]")
            except (TypeError, ValueError):
                ws = []
            lg = legs[0]
            out.append({"chain": ch, "txhash": h, "kind": "감싸기" if lg["from"] == evm_watch.RpcSynthMixin.ZERO_ADDR else "풀기",
                        "wallet": lg["to"] if lg["from"] == evm_watch.RpcSynthMixin.ZERO_ADDR else lg["from"], "value": lg["total"]["value"],
                        "decimals": lg["token"]["decimals"], "ts": tx.get("timestamp"), "snapshot": new, "wallets": ws})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=USAGE_HEAD)
    ap.add_argument("--base", required=True, help="TJ 루트(config.json·state/ 가 있는 곳) — 기본값 없음")
    ap.add_argument("--chains", default="", help="쉼표 구분(기본 = wrapped_native 가 있는 체인 전부)")
    ap.add_argument("--apply", action="store_true", help="inbox/evm 으로 재방출(repair=leg_union)")
    ap.add_argument("--yes", action="store_true", help="--apply 실제 실행 확인")
    a = ap.parse_args(argv)
    base = os.path.realpath(os.path.expanduser(a.base))
    if not os.path.isfile(os.path.join(base, "config.json")) or not os.path.isdir(os.path.join(base, "state")):
        print(f"--base 가 TJ 루트가 아님: {base}", file=sys.stderr)
        return 2
    os.environ["TJ_BASE"] = base
    os.environ.pop("TJ_CONFIG", None)
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    import common
    cfg = json.load(open(os.path.join(base, "config.json"), encoding="utf-8"))
    conn = sqlite3.connect(f"file:{os.path.join(base, 'state', 'ledger.db')}?mode=ro", uri=True)
    try:
        found = find(conn, cfg, {c.strip().lower() for c in a.chains.split(",") if c.strip()} or None)
        ev = {}
        for f in found:
            r9 = conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?", (f["chain"], f["txhash"])).fetchone()
            ev[(f["chain"], f["txhash"])] = r9[0] if r9 else None
    finally:
        conn.close()
    print(f"빠진 랩드 레그(직접 감싸기·풀기) {len(found)}건 — 외부 호출 0")
    for f in found:
        q = int(f["value"]) / (10 ** int(f["decimals"]))
        when = time.strftime("%Y-%m-%d", time.gmtime(int(f["ts"]))) if isinstance(f.get("ts"), int) else "?"
        print(f"  {when} {f['chain']} {f['txhash'][:12]}… {f['kind']} {q:g} · 지금 분류 {ev.get((f['chain'], f['txhash']))} → 재기장 뒤 CONVERT 예상")
    if not a.apply:
        if found:
            print("드라이런 — 재방출하려면 --apply --yes (tj-core 가 inbox 를 소비해야 반영 · 대사 앵커는 core 가 바뀐 양만큼 보정)")
        return 0
    if not found:
        print("적용할 것 없음(no-op)")
        return 0
    if not a.yes:
        print(f"--apply: inbox/evm 레코드 {len(found)}개 예정 — 실제로 하려면 --yes")
        return 0
    import inbox
    w = inbox.SegmentWriter(os.path.join(common.INBOX_DIR, "evm"))
    for f in found:
        w.append({"v": 1, "kind": "evm_tx", "chain": f["chain"], "txhash": f["txhash"], "snapshot": f["snapshot"], "wallets": f["wallets"],
                  "observed_head": 0, "ts": int(time.time()), "repair": "leg_union"})
    w.close()
    print(f"inbox/evm 재방출 {len(found)}건 (repair=leg_union) — tj-core 소비 시 합집합 재기장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
