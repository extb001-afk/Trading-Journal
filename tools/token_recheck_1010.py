#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
import time


def _args(argv=None):
    ap = argparse.ArgumentParser(prog="token_recheck_1010.py", description="기존 지갑 전수 점검(미리보기 전용 · 원장 쓰기 없음)")
    ap.add_argument("--base", help="설치 폴더(config.json·state·src) — 없으면 TJ_BASE 또는 이 파일의 상위")
    ap.add_argument("--src", help="코드 src 폴더(기본 = --base/src 또는 이 파일 옆)")
    ap.add_argument("--state", help="state 폴더(기본 = base/state)")
    ap.add_argument("--chains", default="", help="쉼표 목록(기본 전부)")
    ap.add_argument("--wallets", default="", help="지갑 앞자리 쉼표 목록(기본 전부)")
    ap.add_argument("--max-pairs", type=int, default=0)
    ap.add_argument("--logs-max-calls", type=int, default=600)
    ap.add_argument("--use-cache", action="store_true")
    ap.add_argument("--explain", default="", help="Rabby 설명 지갑 앞자리(기본 = rabby_gap 지갑)")
    ap.add_argument("--out", help="JSON 줄 파일(없으면 표준출력에 'JSONL\\t' 줄)")
    ap.add_argument("--progress", help="진행 저장 파일(이어 돌리기)")
    ap.add_argument("--plan-only", action="store_true", help="예상 콜·시간만 출력")
    ap.add_argument("--go", action="store_true", help="예상이 남은 몫을 넘어도 시작")
    ap.add_argument("--only-failed", action="store_true", help="진행 파일에서 완전히 끝나지 않은 쌍(오류·한도·출처 실패)만 다시")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def _boot(a):
    here = None
    try:
        f = os.path.abspath(__file__)
        here = os.path.dirname(f) if os.path.isfile(f) else None
    except NameError:
        here = None
    base = a.base or os.environ.get("TJ_BASE") or (os.path.dirname(here) if here else None)
    if not base:
        raise SystemExit("--base 필요(표준입력 실행)")
    os.environ["TJ_BASE"] = base
    src = a.src or (os.path.join(os.path.dirname(here), "src") if here and os.path.isfile(os.path.join(os.path.dirname(here), "src", "common.py"))
                    else os.path.join(base, "src"))
    if src not in sys.path:
        sys.path.insert(0, src)
    import common
    if a.state:
        common.rebase_state(a.state)
    return common


def pair_incomplete(td, r: dict) -> str:
    if r.get("err"):
        return "오류: " + str(r["err"])[:80]
    if r.get("stop"):
        return str(r["stop"])[:80]
    soft = [s9 for s9, v in ((r.get("disc") or {}).get("fail") or {}).items() if str(v).split(":")[0] not in td.FINAL_FAIL]
    return ("출처 실패: " + ",".join(sorted(soft))) if soft else ""


def done_keys(prog: dict) -> set:
    res = prog.get("res") or {}
    rt = prog.get("retry") or {}
    out = set()
    for k in (prog.get("done") or {}):
        r9 = res.get(k) or {}
        if k in rt or r9.get("err") or r9.get("full") is False:
            continue
        out.add(k)
    return out


def short(w: str) -> str:
    w = str(w)
    return w[:6] + "…" + w[-4:] if len(w) > 12 else w


def _fmt(raw, dec):
    if raw is None:
        return "?"
    try:
        d = 18 if dec is None else int(dec)
        v = int(raw) / (10 ** d)
    except (TypeError, ValueError, OverflowError):
        return str(raw)
    return f"{v:,.6g}" if abs(v) < 1e15 else f"{v:.3e}"


def _usd(v) -> str:
    return f"${v:,.0f}" if abs(v) >= 10 else f"${v:,.2f}"


