"""Periodic on-chain balance reconciliation (alert only, ledger is never modified)."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import common
import netpace
import pricing
import recon

log = logging.getLogger("tj-web")
KST = timezone(timedelta(hours=9))
STATUS_PATH = os.path.join(common.STATE_DIR, "onchain_check.json")

DEFAULTS = {
    "enabled": True,
    "interval_sec": 3600,
    "min_usd": 1000.0,
    "diff_abs_usd": 500.0,
    "diff_pct": 0.02,
    "max_calls": 400,
    "confirm_sec": 1800,
    "pace_sec": 0.2,
    "sol": True,
    "sol_rpcs": None,
    "sol_max_calls": 80,
    "upbit": True,
}
UPBIT_KEY = ("upbit", "exchange:upbit")
_EX_TERMINAL = ("ACCEPTED", "DONE", "CANCELLED", "CANCELED", "REJECTED", "FAILED", "REFUNDED")


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    for k, v in ((cfg.get("balance_check") or {}).items()):
        if k in out:
            out[k] = v
    return out


def _rpcs_for(cfg: dict, chain: str) -> list:
    if chain == "bsc":
        return list((cfg.get("bsc") or {}).get("detail_rpcs") or [])
    cc = (cfg.get("chains") or {}).get(chain) or {}
    if cc.get("rpcs"):
        return list(cc["rpcs"])
    try:
        from evm_watch import RpcSynthMixin
        return list(RpcSynthMixin.RPC_DEFAULT.get(chain) or [])
    except Exception:
        return []


class _Caller:

    def __init__(self, cfg: dict, max_calls: int, pace: float):
        self.cfg = cfg
        self.max_calls = int(max_calls)
        self.pace = float(pace)
        self.calls = 0
        self.cool = {}

    def capped(self) -> bool:
        return self.calls >= self.max_calls

    def rpc(self, chain: str, method: str, params: list):
        urls = _rpcs_for(self.cfg, chain)
        if not urls:
            raise RuntimeError(f"{chain} RPC 미구성")
        now = time.time()
        order = [u for u in urls if self.cool.get(u, 0) <= now] or urls
        last = None
        for u in order:
            if self.capped():
                raise RuntimeError("호출 상한")
            self.calls += 1
            try:
                r = recon._rpc(u, method, params, timeout=15)
                time.sleep(self.pace)
                return r
            except Exception as e:
                last = e
                m = str(e)
                ratelike = "429" in m or "Too Many" in m or "rate" in m.lower() or "-32016" in m
                self.cool[u] = time.time() + (120 if ratelike else 30)
                time.sleep(self.pace)
        raise last if last else RuntimeError("rpc 실패")


SOL_TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                      "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")


def _sol_rpcs(cfg: dict, st: dict) -> list:
    if st.get("sol_rpcs"):
        urls = list(st["sol_rpcs"])
    else:
        sol = cfg.get("sol") or {}
        urls = list(sol.get("rpc_fallbacks") or [])
        if sol.get("rpc_fallback"):
            urls.append(sol["rpc_fallback"])
        if str(sol.get("rpc") or "").startswith("http"):
            urls.append(sol["rpc"])
    out = []
    for u in urls:
        u = str(u or "").strip()
        if u.startswith("http") and "api-key" not in u and u not in out:
            out.append(u)
    return sorted(out, key=lambda u: 1 if "publicnode" in u else 0)


def _sol_call(caller, urls: list, method: str, params: list):
    if not urls:
        raise RuntimeError("솔라나 RPC 미구성")
    now = time.time()
    order = [u for u in urls if caller.cool.get(u, 0) <= now] or urls
    last = None
    for u in order:
        if caller.capped():
            raise RuntimeError("호출 상한")
        caller.calls += 1
        try:
            netpace.wait(u)
            return recon._rpc(u, method, params, timeout=20)
        except Exception as e:
            last = e
            netpace.note_error(u, e)
            m = str(e)
            ratelike = "429" in m or "Too Many" in m or "rate" in m.lower()
            caller.cool[u] = time.time() + (120 if ratelike else 30)
    raise last if last else RuntimeError("sol rpc 실패")


def _sol_onchain(caller, urls: list, owner: str) -> dict:
    out = {}
    lam = _sol_call(caller, urls, "getBalance", [owner])
    if not isinstance(lam, dict) or lam.get("value") is None:
        raise RuntimeError("getBalance value 누락")
    out[None] = (int(lam["value"]), 9)
    for prog in SOL_TOKEN_PROGRAMS:
        res = _sol_call(caller, urls, "getTokenAccountsByOwner", [owner, {"programId": prog}, {"encoding": "jsonParsed"}])
        if not isinstance(res, dict) or not isinstance(res.get("value"), list):
            raise RuntimeError("getTokenAccountsByOwner value 형식 오류")
        for it in res["value"]:
            info = ((((it or {}).get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
            mint = info.get("mint")
            ta = info.get("tokenAmount") or {}
            if not mint or ta.get("decimals") is None:
                raise RuntimeError("token account mint/decimals 누락")
            try:
                v = int(ta.get("amount"))
            except (TypeError, ValueError):
                raise RuntimeError(f"token account amount 파싱 실패 {str(mint)[:10]}") from None
            prev = out.get(mint, (0, int(ta["decimals"])))
            out[mint] = (prev[0] + v, int(ta["decimals"]))
    return out


def _sol_wallets(cfg: dict) -> list:
    out = []
    for w in cfg.get("wallets") or []:
        if isinstance(w, dict) and w.get("type") == "sol" and w.get("address") and w["address"] not in out:
            out.append(str(w["address"]))
    return out


def _registered_pairs(cfg: dict) -> list:
    out = []
    for w in cfg.get("wallets") or []:
        t = w.get("type", "evm")
        if t == "evm" or t == "bsc_rpc":
            ch = "bsc" if t == "bsc_rpc" else w.get("chain")
            a = str(w.get("address") or "").lower()
            if ch and a.startswith("0x") and (ch, a) not in out:
                out.append((ch, a))
    return out


def _ledger(conn, pairs: list) -> dict:
    want = {f"wallet:{c}:{w}": (c, w) for c, w in pairs}
    out = {}
    for r in conn.execute(
            "SELECT p.location, p.asset_id, p.qty_base, a.kind, a.address, a.symbol, a.decimals, a.group_id"
            " FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.location LIKE 'wallet:%'"):
        cw = want.get(r["location"])
        if not cw:
            continue
        ent = out.setdefault(cw, {}).setdefault(
            r["asset_id"], [0, r["kind"], r["address"], r["symbol"], r["decimals"], r["group_id"]])
        ent[0] += int(r["qty_base"])
    return out


def _anchored_pairs(conn) -> set:
    out = set()
    try:
        done = {r[0][len("recon_done_"):] for r in conn.execute("SELECT k FROM meta WHERE k LIKE 'recon_done\\_%' ESCAPE '\\'")}
        for oid, pl in conn.execute("SELECT obs_id, payload FROM raw_observations WHERE obs_id LIKE 'recon:%'"):
            parts = str(oid).split(":")
            if len(parts) != 2 or parts[1] not in done:
                continue
            try:
                d = json.loads(pl) if pl else {}
            except (TypeError, ValueError):
                continue
            if isinstance(d, dict):
                out |= {(parts[1], str(w).lower()) for w, v in d.items() if isinstance(v, dict)}
        for (k,) in conn.execute("SELECT k FROM meta WHERE k LIKE 'wrecon_done:%'"):
            parts = str(k).split(":", 2)
            if len(parts) == 3:
                out.add((parts[1], parts[2].lower()))
    except Exception as e:
        log.warning("잔고 대조: 기초잔고 표식 읽기 실패(전부 대조): %s", e)
        return None
    return out


def _upbit_partial(o: dict):
    from decimal import InvalidOperation
    market = str(o.get("market") or "")
    if "-" not in market:
        return None
    quote, base = (s.upper() for s in market.split("-", 1))
    try:
        vol = Decimal(str(o.get("executed_volume") or "0"))
        funds = Decimal(str(o.get("executed_funds") if o.get("executed_funds") not in (None, "") else "0"))
        fee = Decimal(str(o.get("paid_fee") if o.get("paid_fee") not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    side = str(o.get("side") or "").lower()
    if side not in ("bid", "ask") or not (vol.is_finite() and funds.is_finite() and fee.is_finite()) or vol < 0:
        return None
    if vol == 0:
        return {}
    return {base: vol, quote: -(funds + fee)} if side == "bid" else {base: -vol, quote: funds - fee}


def _upbit_found(cfg: dict, conn, live_px: dict, st: dict, errors: list):
    try:
        if not conn.execute("SELECT 1 FROM meta WHERE k='recon_done_upbit'").fetchone():
            return None
    except Exception:
        return None
    bal = common.read_json(os.path.join(common.STATE_DIR, "upbit_balances.json"), {}) or {}
    if not isinstance(bal, dict) or time.time() - float(bal.get("ts") or 0) > common.upbit_fresh_sec(cfg):
        return None
    try:
        sync = common.read_json(os.path.join(common.STATE_DIR, "upbit_sync.json"), {})
        ost = common.read_json(os.path.join(common.STATE_DIR, "upbit_orders_state.json"), {})
        snap_ts = float(bal.get("ts") or 0)
        if not isinstance(sync, dict) or not isinstance(ost, dict) or not ost.get("complete"):
            return None
        if float(sync.get("last_ok") or 0) < snap_ts:
            return None
        le9 = sync.get("last_err")
        if isinstance(le9, dict) and float(le9.get("ts") or 0) >= snap_ts:
            return None
    except (Exception, SystemExit):
        return None
    oo = bal.get("open_orders")
    if not isinstance(oo, list) or not isinstance(bal.get("accounts"), list):
        return None
    bts = int(bal.get("ts") or 0)
    actual = {}
    for a in bal.get("accounts") or []:
        if not isinstance(a, dict):
            errors.append("upbit: 잔고 행 형식 오류")
            return None
        cur = str(a.get("currency") or "").strip().upper()
        if not cur or cur == "KRW":
            continue
        try:
            actual[cur] = Decimal(str(a["balance"])) + Decimal(str(a["locked"]))
        except Exception:
            errors.append(f"upbit: {cur} 잔고 파싱 실패")
            return None
    oo_uuids = set()
    for o9 in oo:
        p9 = _upbit_partial(o9) if isinstance(o9, dict) else None
        if p9 is None or not o9.get("uuid"):
            errors.append("upbit: 미체결 주문 형식 오류")
            return None
        oo_uuids.add(str(o9["uuid"]))
        for s9, dq in p9.items():
            if s9 in actual:
                actual[s9] -= dq
    skip = set()
    try:
        for kind9, pl9, at9 in conn.execute(
                "SELECT r.kind, r.payload, r.observed_at FROM raw_ex r JOIN (SELECT exchange, kind, uuid, max(revision) AS revision FROM raw_ex"
                " WHERE exchange='upbit' AND kind IN ('deposit','withdraw') GROUP BY exchange, kind, uuid) x"
                " ON x.exchange=r.exchange AND x.kind=r.kind AND x.uuid=r.uuid AND x.revision=r.revision"):
            try:
                p9 = json.loads(pl9)
            except (TypeError, ValueError):
                continue
            s9 = str(p9.get("state") or "").upper()
            if (s9 and s9 not in _EX_TERMINAL) or int(at9 or 0) >= bts - 5:
                skip.add(str(p9.get("currency") or "").upper())
        in9 = (" OR uuid IN (%s)" % ",".join("?" * len(oo_uuids))) if oo_uuids else ""
        for (pl9,) in conn.execute("SELECT payload FROM raw_ex WHERE exchange='upbit' AND kind='order' AND (observed_at >= ?" + in9 + ")",
                                   (bts - 5, *sorted(oo_uuids))):
            try:
                mk9 = str(json.loads(pl9).get("market") or "")
            except (TypeError, ValueError):
                mk9 = ""
            for s9 in (mk9.split("-", 1) if "-" in mk9 else []):
                skip.add(s9.upper())
    except Exception as e:
        errors.append(f"upbit: 진행 중 입출금·주문 확인 실패 {common.safe_err(e)[:60]}")
        return None
    ledger = {}
    for r in conn.execute("SELECT a.symbol, a.decimals, a.group_id, p.qty_base FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                          " WHERE p.location = 'exchange:upbit'"):
        sym = str(r["symbol"] or "").upper()
        if not sym or sym == "KRW":
            continue
        ent = ledger.setdefault(sym, [Decimal(0), None])
        ent[0] += Decimal(int(r["qty_base"])) / (Decimal(10) ** int(8 if r["decimals"] is None else r["decimals"]))
        if ent[1] is None and r["group_id"] is not None:
            ent[1] = r["group_id"]
    found, n = [], 0
    for sym, (lq, gid) in ledger.items():
        if sym in skip:
            continue
        n += 1
        px = float(live_px.get(gid) or 0) if gid is not None else 0.0
        if px <= 0:
            continue
        oq = actual.get(sym, Decimal(0))
        pxd = Decimal(str(px))
        diff_usd = abs(oq - lq) * pxd
        thr = max(Decimal(str(st["diff_abs_usd"])), Decimal(str(st["diff_pct"])) * max(abs(lq), abs(oq)) * pxd)
        if diff_usd >= thr:
            found.append({"key": f"upbit:exchange:upbit:{sym}", "wallet": UPBIT_KEY[1], "chain": UPBIT_KEY[0], "sym": sym, "ca": None,
                          "ledger": float(lq), "onchain": float(oq), "diffUsd": round(float(diff_usd), 2)})
    return found, n


def run_once(cfg: dict, conn, live_px: dict, skip_gids: set, prev: dict) -> dict:
    st = settings(cfg)
    t0 = time.time()
    try:
        recon_on = not cfg.get("backfill_full_history") and float(cfg.get("backfill_months") or 0) > 0
    except (TypeError, ValueError):
        recon_on = False
    anch = _anchored_pairs(conn) if recon_on else None
    pairs_all = _registered_pairs(cfg)
    fresh = [] if anch is None else [p9 for p9 in pairs_all if p9 not in anch]
    pairs = [p9 for p9 in pairs_all if p9 not in set(fresh)]
    led = _ledger(conn, pairs)
    caller = _Caller(cfg, st["max_calls"], st["pace_sec"])
    checked = 0
    errors = []
    found = []
    capped = False
    rr0 = int((prev or {}).get("rrNext") or 0) % len(pairs) if pairs else 0
    order9 = pairs[rr0:] + pairs[:rr0]
    done_pairs = set()
    failed_keys = set()
    rr_next = 0
    for i9, (ch, w) in enumerate(order9):
        if caller.capped():
            capped = True
            rr_next = (rr0 + i9) % len(pairs)
            break
        rows = led.get((ch, w), {})
        items = []
        native_aid = None
        for aid, (qb, kind, addr, sym, dec, gid) in rows.items():
            if kind == "native":
                native_aid = aid
        if native_aid is not None:
            qb, _k, _a, sym, dec, gid = rows[native_aid]
            items.append(("native", None, qb, 18 if dec is None else int(dec),
                          float(live_px.get(gid) or 0), sym or cfg.get("native_symbol", {}).get(ch) or ch.upper(), gid))
        else:
            items.append(("native", None, 0, 18, 0.0,
                          (cfg.get("native_symbol") or {}).get(ch) or ch.upper(), None))
        stables = {ca.lower(): s for ca, s in (pricing.STABLE_CAS.get(ch) or {}).items()}
        seen_ca = set()
        for aid, (qb, kind, addr, sym, dec, gid) in rows.items():
            if kind != "token" or not addr:
                continue
            ca = addr.lower()
            dec = 18 if dec is None else int(dec)
            if ca in stables:
                items.append(("token", ca, qb, dec, 1.0, stables[ca], gid))
                seen_ca.add(ca)
                continue
            if gid in skip_gids:
                continue
            px = float(live_px.get(gid) or 0)
            if px <= 0:
                continue
            if abs(Decimal(qb) / (Decimal(10) ** dec)) * Decimal(str(px)) < Decimal(str(st["min_usd"])):
                continue
            items.append(("token", ca, qb, dec, px, sym or ca[:10], gid))
            seen_ca.add(ca)
        for ca, s in stables.items():
            if ca not in seen_ca:
                items.append(("token", ca, 0, None, 1.0, s, None))
        for kind, ca, qb, dec, px, sym, gid in items:
            if caller.capped():
                capped = True
                break
            try:
                if kind == "native":
                    raw = int(caller.rpc(ch, "eth_getBalance", [w, "latest"]), 16)
                else:
                    data = "0x70a08231" + w.replace("0x", "").rjust(64, "0")
                    r = caller.rpc(ch, "eth_call", [{"to": ca, "data": data}, "latest"])
                    raw = int(r, 16) if r and r != "0x" else 0
                    if dec is None:
                        if raw == 0:
                            checked += 1
                            continue
                        r2 = caller.rpc(ch, "eth_call", [{"to": ca, "data": "0x313ce567"}, "latest"])
                        dec = int(r2, 16)
            except Exception as e:
                failed_keys.add(f"{ch}:{w}:{ca or 'native'}")
                if len(errors) < 20:
                    errors.append(f"{ch}:{w[:8]}:{sym}: {common.safe_err(e)[:80]}")
                continue
            checked += 1
            if px <= 0:
                continue
            scale = Decimal(10) ** int(dec)
            lq = Decimal(qb) / scale
            oq = Decimal(raw) / scale
            pxd = Decimal(str(px))
            diff_usd = abs(oq - lq) * pxd
            big = max(abs(lq), abs(oq)) * pxd
            thr = max(Decimal(str(st["diff_abs_usd"])), Decimal(str(st["diff_pct"])) * big)
            if diff_usd >= thr:
                found.append({"key": f"{ch}:{w}:{ca or 'native'}", "wallet": w, "chain": ch, "sym": sym,
                              "ca": ca, "ledger": float(lq), "onchain": float(oq),
                              "diffUsd": round(float(diff_usd), 2)})
        if capped:
            rr_next = (rr0 + i9) % len(pairs)
            break
        done_pairs.add((ch, w))
    sol_ws = _sol_wallets(cfg) if st.get("sol") else []
    if anch is not None:
        fresh += [("sol", w9) for w9 in sol_ws if ("sol", w9.lower()) not in anch]
        sol_ws = [w9 for w9 in sol_ws if ("sol", w9.lower()) in anch]
    sol_urls = _sol_rpcs(cfg, st) if sol_ws else []
    if sol_ws and not sol_urls:
        errors.append("sol: 대조용 공개 RPC 미구성(balance_check.sol_rpcs 또는 sol.rpc_fallbacks)")
    led_sol = _ledger(conn, [("sol", w) for w in sol_ws]) if sol_urls else {}
    sol_caller = _Caller(cfg, st.get("sol_max_calls") or 80, st["pace_sec"])
    stable_mints = dict(pricing.STABLE_MINTS)
    for w in (sol_ws if sol_urls else []):
        if sol_caller.capped():
            capped = True
            break
        try:
            onc = _sol_onchain(sol_caller, sol_urls, w)
        except Exception as e:
            if len(errors) < 20:
                errors.append(f"sol:{w[:8]}: {common.safe_err(e)[:80]}")
            continue
        rows = led_sol.get(("sol", w), {})
        items = []
        seen_mint = set()
        nat = [(aid, v) for aid, v in rows.items() if v[1] == "native"]
        if nat:
            qb, _k, _a, sym, dec, gid = nat[0][1]
            items.append((None, qb, onc.get(None, (0, 9))[0], 9 if dec is None else int(dec), float(live_px.get(gid) or 0), sym or "SOL"))
        else:
            items.append((None, 0, onc.get(None, (0, 9))[0], 9, 0.0, "SOL"))
        for aid, (qb, kind, addr, sym, dec, gid) in rows.items():
            if kind != "token" or not addr:
                continue
            dec = int(onc.get(addr, (0, dec if dec is not None else 9))[1]) if dec is None else int(dec)
            if addr in stable_mints:
                items.append((addr, qb, onc.get(addr, (0, dec))[0], dec, 1.0, stable_mints[addr]))
                seen_mint.add(addr)
                continue
            if gid in skip_gids:
                continue
            px = float(live_px.get(gid) or 0)
            if px <= 0 or abs(Decimal(qb) / (Decimal(10) ** dec)) * Decimal(str(px)) < Decimal(str(st["min_usd"])):
                continue
            items.append((addr, qb, onc.get(addr, (0, dec))[0], dec, px, sym or addr[:8]))
            seen_mint.add(addr)
        for mint, sym in stable_mints.items():
            if mint not in seen_mint and onc.get(mint, (0, 0))[0]:
                items.append((mint, 0, onc[mint][0], onc[mint][1], 1.0, sym))
        done_pairs.add(("sol", w))
        for ca, qb, raw, dec, px, sym in items:
            checked += 1
            if px <= 0:
                continue
            scale = Decimal(10) ** int(dec)
            lq = Decimal(qb) / scale
            oq = Decimal(raw) / scale
            pxd = Decimal(str(px))
            diff_usd = abs(oq - lq) * pxd
            big = max(abs(lq), abs(oq)) * pxd
            thr = max(Decimal(str(st["diff_abs_usd"])), Decimal(str(st["diff_pct"])) * big)
            if diff_usd >= thr:
                found.append({"key": f"sol:{w}:{ca or 'native'}", "wallet": w, "chain": "sol", "sym": sym,
                              "ca": ca, "ledger": float(lq), "onchain": float(oq),
                              "diffUsd": round(float(diff_usd), 2)})
    stake_n = 0
    try:
        sd = common.read_json(os.path.join(common.STATE_DIR, "sol_stake.json"), {}) or {}
    except (Exception, SystemExit):
        sd = {}
    if st.get("sol") and sd and time.time() - float(sd.get("ts") or 0) < 3 * 3600:
        led_st = {}
        for r in conn.execute("SELECT p.location, p.qty_base, a.group_id FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                              " WHERE p.location LIKE 'wallet:sol:%:stake:%' AND a.kind='native'"):
            ent = led_st.setdefault(r["location"], [0, r["group_id"]])
            ent[0] += int(r["qty_base"])
        for s9, v9 in (sd.get("accounts") or {}).items():
            if not isinstance(v9, dict) or not v9.get("ledger_ready") or not v9.get("w"):
                continue
            loc9 = f"wallet:sol:{v9['w']}:stake:{s9}"
            qb9, gid9 = led_st.get(loc9, [0, None])
            px9 = float(live_px.get(gid9) or 0) if gid9 is not None else 0.0
            if px9 <= 0:
                px9 = max((float(live_px.get(g9[1]) or 0) for g9 in led_st.values()), default=0.0)
            checked += 1
            stake_n += 1
            if px9 <= 0:
                continue
            lq, oq = Decimal(qb9) / Decimal(10 ** 9), Decimal(int(v9.get("lamports") or 0)) / Decimal(10 ** 9)
            pxd = Decimal(str(px9))
            diff_usd = abs(oq - lq) * pxd
            thr = max(Decimal(str(st["diff_abs_usd"])), Decimal(str(st["diff_pct"])) * max(abs(lq), abs(oq)) * pxd)
            if diff_usd >= thr:
                found.append({"key": f"sol:{s9}:stake", "wallet": s9, "chain": "sol", "sym": "SOL(스테이킹)",
                              "ca": None, "ledger": float(lq), "onchain": float(oq), "diffUsd": round(float(diff_usd), 2)})
    up_n = 0
    if st.get("upbit"):
        r9 = _upbit_found(cfg, conn, live_px, st, errors)
        if r9 is not None:
            found += r9[0]
            up_n = r9[1]
            checked += r9[1]
            done_pairs.add(UPBIT_KEY)
    now = int(time.time())
    prev_pending = dict((prev or {}).get("pending") or {})
    pending = {}
    for m in found:
        fs = int(prev_pending.get(m["key"]) or now)
        pending[m["key"]] = fs
        m["firstSeen"] = fs
        m["confirmed"] = (now - fs) >= int(st["confirm_sec"])
    if UPBIT_KEY not in done_pairs:
        for k, v in prev_pending.items():
            if str(k).startswith("upbit:") and now - int(v) < 3 * 86400:
                pending.setdefault(k, v)
    if capped or errors:
        done_keys = {m["key"] for m in found}
        for k, v in prev_pending.items():
            if k not in done_keys and now - int(v) < 3 * 86400:
                pending.setdefault(k, v)
    found_keys = {m["key"] for m in found}
    for m in found:
        m["seenAt"] = now
    evm_pairs = set(pairs)
    for m in (prev or {}).get("mismatches") or []:
        k9 = str(m.get("key") or "")
        pr9 = (m.get("chain"), m.get("wallet"))
        if (k9 and k9 not in found_keys and not k9.endswith(":stake") and k9 in pending
                and (pr9 not in done_pairs or k9 in failed_keys)):
            m9 = dict(m, carried=True, carriedN=int(m.get("carriedN") or 0) + 1)
            m9.pop("ledgerFixed", None)
            _recheck_carried(m9, led if pr9 in evm_pairs else (led_sol if sol_urls and pr9[0] == "sol" else None), st)
            found.append(m9)
    if fresh:
        fr9 = {(c9, str(w9).lower()) for c9, w9 in fresh}
        found = [m for m in found if (m.get("chain"), str(m.get("wallet") or "").lower()) not in fr9]
        pending = {k: v for k, v in pending.items()
                   if (str(k).split(":", 2)[0], str(k).split(":", 2)[1].lower() if k.count(":") >= 2 else "") not in fr9}
    unchecked = len([p9 for p9 in pairs if p9 not in done_pairs]) + len([w9 for w9 in sol_ws if ("sol", w9) not in done_pairs])
    stake_n += up_n
    return {"checkedAt": now, "durationSec": round(time.time() - t0, 1), "calls": caller.calls + sol_caller.calls if sol_ws else caller.calls,
            "capped": capped, "checked": checked, "pairs": len(pairs) + len(sol_ws) + stake_n, "errors": errors,
            "mismatches": found, "pending": pending, "rrNext": rr_next, "unchecked": unchecked,
            "fresh": [f"{c9}:{w9}" for c9, w9 in fresh],
            "alerted": dict((prev or {}).get("alerted") or {})}


def _recheck_carried(m: dict, led, st: dict) -> None:
    measured = m.setdefault("_measured", {k: m.get(k) for k in ("ledger", "onchain", "diffUsd", "confirmed")})
    m.update(measured)
    m.pop("ledgerFixed", None)
    if led is None:
        return
    try:
        seen9 = m.get("seenAt") or m.get("firstSeen")
        if seen9 is not None and time.time() - float(seen9) >= 86400:
            return
        ch, w, ca = m.get("chain"), m.get("wallet"), m.get("ca")
        rows = led.get((ch, w)) or {}
        hit = None
        for aid, (qb, kind, addr, sym, dec, gid) in rows.items():
            if (ca is None and kind == "native") or (ca and kind == "token" and addr
                                                     and (addr == ca if ch == "sol" else str(addr).lower() == str(ca).lower())):
                hit = (qb, dec)
                break
        if hit is None:
            lq = Decimal(0)
        else:
            if ch == "sol" and ca and hit[1] is None:
                return
            dec = hit[1] if hit[1] is not None else (9 if ch == "sol" and ca is None else 18)
            lq = Decimal(int(hit[0])) / (Decimal(10) ** int(dec))
        old_lq = Decimal(str(m.get("ledger") or 0))
        oq = Decimal(str(m.get("onchain") or 0))
        d_old = abs(oq - old_lq)
        if d_old <= 0 or not m.get("diffUsd"):
            return
        pxd = Decimal(str(m["diffUsd"])) / d_old
        diff_usd = abs(oq - lq) * pxd
        thr = max(Decimal(str(st["diff_abs_usd"])), Decimal(str(st["diff_pct"])) * max(abs(lq), abs(oq)) * pxd)
        m["ledger"] = float(lq)
        m["diffUsd"] = round(float(diff_usd), 2)
        if diff_usd < thr:
            m["ledgerFixed"] = True
            m["confirmed"] = False
    except (TypeError, ValueError, ArithmeticError):
        return


def alert_text(new_alerts: list) -> str:
    lines = [f"⚠️ 온체인 잔고 불일치 {len(new_alerts)}건 (원장 vs 온체인 — 원장은 안 고침, 확인 필요)"]
    for m in new_alerts[:10]:
        if m.get("chain") == UPBIT_KEY[0]:
            lines.append(f"- 업비트 {m['sym']}: 원장 {m['ledger']:,.4f} / 업비트 잔고 {m['onchain']:,.4f} (차이 ${m['diffUsd']:,.0f})"
                         + (" · 지난 실측값(재대조 지연)" if m.get("carried") else ""))
            continue
        lines.append(f"- {m['chain']} {m['wallet'][:6]}…{m['wallet'][-4:]} {m['sym']}: 원장 {m['ledger']:,.4f}"
                     f" / 온체인 {m['onchain']:,.4f} (차이 ${m['diffUsd']:,.0f})"
                     + (" · 지난 실측값(재대조 지연)" if m.get("carried") else ""))
    if len(new_alerts) > 10:
        lines.append(f"… 외 {len(new_alerts) - 10}건 — 대시보드 balanceCheck 참조")
    return "\n".join(lines)


def finalize(state: dict, defer_keys=frozenset()) -> list:
    now = time.time()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    alerted = {k: v for k, v in (state.get("alerted") or {}).items()
               if v >= (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")}
    out = []
    for m in state.get("mismatches") or []:
        if not m.get("confirmed") or m.get("key") in defer_keys:
            continue
        if m.get("carried"):
            try:
                if not (now - float(m.get("firstSeen") or now) >= 86400):
                    continue
            except (TypeError, ValueError):
                continue
        k = f"{m['key']}:{today}"
        if alerted.get(k):
            continue
        alerted[k] = today
        out.append(m)
    state["alerted"] = alerted
    return out


def view():
    try:
        if not os.path.exists(STATUS_PATH):
            return None
        d = common.read_json(STATUS_PATH, {})
    except (Exception, SystemExit):
        return None
    return {"checkedAt": d.get("checkedAt"), "checked": d.get("checked"), "pairs": d.get("pairs"),
            "capped": d.get("capped"), "errors": len(d.get("errors") or []), "unchecked": d.get("unchecked"),
            "mismatches": [{k: m.get(k) for k in ("wallet", "chain", "sym", "ledger", "onchain", "diffUsd",
                                                  "confirmed", "firstSeen")}
                           for m in (d.get("mismatches") or [])]}
