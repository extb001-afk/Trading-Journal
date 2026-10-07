from __future__ import annotations

from decimal import Decimal, InvalidOperation

import outflow_match as OM

WINDOW = 48 * 3600
EXP_NORMAL = 30 * 60
EXP_BRIDGE = 2 * 3600
BRIDGE_SCAN = 6 * 3600
EV_IN = ("TRANSFER_IN", "PROGRAM_IN", "STAKE_REWARD")
EV_DEP = ("EX_DEPOSIT", "EXF_DEPOSIT")
EV_ADJ = ("EX_ADJUST", "EXF_ADJUST", "OPENING")
EV_SEND = ("TRANSFER_OUT", "TRANSFER_OUT_EX", "TRANSFER_SELF", "BRIDGE")
EV_ALL = EV_SEND + EV_IN + EV_DEP + EV_ADJ
EX_KO = {"binance": "바이낸스", "bybit": "바이빗", "okx": "OKX", "kucoin": "쿠코인", "gate": "게이트", "bithumb": "빗썸", "upbit": "업비트",
         "hyperliquid": "하이퍼리퀴드"}


def txk(t) -> str:
    t = OM.norm_txid(t)
    return t.lower() if t.startswith("0x") else t


def _d(v):
    try:
        x = Decimal(str(v))
        return x if x.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def short(a) -> str:
    a = str(a or "")
    return f"{a[:6]}…{a[-4:]}" if len(a) > 12 else a


def _fee_allow(sent: Decimal, sym, bridge: bool) -> Decimal:
    st = OM.canon_sym(sym) in OM.STABLES
    if bridge:
        return sent * OM.BRIDGE_REL + (OM.BRIDGE_ABS_STABLE if st else Decimal(0))
    return sent * OM.FEE_REL + (OM.FEE_ABS_STABLE if st else Decimal(0))


def short_of(sent, got, fee=None, sym=None, bridge=False):
    s, g = _d(sent), _d(got)
    if s is None or g is None or s <= 0:
        return None
    allow = (_d(fee) if _d(fee) is not None and _d(fee) > 0 else _fee_allow(s, sym, bridge)) + s * Decimal("0.001")
    lack = s - g
    return lack - allow if lack > allow else None


class _Ctx:
    def __init__(self, G, px, now, names=None, skip_gids=frozenset()):
        self.G, self.px, self.now = G or {}, px or {}, float(now)
        n = names or {}
        self.chain = n.get("chain") or {}
        self.wallet = {str(k).lower(): str(v) for k, v in (n.get("wallet") or {}).items()}
        self.skip = frozenset(skip_gids or ())

    def sym(self, gid, raw=None):
        return str((self.G.get(gid) or {}).get("sym") or raw or "?")

    def usd(self, gid, qty):
        g = self.G.get(gid) or {}
        if g.get("is_fiat"):
            return None
        p = 1.0 if g.get("is_stable") else self.px.get(gid)
        try:
            p = float(p) if p is not None else None
        except (TypeError, ValueError):
            p = None
        if not p or p <= 0:
            return None
        return round(abs(float(qty)) * p, 2)

    def cname(self, ch):
        return self.chain.get(ch, ch or "")

    def where(self, loc):
        p = str(loc or "").split(":", 2)
        if p[0] == "wallet" and len(p) >= 2:
            a = p[2] if len(p) > 2 else ""
            lab = self.wallet.get(a.lower()) or self.wallet.get(a) or ""
            cn = self.cname(p[1])
            if lab:
                return lab if lab.startswith(cn) else f"{cn} {lab}"
            return f"{cn} 지갑 {short(a)}".strip()
        if p[0] == "exchange" and len(p) >= 2:
            return EX_KO.get(p[1], p[1])
        return str(loc or "")


def _returned_after(row, ts, usd) -> bool:
    if usd is None or usd <= 0:
        return False
    back = Decimal(0)
    for x in (row or {}).get("returned") or ():
        if isinstance(x, dict) and isinstance(x.get("ts"), (int, float)) and x["ts"] >= ts:
            back += _d(x.get("usd")) or Decimal(0)
    return back >= Decimal(str(usd)) * OM.FULL_RETURN


def _eid(a) -> str:
    return f"{a['ev']}|{a['ns']}|{a['sid']}|{a['loc']}|{a.get('ak') or a.get('sym') or a.get('gid')}"


def _ev(ctx, eid, ts, dir_, cls, ev, basis, gid, qty, sym=None, chain="", src="", dst="", tx="", kind="", arr=None):
    q = abs(float(qty))
    d = {"id": eid, "ts": int(ts), "dir": dir_, "cls": cls, "ev": ev, "basis": basis, "kind": kind or "",
         "sym": sym or ctx.sym(gid), "qty": q, "usd": ctx.usd(gid, qty), "chain": chain or "", "src": src or "", "dst": dst or "", "tx": str(tx or "")}
    if arr is not None:
        d["arr"] = arr
    return d


