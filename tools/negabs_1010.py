#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import common
import discopen


def _ro():
    if not os.path.exists(common.DB_PATH):
        raise SystemExit("원장 없음: " + common.DB_PATH)
    c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _wallets(cfg) -> dict:
    out = {}
    for w in cfg.get("wallets") or []:
        t = w.get("type", "evm")
        if t == "evm":
            out.setdefault(w.get("chain"), set()).add(str(w.get("address") or "").lower())
        elif t == "bsc_rpc":
            out.setdefault("bsc", set()).add(str(w.get("address") or "").lower())
    out.pop("sol", None)
    out.pop(None, None)
    return out


def _urls(cfg, chain):
    if chain == "bsc":
        b = cfg.get("bsc") or {}
        return [u for u in list(b.get("detail_rpcs") or []) + list(b.get("logs_rpcs") or []) if u]
    cc = (cfg.get("chains") or {}).get(chain) or {}
    from evm_watch import RpcSynthMixin as _RS
    return list(cc.get("rpcs") or _RS.RPC_DEFAULT.get(chain) or [])


def _fmt(q, dec):
    try:
        return f"{int(q) / (10 ** int(dec if dec is not None else 18)):,.6f}"
    except (TypeError, ValueError):
        return str(q)


def _prefs():
    try:
        d = common.read_json(os.path.join(common.STATE_DIR, "ui_prefs.json"), {}) or {}
    except SystemExit:
        d = {}
    return d if isinstance(d, dict) else {}