def pairs_of(cfg: dict, chains=None, wprefix=None) -> list:
    out = []
    for w in cfg.get("wallets") or []:
        t = w.get("type", "evm")
        c = "bsc" if t == "bsc_rpc" else (w.get("chain") if t == "evm" else None)
        a = str(w.get("address") or "").lower()
        if not c or not a.startswith("0x") or len(a) != 42:
            continue
        if chains and c not in chains:
            continue
        if wprefix and not any(a.startswith(p) for p in wprefix):
            continue
        if (c, a) not in out:
            out.append((c, a))
    return sorted(out)


def cursor_block(common, chain: str, w: str):
    if chain == "bsc":
        cur = common.read_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {}) or {}
        v = cur.get("head")
    else:
        cur = common.read_json(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {}) or {}
        v = cur.get(w, cur.get(str(w).lower()))
    try:
        v = int(v)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def ledger_at(conn, chain: str, w: str, blk: int):
    sums, meta, unk = {}, {}, 0
    for r in conn.execute(
            "SELECT p.asset_id, p.qty_base, p.source_kind, r.block, a.kind, a.address, a.symbol, a.decimals FROM postings p"
            " JOIN assets a ON a.asset_id = p.asset_id"
            " LEFT JOIN raw_txs r ON p.source_kind = 'chain_tx' AND r.chain = p.source_ns AND r.txhash = p.source_id"
            " WHERE p.location = ?", (f"wallet:{chain}:{w}",)).fetchall():
        if r[2] == "chain_tx":
            try:
                if int(r[3]) > blk:
                    continue
            except (TypeError, ValueError):
                unk += 1
                continue
        key = "native" if r[4] == "native" else str(r[5] or "").lower()
        if not key:
            continue
        sums[key] = sums.get(key, 0) + int(r[1])
        meta.setdefault(key, (r[6], r[7], r[0]))
    return sums, meta, unk


def chain_token_cas(conn, chain: str) -> dict:
    out = {}
    for r in conn.execute("SELECT address, symbol, decimals FROM assets WHERE chain=? AND kind='token' AND address IS NOT NULL", (chain,)).fetchall():
        out[str(r[0]).lower()] = (r[1], r[2])
    return out


def strict_fn(cfg, chain):
    import pricing
    import spamguard
    st = {str(k).lower() for k in (pricing.STABLE_CAS.get(chain) or {})} | {str(k).lower() for k in (pricing.JPY_STABLE_CAS.get(chain) or {})}
    wr = str(((cfg.get("wrapped_native") or {}).get(chain)) or "").lower()

    def f(ca):
        ca = str(ca).lower()
        return ca in st or (wr and ca == wr) or spamguard.is_genuine(chain, ca)
    return f


def rpcs_for(cfg, chain):
    if chain == "bsc":
        b = cfg.get("bsc") or {}
        return [u for u in list(b.get("detail_rpcs") or []) + list(b.get("archive_rpcs") or []) if u]
    cc = (cfg.get("chains") or {}).get(chain) or {}
    if cc.get("rpcs"):
        return list(cc["rpcs"])
    from evm_watch import RpcSynthMixin
    return list(RpcSynthMixin.RPC_DEFAULT.get(chain) or [])