def classify(rows, ctx, transit=(), of_rows=(), of_match=None, of_bridge=None, deps=(), offc_ids=frozenset(), debts=None, krw=(), xf_links=None,
             proof_sends=None, deposit_exchange=None, skip_pids=frozenset()):
    of_match, of_bridge = of_match or {}, of_bridge or {}
    skip_pids = frozenset(skip_pids or ())

    def _bad(r):
        return r["gid"] in ctx.skip or r["pid"] in skip_pids
    lo = ctx.now - WINDOW
    out = []
    dep_by_uuid, dep_by_tx = {}, {}
    for d in deps or ():
        if not isinstance(d, dict):
            continue
        dep_by_uuid[(d.get("ex"), d.get("uuid"))] = d
        t = txk(d.get("txn"))
        if t:
            dep_by_tx.setdefault(t, []).append(d)
    by_addr = {str(r.get("address")): r for r in (of_rows or ()) if isinstance(r, dict) and r.get("address") is not None}
    tx_match = {}
    for a, r in by_addr.items():
        for x in r.get("txs") or ():
            if isinstance(x, dict) and isinstance(x.get("match"), dict):
                tx_match[(a, str(x.get("tx") or ""), str(x.get("sym") or ""))] = x["match"]
    phantom = {(a, str(t.get("sym"))) for a, r in by_addr.items() for t in (r.get("tokens") or ()) if isinstance(t, dict) and t.get("phantom")}
    wd_tx = {}
    for e in transit or ():
        t = txk(e.get("txid_raw") or (e.get("txid") if not str(e.get("txid") or "").startswith("amt:") else ""))
        if t:
            wd_tx[t] = e
    xf_dep = {str(k): v for k, v in (xf_links or {}).items() if isinstance(v, dict)}
    xf_by_wd = {}
    for k9, v9 in xf_dep.items():
        if v9.get("wd_uuid"):
            xf_by_wd.setdefault(str(v9["wd_uuid"]), []).append(k9)
    dep_post = {}
    for r in rows:
        if r["ev"] in EV_DEP and r["qty"] > 0 and not _bad(r):
            k9 = (str(r["ns"]).split(":", 1)[0], str(r["sid"]))
            if k9 in dep_post:
                dep_post[k9]["qty"] += r["qty"]
            else:
                dep_post[k9] = {"qty": r["qty"], "loc": r["loc"], "sym": r.get("sym"), "gid": r["gid"], "ts": r["ts"]}
    inflow = [r for r in rows if r["ev"] in ("TRANSFER_IN", "PROGRAM_IN") and r["qty"] > 0 and not _bad(r)
              and str(r["loc"]).startswith("wallet:")]
    in_by_tx = {}
    for r in inflow:
        in_by_tx.setdefault(txk(r["sid"]), []).append(r)
    claimed = set()
    of_bridge = {p9: a9 for p9, a9 in of_bridge.items() if isinstance(a9, dict) and a9.get("gid") not in ctx.skip
                 and a9.get("key") not in skip_pids and p9 not in skip_pids}
    for a9 in of_bridge.values():
        if a9.get("key") is not None:
            claimed.add(a9["key"])
    out_pid = {}
    legs_tf = {}
    pid_ns = {}
    for r in rows:
        if r["ev"] == "TRANSFER_OUT" and str(r["loc"]).startswith("out:") and r["qty"] > 0 and not _bad(r):
            t9, d9, s9 = txk(r["sid"]), r["loc"].split(":", 2)[2] if r["loc"].count(":") >= 2 else "?", ctx.sym(r["gid"], r.get("sym"))
            out_pid[r["pid"]] = (t9, d9, s9, r["qty"])
            legs_tf.setdefault((t9, OM.family(s9)), []).append((r["pid"], d9, r["qty"]))
            pid_ns[r["pid"]] = str(r["loc"]).split(":", 2)[1]

    def _fit_dests(legs9, amt9, sym9):
        tot9 = {}
        for _p9, d9, q9 in legs9:
            tot9[d9] = tot9.get(d9, Decimal(0)) + q9
        return {d9 for d9, q9 in tot9.items() if OM.qty_fits(q9, amt9, sym9)} | {d9 for _p9, d9, q9 in legs9 if OM.qty_fits(q9, amt9, sym9)}

    def _alloc(legs9, ds9, sym9):
        cap9 = {}
        for _p9, d9, q9 in legs9:
            cap9[d9] = cap9.get(d9, Decimal(0)) + q9
        hi9 = Decimal(1) + Decimal("1e-9")
        fit9 = [_fit_dests(legs9, _d(d.get("amt")), sym9) for d in ds9]
        if not all(fit9):
            return None
        own9 = [None] * len(ds9)
        todo9 = list(range(len(ds9)))
        moved9 = True
        while moved9 and todo9:
            moved9 = False
            for i9 in list(todo9):
                a9 = _d(ds9[i9].get("amt"))
                c9 = [k9 for k9 in fit9[i9] if a9 is not None and a9 <= cap9.get(k9, Decimal(0)) * hi9]
                if not c9:
                    return None
                if len(c9) == 1:
                    own9[i9] = c9[0]
                    cap9[c9[0]] -= a9
                    todo9.remove(i9)
                    moved9 = True
        if todo9:
            return None
        if len(ds9) > 1 and _alt_alloc(legs9, ds9, sym9, own9):
            return None
        return own9

    def _alt_alloc(legs9, ds9, sym9, own9):
        n9 = len(ds9)
        if n9 > 12:
            return True
        cap9 = {}
        for _p9, d9, q9 in legs9:
            cap9[d9] = cap9.get(d9, Decimal(0)) + q9
        hi9 = Decimal(1) + Decimal("1e-9")
        am9 = [_d(d.get("amt")) for d in ds9]
        for m9 in range(1, 1 << n9):
            s9 = [i9 for i9 in range(n9) if m9 >> i9 & 1]
            if len(s9) < 2:
                continue
            tot9 = sum((am9[i9] for i9 in s9), Decimal(0))
            for x9 in _fit_dests(legs9, tot9, sym9):
                if all(own9[i9] == x9 for i9 in s9):
                    continue
                left9 = dict(cap9)
                left9[x9] = left9.get(x9, Decimal(0)) - tot9
                if left9[x9] * hi9 < -abs(tot9) * Decimal("1e-9"):
                    continue
                rest9 = [i9 for i9 in range(n9) if i9 not in s9]
                if all(any(am9[i9] <= left9.get(k9, Decimal(0)) * hi9 for k9 in _fit_dests(legs9, am9[i9], sym9)) for i9 in rest9):
                    return True
        return False

    def _fit_deps(t, sym, me_dest, legs9):
        f9 = OM.family(sym)
        all9 = [d for d in dep_by_tx.get(t, ()) if OM.family(d.get("cur")) == f9]
        ds9 = [d for d in all9 if _d(d.get("amt")) is not None]
        unk9 = [d for d in all9 if _d(d.get("amt")) is None]
        if me_dest is None or not ds9 or me_dest not in {d9 for _p9, d9, _q9 in legs9 or ()}:
            return []
        if len({d9 for _p9, d9, _q9 in legs9}) == 1:
            return ds9 + unk9
        if unk9:
            return []
        own9 = _alloc(legs9, ds9, sym)
        mine9 = [d for d, o9 in zip(ds9, own9 or ()) if o9 == me_dest]
        return mine9 + unk9 if mine9 else []

    def _sum_deps(ds9):
        if not ds9:
            return None
        tss = [d.get("ts") for d in ds9 if isinstance(d.get("ts"), (int, float))]
        ams = [_d(d.get("amt")) for d in ds9]
        return {"ts": max(tss) if len(tss) == len(ds9) else None, "amt": sum(ams, Decimal(0)) if all(a9 is not None for a9 in ams) else None,
                "ex": ds9[0].get("ex")}

    def leg_dep(pid, t, sym):
        me9 = out_pid.get(pid)
        return _sum_deps(_fit_deps(t, sym, me9[1] if me9 else None, legs_tf.get((t, OM.family(sym))) or []))

    if proof_sends is None:
        proof_sends = [{"pid": p9, "txn": v9[0], "dest": v9[1], "sym": v9[2], "qty": v9[3], "chain": pid_ns.get(p9)} for p9, v9 in out_pid.items()]

    def _pf_fake(s9):
        return s9.get("gid") in ctx.skip or s9.get("pid") in skip_pids
    pf_legs = {}
    for s9 in proof_sends or ():
        if isinstance(s9, dict) and s9.get("pid") is not None and _d(s9.get("qty")) is not None and _d(s9.get("qty")) > 0 and not _pf_fake(s9):
            pf_legs.setdefault((txk(s9.get("txn")), OM.family(s9.get("sym"))), []).append((s9["pid"], str(s9.get("dest")), _d(s9.get("qty"))))
    txid_dest = set()
    for s9 in proof_sends or ():
        if not isinstance(s9, dict) or _pf_fake(s9) or s9.get("ok") is False:
            continue
        m9 = of_match.get(s9.get("pid"))
        if not (isinstance(m9, dict) and m9.get("basis") == "txid" and m9.get("uuid")):
            continue
        t9, f9 = txk(s9.get("txn")), OM.family(s9.get("sym"))
        legs9 = pf_legs.get((t9, f9)) or []
        if _fit_deps(t9, s9.get("sym"), str(s9.get("dest")), legs9):
            txid_dest.add(str(s9.get("dest")))
    nok_pid = {s9.get("pid") for s9 in proof_sends or () if isinstance(s9, dict) and s9.get("ok") is False}
    _lst = {}

    def listed(pid):
        me9 = out_pid.get(pid)
        if me9 is None or deposit_exchange is None:
            return False
        k9 = (pid_ns.get(pid), me9[1])
        if k9 not in _lst:
            try:
                _lst[k9] = bool(deposit_exchange(k9[0], k9[1]))
            except Exception:
                _lst[k9] = False
        return _lst[k9]

    def addr_proven(pid):
        me9 = out_pid.get(pid)
        return bool(me9) and (me9[1] in txid_dest or listed(pid))

    def _norm_a(a):
        a = str(a or "").strip()
        return a.lower() if a.startswith("0x") else a

    def strong_dep(pid, t, sym):
        if pid in nok_pid:
            return False
        m9 = of_match.get(pid)
        bs9 = m9.get("basis") if isinstance(m9, dict) else None
        if bs9 == "hop_split":
            return True
        if bs9 == "address":
            return m9.get("how") == "list" or addr_proven(pid)
        if bs9 == "amount_time":
            d9 = dep_by_uuid.get((m9.get("ex"), m9.get("uuid"))) or {}
            me9 = out_pid.get(pid)
            return bool(me9) and ((d9.get("origin_from") and _norm_a(d9.get("origin_from")) == _norm_a(me9[1])) or addr_proven(pid))
        return bool(leg_dep(pid, t, sym))
    proven_dest = {(v9[0], v9[1]) for p9, v9 in out_pid.items() if strong_dep(p9, v9[0], v9[2])}
    rej_dep = set()
    rej_wd = set()

    def arr_of(t, sym, wd_uuid=None, dst=None, ex_dest=False, mine=False, qty=None):
        f = OM.family(sym)
        dn = _norm_a(dst)
        q, where = Decimal(0), None
        for r in in_by_tx.get(t, ()) if t else ():
            if dn and _norm_a(str(r["loc"]).split(":", 2)[-1]) != dn:
                continue
            if OM.family(ctx.sym(r["gid"], r.get("sym"))) == f:
                q += r["qty"]
                where = where or ctx.where(r["loc"])
                claimed.add(r["pid"])
        used9 = set()
        for d in dep_by_tx.get(t, ()) if t and (not dn or ex_dest) else ():
            if OM.family(d.get("cur")) == f and _d(d.get("amt")) is not None:
                q += _d(d.get("amt"))
                used9.add(str(d.get("uuid")))
                where = where or EX_KO.get(d.get("ex"), d.get("ex"))
        for du in xf_by_wd.get(str(wd_uuid), ()) if wd_uuid is not None else ():
            if str(du) in used9:
                continue
            xl9 = xf_dep.get(str(du)) or {}
            if dn and not (ex_dest or mine) and not (xl9.get("rule") == "addr" or (xl9.get("rule") == "hop" and _norm_a(xl9.get("via")) == dn)):
                continue
            for (ex9, u9), dp in dep_post.items():
                if u9 == du and OM.family(ctx.sym(dp["gid"], dp.get("sym"))) == f:
                    q += dp["qty"]
                    used9.add(str(du))
                    where = where or ctx.where(dp["loc"])
        if where is None and t and ex_dest and _d(qty) is not None:
            all9 = [d for d in dep_by_tx.get(t, ()) if _d(d.get("amt")) is not None]
            if len(all9) == 1 and OM.qty_fits(_d(qty), _d(all9[0].get("amt")), sym):
                q, where = _d(all9[0].get("amt")), EX_KO.get(all9[0].get("ex"), all9[0].get("ex"))
        return (q, where) if where is not None else (None, None)

    wd_n = {}
    for e in transit or ():
        if isinstance(e, dict) and e.get("state") != "cancel":
            t9 = txk(e.get("txid_raw") or (e.get("txid") if not str(e.get("txid") or "").startswith("amt:") else ""))
            if t9:
                k9 = (t9, OM.family(e.get("sym") or ctx.sym(e.get("gid"))))
                wd_n[k9] = wd_n.get(k9, 0) + 1
    for e in transit or ():
        if not isinstance(e, dict) or e.get("state") == "cancel":
            continue
        ts = int(e.get("ts") or 0)
        frm = int(e.get("start") or ts)
        if ts < lo:
            continue
        gid, q = e.get("gid"), _d(e.get("qty")) or Decimal(0)
        sym = e.get("sym") or ctx.sym(gid)
        src = e.get("src") or EX_KO.get(e.get("ex"), e.get("ex"))
        t = txk(e.get("txid_raw") or (e.get("txid") if not str(e.get("txid") or "").startswith("amt:") else ""))
        eid = f"WD|{e.get('ex')}|{e.get('uuid')}"
        wev = "EX_WITHDRAW" if e.get("ex") == "upbit" else "EXF_WITHDRAW"
        net = str(e.get("net") or "")
        dst = e.get("dst") or (f"외부 {short(e.get('addr'))}" if e.get("addr") else "받는 곳 모름")
        if (f"{e.get('ex')}:withdraw", e.get("uuid")) in offc_ids:
            out.append(_ev(ctx, eid, ts, "out", "internal", wev, "offchain_self", gid, q, sym, net, src, "내 다른 계정", t, "own_acct",
                           {"st": "none", "exp": EXP_NORMAL}))
            continue
        st = e.get("state")
        fee = float(_d(e.get("fee"))) if _d(e.get("fee")) is not None else None
        ex_dest = bool(e.get("own") and (e.get("cls") == "exchange" or e.get("verdict") == "exchange"))
        aq, aw = arr_of(t, sym, e.get("uuid"), e.get("addr"), ex_dest, bool(e.get("own") or e.get("cls") == "wallet_untracked"), q) \
            if st == "arrived" else (None, None)
        if aw is not None and wd_n.get((t, OM.family(sym)), 0) > 1:
            aq = None
        if st == "arrived" and e.get("why") != "amount" and aw is None:
            st = "pending"
            rej_wd.add(str(e.get("uuid")))
        if st == "arrived" and e.get("why") == "amount" and not e.get("addr"):
            st = "pending"
        if e.get("verdict") == "external" or e.get("why") == "external":
            out.append(_ev(ctx, eid, ts, "out", "external", wev, "verdict:external", gid, q, sym, net, src, dst, t, "exchange_wd"))
        elif st == "arrived" and e.get("why") == "amount" and e.get("addr") and not e.get("own") and e.get("cls") != "wallet_untracked":
            out.append(_ev(ctx, eid, ts, "out", "external", wev, "unknown_addr_amount", gid, q, sym, net, src, dst, t, "exchange_wd"))
        elif st == "arrived":
            out.append(_ev(ctx, eid, ts, "out", "internal", wev, f"arrived:{e.get('why') or 'txid'}", gid, q, sym, net, src,
                           aw or dst, t, "exchange_wd", {"st": "arrived", "ts": max(ts, int(e["arr_ts"])) if isinstance(e.get("arr_ts"), (int, float)) and e["arr_ts"] > 0
                                                          else None,
                                                          "qty": float(aq) if aq is not None else None,
                                                          "fee": fee, "exp": EXP_NORMAL, "from": frm, "where": aw or e.get("dst")}))
        elif e.get("own") or e.get("cls") == "wallet_untracked":
            amb = e.get("why") in ("txid_ambiguous", "amount_ambiguous") or e.get("cls") == "wallet_untracked"
            out.append(_ev(ctx, eid, ts, "out", "internal", wev, f"own:{e.get('cls') or e.get('verdict')}", gid, q, sym, net, src, dst, t,
                           "exchange_wd", {"st": "none" if amb else "pending", "exp": EXP_NORMAL, "fee": fee, "from": frm}))
        elif e.get("addr"):
            out.append(_ev(ctx, eid, ts, "out", "external", wev, "unknown_addr", gid, q, sym, net, src, dst, t, "exchange_wd"))
        else:
            out.append(_ev(ctx, eid, ts, "out", "internal", wev, "no_addr", gid, q, sym, net, src, "받는 곳 모름", t, "exchange_wd_noaddr",
                           {"st": "pending" if st in ("pending", "out") else "none", "exp": EXP_NORMAL, "from": frm}))
    agg = {}
    for r in rows:
        if r["ts"] < lo or r["ev"] not in EV_ALL:
            continue
        k = (r["ev"], r["ns"], r["sid"], r["gid"], r["loc"], r.get("ak"))
        a = agg.get(k)
        if a is None:
            agg[k] = a = dict(r, qty=Decimal(0), pids=[])
        a["qty"] += r["qty"]
        a["pids"].append(r["pid"])
    sends = sorted((a for a in agg.values() if a["ev"] in EV_SEND), key=lambda a: (a["ts"], str(a["sid"])))
    for a in sends:
        ev, q, gid, ch = a["ev"], a["qty"], a["gid"], a["ns"]
        sym = ctx.sym(gid, a.get("sym"))
        eid = _eid(a)
        t = txk(a["sid"])
        if gid in ctx.skip or any(p9 in skip_pids for p9 in a["pids"]):
            out.append(_ev(ctx, eid, a["ts"], "out", "ignore", ev, "quarantined", gid, q, sym, ch, ctx.where(a["loc"]), "", t))
            continue
        if ev == "TRANSFER_OUT":
            if not str(a["loc"]).startswith("out:") or q <= 0:
                continue
            dest = a["loc"].split(":", 2)[2] if a["loc"].count(":") >= 2 else "?"
            row = by_addr.get(dest) or {}
            status = row.get("status") or "pending"
            pid = a["pids"][0] if len(a["pids"]) == 1 else next((p for p in a["pids"] if p in of_match or p in of_bridge), a["pids"][0])
            m, b = of_match.get(pid), of_bridge.get(pid)
            ok_dep = strong_dep(pid, t, sym) or (t, dest) in proven_dest
            if isinstance(m, dict) and not ok_dep:
                rej_dep.update(str(u9) for u9 in ([m.get("uuid")] if m.get("uuid") else []) + list(m.get("uuids") or ()))
                m = None
            tm = tx_match.get((dest, str(a["sid"]), sym)) or {}
            dl = {"multi": "여러 수령처", "?": "수령처 모름"}.get(dest) or f"외부 {short(dest)}"
            wl = next((b["loc"] for b in agg.values() if b["ev"] == ev and b["sid"] == a["sid"] and b["ns"] == ch
                       and str(b["loc"]).startswith("wallet:")), None)
            src = ctx.where(wl) if wl else ctx.cname(ch)
            if (dest, sym) in phantom:
                out.append(_ev(ctx, eid, a["ts"], "out", "ignore", ev, "phantom_token", gid, q, sym, ch, src, dl, t))
            elif status == "external" or row.get("verdict") == "external":
                out.append(_ev(ctx, eid, a["ts"], "out", "external", ev, "verdict:external", gid, q, sym, ch, src, row.get("alias") or dl, t))
            elif isinstance(b, dict):
                bs9 = [of_bridge.get(p9) for p9 in dict.fromkeys(a["pids"])]
                ks9 = [x9.get("key") if isinstance(x9, dict) else None for x9 in bs9]
                bs9 = [x9 for i9, x9 in enumerate(bs9) if not (isinstance(x9, dict) and x9.get("key") is not None and x9.get("key") in ks9[:i9])]
                bqs = [_d(x9.get("qty")) if isinstance(x9, dict) else None for x9 in bs9]
                bts = [x9.get("ts") if isinstance(x9, dict) else None for x9 in bs9]
                bfs9 = {OM.family(ctx.sym(x9.get("gid"), x9.get("sym")) if x9.get("gid") is not None else x9.get("sym"))
                        for x9 in bs9 if isinstance(x9, dict)}
                bq = sum(bqs, Decimal(0)) if all(x9 is not None for x9 in bqs) and len(bfs9) == 1 else None
                bt = max(bts) if all(isinstance(x9, (int, float)) and x9 > 0 for x9 in bts) else None
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "bridge_match", gid, q, sym, ch, src,
                               f"{ctx.cname(b.get('chain'))} 지갑", t, "bridge",
                               {"st": "arrived", "ts": int(bt) if bt is not None else None, "qty": float(bq) if bq is not None else None,
                                "sym": ctx.sym(b.get("gid"), b.get("sym")) if b.get("gid") is not None else b.get("sym"),
                                "where": f"{ctx.cname(b.get('chain'))} 지갑", "exp": EXP_BRIDGE}))
            elif isinstance(m, dict):
                if m.get("basis") == "hop_split":
                    hs9 = [dep_by_uuid.get((m.get("ex"), u9)) for u9 in dict.fromkeys(m.get("uuids") or ())]
                    dep = _sum_deps(hs9) if hs9 and all(isinstance(d9, dict) and OM.family(d9.get("cur")) == OM.family(sym) for d9 in hs9) else None
                elif m.get("basis") == "txid":
                    dep = leg_dep(pid, t, sym)
                else:
                    us9 = [((of_match.get(p9) or {}).get("ex"), (of_match.get(p9) or {}).get("uuid")) if isinstance(of_match.get(p9), dict) else (None, None)
                           for p9 in dict.fromkeys(a["pids"])]
                    ds9 = [dep_by_uuid.get(k9) for k9 in dict.fromkeys(us9) if k9[1]]
                    if ds9 and len(ds9) == len(dict.fromkeys(us9)) and all(isinstance(d9, dict) for d9 in ds9):
                        dep = _sum_deps(ds9)
                        if dep is not None and any(OM.family(d9.get("cur")) != OM.family(sym) for d9 in ds9):
                            dep = dict(dep, amt=None)
                    elif any(isinstance(d9, dict) for d9 in ds9):
                        dep = {"ts": None, "amt": None, "ex": m.get("ex")}
                    else:
                        dep = leg_dep(pid, t, sym)
                exn = EX_KO.get((dep or {}).get("ex") or m.get("ex"), (dep or {}).get("ex") or m.get("ex") or "거래소")
                arr = ({"st": "arrived", "ts": int(dep["ts"]) if isinstance(dep.get("ts"), (int, float)) else None,
                        "qty": float(_d(dep.get("amt")) or 0) or None, "where": exn, "exp": EXP_NORMAL}
                       if dep else ({"st": "arrived", "ts": None, "qty": None, "where": exn, "exp": EXP_NORMAL}
                                    if m.get("basis") in ("amount_time", "hop_split") else {"st": "pending", "where": exn, "exp": EXP_NORMAL}))
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, f"deposit_{m.get('basis') or 'txid'}", gid, q, sym, ch, src, exn, t, "exchange", arr))
            elif tm.get("basis") in ("sale", "roundtrip"):
                out.append(_ev(ctx, eid, a["ts"], "out", "ignore", ev, tm["basis"], gid, q, sym, ch, src, dl, t))
            elif status == "returned" and _returned_after(row, a["ts"], ctx.usd(gid, q)):
                out.append(_ev(ctx, eid, a["ts"], "out", "ignore", ev, "returned_after_send", gid, q, sym, ch, src, dl, t))
            elif status == "bridge_matched" and row.get("bridge"):
                bn = (row.get("bridge") or {}).get("name") or "브릿지"
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "bridge_contract", gid, q, sym, ch, src, f"브릿지({bn})", t, "bridge",
                               {"st": "pending", "exp": EXP_BRIDGE}))
            elif status in ("spam", "system") or (status == "exchange_matched" and ok_dep):
                out.append(_ev(ctx, eid, a["ts"], "out", "ignore", ev, f"status:{status}", gid, q, sym, ch, src, dl, t))
            elif status in ("own", "own_restart_needed"):
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "verdict:own", gid, q, sym, ch, src, row.get("alias") or "내 지갑", t, "own",
                               {"st": "none", "exp": EXP_NORMAL}))
            elif status in ("exchange", "exchange_applying"):
                dep = leg_dep(pid, t, sym)
                exn = row.get("exchange") or (EX_KO.get(dep.get("ex"), dep.get("ex")) if dep else "내 거래소")
                arr = {"st": "arrived", "ts": int(dep["ts"]) if isinstance(dep.get("ts"), (int, float)) else None,
                       "qty": float(_d(dep.get("amt")) or 0) or None, "where": exn, "exp": EXP_NORMAL} \
                    if dep else {"st": "none", "where": exn, "exp": EXP_NORMAL}
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "verdict:exchange", gid, q, sym, ch, src, exn, t, "exchange", arr))
            elif status == "bridge_untracked":
                bn = (row.get("bridge") or {}).get("name") or "브릿지"
                out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "bridge_contract", gid, q, sym, ch, src, f"브릿지({bn})", t, "bridge",
                               {"st": "pending", "exp": EXP_BRIDGE, "untracked": True}))
            else:
                out.append(_ev(ctx, eid, a["ts"], "out", "external", ev, "unknown_addr", gid, q, sym, ch, src, dl, t))
            continue
        if q >= 0:
            continue
        src = ctx.where(a["loc"])
        if ev == "TRANSFER_SELF":
            rcv = next((b for b in agg.values() if b["ev"] == "TRANSFER_SELF" and b["sid"] == a["sid"] and b["gid"] == gid and b["qty"] > 0), None)
            out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "own_wallet", gid, q, sym, ch, src, ctx.where(rcv["loc"]) if rcv else "내 지갑", t,
                           "self", {"st": "same_tx", "ts": a["ts"], "qty": float(rcv["qty"]) if rcv else None, "exp": EXP_NORMAL}))
            continue
        dep = _sum_deps([d for d in dep_by_tx.get(t, ()) if OM.family(d.get("cur")) == OM.family(sym)])
        if ev == "TRANSFER_OUT_EX" or dep is not None:
            exn = EX_KO.get(dep.get("ex"), dep.get("ex")) if dep else "내 거래소"
            arr = {"st": "arrived", "ts": int(dep["ts"]) if isinstance(dep.get("ts"), (int, float)) else None,
                   "qty": float(_d(dep.get("amt")) or 0) or None, "where": exn, "exp": EXP_NORMAL} \
                if dep else {"st": "pending", "where": exn, "exp": EXP_NORMAL}
            out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "deposit_txid" if dep else "deposit_addr", gid, q, sym, ch, src, exn, t, "exchange", arr))
            continue
        sent = -q
        f = OM.family(sym)

        def fits9(snd, r, sq):
            return (r["pid"] not in claimed and r["ns"] != snd["ns"] and OM.family(ctx.sym(r["gid"], r.get("sym"))) == f
                    and snd["ts"] - 600 <= r["ts"] <= snd["ts"] + BRIDGE_SCAN and sq * Decimal("0.5") <= r["qty"] <= sq * Decimal("1.02"))
        cands = [r for r in inflow if fits9(a, r, sent)]
        hit, amb = None, len(cands) > 1
        if len(cands) == 1:
            rivals = [b9 for b9 in sends if b9 is not a and b9["ev"] == "BRIDGE" and b9["qty"] < 0 and b9["gid"] not in ctx.skip
                      and OM.family(ctx.sym(b9["gid"], b9.get("sym"))) == f and fits9(b9, cands[0], -b9["qty"])
                      and not any(OM.family(d.get("cur")) == f for d in dep_by_tx.get(txk(b9["sid"]), ()))]
            if rivals:
                amb = True
            else:
                hit = cands[0]
        if hit is not None:
            claimed.add(hit["pid"])
            arr = {"st": "arrived", "ts": int(hit["ts"]), "qty": float(hit["qty"]), "sym": ctx.sym(hit["gid"], hit.get("sym")),
                   "where": ctx.where(hit["loc"]), "exp": EXP_BRIDGE}
        elif amb:
            arr = {"st": "none", "exp": EXP_BRIDGE, "why": "ambiguous"}
        else:
            arr = {"st": "pending", "exp": EXP_BRIDGE}
        out.append(_ev(ctx, eid, a["ts"], "out", "internal", ev, "bridge_contract", gid, q, sym, ch, src,
                       ctx.where(hit["loc"]) if hit is not None else "브릿지", t, "bridge", arr))
    for a in sorted((a for a in agg.values() if a["ev"] in EV_IN + EV_DEP), key=lambda a: (a["ts"], str(a["sid"]))):
        ev, q, gid, ch = a["ev"], a["qty"], a["gid"], a["ns"]
        if q <= 0:
            continue
        sym = ctx.sym(gid, a.get("sym"))
        eid = _eid(a)
        dst = ctx.where(a["loc"])
        if gid in ctx.skip or any(p9 in skip_pids for p9 in a["pids"]):
            out.append(_ev(ctx, eid, a["ts"], "in", "ignore", ev, "quarantined", gid, q, sym, ch, "", dst, a["sid"]))
            continue
        if ev in EV_DEP:
            ex = str(ch).split(":", 1)[0]
            d = dep_by_uuid.get((ex, a["sid"])) or {}
            t = txk(d.get("txn"))
            if (f"{ex}:deposit", a["sid"]) in offc_ids:
                cls, basis = "internal", "offchain_self"
            elif str(a["sid"]) in xf_dep and str((xf_dep.get(str(a["sid"])) or {}).get("wd_uuid")) not in rej_wd:
                cls, basis = "internal", "xfer_link"
            elif t and t in wd_tx and str(wd_tx[t].get("uuid")) not in rej_wd:
                cls, basis = "internal", "wd_arrival"
            elif d.get("origin_mine"):
                cls, basis = "internal", "origin_mine"
            elif t and any(s["ev"] in ("TRANSFER_OUT_EX", "BRIDGE", "TRANSFER_OUT") and txk(s["sid"]) == t for s in sends):
                cls, basis = "internal", "deposit_txid"
            elif str(a["sid"]) not in rej_dep and any(isinstance(m, dict) and m.get("ex") == ex and (m.get("uuid") == a["sid"] or a["sid"] in (m.get("uuids") or ()))
                                                      for m in of_match.values()):
                cls, basis = "internal", "deposit_match"
            else:
                cls, basis = "external", "unknown_in"
            out.append(_ev(ctx, eid, a["ts"], "in", cls, ev, basis, gid, q, sym, ch, "", dst, t))
            continue
        t = txk(a["sid"])
        if t in wd_tx and str(wd_tx[t].get("uuid")) not in rej_wd:
            cls, basis = "internal", "wd_arrival"
        elif any(p in claimed for p in a["pids"]):
            cls, basis = "internal", "bridge_arrival"
        elif ev == "STAKE_REWARD":
            cls, basis = "external", "reward"
        else:
            cls, basis = "external", "unknown_in"
        out.append(_ev(ctx, eid, a["ts"], "in", cls, ev, basis, gid, q, sym, ch, "", dst, t))
    for a in agg.values():
        if a["ev"] not in EV_ADJ or not a["qty"]:
            continue
        gid, q = a["gid"], a["qty"]
        basis = "recon"
        if a["ev"] in ("EX_ADJUST", "EXF_ADJUST") and q < 0:
            db = ((debts or {}).get(a["ns"]) or {}).get(str(a.get("sym") or ctx.sym(gid)).upper())
            if db is not None and -db * Decimal("0.5") <= -q <= -db * Decimal("1.01"):
                basis = "debt"
        out.append(_ev(ctx, _eid(a), a["ts"], "out" if q < 0 else "in", "adjust", a["ev"], basis,
                       gid, q, None, a["ns"], ctx.where(a["loc"]), "", "", "book"))
    for k in krw or ():
        if not isinstance(k, dict) or int(k.get("ts") or 0) < lo:
            continue
        usd = k.get("usd")
        d = {"id": f"KRW|{k.get('kind')}|{k.get('uuid')}", "ts": int(k["ts"]), "sym": "KRW", "qty": abs(float(k.get("krw") or 0)),
             "usd": round(abs(float(usd)), 2) if usd is not None else None, "chain": "", "tx": "", "kind": "bank"}
        if k.get("kind") == "withdraw":
            d.update(dir="out", cls="internal", ev="KRW_WITHDRAW", basis="own_bank", src="업비트", dst="내 은행 계좌", arr={"st": "none", "exp": EXP_NORMAL})
        else:
            d.update(dir="in", cls="external", ev="KRW_DEPOSIT", basis="bank_in", src="내 은행 계좌", dst="업비트")
        out.append(d)
    out.sort(key=lambda d: (d["ts"], d["id"]))
    return out