def preview_neg(a, cfg) -> list:
    my = _wallets(cfg)
    chains = set(my) - {"sol"}
    conn = _ro()
    prefs = _prefs()
    out = []
    try:
        for ch, w, aid in discopen.neg_cells(conn, chains):
            if (a.chain and ch != a.chain) or (a.wallet and w != a.wallet.lower()):
                continue
            ar = discopen.asset_row(conn, aid)
            pl = discopen.plan_cell(conn, ch, w, aid, prefs, my.get(ch))
            k = discopen.cand_key(ch, w, aid)
            st0 = discopen._jload(discopen._meta(conn, k), None)
            row = {"chain": ch, "wallet": w, "aid": aid, "sym": ar[3] if ar else "?", "ca": (ar[2] if ar and ar[0] == "token" else None),
                   "dec": ar[4] if ar else None, "plan": pl["st"], "why": pl.get("why", ""), "core": (st0 or {}).get("st")}
            tot = sum(int(r[0]) for r in conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:{ch}:{w}", aid)))
            row["ledger"] = str(tot)
            if pl["st"] == "go":
                row.update(tx=pl["tx"], block=pl["block"], at=pl["ts"] - 1)
                if a.rpc:
                    urls = _urls(cfg, ch)
                    try:
                        bal, bts = discopen.fetch_at(urls, w, pl["ca"], pl["block"] - 1)
                        base = discopen.posted_le(pl["rows"], pl["block"] - 1, pl["ts"])
                        row.update(bal=str(bal), base=str(base), anchor=str(bal - base) if base is not None else None)
                    except Exception as e:
                        row["rpc_err"] = common.safe_err(str(e))[:120]
                        row["state_err"] = discopen._state_err(e)
            out.append(row)
    finally:
        conn.close()
    return out


def preview_recheck(a, cfg, path) -> list:
    my = _wallets(cfg)
    conn = _ro()
    prefs = _prefs()
    out = []
    bts_cache = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        for ln in lines:
            try:
                it = json.loads(ln)
            except ValueError:
                out.append({"st": "err", "why": "JSON 아님", "line": ln[:80]})
                continue
            if not isinstance(it, dict):
                continue
            ch, w = str(it.get("chain") or ""), str(it.get("wallet") or "").lower()
            if (a.chain and ch != a.chain) or (a.wallet and w != a.wallet.lower()):
                continue
            row = {"chain": ch, "wallet": w, "ca": it.get("ca"), "sym": it.get("symbol"), "block": it.get("block"), "diff_raw": str(it.get("diff_raw")),
                   "spam": it.get("spam"), "dec": it.get("decimals")}
            try:
                dr = int(str(it.get("diff_raw")))
            except (TypeError, ValueError):
                row.update(st="err", why="diff_raw 형식")
                out.append(row)
                continue
            if it.get("spam") is not False:
                row.update(st="skip", why="스팸 표시(또는 판정 없음)")
            elif dr <= 0:
                row.update(st="list", why="원장이 더 많거나 같음 — 넣지 않음(목록만)")
            elif w not in (my.get(ch) or set()):
                row.update(st="skip", why="추적 중인 등록 지갑·체인 아님")
            else:
                ca = it.get("ca")
                ca = None if ca in (None, "", "native") else str(ca).lower()
                r = conn.execute("SELECT asset_id FROM assets WHERE kind='native' AND chain=?", (ch,)).fetchone() if ca is None else \
                    conn.execute("SELECT asset_id FROM assets WHERE kind='token' AND chain=? AND address=?", (ch, ca)).fetchone()
                why = discopen.asset_guard(conn, r[0], prefs) if r else ""
                if not why and ca and not r:
                    from spamguard import impostor_of, odd_symbol, is_genuine
                    if not is_genuine(ch, ca) and (impostor_of(it.get("symbol")) or odd_symbol(it.get("symbol"))):
                        why = "사칭·혼용 심볼"
                if why:
                    row.update(st="skip", why=why)
                else:
                    row.update(st="go", why="원장에 처음 보는 토큰" if not r else "")
                    if r:
                        rows = discopen.cell_rows(conn, f"wallet:{ch}:{w}", r[0])
                        base = discopen.posted_le(rows, int(it["block"]), 1 << 62)
                        row["base_now"] = None if base is None else str(base)
                        if base is not None and base < 0:
                            row.update(st="list", why="그 블록에서 원장 음수 — ② 경로(나간 거래 직전 블록) 대상")
                    if row["st"] == "go" and (a.apply or a.rpc) and not it.get("block_ts"):
                        kb = (ch, int(it["block"]))
                        if kb not in bts_cache:
                            try:
                                import recon

                                def _blk(rr, b=int(it["block"])):
                                    if not isinstance(rr, dict) or recon._hex_int(rr.get("number")) != b:
                                        raise ValueError("블록 불일치")
                                    return recon._hex_int(rr.get("timestamp"))
                                bts_cache[kb] = recon._rpc_any(_urls(cfg, ch), "eth_getBlockByNumber", [hex(int(it["block"])), False], check=_blk, tries=2)
                            except Exception as e:
                                bts_cache[kb] = None
                                row["rpc_err"] = common.safe_err(str(e))[:120]
                        row["block_ts"] = bts_cache[kb]
                    elif it.get("block_ts"):
                        row["block_ts"] = it.get("block_ts")
            row["_item"] = it
            out.append(row)
    finally:
        conn.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="발견 시점 기초 잔고 — 미리보기(기본) · --apply = tj-core 요청 파일")
    ap.add_argument("--apply", action="store_true", help="요청 파일을 쓴다(원장은 tj-core 가 다시 확인한 뒤 기장)")
    ap.add_argument("--rpc", action="store_true", help="미리보기에 직전 블록 잔고 조회 포함(칸당 1~3콜 · 무료 RPC)")
    ap.add_argument("--recheck", metavar="FILE", help="토큰 재점검 결과 JSON 줄(tools/token_recheck_1010.py)")
    ap.add_argument("--chain")
    ap.add_argument("--wallet")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--retry", action="store_true", help="이미 결과 난 칸도 다시(② --apply)")
    a = ap.parse_args(argv)
    cfg = common.load_config()
    if a.recheck:
        rows = preview_recheck(a, cfg, a.recheck)
        if a.json:
            print(json.dumps([{k: v for k, v in r.items() if k != "_item"} for r in rows], ensure_ascii=False, indent=1, default=str))
        else:
            for r in rows:
                print(f"[{r.get('st')}] {r.get('chain')} {str(r.get('wallet'))[:10]}… {r.get('sym')} 블록 {r.get('block')} 차이 {r.get('diff_raw')}"
                      f"{' · ' + r['why'] if r.get('why') else ''}{' · 블록 시각 ' + str(r.get('block_ts')) if r.get('block_ts') else ''}")
            n = {}
            for r in rows:
                n[r.get("st")] = n.get(r.get("st"), 0) + 1
            print("요약:", n)
        if a.apply:
            items = []
            for r in rows:
                if r.get("st") == "go" and r.get("block_ts"):
                    it = dict(r["_item"])
                    it["block_ts"] = int(r["block_ts"])
                    items.append(it)
            if not items:
                print("요청할 줄 없음")
                return 0
            common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.RECHK_REQ_NAME),
                                     {"items": items, "by": "tools/negabs_1010.py", "at": int(time.time())})
            print(f"요청함 {len(items)}줄 → state/{discopen.RECHK_REQ_NAME} — tj-core 가 다시 확인 뒤 기장 · 결과 state/{discopen.RES_NAME}")
        return 0
    rows = preview_neg(a, cfg)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    else:
        for r in rows:
            amt = f" · 기장 예상 {_fmt(r['anchor'], r['dec'])}" if r.get("anchor") else ""
            err = f" · 조회 실패({'과거 상태 없음' if r.get('state_err') else r.get('rpc_err')})" if r.get("rpc_err") else ""
            print(f"[{r['plan']}] {r['chain']} {r['wallet'][:10]}… {r['sym']} 원장 {_fmt(r['ledger'], r['dec'])}"
                  f"{' · ' + r['why'] if r.get('why') else ''}{' · 거래 ' + r['tx'][:12] + ' 블록 ' + str(r['block']) if r.get('tx') else ''}"
                  f"{amt}{err}{' · core=' + r['core'] if r.get('core') else ''}")
        n = {}
        for r in rows:
            n[r["plan"]] = n.get(r["plan"], 0) + 1
        print(f"음수 칸 {len(rows)} · 판정 {n}")
    if a.apply:
        cells = [{"chain": r["chain"], "wallet": r["wallet"], "ca": r["ca"] or "native", **({"retry": True} if a.retry else {})}
                 for r in rows if r["plan"] in ("go", "wait")]
        if not cells:
            print("요청할 칸 없음")
            return 0
        common.atomic_write_json(os.path.join(common.STATE_DIR, discopen.REQ_NAME), {"cells": cells, "by": "tools/negabs_1010.py", "at": int(time.time())})
        print(f"요청함 {len(cells)}칸 → state/{discopen.REQ_NAME} — tj-core 가 같은 규칙으로 다시 확인·직전 블록 잔고 조회 뒤 기장 · 결과 state/{discopen.RES_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
