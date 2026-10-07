"""Transfer matching between exchanges and wallets."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from outflow_match import _hash_family, canon_sym, norm_txid

WINDOW = 6 * 3600
WINDOW_ADDR = 48 * 3600
REL_UNKNOWN_FEE = Decimal("0.001")
EXACT = Decimal("1e-8")
LABEL = "연결: 금액·시간 일치 (txid 다름)"
LABEL_ADDR = "연결: 입금주소 일치"
LABEL_HOP = "연결: 개인지갑 경유 ({})"
LABEL_SPLIT = "연결: 분할 입금 합계 일치"
MAX_PARTS = 3
MAX_POOL = 60
MAX_HOP_PARTS = 6
MAX_HOP_POOL = 20


def _dec(s):
    try:
        d = Decimal(str(s).strip())
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _qty_ok(dep_s, amt_s, fee_s) -> bool:
    dep, amt = _dec(dep_s), _dec(amt_s)
    if dep is None or amt is None or dep <= 0 or amt <= 0:
        return False
    fee = _dec(fee_s) if fee_s not in (None, "") else None
    if fee is None:
        return dep <= amt and amt - dep <= amt * REL_UNKNOWN_FEE
    return any(c > 0 and abs(dep - c) <= EXACT for c in (amt, amt - fee))


def match(withdraws, deposits, onchain_txids=frozenset(), linked_dep_uuids=frozenset(), off=frozenset(), dest_of=None,
          origin_of=None, own_wallets=frozenset()):
    return _match(withdraws, deposits, onchain_txids, linked_dep_uuids, off, dest_of, origin_of, own_wallets)[0]


def _own(own_wallets, w) -> bool:
    if callable(own_wallets):
        return bool(own_wallets(w))
    return norm_addr(w.get("address")) in own_wallets


def norm_addr(a) -> str:
    a = str(a or "").strip()
    return a.lower() if a.startswith("0x") else a


def short(a) -> str:
    a = str(a or "")
    return a if len(a) <= 12 else a[:6] + "…" + a[-4:]


def _sum_ok(parts, amt_s, fee_s) -> bool:
    amt = _dec(amt_s)
    if amt is None or amt <= 0 or any(_dec(p) is None for p in parts):
        return False
    tot = sum((_dec(p) for p in parts), Decimal(0))
    fee = _dec(fee_s) if fee_s not in (None, "") else Decimal(0)
    tol = EXACT * len(parts)
    return any(c > 0 and abs(tot - c) <= tol for c in (amt, amt - (fee or Decimal(0))))


def _subset_matches(items, amount_of, amt_s, fee_s, kmin, kmax, limit=2):
    amt = _dec(amt_s)
    if amt is None or amt <= 0:
        return []
    fee = _dec(fee_s) if fee_s not in (None, "") else Decimal(0)
    targets = [c for c in (amt, amt - (fee or Decimal(0))) if c > 0]
    vals = []
    for it in items:
        v = _dec(amount_of(it))
        if v is None or v <= 0:
            return []
        vals.append((v, it))
    vals.sort(key=lambda t: t[0])
    top = max(targets) + EXACT * kmax
    out = []

    def dfs(start, k, tot, pick):
        if len(out) >= limit:
            return
        if k >= kmin and any(abs(tot - c) <= EXACT * k for c in targets):
            out.append(tuple(pick))
            if len(out) >= limit:
                return
        if k == kmax:
            return
        for i in range(start, len(vals)):
            v, it = vals[i]
            if tot + v > top:
                break
            pick.append(it)
            dfs(i + 1, k + 1, tot + v, pick)
            pick.pop()
            if len(out) >= limit:
                return
    dfs(0, 0, Decimal(0), [])
    return out


def _match(withdraws, deposits, onchain_txids=frozenset(), linked_dep_uuids=frozenset(), off=frozenset(), dest_of=None,
           origin_of=None, own_wallets=frozenset()):
    wd_tx = {norm_txid(w.get("txid")) for w in withdraws if w.get("txid")}
    dep_tx = {norm_txid(d.get("txid")) for d in deposits if d.get("txid")}
    W, D = [], []
    for w in withdraws:
        t = norm_txid(w.get("txid")) if w.get("txid") else ""
        if w["uuid"] in off or (t and (t in dep_tx or t in onchain_txids)):
            continue
        if w.get("address") and _own(own_wallets, w):
            continue
        ts = _ts(w.get("created_at")) or _ts(w.get("done_at"))
        if ts is None:
            continue
        dest = None
        if dest_of is not None and w.get("address"):
            try:
                dest = dest_of(w) or None
            except Exception:
                dest = None
        W.append((w, t, ts, canon_sym(w.get("currency")), dest))
    for d in deposits:
        t = norm_txid(d.get("txid")) if d.get("txid") else ""
        if d["uuid"] in off or d["uuid"] in linked_dep_uuids or (t and (t in wd_tx or t in onchain_txids)):
            continue
        ts = _ts(d.get("done_at")) or _ts(d.get("created_at"))
        if ts is not None:
            D.append((d, t, ts, canon_sym(d.get("currency"))))
    W.sort(key=lambda x: (x[2], x[0]["uuid"]))
    D.sort(key=lambda x: (x[2], x[0]["uuid"]))
    by_sym = {}
    for x in D:
        by_sym.setdefault(x[3], []).append(x)

    def fam_ok(wt, dt):
        fw9, fd9 = _hash_family(wt), _hash_family(dt)
        return not (fw9 and fd9 and fw9 != fd9)

    def link(w, wt, d, rule, dt9, **extra):
        lab = {"addr": LABEL_ADDR, "amt": LABEL, "hop": LABEL_HOP.format(short(extra.get("via"))), "split": LABEL_SPLIT}[rule]
        return dict({"key": wt or ("amt:" + w["uuid"]), "rule": rule, "label": lab, "wd_uuid": w["uuid"], "wd_ex": w["exchange"],
                     "dep_ex": d["exchange"], "sym": canon_sym(d.get("currency")), "qty": str(d.get("amount")), "dt": int(dt9)}, **extra)

    fits_w, fits_d = {}, {}
    for w, wt, wts, ws, dest in W:
        for d, dt, dts, ds in by_sym.get(ws, ()):
            if w["exchange"] == d["exchange"]:
                continue
            if dest is not None and d["exchange"] != dest:
                continue
            rule = "addr" if dest is not None else "amt"
            if not (0 <= dts - wts <= (WINDOW_ADDR if rule == "addr" else WINDOW)) or not fam_ok(wt, dt):
                continue
            if not _qty_ok(d.get("amount"), w.get("amount"), w.get("fee")):
                continue
            fits_w.setdefault(w["uuid"], []).append(d)
            fits_d.setdefault(d["uuid"], []).append((w, wt, rule, dts - wts))
    out = {}
    for d_uuid, cands in sorted(fits_d.items()):
        if any(c[2] == "addr" for c in cands):
            cands = [c for c in cands if c[2] == "addr"]
        if len(cands) != 1:
            continue
        w, wt, rule, dt9 = cands[0]
        if len(fits_w.get(w["uuid"], ())) != 1:
            continue
        out[d_uuid] = link(w, wt, fits_w[w["uuid"]][0], rule, dt9)
    used_w = {v["wd_uuid"] for v in out.values()}
    used_d = set(out)

    if origin_of is not None:
        hop = {}
        for w, wt, wts, ws, dest in W:
            if w["uuid"] in used_w or dest is not None or not w.get("address"):
                continue
            x = norm_addr(w["address"])
            ds = [(d, dt, dts) for d, dt, dts, _s in by_sym.get(ws, ())
                  if d["uuid"] not in used_d and 0 <= dts - wts <= WINDOW_ADDR and origin_of(d) == x]
            if not ds:
                continue
            if _sum_ok([d.get("amount") for d, _t, _s in ds], w.get("amount"), w.get("fee")):
                hop[w["uuid"]] = (w, wt, wts, x, ds)
            elif len(ds) <= MAX_HOP_POOL:
                sub = _subset_matches(ds, lambda t9: t9[0].get("amount"), w.get("amount"), w.get("fee"), 1, MAX_HOP_PARTS)
                if len(sub) == 1:
                    hop[w["uuid"]] = (w, wt, wts, x, sorted(sub[0], key=lambda t9: (t9[2], t9[0]["uuid"])))
        claimed = {}
        for wu, (w, wt, wts, x, ds) in hop.items():
            for d, _t, _s in ds:
                claimed.setdefault(d["uuid"], set()).add(wu)
        for wu, (w, wt, wts, x, ds) in sorted(hop.items()):
            if any(len(claimed[d["uuid"]]) != 1 for d, _t, _s in ds):
                continue
            for d, _t, dts in ds:
                out[d["uuid"]] = link(w, wt, d, "hop", dts - wts, via=x, parts=len(ds))
                used_d.add(d["uuid"])
            used_w.add(wu)

    split = {}
    for w, wt, wts, ws, dest in W:
        if w["uuid"] in used_w or fits_w.get(w["uuid"]):
            continue
        win = WINDOW_ADDR if dest is not None else WINDOW
        pool = [(d, dt, dts) for d, dt, dts, _s in by_sym.get(ws, ())
                if d["uuid"] not in used_d and not fits_d.get(d["uuid"]) and d["exchange"] != w["exchange"]
                and (dest is None or d["exchange"] == dest) and 0 <= dts - wts <= win and fam_ok(wt, dt)]
        if len(pool) < 2 or len(pool) > MAX_POOL:
            continue
        combos = _subset_matches(pool, lambda t9: t9[0].get("amount"), w.get("amount"), w.get("fee"), 2, MAX_PARTS)
        if len(combos) == 1:
            split[w["uuid"]] = (w, wt, wts, tuple(sorted(combos[0], key=lambda t9: (t9[2], t9[0]["uuid"]))))
    claimed = {}
    for wu, (w, wt, wts, c) in split.items():
        for d, _t, _s in c:
            claimed.setdefault(d["uuid"], set()).add(wu)
    for wu, (w, wt, wts, c) in sorted(split.items()):
        if any(len(claimed[d["uuid"]]) != 1 for d, _t, _s in c):
            continue
        for d, _t, dts in c:
            out[d["uuid"]] = link(w, wt, d, "split", dts - wts, parts=len(c))
            used_d.add(d["uuid"])
        used_w.add(wu)
    return out, fits_w, fits_d


def hop_candidates(withdraws, deposits, dest_of=None, own_wallets=frozenset()):
    out = set()
    dd = None
    for w in withdraws:
        a = w.get("address")
        if not a or _own(own_wallets, w):
            continue
        try:
            if dest_of is not None and dest_of(w):
                continue
        except Exception:
            continue
        wts = _ts(w.get("created_at")) or _ts(w.get("done_at"))
        ws = canon_sym(w.get("currency"))
        if wts is None:
            continue
        if dd is None:
            dd = {}
            for d in deposits:
                dts = _ts(d.get("done_at")) or _ts(d.get("created_at"))
                t = norm_txid(d.get("txid")) if d.get("txid") else ""
                if t and dts is not None:
                    dd.setdefault(canon_sym(d.get("currency")), []).append((dts, t))
        for dts, t in dd.get(ws, ()):
            if 0 <= dts - wts <= WINDOW_ADDR:
                out.add(t)
    return out
