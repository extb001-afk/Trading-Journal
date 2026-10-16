from __future__ import annotations
import acct_norm
import common
import depaddr
import json
import os
import rawtx_cache
import re
import spamguard
import time
from datetime import datetime
from decimal import Decimal
from view_common import CHAIN_NAME
from view_common import DM_PATH
from view_common import KST
from view_common import SUB_TAG_RE
from view_fut import FUT_CEX
from view_fut import FUT_T_MIN_MS
from view_fut import PERP_KEYS
from view_fut import PERP_NAMES
from view_fut import _FUT_USD_SETTLE
from view_fut import _fin
from view_fut import _fut_by_date_ex
from view_fut import _fut_fxb
from view_fut import _fut_notional_sum
from view_fut import _fut_settle
from view_fut import _fut_upnl_usd
from view_fut import fut_ev_usd
from view_fut import fut_px_at
from view_fut import perp_active
from view_fut import perp_filter
from view_pending import _PEND_GAP
from view_pending import _PEND_WHY_UNKNOWN
from view_text import _human_dm
from view_text import _scam_name
from view_text import _short_addr
import logging
import calcguard

log = logging.getLogger('tj-web')


class IndexMixin:

    def _futures_view(self, fxb=None):
        poss, ev, margin, ts_max, mm = [], [], 0.0, 0, {}
        snapshot_ts, stale_ex = {}, []
        now9 = time.time()
        perp_on = {}
        try:
            perp_on = perp_active()
            if perp_on is None:
                perp_on = dict(self.__dict__.get("_perp_on_last") or {})
            else:
                self.__dict__["_perp_on_last"] = perp_on
        except Exception as e9:
            calcguard.swallowed("view_index:IndexMixin._futures_view", e9)
            perp_on = {}
            log.warning("퍼프 덱스 설정 읽기 실패(합류 생략): %s", e9)
        venues = {}
        pxf9, est_n9 = None, 0
        for ex9 in FUT_CEX + tuple(k9 for k9 in PERP_KEYS if k9 in perp_on):
            try:
                d9 = common.read_json(
                    os.path.join(common.STATE_DIR, f"futures_{ex9}.json"), {})
            except SystemExit:
                log.warning("선물 스냅숏 손상: %s — 이번 빌드에서 제외", ex9)
                continue
            if not d9:
                continue
            if ex9 in perp_on:
                on9 = perp_on[ex9]
                d9 = perp_filter(d9, on9, now9, ex9)
                ac9 = d9["accts"]
                venues[ex9] = {"dex": True, "accts": len(on9), "err": sum(1 for a9 in on9 if (ac9.get(a9) or {}).get("err")),
                               "equity": _fin((d9.get("wallet") or {}).get("equity")),
                               "liq": sum(1 for r9 in d9["events"] if r9.get("liq") and r9.get("kind") == "REALIZED")}
            ts9 = int(d9.get("ts") or 0)
            snapshot_ts[ex9] = ts9
            fresh9 = ts9 > 0 and now9 - ts9 <= 1800
            if fresh9:
                ts_max = max(ts_max, ts9)
            else:
                stale_ex.append(ex9)
            w9 = (d9.get("wallet") or {}) if fresh9 else {}
            margin += _fin(w9.get("balance")) or 0.0
            mb9 = _fin(w9.get("margin_balance")) or 0.0
            mt9 = _fin(w9.get("maint_margin")) or 0.0
            if mb9 > 0 and mt9 >= 0 and w9.get("maint_margin") is not None:
                mm[ex9] = {"ratio": round(mt9 / mb9 * 100, 2),
                           "maint": round(mt9, 2), "balance": round(mb9, 2)}
            for p9 in ((d9.get("positions") or []) if fresh9 else ()):
                if isinstance(p9, dict) and all(_fin(p9.get(k9) or 0) is not None for k9 in ("qty", "entry", "mark", "upnl", "liq")):
                    poss.append(dict(p9, ex=ex9))
            t_hi9 = (now9 + 86400) * 1000
            for r9 in d9.get("events") or []:
                if not isinstance(r9, dict) or r9.get("kind") not in ("REALIZED", "FUNDING", "FEE"):
                    continue
                a9, tt9 = _fin(r9.get("amount") or 0), _fin(r9.get("t"))
                if a9 is None or (tt9 and not (FUT_T_MIN_MS <= tt9 <= t_hi9)):
                    continue
                if r9.get("asset"):
                    if pxf9 is None:
                        pxf9 = fut_px_at(fxb if fxb is not None else _fut_fxb(getattr(self, "px", None), self.spot), self.spot.price)
                    r9 = fut_ev_usd(r9, lambda a9, t9=r9.get("t"): pxf9(a9, t9))
                    if r9 is None:
                        continue
                    est_n9 += 1 if r9.get("px_est") else 0
                ev.append(dict(r9, ex=ex9))
        exn = dict({"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX"}, **PERP_NAMES)

        def exl9(r9):
            n9 = exn.get(r9.get("ex"), r9.get("ex"))
            a9 = r9.get("acct")
            return f"{n9} · 서브{a9[1:]}" if r9.get("ex") in FUT_CEX and isinstance(a9, str) and SUB_TAG_RE.fullmatch(a9) else n9
        notional = _fut_notional_sum(poss)
        upv9 = [_fut_upnl_usd(p, self.spot.price) for p in poss]
        upk9 = [u9 for u9, _w9 in upv9 if u9 is not None]
        upnl = sum(upk9) if (upk9 or not poss) else None
        long_n = _fut_notional_sum([p for p in poss if p.get("side") == "LONG"])
        short_n = _fut_notional_sum([p for p in poss if p.get("side") != "LONG"])
        by_date, rows = {}, []
        by_date_krw = {}
        by_date_ex = {}
        fev9 = []
        for r9 in ev:
            try:
                t9 = int(r9.get("t") or 0)
                amt9 = float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if not t9:
                continue
            dt9 = datetime.fromtimestamp(t9 / 1000, KST)
            dk9 = dt9.strftime("%Y-%m-%d")
            by_date[dk9] = by_date.get(dk9, 0) + amt9
            k9 = amt9 * (fxb.rate_at(t9 // 1000) if fxb else float(self.spot.rate or 1384))
            by_date_krw[dk9] = by_date_krw.get(dk9, 0) + k9
            fev9.append((dk9, t9, amt9, k9, r9))
            x9 = by_date_ex.setdefault((dk9, r9.get("ex")), [0.0, 0.0, 0, 0])
            x9[0] += amt9
            x9[1] += k9
            x9[2] += 1 if r9.get("kind") == "REALIZED" else 0
            x9[3] = max(x9[3], t9)
            if r9.get("kind") == "REALIZED":
                rows.append(dict({"t": dt9.strftime("%m-%d %H:%M"), "_ts": t9,
                                  "sym": r9.get("symbol") or "—",
                                  "ex": exl9(r9),
                                  "pnl": round(amt9, 4)}, **({"liq": True} if r9.get("liq") else {})))
        rows.sort(key=lambda x: -x["_ts"])
        fee9 = []
        for r9 in ev:
            if r9.get("kind") not in ("FEE", "FUNDING"):
                continue
            try:
                t9, amt9 = int(r9.get("t") or 0), float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if t9:
                fee9.append({"_ts": t9, "kind": r9.get("kind"), "sym": r9.get("symbol") or "—",
                             "ex": exl9(r9), "amt": amt9})
        fee9.sort(key=lambda x: -x["_ts"])
        self._fut_detail = {"rows": rows, "fee": fee9}
        self._fut_ev = fev9
        self._fut_accts = {k9: sorted(v9) for k9, v9 in (perp_on or {}).items()}
        fsum = {}
        for x9 in rows:
            k9 = (datetime.fromtimestamp(x9["_ts"] / 1000, KST).strftime("%Y-%m"), x9["sym"], x9["ex"])
            a9 = fsum.setdefault(k9, [0, 0.0, 0.0])
            a9[0] += 1
            if x9["pnl"] > 0:
                a9[1] += x9["pnl"]
            else:
                a9[2] -= x9["pnl"]
        realized_summary = [[k9[0], k9[1], k9[2], v9[0], round(v9[1], 4), round(v9[2], 4)] for k9, v9 in sorted(fsum.items())]
        brk = {"REALIZED": 0.0, "FUNDING": 0.0, "FEE": 0.0}
        wins = losses = 0
        for r9 in ev:
            try:
                amt9 = float(r9.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            brk[r9.get("kind")] = brk.get(r9.get("kind"), 0.0) + amt9
            if r9.get("kind") == "REALIZED":
                if amt9 > 0:
                    wins += 1
                elif amt9 < 0:
                    losses += 1
        pos_out = []
        for p, (pu9, pw9) in zip(poss, upv9):
            try:
                liq9 = float(p.get("liq") or 0)
                mark9 = float(p.get("mark") or 0)
            except (TypeError, ValueError):
                liq9 = mark9 = 0.0
            dist9 = (round((liq9 - mark9) / mark9 * 100, 2)
                     if liq9 > 0 and mark9 > 0 else None)
            pos_out.append({"ex": exl9(p),
                            "exKey": p.get("ex"), **({"dex": True} if p.get("ex") in PERP_NAMES else {}),
                            "sym": p.get("symbol") or "—",
                            "side": p.get("side") or "",
                            "qty": float(p.get("qty") or 0),
                            "entry": float(p.get("entry") or 0),
                            "mark": mark9,
                            "upnl": None if pu9 is None else round(pu9, 2),
                            **({"upnlWhy": pw9} if pw9 else {}),
                            **({"settle": st9} if (st9 := _fut_settle(p)) and st9 not in _FUT_USD_SETTLE else {}),
                            "lev": str(p.get("leverage") or ""),
                            "liq": liq9, "liqDist": dist9})
        return {
            "margin": round(margin, 2), "notional": None if notional is None else round(notional, 2),
            "mmRatio": mm,
            "pnlBreak": {"realized": round(brk["REALIZED"], 2),
                         "funding": round(brk["FUNDING"], 2),
                         "fee": round(brk["FEE"], 2),
                         "net": round(brk["REALIZED"] + brk["FUNDING"] + brk["FEE"], 2),
                         "wins": wins, "losses": losses,
                         "winRate": (round(wins / (wins + losses) * 100, 1)
                                     if (wins + losses) else None)},
            "longNotional": None if long_n is None else round(long_n, 2), "shortNotional": None if short_n is None else round(short_n, 2),
            "upnl": None if upnl is None else round(upnl, 2), "posCount": len(poss), "ts": ts_max,
            "upnlPartial": any(u9 is None for u9, _w9 in upv9),
            "snapshotTs": snapshot_ts, "staleExchanges": stale_ex,
            "venues": venues,
            "positions": pos_out,
            "realizedByDate": {k: round(v, 2) for k, v in by_date.items()},
            "realizedKrwByDate": {k: round(v) for k, v in by_date_krw.items()},
            "realizedByDateEx": _fut_by_date_ex(by_date_ex, exn),
            "realizedRows": rows[:60],
            "realizedRowsTotal": len(rows), "realizedSummary": realized_summary,
            "realizedTotal": round(sum(r9["pnl"] for r9 in rows), 2),
            "coinEst": est_n9}

    @staticmethod
    def _impostor_reason(g, has_ca: bool, pairs=None, native: bool = False, priced: bool = True, liquid=False):
        if not has_ca or g.get("is_stable") or g.get("is_fiat"):
            return None
        if _scam_name(g.get("sym")) == "링크·보상 유도 이름":
            return "링크·보상 유도 이름(에어드랍 스캠)"
        if native or g.get("px_seen") or g.get("ex_seen"):
            return None
        if _scam_name(g.get("sym")) == "보상 유도 문구":
            return "보상 유도 문구(에어드랍 스캠)"
        sym9 = str(g.get("sym") or "")
        imp = None if re.fullmatch(r"TOKEN|native:.*|\?", sym9) else spamguard.impostor_of(sym9)
        if imp:
            return f"사칭 심볼 — {imp} 흉내(보이지 않는 글자·유사 글자)"
        fm = spamguard.fake_major(g.get("sym"), pairs)
        if fm and not g.get("risk_allow_bridge"):
            if not spamguard.plain_symbol(g.get("sym")):
                return f"가짜 {fm} — 정품 컨트랙트 아님"
            if not (g.get("wd_seen") or (liquid() if callable(liquid) else liquid)):
                g["risk_unv"] = fm
        odd = spamguard.odd_symbol(g.get("sym"))
        if odd:
            return f"사칭 문자 — {odd}"
        if g.get("spoof_n"):
            return "가짜 전송 로그 — 내가 서명하지 않은 tx 로 보유한 적 없는 수량을 '보냄'(주소 오염)"
        if g.get("spoof_soft") and not priced:
            return "가짜 전송 로그 — 내가 서명하지 않은 tx 의 '보냄' · 시세 없는 토큰(주소 오염)"
        return None

    @staticmethod
    def _event_hide_reason(e, G, quarantined, ca_gids):
        gid = e.get("_gid")
        if gid is None:
            return None
        if gid in quarantined:
            return (G.get(gid) or {}).get("risk_reason") or "격리(스팸) 자산"
        g = G.get(gid) or {}
        if gid not in ca_gids or g.get("is_stable") or g.get("is_fiat"):
            return None
        seen9 = set()
        for s9 in (e.get("symRaw"), e.get("sym"), g.get("sym")):
            if not isinstance(s9, str) or not s9 or s9 in seen9:
                continue
            seen9.add(s9)
            imp = spamguard.impostor_of(s9)
            if imp:
                return f"사칭 심볼 — {imp} 흉내"
        return None

    def _signer_map(self, conn, rows) -> dict:
        self._rtxc().sync(conn)
        cache = self._rtxc().signer
        want = {}
        for r in rows:
            if not (r["location"] or "").startswith("wallet:") or (r["source_ns"], r["source_id"]) in cache:
                continue
            if (r["leg_kind"] == "move_out" and (r["source_ns"] or "") != "sol"
                    and r["event"] in ("TRANSFER_OUT", "BRIDGE", "TRANSFER_SELF", "TRANSFER_OUT_EX")) \
                    or (r["leg_kind"] == "acq" and r["event"] in ("TRANSFER_IN", "PROGRAM_IN")) \
                    or (r["kind"] == "token" and (r["leg_kind"] in ("disp", "move_out") or (r["leg_kind"] == "acq" and r["event"] == "SWAP"))):
                want.setdefault(r["source_ns"], set()).add(r["source_id"])
        return self._rtxc().signer_fill(conn, want)

    @property
    def _signer_cache(self):
        return self._rtxc().signer

    @staticmethod
    def _tx_signer(conn, chain, txh):
        try:
            r9 = conn.execute("SELECT " + rawtx_cache.signer_cols(chain) + " FROM raw_txs WHERE chain=? AND txhash=? AND json_valid(snapshot)",
                              (chain, txh)).fetchone()
            return (r9[0], r9[1], r9[2]) if r9 else None
        except Exception as _cg9:
            calcguard.swallowed("view_index:IndexMixin._tx_signer", _cg9)
            return None

    def _risk_wl_hit(self, conn, g, wl) -> bool:
        my9 = set()
        for w9 in self._hist_wallets():
            my9.add(w9["address"] if w9.get("type") == "sol" else w9["address"].lower())
        for ch9, txh9, ca9 in (g.get("risk_srcs") or [])[:50]:
            row9 = conn.execute("SELECT snapshot FROM raw_txs WHERE chain=? AND txhash=?",
                                (ch9, txh9)).fetchone()
            if not row9:
                continue
            try:
                snap9 = json.loads(row9["snapshot"])
            except json.JSONDecodeError:
                continue
            for tt9 in snap9.get("token_transfers") or []:
                tok9 = tt9.get("token") or {}
                ca_t9 = (tok9.get("address") or tok9.get("address_hash") or "").lower()
                if ca_t9 != (ca9 or "").lower():
                    continue
                to9 = tt9.get("to")
                to9 = ((to9.get("hash") if isinstance(to9, dict) else to9) or "").lower()
                fr9 = tt9.get("from")
                fr9 = ((fr9.get("hash") if isinstance(fr9, dict) else fr9) or "").lower()
                if to9 in my9 and fr9 in wl:
                    return True
        return False

    def _cex_proof(self, conn) -> dict:
        try:
            sig = (tuple(conn.execute("SELECT COUNT(*), MAX(observed_at) FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchone()),
                   conn.execute("SELECT MAX(posting_id) FROM postings").fetchone()[0])
        except Exception as _cg9:
            calcguard.swallowed("view_index:IndexMixin._cex_proof", _cg9)
            sig = None
        cache = self.__dict__.get("_cex_proof_cache")
        if cache and sig is not None and cache[0] == sig:
            return cache[1]
        by_tx = {}
        last = {}
        for r in conn.execute("SELECT exchange, kind, uuid, revision, payload FROM raw_ex WHERE kind IN ('deposit','withdraw')").fetchall():
            k9 = (r["exchange"], r["kind"], r["uuid"])
            if k9 not in last or r["revision"] > last[k9][0]:
                last[k9] = (r["revision"], r["payload"])
        for (ex0, kind0, _u0), (_rv0, pl0) in last.items():
            try:
                pl = json.loads(pl0)
            except (TypeError, ValueError):
                continue
            tx = str(pl.get("txid") or "").strip()
            cur = str(pl.get("currency") or "").strip().upper()
            if not tx or not cur or str(pl.get("state") or "").upper() in self._CEX_FAIL_STATES:
                continue
            if re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", tx):
                tx = ("0x" + tx[-64:]).lower()
            by_tx.setdefault(tx, []).append((ex0, kind0, cur))
        proof = {}
        candidates = {}
        ids = list(by_tx)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            for r in conn.execute(
                    "SELECT p.source_id, p.qty_base, a.symbol, a.group_id FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
                    " WHERE p.source_kind = 'chain_tx' AND a.kind = 'token' AND a.group_id IS NOT NULL"
                    " AND p.location LIKE 'wallet:%%' AND p.source_id IN (%s)" % ",".join("?" * len(part)), part).fetchall():
                out9 = str(r["qty_base"] or "").startswith("-")
                for ex, kind, cur in by_tx.get(r["source_id"]) or ():
                    if (kind == "deposit") != out9:
                        continue
                    if not acct_norm.same_asset(r["symbol"], None, cur, ex):
                        continue
                    candidates.setdefault((r["source_id"], ex, kind, cur), set()).add(r["group_id"])
        for (_tx, ex, _kind, cur), gids in candidates.items():
            if len(gids) != 1:
                continue
            proof.setdefault(next(iter(gids)), set()).add((ex, cur))
        order = {e: i for i, e in enumerate(self.CEX_PX_ORDER)}
        out = {gid: sorted(v, key=lambda x: (order.get(x[0], 99), x[0], x[1])) for gid, v in proof.items()}
        self.__dict__["_cex_proof_cache"] = (sig, out)
        return out

    def _transfer_out_dest(self, conn) -> dict:
        if getattr(self, "_todst_at", 0) > time.time() - 60:
            return self._todst
        out = dict(getattr(self, "_todst", {}) or {})
        try:
            with open(DM_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        for ln in lines:
            if '"TRANSFER_OUT"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if d.get("kind") != "TRANSFER_OUT":
                continue
            pl = d.get("payload") or {}
            lbl = self._dest_label(pl)
            for aid_s in (pl.get("deltas") or {}):
                try:
                    row = conn.execute(
                        "SELECT symbol FROM assets WHERE asset_id=?", (int(aid_s),)).fetchone()
                except Exception as _cg9:
                    calcguard.swallowed("view_index:IndexMixin._transfer_out_dest", _cg9)
                    row = None
                if row and row["symbol"]:
                    sym9 = row["symbol"].upper()
                    ts9d = d.get("event_ts") or d.get("ts")
                    prev9 = out.get(sym9) or {}
                    tls9d = list(prev9.get("ts_list") or [])
                    if ts9d and ts9d not in tls9d:
                        tls9d = tls9d + [ts9d]
                    nots9 = bool(prev9.get("no_ts")) or not ts9d
                    out[sym9] = {"label": lbl, "to": pl.get("to"),
                                 "ts": ts9d, "ts_list": tls9d, "no_ts": nots9}
        self._todst, self._todst_at = out, time.time()
        return out

    def _dest_label(self, pl: dict) -> str:
        cands = [str(pl.get("to") or "")] + [str(x) for x in (pl.get("counterparties") or [])]
        cands = [c.lower() if c.startswith("0x") else c for c in cands if c]
        if not cands:
            return "미상"
        for c in cands:
            ex9 = self._ex_addr_index().get(c)
            if ex9:
                return {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX",
                        "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸",
                        "upbit": "업비트", "hyperliquid": "Hyperliquid"}.get(ex9, ex9)
            if c in self.addr_label:
                return f"내 지갑({self.addr_label[c]})"
        return "미등록 외부주소"

    def _ex_addr_index(self) -> dict:
        if getattr(self, "_exidx_at", 0) > time.time() - 60:
            return self._exidx
        idx = {}
        for e in self.cfg.get("exchange_addresses", []):
            a = str(e.get("address") or "")
            if a:
                idx[a.lower() if a.startswith("0x") else a] = e.get("exchange") or "?"
        try:
            for a, labs in depaddr.hint_index().items():
                if labs:
                    idx.setdefault(a, labs[0][0])
        except Exception as _cg9:
            calcguard.swallowed("view_index:IndexMixin._ex_addr_index", _cg9)
            pass
        self._exidx, self._exidx_at = idx, time.time()
        return idx

    def _dm_records(self) -> list:
        try:
            st = os.stat(DM_PATH)
        except OSError:
            self._dm_cache = None
            return []
        c = getattr(self, "_dm_cache", None)
        if not c or c["ino"] != st.st_ino or st.st_size < c["off"]:
            c = {"ino": st.st_ino, "off": 0, "recs": []}
        if st.st_size > c["off"]:
            try:
                with open(DM_PATH, "rb") as f:
                    f.seek(c["off"])
                    buf = f.read(st.st_size - c["off"])
            except OSError:
                return list(c["recs"])
            end = buf.rfind(b"\n") + 1
            for ln in buf[:end].splitlines():
                if b'"kind"' not in ln:
                    continue
                try:
                    d = json.loads(ln.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict) and d.get("kind") in self.DM_KINDS and d.get("kind") != "TRANSFER_OUT":
                    c["recs"].append(d)
            c["off"] += end
        self._dm_cache = c
        return list(c["recs"])

    def _pendings(self, conn, prefs) -> list:
        ignored = set(prefs.get("ignored", []))
        out = []
        seen = set()
        kind_map = self.DM_KINDS
        for d in reversed(self._dm_records()):
            k = d.get("kind")
            if k == "RECON":
                continue
            pl = d.get("payload") or {}
            key = f"{k}:{pl.get('txhash') or d.get('ts')}"
            if key in seen or key in ignored:
                continue
            seen.add(key)
            if k in ("TRANSFER_OUT", "PROGRAM_IN", "UNKNOWN") and pl.get("txhash") and pl.get("chain"):
                ev9 = conn.execute("SELECT event FROM tx_class WHERE chain=? AND txhash=?",
                                   (pl.get("chain"), str(pl.get("txhash")).lower())).fetchone()
                if ev9 and str(ev9["event"] or "").startswith("LP_"):
                    continue
            ch = pl.get("chain", "—")
            out.append({
                "key": key,
                "t": datetime.fromtimestamp(d.get("ts", 0), KST).strftime("%m-%d %H:%M"),
                "kind": kind_map[k], "sym": "—", "chain": CHAIN_NAME.get(ch, ch), "chainKey": ch,
                "onchain": (pl.get("txhash") or "—"),
                "ex": self._dest_label(pl) if k == "TRANSFER_OUT" else "—",
                "gap": _PEND_GAP.get(k) or _human_dm(d.get("text", ""))[:60],
                "why": (f"{self._dest_label(pl)}({_short_addr(pl.get('to'))})로 나간 전송입니다. 내 지갑이면 설정 › 연결 · 키에서 추가하고,"
                        " 외부로 보낸 게 맞으면 무시해도 됩니다." if k == "TRANSFER_OUT" else
                        "컨트랙트(프로그램)를 거쳐 들어온 토큰입니다. 스왑 체결인지 에어드랍인지 확인해 주세요." if k == "PROGRAM_IN" else
                        _PEND_WHY_UNKNOWN if k == "UNKNOWN" else
                        _human_dm(d.get("text", ""))),
                "to": pl.get("to") if k == "TRANSFER_OUT" else None,
                "tx": pl.get("txhash"),
                "cands": [],
            })
        out.extend(self._pend_unknown(conn, ignored, seen))
        rows = conn.execute(
            "SELECT t.transfer_id, t.qty_base, t.chain_txhash, t.updated_at, a.symbol, a.chain,"
            " a.decimals FROM transfers t JOIN assets a ON a.asset_id = t.asset_id"
            " WHERE t.state='sent' ORDER BY t.updated_at DESC").fetchall()
        for r in rows:
            dec = r["decimals"] if r["decimals"] is not None else 18
            qty = float(Decimal(int(r["qty_base"])) / Decimal(10) ** int(dec))
            key = f"sent:{r['transfer_id']}"
            if key in ignored:
                continue
            out.append({
                "key": key,
                "t": datetime.fromtimestamp(r["updated_at"], KST).strftime("%m-%d %H:%M"),
                "kind": "입금 기록 없음", "sym": r["symbol"] or "?",
                "chain": CHAIN_NAME.get(r["chain"], r["chain"]),
                "onchain": f"추적지갑 → 업비트 입금주소 · {qty:,.4f} {r['symbol'] or ''}",
                "ex": "—", "gap": "거래소 API 미연결 — 입금 확인 대기",
                "why": "업비트 조회 키가 아직 등록되지 않아 입금 확인을 못 합니다. 키 등록 후 자동 매칭됩니다.",
                "cands": [],
            })
        return out

    def _pend_unknown(self, conn, ignored, seen) -> list:
        seen_l = {str(k9).lower() for k9 in seen}
        ign_l = {str(k9).lower() for k9 in ignored}
        out = []
        try:
            rows = conn.execute("SELECT chain, txhash FROM tx_class WHERE event='UNKNOWN'").fetchall()
        except Exception as e:
            calcguard.swallowed("view_index:IndexMixin._pend_unknown", e)
            log.warning("분류 보류 검토 행 읽기 실패(건너뜀): %s", e)
            return out
        for r in rows:
            ch, tx9 = r["chain"], r["txhash"]
            key = f"UNKNOWN:{tx9}"
            if key.lower() in seen_l or key.lower() in ign_l:
                continue
            seen_l.add(key.lower())
            try:
                t9 = conn.execute("SELECT MIN(event_ts) FROM postings WHERE source_kind='chain_tx' AND source_ns=? AND source_id=?",
                                  (ch, tx9)).fetchone()[0]
            except Exception as _cg9:
                calcguard.swallowed("view_index:IndexMixin._pend_unknown", _cg9)
                t9 = None
            out.append((int(t9 or 0), {
                "key": key,
                "t": datetime.fromtimestamp(int(t9), KST).strftime("%m-%d %H:%M") if t9 else "—",
                "kind": self.DM_KINDS["UNKNOWN"], "sym": "—", "chain": CHAIN_NAME.get(ch, ch), "chainKey": ch,
                "onchain": tx9, "ex": "—", "gap": _PEND_GAP["UNKNOWN"], "why": _PEND_WHY_UNKNOWN,
                "to": None, "tx": tx9, "cands": [],
            }))
        out.sort(key=lambda x9: -x9[0])
        return [p9 for _t9, p9 in out]

    @staticmethod
    def _day_index(pos_ev_full, extra_vis, extra_hid, lp_events):
        ix, acts = {}, {}

        def add(kind, e, meta):
            try:
                ts = int(e.get("_ts") or 0)
            except (TypeError, ValueError):
                ts = 0
            if ts <= 0:
                return
            d = acct_norm.iso_day(ts)
            ix.setdefault(d, []).append((ts, kind, e, meta))
            a = acts.get(d)
            if a is None:
                a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
            if kind == "hidden":
                a["h"] += 1
                return
            k = str(e.get("k") or "")
            if k == "평단 갱신":
                return
            j = 2 if "매도" in k else (1 if "매수" in k else 0)
            c = a["src"].setdefault(e.get("src") or "", [0, 0, 0, 0])
            a["n"] += 1; c[0] += 1
            if j:
                a["b" if j == 1 else "s"] += 1; c[j] += 1
            if k == "입금 확인":
                a["dep"] += 1; c[3] += 1
        for pkey, sym, chain, evs in pos_ev_full:
            meta = (pkey, sym, chain)
            for e in evs:
                add("pos", e, meta)
        for e in extra_vis:
            add("extra", e, None)
        for e in extra_hid:
            add("hidden", e, None)
        for e in lp_events:
            add("lp", e, None)
        for d, rows in ix.items():
            a = acts.get(d)
            if a is None:
                continue
            buys = set()
            for _ts, kind, e, _m in rows:
                if kind != "hidden" and str(e.get("k") or "") == "온체인 매수" and "지불" in str(e.get("d") or "") and e.get("tx"):
                    buys.add((e.get("src") or "", e.get("tx")))
            pay, sp = 0, {}
            if buys or any(e.get("_ccapay") for _ts, kind, e, _m in rows):
                for _ts, kind, e, _m in rows:
                    if kind != "hidden" and str(e.get("k") or "") == "온체인 매도" and (e.get("_ccapay") or ((e.get("src") or ""), e.get("tx")) in buys):
                        pay += 1
                        sk = e.get("src") or ""
                        sp[sk] = sp.get(sk, 0) + 1
            a["pay"] = pay
            if sp:
                a["srcPay"] = sp
        return ix, {d: acts[d] for d in sorted(acts)}

    @staticmethod
    def _stab_index(stab_ev, acts):
        ix = {}
        for pkey, sym, chain, evs in stab_ev:
            meta = (pkey, sym, chain)
            for e in evs:
                if "매도" not in str(e.get("k") or ""):
                    continue
                try:
                    ts = int(e.get("_ts") or 0)
                except (TypeError, ValueError):
                    ts = 0
                if ts <= 0:
                    continue
                d = acct_norm.iso_day(ts)
                ix.setdefault(d, []).append((ts, e, meta))
                if e.get("_conv"):
                    a = acts.get(d)
                    if a is None:
                        a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
                    a["cv"] = int(a.get("cv") or 0) + 1
                    sk = e.get("src") or ""
                    cs = a.setdefault("cvSrc", {})
                    cs[sk] = int(cs.get(sk) or 0) + 1
        return ix

    @staticmethod
    def _conv_out(e, ts, d, meta):
        o = {k: v for k, v in e.items() if not k.startswith("_")}
        o["k"] = e.get("_conv") or "스테이블 교환"
        o["ts"], o["iso"], o["kind"] = ts, d, "conv"
        o["sym"], o["chain"] = meta[1], meta[2]
        return o

    def _conv_rows(self, idx, d_from, d_to):
        out = []
        for d, lst in (idx.get("stab") or {}).items():
            if d_from <= d <= d_to:
                out.extend(self._conv_out(e, ts, d, meta) for ts, e, meta in lst if e.get("_conv"))
        out.sort(key=lambda o: -o["ts"])
        return out

    def _krw_day_index(self, conn, acts):
        try:
            kf9 = self._krw_flows(conn)
        except Exception as e9:
            calcguard.swallowed("view_index:IndexMixin._krw_day_index", e9)
            log.warning("그날 기록 원화 입출금 색인 실패(목록에서 빠짐): %s", e9)
            kf9 = None
        ix = {}
        for r9 in ((kf9 or {}).get("rows") or ()):
            try:
                key9 = str(r9.get("key") or "")
                if r9.get("st") != "done" or key9.startswith("upbit:withdraw:"):
                    continue
                ex9 = key9.split(":", 1)[0]
                ts9, amt9, fee9 = int(r9["t"]), int(r9["amt"]), int(r9.get("fee") or 0)
                exn9 = str(r9.get("ex") or ex9)
            except (TypeError, ValueError, KeyError):
                continue
            if ts9 <= 0 or amt9 <= 0:
                continue
            if r9.get("src") == "int":
                d9 = f"{exn9} 원화 지급 · {r9.get('note') or '거래소 내부 지급'} (은행 아님)"
            elif r9.get("dir") == "in":
                d9 = f"{exn9} 입금 ← 은행 (원화 입금)"
            else:
                d9 = f"{exn9} 출금 → 은행 (원화 출금" + (f" · 수수료 ₩{fee9:,}" if fee9 else "") + ")"
            e9 = {"t": datetime.fromtimestamp(ts9, KST).strftime("%m-%d %H:%M"), "sym": "KRW", "k": "전송", "d": d9,
                  "q": f"{amt9:,}", "a": f"₩{amt9:,}", "tx": "—", "src": f"ex:{ex9}"}
            d = acct_norm.iso_day(ts9)
            ix.setdefault(d, []).append((ts9, e9))
            a = acts.get(d)
            if a is None:
                a = acts[d] = {"n": 0, "b": 0, "s": 0, "dep": 0, "h": 0, "src": {}}
            a["kw"] = int(a.get("kw") or 0) + 1
            ks9 = a.setdefault("kwSrc", {})
            ks9[e9["src"]] = int(ks9.get(e9["src"]) or 0) + 1
        return ix