def rows_from_db(conn, lo_ts) -> list:
    out = []
    q = ("SELECT p.posting_id, p.source_ns, p.source_id, p.event_ts, p.location, p.qty_base, p.leg_kind, p.event, a.decimals,"
         " COALESCE(a.group_id, -a.asset_id), a.symbol, a.address FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
         " WHERE p.event_ts >= ? AND p.event IN (" + ",".join("?" * len(EV_ALL)) + ")"
         " AND p.leg_kind NOT IN ('fee', 'gas') AND p.location NOT LIKE 'lp:%'")
    for pid, ns, sid, ts, loc, qb, lk, ev, dec, gid, sym, adr in conn.execute(q, (int(lo_ts),) + EV_ALL):
        try:
            qty = Decimal(int(qb)) / (Decimal(10) ** int(dec if dec is not None else 18))
        except (TypeError, ValueError, InvalidOperation):
            continue
        out.append({"pid": pid, "ns": ns, "sid": sid, "ts": int(ts), "loc": loc or "", "qty": qty, "lk": lk, "ev": ev, "gid": gid, "sym": sym,
                    "ak": f"{sym or '?'}@{str(adr or 'native').lower()}"})
    return out


def krw_from_db(conn, lo_ts, fx) -> list:
    import json
    from datetime import datetime
    latest = {}
    for kind, uid, rev, pl in conn.execute("SELECT kind, uuid, revision, payload FROM raw_ex WHERE exchange='upbit' AND kind IN ('deposit', 'withdraw')"):
        if (kind, uid) not in latest or int(rev) > latest[(kind, uid)][0]:
            latest[(kind, uid)] = (int(rev), pl)
    out = []
    for (kind, uid), (_r, pl) in latest.items():
        try:
            o = json.loads(pl)
            if str(o.get("currency") or "").upper() != "KRW":
                continue
            st = str(o.get("state") or "").upper()
            if (kind, st) not in (("deposit", "ACCEPTED"), ("withdraw", "DONE")):
                continue
            ts = datetime.fromisoformat(str(o.get("done_at") or o["created_at"])).timestamp()
            if ts < lo_ts:
                continue
            amt = float(o.get("amount") or 0) + (float(o.get("fee") or 0) if kind == "withdraw" else 0.0)
        except (ValueError, TypeError, KeyError):
            continue
        r = fx(ts) if fx else None
        out.append({"kind": kind, "uuid": uid, "ts": int(ts), "krw": amt, "usd": (amt / r) if r else None})
    return out


def collect(conn, G, px, now, transit=(), of_rows=(), of_match=None, of_bridge=None, deps=(), offc_ids=frozenset(), debts=None,
            skip_gids=frozenset(), names=None, fx=None, xf_links=None, proof_sends=None, deposit_exchange=None, skip_pids=frozenset()) -> dict:
    lo = float(now) - WINDOW - 3600
    ctx = _Ctx(G, px, now, names, skip_gids)
    rows = rows_from_db(conn, lo)
    krw = krw_from_db(conn, lo, fx)
    return {"v": 1, "builtAt": int(now), "window": WINDOW,
            "ev": classify(rows, ctx, transit, of_rows, of_match, of_bridge, deps, offc_ids, debts, krw, xf_links,
                           proof_sends=proof_sends, deposit_exchange=deposit_exchange, skip_pids=skip_pids)}
