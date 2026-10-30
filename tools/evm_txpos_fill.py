#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

USAGE_HEAD = "evm_txpos_fill — EVM 옛 기록 같은 블록 순서(tx.position) 채우기 · 미리보기 기본(외부 0콜)"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import chain_registry, config, histmark, logs, paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import ledger_lock  # noqa: E402

KIND = "evm_txpos_fill_v1"
CACHE = "evm_txpos_fill.json"
UNDO_PREFIX = "evm_txpos_undo_"
RECEIPT = "txpos_fill:"
RPS_DEFAULT, RPS_CAP = 1.0, 2.0
NET_STREAK_STOP = 5
SAVE_EVERY = 10
URL_TRY = 2
HOLD = ("wallet:", "exchange:", "lp:")
TXH = re.compile(r"0x[0-9a-f]{64}")
KST = timezone(timedelta(hours=9))


def _day(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d") if ts else "?"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _ro():
    c = sqlite3.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _evm(chain) -> bool:
    return bool(chain) and chain != "sol" and not chain_registry.is_nonevm(chain)


def _urls(cfg, chain) -> list:
    if chain == "bsc":
        b = cfg.get("bsc") or {}
        return [u for u in list(b.get("detail_rpcs") or []) + list(b.get("logs_rpcs") or []) if u]
    cc = (cfg.get("chains") or {}).get(chain) or {}
    from evm_watch import RpcSynthMixin as _RS
    return list(cc.get("rpcs") or _RS.RPC_DEFAULT.get(chain) or [])


def scan(conn, every: bool = False) -> dict:
    grp = {}
    for ch, blk, txid in conn.execute("SELECT chain, block, txhash FROM raw_txs WHERE block IS NOT NULL AND chain != 'sol'"):
        if TXH.fullmatch(str(txid or "").lower()):
            grp.setdefault((ch, int(blk)), []).append(txid)
    out = {}
    for (ch, blk), ids in grp.items():
        if len(ids) < 2 or not _evm(ch):
            continue
        txs, wal = {}, {}
        for txid in ids:
            r = conn.execute("SELECT blockhash, ts, wallets, CASE WHEN json_valid(snapshot) THEN json_type(snapshot, '$.tx') END,"
                             " CASE WHEN json_valid(snapshot) THEN json_extract(snapshot, '$.tx.position') END FROM raw_txs WHERE chain=? AND txhash=?",
                             (ch, txid)).fetchone()
            h = str(txid).lower()
            txs[h] = {"id": txid, "pos": r[4], "bh": (str(r[0]).lower() if r[0] else None), "ts": r[1], "fill": r[3] == "object" and r[4] is None}
            try:
                wal[h] = {str(w).lower() for w in json.loads(r[2] or "[]")}
            except (TypeError, ValueError):
                wal[h] = set()
        if not any(t["fill"] for t in txs.values()):
            continue
        if every:
            seen, cand = set(), False
            for h in txs:
                cand = cand or bool(wal[h] & seen)
                seen |= wal[h]
        else:
            cand = _sensitive(conn, ch, txs)
        if cand:
            for t in txs.values():
                t["ts"] = _first_ts(conn, ch, t["id"], t["ts"])
        out[(ch, blk)] = {"txs": txs, "cand": cand}
    return out


def _sensitive(conn, ch, txs) -> bool:
    flow = {}
    for h, t in txs.items():
        f = {}
        for q, loc, lk, g, d in conn.execute(
                "SELECT p.qty_base, p.location, p.leg_kind, COALESCE(a.group_id, -a.asset_id), a.decimals FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (ch, t["id"])):
            if lk in ("gas", "fee", "opening") or not str(loc or "").startswith(HOLD):
                continue
            f[g] = f.get(g, Decimal(0)) + Decimal(int(q)) / (Decimal(10) ** int(18 if d is None else d))
        flow[h] = f
    for a, fa in flow.items():
        for b, fb in flow.items():
            if a != b and (txs[a]["fill"] or txs[b]["fill"]) and any(v < 0 and fb.get(g, 0) > 0 for g, v in fa.items()):
                return True
    return False


def _cache_path():
    return os.path.join(paths.STATE_DIR, CACHE)


def load_cache() -> dict:
    d = statefile.read_json(_cache_path(), None)
    if not isinstance(d, dict) or d.get("v") != 1:
        d = {"v": 1, "ok": {}, "fail": {}}
    d.setdefault("ok", {})
    d.setdefault("fail", {})
    return d


def _key(ch, blk):
    return f"{ch}:{int(blk)}"


def _nohash(b) -> bool:
    return any(not t["bh"] for t in b["txs"].values())


def _have(cache, k, b) -> bool:
    e = cache["ok"].get(k)
    return isinstance(e, dict) and all(t["id"] in e.get("pos", {}) and (not t["bh"] or t["bh"] == e.get("h")) for t in b["txs"].values())


def check_block(res, blk: int, txs: dict) -> dict:
    if not isinstance(res, dict):
        raise ValueError("응답 형식 오류")
    try:
        num = int(str(res.get("number")), 16)
    except ValueError:
        raise ValueError("블록 번호 없음") from None
    if num != blk:
        raise ValueError(f"블록 번호 다름({num})")
    bh = str(res.get("hash") or "").lower()
    if not TXH.fullmatch(bh):
        raise ValueError("블록 해시 없음")
    lst = res.get("transactions")
    if not isinstance(lst, list):
        raise ValueError("거래 목록 없음")
    idx = {}
    for i, t in enumerate(lst):
        h = str((t.get("hash") if isinstance(t, dict) else t) or "").lower()
        idx.setdefault(h, i)
    pos = {}
    for h, t in txs.items():
        if t["bh"] and t["bh"] != bh:
            raise ValueError("저장 블록 해시와 다름(재조직?)")
        if h not in idx:
            raise ValueError("우리 거래가 블록 목록에 없음")
        if t["pos"] is not None and str(t["pos"]) != str(idx[h]):
            raise ValueError("이미 있는 순번과 목록 자리가 다름")
        pos[t["id"]] = idx[h]
    return {"h": bh, "pos": pos}


def fetch(cands, cache, cfg, rps, limit=0, save=None, stop=None, clock=time.monotonic, sleep=time.sleep) -> dict:
    import recon
    rps = max(0.05, min(float(rps), RPS_CAP))
    gap, last, n, streak = 1.0 / rps, None, 0, 0
    st = {"calls": 0, "ok": 0, "fail": 0, "stopped": "", "nohash": 0}
    for (ch, blk), b in sorted(cands, key=lambda kb: _key(*kb[0]) in cache["fail"]):
        k = _key(ch, blk)
        if _nohash(b):
            st["nohash"] += 1
            continue
        if _have(cache, k, b):
            continue
        cache["ok"].pop(k, None)
        if stop is not None and stop():
            st["stopped"] = "신호"
            break
        if limit and n >= limit:
            st["stopped"] = "--limit"
            break
        urls = _urls(cfg, ch)[:URL_TRY]
        if not urls:
            cache["fail"][k] = {"why": "엔드포인트 없음", "at": int(time.time())}
            st["fail"] += 1
            continue
        res, err = None, None
        for u in urls:
            if limit and n >= limit:
                break
            if last is not None and clock() - last < gap:
                sleep(gap - (clock() - last))
            last, n = clock(), n + 1
            st["calls"] += 1
            try:
                res, err = recon._rpc_any([u], "eth_getBlockByNumber", [hex(blk), False], tries=1), None
                break
            except Exception as e:   # noqa: BLE001 [fallback]
                err = e
        if err is not None or res is None:
            cache["fail"][k] = {"why": "조회 실패: " + logs.safe_err(str(err or "--limit"))[:120], "at": int(time.time())}
            st["fail"] += 1
            streak += 1
            if streak >= NET_STREAK_STOP:
                st["stopped"] = f"연속 실패 {streak}"
                break
            continue
        try:
            cache["ok"][k] = dict(check_block(res, blk, b["txs"]), at=int(time.time()))
            cache["fail"].pop(k, None)
            st["ok"] += 1
            streak = 0
        except ValueError as e:
            cache["fail"][k] = {"why": str(e), "at": int(time.time())}
            st["fail"] += 1
            streak += 1
            if streak >= NET_STREAK_STOP:
                st["stopped"] = f"연속 실패 {streak}"
                break
        if save is not None and n % SAVE_EVERY == 0:
            save()
    if save is not None:
        save()
    return st


def _rw():
    rw = sqlite3.connect(paths.DB_PATH, timeout=30, isolation_level=None)
    why9 = dbm.fence_why(rw)
    if why9:
        rw.close()
        raise RuntimeError("거부(세대 펜스 · 원장 무변): " + why9)
    return rw


def _first_ts(rw, ch, txid, raw_ts):
    r = rw.execute("SELECT min(event_ts) FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?", (ch, txid)).fetchone()
    return int(r[0]) if r and r[0] is not None else (int(raw_ts) if raw_ts else None)


def apply(cache, now=None) -> dict:
    now = int(time.time() if now is None else now)
    rw = _rw()
    rows, skip = [], {}
    try:
        rw.execute("BEGIN IMMEDIATE")
        heads = {}
        for ch9, blk9, h9, bh9 in rw.execute("SELECT chain, block, txhash, blockhash FROM raw_txs WHERE block IS NOT NULL AND chain != 'sol'"):
            heads.setdefault((ch9, int(blk9)), {})[h9] = str(bh9).lower() if bh9 else None
        for k, ent in sorted(cache["ok"].items()):
            ch, _, blk = k.rpartition(":")
            hb = heads.get((ch, int(blk)), {})
            if not all(h in hb for h in ent.get("pos", {})) or any(v != ent.get("h") for v in hb.values()):
                why9 = "해시 없음 건너뜀" if any(v is None for v in hb.values()) else "블록 대조 다름(다시 --fetch)"
                skip[why9] = skip.get(why9, 0) + len(ent.get("pos", {}))
                continue
            for h, i in sorted(ent.get("pos", {}).items()):
                r = rw.execute("SELECT txhash, block, blockhash, ts, snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ch, h)).fetchone()
                why = None
                if r is None or r[1] is None or int(r[1]) != int(blk):
                    why = "원본 없음·블록 다름"
                elif r[2] and str(r[2]).lower() != ent.get("h"):
                    why = "블록 해시 다름"
                else:
                    try:
                        snap = json.loads(r[4])
                    except ValueError:
                        snap = None
                    tx = snap.get("tx") if isinstance(snap, dict) else None
                    if not isinstance(tx, dict):
                        why = "스냅샷 tx 없음"
                    elif tx.get("position") is not None:
                        why = "이미 순번 있음"
                if why:
                    skip[why] = skip.get(why, 0) + 1
                    continue
                tx["position"] = int(i)
                new = json.dumps(snap, ensure_ascii=False)
                if rw.execute("UPDATE raw_txs SET snapshot=? WHERE chain=? AND txhash=? AND snapshot=?", (new, ch, r[0], r[4])).rowcount != 1:
                    raise RuntimeError(f"{ch} {h[:12]}: 원본 바꾸기 실패")
                rw.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                           (RECEIPT + f"{ch}:{r[0]}", json.dumps({"pos": int(i), "sha": _sha(new)}, separators=(",", ":"))))
                rows.append({"chain": ch, "txhash": r[0], "pos": int(i), "before": r[4], "before_sha": _sha(r[4]), "after_sha": _sha(new),
                             "ts": _first_ts(rw, ch, r[0], r[3])})
        if not rows:
            rw.execute("ROLLBACK")
            return {"n": 0, "skip": skip, "undo": None}
        path = os.path.join(paths.STATE_DIR, f"{UNDO_PREFIX}{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}_{secrets.token_hex(3)}.json")
        statefile.atomic_write_json(path, {"kind": KIND, "at": now, "rows": rows})
        dbm.bump_daily_inval(rw)
        t9 = [r["ts"] for r in rows if r["ts"]]
        if t9:
            print("장기 곡선 다시 계산 표식:", histmark.mark_hist_dirty(min(t9)))
        rw.execute("COMMIT")
    except BaseException:
        if rw.in_transaction:
            rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()
    return {"n": len(rows), "skip": skip, "undo": path}


def undo(obj, write: bool) -> dict:
    rw = _rw() if write else sqlite3.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=30)
    ok, refuse = [], {}
    try:
        if write:
            rw.execute("BEGIN IMMEDIATE")
        for r in obj.get("rows") or []:
            ch, h = str(r.get("chain")), str(r.get("txhash"))
            m = rw.execute("SELECT v FROM meta WHERE k=?", (RECEIPT + f"{ch}:{h}",)).fetchone()
            cur = rw.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?", (ch, h)).fetchone()
            why = None
            try:
                mv = json.loads(m[0]) if m else None
            except ValueError:
                mv = None
            if not isinstance(mv, dict) or mv.get("pos") != r.get("pos") or mv.get("sha") != r.get("after_sha"):
                why = "영수증 없음·다름(이미 되돌림 · 다른 원장 · 손댄 파일)"
            elif cur is None or _sha(cur[0]) != r.get("after_sha"):
                why = "지금 원본이 적용한 것과 다름(sha256)"
            elif _sha(str(r.get("before"))) != r.get("before_sha"):
                why = "되돌리기 파일 원본 sha256 다름"
            if why:
                refuse[why] = refuse.get(why, 0) + 1
                continue
            if write:
                if rw.execute("UPDATE raw_txs SET snapshot=? WHERE chain=? AND txhash=? AND snapshot=?", (r["before"], ch, h, cur[0])).rowcount != 1:
                    raise RuntimeError(f"{ch} {h[:12]}: 되돌리기 실패")
                rw.execute("DELETE FROM meta WHERE k=?", (RECEIPT + f"{ch}:{h}",))
            ok.append(r)
        if write and ok:
            dbm.bump_daily_inval(rw)
            t9 = [int(r["ts"]) for r in ok if r.get("ts")]
            if t9:
                print("장기 곡선 다시 계산 표식:", histmark.mark_hist_dirty(min(t9)))
            rw.execute("COMMIT")
        elif write:
            rw.execute("ROLLBACK")
    except BaseException:
        if rw.in_transaction:
            rw.execute("ROLLBACK")
        raise
    finally:
        rw.close()
    return {"n": len(ok), "refuse": refuse}


def report(found, cache, cfg, rps):
    cands = [(k, b) for k, b in sorted(found.items()) if b["cand"]]
    by = {}
    for (ch, blk), b in cands:
        s = by.setdefault(ch, {"blocks": 0, "txs": 0, "first": None, "done": 0, "fail": 0, "nohash": 0})
        s["blocks"] += 1
        s["txs"] += sum(1 for t in b["txs"].values() if t["fill"])
        t0 = min((t["ts"] for t in b["txs"].values() if t["ts"]), default=None)
        s["first"] = t0 if s["first"] is None or (t0 and t0 < s["first"]) else s["first"]
        s["nohash"] += _nohash(b)
        s["done"] += _have(cache, _key(ch, blk), b) and not _nohash(b)
        s["fail"] += _key(ch, blk) in cache["fail"]
    left = sum(s["blocks"] - s["done"] - s["nohash"] for s in by.values())
    for ch, s in sorted(by.items()):
        print(f"  {ch:>10} 블록 {s['blocks']} · 순번 없는 거래 {s['txs']} · 해시 없음 건너뜀 {s['nohash']} · 예상 호출 {s['blocks'] - s['done'] - s['nohash']}(블록당 1) · 가장 이른 날 {_day(s['first'])}"
              f" · 받음 {s['done']} · 실패 {s['fail']} · 엔드포인트 {len(_urls(cfg, ch))}")
    print(f"후보 블록 {len(cands)} · 남은 조회 {left}회 ≈ {left / max(0.05, min(rps, RPS_CAP)) / 60:.1f}분(초당 {min(rps, RPS_CAP):g}회)")
    why = {}
    for v in cache["fail"].values():
        why[v.get("why")] = why.get(v.get("why"), 0) + 1
    if why:
        print("받기 실패 사유:", why)
    fillable = 0
    for k, e in cache["ok"].items():
        ch, _, blk = k.rpartition(":")
        b = found.get((ch, int(blk))) or {"txs": {}}
        if _nohash(b):
            continue
        fillable += sum(1 for h in e.get("pos", {}) if b["txs"].get(str(h).lower(), {}).get("fill"))
    print(f"받아 둔 블록 {len(cache['ok'])} · 적용하면 채울 거래 {fillable}")
    return cands


def _args(argv):
    ap = argparse.ArgumentParser(prog="evm_txpos_fill.py", description=USAGE_HEAD + " · --fetch = 블록당 1콜 · --apply = tj-core 정지 중에만(원장 작성자 잠금).")
    ap.add_argument("--all", action="store_true", help="같은 지갑이 낀 같은 블록 전부(기본 = 순서에 민감한 블록만)")
    ap.add_argument("--fetch", action="store_true", help="못 받은 후보 블록을 블록당 eth_getBlockByNumber 1콜로 받음(원장 무접촉)")
    ap.add_argument("--rps", type=float, default=RPS_DEFAULT, help=f"초당 조회 수(기본 {RPS_DEFAULT:g} · 상한 {RPS_CAP:g})")
    ap.add_argument("--limit", type=int, default=0, help="이번 실행 조회 상한(0 = 전부)")
    ap.add_argument("--apply", action="store_true", help="받아 둔 자리를 원본에 채움(tj-core 를 멈춘 뒤) · --undo 와 같이 = 실제 되돌리기")
    ap.add_argument("--undo", metavar="UNDO_JSON", help="되돌리기 파일(state/evm_txpos_undo_….json)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = _args(sys.argv[1:] if argv is None else argv)
    if sum(bool(x) for x in (a.fetch, a.apply and not a.undo, a.undo)) > 1:
        print("거부: --fetch · --apply · --undo 중 하나만(--undo 는 --apply 와 같이 써야 실제로 씀)")
        return 2
    print(f"원장 {paths.DB_PATH}")
    if not os.path.isfile(paths.DB_PATH):
        print("거부: 원장 없음 — TJ_BASE 확인")
        return 1
    if (a.fetch or a.apply) and os.stat(paths.DB_PATH).st_uid != os.getuid():
        print("거부: 원장 주인과 다른 사용자 — 서비스 사용자로 실행(root 로 쓰면 state 파일이 root 소유가 돼 봇이 못 씀)")
        return 1
    if a.undo:
        try:
            with open(a.undo, encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError) as e:
            print("거부: 되돌리기 파일 읽기 실패 —", e)
            return 1
        if not isinstance(obj, dict) or obj.get("kind") != KIND:
            print("거부: 이 도구의 되돌리기 파일이 아님")
            return 1
        with ledger_lock.hold_if(a.apply, paths.DB_PATH, who="evm_txpos_fill --undo --apply"):
            res = undo(obj, a.apply)
        print(("되돌림" if a.apply else "되돌릴 수 있음(미리보기 — --apply 로 실제)") + f" {res['n']}건 · 거부 {res['refuse'] or 0}")
        return 0
    cache = load_cache()
    if a.apply:
        with ledger_lock.hold(paths.DB_PATH, who="evm_txpos_fill --apply"):
            res = apply(cache)
        if not res["n"]:
            print("할 일 없음(채울 거래 0)" + (f" · 건너뜀 {res['skip']}" if res["skip"] else ""))
            return 0
        print(f"채움 {res['n']}건 · 건너뜀 {res['skip'] or 0} · 되돌리기 파일 {res['undo']}")
        return 0
    cfg = config.load_config()
    conn = _ro()
    try:
        found = scan(conn, a.all)
    finally:
        conn.close()
    print("후보 기준:", "같은 지갑이 낀 같은 블록 전부(--all)" if a.all else "순서에 민감한 같은 블록(기본)")
    cands = report(found, cache, cfg, a.rps)
    if not a.fetch:
        print("미리보기 — 외부 호출 0 · 쓰기 0")
        return 0
    flag = []

    def _sig(*_a):
        flag.append(1)
    old = [signal.signal(s, _sig) for s in (signal.SIGINT, signal.SIGTERM)]
    try:
        st = fetch(cands, cache, cfg, a.rps, a.limit, save=lambda: statefile.atomic_write_json(_cache_path(), cache), stop=lambda: bool(flag))
    finally:
        for s, h in zip((signal.SIGINT, signal.SIGTERM), old):
            signal.signal(s, h)
    print(f"받기: 호출 {st['calls']} · 받음 {st['ok']} · 실패 {st['fail']} · 해시 없음 건너뜀 {st['nohash']}" + (f" · 멈춤({st['stopped']})" if st["stopped"] else "") + f" → state/{CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
