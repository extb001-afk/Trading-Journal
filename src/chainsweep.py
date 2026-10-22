"""Sweeps registered wallets across chains for activity."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

import chaincatalog
import config, logs, paths, statefile

log = logging.getLogger("tj-web")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
      " Chrome/128.0.0.0 Safari/537.36")

DEFAULTS = {
    "enabled": True,
    "interval_sec": 86400,
    "min_usd": 1.0,
    "min_units_unpriced": 1.0,
    "pace_sec": 0.3,
    "timeout": 20,
    "ignore": [],
    "extra_chains": {},
}

DOLLAR_NATIVE = {"XDAI", "USDC", "USDT0", "GHO"}


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    for k, v in ((cfg.get("chain_sweep") or {}).items()):
        if k in out:
            out[k] = v
    return out


def chain_list(cfg: dict) -> dict:
    out = {k: list(v) for k, v in chaincatalog.SWEEP_CHAINS.items()}
    for k, v in (settings(cfg).get("extra_chains") or {}).items():
        try:
            nm, cid, sym, rpcs, bmax = v
            out[str(k)] = [str(nm), int(cid), str(sym), [str(u) for u in rpcs], max(1, int(bmax))]
        except (TypeError, ValueError):
            log.warning("chain_sweep.extra_chains.%s 형식 오류 — 무시: %r", k, v)
    for k, cc in (cfg.get("chains") or {}).items():
        if k in out and isinstance(cc, dict) and cc.get("rpcs"):
            out[k][3] = list(dict.fromkeys([str(u) for u in cc["rpcs"]] + out[k][3]))
    off = set(cfg.get("_disabled_chains") or [])
    off.update(k for k, cc in (cfg.get("chains") or {}).items() if isinstance(cc, dict) and not config.chain_enabled(k, cc))
    off -= auto_off_keys()
    return {k: v for k, v in out.items() if k not in off}


def auto_off_keys() -> set:
    try:
        raw = statefile.read_json(paths.CONFIG_PATH, {}) or {}
    except (Exception, SystemExit):   # noqa: BLE001 [fallback]
        return set()
    ch = raw.get("chains") if isinstance(raw, dict) else None
    return {str(k) for k, cc in (ch or {}).items() if isinstance(cc, dict) and not config.chain_enabled(k, cc)
            and isinstance(cc.get("_chainoff"), dict) and cc["_chainoff"].get("auto") is True}


def wallets(cfg: dict):
    addrs, labels, tracked = set(), {}, set()
    auto9 = auto_off_keys()
    off_w9 = [w for w in cfg.get("_disabled_wallets") or [] if isinstance(w, dict) and w.get("chain") in auto9]
    for w in list(cfg.get("wallets") or []) + off_w9:
        t = w.get("type", "evm")
        if t not in ("evm", "bsc_rpc"):
            continue
        a = str(w.get("address") or "").lower()
        if not (a.startswith("0x") and len(a) == 42):
            continue
        addrs.add(a)
        if w.get("label") and a not in labels:
            labels[a] = str(w["label"])
        if w.get("chain") not in auto9:
            tracked.add(("bsc" if t == "bsc_rpc" else str(w.get("chain")), a))
    return sorted(addrs), labels, tracked


def _post(url: str, body, timeout: float):
    import bf_engine
    return bf_engine.rpc_post(url, body, timeout=timeout, ua=UA)


def _host(url) -> str:
    return logs.redact_urls(url) if "://" in str(url) else "(주소 숨김)"


def _batch(url: str, calls: list, bmax: int, timeout: float, pace: float, post=None) -> list:
    post = post or _post
    try:
        import bf_engine
        bmax = max(1, min(int(bmax), bf_engine.gate(url).batch_cap(int(bmax))))
    except Exception:   # noqa: BLE001 [optional]
        pass
    out = []
    for i in range(0, len(calls), bmax):
        part = calls[i:i + bmax]
        if len(part) == 1:
            d = post(url, {"jsonrpc": "2.0", "id": i, "method": part[0][0], "params": part[0][1]}, timeout)
            d = [d] if isinstance(d, dict) else d
        else:
            d = post(url, [{"jsonrpc": "2.0", "id": i + j, "method": m, "params": p} for j, (m, p) in enumerate(part)], timeout)
        if not isinstance(d, list) or len(d) != len(part):
            raise RuntimeError(f"배치 응답 형식 이상: {logs.safe_err(str(d)[:400])[:120]}")
        d = sorted(d, key=lambda x: x.get("id", 0) if isinstance(x, dict) else 0)
        for x in d:
            if not isinstance(x, dict) or "result" not in x or x.get("error"):
                raise RuntimeError(f"rpc 오류: {logs.safe_err(str(x)[:400])[:120]}")
            out.append(x["result"])
        if pace:
            time.sleep(pace)
    return out


def _stable_cas_for(key: str) -> dict:
    try:
        import token_tables
        return {str(ca).lower(): str(sym) for ca, sym in ((token_tables.STABLE_CAS.get(key) or {}).items())}
    except Exception:   # noqa: BLE001 [fallback]
        return {}


def _stable_bal(url: str, cas: dict, cand: list, st: dict, bmax: int, post, res: dict):
    ca9 = sorted(cas)
    calls = [("eth_call", [{"to": ca, "data": "0x70a08231" + "0" * 24 + a[2:]}, "latest"]) for a in cand for ca in ca9]
    r = _batch(url, calls, int(bmax), float(st["timeout"]), float(st["pace_sec"]), post)
    res["calls"] += len(calls)
    res["http"] += -(-len(calls) // int(bmax))
    raw = {}
    for i, a in enumerate(cand):
        for j, ca in enumerate(ca9):
            v = r[i * len(ca9) + j]
            try:
                n9 = int(v, 16) if isinstance(v, str) and v not in ("0x", "") else 0
            except ValueError:
                n9 = 0
            if 0 < n9 < 2 ** 255:
                raw[(a, ca)] = n9
    need = sorted({ca for _a, ca in raw})
    dec = {}
    if need:
        d9 = _batch(url, [("eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"]) for ca in need], int(bmax),
                    float(st["timeout"]), float(st["pace_sec"]), post)
        res["calls"] += len(need)
        res["http"] += -(-len(need) // int(bmax))
        for ca, v in zip(need, d9):
            try:
                n9 = int(v, 16)
            except (TypeError, ValueError):
                raise RuntimeError(f"decimals 응답 이상 {ca[:10]}")
            if not 0 <= n9 <= 36:
                raise RuntimeError(f"decimals 범위 밖 {ca[:10]}: {n9}")
            dec[ca] = n9
    out = {}
    for (a, ca), n9 in raw.items():
        u9 = n9 / 10 ** dec[ca]
        usd9, by9 = out.get(a, (0.0, {}))
        by9[cas[ca]] = round(by9.get(cas[ca], 0.0) + u9, 6)
        out[a] = (usd9 + u9, by9)
    return out


def run_once(cfg: dict, price_fn=None, post=None, now: float = None, gate: dict = None, ledger_pairs=None) -> dict:
    st = settings(cfg)
    now = time.time() if now is None else now
    addrs, labels, tracked = wallets(cfg)
    ign = {str(x).lower() for x in (st.get("ignore") or [])}
    chains = chain_list(cfg)
    gate = gate if isinstance(gate, dict) else {}
    gate.setdefault("version", 1)
    g_ch = gate.setdefault("chains", {})
    g_pr = gate.setdefault("pairs", {})
    res = {"checkedAt": int(now), "wallets": len(addrs), "chains": {}, "findings": [], "autoEnabled": [], "errors": [],
           "calls": 0, "http": 0}
    px_cache = {}

    def usd_of(sym):
        if sym in DOLLAR_NATIVE:
            return 1.0
        if sym not in px_cache:
            try:
                v9 = price_fn(sym) if price_fn else None
                px_cache[sym] = float(v9) if v9 else None
            except Exception:   # noqa: BLE001 [fallback]
                px_cache[sym] = None
        return px_cache[sym]

    def activate(key9, since, src, base=None):
        e9 = g_pr.setdefault(key9, {})
        if not e9.get("active"):
            e9.update(active=True, activatedAt=int(now), since_block=since, src=src)
            if since is not None:
                e9["since_state"] = list(base or [0, "0"])
            e9.setdefault("firstSeen", int(now))

    if not addrs:
        return res
    auto_off9 = auto_off_keys()
    for key, (name, cid, sym, rpcs, bmax) in chains.items():
        calls = [("eth_chainId", []), ("eth_blockNumber", [])] + [("eth_getTransactionCount", [a, "latest"]) for a in addrs] \
            + [("eth_getBalance", [a, "latest"]) for a in addrs]
        got, errs, url_ok = None, [], None
        for url in rpcs:
            try:
                r = _batch(url, calls, int(bmax), float(st["timeout"]), float(st["pace_sec"]), post)
                res["calls"] += len(calls)
                res["http"] += -(-len(calls) // int(bmax))
                if int(r[0], 16) != int(cid):
                    raise RuntimeError(f"chainId {int(r[0], 16)} ≠ {cid}")
                got, url_ok = r, url
                break
            except Exception as e:   # noqa: BLE001 [fallback]
                errs.append(f"{_host(url)}: {logs.safe_err(e)[:100]}")
        if got is None:
            res["chains"][key] = {"ok": False, "err": " | ".join(errs)[:300]}
            res["errors"].append(key)
            continue
        n = len(addrs)
        head = int(got[1], 16)
        prev = g_ch.get(key) or {}
        prev_ok = set(prev.get("addrs") or []) if prev.get("ok") else set()
        per = {}
        checked = []
        px = usd_of(sym)
        cas9 = _stable_cas_for(key) if key not in ign else {}
        cand9 = [a for a in addrs if (key, a) not in tracked and f"{key}:{a}" not in ign] if cas9 else []
        tok9, tok_ok9 = {}, False
        if cand9:
            try:
                tok9, tok_ok9 = _stable_bal(url_ok, cas9, cand9, st, int(bmax), post, res), True
            except Exception as e:   # noqa: BLE001 [isolate]
                res.setdefault("tokErrors", []).append(f"{key}: {_host(url_ok)}: {logs.safe_err(e)[:100]}")
        prev_tok = set(prev.get("taddrs") or []) if prev.get("ok") else set()
        for i, a in enumerate(addrs):
            try:
                nonce, bal = int(got[2 + i], 16), int(got[2 + n + i], 16)
            except (TypeError, ValueError):
                continue
            if nonce < 0 or bal < 0:
                continue
            checked.append(a)
            units = bal / 1e18
            usd = units * px if px is not None else None
            sig = nonce > 0 or (usd is not None and usd >= float(st["min_usd"])) \
                or (usd is None and units >= float(st["min_units_unpriced"]))
            k9 = f"{key}:{a}"
            old9 = g_pr.get(k9) or {}
            t_live = tok_ok9 and a in cand9
            if t_live:
                t_usd, t_by = tok9.get(a, (0.0, {}))
            else:
                t_by = old9.get("stable") if isinstance(old9.get("stable"), dict) else {}
                t_usd = sum(float(v or 0) for v in t_by.values())
            tsig = t_live and t_usd >= float(st["min_usd"])
            t_disp = t_usd if (tsig or (not t_live and t_by)) else 0.0
            base9 = [int(old9.get("nonce") or 0), str(old9.get("bal") or "0")]
            grew9 = False
            if key in auto_off9 and old9.get("active") and "nonce" in old9:
                try:
                    d9 = (bal - int(old9.get("bal") or 0)) / 1e18
                    st_old9 = old9.get("stable") if isinstance(old9.get("stable"), dict) else {}
                    grew9 = nonce > int(old9.get("nonce") or 0) \
                        or (d9 * px >= float(st["min_usd"]) if px is not None else d9 >= float(st["min_units_unpriced"])) \
                        or bool(t_live and t_usd - sum(float(v or 0) for v in st_old9.values()) >= float(st["min_usd"]))
                except (TypeError, ValueError):
                    grew9 = False
            if nonce or bal or tsig or k9 in g_pr:
                per[a] = [nonce, str(bal)]
                e9 = g_pr.setdefault(k9, {})
                u9 = (usd or 0.0) + t_disp if (usd is not None or t_disp) else None
                e9.update(nonce=nonce, bal=str(bal), lastChecked=int(now), usd=round(u9, 2) if u9 is not None else None)
                if grew9:
                    e9["activatedAt"] = int(now)
                if tsig:
                    e9["stable"] = t_by
                elif t_live:
                    e9.pop("stable", None)
            if sig or tsig:
                fresh = a in prev_ok and not old9.get("active") and (not tsig or a in prev_tok)
                activate(k9, int(prev["head"]) - 1 if fresh else None, "sweep", base9 if fresh else None)
        g_ch[key] = {"ok": True, "head": head, "checkedAt": int(now),
                     "addrs": [a for a in checked if not (g_pr.get(f"{key}:{a}") or {}).get("active")]}
        if tok_ok9:
            g_ch[key]["taddrs"] = [a for a in cand9 if a in checked and not (g_pr.get(f"{key}:{a}") or {}).get("active")]
        res["chains"][key] = {"ok": True, "name": name, "sym": sym, "head": head, "active": per}
    for c9, a9 in sorted(ledger_pairs or ()):
        activate(f"{c9}:{str(a9).lower()}", None, "ledger")
    gate["updatedAt"] = int(now)
    dec = {(d["chain"], d["addr"]): d for d in config.gate_decisions(cfg, gate)} if settings(cfg).get("enabled") else {}
    off9 = set(cfg.get("_disabled_chains") or []) | auto_off_keys()
    for d9 in dec.values():
        if d9["chain"] in off9:
            d9.update(ok=False, reason="설정에서 끈 체인", block=None)
    auto_on = bool((cfg.get("chain_sweep") or {}).get("auto_enable") is True)
    for k9, e9 in sorted(g_pr.items()):
        if not e9.get("active") or ":" not in k9:
            continue
        c9, a9 = k9.split(":", 1)
        if a9 not in labels or (c9, a9) in tracked or c9 in ign or k9 in ign:
            continue
        ent = chains.get(c9)
        name = ent[0] if ent else c9
        sym = ent[2] if ent else ""
        units = int(e9.get("bal") or 0) / 1e18
        f = {"chain": c9, "name": name, "wallet": a9, "label": labels.get(a9, ""), "nonce": int(e9.get("nonce") or 0),
             "bal": round(units, 8), "sym": sym, "usd": e9.get("usd"), "since": e9.get("since_block"),
             "stable": e9.get("stable") if isinstance(e9.get("stable"), dict) else None,
             "chainTracked": c9 in (cfg.get("chains") or {}) or (c9 == "bsc" and bool(cfg.get("bsc")))}
        d = dec.get((c9, a9))
        if d and d["ok"] and auto_on:
            f["reason"] = d["reason"]
            res["autoEnabled"].append(f)
        else:
            f["reason"] = (d or {}).get("reason") or ("BSC 는 수동 등록(설정 화면)" if c9 == "bsc" else
                                                      "자동 켜기 꺼짐 — 설정 › 지갑 추가에서 같은 주소에 이 체인을 고르면 등록" if d and d["ok"] else "")
            res["findings"].append(f)
    res["findings"].sort(key=lambda f: (-(f["usd"] or 0), f["chain"], f["wallet"]))
    return res


def refresh_reason(f: dict, speed_rows: dict, auto_on: bool) -> dict:
    rs = str(f.get("reason") or "")
    if not rs.startswith("실측 없음"):
        return f
    row = (speed_rows or {}).get(f.get("chain"))
    if not isinstance(row, dict):
        return f
    try:
        import chaincatalog
        blk, why = chaincatalog.block_for(f.get("chain"), f.get("since") is not None, row)
    except Exception:   # noqa: BLE001 [fallback]
        return f
    if blk is not None:
        why = "속도 측정 끝 · 자동 추적 대상 — 다음 점검(하루 1회) 때 목록에서 빠져요" if auto_on else "속도 측정 끝 · 자동 켜기 꺼짐(설정)"
    return dict(f, reason=why)


def finding_text(f: dict) -> str:
    who = (f.get("label") or "") + f"({f['wallet'][:6]}…{f['wallet'][-4:]})"
    amt = f"${f['usd']:,.2f}" if f.get("usd") is not None else f"{f['bal']:g} {f['sym']}(시세 미상)"
    if isinstance(f.get("stable"), dict) and f["stable"]:
        amt += " (" + " · ".join(f"{k} {float(v):,.2f}" for k, v in sorted(f["stable"].items())) + ")"
    tail = f" · 보낸 거래 {f['nonce']}건" if f.get("nonce") else ""
    kind = "" if not f.get("chainTracked") else " · 체인은 추적 중(이 지갑 미등록)"
    rs = str(f.get("reason") or "")
    if rs.startswith("실측 없음"):
        rs = "체인 속도 측정 전이라 자동 추적 대기"
    why = f" — {rs}" if rs else ""
    return f"{f['name']} {who} {amt}{tail}{kind}{why}"


def view():
    d = statefile.read_json(paths.state("chain_sweep.json"), None) if os.path.exists(paths.state("chain_sweep.json")) else None
    if not isinstance(d, dict):
        return None
    return {"checkedAt": d.get("checkedAt"), "findings": d.get("findings") or [], "autoEnabled": d.get("autoEnabled") or [],
            "errors": d.get("errors") or [], "chains": len(d.get("chains") or {}), "calls": d.get("calls"), "http": d.get("http")}


_SPAN_LADDER = (None, 1_000_000, 100_000, 10_000, 1_000, 100)
_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def measure_speed(key: str, ent, wallet: str, post=None, timeout: float = 25) -> dict:
    post = post or _post
    name, cid, _sym, rpcs, _b = ent
    out = {"name": name, "chainId": int(cid), "blocksPerSec": None, "getLogsSpan": None, "getLogsSec": None,
           "archive": None, "rpc": None, "err": None}

    def one(url, m, p):
        d = post(url, {"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout)
        if not isinstance(d, dict) or d.get("error") or "result" not in d:
            raise RuntimeError(logs.redact_secret_text(str(d.get("error") if isinstance(d, dict) else d))[:120])
        return d["result"]
    for url in rpcs:
        try:
            head = int(one(url, "eth_blockNumber", []), 16)
            back = min(200_000, max(1, head // 2))
            t1 = int(one(url, "eth_getBlockByNumber", [hex(head), False])["timestamp"], 16)
            t0 = int(one(url, "eth_getBlockByNumber", [hex(head - back), False])["timestamp"], 16)
            out["blocksPerSec"] = round(back / max(1, t1 - t0), 3)
            out["rpc"] = _host(url)
            pad = "0x" + wallet[2:].rjust(64, "0")
            for sp in _SPAN_LADDER:
                frm = 0 if sp is None else max(0, head - sp)
                t9 = time.time()
                try:
                    r = one(url, "eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(head), "topics": [_TRANSFER, None, pad]}])
                    if isinstance(r, list):
                        out["getLogsSpan"] = head - frm
                        out["getLogsSec"] = round(time.time() - t9, 2)
                        break
                except Exception:   # noqa: BLE001 [optional]
                    pass
                time.sleep(0.3)
            try:
                one(url, "eth_getBalance", [wallet, hex(max(1, head - 100_000))])
                out["archive"] = True
            except Exception:   # noqa: BLE001 [fallback]
                out["archive"] = False
            return out
        except Exception as e:   # noqa: BLE001 [fallback]
            out["err"] = f"{_host(url)}: {logs.safe_err(e)[:100]}"
    return out


def speed_view(cfg: dict, meas: dict, n_wallets: dict = None, auto_window_calls: int = 3000) -> dict:
    months = float(cfg.get("backfill_months") or 5)
    chains = cfg.get("chains") or {}
    rows = {}
    for k, m in meas.items():
        cc = chains.get(k) if isinstance(chains.get(k), dict) else None
        disc = None if cc is None else config.chain_discovery(k, cc) if not cc.get("blockscout") or cc.get("discovery") == "rpc" \
            else "blockscout"
        r = dict(m, discovery=disc, tracked=cc is not None)
        bps, span = m.get("blocksPerSec"), m.get("getLogsSpan")
        nw = max(1, int((n_wallets or {}).get(k) or 1))
        if disc == "blockscout":
            r.update(callsPerMonth=None, callsPerWalletMonth=3.0, estSecPerMonth=None, windowCalls=None, autoOk=True)
        elif bps and span:
            per = int(-(-bps * 86400 * 30 // span)) * 2
            r.update(callsPerMonth=per, callsPerWalletMonth=round(per / nw, 1), estSecPerMonth=round(per / 2.0, 1),
                     windowCalls=int(per * months), autoOk=int(per * months) <= int(auto_window_calls))
        else:
            r.update(callsPerMonth=None, callsPerWalletMonth=None, estSecPerMonth=None, windowCalls=None, autoOk=False)
        rows[k] = r
    return {"version": 1, "measuredAt": int(time.time()), "windowMonths": months, "chains": rows}


SPEED_EVERY = 7 * 86400


def speed_tick(cfg: dict, gate: dict, now: float = None, post=None, force: bool = False) -> dict:
    now = time.time() if now is None else now
    old = statefile.read_json(paths.BACKFILL_SPEED_PATH, {}) if os.path.exists(paths.BACKFILL_SPEED_PATH) else {}
    lst = chain_list(cfg)
    act = {}
    for k9, e9 in ((gate or {}).get("pairs") or {}).items():
        if isinstance(e9, dict) and e9.get("active") and ":" in k9:
            c9, a9 = k9.split(":", 1)
            act.setdefault(c9, a9)
    missing = missing_speed(cfg, gate, old, lst=lst, act=act)
    only_missing = False
    if not force and old.get("measuredAt") and now - float(old["measuredAt"]) < SPEED_EVERY:
        if not missing:
            return old
        only_missing = True
    addrs, _labels, _tr = wallets(cfg)
    if not addrs:
        return old
    want = missing if only_missing else [c for c in lst if c != "bsc" and (c in (cfg.get("chains") or {}) or c in act)]
    meas = {}
    for c in want:
        meas[c] = measure_speed(c, lst[c], act.get(c) or addrs[0], post=post)
    nw = {}
    for w in cfg.get("wallets") or []:
        if w.get("type", "evm") == "evm":
            nw[w["chain"]] = nw.get(w["chain"], 0) + 1
    doc = speed_view(cfg, meas, nw)
    rows = dict((old.get("chains") or {}))
    for c9, row9 in doc["chains"].items():
        prev9 = rows.get(c9) or {}
        if prev9.get("getLogsSpan") and prev9.get("blocksPerSec") and not (row9.get("getLogsSpan") and row9.get("blocksPerSec")):
            rows[c9] = dict(prev9, lastAttempt={k: row9.get(k) for k in ("getLogsSpan", "blocksPerSec", "archive", "err")},
                            lastAttemptAt=int(now))
        else:
            rows[c9] = row9
    doc["chains"] = rows
    if only_missing:
        doc["measuredAt"] = old.get("measuredAt") or doc["measuredAt"]
    statefile.atomic_write_json(paths.BACKFILL_SPEED_PATH, doc)
    log.info("체인 백필 속도 실측%s: %d체인 → %s", "(실측 없던 활동 체인만)" if only_missing else "", len(meas), paths.BACKFILL_SPEED_PATH)
    return doc


def missing_speed(cfg: dict, gate: dict, old: dict = None, lst: dict = None, act: dict = None) -> list:
    if old is None:
        old = statefile.read_json(paths.BACKFILL_SPEED_PATH, {}) if os.path.exists(paths.BACKFILL_SPEED_PATH) else {}
    lst = chain_list(cfg) if lst is None else lst
    if act is None:
        act = {}
        for k9, e9 in ((gate or {}).get("pairs") or {}).items():
            if isinstance(e9, dict) and e9.get("active") and ":" in k9:
                act.setdefault(k9.split(":", 1)[0], k9.split(":", 1)[1])
    rows = (old or {}).get("chains") or {}
    return [c for c in lst if c != "bsc" and c in act and c not in rows]
