from __future__ import annotations
import acct_norm
import cgca
import chain_registry
import config, logs, paths, statefile
import depaddr
import exprov
import json
import os
import token_tables
import provbal
import spamguard
import ubfill
import xfer_match
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from view_common import CHAIN_NAME
from view_common import STABLE_GROUPS
from view_text import _scam_name
import logging
import calcguard  # noqa: E402

log = logging.getLogger('tj-web')


class ProvMixin:

    def _prov_items(self, conn) -> list:
        prov = provbal.load()
        if not prov:
            return []
        done9 = {str(r[0]) for r in conn.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%'")}
        if all(f"recon_done_{c9}" in done9 for c9 in prov):
            return []
        dec9 = {}
        amap9 = {}

        def asset_of(chain, kind, addr):
            if chain not in amap9:
                m9 = amap9[chain] = {}
                for r in conn.execute("SELECT asset_id, kind, address, group_id, symbol, decimals FROM assets WHERE chain=? AND kind IN ('native', 'token')"
                                      " ORDER BY asset_id", (chain,)).fetchall():
                    k9 = (r[1], None if r[1] == "native" else (str(r[2] or "") if chain == "sol" else str(r[2] or "").lower()))
                    m9.setdefault(k9, (r[0], r[3] if r[3] is not None else -r[0], r[4], r[5]))
            return amap9[chain].get((kind, None if kind == "native" else (str(addr or "") if chain == "sol" else str(addr or "").lower())))

        def ainfo(aid):
            r = conn.execute("SELECT kind, address, symbol, decimals, group_id FROM assets WHERE asset_id=?", (aid,)).fetchone()
            return (r[0], r[1], r[2], r[3], r[4] if r[4] is not None else -aid) if r else None

        def ledger(loc, ent):
            if loc.startswith("wallet:sol:") and ":stake:" in loc and ent.get("stake_ts") and not ent.get("stake_live"):
                ent = dict(ent, at=int(ent["stake_ts"]), t1=int(ent["stake_ts"]), block=None)
            b9 = ent.get("block") if isinstance(ent.get("block"), int) and isinstance(ent.get("bts"), int) else None
            if b9 is not None:
                lo9, hi9, m9 = int(ent["bts"]), int(ent["bts"]), 30
            else:
                lo9, hi9, m9 = int(ent.get("at") or 0), int(ent.get("t1") or ent.get("at") or 0), 60
            out9, amb9 = {}, set()
            for aid9, qb9, sk9, ts9, bk9 in conn.execute(
                    "SELECT p.asset_id, p.qty_base, p.source_kind, p.event_ts, r.block FROM postings p"
                    " LEFT JOIN raw_txs r ON p.source_kind = 'chain_tx' AND r.chain = p.source_ns AND r.txhash = p.source_id"
                    " WHERE p.location=?", (loc,)).fetchall():
                try:
                    if b9 is not None and sk9 == "chain_tx" and bk9 is not None:
                        inc9 = int(bk9) <= b9
                    elif ts9 is not None and int(ts9) < lo9 - m9:
                        inc9 = True
                    elif ts9 is not None and int(ts9) > hi9 + m9:
                        inc9 = False
                    else:
                        amb9.add(aid9)
                        continue
                except (TypeError, ValueError):
                    amb9.add(aid9)
                    continue
                if not inc9:
                    continue
                if aid9 not in dec9:
                    r9 = conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid9,)).fetchone()
                    dec9[aid9] = r9[0] if r9 else None
                try:
                    out9[aid9] = out9.get(aid9, Decimal(0)) + Decimal(str(qb9)) / (Decimal(10) ** int(dec9[aid9]))
                except (TypeError, ValueError, InvalidOperation):
                    out9[aid9] = None
                    dec9[aid9] = None
            return out9, amb9
        return provbal.items(prov, done_chain=lambda c: f"recon_done_{c}" in done9, asset_of=asset_of, ledger=ledger, ainfo=ainfo)

    def _exf_prov_items(self, conn, exb) -> list:
        exb = type(self)._hl_bal_view(exb)
        if not exb:
            return []
        done9 = {str(r[0]) for r in conn.execute("SELECT k FROM meta WHERE k LIKE 'recon\\_done\\_exf\\_%' ESCAPE '\\'")}
        if all(f"recon_done_exf_{e9}" in done9 for e9 in exb):
            return []

        def ledger(ex, bts):
            return type(self)._exf_prov_ledger(conn, ex, bts)
        return exprov.items(exb, done=lambda e9: f"recon_done_exf_{e9}" in done9, ledger=ledger)

    @staticmethod
    def _exf_prov_ledger(conn, ex, bts):
        out9, amb9, tot9 = {}, set(), {}
        legs9 = ProvMixin._exf_trade_legs(conn, ex)
        for qb9, ts9, sym9, dec9, gid9, aid9, sns9, sid9, lsq9 in conn.execute(
                "SELECT p.qty_base, p.event_ts, a.symbol, a.decimals, a.group_id, p.asset_id, p.source_ns, p.source_id, p.leg_seq FROM postings p"
                " JOIN assets a ON a.asset_id = p.asset_id WHERE p.location=?", (f"exchange:{ex}",)).fetchall():
            su9 = str(sym9 or "").upper()
            if not su9:
                continue
            try:
                tot9[su9] = tot9.get(su9, Decimal(0)) + Decimal(str(qb9)) / (Decimal(10) ** (8 if dec9 is None else int(dec9)))
            except (TypeError, ValueError, InvalidOperation):
                amb9.add(su9)
                continue
            try:
                t9 = int(ts9)
            except (TypeError, ValueError):
                amb9.add(su9)
                continue
            parts9 = [(t9, qb9)]
            lg9 = legs9.get(str(sid9)) if sns9 == f"{ex}:trade" and lsq9 == 0 else None
            if lg9:
                if all(len(l9) > 2 for l9 in lg9):
                    try:
                        vs9 = [Decimal(str(l9[2])) for l9 in lg9]
                        vt9, q9i, acc9, parts9 = sum(vs9), int(qb9), 0, []
                        for i9, l9 in enumerate(lg9):
                            p9 = (q9i - acc9) if i9 == len(lg9) - 1 else int(Decimal(q9i) * vs9[i9] / vt9)
                            acc9 += p9
                            parts9.append((int(l9[0]), p9))
                    except (TypeError, ValueError, InvalidOperation, ZeroDivisionError, IndexError):
                        amb9.add(su9)
                        continue
                else:
                    try:
                        sd9 = {("b" if int(l9[0]) < int(bts) - 60 else "a" if int(l9[0]) > int(bts) + 60 else "m") for l9 in lg9}
                    except (TypeError, ValueError, IndexError):
                        sd9 = {"m"}
                    if "m" in sd9 or len(sd9) > 1:
                        amb9.add(su9)
                        continue
            for t9, q9 in parts9:
                if abs(t9 - int(bts)) <= 60:
                    amb9.add(su9)
                    break
                if t9 > int(bts):
                    continue
                g9 = gid9 if gid9 is not None else -int(aid9)
                per9 = out9.setdefault(su9, {})
                if per9.get(g9, 0) is None:
                    continue
                try:
                    per9[g9] = per9.get(g9, Decimal(0)) + Decimal(str(q9)) / (Decimal(10) ** (8 if dec9 is None else int(dec9)))
                except (TypeError, ValueError, InvalidOperation):
                    per9[g9] = None
        return out9, amb9, tot9

    @staticmethod
    def _exf_trade_legs(conn, ex) -> dict:
        out, rev = {}, {}
        try:
            rows = conn.execute("SELECT uuid, revision, payload FROM raw_ex WHERE exchange=? AND kind='trade' AND payload LIKE '%cashlegs%'", (ex,)).fetchall()
        except Exception as _cg9:   # noqa: BLE001 [fallback]
            calcguard.swallowed("view_prov:ProvMixin._exf_trade_legs", _cg9)
            return out
        for u9, r9, pl9 in rows:
            try:
                if u9 in rev and int(r9) <= rev[u9]:
                    continue
                lg9 = (json.loads(pl9) or {}).get("cashlegs")
                rev[u9] = int(r9)
                if isinstance(lg9, list) and len(lg9) >= 2 and all(isinstance(l9, list) and len(l9) >= 2 for l9 in lg9):
                    out[str(u9)] = lg9
                else:
                    out.pop(str(u9), None)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _wdt_prov_mark(wdt, cs, xs, xblk=None) -> int:
        n = 0
        for e9 in wdt or ():
            try:
                if e9.get("state") == "pending" and exprov.covered(e9, chain_seen=cs, ex_seen=xs, chain_of=depaddr.chain_of, norm=xfer_match.norm_addr,
                                                                     ex_block=xblk):
                    e9["state"], e9["why"] = "prov", "prov"
                    n += 1
                    if isinstance(e9.get("ev"), dict):
                        e9["ev"]["d"] = (f"{e9.get('src')} 출금 → " + (f"{e9['dst']} " if e9.get("dst") else "")
                                         + "· 받는 쪽 옛 기록 받는 중 — 지금 잔고에 이미 반영")
            except (TypeError, ValueError, KeyError, AttributeError) as e8:
                log.debug("전송 중 임시 잔고 판정 건너뜀: %s", e8)
        return n

    @staticmethod
    def _hl_bal_view(exb) -> dict:
        exb = dict(exb or {})
        bph9 = paths.state("exf_balances_hyperliquid.json")
        for c9 in (bph9, bph9 + ".pending", bph9 + ".view"):
            try:
                d9 = statefile.read_json(c9, {}) if os.path.exists(c9) else {}
            except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
                calcguard.swallowed("view_prov:ProvMixin._hl_bal_view", _cg9)
                d9 = {}
            if isinstance(d9, dict) and isinstance(d9.get("balances"), dict):
                exb["hyperliquid"] = (c9, d9)
                break
        return exb

    def _prov_seen(self, conn, exb) -> tuple:
        cs, xs = {}, {}
        self._prov_xblk = {}
        done9 = {str(r[0]) for r in conn.execute("SELECT k FROM meta WHERE k LIKE 'recon\\_done\\_%' ESCAPE '\\'")}
        nsym9 = dict(self.cfg.get("native_symbol") or {})
        for ch9, ent9 in sorted((provbal.load() or {}).items()):
            if not isinstance(ent9, dict) or ent9.get("mode") != "chain" or f"recon_done_{ch9}" in done9:
                continue
            try:
                seen9 = int(ent9.get("bts") or ent9.get("t1") or ent9.get("at"))
            except (TypeError, ValueError):
                continue
            for w9, wb9 in (ent9.get("wallets") or {}).items():
                un9 = set()
                if isinstance(wb9, dict):
                    if "native" in wb9:
                        u9 = provbal._unit({"chain": ch9, "kind": "native"}, native_sym=lambda c9: nsym9.get(c9))
                        if u9:
                            un9.add(u9)
                    uo9 = {str(x9).lower() for x9 in (wb9.get("unobs") or ())}
                    cas9 = wb9.get("q") if isinstance(wb9.get("q"), list) else list((wb9.get("tok") or {}).keys())
                    for ca9 in cas9:
                        if str(ca9).lower() in uo9:
                            continue
                        u9 = provbal._unit({"chain": ch9, "kind": "token", "addr": ca9})
                        if u9:
                            un9.add(u9)
                    if ch9 == "sol" and "q" not in wb9:
                        un9 |= {str(v9).upper() for v9 in token_tables.STABLE_MINTS.values()}
                cs[(ch9, xfer_match.norm_addr(w9))] = (seen9, frozenset(un9))
        for ex9, (_p9, d9) in sorted((type(self)._hl_bal_view(exb) or {}).items()):
            if f"recon_done_exf_{ex9}" in done9 or not isinstance(d9, dict):
                continue
            try:
                t9 = int(float(d9.get("ts") or 0))
            except (TypeError, ValueError):
                continue
            if t9 > 0:
                xs[ex9] = t9
                try:
                    self._prov_xblk[ex9] = exprov.blocked(type(self)._exf_prov_ledger(conn, ex9, t9))
                except Exception as e9:   # noqa: BLE001 [isolate]
                    calcguard.swallowed("view_prov:ProvMixin._prov_seen", e9)
                    xs.pop(ex9, None)
                    log.warning("첫 대사 전 거래소 보류 심볼 계산 실패(%s — 전송 중 그대로): %s", ex9, logs.safe_err(e9)[:120])
        return cs, xs

    def _prov_price(self, its, now, cg_want, cg_px_want, hold_prio) -> list:
        nsym9 = dict(self.cfg.get("native_symbol") or {})
        off9 = set(self.spot.off_chains or ())
        out, dexw9, natw9 = [], set(), set()
        tot9 = {}
        for it in its:
            if it["kind"] != "native":
                p9 = (it["chain"], str(it["addr"] or "") if it["chain"] == "sol" else str(it["addr"] or "").lower())
                tot9[p9] = tot9.get(p9, 0.0) + max(0.0, float(it["qty"]))
        for it in its:
            ch9, q9 = it["chain"], float(it["qty"])
            if it["kind"] == "native":
                sym9 = str(nsym9.get(ch9) or chain_registry.native_symbol(ch9) or ch9.upper())
                it["sym"] = sym9
                if sym9.upper() in STABLE_GROUPS:
                    it["stable"] = True
                    out.append((it, 1.0, None))
                    continue
                natw9.add(sym9)
                out.append((it, float(self.spot.price(sym9) or 0), None))
                continue
            k9 = str(it["addr"] or "") if ch9 == "sol" else str(it["addr"] or "").lower()
            it["addr"] = k9
            q9 = tot9.get((ch9, k9), q9)
            sym9 = str(it["sym"] or "")
            if token_tables.STABLE_CAS.get(ch9, {}).get(k9) or (ch9 == "sol" and token_tables.STABLE_MINTS.get(k9)):
                it["stable"] = True
                out.append((it, 1.0, None))
                continue
            if _scam_name(sym9):
                out.append((it, 0, "스팸 이름"))
                continue
            if spamguard.major_of(sym9) and not spamguard.is_genuine(ch9, k9):
                out.append((it, 0, "가짜 대표 심볼"))
                continue
            gen9 = spamguard.is_genuine(ch9, k9) or spamguard.is_user_genuine(ch9, k9)
            st9 = cgca.status(ch9, k9)
            if st9 is False and not gen9:
                out.append((it, 0, "코인게코 시세 없음"))
                continue
            if ch9 not in off9:
                dexw9.add((ch9, k9))
            px9 = 0.0
            dx9 = self.spot.dex_price(ch9, k9)
            if dx9:
                rv9 = self.spot.dex_reserve(ch9, k9)
                if rv9 is not None and q9 * float(dx9) > rv9:
                    self.spot._guard_note(f"{ch9}:{k9}", f"보유 평가 ${q9 * float(dx9):,.0f} > 풀 유동성 ${rv9:,.0f}")
                else:
                    px9 = float(dx9)
                    it["src"] = "dex:" + self.spot.dex_src.get(f"{ch9}:{k9}", "gecko")
            if not px9 and spamguard.is_genuine(ch9, k9):
                m9 = spamguard.major_of(sym9)
                if m9 in spamguard.STABLE_MAJ and spamguard.is_user_genuine(ch9, k9):
                    px9 = 1.0
                elif m9 and m9 not in STABLE_GROUPS:
                    ms9 = {"WETH": "ETH", "WBTC": "BTC", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL"}.get(m9, m9)
                    natw9.add(ms9)
                    px9 = float(self.spot.price(ms9) or 0)
                    if px9:
                        it["src"] = "cex:글로벌"
            lp9 = float(self.spot.dex_usd.get(f"{ch9}:{k9}") or 0)
            if ch9 not in off9:
                hold_prio[(ch9, k9)] = max(hold_prio.get((ch9, k9), 0.0), q9 * (lp9 or px9))
                if not gen9:
                    cg_want[(ch9, k9)] = max(cg_want.get((ch9, k9), 0.0), q9 * lp9)
            if not px9 and st9:
                if ch9 not in off9:
                    cg_want[(ch9, k9)] = max(cg_want.get((ch9, k9), 0.0), q9 * lp9)
                    cg_px_want.add((ch9, k9))
                cp9 = cgca.price(ch9, k9, now=self.spot.off_at.get(ch9) if ch9 in off9 else None)
                if cp9:
                    px9 = float(cp9)
                    it["src"] = "coingecko"
            out.append((it, px9, None))
        if natw9:
            self.spot.want(natw9)
        self.spot.want_tokens(dexw9, slot="prov")
        return out

    def _prov_field(self, bfp) -> dict:
        pv = self.__dict__.get("_prov_view") or {}
        if not pv.get("n"):
            return None
        fxn9 = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "hyperliquid": "Hyperliquid", "coinbase": "코인베이스"}
        names = [CHAIN_NAME.get(c, c) for c in sorted(pv.get("chains") or {}) if not str(c).startswith("exchange:")]
        exn9 = [fxn9.get(str(c)[9:], str(c)[9:]) for c in sorted(pv.get("chains") or {}) if str(c).startswith("exchange:")]
        jobs = {str(j.get("chain") or ""): j for j in ((bfp or {}).get("jobs") or []) if isinstance(j, dict)}
        parts = []
        for nm in names:
            j = jobs.get(nm)
            parts.append(f"{nm} {j.get('prog')}" + (f" · {j.get('eta')}" if j.get("eta") else "") if j else nm)
        parts += [f"{nm} 거래소" for nm in exn9]
        note = "원가·손익·지난날 곡선은 옛 기록을 다 받으면(" + " · ".join(parts) + ") 정확하게 맞춰져요 — 오늘 보유·총자산은 지금 실제 잔고예요"
        return {"usd": pv.get("usd"), "n": pv.get("n"), "chains": pv.get("chains"), "note": note,
                "skipped": pv.get("skipped") or {}}

    def _ub_fill_view(self, conn, snap, pos_disp, G, transit_gids, now):
        info = {"why": "none", "n": 0, "ts": int(float((snap or {}).get("ts") or 0))}
        if not snap:
            return pos_disp, {}, {}, info

        def ts_of9(pl):
            try:
                return acct_norm.fill_ts(pl) or datetime.fromisoformat(str(pl["created_at"])).timestamp()
            except (ValueError, TypeError, KeyError):
                return None
        if not (now - float(snap.get("ts") or 0) < config.upbit_fresh_sec(self.cfg)):
            info["why"] = "stale"
            if now - float(snap.get("ts") or 0) < self.UB_KRW_KEEP_SEC:
                dm9, _w9 = ubfill.snapshot_deltas(conn, snap, ts_of9)
                if dm9 and any(e9["dq"] or e9.get("krw") for e9 in dm9.values()):
                    info["stale_fill"] = 1
                    info["krw_st"] = float(ubfill.cash_krw(dm9))
                if ubfill.has_cash_flow(dm9):
                    info["ufx"] = 1
            return pos_disp, {}, {}, info
        dm, why = ubfill.snapshot_deltas(conn, snap, ts_of9)
        info["why"] = why
        if not dm:
            return pos_disp, {}, {}, info
        loc = "exchange:upbit"
        out = list(pos_disp)
        dl, kc = {}, {}
        applied = {}
        led0 = set()
        for sym, e in sorted(dm.items()):
            dq = e["dq"]
            idx = sorted((i for i, r in enumerate(out)
                          if r["location"] == loc and r["qty"] > 0 and not (G.get(r["gid"]) or {}).get("is_fiat")
                          and str((G.get(r["gid"]) or {}).get("sym") or "").upper() == sym),
                         key=lambda i: (-out[i]["qty"], out[i]["gid"]))
            if dq == 0:
                if e.get("krw"):
                    info["n"] += int(e["n"])
                if idx:
                    led0.add(sym)
                continue
            if dq > 0:
                if idx:
                    i = idx[0]
                    out[i] = dict(out[i], qty=out[i]["qty"] + dq)
                    gid = out[i]["gid"]
                else:
                    tg = sorted(g9 for g9 in transit_gids if str((G.get(g9) or {}).get("sym") or "").upper() == sym
                                and not (G.get(g9) or {}).get("is_fiat"))
                    if not tg:
                        continue
                    gid = tg[0]
                    out.append({"gid": gid, "location": loc, "qty": dq})
                dl[(gid, loc)] = dl.get((gid, loc), Decimal(0)) + dq
                applied[sym] = applied.get(sym, Decimal(0)) + dq
                if e["k"] > 0:
                    usd9 = Decimal(0)
                    for ccy9, amt9 in e["c"].items():
                        if ccy9 == "KRW":
                            p9 = (1.0 / float(self.spot.rate)) if self.spot.rate else 0.0
                        elif ccy9 in STABLE_GROUPS:
                            p9 = 1.0
                        else:
                            p9 = float(self.spot.ex_price("upbit", ccy9) or self.spot.price(ccy9) or 0)
                        if p9 <= 0:
                            usd9 = None
                            break
                        usd9 += amt9 * Decimal(str(p9))
                    if usd9 is not None:
                        k9, c9 = kc.get(gid, (Decimal(0), Decimal(0)))
                        kc[gid] = (k9 + e["k"], c9 + usd9)
            else:
                left = -dq
                for i in idx:
                    take = min(out[i]["qty"], left)
                    if take <= 0:
                        continue
                    out[i] = dict(out[i], qty=out[i]["qty"] - take)
                    gid = out[i]["gid"]
                    dl[(gid, loc)] = dl.get((gid, loc), Decimal(0)) - take
                    applied[sym] = applied.get(sym, Decimal(0)) - take
                    left -= take
                    if left <= 0:
                        break
            info["n"] += int(e["n"])
        info["krw_tl"] = float(ubfill.cash_krw(dm))
        ubf9 = {}
        for sym, e in dm.items():
            un9 = e["dq"] - applied.get(sym, Decimal(0))
            if un9:
                ubf9[sym] = float(un9)
        if ubf9:
            info["ubf"] = ubf9
        ufc9 = {}
        for sym, e in dm.items():
            a9 = applied.get(sym, Decimal(0))
            if e["dq"] and a9:
                for u9, k9 in (e.get("ko") or {}).items():
                    ufc9[u9] = ufc9.get(u9, Decimal(0)) + k9 * a9 / e["dq"]
        ufc9 = {u9: round(float(v9), 2) for u9, v9 in ufc9.items() if v9}
        if ufc9:
            info["ufc"] = ufc9
        ufz9 = {}
        for sym in sorted(led0):
            z9 = {u9: round(float(k9), 2) for u9, k9 in (dm[sym].get("ko") or {}).items() if k9}
            if len(z9) >= 2:
                ufz9[sym] = z9
        if ufz9:
            info["ufz"] = ufz9
        if ubfill.has_cash_flow(dm):
            info["ufx"] = 1
        return out, dl, kc, info