def spot_px(common, chain, ca):
    d = common.read_json(os.path.join(common.STATE_DIR, "spot.json"), {}) if os.path.exists(os.path.join(common.STATE_DIR, "spot.json")) else {}
    try:
        v = float(((d or {}).get("dex_usd") or {}).get(f"{chain}:{ca}") or 0)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def estimate(common, td, cfg, pairs, env, logs_max):
    by = {}
    for c, w in pairs:
        by.setdefault(c, []).append(w)
    lines, tot, sec = [], {}, 0.0
    for c, ws in sorted(by.items()):
        p = td.plan(c, cfg, env)
        n = len(ws)
        est = {}
        for s in p:
            if s == "etherscan" or s == "routescan" or s == "ankr" or s == "alchemy":
                est[s] = n * (2 if s == "alchemy" else 1)
            elif s == "blockscout":
                est[s] = n * 4
        if "logs" in p and not any(s in td.INDEX_SOURCES for s in p):
            span = td.logs_span(c, cfg) or 0
            blk = max([cursor_block(common, c, w) or 0 for w in ws] or [0])
            per = 2 * (-(-blk // span)) if span else 0
            est["logs"] = n * min(per, logs_max) if per else 0
            if per > logs_max:
                est["logs_skip"] = n
        est["rpc"] = n * 5
        est["dex"] = n
        for k, v in est.items():
            tot[k] = tot.get(k, 0) + v
        s9 = sum(v for k, v in est.items() if k != "logs_skip") * 0.8
        sec += s9
        lines.append(f"  {c:<10} 지갑 {n:>3} · 출처 {','.join(x for x in p if x != 'rabby') or '(없음 — 원장 정품만)'} · 옛 보유 {td.old_status(c, cfg, env)} · "
                     f"예상 콜 " + " ".join(f"{k} {v}" for k, v in est.items()) + f" · ≈{s9 / 60:.1f}분")
    return lines, tot, sec


def budgets():
    import bf_engine
    out = {}
    try:
        u, cap = bf_engine.es_budget_used()
        out["etherscan"] = (int(u), int(cap))
    except Exception:
        pass
    try:
        bf_engine._rpc_cfg_ensure()
        st = bf_engine.rpc_day_status()
        for k, name in (("alchemy", "node_alchemy"), ("ankr", "node_ankr")):
            if name in st:
                out[k] = (st[name]["used"], st[name]["budget"], st[name]["unit"])
    except Exception:
        pass
    return out


def _native_px(common, td, cfg, chain, dex_cache):
    wr = str(((cfg.get("wrapped_native") or {}).get(chain)) or "").lower()
    if not wr:
        try:
            import chaincatalog
            wr = str(chaincatalog.native_of(chain)[1] or "").lower()
        except Exception:
            wr = ""
    if not wr:
        import spamguard
        wr = next((ca for ca, sym in (spamguard.GENUINE_CAS.get(chain) or {}).items() if str(sym).upper().startswith("W")), "")
    if not wr:
        return None
    v = spot_px(common, chain, wr)
    if v:
        return v
    if (chain, wr) not in dex_cache:
        try:
            dex_cache[(chain, wr)] = td.dex_check(chain, [wr]).get(wr)
        except Exception:
            dex_cache[(chain, wr)] = None
    g = dex_cache.get((chain, wr))
    return g[2] if g else None


def run_pair(common, td, recon, cfg, conn, chain, w, a, env, dex_cache, explain_on=False):
    blk = cursor_block(common, chain, w)
    res = {"chain": chain, "wallet": w, "block": blk, "rows": [], "table": [], "native": None, "usd": {}, "disc": {}, "stop": None, "err": None}
    if not blk:
        res["err"] = "수집 커서 블록 없음(백필 전) — 건너뜀"
        return res
    cached = None
    if a.use_cache:
        e = td.entry(chain, w)
        need, _why = td.need_refresh(e, td.wallet_sig(conn, chain, w), srcs=td.plan(chain, cfg, env))
        if not need:
            cached = {"cas": e.get("cas") or {}, "meta": e.get("meta") or {}, "ok": e.get("ok") or {}, "fail": e.get("fail") or {}, "calls": {}}
    d = cached or td.discover(chain, w, upto=blk, cfg=cfg, env=env, logs_max_calls=a.logs_max_calls,
                              burst=not td.entry(chain, w).get("at"))
    res["disc"] = {"ok": d["ok"], "fail": d["fail"], "calls": d["calls"], "cache": bool(cached)}
    q9 = [s for s, v in d["fail"].items() if str(v).startswith("quota")]
    if q9:
        res["stop"] = "하루 장부 한도: " + ",".join(q9)
    sums, lmeta, unk = ledger_at(conn, chain, w, blk)
    own = {k for k in sums if k != "native"}
    gen = td.ledger_genuine(conn, chain)
    extra = set(d["cas"]) | gen
    cas_all = chain_token_cas(conn, chain)
    excl = {x[0] for x in (common.NATIVE_MIRROR.get(chain), common.ZK_STACK.get(chain)) if x}
    try:
        bal = recon.fetch_evm_rpc_balances(rpcs_for(cfg, chain), [w], cas_all, discover_url=None, must={}, exclude=excl,
                                           multicall=recon.MULTICALL3_BY_CHAIN.get(chain, recon.MULTICALL3), wallet_cas={w: own},
                                           wallet_extra={w: extra}, block=blk, strict=strict_fn(cfg, chain))
    except Exception as e:
        res["err"] = "잔고 조회 실패: " + common.safe_err(e)[:120]
        return res
    per = (bal.get("per_wallet") or {}).get(w)
    if per is None:
        res["err"] = "보류(정품 칸 관측 불가): " + ",".join(str(x)[:10] for x in (bal.get("_hold") or {}).get(w, [])[:5])
        return res
    q = set((bal.get("_queried") or {}).get(w) or ())
    un = set((bal.get("_unobs") or {}).get(w) or ())
    bmeta = bal.get("_meta") or {}
    nraw = per.get(("native", None))
    res["native"] = {"chain_raw": nraw, "ledger_raw": sums.get("native", 0), "diff_raw": (nraw - sums.get("native", 0)) if nraw is not None else None}
    rows = []
    for ca in sorted((q | own) - {"native"}):
        led = sums.get(ca, 0)
        if ca in un:
            onc = None
        elif ca in q:
            onc = per.get(("token", ca), 0)
        else:
            onc = None
        if onc is None and not led:
            continue
        diff = None if onc is None else onc - led
        if diff == 0:
            continue
        m = d["meta"].get(ca) or {}
        sym = (lmeta.get(ca) or (None,))[0] or (bmeta.get(ca) or (None, None))[0] or m.get("sym") or cas_all.get(ca, (None, None))[0]
        dec = (lmeta.get(ca) or (None, None))[1]
        if dec is None:
            dec = (bmeta.get(ca) or (None, None))[1]
        if dec is None:
            dec = m.get("dec")
        srcs = list(d["cas"].get(ca) or [])
        if ca in own:
            srcs.append("ledger_wallet")
        if ca in gen:
            srcs.append("ledger_genuine")
        rows.append({"ca": ca, "sym": sym, "dec": dec, "onc": onc, "led": led, "diff": diff, "srcs": srcs, "m": m})
    strict = strict_fn(cfg, chain)
    conf = td.confirmed_cas(conn, chain)
    import pricing
    stables = {str(k).lower() for k in (pricing.STABLE_CAS.get(chain) or {})}
    unknown = []
    for r in rows:
        m2 = dict(r["m"], sym=r["sym"] or r["m"].get("sym"))
        ok, why = td.static_credible(chain, r["ca"], r["srcs"], m2, strict, conf)
        r["ok"], r["why"] = ok, why
        if ok is None or (r["ca"] not in stables and r["m"].get("px") is None and spot_px(common, chain, r["ca"]) is None):
            unknown.append(r["ca"])
    need = [x for x in unknown if (chain, x) not in dex_cache]
    if need:
        try:
            got = td.dex_check(chain, need)
        except Exception:
            got = {}
        for x in need:
            dex_cache[(chain, x)] = got.get(x)
    usd = {"diff_cred": 0.0, "diff_spam": 0.0, "led_tok": 0.0, "onc_tok": 0.0, "unpriced": 0}
    for r in rows:
        g = dex_cache.get((chain, r["ca"]))
        if r["ok"] is None:
            r["ok"] = bool(g and g[0])
            import pricing as _px9
            r["why"] = (f"덱스 유동성 ${g[1]:,.0f}" if g and g[0] else ("유동성 부족" if g else
                        ("일시 보류 — 판정 출처 장애" if chain in _px9.DS_CHAIN else "판정 불가 체인(덱스 미지원)")))
        px = (1.0 if r["ca"] in stables else None) or r["m"].get("px") or spot_px(common, chain, r["ca"]) or (g[2] if g else None)
        r["px"] = px
        spam = not r["ok"]
        try:
            amt = (r["diff"] or 0) / (10 ** int(18 if r["dec"] is None else r["dec"]))
        except (TypeError, ValueError, OverflowError):
            amt = 0
        r["usd"] = (amt * px) if px else None
        if r["usd"] is None:
            usd["unpriced"] += 1
        elif spam:
            usd["diff_spam"] += r["usd"]
        else:
            usd["diff_cred"] += r["usd"]
        if r["diff"] is not None:
            res["rows"].append({"chain": chain, "wallet": w, "ca": r["ca"], "symbol": r["sym"], "decimals": r["dec"], "block": blk,
                                "chain_bal_raw": int(r["onc"]), "ledger_raw": int(r["led"]), "diff_raw": int(r["diff"]),
                                "spam": bool(spam), "sources": r["srcs"]})
        res["table"].append((short(w), chain, (r["sym"] or r["ca"][:10]), _fmt(r["onc"], r["dec"]), _fmt(r["led"], r["dec"]),
                             _fmt(r["diff"], r["dec"]) if r["diff"] is not None else "관측 불가",
                             ("스팸 의심 · " if spam else "") + (r["why"] or ""), ",".join(r["srcs"]),
                             (_usd(r["usd"]) if r["usd"] is not None else "—"), spam, -abs(r["usd"] or 0)))
    res["table"] = [t[:9] for t in sorted(res["table"], key=lambda t: (t[9], t[10]))]
    if explain_on:
        nz = {ca: v for (k9, ca), v in per.items() if k9 == "token" and v}
        need2 = [ca for ca in nz if ca not in stables and (chain, ca) not in dex_cache and not (d["meta"].get(ca) or {}).get("px")
                 and spot_px(common, chain, ca) is None]
        if need2:
            try:
                got2 = td.dex_check(chain, need2)
            except Exception:
                got2 = {}
            for x in need2:
                dex_cache[(chain, x)] = got2.get(x)
        onc_all = 0.0
        for ca, v in nz.items():
            m = d["meta"].get(ca) or {}
            g = dex_cache.get((chain, ca))
            ok, _w = td.static_credible(chain, ca, d["cas"].get(ca), dict(m, sym=m.get("sym") or (lmeta.get(ca) or (None,))[0]), strict, conf)
            if ok is False or (ok is None and not (g and g[0])):
                continue
            px = (1.0 if ca in stables else None) or m.get("px") or spot_px(common, chain, ca) or (g[2] if g else None)
            dec = (lmeta.get(ca) or (None, None))[1]
            dec = dec if dec is not None else ((bmeta.get(ca) or (None, None))[1] if (bmeta.get(ca) or (None, None))[1] is not None else m.get("dec"))
            if px and dec is not None:
                onc_all += v / (10 ** int(dec)) * px
        npx = _native_px(common, td, cfg, chain, dex_cache)
        if npx and nraw is not None:
            onc_all += nraw / 1e18 * npx
            usd["nat_diff"] = ((nraw - sums.get("native", 0)) / 1e18) * npx
        usd["onc_all"] = onc_all
    res["usd"] = usd
    res["unk_blocks"] = unk
    return res


def explain(common, cfg, results, targets):
    import rabby
    st = rabby.load_state(os.path.join(common.STATE_DIR, rabby.STATE_NAME))
    res = rabby.chain_resolver(cfg, st)
    botu = (rabby.load_bot_usd(os.path.join(common.STATE_DIR, rabby.BOTUSD_NAME)) or {}) if hasattr(rabby, "load_bot_usd") else {}
    out = []
    for w in targets:
        ent = (st.get("wallets") or {}).get(w) or {}
        if not ent:
            out.append(f"  {short(w)}: Rabby 파일에 없음")
            continue
        prot = {}
        for p in ent.get("protocols") or []:
            v = sum(float(it.get("a") or 0) - float(it.get("d") or 0) for it in (p.get("items") or []))
            prot[str(p.get("chain"))] = prot.get(str(p.get("chain")), 0.0) + v
        bu = botu.get(w) if isinstance(botu, dict) else None
        out.append(f"  {short(w)}: Rabby 합 ${float(ent.get('total') or 0):,.0f}" + (f" · 봇 평가 ${float(bu):,.0f}" if isinstance(bu, (int, float)) else ""))
        for c in sorted(ent.get("chains") or [], key=lambda x: -float(x.get("usd") or 0)):
            rid = str(c.get("id"))
            cu = float(c.get("usd") or 0)
            if cu < 1:
                continue
            bc = res(rid)
            pv = prot.get(rid, 0.0)
            r9 = results.get((bc, w)) if bc else None
            tok = (r9 or {}).get("usd") or {}
            nat = (r9 or {}).get("native") or {}
            line = f"    {rid:<8} Rabby ${cu:,.0f} = 프로토콜·스테이킹 ${pv:,.0f}(토큰 아님 — 표에 따로) + 지갑 토큰 ${cu - pv:,.0f}"
            if not bc:
                line += " · 봇 미추적 체인(Rabby 기준으로 더함)"
            elif r9 is None:
                line += " · 이번 점검 범위 밖"
            elif r9.get("err"):
                line += " · 점검 실패: " + r9["err"][:60]
            else:
                led9 = (tok.get("onc_all") or 0) - (tok.get("diff_cred") or 0) - (tok.get("nat_diff") or 0) if "onc_all" in tok else None
                line += (f" · 토큰으로 설명되는 몫(원장에 빠진 보유) ${tok.get('diff_cred', 0):,.0f}" + (f" · 스팸 의심 차이 ${tok.get('diff_spam', 0):,.0f}(뺌)" if tok.get("diff_spam") else "")
                         + (f" · 네이티브 차이 ${tok['nat_diff']:,.0f}" if tok.get("nat_diff") else (f" · 네이티브 차이 {nat.get('diff_raw')}(값 모름)" if nat.get("diff_raw") else ""))
                         + (f" · 체인 실잔고 평가 ${tok['onc_all']:,.0f} → 봇 원장 ≈${led9:,.0f}" if led9 is not None else "")
                         + (f" · 남는 몫(가격 차이·Rabby 만 아는 토큰) ${(cu - pv) - tok['onc_all']:,.0f}" if "onc_all" in tok else "")
                         + (f" · 값 모름 {tok.get('unpriced')}칸" if tok.get("unpriced") else ""))
            out.append(line)
    return out


def main(argv=None):
    a = _args(argv)
    common = _boot(a)
    import recon
    import token_discovery as td
    cfg = common.load_config()
    env = td._env()
    chains = {x.strip() for x in a.chains.split(",") if x.strip()} or None
    wpre = [x.strip().lower() for x in a.wallets.split(",") if x.strip()] or None
    pairs = pairs_of(cfg, chains, wpre)
    prog = common.read_json(a.progress, {}) if a.progress and os.path.exists(a.progress) else {}
    done = done_keys(prog)
    todo = [p for p in pairs if f"{p[0]}:{p[1]}" not in done]
    if a.only_failed:
        tried = set((prog.get("res") or {}).keys()) | set((prog.get("retry") or {}).keys())
        todo = [p for p in todo if f"{p[0]}:{p[1]}" in tried]
    if a.max_pairs:
        todo = todo[:a.max_pairs]
    lines, tot, sec = estimate(common, td, cfg, todo, env, a.logs_max_calls)
    say = (lambda *x: None) if a.quiet else (lambda *x: print(*x, flush=True))
    say(f"전수 점검(미리보기 · 원장 읽기 전용) — 대상 {len(pairs)}쌍 · 이미 끝남 {len(pairs) - len([p for p in pairs if f'{p[0]}:{p[1]}' not in done])} · 이번 {len(todo)}쌍")
    for ln in lines:
        say(ln)
    say("예상 합계: " + " · ".join(f"{k} {v:,}" for k, v in sorted(tot.items())) + f" · ≈{sec / 60:.0f}분(직렬)")
    bud = budgets()
    over = []
    for k, v in bud.items():
        say(f"  오늘 장부 {k}: {v[0]:,}/{v[1]:,}" + (f" {v[2]}" if len(v) > 2 else ""))
        unit = 20 if k == "alchemy" else (td.ANKR_ADV_CREDITS if k == "ankr" else 1)
        if tot.get(k) and v[0] + tot[k] * unit > v[1]:
            over.append(k)
    if over:
        say("★예상이 남은 하루 몫을 넘음: " + ",".join(over) + " — --max-pairs 로 나누거나 --go(한도 거절 오면 그 자리에서 멈춤)★")
        if not a.go and not a.plan_only:
            return 3
    if a.plan_only:
        return 0
    tg = [x.strip().lower() for x in a.explain.split(",") if x.strip()]
    if not tg:
        try:
            import rabby
            tg = sorted((rabby.load_state(os.path.join(common.STATE_DIR, rabby.GAP_NAME)).get("since") or {}).keys())
        except Exception:
            tg = []
    else:
        allw = sorted({w for _c, w in pairs_of(cfg)})
        tg = [w for w in allw if any(w.startswith(p) for p in tg)]
    tgs = set(tg)
    conn = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=30)
    outf = open(a.out, "a", encoding="utf-8") if a.out else None
    results, dex_cache = {}, {}
    for k, v in (prog.get("res") or {}).items():
        c9, w9 = k.split(":", 1)
        results[(c9, w9)] = v
    rc = 0
    t0 = time.time()
    try:
        for i, (c, w) in enumerate(todo):
            r = run_pair(common, td, recon, cfg, conn, c, w, a, env, dex_cache, explain_on=w in tgs)
            for j in r["rows"]:
                s9 = json.dumps(j, ensure_ascii=False, sort_keys=True)
                if outf:
                    outf.write(s9 + "\n")
                    outf.flush()
                else:
                    print("JSONL\t" + s9, flush=True)
            if r.get("err"):
                say(f"[{i + 1}/{len(todo)}] {c} {short(w)} — {r['err']}")
            else:
                f9 = {s: v for s, v in r["disc"]["fail"].items() if not str(v).startswith(("unsupported", "nokey"))}
                say(f"[{i + 1}/{len(todo)}] {c} {short(w)} 블록 {r['block']} · 발견 " + ",".join(f"{s}={n}" for s, n in r["disc"]["ok"].items())
                    + (" · 실패 " + ",".join(f"{s}({str(v)[:30]})" for s, v in f9.items()) if f9 else "") + (" · 캐시" if r["disc"].get("cache") else "")
                    + f" · 차이 {len(r['table'])}칸" + (f" · 블록 모름 기장 {r['unk_blocks']}" if r.get("unk_blocks") else ""))
                for row in r["table"]:
                    say("   " + " | ".join(str(x) for x in row))
                nat = r.get("native") or {}
                if nat.get("diff_raw"):
                    say(f"   {short(w)} | {c} | (네이티브) | 체인 {_fmt(nat['chain_raw'], 18)} | 원장 {_fmt(nat['ledger_raw'], 18)} | 차이 {_fmt(nat['diff_raw'], 18)}")
            why9 = pair_incomplete(td, r)
            results[(c, w)] = dict({k: r[k] for k in ("usd", "native", "err", "block")}, full=not why9, why=why9)
            if a.progress:
                k9 = f"{c}:{w}"
                prog.setdefault("res", {})[k9] = results[(c, w)]
                if why9:
                    (prog.get("done") or {}).pop(k9, None)
                    prog.setdefault("retry", {})[k9] = why9
                else:
                    prog.setdefault("done", {})[k9] = int(time.time())
                    (prog.get("retry") or {}).pop(k9, None)
                common.atomic_write_json(a.progress, prog)
            if r.get("stop"):
                say(f"★한도로 멈춤({r['stop']}) — 진행 저장됨, 내일(UTC) 다시 같은 명령으로 이어서★")
                rc = 4
                break
    finally:
        if outf:
            outf.close()
        conn.close()
    say(f"끝 — {time.time() - t0:.0f}초")
    if tg:
        say("Rabby 대비 설명(봇이 모르는 보유):")
        for ln in explain(common, cfg, results, tg):
            say(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main())
